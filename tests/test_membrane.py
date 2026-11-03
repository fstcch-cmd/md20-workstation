"""Membrane systems, pure logic (docs/specs/membrane.md): orientation scan, composition, surface placement, ions,
grid layout, analyses on synthetic coordinates, protocol switch.  No OpenMM needed."""
import math

import numpy as np
import pytest

from md20.build import membrane as MB
from md20.analysis import membrane as MA
from md20.build.gates import PASS, AUTO_FIXED, NEEDS_HUMAN

HYD = ["LEU", "ILE", "VAL", "PHE", "LEU", "ALA", "MET"]
POL = ["LYS", "GLU", "ASP", "ARG", "ASN", "GLN", "SER"]


def helix_bundle(n_helix=7, n_res=32, ring_nm=1.0, belt_half_nm=1.4, soluble=60, seed=1):
    """CA trace of a TM helix bundle along z (centre 0): hydrophobic residues inside |z| < belt_half, polar outside,
    plus a polar soluble domain above."""
    rng = np.random.default_rng(seed)
    xyz, names = [], []
    for h in range(n_helix):
        cx, cy = ring_nm * math.cos(2 * math.pi * h / n_helix), ring_nm * math.sin(2 * math.pi * h / n_helix)
        for i in range(n_res):
            z = (i - n_res / 2) * 0.15
            t = math.radians(100 * i)
            xyz.append([cx + 0.23 * math.cos(t), cy + 0.23 * math.sin(t), z])
            names.append(HYD[i % len(HYD)] if abs(z) < belt_half_nm else POL[i % len(POL)])
    for i in range(soluble):
        v = rng.normal(size=3)
        v = v / np.linalg.norm(v) * rng.uniform(0, 1.5)
        xyz.append([v[0], v[1], 3.9 + v[2] * 0.7])
        names.append(POL[i % len(POL)])
    return np.array(xyz), names


def rotate(xyz, R, shift):
    return xyz @ R.T + shift


# ------------------------------------------------------------------------------------------------ orientation
def test_orientation_recovers_tilted_bundle():
    xyz, names = helix_bundle()
    R = MB.random_rotation(np.random.default_rng(7))
    shift = np.array([3.0, -2.0, 5.0])
    res = MB.scan_orientation(rotate(xyz, R, shift), names)
    assert res["status"] == PASS and res["confidence"] == "high", res
    true_n = R @ np.array([0, 0, 1.0])
    ang = math.degrees(math.acos(min(1.0, abs(float(np.dot(true_n, res["normal"]))))))
    assert ang < 8.0
    # the slab centre lies on the bundle's belt centre (the original origin)
    assert abs(float(np.dot(np.asarray(res["centre_nm"]) - shift, true_n))) < 0.3
    assert res["tilt_deg"] == pytest.approx(math.degrees(math.acos(abs(true_n[2]))), abs=8.0)
    # applying the transform puts the normal on z and the belt at z = 0
    Rm, t = MB.orientation_transform(res)
    out = MB.apply_transform(rotate(xyz, R, shift), Rm, t)
    belt = np.array([n in HYD for n in names])
    assert abs(out[belt, 2].mean()) < 0.3
    assert out[belt, 2].std() < 1.0 and np.ptp(out[belt, 0]) < 3.5


def test_orientation_ambiguous_for_soluble_protein():
    rng = np.random.default_rng(3)
    v = rng.normal(size=(200, 3))
    v = v / np.linalg.norm(v, axis=1, keepdims=True) * rng.uniform(0, 1, (200, 1)) ** (1 / 3) * 2.2
    r = np.linalg.norm(v, axis=1)
    names = [HYD[i % 7] if r[i] < 1.4 else POL[i % 7] for i in range(200)]   # hydrophobic core, polar surface
    res = MB.scan_orientation(v, names)
    assert res["status"] == NEEDS_HUMAN
    g = MB.orientation_gate(res, oriented=False)
    assert g.status == NEEDS_HUMAN and g.options


def test_orientation_gate_user_oriented():
    xyz, names = helix_bundle()
    res = MB.scan_orientation(xyz, names)
    g = MB.orientation_gate(res, oriented=True)
    assert g.status == PASS
    R = MB.rotation_to_z(np.array([1.0, 0.0, 1.0]))          # 45° off: user claims oriented, scan disagrees
    res2 = MB.scan_orientation(xyz @ R.T, names)
    g2 = MB.orientation_gate(res2, oriented=True)
    assert g2.status == AUTO_FIXED and g2.advisory


