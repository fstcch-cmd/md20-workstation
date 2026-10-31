"""Automatic figures for every stage (PNG 300 dpi + SVG; optional interactive HTML via plotly).

Conventions (one consistent system for the whole workstation):
* one measure per axis (never dual-axis) — related measures become small multiples;
* categorical colours assigned in fixed order (validated palette), identity never by colour alone;
* acceptance windows and targets are drawn as recessive bands/lines with text labels;
* thin 2 px lines, recessive grid, text in neutral ink.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
_INK, _INK2, _GRID = "#0b0b0b", "#52514e", "#e6e5e1"


def _mpl():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": _INK2, "axes.labelcolor": _INK, "xtick.color": _INK2,
                         "ytick.color": _INK2, "axes.grid": True, "grid.color": _GRID, "grid.linewidth": 0.6,
                         "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 100,
                         "savefig.dpi": 300, "lines.linewidth": 1.6})
    return plt


def _save(fig, out_base: Path) -> dict:
    out_base.parent.mkdir(parents=True, exist_ok=True)
    png, svg = out_base.with_suffix(".png"), out_base.with_suffix(".svg")
    fig.savefig(png, bbox_inches="tight")
    fig.savefig(svg, bbox_inches="tight")
    import matplotlib.pyplot as plt
    plt.close(fig)
    return {"png": str(png), "svg": str(svg)}


def plot_stage_log(df: pd.DataFrame, out_base: Path | str, *, title: str, target_temperature_k: float | None = None,
                   ensemble: str = "NVT", accept_window_fraction: float | None = None, html: bool = True) -> dict:
    """Small multiples: temperature, potential energy, (NPT) density & volume vs time."""
    plt = _mpl()
    out_base = Path(out_base)
    panels = [("temperature_k", "Temperature (K)"), ("potential_kj_mol", "Potential energy (kJ/mol)")]
    if ensemble.upper() == "NPT":
        panels += [("density_g_ml", "Density (g/mL)"), ("volume_nm3", "Box volume (nm³)")]
    panels = [p for p in panels if p[0] in df.columns]
    fig, axes = plt.subplots(len(panels), 1, figsize=(7.2, 1.9 * len(panels) + 0.6), sharex=True)
    axes = np.atleast_1d(axes)
    t = df["time_ps"].to_numpy(dtype=float) / 1000.0 if "time_ps" in df else np.arange(len(df))
    for ax, (col, label), color in zip(axes, panels, PALETTE):
        y = df[col].to_numpy(dtype=float)
        ax.plot(t, y, color=color)
        if len(y) > 50:
            k = max(5, len(y) // 50)
            ax.plot(t[k - 1:], np.convolve(y, np.ones(k) / k, mode="valid"), color=_INK, linewidth=1.0, alpha=0.7,
                    label=f"moving mean ({k} pts)")
        if col == "temperature_k" and target_temperature_k:
            ax.axhline(target_temperature_k, color=_INK2, linewidth=0.8, linestyle="--")
            ax.text(t[-1], target_temperature_k, f" target {target_temperature_k:.0f} K", va="center", fontsize=7, color=_INK2)
        if accept_window_fraction:
            x0 = t[-1] * (1 - accept_window_fraction)
            ax.axvspan(x0, t[-1], color=_GRID, alpha=0.5, lw=0)
            if ax is axes[0]:
                ax.text(x0, ax.get_ylim()[1], " acceptance window", va="top", fontsize=7, color=_INK2)
        ax.set_ylabel(label, fontsize=8)
    axes[-1].set_xlabel("Time (ns)")
    axes[0].set_title(title, loc="left", fontsize=10, color=_INK)
    out = _save(fig, out_base)
    if html:
        out["html"] = _plotly_lines(df, t, panels, out_base.with_suffix(".html"), title)
    return out


def plot_minimization(energies: list[float] | np.ndarray, out_base: Path | str, *, title: str = "Energy minimization") -> dict:
    plt = _mpl()
    e = np.asarray(energies, dtype=float)
    fig, ax = plt.subplots(figsize=(6.4, 2.8))
    ax.plot(np.arange(len(e)), e, color=PALETTE[0], marker="o", markersize=3)
    ax.set_xlabel("Minimization stage"); ax.set_ylabel("Potential energy (kJ/mol)")
    ax.set_title(title, loc="left", fontsize=10)
    if len(e) >= 2:
        ax.text(len(e) - 1, e[-1], f" ΔE = {e[-1] - e[0]:,.0f} kJ/mol", va="center", fontsize=8, color=_INK2)
    return _save(fig, Path(out_base))


def plot_overview(stage_frames: dict[str, pd.DataFrame], out_base: Path | str, *, target_temperature_k: float = 300.0) -> dict:
    """Whole-run temperature & density timeline with stage boundaries."""
    plt = _mpl()
    fig, axes = plt.subplots(2, 1, figsize=(7.6, 4.2), sharex=True)
    offset = 0.0
    for i, (name, df) in enumerate(stage_frames.items()):
        if df.empty or "time_ps" not in df:
            continue
        t = df["time_ps"].to_numpy(dtype=float) / 1000.0
        t = t - t[0] + offset
        axes[0].plot(t, df["temperature_k"], color=PALETTE[i % len(PALETTE)], label=name)
        if "density_g_ml" in df:
            axes[1].plot(t, df["density_g_ml"], color=PALETTE[i % len(PALETTE)], label=name)
        axes[0].axvline(t[-1], color=_GRID, linewidth=0.8)
        axes[1].text(t[0], axes[1].get_ylim()[0], f" {name}", fontsize=7, color=_INK2, va="bottom")
        offset = t[-1]
    axes[0].axhline(target_temperature_k, color=_INK2, linewidth=0.8, linestyle="--")
    axes[0].set_ylabel("Temperature (K)"); axes[1].set_ylabel("Density (g/mL)"); axes[1].set_xlabel("Cumulative time (ns)")
    axes[0].set_title("Run overview: equilibration → production", loc="left", fontsize=10)
    axes[0].legend(frameon=False, fontsize=7, ncol=4)
    return _save(fig, Path(out_base))


def plot_umbrella_histograms(samples_by_center: dict[float, np.ndarray], out_base: Path | str, *, unit: str = "nm") -> dict:
    plt = _mpl()
    fig, ax = plt.subplots(figsize=(7.2, 2.8))
    for i, (c, x) in enumerate(sorted(samples_by_center.items())):
        ax.hist(np.asarray(x), bins=40, histtype="step", color=PALETTE[i % len(PALETTE)], linewidth=1.2)
    ax.set_xlabel(f"Collective variable ({unit})"); ax.set_ylabel("Counts")
    ax.set_title("Umbrella windows — overlap check (gaps mean missing windows)", loc="left", fontsize=10)
    return _save(fig, Path(out_base))


def plot_pmf(x: np.ndarray, pmf: np.ndarray, err: np.ndarray | None, out_base: Path | str, *, unit: str = "nm") -> dict:
    plt = _mpl()
    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    ax.plot(x, pmf, color=PALETTE[0])
    if err is not None:
        ax.fill_between(x, pmf - err, pmf + err, color=PALETTE[0], alpha=0.18, lw=0, label="bootstrap ±1σ")
        ax.legend(frameon=False, fontsize=8)
    ax.set_xlabel(f"Collective variable ({unit})"); ax.set_ylabel("PMF (kJ/mol)")
    i = int(np.nanargmin(pmf)); j = int(np.nanargmax(pmf))
    ax.text(x[i], pmf[i], " min", fontsize=7, color=_INK2); ax.text(x[j], pmf[j], " max", fontsize=7, color=_INK2)
    ax.set_title(f"Potential of mean force (ΔPMF = {pmf[j] - pmf[i]:.1f} kJ/mol)", loc="left", fontsize=10)
    return _save(fig, Path(out_base))


def _plotly_lines(df: pd.DataFrame, t: np.ndarray, panels, path: Path, title: str) -> str | None:
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        return None
    fig = make_subplots(rows=len(panels), cols=1, shared_xaxes=True, subplot_titles=[p[1] for p in panels])
    for i, ((col, label), color) in enumerate(zip(panels, PALETTE), 1):
        fig.add_trace(go.Scatter(x=t, y=df[col], mode="lines", name=label, line=dict(color=color, width=1.5),
                                 hovertemplate="%{x:.3f} ns<br>%{y:.3f}"), row=i, col=1)
    fig.update_layout(title=title, height=220 * len(panels) + 80, template="plotly_white", showlegend=False,
                      margin=dict(l=60, r=20, t=60, b=40))
    fig.update_xaxes(title_text="Time (ns)", row=len(panels), col=1)
    fig.write_html(str(path), include_plotlyjs="cdn")
    return str(path)
