"""Redis connection pool."""
import redis.asyncio as aioredis
from app.core.config import settings

_redis_pool = None

async def init_redis():
    global _redis_pool
    _redis_pool = aioredis.from_url(settings.REDIS_URL, decode_responses=True, max_connections=settings.REDIS_MAX_CONNECTIONS)

async def get_redis():
    return _redis_pool
