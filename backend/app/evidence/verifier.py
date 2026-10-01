"""The quote-exactness verifier (docs/AGENTS.md: deliberately NOT an LLM --
matching text against text doesn't need a model, and a model would
reintroduce the exact hallucination risk it's supposed to catch).

Pure, deterministic string matching. Never calls an LLM, never imports
anything from ``app.providers.*``.

## Classification pipeline (per source ref)

1. No page text available at all (page wasn't parsed, or wasn't cited) ->
   ``needs_review``. Never ``verified`` -- the claim just can't be checked
   yet, which is a different thing from being wrong.
2. Normalized excerpt is a literal substring of the normalized page text ->
   ``verified``.
3. Otherwise, find the best-matching window of the page text (anchored on
   ``difflib``'s longest common substring) and classify by:
   a. Same multiset of words as the excerpt, different order -> exactly the
      "reordered words" case -> ``partially_matched``.
   b. A number appears in the excerpt that is not present anywhere in the
      matched window -> a changed digit is a substantive factual difference,
      never just "a few words off" -- capped at ``mismatch`` (or dropped to
      ``not_found`` if the surrounding text barely matches at all), even if
      the surrounding prose is otherwise near-identical.
   c. Otherwise, bucket by character-level similarity ratio
      (``difflib.SequenceMatcher.ratio``) against fixed thresholds (see
      constants below for the reasoning).

## A claim's overall status

A claim can carry more than one source ref. The overall
``verification_status`` is the *worst* status among its refs (severity
order below) -- a claim isn't "verified" just because one of several cited
excerpts checks out; every citation has to hold up.
"""

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from difflib import SequenceMatcher

from app.models.claim import VerificationStatus

# Empirically-chosen thresholds (no labeled corpus exists yet to tune
# against beyond this phase's own adversarial fixture set -- see the AI-eval
# report in this phase's handback for the numbers these produced against
# that set):
#
# - PARTIAL_MATCH_RATIO = 0.85: a handful of missing/added words in a
#   sentence-length excerpt (10-40 words) typically still shares at least
#   85% of its characters with the true source sentence once whitespace is
#   normalized -- close enough to say "this is clearly the same passage,
#   lightly mangled" rather than a different claim entirely.
# - MISMATCH_RATIO_FLOOR = 0.5: below half the characters in common, the
#   matched window is different enough from the excerpt that "the paper
#   probably doesn't say the specific thing this excerpt claims" is a safer
#   read than "close paraphrase" -- push it to ``not_found`` (likely
#   fabricated) rather than the more charitable ``mismatch``.
PARTIAL_MATCH_RATIO = 0.85
MISMATCH_RATIO_FLOOR = 0.5

# Candidate window lengths, as a fraction of the excerpt's own length, tried
# when searching for the best-matching window (see ``_best_window``). A
# single fixed-size window (e.g. always 1.5x the excerpt) systematically
# under-scores excerpts with a few words *inserted* into the middle of an
# otherwise-real sentence: the true matching span in the source is shorter
# than the excerpt, so a window sized off the excerpt's own length overshoots
# into unrelated trailing text and dilutes the ratio. Trying several lengths
# anchored at the same start and keeping whichever scores highest finds a
# window close to the real matching span's actual length instead.
_WINDOW_LENGTH_FACTORS = (0.6, 0.8, 1.0, 1.2, 1.5, 2.0)

# difflib's longest-match search does one inner-loop step per (page char,
# excerpt char) pair that share the same character, so a repetitive page
# ("aaaa...") against a long excerpt is quadratic -- measured at ~0.7us per
# step, i.e. tens of seconds for a 30KB x 1KB pair -- and it runs on the event
# loop. Above this budget the fuzzy comparison is refused and the excerpt is
# ``needs_review`` (verifier could not reach a conclusion), never a guess.
# Ordinary prose/code pages sit well under it; an exact substring match is
# checked first and is unaffected.
MAX_FUZZY_MATCH_STEPS = 4_000_000

_WHITESPACE_RE = re.compile(r"\s+")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?%?")

_SEVERITY = {
    VerificationStatus.verified: 0,
    VerificationStatus.partially_matched: 1,
    VerificationStatus.needs_review: 2,
    VerificationStatus.mismatch: 3,
    VerificationStatus.not_found: 4,
}


def normalize_text(text: str) -> str:
    """Case/whitespace normalization applied before any comparison -- a
    line-wrapped PDF extraction and a claim's excerpt should compare equal
    even if their internal whitespace/casing differs, per the same content.
    """
    return _WHITESPACE_RE.sub(" ", text).strip().lower()


def _numbers(text: str) -> set[str]:
    return set(_NUMBER_RE.findall(text))


