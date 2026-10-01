"""Contract tests for POST /papers/{id}/assistant.

``app.evidence.service.run_assistant`` is mocked here -- the same sanctioned
internal-boundary mock (TESTING.md) test_evidence.py uses for
``run_analysis`` (rag-engineer's real retrieval/generation logic, built in
parallel, isn't what's under test in this file).
"""

import logging
import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient

from app.evidence.exceptions import EvidenceNotFoundError
from app.evidence.service import AnalysisEvent

PASSWORD = "correct-horse-battery"


async def _register_and_login(client: AsyncClient, email: str) -> str:
    response = await client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    login_response = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login_response.status_code == 200, login_response.text
    return login_response.json()["access_token"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _upload_paper(client: AsyncClient, token: str) -> str:
    response = await client.post(
        "/papers/upload",
        headers=_auth_headers(token),
        files={"file": ("paper.pdf", b"%PDF-1.4 fake pdf bytes", "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _assistant_body(action: str = "understand", **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {"action": action, "provider_id": "openai", "api_key": "sk-test", "model": "m"}
    body.update(overrides)
    return body


async def _events_done() -> AsyncIterator[AnalysisEvent]:
    yield AnalysisEvent(type="progress", message="Thinking...")
    yield AnalysisEvent(type="done", data={"answer": "It uses a transformer.", "claim_ids": [str(uuid.uuid4())]})


def _mock_run_assistant(monkeypatch: pytest.MonkeyPatch, events_factory: object) -> None:
    # raising=False: app.evidence.service.run_assistant is rag-engineer's
    # contract, built in parallel -- these tests must pass whether this run
    # lands before or after that module gains the real function.
    monkeypatch.setattr("app.evidence.service.run_assistant", lambda **kwargs: events_factory(), raising=False)


# ---- action validation --------------------------------------------------


async def test_compare_action_without_compare_with_is_rejected(client: AsyncClient) -> None:
    token = await _register_and_login(client, "assistant-compare-missing@example.com")
    paper_id = await _upload_paper(client, token)

    response = await client.post(
        f"/papers/{paper_id}/assistant",
        headers=_auth_headers(token),
        json=_assistant_body(action="compare"),
    )

    assert response.status_code == 422


async def test_compare_action_with_empty_compare_with_is_rejected(client: AsyncClient) -> None:
    token = await _register_and_login(client, "assistant-compare-empty@example.com")
    paper_id = await _upload_paper(client, token)

    response = await client.post(
        f"/papers/{paper_id}/assistant",
        headers=_auth_headers(token),
        json=_assistant_body(action="compare", compare_with=[]),
    )

    assert response.status_code == 422


async def test_non_compare_action_with_compare_with_is_rejected(client: AsyncClient) -> None:
    token = await _register_and_login(client, "assistant-non-compare@example.com")
    paper_id = await _upload_paper(client, token)

    response = await client.post(
        f"/papers/{paper_id}/assistant",
        headers=_auth_headers(token),
        json=_assistant_body(action="understand", compare_with=[str(uuid.uuid4())]),
    )

    assert response.status_code == 422


async def test_compare_with_over_five_papers_is_rejected(client: AsyncClient) -> None:
    token = await _register_and_login(client, "assistant-compare-toomany@example.com")
    paper_id = await _upload_paper(client, token)

    response = await client.post(
        f"/papers/{paper_id}/assistant",
        headers=_auth_headers(token),
        json=_assistant_body(action="compare", compare_with=[str(uuid.uuid4()) for _ in range(6)]),
    )

    assert response.status_code == 422


async def test_question_over_max_length_is_rejected(client: AsyncClient) -> None:
    token = await _register_and_login(client, "assistant-question-toolong@example.com")
    paper_id = await _upload_paper(client, token)

    response = await client.post(
        f"/papers/{paper_id}/assistant",
        headers=_auth_headers(token),
        json=_assistant_body(question="x" * 4001),
    )

    assert response.status_code == 422


# ---- ownership ------------------------------------------------------------


async def test_assistant_rejects_nonexistent_paper(client: AsyncClient) -> None:
    token = await _register_and_login(client, "assistant-missing@example.com")

    response = await client.post(
        f"/papers/{uuid.uuid4()}/assistant",
        headers=_auth_headers(token),
        json=_assistant_body(),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "paper_not_found"


async def test_assistant_rejects_non_owned_primary_paper(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_run_assistant(monkeypatch, _events_done)
    owner_token = await _register_and_login(client, "assistant-owner@example.com")
    intruder_token = await _register_and_login(client, "assistant-intruder@example.com")
    paper_id = await _upload_paper(client, owner_token)

    response = await client.post(
        f"/papers/{paper_id}/assistant",
        headers=_auth_headers(intruder_token),
        json=_assistant_body(),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "paper_not_found"


async def test_assistant_rejects_compare_with_paper_owned_by_another_user(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The primary paper is owned by the requester, but one id in
    ``compare_with`` belongs to a different user -- the whole request must
    fail with the same ``paper_not_found`` 404 as any other ownership
    failure, not silently proceed with a partial claim set."""
    _mock_run_assistant(monkeypatch, _events_done)
    requester_token = await _register_and_login(client, "assistant-compare-requester@example.com")
    other_token = await _register_and_login(client, "assistant-compare-other@example.com")
    own_paper_id = await _upload_paper(client, requester_token)
    other_paper_id = await _upload_paper(client, other_token)

    response = await client.post(
        f"/papers/{own_paper_id}/assistant",
        headers=_auth_headers(requester_token),
        json=_assistant_body(action="compare", compare_with=[other_paper_id]),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "paper_not_found"


async def test_assistant_allows_compare_with_own_papers(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_run_assistant(monkeypatch, _events_done)
    token = await _register_and_login(client, "assistant-compare-own@example.com")
    primary_paper_id = await _upload_paper(client, token)
    other_paper_id = await _upload_paper(client, token)

    response = await client.post(
        f"/papers/{primary_paper_id}/assistant",
        headers=_auth_headers(token),
        json=_assistant_body(action="compare", compare_with=[other_paper_id]),
    )

    assert response.status_code == 200, response.text


# ---- streaming / pre-flight errors -----------------------------------------


async def test_assistant_streams_sse_formatted_events(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_run_assistant(monkeypatch, _events_done)
    token = await _register_and_login(client, "assistant-stream@example.com")
    paper_id = await _upload_paper(client, token)

    response = await client.post(
        f"/papers/{paper_id}/assistant",
        headers=_auth_headers(token),
        json=_assistant_body(),
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "event: progress\n" in body
    assert "event: done\n" in body
    assert body.endswith("\n\n")


async def test_assistant_surfaces_evidence_not_found_as_typed_error(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _raising_run_assistant(**kwargs: object) -> AsyncIterator[AnalysisEvent]:
        raise EvidenceNotFoundError("No evidence found for this paper -- run the evidence stage first")
        yield  # pragma: no cover

    monkeypatch.setattr(
        "app.evidence.service.run_assistant", lambda **kwargs: _raising_run_assistant(**kwargs), raising=False
    )
    token = await _register_and_login(client, "assistant-no-evidence@example.com")
    paper_id = await _upload_paper(client, token)

    response = await client.post(
        f"/papers/{paper_id}/assistant",
        headers=_auth_headers(token),
        json=_assistant_body(),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "evidence_not_found"


# ---- rate limiting ----------------------------------------------------


async def test_assistant_is_rate_limited_per_user(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_run_assistant(monkeypatch, _events_done)
    token = await _register_and_login(client, "assistant-ratelimited@example.com")
    paper_id = await _upload_paper(client, token)

    responses = [
        await client.post(
            f"/papers/{paper_id}/assistant",
            headers=_auth_headers(token),
            json=_assistant_body(),
        )
        for _ in range(31)
    ]

    assert responses[-1].status_code == 429


# ---- secret handling ----------------------------------------------------


async def test_assistant_never_logs_submitted_api_key(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret_key = "sk-super-secret-assistant-24680"
    _mock_run_assistant(monkeypatch, _events_done)
    token = await _register_and_login(client, "assistant-no-log-leak@example.com")
    paper_id = await _upload_paper(client, token)

    with caplog.at_level(logging.DEBUG, logger="app.evidence.router"):
        response = await client.post(
            f"/papers/{paper_id}/assistant",
            headers=_auth_headers(token),
            json=_assistant_body(api_key=secret_key),
        )

    assert response.status_code == 200
    for record in caplog.records:
        assert secret_key not in record.getMessage()
