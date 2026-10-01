"""Paper-claim-to-code linking (docs/ARCHITECTURE.md, "Phase 8 slice 2
decisions"): two bounded generate calls over a linked GitHub repository, with
the resulting code excerpt verified mechanically -- never by a model's own
say-so -- and line numbers computed from the real file text.

Read-only: repository content is fetched as text, shown to the provider inside
a nonce-fenced data block, and rendered by the UI. Nothing here executes,
evaluates, or shells out to anything derived from it.
"""

import re
import uuid
from difflib import SequenceMatcher
from typing import TypeVar, cast

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.coderesearch.code_link_prompts import build_candidate_paths_prompt, build_code_excerpts_prompt
from app.coderesearch.exceptions import (
    ClaimNotLinkableError,
    GithubFileNotTextError,
    GithubFileTooLargeError,
    GithubNotFoundError,
    RepositoryNotFoundError,
)
from app.coderesearch.github_client import DEFAULT_MAX_FILE_BYTES, fetch_file_content, fetch_repo_tree
from app.coderesearch.schemas import CandidatePathsOutput, CodeExcerptsOutput
from app.core.logging import get_logger
from app.discovery.sanitize import sanitize_generated_text
from app.evidence.exceptions import ClaimNotFoundError
from app.evidence.verifier import classify_excerpt, normalize_text
from app.models.claim import Claim, ClaimKind, VerificationStatus
from app.models.code_link import CodeLink
from app.models.repository import Repository
from app.models.user import User
from app.papers.service import get_owned_paper
from app.providers.base import AIProvider

logger = get_logger(__name__)

_T = TypeVar("_T", bound=BaseModel)

MAX_CANDIDATE_FILES = 5
MAX_LINKS_PER_CLAIM = 5
MAX_EXCERPT_CHARS = 4000
# "Verified" only means the excerpt occurs verbatim in the file, so a tiny excerpt
# (a single identifier or character) is trivially verified and says nothing
# about whether the code implements the claim.
MIN_EXCERPT_CHARS = 20
MAX_EXPLANATION_CHARS = 2000
LINKABLE_CLAIM_KINDS = frozenset({ClaimKind.method, ClaimKind.reported_result})

_WHITESPACE_RUN_RE = re.compile(r"\s+")


def _normalize_with_offsets(text: str) -> tuple[str, list[int]]:
    """Mirrors ``verifier.normalize_text`` (whitespace runs -> one space,
    strip, lowercase) while recording, for each normalized character, the
    index of the original character it came from."""
    chars: list[str] = []
    offsets: list[int] = []

    def add(segment: str, base: int) -> None:
        for index, char in enumerate(segment):
            lowered = char.lower()
            chars.extend(lowered)
            offsets.extend([base + index] * len(lowered))

    position = 0
    for match in _WHITESPACE_RUN_RE.finditer(text):
        add(text[position : match.start()], position)
        chars.append(" ")
        offsets.append(match.start())
        position = match.end()
    add(text[position:], position)

    if chars and chars[0] == " ":
        del chars[0], offsets[0]
    if chars and chars[-1] == " ":
        del chars[-1], offsets[-1]
    return "".join(chars), offsets


def compute_line_range(excerpt: str, file_text: str, status: VerificationStatus) -> tuple[int, int]:
    """1-based inclusive (start_line, end_line) of the excerpt's location in
    ``file_text``. ``verified`` means the normalized excerpt is a literal
    substring, so its exact position is used; ``partially-matched`` anchors on
    the longest common run (best effort). Anything else -- and any case where
    the position can't be established -- is ``(1, 1)``: never a
    model-supplied number, and never a made-up range for an unverified link.
    """
    if status not in (VerificationStatus.verified, VerificationStatus.partially_matched):
        return 1, 1
    excerpt_norm = normalize_text(excerpt)
    file_norm, offsets = _normalize_with_offsets(file_text)
    if not excerpt_norm or file_norm != normalize_text(file_text):
        return 1, 1

    start = file_norm.find(excerpt_norm)
    if start < 0:
        match = SequenceMatcher(None, file_norm, excerpt_norm, autojunk=False).find_longest_match(
            0, len(file_norm), 0, len(excerpt_norm)
        )
        if match.size == 0:
            return 1, 1
        start = max(0, match.a - match.b)
    end = min(len(file_norm), start + len(excerpt_norm)) - 1
    if end < start:
        return 1, 1
    start_line = file_text.count("\n", 0, offsets[start]) + 1
    end_line = file_text.count("\n", 0, offsets[end]) + 1
    return start_line, max(start_line, end_line)


async def _generate(provider: AIProvider, prompt: str, schema: type[_T], model: str) -> _T:
    opts: dict[str, object] = {"model": model}
    return cast(_T, await provider.generate(prompt, schema, **opts))


