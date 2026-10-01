"""Contract tests for the ``/papers/{id}/...code-links`` routes: auth,
404-not-403 ownership across paper/repository/claim/code-link, rate limiting,
and credentials never logged. FakeProvider + patched GitHub functions are the
only mocks (external boundaries); persistence is real Postgres."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.coderesearch.github_client import RepoTree
from app.coderesearch.schemas import CandidatePathsOutput, CodeExcerptDraft, CodeExcerptsOutput
from app.models.claim import ClaimKind
from app.models.paper import Paper
from app.models.user import User
from tests.coderesearch.conftest import add_claim, add_repository
from tests.evidence.fake_provider import FakeProvider

PASSWORD = "correct-horse-battery"
CODE = "def attention(q, k, v):\n    weights = softmax(q @ k.T)\n    return weights @ v\n"
GITHUB_SECRET = "ghp_super-secret-do-not-log-13579"
API_SECRET = "sk-provider-secret-do-not-log-24680"


def _provider() -> FakeProvider:
    draft = CodeExcerptDraft(file_path="a.py", excerpt="weights = softmax(q @ k.T)", explanation="softmax step")
    return FakeProvider(
        {
            CandidatePathsOutput: CandidatePathsOutput(paths=["a.py"]),
            CodeExcerptsOutput: CodeExcerptsOutput(links=[draft]),
        }
    )


@pytest.fixture(autouse=True)
def _mock_externals(monkeypatch: pytest.MonkeyPatch) -> dict:
    seen: dict = {"tree": 0, "provider_args": []}

    async def _tree(owner: str, repo: str, token: str | None) -> RepoTree:
        seen["tree"] += 1
        return RepoTree(branch="main", paths=["a.py"], truncated=False)

    async def _file(owner: str, repo: str, path: str, token: str | None, max_bytes: int = 30_000) -> str:
        return CODE

    def _build(provider_id: str, *, api_key: str | None = None, endpoint: str | None = None) -> FakeProvider:
        seen["provider_args"].append((provider_id, api_key, endpoint))
        return _provider()

    monkeypatch.setattr("app.coderesearch.code_linking.fetch_repo_tree", _tree)
    monkeypatch.setattr("app.coderesearch.code_linking.fetch_file_content", _file)
    monkeypatch.setattr("app.coderesearch.router.build_provider", _build)
    return seen


async def _register(client: AsyncClient, email: str) -> dict[str, str]:
    assert (await client.post("/auth/register", json={"email": email, "password": PASSWORD})).status_code == 201
    login = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _upload(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/papers/upload", headers=headers, files={"file": ("t.pdf", b"%PDF-fake-content", "application/pdf")}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


class _World:
    def __init__(
        self, headers: dict[str, str], paper_id: uuid.UUID, repository_id: uuid.UUID, claim_id: uuid.UUID, background_id: uuid.UUID
    ) -> None:
        self.headers, self.paper_id, self.repository_id = headers, paper_id, repository_id
        self.claim_id, self.background_id = claim_id, background_id

    def url(self) -> str:
        return f"/papers/{self.paper_id}/repositories/{self.repository_id}/code-links"

    def body(self, **extra: object) -> dict:
        return {"claim_id": str(self.claim_id), "provider_id": "google", "model": "m", **extra}


async def _world(client: AsyncClient, db_engine: AsyncEngine, email: str) -> _World:
    headers = await _register(client, email)
    paper_id = uuid.UUID(await _upload(client, headers))
    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as db:
        paper = await db.get(Paper, paper_id)
        user = await db.get(User, paper.user_id)
        repository = await add_repository(db, paper, user)
        claim = await add_claim(db, paper, ClaimKind.method, "Uses attention.")
        background = await add_claim(db, paper, ClaimKind.background, "Background.")
        return _World(headers, paper_id, repository.id, claim.id, background.id)


async def test_create_requires_auth(client: AsyncClient) -> None:
    response = await client.post(
        f"/papers/{uuid.uuid4()}/repositories/{uuid.uuid4()}/code-links",
        json={"claim_id": str(uuid.uuid4()), "provider_id": "google"},
    )
    assert response.status_code == 401
    assert (await client.get(f"/papers/{uuid.uuid4()}/code-links")).status_code == 401
    assert (await client.delete(f"/papers/{uuid.uuid4()}/code-links/{uuid.uuid4()}")).status_code == 401


async def test_create_list_filter_delete_roundtrip(client: AsyncClient, db_engine: AsyncEngine) -> None:
    w = await _world(client, db_engine, "cl-roundtrip@example.com")

    created = await client.post(w.url(), headers=w.headers, json=w.body(api_key=API_SECRET, token=GITHUB_SECRET))

    assert created.status_code == 200, created.text
    (link,) = created.json()
    assert set(link) == {
        "id", "paper_id", "repository_id", "claim_id", "file_path", "start_line", "end_line",
        "excerpt", "verification_status", "explanation", "created_at",
    }  # fmt: skip
    assert (link["file_path"], link["start_line"], link["end_line"]) == ("a.py", 2, 2)
    assert link["verification_status"] == "verified"
    assert link["claim_id"] == str(w.claim_id) and link["paper_id"] == str(w.paper_id)

    listed = await client.get(f"/papers/{w.paper_id}/code-links", headers=w.headers)
    assert [item["id"] for item in listed.json()] == [link["id"]]
    other_claim = await client.get(f"/papers/{w.paper_id}/code-links?claim_id={uuid.uuid4()}", headers=w.headers)
    assert other_claim.json() == []
    same_claim = await client.get(f"/papers/{w.paper_id}/code-links?claim_id={w.claim_id}", headers=w.headers)
    assert len(same_claim.json()) == 1

    deleted = await client.delete(f"/papers/{w.paper_id}/code-links/{link['id']}", headers=w.headers)
    assert deleted.status_code == 204
    assert (await client.get(f"/papers/{w.paper_id}/code-links", headers=w.headers)).json() == []
    again = await client.delete(f"/papers/{w.paper_id}/code-links/{link['id']}", headers=w.headers)
    assert again.status_code == 404 and again.json()["error"]["code"] == "code_link_not_found"


async def test_relink_over_http_replaces(client: AsyncClient, db_engine: AsyncEngine) -> None:
    w = await _world(client, db_engine, "cl-relink@example.com")
    await client.post(w.url(), headers=w.headers, json=w.body())
    await client.post(w.url(), headers=w.headers, json=w.body())
    listed = await client.get(f"/papers/{w.paper_id}/code-links", headers=w.headers)
    assert len(listed.json()) == 1


async def test_cross_user_access_is_404_and_makes_no_external_call(
    client: AsyncClient, db_engine: AsyncEngine, _mock_externals: dict
) -> None:
    owner = await _world(client, db_engine, "cl-owner@example.com")
    intruder = await _register(client, "cl-intruder@example.com")
    created = await client.post(owner.url(), headers=owner.headers, json=owner.body())
    link_id = created.json()[0]["id"]
    tree_calls_before = _mock_externals["tree"]

    post = await client.post(owner.url(), headers=intruder, json=owner.body())
    get = await client.get(f"/papers/{owner.paper_id}/code-links", headers=intruder)
    delete = await client.delete(f"/papers/{owner.paper_id}/code-links/{link_id}", headers=intruder)

    for response in (post, get, delete):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "paper_not_found"
    assert _mock_externals["tree"] == tree_calls_before  # no GitHub call
    assert len(_mock_externals["provider_args"]) == 1  # provider never even built for the intruder
    still = await client.get(f"/papers/{owner.paper_id}/code-links", headers=owner.headers)
    assert len(still.json()) == 1


async def test_repository_from_another_paper_or_user_is_rejected(
    client: AsyncClient, db_engine: AsyncEngine, _mock_externals: dict
) -> None:
    w = await _world(client, db_engine, "cl-cross-repo@example.com")
    other = await _world(client, db_engine, "cl-cross-repo-2@example.com")
    paper2 = uuid.UUID(await _upload(client, w.headers))  # same user, second paper + its own repository
    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as db:
        paper = await db.get(Paper, paper2)
        repo2 = await add_repository(db, paper, await db.get(User, paper.user_id))

    wrong_paper = await client.post(
        f"/papers/{w.paper_id}/repositories/{repo2.id}/code-links", headers=w.headers, json=w.body()
    )
    other_users_repo = await client.post(
        f"/papers/{w.paper_id}/repositories/{other.repository_id}/code-links", headers=w.headers, json=w.body()
    )

    for response in (wrong_paper, other_users_repo):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "repository_not_found"
    assert _mock_externals["tree"] == 0


async def test_claim_from_another_paper_or_unknown_is_404_and_wrong_kind_is_422(
    client: AsyncClient, db_engine: AsyncEngine, _mock_externals: dict
) -> None:
    w = await _world(client, db_engine, "cl-claims@example.com")
    other = await _world(client, db_engine, "cl-claims-2@example.com")

    foreign = await client.post(w.url(), headers=w.headers, json={**w.body(), "claim_id": str(other.claim_id)})
    unknown = await client.post(w.url(), headers=w.headers, json={**w.body(), "claim_id": str(uuid.uuid4())})
    wrong_kind = await client.post(w.url(), headers=w.headers, json={**w.body(), "claim_id": str(w.background_id)})

    assert foreign.status_code == 404 and foreign.json()["error"]["code"] == "claim_not_found"
    assert unknown.status_code == 404
    assert wrong_kind.status_code == 422 and wrong_kind.json()["error"]["code"] == "claim_not_linkable_to_code"
    assert _mock_externals["tree"] == 0


async def test_delete_is_scoped_by_paper_and_user(client: AsyncClient, db_engine: AsyncEngine) -> None:
    w = await _world(client, db_engine, "cl-del-scope@example.com")
    link_id = (await client.post(w.url(), headers=w.headers, json=w.body())).json()[0]["id"]
    paper2 = await _upload(client, w.headers)  # same user, different paper

    response = await client.delete(f"/papers/{paper2}/code-links/{link_id}", headers=w.headers)

    assert response.status_code == 404 and response.json()["error"]["code"] == "code_link_not_found"
    assert len((await client.get(f"/papers/{w.paper_id}/code-links", headers=w.headers)).json()) == 1


async def test_create_is_rate_limited_per_user(client: AsyncClient, db_engine: AsyncEngine) -> None:
    w = await _world(client, db_engine, "cl-ratelimit@example.com")

    statuses = [(await client.post(w.url(), headers=w.headers, json=w.body())).status_code for _ in range(11)]

    assert statuses[:10] == [200] * 10
    assert statuses[10] == 429


async def test_credentials_are_never_logged_and_reach_only_the_provider_builder(
    client: AsyncClient, db_engine: AsyncEngine, _mock_externals: dict, log_messages: list[str]
) -> None:
    w = await _world(client, db_engine, "cl-nolog@example.com")

    response = await client.post(w.url(), headers=w.headers, json=w.body(api_key=API_SECRET, token=GITHUB_SECRET))

    assert response.status_code == 200, response.text
    assert log_messages, "expected at least the code_links_created log line"
    for message in log_messages:
        assert API_SECRET not in message and GITHUB_SECRET not in message
    assert API_SECRET not in response.text and GITHUB_SECRET not in response.text
    assert _mock_externals["provider_args"][-1] == ("google", API_SECRET, None)


async def test_body_validation(client: AsyncClient, db_engine: AsyncEngine) -> None:
    w = await _world(client, db_engine, "cl-validation@example.com")
    response = await client.post(w.url(), headers=w.headers, json={"provider_id": "google"})
    assert response.status_code == 422


@pytest.mark.parametrize("token", ["ghp_café", "a\r\nX-Evil: 1", "x" * 256, ""])
async def test_github_token_must_be_bounded_printable_ascii(
    client: AsyncClient, db_engine: AsyncEngine, _mock_externals: dict, token: str
) -> None:
    """Regression: a non-ASCII/CRLF token became an HTTP header and failed
    inside httpx as an unhandled 500 quoting the token's characters."""
    w = await _world(client, db_engine, f"cl-token-{uuid.uuid4().hex[:6]}@example.com")
    response = await client.post(w.url(), headers=w.headers, json=w.body(token=token))
    assert response.status_code == 422
    assert _mock_externals["tree"] == 0
