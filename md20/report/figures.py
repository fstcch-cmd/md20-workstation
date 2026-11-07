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
    from ..analysis.plots import legend_outside
    legend_outside(fig)                      # D-89: legends to the right of the plots, never over the data
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


# D-89 line-chart rules (docs/specs/figures.md): x must increase; every line has a name in the key; one colour per
# series, the same series keeps its colour in every figure of a report; more series than colours add line styles;
# helper lines (second-half mean) are explained in the key; the key sits outside the plot on the right.
_COLOURS: dict[str, int] = {}
LINESTYLES = ["-", "--", "-.", ":"]


def reset_colours() -> None:
    """Called at the start of each report so colour numbering starts again."""
    _COLOURS.clear()


def series_style(label: str) -> dict:
    """Colour and line style of one named series; stable within a report (first come, first numbered)."""
    i = _COLOURS.setdefault(str(label), len(_COLOURS))
    return {"color": PALETTE[i % len(PALETTE)], "ls": LINESTYLES[(i // len(PALETTE)) % len(LINESTYLES)]}


def time_axis(t, n: int) -> tuple[np.ndarray, str]:
    """(x values, x label).  Times that do not increase (chunk files each starting at 0, from runs analysed before
    D-89) are never drawn as time: the frame number is used and the label says so."""
    t = np.asarray(t if t is not None else [], float)[:n]
    if len(t) == n and n > 1 and np.all(np.diff(t) > 0):
        return t, "Time (ns)"
    return np.arange(1, n + 1, dtype=float), "Saved frame (time axis not recorded)"


def running_mean(y: np.ndarray, frac: float = 0.05) -> tuple[np.ndarray, int]:
    """Centred running mean over ~5 % of the frames (at least 3, odd); edges use the frames available."""
    n = len(y)
    w = max(3, int(round(n * frac)) | 1)
    if n < w:
        return y.astype(float), 1
    k = np.ones(w)
    num = np.convolve(y, k, mode="same")
    den = np.convolve(np.ones(n), k, mode="same")
    return num / den, w


OVERLAY_MAX = 3            # more series than this are drawn one panel each (small multiples), same axes


def timeseries(series: dict, ylabel: str, path: Path, *, threshold: float | None = None) -> str | None:
    """series: {label: (t_ns, y)}.  D-89 rules: every line named; thin = every saved frame, thick = running mean in
    the same colour (both named in the key); up to three series share one plot, more get one panel each with the
    series name on the panel, so lines of different ligands never pile up; the key is outside on the right."""
    series = {k: v for k, v in series.items() if v and len(v[1]) > 1}
    if not series:
        return None
    plt = _plt()
    names = list(series)
    many = len(names) > OVERLAY_MAX
    if many:
        fig, axes = plt.subplots(len(names), 1, figsize=(6.4, 1.05 * len(names) + 0.8), sharex=True, sharey=True)
        axes = list(np.atleast_1d(axes))
    else:
        fig, ax = plt.subplots(figsize=(6.4, 2.8))
        axes = [ax] * len(names)
    xlabel, win_ns = "Time (ns)", None
    for ax, k in zip(axes, names):
        t, y = series[k]
        y = np.asarray(y, float)
        x, xl = time_axis(t, len(y))
        if xl != "Time (ns)":
            xlabel = xl
        st = series_style(k)
        ax.plot(x, y, color=st["color"], ls=st["ls"], lw=0.6, alpha=0.35)
        m, w = running_mean(y)
        ax.plot(x, m, color=st["color"], ls=st["ls"], lw=1.8, label=k)
        if w > 1 and xl == "Time (ns)" and len(x) > 1:
            win_ns = w * float(np.median(np.diff(x)))
        if threshold is not None:
            ax.axhline(threshold, color="#b8433f", ls="--", lw=0.8)
        if many:
            ax.set_title(k, loc="left", fontsize=7.5, color=st["color"], fontweight="bold", pad=2)
            ax.set_ylabel("")
    if many:
        fig.supylabel(ylabel, fontsize=9)
        axes[-1].set_xlabel(xlabel)
        key_ax = axes[0]
    else:
        axes[0].set_ylabel(ylabel)
        axes[0].set_xlabel(xlabel)
        key_ax = axes[0]
    key_ax.plot([], [], color="#52514e", lw=0.6, alpha=0.5, label="Thin: every saved frame")
    key_ax.plot([], [], color="#52514e", lw=1.8,
                label="Thick: running mean" + (f" ({win_ns:.2g} ns)" if win_ns else ""))
    if threshold is not None:
        key_ax.plot([], [], color="#b8433f", ls="--", lw=0.8, label=f"Threshold {threshold:g}")
    if many:                                   # names are on the panels; the key explains the line kinds only
        for line in list(key_ax.get_lines()):
            if line.get_label() in names:
                line.set_label("_" + line.get_label())
    key_ax.legend(fontsize=7)
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


def smd_contacts_map(sc: dict, path: Path, max_rows: int = 30) -> str | None:
    """D-116 (F13): one row per ligand-residue contact along the pull (x = ligand-pocket distance d), bars where the
    contact exists, a marker at its last position, the force peak +/- window as a grey band.  Rows with a release at the
    peak are always kept; the rest follow in release order."""
    cons = list(sc.get("contacts") or [])
    d = np.asarray((sc.get("frames") or {}).get("d_nm") or [], float)
    if sc.get("status") not in ("ok", "limited") or not cons or len(d) < 2:
        return None
    plt = _plt()
    keep = [c for c in cons if c.get("category") == "at_peak"]
    for c in cons:
        if len(keep) >= max_rows:
            break
        if c not in keep:
            keep.append(c)
    keep = [c for c in cons if c in keep]
    step = float(sc.get("frame_step_nm") or 0.01)
    fig, ax = plt.subplots(figsize=(6.8, 0.2 * len(keep) + 1.5))
    pk, win = sc.get("peak") or {}, float(sc.get("peak_window_nm") or 0.05)
    if pk.get("resolved"):
        ax.axvspan(pk["d_nm"] - win, pk["d_nm"] + win, color="#7b8794", alpha=0.25, lw=0, label=f"Force peak ± {win:g} nm")
        ax.axvline(pk["d_nm"], color="#52514e", lw=0.8, ls="--")
    c_init, c_new, c_peak = PALETTE[0], PALETTE[2], PALETTE[1]
    for row, c in enumerate(keep):
        col = c_init if c.get("initial") else c_new
        for a, b in c.get("runs") or []:
            lo, hi = float(d[a:b + 1].min()) - step / 2, float(d[a:b + 1].max()) + step / 2
            ax.barh(row, hi - lo, left=lo, height=0.7, color=col, lw=0)
        if c.get("released"):
            at = c.get("category") == "at_peak"
            if not at:      # white underlay so the tick stays visible on the coloured bar
                ax.plot([c["release_d_nm"]], [row], marker="|", ms=9, color="white", mew=3.2, ls="none")
            ax.plot([c["release_d_nm"]], [row], marker="D" if at else "|", ms=5 if at else 8, color=c_peak if at else "#1f2933",
                    mec="#1f2933" if at else None, mew=0.6 if at else 1.2, ls="none")
    ax.set_ylim(len(keep) - 0.5, -0.5)
    ax.set_xlim(float(d.min()) - step, float(d.max()) + step)
    ax.set_yticks(range(len(keep)), [("* " if c.get("category") == "at_peak" else "") + c.get("label", c["residue"]) for c in keep], fontsize=7)
    ax.set_xlabel("Ligand–pocket distance d (nm)")
    ax.set_ylabel("Ligand–residue contacts" + (f" ({len(keep)} of {len(cons)} shown)" if len(keep) < len(cons) else ""))
    ax.plot([], [], "s", color=c_init, label="Present at the start")
    ax.plot([], [], "s", color=c_new, label="Formed during the pull")
    ax.plot([], [], "|", color="#1f2933", ms=8, mew=1.2, label="Last position of a contact")
    ax.plot([], [], "D", color=c_peak, mec="#1f2933", mew=0.6, ms=5, label="Last position at the force peak (*)")
    ax.legend(fontsize=7, frameon=False, loc="upper left", bbox_to_anchor=(1.0, 1.0))
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
    x1, xl = time_axis(t, len(y1))
    y1 = np.asarray(y1, float)
    axes[0].plot(x1, y1, color=PALETTE[0], lw=0.6, alpha=0.35)
    axes[0].plot(x1, running_mean(y1)[0], color=PALETTE[0], lw=1.8)
    axes[0].set_ylabel(l1)
    if y2 is not None and len(y2):
        y2 = np.asarray(y2, float)
        x2, _ = time_axis(t, len(y2))
        axes[1].plot(x2, y2, color=PALETTE[1], lw=0.6, alpha=0.35)
        axes[1].plot(x2, running_mean(y2)[0], color=PALETTE[1], lw=1.8)
    axes[1].set_ylabel(l2)
    axes[1].set_xlabel(xl)
    axes[0].plot([], [], color="#52514e", lw=0.6, alpha=0.5, label="Thin: every saved frame")
    axes[0].plot([], [], color="#52514e", lw=1.8, label="Thick: running mean")
    axes[0].legend(fontsize=7)
    return _save(fig, path)


def dssp_area(t, frac: dict, path: Path) -> str | None:
    if not frac or not frac.get("C"):
        return None
    plt = _plt()
    t, xl = time_axis(t, len(frac["C"]))
    fig, ax = plt.subplots(figsize=(6.4, 2.4))
    ax.stackplot(t, frac["H"], frac["E"], frac["C"], labels=["α-helix", "β-strand", "other"],
                 colors=["#c0612b", "#2f6f9f", "#d9dee3"])
    ax.set_ylim(0, 1)
    ax.set_xlabel(xl)
    ax.set_ylabel("Fraction of residues")
    ax.legend(fontsize=7, ncol=3, loc="lower right")
    return _save(fig, path)


def landscape(land: dict, explained, path: Path, *, axes: tuple[str, str] = ("PC1", "PC2")) -> str | None:
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
    if explained:                     # PCA: share of the variance; tICA (D-105): no variance share to show
        ex = list(explained) + [0, 0]
        ax.set_xlabel(f"{axes[0]} ({ex[0]:.0%})")
        ax.set_ylabel(f"{axes[1]} ({ex[1]:.0%})")
    else:
        ax.set_xlabel(axes[0])
        ax.set_ylabel(axes[1])
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
    t, xl = time_axis(t, len(lab))
    axes[1].scatter(t, lab + 1, c=[PALETTE[i % len(PALETTE)] for i in lab], s=6)
    axes[1].set_xlabel(xl)
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


FP_COLOURS = {"salt_bridge": "#b8433f", "like_charge_proximity": "#8e5ea2", "charged_proximity_ligand_charge_unknown": "#e3a587",
              "polar_proximity": "#2f6f9f", "hydrophobic": "#c9a227"}
FP_NAMES = {"salt_bridge": "salt bridge", "like_charge_proximity": "like-charge proximity",
            "charged_proximity_ligand_charge_unknown": "charged proximity (ligand charge unknown)",
            "polar_proximity": "polar proximity (distance only)", "hydrophobic": "hydrophobic"}


def fingerprint_plot(fp: dict, t, path: Path, top_n: int = 25) -> str | None:
    """D-97: a multi-label fingerprint (schema md20.fingerprint/2) is drawn as one lane per interaction label inside
    each residue row, so concurrent interactions stay visible; older single-class records keep the old drawing."""
    res, mat = fp.get("residues") or [], fp.get("matrix") or []
    if not res:
        return None
    from matplotlib.colors import ListedColormap
    plt = _plt()
    t = np.asarray(fp.get("time_ns") if fp.get("time_ns") else (t if t is not None else []), float)
    if fp.get("bitmask") is not None:
        B = np.asarray(fp["bitmask"], np.int64)
        order = np.argsort(-(B > 0).mean(1), kind="stable")[:top_n]
        labs = [k for k in fp.get("labels") or [] if any(((B[order] & fp["bits"][k]) > 0).any(1))]
        if not labs:
            return None
        nl = len(labs)
        fig, ax = plt.subplots(figsize=(7.2, 0.26 * len(order) + 1.3))
        xl_ = "Time (ns)"
        if len(t) != B.shape[1] or len(t) < 2 or not np.all(np.diff(t) > 0):
            t, xl_ = np.arange(1, B.shape[1] + 1, dtype=float), "Saved frame (time axis not recorded)"
        dtw = float(np.median(np.diff(t))) if len(t) > 1 else 1.0
        disp = fp.get("display_labels") or {}
        for row, ri in enumerate(order):
            for li, k in enumerate(labs):
                on = (B[ri] & fp["bits"][k]) > 0
                if not on.any():
                    continue
                y0 = row - 0.42 + li * (0.84 / nl)
                xs = t[on] - dtw / 2
                ax.broken_barh([(x, dtw) for x in xs], (y0, 0.84 / nl), facecolors=FP_COLOURS.get(k, "#777"), linewidth=0)
        ax.set_ylim(len(order) - 0.5, -0.5)
        ax.set_xlim(t[0] - dtw / 2, t[-1] + dtw / 2)
        ax.set_yticks(range(len(order)), [disp.get(res[i], res[i]) for i in order], fontsize=7)
        ax.set_xlabel(xl_)
        handles = [plt.Rectangle((0, 0), 1, 1, color=FP_COLOURS.get(k, "#777")) for k in labs]
        ax.legend(handles, [FP_NAMES.get(k, k) for k in labs], fontsize=7, ncol=2, loc="upper left", bbox_to_anchor=(0, -0.14),
                  frameon=False)
        return _save(fig, path)
    M = np.asarray(mat, float)
    order = np.argsort(-(M > 0).mean(1))[:top_n]
    M = M[order]
    fig, ax = plt.subplots(figsize=(7.2, 0.22 * len(order) + 1.0))
    xl_ = "Time (ns)"
    if len(t) < 2 or not np.all(np.diff(t) > 0):        # D-89: never stretch a broken time axis over the matrix
        t, xl_ = np.arange(1, M.shape[1] + 1, dtype=float), "Saved frame (time axis not recorded)"
    ax.imshow(M, aspect="auto", interpolation="nearest", cmap=ListedColormap(["#ffffff", "#c9a227", "#2f6f9f", "#b8433f"]),
              vmin=0, vmax=3, extent=[t[0] if len(t) else 0, t[-1] if len(t) else M.shape[1], len(order) - 0.5, -0.5])
    ax.set_yticks(range(len(order)), [res[i] for i in order], fontsize=7)
    ax.set_xlabel(xl_)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in ("#c9a227", "#2f6f9f", "#b8433f")]
    ax.legend(handles, ["hydrophobic", "polar (old record: distance only)", "charged proximity (old record: ligand charge not checked)"],
              fontsize=7, ncol=2, loc="upper left", bbox_to_anchor=(0, -0.12))
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



def cooperativity_plot(rows: list[dict], ylabel: str, path: Path) -> str | None:
    """D-61 thermodynamic cycle: each ligand alone vs with its partner bound (ΔG-like: lower = stronger), with errors."""
    if not rows:
        return None
    plt = _plt()
    fig, ax = plt.subplots(figsize=(5.6, 3.0))
    x = np.arange(len(rows))
    for k, (key, lab, col) in enumerate((("alone", "Alone", PALETTE[0]), ("with", "Partner bound", PALETTE[1]))):
        v = [r[key][0] for r in rows]
        e = [r[key][1] or 0 for r in rows]
        ax.bar(x + (k - 0.5) * 0.36, v, width=0.36, yerr=e, capsize=3, color=col, label=lab)
    for i, r in enumerate(rows):
        d = r["with"][0] - r["alone"][0]
        ax.annotate(f"{d:+.1f}", (i, min(r["with"][0], r["alone"][0])), xytext=(0, -12), textcoords="offset points",
                    ha="center", fontsize=8)
    ax.axhline(0, color="#4d6170", lw=0.8)
    ax.set_xticks(x, [r["ligand"] for r in rows])
    ax.set_ylabel(ylabel)
    ax.legend(fontsize=7, frameon=False)
    return _save(fig, path)


# ============================================================================================ D-82: fold, membrane, long run, coarse-grained
PLDDT_BANDS = ((90, 100, "#0b4f8a", "very high"), (70, 90, "#5fa8e0", "confident"), (50, 70, "#f2d24b", "low"), (0, 50, "#ef8a3b", "very low"))


def plddt_profile(by_chain: dict, path: Path, peptide_chain: str | None = None) -> str | None:
    """Per-residue pLDDT of every chain, concatenated, with the usual confidence bands."""
    chains = [(c, [float(x) for x in v]) for c, v in (by_chain or {}).items() if v]
    if not chains:
        return None
    plt = _plt()
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    for lo, hi, col, _ in PLDDT_BANDS:
        ax.axhspan(lo, hi, color=col, alpha=0.13, lw=0)
    x0 = 0
    for k, (c, v) in enumerate(chains):
        x = np.arange(x0 + 1, x0 + len(v) + 1)
        ax.plot(x, v, color=PALETTE[1] if c == peptide_chain else PALETTE[0], lw=1.2 if c == peptide_chain else 0.9,
                marker="o" if len(v) <= 40 else None, ms=2.5, label=f"chain {c}" + (" (peptide)" if c == peptide_chain else ""))
        if k:
            ax.axvline(x0 + 0.5, color="#4d6170", ls="--", lw=0.8)
        x0 += len(v)
    ax.set_ylim(0, 100)
    ax.set_xlim(0.5, x0 + 0.5)
    ax.set_xlabel("Residue (all chains in order)")
    ax.set_ylabel("pLDDT")
    handles = [plt.Rectangle((0, 0), 1, 1, color=c, alpha=0.4) for _, _, c, _ in PLDDT_BANDS]
    leg = ax.legend(fontsize=7, loc="lower right")
    ax.add_artist(leg)
    ax.legend(handles, [f"{lab} ({lo}–{hi})" for lo, hi, _, lab in PLDDT_BANDS], fontsize=6, ncol=4, loc="upper left",
              bbox_to_anchor=(0, -0.25))
    return _save(fig, path)


def residue_deviation(labels: list, dev, path: Path, *, pocket_mask=None, threshold: float = 2.0) -> str | None:
    d = np.asarray(dev, float)
    if not len(d):
        return None
    plt = _plt()
    pm = np.zeros(len(d), bool) if pocket_mask is None else np.asarray(pocket_mask, bool)
    fig, ax = plt.subplots(figsize=(6.4, 2.5))
    ax.bar(np.arange(len(d)), d, width=1.0, color=[PALETTE[1] if p else "#9aa5b1" for p in pm])
    ax.axhline(threshold, color="#b8433f", ls="--", lw=0.8)
    if len(labels) == len(d):
        idx = np.linspace(0, len(d) - 1, min(len(d), 10)).astype(int)
        ax.set_xticks(idx, [str(labels[i]) for i in idx], fontsize=6, rotation=60)
    ax.set_xlabel("Receptor residue (sequence-matched Cα)")
    ax.set_ylabel("Deviation after superposition (Å)")
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in (PALETTE[1], "#9aa5b1")]
    ax.legend(handles, ["within 10 Å of the peptide", "elsewhere"], fontsize=7, loc="upper right")
    return _save(fig, path)


def contact_matrix(rows: list, cols: list, M, path: Path, *, vmax: float = 8.0, cutoff: float = 4.0) -> str | None:
    D = np.asarray(M, float)
    if D.size == 0:
        return None
    plt = _plt()
    fig, ax = plt.subplots(figsize=(min(7.2, 0.18 * D.shape[1] + 2.6), 0.24 * D.shape[0] + 1.4))
    im = ax.imshow(np.clip(D, 0, vmax), cmap="viridis", vmin=0, vmax=vmax, aspect="auto", interpolation="nearest")
    fig.colorbar(im, ax=ax, label="Min. heavy-atom distance (Å)", shrink=0.8)
    for i, j in zip(*np.where(D <= cutoff)):
        ax.add_patch(plt.Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False, ec="white", lw=0.8))
    ax.set_yticks(range(len(rows)), [str(r) for r in rows], fontsize=6)
    step = max(1, len(cols) // 30)
    ax.set_xticks(range(0, len(cols), step), [str(cols[j]) for j in range(0, len(cols), step)], fontsize=6, rotation=90)
    ax.set_xlabel("Receptor residue")
    ax.set_ylabel("Peptide residue")
    return _save(fig, path)


def _band_panel(ax, t, y, ref, lo, hi, ylabel: str, color: str) -> None:
    y = np.asarray(y, float)
    t, _ = time_axis(t, len(y))
    if ref is not None:
        ax.axhspan(lo, hi, color="#7b8794", alpha=0.15, lw=0)
        ax.axhline(ref, color="#4d6170", lw=0.8)
    ax.plot(t, y, color=color, lw=0.9)
    n = len(y)
    if n >= 8:
        ax.hlines(y[n // 2:].mean(), t[n // 2], t[-1], colors=color, linestyles=":", lw=1.4)
    ax.set_ylabel(ylabel)


def membrane_equil(t, apl, dpp, ref: dict | None, path: Path, *, tol_apl: float = 0.06, tol_dpp: float = 0.30) -> str | None:
    if apl is None or len(apl) < 2:
        return None
    plt = _plt()
    ref = ref or {}
    fig, axes = plt.subplots(2, 1, figsize=(6.4, 3.8), sharex=True)
    ra, rd = ref.get("apl_nm2"), ref.get("dpp_nm")
    _band_panel(axes[0], t, apl, ra, (ra or 0) * (1 - tol_apl), (ra or 0) * (1 + tol_apl), "Area per lipid (nm²)", PALETTE[0])
    _band_panel(axes[1], t, dpp, rd, (rd or 0) - tol_dpp, (rd or 0) + tol_dpp, "P–P thickness (nm)", PALETTE[1])
    axes[1].set_xlabel("Time (ns)")
    return _save(fig, path)


def density_profile(dens: dict, path: Path) -> str | None:
    z = np.asarray(dens.get("z_nm") if dens.get("z_nm") is not None else [], float)
    groups = dens.get("groups") or {}
    if len(z) < 3 or not groups:
        return None
    plt = _plt()
    fig, ax = plt.subplots(figsize=(6.4, 2.8))
    for (name, v), c in zip(groups.items(), PALETTE * 3):
        v = np.asarray(v, float)
        ax.plot(z[:len(v)], v / (v.max() if v.max() > 0 else 1), color=c, lw=1.1, label=f"{name} (max {v.max():.1f})")
    ax.axvline(0, color="#4d6170", lw=0.6, ls=":")
    ax.set_xlabel("z from membrane centre (nm)")
    ax.set_ylabel(f"Density / group max ({dens.get('unit', 'per nm³')})")
    ax.legend(fontsize=7, ncol=2)
    return _save(fig, path)


def scd_plot(series: dict, path: Path, band=(0.12, 0.25)) -> str | None:
    """series: {"sn1": (carbons, −S_CD), "sn2": ...}"""
    if not series:
        return None
    plt = _plt()
    fig, ax = plt.subplots(figsize=(5.6, 2.8))
    ax.axhspan(*band, color="#7b8794", alpha=0.15, lw=0)
    for (tail, (n, s)), c in zip(series.items(), PALETTE):
        ax.plot(n, s, "o-", color=c, ms=3, lw=1.0, label=tail)
    ax.set_xlabel("Carbon number")
    ax.set_ylabel("−S$_{CD}$")
    ax.set_ylim(bottom=0)
    ax.legend(fontsize=7)
    return _save(fig, path)


def insertion_plot(t, com, deepest, path: Path) -> str | None:
    if com is None or len(com) < 2:
        return None
    plt = _plt()
    t, xl = time_axis(t, len(com))
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    ax.axhspan(-0.5, 0.3, color="#7b8794", alpha=0.15, lw=0)
    ax.axhline(0, color="#4d6170", lw=0.8)
    ax.plot(t, com, color=PALETTE[0], lw=1.0, label="centroid")
    if deepest is not None and len(deepest):
        ax.plot(t[:len(deepest)], deepest, color=PALETTE[1], lw=0.9, ls="--", label="deepest heavy atom")
    ax.invert_yaxis()
    ax.set_xlabel(xl)
    ax.set_ylabel("Depth below P plane (nm)")
    ax.legend(fontsize=7)
    return _save(fig, path)


def tilt_hist(tilt, path: Path) -> str | None:
    a = np.asarray(tilt, float)
    if len(a) < 4:
        return None
    plt = _plt()
    fig, ax = plt.subplots(figsize=(5.6, 2.6))
    bins = np.linspace(0, 90, 19)
    ax.hist(a[: len(a) // 2], bins=bins, color="#9aa5b1", alpha=0.7, label="first half")
    ax.hist(a[len(a) // 2:], bins=bins, color=PALETTE[0], alpha=0.7, label="second half")
    for x in (30, 60):
        ax.axvline(x, color="#4d6170", ls=":", lw=0.8)
    ax.set_xlim(0, 90)
    ax.set_xlabel("Tilt to membrane normal (°)  (90° = flat on the surface)")
    ax.set_ylabel("Frames")
    ax.legend(fontsize=7)
    return _save(fig, path)


def thickness_map_plot(tmap: dict, path: Path, marker=None) -> str | None:
    G = np.array([[np.nan if v is None else v for v in row] for row in (tmap or {}).get("dpp_nm") or []], float)
    if G.size == 0 or not np.isfinite(G).any():
        return None
    plt = _plt()
    fig, ax = plt.subplots(figsize=(4.8, 4.0))
    im = ax.pcolormesh(tmap["x_nm"], tmap["y_nm"], np.ma.masked_invalid(G), cmap="cividis", shading="flat")
    fig.colorbar(im, ax=ax, label="Local P–P thickness (nm)")
    if marker is not None:
        ax.plot([marker[0]], [marker[1]], "x", color="#b8433f", ms=9, mew=2)
    ax.set_aspect("equal")
    ax.set_xlabel("x (nm)")
    ax.set_ylabel("y (nm)")
    return _save(fig, path)


def longrun_plot(plan: dict, actual: dict, path: Path) -> str | None:
    if not plan:
        return None
    plt = _plt()
    reps = max(1, int(plan.get("replicas") or 1))
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.6), gridspec_kw={"width_ratios": [1, 2]})
    axes[0].bar([0, 1], [plan.get("production_ns") or 0, actual.get("production_ns") or 0], color=["#9aa5b1", PALETTE[0]], width=0.6)
    axes[0].set_xticks([0, 1], ["planned", "completed"])
    axes[0].set_ylabel("Production (ns)")
    lab = ["trajectory", "chunk files", "planned total", "actual folder"]
    val = [(plan.get("trajectory_gb") or 0) / reps, (plan.get("states_gb") or 0) / reps, (plan.get("total_gb") or 0) / reps,
           actual.get("disk_gb") or 0]
    axes[1].bar(range(4), val, color=["#c9d3dc", "#c9d3dc", "#9aa5b1", PALETTE[1]], width=0.6)
    axes[1].set_xticks(range(4), lab, fontsize=7)
    axes[1].set_ylabel("Disk per replica (GB)")
    fig.tight_layout()
    return _save(fig, path)


def rmsf_halves(residues: list, a, b, path: Path) -> str | None:
    a, b = np.asarray(a, float), np.asarray(b, float)
    n = min(len(a), len(b))
    if n < 3:
        return None
    return rmsf({"first half": (residues[:n], a[:n]), "second half": (residues[:n], b[:n])}, path)


def rmsd_halves(y, path: Path) -> str | None:
    y = np.asarray(y, float)
    if len(y) < 10:
        return None
    plt = _plt()
    fig, ax = plt.subplots(figsize=(5.6, 2.6))
    bins = np.linspace(y.min(), y.max(), 31)
    ax.hist(y[: len(y) // 2], bins=bins, density=True, color="#9aa5b1", alpha=0.7, label="first half")
    ax.hist(y[len(y) // 2:], bins=bins, density=True, color=PALETTE[0], alpha=0.7, label="second half")
    ax.set_xlabel("Backbone RMSD (Å)")
    ax.set_ylabel("Probability density")
    ax.legend(fontsize=7)
    return _save(fig, path)


def cluster_timeline_plot(P, ids: list, t_edges, path: Path) -> str | None:
    P = np.asarray(P, float)
    if P.size == 0:
        return None
    plt = _plt()
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    x = np.asarray(t_edges, float)
    xc = 0.5 * (x[1:] + x[:-1]) if len(x) == len(P) + 1 else np.arange(len(P))
    ax.stackplot(xc, P.T, labels=[f"cluster {c + 1}" for c in ids], colors=(PALETTE * 3)[:len(ids)], alpha=0.85)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Time (ns, window centre)")
    ax.set_ylabel("Share of frames")
    ax.legend(fontsize=7, ncol=min(5, len(ids)), loc="upper left", bbox_to_anchor=(0, -0.25))
    return _save(fig, path)


def cg_membrane_plot(summ: dict, path: Path, *, tol_apl: float = 0.06, tol_dpp: float = 0.30) -> str | None:
    apl = summ.get("apl_nm2") or []
    if len(apl) < 2:
        return None
    plt = _plt()
    p2 = summ.get("p2") or {}
    fig = plt.figure(figsize=(7.2, 3.8))
    gs = fig.add_gridspec(2, 2, width_ratios=[3, 2])
    a0, a1 = fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[1, 0])
    ref = summ.get("reference") or {}
    ra, rd = ref.get("apl_nm2"), ref.get("dpp_nm")
    t = summ.get("time_ns") or list(range(len(apl)))
    _band_panel(a0, t, apl, ra, (ra or 0) * (1 - tol_apl), (ra or 0) * (1 + tol_apl), "APL (nm²)", PALETTE[0])
    _band_panel(a1, t, summ.get("dpp_nm") or [], rd, (rd or 0) - tol_dpp, (rd or 0) + tol_dpp, "PO4–PO4 (nm)", PALETTE[1])
    a1.set_xlabel("Simulated time (ns, CG)")
    if p2:
        a2 = fig.add_subplot(gs[:, 1])
        ks = list(p2)
        a2.barh(range(len(ks)), [p2[k] for k in ks], color=PALETTE[2], height=0.6)
        a2.axvspan(0.1, 0.6, color="#7b8794", alpha=0.12, lw=0)
        a2.set_yticks(range(len(ks)), ks, fontsize=7)
        a2.invert_yaxis()
        a2.set_xlabel("Bond order P2")
    fig.suptitle("COARSE-GRAINED (Martini 3), bead level, not atomistic", fontsize=9, color="#b8433f", x=0.02, ha="left")
    fig.tight_layout()
    return _save(fig, path)


def implied_timescales(m: dict, path: Path) -> str | None:
    """D-105: implied timescales versus lag time.  Grey area: timescales shorter than the lag cannot be resolved;
    dashed line: one third of the run (slower processes were seen too few times)."""
    its = m.get("its_ns") or []
    lags = m.get("lags_ns") or []
    if len(lags) < 2:
        return None
    plt = _plt()
    fig, ax = plt.subplots(figsize=(5.2, 3.4))
    n_proc = max(len(x) for x in its)
    for j in range(n_proc):
        y = [x[j] if j < len(x) and x[j] is not None else np.nan for x in its]
        ax.plot(lags, y, "o-", color=PALETTE[j % len(PALETTE)], label=f"process {j + 1}", ms=4)
    lo = min(lags)
    ax.fill_between(lags, [lo * 0.5] * len(lags), lags, color="#BBBBBB", alpha=0.5, lw=0)
    if m.get("trajectory_ns"):
        ax.axhline(m["trajectory_ns"] / 3, color="#555555", ls="--", lw=1)
    ax.set_yscale("log")
    ax.set_xlabel("Lag time (ns)")
    ax.set_ylabel("Implied timescale (ns)")
    ax.legend(frameon=False, fontsize=8, loc="center left", bbox_to_anchor=(1.0, 0.5))
    return _save(fig, path)


def common_landscape(cb: dict, path: Path) -> str | None:
    """D-106: every system's landscape on one PCA basis and the same bins, side by side; basins marked."""
    names = cb.get("systems") or []
    if len(names) < 2:
        return None
    plt = _plt()
    k = len(names)
    fig, axes = plt.subplots(1, k, figsize=(3.0 * k + 0.6, 3.0), sharex=True, sharey=True, squeeze=False)
    xe, ye = np.asarray(cb["xedges"]), np.asarray(cb["yedges"])
    vmax = max((np.nanmax(np.array([[np.nan if v is None else v for v in r] for r in cb["per_system"][n]["landscape"]["G"]], float))
                for n in names if cb["per_system"][n]["landscape"].get("G")), default=1.0)
    im = None
    for ax, n in zip(axes[0], names):
        land = cb["per_system"][n]["landscape"]
        if land.get("G"):
            G = np.array([[np.nan if v is None else v for v in r] for r in land["G"]], float)
            im = ax.pcolormesh(xe, ye, G.T, cmap="viridis", shading="auto", vmin=0, vmax=vmax)
        for i, b in enumerate(land.get("basins") or []):
            ax.plot(b[0], b[1], "w+", ms=8)
            ax.annotate(str(i + 1), (b[0], b[1]), color="white", fontsize=8, xytext=(3, 3), textcoords="offset points")
        ax.set_title(n, fontsize=9, loc="left")
        ax.set_xlabel(f"PC1 ({cb['explained'][0]:.0%})")
    axes[0][0].set_ylabel(f"PC2 ({cb['explained'][1]:.0%})")
    if im is not None:
        fig.colorbar(im, ax=axes[0].tolist(), label="ΔG (kJ mol$^{-1}$)")
    return _save(fig, path)
