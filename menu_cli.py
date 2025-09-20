# menu_cli.py
from typer.testing import CliRunner
from core.cli import app, set_current_session # Added set_current_session
import os
import logging
import argparse
from datetime import datetime, timedelta
from core.utils import setup_logging, write_csv
from core.session import SessionCache # Changed from session_singleton
from core.session_manager import SessionManager
from core.holdings import HoldingsAnalyzer
from brokers.broker_factory import BrokerFactory

parser = argparse.ArgumentParser(description='TradeCraftX CLI')
parser.add_argument(
    '--log-level',
    default='INFO',
    choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
    help='Set the logging level (default: INFO)'
)
args = parser.parse_args()
setup_logging(args.log_level.upper())
runner = CliRunner()

from core.cli import list_duplicate_gtt_symbols, show_total_buy_gtt_amount

def menu_gtt_summary():
    duplicates = list_duplicate_gtt_symbols()
    if duplicates:
        print("\n🔁 Duplicate GTT Symbols:")
        for symbol in duplicates:
            print(f" - {symbol}")
    else:
        print("✅ No duplicate GTT symbols found.")

    threshold = 5
    total_amount = show_total_buy_gtt_amount(threshold)
    print(f"💰 Total Buy GTT Amount Required (variance ≤ {threshold}%): ₹{total_amount}")

def main_menu():
    print("Please select a broker:")
    print("1. Zerodha (default)")
    print("2. Upstox")
    broker_choice = input("Enter your choice (1 or 2): ").strip()

    session_manager = SessionManager()
    session = SessionCache(session_manager=session_manager) # Initialize SessionCache here
    set_current_session(session) # Set the global session in core.cli
    config = {}

    if broker_choice == '2':
        broker_name = 'upstox'
        config['api_key'] = session_manager.upstox_api_key
        config['api_secret'] = session_manager.upstox_api_secret
        config['redirect_uri'] = session_manager.upstox_redirect_uri
        # For Upstox, the 'code' is part of the login flow, handled by get_valid_upstox_access_token
        config['access_token'] = session_manager.get_valid_upstox_access_token()
        us = "32ADGT"
    else:
        broker_name = 'zerodha'
        config['api_key'] = session_manager.kite_api_key
        config['access_token'] = session_manager.get_valid_kite_access_token()
        us = "NM9165"

    user_id = input(f"Enter User ID for {broker_name} (default: {us}): ").strip() or us

    try:
        session.broker = BrokerFactory.get_broker(broker_name, user_id, config)
        session.broker.login()

        if broker_name == 'upstox':
            if input("Upload trades for the last 400 days? (y/n, default: n): ").lower() == 'y':
                end_date = datetime.now()
                start_date = end_date - timedelta(days=600)
                
                end_date_str = end_date.strftime('%Y-%m-%d')
                start_date_str = start_date.strftime('%Y-%m-%d')

                result = runner.invoke(app, ["download-historical-trades", "--start-date", start_date_str, "--end-date", end_date_str], catch_exceptions=False)
                print(result.output)
                if result.exception:
                    print(f"❌ Exception occurred: {result.exception}")

    except Exception as e:
        print(f"❌ Failed to initialize or use broker: {e}")
        return

    print("🔄 Refreshing all caches...")
    session.refresh_all_caches()

    print("🔄 Initializing application and uploading trades...")
    summary = HoldingsAnalyzer(user_id, broker_name).update_tradebook(session.broker)
    summary_str = " - ".join([f"{key.replace('_', ' ').capitalize()}: {value}" for key, value in summary.items()])
    print(f"\n📊 Tradebook Upload Summary: {summary_str}")

    while True:
        print("\n📋 Menu:")
        print("1. List Entry Startegies")
        print("2. Analyze Entry orders")
        print("3. Analyze Holdings")
        print("4. Analyze ROI Trend")
        print("5. Exit")

        choice = input("Enter your choice: ").strip()

        if choice == "1":
            result = runner.invoke(app, ["list-entry-levels"], catch_exceptions=False)
            print(result.output)
            if result.exception:
                print(f"❌ Exception occurred: {result.exception}")

            if input("\n1.1 Place Multi Level Entry orders? (y/n): ").lower() == "y":
                result = runner.invoke(app, ["place-gtt-orders"], catch_exceptions=False)
                print(result.output)
                if result.exception:
                    print(f"❌ Exception occurred: {result.exception}")

            result = runner.invoke(app, ["plan-dynamic-avg"], catch_exceptions=False)
            print(result.output)
            if result.exception:
                print(f"❌ Exception occurred: {result.exception}")

            if input("\n1.2 Place Dynamic Averaging Entry orders? (y/n): ").lower() == "y":
                result = runner.invoke(app, ["place-dynamic-averaging-orders"], catch_exceptions=False)
                print(result.output)
                if result.exception:
                    print(f"❌ Exception occurred: {result.exception}")

        elif choice == "2":
            result = runner.invoke(app, ["analyze-gtt-variance", "--threshold", "100.0"], catch_exceptions=False)
            print(result.output)

            menu_gtt_summary()

            print("\n📌 Sub-options:")
            print("1. Delete entry orders with variance greater than a custom threshold")
            print("2. Adjust entry orders to match a target variance")
            sub_choice = input("Enter your sub-option (1/2 or press Enter to skip): ").strip()

            if sub_choice == "1":
                delete_threshold = input("Enter variance threshold for deletion (e.g., 0.1): ").strip()
                if delete_threshold:
                    result = runner.invoke(app, ["delete-gtt-orders", "--threshold", delete_threshold], catch_exceptions=False)
                    print(result.output)
                    if result.exception:
                        print(f"❌ Exception occurred: {result.exception}")

            elif sub_choice == "2":
                target_variance = input("Enter target variance (e.g., -3): ").strip()
                result = runner.invoke(app, ["adjust-gtt-orders", "--target-variance", target_variance], catch_exceptions=False)
                print(result.output)
                if result.exception:
                    print(f"❌ Exception occurred: {result.exception}")

        elif choice == "3":
            try:
                filter_expr = input("Enter filter expression or leave blank: ").strip()
                args = ["analyze-holdings"]
                if filter_expr:
                    args += ["--filters", filter_expr]
                result = runner.invoke(app, args, catch_exceptions=False)
                print(result.output)
                if result.exception:
                    print(f"❌ Exception occurred: {result.exception}")

                while True:
                    print("\n🔍 Sort by:")
                    print("1. ROI per day")
                    print("2. Weighted ROI")
                    sub_choice = input("Enter your choice (1/2 or press Enter to go back to main menu): ").strip()

                    if not sub_choice:
                        break

                    sort_key = ""
                    if sub_choice == "1":
                        sort_key = "roi_per_day"
                    elif sub_choice == "2":
                        sort_key = "weighted_roi"
                    else:
                        print("⚠️ Invalid choice. Please try again.")
                        continue

                    if sort_key:
                        sort_args = args + ["--sort-by", sort_key]
                        result = runner.invoke(app, sort_args, catch_exceptions=False)
                        print(result.output)

            except Exception as e:
                print(f"❌ Error analyzing holdings: {e}")

        elif choice == "4":
            result = runner.invoke(app, ["write-roi"])
            print(result.output)

        elif choice == "5":
            print("👋 Exiting workflow.")
            break

        else:
            print("⚠️ Invalid choice. Please try again.")

if __name__ == "__main__":
    main_menu()