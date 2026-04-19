from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from cwi_accountant.app_context import AppServices, build_services
from cwi_accountant.config import default_config_path, load_config
from cwi_accountant.models import ProposedExpenseEntry, ReviewDecision, VendorCandidate
from cwi_accountant.utils import normalize_vendor_name


@st.cache_resource(show_spinner=False)
def load_services(config_path: str) -> tuple[Any, AppServices]:
    loaded = load_config(Path(config_path))
    services = build_services(loaded.config)
    return loaded, services


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", default=str(default_config_path()))
    args, _ = parser.parse_known_args()
    return args


def _json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        return json.loads(value)
    except Exception:
        return {}


def _df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _to_decimal(v: str | float | int | None) -> Decimal | None:
    if v in (None, ""):
        return None
    return Decimal(str(v)).quantize(Decimal("0.01"))


def _open_file(path: str) -> None:
    try:
        subprocess.run(["open", "-R", path], check=False)
    except Exception:
        pass


def page_queue_home(loaded, services: AppServices) -> None:
    st.subheader("Review Queue Home")
    metrics = services.review_queue.dashboard_metrics()

    cols = st.columns(5)
    cols[0].metric("Total Docs", metrics.get("total_documents", 0))
    cols[1].metric("Awaiting Review", metrics.get("awaiting_review", 0))
    cols[2].metric("Low Confidence", metrics.get("low_confidence", 0))
    cols[3].metric("Duplicates", metrics.get("duplicate_suspects", 0))
    cols[4].metric("Recent Errors", metrics.get("recent_errors", 0))

    with st.expander("Filters", expanded=True):
        col1, col2, col3, col4 = st.columns(4)
        date_from = col1.date_input("Date From", value=None)
        date_to = col2.date_input("Date To", value=None)
        vendor = col3.text_input("Vendor")
        status = col4.selectbox("Status", ["", "new", "needs-review", "auto-posted", "approved", "approved-with-edits", "rejected", "duplicate", "deferred", "failed", "archived"])

        col5, col6, col7, col8 = st.columns(4)
        amount_min = col5.text_input("Amount Min")
        amount_max = col6.text_input("Amount Max")
        doc_type = col7.text_input("Doc Type")
        posted = col8.selectbox("Posted", ["", "posted", "review-only"])

        col9, col10, col11 = st.columns(3)
        category = col9.text_input("Category contains")
        confidence_threshold = col10.slider("Confidence Threshold", min_value=0.0, max_value=1.0, value=float(loaded.config.low_confidence_threshold), step=0.01)
        include_deferred = col11.checkbox("Include deferred", value=False)

    queue_rows = services.review_queue.queue(
        confidence_threshold=confidence_threshold,
        date_from=date_from if isinstance(date_from, date) else None,
        date_to=date_to if isinstance(date_to, date) else None,
        vendor=vendor or None,
        amount_min=_to_decimal(amount_min),
        amount_max=_to_decimal(amount_max),
        category=category or None,
        status=status or None,
        doc_type=doc_type or None,
        posted=posted or None,
        include_deferred=include_deferred,
    )

    st.write(f"Queue items: {len(queue_rows)}")
    st.dataframe(_df(queue_rows), use_container_width=True, height=420)

    st.markdown("#### Bulk Actions")
    ids = [int(row["id"]) for row in queue_rows]
    selected_ids = st.multiselect("Select document IDs", ids)
    bulk_action = st.selectbox(
        "Bulk action",
        ["approve-as-is", "mark-duplicate", "archive-non-business", "set-category"],
    )
    bulk_category = st.text_input("Category for set-category") if bulk_action == "set-category" else ""
    confirm_bulk = st.checkbox("Confirm bulk action")
    if st.button("Run bulk action", type="primary"):
        if not confirm_bulk:
            st.warning("Confirmation required")
        elif not selected_ids:
            st.warning("Select at least one item")
        else:
            success = 0
            errors = 0
            for doc_id in selected_ids:
                try:
                    if bulk_action == "approve-as-is":
                        services.writeback.apply_decision(
                            ReviewDecision(document_id=doc_id, action="approve", decided_by="dashboard-human")
                        )
                    elif bulk_action == "mark-duplicate":
                        services.writeback.apply_decision(
                            ReviewDecision(document_id=doc_id, action="mark-duplicate", decided_by="dashboard-human")
                        )
                    elif bulk_action == "archive-non-business":
                        services.writeback.apply_decision(
                            ReviewDecision(document_id=doc_id, action="mark-personal", decided_by="dashboard-human")
                        )
                    elif bulk_action == "set-category":
                        row = services.store.get_document(doc_id)
                        if not row:
                            continue
                        proposed = ProposedExpenseEntry.model_validate(_json(row["proposed_entry_json"]))
                        proposed.category = bulk_category
                        services.store.update_document_proposed_entry(doc_id, proposed)
                    success += 1
                except Exception:
                    errors += 1
            st.success(f"Bulk action completed. Success={success}, Errors={errors}")

    st.markdown("#### Recent Workbook Writes")
    st.dataframe(_df(services.review_queue.recent_writes()), use_container_width=True, height=220)

    st.markdown("#### Recent Errors")
    st.dataframe(_df(services.review_queue.recent_errors()), use_container_width=True, height=220)