def test_rotation_to_z():
    for n in ([0, 0, 1.0], [0, 0, -1.0], [1.0, 2.0, -0.5]):
        R = MB.rotation_to_z(np.array(n))
        assert np.allclose(R @ (np.array(n) / np.linalg.norm(n)), [0, 0, 1], atol=1e-9)
        assert np.allclose(R @ R.T, np.eye(3), atol=1e-9)


# ------------------------------------------------------------------------------------------------ composition
def test_presets_and_normalisation():
    comp, gates = MB.resolve_composition("bacterial")
    assert comp["upper"] == pytest.approx({"POPE": 0.75, "POPG": 0.25}) and not gates
    comp, gates = MB.resolve_composition({"popc": 7, "chl1": 3})
    assert comp["upper"] == pytest.approx({"POPC": 0.7, "CHOL": 0.3}) and gates[0].status == AUTO_FIXED
    comp, gates = MB.resolve_composition({"upper": {"POPC": 1}, "lower": {"POPE": 1}})
    assert comp["lower"] == {"POPE": 1.0}
    for bad in ("plant", {"XYZ": 1}, {"POPC": -1}, {"POPC": 0}, {"POPC": 0.4, "CHOL": 0.6}):
        _, gates = MB.resolve_composition(bad)
        assert any(g.status == NEEDS_HUMAN for g in gates), bad


def test_counts_exact():
    c = MB._counts_from_fractions({"POPE": 0.75, "POPG": 0.25}, 63)
    assert sum(c.values()) == 63 and abs(c["POPE"] - 47.25) <= 1


def test_plan_builders_and_gates():
    p, rep = MB.plan_membrane({"type": "protein", "lipids": "mammalian"}, has_solute=True)
    assert rep.ok and p.builder == "openmm_addmembrane" and p.temperature_k == 310.0
    p, rep = MB.plan_membrane({"type": "bilayer", "lipids": {"DOPC": 1}}, has_solute=False)
    assert rep.ok and p.builder == "openmm_patch_tile"
    p, rep = MB.plan_membrane({"type": "surface", "lipids": "bacterial"}, has_solute=True)
    assert not rep.ok and [g.name for g in rep.blocking] == ["membrane builder"]          # POPG has no template
    p, rep = MB.plan_membrane({"type": "surface", "lipids": "bacterial", "templates_dir": "/x"}, has_solute=True)
    assert rep.ok and p.builder == "grid"
    p, rep = MB.plan_membrane({"type": "bilayer", "lipids": {"POPC": 1, "POPE": 1}}, has_solute=False)
    assert rep.ok and p.builder == "grid" and any(g.advisory for g in rep.gates)
    _, rep = MB.plan_membrane({"type": "surface", "lipids": "gram_positive"}, has_solute=True)
    assert "membrane force field" in [g.name for g in rep.blocking]
    _, rep = MB.plan_membrane({"type": "bilayer", "lipids": {"DPPC": 1}}, has_solute=False)
    assert [g.name for g in rep.blocking] == ["membrane phase"]
    _, rep = MB.plan_membrane({"type": "bilayer", "lipids": {"DPPC": 1}, "temperature_k": 330}, has_solute=False)
    assert rep.ok
    _, rep = MB.plan_membrane({"type": "bilayer"}, has_solute=True)
    assert not rep.ok
    _, rep = MB.plan_membrane({"type": "protein"}, has_solute=True, solvent="gbn2")
    assert [g.name for g in rep.blocking] == ["membrane implicit solvent"]
    _, rep = MB.plan_membrane({"type": "membrane"}, has_solute=True)
    assert [g.name for g in rep.blocking] == ["membrane type"]
    _, rep = MB.plan_membrane({"type": "surface", "surface_distance_nm": 0.1}, has_solute=True)
    assert [g.name for g in rep.blocking] == ["membrane surface placement"]


def test_reference_values():
    r = MB.reference_values({"POPE": 0.75, "POPG": 0.25})
    assert r["apl_nm2"] == pytest.approx(0.75 * 0.58 + 0.25 * 0.661)
    assert MB.reference_values({"POPC": 0.7, "CHOL": 0.3})["apl_nm2"] is None
    assert MB.membrane_temperature({"lipids": "bacterial"}) == 310.0
    assert MB.membrane_temperature({"temperature_k": 303}) == 303.0


