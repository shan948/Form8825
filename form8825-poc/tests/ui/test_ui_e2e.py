"""Task 4.4 - browser UI automation (Playwright) against the real FastAPI + built React app.

    cd frontend && npm run build && cd ..
    python -m pytest tests/ui -m ui
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIST = os.path.join(ROOT, "frontend", "dist", "index.html")
TEST_DATA = os.path.join(ROOT, "test_data")
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers") if os.path.isdir("/opt/pw-browsers") else None

pytestmark = pytest.mark.ui
playwright = pytest.importorskip("playwright.sync_api")


def _fmt(v):
    return f"({abs(v):,})" if v < 0 else (f"{v:,}" if v else "")


@pytest.fixture(scope="module")
def server():
    if not os.path.exists(DIST):
        pytest.skip("frontend not built (cd frontend && npm run build)")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "F8825_DATA_DIR": tempfile.mkdtemp(prefix="f8825-ui-")}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app.main:app", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{url}/api/health", timeout=1)
            break
        except OSError:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail("API did not start")
    yield url
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # browser binaries not installed
            pytest.skip(f"chromium unavailable: {exc}")
        yield b
        b.close()


@pytest.fixture
def page(browser, server):
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
    pg = ctx.new_page()
    pg.goto(server)
    yield pg
    ctx.close()


def upload(page, name):
    page.get_by_test_id("file-input").set_input_files(os.path.join(TEST_DATA, name))
    page.get_by_test_id("notice").wait_for()


def test_upload_shows_every_extracted_value(page):
    upload(page, "f8825_multi_ABC.pdf")
    expected = json.load(open(os.path.join(TEST_DATA, "multi_ABC_expected.json")))
    codes = {"gross_rents": "2a", "other_income": "2b", "advertising": "3", "auto_travel": "4",
             "cleaning_maintenance": "5", "commissions": "6", "insurance": "7", "interest": "8",
             "legal_professional": "9", "real_estate_taxes": "10", "repairs": "11", "utilities": "12",
             "wages_salaries": "13", "depreciation": "14", "other_deductions": "17",
             "total_rental_income": "2c", "total_expenses": "18", "net_income": "19"}
    for prop in expected:
        label = prop["property_name"]
        assert prop["property_address"] in page.get_by_test_id(f"address-{label}").inner_text()
        for group in ("income_line_items", "expense_line_items", "totals"):
            for key, value in prop[group].items():
                cell = page.get_by_test_id(f"cell-{label}-{codes[key]}")
                assert cell.inner_text().strip() == _fmt(value), f"{label} {key}"
    assert "Every total adds up." in page.get_by_test_id("verdict").inner_text()
    assert page.get_by_test_id("grand-total").inner_text() == _fmt(sum(p["totals"]["net_income"] for p in expected))


def test_edit_revalidates_and_is_tracked_then_revert(page):
    upload(page, "f8825_multi_ABC.pdf")                       # duplicate upload opens the same document
    page.get_by_test_id("cell-B-7").click()
    page.get_by_test_id("cell-B-7-input").fill("90,000")
    page.get_by_test_id("cell-B-7-input").press("Enter")

    page.get_by_test_id("cell-B-7-revert").wait_for()
    assert page.get_by_test_id("cell-B-7").inner_text() == "90,000"
    assert "don't add up" in page.get_by_test_id("verdict").inner_text()
    assert page.get_by_test_id("cell-B-18-check").inner_text() == "✗"
    history = page.get_by_test_id("history").inner_text()
    assert "property B, line 7" in history and "88,410" in history and "90,000" in history

    page.get_by_test_id("cell-B-7-revert").click()
    page.get_by_text("Every total adds up.").wait_for()
    assert page.get_by_test_id("cell-B-7").inner_text() == "88,410"
    assert page.get_by_test_id("history").inner_text().startswith("Reverted")


def test_invalid_amount_is_rejected_inline(page):
    upload(page, "f8825_multi_ABC.pdf")
    page.get_by_test_id("cell-A-3").click()
    page.get_by_test_id("cell-A-3-input").fill("12x")
    page.get_by_test_id("cell-A-3-input").press("Enter")
    assert "Enter whole dollars" in page.get_by_test_id("cell-A-3-error").inner_text()


def test_export_downloads_expected_json(page):
    upload(page, "f8825_multi_ABC.pdf")
    with page.expect_download() as dl:
        page.get_by_test_id("export").click()
    data = json.load(open(dl.value.path()))
    assert data == json.load(open(os.path.join(TEST_DATA, "multi_ABC_expected.json")))


def test_non_8825_upload_shows_reason(page):
    upload(page, "not_8825.pdf")
    assert "no Form 8825 page found" in page.get_by_test_id("notice").inner_text()
    page.get_by_test_id("failed-doc").wait_for()
