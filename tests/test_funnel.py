"""D-140 (A8): funnel restraint geometry, standard-state correction, axial PMF, claim gating and four-language text.
Pure Python (the container has no OpenMM); the OpenMM path is in tests/test_binding_integration.py::test_nacl_funnel."""
import inspect
import json
import math

import numpy as np
import pytest

from md20.sampling import funnel as FN
from md20.sampling.assessment import (CLAIM_SCHEMA, THRESHOLDS_VERSION, assess_pmf, claim_eligible, claim_status,
                                      ranking_basis)
from md20.sampling.binding import BindingConfig, V0_NM3, binding_condition, finished_result, run_binding, radial_pmf
from md20.sampling.multi import compare_binding, context_basis

KB = FN.KB_KJ_MOL_K
KT = KB * 300.0


def _geom(**kw):
    d = dict(axis=(1.0, 0.0, 0.0), r_cyl_nm=0.2, r_cone_nm=1.0, z_cc_nm=1.5, k_kj_mol_nm2=4000.0, z_min_nm=-0.2, z0_nm=0.5,
             box=((6.0, 0, 0), (0, 6.0, 0), (0, 0, 6.0)))
    d.update(kw)
    return FN.FunnelGeometry(**d)


# ------------------------------------------------------------------------------------------------ geometry
def test_decompose_z_and_rho_general_axis():
    u = np.array([1.0, 2.0, 2.0]) / 3.0
    g = _geom(axis=tuple(u))
    perp = np.cross(u, [0.0, 0.0, 1.0]); perp /= np.linalg.norm(perp)
    z, rho = g.decompose(1.2 * u + 0.35 * perp)
    assert z == pytest.approx(1.2) and rho == pytest.approx(0.35)
    z, rho = g.decompose(np.array([-0.4 * u, 0.0 * u + 0.1 * perp]))      # vectorised, signed z
    assert z == pytest.approx([-0.4, 0.0]) and rho == pytest.approx([0.0, 0.1])


def test_decompose_xyz_uses_minimum_image_and_com():
    box = np.array([[3.0, 0, 0], [0, 3.0, 0], [0, 0, 3.0]])
    xyz = np.zeros((4, 3)); masses = np.ones(4)
    xyz[0] = [2.9, 1.5, 1.5]; xyz[1] = [2.9, 1.5, 1.5]           # anchor (two atoms)
    xyz[2] = [0.4, 1.9, 1.5]; xyz[3] = [0.4, 1.9, 1.5]           # ligand just across the +x boundary
    g = _geom(box=tuple(map(tuple, box)))
    z, rho = g.decompose_xyz(xyz, box, [0, 1], [2, 3], masses)
    assert z == pytest.approx(0.5) and rho == pytest.approx(0.4)


def test_rho_max_cone_then_cylinder():
    g = _geom()
    assert g.rho_max(0.0) == pytest.approx(1.0)                  # R_cone at the anchor plane
    assert g.rho_max(1.5) == pytest.approx(0.2)                  # R_cyl from z_cc on
    assert g.rho_max(3.0) == pytest.approx(0.2)
    assert g.rho_max(0.75) == pytest.approx(0.6)                 # linear in between
    assert g.rho_max(-0.2) == pytest.approx(1.0)                 # clipped: R_cone stays the widest
    assert np.allclose(g.rho_max(np.array([0.0, 1.5])), [1.0, 0.2])


def test_energy_flat_inside_quadratic_outside_and_z_wall():
    g = _geom()
    assert g.energy(0.5, 0.0) == 0.0 and g.energy(2.0, 0.19) == 0.0 and g.energy(0.75, 0.6) == 0.0   # on the wall: 0
    assert g.energy(2.0, 0.3) == pytest.approx(0.5 * 4000.0 * 0.1 ** 2)
    assert g.energy(0.75, 0.7) == pytest.approx(0.5 * 4000.0 * 0.1 ** 2)
    assert g.energy(-0.3, 0.0) == pytest.approx(0.5 * 4000.0 * 0.1 ** 2)                  # below z_min = -0.2
    assert g.energy(-0.1, 0.0) == 0.0


