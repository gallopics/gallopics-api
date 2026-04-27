import json
from typing import Any, Optional

import redis.asyncio as aioredis

from app.config import get_settings


async def get_redis() -> aioredis.Redis:
    settings = get_settings()
    return aioredis.from_url(settings.redis_url, decode_responses=True)


class CacheService:
    def __init__(self, redis_client: aioredis.Redis):
        self.redis = redis_client

    async def get_cached(self, key: str) -> Optional[Any]:
        value = await self.redis.get(key)
        if value is None:
            return None
        return json.loads(value)

    async def set_cached(self, key: str, value: Any, ttl: int = 300) -> None:
        await self.redis.set(key, json.dumps(value, default=str), ex=ttl)

    async def invalidate(self, pattern: str) -> None:
        async for key in self.redis.scan_iter(match=pattern):
            await self.redis.delete(key)
