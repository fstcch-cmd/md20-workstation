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
from .logic import Runner, config_from_form, list_workflows, pose_table, set_pose_choice, screen_table
from .actions import apply_gate_action, resample_range, select_screen_ligands
from ..docking.screen import echart_screen, echart_ranking
from .views import (gate_cards, timeline, live_series, echart_options, viewer_targets, scene_for, viewer_html,
                    coverage_targets, coverage_chart, coverage_summary)
from .content import t, LANG_NAMES
from .gate_text import gate_title, gate_general, option_text

RUNNER = Runner()
STATE: dict = {"projects_dir": default_projects_dir(), "platform": None, "doctor": None, "lang": None}


def lang() -> str:
    """Interface language (D-51): English by default; the choice is kept in <projects>/gui_settings.json."""
    path = Path(STATE["projects_dir"]) / "gui_settings.json"
    try:
        mt = path.stat().st_mtime_ns
    except OSError:
        mt = None
    if STATE["lang"] is None or STATE.get("lang_mtime") != mt:      # re-read when the file changes (another window)
        STATE["lang"] = load_json(path, {}).get("lang", "en") if mt else "en"
        STATE["lang_mtime"] = mt
    return STATE["lang"] if STATE["lang"] in LANG_NAMES else "en"


def _(zh: str, en: str) -> str:
    """Inline bilingual text for page code."""
    return zh if lang() == "zh" else en


STEP_TEXT = {"receptor_input": ("受體來源", "Receptor source"), "receptor_docking": ("受體整理", "Receptor preparation"),
             "screen_library": ("篩選：化合物庫", "Screening: compound library"), "screen_docking": ("篩選：快速對接", "Screening: fast docking"),
             "screen_selection": ("篩選：選擇化合物", "Screening: compound selection"), "docking": ("分子對接", "Molecular docking"),
             "pose_selection": ("姿勢選擇", "Pose selection"), "md_confirm": ("確認進入分子動力學", "Confirm molecular dynamics"),
             "md_cases": ("建模", "System building"), "md_runs": ("分子動力學", "Molecular dynamics"),
             "analysis": ("軌跡分析", "Trajectory analysis"), "binding": ("結合自由能", "Binding free energy"), "report": ("報告", "Report")}
STATUS_TEXT = {"PASS": ("完成", "Done"), "COMPLETE": ("完成", "Done"), "RUNNING": ("執行中", "Running"), "PAUSED": ("已暫停", "Paused"),
               "NEEDS_HUMAN": ("需要你決定", "Needs your decision"), "ERROR": ("錯誤", "Error"), "IDLE": ("未執行", "Idle"),
               "AUTO_FIXED": ("已自動修正", "Corrected automatically"), "—": ("—", "—")}


SOURCE_EN = [("科學限制 · 胜肽", "Scientific limitation · peptide"), ("結構可信度", "Structure validity"), ("受體整理", "Receptor preparation"),
             ("受體來源", "Receptor source"), ("對接前檢查", "Docking pre-checks"), ("分子對接", "Molecular docking"),
             ("pose 選擇", "Pose selection"), ("確認進入 MD", "Confirm molecular dynamics"), ("MD 建模", "System building"),
             ("MD 執行", "Molecular dynamics"), ("軌跡分析", "Trajectory analysis"), ("SMD＋傘狀採樣", "Binding free energy"),
             ("報告", "Report"), ("組裝", "assembly"), ("受體", "receptor"), ("配體", "ligand")]
BADGE_EN = {"需要你決定": "Needs your decision", "已自動修正": "Corrected automatically", "通過": "Passed", "已暫停": "Paused", "執行中": "Running"}


def card_source(src: str) -> str:
    if lang() == "zh":
        return src
    for zh, en in SOURCE_EN:
        src = src.replace(zh, en)
    return src


def card_badge(c: dict) -> str:
    if c.get("advisory"):
        return _("科學限制提醒", "Scientific notice")
    return c["label"] if lang() == "zh" else BADGE_EN.get(c["label"], c["label"])


def set_lang(code: str) -> None:
    from ..util import atomic_write_json
    STATE["lang"] = code if code in LANG_NAMES else "en"
    path = Path(STATE["projects_dir"]) / "gui_settings.json"
    d = load_json(path, {})
    d["lang"] = STATE["lang"]
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(d, path)


