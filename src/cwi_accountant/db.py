from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

from cwi_accountant.models import (
    AuditEvent,
    DocumentRecord,
    DuplicateCandidate,
    ProposedExpenseEntry,
    RecurringBillCandidate,
    ReviewDecision,
    VendorCandidate,
)


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"Not JSON serializable: {type(value)}")


class StateStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT NOT NULL UNIQUE,
                    file_hash TEXT NOT NULL,
                    file_mtime REAL NOT NULL,
                    file_size INTEGER NOT NULL,
                    file_type TEXT NOT NULL,
                    document_type TEXT,
                    vendor TEXT,
                    doc_date TEXT,
                    due_date TEXT,
                    amount TEXT,
                    subtotal TEXT,
                    tax_amount TEXT,
                    payment_status TEXT,
                    reference_number TEXT,
                    payment_method TEXT,
                    description TEXT,
                    recurring_clue TEXT,
                    client_project TEXT,
                    business_purpose_clue TEXT,
                    extracted_text TEXT,
                    extracted_fields_json TEXT,
                    confidence_overall REAL NOT NULL DEFAULT 0,
                    state TEXT NOT NULL DEFAULT 'new',
                    needs_review INTEGER NOT NULL DEFAULT 1,
                    review_reason TEXT,
                    proposed_entry_json TEXT,
                    posted_sheet TEXT,
                    posted_row INTEGER,
                    expense_ref TEXT,
                    snoozed_until TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(file_hash);
                CREATE INDEX IF NOT EXISTS idx_documents_state ON documents(state);
                CREATE INDEX IF NOT EXISTS idx_documents_vendor_date_amount ON documents(vendor, doc_date, amount);

                CREATE TABLE IF NOT EXISTS review_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    notes TEXT,
                    before_json TEXT,
                    after_json TEXT,
                    link_expense_ref TEXT,
                    defer_until TEXT,
                    decided_by TEXT NOT NULL,
                    decided_at TEXT NOT NULL,
                    FOREIGN KEY(document_id) REFERENCES documents(id)
                );

                CREATE TABLE IF NOT EXISTS duplicate_candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL,
                    candidate_document_id INTEGER NOT NULL,
                    score REAL NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    UNIQUE(document_id, candidate_document_id),
                    FOREIGN KEY(document_id) REFERENCES documents(id),
                    FOREIGN KEY(candidate_document_id) REFERENCES documents(id)
                );

                CREATE TABLE IF NOT EXISTS vendor_candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vendor_name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL UNIQUE,
                    vendor_type TEXT,
                    contact_person TEXT,
                    email TEXT,
                    phone TEXT,
                    address TEXT,
                    website TEXT,
                    tax_form_needed TEXT,
                    eligible_1099 TEXT,
                    usual_category TEXT,
                    payment_terms TEXT,
                    status TEXT,
                    notes TEXT,
                    source_document_ids_json TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS recurring_candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vendor TEXT NOT NULL,
                    expense_name TEXT NOT NULL,
                    category TEXT,
                    amount TEXT,
                    frequency TEXT,
                    due_day INTEGER,
                    first_seen TEXT,
                    last_seen TEXT,
                    source_document_ids_json TEXT,
                    confidence REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'new',
                    linked_recurring_row INTEGER,
                    UNIQUE(vendor, expense_name)
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    document_id INTEGER,
                    source_file TEXT,
                    action TEXT NOT NULL,
                    sheet_name TEXT,
                    row_number INTEGER,
                    fields_written_json TEXT,
                    confidence REAL,
                    auto_or_human TEXT NOT NULL,
                    before_values_json TEXT,
                    after_values_json TEXT,
                    notes TEXT,
                    FOREIGN KEY(document_id) REFERENCES documents(id)
                );

                CREATE TABLE IF NOT EXISTS generated_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_type TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    period TEXT,
                    generated_at TEXT NOT NULL,
                    notes TEXT
                );
                """
            )

    @staticmethod
    def _serialize(obj: Any) -> str:
        return json.dumps(obj, default=_json_default)

    @staticmethod
    def _deserialize(text: str | None, fallback: Any) -> Any:
        if not text:
            return fallback
        return json.loads(text)

    def upsert_document(
        self,
        record: DocumentRecord,
        proposed_entry: ProposedExpenseEntry | None,
    ) -> int:
        extracted_json = self._serialize(
            {k: v.model_dump(mode="json") for k, v in record.extracted_fields.items()}
        )
        proposed_json = self._serialize(proposed_entry.model_dump(mode="json")) if proposed_entry else None
        now = datetime.utcnow().isoformat()

        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM documents WHERE file_path = ?", (record.file_path,)
            ).fetchone()
            if existing:
                doc_id = int(existing["id"])
                conn.execute(
                    """
                    UPDATE documents
                    SET file_hash=?, file_mtime=?, file_size=?, file_type=?, document_type=?, vendor=?,
                        doc_date=?, due_date=?, amount=?, subtotal=?, tax_amount=?, payment_status=?,
                        reference_number=?, payment_method=?, description=?, recurring_clue=?,
                        client_project=?, business_purpose_clue=?, extracted_text=?, extracted_fields_json=?,
                        confidence_overall=?, state=?, needs_review=?, review_reason=?, proposed_entry_json=?,
                        updated_at=?
                    WHERE id=?
                    """,
                    (
                        record.file_hash,
                        record.file_mtime,
                        record.file_size,
                        record.file_type,
                        record.document_type,
                        record.vendor,
                        record.doc_date.isoformat() if record.doc_date else None,
                        record.due_date.isoformat() if record.due_date else None,
                        str(record.amount) if record.amount is not None else None,
                        str(record.subtotal) if record.subtotal is not None else None,
                        str(record.tax_amount) if record.tax_amount is not None else None,
                        record.payment_status,
                        record.reference_number,
                        record.payment_method,
                        record.description,
                        record.recurring_clue,
                        record.client_project,
                        record.business_purpose_clue,
                        record.extracted_text,
                        extracted_json,
                        record.confidence_overall,
                        record.state,
                        int(record.needs_review),
                        record.review_reason,
                        proposed_json,
                        now,
                        doc_id,
                    ),
                )
                return doc_id

            cursor = conn.execute(
                """
                INSERT INTO documents (
                    file_path, file_hash, file_mtime, file_size, file_type, document_type,
                    vendor, doc_date, due_date, amount, subtotal, tax_amount,
                    payment_status, reference_number, payment_method, description,
                    recurring_clue, client_project, business_purpose_clue, extracted_text,
                    extracted_fields_json, confidence_overall, state, needs_review,
                    review_reason, proposed_entry_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.file_path,
                    record.file_hash,
                    record.file_mtime,
                    record.file_size,
                    record.file_type,
                    record.document_type,
                    record.vendor,
                    record.doc_date.isoformat() if record.doc_date else None,
                    record.due_date.isoformat() if record.due_date else None,
                    str(record.amount) if record.amount is not None else None,
                    str(record.subtotal) if record.subtotal is not None else None,
                    str(record.tax_amount) if record.tax_amount is not None else None,
                    record.payment_status,
                    record.reference_number,
                    record.payment_method,
                    record.description,
                    record.recurring_clue,
                    record.client_project,
                    record.business_purpose_clue,
                    record.extracted_text,
                    extracted_json,
                    record.confidence_overall,
                    record.state,
                    int(record.needs_review),
                    record.review_reason,
                    proposed_json,
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def get_document(self, document_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            ).fetchone()

    def get_document_by_path(self, file_path: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM documents WHERE file_path = ?", (file_path,)
            ).fetchone()

    def document_exists_by_hash(self, file_hash: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM documents WHERE file_hash = ? LIMIT 1", (file_hash,)
            ).fetchone()
            return row is not None

    def list_documents(
        self,
        *,
        state: str | None = None,
        min_confidence: float | None = None,
        max_confidence: float | None = None,
        vendor: str | None = None,
        doc_type: str | None = None,
        posted_only: bool | None = None,
        limit: int = 200,
    ) -> list[sqlite3.Row]:
        where = []
        params: list[Any] = []

        if state:
            where.append("state = ?")
            params.append(state)
        if min_confidence is not None:
            where.append("confidence_overall >= ?")
            params.append(min_confidence)
        if max_confidence is not None:
            where.append("confidence_overall <= ?")
            params.append(max_confidence)
        if vendor:
            where.append("vendor LIKE ?")
            params.append(f"%{vendor}%")
        if doc_type:
            where.append("document_type = ?")
            params.append(doc_type)
        if posted_only is True:
            where.append("posted_row IS NOT NULL")
        if posted_only is False:
            where.append("posted_row IS NULL")

        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with self.connect() as conn:
            return conn.execute(
                f"SELECT * FROM documents {clause} ORDER BY updated_at DESC LIMIT ?",
                (*params, limit),
            ).fetchall()

    def list_review_queue(
        self,
        *,
        confidence_threshold: float,
        include_deferred: bool = False,
        limit: int = 500,
    ) -> list[sqlite3.Row]:
        deferred_filter = "" if include_deferred else "AND state != 'deferred'"
        query = f"""
            SELECT
                d.*,
                CASE WHEN d.vendor IS NULL OR d.doc_date IS NULL OR d.amount IS NULL THEN 1 ELSE 0 END AS missing_critical,
                CASE WHEN EXISTS (
                    SELECT 1 FROM duplicate_candidates dc
                    WHERE (dc.document_id = d.id OR dc.candidate_document_id = d.id)
                        AND dc.status = 'open'
                ) THEN 1 ELSE 0 END AS has_duplicate,
                ABS(COALESCE(CAST(d.amount AS REAL), 0)) AS amount_num,
                CASE WHEN d.confidence_overall < ? THEN 1 ELSE 0 END AS low_confidence
            FROM documents d
            WHERE (
                d.state IN ('new', 'needs-review', 'failed')
                OR (d.state = 'auto-posted' AND d.confidence_overall < ?)
            )
            {deferred_filter}
            ORDER BY missing_critical DESC,
                     has_duplicate DESC,
                     amount_num DESC,
                     low_confidence DESC,
                     d.updated_at DESC
            LIMIT ?
        """
        with self.connect() as conn:
            return conn.execute(query, (confidence_threshold, confidence_threshold, limit)).fetchall()

    def set_document_posting(
        self,
        document_id: int,
        *,
        state: str,
        posted_sheet: str | None,
        posted_row: int | None,
        expense_ref: str | None,
        needs_review: bool,
        review_reason: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE documents
                SET state=?, posted_sheet=?, posted_row=?, expense_ref=?,
                    needs_review=?, review_reason=?, updated_at=?
                WHERE id=?
                """,
                (
                    state,
                    posted_sheet,
                    posted_row,
                    expense_ref,
                    int(needs_review),
                    review_reason,
                    datetime.utcnow().isoformat(),
                    document_id,
                ),
            )

    def update_document_state(
        self,
        document_id: int,
        *,
        state: str,
        needs_review: bool,
        review_reason: str | None = None,
        snoozed_until: datetime | None = None,
        last_error: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE documents
                SET state=?, needs_review=?, review_reason=?, snoozed_until=?,
                    last_error=?, updated_at=?
                WHERE id=?
                """,
                (
                    state,
                    int(needs_review),
                    review_reason,
                    snoozed_until.isoformat() if snoozed_until else None,
                    last_error,
                    datetime.utcnow().isoformat(),
                    document_id,
                ),
            )

    def update_document_proposed_entry(
        self,
        document_id: int,
        proposed_entry: ProposedExpenseEntry,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE documents
                SET proposed_entry_json=?, updated_at=?
                WHERE id=?
                """,
                (
                    self._serialize(proposed_entry.model_dump(mode="json")),
                    datetime.utcnow().isoformat(),
                    document_id,
                ),
            )

    def add_review_decision(
        self,
        decision: ReviewDecision,
        *,
        before_payload: dict[str, Any] | None = None,
        after_payload: dict[str, Any] | None = None,
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO review_decisions (
                    document_id, action, notes, before_json, after_json,
                    link_expense_ref, defer_until, decided_by, decided_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.document_id,
                    decision.action,
                    decision.notes,
                    self._serialize(before_payload or {}),
                    self._serialize(after_payload or {}),
                    decision.link_expense_ref,
                    decision.defer_until.isoformat() if decision.defer_until else None,
                    decision.decided_by,
                    datetime.utcnow().isoformat(),
                ),
            )
            return int(cur.lastrowid)

    def add_duplicate_candidate(self, candidate: DuplicateCandidate) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO duplicate_candidates (
                    document_id, candidate_document_id, score, reason, status
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(document_id, candidate_document_id)
                DO UPDATE SET score=excluded.score, reason=excluded.reason, status=excluded.status
                """,
                (
                    candidate.document_id,
                    candidate.candidate_document_id,
                    candidate.score,
                    candidate.reason,
                    candidate.status,
                ),
            )
            return int(cur.lastrowid or 0)

    def list_duplicate_candidates(self, status: str = "open") -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT dc.*, d1.file_path AS file_path_a, d2.file_path AS file_path_b,
                       d1.vendor AS vendor_a, d2.vendor AS vendor_b,
                       d1.amount AS amount_a, d2.amount AS amount_b,
                       d1.doc_date AS date_a, d2.doc_date AS date_b,
                       d1.state AS state_a, d2.state AS state_b
                FROM duplicate_candidates dc
                JOIN documents d1 ON d1.id = dc.document_id
                JOIN documents d2 ON d2.id = dc.candidate_document_id
                WHERE dc.status = ?
                ORDER BY dc.score DESC
                """,
                (status,),
            ).fetchall()

    def resolve_duplicate_pair(self, candidate_id: int, new_status: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE duplicate_candidates SET status = ? WHERE id = ?",
                (new_status, candidate_id),
            )

    def upsert_vendor_candidate(self, candidate: VendorCandidate) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO vendor_candidates (
                    vendor_name, normalized_name, vendor_type, contact_person, email, phone,
                    address, website, tax_form_needed, eligible_1099, usual_category,
                    payment_terms, status, notes, source_document_ids_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(normalized_name)
                DO UPDATE SET
                    vendor_name=excluded.vendor_name,
                    vendor_type=COALESCE(excluded.vendor_type, vendor_candidates.vendor_type),
                    contact_person=COALESCE(excluded.contact_person, vendor_candidates.contact_person),
                    email=COALESCE(excluded.email, vendor_candidates.email),
                    phone=COALESCE(excluded.phone, vendor_candidates.phone),
                    address=COALESCE(excluded.address, vendor_candidates.address),
                    website=COALESCE(excluded.website, vendor_candidates.website),
                    tax_form_needed=COALESCE(excluded.tax_form_needed, vendor_candidates.tax_form_needed),
                    eligible_1099=COALESCE(excluded.eligible_1099, vendor_candidates.eligible_1099),
                    usual_category=COALESCE(excluded.usual_category, vendor_candidates.usual_category),
                    payment_terms=COALESCE(excluded.payment_terms, vendor_candidates.payment_terms),
                    status=COALESCE(excluded.status, vendor_candidates.status),
                    notes=COALESCE(excluded.notes, vendor_candidates.notes),
                    source_document_ids_json=excluded.source_document_ids_json,
                    updated_at=excluded.updated_at
                """,
                (
                    candidate.vendor_name,
                    candidate.normalized_name,
                    candidate.vendor_type,
                    candidate.contact_person,
                    candidate.email,
                    candidate.phone,
                    candidate.address,
                    candidate.website,
                    candidate.tax_form_needed,
                    candidate.eligible_1099,
                    candidate.usual_category,
                    candidate.payment_terms,
                    candidate.status,
                    candidate.notes,
                    self._serialize(candidate.source_document_ids),
                    datetime.utcnow().isoformat(),
                ),
            )
            if cur.lastrowid:
                return int(cur.lastrowid)
            row = conn.execute(
                "SELECT id FROM vendor_candidates WHERE normalized_name = ?",
                (candidate.normalized_name,),
            ).fetchone()
            return int(row["id"]) if row else 0

    def list_vendor_candidates(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM vendor_candidates ORDER BY vendor_name COLLATE NOCASE"
            ).fetchall()

    def merge_vendor_candidates(
        self,
        source_normalized: str,
        target_normalized: str,
        target_vendor_name: str,
    ) -> None:
        with self.connect() as conn:
            target = conn.execute(
                "SELECT source_document_ids_json FROM vendor_candidates WHERE normalized_name = ?",
                (target_normalized,),
            ).fetchone()
            source = conn.execute(
                "SELECT source_document_ids_json FROM vendor_candidates WHERE normalized_name = ?",
                (source_normalized,),
            ).fetchone()

            target_ids = set(self._deserialize(target["source_document_ids_json"], []) if target else [])
            source_ids = set(self._deserialize(source["source_document_ids_json"], []) if source else [])
            merged_ids = sorted(target_ids | source_ids)

            conn.execute(
                """
                UPDATE vendor_candidates
                SET vendor_name=?, source_document_ids_json=?, updated_at=?
                WHERE normalized_name=?
                """,
                (
                    target_vendor_name,
                    self._serialize(merged_ids),
                    datetime.utcnow().isoformat(),
                    target_normalized,
                ),
            )
            conn.execute(
                "DELETE FROM vendor_candidates WHERE normalized_name = ?",
                (source_normalized,),
            )
            conn.execute(
                "UPDATE documents SET vendor = ? WHERE vendor IS NOT NULL AND LOWER(vendor) = ?",
                (target_vendor_name, source_normalized),
            )

    def upsert_recurring_candidate(self, candidate: RecurringBillCandidate) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO recurring_candidates (
                    vendor, expense_name, category, amount, frequency, due_day,
                    first_seen, last_seen, source_document_ids_json, confidence,
                    status, linked_recurring_row
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(vendor, expense_name)
                DO UPDATE SET
                    category=COALESCE(excluded.category, recurring_candidates.category),
                    amount=COALESCE(excluded.amount, recurring_candidates.amount),
                    frequency=COALESCE(excluded.frequency, recurring_candidates.frequency),
                    due_day=COALESCE(excluded.due_day, recurring_candidates.due_day),
                    first_seen=COALESCE(recurring_candidates.first_seen, excluded.first_seen),
                    last_seen=COALESCE(excluded.last_seen, recurring_candidates.last_seen),
                    source_document_ids_json=excluded.source_document_ids_json,
                    confidence=excluded.confidence,
                    status=excluded.status,
                    linked_recurring_row=COALESCE(excluded.linked_recurring_row, recurring_candidates.linked_recurring_row)
                """,
                (
                    candidate.vendor,
                    candidate.expense_name,
                    candidate.category,
                    str(candidate.amount) if candidate.amount is not None else None,
                    candidate.frequency,
                    candidate.due_day,
                    candidate.first_seen.isoformat() if candidate.first_seen else None,
                    candidate.last_seen.isoformat() if candidate.last_seen else None,
                    self._serialize(candidate.source_document_ids),
                    candidate.confidence,
                    candidate.status,
                    candidate.linked_recurring_row,
                ),
            )
            if cur.lastrowid:
                return int(cur.lastrowid)
            row = conn.execute(
                "SELECT id FROM recurring_candidates WHERE vendor = ? AND expense_name = ?",
                (candidate.vendor, candidate.expense_name),
            ).fetchone()
            return int(row["id"]) if row else 0

    def list_recurring_candidates(self, status: str | None = None) -> list[sqlite3.Row]:
        where = "WHERE status = ?" if status else ""
        params = (status,) if status else ()
        with self.connect() as conn:
            return conn.execute(
                f"SELECT * FROM recurring_candidates {where} ORDER BY confidence DESC, last_seen DESC",
                params,
            ).fetchall()

    def update_recurring_candidate_status(
        self,
        candidate_id: int,
        *,
        status: str,
        linked_row: int | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE recurring_candidates
                SET status=?, linked_recurring_row=COALESCE(?, linked_recurring_row)
                WHERE id=?
                """,
                (status, linked_row, candidate_id),
            )

    def add_audit_event(self, event: AuditEvent) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO audit_events (
                    timestamp, document_id, source_file, action, sheet_name, row_number,
                    fields_written_json, confidence, auto_or_human, before_values_json,
                    after_values_json, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.timestamp.isoformat(),
                    event.document_id,
                    event.source_file,
                    event.action,
                    event.sheet_name,
                    event.row_number,
                    self._serialize(event.fields_written),
                    event.confidence,
                    event.auto_or_human,
                    self._serialize(event.before_values),
                    self._serialize(event.after_values),
                    event.notes,
                ),
            )
            return int(cur.lastrowid)

    def list_audit_events(self, limit: int = 200) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM audit_events ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()

    def add_generated_report(
        self,
        *,
        report_type: str,
        file_path: str,
        period: str | None,
        notes: str | None = None,
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO generated_reports (report_type, file_path, period, generated_at, notes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    report_type,
                    file_path,
                    period,
                    datetime.utcnow().isoformat(),
                    notes,
                ),
            )
            return int(cur.lastrowid)

    def list_generated_reports(self, report_type: str | None = None) -> list[sqlite3.Row]:
        where = "WHERE report_type = ?" if report_type else ""
        params = (report_type,) if report_type else ()
        with self.connect() as conn:
            return conn.execute(
                f"SELECT * FROM generated_reports {where} ORDER BY generated_at DESC",
                params,
            ).fetchall()

    def dashboard_metrics(self) -> dict[str, int]:
        with self.connect() as conn:
            metrics = {}
            metrics["total_documents"] = conn.execute(
                "SELECT COUNT(*) AS c FROM documents"
            ).fetchone()["c"]
            metrics["awaiting_review"] = conn.execute(
                """
                SELECT COUNT(*) AS c FROM documents
                WHERE state IN ('new', 'needs-review', 'failed')
                """
            ).fetchone()["c"]
            metrics["low_confidence"] = conn.execute(
                "SELECT COUNT(*) AS c FROM documents WHERE confidence_overall < 0.75"
            ).fetchone()["c"]
            metrics["duplicate_suspects"] = conn.execute(
                "SELECT COUNT(*) AS c FROM duplicate_candidates WHERE status = 'open'"
            ).fetchone()["c"]
            metrics["missing_key_fields"] = conn.execute(
                """
                SELECT COUNT(*) AS c FROM documents
                WHERE vendor IS NULL OR doc_date IS NULL OR amount IS NULL
                """
            ).fetchone()["c"]
            metrics["missing_receipt_link"] = conn.execute(
                """
                SELECT COUNT(*) AS c FROM documents
                WHERE state IN ('approved', 'approved-with-edits', 'auto-posted')
                AND (proposed_entry_json IS NULL OR proposed_entry_json NOT LIKE '%receipt_link_file%')
                """
            ).fetchone()["c"]
            metrics["recurring_candidates"] = conn.execute(
                "SELECT COUNT(*) AS c FROM recurring_candidates WHERE status = 'new'"
            ).fetchone()["c"]
            metrics["possible_1099_vendors"] = conn.execute(
                "SELECT COUNT(*) AS c FROM vendor_candidates WHERE eligible_1099 = 'Yes'"
            ).fetchone()["c"]
            metrics["recent_workbook_writes"] = conn.execute(
                """
                SELECT COUNT(*) AS c FROM audit_events
                WHERE sheet_name IS NOT NULL
                AND timestamp >= datetime('now', '-7 day')
                """
            ).fetchone()["c"]
            metrics["recent_errors"] = conn.execute(
                """
                SELECT COUNT(*) AS c FROM documents
                WHERE last_error IS NOT NULL
                AND updated_at >= datetime('now', '-7 day')
                """
            ).fetchone()["c"]
            return metrics
