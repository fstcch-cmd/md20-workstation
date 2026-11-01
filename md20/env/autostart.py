"""Opt-in "resume unfinished MD20 work at login" (WP11).  Never installed silently; `md20 resume --remove-autostart` undoes it."""
from __future__ import annotations

import os
import sys
from pathlib import Path

NAME = "md20-resume"


def _cmd(projects_dir: str) -> list[str]:
    return [sys.executable, "-m", "md20", "--dir", str(projects_dir), "resume", "--all"]


def autostart_path() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / "Microsoft/Windows/Start Menu/Programs/Startup" / f"{NAME}.cmd"
    if sys.platform == "darwin":
        return Path.home() / "Library/LaunchAgents" / "tw.hcclab.md20.resume.plist"
    return Path.home() / ".config/autostart" / f"{NAME}.desktop"


def install_autostart(projects_dir: str) -> str:
    p = autostart_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    cmd = _cmd(projects_dir)
    if sys.platform == "win32":
        p.write_text("@echo off\r\nrem HCC Lab MD20 — resume unfinished workflows at login\r\n"
                     "start \"MD20 resume\" /min " + " ".join(f'"{c}"' for c in cmd) + "\r\n", encoding="utf-8")
    elif sys.platform == "darwin":
        args = "".join(f"<string>{c}</string>" for c in cmd)
        p.write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>'
                     f"<key>Label</key><string>tw.hcclab.md20.resume</string><key>ProgramArguments</key><array>{args}</array>"
                     f"<key>RunAtLoad</key><true/></dict></plist>\n", encoding="utf-8")
    else:
        p.write_text("[Desktop Entry]\nType=Application\nName=MD20 resume (HCC Lab)\nExec=" + " ".join(cmd) + "\n", encoding="utf-8")
    return f"已設定登入時自動續跑：{p}（移除：md20 resume --remove-autostart）"


def remove_autostart() -> str:
    p = autostart_path()
    if p.is_file():
        p.unlink()
        return f"已移除：{p}"
    return "沒有設定自動續跑。"
