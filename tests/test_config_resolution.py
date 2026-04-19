from pathlib import Path

from cwi_accountant.config import create_default_config, default_config_path, load_config


def test_load_config_resolves_relative_paths_from_project_root(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    (project / "config").mkdir(parents=True)
    docs = project / "docs"
    docs.mkdir()
    workbook = docs / "tracker.xlsx"
    workbook.write_bytes(b"placeholder")

    cfg = project / "config" / "cwi_accountant.toml"
    cfg.write_text(
        """
[paths]
docs_root = "docs"
workbook_path = "docs/tracker.xlsx"
sqlite_path = "data/state.db"
logs_dir = "logs"
reports_dir = "reports"
backups_dir = "backups"

auto_create_categories = false
low_confidence_threshold = 0.75
auto_post_enabled = false
auto_post_threshold = 0.95
auto_post_min_critical_confidence = 0.9
auto_post_blocked_categories = []
trusted_vendors_for_bulk_approve = []
auto_post_vendor_category_policies = []
""".strip()
    )

    loaded = load_config(cfg, create_if_missing=False).config

    assert loaded.paths.docs_root == (project / "docs").resolve()
    assert loaded.paths.workbook_path == (project / "docs" / "tracker.xlsx").resolve()
    assert loaded.paths.sqlite_path == (project / "data" / "state.db").resolve()
    assert loaded.paths.logs_dir == (project / "logs").resolve()


def test_create_default_config_writes_absolute_operational_paths(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    cfg_path = project / "config" / "cwi_accountant.toml"
    created = create_default_config(cfg_path)

    assert created.paths.sqlite_path.is_absolute()
    assert created.paths.logs_dir.is_absolute()
    assert created.paths.reports_dir.is_absolute()
    assert created.paths.backups_dir.is_absolute()


def test_default_config_path_honors_env_override(tmp_path: Path, monkeypatch) -> None:
    override = tmp_path / "custom.toml"
    monkeypatch.setenv("CWI_ACCOUNTANT_CONFIG", str(override))
    assert default_config_path() == override
