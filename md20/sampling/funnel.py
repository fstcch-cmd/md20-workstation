"""Funnel restraint and analytic standard-state correction for the binding step (A8, D-140).

Spec: docs/specs/binding_funnel_restraints.md (Limongelli 2013 PNAS 110:6358; Rizzi 2019 JCAMD 33:1027).

What this module is
  * the geometry of the restraint (pure numpy): axis u from the pocket anchor towards the bound ligand, axial coordinate
    z = (x - c).u, lateral distance rho = |(x - c) - z u|, allowed radius rho_max(z) of a cone (pocket side) that becomes a
    cylinder of radius R_cyl at z_cc;
  * the OpenMM expressions that implement it (`CustomCentroidBondForce`, minimum image written out so that z is a
    signed coordinate, not the |r| of `distance()`), and a pure-python mirror of the energy for tests;
  * the standard-state treatment: dG° = -kT ln( A_eff * Int_site exp(-(W(z)-W_bulk)/kT) dz / V0 );
  * the diagnostics that decide whether that treatment is allowed to stand (bound state not squeezed by the cone,
    ligand solvated in the cylinder, bulk plateau inside the cylinder).

Nothing here changes a threshold of the existing assessment; it only adds the checks the spec asks for.  Missing data is
`unknown`, never `pass`.  OpenMM is imported lazily (the container has none)."""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict

import numpy as np

KB_KJ_MOL_K = 0.00831446261815324
V0_NM3 = 1.66053906660            # standard-state volume per molecule (1 M), nm³

CV_RADIAL = "com_distance_radial"
CV_AXIAL = "axial_projection_z"
STANDARD_STATE_RADIAL = "1 M radial integral (no orientational correction)"
STANDARD_STATE_FUNNEL = "funnel_cylinder_analytic"
SCHEMA = "md20.funnel/1"

# spec §3.1 / §3.3 (values pending reviewer feedback, see the spec's section 5)
DEFAULTS = {"r_cyl_nm": 0.2, "r_cone_nm": 1.0, "k_kj_mol_nm2": 4000.0, "z_min_nm": -0.2}
Z_CC_MARGIN_NM = 0.3               # z_cc = pocket exit + ligand radius + 0.3 nm
EXIT_TUBE_NM = 0.5                 # protein atoms within this lateral distance of the axis define the pocket exit
EXIT_GAP_NM = 0.35                 # first axial gap this wide in the protein atoms ahead of the ligand = pocket exit
BOUND_MARGIN_NM = 0.05             # spec §3.3: 99 % of bound-state samples at least this far inside the funnel wall
BOUND_QUANTILE = 0.99
SOLVATION_OFFSET_NM = 0.5          # spec §3.3: check ligand-protein distance where z >= z_cc + 0.5 nm
SOLVATED_MIN_NM = 0.6              # ... shortest ligand heavy atom - protein heavy atom distance must exceed this
BULK_STRETCH_NM = 0.3              # the bulk plateau needs at least this much z beyond the solvation check (pull sizing)


# --------------------------------------------------------------------------------------------- small pure helpers
def _min_image_many(d: np.ndarray, box: np.ndarray) -> np.ndarray:
    """Minimum-image of (..., 3) displacements for a reduced-form box (rows = box vectors, nm)."""
    d = np.array(d, dtype=float, copy=True)
    for k in (2, 1, 0):
        n = np.round(d[..., k] / box[k][k])
        d -= n[..., None] * np.asarray(box[k], float)
    return d


def _com(xyz: np.ndarray, idx, masses: np.ndarray) -> np.ndarray:
    idx = np.asarray(idx, dtype=int)
    m = masses[idx]
    return (xyz[idx] * m[:, None]).sum(0) / m.sum()