# ------------------------------------------------------------------------------------------------ surface, ions, box
def test_surface_placement():
    xyz, _ = helix_bundle(n_helix=1, n_res=20, soluble=0)
    for orient, tilt in (("parallel", 90.0), ("normal", 0.0)):
        out, info = MB.place_on_surface(xyz, upper_p_z=1.85, distance_nm=1.0, box_xy=(6.4, 6.6), orientation=orient, seed=4)
        assert out[:, 2].min() == pytest.approx(2.85)
        assert info["long_axis_tilt_deg"] == pytest.approx(tilt, abs=2.0)
        assert 0 <= info["lateral_xy_nm"][0] <= 6.4 and 0 <= info["lateral_xy_nm"][1] <= 6.6
        # rigid: internal distances unchanged
        assert np.allclose(np.linalg.norm(out[1:] - out[:-1], axis=1), np.linalg.norm(xyz[1:] - xyz[:-1], axis=1))
    a, _ = MB.place_on_surface(xyz, upper_p_z=1.85, orientation="random", seed=1)
    b, _ = MB.place_on_surface(xyz, upper_p_z=1.85, orientation="random", seed=1)
    assert np.allclose(a, b)
    lz = MB.surface_box_z(5.0, dpp_nm=3.8, water_gap_nm=2.0)
    assert lz == pytest.approx(5.0 + 1.9 + 0.5 + 2.0)


def test_ion_water_choice():
    rng = np.random.default_rng(0)
    o = np.column_stack([rng.uniform(0, 6, 3000), rng.uniform(0, 6, 3000), rng.uniform(-4, 4, 3000)])
    pick = MB.choose_ion_waters(o, 20, centre_z=0.0, box=(6, 6, 8), exclude_half_nm=2.6, min_sep_nm=0.5)
    assert len(set(pick)) == 20
    assert np.all(np.abs(o[pick, 2]) >= 2.6)
    d = o[pick][:, None] - o[pick][None]
    d -= np.array([6, 6, 8]) * np.round(d / np.array([6, 6, 8]))
    dist = np.sqrt((d ** 2).sum(-1)) + np.eye(20) * 9
    assert dist.min() >= 0.5
    with pytest.raises(ValueError):
        MB.choose_ion_waters(o[:5], 10, centre_z=0.0)
    assert MB.n_salt_pairs(5540, 0.15) == 15


# ------------------------------------------------------------------------------------------------ grid placer
def test_template_orientation_and_grid_layout():
    # a "lipid": head P at top, tail going down along a tilted direction
    tail = np.array([[0.0, 0.0, 0.0]] + [[0.05 * k, 0.03 * k, -0.12 * k] for k in range(1, 15)])
    el = ["P"] + ["C"] * 14
    t = MB.template_from_coordinates("POPC", tail + 3.0, el, ["P"] + [f"C{k}" for k in range(14)])
    assert np.allclose(t.xyz[0], 0)
    assert t.xyz[1:, 2].max() < 0                             # tail below the head
    assert np.allclose(t.xyz[1:, :2], 0, atol=1e-9)           # straight tail now along −z
    comp = {"upper": {"POPE": 0.75, "POPG": 0.25}, "lower": {"POPE": 0.75, "POPG": 0.25}}
    prot = np.column_stack([np.full(200, 3.2), np.full(200, 3.2), np.linspace(-2, 2, 200)])   # a thin rod at the centre
    lay = MB.grid_layout(comp, (6.4, 6.4), dpp_nm=3.9, apl_nm2=0.6, protein_xyz=prot, seed=3)
    n_full = lay["n_full_per_leaflet"]
    assert n_full == round(6.4 * 6.4 / 0.6)
    for leaf in ("upper", "lower"):
        slots = [s for s in lay["slots"] if s["leaflet"] == leaf]
        assert len(slots) < n_full                                     # the rod removed slots
        assert all(math.hypot(s["x"] - 3.2, s["y"] - 3.2) > 0.5 for s in slots)
        cnt = lay["counts"][leaf]
        assert cnt["POPE"] + cnt["POPG"] == len(slots) and abs(cnt["POPE"] - 0.75 * len(slots)) <= 1
    lo = next(s for s in lay["slots"] if s["leaflet"] == "lower")
    X = MB.place_template(t, lo)
    assert X[0, 2] == pytest.approx(-1.95) and X[1:, 2].min() > X[0, 2]   # lower leaflet: head down, tail up


def test_index_ranges():
    assert MB.index_ranges([5, 3, 4, 9, 10, 0]) == [[0, 1], [3, 6], [9, 11]]


