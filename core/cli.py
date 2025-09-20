import typer
import json
import os
import logging
import traceback

from core.entry import detect_duplicates
from core.multilevel_entry import MultiLevelEntryStrategy
from core.gtt_manage import GTTManager
from core.holdings import HoldingsAnalyzer
from core.utils import print_table

app = typer.Typer()

current_session = None

def set_current_session(s):
    global current_session
    current_session = s

def get_holdings_analyzer():
    if current_session:
        if hasattr(current_session, 'broker'):
            if current_session.broker:
                broker = current_session.broker
                has_user_id = hasattr(broker, 'user_id')
                has_broker_name = hasattr(broker, 'broker_name')
                logging.debug(f"get_holdings_analyzer: broker has user_id: {has_user_id}, broker_name: {has_broker_name}")
                if has_user_id and has_broker_name:
                    return HoldingsAnalyzer(broker.user_id, broker.broker_name)
    logging.info("get_holdings_analyzer: returning None")
    return None

GTT_PLAN_CACHE_PATH = "data/gtt_plan_cache.json"

from core.utils import setup_logging
setup_logging(logging.INFO)

# ──────────────── Commands ──────────────── #

@app.command()
def write_roi():
    """Write ROI results to master CSV."""
    current_session.refresh_all_caches()
    results = []  # Placeholder
    holdings_analyzer = get_holdings_analyzer()
    if holdings_analyzer:
        holdings_analyzer.write_roi_results(results)

@app.command()
def check_duplicates():
    """Check for duplicate symbols in entry levels."""
    current_session.refresh_all_caches()
    scrips = current_session.get_entry_levels()
    duplicates = detect_duplicates(scrips)
    if duplicates:
        print("\n⚠️ Duplicate entries found:")
        for symbol in duplicates:
            print(f" - {symbol}")
    else:
        print("\n✅ No duplicate entries found.")

@app.command()
def list_entry_levels(filter_ltp: float = typer.Option(None, help="Filter orders with LTP greater than this value")):
    """List GTT orders based on multi-level entry strategy."""
    try:
        current_session.refresh_all_caches()
        
        duplicates = detect_duplicates(current_session.get_entry_levels())
        if duplicates:
            print("\n⚠️ Duplicate entries found in entry_levels.csv:")
            print("  " + ", ".join(duplicates))
        else:
            print("\n✅ No duplicate entries found in entry_levels.csv.")

        # 1. Instantiate the planner with the new signature
        planner = MultiLevelEntryStrategy(
            broker=current_session.broker,
            cmp_manager=current_session.get_cmp_manager(),
            holdings=current_session.get_holdings(),
            entry_levels=current_session.get_entry_levels(),
            gtt_cache=current_session.get_gtt_cache()
        )

        # 2. Identify candidates and generate the plan
        candidates = planner.identify_candidates()
        new_orders = planner.generate_plan(candidates)
        skipped_orders = planner.skipped_orders

        # 3. Display skipped orders
        # if skipped_orders:
        #     display_skipped = [{"Symbol": o["symbol"], "Skip Reason": o["skip_reason"]} for o in skipped_orders]
        #     print_table(
        #         sorted(display_skipped, key=lambda item: item['Symbol']),
        #         ["Symbol", "Skip Reason"],
        #         title="📌 Skipped Multi-Level Entry Symbols",
        #         spacing=6
        #     )

        # 4. Write plan to cache
        current_session.write_gtt_plan(new_orders)

        # 5. Filter and display the plan
        if filter_ltp is not None:
            new_orders = [o for o in new_orders if o.get("ltp") and o["ltp"] > filter_ltp]

        if new_orders:
            display_orders = []
            for order in new_orders:
                order_amount = round(order["price"] * order["qty"], 2)
                display_orders.append({
                    "Symbol": order["symbol"],
                    "Order Price": order["price"],
                    "Trigger Price": order["trigger"],
                    "LTP": order["ltp"],
                    "Order Amount": order_amount,
                    "Entry Level": order["entry"]
                })

            print_table(
                sorted(display_orders, key=lambda item: item['Symbol']),
                ["Symbol", "Order Price", "Trigger Price", "LTP", "Order Amount", "Entry Level"],
                title="📊 New GTT Plan - Multi-Level Entry Strategy",
                spacing=6
            )
        else:
            print("\nℹ️  No Multi-Level Entry plans to display.")

    except Exception as e:
        typer.echo(f"❌ Exception in list_entry_levels: {e}")
        traceback.print_exc()


@app.command()
def place_gtt_orders():
    """Place GTT orders from cached plan."""
    current_session.refresh_all_caches()
    new_orders = current_session.read_gtt_plan()

    if not new_orders:
        logging.debug("No GTT orders found in cache.")
        return

    manager = GTTManager(current_session.broker, current_session.get_cmp_manager(), current_session)

    print("\n📦 Placing GTT orders...")

    try:
        placed_orders = manager.place_orders(new_orders, dry_run=False)
        print_table(
            placed_orders,
            ["symbol", "price", "trigger", "status"],
            title="✅ GTT Order Placement Summary",
            spacing=6
        )
    except Exception as e:
        print(f"❌ Failed to place GTT orders: {e}")
        traceback.print_exc()
        logging.error(f"[ERROR] ❌ Failed to place GTT orders: {e}")

    try:
        current_session.delete_gtt_plan()
    except Exception as e:
        print(f"⚠️ Failed to delete cache file: {e}")

