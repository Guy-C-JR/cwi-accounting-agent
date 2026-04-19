# CWI Accounting Agent

Recruiter-facing project page: https://guy-c-jr.github.io/cwi-accounting-agent/

CWI Accounting Agent is a local-first accounting review system that turns document intake into confidence-scored review items, safe Excel workbook writeback, audit trails, duplicate detection, recurring bill review, and bookkeeping reports.

## Why This Project Matters

This repository is packaged as a public portfolio version of the local CWI accounting automation workspace. It emphasizes practical automation judgment:

- Python CLI workflow for bootstrap, backlog scan, watch mode, review, and report generation
- Document parsing with confidence scoring and review gating
- SQLite state for documents, decisions, duplicates, vendors, recurring candidates, and audit events
- openpyxl workbook mutation with backups, formula/style preservation, and blind-overwrite refusal
- Streamlit human-review cockpit for approval, edit, reject, duplicate, vendor, recurring, audit, and reports workflows
- Tests around the safety-critical paths rather than only the happy path

## Repository Map

- `src/cwi_accountant`: Python package for CLI, config, SQLite state, models, workbook writing, Streamlit app, parsing, services, and reporting.
- `tests`: pytest coverage for queue behavior, extraction confidence, config resolution, duplicate detection, recurring detection, writeback, and auto-post policy.
- `config/cwi_accountant.toml.example`: public configuration template with safe defaults.
- `docs/case_study_assets`: portfolio notes and repository evidence appendix.
- `site`: static GitHub Pages case study.

## Technical Highlights

### Local-First Review Workflow

- Backlog ingestion and continuous watcher entrypoints
- File hash and manifest behavior for idempotent processing
- Confidence-based routing into a human review queue
- Review decisions stored in SQLite for auditability

### Accountant-Safe Workbook Writeback

- Timestamped workbook backup before each write
- Formula and style preservation by row-pattern copy
- Canonical list validation before approval/write
- Workbook duplicate checks and refusal to blindly overwrite posted rows

### Conservative Automation

- Auto-post disabled by default
- Vendor/category policies
- Overall and critical-field confidence floors
- Amount caps and receipt/payment/business-purpose requirements
- Review fallback when policy gates do not pass

## Evidence Anchors

- CLI entrypoints: `src/cwi_accountant/cli.py`
- SQLite state: `src/cwi_accountant/db.py`
- Confidence extraction: `src/cwi_accountant/parsing/extractor.py`
- Ingestion and policy gate: `src/cwi_accountant/services/ingestion.py`
- Workbook safety: `src/cwi_accountant/workbook.py`
- Duplicate/recurring workflows: `src/cwi_accountant/services/duplicate_service.py`, `src/cwi_accountant/services/recurring_service.py`
- Streamlit cockpit: `src/cwi_accountant/review_app.py`
- Reports: `src/cwi_accountant/reporting/reports.py`

## Local Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
pytest -q
```

Run the CLI:

```bash
python -m cwi_accountant bootstrap
python -m cwi_accountant scan-existing
python -m cwi_accountant review-app
```

Copy `config/cwi_accountant.toml.example` to `config/cwi_accountant.toml` in a private local checkout before using real accounting paths. Do not commit workbooks, invoices, local databases, or private reports.

## Portfolio Positioning

The strongest claim for this project is not fully autonomous bookkeeping. The strongest claim is that it treats accounting writes as high-risk operations: ambiguous records go to humans, workbook mutations are backed up and audited, and automation only runs behind explicit policy gates.

This tool supports bookkeeping review hygiene. It does not provide legal or tax filing advice.

