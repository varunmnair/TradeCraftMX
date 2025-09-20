
import os
import pickle
import requests
import webbrowser
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv
from kiteconnect import KiteConnect, exceptions
import logging


load_dotenv()

class SessionManager:
    def __init__(self):
        # Zerodha credentials
        self.kite_api_key = os.getenv("KITE_API_KEY")
        self.kite_api_secret = os.getenv("KITE_API_SECRET")
        self.kite_token_file = "auth/kite_access_token.pkl"

        # Upstox credentials
        self.upstox_api_key = os.getenv("UPSTOX_API_KEY")
        self.upstox_api_secret = os.getenv("UPSTOX_API_SECRET")
        self.upstox_redirect_uri = "http://localhost"
        self.upstox_token_file = "auth/upstox_access_token.pkl"

        os.makedirs(os.path.dirname(self.kite_token_file), exist_ok=True)
        os.makedirs(os.path.dirname(self.upstox_token_file), exist_ok=True)

    # ──────────────── Token Persistence ──────────────── #
    def save_token(self, token: str, token_file: str):
        with open(token_file, "wb") as f:
            pickle.dump(token, f)

    def load_token(self, token_file: str):
        if os.path.exists(token_file):
            with open(token_file, "rb") as f:
                return pickle.load(f)
        return None

    # ──────────────── Zerodha (Kite) ──────────────── #
    def generate_new_kite_token(self, kite: KiteConnect, redirected_url: str = None) -> str:
        if not redirected_url:
            login_url = kite.login_url()
            print(f"🔐 Login URL: {login_url}")
            webbrowser.open(login_url)
            redirected_url = input("📥 Paste the full redirected URL after login: ")
        
        parsed_url = urlparse(redirected_url)
        request_token = parse_qs(parsed_url.query).get("request_token", [None])[0]
        if not request_token:
            raise ValueError("❌ Could not extract request_token from the URL.")
        data = kite.generate_session(request_token, api_secret=self.kite_api_secret)
        access_token = data["access_token"]
        self.save_token(access_token, self.kite_token_file)
        print("✅ New Kite access token generated and saved.")
        return access_token

    def get_valid_kite_access_token(self) -> str:
        """For interactive CLI use. Ensures a valid token exists, or triggers a new login."""
        kite = KiteConnect(api_key=self.kite_api_key)
        is_valid, access_token, _ = self.check_kite_token_validity()
        if is_valid:
            return access_token
        
        print("🔄 Generating a new Kite access token...")
        return self.generate_new_kite_token(kite)

    def check_kite_token_validity(self) -> tuple[bool, str | None, str | None]:
        """
        Checks the validity of the stored Kite token without triggering a new login.
        Returns a tuple: (is_valid, token, login_url).
        """
        kite = KiteConnect(api_key=self.kite_api_key)
        access_token = self.load_token(self.kite_token_file)
        if not access_token:
            print("ℹ️ No Kite token file found.")
            return False, None, kite.login_url()
        try:
            kite.set_access_token(access_token)
            kite.profile()
            logging.debug("✅ Kite access token is valid.")
            return True, access_token, None
        except exceptions.TokenException:
            print("⚠️ Kite access token is invalid or expired.")
            return False, None, kite.login_url()
        except Exception as e:
            print(f"⚠️ An error occurred during Kite token validation: {e}")
            return False, None, kite.login_url()

    # ──────────────── Upstox ──────────────── #
    def generate_new_upstox_token(self, redirected_url: str = None) -> str:
        if not redirected_url:
            login_url = (
                f"https://api.upstox.com/v2/login/authorization/dialog?"
                f"response_type=code&client_id={self.upstox_api_key}&redirect_uri={self.upstox_redirect_uri}"
            )
            print("🔗 Opening Upstox login URL in your browser...")
            webbrowser.open(login_url)
            redirected_url = input("✅ Paste the FULL redirected URL after login:\n")

        code = parse_qs(urlparse(redirected_url).query).get("code", [None])[0]
        if not code:
            raise ValueError("❌ Could not extract authorization code from the URL.")

        token_payload = {
            "code": code,
            "client_id": self.upstox_api_key,
            "client_secret": self.upstox_api_secret,
            "redirect_uri": self.upstox_redirect_uri,
            "grant_type": "authorization_code"
        }
        response = requests.post("https://api.upstox.com/v2/login/authorization/token", data=token_payload)
        response.raise_for_status()
        access_token = response.json().get("access_token")

        if access_token:
            self.save_token(access_token, self.upstox_token_file)
            print("✅ Upstox access token stored.")
            return access_token
        else:
            raise ValueError("❌ Failed to retrieve Upstox access token.")

    def get_valid_upstox_access_token(self) -> str:
        """For interactive CLI use. Ensures a valid token exists, or triggers a new login."""
        is_valid, access_token, _ = self.check_upstox_token_validity()
        if is_valid:
            return access_token

        print("🔄 Generating a new Upstox access token...")
        return self.generate_new_upstox_token()

    def check_upstox_token_validity(self) -> tuple[bool, str | None, str | None]:
        """
        Checks the validity of the stored Upstox token without triggering a new login.
        Returns a tuple: (is_valid, token, login_url).
        """
        access_token = self.load_token(self.upstox_token_file)
        login_url = (
            f"https://api.upstox.com/v2/login/authorization/dialog?"
            f"response_type=code&client_id={self.upstox_api_key}&redirect_uri={self.upstox_redirect_uri}"
        )
        if not access_token:
            print("ℹ️ No Upstox token file found.")
            return False, None, login_url
        try:
            url = "https://api.upstox.com/v2/user/profile"
            headers = {
                'Accept': 'application/json',
                'Authorization': f'Bearer {access_token}'
            }
            response = requests.get(url, headers=headers)
            response.raise_for_status()

            if response.json().get('status') == 'success':
                #print("✅ Upstox access token is valid.")
                return True, access_token, None
            else:
                print("⚠️ Upstox token validation returned a non-success status.")
                return False, None, login_url
        
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                print("⚠️ Upstox access token is invalid or expired.")
            else:
                print(f"⚠️ HTTP error during Upstox token validation: {e}")
            return False, None, login_url
        except Exception as e:
            print(f"⚠️ An error occurred during Upstox token validation: {e}")
            return False, None, login_url
