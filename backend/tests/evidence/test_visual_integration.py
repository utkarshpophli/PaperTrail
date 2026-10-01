"""Integration tests for the "visual" stage of ``run_analysis`` (real
Postgres, fake AI provider -- same conventions as
``test_service_integration.py``, which owns the shared fixtures reused here).

Covers: visual stage requires existing evidence, a standalone visual run
after a prior evidence run, a visual failure not undoing evidence/technical/
report, sanitization of a script-injection payload in a quiz explanation and
a derivation step explanation, and the visual stage's own log calls never
leaking a submitted API key (this phase's explicit "extend the log-safety
test pattern" instruction).
"""

import logging
import re
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.evidence.exceptions import EvidenceNotFoundError, LearningNotFoundError, StoryNotFoundError
from app.evidence.schemas import (
    DerivationDraft,
    DerivationsOutput,
    DerivationStepDraft,
    GeneratedSectionDraft,
    GeneratedSectionsOutput,
    InteractiveDraft,
    InteractiveParameterDraft,
    InteractivesOutput,
    QuizQuestionDraft,
    QuizQuestionsOutput,
    StageConfig,
)
from app.evidence.figure_linking import FigureLinksOutput
from app.evidence.story_visuals import StorySpecOutput
from app.evidence.service import get_learning, get_report, get_story, run_analysis
from app.models.page import Page
from app.providers.base import ModelInfo
from app.providers.errors import NotSupportedError, StructuredOutputError
from tests.evidence.conftest import make_parsed_paper
from tests.evidence.story_fixtures import make_story
from tests.evidence.test_service_integration import (
    _CLAIM_MARKER_RE,
    _EVIDENCE_STAGE,
    _REPORT_STAGE,
    PAGE_1_TEXT,
    PAGE_2_TEXT,
    _extraction_responses,
)

_VISUAL_STAGE = {"visual": StageConfig(provider_id="google", api_key="fake-key", model="fake-model")}


_CLAIM_KIND_RE = re.compile(r"\[CLAIM ([0-9a-f-]{36})\] \(kind=([a-z-]+)")


