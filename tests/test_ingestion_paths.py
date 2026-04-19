from pathlib import Path

from cwi_accountant.config import AgentConfig, AppPaths
from cwi_accountant.services.ingestion import IngestionService


def _service(tmp_path: Path) -> IngestionService:
    docs_root = tmp_path / "sample-documents"
    app_root = tmp_path / "agent"
    config = AgentConfig(
        paths=AppPaths(
            docs_root=docs_root,
            workbook_path=docs_root / "CWI_Expense_Tracker_Numbers_Mac_Compatible.xlsx",
            sqlite_path=app_root / "data" / "state.db",
            logs_dir=app_root / "logs",
            reports_dir=app_root / "reports",
            backups_dir=app_root / "backups",
        )
    )
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


def test_exclusion_keeps_invoice_paths_in_scope(tmp_path: Path) -> None:
    service = _service(tmp_path)
    invoice = service.config.paths.docs_root / "Invoices" / "invoice-001.pdf"
    assert service._should_exclude_path(invoice) is False


def test_exclusion_blocks_internal_operational_paths(tmp_path: Path) -> None:
    service = _service(tmp_path)

    workbook = service.config.paths.workbook_path
    sqlite = service.config.paths.sqlite_path
    log_file = service.config.paths.logs_dir / "agent.log"

    assert service._should_exclude_path(workbook) is True
    assert service._should_exclude_path(sqlite) is True
    assert service._should_exclude_path(log_file) is True
