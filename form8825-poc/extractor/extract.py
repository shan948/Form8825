"""Form 8825 extraction pipeline.

    file checks -> open (pypdf + pdfplumber) -> per page:
        text layer usable?  yes -> page type + calibration from text
                            no  -> OCR the page (if available) for type + calibration
        collect tokens (AcroForm widgets, text words, OCR cells) -> map to cells
    -> assemble properties -> parse amounts -> validate -> ExtractionResult
"""
from __future__ import annotations

import hashlib
import logging
import os
import string
from dataclasses import dataclass, field

import pdfplumber
from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError

from . import errors
from .layout import PageLayout, calibrate, detect_page_kind
from .parse import AmountParseError, parse_amount
from .schema import EXPENSE_LINES, INCOME_LINES, PROPERTY_LINES, SUMMARY_LINES
from .sources import OcrPage, Token, ocr_available, text_layer_quality, text_tokens, text_words, widget_tokens
from .validate import computed_totals, summarize, validate_form

log = logging.getLogger(__name__)
logging.getLogger("pypdf").setLevel(logging.ERROR)   # silence "wrong pointing object" noise

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_PAGES = 200
SOURCE_PRIORITY = {"acroform": 0, "text": 1, "ocr": 2}
OCR_LOW_CONFIDENCE = 0.60


@dataclass
class CellValue:
    raw: str | None = None
    value: int | str | None = None
    source: str | None = None
    confidence: float | None = None
    warnings: list[str] = field(default_factory=list)

    def as_dict(self):
        return {"raw": self.raw, "value": self.value, "source": self.source,
                "confidence": self.confidence, "warnings": self.warnings}


@dataclass
class PropertyResult:
    name: str
    address: str | None
    page: int
    column: int
    lines: dict[str, CellValue]

    def values(self) -> dict[str, int | None]:
        return {code: (cv.value if isinstance(cv.value, int) else None) for code, cv in self.lines.items()}


@dataclass
class ExtractionResult:
    source_file: str
    sha256: str
    taxpayer_name: str | None
    ein: str | None
    pages: list[dict]
    properties: list[PropertyResult]
    summary: dict[str, CellValue]
    warnings: list[str]
    checks: list[dict]

    @property
    def method(self) -> str:
        used = sorted({m for p in self.pages if p.get("form_page")
                       for m in (p.get("method") or "").split("+") if m and m != "empty"})
        return "+".join(used) if used else "none"

    def to_output(self) -> list[dict]:
        """Exactly the shape of the provided 8825_output.json."""
        return [output_record(p.name, p.address, p.values()) for p in self.properties]

    def to_report(self) -> dict:
        """Full diagnostic report: provenance per cell, validation, warnings."""
        return {
            "source_file": self.source_file,
            "sha256": self.sha256,
            "extraction_method": self.method,
            "taxpayer_name": self.taxpayer_name,
            "ein": self.ein,
            "pages": self.pages,
            "properties": [{
                "property_name": p.name, "property_address": p.address, "page": p.page,
                "lines": {c: cv.as_dict() for c, cv in p.lines.items() if cv.raw is not None},
            } for p in self.properties],
            "summary": {c: cv.as_dict() for c, cv in self.summary.items()},
            "validation": {"summary": summarize(self.checks), "checks": self.checks},
            "warnings": self.warnings,
        }


def _pick(reported, computed):
    return reported if reported is not None else computed


def output_record(name: str, address: str | None, vals: dict[str, int | None]) -> dict:
    """One property in the output JSON format. Shared by the CLI and the API export."""
    computed = computed_totals(vals)
    return {
        "property_name": name,
        "property_address": address or "",
        "income_line_items": {d.key: vals.get(d.code) or 0 for d in INCOME_LINES},
        "expense_line_items": {d.key: vals.get(d.code) or 0 for d in EXPENSE_LINES},
        "totals": {
            # Reported value from the form; computed value if the line was left blank.
            "total_rental_income": _pick(vals.get("2c"), computed["2c"]),
            "total_expenses": _pick(vals.get("18"), computed["18"]),
            "net_income": _pick(vals.get("19"), computed["19"]),
        },
    }


