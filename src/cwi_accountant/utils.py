from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path

from dateutil import parser as date_parser


SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".heic",
    ".csv",
    ".txt",
    ".xlsx",
    ".xls",
    ".docx",
}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_vendor_name(name: str | None) -> str:
    if not name:
        return ""
    out = name.lower().strip()
    out = re.sub(r"\b(inc|llc|l\.l\.c\.|corp|corporation|co\.)\b", "", out)
    out = re.sub(r"[^a-z0-9 ]+", " ", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out


def parse_possible_date(text: str | None) -> date | None:
    if not text:
        return None
    try:
        parsed = date_parser.parse(text, fuzzy=True)
        return parsed.date()
    except Exception:
        return None


def safe_decimal_str(value: object) -> str:
    return "" if value is None else str(value)


def is_supported_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS and path.is_file()
