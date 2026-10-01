"""Glossary extraction prompt. See ``claims.py`` for the versioning rule."""

from app.evidence.prompts.shared import wrap_prompt

PROMPT_VERSION = "v1"

_INSTRUCTIONS = """\
You are building a glossary of technical terms used in an academic paper, for
a reader who may not know the field.

For each term worth defining, output:
- "term": the term as written in the paper.
- "definition": a clear, plain-language definition.
- "source_page"/"source_excerpt": if the paper itself defines or explains
  this term, give the page number (matching a "[PAGE n]" marker below) and
  an EXACT, VERBATIM copy of the defining sentence/phrase. If the paper uses
  the term without defining it and you are supplying a general, well-known
  definition instead, set both "source_page" and "source_excerpt" to null
  AND start the definition with "General term (not defined in this paper): "
  -- never present a general definition as if it were quoted from the paper.

Never invent a definition, page number, or excerpt not grounded in either
the paper's own text or general, well-established knowledge of the term.
"""


def build_glossary_prompt(document_text: str) -> str:
    return wrap_prompt(_INSTRUCTIONS, document_text)
