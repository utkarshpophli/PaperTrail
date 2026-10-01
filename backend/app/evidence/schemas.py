"""Pydantic schemas for the Evidence Engine: structured-output shapes the
extraction passes force the model through, plus the API-facing response
shapes ``service.get_evidence`` assembles.

Every extraction schema requires ``source_refs``/``source_page`` +
``source_excerpt`` per item — this is the schema-enforced half of
AI_PROVIDERS.md's "every extraction-stage prompt requires the model to emit
source_refs ... enforced by the output schema, not just prompt instruction."
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.evidence.formula import MAX_FORMULA_LENGTH
from app.models.claim import ClaimKind, VerificationStatus

# --- analysis request shapes ------------------------------------------------


class StageConfig(BaseModel):
    """Provider/model assignment for one analysis stage (``"evidence"`` |
    ``"technical"`` | ``"report"`` | ``"visual"`` per API_SPEC.md's
    ``POST /papers/{id}/analyze`` docstring). Lives here rather than in
    ``app.evidence.router`` because both the router (request body) and
    ``app.evidence.service.run_analysis`` (function signature) need the same
    shape without one importing from the other.
    """

    provider_id: str
    api_key: str | None = None
    endpoint: str | None = None
    model: str = Field(min_length=1, max_length=200)


# --- extraction-pass input/output shapes -----------------------------------


class PageText(BaseModel):
    """Minimal page representation extraction/verifier code needs — decouples
    both from the ``Page`` ORM model so neither has to import SQLAlchemy."""

    number: int
    text: str


class SourceRefExtraction(BaseModel):
    page: int
    excerpt: str = Field(min_length=1)
    locator: str | None = None


class ClaimExtraction(BaseModel):
    statement: str = Field(min_length=1)
    kind: ClaimKind
    # min_length=1: DATA_MODEL.md's "a claim with zero source_refs is
    # rejected at the schema level" — enforced here, before persistence ever
    # sees the claim.
    source_refs: list[SourceRefExtraction] = Field(min_length=1)


class ClaimsExtractionOutput(BaseModel):
    claims: list[ClaimExtraction] = Field(default_factory=list)


class MetricExtraction(BaseModel):
    label: str = Field(min_length=1)
    value: str = Field(min_length=1)
    display_value: str = Field(min_length=1)
    unit: str | None = None
    context: str | None = None
    source_page: int
    source_excerpt: str = Field(min_length=1)


class MetricsExtractionOutput(BaseModel):
    metrics: list[MetricExtraction] = Field(default_factory=list)


class GlossaryTermExtraction(BaseModel):
    term: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    source_page: int | None = None
    source_excerpt: str | None = None


class GlossaryExtractionOutput(BaseModel):
    terms: list[GlossaryTermExtraction] = Field(default_factory=list)


class NarrativeExtraction(BaseModel):
    thesis: str = Field(min_length=1)
    plain_summary: str = Field(min_length=1)
    research_question: str = Field(min_length=1)


class ExtractionResult(BaseModel):
    """Merged output of the four parallel passes (``extraction.run_extraction``)."""

    claims: list[ClaimExtraction]
    metrics: list[MetricExtraction]
    glossary: list[GlossaryTermExtraction]
    narrative: NarrativeExtraction


# --- report/technical derivation input/output shapes ------------------------


class ClaimForPrompt(BaseModel):
    """Minimal claim representation fed into the report/technical generation
    prompts -- decouples ``app.evidence.report``/``app.evidence.technical``
    from the ``Claim`` ORM model, same rationale as ``PageText`` above.

    ``statement``/``excerpts`` originated from an upstream LLM extraction
    pass over untrusted paper content -- verifier-checked, not guaranteed
    clean free text -- so callers must still pass this through
    ``prompts.shared.wrap_prompt``-style fencing, never concatenate it
    directly into an instructions string (this phase's second-order
    prompt-injection note).
    """

    id: uuid.UUID
    kind: ClaimKind
    statement: str
    excerpts: list[str]
    # Populated by the visual stage only (the story prompt shows it); other
    # prompts ignore it.
    verification_status: VerificationStatus | None = None


class MetricForPrompt(BaseModel):
    """Minimal metric representation fed into the technical-appendix prompt."""

    label: str
    value: str
    display_value: str
    unit: str | None = None
    context: str | None = None


# --- Research Assistant input/output shapes (Phase 4c) ----------------------


class AssistantClaimForPrompt(BaseModel):
    """Claim representation for Research Assistant retrieval/prompting --
    same decoupling rationale as ``ClaimForPrompt``, extended with
    ``verification_status`` because several actions (notably ``verify``)
    must surface it directly in the grounded answer, not just cite the
    claim id.
    """

    id: uuid.UUID
    kind: ClaimKind
    statement: str
    excerpts: list[str]
    verification_status: VerificationStatus


class GlossaryTermForPrompt(BaseModel):
    """Minimal glossary representation fed into the ``research`` assistant
    action's prompt."""

    term: str
    definition: str