# ------------------------------------------------------------------------------------------------ analyses
def synthetic_bilayer(F=5, n=64, dpp=3.8, box=(6.4, 6.4, 9.0), wrap_shift=0.0, seed=0):
    rng = np.random.default_rng(seed)
    heads = np.zeros((F, 2 * n, 3))
    for f in range(F):
        heads[f, :, :2] = rng.uniform(0, box[0], (2 * n, 2))
        heads[f, :n, 2] = dpp / 2 + rng.normal(0, 0.05, n)
        heads[f, n:, 2] = -dpp / 2 + rng.normal(0, 0.05, n)
    heads[..., 2] = (heads[..., 2] + wrap_shift) % box[2]           # stored wrapped into [0, Lz)
    return heads, np.tile(np.array(box, float), (F, 1))


def test_thickness_apl_and_centre_with_wrapping():
    for shift in (0.0, 4.5, 8.8):
        heads, box = synthetic_bilayer(wrap_shift=shift)
        th = MA.thickness_pp(heads, box)
        assert th["mean_nm"] == pytest.approx(3.8, abs=0.05)
        assert th["n_upper"] == th["n_lower"] == 64
        c = th["centre_nm"]
        assert np.allclose(MA._mic(c - shift, 9.0), 0, atol=0.05)
    apl = MA.area_per_lipid(box, 64, 64)
    assert apl["mean_nm2"] == pytest.approx(6.4 * 6.4 / 64)


def test_density_profile_integrates_to_count():
    heads, box = synthetic_bilayer()
    c = MA.membrane_centre(heads[..., 2], box)
    prof = MA.density_profile(heads[..., 2], box, c, bin_nm=0.1)
    total = prof["density_per_nm3"].sum() * 0.1 * 6.4 * 6.4
    assert total == pytest.approx(128, rel=1e-6)
    peak_z = prof["z_nm"][np.argmax(prof["density_per_nm3"])]
    assert abs(abs(peak_z) - 1.9) < 0.15
    assert MA.to_g_cm3(602.214076) == pytest.approx(1.0, rel=1e-6)   # 602 amu per nm³ = 1 g/cm³


def test_order_parameter():
    xyz = np.zeros((2, 4, 3))
    xyz[:, 1] = [0, 0, 0.109]          # C–H along z → S = 1
    xyz[:, 3] = [0.109, 0, 0]          # in plane → S = −0.5
    assert MA.order_parameter(xyz, [(0, 1)]) == pytest.approx(1.0)
    assert MA.order_parameter(xyz, [(2, 3)]) == pytest.approx(-0.5)
    names = ["C22", "H2R", "H2S", "C32", "H2X", "H2Y", "C210", "H10R", "P"]
    g = MA.scd_groups_from_names(names, [1] * len(names))
    assert g["sn2:C22"] == [(0, 1), (0, 2)] and g["sn1:C32"] == [(3, 4), (3, 5)] and g["sn2:C210"] == [(6, 7)]
    assert list(g)[:2] == ["sn1:C32", "sn2:C22"]


def test_insertion_depth_contacts_residence_tilt():
    heads, box = synthetic_bilayer(F=6)
    sol = np.zeros((6, 3, 3))
    zs = [3.0, 2.5, 2.0, 1.6, 1.6, 2.4]                  # approaches, dips 0.3 nm below the P plane, leaves
    for f, z in enumerate(zs):
        sol[f] = [[3.0, 3.0, z], [3.1, 3.0, z + 0.2], [3.2, 3.0, z + 0.4]]
    d = MA.insertion_depth(sol, heads, box)
    assert d["com_depth_nm"][0] == pytest.approx(1.9 - 3.2, abs=0.05)
    assert d["com_depth_nm"][3] == pytest.approx(1.9 - 1.8, abs=0.05)
    assert d["deepest_nm"][3] == pytest.approx(0.3, abs=0.05) and not d["crossed_centre"]
    # lower leaflet, mirrored
    low = sol.copy(); low[..., 2] *= -1
    assert np.allclose(MA.insertion_depth(low, heads, box)["com_depth_nm"], d["com_depth_nm"], atol=0.05)
    contact = MA.headgroup_contacts([sol[:, :1], sol[:, 2:3]], heads, box, cutoff_nm=0.6)
    assert contact.shape == (6, 2)
    rt = MA.residence_times(np.array([[0, 1], [1, 1], [1, 0], [0, 0], [1, 1], [1, 1]], bool), dt_ps=10.0)
    assert rt[0] == {"fraction": pytest.approx(4 / 6), "events": 2, "mean_ps": 20.0, "max_ps": 20.0, "open_at_end": True}
    assert rt[1]["events"] == 2 and rt[1]["max_ps"] == 20.0
    ca = np.zeros((2, 10, 3))
    ca[0, :, 0] = np.arange(10) * 0.15                    # flat
    ca[1, :, 2] = np.arange(10) * 0.15                    # along the normal
    assert np.allclose(MA.helix_tilt(ca), [90.0, 0.0], atol=1e-6)