def page_document_review(loaded, services: AppServices) -> None:
    st.subheader("Document Review")

    queue_rows = services.review_queue.queue(
        confidence_threshold=loaded.config.low_confidence_threshold,
        include_deferred=True,
    )
    if not queue_rows:
        st.info("No documents in review queue")
        return

    options = {f"#{row['id']} | {row['vendor']} | {row['doc_date']} | ${row['amount']}": row for row in queue_rows}
    selected_key = st.selectbox("Select queued document", list(options.keys()))
    row = options[selected_key]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("State", row["state"])
    col2.metric("Confidence", f"{row['confidence_overall']:.2f}")
    col3.metric("Amount", row["amount"] or "")
    col4.metric("Doc Type", row["document_type"] or "")

    with st.container(border=True):
        st.write(f"**File:** `{row['file_path']}`")
        st.write(f"**Reference:** {row['reference_number'] or 'N/A'}")
        st.write(f"**Review reason:** {row['review_reason'] or 'None'}")
        if st.button("Reveal Source File in Finder"):
            _open_file(row["file_path"])

    left, right = st.columns([1.1, 1])

    with left:
        st.markdown("#### Source Preview")
        path = Path(row["file_path"])
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".heic"} and path.exists():
            st.image(str(path), use_container_width=True)
        else:
            extracted_text = row["extracted_text"] or ""
            st.text_area("Extracted text", extracted_text[:4000], height=320, disabled=True)

        st.markdown("#### Confidence by Field")
        fields = _json(row["extracted_fields_json"])
        if fields:
            conf_rows = []
            for name, payload in fields.items():
                conf_rows.append(
                    {
                        "field": name,
                        "value": payload.get("value"),
                        "confidence": payload.get("confidence"),
                        "source": payload.get("source"),
                    }
                )
            st.dataframe(pd.DataFrame(conf_rows), use_container_width=True, height=220)
        else:
            st.info("No extracted field payload available")

    with right:
        st.markdown("#### Proposed Entry (Editable)")
        proposal = _json(row["proposed_entry_json"])
        entry = ProposedExpenseEntry.model_validate(proposal or {
            "vendor": row["vendor"],
            "description": row["description"],
            "payment_method": row["payment_method"],
            "amount": row["amount"],
            "receipt_link_file": row["file_path"],
            "receipt": "Yes",
        })

        lists = services.workbook.load_lists()

        with st.form("edit_entry"):
            form_date = st.date_input("Date", value=entry.date)
            form_vendor = st.text_input("Vendor", value=entry.vendor or "")
            form_category = st.selectbox(
                "Category",
                options=["", *lists.categories],
                index=(lists.categories.index(entry.category) + 1 if entry.category in lists.categories else 0),
            )
            form_subcategory = st.selectbox(
                "Subcategory",
                options=["", *lists.subcategories],
                index=(lists.subcategories.index(entry.subcategory) + 1 if entry.subcategory in lists.subcategories else 0),
            )
            form_description = st.text_input("Description", value=entry.description or "")
            form_payment_method = st.selectbox(
                "Payment Method",
                options=["", *lists.payment_methods],
                index=(lists.payment_methods.index(entry.payment_method) + 1 if entry.payment_method in lists.payment_methods else 0),
            )
            form_account = st.text_input("Account/Card", value=entry.account_card or "")
            form_amount = st.text_input("Amount", value=str(entry.amount) if entry.amount is not None else "")
            form_tax_deductible = st.selectbox(
                "Tax Deductible?",
                options=["", *lists.yes_no, "Review"],
                index=((lists.yes_no + ["Review"]).index(entry.tax_deductible) + 1 if entry.tax_deductible in (lists.yes_no + ["Review"]) else 0),
            )
            form_receipt = st.selectbox(
                "Receipt?",
                options=["", *lists.yes_no],
                index=(lists.yes_no.index(entry.receipt) + 1 if entry.receipt in lists.yes_no else 0),
            )
            form_receipt_link = st.text_input("Receipt Link/File", value=entry.receipt_link_file or row["file_path"])
            form_business_purpose = st.text_input("Business Purpose", value=entry.business_purpose or "")
            form_billable = st.selectbox(
                "Billable to Client?",
                options=["", *lists.yes_no],
                index=(lists.yes_no.index(entry.billable_to_client) + 1 if entry.billable_to_client in lists.yes_no else 0),
            )
            form_client_project = st.text_input("Client/Project", value=entry.client_project or "")
            form_recurring = st.selectbox(
                "Recurring?",
                options=["", *lists.yes_no, "Review"],
                index=((lists.yes_no + ["Review"]).index(entry.recurring) + 1 if entry.recurring in (lists.yes_no + ["Review"]) else 0),
            )
            form_notes = st.text_area("Notes", value=entry.notes or "", height=120)
            save_edits = st.form_submit_button("Save edits to proposal")

        edited_entry = ProposedExpenseEntry(
            date=form_date,
            vendor=form_vendor or None,
            category=form_category or None,
            subcategory=form_subcategory or None,
            description=form_description or None,
            payment_method=form_payment_method or None,
            account_card=form_account or None,
            amount=form_amount or None,
            tax_deductible=form_tax_deductible or None,
            receipt=form_receipt or None,
            receipt_link_file=form_receipt_link or None,
            business_purpose=form_business_purpose or None,
            billable_to_client=form_billable or None,
            client_project=form_client_project or None,
            recurring=form_recurring or None,
            notes=form_notes or None,
        )

        if save_edits:
            services.store.update_document_proposed_entry(int(row["id"]), edited_entry)
            st.success("Proposal saved")

        st.markdown("#### Duplicate Candidates")
        duplicate_rows = [
            d
            for d in services.store.list_duplicate_candidates(status="open")
            if int(d["document_id"]) == int(row["id"]) or int(d["candidate_document_id"]) == int(row["id"])
        ]
        if duplicate_rows:
            st.dataframe(_df([{k: r[k] for k in r.keys()} for r in duplicate_rows]), use_container_width=True, height=180)
        else:
            st.info("No duplicate candidates")

    st.markdown("#### Approval Actions")
    col_a, col_b, col_c, col_d = st.columns(4)

    if col_a.button("Approve as-is", type="primary"):
        result = services.writeback.apply_decision(
            ReviewDecision(document_id=int(row["id"]), action="approve", decided_by="dashboard-human")
        )
        st.success(f"Approved: {result}")

    if col_b.button("Edit then approve"):
        result = services.writeback.apply_decision(
            ReviewDecision(
                document_id=int(row["id"]),
                action="approve-with-edits",
                edited_entry=edited_entry,
                decided_by="dashboard-human",
            )
        )
        st.success(f"Approved with edits: {result}")

    if col_c.button("Reject"):
        services.writeback.apply_decision(
            ReviewDecision(document_id=int(row["id"]), action="reject", decided_by="dashboard-human")
        )
        st.warning("Rejected")

    if col_d.button("Mark duplicate"):
        services.writeback.apply_decision(
            ReviewDecision(document_id=int(row["id"]), action="mark-duplicate", decided_by="dashboard-human")
        )
        st.warning("Marked duplicate")

    col_e, col_f, col_g, col_h = st.columns(4)
    link_ref = col_e.text_input("Link existing expense ref (e.g. Expense_Log!42)")
    if col_f.button("Link to existing"):
        services.writeback.apply_decision(
            ReviewDecision(
                document_id=int(row["id"]),
                action="link-existing",
                link_expense_ref=link_ref,
                decided_by="dashboard-human",
            )
        )
        st.success(f"Linked to {link_ref}")

    defer_date = col_g.date_input("Defer until", value=None)
    if col_h.button("Defer"):
        defer_until = datetime.combine(defer_date, time(hour=9)) if isinstance(defer_date, date) else None
        services.writeback.apply_decision(
            ReviewDecision(
                document_id=int(row["id"]),
                action="defer",
                defer_until=defer_until,
                decided_by="dashboard-human",
            )
        )
        st.info("Deferred")

    col_i, col_j = st.columns(2)
    if col_i.button("Send for reprocessing"):
        services.writeback.apply_decision(
            ReviewDecision(document_id=int(row["id"]), action="reprocess", decided_by="dashboard-human")
        )
        st.info("Queued for reprocessing")
    if col_j.button("Mark personal / non-business"):
        services.writeback.apply_decision(
            ReviewDecision(document_id=int(row["id"]), action="mark-personal", decided_by="dashboard-human")
        )
        st.warning("Archived as personal/non-business")

    if st.button("Mark informational only"):
        services.writeback.apply_decision(
            ReviewDecision(document_id=int(row["id"]), action="mark-informational", decided_by="dashboard-human")
        )
        st.success("Indexed as informational only")


