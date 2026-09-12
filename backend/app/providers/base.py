"""
UNIFIED DATA PROVIDER LAYER
============================
A single abstraction over Indian broker APIs and global market-data sources.

Every provider — whether it's Zerodha, Upstox, Angel One, Dhan, Yahoo, Stooq,
Alpha Vantage, or Twelve Data — implements the same `DataProvider` interface and
returns a normalized OHLCV DataFrame. Downstream cycle-discovery code never needs
to know where the data came from.

Design goals:
  • Add a new broker by writing one adapter class (~80 lines).
  • Indian brokers and global sources are interchangeable at the call site.
  • Auth/session handling is encapsulated per provider.
  • Instrument symbol resolution is normalized (NIFTY → each provider's token).
"""
from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Optional, Dict, List, Any

import pandas as pd

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# ENUMS & TYPES
# ─────────────────────────────────────────────────────────────────────────────

class ProviderRegion(str, Enum):
    INDIA = "india"
    GLOBAL = "global"


class ProviderCapability(str, Enum):
    HISTORICAL = "historical"      # Historical candle data
    LIVE_QUOTE = "live_quote"      # Real-time LTP / quote
    STREAMING = "streaming"        # WebSocket tick streaming
    INTRADAY = "intraday"          # Sub-daily candles
    OPTIONS = "options"            # Options chain / F&O
    PLACE_ORDER = "place_order"    # Trade execution


# Canonical interval strings used across the whole platform
CANONICAL_INTERVALS = ["1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w"]


@dataclass
class ProviderInfo:
    """Static metadata describing a provider."""
    key: str                                    # "zerodha", "yahoo", ...
    name: str                                   # Human-readable
    region: ProviderRegion
    capabilities: List[ProviderCapability]
    requires_auth: bool
    auth_type: str                              # "oauth_request_token" | "totp_jwt" | "bearer_token" | "none" | "api_key"
    supported_intervals: List[str]
    max_history_days: Optional[int] = None
    rate_limit_per_min: Optional[int] = None
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "region": self.region.value,
            "capabilities": [c.value for c in self.capabilities],
            "requires_auth": self.requires_auth,
            "auth_type": self.auth_type,
            "supported_intervals": self.supported_intervals,
            "max_history_days": self.max_history_days,
            "rate_limit_per_min": self.rate_limit_per_min,
            "notes": self.notes,
        }


@dataclass
class AuthSession:
    """Holds active credentials/tokens for an authenticated provider."""
    provider_key: str
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    feed_token: Optional[str] = None            # Angel One streaming token
    user_id: Optional[str] = None
    extras: Dict[str, Any] = field(default_factory=dict)
    expires_at: Optional[datetime] = None

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.utcnow() >= self.expires_at


# ─────────────────────────────────────────────────────────────────────────────
# ABSTRACT BASE
# ─────────────────────────────────────────────────────────────────────────────

class DataProvider(abc.ABC):
    """
    Abstract base every provider implements.

    The contract: given a symbol, interval, and date range, return a DataFrame
    indexed by timezone-naive datetime with columns [open, high, low, close, volume].
    """

    info: ProviderInfo

    def __init__(self, session: Optional[AuthSession] = None):
        self.session = session

    # ── Required ─────────────────────────────────────────────────────────────

    @abc.abstractmethod
    async def fetch_ohlcv(
        self,
        symbol: str,
        interval: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """Return normalized OHLCV DataFrame. Must be implemented by every provider."""
        ...

    # ── Optional (override where supported) ──────────────────────────────────

    async def resolve_symbol(self, symbol: str) -> str:
        """
        Map a user-facing symbol (e.g. "NIFTY", "RELIANCE") to this provider's
        native instrument identifier (token, instrument_key, security_id, etc.).
        Default: pass through unchanged.
        """
        return symbol

    async def get_live_quote(self, symbol: str) -> Optional[Dict]:
        """Return current LTP/quote if the provider supports it."""
        raise NotImplementedError(f"{self.info.key} does not support live quotes")

    def supports(self, capability: ProviderCapability) -> bool:
        return capability in self.info.capabilities

    # ── Normalization helpers (shared by all subclasses) ─────────────────────

    @staticmethod
    def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
        """Ensure standard columns, datetime index, sorted, positive close."""
        df = df.copy()
        df.columns = [c.lower().strip() for c in df.columns]

        # Standardize common column aliases
        rename = {
            "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume",
            "vol": "volume", "datetime": "timestamp", "date": "timestamp",
            "time": "timestamp", "ltp": "close", "last_price": "close",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

        # Set datetime index
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            df = df.set_index("timestamp")
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index, utc=True, errors="coerce")

        # Drop tz to keep everything naive-UTC internally
        if df.index.tz is not None:
            df.index = df.index.tz_convert("UTC").tz_localize(None)

        # Keep only OHLCV; fill missing volume
        for col in ["open", "high", "low", "close"]:
            if col not in df.columns:
                if "close" in df.columns:
                    df[col] = df["close"]
                else:
                    raise ValueError(f"Provider returned no '{col}' column")
        if "volume" not in df.columns:
            df["volume"] = 0.0

        df = df[["open", "high", "low", "close", "volume"]].astype(float)
        df = df[df["close"] > 0].sort_index()
        df = df[~df.index.duplicated(keep="first")]
        return df.dropna(subset=["close"])

    @staticmethod
    def _map_interval(canonical: str, mapping: Dict[str, str]) -> str:
        """Translate a canonical interval to a provider-specific one."""
        if canonical not in mapping:
            raise ValueError(
                f"Interval '{canonical}' not supported. "
                f"Available: {', '.join(mapping.keys())}"
            )
        return mapping[canonical]
