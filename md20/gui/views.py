"""WP13 view models (pure Python, no NiceGUI): gate cards, timeline, live curves, offline 3D scene.

Everything here returns plain dicts/lists/HTML strings so it is unit-tested without a browser and can be
reused by the self-contained HTML report.  The 3D viewer (`static/md20view.js`) is dependency-free Canvas 2D:
it works offline, on any laptop GPU (or none), and inside a report opened from disk.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

import numpy as np

from ..i18n import pick, cjk, colon, paren, HTML_LANG, norm
from ..util import load_json

STATIC = Path(__file__).parent / "static"
# Status badge: (label in zh, en, ja, ko) and colour.  Cards keep the Chinese label in "label" when lang="zh" (app.py maps it).
STATUS_STYLE = {"PASS": (("通過", "Passed", "合格", "통과"), "positive"),
                "AUTO_FIXED": (("已自動修正", "Corrected automatically", "自動で修正済み", "자동 수정됨"), "warning"),
                "NEEDS_HUMAN": (("需要你決定", "Needs your decision", "判断が必要", "결정 필요"), "negative"),
                "PAUSED": (("已暫停", "Paused", "一時停止中", "일시 정지됨"), "warning"),
                "RUNNING": (("執行中", "Running", "実行中", "실행 중"), "info")}
# The Chinese labels are matched by app.py (SOURCE_EN, STEP_TEXT); change them there at the same time.
STEP_LABELS = {"receptor_input": ("受體來源", "Receptor source", "受容体の入手元", "수용체 출처"),
               "structure_gate": ("結構可信度", "Structure validity", "構造の信頼性", "구조 신뢰성"),
               "receptor_docking": ("受體整理", "Receptor preparation", "受容体の準備", "수용체 준비"),
               "docking_preflight": ("對接前檢查", "Docking pre-checks", "ドッキング前のチェック", "도킹 전 검사"),
               "fold": ("胜肽摺疊", "Peptide folding", "ペプチドの折りたたみ", "펩타이드 접힘"),
               "docking": ("分子對接", "Molecular docking", "分子ドッキング", "분자 도킹"),
               "pose_selection": ("姿勢選擇", "Pose selection", "ポーズの選択", "포즈 선택"),
               "md_confirm": ("確認進入分子動力學", "Confirm molecular dynamics", "分子動力学に進む確認", "분자동역학 진행 확인"),
               "md_cases": ("MD 建模", "System building", "系の構築", "시스템 구축"),
               "md_runs": ("MD 執行", "Molecular dynamics", "分子動力学の実行", "분자동역학 실행"),
               "analysis": ("軌跡分析", "Trajectory analysis", "軌跡解析", "궤적 분석"),
               "binding": ("結合自由能（SMD 與傘狀採樣）", "Binding free energy", "結合自由エネルギー", "결합 자유 에너지"),
               "report": ("報告", "Report", "レポート", "보고서")}
STEP_LABEL = {k: v[0] for k, v in STEP_LABELS.items()}       # Chinese only, kept for older callers
SRC_RECEPTOR = ("受體", "Receptor", "受容体", "수용체")
SRC_ASSEMBLY = ("組裝", "Assembly", "組み立て", "조립")
SRC_LIGAND = ("配體", "Ligand", "リガンド", "리간드")
SRC_LIMIT = ("科學限制", "Scientific limitation", "科学的な制約", "과학적 한계")
SRC_PEPTIDE = ("胜肽", "peptide", "ペプチド", "펩타이드")


def _step(k: str, lang: str) -> str:
    return pick(STEP_LABELS[k], lang) if k in STEP_LABELS else k


# ------------------------------------------------------------------------------------------- gate cards
def _card(source: str, g: dict, *, step: str | None = None, ligand: str | None = None, lang: str = "zh") -> dict:
    from .actions import gate_actions
    st = g.get("status", "PASS")
    labels, color = STATUS_STYLE.get(st, (st, "grey"))
    label = pick(labels, lang)
    actions, manual = gate_actions(g, step=step, ligand=ligand) if step else ([], list(g.get("options") or []))
    return {"source": source, "title": g.get("name", ""), "status": st, "label": label, "color": color,
            "explanation": g.get("explanation") or g.get("message") or "", "options": list(g.get("options") or []),
            "actions": actions, "manual": manual if (st == "NEEDS_HUMAN" or g.get("advisory")) else [],
            "advisory": bool(g.get("advisory"))}


def gate_cards(wf, *, include_pass: bool = False, lang: str = "zh") -> list[dict]:
    """Every gate the student should look at, most urgent first: workflow blocks, then build gates per case.

    Each NEEDS_HUMAN card carries `actions` (one-click decisions written back to config, see gui.actions)
    and `manual` (options that need work outside the program).  `lang` sets the source and badge text; the default
    "zh" keeps the Chinese text that app.py translates itself."""
    cards = []
    steps = wf.state().get("steps", {})
    for k, s in steps.items():
        if s.get("status") != "NEEDS_HUMAN":
            continue
        structured = [g for g in (s.get("gates") or []) if isinstance(g, dict)]
        if k == "md_cases":
            for ckey, c in (s.get("cases") or {}).items():
                det = c.get("blocking_detail")
                if isinstance(det, list):
                    structured += [dict(g, _source=f"{ckey}") for g in det if isinstance(g, dict)]
        if structured:
            for g in structured:
                src = _step(k, lang) + (f" · {g['_source']}" if g.get("_source") else "")
                cards.append(_card(src, {**g, "status": g.get("status", "NEEDS_HUMAN")}, step=k, ligand=s.get("ligand"),
                                   lang=lang))
            continue
        msg = s.get("message", "")
        opts = []
        if "（選項：" in msg:
            msg, o = msg.split("（選項：", 1)
            opts = [x.strip() for x in o.rstrip("）").split(" / ") if x.strip()]
        cards.append(_card(_step(k, lang), {"name": _step(k, lang), "status": "NEEDS_HUMAN",
                                            "message": msg, "options": opts}, lang=lang))
    for key, c in ((steps.get("md_cases") or {}).get("cases") or {}).items():
        try:
            case = wf.project.case(c["case_id"])
        except Exception:  # noqa: BLE001
            continue
        bm = load_json(case.build_dir / "build_manifest.json", {})
        groups = [(pick(SRC_RECEPTOR, lang), (bm.get("receptor") or {}).get("gates") or {}),
                  (pick(SRC_ASSEMBLY, lang), (bm.get("assembly") or {}).get("gates") or {})]
        groups += [(f"{pick(SRC_LIGAND, lang)} {l.get('name')}", l.get("gates") or {}) for l in bm.get("ligands") or []]
        for src, rep in groups:
            for g in rep.get("gates", []):
                if include_pass or g.get("status") != "PASS":
                    cards.append(_card(f"{key} · {src}", g, step="md_cases", lang=lang))
    # scientific-limitation notices (D-48): never blocking, shown with their options
    st_all = wf.state()
    limit, pep = pick(SRC_LIMIT, lang), pick(SRC_PEPTIDE, lang)
    for name, r in (st_all.get("cpp") or {}).items():
        if r.get("advisory") and not r.get("override"):
            cards.append(_card(f"{limit} · {pep} {name}", {"name": "CPP", "status": "AUTO_FIXED", "advisory": True,
                                                         "explanation": r.get("explanation", ""), "options": r.get("options") or []},
                               step="docking_preflight", ligand=name, lang=lang))
    for name, r in (st_all.get("peptide_access") or {}).items():
        for part in ("precheck", "pose"):
            g = r.get(part) or {}
            if g.get("advisory"):
                cards.append(_card(f"{limit} · {pep} {name}", {"name": "peptide pocket access", "status": "AUTO_FIXED",
                                                             "advisory": True, "explanation": g.get("explanation", ""),
                                                             "options": g.get("options") or []}, lang=lang))
    for name, g in (st_all.get("advisories") or {}).items():            # D-56: generic notices (e.g. box size)
        cards.append(_card(limit, g, step="docking_preflight", lang=lang))
    order = {"NEEDS_HUMAN": 0, "AUTO_FIXED": 1, "PASS": 2}
    return sorted(cards, key=lambda c: (order.get(c["status"], 3), not c.get("advisory")))


# --------------------------------------------------------------------------------------------- timeline
def timeline(wf, *, limit: int = 200, lang: str = "zh") -> list[dict]:
    """Steps and decisions in time order (newest last) — the student's 'what did the program do and why'."""
    ev = []
    for k, s in wf.state().get("steps", {}).items():
        if s.get("at"):
            ev.append({"at": s["at"], "kind": "step", "title": _step(k, lang), "status": s.get("status", ""),
                       "text": s.get("message", "")})
    for d in wf.project.decisions.read():
        if "stage" not in d:
            continue
        ev.append({"at": d.get("at", ""), "kind": d.get("kind", "auto"), "title": f"{d['stage']} · {d.get('what', '')}",
                   "status": "human" if d.get("kind") == "human" else "", "text": d.get("why", ""),
                   "choice": json.dumps(d.get("choice"), ensure_ascii=False, default=str)[:120]})
    ev.sort(key=lambda e: e["at"])
    return ev[-limit:]