def page_duplicates(services: AppServices) -> None:
    st.subheader("Duplicate Review")

    rows = services.store.list_duplicate_candidates(status="open")
    if not rows:
        st.info("No open duplicate candidates")
        return

    options = {f"#{row['id']} | score={row['score']:.2f} | {row['vendor_a']} <> {row['vendor_b']}": row for row in rows}
    selected = st.selectbox("Duplicate candidate", list(options.keys()))
    row = options[selected]

    st.dataframe(_df([{k: row[k] for k in row.keys()}]), use_container_width=True)

    left, right = st.columns(2)
    with left:
        st.markdown("#### Candidate A")
        st.write(f"Doc ID: {row['document_id']}")
        st.write(f"Vendor: {row['vendor_a']}")
        st.write(f"Date: {row['date_a']}")
        st.write(f"Amount: {row['amount_a']}")
        st.write(f"Path: `{row['file_path_a']}`")
    with right:
        st.markdown("#### Candidate B")
        st.write(f"Doc ID: {row['candidate_document_id']}")
        st.write(f"Vendor: {row['vendor_b']}")
        st.write(f"Date: {row['date_b']}")
        st.write(f"Amount: {row['amount_b']}")
        st.write(f"Path: `{row['file_path_b']}`")

    action = st.selectbox(
        "Resolution",
        ["keep-newest-only", "keep-existing-only", "keep-both", "merge-notes", "false-positive"],
    )
    merge_notes = st.text_input("Merge notes") if action == "merge-notes" else None
    confirm = st.checkbox("Confirm duplicate resolution")
    if st.button("Apply resolution", type="primary"):
        if not confirm:
            st.warning("Please confirm resolution")
        else:
            result = services.duplicate_service.resolve(
                candidate_id=int(row["id"]),
                action=action,
                merge_notes=merge_notes,
            )
            st.success(str(result))


