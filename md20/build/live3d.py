"""D-104: live 3D while a membrane system is built.

The build writes one small scene per sub-step to <build dir>/live3d/ and the GUI's 3D tab shows the newest one,
refreshing while the build runs:

  01_solute    solute oriented (protein) or placed above the membrane (surface), with the planes where the
               phosphate layers will go — the student sees the orientation before the slow bilayer step
  02_bilayer   lipids added around / below the solute (heads and a thinned set of tail atoms)
  03_declashed after the water de-clash (D-102), with the number of waters removed

Water is never drawn (tens of thousands of atoms that hide everything); ions are drawn small.  Lipid tails are
thinned so a scene stays under `max_atoms` (Canvas 2D in the browser, no WebGL).  Coordinates are in Å, the
viewer's unit.  This module must not import OpenMM: `atoms_from_topology` duck-types OpenMM's Topology.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np

LIVE_DIR = "live3d"
CURRENT = "live3d_current.json"            # in the workflow folder: which case is being built now
WATER = {"HOH", "WAT", "TIP3", "SOL"}
IONS = {"NA", "CL", "K", "NA+", "CL-", "LI", "RB", "CS", "BR", "F", "I", "MG", "CA", "ZN"}
PROTEIN = {"ALA", "ARG", "ASN", "ASP", "ASH", "CYS", "CYM", "CYX", "GLN", "GLU", "GLH", "GLY", "HIS", "HID", "HIE", "HIP",
           "ILE", "LEU", "LYS", "LYN", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL", "ACE", "NME"}
HEAD_NAMES = {"P", "N", "O3"}             # phosphate P and choline/amine N; O3 = cholesterol hydroxyl (CHL1)
SMALL_PROTEIN = 60                         # up to this many residues the protein is drawn with all heavy atoms

STAGE_TEXT = {
    "solute": ("溶質已定向／放置，虛線是磷原子層將來的位置", "Solute oriented or placed. Dashed outlines mark where the phosphate layers will go",
               "溶質を配向・配置しました。破線はリン原子層が置かれる位置です", "용질을 배향·배치했습니다. 점선은 인 원자층이 놓일 위치입니다"),
    "bilayer": ("已加入脂雙層（水不顯示）", "Bilayer added (water not shown)", "脂質二重層を追加しました（水は非表示）",
                "지질 이중층을 추가했습니다(물은 표시하지 않음)"),
    "declashed": ("重疊的水已移除，建模完成前的最後結構", "Overlapping waters removed: the structure before the system is created",
                  "重なった水を削除しました。系を作る直前の構造です", "겹친 물을 제거했습니다. 계를 만들기 직전 구조입니다"),
}


def atoms_from_topology(topology) -> list[dict]:
    """{e, n, r, s, c} per atom from an OpenMM-like Topology (atoms() with .element.symbol, .name, .residue)."""
    out = []
    for a in topology.atoms():
        el = a.element.symbol if getattr(a, "element", None) is not None else ""
        r = a.residue
        out.append({"e": el, "n": a.name, "r": r.name, "s": str(getattr(r, "id", r.index)),
                    "c": str(getattr(r.chain, "id", ""))})
    return out


def membrane_scene(atoms: list[dict], xyz_nm, *, lipid_indices=(), head_indices=(), planes_nm=(), box_nm=None,
                   max_atoms: int = 9000, stage: str = "", lang_labels: tuple | None = None) -> dict:
    """Scene for md20view.js.  Kinds: T Cα trace, P protein heavy atom (small proteins/peptides), L other solute,
    H lipid head, A lipid tail (thinned), I ion.  `planes_nm`: z of the phosphate planes; `box_nm`: (lx, ly, lz)."""
    xyz = np.asarray(xyz_nm, dtype=float).reshape(-1, 3) * 10.0
    lip = set(int(i) for i in lipid_indices)
    heads = set(int(i) for i in head_indices)
    n_res = len({(a["c"], a["s"]) for a in atoms if a["r"] in PROTEIN})
    keep, kind = [], {}
    tails = []
    for i, a in enumerate(atoms):
        if a["r"] in WATER or a["e"] == "H":
            continue
        if i in lip:
            if i in heads or a["n"] in HEAD_NAMES:
                keep.append(i); kind[i] = "H"
            else:
                tails.append(i)
        elif a["r"] in IONS and a["n"].upper().rstrip("+-") == a["r"].rstrip("+-"):
            keep.append(i); kind[i] = "I"
        elif a["r"] in PROTEIN:
            if n_res <= SMALL_PROTEIN:
                keep.append(i); kind[i] = "P"
            elif a["n"] == "CA":
                keep.append(i); kind[i] = "T"
        else:
            keep.append(i); kind[i] = "L"
    room = max(0, max_atoms - len(keep))
    step = max(1, int(np.ceil(len(tails) / room))) if room else len(tails) + 1
    thinned = tails[::step] if room else []
    for i in thinned:
        kind[i] = "A"
    keep = sorted(keep + thinned)[:max_atoms]
    idx = {old: new for new, old in enumerate(keep)}
    sa = [{"e": atoms[i]["e"], "n": atoms[i]["n"], "r": atoms[i]["r"], "s": atoms[i]["s"], "k": kind[i]} for i in keep]
    bonds = []
    trace = [i for i in keep if kind[i] in ("T", "P") and atoms[i]["n"] == "CA"]
    for a_i in range(len(trace) - 1):
        i, j = trace[a_i], trace[a_i + 1]
        if atoms[i]["c"] == atoms[j]["c"] and np.linalg.norm(xyz[i] - xyz[j]) < 4.3:
            bonds.append([idx[i], idx[j]])
    solute = [i for i in keep if kind[i] in ("P", "L")]
    sx = xyz[solute] if solute else np.zeros((0, 3))
    for a_i, i in enumerate(solute):                        # covalent bonds inside the solute (distance-based)
        d = np.linalg.norm(sx[a_i + 1:] - sx[a_i], axis=1)
        for off in np.where(d < 1.9)[0]:
            bonds.append([idx[i], idx[solute[a_i + 1 + int(off)]]])
    frame = xyz[keep].round(2).reshape(-1).tolist()
    scene = {"atoms": sa, "bonds": bonds, "frames": [frame], "interactions": {"frames": [[]]},
             "summary": {"n_ligand_atoms": sum(1 for i in keep if kind[i] in ("L", "P")), "n_pocket_residues": 0,
                         "n_frames": 1, "n_lipid_heads": sum(1 for i in keep if kind[i] == "H"),
                         "n_tail_atoms_shown": len(thinned), "n_tail_atoms": len(tails), "tail_stride": step if room else 0},
             "stage": stage}
    if box_nm is not None:
        scene["box"] = [round(float(v) * 10.0, 2) for v in box_nm]
    if planes_nm:
        scene["planes"] = [round(float(z) * 10.0, 2) for z in planes_nm]
    if len(keep):
        lo, hi = xyz[keep].min(0), xyz[keep].max(0)
        c = (lo + hi) / 2.0                                   # centre of everything drawn: the membrane is the subject
        scene["center"] = c.round(2).tolist()
        scene["extent"] = round(float(max(6.0, np.linalg.norm(hi - lo) / 2.0)), 2)
    if lang_labels:
        scene["stage_label"] = list(lang_labels)
    return scene


def _write(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for k in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:          # Windows: the GUI is reading the file this instant
            time.sleep(0.05 * (k + 1))
    tmp.unlink(missing_ok=True)


def write_stage(build_dir, stage: str, scene: dict, *, note: str = "") -> Path:
    """Add one stage to <build dir>/live3d/ and update index.json (newest last).  Never raises: a viewer problem must
    not stop a build."""
    d = Path(build_dir) / LIVE_DIR
    try:
        idx = read_index(build_dir)
        order = [s["stage"] for s in idx.get("stages", [])]
        n = order.index(stage) + 1 if stage in order else len(order) + 1
        f = d / f"{n:02d}_{stage}.json"
        _write(scene, f)
        stages = [s for s in idx.get("stages", []) if s["stage"] != stage]
        stages.append({"stage": stage, "file": f.name, "at": time.time(), "note": note,
                       "label": list(STAGE_TEXT.get(stage, (stage,) * 4))})
        _write({"updated_at": time.time(), "stages": stages}, d / "index.json")
        return f
    except Exception:  # noqa: BLE001
        return d


def read_index(build_dir) -> dict:
    try:
        return json.loads((Path(build_dir) / LIVE_DIR / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def latest_scene(build_dir) -> tuple[dict | None, dict | None]:
    """(scene, stage entry) of the newest stage, or (None, None)."""
    idx = read_index(build_dir)
    if not idx.get("stages"):
        return None, None
    st = idx["stages"][-1]
    try:
        return json.loads((Path(build_dir) / LIVE_DIR / st["file"]).read_text(encoding="utf-8")), st
    except (OSError, ValueError):
        return None, None


def snapshot_modeller(build_dir, stage: str, modeller, *, lipid_indices=(), head_indices=(), planes_nm=(), note: str = "") -> None:
    """OpenMM Modeller → write_stage.  Box from the topology's periodic vectors when set."""
    try:
        from openmm import unit
        xyz = np.asarray(modeller.positions.value_in_unit(unit.nanometer), float)
        vecs = modeller.topology.getPeriodicBoxVectors()
        box = [float(vecs[i][i].value_in_unit(unit.nanometer)) for i in range(3)] if vecs else None
        scene = membrane_scene(atoms_from_topology(modeller.topology), xyz, lipid_indices=lipid_indices,
                               head_indices=head_indices, planes_nm=planes_nm, box_nm=box, stage=stage,
                               lang_labels=STAGE_TEXT.get(stage))
        write_stage(build_dir, stage, scene, note=note)
    except Exception:  # noqa: BLE001  (the 3D view is a convenience; the build goes on)
        pass


def ranges_to_indices(ranges) -> list[int]:
    out = []
    for r in ranges or []:
        out.extend(range(int(r[0]), int(r[1])))      # membrane.index_ranges: [start, stop)
    return out


def mark_current(wf_dir, key: str, build_dir) -> None:
    """The workflow tells the GUI which case it is building now (the case is recorded in state.json only after)."""
    _write({"key": key, "build_dir": str(build_dir), "at": time.time()}, Path(wf_dir) / CURRENT)


def current(wf_dir) -> dict:
    try:
        return json.loads((Path(wf_dir) / CURRENT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