@app.command()
def place_dynamic_averaging_orders():
    """Place GTT orders from cached dynamic averaging plan, deleting existing GTTs for symbols in the plan."""
    current_session.refresh_all_caches()
    new_orders = current_session.read_gtt_plan()  # Assuming plan_dynamic_avg writes to the same cache as list_entry_levels

    if not new_orders:
        print("⚠️ No dynamic averaging GTT orders found in cache.")
        return

    manager = GTTManager(current_session.broker, current_session.get_cmp_manager(), current_session)

    # --- Deletion Logic ---
    new_plan_symbols = {order["symbol"] for order in new_orders}
    if new_plan_symbols:
        all_gtts = current_session.get_gtt_cache()
        symbols_to_delete = []
        for g in all_gtts:
            if g.get("status", "").lower() == "active" and g.get("orders") and g["orders"][0].get("transaction_type") == "BUY":
                symbol = g.get("condition", {}).get("tradingsymbol")
                if symbol and symbol in new_plan_symbols:
                    symbols_to_delete.append(symbol)
        
        symbols_to_delete = list(set(symbols_to_delete))

        if symbols_to_delete:
            logging.debug(f"Attempting to delete existing GTTs for symbols in dynamic averaging plan: {symbols_to_delete}")
            deleted_gtt_symbols = manager.delete_gtts_for_symbols(symbols_to_delete)
            if deleted_gtt_symbols:
                print(f"Successfully deleted existing GTTs for: {', '.join(deleted_gtt_symbols)}")
            else:
                print("No existing GTTs found to delete for the dynamic averaging plan symbols.")
        else:
            print("No active, non-triggered GTTs found for symbols in the new plan. Nothing to delete.")
    # --- End Deletion Logic ---

    print("\n📦 Placing dynamic averaging GTT orders...")

    try:
        placed_orders = manager.place_orders(new_orders, dry_run=False)
        print_table(
            placed_orders,
            ["symbol", "price", "trigger", "status"],
            title="✅ Dynamic Averaging GTT Order Placement Summary",
            spacing=6
        )
    except Exception as e:
        print(f"❌ Failed to place dynamic averaging GTT orders: {e}")
        traceback.print_exc()
        logging.error(f"[ERROR] ❌ Failed to place dynamic averaging GTT orders: {e}")

    try:
        current_session.delete_gtt_plan()  # Clear the cache after placing orders
    except Exception as e:
        print(f"⚠️ Failed to delete cache file: {e}")


@app.command()
def adjust_gtt_orders(target_variance: float = typer.Option(..., help="Target variance to adjust GTTs")):
    """Adjust GTT orders to match target variance."""
    current_session.refresh_all_caches()
    manager = GTTManager(current_session.broker, current_session.get_cmp_manager(), current_session)
    orders = manager.analyze_gtt_buy_orders()
    to_adjust = [o for o in orders if o["Variance (%)"] < target_variance]

    from core.entry import BaseEntryStrategy
    adjusted_symbols = manager.adjust_orders(to_adjust, target_variance, BaseEntryStrategy.adjust_trigger_and_order_price)
    print_table(adjusted_symbols, ["Symbol", "Trigger Price", "LTP", "Variance (%)"])

@app.command()
def delete_gtt_orders(threshold: float = typer.Option(..., help="Variance threshold above which GTTs will be deleted")):
    """Delete GTT orders above variance threshold."""
    current_session.refresh_all_caches()
    manager = GTTManager(current_session.broker, current_session.get_cmp_manager(), current_session)
    orders = manager.analyze_gtt_buy_orders()
    to_delete = [o for o in orders if o["Variance (%)"] > threshold]

    deleted = manager.delete_orders_above_variance(to_delete, threshold)

    if deleted:
        print_table(
            [{"Symbol": s, "Status": "Deleted"} for s in deleted],
            ["Symbol", "Status"],
            title="🗑️ Deleting GTTs"
        )
    else:
        print("⚠️ No GTTs were deleted.")

@app.command()
def analyze_gtt_variance(threshold: float = typer.Option(100.0, help="Variance threshold to filter GTTs")):
    """Analyze buy GTT orders and display those below a variance threshold."""
    current_session.refresh_all_caches()
    manager = GTTManager(current_session.broker, current_session.get_cmp_manager(), current_session)

    orders = manager.analyze_gtt_buy_orders()
    filtered = [o for o in orders if o["Variance (%)"] <= threshold]

    print_table(
        filtered,
        ["Symbol", "Trigger Price", "LTP", "Variance (%)", "Qty", "Buy Amount"],
        title=f"📉 GTT Orders Below Threshold ({threshold}%)"
    )

@app.command()
def list_duplicate_gtt_symbols():
    """List symbols with duplicate GTT orders."""
    current_session.refresh_all_caches()
    manager = GTTManager(current_session.broker, current_session.get_cmp_manager(), current_session)

    duplicates = manager.get_duplicate_gtt_symbols()
    return duplicates

