"""Generated-text sanitization for LLM-produced content in this module
(extraction card text, cluster labels/descriptions/overview).

Same length-cap + script/iframe/javascript: stripping logic as
``app.evidence.service._sanitize_generated_text`` -- duplicated rather than
imported because that function is private (leading underscore) to the
Evidence Engine module, which this module must not modify or reach into.
This is the same sanitizer, not a third one.
"""

import re

_MAX_LENGTH = 2000
_UNEXPECTED_CONTENT_PATTERN = re.compile(r"<script|javascript:|<iframe", re.IGNORECASE)


def sanitize_generated_text(value: str, max_length: int = _MAX_LENGTH) -> str:
    text = value[:max_length]
    # Single-pass substitution can reassemble a tag ("<scr<scriptipt>"), so
    # repeat until nothing more is removed.
    while True:
        cleaned = _UNEXPECTED_CONTENT_PATTERN.sub("", text)
        if cleaned == text:
            return cleaned
        text = cleaned
