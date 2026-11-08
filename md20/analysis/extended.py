"""Extended trajectory analysis (D-58): everything the production trajectory supports beyond RMSD/RMSF/contacts.

Two layers:
  * pure numpy (tested everywhere): PCA, free-energy landscape, (D-105, toolbox.py) tICA/MSM, H-bond network, hydration; clustering from an RMSD matrix, cross-correlation,
    hydrogen-bond and fingerprint aggregation, block averages;
  * `extended_metrics(traj, ligand_groups)` (mdtraj, run in the analysis step): extracts the per-frame data and
    calls the pure functions.  Every block is independent and wrapped, so one failure never loses the others.

Result (JSON-able) is written to analysis/extended.json; the report draws and explains every part (report_language.md).
"""
from __future__ import annotations

import numpy as np

EXTENDED_SCHEMA = "md20.extended/3"      # D-135: bump when extended.json gains/changes fields (invalidates cached analyses)
MAX_FRAMES = 250            # frames used for the expensive parts (SASA, clustering, water bridges)
SENSITIVITY_TOLERANCES = {"pc1_abs_cos_min": 0.9, "explained_abs_diff_max": 0.10, "largest_cluster_abs_diff_max": 0.15,
                          "basis": "declared reporting thresholds (empirical); applied to chronological halves (D-144); not a convergence criterion"}
ALL_FRAMES_PCA_MAX_ELEMENTS = 20_000_000   # frames × 3·N_Cα above which the all-frame PCA comparison is skipped as costly
HB_DIST_NM = 0.35           # donor–acceptor heavy-atom distance for a hydrogen bond
HYDROPHOBIC_NM = 0.40
IONIC_NM = 0.40
WATER_BRIDGE_NM = 0.35

HYDROPHOBIC_RES = {"ALA", "VAL", "LEU", "ILE", "MET", "PHE", "TRP", "PRO", "TYR", "CYS"}
POS_ATOMS = {("LYS", "NZ"), ("ARG", "NH1"), ("ARG", "NH2"), ("ARG", "NE"), ("HIP", "ND1"), ("HIP", "NE2")}
NEG_ATOMS = {("ASP", "OD1"), ("ASP", "OD2"), ("GLU", "OE1"), ("GLU", "OE2")}


# =========================================================================================== pure numpy
def frame_indices(n: int, max_frames: int | None = None) -> np.ndarray:
    """Uniform subsample of `n` frames (display / expensive-estimator input; never an event-detection input)."""
    max_frames = MAX_FRAMES if max_frames is None else max_frames
    return np.unique(np.linspace(0, n - 1, min(n, max_frames)).astype(int)) if n else np.array([], int)


def pca(xyz: np.ndarray, n_components: int = 3) -> dict:
    """xyz: frames × atoms × 3 (already superposed).  Returns projections and explained variance."""
    X = xyz.reshape(len(xyz), -1).astype(float)
    X = X - X.mean(0)
    if len(X) < 3:
        return {}
    U, S, Vt = np.linalg.svd(X, full_matrices=False)
    var = S ** 2 / max(1, len(X) - 1)
    frac = var / var.sum() if var.sum() > 0 else var
    k = min(n_components, len(S))
    proj = U[:, :k] * S[:k]
    return {"projection": proj.tolist(), "explained": frac[:k].round(4).tolist(),
            "cumulative": float(frac[:k].sum())}


def _pca_axes(X: np.ndarray, k: int):
    X = np.asarray(X, float).reshape(len(X), -1)
    X = X - X.mean(0)
    _, S, Vt = np.linalg.svd(X, full_matrices=False)
    var = S ** 2 / max(1, len(X) - 1)
    frac = var / var.sum() if var.sum() > 0 else var
    k = min(k, len(S))
    return frac[:k], Vt[:k]


def _subspace_overlap(Va: np.ndarray, Vb: np.ndarray) -> float:
    k = min(len(Va), len(Vb))
    return float(np.linalg.norm(Va[:k] @ Vb[:k].T) ** 2 / k) if k else 0.0


