"""Figure list/enrichment persistence. The list of figures comes from
``pages.figures`` (written by the document parser); ``figures`` rows only add
the parsed label, why-it-matters text and claim links on top.
"""

import uuid
from pathlib import PureWindowsPath

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evidence.figure_linking import FigureClaimContext, FigureInput, FigureLink, parse_figure_label
from app.evidence.schemas import ClaimForPrompt
from app.models.claim import Claim
from app.models.figure import Figure
from app.models.page import Page


class FigureResponse(BaseModel):
    """``GET /papers/{id}/figures`` item. ``id`` is the filename, which is
    also what ``GET /papers/{id}/figures/{filename}`` serves the bytes for."""

    id: str
    filename: str
    page: int
    label: str | None
    caption: str | None
    why_it_matters: str | None
    claim_ids: list[uuid.UUID]


async def load_figure_inputs(db: AsyncSession, paper_id: uuid.UUID) -> list[FigureInput]:
    """Every figure the parser extracted, ordered by page then filename."""
    rows = (await db.scalars(select(Page).where(Page.paper_id == paper_id).order_by(Page.page_number))).all()
    inputs: list[FigureInput] = []
    for row in rows:
        for entry in row.figures:
            image_path = entry.get("image_path")
            if not image_path:
                continue
            caption = entry.get("caption")
            inputs.append(
                FigureInput(
                    filename=PureWindowsPath(image_path).name,
                    page=entry.get("page", row.page_number),
                    label=parse_figure_label(caption),
                    caption=caption,
                )
            )
    return sorted(inputs, key=lambda f: (f.page, f.filename))


async def load_claim_contexts(db: AsyncSession, paper_id: uuid.UUID) -> list[FigureClaimContext]:
    claims = (await db.scalars(select(Claim).where(Claim.paper_id == paper_id).order_by(Claim.created_at))).all()
    return [
        FigureClaimContext(
            claim=ClaimForPrompt(
                id=claim.id,
                kind=claim.kind,
                statement=claim.statement,
                excerpts=[ref.excerpt for ref in claim.source_refs],
                verification_status=claim.verification_status,
            ),
            pages=sorted({ref.page for ref in claim.source_refs}),
        )
        for claim in claims
    ]


async def replace_figure_links(
    db: AsyncSession, paper_id: uuid.UUID, figures: list[FigureInput], links: list[FigureLink]
) -> None:
    """Replace-on-rerun, one row per figure. Adds to the session without
    committing -- the visual stage commits it with the rest of the batch."""
    by_filename = {link.filename: link for link in links}
    await db.execute(delete(Figure).where(Figure.paper_id == paper_id))
    for figure in figures:
        link = by_filename.get(figure.filename)
        db.add(
            Figure(
                paper_id=paper_id,
                filename=figure.filename,
                page=figure.page,
                label=figure.label,
                why_it_matters=link.why_it_matters if link else None,
                claim_ids=[str(cid) for cid in link.claim_ids] if link else [],
            )
        )


async def list_figures(db: AsyncSession, paper_id: uuid.UUID) -> list[FigureResponse]:
    """Parser figures enriched by ``figures`` rows. A figure with no row is
    still listed (unlinked, label parsed from its caption). ``claim_ids`` are
    filtered to claims that still exist: an evidence re-run replaces every
    claim id, and a stale link must not point at a claim that is gone."""
    inputs = await load_figure_inputs(db, paper_id)
    rows = {row.filename: row for row in (await db.scalars(select(Figure).where(Figure.paper_id == paper_id))).all()}
    live_claim_ids = {str(cid) for cid in (await db.scalars(select(Claim.id).where(Claim.paper_id == paper_id))).all()}

    responses: list[FigureResponse] = []
    for figure in inputs:
        row = rows.get(figure.filename)
        responses.append(
            FigureResponse(
                id=figure.filename,
                filename=figure.filename,
                page=figure.page,
                label=(row.label if row and row.label else figure.label),
                caption=figure.caption,
                why_it_matters=row.why_it_matters if row else None,
                claim_ids=[uuid.UUID(cid) for cid in (row.claim_ids if row else []) if cid in live_claim_ids],
            )
        )
    return responses