# ------------------------------------------------------------------------------------------------ the OpenMM expressions
def _lepton(expr: str, variables: dict) -> float:
    """Tiny evaluator for the subset of Lepton the funnel expressions use: main expression + `; name=expr` definitions
    (a definition may use names defined to its right, so names are resolved lazily)."""
    parts = [p.strip() for p in expr.split(";")]
    defs = dict(p.split("=", 1) for p in parts[1:])
    ns = {"floor": math.floor, "sqrt": math.sqrt, "min": min, "max": max, "abs": abs,
          "step": lambda x: 0.0 if x < 0 else 1.0}

    class Env(dict):
        def __missing__(self, k):
            if k in variables:
                return variables[k]
            if k in defs:
                self[k] = eval(defs[k].replace("^", "**"), ns, self)
                return self[k]
            raise KeyError(k)
    return float(eval(parts[0].replace("^", "**"), ns, Env()))


def _vars(g, anchor, lig, **extra):
    v = {"x1": anchor[0], "y1": anchor[1], "z1": anchor[2], "x2": lig[0], "y2": lig[1], "z2": lig[2],
         **{k: float(x) for k, x in FN.funnel_parameters(g).items()}}
    v.update(extra)
    return v


@pytest.mark.parametrize("box", [((4.0, 0, 0), (0, 4.0, 0), (0, 0, 4.0)),
                                 ((4.0, 0, 0), (1.3, 3.8, 0), (-1.1, 1.2, 3.5))])           # cubic and triclinic (reduced form)
def test_expression_matches_python_energy_incl_periodic_images(box):
    u = np.array([0.3, -0.5, 0.8]); u /= np.linalg.norm(u)
    g = _geom(axis=tuple(u), box=box, z_cc_nm=1.1)
    B = np.array(box)
    rng = np.random.default_rng(3)
    cv = FN.cv_expression(box, u)
    fe = FN.funnel_expression(box, u)
    for _ in range(60):
        anchor = rng.uniform(0, 1, 3)
        d = rng.uniform(-0.4, 1.2) * u + rng.normal(0, 0.2, 3)          # a displacement well inside half a box
        for img in ([0, 0, 0], [1, 0, 0], [0, -1, 1], [2, 1, -1]):     # the ligand centroid may sit in any periodic image
            lig = anchor + d + np.array(img) @ B
            z, rho = g.decompose(d)
            v = _vars(g, anchor, lig, k_cv=1000.0, r0_cv=0.7)
            assert _lepton(cv, v) == pytest.approx(0.5 * 1000.0 * (z - 0.7) ** 2, rel=1e-9, abs=1e-9)
            assert _lepton(fe, v) == pytest.approx(float(g.energy(z, rho)), rel=1e-7, abs=1e-8)


def test_expression_structure_and_parameters():
    g = _geom()
    e = FN.funnel_expression(g.box, g.axis)
    assert e.startswith("0.5*fn_k*") and "floor(" in e and "sqrt(rho2+1e-18)" in e
    assert set(FN.funnel_parameters(g)) == {"fn_k", "fn_rcyl", "fn_rcone", "fn_zcc", "fn_zmin"}
    assert FN.cv_expression(g.box, g.axis).startswith("0.5*k_cv*(zc-r0_cv)^2")
    # definitions are written right-to-left of their dependencies (Lepton resolves names defined to the right)
    names = [p.split("=")[0].strip() for p in FN.cv_expression(g.box, g.axis).split(";")[1:]]
    assert names.index("rho2") < names.index("dx0") and names.index("zc") < names.index("dx3")


# ------------------------------------------------------------------------------------------------ standard state
def test_lateral_area_hard_wall_limit_and_closed_form():
    assert FN.lateral_area_nm2(0.2, 1e9, KT) == pytest.approx(math.pi * 0.2 ** 2, rel=2e-3)
    for k in (500.0, 4000.0, 40000.0):
        assert FN.lateral_area_nm2(0.2, k, KT) == pytest.approx(FN.lateral_area_analytic_nm2(0.2, k, KT), rel=1e-4)
    assert FN.lateral_area_nm2(0.2, 4000.0, KT) > math.pi * 0.2 ** 2         # the skirt only adds volume
    with pytest.raises(ValueError):
        FN.lateral_area_nm2(0.2, 0.0, KT)


