"""Integration tests for ``app.discovery.service``'s Phase 6 roadmap
entrypoints -- real Postgres, fake AI provider, milestone selection mocked at
the ``app.discovery.service`` import site (same sanctioned
internal-boundary-adjacent mock ``test_service_integration.py`` uses for
``search_arxiv_topic``) so these tests exercise the orchestration wiring
(concept grounding -> prerequisite mapping -> sequencing -> persistence)
without re-proving arXiv-search/embedding-rerank correctness already covered
by ``test_ranking.py``/``test_service_integration.py``.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.discovery.exceptions import (
    InvalidMilestoneStatusError,
    MilestoneNotFoundError,
    RoadmapNotFoundError,
)
from app.discovery.schemas import (
    ConceptExtractionOutput,
    ConceptTermDraft,
    PrerequisiteExtractionOutput,
    RoadmapOverviewOutput,
    RoadmapPaperTarget,
    RoadmapTopicTarget,
)
from app.discovery.service import (
    build_roadmap_summary,
    get_owned_roadmap,
    list_roadmaps,
    run_roadmap_generation,
    update_milestone_status,
)
from app.models.glossary_term import GlossaryTerm
from app.models.paper import Paper, ParseStatus
from app.models.roadmap import Roadmap
from app.papers.arxiv_client import ArxivMetadata
from app.providers.ping import _PingResponse
from tests.discovery.conftest import make_user
from tests.discovery.fake_provider import FakeDiscoveryProvider

_ABSTRACT_A = "We propose method A that improves accuracy by 5% using attention layers."
_ABSTRACT_B = "We propose method B that reduces latency by 20% using pruning techniques."


def _candidate_a() -> ArxivMetadata:
    return ArxivMetadata(
        arxiv_id="2001.00001", title="Paper A", authors=["Alice"], year=2021,
        pdf_url="https://arxiv.org/pdf/2001.00001", abstract=_ABSTRACT_A,
    )


def _candidate_b() -> ArxivMetadata:
    return ArxivMetadata(
        arxiv_id="2001.00002", title="Paper B", authors=["Bob"], year=2022,
        pdf_url="https://arxiv.org/pdf/2001.00002", abstract=_ABSTRACT_B,
    )


def _concepts_output(*, prefix: str, excerpts: list[str]) -> ConceptExtractionOutput:
    return ConceptExtractionOutput(
        concepts=[
            ConceptTermDraft(term=f"{prefix} {i}", definition=f"{prefix} concept {i}.", excerpt=excerpt)
            for i, excerpt in enumerate(excerpts)
        ]
    )


def _response_fn(prompt: str, schema: type) -> object:
    if schema is _PingResponse:
        return _PingResponse(ok=True)
    if schema is ConceptExtractionOutput:
        if "method A" in prompt:
            return _concepts_output(
                prefix="A", excerpts=["We propose method A", "improves accuracy by 5%", "attention layers"]
            )
        return _concepts_output(
            prefix="B", excerpts=["We propose method B", "reduces latency by 20%", "pruning techniques"]
        )
    if schema is PrerequisiteExtractionOutput:
        return PrerequisiteExtractionOutput(edges=[])
    if schema is RoadmapOverviewOutput:
        return RoadmapOverviewOutput(overview="A learning path overview.")
    raise AssertionError(f"unexpected schema {schema}")


@pytest.fixture
def fake_provider() -> FakeDiscoveryProvider:
    return FakeDiscoveryProvider(_response_fn)


@pytest.fixture(autouse=True)
def _patch_provider_and_session(
    monkeypatch: pytest.MonkeyPatch, db_engine: AsyncEngine, fake_provider: FakeDiscoveryProvider
) -> None:
    monkeypatch.setattr("app.discovery.service.build_provider", lambda *a, **k: fake_provider)
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr("app.discovery.service.AsyncSessionLocal", session_factory)


# --- run_roadmap_generation: topic target -----------------------------------


async def test_run_roadmap_generation_topic_target_persists_roadmap(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)

    async def _fake_select_topic(provider: object, topic: str, *, beginner: bool, embed_model: str) -> list[ArxivMetadata]:
        return [_candidate_a(), _candidate_b()]

    monkeypatch.setattr("app.discovery.service.select_milestone_candidates_for_topic", _fake_select_topic)

    events = [
        event
        async for event in run_roadmap_generation(
            user_id=user.id,
            target=RoadmapTopicTarget(type="topic", topic="attention mechanisms"),
            provider_id="google",
            api_key="fake-key",
            endpoint=None,
            model="m",
            embed_model="m",
        )
    ]

    assert events[-1].type == "done", events
    assert not any(event.type == "error" for event in events)

    roadmap_id = uuid.UUID(events[-1].data["id"])
    roadmap = await db_session.get(Roadmap, roadmap_id)
    assert roadmap is not None
    assert roadmap.user_id == user.id
    assert roadmap.target_description == "attention mechanisms"
    assert roadmap.target_paper_id is None
    assert len(roadmap.milestones) == 2
    assert len(roadmap.concepts) == 6  # 3 verified concepts per candidate
    assert roadmap.overview == "A learning path overview."
    assert all(concept["verification_status"] == "verified" for concept in roadmap.concepts)
    assert roadmap.milestones[0]["status"] == "available"
    assert roadmap.milestones[1]["status"] == "locked"


async def test_run_roadmap_generation_topic_target_emits_error_on_empty_candidates(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)

    async def _fake_select_topic_empty(provider: object, topic: str, *, beginner: bool, embed_model: str) -> list[ArxivMetadata]:
        return []

    monkeypatch.setattr("app.discovery.service.select_milestone_candidates_for_topic", _fake_select_topic_empty)

    events = [
        event
        async for event in run_roadmap_generation(
            user_id=user.id,
            target=RoadmapTopicTarget(type="topic", topic="an obscure topic"),
            provider_id="google",
            api_key="k",
            endpoint=None,
            model="m",
            embed_model="m",
        )
    ]

    assert events[-1].type == "error"


# --- run_roadmap_generation: paper target -----------------------------------


async def test_run_roadmap_generation_paper_target_persists_roadmap_anchored_on_owned_paper(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    paper = Paper(
        user_id=user.id,
        title="Anchor Paper",
        authors=[],
        source_file_path="/tmp/anchor.pdf",
        parse_status=ParseStatus.parsed,
        arxiv_id="9999.00001",
    )
    db_session.add(paper)
    await db_session.commit()
    await db_session.refresh(paper)
    db_session.add(
        GlossaryTerm(
            paper_id=paper.id,
            term="Anchor Concept",
            definition="The anchor paper's own concept.",
            source_page=1,
            source_excerpt="anchor excerpt",
        )
    )
    await db_session.commit()

    async def _fake_select_paper(
        provider: object, *, anchor_title: str, anchor_arxiv_id: str | None, beginner: bool, embed_model: str
    ) -> list[ArxivMetadata]:
        return [_candidate_a()]

    monkeypatch.setattr("app.discovery.service.select_milestone_candidates_for_paper", _fake_select_paper)

    events = [
        event
        async for event in run_roadmap_generation(
            user_id=user.id,
            target=RoadmapPaperTarget(type="paper", paper_id=paper.id),
            provider_id="google",
            api_key="k",
            endpoint=None,
            model="m",
            embed_model="m",
        )
    ]

    assert events[-1].type == "done", events
    roadmap_id = uuid.UUID(events[-1].data["id"])
    roadmap = await db_session.get(Roadmap, roadmap_id)
    assert roadmap is not None
    assert roadmap.target_paper_id == paper.id
    assert roadmap.target_description == "Anchor Paper"
    assert len(roadmap.milestones) == 2

    anchor_milestone = next(m for m in roadmap.milestones if m["paper_id"] == str(paper.id))
    assert anchor_milestone["arxiv_id"] == "9999.00001"
    anchor_concept_ids = set(anchor_milestone["concept_ids"])
    assert any(concept["id"] in anchor_concept_ids and concept["name"] == "Anchor Concept" for concept in roadmap.concepts)


async def test_run_roadmap_generation_paper_target_rejects_unowned_paper(
    db_session: AsyncSession,
) -> None:
    owner = await make_user(db_session)
    intruder = await make_user(db_session)
    paper = Paper(
        user_id=owner.id, title="Owner's Paper", authors=[], source_file_path="/tmp/x.pdf",
        parse_status=ParseStatus.parsed,
    )
    db_session.add(paper)
    await db_session.commit()
    await db_session.refresh(paper)

    events = [
        event
        async for event in run_roadmap_generation(
            user_id=intruder.id,
            target=RoadmapPaperTarget(type="paper", paper_id=paper.id),
            provider_id="google",
            api_key="k",
            endpoint=None,
            model="m",
            embed_model="m",
        )
    ]

    assert events[-1].type == "error"


# --- get_owned_roadmap / list_roadmaps / build_roadmap_summary --------------


def _sample_roadmap(user_id: uuid.UUID) -> Roadmap:
    return Roadmap(
        user_id=user_id,
        target_description="attention",
        concepts=[
            {
                "id": "c1",
                "name": "Attention",
                "description": "d",
                "source_paper_id": None,
                "source_arxiv_id": "2001.00001",
                "grounding_excerpt": "e",
                "verification_status": "verified",
            }
        ],
        edges=[],
        milestones=[
            {
                "id": "m1",
                "order": 0,
                "paper_id": None,
                "arxiv_id": "2001.00001",
                "title": "Paper A",
                "concept_ids": ["c1"],
                "status": "completed",
            },
            {
                "id": "m2",
                "order": 1,
                "paper_id": None,
                "arxiv_id": "2001.00002",
                "title": "Paper B",
                "concept_ids": [],
                "status": "locked",
            },
        ],
        overview="An overview.",
    )


async def test_get_owned_roadmap_rejects_other_users_roadmap(db_session: AsyncSession) -> None:
    owner = await make_user(db_session)
    intruder = await make_user(db_session)
    roadmap = _sample_roadmap(owner.id)
    db_session.add(roadmap)
    await db_session.commit()
    await db_session.refresh(roadmap)

    with pytest.raises(RoadmapNotFoundError):
        await get_owned_roadmap(db_session, roadmap.id, intruder.id)


async def test_get_owned_roadmap_rejects_nonexistent_id(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    with pytest.raises(RoadmapNotFoundError):
        await get_owned_roadmap(db_session, uuid.uuid4(), user.id)


async def test_list_roadmaps_returns_only_owned(db_session: AsyncSession) -> None:
    owner = await make_user(db_session)
    other = await make_user(db_session)
    db_session.add(_sample_roadmap(owner.id))
    db_session.add(_sample_roadmap(other.id))
    await db_session.commit()

    roadmaps = await list_roadmaps(db_session, owner.id)

    assert len(roadmaps) == 1
    assert roadmaps[0].user_id == owner.id


async def test_build_roadmap_summary_counts_milestones(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    roadmap = _sample_roadmap(user.id)
    db_session.add(roadmap)
    await db_session.commit()
    await db_session.refresh(roadmap)

    summary = build_roadmap_summary(roadmap)

    assert summary.target_description == "attention"
    assert summary.milestone_count == 2
    assert summary.completed_count == 1


# --- update_milestone_status -------------------------------------------


async def test_update_milestone_status_persists_new_status(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    roadmap = _sample_roadmap(user.id)
    db_session.add(roadmap)
    await db_session.commit()
    await db_session.refresh(roadmap)

    updated = await update_milestone_status(db_session, roadmap.id, user.id, "m2", "completed")

    statuses = {m["id"]: m["status"] for m in updated.milestones}
    assert statuses["m2"] == "completed"
    assert statuses["m1"] == "completed"  # untouched entry preserved


async def test_update_milestone_status_raises_for_unknown_milestone(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    roadmap = _sample_roadmap(user.id)
    db_session.add(roadmap)
    await db_session.commit()
    await db_session.refresh(roadmap)

    with pytest.raises(MilestoneNotFoundError):
        await update_milestone_status(db_session, roadmap.id, user.id, "does-not-exist", "completed")


async def test_update_milestone_status_raises_for_invalid_status(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    roadmap = _sample_roadmap(user.id)
    db_session.add(roadmap)
    await db_session.commit()
    await db_session.refresh(roadmap)

    with pytest.raises(InvalidMilestoneStatusError):
        await update_milestone_status(db_session, roadmap.id, user.id, "m1", "not-a-real-status")


async def test_update_milestone_status_rejects_other_users_roadmap(db_session: AsyncSession) -> None:
    owner = await make_user(db_session)
    intruder = await make_user(db_session)
    roadmap = _sample_roadmap(owner.id)
    db_session.add(roadmap)
    await db_session.commit()
    await db_session.refresh(roadmap)

    with pytest.raises(RoadmapNotFoundError):
        await update_milestone_status(db_session, roadmap.id, intruder.id, "m1", "completed")
