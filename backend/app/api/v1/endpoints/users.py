from fastapi import APIRouter, Depends
from app.api.v1.endpoints.auth import get_current_user
from app.models.models import User

router = APIRouter()

@router.get("/me")
async def get_profile(current_user: User = Depends(get_current_user)):
    return {"id": str(current_user.id), "email": current_user.email, "full_name": current_user.full_name, "plan": current_user.plan, "is_verified": current_user.is_verified, "api_key": current_user.api_key}
