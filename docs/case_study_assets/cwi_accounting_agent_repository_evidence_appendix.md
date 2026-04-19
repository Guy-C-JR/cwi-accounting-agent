# CWI Accounting Agent
## Repository Evidence Appendix

Use this appendix alongside the resume or portfolio version. It ties the strongest claims to concrete files and gives suggested screenshot targets for a short code appendix.

| Flow / Claim | Why It Matters | Strongest Evidence | Suggested Screenshot |
|---|---|---|---|
| CLI + watcher workflow | Shows real local operations entrypoints | `src/cwi_accountant/cli.py:25`, `:40`, `:49`, `:58`, `:119` | bootstrap / scan-existing / watch / review-app commands |
| SQLite operations state | Proves this is not a stateless script | `src/cwi_accountant/db.py:49`, `:94`, `:108`, `:140`, `:157`, `:359`, `:720` | schema creation for documents, review_decisions, duplicate_candidates, recurring_candidates, audit_events |
| Confidence-based extraction | Demonstrates review-safe parsing rather than naive scraping | `src/cwi_accountant/parsing/extractor.py:88`, `:219`, `:496`, `:517` | extract flow + overall confidence + review reason logic |
| Ingestion + auto-post policy gating | Strongest workflow orchestration/safety logic | `src/cwi_accountant/services/ingestion.py:64`, `:112`, `:122`, `:179`, `:203` | process_file + strict auto-post gate |
| Workbook-safe writeback | Strongest accounting mutation safety evidence | `src/cwi_accountant/workbook.py:90`, `:129`, `:171`, `:284` | backup before write + append expense + recurring write + row-pattern copy |
| Blind overwrite / duplicate prevention | High-signal safety control | `src/cwi_accountant/services/writeback.py:195`, `:205`, `:213`, `:227` | refuse blind overwrite + workbook duplicate guard |
| Duplicate detection workflow | Shows practical accounting review logic | `src/cwi_accountant/services/duplicate_service.py:23`, `:71`, `:83` | detect + resolve duplicate candidates |
| Recurring-bill candidate workflow | Shows workflow expansion beyond one-off expenses | `src/cwi_accountant/services/recurring_service.py:19`, `:36`, `:62`, `:88` | candidate refresh + confidence + workbook upsert |
| Streamlit review cockpit | Real operations UI, not just backend code | `src/cwi_accountant/review_app.py:62`, `:158`, `:386`, `:434`, `:504`, `:542`, `:553` | queue dashboard + document review + duplicate/vendor/recurring/audit/report pages |
| Exception and tax/monthly reports | Real bookkeeping-output layer | `src/cwi_accountant/reporting/reports.py:18`, `:67`, `:127` | monthly summary + tax report + exception reports |
| Validation against canonical workbook lists | Strong control against dirty writes | `src/cwi_accountant/services/category_mapper.py:37`, `:44`, `:48` | lists-based validation errors |
| Test coverage on critical paths | Gives credibility to safety/reliability claims | `tests/test_extractor_confidence.py`, `tests/test_db_and_queue.py`, `tests/test_workbook_gateway.py`, `tests/test_autopost_policy.py` | passing test run + representative test files |

### Short Screenshot Set To Use
Use 4 to 6 screenshots max.

1. **CLI + ingestion orchestration**
   - `cli.py`
   - `services/ingestion.py`

2. **Confidence extraction + review routing**
   - `parsing/extractor.py`
   - `db.py`

3. **Workbook-safe writeback**
   - `workbook.py`
   - `services/writeback.py`

4. **Duplicate + recurring workflows**
   - `services/duplicate_service.py`
   - `services/recurring_service.py`

5. **Review dashboard**
   - `review_app.py`

6. **Reporting + tests**
   - `reporting/reports.py`
   - a terminal screenshot of `19 passed`

### Notes On Safe Positioning
Do not pair this appendix with claims about fully autonomous bookkeeping, production OCR across all document types, tax/legal advice automation, or deep enterprise accounting-system integration unless those are proven elsewhere.
