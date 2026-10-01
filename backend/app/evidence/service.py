"""Public entrypoints for the Evidence Engine -- the contract
``backend-engineer`` builds the analysis/evidence API routes against.

``run_analysis`` owns its own DB session (like ``app.papers.service.run_parsing``)
because it's a long-running generator driving an SSE response, not bound to
one request's session lifecycle. ``reverify_claim``/``get_evidence`` take a
request-scoped ``AsyncSession`` like any other route-backing service call.
"""

import asyncio
import re
import uuid
from collections.abc import AsyncIterator
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.coderesearch import service as coderesearch_service
from app.coderesearch.exceptions import GithubNotFoundError, GithubUnavailableError
from app.coderesearch.github_client import fetch_readme
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.evidence.assistant import build_paper_context, run_assistant_query, select_retrieval_context
from app.evidence.exceptions import (
    AssistantActionNotSupportedError,
    ClaimMissingSourceRefsError,
    ClaimNotFoundError,
    DerivationReferencesUnknownClaimError,
    EvidenceNotFoundError,
    ImplementationPlanNotFoundError,
    InteractiveFormulaInvalidError,
    InteractiveReferencesUnknownClaimError,
    LearningNotFoundError,
    PaperNotParsedError,
    QuizReferencesUnknownClaimError,
    ReportNotFoundError,
    SectionReferencesUnknownClaimError,
    StoryIntegrityError,
    StoryNotFoundError,
    TechnicalAppendixNotFoundError,
)
from app.evidence.extraction import extraction_passes, merge_extraction
from app.evidence.figure_linking import FigureClaimContext, FigureInput, FigureLink, link_figures
from app.evidence.figures import (
    FigureResponse,
    list_figures,
    load_claim_contexts,
    load_figure_inputs,
    replace_figure_links,
)
from app.evidence.implementation_plan import generate_implementation_plan_sections
from app.evidence.interactive import generate_interactives
from app.evidence.learning import (
    generate_application_guide_sections,
    generate_derivations,
    generate_primer_sections,
    generate_quiz_questions,
)
from app.evidence.report import generate_report_sections
from app.evidence.schemas import (
    AssistantClaimForPrompt,
    AssistantRetrievalContext,
    ClaimForPrompt,
    ClaimResponse,
    DerivationDraft,
    DerivationResponse,
    EvidenceResponse,
    ExtractionResult,
    GeneratedSectionDraft,
    GeneratedSectionResponse,
    GlossaryTermForPrompt,
    GlossaryTermResponse,
    InteractiveDraft,
    InteractiveResponse,
    LearningExcerptForPrompt,
    LearningResponse,
    MetricForPrompt,
    MetricResponse,
    PageText,
    PaperContextForPrompt,
    QuizQuestionDraft,
    QuizQuestionResponse,
    StageConfig,
)
from app.evidence.story import generate_story
from app.evidence.story_visuals import StorySectionResponse, StorySpec, StorySpecResponse, index_label
from app.evidence.technical import generate_technical_sections
from app.evidence.verifier import verify_claim_status
from app.models.claim import Claim, ClaimKind
from app.models.evidence import Evidence
from app.models.generated_section import GeneratedSection, SectionType
from app.models.glossary_term import GlossaryTerm
from app.models.learning_derivation import LearningDerivation
from app.models.learning_interactive import LearningInteractive
from app.models.learning_quiz_question import LearningQuizQuestion
from app.models.metric import Metric
from app.models.page import Page
from app.models.paper import Paper, ParseStatus
from app.models.source_reference import SourceReference
from app.models.story import Story
from app.papers.exceptions import PaperNotFoundError
from app.providers.base import AIProvider
from app.providers.errors import (
    AuthenticationError,
    InvalidConfigError,
    NotSupportedError,
    ProviderUnavailableError,
    StructuredOutputError,
)
from app.providers.exceptions import ProviderNotFoundError
from app.providers.ping import ping_chat
from app.providers.redaction import redacting
from app.providers.registry import build_provider, describe_provider

logger = get_logger(__name__)

# Narrative fields (thesis/plain_summary/research_question) and generated
# report/technical section bodies are the same risk category: LLM-produced
# prose with no independent (verifier) backstop, ultimately derived from
# claim statements/excerpts that are themselves unverified free text (the
# quote-exactness verifier only checks excerpts against page text, never
# statement wording). A length cap + basic sanity check is defense-in-depth
# against a hijacked pass, even though no frontend renders any of this
# unescaped today — applied uniformly rather than only to narrative fields.
_NARRATIVE_MAX_LENGTH = 4000
_GENERATED_SECTION_MAX_LENGTH = 8000
_UNEXPECTED_CONTENT_PATTERN = re.compile(r"<script|javascript:|<iframe", re.IGNORECASE)

_GLOSSARY_UNSOURCED_PREFIX = "General term (not defined in this paper): "


def _via(config: StageConfig) -> str:
    """"deepseek-ai/deepseek-v4.1-flash via NVIDIA NIM (cloud API)" -- tells
    the user what a long wait is actually waiting on, and whether the paper
    is being sent off this machine."""
    return f"{config.model} via {describe_provider(config.provider_id)}"


def _sanitize_generated_text(value: str, max_length: int) -> str:
    truncated = value[:max_length]
    return _UNEXPECTED_CONTENT_PATTERN.sub("", truncated)


def _sanitize_narrative_field(value: str) -> str:
    return _sanitize_generated_text(value, _NARRATIVE_MAX_LENGTH)


def _sanitize_optional_narrative_field(value: str | None) -> str | None:
    return None if value is None else _sanitize_narrative_field(value)


class AnalysisEvent(BaseModel):
    type: Literal["progress", "checkpoint", "warning", "error", "done"]
    stage: str | None = None
    message: str | None = None
    data: dict | None = None


async def _preflight_check_models(stages: dict[str, StageConfig]) -> AsyncIterator[AnalysisEvent]:
    """Pings each distinct ``(provider_id, model)`` pair actually requested
    across the stages, once, before any stage's own (possibly multi-minute)
    work starts -- catches a catalogued-but-dead model (404/410) in
    milliseconds instead of after a long pipeline run begins. Cannot catch a
    model that pings fine but times out mid-run; that still surfaces as a
    normal per-stage error event."""
    first_stage_for_pair: dict[tuple[str, str], str] = {}
    for stage_name, config in stages.items():
        first_stage_for_pair.setdefault((config.provider_id, config.model), stage_name)

    if not first_stage_for_pair:
        return

    for (provider_id, model), stage_name in first_stage_for_pair.items():
        config = stages[stage_name]
        yield AnalysisEvent(
            type="progress", stage=None, message=f"Checking model availability: {_via(config)}"
        )
        try:
            provider: AIProvider = redacting(
                build_provider(provider_id, api_key=config.api_key, endpoint=config.endpoint), config.api_key
            )
            await ping_chat(provider, model)
        except (
            ProviderNotFoundError,
            InvalidConfigError,
            NotImplementedError,
            AuthenticationError,
            ProviderUnavailableError,
            NotSupportedError,
            StructuredOutputError,
        ) as exc:
            logger.warning("model_preflight_failed provider_id=%s model=%s error=%s", provider_id, model, exc)
            yield AnalysisEvent(type="error", stage=stage_name, message=str(exc))
            return