def test_standard_state_analytic_case_flat_w_hard_cylinder():
    """Flat W, hard cylinder: dG° = -kT ln(pi R² L / V0)."""
    R, L = 0.2, 1.3
    z = np.linspace(0.3, 0.3 + L, 261)
    out = FN.standard_state_dg(z, np.zeros_like(z), kT=KT, a_eff_nm2=math.pi * R ** 2, site=(z[0], z[-1]), w_bulk=0.0)
    assert out["dG"] == pytest.approx(-KT * math.log(math.pi * R ** 2 * L / V0_NM3), abs=1e-3)
    assert out["k_b_nm3"] == pytest.approx(math.pi * R ** 2 * L)
    # the numerically integrated A_eff with a very stiff wall reaches the same number
    a = FN.lateral_area_nm2(R, 1e9, KT)
    out2 = FN.standard_state_dg(z, np.zeros_like(z), kT=KT, a_eff_nm2=a, site=(z[0], z[-1]), w_bulk=0.0)
    assert out2["dG"] == pytest.approx(out["dG"], abs=5e-3)


def test_standard_state_boltzmann_weight_of_a_square_well():
    z = np.linspace(0.0, 3.0, 601)
    W = np.where(z < 1.0, -15.0, 0.0)                                    # 15 kJ/mol deep, 1 nm wide (grid-edge value at z=1)
    out = FN.standard_state_dg(z, W, kT=KT, a_eff_nm2=0.17, site=(0.0, 1.5), w_bulk=0.0)
    expect = -KT * math.log(0.17 * (1.0 * math.exp(15.0 / KT) + 0.5) / V0_NM3)
    assert out["dG"] == pytest.approx(expect, abs=0.05)
    assert FN.standard_state_dg(z, W, kT=KT, a_eff_nm2=0.17, site=(2.995, 3.0), w_bulk=0.0)["n_bins"] == 2


class _Pres:
    def __init__(self, grid, pmf, sampled_hi=None):
        self.grid_nm, self.pmf_kj_mol, self.err_kj_mol = np.asarray(grid, float), np.asarray(pmf, float), None
        self.quality = {"sampled_nm": [float(grid[0]), float(sampled_hi if sampled_hi is not None else grid[-1])]}


FPAR = {"r_cyl_nm": 0.2, "k_kj_mol_nm2": 4000.0, "z_cc_nm": 1.5}


def _well(z_hi=3.4, depth=25.0, slope=0.0):
    z = np.linspace(0.4, z_hi, 301)
    W = -depth * np.exp(-((z - 0.6) / 0.25) ** 2) + slope * z
    return z, W - W.min()


def test_axial_pmf_has_no_jacobian_and_matches_the_formula():
    z, W = _well()
    r = FN.axial_pmf(_Pres(z, W), 300.0, FPAR)
    assert r["delta_pmf"] == pytest.approx(25.0, abs=0.1)
    assert np.allclose(r["W"], W - W.min())                               # no +2kT ln r (the radial summary would add it)
    rad = radial_pmf(_Pres(z, W), 300.0)
    assert not np.allclose(rad["W"], r["W"], atol=1e-6)
    a = FN.lateral_area_nm2(0.2, 4000.0, KT)
    ss = FN.standard_state_dg(z, r["W"], kT=KT, a_eff_nm2=a, site=tuple(r["site_nm"]), w_bulk=r["w_bulk"])
    assert r["dG"] == pytest.approx(ss["dG"]) and r["dG"] < 0
    assert r["a_eff_nm2"] == pytest.approx(a) and r["plateau"] and r["in_cylinder"]
    assert r["site_nm"][0] == pytest.approx(z[0]) and 0.6 < r["site_nm"][1] < 1.6
    assert r["site_edge_sensitivity_kj_mol"] is not None and r["site_edge_sensitivity_kj_mol"] < 1.0


def test_axial_pmf_bulk_plateau_and_cylinder_checks():
    z, W = _well(slope=15.0)                                              # tail still climbing 15 kJ/mol per nm
    r = FN.axial_pmf(_Pres(z, W), 300.0, FPAR)
    assert r["plateau"] is False and r["tail_rise_kj_mol"] > KT
    z, W = _well(z_hi=1.4)                                                # PMF ends before the cylinder starts (z_cc = 1.5)
    assert FN.axial_pmf(_Pres(z, W), 300.0, FPAR)["in_cylinder"] is False
    assert FN.axial_pmf(_Pres(z, W), 300.0, {**FPAR, "z_cc_nm": 1.0})["in_cylinder"] is True


