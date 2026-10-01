"""Business logic for paper creation, ownership checks, and background
parsing — kept out of the router so route functions stay thin request/
response glue.
"""

import shutil
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.logging import get_logger
from app.core.storage import ensure_paper_dir, paper_dir_path, write_file
from app.db.session import AsyncSessionLocal
from app.models.page import Page
from app.models.paper import Paper, ParseStatus
from app.documents.figures import extract_document_figures
from app.documents.schemas import ParsedFigure
from app.papers.arxiv_client import ArxivMetadata, download_pdf
from app.papers.exceptions import PaperNotFoundError, PaperNotParsedError, SourcePdfMissingError

logger = get_logger(__name__)

try:
    from app.documents.exceptions import DocumentUnreadableError
except ImportError:  # pragma: no cover

    class DocumentUnreadableError(Exception):  # type: ignore[no-redef]
        pass


try:
    from app.documents.parser import parse_pdf
except ImportError:  # pragma: no cover
    # document-processing-engineer's module is built in parallel and may not
    # exist yet in this working tree. Fail loudly (not a silent no-op) only
    # if a parse is actually attempted before that module lands, instead of
    # crashing app startup / every other route via a top-level ImportError.
    def parse_pdf(file_path: str, output_dir: str) -> Any:
        raise RuntimeError("Document parsing pipeline (app.documents.parser) is not available yet")