def pca_sensitivity(xyz_sel: np.ndarray, xyz_all: np.ndarray | None = None, *, n_components: int = 3,
                    max_all_elements: int = ALL_FRAMES_PCA_MAX_ELEMENTS) -> dict:
    """R3 (D-135): how much do the PCA axes depend on WHICH frames were subsampled?  Reported, not promised.

      interleaved_halves  PCA on the even and on the odd frames of the subsample: explained variance of each, |cos| of
                          the two PC1s, mean squared overlap of the leading subspaces (1 = identical subspace)
      all_frames          the subsample's PCA vs PCA of every analysed frame, when that is cheap enough
    `consistent` compares against SENSITIVITY_TOLERANCES (declared reporting thresholds, not a convergence test)."""
    tol = SENSITIVITY_TOLERANCES
    X = np.asarray(xyz_sel, float).reshape(len(xyz_sel), -1)
    out: dict = {"tolerances": tol, "n_frames_subsample": int(len(X)),
                 "note": "sensitivity of the PCA axes to the choice of frames; it does not show that the landscape has "
                         "converged, and a larger frame cap would not guarantee convergence"}
    if len(X) < 8:
        out["interleaved_halves"] = {"status": "insufficient", "reason": f"{len(X)} frames in the subsample"}
        out["consistent"] = None
        return out
    def _cmp(A, B, la, lb):
        fa, Va = _pca_axes(A, n_components)
        fb, Vb = _pca_axes(B, n_components)
        k = min(len(fa), len(fb))
        return {"status": "ok", f"explained_{la}": fa[:k].round(4).tolist(), f"explained_{lb}": fb[:k].round(4).tolist(),
                "pc1_abs_cos": round(float(abs(Va[0] @ Vb[0])), 4), "subspace_overlap": round(_subspace_overlap(Va, Vb), 4),
                "max_explained_abs_diff": round(float(np.abs(fa[:k] - fb[:k]).max()), 4)}
    f0, V0 = _pca_axes(X, n_components)
    h = len(X) // 2
    # D-144: the chronological first/second halves are what can reveal slow, unconverged sampling; the interleaved
    # (even/odd) halves of an autocorrelated trajectory are nearly the same data and agree even when the halves in time
    # disagree completely (synthetic AR(1) calibration: docs/specs/thresholds_calibration.md) — reported as
    # subsample noise only and never used for `consistent`
    out["block_halves"] = {**_cmp(X[:h], X[h:], "first", "second"),
                           "note": "chronological halves of the subsample: sensitive to drift and slow sampling"}
    out["interleaved_halves"] = {**_cmp(X[0::2], X[1::2], "even", "odd"),
                                 "note": "subsample noise only: agrees for autocorrelated frames even when sampling is "
                                         "unconverged; not used for `consistent`"}
    ok = [out["block_halves"]["pc1_abs_cos"] >= tol["pc1_abs_cos_min"],
          out["block_halves"]["max_explained_abs_diff"] <= tol["explained_abs_diff_max"]]
    if xyz_all is None:
        out["all_frames"] = {"status": "skipped", "reason": "not provided"}
    else:
        Xa = np.asarray(xyz_all)
        if Xa.size > max_all_elements:
            out["all_frames"] = {"status": "skipped", "reason": f"{Xa.shape[0]} frames × {Xa.reshape(len(Xa), -1).shape[1]} "
                                                                 f"coordinates exceeds {max_all_elements:,} elements"}
        else:
            fz, Vz = _pca_axes(Xa, n_components)
            kk = min(len(fz), len(f0))
            out["all_frames"] = {"status": "ok", "n_frames": int(len(Xa)), "explained_all": fz[:kk].round(4).tolist(),
                                 "explained_subsample": f0[:kk].round(4).tolist(),
                                 "pc1_abs_cos": round(float(abs(V0[0] @ Vz[0])), 4),
                                 "subspace_overlap": round(_subspace_overlap(V0, Vz), 4),
                                 "max_explained_abs_diff": round(float(np.abs(f0[:kk] - fz[:kk]).max()), 4)}
            ok += [out["all_frames"]["pc1_abs_cos"] >= tol["pc1_abs_cos_min"],
                   out["all_frames"]["max_explained_abs_diff"] <= tol["explained_abs_diff_max"]]
    out["consistent"] = bool(all(ok))
    return out


