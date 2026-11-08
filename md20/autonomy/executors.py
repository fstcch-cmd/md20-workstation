"""D-143: executors — the existing workflow operations wrapped as callables for `Controller(executor=...)`.

Nothing here starts by itself.  An executor is called only after `Ledger.claim()` has durably recorded the launch (the controller
guarantees that), so a duplicate proposal, a second worker or a GUI reconnect cannot start it twice.  Each executor returns an
`ExecutionResult` whose `resources` are MEASURED use (wall seconds, GPU hours, CPU-core hours = CPU seconds of this process,
disk growth) and whose `simulated_ps` is simulated time read back from the files it produced, kept apart from cost.

| action | what is called (public API only) |
|---|---|
| reanalysis, binding variant   | `sampling.reassess.reassess_workflow`  (stored PMF fields, no sampling) |
| reanalysis, trajectory variant| `Workflow.analyse`  (analysis only, MD is never rerun) |
| add_independent_replica       | `md.replicas` +1 in config.json, then `Workflow.run_md` (the D-131 top-up) and `Workflow.analyse` |
| refine_approved_umbrella_windows | `binding.manual_windows` + `Workflow.binding` → `run_binding` resumes with the extra windows |
| extend_approved_run           | `engine.chunks.run_stage` on the run's production stage, the same mechanism as the engine's own auto-extension |

Honest limits: GPU/CPU hours are wall time × one device / process CPU time, not a hardware meter; extending an umbrella WINDOW
(rather than the MD production run) has no public API in `sampling/binding.py`, so such proposals do not start (`preflight`).
"""
from __future__ import annotations

import copy
import dataclasses
import os
import time
from pathlib import Path
from typing import Callable

from ..util import atomic_write_json, load_json, now_iso
from .controller import ExecutionRequest, ExecutionResult
from .model import ACTION_EXTEND, ACTION_REANALYSIS, ACTION_REFINE, ACTION_REPLICA, ActionProposal

WHAT_BINDING = "stored window samples"
WHAT_TRAJECTORY = "trajectory analysis"
GB = 1e9
GPU_PLATFORMS = ("CUDA", "OpenCL", "HIP", "Metal")


# ------------------------------------------------------------------------------------------------ measurement
def dir_bytes(*paths: Path | str) -> int:
    total = 0
    for p in paths:
        p = Path(p)
        if p.is_file():
            total += p.stat().st_size
        elif p.is_dir():
            for f in p.rglob("*"):
                try:
                    if f.is_file():
                        total += f.stat().st_size
                except OSError:
                    pass
    return total


class Meter:
    """Measured use of one executor call.  `gpu_hours` = wall hours when the platform is a GPU, else 0.0; `core_hours` = CPU
    seconds consumed by this process (all its threads) / 3600; `storage_gb` = growth of the watched directories."""

    def __init__(self, platform=None, watch: tuple = ()):
        self.gpu = getattr(platform, "name", None) in GPU_PLATFORMS if platform is not None else False
        self.watch = [Path(w) for w in watch]
        self.t0, self.c0, self.b0 = time.monotonic(), time.process_time(), dir_bytes(*self.watch)

    def resources(self, *, uses_gpu: bool | None = None) -> dict:
        wall = time.monotonic() - self.t0
        gpu = self.gpu if uses_gpu is None else bool(uses_gpu and self.gpu)
        return {"wall_s": round(wall, 3), "gpu_hours": round(wall / 3600.0, 6) if gpu else 0.0,
                "core_hours": round((time.process_time() - self.c0) / 3600.0, 6),
                "storage_gb": round(max(0, dir_bytes(*self.watch) - self.b0) / GB, 6)}


def stage_ps(run_dir: Path | str) -> float:
    """Simulated ps stored in a run's sealed stages (steps × time step), from `<stage>_complete.json`."""
    ps = 0.0
    for stage in ("nvt", "npt", "production"):
        c = load_json(Path(run_dir) / "stages" / stage / f"{stage}_complete.json", {}) or {}
        steps, dt = (c.get("result") or {}).get("steps"), c.get("timestep_fs")
        if isinstance(steps, (int, float)) and isinstance(dt, (int, float)):
            ps += steps * dt / 1000.0
    return ps