async def run_analysis(
    paper_id: uuid.UUID,
    stages: dict[str, StageConfig],
) -> AsyncIterator[AnalysisEvent]:
    """Runs whichever of ``"evidence"``/``"technical"``/``"report"``/
    ``"visual"`` are present in ``stages``, in dependency order: evidence
    first (if requested), then technical/report/visual (each independently
    optional, run sequentially -- ``run_analysis`` makes no ordering promise
    between them beyond "after evidence").

    ``PaperNotFoundError``/``PaperNotParsedError``/``EvidenceNotFoundError``
    are raised up front (before any ``AnalysisEvent`` is yielded) rather than
    emitted as an event -- these are request-validation failures the router
    awaits before starting the SSE stream, same treatment Phase 2 gave
    ``PaperNotFoundError``/``PaperNotParsedError``. ``EvidenceNotFoundError``
    is only checkable up front when evidence isn't *also* being (re)run in
    this same call; if it is, and that evidence stage's extraction fails,
    the failure surfaces as a ``type="error"`` event on the evidence stage
    and technical/report/visual are simply skipped for this call (nothing
    new to derive them from) rather than raising after the stream has
    already sent events.

    Each stage commits its own work before the next stage starts, and each
    gets its own progress/checkpoint/done event sequence tagged by its
    ``stage`` field -- a failure in one requested stage never rolls back or
    blocks a *different* stage that already committed successfully.
    """
    async with AsyncSessionLocal() as db:
        paper = await db.get(Paper, paper_id)
        if paper is None:
            raise PaperNotFoundError("Paper not found")

        run_evidence = "evidence" in stages
        run_technical = "technical" in stages
        run_report = "report" in stages
        run_visual = "visual" in stages

        if run_evidence and paper.parse_status != ParseStatus.parsed:
            raise PaperNotParsedError(f"Paper {paper_id} is not parsed yet (status={paper.parse_status.value})")

        if (run_technical or run_report or run_visual) and not run_evidence:
            existing_evidence = await db.scalar(select(Evidence).where(Evidence.paper_id == paper_id))
            if existing_evidence is None:
                raise EvidenceNotFoundError(
                    f"No evidence found for paper {paper_id} -- run the evidence stage before technical/report/visual"
                )

        async for event in _preflight_check_models(stages):
            yield event
            if event.type == "error":
                return

        evidence_available = not run_evidence  # prerequisite already satisfied if we're not (re)running it
        if run_evidence:
            async for event in _run_evidence_stage(db, paper, stages["evidence"]):
                yield event
                if event.type == "done":
                    evidence_available = True

        if (run_technical or run_report or run_visual) and not evidence_available:
            # Evidence was requested this call but its stage didn't reach
            # "done" (extraction/persistence failed) -- that failure's own
            # error event already told the caller why; nothing new exists
            # for technical/report/visual to derive from.
            return

        if run_technical:
            async for event in _run_technical_stage(db, paper, stages["technical"]):
                yield event

        if run_report:
            async for event in _run_report_stage(db, paper, stages["report"]):
                yield event

        if run_visual:
            async for event in _run_visual_stage(db, paper, stages["visual"]):
                yield event


class AssistantResponse(BaseModel):
    """API-facing response for ``POST /papers/{id}/assistant``
    (API_SPEC.md) -- assembled as the final ``"done"`` event's ``data``."""

    answer: str
    claim_ids: list[uuid.UUID]


_ASSISTANT_ACTIONS = frozenset(
    {"understand", "deep-dive", "challenge", "compare", "verify", "implement", "research", "learn"}
)


async def run_assistant(
    paper_id: uuid.UUID,
    action: str,
    question: str | None,
    compare_with: list[uuid.UUID] | None,
    provider_id: str,
    api_key: str | None,
    endpoint: str | None,
    model: str,
) -> AsyncIterator[AnalysisEvent]:
    """Research Assistant entrypoint (docs/API_SPEC.md's ``POST
    /papers/{id}/assistant``, docs/AGENTS.md's Research Assistant Agent
    entry).

    Not a stage of ``run_analysis``: the Research Assistant is stateless
    (no conversation history, no new DB table -- nothing here is ever
    persisted) and isn't part of the evidence -> technical/report/visual
    pipeline, so it gets its own top-level async-generator function using
    the same ``AnalysisEvent`` progress/checkpoint/done shape rather than
    being shoehorned into ``run_analysis``'s stage dict.

    Raises ``AssistantActionNotSupportedError`` up front if ``action`` isn't
    one of the 8 documented actions (defense-in-depth; the router's request
    body should already constrain this). Raises ``PaperNotFoundError``/
    ``EvidenceNotFoundError`` up front (before any ``AnalysisEvent`` is
    yielded, same treatment ``run_analysis`` gives its own pre-flight
    checks) if the primary paper -- or any paper id in ``compare_with`` --
    doesn't exist or has no ``Evidence`` row yet. The caller (router) has
    already verified every id in ``compare_with`` belongs to the requesting
    user before this is invoked -- only existence of evidence is (re-)
    checked here, never ownership.
    """
    if action not in _ASSISTANT_ACTIONS:
        raise AssistantActionNotSupportedError(f"Unsupported assistant action: {action!r}")

    async with AsyncSessionLocal() as db:
        paper = await db.get(Paper, paper_id)
        if paper is None:
            raise PaperNotFoundError("Paper not found")

        evidence_row = await db.scalar(select(Evidence).where(Evidence.paper_id == paper_id))
        if evidence_row is None:
            raise EvidenceNotFoundError(
                f"No evidence found for paper {paper_id} -- run analysis before using the assistant"
            )

        compare_ids = compare_with or []
        compare_rows: dict[uuid.UUID, tuple[Paper, Evidence]] = {}
        for other_id in compare_ids:
            other_paper = await db.get(Paper, other_id)
            if other_paper is None:
                raise PaperNotFoundError(f"Paper {other_id} not found")
            other_evidence = await db.scalar(select(Evidence).where(Evidence.paper_id == other_id))
            if other_evidence is None:
                raise EvidenceNotFoundError(
                    f"No evidence found for paper {other_id} -- run analysis before comparing against it"
                )
            compare_rows[other_id] = (other_paper, other_evidence)

        yield AnalysisEvent(type="progress", stage="assistant", message="Configuring AI provider")
        try:
            provider: AIProvider = redacting(build_provider(provider_id, api_key=api_key, endpoint=endpoint), api_key)
        except (ProviderNotFoundError, InvalidConfigError, NotImplementedError) as exc:
            logger.warning("assistant_provider_setup_failed paper_id=%s error=%s", paper_id, exc)
            yield AnalysisEvent(type="error", stage="assistant", message=str(exc))
            return

        claims = await _load_claims_for_assistant(db, paper_id)
        known_claim_ids = {claim.id for claim in claims}

        papers_context: list[PaperContextForPrompt] = []
        context = AssistantRetrievalContext()
        if action == "compare":
            papers_context.append(
                build_paper_context(
                    paper_id=paper_id,
                    title=paper.title,
                    thesis=evidence_row.thesis,
                    plain_summary=evidence_row.plain_summary,
                    research_question=evidence_row.research_question,
                    claims=claims,
                )
            )
            for other_id, (other_paper, other_evidence) in compare_rows.items():
                other_claims = await _load_claims_for_assistant(db, other_id)
                known_claim_ids |= {claim.id for claim in other_claims}
                papers_context.append(
                    build_paper_context(
                        paper_id=other_id,
                        title=other_paper.title,
                        thesis=other_evidence.thesis,
                        plain_summary=other_evidence.plain_summary,
                        research_question=other_evidence.research_question,
                        claims=other_claims,
                    )
                )
        else:
            metrics = await _load_metrics_for_prompt(db, paper_id)
            glossary = await _load_glossary_for_prompt(db, paper_id)
            learning_excerpts = await _load_learning_excerpts_for_prompt(db, paper_id)
            context = select_retrieval_context(
                action,
                question,
                thesis=evidence_row.thesis,
                plain_summary=evidence_row.plain_summary,
                research_question=evidence_row.research_question,
                claims=claims,
                metrics=metrics,
                glossary=glossary,
                learning_excerpts=learning_excerpts,
            )

        yield AnalysisEvent(type="progress", stage="assistant", message="Generating grounded answer")
        try:
            draft = await run_assistant_query(
                provider,
                action=action,
                question=question,
                context=context,
                known_claim_ids=known_claim_ids,
                papers_context=papers_context,
                model=model,
            )
        except (StructuredOutputError, ProviderUnavailableError, AuthenticationError, NotSupportedError) as exc:
            logger.warning("assistant_query_failed paper_id=%s provider=%s error=%s", paper_id, provider_id, exc)
            yield AnalysisEvent(type="error", stage="assistant", message=str(exc))
            return

        response = AssistantResponse(
            answer=_sanitize_generated_text(draft.answer, _GENERATED_SECTION_MAX_LENGTH),
            claim_ids=draft.claim_ids,
        )
        yield AnalysisEvent(
            type="checkpoint", stage="assistant", data={"claim_ids": [str(cid) for cid in response.claim_ids]}
        )
        yield AnalysisEvent(type="done", stage="assistant", data=response.model_dump(mode="json"))


