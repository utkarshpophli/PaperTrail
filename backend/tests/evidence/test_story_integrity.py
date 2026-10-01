"""Every StorySpec integrity rule, each failing and passing: schema-level
structural rules (edges, matrix, bounds) and the evidence-level rules in
``app.evidence.story_integrity``.

Includes security-review regression tests (2026-09-22) confirming
``check_story_integrity`` really calls the deterministic verifier
(``app.evidence.verifier.classify_excerpt``) rather than trusting the model's
own claim of accuracy, that a comparison visual's value is checked against
this paper's *persisted* metrics (not something the same batch can satisfy by
construction), and that ``sanitize_json_strings``'s ``quote.quote`` exemption
is scoped to exactly that field.
"""

import copy
import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from app.evidence.exceptions import StoryIntegrityError
from app.evidence.schemas import ClaimForPrompt, MetricForPrompt
from app.evidence.story_integrity import check_story_integrity, sanitize_json_strings, sanitize_story
from app.evidence.story_visuals import StorySpecOutput, VisualAdapter
from app.models.claim import ClaimKind
from tests.evidence.story_fixtures import make_story, story_dict, visual_examples

QUOTE_EXCERPT = "improves translation quality by 10% over the previous baseline"

METHOD = ClaimForPrompt(
    id=uuid.uuid4(), kind=ClaimKind.method, statement="m", excerpts=["a new attention mechanism", QUOTE_EXCERPT]
)
LIMITATION = ClaimForPrompt(id=uuid.uuid4(), kind=ClaimKind.limitation, statement="l", excerpts=["needs compute"])
CLAIMS = [METHOD, LIMITATION]
METRICS = [
    MetricForPrompt(label="Gain", value="10", display_value="10%"),
    MetricForPrompt(label="X", value="1,234.5", display_value="1234.5"),
]


def _claims() -> tuple[ClaimForPrompt, ClaimForPrompt]:
    """Standalone pair (distinct uuids per call) for tests that construct
    their own metrics/story rather than sharing the module-level fixtures."""
    method = ClaimForPrompt(
        id=uuid.uuid4(), kind=ClaimKind.method, statement="Uses a new attention mechanism.",
        excerpts=["a new attention mechanism"],
    )
    limitation = ClaimForPrompt(
        id=uuid.uuid4(), kind=ClaimKind.limitation, statement="Needs a lot of compute.",
        excerpts=["needs a lot of compute"],
    )
    return method, limitation


def _story(**kwargs: Any) -> StorySpecOutput:
    return make_story(method_id=METHOD.id, limitation_id=LIMITATION.id, **kwargs)


def _story_with_visual(visual: dict[str, Any], position: int = 1) -> StorySpecOutput:
    data = story_dict(method_id=METHOD.id, limitation_id=LIMITATION.id)
    data["sections"][position]["visual"] = visual
    return StorySpecOutput.model_validate(data)


def test_valid_story_passes() -> None:
    check_story_integrity(_story(), CLAIMS, METRICS)


def test_unknown_claim_id_rejected() -> None:
    data = story_dict(method_id=METHOD.id, limitation_id=LIMITATION.id)
    data["sections"][0]["claim_ids"].append(str(uuid.uuid4()))
    with pytest.raises(StoryIntegrityError, match="unknown claim_id"):
        check_story_integrity(StorySpecOutput.model_validate(data), CLAIMS, METRICS)


@pytest.mark.parametrize("value", [10.0, 1234.5, 10.0000001])
def test_comparison_values_present_in_metrics_pass(value: float) -> None:
    visual = visual_examples(metric_value=value)["comparison"]
    check_story_integrity(_story_with_visual(visual), CLAIMS, METRICS)


@pytest.mark.parametrize("value", [11.0, 10.01, 0.0])
def test_comparison_value_not_in_metrics_rejected(value: float) -> None:
    visual = visual_examples(metric_value=value)["comparison"]
    with pytest.raises(StoryIntegrityError, match="not a value among this paper's metrics"):
        check_story_integrity(_story_with_visual(visual), CLAIMS, METRICS)