def window_ps(wf_dir: Path, target: str) -> float:
    """Simulated ps in the umbrella windows of one target (production samples + the equilibration each window ran)."""
    import numpy as np
    from ..sampling.reassess import replica_manifests
    ps = 0.0
    for p in replica_manifests(wf_dir, target):
        cfg = (load_json(p, {}) or {}).get("config") or {}
        every, dt, eq = int(cfg.get("sample_every_steps") or 50), float(cfg.get("timestep_fs") or 2.0), float(cfg.get("window_equil_ps") or 0)
        for f in (p.parent / "windows").glob("w_*_cv.npy"):
            try:
                ps += len(np.load(f, mmap_mode="r")) * every * dt / 1000.0 + eq
            except (OSError, ValueError):
                pass
    return ps


# ------------------------------------------------------------------------------------------------ helpers
def _busy(wf_dir: Path) -> str | None:
    """Why this workflow cannot be touched now: another live MD20 process owns it (the same marker `Workflow.run` uses)."""
    import socket
    from ..util.locks import OwnerLock
    cur = load_json(wf_dir / "running.json", {}) or {}
    if cur.get("pid") and cur.get("pid") != os.getpid() and cur.get("host") == socket.gethostname() and OwnerLock._alive(cur["pid"]):
        return f"另一個 MD20 程序（PID {cur['pid']}）正在執行這個工作流程，等它結束或暫停後再啟動。"
    return None


def _licence_problem(feature_cfg: dict | None) -> str | None:
    try:
        from ..util.license import require, require_features
        from ..workflow import required_features
        require("workflow")
        require_features("workflow", required_features(feature_cfg or {}))
    except Exception as exc:  # noqa: BLE001 - LicenseRequired / FeatureNotLicensed; say why, never start
        texts = getattr(exc, "texts", None)
        return (texts()[0] if callable(texts) else str(exc))[:300]
    return None


def _failed(msg: str, *, kind: str, meter: Meter | None = None, **kw) -> ExecutionResult:
    return ExecutionResult(status="failed", error=msg, error_kind=kind, resources=(meter.resources() if meter else {}), **kw)


def _run_dir(wf, run_id: str) -> tuple[Path | None, str | None, str | None]:
    """(run directory, case id, system key) of a run id, from the workflow's md_runs record."""
    runs = ((wf.state().get("steps") or {}).get("md_runs") or {}).get("runs") or {}
    for key, r in runs.items():
        if run_id in (r.get("run_ids") or []):
            return wf.project.dir / "cases" / r["case_id"] / "runs" / run_id, r["case_id"], key
    return None, None, None


