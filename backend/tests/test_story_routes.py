"""GET /papers/{id}/story-spec, GET /papers/{id}/figures, the ``data`` field on
GET /papers/{id}/story, and the demo seed (scripts.seed_demo) that exercises
all of them end to end against real Postgres."""

import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.evidence import service
from app.evidence.story_integrity import check_story_integrity
from app.evidence.story_visuals import StorySpec, StorySpecResponse, VisualAdapter
from app.models.claim import Claim, ClaimKind, VerificationStatus
from app.models.figure import Figure
from app.models.generated_section import GeneratedSection, SectionType
from app.models.page import Page
from app.models.paper import Paper, ParseStatus
from scripts import demo_content
from scripts.seed_demo import seed

PASSWORD = "correct-horse-battery"
ALL_VISUAL_TYPES = {
    "metric", "flow", "comparison", "concept", "layers", "quote",
    "architecture", "equation", "timeline", "matrix", "infographic",
}  # fmt: skip


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    async with async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)() as session:
        yield session


@pytest.fixture(autouse=True)
def _storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    return tmp_path


@pytest.fixture
def local_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "local_mode", True)


# --- the demo seed ---------------------------------------------------------------


async def test_seed_creates_a_paper_whose_story_passes_the_integrity_checker(
    db_session: AsyncSession,
) -> None:
    paper_id = await seed(db_session)

    paper = await db_session.get(Paper, paper_id)
    assert paper is not None and paper.title == "Demo paper (illustrative data)"
    assert paper.parse_status == ParseStatus.parsed

    spec = await service.get_story_spec(db_session, paper_id)
    story = StorySpec.model_validate(
        {
            "meta": spec.meta.model_dump(),
            "sections": [
                {**s.model_dump(mode="json", exclude={"id", "index_label"})} for s in spec.sections
            ],
        }
    )
    claims = await service._load_claims_for_prompt(db_session, paper_id)
    metrics = await service._load_metrics_for_prompt(db_session, paper_id)
    check_story_integrity(story, claims, metrics)  # raises on any rule violation
    assert {s.visual.type for s in spec.sections} == ALL_VISUAL_TYPES
    assert [s.index_label for s in spec.sections] == [f"{i:02d}" for i in range(1, 12)]


async def test_seed_claims_have_verifier_set_mixed_statuses_and_all_five_kinds(db_session: AsyncSession) -> None:
    paper_id = await seed(db_session)
    claims = (await db_session.scalars(select(Claim).where(Claim.paper_id == paper_id))).all()

    statuses = {c.verification_status for c in claims}
    assert {VerificationStatus.verified, VerificationStatus.partially_matched, VerificationStatus.needs_review} <= statuses
    assert len({c.kind for c in claims}) == 5
    assert all(c.source_refs for c in claims)


async def test_seed_states_that_it_is_illustrative(db_session: AsyncSession) -> None:
    paper_id = await seed(db_session)
    evidence = await service.get_evidence(db_session, paper_id)

    for text in (evidence.thesis, evidence.plain_summary):
        assert "illustrative" in text.lower() or "fabricated" in text.lower()
    assert "not a real paper" in demo_content.PAGES[1].lower()


async def test_seed_is_idempotent_and_reset_recreates(db_session: AsyncSession, _storage: Path) -> None:
    first = await seed(db_session)
    assert await seed(db_session) == first
    assert await db_session.scalar(select(func.count()).select_from(Paper)) == 1

    second = await seed(db_session, reset=True)
    assert second != first
    assert await db_session.scalar(select(func.count()).select_from(Paper)) == 1
    assert not (_storage / str(first)).exists()
    assert (_storage / str(second) / "figures" / "page1_fig0.png").is_file()


async def test_every_endpoint_serves_the_seeded_paper(
    client: AsyncClient, db_session: AsyncSession, local_mode: None
) -> None:
    paper_id = await seed(db_session)

    spec = await client.get(f"/papers/{paper_id}/story-spec")
    assert spec.status_code == 200, spec.text
    body = spec.json()
    StorySpecResponse.model_validate(body)  # the fixed contract
    assert set(body["meta"]) == {"title", "dek", "reading_time", "closing"}
    assert set(body["sections"][0]) == {"id", "index_label", "kicker", "title", "body", "claim_ids", "visual"}
    assert {"eyebrow", "caption", "type"} <= set(body["sections"][0]["visual"])
    for section in body["sections"]:
        VisualAdapter.validate_python(section["visual"])
        assert section["claim_ids"]

    story = await client.get(f"/papers/{paper_id}/story")
    assert story.status_code == 200
    rows = story.json()
    assert len(rows) == len(body["sections"])
    assert set(rows[0]["data"]) == {"kicker", "index_label", "visual"}

    figures = await client.get(f"/papers/{paper_id}/figures")
    assert figures.status_code == 200
    listed = figures.json()
    assert [f["filename"] for f in listed] == ["page1_fig0.png", "page2_fig0.png", "page3_fig0.png"]
    assert set(listed[0]) == {"id", "filename", "page", "label", "caption", "why_it_matters", "claim_ids"}
    assert [f["label"] for f in listed] == ["Figure 1", "Figure 2", "Figure 3"]
    assert all(f["claim_ids"] and f["why_it_matters"] for f in listed)
    claim_ids_in_story = {cid for s in body["sections"] for cid in s["claim_ids"]}
    assert all(set(f["claim_ids"]) <= claim_ids_in_story for f in listed)  # figures link to claims the story uses

    image = await client.get(f"/papers/{paper_id}/figures/{listed[0]['filename']}")
    assert image.status_code == 200 and image.content[:4] == b"\x89PNG"

    for path in ("evidence", "report", "technical-appendix", "learning"):
        response = await client.get(f"/papers/{paper_id}/{path}")
        assert response.status_code == 200, (path, response.text)
    learning = (await client.get(f"/papers/{paper_id}/learning")).json()
    assert learning["primer"] and learning["quiz"] and learning["derivations"] and learning["interactives"]


