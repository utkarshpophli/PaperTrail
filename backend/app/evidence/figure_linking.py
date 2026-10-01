"""Links a paper's extracted PDF figures to its claims (one bounded provider
call, validated). Nothing here persists anything -- ``app.evidence.figures``
does, and the visual stage treats this whole pass as non-fatal.

Unlike a story/report section, a figure link is enrichment, so validation
*drops* what it can't trust (unknown filenames, claim ids outside this paper)
instead of rejecting the batch: a hallucinated figure or claim id must never
be persisted, but it also shouldn't cost the paper its other figure links.
"""

import re
import uuid
from typing import cast

from pydantic import BaseModel, Field

from app.discovery.sanitize import sanitize_generated_text
from app.evidence.prompts.figures import build_figure_prompt
from app.evidence.schemas import ClaimForPrompt
from app.evidence.story_integrity import strip_nul
from app.providers.base import AIProvider

MAX_FIGURES = 40  # figures and tables (DeepSeek-V3 has 10 + 9)
MAX_CLAIMS_IN_PROMPT = 60
_WHY_MAX_LENGTH = 400
_MAX_CLAIMS_PER_FIGURE = 6
_FIGURE_LABEL_RE = re.compile(r"\b(fig(?:ure)?|tab(?:le)?)\.?\s*(\d+)", re.IGNORECASE)


def parse_figure_label(caption: str | None) -> str | None:
    """"Figure 3: ..." / "Fig. 3" -> "Figure 3", "Table 2: ..." -> "Table 2";
    ``None`` if the caption carries no figure/table number."""
    match = _FIGURE_LABEL_RE.search(caption or "")
    if match is None:
        return None
    kind = "Table" if match.group(1).lower().startswith("tab") else "Figure"
    return f"{kind} {match.group(2)}"


class FigureInput(BaseModel):
    filename: str
    page: int
    label: str | None
    caption: str | None


class FigureClaimContext(BaseModel):
    """A claim plus the pages its source refs cite, so the prompt can be
    limited to claims near a figure."""

    claim: ClaimForPrompt
    pages: list[int]


class FigureLinkDraft(BaseModel):
    filename: str = Field(min_length=1, max_length=512)
    claim_ids: list[uuid.UUID] = Field(default_factory=list)
    why_it_matters: str = Field(default="", max_length=2000)


class FigureLinksOutput(BaseModel):
    figures: list[FigureLinkDraft] = Field(default_factory=list)


class FigureLink(BaseModel):
    filename: str
    claim_ids: list[uuid.UUID]
    why_it_matters: str | None


def claims_near_figures(
    figures: list[FigureInput], contexts: list[FigureClaimContext]
) -> list[ClaimForPrompt]:
    """Claims citing a figure's page or an adjacent one, deduplicated and
    capped so the prompt stays bounded."""
    figure_pages = {figure.page for figure in figures}
    near = [
        ctx.claim
        for ctx in contexts
        if any(abs(page - fig_page) <= 1 for page in ctx.pages for fig_page in figure_pages)
    ]
    return near[:MAX_CLAIMS_IN_PROMPT]


async def link_figures(
    provider: AIProvider,
    *,
    figures: list[FigureInput],
    contexts: list[FigureClaimContext],
    known_claim_ids: set[uuid.UUID],
    model: str,
) -> list[FigureLink]:
    """One link per input figure (a figure the model skipped comes back
    unlinked). Raises whatever ``provider.generate`` raises (e.g.
    ``StructuredOutputError``) -- the caller decides that is non-fatal."""
    figures = figures[:MAX_FIGURES]
    prompt = build_figure_prompt(
        figures=[(f.filename, f.page, f.label, f.caption) for f in figures],
        claims=claims_near_figures(figures, contexts),
    )
    opts: dict[str, object] = {"model": model}
    output = cast(FigureLinksOutput, await provider.generate(prompt, FigureLinksOutput, **opts))

    by_filename = {draft.filename: draft for draft in output.figures}  # unknown filenames never match an input
    return [_validated_link(figure, by_filename.get(figure.filename), known_claim_ids) for figure in figures]


def _validated_link(figure: FigureInput, draft: FigureLinkDraft | None, known_claim_ids: set[uuid.UUID]) -> FigureLink:
    if draft is None:
        return FigureLink(filename=figure.filename, claim_ids=[], why_it_matters=None)

    claim_ids = list(dict.fromkeys(cid for cid in draft.claim_ids if cid in known_claim_ids))[
        :_MAX_CLAIMS_PER_FIGURE
    ]
    why = sanitize_generated_text(strip_nul(draft.why_it_matters), _WHY_MAX_LENGTH).strip()
    if not why or _normalized(why) == _normalized(figure.caption or ""):
        why = ""
    return FigureLink(filename=figure.filename, claim_ids=claim_ids, why_it_matters=why or None)


def _normalized(text: str) -> str:
    return " ".join(text.lower().split())
