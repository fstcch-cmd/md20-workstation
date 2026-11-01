"""NiceGUI pages.  Thin layer over md20.gui.logic; run with `md20 gui`."""
from __future__ import annotations

from pathlib import Path

from nicegui import app, ui

from ..env import run_doctor, choose_platform
from ..engine import PausePolicy
from ..engine.factory import make_backend_factory
from ..project import Project
from ..util import default_projects_dir, load_json, safe_name
from ..workflow import Workflow
from .logic import Runner, config_from_form, list_workflows, pose_table, set_pose_choice
from .views import gate_cards, timeline, live_series, echart_options, viewer_targets, scene_for, viewer_html

RUNNER = Runner()
STATE: dict = {"projects_dir": default_projects_dir(), "platform": None, "doctor": None}

STATUS_COLOR = {"PASS": "positive", "COMPLETE": "positive", "RUNNING": "primary", "PAUSED": "warning",
                "NEEDS_HUMAN": "negative", "ERROR": "negative"}


def _platform():
    if STATE["platform"] is None:
        STATE["platform"] = choose_platform()
    return STATE["platform"]


def _header():
    with ui.header().classes("items-center justify-between"):
        ui.label("MD20 教學工作站").classes("text-lg font-bold")
        with ui.row():
            ui.link("儀表板", "/").classes("text-white")
            ui.link("新流程", "/new").classes("text-white")


@ui.page("/")
def dashboard():
    _header()
    with ui.column().classes("w-full max-w-5xl mx-auto"):
        ui.label("電腦狀態（Doctor）").classes("text-xl font-semibold")
        box = ui.markdown("_按下按鈕執行診斷_")

        async def do_doctor(bench: bool):
            box.set_content("診斷中…（benchmark 約 20 秒）" if bench else "診斷中…")
            from nicegui import run as nrun
            rep = await nrun.io_bound(run_doctor, do_benchmark=bench, benchmark_seconds=15.0)
            STATE["doctor"] = rep
            if rep.platform:
                STATE["platform"] = None
            box.set_content(rep.to_markdown())
        with ui.row():
            ui.button("快速診斷", on_click=lambda: do_doctor(False))
            ui.button("診斷＋效能測試", on_click=lambda: do_doctor(True)).props("outline")
        ui.separator()
        ui.label("流程").classes("text-xl font-semibold")
        rows = list_workflows(STATE["projects_dir"])
        cols = [{"name": k, "label": l, "field": k} for k, l in
                (("project", "專案"), ("workflow", "流程"), ("last_step", "最後步驟"), ("status", "狀態"), ("updated", "更新"))]
        t = ui.table(columns=cols, rows=rows, row_key="workflow").classes("w-full")
        t.on("rowClick", lambda e: ui.navigate.to(f"/wf/{e.args[1]['project']}/{e.args[1]['workflow']}"))
        if not rows:
            ui.label("尚無流程；按「新流程」開始。").classes("text-gray-500")


