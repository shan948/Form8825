"""Persistence + domain logic. Routes stay thin; everything testable lives here."""
from __future__ import annotations

import hashlib
import json
import os
import sys

from sqlalchemy import func, select
from sqlalchemy.orm import Session

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from extractor import ExtractionError, extract_8825, output_record  # noqa: E402
from extractor.schema import LINES_BY_CODE, PROPERTY_LINES, SUMMARY_LINES  # noqa: E402
from extractor.validate import computed_totals, summarize, validate_form  # noqa: E402

from .db import UPLOAD_DIR  # noqa: E402
from .models import AuditLog, Document, LineItem, Property  # noqa: E402


class ConflictError(Exception):
    pass


class NotFound(Exception):
    pass


# --------------------------------------------------------------------------- #
# Ingest
# --------------------------------------------------------------------------- #
def ingest(db: Session, content: bytes, filename: str, actor: str = "system") -> tuple[Document, bool]:
    """Store the file, run extraction, persist results. Returns (document, is_duplicate).

    Failed extractions are persisted too (status=failed) so every upload is traceable;
    the caller turns them into a 422.
    """
    digest = hashlib.sha256(content).hexdigest()
    existing = db.scalar(select(Document).where(Document.sha256 == digest, Document.status == "extracted"))
    if existing:
        return existing, True

    path = os.path.join(UPLOAD_DIR, f"{digest}.pdf")
    with open(path, "wb") as fh:
        fh.write(content)

    doc = Document(filename=os.path.basename(filename or "upload.pdf"), sha256=digest, stored_path=path,
                   status="failed")
    db.add(doc)
    try:
        result = extract_8825(path)
    except ExtractionError as exc:
        doc.error_code, doc.error_message = exc.code, exc.message
        db.flush()
        db.add(AuditLog(document_id=doc.id, entity_type="document", entity_id=doc.id, action="failed",
                        new_value=exc.code, reason=exc.message, actor=actor))
        db.commit()
        return doc, False

    report = result.to_report()
    doc.status = "extracted"
    doc.taxpayer_name, doc.ein = result.taxpayer_name, result.ein
    doc.extraction_method = result.method
    doc.page_count = len(result.pages)
    doc.report_json = json.dumps(report)
    db.flush()

    for order, p in enumerate(result.properties):
        prop = Property(document_id=doc.id, label=p.name, address=p.address, extracted_address=p.address,
                        page=p.page, sort_order=order)
        db.add(prop)
        db.flush()
        for d in PROPERTY_LINES:
            db.add(_line_item(doc.id, prop.id, d, p.lines.get(d.code)))
    for d in SUMMARY_LINES:
        db.add(_line_item(doc.id, None, d, result.summary.get(d.code)))

    db.add(AuditLog(document_id=doc.id, entity_type="document", entity_id=doc.id, action="extracted",
                    new_value=json.dumps({"method": result.method, "properties": len(result.properties),
                                          "validation": summarize(result.checks)["status"]}),
                    actor=actor))
    db.commit()
    return doc, False


def _line_item(doc_id, prop_id, d, cv) -> LineItem:
    value = cv.value if cv is not None and isinstance(cv.value, int) else None
    return LineItem(
        document_id=doc_id, property_id=prop_id, line_code=d.code, field_key=d.key, section=d.section,
        extracted_value=value, current_value=value,
        raw_text=(cv.raw if cv else None), source=(cv.source if cv else None),
        confidence=(cv.confidence if cv else None),
        needs_review=bool(cv and cv.warnings),
    )


# --------------------------------------------------------------------------- #
# Read models
# --------------------------------------------------------------------------- #
def get_document(db: Session, doc_id: int) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None:
        raise NotFound(f"document {doc_id} not found")
    return doc


def _values(items) -> dict[str, int | None]:
    return {li.line_code: li.current_value for li in items}


def _by_property(doc: Document):
    grouped: dict[int | None, list[LineItem]] = {}
    for li in doc.line_items:
        grouped.setdefault(li.property_id, []).append(li)
    order = {d.code: i for i, d in enumerate(PROPERTY_LINES + SUMMARY_LINES)}
    for items in grouped.values():
        items.sort(key=lambda li: order.get(li.line_code, 99))
    return grouped


def validation_for(doc: Document) -> tuple[dict, int]:
    grouped = _by_property(doc)
    props = {p.label: _values(grouped.get(p.id, [])) for p in doc.properties}
    summary = _values(grouped.get(None, []))
    checks = validate_form(props, summary)
    grand = sum(computed_totals(v)["19"] for v in props.values())
    return {**summarize(checks), "checks": checks}, grand


def line_out(li: LineItem) -> dict:
    return {
        "id": li.id, "line_code": li.line_code, "field_key": li.field_key, "section": li.section,
        "label": LINES_BY_CODE[li.line_code].label, "extracted_value": li.extracted_value,
        "current_value": li.current_value, "raw_text": li.raw_text, "source": li.source,
        "confidence": li.confidence, "needs_review": li.needs_review, "is_manual": li.is_manual,
        "version": li.version,
    }


