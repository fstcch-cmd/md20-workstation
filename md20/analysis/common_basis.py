"""D-106 (A11 / F12 / F10): systems compared on the same axes, only when their conditions allow it.

Before: every system had its own PCA, so "apo has two basins, the complex has one" compared pictures drawn on
different axes; a short trajectory's projection density was called a free-energy landscape without any check; and
the apo–holo ΔRMSF paired residues by index position and never asked whether the two runs were run the same way.

Here:
  conditions / comparability  what must match for two runs to be compared (temperature, ensemble, production
                              restraints, water model, force field, production length within ×1.25) — with reasons
  common_basis                Cα atoms present in every system (matched by chain:residue label), all frames superposed
                              on one reference, one PCA; each system's landscape on the same bin edges; basins with a
                              representative frame (the frame closest to the basin minimum: an actual structure that
                              can be opened, not an average); a half-split check per system (basin populations in the
                              first vs the second half) — when they disagree, the map is labelled as a sampled density,
                              not a converged free-energy landscape
  delta_rmsf                  residue-matched ΔRMSF, refused when the conditions differ
Pure numpy; the workflow feeds it the Cα coordinates analyse_run saved (analysis/ca_xyz.npy, ca_labels.json).
"""
from __future__ import annotations

import numpy as np

from .extended import free_energy_landscape

HALF_SPLIT_MAX = 0.20          # largest allowed change of a basin population between the two halves


# ------------------------------------------------------------------------------------------- conditions
def conditions(run: dict, build: dict | None = None) -> dict:
    """The comparison-relevant conditions of one run (run.json) and its build manifest."""
    prot = (run or {}).get("protocol") or {}
    prod = next((s for s in prot.get("stages") or [] if s.get("name") == "production"), {})
    rg = prod.get("restraint_groups") or {}
    restrained = sorted(g for g, v in rg.items() if v and max(v if isinstance(v, (list, tuple)) else [v]) > 0) if isinstance(rg, dict) else []
    b = build or {}
    a = b.get("assembly") or {}
    # BuildResult.forcefields = force-field XML files + ligand template generators; the generators exist only when a
    # ligand is present (apo never has one), so only the XML files are compared
    ffs = b.get("forcefields") or a.get("forcefields") or b.get("forcefield_files") or a.get("forcefield_files")
    files = sorted(f for f in ffs if isinstance(f, str) and f.endswith(".xml")) if ffs else None
    solvent = b.get("solvent") or a.get("solvent")
    water = b.get("water_model") or a.get("water_model")
    if water is None and files is not None:
        water = next((f for f in files if any(w in f.lower() for w in ("tip3p", "tip4p", "tip5p", "opc", "spce", "spc"))), None)
        if water is None and solvent and solvent != "explicit":
            water = solvent                                       # implicit solvent: the model is the solvent itself
    return {"temperature_k": prod.get("temperature_k"), "ensemble": prod.get("ensemble"), "production_ps": prod.get("length_ps"),
            "timestep_fs": prod.get("timestep_fs"), "hmr": prot.get("hmr"), "restrained": restrained,
            "water_model": water, "forcefield": files, "solvent": solvent}


def comparability(conds: dict[str, dict]) -> dict:
    """Pairwise-free check over all systems: every listed field equal (production length within ×1.25).  A field
    unknown in any system is reported as unknown, never assumed equal."""
    names = list(conds)
    reasons, unknown = [], []
    for f in ("temperature_k", "ensemble", "restrained", "water_model", "forcefield", "solvent", "hmr"):
        vals = [conds[n].get(f) for n in names]
        if any(v is None for v in vals):
            unknown.append(f)
            continue
        if any(v != vals[0] for v in vals[1:]):
            reasons.append({"field": f, "values": {n: conds[n].get(f) for n in names}})
    lens = [conds[n].get("production_ps") for n in names]
    if any(v is None for v in lens):
        unknown.append("production_ps")
    elif min(lens) > 0 and max(lens) / min(lens) > 1.25:
        reasons.append({"field": "production_ps", "values": {n: conds[n].get("production_ps") for n in names}})
    return {"comparable": not reasons and not unknown, "differences": reasons, "unknown": unknown}


# ------------------------------------------------------------------------------------------- geometry
def kabsch(P: np.ndarray, Q: np.ndarray) -> np.ndarray:
    """Rotate+translate P (N×3) onto Q (N×3); returns the moved P."""
    pc, qc = P.mean(0), Q.mean(0)
    H = (P - pc).T @ (Q - qc)
    U, _, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T
    return (P - pc) @ R.T + qc


def _superpose_all(stack: np.ndarray, iters: int = 3) -> np.ndarray:
    ref = stack[0]
    for _ in range(iters):                                    # iterate onto the average (Procrustes)
        stack = np.array([kabsch(f, ref) for f in stack])
        ref = stack.mean(0)
    return stack


