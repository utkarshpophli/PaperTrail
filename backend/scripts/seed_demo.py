"""Seeds one fully populated, clearly fabricated demo paper so the studio UI
can be reviewed with no provider key.

    python -m scripts.seed_demo            # from backend/, idempotent
    python scripts/seed_demo.py --reset    # delete the demo paper and re-create it

The rows go through the same persistence functions a real analysis run uses
(``app.evidence.service``) and claim statuses come from the real verifier --
only the model calls are replaced by ``scripts.demo_content``. Acts as the
local user (``LOCAL_MODE``).
"""

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

import fitz
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

if __package__ in (None, ""):  # `python scripts/seed_demo.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth.dependencies import get_or_create_local_user  # noqa: E402
from app.core.storage import paper_dir_path  # noqa: E402
from app.evidence import service  # noqa: E402
from app.evidence.figure_linking import FigureInput, FigureLink, parse_figure_label  # noqa: E402
from app.evidence.story_integrity import check_story_integrity  # noqa: E402
from app.evidence.verifier import verify_claim_status  # noqa: E402
from app.models.generated_section import SectionType  # noqa: E402
from app.models.page import Page  # noqa: E402
from app.models.paper import Paper, ParseStatus  # noqa: E402
from scripts import demo_content as content  # noqa: E402
from scripts.demo_figures import draw_figures  # noqa: E402


async def _find_demo_paper(db: AsyncSession, user_id: uuid.UUID) -> Paper | None:
    return await db.scalar(select(Paper).where(Paper.user_id == user_id, Paper.title == content.TITLE))


def _write_source_pdf(directory: Path) -> Path:
    doc = fitz.open()
    for number in sorted(content.PAGES):
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(54, 54, 558, 738), content.PAGES[number], fontsize=11)
    path = directory / "demo-paper.pdf"
    doc.save(path)
    doc.close()
    return path


async def seed(db: AsyncSession, *, reset: bool = False) -> uuid.UUID:
    """Returns the demo paper's id. Without ``reset`` an existing demo paper
    is left untouched (idempotent); with it, the paper and its files are
    deleted and re-created."""
    user = await get_or_create_local_user(db)
    existing = await _find_demo_paper(db, user.id)
    if existing is not None and not reset:
        return existing.id
    if existing is not None:
        await _delete(db, existing.id)

    paper = Paper(
        user_id=user.id,
        title=content.TITLE,
        authors=["Demo Author (fictional)"],
        source_file_path="pending",
        parse_status=ParseStatus.parsed,
    )
    db.add(paper)
    await db.commit()
    paper_id = paper.id
    try:
        await _populate(db, paper)
    except Exception:  # cleanup then re-raise: a half-seeded paper must not look complete on the next run
        await db.rollback()
        await _delete(db, paper_id)
        raise
    return paper_id


async def _delete(db: AsyncSession, paper_id: uuid.UUID) -> None:
    directory = paper_dir_path(paper_id)
    await db.execute(delete(Paper).where(Paper.id == paper_id))  # child tables go via ON DELETE CASCADE
    await db.commit()
    if directory.exists():
        for child in sorted(directory.rglob("*"), reverse=True):
            child.unlink() if child.is_file() else child.rmdir()
        directory.rmdir()


async def _populate(db: AsyncSession, paper: Paper) -> None:
    paper_id = paper.id
    directory = paper_dir_path(paper_id)
    (directory / "figures").mkdir(parents=True, exist_ok=True)
    paper.source_file_path = str(_write_source_pdf(directory))
    draw_figures(directory / "figures")

    for number, text in content.PAGES.items():
        db.add(
            Page(
                paper_id=paper_id,
                page_number=number,
                text=text,
                figures=[figure for figure in content.FIGURES if figure["page"] == number],
            )
        )
    await db.commit()

    # Evidence, then the verifier -- exactly the order run_analysis uses.
    claims = await service._persist_extraction(db, paper_id, content.extraction_result())
    for claim in claims:
        claim.verification_status = verify_claim_status(
            [(ref.page, ref.excerpt) for ref in claim.source_refs], content.PAGES
        )
    await db.commit()
    ids: dict[str, uuid.UUID] = dict(zip(content.CLAIM_KEYS, (claim.id for claim in claims), strict=True))

    await service._persist_sections(db, paper_id, SectionType.report, content.report_drafts(ids))
    await service._persist_sections(db, paper_id, SectionType.technical, content.technical_drafts(ids))

    figures = [
        FigureInput(
            filename=Path(str(figure["image_path"])).name,
            page=int(figure["page"]),  # type: ignore[arg-type]
            label=parse_figure_label(str(figure["caption"])),
            caption=str(figure["caption"]),
        )
        for figure in content.FIGURES
    ]
    links = [
        FigureLink(filename=name, claim_ids=claim_ids, why_it_matters=why)
        for name, (claim_ids, why) in content.figure_links(ids).items()
    ]
    story = content.story(ids)
    # Same gate a generated story passes before persistence.
    check_story_integrity(
        story, await service._load_claims_for_prompt(db, paper_id), await service._load_metrics_for_prompt(db, paper_id)
    )
    await service._persist_visual_stage(
        db,
        paper_id,
        story=story,
        primer_drafts=content.primer_drafts(ids),
        application_guide_drafts=content.application_guide_drafts(ids),
        quiz_drafts=content.quiz_drafts(ids),
        derivation_drafts=content.derivation_drafts(ids),
        interactive_drafts=content.interactive_drafts(ids),
        figures=figures,
        figure_links=links,
    )


async def _main(reset: bool) -> None:
    from app.db.session import AsyncSessionLocal, engine

    try:
        async with AsyncSessionLocal() as db:
            paper_id = await seed(db, reset=reset)
    finally:
        await engine.dispose()
    sys.stdout.write(f"Demo paper ready: {paper_id}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the illustrative demo paper.")
    parser.add_argument("--reset", action="store_true", help="delete and re-create the demo paper")
    asyncio.run(_main(parser.parse_args().reset))


if __name__ == "__main__":
    main()
