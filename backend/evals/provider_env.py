"""Shared environment-variable-gated provider construction for the evals
that need a real AI provider call (hallucination rate, answer faithfulness).

Reads credentials from the environment only, and only at call time (never at
import time) -- same rule as the rest of Paper Trail (SECURITY.md): no
hardcoded keys, nothing persisted, nothing logged.
"""

import os
from dataclasses import dataclass

from app.providers.base import AIProvider
from app.providers.errors import InvalidConfigError
from app.providers.exceptions import ProviderNotFoundError
from app.providers.registry import build_provider

PROVIDER_ID_VAR = "EVAL_PROVIDER_ID"
API_KEY_VAR = "EVAL_PROVIDER_API_KEY"
ENDPOINT_VAR = "EVAL_PROVIDER_ENDPOINT"
MODEL_VAR = "EVAL_PROVIDER_MODEL"


class NoEvalProviderConfiguredError(Exception):
    """Raised when the environment doesn't configure a usable provider.

    Callers catch this specifically to print a clear explanation and exit
    cleanly (exit code 0) -- this is an expected, documented state (no API
    key available), not a crash.
    """


@dataclass(frozen=True)
class EvalProviderConfig:
    provider: AIProvider
    model: str | None


def load_eval_provider() -> EvalProviderConfig:
    """Builds a provider from ``EVAL_PROVIDER_ID``/``EVAL_PROVIDER_API_KEY``/
    ``EVAL_PROVIDER_ENDPOINT``/``EVAL_PROVIDER_MODEL``. Raises
    ``NoEvalProviderConfiguredError`` if no provider id is set, or if the
    configured provider can't actually be constructed from what's set (e.g.
    ``google`` with no api key) -- both are "no usable provider" cases from
    the caller's point of view.
    """
    provider_id = os.environ.get(PROVIDER_ID_VAR)
    if not provider_id:
        raise NoEvalProviderConfiguredError(
            f"{PROVIDER_ID_VAR} is not set in the environment -- no provider configured for this eval."
        )

    api_key = os.environ.get(API_KEY_VAR)
    endpoint = os.environ.get(ENDPOINT_VAR)
    model = os.environ.get(MODEL_VAR)

    try:
        provider = build_provider(provider_id, api_key=api_key, endpoint=endpoint)
    except (ProviderNotFoundError, InvalidConfigError, NotImplementedError) as exc:
        raise NoEvalProviderConfiguredError(
            f"Could not construct provider {provider_id!r} from the environment: {exc}"
        ) from exc

    return EvalProviderConfig(provider=provider, model=model)