async def _run_evidence_stage(db: AsyncSession, paper: Paper, config: StageConfig) -> AsyncIterator[AnalysisEvent]:
    """The Phase 2 pipeline (provider -> four extraction passes -> persist ->
    verify), unchanged in behavior, now scoped to one stage of a possibly
    multi-stage ``run_analysis`` call.
    """
    paper_id = paper.id
    page_rows = list(
        (await db.scalars(select(Page).where(Page.paper_id == paper_id).order_by(Page.page_number))).all()
    )
    pages = [PageText(number=p.page_number, text=p.text) for p in page_rows]
    pages_by_number = {p.page_number: p.text for p in page_rows}

    yield AnalysisEvent(type="progress", stage="evidence", message="Configuring AI provider")
    try:
        provider: AIProvider = redacting(build_provider(config.provider_id, api_key=config.api_key, endpoint=config.endpoint), config.api_key)
    except (ProviderNotFoundError, InvalidConfigError, NotImplementedError) as exc:
        logger.warning("evidence_provider_setup_failed paper_id=%s error=%s", paper_id, exc)
        yield AnalysisEvent(type="error", stage="evidence", message=str(exc))
        return

    try:
        passes = extraction_passes(pages)
        results = []
        for number, (what, prompt, schema) in enumerate(passes, start=1):
            yield AnalysisEvent(
                type="progress",
                stage="evidence",
                message=f"Pass {number} of {len(passes)}: extracting {what}, waiting on {_via(config)}",
            )
            results.append(await provider.generate(prompt, schema, model=config.model))
        extraction = merge_extraction(results)
    except (StructuredOutputError, ProviderUnavailableError, AuthenticationError, NotSupportedError) as exc:
        logger.warning(
            "evidence_extraction_failed paper_id=%s provider=%s error=%s", paper_id, config.provider_id, exc
        )
        yield AnalysisEvent(type="error", stage="evidence", message=str(exc))
        return

    yield AnalysisEvent(
        type="checkpoint",
        stage="evidence",
        data={
            "claims": len(extraction.claims),
            "metrics": len(extraction.metrics),
            "glossary": len(extraction.glossary),
        },
    )

    try:
        claims = await _persist_extraction(db, paper_id, extraction)
    except ClaimMissingSourceRefsError as exc:
        await db.rollback()
        logger.error("evidence_persist_rejected paper_id=%s error=%s", paper_id, exc)
        yield AnalysisEvent(type="error", stage="evidence", message=str(exc))
        return

    yield AnalysisEvent(type="progress", stage="evidence", message="Checking every quote against the PDF text (on this machine)")
    status_counts: dict[str, int] = {}
    for claim in claims:
        refs = [(ref.page, ref.excerpt) for ref in claim.source_refs]
        claim.verification_status = verify_claim_status(refs, pages_by_number)
        status_counts[claim.verification_status.value] = status_counts.get(claim.verification_status.value, 0) + 1
    await db.commit()

    yield AnalysisEvent(type="checkpoint", stage="evidence", data=status_counts)
    yield AnalysisEvent(type="done", stage="evidence", data={"paper_id": str(paper_id)})


async def _run_technical_stage(db: AsyncSession, paper: Paper, config: StageConfig) -> AsyncIterator[AnalysisEvent]:
    paper_id = paper.id

    yield AnalysisEvent(type="progress", stage="technical", message="Configuring AI provider")
    try:
        provider: AIProvider = redacting(build_provider(config.provider_id, api_key=config.api_key, endpoint=config.endpoint), config.api_key)
    except (ProviderNotFoundError, InvalidConfigError, NotImplementedError) as exc:
        logger.warning("technical_provider_setup_failed paper_id=%s error=%s", paper_id, exc)
        yield AnalysisEvent(type="error", stage="technical", message=str(exc))
        return

    claims = await _load_claims_for_prompt(db, paper_id)
    metrics = await _load_metrics_for_prompt(db, paper_id)

    yield AnalysisEvent(type="progress", stage="technical", message=f"Generating technical appendix, waiting on {_via(config)}")
    try:
        drafts = await generate_technical_sections(provider, claims=claims, metrics=metrics, model=config.model)
    except (
        StructuredOutputError,
        ProviderUnavailableError,
        AuthenticationError,
        NotSupportedError,
        SectionReferencesUnknownClaimError,
    ) as exc:
        logger.warning(
            "technical_generation_failed paper_id=%s provider=%s error=%s", paper_id, config.provider_id, exc
        )
        yield AnalysisEvent(type="error", stage="technical", message=str(exc))
        return

    await _persist_sections(db, paper_id, SectionType.technical, drafts)

    yield AnalysisEvent(type="checkpoint", stage="technical", data={"sections": len(drafts)})
    yield AnalysisEvent(type="done", stage="technical", data={"paper_id": str(paper_id)})


