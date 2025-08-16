import os
import pandas as pd
import logging
from datetime import datetime
from typing import List, Dict

from core.utils import read_csv
from core.entry import CSV_FILE_PATH

class HoldingsAnalyzer:
    def __init__(self, tradebook_path="data/zerodha-tradebook-master.csv", roi_path="data/roi-master.csv"):
        self.tradebook_path = tradebook_path
        self.roi_path = roi_path

    # ──────────────── Tradebook Update ──────────────── #
    def update_tradebook(self, kite):
        new_trades = kite.trades()
        new_df = pd.DataFrame(new_trades)
        if new_df.empty:
            logging.info("No new trades found.")
            return

        new_df = new_df.rename(columns={
            "tradingsymbol": "symbol",
            "exchange": "exchange",
            "instrument_token": "isin",
            "transaction_type": "trade_type",
            "quantity": "quantity",
            "average_price": "price",
            "trade_id": "trade_id",
            "order_id": "order_id",
            "exchange_timestamp": "order_execution_time"
        })

        new_df["isin"] = ""
        new_df["segment"] = "EQ"
        new_df["series"] = new_df["symbol"].apply(lambda x: "EQ")
        new_df["auction"] = False
        new_df["trade_date"] = pd.to_datetime(new_df["order_execution_time"]).dt.date
        new_df["trade_date"] = new_df["trade_date"].apply(lambda x: x.strftime("%#m/%#d/%Y"))

        new_df = new_df[[
            "symbol", "isin", "trade_date", "exchange", "segment", "series",
            "trade_type", "auction", "quantity", "price", "trade_id", "order_id", "order_execution_time"
        ]]

        if os.path.exists(self.tradebook_path):
            existing_df = pd.read_csv(self.tradebook_path)
            existing_ids = set(existing_df["trade_id"].astype(str))
        else:
            existing_df = pd.DataFrame(columns=new_df.columns)
            existing_ids = set()

        new_df = new_df[~new_df["trade_id"].astype(str).isin(existing_ids)]
        if not new_df.empty:
            updated_df = pd.concat([existing_df, new_df], ignore_index=True)
            updated_df.to_csv(self.tradebook_path, index=False)
            logging.info(f"Appended {len(new_df)} new trades to the tradebook.")
        else:
            logging.info("No new trades to append.")

    # ──────────────── ROI Writer ──────────────── #
    def write_roi_results(self, results: List[Dict]):
        os.makedirs(os.path.dirname(self.roi_path), exist_ok=True)
        today = datetime.today()
        if today.weekday() in (5, 6):
            logging.info("Weekend detected. Skipping ROI write.")
            return

        today_str = today.strftime("%Y-%m-%d")
        df_new = pd.DataFrame(results)
        df_new["Date"] = today_str

        df_new = df_new.rename(columns={
            "Symbol": "Symbol",
            "Invested": "Invested Amount",
            "P&L": "Absolute Profit",
            "Yld/Day": "Yield Per Day",
            "Age": "Age of Stock",
            "P&L%": "Profit Percentage",
            "ROI/Day": "ROI per day"
        })

        df_new = df_new[[
            "Date", "Symbol", "Invested Amount", "Absolute Profit",
            "Yield Per Day", "Age of Stock", "Profit Percentage", "ROI per day"
        ]]

        if os.path.exists(self.roi_path):
            df_existing = pd.read_csv(self.roi_path)
        else:
            df_existing = pd.DataFrame(columns=df_new.columns)

        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        df_combined.drop_duplicates(subset=["Date", "Symbol"], keep="last", inplace=True)
        df_combined.to_csv(self.roi_path, index=False)
        logging.info(f"ROI results written to {self.roi_path}")

    # ──────────────── Holdings Analysis ──────────────── #
    def analyze_symbol_trend(self, symbol: str):
        try:
            if not os.path.exists(self.roi_path):
                return None
            df = pd.read_csv(self.roi_path)
            df["Date"] = pd.to_datetime(df["Date"], errors='coerce')
            df = df[df["Symbol"].str.upper() == symbol.upper()]
            df = df.sort_values(by="Date", ascending=False)
            latest = df.head(5)["ROI per day"].tolist()
            if len(latest) < 2:
                return None
            direction = "UP" if latest[-1] > latest[0] else "DOWN" if latest[-1] < latest[0] else "FLAT"
            return (direction, len(latest))
        except Exception:
            return None

    def apply_filters(self, results: List[Dict], filters: Dict) -> List[Dict]:
        if not filters:
            return results
        filtered = []
        for r in results:
            match = True
            for key, val in filters.items():
                if key not in r:
                    match = False
                    break
                if isinstance(val, (int, float)):
                    if r[key] < val:
                        match = False
                        break
                elif isinstance(val, str):
                    if str(r[key]).lower() != val.lower():
                        match = False
                        break
            if match:
                filtered.append(r)
        return filtered

    def analyze_holdings(self, kite, cmp_manager, filters=None) -> List[Dict]:
        if filters is None:
            filters = {}

        entry_levels = read_csv(CSV_FILE_PATH)
        quality_map = {s["symbol"].upper(): s.get("Quality", "-") for s in entry_levels}

        trades_df = pd.read_csv(self.tradebook_path)
        trades_df.columns = [col.strip().lower().replace(" ", "_") for col in trades_df.columns]
        trades_df["trade_date"] = pd.to_datetime(trades_df["trade_date"], errors='coerce')
        trades_df = trades_df[trades_df["trade_type"].str.lower() == "buy"]

        holdings = kite.holdings()
        results = []

        for holding in holdings:
            symbol = holding["tradingsymbol"]
            symbol_clean = symbol.replace("#", "").replace("-BE", "").upper()
            quantity = holding["quantity"] + holding.get("t1_quantity", 0)
            avg_price = holding["average_price"]
            invested = quantity * avg_price
            quality = quality_map.get(symbol_clean, "-")

            ltp = holding["last_price"]
            if not ltp:
                ltp = cmp_manager.get_cmp(holding.get("exchange", "NSE"), symbol)
            if not ltp:
                continue

            current_value = quantity * ltp
            pnl = current_value - invested
            pnl_pct = (pnl / invested * 100) if invested else 0
            roi = pnl_pct

            symbol_trades = trades_df[trades_df["symbol"].str.upper() == symbol_clean]
            symbol_trades = symbol_trades.sort_values(by="trade_date", ascending=False)

            qty_needed = quantity
            weighted_sum = 0
            total_qty = 0

            for _, trade in symbol_trades.iterrows():
                if qty_needed <= 0:
                    break
                trade_qty = trade["quantity"]
                trade_date = trade["trade_date"].date()
                used_qty = min(qty_needed, trade_qty)
                weighted_sum += used_qty * trade_date.toordinal()
                total_qty += used_qty
                qty_needed -= used_qty

            if total_qty > 0:
                avg_date_ordinal = weighted_sum / total_qty
                avg_date = datetime.fromordinal(int(avg_date_ordinal)).date()
                days_held = (datetime.today().date() - avg_date).days
            else:
                days_held = 0

            yld_per_day = (pnl / days_held) if days_held > 0 else 0
            roi_per_day = (roi / days_held) if days_held > 0 else 0

            trend_result = self.analyze_symbol_trend(symbol)
            trend_str = f"{trend_result[0]}({trend_result[1]})" if trend_result else "-"

            results.append({
                "Symbol": symbol,
                "Invested": round(invested, 2),
                "P&L": round(pnl, 2),
                "Yld/Day": round(yld_per_day, 2),
                "Age": days_held,
                "P&L%": round(pnl_pct, 2),
                "ROI/Day": round(roi_per_day, 2),
                "Trend": trend_str,
                "Quality": quality
            })

        results = self.apply_filters(results, filters)
        sorted_results = sorted(results, key=lambda x: x["ROI/Day"], reverse=True)
        return sorted_results
