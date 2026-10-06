"""Task 4.1 - the extractor produces the expected JSON for every property of every test file."""
import pytest
from conftest import NEGATIVE, POSITIVE, case_id, extracted
from helpers import case_path, compare_property, load_expected

from extractor import extract_8825
from extractor.errors import ExtractionError


def _params(cases):
    return [pytest.param(c, id=case_id(c), marks=[pytest.mark.ocr] if c.get("ocr") else []) for c in cases]


@pytest.mark.parametrize("case", _params(POSITIVE))
def test_property_count_and_names(case):
    got = extracted(case["input"]).to_output()
    exp = load_expected(case)
    assert [p["property_name"] for p in got] == [p["property_name"] for p in exp]


@pytest.mark.parametrize("case", _params(POSITIVE))
def test_every_field_matches_expected(case):
    got = extracted(case["input"]).to_output()
    exp = load_expected(case)
    failures = []
    for a, e in zip(got, exp):
        for row in compare_property(a, e, fuzzy_address=bool(case.get("ocr"))):
            if row["status"] != "PASS":
                failures.append(f"{e['property_name']}.{row['field']}: expected {row['expected']!r}, got {row['actual']!r}")
    assert not failures, "\n".join(failures)


@pytest.mark.parametrize("case", _params([c for c in POSITIVE if not c.get("ocr")]))
def test_exact_json_match(case):
    """Non-OCR inputs must reproduce the expected file byte-for-byte (as parsed JSON)."""
    assert extracted(case["input"]).to_output() == load_expected(case)


@pytest.mark.parametrize("case", _params(POSITIVE))
def test_extraction_method(case):
    assert extracted(case["input"]).method == case["expect_method"]


@pytest.mark.parametrize("case", [pytest.param(c, id=case_id(c)) for c in NEGATIVE])
def test_failure_modes_raise_typed_errors(case):
    with pytest.raises(ExtractionError) as exc:
        extract_8825(case_path(case["input"]))
    assert exc.value.code == case["expect_error"]


def test_encrypted_pdf_opens_with_password():
    case = next(c for c in NEGATIVE if c.get("password_ok"))
    result = extract_8825(case_path(case["input"]), password=case["password_ok"])
    assert result.to_output() == load_expected(case)


def test_scanned_pdf_with_ocr_disabled_reports_missing_text_layer():
    with pytest.raises(ExtractionError) as exc:
        extract_8825(case_path("f8825_multi_ABC_scanned.pdf"), ocr="off")
    assert exc.value.code == "no_text_layer"


def test_sample_text_layer_is_detected_as_usable():
    report = extracted("../samples/f8825.pdf").to_report()
    page1 = report["pages"][0]
    assert page1["text_layer"]["usable"] is True
    assert page1["calibration"]["anchors_matched"] == page1["calibration"]["anchors_total"]


@pytest.mark.ocr
def test_scanned_pdf_text_layer_is_detected_as_unusable():
    report = extracted("f8825_multi_ABC_scanned.pdf").to_report()
    assert report["pages"][0]["text_layer"]["usable"] is False
    assert report["extraction_method"] == "ocr"
