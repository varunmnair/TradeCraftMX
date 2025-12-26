import logging
from typing import List, Dict, Optional

class RiskManager:
    """
    Encapsulates all risk management and position-sizing rules.
    This class assesses market conditions for a symbol and returns adjustments
    to be applied to an investment plan.
    """
    def __init__(self, config: Optional[Dict] = None):
        # Default configuration for risk rules. Can be overridden.
        self.config = {
            "ATR_PERIOD": 14,
            "VOL_GUARD_THRESHOLDS": {
                "HIGH": 0.03, # ATR% >= 3%
                "MEDIUM": 0.02, # ATR% >= 2%
            },
            "VOL_GUARD_SCALES": {
                "HIGH": 0.6,
                "MEDIUM": 0.75,
                "LOW": 0.9,
            },
            "SDT_LEVEL_THRESHOLD": 2,
            "SDT_DROP_PCT_THRESHOLD": 0.04, # 4%
            "SDT_ATR_PCT_THRESHOLD": 0.025, # 2.5%
            "SDT_CAPS": {
                "LEVEL_2": 0.33, # 33% of allocation
                "LEVEL_3": 0.25, # 25% of allocation
            },
            "GAP_DOWN_THRESHOLD": -0.03, # -3%
            "GAP_DOWN_SCALE": 0.15,
            "PER_SYMBOL_RESERVE_PCT": 0.4, # 40%
        }
        if config:
            self.config.update(config)

    def _calculate_atr(self, historical_data: List[Dict]) -> float:
        """Calculates the Average True Range (ATR)."""
        if not historical_data or len(historical_data) < self.config["ATR_PERIOD"]:
            return 0.0
        
        import pandas as pd
        df = pd.DataFrame(historical_data)
        # The Upstox API returns a list of lists. We must assign column names.
        # Format: [timestamp, open, high, low, close, volume, open_interest]
        df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'open_interest']

        # Ensure columns are numeric, coercing errors
        df['high'] = pd.to_numeric(df['high'], errors='coerce')
        df['low'] = pd.to_numeric(df['low'], errors='coerce')
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df.dropna(subset=['high', 'low', 'close'], inplace=True)

        tr1 = df['high'] - df['low']
        tr2 = abs(df['high'] - df['close'].shift(1))
        tr3 = abs(df['low'] - df['close'].shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.ewm(com=self.config["ATR_PERIOD"] - 1, min_periods=self.config["ATR_PERIOD"], adjust=False).mean()
        return atr.iloc[-1] if not atr.empty else 0.0

    def assess_risk_and_get_adjustments(self, scrip_data: Dict) -> Dict:
        """
        Analyzes a scrip's data and returns a dictionary of risk adjustments.
        """
        ltp = scrip_data.get('ltp', 0)
        quote = scrip_data.get('quote', {})
        historical_data = scrip_data.get('historical')
        prev_close = quote.get('ohlc', {}).get('close', ltp) if quote else ltp

        adjustments = {
            "scale_factor": 1.0,
            "sdt_cap_pct": None,
            "per_symbol_reserve_pct": self.config["PER_SYMBOL_RESERVE_PCT"],
            "reasons": []
        }

        # --- 1. Volatility Guard (ATR-aware sizing) ---
        atr = self._calculate_atr(historical_data)
        atr_pct = (atr / ltp) if ltp > 0 and atr > 0 else 0.0
        
        atr_scale = self.config["VOL_GUARD_SCALES"]["LOW"]
        if atr_pct >= self.config["VOL_GUARD_THRESHOLDS"]["HIGH"]:
            atr_scale = self.config["VOL_GUARD_SCALES"]["HIGH"]
            adjustments["reasons"].append(f"VolGuard:HIGH(ATR% {atr_pct:.1%})")
        elif atr_pct >= self.config["VOL_GUARD_THRESHOLDS"]["MEDIUM"]:
            atr_scale = self.config["VOL_GUARD_SCALES"]["MEDIUM"]
            adjustments["reasons"].append(f"VolGuard:MED(ATR% {atr_pct:.1%})")
        adjustments["scale_factor"] *= atr_scale

        # --- 2. Shock-Drop Throttle (SDT) ---
        levels = [scrip_data.get(f"entry{i}") for i in range(1, 4)]
        levels_crossed = sum(1 for p in levels if p is not None and not isinstance(p, str) and ltp <= p)
        session_drop_pct = (prev_close - ltp) / prev_close if prev_close > 0 else 0.0

        sdt_triggered = (levels_crossed >= self.config["SDT_LEVEL_THRESHOLD"] or 
                         session_drop_pct >= self.config["SDT_DROP_PCT_THRESHOLD"] or 
                         atr_pct >= self.config["SDT_ATR_PCT_THRESHOLD"])

        if sdt_triggered:
            if levels_crossed == 2: adjustments["sdt_cap_pct"] = self.config["SDT_CAPS"]["LEVEL_2"]
            elif levels_crossed >= 3: adjustments["sdt_cap_pct"] = self.config["SDT_CAPS"]["LEVEL_3"]
            adjustments["reasons"].append(f"SDT: LvlX:{levels_crossed}, Drop:{session_drop_pct:.1%}, ATR%:{atr_pct:.1%}")

        # --- 3. Gap Guard ---
        open_price = quote.get('ohlc', {}).get('open', ltp) if quote else ltp
        gap_down_pct = (open_price - prev_close) / prev_close if prev_close > 0 else 0.0
        if gap_down_pct <= self.config["GAP_DOWN_THRESHOLD"]:
            adjustments["scale_factor"] *= self.config["GAP_DOWN_SCALE"]
            adjustments["reasons"].append(f"GapGuard: {gap_down_pct:.1%}")

        return adjustments
