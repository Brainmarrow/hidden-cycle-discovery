"""
Market Data endpoints:
POST   /market-data/fetch          — fetch from external source
POST   /market-data/upload         — upload CSV
GET    /market-data                — list user's datasets
GET    /market-data/{id}           — get dataset metadata
DELETE /market-data/{id}           — delete dataset
GET    /market-data/{id}/preview   — first 100 bars
GET    /market-data/{id}/stats     — summary statistics
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.auth import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.models import MarketData, User
from app.tasks.tasks import fetch_market_data
import uuid as uuid_lib

router = APIRouter()


# ── Request / Response schemas ────────────────────────────────────────────────

class FetchRequest(BaseModel):
    symbol: str
    interval: str = "1d"               # 1m | 5m | 15m | 1h | 1d
    source: str = "yfinance"           # yfinance | nsepy | alpha_vantage | twelve_data | ccxt
    start_date: Optional[str] = None   # ISO date string
    end_date: Optional[str] = None
    exchange: Optional[str] = None


class MarketDataResponse(BaseModel):
    id: UUID
    symbol: str
    instrument_type: str
    interval: str
    source: str
    start_date: Optional[str]
    end_date: Optional[str]
    total_bars: Optional[int]
    fetch_status: str
    is_preprocessed: bool

    class Config:
        from_attributes = True


# ── Fetch from external source ────────────────────────────────────────────────

@router.post("/fetch", status_code=202)
async def fetch_data(
    body: FetchRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger async fetch of OHLCV data.
    Returns immediately with job_id; poll GET /market-data/{id} for status.
    """
    # Free plan restriction
    if current_user.plan == "free" and body.interval in ("1m", "5m"):
        raise HTTPException(
            status_code=402,
            detail="Intraday (1m, 5m) data requires Pro plan",
        )

    # Detect instrument type
    instrument_type = _detect_instrument_type(body.symbol, body.source)

    # Create MarketData record
    market_data = MarketData(
        id=uuid_lib.uuid4(),
        user_id=current_user.id,
        symbol=body.symbol.upper(),
        instrument_type=instrument_type,
        exchange=body.exchange,
        interval=body.interval,
        source=body.source,
        start_date=body.start_date,
        end_date=body.end_date,
        fetch_status="pending",
    )
    db.add(market_data)
    await db.commit()
    await db.refresh(market_data)

    # Dispatch Celery task
    task = fetch_market_data.apply_async(
        kwargs={
            "config": {
                "symbol": body.symbol,
                "interval": body.interval,
                "source": body.source,
                "start_date": body.start_date,
                "end_date": body.end_date,
                "market_data_id": str(market_data.id),
                "job_id": str(market_data.id),
            }
        },
        queue="data_fetch",
    )

    return {
        "market_data_id": str(market_data.id),
        "task_id": task.id,
        "status": "pending",
        "message": f"Fetching {body.symbol} data. Poll GET /market-data/{market_data.id} for status.",
    }


# ── Upload CSV ────────────────────────────────────────────────────────────────

