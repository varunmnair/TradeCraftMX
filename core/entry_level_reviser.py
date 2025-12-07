import pandas as pd
import numpy as np
import logging
from brokers.base_broker import BaseBroker

DEFAULT_CONFIG = {
    "INTERVAL": "day",
    "LOOKBACK_DAYS": 90,
    "INDICATOR_WINDOW": 14,
    "EMA_FAST": 20,
    "EMA_SLOW": 50,
    "ADX_PERIOD": 14,
    "LAST_MONTH_DAYS": 21, # Default was 21, user suggested 22. Keeping 21 as it was in code.
    "MIN_SPACING_MULT": 0.5,
    "ROUNDING_UNIT": 1.0,
    "TOUCH_PROB_K": 1.0,
    "MAX_ADJ_FROM_ORIG": 1.5,
    "RSI_BULL_THRESHOLD": 55,
    "RSI_BEAR_THRESHOLD": 45,
    "ADX_BULL_THRESHOLD": 20,
    "P_TOUCH_TARGET_L1": 0.6,
    "P_TOUCH_MAX_L3": 0.9,
}

class EntryLevelReviser:
    """
    Analyzes historical stock data to calculate technical features and suggest revised entry levels.
    """
    def __init__(self, symbol: str, session, all_entry_levels: list, config: dict = None):
        self.symbol = symbol
        self.all_entry_levels = all_entry_levels
        self.session = session
        self.config = DEFAULT_CONFIG.copy()
        if config:
            self.config.update(config)
        self.historical_data: pd.DataFrame = None
        self.features: pd.DataFrame = None
        self.original_levels: dict = None

    def fetch_historical_data(self):
        """
        Fetches historical data using the provided broker instance.
        """
        logging.debug(f"Requesting historical data for {self.symbol} from session...")
        try:
            candles = self.session.get_historical_data(self.symbol, self.config["INTERVAL"], None, None)
            
            if not candles:
                logging.error(f"Failed to fetch historical data for {self.symbol}. The broker returned no data.")
                raise Exception(f"Could not fetch historical data for {self.symbol} (broker returned no data)")

        except Exception as e:
            logging.error(f"An exception occurred while fetching historical data for {self.symbol} via CMPManager: {e}")
            raise Exception(f"Could not fetch historical data for {self.symbol}") from e
            
        logging.debug(f"Successfully fetched {len(candles)} candles for {self.symbol}.")
        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)
        self.historical_data = df
        return self.historical_data

    def load_original_levels(self):
        """
        Loads the original entry levels for the given symbol from the file.
        """
        if not self.all_entry_levels:
            raise Exception("Could not load entry levels as the provided list is empty.")
            
        symbol_levels = [l for l in self.all_entry_levels if 'symbol' in l and str(l['symbol']).upper() == self.symbol.upper()]
        
        if not symbol_levels:
            # For now, let's create dummy original levels if not found, to allow baseline calculation.
            # In a real scenario, you might want to handle this differently.
            ltp = self.historical_data.iloc[-1]['close'] if self.historical_data is not None and not self.historical_data.empty else 100
            self.original_levels = {'l1': ltp * 0.95, 'l2': ltp * 0.90, 'l3': ltp * 0.85}
            return self.original_levels
            
        self.original_levels = {
            'l1': float(symbol_levels[0]['entry1']),
            'l2': float(symbol_levels[0]['entry2']),
            'l3': float(symbol_levels[0]['entry3']),
        }
        return self.original_levels

    def calculate_technical_features(self):
        """
        Calculates various technical indicators on the historical data.
        """
        atr_period = self.config["INDICATOR_WINDOW"]
        rsi_period = self.config["INDICATOR_WINDOW"]
        adx_period = self.config["ADX_PERIOD"]

        if self.historical_data is None:
            self.fetch_historical_data()

        df_out = self.historical_data.copy()

        if not all(col in df_out.columns for col in ['high', 'low', 'close']):
            raise ValueError("Input DataFrame must contain 'high', 'low', and 'close' columns.")

        for period in [self.config["EMA_FAST"], self.config["EMA_SLOW"]]:
            df_out[f'ema_{period}'] = df_out['close'].ewm(span=period, adjust=False).mean()

        delta = df_out['close'].diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        ema_up = up.ewm(com=rsi_period - 1, adjust=False).mean()
        ema_down = down.ewm(com=rsi_period - 1, adjust=False).mean()
        rs = ema_up / ema_down
        df_out[f'rsi_{rsi_period}'] = 100 - (100 / (1 + rs))

        tr1 = df_out['high'] - df_out['low']
        tr2 = abs(df_out['high'] - df_out['close'].shift(1))
        tr3 = abs(df_out['low'] - df_out['close'].shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        atr = tr.ewm(com=atr_period - 1, min_periods=atr_period, adjust=False).mean()
        df_out[f'atr_{atr_period}'] = atr

        move_up = df_out['high'].diff()
        move_down = df_out['low'].diff()
        plus_dm = pd.Series(np.where((move_up > move_down) & (move_up > 0), move_up, 0), index=df_out.index)
        minus_dm = pd.Series(np.where((move_down > move_up) & (move_down > 0), move_down, 0), index=df_out.index)
        smooth_plus_dm = plus_dm.ewm(com=adx_period - 1, min_periods=adx_period, adjust=False).mean()
        smooth_minus_dm = minus_dm.ewm(com=adx_period - 1, min_periods=adx_period, adjust=False).mean()
        plus_di = 100 * (smooth_plus_dm / atr)
        minus_di = 100 * (smooth_minus_dm / atr)
        dx = 100 * (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan))
        dx.fillna(0, inplace=True)
        adx = dx.ewm(com=adx_period - 1, min_periods=adx_period, adjust=False).mean()
        df_out[f'adx_{adx_period}'] = adx

        df_out['monthly_change_pct'] = df_out['close'].pct_change(periods=self.config["LAST_MONTH_DAYS"]) * 100

        self.features = df_out
        return self.features

    def classify_regime(self):
        """
        Classifies the market regime based on technical indicators.
        """
        if self.features is None:
            self.calculate_technical_features()

        rsi_bull_threshold = self.config["RSI_BULL_THRESHOLD"]
        rsi_bear_threshold = self.config["RSI_BEAR_THRESHOLD"]
        adx_bull_threshold = self.config["ADX_BULL_THRESHOLD"]

        df = self.features
        required_cols = [f'ema_{self.config["EMA_FAST"]}', f'ema_{self.config["EMA_SLOW"]}', f'rsi_{self.config["INDICATOR_WINDOW"]}', f'adx_{self.config["ADX_PERIOD"]}']
        if not all(col in df.columns for col in required_cols):
            raise ValueError(f"Missing required columns for regime classification.")

        conditions = [
            (df[f'ema_{self.config["EMA_FAST"]}'] > df[f'ema_{self.config["EMA_SLOW"]}']) & (df[f'rsi_{self.config["INDICATOR_WINDOW"]}'] >= rsi_bull_threshold) & (df[f'adx_{self.config["ADX_PERIOD"]}'] >= adx_bull_threshold),
            (df[f'ema_{self.config["EMA_FAST"]}'] < df[f'ema_{self.config["EMA_SLOW"]}']) & (df[f'rsi_{self.config["INDICATOR_WINDOW"]}'] <= rsi_bear_threshold)
        ]
        choices = ['Bullish', 'Bearish']
        df['regime'] = np.select(conditions, choices, default='Range')
        self.features = df
        return self.features

    def compute_baseline_ladder(self):
        """
        Step 5: Computes the baseline entry ladder based on the current market regime.
        """
        latest_features = self.features.iloc[-1]
        ltp = latest_features['close']
        atr = latest_features[f'atr_{self.config["INDICATOR_WINDOW"]}']
        regime = latest_features['regime']

        multiples = {
            'Bullish': [0.4, 0.8, 1.2],
            'Bearish': [0.6, 1.2, 1.8],
            'Range': [0.5, 1.0, 1.5]
        }
        m = multiples.get(regime, multiples['Range'])
        
        l1 = ltp - m[0] * atr
        l2 = ltp - m[1] * atr
        l3 = ltp - m[2] * atr
        
        return {'l1': l1, 'l2': l2, 'l3': l3}

    def adjust_for_touch_probability(self, ladder):
        """
        Step 6: Adjusts the ladder based on touch probability constraints.
        """
        target_p_l1 = self.config["P_TOUCH_TARGET_L1"]
        max_p_l3 = self.config["P_TOUCH_MAX_L3"]
        k = self.config["TOUCH_PROB_K"]

        latest_features = self.features.iloc[-1]
        ltp = latest_features['close']
        atr = latest_features[f'atr_{self.config["INDICATOR_WINDOW"]}']
        
        l1, l2, l3 = ladder['l1'], ladder['l2'], ladder['l3']
        
        distance_l1 = ltp - l1
        p_touch_l1 = np.exp(-distance_l1 / (k * atr)) if (k * atr) > 0 else 0
        if p_touch_l1 < target_p_l1:
            new_distance_l1 = -np.log(target_p_l1) * k * atr
            l1 = ltp - new_distance_l1

        distance_l3 = ltp - l3
        p_touch_l3 = np.exp(-distance_l3 / (k * atr)) if (k * atr) > 0 else 0
        if p_touch_l3 > max_p_l3:
            new_distance_l3 = -np.log(max_p_l3) * k * atr
            l3 = ltp - new_distance_l3
            l2 = l1 - (l1 - l3) / 2
        
        return {'l1': l1, 'l2': l2, 'l3': l3}

    def _round_to_nearest(self, price, tick_size):
        return round(price / tick_size) * tick_size

    def apply_constraints(self, ladder, original_ladder):
        """
        Step 7: Applies spacing, shift, and rounding constraints.
        """
        min_spacing_mult = self.config["MIN_SPACING_MULT"]
        max_shift_mult = self.config["MAX_ADJ_FROM_ORIG"]
        rounding_tick = self.config["ROUNDING_UNIT"]
        
        latest_features = self.features.iloc[-1]
        atr = latest_features[f'atr_{self.config["INDICATOR_WINDOW"]}']
        
        l1, l2, l3 = ladder['l1'], ladder['l2'], ladder['l3']
        
        # 7.3 Bound shift vs original to reduce whiplash
        max_shift = max_shift_mult * atr
        l1 = np.clip(l1, original_ladder['l1'] - max_shift, original_ladder['l1'] + max_shift)
        l2 = np.clip(l2, original_ladder['l2'] - max_shift, original_ladder['l2'] + max_shift)
        l3 = np.clip(l3, original_ladder['l3'] - max_shift, original_ladder['l3'] + max_shift)

        # 7.2 Enforce minimum spacing (after potential clamping)
        min_spacing = min_spacing_mult * atr
        if l1 - l2 < min_spacing:
            l2 = l1 - min_spacing
        if l2 - l3 < min_spacing:
            l3 = l2 - min_spacing
        
        # 7.4 Round to execution tick
        l1 = self._round_to_nearest(l1, rounding_tick)
        l2 = self._round_to_nearest(l2, rounding_tick)
        l3 = self._round_to_nearest(l3, rounding_tick)
        
        return {'l1': l1, 'l2': l2, 'l3': l3}

    def _generate_summary(self, revision_result):
        """
        Step 9: Generates an action and rationale for the revision.
        """
        # Note: This implementation is a more sophisticated version based on external logic.
        # It assumes `too_far_deep` and `too_close_shallow` would be calculated elsewhere.
        # For this example, we'll set them to False.
        too_far_deep = False
        too_close_shallow = False

        original = revision_result['original']
        final = revision_result['final']
        latest_features = self.features.iloc[-1]
        regime = latest_features['regime']
        atr = latest_features[f'atr_{self.config["INDICATOR_WINDOW"]}']
        
        avg_orig = np.mean(list(original.values()))
        avg_final = np.mean(list(final.values()))
        
        action = "KEEP" # Default action

        if regime == 'Bullish' and (too_far_deep or avg_final > avg_orig):
            action = "UPWARD_ADJUST"
        elif regime == 'Bearish' and (too_close_shallow or avg_final < avg_orig):
            action = "DOWNWARD_ADJUST"
        elif regime == 'Range':
            # In range, only adjust if the change is significant
            delta = np.mean([abs(original[k] - final[k]) for k in original])
            if delta < (0.2 * atr):
                action = "KEEP"
            else:
                if avg_final > avg_orig:
                    action = "UPWARD_ADJUST"
                elif avg_final < avg_orig:
                    action = "DOWNWARD_ADJUST"

        # Build the detailed rationale string
        ind_win = self.config["INDICATOR_WINDOW"]
        adx_p = self.config["ADX_PERIOD"]
        ema_f = self.config["EMA_FAST"]
        ema_s = self.config["EMA_SLOW"]

        old_l = f"[{original['l1']:.2f}, {original['l2']:.2f}, {original['l3']:.2f}]"
        new_l = f"[{final['l1']:.2f}, {final['l2']:.2f}, {final['l3']:.2f}]"

        msg = []
        msg.append(f"Metrics: LTP=₹{latest_features['close']:.2f}, ATR{ind_win}≈₹{atr:.2f}, RSI{ind_win}={latest_features[f'rsi_{ind_win}']:.1f}, ADX{adx_p}={latest_features[f'adx_{adx_p}']:.1f}")
        msg.append(f"EMAs: {ema_f}={latest_features[f'ema_{ema_f}']:.2f}, {ema_s}={latest_features[f'ema_{ema_s}']:.2f}")
        msg.append(f"Last month return: {latest_features['monthly_change_pct']:.2f}%")
        msg.append(f"Levels: {old_l} -> {new_l}")
        
        reasoning = "Reasoning: "
        if regime == 'Bullish':
            reasoning += "Raised ladder closer to LTP to capture shallower pullbacks."
        elif regime == 'Bearish':
            reasoning += "Lowered ladder to be paid for risk in weak trend."
        elif regime == 'Range':
            reasoning += "Centered ladder around neutral multiples."
        msg.append(reasoning)

        # The first line of the rationale is just the regime for quick scanning.
        rationale_str = f"Regime: {regime}\n" + "\n".join(msg)
        
        revision_result['action'] = action
        revision_result['rationale'] = rationale_str
        
        return revision_result

    def revise_entry_levels(self):
        """
        Orchestrates the entire entry level revision process.
        """
        self.classify_regime()
        self.load_original_levels()
        baseline_ladder = self.compute_baseline_ladder()
        prob_adjusted_ladder = self.adjust_for_touch_probability(baseline_ladder)
        final_ladder = self.apply_constraints(prob_adjusted_ladder, self.original_levels)
        
        result = {
            'original': self.original_levels,
            'baseline': baseline_ladder,
            'final': final_ladder,
            'metrics': {
                'ltp': self.features.iloc[-1]['close'],
                'atr': self.features.iloc[-1][f'atr_{self.config["INDICATOR_WINDOW"]}'],
                'regime': self.features.iloc[-1]['regime']
            }
        }
        
        return self._generate_summary(result)