# ------------------------------------------------------------------------------------------------ automatic geometry
def _pocket():
    """Protein slab along x with a 'pocket' ligand at x = 0.5 and an open exit at x ~ 1.4; anchor atoms behind the ligand."""
    box = np.diag([8.0, 8.0, 8.0])
    anchor = np.array([[0.0, 0.1, 0.0], [0.0, -0.1, 0.0], [0.0, 0.0, 0.1], [0.0, 0.0, -0.1]])
    walls = np.array([[x, y, z] for x in np.arange(0.2, 1.45, 0.15) for y in (-0.4, 0.4) for z in (-0.3, 0.3)])
    far = np.array([[3.5, 0.0, 0.0]])                                     # another part of the protein, after a gap
    lig = np.array([[0.5, 0.0, 0.0], [0.62, 0.0, 0.0], [0.5, 0.12, 0.0]])
    xyz = np.vstack([anchor, walls, far, lig])
    idx = lambda a, n: np.arange(a, a + n)                               # noqa: E731
    a_i, w_i, f_i = idx(0, 4), idx(4, len(walls)), idx(4 + len(walls), 1)
    l_i = idx(5 + len(walls), 3)
    return xyz, box, a_i, np.concatenate([a_i, w_i, f_i]), l_i


def test_estimate_geometry_axis_exit_and_auto_z_cc():
    xyz, box, anchor, prot, lig = _pocket()
    masses = np.ones(len(xyz))
    g, info = FN.estimate_geometry(xyz, box, anchor, lig, masses, prot)
    com_l = xyz[lig].mean(0)
    assert np.allclose(g.axis, com_l / np.linalg.norm(com_l), atol=1e-6) and abs(np.linalg.norm(g.axis) - 1) < 1e-9
    assert g.z0_nm == pytest.approx(np.linalg.norm(com_l))
    assert info["z_exit_nm"] == pytest.approx(1.4, abs=0.12)              # the far atom at 3.5 is beyond a 0.35 nm gap: ignored
    assert info["z_cc_source"] == "auto"
    assert g.z_cc_nm == pytest.approx(info["z_exit_nm"] + info["ligand_radius_nm"] + FN.Z_CC_MARGIN_NM)
    assert info["pull_needed_nm"] == pytest.approx(g.z_cc_nm + FN.SOLVATION_OFFSET_NM + FN.BULK_STRETCH_NM - g.z0_nm)
    assert FN.pull_needed_nm(g) == info["pull_needed_nm"]
    g2, info2 = FN.estimate_geometry(xyz, box, anchor, lig, masses, prot, z_cc_nm=2.0, r_cyl_nm=0.25)
    assert g2.z_cc_nm == 2.0 and info2["z_cc_source"] == "user" and g2.r_cyl_nm == 0.25


def test_estimate_geometry_without_protein_atoms_and_degenerate_axis():
    xyz = np.array([[0.0, 0, 0], [0.6, 0, 0]])
    g, info = FN.estimate_geometry(xyz, np.eye(3) * 5, [0], [1], np.ones(2), [])
    assert info["z_exit_nm"] == pytest.approx(g.z0_nm) and g.z_cc_nm == pytest.approx(g.z0_nm + 0.3)
    with pytest.raises(ValueError):
        FN.estimate_geometry(np.zeros((2, 3)), np.eye(3) * 5, [0], [1], np.ones(2), [])


