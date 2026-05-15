# CWI Accounting Agent

https://guy-c-jr.github.io/cwi-accounting-agent/

CWI Accounting Agent is a local accounting automation tool that helps process invoices, receipts, bills, vendor documents, and other expense related files into a structured bookkeeping review workflow.

The agent scans a local document folder, extracts accounting information, scores the confidence of extracted fields, flags uncertain records for review, detects possible duplicates, identifies recurring bills, and safely writes approved records into an Excel workbook with backups and audit history.

It is designed to reduce repetitive bookkeeping work while keeping final accounting decisions under human control.

## Key Features

* Local document intake for invoices, receipts, bills, and expense files
* Backlog scanning for existing documents
* Watch mode for newly added files
* Accounting field extraction from documents
* Confidence scoring for extracted records
* Human review queue for uncertain or incomplete items
* Approval, edit, rejection, and duplicate handling workflows
* Duplicate detection using vendor, amount, date, file hash, and existing records
* Recurring bill and repeated vendor payment detection
* Safe Excel workbook writeback using `openpyxl`
* Timestamped workbook backups before changes are made
* Formula and formatting preservation where possible
* SQLite based local state tracking
* Audit logging for review decisions and system actions
* Streamlit dashboard for reviewing pending items, duplicates, recurring candidates, reports, and audit events
* Report generation from the local accounting database
* Optional OCR support with `pytesseract`

## How It Works

1. Add accounting documents to the configured intake folder.
2. Run a scan or start watch mode.
3. The agent extracts vendor, date, amount, category, and related accounting fields.
4. Extracted records are scored for confidence.
5. Low confidence, incomplete, unusual, duplicate, or recurring records are routed to review.
6. A reviewer approves, edits, rejects, or marks records as duplicates.
7. Approved records are posted to the configured Excel workbook.
8. The system stores decisions, reports, backups, and audit events locally.

## Local First Design

CWI Accounting Agent is designed to run locally. Documents, workbook data, logs, reports, backups, and review decisions stay on the user’s machine by default.

This makes the tool suitable for accounting workflows where privacy, control, and traceability matter.

## Tech Stack

* Python
* Typer
* Streamlit
* SQLite
* Pydantic
* openpyxl
* pandas
* watchdog
* pypdf
* rapidfuzz
* pytest
* Optional OCR with `pytesseract`

## Repository Structure

```text
cwi-accounting-agent/
│
├── config/
│   └── cwi_accountant.toml.example
│
├── site/
│   └── GitHub Pages site files
│
├── src/
│   └── cwi_accountant/
│       ├── cli.py
│       ├── config.py
│       ├── db.py
│       ├── models.py
│       ├── workbook.py
│       ├── review_app.py
│       ├── parsing/
│       ├── reporting/
│       └── services/
│
├── tests/
├── pyproject.toml
├── README.md
└── .gitignore
