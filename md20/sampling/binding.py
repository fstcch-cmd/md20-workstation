"""Binding strength: SMD pulling → umbrella windows → PMF (WHAM/MBAR) → ΔPMF and ΔG° estimate.

Collective variable: distance between the centre of mass of an *anchor* group (pocket Cα atoms
within 8 Å of the ligand) and the ligand heavy atoms, with periodic boundary conditions.

Teaching-level caveats written into every result:
* a 1-D COM-distance PMF does not include orientational/conformational restraint corrections, so
  ΔG° from it is an estimate (typically within a few kJ/mol of the trend, not an absolute number);
* SMD work is path- and speed-dependent (irreversible); only the PMF is a free-energy profile;
* short windows ⇒ check the overlap and half-split convergence figures before trusting the PMF.
"""
from __future__ import annotations

import json
import math
from dataclasses import fields, dataclass, field, asdict
from pathlib import Path
from typing import Callable

import numpy as np

from ..util import atomic_write_json, load_json, now_iso, DecisionLog
from ..analysis.plots import PALETTE, _mpl, _save
from .windows import plan_windows, KB_KJ_MOL_K
from .pmf import pmf_from_windows

V0_NM3 = 1.66053906660  # standard-state volume per molecule (1 M) in nm³


@dataclass
class BindingConfig:
    pull_distance_nm: float = 1.5          # how far beyond the bound distance to pull
    pull_velocity_nm_per_ps: float = 0.005  # D-63: 0.01 dissipated ~100 kT on 3PTB (laptop); SMD cost is minor
    k_pull: float = 1000.0                 # kJ/mol/nm² SMD spring
    k_umbrella: float = 1000.0             # kJ/mol/nm² window spring
    target_overlap: float = 0.2            # neighbouring windows (and the adaptive refinement's stop criterion)
    k_umbrella_max: float = 5000.0         # stiffest spring refinement may use on steep stretches
    max_refine_rounds: int = 6
    max_extensions_per_window: int = 2   # a window with few effective samples is extended at most this often
    max_new_per_round: int = 12
    # D-101: plan the first windows from the SMD force curve (denser/stiffer where it is steep) instead of a uniform grid
    smd_informed_windows: bool = True
    extra_windows: list = field(default_factory=list)   # manual "resample a–b": [{"center", "k"}] from plan_range
    window_equil_ps: float = 10.0
    window_prod_ps: float = 50.0
    sample_every_steps: int = 50
    timestep_fs: float = 2.0
    temperature_k: float = 300.0
    friction_per_ps: float = 1.0
    backbone_restraint_scale: float = 0.1  # × 1000 kJ/mol/nm² from the build restraints
    pocket_cutoff_nm: float = 0.8
    max_windows: int = 40
    box_margin_nm: float = 1.0             # d_max + ligand radius + margin must fit in half the box
    seed: int = 2026
    hold_spectators: bool = True           # D-61: other ligands of a shared pocket stay bound while one is pulled
    spectator_hold_nm: float = 0.3         # free within ±0.3 nm of their bound distance to the pocket anchor

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- geometry
def group_com(xyz: np.ndarray, idx: np.ndarray, masses: np.ndarray) -> np.ndarray:
    m = masses[idx]
    return (xyz[idx] * m[:, None]).sum(0) / m.sum()


def min_image(d: np.ndarray, box: np.ndarray) -> np.ndarray:
    """Minimum-image vector for a (possibly triclinic, reduced-form) OpenMM box (rows = box vectors, nm)."""
    d = d.copy()
    for k in (2, 1, 0):
        d -= box[k] * np.round(d[k] / box[k][k])
    return d


def cv_distance(xyz: np.ndarray, box: np.ndarray, anchor: np.ndarray, ligand: np.ndarray, masses: np.ndarray) -> float:
    return float(np.linalg.norm(min_image(group_com(xyz, ligand, masses) - group_com(xyz, anchor, masses), box)))


# --------------------------------------------------------------------------- system setup
_SOLVENT_RESNAMES = {"HOH", "WAT", "TIP3", "SOL", "NA", "CL", "K", "Na+", "Cl-", "K+", "MG", "CA2", "LI", "RB", "CS", "BR", "F", "I"}


def pocket_anchor(xyz: np.ndarray, ca: np.ndarray, lig: np.ndarray, *, cutoff_nm: float = 0.8,
                  max_cutoff_nm: float = 1.6, min_atoms: int = 4) -> tuple[np.ndarray, float]:
    """Pocket anchor rule (pure): the Cα within `cutoff` of any ligand heavy atom, widening by 0.2 nm until ≥ 4.
    Used by select_groups (SMD) and by the build's box sizing (D-99), so both see the same anchor."""
    cutoff, sel = cutoff_nm, np.array([], dtype=int)
    while len(sel) < min_atoms and cutoff <= max_cutoff_nm and len(ca):
        d = np.min(np.linalg.norm(xyz[ca][:, None, :] - xyz[lig][None, :, :], axis=2), axis=1)
        sel = ca[d <= cutoff]
        cutoff += 0.2
    return sel, cutoff - 0.2


def smd_half_box_need(xyz: np.ndarray, box: np.ndarray | None, anchor: np.ndarray, ligand: np.ndarray,
                      masses: np.ndarray, *, pull_nm: float, margin_nm: float) -> dict:
    """The SMD box rule (pure, D-99): bound distance d0 + pull + ligand radius + margin must fit in half the box.
    `box` None = not yet solvated (no minimum image)."""
    dv = group_com(xyz, ligand, masses) - group_com(xyz, anchor, masses)
    d0 = float(np.linalg.norm(min_image(dv, box) if box is not None else dv))
    lx = xyz[ligand]
    r = float(np.max(np.linalg.norm(lx - lx.mean(0), axis=1))) if len(ligand) > 1 else 0.0
    return {"d0_nm": d0, "pull_nm": float(pull_nm), "ligand_radius_nm": r, "margin_nm": float(margin_nm),
            "need_half_box_nm": d0 + float(pull_nm) + r + float(margin_nm)}


def solute_radius_nm(xyz: np.ndarray) -> float:
    """OpenMM Modeller.addSolvent's solute radius: farthest atom from the centre of the bounding box."""
    c = 0.5 * (xyz.min(0) + xyz.max(0))
    return float(np.max(np.linalg.norm(xyz - c, axis=1))) if len(xyz) else 0.0


def padding_for_half_box(radius_nm: float, half_box_nm: float) -> float:
    """Smallest OpenMM padding giving at least `half_box_nm`.  OpenMM (modeller.py, addSolvent with padding):
    width = max(2R + padding, 2·padding) and every box vector of cube / dodecahedron / octahedron has length = width,
    so half the shortest vector = max(R + p/2, p).  NB: padding is the solute-to-own-image distance, added once."""
    p = 2.0 * (half_box_nm - radius_nm)
    if p <= 2.0 * radius_nm:
        return max(p, 0.0)
    return half_box_nm


def select_groups(topology, positions_nm: np.ndarray, *, ligand_resname: str | None = None,
                  ligand_indices: list[int] | None = None, anchor_indices: list[int] | None = None,
                  pocket_cutoff_nm: float = 0.8, exclude_indices=None) -> tuple[np.ndarray, np.ndarray, dict]:
    atoms = list(topology.atoms())
    excl_res = {atoms[i].residue.index for i in (exclude_indices or [])}   # other ligands (e.g. peptides) never anchor
    if ligand_indices is None:
        ligand_indices = [a.index for a in atoms if a.residue.name == ligand_resname and a.element is not None
                          and a.element.symbol != "H"]
    lig = np.array(ligand_indices, dtype=int)
    if not len(lig):
        raise ValueError(f"找不到配體 {ligand_resname}")
    note = ""
    if anchor_indices is None:
        lig_res = {atoms[i].residue.index for i in lig}   # peptide ligands have their own CA atoms
        ca = np.array([a.index for a in atoms if a.name == "CA" and a.residue.name not in {ligand_resname, "CA"}
                       and a.residue.index not in lig_res and a.residue.index not in excl_res
                       and a.element is not None and a.element.symbol == "C"], dtype=int)
        sel, used = pocket_anchor(positions_nm, ca, lig, cutoff_nm=pocket_cutoff_nm)
        anchor_indices = sel.tolist()
        note = f"口袋 anchor：配體 {used:.1f} nm 內的 {len(sel)} 個 Cα"
    anc = np.array(anchor_indices, dtype=int)
    if not len(anc):
        raise ValueError("找不到 anchor 原子")
    return anc, lig, {"anchor_atoms": anc.tolist(), "ligand_atoms": lig.tolist(), "note": note}