async def _run_report_stage(db: AsyncSession, paper: Paper, config: StageConfig) -> AsyncIterator[AnalysisEvent]:
    paper_id = paper.id

    yield AnalysisEvent(type="progress", stage="report", message="Configuring AI provider")
    try:
        provider: AIProvider = redacting(build_provider(config.provider_id, api_key=config.api_key, endpoint=config.endpoint), config.api_key)
    except (ProviderNotFoundError, InvalidConfigError, NotImplementedError) as exc:
        logger.warning("report_provider_setup_failed paper_id=%s error=%s", paper_id, exc)
        yield AnalysisEvent(type="error", stage="report", message=str(exc))
        return

    evidence_row = await db.scalar(select(Evidence).where(Evidence.paper_id == paper_id))
    if evidence_row is None:
        # Defense-in-depth: run_analysis's own pre-flight/post-evidence-stage
        # checks should make this unreachable, but a stage function must
        # never assume the caller enforced its precondition correctly.
        logger.error("report_generation_missing_evidence paper_id=%s", paper_id)
        yield AnalysisEvent(type="error", stage="report", message=f"No evidence found for paper {paper_id}")
        return
    claims = await _load_claims_for_prompt(db, paper_id)

    yield AnalysisEvent(type="progress", stage="report", message=f"Generating deep report, waiting on {_via(config)}")
    try:
        drafts = await generate_report_sections(
            provider,
            thesis=evidence_row.thesis,
            plain_summary=evidence_row.plain_summary,
            research_question=evidence_row.research_question,
            claims=claims,
            model=config.model,
        )
    except (
        StructuredOutputError,
        ProviderUnavailableError,
        AuthenticationError,
        NotSupportedError,
        SectionReferencesUnknownClaimError,
    ) as exc:
        logger.warning("report_generation_failed paper_id=%s provider=%s error=%s", paper_id, config.provider_id, exc)
        yield AnalysisEvent(type="error", stage="report", message=str(exc))
        return

    await _persist_sections(db, paper_id, SectionType.report, drafts)

    yield AnalysisEvent(type="checkpoint", stage="report", data={"sections": len(drafts)})
    yield AnalysisEvent(type="done", stage="report", data={"paper_id": str(paper_id)})


async def _run_visual_stage(db: AsyncSession, paper: Paper, config: StageConfig) -> AsyncIterator[AnalysisEvent]:
    """Generates all six Learning Layer / StorySpec content types in one
    stage (unlike evidence's four sequential passes, these run together): story, primer,
    application guide, quiz, derivations, interactives. All six are
    validated (claim_ids resolvable against this paper's real claims,
    interactive formulas grammar-validated, story integrity rules) before any
    of them is persisted -- a failure in any one pass fails the whole stage
    rather than persisting a partial, inconsistent Learning Layer.

    A seventh call links extracted PDF figures to claims. It is enrichment,
    so unlike the six it is NON-FATAL: any provider/schema failure is logged
    and the figures simply stay unlinked.
    """
    paper_id = paper.id

    yield AnalysisEvent(type="progress", stage="visual", message="Configuring AI provider")
    try:
        provider: AIProvider = redacting(build_provider(config.provider_id, api_key=config.api_key, endpoint=config.endpoint), config.api_key)
    except (ProviderNotFoundError, InvalidConfigError, NotImplementedError) as exc:
        logger.warning("visual_provider_setup_failed paper_id=%s error=%s", paper_id, exc)
        yield AnalysisEvent(type="error", stage="visual", message=str(exc))
        return

    evidence_row = await db.scalar(select(Evidence).where(Evidence.paper_id == paper_id))
    if evidence_row is None:
        # Defense-in-depth, same reasoning as _run_report_stage's own check:
        # run_analysis's pre-flight/post-evidence-stage checks should make
        # this unreachable, but a stage function must never assume the
        # caller enforced its precondition correctly.
        logger.error("visual_generation_missing_evidence paper_id=%s", paper_id)
        yield AnalysisEvent(type="error", stage="visual", message=f"No evidence found for paper {paper_id}")
        return
    claims = await _load_claims_for_prompt(db, paper_id)
    metrics = await _load_metrics_for_prompt(db, paper_id)
    figures = await load_figure_inputs(db, paper_id)
    figure_contexts = await load_claim_contexts(db, paper_id) if figures else []

    yield AnalysisEvent(
        type="progress",
        stage="visual",
        message=(
            "Generating story, primer, application guide, quiz, derivations, interactives, and figure links"
            f", waiting on {_via(config)}"
        ),
    )
    # Explicit tasks (not bare coroutines) so a failure can cancel the other
    # five in-flight provider calls -- plain asyncio.gather() propagates the
    # first exception but, per its own documented behavior, does NOT cancel
    # sibling awaitables (security review: this stage failing still let the
    # other calls keep running/costing quota in the background after the
    # SSE stream had already reported the failure and moved on).
    tasks = [
        asyncio.create_task(
            generate_story(
                provider,
                thesis=evidence_row.thesis,
                plain_summary=evidence_row.plain_summary,
                research_question=evidence_row.research_question,
                claims=claims,
                metrics=metrics,
                model=config.model,
            )
        ),
        asyncio.create_task(generate_primer_sections(provider, claims=claims, model=config.model)),
        asyncio.create_task(
            generate_application_guide_sections(provider, claims=claims, metrics=metrics, model=config.model)
        ),
        asyncio.create_task(generate_quiz_questions(provider, claims=claims, model=config.model)),
        asyncio.create_task(generate_derivations(provider, claims=claims, metrics=metrics, model=config.model)),
        asyncio.create_task(generate_interactives(provider, claims=claims, metrics=metrics, model=config.model)),
        asyncio.create_task(
            _link_figures_non_fatal(
                provider,
                paper_id=paper_id,
                figures=figures,
                contexts=figure_contexts,
                known_claim_ids={claim.id for claim in claims},
                model=config.model,
            )
        ),
    ]
    try:
        (
            story,
            primer_drafts,
            application_guide_drafts,
            quiz_drafts,
            derivation_drafts,
            interactive_drafts,
            (figure_links, figure_link_warning),
        ) = await asyncio.gather(*tasks)
    except (
        StructuredOutputError,
        ProviderUnavailableError,
        AuthenticationError,
        NotSupportedError,
        SectionReferencesUnknownClaimError,
        QuizReferencesUnknownClaimError,
        DerivationReferencesUnknownClaimError,
        InteractiveReferencesUnknownClaimError,
        InteractiveFormulaInvalidError,
        StoryIntegrityError,
    ) as exc:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.warning("visual_generation_failed paper_id=%s provider=%s error=%s", paper_id, config.provider_id, exc)
        yield AnalysisEvent(type="error", stage="visual", message=str(exc))
        return

    await _persist_visual_stage(
        db,
        paper_id,
        story=story,
        primer_drafts=primer_drafts,
        application_guide_drafts=application_guide_drafts,
        quiz_drafts=quiz_drafts,
        derivation_drafts=derivation_drafts,
        interactive_drafts=interactive_drafts,
        figures=figures,
        figure_links=figure_links,
    )

    if figure_link_warning:
        yield AnalysisEvent(type="warning", stage="visual", message=figure_link_warning)

    yield AnalysisEvent(
        type="checkpoint",
        stage="visual",
        data={
            "story_sections": len(story.sections),
            "primer_sections": len(primer_drafts),
            "application_guide_sections": len(application_guide_drafts),
            "quiz_questions": len(quiz_drafts),
            "derivations": len(derivation_drafts),
            "interactives": len(interactive_drafts),
            "figures_linked": sum(1 for link in figure_links or [] if link.claim_ids),
        },
    )
    yield AnalysisEvent(type="done", stage="visual", data={"paper_id": str(paper_id)})


