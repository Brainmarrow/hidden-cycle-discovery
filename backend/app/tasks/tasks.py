"""
Celery Task Definitions — Hidden Cycle Discovery AI

All heavy ML work runs as async Celery tasks, allowing:
- Non-blocking API responses
- Progress tracking via Redis
- Parallel processing across workers
- GPU-accelerated training tasks
"""
from __future__ import annotations

import logging
import time
import traceback
from datetime import datetime
from typing import Optional
from uuid import UUID

import structlog
from celery import Celery, Task
from celery.signals import task_prerun, task_postrun, task_failure

from app.core.config import settings

logger = structlog.get_logger()

# ── Celery App ────────────────────────────────────────────────────────────────

celery_app = Celery(
    "hidden_cycle_discovery",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_always_eager=settings.CELERY_TASK_ALWAYS_EAGER,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_routes={
        "app.tasks.tasks.run_full_analysis": {"queue": "ml_training"},
        "app.tasks.tasks.run_cycle_detection": {"queue": "cycle_detection"},
        "app.tasks.tasks.run_analog_search": {"queue": "default"},
        "app.tasks.tasks.fetch_market_data": {"queue": "data_fetch"},
        "app.tasks.tasks.train_ai_model": {"queue": "ml_training"},
    },
    beat_schedule={
        # Refresh popular symbols daily
        "refresh-nifty-daily": {
            "task": "app.tasks.tasks.fetch_market_data",
            "schedule": 86400,  # Every 24h
            "args": [{"symbol": "^NSEI", "interval": "1d", "source": "yfinance"}],
        },
    },
)


# ── Base Task with Progress Tracking ─────────────────────────────────────────

class ProgressTask(Task):
    """Base task that updates job progress in DB."""

    abstract = True

    def update_progress(self, job_id: str, progress: float, message: str = ""):
        """Update job progress in DB and Redis."""
        self.update_state(
            state="PROGRESS",
            meta={"progress": progress, "message": message, "job_id": job_id},
        )
        # Also push to Redis for live WebSocket streaming
        try:
            import redis
            r = redis.from_url(settings.REDIS_URL)
            r.publish(f"job:{job_id}:progress", f"{progress}|{message}")
        except Exception:
            pass


# ── Task: Fetch Market Data ───────────────────────────────────────────────────

@celery_app.task(bind=True, base=ProgressTask, name="app.tasks.tasks.fetch_market_data")
def fetch_market_data(self, config: dict) -> dict:
    """
    Fetch OHLCV data from external sources and store in DB.

    Args:
        config: {symbol, interval, source, start_date, end_date, market_data_id}
    """
    from app.services.data_service import DataService
    import asyncio

    job_id = config.get("job_id", self.request.id)
    self.update_progress(job_id, 5, "Initializing data fetch")

    try:
        symbol = config["symbol"]
        interval = config.get("interval", "1d")
        source = config.get("source", "yfinance")
        start_date = config.get("start_date")
        end_date = config.get("end_date")

        logger.info("fetch_market_data_started", symbol=symbol, interval=interval, source=source)
        self.update_progress(job_id, 20, f"Fetching {symbol} from {source}")

        # Run async in sync context
        loop = asyncio.new_event_loop()
        df = loop.run_until_complete(
            DataService.fetch(symbol=symbol, interval=interval, source=source,
                              start_date=start_date, end_date=end_date)
        )
        loop.close()

        self.update_progress(job_id, 80, f"Fetched {len(df)} bars, saving")

        # Save via DB
        market_data_id = config.get("market_data_id")
        if market_data_id:
            loop2 = asyncio.new_event_loop()
            loop2.run_until_complete(DataService.save_bars(market_data_id, df))
            loop2.close()

        self.update_progress(job_id, 100, "Data fetch complete")

        return {
            "status": "success",
            "n_bars": len(df),
            "symbol": symbol,
            "interval": interval,
            "market_data_id": market_data_id,
        }

    except Exception as e:
        logger.error("fetch_market_data_failed", error=str(e), config=config)
        raise


# ── Task: Run Full Analysis ───────────────────────────────────────────────────

