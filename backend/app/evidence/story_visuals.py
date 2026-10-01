"""StorySpec schemas: the typed visual attached to every story section, plus
the story-level meta and the API-facing response shapes.

One set of models serves two boundaries: ``StorySpecOutput`` is what the
provider is forced to emit (so structural rules -- edge endpoints, matrix cell
counts, item-count bounds -- are enforced by the same schema-validation +
one-retry path as every other extraction output), and ``StorySpecResponse`` is
the fixed contract ``GET /papers/{id}/story-spec`` returns. Rules that need
the paper's own evidence (claim ids, metric values, verbatim quotes) live in
``app.evidence.story_integrity``, not here.
"""

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, model_validator

from app.evidence.claim_refs import ClaimId

# Length caps on every string: a hijacked/rambling pass can't stuff a section
# with an arbitrarily large payload, and the UI has a bounded layout to fill.
_Short = Annotated[str, StringConstraints(min_length=1, max_length=120)]
_Medium = Annotated[str, StringConstraints(min_length=1, max_length=400)]
_Long = Annotated[str, StringConstraints(min_length=1, max_length=1200)]
_OptionalNote = Annotated[str, StringConstraints(max_length=200)]
_NodeId = Annotated[str, StringConstraints(min_length=1, max_length=40)]
_Tone = Literal["paper", "accent", "ink"]

MAX_SECTIONS = 8
MIN_SECTIONS = 5
ADVANCED_VISUAL_TYPES = frozenset({"architecture", "equation", "timeline", "matrix", "infographic"})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _VisualBase(_Strict):
    eyebrow: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    caption: Annotated[str, StringConstraints(min_length=1, max_length=300)]


# --- item shapes -------------------------------------------------------------


class MetricItem(_Strict):
    label: _Short
    value: Annotated[str, StringConstraints(min_length=1, max_length=60)]
    note: _OptionalNote


class LabelDetail(_Strict):
    label: _Short
    detail: _Medium


class ComparisonItem(_Strict):
    label: _Short
    value: float = Field(allow_inf_nan=False)
    display_value: Annotated[str, StringConstraints(min_length=1, max_length=60)]
    highlight: bool


class ToneItem(_Strict):
    label: _Short
    detail: _Medium
    tone: _Tone


class InfographicItem(_Strict):
    label: _Short
    detail: _Medium
    badge: _OptionalNote


class ArchitectureNode(_Strict):
    id: _NodeId
    label: _Short
    detail: _Medium
    group: Literal["input", "core", "output", "evidence"]


class ArchitectureEdge(_Strict):
    source: _NodeId
    target: _NodeId
    label: _OptionalNote


class EquationTerm(_Strict):
    symbol: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    label: _Short
    detail: _Medium


class MatrixCell(_Strict):
    label: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    tone: Literal["low", "medium", "high", "neutral"]


class MatrixRow(_Strict):
    label: _Short
    cells: list[MatrixCell] = Field(min_length=2, max_length=5)


# --- the eleven visuals ------------------------------------------------------


class MetricVisual(_VisualBase):
    type: Literal["metric"]
    items: list[MetricItem] = Field(min_length=2, max_length=4)


class FlowVisual(_VisualBase):
    type: Literal["flow"]
    items: list[LabelDetail] = Field(min_length=3, max_length=6)


class ComparisonVisual(_VisualBase):
    type: Literal["comparison"]
    items: list[ComparisonItem] = Field(min_length=2, max_length=6)


class ConceptVisual(_VisualBase):
    type: Literal["concept"]
    center: _Short
    items: list[LabelDetail] = Field(min_length=3, max_length=6)


class LayersVisual(_VisualBase):
    type: Literal["layers"]
    items: list[ToneItem] = Field(min_length=3, max_length=6)


class QuoteVisual(_VisualBase):
    type: Literal["quote"]
    quote: Annotated[str, StringConstraints(min_length=1, max_length=1200)]
    attribution: _Medium


