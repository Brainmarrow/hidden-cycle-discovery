"""
MODULE 7: ANALOG ENGINE
=========================
Finds historical periods most similar to current market conditions.

Methods:
- DTW (shape similarity)
- Euclidean distance on normalized windows
- Embedding similarity (cosine distance on AI model latent space)
- Multi-feature similarity (returns + vol + cycle phase)

Output: top N historical analogs with forward return distributions.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict

import numpy as np
import pandas as pd
from scipy.spatial.distance import cosine, euclidean

logger = logging.getLogger(__name__)


@dataclass
class AnalogMatch:
    rank: int
    start_idx: int
    end_idx: int
    start_date: str
    end_date: str
    similarity_score: float         # 0–1 (1 = perfect match)
    distance: float                 # Raw distance metric
    method: str
    # Forward return distribution after analog
    forward_returns: Dict[str, float]   # key: "5d", "10d", "20d", "60d"
    historical_outcome_direction: str   # "up" | "down" | "sideways"

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "similarity_score": round(self.similarity_score, 4),
            "distance": round(self.distance, 6),
            "method": self.method,
            "forward_returns": {k: round(v, 6) for k, v in self.forward_returns.items()},
            "historical_outcome_direction": self.historical_outcome_direction,
        }


@dataclass
class AnalogResult:
    query_start_date: str
    query_end_date: str
    query_window_bars: int
    top_analogs: List[AnalogMatch]
    composite_projection: Dict[str, float]   # Weighted avg forward returns
    projection_confidence: float             # Based on analog agreement
    similarity_method: str
    n_analogs_found: int

    def to_dict(self) -> dict:
        return {
            "query_start_date": self.query_start_date,
            "query_end_date": self.query_end_date,
            "query_window_bars": self.query_window_bars,
            "top_analogs": [a.to_dict() for a in self.top_analogs],
            "composite_projection": {k: round(v, 6) for k, v in self.composite_projection.items()},
            "projection_confidence": round(self.projection_confidence, 4),
            "similarity_method": self.similarity_method,
            "n_analogs_found": self.n_analogs_found,
        }


class AnalogEngine:
    """
    Historical analog discovery engine.
    Finds past market periods that most closely resemble the current window.
    """

    def __init__(
        self,
        lookback_bars: int = 60,           # Size of comparison window
        top_n: int = 10,
        min_separation_bars: int = 30,     # Exclude overlapping windows
        method: str = "multi",             # euclidean | dtw | cosine | multi
        forward_horizons: Optional[List[int]] = None,
    ):
        self.lookback = lookback_bars
        self.top_n = top_n
        self.min_sep = min_separation_bars
        self.method = method
        self.horizons = forward_horizons or [5, 10, 20, 60]

    def find_analogs(
        self,
        series: pd.Series,
        returns: pd.Series,
        query_end_idx: Optional[int] = None,    # Default: last bar
        embeddings: Optional[np.ndarray] = None, # From Module 6 AI Model
    ) -> AnalogResult:
        """
        Find top N historical analogs to the current market window.

        Args:
            series: Full normalized price series (DatetimeIndex).
            returns: Log returns aligned with series.
            query_end_idx: Index of last bar of the current window.
            embeddings: Optional AI model embeddings for cosine similarity.
        """
        values = series.dropna().values.astype(np.float64)
        ret_vals = returns.dropna().values.astype(np.float64)
        dates = series.dropna().index

        if query_end_idx is None:
            query_end_idx = len(values) - 1

        query_start_idx = query_end_idx - self.lookback
        if query_start_idx < 0:
            raise ValueError(f"Not enough data: need {self.lookback} bars before query_end_idx")

        query_window = values[query_start_idx: query_end_idx + 1]
        query_norm = self._normalize_window(query_window)

        # Search all historical windows (before query_start to avoid lookahead)
        candidates = []
        for start in range(0, query_start_idx - self.lookback - self.min_sep):
            end = start + self.lookback
            hist_window = values[start: end + 1]
            hist_norm = self._normalize_window(hist_window)

            if np.isnan(hist_norm).any() or np.isnan(query_norm).any():
                continue

            # Distance
            if self.method == "euclidean" or self.method == "multi":
                dist_euc = euclidean(query_norm, hist_norm)
                candidates.append((start, end, dist_euc, "euclidean"))

            if self.method == "dtw" or self.method == "multi":
                dist_dtw = self._dtw_distance(query_norm, hist_norm)
                if self.method == "dtw":
                    candidates.append((start, end, dist_dtw, "dtw"))

        # Embedding-based similarity
        if embeddings is not None and self.method in ("cosine", "multi"):
            q_embedding = embeddings[min(query_end_idx, len(embeddings) - 1)]
            for i in range(len(embeddings)):
                if i >= query_start_idx - self.min_sep:
                    continue
                sim = 1.0 - cosine(q_embedding, embeddings[i])
                dist = 1.0 - sim
                candidates.append((i, i + self.lookback, dist, "cosine"))

        if not candidates:
            return self._empty_result(dates, query_start_idx, query_end_idx)

        # Multi-method: average distances across methods for same window
        if self.method == "multi":
            from collections import defaultdict
            window_dists = defaultdict(list)
            for start, end, dist, method in candidates:
                window_dists[start].append(dist)

            merged = [(start, start + self.lookback,
                       np.mean(dists), "multi")
                      for start, dists in window_dists.items()]
            candidates = merged

        # Deduplicate overlapping windows
        candidates = self._deduplicate(candidates)

        # Sort by distance
        candidates.sort(key=lambda x: x[2])

        # Build top-N analogs
        analogs = []
        max_dist = max(c[2] for c in candidates[:50]) + 1e-10

        for rank, (start, end, dist, method) in enumerate(candidates[: self.top_n]):
            similarity = 1.0 - (dist / max_dist)
            similarity = float(np.clip(similarity, 0.0, 1.0))

            # Forward returns after this analog period
            forward_returns = {}
            for h in self.horizons:
                fwd_end = end + h
                if fwd_end < len(ret_vals):
                    forward_returns[f"{h}d"] = float(ret_vals[end: fwd_end].sum())
                else:
                    forward_returns[f"{h}d"] = 0.0

            # Outcome direction
            fwd_5 = forward_returns.get("5d", 0.0)
            if fwd_5 > 0.005:
                direction = "up"
            elif fwd_5 < -0.005:
                direction = "down"
            else:
                direction = "sideways"

            analogs.append(AnalogMatch(
                rank=rank + 1,
                start_idx=int(start),
                end_idx=int(end),
                start_date=str(dates[start]) if start < len(dates) else "",
                end_date=str(dates[min(end, len(dates) - 1)]),
                similarity_score=similarity,
                distance=float(dist),
                method=method,
                forward_returns=forward_returns,
                historical_outcome_direction=direction,
            ))

        # Composite projection: similarity-weighted avg of forward returns
        composite, confidence = self._composite_projection(analogs)

        return AnalogResult(
            query_start_date=str(dates[query_start_idx]),
            query_end_date=str(dates[query_end_idx]),
            query_window_bars=self.lookback,
            top_analogs=analogs,
            composite_projection=composite,
            projection_confidence=confidence,
            similarity_method=self.method,
            n_analogs_found=len(analogs),
        )

    # ── Similarity Methods ───────────────────────────────────────────────────

    def _normalize_window(self, w: np.ndarray) -> np.ndarray:
        std = w.std()
        if std < 1e-8:
            return np.zeros_like(w)
        return (w - w.mean()) / std

    def _dtw_distance(self, a: np.ndarray, b: np.ndarray) -> float:
        """Fast DTW via dynamic programming."""
        try:
            from dtaidistance import dtw as dtw_dist
            return float(dtw_dist.distance_fast(a.astype(np.double), b.astype(np.double)))
        except ImportError:
            # Fallback: simplified DTW
            n, m = len(a), len(b)
            D = np.full((n + 1, m + 1), np.inf)
            D[0, 0] = 0
            for i in range(1, n + 1):
                for j in range(1, m + 1):
                    cost = (a[i - 1] - b[j - 1]) ** 2
                    D[i, j] = cost + min(D[i - 1, j], D[i, j - 1], D[i - 1, j - 1])
            return float(np.sqrt(D[n, m]))

    def _deduplicate(self, candidates: List) -> List:
        """Remove overlapping analog windows, keeping best match."""
        candidates = sorted(candidates, key=lambda x: x[2])
        used_ranges = []
        deduped = []

        for c in candidates:
            start, end = c[0], c[1]
            overlap = False
            for (us, ue) in used_ranges:
                if start < ue and end > us:
                    if abs(start - us) < self.min_sep:
                        overlap = True
                        break
            if not overlap:
                deduped.append(c)
                used_ranges.append((start, end))

        return deduped

    def _composite_projection(
        self, analogs: List[AnalogMatch]
    ) -> tuple:
        """Compute similarity-weighted composite forward return projection."""
        if not analogs:
            return {}, 0.0

        weights = np.array([a.similarity_score for a in analogs])
        weights = weights / (weights.sum() + 1e-10)

        composite = {}
        all_horizons = analogs[0].forward_returns.keys()
        for h in all_horizons:
            vals = np.array([a.forward_returns.get(h, 0.0) for a in analogs])
            composite[h] = float(np.dot(weights, vals))

        # Confidence: based on agreement (low std = high confidence)
        primary_rets = np.array([a.forward_returns.get("5d", 0.0) for a in analogs])
        std_ret = primary_rets.std()
        confidence = float(np.clip(1.0 - std_ret * 10, 0.1, 0.99))

        return composite, confidence

    def _empty_result(self, dates, query_start_idx, query_end_idx) -> AnalogResult:
        return AnalogResult(
            query_start_date=str(dates[query_start_idx]) if query_start_idx < len(dates) else "",
            query_end_date=str(dates[query_end_idx]) if query_end_idx < len(dates) else "",
            query_window_bars=self.lookback,
            top_analogs=[],
            composite_projection={},
            projection_confidence=0.0,
            similarity_method=self.method,
            n_analogs_found=0,
        )