def cluster_sensitivity(D: np.ndarray, cutoff_A: float = 2.0) -> dict:
    """R3 (D-135): the same clustering on the interleaved halves of the subsample (even / odd frames) — number of
    clusters and the largest cluster's population.  Reported, not a convergence claim."""
    D = np.asarray(D, float)
    tol = SENSITIVITY_TOLERANCES
    if len(D) < 8:
        return {"status": "insufficient", "tolerances": tol, "reason": f"{len(D)} frames in the subsample"}
    res = {}
    h = len(D) // 2
    for name, ix in (("all_subsample", np.arange(len(D))), ("even", np.arange(0, len(D), 2)), ("odd", np.arange(1, len(D), 2)),
                     ("first_half", np.arange(0, h)), ("second_half", np.arange(h, len(D)))):
        c = cluster_from_rmsd(D[np.ix_(ix, ix)], cutoff_A=cutoff_A)
        res[name] = {"n_frames": int(len(ix)), "n_clusters": c["n_clusters"], "largest_population": max(c["populations"])}
    diff = abs(res["even"]["largest_population"] - res["odd"]["largest_population"])
    bdiff = abs(res["first_half"]["largest_population"] - res["second_half"]["largest_population"])
    # D-144: `consistent` from the chronological halves; even/odd is subsample noise only (see pca_sensitivity)
    return {"status": "ok", "tolerances": tol, **res, "largest_population_abs_diff": round(float(diff), 4),
            "block_largest_population_abs_diff": round(float(bdiff), 4),
            "consistent": bool(bdiff <= tol["largest_cluster_abs_diff_max"]),
            "note": "sensitivity to which frames were subsampled; the cluster count is a property of the cutoff and the "
                    "subsample, not a converged conformational census"}


def _smooth2d(H: np.ndarray, sigma: float = 1.0) -> np.ndarray:
    r = int(3 * sigma)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    pad = np.pad(H, r, mode="constant")
    a = np.apply_along_axis(lambda v: np.convolve(v, k, mode="valid"), 0, pad)
    return np.apply_along_axis(lambda v: np.convolve(v, k, mode="valid"), 1, a)


def free_energy_landscape(p1, p2, *, temperature_k: float = 300.0, bins: int | None = None, min_population: float = 0.05,
                          edges: tuple | None = None) -> dict:
    """−kT ln P(PC1, PC2) in kJ/mol from a lightly smoothed histogram, minimum set to 0; empty bins are NaN.
    Basins are connected regions below 1 kT that hold at least `min_population` of the frames (sampling noise in a
    sparse histogram is not counted as a state).  Bins scale with the number of frames (√n / 1.5, 10 to 30)."""
    p1, p2 = np.asarray(p1, float), np.asarray(p2, float)
    n = len(p1)
    if n < 10:
        return {}
    if edges is not None:                       # D-106: several systems on the same bins (common basis)
        H, xe, ye = np.histogram2d(p1, p2, bins=[np.asarray(edges[0]), np.asarray(edges[1])])
        bins = len(xe) - 1
    else:
        bins = bins or int(np.clip(np.sqrt(n) / 1.5, 10, 30))
        H, xe, ye = np.histogram2d(p1, p2, bins=bins)
    Hs = _smooth2d(H, 1.0)
    P = Hs / Hs.sum()
    kT = 0.0083145 * temperature_k
    with np.errstate(divide="ignore"):
        G = -kT * np.log(P)
    G[(~np.isfinite(G)) | (Hs < 1e-3 * Hs.max())] = np.nan
    G -= np.nanmin(G)
    low = np.isfinite(G) & (G < 1.0 * kT)
    seen = np.zeros_like(low)
    basins = []
    for i in range(bins):
        for j in range(bins):
            if not low[i, j] or seen[i, j]:
                continue
            stack, cells = [(i, j)], []
            seen[i, j] = True
            while stack:
                a_, b_ = stack.pop()
                cells.append((a_, b_))
                for da, db in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    x, y = a_ + da, b_ + db
                    if 0 <= x < bins and 0 <= y < bins and low[x, y] and not seen[x, y]:
                        seen[x, y] = True
                        stack.append((x, y))
            # population: frames in the region and its one-bin rim (the smoothing spreads a state slightly)
            rim = {(x + da, y + db) for x, y in cells for da in (-1, 0, 1) for db in (-1, 0, 1)
                   if 0 <= x + da < bins and 0 <= y + db < bins}
            pop = sum(H[x, y] for x, y in rim) / n
            if pop < min_population:
                continue
            ci, cj = min(cells, key=lambda c: G[c])
            basins.append([float((xe[ci] + xe[ci + 1]) / 2), float((ye[cj] + ye[cj + 1]) / 2), float(G[ci, cj]), round(float(pop), 3)])
    return {"G": np.where(np.isfinite(G), G.round(3), None).tolist(), "xedges": xe.tolist(), "yedges": ye.tolist(),
            "basins": sorted(basins, key=lambda b: -b[3]), "kT": kT}


