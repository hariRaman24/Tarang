import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import os

from app.orchestrator import orchestrate
from app.schemas import MarineQuery
from app.conversation_store import conversation_store
from app.health import platform_health
from app.config import (
    TARANG_MAX_BODY_BYTES,
    TARANG_RATE_LIMIT,
    TARANG_RATE_WINDOW_SECONDS,
)
from app.security import SlidingWindowRateLimiter

app = FastAPI(title="TARANG Marine Intelligence API", version="0.4.0")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_ROOT / "frontend"

if FRONTEND_DIR.exists():
    app.mount(
        "/static",
        StaticFiles(directory=str(FRONTEND_DIR)),
        name="static",
    )
rate_limiter = SlidingWindowRateLimiter(
    TARANG_RATE_LIMIT,
    TARANG_RATE_WINDOW_SECONDS,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "TARANG_ALLOWED_ORIGINS",
            "http://127.0.0.1:5500,http://localhost:5500",
        ).split(",")
        if origin.strip()
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    started = time.perf_counter()
    if request.method == "POST":
        content_length = request.headers.get("content-length")
        try:
            body_size = int(content_length) if content_length else 0
        except ValueError:
            body_size = TARANG_MAX_BODY_BYTES + 1
        if body_size > TARANG_MAX_BODY_BYTES:
            return JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "PAYLOAD_TOO_LARGE",
                        "message": "Request body exceeds the configured limit.",
                    },
                    "request_id": request_id,
                },
                headers={"X-Request-ID": request_id},
            )

    if request.url.path == "/api/query":
        client_key = request.client.host if request.client else "unknown"
        allowed, retry_after = rate_limiter.check(client_key)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "Too many marine queries. Please retry later.",
                    },
                    "request_id": request_id,
                },
                headers={
                    "X-Request-ID": request_id,
                    "Retry-After": str(retry_after),
                },
            )
    try:
        response = await call_next(request)
    except Exception:
        # Preserve the request ID for server logs while letting FastAPI's
        # exception machinery handle unexpected failures.
        raise
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-Ms"] = str(
        round((time.perf_counter() - started) * 1000, 2)
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
):
    request_id = request.headers.get("X-Request-ID") or "unavailable"
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "The request did not match the TARANG API schema.",
                "fields": exc.errors(),
            },
            "request_id": request_id,
        },
        headers={"X-Request-ID": request_id},
    )


@app.get("/", include_in_schema=False)
async def website():
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        return JSONResponse(
            status_code=503,
            content={
                "platform": "TARANG",
                "status": "frontend_missing",
            },
        )
    return FileResponse(index_file)


@app.get("/api/status")
async def api_status():
    return {
        "platform": "TARANG",
        "status": "online",
        "health_url": "/api/health",
    }


@app.get("/api/health")
async def health():
    return platform_health()


@app.get("/api/health/sources")
async def source_health():
    snapshot = platform_health()
    return {
        "sources": snapshot["sources"],
        "source_count": snapshot["source_count"],
        "probe_policy": (
            "This endpoint reports registry/configuration metadata. "
            "Live source probes occur during agent execution to avoid "
            "turning health checks into expensive upstream traffic."
        ),
    }


@app.get("/api/conversations/{conversation_id}")
async def conversation_history(conversation_id: str):
    return {
        "conversation_id": conversation_id,
        "messages": conversation_store.history(conversation_id, limit=50),
    }


@app.post("/api/query")
async def marine_query(
    payload: MarineQuery,
    http_request: Request,
):
    try:
        return await orchestrate(
            payload,
            request_id=getattr(
                http_request.state,
                "request_id",
                None,
            ),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )
