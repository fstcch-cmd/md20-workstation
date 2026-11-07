"""D-103: the GUI's calculation runs in its own process, never in the GUI's process.

Why: a calculation thread inside the NiceGUI process shares the GIL with the event loop.  Loading a large OpenMM
XML, WHAM/MBAR bootstraps or report figures held the GIL long enough that the browser's WebSocket heartbeat went
unanswered and the page showed "connection lost"; the progress lived only in an in-memory queue, so after a
reconnect or a GUI restart the progress line, live curves and umbrella alerts were gone.

What the worker leaves on disk (everything the GUI shows is read back from here):
  <workflow>/_gui_job/job.json        pid, status, message, report, started_at, heartbeat (every HEARTBEAT_S)
  <workflow>/_gui_job/progress.jsonl  one JSON object per progress event (the same dicts wf.run gives progress_cb)
  <workflow>/_gui_job/worker.log      the worker's stdout/stderr
  <projects root>/_gui_running.json   which workflow is running now (the header banner and D-67 one-at-a-time)

`python -m md20.gui.worker --project <project dir> --name <workflow>`.  This module must not import NiceGUI.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

JOB_DIR = "_gui_job"
POINTER = "_gui_running.json"
HEARTBEAT_S = 5.0
# A worker that holds the GIL in a long C call can miss beats; a worker is declared gone only after this long
# without one (and immediately when the GUI owns its process handle and the process has exited).
STALE_S = 180.0

PAUSED_MSG = ["已暫停。按「開始或繼續」會從停下的地方接著跑。",
              "Paused. Press Start or continue to carry on from where it stopped.",
              "一時停止しました。「開始または再開」を押すと、止まったところから続きます。",
              "일시 정지했습니다. '시작 또는 계속'을 누르면 멈춘 곳부터 이어서 실행합니다."]
DONE_MSG = ["完成", "Done", "完了しました", "완료"]


def job_dir(wf_dir) -> Path:
    return Path(wf_dir) / JOB_DIR


def pointer_path(root) -> Path:
    return Path(root) / POINTER


def _write_json(obj: dict, path: Path) -> None:
    """Atomic replace; on Windows a reader holding the file makes os.replace fail for a moment — retry briefly."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, default=str), encoding="utf-8")
    for k in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (k + 1))
    tmp.unlink(missing_ok=True)