# ------------------------------------------------------------------------------------------------ sample checks
def test_sample_checks_pass_fail_unknown():
    g = _geom()
    n = 200
    rng = np.random.default_rng(1)
    zs = np.full(n, 0.5)
    pw = {0.5: {"z": zs, "rho": np.abs(rng.normal(0, 0.1, n)), "dmin": np.full(n, np.nan)},
          2.2: {"z": np.full(n, 2.2), "rho": np.abs(rng.normal(0, 0.05, n)), "dmin": np.full(n, 0.9)}}
    ok = FN.sample_checks(g, pw, z_well_nm=0.5, bulk_in_cylinder=True)
    assert [ok[k]["status"] for k in ("bound_state", "solvation", "bulk_in_cylinder")] == ["pass"] * 3
    assert ok["bound_state"]["q99_margin_nm"] < -FN.BOUND_MARGIN_NM and FN.funnel_withheld_reason(ok) is None
    # squeezed bound state: lateral spread reaches the wall (rho_max(0.5) = 0.733)
    sq = {**pw, 0.5: {"z": zs, "rho": np.full(n, 0.72), "dmin": np.full(n, np.nan)}}
    r = FN.sample_checks(g, sq, z_well_nm=0.5, bulk_in_cylinder=True)
    assert r["bound_state"]["status"] == "fail" and "圓錐" in FN.funnel_withheld_reason(r)
    # ligand still touching the protein in the cylinder
    near = {**pw, 2.2: {"z": np.full(n, 2.2), "rho": np.zeros(n), "dmin": np.full(n, 0.4)}}
    r = FN.sample_checks(g, near, z_well_nm=0.5, bulk_in_cylinder=True)
    assert r["solvation"]["status"] == "fail" and "溶劑化" in FN.funnel_withheld_reason(r)
    # nothing recorded: unknown, never pass
    none = {c: {"z": v["z"], "rho": None, "dmin": None} for c, v in pw.items()}
    r = FN.sample_checks(g, none, z_well_nm=0.5, bulk_in_cylinder=None)
    assert [r[k]["status"] for k in ("bound_state", "solvation", "bulk_in_cylinder")] == ["unknown"] * 3
    assert FN.funnel_withheld_reason(r)
    # no window reaches z_cc + 0.5
    short = {0.5: pw[0.5]}
    assert FN.sample_checks(g, short, z_well_nm=0.5, bulk_in_cylinder=True)["solvation"]["status"] == "unknown"
    assert FN.sample_checks(g, pw, z_well_nm=0.5, bulk_in_cylinder=False)["bulk_in_cylinder"]["status"] == "fail"


# ------------------------------------------------------------------------------------------------ assessment gating
def _pmf(funnel=False, checks=None, plateau=True, n=6):
    M = [[1.0 if i == j else (0.3 if abs(i - j) == 1 else 0.0) for j in range(n)] for i in range(n)]
    base = {"method": "MBAR", "converged": True, "plateau": plateau, "pmf_radial_kj_mol": [0, 1, 2],
            "quality": {"window_stats": [{"n_effective": 400.0}] * n}, "coverage": {"continuous": True, "breaks": []},
            "overlap_matrix": {"matrix": M, "min_neighbour": 0.3}, "half_split": {"diff_kj_mol": 0.6},
            "convergence": {"0.25": {"delta_pmf": 19.0}, "0.50": {"delta_pmf": 20.2}, "0.75": {"delta_pmf": 20.1},
                            "1.00": {"delta_pmf": 20.0}}}
    ok = {"bound_state": {"status": "pass"}, "solvation": {"status": "pass"}, "bulk_in_cylinder": {"status": "pass"}}
    if funnel:
        base.update({"cv": FN.CV_AXIAL, "standard_state": {"treatment": FN.STANDARD_STATE_FUNNEL},
                     "funnel": {"checks": checks or ok}})
    else:
        base.update({"cv": FN.CV_RADIAL, "standard_state": {"treatment": FN.STANDARD_STATE_RADIAL}})
    return base


def _res(funnel=False, checks=None, plateau=True, dG=-30.0, withheld=None, condition="auto", ligand="A"):
    pm = _pmf(funnel, checks, plateau)
    cond = condition if condition != "auto" else binding_condition(BindingConfig(restraint="funnel" if funnel else "none"))
    return {"status": "PASS", "ligand": ligand, "context": "single", "delta_pmf_kj_mol": 20.0, "delta_pmf_err_kj_mol": 1.0,
            "dG_standard_kj_mol": dG, "dG_err_kj_mol": 1.0, "dG_withheld": withheld, "replicas": 3, "condition": cond,
            "assessment": assess_pmf(pm, dG_withheld=withheld, has_dG=dG is not None)}


def test_radial_result_is_not_eligible_for_ranking_but_keeps_an_approximate_dG():
    r = _res(funnel=False)
    el = r["assessment"]["eligibility"]
    assert el["delta_pmf_path_specific"] and el["dG_standard"] and el["affinity_ranking"] is False
    assert claim_eligible(r, "dG_standard") and not claim_eligible(r, "affinity_ranking")
    cs = claim_status(r, "affinity_ranking")
    assert cs["reasons"] == ["no_funnel_standard_state"] and cs["assessment"] == "pass" and cs["schema"] == CLAIM_SCHEMA
    assert cs["reference_state"]["funnel_standard_state"] is False
    assert "affinity ranking" in r["assessment"]["prohibited"]
    assert any("not for ranking" in x for x in r["assessment"]["permitted"])