# ------------------------------------------------------------------------------------------- live curves
def live_series(history: list[dict], *, max_points: int = 600) -> dict:
    """Progress events → chart series.  MD heartbeats carry T/E per chunk; SMD/umbrella events their own."""
    out = {"temperature": [], "potential": [], "smd_force": [], "smd_work": [], "progress": None, "umbrella": None}
    first: dict = {}
    for h in history:
        st = h.get("stage")
        if "temperature_k" in h and "absolute_step" in h:
            x = h["absolute_step"]
            out["temperature"].append([x, round(float(h["temperature_k"]), 2)])
            if h.get("potential_kj_mol") is not None:
                out["potential"].append([x, round(float(h["potential_kj_mol"]), 1)])
            if h.get("total_steps"):
                key = (h.get("case_id"), st)
                if first.get("key") != key or h.get("elapsed_s", 0) < first.get("elapsed", 0):   # new stage or resumed
                    first.update(key=key, steps=h["completed_local_steps"], elapsed=h.get("elapsed_s") or 0.0)
                out["progress"] = {"stage": st, "pct": round(100.0 * h["completed_local_steps"] / h["total_steps"], 1),
                                   "case": h.get("case_id", ""), "elapsed_s": h.get("elapsed_s")}
                d_steps = h["completed_local_steps"] - first["steps"]
                d_t = (h.get("elapsed_s") or 0.0) - first["elapsed"]
                if d_steps > 0 and d_t > 0:
                    rate = d_steps / d_t                                  # steps per second in this stage
                    out["progress"]["eta_s"] = round((h["total_steps"] - h["completed_local_steps"]) / rate)
                    if h.get("timestep_fs"):
                        out["progress"]["ns_per_day"] = round(rate * float(h["timestep_fs"]) * 1e-6 * 86400, 1)
        elif st == "smd":
            r = h.get("r_nm", h.get("r0"))
            if r is not None and h.get("force") is not None:
                out["smd_force"].append([round(float(r), 4), round(float(h["force"]), 1)])
            w = h.get("work_kj_mol", h.get("work"))
            if r is not None and w is not None:
                out["smd_work"].append([round(float(r), 4), round(float(w), 2)])
        elif st == "umbrella":
            n = h.get("n_windows", h.get("n"))
            out["umbrella"] = {"window": h.get("window"), "n": n,
                               "pct": round(100.0 * h["window"] / n, 1) if n else None}
        elif st == "docking":
            out["progress"] = {"stage": "docking", "pct": round(100.0 * h.get("i", 0) / max(1, h.get("n", 1)), 1),
                               "case": h.get("ligand", "")}
    for k in ("temperature", "potential", "smd_force", "smd_work"):
        out[k] = out[k][-max_points:]
    return out


