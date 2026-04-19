from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

import typer

from cwi_accountant.app_context import build_services
from cwi_accountant.config import default_config_path, load_config
from cwi_accountant.models import ReviewDecision
from cwi_accountant.services.ingestion import run_watch


app = typer.Typer(help="Local-first CWI accounting agent")


def _services(config_path: Path | None = None):
    loaded = load_config(config_path)
    services = build_services(loaded.config)
    return loaded, services


@app.command("bootstrap")
def bootstrap(
    config: Path = typer.Option(default_config_path(), "--config", help="Path to config file"),
    scan: bool = typer.Option(False, "--scan", help="Run initial backlog scan after bootstrap"),
) -> None:
    loaded, services = _services(config)
    typer.echo(f"Config loaded: {loaded.path}")
    typer.echo(f"Docs root: {loaded.config.paths.docs_root}")
    typer.echo(f"Workbook: {loaded.config.paths.workbook_path}")
    typer.echo(f"State DB: {loaded.config.paths.sqlite_path}")
    if scan:
        stats = services.ingestion.scan_existing()
        typer.echo(f"Scan complete: {stats}")


@app.command("scan-existing")
def scan_existing(
    config: Path = typer.Option(default_config_path(), "--config", help="Path to config file"),
) -> None:
    _, services = _services(config)
    stats = services.ingestion.scan_existing()
    typer.echo(json.dumps(stats, indent=2))


@app.command("watch")
def watch(
    config: Path = typer.Option(default_config_path(), "--config", help="Path to config file"),
) -> None:
    _, services = _services(config)
    typer.echo(f"Watching {services.ingestion.config.paths.docs_root} (Ctrl+C to stop)")
    run_watch(services.ingestion)


@app.command("review")
def review(
    config: Path = typer.Option(default_config_path(), "--config", help="Path to config file"),
    approve_id: int | None = typer.Option(None, "--approve-id", help="Approve a queued document id"),
    reject_id: int | None = typer.Option(None, "--reject-id", help="Reject a queued document id"),
) -> None:
    loaded, services = _services(config)
    if approve_id is not None:
        result = services.writeback.apply_decision(
            ReviewDecision(document_id=approve_id, action="approve", decided_by="cli-human")
        )
        typer.echo(json.dumps(result, indent=2))
        return
    if reject_id is not None:
        result = services.writeback.apply_decision(
            ReviewDecision(document_id=reject_id, action="reject", decided_by="cli-human")
        )
        typer.echo(json.dumps(result, indent=2))
        return

    queue = services.review_queue.queue(
        confidence_threshold=loaded.config.low_confidence_threshold,
        include_deferred=False,
    )
    typer.echo(f"Review queue items: {len(queue)}")
    for row in queue[:30]:
        typer.echo(
            f"#{row['id']} | {row['state']} | {row['vendor']} | {row['doc_date']} | {row['amount']} | conf={row['confidence_overall']:.2f}"
        )


@app.command("rebuild-index")
def rebuild_index(
    config: Path = typer.Option(default_config_path(), "--config", help="Path to config file"),
) -> None:
    _, services = _services(config)
    stats = services.ingestion.rebuild_indexes()
    typer.echo(json.dumps(stats, indent=2))


@app.command("monthly-report")
def monthly_report(
    year: int = typer.Option(..., "--year"),
    month: str = typer.Option(..., "--month"),
    config: Path = typer.Option(default_config_path(), "--config", help="Path to config file"),
) -> None:
    _, services = _services(config)
    report = services.report_service.generate_monthly_summary(year=year, month=month)
    typer.echo(f"Monthly report written: {report}")


@app.command("tax-report")
def tax_report(
    year: int = typer.Option(..., "--year"),
    config: Path = typer.Option(default_config_path(), "--config", help="Path to config file"),
) -> None:
    _, services = _services(config)
    report = services.report_service.generate_tax_report(year=year)
    typer.echo(f"Tax report written: {report}")


@app.command("review-app")
def review_app(
    config: Path = typer.Option(default_config_path(), "--config", help="Path to config file"),
    port: int = typer.Option(8501, "--port", help="Streamlit port"),
) -> None:
    review_path = Path(__file__).with_name("review_app.py")
    cmd = [
        "streamlit",
        "run",
        str(review_path),
        "--server.port",
        str(port),
        "--",
        "--config",
        str(config),
    ]
    typer.echo("Launching review dashboard...")
    subprocess.run(cmd, check=True)


@app.command("reports-refresh")
def reports_refresh(
    config: Path = typer.Option(default_config_path(), "--config", help="Path to config file"),
) -> None:
    _, services = _services(config)
    paths = services.report_service.generate_exception_reports()
    typer.echo("Generated reports:")
    for path in paths:
        typer.echo(f"- {path}")


@app.command("demo-seed")
def demo_seed(
    config: Path = typer.Option(default_config_path(), "--config", help="Path to config file"),
) -> None:
    _, services = _services(config)
    demo_file = services.ingestion.config.paths.docs_root / "sample_invoice_demo.txt"
    if not demo_file.exists():
        demo_file.write_text(
            """Invoice #INV-9001
Vendor: Demo Software LLC
Date: 2026-02-18
Amount Due: $79.00
Payment Method: Credit Card
Description: Monthly analytics subscription renewal
"""
        )
    outcome = services.ingestion.process_file(demo_file)
    typer.echo(f"Seeded demo document ({outcome}) at {datetime.now().isoformat(timespec='seconds')}")
