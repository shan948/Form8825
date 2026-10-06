"""Data model.

documents      one row per uploaded PDF (success or failure) + immutable extraction report
properties     one row per property column (A, B, C ...) found on the form
line_items     one row per amount (property lines 2a-19, form lines 20a-23)
               extracted_value is never modified; current_value is what the user sees/edits
audit_log      append-only history: extraction events and every manual change
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow():
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    stored_path: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20))              # extracted | failed
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(Text)
    taxpayer_name: Mapped[str | None] = mapped_column(String(255))
    ein: Mapped[str | None] = mapped_column(String(20))
    extraction_method: Mapped[str | None] = mapped_column(String(50))
    page_count: Mapped[int | None] = mapped_column(Integer)
    report_json: Mapped[str | None] = mapped_column(Text)         # full extractor report (snapshot)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    properties: Mapped[list["Property"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="Property.sort_order")
    line_items: Mapped[list["LineItem"]] = relationship(
        back_populates="document", cascade="all, delete-orphan")
    audit: Mapped[list["AuditLog"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="AuditLog.id")


class Property(Base):
    __tablename__ = "properties"
    __table_args__ = (UniqueConstraint("document_id", "label"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(5))                  # A, B, C ...
    address: Mapped[str | None] = mapped_column(String(500))
    extracted_address: Mapped[str | None] = mapped_column(String(500))
    page: Mapped[int] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer)

    document: Mapped[Document] = relationship(back_populates="properties")
    line_items: Mapped[list["LineItem"]] = relationship(back_populates="property")


class LineItem(Base):
    __tablename__ = "line_items"
    __table_args__ = (UniqueConstraint("document_id", "property_id", "line_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[int | None] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    line_code: Mapped[str] = mapped_column(String(5))              # "2a", "18", "20a"
    field_key: Mapped[str] = mapped_column(String(60))             # "gross_rents"
    section: Mapped[str] = mapped_column(String(20))               # income|expense|total|reserved|summary
    extracted_value: Mapped[int | None] = mapped_column(Integer)
    current_value: Mapped[int | None] = mapped_column(Integer)
    raw_text: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str | None] = mapped_column(String(20))         # acroform | text | ocr
    confidence: Mapped[float | None] = mapped_column(Float)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)       # optimistic locking
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    document: Mapped[Document] = relationship(back_populates="line_items")
    property: Mapped[Property | None] = relationship(back_populates="line_items")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str] = mapped_column(String(20))           # document | property | line_item
    entity_id: Mapped[int] = mapped_column(Integer)
    field: Mapped[str | None] = mapped_column(String(60))          # e.g. "2a" / "address"
    action: Mapped[str] = mapped_column(String(20))                # extracted | failed | updated | reverted
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(100), default="system")
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document] = relationship(back_populates="audit")
