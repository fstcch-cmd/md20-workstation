"""Resumable chunked stage runner with a self-healing watchdog.

Ported from the Colab v6.1 `md_run_segment` (chunk = unit of recovery) with
these changes:

* no `/content` cache, no Drive heartbeat thread, no `fcntl`;
* chunk artefacts are verified with a *cheap* fingerprint on resume (full
  SHA-256 only when the stage is sealed);
* a watchdog samples energy/temperature every batch; on NaN or runaway it
  rolls back to the last confirmed chunk, halves the timestep, retries, and
  only after `max_retries` escalates to NEEDS_HUMAN with a readable reason;
* temperature ramps and in-stage restraint release are linear in *local*
  progress so a resumed stage continues the same schedule.

Everything the runner knows is in `<stage>_progress.json`; the in-memory
state is disposable.
"""
from __future__ import annotations

import math
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..util import (atomic_write_json, load_json, atomic_copy, cheap_fingerprint, verify_cheap_fingerprint,
                    sha256_file, now_iso, DecisionLog)
from .backend import Backend, StateSummary
from .protocol import StageSpec


class WatchdogError(RuntimeError):
    """Raised internally when a chunk is judged unstable."""


class Paused(RuntimeError):
    """Stage paused at a chunk boundary (battery, user request, schedule); resumable as-is."""

    def __init__(self, reason: str, *, stage: str, completed_local_steps: int):
        super().__init__(reason)
        self.stage = stage
        self.completed_local_steps = completed_local_steps


class NeedsHuman(RuntimeError):
    """Stage cannot continue automatically; message is student-readable."""

    def __init__(self, message: str, *, stage: str, evidence: dict | None = None):
        super().__init__(message)
        self.stage = stage
        self.evidence = evidence or {}


@dataclass
class StageResult:
    stage: str
    status: str                       # PASS | NEEDS_HUMAN
    state_path: str
    log_path: str
    dcd_paths: list[str]
    steps: int
    chunks: int
    elapsed_s: float
    final: dict
    identity: dict
    watchdog_events: list[dict] = field(default_factory=list)


BackendFactory = Callable[[StageSpec, float], Backend]   # (spec, timestep_fs) -> backend


def _artifact(path: Path) -> dict:
    return {"path": str(path), **cheap_fingerprint(path)}


def _verify_chunks(progress: dict, stage_dir: Path) -> tuple[list[dict], int, Path | None]:
    """Return (valid chunks, completed local steps, last state path).  Truncates at first bad chunk."""
    chunks = list(progress.get("chunks", []))
    valid, completed, last_state = [], 0, None
    for expected, row in enumerate(chunks, 1):
        if int(row.get("chunk", -1)) != expected or int(row.get("start_local_step", -1)) != completed:
            break
        ok = True
        for role, rec in (row.get("artifacts") or {}).items():
            if role in {"state", "log"} and not verify_cheap_fingerprint(rec["path"], rec):
                ok = False
                break
        if not ok:
            break
        valid.append(row)
        completed = int(row["end_local_step"])
        last_state = Path(row["artifacts"]["state"]["path"])
    return valid, completed, last_state


