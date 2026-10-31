"""Plan umbrella windows along a 1-D CV.

For harmonic biases with the same k, each window samples ≈ Gaussian with
σ = sqrt(kT / k).  The overlap coefficient of two such Gaussians at distance d
is 2·Φ(−d / 2σ); solving for a target overlap gives the spacing.  Windows are
then seeded from the frame of an SMD trajectory whose CV is closest to each
centre (the teaching default; a user may also supply frames manually).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

import numpy as np

KB_KJ_MOL_K = 0.00831446261815324


def _norm_ppf(p: float) -> float:
    try:
        from scipy.stats import norm
        return float(norm.ppf(p))
    except Exception:  # noqa: BLE001 - Acklam approximation
        a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
        b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01]
        c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
        d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
        if p < 0.02425:
            q = math.sqrt(-2 * math.log(p)); return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])/((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
        if p > 1 - 0.02425:
            q = math.sqrt(-2 * math.log(1 - p)); return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])/((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
        q = p - 0.5; r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q/(((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


@dataclass
class WindowPlan:
    centers_nm: list[float]
    force_constant_kj_mol_nm2: float
    sigma_nm: float
    spacing_nm: float
    expected_overlap: float
    seed_frames: list[int] = field(default_factory=list)
    seed_cv_nm: list[float] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def plan_windows(cv_min_nm: float, cv_max_nm: float, *, force_constant_kj_mol_nm2: float = 1000.0,
                 temperature_k: float = 300.0, target_overlap: float = 0.25, smd_cv_nm: np.ndarray | None = None,
                 max_windows: int = 60) -> WindowPlan:
    kT = KB_KJ_MOL_K * temperature_k
    sigma = math.sqrt(kT / force_constant_kj_mol_nm2)
    spacing = 2.0 * sigma * (-_norm_ppf(target_overlap / 2.0))
    n = int(math.floor((cv_max_nm - cv_min_nm) / spacing)) + 1
    notes = []
    if n > max_windows:
        notes.append(f"需要 {n} 個 window 超過上限 {max_windows}；建議降低 k 或縮短 CV 範圍。")
        n = max_windows
    centers = list(np.linspace(cv_min_nm, cv_min_nm + spacing * (n - 1), n))
    if centers[-1] < cv_max_nm - 1e-9:
        centers.append(float(cv_max_nm))
    expected = 2 * (0.5 * (1 + math.erf(-(spacing / (2 * sigma)) / math.sqrt(2))))
    plan = WindowPlan(centers_nm=[float(c) for c in centers], force_constant_kj_mol_nm2=force_constant_kj_mol_nm2,
                      sigma_nm=sigma, spacing_nm=spacing, expected_overlap=expected, notes=notes)
    if smd_cv_nm is not None:
        cv = np.asarray(smd_cv_nm, dtype=float)
        for c in plan.centers_nm:
            i = int(np.argmin(np.abs(cv - c)))
            plan.seed_frames.append(i)
            plan.seed_cv_nm.append(float(cv[i]))
            if abs(cv[i] - c) > spacing:
                notes.append(f"window {c:.3f} nm 最近的 SMD frame 偏離 {abs(cv[i]-c):.3f} nm；SMD 可能未覆蓋此範圍。")
    notes.append(f"σ = {sigma:.4f} nm，間距 {spacing:.4f} nm，預期相鄰 overlap ≈ {expected:.2f}；"
                 "k 越大 window 越窄、數量越多；教學 tier 建議 k=1000 kJ/mol/nm²。")
    return plan