async def list_owned_papers(db: AsyncSession, user_id: uuid.UUID, limit: int = 50, offset: int = 0) -> list[Paper]:
    """Papers belonging to ``user_id``, most recent first — same row-level
    scoping as get_owned_paper, just for the list case."""
    result = await db.scalars(
        select(Paper).where(Paper.user_id == user_id).order_by(Paper.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.all())


async def get_owned_paper(db: AsyncSession, paper_id: uuid.UUID, user_id: uuid.UUID) -> Paper:
    """Fetches a paper only if it belongs to ``user_id`` — a paper owned by
    someone else looks identical to a missing one (SECURITY.md row-level
    authorization: don't leak existence via a 403 vs 404 split).
    """
    paper = await db.scalar(select(Paper).where(Paper.id == paper_id, Paper.user_id == user_id))
    if paper is None:
        raise PaperNotFoundError("Paper not found")
    return paper


async def create_paper_from_upload(
    db: AsyncSession, user_id: uuid.UUID, filename: str, content: bytes
) -> Paper:
    paper_id = uuid.uuid4()
    directory = await run_in_threadpool(ensure_paper_dir, paper_id)
    dest_path = await run_in_threadpool(write_file, directory, filename, content)

    fallback_title = Path(filename).stem or str(paper_id)
    paper = Paper(
        id=paper_id,
        user_id=user_id,
        title=fallback_title,
        authors=[],
        year=None,
        source_file_path=str(dest_path),
        parse_status=ParseStatus.pending,
    )
    db.add(paper)
    await db.commit()
    await db.refresh(paper)
    return paper


async def create_paper_from_arxiv(db: AsyncSession, user_id: uuid.UUID, metadata: ArxivMetadata) -> Paper:
    paper_id = uuid.uuid4()
    directory = await run_in_threadpool(ensure_paper_dir, paper_id)
    dest_path = directory / "source.pdf"
    await download_pdf(metadata.pdf_url, str(dest_path))

    paper = Paper(
        id=paper_id,
        user_id=user_id,
        title=metadata.title or metadata.arxiv_id,
        authors=metadata.authors,
        year=metadata.year,
        arxiv_id=metadata.arxiv_id,
        source_file_path=str(dest_path),
        parse_status=ParseStatus.pending,
    )
    db.add(paper)
    await db.commit()
    await db.refresh(paper)
    return paper


async def run_parsing(paper_id: uuid.UUID) -> None:
    """Background task: parses the source PDF and persists ``Page`` rows, or
    marks the paper failed with ``parse_error`` set. Runs on its own DB
    session — the request-scoped session is already closed by the time a
    ``BackgroundTasks`` callable executes.
    """
    async with AsyncSessionLocal() as db:
        paper = await db.get(Paper, paper_id)
        if paper is None:
            logger.warning("paper_parse_skipped_missing paper_id=%s", paper_id)
            return

        paper.parse_status = ParseStatus.parsing
        await db.commit()

        output_dir = str(await run_in_threadpool(ensure_paper_dir, paper_id))
        try:
            parsed = await run_in_threadpool(parse_pdf, paper.source_file_path, output_dir)
            for page in parsed.pages:
                db.add(
                    Page(
                        paper_id=paper_id,
                        page_number=page.number,
                        text=page.text,
                        figures=[figure.model_dump() for figure in page.figures],
                    )
                )
            paper.parse_status = ParseStatus.parsed
            await db.commit()
            logger.info("paper_parsed paper_id=%s pages=%d", paper_id, len(parsed.pages))
        except Exception as exc:
            # ponytail: broad catch is deliberate, and covers persistence too
            # (not just parse_pdf) — confirmed live that a DB-layer failure
            # here (e.g. a NUL byte in extracted text, which Postgres rejects
            # outright) previously left the paper silently stuck in
            # "parsing" forever with nothing logged, because it raised
            # outside this block entirely. Anything going wrong from here on
            # must still flip the paper to failed, never leave it hanging.
            logger.exception("paper_parse_failed paper_id=%s", paper_id)
            await db.rollback()
            paper.parse_status = ParseStatus.failed
            # Never persist str(exc) verbatim — it can carry absolute file
            # paths or library internals, and parse_error is returned to the
            # paper's owner via GET /papers/{id}. Full detail is already in
            # the log line above; the API only gets a fixed, stage-specific
            # message.
            if isinstance(exc, DocumentUnreadableError):
                paper.parse_error = "Failed to open or read the PDF"
            else:
                paper.parse_error = "An internal error occurred while parsing this document"
            await db.commit()


_FIGURE_STAGING_DIR = ".figures-refresh"


async def refresh_paper_figures(db: AsyncSession, paper: Paper) -> tuple[int, int]:
    """Re-extracts figures from the stored source PDF and replaces both the
    files on disk and each page row's ``figures`` JSON. Page text and every
    other column are untouched. Returns (figure count, pages with figures).
    """
    if paper.parse_status != ParseStatus.parsed:
        raise PaperNotParsedError("Paper has not finished parsing")

    paper_dir = paper_dir_path(paper.id)
    source = Path(paper.source_file_path)
    source_ok = await run_in_threadpool(_is_file_inside, source, paper_dir)
    if not source_ok:
        raise SourcePdfMissingError("The source PDF for this paper is not available")

    by_page = await run_in_threadpool(_replace_figure_files, source, paper_dir)

    pages = await db.scalars(select(Page).where(Page.paper_id == paper.id))
    for page in pages:
        page.figures = [figure.model_dump() for figure in by_page.get(page.page_number, [])]
    await db.commit()

    total = sum(len(figures) for figures in by_page.values())
    return total, sum(1 for figures in by_page.values() if figures)


def _is_file_inside(path: Path, directory: Path) -> bool:
    return path.is_file() and path.resolve().is_relative_to(directory.resolve())


def _replace_figure_files(source_pdf: Path, paper_dir: Path) -> dict[int, list[ParsedFigure]]:
    """Extracts into a staging dir first so a failed extraction leaves the
    old figures in place, then swaps. Deletion is confined to the paper's own
    ``figures/`` directory: a symlinked ``figures`` (or child) is unlinked
    itself, never followed.
    """
    root = paper_dir.resolve()
    staging = root / _FIGURE_STAGING_DIR
    shutil.rmtree(staging, ignore_errors=True)
    try:
        by_page = extract_document_figures(str(source_pdf), str(staging))

        figures_dir = root / "figures"
        if figures_dir.is_symlink():
            figures_dir.unlink()
        elif figures_dir.is_dir():
            for child in figures_dir.iterdir():
                if child.is_symlink() or child.is_file():
                    child.unlink()
        figures_dir.mkdir(exist_ok=True)

        staged = staging / "figures"
        if staged.is_dir():
            for produced in staged.iterdir():
                shutil.move(str(produced), figures_dir / produced.name)
        return by_page
    finally:
        shutil.rmtree(staging, ignore_errors=True)


async def delete_paper_files(paper_id: uuid.UUID) -> None:
    directory = paper_dir_path(paper_id)
    await run_in_threadpool(shutil.rmtree, directory, ignore_errors=True)
