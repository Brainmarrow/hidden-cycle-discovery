"""
INDIAN BROKER ADAPTERS
=======================
Each adapter wraps one broker's REST API behind the common DataProvider interface.

Verified against current (2025) API behavior:
  • Zerodha Kite Connect  — paid plan (₹500/mo) bundles historical+live data.
                            Auth: api_key/secret → request_token → access_token (daily).
  • Upstox v3             — OAuth2 Bearer. Instrument keys like "NSE_EQ|INE..." or "NSE_INDEX|Nifty 50".
                            Historical candle endpoint: /v3/historical-candle.
  • Angel One SmartAPI    — TOTP login → JWT. getCandleData with symboltokens.
  • Dhan                  — Static long-lived access token + security IDs.
  • Fyers                 — OAuth2 auth-code → access token. symbol like "NSE:SBIN-EQ".

Auth flows that need a browser redirect (Zerodha/Upstox/Fyers) are completed via the
session endpoints in app/api/v1/endpoints/providers.py — these adapters assume a valid
AuthSession is already present.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List

import httpx
import pandas as pd

from app.providers.base import (
    DataProvider, ProviderInfo, ProviderRegion, ProviderCapability, AuthSession,
)

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# ZERODHA KITE CONNECT
# ═════════════════════════════════════════════════════════════════════════════

class ZerodhaProvider(DataProvider):
    info = ProviderInfo(
        key="zerodha",
        name="Zerodha Kite Connect",
        region=ProviderRegion.INDIA,
        capabilities=[ProviderCapability.HISTORICAL, ProviderCapability.LIVE_QUOTE,
                      ProviderCapability.STREAMING, ProviderCapability.INTRADAY,
                      ProviderCapability.OPTIONS, ProviderCapability.PLACE_ORDER],
        requires_auth=True,
        auth_type="oauth_request_token",
        supported_intervals=["1m", "3m", "5m", "15m", "30m", "1h", "1d"],
        max_history_days=3650,          # up to 10 years on paid plan
        rate_limit_per_min=180,         # ~3 req/sec historical
        notes="Paid Connect plan (₹500/mo) includes historical + live data. "
              "Access token expires daily; re-login each morning.",
    )

    INTERVAL_MAP = {
        "1m": "minute", "3m": "3minute", "5m": "5minute",
        "15m": "15minute", "30m": "30minute", "1h": "60minute", "1d": "day",
    }
    BASE = "https://api.kite.trade"

    async def resolve_symbol(self, symbol: str) -> str:
        """
        Zerodha needs an instrument_token (numeric). We resolve via the
        instruments dump. For common indices we hardcode known tokens.
        """
        known = {
            "NIFTY": "256265", "NIFTY 50": "256265",
            "BANKNIFTY": "260105", "NIFTY BANK": "260105",
            "FINNIFTY": "257801", "SENSEX": "265",
        }
        up = symbol.upper().strip()
        if up in known:
            return known[up]
        # Otherwise look up via instruments CSV (cached in production)
        token = await self._lookup_instrument_token(symbol)
        return token or symbol

    async def _lookup_instrument_token(self, symbol: str) -> Optional[str]:
        """Download & search the instruments master (cache this in Redis in prod)."""
        headers = self._auth_headers()
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{self.BASE}/instruments", headers=headers)
            if r.status_code != 200:
                return None
            df = pd.read_csv(pd.io.common.StringIO(r.text))
            match = df[df["tradingsymbol"].str.upper() == symbol.upper()]
            if len(match):
                return str(match.iloc[0]["instrument_token"])
        return None

    def _auth_headers(self) -> Dict[str, str]:
        if not self.session or not self.session.access_token:
            raise ValueError("Zerodha requires an authenticated session")
        return {
            "X-Kite-Version": "3",
            "Authorization": f"token {self.session.api_key}:{self.session.access_token}",
        }

    async def fetch_ohlcv(self, symbol, interval, start=None, end=None) -> pd.DataFrame:
        token = await self.resolve_symbol(symbol)
        kite_interval = self._map_interval(interval, self.INTERVAL_MAP)

        end = end or datetime.utcnow().strftime("%Y-%m-%d")
        start = start or (datetime.utcnow() - timedelta(days=self.info.max_history_days)).strftime("%Y-%m-%d")

        url = f"{self.BASE}/instruments/historical/{token}/{kite_interval}"
        params = {"from": start, "to": end, "continuous": 0, "oi": 0}

        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(url, headers=self._auth_headers(), params=params)
            r.raise_for_status()
            data = r.json()

        candles = data.get("data", {}).get("candles", [])
        if not candles:
            raise ValueError(f"Zerodha returned no candles for {symbol}")

        df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume", "oi"][:len(candles[0])])
        return self._normalize_df(df)

    async def get_live_quote(self, symbol: str) -> Optional[Dict]:
        token = await self.resolve_symbol(symbol)
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{self.BASE}/quote/ltp",
                                  headers=self._auth_headers(),
                                  params={"i": f"NSE:{symbol}"})
            r.raise_for_status()
            return r.json().get("data", {})


# ═════════════════════════════════════════════════════════════════════════════
# UPSTOX
# ═════════════════════════════════════════════════════════════════════════════

class UpstoxProvider(DataProvider):
    info = ProviderInfo(
        key="upstox",
        name="Upstox API v3",
        region=ProviderRegion.INDIA,
        capabilities=[ProviderCapability.HISTORICAL, ProviderCapability.LIVE_QUOTE,
                      ProviderCapability.STREAMING, ProviderCapability.INTRADAY,
                      ProviderCapability.OPTIONS, ProviderCapability.PLACE_ORDER],
        requires_auth=True,
        auth_type="oauth_bearer",
        supported_intervals=["1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w"],
        max_history_days=3650,
        rate_limit_per_min=250,
        notes="OAuth2 Bearer token. Instrument keys like 'NSE_EQ|INE...' or "
              "'NSE_INDEX|Nifty 50'. v3 candle endpoint supports flexible intervals.",
    )

    # v3 uses unit + interval pairs: minutes/1, minutes/5, days/1, weeks/1
    INTERVAL_MAP = {
        "1m": ("minutes", "1"), "3m": ("minutes", "3"), "5m": ("minutes", "5"),
        "15m": ("minutes", "15"), "30m": ("minutes", "30"), "1h": ("hours", "1"),
        "1d": ("days", "1"), "1w": ("weeks", "1"),
    }
    BASE = "https://api.upstox.com/v3"

    INDEX_KEYS = {
        "NIFTY": "NSE_INDEX|Nifty 50", "NIFTY 50": "NSE_INDEX|Nifty 50",
        "BANKNIFTY": "NSE_INDEX|Nifty Bank", "NIFTY BANK": "NSE_INDEX|Nifty Bank",
        "FINNIFTY": "NSE_INDEX|Nifty Fin Service", "SENSEX": "BSE_INDEX|SENSEX",
    }

    async def resolve_symbol(self, symbol: str) -> str:
        up = symbol.upper().strip()
        if up in self.INDEX_KEYS:
            return self.INDEX_KEYS[up]
        if "|" in symbol:            # already an instrument key
            return symbol
        # For equities the caller should pass the instrument_key; we default to NSE_EQ
        return f"NSE_EQ|{symbol}"

    def _auth_headers(self) -> Dict[str, str]:
        if not self.session or not self.session.access_token:
            raise ValueError("Upstox requires an authenticated session")
        return {
            "Authorization": f"Bearer {self.session.access_token}",
            "Accept": "application/json",
        }

    async def fetch_ohlcv(self, symbol, interval, start=None, end=None) -> pd.DataFrame:
        instrument_key = await self.resolve_symbol(symbol)
        unit, mult = self._map_interval(interval, self.INTERVAL_MAP)

        end = end or datetime.utcnow().strftime("%Y-%m-%d")
        start = start or (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%d")

        # v3: /historical-candle/{instrument_key}/{unit}/{interval}/{to}/{from}
        from urllib.parse import quote
        ik = quote(instrument_key, safe="")
        url = f"{self.BASE}/historical-candle/{ik}/{unit}/{mult}/{end}/{start}"

        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(url, headers=self._auth_headers())
            r.raise_for_status()
            data = r.json()

        candles = data.get("data", {}).get("candles", [])
        if not candles:
            raise ValueError(f"Upstox returned no candles for {symbol}")

        # Each candle: [timestamp, open, high, low, close, volume, oi]
        df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume", "oi"][:len(candles[0])])
        return self._normalize_df(df)


# ═════════════════════════════════════════════════════════════════════════════
# ANGEL ONE SMARTAPI
# ═════════════════════════════════════════════════════════════════════════════

class AngelOneProvider(DataProvider):
    info = ProviderInfo(
        key="angelone",
        name="Angel One SmartAPI",
        region=ProviderRegion.INDIA,
        capabilities=[ProviderCapability.HISTORICAL, ProviderCapability.LIVE_QUOTE,
                      ProviderCapability.STREAMING, ProviderCapability.INTRADAY,
                      ProviderCapability.OPTIONS, ProviderCapability.PLACE_ORDER],
        requires_auth=True,
        auth_type="totp_jwt",
        supported_intervals=["1m", "3m", "5m", "15m", "30m", "1h", "1d"],
        max_history_days=3650,
        rate_limit_per_min=180,
        notes="TOTP-based login returns a JWT. Uses numeric symboltokens. "
              "Generous historical limits; popular for beginners.",
    )

    INTERVAL_MAP = {
        "1m": "ONE_MINUTE", "3m": "THREE_MINUTE", "5m": "FIVE_MINUTE",
        "15m": "FIFTEEN_MINUTE", "30m": "THIRTY_MINUTE", "1h": "ONE_HOUR", "1d": "ONE_DAY",
    }
    BASE = "https://apiconnect.angelone.in"

    INDEX_TOKENS = {
        "NIFTY": "99926000", "NIFTY 50": "99926000",
        "BANKNIFTY": "99926009", "NIFTY BANK": "99926009",
        "FINNIFTY": "99926037",
    }

    async def resolve_symbol(self, symbol: str) -> str:
        up = symbol.upper().strip()
        return self.INDEX_TOKENS.get(up, symbol)

    def _auth_headers(self) -> Dict[str, str]:
        if not self.session or not self.session.access_token:
            raise ValueError("Angel One requires an authenticated session")
        return {
            "Authorization": f"Bearer {self.session.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "X-PrivateKey": self.session.api_key or "",
            "X-ClientLocalIP": self.session.extras.get("local_ip", "127.0.0.1"),
            "X-ClientPublicIP": self.session.extras.get("public_ip", "127.0.0.1"),
            "X-MACAddress": self.session.extras.get("mac", "00:00:00:00:00:00"),
        }

    async def fetch_ohlcv(self, symbol, interval, start=None, end=None) -> pd.DataFrame:
        token = await self.resolve_symbol(symbol)
        ang_interval = self._map_interval(interval, self.INTERVAL_MAP)
        exchange = self.session.extras.get("exchange", "NSE") if self.session else "NSE"

        # Angel One expects "YYYY-MM-DD HH:MM"
        end_dt = end or datetime.utcnow().strftime("%Y-%m-%d %H:%M")
        start_dt = start or (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%d %H:%M")
        if len(end_dt) == 10:
            end_dt += " 15:30"
        if len(start_dt) == 10:
            start_dt += " 09:15"

        url = f"{self.BASE}/rest/secure/angelbroking/historical/v1/getCandleData"
        payload = {
            "exchange": exchange,
            "symboltoken": token,
            "interval": ang_interval,
            "fromdate": start_dt,
            "todate": end_dt,
        }

        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, headers=self._auth_headers(), json=payload)
            r.raise_for_status()
            data = r.json()

        candles = data.get("data", [])
        if not candles:
            raise ValueError(f"Angel One returned no candles for {symbol}: {data.get('message')}")

        df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
        return self._normalize_df(df)


# ═════════════════════════════════════════════════════════════════════════════
# DHAN
# ═════════════════════════════════════════════════════════════════════════════

class DhanProvider(DataProvider):
    info = ProviderInfo(
        key="dhan",
        name="Dhan API",
        region=ProviderRegion.INDIA,
        capabilities=[ProviderCapability.HISTORICAL, ProviderCapability.LIVE_QUOTE,
                      ProviderCapability.STREAMING, ProviderCapability.INTRADAY,
                      ProviderCapability.OPTIONS, ProviderCapability.PLACE_ORDER],
        requires_auth=True,
        auth_type="static_token",
        supported_intervals=["1m", "5m", "15m", "25m", "1h", "1d"],
        max_history_days=3650,
        rate_limit_per_min=None,
        notes="Long-lived access token (no daily re-login). Uses numeric securityId. "
              "High order rate limits.",
    )

    BASE = "https://api.dhan.co/v2"
    # Dhan intraday uses minute granularity ints; daily uses a separate endpoint
    INTRADAY_MINUTES = {"1m": "1", "5m": "5", "15m": "15", "25m": "25", "1h": "60"}

    async def resolve_symbol(self, symbol: str) -> str:
        # Caller passes the numeric securityId; indices have known IDs
        known = {"NIFTY": "13", "BANKNIFTY": "25", "FINNIFTY": "27"}
        return known.get(symbol.upper().strip(), symbol)

    def _auth_headers(self) -> Dict[str, str]:
        if not self.session or not self.session.access_token:
            raise ValueError("Dhan requires an access token")
        return {
            "access-token": self.session.access_token,
            "client-id": self.session.user_id or "",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def fetch_ohlcv(self, symbol, interval, start=None, end=None) -> pd.DataFrame:
        security_id = await self.resolve_symbol(symbol)
        exchange_segment = self.session.extras.get("exchange_segment", "NSE_EQ") if self.session else "NSE_EQ"

        end = end or datetime.utcnow().strftime("%Y-%m-%d")
        start = start or (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%d")

        if interval == "1d":
            url = f"{self.BASE}/charts/historical"
            payload = {
                "securityId": security_id,
                "exchangeSegment": exchange_segment,
                "instrument": self.session.extras.get("instrument", "EQUITY"),
                "fromDate": start, "toDate": end,
            }
        else:
            url = f"{self.BASE}/charts/intraday"
            payload = {
                "securityId": security_id,
                "exchangeSegment": exchange_segment,
                "instrument": self.session.extras.get("instrument", "EQUITY"),
                "interval": self.INTRADAY_MINUTES.get(interval, "5"),
                "fromDate": start, "toDate": end,
            }

        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, headers=self._auth_headers(), json=payload)
            r.raise_for_status()
            data = r.json()

        # Dhan returns parallel arrays: {open:[], high:[], low:[], close:[], volume:[], timestamp:[]}
        if not data.get("close"):
            raise ValueError(f"Dhan returned no candles for {symbol}")

        df = pd.DataFrame({
            "timestamp": pd.to_datetime(data.get("timestamp", []), unit="s"),
            "open": data["open"], "high": data["high"],
            "low": data["low"], "close": data["close"],
            "volume": data.get("volume", [0] * len(data["close"])),
        })
        return self._normalize_df(df)


# ═════════════════════════════════════════════════════════════════════════════
# FYERS
# ═════════════════════════════════════════════════════════════════════════════

class FyersProvider(DataProvider):
    info = ProviderInfo(
        key="fyers",
        name="Fyers API v3",
        region=ProviderRegion.INDIA,
        capabilities=[ProviderCapability.HISTORICAL, ProviderCapability.LIVE_QUOTE,
                      ProviderCapability.STREAMING, ProviderCapability.INTRADAY,
                      ProviderCapability.OPTIONS, ProviderCapability.PLACE_ORDER],
        requires_auth=True,
        auth_type="oauth_bearer",
        supported_intervals=["1m", "5m", "15m", "30m", "1h", "1d"],
        max_history_days=3650,
        rate_limit_per_min=200,
        notes="OAuth2 auth-code flow. Symbols like 'NSE:SBIN-EQ', 'NSE:NIFTY50-INDEX'.",
    )

    INTERVAL_MAP = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "1d": "D"}
    BASE = "https://api-t1.fyers.in/data"

    INDEX_SYMBOLS = {
        "NIFTY": "NSE:NIFTY50-INDEX", "NIFTY 50": "NSE:NIFTY50-INDEX",
        "BANKNIFTY": "NSE:NIFTYBANK-INDEX", "NIFTY BANK": "NSE:NIFTYBANK-INDEX",
        "FINNIFTY": "NSE:FINNIFTY-INDEX",
    }

    async def resolve_symbol(self, symbol: str) -> str:
        up = symbol.upper().strip()
        if up in self.INDEX_SYMBOLS:
            return self.INDEX_SYMBOLS[up]
        if ":" in symbol:
            return symbol
        return f"NSE:{symbol}-EQ"

    def _auth_headers(self) -> Dict[str, str]:
        if not self.session or not self.session.access_token:
            raise ValueError("Fyers requires an authenticated session")
        return {"Authorization": f"{self.session.api_key}:{self.session.access_token}"}

    async def fetch_ohlcv(self, symbol, interval, start=None, end=None) -> pd.DataFrame:
        fy_symbol = await self.resolve_symbol(symbol)
        resolution = self._map_interval(interval, self.INTERVAL_MAP)

        end = end or datetime.utcnow().strftime("%Y-%m-%d")
        start = start or (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%d")

        params = {
            "symbol": fy_symbol, "resolution": resolution, "date_format": "1",
            "range_from": start, "range_to": end, "cont_flag": "1",
        }
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(f"{self.BASE}/history", headers=self._auth_headers(), params=params)
            r.raise_for_status()
            data = r.json()

        candles = data.get("candles", [])
        if not candles:
            raise ValueError(f"Fyers returned no candles for {symbol}")

        df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
        return self._normalize_df(df)
