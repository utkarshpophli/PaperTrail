"""Integration tests for ``app.discovery.service.promote_landscape`` -- real
Postgres (TESTING.md), covering the ingested-vs-not-ingested split behavior
that's the whole point of this endpoint (ARCHITECTURE.md's Phase 7
decisions: only already-owned ``Paper`` rows get added; the rest are
reported back as skipped, never invented).
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.collections.service import create_collection
from app.discovery.exceptions import InvalidPromoteTargetError
from app.discovery.service import promote_landscape
from app.models.paper import Paper, ParseStatus
from app.models.topic_landscape import TopicLandscape
from tests.discovery.conftest import make_user


def _landscape_with_papers(user_id: object, arxiv_ids: list[str]) -> TopicLandscape:
    return TopicLandscape(
        user_id=user_id,
        topic="a topic",
        overview="an overview",
        papers=[
            {
                "arxiv_id": arxiv_id,
                "title": f"Paper {arxiv_id}",
                "authors": [],
                "year": 2021,
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
                "abstract": "abstract",
                "relevance_score": 0.5,
                "cluster_id": None,
                "extraction": None,
            }
            for arxiv_id in arxiv_ids
        ],
        clusters=[],
    )


async def test_promote_creates_collection_and_splits_ingested_vs_not_ingested(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    owned_paper = Paper(
        user_id=user.id,
        title="Owned",
        authors=[],
        source_file_path="/tmp/a.pdf",
        parse_status=ParseStatus.parsed,
        arxiv_id="2001.00001",
    )
    db_session.add(owned_paper)
    await db_session.commit()

    landscape = _landscape_with_papers(user.id, ["2001.00001", "2001.00002"])
    db_session.add(landscape)
    await db_session.commit()
    await db_session.refresh(landscape)

    collection, added, skipped = await promote_landscape(
        db_session, user.id, landscape.id, collection_id=None, collection_name="Promoted"
    )

    assert collection.name == "Promoted"
    assert added == ["2001.00001"]
    assert skipped == ["2001.00002"]
    assert collection.paper_ids == [str(owned_paper.id)]


async def test_promote_requires_a_target(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    landscape = _landscape_with_papers(user.id, [])
    db_session.add(landscape)
    await db_session.commit()
    await db_session.refresh(landscape)

    with pytest.raises(InvalidPromoteTargetError):
        await promote_landscape(db_session, user.id, landscape.id, collection_id=None, collection_name=None)


async def test_promote_into_existing_collection_appends(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    owned_paper = Paper(
        user_id=user.id,
        title="Owned",
        authors=[],
        source_file_path="/tmp/a.pdf",
        parse_status=ParseStatus.parsed,
        arxiv_id="2001.00003",
    )
    db_session.add(owned_paper)
    await db_session.commit()

    existing = await create_collection(db_session, user.id, "Existing")

    landscape = _landscape_with_papers(user.id, ["2001.00003"])
    db_session.add(landscape)
    await db_session.commit()
    await db_session.refresh(landscape)

    collection, added, skipped = await promote_landscape(
        db_session, user.id, landscape.id, collection_id=existing.id, collection_name=None
    )

    assert collection.id == existing.id
    assert added == ["2001.00003"]
    assert skipped == []


async def test_promote_is_idempotent_across_calls(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    owned_paper = Paper(
        user_id=user.id,
        title="Owned",
        authors=[],
        source_file_path="/tmp/a.pdf",
        parse_status=ParseStatus.parsed,
        arxiv_id="2001.00004",
    )
    db_session.add(owned_paper)
    await db_session.commit()

    landscape = _landscape_with_papers(user.id, ["2001.00004"])
    db_session.add(landscape)
    await db_session.commit()
    await db_session.refresh(landscape)

    collection, _, _ = await promote_landscape(
        db_session, user.id, landscape.id, collection_id=None, collection_name="Promoted twice"
    )
    collection_again, added_again, _ = await promote_landscape(
        db_session, user.id, landscape.id, collection_id=collection.id, collection_name=None
    )

    assert collection_again.paper_ids == [str(owned_paper.id)]
    assert added_again == ["2001.00004"]
