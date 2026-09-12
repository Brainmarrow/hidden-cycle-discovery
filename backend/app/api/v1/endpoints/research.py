"""
Research endpoints — orchestrate full analysis pipeline.

POST /research/analyze          — run full analysis on a dataset
POST /research/query            — natural language research query
GET  /research/jobs             — list analysis jobs
GET  /research/jobs/{id}        — job status + progress
DELETE /research/jobs/{id}      — cancel job
GET  /research/jobs/{id}/result — full result payload
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.auth import get_current_user, get_current_pro_user
from app.db.session import get_db
from app.models.models import ResearchJob, MarketData, User
from app.tasks.tasks import (
    run_full_analysis,
    run_cycle_detection,
    run_analog_search,
    train_ai_model,
)
from app.core.config import settings
import uuid as uuid_lib

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    market_data_id: str
    modules: Optional[List[str]] = None   # None = auto-select based on plan
    model_type: Optional[str] = "autoencoder"
    lookback_bars: int = 60
    # Cycle detection options
    min_period_bars: int = 3
    max_period_bars: Optional[int] = None


class QueryRequest(BaseModel):
    market_data_id: str
    query: str    # e.g. "Find dominant cycles", "What is the strongest periodicity?"


class JobResponse(BaseModel):
    id: uuid_lib.UUID
    job_type: str
    status: str
    progress: float
    progress_message: Optional[str]
    celery_task_id: Optional[str]
    queued_at: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    duration_seconds: Optional[float]

    class Config:
        from_attributes = True


# ── Full Analysis ─────────────────────────────────────────────────────────────

@router.post("/analyze", status_code=202)
async def run_analysis(
    body: AnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger a full analysis pipeline.
    Free plan: cycle detection only.
    Pro/Enterprise: all modules.
    """
    # Verify market data belongs to user
    result = await db.execute(
        select(MarketData).where(
            MarketData.id == body.market_data_id,
            MarketData.user_id == current_user.id,
        )
    )
    md = result.scalar_one_or_none()
    if not md:
        raise HTTPException(status_code=404, detail="Market data not found")

    if md.fetch_status != "ready":
        raise HTTPException(status_code=400, detail=f"Data not ready (status={md.fetch_status})")

    # Determine enabled modules by plan
    if current_user.plan == "free":
        modules = ["preprocessing", "cycle_detection"]
    elif current_user.plan == "pro":
        modules = body.modules or [
            "preprocessing", "cycle_detection", "pattern_discovery",
            "features", "stability", "analog", "planetary",
        ]
    else:  # enterprise
        modules = body.modules or [
            "preprocessing", "cycle_detection", "pattern_discovery",
            "features", "stability", "analog", "planetary", "ai_model",
        ]

    # Create job record
    job = ResearchJob(
        id=uuid_lib.uuid4(),
        user_id=current_user.id,
        market_data_id=body.market_data_id,
        job_type="full_analysis",
        status="queued",
        config={
            "modules": modules,
            "market_data_id": body.market_data_id,
            "model_type": body.model_type,
            "lookback_bars": body.lookback_bars,
            "user_plan": current_user.plan,
            "interval": md.interval,
        },
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Dispatch appropriate task
    if current_user.plan == "free":
        task = run_cycle_detection.apply_async(
            kwargs={"config": {"market_data_id": body.market_data_id, "job_id": str(job.id)}},
            queue="cycle_detection",
        )
    else:
        task = run_full_analysis.apply_async(
            kwargs={
                "config": {
                    **job.config,
                    "job_id": str(job.id),
                }
            },
            queue="ml_training",
        )

    # Save task ID
    job.celery_task_id = task.id
    await db.commit()

    return {
        "job_id": str(job.id),
        "task_id": task.id,
        "status": "queued",
        "modules": modules,
        "message": "Analysis queued. Poll GET /research/jobs/{job_id} for progress.",
    }


# ── NL Query ──────────────────────────────────────────────────────────────────

@router.post("/query")
async def research_query(
    body: QueryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Process a natural-language research query and map it to analysis tasks.

    Examples:
    - "Find strongest cycles" → cycle_detection
    - "Find dominant periodicity" → cycle_detection + stability
    - "Find hidden relationships" → features + planetary
    - "What happened in similar historical periods" → analog
    """
    query_lower = body.query.lower()

    # Map query intent to modules
    modules = ["preprocessing"]

    if any(kw in query_lower for kw in ["cycle", "period", "frequency", "periodicity", "dominant"]):
        modules.extend(["cycle_detection", "stability"])

    if any(kw in query_lower for kw in ["pattern", "structure", "regime", "repeat"]):
        modules.append("pattern_discovery")

    if any(kw in query_lower for kw in ["analog", "similar", "historical", "past"]):
        modules.append("analog")

    if any(kw in query_lower for kw in ["planet", "astro", "lunar", "solar", "jupiter", "saturn"]):
        modules.append("planetary")

    if any(kw in query_lower for kw in ["feature", "predictor", "important", "factor", "driver"]):
        modules.append("features")

    if any(kw in query_lower for kw in ["hidden", "relationship", "correlation", "dependency"]):
        modules.extend(["features", "planetary", "cycle_detection"])

    # Remove duplicates
    modules = list(dict.fromkeys(modules))

    # Apply plan limits
    if current_user.plan == "free":
        modules = [m for m in modules if m in ("preprocessing", "cycle_detection")]

    # Create job
    job = ResearchJob(
        id=uuid_lib.uuid4(),
        user_id=current_user.id,
        market_data_id=body.market_data_id,
        job_type="full_analysis",
        status="queued",
        config={
            "modules": modules,
            "market_data_id": body.market_data_id,
            "user_plan": current_user.plan,
            "query": body.query,
        },
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    task = run_full_analysis.apply_async(
        kwargs={"config": {**job.config, "job_id": str(job.id)}},
        queue="ml_training",
    )
    job.celery_task_id = task.id
    await db.commit()

    return {
        "job_id": str(job.id),
        "query": body.query,
        "interpreted_modules": modules,
        "status": "queued",
        "message": f"Query understood. Running: {', '.join(modules)}",
    }


# ── List Jobs ─────────────────────────────────────────────────────────────────

@router.get("/jobs", response_model=List[JobResponse])
async def list_jobs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 20,
    status_filter: Optional[str] = None,
):
    query = select(ResearchJob).where(ResearchJob.user_id == current_user.id)
    if status_filter:
        query = query.where(ResearchJob.status == status_filter)
    query = query.order_by(ResearchJob.queued_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    jobs = result.scalars().all()

    return [
        JobResponse(
            id=str(j.id),
            job_type=j.job_type,
            status=j.status,
            progress=j.progress or 0,
            progress_message=j.progress_message,
            celery_task_id=j.celery_task_id,
            queued_at=str(j.queued_at) if j.queued_at else None,
            started_at=str(j.started_at) if j.started_at else None,
            completed_at=str(j.completed_at) if j.completed_at else None,
            duration_seconds=j.duration_seconds,
        )
        for j in jobs
    ]


# ── Job Status ────────────────────────────────────────────────────────────────

@router.get("/jobs/{job_id}")
async def get_job_status(
    job_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ResearchJob).where(
            ResearchJob.id == job_id,
            ResearchJob.user_id == current_user.id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Also check Celery task state for live progress
    celery_state = None
    celery_progress = None
    if job.celery_task_id:
        try:
            from app.tasks.tasks import celery_app as celery
            task_result = celery.AsyncResult(job.celery_task_id)
            celery_state = task_result.state
            if task_result.info and isinstance(task_result.info, dict):
                celery_progress = task_result.info.get("progress")
        except Exception:
            pass

    return {
        "id": str(job.id),
        "job_type": job.job_type,
        "status": job.status,
        "progress": celery_progress or job.progress or 0,
        "progress_message": job.progress_message,
        "celery_state": celery_state,
        "queued_at": str(job.queued_at) if job.queued_at else None,
        "started_at": str(job.started_at) if job.started_at else None,
        "completed_at": str(job.completed_at) if job.completed_at else None,
        "duration_seconds": job.duration_seconds,
        "error_message": job.error_message,
    }


# ── Job Result ────────────────────────────────────────────────────────────────

@router.get("/jobs/{job_id}/result")
async def get_job_result(
    job_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ResearchJob).where(
            ResearchJob.id == job_id,
            ResearchJob.user_id == current_user.id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Job not completed yet (status={job.status})",
        )

    return {
        "job_id": str(job.id),
        "status": job.status,
        "result": job.result_summary,
        "completed_at": str(job.completed_at) if job.completed_at else None,
    }


# ── Cancel Job ────────────────────────────────────────────────────────────────

@router.delete("/jobs/{job_id}", status_code=204)
async def cancel_job(
    job_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ResearchJob).where(
            ResearchJob.id == job_id,
            ResearchJob.user_id == current_user.id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.celery_task_id:
        try:
            from app.tasks.tasks import celery_app as celery
            celery.control.revoke(job.celery_task_id, terminate=True)
        except Exception:
            pass

    job.status = "cancelled"
    await db.commit()
