"""GUI v2 pages (D-51): home with four modes, teaching pages, quick and professional forms.

Thin NiceGUI layer: content and logic come from md20.gui.content, md20.gui.logic and md20.advisor (all tested
without NiceGUI).  Registered by importing this module from md20.gui.app.
"""
from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path

from nicegui import app, ui

from .. import advisor
from ..advisor import tx, PARAMS, QUICK_KEYS, GOALS, GROUPS, GROUP_ORDER
from ..i18n import paren, colon as colon_
from ..project import Project
from ..util import load_json, safe_name, atomic_write_json
from ..workflow import Workflow
from .app import STATE, RUNNER, lang, _, _header, _start, _upload_payload
from .content import t, MODES, TEACHING, teaching_config
from .logic import config_from_mode, list_workflows, parse_ligand_lines
from . import advanced as A
from ..i18n import pick

LEVEL_STYLE = {"error": ("negative", "level_error"), "warning": ("warning", "level_warning"), "info": ("grey-7", "level_info")}


def _uploads_dir() -> Path:
    d = Path(STATE["projects_dir"]) / "_uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _project(name: str) -> Project:
    root = Path(STATE["projects_dir"]) / safe_name(name)
    return Project(root) if (root / "project.json").is_file() else Project.create(STATE["projects_dir"], name)


def unique_workflow_name(project_dir: Path, name: str) -> str:
    """Never overwrite an existing workflow (its config.json carries the user's decisions): add _2, _3 …"""
    base = safe_name(name or "workflow")
    cand, i = base, 2
    while (Path(project_dir) / "workflows" / cand).exists():
        cand, i = f"{base}_{i}", i + 1
    return cand


def _doctor_dict() -> dict:
    rep = STATE.get("doctor")
    if rep is None:
        return {}
    plat = getattr(rep, "platform", None)
    return {"benchmark": getattr(rep, "benchmark", None) or {},
            "platform": {"name": getattr(plat, "name", None)} if plat is not None else None}


# --------------------------------------------------------------------------------------------- home
@ui.page("/")
def home():
    L = lang()
    _header()
    with ui.column().classes("w-full max-w-6xl mx-auto gap-4 p-4"):
        ui.label(t("app_title", L)).classes("text-2xl md20-title")
        ui.label(t("home_intro", L)).classes("md20-muted max-w-4xl")
        ui.label(t("choose_mode", L)).classes("md20-section")
        with ui.grid(columns=2).classes("w-full gap-4"):
            for key in ("teach_small", "teach_peptide", "quick", "pro"):
                m = MODES[key]
                with ui.card().classes("md20-card md20-mode p-4").on("click", lambda r=m["route"]: ui.navigate.to(r)):
                    ui.label(tx(m["title"], L)).classes("text-lg font-semibold")
                    ui.label(tx(m["text"], L)).classes("text-sm md20-muted")
                    ui.button(t("open", L), on_click=lambda r=m["route"]: ui.navigate.to(r)).props("flat no-caps color=primary")
        ui.label(t("recent", L)).classes("md20-section")
        rows = list_workflows(Path(STATE["projects_dir"]))
        if not rows:
            ui.label(t("no_recent", L)).classes("md20-muted")
        else:
            cols = [{"name": "project", "label": t("project_name", L), "field": "project", "align": "left"},
                    {"name": "workflow", "label": t("workflow_name", L), "field": "workflow", "align": "left"},
                    {"name": "last_step", "label": t("step", L), "field": "last_step", "align": "left"},
                    {"name": "status", "label": t("status", L), "field": "status", "align": "left"},
                    {"name": "updated", "label": t("time", L), "field": "updated", "align": "left"}]
            from .app import STEP_TEXT, STATUS_TEXT, no_data
            from ..i18n import pick
            shown = [{**r, "key": f"{r['project']}/{r['workflow']}",
                      "last_step": pick(STEP_TEXT[r["last_step"]], L) if r["last_step"] in STEP_TEXT else r["last_step"],
                      "status": pick(STATUS_TEXT[r["status"]], L) if r["status"] in STATUS_TEXT else r["status"]}
                     for r in rows[-20:][::-1]]
            tbl = ui.table(columns=cols, rows=shown, row_key="key").props(no_data()).classes("w-full md20-card")
            tbl.on("rowClick", lambda e: ui.navigate.to(f"/wf/{e.args[1]['project']}/{e.args[1]['workflow']}"))


