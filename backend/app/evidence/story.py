"""StorySpec derivation (docs/DATA_MODEL.md's ``StorySection``, extended with
a typed visual per section -- see ``app.evidence.story_visuals``).

Same shape as ``app.evidence.report``: build the prompt, call the given
``AIProvider`` for a structured output, validate it against this paper's real
evidence before handing the result back to ``app.evidence.service`` for
persistence. Nothing here persists anything.

Like ``app.evidence.interactive``, the integrity rules (which schema
validation can't express) get their own one-retry-with-feedback loop on top of
the provider's schema-validation retry: a second failure raises rather than
looping or silently accepting the story.
"""


from app.evidence.claim_refs import generate_citing_claims
from app.evidence.exceptions import StoryIntegrityError
from app.evidence.prompts.story import build_story_prompt
from app.evidence.schemas import ClaimForPrompt, MetricForPrompt
from app.evidence.story_integrity import check_story_integrity, sanitize_story
from app.evidence.story_visuals import StorySpecOutput
from app.providers.base import AIProvider


async def generate_story(
    provider: AIProvider,
    *,
    thesis: str,
    plain_summary: str,
    research_question: str,
    claims: list[ClaimForPrompt],
    metrics: list[MetricForPrompt],
    model: str,
) -> StorySpecOutput:
    """Runs the story-generation pass and returns a sanitized, integrity-
    checked ``StorySpecOutput``. Raises
    ``app.providers.errors.StructuredOutputError`` if the model's output fails
    schema validation twice, or ``StoryIntegrityError`` if it still breaks an
    integrity rule after one retry with the violations fed back -- in every
    failure case nothing is returned for the caller to persist.
    """
    prompt = build_story_prompt(
        thesis=thesis,
        plain_summary=plain_summary,
        research_question=research_question,
        claims=claims,
        metrics=metrics,
    )
    opts: dict[str, object] = {"model": model}

    output = await generate_citing_claims(provider, prompt, StorySpecOutput, **opts)
    try:
        return _validated(output, claims, metrics)
    except StoryIntegrityError as first_error:
        retry_prompt = (
            f"{prompt}\n\n"
            f"Your previous response was rejected: {first_error}\n"
            "Return ONLY corrected JSON matching the schema, fixing exactly those problems."
        )

    retry_output = await generate_citing_claims(provider, retry_prompt, StorySpecOutput, **opts)
    return _validated(retry_output, claims, metrics)


def _validated(
    output: StorySpecOutput, claims: list[ClaimForPrompt], metrics: list[MetricForPrompt]
) -> StorySpecOutput:
    # Sanitize first, verify second: the only sanitizer-exempt string is the
    # verbatim quote, so the checks below see exactly what would be persisted.
    cleaned = sanitize_story(output)
    check_story_integrity(cleaned, claims, metrics)
    return cleaned
