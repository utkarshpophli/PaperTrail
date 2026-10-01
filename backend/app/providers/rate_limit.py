"""Process-wide request-rate limiter, keyed by (base_url, credential).

``registry.build_provider`` constructs a fresh provider instance per pipeline
stage (evidence/technical/report/visual each get their own), but a documented
per-account RPM cap (e.g. NVIDIA NIM's free-tier 40 RPM) is per-account, not
per-object -- a per-instance limiter would let four stages each burst their
own 40 RPM against the same account. Keying by credential also keeps two
different accounts on the same provider from sharing one budget.
"""

import asyncio
import time
from collections import deque

_buckets: dict[tuple[str, str], "_TokenBucket"] = {}
_buckets_lock = asyncio.Lock()


class _TokenBucket:
    """Sliding-window limiter: at most ``limit`` acquisitions in any
    trailing ``window_seconds``. A caller over budget awaits until the
    oldest acquisition in the window ages out."""

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self._limit = limit
        self._window = window_seconds
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._timestamps and now - self._timestamps[0] >= self._window:
                    self._timestamps.popleft()
                if len(self._timestamps) < self._limit:
                    self._timestamps.append(now)
                    return
                await asyncio.sleep(self._window - (now - self._timestamps[0]))


async def acquire_rate_limit(base_url: str, credential: str, limit: int) -> None:
    """Blocks until the (base_url, credential) bucket has room for one more
    request this minute. No-op is the caller's responsibility (skip calling
    this when ``limit`` is None) -- there is no unlimited bucket here."""
    key = (base_url, credential)
    bucket = _buckets.get(key)
    if bucket is None:
        async with _buckets_lock:
            bucket = _buckets.get(key)
            if bucket is None:
                bucket = _TokenBucket(limit)
                _buckets[key] = bucket
    await bucket.acquire()


def reset_for_tests() -> None:
    """Test-only: this registry is process-wide by design (that's the whole
    point, see module docstring), so it must be cleared between tests or
    unrelated tests sharing a (base_url, credential) -- e.g. every
    NvidiaNimProvider test fixture uses the same fake key -- would burn down
    each other's budget and block on a real sleep."""
    _buckets.clear()
