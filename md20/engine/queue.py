"""Laptop-friendly job queue and pause policy.

* Jobs (case + tier + replicas) are stored in `<project>/queue.json` and run one
  at a time; a crash or power loss leaves the queue file truthful.
* `PausePolicy` is consulted at every chunk boundary: user pause file,
  battery power, or an allowed time window ("only run 22:00–07:00").  Pausing
  is clean — the next `md20 queue run` resumes from the last chunk.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..project import Project
from ..util import atomic_write_json, load_json, now_iso, FileLock


@dataclass
class PausePolicy:
    pause_file: Path | None = None               # touch this file to pause at the next chunk boundary
    pause_on_battery: bool = True
    allowed_hours: tuple[int, int] | None = None  # (start_hour, end_hour) local time, may wrap midnight
    power_probe: Callable[[], dict] | None = None  # returns {"has_battery":..,"on_ac":..}
    clock: Callable[[], _dt.datetime] = field(default=_dt.datetime.now)

    def __call__(self) -> str | None:
        if self.pause_file is not None and Path(self.pause_file).exists():
            return f"使用者要求暫停（存在 {Path(self.pause_file).name}）"
        if self.pause_on_battery and self.power_probe is not None:
            try:
                pw = self.power_probe()
                if pw.get("has_battery") and not pw.get("on_ac", True):
                    return "筆電使用電池供電；在 chunk 邊界暫停，接上電源後續跑"
            except Exception:  # noqa: BLE001
                pass
        if self.allowed_hours is not None:
            h = self.clock().hour
            a, b = self.allowed_hours
            inside = (a <= h < b) if a <= b else (h >= a or h < b)
            if not inside:
                return f"目前 {h:02d}:00 不在允許時段 {a:02d}:00–{b:02d}:00"
        return None


class JobQueue:
    def __init__(self, project: Project):
        self.project = project
        self.path = project.dir / "queue.json"

    def _load(self) -> dict:
        return load_json(self.path, {"jobs": []})

    def _save(self, data: dict) -> None:
        atomic_write_json(data, self.path)

    def add(self, case_id: str, tier: str = "teaching", replicas: int = 1, production_ns: float | None = None) -> dict:
        with FileLock(self.path.with_suffix(".lock")):
            data = self._load()
            job = {"id": f"job_{len(data['jobs']) + 1:04d}", "case_id": case_id, "tier": tier, "replicas": int(replicas),
                   "production_ns": production_ns, "status": "QUEUED", "created_at": now_iso()}
            data["jobs"].append(job)
            self._save(data)
        return job

    def jobs(self) -> list[dict]:
        return list(self._load()["jobs"])

    def _set(self, job_id: str, **fields) -> None:
        with FileLock(self.path.with_suffix(".lock")):
            data = self._load()
            for j in data["jobs"]:
                if j["id"] == job_id:
                    j.update(fields, updated_at=now_iso())
            self._save(data)

    def run_next(self, make_backend_factory: Callable, *, should_pause: Callable[[], str | None] | None = None,
                 progress_cb=None, batch_steps: int | None = None) -> dict | None:
        """Run the first QUEUED/PAUSED job.  Returns the job record or None if the queue is empty."""
        from .protocol import make_protocol
        from .replicas import run_replicas
        job = next((j for j in self.jobs() if j["status"] in {"QUEUED", "PAUSED"}), None)
        if job is None:
            return None
        if should_pause is not None and (reason := should_pause()):
            self._set(job["id"], status="PAUSED", reason=reason)
            return {**job, "status": "PAUSED", "reason": reason}
        group_id = job.get("replica_group") or f"rep_{job['id']}"
        self._set(job["id"], status="RUNNING", replica_group=group_id)
        case = self.project.case(job["case_id"])
        proto = make_protocol(job["tier"], replicas=job["replicas"], production_ns=job.get("production_ns"))
        make = make_backend_factory(case, proto)
        summary = run_replicas(case, proto, make, n=job["replicas"], should_pause=should_pause, progress_cb=progress_cb,
                               batch_steps=batch_steps, group_id=group_id)
        statuses = {r["status"] for r in summary["runs"]}
        if "PAUSED" in statuses:
            self._set(job["id"], status="PAUSED", reason=next(r.get("reason") for r in summary["runs"] if r["status"] == "PAUSED"))
        elif "NEEDS_HUMAN" in statuses:
            self._set(job["id"], status="NEEDS_HUMAN", reason=next(r.get("reason") for r in summary["runs"] if r["status"] == "NEEDS_HUMAN"))
        else:
            self._set(job["id"], status="COMPLETE")
        return next(j for j in self.jobs() if j["id"] == job["id"])