# --------------------------------------------------------------------------------------------- geometry
@dataclass
class FunnelGeometry:
    """The restraint.  Lengths nm, k kJ/mol/nm².  `axis` is a lab-frame unit vector (the protein orientation is held by
    the backbone position restraints of the pulling system); the origin is the live anchor centroid."""
    axis: tuple
    r_cyl_nm: float
    r_cone_nm: float
    z_cc_nm: float
    k_kj_mol_nm2: float
    z_min_nm: float
    z0_nm: float                       # bound-state axial coordinate of the ligand at set-up
    box: tuple                         # 3x3 reduced-form box vectors used by the force expression (nm)

    def rho_max(self, z):
        """Allowed lateral radius: R_cyl + (R_cone - R_cyl) * clip((z_cc - z)/z_cc, 0, 1) (the clip at 1 keeps R_cone the
        widest part below z = 0; spec §3.1 has no upper clip, see the deviation list)."""
        z = np.asarray(z, float)
        frac = np.clip((self.z_cc_nm - z) / self.z_cc_nm, 0.0, 1.0)
        return self.r_cyl_nm + (self.r_cone_nm - self.r_cyl_nm) * frac

    def decompose(self, vec) -> tuple:
        """(z, rho) of displacement(s) `vec` = minimum-image(ligand COM - anchor COM), shape (..., 3)."""
        v = np.asarray(vec, float)
        u = np.asarray(self.axis, float)
        z = v @ u
        perp = v - z[..., None] * u if np.ndim(z) else v - z * u
        return z, np.linalg.norm(perp, axis=-1)

    def decompose_xyz(self, xyz, box, anchor, ligand, masses) -> tuple:
        d = _min_image_many(_com(xyz, ligand, masses) - _com(xyz, anchor, masses), np.asarray(box, float))
        z, rho = self.decompose(d)
        return float(z), float(rho)

    def lateral_energy(self, z, rho):
        ex = np.maximum(0.0, np.asarray(rho, float) - self.rho_max(z))
        return 0.5 * self.k_kj_mol_nm2 * ex ** 2

    def wall_energy(self, z):
        ew = np.maximum(0.0, self.z_min_nm - np.asarray(z, float))
        return 0.5 * self.k_kj_mol_nm2 * ew ** 2

    def energy(self, z, rho):
        """Funnel restraint energy (kJ/mol): flat inside, harmonic outside the wall, plus the lower z wall."""
        return self.lateral_energy(z, rho) + self.wall_energy(z)

    def to_dict(self) -> dict:
        return asdict(self)


def estimate_geometry(xyz: np.ndarray, box: np.ndarray, anchor, ligand, masses: np.ndarray, protein_idx, *,
                      r_cyl_nm: float = DEFAULTS["r_cyl_nm"], r_cone_nm: float = DEFAULTS["r_cone_nm"],
                      z_cc_nm: float | None = None, k_kj_mol_nm2: float = DEFAULTS["k_kj_mol_nm2"],
                      z_min_nm: float = DEFAULTS["z_min_nm"], ligand_heavy=None) -> tuple:
    """Funnel from the bound-state coordinates (pure).  Returns (FunnelGeometry, info).

    axis    : unit vector anchor centroid -> ligand centroid (the SMD direction; no new choice).
    z_cc    : given, or automatic = pocket exit + ligand radius + 0.3 nm.  The pocket exit is the first axial gap of
              >= EXIT_GAP_NM in the protein heavy atoms inside a tube of EXIT_TUBE_NM around the axis, ahead of the
              ligand centroid (a heuristic; the user can override with `funnel_z_cc_nm`).  The ligand radius is added
              so that the spec's own solvation check (ligand-protein distance > 0.6 nm at z_cc + 0.5 nm) is reachable.
    Raises ValueError when the ligand centroid coincides with the anchor centroid (no axis)."""
    box = np.asarray(box, float)
    c = _com(xyz, anchor, masses)
    lc = _com(xyz, ligand, masses)
    d = _min_image_many(lc - c, box)
    z0 = float(np.linalg.norm(d))
    if z0 < 1e-3:
        raise ValueError("配體質心與口袋 anchor 質心重合，無法定義漏斗軸")
    u = d / z0
    prot = np.asarray(protein_idx, dtype=int)
    z_exit, n_tube = z0, 0
    if len(prot):
        rel = _min_image_many(xyz[prot] - c, box)
        zp = rel @ u
        rhop = np.linalg.norm(rel - zp[:, None] * u, axis=1)
        zt = np.sort(zp[(rhop <= EXIT_TUBE_NM) & (zp >= z0)])
        n_tube = int(len(zt))
        if n_tube:
            gaps = np.nonzero(np.diff(zt) >= EXIT_GAP_NM)[0]
            z_exit = float(zt[gaps[0]] if len(gaps) else zt[-1])
    lig = np.asarray(ligand_heavy if ligand_heavy is not None else ligand, dtype=int)
    r_lig = float(np.max(np.linalg.norm(xyz[lig] - xyz[lig].mean(0), axis=1))) if len(lig) > 1 else 0.0
    auto = z_cc_nm is None
    z_cc = float(max(z_exit + r_lig + Z_CC_MARGIN_NM, z0 + 0.3)) if auto else float(z_cc_nm)
    geom = FunnelGeometry(axis=tuple(float(x) for x in u), r_cyl_nm=float(r_cyl_nm), r_cone_nm=float(r_cone_nm), z_cc_nm=z_cc,
                          k_kj_mol_nm2=float(k_kj_mol_nm2), z_min_nm=float(z_min_nm), z0_nm=z0,
                          box=tuple(tuple(float(x) for x in row) for row in box))
    info = {"schema": SCHEMA, "axis": list(geom.axis), "origin_nm": [float(x) for x in c], "z0_nm": z0,
            "z_exit_nm": z_exit, "pocket_depth_nm": z_exit - z0, "ligand_radius_nm": r_lig, "z_cc_nm": z_cc,
            "z_cc_source": "auto" if auto else "user", "n_protein_atoms_in_exit_tube": n_tube,
            "exit_tube_nm": EXIT_TUBE_NM, "exit_gap_nm": EXIT_GAP_NM, "r_cyl_nm": geom.r_cyl_nm, "r_cone_nm": geom.r_cone_nm,
            "k_kj_mol_nm2": geom.k_kj_mol_nm2, "z_min_nm": geom.z_min_nm,
            "pull_needed_nm": pull_needed_nm(geom)}
    return geom, info


