from datetime import date
from decimal import Decimal

from cwi_accountant.config import AgentConfig, AutoPostVendorPolicy
from cwi_accountant.models import DocumentRecord, ExtractedField, ProposedExpenseEntry
from cwi_accountant.services.ingestion import IngestionService


def _service(config: AgentConfig) -> IngestionService:
    return IngestionService(
        config=config,
        store=None,
        extractor=None,
        mapper=None,
        writeback=None,
        duplicate_service=None,
        vendor_service=None,
        recurring_service=None,
    )


def _document(overall: float = 0.99, critical: float = 0.97) -> DocumentRecord:
    fields = {
        "vendor": ExtractedField(name="vendor", value="OpenAI", confidence=critical, source="explicit"),
        "date": ExtractedField(name="date", value="2026-02-14", confidence=critical, source="explicit"),
        "amount": ExtractedField(name="amount", value="42.50", confidence=critical, source="explicit"),
        "document_type": ExtractedField(name="document_type", value="invoice", confidence=critical, source="content"),
    }
    return DocumentRecord(
        file_path="/tmp/doc.pdf",
        file_hash="abc",
        file_mtime=1.0,
        file_size=100,
        file_type="pdf",
        document_type="invoice",
        vendor="OpenAI",
        doc_date=date(2026, 2, 14),
        amount=Decimal("42.50"),
        extracted_fields=fields,
        confidence_overall=overall,
        state="new",
        needs_review=False,
    )


def _entry(category: str = "Software / SaaS") -> ProposedExpenseEntry:
    return ProposedExpenseEntry(
        date=date(2026, 2, 14),
        vendor="OpenAI",
        category=category,
        subcategory="AI/API Usage",
        description="API usage",
        payment_method="Credit Card",
        amount="42.50",
        tax_deductible="Yes",
        receipt="Yes",
        receipt_link_file="/tmp/doc.pdf",
        business_purpose="Product development",
    )


def _strict_config() -> AgentConfig:
    return AgentConfig(
        auto_post_enabled=True,
        auto_post_threshold=0.95,
        auto_post_min_critical_confidence=0.90,
        trusted_vendors_for_bulk_approve=["OpenAI"],
        auto_post_vendor_category_policies=[
            AutoPostVendorPolicy(
                vendor="OpenAI",
                allowed_categories=["Software / SaaS"],
                min_overall_confidence=0.98,
                min_critical_confidence=0.95,
                max_amount=Decimal("500.00"),
                require_receipt_link=True,
                require_payment_method=True,
                require_business_purpose=True,
                require_tax_deductible_explicit=True,
            )
        ],
    )


def test_autopost_policy_allows_strict_match() -> None:
    service = _service(_strict_config())
    allowed, reason = service._evaluate_auto_post_gate(
        document=_document(),
        entry=_entry(),
        needs_review=False,
    )
    assert allowed is True
    assert "vendor policy matched" in reason


def test_autopost_policy_blocks_category_mismatch() -> None:
    service = _service(_strict_config())
    allowed, reason = service._evaluate_auto_post_gate(
        document=_document(),
        entry=_entry(category="Travel"),
        needs_review=False,
    )
    assert allowed is False
    assert "not allowed by vendor policy" in reason


def test_autopost_policy_blocks_weak_critical_confidence() -> None:
    service = _service(_strict_config())
    allowed, reason = service._evaluate_auto_post_gate(
        document=_document(overall=0.99, critical=0.82),
        entry=_entry(),
        needs_review=False,
    )
    assert allowed is False
    assert "critical confidence floor" in reason


def test_autopost_policy_blocks_missing_vendor_policy() -> None:
    config = _strict_config()
    config.auto_post_vendor_category_policies = []
    service = _service(config)
    allowed, reason = service._evaluate_auto_post_gate(
        document=_document(),
        entry=_entry(),
        needs_review=False,
    )
    assert allowed is False
    assert "no vendor policy configured" in reason
