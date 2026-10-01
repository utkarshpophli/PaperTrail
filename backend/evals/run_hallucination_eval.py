"""Hallucination-rate eval (docs/TESTING.md's "AI-specific evaluation").

Runs the real extraction pipeline (``app.evidence.extraction.run_extraction``)
against a handful of synthetic fixture "papers"
(``evals/fixtures/hallucination_fixtures/``) using a real, configured AI
provider, then checks every extracted claim/metric's source_ref(s) against
the SAME fixture text with the real verifier
(``app.evidence.verifier.verify_claim_status``) -- no separate hand-written
answer key, no reimplemented matching logic.

hallucination rate = (extracted items whose status != verified) / (total extracted items)

Needs a real provider + API key. Reads them from the environment
(``EVAL_PROVIDER_ID`` / ``EVAL_PROVIDER_API_KEY`` / optionally
``EVAL_PROVIDER_ENDPOINT`` / ``EVAL_PROVIDER_MODEL``) -- never hardcoded.
If none is configured, this prints a clear explanation and exits 0 (a clean,
documented no-op), rather than crashing or silently skipping.

Usage (from ``backend/``):

    EVAL_PROVIDER_ID=google EVAL_PROVIDER_API_KEY=... python -m evals.run_hallucination_eval
"""

import asyncio
import sys

from app.evidence.extraction import run_extraction
from app.evidence.verifier import verify_claim_status
from app.models.claim import VerificationStatus
from app.providers.errors import (
    AuthenticationError,
    ProviderUnavailableError,
    StructuredOutputError,
)
from evals.fixtures.hallucination_fixtures import FIXTURES, HallucinationFixture
from evals.provider_env import (
    EvalProviderConfig,
    NoEvalProviderConfiguredError,
    load_eval_provider,
)


async def _eval_fixture(
    fixture: HallucinationFixture, config: EvalProviderConfig
) -> tuple[int, int]:
    """Returns (unverified_count, total_count) for one fixture."""
    pages_by_number = {page.number: page.text for page in fixture.pages}
    opts: dict[str, object] = {"model": config.model} if config.model else {}
    result = await run_extraction(config.provider, fixture.pages, **opts)

    print(f"\n=== {fixture.name} ===")
    unverified = 0
    total = 0

    for claim in result.claims:
        refs = [(ref.page, ref.excerpt) for ref in claim.source_refs]
        status = verify_claim_status(refs, pages_by_number)
        total += 1
        is_hallucination = status != VerificationStatus.verified
        unverified += int(is_hallucination)
        marker = "HALLUCINATION" if is_hallucination else "ok"
        print(f"  [claim ] {status.value:16s} {marker:14s} {claim.statement[:80]!r}")

    for metric in result.metrics:
        status = verify_claim_status(
            [(metric.source_page, metric.source_excerpt)], pages_by_number
        )
        total += 1
        is_hallucination = status != VerificationStatus.verified
        unverified += int(is_hallucination)
        marker = "HALLUCINATION" if is_hallucination else "ok"
        print(
            f"  [metric] {status.value:16s} {marker:14s} {metric.label}={metric.display_value!r}"
        )

    return unverified, total


async def _run_all(config: EvalProviderConfig) -> int:
    total_unverified = 0
    total_items = 0

    for fixture in FIXTURES:
        unverified, total = await _eval_fixture(fixture, config)
        total_unverified += unverified
        total_items += total

    rate = (total_unverified / total_items) if total_items else 0.0
    print(f"\nHallucination rate: {total_unverified}/{total_items} = {rate:.1%}")
    return 0


def main() -> int:
    try:
        config = load_eval_provider()
    except NoEvalProviderConfiguredError as exc:
        print(str(exc))
        print(
            "This eval needs a real AI provider call and cannot run meaningfully without one. "
            "Set EVAL_PROVIDER_ID (e.g. 'google') and EVAL_PROVIDER_API_KEY (and EVAL_PROVIDER_ENDPOINT "
            "for 'ollama') to run it. Exiting cleanly -- this is expected when no key is configured."
        )
        return 0

    try:
        return asyncio.run(_run_all(config))
    except (
        AuthenticationError,
        ProviderUnavailableError,
        StructuredOutputError,
    ) as exc:
        print(f"Provider call failed: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
