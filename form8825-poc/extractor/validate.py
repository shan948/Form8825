"""Arithmetic validation of Form 8825.

Works on plain {line_code: int | None} dicts so the same rules are used by the
extractor, the API (after manual edits) and the test suite.

Rules
  per property  2c = 2a + 2b
                18 = lines 3 through 17
                19 = 2c - 18
                lines 15/16 (reserved) should be empty
                expenses should not be negative
  per form      20a = sum(2c)      20b = sum(18)
                23  = 20a - 20b + 21 + 22a
                grand total net income = sum(19)
"""
from __future__ import annotations

from .schema import EXPENSE_LINES, INCOME_LINES, RESERVED_LINES

PASS, FAIL, WARN = "pass", "fail", "warn"


def _v(lines: dict, code: str) -> int:
    return lines.get(code) or 0


def computed_totals(lines: dict) -> dict:
    income = sum(_v(lines, d.code) for d in INCOME_LINES)
    expenses = sum(_v(lines, d.code) for d in EXPENSE_LINES + RESERVED_LINES)   # "lines 3 through 17"
    return {"2c": income, "18": expenses, "19": income - expenses}


def _check(scope, prop, rule, line, expected, actual, message=""):
    if actual is None:
        status = WARN
        message = message or f"line {line} not reported on form; computed value {expected:,}"
    else:
        status = PASS if expected == actual else FAIL
        if status == FAIL and not message:
            message = f"line {line} reported {actual:,} but components add up to {expected:,}"
    return {
        "scope": scope, "property": prop, "rule": rule, "line": line,
        "expected": expected, "actual": actual,
        "difference": None if actual is None else actual - expected,
        "status": status, "message": message,
    }


def validate_property(name: str, lines: dict) -> list[dict]:
    c = computed_totals(lines)
    checks = [
        _check("property", name, "total_income = 2a + 2b", "2c", c["2c"], lines.get("2c")),
        _check("property", name, "total_expenses = sum(lines 3-17)", "18", c["18"], lines.get("18")),
        _check("property", name, "net_income = 2c - 18", "19", c["19"], lines.get("19")),
    ]
    for d in RESERVED_LINES:
        if lines.get(d.code):
            checks.append({"scope": "property", "property": name, "rule": "reserved line empty",
                           "line": d.code, "expected": None, "actual": lines[d.code], "difference": None,
                           "status": WARN, "message": f"line {d.code} is reserved but has a value"})
    for d in EXPENSE_LINES:
        if (lines.get(d.code) or 0) < 0:
            checks.append({"scope": "property", "property": name, "rule": "expense not negative",
                           "line": d.code, "expected": None, "actual": lines[d.code], "difference": None,
                           "status": WARN, "message": f"{d.label} is negative"})
    return checks


def validate_form(properties: dict[str, dict], summary: dict) -> list[dict]:
    """properties: {"A": {line: value}}, summary: {"20a": .., "20b": .., "21": .., "22a": .., "23": ..}"""
    checks: list[dict] = []
    for name, lines in properties.items():
        checks.extend(validate_property(name, lines))

    totals = [computed_totals(l) for l in properties.values()]
    sum_income = sum(t["2c"] for t in totals)
    sum_expense = sum(t["18"] for t in totals)
    grand_net = sum(t["19"] for t in totals)

    checks.append(_check("form", None, "20a = sum(2c)", "20a", sum_income, summary.get("20a")))
    checks.append(_check("form", None, "20b = sum(18)", "20b", sum_expense, summary.get("20b")))
    expected_23 = sum_income - sum_expense + (summary.get("21") or 0) + (summary.get("22a") or 0)
    checks.append(_check("form", None, "23 = 20a - 20b + 21 + 22a", "23", expected_23, summary.get("23")))
    checks.append({"scope": "form", "property": None, "rule": "grand_total_net_income = sum(19)",
                   "line": "19*", "expected": grand_net, "actual": grand_net, "difference": 0,
                   "status": PASS, "message": f"grand total net income {grand_net:,}"})
    return checks


def summarize(checks: list[dict]) -> dict:
    fails = [c for c in checks if c["status"] == FAIL]
    warns = [c for c in checks if c["status"] == WARN]
    return {
        "status": FAIL if fails else (WARN if warns else PASS),
        "passed": sum(c["status"] == PASS for c in checks),
        "failed": len(fails),
        "warnings": len(warns),
    }