# --------------------------------------------------------------------------- #
# File-level checks
# --------------------------------------------------------------------------- #
def _check_file(path: str) -> str:
    if not os.path.isfile(path):
        raise errors.InputFileError(f"file not found: {path}")
    size = os.path.getsize(path)
    if size == 0:
        raise errors.InputFileError("file is empty")
    if size > MAX_FILE_BYTES:
        raise errors.InputFileError(f"file is {size / 1e6:.1f} MB; limit is {MAX_FILE_BYTES / 1e6:.0f} MB")
    with open(path, "rb") as fh:
        head = fh.read(1024)
        fh.seek(0)
        digest = hashlib.sha256(fh.read()).hexdigest()
    if b"%PDF-" not in head:
        raise errors.NotAPdfError("file does not start with a PDF header (%PDF-)")
    return digest


def _open(path: str, password: str | None):
    try:
        reader = PdfReader(path, strict=False)
    except (PdfReadError, ValueError, OSError) as exc:
        raise errors.CorruptPdfError(f"PDF could not be parsed: {exc}") from exc
    if reader.is_encrypted:
        # Many "protected" PDFs only have an owner password and open with "".
        try:
            ok = reader.decrypt(password or "")
        except Exception as exc:
            raise errors.EncryptedPdfError(f"PDF is encrypted and could not be decrypted: {exc}") from exc
        if not ok:
            raise errors.EncryptedPdfError("PDF is password protected; supply the password")
    try:
        n = len(reader.pages)
    except (PdfReadError, FileNotDecryptedError, KeyError) as exc:
        raise errors.CorruptPdfError(f"page tree is unreadable: {exc}") from exc
    if n == 0:
        raise errors.CorruptPdfError("PDF has no pages")
    if n > MAX_PAGES:
        raise errors.InputFileError(f"PDF has {n} pages; limit is {MAX_PAGES}")
    try:
        plumber = pdfplumber.open(path, password=password or "")
    except Exception as exc:
        raise errors.CorruptPdfError(f"PDF text layer could not be opened: {exc}") from exc
    return reader, plumber


# --------------------------------------------------------------------------- #
# Page processing
# --------------------------------------------------------------------------- #
def _assign(tokens: list[Token], layout: PageLayout) -> dict:
    """Group tokens by the cell containing their centre point."""
    cells: dict = {}
    for t in tokens:
        key = layout.cell_at(t.box.cx, t.box.cy)
        if key is not None:
            cells.setdefault(key, []).append(t)
    return cells


def _resolve_cell(tokens: list[Token], numeric: bool, warnings: list[str], where: str) -> CellValue:
    """Pick the most trustworthy source for a cell and parse it."""
    by_source: dict[str, list[Token]] = {}
    for t in tokens:
        by_source.setdefault(t.source, []).append(t)
    ordered = sorted(by_source, key=SOURCE_PRIORITY.get)
    chosen = ordered[0]
    toks = sorted(by_source[chosen], key=lambda t: (round(t.box.top), t.box.x0))
    raw = ("" if numeric else " ").join(t.text for t in toks).strip()
    confs = [t.confidence for t in toks if t.confidence is not None]
    cv = CellValue(raw=raw, source=chosen, confidence=min(confs) if confs else None)

    if not numeric:
        cv.value = raw
        return cv
    try:
        cv.value, w = parse_amount(raw, from_ocr=(chosen == "ocr"))
        cv.warnings.extend(w)
    except AmountParseError as exc:
        cv.value = None
        cv.warnings.append(str(exc))
        warnings.append(f"{where}: {exc} (needs manual review)")
    if chosen == "ocr" and cv.confidence is not None and cv.confidence < OCR_LOW_CONFIDENCE:
        cv.warnings.append(f"low OCR confidence {cv.confidence}")
        warnings.append(f"{where}: low OCR confidence ({cv.confidence}); please verify '{raw}'")

    # Two sources disagree (e.g. stale widget over flattened text) -> surface it.
    for other in ordered[1:]:
        other_raw = "".join(t.text for t in by_source[other])
        try:
            other_val, _ = parse_amount(other_raw, from_ocr=(other == "ocr"))
        except AmountParseError:
            continue
        if other_val is not None and other_val != cv.value:
            msg = f"{where}: {chosen} value {cv.value} differs from {other} value {other_val}"
            cv.warnings.append(msg)
            warnings.append(msg)
    return cv


