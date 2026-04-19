from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from cwi_accountant.models import DocumentRecord, ExtractedField, ProposedExpenseEntry
from cwi_accountant.utils import file_hash, parse_possible_date


AMOUNT_RE = re.compile(
    r"(?:total|amount due|amount paid|balance due)\s*[:\-]?\s*\$?\s*"
    r"([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})|[0-9]+(?:\.[0-9]{2}))",
    re.IGNORECASE,
)
CURRENCY_RE = re.compile(
    r"\$?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})|[0-9]+(?:\.[0-9]{2}))"
)
INVOICE_RE = re.compile(
    r"(?:invoice|order|receipt|reference|confirmation)\s*"
    r"(?:#|number|no\.?|id)?\s*[:\-]?\s*([A-Z0-9\-]{4,})",
    re.IGNORECASE,
)
TAX_RE = re.compile(r"(?:tax|sales tax|vat)\s*[:\-]?\s*\$?\s*([0-9]+(?:\.[0-9]{2}))", re.IGNORECASE)
SUBTOTAL_RE = re.compile(r"subtotal\s*[:\-]?\s*\$?\s*([0-9]+(?:\.[0-9]{2}))", re.IGNORECASE)
PAYMENT_RE = re.compile(r"(?:paid with|payment method|card)\s*[:\-]?\s*([A-Za-z0-9\- ]{3,40})", re.IGNORECASE)
VENDOR_HINT_RE = re.compile(
    r"(?:from|vendor|merchant|seller|bill from)\s*[:\-]?\s*([A-Za-z0-9&.,'\- ]{2,80})",
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r"(?:date|issued|transaction date|invoice date|order date)\s*[:\-]?\s*([A-Za-z0-9,\-/ ]{6,30})",
    re.IGNORECASE,
)
GENERIC_DATE_RE = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})\b"
)
RECURRING_RE = re.compile(
    r"(monthly|annual|yearly|subscription|renewal|auto[- ]?pay|recurring)",
    re.IGNORECASE,
)


def _strip_noise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _safe_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    cleaned = value.replace(",", "").replace("$", "").strip()
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except Exception:
        return None


def _clamp(score: float) -> float:
    return max(0.0, min(1.0, score))


@dataclass(slots=True)
class ExtractionResult:
    document: DocumentRecord
    proposed_entry: ProposedExpenseEntry