@celery_app.task(bind=True, base=ProgressTask, name="app.tasks.tasks.run_full_analysis")
def run_full_analysis(self, config: dict) -> dict:
    """
    Full pipeline: preprocess → cycle detection → patterns → planetary → features → stability → analogs.

    Args:
        config: {market_data_id, job_id, modules: [...], user_plan}
    """
    import asyncio
    import pandas as pd
    from app.services.data_service import DataService

    job_id = config.get("job_id", self.request.id)
    market_data_id = config["market_data_id"]
    modules = config.get("modules", ["preprocessing", "cycle_detection", "pattern_discovery",
                                      "stability", "analog", "features"])
    user_plan = config.get("user_plan", "free")

    results = {"job_id": job_id, "market_data_id": market_data_id, "modules": {}}

    try:
        # ── Load data ─────────────────────────────────────────────
        self.update_progress(job_id, 5, "Loading market data")
        loop = asyncio.new_event_loop()
        df = loop.run_until_complete(DataService.load_dataframe(market_data_id))
        loop.close()

        if df is None or len(df) < 20:
            raise ValueError("Insufficient market data")

        bars_per_day = _get_bars_per_day(config.get("interval", "1d"))

        # ── Module 1: Preprocessing ────────────────────────────────
        self.update_progress(job_id, 10, "Preprocessing data")
        if "preprocessing" in modules:
            from app.ml.preprocessing.engine import PreprocessingEngine, PreprocessingConfig
            engine = PreprocessingEngine(PreprocessingConfig())
            preprocessed = engine.process(df)
            results["modules"]["preprocessing"] = preprocessed.metadata
            logger.info("preprocessing_complete", n_bars=preprocessed.n_bars)
        else:
            preprocessed = None

        # ── Module 2: Cycle Detection ──────────────────────────────
        self.update_progress(job_id, 20, "Detecting cycles (FFT, Wavelets, Lomb-Scargle...)")
        if "cycle_detection" in modules and preprocessed is not None:
            from app.ml.cycle_detection.engine import CycleDetectionEngine

            cycle_engine = CycleDetectionEngine(
                min_period_bars=3,
                max_period_bars=len(preprocessed.detrended) // 2,
                top_n_cycles=30,
                bars_per_day=bars_per_day,
            )
            cycle_result = cycle_engine.detect(preprocessed.detrended)
            results["modules"]["cycle_detection"] = cycle_result.to_dict()

            # Persist to DB
            loop3 = asyncio.new_event_loop()
            loop3.run_until_complete(
                DataService.save_cycles(market_data_id, job_id, cycle_result)
            )
            loop3.close()
            logger.info("cycle_detection_complete", n_dominant=len(cycle_result.dominant))
        else:
            cycle_result = None

        # ── Module 3: Pattern Discovery ────────────────────────────
        self.update_progress(job_id, 40, "Discovering repeating patterns")
        if "pattern_discovery" in modules and preprocessed is not None:
            from app.ml.pattern_discovery.engine import PatternDiscoveryEngine

            pattern_engine = PatternDiscoveryEngine(
                window_sizes=[10, 20, 40, 60] if len(df) > 200 else [5, 10, 20],
                min_occurrences=3,
            )
            pattern_result = pattern_engine.discover(preprocessed.normalized, preprocessed.log_returns)
            results["modules"]["pattern_discovery"] = pattern_result.to_dict()
            logger.info("pattern_discovery_complete", n_patterns=len(pattern_result.patterns))
        else:
            pattern_result = None

        # ── Module 4: Planetary (Pro+) ─────────────────────────────
        if "planetary" in modules and user_plan in ("pro", "enterprise") and preprocessed is not None:
            self.update_progress(job_id, 50, "Computing planetary correlations")
            try:
                from app.ml.planetary.engine import PlanetaryCorrelationEngine
                planet_engine = PlanetaryCorrelationEngine()
                planet_result = planet_engine.analyze(preprocessed.raw, preprocessed.log_returns)
                results["modules"]["planetary"] = planet_result.to_dict()
                logger.info("planetary_complete", n_significant=planet_result.n_significant)
            except Exception as e:
                logger.warning("planetary_skipped", reason=str(e))

        # ── Module 5: Feature Discovery ────────────────────────────
        self.update_progress(job_id, 60, "Discovering important features")
        if "features" in modules and preprocessed is not None:
            from app.ml.feature_engine.engine import FeatureDiscoveryEngine
            feat_engine = FeatureDiscoveryEngine(
                include_cycles=(cycle_result is not None),
                top_k_features=50,
            )
            feat_result = feat_engine.discover(df, preprocessed, cycle_result)
            results["modules"]["features"] = feat_result.to_dict()
            logger.info("features_complete", n_features=feat_result.n_features_total)
        else:
            feat_result = None

        # ── Module 8: Stability ────────────────────────────────────
        self.update_progress(job_id, 75, "Testing cycle stability")
        if "stability" in modules and cycle_result is not None and preprocessed is not None:
            from app.ml.stability.engine import StabilityEngine
            stability_engine = StabilityEngine()
            stability_result = stability_engine.test(preprocessed.detrended, cycle_result)
            results["modules"]["stability"] = stability_result.to_dict()
            logger.info("stability_complete", n_stable=len(stability_result.stable_cycles))

        # ── Module 7: Analog Search ────────────────────────────────
        self.update_progress(job_id, 88, "Finding historical analogs")
        if "analog" in modules and preprocessed is not None and user_plan in ("pro", "enterprise"):
            from app.ml.analog.engine import AnalogEngine
            analog_engine = AnalogEngine(lookback_bars=min(60, len(df) // 4), top_n=10)
            analog_result = analog_engine.find_analogs(preprocessed.normalized, preprocessed.log_returns)
            results["modules"]["analog"] = analog_result.to_dict()
            logger.info("analog_complete", n_analogs=analog_result.n_analogs_found)

        # ── Generate Research Report ───────────────────────────────
        self.update_progress(job_id, 95, "Generating research report")
        report = _generate_summary_report(results)
        results["report"] = report

        self.update_progress(job_id, 100, "Analysis complete")

        # Update job status in DB
        loop4 = asyncio.new_event_loop()
        loop4.run_until_complete(DataService.update_job_status(job_id, "completed", results))
        loop4.close()

        return results

    except Exception as e:
        tb = traceback.format_exc()
        logger.error("full_analysis_failed", error=str(e), traceback=tb, job_id=job_id)
        import asyncio
        loop5 = asyncio.new_event_loop()
        loop5.run_until_complete(DataService.update_job_status(job_id, "failed", {"error": str(e)}))
        loop5.close()
        raise


# ── Task: Run Cycle Detection Only ────────────────────────────────────────────

@celery_app.task(bind=True, base=ProgressTask, name="app.tasks.tasks.run_cycle_detection")
def run_cycle_detection(self, config: dict) -> dict:
    """Standalone cycle detection task (faster, for free tier)."""
    import asyncio
    from app.services.data_service import DataService

    job_id = config.get("job_id", self.request.id)
    market_data_id = config["market_data_id"]

    self.update_progress(job_id, 10, "Loading data")
    loop = asyncio.new_event_loop()
    df = loop.run_until_complete(DataService.load_dataframe(market_data_id))
    loop.close()

    self.update_progress(job_id, 30, "Preprocessing")
    from app.ml.preprocessing.engine import PreprocessingEngine
    preprocessed = PreprocessingEngine().process(df)

    self.update_progress(job_id, 60, "Running cycle detection")
    from app.ml.cycle_detection.engine import CycleDetectionEngine
    engine = CycleDetectionEngine(top_n_cycles=10)  # Free tier: top 10
    result = engine.detect(preprocessed.detrended)

    self.update_progress(job_id, 90, "Saving results")
    loop2 = asyncio.new_event_loop()
    loop2.run_until_complete(DataService.update_job_status(job_id, "completed", result.to_dict()))
    loop2.close()

    self.update_progress(job_id, 100, "Done")
    return result.to_dict()


# ── Task: Train AI Model ──────────────────────────────────────────────────────

@celery_app.task(bind=True, base=ProgressTask, name="app.tasks.tasks.train_ai_model")
def train_ai_model(self, config: dict) -> dict:
    """Train a deep learning model on market data (Pro+)."""
    import asyncio
    from app.services.data_service import DataService

    job_id = config.get("job_id", self.request.id)
    market_data_id = config["market_data_id"]
    model_type = config.get("model_type", "autoencoder")

    self.update_progress(job_id, 5, "Loading data")
    loop = asyncio.new_event_loop()
    df = loop.run_until_complete(DataService.load_dataframe(market_data_id))
    loop.close()

    self.update_progress(job_id, 15, "Preprocessing")
    from app.ml.preprocessing.engine import PreprocessingEngine
    preprocessed = PreprocessingEngine().process(df)

    self.update_progress(job_id, 25, f"Training {model_type} model (GPU if available)")
    from app.ml.ai_models.engine import AIModelEngine, ModelConfig
    model_config = ModelConfig(
        model_type=model_type,
        seq_len=min(64, len(df) // 10),
        latent_dim=32,
        n_epochs=config.get("n_epochs", 100),
    )
    ai_engine = AIModelEngine(config=model_config)

    training_result = ai_engine.train(preprocessed.vol_adjusted, model_id=f"{market_data_id}_{model_type}")
    self.update_progress(job_id, 90, "Saving model artifacts")

    result = {
        "model_type": model_type,
        "best_val_loss": training_result.best_val_loss,
        "best_epoch": training_result.best_epoch,
        "training_time_seconds": training_result.training_time_seconds,
        "model_path": training_result.model_path,
    }

    loop2 = asyncio.new_event_loop()
    loop2.run_until_complete(DataService.update_job_status(job_id, "completed", result))
    loop2.close()

    self.update_progress(job_id, 100, "Training complete")
    return result


# ── Task: Analog Search ───────────────────────────────────────────────────────

@celery_app.task(bind=True, base=ProgressTask, name="app.tasks.tasks.run_analog_search")
def run_analog_search(self, config: dict) -> dict:
    """Find historical analogs for the current market period."""
    import asyncio
    from app.services.data_service import DataService

    job_id = config.get("job_id", self.request.id)
    market_data_id = config["market_data_id"]
    lookback = config.get("lookback_bars", 60)

    self.update_progress(job_id, 10, "Loading data")
    loop = asyncio.new_event_loop()
    df = loop.run_until_complete(DataService.load_dataframe(market_data_id))
    loop.close()

    self.update_progress(job_id, 25, "Preprocessing")
    from app.ml.preprocessing.engine import PreprocessingEngine
    preprocessed = PreprocessingEngine().process(df)

    self.update_progress(job_id, 50, "Searching for analogs")
    from app.ml.analog.engine import AnalogEngine
    analog_engine = AnalogEngine(lookback_bars=lookback, top_n=15)
    result = analog_engine.find_analogs(preprocessed.normalized, preprocessed.log_returns)

    self.update_progress(job_id, 90, "Saving results")
    loop2 = asyncio.new_event_loop()
    loop2.run_until_complete(DataService.update_job_status(job_id, "completed", result.to_dict()))
    loop2.close()

    self.update_progress(job_id, 100, "Done")
    return result.to_dict()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_bars_per_day(interval: str) -> float:
    mapping = {
        "1m": 390.0, "5m": 78.0, "15m": 26.0,
        "1h": 6.5, "1d": 1.0,
    }
    return mapping.get(interval, 1.0)


def _generate_summary_report(results: dict) -> dict:
    """Build a structured summary report from all module results."""
    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "key_findings": [],
        "dominant_cycles": [],
        "stable_cycles": [],
        "top_analogs": [],
        "top_features": [],
    }

    # Cycle findings
    cycle_data = results.get("modules", {}).get("cycle_detection", {})
    if cycle_data:
        dominant = cycle_data.get("dominant_cycles", [])[:5]
        report["dominant_cycles"] = dominant
        for c in dominant:
            report["key_findings"].append(
                f"Dominant cycle detected: {c['period_bars']:.0f} bars "
                f"(strength={c['strength']:.2f}, method={c['method']})"
            )

    # Stable cycles
    stability_data = results.get("modules", {}).get("stability", {})
    if stability_data:
        stable = stability_data.get("stable_cycles", [])[:5]
        report["stable_cycles"] = stable
        for s in stable:
            report["key_findings"].append(
                f"Stable cycle: {s['period_bars']:.0f} bars "
                f"(stability={s['stability_score']:.2f})"
            )

    # Analogs
    analog_data = results.get("modules", {}).get("analog", {})
    if analog_data:
        report["top_analogs"] = analog_data.get("top_analogs", [])[:3]
        proj = analog_data.get("composite_projection", {})
        conf = analog_data.get("projection_confidence", 0)
        if proj.get("5d"):
            direction = "bullish" if proj["5d"] > 0 else "bearish"
            report["key_findings"].append(
                f"Historical analogs suggest {direction} outcome "
                f"(5d projection: {proj['5d']:.2%}, confidence: {conf:.0%})"
            )

    # Features
    feat_data = results.get("modules", {}).get("features", {})
    if feat_data:
        report["top_features"] = feat_data.get("top_features", [])[:10]

    return report
