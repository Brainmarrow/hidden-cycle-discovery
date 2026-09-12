"""
GLOBAL MARKET DATA ADAPTERS
============================
Free / global data sources that need no broker account. These keep worldwide
market access intact alongside the Indian broker integrations.

  • Yahoo Finance (yfinance)  — global equities, indices, FX, crypto, commodities.
  • Stooq                     — CSV endpoint, CORS-friendly, global daily data.
  • Alpha Vantage             — API-key, intraday + daily, global.
  • Twelve Data               — API-key, global, generous free tier.
  • CCXT                      — crypto via 100+ exchanges.

Note on "Google Finance" / "Investing.com": neither offers a stable public OHLCV
API. Google Finance is a Sheets function (GOOGLEFINANCE) with no REST endpoint, and
Investing.com prohibits scraping. We route those user intents to Yahoo/Stooq, which
cover the same global instruments reliably and legally.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict

import pandas as pd

from app.providers.base import (
    DataProvider, ProviderInfo, ProviderRegion, ProviderCapability,
)

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# YAHOO FINANCE
# ═════════════════════════════════════════════════════════════════════════════

class YahooProvider(DataProvider):
    info = ProviderInfo(
        key="yahoo",
        name="Yahoo Finance",
        region=ProviderRegion.GLOBAL,
        capabilities=[ProviderCapability.HISTORICAL, ProviderCapability.INTRADAY,
                      ProviderCapability.LIVE_QUOTE],
        requires_auth=False,
        auth_type="none",
        supported_intervals=["1m", "5m", "15m", "30m", "1h", "1d", "1w"],
        max_history_days=7300,
        rate_limit_per_min=None,
        notes="No key required. Global coverage. Intraday limited to ~60 days. "
              "Indian symbols use .NS (NSE) / .BO (BSE) suffix.",
    )

    INTERVAL_MAP = {
        "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1h": "60m", "1d": "1d", "1w": "1wk",
    }

    INDEX_MAP = {
        "NIFTY": "^NSEI", "NIFTY 50": "^NSEI",
        "BANKNIFTY": "^NSEBANK", "NIFTY BANK": "^NSEBANK",
        "SENSEX": "^BSESN", "SPX": "^GSPC", "S&P500": "^GSPC",
        "NASDAQ": "^IXIC", "DOW": "^DJI", "VIX": "^VIX",
        "FTSE": "^FTSE", "NIKKEI": "^N225", "DAX": "^GDAXI",
    }

    async def resolve_symbol(self, symbol: str) -> str:
        return self.INDEX_MAP.get(symbol.upper().strip(), symbol)

    async def fetch_ohlcv(self, symbol, interval, start=None, end=None) -> pd.DataFrame:
        import yfinance as yf
        yf_symbol = await self.resolve_symbol(symbol)
        yf_interval = self._map_interval(interval, self.INTERVAL_MAP)

        kwargs = {"interval": yf_interval, "auto_adjust": True, "progress": False}
        if start:
            kwargs["start"] = start
        if end:
            kwargs["end"] = end
        if not start:
            kwargs["period"] = "20y" if yf_interval == "1d" else "60d"

        df = yf.Ticker(yf_symbol).history(**kwargs)
        if df.empty:
            raise ValueError(f"Yahoo returned no data for {symbol} ({yf_symbol})")
        df = df.reset_index().rename(columns={df.index.name or "Date": "timestamp"})
        return self._normalize_df(df)


# ═════════════════════════════════════════════════════════════════════════════
# STOOQ
# ═════════════════════════════════════════════════════════════════════════════

class StooqProvider(DataProvider):
    info = ProviderInfo(
        key="stooq",
        name="Stooq",
        region=ProviderRegion.GLOBAL,
        capabilities=[ProviderCapability.HISTORICAL],
        requires_auth=False,
        auth_type="none",
        supported_intervals=["1d", "1w"],
        max_history_days=10950,
        rate_limit_per_min=None,
        notes="CSV endpoint, no key. Global daily data. CORS-friendly (works from browser). "
              "Symbols like 'aapl.us', '^spx', 'eurusd'.",
    )

    INTERVAL_MAP = {"1d": "d", "1w": "w"}

    INDEX_MAP = {
        "NIFTY": "^nsei", "SENSEX": "^bsesn",
        "SPX": "^spx", "S&P500": "^spx", "NASDAQ": "^ndq", "DOW": "^dji",
    }

    async def resolve_symbol(self, symbol: str) -> str:
        return self.INDEX_MAP.get(symbol.upper().strip(), symbol.lower())

    async def fetch_ohlcv(self, symbol, interval, start=None, end=None) -> pd.DataFrame:
        import httpx
        stooq_symbol = await self.resolve_symbol(symbol)
        stooq_interval = self._map_interval(interval, self.INTERVAL_MAP)
        url = f"https://stooq.com/q/d/l/?s={stooq_symbol}&i={stooq_interval}"

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url)
            r.raise_for_status()
            text = r.text

        if "No data" in text or len(text) < 50:
            raise ValueError(f"Stooq returned no data for {symbol}")
        df = pd.read_csv(io.StringIO(text))
        if start:
            df = df[df["Date"] >= start]
        if end:
            df = df[df["Date"] <= end]
        return self._normalize_df(df)


# ═════════════════════════════════════════════════════════════════════════════
# ALPHA VANTAGE
# ═════════════════════════════════════════════════════════════════════════════

class AlphaVantageProvider(DataProvider):
    info = ProviderInfo(
        key="alpha_vantage",
        name="Alpha Vantage",
        region=ProviderRegion.GLOBAL,
        capabilities=[ProviderCapability.HISTORICAL, ProviderCapability.INTRADAY,
                      ProviderCapability.LIVE_QUOTE],
        requires_auth=True,
        auth_type="api_key",
        supported_intervals=["1m", "5m", "15m", "30m", "1h", "1d", "1w"],
        max_history_days=7300,
        rate_limit_per_min=5,           # free tier: 5/min, 25/day
        notes="Free API key. Global equities + FX + crypto. Free tier is rate-limited.",
    )

    INTERVAL_MAP = {
        "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
        "1h": "60min", "1d": "daily", "1w": "weekly",
    }
    BASE = "https://www.alphavantage.co/query"

    def __init__(self, session=None, api_key: Optional[str] = None):
        super().__init__(session)
        from app.core.config import settings
        self.api_key = api_key or settings.ALPHA_VANTAGE_API_KEY

    async def fetch_ohlcv(self, symbol, interval, start=None, end=None) -> pd.DataFrame:
        import httpx
        av_interval = self._map_interval(interval, self.INTERVAL_MAP)

        if av_interval in ("daily", "weekly"):
            func = "TIME_SERIES_DAILY" if av_interval == "daily" else "TIME_SERIES_WEEKLY"
            params = {"function": func, "symbol": symbol, "outputsize": "full", "apikey": self.api_key}
            key_prefix = "Time Series"
        else:
            params = {"function": "TIME_SERIES_INTRADAY", "symbol": symbol,
                      "interval": av_interval, "outputsize": "full", "apikey": self.api_key}
            key_prefix = "Time Series"

        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(self.BASE, params=params)
            r.raise_for_status()
            data = r.json()

        ts_key = next((k for k in data if key_prefix in k), None)
        if not ts_key:
            raise ValueError(f"Alpha Vantage error for {symbol}: {data.get('Note') or data.get('Information') or 'no data'}")

        rows = []
        for ts, vals in data[ts_key].items():
            rows.append({
                "timestamp": ts,
                "open": vals["1. open"], "high": vals["2. high"],
                "low": vals["3. low"], "close": vals["4. close"],
                "volume": vals.get("5. volume", 0),
            })
        df = pd.DataFrame(rows)
        if start:
            df = df[df["timestamp"] >= start]
        if end:
            df = df[df["timestamp"] <= end]
        return self._normalize_df(df)


# ═════════════════════════════════════════════════════════════════════════════
# TWELVE DATA
# ═════════════════════════════════════════════════════════════════════════════

class TwelveDataProvider(DataProvider):
    info = ProviderInfo(
        key="twelve_data",
        name="Twelve Data",
        region=ProviderRegion.GLOBAL,
        capabilities=[ProviderCapability.HISTORICAL, ProviderCapability.INTRADAY,
                      ProviderCapability.LIVE_QUOTE],
        requires_auth=True,
        auth_type="api_key",
        supported_intervals=["1m", "5m", "15m", "30m", "1h", "1d", "1w"],
        max_history_days=7300,
        rate_limit_per_min=8,
        notes="Free API key. Global equities, FX, crypto, indices. Generous free tier.",
    )

    INTERVAL_MAP = {
        "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
        "1h": "1h", "1d": "1day", "1w": "1week",
    }
    BASE = "https://api.twelvedata.com/time_series"

    def __init__(self, session=None, api_key: Optional[str] = None):
        super().__init__(session)
        from app.core.config import settings
        self.api_key = api_key or settings.TWELVE_DATA_API_KEY

    async def fetch_ohlcv(self, symbol, interval, start=None, end=None) -> pd.DataFrame:
        import httpx
        td_interval = self._map_interval(interval, self.INTERVAL_MAP)
        params = {
            "symbol": symbol, "interval": td_interval,
            "outputsize": "5000", "apikey": self.api_key, "format": "JSON",
        }
        if start:
            params["start_date"] = start
        if end:
            params["end_date"] = end

        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(self.BASE, params=params)
            r.raise_for_status()
            data = r.json()

        if data.get("status") == "error" or "values" not in data:
            raise ValueError(f"Twelve Data error for {symbol}: {data.get('message', 'no data')}")

        df = pd.DataFrame(data["values"]).rename(columns={"datetime": "timestamp"})
        return self._normalize_df(df)


# ═════════════════════════════════════════════════════════════════════════════
# CCXT (CRYPTO)
# ═════════════════════════════════════════════════════════════════════════════

class CCXTProvider(DataProvider):
    info = ProviderInfo(
        key="ccxt",
        name="CCXT (Crypto)",
        region=ProviderRegion.GLOBAL,
        capabilities=[ProviderCapability.HISTORICAL, ProviderCapability.INTRADAY,
                      ProviderCapability.LIVE_QUOTE],
        requires_auth=False,
        auth_type="none",
        supported_intervals=["1m", "5m", "15m", "30m", "1h", "1d", "1w"],
        max_history_days=3650,
        rate_limit_per_min=None,
        notes="100+ crypto exchanges. Public OHLCV needs no key. "
              "Symbols like 'BTC/USDT'. Default exchange: Binance.",
    )

    INTERVAL_MAP = {
        "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1h": "1h", "1d": "1d", "1w": "1w",
    }

    def __init__(self, session=None, exchange: str = "binance"):
        super().__init__(session)
        self.exchange_id = exchange

    async def fetch_ohlcv(self, symbol, interval, start=None, end=None) -> pd.DataFrame:
        import ccxt
        ccxt_interval = self._map_interval(interval, self.INTERVAL_MAP)
        exchange = getattr(ccxt, self.exchange_id)({"enableRateLimit": True})

        since = int(pd.Timestamp(start).timestamp() * 1000) if start else None
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=ccxt_interval, since=since, limit=1000)
        if not ohlcv:
            raise ValueError(f"CCXT returned no data for {symbol}")

        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        if end:
            df = df[df["timestamp"] <= end]
        return self._normalize_df(df)