def pull_needed_nm(geom: FunnelGeometry) -> float:
    """Smallest pull distance (beyond the bound z0) that still puts a solvation-check stretch and a bulk plateau in the
    cylinder: z_cc + 0.5 nm (spec §3.3) + BULK_STRETCH_NM, minus z0."""
    return float(geom.z_cc_nm + SOLVATION_OFFSET_NM + BULK_STRETCH_NM - geom.z0_nm)


# --------------------------------------------------------------------------------------------- OpenMM expressions
def _f(x: float) -> str:
    return f"({float(x)!r})"


def axial_definitions(box, axis) -> list:
    """Intermediate definitions (name, expression) in dependency order for the signed axial coordinate zc and the squared
    lateral distance rho2 between the centroids of group 1 (anchor) and group 2 (ligand).  The minimum image is written
    out with floor() because distance() is |r| and loses the sign.  Valid for OpenMM's reduced-form box."""
    box = np.asarray(box, float)
    ax, bx, by = box[0][0], box[1][0], box[1][1]
    cx, cy, cz = box[2][0], box[2][1], box[2][2]
    ux, uy, uz = (float(a) for a in axis)
    return [
        ("dx0", "x2-x1"), ("dy0", "y2-y1"), ("dz0", "z2-z1"),
        ("n2", f"floor(dz0/{_f(cz)}+0.5)"),
        ("dx1", f"dx0-n2*{_f(cx)}"), ("dy1", f"dy0-n2*{_f(cy)}"), ("dz1", f"dz0-n2*{_f(cz)}"),
        ("n1", f"floor(dy1/{_f(by)}+0.5)"),
        ("dx2", f"dx1-n1*{_f(bx)}"), ("dy2", f"dy1-n1*{_f(by)}"),
        ("n0", f"floor(dx2/{_f(ax)}+0.5)"),
        ("dx3", f"dx2-n0*{_f(ax)}"),
        ("zc", f"dx3*{_f(ux)}+dy2*{_f(uy)}+dz1*{_f(uz)}"),
        ("rho2", f"(dy2*{_f(uz)}-dz1*{_f(uy)})^2+(dz1*{_f(ux)}-dx3*{_f(uz)})^2+(dx3*{_f(uy)}-dy2*{_f(ux)})^2"),
    ]


def compose_expression(main: str, defs: list) -> str:
    """Lepton lets a definition use the names defined to its right, so the dependency order is written reversed."""
    return main + "".join(f"; {n}={e}" for n, e in reversed(defs))


def cv_expression(box, axis) -> str:
    """Umbrella / SMD spring on the axial coordinate (global parameters k_cv, r0_cv: same names as the radial bias)."""
    return compose_expression("0.5*k_cv*(zc-r0_cv)^2", axial_definitions(box, axis))


