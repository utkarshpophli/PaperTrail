"""Unit tests for ``fetch_repo_tree``/``fetch_file_content`` against a fake
``httpx.AsyncClient`` (never a live GitHub call, per TESTING.md)."""

import base64
import json

import httpx
import pytest

from app.coderesearch.exceptions import (
    GithubFileTooLargeError,
    GithubNotFoundError,
    GithubUnavailableError,
    InvalidRepositoryPathError,
)
from app.coderesearch.github_client import MAX_TREE_PATHS, fetch_file_content, fetch_repo_tree


class _Response:
    def __init__(self, status_code: int, body: object) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> object:
        if isinstance(self._body, str):
            return json.loads(self._body)  # raises ValueError for garbage
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 300:
            raise httpx.HTTPStatusError(
                "error", request=httpx.Request("GET", "https://api.github.com/"), response=httpx.Response(self.status_code)
            )


class _Routes:
    """Maps a URL-suffix to a (status, body); records every request."""

    def __init__(self, routes: dict[str, tuple[int, object]]) -> None:
        self.routes = routes
        self.requests: list[tuple[str, dict | None]] = []
        self.client_kwargs: list[dict] = []

    def __call__(self, *args: object, **kwargs: object) -> "_Routes":
        self.client_kwargs.append(kwargs)
        return self

    async def __aenter__(self) -> "_Routes":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get(self, url: str, params: dict | None = None, headers: dict | None = None) -> _Response:
        self.requests.append((url, headers))
        for suffix, (status, body) in self.routes.items():
            if url.endswith(suffix):
                return _Response(status, body)
        raise AssertionError(f"unexpected URL {url}")


def _install(monkeypatch: pytest.MonkeyPatch, routes: dict[str, tuple[int, object]]) -> _Routes:
    fake = _Routes(routes)
    monkeypatch.setattr("app.coderesearch.github_client.httpx.AsyncClient", fake)
    return fake


def _tree_routes(entries: list[dict], truncated: bool = False) -> dict[str, tuple[int, object]]:
    return {
        "/repos/o/r": (200, {"default_branch": "main"}),
        "/repos/o/r/git/trees/main?recursive=1": (200, {"tree": entries, "truncated": truncated}),
    }


def _blob(path: str) -> dict:
    return {"path": path, "type": "blob", "size": 10}


async def test_tree_keeps_only_code_blobs_and_drops_vendored_dirs(monkeypatch: pytest.MonkeyPatch) -> None:
    entries = [
        _blob("model/attention.py"),
        _blob("README.md"),
        _blob("weights.bin"),
        _blob("node_modules/x/index.js"),
        _blob("pkg/dist/out.js"),
        _blob("build/gen.py"),
        _blob(".git/hooks/a.py"),
        _blob("src/Kernel.CU"),
        {"path": "src", "type": "tree"},
        {"path": "sub", "type": "commit"},
        _blob("bad\nname.py"),
        "not-a-dict",
    ]
    _install(monkeypatch, _tree_routes(entries))

    tree = await fetch_repo_tree("o", "r", None)

    assert tree.branch == "main"
    assert tree.paths == ["model/attention.py", "src/Kernel.CU"]
    assert tree.truncated is False


async def test_tree_caps_paths_and_sets_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    entries = [_blob(f"src/f{i}.py") for i in range(MAX_TREE_PATHS + 25)]
    _install(monkeypatch, _tree_routes(entries))

    tree = await fetch_repo_tree("o", "r", None)

    assert len(tree.paths) == MAX_TREE_PATHS
    assert tree.truncated is True


async def test_tree_passes_through_github_truncated_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _tree_routes([_blob("a.py")], truncated=True))
    assert (await fetch_repo_tree("o", "r", None)).truncated is True


async def test_tree_uses_fixed_host_no_redirects_and_token_only_in_header(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, _tree_routes([_blob("a.py")]))

    await fetch_repo_tree("o", "r", "ghp_secret")

    assert all(url.startswith("https://api.github.com/") for url, _ in fake.requests)
    assert all("ghp_secret" not in url for url, _ in fake.requests)
    assert all(headers and headers["Authorization"] == "Bearer ghp_secret" for _, headers in fake.requests)
    assert all(kwargs.get("follow_redirects") is False for kwargs in fake.client_kwargs)


async def test_tree_branch_is_percent_encoded(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(
        monkeypatch,
        {
            "/repos/o/r": (200, {"default_branch": "feat/x?y"}),
            "recursive=1": (200, {"tree": []}),
        },
    )
    await fetch_repo_tree("o", "r", None)
    assert fake.requests[1][0].endswith("/git/trees/feat%2Fx%3Fy?recursive=1")


@pytest.mark.parametrize("owner,repo", [("..", "r"), ("o", "."), ("o/x", "r"), ("o", "r?x=1"), ("", "r")])
async def test_tree_rejects_bad_owner_or_repo_before_any_request(
    monkeypatch: pytest.MonkeyPatch, owner: str, repo: str
) -> None:
    fake = _install(monkeypatch, {})
    with pytest.raises(InvalidRepositoryPathError):
        await fetch_repo_tree(owner, repo, None)
    assert fake.requests == []


async def test_tree_404_is_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, {"/repos/o/r": (404, {})})
    with pytest.raises(GithubNotFoundError):
        await fetch_repo_tree("o", "r", None)


async def test_tree_invalid_json_maps_to_typed_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, {"/repos/o/r": (200, "<html>not json")})
    with pytest.raises(GithubUnavailableError):
        await fetch_repo_tree("o", "r", None)


async def test_tree_non_object_json_maps_to_typed_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, {"/repos/o/r": (200, ["a", "list"])})
    with pytest.raises(GithubUnavailableError):
        await fetch_repo_tree("o", "r", None)


