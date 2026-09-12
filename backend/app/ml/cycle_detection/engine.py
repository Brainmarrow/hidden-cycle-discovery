"""
MODULE 2: CYCLE DETECTION ENGINE
==================================
Implements multiple spectral/periodicity analysis methods:
- FFT (Fast Fourier Transform)
- Lomb-Scargle (handles irregular sampling)
- Continuous Wavelet Transform
- Autocorrelation Function
- Power Spectral Density (Welch)
- Hilbert Transform (instantaneous phase/amplitude)
- Hurst Exponent (long-memory / fractal dimension)
- EMD (Empirical Mode Decomposition) - bonus

All methods return a unified CycleCandidate list, ranked by strength.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict
from enum import Enum

import numpy as np
import pandas as pd
from scipy import signal, stats
from scipy.signal import hilbert, find_peaks
from scipy.fft import rfft, rfftfreq

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CycleCandidate:
    """A single detected cycle / periodicity."""
    method: str
    period_bars: float          # Period in bars (e.g., 20 bars)
    period_calendar: float      # Period in calendar days
    frequency: float            # 1 / period_bars
    amplitude: float
    power: float                # Normalized spectral power 0–1
    phase: float                # Phase offset in radians
    strength: float             # Composite strength score 0–1
    confidence: float           # Statistical confidence 0–1

    # Spectral data (for visualization)
    all_frequencies: Optional[np.ndarray] = field(default=None, repr=False)
    all_powers: Optional[np.ndarray] = field(default=None, repr=False)

    # Turning point projection
    next_turning_point_bars: Optional[int] = None
    turning_point_type: Optional[str] = None  # "peak" | "trough"

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "period_bars": round(self.period_bars, 2),
            "period_calendar": round(self.period_calendar, 2),
            "frequency": round(self.frequency, 6),
            "amplitude": round(self.amplitude, 6),
            "power": round(self.power, 4),
            "phase": round(self.phase, 4),
            "strength": round(self.strength, 4),
            "confidence": round(self.confidence, 4),
            "next_turning_point_bars": self.next_turning_point_bars,
            "turning_point_type": self.turning_point_type,
        }


@dataclass
class CycleDetectionResult:
    """Aggregated results from all cycle detection methods."""
    candidates: List[CycleCandidate]
    dominant: List[CycleCandidate]      # Top N by strength
    consensus: List[CycleCandidate]     # Found by multiple methods
    method_results: Dict[str, List[CycleCandidate]] = field(default_factory=dict)
    hurst_exponent: Optional[float] = None
    n_bars_analyzed: int = 0
    bars_per_day: float = 1.0

    def to_dict(self) -> dict:
        return {
            "dominant_cycles": [c.to_dict() for c in self.dominant],
            "consensus_cycles": [c.to_dict() for c in self.consensus],
            "all_candidates": [c.to_dict() for c in self.candidates],
            "hurst_exponent": self.hurst_exponent,
            "n_bars_analyzed": self.n_bars_analyzed,
            "bars_per_day": self.bars_per_day,
            "method_results": {
                m: [c.to_dict() for c in cycles]
                for m, cycles in self.method_results.items()
            },
        }


# ─────────────────────────────────────────────────────────────────────────────
# CYCLE DETECTION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class CycleDetectionEngine:
    """
    Multi-method cycle detection engine.

    Methods:
        fft              - Fast Fourier Transform
        lomb_scargle     - For irregular time series
        wavelet          - Continuous Wavelet Transform (Morlet)
        autocorrelation  - ACF-based period finding
        spectral_density - Welch's method PSD
        hilbert          - Instantaneous frequency via Hilbert transform
        hurst            - Hurst exponent (fractal scaling)
        emd              - Empirical Mode Decomposition
    """

    def __init__(
        self,
        min_period_bars: int = 3,
        max_period_bars: Optional[int] = None,
        top_n_cycles: int = 20,
        min_power_threshold: float = 0.01,
        bars_per_day: float = 1.0,    # 1 for daily, 390 for 1-min equity, etc.
        methods: Optional[List[str]] = None,
    ):
        self.min_period = min_period_bars
        self.max_period = max_period_bars
        self.top_n = top_n_cycles
        self.min_power = min_power_threshold
        self.bars_per_day = bars_per_day
        self.methods = methods or ["fft", "lomb_scargle", "wavelet", "autocorrelation",
                                   "spectral_density", "hilbert", "hurst"]

    # ── Main Entry Point ────────────────────────────────────────────────────

    def detect(self, series: pd.Series) -> CycleDetectionResult:
        """
        Run all configured detection methods on the input series.

        Args:
            series: Preprocessed (detrended, normalized) price/return series.

        Returns:
            CycleDetectionResult with all candidates ranked by strength.
        """
        if len(series) < 32:
            raise ValueError("Series too short for cycle detection (minimum 32 bars)")

        values = series.dropna().values.astype(np.float64)
        if self.max_period is None:
            self.max_period = len(values) // 2

        all_candidates: List[CycleCandidate] = []
        method_results: Dict[str, List[CycleCandidate]] = {}
        hurst = None

        # ── Run each method ────────────────────────────────────────
        for method in self.methods:
            try:
                if method == "fft":
                    candidates = self._fft(values)
                elif method == "lomb_scargle":
                    t = np.arange(len(values), dtype=np.float64)
                    candidates = self._lomb_scargle(t, values)
                elif method == "wavelet":
                    candidates = self._wavelet_cwt(values)
                elif method == "autocorrelation":
                    candidates = self._autocorrelation(values)
                elif method == "spectral_density":
                    candidates = self._welch_psd(values)
                elif method == "hilbert":
                    candidates = self._hilbert_analysis(values)
                elif method == "hurst":
                    hurst = self._hurst_exponent(values)
                    candidates = []
                elif method == "emd":
                    candidates = self._emd_analysis(values)
                else:
                    logger.warning(f"Unknown method: {method}")
                    continue

                method_results[method] = candidates
                all_candidates.extend(candidates)
                logger.debug(f"{method}: found {len(candidates)} candidates")

            except Exception as e:
                logger.error(f"Cycle detection method {method} failed: {e}", exc_info=True)
                method_results[method] = []

        # ── Score & rank ───────────────────────────────────────────
        all_candidates = self._score_candidates(all_candidates, len(values))
        all_candidates.sort(key=lambda c: c.strength, reverse=True)

        # ── Dominant (top N) ───────────────────────────────────────
        dominant = all_candidates[: self.top_n]

        # ── Consensus (found by ≥2 methods within ±10% period) ────
        consensus = self._find_consensus_cycles(method_results)

        # ── Project turning points ─────────────────────────────────
        for candidate in dominant[:10]:
            self._project_turning_point(candidate, values)

        return CycleDetectionResult(
            candidates=all_candidates,
            dominant=dominant,
            consensus=consensus,
            method_results=method_results,
            hurst_exponent=hurst,
            n_bars_analyzed=len(values),
            bars_per_day=self.bars_per_day,
        )

    # ── FFT ─────────────────────────────────────────────────────────────────

    def _fft(self, values: np.ndarray) -> List[CycleCandidate]:
        """Fast Fourier Transform — best for stationary, evenly-sampled series."""
        n = len(values)
        # Window to reduce spectral leakage
        window = np.hanning(n)
        windowed = values * window

        fft_vals = rfft(windowed)
        freqs = rfftfreq(n)  # Cycles per bar

        powers = np.abs(fft_vals) ** 2
        powers = powers / powers.max()  # Normalize

        candidates = []
        # Find peaks in power spectrum
        min_freq = 1.0 / self.max_period if self.max_period else 0
        max_freq = 1.0 / self.min_period
        freq_mask = (freqs > min_freq) & (freqs < max_freq) & (freqs > 0)

        peak_indices, peak_props = find_peaks(
            powers[freq_mask],
            height=self.min_power,
            distance=2,
            prominence=0.005,
        )

        freq_masked = freqs[freq_mask]
        powers_masked = powers[freq_mask]

        # Store full spectrum on first candidate for visualization
        full_freqs = freqs[freq_mask]
        full_powers = powers_masked

        for i, idx in enumerate(peak_indices):
            freq = freq_masked[idx]
            period = 1.0 / freq
            if period < self.min_period or period > self.max_period:
                continue

            phase = np.angle(fft_vals[np.argmin(np.abs(freqs - freq))])
            amplitude = 2.0 * np.sqrt(powers_masked[idx]) / n

            c = CycleCandidate(
                method="fft",
                period_bars=period,
                period_calendar=period / self.bars_per_day,
                frequency=freq,
                amplitude=float(amplitude),
                power=float(powers_masked[idx]),
                phase=float(phase),
                strength=0.0,  # Computed later
                confidence=0.0,
            )
            if i == 0:
                c.all_frequencies = full_freqs
                c.all_powers = full_powers

            candidates.append(c)

        return sorted(candidates, key=lambda c: c.power, reverse=True)[: self.top_n]

    # ── Lomb-Scargle ────────────────────────────────────────────────────────

    def _lomb_scargle(self, t: np.ndarray, values: np.ndarray) -> List[CycleCandidate]:
        """Lomb-Scargle periodogram — handles gaps and irregular sampling."""
        from astropy.timeseries import LombScargle

        # Normalize
        y = (values - values.mean()) / (values.std() + 1e-10)

        min_freq = 1.0 / self.max_period
        max_freq = 1.0 / self.min_period
        n_freqs = min(2000, len(values) * 10)

        frequency = np.linspace(min_freq, max_freq, n_freqs)
        ls = LombScargle(t, y, normalization="standard")
        power = ls.power(frequency)

        # False alarm probability
        fap_levels = ls.false_alarm_level([0.1, 0.05, 0.01])

        peaks, props = find_peaks(power, height=fap_levels[1], distance=3, prominence=0.02)

        candidates = []
        for i, idx in enumerate(peaks):
            freq = frequency[idx]
            period = 1.0 / freq
            if period < self.min_period or period > self.max_period:
                continue

            fap = ls.false_alarm_probability(power[idx])
            confidence = max(0.0, min(1.0, 1.0 - fap))

            c = CycleCandidate(
                method="lomb_scargle",
                period_bars=float(period),
                period_calendar=float(period / self.bars_per_day),
                frequency=float(freq),
                amplitude=float(np.sqrt(power[idx])),
                power=float(power[idx] / power.max()),
                phase=0.0,
                strength=0.0,
                confidence=confidence,
            )
            if i == 0:
                c.all_frequencies = frequency
                c.all_powers = power / power.max()

            candidates.append(c)

        return sorted(candidates, key=lambda c: c.power, reverse=True)[: self.top_n]

    # ── Continuous Wavelet Transform ─────────────────────────────────────────

    def _wavelet_cwt(self, values: np.ndarray) -> List[CycleCandidate]:
        """CWT with Morlet wavelet — detects time-varying cycles."""
        import pywt

        # Scales corresponding to periods min_period..max_period
        scales = np.arange(self.min_period, min(self.max_period, len(values) // 2))
        if len(scales) == 0:
            return []

        coeffs, freqs = pywt.cwt(values, scales, "morl")
        power = np.abs(coeffs) ** 2

        # Time-averaged power per scale
        avg_power = power.mean(axis=1)
        avg_power_norm = avg_power / avg_power.max()

        peaks, _ = find_peaks(avg_power_norm, height=self.min_power, distance=2, prominence=0.01)

        candidates = []
        for idx in peaks:
            scale = scales[idx]
            freq = freqs[idx]
            period = 1.0 / freq if freq > 0 else scale

            candidates.append(CycleCandidate(
                method="wavelet",
                period_bars=float(period),
                period_calendar=float(period / self.bars_per_day),
                frequency=float(freq),
                amplitude=float(np.sqrt(avg_power[idx])),
                power=float(avg_power_norm[idx]),
                phase=float(np.angle(coeffs[idx]).mean()),
                strength=0.0,
                confidence=0.0,
            ))

        return sorted(candidates, key=lambda c: c.power, reverse=True)[: self.top_n]

    # ── Autocorrelation ──────────────────────────────────────────────────────

    def _autocorrelation(self, values: np.ndarray) -> List[CycleCandidate]:
        """ACF-based cycle detection — finds lag of highest autocorrelation."""
        n = len(values)
        max_lag = min(self.max_period, n // 2)

        # Full autocorrelation
        acf_vals = np.correlate(values - values.mean(), values - values.mean(), mode="full")
        acf_vals = acf_vals[n - 1:]
        acf_vals = acf_vals / acf_vals[0]  # Normalize

        # 95% confidence bounds
        conf = 1.96 / np.sqrt(n)

        lag_range = acf_vals[self.min_period: max_lag]
        peaks, props = find_peaks(
            lag_range,
            height=conf * 1.5,
            distance=self.min_period // 2,
            prominence=0.05,
        )

        candidates = []
        for idx in peaks:
            lag = idx + self.min_period
            power = float(lag_range[idx])
            confidence = min(1.0, power / conf)

            candidates.append(CycleCandidate(
                method="autocorrelation",
                period_bars=float(lag),
                period_calendar=float(lag / self.bars_per_day),
                frequency=1.0 / lag,
                amplitude=float(power),
                power=float(np.clip(power, 0, 1)),
                phase=0.0,
                strength=0.0,
                confidence=confidence,
                all_frequencies=np.arange(self.min_period, max_lag) / max_lag,
                all_powers=lag_range,
            ))

        return sorted(candidates, key=lambda c: c.power, reverse=True)[: self.top_n]

    # ── Welch PSD ────────────────────────────────────────────────────────────

    def _welch_psd(self, values: np.ndarray) -> List[CycleCandidate]:
        """Welch's method — smoothed PSD, reduces noise vs raw FFT."""
        nperseg = min(256, len(values) // 2)
        freqs, psd = signal.welch(values, nperseg=nperseg, window="hann", scaling="density")

        # Convert to period space
        freq_mask = (freqs > 0) & (freqs >= 1.0 / self.max_period) & (freqs <= 1.0 / self.min_period)
        f = freqs[freq_mask]
        p = psd[freq_mask]
        p_norm = p / p.max()

        peaks, _ = find_peaks(p_norm, height=self.min_power, distance=2, prominence=0.01)

        candidates = []
        for idx in peaks:
            freq = f[idx]
            period = 1.0 / freq
            candidates.append(CycleCandidate(
                method="spectral_density",
                period_bars=float(period),
                period_calendar=float(period / self.bars_per_day),
                frequency=float(freq),
                amplitude=float(np.sqrt(p[idx])),
                power=float(p_norm[idx]),
                phase=0.0,
                strength=0.0,
                confidence=0.0,
                all_frequencies=f,
                all_powers=p_norm,
            ))

        return sorted(candidates, key=lambda c: c.power, reverse=True)[: self.top_n]

    # ── Hilbert Transform ────────────────────────────────────────────────────

    def _hilbert_analysis(self, values: np.ndarray) -> List[CycleCandidate]:
        """Hilbert transform — extracts instantaneous amplitude, phase, frequency."""
        analytic = hilbert(values)
        amplitude_env = np.abs(analytic)
        instantaneous_phase = np.unwrap(np.angle(analytic))
        instantaneous_freq = np.diff(instantaneous_phase) / (2.0 * np.pi)

        # Filter valid instantaneous frequencies
        valid_mask = (instantaneous_freq > 1.0 / self.max_period) & \
                     (instantaneous_freq < 1.0 / self.min_period)
        valid_freqs = instantaneous_freq[valid_mask]

        if len(valid_freqs) == 0:
            return []

        # Histogram of instantaneous frequencies → peaks = dominant cycles
        hist, bin_edges = np.histogram(valid_freqs, bins=200)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
        hist_norm = hist / hist.max()

        peaks, _ = find_peaks(hist_norm, height=0.1, prominence=0.05, distance=2)

        candidates = []
        for idx in peaks:
            freq = bin_centers[idx]
            period = 1.0 / freq if freq > 0 else 0
            if period < self.min_period or period > self.max_period:
                continue

            candidates.append(CycleCandidate(
                method="hilbert",
                period_bars=float(period),
                period_calendar=float(period / self.bars_per_day),
                frequency=float(freq),
                amplitude=float(amplitude_env.mean()),
                power=float(hist_norm[idx]),
                phase=float(instantaneous_phase[-1] % (2 * np.pi)),
                strength=0.0,
                confidence=0.0,
            ))

        return sorted(candidates, key=lambda c: c.power, reverse=True)[: self.top_n]

    # ── Hurst Exponent ───────────────────────────────────────────────────────

    def _hurst_exponent(self, values: np.ndarray) -> float:
        """
        Hurst exponent via rescaled range (R/S) analysis.
        H > 0.5 → trending (persistent)
        H = 0.5 → random walk
        H < 0.5 → mean-reverting
        """
        n = len(values)
        if n < 20:
            return 0.5

        lags = range(10, min(n // 4, 200))
        rs_vals = []

        for lag in lags:
            sub_series = [values[i:i + lag] for i in range(0, n - lag, lag)]
            rs_sub = []
            for sub in sub_series:
                mean = np.mean(sub)
                deviation = np.cumsum(sub - mean)
                r = np.max(deviation) - np.min(deviation)
                s = np.std(sub, ddof=1)
                if s > 0:
                    rs_sub.append(r / s)
            if rs_sub:
                rs_vals.append(np.mean(rs_sub))

        if len(rs_vals) < 5:
            return 0.5

        log_lags = np.log(list(lags)[:len(rs_vals)])
        log_rs = np.log(rs_vals)

        try:
            slope, _, _, _, _ = stats.linregress(log_lags, log_rs)
            return float(np.clip(slope, 0.0, 1.0))
        except Exception:
            return 0.5

    # ── EMD ─────────────────────────────────────────────────────────────────

    def _emd_analysis(self, values: np.ndarray) -> List[CycleCandidate]:
        """
        Empirical Mode Decomposition — extracts IMFs (Intrinsic Mode Functions).
        Each IMF represents a natural oscillation mode.
        """
        try:
            from PyEMD import EMD
            emd = EMD()
            imfs = emd(values, max_imf=10)
        except ImportError:
            logger.warning("PyEMD not installed, skipping EMD analysis")
            return []
        except Exception as e:
            logger.warning(f"EMD failed: {e}")
            return []

        candidates = []
        for i, imf in enumerate(imfs):
            # Compute dominant frequency of each IMF via zero crossings
            zero_crossings = np.where(np.diff(np.sign(imf)))[0]
            if len(zero_crossings) < 2:
                continue

            avg_half_period = np.mean(np.diff(zero_crossings))
            period = avg_half_period * 2.0

            if period < self.min_period or period > self.max_period:
                continue

            power = float(np.var(imf) / (np.var(values) + 1e-10))

            candidates.append(CycleCandidate(
                method="emd",
                period_bars=float(period),
                period_calendar=float(period / self.bars_per_day),
                frequency=1.0 / period,
                amplitude=float(np.max(np.abs(imf))),
                power=float(np.clip(power, 0, 1)),
                phase=0.0,
                strength=0.0,
                confidence=float(min(1.0, power * 5)),
            ))

        return sorted(candidates, key=lambda c: c.power, reverse=True)

    # ── Scoring ──────────────────────────────────────────────────────────────

    def _score_candidates(self, candidates: List[CycleCandidate], n: int) -> List[CycleCandidate]:
        """
        Compute composite strength score for each candidate.
        Score = weighted combination of power, confidence, and period validity.
        """
        if not candidates:
            return candidates

        max_power = max(c.power for c in candidates) or 1.0

        for c in candidates:
            # Period penalty: prefer periods not near the data length boundary
            boundary_factor = 1.0 - abs(c.period_bars - n / 4) / (n / 4 + 1e-10)
            boundary_factor = max(0.1, min(1.0, boundary_factor))

            # Confidence weight
            conf_w = 0.3 if c.confidence == 0 else c.confidence

            # Power weight
            power_w = c.power / max_power

            # Composite
            c.strength = float(0.6 * power_w + 0.3 * conf_w + 0.1 * boundary_factor)
            c.strength = round(min(1.0, c.strength), 4)

        return candidates

    def _find_consensus_cycles(
        self, method_results: Dict[str, List[CycleCandidate]]
    ) -> List[CycleCandidate]:
        """
        Find cycles confirmed by ≥2 methods within ±15% period tolerance.
        Returns merged consensus candidates.
        """
        all_periods: Dict[float, List[CycleCandidate]] = {}

        for method, candidates in method_results.items():
            for c in candidates[:5]:  # Top 5 per method
                matched = False
                for ref_period in list(all_periods.keys()):
                    ratio = c.period_bars / ref_period
                    if 0.85 <= ratio <= 1.15:
                        all_periods[ref_period].append(c)
                        matched = True
                        break
                if not matched:
                    all_periods[c.period_bars] = [c]

        consensus = []
        for period, group in all_periods.items():
            if len(group) >= 2:
                # Merge: average stats, take max strength
                avg_period = np.mean([c.period_bars for c in group])
                merged = CycleCandidate(
                    method="consensus[" + ",".join(sorted({c.method for c in group})) + "]",
                    period_bars=float(avg_period),
                    period_calendar=float(avg_period / self.bars_per_day),
                    frequency=1.0 / avg_period,
                    amplitude=float(np.mean([c.amplitude for c in group])),
                    power=float(np.mean([c.power for c in group])),
                    phase=float(np.mean([c.phase for c in group])),
                    strength=float(max(c.strength for c in group) * (1.0 + 0.1 * (len(group) - 1))),
                    confidence=float(np.mean([c.confidence for c in group])),
                )
                merged.strength = min(1.0, merged.strength)
                consensus.append(merged)

        return sorted(consensus, key=lambda c: c.strength, reverse=True)

    def _project_turning_point(self, candidate: CycleCandidate, values: np.ndarray) -> None:
        """Estimate bars until next peak or trough based on phase."""
        period = candidate.period_bars
        phase = candidate.phase  # Current phase in radians
        # Distance to next peak (phase = 0) and trough (phase = π)
        bars_to_peak = int(((0 - phase) % (2 * np.pi)) / (2 * np.pi) * period)
        bars_to_trough = int(((np.pi - phase) % (2 * np.pi)) / (2 * np.pi) * period)

        if bars_to_peak <= bars_to_trough:
            candidate.next_turning_point_bars = bars_to_peak
            candidate.turning_point_type = "peak"
        else:
            candidate.next_turning_point_bars = bars_to_trough
            candidate.turning_point_type = "trough"
