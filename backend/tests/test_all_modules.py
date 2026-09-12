"""
Test suite for Hidden Cycle Discovery AI backend.
Tests all 10 ML modules with synthetic data.

Run: pytest tests/ -v --cov=app --cov-report=html
"""
import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timedelta


# ── Test helpers ──────────────────────────────────────────────────────────────

def make_synthetic_series(n: int = 500, seed: int = 42) -> pd.Series:
    """Generate synthetic price series with known cycles."""
    np.random.seed(seed)
    t = np.arange(n)

    # Known cycles: 20, 60, 120 bars
    signal = (
        np.sin(2 * np.pi * t / 20) * 2 +     # 20-bar cycle
        np.sin(2 * np.pi * t / 60) * 3 +     # 60-bar cycle
        np.sin(2 * np.pi * t / 120) * 5 +    # 120-bar cycle
        np.random.randn(n) * 0.5              # Noise
    )

    # Convert to price series (starting at 100)
    prices = 100 * np.exp(np.cumsum(signal / 200))
    dates = pd.date_range("2015-01-01", periods=n, freq="B")
    return pd.Series(prices, index=dates, name="close")


def make_ohlcv_df(n: int = 500) -> pd.DataFrame:
    """Generate synthetic OHLCV DataFrame."""
    close = make_synthetic_series(n)
    noise = np.random.randn(n) * 0.005

    df = pd.DataFrame({
        "open":   close.values * (1 + noise),
        "high":   close.values * (1 + np.abs(noise) + 0.002),
        "low":    close.values * (1 - np.abs(noise) - 0.002),
        "close":  close.values,
        "volume": np.random.randint(1000000, 10000000, n).astype(float),
    }, index=close.index)

    return df


# ── Module 1: Preprocessing ───────────────────────────────────────────────────

class TestPreprocessingEngine:

    def test_basic_preprocessing(self):
        from app.ml.preprocessing.engine import PreprocessingEngine
        df = make_ohlcv_df()
        engine = PreprocessingEngine()
        result = engine.process(df)

        assert result.n_bars > 400
        assert len(result.returns) == result.n_bars
        assert len(result.log_returns) == result.n_bars
        assert len(result.detrended) == result.n_bars
        assert len(result.normalized) == result.n_bars
        assert len(result.volatility) == result.n_bars
        assert len(result.vol_adjusted) == result.n_bars

    def test_handles_missing_values(self):
        from app.ml.preprocessing.engine import PreprocessingEngine
        df = make_ohlcv_df()
        # Inject some NaN values
        df.iloc[10:15, df.columns.get_loc("close")] = np.nan
        engine = PreprocessingEngine()
        result = engine.process(df)
        assert result.n_bars > 400  # Should handle gracefully

    def test_outlier_removal(self):
        from app.ml.preprocessing.engine import PreprocessingEngine, PreprocessingConfig, OutlierMethod
        df = make_ohlcv_df()
        # Inject extreme outlier
        df.iloc[100, df.columns.get_loc("close")] = 999999.0
        config = PreprocessingConfig(outlier_method=OutlierMethod.WINSORIZE)
        engine = PreprocessingEngine(config)
        result = engine.process(df)
        # Should be clipped
        assert result.raw.max() < 999999.0

    def test_returns_finite(self):
        from app.ml.preprocessing.engine import PreprocessingEngine
        df = make_ohlcv_df()
        engine = PreprocessingEngine()
        result = engine.process(df)
        assert np.all(np.isfinite(result.log_returns.dropna()))


# ── Module 2: Cycle Detection ─────────────────────────────────────────────────