# ------------------------------------------------------------------------------------------- common basis
def common_basis(systems: dict[str, dict], *, temperature_k: float = 300.0, min_common: int = 10) -> dict:
    """systems: {name: {"labels": [chain:res...] per Cα, "xyz": (F, N, 3) Å, "time_ns": [F]}} in display order."""
    names = [n for n in systems if len(systems[n].get("labels") or []) and np.asarray(systems[n]["xyz"]).ndim == 3]
    if len(names) < 2:
        return {"status": "insufficient", "reason": "systems"}
    common = set(systems[names[0]]["labels"])
    for n in names[1:]:
        common &= set(systems[n]["labels"])
    order = [l for l in systems[names[0]]["labels"] if l in common]
    if len(order) < min_common:
        return {"status": "insufficient", "reason": "common_atoms", "n_common": len(order)}
    blocks, owner = [], []
    for n in names:
        idx = {l: i for i, l in enumerate(systems[n]["labels"])}
        x = np.asarray(systems[n]["xyz"], float)[:, [idx[l] for l in order], :]
        blocks.append(x)
        owner += [n] * len(x)
    stack = _superpose_all(np.concatenate(blocks))
    X = stack.reshape(len(stack), -1)
    X = X - X.mean(0)
    U, S, Vt = np.linalg.svd(X, full_matrices=False)
    var = S ** 2
    explained = (var / var.sum())[:2] if var.sum() > 0 else np.zeros(2)
    P = U[:, :2] * S[:2]
    owner = np.array(owner)
    bins = int(np.clip(np.sqrt(len(P)) / 1.5, 12, 30))
    xe = np.linspace(P[:, 0].min(), P[:, 0].max(), bins + 1)
    ye = np.linspace(P[:, 1].min(), P[:, 1].max(), bins + 1)
    out = {"status": "ok", "systems": names, "n_common_ca": len(order), "explained": explained.round(4).tolist(),
           "xedges": xe.tolist(), "yedges": ye.tolist(), "per_system": {}, "representatives": []}
    for n in names:
        p = P[owner == n]
        t = list(systems[n].get("time_ns") or range(len(p)))
        land = free_energy_landscape(p[:, 0], p[:, 1], temperature_k=temperature_k, edges=(xe, ye))
        hs = half_split(p, land.get("basins") or [])
        reps = []
        for b_i, b in enumerate(land.get("basins") or []):
            f = int(np.argmin(((p - np.array(b[:2])) ** 2).sum(1)))
            reps.append({"system": n, "basin": b_i + 1, "frame": f, "time_ns": float(t[f]) if f < len(t) else None,
                         "population": b[3] if len(b) > 3 else None})
        out["representatives"] += reps
        step = max(1, len(p) // 400)
        out["per_system"][n] = {"landscape": land, "half_split": hs, "projection": p[::step].round(3).tolist(),
                                "n_frames": int(len(p))}
    return out


def half_split(p: np.ndarray, basins: list) -> dict:
    """Assign each frame to the nearest basin minimum and compare the populations of the two halves."""
    if len(p) < 20 or not basins:
        return {"status": "insufficient"}
    centres = np.array([b[:2] for b in basins])
    lab = np.argmin(((p[:, None, :] - centres[None]) ** 2).sum(-1), axis=1)
    h = len(p) // 2
    a = np.bincount(lab[:h], minlength=len(centres)) / h
    b = np.bincount(lab[h:], minlength=len(centres)) / (len(p) - h)
    diff = float(np.abs(a - b).max())
    return {"status": "ok", "first": a.round(3).tolist(), "second": b.round(3).tolist(), "max_change": round(diff, 3),
            "consistent": diff <= HALF_SPLIT_MAX}


# ------------------------------------------------------------------------------------------- ΔRMSF
def delta_rmsf(ref: tuple[list, list], other: tuple[list, list], comp: dict | None = None, top: int = 10) -> dict:
    """(labels, rmsf) pairs; residues matched by label (never by position).  Refused when `comp` says the runs are
    not comparable."""
    if comp is not None and not comp.get("comparable"):
        return {"status": "not_comparable", "differences": comp.get("differences"), "unknown": comp.get("unknown")}
    ra = dict(zip(ref[0], ref[1]))
    rb = dict(zip(other[0], other[1]))
    keys = [k for k in ref[0] if k in rb]
    if len(keys) < 5:
        return {"status": "insufficient", "n_common": len(keys)}
    d = np.array([rb[k] - ra[k] for k in keys], float)
    idx = np.argsort(d)
    return {"status": "ok", "n_common": len(keys),
            "most_rigidified": [{"residue": keys[i], "delta_rmsf_A": round(float(d[i]), 3)} for i in idx[:top]],
            "most_flexible": [{"residue": keys[i], "delta_rmsf_A": round(float(d[i]), 3)} for i in idx[::-1][:top]]}