@ui.page("/new")
def new_pipeline():
    _header()
    with ui.column().classes("w-full max-w-4xl mx-auto gap-2"):
        ui.label("建立 docking → MD → 結合強度 流程").classes("text-xl font-semibold")
        project = ui.input("專案名稱", value="課堂專案").classes("w-full")
        name = ui.input("流程名稱", value="trypsin_benzamidine").classes("w-full")
        with ui.row().classes("w-full"):
            pdb_id = ui.input("PDB ID", value="3PTB").classes("w-40")
            ph = ui.number("pH", value=7.4, step=0.1).classes("w-24")
            keep = ui.input("保留輔因子／金屬（逗號分隔）", value="CA").classes("w-80")
        ligs = ui.textarea("配體（每行：名稱 SMILES [晶體殘基名]）",
                           value="BEN NC(=[NH2+])c1ccccc1 BEN").classes("w-full font-mono")
        ui.label("SMILES 的質子化狀態會直接用於 docking 與 MD；請依 pH 7.4 寫出帶電形式（如脒基 +1）。").classes("text-xs text-gray-500")
        with ui.row().classes("w-full"):
            box_res = ui.input("Box：以晶體殘基定義（如 BEN）", value="BEN").classes("w-64")
            box_c = ui.input("或中心 x,y,z（Å）").classes("w-48")
            box_s = ui.input("尺寸 x,y,z（Å）", value="22,22,22").classes("w-40")
        with ui.row().classes("w-full items-center"):
            mode = ui.select({"independent": "independent（逐一篩選）", "simultaneous": "simultaneous（同時對接）"},
                             value="independent", label="Docking 模式").classes("w-72")
            exh = ui.number("exhaustiveness", value=16, min=1, max=128).classes("w-36")
        systems = ui.select({"apo": "apo（原始蛋白）", "docked_single": "docked_single（每個配體）", "docked_multi": "docked_multi（多配體同時）"},
                            value=["apo", "docked_single"], multiple=True, label="MD 系統").classes("w-full")
        with ui.row().classes("w-full items-center"):
            tier = ui.select({"classroom": "課堂（2 ns）", "teaching": "教學（10 ns）", "research": "研究（100 ns）"},
                             value="teaching", label="長度").classes("w-48")
            reps = ui.number("replicas", value=1, min=1, max=10).classes("w-28")
            binding = ui.switch("SMD＋傘狀採樣（結合強度）", value=True)
        err = ui.label("").classes("text-negative")

        def create():
            try:
                cfg = config_from_form(name=name.value, pdb_id=pdb_id.value, ligands_text=ligs.value, box_residue=box_res.value,
                                       box_center=box_c.value, box_size=box_s.value, mode=mode.value, exhaustiveness=int(exh.value),
                                       systems=list(systems.value), tier=tier.value, replicas=int(reps.value), binding=binding.value,
                                       ph=float(ph.value), keep_hetero=keep.value)
            except Exception as exc:  # noqa: BLE001
                err.set_text(str(exc)); return
            root = Path(STATE["projects_dir"]) / safe_name(project.value)
            proj = Project(root) if (root / "project.json").is_file() else Project.create(STATE["projects_dir"], project.value)
            wf = Workflow(proj, cfg)
            _start(wf)
            ui.navigate.to(f"/wf/{proj.dir.name}/{wf.name}")
        ui.button("建立並開始", on_click=create).props("color=primary")


def _start(wf: Workflow):
    platform = _platform()
    policy = PausePolicy(pause_file=wf.project.dir / "PAUSE", pause_on_battery=True,
                         power_probe=__import__("md20.env.hardware", fromlist=["_power_state"])._power_state,
                         resource_guard=__import__("md20.env.resources", fromlist=["CachedGuard"]).CachedGuard())
    (wf.project.dir / "PAUSE").unlink(missing_ok=True)
    return RUNNER.start(wf, lambda case, proto: make_backend_factory(case, proto, platform=platform, resource_mode="balanced"), platform, should_pause=policy)