class WorkflowExecutors:
    """`Controller(executor=WorkflowExecutors(wf, make_factory, platform), preflight=ex.preflight, reassessor=ex.reassessor)`.

    wf: a `Workflow`.  make_factory(case, protocol) → backend factory (as `Workflow.run` takes).  platform: the OpenMM platform
    choice (only its name and properties are read, for the cost report).  Tests inject fakes for both."""

    def __init__(self, wf, make_factory: Callable | None = None, platform=None, *, should_pause: Callable | None = None,
                 progress_cb: Callable | None = None, check_licence: bool = True):
        self.wf, self.make_factory, self.platform = wf, make_factory, platform
        self.should_pause, self.progress_cb, self.check_licence = should_pause, progress_cb, check_licence

    # ---- can it start at all (called BEFORE claim: costs nothing, consumes no attempt)
    def preflight(self, p: ActionProposal) -> tuple[bool, str]:
        a, t = p.action_type, p.target or {}
        if a == ACTION_REANALYSIS:
            return True, ""
        if _busy(self.wf.dir):
            return False, _busy(self.wf.dir) or ""
        if self.make_factory is None and a in (ACTION_REPLICA, ACTION_EXTEND):
            return False, "沒有提供運算後端（make_factory），無法啟動模擬。"
        if self.platform is None and a == ACTION_REFINE:
            return False, "沒有提供運算平台，無法啟動傘狀採樣。"
        if self.check_licence and (why := _licence_problem(self.wf.cfg)):
            return False, f"授權不允許真實計算：{why}"
        if a == ACTION_EXTEND and t.get("window_centres"):
            return False, ("延長傘狀採樣的窗口沒有公開的執行介面（sampling/binding.py 只在補窗輪內部延長）；"
                           "這個行動不會自動啟動，請在覆蓋圖上手動補採樣或由使用者決定。")
        if a == ACTION_EXTEND and not (t.get("extend_ps") and float(t["extend_ps"]) > 0):
            return False, "延長的長度沒有由使用者指定（--extend-ps），不使用預設值。"
        if a == ACTION_REFINE and not t.get("binding_target"):
            return False, "提案沒有指明結合目標。"
        if a == ACTION_REPLICA:
            from ..engine.replica_plan import configured_replicas
            done = self.wf.completed_replicas()
            if not done:
                return False, "找不到已完成 MD 的系統，無法補重複。"
            have = min(done.values())
            n, _ = configured_replicas(self.wf.cfg)
            if n > have + 1:
                return False, f"設定已要求 {n} 條重複而目前只有 {have} 條，請用一般流程補齊；自主行動一次只補一條。"
        return True, ""

    # ---- dispatch
    def __call__(self, req: ExecutionRequest) -> ExecutionResult:
        p = ActionProposal.from_dict(req.proposal)
        fn = {ACTION_REANALYSIS: self._reanalysis, ACTION_REPLICA: self._add_replica, ACTION_REFINE: self._refine,
              ACTION_EXTEND: self._extend}.get(p.action_type)
        if fn is None:
            return _failed(f"不支援的行動：{p.action_type}", kind="unexpected")
        return fn(p, req)

    def _pause(self, req: ExecutionRequest) -> Callable[[], str | None]:
        def pause():
            if req.cancelled():
                return "autonomy:cancelled"
            return self.should_pause() if self.should_pause else None
        return pause

    def _state_runs(self) -> tuple[dict, dict]:
        st = self.wf.state().get("steps") or {}
        return dict((st.get("md_runs") or {}).get("runs") or {}), dict((st.get("md_cases") or {}).get("cases") or {})

    def _outcome_of_pause(self, req, meter, exc_reason: str, **kw) -> ExecutionResult:
        if req.cancelled():
            return ExecutionResult(status="cancelled", error=str(exc_reason), resources=meter.resources(), **kw)
        return _failed(f"被暫停：{exc_reason}", kind="paused", meter=meter, **kw)

    # ---- reanalysis ------------------------------------------------------------------------------
    def _reanalysis(self, p: ActionProposal, req: ExecutionRequest) -> ExecutionResult:
        t = p.target or {}
        wf = self.wf
        meter = Meter(None, (wf.dir,))
        try:
            if t.get("what") == WHAT_TRAJECTORY:
                runs, _ = self._state_runs()
                if not runs:
                    return _failed("工作流程沒有已完成的 MD 可重新分析。", kind="scientific", meter=meter)
                # all systems, not only the affected one: Workflow.analyse overwrites `steps.analysis`, and the comparison needs
                # every system.  Systems whose analysis fingerprint is unchanged are reused, so only the affected one is computed.
                wf.analyse(runs)
                out = {"variant": "trajectory", "system": t.get("system_key")}
            else:
                from ..sampling.reassess import reassess_workflow
                target = t.get("binding_target")
                if not target:
                    return _failed("提案沒有指明結合目標。", kind="scientific", meter=meter)
                rep = reassess_workflow(wf.dir, targets=[target], include_outdated=True, wf=wf, kind="auto")
                out = {"variant": "binding", "report": rep["targets"].get(target), "backups": rep.get("state_backup")}
                if (rep["targets"].get(target) or {}).get("status") == "error":
                    return _failed(rep["targets"][target]["why"], kind="scientific", meter=meter, outputs=out)
        except Exception as exc:  # noqa: BLE001 - reported as a failure of this attempt, never retried unless technical
            return _failed(f"{type(exc).__name__}: {exc}", kind="unexpected", meter=meter)
        return ExecutionResult(status="ok", resources=meter.resources(uses_gpu=False), simulated_ps=0.0, outputs=out)

    # ---- add_independent_replica -----------------------------------------------------------------
    def _add_replica(self, p: ActionProposal, req: ExecutionRequest) -> ExecutionResult:
        from ..workflow import WorkflowBlocked
        from ..util.locks import OwnerLock
        wf = self.wf
        runs0, built = self._state_runs()
        meter = Meter(self.platform, (wf.project.dir / "cases",))
        lock = OwnerLock(wf.dir / "running.json")
        try:
            lock.acquire()
        except RuntimeError as exc:
            return _failed(str(exc), kind="busy", meter=meter, simulated_ps=0.0)
        before = {rid for r in runs0.values() for rid in r.get("run_ids") or []}
        try:
            done = wf.completed_replicas()
            have = min(done.values()) if done else 0
            cfg = copy.deepcopy(load_json(wf.dir / "config.json", wf.cfg))
            want = have + 1
            cfg.setdefault("md", {})["replicas"] = want
            atomic_write_json(cfg, wf.dir / "config.json")
            wf.cfg = cfg
            st = wf.state()
            dropped = [k for k in ("analysis", "report") if st["steps"].pop(k, None) is not None]
            atomic_write_json(st, wf.state_path)
            wf.dec.record("autonomy.replicas", "replicas", want,
                          f"自主行動（帳本 {req.key[:12]}）依使用者核准的政策，把每個系統的獨立重複由 {have} 條補到 {want} 條；"
                          f"已完成的不重算，只跑缺的；分析與報告需要重做（{', '.join(dropped) or '無已完成步驟'}）。",
                          kind="auto", previous=have, key=req.key)
            runs = wf.run_md(built, self.make_factory, should_pause=self._pause(req), progress_cb=self.progress_cb)
            if any(r.get("status") == "PAUSED" for r in runs.values()):
                return self._outcome_of_pause(req, meter, "MD 暫停", simulated_ps=self._new_ps(before))
            wf.analyse(runs)
        except WorkflowBlocked as exc:
            return _failed(f"需要人工決定：{exc}", kind="needs_human", meter=meter, simulated_ps=self._new_ps(before))
        except Exception as exc:  # noqa: BLE001
            return _failed(f"{type(exc).__name__}: {exc}", kind="unexpected", meter=meter, simulated_ps=self._new_ps(before))
        finally:
            lock.release()
        return ExecutionResult(status="ok", resources=meter.resources(), simulated_ps=self._new_ps(before),
                               outputs={"replicas": want})

    def _new_ps(self, before: set) -> float:
        runs, _ = self._state_runs()
        ps = 0.0
        for r in runs.values():
            for rid in r.get("run_ids") or []:
                if rid not in before:
                    ps += stage_ps(self.wf.project.dir / "cases" / r["case_id"] / "runs" / rid)
        return ps

    # ---- refine_approved_umbrella_windows --------------------------------------------------------
    def _refine(self, p: ActionProposal, req: ExecutionRequest) -> ExecutionResult:
        from ..workflow import WorkflowBlocked
        from ..util.locks import OwnerLock
        wf, t = self.wf, p.target
        target = t["binding_target"]
        runs, built = self._state_runs()
        meter = Meter(self.platform, (wf.dir / "binding",))
        ps0 = window_ps(wf.dir, target)
        lock = OwnerLock(wf.dir / "running.json")
        try:
            lock.acquire()
        except RuntimeError as exc:
            return _failed(str(exc), kind="busy", meter=meter, simulated_ps=0.0)
        try:
            cfg = copy.deepcopy(load_json(wf.dir / "config.json", wf.cfg))
            mw = cfg.setdefault("binding", {}).setdefault("manual_windows", {}).setdefault(target, [])
            have = {round(float(w["center"]), 4) for w in mw}
            ks = t.get("k") or {}
            new = [{"center": float(c), "k": float(ks.get(f"{float(c):.4f}", 0) or 0) or None} for c in t.get("insert_centres") or []
                   if round(float(c), 4) not in have]
            if not new:
                return ExecutionResult(status="ok", resources=meter.resources(), simulated_ps=0.0,
                                       outputs={"note": "這些窗口已在 manual_windows 中，沒有新增。"})
            mw.extend(new)
            atomic_write_json(cfg, wf.dir / "config.json")
            wf.cfg = cfg
            st = wf.state()
            b = st["steps"].get("binding")
            if b:
                (b.get("results") or {}).pop(target, None)
                b["status"] = "PENDING"
            st["steps"].pop("report", None)
            atomic_write_json(st, wf.state_path)
            wf.dec.record("autonomy.umbrella", target, f"refine +{len(new)} windows",
                          f"自主行動（帳本 {req.key[:12]}）依使用者核准的政策，為 {target} 補 {len(new)} 個傘狀採樣窗口"
                          f"（{', '.join('%.3f' % w['center'] for w in new)} nm）；已完成的窗口沿用，其餘結合目標不重算。",
                          kind="auto", windows=new, key=req.key)
            res = wf.binding(runs, built, self.platform, should_pause=self._pause(req), progress_cb=self.progress_cb)
            if (res.get(target) or {}).get("status") == "PAUSED":
                return self._outcome_of_pause(req, meter, "傘狀採樣暫停", simulated_ps=window_ps(wf.dir, target) - ps0)
            self._refresh_report()
        except WorkflowBlocked as exc:
            return _failed(f"需要人工決定：{exc}", kind="needs_human", meter=meter, simulated_ps=max(0.0, window_ps(wf.dir, target) - ps0))
        except Exception as exc:  # noqa: BLE001
            return _failed(f"{type(exc).__name__}: {exc}", kind="unexpected", meter=meter, simulated_ps=max(0.0, window_ps(wf.dir, target) - ps0))
        finally:
            lock.release()
        return ExecutionResult(status="ok", resources=meter.resources(), simulated_ps=max(0.0, window_ps(wf.dir, target) - ps0),
                               outputs={"windows": new})

    def _refresh_report(self) -> None:
        try:
            from ..gui.actions import refresh_report
            refresh_report(self.wf)
        except Exception:  # noqa: BLE001 - the report is a convenience; the state already holds the new result
            pass

    # ---- extend_approved_run ---------------------------------------------------------------------
    def _extend(self, p: ActionProposal, req: ExecutionRequest) -> ExecutionResult:
        from ..engine.chunks import NeedsHuman, Paused, run_stage
        from ..engine.protocol import Protocol
        from ..engine.runner import checkpoint_fingerprint
        from ..util.locks import OwnerLock
        wf, t = self.wf, p.target
        run_dir, case_id, _key = _run_dir(wf, str(t.get("run_id")))
        meter = Meter(self.platform, (run_dir,) if run_dir else ())
        if run_dir is None:
            return _failed("找不到這個 run。", kind="scientific", meter=meter)
        rj = load_json(run_dir / "run.json", {}) or {}
        want_hash = (p.inputs or {}).get("protocol_hash")
        if rj.get("status") != "COMPLETE" or (want_hash and rj.get("protocol_hash") != want_hash):
            return _failed("run 的狀態或協定雜湊與提案時不同（證據已改變），不延長。", kind="scientific", meter=meter)
        if len(rj.get("extensions") or []) != int((p.inputs or {}).get("extensions_done") or 0):
            return _failed("run 的延長次數與提案時不同（證據已改變），不延長。", kind="scientific", meter=meter)
        extra = float(t["extend_ps"])
        proto = Protocol.from_dict(rj["protocol"])
        spec = proto.stage("production")
        cur_ps = float(rj.get("effective_production_ps") or spec.length_ps)
        lock = OwnerLock(wf.dir / "running.json")
        try:
            lock.acquire()
        except RuntimeError as exc:
            return _failed(str(exc), kind="busy", meter=meter, simulated_ps=0.0)
        sdir = run_dir / "stages" / "production"
        started = now_iso()
        steps_before = (load_json(sdir / "production_progress.json", {}) or {}).get("completed_local_steps") or 0
        try:
            case = wf.project.case(case_id)
            new_spec = dataclasses.replace(spec, length_ps=cur_ps + extra, schedule_length_ps=spec.schedule_length_ps or spec.length_ps)
            factory = self.make_factory(case, proto)
            rj.update({"status": "EXTENDING", "extension_in_progress": {"at": started, "extra_ps": extra, "key": req.key}})
            atomic_write_json(rj, run_dir / "run.json")
            comp = sdir / "production_complete.json"
            if comp.is_file():
                import shutil
                shutil.copy2(comp, comp.with_name(f"production_complete.json.pre-extend-{started.replace(':', '').replace('-', '')}"))
                comp.unlink()
            ident = {"case_id": case.case_id, "run_id": run_dir.name, "project_uuid": case.project.uuid, "protocol_hash": rj["protocol_hash"]}
            npt = run_dir / "stages" / "npt" / "npt_state.xml"
            run_stage(sdir, new_spec, factory, identity=ident, initial_state=npt if npt.is_file() else None, decisions=wf.dec,
                      progress_cb=self.progress_cb, should_pause=self._pause(req))
            rj = load_json(run_dir / "run.json", {}) or rj
            rj.pop("extension_in_progress", None)
            ext = list(rj.get("extensions") or [])
            ext.append({"at": now_iso(), "extra_ps": extra, "from_ps": cur_ps, "to_ps": cur_ps + extra, "key": req.key,
                        "note": "run.json['protocol'] keeps the originally approved length; the files hold the extended trajectory"})
            rj.update({"status": "COMPLETE", "extensions": ext, "effective_production_ps": cur_ps + extra,
                       "checkpoint_fingerprint": checkpoint_fingerprint(run_dir)})
            atomic_write_json(rj, run_dir / "run.json")
            wf.dec.record("autonomy.extend", run_dir.name, f"+{extra:g} ps",
                          f"自主行動（帳本 {req.key[:12]}）依使用者核准的政策，把已核准的正式模擬 {run_dir.name} 由 {cur_ps:g} ps 延長到 "
                          f"{cur_ps + extra:g} ps（同一個協定、同一組種子，從驗證過的檢查點接續）；取樣量變大，比較時要註明。",
                          kind="auto", key=req.key, extra_ps=extra)
            st = wf.state()
            for k in ("analysis", "report"):
                st["steps"].pop(k, None)
            atomic_write_json(st, wf.state_path)
            runs, _ = self._state_runs()
            wf.analyse(runs)
        except Paused as exc:
            rj = load_json(run_dir / "run.json", {}) or rj
            return self._outcome_of_pause(req, meter, str(exc), simulated_ps=extra)
        except NeedsHuman as exc:
            return _failed(f"需要人工決定：{exc}", kind="needs_human", meter=meter)
        except Exception as exc:  # noqa: BLE001
            return _failed(f"{type(exc).__name__}: {exc}", kind="unexpected", meter=meter)
        finally:
            lock.release()
        done_steps = (load_json(sdir / "production_progress.json", {}) or {}).get("completed_local_steps") or 0
        sim = max(0.0, (done_steps - steps_before) * spec.timestep_fs / 1000.0)
        return ExecutionResult(status="ok", resources=meter.resources(), simulated_ps=sim,
                               outputs={"run_id": run_dir.name, "extended_to_ps": cur_ps + extra})

    # ---- the post-action assessment ----------------------------------------------------------------
    def reassessor(self, proposal: dict, result: ExecutionResult) -> dict | None:
        """The stored assessment of the proposal's binding target after the action (None → the controller stops: unreadable)."""
        target = (proposal.get("target") or {}).get("binding_target")
        res = ((((load_json(self.wf.dir / "state.json", {}) or {}).get("steps") or {}).get("binding") or {}).get("results") or {}).get(target or "")
        if not isinstance(res, dict):
            return None
        a = res.get("assessment")
        if a:
            return a
        from ..sampling.assessment import resolve_assessment
        from .inputs import _replica_pmf
        pm = _replica_pmf(self.wf.dir, target)
        return resolve_assessment(res, (pm or {}).get("pmf"))[0]