CSS = """
<style>
  body { font-family: "Inter", "Segoe UI", "Noto Sans TC", "Microsoft JhengHei", system-ui, sans-serif;
         background: #f6f7f9; color: #1f2933; }
  .md20-header { background: #1f2933 !important; }
  .md20-title { font-weight: 600; letter-spacing: .01em; }
  .md20-section { font-size: 1.05rem; font-weight: 600; color: #1f2933; margin-top: .5rem; }
  .md20-muted { color: #616e7c; font-size: .85rem; }
  .md20-card { background: #fff; border: 1px solid #e4e7eb; border-radius: 6px; box-shadow: none; }
  .md20-mode { cursor: pointer; transition: border-color .15s; }
  .md20-mode:hover { border-color: #2f6f9f; }
  .md20-param-label { font-size: .9rem; font-weight: 500; }
  .md20-why { color: #52606d; font-size: .8rem; line-height: 1.35; }
  .md20-changed { color: #b44d12; font-size: .75rem; }
  .q-table th { font-weight: 600; }
</style>
"""

STATUS_COLOR = {"PASS": "positive", "COMPLETE": "positive", "RUNNING": "primary", "PAUSED": "warning",
                "NEEDS_HUMAN": "negative", "ERROR": "negative"}


def _platform():
    if STATE["platform"] is None:
        STATE["platform"] = choose_platform()
    return STATE["platform"]


def _header():
    L = lang()
    ui.add_head_html(CSS)
    with ui.header().classes("items-center justify-between md20-header"):
        ui.label(t("app_title", L)).classes("text-lg md20-title")
        with ui.row().classes("items-center gap-4"):
            ui.link(t("nav_home", L), "/").classes("text-white no-underline")
            ui.link(t("nav_system", L), "/system").classes("text-white no-underline")

            def change(e):
                set_lang(e.value)
                ui.navigate.reload()
            ui.select(LANG_NAMES, value=L, on_change=change).props("dense dark borderless options-dense").classes("w-28")


@ui.page("/system")
def dashboard():
    _header()
    with ui.column().classes("w-full max-w-5xl mx-auto"):
        ui.label(_("電腦狀態", "Computer status")).classes("text-xl font-semibold")
        box = ui.markdown(_("_按下按鈕執行診斷_", "_Press a button to check this computer_"))

        async def do_doctor(bench: bool):
            box.set_content(_("診斷中，效能測試約 20 秒…", "Checking; the benchmark takes about 20 s…") if bench else _("診斷中…", "Checking…"))
            from nicegui import run as nrun
            rep = await nrun.io_bound(run_doctor, do_benchmark=bench, benchmark_seconds=15.0)
            STATE["doctor"] = rep
            if rep.platform:
                STATE["platform"] = None
            box.set_content(rep.to_markdown(lang()))
            render_drivers(rep)
        with ui.row():
            ui.button(_("快速診斷", "Quick check"), on_click=lambda: do_doctor(False))
            ui.button(_("診斷並測試效能", "Check and benchmark"), on_click=lambda: do_doctor(True)).props("outline")
        drv_box = ui.column().classes("w-full gap-2")

        def render_drivers(rep):
            drv_box.clear()
            plans = (rep.hardware or {}).get("driver_plans") or []
            from ..env.drivers import installer_hint, DriverPlan
            with drv_box:
                for d in plans:
                    dp = DriverPlan(**{k: v for k, v in d.items() if k in DriverPlan.__dataclass_fields__})
                    color = {"OK": "positive", "UPDATE": "warning", "FALLBACK": "grey", "NONE": "warning", "UNKNOWN": "grey"}[dp.status]
                    with ui.card().classes("w-full"):
                        with ui.row().classes("items-center gap-2"):
                            ui.badge(dp.status, color=color)
                            ui.label(f"{dp.vendor} {dp.gpu} · 驅動 {dp.driver or '未知'} · 現在會用 {dp.platform_now}").classes("font-semibold")
                        ui.label(dp.why).classes("text-sm whitespace-pre-wrap")
                        for st in dp.steps:
                            ui.label(st).classes("text-sm text-primary")
                        ui.label(f"安裝器指令：{installer_hint(dp)}").classes("text-xs font-mono")
                        with ui.row().classes("gap-2"):
                            if dp.download_url:
                                prog = ui.label("").classes("text-sm")

                                async def do_download(url=dp.download_url, prog=prog):
                                    from nicegui import run as nrun
                                    from ..env.drivers import download_driver
                                    prog.set_text("下載中…")
                                    try:
                                        dest = await nrun.io_bound(download_driver, url)
                                    except Exception as exc:  # noqa: BLE001
                                        prog.set_text(f"下載失敗：{exc}"); return
                                    prog.set_text(f"已下載：{dest}。請雙擊安裝（管理員權限、重開機），再重跑安裝器。")
                                ui.button(f"一鍵下載官方驅動{'（' + dp.package_version + '）' if dp.package_version else ''}",
                                          on_click=do_download).props("color=primary")
                            if dp.download_page:
                                ui.button(_("開啟官方下載頁", "Open the official download page"), on_click=lambda u=dp.download_page: ui.navigate.to(u, new_tab=True)).props("outline")
        ui.separator()
        ui.label(_("流程", "Workflows")).classes("text-xl font-semibold")
        rows = list_workflows(STATE["projects_dir"])
        cols = [{"name": k, "label": l, "field": k} for k, l in
                (("project", "專案"), ("workflow", "流程"), ("last_step", "最後步驟"), ("status", "狀態"), ("updated", "更新"))]
        t = ui.table(columns=cols, rows=rows, row_key="workflow").classes("w-full")
        t.on("rowClick", lambda e: ui.navigate.to(f"/wf/{e.args[1]['project']}/{e.args[1]['workflow']}"))
        if not rows:
            ui.label(_("尚無流程；從首頁選擇模式開始。", "No workflows yet; choose a mode on the home page.")).classes("text-gray-500")


