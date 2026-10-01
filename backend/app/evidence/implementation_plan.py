"""Implementation-plan derivation (docs/ARCHITECTURE.md's Code Research
(Phase 8) section). Same shape as ``report.py``/``technical.py`` (build
prompt, call the provider, validate ``claim_ids``) -- the prompt is fed only
``method``/``reported-result`` claims plus metrics, the kinds relevant to a
reader reproducing the paper's approach, optionally enriched with a linked
repository's README text. ``claim_ids`` are still validated against *all* of
the paper's claims, not just that filtered subset, same "filtering the
prompt's own content never makes validation more permissive" rule as
``technical.py``.

The output is plain guidance text for a human to read and act on manually --
nothing here executes it, writes it to a file, or hands it to any
subprocess.
"""

import uuid

from app.evidence.claim_check import generate_with_claim_check
from app.evidence.exceptions import SectionReferencesUnknownClaimError
from app.evidence.prompts.implementation_plan import build_implementation_plan_prompt
from app.evidence.schemas import ClaimForPrompt, GeneratedSectionDraft, GeneratedSectionsOutput, MetricForPrompt
from app.models.claim import ClaimKind
from app.providers.base import AIProvider

_IMPLEMENTATION_PLAN_CLAIM_KINDS = frozenset({ClaimKind.method, ClaimKind.reported_result})


async def generate_implementation_plan_sections(
    provider: AIProvider,
    *,
    claims: list[ClaimForPrompt],
    metrics: list[MetricForPrompt],
    readme_text: str | None = None,
    model: str,
) -> list[GeneratedSectionDraft]:
    """Runs the implementation-plan generation pass. Same failure modes as
    ``report.generate_report_sections``: ``StructuredOutputError`` from the
    provider, or ``SectionReferencesUnknownClaimError`` if a step cites a
    claim outside this paper's real claims -- either way, nothing is
    returned for the caller to persist.
    """
    relevant_claims = [claim for claim in claims if claim.kind in _IMPLEMENTATION_PLAN_CLAIM_KINDS]
    prompt = build_implementation_plan_prompt(claims=relevant_claims, metrics=metrics, readme_text=readme_text)
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
                f"Implementation plan step {section.heading!r} references unknown claim_id(s): {', '.join(unknown)}"
            )
