"""Metrics extraction prompt. See ``claims.py`` for the versioning rule."""

from app.evidence.prompts.shared import wrap_prompt

PROMPT_VERSION = "v1"

_INSTRUCTIONS = """\
You are extracting quantitative metrics reported in an academic paper (e.g.
accuracy, F1, latency, parameter count, dataset size). Read the paper text
below and extract every distinct reported metric.

For each metric, output:
- "label": what the metric measures (e.g. "Accuracy on ImageNet").
- "value": the raw reported number/token exactly as it appears (e.g. "87.3",
  "13", "O(n log n)").
- "display_value": a human-readable formatted form (e.g. "87.3%", "13
  layers") -- still must reflect only what is reported, never a rounded or
  invented figure.
- "unit": the unit if any (e.g. "%", "ms", "params"), or null.
- "context": brief context distinguishing this metric (e.g. which dataset,
  baseline, or ablation it belongs to), or null.
- "source_page": the page number (matching a "[PAGE n]" marker below).
- "source_excerpt": an EXACT, VERBATIM copy of the sentence, table cell, or
  phrase reporting this metric. Never paraphrase or reformat the excerpt
  itself -- copy it exactly as written in the source text.

Never invent a metric, number, or excerpt that is not literally present in
the text below.
"""


def build_metrics_prompt(document_text: str) -> str:
    return wrap_prompt(_INSTRUCTIONS, document_text)