def _start(wf: Workflow):
    platform = _platform()
    policy = PausePolicy(pause_file=wf.project.dir / "PAUSE", pause_on_battery=True,
                         power_probe=__import__("md20.env.hardware", fromlist=["_power_state"])._power_state,
                         resource_guard=__import__("md20.env.resources", fromlist=["CachedGuard"]).CachedGuard())
    (wf.project.dir / "PAUSE").unlink(missing_ok=True)
    return RUNNER.start(wf, lambda case, proto: make_backend_factory(case, proto, platform=platform, resource_mode="balanced"), platform, should_pause=policy)


def _gate_buttons(wf: Workflow, card: dict):
    """One-click decisions on a NEEDS_HUMAN card; options the program cannot carry out stay as text."""
    if card["status"] != "NEEDS_HUMAN" and not card.get("advisory"):
        return
    for a in card.get("actions", []):
        with ui.row().classes("items-center gap-2 w-full"):
            note = ui.input(a["text_hint"]).classes("w-96") if a["needs_text"] else None

            def do(a=a, note=note):
                job = RUNNER.get(wf)
                if job and job.thread and job.thread.is_alive():
                    ui.notify("流程執行中；請先暫停或等它停在閘門再做決定", type="warning"); return
                try:
                    out = apply_gate_action(wf, a, note.value if note else "")
                except (ValueError, KeyError) as exc:
                    ui.notify(str(exc), type="negative"); return
                ui.notify(f"已寫回設定：{a['label']}；自 {a['from_step']} 起重跑（{len(out['invalidated'])} 個步驟）。"
                          "按「開始／繼續」執行。", type="positive")
            ui.button(option_text(a["label"], lang()), on_click=do).props("outline color=primary no-caps")
    if card.get("manual"):
        ui.label(_("需要在程式外處理（處理後重新提供輸入）：", "Needs work outside the program (then provide the new input):")).classes("text-xs text-gray-500")
        for o in card["manual"]:
            ui.label(f"→ {option_text(o, lang())}").classes("text-sm text-gray-700")


async def _upload_payload(e) -> tuple[str, bytes]:
    """File name and bytes from a NiceGUI upload event (works with the 1.x/2.x and the 3.x event shapes)."""
    f = getattr(e, "file", None)
    if f is not None:
        data = f.read()
        if hasattr(data, "__await__"):
            data = await data
        return getattr(f, "name", "upload"), data
    content = getattr(e, "content", None)
    return getattr(e, "name", "upload"), (content.read() if content is not None else b"")


