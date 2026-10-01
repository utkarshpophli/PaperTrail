"""Integration tests for the Research Assistant service entrypoint
(app.evidence.service.run_assistant) -- real Postgres (TESTING.md: test
against a real database, not mocks of our own persistence layer), fake AI
provider. Extends test_service_integration.py's fixtures/conventions.

Covers `understand` and `compare` end-to-end: a real evidence stage run,
real DB-persisted claim ids flowing through retrieval and back out
validated in the final `AssistantResponse`, and `compare`'s cross-paper
claim id resolution (both papers' claims appear in the prompt, both papers'
claim ids are accepted).
"""

import re

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.evidence.exceptions import EvidenceNotFoundError
from app.evidence.schemas import AssistantAnswerOutput
from app.evidence.service import get_evidence, run_analysis, run_assistant
from app.providers.base import ModelInfo
from tests.evidence.conftest import make_parsed_paper
from tests.evidence.test_service_integration import PAGE_1_TEXT, PAGE_2_TEXT, _EVIDENCE_STAGE, _extraction_responses

_CLAIM_MARKER_RE = re.compile(r"\[CLAIM (C\d+)\]")


class _AssistantAnsweringProvider:
    """Serves the four extraction-pass responses like ``FakeProvider``, and
    for ``AssistantAnswerOutput`` synthesizes an answer citing every real
    claim id it finds in that call's own prompt -- same "assert real,
    DB-persisted claim ids flow through and back out validated" rationale as
    ``test_service_integration._SectionGeneratingProvider``.
    """

    def __init__(self) -> None:
        self._extraction = _extraction_responses()
        self.calls: list[tuple[str, type]] = []

    async def generate(self, prompt: str, schema: type, **opts: object):  # noqa: ANN401
        self.calls.append((prompt, schema))
        if schema is AssistantAnswerOutput:
            claim_ids = _CLAIM_MARKER_RE.findall(prompt)
            return AssistantAnswerOutput(answer="Grounded answer.", claim_ids=claim_ids)
        return self._extraction[schema]

    def stream(self, prompt: str, schema: type, **opts: object):
        raise NotImplementedError

    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        raise NotImplementedError

    async def vision(self, image: bytes, prompt: str) -> str:
        raise NotImplementedError

    def available_models(self) -> list[ModelInfo]:
        return []


@pytest.fixture(autouse=True)
def _patch_session(monkeypatch: pytest.MonkeyPatch, db_engine: AsyncEngine) -> None:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr("app.evidence.service.AsyncSessionLocal", session_factory)


async def test_run_assistant_understand_grounds_answer_in_real_claim_ids(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: _AssistantAnsweringProvider())
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT, 2: PAGE_2_TEXT})
    async for _ in run_analysis(paper.id, _EVIDENCE_STAGE):
        pass

    events = [
        event
        async for event in run_assistant(paper.id, "understand", None, None, "google", "fake-key", None, None)
    ]

    assert events[-1].type == "done"
    assert events[-1].stage == "assistant"
    assert events[-1].data["answer"] == "Grounded answer."

    evidence = await get_evidence(db_session, paper.id)
    real_claim_ids = {str(c.id) for c in evidence.claims}
    cited = set(events[-1].data["claim_ids"])
    assert cited  # actually cited something
    assert cited.issubset(real_claim_ids)  # never an id that isn't a real, persisted claim


async def test_run_assistant_sanitizes_script_tags_out_of_answer(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _ScriptInjectingProvider(_AssistantAnsweringProvider):
        async def generate(self, prompt: str, schema: type, **opts: object):  # noqa: ANN401
            if schema is AssistantAnswerOutput:
                self.calls.append((prompt, schema))
                return AssistantAnswerOutput(answer="Safe text.<script>alert(1)</script>", claim_ids=[])
            return await super().generate(prompt, schema, **opts)

    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: _ScriptInjectingProvider())
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT, 2: PAGE_2_TEXT})
    async for _ in run_analysis(paper.id, _EVIDENCE_STAGE):
        pass

    events = [
        event
        async for event in run_assistant(paper.id, "understand", None, None, "google", "fake-key", None, None)
    ]

    assert events[-1].type == "done"
    assert "<script" not in events[-1].data["answer"]
    assert "Safe text." in events[-1].data["answer"]


async def test_run_assistant_raises_evidence_not_found_without_prior_analysis(db_session: AsyncSession) -> None:
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT})

    with pytest.raises(EvidenceNotFoundError):
        async for _ in run_assistant(paper.id, "understand", None, None, "google", "fake-key", None, None):
            pass


async def test_run_assistant_compare_pulls_evidence_from_both_papers(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _AssistantAnsweringProvider()
    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: provider)

    primary = await make_parsed_paper(db_session, {1: PAGE_1_TEXT, 2: PAGE_2_TEXT})
    async for _ in run_analysis(primary.id, _EVIDENCE_STAGE):
        pass
    other = await make_parsed_paper(db_session, {1: PAGE_1_TEXT, 2: PAGE_2_TEXT})
    async for _ in run_analysis(other.id, _EVIDENCE_STAGE):
        pass

    events = [
        event
        async for event in run_assistant(
            primary.id, "compare", None, [other.id], "google", "fake-key", None, None
        )
    ]

    assert events[-1].type == "done"

    primary_claim_ids = {str(c.id) for c in (await get_evidence(db_session, primary.id)).claims}
    other_claim_ids = {str(c.id) for c in (await get_evidence(db_session, other.id)).claims}
    cited = set(events[-1].data["claim_ids"])
    assert cited  # actually cited something
    assert cited.issubset(primary_claim_ids | other_claim_ids)
    assert cited & other_claim_ids  # the comparison actually drew on the *other* paper too, not just the primary

    # The prompt itself included both papers' data (not just the primary's).
    compare_prompt = next(prompt for prompt, schema in provider.calls if schema is AssistantAnswerOutput)
    assert f"[PAPER {primary.id}" in compare_prompt
    assert f"[PAPER {other.id}" in compare_prompt


async def test_run_assistant_compare_raises_evidence_not_found_for_unanalyzed_compare_target(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: _AssistantAnsweringProvider())
    primary = await make_parsed_paper(db_session, {1: PAGE_1_TEXT, 2: PAGE_2_TEXT})
    async for _ in run_analysis(primary.id, _EVIDENCE_STAGE):
        pass
    other = await make_parsed_paper(db_session, {1: PAGE_1_TEXT})  # never analyzed -- no Evidence row

    with pytest.raises(EvidenceNotFoundError):
        async for _ in run_assistant(
            primary.id, "compare", None, [other.id], "google", "fake-key", None, None
        ):
            pass
