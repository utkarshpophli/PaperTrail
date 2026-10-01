"""Integration tests for the Evidence Engine's service layer -- real
Postgres (TESTING.md: test evidence merging against a real database, not
mocks of our own persistence layer), fake AI provider (mock the external
boundary only).

Covers: evidence merging across the four parallel extraction passes landing
correctly in the DB, the verifier running against real persisted Page text,
``get_evidence``'s derived methods/findings/limitations views, and
``reverify_claim`` re-running the verifier (no LLM) after a page's text
changes.
"""

import logging
import re
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.evidence.exceptions import EvidenceNotFoundError, PaperNotParsedError, TechnicalAppendixNotFoundError
from app.evidence.schemas import (
    ClaimExtraction,
    ClaimsExtractionOutput,
    GeneratedSectionDraft,
    GeneratedSectionsOutput,
    GlossaryExtractionOutput,
    GlossaryTermExtraction,
    MetricExtraction,
    MetricsExtractionOutput,
    NarrativeExtraction,
    SourceRefExtraction,
    StageConfig,
)
from app.evidence.service import get_evidence, get_report, get_technical_appendix, reverify_claim, run_analysis
from app.models.claim import ClaimKind, VerificationStatus
from app.models.page import Page
from app.models.paper import Paper, ParseStatus
from app.providers.base import ModelInfo
from app.providers.errors import AuthenticationError, NotSupportedError, StructuredOutputError
from app.providers.ping import _PingResponse
from tests.evidence.conftest import make_parsed_paper
from tests.evidence.fake_provider import FakeProvider

_EVIDENCE_STAGE = {"evidence": StageConfig(provider_id="google", api_key="fake-key", model="fake-model")}
_TECHNICAL_STAGE = {"technical": StageConfig(provider_id="google", api_key="fake-key", model="fake-model")}
_REPORT_STAGE = {"report": StageConfig(provider_id="google", api_key="fake-key", model="fake-model")}

PAGE_1_TEXT = (
    "We propose a new attention mechanism that improves translation "
    "quality by 10% over the previous baseline on the WMT 2014 task."
)
PAGE_2_TEXT = "A known limitation is that training requires very large compute budgets."


def _extraction_responses() -> dict[type, object]:
    return {
        # run_analysis's preflight liveness ping (app.providers.ping) always
        # requests this schema first -- every provider double built on this
        # dict needs to answer it before its "real" schema handling runs.
        _PingResponse: _PingResponse(ok=True),
        ClaimsExtractionOutput: ClaimsExtractionOutput(
            claims=[
                ClaimExtraction(
                    statement="The method improves translation quality by 10%.",
                    kind=ClaimKind.reported_result,
                    source_refs=[
                        SourceRefExtraction(
                            page=1, excerpt="improves translation quality by 10% over the previous baseline"
                        )
                    ],
                ),
                ClaimExtraction(
                    statement="The method uses a novel attention mechanism.",
                    kind=ClaimKind.method,
                    source_refs=[SourceRefExtraction(page=1, excerpt="a new attention mechanism")],
                ),
                ClaimExtraction(
                    statement="Training requires very large compute budgets.",
                    kind=ClaimKind.limitation,
                    source_refs=[SourceRefExtraction(page=2, excerpt="training requires very large compute budgets")],
                ),
                ClaimExtraction(
                    statement="The authors release a browser extension for annotating PDFs.",
                    kind=ClaimKind.reported_result,
                    # Fabricated -- not present anywhere in either page. This
                    # is the "evidence merging must still let the verifier
                    # catch a bad claim from one of the four passes" case.
                    source_refs=[SourceRefExtraction(page=1, excerpt="a browser extension for annotating PDFs")],
                ),
            ]
        ),
        MetricsExtractionOutput: MetricsExtractionOutput(
            metrics=[
                MetricExtraction(
                    label="Translation quality improvement",
                    value="10",
                    display_value="10%",
                    unit="%",
                    source_page=1,
                    source_excerpt="improves translation quality by 10%",
                )
            ]
        ),
        GlossaryExtractionOutput: GlossaryExtractionOutput(
            terms=[
                GlossaryTermExtraction(
                    term="Attention mechanism",
                    definition="General term (not defined in this paper): a way for a model to weigh input parts.",
                )
            ]
        ),
        NarrativeExtraction: NarrativeExtraction(
            thesis="A new attention mechanism improves translation quality.",
            plain_summary="The paper proposes an attention mechanism that improves translation.",
            research_question="Can attention improve translation quality?",
        ),
    }


_CLAIM_MARKER_RE = re.compile(r"\[CLAIM (C\d+)\]")


