# CWI Accounting Agent
## Skills-Forward Portfolio Page

### What This Project Actually Demonstrates
CWI Accounting Agent is strongest as a reliability-first operations system for accounting review, not as a generic “AI agent” pitch. The repo demonstrates practical engineering across document ingestion, extraction confidence scoring, review-queue state management, workbook-safe writeback, duplicate and recurring detection, audit trails, and reporting.

### Core Technical Themes
#### 1. Local-First Accounting Intake and Review
Built a system that ingests backlog documents and live file events, extracts structured expense candidates, and routes weak or risky records into a review queue instead of silently posting them.

What was implemented:
- CLI for bootstrap, scan-existing, watch, review, report generation, and dashboard launch
- file-system watcher for live document intake
- document parsing across PDF, CSV, XLSX, and optional OCR image path
- confidence-based review gating
- SQLite-backed state store for documents and queue behavior

#### 2. Safe Workbook Writeback
Instead of treating spreadsheets as dumb outputs, the project uses controlled workbook mutation with backups and duplicate protections.

What was implemented:
- timestamped workbook backup before each write
- openpyxl append/update logic
- formula/style preservation via row-pattern copy
- canonical `Lists` validation before write approval
- duplicate checks against workbook rows
- refusal to blindly overwrite already-posted documents

#### 3. Human-in-the-Loop Operations Cockpit
The repo includes a real Streamlit review interface for accounting operations rather than a placeholder admin page.

What was implemented:
- review queue dashboard with metrics and filters
- editable document review and approval actions
- duplicate review and resolution workflow
- vendor normalization/merge workflow
- recurring-bill candidate review
- audit trail viewer
- report generation and download panel

#### 4. Conservative Automation Policies
Automation exists, but it is intentionally constrained.

What was implemented:
- strict auto-post gating behind config flags
- vendor/category policies
- confidence floors for overall and critical fields
- amount caps
- receipt/payment-method/business-purpose requirements
- fallback to review when policy checks fail

### Skills Displayed
- Python systems engineering
- CLI workflow design with Typer
- SQLite schema and state-management design
- openpyxl-based Excel automation
- Streamlit operational dashboards
- document parsing and extraction heuristics
- confidence scoring and review routing
- duplicate detection and fuzzy matching
- recurring-pattern detection
- audit logging and bookkeeping-report generation

### Strongest Engineering Contributions
- Implemented a full accounting intake workflow from document scan/import through extraction, queueing, approval, workbook writeback, and reporting.
- Designed a SQLite-backed review-state model that tracks documents, review decisions, duplicates, vendors, recurring bills, audit events, and generated reports.
- Built accountant-safe workbook writeback with backups, formula preservation, duplicate checks, and overwrite refusal behavior.
- Added strict auto-post policy gates so automation is only allowed when trust, confidence, and bookkeeping requirements all pass.
- Created a Streamlit human-ops cockpit to review, edit, approve, reject, defer, reprocess, merge vendors, and manage recurring bills.
- Added test coverage around the safety-critical paths rather than leaving review/writeback behavior unverified.

### Why This Is Portfolio-Worthy
This project is a strong case study because it shows operational engineering judgment. The important story is not “I built an agent”; it is “I built a constrained accounting review system that treats bookkeeping changes as high-risk mutations, routes ambiguity to humans, preserves auditability, and automates only when explicit policy gates pass.”

### Suggested Interview Framing
- I treated accounting ingestion as an operations and control problem, not just a parser problem.
- I designed automation to be intentionally conservative, with policy gates and human review.
- I built the state, writeback, and dashboard layers together so the workflow was end-to-end, not just extraction logic in isolation.
- I focused on preventing silent data corruption in spreadsheets by backing up, preserving formulas, and refusing blind overwrite.

### What I Would Not Overclaim
- Fully autonomous bookkeeping
- Perfect OCR across messy documents
- Deep semantic DOCX understanding
- Tax/legal advice automation
- Multi-user production SaaS readiness
