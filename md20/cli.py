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
from .util import default_projects_dir, load_json, safe_name


def _guard():
    from .env.resources import CachedGuard
    return CachedGuard()


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
    from .engine.factory import make_backend_factory
    return make_backend_factory(case, protocol, fake=fake, resource_mode=None if fake else "balanced")


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
                             allowed_hours=hours, power_probe=_power_state, resource_guard=_guard())
        while True:
            j = q.run_next(lambda case, proto: _make_backend_factory(case, proto, a.fake), should_pause=policy)
            if j is None:
                _p("佇列已空。"); break
            _p(f"{j['id']} → {j['status']} {j.get('reason', '')}")
            if j["status"] != "COMPLETE":
                break
    return 0


def cmd_pipeline(a):
    from .workflow import Workflow, WorkflowBlocked, example_config
    if a.action == "example":
        print(json.dumps(example_config(screen=getattr(a, "screen", False)), ensure_ascii=False, indent=2))
        return 0
    if not a.config:
        _p("pipeline run 需要設定檔：md20 pipeline example > my.json；md20 pipeline run my.json")
        return 2
    from .project import Project
    from .engine import PausePolicy
    from .engine.factory import make_backend_factory
    from .env import choose_platform
    from .env.hardware import _power_state
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    root = Path(a.dir) / safe_name(a.project)
    proj = Project(root) if (root / "project.json").is_file() else Project.create(a.dir, a.project)
    wf_cfg_path = root / "workflows" / safe_name(cfg.get("name", "workflow")) / "config.json"
    existing = load_json(wf_cfg_path, {}) if wf_cfg_path.is_file() else {}
    if existing and existing != cfg:
        # the workflow's own config.json carries decisions made at gates (GUI buttons / hand edits); the student's
        # original file does not — keep those instead of silently re-blocking at the same gate
        from .workflow import merge_human_decisions
        cfg, carried = merge_human_decisions(cfg, existing)
        if carried:
            _p("沿用先前在 workflow config.json 裡的人工決定：" + ", ".join(carried))
    wf = Workflow(proj, cfg)
    platform = choose_platform()
    _p(f"平台：{platform.name}；workflow 目錄：{wf.dir}")
    hours = tuple(int(x) for x in a.hours.split("-")) if a.hours else None
    policy = PausePolicy(pause_file=proj.dir / "PAUSE", pause_on_battery=not a.ignore_battery, allowed_hours=hours,
                         power_probe=_power_state, resource_guard=_guard())
    last = {"t": 0.0}

    def cb(ev):
        import time
        if time.monotonic() - last["t"] > 15:
            last["t"] = time.monotonic()
            _p("  " + ", ".join(f"{k}={v:.3g}" if isinstance(v, float) else f"{k}={v}" for k, v in ev.items() if k in
                                {"stage", "chunk", "completed_local_steps", "total_steps", "temperature_k", "ligand", "window", "n", "r0", "force"}))
    try:
        out = wf.run(lambda case, proto: make_backend_factory(case, proto, fake=a.fake, platform=platform, resource_mode=a.mode), platform,
                     should_pause=policy, progress_cb=cb)
    except WorkflowBlocked as exc:
        _p(f"[NEEDS_HUMAN] {exc}")
        _p(f"請在 {wf.dir / 'config.json'} 加上 pose_choices / human_choices 後重新執行同一指令。")
        return 3
    _p(f"workflow {out['status']}" + (f"；報告：{out.get('report')}" if out.get("report") else "（已暫停，重新執行即可續跑）"))
    return 0


def cmd_resume(a):
    """WP11: continue every unfinished workflow (after a reboot, crash or closed window)."""
    from .workflow import Workflow, WorkflowBlocked, find_workflows
    from .project import Project
    from .engine import PausePolicy
    from .engine.factory import make_backend_factory
    from .env import choose_platform
    from .env.hardware import _power_state
    if a.install_autostart or a.remove_autostart:
        from .env.autostart import install_autostart, remove_autostart
        _p(remove_autostart() if a.remove_autostart else install_autostart(a.dir))
        return 0
    rows = find_workflows(a.dir)
    todo = [r for r in rows if r["status"] in ("INCOMPLETE", "NEW") or (a.include_blocked and r["status"] == "NEEDS_HUMAN")]
    for r in rows:
        _p(f"  {r['status']:<12} {r['name']}  ({r['workflow_dir']})")
    if a.list or not todo:
        _p("沒有需要續跑的工作流程。" if not todo else f"{len(todo)} 個可續跑（去掉 --list 開始）。")
        return 0
    platform = choose_platform()
    _p(f"平台：{platform.name}；續跑 {len(todo)} 個工作流程")
    rc = 0
    for r in todo:
        proj = Project(r["project_dir"])
        cfg = json.loads((Path(r["workflow_dir"]) / "config.json").read_text(encoding="utf-8"))
        policy = PausePolicy(pause_file=proj.dir / "PAUSE", pause_on_battery=not a.ignore_battery, power_probe=_power_state, resource_guard=_guard())
        try:
            out = Workflow(proj, cfg).run(lambda case, proto: make_backend_factory(case, proto, platform=platform, resource_mode=a.mode), platform,
                                          should_pause=policy)
            _p(f"[{out['status']}] {r['name']}")
            if out["status"] == "PAUSED":
                return 0
        except WorkflowBlocked as exc:
            _p(f"[NEEDS_HUMAN] {r['name']}：{exc}")
            rc = 3
    return rc


