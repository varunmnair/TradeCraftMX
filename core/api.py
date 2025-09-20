from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
import traceback
import json
import math
from pydantic import BaseModel
from kiteconnect import KiteConnect

from core.session_singleton import shared_session as session
from core.entry import detect_duplicates, BaseEntryStrategy
from core.multilevel_entry import MultiLevelEntryStrategy
from core.gtt_manage import GTTManager
from core.holdings import HoldingsAnalyzer
from brokers.broker_factory import BrokerFactory

app = FastAPI(
    title="Equity Portfolio API",
    description="REST API for managing tradebook, GTT orders, and ROI analysis",
    version="1.0.0"
)

class SessionInitRequest(BaseModel):
    broker_name: str
    user_id: str

@app.post("/session/initialize")
def initialize_session(request: SessionInitRequest):
    try:
        session_manager = session.session_manager
        config = {}
        broker_name = request.broker_name
        user_id = request.user_id

        if broker_name == 'upstox':
            config['api_key'] = session_manager.upstox_api_key
            config['api_secret'] = session_manager.upstox_api_secret
            config['redirect_uri'] = session_manager.upstox_redirect_uri
            config['access_token'] = session_manager.get_valid_upstox_access_token()
        else: # default to zerodha
            broker_name = 'zerodha'
            config['api_key'] = session_manager.kite_api_key
            config['access_token'] = session_manager.get_valid_kite_access_token()

        session.broker = BrokerFactory.get_broker(broker_name, user_id, config)
        session.broker.login()
        session.refresh_all_caches()

        return {"message": f"Session initialized for {broker_name} with user_id {user_id}"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e), "trace": traceback.format_exc()})


@app.get("/session/validate-tokens")
def validate_tokens(broker_name: str = Query(..., description="The broker to check ('zerodha', 'upstox')")):
    """
    Validates the access tokens for the specified broker without triggering interactive login.
    - If broker_name is 'upstox', only the Upstox token is validated.
    - If broker_name is not 'upstox' (e.g., 'zerodha'), it validates both that broker's token and the Upstox token.
    """
    try:
        session_manager = session.session_manager
        response_data = {}
        brokers_to_check = {broker_name.lower()}
        if broker_name.lower() != 'upstox':
            brokers_to_check.add('upstox')

        if 'upstox' in brokers_to_check:
            is_valid, _, login_url = session_manager.check_upstox_token_validity()
            response_data['upstox'] = {
                'is_valid': is_valid,
                'message': 'Token is valid.' if is_valid else 'Token is invalid, missing, or expired.',
                'login_url': login_url if not is_valid else None
            }

        if 'zerodha' in brokers_to_check:
            is_valid, _, login_url = session_manager.check_kite_token_validity()
            response_data['zerodha'] = {
                'is_valid': is_valid,
                'message': 'Token is valid.' if is_valid else 'Token is invalid, missing, or expired.',
                'login_url': login_url if not is_valid else None
            }
        
        return JSONResponse(status_code=200, content=response_data)

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"An unexpected error occurred: {str(e)}", "trace": traceback.format_exc()})

@app.post("/session/generate-token")
def generate_token(broker_name: str = Query(..., description="The broker to generate a token for ('kite', 'zerodha', 'upstox')"), redirected_url: str = Query(None, description="The redirected URL with the request token or code")):
    try:
        session_manager = session.session_manager
        access_token = None
        broker_name_lower = broker_name.lower()

        if broker_name_lower == 'upstox':
            access_token = session_manager.generate_new_upstox_token(redirected_url)
        elif broker_name_lower in ['kite', 'zerodha']:
            kite = KiteConnect(api_key=session_manager.kite_api_key)
            access_token = session_manager.generate_new_kite_token(kite, redirected_url)
        else:
            return JSONResponse(status_code=400, content={"error": f"Broker '{broker_name}' is not supported for token generation."})

        return {"message": f"New access token for {broker_name} generated and saved."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e), "trace": traceback.format_exc()})


@app.post("/update-tradebook")
def update_tradebook():
    try:
        session.refresh_all_caches()
        holdings_analyzer = HoldingsAnalyzer(session.broker.user_id, session.broker.broker_name)
        summary = holdings_analyzer.update_tradebook(session.broker)
        return {"message": "Tradebook updated successfully.", "summary": summary}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/write-roi")
def write_roi():
    try:
        session.refresh_all_caches()
        holdings_analyzer = HoldingsAnalyzer(session.broker.user_id, session.broker.broker_name)
        # In the CLI, this is called from analyze_holdings. 
        # This endpoint might need to be re-evaluated or accept data.
        results = holdings_analyzer.analyze_holdings(session.broker, session.get_cmp_manager())
        holdings_analyzer.write_roi_results(results)
        return {"message": "ROI results written successfully."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/entry-levels/duplicates")
def check_duplicates():
    try:
        session.refresh_all_caches()
        scrips = session.get_entry_levels()
        duplicates = detect_duplicates(scrips)
        return {"duplicates": duplicates}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/entry-levels/gtt-plan")
def list_entry_levels(filter_ltp: float = Query(None, description="Filter orders with LTP greater than this value")):
    try:
        session.refresh_all_caches()
        
        duplicates = detect_duplicates(session.get_entry_levels())

        planner = MultiLevelEntryStrategy(
            broker=session.broker,
            cmp_manager=session.get_cmp_manager(),
            holdings=session.get_holdings(),
            entry_levels=session.get_entry_levels(),
            gtt_cache=session.get_gtt_cache()
        )

        candidates = planner.identify_candidates()
        new_orders = planner.generate_plan(candidates)
        skipped_orders = planner.skipped_orders

        session.write_gtt_plan(new_orders)

        if filter_ltp is not None:
            new_orders = [o for o in new_orders if o.get("ltp") and o["ltp"] > filter_ltp]

        return {
            "duplicates": duplicates,
            "skipped_orders": skipped_orders,
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

        manager = GTTManager(session.broker, session.get_cmp_manager(), session)
        placed_orders = manager.place_orders(new_orders, dry_run=False)
        session.delete_gtt_plan()

        return {
            "message": "GTT orders placed successfully.",
            "placed_orders": placed_orders
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e), "trace": traceback.format_exc()})