def _fuzzy_match_steps(page_norm: str, excerpt_norm: str) -> int:
    page_counts = Counter(page_norm)
    return sum(page_counts[char] * count for char, count in Counter(excerpt_norm).items())


def _best_window(page_norm: str, excerpt_norm: str) -> str:
    """Approximates a sliding-window best match without an O(n*m) full scan
    over the whole page: anchor once on the single longest common substring
    between the excerpt and the page (cheap, one ``difflib`` call), then try
    a handful of window lengths from that same anchor and keep whichever
    scores highest against the excerpt (see ``_WINDOW_LENGTH_FACTORS``).
    """
    if not page_norm:
        return ""
    match = SequenceMatcher(None, page_norm, excerpt_norm, autojunk=False).find_longest_match(
        0, len(page_norm), 0, len(excerpt_norm)
    )
    anchor = match.a - match.b if match.size > 0 else 0
    start = max(0, min(anchor, len(page_norm) - 1))
    # Snap the start to a word boundary: the anchor is a character-offset
    # estimate and can land mid-word (the matched substring's aligned start
    # doesn't necessarily fall on a word boundary on both sides when words
    # around it differ in length, e.g. reordered text) -- starting the
    # window mid-word would corrupt every downstream word-level comparison.
    while start > 0 and page_norm[start - 1] != " ":
        start -= 1

    candidates = []
    for factor in _WINDOW_LENGTH_FACTORS:
        window_len = max(int(len(excerpt_norm) * factor), 1)
        end = min(len(page_norm), start + window_len)
        while end < len(page_norm) and page_norm[end] != " ":
            end += 1
        candidates.append(page_norm[start:end].strip())

    return max(candidates, key=lambda window: SequenceMatcher(None, excerpt_norm, window, autojunk=False).ratio())


def _is_word_reordering(excerpt_norm: str, window: str) -> bool:
    """True if some contiguous same-length slice of ``window``'s words is
    the exact same multiset as the excerpt's words, in a different order.
    """
    excerpt_words = excerpt_norm.split()
    window_words = window.split()
    count = len(excerpt_words)
    if count == 0:
        return False
    sorted_excerpt = sorted(excerpt_words)
    for start in range(max(1, len(window_words) - count + 1)):
        candidate = window_words[start : start + count]
        if len(candidate) < count:
            break
        if candidate != excerpt_words and sorted(candidate) == sorted_excerpt:
            return True
    return False


def classify_excerpt(excerpt: str, page_text: str | None) -> VerificationStatus:
    """Classifies a single (excerpt, cited page text) pair. ``page_text`` is
    ``None``/empty when the cited page has no parsed text (unparsed page, or
    a page number that doesn't exist for this paper) -- both cases map to
    ``needs_review``, per ARCHITECTURE.md's "Verifier can't reach a
    conclusion -> claim stays needs-review, never defaults to verified."
    """
    if not page_text or not page_text.strip():
        return VerificationStatus.needs_review

    excerpt_norm = normalize_text(excerpt)
    if not excerpt_norm:
        return VerificationStatus.needs_review

    page_norm = normalize_text(page_text)
    if excerpt_norm in page_norm:
        return VerificationStatus.verified

    if _fuzzy_match_steps(page_norm, excerpt_norm) > MAX_FUZZY_MATCH_STEPS:
        return VerificationStatus.needs_review

    window = _best_window(page_norm, excerpt_norm)

    if _is_word_reordering(excerpt_norm, window):
        return VerificationStatus.partially_matched

    ratio = SequenceMatcher(None, excerpt_norm, window, autojunk=False).ratio()
    numbers_missing = _numbers(excerpt_norm) - _numbers(window)

    if numbers_missing:
        # A number in the excerpt that isn't anywhere in the matched window
        # is a changed figure, not a wording difference -- never let a high
        # character-ratio (e.g. "10%" vs "1.0%" differ by one character)
        # promote this to partially_matched or verified.
        return VerificationStatus.mismatch if ratio >= MISMATCH_RATIO_FLOOR else VerificationStatus.not_found

    if ratio >= PARTIAL_MATCH_RATIO:
        return VerificationStatus.partially_matched
    if ratio >= MISMATCH_RATIO_FLOOR:
        return VerificationStatus.mismatch
    return VerificationStatus.not_found


def verify_claim_status(
    source_refs: Sequence[tuple[int, str]], pages_by_number: Mapping[int, str]
) -> VerificationStatus:
    """Classifies every ``(page, excerpt)`` source ref and returns the worst
    (most concerning) status among them -- a claim is only as good as its
    least-verified citation.
    """
    if not source_refs:
        return VerificationStatus.needs_review

    statuses = [classify_excerpt(excerpt, pages_by_number.get(page)) for page, excerpt in source_refs]
    return max(statuses, key=lambda status: _SEVERITY[status])