# --- route behaviour on hand-built papers ------------------------------------------


async def _register(client: AsyncClient, email: str) -> tuple[str, dict[str, str]]:
    response = await client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    login = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return response.json()["id"], {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _paper(db: AsyncSession, user_id: str, figures: list[dict] | None = None) -> uuid.UUID:
    paper = Paper(user_id=uuid.UUID(user_id), title="P", source_file_path="/tmp/x.pdf", parse_status=ParseStatus.parsed)
    db.add(paper)
    await db.commit()
    if figures is not None:
        db.add(Page(paper_id=paper.id, page_number=1, text="t", figures=figures))
        await db.commit()
    return paper.id


@pytest.mark.parametrize("path", ["story-spec", "figures"])
async def test_routes_require_auth(client: AsyncClient, path: str) -> None:
    response = await client.get(f"/papers/{uuid.uuid4()}/{path}")
    assert response.status_code == 401


@pytest.mark.parametrize("path", ["story-spec", "figures"])
async def test_routes_404_for_someone_elses_paper(
    client: AsyncClient, db_session: AsyncSession, path: str
) -> None:
    owner_id, _ = await _register(client, f"owner-{path}@example.com")
    _, intruder = await _register(client, f"intruder-{path}@example.com")
    paper_id = await _paper(db_session, owner_id, figures=[])

    response = await client.get(f"/papers/{paper_id}/{path}", headers=intruder)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "paper_not_found"


async def test_story_spec_404s_with_story_not_found(client: AsyncClient, db_session: AsyncSession) -> None:
    user_id, headers = await _register(client, "nostory@example.com")
    paper_id = await _paper(db_session, user_id)

    response = await client.get(f"/papers/{paper_id}/story-spec", headers=headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "story_not_found"


async def test_legacy_story_rows_still_serve_on_story_but_404_on_story_spec(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user_id, headers = await _register(client, "legacy@example.com")
    paper_id = await _paper(db_session, user_id)
    db_session.add(
        GeneratedSection(paper_id=paper_id, section_type=SectionType.story, order=0, title="Old", content="Body", claim_ids=[])
    )
    await db_session.commit()

    story = await client.get(f"/papers/{paper_id}/story", headers=headers)
    assert story.status_code == 200
    assert story.json()[0]["title"] == "Old" and story.json()[0]["data"] is None

    spec = await client.get(f"/papers/{paper_id}/story-spec", headers=headers)
    assert spec.status_code == 404 and spec.json()["error"]["code"] == "story_not_found"


async def test_figures_list_includes_unenriched_figures_with_parsed_label(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user_id, headers = await _register(client, "figs@example.com")
    paper_id = await _paper(
        db_session,
        user_id,
        figures=[
            {"page": 3, "caption": "Fig. 7. Loss curves.", "image_path": "figures/page3_fig1.png"},
            {"page": 1, "caption": None, "image_path": "figures/page1_fig0.png"},
        ],
    )

    response = await client.get(f"/papers/{paper_id}/figures", headers=headers)

    assert response.status_code == 200
    assert response.json() == [
        {"id": "page1_fig0.png", "filename": "page1_fig0.png", "page": 1, "label": None, "caption": None, "why_it_matters": None, "claim_ids": []},
        {"id": "page3_fig1.png", "filename": "page3_fig1.png", "page": 3, "label": "Figure 7", "caption": "Fig. 7. Loss curves.", "why_it_matters": None, "claim_ids": []},
    ]


async def test_figures_list_enriches_from_rows_and_drops_stale_claim_ids(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user_id, headers = await _register(client, "enrich@example.com")
    paper_id = await _paper(
        db_session, user_id, figures=[{"page": 1, "caption": "Figure 1: x", "image_path": "figures/page1_fig0.png"}]
    )
    live = Claim(paper_id=paper_id, statement="s", kind=ClaimKind.method)
    db_session.add(live)
    await db_session.commit()
    stale = uuid.uuid4()  # e.g. a claim replaced by an evidence re-run
    db_session.add(
        Figure(
            paper_id=paper_id, filename="page1_fig0.png", page=1, label="Figure 1",
            why_it_matters="Because.", claim_ids=[str(live.id), str(stale)],
        )
    )  # fmt: skip
    await db_session.commit()

    (item,) = (await client.get(f"/papers/{paper_id}/figures", headers=headers)).json()

    assert item["why_it_matters"] == "Because."
    assert item["claim_ids"] == [str(live.id)]
