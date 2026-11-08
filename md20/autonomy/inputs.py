"""D-143: the controller's inputs, read from the files of one workflow (file truth, no Workflow object, writes nothing).

`inputs_for_workflow(wf_dir)` returns one `AssessmentInputs` per finished binding target:

* **assessment**  the stored one of `steps.binding.results[target]`; a result without one (written before D-96) is resolved
  by `sampling.assessment.resolve_assessment` from its stored PMF fields, which shows the diagnostics but keeps the result
  not eligible, so the rules propose a re-assessment (`sampling/reassess.py`).
* **costs**  speed (`ns_per_day`) from the doctor benchmark record of this computer and storage (`gb_per_ns`) from the frame
  size of the production trajectory, as `engine/longrun.py` estimates it.  A missing source stays missing (the estimate is
  unknown and the policy asks a person), never a default.
* **approved_run**  the MD run the target's first pull started from, with the checkpoint fingerprint `run.json` recorded when
  the run finished.  A run that finished before fingerprints were recorded is marked `legacy_run`: extending it escalates.
* **replicas**  attached to the first target only (replicas belong to the workflow, not to a pull).
"""
from __future__ import annotations

from pathlib import Path

from ..util import load_json
from .rules import AssessmentInputs

DOCTOR_FILE = ("doctor", "doctor_report.json")
GPU_PLATFORMS = ("CUDA", "OpenCL", "HIP", "Metal")


# ------------------------------------------------------------------------------------------------ doctor benchmark
def doctor_benchmark(path: Path | str | None = None) -> dict | None:
    """The benchmark of the last `md20 doctor` run on this computer (`app_data_dir()/doctor/doctor_report.json`), or None.
    Returns the record as saved (`ns_per_day`, `n_atoms`, `timestep_fs`, `platform`) plus `recorded_at`."""
    if path is None:
        from ..util.paths import app_data_dir
        path = app_data_dir().joinpath(*DOCTOR_FILE)
    rep = load_json(Path(path), {}) or {}
    b = rep.get("benchmark")
    if not isinstance(b, dict) or not isinstance(b.get("ns_per_day"), (int, float)) or b["ns_per_day"] <= 0:
        return None
    return {**b, "recorded_at": rep.get("created_at")}


def device_kind(bench: dict | None) -> str | None:
    p = (bench or {}).get("platform")
    if not isinstance(p, str):
        return None
    return "gpu" if p in GPU_PLATFORMS else "cpu"


# ------------------------------------------------------------------------------------------------ storage and speed
def storage_gb_per_ns(n_atoms: int | None, trajectory_interval_ps: float | None, *, unit_cell: bool = True) -> float | None:
    """Trajectory disk per simulated ns: frames per ns × the DCD frame size of `engine.longrun.dcd_frame_bytes`.  Unknown
    without the atom count or the frame interval."""
    if not n_atoms or not trajectory_interval_ps or trajectory_interval_ps <= 0:
        return None
    from ..engine.longrun import dcd_frame_bytes, GB
    return round((1000.0 / float(trajectory_interval_ps)) * dcd_frame_bytes(int(n_atoms), unit_cell) / GB, 6)


def scaled_speed(bench: dict | None, n_atoms: int | None, timestep_fs: float | None) -> tuple[float | None, str]:
    """(ns/day for this system, basis).  Scaled by atoms and time step as everywhere else (`engine.longrun.scaled_ns_per_day`);
    without the system size the benchmark is used as it is and labelled so."""
    if not bench:
        return None, "no doctor benchmark on this computer"
    from ..engine.longrun import scaled_ns_per_day
    if n_atoms and timestep_fs:
        v = scaled_ns_per_day(bench, int(n_atoms), float(timestep_fs))
        if v:
            return round(v, 3), f"doctor benchmark scaled to {int(n_atoms)} atoms"
    return float(bench["ns_per_day"]), "doctor benchmark as measured (system size unknown)"


# ------------------------------------------------------------------------------------------------ one workflow
def _case_dir(project_dir: Path, case_id: str) -> Path:
    return project_dir / "cases" / case_id


def _n_atoms(case_dir: Path) -> int | None:
    bm = load_json(case_dir / "build" / "build_manifest.json", {}) or {}
    n = (bm.get("assembly") or {}).get("n_atoms") or bm.get("n_atoms")
    return int(n) if isinstance(n, (int, float)) and n > 0 else None


