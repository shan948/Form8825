"""Generate Form 8825 test PDFs and their expected JSON from ONE source file.

    python test_data/generate_test_pdfs.py

Source: test_data/source_data.json (simulated data). Template: samples/f8825.pdf
(the real IRS Rev. 12-2025 form). For each dataset we write

    <name>.pdf                 fillable: values in AcroForm widgets (like the sample)
    <name>_flattened.pdf       values drawn as page text, no form fields
    <name>_scanned.pdf         image-only (rasterised + noise) -> exercises OCR
    <name>_expected.json       expected extractor output, computed from the source

plus negative cases (bad totals, encrypted, corrupt, not-a-PDF, not-8825) and
manifest.json, which the test-suite iterates over.
"""
from __future__ import annotations

import io
import json
import os
import random
import sys

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, BooleanObject, NameObject, TextStringObject
from reportlab.lib.colors import Color
from reportlab.pdfgen import canvas

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import pdfplumber  # noqa: E402

from extractor.layout import calibrate, detect_page_kind  # noqa: E402
from extractor.parse import format_amount  # noqa: E402
from extractor.schema import EXPENSE_LINES, INCOME_LINES  # noqa: E402
from extractor.validate import computed_totals  # noqa: E402

TEMPLATE = os.path.join(ROOT, "samples", "f8825.pdf")
INK = Color(0.55, 0.1, 0.1)          # dark red, like the sample's filled values


# --------------------------------------------------------------------------- #
# Source data -> cell values
# --------------------------------------------------------------------------- #
def with_totals(ds: dict) -> dict:
    """Return {"props": [...with 2c/18/19...], "summary": {20a..23}} computed from source lines."""
    props = []
    for p in ds["properties"]:
        lines = dict(p["lines"])
        lines.update(computed_totals(lines))
        props.append({**p, "lines": lines})
    s = dict(ds.get("summary", {}))
    s["20a"] = sum(p["lines"]["2c"] for p in props)
    s["20b"] = sum(p["lines"]["18"] for p in props)
    s["23"] = s["20a"] - s["20b"] + s.get("21", 0) + s.get("22a", 0)
    return {"props": props, "summary": s, "taxpayer_name": ds["taxpayer_name"], "ein": ds["ein"]}


def expected_json(filled: dict) -> list[dict]:
    out = []
    for p in filled["props"]:
        l = p["lines"]
        out.append({
            "property_name": p["name"],
            "property_address": p["address"],
            "income_line_items": {d.key: l.get(d.code, 0) for d in INCOME_LINES},
            "expense_line_items": {d.key: l.get(d.code, 0) for d in EXPENSE_LINES},
            "totals": {"total_rental_income": l["2c"], "total_expenses": l["18"], "net_income": l["19"]},
        })
    return out


def cell_values(filled: dict) -> dict[int, dict]:
    """{page_index: {cell_key: text}} - what should appear in each cell."""
    pages: dict[int, dict] = {0: {}}
    pages[0][("name",)] = filled["taxpayer_name"]
    pages[0][("ein",)] = filled["ein"]
    for code, v in filled["summary"].items():
        if v:
            pages[0][("summary", code)] = format_amount(abs(v) if code == "20b" else v)
    for i, p in enumerate(filled["props"]):
        page, col = (0, i) if i < 4 else (1, (i - 4) % 4)
        if i >= 8:
            raise ValueError("generator supports up to 8 properties (page 1 + one page 2)")
        cells = pages.setdefault(page, {})
        cells[("address", col)] = p["address"]
        if page == 1:
            cells[("col_letter", col)] = p["name"]
            cells[("row_letter", col)] = p["name"]
        for code, v in p["lines"].items():
            if v:                                   # preparers leave zero lines blank
                cells[("grid", col, code)] = format_amount(v)
    return pages


def template_layouts() -> dict[int, object]:
    layouts = {}
    with pdfplumber.open(TEMPLATE) as pdf:
        for i, page in enumerate(pdf.pages):
            kind = detect_page_kind(page.extract_text() or "")
            layouts[i] = calibrate(kind, page.extract_words(), float(page.width), float(page.height))
    return layouts


