"""Contact release along the SMD pulling path (D-116; spec F13).

The SMD force curve says WHEN the ligand is held back; this module says WHICH ligand-residue contacts are lost on the way,
and whether they are lost where the force peaks.  It only describes one pull.  The pulling force and the work are not
free energies (D-96), the release points depend on the pulling speed and the spring, and nothing here ranks interactions
by strength.

Data (`smd_path.npz`, written by `sampling/binding.run_binding` during the pull, never changes the SMD protocol):
heavy-atom coordinates of the ligand and of the protein residues near the pocket and near the exit path, at most about
200 frames of the whole pull, with time, CV distance d, spring position and box.  No water.  A result without this file
is "unavailable"; nothing is guessed from the force curve.

Contact definition = `interactions.SEARCH_NM` (any ligand heavy atom within 0.40 nm of any heavy atom of the residue,
minimum image, orthorhombic or triclinic box).  Residue-level: one contact per ligand-residue pair.

For each contact:
  * ``initial``      present in the first stored frame;
  * ``release_d_nm`` CV distance d of the LAST frame in which it is present (the contact is gone within one frame step
                     after this); None when it is still present in the last frame (``released`` False);
  * ``category``     ``at_peak`` when the release is within `PEAK_WINDOW_NM` of the force peak's d, else ``before_peak`` /
                     ``after_peak``; ``not_released``; ``peak_unresolved`` when the peak cannot be placed on the path.
d is not monotone in time (stick-slip), so "last present" is taken in time order and the d of that frame is reported.

Pure numpy; no MD engine.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

from .interactions import SEARCH_NM, min_image_distances, display_labels

SCHEMA = "md20.smd_path/1"
RESULT_SCHEMA = "md20.smd_contacts/1"
CONTACT_NM = SEARCH_NM            # 0.40 nm, the same search radius as the interaction fingerprint
PEAK_WINDOW_NM = 0.05             # release within this distance of the force peak = "released at the peak"
MAX_FRAMES = 200                  # stored frames over the whole pull (about)
MIN_FRAMES = 5                    # fewer than this: nothing to analyse
GOOD_FRAMES = 20                  # fewer than this: analysed, flagged limited
NEAR_NM = 0.8                     # residues kept: any heavy atom within this of the starting ligand ...
PATH_MARGIN_NM = 0.6              # ... or within (ligand radius + this) of the straight exit path
PATH_FILE = "smd_path.npz"
RESULT_FILE = "smd_contacts.json"

REASONS = {
    "no_path_file": "這次拉離沒有記錄沿路徑的座標（舊結果，或記錄當時失敗），所以無法分析接觸釋放。重新拉離才會有。",
    "bad_path_file": "沿路徑的座標檔讀不出來或格式不符，所以無法分析接觸釋放。",
    "too_few_frames": "記錄的幀數太少，無法分析接觸釋放。",
    "no_ligand_atoms": "座標檔裡沒有配體重原子，無法分析接觸釋放。",
    "no_environment": "座標檔裡沒有口袋殘基，無法分析接觸釋放。",
    "no_force_curve": "找不到 SMD 力曲線（smd.tsv），無法把接觸釋放對應到力的峰值。",
}


# ------------------------------------------------------------------------------------------ recording (called by binding)
def path_stride(n_records: int, max_frames: int = MAX_FRAMES) -> int:
    """Record every `stride`-th SMD record so the whole pull keeps at most `max_frames` frames (plus the final state)."""
    return max(1, int(np.ceil(max(1, int(n_records)) / max(1, int(max_frames)))))


def _wrap_near(xyz: np.ndarray, ref: np.ndarray, box: np.ndarray | None) -> np.ndarray:
    """Coordinates shifted by lattice vectors to lie in the cell centred on `ref` (selection only; distances that matter
    later use the full minimum image)."""
    if box is None:
        return xyz
    box = np.asarray(box, float)
    if box.shape == (3,):
        box = np.diag(box)
    f = (xyz - ref) @ np.linalg.inv(box)
    return ref + (f - np.round(f)) @ box


def select_capture(xyz: np.ndarray, box: np.ndarray | None, ligand: np.ndarray, env: np.ndarray, env_res: np.ndarray, *,
                   pull_nm: float, direction: np.ndarray | None, near_nm: float = NEAR_NM,
                   margin_nm: float = PATH_MARGIN_NM) -> dict:
    """Which environment residues to follow: those within `near_nm` of the ligand's starting pose and those along the
    straight exit path of length `pull_nm` in `direction` (anchor to ligand, the direction the spring pulls), within
    ligand radius + `margin_nm` of it.  Whole residues are kept.  Returns {"atoms": env atom indices (sorted),
    "residues": residue ids, "n_near", "n_path", "ligand_radius_nm"}."""
    xyz = np.asarray(xyz, float)
    ligand, env, env_res = np.asarray(ligand, int), np.asarray(env, int), np.asarray(env_res, int)
    if not len(ligand) or not len(env):
        return {"atoms": np.zeros(0, int), "residues": [], "n_near": 0, "n_path": 0, "ligand_radius_nm": 0.0}
    lx = xyz[ligand]
    com0 = lx.mean(0)
    rad = float(np.max(np.linalg.norm(lx - com0, axis=1))) if len(ligand) > 1 else 0.0
    D = min_image_distances(lx, xyz[env], box)
    near_atoms = D.min(axis=0) <= near_nm
    keep = near_atoms.copy()
    path_atoms = np.zeros(len(env), bool)
    if direction is not None and float(np.linalg.norm(direction)) > 0 and pull_nm > 0:
        u = np.asarray(direction, float) / float(np.linalg.norm(direction))
        p = _wrap_near(xyz[env], com0, box) - com0
        t = np.clip(p @ u, 0.0, float(pull_nm))
        path_atoms = np.linalg.norm(p - t[:, None] * u[None, :], axis=1) <= rad + margin_nm
        keep |= path_atoms
    res_keep = set(env_res[keep].tolist())
    sel = np.array([i for i, r in zip(env, env_res) if int(r) in res_keep], int)
    return {"atoms": np.sort(sel), "residues": sorted(res_keep), "n_near": int(len(set(env_res[near_atoms].tolist()))),
            "n_path": int(len(set(env_res[path_atoms].tolist()))), "ligand_radius_nm": rad}


def save_path(out_dir: Path | str, *, time_ps, d_nm, r0_nm, xyz_nm, box_nm, atom_index, atom_res, atom_name, is_ligand,
              res_labels, meta: dict | None = None) -> Path:
    """Write `smd_path.npz` atomically.  xyz_nm (F, A, 3), box_nm (F, 3, 3); atom_res indexes `res_labels`
    (ligand atoms carry -1)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / (PATH_FILE + ".tmp.npz")
    np.savez_compressed(tmp, schema=np.array(SCHEMA), time_ps=np.asarray(time_ps, float), d_nm=np.asarray(d_nm, float),
                        r0_nm=np.asarray(r0_nm, float), xyz_nm=np.asarray(xyz_nm, np.float32),
                        box_nm=np.asarray(box_nm, np.float32), atom_index=np.asarray(atom_index, np.int32),
                        atom_res=np.asarray(atom_res, np.int32), atom_name=np.asarray(atom_name, dtype=str),
                        is_ligand=np.asarray(is_ligand, bool), res_labels=np.asarray(res_labels, dtype=str),
                        meta=np.array(json.dumps(meta or {}, default=lambda o: o.item() if hasattr(o, "item") else str(o))))
    dst = out / PATH_FILE
    os.replace(tmp, dst)
    return dst


