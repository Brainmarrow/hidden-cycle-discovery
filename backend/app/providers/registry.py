"""
PROVIDER REGISTRY
=================
Central registry + smart router for all data providers.

Responsibilities:
  • Hold the catalog of every Indian broker + global source.
  • Resolve "which provider should serve this request" given user intent.
  • Provide automatic fallback (broker fails → global source) so analysis never
    dies just because one feed is down or a token expired.
  • Expose a single `get_ohlcv()` entry point the rest of the platform calls.
"""
from __future__ import annotations

import logging
from typing import Optional, Dict, List, Type

import pandas as pd

from app.providers.base import (
    DataProvider, ProviderInfo, ProviderRegion, ProviderCapability, AuthSession,
)
from app.providers.indian_brokers import (
    ZerodhaProvider, UpstoxProvider, AngelOneProvider, DhanProvider, FyersProvider,
)
from app.providers.global_sources import (
    YahooProvider, StooqProvider, AlphaVantageProvider, TwelveDataProvider, CCXTProvider,
)

logger = logging.getLogger(__name__)


# ── Catalog ───────────────────────────────────────────────────────────────────

PROVIDER_CLASSES: Dict[str, Type[DataProvider]] = {
    # Indian brokers
    "zerodha": ZerodhaProvider,
    "upstox": UpstoxProvider,
    "angelone": AngelOneProvider,
    "dhan": DhanProvider,
    "fyers": FyersProvider,
    # Global sources
    "yahoo": YahooProvider,
    "stooq": StooqProvider,
    "alpha_vantage": AlphaVantageProvider,
    "twelve_data": TwelveDataProvider,
    "ccxt": CCXTProvider,
}

# Order in which we try global sources as automatic fallback
GLOBAL_FALLBACK_ORDER = ["yahoo", "stooq", "twelve_data", "alpha_vantage"]

# Indian index symbols recognized across providers
INDIAN_INDEX_SYMBOLS = {
    "NIFTY", "NIFTY 50", "BANKNIFTY", "NIFTY BANK", "FINNIFTY", "SENSEX",
    "MIDCPNIFTY", "NIFTY IT", "NIFTY AUTO", "NIFTY PHARMA", "NIFTY FMCG",
}


class ProviderRegistry:
    """Singleton-style registry that all data requests flow through."""

    @staticmethod
    def list_providers(region: Optional[ProviderRegion] = None) -> List[ProviderInfo]:
        """Return metadata for all (or region-filtered) providers."""
        infos = [cls.info for cls in PROVIDER_CLASSES.values()]
        if region:
            infos = [i for i in infos if i.region == region]
        return infos

    @staticmethod
    def get_info(key: str) -> Optional[ProviderInfo]:
        cls = PROVIDER_CLASSES.get(key)
        return cls.info if cls else None

    @staticmethod
    def create(key: str, session: Optional[AuthSession] = None, **kwargs) -> DataProvider:
        """Instantiate a provider by key, optionally with an auth session."""
        cls = PROVIDER_CLASSES.get(key)
        if not cls:
            raise ValueError(f"Unknown provider: '{key}'. Available: {list(PROVIDER_CLASSES)}")
        # Providers with custom __init__ signatures
        if key in ("alpha_vantage", "twelve_data", "ccxt"):
            return cls(session=session, **kwargs)
        return cls(session=session)

    # ── Smart routing ────────────────────────────────────────────────────────

    @staticmethod
    def suggest_provider(symbol: str, prefer_broker: Optional[str] = None) -> str:
        """
        Pick the best default provider for a symbol when the user hasn't named one.

        Logic:
          • Crypto pair (has '/') → ccxt
          • Indian index/equity + a connected broker → that broker
          • Indian symbol, no broker → yahoo (with .NS resolution)
          • Everything else (global) → yahoo
        """
        up = symbol.upper().strip()

        if "/" in symbol or up.endswith("USDT") or up.endswith("USD") and len(up) <= 7:
            # crude crypto detection; refine with a real symbol table in prod
            if "/" in symbol:
                return "ccxt"

        is_indian = (
            up in INDIAN_INDEX_SYMBOLS
            or symbol.endswith(".NS") or symbol.endswith(".BO")
        )

        if is_indian and prefer_broker and prefer_broker in PROVIDER_CLASSES:
            return prefer_broker
        if is_indian:
            return "yahoo"   # works for Indian symbols via ^NSEI / .NS, no auth

        return "yahoo"

    # ── Unified entry point with fallback ────────────────────────────────────

    @staticmethod
    async def get_ohlcv(
        symbol: str,
        interval: str = "1d",
        start: Optional[str] = None,
        end: Optional[str] = None,
        provider_key: Optional[str] = None,
        session: Optional[AuthSession] = None,
        enable_fallback: bool = True,
        provider_kwargs: Optional[dict] = None,
    ) -> Dict:
        """
        The single function the platform calls to get market data.

        Returns:
            {
              "data": <DataFrame>,
              "provider": <key actually used>,
              "fell_back": <bool>,
              "attempts": [<keys tried>],
            }

        If `provider_key` is given, that provider is used. If it fails and
        `enable_fallback` is on, we cascade through global sources so the user
        still gets data (e.g. broker token expired at 6am → Yahoo serves daily).
        """
        provider_kwargs = provider_kwargs or {}
        attempts: List[str] = []

        # Decide primary provider
        primary = provider_key or ProviderRegistry.suggest_provider(symbol)

        # Build the try-order: primary first, then global fallbacks (dedup)
        try_order = [primary]
        if enable_fallback:
            for fb in GLOBAL_FALLBACK_ORDER:
                if fb not in try_order:
                    try_order.append(fb)

        last_error = None
        for i, key in enumerate(try_order):
            attempts.append(key)
            try:
                # Auth session only applies to the primary broker, not fallbacks
                use_session = session if key == primary else None
                provider = ProviderRegistry.create(key, session=use_session, **(provider_kwargs if key == primary else {}))

                # Skip auth-required providers in fallback if we have no session
                if key != primary and provider.info.requires_auth:
                    continue

                df = await provider.fetch_ohlcv(symbol, interval, start, end)
                if df is None or len(df) < 10:
                    raise ValueError(f"{key} returned insufficient data")

                logger.info(
                    "ohlcv_fetched provider=%s symbol=%s bars=%d fell_back=%s",
                    key, symbol, len(df), i > 0,
                )
                return {
                    "data": df,
                    "provider": key,
                    "fell_back": i > 0,
                    "attempts": attempts,
                }
            except Exception as e:
                last_error = e
                logger.warning("provider_failed provider=%s symbol=%s error=%s", key, symbol, str(e))
                continue

        raise RuntimeError(
            f"All providers failed for {symbol}. Tried: {attempts}. Last error: {last_error}"
        )
