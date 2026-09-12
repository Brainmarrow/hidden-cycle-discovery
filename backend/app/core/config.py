"""
Core application configuration using Pydantic Settings.
All settings are loaded from environment variables / .env file.
"""
from functools import lru_cache
from typing import Literal, List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyHttpUrl, PostgresDsn, field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────
    APP_NAME: str = "Hidden Cycle Discovery AI"
    APP_VERSION: str = "1.0.0"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me-in-production"
    ALLOWED_HOSTS: List[str] = ["*"]
    API_PREFIX: str = "/api/v1"

    # ── Database ──────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://hcd_user:hcd_password@localhost:5432/hcd_db"
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
    DATABASE_ECHO: bool = False

    # ── Redis ──────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_MAX_CONNECTIONS: int = 50

    # ── Celery ──────────────────────────────────────────────────────────────
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    CELERY_TASK_ALWAYS_EAGER: bool = False
    CELERY_WORKER_CONCURRENCY: int = 4
    CELERY_TASK_TIME_LIMIT: int = 3600  # 1 hour
    CELERY_TASK_SOFT_TIME_LIMIT: int = 3300

    # ── AWS S3 ──────────────────────────────────────────────────────────────
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "ap-south-1"
    S3_BUCKET_NAME: str = "hidden-cycle-discovery"

    # ── JWT Auth ──────────────────────────────────────────────────────────────
    JWT_SECRET_KEY: str = "change-me-jwt-secret"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # ── Data Sources ──────────────────────────────────────────────────────────
    ALPHA_VANTAGE_API_KEY: str = ""
    TWELVE_DATA_API_KEY: str = ""
    NSE_DATA_ENABLED: bool = True

    # ── ML ──────────────────────────────────────────────────────────────
    DEVICE: str = "cuda"  # or cpu
    NUM_WORKERS: int = 4
    ARTIFACTS_DIR: str = "/app/artifacts"
    MAX_DATA_POINTS_DAILY: int = 7300      # 20 years
    MAX_DATA_POINTS_INTRADAY: int = 650000  # 5 years of 1m

    # ── Planetary ──────────────────────────────────────────────────────────────
    EPHEM_ENABLED: bool = True

    # ── Stripe ──────────────────────────────────────────────────────────────
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    # ── Plans ──────────────────────────────────────────────────────────────
    FREE_MAX_LOOKBACK_DAYS: int = 365
    FREE_MAX_CYCLES_RETURNED: int = 10
    PRO_PRICE_USD: float = 49.0
    ENTERPRISE_PRICE_USD: float = 299.0

    # ── Logging / Monitoring ──────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    SENTRY_DSN: str = ""
    PROMETHEUS_ENABLED: bool = True

    @field_validator("ALLOWED_HOSTS", mode="before")
    @classmethod
    def parse_allowed_hosts(cls, v):
        if isinstance(v, str):
            return [h.strip() for h in v.split(",")]
        return v


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