def load_path(path: Path | str) -> tuple[dict | None, str | None]:
    """(data, None) or (None, reason_code)."""
    p = Path(path)
    if not p.is_file():
        return None, "no_path_file"
    try:
        with np.load(p, allow_pickle=False) as z:
            if str(z["schema"]) != SCHEMA:
                return None, "bad_path_file"
            d = {k: z[k] for k in ("time_ps", "d_nm", "r0_nm", "xyz_nm", "box_nm", "atom_index", "atom_res", "atom_name",
                                    "is_ligand", "res_labels")}
            d["meta"] = json.loads(str(z["meta"]))
    except Exception:  # noqa: BLE001  (truncated or foreign file)
        return None, "bad_path_file"
    F = len(d["time_ps"])
    if d["xyz_nm"].ndim != 3 or d["xyz_nm"].shape[0] != F or d["xyz_nm"].shape[1] != len(d["is_ligand"]) \
            or len(d["d_nm"]) != F or d["box_nm"].shape[0] != F:
        return None, "bad_path_file"
    return d, None


# ------------------------------------------------------------------------------------------ analysis
def unavailable(code: str, **extra) -> dict:
    return {"schema": RESULT_SCHEMA, "status": "unavailable", "reason_code": code, "why": REASONS.get(code, code),
            "contacts": [], "at_peak": [], **extra}


