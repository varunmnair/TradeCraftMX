from .base_broker import BaseBroker
import upstox_client
from upstox_client.rest import ApiException
from core.utils import read_csv, write_csv, get_symbol_from_isin
import os
import requests
import json
import pandas as pd
import logging

from datetime import datetime

class UpstoxBroker(BaseBroker):
    """
    Concrete implementation for Upstox broker using upstox-python-sdk v2.
    """

    def __init__(self, user_id, api_key, api_secret, redirect_uri, code=None, access_token=None):
        super().__init__(user_id)
        self.broker_name = "upstox"
        self.configuration = upstox_client.Configuration()
        self.api_key = api_key
        self.api_secret = api_secret
        self.redirect_uri = redirect_uri
        self.access_token = access_token
        self._trades = []
        self.TRANSACTION_TYPE_BUY = 'BUY'
        self.TRANSACTION_TYPE_SELL = 'SELL'
        self.GTT_TYPE_SINGLE = 'single'
        self.GTT_TYPE_OCO = 'two-leg'
        self.ORDER_TYPE_LIMIT = 'LIMIT'
        self.PRODUCT_CNC = 'CNC'
        self.csv_path = "c:\\Users\\nairv1\\OneDrive - Pegasystems Inc\\code\\pycode\\data\\Name-symbol-mapping.csv"

        # API clients will be initialized after login
        self.login_api = None
        self.order_api = None
        self.portfolio_api = None
        self.market_quote_api = None
        self.history_api = None

    def _get_instrument_key(self, symbol, segment):
        try:
            df = pd.read_csv(self.csv_path)
            df.columns = [col.strip() for col in df.columns]
            symbol_clean = symbol.replace("-BE", "").strip().upper()
            match = df[df['SYMBOL'].str.upper() == symbol_clean]
            if not match.empty:
                isin = match.iloc[0]['ISIN NUMBER']
                if pd.notna(isin) and str(isin).strip():
                    return f"{segment}|{isin.strip()}"
                else:
                    logging.warning(f"Missing ISIN for {symbol_clean}")
            else:
                logging.warning(f"Symbol {symbol_clean} not found in mapping CSV.")
        except Exception as e:
            logging.error(f"Error reading CSV or extracting instrument key: {e}")
        return None

    def login(self):
        """
        Authenticate and establish a session with the broker.
        """
        logging.debug(f"Logging in to Upstox for user {self.user_id}")
        try:
            if not self.access_token:
                raise Exception("Upstox access token not available for login.")

            self.configuration.access_token = self.access_token
            api_client = upstox_client.ApiClient(self.configuration)

            # Initialize the specific API clients
            self.login_api = upstox_client.LoginApi(api_client)
            self.order_api = upstox_client.OrderApi(api_client)
            self.portfolio_api = upstox_client.PortfolioApi(api_client)
            self.market_quote_api = upstox_client.MarketQuoteApi(api_client)
            self.history_api = upstox_client.HistoryApi(api_client)

            logging.debug(f"Successfully logged in to Upstox for user {self.user_id} using existing token.")

        except Exception as e:
            logging.debug(f"Error logging in to Upstox: {e}")
            raise

    def logout(self):
        """
        Log out and terminate the session by revoking the access token.
        """
        logging.debug(f"Logging out from Upstox for user {self.user_id}")
        try:
            if self.login_api:
                self.login_api.revoke_access_token('v2')
                logging.debug("Successfully logged out from Upstox (token revoked).")
        except ApiException as e:
            logging.debug(f"Error logging out from Upstox: {e}")

    def get_holdings(self):
        """
        Retrieve the user's current holdings and transform them into a list of dictionaries
        matching the Zerodha format.
        """
        logging.debug("Getting holdings from Upstox")
        try:
            api_response = self.portfolio_api.get_holdings('v2')
            holdings_data = api_response.data
            #logging.debug(f"holdings_data: {holdings_data}")
            holdings = []
            for item in holdings_data:
                holding_dict = {
                    'tradingsymbol': getattr(item, 'tradingsymbol', None),
                    'exchange': getattr(item, 'exchange', None),
                    'instrument_token': getattr(item, 'instrument_token', None),
                    'isin': getattr(item, 'isin', None),
                    'product': getattr(item, 'product', None),
                    'price': getattr(item, 'price', 0),
                    'quantity': getattr(item, 'quantity', 0),
                    'used_quantity': getattr(item, 'used_quantity', 0),
                    't1_quantity': getattr(item, 't1_quantity', 0),
                    'realised_quantity': getattr(item, 'realised_quantity', 0),
                    'authorised_quantity': getattr(item, 'authorised_quantity', 0),
                    'authorised_date': getattr(item, 'authorised_date', None),
                    'authorisation': {},
                    'opening_quantity': getattr(item, 'opening_quantity', 0),
                    'short_quantity': 0,
                    'collateral_quantity': getattr(item, 'collateral_quantity', 0),
                    'collateral_type': getattr(item, 'collateral_type', ''),
                    'discrepancy': getattr(item, 'discrepancy', False),
                    'average_price': getattr(item, 'average_price', 0),
                    'last_price': getattr(item, 'last_price', 0),
                    'close_price': getattr(item, 'close_price', 0),
                    'pnl': getattr(item, 'pnl', 0),
                    'day_change': getattr(item, 'day_change', 0),
                    'day_change_percentage': getattr(item, 'day_change_percentage', 0),
                    'mtf': {'quantity': 0, 'used_quantity': 0, 'average_price': 0, 'value': 0, 'initial_margin': 0}
                }
                holdings.append(holding_dict)
            #logging.debug(f"Holdings: {holdings}")
            return holdings
        except ApiException as e:
            logging.debug(f"Error getting holdings from Upstox: {e}")
            return []

    def _get_gtt_headers(self):
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    def get_gtt_orders(self):
        """
        Retrieve the user's Good Till Triggered (GTT) orders.
        """
        logging.debug("Getting GTT orders from Upstox")
        try:
            url = "https://api.upstox.com/v3/order/gtt"
            headers = self._get_gtt_headers()
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            gtc_data = response.json().get('data', [])
            #logging.debug(f"gtc_data: {gtc_data}")
            
            gtt_orders = []
            for g in gtc_data:
                # Find the ENTRY rule and discard others
                entry_rule = None
                if 'rules' in g and isinstance(g['rules'], list):
                    for rule in g['rules']:
                        if rule.get('strategy') == 'ENTRY':
                            entry_rule = rule
                            break
                
                # If no ENTRY rule is found, skip this record
                if not entry_rule:
                    continue

                # Combine original GTC data with the entry rule data
                processed_data = g.copy()
                processed_data.update(entry_rule)

                # Format dates
                def format_timestamp(ts):
                    if not isinstance(ts, int) or ts < 0:
                        return None
                    try:
                        # Assuming timestamp is in microseconds
                        return datetime.fromtimestamp(ts / 1000000).strftime('%Y-%m-%d %H:%M:%S')
                    except (ValueError, TypeError, OSError):
                        return None

                created_at = format_timestamp(processed_data.get('created_at'))
                expires_at = format_timestamp(processed_data.get('expires_at'))
                # The user's desired format has updated_at. Let's use created_at as a fallback.
                updated_at = format_timestamp(processed_data.get('updated_at', processed_data.get('created_at')))


                # Transform status
                status = processed_data.get('status')
                if status == 'SCHEDULED':
                    status = 'active'

                # Trim _EQ from exchange
                exchange = processed_data.get('exchange')
                if exchange and exchange.endswith('_EQ'):
                    exchange = exchange[:-3]

                # Build the final nested order dictionary
                order = {
                    'id': processed_data.get('gtt_order_id'),
                    'user_id': self.user_id,
                    'parent_trigger': None,
                    'type': processed_data.get('type', 'single'),
                    'created_at': created_at,
                    'updated_at': updated_at,
                    'expires_at': expires_at,
                    'status': status,
                    'condition': {
                        'exchange': exchange,
                        'last_price': None,  # Not available from Upstox GTT list API
                        'tradingsymbol': processed_data.get('trading_symbol'),
                        'trigger_values': [processed_data.get('trigger_price')],
                        'instrument_token': processed_data.get('instrument_token')
                    },
                    'orders': [{
                        'exchange': exchange,
                        'tradingsymbol': processed_data.get('trading_symbol'),
                        'product': 'CNC',  # Assuming CNC, as product is not in Upstox GTT response
                        'order_type': 'LIMIT',  # Assuming LIMIT, as order_type is not in Upstox GTT response
                        'transaction_type': processed_data.get('transaction_type'),
                        'quantity': processed_data.get('quantity'),
                        'price': processed_data.get('trigger_price'), # price is not in the root, but trigger_price is. Assuming this is what's wanted.
                        'result': None
                    }],
                    'meta': {}
                }
                gtt_orders.append(order)

            #logging.debug(f"GTT Orders: {gtt_orders}")
            return gtt_orders
            
        except requests.exceptions.RequestException as e:
            logging.debug(f"Error getting GTT orders from Upstox: {e}")
            return []

    def place_gtt(self, **kwargs):
        """
        Place a single-leg GTT order.
        Handles both Upstox-style and Zerodha-style arguments.
        """
        if 'instrument_token' in kwargs and 'transaction_type' in kwargs and 'quantity' in kwargs and 'trigger_price' in kwargs:
            # Upstox-style arguments
            instrument_token = kwargs['instrument_token']
            transaction_type = kwargs['transaction_type']
            quantity = kwargs['quantity']
            trigger_price = kwargs['trigger_price']
        else:
            # Zerodha-style arguments
            tradingsymbol = kwargs['tradingsymbol']
            exchange = kwargs['exchange']
            segment = f"{exchange.upper()}_EQ"
            instrument_token = self._get_instrument_key(tradingsymbol, segment)
            if not instrument_token:
                raise Exception(f"Could not find instrument key for {tradingsymbol}")

            orders = kwargs['orders']
            transaction_type = orders[0]['transaction_type']
            quantity = orders[0]['quantity']
            trigger_values = kwargs['trigger_values']
            trigger_price = trigger_values[0]

        order_details = {
            "type": "SINGLE",
            "quantity": int(quantity),
            "product": "D",  # Assuming Delivery
            "rules": [
                {
                    "strategy": "ENTRY",
                    "trigger_type": "BELOW", # This might need to be configurable
                    "trigger_price": round(float(trigger_price))
                }
            ],
            "instrument_token": instrument_token,
            "transaction_type": transaction_type.upper()
        }
        return self.place_gtt_order(order_details)

    def place_gtt_order(self, order_details):
        """
        Place a GTT order.
        """
        #logging.debug(f"Placing GTT order in Upstox: {order_details}")
        try:
            url = "https://api.upstox.com/v3/order/gtt/place"
            headers = self._get_gtt_headers()
            response = requests.post(url, headers=headers, data=json.dumps(order_details))
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logging.error(f"Error placing GTT order in Upstox: {e}")
            if e.response is not None:
                logging.error(f"Response body: {e.response.text}")
            raise

    def modify_gtt(self, order_id, order_details):
        """
        Modify an existing GTT order.
        """
        logging.debug(f"Modifying GTT in Upstox: {order_id}")
        try:
            url = f"https://api.upstox.com/v2/gtt/orders/{order_id}"
            headers = self._get_gtt_headers()
            response = requests.put(url, headers=headers, data=json.dumps(order_details))
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logging.debug(f"Error modifying GTT in Upstox: {e}")
            raise

    def cancel_gtt(self, order_id):
        """
        Cancel a GTT order.
        """
        logging.debug(f"Cancelling GTT in Upstox: {order_id}")
        try:
            url = "https://api.upstox.com/v3/order/gtt/cancel"
            headers = self._get_gtt_headers()
            payload = {'gtt_order_id': order_id}
            response = requests.delete(url, headers=headers, data=json.dumps(payload))
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logging.debug(f"Error cancelling GTT in Upstox: {e}")
            raise

    def get_trades(self):
        """
        Retrieve the user's trades from the trade book.
        """
        file_path = f"data/{self.user_id}_trade_book.csv"
        logging.debug(f"Getting trades from {file_path} for Upstox")
        if os.path.exists(file_path):
            self._trades = read_csv(file_path)
        return self._trades

    def trades(self):
        """
        Retrieve the user's trades from the broker's API and format them
        to match the Zerodha broker's trade structure.
        """
        logging.debug("Getting trades from Upstox API")
        try:
            api_response = self.order_api.get_trade_history('v2')
            upstox_trades = api_response.data
            formatted_trades = []
            for trade in upstox_trades:
                
                def parse_datetime(date_str):
                    if not date_str:
                        return None
                    
                    # List of possible formats
                    formats_to_try = [
                        '%Y-%m-%dT%H:%M:%S',  # ISO format
                        '%Y-%m-%d %H:%M:%S',  # Space separated
                    ]

                    # Pre-process string to handle variations
                    date_str = date_str.replace('Z', '')
                    if '.' in date_str:
                        date_str = date_str.split('.')[0]

                    for fmt in formats_to_try:
                        try:
                            return datetime.strptime(date_str, fmt)
                        except (ValueError, TypeError):
                            continue
                    
                    # If all formats fail, log a warning and return the original string
                    logging.warning(f"Could not parse datetime string '{date_str}' with known formats.")
                    return date_str

                def format_time(date_obj):
                     if not date_obj or not isinstance(date_obj, datetime):
                        return None
                     return date_obj.strftime('%H:%M:%S')

                product_mapping = {'D': 'CNC', 'I': 'MIS'} # Add other mappings if needed
                
                order_timestamp_dt = parse_datetime(trade.order_timestamp)

                tradingsymbol = trade.tradingsymbol
                instrument_token = trade.instrument_token
                if instrument_token and instrument_token.startswith('NSE_EQ') and not tradingsymbol.endswith('-EQ'):
                    tradingsymbol += '-EQ'

                formatted_trade = {
                    'account_id': self.user_id,
                    'trade_id': trade.trade_id,
                    'order_id': trade.order_id,
                    'exchange': trade.exchange,
                    'tradingsymbol': tradingsymbol,
                    'instrument_token': instrument_token,
                    'product': product_mapping.get(trade.product, trade.product),
                    'average_price': trade.average_price,
                    'quantity': trade.quantity,
                    'exchange_order_id': trade.exchange_order_id,
                    'transaction_type': trade.transaction_type,
                    'fill_timestamp': parse_datetime(trade.exchange_timestamp),
                    'order_timestamp': format_time(order_timestamp_dt),
                    'exchange_timestamp': parse_datetime(trade.exchange_timestamp)
                }
                formatted_trades.append(formatted_trade)
            return formatted_trades
        except ApiException as e:
            logging.debug(f"Error getting trades from Upstox API: {e}")
            return []

    def place_order(self, order_details):
        """
        Place an order with the broker.
        """
        logging.debug(f"Placing order in Upstox: {order_details}")
        try:
            body = upstox_client.PlaceOrderRequest(
                quantity=order_details['quantity'],
                product=order_details['product'],
                validity=order_details['validity'],
                price=order_details.get('price', 0.0),
                instrument_token=order_details['instrument_token'],
                order_type=order_details['order_type'],
                transaction_type=order_details['transaction_type'],
                disclosed_quantity=order_details.get('disclosed_quantity', 0),
                trigger_price=order_details.get('trigger_price', 0.0),
                is_amo=order_details.get('is_amo', False)
            )
            api_response = self.order_api.place_order(body, 'v2')
            return api_response.data
        except ApiException as e:
            logging.debug(f"Error placing order in Upstox: {e}")
            raise

    def load_entry_levels(self, file_path):
        """
        Load entry levels from a broker-specific file.
        """
        logging.debug(f"Loading entry levels from {file_path} for Upstox")
        if os.path.exists(file_path):
            return read_csv(file_path)
        return []

    def update_roi_master(self, data):
        """
        Update the ROI master file for the broker.
        """
        file_path = f"data/{self.user_id}_roi_master.csv"
        logging.debug(f"Updating ROI master file for Upstox: {file_path}")
        write_csv(file_path, data)

    def update_trade_book(self, data):
        """
        Update the trade book master file for the broker.
        """
        file_path = f"data/{self.user_id}_trade_book.csv"
        logging.debug(f"Updating trade book for Upstox: {file_path}")
        write_csv(file_path, data)

    def download_historical_trades(self, start_date, end_date):
        """
        Download historical trades from Upstox API.
        """
        logging.debug(f"Downloading historical trades for user {self.user_id} from {start_date} to {end_date}")
        all_trades = []
        page_number = 1
        page_size = 500  # As per Upstox API docs, max page size is 500

        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.access_token}'
        }

        while True:
            url = f"https://api.upstox.com/v2/charges/historical-trades?start_date={start_date}&end_date={end_date}&page_size={page_size}&page_number={page_number}"
            
            try:
                response = requests.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()

                if data.get('status') != 'success':
                    logging.error(f"Error from Upstox API: {data.get('errors')}")
                    break

                trades = data.get('data', [])
                if not trades:
                    break

                all_trades.extend(trades)

                meta_data = data.get('meta_data', {})
                total_pages = meta_data.get('page', {}).get('total_pages', 1)

                if page_number >= total_pages:
                    break

                page_number += 1

            except requests.exceptions.RequestException as e:
                logging.error(f"Error downloading historical trades from Upstox: {e}")
                break
        
        # Transform data
        transformed_trades = []
        for trade in all_trades:
            transformed_trade = {
                'symbol': get_symbol_from_isin(trade.get('isin')),
                'isin': trade.get('isin'),
                'trade_date': trade.get('trade_date'),
                'exchange': trade.get('exchange'),
                'segment': trade.get('segment'),
                'series': trade.get('segment'),  # As per user mapping
                'trade_type': trade.get('transaction_type'),
                'auction': 'FALSE',
                'quantity': trade.get('quantity'),
                'price': trade.get('price'),
                'trade_id': trade.get('trade_id'),
                'order_id': 'NA',
                'order_execution_time': 'NA'
            }
            transformed_trades.append(transformed_trade)
        
        return transformed_trades
