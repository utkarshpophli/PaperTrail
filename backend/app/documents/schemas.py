"""The fixed contract nothing downstream reaches past (ARCHITECTURE.md:
Document Pipeline). ``parser.py``, ``figures.py`` and every caller build to
these shapes exactly — do not add provider-specific fields here.
"""

from typing import Any

from pydantic import BaseModel


class ParsedFigure(BaseModel):
    page: int
    caption: str | None
    image_path: str  # path on disk, relative to output_dir
    # Page-space (x0, y0, x1, y1) in PDF points. Optional: rows stored before
    # this field existed have none, and PageResponse doesn't expose it.
    bbox: tuple[float, float, float, float] | None = None


class ParsedPage(BaseModel):
    number: int
    text: str
    figures: list[ParsedFigure]


class ParsedDocument(BaseModel):
    pages: list[ParsedPage]
    metadata: dict[str, Any]
