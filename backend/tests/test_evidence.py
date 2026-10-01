"""Contract tests for POST /papers/{id}/analyze, GET /papers/{id}/evidence,
GET /papers/{id}/report, GET /papers/{id}/technical-appendix,
GET /papers/{id}/story, GET /papers/{id}/learning,
GET /papers/{id}/claims/{claim_id}, POST /papers/{id}/claims/{claim_id}/reverify.

``app.evidence.service.run_analysis``/``get_evidence``/``get_report``/
``get_technical_appendix``/``get_story``/``get_learning``/``reverify_claim``
are mocked here — the one sanctioned internal-boundary mock (TESTING.md) for
a sibling module (rag-engineer's real extraction/verifier/report/story/
learning generation) we don't own, same pattern test_papers.py used for
``parse_pdf`` and test_providers.py used for ``build_provider``.
"""

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.evidence.exceptions import (
    EvidenceNotFoundError,
    LearningNotFoundError,
    ReportNotFoundError,
    StoryNotFoundError,
    TechnicalAppendixNotFoundError,
)
from app.evidence.schemas import (
    ClaimResponse,
    DerivationResponse,
    DerivationStepResponse,
    EvidenceResponse,
    GeneratedSectionResponse,
    LearningResponse,
    QuizQuestionResponse,
)
from app.evidence.service import AnalysisEvent, PaperNotParsedError
from app.models.claim import VerificationStatus

PASSWORD = "correct-horse-battery"


class _FakeParsedDocument:
    class _Page:
        number = 1
        text = "hello world"
        figures: list = []

    pages = [_Page()]


def _fake_parse_pdf(file_path: str, output_dir: str) -> _FakeParsedDocument:
    return _FakeParsedDocument()


@pytest.fixture
def mock_parse_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    # app.documents.parser may not exist yet (document-processing-engineer's
    # module, built in parallel) — same guarded-mock rationale as
    # test_papers.py's fixture of the same name.
    monkeypatch.setattr("app.papers.service.parse_pdf", _fake_parse_pdf)


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


def _fake_claim_response(claim_id: uuid.UUID | None = None, verification_status: str = "verified") -> ClaimResponse:
    return ClaimResponse.model_validate(
        SimpleNamespace(
            id=claim_id or uuid.uuid4(),
            statement="The model achieves 90% accuracy.",
            kind="reported-result",
            verification_status=verification_status,
            source_refs=[
                SimpleNamespace(id=uuid.uuid4(), page=3, excerpt="90% accuracy on the test set", locator=None)
            ],
            created_at=datetime.now(UTC),
        )
    )


def _fake_evidence(paper_id: str, claim: ClaimResponse | None = None) -> EvidenceResponse:
    claims = [claim] if claim else []
    return EvidenceResponse(
        paper_id=uuid.UUID(paper_id),
        thesis="A thesis.",
        plain_summary="A summary.",
        research_question="A question?",
        methods=[],
        findings=[],
        limitations=[],
        claims=claims,
        metrics=[],
        glossary=[],
    )


def _stages_body(*stage_names: str) -> dict[str, object]:
    """``{stages: {...}}`` request body -- one ``StageConfig`` per requested
    stage name, all sharing the same fake provider/key for test simplicity."""
    return {"stages": {name: {"provider_id": "openai", "api_key": "sk-test", "model": "m"} for name in stage_names}}


async def _events_done() -> AsyncIterator[AnalysisEvent]:
    yield AnalysisEvent(type="progress", stage="extraction", message="Extracting claims...")
    yield AnalysisEvent(type="done", data={"claim_count": 1})


async def _events_multi_stage() -> AsyncIterator[AnalysisEvent]:
    yield AnalysisEvent(type="progress", stage="evidence", message="Extracting claims...")
    yield AnalysisEvent(type="done", stage="evidence", data={"claim_count": 1})
    yield AnalysisEvent(type="progress", stage="technical", message="Writing technical appendix...")
    yield AnalysisEvent(type="done", stage="technical", data={"section_count": 2})


def _fake_generated_section(order: int = 0) -> GeneratedSectionResponse:
    return GeneratedSectionResponse(
        id=uuid.uuid4(),
        title="Method Overview",
        content="The authors propose a new architecture.",
        order=order,
        claim_ids=[uuid.uuid4()],
        created_at=datetime.now(UTC),
    )


