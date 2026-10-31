"""Run a whole protocol for one run directory: minimize → NVT → NPT → production.

Each stage: run (resumable) → acceptance → auto-extend (max twice) → figures.
`make_backend(spec, timestep_fs)` is injected so the same orchestration drives
OpenMM or the FakeBackend.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Callable

from ..util import atomic_write_json, load_json, now_iso, DecisionLog
from ..analysis import read_state_log, evaluate_acceptance, plot_stage_log, plot_minimization, plot_overview
from .protocol import Protocol, StageSpec
from .chunks import run_stage, NeedsHuman, Paused, StageResult


def _minimize(stage_dir: Path, spec: StageSpec, make_backend, *, identity: dict, decisions: DecisionLog | None) -> dict:
    """Staged minimization: restrained → half restraint → free (3 ladders), each with energy recorded."""
    stage_dir.mkdir(parents=True, exist_ok=True)
    complete = stage_dir / "minimize_complete.json"
    existing = load_json(complete, {})
    if existing.get("status") == "PASS" and all(existing.get(k) == v for k, v in identity.items()):
        return existing
    backend = make_backend(spec, spec.timestep_fs)
    try:
        backend.initialize(None, None, spec.seed, False)
        energies = [backend.summary().potential_kj_mol]
        ladder = [1.0, 0.5, 0.0] if backend.set_global_parameter("msw_restraint_scale", 1.0) else [None]
        for k in ladder:
            if k is not None:
                backend.set_global_parameter("msw_restraint_scale", k)
            backend.minimize(spec.tolerance_kj_mol_nm, spec.max_iterations)
            s = backend.summary()
            if not s.finite():
                raise NeedsHuman("最小化後能量為 NaN：起始結構有嚴重碰撞或配體參數錯誤；請回到 build 閘門檢查。", stage="minimize")
            energies.append(s.potential_kj_mol)
        backend.set_global_parameter("msw_restraint_scale", 1.0)
        state = stage_dir / "minimize_state.xml"
        backend.save_state(state)
        backend.write_pdb(stage_dir / "minimize_final.pdb")
        figs = plot_minimization(energies, stage_dir.parent.parent / "figures" / "minimize_energy")
        data = {**identity, "status": "PASS", "stage": "minimize", "energies_kj_mol": energies,
                "restraint_ladder": ladder, "state": str(state), "figures": figs, "sealed_at": now_iso(),
                "platform": getattr(backend, "platform_name", None), "backend_info": getattr(backend, "info", {})}
        atomic_write_json(data, complete)
        if decisions:
            decisions.record("engine.minimize", "restraint ladder", ladder,
                             "分三段最小化：先在完整位置約束下消除碰撞，再逐步釋放，避免配體被推出口袋。")
        return data
    finally:
        backend.close()


def run_protocol(run_dir: Path | str, protocol: Protocol, make_backend: Callable, *, identity: dict,
                 decisions: DecisionLog | None = None, progress_cb=None, max_extensions: int = 2,
                 write_dcd: bool = True, batch_steps: int | None = None, should_pause=None) -> dict:
    run_dir = Path(run_dir)
    stages_dir = run_dir / "stages"
    figures = run_dir / "figures"
    status = load_json(run_dir / "run.json", {})
    status.update({"status": "RUNNING", "protocol": protocol.to_dict(), "protocol_hash": protocol.hash(),
                   "started_at": status.get("started_at") or now_iso()})
    atomic_write_json(status, run_dir / "run.json")
    ident = {**identity, "protocol_hash": protocol.hash()}
    prev_state: Path | None = None
    frames = {}
    results: dict[str, dict] = {}
    try:
        for spec in protocol.stages:
            sdir = stages_dir / spec.name
            if spec.ensemble == "MIN":
                data = _minimize(sdir, spec, make_backend, identity=ident, decisions=decisions)
                prev_state = Path(data["state"])
                results[spec.name] = {"status": "PASS", "energies": data["energies_kj_mol"]}
                continue
            spec_run = spec
            for attempt in range(max_extensions + 1):
                res: StageResult = run_stage(sdir, spec_run, make_backend, identity=ident, initial_state=prev_state,
                                             decisions=decisions, write_dcd=write_dcd, progress_cb=progress_cb,
                                             batch_steps=batch_steps, should_pause=should_pause)
                df = read_state_log(res.log_path)
                frames[spec.name] = df
                acc = evaluate_acceptance(df, ensemble=spec.ensemble, target_temperature_k=spec.temperature_k,
                                          length_ps=spec_run.length_ps, **{k: v for k, v in spec.accept.items()
                                                                             if k in {"temp_tol_k", "density_cv", "last_fraction"}})
                figs = plot_stage_log(df, figures / f"{spec.name}_timeseries", title=f"{spec.name.upper()} — {res.steps:,} steps",
                                      target_temperature_k=spec.temperature_k, ensemble=spec.ensemble,
                                      accept_window_fraction=spec.accept.get("last_fraction"))
                comp = load_json(sdir / f"{spec.name}_complete.json", {})
                comp.update({"acceptance": dataclasses.asdict(acc), "figures": figs})
                atomic_write_json(comp, sdir / f"{spec.name}_complete.json")
                if acc.ok or spec.name == "production":
                    if not acc.ok and decisions:
                        decisions.record(f"engine.{spec.name}", "acceptance", acc.status,
                                         "Production 不自動延長；末段統計未達標會在報告中標示，由使用者判斷。", kind="auto")
                    break
                if attempt == max_extensions:
                    comp["status"] = "NEEDS_HUMAN"
                    atomic_write_json(comp, sdir / f"{spec.name}_complete.json")
                    raise NeedsHuman(f"{spec.name} 延長 {max_extensions} 次後仍未通過驗收：{acc.recommendation}",
                                     stage=spec.name, evidence={"checks": acc.checks})
                # extend: a *new* spec with longer length continues the same chunk sequence
                spec_run = dataclasses.replace(spec_run, length_ps=spec_run.length_ps + acc.extend_ps)
                (sdir / f"{spec.name}_complete.json").unlink(missing_ok=True)
                if decisions:
                    decisions.record(f"engine.{spec.name}", "auto-extend", f"+{acc.extend_ps} ps",
                                     acc.recommendation, kind="auto_fixed", attempt=attempt + 1, checks=acc.checks)
            prev_state = Path(res.state_path)
            results[spec.name] = {"status": acc.status, "checks": acc.checks, "elapsed_s": res.elapsed_s,
                                  "chunks": res.chunks, "watchdog_events": len(res.watchdog_events)}
        if frames:
            results["overview_figure"] = plot_overview(frames, figures / "run_overview")
        status.update({"status": "COMPLETE", "results": results, "finished_at": now_iso()})
        atomic_write_json(status, run_dir / "run.json")
        return status
    except Paused as exc:
        status.update({"status": "PAUSED", "results": results, "reason": str(exc), "stage": exc.stage,
                       "updated_at": now_iso()})
        atomic_write_json(status, run_dir / "run.json")
        raise
    except NeedsHuman as exc:
        status.update({"status": "NEEDS_HUMAN", "results": results, "error": str(exc), "stage": exc.stage,
                       "evidence": exc.evidence, "updated_at": now_iso()})
        atomic_write_json(status, run_dir / "run.json")
        raise
    except BaseException as exc:  # noqa: BLE001 - keep file truth even on Ctrl-C
        status.update({"status": "INTERRUPTED", "results": results, "error": f"{type(exc).__name__}: {exc}",
                       "updated_at": now_iso()})
        atomic_write_json(status, run_dir / "run.json")
        raise
