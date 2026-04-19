from __future__ import annotations

from decimal import Decimal
import os
from pathlib import Path
import tomllib
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


DEFAULT_DOCS_ROOT = Path("./sample_docs")
DEFAULT_WORKBOOK = (
    DEFAULT_DOCS_ROOT / "CWI_Expense_Tracker_Numbers_Mac_Compatible.xlsx"
)


class AppPaths(BaseModel):
    docs_root: Path = Field(default=DEFAULT_DOCS_ROOT)
    workbook_path: Path = Field(default=DEFAULT_WORKBOOK)
    sqlite_path: Path = Field(default=Path("./data/state.db"))
    logs_dir: Path = Field(default=Path("./logs"))
    reports_dir: Path = Field(default=Path("./reports"))
    backups_dir: Path = Field(default=Path("./backups"))


class AutoPostVendorPolicy(BaseModel):
    vendor: str
    allowed_categories: list[str] = Field(default_factory=list)
    min_overall_confidence: float = 0.97
    min_critical_confidence: float = 0.94
    max_amount: Decimal | None = None
    require_receipt_link: bool = True
    require_payment_method: bool = True
    require_business_purpose: bool = True
    require_tax_deductible_explicit: bool = True

    @field_validator("min_overall_confidence", "min_critical_confidence")
    @classmethod
    def _confidence_bounds(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("Confidence thresholds must be between 0 and 1")
        return value


class AgentConfig(BaseModel):
    paths: AppPaths = Field(default_factory=AppPaths)
    auto_create_categories: bool = False
    low_confidence_threshold: float = 0.75
    auto_post_enabled: bool = False
    auto_post_threshold: float = 0.95
    auto_post_min_critical_confidence: float = 0.9
    auto_post_blocked_categories: list[str] = Field(default_factory=list)
    auto_post_vendor_category_policies: list[AutoPostVendorPolicy] = Field(default_factory=list)
    trusted_vendors_for_bulk_approve: list[str] = Field(default_factory=list)

    @field_validator("auto_post_threshold", "auto_post_min_critical_confidence")
    @classmethod
    def _autopost_conf_bounds(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("Auto-post thresholds must be between 0 and 1")
        return value


@dataclass(slots=True)
class LoadedConfig:
    config: AgentConfig
    path: Path


def default_config_path(workdir: Path | None = None) -> Path:
    env_override = os.getenv("CWI_ACCOUNTANT_CONFIG")
    if env_override:
        return Path(env_override).expanduser()

    package_candidate = Path(__file__).resolve().parents[2] / "config" / "cwi_accountant.toml"
    if package_candidate.exists():
        return package_candidate

    root = workdir or Path.cwd()
    return root / "config" / "cwi_accountant.toml"


def discover_workbook(docs_root: Path) -> Path | None:
    preferred = docs_root / "CWI_Expense_Tracker_Numbers_Mac_Compatible.xlsx"
    if preferred.exists():
        return preferred

    candidates = sorted(
        docs_root.rglob("*.xlsx"),
        key=lambda p: (
            0
            if "expense" in p.name.lower() and "tracker" in p.name.lower()
            else 1,
            len(p.name),
            p.name.lower(),
        ),
    )
    return candidates[0] if candidates else None


def _parse_toml(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _merge_dict(base: dict, incoming: dict) -> dict:
    merged = dict(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _config_base_dir(config_path: Path) -> Path:
    if config_path.parent.name == "config":
        return config_path.parent.parent
    return config_path.parent


def _resolve_path(base_dir: Path, target: Path) -> Path:
    if target.is_absolute():
        return target
    return (base_dir / target).resolve()


def create_default_config(path: Path) -> AgentConfig:
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = AgentConfig()
    base_dir = _config_base_dir(path)
    cfg.paths.sqlite_path = (base_dir / "data" / "state.db").resolve()
    cfg.paths.logs_dir = (base_dir / "logs").resolve()
    cfg.paths.reports_dir = (base_dir / "reports").resolve()
    cfg.paths.backups_dir = (base_dir / "backups").resolve()

    workbook = discover_workbook(cfg.paths.docs_root)
    if workbook is not None:
        cfg.paths.workbook_path = workbook

    text = f"""# CWI Accounting Agent configuration
# Generated on {datetime.now().isoformat(timespec='seconds')}

[paths]
docs_root = \"{cfg.paths.docs_root}\"
workbook_path = \"{cfg.paths.workbook_path}\"
sqlite_path = \"{cfg.paths.sqlite_path}\"
logs_dir = \"{cfg.paths.logs_dir}\"
reports_dir = \"{cfg.paths.reports_dir}\"
backups_dir = \"{cfg.paths.backups_dir}\"

auto_create_categories = {str(cfg.auto_create_categories).lower()}
low_confidence_threshold = {cfg.low_confidence_threshold}
auto_post_enabled = {str(cfg.auto_post_enabled).lower()}
auto_post_threshold = {cfg.auto_post_threshold}
auto_post_min_critical_confidence = {cfg.auto_post_min_critical_confidence}
auto_post_blocked_categories = []
trusted_vendors_for_bulk_approve = []
auto_post_vendor_category_policies = []

# Example strict policy (uncomment and edit):
# [[auto_post_vendor_category_policies]]
# vendor = "OpenAI"
# allowed_categories = ["Software / SaaS"]
# min_overall_confidence = 0.98
# min_critical_confidence = 0.95
# max_amount = "500.00"
# require_receipt_link = true
# require_payment_method = true
# require_business_purpose = true
# require_tax_deductible_explicit = true
"""
    path.write_text(text)
    return cfg


def load_config(path: Path | None = None, create_if_missing: bool = True) -> LoadedConfig:
    cfg_path = path or default_config_path()
    if not cfg_path.exists():
        if not create_if_missing:
            raise FileNotFoundError(f"Config file not found: {cfg_path}")
        config = create_default_config(cfg_path)
    else:
        defaults = AgentConfig().model_dump(mode="python")
        data = _parse_toml(cfg_path)
        merged = _merge_dict(defaults, data)
        config = AgentConfig.model_validate(merged)

    base_dir = _config_base_dir(cfg_path)
    config.paths.docs_root = _resolve_path(base_dir, config.paths.docs_root)
    config.paths.workbook_path = _resolve_path(base_dir, config.paths.workbook_path)
    config.paths.sqlite_path = _resolve_path(base_dir, config.paths.sqlite_path)
    config.paths.logs_dir = _resolve_path(base_dir, config.paths.logs_dir)
    config.paths.reports_dir = _resolve_path(base_dir, config.paths.reports_dir)
    config.paths.backups_dir = _resolve_path(base_dir, config.paths.backups_dir)

    workbook = config.paths.workbook_path
    if not workbook.exists():
        discovered = discover_workbook(config.paths.docs_root)
        if discovered is not None:
            config.paths.workbook_path = discovered

    for attr in ["logs_dir", "reports_dir", "backups_dir", "sqlite_path"]:
        target = getattr(config.paths, attr)
        parent = target.parent if attr == "sqlite_path" else target
        parent.mkdir(parents=True, exist_ok=True)

    return LoadedConfig(config=config, path=cfg_path)
