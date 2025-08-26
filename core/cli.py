import typer
import json
import os
import logging
import traceback


from core.entry import EntryStrategyManager
from core.gtt_buy import BuyOrderPlanner
from core.gtt_manage import GTTManager
from core.holdings import HoldingsAnalyzer
from core.utils import print_table

app = typer.Typer()
from core.session_singleton import shared_session as session

entry_mgr = EntryStrategyManager()
holdings_analyzer = HoldingsAnalyzer()
GTT_PLAN_CACHE_PATH = "data/gtt_plan_cache.json"

from core.utils import setup_logging
setup_logging(logging.INFO)

# ──────────────── Commands ──────────────── #

@app.command()
def update_tradebook():
    """Update tradebook from Kite."""
    session.refresh_all_caches()
    holdings_analyzer.update_tradebook(session.kite)

@app.command()
def write_roi():
    """Write ROI results to master CSV."""
    session.refresh_all_caches()
    results = []  # Placeholder
    holdings_analyzer.write_roi_results(results)

@app.command()
def check_duplicates():
    """Check for duplicate symbols in entry levels."""
    session.refresh_all_caches()
    scrips = session.get_entry_levels()
    duplicates = entry_mgr.detect_duplicates(scrips)
    if duplicates:
        print("\n⚠️ Duplicate entries found:")
        for symbol in duplicates:
            print(f" - {symbol}")
    else:
        print("\n✅ No duplicate entries found.")

@app.command()
def list_entry_levels(filter_ltp: float = typer.Option(None, help="Filter orders with LTP greater than this value")):
    """List GTT orders based on entry levels and CMP."""
    try:
        entry_levels = session.get_entry_levels()
        duplicates = entry_mgr.detect_duplicates(entry_levels)
        if duplicates:
            print("\n⚠️ Duplicate entries found in entry_levels.csv:")
            print("  " + ", ".join(duplicates))
        else:
            print("\n✅ No duplicate entries found in entry_levels.csv.")

        planner = BuyOrderPlanner(session.kite, session.get_cmp_manager(), holdings=session.get_holdings())
        new_orders = []
        skipped_gtt = []
        skipped_holding = []
        planned_symbols = set()  # 🔁 Track processed symbols

        for scrip in entry_levels:
            try:
                symbol = scrip.get("symbol", "").strip().upper()
                if symbol in planned_symbols:
                    continue  # ✅ Skip duplicate symbol
                plan = planner.generate_plan(scrip)

                for order in plan:
                    if "skip_reason" in order:
                        if order["skip_reason"] == "GTT already exists for symbol":
                            skipped_gtt.append(symbol)
                        elif order["skip_reason"] == "Holding exceeded allocated amount":
                            skipped_holding.append(symbol)
                    else:
                        new_orders.append(order)
                    planned_symbols.add(symbol)  # ✅ Mark symbol as processed

            except Exception as e:
                typer.echo(f"❌ Error generating plan for {symbol}: {e}")

        if skipped_gtt:
            print("\n📌 Skipped - GTT already exists:")
            print("  " + ", ".join(skipped_gtt))

        if skipped_holding:
            print("\n📌 Skipped - Holding exceeded allocated amount:")
            print("  " + ", ".join(skipped_holding))

        session.write_gtt_plan(new_orders)

        if filter_ltp is not None:
            new_orders = [o for o in new_orders if o["ltp"] > filter_ltp]

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
                display_orders,
                ["Symbol", "Order Price", "Trigger Price", "LTP", "Order Amount", "Entry Level"],
                title="📊 New GTT Plan - Entry Level Strategy",
                spacing=6
            )
        else:
            print("\nℹ️ No new GTT plans to display.")

    except Exception as e:
        typer.echo(f"❌ Exception in list_entry_levels: {e}")


@app.command()
def place_gtt_orders():
    """Place GTT orders from cached plan."""
    session.refresh_all_caches()
    new_orders = session.read_gtt_plan()

    if not new_orders:
        print("⚠️ No GTT orders found in cache.")
        return

    planner = BuyOrderPlanner(
        session.kite,
        session.get_cmp_manager(),
        holdings=session.get_holdings(),
        session=session
    )

    print("\n📦 Placing GTT orders...")

    try:
        placed_orders = planner.place_orders(new_orders, dry_run=False)
        print_table(
            placed_orders,
            ["symbol", "price", "trigger", "status", "remarks"],
            title="✅ GTT Order Placement Summary",
            spacing=6
        )
    except Exception as e:
        print(f"❌ Failed to place GTT orders: {e}")
        traceback.print_exc()
        logging.error(f"[ERROR] ❌ Failed to place GTT orders: {e}")

    try:
        session.delete_gtt_plan()
    except Exception as e:
        print(f"⚠️ Failed to delete cache file: {e}")

