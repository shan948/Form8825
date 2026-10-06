"""Three ways a value can be present on a page, normalised into `Token`s.

1. AcroForm widgets  - fillable PDF (the supplied sample). Values live in the
                       widget /V entries; they are NOT in the page text layer.
2. Text layer        - flattened/printed-to-PDF returns; values are ordinary
                       text drawn on the page.
3. OCR               - scanned/image-only pages. Rendered with pdf2image and
                       read cell-by-cell with Tesseract.
"""
from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass

from .layout import Box

log = logging.getLogger(__name__)


@dataclass
class Token:
    text: str
    box: Box                       # PDF points, top-left origin
    source: str                    # acroform | text | ocr
    confidence: float | None = None
    field_name: str | None = None


# --------------------------------------------------------------------------- #
# 1. AcroForm widgets
# --------------------------------------------------------------------------- #
def _inherited(annot, key):
    """Field attributes (/FT, /V) may sit on a parent field, not the widget."""
    node, depth = annot, 0
    while node is not None and depth < 10:
        if key in node:
            return node[key]
        parent = node.get("/Parent")
        node = parent.get_object() if parent is not None else None
        depth += 1
    return None


def _full_name(annot) -> str:
    parts, node, depth = [], annot, 0
    while node is not None and depth < 10:
        if "/T" in node:
            parts.append(str(node["/T"]))
        parent = node.get("/Parent")
        node = parent.get_object() if parent is not None else None
        depth += 1
    return ".".join(reversed(parts))


def widget_tokens(pypdf_page) -> list[Token]:
    tokens: list[Token] = []
    annots = pypdf_page.get("/Annots")
    if annots is None:
        return tokens
    annots = annots.get_object()
    mb = pypdf_page.mediabox
    page_top, page_left = float(mb.top), float(mb.left)
    for ref in annots:
        try:
            annot = ref.get_object()
            if annot.get("/Subtype") != "/Widget":
                continue
            if _inherited(annot, "/FT") != "/Tx":        # ignore checkboxes/buttons
                continue
            value = _inherited(annot, "/V")
            if value is None or str(value).strip() == "":
                continue
            x0, y0, x1, y1 = (float(v) for v in annot["/Rect"])
            x0, x1 = sorted((x0, x1))
            y0, y1 = sorted((y0, y1))
            box = Box(x0 - page_left, page_top - y1, x1 - page_left, page_top - y0)
            tokens.append(Token(str(value).strip(), box, "acroform", 1.0, _full_name(annot)))
        except Exception as exc:  # one broken widget must not kill the page
            log.warning("skipping unreadable widget: %s", exc)
    return tokens


# --------------------------------------------------------------------------- #
# 2. Text layer
# --------------------------------------------------------------------------- #
_CID_RE = re.compile(r"\(cid:\d+\)")


def text_layer_quality(plumber_page) -> dict:
    """Decide whether a page has a *usable* text layer.

    A page can have text that is useless: an image-only scan (0 chars), a scan
    with a few stray characters, or fonts without a ToUnicode map that extract
    as "(cid:123)" garbage. We require enough characters, a low share of
    unmapped glyphs and a mostly printable/alphanumeric character mix.
    """
    chars = plumber_page.chars
    text = plumber_page.extract_text() or ""
    n = len(chars)
    cid_hits = len(_CID_RE.findall(text))
    visible = [c for c in text if not c.isspace()]
    alnum_ratio = (sum(c.isalnum() for c in visible) / len(visible)) if visible else 0.0
    image_area = sum((im["x1"] - im["x0"]) * (im["bottom"] - im["top"]) for im in plumber_page.images)
    page_area = float(plumber_page.width * plumber_page.height) or 1.0
    usable = n >= 200 and cid_hits <= 0.1 * max(n, 1) and alnum_ratio >= 0.5
    return {
        "chars": n,
        "cid_glyphs": cid_hits,
        "alnum_ratio": round(alnum_ratio, 3),
        "image_coverage": round(min(image_area / page_area, 1.0), 3),
        "usable": usable,
        "text": text,
    }


def text_words(plumber_page) -> list[dict]:
    return plumber_page.extract_words(x_tolerance=1.5, y_tolerance=2, keep_blank_chars=False)


def text_tokens(words: list[dict]) -> list[Token]:
    # Pure punctuation words (the printed "( )" around line 20b, leader dots)
    # belong to the form template, never to a value.
    return [Token(w["text"], Box(w["x0"], w["top"], w["x1"], w["bottom"]), "text", 1.0)
            for w in words if any(ch.isalnum() for ch in w["text"])]


# --------------------------------------------------------------------------- #
# 3. OCR (Tesseract)
# --------------------------------------------------------------------------- #
def ocr_available() -> bool:
    if shutil.which("tesseract") is None:
        return False
    try:
        import pytesseract  # noqa: F401
        from pdf2image import convert_from_path  # noqa: F401
    except ImportError:
        return False
    return True


