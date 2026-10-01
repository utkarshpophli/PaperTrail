"""Unit tests for the Interactive learning-content generation module
(app.evidence.interactive). Fake provider (TESTING.md: mock the external AI
boundary, not our own code) -- covers successful claim_id-validated
generation, rejection of a fabricated claim_id, and the formula-specific
one-retry-then-surface path this content type adds on top of
provider.generate's own JSON-schema retry.
"""

import uuid
from collections.abc import AsyncIterator

from pydantic import BaseModel

import pytest

from app.evidence.exceptions import InteractiveFormulaInvalidError, InteractiveReferencesUnknownClaimError
from app.evidence.interactive import generate_interactives
from app.evidence.schemas import ClaimForPrompt, InteractiveDraft, InteractiveParameterDraft, InteractivesOutput
from app.models.claim import ClaimKind
from app.providers.base import ModelInfo
from app.providers.errors import NotSupportedError

_CLAIM_1 = ClaimForPrompt(
    id=uuid.uuid4(),
    kind=ClaimKind.method,
    statement="Uses a new attention mechanism.",
    excerpts=["a new attention mechanism"],
)

_PARAM = InteractiveParameterDraft(name="x", label="Input size", min=1.0, max=100.0, step=1.0, default=10.0, unit=None)


def _make_draft(formula: str = "sqrt(x)", claim_ids: list[uuid.UUID] | None = None) -> InteractiveDraft:
    return InteractiveDraft(
        title="Scaling behavior",
        description="How the result scales with input size.",
        parameters=[_PARAM],
        formula=formula,
        output_label="Result",
        claim_ids=claim_ids if claim_ids is not None else [_CLAIM_1.id],
    )


class _QueuedProvider:
    """Returns each queued ``InteractivesOutput`` in order, one per call --
    unlike the shared ``FakeProvider`` (fixed single response), this test
    needs to assert on retry behavior across two calls."""

    def __init__(self, outputs: list[InteractivesOutput]) -> None:
        self._outputs = list(outputs)
        self.calls: list[str] = []

    async def generate(self, prompt: str, schema: type[BaseModel], **opts: object) -> BaseModel:
        self.calls.append(prompt)
        return self._outputs.pop(0)

    def stream(self, prompt: str, schema: type[BaseModel], **opts: object) -> AsyncIterator[str]:
        raise NotImplementedError

    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        raise NotSupportedError("unused")

    async def vision(self, image: bytes, prompt: str) -> str:
        raise NotSupportedError("unused")

    def available_models(self) -> list[ModelInfo]:
        return []


async def test_generate_interactives_returns_validated_drafts() -> None:
    output = InteractivesOutput(interactives=[_make_draft()])
    provider = _QueuedProvider([output])

    interactives = await generate_interactives(provider, claims=[_CLAIM_1], metrics=[], model="m")

    assert interactives == output.interactives
    assert len(provider.calls) == 1


async def test_generate_interactives_rejects_unknown_claim_id() -> None:
    fabricated_id = uuid.uuid4()
    output = InteractivesOutput(interactives=[_make_draft(claim_ids=[fabricated_id])])
    provider = _QueuedProvider([output])

    with pytest.raises(InteractiveReferencesUnknownClaimError):
        await generate_interactives(provider, claims=[_CLAIM_1], metrics=[], model="m")


async def test_invalid_formula_retries_once_then_succeeds() -> None:
    bad_output = InteractivesOutput(interactives=[_make_draft(formula="x.__class__")])
    good_output = InteractivesOutput(interactives=[_make_draft(formula="sqrt(x)")])
    provider = _QueuedProvider([bad_output, good_output])

    interactives = await generate_interactives(provider, claims=[_CLAIM_1], metrics=[], model="m")

    assert interactives == good_output.interactives
    assert len(provider.calls) == 2
    assert "invalid formula" in provider.calls[1]


async def test_invalid_formula_twice_raises_typed_error() -> None:
    bad_output = InteractivesOutput(interactives=[_make_draft(formula="x.__class__")])
    provider = _QueuedProvider([bad_output, bad_output])

    with pytest.raises(InteractiveFormulaInvalidError):
        await generate_interactives(provider, claims=[_CLAIM_1], metrics=[], model="m")
    assert len(provider.calls) == 2


async def test_division_by_zero_at_default_is_treated_as_invalid_formula() -> None:
    # x's default is 10.0 (not zero) so "1 / (x - 10)" divides by zero at
    # the draft's own default parameter value -- caught by the
    # smoke-evaluation step, not just grammar validation.
    bad_output = InteractivesOutput(interactives=[_make_draft(formula="1 / (x - 10)")])
    provider = _QueuedProvider([bad_output, bad_output])

    with pytest.raises(InteractiveFormulaInvalidError):
        await generate_interactives(provider, claims=[_CLAIM_1], metrics=[], model="m")


async def test_duplicate_parameter_names_treated_as_invalid_formula() -> None:
    duplicate_params = [_PARAM, _PARAM]
    bad_draft = InteractiveDraft(
        title="Bad",
        description="d",
        parameters=duplicate_params,
        formula="x + x",
        output_label="Result",
        claim_ids=[_CLAIM_1.id],
    )
    bad_output = InteractivesOutput(interactives=[bad_draft])
    provider = _QueuedProvider([bad_output, bad_output])

    with pytest.raises(InteractiveFormulaInvalidError):
        await generate_interactives(provider, claims=[_CLAIM_1], metrics=[], model="m")
