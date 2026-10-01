"""Business logic for collection creation, ownership checks, and paper
membership -- kept out of the router so route functions stay thin
request/response glue (same split as ``app.papers.service``).

Plain CRUD, no AI/embedding logic -- deliberately not part of
``app.discovery`` (ARCHITECTURE.md's Phase 7 decisions: curating a list of
papers is a different concern from AI-driven ranking/generation).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collections.exceptions import CollectionNotFoundError
from app.models.collection import Collection


async def create_collection(db: AsyncSession, user_id: uuid.UUID, name: str) -> Collection:
    collection = Collection(user_id=user_id, name=name, paper_ids=[])
    db.add(collection)
    await db.commit()
    await db.refresh(collection)
    return collection


async def list_owned_collections(db: AsyncSession, user_id: uuid.UUID) -> list[Collection]:
    result = await db.scalars(
        select(Collection).where(Collection.user_id == user_id).order_by(Collection.created_at.desc())
    )
    return list(result.all())


async def get_owned_collection(db: AsyncSession, collection_id: uuid.UUID, user_id: uuid.UUID) -> Collection:
    """Fetches a collection only if it belongs to ``user_id`` -- a collection
    owned by someone else looks identical to a missing one, same row-level
    authorization discipline as ``app.papers.service.get_owned_paper``."""
    collection = await db.scalar(
        select(Collection).where(Collection.id == collection_id, Collection.user_id == user_id)
    )
    if collection is None:
        raise CollectionNotFoundError("Collection not found")
    return collection


async def add_paper_to_collection(db: AsyncSession, collection: Collection, paper_id: uuid.UUID) -> Collection:
    """Idempotent: adding an already-present paper_id is a no-op, not an
    error. Rebuilds the list rather than mutating it in place -- this
    project's immutability rule, and the practical reason SQLAlchemy's
    JSONB change-tracking needs a fresh list object assigned to notice the
    change (same pattern as ``app.discovery.service.update_milestone_status``).
    """
    paper_id_str = str(paper_id)
    if paper_id_str not in collection.paper_ids:
        collection.paper_ids = [*collection.paper_ids, paper_id_str]
        await db.commit()
        await db.refresh(collection)
    return collection


async def remove_paper_from_collection(db: AsyncSession, collection: Collection, paper_id: uuid.UUID) -> Collection:
    """No-op if ``paper_id`` isn't present in the collection, not an error."""
    paper_id_str = str(paper_id)
    if paper_id_str in collection.paper_ids:
        collection.paper_ids = [pid for pid in collection.paper_ids if pid != paper_id_str]
        await db.commit()
        await db.refresh(collection)
    return collection
