import logging
import math
from typing import List, Dict
from core.entry import BaseEntryStrategy

class MultiLevelEntryStrategy(BaseEntryStrategy):
    LTP_TRIGGER_VARIANCE_PERCENT = 0.15  # 15% configurable value
    ORDER_PRICE_BUFFER_PERCENT = 0.025  # 2.5% buffer

    def __init__(self, kite, cmp_manager, holdings, entry_levels, gtt_cache):
        super().__init__(kite, cmp_manager, holdings)
        self.entry_levels = entry_levels
        self.gtt_cache = gtt_cache
        self.skipped_orders = []

    def _is_valid_price(self, price) -> bool:
        """Checks if a price is a valid, non-NaN number."""
        return price is not None and not (isinstance(price, float) and math.isnan(price))

    def _create_skipped_order(self, symbol: str, reason: str, exchange: str = None, ltp: float = None, entry: str = None) -> Dict:
        logging.info(f"⏭️ Skipping {symbol}: {reason}")
        return {
            "symbol": symbol,
            "exchange": exchange,
            "price": None,
            "trigger": None,
            "qty": 0,
            "ltp": ltp,
            "entry": entry,
            "skip_reason": reason
        }

    def identify_candidates(self) -> List[Dict]:
        candidates = []
        existing_gtt_symbols = {g["tradingsymbol"].upper() for g in self.gtt_cache if g["transaction_type"] == "BUY"}

        for scrip in self.entry_levels:
            symbol = scrip.get("symbol")
            if not symbol:
                continue
            
            exchange = scrip.get("exchange", "NSE")

            # 1. Check for existing GTT order
            if symbol.upper() in existing_gtt_symbols:
                self.skipped_orders.append(self._create_skipped_order(symbol, "GTT already exists for symbol", exchange=exchange))
                continue

            # 2. Check for valid allocation
            allocated = scrip.get("Allocated")
            if allocated is None or (isinstance(allocated, float) and math.isnan(allocated)) or allocated == 0:
                self.skipped_orders.append(self._create_skipped_order(symbol, "Invalid or zero allocation", exchange=exchange))
                continue

            # 3. Check for valid entry levels
            entry1 = scrip.get("entry1")
            entry2 = scrip.get("entry2")
            entry3 = scrip.get("entry3")
            is_entry1_valid = self._is_valid_price(entry1)
            is_entry2_valid = self._is_valid_price(entry2)
            is_entry3_valid = self._is_valid_price(entry3)
            num_entries = (1 if is_entry1_valid else 0) + (1 if is_entry2_valid else 0) + (1 if is_entry3_valid else 0)

            if num_entries == 0:
                self.skipped_orders.append(self._create_skipped_order(symbol, "No valid entry levels", exchange=exchange))
                continue

            # 4. Fetch and validate LTP (done last to save API calls)
            ltp = self.cmp_manager.get_cmp(exchange, symbol)
            if ltp is None or ltp == 0 or (isinstance(ltp, float) and math.isnan(ltp)):
                self.skipped_orders.append(self._create_skipped_order(symbol, "Invalid CMP", exchange=exchange))
                continue
            
            # If all checks pass, add to candidates
            candidate_scrip = scrip.copy()
            candidate_scrip['ltp'] = ltp
            candidate_scrip['num_entries'] = num_entries
            candidate_scrip['is_entry1_valid'] = is_entry1_valid
            candidate_scrip['is_entry2_valid'] = is_entry2_valid
            candidate_scrip['is_entry3_valid'] = is_entry3_valid
            candidates.append(candidate_scrip)
            
        return candidates

    def generate_plan(self, candidates: List[Dict]) -> List[Dict]:
        final_plan = []
        holdings_map = {h["tradingsymbol"].replace("#", "").replace("-BE", ""): h for h in self.holdings}

        for scrip in candidates:
            symbol = scrip["symbol"]
            exchange = scrip["exchange"]
            ltp = scrip["ltp"]
            allocated = scrip["Allocated"]
            num_entries = scrip["num_entries"]
            entry1 = scrip.get("entry1")
            entry2 = scrip.get("entry2")
            entry3 = scrip.get("entry3")
            is_entry1_valid = scrip['is_entry1_valid']
            is_entry2_valid = scrip['is_entry2_valid']
            is_entry3_valid = scrip['is_entry3_valid']

            entry_allocated = allocated / num_entries

            # Determine current holdings from map
            holding = holdings_map.get(symbol)
            total_qty = 0
            average_price = 0
            if holding:
                total_qty = holding["quantity"] + holding.get("t1_quantity", 0)
                average_price = holding.get("average_price", 0)

            invested_amount = total_qty * average_price

            # Skip if already fully invested
            if invested_amount >= allocated:
                self.skipped_orders.append(self._create_skipped_order(symbol, "Holding has reached or exceeded allocated amount", exchange, ltp))
                continue

            entry_level_definitions = [
                {'level': 'E1', 'price': entry1, 'is_valid': is_entry1_valid, 'max_investment': entry_allocated if num_entries >= 1 else 0},
                {'level': 'E2', 'price': entry2, 'is_valid': is_entry2_valid, 'max_investment': 2 * entry_allocated if num_entries >= 2 else 0},
                {'level': 'E3', 'price': entry3, 'is_valid': is_entry3_valid, 'max_investment': allocated} # Last level is always total allocation
            ]

            entry_level = None
            entry_price = None
            target_investment = 0

            for level_info in entry_level_definitions:
                if level_info['is_valid'] and invested_amount < level_info['max_investment']:
                    entry_level = level_info['level']
                    entry_price = level_info['price']
                    target_investment = level_info['max_investment']
                    break  # Found the correct level, no need to check further

            if not entry_level:
                self.skipped_orders.append(self._create_skipped_order(symbol, "Holding does not qualify for any entry level", exchange, ltp))
                continue

            if entry_price is None or entry_price == 0:
                self.skipped_orders.append(self._create_skipped_order(symbol, "Entry price is invalid for quantity calculation", exchange, ltp, entry_level))
                continue
            
            amount_to_invest = target_investment - invested_amount
            if amount_to_invest <= 0:
                 self.skipped_orders.append(self._create_skipped_order(symbol, "No further investment needed for this level", exchange, ltp, entry_level))
                 continue

            qty = int(amount_to_invest / entry_price)

            if qty == 0:
                self.skipped_orders.append(self._create_skipped_order(symbol, "Computed quantity is 0", exchange, ltp, entry_level))
                continue

            # Adjust quantity if total investment exceeds allocation
            order_amount = qty * entry_price
            if invested_amount + order_amount > allocated:
                remaining_allocation = allocated - invested_amount
                if remaining_allocation > 0:
                    qty = int(remaining_allocation / entry_price)
                else:
                    self.skipped_orders.append(self._create_skipped_order(symbol, "Invested amount already exceeds allocation", exchange, ltp, entry_level))
                    continue

            if qty == 0:
                self.skipped_orders.append(self._create_skipped_order(symbol, "Computed quantity is 0 after allocation adjustment", exchange, ltp, entry_level))
                continue

            order_price = min(entry_price, round(ltp * (1 + self.ORDER_PRICE_BUFFER_PERCENT), 2)) if entry_price > ltp else entry_price
            order_price, trigger = self.adjust_trigger_and_order_price(order_price, ltp)

            # Skip if LTP has deviated too much from the trigger price
            if trigger and trigger > 0:
                variance = abs(ltp - trigger) / trigger
                if variance > self.LTP_TRIGGER_VARIANCE_PERCENT:
                    reason = f"LTP-trigger variance of {variance:.1%} exceeds threshold of {self.LTP_TRIGGER_VARIANCE_PERCENT:.1%}"
                    self.skipped_orders.append(self._create_skipped_order(symbol, reason, exchange, ltp, entry_level))
                    continue

            final_plan.append({
                "symbol": symbol,
                "exchange": exchange,
                "price": order_price,
                "trigger": trigger,
                "qty": qty,
                "ltp": round(ltp, 2),
                "entry": entry_level
            })
        return final_plan