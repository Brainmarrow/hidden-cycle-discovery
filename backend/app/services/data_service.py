"""
DataService — handles loading/saving market data and job state.
Supports: yfinance, NSE, Alpha Vantage, Twelve Data, CCXT, CSV uploads.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class DataService:
    """All market data I/O operations."""

    # ── Fetch from external source ────────────────────────────────────────────

    @staticmethod
    async def fetch(
        symbol: str,
        interval: str = "1d",
        source: str = "yfinance",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data from the specified source.
        Returns normalized DataFrame with columns: open, high, low, close, volume.
        """
        if source == "yfinance":
            return await DataService._fetch_yfinance(symbol, interval, start_date, end_date)
        elif source == "nsepy":
            return await DataService._fetch_nse(symbol, interval, start_date, end_date)
        elif source == "alpha_vantage":
            return await DataService._fetch_alpha_vantage(symbol, interval, start_date, end_date)
        elif source == "twelve_data":
            return await DataService._fetch_twelve_data(symbol, interval, start_date, end_date)
        elif source == "ccxt":
            return await DataService._fetch_ccxt(symbol, interval, start_date, end_date)
        else:
            raise ValueError(f"Unknown data source: {source}")

    @staticmethod
    async def _fetch_yfinance(symbol: str, interval: str, start: Optional[str], end: Optional[str]) -> pd.DataFrame:
        import yfinance as yf

        # Map interval
        interval_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "60m", "1d": "1d"}
        yf_interval = interval_map.get(interval, "1d")

        ticker = yf.Ticker(symbol)

        kwargs = {"interval": yf_interval, "auto_adjust": True, "progress": False}
        if start:
            kwargs["start"] = start
        if end:
            kwargs["end"] = end
        elif not start:
            # Default: 5 years for daily, 60 days for intraday
            if yf_interval == "1d":
                kwargs["period"] = "20y"
            else:
                kwargs["period"] = "60d"

        df = ticker.history(**kwargs)
        if df.empty:
            raise ValueError(f"No data returned for {symbol}")

        df.columns = [c.lower() for c in df.columns]
        df = df[["open", "high", "low", "close", "volume"]].copy()
        df.index = pd.to_datetime(df.index, utc=True).tz_convert(None)
        df = df[df["close"] > 0].dropna(subset=["close"])

        logger.info(f"yfinance: fetched {len(df)} bars for {symbol} @ {interval}")
        return df

    @staticmethod
    async def _fetch_nse(symbol: str, interval: str, start: Optional[str], end: Optional[str]) -> pd.DataFrame:
        """Fetch Indian NSE data via nsepy or yfinance fallback."""
        # Map NSE symbols to yfinance format
        symbol_map = {
            "NIFTY": "^NSEI",
            "BANKNIFTY": "^NSEBANK",
            "SENSEX": "^BSESN",
        }
        yf_symbol = symbol_map.get(symbol.upper(), f"{symbol}.NS")
        return await DataService._fetch_yfinance(yf_symbol, interval, start, end)

    @staticmethod
    async def _fetch_alpha_vantage(symbol: str, interval: str, start: Optional[str], end: Optional[str]) -> pd.DataFrame:
        from alpha_vantage.timeseries import TimeSeries
        from app.core.config import settings

        ts = TimeSeries(key=settings.ALPHA_VANTAGE_API_KEY, output_format="pandas")
        interval_map = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "60min", "1d": "daily"}
        av_interval = interval_map.get(interval, "daily")

        if av_interval == "daily":
            data, _ = ts.get_daily_adjusted(symbol=symbol, outputsize="full")
        else:
            data, _ = ts.get_intraday(symbol=symbol, interval=av_interval, outputsize="full")

        data.columns = ["open", "high", "low", "close", "volume"] + list(data.columns[5:])
        data = data[["open", "high", "low", "close", "volume"]].sort_index()
        data.index = pd.to_datetime(data.index)

        if start:
            data = data[data.index >= start]
        if end:
            data = data[data.index <= end]

        return data.astype(float)

    @staticmethod
    async def _fetch_twelve_data(symbol: str, interval: str, start: Optional[str], end: Optional[str]) -> pd.DataFrame:
        from twelvedata import TDClient
        from app.core.config import settings

        td = TDClient(apikey=settings.TWELVE_DATA_API_KEY)
        interval_map = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h", "1d": "1day"}

        ts = td.time_series(
            symbol=symbol,
            interval=interval_map.get(interval, "1day"),
            start_date=start,
            end_date=end,
            outputsize=5000,
        )
        df = ts.as_pandas()
        df.index = pd.to_datetime(df.index)
        df.columns = [c.lower() for c in df.columns]
        return df[["open", "high", "low", "close", "volume"]].sort_index().astype(float)

    @staticmethod
    async def _fetch_ccxt(symbol: str, interval: str, start: Optional[str], end: Optional[str]) -> pd.DataFrame:
        """Fetch crypto OHLCV via CCXT (supports 100+ exchanges)."""
        import ccxt

        # Default to Binance for crypto
        exchange = ccxt.binance({"enableRateLimit": True})
        interval_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "1d": "1d"}
        tf = interval_map.get(interval, "1d")

        since = None
        if start:
            since = int(pd.Timestamp(start).timestamp() * 1000)

        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=tf, since=since, limit=1000)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df.set_index("timestamp")

        if end:
            df = df[df.index <= end]

        return df.astype(float)

    # ── Save / Load ───────────────────────────────────────────────────────────

    @staticmethod
    async def save_bars(market_data_id: str, df: pd.DataFrame) -> None:
        """Save OHLCV bars to S3 as Parquet + update DB record."""
        from app.services.storage_service import StorageService
        from app.db.session import async_session_factory
        from app.models.models import MarketData
        from sqlalchemy import select

        s3_key = f"market_data/{market_data_id}/ohlcv.parquet"
        parquet_bytes = df.to_parquet(index=True)
        await StorageService.upload_bytes(parquet_bytes, s3_key)

        async with async_session_factory() as db:
            result = await db.execute(select(MarketData).where(MarketData.id == market_data_id))
            md = result.scalar_one_or_none()
            if md:
                md.s3_key = s3_key
                md.total_bars = len(df)
                md.start_date = df.index[0] if len(df) > 0 else None
                md.end_date = df.index[-1] if len(df) > 0 else None
                md.fetch_status = "ready"
                await db.commit()

    @staticmethod
    async def load_dataframe(market_data_id: str) -> Optional[pd.DataFrame]:
        """Load OHLCV DataFrame from S3 Parquet."""
        from app.db.session import async_session_factory
        from app.models.models import MarketData
        from sqlalchemy import select
        from app.services.storage_service import StorageService

        async with async_session_factory() as db:
            result = await db.execute(select(MarketData).where(MarketData.id == market_data_id))
            md = result.scalar_one_or_none()

        if not md or not md.s3_key:
            return None

        try:
            parquet_bytes = await StorageService.download_bytes(md.s3_key)
            df = pd.read_parquet(io.BytesIO(parquet_bytes))
            df.columns = [c.lower() for c in df.columns]
            return df
        except Exception as e:
            logger.error(f"Failed to load market data {market_data_id}: {e}")
            return None

    @staticmethod
    async def save_cycles(market_data_id: str, job_id: str, cycle_result) -> None:
        """Persist CycleDetectionResult to database."""
        from app.db.session import async_session_factory
        from app.models.models import CycleResult as CycleResultModel

        async with async_session_factory() as db:
            for candidate in cycle_result.dominant[:30]:
                cycle = CycleResultModel(
                    market_data_id=market_data_id,
                    job_id=job_id,
                    method=candidate.method.split("[")[0],  # strip consensus suffix
                    period_bars=candidate.period_bars,
                    period_calendar=candidate.period_calendar,
                    frequency=candidate.frequency,
                    amplitude=candidate.amplitude,
                    power=candidate.power,
                    phase=candidate.phase,
                    strength=candidate.strength,
                    confidence=candidate.confidence,
                    frequencies_json=candidate.all_frequencies.tolist() if candidate.all_frequencies is not None else None,
                    powers_json=candidate.all_powers.tolist() if candidate.all_powers is not None else None,
                    next_turning_point_bars=candidate.next_turning_point_bars,
                    turning_point_type=candidate.turning_point_type,
                )
                db.add(cycle)
            await db.commit()

    @staticmethod
    async def update_job_status(job_id: str, status: str, result: Optional[dict] = None) -> None:
        """Update ResearchJob status and result in DB."""
        from app.db.session import async_session_factory
        from app.models.models import ResearchJob
        from sqlalchemy import select

        async with async_session_factory() as db:
            res = await db.execute(select(ResearchJob).where(ResearchJob.id == job_id))
            job = res.scalar_one_or_none()
            if job:
                job.status = status
                job.completed_at = datetime.utcnow()
                if result:
                    job.result_summary = result
                await db.commit()
