"""Atomic sliding-window rate limiting shared across workers in Redis."""
import hashlib
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Redis's clock keeps the rolling window consistent across instances.
_SLIDING_WINDOW = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
local window = 60000
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
local count = redis.call('ZCARD', KEYS[1])
if count >= tonumber(ARGV[1]) then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    local retry_after = math.max(1, math.ceil((tonumber(oldest[2]) + window - now) / 1000))
    return {0, retry_after}
end
redis.call('ZADD', KEYS[1], now, ARGV[2])
redis.call('PEXPIRE', KEYS[1], window)
return {1, 0}
"""


def check_rate_limit(key: str) -> None:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    redis_key = f"production-agent:{settings.environment}:rate:{digest}"
    allowed, retry_after = r.eval(_SLIDING_WINDOW, 1, redis_key,
                                  settings.rate_limit_per_minute, uuid.uuid4().hex)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded",
                            headers={"Retry-After": str(retry_after)})