class _SectionGeneratingProvider:
    """Serves the four extraction-pass responses like ``FakeProvider``, and
    for ``GeneratedSectionsOutput`` synthesizes one section that cites every
    claim id it finds in the prompt's ``[CLAIM <uuid>]`` markers -- lets a
    test assert real, DB-persisted claim ids (not knowable ahead of a
    ``uuid4()`` default) flow through the technical/report prompts and back
    out validated, without hardcoding UUIDs.
    """

    def __init__(self) -> None:
        self._extraction = _extraction_responses()
        self.calls: list[tuple[str, type]] = []

    async def generate(self, prompt: str, schema: type, **opts: object):  # noqa: ANN401
        self.calls.append((prompt, schema))
        if schema is GeneratedSectionsOutput:
            claim_ids = _CLAIM_MARKER_RE.findall(prompt)
            return GeneratedSectionsOutput(
                sections=[GeneratedSectionDraft(heading="Overview", body="Synthesized body.", claim_ids=claim_ids)]
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


class _TechnicalFailingProvider:
    """Succeeds on the four extraction passes, but always fails structured
    output for ``GeneratedSectionsOutput`` -- used to prove a downstream
    stage's failure never undoes an earlier stage's already-committed work.
    """

    def __init__(self) -> None:
        self._extraction = _extraction_responses()

    async def generate(self, prompt: str, schema: type, **opts: object):  # noqa: ANN401
        if schema is GeneratedSectionsOutput:
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


class _PreflightFailingProvider:
    """Fails only the liveness ping (``_PingResponse``) -- proves
    ``run_analysis``'s preflight check stops the whole run before any
    stage's real work starts, never reaching a real extraction/generation
    call."""

    def __init__(self) -> None:
        self.generate_calls: list[type] = []

    async def generate(self, prompt: str, schema: type, **opts: object):  # noqa: ANN401
        self.generate_calls.append(schema)
        if schema is _PingResponse:
            raise AuthenticationError("bad key")
        raise AssertionError(f"unexpected schema {schema} -- preflight should have stopped the run")

    def stream(self, prompt: str, schema: type, **opts: object):
        raise NotImplementedError

    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        raise NotSupportedError("unused")

    async def vision(self, image: bytes, prompt: str) -> str:
        raise NotSupportedError("unused")

    def available_models(self) -> list[ModelInfo]:
        return []


async def test_run_analysis_preflight_stops_before_any_stage_work_and_dedupes_by_model(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _PreflightFailingProvider()
    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: provider)
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT})

    # Both stages share provider_id/model -- the preflight should ping once,
    # not once per stage.
    stages = {**_EVIDENCE_STAGE, **_TECHNICAL_STAGE}
    events = [event async for event in run_analysis(paper.id, stages)]

    assert [e.type for e in events] == ["progress", "error"]
    assert events[0].message == "Checking model availability: fake-model via Google Gemini (cloud API)"
    assert events[1].stage == "evidence"  # first stage requesting this (provider_id, model) pair
    assert provider.generate_calls == [_PingResponse]


@pytest.fixture(autouse=True)
def _patch_provider_and_session(monkeypatch: pytest.MonkeyPatch, db_engine: AsyncEngine) -> None:
    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: FakeProvider(_extraction_responses()))
    # run_analysis opens its own session via AsyncSessionLocal -- point it at
    # this test's per-loop engine (same pattern as test_papers_integration.py's
    # monkeypatch of app.papers.service.AsyncSessionLocal). A separate
    # connection from db_session's, but same DB: committed rows from one are
    # visible to the other under Postgres's default read-committed isolation.
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr("app.evidence.service.AsyncSessionLocal", session_factory)


async def test_run_analysis_persists_evidence_merged_from_all_four_passes(db_session: AsyncSession) -> None:
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT, 2: PAGE_2_TEXT})

    events = [event async for event in run_analysis(paper.id, _EVIDENCE_STAGE)]

    assert events[-1].type == "done"
    assert any(event.type == "error" for event in events) is False
    # Each of the four passes is announced as it starts, naming the model and
    # whether the paper leaves this machine.
    pass_messages = [e.message for e in events if e.message and e.message.startswith("Pass ")]
    assert pass_messages == [
        f"Pass {n} of 4: extracting {what}, waiting on fake-model via Google Gemini (cloud API)"
        for n, what in enumerate(["claims", "metrics", "glossary terms", "summary and narrative"], start=1)
    ]

    evidence = await get_evidence(db_session, paper.id)
    assert evidence.thesis == "A new attention mechanism improves translation quality."
    assert len(evidence.claims) == 4
    assert len(evidence.metrics) == 1
    assert len(evidence.glossary) == 1

    # Derived views (design decision #1): filtered by kind, not separate storage.
    assert len(evidence.methods) == 1
    assert evidence.methods[0].statement == "The method uses a novel attention mechanism."
    assert len(evidence.limitations) == 1
    assert evidence.limitations[0].statement == "Training requires very large compute budgets."
    findings = [c for c in evidence.claims if c.kind == ClaimKind.reported_result]
    assert len(findings) == 2

    # The verifier actually ran against real persisted page text: the real
    # claim verifies, the fabricated one does not.
    real_claim = next(c for c in evidence.claims if "10%" in c.statement)
    assert real_claim.verification_status == VerificationStatus.verified
    fabricated_claim = next(c for c in evidence.claims if "browser extension" in c.statement)
    assert fabricated_claim.verification_status == VerificationStatus.not_found


