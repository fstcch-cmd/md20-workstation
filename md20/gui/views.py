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

from ..util import load_json

STATIC = Path(__file__).parent / "static"
STATUS_STYLE = {"PASS": ("通過", "positive"), "AUTO_FIXED": ("已自動修正", "warning"), "NEEDS_HUMAN": ("需要你決定", "negative"),
                "PAUSED": ("已暫停", "warning"), "RUNNING": ("執行中", "info")}
STEP_LABEL = {"receptor_input": "受體來源", "structure_gate": "結構可信度", "receptor_docking": "受體整理",
              "docking_preflight": "對接前檢查", "docking": "分子對接", "pose_selection": "pose 選擇", "md_cases": "MD 建模",
              "md_runs": "MD 執行", "analysis": "軌跡分析", "binding": "SMD＋傘狀採樣", "report": "報告"}


# ------------------------------------------------------------------------------------------- gate cards
def _card(source: str, g: dict, *, step: str | None = None, ligand: str | None = None) -> dict:
    from .actions import gate_actions
    st = g.get("status", "PASS")
    label, color = STATUS_STYLE.get(st, (st, "grey"))
    actions, manual = gate_actions(g, step=step, ligand=ligand) if step else ([], list(g.get("options") or []))
    return {"source": source, "title": g.get("name", ""), "status": st, "label": label, "color": color,
            "explanation": g.get("explanation") or g.get("message") or "", "options": list(g.get("options") or []),
            "actions": actions, "manual": manual if st == "NEEDS_HUMAN" else []}


def gate_cards(wf, *, include_pass: bool = False) -> list[dict]:
    """Every gate the student should look at, most urgent first: workflow blocks, then build gates per case.

    Each NEEDS_HUMAN card carries `actions` (one-click decisions written back to config, see gui.actions)
    and `manual` (options that need work outside the program)."""
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
                src = STEP_LABEL.get(k, k) + (f" · {g['_source']}" if g.get("_source") else "")
                cards.append(_card(src, {**g, "status": g.get("status", "NEEDS_HUMAN")}, step=k, ligand=s.get("ligand")))
            continue
        msg = s.get("message", "")
        opts = []
        if "（選項：" in msg:
            msg, o = msg.split("（選項：", 1)
            opts = [x.strip() for x in o.rstrip("）").split(" / ") if x.strip()]
        cards.append(_card(STEP_LABEL.get(k, k), {"name": STEP_LABEL.get(k, k), "status": "NEEDS_HUMAN",
                                                  "message": msg, "options": opts}))
    for key, c in ((steps.get("md_cases") or {}).get("cases") or {}).items():
        try:
            case = wf.project.case(c["case_id"])
        except Exception:  # noqa: BLE001
            continue
        bm = load_json(case.build_dir / "build_manifest.json", {})
        groups = [("受體", (bm.get("receptor") or {}).get("gates") or {}),
                  ("組裝", (bm.get("assembly") or {}).get("gates") or {})]
        groups += [(f"配體 {l.get('name')}", l.get("gates") or {}) for l in bm.get("ligands") or []]
        for src, rep in groups:
            for g in rep.get("gates", []):
                if include_pass or g.get("status") != "PASS":
                    cards.append(_card(f"{key} · {src}", g, step="md_cases"))
    order = {"NEEDS_HUMAN": 0, "AUTO_FIXED": 1, "PASS": 2}
    return sorted(cards, key=lambda c: order.get(c["status"], 3))