def test_funnel_result_with_passing_diagnostics_is_eligible_for_ranking():
    r = _res(funnel=True)
    assert r["assessment"]["eligibility"]["affinity_ranking"] is True
    cs = claim_status(r, "affinity_ranking")
    assert cs["eligible"] and cs["reasons"] == [] and cs["reference_state"]["funnel_standard_state"] is True
    assert "funnel_solvation" in cs["evidence_ids"] and "funnel_bulk_cylinder" in cs["evidence_ids"]
    assert claim_eligible(r, "dG_standard") and claim_eligible(r, "path_specific")
    assert r["assessment"]["reference_state"] == {"cv": FN.CV_AXIAL, "standard_state": FN.STANDARD_STATE_FUNNEL, "funnel": True}
    assert any("funnel" in x for x in r["assessment"]["permitted"])


@pytest.mark.parametrize("which", ["bound_state", "solvation", "bulk_in_cylinder"])
@pytest.mark.parametrize("state", ["fail", "unknown"])
def test_funnel_check_not_passing_blocks_dG_and_ranking(which, state):
    checks = {"bound_state": {"status": "pass"}, "solvation": {"status": "pass"}, "bulk_in_cylinder": {"status": "pass"}}
    checks[which] = {"status": state}
    r = _res(funnel=True, checks=checks)
    assert not claim_eligible(r, "affinity_ranking") and not claim_eligible(r, "dG_standard")
    assert claim_eligible(r, "path_specific") is (which != "bound_state")     # only a squeezed bound state distorts the PMF
    cs = claim_status(r, "affinity_ranking")
    assert f"funnel_{'bulk_cylinder' if which == 'bulk_in_cylinder' else which}" in (cs["failed"] if state == "fail" else cs["unknown"])
    assert claim_status(r, "affinity_ranking")["assessment"] == state


def test_funnel_without_bulk_plateau_is_not_eligible():
    r = _res(funnel=True, plateau=False, dG=None, withheld="plateau")
    assert not claim_eligible(r, "affinity_ranking") and not claim_eligible(r, "dG_standard") and not claim_eligible(r, "path_specific")
    r2 = _res(funnel=True, plateau=False)                                 # a number was stored anyway: still no
    assert not claim_eligible(r2, "affinity_ranking")
    assert claim_status(r2, "affinity_ranking")["failed"] == ["endpoint_plateau"]


def test_stored_flag_cannot_outvote_the_recorded_reference_state():
    r = _res(funnel=False)
    r["assessment"]["eligibility"]["affinity_ranking"] = True             # tampered / stale flag
    assert not claim_eligible(r, "affinity_ranking")
    r = _res(funnel=True)
    r["condition"] = binding_condition(BindingConfig())                   # condition says radial
    assert not claim_eligible(r, "affinity_ranking") and ranking_basis(r, r["assessment"])[0] is False
    r["condition"] = None                                                 # condition not recorded: not guessed
    assert not claim_eligible(r, "affinity_ranking")
    r = _res(funnel=True)
    r["assessment"].pop("reference_state")                                # assessment written before D-140
    assert not claim_eligible(r, "affinity_ranking")


def test_versions_were_bumped():
    assert THRESHOLDS_VERSION == "2026-11-08.1" and CLAIM_SCHEMA.endswith("/2")
    assert _res(funnel=True)["assessment"]["thresholds_version"] == THRESHOLDS_VERSION


# ------------------------------------------------------------------------------------------------ condition, compare, config
def test_binding_condition_carries_cv_restraint_and_standard_state():
    c0 = binding_condition(BindingConfig())
    assert (c0["cv"], c0["funnel_restraint"], c0["standard_state"]) == (FN.CV_RADIAL, False, FN.STANDARD_STATE_RADIAL) and "funnel" not in c0
    c1 = binding_condition(BindingConfig(restraint="funnel", funnel_z_cc_nm=1.7))
    assert (c1["cv"], c1["funnel_restraint"], c1["standard_state"]) == (FN.CV_AXIAL, True, FN.STANDARD_STATE_FUNNEL)
    assert c1["funnel"] == {"r_cyl_nm": 0.2, "r_cone_nm": 1.0, "k_kj_mol_nm2": 4000.0, "z_min_nm": -0.2, "z_cc": 1.7}
    assert binding_condition(BindingConfig(restraint="funnel"))["funnel"]["z_cc"] == "auto"