def _manual_upload_panel(wf: Workflow):
    """D-50: manual SDF upload with strict naming for compounds whose download failed or was blocked."""
    from ..docking.library import manual_upload_report, check_upload_name, MANUAL_DIR, NAMING_RULES
    from ..advisor import tx
    lib_dir = wf.dir / "screen" / "library"
    man = load_json(lib_dir / "library_manifest.json", {})
    names = sorted((man.get("entries") or {}).keys())
    if not names:
        return
    rep = manual_upload_report(names, lib_dir)
    failed = [n for n, r in (man.get("entries") or {}).items() if r.get("status") != "OK"]
    with ui.expansion(_("手動上傳結構（下載被阻擋時）", "Upload structures manually (when downloads are blocked)"),
                      value=bool(failed)).classes("w-full md20-card"):
        ui.label(tx(NAMING_RULES[0], lang())).classes("md20-why")
        if failed:
            ui.label(_("仍需結構：", "Still missing: ") + ", ".join(f"{n}.sdf" for n in failed[:40])).classes("text-sm")
        if rep["bad_name"] or rep["unmatched"]:
            ui.label(_("未使用（命名不符）：", "Not used (name does not match): ") + ", ".join(rep["bad_name"] + rep["unmatched"])).classes("text-sm text-negative")
        log = ui.column().classes("gap-0")

        async def got(e):
            fname, data = await _upload_payload(e)
            ok, why, save_as = check_upload_name(fname, names)
            with log:
                if not ok:
                    ui.label(f"{fname}: {_('已拒絕', 'Rejected')} — {tx(why, lang())}").classes("text-sm text-negative")
                    return
                d = lib_dir / MANUAL_DIR
                d.mkdir(parents=True, exist_ok=True)
                for old_f in d.glob("*"):               # one file per compound whatever its case on disk
                    if old_f.name.lower() == save_as.lower() and old_f.name != save_as:
                        old_f.replace(d / save_as)
                (d / save_as).write_bytes(data)
                ui.label(f"{fname}: {_('已接受', 'Accepted')}").classes("text-sm text-positive")
            # the library step is re-run so the new file is picked up (downloaded files are cached, not re-fetched)
            st = wf.state()
            for k in ("screen_library", "screen_docking", "screen_selection"):
                st["steps"].pop(k, None)
            from ..util import atomic_write_json
            atomic_write_json(st, wf.state_path)
        ui.upload(on_upload=got, multiple=True, auto_upload=True, label=_("選擇 .sdf 檔", "Choose .sdf files")).props("accept=.sdf flat bordered color=blue-grey-7").classes("w-full")


