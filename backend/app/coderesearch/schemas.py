"""Pydantic v2 request/response shapes for the Code Research module
(Phase 8). See docs/DATA_MODEL.md's ``Repository`` entry.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.claim import VerificationStatus


# Printable ASCII only, bounded: the value becomes an HTTP header, and a
# non-ASCII or CR/LF-bearing one would otherwise fail deep inside httpx as an
# unhandled error whose text quotes the offending token characters.
GithubToken = Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[!-~]+$")]


class RepositoryLinkRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    # Never persisted -- used only for this one metadata fetch (SECURITY.md:
    # a token is per-request user input, same as every other credential in
    # this codebase).
    token: GithubToken | None = None


class RepositoryDetectRequest(BaseModel):
    token: GithubToken | None = None


class RepositoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    paper_id: uuid.UUID
    url: str
    owner: str
    name: str
    description: str | None
    stars: int | None
    source: Literal["user_linked", "detected"]
    confidence: float | None
    created_at: datetime


class RepositoryCandidateResponse(BaseModel):
    """An unpersisted candidate returned by the detect route -- distinct
    from ``RepositoryResponse`` (which always carries an ``id``/
    ``created_at``, i.e. is a real persisted row) so a detected-but-
    unconfirmed guess can never be mistaken for a linked repository at the
    schema level (research-integrity: a "detected" repo is a guess, never
    silently promoted to the same status as a user-confirmed link). The
    caller must separately call ``POST /papers/{id}/repositories`` to turn a
    candidate into a real ``Repository`` row.
    """

    url: str
    owner: str
    name: str
    description: str | None
    stars: int | None
    confidence: float


# ---- claim-to-code linking (Phase 8 slice 2) ---------------------------------


class CodeLinkRequest(BaseModel):
    claim_id: uuid.UUID
    provider_id: str
    # Neither is ever persisted or logged: api_key is the AI provider
    # credential, token an optional GitHub PAT (same per-request discipline
    # as RepositoryLinkRequest.token / StageConfig.api_key).
    api_key: str | None = None
    endpoint: str | None = None
    model: str = Field(min_length=1, max_length=200)
    token: GithubToken | None = None


class CodeLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    paper_id: uuid.UUID
    repository_id: uuid.UUID
    claim_id: uuid.UUID
    file_path: str
    start_line: int
    end_line: int
    excerpt: str
    verification_status: VerificationStatus
    explanation: str
    created_at: datetime


class CandidatePathsOutput(BaseModel):
    """Structured output of generate call 1. No ``max_length`` here on
    purpose: an over-long list is truncated in code rather than failing
    structured-output validation."""

    paths: list[str]


class CodeExcerptDraft(BaseModel):
    file_path: str
    excerpt: str = Field(min_length=1)
    explanation: str


class CodeExcerptsOutput(BaseModel):
    links: list[CodeExcerptDraft]


class OpencodeHandoffResponse(BaseModel):
    """Export only -- Paper Trail never runs OpenCode. ``command`` embeds
    nothing paper-derived except the [a-z0-9-.] filename slug."""

    filename: str
    markdown: str
    command: str
