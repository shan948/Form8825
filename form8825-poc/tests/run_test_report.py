"""Task 4.3 - run every manifest case and write CSV test results.

    python tests/run_test_report.py            # -> test_results/test_results.csv + test_summary.csv
    python tests/run_test_report.py --no-ocr   # skip the slow scanned case

test_results.csv (one row per check)
    run_id, run_at, test_file, check_type, property, field_or_rule, line,
    expected, actual, difference, status, extraction_method, notes
  check_type:
    field_match     every JSON field vs the expected file         (4.1)
    arithmetic      2c = 2a+2b, 18 = sum(3..17), 19 = 2c-18        (4.2)
    form_rule       20a, 20b, 23, grand total net income           (4.2)
    error_handling  bad input raises the expected typed error
    validation      the file's overall validation status is as expected

test_summary.csv (one row per test file)
    run_id, test_file, extraction_method, properties, checks, passed, failed, status, seconds, note
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import (ROOT, arithmetic_checks, case_path, compare_property, grand_total,  # noqa: E402
                     load_expected, load_manifest, tesseract_available)

from extractor import ExtractionError, extract_8825  # noqa: E402

RESULT_COLS = ["run_id", "run_at", "test_file", "check_type", "property", "field_or_rule", "line",
               "expected", "actual", "difference", "status", "extraction_method", "notes"]
SUMMARY_COLS = ["run_id", "test_file", "extraction_method", "properties", "checks", "passed", "failed",
                "status", "seconds", "note"]


def _diff(e, a):
    return a - e if isinstance(e, int) and isinstance(a, int) and not isinstance(e, bool) else ""


def run(include_ocr: bool = True, out_dir: str | None = None) -> tuple[str, str, bool]:
    out_dir = out_dir or os.path.join(ROOT, "test_results")
    os.makedirs(out_dir, exist_ok=True)
    run_id = uuid.uuid4().hex[:8]
    run_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows, summary = [], []

    for case in load_manifest():
        name = os.path.basename(case["input"])
        base = {"run_id": run_id, "run_at": run_at, "test_file": name}
        if case.get("ocr") and not (include_ocr and tesseract_available()):
            summary.append({"run_id": run_id, "test_file": name, "status": "SKIPPED", "note": "OCR case skipped"})
            continue
        start = time.time()
        case_rows = []

        if "expect_error" in case:
            try:
                extract_8825(case_path(case["input"]))
                actual, note = "no error", "expected an error but extraction succeeded"
            except ExtractionError as exc:
                actual, note = exc.code, exc.message
            case_rows.append({**base, "check_type": "error_handling", "field_or_rule": "raises typed error",
                              "expected": case["expect_error"], "actual": actual, "difference": "",
                              "status": "PASS" if actual == case["expect_error"] else "FAIL",
                              "extraction_method": "", "notes": note})
            method, n_props = "", 0
        else:
            result = extract_8825(case_path(case["input"]))
            method = result.method
            got, exp = result.to_output(), load_expected(case)
            n_props = len(got)
            fuzzy = bool(case.get("ocr"))
            exp_by_name = {p["property_name"]: p for p in exp}
            got_by_name = {p["property_name"]: p for p in got}
            for pname in sorted(exp_by_name.keys() | got_by_name.keys()):
                e, a = exp_by_name.get(pname), got_by_name.get(pname)
                if e is None or a is None:
                    case_rows.append({**base, "check_type": "field_match", "property": pname,
                                      "field_or_rule": "property present", "expected": e is not None,
                                      "actual": a is not None, "status": "FAIL", "extraction_method": method})
                    continue
                for r in compare_property(a, e, fuzzy_address=fuzzy):
                    case_rows.append({**base, "check_type": "field_match", "property": pname,
                                      "field_or_rule": r["field"], "expected": r["expected"], "actual": r["actual"],
                                      "difference": _diff(r["expected"], r["actual"]), "status": r["status"],
                                      "extraction_method": method,
                                      "notes": "address compared ignoring punctuation (OCR)"
                                      if fuzzy and r["field"] == "property_address" else ""})
                for r in arithmetic_checks(a):
                    # On the deliberately broken file a FAIL here is the *expected* outcome.
                    planted = [pname, r["line"]] in case.get("expect_failed_rules", [])
                    case_rows.append({**base, "check_type": "arithmetic", "property": pname,
                                      "field_or_rule": r["rule"], "line": r["line"], "expected": r["expected"],
                                      "actual": r["actual"], "difference": _diff(r["expected"], r["actual"]),
                                      "status": ("PASS" if r["status"] == "FAIL" else "FAIL") if planted else r["status"],
                                      "extraction_method": method,
                                      "notes": "planted error: mismatch expected" if planted else ""})
            for c in result.checks:
                if c["scope"] != "form":
                    continue
                planted = [None, c["line"]] in case.get("expect_failed_rules", [])
                ok = (c["status"] == "fail") if planted else (c["status"] != "fail")
                case_rows.append({**base, "check_type": "form_rule", "field_or_rule": c["rule"], "line": c["line"],
                                  "expected": c["expected"], "actual": c["actual"],
                                  "difference": c["difference"] if c["difference"] is not None else "",
                                  "status": "PASS" if ok else "FAIL", "extraction_method": method,
                                  "notes": "planted error: mismatch expected" if planted else c["message"]})
            case_rows.append({**base, "check_type": "form_rule", "field_or_rule": "grand total vs expected file",
                              "line": "19*", "expected": grand_total(exp), "actual": grand_total(got),
                              "difference": grand_total(got) - grand_total(exp),
                              "status": "PASS" if grand_total(got) == grand_total(exp) else "FAIL",
                              "extraction_method": method})
            has_fail = any(c["status"] == "fail" for c in result.checks)
            want_fail = case["expect_validation"] == "fail"
            case_rows.append({**base, "check_type": "validation", "field_or_rule": "overall validation status",
                              "expected": case["expect_validation"], "actual": "fail" if has_fail else "pass",
                              "status": "PASS" if has_fail == want_fail else "FAIL", "extraction_method": method,
                              "notes": case.get("note", "")})

        rows += case_rows
        failed = sum(r["status"] == "FAIL" for r in case_rows)
        summary.append({"run_id": run_id, "test_file": name, "extraction_method": method, "properties": n_props,
                        "checks": len(case_rows), "passed": len(case_rows) - failed, "failed": failed,
                        "status": "PASS" if failed == 0 else "FAIL", "seconds": round(time.time() - start, 2),
                        "note": case.get("note", "")})

    results_path = os.path.join(out_dir, "test_results.csv")
    summary_path = os.path.join(out_dir, "test_summary.csv")
    for path, cols, data in ((results_path, RESULT_COLS, rows), (summary_path, SUMMARY_COLS, summary)):
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, restval="")
            w.writeheader()
            w.writerows(data)

    all_ok = all(s["status"] in ("PASS", "SKIPPED") for s in summary)
    for s in summary:
        print(f"{s['status']:8} {s['test_file']:40} {s.get('passed', '')}/{s.get('checks', '')} "
              f"{s.get('extraction_method', '')}")
    print(f"\n{len(rows)} checks written to {results_path}")
    return results_path, summary_path, all_ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--out-dir")
    args = ap.parse_args()
    _, _, ok = run(include_ocr=not args.no_ocr, out_dir=args.out_dir)
    raise SystemExit(0 if ok else 1)
