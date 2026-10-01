"""Conservative model-id heuristics for the live model picker.

Provider listing endpoints rarely say what a model is for, so ids are
classified by name. The bias is deliberate: when an id looks like an embedder,
reranker, speech or image model it is kept out of the chat dropdown; an
unfamiliar id is treated as chat (the user can still type any id freeform).
"""

from app.providers.base import ModelKind

_EMBEDDING_TOKENS = ("embed", "retriev", "bge-")
_OTHER_TOKENS = (
    "rerank",
    "moderation",
    "whisper",
    "tts",
    "dall-e",
    "image",
    "audio",
    "transcribe",
    "speech",
    "realtime",
    "guard",
    "safety",
    "parakeet",
    # Agent/tool-use models, not general chat-completion -- confirmed live:
    # Gemini's "Antigravity Agent Preview" 400s on a plain generateContent
    # structured-JSON call, the exact request shape this app's picker uses.
    # These would otherwise sort alphabetically ahead of "gemini-*" and win
    # the picker's auto-select.
    "antigravity",
    "deep-research",
    "computer-use",
)


def classify_model_id(model_id: str) -> ModelKind:
    lowered = model_id.lower()
    if any(token in lowered for token in _EMBEDDING_TOKENS):
        return "embedding"
    if any(token in lowered for token in _OTHER_TOKENS):
        return "other"
    return "chat"