def run_stage(stage_dir: Path | str, spec: StageSpec, make_backend: BackendFactory, *, identity: dict,
              initial_state: Path | None, decisions: DecisionLog | None = None, write_dcd: bool = True,
              max_retries: int = 3, min_timestep_fs: float = 0.5, progress_cb: Callable[[dict], None] | None = None,
              batch_steps: int | None = None, clock: Callable[[], float] = time.monotonic,
              should_pause: Callable[[], str | None] | None = None) -> StageResult:
    stage_dir = Path(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)
    name = spec.name
    progress_path = stage_dir / f"{name}_progress.json"
    heartbeat_path = stage_dir / f"{name}_running.json"
    complete_path = stage_dir / f"{name}_complete.json"
    total = spec.steps()
    chunk_steps = max(1, min(total, spec.interval_steps(spec.checkpoint_interval_ps)))
    report_steps = spec.interval_steps(spec.report_interval_ps)
    dcd_steps = spec.interval_steps(spec.trajectory_interval_ps)
    batch = int(batch_steps or max(50, min(report_steps, 2000)))

    # ---- resume -------------------------------------------------------------
    progress = load_json(progress_path, {})
    for key, value in identity.items():
        if progress.get(key) not in (None, value):
            raise NeedsHuman(f"{name} 的既有進度屬於另一個 run/config（{key} 不一致）；請建立新 run，不要覆寫。",
                             stage=name, evidence={"expected": value, "found": progress.get(key)})
    chunks, completed, last_state = _verify_chunks(progress, stage_dir)
    if progress.get("chunks") and len(chunks) < len(progress["chunks"]):
        bad = len(progress["chunks"]) - len(chunks)
        if decisions:
            decisions.record(f"engine.{name}", "resume", f"discard {bad} damaged chunk(s)",
                             "續跑時發現後段 chunk 檔案損壞或不完整；只重算這些 chunk，之前確認過的保留。", kind="auto_fixed",
                             stage_name=name, discarded=bad)
    if completed >= total and chunks:
        # already done: fall through to sealing (idempotent)
        pass
    events: list[dict] = list(progress.get("watchdog_events", []))
    started = clock()
    dt = spec.timestep_fs
    backend = make_backend(spec, dt)
    try:
        backend.initialize(str(last_state) if last_state else (str(initial_state) if initial_state else None),
                           spec.start_temperature_k if spec.start_temperature_k is not None else spec.temperature_k,
                           spec.seed, spec.regenerate_velocities and completed == 0)
        absolute_start = backend.current_step() - completed
        retries = 0
        while completed < total:
            if should_pause is not None:
                reason = should_pause()
                if reason:
                    atomic_write_json({**identity, "status": "PAUSED", "stage": name, "reason": reason, "total_steps": total,
                                       "completed_local_steps": completed, "chunks": chunks,
                                       "watchdog_events": events, "updated_at": now_iso()}, progress_path)
                    heartbeat_path.unlink(missing_ok=True)
                    raise Paused(reason, stage=name, completed_local_steps=completed)
            chunk_id = len(chunks) + 1
            todo = min(chunk_steps, total - completed)
            tmp = stage_dir / f"_tmp_chunk_{chunk_id:05d}"
            shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir()
            log_tmp, dcd_tmp = tmp / "chunk.log", (tmp / "chunk.dcd" if write_dcd and spec.ensemble != "MIN" else None)
            try:
                backend.start_reporters(log_tmp, dcd_tmp, min(report_steps, todo), min(dcd_steps, todo), absolute_start + total)
                advanced = 0
                while advanced < todo:
                    n = min(batch, todo - advanced)
                    frac_after = (completed + advanced + n) / total
                    _apply_schedule(backend, spec, frac_after)
                    backend.step(n)
                    advanced += n
                    s = backend.summary()
                    _watch(s, spec, frac_after, chunk_id)
                    hb = {"status": "RUNNING", **identity, "stage": name, "chunk": chunk_id,
                          "completed_local_steps": completed + advanced, "total_steps": total,
                          "absolute_step": s.step, "temperature_k": s.temperature_k,
                          "potential_kj_mol": s.potential_kj_mol, "timestep_fs": dt, "heartbeat_at": now_iso(),
                          "elapsed_s": round(clock() - started, 1)}
                    atomic_write_json(hb, heartbeat_path, backup=False)
                    if progress_cb:
                        progress_cb(hb)
                backend.stop_reporters()
                # seal chunk
                cp = stage_dir / f"chunk_{chunk_id:05d}"
                arts = {}
                backend.save_state(tmp / "final.xml"); atomic_copy(tmp / "final.xml", cp.with_suffix(".xml"))
                arts["state"] = _artifact(cp.with_suffix(".xml"))
                backend.save_checkpoint(tmp / "final.chk"); atomic_copy(tmp / "final.chk", cp.with_suffix(".chk"))
                arts["checkpoint"] = _artifact(cp.with_suffix(".chk"))
                atomic_copy(log_tmp, cp.with_suffix(".log")); arts["log"] = _artifact(cp.with_suffix(".log"))
                if dcd_tmp is not None and dcd_tmp.is_file() and dcd_tmp.stat().st_size > 0:
                    atomic_copy(dcd_tmp, cp.with_suffix(".dcd")); arts["dcd"] = _artifact(cp.with_suffix(".dcd"))
                row = {"chunk": chunk_id, "start_local_step": completed, "end_local_step": completed + todo,
                       "steps": todo, "absolute_step": backend.current_step(), "timestep_fs": dt,
                       "artifacts": arts, "summary": backend.summary().to_dict(), "completed_at": now_iso()}
                chunks.append(row)
                completed += todo
                last_state = cp.with_suffix(".xml")
                atomic_write_json({**identity, "status": "RUNNING", "stage": name, "total_steps": total,
                                   "completed_local_steps": completed, "chunks": chunks,
                                   "watchdog_events": events, "updated_at": now_iso()}, progress_path)
                shutil.rmtree(tmp, ignore_errors=True)
                if dt != spec.timestep_fs:
                    # one clean chunk at the reduced timestep: restore the protocol timestep
                    dt = spec.timestep_fs
                    backend.set_timestep_fs(dt)
                    if decisions:
                        decisions.record(f"engine.{name}", "timestep", dt, "縮小 dt 後已穩定完成一個 chunk，恢復 protocol 的 dt。",
                                         kind="auto_fixed", chunk=chunk_id)
                retries = 0
            except WatchdogError as exc:
                backend.stop_reporters()
                shutil.rmtree(tmp, ignore_errors=True)
                retries += 1
                events.append({"chunk": chunk_id, "attempt": retries, "error": str(exc), "timestep_fs": dt, "at": now_iso()})
                if retries > max_retries or dt / 2 < min_timestep_fs:
                    atomic_write_json({**identity, "status": "NEEDS_HUMAN", "stage": name, "error": str(exc),
                                       "completed_local_steps": completed, "chunks": chunks,
                                       "watchdog_events": events, "updated_at": now_iso()}, progress_path)
                    raise NeedsHuman(
                        f"{name} 階段在 chunk {chunk_id} 連續 {retries} 次不穩定（{exc}）。"
                        "已自動嘗試縮小時間步長仍失敗。常見原因：配體參數有誤（請看 build 的配體煙霧測試）、"
                        "起始結構有嚴重碰撞（看 Phase 14 幾何閘門）、或約束釋放太快。"
                        f"可從 chunk {len(chunks)} 的 state 手動續跑。", stage=name,
                        evidence={"events": events, "last_confirmed_chunk": len(chunks)}) from exc
                dt = dt / 2.0
                if decisions:
                    decisions.record(f"engine.{name}", "watchdog", f"retry chunk {chunk_id} with dt={dt} fs",
                                     f"偵測到不穩定（{exc}）；回到最後確認的 chunk {len(chunks)}，時間步長減半後重試。",
                                     kind="auto_fixed", attempt=retries)
                backend.close()
                backend = make_backend(spec, dt)
                backend.initialize(str(last_state) if last_state else (str(initial_state) if initial_state else None),
                                   spec.start_temperature_k if spec.start_temperature_k is not None else spec.temperature_k,
                                   spec.seed + retries, True)
                absolute_start = backend.current_step() - completed
        # ---- seal stage -----------------------------------------------------
        final_state = stage_dir / f"{name}_state.xml"
        atomic_copy(last_state, final_state)
        atomic_copy(chunks[-1]["artifacts"]["checkpoint"]["path"], stage_dir / f"{name}.chk")
        backend.write_pdb(stage_dir / f"{name}_final.pdb")
        log_path = stage_dir / f"{name}.log"
        _concat_logs([c["artifacts"]["log"]["path"] for c in chunks], log_path)
        dcds = [c["artifacts"]["dcd"]["path"] for c in chunks if "dcd" in c["artifacts"]]
        final_summary = backend.summary().to_dict()
        result = StageResult(stage=name, status="PASS", state_path=str(final_state), log_path=str(log_path),
                             dcd_paths=dcds, steps=total, chunks=len(chunks), elapsed_s=round(clock() - started, 1),
                             final=final_summary, identity=identity, watchdog_events=events)
        atomic_write_json({**identity, "status": "PASS", "stage": name, "result": result.__dict__,
                           "state_sha256": sha256_file(final_state), "timestep_fs": spec.timestep_fs,
                           "platform": getattr(backend, "platform_name", None), "backend_info": getattr(backend, "info", {}),
                           "sealed_at": now_iso()}, complete_path)
        heartbeat_path.unlink(missing_ok=True)
        return result
    finally:
        try:
            backend.close()
        except Exception:  # noqa: BLE001
            pass


