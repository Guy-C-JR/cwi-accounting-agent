from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from rapidfuzz import fuzz

from cwi_accountant.db import StateStore
from cwi_accountant.models import VendorCandidate
from cwi_accountant.utils import normalize_vendor_name


class VendorService:
    def __init__(self, store: StateStore):
        self.store = store

    def refresh_candidates_from_documents(self) -> int:
        docs = self.store.list_documents(limit=20000)
        grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "vendor_name": "",
            "doc_ids": [],
            "spend": Decimal("0.00"),
            "count": 0,
        })

        for doc in docs:
            if not doc["vendor"]:
                continue
            norm = normalize_vendor_name(doc["vendor"])
            if not norm:
                continue
            group = grouped[norm]
            group["vendor_name"] = doc["vendor"]
            group["doc_ids"].append(int(doc["id"]))
            if doc["amount"]:
                group["spend"] += Decimal(doc["amount"])
            group["count"] += 1

        created = 0
        for norm, payload in grouped.items():
            vendor_type = self._infer_vendor_type(payload["vendor_name"])
            eligible_1099 = self._infer_1099(vendor_type, payload["spend"])
            candidate = VendorCandidate(
                vendor_name=payload["vendor_name"],
                normalized_name=norm,
                vendor_type=vendor_type,
                eligible_1099=eligible_1099,
                tax_form_needed=("Yes" if eligible_1099 == "Yes" else None),
                status="Active",
                notes=f"Auto-derived from {payload['count']} documents",
                source_document_ids=sorted(payload["doc_ids"]),
            )
            self.store.upsert_vendor_candidate(candidate)
            created += 1
        return created

    def list_candidates(self) -> list[dict[str, Any]]:
        rows = self.store.list_vendor_candidates()
        return [{k: row[k] for k in row.keys()} for row in rows]

    def find_variants(self, threshold: int = 86) -> list[dict[str, Any]]:
        rows = self.store.list_vendor_candidates()
        variants: list[dict[str, Any]] = []
        for idx in range(len(rows)):
            for jdx in range(idx + 1, len(rows)):
                a, b = rows[idx], rows[jdx]
                score = fuzz.ratio(a["normalized_name"], b["normalized_name"])
                if score >= threshold:
                    variants.append(
                        {
                            "a": a["vendor_name"],
                            "a_norm": a["normalized_name"],
                            "b": b["vendor_name"],
                            "b_norm": b["normalized_name"],
                            "score": score,
                        }
                    )
        variants.sort(key=lambda item: item["score"], reverse=True)
        return variants

    def merge(self, source_normalized: str, target_normalized: str, target_name: str) -> None:
        self.store.merge_vendor_candidates(source_normalized, target_normalized, target_name)

    @staticmethod
    def _infer_vendor_type(vendor_name: str) -> str:
        name = vendor_name.lower()
        if any(k in name for k in ["llc", "inc", "corp"]):
            return "Professional Service"
        if any(k in name for k in ["bank", "stripe", "square", "paypal"]):
            return "Bank / Processor"
        if any(k in name for k in ["irs", "state", "treasury"]):
            return "Government / Tax"
        if any(k in name for k in ["amazon", "walmart", "costco", "target"]):
            return "Other"
        return "Other"

    @staticmethod
    def _infer_1099(vendor_type: str, spend: Decimal) -> str | None:
        if vendor_type in {"Professional Service", "Contractor"} and spend >= Decimal("600"):
            return "Yes"
        if vendor_type in {"Government / Tax", "Bank / Processor"}:
            return "No"
        return None
