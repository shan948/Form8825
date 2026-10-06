"""Turn the raw text found in a form cell into an integer dollar amount."""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Characters OCR commonly confuses with digits in numeric cells.
_OCR_DIGIT_FIXES = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0",
                                   "l": "1", "I": "1", "|": "1", "i": "1",
                                   "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2"})
_EMPTY_MARKERS = {"", "-", "--", "—", "–", "n/a", "N/A", "none", "0-"}
_NUMBER_RE = re.compile(r"^\d+(\.\d+)?$")


class AmountParseError(ValueError):
    pass


def parse_amount(raw: str | None, *, from_ocr: bool = False) -> tuple[int | None, list[str]]:
    """Parse '1,734,896', '3110', '(5,000)', '-5,000', '$1,200.50' ...

    Returns (value, warnings). value is None for an empty cell.
    Raises AmountParseError when the text can't be read as a number, so the
    caller can flag the cell for review instead of silently storing 0.
    """
    warnings: list[str] = []
    if raw is None:
        return None, warnings
    s = " ".join(str(raw).split())
    if s in _EMPTY_MARKERS:
        return None, warnings

    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    elif s.startswith("(") or s.endswith(")"):          # half a parenthesis, typical OCR loss
        negative, s = True, s.strip("()")
        warnings.append(f"unbalanced parentheses in {raw!r}; treated as negative")
    if s.startswith("-") or s.endswith("-"):
        negative, s = True, s.strip("-")

    s = s.replace("$", "").replace(",", "").replace(" ", "")
    if from_ocr:
        fixed = s.translate(_OCR_DIGIT_FIXES)
        if fixed != s:
            warnings.append(f"OCR character correction {s!r} -> {fixed!r}")
        s = fixed
        # OCR often reads a thousands comma as a period: "1.734.896"
        if s.count(".") > 1 or re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
            warnings.append(f"treated '.' as thousands separator in {raw!r}")
            s = s.replace(".", "")

    if from_ocr and "," in raw and not re.fullmatch(r"[($-]*\d{1,3}(,\d{3})+(\.\d+)?[)-]*", raw.strip().strip(".")):
        warnings.append(f"unusual digit grouping in OCR text {raw!r}; verify")

    if not _NUMBER_RE.match(s):
        raise AmountParseError(f"cannot parse amount from {raw!r}")

    try:
        value = Decimal(s)
    except InvalidOperation as exc:  # pragma: no cover - guarded by regex
        raise AmountParseError(f"cannot parse amount from {raw!r}") from exc

    if value != value.to_integral_value():
        warnings.append(f"cents found in {raw!r}; rounded to whole dollars")
    result = int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return (-result if negative else result), warnings


def format_amount(value: int | None) -> str:
    """Form-style formatting used when we *write* test PDFs."""
    if value is None:
        return ""
    return f"({abs(value):,})" if value < 0 else f"{value:,}"
