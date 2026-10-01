"""Answer-faithfulness eval for the Research Assistant
(docs/TESTING.md's "AI-specific evaluation": "does an assistant answer's
cited claims actually support what it says, checked programmatically where
possible").

Runs the real ``app.evidence.assistant.run_assistant_query`` against hand
-written cases (``evals/fixtures/assistant_faithfulness_cases.py``) with a
real, configured AI provider, and measures what fraction of the model's
*raw* claim-id citations actually resolve to a claim it was given as context.

Note: ``run_assistant_query`` already filters unresolvable citations out of
its returned answer before anything downstream ever sees them (Phase 4c) --
that's a code-level invariant, not something this eval is checking for a
bug. What this eval adds is a standing, run-able *metric* for how often the
model cites a claim_id that wasn't actually offered to it in the first
place, by counting the ``assistant_answer_cited_unknown_claim_id`` warning
``run_assistant_query`` logs for each dropped citation -- captured here via
a logging handler, not a reimplementation of the filtering logic.

faithfulness rate = valid citations / (valid citations + dropped citations), across all cases with at least one citation.

Needs a real provider + API key, same environment variables as
``run_hallucination_eval.py``. No key configured -> clean exit, message
printed, exit code 0.

Usage (from ``backend/``):

    EVAL_PROVIDER_ID=google EVAL_PROVIDER_API_KEY=... python -m evals.run_assistant_faithfulness_eval
"""

import asyncio
import logging
import sys

from app.evidence.assistant import run_assistant_query, select_retrieval_context
from app.providers.errors import (
    AuthenticationError,
    ProviderUnavailableError,
    StructuredOutputError,
)
from evals.fixtures.assistant_faithfulness_cases import CASES, AssistantFaithfulnessCase
from evals.provider_env import (
    EvalProviderConfig,
    NoEvalProviderConfiguredError,
    load_eval_provider,
)

_UNKNOWN_CITATION_MARKER = "assistant_answer_cited_unknown_claim_id"


class _CountingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.count = 0

    def emit(self, record: logging.LogRecord) -> None:
        if _UNKNOWN_CITATION_MARKER in record.getMessage():
            self.count += 1


async def _eval_case(
    case: AssistantFaithfulnessCase, config: EvalProviderConfig
) -> tuple[int, int]:
    """Returns (valid_citations, dropped_citations) for one case."""
    context = select_retrieval_context(
        case.action,
        case.question,
        thesis=case.thesis,
        plain_summary=case.plain_summary,
        research_question=case.research_question,
        claims=case.claims,
        metrics=case.metrics,
        glossary=case.glossary,
        learning_excerpts=[],
    )
    known_claim_ids = {claim.id for claim in case.claims}

    handler = _CountingHandler()
    assistant_logger = logging.getLogger("app.evidence.assistant")
    assistant_logger.addHandler(handler)
    try:
        opts: dict[str, object] = {"model": config.model} if config.model else {}
        draft = await run_assistant_query(
            config.provider,
            action=case.action,
            question=case.question,
            context=context,
            known_claim_ids=known_claim_ids,
            **opts,
        )
    finally:
        assistant_logger.removeHandler(handler)

    valid = len(draft.claim_ids)
    dropped = handler.count
    total = valid + dropped
    print(f"\n=== {case.id} (action={case.action}) ===")
    print(f"  answer: {draft.answer[:160]!r}")
    if total == 0:
        print("  no citations returned -- can't score faithfulness for this case")
    else:
        print(
            f"  citations: {valid} valid, {dropped} dropped (unresolvable) -> {valid / total:.1%} faithful"
        )
    return valid, dropped


async def _run_all(config: EvalProviderConfig) -> int:
    total_valid = 0
    total_dropped = 0

    for case in CASES:
        valid, dropped = await _eval_case(case, config)
        total_valid += valid
        total_dropped += dropped

    total = total_valid + total_dropped
    if total == 0:
        print(
            "\nNo case produced any citations -- faithfulness rate is undefined for this run."
        )
        return 0

    rate = total_valid / total
    print(
        f"\nAnswer faithfulness: {total_valid}/{total} citations resolved = {rate:.1%}"
    )
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