async def test_run_analysis_sanitizes_claim_metric_and_glossary_text(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Claim.statement / Metric.label,display_value,unit,context /
    GlossaryTerm.term,definition are LLM-produced prose, same sanitization
    risk category as narrative fields and generated sections (security
    review: this coverage was missing here). source_refs/source_excerpt --
    verbatim quotations -- must never be touched by sanitization.
    """
    malicious_responses = {
        ClaimsExtractionOutput: ClaimsExtractionOutput(
            claims=[
                ClaimExtraction(
                    statement="The method improves quality<script>alert(1)</script> by 10%.",
                    kind=ClaimKind.reported_result,
                    source_refs=[
                        SourceRefExtraction(
                            page=1, excerpt="improves translation quality by 10% over the previous baseline"
                        )
                    ],
                )
            ]
        ),
        MetricsExtractionOutput: MetricsExtractionOutput(
            metrics=[
                MetricExtraction(
                    label="Quality<script>alert(1)</script>",
                    value="10",
                    display_value="10%<script>alert(1)</script>",
                    unit="%<script>alert(1)</script>",
                    context="javascript:alert(1)",
                    source_page=1,
                    source_excerpt="improves translation quality by 10%",
                )
            ]
        ),
        GlossaryExtractionOutput: GlossaryExtractionOutput(
            terms=[
                GlossaryTermExtraction(
                    term="Attention<script>alert(1)</script>",
                    definition="A way<iframe src=x></iframe> to weigh input parts.",
                )
            ]
        ),
        NarrativeExtraction: NarrativeExtraction(
            thesis="A new attention mechanism improves translation quality.",
            plain_summary="The paper proposes an attention mechanism that improves translation.",
            research_question="Can attention improve translation quality?",
        ),
    }
    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: FakeProvider(malicious_responses))
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT})

    events = [event async for event in run_analysis(paper.id, _EVIDENCE_STAGE)]
    assert any(event.type == "error" for event in events) is False

    evidence = await get_evidence(db_session, paper.id)
    claim = evidence.claims[0]
    metric = evidence.metrics[0]
    glossary_term = evidence.glossary[0]

    for value in (
        claim.statement,
        metric.label,
        metric.display_value,
        metric.unit,
        metric.context,
        glossary_term.term,
        glossary_term.definition,
    ):
        assert "<script" not in value
        assert "<iframe" not in value
        assert "javascript:" not in value

    # Verbatim quotations are never rewritten by sanitization.
    assert claim.source_refs[0].excerpt == "improves translation quality by 10% over the previous baseline"
    assert metric.source_excerpt == "improves translation quality by 10%"


async def test_run_analysis_is_idempotent_on_rerun(db_session: AsyncSession) -> None:
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT, 2: PAGE_2_TEXT})

    async for _ in run_analysis(paper.id, _EVIDENCE_STAGE):
        pass
    async for _ in run_analysis(paper.id, _EVIDENCE_STAGE):
        pass

    evidence = await get_evidence(db_session, paper.id)
    assert len(evidence.claims) == 4  # not doubled by the second run


async def test_run_analysis_raises_paper_not_parsed_error(db_session: AsyncSession) -> None:
    paper = await make_parsed_paper(db_session, {})
    paper_row = await db_session.get(Paper, paper.id)
    paper_row.parse_status = ParseStatus.pending
    await db_session.commit()

    with pytest.raises(PaperNotParsedError):
        async for _ in run_analysis(paper.id, _EVIDENCE_STAGE):
            pass


async def test_reverify_claim_updates_status_after_page_text_changes(db_session: AsyncSession) -> None:
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT, 2: PAGE_2_TEXT})
    async for _ in run_analysis(paper.id, _EVIDENCE_STAGE):
        pass

    evidence = await get_evidence(db_session, paper.id)
    real_claim = next(c for c in evidence.claims if "10%" in c.statement)
    assert real_claim.verification_status == VerificationStatus.verified

    # Simulate a re-parse that lost page 1's text entirely.
    page_1 = await db_session.scalar(select(Page).where(Page.paper_id == paper.id, Page.page_number == 1))
    page_1.text = ""
    await db_session.commit()

    reverified = await reverify_claim(db_session, real_claim.id)
    assert reverified.verification_status == VerificationStatus.needs_review


async def test_reverify_claim_raises_not_found_for_unknown_claim(db_session: AsyncSession) -> None:
    from app.evidence.exceptions import ClaimNotFoundError

    with pytest.raises(ClaimNotFoundError):
        await reverify_claim(db_session, uuid.uuid4())


# --- multi-stage run_analysis (Phase 4a) ------------------------------------


async def test_run_analysis_runs_evidence_technical_report_in_one_call(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT, 2: PAGE_2_TEXT})
    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: _SectionGeneratingProvider())

    stages = {**_EVIDENCE_STAGE, **_TECHNICAL_STAGE, **_REPORT_STAGE}
    events = [event async for event in run_analysis(paper.id, stages)]

    assert [e.stage for e in events if e.type == "done"] == ["evidence", "technical", "report"]
    assert any(event.type == "error" for event in events) is False

    report_sections = await get_report(db_session, paper.id)
    technical_sections = await get_technical_appendix(db_session, paper.id)
    assert len(report_sections) == 1
    assert len(technical_sections) == 1
    # claim_ids resolved to real, DB-persisted claims -- not hardcoded/fabricated.
    assert report_sections[0].claim_ids
    assert technical_sections[0].claim_ids


async def test_run_analysis_raises_evidence_not_found_for_technical_without_evidence(
    db_session: AsyncSession,
) -> None:
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT})

    with pytest.raises(EvidenceNotFoundError):
        async for _ in run_analysis(paper.id, _TECHNICAL_STAGE):
            pass


async def test_run_analysis_raises_evidence_not_found_for_report_without_evidence(db_session: AsyncSession) -> None:
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT})

    with pytest.raises(EvidenceNotFoundError):
        async for _ in run_analysis(paper.id, _REPORT_STAGE):
            pass


async def test_run_analysis_runs_report_standalone_after_a_prior_evidence_run(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT, 2: PAGE_2_TEXT})
    async for _ in run_analysis(paper.id, _EVIDENCE_STAGE):
        pass

    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: _SectionGeneratingProvider())
    events = [event async for event in run_analysis(paper.id, _REPORT_STAGE)]

    assert events[-1].type == "done"
    assert events[-1].stage == "report"
    sections = await get_report(db_session, paper.id)
    assert len(sections) == 1


async def test_run_analysis_technical_failure_does_not_undo_committed_evidence(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT, 2: PAGE_2_TEXT})
    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: _TechnicalFailingProvider())

    stages = {**_EVIDENCE_STAGE, **_TECHNICAL_STAGE}
    events = [event async for event in run_analysis(paper.id, stages)]

    assert any(e.type == "done" and e.stage == "evidence" for e in events)
    assert any(e.type == "error" and e.stage == "technical" for e in events)

    # Evidence's own commit is untouched by technical's later failure.
    evidence = await get_evidence(db_session, paper.id)
    assert len(evidence.claims) == 4

    # Nothing was persisted for the failed technical stage.
    with pytest.raises(TechnicalAppendixNotFoundError):
        await get_technical_appendix(db_session, paper.id)


class _KeyLeakingProvider:
    """Succeeds on extraction, but fails GeneratedSectionsOutput with an
    exception message that embeds a secret -- proves the technical/report
    stages' own logger.warning calls (service.py's *_generation_failed
    lines) never let a submitted credential reach a log record, even when
    the underlying exception text contains it (security-review LOW finding:
    the existing log-safety tests only exercised the evidence stage)."""

    def __init__(self, secret: str) -> None:
        self._extraction = _extraction_responses()
        self._secret = secret

    async def generate(self, prompt: str, schema: type, **opts: object):  # noqa: ANN401
        if schema is GeneratedSectionsOutput:
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


@pytest.mark.parametrize("stage_name,stage_dict", [("technical", _TECHNICAL_STAGE), ("report", _REPORT_STAGE)])
async def test_technical_and_report_stage_failures_never_log_submitted_api_key(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    stage_name: str,
    stage_dict: dict[str, StageConfig],
) -> None:
    secret_key = f"sk-super-secret-{stage_name}-24680"
    paper = await make_parsed_paper(db_session, {1: PAGE_1_TEXT, 2: PAGE_2_TEXT})
    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: _SectionGeneratingProvider())
    async for _ in run_analysis(paper.id, _EVIDENCE_STAGE):
        pass

    monkeypatch.setattr("app.evidence.service.build_provider", lambda *a, **k: _KeyLeakingProvider(secret_key))
    leaking_stage = {stage_name: StageConfig(provider_id="google", api_key=secret_key, model="fake-model")}

    with caplog.at_level(logging.DEBUG, logger="app.evidence.service"):
        events = [event async for event in run_analysis(paper.id, leaking_stage)]

    assert any(e.type == "error" and e.stage == stage_name for e in events)
    for record in caplog.records:
        assert secret_key not in record.getMessage()
