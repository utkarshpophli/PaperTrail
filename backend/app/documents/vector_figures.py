"""Caption-anchored figure and table crops.

For each ``Figure N`` caption this finds the figure next to it and renders
that clip of the page to PNG, so one caption gives exactly one image. The
figure is built from the page's drawing operators *and* its embedded images
together. Real figures mix the two: a diagram with small raster icons, a
plot with an inset, a heatmap with a raster colorbar. Treating each embedded
image as its own figure split them into fragments. ``Table N`` captions get
the table found by ``table_figures``. Nothing is fetched or executed, and no
filename is derived from PDF text.

Never guess: if nothing next to a caption looks like a figure (enough items,
real shapes rather than rules, sane size), the caption gets no crop.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import fitz
from PIL import Image, ImageChops

from app.documents.schemas import ParsedFigure
from app.documents.table_figures import TABLE_CAPTION_START, find_table_regions

# ponytail: a caption must have a delimiter after its number ("Figure 2:",
# "Fig. 2.", "Table 1 |"), which is what tells it apart from prose like
# "Table 6 presents...". Known ceiling: papers whose captions use no
# delimiter ("Figure 1 Overview") get no crop. Upgrade path: font-based
# caption detection (bold label) if that shows up in practice.
_FIGURE_CAPTION_START = re.compile(r"^\s*fig(?:ure)?\.?\s*\d+\s*[:.|]", re.IGNORECASE)
_ANY_CAPTION_START = re.compile(r"^\s*(?:fig(?:ure)?|tab(?:le)?)\.?\s*\d+\s*[:.|]", re.IGNORECASE)

# Drawing filters (points). Page borders/backgrounds and page-wide rules are
# layout furniture, and sub-1.5pt marks are noise.
_MIN_MARK = 1.5
_WHITE = (1.0, 1.0, 1.0)
_FURNITURE_AREA_FRACTION = 0.7
_RULE_THICKNESS = 3.0
_RULE_LENGTH_FRACTION = 0.9

# Cluster validation: enough drawing items, at least one real shape (a
# ruled table is only axis-aligned hairlines), and a plausible size.
MIN_CLUSTER_ITEMS = 6
_MIN_SHAPE_DIM = 3.0
_MIN_FIGURE_WIDTH = 40.0
_MIN_FIGURE_HEIGHT = 25.0
_MAX_PAGE_AREA_FRACTION = 0.8

# Clustering / search geometry (points).
_GAP_NARROW = 12.0  # < typical two-column gutter (~14pt) so columns don't fuse
_GAP_WIDE = 30.0  # full-width caption: allow side-by-side subfigures
_GAP_Y = 25.0
_WIDE_CAPTION_FRACTION = 0.6
_MAX_CAPTION_GAP = 50.0  # figure edge must be this close to its caption
_CAPTION_OVERLAP_TOLERANCE = 4.0
_LABEL_MERGE_MARGIN = 10.0
_CROP_MARGIN = 4.0
_MAX_CLUSTER_INPUTS = 5000  # ponytail: scatter plots of thousands of marks are skipped, not clustered
# Security review: a page whose text a pathological PDF fills with thousands
# of blocks matching "Figure N:" had no bound on how many the caption loop
# below would search a region for -- unlike every other loop in this module.
# A real paper has a handful of figure captions per page; this caps the
# search itself (not just the per-caption clustering _MAX_CLUSTER_INPUTS
# already bounded) so that unbounded caption count can't turn into unbounded
# work even when nothing ever matches (no drawing found -> no early break).
_MAX_CAPTIONS_PER_PAGE = 100

# Text classification.
_BODY_MIN_LINES = 4
_BODY_MIN_WIDTH_FRACTION = 0.3
_BODY_MIN_CHARS_PER_LINE = 20
_LABEL_MAX_LINES = 3
_LABEL_MAX_WIDTH_FRACTION = 0.6

# Render bounds: cap on either pixel dimension (decompression-bomb style
# huge clips on oversized pages).
RENDER_DPI = 150
_MAX_RENDER_PX = 2400
_TRIM_PADDING_PX = 8


class _Box(NamedTuple):
    # Plain tuple instead of fitz.Rect: PDF hairlines have zero-width rects,
    # which fitz treats as "empty" and refuses to intersect.
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def w(self) -> float:
        return self.x1 - self.x0

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    def union(self, other: "_Box") -> "_Box":
        return _Box(min(self.x0, other.x0), min(self.y0, other.y0), max(self.x1, other.x1), max(self.y1, other.y1))

    def expand(self, dx: float, dy: float) -> "_Box":
        return _Box(self.x0 - dx, self.y0 - dy, self.x1 + dx, self.y1 + dy)

    def touches(self, other: "_Box") -> bool:
        return self.x0 <= other.x1 and other.x0 <= self.x1 and self.y0 <= other.y1 and other.y0 <= self.y1

    def contains(self, other: "_Box") -> bool:
        return self.x0 <= other.x0 and self.y0 <= other.y0 and self.x1 >= other.x1 and self.y1 >= other.y1


@dataclass(frozen=True)
class _Text:
    box: _Box
    text: str
    lines: int


@dataclass(frozen=True)
class _Cluster:
    box: _Box
    items: int
    has_shape: bool


def extract_vector_figures(
    page: fitz.Page,
    page_number: int,
    figures_dir: Path,
    blocks: list[tuple],
    image_boxes: list[tuple[float, float, float, float]],
    max_figures: int,
) -> list[ParsedFigure]:
    """Renders one crop per ``Figure N``/``Table N`` caption on the page.
    ``blocks`` is ``page.get_text("blocks")``; ``image_boxes`` are where the
    page's embedded images are drawn. Returns at most ``max_figures`` results.
    """
    if max_figures <= 0:
        return []

    page_box = _Box(*page.rect)
    texts = [_Text(_Box(*b[:4]), b[4].strip(), _line_count(b[4])) for b in blocks if b[6] == 0 and b[4].strip()]
    captions = sorted((t for t in texts if _is_caption_like(t)), key=lambda t: t.box.y0)[:_MAX_CAPTIONS_PER_PAGE]
    if not captions:
        return []

    # An embedded image counts as one solid shape, enough on its own to
    # make a figure when it is figure-sized.
    drawings = _usable_drawings(page, page_box) + [(_Box(*b), MIN_CLUSTER_ITEMS, True) for b in image_boxes]
    regions: list[tuple[str, _Box, str]] = []
    for caption in (c for c in captions if _FIGURE_CAPTION_START.match(c.text)):
        region = _find_region(caption, texts, drawings, page_box)
        if region is not None:
            regions.append((caption.text, region, "vec"))
    table_captions = [(tuple(c.box), c.text) for c in captions if TABLE_CAPTION_START.match(c.text)]
    for text, box in find_table_regions(page, table_captions):
        regions.append((text, _clip(_Box(*box).expand(_CROP_MARGIN, _CROP_MARGIN), page_box), "tab"))

    used: list[_Box] = []
    figures: list[ParsedFigure] = []
    for caption_text, region, kind in sorted(regions, key=lambda r: r[1].y0):
        if len(figures) >= max_figures:
            break
        if any(_overlaps(region, u) for u in used):
            continue
        filename = f"page{page_number}_{kind}{len(figures)}.png"
        _render(page, region, figures_dir / filename)
        used.append(region)
        figures.append(
            ParsedFigure(
                page=page_number,
                caption=caption_text,
                image_path=f"figures/{filename}",
                bbox=tuple(round(v, 2) for v in region),
            )
        )
    return figures


def _clip(box: _Box, page_box: _Box) -> _Box:
    return _Box(max(box.x0, page_box.x0), max(box.y0, page_box.y0), min(box.x1, page_box.x1), min(box.y1, page_box.y1))


def _line_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def _overlaps(a: _Box, b: _Box) -> bool:
    return a.x0 < b.x1 and b.x0 < a.x1 and a.y0 < b.y1 and b.y0 < a.y1


def _usable_drawings(page: fitz.Page, page_box: _Box) -> list[tuple[_Box, int, bool]]:
    """(box, item count, is-real-shape) for drawings that could be part of a
    figure. Filters page furniture: borders/backgrounds and page-wide rules.
    """
    page_area = page_box.w * page_box.h
    out: list[tuple[_Box, int, bool]] = []
    for drawing in page.get_drawings():
        if drawing.get("color") is None and drawing.get("fill") == _WHITE:
            # Invisible white background a plotting tool painted under the
            # figure; it can reach over headings and prose and drag them in.
            continue
        # Clipped to the page: a path running off the page (GLM-5 p28 has one
        # ending at y=2402 on a 792pt page) would otherwise inflate its figure
        # past the size limit.
        box = _clip(_Box(*drawing["rect"]), page_box)
        if box.w < 0 or box.h < 0:
            continue  # entirely off the page
        if max(box.w, box.h) < _MIN_MARK:
            continue
        if box.w * box.h > _FURNITURE_AREA_FRACTION * page_area:
            continue
        thin_wide = box.h < _RULE_THICKNESS and box.w > _RULE_LENGTH_FRACTION * page_box.w
        thin_tall = box.w < _RULE_THICKNESS and box.h > _RULE_LENGTH_FRACTION * page_box.h
        if thin_wide or thin_tall:
            continue
        out.append((box, len(drawing["items"]), min(box.w, box.h) >= _MIN_SHAPE_DIM))
    return out


def _is_caption_like(text: _Text) -> bool:
    return bool(_ANY_CAPTION_START.match(text.text))


def _is_body(text: _Text, page_w: float) -> bool:
    # Line length separates prose from axis ticks ("0\n2\n4\n6") and table
    # cells, which can also be many lines spread across a wide box.
    return (
        text.lines >= _BODY_MIN_LINES
        and text.box.w >= _BODY_MIN_WIDTH_FRACTION * page_w
        and len(text.text) / text.lines >= _BODY_MIN_CHARS_PER_LINE
    )


def _is_label(text: _Text, page_w: float) -> bool:
    return (
        text.lines <= _LABEL_MAX_LINES
        and text.box.w <= _LABEL_MAX_WIDTH_FRACTION * page_w
        and not _is_caption_like(text)
    )


def _find_region(
    caption: _Text, texts: list[_Text], drawings: list[tuple[_Box, int, bool]], page_box: _Box
) -> _Box | None:
    wide = caption.box.w >= _WIDE_CAPTION_FRACTION * page_box.w
    for above in (True, False):  # figure is usually above its caption, occasionally below
        region = _region_on_side(caption, texts, drawings, page_box, above, wide)
        if region is not None:
            return region
    return None


def _region_on_side(
    caption: _Text,
    texts: list[_Text],
    drawings: list[tuple[_Box, int, bool]],
    page_box: _Box,
    above: bool,
    wide: bool,
) -> _Box | None:
    cap = caption.box
    limit = _barrier(caption, texts, drawings, page_box, above)
    lo, hi = (limit, cap.y0 + _CAPTION_OVERLAP_TOLERANCE) if above else (cap.y1 - _CAPTION_OVERLAP_TOLERANCE, limit)

    # A drawing may run a little past the caption edge (invisible hairlines,
    # or labels fused into the caption block), so only its near end is tested
    # here; the crop is clipped at the caption in _finish_box.
    if above:
        candidates = [d for d in drawings if d[0].y0 >= lo - 1 and d[0].y0 < cap.y0]
    else:
        candidates = [d for d in drawings if d[0].y1 <= hi + 1 and d[0].y1 > cap.y1]
    if not candidates or len(candidates) > _MAX_CLUSTER_INPUTS:
        return None

    clusters = _cluster(candidates, _GAP_WIDE if wide else _GAP_NARROW, _GAP_Y)
    # Every figure-like cluster right at the caption belongs to it: panels
    # set side by side (GLM-5 Figure 3) are separate clusters but one figure.
    panels = [
        c
        for c in clusters
        if -_CAPTION_OVERLAP_TOLERANCE <= _caption_distance(c.box, cap, above) <= _MAX_CAPTION_GAP
        and c.box.x0 < cap.x1
        and c.box.x1 > cap.x0
        and _is_figure_like(c, page_box)
    ]
    if not panels:
        return None
    box = panels[0].box
    for panel in panels[1:]:
        box = box.union(panel.box)
    finished = _finish_box(box, caption, texts, page_box, lo, hi, above)
    if finished.w >= _MIN_FIGURE_WIDTH and finished.h >= _MIN_FIGURE_HEIGHT:
        return finished
    return None


def _caption_distance(box: _Box, cap: _Box, above: bool) -> float:
    # Overlap with the caption counts as touching (0), not negative.
    return max(0.0, cap.y0 - box.y1) if above else max(0.0, box.y0 - cap.y1)


def _barrier(
    caption: _Text, texts: list[_Text], drawings: list[tuple[_Box, int, bool]], page_box: _Box, above: bool
) -> float:
    """Nearest body paragraph or other caption in the caption's column on the
    search side — the figure region must not extend past it, which is what
    stops a crop from swallowing prose.
    """
    cap = caption.box
    limit = page_box.y0 if above else page_box.y1
    for text in texts:
        if text is caption or not (text.box.x0 < cap.x1 and text.box.x1 > cap.x0):
            continue
        caption_like = _is_caption_like(text)
        if not caption_like and (not _is_body(text, page_box.w) or any(d[0].contains(text.box) for d in drawings)):
            continue  # not prose, or a text box drawn inside the figure itself
        if above and text.box.y1 <= cap.y0 + 1:
            limit = max(limit, text.box.y1)
        elif not above and text.box.y0 >= cap.y1 - 1:
            limit = min(limit, text.box.y0)
    return limit


def _cluster(drawings: list[tuple[_Box, int, bool]], gap_x: float, gap_y: float) -> list[_Cluster]:
    clusters: list[_Cluster] = []
    for box, items, shape in drawings:
        merged = _Cluster(box, items, shape)
        rest: list[_Cluster] = []
        for existing in clusters:
            if existing.box.expand(gap_x, gap_y).touches(merged.box):
                merged = _merge(merged, existing)
            else:
                rest.append(existing)
        clusters = [*rest, merged]

    # Merging grows boxes, which can bring previously separate clusters
    # together; repeat until stable (cluster count, not input count, so cheap).
    while True:
        before = len(clusters)
        combined: list[_Cluster] = []
        for cluster in clusters:
            for index, other in enumerate(combined):
                if other.box.expand(gap_x, gap_y).touches(cluster.box):
                    combined[index] = _merge(other, cluster)
                    break
            else:
                combined.append(cluster)
        clusters = combined
        if len(clusters) == before:
            return clusters


def _merge(a: _Cluster, b: _Cluster) -> _Cluster:
    return _Cluster(a.box.union(b.box), a.items + b.items, a.has_shape or b.has_shape)


def _is_figure_like(cluster: _Cluster, page_box: _Box) -> bool:
    box = cluster.box
    return (
        cluster.items >= MIN_CLUSTER_ITEMS
        and cluster.has_shape
        and box.w >= _MIN_FIGURE_WIDTH
        and box.h >= _MIN_FIGURE_HEIGHT
        and box.w * box.h <= _MAX_PAGE_AREA_FRACTION * page_box.w * page_box.h
    )


def _finish_box(
    box: _Box, caption: _Text, texts: list[_Text], page_box: _Box, lo: float, hi: float, above: bool
) -> _Box:
    """Grows the drawing cluster to include short text labels (axis titles,
    box captions, legends) touching it, then pads and clips to the search
    window so it never covers the caption or a paragraph past the barrier.
    """
    labels = [
        t
        for t in texts
        if t is not caption and _is_label(t, page_box.w) and t.box.y0 >= lo - 1 and t.box.y1 <= hi + 1
    ]
    for _ in range(2):
        grown = box
        for label in labels:
            if box.expand(_LABEL_MERGE_MARGIN, _LABEL_MERGE_MARGIN).touches(label.box):
                grown = grown.union(label.box)
        box = grown

    box = box.expand(_CROP_MARGIN, _CROP_MARGIN)
    cap = caption.box
    y0, y1 = (max(box.y0, lo), min(box.y1, cap.y0 - 1)) if above else (max(box.y0, cap.y1 + 1), min(box.y1, hi))
    return _Box(max(box.x0, page_box.x0), max(y0, page_box.y0), min(box.x1, page_box.x1), min(y1, page_box.y1))


def _render(page: fitz.Page, region: _Box, dest: Path) -> None:
    longest_pt = max(region.w, region.h)
    # int floor: PNG resolution metadata requires an int, and flooring keeps pixels under the cap.
    dpi = max(1, int(min(RENDER_DPI, _MAX_RENDER_PX * 72.0 / longest_pt)))
    pixmap = page.get_pixmap(clip=fitz.Rect(*region), dpi=dpi)
    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples) if pixmap.n == 3 else None
    if image is None:
        pixmap.save(str(dest))
        return
    # Figures often sit on an invisible page-wide background shape, which
    # pulls blank page margin into the region; trim it off.
    content = ImageChops.difference(image, Image.new("RGB", image.size, (255, 255, 255))).getbbox()
    if content is not None:
        pad = _TRIM_PADDING_PX
        image = image.crop(
            (max(0, content[0] - pad), max(0, content[1] - pad), min(image.width, content[2] + pad), min(image.height, content[3] + pad))
        )
    image.save(str(dest), format="PNG")
