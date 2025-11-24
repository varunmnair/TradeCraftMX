import logging
import math
from typing import List, Dict, Tuple
from core.entry import BaseEntryStrategy


class MultiLevelEntryStrategy(BaseEntryStrategy):
    LTP_TRIGGER_VARIANCE_PERCENT = 0.15  # 15% configurable value
    ORDER_PRICE_BUFFER_PERCENT = 0.025  # 2.5% buffer

    def __init__(self, broker, cmp_manager, holdings, entry_levels, gtt_cache):
        super().__init__(broker, cmp_manager, holdings)
        self.entry_levels = entry_levels
        self.gtt_cache = gtt_cache
        self.skipped_orders = []

    def _is_valid_price(self, price) -> bool:
        """Checks if a price is a valid, non-NaN number."""
        return price is not None and not (isinstance(price, float) and math.isnan(price))

    def _create_skipped_order(self, symbol: str, reason: str, exchange: str = None, ltp: float = None, entry: str = None) -> Dict:
        #logging.debug(f"⏭️ Skipping {symbol}: {reason}")
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
        existing_gtt_symbols = set()
        gtt_orders = self.broker.get_gtt_orders() # Get standardized GTTOrder objects
        for gtt_order in gtt_orders:
            # The transaction_type is nested within the 'orders' list
            if gtt_order.get('orders') and len(gtt_order['orders']) > 0:
                if gtt_order.get('status') in ['active', 'COMPLETED'] and gtt_order['orders'][0]['transaction_type'] == "BUY":
                    # The tradingsymbol is in the 'condition' dictionary
                    if gtt_order.get('condition') and gtt_order['condition'].get('tradingsymbol'):
                        existing_gtt_symbols.add(gtt_order['condition']['tradingsymbol'].upper())

        from datetime import datetime
        # Get completed trades for the day
        trades = self.broker.trades() 
        completed_trade_symbols = set()
        today = datetime.now().date()
        for trade in trades:
            trade_date = trade.get('fill_timestamp')
            if trade_date and trade_date.date() == today:
                #if trade.get('transaction_type') == 'BUY':
                    completed_trade_symbols.add(trade.get('tradingsymbol').upper())

        for scrip in self.entry_levels:
            symbol = scrip.get("symbol")
            if not symbol:
                continue
            
            if symbol == "AFIL":
                logging.debug(f"--- Identifying LEHAR ---")
                logging.debug(f"  Scrip: {scrip}")

            exchange = scrip.get("exchange", "NSE")

            # 1. Check for existing GTT order
            if symbol.upper() in existing_gtt_symbols:
                if symbol == "AFIL":
                    logging.debug(f"  Skipping LEHAR: GTT already exists.")
                self.skipped_orders.append(self._create_skipped_order(symbol, "GTT already exists for symbol", exchange=exchange))
                continue
            
            # 2. Check for completed trade on the same day
            if symbol.upper() in completed_trade_symbols:
                self.skipped_orders.append(self._create_skipped_order(symbol, "Trade already completed today", exchange=exchange))
                continue

            # 3. Check for valid allocation
            allocated = scrip.get("Allocated")
            if allocated is None or (isinstance(allocated, float) and math.isnan(allocated)) or allocated == 0:
                if symbol == "AFIL":
                    logging.debug(f"  Skipping LEHAR: Invalid or zero allocation ({allocated}).")
                self.skipped_orders.append(self._create_skipped_order(symbol, "Invalid or zero allocation", exchange=exchange))
                continue

            # 4. Check for valid entry levels
            entry1 = scrip.get("entry1")
            entry2 = scrip.get("entry2")
            entry3 = scrip.get("entry3")
            is_entry1_valid = self._is_valid_price(entry1)
            is_entry2_valid = self._is_valid_price(entry2)
            is_entry3_valid = self._is_valid_price(entry3)
            num_entries = (1 if is_entry1_valid else 0) + (1 if is_entry2_valid else 0) + (1 if is_entry3_valid else 0)

            if num_entries == 0:
                if symbol == "AFIL":
                    logging.debug(f"  Skipping LEHAR: No valid entry levels.")
                self.skipped_orders.append(self._create_skipped_order(symbol, "No valid entry levels", exchange=exchange))
                continue

            # 5. Fetch and validate LTP (done last to save API calls)
            ltp = self.cmp_manager.get_cmp(exchange, symbol)
            if ltp is None or ltp == 0 or (isinstance(ltp, float) and math.isnan(ltp)):
                if symbol == "AFIL":
                    logging.debug(f"  Skipping LEHAR: Invalid CMP ({ltp}).")
                self.skipped_orders.append(self._create_skipped_order(symbol, "Invalid CMP", exchange=exchange))
                continue
            
            # If all checks pass, add to candidates
            if symbol == "AFIL":
                logging.debug(f"  LEHAR added to candidates.")
            candidate_scrip = scrip.copy()
            candidate_scrip['ltp'] = ltp
            candidate_scrip['num_entries'] = num_entries
            candidate_scrip['is_entry1_valid'] = is_entry1_valid
            candidate_scrip['is_entry2_valid'] = is_entry2_valid
            candidate_scrip['is_entry3_valid'] = is_entry3_valid
            candidates.append(candidate_scrip)
            
        return candidates

    def _get_holding_details(self, holdings_map: Dict, symbol: str) -> Tuple[float, float]:
        holding = holdings_map.get(symbol)
        if not holding:
            return 0, 0
        
        total_qty = holding.get("quantity", 0) + holding.get("t1_quantity", 0)
        average_price = holding.get("average_price", 0)
        return total_qty, average_price

    def _determine_entry_level(self, scrip: Dict, invested_amount: float, ltp: float) -> Tuple[str, float, float]:
        num_entries = scrip["num_entries"]
        allocated = scrip["Allocated"]
        entry_allocated = allocated / num_entries if num_entries > 0 else 0

        entry_level_definitions = [
            {'level': 'E1', 'price': scrip.get("entry1"), 'is_valid': scrip['is_entry1_valid'], 'max_investment': entry_allocated},
            {'level': 'E2', 'price': scrip.get("entry2"), 'is_valid': scrip['is_entry2_valid'], 'max_investment': 2 * entry_allocated},
            {'level': 'E3', 'price': scrip.get("entry3"), 'is_valid': scrip['is_entry3_valid'], 'max_investment': allocated}
        ]

        # Levels where LTP is already low enough to buy
        potential_levels = []
        for i, level_info in enumerate(entry_level_definitions):
            if level_info['is_valid'] and self._is_valid_price(level_info['price']) and ltp <= level_info['price']:
                current_level_max_investment = (i + 1) * entry_allocated
                if i + 1 == num_entries: # Last level
                    current_level_max_investment = allocated
                
                if invested_amount < current_level_max_investment:
                    potential_levels.append((level_info, current_level_max_investment))
        
        if potential_levels:
            # If there are levels ready for immediate buy, choose the one with the lowest price (best value)
            best_level, best_max_investment = min(potential_levels, key=lambda x: x[0]['price'])
            return best_level['level'], best_level['price'], best_max_investment

        # If LTP is higher than all entry prices, find the next target for a GTT order
        for i, level_info in enumerate(entry_level_definitions):
            if level_info['is_valid'] and self._is_valid_price(level_info['price']):
                current_level_max_investment = (i + 1) * entry_allocated
                if i + 1 == num_entries: # Last level
                    current_level_max_investment = allocated

                if invested_amount < current_level_max_investment:
                    # This is the next level to aim for with a GTT order.
                    return level_info['level'], level_info['price'], current_level_max_investment

        # If we are here, it means we have invested in all valid levels
        return None, None, 0

    def _calculate_quantity(self, amount_to_invest: float, entry_price: float) -> int:
        if entry_price is None or entry_price == 0:
            return 0
        return int(amount_to_invest / entry_price)

    def generate_plan(self, candidates: List[Dict]) -> List[Dict]:
        logging.debug(f"--- Generating Multi-Level Entry Plan ---")
        final_plan = []
        holdings_map = {h["tradingsymbol"].replace("#", "").replace("-BE", ""): h for h in self.holdings}

        for scrip in candidates:
            symbol = scrip["symbol"]
            exchange = scrip["exchange"]
            ltp = scrip["ltp"]
            allocated = scrip["Allocated"]

            # Add logging for LEHAR
            if symbol == "AFIL":
                logging.debug(f"--- Processing LEHAR ---")
                logging.debug(f"  Scrip: {scrip}")

            total_qty, average_price = self._get_holding_details(holdings_map, symbol)
            invested_amount = total_qty * average_price

            if symbol == "AFIL":
                logging.debug(f"  Holdings - Total Qty: {total_qty}, Avg Price: {average_price}, LTP: {ltp} ")
                logging.debug(f"  Calculated Invested Amount: {invested_amount}")
                logging.debug(f"  Allocated Amount: {allocated}")

            if invested_amount >= allocated:
                if symbol == "AFIL":
                    logging.warning(f"  Skipping LEHAR: Invested amount ({invested_amount}) >= Allocated amount ({allocated})")
                self.skipped_orders.append(self._create_skipped_order(symbol, "Holding has reached or exceeded allocated amount", exchange, ltp))
                continue

            entry_level, entry_price, target_investment = self._determine_entry_level(scrip, invested_amount, ltp)

            if symbol == "AFIL":
                logging.debug(f"  Determined Entry Level: {entry_level}, Entry Price: {entry_price}, Target Investment: {target_investment}")

            if not entry_level:
                if symbol == "AFIL":
                    logging.debug(f"  Skipping LEHAR: Does not qualify for any entry level.")
                self.skipped_orders.append(self._create_skipped_order(symbol, "Holding does not qualify for any entry level", exchange, ltp))
                continue

            if not self._is_valid_price(entry_price):
                if symbol == "AFIL":
                    logging.debug(f"  Skipping LEHAR: Invalid entry price ({entry_price}).")
                self.skipped_orders.append(self._create_skipped_order(symbol, "Invalid entry price for quantity calculation", exchange, ltp, entry_level))
                continue

            amount_to_invest = min(target_investment - invested_amount, allocated - invested_amount)
            if symbol == "AFIL":
                logging.debug(f"  Amount to Invest: {amount_to_invest}")

            if amount_to_invest <= 0:
                if symbol == "AFIL":
                    logging.debug(f"  Skipping LEHAR: Amount to invest is not positive ({amount_to_invest}).")
                self.skipped_orders.append(self._create_skipped_order(symbol, "No further investment needed for this level", exchange, ltp, entry_level))
                continue

            qty = self._calculate_quantity(amount_to_invest, entry_price)
            if symbol == "AFIL":
                logging.debug(f"  Calculated Quantity: {qty}")

            if qty == 0:
                if symbol == "AFIL":
                    logging.error(f"  Skipping LEHAR: Computed quantity is 0.")
                self.skipped_orders.append(self._create_skipped_order(symbol, "Computed quantity is 0", exchange, ltp, entry_level))
                continue

            order_price = min(entry_price, round(ltp * (1 + self.ORDER_PRICE_BUFFER_PERCENT), 2)) if entry_price > ltp else entry_price
            order_price, trigger = self.adjust_trigger_and_order_price(order_price, ltp)

            variance = abs(ltp - trigger) / trigger if trigger > 0 else 0
            if variance > self.LTP_TRIGGER_VARIANCE_PERCENT:
                if symbol == "AFIL":
                    logging.debug(f"  Skipping LEHAR: LTP-trigger variance of {variance:.1%} exceeds threshold.")
                reason = f"LTP-trigger variance of {variance:.1%} exceeds threshold of {self.LTP_TRIGGER_VARIANCE_PERCENT:.1%}"
                self.skipped_orders.append(self._create_skipped_order(symbol, reason, exchange, ltp, entry_level))
                continue

            if symbol == "AFIL":
                logging.debug(f"  LEHAR successfully added to plan.")

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