def test_comparison_rejected_when_paper_has_no_metrics() -> None:
    with pytest.raises(StoryIntegrityError, match="comparison value"):
        check_story_integrity(_story(), CLAIMS, [])


def test_check_story_integrity_accepts_a_comparison_value_that_matches_a_persisted_metric() -> None:
    method, limitation = _claims()
    metrics = [MetricForPrompt(label="Gain", value="10", display_value="10%")]
    story = make_story(method_id=method.id, limitation_id=limitation.id, metric_value=10.0)

    check_story_integrity(story, [method, limitation], metrics)  # must not raise


def test_check_story_integrity_rejects_a_comparison_value_not_among_persisted_metrics() -> None:
    """A comparison value must match a number among the paper's *persisted*
    metrics -- a model can't satisfy this by simply padding the same batch
    with a fabricated matching number, since metrics are loaded before the
    story call and passed in as ground truth."""
    method, limitation = _claims()
    metrics = [MetricForPrompt(label="Gain", value="10", display_value="10%")]
    story = make_story(method_id=method.id, limitation_id=limitation.id, metric_value=42.0)

    with pytest.raises(StoryIntegrityError, match="is not a value among this paper's metrics"):
        check_story_integrity(story, [method, limitation], metrics)


def test_quote_verbatim_from_any_claim_excerpt_passes() -> None:
    check_story_integrity(_story(quote="quality by 10% over the previous"), CLAIMS, METRICS)


def test_check_story_integrity_accepts_a_genuine_verbatim_quote() -> None:
    method, limitation = _claims()
    metrics = [MetricForPrompt(label="Gain", value="10", display_value="10%")]
    story = make_story(method_id=method.id, limitation_id=limitation.id, quote="a new attention mechanism")

    check_story_integrity(story, [method, limitation], metrics)  # must not raise


@pytest.mark.parametrize(
    "quote",
    [
        "improves translation quality by 11% over the previous baseline",  # near-miss number
        "over the previous baseline improves translation quality by 10%",  # reordered words
        "a completely invented sentence",
    ],
)
def test_quote_not_verbatim_rejected(quote: str) -> None:
    with pytest.raises(StoryIntegrityError, match="not a verbatim excerpt"):
        check_story_integrity(_story(quote=quote), CLAIMS, METRICS)


def test_check_story_integrity_rejects_a_fabricated_quote() -> None:
    """A quote that is not a verbatim excerpt of any claim's source_refs must
    be rejected -- proves the check runs the real verifier, not a stub that
    always passes (or a check that only looks at claim_ids)."""
    method, limitation = _claims()
    metrics = [MetricForPrompt(label="Gain", value="10", display_value="10%")]
    story = make_story(
        method_id=method.id,
        limitation_id=limitation.id,
        quote="This exact sentence was never written anywhere in the source paper.",
    )

    with pytest.raises(StoryIntegrityError, match="not a verbatim excerpt"):
        check_story_integrity(story, [method, limitation], metrics)


def test_fewer_than_three_distinct_visual_types_rejected() -> None:
    with pytest.raises(StoryIntegrityError, match="distinct visual type"):
        check_story_integrity(_story(visual_types=("timeline",) * 5), CLAIMS, METRICS)


def test_no_advanced_visual_rejected() -> None:
    types = ("metric", "flow", "concept", "layers", "quote")
    with pytest.raises(StoryIntegrityError, match="no advanced visual"):
        check_story_integrity(_story(visual_types=types), CLAIMS, METRICS)


def test_advanced_visual_present_passes() -> None:
    types = ("metric", "flow", "concept", "layers", "infographic")
    check_story_integrity(_story(visual_types=types), CLAIMS, METRICS)


