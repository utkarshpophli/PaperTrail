"""Technical appendix derivation (docs/DATA_MODEL.md's ``TechnicalAppendix``).

Same shape as ``report.py`` (build prompt, call the provider, validate
``claim_ids``), but the prompt is fed only ``method``/``reported-result``/
``background`` claims plus metrics -- the kinds relevant to a reader deciding
whether to implement the paper's approach (this phase's task brief).
``claim_ids`` are still validated against *all* of the paper's claims, not
just that filtered subset, per DATA_MODEL.md's "validated ... resolvable
against the paper's evidence" (a strict superset check, so filtering the
prompt's own content never makes validation more permissive).
"""

import uuid

from app.evidence.claim_check import generate_with_claim_check
from app.evidence.exceptions import SectionReferencesUnknownClaimError
from app.evidence.prompts.technical import build_technical_prompt
from app.evidence.schemas import ClaimForPrompt, GeneratedSectionDraft, GeneratedSectionsOutput, MetricForPrompt
from app.models.claim import ClaimKind
from app.providers.base import AIProvider

_TECHNICAL_CLAIM_KINDS = frozenset({ClaimKind.method, ClaimKind.reported_result, ClaimKind.background})


async def generate_technical_sections(
    provider: AIProvider,
    *,
    claims: list[ClaimForPrompt],
    metrics: list[MetricForPrompt],
    model: str,
) -> list[GeneratedSectionDraft]:
    """Runs the technical-appendix generation pass. Same failure modes as
    ``report.generate_report_sections``: ``StructuredOutputError`` from the
    provider, or ``SectionReferencesUnknownClaimError`` if a section cites a
    claim outside this paper's real claims -- either way, nothing is
    returned for the caller to persist.
    """
    relevant_claims = [claim for claim in claims if claim.kind in _TECHNICAL_CLAIM_KINDS]
    prompt = build_technical_prompt(claims=relevant_claims, metrics=metrics)
    known_claim_ids = {claim.id for claim in claims}
    output = await generate_with_claim_check(
        provider,
        prompt,
        GeneratedSectionsOutput,
        model=model,
        check=lambda out: _reject_unknown_claim_ids(out.sections, known_claim_ids),
    )
    return output.sections


def _reject_unknown_claim_ids(sections: list[GeneratedSectionDraft], known_claim_ids: set[uuid.UUID]) -> None:
    for section in sections:
        unknown = [str(claim_id) for claim_id in section.claim_ids if claim_id not in known_claim_ids]
        if unknown:
            raise SectionReferencesUnknownClaimError(
                f"Technical appendix section {section.heading!r} references unknown claim_id(s): "
                f"{', '.join(unknown)}"
            )