async def _link_figures_non_fatal(
    provider: AIProvider,
    *,
    paper_id: uuid.UUID,
    figures: list[FigureInput],
    contexts: list[FigureClaimContext],
    known_claim_ids: set[uuid.UUID],
    model: str,
) -> tuple[list[FigureLink] | None, str | None]:
    """``None`` figure_links means "leave figure rows as they are": no
    figures to link (the provider is never called), or the call failed. A
    non-``None`` warning message means the call failed and the caller should
    tell the user, not just the server log."""
    if not figures:
        return None, None
    try:
        return await link_figures(
            provider, figures=figures, contexts=contexts, known_claim_ids=known_claim_ids, model=model
        ), None
    except (StructuredOutputError, ProviderUnavailableError, AuthenticationError, NotSupportedError) as exc:
        logger.warning("figure_linking_failed paper_id=%s error=%s", paper_id, exc)
        return None, f"Figure linking failed: {exc}"


async def _load_claims_for_prompt(db: AsyncSession, paper_id: uuid.UUID) -> list[ClaimForPrompt]:
    claim_rows = (await db.scalars(select(Claim).where(Claim.paper_id == paper_id))).all()
    return [
        ClaimForPrompt(
            id=claim.id,
            kind=claim.kind,
            statement=claim.statement,
            excerpts=[ref.excerpt for ref in claim.source_refs],
            verification_status=claim.verification_status,
        )
        for claim in claim_rows
    ]


async def _load_metrics_for_prompt(db: AsyncSession, paper_id: uuid.UUID) -> list[MetricForPrompt]:
    metric_rows = (await db.scalars(select(Metric).where(Metric.paper_id == paper_id))).all()
    return [
        MetricForPrompt(
            label=metric.label,
            value=metric.value,
            display_value=metric.display_value,
            unit=metric.unit,
            context=metric.context,
        )
        for metric in metric_rows
    ]


async def _load_claims_for_assistant(db: AsyncSession, paper_id: uuid.UUID) -> list[AssistantClaimForPrompt]:
    """Same shape as ``_load_claims_for_prompt``, plus ``verification_status``
    -- several assistant actions (notably ``verify``) must surface it
    directly in the grounded answer."""
    claim_rows = (await db.scalars(select(Claim).where(Claim.paper_id == paper_id))).all()
    return [
        AssistantClaimForPrompt(
            id=claim.id,
            kind=claim.kind,
            statement=claim.statement,
            excerpts=[ref.excerpt for ref in claim.source_refs],
            verification_status=claim.verification_status,
        )
        for claim in claim_rows
    ]


async def _load_glossary_for_prompt(db: AsyncSession, paper_id: uuid.UUID) -> list[GlossaryTermForPrompt]:
    rows = (await db.scalars(select(GlossaryTerm).where(GlossaryTerm.paper_id == paper_id))).all()
    return [GlossaryTermForPrompt(term=row.term, definition=row.definition) for row in rows]


async def _load_learning_excerpts_for_prompt(db: AsyncSession, paper_id: uuid.UUID) -> list[LearningExcerptForPrompt]:
    """Primer + application-guide sections only (not story, quiz, or
    derivations) -- the two Learning Layer content types that are plain
    heading/body prose, a natural fit for grounding the ``learn`` action's
    prompt. Empty if the visual stage hasn't been run for this paper yet;
    ``select_retrieval_context``'s ``"learn"`` handling falls back to
    ``"understand"``'s broader context in that case."""
    rows = (
        await db.scalars(
            select(GeneratedSection).where(
                GeneratedSection.paper_id == paper_id,
                GeneratedSection.section_type.in_([SectionType.primer, SectionType.application_guide]),
            )
        )
    ).all()
    return [LearningExcerptForPrompt(heading=row.title, body=row.content) for row in rows]


async def _persist_sections(
    db: AsyncSession, paper_id: uuid.UUID, section_type: SectionType, drafts: list[GeneratedSectionDraft]
) -> None:
    """Replace-on-rerun, same idempotent-reanalysis pattern
    ``_persist_extraction`` uses for claims: this stage's previous sections
    (if any) are fully replaced by the new batch, never appended to.
    """
    await db.execute(
        delete(GeneratedSection).where(
            GeneratedSection.paper_id == paper_id, GeneratedSection.section_type == section_type
        )
    )
    for order, draft in enumerate(drafts):
        db.add(
            GeneratedSection(
                paper_id=paper_id,
                section_type=section_type,
                order=order,
                title=_sanitize_generated_text(draft.heading, _GENERATED_SECTION_MAX_LENGTH),
                content=_sanitize_generated_text(draft.body, _GENERATED_SECTION_MAX_LENGTH),
                claim_ids=[str(claim_id) for claim_id in draft.claim_ids],
            )
        )
    await db.commit()


