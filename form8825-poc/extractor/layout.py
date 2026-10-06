"""Where each value lives on the page.

Why position-based instead of AcroForm field names?
  * In the supplied sample the widget names are unreliable: line 14 col A and
    line 19 col A are both named `...f1_99[0]`, and only filled widgets are
    registered in /AcroForm /Fields.
  * Flattened or scanned returns have no field names at all.
A value's *position* (row = line number, column = property) is the one thing
that holds across fillable, flattened and scanned inputs.

Coordinates are PDF points, origin top-left (pdfplumber convention), measured
on the Rev. December 2025 form (612 x 792). `calibrate()` shifts/scales the
template using printed anchor labels ("2a", "2b", ... "19") found on the actual
page, so small offsets between revisions, printers or scans are absorbed.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from .schema import PROPERTY_LINES, SUMMARY_LINES

TEMPLATE_WIDTH, TEMPLATE_HEIGHT = 612.0, 792.0

# Amount columns for properties (x0, x1). Same on page 1 and page 2.
GRID_COLUMNS = [(288.0, 360.0), (360.0, 432.0), (432.0, 504.0), (504.0, 576.0)]
LABEL_COLUMN_X0 = 272.0          # x of the small printed line-number box ("2a")

# Top of the printed line-number label for each grid line on page 1.
_P1_LABEL_TOPS = {
    "2a": 302, "2b": 314, "2c": 338, "3": 362, "4": 374, "5": 386, "6": 398,
    "7": 410, "8": 422, "9": 434, "10": 446, "11": 458, "12": 470, "13": 482,
    "14": 494, "15": 506, "16": 518, "17": 530, "18": 554, "19": 578,
}
_P2_OFFSET = -60                 # the page-2 grid sits 60pt higher than page 1
_SUMMARY_CELL_TOPS = {"20a": 588, "20b": 600, "21": 624, "22a": 648, "23": 744}
_SUMMARY_X = (504.0, 576.0)
_ADDRESS_X = (59.0, 201.0)


@dataclass(frozen=True)
class Box:
    x0: float
    top: float
    x1: float
    bottom: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2

    def contains(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.top <= y <= self.bottom

    def transform(self, dx: float, dy: float, sx: float, sy: float) -> "Box":
        return Box(self.x0 * sx + dx, self.top * sy + dy, self.x1 * sx + dx, self.bottom * sy + dy)

    def inset(self, d: float) -> "Box":
        return Box(self.x0 + d, self.top + d, self.x1 - d, self.bottom - d)


# Cell keys:
#   ("grid", col_idx, line_code)   amount for a property column
#   ("address", row_idx)           line 1 column (a) for property row
#   ("row_letter", row_idx)        page 2 only: letter typed next to the address row
#   ("col_letter", col_idx)        page 2 only: letter typed above an amount column
#   ("summary", line_code)         lines 20a-23 (page 1)
#   ("name",) / ("ein",)           header (page 1)
CellKey = tuple


@dataclass
class PageLayout:
    kind: str                                   # "page1" | "page2"
    cells: dict[CellKey, Box]
    anchors: dict[str, Box]                     # printed labels used for calibration
    calibration: dict = field(default_factory=dict)

    def cell_at(self, x: float, y: float) -> CellKey | None:
        for key, box in self.cells.items():
            if box.contains(x, y):
                return key
        return None

    def transformed(self, dx: float, dy: float, sx: float, sy: float) -> "PageLayout":
        return PageLayout(
            kind=self.kind,
            cells={k: b.transform(dx, dy, sx, sy) for k, b in self.cells.items()},
            anchors={k: b.transform(dx, dy, sx, sy) for k, b in self.anchors.items()},
            calibration=dict(self.calibration),
        )


def template_layout(kind: str) -> PageLayout:
    off = 0 if kind == "page1" else _P2_OFFSET
    cells: dict[CellKey, Box] = {}
    anchors: dict[str, Box] = {}
    for d in PROPERTY_LINES:
        top = _P1_LABEL_TOPS[d.code] + off
        anchors[d.code] = Box(LABEL_COLUMN_X0, top, LABEL_COLUMN_X0 + 10, top + 9)
        for ci, (x0, x1) in enumerate(GRID_COLUMNS):
            cells[("grid", ci, d.code)] = Box(x0, top - 2, x1, top + 10)

    if kind == "page1":
        for ri in range(4):                       # rows A-D, 24pt tall
            top = 180 + 24 * ri
            cells[("address", ri)] = Box(_ADDRESS_X[0], top, _ADDRESS_X[1], top + 24)
        for d in SUMMARY_LINES:
            top = _SUMMARY_CELL_TOPS[d.code]
            cells[("summary", d.code)] = Box(_SUMMARY_X[0], top, _SUMMARY_X[1], top + 12)
        cells[("name",)] = Box(36, 94, 454, 108)
        cells[("ein",)] = Box(454, 94, 576, 108)
    else:
        for ri in range(4):
            top = 120 + 24 * ri
            cells[("address", ri)] = Box(_ADDRESS_X[0], top, _ADDRESS_X[1], top + 24)
            cells[("row_letter", ri)] = Box(36, top, 58, top + 24)
        for ci, (x0, x1) in enumerate(GRID_COLUMNS):
            cells[("col_letter", ci)] = Box(x0, 228, x1, 240)
    return PageLayout(kind=kind, cells=cells, anchors=anchors)


def detect_page_kind(text: str) -> str | None:
    """Classify a page from its text (text layer or OCR). None = not an 8825 page."""
    t = " ".join(text.split()).lower()
    if "8825" not in t and "rental real estate" not in t:
        return None
    if "gross rents" not in t and "rental real estate income" not in t:
        return None
    # Page 1 itself says "Attach page 2 ...", so key on content unique to page 2.
    if "allowable codes" in t:
        return "page2"
    return "page1"


def calibrate(kind: str, words: list[dict], page_width: float, page_height: float) -> PageLayout:
    """Fit the template to the page using printed line-number labels.

    `words` are dicts with text/x0/top (points, top-left origin) from either
    pdfplumber or OCR. Returns the template scaled to the page with a
    translation estimated from the anchors; `calibration` records how many
    anchors matched and the residual error so callers can judge confidence.
    """
    sx, sy = page_width / TEMPLATE_WIDTH, page_height / TEMPLATE_HEIGHT
    base = template_layout(kind).transformed(0, 0, sx, sy)

    by_text: dict[str, list[dict]] = {}
    for w in words:
        by_text.setdefault(w["text"].strip().rstrip("."), []).append(w)

    dxs, dys, matched = [], [], []
    for code, anchor in base.anchors.items():
        # Nearest printed label with the same text, within a generous window.
        best = None
        for w in by_text.get(code, []):
            ddx, ddy = w["x0"] - anchor.x0, w["top"] - anchor.top
            if abs(ddx) < 40 * sx and abs(ddy) < 40 * sy:
                if best is None or abs(ddy) < abs(best[1]):
                    best = (ddx, ddy)
        if best:
            dxs.append(best[0])
            dys.append(best[1])
            matched.append(code)

    total = len(base.anchors)
    if len(matched) >= 3:
        dx, dy = statistics.median(dxs), statistics.median(dys)
        residual = statistics.median(abs(y - dy) for y in dys)
    else:
        dx = dy = 0.0
        residual = None
    layout = base.transformed(dx, dy, 1, 1)
    layout.calibration = {
        "anchors_matched": len(matched),
        "anchors_total": total,
        "offset": [round(dx, 2), round(dy, 2)],
        "scale": [round(sx, 4), round(sy, 4)],
        "residual": None if residual is None else round(residual, 2),
        "method": "anchors" if len(matched) >= 3 else "template_default",
    }
    return layout
