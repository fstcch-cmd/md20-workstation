"""Umbrella-sampling quality + PMF (WHAM/MBAR) with figures.

Thin, tested wrappers over the salvaged MDH library.  Inputs are plain
per-window samples of a 1-D collective variable (nm); outputs are a
`PMFResult` plus PNG/SVG figures.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path

import math

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



def pmf_span_needed(eq_lists, *, trim: float = 0.0) -> tuple[float, float]:
    """CV range the windows actually sampled: from the lowest to the highest window mean (not the extreme tails,
    whose bins are legitimately empty)."""
    means = [float(np.mean(x)) for x in eq_lists if len(x)]
    return (min(means) + trim, max(means) - trim) if means else (float("nan"), float("nan"))


def pmf_coverage(result: dict, lo: float, hi: float) -> dict:
    """Does the finite part of a PMF span [lo, hi] (within one bin)?"""
    g = np.asarray(result.get("grid_nm"), dtype=float)
    w = np.asarray(result.get("pmf_kj_mol"), dtype=float)
    fin = np.isfinite(w)
    if g.size < 2 or not fin.any() or not np.isfinite(lo):
        return {"ok": False, "finite_nm": None}
    dx = float(g[1] - g[0])
    f_lo, f_hi = float(g[fin].min()), float(g[fin].max())
    return {"ok": bool(f_lo <= lo + dx and f_hi >= hi - dx), "finite_nm": [round(f_lo, 4), round(f_hi, 4)]}

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
    # D-62: the PMF must span what the windows sampled.  An MBAR solve with poor f_k gives windows weights that
    # underflow to zero, so the PMF is NaN past them and the curve silently stops (laptop 3PTB: sampled to 1.72 nm,
    # PMF ended at 0.50 nm, "ΔPMF" was the edge value).  Then WHAM on the same samples is used if it covers the range.
    need_lo, need_hi = pmf_span_needed(eq_lists)
    # D-113: keep the MBAR estimator's own overlap matrix (computed by mbar_pmf_1d, previously dropped here).  It is a
    # property of the samples + f_k, so it is kept even when WHAM later replaces a truncated MBAR curve (noted).
    ovm = base.get("overlap_matrix")
    if ovm is not None and str(base.get("method", "")).startswith("PyMBAR"):
        M = np.asarray(ovm, dtype=float)
        adj = [float(M[i, i + 1]) for i in range(M.shape[0] - 1)] if M.ndim == 2 and M.shape[0] > 1 else []
        quality["mbar_overlap"] = {"matrix": np.round(M, 4).tolist(), "centers_nm": [float(c) for c in centers],
                                   "min_adjacent": (round(min(adj), 4) if adj else None),
                                   "scalar": (float(base["mbar_overlap_scalar"]) if base.get("mbar_overlap_scalar") is not None
                                              else None)}
    cov = pmf_coverage(base, need_lo, need_hi)
    if not cov["ok"] and str(base.get("method", "")).startswith("PyMBAR"):
        wb = mdh.bootstrap_pmf_1d(eq_lists, centers, k, temperature_k, bins=bins,
                                  n_bootstrap=n_bootstrap, seed=seed, prefer_mbar=False)
        wcov = pmf_coverage(wb, need_lo, need_hi)
        quality["pmf_truncated"] = {"method": str(base.get("method")), "finite_nm": cov["finite_nm"],
                                    "sampled_nm": [round(need_lo, 4), round(need_hi, 4)],
                                    "replaced_by": "WHAM" if wcov["ok"] else None, "wham_finite_nm": wcov["finite_nm"]}
        if wcov["ok"]:
            base = wb
            if "mbar_overlap" in quality:
                quality["mbar_overlap"]["note"] = "PMF from WHAM (MBAR curve truncated); matrix is from the MBAR solve"
    grid = np.asarray(base["grid_nm"], dtype=float)
    pmf = np.asarray(base["pmf_kj_mol"], dtype=float)
    lo, hi = np.asarray(base.get("ci95_low_kj_mol"), dtype=float), np.asarray(base.get("ci95_high_kj_mol"), dtype=float)
    err = (hi - lo) / (2 * 1.96) if base.get("bootstrap_success", 0) > 1 else None
    finite = np.isfinite(pmf)
    delta = float(np.nanmax(pmf[finite]) - np.nanmin(pmf[finite])) if finite.any() else float("nan")
    converged = bool(base.get("converged", True))
    if not pmf_coverage(base, need_lo, need_hi)["ok"]:
        converged = False                      # neither estimator covers the sampled range: never report an edge value
    # D-43: an MBAR solve that did not reach tolerance is cross-checked with WHAM on the same samples; it is accepted
    # only when the two ΔPMF agree within 2 kJ/mol (the reason is kept for the report either way)
    if not converged and str(base.get("method", "")).startswith("PyMBAR"):
        try:
            w = mdh.stable_wham_1d(eq_lists, centers, k, temperature_k, bins=bins)
            wp = np.asarray(w["pmf_kj_mol"], dtype=float); wf = np.isfinite(wp)
            w_delta = float(np.nanmax(wp[wf]) - np.nanmin(wp[wf])) if wf.any() else float("nan")
            diff = abs(w_delta - (float(np.nanmax(pmf[finite]) - np.nanmin(pmf[finite])) if finite.any() else float("nan")))
            quality["solver_cross_check"] = {"mbar_note": base.get("solver_note", ""), "wham_converged": bool(w.get("converged")),
                                             "wham_delta_kj_mol": w_delta, "abs_diff_kj_mol": diff}
            converged = bool(w.get("converged")) and np.isfinite(diff) and diff <= 2.0
        except Exception as exc:  # noqa: BLE001
            quality["solver_cross_check"] = {"mbar_note": base.get("solver_note", ""), "error": f"{type(exc).__name__}: {exc}"}
    quality["sampled_nm"] = [round(need_lo, 4), round(need_hi, 4)]   # lowest/highest window mean (D-65 plateau check)
    quality["solver"] = {k: base.get(k) for k in ("timing_s", "bootstrap_warm_start", "bootstrap_solver_protocol",
                                                  "solver_fallback", "bootstrap_success", "bootstrap_requested")}
    res = PMFResult(grid_nm=grid, pmf_kj_mol=pmf, err_kj_mol=err, method=str(base.get("method", "")),
                    converged=converged, delta_pmf_kj_mol=delta, quality=quality,
                    boot_pmfs=base.get("bootstrap_pmfs"))
    if out_dir is not None:
        out = Path(out_dir)
        res.figures["histograms"] = plot_umbrella_histograms(samples_by_center, out / "umbrella_histograms")
        res.figures["pmf"] = plot_pmf(grid[finite], pmf[finite], err[finite] if err is not None else None, out / "pmf")
    return res

# moved from the removed sampling/runner.py (D-109, REVIEW #17); the workflow uses sampling/binding.py
KB = 0.00831446261815324  # kJ mol⁻¹ K⁻¹ (same value as the removed runner)


def binding_summary(grid: np.ndarray, pmf: np.ndarray, err: np.ndarray | None, r_start: float, r_end: float, temperature_k: float) -> dict:
    """Well depth from the PMF plus honest caveats (1-D PMF ≠ standard binding free energy without corrections)."""
    m = np.isfinite(pmf)
    g, p = grid[m], pmf[m]
    i_min = int(np.argmin(p))
    bulk = p[g >= g.max() - 0.15]  # last 0.15 nm as "bulk"
    bulk_mean = float(bulk.mean()) if len(bulk) else float(p[-1])
    delta = bulk_mean - float(p[i_min])
    kT = KB * temperature_k
    e_min = float(err[m][i_min]) if err is not None else None
    e_bulk = float(np.mean(err[m][g >= g.max() - 0.15])) if err is not None and len(bulk) else None
    err_delta = math.sqrt((e_min or 0) ** 2 + (e_bulk or 0) ** 2) if err is not None else None
    interp = (f"PMF 井深 {delta:.1f} kJ/mol（≈ {delta / 4.184:.1f} kcal/mol，{delta / kT:.1f} kT）。"
              "這是沿一維 COM 距離的平均力位能，反映配體離開口袋的能量代價；要換算成標準結合自由能還需要體積／取向的標準態校正與充分收斂，"
              "教學 tier 的短視窗只適合比較不同配體的相對強弱。")
    return {"r_min_nm": float(g[i_min]), "pmf_min_kj_mol": float(p[i_min]), "bulk_pmf_kj_mol": bulk_mean,
            "delta_pmf_kj_mol": delta, "delta_pmf_kcal_mol": delta / 4.184, "delta_pmf_kT": delta / kT,
            "err_kj_mol": err_delta, "r_start_nm": r_start, "r_end_nm": r_end, "interpretation": interp}