# --------------------------------------------------------------------------------------------- teaching
@ui.page("/teach/{case}")
def teach(case: str):
    L = lang()
    _header()
    if case not in TEACHING:
        ui.label("not found"); return
    from ..validation import CASES
    c, paper = TEACHING[case], CASES[case].PAPER
    cfg = teaching_config(case, lang=L)
    f = advisor.features_from_config(cfg)
    with ui.column().classes("w-full max-w-5xl mx-auto gap-3 p-4"):
        ui.label(t("teaching_mode", L)).classes("md20-muted")
        ui.label(tx(c["title"], L)).classes("text-2xl md20-title")
        with ui.card().classes("w-full md20-card p-4"):
            ui.label(t("paper", L)).classes("md20-section")
            ui.label(paper["citation"]).classes("text-sm")
            ui.label(t("background", L)).classes("md20-section")
            ui.label(tx(c["background"], L)).classes("text-sm leading-relaxed")
        with ui.row().classes("w-full gap-3 no-wrap items-stretch"):
            with ui.card().classes("w-1/2 md20-card p-4"):
                ui.label(t("objectives", L)).classes("md20-section")
                for i, o in enumerate(c["objectives"], 1):
                    ui.label(f"{i}. {tx(o, L)}").classes("text-sm")
            with ui.card().classes("w-1/2 md20-card p-4"):
                ui.label(t("what_md20_shows", L)).classes("md20-section")
                for o in c["checks"]:
                    ui.label("• " + tx(o, L)).classes("text-sm")
        with ui.card().classes("w-full md20-card p-4"):
            ui.label(t("stages", L)).classes("md20-section")
            for i, (title, text) in enumerate(c["stages"], 1):
                with ui.row().classes("items-baseline gap-2 no-wrap"):
                    ui.label(f"{i}").classes("text-primary font-semibold w-5")
                    ui.label(tx(title, L)).classes("font-medium w-56")
                    ui.label(tx(text, L)).classes("text-sm md20-muted")
        with ui.card().classes("w-full md20-card p-4"):
            ui.label(t("teach_params", L)).classes("md20-section")
            vals = advisor.values_from_config(cfg)
            from ..validation import CASES as _C
            paper_vals = advisor.values_from_config(_C[case].workflow_config(tier="classroom"))
            rows = teaching_rows(vals, paper_vals, f, L)
            ui.table(columns=[{"name": "label", "label": t("parameters", L), "field": "label", "align": "left"},
                              {"name": "value_text", "label": t("value", L), "field": "value_text", "align": "left"},
                              {"name": "why", "label": t("reason", L), "field": "why", "align": "left",
                               "style": "white-space: normal; max-width: 520px"}],
                     rows=[{**r, "key": r["key"]} for r in rows], row_key="key").props("dense flat").classes("w-full")
        with ui.card().classes("w-full md20-card p-4"):
            ui.label(t("discussion", L)).classes("md20-section")
            for i, q in enumerate(c["discussion"], 1):
                ui.label(f"{i}. {tx(q, L)}").classes("text-sm")

        def start():
            proj = _project("Teaching")       # D-67: one folder whatever the interface language (a switch restarted the lesson)
            if (proj.dir / "workflows" / safe_name(cfg["name"]) / "config.json").is_file():
                # the lesson already exists: continue it instead of overwriting its decisions
                wf = Workflow.open(proj, cfg["name"])
                ui.notify(_("這個教學案例已經建立過，會接著原本的流程。", "This lesson already exists. Continuing it.",
                            "この教材はすでに作成済みです。元のワークフローを続けます。", "이 교육 사례는 이미 만들어져 있습니다. 기존 워크플로를 이어 갑니다."))
            else:
                wf = Workflow(proj, cfg)
            job = _start(wf)
            if job.wf.dir != wf.dir:
                ui.notify(_("已有另一個計算在進行。同一時間只跑一個，先帶你回到它。",
                            "Another calculation is running. Only one runs at a time, so this takes you to it.",
                            "別の計算が実行中です。同時に動かせるのは一つだけなので、そちらに移動します。",
                            "다른 계산이 실행 중입니다. 한 번에 하나만 실행하므로 그 계산으로 이동합니다."), type="warning")
            ui.navigate.to(f"/wf/{job.wf.project.dir.name}/{job.wf.name}")
        ui.button(t("start_lesson", L), on_click=start).props("color=primary no-caps size=lg data-testid=start-lesson")


