"""Integration tests for ``app.evidence.service.generate_implementation_plan``/
``get_implementation_plan`` -- real Postgres persistence (TESTING.md: not
mocks of our own persistence layer), fake AI provider (mock the external
boundary only). Covers claim-linked persistence, sanitization, the
fabricated-claim-id rejection path, and optional linked-repository README
enrichment degrading gracefully when the README is unavailable.
"""

import re
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.coderesearch.exceptions import GithubNotFoundError
from app.evidence.exceptions import (
    EvidenceNotFoundError,
    ImplementationPlanNotFoundError,
    SectionReferencesUnknownClaimError,
)
from app.evidence.schemas import (
    ClaimExtraction,
    ClaimsExtractionOutput,
    GeneratedSectionDraft,
    GeneratedSectionsOutput,
    GlossaryExtractionOutput,
    MetricsExtractionOutput,
    NarrativeExtraction,
    SourceRefExtraction,
    StageConfig,
)
from app.evidence.service import generate_implementation_plan, get_implementation_plan, run_analysis
from app.models.claim import ClaimKind
from app.models.repository import Repository
from app.providers.base import ModelInfo
from app.providers.errors import NotSupportedError
from app.providers.ping import _PingResponse
from tests.evidence.conftest import make_parsed_paper

_EVIDENCE_STAGE = {"evidence": StageConfig(provider_id="google", api_key="fake-key", model="fake-model")}

PAGE_1_TEXT = (
    "We propose a new attention mechanism that improves translation "
    "quality by 10% over the previous baseline on the WMT 2014 task."
)


def _extraction_responses() -> dict[type, object]:
    return {
        _PingResponse: _PingResponse(ok=True),
        ClaimsExtractionOutput: ClaimsExtractionOutput(
            claims=[
                ClaimExtraction(
                    statement="The method uses a novel attention mechanism.",
                    kind=ClaimKind.method,
                    source_refs=[SourceRefExtraction(page=1, excerpt="a new attention mechanism")],
                ),
                ClaimExtraction(
                    statement="The method improves translation quality by 10%.",
                    kind=ClaimKind.reported_result,
                    source_refs=[
                        SourceRefExtraction(
                            page=1, excerpt="improves translation quality by 10% over the previous baseline"
                        )
                    ],
                ),
            ]
        ),
        MetricsExtractionOutput: MetricsExtractionOutput(metrics=[]),
        GlossaryExtractionOutput: GlossaryExtractionOutput(terms=[]),
        NarrativeExtraction: NarrativeExtraction(
            thesis="A new attention mechanism improves translation quality.",
            plain_summary="The paper proposes an attention mechanism that improves translation.",
            research_question="Can attention improve translation quality?",
        ),
    }


_CLAIM_MARKER_RE = re.compile(r"\[CLAIM ([0-9a-f-]{36})\]")


class _PlanProvider:
    """Serves the four extraction-pass responses, and for
    ``GeneratedSectionsOutput`` synthesizes one step citing every real claim
    id it finds in the prompt's ``[CLAIM <uuid>]`` markers plus a
    ``<script>`` tag in its heading (sanitization check) -- same
    "assert real, DB-persisted ids flow through unmodified" pattern as
    ``test_service_integration.py``'s ``_SectionGeneratingProvider``.
    """

    def __init__(self, fabricate_claim_id: bool = False) -> None:
        self._extraction = _extraction_responses()
        self._fabricate = fabricate_claim_id
        self.calls: list[tuple[str, type]] = []

    async def generate(self, prompt: str, schema: type, **opts: object):  # noqa: ANN401
        self.calls.append((prompt, schema))
        if schema is GeneratedSectionsOutput:
            claim_ids = [str(uuid.uuid4())] if self._fabricate else _CLAIM_MARKER_RE.findall(prompt)
            return GeneratedSectionsOutput(
                sections=[
                    GeneratedSectionDraft(
                        heading="1. Set up <script>alert(1)</script>the pipeline",
                        body="Implement the attention mechanism described above.",
                        claim_ids=claim_ids,
                    )
                ]
            )
        return self._extraction[schema]

    def stream(self, prompt: str, schema: type, **opts: object):
        raise NotImplementedError

    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        raise NotSupportedError("unused")

    async def vision(self, image: bytes, prompt: str) -> str:
        raise NotSupportedError("unused")

    def available_models(self) -> list[ModelInfo]:
        return []


