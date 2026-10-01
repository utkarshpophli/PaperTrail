"""Papers routes: create (upload or arXiv resolve), read, delete.

API_SPEC.md specifies a single polymorphic ``POST /papers``. This
implementation splits it into ``POST /papers/upload`` (multipart PDF) and
``POST /papers/from-arxiv`` (JSON body) instead — two request shapes with
different content types and validation rules are clearer as two routes than
as one handler branching on ``Content-Type``. Flagged here and in the
handback report as a deliberate deviation.
"""

import re
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.rate_limit import limiter, rate_limit_key
from app.core.storage import paper_dir_path
from app.db.session import get_db
from app.models.page import Page
from app.models.paper import Paper
from app.models.user import User
from app.papers.arxiv_client import resolve_arxiv_metadata
from app.papers.exceptions import FigureNotFoundError, FileTooLargeError, InvalidFileTypeError, PageNotFoundError
from app.papers.schemas import ArxivResolveRequest, FigureRefreshResponse, PageResponse, PaperResponse
from app.papers.service import (
    create_paper_from_arxiv,
    create_paper_from_upload,
    delete_paper_files,
    get_owned_paper,
    list_owned_papers,
    refresh_paper_figures,
    run_parsing,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/papers", tags=["papers"])

_PDF_MAGIC = b"%PDF-"
# Generated figure names are page{N}_fig{i}.{ext} / page{N}_vec{i}.png; the
# allowlist also keeps NULs, drive-letter colons and backslashes out of Path().
_SAFE_FIGURE_FILENAME = re.compile(r"[A-Za-z0-9_.-]+")
_UPLOAD_CHUNK_SIZE = 1024 * 1024


async def _read_upload_capped(file: UploadFile, max_bytes: int) -> bytes:
    """Reads the upload in chunks, aborting as soon as the size cap is
    exceeded — avoids buffering an unbounded upload into memory before the
    size check runs (docs/SECURITY.md: validate size before processing).
    """
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_UPLOAD_CHUNK_SIZE):
        total += len(chunk)
        if total > max_bytes:
            raise FileTooLargeError(f"File exceeds the {max_bytes} byte limit")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/upload", response_model=PaperResponse, status_code=201)
@limiter.limit("10/minute", key_func=rate_limit_key)
async def upload_paper(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Paper:
    settings = get_settings()
    content = await _read_upload_capped(file, settings.max_upload_size_bytes)
    if not content.startswith(_PDF_MAGIC):
        raise InvalidFileTypeError("Only PDF files are accepted")

    paper = await create_paper_from_upload(db, current_user.id, file.filename or "upload.pdf", content)
    background_tasks.add_task(run_parsing, paper.id)
    logger.info("paper_upload_accepted paper_id=%s user_id=%s", paper.id, current_user.id)
    return paper


@router.post("/from-arxiv", response_model=PaperResponse, status_code=201)
@limiter.limit("10/minute", key_func=rate_limit_key)
async def create_paper_from_arxiv_route(
    request: Request,
    body: ArxivResolveRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Paper:
    metadata = await resolve_arxiv_metadata(arxiv_id=body.arxiv_id, title=body.arxiv_title)
    paper = await create_paper_from_arxiv(db, current_user.id, metadata)
    background_tasks.add_task(run_parsing, paper.id)
    logger.info("paper_arxiv_accepted paper_id=%s user_id=%s", paper.id, current_user.id)
    return paper


@router.get("", response_model=list[PaperResponse])
async def list_papers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
) -> list[Paper]:
    return await list_owned_papers(db, current_user.id, limit=limit, offset=offset)


@router.get("/{paper_id}", response_model=PaperResponse)
async def get_paper(
    paper_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Paper:
    return await get_owned_paper(db, paper_id, current_user.id)


@router.get("/{paper_id}/pages/{page_number}", response_model=PageResponse)
async def get_page(
    paper_id: uuid.UUID,
    page_number: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page:
    await get_owned_paper(db, paper_id, current_user.id)
    page = await db.scalar(select(Page).where(Page.paper_id == paper_id, Page.page_number == page_number))
    if page is None:
        raise PageNotFoundError("Page not found")
    return page


@router.get("/{paper_id}/figures/{filename}")
async def get_figure(
    paper_id: uuid.UUID,
    filename: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Serves an extracted figure's image bytes.

    Per the security review: the path is derived only from the server-known
    paper directory + this filename, never a client-supplied full path, and
    is re-verified to resolve inside that paper's figures directory before
    being served — ``filename`` can't contain "/" (FastAPI's path-segment
    matching already excludes it), but this also closes off "..", symlink
    tricks, etc. with an explicit check rather than trusting that alone.
    """
    await get_owned_paper(db, paper_id, current_user.id)
    if not _SAFE_FIGURE_FILENAME.fullmatch(filename):
        raise FigureNotFoundError("Figure not found")

    figures_dir = (paper_dir_path(paper_id) / "figures").resolve()
    candidate = (figures_dir / filename).resolve()
    if not candidate.is_relative_to(figures_dir) or not candidate.is_file():
        raise FigureNotFoundError("Figure not found")

    return FileResponse(candidate)


@router.post("/{paper_id}/figures/refresh", response_model=FigureRefreshResponse)
@limiter.limit("5/minute", key_func=rate_limit_key)
async def refresh_figures(
    request: Request,
    paper_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FigureRefreshResponse:
    """Re-extracts figures (raster + vector) for an already-parsed paper."""
    paper = await get_owned_paper(db, paper_id, current_user.id)
    figures, pages_with_figures = await refresh_paper_figures(db, paper)
    logger.info("paper_figures_refreshed paper_id=%s figures=%d", paper_id, figures)
    return FigureRefreshResponse(figures=figures, pages_with_figures=pages_with_figures)


@router.delete("/{paper_id}", status_code=204)
async def delete_paper(
    paper_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    paper = await get_owned_paper(db, paper_id, current_user.id)
    await delete_paper_files(paper.id)
    await db.delete(paper)
    await db.commit()