class LearningExcerptForPrompt(BaseModel):
    """One primer/application-guide section, decoupled from
    ``GeneratedSectionResponse`` the same way ``ClaimForPrompt`` decouples
    from the ``Claim`` ORM model. Fed into the ``learn`` assistant action's
    prompt when a Learning Layer already exists for the paper."""

    heading: str
    body: str


class PaperContextForPrompt(BaseModel):
    """One paper's evidence, as fed into the ``compare`` assistant action --
    the primary paper and every paper in ``compare_with`` are represented
    identically. Claim ids are globally unique (not paper-scoped), so no
    per-paper qualifier is needed on ``claims``."""

    paper_id: uuid.UUID
    title: str
    thesis: str
    plain_summary: str
    research_question: str
    claims: list[AssistantClaimForPrompt]


class AssistantRetrievalContext(BaseModel):
    """The exact narrative/claims/metrics/glossary/learning-layer slice
    ``app.evidence.assistant.select_retrieval_context`` chose for one
    non-``compare`` action -- ``app.evidence.assistant.run_assistant_query``
    grounds its single ``provider.generate()`` call in exactly this, nothing
    broader. All fields default empty/``None`` so an action that doesn't use
    a given section (e.g. ``verify`` never needs metrics) simply omits it
    from the prompt instead of every call site repeating several empty-list
    arguments.
    """

    thesis: str | None = None
    plain_summary: str | None = None
    research_question: str | None = None
    claims: list[AssistantClaimForPrompt] = Field(default_factory=list)
    metrics: list[MetricForPrompt] = Field(default_factory=list)
    glossary: list[GlossaryTermForPrompt] = Field(default_factory=list)
    learning_excerpts: list[LearningExcerptForPrompt] = Field(default_factory=list)


class AssistantAnswerOutput(BaseModel):
    """Structured output every assistant action forces the model through.

    ``claim_ids`` is deliberately NOT ``min_length=1`` like the
    persisted-content drafts elsewhere in this file: the Research Assistant
    is stateless (nothing here is ever persisted -- no conversation history,
    no new DB table), and a citation that doesn't resolve to a real,
    accessible claim is filtered out rather than rejecting the whole answer
    (``app.evidence.assistant.run_assistant_query``) -- so an empty list
    after filtering is a valid, if degraded, result, not a schema violation.
    """

    # max_length matches _GENERATED_SECTION_MAX_LENGTH's existing precedent
    # (service.py) -- security review MEDIUM: this field previously had no
    # cap and, unlike every other generated content type, skipped the
    # markup-stripping sanitizer entirely before reaching the client.
    answer: str = Field(min_length=1, max_length=8000)
    claim_ids: list[uuid.UUID] = Field(default_factory=list)


