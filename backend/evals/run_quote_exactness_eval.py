"""Quote-exactness accuracy eval (docs/TESTING.md's "AI-specific evaluation").

Pure-logic eval: exercises the real ``app.evidence.verifier.classify_excerpt``
against a hand-labeled fixture set (``evals/fixtures/quote_exactness_cases.py``).
No LLM, no network, no API key -- this must always run, anywhere, including CI.

Usage (from ``backend/``):

    python -m evals.run_quote_exactness_eval

Exits non-zero if accuracy drops below ``ACCURACY_THRESHOLD``.
"""

import sys

from app.evidence.verifier import classify_excerpt
from evals.fixtures.quote_exactness_cases import CASES, QuoteExactnessCase

# 90%: the fixture set intentionally includes cases right at the verifier's
# documented decision boundaries (e.g. "correct number, wrong surrounding
# sentence" / trailing-clause insertions land close to the
# mismatch/partially-matched line by design -- see verifier.py's threshold
# comments). A handful of these landing one bucket off from a human's exact
# call is expected drift, not a regression; anything worse than 1-in-10
# disagreeing with hand-verified labels means the verifier's classification
# behavior has materially changed and needs a human look before merging.
ACCURACY_THRESHOLD = 0.90


def _run_case(case: QuoteExactnessCase) -> bool:
    actual = classify_excerpt(case.claimed_excerpt, case.source_text)
    return actual == case.expected_status


def main() -> int:
    results: list[tuple[QuoteExactnessCase, bool]] = [
        (case, _run_case(case)) for case in CASES
    ]

    print(f"Quote-exactness eval -- {len(results)} cases\n")
    for case, passed in results:
        actual = classify_excerpt(case.claimed_excerpt, case.source_text)
        marker = "PASS" if passed else "FAIL"
        print(f"[{marker}] {case.id} ({case.category})")
        if not passed:
            print(f"       expected={case.expected_status.value} actual={actual.value}")
            print(f"       note: {case.note}")

    correct = sum(1 for _, passed in results if passed)
    total = len(results)
    accuracy = correct / total if total else 0.0

    print(
        f"\nAccuracy: {correct}/{total} = {accuracy:.1%} (threshold: {ACCURACY_THRESHOLD:.0%})"
    )

    if accuracy < ACCURACY_THRESHOLD:
        print("FAILED: accuracy below documented threshold.")
        return 1

    print("OK: accuracy meets threshold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
