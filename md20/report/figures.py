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