# --------------------------------------------------------------------------- #
# Writers
# --------------------------------------------------------------------------- #
def write_fillable(filled: dict, out_path: str, tamper=None) -> None:
    """Fill the template's own widgets (located by position, not by name)."""
    layouts = template_layouts()
    values = cell_values(filled)
    if tamper:
        tamper(values)
    writer = PdfWriter(clone_from=TEMPLATE)
    acro = writer._root_object["/AcroForm"]
    fields = ArrayObject()
    for pi, page in enumerate(writer.pages):
        layout = layouts[pi]
        mb = page.mediabox
        by_name = {}
        for ref in page.get("/Annots", []):
            annot = ref.get_object()
            if annot.get("/Subtype") != "/Widget":
                continue
            fields.append(ref)                      # register every widget as a field
            x0, y0, x1, y1 = (float(v) for v in annot["/Rect"])
            key = layout.cell_at((x0 + x1) / 2, float(mb.top) - (y0 + y1) / 2)
            text = values.get(pi, {}).get(key, "")
            annot[NameObject("/V")] = TextStringObject(text)
            if "/MaxLen" in annot and text:
                del annot["/MaxLen"]
            by_name[str(annot["/T"])] = text
        writer.update_page_form_field_values(page, by_name, auto_regenerate=False)
    acro[NameObject("/Fields")] = fields
    acro[NameObject("/NeedAppearances")] = BooleanObject(True)
    with open(out_path, "wb") as fh:
        writer.write(fh)


def write_flattened(filled: dict, out_path: str) -> None:
    """Template with widgets removed and values drawn into the page content."""
    layouts = template_layouts()
    values = cell_values(filled)
    reader = PdfReader(TEMPLATE)
    writer = PdfWriter()
    for pi, page in enumerate(reader.pages):
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(w, h))
        c.setFillColor(INK)
        c.setFont("Helvetica", 8)
        for key, text in values.get(pi, {}).items():
            box = layouts[pi].cells[key]
            baseline = h - box.bottom + 3
            if key[0] in ("grid", "summary"):
                c.drawRightString(box.x1 - 3, baseline, text)
            elif key[0] in ("address", "row_letter"):
                c.drawString(box.x0 + 2, h - box.top - 9, text)
            elif key[0] == "col_letter":
                c.drawCentredString(box.cx, baseline, text)
            else:
                c.drawString(box.x0 + 2, baseline, text)
        c.save()
        buf.seek(0)
        page.merge_page(PdfReader(buf).pages[0])
        if "/Annots" in page:
            del page["/Annots"]
        writer.add_page(page)
    with open(out_path, "wb") as fh:
        writer.write(fh)