def read_json(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def read_job(wf_dir) -> dict:
    return read_json(job_dir(wf_dir) / "job.json")


def heartbeat_fresh(info: dict, now: float | None = None) -> bool:
    return info.get("status") == "RUNNING" and (now or time.time()) - float(info.get("heartbeat") or 0) < STALE_S


class ProgressReader:
    """Incremental reader of progress.jsonl: only whole lines, from where the last call stopped."""

    def __init__(self, path: Path, keep: int = 2000):
        self.path, self.keep = Path(path), keep
        self.offset = 0
        self.history: list[dict] = []
        self._ident = None

    def read(self) -> list[dict]:
        try:
            st = self.path.stat()
        except OSError:
            return self.history
        ident = (getattr(st, "st_ino", 0), getattr(st, "st_ctime_ns", 0))
        if self._ident is not None and (ident != self._ident or st.st_size < self.offset):   # a new run truncated it
            self.offset, self.history = 0, []
        self._ident = ident
        if st.st_size == self.offset:
            return self.history
        with open(self.path, "rb") as fh:
            fh.seek(self.offset)
            data = fh.read()
        end = data.rfind(b"\n")
        if end < 0:                                   # half a line: the writer is in the middle of it
            return self.history
        for line in data[:end].splitlines():
            try:
                self.history.append(json.loads(line.decode("utf-8")))
            except ValueError:
                continue
        self.offset += end + 1
        self.history = self.history[-self.keep:]
        return self.history


class _Sink:
    def __init__(self, path: Path):
        self.fh = open(path, "a", encoding="utf-8")
        self.lock = threading.Lock()

    def __call__(self, ev: dict) -> None:
        line = json.dumps(ev, ensure_ascii=False, default=str)
        with self.lock:
            self.fh.write(line + "\n")
            self.fh.flush()


def _resource_mode(root: Path) -> str:
    from ..env.resources import MODES
    m = read_json(root / "gui_settings.json").get("resource_mode", "balanced")
    return m if m in MODES else "balanced"


def run_worker(project_dir, name: str, *, run_fn=None) -> dict:
    """Run one workflow and keep job.json / progress.jsonl / the pointer current.  `run_fn(wf, progress_cb)` replaces
    the real driver in tests."""
    from ..project import Project
    from ..workflow import Workflow, WorkflowBlocked
    project_dir = Path(project_dir)
    root = project_dir.parent
    wf = Workflow.open(Project(project_dir), name)
    jd = job_dir(wf.dir)
    jd.mkdir(parents=True, exist_ok=True)
    (jd / "progress.jsonl").write_text("", encoding="utf-8")            # a new run starts a new progress record
    info = {"pid": os.getpid(), "project": str(project_dir), "name": wf.name, "status": "RUNNING", "message": "",
            "report": "", "started_at": time.time(), "heartbeat": time.time()}
    lock = threading.Lock()

    def save():
        with lock:
            info["heartbeat"] = time.time()
            _write_json(info, jd / "job.json")
            if info["status"] == "RUNNING":
                _write_json({"project": info["project"], "name": info["name"], "pid": info["pid"],
                             "heartbeat": info["heartbeat"]}, pointer_path(root))

    stop = threading.Event()

    def beat():
        while not stop.wait(HEARTBEAT_S):
            save()
    save()
    threading.Thread(target=beat, name="md20-heartbeat", daemon=True).start()
    sink = _Sink(jd / "progress.jsonl")
    try:
        if run_fn is not None:
            out = run_fn(wf, sink)
        else:
            out = _real_run(wf, root, sink)
        info["status"] = out["status"]
        info["report"] = str(out.get("report", "") or "")
        info["message"] = DONE_MSG if out["status"] == "COMPLETE" else PAUSED_MSG
    except WorkflowBlocked as exc:
        info["status"], info["message"] = "NEEDS_HUMAN", str(exc)
    except BaseException as exc:  # noqa: BLE001  (KeyboardInterrupt too: the GUI must see that the run ended)
        info["status"], info["message"] = "ERROR", f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-2000:]}"
    finally:
        stop.set()
        save()
        p = read_json(pointer_path(root))
        if p.get("pid") == os.getpid():
            pointer_path(root).unlink(missing_ok=True)
        sink.fh.close()
    return info


def _real_run(wf, root: Path, sink) -> dict:
    """The same driver call the GUI made in its thread before D-103 (app._start)."""
    fake = os.environ.get("MD20_GUI_FAKE_RUN")
    if fake:
        from .logic import _fake_run
        return _fake_run(wf, float(fake), sink)
    from ..engine import PausePolicy
    from ..engine.factory import make_backend_factory
    from ..env import choose_platform
    from ..env.hardware import _power_state
    from ..env.resources import CachedGuard
    platform = choose_platform()          # probed here, not in the GUI process (it imports OpenMM and runs a context)
    policy = PausePolicy(pause_file=wf.project.dir / "PAUSE", pause_on_battery=True, power_probe=_power_state,
                         resource_guard=CachedGuard())
    os.environ["MD20_RESOURCE_MODE"] = _resource_mode(root)
    # D-68: the resource mode is read again for every case, so a change in the GUI applies from the next step
    return wf.run(lambda case, proto: make_backend_factory(case, proto, platform=platform, resource_mode=_resource_mode(root)),
                  platform, should_pause=policy, progress_cb=sink)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="md20.gui.worker")
    ap.add_argument("--project", required=True)
    ap.add_argument("--name", required=True)
    a = ap.parse_args(argv)
    info = run_worker(a.project, a.name)
    return 0 if info["status"] in ("COMPLETE", "PAUSED", "NEEDS_HUMAN") else 1


if __name__ == "__main__":
    sys.exit(main())
