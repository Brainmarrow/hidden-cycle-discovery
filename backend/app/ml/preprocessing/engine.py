"""
MODULE 1: PREPROCESSING ENGINE
================================
Transforms raw OHLCV data into analysis-ready series:
- Returns, log-returns, detrended, normalized, volatility-adjusted
- Missing data handling, outlier detection, resampling
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple

import numpy as np
import pandas as pd
from scipy import signal, stats
from sklearn.preprocessing import RobustScaler, StandardScaler, MinMaxScaler

logger = logging.getLogger(__name__)


class NormalizationMethod(str, Enum):
    ZSCORE = "zscore"
    ROBUST = "robust"
    MINMAX = "minmax"
    NONE = "none"


class OutlierMethod(str, Enum):
    WINSORIZE = "winsorize"
    IQR = "iqr"
    ZSCORE = "zscore"
    NONE = "none"


class DetrendMethod(str, Enum):
    LINEAR = "linear"
    HP_FILTER = "hp_filter"
    ROLLING_MEAN = "rolling_mean"
    POLYNOMIAL = "polynomial"
    NONE = "none"


@dataclass
class PreprocessingConfig:
    # Missing data
    max_gap_fill_bars: int = 5       # Fill gaps up to N bars via interpolation
    forward_fill_limit: int = 2

    # Outliers
    outlier_method: OutlierMethod = OutlierMethod.WINSORIZE
    winsorize_limits: Tuple[float, float] = (0.005, 0.005)  # 0.5% each tail
    zscore_threshold: float = 4.0

    # Detrending
    detrend_method: DetrendMethod = DetrendMethod.HP_FILTER
    hp_lambda: float = 1600.0
    rolling_window: int = 252
    poly_degree: int = 2

    # Normalization
    normalization: NormalizationMethod = NormalizationMethod.ROBUST

    # Returns
    log_returns: bool = True
    returns_period: int = 1

    # Volatility
    vol_window: int = 20
    vol_annualize: bool = True
    annualization_factor: int = 252  # Trading days per year

    # Resampling
    resample_to: Optional[str] = None  # e.g. 'D', 'W', 'M'


@dataclass
class PreprocessedData:
    """Container for all preprocessed series."""
    raw: pd.Series
    returns: pd.Series
    log_returns: pd.Series
    detrended: pd.Series
    normalized: pd.Series
    vol_adjusted: pd.Series
    volatility: pd.Series
    index: pd.DatetimeIndex
    config: PreprocessingConfig
    metadata: dict = field(default_factory=dict)

    @property
    def n_bars(self) -> int:
        return len(self.raw)

    def to_dict(self) -> dict:
        return {
            "raw": self.raw.tolist(),
            "returns": self.returns.tolist(),
            "log_returns": self.log_returns.tolist(),
            "detrended": self.detrended.tolist(),
            "normalized": self.normalized.tolist(),
            "vol_adjusted": self.vol_adjusted.tolist(),
            "volatility": self.volatility.tolist(),
            "timestamps": self.index.strftime("%Y-%m-%dT%H:%M:%SZ").tolist(),
            "metadata": self.metadata,
        }


class PreprocessingEngine:
    """
    Institutional-grade preprocessing pipeline.
    Converts raw OHLCV → analysis-ready series for all downstream modules.
    """

    def __init__(self, config: Optional[PreprocessingConfig] = None):
        self.config = config or PreprocessingConfig()

    # ─── Public API ──────────────────────────────────────────────────────

    def process(self, df: pd.DataFrame) -> PreprocessedData:
        """
        Main entry point. Takes raw OHLCV DataFrame and returns PreprocessedData.

        Args:
            df: DataFrame with columns [open, high, low, close, volume]
                and DatetimeIndex.

        Returns:
            PreprocessedData with all derived series.
        """
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]

        # 1. Validate & clean
        df = self._validate_and_clean(df)

        # 2. Handle missing data
        df = self._handle_missing(df)

        # 3. Resample if requested
        if self.config.resample_to:
            df = self._resample(df)

        # 4. Handle outliers in close prices
        close_clean = self._handle_outliers(df["close"])

        # 5. Compute returns
        returns = self._compute_returns(close_clean, log=False)
        log_returns = self._compute_returns(close_clean, log=True)

        # 6. Handle outliers in returns
        log_returns = self._handle_outliers(log_returns)

        # 7. Detrend
        detrended = self._detrend(close_clean)

        # 8. Normalize
        normalized = self._normalize(detrended)

        # 9. Compute volatility
        volatility = self._compute_volatility(log_returns)

        # 10. Volatility-adjusted returns
        vol_adjusted = self._vol_adjust(log_returns, volatility)

        metadata = {
            "n_bars": len(df),
            "start": str(df.index[0]),
            "end": str(df.index[-1]),
            "missing_bars_filled": self._missing_filled,
            "outliers_clipped": self._outliers_clipped,
            "price_range": (float(close_clean.min()), float(close_clean.max())),
            "annualized_vol": float(volatility.mean() * np.sqrt(self.config.annualization_factor)),
        }

        return PreprocessedData(
            raw=close_clean,
            returns=returns,
            log_returns=log_returns,
            detrended=detrended,
            normalized=normalized,
            vol_adjusted=vol_adjusted,
            volatility=volatility,
            index=df.index,
            config=self.config,
            metadata=metadata,
        )

    # ─── Private methods ─────────────────────────────────────────────────

    _missing_filled: int = 0
    _outliers_clipped: int = 0

    def _validate_and_clean(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure required columns exist and index is datetime."""
        required = ["close"]
        for col in required:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")

        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

        df = df.sort_index()
        df = df[~df.index.duplicated(keep="first")]

        # Remove rows where close is zero or negative
        df = df[df["close"] > 0]

        return df

    def _handle_missing(self, df: pd.DataFrame) -> pd.DataFrame:
        """Fill small gaps via interpolation; flag large gaps."""
        initial_na = df["close"].isna().sum()

        df["close"] = df["close"].interpolate(
            method="time", limit=self.config.max_gap_fill_bars
        )
        df["close"] = df["close"].ffill(limit=self.config.forward_fill_limit)

        self._missing_filled = initial_na - df["close"].isna().sum()

        if df["close"].isna().sum() > 0:
            logger.warning(f"Dropping {df['close'].isna().sum()} bars with unfillable NaN close prices")
            df = df.dropna(subset=["close"])

        return df

    def _handle_outliers(self, series: pd.Series) -> pd.Series:
        """Detect and clip outliers."""
        method = self.config.outlier_method
        initial = len(series)

        if method == OutlierMethod.WINSORIZE:
            from scipy.stats import mstats
            arr = mstats.winsorize(series.values, limits=self.config.winsorize_limits)
            result = pd.Series(arr, index=series.index, name=series.name)

        elif method == OutlierMethod.IQR:
            q1 = series.quantile(0.25)
            q3 = series.quantile(0.75)
            iqr = q3 - q1
            lower = q1 - 3.0 * iqr
            upper = q3 + 3.0 * iqr
            result = series.clip(lower=lower, upper=upper)

        elif method == OutlierMethod.ZSCORE:
            z = np.abs(stats.zscore(series.dropna()))
            mask = z < self.config.zscore_threshold
            result = series[mask].reindex(series.index).interpolate(method="time")

        else:
            result = series

        self._outliers_clipped = (result != series).sum()
        return result

    def _compute_returns(self, series: pd.Series, log: bool = True) -> pd.Series:
        """Compute simple or log returns."""
        period = self.config.returns_period
        if log:
            ret = np.log(series / series.shift(period))
        else:
            ret = series.pct_change(period)
        return ret.dropna().reindex(series.index)

    def _detrend(self, series: pd.Series) -> pd.Series:
        """Remove trend component from price series."""
        method = self.config.detrend_method
        clean = series.dropna()

        if method == DetrendMethod.LINEAR:
            detrended_vals = signal.detrend(clean.values, type="linear")
            return pd.Series(detrended_vals, index=clean.index).reindex(series.index)

        elif method == DetrendMethod.HP_FILTER:
            try:
                from statsmodels.tsa.filters.hp_filter import hpfilter
                _, trend = hpfilter(clean.values, lamb=self.config.hp_lambda)
                detrended_vals = clean.values - trend
                return pd.Series(detrended_vals, index=clean.index).reindex(series.index)
            except Exception as e:
                logger.warning(f"HP filter failed: {e}, falling back to linear detrend")
                return self._detrend_linear(series)

        elif method == DetrendMethod.ROLLING_MEAN:
            window = self.config.rolling_window
            trend = series.rolling(window=window, center=True, min_periods=window // 4).mean()
            return (series - trend).fillna(0)

        elif method == DetrendMethod.POLYNOMIAL:
            x = np.arange(len(clean))
            coeffs = np.polyfit(x, clean.values, deg=self.config.poly_degree)
            trend = np.polyval(coeffs, x)
            detrended_vals = clean.values - trend
            return pd.Series(detrended_vals, index=clean.index).reindex(series.index)

        else:
            return series

    def _detrend_linear(self, series: pd.Series) -> pd.Series:
        clean = series.dropna()
        detrended_vals = signal.detrend(clean.values, type="linear")
        return pd.Series(detrended_vals, index=clean.index).reindex(series.index)

    def _normalize(self, series: pd.Series) -> pd.Series:
        """Normalize series to remove scale effects."""
        method = self.config.normalization
        clean = series.dropna()
        values = clean.values.reshape(-1, 1)

        if method == NormalizationMethod.ZSCORE:
            scaler = StandardScaler()
        elif method == NormalizationMethod.ROBUST:
            scaler = RobustScaler()
        elif method == NormalizationMethod.MINMAX:
            scaler = MinMaxScaler(feature_range=(-1, 1))
        else:
            return series

        normalized_vals = scaler.fit_transform(values).flatten()
        return pd.Series(normalized_vals, index=clean.index).reindex(series.index)

    def _compute_volatility(self, log_returns: pd.Series) -> pd.Series:
        """Rolling realized volatility."""
        window = self.config.vol_window
        vol = log_returns.rolling(window=window, min_periods=window // 2).std()

        if self.config.vol_annualize:
            vol = vol * np.sqrt(self.config.annualization_factor)

        return vol.fillna(method="bfill")

    def _vol_adjust(self, log_returns: pd.Series, volatility: pd.Series) -> pd.Series:
        """Volatility-normalized returns (Kelly-style scaling)."""
        # Target annualized vol of 16% (1 std dev)
        target_vol = 0.16 / np.sqrt(self.config.annualization_factor)
        vol_daily = volatility / np.sqrt(self.config.annualization_factor)
        scale = (target_vol / vol_daily.clip(lower=1e-8)).clip(upper=3.0)
        return (log_returns * scale).fillna(0)

    def _resample(self, df: pd.DataFrame) -> pd.DataFrame:
        """Resample OHLCV to lower frequency."""
        rule = self.config.resample_to
        resampled = df.resample(rule).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum" if "volume" in df.columns else "first",
        }).dropna(subset=["close"])
        return resampled

    # ─── Utilities ───────────────────────────────────────────────────────

    @staticmethod
    def from_csv(filepath: str, config: Optional[PreprocessingConfig] = None) -> PreprocessedData:
        """Convenience: load CSV and preprocess."""
        df = pd.read_csv(filepath, parse_dates=True, index_col=0)
        engine = PreprocessingEngine(config)
        return engine.process(df)

    @staticmethod
    def get_analysis_series(preprocessed: PreprocessedData, series_type: str = "detrended") -> pd.Series:
        """Select the best series for a given analysis type."""
        mapping = {
            "cycle": "detrended",
            "pattern": "normalized",
            "volatility": "volatility",
            "analog": "normalized",
            "ml": "vol_adjusted",
        }
        series_key = mapping.get(series_type, series_type)
        return getattr(preprocessed, series_key)
