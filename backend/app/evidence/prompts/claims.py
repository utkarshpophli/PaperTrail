"""Claims extraction prompt. Version bump required whenever the output
shape (not just wording) changes -- AI_PROVIDERS.md's prompt-versioning rule.
"""

from app.evidence.prompts.shared import wrap_prompt

PROMPT_VERSION = "v1"

_INSTRUCTIONS = """\
You are extracting claims from an academic paper for a citation-verification
system. Read the paper text below and extract every distinct claim it makes.

For each claim, output:
- "statement": one clear sentence describing the claim. You may paraphrase
  the statement itself for clarity.
- "kind": exactly one of "reported-result" (an experimental/empirical
  finding), "author-interpretation" (the authors' own interpretation or
  opinion about a result), "method" (something the paper's approach does),
  "background" (prior work or context the paper states as given), or
  "limitation" (a limitation or weakness the paper itself acknowledges).
- "source_refs": a list with at least one entry. Each entry has:
  - "page": the page number (matching a "[PAGE n]" marker below) the excerpt
    is copied from.
  - "excerpt": an EXACT, VERBATIM, character-for-character copy of a
    sentence or phrase from that page's text supporting the claim. Never
    paraphrase, translate, summarize, or "clean up" the excerpt -- copy it
    exactly as written in the source text (only joining line-wrapped
    whitespace is acceptable). Keep it in the paper's own language even if
    your statement/summary is in a different language.
  - "locator" (optional): a short human-readable pointer such as a section
    or table/figure name, if useful.

Never invent a page number or excerpt that is not literally present in the
text below. If you cannot find real supporting text for something, do not
include it as a claim.
"""


def build_claims_prompt(document_text: str) -> str:
    return wrap_prompt(_INSTRUCTIONS, document_text)