def cluster_from_rmsd(D: np.ndarray, cutoff_A: float = 2.0) -> dict:
    """GROMOS-style clustering on a symmetric RMSD matrix (Å): repeatedly take the frame with the most neighbours
    within the cutoff as the centre of a cluster and remove them.  Returns labels, populations and centres."""
    D = np.asarray(D, float)
    n = len(D)
    if n == 0:
        return {}
    left = np.ones(n, bool)
    labels = -np.ones(n, int)
    centres, pops = [], []
    k = 0
    while left.any():
        nb = (D <= cutoff_A) & left[None, :] & left[:, None]
        counts = nb.sum(1)
        c = int(np.argmax(np.where(left, counts, -1)))
        members = np.where(nb[c])[0]
        labels[members] = k
        left[members] = False
        centres.append(c)
        pops.append(len(members))
        k += 1
    pops = np.asarray(pops)
    return {"labels": labels.tolist(), "centres": centres, "populations": (pops / n).round(4).tolist(),
            "n_clusters": int(k), "cutoff_A": cutoff_A}


def cross_correlation(xyz: np.ndarray) -> np.ndarray:
    """Dynamic cross-correlation of atom displacements (frames × atoms × 3) → atoms × atoms in [−1, 1]."""
    d = xyz - xyz.mean(0)
    cov = np.einsum("fik,fjk->ij", d, d) / len(d)
    diag = np.sqrt(np.clip(np.diag(cov), 1e-12, None))
    return np.clip(cov / np.outer(diag, diag), -1, 1)


def occupancy(per_frame: list[list], n_frames: int, top: int = 30) -> list[list]:
    """per_frame: list (frames) of lists of hashable keys → [[key, fraction], …] sorted by fraction."""
    cnt: dict = {}
    for fr in per_frame:
        for k in set(fr):
            cnt[k] = cnt.get(k, 0) + 1
    return [[k, round(v / max(1, n_frames), 4)] for k, v in sorted(cnt.items(), key=lambda kv: -kv[1])[:top]]


def block_average(y, n_blocks: int = 5) -> dict:
    """Mean and the standard error from block averages (accounts for time correlation)."""
    y = np.asarray(y, float)
    if len(y) < n_blocks * 2:
        return {}
    blocks = np.array_split(y, n_blocks)
    means = np.array([b.mean() for b in blocks])
    return {"mean": float(y.mean()), "sem": float(means.std(ddof=1) / np.sqrt(n_blocks)), "block_means": means.round(4).tolist()}


def histogram_overlap_matrix(samples: dict, bins: int = 80) -> dict:
    """Pairwise overlap (∑ min(p_i, p_j)) of umbrella window distributions on a common grid."""
    keys = sorted(samples)
    if len(keys) < 2:
        return {}
    allv = np.concatenate([np.asarray(samples[k], float) for k in keys])
    edges = np.linspace(allv.min(), allv.max(), bins + 1)
    P = []
    for k in keys:
        h, _ = np.histogram(np.asarray(samples[k], float), bins=edges)
        P.append(h / max(1, h.sum()))
    P = np.array(P)
    O = np.minimum(P[:, None, :], P[None, :, :]).sum(-1)
    nb = [float(O[i, i + 1]) for i in range(len(keys) - 1)]
    return {"centers": [float(k) for k in keys], "matrix": O.round(4).tolist(), "neighbour": [round(x, 4) for x in nb],
            "min_neighbour": round(min(nb), 4)}


# =========================================================================================== mdtraj layer
def _label(top, i: int) -> str:
    a = top.atom(int(i))
    return f"{a.residue.name}{a.residue.resSeq}:{a.name}"


