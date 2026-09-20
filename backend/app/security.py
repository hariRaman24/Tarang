"""Small-process API protection primitives.

This is intentionally process-local for the current single-container demo.
Production multi-worker deployments should move the limiter state to Redis.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = max(1, limit)
        self.window_seconds = max(1, window_seconds)
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, now: float | None = None) -> tuple[bool, int]:
        current = time.monotonic() if now is None else now
        timestamps = self._requests[key]
        cutoff = current - self.window_seconds
        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()
        if len(timestamps) >= self.limit:
            retry_after = max(
                1,
                int(timestamps[0] + self.window_seconds - current),
            )
            return False, retry_after
        timestamps.append(current)
        return True, 0

    def clear(self) -> None:
        self._requests.clear()