def _apply_schedule(backend: Backend, spec: StageSpec, frac: float) -> None:
    """Linear temperature ramp and restraint release as a function of local progress."""
    if spec.start_temperature_k is not None:
        backend.set_temperature(_ramp_target(spec, frac))
    if spec.restraint_scale_end is not None:
        k = spec.restraint_scale + (spec.restraint_scale_end - spec.restraint_scale) * min(1.0, frac)
        backend.set_global_parameter("msw_restraint_scale", k)
    else:
        backend.set_global_parameter("msw_restraint_scale", spec.restraint_scale)


def _ramp_target(spec: StageSpec, frac: float) -> float:
    """Target temperature at local progress `frac`: linear ramp over the first `ramp_fraction`, then hold."""
    if spec.start_temperature_k is None:
        return spec.temperature_k
    r = max(1e-6, float(spec.ramp_fraction))
    return spec.start_temperature_k + (spec.temperature_k - spec.start_temperature_k) * min(1.0, frac / r)


THERMOSTAT_SETTLE_PS = 2.0     # no temperature judgement during the first picoseconds of a stage
THERMOSTAT_LAG_PS = 3.0        # a Langevin thermostat (γ ≈ 1/ps) trails a ramp by a few ps


def _watch(s: StateSummary, spec: StageSpec, frac: float, chunk_id: int) -> None:
    """Catch real blow-ups (NaN, runaway temperature) without false alarms during heating.

    Verified on a real OpenMM run (Windows, OpenCL): a 50→300 K ramp compressed into a
    few ps made the instantaneous target run ahead of the thermostat; the tolerance now
    includes the lag a thermostat physically needs to follow the ramp rate.
    """
    if not s.finite():
        raise WatchdogError(f"NaN/Inf 能量或座標（chunk {chunk_id}）")
    local_ps = frac * spec.length_ps
    if local_ps < THERMOSTAT_SETTLE_PS:
        return
    target = _ramp_target(spec, frac)
    tol = max(60.0, 0.25 * target)
    if spec.start_temperature_k is not None and spec.length_ps > 0:
        ramp_ps = max(1e-6, spec.ramp_fraction * spec.length_ps)
        rate = abs(spec.temperature_k - spec.start_temperature_k) / ramp_ps     # K per ps
        tol += THERMOSTAT_LAG_PS * rate
    if abs(s.temperature_k - target) > tol:
        raise WatchdogError(f"溫度失控：{s.temperature_k:.0f} K vs 目標 {target:.0f} K（容許 ±{tol:.0f} K，chunk {chunk_id}）")


def _concat_logs(paths: list[str], target: Path) -> None:
    header_written = False
    tmp = target.with_suffix(target.suffix + ".part")
    with open(tmp, "w", encoding="utf-8") as out:
        for p in paths:
            with open(p, "r", encoding="utf-8", errors="ignore") as inp:
                for line in inp:
                    if line.startswith("#"):
                        if header_written:
                            continue
                        header_written = True
                    out.write(line)
    tmp.replace(target)