@app.command()
def analyze_gtt_variance(threshold: float = typer.Option(..., help="Variance threshold to filter GTTs")):
    """Analyze GTT orders below variance threshold."""
    session.refresh_all_caches()
    manager = GTTManager(session.kite, session.get_cmp_manager(), session)
    result = manager.analyze_orders()
    filtered = [o for o in result["orders"] if o["Variance (%)"] < threshold]
    print_table(filtered, ["Symbol", "Trigger Price", "LTP", "Variance (%)"], title="📉 GTT Orders Below Threshold")

@app.command()
def adjust_gtt_orders(target_variance: float = typer.Option(..., help="Target variance to adjust GTTs")):
    """Adjust GTT orders to match target variance."""
    session.refresh_all_caches()
    manager = GTTManager(session.kite, session.get_cmp_manager(), session)
    planner = BuyOrderPlanner(session.kite, session.get_cmp_manager(), holdings=session.get_holdings())
    orders = manager.analyze_gtt_buy_orders()
    to_adjust = [o for o in orders if o["Variance (%)"] < target_variance]

    adjusted_symbols = manager.adjust_orders(to_adjust, target_variance, planner.adjust_trigger_and_order_price)
    print_table(adjusted_symbols, ["Symbol", "Trigger Price", "LTP", "Variance (%)"], title="📉 GTT Orders Adjusted")

@app.command()
def delete_gtt_orders(threshold: float = typer.Option(..., help="Variance threshold above which GTTs will be deleted")):
    """Delete GTT orders above variance threshold."""
    session.refresh_all_caches()
    manager = GTTManager(session.kite, session.get_cmp_manager(), session)
    orders = manager.analyze_gtt_buy_orders()
    to_delete = [o for o in orders if o["Variance (%)"] > threshold]

    deleted = manager.delete_orders_above_variance(to_delete, threshold)

    if deleted:
        print_table(
            [{"Symbol": s, "Status": "Deleted"} for s in deleted],
            ["Symbol", "Status"],
            title="🗑️ Deleted GTTs"
        )
    else:
        print("⚠️ No GTTs were deleted.")

@app.command()
def analyze_gtt_variance(threshold: float = typer.Option(100.0, help="Variance threshold to filter GTTs")):
    """Analyze buy GTT orders and display those below a variance threshold."""
    session.refresh_all_caches()
    manager = GTTManager(session.kite, session.get_cmp_manager(), session)

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
    session.refresh_all_caches()
    manager = GTTManager(session.kite, session.get_cmp_manager(), session)

    duplicates = manager.get_duplicate_gtt_symbols()
    return duplicates

@app.command()
def show_total_buy_gtt_amount(threshold: float = None) -> float:
    """Show total capital required for buy GTT orders."""
    session.refresh_all_caches()
    manager = GTTManager(session.kite, session.get_cmp_manager(), session)
    
    total_amount = manager.get_total_buy_gtt_amount(threshold)
    return total_amount

@app.command()
def analyze_holdings(
    filters: str = typer.Option(None, help="JSON string of filters"),
    sort_by: str = typer.Option("W ROI", help="Column to sort by (e.g., 'ROI/Day', 'P&L')")
):
    """Analyze holdings and display ROI metrics including Weighted ROI."""
    try:
        session.refresh_all_caches()
        parsed_filters = json.loads(filters) if filters else {}
        results = holdings_analyzer.analyze_holdings(
            session.kite,
            session.get_cmp_manager(),
            parsed_filters,
            sort_by=sort_by
        )

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
    except Exception as e:
        print(f"❌ Error analyzing holdings: {e}")


@app.command()
def update_tradebook():
    """Update tradebook from Kite and show summary."""
    session.refresh_all_caches()
    summary = holdings_analyzer.update_tradebook(session.kite)
    print("\n📊 Tradebook Update Summary:")
    for key, value in summary.items():
        print(f" - {key.replace('_', ' ').capitalize()}: {value}")

@app.command
def get_total_invested_amount():
    session.refresh_all_caches()
    holdings = session.get_holdings()
    analyzer = HoldingsAnalyzer()
    total = analyzer.get_total_invested(holdings)
    return {"total_invested": round(total, 2)}

@app.command()
def plan_dynamic_avg():
    """Plan GTT buy orders for dynamic averaging strategy."""
    session.refresh_all_caches()
    from core.dynamic_avg import DynamicAveragingPlanner
    planner = DynamicAveragingPlanner()
    candidates = planner.identify_candidates()
    plan = planner.generate_buy_plan(candidates)

    print_table(
        plan,
        ["symbol", "exchange", "price", "trigger", "qty", "ltp", "strategy", "leg", "entry"],
        title="📉 Dynamic Averaging Buy Plan",
        spacing=6
    )

    if hasattr(planner, "skipped_symbols") and planner.skipped_symbols:
        print_table(
            planner.skipped_symbols,
            ["symbol", "skip_reason"],
            title="⏭️ Skipped Symbols",
            spacing=6
        )

    session.write_gtt_plan(plan)


if __name__ == "__main__":
    app()
