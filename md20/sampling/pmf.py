"""Umbrella-sampling quality + PMF (WHAM/MBAR) with figures.

Thin, tested wrappers over the salvaged MDH library.  Inputs are plain
per-window samples of a 1-D collective variable (nm); outputs are a
`PMFResult` plus PNG/SVG figures.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np

from . import _mdh_legacy as mdh
from ..analysis.plots import plot_pmf, plot_umbrella_histograms


@dataclass
class PMFResult:
    grid_nm: np.ndarray
    pmf_kj_mol: np.ndarray
    err_kj_mol: np.ndarray | None
    method: str
    converged: bool
    delta_pmf_kj_mol: float
    quality: dict = field(default_factory=dict)
    figures: dict = field(default_factory=dict)
    boot_pmfs: np.ndarray | None = field(default=None, repr=False)   # bootstrap replicates (not serialised)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("boot_pmfs", None)
        for k in ("grid_nm", "pmf_kj_mol", "err_kj_mol"):
            if d[k] is not None:
                d[k] = np.asarray(d[k]).tolist()
        return d


def umbrella_quality(samples_by_center: dict[float, np.ndarray], *, target_overlap: float = 0.2,
                     min_effective_samples: float = 100.0) -> tuple[dict, dict, dict]:
    """Per-window equilibration/decorrelation + pairwise overlap + connectivity.

    Returns (report dict, equilibrated samples, uncorrelated samples).  The report
    lists `insert_centers_nm` (gaps to fill) and `extend_centers_nm` (windows
    needing more sampling) — the GUI turns these into one-click actions.
    """
    report, eq, unc = mdh.assess_umbrella_samples(samples_by_center, target_overlap=target_overlap,
                                                   min_effective_samples=min_effective_samples)
    return mdh.quality_report_to_dict(report), eq, unc


def pmf_from_windows(samples_by_center: dict[float, np.ndarray], *, force_constant_kj_mol_nm2: float | dict,
                     temperature_k: float = 300.0, out_dir: Path | str | None = None, n_bootstrap: int = 100,
                     bins: int = 200, prefer_mbar: bool = True, seed: int = 2026) -> PMFResult:
    """`force_constant_kj_mol_nm2`: one k for all windows, or {center: k} when refinement used stiffer springs."""
    centers = sorted(samples_by_center)
    quality, eq, unc = umbrella_quality(samples_by_center)
    eq_lists = [np.asarray(eq[c], dtype=float) for c in centers]
    k = ([float(force_constant_kj_mol_nm2[c]) for c in centers] if isinstance(force_constant_kj_mol_nm2, dict)
         else force_constant_kj_mol_nm2)
    base = mdh.bootstrap_pmf_1d(eq_lists, centers, k, temperature_k, bins=bins,
                                n_bootstrap=n_bootstrap, seed=seed, prefer_mbar=prefer_mbar)
    grid = np.asarray(base["grid_nm"], dtype=float)
    pmf = np.asarray(base["pmf_kj_mol"], dtype=float)
    lo, hi = np.asarray(base.get("ci95_low_kj_mol"), dtype=float), np.asarray(base.get("ci95_high_kj_mol"), dtype=float)
    err = (hi - lo) / (2 * 1.96) if base.get("bootstrap_success", 0) > 1 else None
    finite = np.isfinite(pmf)
    delta = float(np.nanmax(pmf[finite]) - np.nanmin(pmf[finite])) if finite.any() else float("nan")
    res = PMFResult(grid_nm=grid, pmf_kj_mol=pmf, err_kj_mol=err, method=str(base.get("method", "")),
                    converged=bool(base.get("converged", True)), delta_pmf_kj_mol=delta, quality=quality,
                    boot_pmfs=base.get("bootstrap_pmfs"))
    if out_dir is not None:
        out = Path(out_dir)
        res.figures["histograms"] = plot_umbrella_histograms(samples_by_center, out / "umbrella_histograms")
        res.figures["pmf"] = plot_pmf(grid[finite], pmf[finite], err[finite] if err is not None else None, out / "pmf")
    return res