def _process_page(path, index, reader, plumber, ocr_mode, dpi, password, warnings):
    """Return (page_info, layout, cells) or (page_info, None, None) for non-8825 pages."""
    ppage, pl_page = reader.pages[index], plumber.pages[index]
    info = {"page": index + 1, "form_page": False, "method": None}
    width, height = float(pl_page.width), float(pl_page.height)

    quality = text_layer_quality(pl_page)
    info["text_layer"] = {k: v for k, v in quality.items() if k != "text"}
    widgets = widget_tokens(ppage)
    ocr_page = None

    if quality["usable"]:
        kind = detect_page_kind(quality["text"])
        words = text_words(pl_page)
    else:
        kind, words = None, []
        if ocr_mode == "off":
            info["skipped"] = "no usable text layer and OCR disabled"
            return info, None, None
        if not ocr_available():
            info["needs_ocr"] = True
            return info, None, None
        ocr_page = OcrPage(path, index + 1, width, dpi=dpi, password=password)
        words = ocr_page.words()
        kind = detect_page_kind(" ".join(w["text"] for w in words))

    if kind is None:
        return info, None, None

    layout = calibrate(kind, words, width, height)
    info.update(form_page=True, kind=kind, calibration=layout.calibration)
    cal = layout.calibration
    if cal["method"] == "template_default":
        warnings.append(f"page {index + 1}: only {cal['anchors_matched']}/{cal['anchors_total']} layout anchors "
                        "found; using fixed template positions, results may be misaligned")

    tokens: list[Token] = list(widgets)
    if quality["usable"]:
        tokens += text_tokens(words)
    cells = _assign(tokens, layout)
    grid_found = any(k[0] == "grid" for k in cells)

    # OCR cell-by-cell when forced, when the page is image-only, or when a
    # text page has no values but carries a large image (hybrid scan).
    want_ocr = ocr_mode == "force" or ocr_page is not None or (
        not grid_found and quality["image_coverage"] > 0.5 and ocr_mode == "auto")
    if want_ocr:
        if not ocr_available():
            warnings.append(f"page {index + 1}: OCR needed but Tesseract is not installed")
        else:
            ocr_page = ocr_page or OcrPage(path, index + 1, width, dpi=dpi, password=password)
            for key, box in layout.cells.items():
                tok = ocr_page.read_cell(box, numeric=key[0] in ("grid", "summary"))
                if tok:
                    cells.setdefault(key, []).append(tok)

    sources = sorted({t.source for toks in cells.values() for t in toks}, key=SOURCE_PRIORITY.get)
    info["method"] = "+".join(sources) if sources else "empty"
    return info, layout, cells


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def extract_8825(path: str, *, ocr: str = "auto", dpi: int = 300, password: str | None = None) -> ExtractionResult:
    """Extract every property's income/expenses from a Form 8825 PDF.

    ocr: "auto" (only when a page has no usable text layer), "force", or "off".
    """
    if ocr not in ("auto", "force", "off"):
        raise ValueError("ocr must be auto|force|off")
    digest = _check_file(path)
    reader, plumber = _open(path, password)
    warnings: list[str] = []
    pages_info: list[dict] = []
    properties: list[PropertyResult] = []
    summary: dict[str, CellValue] = {}
    header: dict[str, str] = {}
    next_letter = 0
    letters = string.ascii_uppercase

    try:
        for i in range(len(reader.pages)):
            try:
                info, layout, cells = _process_page(path, i, reader, plumber, ocr, dpi, password, warnings)
            except errors.ExtractionError:
                raise
            except Exception as exc:  # isolate a single bad page
                log.exception("page %s failed", i + 1)
                pages_info.append({"page": i + 1, "form_page": False, "error": str(exc)})
                warnings.append(f"page {i + 1}: could not be processed ({exc})")
                continue
            pages_info.append(info)
            if layout is None:
                continue

            def cell(key, numeric, where):
                toks = cells.get(key)
                return _resolve_cell(toks, numeric, warnings, where) if toks else CellValue()

            if layout.kind == "page1":
                if header:
                    warnings.append(f"page {i + 1}: a second 8825 page 1 was found; its properties are appended")
                for key in ("name", "ein"):
                    cv = cell((key,), False, f"page {i + 1} {key}")
                    if cv.value and key not in header:
                        header[key] = cv.value
                for d in SUMMARY_LINES:
                    cv = cell(("summary", d.code), True, f"line {d.code}")
                    if d.code == "20b" and isinstance(cv.value, int) and cv.value < 0:
                        cv.value = -cv.value      # the form prints 20b inside ( ); it is a positive total
                    summary.setdefault(d.code, cv)

            n_cols = 4
            col_names = []
            for ci in range(n_cols):
                if layout.kind == "page1":
                    col_names.append(letters[ci])
                else:
                    typed = cell(("col_letter", ci), False, "column letter").value
                    col_names.append(typed.strip().upper() if typed else None)
            if layout.kind == "page1":
                next_letter = max(next_letter, 4)

            for ci in range(n_cols):
                lines = {d.code: cell(("grid", ci, d.code), True,
                                      f"page {i + 1} col {ci + 1} line {d.code}") for d in PROPERTY_LINES}
                address = cell(("address", ci), False, "address").value or None
                if address is None and all(cv.raw is None for cv in lines.values()):
                    continue                       # empty column
                name = col_names[ci]
                if not name:
                    name = letters[next_letter] if next_letter < 26 else f"P{next_letter + 1}"
                    next_letter += 1
                properties.append(PropertyResult(name=name, address=address, page=i + 1, column=ci, lines=lines))
    finally:
        plumber.close()

    form_pages = [p for p in pages_info if p.get("form_page")]
    if not form_pages:
        if any(p.get("skipped") for p in pages_info):
            raise errors.NoTextLayerError("PDF has no usable text layer (scanned?) and OCR is disabled")
        if any(p.get("needs_ocr") for p in pages_info):
            raise errors.OcrUnavailableError("PDF has no usable text layer (scanned?) and Tesseract OCR is not installed")
        raise errors.NotForm8825Error("no Form 8825 page found in the document")
    if not properties:
        raise errors.NoDataFoundError("Form 8825 found but no property values could be read")

    ein = header.get("ein")
    if ein and not _valid_ein(ein):
        warnings.append(f"EIN '{ein}' is not in the NN-NNNNNNN format")

    checks = validate_form({p.name: p.values() for p in properties},
                           {c: (cv.value if isinstance(cv.value, int) else None) for c, cv in summary.items()})
    return ExtractionResult(
        source_file=os.path.basename(path), sha256=digest,
        taxpayer_name=header.get("name"), ein=ein, pages=pages_info,
        properties=properties, summary=summary, warnings=warnings, checks=checks,
    )


def _valid_ein(ein: str) -> bool:
    digits = ein.replace("-", "")
    return digits.isdigit() and len(digits) == 9
