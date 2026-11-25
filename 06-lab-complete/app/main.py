"""
Production AI Agent — Part 6 Final Project.
"""
import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import close_redis, redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Định dạng mỗi dòng log của ứng dụng thành một JSON object hợp lệ."""

    _STANDARD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys())

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in self._STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _setup_logger() -> logging.Logger:
    app_logger = logging.getLogger("app")
    app_logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    app_logger.propagate = False
    if not app_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        app_logger.addHandler(handler)
    return app_logger


logger = _setup_logger()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info(
        "startup",
        extra={
            "event": "startup",
            "environment": settings.environment,
            "port": settings.port,
        },
    )
    yield
    logger.info("shutdown", extra={"event": "shutdown"})
    close_redis()


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        logger.info(
            "http_request",
            extra={
                "event": "http_request",
                "method": request.method,
                "path": request.url.path,
                "status": status,
                "ms": elapsed_ms,
            },
        )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception):
    logger.error("unhandled_error", extra={"event": "unhandled_error", "error": type(exc).__name__})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=128)


@app.get("/health")
def health():
    """Liveness probe — luôn trả 200 khi process còn sống."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness probe — trả 200 khi Redis kết nối được, 503 khi mất Redis."""
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis unavailable")
    return {"status": "ready"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    scope = body.user_id or api_key
    check_budget(scope=scope)

    answer = llm_ask(body.question)
    input_tokens = max(1, len(body.question) // 4)
    output_tokens = max(1, len(answer) // 4)
    cost = record_cost(input_tokens, output_tokens, scope=scope)

    logger.info(
        "ask_completed",
        extra={
            "event": "ask_completed",
            "user_id": body.user_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 8),
        },
    )
    return {
        "question": body.question,
        "answer": answer,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 8),
        },
    }
