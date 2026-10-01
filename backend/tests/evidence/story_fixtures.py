"""Builders for valid StorySpec test data. ``visual_examples`` returns one
minimal valid visual per type (as plain dicts, i.e. what a provider emits),
so a test can override just the field it wants to break."""

import copy
import uuid
from typing import Any

from app.evidence.story_visuals import StorySpecOutput

_EYE = {"eyebrow": "Eyebrow", "caption": "Caption."}
_LD = [{"label": f"L{i}", "detail": f"D{i}"} for i in range(3)]
_TONE = [{"label": f"L{i}", "detail": f"D{i}", "tone": "paper"} for i in range(3)]


def visual_examples(*, quote: str = "a new attention mechanism", metric_value: float = 10.0) -> dict[str, dict[str, Any]]:
    return {
        "metric": {"type": "metric", **_EYE, "items": [{"label": "A", "value": "10%", "note": ""}, {"label": "B", "value": "2x", "note": "n"}]},
        "flow": {"type": "flow", **_EYE, "items": copy.deepcopy(_LD)},
        "comparison": {
            "type": "comparison",
            **_EYE,
            "items": [
                {"label": "Ours", "value": metric_value, "display_value": f"{metric_value:g}", "highlight": True},
                {"label": "Base", "value": metric_value, "display_value": f"{metric_value:g}", "highlight": False},
            ],
        },
        "concept": {"type": "concept", **_EYE, "center": "Core", "items": copy.deepcopy(_LD)},
        "layers": {"type": "layers", **_EYE, "items": copy.deepcopy(_TONE)},
        "quote": {"type": "quote", **_EYE, "quote": quote, "attribution": "The paper"},
        "architecture": {
            "type": "architecture",
            **_EYE,
            "nodes": [
                {"id": "in", "label": "Input", "detail": "d", "group": "input"},
                {"id": "core", "label": "Core", "detail": "d", "group": "core"},
                {"id": "out", "label": "Output", "detail": "d", "group": "output"},
            ],
            "edges": [{"source": "in", "target": "core", "label": ""}, {"source": "core", "target": "out", "label": "x"}],
        },
        "equation": {
            "type": "equation",
            **_EYE,
            "formula": "y = f(x)",
            "terms": [{"symbol": "y", "label": "out", "detail": "d"}, {"symbol": "x", "label": "in", "detail": "d"}],
            "steps": ["first", "second"],
        },
        "timeline": {"type": "timeline", **_EYE, "items": copy.deepcopy(_TONE)},
        "matrix": {
            "type": "matrix",
            **_EYE,
            "columns": ["c1", "c2"],
            "rows": [
                {"label": "r1", "cells": [{"label": "a", "tone": "low"}, {"label": "b", "tone": "high"}]},
                {"label": "r2", "cells": [{"label": "a", "tone": "neutral"}, {"label": "b", "tone": "medium"}]},
            ],
        },
        "infographic": {"type": "infographic", **_EYE, "items": [{"label": f"L{i}", "detail": "d", "badge": ""} for i in range(3)]},
    }


def story_dict(
    *,
    method_id: uuid.UUID,
    limitation_id: uuid.UUID,
    visual_types: tuple[str, ...] = ("metric", "comparison", "quote", "architecture", "timeline"),
    quote: str = "a new attention mechanism",
    metric_value: float = 10.0,
) -> dict[str, Any]:
    examples = visual_examples(quote=quote, metric_value=metric_value)
    sections = []
    for position, visual_type in enumerate(visual_types):
        claim_id = limitation_id if position == len(visual_types) - 1 else method_id
        sections.append(
            {
                "kicker": f"Kicker {position}",
                "title": f"Section {position}",
                "body": "Body text.",
                "claim_ids": [str(claim_id)],
                "visual": examples[visual_type],
            }
        )
    return {
        "meta": {"title": "T", "dek": "Dek.", "reading_time": "5 min read", "closing": {"title": "End", "body": "Closing."}},
        "sections": sections,
    }


def make_story(**kwargs: Any) -> StorySpecOutput:
    return StorySpecOutput.model_validate(story_dict(**kwargs))