def _production_stage(run_json: dict) -> dict:
    for s in (run_json.get("protocol") or {}).get("stages") or []:
        if isinstance(s, dict) and s.get("name") == "production":
            return s
    return {}


def _replica_pmf(wf_dir: Path, name: str) -> dict | None:
    from ..sampling.reassess import replica_manifests
    for p in replica_manifests(wf_dir, name):
        r = (load_json(p, {}) or {}).get("result") or {}
        if r.get("pmf"):
            return {"pmf": r["pmf"], "result": r}
    return None


def _samples_on_disk(wf_dir: Path, name: str) -> bool:
    from ..sampling.reassess import replica_manifests
    ps = replica_manifests(wf_dir, name)
    return bool(ps) and all(any((p.parent / "windows").glob("w_*_cv.npy")) for p in ps)


def cost_inputs(wf_dir: Path | str, *, bench: dict | None = ..., target: str | None = None) -> dict:
    """The `costs` dict of `AssessmentInputs`, from recorded files only.  `bench=...` (default) reads this computer's doctor
    record; pass None to say there is none."""
    from ..engine.replica_plan import md_ns_per_replica, count_systems
    wf_dir = Path(wf_dir)
    project_dir = wf_dir.parent.parent
    cfg = load_json(wf_dir / "config.json", {}) or {}
    st = (load_json(wf_dir / "state.json", {"steps": {}}) or {}).get("steps") or {}
    if bench is ...:
        bench = doctor_benchmark()
    cases = (st.get("md_cases") or {}).get("cases") or {}
    runs = (st.get("md_runs") or {}).get("runs") or {}
    atoms = [a for a in (_n_atoms(_case_dir(project_dir, c["case_id"])) for c in cases.values() if c.get("case_id")) if a]
    n_atoms = max(atoms) if atoms else None
    # a finished run's own protocol says how often frames were written (file truth); the config's protocol is the fallback
    traj_ps, dt = None, None
    for key, r in runs.items():
        cid = (r or {}).get("case_id")
        for rid in (r or {}).get("run_ids") or []:
            rj = load_json(_case_dir(project_dir, cid) / "runs" / rid / "run.json", {}) or {} if cid else {}
            s = _production_stage(rj)
            if s.get("trajectory_interval_ps"):
                traj_ps, dt = float(s["trajectory_interval_ps"]), float(s.get("timestep_fs") or 0) or None
                break
        if traj_ps:
            break
    speed, speed_basis = scaled_speed(bench, n_atoms, dt or (bench or {}).get("timestep_fs"))
    # a re-assessment from stored fields runs no simulation and only reads and copies a few JSON files: negligible, estimated
    # as zero; the ledger charges what the executor then MEASURES (CPU seconds, disk growth), so nothing escapes the budget
    costs: dict = {"reanalysis_core_hours": 0.0, "reanalysis_storage_gb": 0.0}
    notes = ["re-assessment from stored fields estimated as negligible, measured when run"]
    if speed is not None:
        costs["ns_per_day"] = speed
        notes.append(f"ns/day {speed} ({speed_basis}, recorded {bench.get('recorded_at') or 'unknown'})")
    kind = device_kind(bench)
    if kind:
        costs["device"] = kind
        if kind == "cpu":
            import os
            costs["cpu_threads"] = os.cpu_count() or None
    gpn = storage_gb_per_ns(n_atoms, traj_ps)
    if gpn is not None:
        costs["gb_per_ns"] = gpn
        notes.append(f"{gpn} GB/ns (frame every {traj_ps:g} ps, {n_atoms} atoms)")
    try:
        ns_rep, _ = md_ns_per_replica(cfg)
        systems = count_systems(cfg, list(cases) or None)
        costs["replica_ns"] = round(ns_rep * systems, 6)          # a replica of EVERY system: the workflow's replica count is global
        costs["replica_systems"] = systems
    except Exception:  # noqa: BLE001 - an unreadable config means an unknown estimate
        pass
    if target:
        man = _replica_pmf_config(wf_dir, target)
        for k in ("window_equil_ps", "window_prod_ps"):
            if man.get(k) is not None:
                costs[k] = float(man[k])
        from ..sampling.reassess import replica_manifests
        costs["binding_replicas"] = max(1, len(replica_manifests(wf_dir, target)))
    if notes:
        costs["basis_note"] = "; ".join(notes)
    return costs


