"""A representative structured-output schema for provider tests — same
shape/complexity as an evidence-extraction claim schema (which doesn't exist
yet; the Evidence Engine is a later phase) without depending on it."""

from pydantic import BaseModel


class SampleClaim(BaseModel):
    claim_text: str
    page: int
    confidence: float
    source_excerpt: str