@pytest.mark.parametrize("missing", ["method", "limitation"])
def test_story_must_cite_method_and_limitation_claims(missing: str) -> None:
    other = LIMITATION if missing == "method" else METHOD
    # every section cites only the other kind's claim
    story = make_story(method_id=other.id, limitation_id=other.id)
    with pytest.raises(StoryIntegrityError, match=f"no {missing} claim"):
        check_story_integrity(story, CLAIMS, METRICS)


def test_kind_rule_waived_when_paper_has_no_such_claims() -> None:
    story = make_story(method_id=METHOD.id, limitation_id=METHOD.id)
    check_story_integrity(story, [METHOD], METRICS)


def test_all_violations_reported_together() -> None:
    story = _story(visual_types=("comparison",) * 5, metric_value=99.0)
    with pytest.raises(StoryIntegrityError) as excinfo:
        check_story_integrity(story, CLAIMS, METRICS)
    message = str(excinfo.value)
    assert "comparison value" in message and "distinct visual type" in message and "advanced" in message


# --- schema-level structural rules -------------------------------------------


def test_architecture_edge_to_missing_node_rejected() -> None:
    visual = copy.deepcopy(visual_examples()["architecture"])
    visual["edges"][0]["target"] = "ghost"
    with pytest.raises(ValidationError, match="unknown node id"):
        VisualAdapter.validate_python(visual)


def test_architecture_duplicate_node_ids_rejected() -> None:
    visual = copy.deepcopy(visual_examples()["architecture"])
    visual["nodes"][1]["id"] = "in"
    with pytest.raises(ValidationError, match="unique"):
        VisualAdapter.validate_python(visual)


def test_matrix_cell_count_must_match_columns() -> None:
    visual = copy.deepcopy(visual_examples()["matrix"])
    visual["columns"].append("c3")
    with pytest.raises(ValidationError, match="cell"):
        VisualAdapter.validate_python(visual)


@pytest.mark.parametrize(
    ("visual_type", "field", "too_few"),
    [("metric", "items", 1), ("flow", "items", 2), ("equation", "steps", 1), ("architecture", "edges", 1)],
)
def test_item_count_lower_bounds(visual_type: str, field: str, too_few: int) -> None:
    visual = copy.deepcopy(visual_examples()[visual_type])
    visual[field] = visual[field][:too_few]
    with pytest.raises(ValidationError):
        VisualAdapter.validate_python(visual)


def test_extra_fields_and_bad_tone_rejected() -> None:
    visual = copy.deepcopy(visual_examples()["layers"])
    visual["items"][0]["tone"] = "neon"
    with pytest.raises(ValidationError):
        VisualAdapter.validate_python(visual)
    visual = copy.deepcopy(visual_examples()["flow"])
    visual["surprise"] = "x"
    with pytest.raises(ValidationError):
        VisualAdapter.validate_python(visual)


def test_section_count_bounds() -> None:
    data = story_dict(method_id=METHOD.id, limitation_id=LIMITATION.id)
    with pytest.raises(ValidationError):
        StorySpecOutput.model_validate({**data, "sections": data["sections"][:4]})
    with pytest.raises(ValidationError):
        StorySpecOutput.model_validate({**data, "sections": data["sections"] * 2})


def test_visual_string_length_capped() -> None:
    visual = copy.deepcopy(visual_examples()["flow"])
    visual["items"][0]["detail"] = "x" * 401
    with pytest.raises(ValidationError):
        VisualAdapter.validate_python(visual)


# --- sanitization ------------------------------------------------------------


def test_sanitizer_recurses_to_any_depth() -> None:
    nested = {"a": [{"b": {"c": ["ok<script>alert(1)</script>", 3, None]}}], "d": "<iframe src=x>"}
    cleaned = sanitize_json_strings(nested)
    assert cleaned == {"a": [{"b": {"c": ["ok>alert(1)</script>", 3, None]}}], "d": " src=x>"}
    assert "<script" not in str(cleaned).lower() and "<iframe" not in str(cleaned).lower()


