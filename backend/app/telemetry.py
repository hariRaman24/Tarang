"""Structured execution telemetry for the TARANG agent pipeline."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Awaitable, Callable


logger = logging.getLogger("tarang")


async def timed_call(
    name: str,
    operation: Callable[[], Awaitable[dict[str, Any]]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    result = await operation()
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    telemetry = {
        "agent": name,
        "duration_ms": duration_ms,
        "ok": result.get("ok") is not False,
        "degraded": result.get("degraded") is True,
    }
    logger.info(
        json.dumps(
            {
                "event": "agent_completed",
                **telemetry,
            },
            ensure_ascii=False,
        )
    )
    return result, telemetry


def log_query_completed(
    request_id: str | None,
    duration_ms: float,
    telemetry: dict[str, Any],
) -> None:
    logger.info(
        json.dumps(
            {
                "event": "query_completed",
                "request_id": request_id,
                "duration_ms": duration_ms,
                "agents": telemetry,
            },
            ensure_ascii=False,
        )
    )