def page_vendors(services: AppServices) -> None:
    st.subheader("Vendor Review")

    if st.button("Refresh vendor candidates from documents"):
        n = services.vendor_service.refresh_candidates_from_documents()
        st.success(f"Refreshed {n} vendor candidates")

    vendor_rows = services.vendor_service.list_candidates()
    st.dataframe(_df(vendor_rows), use_container_width=True, height=340)

    if not vendor_rows:
        return

    options = {f"{v['vendor_name']} ({v['normalized_name']})": v for v in vendor_rows}
    selected = st.selectbox("Select vendor", list(options.keys()))
    current = options[selected]
    yes_no_blank = ["", "Yes", "No"]

    def _safe_index(value: str | None, options: list[str]) -> int:
        return options.index(value) if value in options else 0

    with st.form("vendor_edit"):
        name = st.text_input("Vendor Name", value=current.get("vendor_name") or "")
        vendor_type = st.text_input("Vendor Type", value=current.get("vendor_type") or "")
        tax_form = st.selectbox(
            "Tax Form Needed?",
            yes_no_blank,
            index=_safe_index(current.get("tax_form_needed"), yes_no_blank),
        )
        eligible_1099 = st.selectbox(
            "1099 Eligible?",
            yes_no_blank,
            index=_safe_index(current.get("eligible_1099"), yes_no_blank),
        )
        usual_category = st.text_input("Usual Category", value=current.get("usual_category") or "")
        notes = st.text_area("Notes", value=current.get("notes") or "")
        save = st.form_submit_button("Save vendor")

    if save:
        candidate = VendorCandidate(
            id=current.get("id"),
            vendor_name=name,
            normalized_name=normalize_vendor_name(name),
            vendor_type=vendor_type or None,
            tax_form_needed=tax_form or None,
            eligible_1099=eligible_1099 or None,
            usual_category=usual_category or None,
            notes=notes or None,
            source_document_ids=[],
        )
        services.store.upsert_vendor_candidate(candidate)
        services.workbook.upsert_vendor(candidate)
        st.success("Vendor saved to state + workbook")

    st.markdown("#### Potential Naming Variants")
    variants = services.vendor_service.find_variants()
    st.dataframe(_df(variants), use_container_width=True, height=220)

    st.markdown("#### Merge Vendor Variants")
    source_norm = st.text_input("Source normalized name")
    target_norm = st.text_input("Target normalized name")
    target_name = st.text_input("Final vendor display name")
    if st.button("Merge variants"):
        if not source_norm or not target_norm or not target_name:
            st.warning("All merge fields are required")
        else:
            services.vendor_service.merge(source_norm, target_norm, target_name)
            st.success("Vendors merged")


