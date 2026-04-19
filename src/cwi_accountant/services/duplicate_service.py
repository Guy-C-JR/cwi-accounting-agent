from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from rapidfuzz import fuzz

from cwi_accountant.db import StateStore
from cwi_accountant.models import DuplicateCandidate
from cwi_accountant.utils import normalize_vendor_name


class DuplicateService:
    def __init__(self, store: StateStore):
        self.store = store

    def detect(self) -> int:
        rows = self.store.list_documents(limit=20000)
        inserted = 0

        by_hash: dict[str, list] = {}
        for row in rows:
            by_hash.setdefault(row["file_hash"], []).append(row)

        for _, group in by_hash.items():
            if len(group) < 2:
                continue
            for idx in range(len(group)):
                for jdx in range(idx + 1, len(group)):
                    left, right = group[idx], group[jdx]
                    candidate = DuplicateCandidate(
                        document_id=left["id"],
                        candidate_document_id=right["id"],
                        score=1.0,
                        reason="Exact file hash match",
                    )
                    self.store.add_duplicate_candidate(candidate)
                    inserted += 1

        for idx in range(len(rows)):
            for jdx in range(idx + 1, len(rows)):
                left, right = rows[idx], rows[jdx]
                if left["id"] == right["id"]:
                    continue
                if left["file_hash"] == right["file_hash"]:
                    continue

                score = self._similarity_score(left, right)
                if score < 0.86:
                    continue

                reason = self._build_reason(left, right, score)
                candidate = DuplicateCandidate(
                    document_id=left["id"],
                    candidate_document_id=right["id"],
                    score=score,
                    reason=reason,
                )
                self.store.add_duplicate_candidate(candidate)
                inserted += 1

        return inserted

    def resolve(
        self,
        *,
        candidate_id: int,
        action: str,
        merge_notes: str | None = None,
    ) -> dict[str, str]:
        candidates = self.store.list_duplicate_candidates()
        item = next((row for row in candidates if row["id"] == candidate_id), None)
        if item is None:
            return {"status": "not-found"}

        doc_a, doc_b = int(item["document_id"]), int(item["candidate_document_id"])

        if action == "keep-newest-only":
            newest_id = self._pick_newest(item)
            older_id = doc_b if newest_id == doc_a else doc_a
            self.store.update_document_state(
                older_id,
                state="duplicate",
                needs_review=False,
                review_reason=f"Resolved duplicate against document {newest_id}",
            )
            self.store.resolve_duplicate_pair(candidate_id, "resolved")
            return {"status": "resolved", "kept": str(newest_id), "dropped": str(older_id)}

        if action == "keep-existing-only":
            existing_id = self._pick_existing(item)
            other_id = doc_b if existing_id == doc_a else doc_a
            self.store.update_document_state(
                other_id,
                state="duplicate",
                needs_review=False,
                review_reason=f"Resolved duplicate against posted document {existing_id}",
            )
            self.store.resolve_duplicate_pair(candidate_id, "resolved")
            return {"status": "resolved", "kept": str(existing_id), "dropped": str(other_id)}

        if action == "keep-both":
            self.store.resolve_duplicate_pair(candidate_id, "keep-both")
            return {"status": "resolved", "decision": "keep-both"}

        if action == "merge-notes":
            notes = merge_notes or "Duplicate review notes merged"
            self.store.update_document_state(
                doc_a,
                state="needs-review",
                needs_review=True,
                review_reason=notes,
            )
            self.store.update_document_state(
                doc_b,
                state="needs-review",
                needs_review=True,
                review_reason=notes,
            )
            self.store.resolve_duplicate_pair(candidate_id, "merged-notes")
            return {"status": "resolved", "decision": "merge-notes"}

        if action == "false-positive":
            self.store.resolve_duplicate_pair(candidate_id, "false-positive")
            return {"status": "resolved", "decision": "false-positive"}

        return {"status": "unknown-action"}

    @staticmethod
    def _pick_newest(candidate_row) -> int:
        date_a = datetime.fromisoformat(candidate_row["date_a"]) if candidate_row["date_a"] else datetime.min
        date_b = datetime.fromisoformat(candidate_row["date_b"]) if candidate_row["date_b"] else datetime.min
        return int(candidate_row["document_id"] if date_a >= date_b else candidate_row["candidate_document_id"])

    @staticmethod
    def _pick_existing(candidate_row) -> int:
        if candidate_row["state_a"] in {"approved", "approved-with-edits", "auto-posted"}:
            return int(candidate_row["document_id"])
        if candidate_row["state_b"] in {"approved", "approved-with-edits", "auto-posted"}:
            return int(candidate_row["candidate_document_id"])
        return int(candidate_row["document_id"])

    @staticmethod
    def _similarity_score(left, right) -> float:
        vendor_l = normalize_vendor_name(left["vendor"])
        vendor_r = normalize_vendor_name(right["vendor"])
        vendor_score = fuzz.ratio(vendor_l, vendor_r) / 100 if vendor_l and vendor_r else 0

        amount_score = 0.0
        if left["amount"] and right["amount"]:
            a, b = Decimal(left["amount"]), Decimal(right["amount"])
            amount_score = 1.0 if a == b else (0.8 if abs(a - b) <= Decimal("1.00") else 0.0)

        date_score = 0.0
        if left["doc_date"] and right["doc_date"]:
            date_score = 1.0 if left["doc_date"] == right["doc_date"] else 0.0

        hash_score = 1.0 if left["file_hash"] == right["file_hash"] else 0.0

        return (vendor_score * 0.4) + (amount_score * 0.35) + (date_score * 0.2) + (hash_score * 0.05)

    @staticmethod
    def _build_reason(left, right, score: float) -> str:
        parts: list[str] = [f"similarity={score:.2f}"]
        if normalize_vendor_name(left["vendor"]) == normalize_vendor_name(right["vendor"]):
            parts.append("vendor match")
        if left["amount"] and right["amount"] and Decimal(left["amount"]) == Decimal(right["amount"]):
            parts.append("amount match")
        if left["doc_date"] and right["doc_date"] and left["doc_date"] == right["doc_date"]:
            parts.append("date match")
        return ", ".join(parts)
