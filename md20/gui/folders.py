"""D-88: where projects are stored, chosen by the user, and opening a project or workflow folder from anywhere.

The choice is kept per user (not per projects folder) in <app data>/gui_folders.json, so the GUI and the command
line open the same folder next time:  {"projects_dir": "...", "recent": ["...", ...]}.
MD20_GUI_FOLDERS overrides the file location (tests, side installs).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from ..util import load_json
from ..util.paths import app_data_dir, default_projects_dir

MAX_RECENT = 10


def settings_path() -> Path:
    p = os.environ.get("MD20_GUI_FOLDERS")
    return Path(p) if p else app_data_dir() / "gui_folders.json"


def load() -> dict:
    d = load_json(settings_path(), {})
    return d if isinstance(d, dict) else {}


def save(d: dict) -> None:
    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def saved_projects_dir() -> Path:
    """The folder chosen last time, else ~/Documents/MD20_Projects."""
    d = load().get("projects_dir")
    return Path(d) if d else default_projects_dir()


def check_folder(path: str | Path) -> tuple[bool, str]:
    """(usable, reason).  The folder must be an absolute path and writable; it is created when missing."""
    s = str(path or "").strip().strip('"')
    if not s:
        return False, "empty"
    p = Path(os.path.expanduser(s))
    if not p.is_absolute():
        return False, "relative"
    if p.exists() and not p.is_dir():
        return False, "not_a_folder"
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / f".md20_write_test_{uuid.uuid4().hex[:8]}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return False, f"not_writable:{exc}"
    return True, str(p)


def remember(path: str | Path) -> dict:
    """Make `path` the projects folder and put it first in the recent list."""
    d = load()
    s = str(Path(path))
    d["projects_dir"] = s
    d["recent"] = [s] + [r for r in d.get("recent") or [] if r != s][: MAX_RECENT - 1]
    save(d)
    return d


def recent() -> list[str]:
    """Recent projects folders that still exist."""
    return [r for r in load().get("recent") or [] if Path(r).is_dir()]


def classify(path: str | Path) -> dict:
    """What a folder the user points at is: a projects folder (holds projects), a project (project.json), a workflow
    (config.json inside <project>/workflows/), or something else.  Returns the projects folder to switch to and,
    when known, the project and workflow to open."""
    p = Path(os.path.expanduser(str(path or "").strip().strip('"')))
    if not p.is_dir():
        return {"kind": "missing", "path": str(p)}
    if (p / "config.json").is_file() and p.parent.name == "workflows" and (p.parent.parent / "project.json").is_file():
        proj = p.parent.parent
        return {"kind": "workflow", "projects_dir": str(proj.parent), "project": proj.name, "workflow": p.name}
    if p.name == "workflows" and (p.parent / "project.json").is_file():
        p = p.parent
    if (p / "project.json").is_file():
        return {"kind": "project", "projects_dir": str(p.parent), "project": p.name}
    if any((c / "project.json").is_file() for c in p.iterdir() if c.is_dir()):
        return {"kind": "projects_root", "projects_dir": str(p)}
    return {"kind": "empty_folder", "projects_dir": str(p)}


def project_workflows(projects_dir: str | Path, project: str) -> list[str]:
    w = Path(projects_dir) / project / "workflows"
    return sorted(x.name for x in w.iterdir() if (x / "config.json").is_file()) if w.is_dir() else []


PICKER = ("import sys, tkinter as tk\n"
          "from tkinter import filedialog\n"
          "r = tk.Tk(); r.withdraw()\n"
          "try:\n    r.attributes('-topmost', True)\nexcept Exception:\n    pass\n"
          "p = filedialog.askdirectory(initialdir=sys.argv[1] if len(sys.argv) > 1 else None, mustexist=False)\n"
          "print(p or '')\n")


def pick_folder(initial: str | Path | None = None, timeout_s: float = 600.0) -> str | None:
    """The operating system's folder dialog, shown on this computer (the GUI runs locally).  Run in its own Python
    process: Tk must own the main thread (macOS) and must not block the GUI server.  None when no dialog is
    available (no Tk, no display); "" when the user cancelled."""
    try:
        r = subprocess.run([sys.executable, "-c", PICKER] + ([str(initial)] if initial else []), capture_output=True,
                           text=True, timeout=timeout_s)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip()
