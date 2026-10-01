import pytest

from app.providers.model_kinds import classify_model_id


@pytest.mark.parametrize(
    ("model_id", "kind"),
    [
        ("gpt-4o", "chat"),
        ("claude-sonnet-4-5", "chat"),
        ("meta/llama-3.1-8b-instruct", "chat"),
        ("qwen2.5:7b", "chat"),
        ("some-brand-new-model", "chat"),
        ("text-embedding-3-large", "embedding"),
        ("nomic-embed-text:latest", "embedding"),
        ("nvidia/nemoretriever-embed", "embedding"),
        ("nvidia/nv-rerankqa-mistral-4b-v3", "other"),
        ("whisper-large-v3", "other"),
        ("gpt-image-1", "other"),
        ("tts-1-hd", "other"),
        ("gemini-2.5-flash-image", "other"),
        ("omni-moderation-latest", "other"),
        # Agent/tool-use models, not general chat-completion -- regression
        # for a live bug: alphabetically-first auto-select picked
        # "antigravity-preview-05-2026" over any "gemini-*" model, and it
        # 400s on a plain generateContent structured-JSON call.
        ("antigravity-preview-05-2026", "other"),
        ("deep-research-pro-preview-12-2025", "other"),
        ("gemini-2.5-computer-use-preview-10-2025", "other"),
        ("gemini-2.5-flash", "chat"),
    ],
)
def test_classification(model_id: str, kind: str) -> None:
    assert classify_model_id(model_id) == kind
