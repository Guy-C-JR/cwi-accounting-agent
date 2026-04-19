from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Iterable

from cwi_accountant.config import AgentConfig, AutoPostVendorPolicy
from cwi_accountant.db import StateStore
from cwi_accountant.models import (
    AuditEvent,
    DocumentRecord,
    ProposedExpenseEntry,
    ReviewDecision,
)
from cwi_accountant.parsing.extractor import DocumentExtractor
from cwi_accountant.services.category_mapper import CategoryMapper
from cwi_accountant.services.duplicate_service import DuplicateService
from cwi_accountant.services.recurring_service import RecurringService
from cwi_accountant.services.vendor_service import VendorService
from cwi_accountant.services.writeback import WritebackError, WritebackService
from cwi_accountant.utils import is_supported_file, normalize_vendor_name


class IngestionService:
    def __init__(
        self,
        *,
        config: AgentConfig,
        store: StateStore,
        extractor: DocumentExtractor,
        mapper: CategoryMapper,
        writeback: WritebackService,
        duplicate_service: DuplicateService,
        vendor_service: VendorService,
        recurring_service: RecurringService,
    ):
        self.config = config
        self.store = store
        self.extractor = extractor
        self.mapper = mapper
        self.writeback = writeback
        self.duplicate_service = duplicate_service
        self.vendor_service = vendor_service
        self.recurring_service = recurring_service

    def scan_existing(self) -> dict[str, int]:
        processed = 0
        skipped = 0
        failed = 0

        for path in self._iter_supported_files(self.config.paths.docs_root):
            result = self.process_file(path)
            if result == "processed":
                processed += 1
            elif result == "skipped":
                skipped += 1
            else:
                failed += 1

        self.rebuild_indexes()
        return {"processed": processed, "skipped": skipped, "failed": failed}

    def process_file(self, path: Path) -> str:
        if not is_supported_file(path) or self._should_exclude_path(path):
            return "skipped"

        stat = path.stat()
        existing = self.store.get_document_by_path(str(path))
        if (
            existing
            and float(existing["file_mtime"]) == stat.st_mtime
            and int(existing["file_size"]) == stat.st_size
            and existing["state"] != "new"
        ):
            return "skipped"

        try:
            extraction = self.extractor.extract(path)
        except Exception as exc:
            failed_record = self._build_failed_record(path, str(exc))
            doc_id = self.store.upsert_document(failed_record, proposed_entry=None)
            self.store.update_document_state(
                doc_id,
                state="failed",
                needs_review=True,
                review_reason="Extraction failed; manual review required",
                last_error=str(exc),
            )
            self.store.add_audit_event(
                AuditEvent(
                    document_id=doc_id,
                    source_file=str(path),
                    action="extract-failed",
                    notes=str(exc),
                    auto_or_human="auto",
                )
            )
            return "failed"

        if existing and existing["file_hash"] == extraction.document.file_hash:
            return "skipped"

        mapped_entry = self.mapper.apply(extraction.proposed_entry)

        missing_critical = [
            not mapped_entry.vendor,
            mapped_entry.date is None,
            mapped_entry.amount is None,
            extraction.document.document_type in (None, ""),
        ]
        needs_review = any(missing_critical) or extraction.document.confidence_overall < self.config.low_confidence_threshold
        extraction.document.needs_review = needs_review
        extraction.document.state = "needs-review" if needs_review else "new"
        extraction.document.review_reason = "Missing critical fields" if any(missing_critical) else extraction.document.review_reason

        doc_id = self.store.upsert_document(extraction.document, mapped_entry)

        should_autopost, autopost_reason = self._evaluate_auto_post_gate(
            document=extraction.document,
            entry=mapped_entry,
            needs_review=needs_review,
        )
        if should_autopost:
            try:
                self.writeback.apply_decision(
                    ReviewDecision(
                        document_id=doc_id,
                        action="approve",
                        notes=f"Auto-posted via strict policy gate: {autopost_reason}",
                        decided_by="auto",
                    )
                )
                self.store.update_document_state(
                    doc_id,
                    state="auto-posted",
                    needs_review=False,
                    review_reason=None,
                )
            except WritebackError as exc:
                self.store.update_document_state(
                    doc_id,
                    state="needs-review",
                    needs_review=True,
                    review_reason=f"Auto-post blocked: {exc}",
                    last_error=str(exc),
                )
        elif self.config.auto_post_enabled:
            self.store.add_audit_event(
                AuditEvent(
                    document_id=doc_id,
                    source_file=str(path),
                    action="auto-post-skipped",
                    auto_or_human="auto",
                    notes=autopost_reason,
                )
            )

        self.store.add_audit_event(
            AuditEvent(
                document_id=doc_id,
                source_file=str(path),
                action="document-processed",
                confidence=extraction.document.confidence_overall,
                auto_or_human="auto",
                fields_written={
                    "vendor": extraction.document.vendor,
                    "date": extraction.document.doc_date.isoformat() if extraction.document.doc_date else None,
                    "amount": str(extraction.document.amount) if extraction.document.amount else None,
                    "document_type": extraction.document.document_type,
                },
                notes=extraction.document.review_reason,
            )
        )

        return "processed"

    def rebuild_indexes(self) -> dict[str, int]:
        duplicates = self.duplicate_service.detect()
        vendors = self.vendor_service.refresh_candidates_from_documents()
        recurring = self.recurring_service.refresh_candidates()
        self.store.add_audit_event(
            AuditEvent(
                action="rebuild-index",
                auto_or_human="auto",
                fields_written={
                    "duplicates": duplicates,
                    "vendors": vendors,
                    "recurring": recurring,
                },
            )
        )
        return {"duplicates": duplicates, "vendors": vendors, "recurring": recurring}

    def _evaluate_auto_post_gate(
        self,
        *,
        document: DocumentRecord,
        entry: ProposedExpenseEntry,
        needs_review: bool,
    ) -> tuple[bool, str]:
        if not self.config.auto_post_enabled:
            return False, "auto-post disabled in config"
        if needs_review:
            return False, "document marked for review"
        if document.confidence_overall < self.config.auto_post_threshold:
            return (
                False,
                f"overall confidence {document.confidence_overall:.2f} below "
                f"{self.config.auto_post_threshold:.2f}",
            )

        critical_scores = self._critical_confidences(document)
        min_critical = min(critical_scores.values())
        if min_critical < self.config.auto_post_min_critical_confidence:
            return (
                False,
                f"critical confidence floor {min_critical:.2f} below "
                f"{self.config.auto_post_min_critical_confidence:.2f}",
            )

        if not entry.vendor or not entry.category or not entry.date or entry.amount is None:
            return False, "missing required posting fields for auto-post"

        if entry.category in set(self.config.auto_post_blocked_categories):
            return False, f"category '{entry.category}' is blocked for auto-post"

        trusted_norm = {normalize_vendor_name(v) for v in self.config.trusted_vendors_for_bulk_approve}
        vendor_norm = normalize_vendor_name(entry.vendor)
        if vendor_norm not in trusted_norm:
            return False, f"vendor '{entry.vendor}' not in trusted auto-post list"

        policy = self._find_vendor_policy(vendor_norm)
        if policy is None:
            return False, f"no vendor policy configured for '{entry.vendor}'"

        if policy.allowed_categories and entry.category not in set(policy.allowed_categories):
            return (
                False,
                f"category '{entry.category}' not allowed by vendor policy "
                f"for '{policy.vendor}'",
            )

        if document.confidence_overall < policy.min_overall_confidence:
            return (
                False,
                f"overall confidence {document.confidence_overall:.2f} below policy "
                f"minimum {policy.min_overall_confidence:.2f}",
            )
        if min_critical < policy.min_critical_confidence:
            return (
                False,
                f"critical confidence {min_critical:.2f} below policy minimum "
                f"{policy.min_critical_confidence:.2f}",
            )

        if policy.max_amount is not None and entry.amount > policy.max_amount:
            return (
                False,
                f"amount {entry.amount} exceeds policy max {policy.max_amount}",
            )

        if policy.require_receipt_link and not entry.receipt_link_file:
            return False, "receipt link/file required by policy"
        if policy.require_payment_method and not entry.payment_method:
            return False, "payment method required by policy"
        if policy.require_business_purpose and not entry.business_purpose:
            return False, "business purpose required by policy"
        if policy.require_tax_deductible_explicit and entry.tax_deductible not in {"Yes", "No"}:
            return False, "tax deductible flag must be explicit Yes/No for auto-post"

        return True, f"vendor policy matched ({policy.vendor})"

    @staticmethod
    def _critical_confidences(document: DocumentRecord) -> dict[str, float]:
        critical = {}
        for field_name in ["vendor", "date", "amount", "document_type"]:
            extracted = document.extracted_fields.get(field_name)
            critical[field_name] = extracted.confidence if extracted else 0.0
        return critical

    def _find_vendor_policy(self, normalized_vendor: str) -> AutoPostVendorPolicy | None:
        for policy in self.config.auto_post_vendor_category_policies:
            if normalize_vendor_name(policy.vendor) == normalized_vendor:
                return policy
        return None

    def _iter_supported_files(self, root: Path) -> Iterable[Path]:
        for path in root.rglob("*"):
            if path.name.startswith("."):
                continue
            if is_supported_file(path) and not self._should_exclude_path(path):
                yield path

    def _should_exclude_path(self, path: Path) -> bool:
        resolved = path.resolve()
        workbook = self.config.paths.workbook_path.resolve()
        sqlite = self.config.paths.sqlite_path.resolve()
        sqlite_parent = sqlite.parent
        agent_root = Path(__file__).resolve().parents[3]
        excluded_roots = [
            self.config.paths.logs_dir.resolve(),
            self.config.paths.reports_dir.resolve(),
            self.config.paths.backups_dir.resolve(),
            sqlite_parent,
            agent_root,
        ]
        if resolved in {workbook, sqlite}:
            return True
        return any(self._is_under(resolved, ex) for ex in excluded_roots)

    @staticmethod
    def _is_under(path: Path, ancestor: Path) -> bool:
        try:
            path.relative_to(ancestor)
            return True
        except ValueError:
            return False

    @staticmethod
    def _build_failed_record(path: Path, error: str) -> DocumentRecord:
        stat = path.stat()
        synthetic_hash = hashlib.sha256(
            f"{path.resolve()}|{stat.st_mtime}|{stat.st_size}".encode("utf-8")
        ).hexdigest()
        return DocumentRecord(
            file_path=str(path),
            file_hash=synthetic_hash,
            file_mtime=stat.st_mtime,
            file_size=stat.st_size,
            file_type=path.suffix.lstrip(".").lower() or "unknown",
            document_type="unknown",
            confidence_overall=0.0,
            state="failed",
            needs_review=True,
            review_reason="Extraction failed; manual review required",
            description=f"Extraction error: {error}",
        )


class WatchEventHandler:
    def __init__(self, ingestion: IngestionService):
        self.ingestion = ingestion

    def on_created(self, path: str) -> None:
        self.ingestion.process_file(Path(path))

    def on_modified(self, path: str) -> None:
        self.ingestion.process_file(Path(path))


def run_watch(ingestion: IngestionService) -> None:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    class _Handler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory:
                return
            ingestion.process_file(Path(event.src_path))

        def on_modified(self, event):
            if event.is_directory:
                return
            ingestion.process_file(Path(event.src_path))

    observer = Observer()
    observer.schedule(_Handler(), str(ingestion.config.paths.docs_root), recursive=True)
    observer.start()
    try:
        while True:
            observer.join(timeout=1)
    except KeyboardInterrupt:
        observer.stop()
        observer.join()
