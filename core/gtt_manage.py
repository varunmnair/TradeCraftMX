import logging
from typing import List, Dict, Callable
from core.session_singleton import shared_session as session


class GTTManager:
    def __init__(self, kite, cmp_manager, session):
        self.kite = kite
        self.cmp_manager = cmp_manager
        self.session = session  # ✅ Add session reference

    # ──────────────── GTT Analysis ──────────────── #
    def analyze_orders(self) -> Dict:
        try:
            gtts = session.get_gtt_cache()
            orders = []
            symbol_count = {}
            total_amount = 0.0

            for g in gtts:
                # Handle both formats: with 'orders' or flat structure
                if "orders" in g and isinstance(g["orders"], list):
                    order_data = g["orders"][0]
                    transaction_type = order_data.get("transaction_type")
                    qty = order_data.get("quantity")
                    price = order_data.get("price")
                else:
                    transaction_type = g.get("transaction_type")
                    qty = g.get("quantity")
                    price = g.get("price")

                if transaction_type != self.kite.TRANSACTION_TYPE_BUY:
                    continue

                symbol = g.get("tradingsymbol") or g.get("condition", {}).get("tradingsymbol")
                exchange = g.get("exchange") or g.get("condition", {}).get("exchange")
                trigger_values = g.get("trigger_values") or g.get("condition", {}).get("trigger_values")
                trigger = trigger_values[0] if trigger_values else None

                if not symbol or not exchange or trigger is None:
                    continue

                ltp = self.cmp_manager.get_cmp(exchange, symbol)
                if ltp is None:
                    logging.warning(f"Skipping {symbol} due to missing LTP.")
                    continue

                gtt_id = g.get("id")
                variance = round(((ltp - trigger) / trigger) * 100, 2)

                orders.append({
                    "Symbol": symbol,
                    "Exchange": exchange,
                    "Trigger Price": trigger,
                    "LTP": ltp,
                    "Variance (%)": variance,
                    "Qty": qty,
                    "Price": price,
                    "GTT ID": gtt_id
                })

                symbol_count[symbol] = symbol_count.get(symbol, 0) + 1
                total_amount += price * qty if price and qty else 0

            sorted_orders = sorted(orders, key=lambda x: x["Variance (%)"])
            duplicates = [s for s, c in symbol_count.items() if c > 1]

            return {
                "orders": sorted_orders,
                "duplicates": duplicates,
                "total_amount": round(total_amount, 2)
            }

        except Exception as e:
            logging.error(f"Error computing GTT analysis: {e}")
            return {
                "orders": [],
                "duplicates": [],
                "total_amount": 0.0
            }


    # ──────────────── GTT Adjustment ──────────────── #
    def adjust_orders(self, orders: List[Dict], target_variance: float,
                      adjust_fn: Callable[[float, float], tuple[float, float]]) -> List[Dict]:
        modified = []
        for order in orders:
            if order["Variance (%)"] < target_variance:
                try:
                    new_trigger = round(order["LTP"] / (1 + target_variance / 100), 2)
                    new_price, new_trigger = adjust_fn(order_price=new_trigger, ltp=order["LTP"])

                    self.kite.delete_gtt(order["GTT ID"])
                    self.kite.place_gtt(
                        trigger_type=self.kite.GTT_TYPE_SINGLE,
                        tradingsymbol=order["Symbol"],
                        exchange=order["Exchange"],
                        trigger_values=[new_trigger],
                        last_price=order["LTP"],
                        orders=[{
                            "transaction_type": self.kite.TRANSACTION_TYPE_BUY,
                            "quantity": order["Qty"],
                            "order_type": self.kite.ORDER_TYPE_LIMIT,
                            "product": self.kite.PRODUCT_CNC,
                            "price": new_price
                        }]
                    )
                    modified.append({
                        "Symbol": order["Symbol"],
                        "Trigger Price": new_trigger,
                        "LTP": order["LTP"],
                        "Variance (%)": round(((order["LTP"] - new_trigger) / new_trigger) * 100, 2)
                    })

                except Exception as e:
                    logging.warning(f"Failed to modify GTT for {order['Symbol']}: {e}")
        self.session.refresh_gtt_cache()  # ✅ Refresh GTT cache after adjustment
        return modified

    # ──────────────── GTT Deletion ──────────────── #
    def delete_orders_above_variance(self, orders: List[Dict], threshold: float) -> List[str]:
        deleted = []
        for order in orders:
            if order["Variance (%)"] > threshold:
                try:
                    self.kite.delete_gtt(order["GTT ID"])
                    deleted.append(order["Symbol"])
                except Exception as e:
                    logging.warning(f"Failed to delete GTT for {order['Symbol']}: {e}")
        self.session.refresh_gtt_cache()  # ✅ Refresh GTT cache after deletion
        return deleted
