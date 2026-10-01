"""Cheap liveness checks for a specific ``(provider, model)`` pair --
proves a model is actually reachable before committing to a real,
possibly multi-minute generation run.

Split chat/embed because they exercise different provider methods
(``generate`` vs ``embed``); a catalogued-but-dead model (404/410) fails
here in milliseconds instead of after a long pipeline run starts.

No timeout of its own anymore -- a live model that's merely slow (not
dead) was failing this check under its own separate short cap, even
though the same call would have gone on to succeed if actually run
(confirmed live against NVIDIA NIM). Bounding now comes from
``OpenAICompatibleProvider``'s own ``provider_operation_timeout_seconds``
deadline (``app/providers/openai_compatible.py``, docs/NIM_HANG_FIX.md),
which every OpenAI-compatible provider (NIM, OpenAI, OpenRouter, Groq,
Ollama, LM Studio, llama.cpp) already applies to ``generate``/``embed``
directly -- a second, shorter cap here was redundant for those and wrong
whenever the model just needed more than a few seconds. Gemini doesn't
have that per-operation deadline yet (docs/NIM_HANG_FIX.md's own
follow-up item) and so is not bounded during this specific check until
that lands.
"""

from pydantic import BaseModel

from app.providers.base import AIProvider


class _PingResponse(BaseModel):
    """Minimal structured-output schema used only to prove a provider
    connection/credential is valid -- never a real generation."""

    ok: bool = True


_PING_PROMPT = 'Reply with only this exact JSON object: {"ok": true}'


async def ping_chat(provider: AIProvider, model: str) -> None:
    """Raises whatever typed error the provider raises (AuthenticationError,
    ProviderUnavailableError, ...) if the model isn't actually reachable."""
    await provider.generate(_PING_PROMPT, _PingResponse, model=model)


async def ping_embed(provider: AIProvider, model: str) -> None:
    await provider.embed(["ping"], model=model)
