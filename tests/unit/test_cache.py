import pytest
from fakeredis.aioredis import FakeRedis

from app.redis import CacheService


@pytest.fixture
def fake_redis():
    r = FakeRedis(decode_responses=True)
    return r


@pytest.fixture
def cache(fake_redis):
    return CacheService(fake_redis)


async def test_set_and_get_cached(cache):
    await cache.set_cached("key1", {"name": "test"})
    result = await cache.get_cached("key1")
    assert result == {"name": "test"}


async def test_get_cached_miss(cache):
    result = await cache.get_cached("nonexistent")
    assert result is None


async def test_cache_expiry(cache, fake_redis):
    await cache.set_cached("key_ttl", "value", ttl=10)
    ttl = await fake_redis.ttl("key_ttl")
    assert ttl > 0
    assert ttl <= 10


async def test_invalidate_pattern(cache, fake_redis):
    await cache.set_cached("events:list:a", "data1")
    await cache.set_cached("events:list:b", "data2")
    await cache.set_cached("other:key", "data3")

    await cache.invalidate("events:list:*")

    assert await cache.get_cached("events:list:a") is None
    assert await cache.get_cached("events:list:b") is None
    assert await cache.get_cached("other:key") is not None