def teaching_rows(vals: dict, paper_vals: dict, f, L: str) -> list[dict]:
    """Parameter table of a teaching case: values the paper fixed are labelled as such (with the recommendation next to
    them), and binding parameters are left out when the lesson does not compute binding."""
    rows = []
    for r in advisor.parameter_table(vals, f, "teaching", L):
        if r["group_key"] == "binding" and r["key"] != "binding" and not vals.get("binding"):
            continue
        if r["key"] == "exhaustiveness" and vals.get("docking_mode", vals.get("mode")) != "independent" and r["value"] == 8:
            r = {**r, "why": _("這個搜尋強度在一堂課內跑得完。論文用的是 32，六個配體同時對接在 RTX 4060 筆電上要超過 2 小時。研究等級會改回 32。",
                               "This exhaustiveness finishes within one class. The paper used 32, which takes over 2 h on an RTX 4060 "
                               "laptop for six ligands docked together. The research tier sets it back to 32.",
                               "この探索の徹底度（exhaustiveness）なら授業時間内に終わります。論文では 32 を使っており、6 つのリガンドを同時にドッキングすると "
                               "RTX 4060 のノートパソコンで 2 時間以上かかります。研究レベルでは 32 に戻します。",
                               "이 탐색 강도(exhaustiveness)는 수업 시간 안에 끝납니다. 논문은 32를 사용했으며, 리간드 여섯 개를 함께 도킹하면 "
                               "RTX 4060 노트북에서 2시간 넘게 걸립니다. 연구 등급에서는 32로 되돌립니다.")}
            rows.append(r); continue
        if r["key"] in paper_vals and r["value"] != r["recommended"]:
            rt, w = r["recommended_text"], r["why"]
            r = {**r, "why": _(f"依論文的設定。一般個案的建議值是 {rt}。{w}",
                               f"Taken from the paper. For a general case the recommendation is {rt}. {w}",
                               f"論文の設定に合わせています。一般的な事例での推奨値は {rt} です。{w}",
                               f"논문 설정을 따릅니다. 일반적인 사례의 권장값은 {rt}입니다. {w}")}
        rows.append(r)
    return rows


# --------------------------------------------------------------------------------------------- quick and pro forms
@ui.page("/new")
def new_default():
    _form("quick")


@ui.page("/new/{mode}")
def new_mode(mode: str, expand: str = ""):
    # ?expand=all opens every parameter group (tools/gui_preview.py screenshots the membrane and folding groups)
    _form("pro" if mode == "pro" else "quick", expand_all=(expand == "all"))


def _fold_engines() -> dict:
    """Installed folding tools, probed once per GUI process (nvidia-smi and PATH lookups)."""
    if "fold_engines" not in STATE:
        try:
            from ..build.fold import fold_status
            STATE["fold_engines"] = fold_status().get("engines") or {}
        except Exception:  # noqa: BLE001 — unknown: the form then says nothing about the tools
            STATE["fold_engines"] = {}
    return STATE["fold_engines"]


def _widget(key: str, value, L: str, on_change):
    p = PARAMS[key]
    label = advisor.param_label(key, L) + (paren(p["unit"], L) if p["unit"] else "")
    if p["type"] == "choice":
        return ui.select({k: tx(v, L) for k, v in p["choices"].items()}, value=value, label=label,
                         on_change=on_change).classes("w-full")
    if p["type"] == "bool":
        return ui.switch(label, value=bool(value), on_change=on_change)
    fmt = "%.0f" if p["type"] == "int" else None
    kw = {"min": p.get("min"), "max": p.get("max"), "step": p.get("step", 1 if p["type"] == "int" else 0.1)}
    if fmt:
        kw["format"] = fmt
    return ui.number(label, value=value, on_change=on_change, **{k: v for k, v in kw.items() if v is not None}).classes("w-full")


