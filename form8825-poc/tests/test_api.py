"""API: upload -> extract -> edit -> audit -> export."""
import json
import os
import tempfile
import warnings

import pytest

os.environ["F8825_DATA_DIR"] = tempfile.mkdtemp(prefix="f8825-api-")
warnings.filterwarnings("ignore", category=DeprecationWarning)

from fastapi.testclient import TestClient  # noqa: E402
from helpers import case_path  # noqa: E402

from backend.app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _upload(client, name):
    with open(case_path(name), "rb") as fh:
        return client.post("/api/documents", files={"file": (os.path.basename(name), fh, "application/pdf")})


@pytest.fixture(scope="module")
def doc(client):
    r = _upload(client, "f8825_multi_ABC.pdf")
    assert r.status_code == 201, r.text
    return r.json()


def _line(doc, prop, code):
    p = next(p for p in doc["properties"] if p["label"] == prop)
    return next(l for l in p["lines"] if l["line_code"] == code)


def test_upload_extracts_three_properties(doc):
    assert [p["label"] for p in doc["properties"]] == ["A", "B", "C"]
    assert doc["validation"]["status"] == "pass"
    assert doc["taxpayer_name"] == "Riverbend Holdings LLC"


def test_export_matches_expected_json(client, doc):
    exported = client.get(f"/api/documents/{doc['id']}/export").json()
    assert exported == json.load(open(case_path("multi_ABC_expected.json")))


def test_update_is_tracked_and_revalidated(client, doc):
    li = _line(doc, "A", "4")
    r = client.patch(f"/api/line-items/{li['id']}", json={"value": 2500, "expected_version": li["version"],
                                                          "reason": "receipt shows 2,500"})
    assert r.status_code == 200
    body = r.json()
    assert body["line_item"]["current_value"] == 2500 and body["line_item"]["extracted_value"] == 2150
    assert body["line_item"]["is_manual"] is True
    assert body["validation"]["status"] == "fail"             # 18 no longer ties
    assert body["property_computed"]["18"] == 502945 + 350

    hist = client.get(f"/api/documents/{doc['id']}/history").json()
    latest = hist[0]
    assert (latest["action"], latest["field"], latest["old_value"], latest["new_value"]) == ("updated", "4", "2150", "2500")
    assert latest["property_label"] == "A" and latest["reason"] == "receipt shows 2,500"

    exported = client.get(f"/api/documents/{doc['id']}/export").json()
    assert exported[0]["expense_line_items"]["auto_travel"] == 2500
    original = client.get(f"/api/documents/{doc['id']}/export?source=extracted").json()
    assert original[0]["expense_line_items"]["auto_travel"] == 2150


def test_stale_version_is_rejected(client, doc):
    li = _line(doc, "B", "2a")
    ok = client.patch(f"/api/line-items/{li['id']}", json={"value": 1, "expected_version": li["version"]})
    assert ok.status_code == 200
    stale = client.patch(f"/api/line-items/{li['id']}", json={"value": 2, "expected_version": li["version"]})
    assert stale.status_code == 409


def test_revert_restores_extracted_value(client, doc):
    li = _line(doc, "B", "2a")
    r = client.post(f"/api/line-items/{li['id']}/revert")
    assert r.json()["line_item"]["current_value"] == 1212000
    assert r.json()["line_item"]["is_manual"] is False
    hist = client.get(f"/api/documents/{doc['id']}/history").json()
    assert hist[0]["action"] == "reverted"


def test_address_update_is_audited(client, doc):
    pid = doc["properties"][2]["id"]
    r = client.patch(f"/api/properties/{pid}", json={"address": "4500 N Lakeview Dr, Chicago, IL 60614"})
    assert r.status_code == 200 and r.json()["extracted_address"] == "4500 Lakeview Dr, Chicago, IL 60614"
    assert client.get(f"/api/documents/{doc['id']}/history").json()[0]["field"] == "address"


def test_duplicate_upload_returns_existing(client, doc):
    r = _upload(client, "f8825_multi_ABC.pdf")
    assert r.status_code == 200 and r.json()["duplicate"] is True and r.json()["id"] == doc["id"]


@pytest.mark.parametrize("name, code", [("not_8825.pdf", "not_form_8825"), ("not_a_pdf.pdf", "not_a_pdf"),
                                         ("f8825_corrupt.pdf", "corrupt_pdf"), ("f8825_encrypted.pdf", "encrypted_pdf")])
def test_bad_uploads_return_422_and_are_recorded(client, name, code):
    r = _upload(client, name)
    assert r.status_code == 422 and r.json()["detail"]["code"] == code
    listed = {d["id"]: d for d in client.get("/api/documents").json()}
    assert listed[r.json()["detail"]["document_id"]]["status"] == "failed"


def test_unknown_ids_404(client):
    assert client.get("/api/documents/99999").status_code == 404
    assert client.patch("/api/line-items/99999", json={"value": 1}).status_code == 404


def test_delete(client):
    d = _upload(client, "f8825_multi_page2.pdf").json()
    assert len(d["properties"]) == 6
    assert client.delete(f"/api/documents/{d['id']}").status_code == 204
    assert client.get(f"/api/documents/{d['id']}").status_code == 404
