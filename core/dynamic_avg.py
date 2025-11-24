import logging
import math
from typing import List, Dict
from core.multilevel_entry import MultiLevelEntryStrategy
from core.utils import print_table

class DynamicAveragingPlanner:
    def __init__(self, session, trigger_offset_factor=0.3):
        self.session = session
        self.broker = self.session.broker
        self.cmp_manager = self.session.get_cmp_manager()
        self.holdings = self.session.get_holdings()
        self.entry_levels = self.session.get_entry_levels()
        self.gtt_cache = self.session.get_gtt_cache()
        self.planner = MultiLevelEntryStrategy(self.broker, self.cmp_manager, self.holdings, self.entry_levels, self.gtt_cache)
        self.skipped_symbols = []
        self.trigger_offset_factor = trigger_offset_factor

    def identify_candidates(self) -> List[Dict]:
        candidates = []
        entry_levels_map = {entry.get("symbol", "").strip().upper(): entry for entry in self.entry_levels}

        from datetime import datetime
        # Get completed trades for the day
        trades = self.broker.trades()
        completed_trade_symbols = set()
        today = datetime.now().date()

        for trade in trades:
            trade_date = trade.get('fill_timestamp')
            if trade_date and trade_date.date() == today:
                if trade.get('transaction_type') == 'BUY':
                    completed_trade_symbols.add(trade.get('tradingsymbol').upper())

        for holding in self.holdings:
            symbol = holding["tradingsymbol"].replace("#", "").replace("-BE", "").upper()

            if symbol in completed_trade_symbols:
                self.skipped_symbols.append({"symbol": symbol, "skip_reason": "Trade already completed today"})
                continue
           
            entry = entry_levels_map.get(symbol)

            # First, check for a valid entry plan without fetching LTP
            da_enabled = entry.get("DA Enabled", "").strip().upper() == "Y" if entry else False
            entry_prices = []
            if entry:
                for key in ["entry1", "entry2", "entry3"]:
                    try:
                        val = float(entry.get(key))
                        if not math.isnan(val):
                            entry_prices.append(val)
                    except (TypeError, ValueError):
                        continue
            
            if not entry or not da_enabled or not entry_prices:
                self.skipped_symbols.append({"symbol": symbol, "skip_reason": "No valid row in entry levels"})
                continue

            # Now that we have a valid plan, fetch the LTP
            exchange = entry.get("exchange", "NSE")
            ltp = self.cmp_manager.get_cmp(exchange, symbol)

            if not ltp or ltp <= 0:
                self.skipped_symbols.append({"symbol": symbol, "skip_reason": "Invalid LTP"})
                continue

            # Final check that requires LTP
            allocated = float(entry.get("Allocated", 0))
            if allocated < ltp:
                self.skipped_symbols.append({"symbol": symbol, "skip_reason": f"Allocation {allocated} < LTP {ltp}"})
                continue

            # --- START OF NEW VALUE-BASED LOGIC ---
            held_qty = holding["quantity"] + holding.get("t1_quantity", 0)
            avg_price = holding["average_price"]
            invested_amount = avg_price * held_qty

            if invested_amount > allocated:
                self.skipped_symbols.append({"symbol": symbol, "skip_reason": f"Invested amount {invested_amount:.2f} > allocated {allocated:.2f}"})
                continue

            # Determine level based on allocation thresholds
            entry_alloc_per_leg = allocated / len(entry_prices)
            cumulative_allocs = [entry_alloc_per_leg * (i + 1) for i in range(len(entry_prices))]

            level = None
            for i, target_alloc in enumerate(cumulative_allocs):
                if invested_amount <= target_alloc:
                    level = i
                    break

            if level is None:
                self.skipped_symbols.append({"symbol": symbol, "skip_reason": "Holding amount not in any entry level range"})
                continue
            
            # --- END OF NEW VALUE-BASED LOGIC ---

            da_legs = int(entry.get("DA Legs", 1))
            buyback_col = f"DA E{level+1} Buyback"
            da_buyback_at = float(entry.get(buyback_col, 5))
            da_trigger_offset = da_buyback_at * self.trigger_offset_factor

            threshold_price = avg_price * (1 - da_buyback_at / 100)
            if ltp > threshold_price:
                self.skipped_symbols.append({"symbol": symbol, "skip_reason": f"LTP {ltp} not below threshold {threshold_price}"})
                continue

            candidates.append({
                "symbol": symbol,
                "exchange": exchange,
                "ltp": ltp,
                "da_legs": da_legs,
                "da_trigger_offset": da_trigger_offset,
                "entry_level": f"E{level+1}",
                "level_idx": level,
                "invested_amount": invested_amount,
                "cumulative_allocs": cumulative_allocs
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

            # --- START OF NEW VALUE-BASED ORDER LOGIC ---
            level_idx = c["level_idx"]
            cumulative_allocs = c["cumulative_allocs"]
            invested_amount = c["invested_amount"]

            target_allocation_for_level = cumulative_allocs[level_idx]
            amount_to_invest = target_allocation_for_level - invested_amount
            
            # Per user: skip if the remaining amount to invest is > 75% of the leg's allocation
            # This means we only "top up" when a leg is mostly filled.
            entry_alloc_per_leg = cumulative_allocs[0]
            if amount_to_invest > (entry_alloc_per_leg * 0.75):
                self.skipped_symbols.append({
                    "symbol": symbol,
                    "skip_reason": f"Remaining amount {amount_to_invest:.2f} > 75% of leg allocation"
                })
                continue

            if amount_to_invest <= 0:
                self.skipped_symbols.append({"symbol": symbol, "skip_reason": "No amount to invest for this level"})
                continue
            
            remaining_qty = math.floor(amount_to_invest / ltp)
            # --- END OF NEW VALUE-BASED ORDER LOGIC ---

            if remaining_qty <= 0:
                self.skipped_symbols.append({"symbol": symbol, "skip_reason": "Invalid quantity"})
                continue

            leg_qty = int(remaining_qty / da_legs)

            if leg_qty <= 0:
                self.skipped_symbols.append({"symbol": symbol, "skip_reason": "Invalid quantity"})
                continue

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
                    "leg": f"DA{i+1}",
                    "entry": c["entry_level"]
                })

        return plan