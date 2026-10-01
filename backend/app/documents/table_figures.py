"""Table regions for ``Table N`` captions.

A ruled table (booktabs, or a full grid) is bounded by horizontal rules of the
same width stacked down the page: top rule, header rule, bottom rule. A stack
of two or more such rules is a table, paired with the nearest caption
directly above or below it. PyMuPDF's ``find_tables`` was tried first and
missed booktabs tables next to drawn figures (DeepSeek-V3 Table 2).

Never guess: a caption with no rule stack close to it gets no crop.
"""

import re

import fitz

TABLE_CAPTION_START = re.compile(r"^\s*tab(?:le)?\.?\s*\d+\s*[:.|]", re.IGNORECASE)

Box = tuple[float, float, float, float]

_RULE_MAX_THICKNESS = 3.0
_RULE_MIN_LENGTH = 100.0
_EDGE_TOLERANCE = 12.0  # rules of one table start/end within this of each other
_MAX_CAPTION_GAP = 50.0
_CAPTION_OVERLAP_TOLERANCE = 4.0


def find_table_regions(page: fitz.Page, captions: list[tuple[Box, str]]) -> list[tuple[str, Box]]:
    """(caption text, table box) for each caption that has a table adjacent
    to it. Each table is claimed by at most one caption.

    A paper puts table captions consistently on one side, and a caption
    between two tables is close to both, so nearest-wins picks wrong. Both
    sides are tried and the one that explains more captions is kept."""
    if not captions:
        return []
    tables = _rule_stacks(page, [cap for cap, _ in captions])
    above = _pair(captions, tables, table_above=True)
    below = _pair(captions, tables, table_above=False)
    return above if len(above) >= len(below) else below


def _pair(captions: list[tuple[Box, str]], tables: list[Box], table_above: bool) -> list[tuple[str, Box]]:
    regions: list[tuple[str, Box]] = []
    claimed: set[int] = set()
    for cap, text in captions:
        best: tuple[float, int] | None = None
        for index, table in enumerate(tables):
            if index in claimed or not (table[0] < cap[2] and table[2] > cap[0]):
                continue
            gap = _caption_gap(table, cap, table_above)
            if gap is not None and (best is None or gap < best[0]):
                best = (gap, index)
        if best is not None:
            claimed.add(best[1])
            regions.append((text, tables[best[1]]))
    return regions


def _rule_stacks(page: fitz.Page, caption_boxes: list[Box]) -> list[Box]:
    rules = sorted(
        (
            d["rect"]
            for d in page.get_drawings()
            if d["rect"].height < _RULE_MAX_THICKNESS and d["rect"].width >= _RULE_MIN_LENGTH
        ),
        key=lambda r: r.y0,
    )
    stacks: list[list[fitz.Rect]] = []
    for rule in rules:
        for stack in stacks:
            last = stack[-1]
            same_edges = abs(rule.x0 - last.x0) <= _EDGE_TOLERANCE and abs(rule.x1 - last.x1) <= _EDGE_TOLERANCE
            # A caption between two rules means they belong to different tables.
            split = any(last.y1 <= cap[1] and cap[3] <= rule.y0 for cap in caption_boxes)
            if same_edges and not split:
                stack.append(rule)
                break
        else:
            stacks.append([rule])
    return [
        (min(r.x0 for r in s), s[0].y0, max(r.x1 for r in s), s[-1].y1)
        for s in stacks
        if len(s) >= 2
    ]


def _caption_gap(table: Box, cap: Box, table_above: bool) -> float | None:
    if table_above and table[3] <= cap[1] + _CAPTION_OVERLAP_TOLERANCE:
        gap = cap[1] - table[3]
    elif not table_above and table[1] >= cap[3] - _CAPTION_OVERLAP_TOLERANCE:
        gap = table[1] - cap[3]
    else:
        return None
    return max(0.0, gap) if gap <= _MAX_CAPTION_GAP else None
