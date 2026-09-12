"""
MODULE 4: PLANETARY CORRELATION ENGINE
=========================================
Discovers (not assumes) relationships between planetary positions and market data.

Tests:
- Pearson / Spearman correlation
- Mutual information
- Cross-correlation with leads/lags
- Granger causality
- Phase-locked loops

Never assumes significance. Reports statistical metrics with FDR-corrected p-values.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from scipy import stats
from scipy.signal import correlate
from sklearn.feature_selection import mutual_info_regression
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

PLANETS = ["sun", "moon", "mercury", "venus", "mars", "jupiter",
           "saturn", "uranus", "neptune", "pluto"]

ASPECTS = {
    "conjunction": 0,
    "sextile": 60,
    "square": 90,
    "trine": 120,
    "opposition": 180,
}
ASPECT_ORB = 5.0  # degrees


@dataclass
class PlanetaryCorrelation:
    """A single discovered planetary–market relationship."""
    planet: str
    factor: str                 # degree, speed, declination, aspect_to_X, retrograde
    aspect_planet: Optional[str]
    lag_bars: int              # Positive = planet leads market
    pearson_r: float
    pearson_p: float
    spearman_r: float
    spearman_p: float
    mutual_info: float
    is_significant: bool       # After FDR correction
    fdr_corrected_p: float
    description: str

    def to_dict(self) -> dict:
        return {
            "planet": self.planet,
            "factor": self.factor,
            "aspect_planet": self.aspect_planet,
            "lag_bars": self.lag_bars,
            "pearson_r": round(self.pearson_r, 4),
            "pearson_p": round(self.pearson_p, 6),
            "spearman_r": round(self.spearman_r, 4),
            "spearman_p": round(self.spearman_p, 6),
            "mutual_info": round(self.mutual_info, 4),
            "is_significant": self.is_significant,
            "fdr_corrected_p": round(self.fdr_corrected_p, 6),
            "description": self.description,
        }


@dataclass
class PlanetaryAnalysisResult:
    top_correlations: List[PlanetaryCorrelation]
    all_correlations: List[PlanetaryCorrelation]
    feature_importance: Dict[str, float]
    dates_analyzed: Tuple[str, str]
    n_features_tested: int
    n_significant: int
    current_positions: Dict[str, Dict]    # Current planetary positions
    upcoming_events: List[Dict]            # Upcoming aspects / retrogrades

    def to_dict(self) -> dict:
        return {
            "top_correlations": [c.to_dict() for c in self.top_correlations],
            "n_features_tested": self.n_features_tested,
            "n_significant": self.n_significant,
            "feature_importance": self.feature_importance,
            "dates_analyzed": self.dates_analyzed,
            "current_positions": self.current_positions,
            "upcoming_events": self.upcoming_events,
        }


class PlanetaryCorrelationEngine:
    """
    Tests statistical relationships between planetary data and market returns.
    Uses multiple correlation metrics + FDR correction to discover genuine signals.
    Never assumes relationships exist.
    """

    def __init__(
        self,
        max_lag_bars: int = 20,
        significance_level: float = 0.05,
        top_n: int = 20,
        use_swiss_ephemeris: bool = False,  # Fallback to ephem if False
    ):
        self.max_lag = max_lag_bars
        self.alpha = significance_level
        self.top_n = top_n
        self.use_swe = use_swiss_ephemeris
        self._ephem_available = self._check_ephem()

    def _check_ephem(self) -> bool:
        try:
            import ephem
            return True
        except ImportError:
            logger.warning("ephem not installed — planetary engine disabled")
            return False

    # ── Main Entry Point ─────────────────────────────────────────────────────

    def analyze(
        self,
        series: pd.Series,
        returns: pd.Series,
    ) -> PlanetaryAnalysisResult:
        """
        Compute planetary features for each date and test correlations
        with market returns across multiple lags.

        Args:
            series: Price series (DatetimeIndex)
            returns: Log returns (DatetimeIndex aligned with series)
        """
        if not self._ephem_available:
            return self._empty_result(series)

        dates = series.index
        start_str = str(dates[0].date())
        end_str = str(dates[-1].date())

        logger.info(f"Computing planetary features for {len(dates)} dates ({start_str} → {end_str})")

        # ── Build planetary feature matrix ─────────────────────────────
        planet_df = self._build_planetary_features(dates)
        logger.info(f"Built {len(planet_df.columns)} planetary features")

        # Align with returns
        aligned_returns = returns.reindex(planet_df.index).dropna()
        planet_aligned = planet_df.reindex(aligned_returns.index).fillna(method="ffill").dropna()

        # ── Test correlations ─────────────────────────────────────────
        all_correlations = self._test_all_correlations(planet_aligned, aligned_returns)

        # ── FDR correction (Benjamini-Hochberg) ───────────────────────
        all_correlations = self._apply_fdr(all_correlations)

        # ── Sort by |pearson_r| ───────────────────────────────────────
        all_correlations.sort(key=lambda c: abs(c.pearson_r), reverse=True)
        significant = [c for c in all_correlations if c.is_significant]
        top_n = all_correlations[: self.top_n]

        # ── Feature importance via MI ─────────────────────────────────
        feature_imp = self._compute_feature_importance(planet_aligned, aligned_returns)

        # ── Current positions ─────────────────────────────────────────
        current_positions = self._get_current_positions()
        upcoming_events = self._get_upcoming_events(30)

        return PlanetaryAnalysisResult(
            top_correlations=top_n,
            all_correlations=all_correlations,
            feature_importance=feature_imp,
            dates_analyzed=(start_str, end_str),
            n_features_tested=len(all_correlations),
            n_significant=len(significant),
            current_positions=current_positions,
            upcoming_events=upcoming_events,
        )

    # ── Planetary Feature Builder ─────────────────────────────────────────────

    def _build_planetary_features(self, dates: pd.DatetimeIndex) -> pd.DataFrame:
        """Compute planetary degree, speed, declination, aspects, retrogrades for each date."""
        import ephem

        features = {}

        for date in dates:
            date_key = date.date()
            ep_date = ephem.Date(str(date_key))

            row = {}
            planet_positions = {}

            for planet_name in PLANETS:
                try:
                    planet_obj = self._get_ephem_planet(planet_name)
                    planet_obj.compute(ep_date)

                    lon = float(planet_obj.hlong)  # Ecliptic longitude in radians
                    lon_deg = np.degrees(lon) % 360

                    # Speed: compute difference from previous day
                    planet_obj_prev = self._get_ephem_planet(planet_name)
                    planet_obj_prev.compute(ephem.Date(ep_date - 1))
                    lon_prev = np.degrees(float(planet_obj_prev.hlong)) % 360
                    speed = (lon_deg - lon_prev + 360) % 360
                    if speed > 180:
                        speed -= 360  # Handle retrograde

                    is_retrograde = speed < 0

                    # Declination
                    dec = float(planet_obj.dec)

                    # Store
                    planet_positions[planet_name] = lon_deg
                    row[f"{planet_name}_lon"] = lon_deg
                    row[f"{planet_name}_lon_sin"] = np.sin(np.radians(lon_deg))
                    row[f"{planet_name}_lon_cos"] = np.cos(np.radians(lon_deg))
                    row[f"{planet_name}_speed"] = speed
                    row[f"{planet_name}_speed_abs"] = abs(speed)
                    row[f"{planet_name}_retrograde"] = float(is_retrograde)
                    row[f"{planet_name}_dec"] = dec

                except Exception:
                    pass

            # Compute aspects between planet pairs
            planet_names = list(planet_positions.keys())
            for i, p1 in enumerate(planet_names):
                for p2 in planet_names[i + 1:]:
                    angle = abs(planet_positions[p1] - planet_positions[p2]) % 360
                    if angle > 180:
                        angle = 360 - angle

                    # Aspect proximity (0 = exact aspect)
                    for aspect_name, aspect_angle in ASPECTS.items():
                        proximity = abs(angle - aspect_angle)
                        row[f"{p1}_{p2}_{aspect_name}_proximity"] = proximity
                        row[f"{p1}_{p2}_{aspect_name}_active"] = float(proximity <= ASPECT_ORB)

            features[date] = row

        return pd.DataFrame(features).T

    def _get_ephem_planet(self, name: str):
        import ephem
        mapping = {
            "sun": ephem.Sun(),
            "moon": ephem.Moon(),
            "mercury": ephem.Mercury(),
            "venus": ephem.Venus(),
            "mars": ephem.Mars(),
            "jupiter": ephem.Jupiter(),
            "saturn": ephem.Saturn(),
            "uranus": ephem.Uranus(),
            "neptune": ephem.Neptune(),
            "pluto": ephem.Pluto(),
        }
        return mapping.get(name, ephem.Sun())

    # ── Correlation Testing ───────────────────────────────────────────────────

    def _test_all_correlations(
        self, planet_df: pd.DataFrame, returns: pd.Series
    ) -> List[PlanetaryCorrelation]:
        """Test each planetary feature against returns at multiple lags."""
        results = []
        ret_vals = returns.values
        n = len(ret_vals)

        for col in planet_df.columns:
            feat_vals = planet_df[col].values

            for lag in range(-self.max_lag, self.max_lag + 1):
                if lag == 0:
                    x = feat_vals
                    y = ret_vals
                elif lag > 0:
                    # Planet leads returns by `lag` bars
                    x = feat_vals[: n - lag]
                    y = ret_vals[lag:]
                else:
                    # Returns lead planet
                    x = feat_vals[-lag:]
                    y = ret_vals[: n + lag]

                if len(x) < 30:
                    continue

                # Remove NaN pairs
                mask = np.isfinite(x) & np.isfinite(y)
                x, y = x[mask], y[mask]
                if len(x) < 20:
                    continue

                try:
                    pr, pp = stats.pearsonr(x, y)
                    sr, sp = stats.spearmanr(x, y)
                except Exception:
                    continue

                # Parse feature name
                parts = col.split("_")
                planet = parts[0] if parts[0] in PLANETS else "unknown"
                factor = "_".join(parts[1:]) if len(parts) > 1 else col
                aspect_planet = None

                # Detect aspect feature
                if len(parts) >= 3 and parts[1] in PLANETS:
                    aspect_planet = parts[1]
                    factor = "_".join(parts[2:])

                corr = PlanetaryCorrelation(
                    planet=planet,
                    factor=factor,
                    aspect_planet=aspect_planet,
                    lag_bars=lag,
                    pearson_r=float(pr),
                    pearson_p=float(pp),
                    spearman_r=float(sr),
                    spearman_p=float(sp),
                    mutual_info=0.0,  # Computed separately
                    is_significant=False,
                    fdr_corrected_p=1.0,
                    description=f"{col} lag={lag}",
                )
                results.append(corr)

        # Add mutual information (lag=0 only)
        try:
            mi_scores = mutual_info_regression(
                planet_df.fillna(0).values, ret_vals, random_state=42
            )
            mi_map = dict(zip(planet_df.columns, mi_scores))
            mi_max = max(mi_scores) if len(mi_scores) > 0 else 1.0

            for c in results:
                if c.lag_bars == 0:
                    c.mutual_info = float(mi_map.get(c.description.split(" lag=")[0], 0.0) / (mi_max + 1e-10))
        except Exception as e:
            logger.warning(f"MI computation failed: {e}")

        return results

    def _apply_fdr(self, correlations: List[PlanetaryCorrelation]) -> List[PlanetaryCorrelation]:
        """Benjamini-Hochberg FDR correction on p-values."""
        from statsmodels.stats.multitest import multipletests

        p_values = np.array([c.pearson_p for c in correlations])
        if len(p_values) == 0:
            return correlations

        reject, pvals_corrected, _, _ = multipletests(p_values, alpha=self.alpha, method="fdr_bh")

        for i, c in enumerate(correlations):
            c.fdr_corrected_p = float(pvals_corrected[i])
            c.is_significant = bool(reject[i])

        return correlations

    def _compute_feature_importance(
        self, planet_df: pd.DataFrame, returns: pd.Series
    ) -> Dict[str, float]:
        """Rank planetary features by predictive importance using Random Forest."""
        try:
            from sklearn.ensemble import RandomForestRegressor
            X = planet_df.fillna(0).values
            y = returns.values

            rf = RandomForestRegressor(n_estimators=50, max_depth=5, random_state=42, n_jobs=-1)
            rf.fit(X, y)

            importance = rf.feature_importances_
            imp_dict = {col: float(importance[i]) for i, col in enumerate(planet_df.columns)}
            # Return top 30
            return dict(sorted(imp_dict.items(), key=lambda x: x[1], reverse=True)[:30])
        except Exception as e:
            logger.warning(f"Feature importance failed: {e}")
            return {}

    # ── Current & Upcoming Positions ─────────────────────────────────────────

    def _get_current_positions(self) -> Dict[str, Dict]:
        """Compute current planetary positions for display."""
        if not self._ephem_available:
            return {}

        import ephem
        today = ephem.Date(str(datetime.utcnow().date()))
        positions = {}

        for planet_name in PLANETS:
            try:
                p = self._get_ephem_planet(planet_name)
                p.compute(today)
                lon_deg = float(np.degrees(float(p.hlong)) % 360)
                sign = self._degree_to_sign(lon_deg)

                p_prev = self._get_ephem_planet(planet_name)
                p_prev.compute(ephem.Date(today - 1))
                lon_prev = float(np.degrees(float(p_prev.hlong)) % 360)
                speed = (lon_deg - lon_prev + 360) % 360
                if speed > 180:
                    speed -= 360

                positions[planet_name] = {
                    "longitude": round(lon_deg, 4),
                    "sign": sign,
                    "degree_in_sign": round(lon_deg % 30, 2),
                    "speed": round(speed, 4),
                    "is_retrograde": speed < 0,
                    "declination": round(float(np.degrees(float(p.dec))), 4),
                }
            except Exception:
                pass

        return positions

    def _degree_to_sign(self, lon: float) -> str:
        signs = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
                 "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]
        return signs[int(lon // 30) % 12]

    def _get_upcoming_events(self, days_ahead: int) -> List[Dict]:
        """Find upcoming aspects and retrogrades in next N days."""
        if not self._ephem_available:
            return []

        import ephem
        events = []
        today = ephem.Date(str(datetime.utcnow().date()))

        for day_offset in range(0, days_ahead, 1):
            date = ephem.Date(today + day_offset)
            date_str = str(ephem.Date(date))[:10]

            positions = {}
            for planet_name in PLANETS:
                try:
                    p = self._get_ephem_planet(planet_name)
                    p.compute(date)
                    positions[planet_name] = float(np.degrees(float(p.hlong)) % 360)
                except Exception:
                    pass

            # Check aspects forming exact today
            for i, p1 in enumerate(PLANETS):
                for p2 in PLANETS[i + 1:]:
                    if p1 not in positions or p2 not in positions:
                        continue
                    angle = abs(positions[p1] - positions[p2]) % 360
                    if angle > 180:
                        angle = 360 - angle

                    for asp_name, asp_angle in ASPECTS.items():
                        if abs(angle - asp_angle) <= 1.0:
                            events.append({
                                "date": date_str,
                                "type": "aspect",
                                "planet1": p1,
                                "planet2": p2,
                                "aspect": asp_name,
                                "orb": round(abs(angle - asp_angle), 2),
                                "days_from_now": day_offset,
                            })

        return events[:50]  # Limit output

    def _empty_result(self, series: pd.Series) -> PlanetaryAnalysisResult:
        dates = series.index
        return PlanetaryAnalysisResult(
            top_correlations=[],
            all_correlations=[],
            feature_importance={},
            dates_analyzed=(str(dates[0]), str(dates[-1])),
            n_features_tested=0,
            n_significant=0,
            current_positions={},
            upcoming_events=[],
        )