def build_pulling_system(system, positions_nm: np.ndarray, anchor: np.ndarray, ligand: np.ndarray):
    """Add the CV bias; free the ligand from build restraints; re-reference backbone restraints; NVT."""
    import openmm as mm
    for i in range(system.getNumForces()):
        f = system.getForce(i)
        if isinstance(f, mm.MonteCarloBarostat):
            f.setFrequency(0)
        if isinstance(f, mm.CustomExternalForce) and f.getName() == "msw_lipid_head_restraints":
            # membrane builds: the head-group z reference is the build geometry, stale after NPT; off while pulling
            for g in range(f.getNumGlobalParameters()):
                if f.getGlobalParameterName(g) == "msw_rs_lipid_head":
                    f.setGlobalParameterDefaultValue(g, 0.0)
        if isinstance(f, mm.CustomExternalForce) and f.getName() == "msw_position_restraints":
            # pulling/umbrella: only the backbone keeps a (weak, master-scaled) restraint.  The ligand must be free
            # and so must the side chains (a pocket that cannot rearrange biases the PMF).  Older builds have no
            # `grp` parameter (backbone + ligand only); newer ones mark side chains with grp = 1.
            lig_set = set(int(x) for x in ligand)
            for p in range(f.getNumParticles()):
                idx, prm = f.getParticleParameters(p)
                prm = list(prm)
                side = len(prm) > 4 and int(round(prm[4])) == 1
                k = 0.0 if (idx in lig_set or side) else prm[0]
                x, y, z = positions_nm[idx]
                f.setParticleParameters(p, idx, [k, x, y, z] + prm[4:])
    bias = mm.CustomCentroidBondForce(2, "0.5*k_cv*(distance(g1,g2)-r0_cv)^2")
    bias.addGlobalParameter("k_cv", 0.0)
    bias.addGlobalParameter("r0_cv", 0.0)
    bias.addGroup([int(i) for i in anchor])
    bias.addGroup([int(i) for i in ligand])
    bias.addBond([0, 1], [])
    bias.setUsesPeriodicBoundaryConditions(True)
    bias.setName("md20_cv_bias")
    system.addForce(bias)
    return system


def add_spectator_hold(system, positions_nm, box, anchor, spectators: dict, masses, width_nm: float, k: float = 2000.0) -> dict:
    """D-61: while ligand A is pulled from a shared pocket, every other ligand B is kept in its bound state with a
    flat-bottom restraint on its COM distance to the pocket anchor: zero force within ±width of the bound distance.
    Without it, B may leave during A's windows and ΔG(A|B) — one leg of the cooperativity cycle — would not refer to
    "B bound".  Inside the band the restraint does nothing, so it adds no free energy as long as B stays (the fraction of
    samples at the wall is recorded and reported)."""
    import openmm as mm
    out = {}
    for name, idx in spectators.items():
        d0 = float(np.linalg.norm(min_image(group_com(positions_nm, idx, masses) - group_com(positions_nm, anchor, masses), box))) \
            if box is not None else float(np.linalg.norm(group_com(positions_nm, idx, masses) - group_com(positions_nm, anchor, masses)))
        f = mm.CustomCentroidBondForce(2, "k_sh*step(abs(distance(g1,g2)-d0_sh)-w_sh)*(abs(distance(g1,g2)-d0_sh)-w_sh)^2")
        for p_ in ("k_sh", "d0_sh", "w_sh"):
            f.addPerBondParameter(p_)
        f.addGroup([int(i) for i in anchor])
        f.addGroup([int(i) for i in idx])
        f.addBond([0, 1], [k, d0, width_nm])
        f.setUsesPeriodicBoundaryConditions(box is not None)
        f.setName(f"md20_spectator_hold_{name}")
        system.addForce(f)
        out[name] = {"d0_nm": round(d0, 3), "idx": idx}
    return out


@dataclass
class BindingResult:
    status: str
    d_bound_nm: float = 0.0
    smd: dict = field(default_factory=dict)
    windows: list = field(default_factory=list)
    pmf: dict = field(default_factory=dict)
    delta_pmf_kj_mol: float | None = None
    delta_pmf_err_kj_mol: float | None = None
    dG_err_kj_mol: float | None = None
    dG_standard_kj_mol: float | None = None
    dG_standard_kcal_mol: float | None = None
    figures: dict = field(default_factory=dict)
    caveats: list = field(default_factory=list)
    # D-96: scientific assessment (sampling/assessment.py) — execution status above, eligibility here
    assessment: dict = field(default_factory=dict)
    condition: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _make_context(system, positions, platform_name, properties, cfg: BindingConfig, seed: int,
                  timestep_fs: float | None = None):
    import openmm as mm
    from openmm import unit
    integ = mm.LangevinMiddleIntegrator(cfg.temperature_k * unit.kelvin, cfg.friction_per_ps / unit.picosecond,
                                        (timestep_fs or cfg.timestep_fs) * unit.femtoseconds)
    integ.setRandomNumberSeed(int(seed))
    ctx = mm.Context(system, integ, mm.Platform.getPlatformByName(platform_name), properties or {})
    return ctx, integ


