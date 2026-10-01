"""Integration tests for ``app.discovery.service`` -- real Postgres
(TESTING.md: test against a real database, not mocks of our own persistence
layer), fake AI provider (mock the external boundary only), arXiv search
mocked at the ``app.discovery.service.search_arxiv_topic`` import site (same
sanctioned internal-boundary-adjacent mock ``tests/evidence`` uses for
``build_provider``).
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.discovery.exceptions import TopicLandscapeNotFoundError
from app.discovery.schemas import (
    ClusterAssignmentDraft,
    ExtractionFieldDraft,
    LandscapeClusteringOutput,
    PaperExtractionCardDraft,
)
from app.discovery.service import (
    build_landscape_graph,
    get_or_create_profile,
    get_owned_landscape,
    run_landscape_search,
    run_recommendations,
    update_profile,
)
from app.models.claim import VerificationStatus
from app.models.paper import Paper, ParseStatus
from app.models.topic_landscape import TopicLandscape
from app.papers.arxiv_client import ArxivMetadata
from app.papers.exceptions import ArxivUnavailableError
from app.providers.errors import AuthenticationError, NotSupportedError
from app.providers.ping import _PingResponse
from tests.discovery.conftest import make_user
from tests.discovery.fake_provider import FakeDiscoveryProvider

_ABSTRACT_A = "We propose method A that improves accuracy by 5% using attention layers."
_ABSTRACT_B = "We propose method B that reduces latency by 20% using pruning techniques."

_EMBEDDINGS = {
    "attention mechanisms": [1.0, 0.0],
    _ABSTRACT_A: [0.9, 0.1],
    _ABSTRACT_B: [0.1, 0.9],
}


def _candidates() -> list[ArxivMetadata]:
    return [
        ArxivMetadata(
            arxiv_id="2001.00001",
            title="Paper A",
            authors=["Alice"],
            year=2021,
            pdf_url="https://arxiv.org/pdf/2001.00001",
            abstract=_ABSTRACT_A,
        ),
        ArxivMetadata(
            arxiv_id="2001.00002",
            title="Paper B",
            authors=["Bob"],
            year=2022,
            pdf_url="https://arxiv.org/pdf/2001.00002",
            abstract=_ABSTRACT_B,
        ),
    ]


def _extraction_draft(excerpt: str) -> PaperExtractionCardDraft:
    field = ExtractionFieldDraft(text="A short summary.", excerpt=excerpt)
    return PaperExtractionCardDraft(tldr=field, problem=field, method=field, results=field, why_it_matters=field)


def _response_fn(prompt: str, schema: type) -> object:
    if schema is _PingResponse:
        return _PingResponse(ok=True)
    if schema is PaperExtractionCardDraft:
        if "method A" in prompt:
            return _extraction_draft("improves accuracy by 5%")
        return _extraction_draft("reduces latency by 20%")
    if schema is LandscapeClusteringOutput:
        return LandscapeClusteringOutput(
            overview="Two approaches: accuracy-focused and latency-focused.",
            clusters=[
                ClusterAssignmentDraft(
                    label="Accuracy-focused", description="Improves accuracy via attention.", arxiv_ids=["2001.00001"]
                ),
                ClusterAssignmentDraft(
                    label="Latency-focused", description="Reduces latency via pruning.", arxiv_ids=["2001.00002"]
                ),
            ],
        )
    raise AssertionError(f"unexpected schema {schema}")


@pytest.fixture
def fake_provider() -> FakeDiscoveryProvider:
    return FakeDiscoveryProvider(_response_fn, embeddings=_EMBEDDINGS)


@pytest.fixture(autouse=True)
def _patch_provider_and_session(
    monkeypatch: pytest.MonkeyPatch, db_engine: AsyncEngine, fake_provider: FakeDiscoveryProvider
) -> None:
    monkeypatch.setattr("app.discovery.service.build_provider", lambda *a, **k: fake_provider)
    # run_landscape_search opens its own session via AsyncSessionLocal --
    # point it at this test's per-loop engine (same pattern as
    # tests/evidence/test_service_integration.py).
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr("app.discovery.service.AsyncSessionLocal", session_factory)


async def test_run_landscape_search_persists_ranked_extracted_clustered_landscape(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    monkeypatch.setattr("app.discovery.service.search_arxiv_topic", _fake_search_candidates)

    events = [
        event
        async for event in run_landscape_search(
            user_id=user.id,
            topic="attention mechanisms",
            provider_id="google",
            api_key="fake-key",
            endpoint=None,
            model="m",
            embed_model="m",
        )
    ]

    assert events[-1].type == "done"
    assert not any(event.type == "error" for event in events)

    landscape_id = uuid.UUID(events[-1].data["id"])
    landscape = await db_session.get(TopicLandscape, landscape_id)
    assert landscape is not None
    assert landscape.user_id == user.id
    assert landscape.topic == "attention mechanisms"
    assert len(landscape.papers) == 2
    assert 2 <= len(landscape.clusters) <= 5

    # Ranked by cosine similarity to the topic -- Paper A's abstract vector
    # is closer to the topic vector than Paper B's.
    assert landscape.papers[0]["arxiv_id"] == "2001.00001"
    assert landscape.papers[0]["relevance_score"] > landscape.papers[1]["relevance_score"]

    # Every paper got a cluster assignment and a verified extraction card.
    for paper in landscape.papers:
        assert paper["cluster_id"] is not None
        assert paper["extraction"]["tldr"]["verification_status"] == VerificationStatus.verified.value

    # get_owned_landscape / build_landscape_graph round-trip.
    owned = await get_owned_landscape(db_session, landscape_id, user.id)
    graph = build_landscape_graph(owned)
    assert {node.id for node in graph.nodes} == {"2001.00001", "2001.00002"}
    assert len(graph.edges) == 0  # each cluster here has exactly one paper -- no same-cluster pairs
    assert all(node.color for node in graph.nodes)


async def test_get_owned_landscape_rejects_other_users_landscape(db_session: AsyncSession) -> None:
    owner = await make_user(db_session)
    intruder = await make_user(db_session)
    landscape = TopicLandscape(user_id=owner.id, topic="x", overview="x", papers=[], clusters=[])
    db_session.add(landscape)
    await db_session.commit()
    await db_session.refresh(landscape)

    with pytest.raises(TopicLandscapeNotFoundError):
        await get_owned_landscape(db_session, landscape.id, intruder.id)


async def test_get_owned_landscape_rejects_nonexistent_id(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    with pytest.raises(TopicLandscapeNotFoundError):
        await get_owned_landscape(db_session, uuid.uuid4(), user.id)


async def test_run_landscape_search_emits_error_event_on_empty_arxiv_result(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    monkeypatch.setattr("app.discovery.service.search_arxiv_topic", _fake_search_empty)

    events = [
        event
        async for event in run_landscape_search(
            user_id=user.id, topic="an obscure topic", provider_id="google", api_key="k", endpoint=None, model="m", embed_model="m"
        )
    ]

    assert events[-1].type == "error"
    assert "No arXiv results" in events[-1].message


async def test_run_landscape_search_emits_error_event_on_arxiv_unavailable(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)

    async def _raise(*args: object, **kwargs: object) -> list[ArxivMetadata]:
        raise ArxivUnavailableError("arXiv is down")

    monkeypatch.setattr("app.discovery.service.search_arxiv_topic", _raise)

    events = [
        event
        async for event in run_landscape_search(
            user_id=user.id, topic="topic", provider_id="google", api_key="k", endpoint=None, model="m", embed_model="m"
        )
    ]

    assert events[-1].type == "error"
    assert events[-1].stage == "landscape"


async def test_run_landscape_search_emits_error_event_when_embed_not_supported(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession, fake_provider: FakeDiscoveryProvider
) -> None:
    fake_provider_no_embed = FakeDiscoveryProvider(_response_fn, embed_error=NotSupportedError("no embed"))
    monkeypatch.setattr("app.discovery.service.build_provider", lambda *a, **k: fake_provider_no_embed)
    monkeypatch.setattr("app.discovery.service.search_arxiv_topic", _fake_search_candidates)
    user = await make_user(db_session)

    events = [
        event
        async for event in run_landscape_search(
            user_id=user.id, topic="topic", provider_id="ollama", api_key=None, endpoint="http://127.0.0.1:11434", model="m", embed_model="m"
        )
    ]

    assert events[-1].type == "error"


async def test_run_landscape_search_preflight_stops_before_arxiv_search(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    def _fail_ping(prompt: str, schema: type) -> object:
        raise AuthenticationError("bad key")

    fake_provider_bad_key = FakeDiscoveryProvider(_fail_ping)
    monkeypatch.setattr("app.discovery.service.build_provider", lambda *a, **k: fake_provider_bad_key)

    async def _search_should_not_be_called(topic: str, max_results: int = 30) -> list[ArxivMetadata]:
        raise AssertionError("arXiv search should not run when the preflight ping fails")

    monkeypatch.setattr("app.discovery.service.search_arxiv_topic", _search_should_not_be_called)
    user = await make_user(db_session)

    events = [
        event
        async for event in run_landscape_search(
            user_id=user.id, topic="topic", provider_id="google", api_key="k", endpoint=None, model="m", embed_model="m"
        )
    ]

    assert [e.type for e in events] == ["progress", "progress", "error"]
    assert events[1].message == "Checking model availability"
    assert events[2].stage == "landscape"


async def _fake_search_candidates(topic: str, max_results: int = 30) -> list[ArxivMetadata]:
    return _candidates()


async def _fake_search_empty(topic: str, max_results: int = 30) -> list[ArxivMetadata]:
    return []


# --- profile -----------------------------------------------------------


async def test_get_or_create_profile_defaults_lazily(db_session: AsyncSession) -> None:
    user = await make_user(db_session)

    profile = await get_or_create_profile(db_session, user.id)

    assert profile.interests == []
    assert profile.level == "beginner"
    assert profile.goals == []

    # Second call returns the same row, not a duplicate.
    profile_again = await get_or_create_profile(db_session, user.id)
    assert profile_again.id == profile.id


async def test_update_profile_upserts(db_session: AsyncSession) -> None:
    user = await make_user(db_session)

    updated = await update_profile(
        db_session, user.id, interests=["diffusion models"], level="intermediate", goals=["build a demo"]
    )

    assert updated.interests == ["diffusion models"]
    assert updated.level == "intermediate"
    assert updated.goals == ["build a demo"]

    fetched = await get_or_create_profile(db_session, user.id)
    assert fetched.id == updated.id
    assert fetched.interests == ["diffusion models"]


# --- recommendations -----------------------------------------------------


async def test_run_recommendations_grounds_explanation_in_matched_interest(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    await update_profile(db_session, user.id, interests=["attention mechanisms"], level="beginner", goals=[])

    async def _fake_search(topic: str, max_results: int = 10) -> list[ArxivMetadata]:
        return _candidates()

    monkeypatch.setattr("app.discovery.service.search_arxiv_topic", _fake_search)

    recommendations = await run_recommendations(
        db_session, user.id, provider_id="google", api_key="fake-key", endpoint=None, embed_model="m"
    )

    assert len(recommendations) == 2
    assert recommendations[0].arxiv_id == "2001.00001"
    assert "attention mechanisms" in recommendations[0].explanation


async def test_run_recommendations_excludes_papers_user_already_owns(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    await update_profile(db_session, user.id, interests=["attention mechanisms"], level="beginner", goals=[])
    db_session.add(
        Paper(
            user_id=user.id,
            title="Already owned",
            authors=[],
            source_file_path="/tmp/x.pdf",
            parse_status=ParseStatus.parsed,
            arxiv_id="2001.00001",
        )
    )
    await db_session.commit()

    async def _fake_search(topic: str, max_results: int = 10) -> list[ArxivMetadata]:
        return _candidates()

    monkeypatch.setattr("app.discovery.service.search_arxiv_topic", _fake_search)

    recommendations = await run_recommendations(
        db_session, user.id, provider_id="google", api_key="fake-key", endpoint=None, embed_model="m"
    )

    assert all(rec.arxiv_id != "2001.00001" for rec in recommendations)


async def test_run_recommendations_returns_empty_for_profile_with_no_signals(db_session: AsyncSession) -> None:
    user = await make_user(db_session)

    recommendations = await run_recommendations(
        db_session, user.id, provider_id="google", api_key="fake-key", endpoint=None, embed_model="m"
    )

    assert recommendations == []