@ui.page("/wf/{project}/{name}")
def workflow_page(project: str, name: str):
    _header()
    if safe_name(project) != project or safe_name(name) != name or not (Path(STATE["projects_dir"]) / project / "project.json").is_file():
        ui.label(_("找不到這個專案或流程。", "Project or workflow not found.")).classes("text-negative"); return
    proj = Project(Path(STATE["projects_dir"]) / project)
    try:
        wf = Workflow.open(proj, name)          # never creates an empty workflow for a mistyped URL
    except FileNotFoundError:
        ui.label(f"找不到流程 {name}。").classes("text-negative"); return
    cfg = wf.cfg
    with ui.column().classes("w-full max-w-6xl mx-auto gap-3"):
        ui.label(f"{project} / {name}").classes("text-xl font-semibold")
        status = ui.label("").classes("text-lg")
        msg = ui.markdown("")
        confirm_box = ui.column().classes("w-full")
        confirm_sig = {"v": None}

        def render_confirm():
            stp = wf.state()["steps"].get("md_confirm") or {}
            sig = (stp.get("status"), stp.get("at"))
            if sig == confirm_sig["v"]:
                return
            confirm_sig["v"] = sig
            confirm_box.clear()
            if stp.get("status") != "NEEDS_HUMAN":
                return
            card = next((c for c in gate_cards(wf) if c["title"] == "confirm MD"), None)
            go = next((a for a in (card or {}).get("actions", []) if a["label"].startswith("進入分子動力學")), None)
            with confirm_box, ui.card().classes("w-full md20-card").style("border-left: 4px solid #2f6f9f"):
                ui.label(t("confirm_md_title", lang())).classes("md20-section")
                ui.label(_(stp.get("message", ""), "Docking and pose selection are complete. Check the selected poses in "
                           "the pose table, then decide whether to continue to molecular dynamics (building, "
                           "equilibration and production; this can take hours depending on the settings).")).classes("text-sm")

                def proceed():
                    job = RUNNER.get(wf)
                    if job and job.thread and job.thread.is_alive():
                        ui.notify(t("busy", lang()), type="warning"); return
                    if go:
                        apply_gate_action(wf, go)
                    _start(wf)
                    ui.notify(_("已確認，開始分子動力學。", "Confirmed; molecular dynamics is starting."), type="positive")
                with ui.row().classes("gap-2"):
                    ui.button(_("進入分子動力學", "Proceed to molecular dynamics"), on_click=proceed).props("color=primary no-caps")
                    ui.button(_("先改選姿勢", "Choose another pose first"),
                              on_click=lambda: ui.notify(_("在下方姿勢表點選要使用的姿勢，再按「進入分子動力學」。",
                                                           "Click the pose to use in the table below, then press Proceed."))
                              ).props("outline no-caps")
        with ui.row():
            ui.button(_("開始或繼續", "Start or continue"), on_click=lambda: _start(wf))
            ui.button(_("暫停（在下一個區段結束時）", "Pause (at the end of the next segment)"), on_click=lambda: (wf.project.dir / "PAUSE").touch()).props("outline")
            report_btn = ui.button(_("開啟報告", "Open report"),
                                   on_click=lambda: ui.navigate.to(f"/report/{project}/{name}?lang={lang()}", new_tab=True)).props("outline")
        steps = ui.table(columns=[{"name": k, "label": l, "field": k, "align": "left",
                                   **({"style": "white-space: normal; max-width: 560px"} if k == "message" else {})}
                                  for k, l in (("step", _("步驟", "Step")), ("status", _("狀態", "Status")), ("at", _("時間", "Time")),
                                               ("message", _("訊息", "Message")))],
                         rows=[], row_key="key").props("dense flat").classes("w-full md20-card")
        ui.label(_("對接姿勢（★ 推薦、✔ 已選；點選一列改用該姿勢，系統會從姿勢選擇之後重新執行）", "Docking poses (★ recommended, ✔ selected; click a row to use that pose, the run restarts from pose selection)")).classes("font-semibold")
        poses = ui.table(columns=[{"name": k, "label": l, "field": k, "align": "left"} for k, l in
                                  (("entry", _("配體", "Ligand")), ("rank", _("名次", "Rank")), ("score", _("分數（kcal mol⁻¹）", "Score (kcal mol⁻¹)")),
                                   ("cluster", _("叢集（大小）", "Cluster (size)")), ("contacts", _("接觸殘基數", "Contacts")),
                                   ("rmsd_ref", _("與晶體 RMSD（Å）", "RMSD to crystal (Å)")), ("md_screen", _("短模擬篩選", "Short-MD screen")),
                                   ("tag", ""))], rows=[], row_key="key").props("dense flat").classes("w-full md20-card")
        reason = ui.markdown("")

        def pick(e):
            row = e.args[1]
            job = RUNNER.get(wf)
            if job and job.thread and job.thread.is_alive():
                ui.notify("流程執行中；請先暫停再改選 pose（執行中改選會和背景執行緒互相覆寫狀態）", type="warning"); return
            set_pose_choice(wf, row["entry"], row["rank"])
            ui.notify(f"{row['entry']} 改用第 {row['rank']} 名 pose；按「開始／繼續」重新執行後續步驟")
        poses.on("rowClick", pick)
        # ---- WP13: gate cards / live curves / timeline / offline 3D -------------------------------------
        with ui.tabs().classes("w-full") as tabs:
            t_gate, t_screen, t_live, t_umb, t_time, t_3d = (ui.tab(_("閘門", "Gates")), ui.tab(_("篩選", "Screening")), ui.tab(_("即時曲線", "Live curves")),
                                                             ui.tab(_("傘狀採樣覆蓋", "Umbrella coverage")), ui.tab(_("時間軸", "Timeline")), ui.tab(_("3D 檢視", "3D view")))
        with ui.tab_panels(tabs, value=t_gate).classes("w-full"):
            with ui.tab_panel(t_gate):
                cards_box = ui.column().classes("w-full gap-2")
            with ui.tab_panel(t_screen):
                ui.label(_("高通量篩選（縮減搜尋的 Vina 分數，只用來剔除）。勾選要進入下一步的化合物，或直接點選排名圖的長條。", "High-throughput screen (reduced-search Vina scores, used only to discard). Tick the compounds to take forward, or click a bar in the ranking chart.") + " " + _(
                         "≈ 表示與第 1 名差距 < 1 kcal/mol，在 Vina 誤差內、名次沒有統計意義。",
                         "≈ marks a gap below 1 kcal/mol to the best compound: within Vina's error, the order is not meaningful.")).classes("text-sm")
                scr_info = ui.label("").classes("text-sm")
                ch_rank = ui.echart(echart_ranking([], lang=lang())).classes("w-full h-96")
                ch_scr = ui.echart(echart_screen([])).classes("w-full h-80")
                scr_tbl = ui.table(columns=[{"name": k, "label": l, "field": k, "sortable": True} for k, l in
                                            (("rank", "名次"), ("name", "化合物"), ("score", "score"), ("delta_to_best", "Δ最佳"),
                                             ("heavy_atoms", "重原子"), ("ligand_efficiency", "LE"), ("cluster_size", "cluster"),
                                             ("contacts", "接觸"), ("recommendation_status", "推薦"), ("tag", ""))],
                                   rows=[], row_key="key", selection="multiple", pagination=25).classes("w-full")


                def bar_click(e):
                    data = getattr(e, "data", None)
                    nm = getattr(e, "name", None) or (data.get("name") if isinstance(data, dict) else None)
                    nm = str(nm or "").split("：")[0]
                    row = next((r for r in scr_tbl.rows if r.get("name") == nm), None)
                    if not row:
                        return
                    sel = [r for r in scr_tbl.selected if r.get("key") != row.get("key")]
                    if len(sel) == len(scr_tbl.selected):
                        sel.append(row)
                    scr_tbl.selected = sel
                    scr_tbl.update()
                    ui.notify(_(f"已選 {len(sel)} 個化合物", f"{len(sel)} compounds selected"))
                try:
                    ch_rank.on_point_click(bar_click)
                    ch_scr.on_point_click(bar_click)
                except AttributeError:      # older NiceGUI without point-click events: the table selection still works
                    pass
                with ui.row().classes("items-end gap-2"):
                    scr_note = ui.input(_("備註（為什麼選這些）", "Note (why these compounds)")).classes("w-72")

                    def do_select(mode: str):
                        job = RUNNER.get(wf)
                        if job and job.thread and job.thread.is_alive():
                            ui.notify("流程執行中；請先暫停再選擇", type="warning"); return
                        names = [r["name"] for r in scr_tbl.selected]
                        try:
                            out = select_screen_ligands(wf, names, mode, note=scr_note.value or "")
                        except ValueError as exc:
                            ui.notify(str(exc), type="negative"); return
                        ui.notify(f"已選 {len(out['selected'])} 個化合物（{mode}）；按「開始／繼續」進入正式對接與 MD", type="positive")
                    ui.button(_("各自對接後進入模擬", "Dock each, then simulate"), on_click=lambda: do_select("independent")).props("color=primary")
                    ui.button(_("多配體同時對接後進入模擬", "Dock together, then simulate"), on_click=lambda: do_select("simultaneous")).props("outline")
                _manual_upload_panel(wf)
            with ui.tab_panel(t_live):
                prog = ui.label("").classes("text-sm")
                bar = ui.linear_progress(value=0, show_value=False).classes("w-full")
                with ui.row().classes("w-full"):
                    ch_t = ui.echart(echart_options([], title=_("溫度", "Temperature"), x=_("步", "step"), y="K")).classes("w-[48%] h-60")
                    ch_e = ui.echart(echart_options([], title=_("位能", "Potential energy"), x=_("步", "step"), y="kJ mol⁻¹")).classes("w-[48%] h-60")
                with ui.row().classes("w-full"):
                    ch_f = ui.echart(echart_options([], title=_("SMD 拉力", "SMD force"), x="r (nm)", y="kJ mol⁻¹ nm⁻¹")).classes("w-[48%] h-60")
                    ch_w = ui.echart(echart_options([], title=_("SMD 功", "SMD work"), x="r (nm)", y="kJ mol⁻¹")).classes("w-[48%] h-60")
            with ui.tab_panel(t_umb):
                ui.label("每個 window 的取樣分佈（細線）與合併樣本（面積）；紅色 = 斷點，PMF 在那裡不可信。"
                         "自動補窗會由大缺口到小缺口補齊；若你看到想補的區間，輸入範圍後按「補採樣」。").classes("text-sm")
                cov_pick = ui.select({}, label="結合目標").classes("w-96")
                cov_info = ui.label("").classes("text-sm")
                ch_cov = ui.echart(coverage_chart({})).classes("w-full h-80")
                with ui.row().classes("items-end gap-2"):
                    rs_lo = ui.number("從 (nm)", step=0.01, format="%.3f").classes("w-32")
                    rs_hi = ui.number("到 (nm)", step=0.01, format="%.3f").classes("w-32")
                    rs_k = ui.number("k（選填，kJ/mol/nm²）", step=100).classes("w-48")
                    rs_note = ui.input("備註（為什麼補這段）").classes("w-72")

                    def do_resample():
                        job = RUNNER.get(wf)
                        if job and job.thread and job.thread.is_alive():
                            ui.notify("流程執行中；請先暫停再補採樣", type="warning"); return
                        if not cov_pick.value or rs_lo.value is None or rs_hi.value is None:
                            ui.notify("請選擇結合目標並輸入範圍", type="warning"); return
                        target = cov_pick.value.split("|")[0]
                        try:
                            out = resample_range(wf, target, float(rs_lo.value), float(rs_hi.value),
                                                 k=float(rs_k.value) if rs_k.value else None, note=rs_note.value or "")
                        except ValueError as exc:
                            ui.notify(str(exc), type="negative"); return
                        ui.notify(f"{target}：在此區間新增 {len(out['windows'])} 個 window（k {out['k']:.0f}、間距 "
                                  f"{out['spacing_nm']:.3f} nm）；按「開始／繼續」執行，已完成的 window 不重跑。", type="positive")
                    ui.button(_("補採樣", "Add windows"), on_click=do_resample).props("color=primary")
            with ui.tab_panel(t_time):
                time_box = ui.column().classes("w-full gap-1")
            with ui.tab_panel(t_3d):
                targets = viewer_targets(wf)
                if not targets:
                    ui.label(_("建模完成後即可檢視 3D 結構；正式模擬完成後可播放軌跡。", "The 3D structure appears after building; the trajectory plays after production.")).classes("text-gray-500")
                else:
                    pick3d = ui.select({i: t["label"] for i, t in enumerate(targets)}, value=0, label="結構").classes("w-96")
                    frame = ui.html("").classes("w-full")

                    def show3d():
                        frame.set_content(f'<iframe src="/viewer?project={project}&name={name}&i={pick3d.value}" '
                                          'style="width:100%;height:560px;border:0"></iframe>')
                    pick3d.on_value_change(lambda _: show3d())
                    show3d()
        cards_sig = {"v": None}
        scr_sig = {"v": None}
        cov_sig = {"v": None}
        time_sig = {"v": None}

        def refresh():
            job = RUNNER.get(wf)
            snap = job.snapshot() if job else {"status": "IDLE", "message": "", "steps": __import__("md20.gui.logic", fromlist=["step_rows"]).step_rows(wf.state()), "history": []}
            status.set_text(_("狀態：", "Status: ") + STATUS_TEXT.get(str(snap['status']), (str(snap['status']),) * 2)[0 if lang() == "zh" else 1])
            render_confirm()
            msg.set_content(f"```\n{snap['message']}\n```" if snap["message"] else "")
            L = lang()
            steps.rows = [{**r, "step": (STEP_TEXT.get(r.get("key"), (r["step"], r["step"]))[0 if L == "zh" else 1]),
                           "status": STATUS_TEXT.get(r["status"], (r["status"], r["status"]))[0 if L == "zh" else 1],
                           "at": (r.get("at") or "").replace("T", " ")[:19]} for r in snap["steps"]]
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
            tg = coverage_targets(wf)
            opts = {f"{t['target']}|{t['dir']}": t["label"] for t in tg}
            if opts != cov_pick.options:
                cov_pick.set_options(opts, value=cov_pick.value if cov_pick.value in opts else (next(iter(opts), None)))
            if cov_pick.value:
                cov = load_json(Path(cov_pick.value.split("|", 1)[1]) / "coverage.json", {})
                if cov.get("updated_at") != cov_sig["v"]:
                    cov_sig["v"] = cov.get("updated_at")
                    ch_cov.options.clear(); ch_cov.options.update(coverage_chart(cov)); ch_cov.update()
                    cov_info.set_text(coverage_summary(cov))
            srows = screen_table(wf)
            if len(srows) != scr_sig["v"]:
                scr_sig["v"] = len(srows)
                scr_tbl.rows = srows
                ch_scr.options.clear(); ch_scr.options.update(echart_screen(srows)); ch_scr.update()
                ch_rank.options.clear(); ch_rank.options.update(echart_ranking(srows, lang=lang())); ch_rank.update()
                sd = wf.state()["steps"].get("screen_docking") or {}
                scr_info.set_text(f"{len(srows)} 個化合物有分數；{len(sd.get('failed') or [])} 個失敗／略過（見閘門與報告）。" if srows else
                                  "尚無篩選結果（config 的 screen.library 指定化合物庫後執行）。")
            cards = gate_cards(wf)
            if cards != cards_sig["v"]:
                cards_sig["v"] = cards
                cards_box.clear()
                with cards_box:
                    if not cards:
                        ui.label(_("目前沒有需要注意的閘門。", "No gates need attention.")).classes("text-gray-500")
                    for c in cards:
                        with ui.card().classes("w-full"):
                            with ui.row().classes("items-center gap-2"):
                                ui.badge(card_badge(c), color="blue-grey-6" if c.get("advisory") else c["color"])
                                ui.label(f"{card_source(c['source'])} · {gate_title(c['title'], lang())}").classes("font-semibold")
                            if lang() == "en" and gate_general(c["title"]):
                                # D-55: general English explanation; the recorded detail (Chinese, with this run's numbers) below
                                ui.label(gate_general(c["title"])).classes("text-sm")
                                if c["explanation"]:
                                    with ui.expansion("Details (recorded in Chinese)").classes("w-full text-xs"):
                                        ui.label(c["explanation"]).classes("text-xs whitespace-pre-wrap")
                            else:
                                ui.label(c["explanation"]).classes("text-sm whitespace-pre-wrap")
                            if c["status"] != "NEEDS_HUMAN" and not c.get("advisory"):
                                for o in c["options"]:
                                    ui.label(f"→ {option_text(o, lang())}").classes("text-sm text-primary")
                            _gate_buttons(wf, c)
            tl = timeline(wf, limit=120)
            if len(tl) != time_sig["v"]:
                time_sig["v"] = len(tl)
                time_box.clear()
                with time_box:
                    for e in reversed(tl):
                        with ui.row().classes("w-full items-start gap-2"):
                            ui.label(e["at"][11:19]).classes("text-xs text-gray-500 w-16")
                            ui.badge(_("人工", "Manual") if e["status"] == "human" else (_("步驟", "Step") if e["kind"] == "step" else _("自動", "Automatic")),
                                     color="negative" if e["status"] in ("human", "NEEDS_HUMAN") else
                                     ("primary" if e["kind"] == "step" else "grey"))
                            with ui.column().classes("gap-0"):
                                ui.label(e["title"]).classes("text-sm font-semibold")
                                if e["text"]:
                                    ui.label(e["text"]).classes("text-xs whitespace-pre-wrap")
            report_btn.set_visibility(bool(wf.state()["steps"].get("docking") or wf.state()["steps"].get("md_cases")))
        ui.timer(2.0, refresh)
        refresh()