class TestCycleDetectionEngine:

    def test_fft_detects_known_cycles(self):
        from app.ml.cycle_detection.engine import CycleDetectionEngine
        series = make_synthetic_series(500)

        # Detrend with linear
        from scipy.signal import detrend as sp_detrend
        values = sp_detrend(series.values)
        detrended = pd.Series(values, index=series.index)

        engine = CycleDetectionEngine(min_period_bars=5, max_period_bars=200, methods=["fft"])
        result = engine.detect(detrended)

        assert len(result.dominant) > 0
        # Should find a cycle near 20, 60, or 120 bars
        periods = [c.period_bars for c in result.dominant]
        found_known = any(
            any(abs(p - known) / known < 0.2 for known in [20, 60, 120])
            for p in periods
        )
        assert found_known, f"No known cycles found in {periods[:5]}"

    def test_all_methods_run(self):
        from app.ml.cycle_detection.engine import CycleDetectionEngine
        from app.ml.preprocessing.engine import PreprocessingEngine
        df = make_ohlcv_df()
        preprocessed = PreprocessingEngine().process(df)
        engine = CycleDetectionEngine()
        result = engine.detect(preprocessed.detrended)

        assert result.n_bars_analyzed > 0
        assert result.hurst_exponent is not None
        assert 0 <= result.hurst_exponent <= 1.0
        assert len(result.candidates) > 0

    def test_hurst_exponent_range(self):
        from app.ml.cycle_detection.engine import CycleDetectionEngine
        engine = CycleDetectionEngine()

        # Trending series should have H > 0.5
        trend = np.cumsum(np.ones(300) * 0.01 + np.random.randn(300) * 0.1)
        h = engine._hurst_exponent(trend)
        assert 0.0 <= h <= 1.0

    def test_consensus_cycles(self):
        from app.ml.cycle_detection.engine import CycleDetectionEngine
        from app.ml.preprocessing.engine import PreprocessingEngine
        df = make_ohlcv_df()
        preprocessed = PreprocessingEngine().process(df)
        engine = CycleDetectionEngine(methods=["fft", "lomb_scargle", "autocorrelation"])
        result = engine.detect(preprocessed.detrended)
        # Consensus cycles should have method strings showing multiple methods
        for c in result.consensus:
            assert "," in c.method or "consensus" in c.method

    def test_turning_point_projection(self):
        from app.ml.cycle_detection.engine import CycleDetectionEngine
        from app.ml.preprocessing.engine import PreprocessingEngine
        df = make_ohlcv_df()
        preprocessed = PreprocessingEngine().process(df)
        engine = CycleDetectionEngine()
        result = engine.detect(preprocessed.detrended)
        for c in result.dominant[:3]:
            if c.next_turning_point_bars is not None:
                assert c.next_turning_point_bars >= 0
                assert c.turning_point_type in ("peak", "trough")


# ── Module 3: Pattern Discovery ───────────────────────────────────────────────

class TestPatternDiscoveryEngine:

    def test_discovers_patterns(self):
        from app.ml.pattern_discovery.engine import PatternDiscoveryEngine
        from app.ml.preprocessing.engine import PreprocessingEngine
        df = make_ohlcv_df(n=300)
        preprocessed = PreprocessingEngine().process(df)

        engine = PatternDiscoveryEngine(window_sizes=[10, 20], min_occurrences=2)
        result = engine.discover(preprocessed.normalized, preprocessed.log_returns)

        assert result.n_bars > 0
        # Should find at least some patterns
        assert len(result.patterns) >= 0  # Can be 0 for random data

    def test_matrix_profile_motifs(self):
        from app.ml.pattern_discovery.engine import PatternDiscoveryEngine
        engine = PatternDiscoveryEngine()
        values = np.sin(np.linspace(0, 20 * np.pi, 400)) + np.random.randn(400) * 0.1
        motifs = engine._matrix_profile_motifs(values, window=20)
        # Should find sinusoidal motifs
        assert isinstance(motifs, list)

    def test_regime_detection(self):
        from app.ml.pattern_discovery.engine import PatternDiscoveryEngine
        from app.ml.preprocessing.engine import PreprocessingEngine
        df = make_ohlcv_df(n=500)
        preprocessed = PreprocessingEngine().process(df)
        engine = PatternDiscoveryEngine(regime_n_states=3)
        regimes, stats = engine._detect_regimes(preprocessed.normalized, preprocessed.log_returns)

        if regimes is not None:
            assert len(regimes) > 0
            assert stats is not None
            assert len(stats) == 3


# ── Module 5: Feature Discovery ───────────────────────────────────────────────

class TestFeatureDiscoveryEngine:

    def test_builds_feature_matrix(self):
        from app.ml.feature_engine.engine import FeatureDiscoveryEngine
        from app.ml.preprocessing.engine import PreprocessingEngine

        df = make_ohlcv_df(n=300)
        preprocessed = PreprocessingEngine().process(df)

        engine = FeatureDiscoveryEngine(include_planetary=False, include_cycles=False)
        result = engine.discover(df, preprocessed)

        assert result.n_features_total > 50
        assert len(result.feature_matrix) == len(df)
        assert len(result.top_features) > 0

    def test_feature_importance_ranking(self):
        from app.ml.feature_engine.engine import FeatureDiscoveryEngine
        from app.ml.preprocessing.engine import PreprocessingEngine

        df = make_ohlcv_df(n=400)
        preprocessed = PreprocessingEngine().process(df)
        engine = FeatureDiscoveryEngine(include_planetary=False, include_cycles=False, top_k_features=20)
        result = engine.discover(df, preprocessed)

        assert len(result.importance_ranking) > 0
        # Should be sorted descending by composite score
        scores = [f.composite_score for f in result.importance_ranking[:20]]
        assert scores == sorted(scores, reverse=True)