class _VisualGeneratingProvider:
    """Serves the four extraction-pass responses, and for each visual-stage
    output schema synthesizes content that cites every claim id it finds in
    that call's own prompt -- same "assert real, DB-persisted claim ids flow
    through and back out validated" rationale as
    ``test_service_integration._SectionGeneratingProvider``.
    """

    def __init__(self) -> None:
        self._extraction = _extraction_responses()
        self.calls: list[tuple[str, type]] = []

    async def generate(self, prompt: str, schema: type, **opts: object):  # noqa: ANN401
        self.calls.append((prompt, schema))
        claim_ids = _CLAIM_MARKER_RE.findall(prompt)
        if schema is StorySpecOutput:
            kinds = dict((cid, kind) for cid, kind in _CLAIM_KIND_RE.findall(prompt))
            method_id = next(cid for cid, kind in kinds.items() if kind == "method")
            limitation_id = next(cid for cid, kind in kinds.items() if kind == "limitation")
            return make_story(method_id=uuid.UUID(method_id), limitation_id=uuid.UUID(limitation_id))
        if schema is GeneratedSectionsOutput:
            return GeneratedSectionsOutput(
                sections=[GeneratedSectionDraft(heading="Overview", body="Synthesized body.", claim_ids=claim_ids)]
            )
        if schema is QuizQuestionsOutput:
            return QuizQuestionsOutput(
                questions=[
                    QuizQuestionDraft(
                        question="What did the paper show?",
                        correct_answer="See explanation",
                        explanation="Grounded explanation.<script>alert(1)</script>",
                        claim_ids=claim_ids,
                    )
                ]
            )
        if schema is DerivationsOutput:
            return DerivationsOutput(
                derivations=[
                    DerivationDraft(
                        title="Key derivation",
                        steps=[
                            DerivationStepDraft(
                                explanation="Step explanation.<script>alert(1)</script>",
                                formula="y = f(x)",
                                claim_ids=claim_ids,
                            )
                        ],
                    )
                ]
            )
        if schema is InteractivesOutput:
            return InteractivesOutput(
                interactives=[
                    InteractiveDraft(
                        title="Scaling behavior",
                        description="Illustrative scaling playground.<script>alert(1)</script>",
                        parameters=[
                            InteractiveParameterDraft(
                                name="x", label="Input size", min=1.0, max=100.0, step=1.0, default=10.0
                            )
                        ],
                        formula="sqrt(x)",
                        output_label="Result",
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


class _VisualFailingProvider:
    """Succeeds on the four extraction passes, but always fails structured
    output for the visual stage's schemas -- used to prove the visual
    stage's failure never undoes an earlier stage's already-committed work.
    """

    def __init__(self) -> None:
        self._extraction = _extraction_responses()

    async def generate(self, prompt: str, schema: type, **opts: object):  # noqa: ANN401
        if schema in (StorySpecOutput, GeneratedSectionsOutput, QuizQuestionsOutput, DerivationsOutput, InteractivesOutput):
            raise StructuredOutputError("schema validation failed twice")
        return self._extraction[schema]

    def stream(self, prompt: str, schema: type, **opts: object):
        raise NotImplementedError

    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        raise NotSupportedError("unused")

    async def vision(self, image: bytes, prompt: str) -> str:
        raise NotSupportedError("unused")

    def available_models(self) -> list[ModelInfo]:
        return []


class _FigureLinkFailingProvider(_VisualGeneratingProvider):
    """Same as ``_VisualGeneratingProvider`` except figure linking always
    fails -- used to prove that failure surfaces as a non-blocking warning
    event, not a silently swallowed server-only log line."""

    async def generate(self, prompt: str, schema: type, **opts: object):  # noqa: ANN401
        if schema is FigureLinksOutput:
            raise StructuredOutputError("figure linking schema validation failed twice")
        return await super().generate(prompt, schema, **opts)


class _VisualKeyLeakingProvider:
    """Succeeds on extraction, but fails every visual-stage schema with an
    exception message embedding a secret -- proves the visual stage's own
    ``logger.warning`` call never lets a submitted credential reach a log
    record (security-review pattern from Phase 4a, extended here per this
    phase's explicit instruction to cover the new stage's log call sites)."""

    def __init__(self, secret: str) -> None:
        self._extraction = _extraction_responses()
        self._secret = secret

    async def generate(self, prompt: str, schema: type, **opts: object):  # noqa: ANN401
        if schema in (StorySpecOutput, GeneratedSectionsOutput, QuizQuestionsOutput, DerivationsOutput, InteractivesOutput):
            raise StructuredOutputError(f"generation failed using key {self._secret}")
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
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr("app.evidence.service.AsyncSessionLocal", session_factory)


async def test_run_analysis_raises_evidence_not_found_for_visual_without_evidence(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT})
    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: _VisualGeneratingProvider())

    with pytest.raises(EvidenceNotFoundError):
        async for _ in run_analysis(paper.id, _VISUAL_STAGE):
            pass


async def test_run_analysis_runs_visual_standalone_after_a_prior_evidence_run(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: _VisualGeneratingProvider())
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT, 2: PAGE_2_TEXT})
    async for _ in run_analysis(paper.id, _EVIDENCE_STAGE):
        pass

    events = [event async for event in run_analysis(paper.id, _VISUAL_STAGE)]

    assert events[-1].type == "done"
    assert events[-1].stage == "visual"
    assert any(event.type == "error" for event in events) is False

    story_sections = await get_story(db_session, paper.id)
    learning = await get_learning(db_session, paper.id)
    assert len(story_sections) == 5
    assert story_sections[0].data is not None  # typed visual persisted alongside the legacy fields
    assert story_sections[0].claim_ids  # real, DB-persisted claim ids, not fabricated
    assert len(learning.primer) == 1
    assert len(learning.application_guide) == 1
    assert len(learning.quiz) == 1
    assert len(learning.derivations) == 1
    assert len(learning.interactives) == 1
    assert learning.interactives[0].claim_ids  # real, DB-persisted claim ids, not fabricated
    assert learning.interactives[0].formula == "sqrt(x)"

    # Sanitization (this phase's task brief): a <script> payload is stripped
    # from a quiz explanation and a derivation step explanation, not just
    # section bodies -- and from an interactive's description, but NOT from
    # its formula (formula is validated by the grammar, never regex-sanitized).
    assert "<script" not in learning.quiz[0].explanation
    assert "<script" not in learning.derivations[0].steps[0].explanation
    assert "<script" not in learning.interactives[0].description


