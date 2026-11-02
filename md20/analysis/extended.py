"""Extended trajectory analysis (D-58): everything the production trajectory supports beyond RMSD/RMSF/contacts.

Two layers:
  * pure numpy (tested everywhere): PCA, free-energy landscape, clustering from an RMSD matrix, cross-correlation,
    hydrogen-bond and fingerprint aggregation, block averages;
  * `extended_metrics(traj, ligand_groups)` (mdtraj, run in the analysis step): extracts the per-frame data and
    calls the pure functions.  Every block is independent and wrapped, so one failure never loses the others.

Result (JSON-able) is written to analysis/extended.json; the report draws and explains every part (report_language.md).
"""
from __future__ import annotations

import numpy as np

MAX_FRAMES = 250            # frames used for the expensive parts (SASA, clustering, water bridges)
HB_DIST_NM = 0.35           # donor–acceptor heavy-atom distance for a hydrogen bond
HYDROPHOBIC_NM = 0.40
IONIC_NM = 0.40
WATER_BRIDGE_NM = 0.35

HYDROPHOBIC_RES = {"ALA", "VAL", "LEU", "ILE", "MET", "PHE", "TRP", "PRO", "TYR", "CYS"}
POS_ATOMS = {("LYS", "NZ"), ("ARG", "NH1"), ("ARG", "NH2"), ("ARG", "NE"), ("HIP", "ND1"), ("HIP", "NE2")}
NEG_ATOMS = {("ASP", "OD1"), ("ASP", "OD2"), ("GLU", "OE1"), ("GLU", "OE2")}


# =========================================================================================== pure numpy
def frame_indices(n: int, max_frames: int = MAX_FRAMES) -> np.ndarray:
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


def _smooth2d(H: np.ndarray, sigma: float = 1.0) -> np.ndarray:
    r = int(3 * sigma)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    pad = np.pad(H, r, mode="constant")
    a = np.apply_along_axis(lambda v: np.convolve(v, k, mode="valid"), 0, pad)
    return np.apply_along_axis(lambda v: np.convolve(v, k, mode="valid"), 1, a)


def free_energy_landscape(p1, p2, *, temperature_k: float = 300.0, bins: int | None = None, min_population: float = 0.05) -> dict:
    """−kT ln P(PC1, PC2) in kJ/mol from a lightly smoothed histogram, minimum set to 0; empty bins are NaN.
    Basins are connected regions below 1 kT that hold at least `min_population` of the frames (sampling noise in a
    sparse histogram is not counted as a state).  Bins scale with the number of frames (√n / 1.5, 10 to 30)."""
    p1, p2 = np.asarray(p1, float), np.asarray(p2, float)
    n = len(p1)
    if n < 10:
        return {}
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


def extended_metrics(traj, ligand_groups: dict[str, list[int]] | None = None, *, temperature_k: float = 300.0) -> dict:
    """All extended analyses for one (centred, superposed) production trajectory.  JSON-able."""
    import mdtraj as md
    top = traj.topology
    out: dict = {"errors": {}}
    lig_all = np.array(sorted({i for v in (ligand_groups or {}).values() for i in v}), dtype=int)
    prot = np.setdiff1d(top.select("protein"), lig_all)
    ca = np.setdiff1d(top.select("protein and name CA"), lig_all)
    sel = frame_indices(traj.n_frames)
    sub = traj[sel]
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
        return p
    guard("pca", pca_block)

    # ---- clustering (Cα + ligand heavy atoms)
    def clusters():
        idx = np.concatenate([ca, lig_all]).astype(int)
        D = np.array([md.rmsd(sub, sub, i, atom_indices=idx) for i in range(sub.n_frames)]) * 10.0
        D = (D + D.T) / 2
        return cluster_from_rmsd(D, cutoff_A=2.0)
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

    # ---- intramolecular protein hydrogen bonds (count per frame)
    def hb_protein():
        step = max(1, sub.n_frames // 100)                      # ≤ 100 frames: the whole protein is the slow part
        cplx = sub[::step].atom_slice(prot)
        per = md.wernet_nilsson(cplx)
        return {"count": [int(len(x)) for x in per], "time_ns": t_ns[::step]}
    guard("hbonds_protein", hb_protein)

    out["ligands"] = {}
    polar = np.setdiff1d(top.select("protein and (element N or element O)"), lig_all)
    prot_c = np.array([i for i in np.setdiff1d(top.select("protein and element C and sidechain"), lig_all)
                       if top.atom(int(i)).residue.name in HYDROPHOBIC_RES], int)
    pos = np.array([i for i in prot if (top.atom(int(i)).residue.name, top.atom(int(i)).name) in POS_ATOMS], int)
    neg = np.array([i for i in prot if (top.atom(int(i)).residue.name, top.atom(int(i)).name) in NEG_ATOMS], int)
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
        lcarb = np.array([i for i in lh if top.atom(int(i)).element.symbol == "C"], int)

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

        # interaction fingerprint per residue: hydrogen bond, hydrophobic, ionic
        def fingerprint():
            res_frames = {"hydrophobic": [], "ionic": [], "polar": []}
            for kind, la, pa, cut in (("hydrophobic", lcarb, prot_c, HYDROPHOBIC_NM), ("polar", lpolar, polar, HB_DIST_NM),
                                      ("ionic", lpolar, np.concatenate([pos, neg]).astype(int), IONIC_NM)):
                if not len(la) or not len(pa):
                    res_frames[kind] = [[] for _ in range(sub.n_frames)]
                    continue
                pairs = np.array([[i, j] for i in la for j in pa])
                d0 = md.compute_distances(sub[0], pairs)[0]
                pairs = pairs[d0 < 1.2] if (d0 < 1.2).any() else pairs[:0]
                if not len(pairs):
                    res_frames[kind] = [[] for _ in range(sub.n_frames)]
                    continue
                d = md.compute_distances(sub, pairs)
                res_frames[kind] = [sorted({_res_label(top, j) for (i, j), on in zip(pairs, d[f] < cut) if on})
                                    for f in range(sub.n_frames)]
            residues = sorted({r for v in res_frames.values() for fr in v for r in fr})
            occ = {k: dict(occupancy(v, sub.n_frames, top=200)) for k, v in res_frames.items()}
            # residue × time matrix: 0 none, 1 hydrophobic, 2 polar, 3 ionic (strongest class shown)
            mat = []
            for r in residues:
                row = []
                for f in range(sub.n_frames):
                    v = 3 if r in res_frames["ionic"][f] else (2 if r in res_frames["polar"][f] else (1 if r in res_frames["hydrophobic"][f] else 0))
                    row.append(v)
                mat.append(row)
            return {"residues": residues, "matrix": mat, "occupancy": occ}
        lguard("fingerprint", fingerprint)

        # water bridges: a water oxygen within 3.5 Å of a ligand N/O and of a protein N/O in the same frame
        def water_bridges():
            if not len(water_o) or not len(lpolar):
                return {"count": [0] * sub.n_frames, "residues": []}
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
            return {"count": counts, "residues": occupancy(per_res, sub.n_frames)}
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

        out["ligands"][rn] = L
    return out
