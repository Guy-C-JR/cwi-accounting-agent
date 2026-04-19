from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from statistics import median
from typing import Any

from cwi_accountant.db import StateStore
from cwi_accountant.models import RecurringBillCandidate
from cwi_accountant.workbook import WorkbookGateway


class RecurringService:
    def __init__(self, store: StateStore, workbook: WorkbookGateway):
        self.store = store
        self.workbook = workbook

    def refresh_candidates(self) -> int:
        docs = self.store.list_documents(limit=20000)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for doc in docs:
            if not doc["vendor"] or not doc["doc_date"] or not doc["amount"]:
                continue
            if doc["state"] in {"rejected", "duplicate", "archived"}:
                continue
            expense_name = self._expense_name(doc)
            key = f"{doc['vendor']}::{expense_name}"
            grouped[key].append({k: doc[k] for k in doc.keys()})

        upserted = 0
        for key, items in grouped.items():
            if len(items) < 2:
                continue
            items.sort(key=lambda row: row["doc_date"])
            freq, confidence = self._frequency_and_confidence(items)
            if confidence < 0.65:
                continue

            vendor, expense_name = key.split("::", 1)
            candidate = RecurringBillCandidate(
                vendor=vendor,
                expense_name=expense_name,
                category=self._category_from_proposed(items[-1].get("proposed_entry_json")),
                amount=Decimal(items[-1]["amount"]),
                frequency=freq,
                due_day=datetime.fromisoformat(items[-1]["doc_date"]).day,
                first_seen=datetime.fromisoformat(items[0]["doc_date"]).date(),
                last_seen=datetime.fromisoformat(items[-1]["doc_date"]).date(),
                source_document_ids=[int(i["id"]) for i in items],
                confidence=confidence,
                status="new",
            )
            self.store.upsert_recurring_candidate(candidate)
            upserted += 1
        return upserted

    def list_candidates(self) -> list[dict[str, Any]]:
        rows = self.store.list_recurring_candidates()
        return [{k: row[k] for k in row.keys()} for row in rows]

    def approve_candidate(
        self,
        *,
        candidate_id: int,
        frequency: str | None = None,
        due_day: int | None = None,
    ) -> dict[str, Any]:
        row = next((x for x in self.store.list_recurring_candidates() if x["id"] == candidate_id), None)
        if row is None:
            return {"status": "not-found"}

        candidate = RecurringBillCandidate(
            id=row["id"],
            vendor=row["vendor"],
            expense_name=row["expense_name"],
            category=row["category"],
            amount=Decimal(row["amount"]) if row["amount"] else None,
            frequency=frequency or row["frequency"],
            due_day=due_day or row["due_day"],
            first_seen=datetime.fromisoformat(row["first_seen"]).date() if row["first_seen"] else None,
            last_seen=datetime.fromisoformat(row["last_seen"]).date() if row["last_seen"] else None,
            source_document_ids=[],
            confidence=row["confidence"],
            status="approved",
        )

        write = self.workbook.upsert_recurring_bill(candidate)
        self.store.update_recurring_candidate_status(candidate_id, status="approved", linked_row=write.row_number)
        return {"status": "approved", "row": write.row_number}

    def reject_candidate(self, candidate_id: int) -> None:
        self.store.update_recurring_candidate_status(candidate_id, status="rejected")

    @staticmethod
    def _expense_name(doc: dict[str, Any]) -> str:
        description = RecurringService._value(doc, "description")
        if description:
            return str(description)[:80]
        doc_type = str(RecurringService._value(doc, "document_type") or "expense").replace("_", " ")
        return doc_type

    @staticmethod
    def _value(doc: Any, key: str) -> Any:
        if isinstance(doc, dict):
            return doc.get(key)
        try:
            return doc[key]
        except Exception:
            return None

    @staticmethod
    def _frequency_and_confidence(items: list[dict[str, Any]]) -> tuple[str, float]:
        dates = [datetime.fromisoformat(i["doc_date"]).date() for i in items if i["doc_date"]]
        if len(dates) < 2:
            return "As Needed", 0.0
        intervals = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        avg = median(intervals)
        if 27 <= avg <= 33:
            return "Monthly", 0.9
        if 85 <= avg <= 95:
            return "Quarterly", 0.85
        if 350 <= avg <= 380:
            return "Annual", 0.85
        if 6 <= avg <= 8:
            return "Weekly", 0.8
        return "As Needed", 0.6

    @staticmethod
    def _category_from_proposed(proposed_json: str | None) -> str | None:
        if not proposed_json:
            return None
        import json

        try:
            payload = json.loads(proposed_json)
        except Exception:
            return None
        return payload.get("category")