def _runs(on: np.ndarray) -> list[tuple[int, int]]:
    out, start = [], None
    for i, v in enumerate(on):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(on) - 1))
    return out


def force_peak(time_ps, d_nm, force, r0_nm=None) -> dict | None:
    """Position of the main force peak on the pull: argmax of the force smoothed over ~1 % of the records (a single noisy
    record is not a rupture).  Returns the ligand CV distance d at the peak, not the spring position."""
    t, d, f = (np.asarray(x, float) for x in (time_ps, d_nm, force))
    n = len(f)
    if n < 10 or len(d) != n or not np.all(np.isfinite(f)):
        return None
    w = max(3, n // 100)
    if w % 2 == 0:
        w += 1
    sm = np.convolve(f, np.ones(w) / w, mode="valid")
    i = int(np.argmax(sm)) + w // 2
    out = {"index": int(i), "time_ps": float(t[i]), "d_nm": float(d[i]), "force_kj_mol_nm": float(sm[int(np.argmax(sm))]),
           "max_raw_force_kj_mol_nm": float(f.max()), "smooth_records": int(w)}
    if r0_nm is not None and len(r0_nm) == n:
        out["r0_nm"] = float(np.asarray(r0_nm, float)[i])
    return out


def residue_distances(path: dict, cutoff_nm: float = CONTACT_NM) -> dict:
    """Per frame and residue: the smallest heavy-atom distance to the ligand (nm) and the atom pair that gives it.
    Returns {"dmin": (F, R), "lig_atom": (F, R) index into the ligand atoms, "env_atom": (F, R) index into the env atoms}."""
    xyz, box = path["xyz_nm"].astype(float), path["box_nm"].astype(float)
    lig = np.nonzero(path["is_ligand"])[0]
    env = np.nonzero(~path["is_ligand"])[0]
    res = path["atom_res"][env]
    ids = np.unique(res)
    order = np.argsort(res, kind="stable")
    env, res = env[order], res[order]
    starts = np.r_[0, np.nonzero(np.diff(res))[0] + 1]
    F, R = xyz.shape[0], len(starts)
    dmin = np.full((F, R), np.inf)
    la = np.zeros((F, R), np.int32)
    ea = np.zeros((F, R), np.int32)
    for f in range(F):
        D = min_image_distances(xyz[f, lig], xyz[f, env], box[f])         # (L, E)
        col_min, col_arg = D.min(axis=0), D.argmin(axis=0)
        for k in range(R):
            s, e = starts[k], (starts[k + 1] if k + 1 < R else len(env))
            j = int(np.argmin(col_min[s:e]))
            dmin[f, k] = col_min[s + j]
            la[f, k] = col_arg[s + j]
            ea[f, k] = s + j
    return {"dmin": dmin, "lig_atom": la, "env_atom": ea, "res_ids": ids, "lig": lig, "env": env}


def analyse(path: dict, smd: dict | None, *, cutoff_nm: float = CONTACT_NM, peak_window_nm: float = PEAK_WINDOW_NM) -> dict:
    """Release of every ligand-residue contact along the pull and its relation to the force peak.
    `smd` = {"time_ps", "r0_nm", "d_nm", "force"} (the columns of smd.tsv) or None."""
    F = len(path["time_ps"])
    if F < MIN_FRAMES:
        return unavailable("too_few_frames", n_frames=int(F))
    if not path["is_ligand"].any():
        return unavailable("no_ligand_atoms")
    if path["is_ligand"].all():
        return unavailable("no_environment")
    if not smd or smd.get("force") is None or len(smd["force"]) < 10:
        return unavailable("no_force_curve")
    d = np.asarray(path["d_nm"], float)
    t = np.asarray(path["time_ps"], float)
    pk = force_peak(smd["time_ps"], smd["d_nm"], smd["force"], smd.get("r0_nm"))
    if pk is None:
        return unavailable("no_force_curve")
    step = float(np.median(np.abs(np.diff(d)))) if F > 1 else 0.0
    nearest = float(np.min(np.abs(d - pk["d_nm"])))
    peak_ok = nearest <= peak_window_nm
    rd = residue_distances(path, cutoff_nm)
    present = rd["dmin"] < cutoff_nm                                    # (F, R)
    labels_all = [str(path["res_labels"][int(i)]) for i in rd["res_ids"]]
    atom_name = path["atom_name"]
    contacts = []
    for k, rid in enumerate(rd["res_ids"]):
        on = present[:, k]
        if not on.any():
            continue
        idx = np.nonzero(on)[0]
        first, last = int(idx[0]), int(idx[-1])
        runs = _runs(on)
        released = last < F - 1
        rel_d = float(d[last]) if released else None
        off = (rel_d - pk["d_nm"]) if (released and peak_ok) else None
        if not released:
            cat = "not_released"
        elif not peak_ok:
            cat = "peak_unresolved"
        elif abs(off) <= peak_window_nm:
            cat = "at_peak"
        else:
            cat = "before_peak" if off < 0 else "after_peak"
        li, ei = int(rd["lig"][rd["lig_atom"][first, k]]), int(rd["env"][rd["env_atom"][first, k]])
        contacts.append({
            "residue": labels_all[k], "initial": bool(on[0]), "first_d_nm": float(d[first]), "first_time_ps": float(t[first]),
            "released": bool(released), "release_d_nm": rel_d, "release_time_ps": float(t[last]) if released else None,
            "offset_from_peak_nm": None if off is None else float(off), "category": cat,
            "n_runs": int(len(runs)), "runs": [[int(a), int(b)] for a, b in runs], "fraction_of_frames": float(on.mean()),
            "closest_pair_at_first": f"{atom_name[li]} - {atom_name[ei]}",
            "closest_nm_at_first": float(rd["dmin"][first, k]),
        })
    contacts.sort(key=lambda c: (c["release_d_nm"] if c["release_d_nm"] is not None else np.inf, c["first_d_nm"], c["residue"]))
    at_peak = sorted((c for c in contacts if c["category"] == "at_peak"), key=lambda c: abs(c["offset_from_peak_nm"]))
    init = [c for c in contacts if c["initial"]]
    caveats = ["capture_limited", "rate_dependent"]
    limited = []
    if F < GOOD_FRAMES:
        limited.append("few_frames")
    if step > peak_window_nm / 2:
        limited.append("coarse_steps")
    if not peak_ok:
        limited.append("peak_off_path")
    if limited:
        caveats.append("limited_resolution")
    disp = display_labels([c["residue"] for c in contacts])
    for c in contacts:
        c["label"] = disp[c["residue"]]
    return {
        "schema": RESULT_SCHEMA, "status": "limited" if limited else "ok", "limited_by": limited, "reason_code": None, "why": "",
        "cutoff_nm": float(cutoff_nm), "peak_window_nm": float(peak_window_nm),
        "n_frames": int(F), "d_range_nm": [float(d.min()), float(d.max())], "frame_step_nm": step,
        "peak": {**pk, "resolved": bool(peak_ok), "nearest_frame_d_nm": nearest},
        "frames": {"d_nm": [round(float(x), 4) for x in d], "time_ps": [round(float(x), 3) for x in t]},
        "contacts": contacts, "at_peak": [c["residue"] for c in at_peak],
        "n_contacts": len(contacts), "n_initial": len(init), "n_initial_released": sum(1 for c in init if c["released"]),
        "n_initial_at_peak": sum(1 for c in init if c["category"] == "at_peak"),
        "n_formed_later": sum(1 for c in contacts if not c["initial"]),
        "n_not_released": sum(1 for c in contacts if not c["released"]),
        "capture": dict(path.get("meta") or {}), "caveat_codes": caveats,
    }


def read_smd_curve(tsv: Path | str) -> dict | None:
    """Columns of smd.tsv (time_ps, r0_nm, d_nm, force_kj_mol_nm, work_kj_mol)."""
    p = Path(tsv)
    if not p.is_file():
        return None
    try:
        a = np.loadtxt(p, delimiter="\t", ndmin=2)
    except Exception:  # noqa: BLE001
        return None
    if a.ndim != 2 or a.shape[1] < 5 or a.shape[0] < 10:
        return None
    return {"time_ps": a[:, 0], "r0_nm": a[:, 1], "d_nm": a[:, 2], "force": a[:, 3]}


def from_files(out_dir: Path | str) -> dict:
    """Analyse the pull stored in `out_dir` (smd_path.npz + smd.tsv).  Deterministic, so a resumed or rebuilt run gets the
    same answer; a folder without the path file is "unavailable" (never inferred from the force curve)."""
    out = Path(out_dir)
    data, why = load_path(out / PATH_FILE)
    if data is None:
        return unavailable(why or "no_path_file")
    return analyse(data, read_smd_curve(out / "smd.tsv"))
