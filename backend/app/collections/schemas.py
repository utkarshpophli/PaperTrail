"""Pydantic v2 request/response shapes for the Collections module (Phase 7).
See docs/API_SPEC.md's "Collections" section and docs/DATA_MODEL.md's
``Collection`` entry.
"""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class CollectionCreateRequest(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]


class CollectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    paper_ids: list[str]
    created_at: datetime
    updated_at: datetime
