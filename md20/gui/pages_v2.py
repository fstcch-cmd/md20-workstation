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
from ..project import Project
from ..util import load_json, safe_name, atomic_write_json
from ..workflow import Workflow
from .app import STATE, RUNNER, lang, _, _header, _start, _upload_payload
from .content import t, MODES, TEACHING, teaching_config
from .logic import config_from_mode, list_workflows, parse_ligand_lines

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
            tbl = ui.table(columns=cols, rows=[{**r, "key": f"{r['project']}/{r['workflow']}"} for r in rows[-20:][::-1]],
                           row_key="key").classes("w-full md20-card")
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
            proj = _project("Teaching" if L == "en" else "教學")
            if (proj.dir / "workflows" / safe_name(cfg["name"]) / "config.json").is_file():
                # the lesson already exists: continue it instead of overwriting its decisions
                wf = Workflow.open(proj, cfg["name"])
                ui.notify(_("這個教學案例已經建立過，繼續原本的流程。", "This lesson already exists; continuing it."))
            else:
                wf = Workflow(proj, cfg)
            _start(wf)
            ui.navigate.to(f"/wf/{proj.dir.name}/{wf.name}")
        ui.button(t("start_lesson", L), on_click=start).props("color=primary no-caps size=lg")


def teaching_rows(vals: dict, paper_vals: dict, f, L: str) -> list[dict]:
    """Parameter table of a teaching case: values the paper fixed are labelled as such (with the recommendation next to
    them), and binding parameters are left out when the lesson does not compute binding."""
    rows = []
    for r in advisor.parameter_table(vals, f, "teaching", L):
        if r["group_key"] == "binding" and r["key"] != "binding" and not vals.get("binding"):
            continue
        if r["key"] in paper_vals and r["value"] != r["recommended"]:
            r = {**r, "why": _(f"依論文設定（系統對一般個案的建議為 {r['recommended_text']}：{r['why']}）",
                               f"Taken from the paper (for a general case the recommendation is {r['recommended_text']}: {r['why']})")}
        rows.append(r)
    return rows


# --------------------------------------------------------------------------------------------- quick and pro forms
@ui.page("/new")
def new_default():
    _form("quick")


@ui.page("/new/{mode}")
def new_mode(mode: str):
    _form("pro" if mode == "pro" else "quick")


def _widget(key: str, value, L: str, on_change):
    p = PARAMS[key]
    label = advisor.param_label(key, L) + (f"（{p['unit']}）" if (p["unit"] and L == "zh") else (f" ({p['unit']})" if p["unit"] else ""))
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


