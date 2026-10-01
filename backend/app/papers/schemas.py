"""Pydantic request/response models for the papers routes."""

import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.paper import ParseStatus


class ArxivResolveRequest(BaseModel):
    """Body for ``POST /papers/from-arxiv`` — exactly one identifier."""

    arxiv_id: str | None = Field(default=None, min_length=1)
    arxiv_title: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _exactly_one_identifier(self) -> Self:
        if bool(self.arxiv_id) == bool(self.arxiv_title):
            raise ValueError("Provide exactly one of arxiv_id or arxiv_title")
        return self


class FigureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    page: int
    caption: str | None
    image_path: str


class FigureRefreshResponse(BaseModel):
    figures: int
    pages_with_figures: int


class PageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    page_number: int
    text: str
    figures: list[FigureResponse]


class PaperResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    authors: list[str]
    year: int | None
    venue: str | None
    doi: str | None
    arxiv_id: str | None
    parse_status: ParseStatus
    parse_error: str | None
    created_at: datetime
