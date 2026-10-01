"""POST /papers/{id}/figures/refresh and the figure-serving route's filename
safety. Uses the real parser on a synthetic PDF with one vector figure."""

import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.storage import paper_dir_path
from app.models.page import Page
from tests.documents.pdf_builders import vector_figure_pdf
from tests.test_papers import _auth_headers, _register_and_login

STALE_JSON = [{"page": 1, "caption": "stale", "image_path": "figures/stale_old.png"}]


@pytest.fixture
def vector_pdf_bytes(tmp_path: Path) -> bytes:
    path = tmp_path / "vec.pdf"
    vector_figure_pdf(str(path))
    return path.read_bytes()


async def _upload(client: AsyncClient, token: str, pdf: bytes) -> str:
    response = await client.post(
        "/papers/upload", headers=_auth_headers(token), files={"file": ("vec.pdf", pdf, "application/pdf")}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _page_1(client: AsyncClient, token: str, paper_id: str) -> dict:
    response = await client.get(f"/papers/{paper_id}/pages/1", headers=_auth_headers(token))
    assert response.status_code == 200, response.text
    return response.json()


async def _set_page_figures(engine: AsyncEngine, paper_id: str, figures: list[dict]) -> None:
    async with async_sessionmaker(engine, class_=AsyncSession)() as session:
        await session.execute(
            update(Page).where(Page.paper_id == uuid.UUID(paper_id), Page.page_number == 1).values(figures=figures)
        )
        await session.commit()


async def test_refresh_requires_auth(client: AsyncClient) -> None:
    response = await client.post(f"/papers/{uuid.uuid4()}/figures/refresh")
    assert response.status_code == 401


async def test_refresh_of_another_users_paper_is_a_uniform_404(client: AsyncClient, vector_pdf_bytes: bytes) -> None:
    owner = await _register_and_login(client, "owner@example.com")
    other = await _register_and_login(client, "intruder@example.com")
    paper_id = await _upload(client, owner, vector_pdf_bytes)

    cross = await client.post(f"/papers/{paper_id}/figures/refresh", headers=_auth_headers(other))
    missing = await client.post(f"/papers/{uuid.uuid4()}/figures/refresh", headers=_auth_headers(other))

    assert cross.status_code == 404
    assert cross.json() == missing.json()
    assert cross.json()["error"]["code"] == "paper_not_found"


async def test_refresh_rejects_a_paper_that_is_not_parsed(
    client: AsyncClient, vector_pdf_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _never_parse(paper_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr("app.papers.router.run_parsing", _never_parse)
    token = await _register_and_login(client, "pending@example.com")
    paper_id = await _upload(client, token, vector_pdf_bytes)

    response = await client.post(f"/papers/{paper_id}/figures/refresh", headers=_auth_headers(token))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "paper_not_parsed"


async def test_refresh_rejects_when_source_pdf_is_gone(client: AsyncClient, vector_pdf_bytes: bytes) -> None:
    token = await _register_and_login(client, "nosource@example.com")
    paper_id = await _upload(client, token, vector_pdf_bytes)
    (paper_dir_path(uuid.UUID(paper_id)) / "vec.pdf").unlink()

    response = await client.post(f"/papers/{paper_id}/figures/refresh", headers=_auth_headers(token))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "source_pdf_missing"


async def test_refresh_replaces_old_files_and_json_and_leaves_text_alone(
    client: AsyncClient, db_engine: AsyncEngine, vector_pdf_bytes: bytes
) -> None:
    token = await _register_and_login(client, "refresh@example.com")
    paper_id = await _upload(client, token, vector_pdf_bytes)
    paper_dir = paper_dir_path(uuid.UUID(paper_id))
    text_before = (await _page_1(client, token, paper_id))["text"]

    stale_file = paper_dir / "figures" / "stale_old.png"
    stale_file.write_bytes(b"old")
    await _set_page_figures(db_engine, paper_id, STALE_JSON)
    outside_files = [paper_dir / "vec.pdf", paper_dir / "notes.txt"]
    (paper_dir / "notes.txt").write_text("keep me")
    other_paper_file = paper_dir_path(uuid.uuid4()) / "figures" / "keep.png"
    other_paper_file.parent.mkdir(parents=True)
    other_paper_file.write_bytes(b"other paper")

    response = await client.post(f"/papers/{paper_id}/figures/refresh", headers=_auth_headers(token))

    assert response.status_code == 200, response.text
    assert response.json() == {"figures": 1, "pages_with_figures": 1}
    assert not stale_file.exists()
    assert (paper_dir / "figures" / "page1_vec0.png").stat().st_size > 0
    assert not (paper_dir / ".figures-refresh").exists()
    assert all(f.exists() for f in outside_files) and other_paper_file.read_bytes() == b"other paper"

    page = await _page_1(client, token, paper_id)
    assert page["text"] == text_before
    assert [f["image_path"] for f in page["figures"]] == ["figures/page1_vec0.png"]
    assert page["figures"][0]["caption"] == "Figure 1: Overview of the model"
    assert set(page["figures"][0]) == {"page", "caption", "image_path"}

    served = await client.get(f"/papers/{paper_id}/figures/page1_vec0.png", headers=_auth_headers(token))
    assert served.status_code == 200
    assert served.content.startswith(b"\x89PNG")


async def test_refresh_never_follows_symlinks_out_of_the_figures_dir(
    client: AsyncClient, vector_pdf_bytes: bytes, tmp_path: Path
) -> None:
    token = await _register_and_login(client, "symlink@example.com")
    paper_id = await _upload(client, token, vector_pdf_bytes)
    victim = tmp_path / "victim.txt"
    victim.write_text("must survive")
    link = paper_dir_path(uuid.UUID(paper_id)) / "figures" / "link.png"
    try:
        link.symlink_to(victim)
    except OSError:
        pytest.skip("symlinks not permitted on this platform")

    response = await client.post(f"/papers/{paper_id}/figures/refresh", headers=_auth_headers(token))

    assert response.status_code == 200
    assert victim.read_text() == "must survive"
    assert not link.is_symlink()


async def test_refresh_is_rate_limited(client: AsyncClient, vector_pdf_bytes: bytes) -> None:
    token = await _register_and_login(client, "limited@example.com")
    paper_id = await _upload(client, token, vector_pdf_bytes)

    statuses = [
        (await client.post(f"/papers/{paper_id}/figures/refresh", headers=_auth_headers(token))).status_code
        for _ in range(6)
    ]

    assert statuses[:5] == [200] * 5
    assert statuses[5] == 429


@pytest.mark.parametrize(
    "filename",
    ["..%2F..%2Fvec.pdf", "..%5C..%5Cvec.pdf", "%2E%2E%2Fvec.pdf", "page1_vec0.png%00.pdf"],
)
async def test_figure_route_rejects_path_traversal(client: AsyncClient, vector_pdf_bytes: bytes, filename: str) -> None:
    token = await _register_and_login(client, "traverse@example.com")
    paper_id = await _upload(client, token, vector_pdf_bytes)

    response = await client.get(f"/papers/{paper_id}/figures/{filename}", headers=_auth_headers(token))

    assert response.status_code in (404, 422)
    assert b"%PDF" not in response.content


async def test_figure_route_serves_vec_filenames_only_to_the_owner(client: AsyncClient, vector_pdf_bytes: bytes) -> None:
    owner = await _register_and_login(client, "servowner@example.com")
    other = await _register_and_login(client, "servother@example.com")
    paper_id = await _upload(client, owner, vector_pdf_bytes)

    ok = await client.get(f"/papers/{paper_id}/figures/page1_vec0.png", headers=_auth_headers(owner))
    denied = await client.get(f"/papers/{paper_id}/figures/page1_vec0.png", headers=_auth_headers(other))

    assert ok.status_code == 200
    assert denied.status_code == 404

