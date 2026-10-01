"""Short claim references (C1, C2, ...) for every prompt that cites claims.

Models are bad at copying 36-character random strings. Confirmed live: a
model copied a claim UUID with one extra character, failed schema validation
twice and discarded a whole stage. So the model never sees a UUID: every
``[CLAIM <uuid>]`` marker is rewritten to ``[CLAIM C<n>]`` just before the
call, and while the output is validated each ``C<n>`` is mapped back to the
real UUID. An unknown reference fails validation, which gives the model the
usual one repair retry with the error fed back; it is never persisted.
"""

import re
import uuid
from contextvars import ContextVar
from typing import Annotated, Any, TypeVar, cast

from pydantic import BaseModel, BeforeValidator, WithJsonSchema

from app.providers.base import AIProvider

_T = TypeVar("_T", bound=BaseModel)

_MARKER = re.compile(
    r"\[CLAIM ([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\]"
)
_REF = re.compile(r"^C\d+$")

# Set only for the duration of one claim-citing generate call (see below);
# None everywhere else, so stored rows and API payloads validate as plain UUIDs.
_active_refs: ContextVar[dict[str, uuid.UUID] | None] = ContextVar(
    "claim_refs", default=None
)


def rewrite_claim_markers(prompt: str) -> tuple[str, dict[str, uuid.UUID]]:
    """Numbers claims in order of first appearance; the same claim always
    gets the same reference within one prompt."""
    refs: dict[str, uuid.UUID] = {}
    by_id: dict[uuid.UUID, str] = {}

    def to_ref(match: re.Match[str]) -> str:
        claim_id = uuid.UUID(match.group(1))
        if claim_id not in by_id:
            by_id[claim_id] = f"C{len(by_id) + 1}"
            refs[by_id[claim_id]] = claim_id
        return f"[CLAIM {by_id[claim_id]}]"

    return _MARKER.sub(to_ref, prompt), refs


def _resolve(value: Any) -> Any:
    refs = _active_refs.get()
    if refs is None or not isinstance(value, str) or not _REF.match(value.strip()):
        return value
    ref = value.strip()
    if ref not in refs:
        raise ValueError(
            f"unknown claim reference {ref!r}: cite only the C-numbers shown in the [CLAIM ...] markers"
        )
    return refs[ref]


# The claim-id type for every model-output schema. Outside a claim-citing
# call it is an ordinary UUID.
ClaimId = Annotated[
    uuid.UUID,
    BeforeValidator(_resolve),
    WithJsonSchema(
        {
            "type": "string",
            "description": "A claim reference exactly as shown in [CLAIM ...], e.g. C3",
        }
    ),
]


async def generate_citing_claims(
    provider: AIProvider, prompt: str, schema: type[_T], **opts: Any
) -> _T:
    """``provider.generate`` for prompts containing ``[CLAIM <uuid>]`` markers."""
    short_prompt, refs = rewrite_claim_markers(prompt)
    token = _active_refs.set(refs)
    try:
        return cast(_T, await provider.generate(short_prompt, schema, **opts))
    finally:
        _active_refs.reset(token)