class ArchitectureVisual(_VisualBase):
    type: Literal["architecture"]
    nodes: list[ArchitectureNode] = Field(min_length=3, max_length=8)
    edges: list[ArchitectureEdge] = Field(min_length=2, max_length=12)

    @model_validator(mode="after")
    def _edges_reference_existing_nodes(self) -> "ArchitectureVisual":
        ids = [node.id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("architecture node ids must be unique")
        known = set(ids)
        for edge in self.edges:
            missing = sorted({edge.source, edge.target} - known)
            if missing:
                raise ValueError(
                    f"architecture edge {edge.source!r}->{edge.target!r} references unknown node id(s): {missing}"
                )
        return self


class EquationVisual(_VisualBase):
    type: Literal["equation"]
    formula: Annotated[str, StringConstraints(min_length=1, max_length=400)]
    terms: list[EquationTerm] = Field(min_length=2, max_length=7)
    steps: list[_Medium] = Field(min_length=2, max_length=5)


class TimelineVisual(_VisualBase):
    type: Literal["timeline"]
    items: list[ToneItem] = Field(min_length=3, max_length=7)


class MatrixVisual(_VisualBase):
    type: Literal["matrix"]
    columns: list[_Short] = Field(min_length=2, max_length=5)
    rows: list[MatrixRow] = Field(min_length=2, max_length=6)

    @model_validator(mode="after")
    def _cells_match_columns(self) -> "MatrixVisual":
        for row in self.rows:
            if len(row.cells) != len(self.columns):
                raise ValueError(
                    f"matrix row {row.label!r} has {len(row.cells)} cell(s) but there are {len(self.columns)} column(s)"
                )
        return self


class InfographicVisual(_VisualBase):
    type: Literal["infographic"]
    items: list[InfographicItem] = Field(min_length=3, max_length=6)


Visual = Annotated[
    MetricVisual
    | FlowVisual
    | ComparisonVisual
    | ConceptVisual
    | LayersVisual
    | QuoteVisual
    | ArchitectureVisual
    | EquationVisual
    | TimelineVisual
    | MatrixVisual
    | InfographicVisual,
    Field(discriminator="type"),
]
VisualAdapter: TypeAdapter[Visual] = TypeAdapter(Visual)


# --- story structure ---------------------------------------------------------


class StoryClosing(_Strict):
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    body: _Long


class StoryMeta(_Strict):
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    dek: _Medium
    reading_time: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    closing: StoryClosing


class StorySectionDraft(_Strict):
    """A section as the provider emits it. ``id`` and ``index_label`` are
    deliberately not model-controlled: the id is the persisted row's uuid and
    the label is the section's position, so neither can be duplicated or
    skipped by a misbehaving model."""

    kicker: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    body: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    claim_ids: list[ClaimId] = Field(min_length=1, max_length=12)
    visual: Visual


class StorySpec(_Strict):
    """A whole story with no section-count bound -- what validation, integrity
    checking and persistence work on, so a hand-authored demo story (one
    section per visual type) uses the same code path as a generated one."""

    meta: StoryMeta
    sections: list[StorySectionDraft] = Field(min_length=1)


class StorySpecOutput(StorySpec):
    """What the provider is forced to emit: a story of 5-8 sections."""

    sections: list[StorySectionDraft] = Field(min_length=MIN_SECTIONS, max_length=MAX_SECTIONS)


# --- API-facing response (the fixed GET /papers/{id}/story-spec contract) -----


class StorySectionResponse(_Strict):
    id: uuid.UUID
    index_label: Annotated[str, StringConstraints(pattern=r"^\d{2}$")]
    kicker: str
    title: str
    body: str
    claim_ids: list[ClaimId]
    visual: Visual


class StorySpecResponse(_Strict):
    meta: StoryMeta
    sections: list[StorySectionResponse]

    @model_validator(mode="after")
    def _labels_sequential(self) -> "StorySpecResponse":
        expected = [index_label(i) for i in range(len(self.sections))]
        if [s.index_label for s in self.sections] != expected:
            raise ValueError("section index_labels must run sequentially from '01'")
        return self


def index_label(position: int) -> str:
    """Zero-based section position -> "01", "02", ..."""
    return f"{position + 1:02d}"
