"""RedactingProvider scrubs the request's own credentials from provider errors."""

import pytest
from pydantic import BaseModel

from app.providers.errors import ProviderUnavailableError
from app.providers.redaction import RedactingProvider, redact_secrets, redacting

SECRET = "sk-super-secret-123456"


class _Out(BaseModel):
    value: str = "x"


class _LeakyProvider:
    marker = "delegated"

    async def generate(self, prompt: str, schema: type[BaseModel], **opts: object) -> BaseModel:
        raise ProviderUnavailableError(f"call failed using key {SECRET}")

    async def stream(self, prompt: str, schema: type[BaseModel], **opts: object):
        yield "partial"
        raise ValueError(f"stream failed at https://x/?key={SECRET}")

    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        raise RuntimeError(f"embed failed {SECRET}")

    async def vision(self, image: bytes, prompt: str) -> str:
        return "ok"

    def available_models(self) -> list[str]:
        return ["m"]


def test_redact_secrets_replaces_every_occurrence_and_ignores_short_values() -> None:
    assert redact_secrets(f"a {SECRET} b {SECRET}", (SECRET,)) == "a [redacted] b [redacted]"
    assert redact_secrets("the abc key", ("abc",)) == "the abc key"


async def test_generate_error_keeps_type_and_loses_the_secret() -> None:
    provider = RedactingProvider(_LeakyProvider(), (SECRET,))  # type: ignore[arg-type]
    with pytest.raises(ProviderUnavailableError) as info:
        await provider.generate("p", _Out)
    assert SECRET not in str(info.value)
    assert SECRET not in info.value.message
    assert "[redacted]" in info.value.message


async def test_stream_and_embed_errors_are_scrubbed_too() -> None:
    provider = RedactingProvider(_LeakyProvider(), (SECRET,))  # type: ignore[arg-type]
    seen: list[str] = []
    with pytest.raises(ValueError) as stream_info:
        async for delta in provider.stream("p", _Out):
            seen.append(delta)
    assert seen == ["partial"]
    assert SECRET not in str(stream_info.value)
    with pytest.raises(RuntimeError) as embed_info:
        await provider.embed(["t"], model="m")
    assert SECRET not in str(embed_info.value)


async def test_success_paths_and_other_attributes_delegate() -> None:
    provider = RedactingProvider(_LeakyProvider(), (SECRET,))  # type: ignore[arg-type]
    assert await provider.vision(b"", "p") == "ok"
    assert provider.available_models() == ["m"]
    assert provider.marker == "delegated"


def test_redacting_returns_the_provider_itself_when_there_is_nothing_to_hide() -> None:
    inner = _LeakyProvider()
    assert redacting(inner, None, "") is inner  # type: ignore[arg-type]
    assert isinstance(redacting(inner, SECRET), RedactingProvider)  # type: ignore[arg-type]
