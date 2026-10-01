"""Collections routes: plain CRUD over a user's curated paper lists.

Router lives in this domain package, same module-owns-its-router pattern as
``app.papers.router``/``app.discovery.router``.

API_SPEC.md's "Collections" section spec's four routes (create/list/
add-paper/remove-paper); ``GET /collections/{id}`` is an addition -- needed
to actually fetch a collection's contents, a gap in that spec
(ARCHITECTURE.md's Phase 7 decisions).

Rate limiting mirrors ``app.papers.router``'s own CRUD precedent: its write
routes (``POST /papers/upload``, ``POST /papers/from-arxiv``) are limited to
10/minute per user, its read/delete routes carry no limiter at all. Applied
here the same way -- these are plain DB writes with no AI-provider call, so
no tighter limit is warranted.
"""

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.collections import service as collections_service
from app.collections.schemas import CollectionCreateRequest, CollectionResponse
from app.core.logging import get_logger
from app.core.rate_limit import limiter, rate_limit_key
from app.db.session import get_db
from app.models.collection import Collection
from app.models.user import User
from app.papers.service import get_owned_paper

logger = get_logger(__name__)
router = APIRouter(prefix="/collections", tags=["collections"])


@router.post("", response_model=CollectionResponse, status_code=201)
@limiter.limit("10/minute", key_func=rate_limit_key)
async def create_collection(
    request: Request,
    body: CollectionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Collection:
    collection = await collections_service.create_collection(db, current_user.id, body.name)
    logger.info("collection_created collection_id=%s user_id=%s", collection.id, current_user.id)
    return collection


@router.get("", response_model=list[CollectionResponse])
async def list_collections(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Collection]:
    return await collections_service.list_owned_collections(db, current_user.id)


@router.get("/{collection_id}", response_model=CollectionResponse)
async def get_collection(
    collection_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Collection:
    return await collections_service.get_owned_collection(db, collection_id, current_user.id)


@router.post("/{collection_id}/papers/{paper_id}", response_model=CollectionResponse)
@limiter.limit("10/minute", key_func=rate_limit_key)
async def add_paper_to_collection(
    request: Request,
    collection_id: uuid.UUID,
    paper_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Collection:
    collection = await collections_service.get_owned_collection(db, collection_id, current_user.id)
    # A collection must never reference a paper the requesting user doesn't
    # own -- 404s (not silently ignores) a paper_id that's missing or owned
    # by someone else, same discipline as every other owned-resource check.
    await get_owned_paper(db, paper_id, current_user.id)
    return await collections_service.add_paper_to_collection(db, collection, paper_id)


@router.delete("/{collection_id}/papers/{paper_id}", response_model=CollectionResponse)
async def remove_paper_from_collection(
    collection_id: uuid.UUID,
    paper_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Collection:
    collection = await collections_service.get_owned_collection(db, collection_id, current_user.id)
    return await collections_service.remove_paper_from_collection(db, collection, paper_id)
