from pathlib import Path

from cwi_accountant.db import StateStore
from cwi_accountant.models import DocumentRecord, ProposedExpenseEntry
from cwi_accountant.services.duplicate_service import DuplicateService


def test_duplicate_detection_hash_match(tmp_path: Path) -> None:
    db = StateStore(tmp_path / "state.db")
    a = DocumentRecord(
        file_path="/tmp/a.pdf",
        file_hash="samehash",
        file_mtime=1.0,
        file_size=100,
        file_type="pdf",
        document_type="invoice",
        vendor="Vendor A",
        confidence_overall=0.9,
        needs_review=False,
        state="new",
    )
    b = DocumentRecord(
        file_path="/tmp/b.pdf",
        file_hash="samehash",
        file_mtime=2.0,
        file_size=120,
        file_type="pdf",
        document_type="invoice",
        vendor="Vendor A",
        confidence_overall=0.9,
        needs_review=False,
        state="new",
    )
    db.upsert_document(a, ProposedExpenseEntry(vendor="Vendor A"))
    db.upsert_document(b, ProposedExpenseEntry(vendor="Vendor A"))

    service = DuplicateService(db)
    inserted = service.detect()
    assert inserted >= 1
    assert len(db.list_duplicate_candidates()) >= 1
