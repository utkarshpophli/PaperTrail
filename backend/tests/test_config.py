"""Settings invariants that aren't covered by any single provider test."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _settings(**overrides: object) -> Settings:
    return Settings(database_url="postgresql://x/y", jwt_secret_key="k", **overrides)


def test_operation_timeout_must_exceed_read_timeout() -> None:
    with pytest.raises(ValidationError, match="provider_operation_timeout_seconds"):
        _settings(provider_read_timeout_seconds=600.0, provider_operation_timeout_seconds=600.0)
    with pytest.raises(ValidationError, match="provider_operation_timeout_seconds"):
        _settings(provider_read_timeout_seconds=600.0, provider_operation_timeout_seconds=100.0)


def test_operation_timeout_greater_than_read_timeout_is_accepted() -> None:
    settings = _settings(provider_read_timeout_seconds=600.0, provider_operation_timeout_seconds=900.0)
    assert settings.provider_operation_timeout_seconds == 900.0


def test_defaults_satisfy_the_invariant() -> None:
    settings = _settings()
    assert settings.provider_operation_timeout_seconds > settings.provider_read_timeout_seconds
