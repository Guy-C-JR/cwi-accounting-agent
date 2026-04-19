# CWI Accounting Agent
## FAANG-Style Resume Project Version

### Positioning
Local-first accounting operations system demonstrating workflow engineering across CLI automation, document extraction, SQLite-backed review state, workbook-safe writeback, human-in-the-loop review tooling, and policy-gated automation. Strongest evidence is in review-safe accounting ingestion rather than generic “AI agent” branding.

### Recruiter-Safe Summary
- Built a local-first accounting workflow for document ingestion, extraction, review routing, duplicate detection, recurring-bill detection, workbook writeback, and reporting.
- Implemented confidence-based extraction and strict review gating so weak or ambiguous records are routed to humans instead of auto-posted.
- Added backup-protected Excel writeback with duplicate guards, canonical list validation, and audit logging for every material mutation.
- Built a Streamlit review cockpit for queue triage, document review, duplicate resolution, vendor normalization, recurring-bill review, and audit/report access.
- Added strict auto-post policy gating with trusted-vendor, category, confidence, amount, and receipt/business-purpose requirements.

### Strongest Resume Bullets
- Built a local-first accounting agent in Python that ingests existing/backlog documents and live file-system events, extracts structured expense data, and routes low-confidence or ambiguous records into a human review queue.
- Implemented accountant-safe document extraction with field-level confidence scoring, overall review thresholds, OCR fallback, and conservative review reasoning for missing critical fields.
- Designed a SQLite-backed operations state layer covering documents, review decisions, duplicate candidates, vendor candidates, recurring-bill candidates, audit events, and generated reports.
- Built strict auto-post policy gating that only approves writeback when vendor trust, category allow-lists, amount limits, receipt evidence, payment method, business purpose, and confidence floors all pass.
- Implemented safe Excel workbook writeback using openpyxl with timestamped backups, formula/style preservation by row-pattern copy, and duplicate/overwrite protection.
- Added duplicate detection using both file-hash identity and fuzzy vendor/date/amount similarity, with reviewer-driven resolution workflows.
- Built recurring-bill candidate detection using pattern-based frequency inference and workbook writeback into a recurring-bills sheet.
- Created a Streamlit review dashboard for queue triage, editable document review, duplicate resolution, vendor normalization, recurring-bill approval, audit browsing, and report downloads.
- Added report-generation workflows for monthly summaries, tax-prep output, and exception reports such as uncategorized spend, missing receipts, duplicate suspects, and missing business purpose.
- Expanded reliability with a passing backend test suite covering extraction confidence, DB/queue behavior, duplicate logic, reprocessing behavior, recurring detection, config resolution, auto-post policy gating, and workbook backup/write behavior.

### High-Signal Technical Scope
- Python 3.11, Typer CLI
- SQLite state store
- openpyxl workbook automation
- watchdog file-system watcher
- Streamlit review UI
- pydantic data models and validation
- rapidfuzz duplicate/vendor matching
- OCR fallback via pytesseract
- CSV/PDF/XLSX extraction and reporting

### Safe Scope Boundaries
Safe to claim:
- End-to-end accounting document ingestion and review workflow
- Local-first operations/state design
- Policy-gated automation with human review
- Workbook-safe writeback and backups
- Review dashboard and reporting implementation

Avoid claiming:
- Production-grade OCR accuracy across all document types
- Full ERP/accounting system integration
- Fully autonomous bookkeeping without human review
- Deep DOCX layout parsing
- Tax/legal automation beyond bookkeeping support
