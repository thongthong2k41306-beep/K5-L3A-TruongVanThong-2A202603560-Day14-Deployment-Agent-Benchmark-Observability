"""Lazy Redis client: importing the app never requires a live Redis server."""
import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from app.config import settings

r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=settings.redis_timeout_seconds,
    socket_timeout=settings.redis_timeout_seconds,
    retry=Retry(NoBackoff(), 0),
)


def redis_healthy() -> bool:
    try:
        return bool(r.ping())
    except redis.RedisError:
        return False
