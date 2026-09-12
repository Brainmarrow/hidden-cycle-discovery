"""cycles.py — Cycle result endpoints"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.endpoints.auth import get_current_user
from app.db.session import get_db
from app.models.models import CycleResult, User
from uuid import UUID

router = APIRouter()

@router.get("/{market_data_id}")
async def get_cycles(
    market_data_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    top_n: int = 20,
    min_strength: float = 0.0,
):
    """Return detected cycles for a market dataset, sorted by strength."""
    result = await db.execute(
        select(CycleResult)
        .where(CycleResult.market_data_id == market_data_id)
        .where(CycleResult.strength >= min_strength)
        .order_by(CycleResult.strength.desc())
        .limit(top_n)
    )
    cycles = result.scalars().all()
    return {
        "market_data_id": str(market_data_id),
        "count": len(cycles),
        "cycles": [
            {
                "id": str(c.id),
                "method": c.method,
                "period_bars": c.period_bars,
                "period_calendar": c.period_calendar,
                "frequency": c.frequency,
                "amplitude": c.amplitude,
                "power": c.power,
                "strength": c.strength,
                "confidence": c.confidence,
                "is_stable": c.is_stable,
                "stability_score": c.stability_score,
                "next_turning_point": str(c.next_turning_point) if c.next_turning_point else None,
                "turning_point_type": c.turning_point_type,
                "created_at": str(c.created_at),
            }
            for c in cycles
        ],
    }


@router.get("/{market_data_id}/dominant")
async def get_dominant_cycles(
    market_data_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the single strongest cycle per unique period bucket."""
    result = await db.execute(
        select(CycleResult)
        .where(CycleResult.market_data_id == market_data_id)
        .order_by(CycleResult.strength.desc())
        .limit(5)
    )
    cycles = result.scalars().all()
    return {"dominant_cycles": [{"period_bars": c.period_bars, "strength": c.strength, "method": c.method} for c in cycles]}


@router.get("/{market_data_id}/heatmap")
async def get_cycle_heatmap(
    market_data_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return frequency-vs-time heatmap data for spectrograms."""
    result = await db.execute(
        select(CycleResult)
        .where(CycleResult.market_data_id == market_data_id)
        .where(CycleResult.frequencies_json.isnot(None))
        .limit(1)
    )
    cycle = result.scalar_one_or_none()
    if not cycle:
        raise HTTPException(404, "No spectral data found")
    return {
        "frequencies": cycle.frequencies_json,
        "powers": cycle.powers_json,
    }
