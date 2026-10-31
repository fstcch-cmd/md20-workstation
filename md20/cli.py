"""`md20` command line.

  md20 doctor [--no-benchmark]                  hardware / platform / package report
  md20 project new NAME [--dir DIR]             create a project
  md20 build --project P --case NAME --receptor R.pdb --ligand REF.sdf [--pose POSE] ...
  md20 run --project P --case CASE [--tier teaching|classroom|research] [--fake]
  md20 status --project P                       stage of every case / run
  md20 demo [--dir DIR]                         end-to-end demo with the Fake backend (no OpenMM needed)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .util import default_projects_dir, load_json


def _p(msg: str) -> None:
    print(msg, flush=True)


def cmd_doctor(a):
    from .env import run_doctor
    rep = run_doctor(do_benchmark=not a.no_benchmark, benchmark_seconds=a.seconds)
    _p(rep.to_markdown())
    return 0 if rep.ok else 1


def cmd_project(a):
    from .project import Project
    if a.action == "new":
        p = Project.create(a.dir, a.name)
        _p(f"建立專案：{p.dir}")
    else:
        for p in Project.discover(a.dir):
            _p(f"{p.name}\t{p.dir}")
    return 0


def _open_project(a):
    from .project import Project
    path = Path(a.project)
    if not (path / "project.json").is_file():
        path = Path(a.dir) / a.project
    return Project(path)


def cmd_build(a):
    from .build.pipeline import build_case
    proj = _open_project(a)
    case = proj.new_case(a.case)
    poses = a.pose or []
    poses += [None] * (len(a.ligand) - len(poses))
    s = build_case(case, receptor=a.receptor, ligand_references=a.ligand, ligand_poses=poses, ph=a.ph,
                   padding_nm=a.padding, run_smoke_test=not a.no_smoke)
    _p(f"case {case.case_id}: {s['status']}")
    if s["status"] != "PASS":
        _p(json.dumps({k: v for k, v in s.items() if k in {"blocking", "receptor", "ligands"}}, ensure_ascii=False, indent=2, default=str)[:4000])
        return 2
    _p(f"system: {s['system_xml']}\ntopology: {s['topology_pdb']}")
    return 0


def _make_backend_factory(case, protocol, fake: bool):
    if fake:
        from .engine import FakeBackend
        return lambda spec, dt: FakeBackend(timestep_fs=dt, temperature_k=spec.temperature_k, ensemble=spec.ensemble)
    from .engine import OpenMMBackend
    from .env import choose_platform
    choice = choose_platform()
    bm = load_json(case.build_dir / "build_manifest.json", {})
    sys_xml, top = bm.get("system_xml"), bm.get("topology_pdb")
    if not sys_xml or not top:
        raise SystemExit("此 case 尚未 build 成功。")
    case.project.decisions.record("engine.platform", "OpenMM platform", choice.name,
                                  "依 CUDA→HIP→OpenCL→CPU 順序實測第一個能建立 Context 的平台。", rejected=choice.rejected)

    def make(spec, dt):
        return OpenMMBackend(sys_xml, top, platform_name=choice.name, platform_properties=choice.properties,
                             timestep_fs=dt, temperature_k=spec.temperature_k, friction_per_ps=spec.friction_per_ps,
                             ensemble=spec.ensemble, pressure_bar=spec.pressure_bar,
                             barostat_interval_steps=spec.barostat_interval_steps, hmr=protocol.hmr, seed=spec.seed)
    return make


def cmd_run(a):
    from .engine import make_protocol, run_protocol, NeedsHuman
    proj = _open_project(a)
    case = proj.case(a.case)
    run = case.active_run() if a.resume else None
    if run is None:
        protocol = make_protocol(a.tier, production_ns=a.ns)
        run = case.new_run(protocol.to_dict(), reason="cli")
    else:
        from .engine import Protocol
        protocol = Protocol.from_dict(run.manifest()["protocol"])
    make = _make_backend_factory(case, protocol, a.fake)
    identity = {"case_id": case.case_id, "run_id": run.run_id, "project_uuid": proj.uuid}
    last = {"t": 0.0}

    def cb(hb):
        import time
        if time.monotonic() - last["t"] > 10:
            last["t"] = time.monotonic()
            _p(f"[{hb['stage']}] chunk {hb['chunk']} {hb['completed_local_steps']:,}/{hb['total_steps']:,} "
               f"T={hb['temperature_k']:.1f}K dt={hb['timestep_fs']}fs {hb['elapsed_s']}s")
    try:
        st = run_protocol(run.dir, protocol, make, identity=identity, decisions=proj.decisions, progress_cb=cb)
    except NeedsHuman as exc:
        _p(f"[NEEDS_HUMAN] {exc}")
        return 3
    _p(f"run {run.run_id}: {st['status']}  figures → {run.figures_dir}")
    return 0


def cmd_report(a):
    from .report import build_run_report, reproducibility_bundle
    proj = _open_project(a)
    case = proj.case(a.case)
    run = case.active_run() if not a.run else __import__("md20.project", fromlist=["Run"]).Run(case, a.run)
    if run is None:
        raise SystemExit("此 case 沒有 run。")
    out = build_run_report(run)
    _p(f"report: {out}")
    if a.bundle:
        _p(f"bundle: {reproducibility_bundle(run)}")
    return 0


def cmd_queue(a):
    from .engine import JobQueue, PausePolicy
    from .env.hardware import _power_state
    proj = _open_project(a)
    q = JobQueue(proj)
    if a.action == "add":
        j = q.add(a.case, tier=a.tier, replicas=a.replicas, production_ns=a.ns)
        _p(f"queued {j['id']}: case={j['case_id']} tier={j['tier']} replicas={j['replicas']}")
    elif a.action == "list":
        for j in q.jobs():
            _p(f"{j['id']}  {j['case_id']}  {j['tier']}×{j['replicas']}  {j['status']}  {j.get('reason', '')}")
    elif a.action == "run":
        hours = tuple(int(x) for x in a.hours.split("-")) if a.hours else None
        policy = PausePolicy(pause_file=proj.dir / "PAUSE", pause_on_battery=not a.ignore_battery,
                             allowed_hours=hours, power_probe=_power_state)
        while True:
            j = q.run_next(lambda case, proto: _make_backend_factory(case, proto, a.fake), should_pause=policy)
            if j is None:
                _p("佇列已空。"); break
            _p(f"{j['id']} → {j['status']} {j.get('reason', '')}")
            if j["status"] != "COMPLETE":
                break
    return 0


def cmd_status(a):
    proj = _open_project(a)
    for c in proj.cases():
        m = c.manifest()
        _p(f"case {c.case_id}  ff={m.get('forcefield_family')}  status={m.get('status')}")
        for r in c.runs():
            rm = r.manifest()
            _p(f"   run {r.run_id}  stage={r.stage()}  status={rm.get('status')}")
    return 0


def cmd_demo(a):
    """Everything after build, with the fake backend: project → case → run → figures → decision log."""
    import tempfile
    from .project import Project
    from .engine import make_protocol, run_protocol, FakeBackend
    root = Path(a.dir) if a.dir else Path(tempfile.mkdtemp(prefix="md20_demo_"))
    proj = Project.create(root, "demo_project")
    case = proj.new_case("demo_case")
    proto = make_protocol("classroom")
    for s in proto.stages:
        if s.ensemble != "MIN":
            s.length_ps = 40.0; s.checkpoint_interval_ps = 10.0; s.report_interval_ps = 0.2
    run = case.new_run(proto.to_dict(), reason="demo")
    make = lambda spec, dt: FakeBackend(timestep_fs=dt, temperature_k=spec.temperature_k, ensemble=spec.ensemble)  # noqa: E731
    st = run_protocol(run.dir, proto, make, identity={"case_id": case.case_id, "run_id": run.run_id}, decisions=proj.decisions,
                      batch_steps=500)
    from .report import build_run_report
    _p(f"demo status: {st['status']}")
    _p(f"report: {build_run_report(run)}")
    _p(f"figures: {run.figures_dir}")
    _p(proj.decisions.to_markdown())
    return 0


def main(argv=None) -> int:
    from .env.winfix import suppress_windows_error_dialogs
    suppress_windows_error_dialogs()
    ap = argparse.ArgumentParser(prog="md20", description=f"MD20 teaching workstation {__version__}")
    ap.add_argument("--dir", default=str(default_projects_dir()), help="projects root directory")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("doctor"); d.add_argument("--no-benchmark", action="store_true"); d.add_argument("--seconds", type=float, default=20.0)
    d.set_defaults(fn=cmd_doctor)
    p = sub.add_parser("project"); p.add_argument("action", choices=["new", "list"]); p.add_argument("name", nargs="?")
    p.set_defaults(fn=cmd_project)
    b = sub.add_parser("build"); b.add_argument("--project", required=True); b.add_argument("--case", required=True)
    b.add_argument("--receptor", required=True); b.add_argument("--ligand", action="append", required=True)
    b.add_argument("--pose", action="append"); b.add_argument("--ph", type=float, default=7.4)
    b.add_argument("--padding", type=float, default=1.0); b.add_argument("--no-smoke", action="store_true")
    b.set_defaults(fn=cmd_build)
    r = sub.add_parser("run"); r.add_argument("--project", required=True); r.add_argument("--case", required=True)
    r.add_argument("--tier", default="teaching"); r.add_argument("--ns", type=float); r.add_argument("--resume", action="store_true")
    r.add_argument("--fake", action="store_true", help="use the synthetic backend (no OpenMM)")
    r.set_defaults(fn=cmd_run)
    s = sub.add_parser("status"); s.add_argument("--project", required=True); s.set_defaults(fn=cmd_status)
    qp = sub.add_parser("queue"); qp.add_argument("action", choices=["add", "list", "run"]); qp.add_argument("--project", required=True)
    qp.add_argument("--case"); qp.add_argument("--tier", default="teaching"); qp.add_argument("--replicas", type=int, default=1)
    qp.add_argument("--ns", type=float); qp.add_argument("--hours", help="允許時段，如 22-7"); qp.add_argument("--ignore-battery", action="store_true")
    qp.add_argument("--fake", action="store_true"); qp.set_defaults(fn=cmd_queue)
    rp = sub.add_parser("report"); rp.add_argument("--project", required=True); rp.add_argument("--case", required=True)
    rp.add_argument("--run"); rp.add_argument("--bundle", action="store_true"); rp.set_defaults(fn=cmd_report)
    m = sub.add_parser("demo"); m.add_argument("--dir"); m.set_defaults(fn=cmd_demo)
    a = ap.parse_args(argv)
    return int(a.fn(a) or 0)


if __name__ == "__main__":
    sys.exit(main())
