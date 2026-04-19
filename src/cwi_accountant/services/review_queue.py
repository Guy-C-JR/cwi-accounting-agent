from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from cwi_accountant.db import StateStore


class ReviewQueueService:
    def __init__(self, store: StateStore):
        self.store = store

    def dashboard_metrics(self) -> dict[str, int]:
        return self.store.dashboard_metrics()

    def queue(
        self,
        *,
        confidence_threshold: float,
        date_from: date | None = None,
        date_to: date | None = None,
        vendor: str | None = None,
        amount_min: Decimal | None = None,
        amount_max: Decimal | None = None,
        category: str | None = None,
        status: str | None = None,
        doc_type: str | None = None,
        posted: str | None = None,
        include_deferred: bool = False,
    ) -> list[dict[str, Any]]:
        rows = self.store.list_review_queue(
            confidence_threshold=confidence_threshold,
            include_deferred=include_deferred,
            limit=2000,
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            if date_from and row["doc_date"] and row["doc_date"] < date_from.isoformat():
                continue
            if date_to and row["doc_date"] and row["doc_date"] > date_to.isoformat():
                continue
            if vendor and vendor.lower() not in str(row["vendor"] or "").lower():
                continue
            if amount_min is not None and row["amount"] is not None and Decimal(row["amount"]) < amount_min:
                continue
            if amount_max is not None and row["amount"] is not None and Decimal(row["amount"]) > amount_max:
                continue
            if status and status != row["state"]:
                continue
            if doc_type and doc_type != row["document_type"]:
                continue
            if posted == "posted" and row["posted_row"] is None:
                continue
            if posted == "review-only" and row["posted_row"] is not None:
                continue
            if category and category.lower() not in str(row["proposed_entry_json"] or "").lower():
                continue
            out.append({k: row[k] for k in row.keys()})
        return out

    def recent_errors(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.store.list_documents(limit=2000)
        errors = [
            {k: r[k] for k in r.keys()}
            for r in rows
            if r["last_error"]
        ]
        return errors[:limit]

    def recent_writes(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.store.list_audit_events(limit=limit)
        return [{k: r[k] for k in r.keys()} for r in rows if r["sheet_name"]]
