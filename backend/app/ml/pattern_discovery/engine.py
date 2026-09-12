"""
MODULE 3: PATTERN DISCOVERY ENGINE
=====================================
Detects recurring structural patterns using:
- DTW-based clustering
- KMeans / Hierarchical clustering
- STUMPY matrix profile (motif discovery)
- Regime detection via HMM
- Volatility cycle identification
- Shape similarity search
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from enum import Enum

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import dendrogram, linkage, fcluster
from scipy.spatial.distance import pdist, squareform
from sklearn.cluster import KMeans, DBSCAN
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

logger = logging.getLogger(__name__)


@dataclass
class PatternOccurrence:
    start_idx: int
    end_idx: int
    similarity: float
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    forward_return_5: Optional[float] = None
    forward_return_20: Optional[float] = None


@dataclass
class Pattern:
    pattern_id: str
    pattern_type: str           # shape | turning_point | volatility | regime
    cluster_id: int
    template: np.ndarray        # Normalized shape centroid
    occurrences: List[PatternOccurrence]
    occurrence_count: int
    avg_duration_bars: float
    similarity_threshold: float
    mean_forward_return: float
    std_forward_return: float
    hit_rate: float             # % occurrences where forward_return > 0
    sharpe_like: float

    def to_dict(self) -> dict:
        return {
            "pattern_id": self.pattern_id,
            "pattern_type": self.pattern_type,
            "cluster_id": self.cluster_id,
            "template": self.template.tolist(),
            "occurrence_count": self.occurrence_count,
            "avg_duration_bars": round(self.avg_duration_bars, 1),
            "similarity_threshold": round(self.similarity_threshold, 4),
            "mean_forward_return": round(self.mean_forward_return, 6),
            "std_forward_return": round(self.std_forward_return, 6),
            "hit_rate": round(self.hit_rate, 4),
            "sharpe_like": round(self.sharpe_like, 4),
            "occurrences": [
                {
                    "start_idx": o.start_idx,
                    "end_idx": o.end_idx,
                    "similarity": round(o.similarity, 4),
                    "start_date": o.start_date,
                    "end_date": o.end_date,
                    "forward_return_5": o.forward_return_5,
                    "forward_return_20": o.forward_return_20,
                }
                for o in self.occurrences
            ],
        }


@dataclass
class PatternDiscoveryResult:
    patterns: List[Pattern]
    regimes: Optional[pd.Series] = None
    regime_stats: Optional[Dict] = None
    motifs: Optional[List[Dict]] = None
    n_bars: int = 0

    def to_dict(self) -> dict:
        return {
            "patterns": [p.to_dict() for p in self.patterns],
            "regime_stats": self.regime_stats,
            "motifs": self.motifs,
            "n_bars": self.n_bars,
        }


class PatternDiscoveryEngine:
    """
    Discovers repeating structural patterns in market data.
    """

    def __init__(
        self,
        window_sizes: Optional[List[int]] = None,
        n_clusters: Optional[int] = None,  # None = auto
        max_patterns: int = 20,
        min_occurrences: int = 3,
        dtw_enabled: bool = True,
        regime_n_states: int = 3,
    ):
        self.window_sizes = window_sizes or [10, 20, 40, 60, 120]
        self.n_clusters = n_clusters
        self.max_patterns = max_patterns
        self.min_occurrences = min_occurrences
        self.dtw_enabled = dtw_enabled
        self.regime_n_states = regime_n_states

    def discover(
        self,
        series: pd.Series,
        returns: Optional[pd.Series] = None,
    ) -> PatternDiscoveryResult:
        """
        Main entry point for pattern discovery.

        Args:
            series: Normalized price/detrended series (DatetimeIndex)
            returns: Log returns for forward return calculation
        """
        values = series.dropna().values.astype(np.float64)
        dates = series.dropna().index if hasattr(series, "index") else None
        n = len(values)

        all_patterns: List[Pattern] = []

        # ── 1. Shape patterns via sliding windows + clustering ─────────
        for window in self.window_sizes:
            if window >= n // 3:
                continue
            patterns = self._discover_shape_patterns(values, window, returns, dates)
            all_patterns.extend(patterns)

        # ── 2. Matrix profile motif discovery ─────────────────────────
        motifs = self._matrix_profile_motifs(values, min(self.window_sizes))

        # ── 3. Regime detection ────────────────────────────────────────
        regimes, regime_stats = self._detect_regimes(series, returns)

        # ── 4. Volatility cycle patterns ───────────────────────────────
        if returns is not None:
            vol_patterns = self._volatility_cycle_patterns(returns, dates)
            all_patterns.extend(vol_patterns)

        # ── 5. Turning point sequence patterns ────────────────────────
        tp_patterns = self._turning_point_patterns(values, returns, dates)
        all_patterns.extend(tp_patterns)

        # Rank by sharpe_like and occurrence count
        all_patterns.sort(key=lambda p: (p.sharpe_like * p.occurrence_count), reverse=True)
        all_patterns = all_patterns[: self.max_patterns]

        return PatternDiscoveryResult(
            patterns=all_patterns,
            regimes=regimes,
            regime_stats=regime_stats,
            motifs=motifs,
            n_bars=n,
        )

    # ── Shape Patterns via Clustering ────────────────────────────────────────

    def _discover_shape_patterns(
        self,
        values: np.ndarray,
        window: int,
        returns: Optional[pd.Series],
        dates,
    ) -> List[Pattern]:
        """Extract overlapping windows, cluster shapes, compute stats."""
        step = max(1, window // 4)
        windows = []
        indices = []

        for i in range(0, len(values) - window, step):
            w = values[i: i + window]
            if np.std(w) < 1e-8:
                continue
            windows.append(self._normalize_window(w))
            indices.append(i)

        if len(windows) < self.min_occurrences * 2:
            return []

        X = np.array(windows)

        # Determine optimal clusters
        n_clusters = self.n_clusters or self._optimal_clusters(X, max_k=min(12, len(X) // 5))
        if n_clusters < 2:
            return []

        # Cluster
        if self.dtw_enabled and len(X) <= 500:
            labels = self._dtw_cluster(X, n_clusters)
        else:
            km = KMeans(n_clusters=n_clusters, n_init=10, random_state=42)
            labels = km.fit_predict(X)

        patterns = []
        for cluster_id in range(n_clusters):
            mask = labels == cluster_id
            cluster_indices = [indices[i] for i in range(len(indices)) if mask[i]]
            cluster_windows = X[mask]

            if len(cluster_indices) < self.min_occurrences:
                continue

            template = cluster_windows.mean(axis=0)
            similarities = [self._cosine_similarity(w, template) for w in cluster_windows]

            # Forward returns
            occurrences = []
            fwd_returns = []

            for j, start_idx in enumerate(cluster_indices):
                end_idx = start_idx + window
                occ = PatternOccurrence(
                    start_idx=start_idx,
                    end_idx=end_idx,
                    similarity=float(similarities[j]),
                    start_date=str(dates[start_idx]) if dates is not None else None,
                    end_date=str(dates[min(end_idx, len(dates) - 1)]) if dates is not None else None,
                )

                if returns is not None and end_idx + 5 < len(returns):
                    ret_vals = returns.values
                    occ.forward_return_5 = float(ret_vals[end_idx: end_idx + 5].sum())
                    occ.forward_return_20 = float(ret_vals[end_idx: end_idx + 20].sum()) \
                        if end_idx + 20 < len(ret_vals) else None
                    if occ.forward_return_5 is not None:
                        fwd_returns.append(occ.forward_return_5)

                occurrences.append(occ)

            fwd_arr = np.array(fwd_returns) if fwd_returns else np.array([0.0])
            mean_ret = float(fwd_arr.mean())
            std_ret = float(fwd_arr.std()) + 1e-10
            hit_rate = float((fwd_arr > 0).mean())
            sharpe = mean_ret / std_ret

            patterns.append(Pattern(
                pattern_id=f"shape_w{window}_c{cluster_id}",
                pattern_type="shape",
                cluster_id=cluster_id,
                template=template,
                occurrences=occurrences,
                occurrence_count=len(occurrences),
                avg_duration_bars=float(window),
                similarity_threshold=float(np.percentile(similarities, 25)),
                mean_forward_return=mean_ret,
                std_forward_return=std_ret,
                hit_rate=hit_rate,
                sharpe_like=sharpe,
            ))

        return patterns

    def _normalize_window(self, w: np.ndarray) -> np.ndarray:
        """Z-score normalize a window for shape comparison."""
        std = w.std()
        if std < 1e-8:
            return np.zeros_like(w)
        return (w - w.mean()) / std

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        denom = (np.linalg.norm(a) * np.linalg.norm(b))
        if denom < 1e-10:
            return 0.0
        return float(np.dot(a, b) / denom)

    def _optimal_clusters(self, X: np.ndarray, max_k: int = 10) -> int:
        """Elbow method + silhouette to find optimal k."""
        if len(X) < 10 or max_k < 2:
            return 2

        best_k = 2
        best_score = -1.0

        for k in range(2, min(max_k + 1, len(X))):
            try:
                km = KMeans(n_clusters=k, n_init=5, random_state=42, max_iter=100)
                labels = km.fit_predict(X)
                if len(np.unique(labels)) < 2:
                    continue
                score = silhouette_score(X, labels, sample_size=min(500, len(X)))
                if score > best_score:
                    best_score = score
                    best_k = k
            except Exception:
                continue

        return best_k

    def _dtw_cluster(self, X: np.ndarray, n_clusters: int) -> np.ndarray:
        """DTW-based clustering using dtaidistance."""
        try:
            from dtaidistance import dtw, clustering as dtw_clustering
            ds = dtw.distance_matrix_fast(X.tolist())
            model = dtw_clustering.Hierarchical(
                dtw_clustering.HierarchicalLinkage.complete, {}, n_clusters
            )
            labels = model.fit(ds)
            return np.array(labels)
        except Exception as e:
            logger.warning(f"DTW clustering failed: {e}, falling back to KMeans")
            km = KMeans(n_clusters=n_clusters, n_init=10, random_state=42)
            return km.fit_predict(X)

    # ── Matrix Profile (STUMPY) ──────────────────────────────────────────────

    def _matrix_profile_motifs(self, values: np.ndarray, window: int) -> List[Dict]:
        """Find top motifs (most similar non-overlapping subsequences)."""
        try:
            import stumpy
            if len(values) < window * 4:
                return []

            mp = stumpy.stump(values, m=window)
            motif_distances = mp[:, 0].astype(float)
            motif_indices = mp[:, 1].astype(int)

            top_motifs = []
            used = set()

            sorted_idx = np.argsort(motif_distances)
            for i in sorted_idx[:10]:
                j = motif_indices[i]
                if i in used or j in used:
                    continue
                if abs(int(i) - int(j)) < window:
                    continue

                # Mark exclusion zone
                for k in range(max(0, i - window // 2), min(len(values), i + window // 2)):
                    used.add(k)
                for k in range(max(0, j - window // 2), min(len(values), j + window // 2)):
                    used.add(k)

                top_motifs.append({
                    "motif_a_start": int(i),
                    "motif_b_start": int(j),
                    "window_size": window,
                    "distance": float(motif_distances[i]),
                    "similarity": float(1.0 / (1.0 + motif_distances[i])),
                })

                if len(top_motifs) >= 5:
                    break

            return top_motifs

        except ImportError:
            logger.warning("STUMPY not installed, skipping matrix profile motifs")
            return []
        except Exception as e:
            logger.warning(f"Matrix profile failed: {e}")
            return []

    # ── Regime Detection ─────────────────────────────────────────────────────

    def _detect_regimes(
        self, series: pd.Series, returns: Optional[pd.Series]
    ) -> Tuple[Optional[pd.Series], Optional[Dict]]:
        """Detect market regimes using Hidden Markov Model."""
        try:
            from hmmlearn import hmm

            # Features: returns + rolling vol
            if returns is None:
                returns = series.pct_change()

            vol = returns.rolling(20).std().fillna(method="bfill")
            X = np.column_stack([
                returns.values,
                vol.values,
                (returns.rolling(5).mean()).fillna(0).values,
            ])
            X = StandardScaler().fit_transform(X)

            n_states = self.regime_n_states
            model = hmm.GaussianHMM(
                n_components=n_states,
                covariance_type="full",
                n_iter=200,
                random_state=42,
            )
            model.fit(X)
            regime_labels = model.predict(X)
            regimes = pd.Series(regime_labels, index=series.index, name="regime")

            # Compute regime statistics
            regime_stats = {}
            for state in range(n_states):
                mask = regime_labels == state
                if returns is not None:
                    state_returns = returns.values[mask]
                    regime_stats[f"regime_{state}"] = {
                        "count": int(mask.sum()),
                        "pct": float(mask.mean()),
                        "mean_return": float(state_returns.mean()),
                        "vol": float(state_returns.std()),
                        "sharpe": float(state_returns.mean() / (state_returns.std() + 1e-10)),
                        "label": self._classify_regime(state_returns),
                    }

            return regimes, regime_stats

        except ImportError:
            logger.warning("hmmlearn not installed, skipping regime detection")
            return None, None
        except Exception as e:
            logger.warning(f"Regime detection failed: {e}")
            return None, None

    def _classify_regime(self, returns: np.ndarray) -> str:
        mean = returns.mean()
        vol = returns.std()
        if mean > 0.001 and vol < 0.01:
            return "trending_up_low_vol"
        elif mean > 0.001 and vol >= 0.01:
            return "trending_up_high_vol"
        elif mean < -0.001 and vol >= 0.01:
            return "trending_down_high_vol"
        elif mean < -0.001 and vol < 0.01:
            return "trending_down_low_vol"
        else:
            return "sideways_consolidation"

    # ── Volatility Cycle Patterns ─────────────────────────────────────────────

    def _volatility_cycle_patterns(
        self, returns: pd.Series, dates
    ) -> List[Pattern]:
        """Find repeating high/low volatility cycles."""
        vol = returns.rolling(20).std().fillna(method="bfill")
        vol_z = (vol - vol.mean()) / (vol.std() + 1e-10)

        # Find high-vol and low-vol regimes via threshold
        high_vol = vol_z > 1.0
        low_vol = vol_z < -0.5

        patterns = []

        for regime_type, mask in [("high_vol", high_vol), ("low_vol", low_vol)]:
            # Find contiguous runs
            runs = []
            in_run = False
            run_start = 0
            for i, flag in enumerate(mask):
                if flag and not in_run:
                    in_run = True
                    run_start = i
                elif not flag and in_run:
                    in_run = False
                    runs.append((run_start, i - 1))
            if in_run:
                runs.append((run_start, len(mask) - 1))

            if len(runs) < self.min_occurrences:
                continue

            durations = [r[1] - r[0] for r in runs]
            fwd_rets = []

            occurrences = []
            for r in runs:
                occ = PatternOccurrence(
                    start_idx=r[0],
                    end_idx=r[1],
                    similarity=1.0,
                    start_date=str(dates[r[0]]) if dates is not None else None,
                    end_date=str(dates[r[1]]) if dates is not None else None,
                )
                end = r[1]
                if end + 5 < len(returns):
                    fwd = float(returns.values[end: end + 5].sum())
                    occ.forward_return_5 = fwd
                    fwd_rets.append(fwd)
                occurrences.append(occ)

            fwd_arr = np.array(fwd_rets) if fwd_rets else np.array([0.0])
            mean_ret = float(fwd_arr.mean())
            std_ret = float(fwd_arr.std()) + 1e-10

            patterns.append(Pattern(
                pattern_id=f"volcycle_{regime_type}",
                pattern_type="volatility_cycle",
                cluster_id=0,
                template=np.array([]),
                occurrences=occurrences,
                occurrence_count=len(occurrences),
                avg_duration_bars=float(np.mean(durations)),
                similarity_threshold=1.0,
                mean_forward_return=mean_ret,
                std_forward_return=std_ret,
                hit_rate=float((fwd_arr > 0).mean()),
                sharpe_like=mean_ret / std_ret,
            ))

        return patterns

    # ── Turning Point Sequence Patterns ──────────────────────────────────────

    def _turning_point_patterns(
        self, values: np.ndarray, returns: Optional[pd.Series], dates
    ) -> List[Pattern]:
        """Find sequences of peaks and troughs that repeat."""
        from scipy.signal import argrelextrema

        # Find local peaks and troughs
        order = max(3, len(values) // 100)
        peaks = argrelextrema(values, np.greater, order=order)[0]
        troughs = argrelextrema(values, np.less, order=order)[0]

        if len(peaks) < 3 or len(troughs) < 3:
            return []

        # Build alternating P/T sequence and compute intervals
        events = sorted(
            [(i, "P") for i in peaks] + [(i, "T") for i in troughs],
            key=lambda x: x[0],
        )

        intervals = []
        for i in range(1, len(events)):
            dt = events[i][0] - events[i - 1][0]
            tp_type = events[i][1]
            intervals.append((dt, tp_type))

        if len(intervals) < 4:
            return []

        # Look for repeating interval sequences of length 2, 3, 4
        patterns = []
        for seq_len in [2, 3, 4]:
            if len(intervals) < seq_len * 2:
                continue

            sequences = [
                tuple(intervals[i: i + seq_len])
                for i in range(len(intervals) - seq_len + 1)
            ]

            # Count unique sequences
            from collections import Counter
            seq_counts = Counter(sequences)

            for seq, count in seq_counts.most_common(3):
                if count < self.min_occurrences:
                    continue

                # Find occurrence indices
                occ_list = []
                for i, s in enumerate(sequences):
                    if s == seq:
                        start_idx = events[i][0]
                        end_idx = events[i + seq_len][0] if i + seq_len < len(events) else events[-1][0]
                        occ = PatternOccurrence(
                            start_idx=start_idx,
                            end_idx=end_idx,
                            similarity=1.0,
                            start_date=str(dates[start_idx]) if dates is not None else None,
                            end_date=str(dates[min(end_idx, len(dates) - 1)]) if dates is not None else None,
                        )
                        if returns is not None and end_idx + 5 < len(returns):
                            occ.forward_return_5 = float(returns.values[end_idx: end_idx + 5].sum())
                        occ_list.append(occ)

                fwd_rets = [o.forward_return_5 for o in occ_list if o.forward_return_5 is not None]
                fwd_arr = np.array(fwd_rets) if fwd_rets else np.array([0.0])

                avg_dur = np.mean([sum(s[0] for s in seq)] if seq else [0])
                mean_ret = float(fwd_arr.mean())
                std_ret = float(fwd_arr.std()) + 1e-10

                patterns.append(Pattern(
                    pattern_id=f"tp_seq_{seq_len}_{hash(seq) % 10000}",
                    pattern_type="turning_point_sequence",
                    cluster_id=0,
                    template=np.array([]),
                    occurrences=occ_list,
                    occurrence_count=count,
                    avg_duration_bars=float(avg_dur),
                    similarity_threshold=1.0,
                    mean_forward_return=mean_ret,
                    std_forward_return=std_ret,
                    hit_rate=float((fwd_arr > 0).mean()),
                    sharpe_like=mean_ret / std_ret,
                ))

        return patterns