@router.post("/upload", status_code=201)
async def upload_csv(
    file: UploadFile = File(...),
    symbol: str = "CUSTOM",
    interval: str = "1d",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a custom OHLCV CSV file.
    Required columns: date/timestamp, open, high, low, close, volume (optional)
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted")

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:  # 50MB limit
        raise HTTPException(status_code=413, detail="File too large (max 50MB)")

    import io
    import pandas as pd

    try:
        df = pd.read_csv(io.BytesIO(content))
        df.columns = [c.lower().strip() for c in df.columns]

        # Detect date column
        date_col = next((c for c in df.columns if "date" in c or "time" in c), None)
        if not date_col:
            raise ValueError("No date/timestamp column found")
        if "close" not in df.columns:
            raise ValueError("No 'close' column found")

        df[date_col] = pd.to_datetime(df[date_col])
        df = df.set_index(date_col).sort_index()

        n_bars = len(df)
        start_date = str(df.index[0])
        end_date = str(df.index[-1])

    except Exception as e:
        raise HTTPException(status_code=422, detail=f"CSV parsing error: {e}")

    # Save to S3 and create record
    from app.services.storage_service import StorageService
    s3_key = f"uploads/{current_user.id}/{uuid_lib.uuid4()}.csv"
    await StorageService.upload_bytes(content, s3_key)

    market_data = MarketData(
        id=uuid_lib.uuid4(),
        user_id=current_user.id,
        symbol=symbol.upper(),
        instrument_type="custom",
        interval=interval,
        source="csv_upload",
        start_date=start_date,
        end_date=end_date,
        total_bars=n_bars,
        s3_key=s3_key,
        fetch_status="ready",
    )
    db.add(market_data)
    await db.commit()
    await db.refresh(market_data)

    return {
        "market_data_id": str(market_data.id),
        "symbol": symbol,
        "n_bars": n_bars,
        "start_date": start_date,
        "end_date": end_date,
        "status": "ready",
    }


# ── List datasets ─────────────────────────────────────────────────────────────

@router.get("", response_model=List[MarketDataResponse])
async def list_market_data(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 50,
):
    result = await db.execute(
        select(MarketData)
        .where(MarketData.user_id == current_user.id)
        .order_by(MarketData.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


# ── Get single dataset ────────────────────────────────────────────────────────

@router.get("/{market_data_id}")
async def get_market_data(
    market_data_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MarketData).where(
            MarketData.id == market_data_id,
            MarketData.user_id == current_user.id,
        )
    )
    md = result.scalar_one_or_none()
    if not md:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return md


# ── Preview (first 100 bars) ──────────────────────────────────────────────────

@router.get("/{market_data_id}/preview")
async def preview_data(
    market_data_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.data_service import DataService
    df = await DataService.load_dataframe(str(market_data_id))
    if df is None:
        raise HTTPException(status_code=404, detail="Data not found")

    preview = df.head(100)
    return {
        "columns": list(preview.columns),
        "data": preview.reset_index().to_dict(orient="records"),
        "total_bars": len(df),
        "start": str(df.index[0]),
        "end": str(df.index[-1]),
    }


# ── Statistics ────────────────────────────────────────────────────────────────

@router.get("/{market_data_id}/stats")
async def data_stats(
    market_data_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.data_service import DataService
    import numpy as np

    df = await DataService.load_dataframe(str(market_data_id))
    if df is None:
        raise HTTPException(status_code=404, detail="Data not found")

    close = df["close"]
    log_ret = np.log(close / close.shift(1)).dropna()

    return {
        "n_bars": len(df),
        "start": str(df.index[0]),
        "end": str(df.index[-1]),
        "price_min": float(close.min()),
        "price_max": float(close.max()),
        "price_mean": float(close.mean()),
        "total_return": float((close.iloc[-1] / close.iloc[0]) - 1),
        "annualized_vol": float(log_ret.std() * np.sqrt(252)),
        "annualized_return": float(log_ret.mean() * 252),
        "sharpe": float((log_ret.mean() * 252) / (log_ret.std() * np.sqrt(252) + 1e-10)),
        "max_drawdown": float(_max_drawdown(close)),
        "skewness": float(log_ret.skew()),
        "kurtosis": float(log_ret.kurt()),
    }


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete("/{market_data_id}", status_code=204)
async def delete_market_data(
    market_data_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MarketData).where(
            MarketData.id == market_data_id,
            MarketData.user_id == current_user.id,
        )
    )
    md = result.scalar_one_or_none()
    if not md:
        raise HTTPException(status_code=404, detail="Dataset not found")

    await db.delete(md)
    await db.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _detect_instrument_type(symbol: str, source: str) -> str:
    symbol_upper = symbol.upper()
    if source == "ccxt" or any(x in symbol_upper for x in ["BTC", "ETH", "USDT", "BNB"]):
        return "crypto"
    if any(x in symbol_upper for x in ["USD", "EUR", "GBP", "JPY", "FOREX"]):
        return "forex"
    if any(x in symbol_upper for x in ["GOLD", "SILVER", "OIL", "CRUDE", "XAU", "XAG"]):
        return "commodity"
    if symbol_upper in ("^NSEI", "^BSESN", "^NSEBANK", "NIFTY", "BANKNIFTY"):
        return "index"
    return "stock"


def _max_drawdown(prices) -> float:
    import numpy as np
    roll_max = prices.cummax()
    drawdown = (prices - roll_max) / roll_max
    return float(drawdown.min())
