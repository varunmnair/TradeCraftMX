import logging
import math
from typing import List, Dict
from core.session_singleton import shared_session as session
from core.gtt_buy import BuyOrderPlanner
from core.utils import print_table

class DynamicAveragingPlanner:
    def __init__(self, trigger_offset_factor=0.3):
        self.kite = session.kite
        self.cmp_manager = session.get_cmp_manager()
        self.holdings = session.get_holdings()
        self.entry_levels = session.get_entry_levels()
        self.gtt_cache = session.get_gtt_cache()
        self.planner = BuyOrderPlanner(self.kite, self.cmp_manager, self.holdings, session)
        self.skipped_symbols = []
        self.trigger_offset_factor = trigger_offset_factor

    def identify_candidates(self) -> List[Dict]:
        candidates = []
        gtt_symbols = {g["tradingsymbol"].upper() for g in self.gtt_cache if g["transaction_type"] == "BUY"}
        entry_levels_map = {entry.get("symbol", "").strip().upper(): entry for entry in self.entry_levels}

        for holding in self.holdings:
            symbol = holding["tradingsymbol"].replace("#", "").replace("-BE", "").upper()
            
            entry = entry_levels_map.get(symbol)
            if not entry:
                self.skipped_symbols.append({"symbol": symbol, "skip_reason": "Not in entry levels"})
                continue

            exchange = entry.get("exchange", "NSE")
            
            # Fetch LTP early for the new check
            ltp = self.cmp_manager.get_cmp(exchange, symbol)
            if not ltp or ltp <= 0:
                self.skipped_symbols.append({"symbol": symbol, "skip_reason": "Invalid LTP"})
                continue

            allocated = float(entry.get("Allocated", 0))
            da_enabled = entry.get("DA Enabled", "").strip().upper() == "Y"
            da_legs = int(entry.get("DA Legs", 1))

            # New check for allocation vs LTP
            if not da_enabled or allocated < ltp:
                self.skipped_symbols.append({"symbol": symbol, "skip_reason": f"DA not enabled or allocated {allocated} < LTP {ltp}"})
                continue

            entry_prices = []
            for key in ["entry1", "entry2", "entry3"]:
                try:
                    val = float(entry.get(key))
                    if not math.isnan(val):
                        entry_prices.append(val)
                except (TypeError, ValueError):
                    continue

            if not entry_prices:
                self.skipped_symbols.append({"symbol": symbol, "skip_reason": "No valid entry levels"})
                continue

            entry_alloc = allocated / len(entry_prices)
            entry_qtys = [round(entry_alloc / p) for p in entry_prices]
            cumulative_qtys = [sum(entry_qtys[:i+1]) for i in range(len(entry_qtys))]

            held_qty = holding["quantity"] + holding.get("t1_quantity", 0)
            avg_price = holding["average_price"]
            
            invested_amount = avg_price * held_qty
            if invested_amount > allocated:
                self.skipped_symbols.append({"symbol": symbol, "skip_reason": f"Invested amount {invested_amount:.2f} > allocated {allocated:.2f}"})
                continue

            level = None
            lower_bound = 0
            for i, target_qty in enumerate(cumulative_qtys):
                upper_bound = target_qty
                if lower_bound <= held_qty < upper_bound:
                    level = i
                    break
                lower_bound = upper_bound

            if level is None:
                self.skipped_symbols.append({"symbol": symbol, "skip_reason": "Holding quantity not in any entry level range"})
                continue

            buyback_col = f"DA E{level+1} Buyback"
            da_buyback_at = float(entry.get(buyback_col, 5))
            da_trigger_offset = da_buyback_at * self.trigger_offset_factor

            threshold_price = avg_price * (1 - da_buyback_at / 100)
            if ltp > threshold_price:
                self.skipped_symbols.append({"symbol": symbol, "skip_reason": f"LTP {ltp} not below threshold {threshold_price}"})
                continue

            if symbol in gtt_symbols:
                self.skipped_symbols.append({"symbol": symbol, "skip_reason": "GTT already exists"})
                continue

            candidates.append({
                "symbol": symbol,
                "exchange": exchange,
                "allocated": allocated,
                "held_qty": held_qty,
                "avg_price": avg_price,
                "ltp": ltp,
                "da_legs": da_legs,
                "da_buyback_at": da_buyback_at,
                "da_trigger_offset": da_trigger_offset,
                "target_qty": cumulative_qtys[level],
                "entry_level": f"E{level+1}"
            })

        return candidates

    def generate_buy_plan(self, candidates: List[Dict]) -> List[Dict]:
        plan = []
        for c in candidates:
            symbol = c["symbol"]
            exchange = c["exchange"]
            ltp = c["ltp"]
            da_legs = c["da_legs"]
            da_trigger_offset = c["da_trigger_offset"]
            remaining_qty = c["target_qty"] - c["held_qty"]
            if remaining_qty <= 0:
                continue

            leg_qty = int(remaining_qty / da_legs)
            trigger_price = round(ltp * (1 + da_trigger_offset / 100), 2)
            order_price, trigger_price = self.planner.adjust_trigger_and_order_price(trigger_price, ltp)

            for i in range(da_legs):
                plan.append({
                    "symbol": symbol,
                    "exchange": exchange,
                    "price": order_price,
                    "trigger": trigger_price,
                    "qty": leg_qty,
                    "ltp": round(ltp, 2),
                    "strategy": "Dynamic Averaging",
                    "leg": f"DA{i+1}",
                    "entry": c["entry_level"]
                })

        return plan


# CLI command
def plan_dynamic_avg():
    session.refresh_all_caches()
    planner = DynamicAveragingPlanner()
    candidates = planner.identify_candidates()
    plan = planner.generate_buy_plan(candidates)

    print_table(plan, ["symbol", "exchange", "price", "trigger", "qty", "ltp", "strategy", "leg", "entry"], title="📉 Dynamic Averaging Buy Plan")
    session.write_gtt_plan(plan)

# API endpoint
def api_plan_dynamic_avg():
    session.refresh_all_caches()
    planner = DynamicAveragingPlanner()
    candidates = planner.identify_candidates()
    plan = planner.generate_buy_plan(candidates)
    return {"plan": plan}