def echart_options(series: list, *, title: str, x: str, y: str) -> dict:
    return {"title": {"text": title, "textStyle": {"fontSize": 12}}, "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "value", "name": x, "scale": True}, "yAxis": {"type": "value", "name": y, "scale": True},
            "series": [{"type": "line", "showSymbol": False, "data": series}], "grid": {"left": 60, "right": 20}}


# --------------------------------------------------------------------------------------------- 3D scene
WATER_IONS = {"HOH", "WAT", "TIP3", "SOL", "NA", "CL", "K", "NA+", "CL-"}
METALS = {"ZN", "FE", "FE2", "CU", "CU1", "MN", "CO", "NI", "MG", "CA", "CD"}
PROTEIN = {"ALA", "ARG", "ASN", "ASP", "ASH", "CYS", "CYM", "CYX", "GLN", "GLU", "GLH", "GLY", "HIS", "HID", "HIE", "HIP",
           "ILE", "LEU", "LYS", "LYN", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL"}
COVALENT = {"H": 0.31, "C": 0.76, "N": 0.71, "O": 0.66, "S": 1.05, "P": 1.07, "F": 0.57, "Cl": 1.02, "Br": 1.20, "I": 1.39}


def parse_pdb_atoms(text: str) -> tuple[list[dict], np.ndarray]:
    atoms, xyz = [], []
    for line in text.splitlines():
        if not line.startswith(("ATOM", "HETATM")):
            continue
        el = line[76:78].strip() or line[12:16].strip()[:1]
        el = el[:1].upper() + el[1:].lower()
        atoms.append({"n": line[12:16].strip(), "r": line[17:20].strip(), "c": line[21:22], "s": line[22:26].strip(), "e": el})
        xyz.append([float(line[30:38]), float(line[38:46]), float(line[46:54])])
    return atoms, np.asarray(xyz, dtype=float).reshape(-1, 3)


HYDROPHOBIC = {"ALA", "VAL", "LEU", "ILE", "MET", "PHE", "TRP", "PRO", "TYR", "CYS", "CYM", "CYX"}
BACKBONE = {"N", "CA", "C", "O"}
INTERACTION_TEXT = {   # type → (label, rule), each (zh, en, ja, ko)
    "h": (("氫鍵候選", "Hydrogen-bond candidate", "水素結合の候補", "수소 결합 후보"),
          ("配體的 N 或 O 與口袋的 N 或 O 重原子距離 ≤ 3.5 Å。氫原子已省略，未檢查角度。",
           "Distance ≤ 3.5 Å between a ligand N or O and a pocket N or O heavy atom. Hydrogens are omitted and angles "
           "are not checked.",
           "リガンドの N または O と、ポケットの N または O の重原子との距離が ≤ 3.5 Å。水素は省略しており、角度は"
           "確認していません。",
           "리간드의 N 또는 O와 포켓의 N 또는 O 중원자 사이 거리 ≤ 3.5 Å. 수소는 생략했고 각도는 확인하지 않았습니다.")),
    "c": (("疏水接觸", "Hydrophobic contact", "疎水性接触", "소수성 접촉"),
          ("配體的 C 與疏水殘基側鏈的 C 距離 ≤ 4.0 Å。每個殘基在每一幀只取最近的一對。",
           "Distance ≤ 4.0 Å between a ligand C and a side-chain C of a hydrophobic residue. Only the closest pair per "
           "residue is counted in each frame.",
           "リガンドの C と疎水性残基の側鎖の C との距離が ≤ 4.0 Å。各フレームで残基ごとに最も近い 1 組だけを数えます。",
           "리간드의 C와 소수성 잔기 곁사슬의 C 사이 거리 ≤ 4.0 Å. 각 프레임에서 잔기마다 가장 가까운 한 쌍만 셉니다.")),
    "m": (("金屬配位", "Metal coordination", "金属配位", "금속 배위"),
          ("配體的 N、O 或 S 與金屬距離 ≤ 2.8 Å。", "Distance ≤ 2.8 Å between a ligand N, O or S and a metal.",
           "リガンドの N、O または S と金属との距離が ≤ 2.8 Å。", "리간드의 N, O 또는 S와 금속 사이 거리 ≤ 2.8 Å.")),
}
# Chinese labels and rules travel with the scene data (as before); interaction_table_html translates by type.
INTERACTION_TYPES = {k: {"label": lab[0], "rule": rule[0]} for k, (lab, rule) in INTERACTION_TEXT.items()}


def ligand_interactions(sa: list[dict], frames: np.ndarray) -> dict:
    """Geometric ligand–pocket contacts per frame + per-residue occupancy over the trajectory.

    Purely distance-based on the heavy atoms in the scene — a teaching overlay, not an energy decomposition.
    Returns {"frames": [[[i, j, type], ...] per frame], "occupancy": [{residue, type, label, fraction}], "types"}."""
    lig = [i for i, a in enumerate(sa) if a["k"] == "L"]
    poc = [i for i, a in enumerate(sa) if a["k"] in ("P", "M")]
    out = {"frames": [], "occupancy": [], "types": INTERACTION_TYPES}
    if not lig or not poc:
        return out
    counts: dict[tuple[str, str], int] = {}
    for f in np.asarray(frames, dtype=float):
        d = np.linalg.norm(f[lig][:, None, :] - f[poc][None, :, :], axis=-1)
        best: dict[tuple, tuple[float, int, int]] = {}
        for li, pj in zip(*np.where(d <= 4.0)):
            a, b, dist = sa[lig[li]], sa[poc[pj]], float(d[li, pj])
            res = f"{b['r']}{b['s']}"
            if b["k"] == "M":
                t = "m" if a["e"] in ("N", "O", "S") and dist <= 2.8 else None
            elif a["e"] in ("N", "O") and b["e"] in ("N", "O") and dist <= 3.5:
                t = "h"
            elif a["e"] == "C" and b["e"] == "C" and b["r"] in HYDROPHOBIC and b["n"] not in BACKBONE:
                t = "c"
            else:
                t = None
            if t is None:
                continue
            key = (res, t) if t == "c" else (res, t, lig[li], poc[pj])
            if key not in best or dist < best[key][0]:
                best[key] = (dist, lig[li], poc[pj])
        items = [[i, j, k[1]] for k, (_, i, j) in sorted(best.items(), key=lambda kv: kv[1][0])]
        out["frames"].append(items)
        for res, t in {(k[0], k[1]) for k in best}:
            counts[(res, t)] = counts.get((res, t), 0) + 1
    n = max(1, len(out["frames"]))
    out["occupancy"] = sorted(({"residue": r, "type": t, "label": INTERACTION_TYPES[t]["label"], "fraction": round(c / n, 3)}
                               for (r, t), c in counts.items()), key=lambda x: (-x["fraction"], x["type"], x["residue"]))
    return out


def _type_label(o: dict, lang: str) -> str:
    t = INTERACTION_TEXT.get(o.get("type"))
    return pick(t[0], lang) if t else o.get("label", "")


def interaction_table_html(scene: dict, *, limit: int = 12, lang: str = "zh") -> str:
    occ = (scene.get("interactions") or {}).get("occupancy") or []
    if not occ:
        none = pick(("配體與口袋之間沒有符合幾何準則的互作。", "No interaction between the ligand and the pocket meets the "
                     "geometric criteria.", "リガンドとポケットの間に、幾何学的な基準を満たす相互作用はありません。",
                     "리간드와 포켓 사이에 기하 기준을 만족하는 상호작용이 없습니다."), lang)
        return f"<p style='font-size:12px;color:#667'>{html.escape(none)}</p>"
    n = (scene.get("summary") or {}).get("n_frames", 1)
    head = pick(("佔有率（軌跡中出現的幀比例）", "Occupancy (fraction of frames)", "占有率（出現したフレームの割合）",
                 "점유율(나타난 프레임 비율)") if n > 1 else ("起始結構", "Starting structure", "初期構造", "시작 구조"), lang)
    th_res = pick(("殘基", "Residue", "残基", "잔기"), lang)
    th_type = pick(("類型", "Type", "種類", "유형"), lang)
    rows = "".join(f"<tr><td>{html.escape(o['residue'])}</td><td>{html.escape(_type_label(o, lang))}</td>"
                   f"<td style='text-align:right'>{o['fraction'] * 100:.0f}%</td></tr>" for o in occ[:limit])
    intro = pick(("以下是教學用的幾何準則，不是能量分解。", "These are geometric criteria for teaching, not an energy "
                  "decomposition.", "以下は教育用の幾何学的な基準で、エネルギー分解ではありません。",
                  "아래는 교육용 기하 기준이며 에너지 분해가 아닙니다."), lang)
    rules = "<br>".join(html.escape(pick(lab, lang) + colon(lang) + pick(rule, lang)) for lab, rule in INTERACTION_TEXT.values())
    return (f"<table style='font-size:12px;border-collapse:collapse' cellpadding=3><tr><th>{th_res}</th><th>{th_type}</th>"
            f"<th>{head}</th></tr>{rows}</table><p style='font-size:11px;color:#667'>{html.escape(intro)}<br>{rules}</p>")


def build_scene(atoms: list[dict], frames: np.ndarray, *, ligand_indices: list[int] | None = None,
                ligand_resnames: set[str] | None = None, pocket_cutoff_A: float = 6.0, max_atoms: int = 4000,
                times_ps: list[float] | None = None) -> dict:
    """Small scene for the viewer: Cα trace of the protein, pocket residues (heavy atoms) and ligand(s).

    `frames`: (n_frames, n_atoms, 3) in Å (or (n_atoms, 3)).  Water/ions are always dropped; hydrogens too,
    except polar hydrogens of the ligand."""
    frames = np.asarray(frames, dtype=float)
    if frames.ndim == 2:
        frames = frames[None]
    lig = set(ligand_indices or [])
    if not lig and ligand_resnames:
        lig = {i for i, a in enumerate(atoms) if a["r"] in ligand_resnames}
    if not lig:   # fallback: L01, L02 … residue names written by the build
        lig = {i for i, a in enumerate(atoms) if len(a["r"]) == 3 and a["r"][0] == "L" and a["r"][1:].isdigit()}
    x0 = frames[0]
    keep, kind = [], {}
    lig_xyz = x0[sorted(lig)] if lig else np.zeros((0, 3))
    near_res = set()
    if len(lig_xyz):
        for i, a in enumerate(atoms):
            if i in lig or a["r"] not in PROTEIN or a["e"] == "H":
                continue
            if np.min(np.linalg.norm(lig_xyz - x0[i], axis=1)) <= pocket_cutoff_A:
                near_res.add((a["c"], a["s"]))
    for i, a in enumerate(atoms):
        if a["r"] in WATER_IONS:
            continue
        if i in lig:
            if a["e"] == "H":
                continue
            keep.append(i); kind[i] = "L"
        elif a["r"] in METALS and a["r"] not in PROTEIN and a["n"].upper() == a["r"]:
            keep.append(i); kind[i] = "M"
        elif a["r"] in PROTEIN and (a["c"], a["s"]) in near_res and a["e"] != "H":
            keep.append(i); kind[i] = "P"
        elif a["r"] in PROTEIN and a["n"] == "CA":
            keep.append(i); kind[i] = "T"
    keep = keep[:max_atoms]
    idx = {old: new for new, old in enumerate(keep)}
    sa = [{"e": atoms[i]["e"], "n": atoms[i]["n"], "r": atoms[i]["r"], "s": atoms[i]["s"], "k": kind[i]} for i in keep]
    bonds = []
    # covalent bonds within ligand/pocket (distance-based, frame 0); Cα trace along consecutive residues per chain
    heavy = [i for i in keep if kind[i] in ("L", "P")]
    hx = x0[heavy]
    for a_i, i in enumerate(heavy):
        d = np.linalg.norm(hx[a_i + 1:] - hx[a_i], axis=1)
        for off in np.where(d < 2.1)[0]:
            j = heavy[a_i + 1 + int(off)]
            if kind[i] != kind[j] and not (kind[i] == "P" and kind[j] == "P"):
                continue
            if atoms[i]["r"] != atoms[j]["r"] and kind[i] == "L":
                continue
            ri = COVALENT.get(atoms[i]["e"], 0.8) + COVALENT.get(atoms[j]["e"], 0.8) + 0.45
            if d[off] <= ri:
                bonds.append([idx[i], idx[j]])
    trace = [i for i in keep if kind[i] in ("T", "P") and atoms[i]["n"] == "CA"]
    for a_i in range(len(trace) - 1):
        i, j = trace[a_i], trace[a_i + 1]
        if atoms[i]["c"] == atoms[j]["c"] and np.linalg.norm(x0[i] - x0[j]) < 4.3:
            bonds.append([idx[i], idx[j]])
    fr = [np.round(f[keep].reshape(-1), 2).tolist() for f in frames]
    inter = ligand_interactions(sa, frames[:, keep, :]) if keep else {"frames": [], "occupancy": []}
    scene = {"atoms": sa, "bonds": bonds, "frames": fr, "interactions": inter,
             "summary": {"n_ligand_atoms": sum(1 for k in kind.values() if k == "L"), "n_pocket_residues": len(near_res),
                         "n_frames": len(fr), "n_interaction_types": len(inter["occupancy"])}}
    if times_ps is not None:
        scene["times_ps"] = [float(t) for t in times_ps][:len(fr)]
    return scene


def scene_from_pdb(path: Path | str, **kw) -> dict:
    atoms, xyz = parse_pdb_atoms(Path(path).read_text(encoding="utf-8", errors="ignore"))
    return build_scene(atoms, xyz, **kw)


def scene_from_run(run_dir: Path | str, topology_pdb: Path | str, *, ligand_indices: list[int] | None = None,
                   max_frames: int = 60) -> dict:
    """Production trajectory → scene with up to `max_frames` frames (needs mdtraj; imaged + Cα-superposed)."""
    from ..analysis.traj import load_production
    from ..workflow import metal_indices_from_manifest
    bm = load_json(Path(topology_pdb).parent / "build_manifest.json", {})
    traj = load_production(run_dir, topology_pdb, metal_indices=metal_indices_from_manifest(bm))
    stride = max(1, traj.n_frames // max_frames)
    traj = traj[::stride]
    atoms, _ = parse_pdb_atoms(Path(topology_pdb).read_text(encoding="utf-8", errors="ignore"))
    return build_scene(atoms, traj.xyz * 10.0, ligand_indices=ligand_indices,
                       times_ps=list(traj.time) if traj.time is not None else None)


def _viewer_caption(s: dict, lang: str) -> str:
    n_lig, n_res, n_fr = s.get("n_ligand_atoms", 0), s.get("n_pocket_residues", 0), s.get("n_frames", 1)
    many = n_fr > 1
    return pick((
        f"配體有 {n_lig} 個重原子，口袋有 {n_res} 個殘基" + (f"，共 {n_fr} 幀" if many else "") +
        "。拖曳可以旋轉，滾輪可以縮放。虛線的顏色，黃色是氫鍵候選，灰色是疏水接觸，紫色是金屬配位。"
        "「表面」是用口袋原子的凡得瓦球近似畫出來的，不是溶劑可及表面。",
        f"Shows {n_lig} ligand heavy atoms and {n_res} pocket residues" + (f" over {n_fr} frames" if many else "") +
        ". Drag to rotate and scroll to zoom. Dashed lines are yellow for hydrogen-bond candidates, grey for "
        "hydrophobic contacts and purple for metal coordination. The Surface button draws pocket atoms as "
        "van der Waals spheres. It is not a solvent-accessible surface.",
        f"リガンドの重原子 {n_lig} 個とポケットの残基 {n_res} 個" + (f"を {n_fr} フレーム分" if many else "を") +
        "表示しています。ドラッグで回転、ホイールで拡大と縮小ができます。破線の色は、黄が水素結合の候補、"
        "灰が疎水性接触、紫が金属配位です。「表面」はポケット原子をファンデルワールス球で近似したもので、"
        "溶媒接触可能表面ではありません。",
        f"리간드 중원자 {n_lig}개와 포켓 잔기 {n_res}개" + (f"를 프레임 {n_fr}개에 걸쳐" if many else "를") +
        " 표시합니다. 드래그하면 회전하고, 휠로 확대하거나 축소합니다. 점선 색은 노란색이 수소 결합 후보, "
        "회색이 소수성 접촉, 보라색이 금속 배위입니다. '표면' 버튼은 포켓 원자를 반데르발스 구로 "
        "근사한 것이며 용매 접근 표면이 아닙니다."), lang)


VIEWER_BUTTONS = {"interactions": ("互作", "Interactions", "相互作用", "상호작용"),
                  "surface": ("表面", "Surface", "表面", "표면")}


def viewer_html(scene: dict, *, title: str = "MD20 3D", standalone: bool = True, height_px: int = 420,
                lang: str = "zh") -> str:
    """HTML for the viewer with the JS inlined (works from file://, offline)."""
    js = (STATIC / "md20view.js").read_text(encoding="utf-8")
    scene = {**scene, "ui": {"interactions": pick(VIEWER_BUTTONS["interactions"], lang),
                              "surface": pick(VIEWER_BUTTONS["surface"], lang)}}
    data = json.dumps(scene, separators=(",", ":")).replace("</", "<\\/")
    import hashlib
    uid = "md20v" + hashlib.sha1(data.encode()).hexdigest()[:10]
    cap = _viewer_caption(scene.get("summary", {}), lang)
    body = (f'<div id="{uid}" style="width:100%;max-width:900px;min-height:{height_px}px;background:#111418;border-radius:6px"></div>'
            f'<p style="font-size:12px;color:#667">{html.escape(cap)}</p>' + interaction_table_html(scene, lang=lang) +
            f"<script>{js}</script><script>md20Mount(document.getElementById('{uid}'), {data});</script>")
    if not standalone:
        return body
    return (f"<!DOCTYPE html><html lang={HTML_LANG[norm(lang)]}><head><meta charset=utf-8><title>{html.escape(title)}</title></head>"
            f"<body style='font-family:sans-serif;margin:16px'><h3>{html.escape(title)}</h3>{body}</body></html>")


TARGET_START = ("建模起始結構", "Built starting structure", "構築した初期構造", "구축한 시작 구조")
TARGET_TRAJ = ("正式模擬軌跡", "Production trajectory", "本計算の軌跡", "본 시뮬레이션 궤적")


def viewer_targets(wf, *, lang: str = "zh") -> list[dict]:
    """Cases that can be shown: built start structure always; production trajectory when the run finished."""
    from ..workflow import manifest_ligands
    steps = wf.state().get("steps", {})
    runs = (steps.get("md_runs") or {}).get("runs") or {}
    out = []
    for key, c in ((steps.get("md_cases") or {}).get("cases") or {}).items():
        try:
            case = wf.project.case(c["case_id"])
        except Exception:  # noqa: BLE001
            continue
        bm = load_json(case.build_dir / "build_manifest.json", {})
        if not bm.get("topology_pdb") or not Path(bm["topology_pdb"]).is_file():
            continue
        lig = sorted({i for l in manifest_ligands(bm) for i in (l.get("atom_indices") or l.get("heavy_atom_indices") or [])})
        out.append({"key": key, "mode": "start", "label": f"{key}{colon(lang)}{pick(TARGET_START, lang)}", "topology_pdb": bm["topology_pdb"],
                    "ligand_indices": lig})
        r = runs.get(key) or {}
        if r.get("status") == "COMPLETE" and r.get("run_ids"):
            out.append({"key": key, "mode": "traj", "label": f"{key}{colon(lang)}{pick(TARGET_TRAJ, lang)}", "topology_pdb": bm["topology_pdb"],
                        "ligand_indices": lig, "run_dir": str(case.dir / "runs" / r["run_ids"][0])})
    return out


def scene_for(target: dict, *, max_frames: int = 60) -> dict:
    if target["mode"] == "traj":
        return scene_from_run(target["run_dir"], target["topology_pdb"], ligand_indices=target["ligand_indices"] or None,
                              max_frames=max_frames)
    return scene_from_pdb(target["topology_pdb"], ligand_indices=target["ligand_indices"] or None)


# ------------------------------------------------------------------------------ umbrella coverage (live)
def coverage_targets(wf, *, lang: str = "zh") -> list[dict]:
    """Binding targets that have (or are writing) a coverage.json — one entry per replica directory."""
    root = Path(wf.dir) / "binding"
    out = []
    if not root.is_dir():
        return out
    for tdir in sorted(p for p in root.iterdir() if p.is_dir()):
        reps = sorted(p for p in tdir.glob("rep*") if p.is_dir()) or [tdir]
        for r in reps:
            if (r / "coverage.json").is_file():
                name = tdir.name.replace("_", ":", 1) if tdir.name.startswith("multi_") else tdir.name
                out.append({"target": name, "dir": str(r),
                            "label": name + (paren(r.name, lang) if r != tdir else "")})
    return out


def _pl(n: int) -> str:
    return "" if n == 1 else "s"


def _sep(lang: str) -> str:
    return "、" if cjk(lang) else ", "


def coverage_chart(cov: dict, *, lang: str = "zh") -> dict:
    """ECharts option: pooled samples per CV bin (area) + each window's histogram (thin lines); breaks shaded red."""
    edges = cov.get("edges") or []
    if len(edges) < 2:
        empty = pick(("還沒有取樣", "No samples yet", "まだサンプルがありません", "아직 샘플이 없습니다"), lang)
        return {"title": {"text": empty, "textStyle": {"fontSize": 12}}, "xAxis": {}, "yAxis": {}, "series": []}
    mids = [round((a + b) / 2, 4) for a, b in zip(edges[:-1], edges[1:])]
    gap = pick(("斷點", "Gap", "切れ目", "끊긴 구간"), lang)
    series = [{"name": pick(("合併樣本", "Pooled samples", "統合したサンプル", "합친 샘플"), lang), "type": "line", "step": "middle",
               "showSymbol": False, "areaStyle": {"opacity": 0.25},
               "lineStyle": {"width": 1.5}, "data": [[x, y] for x, y in zip(mids, cov.get("pooled") or [])],
               "markArea": {"itemStyle": {"color": "rgba(220,38,38,0.25)"},
                            "data": [[{"xAxis": lo, "name": gap}, {"xAxis": hi}] for lo, hi in cov.get("breaks") or []]}}]
    for w in cov.get("windows") or []:
        series.append({"name": f"{w['center']:.3f}" + (f" (k {w['k']:.0f})" if w.get("k") else ""), "type": "line",
                       "showSymbol": False, "lineStyle": {"width": 0.8, "opacity": 0.7},
                       "data": [[x, y] for x, y in zip(mids, w["counts"]) if y > 0]})
    rng = cov.get("cv_range_nm") or [mids[0], mids[-1]]
    n_win, n_gap = len(cov.get("windows") or []), len(cov.get("breaks") or [])
    if cov.get("continuous"):
        state = pick(("連續", "continuous", "連続", "연속"), lang)
    else:
        state = pick((f"{n_gap} 個斷點", f"{n_gap} gap{_pl(n_gap)}", f"切れ目 {n_gap} か所", f"끊긴 구간 {n_gap}곳"), lang)
    title = pick((f"取樣覆蓋範圍（{n_win} 個窗口，{state}）", f"Sampling coverage ({n_win} window{_pl(n_win)}, {state})",
                  f"サンプリングのカバー範囲（{n_win} ウィンドウ、{state}）", f"샘플링 범위(윈도우 {n_win}개, {state})"), lang)
    x_name = pick(("錨點到配體質心的距離", "Distance from the anchor to the ligand centre of mass",
                   "アンカーからリガンド重心までの距離", "앵커에서 리간드 질량 중심까지의 거리"), lang) + paren("nm", lang)
    return {"title": {"text": title, "textStyle": {"fontSize": 12}},
            "tooltip": {"trigger": "axis"}, "legend": {"show": False},
            "xAxis": {"type": "value", "name": x_name, "min": round(min(rng[0], mids[0]), 3),
                      "max": round(max(rng[1], mids[-1]), 3)},
            "yAxis": {"type": "value", "name": pick(("樣本數", "Samples", "サンプル数", "샘플 수"), lang)},
            "series": series, "grid": {"left": 60, "right": 20}}


def coverage_summary(cov: dict, *, lang: str = "zh") -> str:
    """One short paragraph: status, number of windows, gaps, and the last automatic window round."""
    rounds = cov.get("rounds") or []
    sep, st = _sep(lang), cov.get("status", "")
    n_win = len(cov.get("windows") or [])
    parts = [pick((f"狀態：{st}。", f"Status: {st}.", f"状態：{st}。", f"상태: {st}."), lang),
             pick((f"共 {n_win} 個窗口。", f"{n_win} window{_pl(n_win)}.", f"ウィンドウは {n_win} 個です。", f"윈도우 {n_win}개."), lang)]
    if cov.get("continuous"):
        parts.append(pick(("取樣連續。", "Sampling is continuous.", "サンプリングは連続しています。", "샘플링이 연속입니다."), lang))
    else:
        gaps = sep.join(f"{a:.3f}–{b:.3f} nm" for a, b in cov.get("breaks") or [])
        parts.append(pick((f"斷點（紅色）：{gaps}。", f"Gaps (red): {gaps}.", f"切れ目（赤）：{gaps}。",
                           f"끊긴 구간(빨간색): {gaps}."), lang))
    if rounds:
        last = rounds[-1]
        r, n_ins, n_ext = last["round"], len(last.get("insert") or []), len(last.get("extend") or [])
        parts.append(pick((f"自動補窗第 {r} 輪：新增 {n_ins} 個，延長 {n_ext} 個。",
                           f"Automatic window round {r}: {n_ins} added, {n_ext} extended.",
                           f"ウィンドウの自動追加 第 {r} 回：追加 {n_ins}、延長 {n_ext}。",
                           f"자동 윈도우 보완 {r}회차: 추가 {n_ins}, 연장 {n_ext}."), lang))
        if last.get("unsamplable"):
            bad = sep.join(f"{a:.3f}–{b:.3f}" for a, b in last["unsamplable"])
            parts.append(pick((f"在 k 上限仍取樣不到：{bad}。", f"Still not sampled at the k limit: {bad}.",
                               f"k の上限でもサンプリングできない区間：{bad}。",
                               f"k 상한에서도 샘플링되지 않은 구간: {bad}."), lang))
    return ("" if cjk(lang) else " ").join(parts)
