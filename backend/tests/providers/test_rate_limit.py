"""app.providers.rate_limit: process-wide, credential-keyed throttling used
by NVIDIA NIM's 40 RPM free-tier cap (openai_compatible.py::_throttle)."""

import pytest

from app.providers.rate_limit import acquire_rate_limit, reset_for_tests


async def test_second_call_over_budget_waits_for_the_window(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_for_tests()
    clock = {"t": 0.0}
    monkeypatch.setattr("app.providers.rate_limit.time.monotonic", lambda: clock["t"])

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["t"] += seconds

    monkeypatch.setattr("app.providers.rate_limit.asyncio.sleep", fake_sleep)

    await acquire_rate_limit("https://api.example", "key-a", limit=1)
    await acquire_rate_limit("https://api.example", "key-a", limit=1)

    assert sleeps == [pytest.approx(60.0)]


async def test_different_credentials_get_independent_budgets(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_for_tests()
    monkeypatch.setattr("app.providers.rate_limit.time.monotonic", lambda: 0.0)

    async def fail_sleep(_seconds: float) -> None:
        raise AssertionError("should not need to wait: different credential, fresh budget")

    monkeypatch.setattr("app.providers.rate_limit.asyncio.sleep", fail_sleep)

    await acquire_rate_limit("https://api.example", "key-a", limit=1)
    await acquire_rate_limit("https://api.example", "key-b", limit=1)  # distinct bucket, no wait