def cmd_validate(a):
    """Write the workflow config of a paper-validation case (then: md20 pipeline run <file>)."""
    from .validation import CASES
    if a.case not in CASES:
        _p("可用案例：" + "、".join(f"{k}（{v.PAPER['citation'][:60]}…）" for k, v in CASES.items()))
        return 1
    mod = CASES[a.case]
    cfg = mod.workflow_config(tier=a.tier) if a.case != "hsieh2025" else mod.workflow_config(tier=a.tier, cpp_override=a.cpp_override)
    out = Path(a.out or f"{cfg['name']}.json")
    out.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    _p(f"已寫入 {out}\n{(mod.__doc__ or '').strip()}\n下一步：md20 pipeline run {out}")
    return 0


def cmd_drivers(a):
    """Detect GPUs → decide → one-click download of the official driver (never executed by us)."""
    from .env.hardware import probe_hardware
    from .env.drivers import plan_drivers, resolve_nvidia_download, download_driver, installer_hint
    hw = probe_hardware()
    plans = plan_drivers(hw, resolve=resolve_nvidia_download)
    for i, p in enumerate(plans, 1):
        _p(f"[{i}] {p.vendor} {p.gpu}  驅動 {p.driver or '未知'}  狀態 {p.status}  → 現在會用 {p.platform_now}")
        _p("    " + p.why)
        for st in p.steps:
            _p("    " + st)
        if p.download_url:
            _p(f"    官方下載：{p.download_url}" + (f"（{p.package_version}）" if p.package_version else ""))
        elif p.download_page:
            _p(f"    官方頁面：{p.download_page}")
        _p(f"    安裝器：{installer_hint(p)}")
    if a.action == "plan":
        return 0
    targets = [p for p in plans if p.download_url or p.download_page]
    if not targets:
        _p("沒有可下載的驅動（沒有偵測到 GPU，或驅動已是最新）。")
        return 0
    p = targets[0]
    import webbrowser
    if a.action == "open" or not p.download_url:
        _p(f"開啟官方頁面：{p.download_page or p.download_url}")
        webbrowser.open(p.download_page or p.download_url)
        return 0
    last = {"pct": -1}

    def cb(ev):
        if ev["pct"] is not None and ev["pct"] != last["pct"] and ev["pct"] % 5 == 0:
            last["pct"] = ev["pct"]; _p(f"  下載 {ev['pct']}%")
    dest = download_driver(p.download_url, a.out, progress_cb=cb)
    _p(f"已下載到 {dest}\n請雙擊安裝（需要管理員權限，安裝後重開機），然後重跑安裝器：{installer_hint(p).replace(' -Cuda ' + str(p.env_cuda_version), '')}")
    try:
        webbrowser.open(str(dest.parent))
    except Exception:  # noqa: BLE001
        pass
    return 0


def cmd_screen(a):
    """Write an example compound sheet (every accepted column) for `screen.library`."""
    from .docking.library import write_template
    p = write_template(a.out)
    _p(f"已寫入 {p}。填入化合物後在 pipeline 設定加上：\n"
       '  "screen": {"library": "' + str(p) + '", "exhaustiveness": 8, "n_poses": 3, "top_n": 20}\n'
       "欄位：name（必填）＋ smiles / pubchem_cid / inchikey / chembl_id / ccd / sdf 任一（優先序同此順序）。")
    return 0


def cmd_gui(a):
    from .gui.app import main as gui_main
    gui_main(projects_dir=a.dir, port=a.port, show=not a.no_browser, host=a.host)
    return 0


def cmd_setup_vina(a):
    from .docking.vina_cli import ensure_vina_exe
    try:
        import vina  # noqa: F401
        _p("vina Python bindings 已安裝；不需要執行檔。")
        return 0
    except ImportError:
        pass
    _p(f"vina 執行檔：{ensure_vina_exe()}")
    return 0


def cmd_stamp(a):
    from .util import stamp as st
    if a.action == "keygen":
        priv, pub = st.keygen(a.out)
        _p(f"私鑰（請離線保存，切勿上傳）：{priv}\n公鑰（放進 md20/util/owner_pub.pem）：{pub}")
        return 0
    for f in a.files:
        found = st.find_markers(f)
        _p(f"{f}\n  可見戳記：{'有' if found['visible'] else '無'}\n  隱藏標記：{', '.join(found['hidden']) or '無'}\n"
           f"  加密來源紀錄：{'有' if found['blob'] else '無'}")
        if a.action == "decrypt" and found["blob"]:
            if not a.key:
                _p("  （需要 --key 私鑰才能解開）"); continue
            try:
                _p("  解密內容：" + json.dumps(st.decrypt_blob(found["blob"], a.key), ensure_ascii=False))
            except Exception as exc:  # noqa: BLE001
                _p(f"  解密失敗：{type(exc).__name__}（金鑰不符或內容被竄改）")
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


