"""Business logic for GitHub repo linking + official-implementation
detection -- kept out of the router so route functions stay thin
request/response glue (same split as ``app.collections.service``).

Detection never persists anything (``detect_repositories`` returns
candidates only) -- research-integrity: a "detected" repo is a guess, the
caller must separately confirm one via ``link_repository`` to create a real
row.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.coderesearch.exceptions import RepositoryNotFoundError
from app.coderesearch.handoff import (
    HandoffClaim,
    HandoffCodeLink,
    HandoffInput,
    HandoffMetric,
    HandoffPlanSection,
    HandoffRepository,
    HandoffSourceRef,
)
from app.coderesearch.github_client import RepoMetadata, fetch_repo_metadata, parse_github_url, search_repos_by_query
from app.evidence.exceptions import EvidenceNotFoundError
from app.models.claim import Claim
from app.models.code_link import CodeLink
from app.models.evidence import Evidence
from app.models.generated_section import GeneratedSection, SectionType
from app.models.metric import Metric
from app.models.paper import Paper
from app.models.repository import Repository

# A "detected" repo is unverified by construction (a search-result guess,
# not a user-confirmed link) -- a fixed, deliberately-low confidence keeps
# that honest without building a real title-similarity heuristic this phase
# doesn't need.
# ponytail: flat score rather than a text-similarity match ratio; upgrade to
# a real per-candidate score if detection quality ever needs to be ranked.
DETECTED_CONFIDENCE = 0.4


async def link_repository(db: AsyncSession, paper_id: uuid.UUID, user_id: uuid.UUID, url: str, token: str | None) -> Repository:
    """Validates ``url``, fetches real metadata from GitHub, and persists it
    as ``source="user_linked"`` with ``confidence=None`` -- a user's own
    link is a fact, not a guess."""
    owner, repo = parse_github_url(url)
    metadata = await fetch_repo_metadata(owner, repo, token)
    repository = Repository(
        paper_id=paper_id,
        user_id=user_id,
        url=metadata.url,
        owner=metadata.owner,
        name=metadata.name,
        description=metadata.description,
        stars=metadata.stars,
        source="user_linked",
        confidence=None,
    )
    db.add(repository)
    await db.commit()
    await db.refresh(repository)
    return repository


async def list_repositories(db: AsyncSession, paper_id: uuid.UUID) -> list[Repository]:
    result = await db.scalars(
        select(Repository).where(Repository.paper_id == paper_id).order_by(Repository.created_at.desc())
    )
    return list(result.all())


async def get_paper_repository(db: AsyncSession, paper_id: uuid.UUID) -> Repository | None:
    """The most recently linked/detected repository for this paper, if any --
    used by ``app.evidence.implementation_plan`` to optionally enrich a plan
    with README content. Returns ``None`` rather than raising: not having a
    linked repo yet is a normal state, not an error."""
    return await db.scalar(
        select(Repository).where(Repository.paper_id == paper_id).order_by(Repository.created_at.desc()).limit(1)
    )


async def unlink_repository(db: AsyncSession, paper_id: uuid.UUID, repository_id: uuid.UUID) -> None:
    repository = await db.scalar(
        select(Repository).where(Repository.id == repository_id, Repository.paper_id == paper_id)
    )
    if repository is None:
        raise RepositoryNotFoundError("Repository not found")
    await db.delete(repository)
    await db.commit()


async def detect_repositories(title: str, arxiv_id: str | None, token: str | None) -> list[RepoMetadata]:
    """Searches GitHub for candidate implementations of this paper, using
    its title (and arXiv id, if known) as the query. Returns candidates only
    -- see module docstring."""
    query = f'"{title}" {arxiv_id}' if arxiv_id else f'"{title}"'
    return await search_repos_by_query(query, token)


async def load_handoff_input(db: AsyncSession, paper: Paper) -> HandoffInput:
    """Read-only load of everything the OpenCode handoff export needs.
    ``paper`` must already be ownership-checked (``get_owned_paper``).
    Raises ``EvidenceNotFoundError`` if analysis hasn't run."""
    evidence = await db.scalar(select(Evidence).where(Evidence.paper_id == paper.id))
    if evidence is None:
        raise EvidenceNotFoundError(f"No evidence found for paper {paper.id} -- has analysis been run?")
    claims = (await db.scalars(select(Claim).where(Claim.paper_id == paper.id).order_by(Claim.created_at))).all()
    metrics = (await db.scalars(select(Metric).where(Metric.paper_id == paper.id))).all()
    plan = (
        await db.scalars(
            select(GeneratedSection)
            .where(GeneratedSection.paper_id == paper.id, GeneratedSection.section_type == SectionType.implementation_plan)
            .order_by(GeneratedSection.order)
        )
    ).all()
    repositories = await list_repositories(db, paper.id)
    code_links = (
        await db.scalars(
            select(CodeLink)
            .where(CodeLink.paper_id == paper.id, CodeLink.user_id == paper.user_id)
            .order_by(CodeLink.created_at)
        )
    ).all()
    return HandoffInput(
        paper_id=paper.id,
        title=paper.title,
        authors=tuple(paper.authors),
        arxiv_id=paper.arxiv_id,
        doi=paper.doi,
        thesis=evidence.thesis,
        research_question=evidence.research_question,
        plain_summary=evidence.plain_summary,
        claims=tuple(
            HandoffClaim(
                id=c.id,
                kind=c.kind,
                status=c.verification_status,
                statement=c.statement,
                refs=tuple(HandoffSourceRef(page=r.page, excerpt=r.excerpt) for r in c.source_refs),
            )
            for c in claims
        ),
        metrics=tuple(HandoffMetric(m.label, m.value, m.unit, m.source_page, m.source_excerpt) for m in metrics),
        plan=tuple(HandoffPlanSection(s.title, s.content) for s in plan),
        repositories=tuple(HandoffRepository(r.id, r.url) for r in repositories),
        code_links=tuple(
            HandoffCodeLink(c.claim_id, c.repository_id, c.file_path, c.start_line, c.end_line, c.excerpt, c.verification_status)
            for c in code_links
        ),
    )