# --------------------------------------------------------------------------------------------- timeline
def timeline(wf, *, limit: int = 200) -> list[dict]:
    """Steps and decisions in time order (newest last) — the student's 'what did the program do and why'."""
    ev = []
    for k, s in wf.state().get("steps", {}).items():
        if s.get("at"):
            ev.append({"at": s["at"], "kind": "step", "title": STEP_LABEL.get(k, k), "status": s.get("status", ""),
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
    for h in history:
        st = h.get("stage")
        if "temperature_k" in h and "absolute_step" in h:
            x = h["absolute_step"]
            out["temperature"].append([x, round(float(h["temperature_k"]), 2)])
            if h.get("potential_kj_mol") is not None:
                out["potential"].append([x, round(float(h["potential_kj_mol"]), 1)])
            if h.get("total_steps"):
                out["progress"] = {"stage": st, "pct": round(100.0 * h["completed_local_steps"] / h["total_steps"], 1),
                                   "case": h.get("case_id", ""), "elapsed_s": h.get("elapsed_s")}
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
INTERACTION_TYPES = {
    "h": {"label": "氫鍵候選", "rule": "配體 N/O 與口袋 N/O 重原子距離 ≤ 3.5 Å（氫已省略，未檢查角度）"},
    "c": {"label": "疏水接觸", "rule": "配體 C 與疏水殘基側鏈 C 距離 ≤ 4.0 Å（每殘基每幀取最近一對）"},
    "m": {"label": "金屬配位", "rule": "配體 N/O/S 與金屬距離 ≤ 2.8 Å"},
}


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


def interaction_table_html(scene: dict, *, limit: int = 12) -> str:
    occ = (scene.get("interactions") or {}).get("occupancy") or []
    if not occ:
        return "<p style='font-size:12px;color:#667'>配體與口袋之間沒有符合幾何準則的互作。</p>"
    n = (scene.get("summary") or {}).get("n_frames", 1)
    head = "佔有率（軌跡中出現的幀比例）" if n > 1 else "起始結構"
    rows = "".join(f"<tr><td>{html.escape(o['residue'])}</td><td>{html.escape(o['label'])}</td>"
                   f"<td style='text-align:right'>{o['fraction'] * 100:.0f}%</td></tr>" for o in occ[:limit])
    rules = "；".join(f"{v['label']}：{v['rule']}" for v in INTERACTION_TYPES.values())
    return (f"<table style='font-size:12px;border-collapse:collapse' cellpadding=3><tr><th>殘基</th><th>類型</th><th>{head}</th></tr>"
            f"{rows}</table><p style='font-size:11px;color:#667'>幾何準則（教學用，不是能量分解）：{html.escape(rules)}。</p>")


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
    traj = load_production(run_dir, topology_pdb)
    stride = max(1, traj.n_frames // max_frames)
    traj = traj[::stride]
    atoms, _ = parse_pdb_atoms(Path(topology_pdb).read_text(encoding="utf-8", errors="ignore"))
    return build_scene(atoms, traj.xyz * 10.0, ligand_indices=ligand_indices,
                       times_ps=list(traj.time) if traj.time is not None else None)


def viewer_html(scene: dict, *, title: str = "MD20 3D", standalone: bool = True, height_px: int = 420) -> str:
    """HTML for the viewer with the JS inlined (works from file://, offline)."""
    js = (STATIC / "md20view.js").read_text(encoding="utf-8")
    data = json.dumps(scene, separators=(",", ":")).replace("</", "<\\/")
    import hashlib
    uid = "md20v" + hashlib.sha1(data.encode()).hexdigest()[:10]
    s = scene.get("summary", {})
    cap = (f"配體 {s.get('n_ligand_atoms', 0)} 個重原子、口袋 {s.get('n_pocket_residues', 0)} 個殘基"
           + (f"、{s['n_frames']} 幀" if s.get("n_frames", 1) > 1 else "") +
           "；拖曳旋轉、滾輪縮放。虛線：黃＝氫鍵候選、灰＝疏水接觸、紫＝金屬配位；「表面」為口袋原子 vdW 球近似，不是溶劑可及表面。")
    body = (f'<div id="{uid}" style="width:100%;max-width:900px;min-height:{height_px}px;background:#111418;border-radius:6px"></div>'
            f'<p style="font-size:12px;color:#667">{html.escape(cap)}</p>' + interaction_table_html(scene) +
            f"<script>{js}</script><script>md20Mount(document.getElementById('{uid}'), {data});</script>")
    if not standalone:
        return body
    return (f"<!DOCTYPE html><html lang=zh-Hant><head><meta charset=utf-8><title>{html.escape(title)}</title></head>"
            f"<body style='font-family:sans-serif;margin:16px'><h3>{html.escape(title)}</h3>{body}</body></html>")


def viewer_targets(wf) -> list[dict]:
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
        out.append({"key": key, "mode": "start", "label": f"{key}：建模起始結構", "topology_pdb": bm["topology_pdb"],
                    "ligand_indices": lig})
        r = runs.get(key) or {}
        if r.get("status") == "COMPLETE" and r.get("run_ids"):
            out.append({"key": key, "mode": "traj", "label": f"{key}：production 軌跡", "topology_pdb": bm["topology_pdb"],
                        "ligand_indices": lig, "run_dir": str(case.dir / "runs" / r["run_ids"][0])})
    return out


def scene_for(target: dict, *, max_frames: int = 60) -> dict:
    if target["mode"] == "traj":
        return scene_from_run(target["run_dir"], target["topology_pdb"], ligand_indices=target["ligand_indices"] or None,
                              max_frames=max_frames)
    return scene_from_pdb(target["topology_pdb"], ligand_indices=target["ligand_indices"] or None)


# ------------------------------------------------------------------------------ umbrella coverage (live)
def coverage_targets(wf) -> list[dict]:
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
                            "label": name + (f"（{r.name}）" if r != tdir else "")})
    return out


def coverage_chart(cov: dict) -> dict:
    """ECharts option: pooled samples per CV bin (area) + each window's histogram (thin lines); breaks shaded red."""
    edges = cov.get("edges") or []
    if len(edges) < 2:
        return {"title": {"text": "尚無取樣", "textStyle": {"fontSize": 12}}, "xAxis": {}, "yAxis": {}, "series": []}
    mids = [round((a + b) / 2, 4) for a, b in zip(edges[:-1], edges[1:])]
    series = [{"name": "合併樣本", "type": "line", "step": "middle", "showSymbol": False, "areaStyle": {"opacity": 0.25},
               "lineStyle": {"width": 1.5}, "data": [[x, y] for x, y in zip(mids, cov.get("pooled") or [])],
               "markArea": {"itemStyle": {"color": "rgba(220,38,38,0.25)"},
                            "data": [[{"xAxis": lo, "name": "斷點"}, {"xAxis": hi}] for lo, hi in cov.get("breaks") or []]}}]
    for w in cov.get("windows") or []:
        series.append({"name": f"{w['center']:.3f}" + (f" (k {w['k']:.0f})" if w.get("k") else ""), "type": "line",
                       "showSymbol": False, "lineStyle": {"width": 0.8, "opacity": 0.7},
                       "data": [[x, y] for x, y in zip(mids, w["counts"]) if y > 0]})
    rng = cov.get("cv_range_nm") or [mids[0], mids[-1]]
    state = "連續" if cov.get("continuous") else f"{len(cov.get('breaks') or [])} 個斷點"
    return {"title": {"text": f"CV 取樣覆蓋（{len(cov.get('windows') or [])} 個 window，{state}）", "textStyle": {"fontSize": 12}},
            "tooltip": {"trigger": "axis"}, "legend": {"show": False},
            "xAxis": {"type": "value", "name": "anchor–配體 COM 距離 (nm)", "min": round(min(rng[0], mids[0]), 3),
                      "max": round(max(rng[1], mids[-1]), 3)},
            "yAxis": {"type": "value", "name": "樣本數"}, "series": series, "grid": {"left": 60, "right": 20}}


def coverage_summary(cov: dict) -> str:
    rounds = cov.get("rounds") or []
    parts = [f"狀態：{cov.get('status', '')}", f"window {len(cov.get('windows') or [])} 個",
             "取樣連續" if cov.get("continuous") else "斷點（紅色）：" + "、".join(f"{a:.3f}–{b:.3f} nm" for a, b in cov.get("breaks") or [])]
    if rounds:
        last = rounds[-1]
        parts.append(f"自動補窗第 {last['round']} 輪：補 {len(last.get('insert') or [])}、延長 {len(last.get('extend') or [])}")
        if last.get("unsamplable"):
            parts.append("在 k 上限仍取樣不到：" + "、".join(f"{a:.3f}–{b:.3f}" for a, b in last["unsamplable"]))
    return "；".join(parts)
