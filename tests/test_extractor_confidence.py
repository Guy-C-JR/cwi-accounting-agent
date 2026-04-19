from pathlib import Path

from cwi_accountant.parsing.extractor import DocumentExtractor


def test_field_confidence_high_for_explicit_invoice_fields() -> None:
    extractor = DocumentExtractor()
    text = """
    Invoice #INV-1001
    Vendor: OpenAI
    Date: 2026-02-14
    Amount Due: $42.50
    Payment Method: Credit Card
    Description: API usage for product development
    """
    fields = extractor._extract_fields(text, Path("/tmp/invoice.pdf"))
    overall = extractor._overall_confidence(fields)

    assert fields["vendor"].confidence >= 0.9
    assert fields["date"].confidence >= 0.9
    assert fields["amount"].confidence >= 0.9
    assert fields["document_type"].confidence >= 0.9
    assert overall >= 0.9


def test_field_confidence_low_for_ambiguous_text() -> None:
    extractor = DocumentExtractor()
    text = "Charge posted 42.50. Thanks."
    fields = extractor._extract_fields(text, Path("/tmp/random.txt"))
    overall = extractor._overall_confidence(fields)
    reason = extractor._review_reason(fields, overall)

    assert fields["vendor"].confidence < 0.78
    assert fields["date"].confidence < 0.78
    assert reason is not None
