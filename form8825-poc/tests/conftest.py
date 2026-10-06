import functools
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import case_path, load_manifest, tesseract_available  # noqa: E402

from extractor import extract_8825  # noqa: E402

MANIFEST = load_manifest()
POSITIVE = [c for c in MANIFEST if "expect_error" not in c]
NEGATIVE = [c for c in MANIFEST if "expect_error" in c]


def case_id(case):
    return os.path.basename(case["input"])


@functools.lru_cache(maxsize=None)
def extracted(input_name: str):
    """Extract each test PDF once per session (OCR takes ~25 s)."""
    return extract_8825(case_path(input_name))


def pytest_collection_modifyitems(config, items):
    if tesseract_available():
        return
    skip = pytest.mark.skip(reason="tesseract not installed")
    for item in items:
        if "ocr" in item.keywords:
            item.add_marker(skip)


