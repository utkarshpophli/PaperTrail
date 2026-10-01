"""Typed exceptions for the evidence domain — never a bare ``Exception``,
each maps to the API error envelope (API_SPEC.md Conventions)."""

from app.core.errors import AppError


class PaperNotParsedError(AppError):
    """Raised by ``run_analysis`` when the paper's ``parse_status`` isn't
    ``parsed`` yet — there is no page text to extract from or verify
    against."""

    status_code = 422
    code = "paper_not_parsed"


class EvidenceNotFoundError(AppError):
    """Raised by ``get_evidence`` when no analysis has been persisted yet
    for this paper."""

    status_code = 404
    code = "evidence_not_found"


class ClaimNotFoundError(AppError):
    status_code = 404
    code = "claim_not_found"


class ClaimMissingSourceRefsError(AppError):
    """A claim reached the persistence boundary with zero ``source_refs``.

    The extraction schema already enforces ``min_length=1`` on
    ``source_refs``, so this should never actually trigger — it exists as
    the service-layer backstop DATA_MODEL.md requires ("enforced at the
    Pydantic/service layer, not just the DB"), in case a future schema
    change or a provider that bypasses schema validation ever lets one
    through.
    """

    status_code = 422
    code = "claim_missing_source_refs"


class SectionReferencesUnknownClaimError(AppError):
    """A generated report/technical section emitted a ``claim_id`` that does
    not exist among this paper's persisted ``Claim`` rows. Raised before any
    ``GeneratedSection`` for the batch is persisted — DATA_MODEL.md's "a
    downstream artifact referencing a claim_id that doesn't exist ... is
    rejected before persistence", never silently dropped."""

    status_code = 422
    code = "section_references_unknown_claim"


class ReportNotFoundError(AppError):
    """Raised by ``get_report`` when no report sections have been persisted
    yet for this paper."""

    status_code = 404
    code = "report_not_found"


class TechnicalAppendixNotFoundError(AppError):
    """Raised by ``get_technical_appendix`` when no technical-appendix
    sections have been persisted yet for this paper."""

    status_code = 404
    code = "technical_appendix_not_found"


class QuizReferencesUnknownClaimError(AppError):
    """A generated quiz question emitted a ``claim_id`` that does not exist
    among this paper's persisted ``Claim`` rows. Raised before any
    ``LearningQuizQuestion`` for the batch is persisted -- same
    reject-the-whole-batch discipline as ``SectionReferencesUnknownClaimError``."""

    status_code = 422
    code = "quiz_references_unknown_claim"


class DerivationReferencesUnknownClaimError(AppError):
    """A generated derivation step emitted a ``claim_id`` that does not exist
    among this paper's persisted ``Claim`` rows. Raised before any
    ``LearningDerivation`` for the batch is persisted -- same
    reject-the-whole-batch discipline as ``SectionReferencesUnknownClaimError``."""

    status_code = 422
    code = "derivation_references_unknown_claim"


class StoryNotFoundError(AppError):
    """Raised by ``get_story`` when the visual stage hasn't been run yet for
    this paper."""

    status_code = 404
    code = "story_not_found"


class StoryIntegrityError(AppError):
    """A generated StorySpec broke an integrity rule that schema validation
    can't express (unknown claim id, comparison value not among the paper's
    metrics, a quote that isn't a verbatim source excerpt, too little visual
    variety, ...). Rejects the whole story batch -- nothing is persisted."""

    status_code = 422
    code = "story_integrity_failed"


class LearningNotFoundError(AppError):
    """Raised by ``get_learning`` when the visual stage hasn't been run yet
    for this paper -- the Learning Layer is generated alongside the story,
    same stage."""

    status_code = 404
    code = "learning_not_found"


class FormulaValidationError(AppError):
    """A formula string failed ``app.evidence.formula.validate_formula``'s
    restricted-grammar AST walk -- SECURITY.md's "restricted declarative
    grammar ... never eval" requirement. Raised before a single node of the
    formula is ever evaluated."""

    status_code = 422
    code = "formula_validation_failed"


class FormulaEvaluationError(AppError):
    """A syntactically-valid, already-validated formula produced an
    undefined result when evaluated: division by zero, a domain error
    (e.g. ``sqrt`` of a negative number), overflow, or a NaN/Infinity/complex
    result. This is the defined sentinel exception ``app.evidence.formula``
    raises instead of letting a raw Python exception (or a silently-returned
    NaN/inf) propagate."""

    status_code = 422
    code = "formula_evaluation_undefined"


class InteractiveReferencesUnknownClaimError(AppError):
    """A generated interactive emitted a ``claim_id`` that does not exist
    among this paper's persisted ``Claim`` rows. Raised before any
    ``LearningInteractive`` for the batch is persisted -- same
    reject-the-whole-batch discipline as ``SectionReferencesUnknownClaimError``."""

    status_code = 422
    code = "interactive_references_unknown_claim"


class AssistantActionNotSupportedError(AppError):
    """Raised when ``action`` isn't one of the 8 documented Research
    Assistant actions (API_SPEC.md's ``POST /papers/{id}/assistant``) --
    defense-in-depth backstop; the router's own request-body schema should
    already constrain this before it ever reaches the service layer."""

    status_code = 422
    code = "assistant_action_not_supported"


class ImplementationPlanNotFoundError(AppError):
    """Raised by ``get_implementation_plan`` when no implementation-plan
    sections have been persisted yet for this paper."""

    status_code = 404
    code = "implementation_plan_not_found"


class InteractiveFormulaInvalidError(AppError):
    """A generated interactive's formula failed
    ``app.evidence.formula.validate_formula`` twice in a row (JSON-schema
    validation passed both times -- this is a semantic failure on top of
    that, not a shape failure) -- AI_PROVIDERS.md's "one retry ... a second
    failure surfaces to the user", applied to this content type's
    formula-specific validation layer."""

    status_code = 422
    code = "interactive_formula_invalid"