def _res_label(top, i: int) -> str:
    r = top.atom(int(i)).residue
    return f"{r.name}{r.resSeq}"


def _persistence(fp: dict, *, max_gap_ps: float = 0.0, min_occupancy: float = 0.1, top: int = 12,
                 resolution: dict | None = None) -> dict:
    """F09 (D-97, D-135): residue-level persistence of each interaction label on the frames given to the fingerprint
    (`resolution` states whether these are all stored frames or a stride-decimated subset; stride > 1 ⇒ "limited")."""
    from .persistence import EventAccumulator, select_interactions, persistence_report
    t = fp.get("time_ps")
    if not t or len(t) != fp.get("n_frames"):
        return {"status": "unavailable", "reason": "stored frame times are not recorded"}
    selected = select_interactions(fp.get("occupancy") or {}, min_occupancy=min_occupancy, top=top)
    acc = EventAccumulator(run_id="this_run", max_gap_ps=max_gap_ps)
    on = {}
    for r, lab in selected:
        on[(r, lab)] = (np.asarray(fp["bitmask"][fp["residues"].index(r)]) & fp["bits"][lab]) > 0
    acc.update(on, t)
    return persistence_report(acc, selected, resolution=resolution,
                              source="frames given to the fingerprint (see resolution)")


def _sampling_record(n_analysed: int, sel: np.ndarray, resolution: dict) -> dict:
    """R3 (D-135): which blocks use a uniform subsample, how many frames of how many, and which use every analysed frame."""
    eff = resolution.get("effective_interval_ps")
    gap = None if (eff is None or len(sel) < 2 or n_analysed < 2) else round(eff * (n_analysed - 1) / (len(sel) - 1), 4)
    return {"scheme": "uniform subsample: np.linspace(0, N-1, n).astype(int), unique indices (deterministic, not random)",
            "role": "estimator input for PCA/free-energy map, clustering, cross-correlation, SASA, secondary structure, "
                    "ligand hydrogen bonds, water bridges and hydration; display for the matrices drawn from them",
            "max_frames": MAX_FRAMES, "n_frames_analysed": int(n_analysed), "n_used": int(len(sel)),
            "fraction_used": round(float(len(sel)) / n_analysed, 4) if n_analysed else None,
            "mean_interval_between_used_frames_ps": gap,
            "subsampled_blocks": ["dssp", "pca", "clusters", "dccm", "sasa_protein", "hbonds_protein (further ≤ 100 frames)",
                                  "ligands.*.hbonds", "ligands.*.water_bridges", "ligands.*.sasa", "ligands.*.hydration"],
            "all_analysed_frames_blocks": ["ligands.*.fingerprint (contacts and persistence events)", "tica / msm"],
            "note": "N counts the frames handed to extended_metrics; if effective_stride > 1 these are already every k-th "
                    "stored frame (see resolution). A larger cap is not promised to converge any of the blocks."}


