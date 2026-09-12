from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.endpoints.auth import get_current_user, get_current_pro_user
from app.db.session import get_db
from app.models.models import AnalogResult, User
from uuid import UUID

router = APIRouter()

@router.get("/{market_data_id}")
async def get_analogs(market_data_id: UUID, current_user: User = Depends(get_current_pro_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AnalogResult).where(AnalogResult.market_data_id == market_data_id).order_by(AnalogResult.created_at.desc()).limit(1))
    analog = result.scalar_one_or_none()
    if not analog:
        return {"analogs": [], "message": "No analog results found. Run analysis first."}
    return {"top_analogs": analog.top_analogs, "composite_projection": analog.composite_projection}
