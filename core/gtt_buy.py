import logging
from datetime import datetime
from typing import List, Dict
from core.cmp import CMPManager
import math
from core.session_singleton import shared_session as session
from core.session import SessionCache

class BuyOrderPlanner:
    def __init__(self, kite, cmp_manager: CMPManager, holdings: List[Dict] = None, session: SessionCache = None):
        self.kite = kite
        self.cmp_manager = cmp_manager
        self.session = session if session is not None else SessionCache()
        self.holdings = holdings if holdings is not None else self.session.kite.holdings()



    # ──────────────── Price Adjustment ──────────────── #
    def adjust_trigger_and_order_price(self, order_price: float, ltp: float) -> tuple[float, float]:
        LTP_TRIGGER_DIFF = 0.0026
        ORDER_TRIGGER_DIFF = 0.001
        MIN_REQUIRED_DIFF = 0.0025  # 0.25%

        min_diff = round(ltp * LTP_TRIGGER_DIFF, 4)
        exact_diff = round(order_price * ORDER_TRIGGER_DIFF, 4)

        if order_price < ltp:
            min_trigger = round(ltp - min_diff, 2)
            trigger = round(order_price + exact_diff, 2)
            if trigger < min_trigger:
                order_price, trigger = order_price, trigger
            else:
                trigger = min_trigger
                order_price = round(trigger - exact_diff, 2)
        else:
            max_trigger = round(ltp + min_diff, 2)
            trigger = round(order_price - exact_diff, 2)
            if trigger > max_trigger:
                order_price, trigger = order_price, trigger
            else:
                trigger = max_trigger
                order_price = round(trigger + exact_diff, 2)

        # Round to nearest 0.05
        order_price = round(round(order_price / 0.05) * 0.05, 2)
        trigger = round(round(trigger / 0.05) * 0.05, 2)

        # ✅ Final validation
        actual_diff = abs(trigger - ltp) / ltp
        if actual_diff < MIN_REQUIRED_DIFF:
            logging.warning(f"⚠️ Adjusted trigger ({trigger}) too close to LTP ({ltp}). Enforcing minimum diff.")
            if trigger < ltp:
                trigger = round(ltp - ltp * MIN_REQUIRED_DIFF, 2)
            else:
                trigger = round(ltp + ltp * MIN_REQUIRED_DIFF, 2)
            order_price = round(trigger - exact_diff, 2)

        return order_price, trigger

    
    # ──────────────── GTT Plan Generation ──────────────── #

    def generate_plan(self, scrip: Dict) -> List[Dict]:
        symbol = scrip["symbol"]
        exchange = scrip["exchange"]
        entry1 = scrip.get("entry1")
        entry2 = scrip.get("entry2")
        entry3 = scrip.get("entry3")
        allocated = scrip["Allocated"]

        gtt_cache = session.get_gtt_cache()
        if symbol.upper() in [g["tradingsymbol"].upper() for g in gtt_cache if g["transaction_type"] == "BUY"]:
            logging.info(f"⏭️ Skipping {symbol}: GTT already exists")
            return [{
                "symbol": symbol,
                "skip_reason": "GTT already exists for symbol"
            }]

        ltp = self.cmp_manager.get_cmp(exchange, symbol)
        if ltp is None or ltp == 0 or (isinstance(ltp, float) and math.isnan(ltp)):
            logging.error(f"❌ Skipping {symbol}: Invalid CMP ({ltp})")
            return []

        if allocated is None or (isinstance(allocated, float) and math.isnan(allocated)):
            logging.error(f"❌ Skipping {symbol}: Invalid allocation ({allocated})")
            return []

        entry_allocated = allocated / 3
        qty = int(entry_allocated / ltp)

        if qty == 0:
            logging.debug(f"⚠️ Skipping {symbol}: Computed quantity is 0")
            return []

        # Determine current holdings
        total_qty = 0
        for h in self.holdings:
            if h["tradingsymbol"].replace("#", "").replace("-BE", "") == symbol:
                total_qty = h["quantity"] + h.get("t1_quantity", 0)
                break

        # Consolidated skip condition for holdings
        if total_qty >= qty:
            logging.info(f"⏭️ Skipping {symbol}: Holding exceeds or matches allocation")
            return [{
                "symbol": symbol,
                "exchange": exchange,
                "price": None,
                "trigger": None,
                "qty": 0,
                "ltp": round(ltp, 2),
                "entry": None,
                "skip_reason": "Holding exceeded allocated amount"
            }]

        # Select the appropriate entry level
        entry_level = None
        entry_price = None
        if total_qty == 0 and entry1 is not None:
            entry_level = "E1"
            entry_price = entry1
        elif total_qty <= qty // 3 and entry2 is not None:
            entry_level = "E2"
            entry_price = entry2
        elif total_qty <= (2 * qty) // 3 and entry3 is not None:
            entry_level = "E3"
            entry_price = entry3
        else:
            logging.info(f"⏭️ Skipping {symbol}: Holding exceeds or matches allocation")
            return [{
                "symbol": symbol,
                "exchange": exchange,
                "price": None,
                "trigger": None,
                "qty": 0,
                "ltp": round(ltp, 2),
                "entry": None,
                "skip_reason": "Holding exceeded allocated amount"
            }]

        order_price = min(entry_price, round(ltp * 1.025, 2)) if entry_price > ltp else entry_price
        order_price, trigger = self.adjust_trigger_and_order_price(order_price, ltp)

        return [{
            "symbol": symbol,
            "exchange": exchange,
            "price": order_price,
            "trigger": trigger,
            "qty": qty,
            "ltp": round(ltp, 2),
            "entry": entry_level
        }]
    
   # ──────────────── GTT Order Placement ──────────────── #
    def place_orders(self, gtt_plan: List[Dict], dry_run: bool = False) -> List[Dict]:
        results = []

        for order in gtt_plan:
            symbol = order["symbol"]
            result = {
                "symbol": symbol,
                "price": order["price"],
                "trigger": order["trigger"],
                "status": "Success",
                "remarks": ""
            }

            if not dry_run:
                try:
                    self.kite.place_gtt(
                        trigger_type=self.kite.GTT_TYPE_SINGLE,
                        tradingsymbol=symbol,
                        exchange=order["exchange"],
                        trigger_values=[order["trigger"]],
                        last_price=order["ltp"],
                        orders=[{
                            "transaction_type": self.kite.TRANSACTION_TYPE_BUY,
                            "quantity": order["qty"],
                            "order_type": self.kite.ORDER_TYPE_LIMIT,
                            "product": self.kite.PRODUCT_CNC,
                            "price": order["price"]
                        }]
                    )
                except Exception as e:
                    result["status"] = "Fail"
                    result["remarks"] = str(e)
                    logging.error(f"[ERROR] ❌ Failed to place GTT for {symbol}: {e}")

            results.append(result)

        self.session.refresh_gtt_cache()  # ✅ Refresh cache after placing GTTs
        return results