def test_water_in_core_and_gate():
    heads, box = synthetic_bilayer(F=2)
    c = MA.membrane_centre(heads[..., 2], box)
    o = np.zeros((2, 4, 3))
    o[:, :, :2] = [[1, 1], [3, 3], [5, 5], [2, 2]]
    o[:, :, 2] = [0.1, -0.2, 3.5, 0.0]
    o[..., 2] = (o[..., 2] + c[:, None])
    assert list(MA.water_in_core(o, c, box)) == [3, 3]
    prot = np.zeros((2, 1, 3)); prot[:, 0] = [3.1, 3.0, 0]
    assert list(MA.water_in_core(o, c, box, exclude_xyz=prot)) == [2, 2]       # pore water does not count
    ref = MB.reference_values({"POPC": 1.0})
    g = MA.assess_equilibration(apl_nm2=0.65, dpp_nm=3.75, core_water=0.2, n_lipids=128, reference=ref)
    assert g.status == PASS
    g = MA.assess_equilibration(apl_nm2=0.55, dpp_nm=3.75, core_water=0.2, n_lipids=128, reference=ref)
    assert g.status == AUTO_FIXED and g.evidence["action"] == "extend_equilibration"
    g = MA.assess_equilibration(apl_nm2=0.55, dpp_nm=3.75, core_water=0.2, n_lipids=128, reference=ref, attempt=1)
    assert g.status == NEEDS_HUMAN and g.options
    g = MA.assess_equilibration(apl_nm2=None, dpp_nm=3.7, core_water=5, n_lipids=128,
                                reference={"apl_nm2": None, "dpp_nm": 3.7}, protein_offset_nm=0.2)
    assert g.status == AUTO_FIXED and g.evidence["checks"] == {"dpp": True, "core_water": False, "protein_in_membrane": True}
    assert MA.protein_offset(np.full((2, 3, 3), 0.4) + c[:, None, None] * np.array([0, 0, 1]), c, box) == pytest.approx([0.4, 0.4])


# ------------------------------------------------------------------------------------------------ engine switch
def test_membrane_protocol_is_additive():
    from md20.engine.protocol import make_protocol, membrane_protocol, production_restraints, Protocol
    for strat in ("standard", "hold_backbone"):
        p = make_protocol("teaching", restraints=strat)
        h = p.hash()
        m = membrane_protocol(p, temperature_k=310.0)
        assert p.hash() == h and m.hash() != h                         # the original is untouched
        st = {s.name: s for s in m.stages}
        assert st["npt"].barostat == "membrane" and st["production"].barostat == "membrane"
        assert st["nvt"].barostat == "isotropic"
        assert st["nvt"].restraint_groups["lipid_head"] == [1.0, 1.0]
        assert st["npt"].restraint_groups["lipid_head"] == [1.0, 0.0]
        assert all(s.temperature_k == 310.0 for s in m.stages if s.ensemble != "MIN")
        assert Protocol.from_dict(m.to_dict()).hash() == m.hash()
        assert "lipid_head" not in production_restraints(m)
        if strat == "hold_backbone":
            assert st["production"].restraint_groups["lipid_head"] == [0.0, 0.0]
    d = make_protocol("teaching").to_dict()
    assert all("barostat" not in s for s in d["stages"])            # default omitted: old hashes unchanged


def test_fake_backend_accepts_lipid_head_group():
    from md20.engine.backend import FakeBackend
    assert FakeBackend().set_global_parameter("msw_rs_lipid_head", 0.0)


def test_gate_texts_registered():
    from md20.gui.gate_text import gate_title, gate_general
    for name in ("membrane type", "membrane composition", "membrane phase", "membrane force field", "membrane builder",
                 "membrane orientation", "membrane surface placement", "membrane implicit solvent",
                 "membrane equilibration", "membrane binding"):
        for lang in ("zh", "en", "ja", "ko"):
            assert gate_general(name, lang), (name, lang)
        assert gate_title(name, "en") != name