def write_scanned(src_pdf: str, out_path: str, dpi: int = 200, seed: int = 7) -> None:
    """Rasterise to an image-only PDF with light noise, like an office scanner."""
    from pdf2image import convert_from_path
    from PIL import ImageFilter

    rng = random.Random(seed)
    images = []
    for img in convert_from_path(src_pdf, dpi=dpi, grayscale=True):
        img = img.filter(ImageFilter.GaussianBlur(0.4))
        px = img.load()
        for _ in range(img.width * img.height // 400):          # salt & pepper specks
            x, y = rng.randrange(img.width), rng.randrange(img.height)
            px[x, y] = rng.choice((0, 255))
        images.append(img.convert("L"))
    images[0].save(out_path, save_all=True, append_images=images[1:], resolution=dpi)


def write_negative_cases(out_dir: str, fillable_src: str) -> list[dict]:
    cases = []
    # Encrypted with a user password
    enc = os.path.join(out_dir, "f8825_encrypted.pdf")
    w = PdfWriter(clone_from=fillable_src)
    w.encrypt(user_password="secret", owner_password="owner", algorithm="AES-128")
    with open(enc, "wb") as fh:
        w.write(fh)
    cases.append({"input": os.path.basename(enc), "expect_error": "encrypted_pdf", "password_ok": "secret",
                  "expected": "multi_ABC_expected.json", "note": "user-password protected"})
    # Truncated file
    corrupt = os.path.join(out_dir, "f8825_corrupt.pdf")
    data = open(fillable_src, "rb").read()
    with open(corrupt, "wb") as fh:
        fh.write(data[:2000])
    cases.append({"input": os.path.basename(corrupt), "expect_error": "corrupt_pdf", "note": "truncated after 2 KB"})
    # Not a PDF at all
    fake = os.path.join(out_dir, "not_a_pdf.pdf")
    with open(fake, "w") as fh:
        fh.write("this is a text file renamed to .pdf\n")
    cases.append({"input": os.path.basename(fake), "expect_error": "not_a_pdf"})
    # A valid PDF that is not Form 8825
    other = os.path.join(out_dir, "not_8825.pdf")
    c = canvas.Canvas(other)
    c.setFont("Helvetica", 12)
    for i, line in enumerate(["Invoice #1043", "Consulting services .......... 4,500",
                              "This document is not a tax form."] * 10):
        c.drawString(72, 720 - 18 * i, line)
    c.save()
    cases.append({"input": os.path.basename(other), "expect_error": "not_form_8825"})
    return cases


def main() -> None:
    src = json.load(open(os.path.join(HERE, "source_data.json")))
    manifest = []
    for name, ds in src.items():
        filled = with_totals(ds)
        exp_name = f"{name}_expected.json"
        with open(os.path.join(HERE, exp_name), "w") as fh:
            json.dump(expected_json(filled), fh, indent=2)
            fh.write("\n")
        pdf = os.path.join(HERE, f"f8825_{name}.pdf")
        write_fillable(filled, pdf)
        flat = os.path.join(HERE, f"f8825_{name}_flattened.pdf")
        write_flattened(filled, flat)
        manifest += [
            {"input": os.path.basename(pdf), "expected": exp_name, "expect_method": "acroform",
             "expect_validation": "pass", "note": ds["description"]},
            {"input": os.path.basename(flat), "expected": exp_name, "expect_method": "text",
             "expect_validation": "pass", "note": "flattened: values in the text layer"},
        ]
        if name == "multi_ABC":
            scan = os.path.join(HERE, f"f8825_{name}_scanned.pdf")
            write_scanned(flat, scan)
            manifest.append({"input": os.path.basename(scan), "expected": exp_name, "expect_method": "ocr",
                             "expect_validation": "pass", "ocr": True,
                             "note": "image-only scan at 200 dpi with noise"})

            # Arithmetic errors a preparer (or a bad extraction) could introduce
            def tamper(values):
                values[0][("grid", 1, "18")] = format_amount(filled["props"][1]["lines"]["18"] + 1000)
                values[0][("summary", "20a")] = format_amount(filled["summary"]["20a"] - 500)
            bad = os.path.join(HERE, "f8825_multi_ABC_bad_totals.pdf")
            write_fillable(filled, bad, tamper=tamper)
            bad_expected = expected_json(filled)
            bad_expected[1]["totals"]["total_expenses"] += 1000
            with open(os.path.join(HERE, "multi_ABC_bad_totals_expected.json"), "w") as fh:
                json.dump(bad_expected, fh, indent=2)
                fh.write("\n")
            manifest.append({"input": os.path.basename(bad), "expected": "multi_ABC_bad_totals_expected.json",
                             "expect_method": "acroform", "expect_validation": "fail",
                             "expect_failed_rules": [["B", "18"], [None, "20a"]],
                             "note": "line 18 of B overstated by 1,000; line 20a understated by 500"})
            manifest += write_negative_cases(HERE, pdf)

    manifest.insert(0, {"input": "../samples/f8825.pdf", "expected": "../samples/8825_output.json",
                        "expect_method": "acroform", "expect_validation": "pass", "note": "provided sample"})
    with open(os.path.join(HERE, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    print(f"wrote {len(manifest)} test cases to {HERE}")


if __name__ == "__main__":
    main()