async def _persist_visual_stage(
    db: AsyncSession,
    paper_id: uuid.UUID,
    *,
    story: StorySpec,
    primer_drafts: list[GeneratedSectionDraft],
    application_guide_drafts: list[GeneratedSectionDraft],
    quiz_drafts: list[QuizQuestionDraft],
    derivation_drafts: list[DerivationDraft],
    interactive_drafts: list[InteractiveDraft],
    figures: list[FigureInput],
    figure_links: list[FigureLink] | None,
) -> None:
    """Replace-on-rerun for all six visual-stage content types, committed
    together in one transaction -- unlike ``_persist_sections`` (one commit
    per content type, fine when a stage produces exactly one type), a
    mid-batch failure here must not leave story/primer/application-guide/
    quiz/derivations/interactives for one paper out of sync with each other,
    since all six were generated and validated together as one Learning
    Layer. ``story`` arrives already sanitized and integrity-checked
    (``app.evidence.story``); ``figure_links is None`` leaves existing figure
    rows untouched.
    """
    await db.execute(
        delete(GeneratedSection).where(
            GeneratedSection.paper_id == paper_id,
            GeneratedSection.section_type.in_(
                [SectionType.story, SectionType.primer, SectionType.application_guide]
            ),
        )
    )
    await db.execute(delete(Story).where(Story.paper_id == paper_id))
    await db.execute(delete(LearningQuizQuestion).where(LearningQuizQuestion.paper_id == paper_id))
    await db.execute(delete(LearningDerivation).where(LearningDerivation.paper_id == paper_id))
    await db.execute(delete(LearningInteractive).where(LearningInteractive.paper_id == paper_id))

    db.add(
        Story(
            paper_id=paper_id,
            title=story.meta.title,
            dek=story.meta.dek,
            reading_time=story.meta.reading_time,
            closing=story.meta.closing.model_dump(),
        )
    )
    for order, section in enumerate(story.sections):
        db.add(
            GeneratedSection(
                paper_id=paper_id,
                section_type=SectionType.story,
                order=order,
                title=section.title,
                content=section.body,
                claim_ids=[str(claim_id) for claim_id in section.claim_ids],
                data={
                    "kicker": section.kicker,
                    "index_label": index_label(order),
                    "visual": section.visual.model_dump(mode="json"),
                },
            )
        )

    for section_type, drafts in (
        (SectionType.primer, primer_drafts),
        (SectionType.application_guide, application_guide_drafts),
    ):
        for order, draft in enumerate(drafts):
            db.add(
                GeneratedSection(
                    paper_id=paper_id,
                    section_type=section_type,
                    order=order,
                    title=_sanitize_generated_text(draft.heading, _GENERATED_SECTION_MAX_LENGTH),
                    content=_sanitize_generated_text(draft.body, _GENERATED_SECTION_MAX_LENGTH),
                    claim_ids=[str(claim_id) for claim_id in draft.claim_ids],
                )
            )

    for order, quiz_draft in enumerate(quiz_drafts):
        db.add(
            LearningQuizQuestion(
                paper_id=paper_id,
                order=order,
                question=_sanitize_generated_text(quiz_draft.question, _GENERATED_SECTION_MAX_LENGTH),
                options=(
                    [_sanitize_generated_text(option, _GENERATED_SECTION_MAX_LENGTH) for option in quiz_draft.options]
                    if quiz_draft.options is not None
                    else None
                ),
                correct_answer=_sanitize_generated_text(quiz_draft.correct_answer, _GENERATED_SECTION_MAX_LENGTH),
                explanation=_sanitize_generated_text(quiz_draft.explanation, _GENERATED_SECTION_MAX_LENGTH),
                claim_ids=[str(claim_id) for claim_id in quiz_draft.claim_ids],
            )
        )

    for order, derivation_draft in enumerate(derivation_drafts):
        db.add(
            LearningDerivation(
                paper_id=paper_id,
                order=order,
                title=_sanitize_generated_text(derivation_draft.title, _GENERATED_SECTION_MAX_LENGTH),
                steps=[
                    {
                        "explanation": _sanitize_generated_text(step.explanation, _GENERATED_SECTION_MAX_LENGTH),
                        "formula": _sanitize_generated_text(step.formula, _GENERATED_SECTION_MAX_LENGTH),
                        "claim_ids": [str(claim_id) for claim_id in step.claim_ids],
                    }
                    for step in derivation_draft.steps
                ],
            )
        )

    for order, interactive_draft in enumerate(interactive_drafts):
        db.add(
            LearningInteractive(
                paper_id=paper_id,
                order=order,
                title=_sanitize_generated_text(interactive_draft.title, _GENERATED_SECTION_MAX_LENGTH),
                description=_sanitize_generated_text(interactive_draft.description, _GENERATED_SECTION_MAX_LENGTH),
                # `formula` is NOT sanitized with the markup-stripping regex
                # -- it isn't display prose, it's already-validated by
                # app.evidence.formula.validate_formula (interactive.py),
                # which is the correct control for this field; running the
                # same regex over it could corrupt a legitimate expression.
                formula=interactive_draft.formula,
                output_label=_sanitize_generated_text(interactive_draft.output_label, _GENERATED_SECTION_MAX_LENGTH),
                parameters=[
                    {
                        "name": param.name,
                        "label": _sanitize_generated_text(param.label, _GENERATED_SECTION_MAX_LENGTH),
                        "min": param.min,
                        "max": param.max,
                        "step": param.step,
                        "default": param.default,
                        "unit": param.unit,
                    }
                    for param in interactive_draft.parameters
                ],
                claim_ids=[str(claim_id) for claim_id in interactive_draft.claim_ids],
            )
        )

    if figure_links is not None:
        await replace_figure_links(db, paper_id, figures, figure_links)

    await db.commit()


async def _persist_extraction(db: AsyncSession, paper_id: uuid.UUID, extraction: ExtractionResult) -> list[Claim]:
    """Replaces any previous analysis for this paper (idempotent re-run) and
    inserts the new Evidence/Claim/SourceReference/Metric/GlossaryTerm rows.
    Raises ``ClaimMissingSourceRefsError`` -- and persists nothing -- if any
    claim has zero source refs (defense-in-depth; the extraction schema
    already enforces this, see ``schemas.ClaimExtraction``).
    """
    for claim in extraction.claims:
        if not claim.source_refs:
            raise ClaimMissingSourceRefsError(f"Claim {claim.statement!r} has zero source_refs")

    await db.execute(delete(Claim).where(Claim.paper_id == paper_id))
    await db.execute(delete(Metric).where(Metric.paper_id == paper_id))
    await db.execute(delete(GlossaryTerm).where(GlossaryTerm.paper_id == paper_id))
    await db.execute(delete(Evidence).where(Evidence.paper_id == paper_id))

    db.add(
        Evidence(
            paper_id=paper_id,
            thesis=_sanitize_narrative_field(extraction.narrative.thesis),
            plain_summary=_sanitize_narrative_field(extraction.narrative.plain_summary),
            research_question=_sanitize_narrative_field(extraction.narrative.research_question),
        )
    )

    persisted_claims: list[Claim] = []
    for extracted_claim in extraction.claims:
        # statement is LLM-produced prose (never the verbatim source_refs
        # excerpt, which is a quotation and must never be touched) -- same
        # sanitization risk category as narrative fields/generated sections
        # (security review: this was missing here despite the "applied
        # uniformly" intent above).
        claim = Claim(
            paper_id=paper_id,
            statement=_sanitize_narrative_field(extracted_claim.statement),
            kind=extracted_claim.kind,
        )
        # Assigned via the relationship (not `claim_id=claim.id`) so SQLAlchemy's
        # unit-of-work fills in the foreign key at flush time -- `claim.id`'s
        # client-side default isn't evaluated until flush, so it isn't set yet here.
        claim.source_refs = [
            SourceReference(page=ref.page, excerpt=ref.excerpt, locator=ref.locator)
            for ref in extracted_claim.source_refs
        ]
        db.add(claim)
        persisted_claims.append(claim)

    for metric in extraction.metrics:
        # label/display_value/unit/context are LLM-produced descriptions, not
        # quotations -- source_excerpt (the verbatim quote) is deliberately
        # left untouched below.
        db.add(
            Metric(
                paper_id=paper_id,
                label=_sanitize_narrative_field(metric.label),
                value=metric.value,
                display_value=_sanitize_narrative_field(metric.display_value),
                unit=_sanitize_optional_narrative_field(metric.unit),
                context=_sanitize_optional_narrative_field(metric.context),
                source_page=metric.source_page,
                source_excerpt=metric.source_excerpt,
            )
        )

    for term in extraction.glossary:
        definition = _sanitize_narrative_field(term.definition)
        # Defense-in-depth (security review): the prompt asks the model to
        # prefix unsourced definitions itself, but that's an instruction, not
        # an enforcement -- a claim with source_page=None and an unlabeled
        # definition would otherwise persist looking indistinguishable from a
        # paper-grounded one. Enforce it here regardless of what the model did.
        if term.source_page is None and not definition.startswith(_GLOSSARY_UNSOURCED_PREFIX):
            definition = f"{_GLOSSARY_UNSOURCED_PREFIX}{definition}"
        db.add(
            GlossaryTerm(
                paper_id=paper_id,
                term=_sanitize_narrative_field(term.term),
                definition=definition,
                source_page=term.source_page,
                source_excerpt=term.source_excerpt,
            )
        )

    await db.commit()
    return persisted_claims


