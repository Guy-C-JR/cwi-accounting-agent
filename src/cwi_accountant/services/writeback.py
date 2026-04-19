from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from cwi_accountant.db import StateStore
from cwi_accountant.models import AuditEvent, ProposedExpenseEntry, ReviewDecision, VendorCandidate
from cwi_accountant.services.category_mapper import CategoryMapper
from cwi_accountant.utils import normalize_vendor_name
from cwi_accountant.workbook import WorkbookGateway


class WritebackError(RuntimeError):
    pass


class WritebackService:
    def __init__(
        self,
        *,
        store: StateStore,
        workbook: WorkbookGateway,
        mapper: CategoryMapper,
    ):
        self.store = store
        self.workbook = workbook
        self.mapper = mapper

    def apply_decision(self, decision: ReviewDecision) -> dict[str, Any]:
        row = self.store.get_document(decision.document_id)
        if row is None:
            raise WritebackError(f"Document {decision.document_id} not found")

        before = self._row_to_payload(row)
        proposed_entry = self._load_proposed_entry(row, decision)

        if decision.action in {"approve", "approve-with-edits"}:
            return self._handle_approve(row, decision, proposed_entry, before)
        if decision.action == "reject":
            self.store.update_document_state(
                decision.document_id,
                state="rejected",
                needs_review=False,
                review_reason=decision.notes,
            )
            self.store.add_review_decision(decision, before_payload=before, after_payload={"state": "rejected"})
            self.store.add_audit_event(
                AuditEvent(
                    document_id=decision.document_id,
                    source_file=row["file_path"],
                    action="reject-document",
                    notes=decision.notes,
                    auto_or_human="human",
                )
            )
            return {"status": "rejected"}

        if decision.action == "mark-duplicate":
            self.store.update_document_state(
                decision.document_id,
                state="duplicate",
                needs_review=False,
                review_reason=decision.notes or "Marked duplicate by reviewer",
            )
            self.store.add_review_decision(
                decision,
                before_payload=before,
                after_payload={"state": "duplicate"},
            )
            self.store.add_audit_event(
                AuditEvent(
                    document_id=decision.document_id,
                    source_file=row["file_path"],
                    action="mark-duplicate",
                    notes=decision.notes,
                    auto_or_human="human",
                )
            )
            return {"status": "duplicate"}

        if decision.action == "link-existing":
            if not decision.link_expense_ref:
                raise WritebackError("link-existing requires link_expense_ref")
            self.store.set_document_posting(
                decision.document_id,
                state="approved",
                posted_sheet="Expense_Log",
                posted_row=int(decision.link_expense_ref.split("!")[-1]),
                expense_ref=decision.link_expense_ref,
                needs_review=False,
                review_reason=None,
            )
            self.store.add_review_decision(
                decision,
                before_payload=before,
                after_payload={"expense_ref": decision.link_expense_ref},
            )
            self.store.add_audit_event(
                AuditEvent(
                    document_id=decision.document_id,
                    source_file=row["file_path"],
                    action="link-existing-expense",
                    sheet_name="Expense_Log",
                    row_number=int(decision.link_expense_ref.split("!")[-1]),
                    notes=decision.notes,
                    auto_or_human="human",
                )
            )
            return {"status": "linked", "expense_ref": decision.link_expense_ref}

        if decision.action == "reprocess":
            self.store.update_document_state(
                decision.document_id,
                state="new",
                needs_review=True,
                review_reason="Queued for reprocessing",
            )
            self.store.add_review_decision(decision, before_payload=before, after_payload={"state": "new"})
            return {"status": "queued-reprocess"}

        if decision.action == "defer":
            self.store.update_document_state(
                decision.document_id,
                state="deferred",
                needs_review=True,
                review_reason=decision.notes or "Deferred",
                snoozed_until=decision.defer_until,
            )
            self.store.add_review_decision(
                decision,
                before_payload=before,
                after_payload={"state": "deferred", "defer_until": decision.defer_until.isoformat() if decision.defer_until else None},
            )
            return {"status": "deferred"}

        if decision.action == "mark-personal":
            self.store.update_document_state(
                decision.document_id,
                state="archived",
                needs_review=False,
                review_reason="Marked personal/non-business",
            )
            self.store.add_review_decision(decision, before_payload=before, after_payload={"state": "archived"})
            self.store.add_audit_event(
                AuditEvent(
                    document_id=decision.document_id,
                    source_file=row["file_path"],
                    action="mark-personal",
                    notes=decision.notes,
                    auto_or_human="human",
                )
            )
            return {"status": "archived-personal"}

        if decision.action == "mark-informational":
            receipt_id = self._receipt_id(decision.document_id)
            receipt_result = self.workbook.append_receipt_index(
                receipt_id=receipt_id,
                date_value=row["doc_date"],
                vendor=row["vendor"],
                amount=Decimal(row["amount"]) if row["amount"] else None,
                linked_expense_ref=None,
                file_path=row["file_path"],
                verified="No",
                notes=decision.notes or "Informational document only",
            )
            self.store.update_document_state(
                decision.document_id,
                state="archived",
                needs_review=False,
                review_reason="Indexed informational document",
            )
            self.store.add_review_decision(
                decision,
                before_payload=before,
                after_payload={"state": "archived", "receipt_index_row": receipt_result.row_number},
            )
            self.store.add_audit_event(
                AuditEvent(
                    document_id=decision.document_id,
                    source_file=row["file_path"],
                    action="index-informational",
                    sheet_name=receipt_result.sheet_name,
                    row_number=receipt_result.row_number,
                    fields_written={"Receipt ID": receipt_id},
                    auto_or_human="human",
                    notes=decision.notes,
                )
            )
            return {"status": "indexed-informational", "receipt_row": receipt_result.row_number}

        raise WritebackError(f"Unsupported action: {decision.action}")

    def _handle_approve(
        self,
        row: Any,
        decision: ReviewDecision,
        proposed_entry: ProposedExpenseEntry,
        before: dict[str, Any],
    ) -> dict[str, Any]:
        doc_id = int(row["id"])

        if row["posted_row"]:
            # Avoid blind overwrite when workbook row may have diverged.
            self.store.update_document_state(
                doc_id,
                state="needs-review",
                needs_review=True,
                review_reason="Document already posted; manual reconcile required before rewrite",
            )
            raise WritebackError(
                "Document already posted to workbook. Refusing blind overwrite; use link-existing or reject."
            )

        proposed_entry = self.mapper.apply(proposed_entry)
        validation_errors = self.mapper.validate(proposed_entry)
        if validation_errors:
            self.store.update_document_state(
                doc_id,
                state="needs-review",
                needs_review=True,
                review_reason="; ".join(validation_errors),
            )
            raise WritebackError("Validation failed: " + "; ".join(validation_errors))

        duplicate_row = self.workbook.find_expense_duplicate(
            vendor=proposed_entry.vendor,
            date_value=proposed_entry.date,
            amount=proposed_entry.amount,
        )
        if duplicate_row is not None:
            self.store.update_document_state(
                doc_id,
                state="duplicate",
                needs_review=False,
                review_reason=f"Workbook duplicate at Expense_Log!{duplicate_row}",
            )
            self.store.add_review_decision(
                ReviewDecision(
                    document_id=doc_id,
                    action="mark-duplicate",
                    notes=f"Duplicate detected against Expense_Log!{duplicate_row}",
                    decided_by=decision.decided_by,
                ),
                before_payload=before,
                after_payload={"state": "duplicate"},
            )
            return {"status": "duplicate", "duplicate_row": duplicate_row}

        expense_write = self.workbook.append_expense(proposed_entry)

        vendor_result = None
        if proposed_entry.vendor:
            vendor_candidate = VendorCandidate(
                vendor_name=proposed_entry.vendor,
                normalized_name=normalize_vendor_name(proposed_entry.vendor),
                usual_category=proposed_entry.category,
                status="Active",
                source_document_ids=[doc_id],
            )
            vendor_result = self.workbook.upsert_vendor(vendor_candidate)

        receipt_id = self._receipt_id(doc_id)
        receipt_write = self.workbook.append_receipt_index(
            receipt_id=receipt_id,
            date_value=proposed_entry.date,
            vendor=proposed_entry.vendor,
            amount=proposed_entry.amount,
            linked_expense_ref=expense_write.expense_ref,
            file_path=row["file_path"],
            verified="Yes" if decision.action.startswith("approve") else "No",
            notes=proposed_entry.notes or "",
        )

        final_state = "approved-with-edits" if decision.action == "approve-with-edits" else "approved"
        self.store.set_document_posting(
            doc_id,
            state=final_state,
            posted_sheet=expense_write.sheet_name,
            posted_row=expense_write.row_number,
            expense_ref=expense_write.expense_ref,
            needs_review=False,
            review_reason=None,
        )
        self.store.update_document_proposed_entry(doc_id, proposed_entry)

        after_payload = {
            "state": final_state,
            "expense_ref": expense_write.expense_ref,
            "expense_row": expense_write.row_number,
            "receipt_index_row": receipt_write.row_number,
            "vendor_row": vendor_result.row_number if vendor_result else None,
            "entry": proposed_entry.model_dump(mode="json"),
        }
        self.store.add_review_decision(decision, before_payload=before, after_payload=after_payload)

        self.store.add_audit_event(
            AuditEvent(
                document_id=doc_id,
                source_file=row["file_path"],
                action="write-expense-log",
                sheet_name=expense_write.sheet_name,
                row_number=expense_write.row_number,
                fields_written=proposed_entry.model_dump(mode="json"),
                confidence=row["confidence_overall"],
                auto_or_human="human",
                before_values={},
                after_values=proposed_entry.model_dump(mode="json"),
                notes=decision.notes,
            )
        )
        self.store.add_audit_event(
            AuditEvent(
                document_id=doc_id,
                source_file=row["file_path"],
                action="write-receipt-index",
                sheet_name=receipt_write.sheet_name,
                row_number=receipt_write.row_number,
                fields_written={
                    "Receipt ID": receipt_id,
                    "Linked Expense Ref": expense_write.expense_ref,
                },
                auto_or_human="human",
            )
        )

        return {
            "status": final_state,
            "expense_row": expense_write.row_number,
            "receipt_row": receipt_write.row_number,
            "vendor_row": vendor_result.row_number if vendor_result else None,
            "expense_ref": expense_write.expense_ref,
        }

    def _load_proposed_entry(self, row: Any, decision: ReviewDecision) -> ProposedExpenseEntry:
        if decision.edited_entry is not None:
            return decision.edited_entry
        payload = row["proposed_entry_json"]
        if not payload:
            return ProposedExpenseEntry(
                date=(datetime.fromisoformat(row["doc_date"]).date() if row["doc_date"] else None),
                vendor=row["vendor"],
                amount=Decimal(row["amount"]) if row["amount"] else None,
                description=row["description"],
                payment_method=row["payment_method"],
                receipt="Yes",
                receipt_link_file=row["file_path"],
                notes="Autogenerated from document without proposal payload",
            )

        import json

        data = json.loads(payload)
        return ProposedExpenseEntry.model_validate(data)

    @staticmethod
    def _row_to_payload(row: Any) -> dict[str, Any]:
        return {k: row[k] for k in row.keys()}

    @staticmethod
    def _receipt_id(document_id: int) -> str:
        return f"RCPT-{datetime.utcnow().strftime('%Y%m%d')}-{document_id:06d}"