def funnel_expression(box, axis) -> str:
    """Flat-bottom funnel: lateral wall around rho_max(zc) and the lower z wall (global fn_* parameters)."""
    defs = axial_definitions(box, axis) + [
        ("rho", "sqrt(rho2+1e-18)"),
        ("rmax", "fn_rcyl+(fn_rcone-fn_rcyl)*min(1,max(0,(fn_zcc-zc)/fn_zcc))"),
        ("ex", "rho-rmax"), ("ew", "fn_zmin-zc")]
    return compose_expression("0.5*fn_k*(step(ex)*ex)^2+0.5*fn_k*(step(ew)*ew)^2", defs)


def funnel_parameters(geom: FunnelGeometry) -> dict:
    return {"fn_k": geom.k_kj_mol_nm2, "fn_rcyl": geom.r_cyl_nm, "fn_rcone": geom.r_cone_nm, "fn_zcc": geom.z_cc_nm,
            "fn_zmin": geom.z_min_nm}


FUNNEL_FORCE_GROUP = 31            # lets a test (or a diagnostic) read the funnel energy alone


def add_funnel_forces(system, geom: FunnelGeometry, anchor, ligand):
    """Replace nothing: adds the lateral/wall restraint (`md20_funnel`) to `system`.  The CV spring is added by
    `binding.build_pulling_system` (it needs the same expressions).  Returns the force."""
    import openmm as mm
    f = mm.CustomCentroidBondForce(2, funnel_expression(geom.box, geom.axis))
    for k, v in funnel_parameters(geom).items():
        f.addGlobalParameter(k, float(v))
    f.addGroup([int(i) for i in anchor])
    f.addGroup([int(i) for i in ligand])
    f.addBond([0, 1], [])
    f.setUsesPeriodicBoundaryConditions(True)
    f.setName("md20_funnel")
    f.setForceGroup(FUNNEL_FORCE_GROUP)
    system.addForce(f)
    return f


def add_axial_cv_bias(system, geom: FunnelGeometry, anchor, ligand):
    """The CV spring on the axial coordinate; same force name and global parameters as the radial bias."""
    import openmm as mm
    bias = mm.CustomCentroidBondForce(2, cv_expression(geom.box, geom.axis))
    bias.addGlobalParameter("k_cv", 0.0)
    bias.addGlobalParameter("r0_cv", 0.0)
    bias.addGroup([int(i) for i in anchor])
    bias.addGroup([int(i) for i in ligand])
    bias.addBond([0, 1], [])
    bias.setUsesPeriodicBoundaryConditions(True)
    bias.setName("md20_cv_bias")
    system.addForce(bias)
    return bias


# --------------------------------------------------------------------------------------------- standard state
def _trapz(y, x) -> float:
    return float(np.trapezoid(y, x)) if hasattr(np, "trapezoid") else float(np.trapz(y, x))


def lateral_area_nm2(r_cyl_nm: float, k_kj_mol_nm2: float, kT: float, *, n: int = 20001) -> float:
    """A_eff = Int exp(-U_lat(rho)/kT) 2 pi rho drho over the bulk cylinder (rho_max = R_cyl), numerically.
    Hard wall (k -> inf) gives pi R²; the harmonic skirt adds the part of the ligand's lateral excursion outside R."""
    if not np.isfinite(k_kj_mol_nm2) or k_kj_mol_nm2 <= 0:
        raise ValueError("k must be positive")
    width = math.sqrt(2.0 * kT / k_kj_mol_nm2)             # Boltzmann factor at the wall decays on this scale
    rho_hi = r_cyl_nm + 12.0 * width                       # exp(-72) beyond: below double-precision relevance
    rho = np.linspace(0.0, rho_hi, int(n))
    ex = np.maximum(0.0, rho - r_cyl_nm)
    return _trapz(np.exp(-0.5 * k_kj_mol_nm2 * ex ** 2 / kT) * 2.0 * np.pi * rho, rho)


def lateral_area_analytic_nm2(r_cyl_nm: float, k_kj_mol_nm2: float, kT: float) -> float:
    """Closed form of the same integral: pi R² + 2 pi [ R sqrt(pi/(4a)) + 1/(2a) ], a = k/(2 kT)  (cross-check)."""
    a = k_kj_mol_nm2 / (2.0 * kT)
    return math.pi * r_cyl_nm ** 2 + 2.0 * math.pi * (r_cyl_nm * 0.5 * math.sqrt(math.pi / a) + 1.0 / (2.0 * a))


