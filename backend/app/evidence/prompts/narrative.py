"""Narrative (thesis/plain_summary/research_question) extraction prompt.
See ``claims.py`` for the versioning rule.

Unlike the other three passes, narrative output carries no per-field
``source_refs`` (docs/DATA_MODEL.md's ``Evidence`` entity has none) -- it is
a synthesized reading of the whole paper, not an individually-cited
statement, so there is nothing here for the quote-exactness verifier to
check. It must still stay strictly grounded in the paper's actual content.
"""

from app.evidence.prompts.shared import wrap_prompt

PROMPT_VERSION = "v1"

_INSTRUCTIONS = """\
You are summarizing an academic paper for a reader deciding whether to read
it in full. Read the paper text below and output:

- "thesis": one or two sentences stating the paper's central claim/contribution.
- "plain_summary": a short (3-5 sentence) plain-language summary of what the
  paper does and finds, avoiding unexplained jargon.
- "research_question": the core question or problem the paper sets out to
  answer, as a single sentence.

Base all three strictly on the paper's actual content below -- never invent
a contribution, finding, or question the paper does not actually make.
"""


def build_narrative_prompt(document_text: str) -> str:
    return wrap_prompt(_INSTRUCTIONS, document_text)
