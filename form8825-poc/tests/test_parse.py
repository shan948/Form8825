import pytest

from extractor.parse import AmountParseError, parse_amount


@pytest.mark.parametrize("raw, expected", [
    ("1,734,896", 1734896), ("3110", 3110), ("(5,000)", -5000), ("-5,000", -5000),
    ("$1,200", 1200), ("1,200.50", 1201), ("", None), ("-", None), (None, None), ("  17,540 ", 17540),
])
def test_parse_amount(raw, expected):
    assert parse_amount(raw)[0] == expected


@pytest.mark.parametrize("raw, expected", [("1O,5OO", 10500), ("1.734.896", 1734896), ("l,200", 1200)])
def test_ocr_corrections(raw, expected):
    value, warnings = parse_amount(raw, from_ocr=True)
    assert value == expected and warnings


@pytest.mark.parametrize("raw", ["12a45", "abc", "1,2,3x"])
def test_unparseable_raises(raw):
    with pytest.raises(AmountParseError):
        parse_amount(raw)
