from pathlib import Path

from cwi_accountant.config import AgentConfig, AppPaths
from cwi_accountant.db import StateStore
from cwi_accountant.models import DocumentRecord
from cwi_accountant.services.ingestion import IngestionService


class _DummyExtractor:
    called = False

    def extract(self, path: Path):
        self.called = True
        raise RuntimeError("forced")


def _service(tmp_path: Path, store: StateStore, extractor: _DummyExtractor) -> IngestionService:
    docs_root = tmp_path / "docs"
    docs_root.mkdir(parents=True, exist_ok=True)
    cfg = AgentConfig(
        paths=AppPaths(
            docs_root=docs_root,
            workbook_path=tmp_path / "tracker.xlsx",
            sqlite_path=tmp_path / "data" / "state.db",
            logs_dir=tmp_path / "logs",
            reports_dir=tmp_path / "reports",
            backups_dir=tmp_path / "backups",
        )
    )
    return IngestionService(
        config=cfg,
        store=store,
        extractor=extractor,
        mapper=None,
        writeback=None,
        duplicate_service=None,
        vendor_service=None,
        recurring_service=None,
    )


def test_state_new_forces_reprocess_even_if_same_size_mtime(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs"
    docs_root.mkdir(parents=True, exist_ok=True)
    f = docs_root / "sample.pdf"
    f.write_bytes(b"x")

    store = StateStore(tmp_path / "data" / "state.db")
    stat = f.stat()
    doc = DocumentRecord(
        file_path=str(f),
        file_hash="abc",
        file_mtime=stat.st_mtime,
        file_size=stat.st_size,
        file_type="pdf",
        document_type="invoice",
        confidence_overall=0.0,
        state="new",
        needs_review=True,
    )
    store.upsert_document(doc, proposed_entry=None)

    extractor = _DummyExtractor()
    service = _service(tmp_path, store, extractor)
    service.process_file(f)

    assert extractor.called is True
