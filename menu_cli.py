# menu_cli.py
from typer.testing import CliRunner
from core.cli import app
import os
import logging
from core.utils import setup_logging
from core.session_singleton import shared_session as session

from core.session_singleton import shared_session as session
from core.holdings import HoldingsAnalyzer


setup_logging(logging.INFO)
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
    #session.refresh_all_caches()  # ✅ Initial cache refresh
    print("🔄 Refreshing all caches...")

    

    print("🔄 Initializing application and uploading trades...")
    summary = HoldingsAnalyzer().update_tradebook(session.kite)
    print("\n📊 Tradebook Upload Summary:")
    for key, value in summary.items():
        print(f" - {key.replace('_', ' ').capitalize()}: {value}")

    
    while True:
        print("\n📋 Menu:")
        print("1. List GTT orders")
        print("2. Analyze GTT orders")
        print("3. Analyze Holdings")
        print("4. Analyze ROI Trend")
        print("5. Exit")

        choice = input("Enter your choice: ").strip()

        if choice == "1":
            result = runner.invoke(app, ["list-entry-levels"], catch_exceptions=False)
            print(result.output)
            if result.exception:
                print(f"❌ Exception occurred: {result.exception}")
            if input("\n1.1 Place GTT orders? (y/n): ").lower() == "y":
                result = runner.invoke(app, ["place-gtt-orders"], catch_exceptions=False)
                print(result.output)
                if result.exception:
                    print(f"❌ Exception occurred: {result.exception}")

        elif choice == "2":
            print("\n📉 GTT Orders Below Threshold:")
            result = runner.invoke(app, ["analyze-gtt-variance", "--threshold", "100.0"], catch_exceptions=False)
            print(result.output)

            menu_gtt_summary()

            # result = runner.invoke(app, ["list-duplicate-gtt-symbols"], catch_exceptions=False)
            # print(result.output)

            # result = runner.invoke(app, ["show-total-buy-gtt-amount"], catch_exceptions=False)
            # print(result.output)


            print("\n📌 Sub-options:")
            print("1. Delete GTTs with variance greater than a custom threshold")
            print("2. Adjust GTTs to match a target variance")
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
