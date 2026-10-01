"""Multi-pass claim/metric/glossary/narrative extraction against a
``ParsedDocument``'s page text.

Depends only on ``AIProvider`` (the interface) -- never imports a concrete
provider implementation from ``app.providers.*`` (ARCHITECTURE.md's Evidence
Engine contract). Structured-output validation + the one-retry-then-surface
behavior already lives in ``app.providers.structured_output`` and is invoked
transparently by every ``AIProvider.generate`` implementation -- this module
does not reimplement it.
"""

from typing import cast

from pydantic import BaseModel

from app.evidence.prompts.claims import build_claims_prompt
from app.evidence.prompts.glossary import build_glossary_prompt
from app.evidence.prompts.metrics import build_metrics_prompt
from app.evidence.prompts.narrative import build_narrative_prompt
from app.evidence.prompts.shared import build_page_marked_text
from app.evidence.schemas import (
    ClaimsExtractionOutput,
    ExtractionResult,
    GlossaryExtractionOutput,
    MetricsExtractionOutput,
    NarrativeExtraction,
    PageText,
)
from app.providers.base import AIProvider


async def run_extraction(
    provider: AIProvider, pages: list[PageText], *, model: str
) -> ExtractionResult:
    """Runs the four extraction passes against ``provider`` and merges their
    output. Each pass validates its own structured-output schema (via
    ``provider.generate``); a schema-validation failure that survives the
    provider's one retry raises ``app.providers.errors.StructuredOutputError``
    and is left to the caller (``service.run_analysis``) to surface, not
    swallowed here.

    Sequential, not parallel: each pass embeds the *whole* document (design
    decision #3, ``prompts/shared.py`` -- no chunking), so four passes fired
    concurrently means four full-document-sized requests hitting the
    provider at once. Confirmed live against NVIDIA NIM on a 53-page paper
    (~37k tokens/request, ~150k tokens in one concurrent burst): the
    provider's own gateway returned two consecutive 504s under that load.
    Running one pass at a time keeps peak concurrent token volume at a
    single request's worth, trading stage wall-time (roughly 4x slower) for
    not overloading a capacity-constrained inference backend. Revisit if a
    provider's own concurrency/TPM limit is ever confirmed high enough to
    make this unnecessary.
    """
    results = [await provider.generate(prompt, schema, model=model) for _, prompt, schema in extraction_passes(pages)]
    return merge_extraction(results)


def extraction_passes(pages: list[PageText]) -> list[tuple[str, str, type[BaseModel]]]:
    """(what the pass extracts, prompt, output schema), in run order. The
    service walks this list itself so it can report each pass as it starts --
    a pass can take 10+ minutes on a hosted model."""
    document_text = build_page_marked_text(pages)
    return [
        ("claims", build_claims_prompt(document_text), ClaimsExtractionOutput),
        ("metrics", build_metrics_prompt(document_text), MetricsExtractionOutput),
        ("glossary terms", build_glossary_prompt(document_text), GlossaryExtractionOutput),
        ("summary and narrative", build_narrative_prompt(document_text), NarrativeExtraction),
    ]


def merge_extraction(results: list[BaseModel]) -> ExtractionResult:
    """Combines the outputs of ``extraction_passes``, in the same order."""
    claims = cast(ClaimsExtractionOutput, results[0])
    metrics = cast(MetricsExtractionOutput, results[1])
    glossary = cast(GlossaryExtractionOutput, results[2])
    narrative = cast(NarrativeExtraction, results[3])

    return ExtractionResult(
        claims=claims.claims,
        metrics=metrics.metrics,
        glossary=glossary.terms,
        narrative=narrative,
    )
