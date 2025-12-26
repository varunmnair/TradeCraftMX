import logging
import pandas as pd
from datetime import datetime

DEFAULT_CONFIG = {
    "ATR_PERIOD": 14,
    "RSI_PERIOD": 14,
    "ADX_PERIOD": 14,
    "INDICATOR_WINDOW": 14,
    "REGIME_THRESHOLDS": {
        "ADX_TRENDING": 25,
        "RSI_OVERSOLD": 35,
        "RSI_OVERBOUGHT": 70,
        "ATR_PCT_VOLATILE": 4.0,
    },
    "REVISION_LOGIC": {
        "TRENDING_UP": {"l1_atr": 1.0, "l2_atr": 2.0, "l3_atr": 3.0},
        "RANGING": {"l1_atr": 1.5, "l2_atr": 2.5, "l3_atr": 3.5},
        "VOLATILE_DROP": {"l1_atr": 2.0, "l2_atr": 3.5, "l3_atr": 5.0},
        "DEFAULT": {"l1_atr": 1.25, "l2_atr": 2.25, "l3_atr": 3.25},
    }
}

class EntryLevelReviser:
    def __init__(self, symbol, session, all_entry_levels, config=None):
        self.symbol = symbol
        self.session = session
        self.all_entry_levels = all_entry_levels
        self.config = config or DEFAULT_CONFIG
        self.historical_data = None
        self.metrics = {}

    def _fetch_data(self):
        """Fetches historical data for the symbol."""
        try:
            # Find the original scrip to get the correct exchange
            original_scrip = self._find_original_scrip()
            if not original_scrip:
                raise ValueError(f"Could not find entry level data for {self.symbol} to determine exchange.")
            exchange = original_scrip.get("exchange", "NSE")
            # Fetch more data to ensure indicators are stable
            self.historical_data = self.session.get_historical_data(self.symbol, exchange, 'day')
            if not self.historical_data or len(self.historical_data) < 50:
                raise ValueError("Insufficient historical data for analysis.")
            
            # Convert to DataFrame for easier processing
            self.df = pd.DataFrame(self.historical_data)
            # The Upstox API returns a list of lists, so we need to name the columns.
            # Format: [timestamp, open, high, low, close, volume, open_interest]
            self.df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'open_interest']

            self.df['timestamp'] = pd.to_datetime(self.df['timestamp'], format='%Y-%m-%dT%H:%M:%S%z')
            self.df.set_index('timestamp', inplace=True)
            for col in ['open', 'high', 'low', 'close', 'volume']:
                self.df[col] = pd.to_numeric(self.df[col])
            
            self.metrics['ltp'] = self.df['close'].iloc[-1]

        except Exception as e:
            logging.error(f"Failed to fetch or process data for {self.symbol}: {e}")
            raise

    def _calculate_indicators(self):
        """Calculates all required technical indicators."""
        # ATR
        high_low = self.df['high'] - self.df['low']
        high_close = (self.df['high'] - self.df['close'].shift()).abs()
        low_close = (self.df['low'] - self.df['close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1/self.config['ATR_PERIOD'], adjust=False).mean()
        self.metrics['atr'] = atr.iloc[-1]
        self.metrics['atr_pct'] = (self.metrics['atr'] / self.metrics['ltp'] * 100) if self.metrics['ltp'] > 0 else 0

        # RSI
        delta = self.df['close'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/self.config['RSI_PERIOD'], adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/self.config['RSI_PERIOD'], adjust=False).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        self.metrics[f'rsi_{self.config["INDICATOR_WINDOW"]}'] = rsi.iloc[-1]

        # ADX
        plus_dm = self.df['high'].diff()
        minus_dm = self.df['low'].diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm > 0] = 0
        
        tr_adx = tr.ewm(alpha=1/self.config['ADX_PERIOD'], adjust=False).mean()
        plus_di = 100 * (plus_dm.ewm(alpha=1/self.config['ADX_PERIOD'], adjust=False).mean() / tr_adx)
        minus_di = 100 * (abs(minus_dm.ewm(alpha=1/self.config['ADX_PERIOD'], adjust=False).mean()) / tr_adx)
        dx = 100 * (abs(plus_di - minus_di) / (plus_di + minus_di))
        adx = dx.ewm(alpha=1/self.config['ADX_PERIOD'], adjust=False).mean()
        self.metrics[f'adx_{self.config["ADX_PERIOD"]}'] = adx.iloc[-1]

    def _determine_regime(self):
        """Determines the market regime based on indicators."""
        adx = self.metrics.get(f'adx_{self.config["ADX_PERIOD"]}')
        rsi = self.metrics.get(f'rsi_{self.config["INDICATOR_WINDOW"]}')
        atr_pct = self.metrics.get('atr_pct')
        
        thresholds = self.config['REGIME_THRESHOLDS']

        if atr_pct > thresholds['ATR_PCT_VOLATILE']:
            self.metrics['regime'] = "VOLATILE_DROP"
            return
        
        if adx > thresholds['ADX_TRENDING']:
            self.metrics['regime'] = "TRENDING_UP"
            return

        if rsi < thresholds['RSI_OVERSOLD']:
            self.metrics['regime'] = "RANGING" # Could be bottoming
            return

        self.metrics['regime'] = "DEFAULT"

    def _get_new_levels(self):
        """Calculates new entry levels based on the determined regime."""
        regime = self.metrics.get('regime', 'DEFAULT')
        logic = self.config['REVISION_LOGIC'].get(regime, self.config['REVISION_LOGIC']['DEFAULT'])
        
        ltp = self.metrics['ltp']
        atr = self.metrics['atr']
        
        l1 = ltp - (logic['l1_atr'] * atr)
        l2 = ltp - (logic['l2_atr'] * atr)
        l3 = ltp - (logic['l3_atr'] * atr)

        rationale = f"Regime: {regime}. Using ATR multiples: {logic['l1_atr']}, {logic['l2_atr']}, {logic['l3_atr']}."

        return {"l1": l1, "l2": l2, "l3": l3}, rationale

    def _find_original_scrip(self):
        """Finds the original entry level data for the symbol."""
        for scrip in self.all_entry_levels:
            if scrip.get('symbol') == self.symbol:
                return scrip
        return None

    def revise_entry_levels(self):
        """
        The main method to orchestrate the revision process.
        """
        try:
            # 1. Fetch data
            self._fetch_data()

            # 2. Calculate indicators
            self._calculate_indicators()

            # 3. Determine market regime
            self._determine_regime()

            # 4. Calculate new levels
            new_levels, rationale = self._get_new_levels()

            # 5. Get original levels for comparison
            original_scrip = self._find_original_scrip()
            if not original_scrip:
                raise ValueError(f"Original scrip data not found for {self.symbol}")

            original_levels = {
                "l1": original_scrip.get('entry1', 0),
                "l2": original_scrip.get('entry2', 0),
                "l3": original_scrip.get('entry3', 0)
            }

            # 7. Return the comprehensive result
            return {
                "symbol": self.symbol,
                "original": original_levels,
                "final": new_levels,
                "metrics": self.metrics,
                "rationale": rationale
            }

        except Exception as e:
            logging.error(f"Error during revision for {self.symbol}: {e}")
            # Re-raise to be handled by the caller in cli.py
            raise