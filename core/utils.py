import logging
import math
import json
import pandas as pd
from typing import List, Dict

# ──────────────── Logging Setup ──────────────── #
def setup_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

# ──────────────── JSON Sanitization ──────────────── #
def sanitize_for_json(data):
    def sanitize_value(v):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v

    if isinstance(data, list):
        return [{k: sanitize_value(v) for k, v in item.items()} for item in data]
    elif isinstance(data, dict):
        return {k: sanitize_value(v) for k, v in data.items()}
    return data

# ──────────────── CLI Table Printer ──────────────── #
def print_table(rows: List[Dict], columns: List[str], title=None, spacing=4):
    if not rows:
        print("\n(No matching records found.)")
        return

    col_widths = {
        col: max(len(str(col)), max(len(str(row.get(col, ""))) for row in rows))
        for col in columns
    }
    total_width = sum(col_widths.values()) + spacing * (len(columns) - 1)

    if title:
        print(f"\n{title}")
    print("-" * total_width)

    header = (" " * spacing).join(f"{col:<{col_widths[col]}}" for col in columns)
    print(header)
    print("-" * total_width)

    for row in rows:
        line = (" " * spacing).join(f"{str(row.get(col, '')):<{col_widths[col]}}" for col in columns)
        print(line)


# ──────────────── CSV Reader ──────────────── #

import os

def read_csv(file_path: str) -> List[Dict]:
    try:

        df = pd.read_csv(file_path)
        df.columns = [col.strip() for col in df.columns]
        return df.to_dict(orient="records")
    except Exception as e:
        logging.error(f"Failed to read CSV: {e}")
        return []

def write_csv(file_path: str, data: List[Dict]):
    try:
        df = pd.DataFrame.from_records(data)
        df.to_csv(file_path, index=False)
    except Exception as e:
        logging.error(f"Failed to write to CSV: {e}")

def get_trade_from_tradebook(trade_id: str, tradebook: List[Dict]) -> Dict:
    """
    Retrieves a trade from the tradebook by its ID.

    Args:
        trade_id (str): The ID of the trade to retrieve.
        tradebook (List[Dict]): The tradebook to search.

    Returns:
        Dict: The trade with the matching ID, or None if not found.
    """
    for trade in tradebook:
        if trade.get("trade_id") == trade_id:
            return trade
    return None

def get_symbol_from_isin(isin: str) -> str:
    """
    Retrieves the symbol for a given ISIN from the Name-symbol-mapping.csv file.

    Args:
        isin (str): The ISIN of the instrument.

    Returns:
        str: The symbol corresponding to the ISIN, or None if not found.
    """
    try:
        mapping_file_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'Name-symbol-mapping.csv')
        df = pd.read_csv(mapping_file_path)
        df.columns = [col.strip() for col in df.columns]
        symbol = df[df['ISIN NUMBER'] == isin]['SYMBOL'].values
        if len(symbol) > 0:
            return symbol[0]
        return None
    except Exception as e:
        logging.error(f"Failed to get symbol from ISIN: {e}")
        return None