def _replica_pmf_config(wf_dir: Path, name: str) -> dict:
    from ..sampling.reassess import replica_manifests
    for p in replica_manifests(wf_dir, name):
        c = (load_json(p, {}) or {}).get("config")
        if isinstance(c, dict):
            return c
    return {}


def approved_run_for(wf_dir: Path | str, target: str, *, extend_ps: float | None = None, max_extensions: int = 2) -> dict | None:
    """The MD run a target's first pull started from, as `approved_run` for the rules; None when it cannot be found.
    `extend_ps` is chosen by a person (None = not chosen: the extension proposal is blocked)."""
    wf_dir = Path(wf_dir)
    project_dir = wf_dir.parent.parent
    res = (((load_json(wf_dir / "state.json", {}) or {}).get("steps") or {}).get("binding") or {}).get("results") or {}
    steps = (load_json(wf_dir / "state.json", {}) or {}).get("steps") or {}
    runs = (steps.get("md_runs") or {}).get("runs") or {}
    src = ((res.get(target) or {}).get("replica_sources") or [])
    rid = (src[0] or {}).get("md_run_id") if src else None
    cid = None
    for r in runs.values():
        if rid and rid in (r.get("run_ids") or []):
            cid = r.get("case_id")
    if not (rid and cid):
        return None
    run_dir = _case_dir(project_dir, cid) / "runs" / rid
    rj = load_json(run_dir / "run.json", {}) or {}
    if rj.get("status") != "COMPLETE":
        return None
    state = run_dir / "stages" / "production" / "production_state.xml"
    fp = rj.get("checkpoint_fingerprint")
    cp = {"path": str(state), "fingerprint": fp if isinstance(fp, dict) else None}
    if not isinstance(fp, dict):
        cp["legacy_run"] = True
    return {"run_id": rid, "case_id": cid, "protocol_hash": rj.get("protocol_hash"), "checkpoint": cp,
            "extensions_done": len(rj.get("extensions") or []), "max_extensions": int(max_extensions), "extend_ps": extend_ps}


def inputs_for_workflow(wf_dir: Path | str, *, extend_ps: float | None = None, bench: dict | None = ...,
                        targets: list[str] | None = None) -> list[AssessmentInputs]:
    """One `AssessmentInputs` per finished binding target (see the module doc).  Empty when the workflow has no finished
    binding result: the autonomy loop reads umbrella-sampling assessments, so there is nothing to propose without one."""
    from ..sampling.assessment import resolve_assessment
    from ..engine.replica_plan import required_replicas
    wf_dir = Path(wf_dir)
    state = load_json(wf_dir / "state.json", {"steps": {}}) or {}
    results = ((state.get("steps") or {}).get("binding") or {}).get("results") or {}
    name = wf_dir.name
    out: list[AssessmentInputs] = []
    first = True
    for tkey in sorted(results):
        res = results[tkey]
        if not isinstance(res, dict) or res.get("status") != "PASS" or (targets and tkey not in targets):
            continue
        pm = _replica_pmf(wf_dir, tkey)
        a, source = resolve_assessment(res, (pm or {}).get("pmf"))
        digest_src = "stored" if source == "stored" else f"{source}(not stored)"
        inp = AssessmentInputs(
            scope=f"{name}/{tkey}", assessment=a, assessment_id=f"state.json#binding.{tkey}.assessment ({digest_src})",
            reanalysis={"available": _samples_on_disk(wf_dir, tkey) or bool(pm)},
            approved_run=approved_run_for(wf_dir, tkey, extend_ps=extend_ps),
            costs=cost_inputs(wf_dir, bench=bench, target=tkey), target_key=tkey)
        if first:
            done = _completed_replicas(wf_dir)
            if done:
                inp.replicas = {"done": min(done.values()), "required": required_replicas(), "system_ready": True}
            first = False
        out.append(inp)
    return out


def _completed_replicas(wf_dir: Path) -> dict:
    """{system: number of COMPLETE replica runs} from the run.json files (file truth)."""
    project_dir = wf_dir.parent.parent
    runs = (((load_json(wf_dir / "state.json", {}) or {}).get("steps") or {}).get("md_runs") or {}).get("runs") or {}
    out = {}
    for key, r in runs.items():
        cid = (r or {}).get("case_id")
        if not cid or (r or {}).get("cg"):
            continue
        out[key] = sum(1 for rid in (r.get("run_ids") or [])
                       if (load_json(_case_dir(project_dir, cid) / "runs" / rid / "run.json", {}) or {}).get("status") == "COMPLETE")
    return out
