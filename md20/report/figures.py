"""Report figures drawn from the data (D-54): one consistent style, so every figure has a matching explanation.

Axis labels are English with SI units (the scientific convention in either report language); captions and text are
bilingual in the HTML.  Each function returns the PNG path or None when the data is missing.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

PALETTE = ["#2f6f9f", "#c0612b", "#2f7d5b", "#7a4fa3", "#a8862b", "#4d6170", "#b8433f", "#3f8f8f"]


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False, "axes.titlesize": 10,
                         "axes.titleweight": "bold", "axes.titlelocation": "left", "legend.frameon": False,
                         "figure.dpi": 150, "savefig.bbox": "tight"})
    return plt


def _save(fig, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    import matplotlib.pyplot as plt
    plt.close(fig)
    return str(path)


def docking_scores(poses: list[dict], chosen: int | None, title: str, path: Path) -> str | None:
    if not poses:
        return None
    plt = _plt()
    ps = sorted(poses, key=lambda p: p["rank"])
    clusters = sorted({p.get("cluster", 0) for p in ps})
    cmap = {c: PALETTE[i % len(PALETTE)] for i, c in enumerate(clusters)}
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    x = np.arange(len(ps))
    ax.bar(x, [p["score"] for p in ps], color=[cmap[p.get("cluster", 0)] for p in ps], width=0.7)
    best = min(p["score"] for p in ps)
    ax.axhspan(best, best + 1.0, color="#7b8794", alpha=0.12, lw=0)
    for i, p in enumerate(ps):
        if p["rank"] == chosen:
            ax.text(i, p["score"], "★", ha="center", va="top", fontsize=12, color="#1f2933")
    ax.set_xticks(x, [str(p["rank"]) for p in ps])
    ax.set_xlabel("Pose rank")
    ax.set_ylabel("Vina score (kcal mol$^{-1}$)")
    ax.invert_yaxis()
    ax.set_title(title)
    handles = [plt.Rectangle((0, 0), 1, 1, color=cmap[c]) for c in clusters]
    ax.legend(handles, [f"cluster {c}" for c in clusters], ncol=min(6, len(clusters)), fontsize=7, loc="upper left",
              bbox_to_anchor=(0, -0.28))
    return _save(fig, path)


def screen_ranking(rows: list[dict], path: Path, top_n: int = 25) -> str | None:
    rs = [r for r in rows if r.get("score") is not None][:top_n]
    if not rs:
        return None
    plt = _plt()
    rs = rs[::-1]
    fig, ax = plt.subplots(figsize=(6.4, 0.25 * len(rs) + 0.9))
    col = {"PASS": "#2f7d5b", "AUTO_FIXED": "#c08a1e", "NEEDS_HUMAN": "#b8433f"}
    ax.barh(range(len(rs)), [r["score"] for r in rs], color=[col.get(r.get("recommendation_status"), "#7b8794") for r in rs], height=0.7)
    best = min(r["score"] for r in rs)
    ax.axvspan(best, best + 1.0, color="#7b8794", alpha=0.12, lw=0)
    ax.set_yticks(range(len(rs)), [r["name"] for r in rs], fontsize=7)
    ax.set_xlabel("Vina score (kcal mol$^{-1}$)")
    ax.invert_xaxis()
    return _save(fig, path)


def timeseries(series: dict, ylabel: str, path: Path, *, threshold: float | None = None) -> str | None:
    """series: {label: (t_ns, y)}"""
    series = {k: v for k, v in series.items() if v and len(v[1]) > 1}
    if not series:
        return None
    plt = _plt()
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    for (k, (t, y)), c in zip(series.items(), PALETTE * 3):
        t, y = np.asarray(t, float)[:len(y)], np.asarray(y, float)
        ax.plot(t, y, color=c, lw=1.0, label=k, alpha=0.85)
        n = len(y)
        if n >= 8:
            ax.hlines(y[n // 2:].mean(), t[n // 2], t[-1], colors=c, linestyles=":", lw=1.2)
    if threshold is not None:
        ax.axhline(threshold, color="#b8433f", ls="--", lw=0.8)
    ax.set_xlabel("Time (ns)")
    ax.set_ylabel(ylabel)
    ax.legend(fontsize=7, ncol=min(4, len(series)))
    return _save(fig, path)


def rmsf(series: dict, path: Path) -> str | None:
    """series: {label: (residue_names, rmsf_A)}; the first label is the reference for the difference panel."""
    series = {k: v for k, v in series.items() if v and len(v[1]) > 1}
    if not series:
        return None
    plt = _plt()
    two = len(series) >= 2
    fig, axes = plt.subplots(2 if two else 1, 1, figsize=(6.4, 3.8 if two else 2.4), sharex=True,
                             gridspec_kw={"height_ratios": [2, 1]} if two else None)
    axes = np.atleast_1d(axes)
    keys = list(series)
    for k, c in zip(keys, PALETTE * 3):
        axes[0].plot(np.arange(len(series[k][1])), series[k][1], color=c, lw=0.9, label=k)
    axes[0].set_ylabel("RMSF (Å)")
    axes[0].legend(fontsize=7, ncol=min(4, len(series)))
    if two:
        ref = np.asarray(series[keys[0]][1], float)
        for k, c in zip(keys[1:], PALETTE[1:] * 3):
            o = np.asarray(series[k][1], float)
            n = min(len(o), len(ref))
            axes[1].bar(np.arange(n), o[:n] - ref[:n], color=c, width=1.0, alpha=0.7)
        axes[1].axhline(0, color="#1f2933", lw=0.6)
        axes[1].set_ylabel("ΔRMSF (Å)")
    axes[-1].set_xlabel("Residue index")
    return _save(fig, path)


def contacts(freq: dict, path: Path, top_n: int = 15) -> str | None:
    items = sorted(freq.items(), key=lambda kv: -kv[1])[:top_n]
    if not items:
        return None
    plt = _plt()
    items = items[::-1]
    fig, ax = plt.subplots(figsize=(6.4, 0.22 * len(items) + 0.9))
    vals = [v for _, v in items]
    ax.barh(range(len(items)), vals, color=["#2f7d5b" if v >= 0.75 else ("#2f6f9f" if v >= 0.25 else "#9aa5b1") for v in vals], height=0.7)
    ax.axvline(0.75, color="#2f7d5b", ls="--", lw=0.8)
    ax.axvline(0.25, color="#9aa5b1", ls="--", lw=0.8)
    ax.set_yticks(range(len(items)), [k for k, _ in items], fontsize=7)
    ax.set_xlim(0, 1)
    ax.set_xlabel("Fraction of time within 4 Å")
    return _save(fig, path)


def smd(pos, force, work, path: Path) -> str | None:
    if pos is None or len(pos) < 5:
        return None
    plt = _plt()
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    ax.plot(pos, force, color=PALETTE[0], lw=0.8)
    ax.set_xlabel("Spring position (nm)")
    ax.set_ylabel("Force (kJ mol$^{-1}$ nm$^{-1}$)", color=PALETTE[0])
    ax2 = ax.twinx()
    ax2.plot(pos, work, color=PALETTE[1], lw=1.2)
    ax2.set_ylabel("Work (kJ mol$^{-1}$)", color=PALETTE[1])
    ax2.spines["right"].set_visible(True)
    return _save(fig, path)


def pmf(grid, W, err, path: Path) -> str | None:
    if grid is None or len(grid) < 3:
        return None
    plt = _plt()
    g, W = np.asarray(grid, float), np.asarray(W, float)
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    ax.plot(g, W, color=PALETTE[0], lw=1.4)
    if err is not None and len(err) == len(g):
        e = np.asarray(err, float)
        ax.fill_between(g, W - e, W + e, color=PALETTE[0], alpha=0.2, lw=0)
    i = int(np.nanargmin(W))
    ax.plot([g[i]], [W[i]], "o", color=PALETTE[1], ms=4)
    ax.set_xlabel("Ligand–pocket distance (nm)")
    ax.set_ylabel("PMF (kJ mol$^{-1}$)")
    return _save(fig, path)


# ============================================================================================ D-58: extended figures
def bars(items: list, xlabel: str, path: Path, *, top_n: int = 15, thresholds=(0.5, 0.2)) -> str | None:
    """Horizontal bars of [label, fraction] (occupancies)."""
    items = list(items)[:top_n]
    if not items:
        return None
    plt = _plt()
    items = items[::-1]
    fig, ax = plt.subplots(figsize=(6.4, 0.24 * len(items) + 0.9))
    vals = [float(v) for _, v in items]
    ax.barh(range(len(items)), vals, color=["#2f7d5b" if v >= thresholds[0] else ("#2f6f9f" if v >= thresholds[1] else "#9aa5b1")
                                             for v in vals], height=0.7)
    for t in thresholds:
        ax.axvline(t, color="#9aa5b1", ls="--", lw=0.8)
    ax.set_yticks(range(len(items)), [str(k) for k, _ in items], fontsize=7)
    ax.set_xlim(0, 1)
    ax.set_xlabel(xlabel)
    return _save(fig, path)


def two_panel(t, y1, y2, l1: str, l2: str, path: Path) -> str | None:
    if t is None or len(y1) < 2:
        return None
    plt = _plt()
    fig, axes = plt.subplots(2, 1, figsize=(6.4, 3.6), sharex=True)
    t = np.asarray(t, float)
    axes[0].plot(t[:len(y1)], y1, color=PALETTE[0], lw=0.9)
    axes[0].set_ylabel(l1)
    if y2 is not None and len(y2):
        axes[1].plot(t[:len(y2)], y2, color=PALETTE[1], lw=0.9)
    axes[1].set_ylabel(l2)
    axes[1].set_xlabel("Time (ns)")
    return _save(fig, path)


def dssp_area(t, frac: dict, path: Path) -> str | None:
    if not frac or not frac.get("C"):
        return None
    plt = _plt()
    t = np.asarray(t, float)[:len(frac["C"])]
    fig, ax = plt.subplots(figsize=(6.4, 2.4))
    ax.stackplot(t, frac["H"], frac["E"], frac["C"], labels=["α-helix", "β-strand", "other"],
                 colors=["#c0612b", "#2f6f9f", "#d9dee3"])
    ax.set_ylim(0, 1)
    ax.set_xlabel("Time (ns)")
    ax.set_ylabel("Fraction of residues")
    ax.legend(fontsize=7, ncol=3, loc="lower right")
    return _save(fig, path)


def landscape(land: dict, explained, path: Path) -> str | None:
    if not land or not land.get("G"):
        return None
    plt = _plt()
    G = np.array([[np.nan if v is None else v for v in row] for row in land["G"]], float)
    xe, ye = np.asarray(land["xedges"]), np.asarray(land["yedges"])
    fig, ax = plt.subplots(figsize=(5.2, 4.2))
    im = ax.pcolormesh(xe, ye, G.T, cmap="viridis", shading="auto")
    fig.colorbar(im, ax=ax, label="ΔG (kJ mol$^{-1}$)")
    for b in land.get("basins") or []:
        ax.plot(b[0], b[1], "w+", ms=8)
    ex = list(explained or [0, 0]) + [0, 0]
    ax.set_xlabel(f"PC1 ({ex[0]:.0%})")
    ax.set_ylabel(f"PC2 ({ex[1]:.0%})")
    return _save(fig, path)


def clusters_plot(c: dict, t, path: Path) -> str | None:
    pops = c.get("populations") or []
    if not pops:
        return None
    plt = _plt()
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.4), gridspec_kw={"width_ratios": [1, 2]})
    k = min(len(pops), 8)
    axes[0].bar(range(1, k + 1), pops[:k], color=PALETTE[:k])
    axes[0].set_xlabel("Cluster")
    axes[0].set_ylabel("Population")
    axes[0].set_ylim(0, 1)
    axes[0].set_xticks(range(1, k + 1))
    lab = np.asarray(c.get("labels") or [], int)
    t = np.asarray(t, float)[:len(lab)]
    axes[1].scatter(t, lab + 1, c=[PALETTE[i % len(PALETTE)] for i in lab], s=6)
    axes[1].set_xlabel("Time (ns)")
    axes[1].set_ylabel("Cluster")
    axes[1].set_yticks(range(1, int(lab.max()) + 2) if len(lab) else [1])
    return _save(fig, path)


def heatmap(M, path: Path, *, cmap: str = "RdBu_r", vmin=-1, vmax=1, label: str = "", ticks=None, xlabel="", ylabel="") -> str | None:
    M = np.asarray(M, float)
    if M.size == 0:
        return None
    plt = _plt()
    fig, ax = plt.subplots(figsize=(5.2, 4.4))
    im = ax.imshow(M, cmap=cmap, vmin=vmin, vmax=vmax, origin="lower", aspect="auto")
    fig.colorbar(im, ax=ax, label=label)
    if ticks:
        idx = np.arange(len(ticks)) if len(ticks) <= 12 else np.linspace(0, len(ticks) - 1, 8).astype(int)   # D-59: label every row up to 12
        ax.set_xticks(idx, [ticks[i] for i in idx], fontsize=6, rotation=90)
        ax.set_yticks(idx, [ticks[i] for i in idx], fontsize=6)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    return _save(fig, path)


def fingerprint_plot(fp: dict, t, path: Path, top_n: int = 25) -> str | None:
    res, mat = fp.get("residues") or [], fp.get("matrix") or []
    if not res:
        return None
    from matplotlib.colors import ListedColormap
    plt = _plt()
    M = np.asarray(mat, float)
    order = np.argsort(-(M > 0).mean(1))[:top_n]
    M = M[order]
    fig, ax = plt.subplots(figsize=(7.2, 0.22 * len(order) + 1.0))
    t = np.asarray(t, float)
    ax.imshow(M, aspect="auto", interpolation="nearest", cmap=ListedColormap(["#ffffff", "#c9a227", "#2f6f9f", "#b8433f"]),
              vmin=0, vmax=3, extent=[t[0] if len(t) else 0, t[-1] if len(t) else M.shape[1], len(order) - 0.5, -0.5])
    ax.set_yticks(range(len(order)), [res[i] for i in order], fontsize=7)
    ax.set_xlabel("Time (ns)")
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in ("#c9a227", "#2f6f9f", "#b8433f")]
    ax.legend(handles, ["hydrophobic", "polar", "ionic"], fontsize=7, ncol=3, loc="upper left", bbox_to_anchor=(0, -0.12))
    return _save(fig, path)


def pmf_convergence(conv: dict, path: Path) -> str | None:
    curves = [(k, v) for k, v in sorted(conv.items()) if isinstance(v, dict) and v.get("grid_nm")]
    if len(curves) < 2:
        return None
    plt = _plt()
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    for (k, v), c in zip(curves, ["#c9d3dc", "#9aa5b1", "#4d6170", PALETTE[0]]):
        ax.plot(v["grid_nm"], v["pmf_kj_mol"], color=c, lw=1.3 if k == "1.00" else 1.0, label=f"{float(k):.0%} of samples")
    ax.set_xlabel("Ligand–pocket distance (nm)")
    ax.set_ylabel("PMF (kJ mol$^{-1}$)")
    ax.legend(fontsize=7)
    return _save(fig, path)


def properties_plot(props: list[dict], path: Path) -> str | None:
    if not props:
        return None
    from .chem import LIMITS
    plt = _plt()
    keys = ["mw", "logp", "tpsa", "hbd", "hba", "rotb"]
    labels = {"mw": "Molecular weight (Da)", "logp": "logP", "tpsa": "Polar surface area (Å²)", "hbd": "H-bond donors",
              "hba": "H-bond acceptors", "rotb": "Rotatable bonds"}
    fig, axes = plt.subplots(2, 3, figsize=(7.2, 4.0))
    for ax, k in zip(axes.ravel(), keys):
        v = [p[k] for p in props if p.get(k) is not None]
        ax.hist(v, bins=12, color=PALETTE[0], alpha=0.85)
        ax.axvline(LIMITS[k], color="#b8433f", ls="--", lw=0.9)
        ax.set_xlabel(labels[k], fontsize=8)
    fig.tight_layout()
    return _save(fig, path)


def chem_space_plot(xy, scores, names, path: Path) -> str | None:
    xy = np.asarray(xy, float)
    if len(xy) < 3:
        return None
    plt = _plt()
    fig, ax = plt.subplots(figsize=(5.6, 4.2))
    sc = ax.scatter(xy[:, 0], xy[:, 1], c=scores, cmap="viridis_r", s=22, edgecolor="none")
    fig.colorbar(sc, ax=ax, label="Vina score (kcal mol$^{-1}$)")
    for i in np.argsort(scores)[:5]:
        ax.annotate(names[i], xy[i], fontsize=6, xytext=(3, 3), textcoords="offset points")
    ax.set_xlabel("Fingerprint PC1")
    ax.set_ylabel("Fingerprint PC2")
    return _save(fig, path)


# ============================================================================================ D-59: docking figures
def funnel(poses: list[dict], path: Path) -> str | None:
    pts = [(p["rmsd_ref"], p["score"], p["rank"]) for p in poses if p.get("rmsd_ref") is not None]
    if len(pts) < 2:
        return None
    plt = _plt()
    r, s, k = np.array(pts).T
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    ax.axvspan(0, 2.0, color="#2f7d5b", alpha=0.08, lw=0)
    ax.scatter(r, s, c=PALETTE[0], s=28)
    for x, y, n in pts:
        ax.annotate(int(n), (x, y), fontsize=7, xytext=(3, 2), textcoords="offset points")
    ax.set_xlabel("RMSD to co-crystal pose (Å)")
    ax.set_ylabel("Vina score (kcal mol$^{-1}$)")
    ax.invert_yaxis()
    return _save(fig, path)


def pose_positions(cents: np.ndarray, scores, box: dict, path: Path) -> str | None:
    if len(cents) < 1 or not box.get("center"):
        return None
    plt = _plt()
    c, h = np.asarray(box["center"], float), np.asarray(box.get("size") or [20, 20, 20], float) / 2
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.2))
    for ax, (i, j, li, lj) in zip(axes, ((0, 1, "x (Å)", "y (Å)"), (0, 2, "x (Å)", "z (Å)"))):
        ax.add_patch(plt.Rectangle((c[i] - h[i], c[j] - h[j]), 2 * h[i], 2 * h[j], fill=False, ec="#4d6170", lw=1))
        sc = ax.scatter(cents[:, i], cents[:, j], c=scores, cmap="viridis_r", s=30)
        ax.set_xlim(c[i] - h[i] - 2, c[i] + h[i] + 2)
        ax.set_ylim(c[j] - h[j] - 2, c[j] + h[j] + 2)
        ax.set_aspect("equal")
        ax.set_xlabel(li); ax.set_ylabel(lj)
    fig.colorbar(sc, ax=axes, label="Score (kcal mol$^{-1}$)", shrink=0.8)
    return _save(fig, path)


def binary_map(rows: list[str], M, path: Path, cols: list[str] | None = None, xlabel: str = "Pose rank") -> str | None:
    M = np.asarray(M)
    if M.size == 0:
        return None
    plt = _plt()
    fig, ax = plt.subplots(figsize=(min(7.2, 0.35 * M.shape[1] + 2.4), 0.2 * len(rows) + 1.0))
    ax.imshow(M, cmap="Blues", vmin=0, vmax=1.2, aspect="auto", interpolation="nearest")
    ax.set_yticks(range(len(rows)), rows, fontsize=7)
    ax.set_xticks(range(M.shape[1]), cols or [str(i + 1) for i in range(M.shape[1])], fontsize=7)
    ax.set_xlabel(xlabel)
    return _save(fig, path)


def ligand_compare(rows: list[dict], path: Path) -> str | None:
    if len(rows) < 2:
        return None
    plt = _plt()
    rows = sorted(rows, key=lambda r: r["score"])
    names = [r["name"] for r in rows]
    fig, axes = plt.subplots(1, 3, figsize=(7.2, 0.28 * len(rows) + 1.4), sharey=True)
    for ax, key, lab, col in zip(axes, ("score", "le", "heavy"), ("Score (kcal mol$^{-1}$)", "Ligand efficiency", "Heavy atoms"), PALETTE):
        ax.barh(range(len(rows)), [r.get(key) or 0 for r in rows], color=col, height=0.6)
        ax.set_xlabel(lab, fontsize=8)
    axes[0].set_yticks(range(len(rows)), names, fontsize=7)
    axes[0].invert_yaxis()
    return _save(fig, path)


# ------------------------------------------------------------------------------------------- D-60 multi-ligand
def joint_poses(poses: list[dict], names: list[str], path: Path, *, ll_min: float = 3.3, ll_max: float = 4.5, chosen: int | None = None) -> str | None:
    """Per joint pose: minimum ligand–ligand distance (band = co-occupancy without clash) and each ligand's protein contacts."""
    if not poses or poses[0].get("min_ll_distance") is None:
        return None
    plt = _plt()
    ranks = [p["rank"] for p in poses]
    fig, axes = plt.subplots(2, 1, figsize=(6.4, 4.2), sharex=True)
    d = [p.get("min_ll_distance") or np.nan for p in poses]
    axes[0].axhspan(ll_min, ll_max, color="#2f7d5b", alpha=0.10, lw=0)
    axes[0].axhline(ll_min, color="#b8433f", ls="--", lw=0.8)
    axes[0].bar(ranks, d, color=["#b8433f" if x < ll_min else ("#9aa5b1" if x > ll_max else PALETTE[0]) for x in d], width=0.6)
    axes[0].set_ylabel("Min. ligand–ligand\ndistance (Å)", fontsize=8)
    cp = np.array([p.get("contacts_per_ligand") or [0] * len(names) for p in poses], float)
    w = 0.8 / max(1, cp.shape[1])
    for k in range(cp.shape[1]):
        axes[1].bar(np.array(ranks) + (k - (cp.shape[1] - 1) / 2) * w, cp[:, k], width=w, color=PALETTE[k % len(PALETTE)],
                    label=names[k] if k < len(names) else f"L{k + 1}")
    axes[1].set_ylabel("Protein contacts\n(heavy atoms)", fontsize=8)
    axes[1].set_xlabel("Joint pose rank")
    axes[1].legend(fontsize=7, ncol=min(4, cp.shape[1]), frameon=False)
    if chosen:
        for ax in axes:
            ax.axvline(chosen, color="#4d6170", ls=":", lw=1)
    axes[1].set_xticks(ranks)
    return _save(fig, path)