class OcrPage:
    """A rendered page plus helpers to OCR whole-page words or single cells."""

    NUMERIC_CFG = "--psm 7 -c tessedit_char_whitelist=0123456789,.()-$"
    TEXT_CFG = "--psm 7"

    def __init__(self, pdf_path: str, page_number: int, page_width_pt: float, dpi: int = 300,
                 password: str | None = None):
        from pdf2image import convert_from_path

        images = convert_from_path(pdf_path, dpi=dpi, first_page=page_number, last_page=page_number,
                                   grayscale=True, userpw=password)
        self.image = images[0]
        self._fix_rotation()
        self.scale = self.image.width / page_width_pt       # pixels per PDF point
        from PIL import ImageFilter
        self.clean = self.image.filter(ImageFilter.MedianFilter(3))   # removes salt & pepper specks

    def _fix_rotation(self):
        """Use Tesseract orientation detection to undo 90/180/270 rotated scans."""
        import pytesseract
        try:
            osd = pytesseract.image_to_osd(self.image, output_type=pytesseract.Output.DICT)
            angle = int(osd.get("rotate", 0))
            if angle and osd.get("orientation_conf", 0) > 2:
                self.image = self.image.rotate(-angle, expand=True)
        except Exception:  # OSD fails on sparse pages; not fatal
            pass

    def words(self) -> list[dict]:
        """Whole-page OCR words in PDF points (used for page detection + calibration)."""
        import pytesseract
        data = pytesseract.image_to_data(self.image, config="--psm 11",
                                         output_type=pytesseract.Output.DICT)
        out = []
        for i, txt in enumerate(data["text"]):
            if not txt.strip():
                continue
            s = self.scale
            out.append({"text": txt, "x0": data["left"][i] / s, "top": data["top"][i] / s,
                        "x1": (data["left"][i] + data["width"][i]) / s,
                        "bottom": (data["top"][i] + data["height"][i]) / s,
                        "conf": float(data["conf"][i])})
        return out

    def text(self) -> str:
        import pytesseract
        return pytesseract.image_to_string(self.image)

    def _clean_cell(self, box: Box):
        """Crop a cell and prepare it for Tesseract.

        despeckle (page-level median filter) -> binarise -> erase ruling lines
        -> crop to the remaining ink -> upscale. Returns None for empty cells.
        """
        from PIL import Image

        s = self.scale
        inner = box.inset(1.5)                       # stay clear of the grid lines
        crop = self.clean.crop((int(inner.x0 * s), int(inner.top * s), int(inner.x1 * s), int(inner.bottom * s)))
        bw = crop.point(lambda p: 0 if p < 150 else 255, "L")
        w, h = bw.size
        if w < 4 or h < 4:
            return None
        px = bw.load()
        for y in range(h):                            # horizontal rules / dashed leaders
            if sum(px[x, y] == 0 for x in range(w)) > 0.45 * w:
                for x in range(w):
                    px[x, y] = 255
        for x in range(w):                            # vertical rules
            if sum(px[x, y] == 0 for y in range(h)) > 0.7 * h:
                for y in range(h):
                    px[x, y] = 255
        bbox = Image.eval(bw, lambda p: 255 - p).getbbox()
        if bbox is None:
            return None
        x0, y0, x1, y1 = bbox
        dark = sum(1 for v in bw.crop(bbox).getdata() if v == 0)
        if (y1 - y0) < 0.25 * 7 * s or dark < 0.3 * s * s:      # smaller than ~a quarter of a glyph
            return None
        pad = int(2 * s)
        tight = bw.crop((max(x0 - pad, 0), max(y0 - pad, 0), min(x1 + pad, w), min(y1 + pad, h)))
        target_h = 48                                  # tesseract is happiest with ~30-50px glyph rows
        factor = max(1.0, target_h / tight.height)
        tight = tight.resize((int(tight.width * factor), int(tight.height * factor)), Image.LANCZOS)
        out = Image.new("L", (tight.width + 40, tight.height + 40), 255)
        out.paste(tight, (20, 20))
        return out

    def has_ink(self, box: Box) -> bool:
        return self._clean_cell(box) is not None

    def read_cell(self, box: Box, numeric: bool) -> Token | None:
        import pytesseract

        img = self._clean_cell(box)
        if img is None:
            return None
        data = pytesseract.image_to_data(img, config=self.NUMERIC_CFG if numeric else self.TEXT_CFG,
                                         output_type=pytesseract.Output.DICT)
        parts = [(t, float(c)) for t, c in zip(data["text"], data["conf"]) if t.strip()]
        if numeric:
            parts = [p for p in parts if any(ch.isdigit() for ch in p[0])] or parts
        if not parts:
            return None
        text = ("" if numeric else " ").join(p[0] for p in parts)
        if numeric:
            text = text.strip(".,")                    # stray specks at either end
        confs = [p[1] for p in parts if p[1] >= 0]
        conf = (min(confs) / 100.0) if confs else None
        return Token(text, box, "ocr", None if conf is None else round(conf, 3))