def page_recurring(services: AppServices) -> None:
    st.subheader("Recurring Bill Review")

    if st.button("Refresh recurring candidates"):
        n = services.recurring_service.refresh_candidates()
        st.success(f"Detected/updated {n} candidates")

    rows = services.recurring_service.list_candidates()
    st.dataframe(_df(rows), use_container_width=True, height=340)

    if not rows:
        return

    options = {f"#{r['id']} | {r['vendor']} | {r['expense_name']}": r for r in rows}
    selected = st.selectbox("Select recurring candidate", list(options.keys()))
    row = options[selected]

    col1, col2, col3 = st.columns(3)
    frequency = col1.text_input("Frequency", value=row.get("frequency") or "")
    due_day = col2.number_input("Due Day", value=int(row.get("due_day") or 1), min_value=1, max_value=31)
    status_action = col3.selectbox("Action", ["approve", "reject", "defer"])

    if st.button("Apply recurring action", type="primary"):
        if status_action == "approve":
            result = services.recurring_service.approve_candidate(
                candidate_id=int(row["id"]),
                frequency=frequency,
                due_day=int(due_day),
            )
            st.success(str(result))
        elif status_action == "reject":
            services.recurring_service.reject_candidate(int(row["id"]))
            st.warning("Candidate rejected")
        else:
            services.store.update_recurring_candidate_status(int(row["id"]), status="deferred")
            st.info("Candidate deferred")


