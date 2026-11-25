"""Production lab agent: shared limits, JSON logs, probes and safe shutdown."""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import time
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from redis.exceptions import RedisError

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_cost, record_cost, release_reservation
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import MOCK_RESPONSES, ask as llm_ask


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            **getattr(record, "fields", {}),
        }, ensure_ascii=False)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger = logging.getLogger("production_agent")
logger.handlers = [handler]
logger.setLevel(settings.log_level)
logger.propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.accepting = True
    logger.info("startup", extra={"fields": {"environment": settings.environment, "port": settings.port}})
    try:
        yield
    finally:
        # Uvicorn drains in-flight work before lifespan teardown. Keep its own
        # SIGTERM handler so shutdown works in both workers and Docker.
        app.state.accepting = False
        r.close()
        logger.info("shutdown_complete")


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    request_id = uuid.uuid4().hex
    request.state.request_id = request_id
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        route = request.scope.get("route")
        logger.info("http_request", extra={"fields": {
            "request_id": request_id, "method": request.method,
            "route": route.path if route else "unmatched", "status": status,
            "duration_ms": round((time.perf_counter() - start) * 1000, 3),
        }})


@app.exception_handler(RedisError)
async def redis_unavailable(request: Request, exc: RedisError):
    logger.warning("redis_unavailable", extra={"fields": {
        "request_id": getattr(request.state, "request_id", ""),
        "error_type": type(exc).__name__,
    }})
    return JSONResponse(status_code=503, content={"detail": "Storage temporarily unavailable"},
                        headers={"Retry-After": "1"})


@app.exception_handler(Exception)
async def internal_error(request: Request, exc: Exception):
    logger.error("internal_error", extra={"fields": {
        "request_id": getattr(request.state, "request_id", ""),
        "error_type": type(exc).__name__,
    }})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)

    @field_validator("question")
    @classmethod
    def nonblank_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


# Reserve the largest possible canned response, then refund the difference.
# This bound belongs to this mock, not to an arbitrary external LLM provider.
MAX_MOCK_OUTPUT_TOKENS = max(estimate_tokens(text)
                             for responses in MOCK_RESPONSES.values() for text in responses)


@app.get("/health")
def health():
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    if not getattr(app.state, "accepting", False) or not redis_healthy():
        raise HTTPException(status_code=503, detail="Agent not ready")
    return {"ready": True}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    input_tokens = estimate_tokens(body.question)
    reservation = check_budget(estimate_cost(input_tokens, MAX_MOCK_OUTPUT_TOKENS))
    try:
        answer = llm_ask(body.question)
    except Exception:
        release_reservation(reservation)
        raise
    output_tokens = estimate_tokens(answer)
    cost = record_cost(input_tokens, output_tokens, reservation)
    return {"question": body.question, "answer": answer,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                      "cost_usd": cost}}
