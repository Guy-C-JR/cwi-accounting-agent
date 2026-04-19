from __future__ import annotations

from dataclasses import dataclass

from cwi_accountant.config import AgentConfig
from cwi_accountant.db import StateStore
from cwi_accountant.parsing.extractor import DocumentExtractor
from cwi_accountant.reporting.reports import ReportService
from cwi_accountant.services.category_mapper import CategoryMapper
from cwi_accountant.services.duplicate_service import DuplicateService
from cwi_accountant.services.ingestion import IngestionService
from cwi_accountant.services.recurring_service import RecurringService
from cwi_accountant.services.review_queue import ReviewQueueService
from cwi_accountant.services.vendor_service import VendorService
from cwi_accountant.services.writeback import WritebackService
from cwi_accountant.workbook import WorkbookGateway


@dataclass(slots=True)
class AppServices:
    store: StateStore
    workbook: WorkbookGateway
    extractor: DocumentExtractor
    mapper: CategoryMapper
    writeback: WritebackService
    duplicate_service: DuplicateService
    vendor_service: VendorService
    recurring_service: RecurringService
    review_queue: ReviewQueueService
    report_service: ReportService
    ingestion: IngestionService


def build_services(config: AgentConfig) -> AppServices:
    store = StateStore(config.paths.sqlite_path)
    workbook = WorkbookGateway(
        workbook_path=config.paths.workbook_path,
        backups_dir=config.paths.backups_dir,
    )
    mapper = CategoryMapper(workbook.load_lists())
    extractor = DocumentExtractor()
    duplicate_service = DuplicateService(store)
    vendor_service = VendorService(store)
    recurring_service = RecurringService(store, workbook)
    writeback = WritebackService(store=store, workbook=workbook, mapper=mapper)
    review_queue = ReviewQueueService(store)
    report_service = ReportService(store=store, reports_dir=config.paths.reports_dir)
    ingestion = IngestionService(
        config=config,
        store=store,
        extractor=extractor,
        mapper=mapper,
        writeback=writeback,
        duplicate_service=duplicate_service,
        vendor_service=vendor_service,
        recurring_service=recurring_service,
    )
    return AppServices(
        store=store,
        workbook=workbook,
        extractor=extractor,
        mapper=mapper,
        writeback=writeback,
        duplicate_service=duplicate_service,
        vendor_service=vendor_service,
        recurring_service=recurring_service,
        review_queue=review_queue,
        report_service=report_service,
        ingestion=ingestion,
    )