def standard_state_dg(grid, W, *, kT: float, a_eff_nm2: float, site: tuple, w_bulk: float, v0_nm3: float = V0_NM3) -> dict:
    """dG° = -kT ln( A_eff * Int_site exp(-(W(z)-W_bulk)/kT) dz / V0 ).
    W kJ/mol on `grid` nm (no Jacobian: z is a straight-line coordinate); `site` = (z_lo, z_hi) nm.  K_b in nm³."""
    g, w = np.asarray(grid, float), np.asarray(W, float)
    m = np.isfinite(w) & (g >= site[0] - 1e-12) & (g <= site[1] + 1e-12)
    if m.sum() < 2:
        return {"dG": None, "k_b_nm3": None, "site_nm": [float(site[0]), float(site[1])], "n_bins": int(m.sum())}
    integral = _trapz(np.exp(-(w[m] - w_bulk) / kT), g[m])               # nm
    k_b = a_eff_nm2 * integral                                            # nm³
    dg = -kT * math.log(k_b / v0_nm3) if k_b > 0 else None
    return {"dG": (round(dg, 3) if dg is not None else None), "k_b_nm3": k_b, "integral_nm": integral,
            "site_nm": [float(g[m][0]), float(g[m][-1])], "n_bins": int(m.sum())}