def _utf8_console() -> None:
    """Windows consoles default to a legacy code page; Chinese output would raise UnicodeEncodeError."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def main(argv=None) -> int:
    from .env.winfix import suppress_windows_error_dialogs
    suppress_windows_error_dialogs()
    _utf8_console()
    ap = argparse.ArgumentParser(prog="md20", description=f"MD20 teaching workstation {__version__}")
    ap.add_argument("--dir", default=str(default_projects_dir()), help="projects root directory")
    ap.add_argument("--mode", choices=["background", "balanced", "full"], default="balanced",
                    help="資源模式：background（不干擾使用者）/ balanced / full（整台電腦）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("doctor"); d.add_argument("--no-benchmark", action="store_true"); d.add_argument("--seconds", type=float, default=20.0)
    d.set_defaults(fn=cmd_doctor)
    p = sub.add_parser("project"); p.add_argument("action", choices=["new", "list"]); p.add_argument("name", nargs="?")
    p.set_defaults(fn=cmd_project)
    b = sub.add_parser("build"); b.add_argument("--project", required=True); b.add_argument("--case", required=True)
    b.add_argument("--receptor", required=True); b.add_argument("--ligand", action="append", required=True)
    b.add_argument("--pose", action="append"); b.add_argument("--ph", type=float, default=7.4)
    b.add_argument("--padding", type=float, default=0.8); b.add_argument("--no-smoke", action="store_true")
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
    pl = sub.add_parser("pipeline", help="docking → MD → binding 全流程")
    pl.add_argument("action", choices=["run", "example"]); pl.add_argument("config", nargs="?")
    pl.add_argument("--screen", action="store_true", help="example：含高通量篩選（screen.library）的範本")
    pl.add_argument("--project", default="MD20_Pipelines"); pl.add_argument("--hours"); pl.add_argument("--ignore-battery", action="store_true")
    pl.add_argument("--fake", action="store_true"); pl.set_defaults(fn=cmd_pipeline)
    rs = sub.add_parser("resume", help="續跑所有未完成的工作流程（重開機／當機後）")
    rs.add_argument("--all", action="store_true", help="（預設行為）所有未完成者"); rs.add_argument("--list", action="store_true")
    rs.add_argument("--include-blocked", action="store_true"); rs.add_argument("--ignore-battery", action="store_true")
    rs.add_argument("--install-autostart", action="store_true", help="登入時自動續跑（可隨時移除）")
    rs.add_argument("--remove-autostart", action="store_true"); rs.set_defaults(fn=cmd_resume)
    va = sub.add_parser("validate", help="以 HCC Lab 論文建立驗證／教學案例")
    va.add_argument("case", nargs="?", default="list"); va.add_argument("--out"); va.add_argument("--tier", default="classroom")
    va.add_argument("--cpp-override", help="胜肽 CPP 未通過仍要繼續的理由（會寫入報告）"); va.set_defaults(fn=cmd_validate)
    dr = sub.add_parser("drivers", help="顯示卡驅動：偵測 → 判定 → 一鍵下載官方驅動（不自動安裝）")
    dr.add_argument("action", choices=["plan", "download", "open"], nargs="?", default="plan")
    dr.add_argument("--out", help="下載目錄（預設 ~/Downloads）"); dr.set_defaults(fn=cmd_drivers)
    sc = sub.add_parser("screen", help="高通量篩選：化合物庫範本")
    sc.add_argument("action", choices=["template"]); sc.add_argument("--out", default="compound_library.xlsx"); sc.set_defaults(fn=cmd_screen)
    g = sub.add_parser("gui", help="圖形介面（瀏覽器）"); g.add_argument("--port", type=int, default=8020)
    g.add_argument("--host", default="127.0.0.1", help="預設只本機可連；0.0.0.0 才對網路開放（教室 Wi-Fi 上任何人都能操作）")
    g.add_argument("--no-browser", action="store_true"); g.set_defaults(fn=cmd_gui)
    stp = sub.add_parser("stamp", help="檢查／解開 HCC Lab 戳記"); stp.add_argument("action", choices=["verify", "decrypt", "keygen"])
    stp.add_argument("files", nargs="*"); stp.add_argument("--key"); stp.add_argument("--out", default="."); stp.set_defaults(fn=cmd_stamp)
    sv = sub.add_parser("setup-vina", help="下載 AutoDock Vina 執行檔（Windows）"); sv.set_defaults(fn=cmd_setup_vina)
    rp = sub.add_parser("report"); rp.add_argument("--project", required=True); rp.add_argument("--case", required=True)
    rp.add_argument("--run"); rp.add_argument("--bundle", action="store_true"); rp.set_defaults(fn=cmd_report)
    m = sub.add_parser("demo"); m.add_argument("--dir"); m.set_defaults(fn=cmd_demo)
    a = ap.parse_args(argv)
    return int(a.fn(a) or 0)


if __name__ == "__main__":
    sys.exit(main())
