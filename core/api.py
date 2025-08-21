from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
import traceback
import json
import math

from core.session_singleton import shared_session as session
from core.entry import EntryStrategyManager
from core.gtt_buy import BuyOrderPlanner
from core.gtt_manage import GTTManager
from core.holdings import HoldingsAnalyzer

app = FastAPI(
    title="Equity Portfolio API",
    description="REST API for managing tradebook, GTT orders, and ROI analysis",
    version="1.0.0"
)

entry_mgr = EntryStrategyManager()
holdings_analyzer = HoldingsAnalyzer()

@app.post("/update-tradebook")
def update_tradebook():
    try:
        session.refresh_all_caches()
        summary = holdings_analyzer.update_tradebook(session.kite)
        return {"message": "Tradebook updated successfully.", "summary": summary}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/write-roi")
def write_roi():
    try:
        session.refresh_all_caches()
        results = []  # Placeholder
        holdings_analyzer.write_roi_results(results)
        return {"message": "ROI results written successfully."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/entry-levels/duplicates")
def check_duplicates():
    try:
        session.refresh_all_caches()
        scrips = session.get_entry_levels()
        duplicates = entry_mgr.detect_duplicates(scrips)
        return {"duplicates": duplicates}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/entry-levels/gtt-plan")
def list_entry_levels(filter_ltp: float = Query(None, description="Filter orders with LTP greater than this value")):
    try:
        session.refresh_all_caches()
        entry_levels = session.get_entry_levels()
        duplicates = entry_mgr.detect_duplicates(entry_levels)

        planner = BuyOrderPlanner(session.kite, session.get_cmp_manager(), holdings=session.get_holdings())
        new_orders, skipped_gtt, skipped_holding = [], [], []
        planned_symbols = set()

        for scrip in entry_levels:
            symbol = scrip.get("symbol", "").strip().upper()
            if symbol in planned_symbols:
                continue
            plan = planner.generate_plan(scrip)
            for order in plan:
                if "skip_reason" in order:
                    if order["skip_reason"] == "GTT already exists for symbol":
                        skipped_gtt.append(symbol)
                    elif order["skip_reason"] == "Holding exceeded allocated amount":
                        skipped_holding.append(symbol)
                else:
                    new_orders.append(order)
                    planned_symbols.add(symbol)

        session.write_gtt_plan(new_orders)

        if filter_ltp is not None:
            new_orders = [o for o in new_orders if o["ltp"] > filter_ltp]

        return {
            "duplicates": duplicates,
            "skipped_gtt": skipped_gtt,
            "skipped_holding": skipped_holding,
            "new_orders": new_orders
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e), "trace": traceback.format_exc()})

@app.post("/gtt-orders/place")
def place_gtt_orders():
    try:
        session.refresh_all_caches()
        new_orders = session.read_gtt_plan()
        if not new_orders:
            return JSONResponse(status_code=400, content={"error": "No GTT orders found in cache."})

        planner = BuyOrderPlanner(session.kite, session.get_cmp_manager(), holdings=session.get_holdings(), session=session)
        placed_orders = planner.place_orders(new_orders, dry_run=False)
        session.delete_gtt_plan()

        return {
            "message": "GTT orders placed successfully.",
            "placed_orders": placed_orders
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e), "trace": traceback.format_exc()})

@app.get("/gtt-orders/variance")
def analyze_gtt_variance(threshold: float = Query(..., description="Variance threshold to filter GTTs")):
    try:
        session.refresh_all_caches()
        manager = GTTManager(session.kite, session.get_cmp_manager(), session)
        orders = manager.analyze_gtt_buy_orders()
        filtered = [o for o in orders if o["Variance (%)"] <= threshold]
        return {
            "threshold": threshold,
            "filtered_orders": filtered
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/gtt-orders/adjust")
def adjust_gtt_orders(target_variance: float = Query(..., description="Target variance to adjust GTTs")):
    try:
        session.refresh_all_caches()
        manager = GTTManager(session.kite, session.get_cmp_manager(), session)
        planner = BuyOrderPlanner(session.kite, session.get_cmp_manager(), holdings=session.get_holdings())
        orders = manager.analyze_gtt_buy_orders()
        to_adjust = [o for o in orders if o["Variance (%)"] < target_variance]
        adjusted = manager.adjust_orders(to_adjust, target_variance, planner.adjust_trigger_and_order_price)
        return {"adjusted_orders": adjusted}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.delete("/gtt-orders/delete")
def delete_gtt_orders(threshold: float = Query(..., description="Variance threshold above which GTTs will be deleted")):
    try:
        session.refresh_all_caches()
        manager = GTTManager(session.kite, session.get_cmp_manager(), session)
        orders = manager.analyze_gtt_buy_orders()
        to_delete = [o for o in orders if o["Variance (%)"] > threshold]
        deleted = manager.delete_orders_above_variance(to_delete, threshold)
        return {"deleted_symbols": deleted}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/gtt-orders/duplicates")
def list_duplicate_gtt_symbols():
    try:
        session.refresh_all_caches()
        manager = GTTManager(session.kite, session.get_cmp_manager(), session)
        duplicates = manager.get_duplicate_gtt_symbols()
        return {"duplicates": duplicates}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/gtt-orders/total-buy-amount")
def show_total_buy_gtt_amount(threshold: float = Query(None, description="Optional variance threshold")):
    try:
        session.refresh_all_caches()
        manager = GTTManager(session.kite, session.get_cmp_manager(), session)
        total_amount = manager.get_total_buy_gtt_amount(threshold)
        return {"total_buy_gtt_amount": total_amount}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/holdings/analyze")
def analyze_holdings(filters: str = Query(None, description="JSON string of filters")):
    try:
        session.refresh_all_caches()
        parsed_filters = json.loads(filters) if filters else {}
        results = holdings_analyzer.analyze_holdings(session.kite, session.get_cmp_manager(), parsed_filters)

        for row in results:
            trend = row.get("Trend", "-")
            trend_days = row.get("Trend Days", "")
            row["Trend"] = f"{trend}({trend_days})" if trend_days != "" else trend

        return {"results": results}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