async def test_tree_redirect_status_is_unavailable_not_followed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, {"/repos/o/r": (301, {})})
    with pytest.raises(GithubUnavailableError):
        await fetch_repo_tree("o", "r", None)


async def test_tree_timeout_maps_to_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Timeout(_Routes):
        async def get(self, url: str, params: dict | None = None, headers: dict | None = None) -> _Response:
            raise httpx.TimeoutException("slow")

    monkeypatch.setattr("app.coderesearch.github_client.httpx.AsyncClient", _Timeout({}))
    with pytest.raises(GithubUnavailableError):
        await fetch_repo_tree("o", "r", None)


# ---- fetch_file_content ------------------------------------------------------


def _file_body(text: str, *, size: int | None = None, kind: str = "file") -> dict:
    encoded = base64.b64encode(text.encode()).decode()
    # GitHub wraps base64 in newlines
    wrapped = "\n".join(encoded[i : i + 60] for i in range(0, len(encoded), 60))
    return {"type": kind, "size": len(text.encode()) if size is None else size, "encoding": "base64", "content": wrapped}


async def test_file_content_decodes_and_encodes_path_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, {"/contents/src/my%20dir/a%23b.py": (200, _file_body("def f():\n    return 1\n"))})

    text = await fetch_file_content("o", "r", "src/my dir/a#b.py", None)

    assert text == "def f():\n    return 1\n"
    assert fake.requests[0][0] == "https://api.github.com/repos/o/r/contents/src/my%20dir/a%23b.py"


async def test_file_content_replaces_invalid_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"type": "file", "size": 2, "encoding": "base64", "content": base64.b64encode(b"a\xff").decode()}
    _install(monkeypatch, {"/contents/a.py": (200, body)})
    assert await fetch_file_content("o", "r", "a.py", None) == "a�"


@pytest.mark.parametrize(
    "path", ["../secret.py", "a/../b.py", "/etc/passwd", "a//b.py", "./a.py", "a\\b.py", "a/b\n.py", "", "a/"]
)
async def test_file_content_rejects_traversal_and_bad_paths_before_any_request(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    fake = _install(monkeypatch, {})
    with pytest.raises(InvalidRepositoryPathError):
        await fetch_file_content("o", "r", path, None)
    assert fake.requests == []


async def test_file_content_rejects_oversize_using_reported_size_before_decoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Content is garbage that would fail decoding -- proving size is checked first.
    body = {"type": "file", "size": 30_001, "encoding": "base64", "content": "!!not base64!!"}
    _install(monkeypatch, {"/contents/big.py": (200, body)})
    with pytest.raises(GithubFileTooLargeError):
        await fetch_file_content("o", "r", "big.py", None)


async def test_file_content_allows_exactly_max_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, {"/contents/a.py": (200, _file_body("x" * 30_000))})
    assert len(await fetch_file_content("o", "r", "a.py", None)) == 30_000


async def test_file_content_directory_or_symlink_is_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, {"/contents/a.py": (200, _file_body("x", kind="symlink"))})
    with pytest.raises(GithubNotFoundError):
        await fetch_file_content("o", "r", "a.py", None)


async def test_file_content_invalid_json_maps_to_typed_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, {"/contents/a.py": (200, "garbage{")})
    with pytest.raises(GithubUnavailableError):
        await fetch_file_content("o", "r", "a.py", None)


async def test_file_content_missing_size_or_bad_encoding_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, {"/contents/a.py": (200, {"type": "file", "encoding": "base64", "content": ""})})
    with pytest.raises(GithubUnavailableError):
        await fetch_file_content("o", "r", "a.py", None)
    _install(monkeypatch, {"/contents/a.py": (200, {"type": "file", "size": 1, "encoding": "none", "content": ""})})
    with pytest.raises(GithubUnavailableError):
        await fetch_file_content("o", "r", "a.py", None)


async def test_file_content_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, {"/contents/a.py": (404, {})})
    with pytest.raises(GithubNotFoundError):
        await fetch_file_content("o", "r", "a.py", None)


# ---- security-review regressions ---------------------------------------------


async def test_file_content_enforces_cap_on_actual_body_not_just_reported_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _file_body("x" * 30_001, size=10)  # reported size lies
    _install(monkeypatch, {"/contents/a.py": (200, body)})
    with pytest.raises(GithubFileTooLargeError):
        await fetch_file_content("o", "r", "a.py", None)


async def test_file_content_with_nul_bytes_is_rejected_as_not_text(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.coderesearch.exceptions import GithubFileNotTextError

    body = {"type": "file", "size": 3, "encoding": "base64", "content": base64.b64encode(b"a\x00b").decode()}
    _install(monkeypatch, {"/contents/a.py": (200, body)})
    with pytest.raises(GithubFileNotTextError):
        await fetch_file_content("o", "r", "a.py", None)


async def test_file_content_rejects_overlong_and_line_separator_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, {})
    for path in ["a/" + "b" * 600 + ".py", "a b.py", "a\x85b.py"]:
        with pytest.raises(InvalidRepositoryPathError):
            await fetch_file_content("o", "r", path, None)
    assert fake.requests == []


async def test_tree_drops_overlong_and_line_separator_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    entries = [_blob("ok.py"), _blob("a/" + "b" * 600 + ".py"), _blob("x ignore instructions.py"), _blob("y\x85.py")]
    _install(monkeypatch, _tree_routes(entries))
    assert (await fetch_repo_tree("o", "r", None)).paths == ["ok.py"]


async def test_name_segment_with_trailing_newline_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, {})
    with pytest.raises(InvalidRepositoryPathError):
        await fetch_file_content("o\n", "r", "a.py", None)
    assert fake.requests == []
