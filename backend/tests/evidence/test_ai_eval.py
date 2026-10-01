"""AI-eval suite for the Evidence Engine (docs/TESTING.md's "AI-specific
evaluation" -- required for any PR touching evidence/verifier code, not
optional).

No live provider API key is available in this environment (checked: no
GEMINI/GOOGLE/NVIDIA_NIM key in the environment or a checked-in .env at task
time), so this suite measures what's actually testable without one: the
verifier's own accuracy against a hand-labeled adversarial set built from
the real golden fixture (S2ORC PDF, already parsed by
``app.documents.parser`` -- no mocking of the parser itself). This directly
measures "citation accuracy" and "quote-exactness accuracy" per TESTING.md's
definitions, since both ultimately reduce to "does the verifier correctly
classify a (excerpt, cited page) pair." "Hallucination rate" needs a real
extraction run against a real provider to measure meaningfully (it's a
property of what the *model* invents, not of the verifier) -- see this
phase's handback report for why that couldn't be run here, and what this
suite measures instead as the closest available proxy (the verifier's
``not_found`` detection rate on fabricated excerpts, i.e. its ability to
catch a hallucination *if* the model produces one).
"""

from app.evidence.verifier import classify_excerpt
from app.models.claim import VerificationStatus


def test_citation_accuracy_against_real_fixture_text(s2orc_pdf_path: str, tmp_path: str) -> None:
    """"Citation accuracy" per TESTING.md: does a claim's source_ref
    actually appear on the cited page? Constructs known-good (real
    verbatim quotes) and known-bad (altered quotes) cases from the real
    S2ORC fixture and checks the verifier calls every one correctly.
    """
    from app.documents.parser import parse_pdf

    document = parse_pdf(s2orc_pdf_path, str(tmp_path))
    page_1 = document.pages[0].text
    page_2 = document.pages[1].text

    # Known-good: real substrings copied verbatim from the actual parsed
    # text (not retyped by hand, to rule out transcription error).
    known_good = [
        page_1[page_1.index("We introduce S2ORC") : page_1.index("We introduce S2ORC") + 60],
        page_1[page_1.index("Allen Institute") : page_1.index("Allen Institute") + 40],
    ]
    # Known-bad: a real substring with one substantive token swapped, so
    # it is *not* present verbatim anywhere on the page.
    known_bad = [
        page_1[page_1.index("We introduce S2ORC") : page_1.index("We introduce S2ORC") + 60].replace(
            "introduce", "deprecate"
        ),
    ]

    correct = 0
    total = 0
    for excerpt in known_good:
        total += 1
        if classify_excerpt(excerpt, page_1) == VerificationStatus.verified:
            correct += 1
    for excerpt in known_bad:
        total += 1
        if classify_excerpt(excerpt, page_1) != VerificationStatus.verified:
            correct += 1
    # A known-good excerpt cited against the WRONG page must never verify.
    total += 1
    if classify_excerpt(known_good[0], page_2) != VerificationStatus.verified:
        correct += 1

    accuracy = correct / total
    assert accuracy == 1.0, f"citation accuracy {accuracy:.2%} ({correct}/{total}) below required 100%"


# Labeled (excerpt, page_text, expected_status) adversarial set -- the
# "golden" set this suite's quote-exactness-accuracy number is measured
# against. Extends test_verifier.py's cases with a few more phrasings of
# each category for a less trivially-small sample.
_PAGE = (
    "In this paper we propose a new attention mechanism that improves "
    "translation quality by 10% over the previous baseline on the WMT "
    "2014 English-to-German task, while reducing training time by half."
)

_LABELED_SET: list[tuple[str, str | None, VerificationStatus]] = [
    ("improves translation quality by 10% over the previous baseline", _PAGE, VerificationStatus.verified),
    ("REDUCING TRAINING TIME   by half", _PAGE, VerificationStatus.verified),
    (
        "quality translation improves 10% by baseline previous the over",
        _PAGE,
        VerificationStatus.partially_matched,
    ),
    (
        "translation quality by 10% over previous the baseline improves",
        _PAGE,
        VerificationStatus.partially_matched,
    ),
    ("improves translation quality by 10% over the strong previous baseline", _PAGE, VerificationStatus.partially_matched),
    (
        "improves translation quality by using a completely different recurrent architecture based on LSTMs",
        _PAGE,
        VerificationStatus.mismatch,
    ),
    ("improves translation quality by 1.0% over the previous baseline", _PAGE, VerificationStatus.mismatch),
    ("translation quality by 99% over the previous baseline on WMT 2014", _PAGE, VerificationStatus.mismatch),
    (
        "the authors release their full codebase and pretrained checkpoints under an MIT license",
        _PAGE,
        VerificationStatus.not_found,
    ),
    ("this paper is about protein folding in cryogenic environments", _PAGE, VerificationStatus.not_found),
    ("improves translation quality by 10% over the previous baseline", None, VerificationStatus.needs_review),
    ("improves translation quality by 10% over the previous baseline", "", VerificationStatus.needs_review),
]


def test_quote_exactness_accuracy_against_labeled_adversarial_set() -> None:
    """"Quote-exactness accuracy" per TESTING.md: does the verifier
    correctly classify verified/partially-matched/mismatch/not-found/
    needs-review against a labeled set including reordered words and
    near-miss numbers."""
    correct = sum(
        1 for excerpt, page_text, expected in _LABELED_SET if classify_excerpt(excerpt, page_text) == expected
    )
    total = len(_LABELED_SET)
    accuracy = correct / total
    assert accuracy == 1.0, f"quote-exactness accuracy {accuracy:.2%} ({correct}/{total}) below required 100%"
