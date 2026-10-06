"""Command line entry point.

    python -m extractor samples/f8825.pdf                       # prints JSON
    python -m extractor samples/f8825.pdf -o out/8825_output.json --report out/report.json
    python -m extractor test_data/*.pdf --out-dir out/          # batch: <name>_output.json each

Exit codes: 0 ok, 1 extraction error, 2 validation failed (only with --strict).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from .errors import ExtractionError
from .extract import extract_8825
from .validate import summarize


def _write(path: str, data) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="extractor", description="Extract Form 8825 income and expenses to JSON")
    ap.add_argument("inputs", nargs="+", help="PDF file(s)")
    ap.add_argument("-o", "--output", help="output JSON path (single input only)")
    ap.add_argument("--out-dir", help="write <name>_output.json (+ _report.json) per input into this folder")
    ap.add_argument("--report", help="also write the diagnostic report (single input only)")
    ap.add_argument("--ocr", choices=["auto", "force", "off"], default="auto")
    ap.add_argument("--dpi", type=int, default=300, help="render DPI for OCR")
    ap.add_argument("--password", help="password for encrypted PDFs")
    ap.add_argument("--strict", action="store_true", help="exit 2 if arithmetic validation fails")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    if len(args.inputs) > 1 and (args.output or args.report):
        ap.error("-o/--report work with a single input; use --out-dir for batches")

    exit_code = 0
    for path in args.inputs:
        try:
            result = extract_8825(path, ocr=args.ocr, dpi=args.dpi, password=args.password)
        except ExtractionError as exc:
            print(f"[{exc.code}] {path}: {exc.message}", file=sys.stderr)
            exit_code = max(exit_code, 1)
            continue

        output, report = result.to_output(), result.to_report()
        status = summarize(result.checks)
        if args.out_dir:
            stem = os.path.splitext(os.path.basename(path))[0]
            _write(os.path.join(args.out_dir, f"{stem}_output.json"), output)
            _write(os.path.join(args.out_dir, f"{stem}_report.json"), report)
        elif args.output:
            _write(args.output, output)
        else:
            json.dump(output, sys.stdout, indent=2)
            print()
        if args.report:
            _write(args.report, report)

        print(f"{os.path.basename(path)}: {len(output)} propert{'y' if len(output) == 1 else 'ies'}, "
              f"method={result.method}, validation={status['status']} "
              f"({status['passed']} pass / {status['failed']} fail / {status['warnings']} warn)", file=sys.stderr)
        for w in result.warnings:
            print(f"  warning: {w}", file=sys.stderr)
        for c in result.checks:
            if c["status"] == "fail":
                print(f"  FAIL {c['property'] or 'form'} {c['rule']}: {c['message']}", file=sys.stderr)
        if args.strict and status["status"] == "fail":
            exit_code = max(exit_code, 2)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
