from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.api.v1.endpoints.auth import get_current_pro_user
from app.models.models import User
from app.tasks.tasks import train_ai_model
import uuid

router = APIRouter()

class TrainRequest(BaseModel):
    market_data_id: str
    model_type: str = "autoencoder"
    n_epochs: int = 100

@router.post("/train", status_code=202)
async def train_model(body: TrainRequest, current_user: User = Depends(get_current_pro_user)):
    job_id = str(uuid.uuid4())
    task = train_ai_model.apply_async(kwargs={"config": {"market_data_id": body.market_data_id, "model_type": body.model_type, "n_epochs": body.n_epochs, "job_id": job_id}}, queue="ml_training")
    return {"job_id": job_id, "task_id": task.id, "model_type": body.model_type}