class GeneratedSectionDraft(BaseModel):
    """One report/technical section as returned by the AI provider, before
    its ``claim_ids`` are checked against the paper's real claims.
    ``min_length=1`` on both fields mirrors ``ClaimExtraction.source_refs``:
    DATA_MODEL.md requires every claim-linked artifact's ``claim_ids`` to be
    non-empty, enforced at the schema level before persistence ever sees it.
    """

    # max_length matches GeneratedSection.title's actual column width
    # (String(512)) -- security review: without this, an over-length model
    # output passed schema validation and only failed at persistence with a
    # raw Postgres DataError instead of the normal one-retry-then-surface
    # path. Enforcing it here instead lets the existing retry recover.
    heading: str = Field(min_length=1, max_length=512)
    body: str = Field(min_length=1)
    claim_ids: list[uuid.UUID] = Field(min_length=1)


class GeneratedSectionsOutput(BaseModel):
    sections: list[GeneratedSectionDraft] = Field(min_length=1)


# --- quiz/derivation generation output shapes (visual stage) ----------------


class QuizQuestionDraft(BaseModel):
    """One quiz question as returned by the AI provider, before its
    ``claim_ids`` are checked against the paper's real claims. Same
    non-empty-``claim_ids`` enforcement as ``GeneratedSectionDraft``."""

    question: str = Field(min_length=1)
    options: list[str] | None = None
    # max_length matches LearningQuizQuestion.correct_answer's column width
    # (String(1024)) -- same over-length-crashes-persistence fix as above.
    correct_answer: str = Field(min_length=1, max_length=1024)
    explanation: str = Field(min_length=1)
    claim_ids: list[uuid.UUID] = Field(min_length=1)


class QuizQuestionsOutput(BaseModel):
    questions: list[QuizQuestionDraft] = Field(min_length=1)


class DerivationStepDraft(BaseModel):
    """``formula`` is inert display text (e.g. rendered math notation as a
    string) -- never evaluated, never passed through any expression parser.
    """

    explanation: str = Field(min_length=1)
    formula: str = Field(min_length=1)
    claim_ids: list[uuid.UUID] = Field(min_length=1)


class DerivationDraft(BaseModel):
    # max_length matches LearningDerivation.title's column width (String(512)).
    title: str = Field(min_length=1, max_length=512)
    steps: list[DerivationStepDraft] = Field(min_length=1)


class DerivationsOutput(BaseModel):
    derivations: list[DerivationDraft] = Field(min_length=1)


class InteractiveParameterDraft(BaseModel):
    """One numeric slider. Bounds are checked for basic sanity here (input
    validation at the schema boundary) -- whether ``formula`` actually uses
    ONLY these parameter names, and whether it's safe to evaluate at all, is
    ``app.evidence.formula.validate_formula``'s job, not this model's."""

    # Identifier-shaped: this is what a valid reference in `formula` actually
    # looks like on both the Python and JS sides, and closes off a
    # theoretical defense-in-depth gap (security review LOW) even though a
    # live check found no current renderer treats an arbitrary name unsafely.
    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=256)
    # allow_inf_nan=False: security review MEDIUM — Python's json.loads (used
    # on the raw provider response, structured_output.py) accepts the
    # non-standard NaN/Infinity/-Infinity tokens with no error, and the
    # min>=max / step<=0 checks below don't reject them either (NaN fails
    # every comparison silently; Infinity legitimately satisfies "step > 0").
    # Without this, a NaN/Infinity value only surfaces as a raw, unhandled
    # DBAPI error at commit time (Postgres's json/jsonb types are RFC-8259-
    # strict) instead of the normal one-retry-then-surface path.
    min: float = Field(allow_inf_nan=False)
    max: float = Field(allow_inf_nan=False)
    step: float = Field(allow_inf_nan=False)
    default: float = Field(allow_inf_nan=False)
    unit: str | None = None

    @model_validator(mode="after")
    def _check_bounds(self) -> "InteractiveParameterDraft":
        if self.min >= self.max:
            raise ValueError(f"parameter {self.name!r}: min ({self.min}) must be less than max ({self.max})")
        if not (self.min <= self.default <= self.max):
            raise ValueError(f"parameter {self.name!r}: default ({self.default}) must be within [min, max]")
        if self.step <= 0:
            raise ValueError(f"parameter {self.name!r}: step ({self.step}) must be positive")
        return self


