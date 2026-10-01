"""Code Research routes: GitHub repo linking, listing, unlinking, and
official-implementation detection (docs/ARCHITECTURE.md's Code Research
(Phase 8) section -- only these two deliverables; no OpenCode subprocess
integration is built or attempted here).

Router lives in this domain package, same module-owns-its-router pattern as
``app.papers.router``/``app.collections.router``.

Rate limiting mirrors ``app.collections.router``'s CRUD precedent (plain
DB reads/writes get none or a light limit) plus ``app.evidence.router``'s
"AI/external-API-heavy route gets a real ceiling" precedent -- applied here
to the two routes that call out to GitHub's API.
"""

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.coderesearch import code_linking
from app.coderesearch.handoff import build_handoff
from app.coderesearch import service as coderesearch_service
from app.coderesearch.exceptions import CodeLinkNotFoundError
from app.coderesearch.schemas import (
    CodeLinkRequest,
    CodeLinkResponse,
    OpencodeHandoffResponse,
    RepositoryCandidateResponse,
    RepositoryDetectRequest,
    RepositoryLinkRequest,
    RepositoryResponse,
)
from app.core.logging import get_logger
from app.core.rate_limit import limiter, rate_limit_key
from app.db.session import get_db
from app.models.code_link import CodeLink
from app.models.repository import Repository
from app.models.user import User
from app.papers.service import get_owned_paper
from app.providers.errors import InvalidConfigError
from app.providers.redaction import redacting
from app.providers.registry import build_provider

logger = get_logger(__name__)
router = APIRouter(prefix="/papers", tags=["coderesearch"])


@router.post("/{paper_id}/repositories", response_model=RepositoryResponse, status_code=201)
# 20/hour: same ceiling as detect below -- a plain link call still makes one
# real GitHub API round-trip (SECURITY.md: per-user limits on endpoints that
# call out to an external API).
@limiter.limit("20/hour", key_func=rate_limit_key)
async def create_repository_link(
    request: Request,
    paper_id: uuid.UUID,
    body: RepositoryLinkRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Repository:
    """Never logs ``body.token`` -- same credential-handling discipline as
    ``app.evidence.router.analyze_paper``."""
    await get_owned_paper(db, paper_id, current_user.id)
    repository = await coderesearch_service.link_repository(db, paper_id, current_user.id, body.url, body.token)
    logger.info(
        "repository_linked paper_id=%s repository_id=%s user_id=%s", paper_id, repository.id, current_user.id
    )
    return repository


@router.get("/{paper_id}/repositories", response_model=list[RepositoryResponse])
async def get_paper_repositories(
    paper_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Repository]:
    await get_owned_paper(db, paper_id, current_user.id)
    return await coderesearch_service.list_repositories(db, paper_id)


@router.delete("/{paper_id}/repositories/{repository_id}", status_code=204)
async def delete_repository_link(
    paper_id: uuid.UUID,
    repository_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await get_owned_paper(db, paper_id, current_user.id)
    await coderesearch_service.unlink_repository(db, paper_id, repository_id)
    logger.info("repository_unlinked paper_id=%s repository_id=%s user_id=%s", paper_id, repository_id, current_user.id)


@router.post("/{paper_id}/repositories/detect", response_model=list[RepositoryCandidateResponse])
# 20/hour: detection is the most GitHub-API-heavy route (a search call, not
# a single-repo lookup) -- a real ceiling per SECURITY.md's "per-user limits
# on expensive endpoints".
@limiter.limit("20/hour", key_func=rate_limit_key)
async def detect_paper_repositories(
    request: Request,
    paper_id: uuid.UUID,
    body: RepositoryDetectRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RepositoryCandidateResponse]:
    """Returns candidate repositories only -- never persists. A candidate
    must be separately confirmed via ``POST /papers/{id}/repositories`` to
    become a real linked ``Repository`` row (research-integrity: a detected
    repo is a guess, never silently promoted). Never logs ``body.token``.
    """
    paper = await get_owned_paper(db, paper_id, current_user.id)
    candidates = await coderesearch_service.detect_repositories(paper.title, paper.arxiv_id, body.token)
    logger.info(
        "repository_detect_requested paper_id=%s user_id=%s results=%s", paper_id, current_user.id, len(candidates)
    )
    return [
        RepositoryCandidateResponse(
            url=candidate.url,
            owner=candidate.owner,
            name=candidate.name,
            description=candidate.description,
            stars=candidate.stars,
            confidence=coderesearch_service.DETECTED_CONFIDENCE,
        )
        for candidate in candidates
    ]


@router.post("/{paper_id}/repositories/{repository_id}/code-links", response_model=list[CodeLinkResponse])
# 10/hour: two provider round-trips plus up to ~7 GitHub API calls per call
# (SECURITY.md: per-user limits on expensive endpoints).
@limiter.limit("10/hour", key_func=rate_limit_key)
async def create_code_links(
    request: Request,
    paper_id: uuid.UUID,
    repository_id: uuid.UUID,
    body: CodeLinkRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CodeLink]:
    """Links one method/reported-result claim to the code implementing it,
    replacing prior links for the same (repository, claim). Never logs
    ``body.api_key`` or ``body.token``. Ownership of paper/repository/claim
    is checked inside ``link_claim_to_code`` before any GitHub/provider call.
    """
    await get_owned_paper(db, paper_id, current_user.id)
    try:
        provider = redacting(
            build_provider(body.provider_id, api_key=body.api_key, endpoint=body.endpoint), body.api_key, body.token
        )
    except NotImplementedError as exc:
        raise InvalidConfigError(str(exc)) from exc
    links = await code_linking.link_claim_to_code(
        db, provider, current_user, paper_id, repository_id, body.claim_id, body.token, body.model
    )
    logger.info(
        "code_links_created paper_id=%s repository_id=%s claim_id=%s user_id=%s count=%s",
        paper_id,
        repository_id,
        body.claim_id,
        current_user.id,
        len(links),
    )
    return links


@router.get("/{paper_id}/code-links", response_model=list[CodeLinkResponse])
async def get_paper_code_links(
    paper_id: uuid.UUID,
    claim_id: uuid.UUID | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CodeLink]:
    await get_owned_paper(db, paper_id, current_user.id)
    return await code_linking.list_code_links(db, paper_id, current_user.id, claim_id)


@router.delete("/{paper_id}/code-links/{code_link_id}", status_code=204)
async def delete_code_link(
    paper_id: uuid.UUID,
    code_link_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await get_owned_paper(db, paper_id, current_user.id)
    result = await db.execute(
        delete(CodeLink).where(
            CodeLink.id == code_link_id, CodeLink.paper_id == paper_id, CodeLink.user_id == current_user.id
        )
    )
    if result.rowcount == 0:
        raise CodeLinkNotFoundError("Code link not found")
    await db.commit()
    logger.info("code_link_deleted paper_id=%s code_link_id=%s user_id=%s", paper_id, code_link_id, current_user.id)


@router.get("/{paper_id}/opencode-handoff", response_model=OpencodeHandoffResponse)
async def get_opencode_handoff(
    paper_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OpencodeHandoffResponse:
    """Export only: reads persisted data and returns text. Paper Trail never
    runs OpenCode (docs/ARCHITECTURE.md); no provider or network call here."""
    paper = await get_owned_paper(db, paper_id, current_user.id)
    handoff = build_handoff(await coderesearch_service.load_handoff_input(db, paper))
    logger.info("opencode_handoff_exported paper_id=%s user_id=%s", paper_id, current_user.id)
    return handoff