async def generate_implementation_plan(
    db: AsyncSession,
    paper_id: uuid.UUID,
    *,
    provider_id: str,
    api_key: str | None,
    endpoint: str | None,
    model: str,
) -> list[GeneratedSectionResponse]:
    """Generates and persists the implementation plan for a paper (docs/
    ARCHITECTURE.md's Code Research (Phase 8) section -- the safe,
    non-subprocess interpretation of PRD.md's Marcus journey). A single
    request/response call, not a multi-stage SSE pipeline like
    ``run_analysis``: this is one generation call over already-persisted
    evidence, so there's no multi-stage progress to stream.

    Raises ``EvidenceNotFoundError`` if analysis hasn't been run yet for
    this paper. Provider/generation failures
    (``ProviderNotFoundError``/``InvalidConfigError`` from ``build_provider``,
    a bare ``NotImplementedError`` translated to ``InvalidConfigError`` same
    as ``app.graph.router._build_provider_or_raise``;
    ``StructuredOutputError``/``ProviderUnavailableError``/
    ``AuthenticationError``/``NotSupportedError``/
    ``SectionReferencesUnknownClaimError`` from
    ``generate_implementation_plan_sections``) propagate directly to the
    router rather than being caught here -- unlike ``run_analysis``'s
    stages, this call has no SSE event stream to report an error event on.
    """
    evidence_row = await db.scalar(select(Evidence).where(Evidence.paper_id == paper_id))
    if evidence_row is None:
        raise EvidenceNotFoundError(
            f"No evidence found for paper {paper_id} -- run analysis before generating an implementation plan"
        )

    claims = await _load_claims_for_prompt(db, paper_id)
    metrics = await _load_metrics_for_prompt(db, paper_id)
    readme_text = await _load_linked_repo_readme(db, paper_id)

    try:
        provider: AIProvider = redacting(build_provider(provider_id, api_key=api_key, endpoint=endpoint), api_key)
    except NotImplementedError as exc:
        raise InvalidConfigError(str(exc)) from exc
    drafts = await generate_implementation_plan_sections(
        provider, claims=claims, metrics=metrics, readme_text=readme_text, model=model
    )
    await _persist_sections(db, paper_id, SectionType.implementation_plan, drafts)
    return await get_implementation_plan(db, paper_id)


async def get_implementation_plan(db: AsyncSession, paper_id: uuid.UUID) -> list[GeneratedSectionResponse]:
    """Ordered implementation-plan steps for this paper. Raises
    ``ImplementationPlanNotFoundError`` if it hasn't been generated yet."""
    rows = (
        await db.scalars(
            select(GeneratedSection)
            .where(
                GeneratedSection.paper_id == paper_id,
                GeneratedSection.section_type == SectionType.implementation_plan,
            )
            .order_by(GeneratedSection.order)
        )
    ).all()
    if not rows:
        raise ImplementationPlanNotFoundError(
            f"No implementation plan found for paper {paper_id} -- has it been generated yet?"
        )
    return [GeneratedSectionResponse.model_validate(row) for row in rows]


async def _load_linked_repo_readme(db: AsyncSession, paper_id: uuid.UUID) -> str | None:
    """Best-effort enrichment: a missing linked repository, or a README
    that's unreachable/absent on GitHub, degrades to "no README" rather than
    failing plan generation -- the README is enrichment, not a requirement
    (unlike a claim's source_refs, which are). No token is used here (the
    implementation-plan request carries no per-call GitHub token, unlike the
    repositories/detect route) -- public repos only, consistent with
    ``fetch_repo_metadata``'s own "token is optional, never required" rule.
    """
    repository = await coderesearch_service.get_paper_repository(db, paper_id)
    if repository is None:
        return None
    try:
        return await fetch_readme(repository.owner, repository.name, None)
    except (GithubNotFoundError, GithubUnavailableError) as exc:
        logger.warning(
            "implementation_plan_readme_fetch_failed paper_id=%s repository_id=%s error=%s",
            paper_id,
            repository.id,
            exc,
        )
        return None


async def reverify_claim(db: AsyncSession, claim_id: uuid.UUID) -> Claim:
    """Re-runs only the verifier (no LLM) against an existing claim's
    source_refs and the paper's current parsed page text."""
    claim = await db.get(Claim, claim_id)
    if claim is None:
        raise ClaimNotFoundError(f"Claim {claim_id} not found")

    page_rows = (await db.scalars(select(Page).where(Page.paper_id == claim.paper_id))).all()
    pages_by_number = {p.page_number: p.text for p in page_rows}

    refs = [(ref.page, ref.excerpt) for ref in claim.source_refs]
    claim.verification_status = verify_claim_status(refs, pages_by_number)
    await db.commit()
    return claim


