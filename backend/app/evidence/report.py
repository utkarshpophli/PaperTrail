"""Deep report derivation (docs/DATA_MODEL.md's ``DeepReportSection``).

Builds the report prompt, calls the given ``AIProvider`` for a structured
list of sections, and validates every ``claim_id`` a section emits against
this paper's real claims before handing the result back to
``app.evidence.service`` for persistence. Nothing here persists anything --
that stays the service layer's job (same division as ``extraction.py``).
"""

import uuid

from app.evidence.claim_check import generate_with_claim_check
from app.evidence.exceptions import SectionReferencesUnknownClaimError
from app.evidence.prompts.report import build_report_prompt
from app.evidence.schemas import ClaimForPrompt, GeneratedSectionDraft, GeneratedSectionsOutput
from app.providers.base import AIProvider


async def generate_report_sections(
    provider: AIProvider,
    *,
    thesis: str,
    plain_summary: str,
    research_question: str,
    claims: list[ClaimForPrompt],
    model: str,
) -> list[GeneratedSectionDraft]:
    """Runs the report-generation pass. Raises
    ``app.providers.errors.StructuredOutputError`` if the model's output
    fails schema validation twice (surfaced by ``provider.generate``, not
    swallowed here), or ``SectionReferencesUnknownClaimError`` if any
    section cites a ``claim_id`` outside ``claims`` -- in both cases nothing
    is returned for the caller to persist.
    """
    prompt = build_report_prompt(
        thesis=thesis, plain_summary=plain_summary, research_question=research_question, claims=claims
    )
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
                f"Report section {section.heading!r} references unknown claim_id(s): {', '.join(unknown)}"
            )