def test_default_config_is_unchanged_and_old_results_stay_finished(tmp_path):
    d = BindingConfig()
    assert d.restraint == "none" and d.funnel_z_cc_nm is None and (d.funnel_r_cyl_nm, d.funnel_r_cone_nm, d.funnel_k) == (0.2, 1.0, 4000.0)
    old = {k: v for k, v in d.to_dict().items() if not k.startswith("funnel") and k != "restraint"}   # manifest from before D-140
    (tmp_path / "binding_manifest.json").write_text(json.dumps({"status": "PASS", "config": old, "result": {"status": "PASS", "d_bound_nm": 0.3}}))
    assert finished_result(tmp_path, d) is not None
    assert finished_result(tmp_path, BindingConfig(restraint="funnel")) is None      # a different protocol is not "finished"


def test_compare_binding_ranks_only_funnel_results():
    rad = {"A": _res(False, ligand="A"), "B": _res(False, ligand="B")}
    c = compare_binding(rad, contexts={"single": ["A", "B"]})["contexts"]["single"]
    assert c["status"] == "PATH_SPECIFIC" and c["quantity"].startswith("ΔΔPMF")
    assert context_basis(rad, ["A", "B"])["use_dG"] is False
    fun = {"A": _res(True, ligand="A"), "B": _res(True, ligand="B")}
    fun["B"]["dG_standard_kj_mol"] = -20.0
    c = compare_binding(fun, contexts={"single": ["A", "B"]})["contexts"]["single"]
    assert c["status"] == "PASS" and c["quantity"] == "ΔΔG°"
    mixed = {"A": _res(True, ligand="A"), "B": _res(False, ligand="B")}      # different CV/standard state: not the same quantity
    cm = compare_binding(mixed, contexts={"single": ["A", "B"]})["contexts"]["single"]
    assert cm["status"] == "INSUFFICIENT" or "ΔΔPMF" not in cm.get("quantity", "")
    assert context_basis(mixed, ["A", "B"])["use_dG"] is False and context_basis(mixed, ["A", "B"])["cond_bad"] is True


def test_comparability_matrix_says_why_a_radial_pair_is_only_an_order():
    from md20.report.comparability import comparability_matrix, reason_text
    m = comparability_matrix({"A": _res(False, ligand="A"), "B": _res(False, ligand="B")})
    cell = m["cells"]["A"]["B"]
    assert cell["grade"] == "order"
    lim = [x for x in cell["limits"] if x["code"] == "radial_not_ranked"]
    assert lim and lim[0]["keys"] == ["A", "B"]
    texts = [reason_text(lim[0], lg) for lg in ("zh", "en", "ja", "ko")]
    assert all(t.strip() and "A" in t for t in texts) and len(set(texts)) == 4
    assert comparability_matrix({"A": _res(True, ligand="A"), "B": _res(True, ligand="B")})["cells"]["A"]["B"]["grade"] == "ddg"


# ------------------------------------------------------------------------------------------------ wording in four languages
def test_report_text_four_languages():
    from md20.report import evidence as EV
    from md20.report.figure_text import classify_assessment, classify_standard_state, _DIAG_NAME
    from md20.report.interpret import binding as interpret_binding
    for k in ("no_funnel_standard_state",):
        assert len(EV.R[k]) == 4 and all(x.strip() for x in EV.R[k]) and len(set(EV.R[k])) == 4
    for k in ("affinity_ranking", "dG_standard"):
        assert len(EV.C[k]) == 4 and len(set(EV.C[k])) == 4
    assert "not for affinity ranking" in EV.C["dG_standard"][1] and "approximate" in EV.C["dG_standard"][1]
    for i in ("funnel_bound_state", "funnel_solvation", "funnel_bulk_cylinder"):
        assert len(_DIAG_NAME[i]) == 4 and all(x.strip() for x in _DIAG_NAME[i])
    rad, fun = _res(False), _res(True)
    s_rad, s_fun = classify_standard_state("A", rad["assessment"]), classify_standard_state("A", fun["assessment"])
    assert s_rad[0]["level"] == "note" and s_fun[0]["level"] == "good"
    for s in (s_rad[0], s_fun[0]):
        assert len(s["text"]) == 4 and all(t.strip() for t in s["text"]) and len(set(s["text"])) == 4
    assert "not used for affinity ranking" in s_rad[0]["text"][1] and "funnel" in s_fun[0]["text"][1]
    assert classify_standard_state("A", None) == [] and classify_standard_state("A", _res(False, dG=None)["assessment"]) == []
    assert any("funnel" in x["text"][1] for x in classify_assessment("A", fun["assessment"]))
    assert any("not used for affinity ranking" in x["text"][1] for x in classify_assessment("A", rad["assessment"]))
    f_rad = interpret_binding({"A": rad})
    f_fun = interpret_binding({"A": fun})
    approx = [f for f in f_rad if "approximate ΔG°" in f["text"][1]]
    assert approx and approx[0]["level"] == "note" and len(set(approx[0]["text"])) == 4
    good = [f for f in f_fun if f["level"] == "good" and "funnel restraint" in f["text"][1]]
    assert good and len(set(good[0]["text"])) == 4