@app.get("/viewer")
def serve_viewer(project: str, name: str, i: int = 0):
    """Offline 3D viewer page (inline JS, no CDN) for one case of a workflow."""
    from fastapi.responses import HTMLResponse
    if safe_name(project) != project or safe_name(name) != name:
        return HTMLResponse("not allowed", status_code=403)
    proj = Project(Path(STATE["projects_dir"]) / project)
    try:
        wf = Workflow.open(proj, name)
    except FileNotFoundError:
        return HTMLResponse("not found", status_code=404)
    targets = viewer_targets(wf)
    if not 0 <= i < len(targets):
        return HTMLResponse("沒有可檢視的結構", status_code=404)
    try:
        return HTMLResponse(viewer_html(scene_for(targets[i]), title=targets[i]["label"]))
    except Exception as exc:  # noqa: BLE001
        return HTMLResponse(f"無法產生 3D 場景：{type(exc).__name__}: {exc}", status_code=500)


@app.get("/report/{project}/{name}")
def serve_report(project: str, name: str, lang: str = "en"):
    """Workflow report in the requested language (D-52); rebuilt from the workflow files on every request."""
    from fastapi.responses import HTMLResponse
    if safe_name(project) != project or safe_name(name) != name:
        return HTMLResponse("not allowed", status_code=403)
    try:
        wf = Workflow.open(Project(Path(STATE["projects_dir"]) / project), name)
    except FileNotFoundError:
        return HTMLResponse("not found", status_code=404)
    from ..report.workflow_report import build_workflow_report
    code = lang if lang in ("en", "zh") else "en"
    try:
        p = build_workflow_report(wf, wf.dir / f"workflow_report_{code}.html", lang=code)
    except Exception as exc:  # noqa: BLE001
        return HTMLResponse(f"report failed: {type(exc).__name__}: {exc}", status_code=500)
    return HTMLResponse(p.read_text(encoding="utf-8"))


@app.get("/file")
def serve_file(path: str):
    from fastapi.responses import FileResponse, HTMLResponse
    p = Path(path).resolve()
    root = Path(STATE["projects_dir"]).resolve()
    if root not in p.parents or not p.is_file():
        return HTMLResponse("not allowed", status_code=403)
    return FileResponse(p)


from . import pages_v2  # noqa: E402,F401  (registers the v2 pages: home, teaching, quick and pro forms)


def main(projects_dir: str | None = None, port: int = 8020, show: bool = True, host: str = "127.0.0.1"):
    """Local-only by default: NiceGUI would otherwise listen on 0.0.0.0, and on a classroom Wi-Fi anyone could open
    another student's GUI, start/pause runs, rewrite config and download project files.  `--host 0.0.0.0` opts in."""
    if projects_dir:
        STATE["projects_dir"] = Path(projects_dir)
        STATE["lang"] = None
    Path(STATE["projects_dir"]).mkdir(parents=True, exist_ok=True)
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"注意：GUI 對外開放於 {host}:{port}——同一網路上的任何人都能操作此工作站與下載專案檔。", flush=True)
    ui.run(title="MD20", host=host, port=port, show=show, reload=False, language="zh-TW" if lang() == "zh" else "en-US")
