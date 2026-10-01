"""Models cite claims by short references (C1, C2, ...), never by copying
36-character UUIDs. Confirmed live: a model copied a claim UUID with one
extra character, failed schema validation twice and killed a whole stage.

These tests drive the real structured-output path (raw JSON text in,
``generate_structured`` validation, one repair retry), not pre-built models.
"""

import json
import re
import uuid
from collections.abc import AsyncIterator

import pytest
from pydantic import BaseModel

from app.evidence.claim_refs import rewrite_claim_markers
from app.evidence.report import generate_report_sections
from app.evidence.schemas import ClaimForPrompt
from app.models.claim import ClaimKind
from app.providers.base import ModelInfo
from app.providers.errors import StructuredOutputError
from app.providers.structured_output import generate_structured

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class RawJsonProvider:
    """Answers with raw model text and validates it exactly like a real
    adapter does (``generate_structured``)."""

    def __init__(self, *raw_replies: str) -> None:
        self._replies = list(raw_replies)
        self.prompts: list[str] = []

    async def generate(
        self, prompt: str, schema: type[BaseModel], **opts: object
    ) -> BaseModel:
        async def call(p: str) -> str:
            self.prompts.append(p)
            return self._replies.pop(0)

        return await generate_structured(schema, call, prompt)

    def stream(
        self, prompt: str, schema: type[BaseModel], **opts: object
    ) -> AsyncIterator[str]:
        raise NotImplementedError

    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        raise NotImplementedError

    async def vision(self, image: bytes, prompt: str) -> str:
        raise NotImplementedError

    def available_models(self) -> list[ModelInfo]:
        return []


def _claims() -> list[ClaimForPrompt]:
    return [
        ClaimForPrompt(
            id=uuid.uuid4(),
            kind=ClaimKind.method,
            statement="Six layers.",
            excerpts=["N = 6"],
        ),
        ClaimForPrompt(
            id=uuid.uuid4(),
            kind=ClaimKind.method,
            statement="Twelve hours.",
            excerpts=["12 hours"],
        ),
    ]


def _sections(*refs: str) -> str:
    return json.dumps(
        {
            "sections": [
                {
                    "heading": "Training",
                    "body": "Trained for 12 hours.",
                    "claim_ids": list(refs),
                }
            ]
        }
    )


def test_markers_become_short_refs_in_first_appearance_order() -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    prompt = f"[CLAIM {second}] b\n[CLAIM {first}] a\nagain [CLAIM {second}]"

    rewritten, refs = rewrite_claim_markers(prompt)

    assert rewritten == "[CLAIM C1] b\n[CLAIM C2] a\nagain [CLAIM C1]"
    assert refs == {"C1": second, "C2": first}


async def test_model_sees_no_uuids_and_its_refs_resolve_to_real_claim_ids() -> None:
    claims = _claims()
    provider = RawJsonProvider(_sections("C2"))

    sections = await generate_report_sections(
        provider,
        thesis="t",
        plain_summary="s",
        research_question="q",
        claims=claims,
        model="m",
    )

    assert sections[0].claim_ids == [claims[1].id]
    assert "[CLAIM C1]" in provider.prompts[0]
    assert not UUID_RE.search(provider.prompts[0])


async def test_unknown_ref_gets_one_repair_retry_with_the_reason() -> None:
    claims = _claims()
    provider = RawJsonProvider(_sections("C9"), _sections("C1"))

    sections = await generate_report_sections(
        provider,
        thesis="t",
        plain_summary="s",
        research_question="q",
        claims=claims,
        model="m",
    )

    assert sections[0].claim_ids == [claims[0].id]
    assert "C9" in provider.prompts[1]


async def test_unknown_ref_twice_is_never_accepted() -> None:
    provider = RawJsonProvider(_sections("C9"), _sections("C9"))

    with pytest.raises(StructuredOutputError):
        await generate_report_sections(
            provider,
            thesis="t",
            plain_summary="s",
            research_question="q",
            claims=_claims(),
            model="m",
        )
