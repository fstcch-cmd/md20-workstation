"""GUI state and background-job handling (pure Python, no NiceGUI needed)."""
from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..util import default_projects_dir, now_iso
from .buffers import HeartbeatBuffer


class BackgroundJob:
    """Runs `fn(*args, **kwargs)` in a daemon thread; the GUI polls `status` with `ui.timer`.

    status: IDLE → RUNNING → DONE | ERROR.  `result` / `error` / `traceback` are set at the end.
    """

    def __init__(self, name: str, fn: Callable, *args, **kwargs):
        self.name = name
        self._fn, self._args, self._kwargs = fn, args, kwargs
        self.status = "IDLE"
        self.result: Any = None
        self.error: str = ""
        self.traceback: str = ""
        self.started_at: str = ""
        self.finished_at: str = ""
        self._thread: threading.Thread | None = None

    def start(self) -> "BackgroundJob":
        if self._thread is not None:
            raise RuntimeError(f"工作 {self.name} 已經啟動過")
        self.status = "RUNNING"
        self.started_at = now_iso()
        self._thread = threading.Thread(target=self._target, name=f"md20-gui-{self.name}", daemon=True)
        self._thread.start()
        return self

    def _target(self) -> None:
        try:
            self.result = self._fn(*self._args, **self._kwargs)
            self.status = "DONE"
        except BaseException as exc:  # noqa: BLE001 - surface every failure in the GUI
            self.error = f"{type(exc).__name__}: {exc}"
            self.traceback = traceback.format_exc()
            self.status = "ERROR"
        finally:
            self.finished_at = now_iso()

    @property
    def running(self) -> bool:
        return self.status == "RUNNING"

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)


@dataclass
class GuiState:
    """Everything the pages share.  One instance per `launch()` (single local user)."""
    projects_dir: Path = field(default_factory=default_projects_dir)
    active_project: Any = None          # md20.project.Project | None
    active_case: Any = None             # md20.project.Case | None
    active_run: Any = None              # md20.project.Run | None
    jobs: dict = field(default_factory=dict)          # kind ("doctor","build","run","dock","report") → BackgroundJob
    progress: dict = field(default_factory=dict)      # last heartbeat (written from the worker thread)
    heartbeats: HeartbeatBuffer = field(default_factory=HeartbeatBuffer)
    last_build: dict | None = None      # last build_case summary
    build_inputs: dict = field(default_factory=dict)  # form values of the last build (for retry)
    last_doctor: Any = None             # DoctorReport
    last_docking: dict = field(default_factory=dict)  # {"result":…, "selection":…, "ligands":…, "receptor":…}
    handoff: dict | None = None         # docking → build inputs
    static_routes: dict = field(default_factory=dict) # run dir → url prefix

    def __post_init__(self):
        self.projects_dir = Path(self.projects_dir)

    # ---- selection -------------------------------------------------------------
    def set_projects_dir(self, path: Path | str) -> None:
        self.projects_dir = Path(path)
        self.active_project = self.active_case = self.active_run = None

    def select_project(self, project) -> None:
        self.active_project = project
        self.active_case = self.active_run = None

    def select_case(self, case) -> None:
        self.active_case = case
        self.active_run = case.active_run() if case is not None else None

    def select_run(self, run) -> None:
        self.active_run = run

    # ---- jobs --------------------------------------------------------------------
    def job(self, kind: str) -> BackgroundJob | None:
        return self.jobs.get(kind)

    def is_running(self, kind: str) -> bool:
        j = self.jobs.get(kind)
        return bool(j and j.running)

    def start_job(self, kind: str, fn: Callable, *args, **kwargs) -> BackgroundJob:
        if self.is_running(kind):
            raise RuntimeError(f"已有「{kind}」工作在執行中，請等它結束。")
        j = BackgroundJob(kind, fn, *args, **kwargs)
        self.jobs[kind] = j
        return j.start()

    def progress_cb(self, hb: dict) -> None:
        """Engine heartbeat → shared dict + plot buffer.  Called from the worker thread."""
        self.progress.update(hb)  # update (not clear+update) so a concurrent reader never sees an empty dict
        self.heartbeats.append(hb)

    @property
    def pause_file(self) -> Path | None:
        return self.active_project.dir / "PAUSE" if self.active_project is not None else None
