from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.endpoints.auth import get_current_user
from app.db.session import get_db
from app.models.models import FeatureSet, User
from uuid import UUID

router = APIRouter()

@router.get("/{market_data_id}/importance")
async def feature_importance(market_data_id: UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FeatureSet).where(FeatureSet.market_data_id == market_data_id).order_by(FeatureSet.created_at.desc()).limit(1))
    fs = result.scalar_one_or_none()
    if not fs:
        return {"message": "No feature data found. Run analysis first."}
    return {"feature_count": fs.feature_count, "importance_scores": fs.importance_scores, "top_features": list((fs.importance_scores or {}).keys())[:20]}