def _form(mode: str, expand_all: bool = False):
    L = lang()
    _header()
    pro = mode == "pro"
    state = {"goal": "teaching", "touched": set(), "updating": False, "receptor_file": "", "receptor_text": None,
             "library_file": "", "adv": A.defaults(), "quick_fold": set(), "quick_peps": None}
    widgets: dict = {}
    why_labels: dict = {}
    rec_labels: dict = {}

    with ui.column().classes("w-full max-w-6xl mx-auto gap-3 p-4"):
        ui.label(tx(MODES[mode]["title"], L)).classes("text-2xl md20-title")
        ui.label(tx(MODES[mode]["text"], L)).classes("md20-muted max-w-4xl")
        with ui.row().classes("w-full gap-4 no-wrap items-start"):
            left = ui.column().classes("w-2/3 gap-3")
            right = ui.column().classes("w-1/3 gap-3 sticky top-16")

    with left:
        with ui.card().classes("w-full md20-card p-4"):
            with ui.row().classes("w-full gap-3 no-wrap"):
                project = ui.input(t("project_name", L), value="Projects").classes("w-1/2")      # D-67: ASCII project names
                name = ui.input(t("workflow_name", L), value="workflow_1").classes("w-1/2")
            goal = ui.select({k: tx(v, L) for k, v in GOALS.items()}, value="teaching", label=t("goal", L)).classes("w-full")
        with ui.card().classes("w-full md20-card p-4"):
            ui.label(t("receptor", L)).classes("md20-section")
            with ui.row().classes("w-full gap-3 no-wrap items-end"):
                pdb_id = ui.input(t("pdb_id", L)).props("clearable").classes("w-40")
                ph = ui.number(t("ph", L), value=7.4, min=0, max=14, step=0.1).classes("w-24")
                keep = ui.input(t("keep_hetero", L)).classes("flex-grow")
            rec_info = ui.label("").classes("md20-why")

            async def got_receptor(e):
                fname, data = await _upload_payload(e)
                if Path(fname).suffix.lower() not in (".pdb", ".ent", ".cif", ".mmcif"):
                    ui.notify(_("只接受 PDB 或 mmCIF 檔。", "Only PDB or mmCIF files are accepted.", "PDB か mmCIF のファイルだけを受け付けます。",
                                "PDB 또는 mmCIF 파일만 받습니다."), type="negative"); return
                dst = _uploads_dir() / f"{uuid.uuid4().hex[:8]}_{safe_name(Path(fname).stem)}{Path(fname).suffix.lower()}"
                dst.write_bytes(data)
                state["receptor_file"] = str(dst)
                state["receptor_text"] = data.decode("utf-8", errors="ignore") if dst.suffix in (".pdb", ".ent") else None
                rec_info.set_text(_("已上傳：", "Uploaded: ", "アップロード済み：", "업로드됨: ") + fname)
                refresh()
            ui.upload(on_upload=got_receptor, auto_upload=True, max_files=1, label=t("or_upload", L)).props("accept=.pdb,.ent,.cif,.mmcif flat bordered color=blue-grey-7").classes("w-full")
        with ui.card().classes("w-full md20-card p-4"):
            ui.label(t("ligands", L)).classes("md20-section")
            ui.label(t("ligand_help", L)).classes("md20-why")
            ligs = ui.textarea(placeholder="LIG  CC(=O)Nc1ccc(O)cc1\nPEP  peptide:GGGGGKP").props("autogrow").classes("w-full font-mono")
            lig_err = ui.label("").classes("text-sm text-negative")
            qf_box = ui.row().classes("w-full gap-3 items-center")       # quick mode: "fold this peptide" per peptide
            ligs.on("blur", lambda: refresh())
            ui.label(t("site", L)).classes("md20-section")
            with ui.row().classes("w-full gap-3 no-wrap"):
                box_res = ui.input(t("site_residue", L)).classes("w-1/3")
                box_c = ui.input(t("site_center", L)).classes("w-1/3")
                box_s = ui.input(t("site_size", L), value="22, 22, 22").classes("w-1/3")
            ui.label(t("site_note", L)).classes("md20-why")
            for w in (box_res, box_c, box_s):
                w.on("blur", lambda: refresh())
            systems = ui.select({"apo": t("sys_apo", L), "docked_single": t("sys_single", L), "docked_multi": t("sys_multi", L)},
                                value=["apo", "docked_single"], multiple=True, label=t("systems", L)).classes("w-full")
        with ui.card().classes("w-full md20-card p-4"):
            ui.label(t("hts", L)).classes("md20-section")
            ui.label(t("hts_help", L)).classes("md20-why")
            lib_info = ui.label("").classes("text-sm")
            with ui.row().classes("items-center gap-3"):
                ui.button(t("hts_template", L), on_click=lambda: ui.navigate.to("/template/compound_library.xlsx", new_tab=True)).props("outline no-caps")

                async def got_library(e):
                    fname, data = await _upload_payload(e)
                    if Path(fname).suffix.lower() not in (".xlsx", ".xls", ".csv"):
                        ui.notify(_("只接受 Excel 或 CSV 檔。", "Only Excel or CSV files are accepted.", "Excel か CSV のファイルだけを受け付けます。",
                                    "Excel 또는 CSV 파일만 받습니다."), type="negative"); return
                    dst = _uploads_dir() / f"{uuid.uuid4().hex[:8]}_{safe_name(Path(fname).stem)}{Path(fname).suffix.lower()}"
                    dst.write_bytes(data)
                    try:
                        from ..docking.library import read_library
                        entries, warns = read_library(dst)
                    except Exception as exc:  # noqa: BLE001
                        ui.notify(_("表格無法讀取：", "The table could not be read: ", "表を読み込めませんでした：", "표를 읽을 수 없습니다: ")
                                  + str(exc), type="negative"); return
                    state["library_file"] = str(dst)
                    ne, nw = len(entries), len(warns)
                    lib_info.set_text(_(f"已上傳 {fname}，共 {ne} 個化合物", f"Uploaded {fname} with {ne} compounds",
                                        f"{fname} をアップロードしました（化合物 {ne} 個）", f"{fname} 업로드됨, 화합물 {ne}개")
                                      + (_(f"，{nw} 則提醒", f", {nw} notes", f"、注意 {nw} 件", f", 알림 {nw}건") if warns else ""))
                ui.upload(on_upload=got_library, auto_upload=True, max_files=1, label=t("hts_upload", L)).props("accept=.xlsx,.xls,.csv flat bordered color=blue-grey-7")

        # ------------------------------------------------------------------ parameters
        ui.label(t("parameters", L)).classes("md20-section")
        with ui.row().classes("items-center gap-2"):
            ui.button(t("reset_rec", L), on_click=lambda: reset_all()).props("outline no-caps size=sm")
        keys = list(PARAMS) if pro else QUICK_KEYS
        param_box = ui.column().classes("w-full gap-2")
        adv_box = ui.column().classes("w-full gap-2")

    with right:
        with ui.card().classes("w-full md20-card p-4"):
            ui.label(t("checks", L)).classes("md20-section")
            checks_box = ui.column().classes("w-full gap-2")
        with ui.card().classes("w-full md20-card p-4"):
            ui.label(t("estimate", L)).classes("md20-section")
            est_label = ui.label("").classes("text-sm")
        with ui.card().classes("w-full md20-card p-4").props("data-testid=long-run") as lr_card:
            ui.label(A.tx("long_run", L)).classes("md20-section")
            lr_lines = ui.column().classes("w-full gap-1")
            lr_confirm = ui.checkbox(A.tx("long_run_confirm", L), value=False,
                                     on_change=lambda e: (state["adv"].__setitem__("long_run_confirmed", bool(e.value)), refresh()))
            lr_note = ui.label(A.tx("long_run_note", L)).classes("md20-why")
        lr_card.set_visibility(False)
        err = ui.label("").classes("text-negative text-sm")
        create_btn = ui.button(t("create_start", L), on_click=lambda: create()).props("color=primary no-caps size=lg").classes("w-full")

    # ---------------------------------------------------------------------- behaviour
    def draft_cfg() -> dict:
        try:
            parsed = parse_ligand_lines(ligs.value or "", L)
            lig_err.set_text("")
        except ValueError as exc:
            parsed = []
            lig_err.set_text(str(exc))
        box = {}
        if (box_res.value or "").strip():
            box = {"from_residue": box_res.value.strip().upper()}
        elif (box_c.value or "").strip():
            try:
                box = {"center": [float(x) for x in box_c.value.split(",")], "size": [float(x) for x in (box_s.value or "22,22,22").split(",")]}
            except ValueError:
                box = {}
        return {"ligands": parsed, "keep_hetero": (keep.value or "").split(), "box": box,
                "docking": {"mode": (widgets.get("docking_mode").value if widgets.get("docking_mode") else "independent")}}

    def features():
        return advisor.features_from_config(draft_cfg(), receptor_text=state["receptor_text"], doctor=_doctor_dict())

    def current_values(f) -> dict:
        rec = advisor.recommended_values(f, state["goal"])
        out = dict(rec)
        for k, w in widgets.items():
            if k in state["touched"]:
                out[k] = w.value
        return out

    def on_change_factory(key):
        def h(e):
            if state["updating"]:
                return
            state["touched"].add(key)
            refresh()
        return h

    def build_params():
        param_box.clear()
        f = features()
        rec = advisor.recommend(f, state["goal"], L)
        with param_box:
            groups = GROUP_ORDER if pro else [None]
            for g in groups:
                ks = [k for k in keys if g is None or PARAMS[k]["group"] == g]
                if not ks:
                    continue
                ctx = ui.expansion(tx(GROUPS[g], L), value=expand_all or g in ("docking", "prod")).classes("w-full md20-card") if g else ui.card().classes("w-full md20-card p-4")
                with ctx:
                    for k in ks:
                        with ui.row().classes("w-full gap-3 no-wrap items-start py-1"):
                            with ui.column().classes("w-2/5 gap-0"):
                                widgets[k] = _widget(k, rec[k]["value"], L, on_change_factory(k))
                            with ui.column().classes("w-3/5 gap-0"):
                                rec_labels[k] = ui.label("").classes("md20-changed")
                                why_labels[k] = ui.label(rec[k]["why"]).classes("md20-why")

    def adv_set(key, cast=None):
        def h(e):
            state["adv"][key] = cast(e.value) if (cast and e.value is not None) else e.value
            refresh()
        return h

    def adv_row(widget_fn, help_key):
        with ui.row().classes("w-full gap-3 no-wrap items-start py-1"):
            with ui.column().classes("w-2/5 gap-0"):
                widget_fn()
            with ui.column().classes("w-3/5 gap-0"):
                if help_key:
                    ui.label(A.tx(help_key, L)).classes("md20-why")

    def build_advanced():
        """Professional mode: membrane and peptide-folding groups (gui/advanced.py writes them into the config)."""
        adv = state["adv"]
        adv_box.clear()
        with adv_box:
            with ui.expansion(A.tx("membrane", L), value=expand_all).classes("w-full md20-card").props("data-testid=group-membrane"):
                ui.label(A.tx("membrane_help", L)).classes("md20-why")
                adv_row(lambda: ui.select({k: pick(v, L) for k, v in A.MEMBRANE_TYPES.items()}, value=adv["membrane_type"],
                                          label=A.tx("membrane_type", L), on_change=adv_set("membrane_type")).classes("w-full"), None)
                adv_row(lambda: ui.select({k: pick(v, L) for k, v in A.LIPID_PRESETS.items()}, value=adv["lipids"],
                                          label=A.tx("lipids", L), on_change=adv_set("lipids")).classes("w-full"), "lipids_help")
                adv_row(lambda: ui.switch(A.tx("oriented", L), value=adv["oriented"], on_change=adv_set("oriented", bool)),
                        "oriented_help")
                adv_row(lambda: ui.number(A.tx("surface_distance", L) + paren("nm", L), value=adv["surface_distance_nm"],
                                          min=0.0, max=5.0, step=0.1, on_change=adv_set("surface_distance_nm", float)).classes("w-full"),
                        "surface_help")
            with ui.expansion(A.tx("fold", L), value=expand_all).classes("w-full md20-card").props("data-testid=group-fold"):
                ui.label(A.tx("fold_help", L)).classes("md20-why")
                adv_row(lambda: ui.select({k: pick(v, L) for k, v in A.FOLD_MODES.items()}, value=adv["fold"],
                                          label=A.tx("fold_mode", L), on_change=adv_set("fold")).classes("w-full"), None)
                adv_row(lambda: ui.select({k: pick(v, L) for k, v in A.FOLD_ENGINES.items()}, value=adv["fold_engine"],
                                          label=A.tx("fold_engine", L), on_change=adv_set("fold_engine")).classes("w-full"), None)

                def seq_widget():
                    w = ui.textarea(A.tx("fold_receptor_seq", L), value=adv["fold_receptor_seq"]).props("autogrow").classes("w-full font-mono")
                    w.on("blur", lambda: (adv.__setitem__("fold_receptor_seq", w.value or ""), refresh()))
                adv_row(seq_widget, "fold_receptor_help")
                up_info = ui.label("").classes("md20-why")

                async def got_fold(e):
                    fname, data = await _upload_payload(e)
                    if Path(fname).suffix.lower() not in (".pdb", ".cif", ".mmcif"):
                        ui.notify(_("只接受 PDB 或 mmCIF 檔。", "Only PDB or mmCIF files are accepted.", "PDB か mmCIF のファイルだけを受け付けます。",
                                    "PDB 또는 mmCIF 파일만 받습니다."), type="negative"); return
                    dst = _uploads_dir() / f"{uuid.uuid4().hex[:8]}_{safe_name(Path(fname).stem)}{Path(fname).suffix.lower()}"
                    dst.write_bytes(data)
                    adv["fold_upload"] = str(dst)
                    up_info.set_text(_("已上傳：", "Uploaded: ", "アップロード済み：", "업로드됨: ") + fname)
                    refresh()
                ui.upload(on_upload=got_fold, auto_upload=True, max_files=1, label=A.tx("fold_upload", L)).props(
                    "accept=.pdb,.cif,.mmcif flat bordered color=blue-grey-7").classes("w-full")

    def render_quick_fold(parsed):
        """Quick mode: one "fold this peptide" checkbox next to each peptide ligand."""
        names = A.peptide_names(parsed)
        if names == state["quick_peps"]:
            return
        state["quick_peps"] = names
        state["quick_fold"] &= set(names)
        qf_box.clear()
        with qf_box:
            for n in names:
                def toggle(e, n=n):
                    (state["quick_fold"].add if e.value else state["quick_fold"].discard)(n)
                    refresh()
                ui.checkbox(f"{n}" + colon_(L) + A.tx("quick_fold", L), value=n in state["quick_fold"],
                            on_change=toggle).props(f"data-testid=quick-fold-{n}")

    def adv_values(for_checks: bool = False) -> dict:
        """Pro: the whole group.  Quick: only the long-run confirmation; the ticked peptides go through quick_fold
        (for the checks they count as "fold before docking", so a missing folding tool is reported)."""
        if pro:
            return state["adv"]
        return {**A.defaults(), "fold": "dock" if (for_checks and state["quick_fold"]) else "off",
                "long_run_confirmed": state["adv"]["long_run_confirmed"]}

    def refresh():
        f = features()
        state["goal"] = goal.value or "teaching"
        rec = advisor.recommend(f, state["goal"], L)
        state["updating"] = True
        try:
            for k, w in widgets.items():
                if k not in state["touched"] and w.value != rec[k]["value"]:
                    w.value = rec[k]["value"]
                why_labels[k].set_text(rec[k]["why"])
                changed = k in state["touched"] and w.value != rec[k]["value"]
                rec_labels[k].set_text((t("changed", L) + " · " + t("recommended", L) + " " +
                                        advisor.format_value(k, rec[k]["value"], L)) if changed else "")
        finally:
            state["updating"] = False
        vals = current_values(f)
        issues = advisor.check(vals, f, goal=state["goal"], lang=L)
        draft = draft_cfg()
        if not pro:
            render_quick_fold(draft["ligands"])
        issues += A.advanced_checks(adv_values(for_checks=True), ligands=draft["ligands"],
                                    has_receptor=bool((pdb_id.value or "").strip() or state["receptor_file"]),
                                    binding=bool(vals.get("binding")), solvent=vals.get("solvent", "explicit"),
                                    production_ns=vals.get("production_ns"), fold_installed=_fold_engines(), lang=L)
        order = {"error": 0, "warning": 1, "info": 2}
        issues.sort(key=lambda i: order.get(i["level"], 3))
        lr = A.long_run_view(vals, f, state["goal"], L)
        lr_card.set_visibility(lr["show"])
        lr_lines.clear()
        with lr_lines:
            for line in lr["lines"]:
                ui.label(line).classes("text-sm")
        lr_confirm.set_visibility(lr["needs_confirm"])
        lr_note.set_visibility(lr["needs_confirm"])
        checks_box.clear()
        with checks_box:
            if not issues:
                ui.label(t("checks_ok", L)).classes("text-sm text-positive")
            for i in issues:
                color, lab = LEVEL_STYLE[i["level"]]
                with ui.column().classes("gap-0 w-full"):
                    with ui.row().classes("items-center gap-2"):
                        ui.badge(t(lab, L), color=color)
                        ui.label(i["label"]).classes("text-sm font-medium")
                    ui.label(i["message"]).classes("md20-why")
                    if i["suggestion"] is not None and i["key"] in widgets:
                        ui.button(t("use_suggestion", L) + ": " + advisor.format_value(i["key"], i["suggestion"], L),
                                  on_click=lambda k=i["key"], v=i["suggestion"]: apply_suggestion(k, v)).props("flat dense no-caps size=sm color=primary")
        est = advisor.estimate_hours(vals, f, state["goal"])
        est_label.set_text(t("estimate_none", L) if est.get("total_hours") is None else
                           t("estimate_text", L, total=est["total_hours"], md=est["md_hours"], bind=est["binding_hours"],
                             atoms=f"{est['atoms']:,}", speed=est["ns_per_day"]))
        has_error = any(i["level"] == "error" for i in issues)
        err.set_text(t("errors_block", L) if has_error else "")
        create_btn.set_enabled(not has_error)

    def apply_suggestion(k, v):
        state["touched"].add(k)
        state["updating"] = True
        widgets[k].value = v
        state["updating"] = False
        refresh()

    def reset_all():
        state["touched"].clear()
        refresh()

    goal.on_value_change(lambda e: refresh())

    def create():
        f = features()
        vals = current_values(f)
        try:
            cfg = config_from_mode(mode=mode, name=name.value, values=vals, pdb_id=pdb_id.value or "",
                                   receptor_file=state["receptor_file"], ligands_text=ligs.value or "",
                                   box_residue=box_res.value or "", box_center=box_c.value or "", box_size=box_s.value or "",
                                   systems=list(systems.value or []), ph=float(ph.value or 7.4), keep_hetero=keep.value or "",
                                   goal=state["goal"], library_file=Path(state["library_file"]).name if state["library_file"] else "",
                                   lang=L, advanced=adv_values(), quick_fold=set(state["quick_fold"]))
        except ValueError as exc:
            err.set_text(str(exc)); return
        proj = _project(project.value or "Projects")
        cfg["name"] = unique_workflow_name(proj.dir, cfg["name"])
        wf = Workflow(proj, cfg)
        if state["library_file"]:
            shutil.copy2(state["library_file"], wf.dir / Path(state["library_file"]).name)
        job = _start(wf)
        if job.wf.dir != wf.dir:
            btn = t("run_continue", L)
            ui.notify(_(f"已有另一個計算在進行。新流程已建立但還沒開始，等目前的計算結束後，到它的頁面按「{btn}」。",
                        f"Another calculation is running. The new workflow is created but not started. When the current one "
                        f"finishes, press {btn} on its page.",
                        f"別の計算が実行中です。新しいワークフローは作成しましたが、まだ始めていません。今の計算が終わったら、そのページで「{btn}」を押してください。",
                        f"다른 계산이 실행 중입니다. 새 워크플로는 만들었지만 아직 시작하지 않았습니다. 지금 계산이 끝나면 그 페이지에서 '{btn}'을 누르십시오."),
                      type="warning")
        ui.navigate.to(f"/wf/{job.wf.project.dir.name}/{job.wf.name}")

    build_params()
    if pro:
        build_advanced()
    refresh()


# --------------------------------------------------------------------------------------------- downloads
@app.get("/template/compound_library.xlsx")
def template_xlsx():
    from fastapi.responses import FileResponse
    from ..docking.library import write_template
    d = Path(tempfile.mkdtemp(prefix="md20tpl_"))
    p = write_template(d / "compound_library.xlsx")
    return FileResponse(p, filename="compound_library.xlsx")
