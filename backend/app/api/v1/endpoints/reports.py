from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.endpoints.auth import get_current_user
from app.db.session import get_db
from app.models.models import ResearchReport, User
from uuid import UUID

router = APIRouter()

@router.get("")
async def list_reports(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ResearchReport).where(ResearchReport.user_id == current_user.id).order_by(ResearchReport.created_at.desc()).limit(20))
    return {"reports": [{"id": str(r.id), "title": r.title, "report_type": r.report_type, "created_at": str(r.created_at)} for r in result.scalars().all()]}

@router.get("/{report_id}")
async def get_report(report_id: UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ResearchReport).where(ResearchReport.id == report_id, ResearchReport.user_id == current_user.id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(404, "Report not found")
    return {"id": str(report.id), "title": report.title, "executive_summary": report.executive_summary, "sections": report.sections, "charts_config": report.charts_config}
