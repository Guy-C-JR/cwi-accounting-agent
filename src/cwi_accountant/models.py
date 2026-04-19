from __future__ import annotations

from datetime import date as dt_date
from datetime import datetime as dt_datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


ReviewState = Literal[
    "new",
    "auto-posted",
    "needs-review",
    "approved",
    "approved-with-edits",
    "rejected",
    "duplicate",
    "deferred",
    "failed",
    "archived",
]

DecisionAction = Literal[
    "approve",
    "approve-with-edits",
    "reject",
    "mark-duplicate",
    "link-existing",
    "reprocess",
    "defer",
    "mark-personal",
    "mark-informational",
]


class ExtractedField(BaseModel):
    name: str
    value: str | None = None
    confidence: float = 0.0
    source: str = "unknown"
    notes: str | None = None

    @field_validator("confidence")
    @classmethod
    def confidence_bounds(cls, v: float) -> float:
        if v < 0 or v > 1:
            raise ValueError("confidence must be between 0 and 1")
        return v


class ProposedExpenseEntry(BaseModel):
    date: dt_date | None = None
    vendor: str | None = None
    category: str | None = None
    subcategory: str | None = None
    description: str | None = None
    payment_method: str | None = None
    account_card: str | None = None
    amount: Decimal | None = None
    tax_deductible: str | None = None
    receipt: str | None = None
    receipt_link_file: str | None = None
    business_purpose: str | None = None
    billable_to_client: str | None = None
    client_project: str | None = None
    recurring: str | None = None
    notes: str | None = None
    month: str | None = None
    year: int | None = None
    quarter: str | None = None
    week_num: int | None = None
    month_key: str | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def parse_amount(cls, v: Any) -> Decimal | None:
        if v is None or v == "":
            return None
        if isinstance(v, Decimal):
            return v
        if isinstance(v, (int, float)):
            return Decimal(str(v)).quantize(Decimal("0.01"))
        if isinstance(v, str):
            cleaned = v.replace("$", "").replace(",", "").strip()
            try:
                return Decimal(cleaned).quantize(Decimal("0.01"))
            except InvalidOperation as exc:
                raise ValueError(f"Invalid amount: {v}") from exc
        raise ValueError(f"Unsupported amount type: {type(v)}")

    @model_validator(mode="after")
    def critical_fields(self) -> "ProposedExpenseEntry":
        if self.amount is not None and self.amount < 0:
            raise ValueError("Amount cannot be negative")
        return self


class DocumentRecord(BaseModel):
    id: int | None = None
    file_path: str
    file_hash: str
    file_mtime: float
    file_size: int
    file_type: str
    document_type: str | None = None
    vendor: str | None = None
    doc_date: dt_date | None = None
    due_date: dt_date | None = None
    amount: Decimal | None = None
    subtotal: Decimal | None = None
    tax_amount: Decimal | None = None
    payment_status: str | None = None
    reference_number: str | None = None
    payment_method: str | None = None
    description: str | None = None
    recurring_clue: str | None = None
    client_project: str | None = None
    business_purpose_clue: str | None = None
    extracted_text: str | None = None
    extracted_fields: dict[str, ExtractedField] = Field(default_factory=dict)
    confidence_overall: float = 0.0
    state: ReviewState = "new"
    needs_review: bool = True
    review_reason: str | None = None
    posted_sheet: str | None = None
    posted_row: int | None = None
    expense_ref: str | None = None
    created_at: dt_datetime = Field(default_factory=dt_datetime.utcnow)
    updated_at: dt_datetime = Field(default_factory=dt_datetime.utcnow)

    @field_validator("confidence_overall")
    @classmethod
    def confidence_range(cls, v: float) -> float:
        if v < 0 or v > 1:
            raise ValueError("confidence_overall must be between 0 and 1")
        return v


class VendorCandidate(BaseModel):
    id: int | None = None
    vendor_name: str
    normalized_name: str
    vendor_type: str | None = None
    contact_person: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    website: str | None = None
    tax_form_needed: str | None = None
    eligible_1099: str | None = None
    usual_category: str | None = None
    payment_terms: str | None = None
    status: str | None = None
    notes: str | None = None
    source_document_ids: list[int] = Field(default_factory=list)


class DuplicateCandidate(BaseModel):
    id: int | None = None
    document_id: int
    candidate_document_id: int
    score: float
    reason: str
    status: str = "open"


class RecurringBillCandidate(BaseModel):
    id: int | None = None
    vendor: str
    expense_name: str
    category: str | None = None
    amount: Decimal | None = None
    frequency: str | None = None
    due_day: int | None = None
    first_seen: dt_date | None = None
    last_seen: dt_date | None = None
    source_document_ids: list[int] = Field(default_factory=list)
    confidence: float = 0.0
    status: str = "new"
    linked_recurring_row: int | None = None


class ReviewDecision(BaseModel):
    document_id: int
    action: DecisionAction
    notes: str | None = None
    edited_entry: ProposedExpenseEntry | None = None
    link_expense_ref: str | None = None
    defer_until: dt_datetime | None = None
    decided_by: str = "human"


class AuditEvent(BaseModel):
    id: int | None = None
    timestamp: dt_datetime = Field(default_factory=dt_datetime.utcnow)
    document_id: int | None = None
    source_file: str | None = None
    action: str
    sheet_name: str | None = None
    row_number: int | None = None
    fields_written: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None
    auto_or_human: str = "human"
    before_values: dict[str, Any] = Field(default_factory=dict)
    after_values: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None


class ExceptionReportItem(BaseModel):
    id: str
    report_type: str
    severity: str
    message: str
    document_id: int | None = None
    vendor: str | None = None
    amount: Decimal | None = None
    file_path: str | None = None
    created_at: dt_datetime = Field(default_factory=dt_datetime.utcnow)
