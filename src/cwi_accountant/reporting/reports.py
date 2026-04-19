from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from cwi_accountant.db import StateStore


class ReportService:
    def __init__(self, *, store: StateStore, reports_dir: Path):
        self.store = store
        self.reports_dir = reports_dir
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def generate_monthly_summary(self, *, year: int, month: str) -> Path:
        month_lookup = {
            "jan": "01",
            "feb": "02",
            "mar": "03",
            "apr": "04",
            "may": "05",
            "jun": "06",
            "jul": "07",
            "aug": "08",
            "sep": "09",
            "oct": "10",
            "nov": "11",
            "dec": "12",
        }
        month_num = month_lookup.get(month.strip().lower()[:3])
        if not month_num:
            raise ValueError("Month must be one of Jan..Dec")

        rows = self.store.list_documents(limit=50000)
        filtered = [
            r
            for r in rows
            if r["doc_date"]
            and r["doc_date"].startswith(f"{year}-{month_num}")
            and r["state"] not in {"rejected", "duplicate", "archived"}
        ]

        totals: dict[str, Decimal] = {}
        for row in filtered:
            category = self._category(row)
            amount = Decimal(row["amount"]) if row["amount"] else Decimal("0")
            totals[category] = totals.get(category, Decimal("0")) + amount

        path = self.reports_dir / f"monthly_expense_summary_{year}_{month_num}.csv"
        with path.open("w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["Category", "Total Amount", "Count"])
            for category in sorted(totals):
                count = sum(1 for row in filtered if self._category(row) == category)
                writer.writerow([category, f"{totals[category]:.2f}", count])

        self.store.add_generated_report(
            report_type="monthly-expense-summary",
            file_path=str(path),
            period=f"{year}-{month_num}",
        )
        return path

    def generate_tax_report(self, *, year: int) -> Path:
        rows = self.store.list_documents(limit=50000)
        filtered = [
            r
            for r in rows
            if r["doc_date"]
            and r["doc_date"].startswith(f"{year}-")
            and r["state"] in {"approved", "approved-with-edits", "auto-posted"}
        ]

        path = self.reports_dir / f"tax_prep_exceptions_{year}.csv"
        with path.open("w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(
                [
                    "Document ID",
                    "Date",
                    "Vendor",
                    "Amount",
                    "Tax Deductible",
                    "Category",
                    "Receipt Link",
                    "Needs Attention",
                    "Reason",
                ]
            )
            for row in filtered:
                proposal = self._proposal(row)
                tax = proposal.get("tax_deductible")
                category = proposal.get("category")
                receipt_link = proposal.get("receipt_link_file")
                reason = []
                if not tax or str(tax).lower() in {"review", "partial / depends", "usually"}:
                    reason.append("uncertain tax treatment")
                if not category:
                    reason.append("missing category")
                if not receipt_link:
                    reason.append("missing receipt link")
                needs_attention = "Yes" if reason else "No"
                writer.writerow(
                    [
                        row["id"],
                        row["doc_date"],
                        row["vendor"],
                        row["amount"],
                        tax,
                        category,
                        receipt_link,
                        needs_attention,
                        "; ".join(reason),
                    ]
                )

        self.store.add_generated_report(
            report_type="tax-prep",
            file_path=str(path),
            period=str(year),
        )
        return path

    def generate_exception_reports(self) -> list[Path]:
        paths: list[Path] = []
        paths.append(self._write_simple_report("uncategorized_expenses", self._uncategorized_rows()))
        paths.append(self._write_simple_report("missing_receipts", self._missing_receipts_rows()))
        paths.append(self._write_simple_report("duplicate_suspects", self._duplicate_rows()))
        paths.append(self._write_simple_report("possible_1099_vendors", self._vendor_1099_rows()))
        paths.append(self._write_simple_report("expenses_missing_business_purpose", self._missing_business_purpose_rows()))
        paths.append(self._write_simple_report("entries_missing_payment_account", self._missing_payment_rows()))
        paths.append(self._write_simple_report("processing_failures", self._failed_rows()))
        return paths

    def list_reports(self) -> list[dict[str, Any]]:
        rows = self.store.list_generated_reports()
        return [{k: row[k] for k in row.keys()} for row in rows]

    def _write_simple_report(self, report_type: str, rows: list[dict[str, Any]]) -> Path:
        path = self.reports_dir / f"{report_type}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        if rows:
            keys = sorted(rows[0].keys())
        else:
            keys = ["message"]
            rows = [{"message": "No rows"}]

        with path.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=keys)
            writer.writeheader()
            writer.writerows(rows)

        self.store.add_generated_report(
            report_type=report_type,
            file_path=str(path),
            period=None,
        )
        return path

    def _uncategorized_rows(self) -> list[dict[str, Any]]:
        out = []
        for row in self.store.list_documents(limit=50000):
            proposal = self._proposal(row)
            if row["state"] in {"rejected", "duplicate", "archived"}:
                continue
            if proposal.get("category"):
                continue
            out.append(self._document_row(row, reason="missing category"))
        return out

    def _missing_receipts_rows(self) -> list[dict[str, Any]]:
        out = []
        for row in self.store.list_documents(limit=50000):
            proposal = self._proposal(row)
            if row["state"] not in {"approved", "approved-with-edits", "auto-posted"}:
                continue
            if proposal.get("receipt") == "Yes" and proposal.get("receipt_link_file"):
                continue
            out.append(self._document_row(row, reason="receipt missing or unlinked"))
        return out

    def _duplicate_rows(self) -> list[dict[str, Any]]:
        out = []
        for row in self.store.list_duplicate_candidates(status="open"):
            out.append(
                {
                    "candidate_id": row["id"],
                    "document_id": row["document_id"],
                    "candidate_document_id": row["candidate_document_id"],
                    "score": row["score"],
                    "reason": row["reason"],
                    "file_a": row["file_path_a"],
                    "file_b": row["file_path_b"],
                }
            )
        return out

    def _vendor_1099_rows(self) -> list[dict[str, Any]]:
        out = []
        for row in self.store.list_vendor_candidates():
            if row["eligible_1099"] != "Yes":
                continue
            out.append({k: row[k] for k in row.keys()})
        return out

    def _missing_business_purpose_rows(self) -> list[dict[str, Any]]:
        out = []
        for row in self.store.list_documents(limit=50000):
            proposal = self._proposal(row)
            if row["state"] not in {"approved", "approved-with-edits", "auto-posted", "needs-review", "new"}:
                continue
            if proposal.get("business_purpose"):
                continue
            out.append(self._document_row(row, reason="missing business purpose"))
        return out

    def _missing_payment_rows(self) -> list[dict[str, Any]]:
        out = []
        for row in self.store.list_documents(limit=50000):
            proposal = self._proposal(row)
            if row["state"] in {"rejected", "duplicate", "archived"}:
                continue
            if proposal.get("payment_method") and proposal.get("account_card"):
                continue
            out.append(self._document_row(row, reason="missing payment method/account"))
        return out

    def _failed_rows(self) -> list[dict[str, Any]]:
        out = []
        for row in self.store.list_documents(limit=50000):
            if row["state"] != "failed":
                continue
            out.append(self._document_row(row, reason=row["last_error"] or "failed"))
        return out

    @staticmethod
    def _proposal(row) -> dict[str, Any]:
        import json

        raw = row["proposed_entry_json"]
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception:
            return {}

    @staticmethod
    def _category(row) -> str:
        proposal = ReportService._proposal(row)
        return proposal.get("category") or "Uncategorized"

    @staticmethod
    def _document_row(row, *, reason: str) -> dict[str, Any]:
        return {
            "document_id": row["id"],
            "file_path": row["file_path"],
            "vendor": row["vendor"],
            "doc_date": row["doc_date"],
            "amount": row["amount"],
            "state": row["state"],
            "reason": reason,
        }
