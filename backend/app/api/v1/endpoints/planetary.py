from fastapi import APIRouter, Depends
from app.api.v1.endpoints.auth import get_current_user, get_current_pro_user
from app.models.models import User

router = APIRouter()

@router.get("/positions")
async def current_positions(current_user: User = Depends(get_current_user)):
    from app.ml.planetary.engine import PlanetaryCorrelationEngine
    engine = PlanetaryCorrelationEngine()
    return {"positions": engine._get_current_positions()}

@router.get("/upcoming-events")
async def upcoming_events(days: int = 30, current_user: User = Depends(get_current_user)):
    from app.ml.planetary.engine import PlanetaryCorrelationEngine
    engine = PlanetaryCorrelationEngine()
    return {"events": engine._get_upcoming_events(days)}
