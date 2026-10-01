"""Integrity rules for a generated StorySpec -- everything that needs the
paper's own evidence, so it can't live in the schema (``story_visuals``).

Nothing here trusts the model: claim ids are checked against the paper's real
claims, comparison numbers against its persisted metrics, and a quote visual
against the source-ref excerpts through the deterministic verifier. Every
violation is collected and raised together as one ``StoryIntegrityError`` (so
the retry-with-feedback prompt can name all of them), which rejects the whole
story batch.
"""

import math
import re
from collections.abc import Sequence
from typing import Any, TypeVar

from pydantic import ValidationError

from app.discovery.sanitize import sanitize_generated_text
from app.evidence.exceptions import StoryIntegrityError
from app.evidence.schemas import ClaimForPrompt, MetricForPrompt
from app.evidence.story_visuals import ADVANCED_VISUAL_TYPES, ComparisonVisual, QuoteVisual, StorySpec
from app.evidence.verifier import classify_excerpt
from app.models.claim import ClaimKind, VerificationStatus

_S = TypeVar("_S", bound=StorySpec)
MIN_DISTINCT_VISUAL_TYPES = 3
_SANITIZE_MAX_LENGTH = 8000
_THOUSANDS_COMMA = re.compile(r"(?<=\d),(?=\d{3})")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def strip_nul(text: str) -> str:
    # Postgres text/JSONB reject NUL; left in, it would surface as a raw
    # DBAPI error at commit instead of a handled failure.
    return text.replace(chr(0), "")


def sanitize_json_strings(value: Any) -> Any:  # noqa: ANN401 -- recursive over arbitrary JSON
    """Returns a copy of a JSON-shaped value with every string run through the
    shared generated-text sanitizer, at any depth.

    ``quote.quote`` is the one exemption: it is a verbatim excerpt of the
    paper, checked byte-for-byte by the verifier, and rewriting it would turn
    a true quotation into a false one (same reason claim ``source_refs``
    excerpts are never sanitized). It is rendered as text, never as markup.
    Only NUL bytes (which no database accepts) are removed from it.
    """
    if isinstance(value, str):
        return sanitize_generated_text(strip_nul(value), _SANITIZE_MAX_LENGTH)
    if isinstance(value, list):
        return [sanitize_json_strings(item) for item in value]
    if isinstance(value, dict):
        verbatim_key = "quote" if value.get("type") == "quote" else None
        return {
            key: strip_nul(item) if key == verbatim_key else sanitize_json_strings(item)
            for key, item in value.items()
        }
    return value


def sanitize_story(output: _S) -> _S:
    """Sanitizes every string in meta/sections/visuals and re-validates, so a
    string emptied by stripping (or an edge id changed differently from its
    node id) is rejected rather than persisted."""
    cleaned = sanitize_json_strings(output.model_dump(mode="json"))
    try:
        return type(output).model_validate(cleaned)
    except ValidationError as exc:
        raise StoryIntegrityError(f"Story is invalid after sanitization: {exc}") from exc


def metric_numbers(metrics: Sequence[MetricForPrompt]) -> list[float]:
    """Every number appearing in a persisted metric's ``value``."""
    numbers: list[float] = []
    for metric in metrics:
        numbers.extend(float(match) for match in _NUMBER.findall(_THOUSANDS_COMMA.sub("", metric.value)))
    return numbers


def check_story_integrity(
    output: StorySpec, claims: Sequence[ClaimForPrompt], metrics: Sequence[MetricForPrompt]
) -> None:
    """Raises ``StoryIntegrityError`` listing every violated rule."""
    problems: list[str] = []
    claims_by_id = {claim.id: claim for claim in claims}
    known_numbers = metric_numbers(metrics)
    all_excerpts = [excerpt for claim in claims for excerpt in claim.excerpts]

    cited_kinds: set[ClaimKind] = set()
    for section in output.sections:
        unknown = [str(cid) for cid in section.claim_ids if cid not in claims_by_id]
        if unknown:
            problems.append(f"section {section.title!r} cites unknown claim_id(s): {', '.join(unknown)}")
        cited_kinds.update(claims_by_id[cid].kind for cid in section.claim_ids if cid in claims_by_id)

        visual = section.visual
        if isinstance(visual, ComparisonVisual):
            for item in visual.items:
                if not any(math.isclose(item.value, known, rel_tol=1e-6, abs_tol=1e-9) for known in known_numbers):
                    problems.append(
                        f"section {section.title!r}: comparison value {item.value} ({item.label!r}) "
                        "is not a value among this paper's metrics"
                    )
        elif isinstance(visual, QuoteVisual):
            if not any(classify_excerpt(visual.quote, excerpt) == VerificationStatus.verified for excerpt in all_excerpts):
                problems.append(
                    f"section {section.title!r}: quote is not a verbatim excerpt of any claim source_ref"
                )

    types_used = {section.visual.type for section in output.sections}
    if len(types_used) < MIN_DISTINCT_VISUAL_TYPES:
        problems.append(
            f"only {len(types_used)} distinct visual type(s) used; at least {MIN_DISTINCT_VISUAL_TYPES} required"
        )
    if not types_used & ADVANCED_VISUAL_TYPES:
        problems.append(f"no advanced visual used; include one of: {', '.join(sorted(ADVANCED_VISUAL_TYPES))}")

    # A kind the paper simply has no claims of can't be demanded -- otherwise
    # such a paper's story could never pass.
    available_kinds = {claim.kind for claim in claims}
    for kind in (ClaimKind.method, ClaimKind.limitation):
        if kind in available_kinds and kind not in cited_kinds:
            problems.append(f"story cites no {kind.value} claim; cite at least one")

    if problems:
        raise StoryIntegrityError("Story failed integrity checks: " + "; ".join(problems))
