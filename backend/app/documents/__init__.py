"""Document Pipeline: PDF -> text/figures/layout.

Owns everything up to ``ParsedDocument`` (see schemas.py). Never calls an LLM
and never imports from ``app.providers`` or ``app.evidence`` — see
docs/ARCHITECTURE.md's "Document Pipeline" section and docs/AGENTS.md's
"What's deliberately not an agent".
"""