class InteractiveDraft(BaseModel):
    """One interactive as returned by the AI provider, before its
    ``formula`` is run through the grammar validator (``app.evidence.formula``)
    and its ``claim_ids`` are checked against the paper's real claims.

    ``formula``'s ``max_length`` mirrors ``app.evidence.formula.MAX_FORMULA_LENGTH``
    -- the same length cap the grammar validator itself enforces, applied
    here too so an over-length formula is rejected at the same schema
    boundary as every other over-length draft field, feeding the existing
    one-retry-then-surface path.
    """

    title: str = Field(min_length=1, max_length=512)
    description: str = Field(min_length=1)
    parameters: list[InteractiveParameterDraft] = Field(min_length=1, max_length=4)
    formula: str = Field(min_length=1, max_length=MAX_FORMULA_LENGTH)
    output_label: str = Field(min_length=1, max_length=256)
    claim_ids: list[uuid.UUID] = Field(min_length=1)


class InteractivesOutput(BaseModel):
    interactives: list[InteractiveDraft] = Field(min_length=1)


# --- API-facing response shapes (the contract backend-engineer builds against) --


class SourceReferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    page: int
    excerpt: str
    locator: str | None


class ClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    statement: str
    kind: ClaimKind
    verification_status: VerificationStatus
    source_refs: list[SourceReferenceResponse]
    created_at: datetime


class MetricResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    value: str
    display_value: str
    unit: str | None
    context: str | None
    source_page: int
    source_excerpt: str


class GlossaryTermResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    term: str
    definition: str
    source_page: int | None
    source_excerpt: str | None


class GeneratedSectionResponse(BaseModel):
    """Shared response shape for both the Deep Report and Technical Appendix
    (``service.get_report`` / ``service.get_technical_appendix``) --
    DATA_MODEL.md's DeepReportSection/TechnicalAppendix entities differ only
    in which pipeline stage produced them, not in shape: every section is
    claim-linked (``claim_ids``, non-empty per DATA_MODEL.md) and ordered
    within its document.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    content: str
    order: int
    claim_ids: list[uuid.UUID]
    # Story rows carry {kicker, index_label, visual}; every other type is None.
    data: dict[str, Any] | None = None
    created_at: datetime


class EvidenceResponse(BaseModel):
    """Assembled by ``service.get_evidence``. ``methods``/``findings``/
    ``limitations`` are derived views over ``claims`` filtered by ``kind``
    (design decision #1 in this phase's task brief) — not separately stored.
    """

    paper_id: uuid.UUID
    thesis: str
    plain_summary: str
    research_question: str
    methods: list[ClaimResponse]
    findings: list[ClaimResponse]
    limitations: list[ClaimResponse]
    claims: list[ClaimResponse]
    metrics: list[MetricResponse]
    glossary: list[GlossaryTermResponse]


class QuizQuestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order: int
    question: str
    options: list[str] | None
    correct_answer: str
    explanation: str
    claim_ids: list[uuid.UUID]
    created_at: datetime


class DerivationStepResponse(BaseModel):
    explanation: str
    formula: str
    claim_ids: list[uuid.UUID]


class DerivationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order: int
    title: str
    steps: list[DerivationStepResponse]
    created_at: datetime


class InteractiveParameterResponse(BaseModel):
    name: str
    label: str
    min: float
    max: float
    step: float
    default: float
    unit: str | None


class InteractiveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str
    parameters: list[InteractiveParameterResponse]
    formula: str
    output_label: str
    claim_ids: list[uuid.UUID]
    created_at: datetime


class LearningResponse(BaseModel):
    """Assembled by ``service.get_learning`` -- bundles the five non-Story
    Learning Layer content types generated by the visual stage, same
    bundling pattern as ``EvidenceResponse``."""

    paper_id: uuid.UUID
    primer: list[GeneratedSectionResponse]
    application_guide: list[GeneratedSectionResponse]
    quiz: list[QuizQuestionResponse]
    derivations: list[DerivationResponse]
    interactives: list[InteractiveResponse]
