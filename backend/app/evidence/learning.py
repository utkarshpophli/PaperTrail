"""Learning Layer derivation -- Primer, Application Guide, Quiz, Derivation
(docs/DATA_MODEL.md's ``LearningLayer``; Interactive is explicitly out of
scope this phase).

Same shape as ``app.evidence.report``/``app.evidence.technical``: build a
prompt, call the given ``AIProvider`` for structured output, validate every
``claim_id`` emitted against this paper's real claims before handing the
result back to ``app.evidence.service`` for persistence. Nothing here
persists anything.

Primer/Application Guide reuse ``GeneratedSectionDraft`` (design decision #1)
and are validated the same way as ``report.py``/``technical.py``. Quiz and
Derivation have their own draft shapes and are validated the same way, just
against ``QuizReferencesUnknownClaimError``/``DerivationReferencesUnknownClaimError``
instead of ``SectionReferencesUnknownClaimError``, so a router/log message
can tell which content type failed.

``claim_ids`` are validated against *all* of the paper's claims passed in,
not just whichever kind-filtered subset fed a given prompt -- same
strict-superset rule ``technical.py`` documents, so filtering a prompt's own
content never makes validation more permissive.
"""

import uuid

from app.evidence.claim_check import generate_with_claim_check
from app.evidence.exceptions import (
    DerivationReferencesUnknownClaimError,
    QuizReferencesUnknownClaimError,
    SectionReferencesUnknownClaimError,
)
from app.evidence.prompts.application_guide import build_application_guide_prompt
from app.evidence.prompts.derivation import build_derivation_prompt
from app.evidence.prompts.primer import build_primer_prompt
from app.evidence.prompts.quiz import build_quiz_prompt
from app.evidence.schemas import (
    ClaimForPrompt,
    DerivationDraft,
    DerivationsOutput,
    GeneratedSectionDraft,
    GeneratedSectionsOutput,
    MetricForPrompt,
    QuizQuestionDraft,
    QuizQuestionsOutput,
)
from app.models.claim import ClaimKind
from app.providers.base import AIProvider

_PRIMER_CLAIM_KINDS = frozenset({ClaimKind.background, ClaimKind.method})
_APPLICATION_GUIDE_CLAIM_KINDS = frozenset({ClaimKind.method, ClaimKind.reported_result})
_DERIVATION_CLAIM_KINDS = frozenset({ClaimKind.method, ClaimKind.reported_result})


async def generate_primer_sections(
    provider: AIProvider, *, claims: list[ClaimForPrompt], model: str
) -> list[GeneratedSectionDraft]:
    """Same failure modes as ``report.generate_report_sections``."""
    relevant_claims = [claim for claim in claims if claim.kind in _PRIMER_CLAIM_KINDS]
    prompt = build_primer_prompt(claims=relevant_claims)
    known_claim_ids = {claim.id for claim in claims}
    output = await generate_with_claim_check(
        provider,
        prompt,
        GeneratedSectionsOutput,
        model=model,
        check=lambda out: _reject_unknown_section_claim_ids("Primer", out.sections, known_claim_ids),
    )
    return output.sections


async def generate_application_guide_sections(
    provider: AIProvider,
    *,
    claims: list[ClaimForPrompt],
    metrics: list[MetricForPrompt],
    model: str,
) -> list[GeneratedSectionDraft]:
    """Same failure modes as ``report.generate_report_sections``."""
    relevant_claims = [claim for claim in claims if claim.kind in _APPLICATION_GUIDE_CLAIM_KINDS]
    prompt = build_application_guide_prompt(claims=relevant_claims, metrics=metrics)
    known_claim_ids = {claim.id for claim in claims}
    output = await generate_with_claim_check(
        provider,
        prompt,
        GeneratedSectionsOutput,
        model=model,
        check=lambda out: _reject_unknown_section_claim_ids("Application guide", out.sections, known_claim_ids),
    )
    return output.sections


async def generate_quiz_questions(
    provider: AIProvider, *, claims: list[ClaimForPrompt], model: str
) -> list[QuizQuestionDraft]:
    """Raises ``QuizReferencesUnknownClaimError`` (instead of
    ``SectionReferencesUnknownClaimError``) if a question cites a claim
    outside the paper's real claims -- nothing is returned for the caller to
    persist either way."""
    prompt = build_quiz_prompt(claims=claims)
    known_claim_ids = {claim.id for claim in claims}

    def check(out: QuizQuestionsOutput) -> None:
        for question in out.questions:
            unknown = [str(claim_id) for claim_id in question.claim_ids if claim_id not in known_claim_ids]
            if unknown:
                raise QuizReferencesUnknownClaimError(
                    f"Quiz question {question.question!r} references unknown claim_id(s): {', '.join(unknown)}"
                )

    output = await generate_with_claim_check(provider, prompt, QuizQuestionsOutput, model=model, check=check)
    return output.questions


async def generate_derivations(
    provider: AIProvider,
    *,
    claims: list[ClaimForPrompt],
    metrics: list[MetricForPrompt],
    model: str,
) -> list[DerivationDraft]:
    """Raises ``DerivationReferencesUnknownClaimError`` if any step cites a
    claim outside the paper's real claims -- nothing is returned for the
    caller to persist either way."""
    relevant_claims = [claim for claim in claims if claim.kind in _DERIVATION_CLAIM_KINDS]
    prompt = build_derivation_prompt(claims=relevant_claims, metrics=metrics)
    known_claim_ids = {claim.id for claim in claims}

    def check(out: DerivationsOutput) -> None:
        for derivation in out.derivations:
            for step in derivation.steps:
                unknown = [str(claim_id) for claim_id in step.claim_ids if claim_id not in known_claim_ids]
                if unknown:
                    raise DerivationReferencesUnknownClaimError(
                        f"Derivation {derivation.title!r} step references unknown claim_id(s): {', '.join(unknown)}"
                    )

    output = await generate_with_claim_check(provider, prompt, DerivationsOutput, model=model, check=check)
    return output.derivations


def _reject_unknown_section_claim_ids(
    label: str, sections: list[GeneratedSectionDraft], known_claim_ids: set[uuid.UUID]
) -> None:
    for section in sections:
        unknown = [str(claim_id) for claim_id in section.claim_ids if claim_id not in known_claim_ids]
        if unknown:
            raise SectionReferencesUnknownClaimError(
                f"{label} section {section.heading!r} references unknown claim_id(s): {', '.join(unknown)}"
            )
