import os
import pandas as pd
import logging
from datetime import datetime
from typing import List, Dict

from core.utils import read_csv, write_csv

class HoldingsAnalyzer:
    def __init__(self, user_id: str, broker_name: str):
        self.user_id = user_id
        self.broker_name = broker_name
        self.tradebook_path = f"data/{user_id}-{broker_name}-tradebook.csv"
        self.roi_path = f"data/{user_id}-{broker_name}-roi-data.csv"
        self.entry_levels_path = f"data/{user_id}-{broker_name}-entry-levels.csv"

    # ──────────────── Tradebook Update ──────────────── #
    def update_tradebook(self, broker) -> dict:
        result_summary = {
            "total_records_fetched": 0,
            "records_uploaded": 0,
            "duplicates_skipped": 0,
            "records_failed": 0
        }

        try:
            new_trades = broker.trades()
            new_df = pd.DataFrame(new_trades)
            result_summary["total_records_fetched"] = len(new_df)

            if new_df.empty:
                logging.debug("No new trades found.")
                return result_summary
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

            initial_count = len(new_df)
            new_df = new_df[~new_df["trade_id"].astype(str).isin(existing_ids)]
            result_summary["duplicates_skipped"] = initial_count - len(new_df)

            if not new_df.empty:
                updated_df = pd.concat([existing_df, new_df], ignore_index=True)
                updated_df.to_csv(self.tradebook_path, index=False)
                result_summary["records_uploaded"] = len(new_df)
                logging.info(f"Appended {len(new_df)} new trades to the tradebook: {self.tradebook_path}")
            else:
                logging.info("No new trades to append.")

        except Exception as e:
            logging.error(f"Failed to update tradebook: {e}")
            result_summary["records_failed"] = result_summary["total_records_fetched"]

        return result_summary


    # ──────────────── ROI Writer ──────────────── #
    def write_roi_results(self, results: List[Dict]):
        logging.debug(f"Received {len(results)} results to write to ROI file.")
        os.makedirs(os.path.dirname(self.roi_path), exist_ok=True)
        today = datetime.today()
        if today.weekday() in (5, 6):
            logging.info("Weekend detected. Skipping ROI write.")
            return

        today_str = today.strftime("%Y-%m-%d")
        df_new = pd.DataFrame(results)
        df_new["Date"] = today_str

        # Rename columns for the new data
        df_new = df_new.rename(columns={
            "Symbol": "Symbol",
            "Invested": "Invested Amount",
            "P&L": "Absolute Profit",
            "Yld/Day": "Yield Per Day",
            "Age": "Age of Stock",
            "P&L%": "Profit Percentage",
            "ROI/Day": "ROI per day"
        })

        # Ensure columns are in the correct order
        output_columns = [
            "Date", "Symbol", "Invested Amount", "Absolute Profit",
            "Yield Per Day", "Age of Stock", "Profit Percentage", "ROI per day"
        ]
        df_new = df_new.reindex(columns=output_columns)
        logging.info(f"New records to be added: {len(df_new)}")


        if os.path.exists(self.roi_path):
            df_existing = pd.read_csv(self.roi_path)
            logging.debug(f"Loaded {len(df_existing)} existing records from {self.roi_path}")
        else:
            df_existing = pd.DataFrame(columns=output_columns)
            logging.debug(f"ROI file not found at {self.roi_path}. Creating a new one.")

        # Combine the dataframes
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        logging.debug(f"Total records after combining: {len(df_combined)}")

        # Clean up and standardize before dropping duplicates
        df_combined["Date"] = pd.to_datetime(df_combined["Date"], errors='coerce').dt.strftime("%Y-%m-%d")
        df_combined["Symbol"] = df_combined["Symbol"].str.strip()

        # Drop duplicates, keeping the last (most recent) entry
        df_combined.drop_duplicates(subset=["Date", "Symbol"], keep="last", inplace=True)
        logging.debug(f"Records after dropping duplicates: {len(df_combined)}")
        
        df_combined.to_csv(self.roi_path, index=False)
        logging.info(f"ROI results written to {self.roi_path}")

    # ──────────────── Holdings Analysis ──────────────── #
    def analyze_symbol_trend(self, symbol: str, threshold=0.002):
        """
        Analyze the trend (uptrend or downtrend) for a given symbol in roi-master.csv.
        Returns ("UP", n), ("DOWN", n), or ("FLAT", 1) where n is the number of days the trend has continued.
        Small fluctuations within the threshold are ignored.
        """
        try:
            import pandas as pd
            if not os.path.exists(self.roi_path):
                return None

            df = pd.read_csv(self.roi_path)
            df = df[df["Symbol"].str.upper() == symbol.upper()]
            if df.empty or len(df) < 2:
                return None

            df["Date"] = pd.to_datetime(df["Date"], errors='coerce')
            df = df.sort_values("Date", ascending=True)
            roi_series = df["ROI per day"].values

            trend = None
            count = 1

            for i in range(len(roi_series) - 1, 0, -1):
                today = roi_series[i]
                prev = roi_series[i - 1]
                diff = today - prev

                if trend is None:
                    if abs(diff) <= threshold:
                        return "FLAT", 1
                    trend = "UP" if diff > 0 else "DOWN"
                    count = 1
                else:
                    if trend == "UP" and diff > threshold:
                        count += 1
                    elif trend == "DOWN" and diff < -threshold:
                        count += 1
                    else:
                        break

            return trend, count

        except Exception as e:
            print(f"Error analyzing symbol trend: {e}")
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

    def get_total_invested(self, holdings: List[Dict]) -> float:
        return sum(h["quantity"] * h["average_price"] for h in holdings if h["quantity"] > 0 and h["average_price"] > 0)

    def analyze_holdings(self, broker, cmp_manager, filters=None, sort_by="ROI/Day") -> List[Dict]:
        logging.debug("Analyzing holdings...")
        if filters is None:
            filters = {}

        entry_levels = read_csv(self.entry_levels_path)
        quality_map = {s["symbol"].upper(): s.get("Quality", "-") for s in entry_levels}

        trades_df = pd.read_csv(self.tradebook_path)
        trades_df.columns = [col.strip().lower().replace(" ", "_") for col in trades_df.columns]
        trades_df["trade_date"] = pd.to_datetime(trades_df["trade_date"], errors='coerce')
        trades_df = trades_df[trades_df["trade_type"].str.lower() == "buy"]

        holdings = broker.get_holdings()
        logging.debug(f"Found {len(holdings)} holdings.")
        results = []
        total_invested = self.get_total_invested(holdings)

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
                logging.warning(f"LTP not found for {symbol}. Skipping.")
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
                trade_date = trade["trade_date"]
                if pd.isna(trade_date):
                    logging.warning(f"Skipping trade with invalid date: {trade.to_dict()}")
                    continue
                trade_date = trade_date.date()
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
            weighted_roi = (roi_per_day * invested / total_invested) if total_invested > 0 else 0

            trend_result = self.analyze_symbol_trend(symbol)
            trend_str = trend_result[0] if trend_result else "-"
            trend_days = trend_result[1] if trend_result else None

            results.append({
                "Symbol": symbol,
                "Invested": round(invested, 1),
                "P&L": round(pnl, 1),
                "Yld/Day": round(yld_per_day, 1),
                "Age": days_held,
                "P&L%": round(pnl_pct, 2),
                "ROI/Day": round(roi_per_day, 2),
                "W ROI": round(weighted_roi, 4),
                "Trend": trend_str,
                "Trend Days": trend_days,
                "Quality": quality
            })

        logging.debug(f"Generated {len(results)} results before filtering.")
        results = self.apply_filters(results, filters)
        logging.debug(f"Found {len(results)} results after applying filters.")
        
        sort_key_mapping = {"roi_per_day": "ROI/Day", "weighted_roi": "W ROI"}
        sort_key = sort_key_mapping.get(sort_by, sort_by)

        sorted_results = sorted(results, key=lambda x: x.get(sort_key, 0), reverse=True)
        logging.debug(f"Sorted results by {sort_key}.")
        
        self.write_roi_results(sorted_results)
        
        return sorted_results

    def download_historical_trades(self, broker, start_date, end_date):
        """
        Downloads historical trades from the broker and saves them to a CSV file.
        """
        try:
            logging.info(f"Fetching trades from {start_date} to {end_date} for user {broker.user_id}...")
            trades = broker.download_historical_trades(start_date, end_date)
            
            if trades:
                file_path = f"data/{broker.user_id}-{broker.broker_name}-tradebook.csv"
                write_csv(file_path, trades)
                return {
                    "message": f"Successfully saved {len(trades)} trades to {file_path}",
                    "trade_count": len(trades),
                    "file_path": file_path
                }
            else:
                return {
                    "message": "No trades found for the specified period.",
                    "trade_count": 0,
                    "file_path": None
                }

        except Exception as e:
            logging.error(f"Failed to download historical trades: {e}")
            raise e
