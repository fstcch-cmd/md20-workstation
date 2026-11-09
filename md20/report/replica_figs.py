"""Replica overlay figure (D-130 redo): one line per replica plus the mean ± SD band across replicas.

Follows docs/specs/figures.md: every line named (run id), legend outside via `_save`, one colour per series from
`series_style`, a time axis that is never drawn from a non-increasing time (`time_axis`).  The band needs >= 2 replicas
on a common time grid; with one replica there is no band (the figure says so) — never an invented spread.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

BAND_MIN_REPLICAS = 2


def _grid_stats(series: list[tuple[np.ndarray, np.ndarray]], npts: int = 200):
    """Mean and SD (ddof = 1) across replicas on a common grid over the overlapping time range."""
    lo = max(t[0] for t, _ in series)
    hi = min(t[-1] for t, _ in series)
    if not hi > lo:
        return None
    g = np.linspace(lo, hi, npts)
    Y = np.array([np.interp(g, t, y) for t, y in series], float)
    return g, Y.mean(0), Y.std(0, ddof=1)


def replica_overlay(metrics_by_run: dict[str, dict], path: Path, *, label: str = "") -> str | None:
    """Backbone RMSD and each ligand's pocket RMSD against time, one line per replica (``metrics_by_run`` =
    {run_id: metrics.json}).  Returns the PNG path or None when nothing can be drawn."""
    from . import figures as FG
    panels = [("rmsd_backbone_A", None, "Backbone RMSD (Å)")]
    lig_names = sorted({ln for m in metrics_by_run.values() for ln in (m.get("ligands") or {})})
    panels += [("rmsd_in_pocket_A", ln, f"{ln} pocket RMSD (Å)") for ln in lig_names]
    drawn = []
    for key, ln, yl in panels:
        rows = []
        for rid, m in metrics_by_run.items():
            y = ((m.get("ligands") or {}).get(ln) or {}).get(key) if ln else m.get(key)
            if y is None or len(y) < 2:
                continue
            x, xl = FG.time_axis(m.get("time_ns"), len(y))
            rows.append((rid, x, np.asarray(y, float), xl))
        if rows:
            drawn.append((yl, rows))
    if not drawn:
        return None
    plt = FG._plt()
    fig, axes = plt.subplots(len(drawn), 1, figsize=(7.2, 2.2 * len(drawn) + 0.6), squeeze=False)
    for ax, (yl, rows) in zip(axes[:, 0], drawn):
        series = []
        for rid, x, y, xl in rows:
            st = FG.series_style(f"{label} {rid}".strip())
            ax.plot(x, y, color=st["color"], ls=st["ls"], lw=1.1, alpha=0.9, label=rid)
            series.append((x, y))
        same_axis = len({r[3] for r in rows}) == 1
        if len(series) >= BAND_MIN_REPLICAS and same_axis:
            g = _grid_stats(series)
            if g is not None:
                gx, mu, sd = g
                ax.fill_between(gx, mu - sd, mu + sd, color="#808080", alpha=0.18, lw=0, label="mean ± SD (replicas)")
                ax.plot(gx, mu, color="#303030", lw=2.0, label=f"mean of {len(series)} replicas")
        ax.set_ylabel(yl, fontsize=8)
        ax.legend(fontsize=7)                 # `_save` moves every legend outside the axes (figures.md rule 3)
        ax.set_xlabel(rows[0][3])
    n = max(len(r) for _, r in drawn)
    axes[0, 0].set_title(f"{label} replicas (n = {n})".strip() +
                         ("" if n >= BAND_MIN_REPLICAS else " — single trajectory, no between-replica band"), fontsize=10)
    fig.tight_layout()
    return FG._save(fig, Path(path).with_suffix(".png"))


def delta_rmsf_replicas(rows: list[dict], path, *, label: str = "") -> str | None:
    """Per-residue ΔRMSF (other − ref) with the between-replica Welch 95 % CI as a band (D-164).  ``rows`` are the
    ``residues`` entries of ``delta_rmsf_between_replicas`` (residue, delta_A, ci95_low, ci95_high, ci_excludes_zero).
    Residues whose interval excludes 0 are marked; no multiple-comparison correction is applied (the caption says so)."""
    from . import figures as FG
    if not rows or len(rows) < 3:
        return None
    d = np.array([r["delta_A"] for r in rows], float)
    lo = np.array([r["ci95_low"] for r in rows], float)
    hi = np.array([r["ci95_high"] for r in rows], float)
    sig = np.array([bool(r.get("ci_excludes_zero")) for r in rows])
    x = np.arange(len(rows))
    plt = FG._plt()
    fig, ax = plt.subplots(figsize=(6.8, 2.8))
    st = FG.series_style(f"{label} delta".strip() or "delta")
    ax.fill_between(x, lo, hi, color="#808080", alpha=0.25, lw=0, label="95 % CI (Welch)")
    ax.plot(x, d, color=st["color"], lw=1.0, label="ΔRMSF")
    if sig.any():
        ax.scatter(x[sig], d[sig], s=14, color="#b8433f", zorder=3, label="CI excludes 0")
    ax.axhline(0, color="#1f2933", lw=0.6)
    ax.set_xlabel("Residue index (common residues)")
    ax.set_ylabel("ΔRMSF (Å)")
    ax.legend(fontsize=7)
    fig.tight_layout()
    return FG._save(fig, Path(path).with_suffix(".png"))


def dccm_replicas(mean, sd, path, *, ticks=None) -> str | None:
    """Two panels: element-wise mean DCCM over replicas (diverging colours, -1 to 1) and element-wise sample SD over
    replicas (single colour ramp, 0 up to the largest SD).  ``sd`` is None for one replica; then only the mean is drawn."""
    from . import figures as FG
    M = np.asarray(mean, float)
    if M.ndim != 2 or M.shape[0] < 3 or M.shape[0] != M.shape[1]:
        return None
    S = None if sd is None else np.asarray(sd, float)
    plt = FG._plt()
    fig, axes = plt.subplots(1, 1 if S is None else 2, figsize=(5.2 if S is None else 9.6, 4.2), squeeze=False)
    panels = [(M, "RdBu_r", -1.0, 1.0, "Mean correlation")]
    if S is not None:
        panels.append((S, "viridis", 0.0, max(float(np.nanmax(S)), 0.1), "SD across replicas"))
    for ax, (A, cmap, vmin, vmax, lab) in zip(axes[0], panels):
        im = ax.imshow(A, cmap=cmap, vmin=vmin, vmax=vmax, origin="lower", aspect="auto")
        fig.colorbar(im, ax=ax, label=lab)
        if ticks:
            idx = np.arange(len(ticks)) if len(ticks) <= 12 else np.linspace(0, len(ticks) - 1, 8).astype(int)
            ax.set_xticks(idx, [ticks[i] for i in idx], fontsize=6, rotation=90)
            ax.set_yticks(idx, [ticks[i] for i in idx], fontsize=6)
        ax.set_xlabel("Residue")
        ax.set_ylabel("Residue")
        ax.set_title(lab, fontsize=9)
    fig.tight_layout()
    return FG._save(fig, Path(path).with_suffix(".png"))