@pytest.fixture(autouse=True)
def _patch_session(monkeypatch: pytest.MonkeyPatch, db_engine: AsyncEngine) -> None:
    # run_analysis opens its own session via AsyncSessionLocal -- point it at
    # this test's per-loop engine, same pattern as
    # test_service_integration.py's _patch_provider_and_session fixture.
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr("app.evidence.service.AsyncSessionLocal", session_factory)


async def test_generate_implementation_plan_raises_evidence_not_found_without_evidence(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: _PlanProvider())
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT})

    with pytest.raises(EvidenceNotFoundError):
        await generate_implementation_plan(
            db_session, paper.id, provider_id="google", api_key="fake-key", endpoint=None, model=None
        )


async def test_generate_implementation_plan_persists_sanitized_claim_linked_steps(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: _PlanProvider())
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT})
    async for _ in run_analysis(paper.id, _EVIDENCE_STAGE):
        pass

    steps = await generate_implementation_plan(
        db_session, paper.id, provider_id="google", api_key="fake-key", endpoint=None, model=None
    )

    assert len(steps) == 1
    # <script> stripped by the same markup-sanitization pattern every other
    # generated content type goes through (service.py's _sanitize_generated_text).
    assert "<script" not in steps[0].title
    assert len(steps[0].claim_ids) == 2  # both real, DB-persisted claim ids flowed through

    fetched = await get_implementation_plan(db_session, paper.id)
    assert fetched == steps


async def test_generate_implementation_plan_rejects_fabricated_claim_id_and_persists_nothing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: _PlanProvider(fabricate_claim_id=True))
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT})
    async for _ in run_analysis(paper.id, _EVIDENCE_STAGE):
        pass

    with pytest.raises(SectionReferencesUnknownClaimError):
        await generate_implementation_plan(
            db_session, paper.id, provider_id="google", api_key="fake-key", endpoint=None, model=None
        )

    with pytest.raises(ImplementationPlanNotFoundError):
        await get_implementation_plan(db_session, paper.id)


async def test_generate_implementation_plan_degrades_gracefully_when_readme_unavailable(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A linked repository whose README fetch fails (private/deleted repo,
    GitHub outage) must not fail plan generation -- the README is
    enrichment, not a requirement."""
    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: _PlanProvider())
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT})
    async for _ in run_analysis(paper.id, _EVIDENCE_STAGE):
        pass
    db_session.add(
        Repository(
            paper_id=paper.id,
            user_id=paper.user_id,
            url="https://github.com/openai/gpt-3",
            owner="openai",
            name="gpt-3",
            source="user_linked",
            confidence=None,
        )
    )
    await db_session.commit()

    async def _raise_not_found(owner: str, repo: str, token: str | None) -> str:
        raise GithubNotFoundError("no README")

    monkeypatch.setattr("app.evidence.service.fetch_readme", _raise_not_found)

    steps = await generate_implementation_plan(
        db_session, paper.id, provider_id="google", api_key="fake-key", endpoint=None, model=None
    )

    assert len(steps) == 1


async def test_generate_implementation_plan_includes_readme_when_available(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _PlanProvider()
    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: provider)
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT})
    async for _ in run_analysis(paper.id, _EVIDENCE_STAGE):
        pass
    db_session.add(
        Repository(
            paper_id=paper.id,
            user_id=paper.user_id,
            url="https://github.com/openai/gpt-3",
            owner="openai",
            name="gpt-3",
            source="user_linked",
            confidence=None,
        )
    )
    await db_session.commit()

    async def _fake_readme(owner: str, repo: str, token: str | None) -> str:
        return "# gpt-3\nReference implementation."

    monkeypatch.setattr("app.evidence.service.fetch_readme", _fake_readme)

    await generate_implementation_plan(
        db_session, paper.id, provider_id="google", api_key="fake-key", endpoint=None, model=None
    )

    plan_prompt = next(prompt for prompt, schema in provider.calls if schema is GeneratedSectionsOutput)
    assert "Reference implementation." in plan_prompt