class DocumentExtractor:
    SUPPORTED = {
        ".pdf",
        ".txt",
        ".csv",
        ".xlsx",
        ".xls",
        ".jpg",
        ".jpeg",
        ".png",
        ".heic",
        ".docx",
    }

    def extract(self, path: Path) -> ExtractionResult:
        text, file_type = self._extract_text(path)
        fields = self._extract_fields(text, path)
        doc_type = fields["document_type"].value or "financial_document"

        confidence_overall = self._overall_confidence(fields)
        review_reason = self._review_reason(fields, confidence_overall)

        doc_date = parse_possible_date(fields["date"].value)
        amount = _safe_decimal(fields["amount"].value)
        subtotal = _safe_decimal(fields["subtotal"].value)
        tax_amount = _safe_decimal(fields["tax_amount"].value)
        due_date = parse_possible_date(fields["due_date"].value)

        recurring = "Yes" if fields["recurring_clue"].value else "No"

        file_path = str(path)
        record = DocumentRecord(
            file_path=file_path,
            file_hash=file_hash(path),
            file_mtime=path.stat().st_mtime,
            file_size=path.stat().st_size,
            file_type=file_type,
            document_type=doc_type,
            vendor=fields["vendor"].value,
            doc_date=doc_date,
            due_date=due_date,
            amount=amount,
            subtotal=subtotal,
            tax_amount=tax_amount,
            payment_status=fields["payment_status"].value,
            reference_number=fields["reference_number"].value,
            payment_method=fields["payment_method"].value,
            description=fields["description"].value,
            recurring_clue=fields["recurring_clue"].value,
            client_project=fields["client_project"].value,
            business_purpose_clue=fields["business_purpose"].value,
            extracted_text=(text[:20000] if text else None),
            extracted_fields=fields,
            confidence_overall=confidence_overall,
            state="needs-review" if review_reason else "new",
            needs_review=bool(review_reason),
            review_reason=review_reason,
        )

        proposed = ProposedExpenseEntry(
            date=doc_date,
            vendor=fields["vendor"].value,
            description=fields["description"].value or doc_type.replace("_", " ").title(),
            payment_method=fields["payment_method"].value,
            amount=amount,
            tax_deductible="Review",
            receipt="Yes",
            receipt_link_file=file_path,
            business_purpose=fields["business_purpose"].value,
            client_project=fields["client_project"].value,
            recurring=recurring,
            notes=self._build_notes(record, fields),
        )

        return ExtractionResult(document=record, proposed_entry=proposed)

    def _extract_text(self, path: Path) -> tuple[str, str]:
        suffix = path.suffix.lower()
        if suffix not in self.SUPPORTED:
            return "", "unknown"
        if suffix == ".pdf":
            return self._extract_pdf_text(path), "pdf"
        if suffix in {".txt", ".docx"}:
            return path.read_text(errors="ignore"), "text"
        if suffix == ".csv":
            return self._extract_csv_text(path), "csv"
        if suffix in {".xlsx", ".xls"}:
            return self._extract_xlsx_text(path), "spreadsheet"
        if suffix in {".jpg", ".jpeg", ".png", ".heic"}:
            text = self._extract_image_text(path)
            return text, "image"
        return "", "unknown"

    def _extract_pdf_text(self, path: Path) -> str:
        parts: list[str] = []
        try:
            reader = PdfReader(str(path))
            for page in reader.pages:
                try:
                    parts.append(page.extract_text() or "")
                except Exception:
                    continue
        except Exception:
            return ""
        return _strip_noise("\n".join(parts))

    def _extract_csv_text(self, path: Path) -> str:
        rows: list[str] = []
        with path.open("r", errors="ignore", newline="") as fh:
            reader = csv.reader(fh)
            for idx, row in enumerate(reader):
                rows.append(" | ".join(cell.strip() for cell in row if cell.strip()))
                if idx > 300:
                    break
        return _strip_noise("\n".join(rows))

    def _extract_xlsx_text(self, path: Path) -> str:
        try:
            import openpyxl
        except Exception:
            return ""

        rows: list[str] = []
        try:
            wb = openpyxl.load_workbook(path, data_only=True)
        except Exception:
            return ""

        for ws in wb.worksheets[:4]:
            for row in ws.iter_rows(min_row=1, max_row=120, values_only=True):
                values = [str(x).strip() for x in row if x not in (None, "")]
                if values:
                    rows.append(" | ".join(values))
        return _strip_noise("\n".join(rows))

    def _extract_image_text(self, path: Path) -> str:
        try:
            from PIL import Image
            import pytesseract

            text = pytesseract.image_to_string(Image.open(path))
            return _strip_noise(text)
        except Exception:
            return ""

    def _extract_fields(self, text: str, path: Path) -> dict[str, ExtractedField]:
        txt = text or ""

        doc_type, doc_conf, doc_source = self._classify_document_type(txt, path)

        vendor, vendor_source = self._vendor_from_text(txt)
        vendor_conf = self._vendor_confidence(vendor, vendor_source)

        date_val, date_source, date_conf = self._date_from_text(txt)
        amount_val, amount_source, amount_conf = self._amount_from_text(txt)

        subtotal_val = self._match_group(SUBTOTAL_RE, txt)
        tax_val = self._match_group(TAX_RE, txt)
        due_val = self._match_due_date(txt)

        payment_status, payment_status_conf = self._infer_payment_status(txt)

        payment_method = self._match_group(PAYMENT_RE, txt)
        payment_method_conf = 0.84 if payment_method else 0.18

        reference_number = self._match_group(INVOICE_RE, txt)
        reference_conf = 0.88 if reference_number else 0.15

        description, description_source = self._infer_description(txt, doc_type)
        description_conf = 0.72 if description_source == "content" else 0.45

        recurring_match = RECURRING_RE.search(txt)
        recurring_val = recurring_match.group(1) if recurring_match else None
        recurring_conf = 0.82 if recurring_val else 0.2

        client_project, client_source = self._infer_client_project(txt)
        client_conf = 0.74 if client_source == "explicit" else 0.2

        purpose, purpose_source = self._infer_business_purpose(txt)
        purpose_conf = 0.74 if purpose_source == "explicit" else 0.2

        subtotal_conf = 0.9 if subtotal_val and _safe_decimal(subtotal_val) is not None else 0.15
        tax_conf = 0.9 if tax_val and _safe_decimal(tax_val) is not None else 0.15
        due_conf = 0.86 if due_val and parse_possible_date(due_val) else 0.15

        fields = {
            "vendor": ExtractedField(
                name="vendor",
                value=vendor,
                confidence=vendor_conf,
                source=vendor_source,
            ),
            "date": ExtractedField(
                name="date",
                value=date_val,
                confidence=date_conf,
                source=date_source,
            ),
            "amount": ExtractedField(
                name="amount",
                value=amount_val,
                confidence=amount_conf,
                source=amount_source,
            ),
            "subtotal": ExtractedField(
                name="subtotal",
                value=subtotal_val,
                confidence=subtotal_conf,
                source="regex-subtotal",
            ),
            "tax_amount": ExtractedField(
                name="tax_amount",
                value=tax_val,
                confidence=tax_conf,
                source="regex-tax",
            ),
            "due_date": ExtractedField(
                name="due_date",
                value=due_val,
                confidence=due_conf,
                source="regex-due-date",
            ),
            "payment_status": ExtractedField(
                name="payment_status",
                value=payment_status,
                confidence=payment_status_conf,
                source="keyword-status",
            ),
            "reference_number": ExtractedField(
                name="reference_number",
                value=reference_number,
                confidence=reference_conf,
                source="regex-reference",
            ),
            "payment_method": ExtractedField(
                name="payment_method",
                value=payment_method,
                confidence=payment_method_conf,
                source="regex-payment-method",
            ),
            "description": ExtractedField(
                name="description",
                value=description,
                confidence=description_conf,
                source=description_source,
            ),
            "recurring_clue": ExtractedField(
                name="recurring_clue",
                value=recurring_val,
                confidence=recurring_conf,
                source="regex-recurring",
            ),
            "client_project": ExtractedField(
                name="client_project",
                value=client_project,
                confidence=client_conf,
                source=client_source,
            ),
            "business_purpose": ExtractedField(
                name="business_purpose",
                value=purpose,
                confidence=purpose_conf,
                source=purpose_source,
            ),
            "document_type": ExtractedField(
                name="document_type",
                value=doc_type,
                confidence=doc_conf,
                source=doc_source,
            ),
        }
        return fields

    def _classify_document_type(self, text: str, path: Path | None) -> tuple[str, float, str]:
        hay = (text or "").lower()

        rules = [
            ("invoice", ["invoice", "bill to", "amount due"], 0.97),
            ("receipt", ["receipt", "thank you for your purchase", "order confirmed"], 0.96),
            ("purchase_order", ["purchase order", "po #"], 0.95),
            ("vendor_statement", ["statement", "account summary"], 0.93),
            ("subscription_renewal", ["renewal", "subscription", "auto-renew"], 0.92),
        ]
        for label, tokens, confidence in rules:
            if any(token in hay for token in tokens):
                return label, confidence, "content-rule"

        if path is not None:
            lower = path.name.lower()
            if "invoice" in lower:
                return "invoice", 0.78, "filename-rule"
            if "receipt" in lower:
                return "receipt", 0.76, "filename-rule"
            if "statement" in lower:
                return "vendor_statement", 0.74, "filename-rule"

        return "financial_document", 0.45, "fallback"

    def _vendor_from_text(self, text: str) -> tuple[str | None, str]:
        match = VENDOR_HINT_RE.search(text)
        if match:
            vendor = match.group(1)
            vendor = re.split(r"\b(invoice|receipt|order|date|amount|due|total)\b", vendor, maxsplit=1)[0]
            vendor = _strip_noise(vendor)
            if len(vendor) >= 2:
                return vendor[:120], "explicit-label"

        for line in text.splitlines()[:20]:
            clean = line.strip()
            if not clean:
                continue
            lower = clean.lower()
            if any(key in lower for key in ["invoice", "receipt", "date", "subtotal", "tax", "amount"]):
                continue
            if re.search(r"\d{3,}", clean):
                continue
            if not re.search(r"[a-zA-Z]", clean):
                continue
            if 2 <= len(clean) <= 80:
                return clean, "header-line"
        return None, "missing"

    def _vendor_confidence(self, vendor: str | None, source: str) -> float:
        if not vendor:
            return 0.1
        base = 0.93 if source == "explicit-label" else 0.62
        lower = vendor.lower()
        if any(tok in lower for tok in ["invoice", "amount", "date", "subtotal", "tax"]):
            base -= 0.25
        if len(vendor.strip()) < 3:
            base -= 0.2
        return _clamp(base)

    def _date_from_text(self, text: str) -> tuple[str | None, str, float]:
        primary = self._match_group(DATE_RE, text)
        if primary:
            parsed = parse_possible_date(primary)
            if parsed:
                return primary, "labeled-date", 0.94
            return primary, "labeled-date-unparsed", 0.42

        generic = GENERIC_DATE_RE.search(text)
        if generic:
            value = _strip_noise(generic.group(0))
            parsed = parse_possible_date(value)
            if parsed:
                return value, "generic-date", 0.68
            return value, "generic-date-unparsed", 0.35

        return None, "missing", 0.1

    def _amount_from_text(self, text: str) -> tuple[str | None, str, float]:
        primary = self._match_group(AMOUNT_RE, text)
        if primary:
            if _safe_decimal(primary) is not None:
                return primary, "labeled-total", 0.95
            return primary, "labeled-total-unparsed", 0.4

        candidates: list[Decimal] = []
        for match in CURRENCY_RE.finditer(text):
            amount = _safe_decimal(match.group(1))
            if amount is None or amount <= 0:
                continue
            candidates.append(amount)

        if candidates:
            likely_total = max(candidates)
            return f"{likely_total:.2f}", "currency-fallback", 0.62

        return None, "missing", 0.1

    def _match_group(self, regex: re.Pattern[str], text: str) -> str | None:
        m = regex.search(text)
        if not m:
            return None
        return _strip_noise(m.group(1))

    def _match_due_date(self, text: str) -> str | None:
        due = re.search(r"due(?:\s+date)?\s*[:\-]?\s*([A-Za-z0-9,\-/ ]{6,30})", text, re.IGNORECASE)
        if not due:
            return None
        return _strip_noise(due.group(1))

    def _infer_payment_status(self, text: str) -> tuple[str | None, float]:
        hay = text.lower()
        if "overdue" in hay:
            return "overdue", 0.88
        if "paid" in hay and "unpaid" not in hay:
            return "paid", 0.86
        if "balance due" in hay or "due date" in hay:
            return "due", 0.82
        return None, 0.18

    def _infer_description(self, text: str, doc_type: str) -> tuple[str, str]:
        for line in text.splitlines():
            clean = line.strip()
            if len(clean) < 8:
                continue
            if any(
                token in clean.lower()
                for token in ["invoice", "receipt", "amount", "subtotal", "tax", "date", "balance due"]
            ):
                continue
            return clean[:180], "content"
        return doc_type.replace("_", " "), "fallback"

    def _infer_client_project(self, text: str) -> tuple[str | None, str]:
        m = re.search(r"(?:client|project)\s*[:\-]\s*([A-Za-z0-9\- _]{2,80})", text, re.IGNORECASE)
        if not m:
            return None, "missing"
        return _strip_noise(m.group(1)), "explicit"

    def _infer_business_purpose(self, text: str) -> tuple[str | None, str]:
        m = re.search(
            r"(?:business purpose|purpose|service)\s*[:\-]\s*([A-Za-z0-9\- _.,]{4,120})",
            text,
            re.IGNORECASE,
        )
        if not m:
            return None, "missing"
        return _strip_noise(m.group(1)), "explicit"

    def _overall_confidence(self, fields: dict[str, ExtractedField]) -> float:
        weights = {
            "vendor": 0.28,
            "date": 0.24,
            "amount": 0.28,
            "document_type": 0.2,
        }
        score = sum(fields[name].confidence * weight for name, weight in weights.items())

        supporting = [
            fields["reference_number"].confidence,
            fields["payment_method"].confidence,
            fields["description"].confidence,
        ]
        score += (sum(supporting) / len(supporting)) * 0.08

        for name in ["vendor", "date", "amount", "document_type"]:
            if not fields[name].value:
                score -= 0.12
        return _clamp(score)

    def _review_reason(
        self,
        fields: dict[str, ExtractedField],
        overall_confidence: float,
    ) -> str | None:
        weak: list[str] = []
        for name in ["vendor", "date", "amount", "document_type"]:
            field = fields[name]
            if not field.value or field.confidence < 0.78:
                weak.append(f"{name}={field.confidence:.2f}")

        if weak:
            return "Weak critical fields: " + ", ".join(weak)
        if overall_confidence < 0.82:
            return f"Overall confidence below review threshold: {overall_confidence:.2f}"
        return None

    def _build_notes(self, record: DocumentRecord, fields: dict[str, ExtractedField]) -> str:
        notes: list[str] = []
        if fields["reference_number"].value:
            notes.append(f"Ref: {fields['reference_number'].value}")
        notes.append(f"Doc type: {record.document_type}")
        notes.append(f"Confidence: {record.confidence_overall:.2f}")
        notes.append(
            "Critical conf "
            + ", ".join(
                [
                    f"vendor={fields['vendor'].confidence:.2f}",
                    f"date={fields['date'].confidence:.2f}",
                    f"amount={fields['amount'].confidence:.2f}",
                    f"doctype={fields['document_type'].confidence:.2f}",
                ]
            )
        )
        if record.review_reason:
            notes.append(f"Review reason: {record.review_reason}")
        notes.append(f"Source: {record.file_path}")
        return " | ".join(notes)

    def should_process(self, path: Path) -> bool:
        return path.suffix.lower() in self.SUPPORTED and path.is_file()

    @staticmethod
    def as_dict(result: ExtractionResult) -> dict[str, Any]:
        return {
            "document": result.document.model_dump(mode="json"),
            "proposed_entry": result.proposed_entry.model_dump(mode="json"),
            "extracted_at": datetime.utcnow().isoformat(),
        }
