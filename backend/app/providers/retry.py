"""Retry and deadline policy shared by the HTTP provider adapters
(OpenAI-compatible family, Anthropic).

A 429/502/503/504 or a transport-level timeout/connection error is retried
in-process before surfacing as an error. Confirmed live against NVIDIA NIM:
its gateway 504s any request still queued (no first byte) after ~300s, and
under load a request's queue wait alone is 3-5 min, so a single attempt is
close to a coin flip -- two attempts failed a whole GLM-5 analysis. Total
time stays bounded by ``within_deadline`` (provider_operation_timeout_seconds),
not by the attempt count.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

from app.core.logging import get_logger
from app.providers.errors import ProviderUnavailableError

logger = get_logger(__name__)

_T = TypeVar("_T")

MAX_ATTEMPTS = 4
_RETRYABLE_STATUS = frozenset({429, 502, 503, 504, 529})  # 529: Anthropic "overloaded"


def should_retry_status(status_code: int, attempt: int) -> bool:
    retry = status_code in _RETRYABLE_STATUS and attempt < MAX_ATTEMPTS - 1
    if retry:
        logger.warning("provider_request_retrying status=%s attempt=%d", status_code, attempt + 1)
    return retry


def retry_delay(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return max(float(retry_after), 0.0)
        except ValueError:
            pass
    return float(2**attempt)  # 1s, 2s, 4s


async def retry_transient_exception(exc: httpx.HTTPError, attempt: int, url: str, label: str) -> int:
    """Sleeps and returns the next attempt number, or raises
    ``ProviderUnavailableError`` once ``MAX_ATTEMPTS`` is spent."""
    kind = "timed out" if isinstance(exc, httpx.TimeoutException) else f"failed: {type(exc).__name__}"
    if attempt >= MAX_ATTEMPTS - 1:
        raise ProviderUnavailableError(f"{label} to {url} {kind}") from exc
    logger.warning("provider_request_retrying error=%s attempt=%d", kind, attempt + 1)
    await asyncio.sleep(float(2**attempt))
    return attempt + 1


async def send_with_retry(send: Callable[[], Awaitable[httpx.Response]], url: str) -> httpx.Response:
    """Retry loop for a plain (non-streaming) request. ``send`` is called
    fresh on every attempt."""
    attempt = 0
    while True:
        try:
            response = await send()
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            attempt = await retry_transient_exception(exc, attempt, url, "Request")
            continue
        if should_retry_status(response.status_code, attempt):
            await response.aread()
            await asyncio.sleep(retry_delay(response, attempt))
            attempt += 1
            continue
        return response


async def within_deadline(provider: str, operation: str, seconds: float, work: Awaitable[_T]) -> _T:
    """Hard upper bound on one whole public operation (generate/embed),
    including HTTP retries and the one structured-output repair attempt.
    Unlike the HTTPX read timeout, this bounds total elapsed time even if
    the upstream sends keepalive bytes without ever completing a usable
    response (confirmed live against NVIDIA NIM: a 33+ minute hang with
    no success, error, or retry -- see docs/NIM_HANG_FIX.md). Never
    catches ``asyncio.CancelledError``: caller cancellation and server
    shutdown must keep propagating as cancellation, not a provider error.
    """
    try:
        async with asyncio.timeout(seconds):
            return await work
    except TimeoutError as exc:
        logger.warning(
            "provider_operation_timed_out provider=%s operation=%s deadline_seconds=%s", provider, operation, seconds
        )
        raise ProviderUnavailableError(f"{operation.capitalize()} did not complete within {seconds:.0f}s") from exc
