"""
DESKTOP MODE ENTRY POINT
=========================
This is what PyInstaller freezes into `hcd-engine`. When DESKTOP_MODE=1:

  • Postgres  → SQLite   (aiosqlite, file in the app's user-data dir)
  • S3        → local disk (same dir)
  • Redis     → in-process fakeredis (job progress only)
  • Celery    → eager mode (tasks run in-process; no broker needed)

The FastAPI app and all 10 ML engines are unchanged — only the I/O layer
is swapped. Heavy analyses run in a thread pool so the UI stays responsive.
"""
import os
import sys
import multiprocessing


def configure_desktop_env():
    """Set environment overrides BEFORE importing app.core.config."""
    data_dir = os.environ.get("HCD_DATA_DIR") or os.path.join(
        os.path.expanduser("~"), ".hidden-cycle-discovery"
    )
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(os.path.join(data_dir, "storage"), exist_ok=True)
    os.makedirs(os.path.join(data_dir, "artifacts"), exist_ok=True)

    db_path = os.path.join(data_dir, "hcd.db").replace("\\", "/")

    os.environ.setdefault("APP_ENV", "development")   # enables auto create_all
    os.environ.setdefault("DEBUG", "false")
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    os.environ["CELERY_TASK_ALWAYS_EAGER"] = "true"
    os.environ.setdefault("DEVICE", "cpu")
    os.environ["ARTIFACTS_DIR"] = os.path.join(data_dir, "artifacts")
    os.environ["HCD_LOCAL_STORAGE_DIR"] = os.path.join(data_dir, "storage")
    os.environ["HCD_DESKTOP"] = "1"
    # Secrets only protect the local single-user instance
    os.environ.setdefault("SECRET_KEY", "desktop-local-instance")
    os.environ.setdefault("JWT_SECRET_KEY", "desktop-local-jwt")
    # Disable things that need cloud infra
    os.environ.setdefault("PROMETHEUS_ENABLED", "false")
    os.environ.setdefault("SENTRY_DSN", "")

    return data_dir


def patch_redis_for_desktop():
    """
    Desktop mode has no real Redis server. Swap app.core.redis's connection
    for an in-process fakeredis instance so job-progress code paths that
    expect a redis client keep working with zero extra process to run.
    """
    import fakeredis.aioredis
    from app.core import redis as redis_module

    _fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _init_redis_desktop():
        redis_module._redis_pool = _fake

    async def _get_redis_desktop():
        return _fake

    redis_module.init_redis = _init_redis_desktop
    redis_module.get_redis = _get_redis_desktop
    redis_module._redis_pool = _fake


def patch_storage_for_desktop():
    """
    Replace StorageService's S3 calls with local-disk equivalents.
    Done by monkeypatch so the rest of the codebase is untouched.
    """
    import asyncio
    from app.services import storage_service

    local_root = os.environ["HCD_LOCAL_STORAGE_DIR"]

    class LocalStorageService:
        @staticmethod
        async def upload_bytes(data: bytes, key: str, content_type: str = "") -> str:
            path = os.path.join(local_root, key)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: open(path, "wb").write(data)
            )
            return f"file://{path}"

        @staticmethod
        async def download_bytes(key: str) -> bytes:
            path = os.path.join(local_root, key)
            return await asyncio.get_event_loop().run_in_executor(
                None, lambda: open(path, "rb").read()
            )

        @staticmethod
        async def generate_presigned_url(key: str, expires_in: int = 3600) -> str:
            return f"file://{os.path.join(local_root, key)}"

        @staticmethod
        async def delete(key: str) -> None:
            path = os.path.join(local_root, key)
            if os.path.exists(path):
                os.remove(path)

    storage_service.StorageService = LocalStorageService


def main():
    multiprocessing.freeze_support()   # required for PyInstaller on Windows
    data_dir = configure_desktop_env()

    # Imports AFTER env config so settings pick up the overrides
    patch_storage_for_desktop()
    patch_redis_for_desktop()
    import uvicorn
    from app.main import app

    port = int(os.environ.get("HCD_PORT", "8741"))
    print(f"[hcd-engine] desktop mode | data: {data_dir} | port: {port}")

    uvicorn.run(
        app,
        host="127.0.0.1",      # local only — never exposed to the network
        port=port,
        log_level="warning",
        loop="asyncio",        # uvloop unavailable in frozen Windows builds
    )


if __name__ == "__main__":
    main()