# ------------------------------------------------------------------------------------------------ run_binding wiring (no OpenMM)
def test_run_binding_signature_and_recorder_is_passed_to_the_refinement():
    sig = inspect.signature(run_binding)
    assert sig.parameters["recorder"].default is None
    assert "recorder=recorder" in inspect.getsource(run_binding)
    assert sig.parameters["config"].default is None


def test_invalid_restraint_value_and_mixed_restraint_directories_are_stopped_before_any_simulation(tmp_path):
    r = run_binding("s.xml", "t.pdb", None, tmp_path / "a", config=BindingConfig(restraint="cone"))
    assert r.status == "NEEDS_HUMAN" and "restraint" in r.caveats[0]
    out = tmp_path / "b"
    out.mkdir()
    (out / "smd.json").write_text("{}")                                   # a radial pull already exists here (no marker = legacy none)
    r = run_binding("s.xml", "t.pdb", None, out, config=BindingConfig(restraint="funnel"))
    assert r.status == "NEEDS_HUMAN" and "不能混在一起" in r.caveats[0]
    (out / "restraint.json").write_text(json.dumps({"restraint": "funnel"}))
    with pytest.raises(Exception) as ei:                                  # same restraint: gets past the guard (then needs OpenMM)
        run_binding("s.xml", "t.pdb", None, out, config=BindingConfig(restraint="funnel"))
    assert "不能混在一起" not in str(ei.value)


# ------------------------------------------------------------------------------------------------ axial-z WHAM/MBAR path
def test_wham_on_synthetic_axial_samples_recovers_the_known_well_and_dG():
    """Independent samples of a known 1-D profile U(z) under harmonic windows -> pmf_from_windows -> axial_pmf.
    The profile is flat for z > 1.5 (the cylinder), so the recovered dG° must match the direct integral of exp(-U/kT)."""
    from md20.sampling.pmf import pmf_from_windows
    zg = np.linspace(0.2, 3.2, 3001)
    U = -20.0 * np.exp(-((zg - 0.6) / 0.2) ** 2)
    rng = np.random.default_rng(7)
    k = 1000.0
    samples, ks = {}, {}
    for c in np.arange(0.4, 2.61, 0.1):
        w = np.exp(-(U + 0.5 * k * (zg - c) ** 2) / KT)
        cdf = np.cumsum(w); cdf /= cdf[-1]
        samples[round(float(c), 4)] = np.interp(rng.uniform(size=4000), cdf, zg)
        ks[round(float(c), 4)] = k
    pres = pmf_from_windows(samples, force_constant_kj_mol_nm2=ks, temperature_k=300.0, n_bootstrap=0)
    r = FN.axial_pmf(pres, 300.0, {"r_cyl_nm": 0.2, "k_kj_mol_nm2": 4000.0, "z_cc_nm": 1.5})
    assert r["delta_pmf"] == pytest.approx(20.0, abs=1.5) and r["plateau"]
    a = FN.lateral_area_nm2(0.2, 4000.0, KT)
    sel = (zg >= 0.4) & (zg <= r["site_nm"][1])
    ref = -KT * math.log(a * np.trapezoid(np.exp(-U[sel] / KT), zg[sel]) / V0_NM3)
    assert r["dG"] == pytest.approx(ref, abs=1.5)
    assert r["dG"] < 0 and "pmf_kj_mol" not in r and np.all(np.isfinite(r["W"]))
