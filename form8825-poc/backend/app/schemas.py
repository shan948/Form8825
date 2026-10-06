from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LineItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    line_code: str
    field_key: str
    section: str
    label: str
    extracted_value: int | None
    current_value: int | None
    raw_text: str | None
    source: str | None
    confidence: float | None
    needs_review: bool
    is_manual: bool
    version: int


class PropertyOut(BaseModel):
    id: int
    label: str
    address: str | None
    extracted_address: str | None
    page: int
    lines: list[LineItemOut]
    computed: dict[str, int]           # {"2c":.., "18":.., "19":..} from current values


class CheckOut(BaseModel):
    scope: str
    property: str | None
    rule: str
    line: str
    expected: int | None
    actual: int | None
    difference: int | None
    status: str
    message: str


class ValidationOut(BaseModel):
    status: str
    passed: int
    failed: int
    warnings: int
    checks: list[CheckOut]


class DocumentSummary(BaseModel):
    id: int
    filename: str
    status: str
    error_code: str | None
    taxpayer_name: str | None
    property_count: int
    validation_status: str | None
    grand_total_net_income: int | None
    manual_changes: int
    created_at: datetime


class DocumentDetail(BaseModel):
    id: int
    filename: str
    sha256: str
    status: str
    error_code: str | None
    error_message: str | None
    taxpayer_name: str | None
    ein: str | None
    extraction_method: str | None
    page_count: int | None
    created_at: datetime
    properties: list[PropertyOut]
    summary_lines: list[LineItemOut]
    grand_total_net_income: int
    validation: ValidationOut
    warnings: list[str]
    duplicate: bool = False


class LineItemUpdate(BaseModel):
    value: int | None = Field(description="New amount in whole dollars; null clears the line")
    expected_version: int | None = Field(None, description="Optimistic lock: version the client last saw")
    changed_by: str = Field("ui-user", max_length=100)
    reason: str | None = Field(None, max_length=500)


class PropertyUpdate(BaseModel):
    address: str = Field(max_length=500)
    changed_by: str = Field("ui-user", max_length=100)
    reason: str | None = Field(None, max_length=500)


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    entity_type: str
    entity_id: int
    field: str | None
    action: str
    old_value: str | None
    new_value: str | None
    actor: str
    reason: str | None
    created_at: datetime
    property_label: str | None = None


class LineItemUpdateResult(BaseModel):
    line_item: LineItemOut
    property_computed: dict[str, int] | None
    validation: ValidationOut
    grand_total_net_income: int