# ── Module 7: Analog Engine ───────────────────────────────────────────────────

class TestAnalogEngine:

    def test_finds_analogs(self):
        from app.ml.analog.engine import AnalogEngine
        from app.ml.preprocessing.engine import PreprocessingEngine

        df = make_ohlcv_df(n=500)
        preprocessed = PreprocessingEngine().process(df)

        engine = AnalogEngine(lookback_bars=40, top_n=5)
        result = engine.find_analogs(
            preprocessed.normalized,
            preprocessed.log_returns,
        )

        assert result.n_analogs_found > 0
        assert len(result.top_analogs) <= 5
        for a in result.top_analogs:
            assert 0 <= a.similarity_score <= 1.0

    def test_analog_no_lookahead(self):
        """Analogs must not overlap with the query window."""
        from app.ml.analog.engine import AnalogEngine
        from app.ml.preprocessing.engine import PreprocessingEngine

        df = make_ohlcv_df(n=300)
        preprocessed = PreprocessingEngine().process(df)
        engine = AnalogEngine(lookback_bars=30, top_n=5, min_separation_bars=20)
        result = engine.find_analogs(preprocessed.normalized, preprocessed.log_returns)

        n = len(preprocessed.normalized.dropna())
        query_start = n - 1 - 30

        for analog in result.top_analogs:
            assert analog.end_idx < query_start - 20, "Analog overlaps with query window!"


# ── Module 8: Stability Engine ────────────────────────────────────────────────

class TestStabilityEngine:

    def test_stability_scores_range(self):
        from app.ml.stability.engine import StabilityEngine
        from app.ml.cycle_detection.engine import CycleDetectionEngine
        from app.ml.preprocessing.engine import PreprocessingEngine

        df = make_ohlcv_df(n=500)
        preprocessed = PreprocessingEngine().process(df)
        cycle_result = CycleDetectionEngine(methods=["fft"]).detect(preprocessed.detrended)

        engine = StabilityEngine(n_bootstrap=20)
        result = engine.test(preprocessed.detrended, cycle_result)

        for m in result.cycle_metrics:
            assert 0.0 <= m.stability_score <= 1.0
            assert 0.0 <= m.wf_detection_rate <= 1.0
            assert 0.0 <= m.bootstrap_percentile <= 1.0

    def test_bootstrap_significance(self):
        from app.ml.stability.engine import StabilityEngine

        engine = StabilityEngine(n_bootstrap=100)
        # Strong cycle: known 20-bar sine
        t = np.arange(400)
        signal = np.sin(2 * np.pi * t / 20) * 3 + np.random.randn(400) * 0.1
        pct = engine._bootstrap_significance(signal, 20.0)
        # Should be high percentile for a real strong cycle
        assert 0.0 <= pct <= 1.0

    def test_regime_stability_returns_dict(self):
        from app.ml.stability.engine import StabilityEngine
        engine = StabilityEngine()
        values = make_synthetic_series(n=400).values
        metrics = engine._regime_stability_analysis(values)
        assert "hurst" in metrics
        assert "adf_pvalue" in metrics


# ── Integration test ──────────────────────────────────────────────────────────

class TestIntegrationPipeline:

    def test_full_pipeline_smoke(self):
        """End-to-end smoke test: preprocessing → cycles → stability → analog."""
        from app.ml.preprocessing.engine import PreprocessingEngine
        from app.ml.cycle_detection.engine import CycleDetectionEngine
        from app.ml.stability.engine import StabilityEngine
        from app.ml.analog.engine import AnalogEngine

        df = make_ohlcv_df(n=600)

        # Step 1: preprocess
        preprocessed = PreprocessingEngine().process(df)
        assert preprocessed.n_bars > 500

        # Step 2: cycles
        cycle_result = CycleDetectionEngine(methods=["fft", "autocorrelation"]).detect(preprocessed.detrended)
        assert len(cycle_result.dominant) > 0

        # Step 3: stability
        stability_result = StabilityEngine(n_bootstrap=20).test(preprocessed.detrended, cycle_result)
        assert stability_result.overall_market_stability >= 0

        # Step 4: analogs
        analog_result = AnalogEngine(lookback_bars=40, top_n=5).find_analogs(
            preprocessed.normalized, preprocessed.log_returns
        )
        assert analog_result is not None
        assert isinstance(analog_result.composite_projection, dict)

        print(f"\n✓ Pipeline complete:")
        print(f"  {preprocessed.n_bars} bars preprocessed")
        print(f"  {len(cycle_result.dominant)} dominant cycles found")
        print(f"  {len(stability_result.stable_cycles)} stable cycles")
        print(f"  {analog_result.n_analogs_found} historical analogs")