async def test_run_analysis_runs_evidence_and_visual_in_one_call(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: _VisualGeneratingProvider())
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT, 2: PAGE_2_TEXT})

    stages = {**_EVIDENCE_STAGE, **_VISUAL_STAGE}
    events = [event async for event in run_analysis(paper.id, stages)]

    assert [e.stage for e in events if e.type == "done"] == ["evidence", "visual"]
    assert any(event.type == "error" for event in events) is False


async def test_run_analysis_visual_failure_does_not_undo_committed_report(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: _VisualGeneratingProvider())
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT, 2: PAGE_2_TEXT})
    async for _ in run_analysis(paper.id, _EVIDENCE_STAGE):
        pass
    async for _ in run_analysis(paper.id, _REPORT_STAGE):
        pass

    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: _VisualFailingProvider())
    events = [event async for event in run_analysis(paper.id, _VISUAL_STAGE)]

    assert any(e.type == "error" and e.stage == "visual" for e in events)

    # Report's own earlier commit is untouched by visual's later failure.
    report_sections = await get_report(db_session, paper.id)
    assert len(report_sections) == 1

    # Nothing was persisted for the failed visual stage.
    with pytest.raises(StoryNotFoundError):
        await get_story(db_session, paper.id)
    with pytest.raises(LearningNotFoundError):
        await get_learning(db_session, paper.id)


async def test_run_analysis_figure_linking_failure_emits_warning_but_stage_still_completes(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: _VisualGeneratingProvider())
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT, 2: PAGE_2_TEXT})
    async for _ in run_analysis(paper.id, _EVIDENCE_STAGE):
        pass

    page = (await db_session.scalars(select(Page).where(Page.paper_id == paper.id, Page.page_number == 1))).one()
    page.figures = [{"image_path": "fig1.png", "page": 1, "caption": "Figure 1: Accuracy over time."}]
    await db_session.commit()

    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: _FigureLinkFailingProvider())
    events = [event async for event in run_analysis(paper.id, _VISUAL_STAGE)]

    assert events[-1].type == "done"
    assert events[-1].stage == "visual"
    warnings = [e for e in events if e.type == "warning"]
    assert len(warnings) == 1
    assert warnings[0].stage == "visual"
    assert "Figure linking failed" in warnings[0].message
    assert not any(e.type == "error" for e in events)


async def test_visual_stage_failure_never_logs_submitted_api_key(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret_key = "sk-super-secret-visual-13579"
    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: _VisualGeneratingProvider())
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT, 2: PAGE_2_TEXT})
    async for _ in run_analysis(paper.id, _EVIDENCE_STAGE):
        pass

    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: _VisualKeyLeakingProvider(secret_key))
    leaking_stage = {"visual": StageConfig(provider_id="google", api_key=secret_key, model="fake-model")}

    with caplog.at_level(logging.DEBUG, logger="app.evidence.service"):
        events = [event async for event in run_analysis(paper.id, leaking_stage)]

    assert any(e.type == "error" and e.stage == "visual" for e in events)
    for record in caplog.records:
        assert secret_key not in record.getMessage()
