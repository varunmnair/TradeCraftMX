import pandas as pd
import logging
from collections import Counter
from typing import List, Dict
from abc import ABC, abstractmethod
from core.session_singleton import shared_session as session

class BaseEntryStrategy(ABC):
    def __init__(self, kite, cmp_manager, holdings=None):
        self.kite = kite
        self.cmp_manager = cmp_manager
        self.holdings = holdings if holdings is not None else session.kite.holdings()

    @abstractmethod
    def generate_plan(self, scrip: Dict) -> List[Dict]:
        """
        Generates an entry plan for a given scrip.
        This method must be implemented by all concrete strategy classes.
        """
        pass

    

    @staticmethod
    def adjust_trigger_and_order_price(order_price: float, ltp: float) -> tuple[float, float]:
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

        tick_size = 0.05 if ltp < 500 else 0.1
        order_price = round(round(order_price / tick_size) * tick_size, 2)
        trigger = round(round(trigger / tick_size) * tick_size, 2)

        actual_diff = abs(trigger - ltp) / ltp
        if actual_diff < MIN_REQUIRED_DIFF:
            logging.warning(f"⚠️ Adjusted trigger ({trigger}) too close to LTP ({ltp}). Enforcing minimum diff.")
            if trigger < ltp:
                trigger = round(ltp - ltp * MIN_REQUIRED_DIFF, 2)
            else:
                trigger = round(ltp + ltp * MIN_REQUIRED_DIFF, 2)
            order_price = round(trigger - exact_diff, 2)

        return order_price, trigger

# Utility functions, can be kept separate from the class
def detect_duplicates(scrips: List[Dict]) -> List[str]:
    symbol_counts = Counter(
        s["symbol"].strip().upper()
        for s in scrips
        if "symbol" in s and isinstance(s["symbol"], str)
    )
    duplicates = [symbol for symbol, count in symbol_counts.items() if count > 1]
    if duplicates:
        logging.warning(f"Duplicate symbols found: {duplicates}")
    return duplicates
