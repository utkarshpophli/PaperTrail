"""Real end-to-end test for the paper ingestion pipeline: uploads the
actual golden fixture (``tests/fixtures/s2orc_1911.02782v3.pdf``) through
the real API and lets it run through the real ``app.documents.parser``
pipeline — no mocking of ``parse_pdf`` here, unlike ``test_papers.py``'s
fast contract tests, which mock that module boundary deliberately.

This is the "add a real end-to-end test that uploads an actual PDF fixture
and asserts on real extracted text/figures" follow-up flagged in
test_papers.py's module docstring.
"""

import asyncio
import uuid
from pathlib import Path

from httpx import AsyncClient

from app.core.storage import paper_dir_path
from tests.test_papers import _auth_headers, _register_and_login  # reuse helpers

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "s2orc_1911.02782v3.pdf"

_POLL_MAX_ATTEMPTS = 30
_POLL_INTERVAL_SECONDS = 1.0


async def _poll_until_terminal(client: AsyncClient, paper_id: str, token: str) -> dict:
    for _ in range(_POLL_MAX_ATTEMPTS):
        response = await client.get(f"/papers/{paper_id}", headers=_auth_headers(token))
        body = response.json()
        if body["parse_status"] in ("parsed", "failed"):
            return body
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
    raise AssertionError(
        f"Paper {paper_id} did not reach a terminal parse_status within "
        f"{_POLL_MAX_ATTEMPTS * _POLL_INTERVAL_SECONDS}s (still {body['parse_status']!r})"
    )


async def test_real_pdf_uploads_parses_and_deletes_end_to_end(client: AsyncClient) -> None:
    token = await _register_and_login(client, "realpdf@example.com")
    pdf_bytes = FIXTURE_PATH.read_bytes()

    upload_response = await client.post(
        "/papers/upload",
        headers=_auth_headers(token),
        files={"file": ("s2orc_1911.02782v3.pdf", pdf_bytes, "application/pdf")},
    )
    assert upload_response.status_code == 201, upload_response.text
    paper_id = upload_response.json()["id"]

    paper = await _poll_until_terminal(client, paper_id, token)
    assert paper["parse_status"] == "parsed", (
        f"Real pipeline failed to parse the S2ORC fixture: {paper.get('parse_error')!r}"
    )

    page_response = await client.get(f"/papers/{paper_id}/pages/1", headers=_auth_headers(token))
    assert page_response.status_code == 200, page_response.text
    page_1_text = page_response.json()["text"]
    assert "S2ORC" in page_1_text or "Semantic Scholar" in page_1_text

    # The paper has 15 pages, 4 real embedded figures — at least one page
    # must have a non-empty figures list (not asserting which page, since
    # that's an implementation detail of the source PDF's layout).
    found_figure = False
    page_number = 1
    while True:
        resp = await client.get(f"/papers/{paper_id}/pages/{page_number}", headers=_auth_headers(token))
        if resp.status_code == 404:
            break
        if resp.json()["figures"]:
            found_figure = True
            break
        page_number += 1
    assert found_figure, "Expected at least one page with a non-empty figures list from the real fixture"

    on_disk_dir = paper_dir_path(uuid.UUID(paper_id))
    assert on_disk_dir.exists() and any(on_disk_dir.iterdir()), "Expected parsed output on disk before delete"

    delete_response = await client.delete(f"/papers/{paper_id}", headers=_auth_headers(token))
    assert delete_response.status_code == 204

    assert not on_disk_dir.exists(), "Paper directory should be removed from disk after delete"
