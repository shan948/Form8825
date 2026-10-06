"""Task 4.2 - extracted totals (lines 2c, 18, 19) are arithmetically correct."""
import pytest
from conftest import POSITIVE, case_id, extracted
from helpers import arithmetic_checks, grand_total, load_expected

from extractor.validate import validate_form

GOOD = [c for c in POSITIVE if c["expect_validation"] == "pass"]


def _params(cases):
    return [pytest.param(c, id=case_id(c), marks=[pytest.mark.ocr] if c.get("ocr") else []) for c in cases]


@pytest.mark.parametrize("case", _params(GOOD))
def test_line_2c_18_19_are_accurate(case):
    for prop in extracted(case["input"]).to_output():
        for chk in arithmetic_checks(prop):
            assert chk["status"] == "PASS", f"{prop['property_name']} {chk['rule']}: {chk}"


@pytest.mark.parametrize("case", _params(GOOD))
def test_grand_total_net_income(case):
    got = extracted(case["input"]).to_output()
    assert grand_total(got) == grand_total(load_expected(case))


@pytest.mark.parametrize("case", _params(POSITIVE))
def test_validation_status(case):
    result = extracted(case["input"])
    statuses = {c["status"] for c in result.checks}
    expected = case["expect_validation"]
    assert ("fail" in statuses) == (expected == "fail")


def test_bad_totals_are_flagged_on_the_right_lines():
    case = next(c for c in POSITIVE if c.get("expect_failed_rules"))
    result = extracted(case["input"])
    failed = sorted([c["property"] or "", c["line"]] for c in result.checks if c["status"] == "fail")
    assert failed == sorted([p or "", line] for p, line in case["expect_failed_rules"])


def test_rules_on_hand_built_data():
    props = {"A": {"2a": 100, "2b": 20, "2c": 120, "3": 10, "14": 30, "18": 40, "19": 80}}
    summary = {"20a": 120, "20b": 40, "21": 5, "22a": -10, "23": 75}
    assert all(c["status"] == "pass" for c in validate_form(props, summary))

    props["A"]["18"] = 41                                        # wrong total expenses
    fails = [c["line"] for c in validate_form(props, summary) if c["status"] == "fail"]
    assert fails == ["18"]


def test_missing_total_is_warning_not_failure():
    checks = validate_form({"A": {"2a": 100, "3": 30}}, {})
    by_line = {c["line"]: c["status"] for c in checks if c["scope"] == "property"}
    assert by_line == {"2c": "warn", "18": "warn", "19": "warn"}