def _form(mode: str):
    L = lang()
    _header()
    pro = mode == "pro"
    state = {"goal": "teaching", "touched": set(), "updating": False, "receptor_file": "", "receptor_text": None,
             "library_file": ""}
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
                project = ui.input(t("project_name", L), value="Projects" if L == "en" else "專案").classes("w-1/2")
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
                    ui.notify(_("只接受 PDB 或 mmCIF 檔。", "Only PDB or mmCIF files are accepted."), type="negative"); return
                dst = _uploads_dir() / f"{uuid.uuid4().hex[:8]}_{safe_name(Path(fname).stem)}{Path(fname).suffix.lower()}"
                dst.write_bytes(data)
                state["receptor_file"] = str(dst)
                state["receptor_text"] = data.decode("utf-8", errors="ignore") if dst.suffix in (".pdb", ".ent") else None
                rec_info.set_text(_("已上傳：", "Uploaded: ") + fname)
                refresh()
            ui.upload(on_upload=got_receptor, auto_upload=True, max_files=1, label=t("or_upload", L)).props("accept=.pdb,.ent,.cif,.mmcif flat bordered color=blue-grey-7").classes("w-full")
        with ui.card().classes("w-full md20-card p-4"):
            ui.label(t("ligands", L)).classes("md20-section")
            ui.label(t("ligand_help", L)).classes("md20-why")
            ligs = ui.textarea(placeholder="LIG  CC(=O)Nc1ccc(O)cc1\nPEP  peptide:GGGGGKP").props("autogrow").classes("w-full font-mono")
            lig_err = ui.label("").classes("text-sm text-negative")
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
                        ui.notify(_("只接受 Excel 或 CSV。", "Only Excel or CSV files are accepted."), type="negative"); return
                    dst = _uploads_dir() / f"{uuid.uuid4().hex[:8]}_{safe_name(Path(fname).stem)}{Path(fname).suffix.lower()}"
                    dst.write_bytes(data)
                    try:
                        from ..docking.library import read_library
                        entries, warns = read_library(dst)
                    except Exception as exc:  # noqa: BLE001
                        ui.notify(_("表格無法讀取：", "The table could not be read: ") + str(exc), type="negative"); return
                    state["library_file"] = str(dst)
                    lib_info.set_text(_(f"已上傳 {fname}：{len(entries)} 個化合物", f"Uploaded {fname}: {len(entries)} compounds")
                                      + (f"；{len(warns)} " + _("則提醒", "notes") if warns else ""))
                ui.upload(on_upload=got_library, auto_upload=True, max_files=1, label=t("hts_upload", L)).props("accept=.xlsx,.xls,.csv flat bordered color=blue-grey-7")

        # ------------------------------------------------------------------ parameters
        ui.label(t("parameters", L)).classes("md20-section")
        with ui.row().classes("items-center gap-2"):
            ui.button(t("reset_rec", L), on_click=lambda: reset_all()).props("outline no-caps size=sm")
        keys = list(PARAMS) if pro else QUICK_KEYS
        param_box = ui.column().classes("w-full gap-2")

    with right:
        with ui.card().classes("w-full md20-card p-4"):
            ui.label(t("checks", L)).classes("md20-section")
            checks_box = ui.column().classes("w-full gap-2")
        with ui.card().classes("w-full md20-card p-4"):
            ui.label(t("estimate", L)).classes("md20-section")
            est_label = ui.label("").classes("text-sm")
        err = ui.label("").classes("text-negative text-sm")
        create_btn = ui.button(t("create_start", L), on_click=lambda: create()).props("color=primary no-caps size=lg").classes("w-full")

    # ---------------------------------------------------------------------- behaviour
    def draft_cfg() -> dict:
        try:
            parsed = parse_ligand_lines(ligs.value or "")
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
                ctx = ui.expansion(tx(GROUPS[g], L), value=g in ("docking", "prod")).classes("w-full md20-card") if g else ui.card().classes("w-full md20-card p-4")
                with ctx:
                    for k in ks:
                        with ui.row().classes("w-full gap-3 no-wrap items-start py-1"):
                            with ui.column().classes("w-2/5 gap-0"):
                                widgets[k] = _widget(k, rec[k]["value"], L, on_change_factory(k))
                            with ui.column().classes("w-3/5 gap-0"):
                                rec_labels[k] = ui.label("").classes("md20-changed")
                                why_labels[k] = ui.label(rec[k]["why"]).classes("md20-why")

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
                                   lang=L)
        except ValueError as exc:
            err.set_text(str(exc)); return
        proj = _project(project.value or "Projects")
        cfg["name"] = unique_workflow_name(proj.dir, cfg["name"])
        wf = Workflow(proj, cfg)
        if state["library_file"]:
            shutil.copy2(state["library_file"], wf.dir / Path(state["library_file"]).name)
        _start(wf)
        ui.navigate.to(f"/wf/{proj.dir.name}/{wf.name}")

    build_params()
    refresh()


# --------------------------------------------------------------------------------------------- downloads
@app.get("/template/compound_library.xlsx")
def template_xlsx():
    from fastapi.responses import FileResponse
    from ..docking.library import write_template
    d = Path(tempfile.mkdtemp(prefix="md20tpl_"))
    p = write_template(d / "compound_library.xlsx")
    return FileResponse(p, filename="compound_library.xlsx")
