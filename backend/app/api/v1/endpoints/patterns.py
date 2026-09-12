from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.endpoints.auth import get_current_user
from app.db.session import get_db
from app.models.models import PatternResult, User
from uuid import UUID

router = APIRouter()

@router.get("/{market_data_id}")
async def get_patterns(market_data_id: UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PatternResult).where(PatternResult.market_data_id == market_data_id).limit(50))
    patterns = result.scalars().all()
    return {"patterns": [{"id": str(p.id), "pattern_type": p.pattern_type, "occurrence_count": p.occurrence_count, "hit_rate": p.hit_rate, "sharpe_like": p.sharpe_like, "mean_forward_return": p.mean_forward_return} for p in patterns]}