def positions_by_ligand(cents: dict, box: dict, path: Path) -> str | None:
    """Pose centres of each ligand in the box (colour = ligand, number = joint rank)."""
    if not cents or not box.get("center"):
        return None
    plt = _plt()
    c, h = np.asarray(box["center"], float), np.asarray(box.get("size") or [20, 20, 20], float) / 2
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.3))
    for ax, (i, j, li, lj) in zip(axes, ((0, 1, "x (Å)", "y (Å)"), (0, 2, "x (Å)", "z (Å)"))):
        ax.add_patch(plt.Rectangle((c[i] - h[i], c[j] - h[j]), 2 * h[i], 2 * h[j], fill=False, ec="#4d6170", lw=1))
        for (name, X), col in zip(cents.items(), PALETTE * 3):
            X = np.asarray(X)
            ax.scatter(X[:, i], X[:, j], color=col, s=26, label=name)
            for r, x in enumerate(X[:5], 1):
                ax.annotate(r, (x[i], x[j]), fontsize=6, xytext=(2, 2), textcoords="offset points")
        ax.set_xlim(c[i] - h[i] - 2, c[i] + h[i] + 2); ax.set_ylim(c[j] - h[j] - 2, c[j] + h[j] + 2)
        ax.set_aspect("equal"); ax.set_xlabel(li); ax.set_ylabel(lj)
    axes[1].legend(fontsize=7, frameon=False, loc="upper right")
    return _save(fig, path)
