from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
import traceback
import json
import math
import os
import random
import time

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

@app.get("/tax/base-rate")
def get_base_tax_rate(pan: str = Query(..., description="Employee PAN number")):
    try:
        time.sleep(10)
        rate = round(random.uniform(0.10, 0.25), 4)
        return {"pan": pan, "base_tax_rate": rate}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/update-tradebook")
def update_tradebook():
    try:
        session.refresh_all_caches()
        holdings_analyzer.update_tradebook(session.kite)
        return {"message": "Tradebook updated successfully."}
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
def get_entry_level_gtt_plan():
    try:
        session.refresh_all_caches()
        scrips = session.get_entry_levels()
        planner = BuyOrderPlanner(session.kite, session.get_cmp_manager())
        all_orders = []
        for scrip in scrips:
            plan = planner.generate_plan(scrip)
            all_orders.extend(plan)

        def sanitize(v):
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                return None
            return v

        sanitized_orders = [{k: sanitize(v) for k, v in o.items()} for o in all_orders]
        session.write_gtt_plan(sanitized_orders)

        return {"new_orders": sanitized_orders}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e), "trace": traceback.format_exc()})

@app.post("/gtt-orders/place")
def place_cached_gtt_orders():
    try:
        session.refresh_all_caches()
        new_orders = session.read_gtt_plan()
        if not new_orders:
            return JSONResponse(status_code=400, content={"error": "No GTT orders found in cache."})

        planner = BuyOrderPlanner(session.kite, session.get_cmp_manager())
        planner.place_orders(new_orders, dry_run=False)

        session.delete_gtt_plan()

        return {
            "message": f"{len(new_orders)} GTT orders placed successfully.",
            "placed_orders": [{"symbol": o["symbol"], "price": o["price"]} for o in new_orders]
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e), "trace": traceback.format_exc()})

@app.get("/gtt-orders/variance")
def analyze_gtt_variance(threshold: float = Query(..., description="Variance threshold to filter GTTs")):
    try:
        session.refresh_all_caches()
        manager = GTTManager(session.kite, session.get_cmp_manager(), session)
        result = manager.analyze_orders()
        filtered = [o for o in result["orders"] if o["Variance (%)"] < threshold]
        return {
            "threshold": threshold,
            "total_filtered": len(filtered),
            "filtered_orders": filtered,
            "duplicate_symbols": result["duplicates"],
            "total_amount": result["total_amount"]
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e), "trace": traceback.format_exc()})

@app.post("/gtt-orders/adjust")
def adjust_gtt_orders(target_variance: float = Query(..., description="Target variance to adjust GTTs")):
    try:
        session.refresh_all_caches()
        manager = GTTManager(session.kite, session.get_cmp_manager(), session)
        planner = BuyOrderPlanner(session.kite, session.get_cmp_manager())
        result = manager.analyze_orders()
        to_adjust = [o for o in result["orders"] if o["Variance (%)"] < target_variance]
        if not to_adjust:
            return {"message": "No GTTs found below the specified variance threshold.", "adjusted": []}
        modified = manager.adjust_orders(to_adjust, target_variance, planner.adjust_trigger_and_order_price)
        return {"message": "Adjustment completed.", "adjusted_symbols": modified}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e), "trace": traceback.format_exc()})

@app.delete("/gtt-orders/delete")
def delete_gtt_orders(threshold: float = Query(..., description="Variance threshold above which GTTs will be deleted")):
    try:
        session.refresh_all_caches()
        manager = GTTManager(session.kite, session.get_cmp_manager(), session)
        result = manager.analyze_orders()
        to_delete = [o for o in result["orders"] if o["Variance (%)"] > threshold]
        if not to_delete:
            return {"message": "No GTTs found above the specified variance threshold.", "deleted": []}
        deleted = manager.delete_orders_above_variance(to_delete, threshold)
        return {"message": "Deletion completed.", "deleted_symbols": deleted}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e), "trace": traceback.format_exc()})

@app.get("/holdings/analyze")
def analyze_holdings_api(request: Request, filters: str = Query(default=None, description="JSON string of filters")):
    try:
        session.refresh_all_caches()
        parsed_filters = {}
        if filters:
            try:
                parsed_filters = json.loads(filters)
            except json.JSONDecodeError as e:
                return JSONResponse(status_code=400, content={"error": f"Invalid JSON in filters: {e}"})
        results = []  # Replace with actual ROI analysis logic
        def sanitize(v): return "NA" if isinstance(v, float) and (math.isnan(v) or math.isinf(v)) else v
        sanitized = [{k: sanitize(v) for k, v in row.items()} for row in results]
        return {"results": sanitized}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e), "trace": traceback.format_exc()})
