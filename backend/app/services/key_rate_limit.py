"""Per-API-key request rate limit, shared by every pod through Redis.

WAF limits are per source IP and can't tell keys apart; this caps what one
key can send regardless of where it comes from. Fixed one-minute windows:
simple, one round trip, and generous enough (default 600/min against a
30-day per-key peak of 36/min) that window-edge bursts don't matter.

If Redis is unavailable the request is allowed and a warning logged:
failing closed would turn a cache outage into a full gateway outage.
"""

import logging
import time

from fastapi import HTTPException, status

from app.core.config import get_settings
from app.core.redis import get_redis
from app.models.token import APIToken

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60


def limit_for(token: APIToken) -> int:
    """Requests per minute for this key; 0 means unlimited."""
    meta = token.token_metadata if isinstance(token.token_metadata, dict) else {}
    override = meta.get("rate_limit_rpm")
    if isinstance(override, int) and not isinstance(override, bool) and override >= 0:
        return override
    return get_settings().KEY_RATE_LIMIT_RPM


async def enforce_key_rate_limit(token: APIToken, now: float | None = None) -> None:
    limit = limit_for(token)
    if limit <= 0:
        return
    redis = await get_redis()
    if redis is None:
        return
    now = time.time() if now is None else now
    window = int(now // WINDOW_SECONDS)
    key = f"kbp:rl:key:{token.id}:{window}"
    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, WINDOW_SECONDS * 2, nx=True)
            count, _ = await pipe.execute()
    except Exception:
        logger.warning("Key rate limit check skipped: Redis error", exc_info=True)
        return
    if count > limit:
        retry_after = max(1, int((window + 1) * WINDOW_SECONDS - now))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for this API key",
            headers={"Retry-After": str(retry_after)},
        )