def document_detail(doc: Document, duplicate: bool = False) -> dict:
    grouped = _by_property(doc)
    validation, grand = validation_for(doc) if doc.status == "extracted" else (
        {"status": "fail", "passed": 0, "failed": 0, "warnings": 0, "checks": []}, 0)
    report = json.loads(doc.report_json) if doc.report_json else {}
    return {
        "id": doc.id, "filename": doc.filename, "sha256": doc.sha256, "status": doc.status,
        "error_code": doc.error_code, "error_message": doc.error_message,
        "taxpayer_name": doc.taxpayer_name, "ein": doc.ein, "extraction_method": doc.extraction_method,
        "page_count": doc.page_count, "created_at": doc.created_at,
        "properties": [{
            "id": p.id, "label": p.label, "address": p.address, "extracted_address": p.extracted_address,
            "page": p.page, "lines": [line_out(li) for li in grouped.get(p.id, [])],
            "computed": computed_totals(_values(grouped.get(p.id, []))),
        } for p in doc.properties],
        "summary_lines": [line_out(li) for li in grouped.get(None, [])],
        "grand_total_net_income": grand,
        "validation": validation,
        "warnings": report.get("warnings", []),
        "duplicate": duplicate,
    }


def list_documents(db: Session) -> list[dict]:
    docs = db.scalars(select(Document).order_by(Document.id.desc())).all()
    manual = dict(db.execute(select(AuditLog.document_id, func.count())
                             .where(AuditLog.action.in_(("updated", "reverted")))
                             .group_by(AuditLog.document_id)).all())
    out = []
    for d in docs:
        v, grand = validation_for(d) if d.status == "extracted" else (None, None)
        out.append({"id": d.id, "filename": d.filename, "status": d.status, "error_code": d.error_code,
                    "taxpayer_name": d.taxpayer_name, "property_count": len(d.properties),
                    "validation_status": v["status"] if v else None, "grand_total_net_income": grand,
                    "manual_changes": manual.get(d.id, 0), "created_at": d.created_at})
    return out


# --------------------------------------------------------------------------- #
# Mutations (all audited)
# --------------------------------------------------------------------------- #
def update_line_item(db: Session, item_id: int, value: int | None, expected_version: int | None,
                     actor: str, reason: str | None, action: str = "updated") -> LineItem:
    li = db.get(LineItem, item_id)
    if li is None:
        raise NotFound(f"line item {item_id} not found")
    if expected_version is not None and expected_version != li.version:
        raise ConflictError(f"line item was changed by someone else (version {li.version}, "
                            f"you had {expected_version}); reload and retry")
    if value == li.current_value:
        return li
    old = li.current_value
    li.current_value = value
    li.is_manual = value != li.extracted_value
    li.version += 1
    db.add(AuditLog(document_id=li.document_id, entity_type="line_item", entity_id=li.id, field=li.line_code,
                    action=action, old_value=None if old is None else str(old),
                    new_value=None if value is None else str(value), actor=actor, reason=reason))
    db.commit()
    db.refresh(li)
    return li


def revert_line_item(db: Session, item_id: int, actor: str) -> LineItem:
    li = db.get(LineItem, item_id)
    if li is None:
        raise NotFound(f"line item {item_id} not found")
    return update_line_item(db, item_id, li.extracted_value, None, actor, "reverted to extracted value",
                            action="reverted")


def update_property(db: Session, prop_id: int, address: str, actor: str, reason: str | None) -> Property:
    prop = db.get(Property, prop_id)
    if prop is None:
        raise NotFound(f"property {prop_id} not found")
    if address != prop.address:
        db.add(AuditLog(document_id=prop.document_id, entity_type="property", entity_id=prop.id,
                        field="address", action="updated", old_value=prop.address, new_value=address,
                        actor=actor, reason=reason))
        prop.address = address
        db.commit()
    return prop


def history(db: Session, doc: Document) -> list[dict]:
    labels = {p.id: p.label for p in doc.properties}
    li_prop = {li.id: labels.get(li.property_id) for li in doc.line_items}
    out = []
    for a in reversed(doc.audit):
        label = li_prop.get(a.entity_id) if a.entity_type == "line_item" else (
            labels.get(a.entity_id) if a.entity_type == "property" else None)
        out.append({"id": a.id, "entity_type": a.entity_type, "entity_id": a.entity_id, "field": a.field,
                    "action": a.action, "old_value": a.old_value, "new_value": a.new_value, "actor": a.actor,
                    "reason": a.reason, "created_at": a.created_at, "property_label": label})
    return out


def export_json(doc: Document, source: str = "current") -> list[dict]:
    """Output JSON (same shape as 8825_output.json) from current or originally extracted values."""
    grouped = _by_property(doc)
    out = []
    for p in doc.properties:
        items = grouped.get(p.id, [])
        vals = {li.line_code: (li.current_value if source == "current" else li.extracted_value) for li in items}
        out.append(output_record(p.label, p.address if source == "current" else p.extracted_address, vals))
    return out


def delete_document(db: Session, doc: Document) -> None:
    path = doc.stored_path
    others = db.scalar(select(func.count()).select_from(Document)
                       .where(Document.sha256 == doc.sha256, Document.id != doc.id))
    db.delete(doc)
    db.commit()
    if not others and path and os.path.exists(path):
        os.remove(path)