@ui.page("/wf/{project}/{name}")
def workflow_page(project: str, name: str):
    _header()
    proj = Project(Path(STATE["projects_dir"]) / project)
    cfg = load_json(proj.dir / "workflows" / name / "config.json", {})
    wf = Workflow(proj, cfg)
    with ui.column().classes("w-full max-w-6xl mx-auto gap-3"):
        ui.label(f"{project} / {name}").classes("text-xl font-semibold")
        status = ui.label("").classes("text-lg")
        msg = ui.markdown("")
        with ui.row():
            ui.button("開始／繼續", on_click=lambda: _start(wf))
            ui.button("暫停（在下一個 chunk 邊界）", on_click=lambda: (wf.project.dir / "PAUSE").touch()).props("outline")
            report_btn = ui.button("開啟報告", on_click=lambda: ui.navigate.to(f"/file?path={wf.dir / 'workflow_report.html'}", new_tab=True)).props("outline")
        steps = ui.table(columns=[{"name": k, "label": l, "field": k} for k, l in (("step", "步驟"), ("status", "狀態"), ("at", "時間"), ("message", "訊息"))],
                         rows=[], row_key="key").classes("w-full")
        ui.label("Pose（★ 推薦、✔ 已選；點選某列改用該 pose，系統會從 pose 選擇之後重新執行）").classes("font-semibold")
        poses = ui.table(columns=[{"name": k, "label": l, "field": k} for k, l in
                                  (("entry", "配體"), ("rank", "rank"), ("score", "score"), ("cluster", "cluster"), ("contacts", "接觸"),
                                   ("rmsd_ref", "RMSD 晶體"), ("tag", ""))], rows=[], row_key="key").classes("w-full")
        reason = ui.markdown("")

        def pick(e):
            row = e.args[1]
            set_pose_choice(wf, row["entry"], row["rank"])
            ui.notify(f"{row['entry']} 改用第 {row['rank']} 名 pose；按「開始／繼續」重新執行後續步驟")
        poses.on("rowClick", pick)
        # ---- WP13: gate cards / live curves / timeline / offline 3D -------------------------------------
        with ui.tabs().classes("w-full") as tabs:
            t_gate, t_live, t_time, t_3d = (ui.tab("閘門"), ui.tab("即時曲線"), ui.tab("時間軸"), ui.tab("3D 檢視"))
        with ui.tab_panels(tabs, value=t_gate).classes("w-full"):
            with ui.tab_panel(t_gate):
                cards_box = ui.column().classes("w-full gap-2")
            with ui.tab_panel(t_live):
                prog = ui.label("").classes("text-sm")
                bar = ui.linear_progress(value=0, show_value=False).classes("w-full")
                with ui.row().classes("w-full"):
                    ch_t = ui.echart(echart_options([], title="溫度", x="步", y="K")).classes("w-[48%] h-60")
                    ch_e = ui.echart(echart_options([], title="位能", x="步", y="kJ/mol")).classes("w-[48%] h-60")
                with ui.row().classes("w-full"):
                    ch_f = ui.echart(echart_options([], title="SMD 拉力", x="r (nm)", y="kJ/mol/nm")).classes("w-[48%] h-60")
                    ch_w = ui.echart(echart_options([], title="SMD 功", x="r (nm)", y="kJ/mol")).classes("w-[48%] h-60")
            with ui.tab_panel(t_time):
                time_box = ui.column().classes("w-full gap-1")
            with ui.tab_panel(t_3d):
                targets = viewer_targets(wf)
                if not targets:
                    ui.label("建模完成後即可檢視 3D 結構；production 完成後可播放軌跡。").classes("text-gray-500")
                else:
                    pick3d = ui.select({i: t["label"] for i, t in enumerate(targets)}, value=0, label="結構").classes("w-96")
                    frame = ui.html("").classes("w-full")

                    def show3d():
                        frame.set_content(f'<iframe src="/viewer?project={project}&name={name}&i={pick3d.value}" '
                                          'style="width:100%;height:560px;border:0"></iframe>')
                    pick3d.on_value_change(lambda _: show3d())
                    show3d()
        cards_sig = {"v": None}
        time_sig = {"v": None}

        def refresh():
            job = RUNNER.get(wf)
            snap = job.snapshot() if job else {"status": "IDLE", "message": "", "steps": __import__("md20.gui.logic", fromlist=["step_rows"]).step_rows(wf.state()), "history": []}
            status.set_text(f"狀態：{snap['status']}")
            msg.set_content(f"```\n{snap['message']}\n```" if snap["message"] else "")
            steps.rows = snap["steps"]
            rows = pose_table(wf)
            for r in rows:
                r["key"] = f"{r['entry']}-{r['rank']}"
                r["tag"] = ("★" if r["recommended"] else "") + ("✔" if r["chosen"] else "") + ("⚠碰撞" if r["clash"] else "")
            poses.rows = rows
            reason.set_content("\n\n".join(f"**{r['entry']} 推薦理由：** {r['reason']}" for r in rows if r["reason"]))
            ls = live_series(snap["history"])
            for ch, k in ((ch_t, "temperature"), (ch_e, "potential"), (ch_f, "smd_force"), (ch_w, "smd_work")):
                ch.options["series"][0]["data"] = ls[k]
                ch.update()
            pg = ls["progress"]
            if pg:
                prog.set_text(f"{pg['stage']}：{pg['pct']}%" + (f"（傘狀採樣 window {ls['umbrella']['window']}/{ls['umbrella']['n']}）"
                                                               if ls.get("umbrella") else ""))
                bar.set_value((pg["pct"] or 0) / 100.0)
            cards = gate_cards(wf)
            if cards != cards_sig["v"]:
                cards_sig["v"] = cards
                cards_box.clear()
                with cards_box:
                    if not cards:
                        ui.label("目前沒有需要注意的閘門。").classes("text-gray-500")
                    for c in cards:
                        with ui.card().classes("w-full"):
                            with ui.row().classes("items-center gap-2"):
                                ui.badge(c["label"], color=c["color"])
                                ui.label(f"{c['source']} · {c['title']}").classes("font-semibold")
                            ui.label(c["explanation"]).classes("text-sm whitespace-pre-wrap")
                            for o in c["options"]:
                                ui.label(f"→ {o}").classes("text-sm text-primary")
            tl = timeline(wf, limit=120)
            if len(tl) != time_sig["v"]:
                time_sig["v"] = len(tl)
                time_box.clear()
                with time_box:
                    for e in reversed(tl):
                        with ui.row().classes("w-full items-start gap-2"):
                            ui.label(e["at"][11:19]).classes("text-xs text-gray-500 w-16")
                            ui.badge("人工" if e["status"] == "human" else ("步驟" if e["kind"] == "step" else "自動"),
                                     color="negative" if e["status"] in ("human", "NEEDS_HUMAN") else
                                     ("primary" if e["kind"] == "step" else "grey"))
                            with ui.column().classes("gap-0"):
                                ui.label(e["title"]).classes("text-sm font-semibold")
                                if e["text"]:
                                    ui.label(e["text"]).classes("text-xs whitespace-pre-wrap")
            report_btn.set_visibility((wf.dir / "workflow_report.html").is_file())
        ui.timer(2.0, refresh)
        refresh()


