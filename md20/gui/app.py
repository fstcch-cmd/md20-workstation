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
        chart = ui.echart({"xAxis": {"type": "value", "name": "步"}, "yAxis": {"type": "value", "name": "T (K)"},
                           "series": [{"type": "line", "showSymbol": False, "data": []}], "title": {"text": "即時溫度", "textStyle": {"fontSize": 12}}}
                          ).classes("w-full h-64")

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
            pts = [[h.get("absolute_step", i), h["temperature_k"]] for i, h in enumerate(snap["history"]) if "temperature_k" in h]
            chart.options["series"][0]["data"] = pts[-500:]
            chart.update()
            report_btn.set_visibility((wf.dir / "workflow_report.html").is_file())
        ui.timer(2.0, refresh)
        refresh()


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
