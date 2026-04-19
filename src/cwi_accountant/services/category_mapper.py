from __future__ import annotations

import re
from dataclasses import dataclass

from cwi_accountant.models import ProposedExpenseEntry


@dataclass(slots=True)
class CanonicalLists:
    categories: list[str]
    subcategories: list[str]
    payment_methods: list[str]
    yes_no: list[str]
    vendor_types: list[str]
    frequencies: list[str]
    statuses: list[str]


class CategoryMapper:
    def __init__(self, lists: CanonicalLists):
        self.lists = lists

    def apply(self, entry: ProposedExpenseEntry) -> ProposedExpenseEntry:
        if not entry.category:
            entry.category = self._infer_category(entry)
        if not entry.subcategory:
            entry.subcategory = self._infer_subcategory(entry)
        if entry.payment_method:
            entry.payment_method = self._canonicalize(entry.payment_method, self.lists.payment_methods)
        if entry.tax_deductible:
            entry.tax_deductible = self._canonical_yes_no_like(entry.tax_deductible)
        if entry.receipt:
            entry.receipt = self._canonical_yes_no_like(entry.receipt)
        if entry.billable_to_client:
            entry.billable_to_client = self._canonical_yes_no_like(entry.billable_to_client)
        if entry.recurring:
            entry.recurring = self._canonical_yes_no_like(entry.recurring)
        return entry

    def validate(self, entry: ProposedExpenseEntry) -> list[str]:
        errors: list[str] = []
        if entry.category and entry.category not in self.lists.categories:
            errors.append(f"Category '{entry.category}' not in Lists sheet")
        if entry.subcategory and entry.subcategory not in self.lists.subcategories:
            errors.append(f"Subcategory '{entry.subcategory}' not in Lists sheet")
        if entry.payment_method and entry.payment_method not in self.lists.payment_methods:
            errors.append(f"Payment Method '{entry.payment_method}' not in Lists sheet")
        for field_name in ["tax_deductible", "receipt", "billable_to_client", "recurring"]:
            value = getattr(entry, field_name)
            if value and value not in self.lists.yes_no and value not in {"Review"}:
                errors.append(f"{field_name} value '{value}' is invalid")
        return errors

    def _infer_category(self, entry: ProposedExpenseEntry) -> str | None:
        text = f"{entry.description or ''} {entry.vendor or ''}".lower()
        keyword_map = {
            "hosting": "Software / SaaS",
            "api": "Software / SaaS",
            "cloud": "Software / SaaS",
            "domain": "Licenses / Registrations",
            "ad": "Advertising / Marketing",
            "google ads": "Advertising / Marketing",
            "meta ads": "Advertising / Marketing",
            "tax": "Taxes",
            "insurance": "Insurance",
            "internet": "Internet / Phone",
            "phone": "Internet / Phone",
            "equipment": "Equipment",
            "office": "Office Supplies",
            "travel": "Travel",
            "meal": "Meals",
        }
        for key, mapped in keyword_map.items():
            if key in text:
                return self._canonicalize(mapped, self.lists.categories)
        return None

    def _infer_subcategory(self, entry: ProposedExpenseEntry) -> str | None:
        text = f"{entry.description or ''} {entry.vendor or ''}".lower()
        keyword_map = {
            "api": "AI/API Usage",
            "domain": "Domain",
            "license": "Software License",
            "subscription": "Subscription",
            "consult": "Consulting",
            "bank": "Bank Fee",
            "hosting": "Hosting",
        }
        for key, mapped in keyword_map.items():
            if key in text:
                return self._canonicalize(mapped, self.lists.subcategories)
        return None

    def _canonical_yes_no_like(self, value: str) -> str:
        val = value.strip().lower()
        if val in {"y", "yes", "true", "1"}:
            return "Yes" if "Yes" in self.lists.yes_no else self.lists.yes_no[0]
        if val in {"n", "no", "false", "0"}:
            return "No" if "No" in self.lists.yes_no else self.lists.yes_no[0]
        if val in {"review", "unknown", "maybe"}:
            return "Review"
        return value

    @staticmethod
    def _canonicalize(value: str, candidates: list[str]) -> str:
        if not value:
            return value
        for candidate in candidates:
            if value.lower() == candidate.lower():
                return candidate
        for candidate in candidates:
            if re.sub(r"\W+", "", value.lower()) == re.sub(r"\W+", "", candidate.lower()):
                return candidate
        return value