def radial_pmf(pres, temperature_k: float) -> dict:
    """Jacobian-corrected radial PMF, well depth and radial-integration ΔG° (1 M)."""
    grid, W = np.asarray(pres.grid_nm), np.asarray(pres.pmf_kj_mol)
    kT = KB_KJ_MOL_K * temperature_k
    ok = np.isfinite(W) & (grid > 0)
    g, W_raw = grid[ok], W[ok]
    # Jacobian (volume-element) correction for a 3-D distance CV: the raw PMF contains −2kT·ln r,
    # which makes large separations look favourable.  w(r) = W(r) + 2kT·ln r is the radial PMF.
    Wv = W_raw + 2.0 * kT * np.log(g)
    Wv = Wv - np.min(Wv)
    err = np.asarray(pres.err_kj_mol)[ok] if pres.err_kj_mol is not None else None
    tail = max(3, len(Wv) // 10)
    w_bulk = float(np.mean(Wv[-tail:]))
    # D-65: the well depth is only defined if the profile is flat at the far end.  Rise across the tail window, from a
    # straight-line fit, compared with 1 kT (a curve still climbing there makes "ΔPMF" an edge value, not a depth)
    # bins past the outermost window's mean are sampled only by that window's tail (edge artefact): stop the check there
    hi = (getattr(pres, "quality", None) or {}).get("sampled_nm", [None, None])[1]
    inner = g <= hi + 1e-9 if hi is not None else np.ones_like(g, dtype=bool)
    gi, wi = (g[inner], Wv[inner]) if inner.sum() >= tail else (g, Wv)
    gt, wt = gi[-tail:], wi[-tail:]
    slope = float(np.polyfit(gt, wt, 1)[0]) if len(gt) >= 3 and np.ptp(gt) > 0 else 0.0
    tail_rise = float(slope * (gt[-1] - gt[0])) if len(gt) >= 2 else 0.0
    i_min = int(np.argmin(Wv))
    dpmf = round(w_bulk - float(Wv[i_min]), 3)
    beyond = np.where(Wv[i_min:] >= w_bulk - 0.5 * kT)[0]
    r_cut = float(g[i_min + beyond[0]] if len(beyond) else g[-1])
    bound = g <= r_cut
    integrand = 4 * np.pi * g[bound] ** 2 * np.exp(-(Wv[bound] - w_bulk) / kT)
    k_eq = float(np.trapezoid(integrand, g[bound])) if hasattr(np, "trapezoid") else float(np.trapz(integrand, g[bound]))
    dG = round(-kT * math.log(k_eq / V0_NM3), 3) if k_eq > 0 else None
    from .multi import delta_pmf_error
    return {"grid": g, "W": Wv, "W_raw": W_raw - np.min(W_raw), "err": err, "w_bulk": w_bulk, "r_min": float(g[i_min]),
            "r_cut": r_cut, "delta_pmf": dpmf, "delta_pmf_err": delta_pmf_error(g, err, i_min, tail), "dG": dG,
            "tail_rise_kj_mol": round(tail_rise, 3), "plateau": bool(abs(tail_rise) <= kT), "r_max": float(gt[-1])}


def bootstrap_binding_sigma(grid_nm, boot_pmfs, temperature_k: float, *, min_ok: int = 10) -> dict:
    """σ of ΔPMF and ΔG° from the bootstrap PMF replicates: each replicate goes through the same Jacobian
    correction / well / radial integration as the estimate, so the SD is that of the derived quantity."""
    from types import SimpleNamespace
    out = {"delta_pmf_sd": None, "dG_sd": None, "n": 0}
    if boot_pmfs is None or len(boot_pmfs) == 0:
        return out
    dp, dg = [], []
    for curve in np.asarray(boot_pmfs, dtype=float):
        try:
            r = radial_pmf(SimpleNamespace(grid_nm=grid_nm, pmf_kj_mol=curve, err_kj_mol=None), temperature_k)
        except Exception:  # noqa: BLE001
            continue
        if r["delta_pmf"] is not None and np.isfinite(r["delta_pmf"]):
            dp.append(r["delta_pmf"])
        if r["dG"] is not None and np.isfinite(r["dG"]):
            dg.append(r["dG"])
    out["n"] = len(dp)
    if len(dp) >= min_ok:
        out["delta_pmf_sd"] = round(float(np.std(dp, ddof=1)), 3)
    if len(dg) >= min_ok:
        out["dG_sd"] = round(float(np.std(dg, ddof=1)), 3)
    return out


def _unwrap_near(xyz: np.ndarray, ref: np.ndarray, box: np.ndarray) -> np.ndarray:
    """Images of `xyz` closest to `ref` (orthorhombic/triclinic via min_image on each atom)."""
    return np.asarray(ref) + np.array([min_image(np.asarray(x) - ref, box) for x in xyz])


def _reroute_exit(top, pos, box, anchor, ligand, other_ligand_indices, masses, gi, pull_distance_nm):
    """D-92: the automatic pocket anchor pulls the ligand away from the pocket centre.  In a shared pocket that line can
    run through another ligand (the work would then be pushing it aside).  Look for an exit that crosses no other
    ligand and the fewest protein heavy atoms, and put the anchor behind the ligand on that line.  Returns
    (anchor, groups info, reroute record or None).  If no free exit or no usable anchor is found, nothing changes and
    the path gate below stops as before."""
    from .multi import pull_path_blockers, find_exit_direction, anchor_for_direction
    box = np.asarray(box, float) if box is not None else None
    def unwrap(x, ref):
        return _unwrap_near(x, ref, box) if box is not None else np.asarray(x, float)
    lig_xyz = np.asarray(pos[ligand], float)
    lc = lig_xyz.mean(0)
    lig_xyz = unwrap(lig_xyz, lc)
    lc = lig_xyz.mean(0)
    others = {k: unwrap(pos[np.array(v, dtype=int)], lc) for k, v in other_ligand_indices.items() if v}
    acom = unwrap(((masses[anchor, None] * pos[anchor]).sum(0) / masses[anchor].sum())[None], lc)[0]
    blk = pull_path_blockers(acom, lig_xyz, others, pull_distance_nm=pull_distance_nm)
    if not blk:
        return anchor, gi, None
    atoms = list(top.atoms())
    spect = {int(i) for v in other_ligand_indices.values() for i in v}
    lig_set = {int(i) for i in ligand}
    prot_res = {a.residue.index for a in atoms if a.name == "CA" and a.element is not None and a.element.symbol == "C"}
    prot_heavy = np.array([a.index for a in atoms if a.residue.index in prot_res and a.index not in lig_set
                           and a.index not in spect and a.element is not None and a.element.symbol != "H"], dtype=int)
    ca_idx = np.array([a.index for a in atoms if a.name == "CA" and a.residue.index in prot_res
                       and a.index not in lig_set and a.index not in spect], dtype=int)
    if not len(ca_idx):
        return anchor, gi, None
    ex = find_exit_direction(lig_xyz, others, unwrap(pos[prot_heavy], lc) if len(prot_heavy) else None,
                             pull_distance_nm=pull_distance_nm, default_u=lc - acom)
    if ex is None:
        return anchor, gi, None
    new = anchor_for_direction(ca_idx, unwrap(pos[ca_idx], lc), lc, ex["u"])
    if new is None:
        return anchor, gi, None
    a2 = np.array(new["anchor_indices"], dtype=int)
    acom2 = unwrap(((masses[a2, None] * pos[a2]).sum(0) / masses[a2].sum())[None], lc)[0]
    if pull_path_blockers(acom2, lig_xyz, others, pull_distance_nm=pull_distance_nm):
        return anchor, gi, None
    old = "；".join(f"{b['ligand']}（{b.get('n_atoms_in_path', '?')} 個重原子）" for b in blk)
    why = (f"自動選的拉離方向（口袋 anchor → 配體）穿過其他配體：{old}。改從沒有其他配體的方向拉出：與原方向夾 "
           f"{ex['angle_from_default_deg']}°，路徑上有 {ex['protein_atoms_in_path']} 個蛋白重原子（在所有不穿過其他配體的方向中最少）；"
           f"anchor 改為配體後方的 {len(a2)} 個 Cα，anchor 到配體的方向與新方向夾 {new['angle_deg']}°。")
    rec = {"original_blockers": blk, "angle_from_default_deg": ex["angle_from_default_deg"],
           "protein_atoms_in_path": ex["protein_atoms_in_path"], "direction": [round(float(x), 4) for x in ex["u"]],
           "anchor": new}
    return a2, {**gi, "anchor_atoms": a2.tolist(), "note": why, "rerouted": True}, rec


def _state_xyz_box(ctx):
    st = ctx.getState(getPositions=True)
    xyz = st.getPositions(asNumpy=True)._value
    box = np.array([[v.x, v.y, v.z] for v in st.getPeriodicBoxVectors()])
    return xyz, box


def well_depth_hint(delta_pmf_kj_mol, n_ligand_heavy: int) -> str | None:
    """Flag a 1D PMF well that is implausibly deep for the ligand size (D-43).  Empirical ceiling: about 1.5 kcal/mol
    (≈ 6.3 kJ/mol) of binding free energy per heavy atom for the most efficient fragments, at least 40 kJ/mol."""
    try:
        d = float(delta_pmf_kj_mol)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(d) or n_ligand_heavy <= 0:
        return None
    ceiling = max(40.0, 6.3 * n_ligand_heavy)
    if d <= ceiling:
        return None
    return (f"ΔPMF 井深 {d:.0f} kJ/mol 高於 {n_ligand_heavy} 個重原子配體的經驗上限（約 {ceiling:.0f} kJ/mol）。常見原因：window 太短、"
            "配體離開口袋時周圍（水、側鏈、鹽橋）來不及鬆弛造成的取樣滯後。數值未修改；建議改用 teaching 等級或延長 window 後重跑比較。")


class WindowStartPicker:
    """Choose the SMD frame that seeds each umbrella window (D-45).

    The old rule took the *first* frame whose CV passed the window centre.  With a stiff spring and a fast pull the
    ligand sticks, slips and then rings around the spring (period ≈ 2π·√(m/k) ≈ 2 ps for a small ligand), so the
    first crossing is often an overshoot: the ligand is momentarily at the centre with the spring pulling it back,
    and the window then relaxes far from its centre (laptop run: centre 0.604 nm sampled at 0.27 nm).
    Now: after the first crossing, wait for a *relaxed* frame (|r0 − d| ≤ `relaxed_nm`, i.e. small spring force) with d
    within `tol_nm` of the centre; if none appears before the spring is `give_up_nm` past the centre, keep the first
    crossing and mark it."""

    def __init__(self, centers, *, relaxed_nm: float = 0.05, tol_nm: float = 0.05, give_up_nm: float = 0.3):
        self.centers = [float(c) for c in centers]
        self.relaxed, self.tol, self.give_up = relaxed_nm, tol_nm, give_up_nm
        self.next = 0
        self.pending: dict | None = None

    def offer(self, d: float, r0: float, snapshot) -> list:
        out = []
        while self.next < len(self.centers):
            c = self.centers[self.next]
            relaxed = abs(r0 - d) <= self.relaxed and abs(d - c) <= self.tol
            if relaxed:
                out.append((self.next, {"cv": d, "r0": r0, "xml": snapshot(), "pick": "relaxed"}))
                self.next += 1; self.pending = None
                continue
            if self.pending is None and d >= c:
                self.pending = {"cv": d, "r0": r0, "xml": snapshot(), "pick": "first_crossing"}
            if self.pending is not None and r0 >= c + self.give_up:
                out.append((self.next, self.pending))
                self.next += 1; self.pending = None
                continue
            break
        return out

    def flush(self) -> list:
        if self.pending is not None and self.next < len(self.centers):
            rec, self.pending = (self.next, self.pending), None
            self.next += 1
            return [rec]
        return []


def smd_ringing(arr) -> dict:
    """Largest CV jump between consecutive SMD records and how often the ligand runs ahead of the spring (D-45)."""
    a = np.asarray(arr, dtype=float)
    if len(a) < 3:
        return {}
    dd = np.abs(np.diff(a[:, 2]))
    ahead = float(np.mean(a[:, 2] > a[:, 1] + 0.05))
    back = float(np.mean(np.diff(a[:, 2]) < -0.05))
    return {"max_cv_jump_nm": float(dd.max()), "fraction_ligand_ahead_of_spring": ahead, "fraction_backward_steps": back,
            "record_interval_ps": float(a[1, 0] - a[0, 0])}


def finished_result(out_dir: Path | str, cfg: "BindingConfig") -> "BindingResult | None":
    """Finished is finished: a second call with the same config returns the stored result instead of re-planning
    the refinement on the (now larger) sample set — that re-ran extend_window and shifted ΔPMF (CI Windows:
    3.518 → 3.396 kJ/mol on the resume call).  A changed config (e.g. manual extra_windows from the coverage
    chart) reopens the sampling."""
    manifest = load_json(Path(out_dir) / "binding_manifest.json", {})
    prev = manifest.get("result") or {}
    stored = {**BindingConfig().to_dict(), **(manifest.get("config") or {})}   # fields added later keep old results valid
    if manifest.get("status") == "PASS" and prev.get("status") == "PASS" and manifest.get("config") and stored == cfg.to_dict():
        known = {f.name for f in fields(BindingResult)}
        return BindingResult(**{k: v for k, v in prev.items() if k in known})
    return None


def anchor_atoms_from_residues(topology_pdb, spec: str) -> tuple[list[int], list[str]]:
    """D-93: the student names anchor residues by their number in the structure ("120, 145, A:163"); the anchor is
    their Cα atoms.  Atom index = order of the ATOM/HETATM records (how OpenMM numbers a PDB it wrote).  Returns
    (indices, residues not found)."""
    import re as _re
    want = []
    for tok in _re.split(r"[\s,，;；]+", str(spec or "").strip()):
        if not tok:
            continue
        m = _re.fullmatch(r"(?:([A-Za-z0-9]):)?(-?\d+)", tok)
        if not m:
            want.append((None, None, tok))
            continue
        want.append((m.group(1), int(m.group(2)), tok))
    found: dict[str, int] = {}
    i = 0
    for line in Path(topology_pdb).read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith(("ATOM", "HETATM")):
            continue
        if line[12:16].strip() == "CA" and line[76:78].strip() in ("C", ""):
            try:
                rs = int(line[22:26])
            except ValueError:
                rs = None
            ch = line[21].strip()
            for c, r, tok in want:
                if r is not None and rs == r and (c is None or c == ch) and tok not in found:
                    found[tok] = i
        i += 1
    return [found[t] for _, _, t in want if t in found], [t for _, _, t in want if t not in found]


def run_binding(system_xml: Path | str, topology_pdb: Path | str, start_state_xml: Path | str | None, out_dir: Path | str, *,
                ligand_resname: str | None = None, ligand_indices: list[int] | None = None,
                anchor_indices: list[int] | None = None, config: BindingConfig | None = None,
                platform_name: str = "CPU", platform_properties: dict | None = None,
                decisions: DecisionLog | None = None, should_pause: Callable[[], str | None] | None = None,
                progress_cb: Callable[[dict], None] | None = None, positions_override=None,
                other_ligand_indices: dict[str, list[int]] | None = None) -> BindingResult:
    cfg = config or BindingConfig()
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    done = finished_result(out, cfg)
    if done is not None:
        return done
    import openmm as mm
    from openmm import app, unit, XmlSerializer
    wdir = out / "windows"; wdir.mkdir(exist_ok=True)
    system = XmlSerializer.deserialize(Path(system_xml).read_text(encoding="utf-8"))
    pdb = app.PDBFile(str(topology_pdb))
    top = pdb.topology
    if start_state_xml:
        st = XmlSerializer.deserialize(Path(start_state_xml).read_text(encoding="utf-8"))
        pos = st.getPositions(asNumpy=True)._value
        box_vecs = st.getPeriodicBoxVectors()
    else:
        pos = np.asarray(positions_override if positions_override is not None else pdb.getPositions(asNumpy=True)._value)
        box_vecs = top.getPeriodicBoxVectors() or system.getDefaultPeriodicBoxVectors()
    masses = np.array([system.getParticleMass(i).value_in_unit(unit.dalton) for i in range(system.getNumParticles())])
    anchor, ligand, gi = select_groups(top, pos, ligand_resname=ligand_resname, ligand_indices=ligand_indices,
                                       anchor_indices=anchor_indices, pocket_cutoff_nm=cfg.pocket_cutoff_nm,
                                       exclude_indices=[i for v in (other_ligand_indices or {}).values() for i in v])
    if other_ligand_indices and anchor_indices is None:
        anchor, gi, reroute = _reroute_exit(top, pos, np.array([[v.x, v.y, v.z] for v in box_vecs]) if box_vecs else None,
                                            anchor, ligand, other_ligand_indices, masses, gi, cfg.pull_distance_nm)
        if reroute and decisions:
            decisions.record("binding.path", "multi-ligand exit path", "rerouted", gi["note"], kind="auto_fixed")
    else:
        reroute = None
    system = build_pulling_system(system, pos, anchor, ligand)
    spect = {}
    if other_ligand_indices and cfg.hold_spectators:
        spect = add_spectator_hold(system, pos, np.array([[v.x, v.y, v.z] for v in box_vecs]) if box_vecs else None, anchor,
                                   {k: np.array(v, dtype=int) for k, v in other_ligand_indices.items() if v}, masses, cfg.spectator_hold_nm)
    manifest = load_json(out / "binding_manifest.json", {})
    manifest.update({"config": cfg.to_dict(), "groups": gi, "platform": platform_name, "updated_at": now_iso()})
    if reroute:
        manifest["reroute"] = reroute
    if decisions:
        decisions.record("binding.setup", "CV", "COM distance anchor–ligand", gi["note"] or "使用者指定 anchor 原子。",
                         k_pull=cfg.k_pull, v=cfg.pull_velocity_nm_per_ps)
    # ------------------------------------------------------------------ SMD
    smd_file = out / "smd.json"
    smd = load_json(smd_file, {})
    ctx, integ = _make_context(system, pos, platform_name, platform_properties, cfg, cfg.seed)
    ctx.setPeriodicBoxVectors(*box_vecs)
    ctx.setPositions(pos * unit.nanometer)
    if "msw_restraint_scale" in ctx.getParameters():
        ctx.setParameter("msw_restraint_scale", cfg.backbone_restraint_scale)
    if "msw_fb_scale" in ctx.getParameters():
        ctx.setParameter("msw_fb_scale", 0.0)   # multi-ligand flat-bottom restraints are off for free-energy work
    xyz, box = _state_xyz_box(ctx)
    d0 = cv_distance(xyz, box, anchor, ligand, masses)
    bc = smd_half_box_need(xyz, box, anchor, ligand, masses, pull_nm=cfg.pull_distance_nm, margin_nm=cfg.box_margin_nm)
    lig_radius, need = bc["ligand_radius_nm"], bc["need_half_box_nm"]
    lig_xyz = xyz[ligand]
    half_box = 0.5 * float(min(np.linalg.norm(box, axis=1)))
    manifest["box_check"] = {**bc, "half_box_nm": half_box}
    if need > half_box:
        # D-99: say exactly which padding would have been enough for THIS structure (same rule as the build's sizing)
        solute = np.array([a.index for a in top.atoms() if a.residue.name not in _SOLVENT_RESNAMES], dtype=int)
        r_sol = solute_radius_nm(_unwrap_near(xyz[solute], xyz[anchor].mean(0), box)) if len(solute) else 0.0
        p_need = padding_for_half_box(r_sol, need)
        manifest["box_check"].update({"solute_radius_nm": r_sol, "padding_needed_nm": round(p_need + 0.05, 2)})
        msg = (f"水盒太小：拉離終點 {d0 + cfg.pull_distance_nm:.2f} nm + 配體半徑 {lig_radius:.2f} + 安全距離 "
               f"{cfg.box_margin_nm:.1f} = {need:.2f} nm，超過盒子半長 {half_box:.2f} nm；配體會接近週期影像，PMF 不可信。"
               f"這個結構至少要 padding {p_need + 0.05:.2f} nm（OpenMM 的 padding 是溶質到自身影像的距離，只加一次）。"
               f"選項：md.padding_nm: {p_need + 0.05:.2f} 後重建／縮短 binding.config.pull_distance_nm。")
        manifest.update({"status": "NEEDS_HUMAN", "reason": msg})
        atomic_write_json(json.loads(json.dumps(manifest, default=_np_default)), out / "binding_manifest.json")
        if decisions:
            decisions.record("binding.box", "box size", "NEEDS_HUMAN", msg, kind="human")
        return BindingResult(status="NEEDS_HUMAN", d_bound_nm=d0, caveats=[msg])
    if other_ligand_indices:
        # WP9: in a shared pocket, the exit path of the pulled ligand must be free of the other ligands
        from .multi import pull_path_blockers
        others = {k: _unwrap_near(xyz[np.array(v, dtype=int)], lig_xyz.mean(0), box) for k, v in other_ligand_indices.items() if v}
        acom = (masses[anchor, None] * xyz[anchor]).sum(0) / masses[anchor].sum()
        acom = _unwrap_near(acom[None], lig_xyz.mean(0), box)[0]
        blk = pull_path_blockers(acom, lig_xyz, others, pull_distance_nm=cfg.pull_distance_nm)
        manifest["path_check"] = {"blockers": blk, "others": sorted(others)}
        if blk:
            msg = ("拉離路徑被其他配體擋住：" + "；".join(f"{b['ligand']} 有 {b.get('n_atoms_in_path', '?')} 個重原子在拉離圓柱內"
                                                      f"（沿路徑 {b.get('nearest_along_path_nm', '?')} nm）" for b in blk)
                   + "。穿過另一個配體拉離得到的是推開它的功，不是本配體的結合自由能。")
            manifest.update({"status": "NEEDS_HUMAN", "reason": msg})
            atomic_write_json(json.loads(json.dumps(manifest, default=_np_default)), out / "binding_manifest.json")
            if decisions:
                decisions.record("binding.path", "multi-ligand exit path", "NEEDS_HUMAN", msg, kind="human")
            return BindingResult(status="NEEDS_HUMAN", d_bound_nm=d0, caveats=[msg + "選項：先拉外側配體／只算單獨結合（docked_single）／指定 anchor_indices 改變方向"])
        if decisions:
            decisions.record("binding.path", "multi-ligand exit path", "clear",
                             f"其他配體（{', '.join(sorted(others))}）不在拉離圓柱內；" + (f"拉離期間以平底限制保持在結合距離 ±{cfg.spectator_hold_nm} nm 內（範圍內無力，D-61），"
                             "可在口袋內重排但不會離開，確保這一腿量的是「另一配體仍結合」時的自由能。" if cfg.hold_spectators else
                             "拉離期間它們不加限制（可自由移動），結果含其重排。"))
    plan = plan_windows(d0, d0 + cfg.pull_distance_nm, force_constant_kj_mol_nm2=cfg.k_umbrella,
                        temperature_k=cfg.temperature_k, target_overlap=cfg.target_overlap, max_windows=cfg.max_windows)
    if smd.get("status") != "PASS":
        if not start_state_xml:
            mm.LocalEnergyMinimizer.minimize(ctx, maxIterations=500)
        ctx.setVelocitiesToTemperature(cfg.temperature_k * unit.kelvin, cfg.seed)
        ctx.setParameter("k_cv", cfg.k_pull)
        ctx.setParameter("r0_cv", d0)
        integ.step(int(2000 / cfg.timestep_fs))  # 2 ps settle at the bound distance
        dt_ps = cfg.timestep_fs / 1000.0
        n_steps = int(math.ceil(cfg.pull_distance_nm / cfg.pull_velocity_nm_per_ps / dt_ps))
        rec_every = max(1, int(0.2 / dt_ps))  # every 0.2 ps
        rows, work = [], 0.0
        r0 = d0
        saved = {}
        picker = WindowStartPicker(plan.centers_nm)
        for s in range(0, n_steps, rec_every):
            nstep = min(rec_every, n_steps - s)
            dr = cfg.pull_velocity_nm_per_ps * dt_ps * nstep
            xyz, box = _state_xyz_box(ctx)
            d = cv_distance(xyz, box, anchor, ligand, masses)
            force = cfg.k_pull * (r0 - d)
            work += force * dr
            rows.append((s * dt_ps, r0, d, force, work))
            for w, rec in picker.offer(d, r0, lambda: XmlSerializer.serialize(ctx.getState(getPositions=True, getVelocities=True))):
                path = wdir / f"w{w:03d}_start.xml"
                path.write_text(rec.pop("xml"), encoding="utf-8")
                saved[w] = {"path": str(path), **rec}
            r0 += dr
            ctx.setParameter("r0_cv", r0)
            integ.step(nstep)
            if progress_cb and len(rows) % 50 == 0:
                progress_cb({"stage": "smd", "r0": r0, "d": d, "force": force, "work": work})
        for w, rec in picker.flush():
            path = wdir / f"w{w:03d}_start.xml"
            path.write_text(rec.pop("xml"), encoding="utf-8")
            saved[w] = {"path": str(path), **rec}
        # windows the ligand never reached (lags behind the spring): seed from the last frame
        xyz, box = _state_xyz_box(ctx)
        for w in range(len(plan.centers_nm)):
            if w in saved:
                continue
            path = wdir / f"w{w:03d}_start.xml"
            path.write_text(XmlSerializer.serialize(ctx.getState(getPositions=True, getVelocities=True)), encoding="utf-8")
            saved[w] = {"path": str(path), "cv": cv_distance(xyz, box, anchor, ligand, masses), "fallback": True}
        arr = np.array(rows)
        smd_diag = smd_ringing(arr)
        np.savetxt(out / "smd.tsv", arr, header="time_ps\tr0_nm\td_nm\tforce_kj_mol_nm\twork_kj_mol", delimiter="\t")
        smd = {"status": "PASS", "d0_nm": d0, "n_steps": n_steps, "max_force_kj_mol_nm": float(arr[:, 3].max()),
               "final_work_kj_mol": float(arr[-1, 4]), "window_starts": {str(k): v for k, v in saved.items()},
               "diagnostics": smd_diag,
               "plan": plan.to_dict(), "sealed_at": now_iso()}
        atomic_write_json(smd, smd_file)
    del ctx, integ
    # ------------------------------------------------------------------ umbrella windows (adaptive, coarse → fine)
    from .adaptive import plan_refinement, coverage_view, continuity_report, gap_alerts, plan_from_smd
    eq_steps = int(cfg.window_equil_ps * 1000 / cfg.timestep_fs)
    pr_steps = int(cfg.window_prod_ps * 1000 / cfg.timestep_fs)
    samples: dict[float, np.ndarray] = {}
    hold_wall: dict[float, float] = {}
    finals: dict[float, str] = {}
    k_file = wdir / "windows_k.json"
    ks: dict[float, float] = {float(c): float(v) for c, v in load_json(k_file, {}).items() if not c.startswith("_")}
    refine_log: list[dict] = load_json(out / "refine_log.json", [])

    def wfile(c: float, kind: str) -> Path:
        return wdir / f"w_{c:.4f}_{kind}"

    alerts_seen: set = set()
    planned_now: list = []

    def write_coverage(status: str) -> list:
        """Live data for the GUI coverage chart, rewritten after every window (D-101: + early gap alerts, and the
        coverage figure is written every time, so a message that points at it never points at nothing)."""
        view = coverage_view(samples, ks) if len(samples) >= 1 else {}
        alerts = gap_alerts(samples, ks, planned=planned_now, temperature_k=cfg.temperature_k,
                            target_overlap=cfg.target_overlap, k_max=cfg.k_umbrella_max) if len(samples) >= 2 else []
        fig = {}
        if samples:
            try:
                from ..analysis.plots import plot_umbrella_histograms
                fig = plot_umbrella_histograms(samples, out / "umbrella_coverage", breaks=view.get("breaks") or [],
                                               alerts=alerts, cv_range=(d0, d0 + cfg.pull_distance_nm))
            except Exception as exc:  # noqa: BLE001
                fig = {"error": f"{type(exc).__name__}: {exc}"}
        atomic_write_json({"status": status, "updated_at": now_iso(), "d0_nm": d0,
                           "cv_range_nm": [d0, d0 + cfg.pull_distance_nm], "rounds": refine_log,
                           "planned_centers": sorted(planned_now), "alerts": alerts, "figure": fig,
                           "message": ("SMD 拉離中或尚未開始，還沒有任何 window 的樣本。" if not samples else ""), **view},
                          out / "coverage.json")
        for al in alerts:                                     # each new gap is logged once, when it is first seen
            key = tuple(al["windows"])
            if key not in alerts_seen:
                alerts_seen.add(key)
                if decisions is not None:
                    decisions.record("binding.umbrella", "gap alert", {"nm": [al["lo"], al["hi"]], "cause": al["cause"]},
                                     f"{al['lo']:.3f}–{al['hi']:.3f} nm 的取樣開始不連續（相鄰 window 重疊 {al['overlap']:.2f}）：{al['why']}。"
                                     f"{al['action']}。", kind="auto")
        return alerts

    def sim_window(c: float, k: float, start_xml: str, seed: int, equilibrate: bool) -> tuple[np.ndarray, str]:
        """One window; a NaN blow-up (OpenMM raises) is retried once from the same start after a short restrained
        minimization at half the timestep (same simulated time) — CI 1634916, D-32.  A second failure is reported."""
        try:
            return _sim_window(c, k, start_xml, seed, equilibrate, retry=False)
        except Exception as exc:  # noqa: BLE001 — OpenMMException "Particle coordinate is NaN"
            if "nan" not in str(exc).lower():
                raise
            if decisions is not None:
                decisions.record("binding.umbrella", f"window {c:.3f} nm", "NaN → retry",
                                 f"window {c:.3f} nm（k = {k:.0f}）在 {cfg.timestep_fs:g} fs 下出現 NaN；從同一起點先做短暫最小化（偏壓開著），"
                                 f"再以 {cfg.timestep_fs / 2:g} fs、相同模擬時間重跑一次。再失敗就停下回報。", kind="auto_fixed")
            try:
                return _sim_window(c, k, start_xml, seed + 1, equilibrate, retry=True)
            except Exception as exc2:  # noqa: BLE001
                raise RuntimeError(f"window {c:.3f} nm 兩次都出現 NaN（{cfg.timestep_fs:g} 與 {cfg.timestep_fs / 2:g} fs）：{exc2}。"
                                   "請檢查 SMD 起始幀與 k_umbrella；不以內插或略過 window 代替。") from exc2

    def _sim_window(c: float, k: float, start_xml: str, seed: int, equilibrate: bool, *, retry: bool) -> tuple[np.ndarray, str]:
        dt = cfg.timestep_fs / 2.0 if retry else cfg.timestep_fs
        f = 2 if retry else 1
        ctx, integ = _make_context(system, pos, platform_name, platform_properties, cfg, seed, timestep_fs=dt)
        ctx.setState(XmlSerializer.deserialize(Path(start_xml).read_text(encoding="utf-8")))
        if "msw_restraint_scale" in ctx.getParameters():
            ctx.setParameter("msw_restraint_scale", cfg.backbone_restraint_scale)
        if "msw_fb_scale" in ctx.getParameters():
            ctx.setParameter("msw_fb_scale", 0.0)
        ctx.setParameter("k_cv", float(k))
        ctx.setParameter("r0_cv", float(c))
        if retry:
            import openmm as _mm
            _mm.LocalEnergyMinimizer.minimize(ctx, 10.0, 200)
            ctx.setVelocitiesToTemperature(cfg.temperature_k * unit.kelvin, int(seed))
        if equilibrate:
            integ.step(eq_steps * f)
        vals = []
        wall = 0
        for _ in range(0, pr_steps, cfg.sample_every_steps):
            integ.step(cfg.sample_every_steps * f)
            xyz_, box_ = _state_xyz_box(ctx)
            vals.append(cv_distance(xyz_, box_, anchor, ligand, masses))
            for sp in spect.values():
                if abs(cv_distance(xyz_, box_, anchor, sp["idx"], masses) - sp["d0_nm"]) > cfg.spectator_hold_nm:
                    wall += 1
                    break
        if spect:
            hold_wall[float(c)] = wall / max(1, len(vals))
        arr = np.asarray(vals)
        if not np.all(np.isfinite(arr)):
            raise RuntimeError(f"window {c:.3f} nm 出現 NaN")
        xml = XmlSerializer.serialize(ctx.getState(getPositions=True, getVelocities=True))
        del ctx, integ
        return arr, xml

    def paused() -> bool:
        if should_pause is not None and (reason := should_pause()):
            manifest.update({"status": "PAUSED", "reason": reason, "windows_done": len(samples)})
            atomic_write_json(manifest, out / "binding_manifest.json")
            write_coverage("PAUSED")
            return True
        return False

    def run_window(c: float, start_xml: str, seed: int, k: float) -> bool:
        npy = wfile(c, "cv.npy")
        if npy.is_file():
            samples[c] = np.load(npy)
            finals[c] = str(wfile(c, "final.xml"))
            ks.setdefault(c, float(k))
            return True
        if paused():
            return False
        arr, xml = sim_window(c, k, start_xml, seed, equilibrate=True)
        wfile(c, "final.xml").write_text(xml, encoding="utf-8")
        np.save(npy, arr)
        samples[c], finals[c], ks[c] = arr, str(wfile(c, "final.xml")), float(k)
        atomic_write_json({f"{kc:.4f}": kv for kc, kv in ks.items()}, k_file)
        alerts = write_coverage("RUNNING")
        if progress_cb:
            progress_cb({"stage": "umbrella", "window": len(samples), "n": max(len(samples), len(planned_now)),
                         "mean": float(arr.mean()), "k": float(k), "continuous": continuity_report(samples)["continuous"]
                         if len(samples) >= 2 else None,
                         "alerts": [{k_: a[k_] for k_ in ("lo", "hi", "cause")} for a in alerts]})
        return True

    def extend_window(c: float, rnd: int) -> bool:
        """More samples for a window (continue from its last frame; no re-equilibration) — never a duplicate window."""
        marker = wfile(c, f"ext{rnd}.done")
        if marker.is_file():
            return True
        if paused():
            return False
        arr, xml = sim_window(c, ks[c], finals[c], cfg.seed + 104729 + rnd + int(c * 1e4), equilibrate=False)
        samples[c] = np.concatenate([samples[c], arr])
        np.save(wfile(c, "cv.npy"), samples[c])
        wfile(c, "final.xml").write_text(xml, encoding="utf-8")
        marker.write_text(now_iso(), encoding="utf-8")
        write_coverage("RUNNING")
        return True

    smd_starts = [(float(v["cv"]), v["path"]) for v in smd.get("window_starts", {}).values()]

    def start_for(c: float) -> str:
        """Start a new window from the configuration that actually sampled closest to c (a finished window's last
        frame, judged by its sampled mean — not its centre) or the nearest SMD frame."""
        cands = [(abs(float(np.mean(samples[w])) - c), finals[w]) for w in samples] + [(abs(cv - c), pth) for cv, pth in smd_starts]
        return min(cands)[1]

    centers = [float(c) for c in smd["plan"]["centers_nm"]]
    # D-101: the first windows follow the SMD force curve (denser and stiffer where steep, centres aimed uphill).
    # Computed once and stored in smd.json; a run that already started windows on the uniform grid keeps it.
    informed = smd.get("informed_plan")
    started_uniform = any(wfile(c, "cv.npy").is_file() for c in centers) and informed is None
    if informed is None and cfg.smd_informed_windows and not started_uniform and (out / "smd.tsv").is_file():
        try:
            tsv = np.loadtxt(out / "smd.tsv", delimiter="\t", ndmin=2)
            informed = plan_from_smd(tsv[:, 2], tsv[:, 3], d0, d0 + cfg.pull_distance_nm, k0=cfg.k_umbrella,
                                     k_max=cfg.k_umbrella_max, temperature_k=cfg.temperature_k,
                                     target_overlap=cfg.target_overlap, max_windows=cfg.max_windows)
        except Exception as exc:  # noqa: BLE001
            informed = {"uniform": True, "notes": [f"力曲線讀取失敗（{type(exc).__name__}），沿用等距規劃。"], "centers": [], "k": []}
        smd["informed_plan"] = informed
        atomic_write_json(json.loads(json.dumps(smd, default=_np_default)), smd_file)
        if decisions is not None:
            decisions.record("binding.windows", "initial plan from SMD", {"n": len(informed.get("centers") or []),
                             "regions": informed.get("regions")},
                             ("依 SMD 力曲線規劃第一批 window：" + " ".join(informed.get("notes") or [])
                              + f"共 {len(informed.get('centers') or [])} 個（等距規劃為 {len(centers)} 個）。陡的地方 k 依 F′²/4kT 提高、"
                              "中心往上坡預先偏移，讓 window 一開始就留在原位，減少事後補窗的輪數。")
                             if not informed.get("uniform") else " ".join(informed.get("notes") or []))
    if informed and not informed.get("uniform") and informed.get("centers"):
        first = list(zip([float(c) for c in informed["centers"]], [float(k) for k in informed["k"]]))
        planned_now[:] = [c for c, _ in first]
        for w, (c, k) in enumerate(first):
            if not run_window(c, start_for(c), cfg.seed + 17 * (w + 1), k):
                return BindingResult(status="PAUSED", d_bound_nm=d0, smd=smd, caveats=[manifest.get("reason", "")])
    else:
        planned_now[:] = centers
        for w, c in enumerate(centers):
            if not run_window(c, smd["window_starts"][str(w)]["path"], cfg.seed + 17 * (w + 1), cfg.k_umbrella):
                return BindingResult(status="PAUSED", d_bound_nm=d0, smd=smd, caveats=[manifest.get("reason", "")])
    # manual "resample a–b" windows requested by the user (GUI coverage chart → plan_range → config)
    manual = []
    for i, ew in enumerate(cfg.extra_windows or []):
        c, k = float(round(float(ew["center"]), 4)), float(ew.get("k") or cfg.k_umbrella)
        if c not in samples:
            if not run_window(c, start_for(c), cfg.seed + 6151 + i, k):
                return BindingResult(status="PAUSED", d_bound_nm=d0, smd=smd, caveats=[manifest.get("reason", "")])
            manual.append(c)
    if manual and decisions:
        decisions.record("binding.windows", "manual resample", [round(c, 3) for c in manual],
                         "使用者在覆蓋圖上指定區間補採樣（plan_range：依附近斜率決定 k 與中心偏移）。", kind="human")
    # adaptive refinement: large holes first, then the residual small ones; extend instead of duplicating.
    # Resumable and idempotent: rounds that completed are not re-planned (re-planning on the enlarged sample set
    # would add windows and change a finished PMF); a new manual request reopens refinement with a fresh budget.
    added: list[float] = [c for e in refine_log for c in (i["center"] for i in e.get("insert", []))]
    final_plan = None
    # extensions already done per window (any round, incl. rounds reopened by a manual request)
    ext_count: dict[float, int] = {c: len(list(wdir.glob(f"w_{c:.4f}_ext*.done"))) for c in samples}
    # mid-refinement resume (pause/crash): continue from the next incomplete round instead of re-planning finished
    # rounds; a finished run is returned earlier by finished_result(); a new manual request reopens with a new budget
    state_file = out / "refine_state.json"
    rstate = load_json(state_file, {})
    manual_sig = sorted(round(float(ew["center"]), 4) for ew in (cfg.extra_windows or []))
    if rstate.get("manual") != manual_sig:
        rstate = {"finished": False, "base_round": len([e for e in refine_log if e.get("completed")]), "manual": manual_sig}
        atomic_write_json(rstate, state_file)
    first = len([e for e in refine_log if e.get("completed")])
    last = rstate["base_round"] + cfg.max_refine_rounds
    for rnd in (range(first, last) if not rstate.get("finished") else range(0)):
        rp = plan_refinement(samples, ks, temperature_k=cfg.temperature_k, target_overlap=cfg.target_overlap,
                             k_max=cfg.k_umbrella_max, max_new_per_round=cfg.max_new_per_round,
                             max_total_windows=cfg.max_windows, cv_range=(d0, d0 + cfg.pull_distance_nm),
                             min_effective_samples=min(100.0, 0.25 * pr_steps / cfg.sample_every_steps),
                             extensions_done=ext_count, max_extensions=cfg.max_extensions_per_window)
        final_plan = rp
        entry = {"round": rnd + 1, "insert": rp.insert, "extend": [e["center"] for e in rp.extend],
                 "holes": rp.holes, "unsamplable": rp.unsamplable, "notes": rp.notes, "continuous": rp.continuous}
        if not refine_log or refine_log[-1].get("round") != rnd + 1:
            refine_log.append(entry)
        else:
            refine_log[-1] = entry
        atomic_write_json(refine_log, out / "refine_log.json")
        if rp.done or (not rp.insert and not rp.extend):
            refine_log[-1]["completed"] = True
            atomic_write_json(refine_log, out / "refine_log.json")
            break
        for e in rp.extend:
            if not extend_window(float(e["center"]), rnd + 1):
                return BindingResult(status="PAUSED", d_bound_nm=d0, smd=smd, caveats=[manifest.get("reason", "")])
            ext_count[float(e["center"])] = ext_count.get(float(e["center"]), 0) + 1
        planned_now.extend(float(i["center"]) for i in rp.insert)
        for j, ins in enumerate(rp.insert):
            c = float(ins["center"])
            if not run_window(c, start_for(c), cfg.seed + 7919 * (rnd + 1) + j, float(ins["k"])):
                return BindingResult(status="PAUSED", d_bound_nm=d0, smd=smd, caveats=[manifest.get("reason", "")])
            added.append(c)
        refine_log[-1]["completed"] = True
        atomic_write_json(refine_log, out / "refine_log.json")
        if decisions:
            decisions.record("binding.windows", f"refine round {rnd + 1}",
                             {"insert": [(round(i["center"], 3), i["k"]) for i in rp.insert],
                              "extend": [round(e["center"], 3) for e in rp.extend]},
                             "；".join(dict.fromkeys(i["why"] for i in rp.insert)) or "只延長樣本不足的 window。")
    if not rstate.get("finished"):
        rstate["finished"] = True
        atomic_write_json(rstate, state_file)
    if final_plan is None and refine_log:          # resumed after refinement had finished: report its last state
        last_e = refine_log[-1]
        from types import SimpleNamespace
        final_plan = SimpleNamespace(unsamplable=last_e.get("unsamplable", []))
    cont = continuity_report(samples)
    write_coverage("DONE")
    centers = sorted(samples)
    # ------------------------------------------------------------------ PMF + ΔG
    pres = pmf_from_windows(samples, force_constant_kj_mol_nm2=dict(ks), temperature_k=cfg.temperature_k,
                            out_dir=out, n_bootstrap=100)
    res = BindingResult(status="PASS", d_bound_nm=d0, smd=smd, windows=[{"center_nm": c, "k": ks[c], "n": int(len(samples[c])),
                        "mean_nm": float(samples[c].mean()), "sd_nm": float(samples[c].std()), "added": c in added,
                        "manual": c in manual} for c in centers])
    rp = radial_pmf(pres, cfg.temperature_k)
    g, Wv, err = rp["grid"], rp["W"], rp["err"]
    res.delta_pmf_kj_mol, res.dG_standard_kj_mol = rp["delta_pmf"], rp["dG"]
    bs = bootstrap_binding_sigma(pres.grid_nm, getattr(pres, "boot_pmfs", None), cfg.temperature_k)
    # bootstrap SD of the derived quantities; the point-wise approximation is only a fallback
    res.delta_pmf_err_kj_mol = bs["delta_pmf_sd"] if bs["delta_pmf_sd"] is not None else rp["delta_pmf_err"]
    res.dG_err_kj_mol = bs["dG_sd"]
    if res.dG_standard_kj_mol is not None:
        res.dG_standard_kcal_mol = round(res.dG_standard_kj_mol / 4.184, 3)
    # half-split convergence: first vs second half of every window
    half = {}
    try:
        h1 = {c: v[: len(v) // 2] for c, v in samples.items()}
        h2 = {c: v[len(v) // 2:] for c, v in samples.items()}
        a = radial_pmf(pmf_from_windows(h1, force_constant_kj_mol_nm2=dict(ks), temperature_k=cfg.temperature_k,
                                        n_bootstrap=0), cfg.temperature_k)
        b = radial_pmf(pmf_from_windows(h2, force_constant_kj_mol_nm2=dict(ks), temperature_k=cfg.temperature_k,
                                        n_bootstrap=0), cfg.temperature_k)
        half = {"first_half_dpmf": a["delta_pmf"], "second_half_dpmf": b["delta_pmf"],
                "diff_kj_mol": round(abs(a["delta_pmf"] - b["delta_pmf"]), 3)}
    except Exception as exc:  # noqa: BLE001
        half = {"error": str(exc)}
    # D-58: PMF convergence (cumulative 25/50/75 % of every window) and the window-overlap matrix, for the report
    conv = {}
    for fr in (0.25, 0.5, 0.75):
        try:
            part = {c: v[: max(5, int(len(v) * fr))] for c, v in samples.items()}
            q = radial_pmf(pmf_from_windows(part, force_constant_kj_mol_nm2=dict(ks), temperature_k=cfg.temperature_k,
                                            n_bootstrap=0), cfg.temperature_k)
            conv[f"{fr:.2f}"] = {"grid_nm": np.asarray(q["grid"]).tolist(), "pmf_kj_mol": np.asarray(q["W"]).tolist(),
                                 "delta_pmf": q["delta_pmf"]}
        except Exception as exc:  # noqa: BLE001
            conv[f"{fr:.2f}"] = {"error": str(exc)}
    conv["1.00"] = {"grid_nm": g.tolist(), "pmf_kj_mol": Wv.tolist(), "delta_pmf": rp["delta_pmf"]}
    try:
        from ..analysis.extended import histogram_overlap_matrix
        overlap = histogram_overlap_matrix(samples)
    except Exception as exc:  # noqa: BLE001
        overlap = {"error": str(exc)}
    res.pmf = {"method": pres.method, "converged": pres.converged, "quality": pres.quality,
               "bound_cutoff_nm": rp["r_cut"], "w_bulk_kj_mol": rp["w_bulk"], "r_min_nm": rp["r_min"],
               "jacobian_corrected": True, "half_split": half, "convergence": conv, "overlap_matrix": overlap,
               "err_kj_mol": (np.asarray(err).tolist() if err is not None else None),
               "grid_nm": g.tolist(), "pmf_radial_kj_mol": Wv.tolist(), "pmf_raw_kj_mol": rp["W_raw"].tolist()}
    res.figures = dict(pres.figures)
    from ..analysis.plots import plot_pmf
    res.figures["pmf"] = plot_pmf(g, Wv, err, out / "pmf")
    res.figures["smd"] = _plot_smd(out / "smd.tsv", out / "smd_force_work")
    res.figures["umbrella_coverage"] = load_json(out / "coverage.json", {}).get("figure") or {}
    res.caveats = [
        f"拉離與每個 window 期間，蛋白骨架施加 {cfg.backbone_restraint_scale * 1000:.0f} kJ/mol/nm² 位置限制"
        f"（避免整顆蛋白被拖走）；PMF 不包含蛋白構形重排的自由能。",
        "ΔPMF 是一維 COM 距離 PMF 的井深，不等於實驗結合自由能。",
        "PMF 已做 Jacobian 校正（+2kT·ln r）；未校正的一維距離 PMF 會因 r² 體積項而在遠距離偏低。",
        "ΔG° 以徑向積分與 1 M 標準態估算，未包含方向／構形約束校正；適合比較配體間趨勢。",
        "SMD 的功與拉伸速度有關（不可逆），只有 PMF 是自由能剖面。",
    ]
    diag = (smd or {}).get("diagnostics") or {}
    if diag.get("max_cv_jump_nm", 0) > 0.1:
        res.caveats.append(f"SMD 拉離時配體與彈簧之間出現明顯振盪（相鄰兩筆紀錄間距離最大跳動 {diag['max_cv_jump_nm']:.2f} nm，"
                           f"{diag.get('fraction_backward_steps', 0) * 100:.0f}% 的紀錄距離倒退）：拉離速度偏快或彈簧偏硬。"
                           "傘狀採樣窗口已改由彈簧接近鬆弛的幀起始；建議降低拉離速度（0.001 至 0.005 nm ps⁻¹）。")
    starts = (smd or {}).get("window_starts") or {}
    n_first = sum(1 for v in starts.values() if v.get("pick") == "first_crossing")
    if n_first:
        res.caveats.append(f"{n_first} 個窗口找不到彈簧鬆弛的起始幀，沿用第一次越過中心的幀（可能處於反彈中）。")
    res.pmf["coverage"] = {"continuous": cont["continuous"], "breaks": cont["breaks"], "n_windows": len(samples),
                           "n_added": len(added), "n_manual": len(manual), "k_values": sorted({round(v, 1) for v in ks.values()}),
                           "rounds": len(refine_log), "unsamplable": final_plan.unsamplable if final_plan else []}
    if spect:
        mx = max(hold_wall.values(), default=0.0)
        res.pmf["spectator_hold"] = {"width_nm": cfg.spectator_hold_nm, "ligands": {k: v["d0_nm"] for k, v in spect.items()},
                                     "wall_fraction_max": round(mx, 3), "by_window": {f"{c:.3f}": round(v, 3) for c, v in hold_wall.items()}}
        if mx > 0.1:
            res.caveats.append(f"共同口袋中的其他配體（{', '.join(spect)}）在某些窗口有 {mx * 100:.0f}% 的取樣碰到 ±{cfg.spectator_hold_nm} nm 的保持限制："
                               "它們想離開，這一腿的「另一配體結合」狀態部分由限制維持，協同自由能需保守解讀。")
    elif other_ligand_indices and not cfg.hold_spectators:
        res.caveats.append("其他配體在拉離期間沒有保持限制（binding.hold_spectators = false），可能隨之離開；協同自由能不可解讀。")
    if not cont["continuous"]:
        res.caveats.insert(1, f"CV 取樣仍有斷點 {cont['breaks']} nm（自動補窗 {len(refine_log)} 輪後）；PMF 在斷點處不可信，"
                              "不輸出 ΔG°。可在覆蓋圖上指定該區間補採樣，或提高 k_umbrella_max。")
        res.dG_standard_kj_mol = res.dG_standard_kcal_mol = None
        res.dG_err_kj_mol = None
        res.pmf["dG_withheld"] = "sampling discontinuous"
    # D-43: say WHICH condition failed (students and reviewers could not tell from "not converged")
    reasons = []
    q = res.pmf["quality"]
    if not q.get("graph_connected", True):
        reasons.append("window 重疊圖不連通：有一段距離沒有任何兩個 window 的取樣互相重疊（見傘狀採樣覆蓋圖 umbrella_coverage.png，紅色區段）")
    if not pres.converged:
        xc = q.get("solver_cross_check") or {}
        if xc.get("abs_diff_kj_mol") is not None:
            reasons.append(f"MBAR 求解未達容差，且與 WHAM 的 ΔPMF 相差 {xc['abs_diff_kj_mol']:.1f} kJ/mol（> 2）")
        elif xc.get("mbar_note"):
            reasons.append("MBAR 求解未達容差，WHAM 交叉驗證失敗")
        else:
            reasons.append("WHAM 自洽迭代未收斂")
    elif (q.get("solver_cross_check") or {}).get("abs_diff_kj_mol") is not None:
        res.caveats.append(f"MBAR 求解未達容差，但與 WHAM 的 ΔPMF 一致（差 {q['solver_cross_check']['abs_diff_kj_mol']:.1f} kJ/mol），採用。")
    tr = q.get("pmf_truncated")
    if tr:
        if tr.get("replaced_by"):
            res.caveats.append(f"MBAR 的 PMF 只涵蓋 {tr['finite_nm'][0]:.2f}–{tr['finite_nm'][1]:.2f} nm（window 取樣到 {tr['sampled_nm'][1]:.2f} nm），"
                               f"已改用 {tr['replaced_by']} 以同一批樣本計算全範圍（D-62）。")
        else:
            reasons.append(f"PMF 只涵蓋 {tr['finite_nm']} nm，未涵蓋 window 取樣範圍 {tr['sampled_nm']} nm（MBAR 與 WHAM 皆是）")
    res.pmf["plateau"] = bool(rp.get("plateau", True))          # D-96: explicit, so a missing field means "unknown"
    if not rp.get("plateau", True):
        reasons.append(f"PMF 末端（{rp['r_max']:.2f} nm）仍未持平（尾段變化 {rp['tail_rise_kj_mol']:.1f} kJ/mol > 1 kT）：ΔPMF 是邊緣值不是井深；"
                       "可加長 pull_distance_nm 或檢查盒子大小")
        res.pmf["plateau"] = False
    if reasons:
        res.caveats.insert(1, "ΔG° 不輸出：" + "；".join(reasons) + "。只保留 ΔPMF 作定性參考。")
        res.dG_standard_kj_mol = res.dG_standard_kcal_mol = None
        res.dG_err_kj_mol = None
        res.pmf["dG_withheld"] = "；".join(reasons)
    # D-43: plausibility of the well depth — flag, never change the number
    hint = well_depth_hint(res.delta_pmf_kj_mol, len(ligand))
    if hint:
        res.caveats.insert(1, hint)
        res.pmf["well_depth_flag"] = True
    # D-96: one structured assessment; execution PASS ≠ scientifically qualified
    from .assessment import assess_pmf
    res.assessment = assess_pmf(res.pmf, dG_withheld=res.pmf.get("dG_withheld"), has_dG=res.dG_standard_kj_mol is not None)
    res.condition = binding_condition(cfg, other_ligand_indices, anchor_indices)
    manifest.update({"status": "PASS", "result": res.to_dict()})
    atomic_write_json(json.loads(json.dumps(manifest, default=_np_default)), out / "binding_manifest.json")
    if decisions:
        decisions.record("binding.result", "ΔPMF / ΔG°", f"{res.delta_pmf_kj_mol} / {res.dG_standard_kj_mol} kJ/mol",
                         "；".join(res.caveats[:2]))
    return res


def binding_condition(cfg, other_ligand_indices=None, anchor_indices=None) -> dict:
    """Condition signature of a pull (A8): results whose signatures differ estimate different quantities."""
    return {"cv": "com_distance_radial", "temperature_k": float(cfg.temperature_k),
            "backbone_restraint_kj_mol_nm2": round(float(cfg.backbone_restraint_scale) * 1000.0, 3),
            "spectators": sorted(other_ligand_indices or {}), "hold_spectators": ({"on": bool(cfg.hold_spectators), "width_nm": float(cfg.spectator_hold_nm)}
                                if other_ligand_indices else None),
            "anchor": "user residues" if anchor_indices is not None else "automatic",
            "funnel_restraint": False, "standard_state": "1 M radial integral (no orientational correction)"}


def _np_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def _plot_smd(tsv: Path, out_base: Path) -> dict:
    plt = _mpl()
    a = np.loadtxt(tsv, delimiter="\t")
    # D-45: x = spring position (monotonic in time).  Plotting against the ligand's CV made stick–slip and the
    # ringing after each slip look like the trajectory ran backwards.
    fig, axes = plt.subplots(3, 1, figsize=(7.2, 6.0), sharex=True)
    axes[0].plot(a[:, 1], a[:, 1], color="#9aa4ae", lw=0.8, label="spring position")
    axes[0].plot(a[:, 1], a[:, 2], color=PALETTE[2 % len(PALETTE)], lw=0.9, label="ligand–pocket COM distance")
    axes[0].set_ylabel("Distance (nm)"); axes[0].legend(fontsize=7, frameon=False, loc="upper left")
    axes[1].plot(a[:, 1], a[:, 3], color=PALETTE[0], lw=0.9)
    axes[1].set_ylabel("Pulling force (kJ mol⁻¹ nm⁻¹)")
    axes[2].plot(a[:, 1], a[:, 4], color=PALETTE[1], lw=0.9)
    axes[2].set_ylabel("Work (kJ mol⁻¹)"); axes[2].set_xlabel("Spring position (nm)")
    i = int(np.argmax(a[:, 3]))
    axes[1].text(a[i, 1], a[i, 3], f"  maximum force {a[i, 3]:.0f}", fontsize=7, color="#52514e")
    axes[0].set_title("SMD: distance, force and accumulated work vs. spring position (irreversible, speed-dependent)", loc="left", fontsize=10)
    return _save(fig, out_base)
