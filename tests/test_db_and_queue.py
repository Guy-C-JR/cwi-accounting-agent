from pathlib import Path

from cwi_accountant.db import StateStore
from cwi_accountant.models import DocumentRecord, ProposedExpenseEntry


def test_upsert_and_queue(tmp_path: Path) -> None:
    db = StateStore(tmp_path / "state.db")
    doc = DocumentRecord(
        file_path="/tmp/a.pdf",
        file_hash="abc",
        file_mtime=1.0,
        file_size=100,
        file_type="pdf",
        document_type="invoice",
        vendor="Vendor A",
        confidence_overall=0.4,
        needs_review=True,
        state="needs-review",
    )
    doc_id = db.upsert_document(doc, ProposedExpenseEntry(vendor="Vendor A"))
    assert doc_id > 0

    queue = db.list_review_queue(confidence_threshold=0.75)
    ids = [int(row["id"]) for row in queue]
    assert doc_id in ids