async def _load_scoped(
    db: AsyncSession, user: User, paper_id: uuid.UUID, repository_id: uuid.UUID, claim_id: uuid.UUID
) -> tuple[Repository, Claim]:
    await get_owned_paper(db, paper_id, user.id)
    repository = await db.scalar(
        select(Repository).where(
            Repository.id == repository_id, Repository.paper_id == paper_id, Repository.user_id == user.id
        )
    )
    if repository is None:
        raise RepositoryNotFoundError("Repository not found")
    claim = await db.scalar(select(Claim).where(Claim.id == claim_id, Claim.paper_id == paper_id))
    if claim is None:
        raise ClaimNotFoundError("Claim not found")
    if claim.kind not in LINKABLE_CLAIM_KINDS:
        raise ClaimNotLinkableError(f"Only method and reported-result claims can be linked to code, not {claim.kind.value}")
    return repository, claim


async def _fetch_candidate_files(
    repository: Repository, chosen_paths: list[str], token: str | None
) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in chosen_paths:
        try:
            files[path] = await fetch_file_content(repository.owner, repository.name, path, token, DEFAULT_MAX_FILE_BYTES)
        except (GithubFileTooLargeError, GithubFileNotTextError, GithubNotFoundError):
            # One unreadable candidate must not sink the others; a real
            # outage (GithubUnavailableError) still propagates.
            logger.warning("code_link_file_skipped repository_id=%s path=%.200r", repository.id, path)
    return files


async def link_claim_to_code(
    db: AsyncSession,
    provider: AIProvider,
    user: User,
    paper_id: uuid.UUID,
    repository_id: uuid.UUID,
    claim_id: uuid.UUID,
    token: str | None,
    model: str,
) -> list[CodeLink]:
    """Ownership/kind checks run before any GitHub or provider call. Existing
    links for the same (repository, claim) are replaced in one transaction
    once generation has succeeded -- including by an empty set if nothing
    plausible was found; any earlier failure leaves them untouched.
    """
    repository, claim = await _load_scoped(db, user, paper_id, repository_id, claim_id)
    excerpts = [ref.excerpt for ref in claim.source_refs]

    tree = await fetch_repo_tree(repository.owner, repository.name, token)
    picked = await _generate(
        provider, build_candidate_paths_prompt(claim.statement, excerpts, tree.paths), CandidatePathsOutput, model
    )
    known_paths = set(tree.paths)
    chosen: list[str] = []
    for path in picked.paths:
        if path not in known_paths:
            logger.warning("code_link_path_dropped repository_id=%s path=%.200r", repository.id, path)
        elif path not in chosen:
            chosen.append(path)
    chosen = chosen[:MAX_CANDIDATE_FILES]

    files = await _fetch_candidate_files(repository, chosen, token) if chosen else {}
    links: list[CodeLink] = []
    if files:
        output = await _generate(
            provider, build_code_excerpts_prompt(claim.statement, excerpts, files), CodeExcerptsOutput, model
        )
        seen_excerpts: set[tuple[str, str]] = set()
        for draft in output.links:
            if len(links) >= MAX_LINKS_PER_CLAIM:
                break
            file_text = files.get(draft.file_path)
            if file_text is None:
                logger.warning("code_link_excerpt_dropped repository_id=%s path=%.200r", repository.id, draft.file_path)
                continue
            # NUL can't be stored in a Postgres text column; the fetched file
            # has none, so an excerpt containing one is not verbatim anyway.
            excerpt = draft.excerpt.replace("\x00", "")[:MAX_EXCERPT_CHARS]
            excerpt_key = (draft.file_path, normalize_text(excerpt))
            if len(excerpt_key[1]) < MIN_EXCERPT_CHARS or excerpt_key in seen_excerpts:
                continue
            seen_excerpts.add(excerpt_key)
            status = classify_excerpt(excerpt, file_text)
            start_line, end_line = compute_line_range(excerpt, file_text, status)
            links.append(
                CodeLink(
                    paper_id=paper_id,
                    user_id=user.id,
                    repository_id=repository.id,
                    claim_id=claim.id,
                    file_path=draft.file_path,
                    start_line=start_line,
                    end_line=end_line,
                    excerpt=excerpt,
                    verification_status=status,
                    explanation=sanitize_generated_text(draft.explanation.replace("\x00", ""), MAX_EXPLANATION_CHARS),
                )
            )

    # Serialize concurrent identical requests: without the row lock two
    # in-flight calls each delete "nothing" and both insert, duplicating rows.
    await db.execute(select(Repository.id).where(Repository.id == repository.id).with_for_update())
    await db.execute(
        delete(CodeLink).where(
            CodeLink.repository_id == repository.id, CodeLink.claim_id == claim.id, CodeLink.user_id == user.id
        )
    )
    db.add_all(links)
    await db.flush()
    for link in links:
        await db.refresh(link)
    await db.commit()
    return links


async def list_code_links(
    db: AsyncSession, paper_id: uuid.UUID, user_id: uuid.UUID, claim_id: uuid.UUID | None
) -> list[CodeLink]:
    query = select(CodeLink).where(CodeLink.paper_id == paper_id, CodeLink.user_id == user_id)
    if claim_id is not None:
        query = query.where(CodeLink.claim_id == claim_id)
    return list((await db.scalars(query.order_by(CodeLink.created_at, CodeLink.file_path, CodeLink.start_line))).all())