@app.get("/viewer")
def serve_viewer(project: str, name: str, i: int = 0):
    """Offline 3D viewer page (inline JS, no CDN) for one case of a workflow."""
    from fastapi.responses import HTMLResponse
    if safe_name(project) != project or safe_name(name) != name:
        return HTMLResponse("not allowed", status_code=403)
    proj = Project(Path(STATE["projects_dir"]) / project)
    wf = Workflow(proj, load_json(proj.dir / "workflows" / name / "config.json", {}))
    targets = viewer_targets(wf)
    if not 0 <= i < len(targets):
        return HTMLResponse("沒有可檢視的結構", status_code=404)
    try:
        return HTMLResponse(viewer_html(scene_for(targets[i]), title=targets[i]["label"]))
    except Exception as exc:  # noqa: BLE001
        return HTMLResponse(f"無法產生 3D 場景：{type(exc).__name__}: {exc}", status_code=500)


@app.get("/file")
def serve_file(path: str):
    from fastapi.responses import FileResponse, HTMLResponse
    p = Path(path).resolve()
    root = Path(STATE["projects_dir"]).resolve()
    if root not in p.parents or not p.is_file():
        return HTMLResponse("not allowed", status_code=403)
    return FileResponse(p)


def main(projects_dir: str | None = None, port: int = 8020, show: bool = True):
    if projects_dir:
        STATE["projects_dir"] = Path(projects_dir)
    Path(STATE["projects_dir"]).mkdir(parents=True, exist_ok=True)
    ui.run(title="MD20", port=port, show=show, reload=False, language="zh-TW")