def page_audit(services: AppServices) -> None:
    st.subheader("Audit Trail")
    limit = st.slider("Rows", min_value=20, max_value=1000, value=200, step=20)
    action_filter = st.text_input("Filter action contains")
    rows = services.store.list_audit_events(limit=limit)
    payload = [{k: row[k] for k in row.keys()} for row in rows]
    if action_filter:
        payload = [p for p in payload if action_filter.lower() in str(p.get("action", "")).lower()]
    st.dataframe(_df(payload), use_container_width=True, height=540)


def page_reports(loaded, services: AppServices) -> None:
    st.subheader("Reports & Exceptions")

    col1, col2, col3 = st.columns(3)
    year = col1.number_input("Year", min_value=2020, max_value=2100, value=datetime.now().year)
    month = col2.selectbox("Month", ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])

    if col3.button("Generate monthly summary"):
        path = services.report_service.generate_monthly_summary(year=int(year), month=month)
        st.success(f"Generated: {path}")

    if st.button("Generate tax prep report"):
        path = services.report_service.generate_tax_report(year=int(year))
        st.success(f"Generated: {path}")

    if st.button("Generate all exception reports"):
        paths = services.report_service.generate_exception_reports()
        st.success(f"Generated {len(paths)} exception reports")

    report_rows = services.report_service.list_reports()
    st.dataframe(_df(report_rows), use_container_width=True, height=360)

    st.markdown("#### Download Report")
    if report_rows:
        labels = [f"{r['id']} | {r['report_type']} | {r['generated_at']}" for r in report_rows]
        selected = st.selectbox("Select report", labels)
        selected_row = report_rows[labels.index(selected)]
        report_path = Path(selected_row["file_path"])
        if report_path.exists():
            content = report_path.read_bytes()
            st.download_button(
                "Download selected CSV",
                data=content,
                file_name=report_path.name,
                mime="text/csv",
            )
        else:
            st.warning("Report file not found on disk")


def main() -> None:
    args = parse_args()
    loaded, services = load_services(args.config)

    st.set_page_config(page_title="CWI Accounting Review", layout="wide")
    st.title("CWI Accounting Review Dashboard")
    st.caption(
        "Local-first accountant operations cockpit. Approvals are audit-logged and workbook writes are backup-protected."
    )

    with st.sidebar:
        st.write(f"Config: `{args.config}`")
        st.write(f"Docs root: `{loaded.config.paths.docs_root}`")
        st.write(f"Workbook: `{loaded.config.paths.workbook_path}`")
        page = st.radio(
            "Navigation",
            [
                "Review Queue",
                "Document Review",
                "Duplicate Review",
                "Vendor Review",
                "Recurring Bills",
                "Audit Trail",
                "Reports",
            ],
        )

    if page == "Review Queue":
        page_queue_home(loaded, services)
    elif page == "Document Review":
        page_document_review(loaded, services)
    elif page == "Duplicate Review":
        page_duplicates(services)
    elif page == "Vendor Review":
        page_vendors(services)
    elif page == "Recurring Bills":
        page_recurring(services)
    elif page == "Audit Trail":
        page_audit(services)
    elif page == "Reports":
        page_reports(loaded, services)


if __name__ == "__main__":
    main()
