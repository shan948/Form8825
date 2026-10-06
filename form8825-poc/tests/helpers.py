"""Helpers shared by the pytest suite and the CSV report generator."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_DATA = os.path.join(ROOT, "test_data")
sys.path.insert(0, ROOT)

from extractor.validate import computed_totals  # noqa: E402

GROUPS = ("income_line_items", "expense_line_items", "totals")


def load_manifest() -> list[dict]:
    with open(os.path.join(TEST_DATA, "manifest.json")) as fh:
        return json.load(fh)


def case_path(name: str) -> str:
    return os.path.normpath(os.path.join(TEST_DATA, name))


def load_expected(case: dict) -> list[dict]:
    with open(case_path(case["expected"])) as fh:
        return json.load(fh)


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def normalize_address(s: str) -> str:
    """OCR reads ',' as '.', so compare addresses on letters/digits only."""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def compare_property(actual: dict, expected: dict, fuzzy_address: bool = False) -> list[dict]:
    """Field-by-field comparison rows: {field, expected, actual, status}."""
    rows = []
    a_addr, e_addr = actual.get("property_address", ""), expected.get("property_address", "")
    same = normalize_address(a_addr) == normalize_address(e_addr) if fuzzy_address else a_addr == e_addr
    rows.append({"field": "property_address", "expected": e_addr, "actual": a_addr, "status": "PASS" if same else "FAIL"})
    for group in GROUPS:
        exp_g, act_g = expected.get(group, {}), actual.get(group, {})
        for key in list(exp_g) + [k for k in act_g if k not in exp_g]:
            e, a = exp_g.get(key), act_g.get(key)
            rows.append({"field": f"{group}.{key}", "expected": e, "actual": a, "status": "PASS" if e == a else "FAIL"})
    return rows


def arithmetic_checks(prop: dict) -> list[dict]:
    """Recompute lines 2c, 18, 19 from the extracted line items (Task 4.2)."""
    inc, exp, tot = prop["income_line_items"], prop["expense_line_items"], prop["totals"]
    total_income = inc["gross_rents"] + inc["other_income"]
    total_expense = sum(exp.values())
    net = total_income - total_expense
    out = []
    for rule, line, expected, actual in [
        ("total_income = 2a + 2b", "2c", total_income, tot["total_rental_income"]),
        ("total_expenses = sum(3..17)", "18", total_expense, tot["total_expenses"]),
        ("net_income = total_income - total_expenses", "19", net, tot["net_income"]),
    ]:
        out.append({"rule": rule, "line": line, "expected": expected, "actual": actual,
                    "status": "PASS" if expected == actual else "FAIL"})
    return out


def grand_total(props: list[dict]) -> int:
    return sum(p["totals"]["net_income"] for p in props)


__all__ = ["computed_totals"]
