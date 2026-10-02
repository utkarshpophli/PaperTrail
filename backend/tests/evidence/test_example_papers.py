"""Bundled example analyses: exported from one paper, imported onto a freshly
parsed copy of the same paper, byte-for-byte (claims keep their ids, quotes
and verification status)."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.example_papers import export_analysis, import_analysis
from app.models.claim import Claim, ClaimKind, VerificationStatus
from app.models.paper import Paper
from app.models.source_reference import SourceReference
from tests.evidence.conftest import make_parsed_paper

PAGE = "We trained the base models for a total of 100,000 steps or 12 hours."


async def test_analysis_round_trips_onto_a_freshly_parsed_paper(db_session: AsyncSession) -> None:
    source = await make_parsed_paper(db_session, {7: PAGE})
    source.arxiv_id = "1706.03762v7"
    claim = Claim(
        paper_id=source.id,
        statement="Base models were trained for 12 hours.",
        kind=ClaimKind.method,
        verification_status=VerificationStatus.verified,
    )
    db_session.add(claim)
    await db_session.flush()
    db_session.add(SourceReference(claim_id=claim.id, page=7, excerpt=PAGE, locator="Section 5.2"))
    await db_session.commit()
    claim_id = claim.id

    example = await export_analysis(db_session, source.id)
    await db_session.execute(delete(SourceReference))
    await db_session.execute(delete(Claim))
    await db_session.execute(delete(Paper).where(Paper.id == source.id))
    await db_session.commit()

    target = await make_parsed_paper(db_session, {7: PAGE})
    assert await import_analysis(db_session, example, target.id) is True

    claims = (await db_session.scalars(select(Claim).where(Claim.paper_id == target.id))).all()
    assert [(c.id, c.verification_status) for c in claims] == [(claim_id, VerificationStatus.verified)]
    refs = (await db_session.scalars(select(SourceReference))).all()
    assert [(r.claim_id, r.page, r.excerpt) for r in refs] == [(claim_id, 7, PAGE)]

    # Second run is a no-op, never a duplicate or a crash.
    assert await import_analysis(db_session, example, target.id) is False
