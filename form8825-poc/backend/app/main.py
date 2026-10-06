"""Form 8825 extraction API.

    uvicorn backend.app.main:app --reload --port 8000        (from the repo root)

Endpoints (all JSON, prefix /api):
    GET    /health
    POST   /documents                       upload a PDF (multipart "file") -> extract -> persist
    GET    /documents                       list uploads with validation status
    GET    /documents/{id}                  properties, line items, live validation
    GET    /documents/{id}/history          audit trail (extraction + manual edits)
    GET    /documents/{id}/export           output JSON (?source=current|extracted)
    GET    /documents/{id}/file             the original PDF
    DELETE /documents/{id}
    PATCH  /line-items/{id}                 {value, expected_version, changed_by, reason}
    POST   /line-items/{id}/revert          back to the extracted value
    PATCH  /properties/{id}                 {address, changed_by, reason}
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import services
from .db import get_db, init_db
from .db import UPLOAD_DIR
from .models import LineItem
from .schemas import (AuditOut, DocumentDetail, DocumentSummary, LineItemUpdate, LineItemUpdateResult,
                      PropertyUpdate)

MAX_UPLOAD = 20 * 1024 * 1024


@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield


app = FastAPI(title="Form 8825 Extraction API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(services.NotFound)
async def _not_found(_req, exc):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(services.ConflictError)
async def _conflict(_req, exc):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/documents", response_model=DocumentDetail, status_code=201,
          responses={422: {"description": "File is not a readable Form 8825"}})
async def upload(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read(MAX_UPLOAD + 1)
    if len(content) > MAX_UPLOAD:
        raise HTTPException(413, f"file larger than {MAX_UPLOAD // (1024 * 1024)} MB")
    if not content:
        raise HTTPException(422, {"code": "input_file_error", "message": "empty upload"})
    doc, duplicate = services.ingest(db, content, file.filename or "upload.pdf")
    if doc.status == "failed":
        raise HTTPException(422, {"code": doc.error_code, "message": doc.error_message, "document_id": doc.id})
    body = services.document_detail(doc, duplicate=duplicate)
    return JSONResponse(status_code=200 if duplicate else 201,
                        content=DocumentDetail.model_validate(body).model_dump(mode="json"))


@app.get("/api/documents", response_model=list[DocumentSummary])
def list_documents(db: Session = Depends(get_db)):
    return services.list_documents(db)


@app.get("/api/documents/{doc_id}", response_model=DocumentDetail)
def get_document(doc_id: int, db: Session = Depends(get_db)):
    return services.document_detail(services.get_document(db, doc_id))


@app.get("/api/documents/{doc_id}/history", response_model=list[AuditOut])
def get_history(doc_id: int, db: Session = Depends(get_db)):
    return services.history(db, services.get_document(db, doc_id))


@app.get("/api/documents/{doc_id}/export")
def export(doc_id: int, source: Literal["current", "extracted"] = Query("current"), db: Session = Depends(get_db)):
    doc = services.get_document(db, doc_id)
    if doc.status != "extracted":
        raise HTTPException(409, "document has no extraction result")
    stem = os.path.splitext(doc.filename)[0]
    return JSONResponse(services.export_json(doc, source),
                        headers={"Content-Disposition": f'attachment; filename="{stem}_output.json"'})


@app.get("/api/documents/{doc_id}/file")
def get_file(doc_id: int, db: Session = Depends(get_db)):
    doc = services.get_document(db, doc_id)
    print("Stored path:",doc.stored_path)
    file_path = os.path.join(UPLOAD_DIR, doc.stored_path)

    print("Full path:", file_path)
    if not os.path.exists(doc.stored_path):
        raise HTTPException(404, "stored file missing")
    return FileResponse(doc.stored_path, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{doc.filename}"'})


@app.delete("/api/documents/{doc_id}", status_code=204)
def delete(doc_id: int, db: Session = Depends(get_db)):
    services.delete_document(db, services.get_document(db, doc_id))


def _update_result(db: Session, li: LineItem) -> dict:
    doc = services.get_document(db, li.document_id)
    db.refresh(doc)
    validation, grand = services.validation_for(doc)
    computed = None
    if li.property_id is not None:
        prop = next(p for p in services.document_detail(doc)["properties"] if p["id"] == li.property_id)
        computed = prop["computed"]
    return {"line_item": services.line_out(li), "property_computed": computed,
            "validation": validation, "grand_total_net_income": grand}


@app.patch("/api/line-items/{item_id}", response_model=LineItemUpdateResult,
           responses={409: {"description": "Version conflict"}})
def patch_line_item(item_id: int, body: LineItemUpdate, db: Session = Depends(get_db)):
    if body.value is not None and abs(body.value) > 10**12:
        raise HTTPException(422, "value out of range")
    li = services.update_line_item(db, item_id, body.value, body.expected_version, body.changed_by, body.reason)
    return _update_result(db, li)


@app.post("/api/line-items/{item_id}/revert", response_model=LineItemUpdateResult)
def revert_line_item(item_id: int, db: Session = Depends(get_db)):
    li = services.revert_line_item(db, item_id, actor="ui-user")
    return _update_result(db, li)


@app.patch("/api/properties/{prop_id}")
def patch_property(prop_id: int, body: PropertyUpdate, db: Session = Depends(get_db)):
    p = services.update_property(db, prop_id, body.address, body.changed_by, body.reason)
    return {"id": p.id, "label": p.label, "address": p.address, "extracted_address": p.extracted_address}


# Serve the built React app (frontend/dist) from the same origin when present.
_DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "frontend", "dist")
if os.path.isdir(_DIST):
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="ui")
