# AI-eval suite

This directory implements the four metrics docs/TESTING.md's "AI-specific
evaluation" section names as first-class: **citation accuracy**,
**quote-exactness accuracy**, **hallucination rate**, and **answer
faithfulness** (Research Assistant). **Recommendation relevance** is
explicitly out of scope (docs/TESTING.md marks it "post-MVP" and it needs
held-out reading-history data this project doesn't have yet).

`backend/evals/` is a sibling of `backend/app/` and `backend/tests/`, not a
subdirectory of `tests/` — these are **offline evals that report a number**,
not pass/fail CI assertions the way pytest is. One of the four
(quote-exactness) has a documented pass/fail threshold because it's the one
that's fully deterministic; the other two provider-dependent ones report a
metric for a human to read, not a gate.

All commands below assume `cd backend` first (they use `python -m`, which
needs `backend/` as the working directory so `app` and `evals` are both
importable — no `sys.path` hacks, no installed package required).

## 1. Quote-exactness accuracy — always runs, no dependencies

```
python -m evals.run_quote_exactness_eval
```

Runs the real `app.evidence.verifier.classify_excerpt` against 24
hand-labeled cases in `evals/fixtures/quote_exactness_cases.py`, covering:
exact match, reordered words (the adversarial case docs/TESTING.md names
explicitly), near-miss numbers (the other named adversarial case — e.g. a
transposed digit must never come back `verified`), paraphrase, partial
match (word substitution / minor insertion / punctuation drift), a
genuinely absent claim, and the "can't be checked" cases (no page text,
blank page text, blank excerpt) that must land on `needs_review`, never
`verified`.

Pure Python, no network, no LLM, no database. **This is the only one of the
four that should run in CI on every PR** touching evidence/verifier code
(docs/TESTING.md's regression-gate requirement) — see the note in
`docs/TESTING.md` this task added.

Exits non-zero if accuracy drops below **90%**. That threshold (not 100%) is
deliberate: several cases sit right at the verifier's own documented
decision boundaries (e.g. "right number, reworded sentence" or a
trailing-clause insertion) — see `verifier.py`'s threshold comments. A case
or two landing one bucket off from the hand-labeled call is expected
classifier noise at a boundary, not a regression. Anything worse than
1-in-10 disagreeing with hand-verified labels means classification behavior
materially changed and needs a human look before merging. On the run done
while building this suite: **24/24 = 100%**.

## 2. Citation accuracy — folded into quote-exactness (see below for why)

docs/TESTING.md defines citation accuracy as "does every claim's
`source_ref` actually appear on the cited page" and quote-exactness
accuracy as "does the verifier correctly classify verified/
partially-matched/mismatch/not-found... including adversarial cases."

Judgment call: these are **the same question asked twice**. "Does the
source_ref appear on the cited page" *is* what `classify_excerpt` decides —
there's no second, different check the codebase performs for
"citation accuracy" that isn't quote-exactness classification. The
distinction docs/TESTING.md seems to be gesturing at (real extracted
claims vs. synthetic adversarial cases) doesn't correspond to a different
code path or a different correctness question, only a different *source*
of the (excerpt, page-text) pairs being checked. A second harness that
re-implements the identical check against a different fixture set would be
redundant scaffolding, not a second metric — the run_hallucination_eval.py
harness (below) already exercises this same verifier against *real,
provider-extracted* claims rather than hand-written ones, which is the
actual "real extraction, not synthetic adversarial cases" angle. No
separate `run_citation_accuracy_eval.py` was built; this note is the
explicit call-out the task asked for instead.

If a real golden fixture set of hand-verified real papers
(`tests/fixtures/`, referenced in docs/TESTING.md's "Test data" section but
not yet built as of this phase) is added later, re-run
`run_quote_exactness_eval.py`-style checks against *its* claims and that
becomes the "citation accuracy on real papers" number docs/TESTING.md
describes — same code, real fixture data instead of synthetic cases.

## 3. Hallucination rate — needs a real provider + API key

```
EVAL_PROVIDER_ID=google EVAL_PROVIDER_API_KEY=your-key python -m evals.run_hallucination_eval
```

Runs the real extraction pipeline
(`app.evidence.extraction.run_extraction`) against 3 short synthetic
"papers" (`evals/fixtures/hallucination_fixtures/papers.py` — fabricated
abstract+body text with known numbers/claims, not real papers, just enough
for the extraction prompts to have something to extract), then checks every
extracted claim/metric's `source_ref`(s) against that **same** fixture text
using the real verifier (`app.evidence.verifier.verify_claim_status`) — no
separate hand-written answer key, no reimplemented matching logic.

`hallucination rate = (extracted items whose status != verified) / (total extracted items)`

**Needs `EVAL_PROVIDER_ID` and `EVAL_PROVIDER_API_KEY` in the environment.**
Never hardcode a key anywhere — set it in your shell for the one command,
same as any other Paper Trail provider credential. For `ollama` also set
`EVAL_PROVIDER_ENDPOINT` (loopback only, same SSRF rule as production). An
optional `EVAL_PROVIDER_MODEL` overrides the provider's default model.

**With no key configured, this prints a clear explanation and exits 0** —
confirmed by running it with no environment variables set. This is not a
skip-silently no-op: the message names exactly which variables are missing
and that the eval needs a real provider call to mean anything. It will not
run meaningfully in CI without a key provisioned for a scheduled job — see
docs/TESTING.md's "Scheduled (not per-PR)" note, which this eval fits
naturally under.

No fixed pass/fail threshold here (unlike quote-exactness): a hallucination
rate depends on which provider/model is configured, and this project has no
production usage baseline yet to set a numeric bar against. It reports the
number; a human reads it.

## 4. Answer faithfulness (Research Assistant) — needs a real provider + API key

```
EVAL_PROVIDER_ID=google EVAL_PROVIDER_API_KEY=your-key python -m evals.run_assistant_faithfulness_eval
```

Runs the real `app.evidence.assistant.run_assistant_query` against 4
hand-written cases (`evals/fixtures/assistant_faithfulness_cases.py` — one
closed, known claim set per case, covering the `understand`, `deep-dive`,
`verify`, and `challenge` actions) with a real provider, and measures what
fraction of the model's *raw* claim-id citations actually resolve to a
claim it was actually given as context.

Note on what this is (and isn't) testing: `run_assistant_query` already
filters unresolvable citations out of the answer it returns, before
anything downstream ever sees them (Phase 4c's own code, `assistant.py`) —
so this eval is **not** hunting for a bug in that filter. It's giving that
already-enforced invariant a standing, run-able *metric*: how often does
the model cite a claim_id that wasn't offered to it in the first place, at
all. That's measured by counting the
`assistant_answer_cited_unknown_claim_id` warning `run_assistant_query`
logs for each dropped citation (captured with a logging handler around the
real call — not a reimplementation of the filtering logic).

`faithfulness rate = valid citations / (valid citations + dropped citations)`

Same environment variables as hallucination rate above
(`EVAL_PROVIDER_ID`/`EVAL_PROVIDER_API_KEY`/`EVAL_PROVIDER_ENDPOINT`/
`EVAL_PROVIDER_MODEL`). **With no key configured, this also prints a clear
explanation and exits 0** — confirmed the same way as #3.

No fixed pass/fail threshold, same reasoning as hallucination rate.

## What's real and what's honestly out of scope

- Quote-exactness's 24 cases are small on purpose (docs/TESTING.md and this
  task's brief both call for a *small, real* set, not a synthetic
  "dataset"). Every case is a hand-written sentence a human actually
  labeled by reading the verifier's documented design, not scraped or
  generated.
- Hallucination rate and answer faithfulness use synthetic fixture
  "papers"/claim sets, not real arXiv papers, because a genuine
  hand-verified corpus of real papers (`tests/fixtures/`) doesn't exist in
  this repo yet. When it does, both scripts' fixture-loading is the only
  part that would need to change — the eval logic itself already runs
  against real production code paths.
- Recommendation relevance is not built here at all — docs/TESTING.md
  itself marks it post-MVP pending held-out reading-history data this
  project has no way to produce yet. Building a fake version of it would
  look rigorous without being real, which is exactly what this task's brief
  says not to do.
