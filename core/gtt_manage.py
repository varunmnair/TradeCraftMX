import logging
from typing import List, Dict, Callable
from collections import Counter

class GTTManager:
    def __init__(self, broker, cmp_manager, session):
        self.broker = broker
        self.cmp_manager = cmp_manager
        self.session = session

    def _parse_gtt(self, g: Dict) -> Dict:
        """Parses a GTT object to extract key details into a flat dictionary."""
        is_order_list = "orders" in g and isinstance(g["orders"], list)
        order_data = g["orders"][0] if is_order_list else g

        details = {
            "transaction_type": order_data.get("transaction_type"),
            "qty": order_data.get("quantity"),
            "price": order_data.get("price"),
            "symbol": g.get("tradingsymbol") or g.get("condition", {}).get("tradingsymbol"),
            "exchange": g.get("exchange") or g.get("condition", {}).get("exchange"),
            "id": g.get("id"),
            "status": g.get("status"),
        }

        trigger_values = g.get("trigger_values") or g.get("condition", {}).get("trigger_values")
        details["trigger"] = trigger_values[0] if trigger_values else None
        
        return details

    def place_orders(self, gtt_plan: List[Dict], dry_run: bool = False) -> List[Dict]:
        """
        Places GTT orders based on the generated plan.
        """
        results = []
        for order in gtt_plan:
            if order.get("skip_reason"):
                results.append({**order, "status": "Skipped", "remarks": order["skip_reason"]})
                continue

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
                    self.broker.place_gtt(
                        trigger_type=self.broker.GTT_TYPE_SINGLE,
                        tradingsymbol=symbol,
                        exchange=order["exchange"],
                        trigger_values=[order["trigger"]],
                        last_price=order["ltp"],
                        orders=[
                            {
                                "transaction_type": self.broker.TRANSACTION_TYPE_BUY,
                                "quantity": order["qty"],
                                "order_type": self.broker.ORDER_TYPE_LIMIT,
                                "product": self.broker.PRODUCT_CNC,
                                "price": order["price"]
                            }
                        ]
                    )
                except Exception as e:
                    result["status"] = "Fail"
                    result["remarks"] = str(e)
                    logging.error(f"[ERROR] ❌ Failed to place GTT for {symbol}: {e}")

            results.append(result)

        self.session.refresh_gtt_cache()
        return results

    # ──────────────── GTT Analysis ──────────────── #
    def analyze_gtt_buy_orders(self) -> List[Dict]:
        try:
            gtts = self.session.get_gtt_cache()
            orders = []

            for g in gtts:
                details = self._parse_gtt(g)
                
                if details.get("status") != "active":
                    continue
                
                if details.get("transaction_type") != self.broker.TRANSACTION_TYPE_BUY:
                    continue

                symbol = details.get("symbol")
                exchange = details.get("exchange")
                trigger = details.get("trigger")

                if not symbol or not exchange or trigger is None:
                    continue

                ltp = self.cmp_manager.get_cmp(exchange, symbol)
                if ltp is None:
                    logging.warning(f"Skipping {symbol} due to missing LTP.")
                    continue

                variance = round(((ltp - trigger) / trigger) * 100, 2)
                
                qty = details.get("qty")
                buy_amount = int(qty * ltp) if qty and ltp else 0

                orders.append(
                    {
                        "GTT ID": details.get("id"),
                        "Symbol": symbol,
                        "Exchange": exchange,
                        "Trigger Price": trigger,
                        "LTP": ltp,
                        "Variance (%)": variance,
                        "Qty": qty,
                        "Buy Amount": buy_amount,
                    }
                )

            return sorted(orders, key=lambda x: x["Variance (%)"])

        except Exception as e:
            logging.error(f"Error computing GTT buy order analysis: {e}")
            return []
        
    def get_duplicate_gtt_symbols(self) -> List[str]:
        try:
            gtts = self.session.get_gtt_cache()
            
            active_buy_symbols = []
            for g in gtts:
                details = self._parse_gtt(g)
                if (details.get("status") == "active" and 
                    details.get("transaction_type") == self.broker.TRANSACTION_TYPE_BUY and 
                    details.get("symbol")):
                    active_buy_symbols.append(details["symbol"])
            
            symbol_counts = Counter(active_buy_symbols)
            return [symbol for symbol, count in symbol_counts.items() if count > 1]

        except Exception as e:
            logging.error(f"Error computing duplicate GTT symbols: {e}")
            return []

    def get_total_buy_gtt_amount(self, threshold: float = None) -> float:
        try:
            gtts = self.session.get_gtt_cache()
            total_amount = 0.0

            for g in gtts:
                details = self._parse_gtt(g)

                if details.get("status") != "active":
                    continue
                
                if details.get("transaction_type") != self.broker.TRANSACTION_TYPE_BUY or not details.get("price") or not details.get("qty"):
                    continue

                if threshold is not None:
                    trigger = details.get("trigger")
                    symbol = details.get("symbol")
                    exchange = details.get("exchange")
                    
                    if trigger is None or exchange is None or symbol is None:
                        continue

                    ltp = self.cmp_manager.get_cmp(exchange, symbol)

                    if ltp is None:
                        continue

                    variance = round(((ltp - trigger) / trigger) * 100, 2)
                    if variance > threshold:
                        continue

                total_amount += details["price"] * details["qty"]

            return round(total_amount, 2)

        except Exception as e:
            logging.error(f"Error computing total buy GTT amount: {e}")
            return 0.0

    # ──────────────── GTT Adjustment ──────────────── #
    def adjust_orders(self, orders: List[Dict], target_variance: float,
                      adjust_fn: Callable[[float, float], tuple[float, float]]) -> List[Dict]:
        modified = []
        for order in orders:
            if order["Variance (%)"] < target_variance:
                try:
                    new_trigger = round(order["LTP"] / (1 + target_variance / 100), 2)
                    new_price, new_trigger = adjust_fn(order_price=new_trigger, ltp=order["LTP"])

                    self.broker.cancel_gtt(order["GTT ID"])
                    self.broker.place_gtt(
                        trigger_type=self.broker.GTT_TYPE_SINGLE,
                        tradingsymbol=order["Symbol"],
                        exchange=order["Exchange"],
                        trigger_values=[new_trigger],
                        last_price=order["LTP"],
                        orders=[{
                            "transaction_type": self.broker.TRANSACTION_TYPE_BUY,
                            "quantity": order["Qty"],
                            "order_type": self.broker.ORDER_TYPE_LIMIT,
                            "product": self.broker.PRODUCT_CNC,
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
                    self.broker.cancel_gtt(order["GTT ID"])
                    deleted.append(order["Symbol"])
                except Exception as e:
                    logging.warning(f"Failed to delete GTT for {order['Symbol']}: {e}")
        self.session.refresh_gtt_cache()  # ✅ Refresh GTT cache after deletion
        return deleted

    def delete_gtts_for_symbols(self, symbols_to_delete: List[str]) -> List[str]:
        deleted_symbols = []
        try:
            gtts = self.session.get_gtt_cache()
            symbols_to_delete_set = set(symbols_to_delete)
            
            gtts_to_process = [g for g in gtts if self._parse_gtt(g).get("symbol") in symbols_to_delete_set]

            for g in gtts_to_process:
                details = self._parse_gtt(g)
                symbol = details.get("symbol")
                status = details.get("status")
                gtt_id = details.get("id")

                if status == "active":
                    try:
                        self.broker.cancel_gtt(gtt_id)
                        deleted_symbols.append(symbol)
                        logging.debug(f"✅ Deleted existing GTT for {symbol} (ID: {gtt_id})")
                    except Exception as e:
                        logging.warning(f"Failed to delete GTT for {symbol} (ID: {gtt_id}): {e}")

            if deleted_symbols:
                self.session.refresh_gtt_cache()
                
        except Exception as e:
            logging.error(f"Error deleting GTTs for symbols: {e}")
        return list(set(deleted_symbols))
