"""
API v1 Router — registers all endpoint modules.
"""
from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    market_data,
    research,
    cycles,
    patterns,
    analogs,
    planetary,
    features,
    models,
    reports,
    users,
    webhooks,
    providers,
)

api_router = APIRouter()

api_router.include_router(auth.router,        prefix="/auth",       tags=["Authentication"])
api_router.include_router(users.router,       prefix="/users",      tags=["Users"])
api_router.include_router(market_data.router, prefix="/market-data",tags=["Market Data"])
api_router.include_router(research.router,    prefix="/research",   tags=["Research"])
api_router.include_router(cycles.router,      prefix="/cycles",     tags=["Cycle Detection"])
api_router.include_router(patterns.router,    prefix="/patterns",   tags=["Pattern Discovery"])
api_router.include_router(analogs.router,     prefix="/analogs",    tags=["Analog Engine"])
api_router.include_router(planetary.router,   prefix="/planetary",  tags=["Planetary"])
api_router.include_router(features.router,    prefix="/features",   tags=["Features"])
api_router.include_router(models.router,      prefix="/models",     tags=["AI Models"])
api_router.include_router(reports.router,     prefix="/reports",    tags=["Reports"])
api_router.include_router(webhooks.router,    prefix="/webhooks",   tags=["Webhooks"])
api_router.include_router(providers.router,   prefix="/providers",  tags=["Data Providers"])
