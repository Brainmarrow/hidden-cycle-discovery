"""
MODULE 8: STABILITY ENGINE
============================
Tests whether discovered cycles are statistically stable and persist out-of-sample.

Methods:
1. Walk-Forward Stability  — re-detect cycles on rolling windows, measure consistency
2. Out-of-Sample Strength  — compare IS vs OOS cycle power
3. Cycle Decay Rate        — how fast cycle fades over time
4. Bootstrap Significance  — randomized baseline comparison
5. Stationarity Tests      — ADF, KPSS on cycle components
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)


@dataclass
class CycleStabilityMetrics:
    period_bars: float
    method: str

    # Walk-forward
    wf_detection_rate: float        # % of windows where cycle was detected
    wf_period_stability: float      # Coefficient of variation of detected periods
    wf_power_mean: float
    wf_power_std: float
    wf_n_windows: int

    # OOS
    is_power: float                 # In-sample spectral power
    oos_power: float                # Out-of-sample spectral power
    oos_ratio: float                # oos_power / is_power (1.0 = stable, <1 = decaying)

    # Decay
    decay_rate_per_year: float      # % power loss per year
    half_life_bars: Optional[int]

    # Statistical
    bootstrap_percentile: float     # Where observed power falls in null distribution
    is_significant: bool

    # Composite stability score
    stability_score: float          # 0–1

    def to_dict(self) -> dict:
        return {
            "period_bars": round(self.period_bars, 2),
            "method": self.method,
            "walk_forward": {
                "detection_rate": round(self.wf_detection_rate, 4),
                "period_cv": round(self.wf_period_stability, 4),
                "power_mean": round(self.wf_power_mean, 4),
                "power_std": round(self.wf_power_std, 4),
                "n_windows": self.wf_n_windows,
            },
            "oos": {
                "is_power": round(self.is_power, 4),
                "oos_power": round(self.oos_power, 4),
                "oos_ratio": round(self.oos_ratio, 4),
            },
            "decay": {
                "rate_per_year": round(self.decay_rate_per_year, 4),
                "half_life_bars": self.half_life_bars,
            },
            "statistics": {
                "bootstrap_percentile": round(self.bootstrap_percentile, 4),
                "is_significant": self.is_significant,
            },
            "stability_score": round(self.stability_score, 4),
        }


@dataclass
class StabilityResult:
    cycle_metrics: List[CycleStabilityMetrics]
    stable_cycles: List[CycleStabilityMetrics]
    unstable_cycles: List[CycleStabilityMetrics]
    overall_market_stability: float
    regime_stability: Dict[str, float]

    def to_dict(self) -> dict:
        return {
            "stable_cycles": [c.to_dict() for c in self.stable_cycles],
            "unstable_cycles": [c.to_dict() for c in self.unstable_cycles],
            "all_cycles": [c.to_dict() for c in self.cycle_metrics],
            "overall_market_stability": round(self.overall_market_stability, 4),
            "regime_stability": self.regime_stability,
        }


class StabilityEngine:
    """
    Tests persistence and reliability of detected market cycles.
    """

    def __init__(
        self,
        wf_window_size: Optional[int] = None,  # Walk-forward window in bars
        wf_step_size: Optional[int] = None,
        n_bootstrap: int = 200,
        oos_split: float = 0.3,                  # 30% held out for OOS
        stability_threshold: float = 0.5,
        bars_per_year: float = 252.0,
    ):
        self.wf_window = wf_window_size
        self.wf_step = wf_step_size
        self.n_bootstrap = n_bootstrap
        self.oos_split = oos_split
        self.threshold = stability_threshold
        self.bars_per_year = bars_per_year

    def test(
        self,
        series: pd.Series,
        cycles,  # CycleDetectionResult from Module 2
    ) -> StabilityResult:
        """
        Run stability analysis for each dominant cycle candidate.

        Args:
            series: Preprocessed series (detrended / normalized).
            cycles: CycleDetectionResult from Module 2.
        """
        values = series.dropna().values.astype(np.float64)
        n = len(values)

        # Determine window sizes
        wf_window = self.wf_window or max(n // 5, 60)
        wf_step = self.wf_step or max(wf_window // 4, 10)

        # IS/OOS split
        oos_start = int(n * (1 - self.oos_split))
        is_values = values[:oos_start]
        oos_values = values[oos_start:]

        metrics_list = []

        for candidate in cycles.dominant[:15]:
            logger.debug(f"Testing stability for period={candidate.period_bars:.1f} bars")

            try:
                # ── Walk-forward ─────────────────────────────
                wf = self._walk_forward_test(values, candidate.period_bars, wf_window, wf_step)

                # ── OOS test ─────────────────────────────────
                is_power = self._measure_cycle_power(is_values, candidate.period_bars)
                oos_power = self._measure_cycle_power(oos_values, candidate.period_bars)
                oos_ratio = oos_power / (is_power + 1e-10)

                # ── Decay rate ───────────────────────────────
                decay_rate, half_life = self._estimate_decay(values, candidate.period_bars, wf_window, wf_step)

                # ── Bootstrap significance ───────────────────
                bootstrap_pct = self._bootstrap_significance(values, candidate.period_bars)
                is_significant = bootstrap_pct > (1.0 - 0.05)

                # ── Composite stability score ─────────────────
                stability = self._compute_stability_score(
                    wf_detection_rate=wf["detection_rate"],
                    wf_period_cv=wf["period_cv"],
                    oos_ratio=oos_ratio,
                    bootstrap_pct=bootstrap_pct,
                )

                metrics = CycleStabilityMetrics(
                    period_bars=candidate.period_bars,
                    method=candidate.method,
                    wf_detection_rate=wf["detection_rate"],
                    wf_period_stability=wf["period_cv"],
                    wf_power_mean=wf["power_mean"],
                    wf_power_std=wf["power_std"],
                    wf_n_windows=wf["n_windows"],
                    is_power=float(is_power),
                    oos_power=float(oos_power),
                    oos_ratio=float(np.clip(oos_ratio, 0, 2)),
                    decay_rate_per_year=float(decay_rate),
                    half_life_bars=half_life,
                    bootstrap_percentile=float(bootstrap_pct),
                    is_significant=is_significant,
                    stability_score=stability,
                )
                metrics_list.append(metrics)

            except Exception as e:
                logger.warning(f"Stability test failed for period={candidate.period_bars:.1f}: {e}")
                continue

        # Sort by stability
        metrics_list.sort(key=lambda m: m.stability_score, reverse=True)
        stable = [m for m in metrics_list if m.stability_score >= self.threshold]
        unstable = [m for m in metrics_list if m.stability_score < self.threshold]

        overall = float(np.mean([m.stability_score for m in metrics_list])) if metrics_list else 0.0

        # Regime stability
        regime_stability = self._regime_stability_analysis(values)

        return StabilityResult(
            cycle_metrics=metrics_list,
            stable_cycles=stable,
            unstable_cycles=unstable,
            overall_market_stability=overall,
            regime_stability=regime_stability,
        )

    # ── Walk-Forward ─────────────────────────────────────────────────────────

    def _walk_forward_test(
        self, values: np.ndarray, period: float, window: int, step: int
    ) -> Dict:
        """Re-detect cycle in rolling windows, measure consistency."""
        detected_periods = []
        detected_powers = []

        for start in range(0, len(values) - window, step):
            segment = values[start: start + window]
            if len(segment) < max(20, period * 3):
                continue

            power = self._measure_cycle_power(segment, period)
            if power > 0.01:
                detected_periods.append(period)
                detected_powers.append(power)

        n_windows = max(1, (len(values) - window) // step)
        detection_rate = len(detected_periods) / n_windows

        if not detected_periods:
            return {
                "detection_rate": 0.0,
                "period_cv": 1.0,
                "power_mean": 0.0,
                "power_std": 0.0,
                "n_windows": n_windows,
            }

        period_cv = float(np.std(detected_periods) / (np.mean(detected_periods) + 1e-10))

        return {
            "detection_rate": float(detection_rate),
            "period_cv": float(period_cv),
            "power_mean": float(np.mean(detected_powers)),
            "power_std": float(np.std(detected_powers)),
            "n_windows": n_windows,
        }

    # ── Cycle Power Measurement ───────────────────────────────────────────────

    def _measure_cycle_power(self, values: np.ndarray, period: float) -> float:
        """Measure normalized spectral power at target period via FFT."""
        if len(values) < 10 or period <= 0:
            return 0.0

        n = len(values)
        windowed = values * np.hanning(n)
        fft_vals = np.abs(np.fft.rfft(windowed)) ** 2
        freqs = np.fft.rfftfreq(n)

        target_freq = 1.0 / period
        if target_freq <= 0 or target_freq > 0.5:
            return 0.0

        # Find bin closest to target frequency
        freq_idx = np.argmin(np.abs(freqs - target_freq))
        if freq_idx >= len(fft_vals):
            return 0.0

        # Power at target relative to total
        total_power = fft_vals.sum() + 1e-10
        local_power = fft_vals[max(0, freq_idx - 1): freq_idx + 2].sum()
        return float(local_power / total_power)

    # ── Decay Rate ───────────────────────────────────────────────────────────

    def _estimate_decay(
        self, values: np.ndarray, period: float, window: int, step: int
    ) -> tuple:
        """Estimate how quickly cycle power decays over time (linear regression on power vs time)."""
        powers = []
        times = []

        for i, start in enumerate(range(0, len(values) - window, step)):
            segment = values[start: start + window]
            power = self._measure_cycle_power(segment, period)
            powers.append(power)
            times.append(i)

        if len(powers) < 4:
            return 0.0, None

        times_arr = np.array(times, dtype=float)
        powers_arr = np.array(powers, dtype=float)

        try:
            slope, intercept, r, p, se = stats.linregress(times_arr, powers_arr)
        except Exception:
            return 0.0, None

        # Slope is power change per step; convert to per year
        steps_per_year = self.bars_per_year / max(step, 1)
        decay_per_year = float(-slope * steps_per_year)  # Positive = decaying

        # Half-life: time for power to halve
        if slope < 0 and intercept > 0:
            half_life_steps = intercept / (2 * abs(slope))
            half_life_bars = int(half_life_steps * step)
        else:
            half_life_bars = None

        return decay_per_year, half_life_bars

    # ── Bootstrap Significance ────────────────────────────────────────────────

    def _bootstrap_significance(self, values: np.ndarray, period: float) -> float:
        """
        Compare observed cycle power against power in phase-randomized (null) series.
        Returns the percentile of observed power in the null distribution.
        """
        observed_power = self._measure_cycle_power(values, period)

        null_powers = []
        fft_vals = np.fft.rfft(values)
        magnitudes = np.abs(fft_vals)

        for _ in range(min(self.n_bootstrap, 500)):
            # Phase randomization: preserve magnitude spectrum, randomize phases
            random_phases = np.exp(1j * np.random.uniform(0, 2 * np.pi, len(fft_vals)))
            # Ensure conjugate symmetry for real output
            random_phases[0] = 1.0
            if len(fft_vals) % 2 == 0:
                random_phases[-1] = 1.0

            null_fft = magnitudes * random_phases
            null_series = np.fft.irfft(null_fft, n=len(values))
            null_power = self._measure_cycle_power(null_series, period)
            null_powers.append(null_power)

        if not null_powers:
            return 0.5

        percentile = float(np.mean(np.array(null_powers) < observed_power))
        return percentile

    # ── Composite Stability Score ─────────────────────────────────────────────

    def _compute_stability_score(
        self,
        wf_detection_rate: float,
        wf_period_cv: float,
        oos_ratio: float,
        bootstrap_pct: float,
    ) -> float:
        """
        Composite stability score 0–1:
        - High detection rate → more stable
        - Low period CV → more stable
        - OOS ratio near 1 → more stable
        - High bootstrap percentile → more significant
        """
        # Detection rate score (0–1)
        det_score = float(np.clip(wf_detection_rate, 0, 1))

        # Period consistency score
        cv_score = float(np.clip(1.0 - wf_period_cv * 2, 0, 1))

        # OOS persistence score (1.0 is ideal; penalize > 1 (spurious) and < 0.5 (weak OOS))
        oos_score = float(np.clip(1.0 - abs(oos_ratio - 0.8) / 0.8, 0, 1))

        # Significance score
        sig_score = float(np.clip((bootstrap_pct - 0.8) / 0.2, 0, 1))

        composite = (
            0.35 * det_score
            + 0.20 * cv_score
            + 0.25 * oos_score
            + 0.20 * sig_score
        )
        return float(np.clip(composite, 0, 1))

    # ── Regime Stability ──────────────────────────────────────────────────────

    def _regime_stability_analysis(self, values: np.ndarray) -> Dict[str, float]:
        """Assess whether the overall series shows structural stability."""
        n = len(values)
        metrics = {}

        # Hurst exponent (overall)
        try:
            from app.ml.cycle_detection.engine import CycleDetectionEngine
            h = CycleDetectionEngine()._hurst_exponent(values)
            metrics["hurst"] = round(h, 4)
        except Exception:
            metrics["hurst"] = 0.5

        # ADF test for stationarity
        try:
            from statsmodels.tsa.stattools import adfuller
            adf_result = adfuller(values, maxlag=20, autolag="AIC")
            metrics["adf_pvalue"] = round(float(adf_result[1]), 6)
            metrics["is_stationary_adf"] = bool(adf_result[1] < 0.05)
        except Exception:
            metrics["adf_pvalue"] = 1.0
            metrics["is_stationary_adf"] = False

        # KPSS test
        try:
            from statsmodels.tsa.stattools import kpss
            kpss_result = kpss(values, regression="c", nlags="auto")
            metrics["kpss_pvalue"] = round(float(kpss_result[1]), 6)
            metrics["is_stationary_kpss"] = bool(kpss_result[1] > 0.05)
        except Exception:
            metrics["kpss_pvalue"] = 0.0
            metrics["is_stationary_kpss"] = False

        # Variance ratio test (Chow-Denning)
        q1 = int(n * 0.25)
        q2 = int(n * 0.75)
        if q1 > 0 and q2 < n:
            var1 = np.var(values[:q1])
            var2 = np.var(values[q1:q2])
            var3 = np.var(values[q2:])
            metrics["variance_ratio_1_2"] = round(float(var1 / (var2 + 1e-10)), 4)
            metrics["variance_ratio_2_3"] = round(float(var2 / (var3 + 1e-10)), 4)
            # Close to 1.0 = stable variance
            vr_stability = 1.0 - abs(1.0 - metrics["variance_ratio_1_2"]) * 0.5
            metrics["variance_stability"] = round(float(np.clip(vr_stability, 0, 1)), 4)

        return metrics
