"""
SQLAlchemy ORM Models — All database tables for Hidden Cycle Discovery AI.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey,
    Integer, JSON, String, Text, UniqueConstraint, Index,
    ARRAY, BigInteger, Numeric, SmallInteger, CHAR, TypeDecorator,
)
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID, BYTEA
from sqlalchemy.orm import relationship, Mapped
from sqlalchemy.sql import func

from app.db.base import Base


# ── Dialect-agnostic types ────────────────────────────────────────────────────
# Postgres gets native JSONB/UUID; SQLite (desktop mode) gets JSON/CHAR(36).

JSONB = JSON().with_variant(PG_JSONB(), "postgresql")


class UUID(TypeDecorator):
    """Platform-independent UUID: PG native uuid, elsewhere CHAR(36)."""
    impl = CHAR(36)
    cache_ok = True

    def __init__(self, as_uuid: bool = True):
        self.as_uuid = as_uuid
        super().__init__()

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=self.as_uuid))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None or dialect.name == "postgresql":
            return value
        if self.as_uuid and not isinstance(value, uuid.UUID):
            return uuid.UUID(value)
        return value


def gen_uuid():
    return str(uuid.uuid4())


# ─────────────────────────────────────────────
# USERS & AUTH
# ─────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255))
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    is_superuser = Column(Boolean, default=False)
    plan = Column(Enum("free", "pro", "enterprise", name="plan_enum"), default="free", nullable=False)
    stripe_customer_id = Column(String(255))
    stripe_subscription_id = Column(String(255))
    plan_expires_at = Column(DateTime(timezone=True))
    api_key = Column(String(64), unique=True, index=True)
    api_calls_today = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    market_data_uploads = relationship("MarketData", back_populates="user")
    research_jobs = relationship("ResearchJob", back_populates="user")
    research_reports = relationship("ResearchReport", back_populates="user")


# ─────────────────────────────────────────────
# MARKET DATA
# ─────────────────────────────────────────────

class MarketData(Base):
    __tablename__ = "market_data"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    symbol = Column(String(50), nullable=False, index=True)
    instrument_type = Column(
        Enum("index", "stock", "commodity", "crypto", "forex", "custom", name="instrument_type_enum"),
        nullable=False
    )
    exchange = Column(String(20))
    interval = Column(
        Enum("1m", "5m", "15m", "1h", "1d", name="interval_enum"),
        nullable=False
    )
    source = Column(
        Enum("yfinance", "nsepy", "alpha_vantage", "twelve_data", "ccxt", "csv_upload", name="data_source_enum"),
        nullable=False,
        default="yfinance"
    )

    # Date range
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    total_bars = Column(Integer)

    # OHLCV stored as S3 reference + metadata
    s3_key = Column(String(512))
    checksum = Column(String(64))  # SHA256 for integrity

    # Preprocessing state
    is_preprocessed = Column(Boolean, default=False)
    preprocessing_config = Column(JSONB, default={})

    # Status
    fetch_status = Column(
        Enum("pending", "fetching", "ready", "failed", name="fetch_status_enum"),
        default="pending"
    )
    error_message = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="market_data_uploads")
    cycles = relationship("CycleResult", back_populates="market_data")
    patterns = relationship("PatternResult", back_populates="market_data")
    analogs = relationship("AnalogResult", back_populates="market_data")

    __table_args__ = (
        Index("ix_market_data_symbol_interval", "symbol", "interval"),
        Index("ix_market_data_dates", "start_date", "end_date"),
    )


class MarketDataBar(Base):
    """Hot path: individual OHLCV bars stored in DB for small datasets / fast access."""
    __tablename__ = "market_data_bars"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    market_data_id = Column(UUID(as_uuid=True), ForeignKey("market_data.id", ondelete="CASCADE"), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    open = Column(Numeric(20, 8))
    high = Column(Numeric(20, 8))
    low = Column(Numeric(20, 8))
    close = Column(Numeric(20, 8))
    volume = Column(Numeric(24, 2))
    vwap = Column(Numeric(20, 8))

    # Derived series
    returns = Column(Float)
    log_returns = Column(Float)
    volatility_20 = Column(Float)

    __table_args__ = (
        Index("ix_bars_market_data_timestamp", "market_data_id", "timestamp"),
        UniqueConstraint("market_data_id", "timestamp", name="uq_bar_market_ts"),
    )


# ─────────────────────────────────────────────
# RESEARCH JOBS
# ─────────────────────────────────────────────

class ResearchJob(Base):
    __tablename__ = "research_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    market_data_id = Column(UUID(as_uuid=True), ForeignKey("market_data.id"))
    celery_task_id = Column(String(255))

    job_type = Column(
        Enum("full_analysis", "cycle_detection", "pattern_discovery",
             "planetary_correlation", "analog_search", "stability_test",
             "feature_discovery", "ai_train", name="job_type_enum"),
        nullable=False
    )

    status = Column(
        Enum("queued", "running", "completed", "failed", "cancelled", name="job_status_enum"),
        default="queued",
        index=True
    )

    config = Column(JSONB, default={})   # Job-specific parameters
    progress = Column(Float, default=0.0)  # 0–100
    progress_message = Column(String(500))
    result_summary = Column(JSONB)
    error_message = Column(Text)
    duration_seconds = Column(Float)

    queued_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))

    user = relationship("User", back_populates="research_jobs")

    __table_args__ = (
        Index("ix_jobs_user_status", "user_id", "status"),
    )


# ─────────────────────────────────────────────
# CYCLE RESULTS
# ─────────────────────────────────────────────

class CycleResult(Base):
    __tablename__ = "cycles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    market_data_id = Column(UUID(as_uuid=True), ForeignKey("market_data.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(UUID(as_uuid=True), ForeignKey("research_jobs.id"))

    # Cycle properties
    method = Column(
        Enum("fft", "lomb_scargle", "wavelet", "autocorrelation", "spectral_density",
             "hilbert", "hurst", "emd", name="cycle_method_enum"),
        nullable=False
    )
    period_bars = Column(Float, nullable=False)   # Period in bars
    period_calendar = Column(Float)                # Period in calendar days
    frequency = Column(Float)                      # 1/period
    amplitude = Column(Float)
    power = Column(Float)                          # Spectral power
    phase = Column(Float)                          # Phase offset in radians
    strength = Column(Float)                       # Normalized 0–1
    confidence = Column(Float)                     # Statistical confidence

    # Stability metrics
    is_stable = Column(Boolean, default=False)
    stability_score = Column(Float)
    oos_strength = Column(Float)                   # Out-of-sample strength
    decay_rate = Column(Float)                     # Cycle decay per year
    half_life_bars = Column(Integer)

    # Time context
    analysis_start = Column(DateTime(timezone=True))
    analysis_end = Column(DateTime(timezone=True))
    window_size_bars = Column(Integer)

    # Raw spectral data (for visualization)
    frequencies_json = Column(JSONB)
    powers_json = Column(JSONB)
    next_turning_point = Column(DateTime(timezone=True))
    turning_point_type = Column(Enum("peak", "trough", "unknown", name="tp_type_enum"))

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    market_data = relationship("MarketData", back_populates="cycles")

    __table_args__ = (
        Index("ix_cycles_market_period", "market_data_id", "period_bars"),
        Index("ix_cycles_strength", "strength"),
    )


# ─────────────────────────────────────────────
# PATTERN RESULTS
# ─────────────────────────────────────────────

class PatternResult(Base):
    __tablename__ = "patterns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    market_data_id = Column(UUID(as_uuid=True), ForeignKey("market_data.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(UUID(as_uuid=True), ForeignKey("research_jobs.id"))

    pattern_type = Column(
        Enum("shape", "turning_point_sequence", "volatility_cycle",
             "market_regime", "price_structure", name="pattern_type_enum"),
        nullable=False
    )
    cluster_id = Column(Integer)
    cluster_label = Column(String(100))

    # Pattern occurrences (list of [start_idx, end_idx, similarity_score])
    occurrences = Column(JSONB)
    occurrence_count = Column(Integer)
    avg_duration_bars = Column(Float)
    similarity_threshold = Column(Float)

    # Template/centroid stored as float array
    template_json = Column(JSONB)

    # Statistical
    mean_return_after = Column(Float)
    std_return_after = Column(Float)
    hit_rate = Column(Float)
    sharpe_like = Column(Float)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    market_data = relationship("MarketData", back_populates="patterns")


# ─────────────────────────────────────────────
# FEATURES
# ─────────────────────────────────────────────

class FeatureSet(Base):
    __tablename__ = "feature_sets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    market_data_id = Column(UUID(as_uuid=True), ForeignKey("market_data.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(UUID(as_uuid=True), ForeignKey("research_jobs.id"))
    feature_count = Column(Integer)
    s3_key = Column(String(512))       # Parquet file with all features
    feature_names = Column(JSONB)      # List of feature names
    importance_scores = Column(JSONB)  # Feature name -> importance
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PlanetaryFeatureSet(Base):
    __tablename__ = "planetary_features"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    market_data_id = Column(UUID(as_uuid=True), ForeignKey("market_data.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(UUID(as_uuid=True), ForeignKey("research_jobs.id"))

    # Top correlated planetary factors
    top_correlations = Column(JSONB)  # [{planet, aspect, lag, correlation, p_value}]
    mutual_information_scores = Column(JSONB)
    s3_key = Column(String(512))       # Full planetary feature matrix
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────────────────────────────
# AI MODELS
# ─────────────────────────────────────────────

class MLModel(Base):
    __tablename__ = "ml_models"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    market_data_id = Column(UUID(as_uuid=True), ForeignKey("market_data.id"))
    job_id = Column(UUID(as_uuid=True), ForeignKey("research_jobs.id"))

    model_type = Column(
        Enum("autoencoder", "transformer", "lstm", "tcn", "embedding", name="model_type_enum"),
        nullable=False
    )
    architecture_config = Column(JSONB)
    training_config = Column(JSONB)
    metrics = Column(JSONB)  # loss, reconstruction_error, etc.

    s3_key_weights = Column(String(512))
    s3_key_config = Column(String(512))

    is_production = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Embedding(Base):
    __tablename__ = "embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_id = Column(UUID(as_uuid=True), ForeignKey("ml_models.id"))
    market_data_id = Column(UUID(as_uuid=True), ForeignKey("market_data.id"))

    timestamp = Column(DateTime(timezone=True), nullable=False)
    vector = Column(JSONB)  # Embedding vector (list of floats)
    dim = Column(SmallInteger)
    window_size = Column(Integer)

    __table_args__ = (
        Index("ix_embeddings_market_ts", "market_data_id", "timestamp"),
    )


# ─────────────────────────────────────────────
# ANALOGS
# ─────────────────────────────────────────────

class AnalogResult(Base):
    __tablename__ = "analogs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    market_data_id = Column(UUID(as_uuid=True), ForeignKey("market_data.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(UUID(as_uuid=True), ForeignKey("research_jobs.id"))

    query_start = Column(DateTime(timezone=True))
    query_end = Column(DateTime(timezone=True))

    # Each analog: {start, end, similarity_score, forward_return_5d, forward_return_20d, ...}
    top_analogs = Column(JSONB)
    analog_count = Column(Integer)
    similarity_method = Column(String(50))

    # Composite forward projection
    composite_projection = Column(JSONB)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    market_data = relationship("MarketData", back_populates="analogs")


# ─────────────────────────────────────────────
# RESEARCH REPORTS
# ─────────────────────────────────────────────

class ResearchReport(Base):
    __tablename__ = "research_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    market_data_id = Column(UUID(as_uuid=True), ForeignKey("market_data.id"))
    job_id = Column(UUID(as_uuid=True), ForeignKey("research_jobs.id"))

    title = Column(String(500), nullable=False)
    query = Column(Text)  # Natural language query that generated this
    report_type = Column(
        Enum("cycle_summary", "full_analysis", "analog_report",
             "pattern_report", "planetary_report", "custom", name="report_type_enum"),
        nullable=False
    )

    # Report content
    executive_summary = Column(Text)
    sections = Column(JSONB)  # Structured sections
    charts_config = Column(JSONB)  # Chart configurations for frontend

    # File exports
    s3_key_pdf = Column(String(512))
    s3_key_csv = Column(String(512))
    s3_key_json = Column(String(512))

    is_public = Column(Boolean, default=False)
    public_slug = Column(String(100), unique=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="research_reports")

    __table_args__ = (
        Index("ix_reports_user", "user_id"),
    )
