"""Cross-platform path helpers.  No `/content`, no Google Drive, no hard-coded POSIX paths."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_APP = "MD20"


def app_data_dir() -> Path:
    """Per-user writable directory for MD20 settings, doctor reports and caches."""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / _APP
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / _APP
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / _APP


def default_projects_dir() -> Path:
    """Where projects live by default: ~/Documents/MD20_Projects (Documents exists on all three OSes)."""
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / "MD20_Projects"


def ensure_dir(path: Path | str) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_name(value: str, fallback: str = "item", max_len: int = 80) -> str:
    """File-system safe identifier (Windows reserved characters removed)."""
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip())
    value = re.sub(r"_+", "_", value).strip("_.")
    if value.upper() in {"CON", "PRN", "AUX", "NUL"} or re.match(r"^(COM|LPT)\d$", value.upper()):
        value = f"{value}_"
    return (value or fallback)[:max_len]