@app.command()
def show_total_buy_gtt_amount(threshold: float = None) -> float:
    """Show total capital required for buy GTT orders."""
    current_session.refresh_all_caches()
    manager = GTTManager(current_session.broker, current_session.get_cmp_manager(), current_session)
    
    total_amount = manager.get_total_buy_gtt_amount(threshold)
    return total_amount

@app.command()
def analyze_holdings(
    filters: str = typer.Option(None, help="JSON string of filters"),
    sort_by: str = typer.Option("W ROI", help="Column to sort by (e.g., 'ROI/Day', 'P&L')")
):
    """Analyze holdings and display ROI metrics including Weighted ROI."""
    logging.debug("Entering analyze_holdings command.")
    logging.debug(f"Filters: {filters}, Sort by: {sort_by}")
    try:
        current_session.refresh_all_caches()
        parsed_filters = json.loads(filters) if filters else {}
        logging.debug("Getting holdings analyzer.")
        holdings_analyzer = get_holdings_analyzer()
        if holdings_analyzer:
            logging.debug("Holdings analyzer obtained. Calling analyze_holdings.")
            results = holdings_analyzer.analyze_holdings(
                current_session.broker,
                current_session.get_cmp_manager(),
                parsed_filters,
                sort_by=sort_by
            )
            logging.debug(f"Received {len(results)} results from analyze_holdings.")

            # 🔧 Format Trend field as 'UP(5)'
            for row in results:
                trend = row.get("Trend", "-")
                trend_days = row.get("Trend Days", "")
                row["Trend"] = f"{trend}({trend_days})" if trend_days != "" else trend

            print_table(
                results,
                ["Symbol", "Invested", "P&L", "Yld/Day", "Age", "P&L%", "ROI/Day", "W ROI", "Trend", "Quality"],
                title="📊 Holdings ROI",
                spacing=6
            )
        else:
            logging.warning("Could not get holdings analyzer.")
    except Exception as e:
        logging.error(f"Error in analyze_holdings command: {e}")
        print(f"❌ Error analyzing holdings: {e}")

@app.command()
def update_tradebook():
    """Update tradebook from broker and show summary."""
    current_session.refresh_all_caches()
    holdings_analyzer = get_holdings_analyzer()
    if holdings_analyzer:
        summary = holdings_analyzer.update_tradebook(current_session.broker)
        print("\n📊 Tradebook Update Summary:")
        for key, value in summary.items():
            print(f" - {key.replace('_', ' ').capitalize()}: {value}")

@app.command()
def get_total_invested_amount():
    current_session.refresh_all_caches()
    holdings = current_session.get_holdings()
    analyzer = get_holdings_analyzer()
    if analyzer:
        total = analyzer.get_total_invested(holdings)
        return {"total_invested": round(total, 2)}

@app.command()
def plan_dynamic_avg():
    """Plan GTT buy orders for dynamic averaging strategy."""
    current_session.refresh_all_caches()
    from core.dynamic_avg import DynamicAveragingPlanner
    planner = DynamicAveragingPlanner(current_session)
    candidates = planner.identify_candidates()
    plan = planner.generate_buy_plan(candidates)

    display_plan = []
    for order in plan:
        display_plan.append({
            "Symbol": order["symbol"],
            "Order Price": order["price"],
            "Trigger Price": order["trigger"],
            "LTP": order["ltp"],
            "Order Amt": round(order["qty"] * order["price"], 2),
            "DA Leg": order["leg"],
            "Entry Level": order["entry"],
        })

    if display_plan:
        print_table(
            sorted(display_plan, key=lambda item: item['Symbol']),
            ["Symbol", "Order Price", "Trigger Price", "LTP", "Order Amt",  "DA Leg", "Entry Level"],
            title="📉 Dynamic Averaging Buy Plan",
            spacing=6
        )
    else:
        print("\nℹ️ No Dynamic Averaging buy plan to display.")


    # if hasattr(planner, "skipped_symbols") and planner.skipped_symbols:
    #     print_table(
    #         sorted(planner.skipped_symbols, key=lambda item: item['symbol']),
    #         ["symbol", "skip_reason"],
    #         title="⏭️ Skipped Symbols",
    #         spacing=6
    #     )

    current_session.write_gtt_plan(plan)

@app.command()
def exit():
    """Exit the application."""
    print("Exiting the application.")
    raise typer.Exit()


if __name__ == "__main__":
    app()

@app.command()
def download_historical_trades(start_date: str = typer.Option(..., help="Start date in YYYY-MM-DD format"), end_date: str = typer.Option(..., help="End date in YYYY-MM-DD format")):
    """Download historical trades from the broker."""
    try:
        holdings_analyzer = get_holdings_analyzer()
        if holdings_analyzer:
            summary = holdings_analyzer.download_historical_trades(current_session.broker, start_date, end_date)
            print(summary.get("message"))
        else:
            print("Could not get holdings analyzer.")
    except Exception as e:
        print(f"❌ Error downloading historical trades: {e}")
