"""D-105 analysis toolbox (roadmap stage 1): what extended.py (D-58) did not have yet.

  tica            slow collective motions (time-lagged independent components) on the leading PCA components
  kmeans          seeded k-means used to discretise tICA space
  msm             a small Markov state model from that discretisation: implied timescales versus lag time and the
                  stationary distribution, with an honest eligibility label — a single short run rarely supports
                  kinetic conclusions, and the label says so instead of printing rates
  hbond_network   persistent hydrogen bonds as a residue graph: edges with occupancy, hubs, connected components
  hydration_sites water density peaks around a ligand (sites where water stays), occupancy and density ratio to bulk

Pure numpy (container-testable).  mdtraj only appears in extended.py, which feeds these functions.
"""
from __future__ import annotations

import numpy as np

BULK_WATER_PER_NM3 = 33.4          # TIP3P-like water at 300 K


# ------------------------------------------------------------------------------------------------ tICA
def tica(X, lag: int, *, n_components: int = 2, n_pca: int = 10) -> dict:
    """X: frames × features (time-ordered, constant spacing).  Reduce to `n_pca` PCA components first (standard: the
    covariance of thousands of coordinates is singular for a few hundred frames), then solve C(τ) v = λ C(0) v with
    the symmetrised lagged covariance.  Timescales t_i = −τ / ln λ_i in frames (λ ≤ 0 → not resolvable: None)."""
    X = np.asarray(X, float)
    n = len(X)
    if lag < 1 or n < 10 * lag or n < 30:
        return {"status": "insufficient", "reason": "frames", "n_frames": n, "lag_frames": int(lag)}
    X = X - X.mean(0)
    U, S, Vt = np.linalg.svd(X, full_matrices=False)
    k = int(min(n_pca, len(S), max(2, n // 20)))
    Y = U[:, :k] * S[:k]
    Y = Y / Y.std(0).clip(1e-12)
    A, B = Y[:-lag], Y[lag:]
    C0 = (A.T @ A + B.T @ B) / (2 * len(A))
    Ct = (A.T @ B + B.T @ A) / (2 * len(A))
    w, V = np.linalg.eigh(C0)
    keep = w > 1e-10 * w.max()
    W = V[:, keep] / np.sqrt(w[keep])                         # whitening
    lam, R = np.linalg.eigh(W.T @ Ct @ W)
    order = np.argsort(lam)[::-1]
    lam, R = lam[order], R[:, order]
    m = int(min(n_components, len(lam)))
    proj = Y @ (W @ R[:, :m])
    ts = [float(-lag / np.log(v)) if 0 < v < 1 else None for v in lam[:m]]
    return {"status": "ok", "projection": proj.round(4).tolist(), "eigenvalues": lam[:m].round(4).tolist(),
            "timescales_frames": ts, "lag_frames": int(lag), "n_pca": k, "n_frames": n}


# ------------------------------------------------------------------------------------------------ k-means
def kmeans(X, k: int, *, seed: int = 2026, iters: int = 100) -> tuple[np.ndarray, np.ndarray]:
    """Seeded k-means++ (deterministic for a given seed).  Returns (labels, centres)."""
    X = np.asarray(X, float)
    rng = np.random.default_rng(seed)
    k = int(max(1, min(k, len(X))))
    C = [X[rng.integers(len(X))]]
    for _ in range(1, k):
        d = np.min(((X[:, None, :] - np.array(C)[None]) ** 2).sum(-1), axis=1)
        p = d / d.sum() if d.sum() > 0 else np.full(len(X), 1 / len(X))
        C.append(X[rng.choice(len(X), p=p)])
    C = np.array(C)
    lab = np.zeros(len(X), int)
    for it in range(iters):
        lab_new = np.argmin(((X[:, None, :] - C[None]) ** 2).sum(-1), axis=1)
        if it > 0 and np.array_equal(lab_new, lab):
            break
        lab = lab_new
        for j in range(k):
            if np.any(lab == j):
                C[j] = X[lab == j].mean(0)
    return lab, C


# ------------------------------------------------------------------------------------------------ MSM
def _largest_connected(C: np.ndarray) -> np.ndarray:
    """States strongly connected through observed transitions (both directions)."""
    n = len(C)
    adj = (C + C.T) > 0
    best: list[int] = []
    seen = np.zeros(n, bool)
    for s in range(n):
        if seen[s]:
            continue
        comp, stack = [], [s]
        seen[s] = True
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in np.where(adj[u])[0]:
                if not seen[v]:
                    seen[v] = True
                    stack.append(int(v))
        if len(comp) > len(best):
            best = comp
    return np.array(sorted(best), int)


def msm(dtraj, *, lags: list[int], n_states: int, dt_ns: float, n_its: int = 3) -> dict:
    """Implied timescales versus lag from a single discrete trajectory.  Reversibility by symmetrised counts
    ((C + Cᵀ)/2, a simple and documented estimator; not maximum likelihood).

    Eligibility (what may be said):
      insufficient — too few transitions (< 10 per state at the shortest lag) or the connected set holds < 90% of
                     frames: no timescale is reported as a result
      unresolved   — the slowest timescale is longer than a third of the trajectory: the process was seen too few
                     times; the curve is shown for teaching only
      exploratory  — timescales present; `its_flat` says whether the slowest one levels off over the last lags
                     (relative change < 20%), the usual sign the lag is long enough.  Never a rate claim from one run."""
    d = np.asarray(dtraj, int)
    n = len(d)
    T_total_ns = n * dt_ns
    out = {"n_frames": n, "n_states": int(n_states), "dt_ns": dt_ns, "lags_frames": [], "lags_ns": [], "its_ns": [],
           "estimator": "symmetrised counts"}
    first_counts = None
    for lag in sorted(set(int(x) for x in lags if 1 <= int(x) < n // 2)):
        C = np.zeros((n_states, n_states))
        np.add.at(C, (d[:-lag], d[lag:]), 1.0)
        if first_counts is None:
            first_counts = C
        cs = _largest_connected(C)
        Cs = (C[np.ix_(cs, cs)] + C[np.ix_(cs, cs)].T) / 2
        rows = Cs.sum(1)
        if len(cs) < 2 or np.any(rows == 0):
            continue
        T = Cs / rows[:, None]
        ev = np.sort(np.real(np.linalg.eigvals(T)))[::-1]
        its = [float(-lag * dt_ns / np.log(v)) if 0 < v < 1 else None for v in ev[1:1 + n_its]]
        out["lags_frames"].append(lag)
        out["lags_ns"].append(round(lag * dt_ns, 4))
        out["its_ns"].append(its)
        if "stationary" not in out:
            pi = rows / rows.sum()
            full = np.zeros(n_states)
            full[cs] = pi
            out["stationary"] = full.round(4).tolist()
            out["connected_fraction"] = round(float(np.isin(d, cs).mean()), 3)
    if first_counts is None or not out["its_ns"]:
        out["eligibility"] = "insufficient"
        out["reason"] = "no lag gave a connected model"
        return out
    trans = int(first_counts.sum() - np.trace(first_counts))
    out["transitions"] = trans
    slow = [x[0] for x in out["its_ns"] if x and x[0] is not None]
    if trans < 10 * n_states or out.get("connected_fraction", 0) < 0.9:
        out["eligibility"], out["reason"] = "insufficient", "transitions" if trans < 10 * n_states else "connectivity"
    elif not slow or max(slow) > T_total_ns / 3:
        out["eligibility"], out["reason"] = "unresolved", "slowest process longer than a third of the run"
    else:
        out["eligibility"] = "exploratory"
    if len(slow) >= 2 and slow[-2]:
        out["its_flat"] = bool(abs(slow[-1] - slow[-2]) / slow[-2] < 0.2)
    else:
        out["its_flat"] = False
    out["trajectory_ns"] = round(T_total_ns, 3)
    return out


# ------------------------------------------------------------------------------------------------ H-bond network
def hbond_network(per_frame: list[list[tuple[str, str]]], *, min_occupancy: float = 0.3, top: int = 25) -> dict:
    """per_frame: for each frame, the (donor residue, acceptor residue) pairs with a hydrogen bond.  An edge joins two
    residues (undirected) when bonded in ≥ min_occupancy of frames; occupancy counts a frame once per pair.
    Hubs = residues with the most persistent partners; components = groups held together by persistent bonds."""
    n = len(per_frame)
    if n == 0:
        return {"status": "insufficient", "n_frames": 0}
    occ: dict[tuple[str, str], int] = {}
    for fr in per_frame:
        for a, b in {tuple(sorted(p)) for p in fr if p[0] != p[1]}:
            occ[(a, b)] = occ.get((a, b), 0) + 1
    edges = sorted(([a, b, round(c / n, 3)] for (a, b), c in occ.items() if c / n >= min_occupancy), key=lambda e: -e[2])
    deg: dict[str, int] = {}
    for a, b, _ in edges:
        deg[a] = deg.get(a, 0) + 1
        deg[b] = deg.get(b, 0) + 1
    parent = {r: r for r in deg}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b, _ in edges:
        parent[find(a)] = find(b)
    comps: dict[str, list[str]] = {}
    for r in deg:
        comps.setdefault(find(r), []).append(r)
    comp_list = sorted((sorted(c) for c in comps.values()), key=len, reverse=True)
    return {"status": "ok", "n_frames": n, "min_occupancy": min_occupancy, "n_edges": len(edges), "edges": edges[:top],
            "hubs": sorted(([r, k] for r, k in deg.items()), key=lambda x: (-x[1], x[0]))[:10],
            "components": [c for c in comp_list if len(c) >= 3][:8], "n_pairs_seen": len(occ)}


# ------------------------------------------------------------------------------------------------ hydration
def hydration_sites(o_frames_nm, center_nm, *, radius_nm: float = 1.0, spacing_nm: float = 0.1, min_ratio: float = 2.0,
                    max_sites: int = 10, site_radius_nm: float = 0.14, bulk: float = BULK_WATER_PER_NM3) -> dict:
    """Water oxygen density on a grid inside a sphere around `center_nm` (pocket / ligand COM in the superposed
    frame), peaks ≥ `min_ratio` × bulk, merged within 0.2 nm.  Occupancy = fraction of frames with an O within
    `site_radius_nm` of the site.  o_frames_nm: list (frames) of (n_water, 3) arrays."""
    frames = [np.asarray(f, float).reshape(-1, 3) for f in o_frames_nm]
    n = len(frames)
    if n < 10:
        return {"status": "insufficient", "n_frames": n}
    c = np.asarray(center_nm, float)
    m = int(np.ceil(radius_nm / spacing_nm))
    ax = np.arange(-m, m + 1) * spacing_nm
    G = np.zeros((len(ax),) * 3)
    for f in frames:
        rel = f - c
        rel = rel[np.einsum("ij,ij->i", rel, rel) <= radius_nm ** 2]
        if len(rel) == 0:
            continue
        ijk = np.clip(np.round(rel / spacing_nm).astype(int) + m, 0, len(ax) - 1)
        np.add.at(G, (ijk[:, 0], ijk[:, 1], ijk[:, 2]), 1.0)
    vox = spacing_nm ** 3
    dens = G / (n * vox) / bulk                                  # ratio to bulk
    gx, gy, gz = np.meshgrid(ax, ax, ax, indexing="ij")
    inside = gx ** 2 + gy ** 2 + gz ** 2 <= radius_nm ** 2
    cand = []
    for i, j, k in zip(*np.where((dens >= min_ratio) & inside)):
        sl = dens[max(0, i - 1):i + 2, max(0, j - 1):j + 2, max(0, k - 1):k + 2]
        if dens[i, j, k] >= sl.max():
            cand.append((float(dens[i, j, k]), np.array([ax[i], ax[j], ax[k]])))
    cand.sort(key=lambda x: -x[0])
    sites: list[tuple[float, np.ndarray]] = []
    for r, p in cand:
        if all(np.linalg.norm(p - q) > 0.2 for _, q in sites):
            sites.append((r, p))
        if len(sites) >= max_sites:
            break
    out = []
    for r, p in sites:
        pos = c + p
        hit = sum(1 for f in frames if len(f) and np.min(np.linalg.norm(f - pos, axis=1)) <= site_radius_nm)
        out.append({"xyz_nm": pos.round(3).tolist(), "density_ratio": round(r, 2), "occupancy": round(hit / n, 3),
                    "distance_to_center_nm": round(float(np.linalg.norm(p)), 3)})
    return {"status": "ok", "n_frames": n, "radius_nm": radius_nm, "min_ratio": min_ratio, "sites": out}
