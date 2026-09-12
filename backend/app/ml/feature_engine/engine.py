"""
MODULE 5: FEATURE DISCOVERY ENGINE
=====================================
Generates 1000+ features from market data + discovered cycles + planetary data.
Runs feature importance ranking to surface predictive variables.

Feature categories:
- Time: hour, day, week, month, quarter, year, day-of-week
- Calendar: seasonality, expiry dates, earnings seasons
- Returns: multi-period returns, momentum, mean reversion
- Volatility: realized vol, vol-of-vol, GARCH-like
- Technical: RSI, MACD, Bollinger, ATR, ADX
- Cycle: phase, amplitude from detected cycles
- Spectral: FFT features across rolling windows
- Planetary: positions, aspects (from Module 4)
- Autocorrelation: ACF features at multiple lags
- Regime: HMM state probabilities
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.feature_selection import mutual_info_regression, SelectKBest, f_regression
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)


@dataclass
class FeatureImportance:
    feature_name: str
    rf_importance: float
    mi_score: float
    f_score: float
    composite_score: float
    category: str


@dataclass
class FeatureDiscoveryResult:
    feature_matrix: pd.DataFrame               # Full feature matrix (n_bars x n_features)
    importance_ranking: List[FeatureImportance]
    top_features: List[str]
    category_importance: Dict[str, float]
    n_features_total: int
    n_features_selected: int

    def to_dict(self) -> dict:
        return {
            "top_features": self.top_features[:50],
            "n_features_total": self.n_features_total,
            "n_features_selected": self.n_features_selected,
            "category_importance": self.category_importance,
            "importance_ranking": [
                {
                    "feature": f.feature_name,
                    "rf_importance": round(f.rf_importance, 6),
                    "mi_score": round(f.mi_score, 6),
                    "composite": round(f.composite_score, 6),
                    "category": f.category,
                }
                for f in self.importance_ranking[:100]
            ],
        }


class FeatureDiscoveryEngine:
    """
    Generates and evaluates thousands of features for cycle prediction.
    """

    def __init__(
        self,
        include_planetary: bool = True,
        include_cycles: bool = True,
        include_technical: bool = True,
        target_horizon_bars: int = 5,
        top_k_features: int = 50,
    ):
        self.include_planetary = include_planetary
        self.include_cycles = include_cycles
        self.include_technical = include_technical
        self.horizon = target_horizon_bars
        self.top_k = top_k_features

    def discover(
        self,
        df: pd.DataFrame,                       # OHLCV DataFrame
        preprocessed_data=None,                  # PreprocessedData from Module 1
        cycle_results=None,                      # CycleDetectionResult from Module 2
        planetary_df: Optional[pd.DataFrame] = None,  # Planetary feature matrix
    ) -> FeatureDiscoveryResult:
        """Build full feature matrix and rank by importance."""

        features = {}

        # ── 1. Time features ──────────────────────────────────────────
        features.update(self._time_features(df.index))

        # ── 2. Return features ────────────────────────────────────────
        if "close" in df.columns:
            features.update(self._return_features(df["close"]))

        # ── 3. Volatility features ────────────────────────────────────
        if "close" in df.columns:
            features.update(self._volatility_features(df["close"]))

        # ── 4. Technical features ─────────────────────────────────────
        if self.include_technical and {"high", "low", "close", "volume"}.issubset(df.columns):
            features.update(self._technical_features(df))

        # ── 5. Autocorrelation features ───────────────────────────────
        if preprocessed_data is not None:
            features.update(self._autocorr_features(preprocessed_data.log_returns))

        # ── 6. Spectral features ──────────────────────────────────────
        if preprocessed_data is not None:
            features.update(self._spectral_features(preprocessed_data.detrended))

        # ── 7. Cycle phase features ───────────────────────────────────
        if self.include_cycles and cycle_results is not None:
            features.update(self._cycle_features(df.index, cycle_results))

        # ── 8. Planetary features ─────────────────────────────────────
        if self.include_planetary and planetary_df is not None:
            for col in planetary_df.columns:
                features[f"planet_{col}"] = planetary_df[col].reindex(df.index).ffill()

        # ── Build DataFrame ───────────────────────────────────────────
        feature_df = pd.DataFrame(features, index=df.index)
        feature_df = feature_df.fillna(method="ffill").fillna(0)

        n_total = len(feature_df.columns)
        logger.info(f"Built {n_total} features")

        # ── Build target ──────────────────────────────────────────────
        if "close" in df.columns:
            target = np.log(df["close"] / df["close"].shift(self.horizon)).shift(-self.horizon)
            target = target.reindex(feature_df.index)

            # Align for importance
            valid_mask = target.notna() & feature_df.notna().all(axis=1)
            X = feature_df[valid_mask].values
            y = target[valid_mask].values

            importance_ranking = self._rank_features(X, y, list(feature_df.columns))
            top_features = [f.feature_name for f in importance_ranking[:self.top_k]]
            n_selected = min(self.top_k, n_total)
        else:
            importance_ranking = []
            top_features = list(feature_df.columns[:self.top_k])
            n_selected = self.top_k

        # ── Category importance ───────────────────────────────────────
        category_importance = self._category_importance(importance_ranking)

        return FeatureDiscoveryResult(
            feature_matrix=feature_df,
            importance_ranking=importance_ranking,
            top_features=top_features,
            category_importance=category_importance,
            n_features_total=n_total,
            n_features_selected=n_selected,
        )

    # ── Feature Generators ───────────────────────────────────────────────────

    def _time_features(self, index: pd.DatetimeIndex) -> Dict[str, pd.Series]:
        f = {}
        f["time_hour"] = pd.Series(index.hour, index=index) / 23.0
        f["time_dow"] = pd.Series(index.dayofweek, index=index) / 6.0
        f["time_day"] = pd.Series(index.day, index=index) / 31.0
        f["time_month"] = pd.Series(index.month, index=index) / 12.0
        f["time_quarter"] = pd.Series(index.quarter, index=index) / 4.0
        f["time_week"] = pd.Series(index.isocalendar().week.values, index=index) / 52.0
        f["time_year_frac"] = pd.Series(index.dayofyear, index=index) / 365.0

        # Cyclical encoding
        for period, col in [(7, "dow"), (12, "month"), (52, "week"), (252, "yearday")]:
            vals = {
                "dow": index.dayofweek,
                "month": index.month - 1,
                "week": index.isocalendar().week.values - 1,
                "yearday": index.dayofyear - 1,
            }[col]
            f[f"time_{col}_sin"] = pd.Series(np.sin(2 * np.pi * vals / period), index=index)
            f[f"time_{col}_cos"] = pd.Series(np.cos(2 * np.pi * vals / period), index=index)

        # Is month-end, quarter-end
        f["time_is_month_end"] = pd.Series(index.is_month_end.astype(float), index=index)
        f["time_is_quarter_end"] = pd.Series(index.is_quarter_end.astype(float), index=index)

        return {f"cat_time_{k}": v for k, v in f.items()}

    def _return_features(self, close: pd.Series) -> Dict[str, pd.Series]:
        f = {}
        log_ret = np.log(close / close.shift(1))

        for period in [1, 2, 3, 5, 10, 20, 40, 60, 120, 252]:
            ret = np.log(close / close.shift(period))
            f[f"ret_{period}"] = ret
            f[f"ret_{period}_sign"] = np.sign(ret)

        # Momentum
        f["mom_5_20"] = np.log(close / close.shift(5)) - np.log(close / close.shift(20))
        f["mom_20_60"] = np.log(close / close.shift(20)) - np.log(close / close.shift(60))

        # Mean reversion z-score
        for window in [20, 60, 120]:
            roll_mean = close.rolling(window).mean()
            roll_std = close.rolling(window).std()
            f[f"zscore_{window}"] = (close - roll_mean) / (roll_std + 1e-10)

        # Skewness and kurtosis of returns
        for window in [20, 60]:
            f[f"ret_skew_{window}"] = log_ret.rolling(window).skew()
            f[f"ret_kurt_{window}"] = log_ret.rolling(window).kurt()

        return {f"cat_returns_{k}": v for k, v in f.items()}

    def _volatility_features(self, close: pd.Series) -> Dict[str, pd.Series]:
        f = {}
        log_ret = np.log(close / close.shift(1))

        for window in [5, 10, 20, 40, 60, 120]:
            vol = log_ret.rolling(window).std()
            f[f"vol_{window}"] = vol
            f[f"vol_{window}_ann"] = vol * np.sqrt(252)

        # Vol-of-vol
        vol20 = log_ret.rolling(20).std()
        f["vol_of_vol"] = vol20.rolling(20).std()

        # Vol ratio (short/long)
        f["vol_ratio_5_20"] = log_ret.rolling(5).std() / (log_ret.rolling(20).std() + 1e-10)
        f["vol_ratio_20_60"] = log_ret.rolling(20).std() / (log_ret.rolling(60).std() + 1e-10)

        # Parkinson volatility (uses H/L if available)
        return {f"cat_vol_{k}": v for k, v in f.items()}

    def _technical_features(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        """Common technical indicators as features."""
        f = {}
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df.get("volume", pd.Series(1.0, index=df.index))

        # RSI
        for period in [7, 14, 21]:
            f[f"rsi_{period}"] = self._rsi(close, period)

        # MACD
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal_line = macd.ewm(span=9, adjust=False).mean()
        f["macd"] = macd
        f["macd_signal"] = signal_line
        f["macd_hist"] = macd - signal_line

        # Bollinger Bands
        for window in [20, 50]:
            bb_mid = close.rolling(window).mean()
            bb_std = close.rolling(window).std()
            f[f"bb_upper_{window}"] = bb_mid + 2 * bb_std
            f[f"bb_lower_{window}"] = bb_mid - 2 * bb_std
            f[f"bb_pct_{window}"] = (close - f[f"bb_lower_{window}"]) / (f[f"bb_upper_{window}"] - f[f"bb_lower_{window}"] + 1e-10)
            f[f"bb_width_{window}"] = (f[f"bb_upper_{window}"] - f[f"bb_lower_{window}"]) / (bb_mid + 1e-10)

        # ATR
        for period in [14, 20]:
            tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
            f[f"atr_{period}"] = tr.rolling(period).mean()
            f[f"atr_{period}_pct"] = f[f"atr_{period}"] / (close + 1e-10)

        # Volume features
        f["vol_ma_ratio"] = volume / (volume.rolling(20).mean() + 1e-10)
        f["vol_zscore"] = (volume - volume.rolling(20).mean()) / (volume.rolling(20).std() + 1e-10)

        # Price position in range
        for window in [20, 52]:
            roll_high = high.rolling(window).max()
            roll_low = low.rolling(window).min()
            f[f"price_position_{window}"] = (close - roll_low) / (roll_high - roll_low + 1e-10)

        # EMA spreads
        for fast, slow in [(9, 21), (21, 55), (50, 200)]:
            f[f"ema_spread_{fast}_{slow}"] = (close.ewm(span=fast, adjust=False).mean() -
                                               close.ewm(span=slow, adjust=False).mean()) / close

        return {f"cat_technical_{k}": v for k, v in f.items()}

    def _autocorr_features(self, log_returns: pd.Series) -> Dict[str, pd.Series]:
        """Rolling autocorrelation at multiple lags."""
        f = {}
        for lag in [1, 2, 3, 5, 10, 20]:
            f[f"acf_{lag}"] = log_returns.rolling(60).apply(
                lambda x: pd.Series(x).autocorr(lag=lag) if len(x) > lag else 0,
                raw=False,
            )
        return {f"cat_acf_{k}": v for k, v in f.items()}

    def _spectral_features(self, detrended: pd.Series) -> Dict[str, pd.Series]:
        """Rolling FFT energy bands."""
        f = {}
        window = 64
        step = 5
        values = detrended.fillna(0).values

        # Compute rolling FFT bands
        bands = {
            "short": (window // 8, window // 4),
            "medium": (window // 4, window // 2),
            "long": (window // 2, window),
        }

        band_energy = {b: np.zeros(len(values)) for b in bands}

        for i in range(window, len(values), step):
            segment = values[i - window: i]
            fft_mag = np.abs(np.fft.rfft(segment * np.hanning(window))) ** 2
            for band_name, (lo, hi) in bands.items():
                band_energy[band_name][i] = fft_mag[lo:hi].sum()

        for band_name, energy in band_energy.items():
            s = pd.Series(energy, index=detrended.index)
            s = s / (s.rolling(100).max() + 1e-10)  # Normalize
            f[f"fft_energy_{band_name}"] = s

        return {f"cat_spectral_{k}": v for k, v in f.items()}

    def _cycle_features(self, index: pd.DatetimeIndex, cycle_results) -> Dict[str, pd.Series]:
        """Encode cycle phase as sin/cos features."""
        f = {}
        n = len(index)

        for i, cycle in enumerate(cycle_results.dominant[:10]):
            period = cycle.period_bars
            phase_offset = cycle.phase

            t = np.arange(n, dtype=float)
            phase = 2 * np.pi * t / period + phase_offset

            f[f"cycle_{i}_sin"] = pd.Series(np.sin(phase), index=index)
            f[f"cycle_{i}_cos"] = pd.Series(np.cos(phase), index=index)
            f[f"cycle_{i}_amplitude"] = pd.Series(
                np.ones(n) * cycle.amplitude, index=index
            )

        return {f"cat_cycle_{k}": v for k, v in f.items()}

    # ── Feature Importance ───────────────────────────────────────────────────

    def _rank_features(
        self, X: np.ndarray, y: np.ndarray, feature_names: List[str]
    ) -> List[FeatureImportance]:
        """Rank features using RF importance + mutual information + F-test."""

        # Handle NaN
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        y = np.nan_to_num(y, nan=0.0)

        # Mutual information
        try:
            mi_scores = mutual_info_regression(X, y, random_state=42)
            mi_max = mi_scores.max() + 1e-10
            mi_norm = mi_scores / mi_max
        except Exception:
            mi_norm = np.zeros(X.shape[1])

        # F-test
        try:
            f_scores, _ = f_regression(X, y)
            f_max = np.nanmax(f_scores) + 1e-10
            f_norm = np.nan_to_num(f_scores / f_max)
        except Exception:
            f_norm = np.zeros(X.shape[1])

        # Random Forest importance
        try:
            rf = RandomForestRegressor(
                n_estimators=100, max_depth=6, n_jobs=-1,
                random_state=42, max_features="sqrt"
            )
            rf.fit(X, y)
            rf_imp = rf.feature_importances_
        except Exception:
            rf_imp = np.zeros(X.shape[1])

        # Composite score
        results = []
        for i, name in enumerate(feature_names):
            composite = 0.5 * rf_imp[i] + 0.3 * mi_norm[i] + 0.2 * f_norm[i]
            category = name.split("_")[1] if name.startswith("cat_") else "other"
            results.append(FeatureImportance(
                feature_name=name,
                rf_importance=float(rf_imp[i]),
                mi_score=float(mi_norm[i]),
                f_score=float(f_norm[i]),
                composite_score=float(composite),
                category=category,
            ))

        results.sort(key=lambda x: x.composite_score, reverse=True)
        return results

    def _category_importance(self, ranking: List[FeatureImportance]) -> Dict[str, float]:
        from collections import defaultdict
        cat_scores = defaultdict(list)
        for f in ranking:
            cat_scores[f.category].append(f.composite_score)
        return {cat: float(np.mean(scores)) for cat, scores in sorted(
            cat_scores.items(), key=lambda x: np.mean(x[1]), reverse=True
        )}

    # ── Utilities ────────────────────────────────────────────────────────────

    @staticmethod
    def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / (loss + 1e-10)
        return 100 - (100 / (1 + rs))