def axial_pmf(pres, temperature_k: float, funnel: dict) -> dict:
    """Axial-coordinate PMF summary, same keys as `binding.radial_pmf` where they mean the same thing.

    No Jacobian (z is a straight line).  W_bulk = mean of the tail inside the sampled range; the plateau check is the
    D-65 one (rise across the tail from a straight-line fit <= 1 kT).  The site is [first bin, first z after the minimum
    where W is back to W_bulk - 0.5 kT] (same rule as the radial integral).  `funnel` = {"r_cyl_nm", "k_kj_mol_nm2",
    "z_cc_nm"}."""
    grid, W = np.asarray(pres.grid_nm, float), np.asarray(pres.pmf_kj_mol, float)
    kT = KB_KJ_MOL_K * temperature_k
    ok = np.isfinite(W)
    g, W_raw = grid[ok], W[ok]
    Wv = W_raw - np.min(W_raw)
    err = np.asarray(pres.err_kj_mol)[ok] if pres.err_kj_mol is not None else None
    tail = max(3, len(Wv) // 10)
    hi = (getattr(pres, "quality", None) or {}).get("sampled_nm", [None, None])[1]
    inner = g <= hi + 1e-9 if hi is not None else np.ones_like(g, dtype=bool)
    gi, wi = (g[inner], Wv[inner]) if inner.sum() >= tail else (g, Wv)
    gt, wt = gi[-tail:], wi[-tail:]
    w_bulk = float(np.mean(wt))
    slope = float(np.polyfit(gt, wt, 1)[0]) if len(gt) >= 3 and np.ptp(gt) > 0 else 0.0
    tail_rise = float(slope * (gt[-1] - gt[0])) if len(gt) >= 2 else 0.0
    i_min = int(np.argmin(Wv))
    dpmf = round(w_bulk - float(Wv[i_min]), 3)
    beyond = np.where(Wv[i_min:] >= w_bulk - 0.5 * kT)[0]
    z_cut = float(g[i_min + beyond[0]] if len(beyond) else g[-1])
    a_eff = lateral_area_nm2(funnel["r_cyl_nm"], funnel["k_kj_mol_nm2"], kT)
    ss = standard_state_dg(g, Wv, kT=kT, a_eff_nm2=a_eff, site=(float(g[0]), z_cut), w_bulk=w_bulk)
    # how much the site boundary matters: the same integral with the boundary moved 0.1 nm outwards
    ss2 = standard_state_dg(g, Wv, kT=kT, a_eff_nm2=a_eff, site=(float(g[0]), min(float(g[-1]), z_cut + 0.1)), w_bulk=w_bulk)
    sens = (round(abs(ss2["dG"] - ss["dG"]), 3) if ss.get("dG") is not None and ss2.get("dG") is not None else None)
    from .multi import delta_pmf_error
    return {"grid": g, "W": Wv, "W_raw": Wv, "err": err, "w_bulk": w_bulk, "r_min": float(g[i_min]), "r_cut": z_cut,
            "delta_pmf": dpmf, "delta_pmf_err": delta_pmf_error(g, err, i_min, tail), "dG": ss.get("dG"),
            "tail_rise_kj_mol": round(tail_rise, 3), "plateau": bool(abs(tail_rise) <= kT), "r_max": float(gt[-1]),
            "a_eff_nm2": a_eff, "k_b_nm3": ss.get("k_b_nm3"), "site_nm": ss.get("site_nm"),
            "bulk_z_nm": [float(gt[0]), float(gt[-1])], "site_edge_sensitivity_kj_mol": sens,
            "in_cylinder": bool(gt[0] >= float(funnel["z_cc_nm"]))}


# --------------------------------------------------------------------------------------------- diagnostics from samples
def sample_checks(geom: FunnelGeometry, per_window: dict, *, z_well_nm: float | None, bulk_in_cylinder: bool | None) -> dict:
    """The three checks of spec §3.3 from per-window samples.

    per_window: {centre: {"z": array, "rho": array | None, "dmin": array | None}}; dmin is NaN where it was not
    computed.  Each check is {"status": pass | fail | unknown, ...}; absent data is unknown."""
    centres = sorted(per_window)
    # --- bound state: windows up to the PMF well (+0.1 nm), and always the first one
    bound = [c for c in centres if (z_well_nm is not None and c <= z_well_nm + 0.1)] or centres[:1]
    margins = []
    for c in bound:
        rho = per_window[c].get("rho")
        if rho is None or not len(rho):
            continue
        z = np.asarray(per_window[c]["z"], float)
        margins.append(np.asarray(rho, float) - geom.rho_max(z))
    if margins:
        q = float(np.quantile(np.concatenate(margins), BOUND_QUANTILE))
        bs = {"status": "pass" if q < -BOUND_MARGIN_NM else "fail", "q99_margin_nm": round(q, 4), "required_below_nm": -BOUND_MARGIN_NM,
              "windows": [round(float(c), 4) for c in bound],
              "n_samples": int(sum(len(m) for m in margins))}
    else:
        bs = {"status": "unknown", "q99_margin_nm": None, "required_below_nm": -BOUND_MARGIN_NM, "windows": [], "n_samples": 0}
    # --- ligand solvated in the cylinder
    z_chk = geom.z_cc_nm + SOLVATION_OFFSET_NM
    vals = []
    for c in centres:
        dm, z = per_window[c].get("dmin"), per_window[c].get("z")
        if dm is None or z is None:
            continue
        dm, z = np.asarray(dm, float), np.asarray(z, float)
        sel = (z >= z_chk) & np.isfinite(dm)
        if sel.any():
            vals.append(dm[sel])
    if vals:
        v = np.concatenate(vals)
        q = float(np.quantile(v, 1.0 - BOUND_QUANTILE))
        sv = {"status": "pass" if q > SOLVATED_MIN_NM else "fail", "q01_dmin_nm": round(q, 4), "required_above_nm": SOLVATED_MIN_NM,
              "z_from_nm": round(z_chk, 4), "n_samples": int(len(v))}
    else:
        sv = {"status": "unknown", "q01_dmin_nm": None, "required_above_nm": SOLVATED_MIN_NM, "z_from_nm": round(z_chk, 4), "n_samples": 0}
    bc = {"status": "unknown" if bulk_in_cylinder is None else ("pass" if bulk_in_cylinder else "fail"), "z_cc_nm": geom.z_cc_nm}
    return {"bound_state": bs, "solvation": sv, "bulk_in_cylinder": bc}


def funnel_withheld_reason(checks: dict) -> str | None:
    """Why dG° cannot stand with the funnel treatment (None = every check passes).  Zh, as the DecisionLog."""
    bad = []
    bs, sv, bc = checks["bound_state"], checks["solvation"], checks["bulk_in_cylinder"]
    if bs["status"] != "pass":
        bad.append("結合態被漏斗壓住（圓錐太窄）" if bs["status"] == "fail" else "沒有結合態 ρ 紀錄")
    if sv["status"] != "pass":
        bad.append(f"圓柱段配體尚未完全溶劑化（z ≥ {sv['z_from_nm']:.2f} nm 處重原子到蛋白最短距離的 1% 分位 "
                   f"{sv['q01_dmin_nm']} nm，需 > {SOLVATED_MIN_NM} nm）" if sv["status"] == "fail" else "圓柱段沒有配體–蛋白距離紀錄")
    if bc["status"] != "pass":
        bad.append("PMF 末端平台不在圓柱段內" if bc["status"] == "fail" else "沒有平台位置紀錄")
    return "漏斗標準態檢查未通過：" + "；".join(bad) if bad else None
