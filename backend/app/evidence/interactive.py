"""Interactive learning-content derivation (docs/DATA_MODEL.md's
``LearningLayer`` Interactive) -- numeric-slider formula playgrounds.

Same shape as ``app.evidence.report``/``app.evidence.technical``/
``app.evidence.learning``: build a prompt, call the given ``AIProvider`` for
structured output, validate every ``claim_id`` against this paper's real
claims before handing the result back to ``app.evidence.service`` for
persistence. Nothing here persists anything.

The one thing unique to this content type: every draft's ``formula`` is
additionally run through ``app.evidence.formula`` (the restricted-grammar AST
validator, SECURITY.md's "never eval, never arbitrary JS" requirement)
*before* it is accepted. ``provider.generate`` already retries once on a raw
JSON-schema mismatch (AI_PROVIDERS.md), but that retry loop has no idea a
formula string can itself be invalid -- schema validation happily accepts
``"1 / x"`` as a string. So this module runs its own one-retry-with-feedback
loop on top, specifically for the formula-grammar failure mode, and raises
``InteractiveFormulaInvalidError`` (never a second silent retry, never an
unvalidated formula slipping through) if the second attempt is still bad.
"""

import uuid
from typing import cast

from app.evidence.exceptions import (
    FormulaEvaluationError,
    FormulaValidationError,
    InteractiveFormulaInvalidError,
    InteractiveReferencesUnknownClaimError,
)
from app.evidence.formula import assert_parameter_names_allowed, evaluate_formula, validate_formula
from app.evidence.prompts.interactive import build_interactive_prompt
from app.evidence.schemas import ClaimForPrompt, InteractiveDraft, InteractivesOutput, MetricForPrompt
from app.models.claim import ClaimKind
from app.providers.base import AIProvider

_INTERACTIVE_CLAIM_KINDS = frozenset({ClaimKind.method, ClaimKind.reported_result})


async def generate_interactives(
    provider: AIProvider,
    *,
    claims: list[ClaimForPrompt],
    metrics: list[MetricForPrompt],
    model: str,
) -> list[InteractiveDraft]:
    """Raises ``InteractiveReferencesUnknownClaimError`` if any interactive
    cites a claim outside the paper's real claims, or
    ``InteractiveFormulaInvalidError`` if a formula still fails grammar
    validation after one retry -- nothing is returned for the caller to
    persist in either case.
    """
    relevant_claims = [claim for claim in claims if claim.kind in _INTERACTIVE_CLAIM_KINDS]
    prompt = build_interactive_prompt(claims=relevant_claims, metrics=metrics)
    opts: dict[str, object] = {"model": model}
    known_claim_ids = {claim.id for claim in claims}

    output = cast(InteractivesOutput, await provider.generate(prompt, InteractivesOutput, **opts))
    error_detail = _first_formula_error(output.interactives)
    if error_detail is None:
        _reject_unknown_claim_ids(output.interactives, known_claim_ids)
        return output.interactives

    retry_prompt = (
        f"{prompt}\n\n"
        f"Your previous response used an invalid formula: {error_detail}\n"
        "Return ONLY corrected JSON matching the schema, using exclusively "
        "the whitelisted operators/functions described above."
    )
    retry_output = cast(InteractivesOutput, await provider.generate(retry_prompt, InteractivesOutput, **opts))
    retry_error_detail = _first_formula_error(retry_output.interactives)
    if retry_error_detail is not None:
        raise InteractiveFormulaInvalidError(
            f"Model produced an invalid interactive formula twice: {retry_error_detail}"
        )

    _reject_unknown_claim_ids(retry_output.interactives, known_claim_ids)
    return retry_output.interactives


def _first_formula_error(drafts: list[InteractiveDraft]) -> str | None:
    """Runs every draft's formula through the grammar validator, plus a
    smoke-evaluation at the draft's own default parameter values (so a
    formula that's syntactically fine but immediately divides by zero at its
    own defaults is caught here too, not just at grammar-parse time) --
    returns the first failure's message, or ``None`` if every draft is
    clean.
    """
    for draft in drafts:
        try:
            names = [param.name for param in draft.parameters]
            if len(names) != len(set(names)):
                raise FormulaValidationError(f"interactive {draft.title!r}: duplicate parameter names")
            parameter_names = frozenset(names)
            assert_parameter_names_allowed(parameter_names)
            tree = validate_formula(draft.formula, parameter_names)
            evaluate_formula(tree, {param.name: param.default for param in draft.parameters})
        except (FormulaValidationError, FormulaEvaluationError) as exc:
            return f"interactive {draft.title!r}: {exc}"
    return None


def _reject_unknown_claim_ids(drafts: list[InteractiveDraft], known_claim_ids: set[uuid.UUID]) -> None:
    for draft in drafts:
        unknown = [str(claim_id) for claim_id in draft.claim_ids if claim_id not in known_claim_ids]
        if unknown:
            raise InteractiveReferencesUnknownClaimError(
                f"Interactive {draft.title!r} references unknown claim_id(s): {', '.join(unknown)}"
            )
