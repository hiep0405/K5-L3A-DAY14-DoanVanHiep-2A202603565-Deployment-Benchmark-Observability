"""
Cost guard (tiêu chí 8) — theo dõi chi phí LLM theo token trong Redis.
"""
import logging
from datetime import datetime, timezone

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import r

logger = logging.getLogger("app.cost_guard")

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

_fallback_daily: dict[str, float] = {}
_fallback_monthly: dict[str, float] = {}


def _keys(scope: str = "global") -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    month = now.strftime("%Y-%m")
    return f"cost:daily:{scope}:{day}", f"cost:monthly:{scope}:{month}"


def check_budget(scope: str = "global") -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    daily_key, monthly_key = _keys(scope)

    if r is not None:
        try:
            pipe = r.pipeline()
            pipe.get(daily_key)
            pipe.get(monthly_key)
            daily_raw, monthly_raw = pipe.execute()
            daily_spent = float(daily_raw or 0.0)
            monthly_spent = float(monthly_raw or 0.0)
            if daily_spent >= settings.daily_budget_usd or monthly_spent >= settings.monthly_budget_usd:
                raise HTTPException(status_code=402, detail="Budget exceeded")
            return
        except RedisError as exc:
            logger.warning("redis_cost_check_fallback", extra={"error": str(exc)})

    daily_spent = _fallback_daily.get(daily_key, 0.0)
    monthly_spent = _fallback_monthly.get(monthly_key, 0.0)
    if daily_spent >= settings.daily_budget_usd or monthly_spent >= settings.monthly_budget_usd:
        raise HTTPException(status_code=402, detail="Budget exceeded")


def record_cost(input_tokens: int, output_tokens: int, scope: str = "global") -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (
        (input_tokens / 1000.0) * PRICE_INPUT_PER_1K
        + (output_tokens / 1000.0) * PRICE_OUTPUT_PER_1K
    )
    daily_key, monthly_key = _keys(scope)

    if r is not None:
        try:
            pipe = r.pipeline()
            pipe.incrbyfloat(daily_key, cost)
            pipe.expire(daily_key, 2 * 24 * 3600)
            pipe.incrbyfloat(monthly_key, cost)
            pipe.expire(monthly_key, 32 * 24 * 3600)
            pipe.execute()
            return cost
        except RedisError as exc:
            logger.warning("redis_cost_record_fallback", extra={"error": str(exc)})

    _fallback_daily[daily_key] = _fallback_daily.get(daily_key, 0.0) + cost
    _fallback_monthly[monthly_key] = _fallback_monthly.get(monthly_key, 0.0) + cost
    return cost
