"""Bundled example papers, so a fresh install opens with finished analyses.

Only Paper Trail's own output is shipped (``backend/examples/*.json``): claims,
quotes, reports, stories, quizzes. The papers themselves are not redistributed.
On load, each paper's exact arXiv version is downloaded and parsed like any
other import, and the analysis is attached to it. Claims keep their ids and
their verification status from the original run.

    python -m app.example_papers load               # idempotent
    python -m app.example_papers export <paper_id>  # maintainer use
"""

import asyncio
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_or_create_local_user
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.models.paper import Paper, ParseStatus
from app.papers.arxiv_client import ArxivMetadata
from app.papers.service import create_paper_from_arxiv, run_parsing

logger = get_logger(__name__)

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"

# Insert order follows the foreign keys: everything hangs off papers, except
# source_references, which hangs off claims. Fixed names, never user input.
_PAPER_TABLES = (
    "evidence",
    "claims",
    "metrics",
    "glossary_terms",
    "generated_sections",
    "stories",
    "figures",
    "learning_quiz_questions",
    "learning_derivations",
    "learning_interactives",
)
_ALL_TABLES = (*_PAPER_TABLES, "source_references")


async def _rows(db: AsyncSession, sql: str, paper_id: uuid.UUID) -> list[dict[str, Any]]:
    result = await db.scalar(text(sql), {"pid": paper_id})
    return list(result or [])


async def export_analysis(db: AsyncSession, paper_id: uuid.UUID) -> dict[str, Any]:
    """Every analysis row of one paper, serialized by Postgres itself so each
    column type (enums, jsonb, timestamps) round-trips exactly."""
    paper = await db.get(Paper, paper_id)
    if paper is None or not paper.arxiv_id:
        raise ValueError(f"paper {paper_id} not found or has no arXiv id")
    tables = {
        table: await _rows(db, f"SELECT coalesce(json_agg(t), '[]') FROM {table} t WHERE paper_id = :pid", paper_id)
        for table in _PAPER_TABLES
    }
    tables["source_references"] = await _rows(
        db,
        "SELECT coalesce(json_agg(t), '[]') FROM source_references t "
        "WHERE claim_id IN (SELECT id FROM claims WHERE paper_id = :pid)",
        paper_id,
    )
    return {
        "arxiv_id": paper.arxiv_id,
        "title": paper.title,
        "authors": paper.authors,
        "year": paper.year,
        "tables": tables,
    }


async def import_analysis(db: AsyncSession, example: dict[str, Any], paper_id: uuid.UUID) -> bool:
    """Attaches an exported analysis to ``paper_id``. Returns False, changing
    nothing, when this example was already imported."""
    claims = example["tables"]["claims"]
    if claims and await db.scalar(text("SELECT 1 FROM claims WHERE id = :id"), {"id": uuid.UUID(claims[0]["id"])}):
        return False
    for table in _ALL_TABLES:
        rows = example["tables"][table]
        if table != "source_references":
            rows = [{**row, "paper_id": str(paper_id)} for row in rows]
        if rows:
            await db.execute(
                text(f"INSERT INTO {table} SELECT * FROM json_populate_recordset(NULL::{table}, CAST(:rows AS json))"),
                {"rows": json.dumps(rows)},
            )
    await db.commit()
    return True


async def _already_loaded(db: AsyncSession, example: dict[str, Any]) -> bool:
    claims = example["tables"]["claims"]
    return bool(claims) and bool(
        await db.scalar(text("SELECT 1 FROM claims WHERE id = :id"), {"id": uuid.UUID(claims[0]["id"])})
    )


async def load_examples() -> None:
    """Best effort: a paper that can't be downloaded or parsed is logged and
    skipped, never half-imported (its analysis is attached only after a
    successful parse)."""
    for path in sorted(EXAMPLES_DIR.glob("*.json")):
        example = json.loads(path.read_text(encoding="utf-8"))
        async with AsyncSessionLocal() as db:
            if await _already_loaded(db, example):
                logger.info("example_paper_skipped_already_loaded arxiv_id=%s", example["arxiv_id"])
                continue
            user = await get_or_create_local_user(db)
            try:
                # Metadata ships with the example: only the PDF itself is fetched,
                # so arXiv's strictly rate-limited search API is never needed.
                metadata = ArxivMetadata(
                    arxiv_id=example["arxiv_id"],
                    title=example["title"],
                    authors=example["authors"],
                    year=example["year"],
                    pdf_url=f"https://arxiv.org/pdf/{example['arxiv_id']}",
                )
                paper = await create_paper_from_arxiv(db, user.id, metadata)
            except Exception:
                # ponytail: broad catch is deliberate -- examples are optional,
                # and a network or arXiv failure must not stop the app booting.
                logger.exception("example_paper_download_failed arxiv_id=%s", example["arxiv_id"])
                continue
        await run_parsing(paper.id)
        async with AsyncSessionLocal() as db:
            parsed = await db.get(Paper, paper.id)
            if parsed is None or parsed.parse_status != ParseStatus.parsed:
                logger.warning("example_paper_parse_failed arxiv_id=%s", example["arxiv_id"])
                continue
            await import_analysis(db, example, paper.id)
            logger.info("example_paper_loaded arxiv_id=%s title=%s", example["arxiv_id"], example["title"])


async def _export(paper_ids: list[str]) -> None:
    EXAMPLES_DIR.mkdir(exist_ok=True)
    async with AsyncSessionLocal() as db:
        for paper_id in paper_ids:
            example = await export_analysis(db, uuid.UUID(paper_id))
            name = re.sub(r"[^0-9A-Za-z.]+", "_", example["arxiv_id"])
            (EXAMPLES_DIR / f"{name}.json").write_text(json.dumps(example, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    command, *args = sys.argv[1:] or ["load"]
    asyncio.run(_export(args) if command == "export" else load_examples())
