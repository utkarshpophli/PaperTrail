"""Unit tests for the quote-exactness verifier (app.evidence.verifier).

Pure string-matching logic -- no DB, no provider, no async needed. Includes
the adversarial cases the RAG-engineer agent spec calls out explicitly:
reordered words and near-miss numbers.
"""

from app.evidence.verifier import classify_excerpt, verify_claim_status
from app.models.claim import VerificationStatus

PAGE_TEXT = (
    "In this paper we propose a new attention mechanism that improves "
    "translation quality by 10% over the previous baseline on the WMT "
    "2014 English-to-German task, while reducing training time by half."
)


def test_exact_substring_match_is_verified() -> None:
    excerpt = "improves translation quality by 10% over the previous baseline"
    assert classify_excerpt(excerpt, PAGE_TEXT) == VerificationStatus.verified


def test_whitespace_and_case_insensitive_match_is_verified() -> None:
    excerpt = "IMPROVES   translation quality\nby 10% over the previous baseline"
    assert classify_excerpt(excerpt, PAGE_TEXT) == VerificationStatus.verified


def test_reordered_words_is_partially_matched() -> None:
    # Same words, shuffled order -- not a substring, but nothing is
    # missing/added/changed either.
    excerpt = "quality translation improves 10% by baseline previous the over"
    assert classify_excerpt(excerpt, PAGE_TEXT) == VerificationStatus.partially_matched


def test_a_few_added_words_is_partially_matched() -> None:
    excerpt = "improves translation quality by 10% over the strong previous baseline"
    assert classify_excerpt(excerpt, PAGE_TEXT) == VerificationStatus.partially_matched


def test_substantially_different_text_is_mismatch() -> None:
    # Shares the sentence's opening (same topic, same location in the page)
    # but the actual content diverges substantially -- a different, invented
    # architectural claim grafted onto real wording, not just a light edit.
    excerpt = "improves translation quality by using a completely different recurrent architecture based on LSTMs"
    assert classify_excerpt(excerpt, PAGE_TEXT) == VerificationStatus.mismatch


def test_fabricated_claim_not_in_text_is_not_found() -> None:
    excerpt = "the authors release their full codebase and pretrained checkpoints under an MIT license"
    assert classify_excerpt(excerpt, PAGE_TEXT) == VerificationStatus.not_found


def test_near_miss_number_is_never_verified_or_partially_matched() -> None:
    # "10%" in the source became "1.0%" in the excerpt -- textually almost
    # identical (one changed character) but a materially different number.
    excerpt = "improves translation quality by 1.0% over the previous baseline"
    status = classify_excerpt(excerpt, PAGE_TEXT)
    assert status in (VerificationStatus.mismatch, VerificationStatus.not_found)


def test_near_miss_number_different_metric_value() -> None:
    excerpt = "translation quality by 99% over the previous baseline on WMT 2014"
    status = classify_excerpt(excerpt, PAGE_TEXT)
    assert status in (VerificationStatus.mismatch, VerificationStatus.not_found)


def test_missing_page_text_is_needs_review_never_verified() -> None:
    assert classify_excerpt("improves translation quality", None) == VerificationStatus.needs_review
    assert classify_excerpt("improves translation quality", "") == VerificationStatus.needs_review
    assert classify_excerpt("improves translation quality", "   ") == VerificationStatus.needs_review


def test_empty_excerpt_is_needs_review() -> None:
    assert classify_excerpt("", PAGE_TEXT) == VerificationStatus.needs_review


def test_normalize_text_collapses_whitespace_and_case() -> None:
    from app.evidence.verifier import normalize_text

    assert normalize_text("Hello   \n World") == "hello world"


# --- claim-level combination (multiple source refs) -------------------------


def test_claim_status_is_worst_of_multiple_refs() -> None:
    refs = [
        (1, "improves translation quality by 10% over the previous baseline"),  # verified
        (1, "the authors release their full codebase and pretrained checkpoints under an MIT license"),  # not_found
    ]
    pages_by_number = {1: PAGE_TEXT}
    assert verify_claim_status(refs, pages_by_number) == VerificationStatus.not_found


def test_claim_status_verified_when_all_refs_verified() -> None:
    refs = [
        (1, "improves translation quality by 10% over the previous baseline"),
        (1, "reducing training time by half"),
    ]
    pages_by_number = {1: PAGE_TEXT}
    assert verify_claim_status(refs, pages_by_number) == VerificationStatus.verified


def test_claim_status_needs_review_when_cited_page_missing() -> None:
    refs = [(5, "improves translation quality by 10% over the previous baseline")]
    assert verify_claim_status(refs, {1: PAGE_TEXT}) == VerificationStatus.needs_review


def test_claim_status_needs_review_for_empty_refs() -> None:
    assert verify_claim_status([], {1: PAGE_TEXT}) == VerificationStatus.needs_review


# --- bounded worst-case cost -------------------------------------------------


def test_repetitive_page_with_long_non_matching_excerpt_is_refused_quickly() -> None:
    """Regression: difflib is quadratic on repetitive text (30KB 'a's vs a 1KB
    excerpt took ~20s on the event loop). Over the step budget the verifier
    refuses to guess -- needs_review, never verified -- and returns instantly.
    """
    import time

    start = time.perf_counter()
    status = classify_excerpt("a" * 999 + "b", "a" * 30_000)
    assert status == VerificationStatus.needs_review
    assert time.perf_counter() - start < 1.0


def test_exact_substring_match_is_unaffected_by_the_fuzzy_budget() -> None:
    assert classify_excerpt("a" * 2000, "b" + "a" * 30_000) == VerificationStatus.verified
