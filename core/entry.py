import pandas as pd
import logging
from collections import Counter
from typing import List, Dict

CSV_FILE_PATH = "data/entry_levels.csv"

class EntryStrategyManager:
    def __init__(self, csv_path: str = "data/entry_levels.csv"):
        self.csv_path = csv_path

    # ──────────────── Load Entry Levels ──────────────── #
    def load_entry_levels(self) -> List[Dict]:
        try:
            df = pd.read_csv(self.csv_path)
            df.columns = [col.strip() for col in df.columns]
            return df.to_dict(orient="records")
        except Exception as e:
            logging.error(f"Failed to read entry levels CSV: {e}")
            return []

    # ──────────────── Duplicate Detection ──────────────── #
    def detect_duplicates(self, scrips: List[Dict]) -> List[str]:
        symbol_counts = Counter(
            s["symbol"].strip().upper()
            for s in scrips
            if "symbol" in s and isinstance(s["symbol"], str)
        )
        duplicates = [symbol for symbol, count in symbol_counts.items() if count > 1]
        if duplicates:
            logging.warning(f"Duplicate symbols found: {duplicates}")
        return duplicates

    # ──────────────── Strategy Placeholder ──────────────── #
    def apply_strategy(self, strategy_name: str, scrips: List[Dict]) -> List[Dict]:
        """
        Placeholder for applying different entry strategies.
        Currently supports only 'multi_entry'.
        """
        if strategy_name == "multi_entry":
            return scrips  # No transformation yet
        else:
            logging.warning(f"Strategy '{strategy_name}' not implemented.")
            return []

    # ──────────────── Utility ──────────────── #
    def print_summary(self, scrips: List[Dict]):
        print(f"\n📋 Entry Levels Summary ({len(scrips)} scrips):")
        for s in scrips:
            print(f" - {s.get('symbol', 'N/A')} | Allocated: {s.get('Allocated', 'N/A')}")
