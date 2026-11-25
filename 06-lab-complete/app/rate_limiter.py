"""
Rate limiting (tiêu chí 7) — sliding window 60 giây lưu trong Redis.
"""
import logging
import time
import uuid
from collections import defaultdict, deque

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import r

logger = logging.getLogger("app.rate_limiter")

WINDOW_SECONDS = 60
_fallback_windows: dict[str, deque[float]] = defaultdict(deque)


def check_rate_limit(key: str) -> None:
    """Kiểm tra giới hạn RATE_LIMIT_PER_MINUTE trong 60 giây gần nhất."""
    limit = settings.rate_limit_per_minute
    now = time.time()
    redis_key = f"rate_limit:{key}"

    if r is not None:
        try:
            cutoff = now - WINDOW_SECONDS
            pipe = r.pipeline()
            pipe.zremrangebyscore(redis_key, 0, cutoff)
            pipe.zcard(redis_key)
            _, current = pipe.execute()

            if current >= limit:
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": str(WINDOW_SECONDS)},
                )

            member = f"{now:.6f}:{uuid.uuid4().hex}"
            pipe_add = r.pipeline()
            pipe_add.zadd(redis_key, {member: now})
            pipe_add.expire(redis_key, WINDOW_SECONDS + 5)
            pipe_add.execute()
            return
        except RedisError as exc:
            logger.warning("redis_rate_limit_fallback", extra={"error": str(exc)})

    # Fallback in-memory chỉ dùng khi Redis không sẵn sàng ở môi trường local không có Redis
    window = _fallback_windows[key]
    cutoff = now - WINDOW_SECONDS
    while window and window[0] < cutoff:
        window.popleft()
    if len(window) >= limit:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(WINDOW_SECONDS)},
        )
    window.append(now)
