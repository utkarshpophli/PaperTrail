"""Structured generation plus a claim-id check, with one repair retry.

A schema can't know which claim ids belong to this paper, so derivation
modules check ``claim_ids`` after ``provider.generate``. Before this, one
hallucinated id raised immediately and the model never got the feedback
loop every other validation failure gets. Confirmed live: a single bad id
in one Application Guide section discarded a whole visual stage.

Same rule as ``app.providers.structured_output``: one retry with the
specific error fed back, then a second failure surfaces. A hallucinated id
is still never persisted.
"""

from collections.abc import Callable
from typing import TypeVar, cast

from pydantic import BaseModel

from app.evidence.exceptions import (
    DerivationReferencesUnknownClaimError,
    QuizReferencesUnknownClaimError,
    SectionReferencesUnknownClaimError,
)
from app.providers.base import AIProvider

_T = TypeVar("_T", bound=BaseModel)

_UNKNOWN_CLAIM_ERRORS = (
    SectionReferencesUnknownClaimError,
    QuizReferencesUnknownClaimError,
    DerivationReferencesUnknownClaimError,
)


async def generate_with_claim_check(
    provider: AIProvider, prompt: str, schema: type[_T], *, model: str, check: Callable[[_T], None]
) -> _T:
    """``check`` raises one of the unknown-claim errors on a bad id."""
    output = cast(_T, await provider.generate(prompt, schema, model=model))
    try:
        check(output)
        return output
    except _UNKNOWN_CLAIM_ERRORS as exc:
        repair_prompt = (
            f"{prompt}\n\n"
            f"Your previous response was rejected: {exc.message}\n"
            "Return ONLY corrected JSON matching the schema. Every claim_id must be copied "
            "exactly from the claims listed above; never invent or alter one."
        )
    retry = cast(_T, await provider.generate(repair_prompt, schema, model=model))
    check(retry)
    return retry