async def get_evidence(db: AsyncSession, paper_id: uuid.UUID) -> EvidenceResponse:
    """Assembles the full evidence view for a paper: narrative fields from
    the ``Evidence`` row, methods/findings/limitations derived from that
    paper's claims filtered by ``kind``, plus the full claims/metrics/
    glossary lists."""
    evidence_row = await db.scalar(select(Evidence).where(Evidence.paper_id == paper_id))
    if evidence_row is None:
        raise EvidenceNotFoundError(f"No evidence found for paper {paper_id} -- has analysis been run?")

    claim_rows = (
        await db.scalars(select(Claim).where(Claim.paper_id == paper_id).order_by(Claim.created_at))
    ).all()
    metric_rows = (await db.scalars(select(Metric).where(Metric.paper_id == paper_id))).all()
    glossary_rows = (await db.scalars(select(GlossaryTerm).where(GlossaryTerm.paper_id == paper_id))).all()

    claims = [ClaimResponse.model_validate(row) for row in claim_rows]

    return EvidenceResponse(
        paper_id=paper_id,
        thesis=evidence_row.thesis,
        plain_summary=evidence_row.plain_summary,
        research_question=evidence_row.research_question,
        methods=[c for c in claims if c.kind == ClaimKind.method],
        findings=[c for c in claims if c.kind == ClaimKind.reported_result],
        limitations=[c for c in claims if c.kind == ClaimKind.limitation],
        claims=claims,
        metrics=[MetricResponse.model_validate(row) for row in metric_rows],
        glossary=[GlossaryTermResponse.model_validate(row) for row in glossary_rows],
    )


async def get_report(db: AsyncSession, paper_id: uuid.UUID) -> list[GeneratedSectionResponse]:
    """Ordered deep-report sections for this paper. Raises
    ``ReportNotFoundError`` if the report stage hasn't been run yet."""
    rows = (
        await db.scalars(
            select(GeneratedSection)
            .where(GeneratedSection.paper_id == paper_id, GeneratedSection.section_type == SectionType.report)
            .order_by(GeneratedSection.order)
        )
    ).all()
    if not rows:
        raise ReportNotFoundError(f"No report found for paper {paper_id} -- has the report stage been run?")
    return [GeneratedSectionResponse.model_validate(row) for row in rows]


async def get_technical_appendix(db: AsyncSession, paper_id: uuid.UUID) -> list[GeneratedSectionResponse]:
    """Ordered technical-appendix sections for this paper. Raises
    ``TechnicalAppendixNotFoundError`` if the technical stage hasn't been run
    yet."""
    rows = (
        await db.scalars(
            select(GeneratedSection)
            .where(GeneratedSection.paper_id == paper_id, GeneratedSection.section_type == SectionType.technical)
            .order_by(GeneratedSection.order)
        )
    ).all()
    if not rows:
        raise TechnicalAppendixNotFoundError(
            f"No technical appendix found for paper {paper_id} -- has the technical stage been run?"
        )
    return [GeneratedSectionResponse.model_validate(row) for row in rows]


async def get_story(db: AsyncSession, paper_id: uuid.UUID) -> list[GeneratedSectionResponse]:
    """Ordered StorySpec sections for this paper. Raises
    ``StoryNotFoundError`` if the visual stage hasn't been run yet."""
    rows = (
        await db.scalars(
            select(GeneratedSection)
            .where(GeneratedSection.paper_id == paper_id, GeneratedSection.section_type == SectionType.story)
            .order_by(GeneratedSection.order)
        )
    ).all()
    if not rows:
        raise StoryNotFoundError(f"No story found for paper {paper_id} -- has the visual stage been run?")
    return [GeneratedSectionResponse.model_validate(row) for row in rows]


async def get_story_spec(db: AsyncSession, paper_id: uuid.UUID) -> StorySpecResponse:
    """The typed StorySpec. Raises ``StoryNotFoundError`` if the visual stage
    hasn't run, or only produced a legacy story (sections with no ``data``,
    from before typed visuals) -- ``get_story`` still serves those."""
    story = await db.scalar(select(Story).where(Story.paper_id == paper_id))
    rows = (
        await db.scalars(
            select(GeneratedSection)
            .where(GeneratedSection.paper_id == paper_id, GeneratedSection.section_type == SectionType.story)
            .order_by(GeneratedSection.order)
        )
    ).all()
    if story is None or not rows or any(row.data is None for row in rows):
        raise StoryNotFoundError(f"No story spec found for paper {paper_id} -- has the visual stage been run?")
    return StorySpecResponse(
        meta={
            "title": story.title,
            "dek": story.dek,
            "reading_time": story.reading_time,
            "closing": story.closing,
        },
        sections=[
            StorySectionResponse(
                id=row.id,
                index_label=row.data["index_label"],
                kicker=row.data["kicker"],
                title=row.title,
                body=row.content,
                claim_ids=row.claim_ids,
                visual=row.data["visual"],
            )
            for row in rows
        ],
    )


async def get_figures(db: AsyncSession, paper_id: uuid.UUID) -> list[FigureResponse]:
    return await list_figures(db, paper_id)


async def get_learning(db: AsyncSession, paper_id: uuid.UUID) -> LearningResponse:
    """Assembles the bundled Learning Layer for a paper: primer/application
    guide sections, quiz questions, and derivations -- same bundling pattern
    as ``get_evidence``. Raises ``LearningNotFoundError`` if the visual stage
    hasn't been run yet (checked via the primer sections, since all four
    Learning Layer content types are generated and persisted together by the
    same visual-stage run)."""
    primer_rows = (
        await db.scalars(
            select(GeneratedSection)
            .where(GeneratedSection.paper_id == paper_id, GeneratedSection.section_type == SectionType.primer)
            .order_by(GeneratedSection.order)
        )
    ).all()
    if not primer_rows:
        raise LearningNotFoundError(f"No learning layer found for paper {paper_id} -- has the visual stage been run?")

    application_guide_rows = (
        await db.scalars(
            select(GeneratedSection)
            .where(
                GeneratedSection.paper_id == paper_id,
                GeneratedSection.section_type == SectionType.application_guide,
            )
            .order_by(GeneratedSection.order)
        )
    ).all()
    quiz_rows = (
        await db.scalars(
            select(LearningQuizQuestion)
            .where(LearningQuizQuestion.paper_id == paper_id)
            .order_by(LearningQuizQuestion.order)
        )
    ).all()
    derivation_rows = (
        await db.scalars(
            select(LearningDerivation)
            .where(LearningDerivation.paper_id == paper_id)
            .order_by(LearningDerivation.order)
        )
    ).all()
    interactive_rows = (
        await db.scalars(
            select(LearningInteractive)
            .where(LearningInteractive.paper_id == paper_id)
            .order_by(LearningInteractive.order)
        )
    ).all()

    return LearningResponse(
        paper_id=paper_id,
        primer=[GeneratedSectionResponse.model_validate(row) for row in primer_rows],
        application_guide=[GeneratedSectionResponse.model_validate(row) for row in application_guide_rows],
        quiz=[QuizQuestionResponse.model_validate(row) for row in quiz_rows],
        derivations=[DerivationResponse.model_validate(row) for row in derivation_rows],
        interactives=[InteractiveResponse.model_validate(row) for row in interactive_rows],
    )