def _mock_get_sections(sections: list[GeneratedSectionResponse]) -> object:
    async def _get_sections(db: object, paper_id: object) -> list[GeneratedSectionResponse]:
        return sections

    return _get_sections


def _mock_raises(exc: Exception) -> object:
    async def _raise(db: object, paper_id: object) -> None:
        raise exc

    return _raise


def _mock_get_evidence(evidence: EvidenceResponse) -> object:
    """``get_evidence`` is awaited by the router, so the mock must be an
    async function returning the fixture, not a plain lambda."""

    async def _get_evidence(db: object, paper_id: object) -> EvidenceResponse:
        return evidence

    return _get_evidence


def _mock_reverify_claim(claim: ClaimResponse) -> object:
    async def _reverify_claim(db: object, claim_id: object) -> ClaimResponse:
        return claim

    return _reverify_claim


# ---- analyze ----------------------------------------------------------


async def test_analyze_rejects_nonexistent_paper(client: AsyncClient) -> None:
    token = await _register_and_login(client, "analyze-missing@example.com")

    response = await client.post(
        f"/papers/{uuid.uuid4()}/analyze",
        headers=_auth_headers(token),
        json=_stages_body("evidence"),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "paper_not_found"


async def test_analyze_rejects_non_owned_paper(
    client: AsyncClient, mock_parse_pdf: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.evidence.service.run_analysis", lambda **kwargs: _events_done())
    owner_token = await _register_and_login(client, "analyze-owner@example.com")
    intruder_token = await _register_and_login(client, "analyze-intruder@example.com")
    paper_id = await _upload_paper(client, owner_token)

    response = await client.post(
        f"/papers/{paper_id}/analyze",
        headers=_auth_headers(intruder_token),
        json=_stages_body("evidence"),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "paper_not_found"


async def test_analyze_on_unparsed_paper_surfaces_typed_error(
    client: AsyncClient, mock_parse_pdf: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _raising_run_analysis(**kwargs: object) -> AsyncIterator[AnalysisEvent]:
        raise PaperNotParsedError("Paper is not parsed yet")
        yield  # pragma: no cover

    monkeypatch.setattr("app.evidence.service.run_analysis", lambda **kwargs: _raising_run_analysis(**kwargs))
    token = await _register_and_login(client, "analyze-unparsed@example.com")
    paper_id = await _upload_paper(client, token)

    response = await client.post(
        f"/papers/{paper_id}/analyze",
        headers=_auth_headers(token),
        json=_stages_body("evidence"),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "paper_not_parsed"


async def test_analyze_technical_without_evidence_surfaces_evidence_not_found(
    client: AsyncClient, mock_parse_pdf: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contract: ``run_analysis`` raises ``EvidenceNotFoundError`` when
    technical/report is requested without evidence ever having run for this
    paper -- surfaced as a normal typed-error response, same as
    ``PaperNotParsedError``, not swallowed into an SSE error event."""

    async def _raising_run_analysis(**kwargs: object) -> AsyncIterator[AnalysisEvent]:
        raise EvidenceNotFoundError("No evidence found for this paper -- run the evidence stage first")
        yield  # pragma: no cover

    monkeypatch.setattr("app.evidence.service.run_analysis", lambda **kwargs: _raising_run_analysis(**kwargs))
    token = await _register_and_login(client, "analyze-no-evidence@example.com")
    paper_id = await _upload_paper(client, token)

    response = await client.post(
        f"/papers/{paper_id}/analyze",
        headers=_auth_headers(token),
        json=_stages_body("technical"),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "evidence_not_found"


async def test_analyze_streams_sse_formatted_events(
    client: AsyncClient, mock_parse_pdf: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.evidence.service.run_analysis", lambda **kwargs: _events_done())
    token = await _register_and_login(client, "analyze-stream@example.com")
    paper_id = await _upload_paper(client, token)

    response = await client.post(
        f"/papers/{paper_id}/analyze",
        headers=_auth_headers(token),
        json=_stages_body("evidence"),
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "event: progress\n" in body
    assert '"stage":"extraction"' in body
    assert "event: done\n" in body
    assert body.endswith("\n\n")


async def test_analyze_streams_events_tagged_per_requested_stage(
    client: AsyncClient, mock_parse_pdf: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Multi-stage request (evidence + technical) streams events tagged with
    the right ``stage`` field for each."""
    monkeypatch.setattr("app.evidence.service.run_analysis", lambda **kwargs: _events_multi_stage())
    token = await _register_and_login(client, "analyze-multi-stage@example.com")
    paper_id = await _upload_paper(client, token)

    response = await client.post(
        f"/papers/{paper_id}/analyze",
        headers=_auth_headers(token),
        json=_stages_body("evidence", "technical"),
    )

    assert response.status_code == 200, response.text
    body = response.text
    assert '"stage":"evidence"' in body
    assert '"stage":"technical"' in body
    assert body.count("event: done\n") == 2


async def _events_visual_stage() -> AsyncIterator[AnalysisEvent]:
    yield AnalysisEvent(type="progress", stage="evidence", message="Extracting claims...")
    yield AnalysisEvent(type="done", stage="evidence", data={"claim_count": 1})
    yield AnalysisEvent(type="progress", stage="visual", message="Generating story and learning layer...")
    yield AnalysisEvent(type="done", stage="visual", data={"section_count": 3})


async def test_analyze_streams_visual_stage_tagged_events(
    client: AsyncClient, mock_parse_pdf: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requesting ``"visual"`` (alongside evidence, same prerequisite
    requirement as technical/report) streams events tagged ``stage="visual"``
    -- ``AnalyzeRequest.stages`` accepts it as a plain string key with no
    router/schema change needed."""
    monkeypatch.setattr("app.evidence.service.run_analysis", lambda **kwargs: _events_visual_stage())
    token = await _register_and_login(client, "analyze-visual-stage@example.com")
    paper_id = await _upload_paper(client, token)

    response = await client.post(
        f"/papers/{paper_id}/analyze",
        headers=_auth_headers(token),
        json=_stages_body("evidence", "visual"),
    )

    assert response.status_code == 200, response.text
    body = response.text
    assert '"stage":"evidence"' in body
    assert '"stage":"visual"' in body
    assert body.count("event: done\n") == 2


async def test_analyze_visual_without_evidence_surfaces_evidence_not_found(
    client: AsyncClient, mock_parse_pdf: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same prerequisite as technical/report: visual requested without
    evidence ever having run for this paper surfaces ``EvidenceNotFoundError``
    as a typed-error response, not an SSE error event."""

    async def _raising_run_analysis(**kwargs: object) -> AsyncIterator[AnalysisEvent]:
        raise EvidenceNotFoundError("No evidence found for this paper -- run the evidence stage first")
        yield  # pragma: no cover

    monkeypatch.setattr("app.evidence.service.run_analysis", lambda **kwargs: _raising_run_analysis(**kwargs))
    token = await _register_and_login(client, "analyze-visual-no-evidence@example.com")
    paper_id = await _upload_paper(client, token)

    response = await client.post(
        f"/papers/{paper_id}/analyze",
        headers=_auth_headers(token),
        json=_stages_body("visual"),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "evidence_not_found"


async def test_analyze_is_rate_limited_per_user(
    client: AsyncClient, mock_parse_pdf: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.evidence.service.run_analysis", lambda **kwargs: _events_done())
    token = await _register_and_login(client, "analyze-ratelimited@example.com")
    paper_id = await _upload_paper(client, token)

    responses = [
        await client.post(
            f"/papers/{paper_id}/analyze",
            headers=_auth_headers(token),
            json=_stages_body("evidence"),
        )
        for _ in range(6)
    ]

    assert responses[-1].status_code == 429


async def test_analyze_never_logs_submitted_api_key(
    client: AsyncClient, mock_parse_pdf: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret_key = "sk-super-secret-do-not-log-98765"
    monkeypatch.setattr("app.evidence.service.run_analysis", lambda **kwargs: _events_done())
    token = await _register_and_login(client, "analyze-no-log-leak@example.com")
    paper_id = await _upload_paper(client, token)

    with caplog.at_level(logging.DEBUG, logger="app.evidence.router"):
        response = await client.post(
            f"/papers/{paper_id}/analyze",
            headers=_auth_headers(token),
            json={"stages": {"evidence": {"provider_id": "openai", "api_key": secret_key, "model": "m"}}},
        )

    assert response.status_code == 200
    for record in caplog.records:
        assert secret_key not in record.getMessage()


async def test_analyze_service_layer_never_logs_submitted_api_key(
    client: AsyncClient, mock_parse_pdf: None, caplog: pytest.LogCaptureFixture
) -> None:
    """Widens the router-only test above per the security-review LOW finding:
    that test mocks run_analysis entirely, so app.evidence.service's own
    logger.warning/error calls (the paths most likely to embed error detail
    from a provider exception) never actually run. This exercises the REAL
    service code by hitting a real, guaranteed-to-fail path -- an
    unimplemented provider id -- so those log calls genuinely execute."""
    secret_key = "sk-super-secret-service-layer-13579"
    token = await _register_and_login(client, "analyze-service-no-log-leak@example.com")
    paper_id = await _upload_paper(client, token)

    with caplog.at_level(logging.DEBUG, logger="app.evidence.service"):
        response = await client.post(
            f"/papers/{paper_id}/analyze",
            headers=_auth_headers(token),
            # "openai" is catalogued but not implemented yet (Phase 3 scope) --
            # guaranteed to hit build_provider's real NotImplementedError path
            # inside the real run_analysis, exercising its actual log call.
            json={"stages": {"evidence": {"provider_id": "openai", "api_key": secret_key, "model": "m"}}},
        )

    assert response.status_code == 200
    body = response.text
    assert "error" in body  # the real pipeline did hit and report the failure
    for record in caplog.records:
        assert secret_key not in record.getMessage()


# ---- evidence / claims -------------------------------------------------


async def test_get_evidence_requires_ownership(
    client: AsyncClient, mock_parse_pdf: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_token = await _register_and_login(client, "evidence-owner@example.com")
    intruder_token = await _register_and_login(client, "evidence-intruder@example.com")
    paper_id = await _upload_paper(client, owner_token)
    monkeypatch.setattr("app.evidence.service.get_evidence", _mock_get_evidence(_fake_evidence(paper_id)))

    owner_response = await client.get(f"/papers/{paper_id}/evidence", headers=_auth_headers(owner_token))
    assert owner_response.status_code == 200
    assert owner_response.json()["thesis"] == "A thesis."

    intruder_response = await client.get(f"/papers/{paper_id}/evidence", headers=_auth_headers(intruder_token))
    assert intruder_response.status_code == 404
    assert intruder_response.json()["error"]["code"] == "paper_not_found"


# ---- report / technical appendix ---------------------------------------


async def test_get_report_requires_ownership(
    client: AsyncClient, mock_parse_pdf: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_token = await _register_and_login(client, "report-owner@example.com")
    intruder_token = await _register_and_login(client, "report-intruder@example.com")
    paper_id = await _upload_paper(client, owner_token)
    section = _fake_generated_section()
    monkeypatch.setattr("app.evidence.service.get_report", _mock_get_sections([section]))

    owner_response = await client.get(f"/papers/{paper_id}/report", headers=_auth_headers(owner_token))
    assert owner_response.status_code == 200, owner_response.text
    assert owner_response.json()[0]["title"] == "Method Overview"

    intruder_response = await client.get(f"/papers/{paper_id}/report", headers=_auth_headers(intruder_token))
    assert intruder_response.status_code == 404
    assert intruder_response.json()["error"]["code"] == "paper_not_found"


async def test_get_report_404s_with_specific_code_when_not_generated(
    client: AsyncClient, mock_parse_pdf: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Distinguishes "paper exists, report stage never ran" from "paper
    doesn't exist" -- both are 404 but with different error codes."""
    token = await _register_and_login(client, "report-not-generated@example.com")
    paper_id = await _upload_paper(client, token)
    monkeypatch.setattr(
        "app.evidence.service.get_report", _mock_raises(ReportNotFoundError("No report generated yet"))
    )

    response = await client.get(f"/papers/{paper_id}/report", headers=_auth_headers(token))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "report_not_found"


async def test_get_technical_appendix_requires_ownership(
    client: AsyncClient, mock_parse_pdf: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_token = await _register_and_login(client, "technical-owner@example.com")
    intruder_token = await _register_and_login(client, "technical-intruder@example.com")
    paper_id = await _upload_paper(client, owner_token)
    section = _fake_generated_section()
    monkeypatch.setattr("app.evidence.service.get_technical_appendix", _mock_get_sections([section]))

    owner_response = await client.get(f"/papers/{paper_id}/technical-appendix", headers=_auth_headers(owner_token))
    assert owner_response.status_code == 200, owner_response.text
    assert owner_response.json()[0]["title"] == "Method Overview"

    intruder_response = await client.get(
        f"/papers/{paper_id}/technical-appendix", headers=_auth_headers(intruder_token)
    )
    assert intruder_response.status_code == 404
    assert intruder_response.json()["error"]["code"] == "paper_not_found"


async def test_get_technical_appendix_404s_with_specific_code_when_not_generated(
    client: AsyncClient, mock_parse_pdf: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = await _register_and_login(client, "technical-not-generated@example.com")
    paper_id = await _upload_paper(client, token)
    monkeypatch.setattr(
        "app.evidence.service.get_technical_appendix",
        _mock_raises(TechnicalAppendixNotFoundError("No technical appendix generated yet")),
    )

    response = await client.get(f"/papers/{paper_id}/technical-appendix", headers=_auth_headers(token))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "technical_appendix_not_found"


async def test_get_story_requires_ownership(
    client: AsyncClient, mock_parse_pdf: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_token = await _register_and_login(client, "story-owner@example.com")
    intruder_token = await _register_and_login(client, "story-intruder@example.com")
    paper_id = await _upload_paper(client, owner_token)
    section = _fake_generated_section()
    monkeypatch.setattr("app.evidence.service.get_story", _mock_get_sections([section]))

    owner_response = await client.get(f"/papers/{paper_id}/story", headers=_auth_headers(owner_token))
    assert owner_response.status_code == 200, owner_response.text
    assert owner_response.json()[0]["title"] == "Method Overview"

    intruder_response = await client.get(f"/papers/{paper_id}/story", headers=_auth_headers(intruder_token))
    assert intruder_response.status_code == 404
    assert intruder_response.json()["error"]["code"] == "paper_not_found"


async def test_get_story_404s_with_specific_code_when_not_generated(
    client: AsyncClient, mock_parse_pdf: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Distinguishes "paper exists, visual stage never ran" from "paper
    doesn't exist" -- both are 404 but with different error codes."""
    token = await _register_and_login(client, "story-not-generated@example.com")
    paper_id = await _upload_paper(client, token)
    monkeypatch.setattr("app.evidence.service.get_story", _mock_raises(StoryNotFoundError("No story generated yet")))

    response = await client.get(f"/papers/{paper_id}/story", headers=_auth_headers(token))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "story_not_found"


def _fake_quiz_question(order: int = 0) -> QuizQuestionResponse:
    return QuizQuestionResponse(
        id=uuid.uuid4(),
        order=order,
        question="What accuracy did the model achieve?",
        options=["80%", "90%", "95%"],
        correct_answer="90%",
        explanation="The paper reports 90% accuracy on the test set.",
        claim_ids=[uuid.uuid4()],
        created_at=datetime.now(UTC),
    )


def _fake_derivation(order: int = 0) -> DerivationResponse:
    return DerivationResponse(
        id=uuid.uuid4(),
        order=order,
        title="Loss derivation",
        steps=[DerivationStepResponse(explanation="Start from the objective.", formula="L = -log(p)", claim_ids=[uuid.uuid4()])],
        created_at=datetime.now(UTC),
    )


def _fake_learning(paper_id: str) -> LearningResponse:
    return LearningResponse(
        paper_id=uuid.UUID(paper_id),
        primer=[_fake_generated_section()],
        application_guide=[_fake_generated_section(order=1)],
        quiz=[_fake_quiz_question()],
        derivations=[_fake_derivation()],
        interactives=[],
    )


def _mock_get_learning(learning: LearningResponse) -> object:
    async def _get_learning(db: object, paper_id: object) -> LearningResponse:
        return learning

    return _get_learning


async def test_get_learning_requires_ownership(
    client: AsyncClient, mock_parse_pdf: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_token = await _register_and_login(client, "learning-owner@example.com")
    intruder_token = await _register_and_login(client, "learning-intruder@example.com")
    paper_id = await _upload_paper(client, owner_token)
    monkeypatch.setattr("app.evidence.service.get_learning", _mock_get_learning(_fake_learning(paper_id)))

    owner_response = await client.get(f"/papers/{paper_id}/learning", headers=_auth_headers(owner_token))
    assert owner_response.status_code == 200, owner_response.text
    assert owner_response.json()["primer"][0]["title"] == "Method Overview"

    intruder_response = await client.get(f"/papers/{paper_id}/learning", headers=_auth_headers(intruder_token))
    assert intruder_response.status_code == 404
    assert intruder_response.json()["error"]["code"] == "paper_not_found"


async def test_get_learning_404s_with_specific_code_when_not_generated(
    client: AsyncClient, mock_parse_pdf: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = await _register_and_login(client, "learning-not-generated@example.com")
    paper_id = await _upload_paper(client, token)
    monkeypatch.setattr(
        "app.evidence.service.get_learning", _mock_raises(LearningNotFoundError("No learning layer generated yet"))
    )

    response = await client.get(f"/papers/{paper_id}/learning", headers=_auth_headers(token))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "learning_not_found"


async def test_get_claim_requires_ownership_and_404s_for_missing_claim(
    client: AsyncClient, mock_parse_pdf: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_token = await _register_and_login(client, "claim-owner@example.com")
    intruder_token = await _register_and_login(client, "claim-intruder@example.com")
    paper_id = await _upload_paper(client, owner_token)
    claim = _fake_claim_response()
    monkeypatch.setattr("app.evidence.service.get_evidence", _mock_get_evidence(_fake_evidence(paper_id, claim)))

    ok_response = await client.get(f"/papers/{paper_id}/claims/{claim.id}", headers=_auth_headers(owner_token))
    assert ok_response.status_code == 200, ok_response.text
    assert ok_response.json()["verification_status"] == "verified"
    assert ok_response.json()["source_refs"][0]["excerpt"] == "90% accuracy on the test set"

    missing_response = await client.get(
        f"/papers/{paper_id}/claims/{uuid.uuid4()}", headers=_auth_headers(owner_token)
    )
    assert missing_response.status_code == 404
    assert missing_response.json()["error"]["code"] == "claim_not_found"

    intruder_response = await client.get(f"/papers/{paper_id}/claims/{claim.id}", headers=_auth_headers(intruder_token))
    assert intruder_response.status_code == 404
    assert intruder_response.json()["error"]["code"] == "paper_not_found"


async def test_reverify_claim_requires_ownership_and_calls_service(
    client: AsyncClient, mock_parse_pdf: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_token = await _register_and_login(client, "reverify-owner@example.com")
    intruder_token = await _register_and_login(client, "reverify-intruder@example.com")
    paper_id = await _upload_paper(client, owner_token)
    claim = _fake_claim_response()
    reverified_claim = claim.model_copy(update={"verification_status": VerificationStatus.needs_review})

    monkeypatch.setattr("app.evidence.service.get_evidence", _mock_get_evidence(_fake_evidence(paper_id, claim)))
    monkeypatch.setattr("app.evidence.service.reverify_claim", _mock_reverify_claim(reverified_claim))

    intruder_response = await client.post(
        f"/papers/{paper_id}/claims/{claim.id}/reverify", headers=_auth_headers(intruder_token)
    )
    assert intruder_response.status_code == 404

    ok_response = await client.post(
        f"/papers/{paper_id}/claims/{claim.id}/reverify", headers=_auth_headers(owner_token)
    )
    assert ok_response.status_code == 200, ok_response.text
    assert ok_response.json()["verification_status"] == "needs-review"


async def test_reverify_claim_404s_for_claim_not_on_this_paper(
    client: AsyncClient, mock_parse_pdf: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = await _register_and_login(client, "reverify-nomatch@example.com")
    paper_id = await _upload_paper(client, token)
    monkeypatch.setattr("app.evidence.service.get_evidence", _mock_get_evidence(_fake_evidence(paper_id)))

    response = await client.post(
        f"/papers/{paper_id}/claims/{uuid.uuid4()}/reverify", headers=_auth_headers(token)
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "claim_not_found"