def test_sanitize_story_strips_script_deep_in_visual_but_keeps_quote_verbatim() -> None:
    data = story_dict(method_id=METHOD.id, limitation_id=LIMITATION.id)
    data["meta"]["dek"] = "Dek <script>x</script>"
    data["sections"][3]["visual"]["nodes"][0]["detail"] = "deep <script>alert(1)</script>"
    quote = "a new attention mechanism"
    data["sections"][2]["visual"]["quote"] = quote

    cleaned = sanitize_story(StorySpecOutput.model_validate(data))

    assert "<script" not in cleaned.model_dump_json().lower()
    assert cleaned.sections[2].visual.quote == quote  # exempt, so the verbatim check is unaffected
    check_story_integrity(cleaned, CLAIMS, METRICS)


def test_quote_is_exempt_from_sanitizing() -> None:
    # A verbatim source string that happens to contain markup-like text must not be rewritten.
    assert sanitize_json_strings({"type": "quote", "quote": "x <script> y", "caption": "c <script>"}) == {
        "type": "quote",
        "quote": "x <script> y",
        "caption": "c >",
    }


def test_sanitize_json_strings_exempts_only_the_quote_visuals_quote_field() -> None:
    """The verbatim-quote exemption must be scoped to exactly
    ``{"type": "quote"}``'s own ``quote`` key -- every other string,
    including the same section's kicker/title/body and every other visual
    type's fields, still gets script/iframe/javascript: stripped."""
    payload = "<script>alert(1)</script>"
    quote_text = f"A claim that verbatim contains {payload} in the source."
    section = {
        "kicker": payload,
        "title": "T",
        "body": "B",
        "claim_ids": [str(uuid.uuid4())],
        "visual": {
            "type": "quote",
            "eyebrow": payload,
            "caption": payload,
            "quote": quote_text,
            "attribution": payload,
        },
    }

    cleaned = sanitize_json_strings(section)

    # The one exemption: quote.quote survives byte-for-byte (minus NUL).
    assert cleaned["visual"]["quote"] == quote_text
    # Every other string in the same visual, and the section itself, is stripped.
    assert "<script" not in cleaned["kicker"]
    assert "<script" not in cleaned["visual"]["eyebrow"]
    assert "<script" not in cleaned["visual"]["caption"]
    assert "<script" not in cleaned["visual"]["attribution"]


def test_sanitize_json_strings_still_strips_nul_from_an_exempt_quote() -> None:
    section = {
        "kicker": "K",
        "title": "T",
        "body": "B",
        "claim_ids": [],
        "visual": {
            "type": "quote",
            "eyebrow": "E",
            "caption": "C",
            "quote": "a\x00b",
            "attribution": "A",
        },
    }

    cleaned = sanitize_json_strings(section)

    assert cleaned["visual"]["quote"] == "ab"


def test_sanitize_json_strings_does_not_exempt_quote_shaped_keys_on_other_visual_types() -> None:
    """A dict that merely has a key literally named "quote" but isn't the
    quote visual (``type`` != "quote") must not be exempted -- the exemption
    is keyed off the visual's own discriminator, not the field name alone."""
    payload = "<script>alert(1)</script>"
    not_a_quote_visual = {"type": "metric", "quote": payload, "eyebrow": "E", "caption": "C"}

    cleaned = sanitize_json_strings(not_a_quote_visual)

    assert "<script" not in cleaned["quote"]


def test_sanitize_story_rejects_string_emptied_by_stripping() -> None:
    data = story_dict(method_id=METHOD.id, limitation_id=LIMITATION.id)
    data["sections"][0]["kicker"] = "<script"
    with pytest.raises(StoryIntegrityError, match="after sanitization"):
        sanitize_story(StorySpecOutput.model_validate(data))