def extended_metrics(traj, ligand_groups: dict[str, list[int]] | None = None, *, temperature_k: float = 300.0,
                     ligand_charges: dict[str, dict[int, int]] | None = None, resolution: dict | None = None) -> dict:
    """All extended analyses for one (centred, superposed) production trajectory.  JSON-able.

    `resolution` (D-135) = {"effective_stride": k, "source_frame_interval_ps": …, "n_frames_source": …} as known by the
    caller that loaded `traj`; absent ⇒ the stride is "unverified" (full resolution is not claimed)."""
    import mdtraj as md
    from .persistence import resolution_record
    top = traj.topology
    ctx = resolution or {}
    res_rec = resolution_record(traj.time if traj.time is not None and len(traj.time) else None,
                                source_frame_interval_ps=ctx.get("source_frame_interval_ps"),
                                effective_stride=ctx.get("effective_stride"), n_frames_source=ctx.get("n_frames_source"),
                                origin="frames of the analysed trajectory (after any memory stride)")
    if res_rec["n_frames_used"] == 0:
        res_rec["n_frames_used"] = int(traj.n_frames)
    out: dict = {"schema": EXTENDED_SCHEMA, "errors": {}, "resolution": res_rec}
    lig_all = np.array(sorted({i for v in (ligand_groups or {}).values() for i in v}), dtype=int)
    prot = np.setdiff1d(top.select("protein"), lig_all)
    ca = np.setdiff1d(top.select("protein and name CA"), lig_all)
    sel = frame_indices(traj.n_frames)
    sub = traj[sel]
    out["sampling"] = _sampling_record(int(traj.n_frames), sel, res_rec)
    t_ns = (sub.time / 1000.0).tolist() if sub.time is not None and len(sub.time) else list(range(len(sel)))
    out["time_ns"] = t_ns

    def guard(name, fn):
        try:
            out[name] = fn()
        except Exception as exc:  # noqa: BLE001  (each block is independent)
            out["errors"][name] = f"{type(exc).__name__}: {exc}"

    # ---- protein secondary structure
    def dssp():
        ss = md.compute_dssp(sub.atom_slice(prot), simplified=True)
        frac = {c: (ss == c).mean(1).round(4).tolist() for c in ("H", "E", "C")}
        res = [f"{r.name}{r.resSeq}" for r in sub.atom_slice(prot).topology.residues]
        per_res = {c: (ss == c).mean(0).round(3).tolist() for c in ("H", "E")}
        return {"fraction": frac, "residues": res, "per_residue": per_res,
                "matrix": ["".join(row) for row in ss[:: max(1, len(ss) // 120)]]}
    guard("dssp", dssp)

    # ---- PCA and free-energy landscape on Cα
    def pca_block():
        p = pca(sub.xyz[:, ca, :] * 10.0)
        if p:
            pr = np.asarray(p["projection"])
            p["landscape"] = free_energy_landscape(pr[:, 0], pr[:, 1], temperature_k=temperature_k)
            p["sampling"] = {"n_used": int(len(sel)), "n_frames_analysed": int(traj.n_frames), "scheme": "uniform subsample"}
            allx = traj.xyz[:, ca, :] * 10.0 if len(ca) * 3 * traj.n_frames <= ALL_FRAMES_PCA_MAX_ELEMENTS else None
            p["sensitivity"] = pca_sensitivity(sub.xyz[:, ca, :] * 10.0, allx)
        return p
    guard("pca", pca_block)

    # ---- clustering (Cα + ligand heavy atoms)
    def clusters():
        idx = np.concatenate([ca, lig_all]).astype(int)
        D = np.array([md.rmsd(sub, sub, i, atom_indices=idx) for i in range(sub.n_frames)]) * 10.0
        D = (D + D.T) / 2
        c = cluster_from_rmsd(D, cutoff_A=2.0)
        c["sampling"] = {"n_used": int(len(sel)), "n_frames_analysed": int(traj.n_frames), "scheme": "uniform subsample"}
        c["sensitivity"] = cluster_sensitivity(D, 2.0)
        return c
    guard("clusters", clusters)

    # ---- dynamic cross-correlation (Cα)
    def dccm():
        C = cross_correlation(sub.xyz[:, ca, :])
        res = [_res_label(top, i) for i in ca]
        return {"matrix": C.round(3).tolist(), "residues": res}
    guard("dccm", dccm)

    # ---- protein SASA
    def sasa_protein():
        s = md.shrake_rupley(sub.atom_slice(prot), mode="residue").sum(1) * 100.0   # nm² → Å²
        return {"total_A2": s.round(1).tolist()}
    guard("sasa_protein", sasa_protein)

    # ---- intramolecular protein hydrogen bonds (count per frame) and, D-105, the side-chain network
    def hb_protein():
        step = max(1, sub.n_frames // 100)                      # ≤ 100 frames: the whole protein is the slow part
        cplx = sub[::step].atom_slice(prot)
        if not any(a.element is not None and a.element.symbol == "H" for a in cplx.topology.atoms):
            # D-121: no hydrogens in the topology (heavy-atom-only input) — an H-bond needs the H; say so, do not guess
            why = "拓撲沒有氫原子，無法判斷氫鍵（需要含氫的拓撲）。"
            return {"status": "unavailable", "why": why, "count": [], "time_ns": [],
                    "network": {"status": "insufficient", "n_frames": 0, "why": why}}
        per = md.wernet_nilsson(cplx)
        ctop = cplx.topology
        backbone = {"N", "O", "OXT", "H"}
        pairs = []
        for x in per:                                            # side chain involved: backbone helix/sheet bonds
            fr = []                                              # would make every residue a "hub"
            for d, h, a in x:
                ad, aa = ctop.atom(int(d)), ctop.atom(int(a))
                if ad.name in backbone and aa.name in backbone:
                    continue
                fr.append((f"{ad.residue.name}{ad.residue.resSeq}", f"{aa.residue.name}{aa.residue.resSeq}"))
            pairs.append(fr)
        from .toolbox import hbond_network
        return {"count": [int(len(x)) for x in per], "time_ns": t_ns[::step], "network": hbond_network(pairs)}
    guard("hbonds_protein", hb_protein)

    # ---- D-105: slow motions (tICA on Cα, all frames in time order) and a small Markov state model on them
    def kinetics():
        from .toolbox import tica, kmeans, msm
        n = traj.n_frames
        tt = np.asarray(traj.time, float) if traj.time is not None and len(traj.time) == n else np.arange(n, dtype=float)
        dt_ns = float(np.median(np.diff(tt))) / 1000.0 if n > 1 else 0.0
        if n < 100 or dt_ns <= 0:
            return {"status": "insufficient", "reason": "frames", "n_frames": int(n)}
        X = traj.xyz[:, ca, :].reshape(n, -1) * 10.0
        lags = sorted({int(max(1, round(v / dt_ns))) for v in (0.05, 0.1, 0.2, 0.5, 1.0, 2.0)} & set(range(1, n // 10)))
        if not lags:
            return {"status": "insufficient", "reason": "frames", "n_frames": int(n)}
        lag = lags[len(lags) // 2]
        ti = tica(X, lag)
        if ti.get("status") != "ok":
            return ti
        proj = np.asarray(ti["projection"])
        ti["dt_ns"], ti["lag_ns"] = dt_ns, round(lag * dt_ns, 4)
        ti["resolution"] = res_rec                               # D-135: dt is the EFFECTIVE interval of the analysed frames
        ti["timescales_ns"] = [None if v is None else round(v * dt_ns, 4) for v in ti["timescales_frames"]]
        ti["landscape"] = free_energy_landscape(proj[:, 0], proj[:, 1], temperature_k=temperature_k)
        k = int(np.clip(n // 50, 5, 30))
        lab, _ = kmeans(proj, k)
        ti["msm"] = msm(lab, lags=lags, n_states=k, dt_ns=dt_ns)
        step = max(1, n // 2000)                                 # keep the JSON small
        ti["projection"] = proj[::step].round(3).tolist()
        return ti
    guard("tica", kinetics)

    out["ligands"] = {}
    polar = np.setdiff1d(top.select("protein and (element N or element O)"), lig_all)
    water_o = top.select("water and element O")
    for rn, idx in (ligand_groups or {}).items():
        lh = np.array(idx, int)
        L: dict = {"errors": {}}

        def lguard(name, fn):
            try:
                L[name] = fn()
            except Exception as exc:  # noqa: BLE001
                L["errors"][name] = f"{type(exc).__name__}: {exc}"
        lpolar = np.array([i for i in lh if top.atom(int(i)).element.symbol in ("N", "O")], int)

        # hydrogen bonds between ligand and protein (geometric: heavy-atom distance; donor–H–acceptor from Wernet–Nilsson)
        def hbonds():
            keep = np.concatenate([prot, lh]).astype(int)
            s2 = sub.atom_slice(keep)
            m = {int(o): int(n) for n, o in enumerate(keep)}
            inv = {v: k for k, v in m.items()}
            lset = {m[int(i)] for i in lh}
            per = md.wernet_nilsson(s2)
            frames = []
            for x in per:
                fr = []
                for d, h, a in x:
                    if (d in lset) != (a in lset):
                        fr.append(f"{_label(top, inv[int(d)])} → {_label(top, inv[int(a)])}")
                frames.append(fr)
            return {"count": [len(f) for f in frames], "occupancy": occupancy(frames, len(frames))}
        lguard("hbonds", hbonds)

        # interaction fingerprint per residue (D-97, A5/A6): chemically defined, multi-label, complete per-frame
        # neighbour search over the STORED frames (not the display subset `sub`), with chain-aware residue identity
        def fingerprint():
            from . import interactions as IX
            prot_heavy = np.array([i for i in prot if top.atom(int(i)).element is not None
                                   and top.atom(int(i)).element.symbol != "H"], int)
            dyn = IX.dynamic_pairs(traj.xyz, lh, prot_heavy, cutoff_nm=IX.SEARCH_NM)   # centred trajectory: complex whole
            atoms = IX.atoms_from_topology(top, list(lh) + list(prot_heavy[np.isin(prot_heavy, dyn["pairs"][:, 1])]))
            charges = (ligand_charges or {}).get(rn)
            fp = IX.fingerprint(dyn, atoms, ligand_charges=charges,
                                time_ps=(traj.time.tolist() if traj.time is not None and len(traj.time) else None))
            fp["time_ns"] = [x / 1000.0 for x in fp["time_ps"]] if fp.get("time_ps") else list(range(traj.n_frames))
            fp["display_labels"] = IX.display_labels(fp["residues"])
            fp["matrix"] = IX.legacy_matrix(fp)
            fp["initial_vs_new"] = IX.initial_vs_new(fp)
            fp["resolution"] = res_rec
            rs = res_rec["resolution"]
            fp["status"] = {"full": "computed"}.get(rs["status"], rs["status"])
            if rs["status"] != "full":
                fp["reason"] = ("; ".join(rs["reasons"]) + ("; occupancy fractions are sampled estimates, event durations "
                                                            "and interruptions are not resolved below the effective interval"
                                                            if rs["status"] == "limited" else ""))
            fp["persistence"] = _persistence(fp, resolution=res_rec)
            return fp
        lguard("fingerprint", fingerprint)

        # water bridges: GEOMETRIC CANDIDATES only — a water oxygen within 3.5 Å of a ligand N/O and of a protein N/O in
        # the same frame (no hydrogen-bond geometry).  No solvent coordinates → unavailable, never zero (D-97, A5)
        def water_bridges():
            from .interactions import water_unavailable
            if not len(water_o):
                return water_unavailable("no water coordinates in this trajectory (solvent stripped or implicit solvent)")
            if not len(lpolar):
                return {"status": "not_applicable", "reason": "ligand has no N/O atoms", "count": None, "residues": None}
            counts, per_res = [], []
            for f in range(sub.n_frames):
                X = sub.xyz[f]
                wl = np.linalg.norm(X[water_o][:, None, :] - X[lpolar][None, :, :], axis=-1).min(1) < WATER_BRIDGE_NM
                ws = water_o[wl]
                if not len(ws):
                    counts.append(0); per_res.append([]); continue
                dp = np.linalg.norm(X[ws][:, None, :] - X[polar][None, :, :], axis=-1)
                hit = dp < WATER_BRIDGE_NM
                bridged = hit.any(1)
                counts.append(int(bridged.sum()))
                per_res.append(sorted({_res_label(top, polar[j]) for i in range(len(ws)) for j in np.where(hit[i])[0]}))
            return {"status": "computed", "definition": "geometric candidate (distance only, display frames)",
                    "count": counts, "residues": occupancy(per_res, sub.n_frames)}
        lguard("water_bridges", water_bridges)

        # solvent exposure of the ligand: SASA in the complex vs alone (buried fraction)
        def sasa_lig():
            keep = np.concatenate([prot, lh]).astype(int)
            s2 = sub.atom_slice(keep)
            a = md.shrake_rupley(s2, mode="atom")[:, len(prot):].sum(1) * 100.0
            free = md.shrake_rupley(sub.atom_slice(lh), mode="atom").sum(1) * 100.0
            buried = 1.0 - a / np.clip(free, 1e-6, None)
            return {"complex_A2": a.round(1).tolist(), "free_A2": free.round(1).tolist(), "buried_fraction": buried.round(4).tolist()}
        lguard("sasa", sasa_lig)

        # D-105: where water stays around the ligand (needs waters in the trajectory; solute-only DCDs have none)
        def hydration():
            if not len(water_o):
                return {"status": "no_water"}
            from .toolbox import hydration_sites
            com = sub.xyz[:, lh, :].mean(axis=(0, 1))
            return hydration_sites([fr for fr in sub.xyz[:, water_o, :]], com, radius_nm=1.0)
        lguard("hydration", hydration)

        out["ligands"][rn] = L
    return out