@app.get("/gtt-orders/variance")
def analyze_gtt_variance(threshold: float = Query(100.0, description="Variance threshold to filter GTTs")):
    try:
        session.refresh_all_caches()
        manager = GTTManager(session.broker, session.get_cmp_manager(), session)
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
        manager = GTTManager(session.broker, session.get_cmp_manager(), session)
        orders = manager.analyze_gtt_buy_orders()
        to_adjust = [o for o in orders if o["Variance (%)"] < target_variance]
        adjusted = manager.adjust_orders(to_adjust, target_variance, BaseEntryStrategy.adjust_trigger_and_order_price)
        return {"adjusted_orders": adjusted}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.delete("/gtt-orders/delete")
def delete_gtt_orders(threshold: float = Query(..., description="Variance threshold above which GTTs will be deleted")):
    try:
        session.refresh_all_caches()
        manager = GTTManager(session.broker, session.get_cmp_manager(), session)
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
        manager = GTTManager(session.broker, session.get_cmp_manager(), session)
        duplicates = manager.get_duplicate_gtt_symbols()
        return {"duplicates": duplicates}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/gtt-orders/total-buy-amount")
def show_total_buy_gtt_amount(threshold: float = Query(None, description="Optional variance threshold")):
    try:
        session.refresh_all_caches()
        manager = GTTManager(session.broker, session.get_cmp_manager(), session)
        total_amount = manager.get_total_buy_gtt_amount(threshold)
        return {"total_buy_gtt_amount": total_amount}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/holdings/analyze")
def analyze_holdings(
    filters: str = Query(None, description="JSON string of filters"),
    sort_by: str = Query("W ROI", description="Column to sort by (e.g., 'ROI/Day', 'P&L')")
):
    try:
        session.refresh_all_caches()
        holdings_analyzer = HoldingsAnalyzer(session.broker.user_id, session.broker.broker_name)
        parsed_filters = json.loads(filters) if filters else {}
        results = holdings_analyzer.analyze_holdings(
            session.broker,
            session.get_cmp_manager(),
            parsed_filters,
            sort_by=sort_by
        )

        for row in results:
            trend = row.get("Trend", "-")
            trend_days = row.get("Trend Days", "")
            row["Trend"] = f"{trend}({trend_days})" if trend_days != "" else trend

        return {"results": results}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    


@app.get("/dynamic-avg/plan")
def plan_dynamic_avg():
    """Generate a buy plan for the dynamic averaging strategy."""
    try:
        session.refresh_all_caches()
        from core.dynamic_avg import DynamicAveragingPlanner
        planner = DynamicAveragingPlanner()
        candidates = planner.identify_candidates()
        plan = planner.generate_buy_plan(candidates)
        session.write_gtt_plan(plan)
        return {"plan": plan}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e), "trace": traceback.format_exc()})

@app.post("/dynamic-averaging/place")
def place_dynamic_averaging_orders():
    """Place GTT orders from cached dynamic averaging plan, deleting existing GTTs for symbols in the plan."""
    try:
        session.refresh_all_caches()
        new_orders = session.read_gtt_plan()

        if not new_orders:
            return JSONResponse(status_code=400, content={"error": "No dynamic averaging GTT orders found in cache."})

        manager = GTTManager(session.broker, session.get_cmp_manager(), session)

        # --- Deletion Logic from CLI ---
        deleted_gtt_symbols = []
        new_plan_symbols = {order["symbol"] for order in new_orders}
        if new_plan_symbols:
            all_gtts = session.get_gtt_cache()
            
            symbols_to_delete = []
            for g in all_gtts:
                details = manager._parse_gtt(g)
                if details.get("status") == "active":
                    symbol = details.get("symbol")
                    if symbol in new_plan_symbols:
                        symbols_to_delete.append(symbol)
            
            symbols_to_delete = list(set(symbols_to_delete))

            if symbols_to_delete:
                deleted_gtt_symbols = manager.delete_gtts_for_symbols(symbols_to_delete)
        # --- End Deletion Logic ---
        
        placed_orders = manager.place_orders(new_orders, dry_run=False)
        session.delete_gtt_plan()
        return {
            "message": "Dynamic averaging GTT orders placed successfully.",
            "placed_orders": placed_orders,
            "deleted_gtts": deleted_gtt_symbols
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e), "trace": traceback.format_exc()})

@app.get("/holdings/total-invested")
def get_total_invested_amount():
    try:
        session.refresh_all_caches()
        holdings = session.get_holdings()
        analyzer = HoldingsAnalyzer(session.broker.user_id, session.broker.broker_name)
        total = analyzer.get_total_invested(holdings)
        return {"total_invested": round(total, 2)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/trades/download-historical")
def download_historical_trades_api(start_date: str = Query(..., description="Start date in YYYY-MM-DD format"), end_date: str = Query(..., description="End date in YYYY-MM-DD format")):
    try:
        if not session.broker:
            return JSONResponse(status_code=400, content={"error": "Session not initialized."})

        holdings_analyzer = HoldingsAnalyzer(session.broker.user_id, session.broker.broker_name)
        summary = holdings_analyzer.download_historical_trades(session.broker, start_date, end_date)
        return summary
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e), "trace": traceback.format_exc()})
