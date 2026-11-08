"""D-141: the metal-bound water as a hydroxide (OH-) — config resolution, the gate without parameters, the
`site_water` block of metal_params, the OHM template, the QM cluster with the water/OH-.  Pure logic (no OpenMM).

Numbers below that look like charges or force constants are *test values* that exercise the plumbing; they are not
parameters for any real system (the program never supplies such values itself)."""
import math
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from md20.build.gates import AUTO_FIXED, NEEDS_HUMAN
from md20.build.metal import (HYDROXIDE_ATOM_TYPES, HYDROXIDE_RESNAME, OPT_PROVIDE_SITE_WATER, OPT_QM_HYDROXIDE, WATER_STATES,
                              bonded_metal_terms, choose_hydroxide_h, decide_water_mode, find_sites, hydroxide_template_xml,
                              plan_site, site_gates, site_waters_to_add, water_state_for)
from md20.build.metal_params import (BOHR_TO_A, check_site_water_block, resolve_site_params, site_water_block,
                                     site_water_charge_problems, write_qm_cluster)
from test_metal_params import (DIRS, FRCMOD, R0, ZN, _mcpb_files, _mol2, _protonated_site_atoms, _residue_atoms, _site_atoms,
                               _xyz_of)

D4 = np.array([-1, -1, 1], float) / math.sqrt(3)             # the fourth tetrahedral vertex: the zinc water / hydroxide
O_IDX, H_IDX = 7, 8


def _oh_site(resname=HYDROXIDE_RESNAME, dist=1.95, with_h=True):
    """Zn + three His N (+ ring C) and a water residue at the fourth vertex (index 7 O, 8 H1)."""
    atoms = _site_atoms()
    o = ZN + dist * D4
    atoms.append({"index": O_IDX, "name": "O", "resname": resname, "chain": "A", "resseq": "400", "xyz": o.tolist(),
                  "element": "O", "is_protein": False})
    if with_h:
        h = o + 0.96 * (D4 * 0.4 + np.array([0.0, 0.9, 0.1])) / np.linalg.norm(D4 * 0.4 + np.array([0.0, 0.9, 0.1]))
        atoms.append({"index": H_IDX, "name": "H1", "resname": resname, "chain": "A", "resseq": "400", "xyz": h.tolist(),
                      "element": "H", "is_protein": False})
    return atoms


RES_ATOMS = {**_residue_atoms(), "A:400": {"O": O_IDX, "H1": H_IDX}}
BLOCK = {"state": "hydroxide", "charges": {"O": -1.2, "H": 0.2}, "bond": {"k_kcal_A2": 90.0, "r0_A": 1.93}}
JSON_DATA = {"bonds": {"N": {"k_kcal_A2": 70.0}}, "angles": {"default": {"k_kcal_rad2": 35.0}}, "site_water": BLOCK}
SPEC = {"source": "json", "data": JSON_DATA}


# ------------------------------------------------------------------------------------------- config resolution
def test_water_state_for_site_key_beats_element():
    cfg = {"ZN": "Hydroxide", "ZN:A301": "water"}
    assert water_state_for("ZN:A301", cfg) == "water" and water_state_for("ZN:B300", cfg) == "hydroxide"
    assert water_state_for("ZN:A301", None) is None and water_state_for("CA:A5", cfg) is None
    assert WATER_STATES == ("water", "hydroxide")


def test_decide_water_mode_matrix():
    d = decide_water_mode("ZN:A301", "bonded", None, None)
    assert d["mode"] == "water" and d["problem"] is None                       # default = current behaviour
    assert decide_water_mode("ZN:A301", "bonded", "water", {"source": "json"})["mode"] == "none"   # D-133: fitted params, no water
    assert decide_water_mode("ZN:A301", "bonded", None, {"source": "json"})["mode"] == "none"
    assert decide_water_mode("ZN:A301", "bonded", "hydroxide", None)["mode"] == "hydroxide"
    assert decide_water_mode("ZN:A301", "bonded", "hydroxide", SPEC)["block"] == BLOCK
    for pol in ("bonded_open", "keep_nonbonded", None):
        d = decide_water_mode("ZN:A301", pol, "hydroxide", None)
        assert d["problem"] and "bonded" in d["problem"] and d["mode"] == "none"
    assert decide_water_mode("ZN:A301", "bonded_open", None, None)["mode"] == "none"       # no state, no problem
    assert "不認得" in decide_water_mode("ZN:A301", "bonded", "oh", None)["problem"]
    # X-ray cannot see the proton: a hydroxide block without an explicit state is a conflict, never a decision
    d = decide_water_mode("ZN:A301", "bonded", None, SPEC)
    assert d["problem"] and "不自動決定" in d["problem"] and "metal_water_state: {ZN:A301: hydroxide}" in d["options"][0]
    d = decide_water_mode("ZN:A301", "bonded", "water", SPEC)                           # explicit water: block ignored, said so
    assert d["mode"] == "none" and d["problem"] is None and "未使用" in d["caveat"]


# ---------------------------------------------------------------------------------- the gate without parameters
def test_hydroxide_without_parameters_stops_with_three_options():
    atoms = _oh_site()
    site = find_sites(atoms)[0]
    assert [w["resname"] for w in site["waters"]] == ["OHM"] and not site["foreign"]      # OHM is a site water, not a ligand
    xo = _xyz_of(atoms)
    first = plan_site(site, "bonded", None, water_state="hydroxide")                      # before the topology edit: no gate yet
    assert first["status"] == AUTO_FIXED and first["water_mode"] == "hydroxide"
    p = plan_site(site, "bonded", xo, residue_atoms=RES_ATOMS, water_state="hydroxide")
    assert p["status"] == NEEDS_HUMAN and p["needs_water_params"] and p["gate_name"] == "metal water state ZN:A301"
    assert "不自動決定" in p["why"] and "不憑空設定" in p["why"]
    assert p["options"][0] == "metal_water_state: {ZN:A301: water}（維持中性 TIP3P 水，不改質子化狀態）"
    assert p["options"][1:] == [OPT_QM_HYDROXIDE, OPT_PROVIDE_SITE_WATER] and not p["bonds"]
    gates = site_gates([p])
    assert gates[0].name == "metal water state ZN:A301" and gates[0].status == NEEDS_HUMAN
    assert gates[0].evidence["water_mode"] == "hydroxide"
    # fitted donor parameters without a site_water block do not make the hydroxide parameterised
    p2 = plan_site(site, "bonded", xo, params={"source": "json", "data": {k: v for k, v in JSON_DATA.items() if k != "site_water"}},
                   residue_atoms=RES_ATOMS, water_state="hydroxide")
    assert p2["status"] == NEEDS_HUMAN and p2["needs_water_params"]


def test_gate_text_in_four_languages_and_one_click_actions():
    from md20.gui.actions import gate_actions
    from md20.gui.gate_text import gate_general, gate_title, option_text
    name = "metal water state ZN:A301"
    titles = {lang: gate_title(name, lang) for lang in ("zh", "en", "ja", "ko")}
    assert len(set(titles.values())) == 4 and all(t.endswith(" ZN:A301") for t in titles.values())
    gens = {lang: gate_general(name, lang) for lang in ("zh", "en", "ja", "ko")}
    assert all(gens.values()) and len(set(gens.values())) == 4 and "metal_qm" in gens["en"]
    p = plan_site(find_sites(_oh_site())[0], "bonded", _xyz_of(_oh_site()), residue_atoms=RES_ATOMS, water_state="hydroxide")
    for lang in ("en", "ja", "ko"):
        for o in (OPT_QM_HYDROXIDE, OPT_PROVIDE_SITE_WATER):
            assert option_text(o, lang) != o
        assert option_text(p["options"][0], lang) != p["options"][0] and "ZN:A301" in option_text(p["options"][0], lang)
    gate = {"name": name, "status": "NEEDS_HUMAN", "options": p["options"]}
    acts, manual = gate_actions(gate, step="md_cases")
    assert len(acts) == 1 and acts[0]["patch"] == [{"path": ["metal_water_state", "ZN:A301"], "value": "water"}]
    assert acts[0]["from_step"] == "md_cases" and manual == [OPT_QM_HYDROXIDE, OPT_PROVIDE_SITE_WATER]
    conflict = decide_water_mode("ZN:A301", "bonded", None, SPEC)
    acts, manual = gate_actions({"name": name, "status": "NEEDS_HUMAN", "options": conflict["options"]}, step="md_cases")
    assert [a["patch"][0]["value"] for a in acts] == ["hydroxide", "water"] and manual == []
    pol = decide_water_mode("ZN:A301", "bonded_open", "hydroxide", None)
    acts, _ = gate_actions({"name": name, "status": "NEEDS_HUMAN", "options": pol["options"]}, step="md_cases")
    assert acts[0]["patch"] == [{"path": ["metal_policy", "ZN:A301"], "value": "bonded"}]
    from md20.gui.actions import apply_patch
    cfg = apply_patch({}, [{"path": ["metal_water_state", "ZN:A301"], "value": "water"}])
    assert cfg == {"metal_water_state": {"ZN:A301": "water"}}


def test_metal_water_state_is_a_carried_decision():
    from md20.workflow import DECISION_KEYS
    assert ("metal_water_state",) in DECISION_KEYS


def test_default_water_behaviour_is_unchanged():
    atoms = _oh_site(resname="HOH")
    atoms = [a for a in atoms if a["index"] != H_IDX]
    site = find_sites(atoms)[0]
    p = plan_site(site, "bonded", _xyz_of(atoms))
    assert p["water_mode"] == "water" and len(p["bonds"]) == 4 and p["bonds"][3].get("water") and not p["bonds"][3].get("hydroxide")
    assert "site_water" not in p and p["status"] == AUTO_FIXED
    # fitted donor parameters: still no water (D-133)
    p = plan_site(site, "bonded", _xyz_of(atoms), params={"source": "json", "data": {k: v for k, v in JSON_DATA.items() if k != "site_water"}},
                  residue_atoms=RES_ATOMS)
    assert p["water_mode"] == "none" and len(p["bonds"]) == 3


def test_hydroxide_needs_exactly_one_converted_first_shell_water():
    atoms = _oh_site()
    xo = _xyz_of(atoms)
    kw = dict(residue_atoms=RES_ATOMS, water_state="hydroxide", params=SPEC)
    # not converted yet (still HOH with two H)
    a2 = _oh_site(resname="HOH")
    p = plan_site(find_sites(a2)[0], "bonded", _xyz_of(a2), **kw)
    assert p["status"] == NEEDS_HUMAN and "尚未轉成氫氧根" in p["why"] and p["options"] == ["metal_water_state: {ZN:A301: water}（維持中性 TIP3P 水，不改質子化狀態）"]
    # no crystal water at all: nothing is invented
    bare = _site_atoms()
    p = plan_site(find_sites(bare)[0], "bonded", _xyz_of(bare), **kw)
    assert p["status"] == NEEDS_HUMAN and "不憑空放置" in p["why"]
    # two first-shell waters: which one is the hydroxide?
    two = _oh_site()
    two.append({"index": 9, "name": "O", "resname": "HOH", "chain": "A", "resseq": "401", "xyz": (ZN + 2.1 * np.array([1, 0, 0])).tolist(),
                "element": "O", "is_protein": False})
    p = plan_site(find_sites(two)[0], "bonded", _xyz_of(two), **kw)
    assert p["status"] == NEEDS_HUMAN and "2 個水" in p["why"]
    assert plan_site(find_sites(atoms)[0], "bonded", xo, **kw)["status"] == AUTO_FIXED


def test_hydroxide_on_a_site_without_bonded_model_is_not_ignored():
    site = find_sites(_oh_site())[0]
    for pol in ("bonded_open", "keep_nonbonded", None):
        p = plan_site(site, pol, None, water_state="hydroxide")
        assert p["status"] == NEEDS_HUMAN and p["gate_name"] == "metal water state ZN:A301", pol
    assert plan_site(site, "remove", None, water_state="hydroxide")["action"] == "remove"      # the metal is gone: nothing to model


def test_site_waters_to_add_brings_the_water_back_for_a_hydroxide_site():
    atoms = _site_atoms()
    s = find_sites(atoms)[0]
    side = [{"resname": "HOH", "resseq": "400", "xyz": tuple((ZN + 1.95 * D4).tolist())}]
    plan = lambda st, params=None: plan_site(s, "bonded", None, params=params, water_state=st)           # noqa: E731
    got = site_waters_to_add([s], [plan("hydroxide")], side)
    assert [w["state"] for w in got] == ["hydroxide"] and got[0]["metal_key"] == "ZN:A301"      # also without parameters: the QM input needs it
    assert [w["state"] for w in site_waters_to_add([s], [plan("hydroxide", SPEC)], side, metal_params={"ZN": SPEC})] == ["hydroxide"]
    assert [w["state"] for w in site_waters_to_add([s], [plan(None)], side)] == ["water"]
    assert site_waters_to_add([s], [plan("water", SPEC)], side, metal_params={"ZN": SPEC}) == []      # explicit water + fitted params: D-133


# -------------------------------------------------------------------------- site_water block validation (pure)
def test_site_water_block_lookup():
    assert site_water_block(None) == (None, None) and site_water_block({"source": "json", "data": {}}) == (None, None)
    assert site_water_block(SPEC) == (BLOCK, None)
    assert site_water_block({"source": "hessian", "file": "x.hess", "site_water": BLOCK}) == (BLOCK, None)
    assert site_water_block({"source": "json", "file": "/nonexistent.json"}) == (None, None)       # reported at resolution
    assert site_water_block({"source": "json", "data": {"site_water": "OH"}})[1]


def test_site_water_block_structure_problems():
    ok = check_site_water_block(BLOCK)
    assert ok == []
    assert any("charges 缺少" in p for p in check_site_water_block({"state": "hydroxide"}))
    assert check_site_water_block({"state": "hydroxide"}, charges_required=False) == []               # mcpb: charges from the mol2
    assert any("H" in p and "缺少" in p for p in check_site_water_block({"state": "hydroxide", "charges": {"O": -1.0}}))   # missing H
    assert any("缺少 O" in p for p in check_site_water_block({"state": "hydroxide", "charges": {"H": 0.0}}))
    assert any("多餘" in p and "H2" in p for p in check_site_water_block({"state": "hydroxide", "charges": {"O": -0.8, "H": 0.4, "H2": 0.4}}))
    assert any("state" in p for p in check_site_water_block({"state": "water", "charges": {"O": -0.8, "H": 0.4}}))
    assert any("state" in p for p in check_site_water_block({"charges": {"O": -1.0, "H": 0.0}}))
    assert any("不認得" in p for p in check_site_water_block({**BLOCK, "chrages": {}}))
    assert any("不是合理" in p for p in check_site_water_block({"state": "hydroxide", "charges": {"O": "x", "H": 0.0}}))
    assert any("angle_MOH" in p for p in check_site_water_block({**BLOCK, "angle_MOH": {"k_kcal_rad2": 30}}))
    assert any("bond" in p for p in check_site_water_block({**BLOCK, "bond": {"r0_A": 1.9}}))


def test_site_water_net_charge_rules():
    f = lambda o, h, **kw: site_water_charge_problems(o, h, metal_charge=kw.get("m"), other_charges=kw.get("others", []), metal_element="ZN")  # noqa: E731
    assert f(-1.2, 0.2) == [] and f(-1.0, 0.0) == []                              # OH- alone: −1
    assert f(-0.8, 0.4)                                                          # −0.4: not an integer
    assert "要求 -1" in f(-0.5, 0.5)[0]                                           # sums to 0: that is a water, not a hydroxide
    assert f(-1.1, 0.1, m=2.0) == []                                              # Zn 2 + OH −1 = +1
    assert f(-1.1, 0.1, m=1.5)                                                    # 0.5: inconsistent
    assert "要求 +1" in f(-1.0, 0.0, m=3.0)[0]                                    # integer, wrong oxidation state
    assert f(-1.1, 0.1, m=1.2, others=[0.8]) == []                                # residue charges listed: only the integer is checked here
    assert f(-1.1, 0.1, m=1.2, others=[0.7])                                      # 0.9 → not an integer
    assert site_water_charge_problems(-1.0, 0.0, metal_charge=1.0, other_charges=[], metal_element="FE") == []      # no oxidation-state table for Fe: integer only


# --------------------------------------------------------- resolution with fitted parameters (json / hessian / mcpb)
def test_plan_with_fitted_water_bond_and_template():
    atoms = _oh_site()
    xo = _xyz_of(atoms)
    p = plan_site(find_sites(atoms)[0], "bonded", xo, params=SPEC, residue_atoms=RES_ATOMS, water_state="hydroxide")
    assert p["status"] == AUTO_FIXED and p["source"] == "json" and p["water_mode"] == "hydroxide", p["why"]
    assert len(p["bonds"]) == 4 and len(p["angles"]) == 6                         # three His + the hydroxide O, all pairs
    w = [b for b in p["bonds"] if b.get("water")][0]
    assert w["hydroxide"] and w["donor"] == O_IDX and w["label"] == "OHM400:O"
    assert w["r0_nm"] == pytest.approx(0.193) and w["k"] == pytest.approx(90.0 * 418.4)        # M–O from the fitted block
    assert [b["k"] for b in p["bonds"] if not b.get("water")] == [pytest.approx(70.0 * 418.4)] * 3
    assert all(a["k"] == pytest.approx(35.0 * 4.184) for a in p["angles"]) and any(O_IDX in (a["a"], a["b"]) for a in p["angles"])
    assert p["charges"] == {str(O_IDX): -1.2, str(H_IDX): 0.2}
    sw = p["site_water"]
    assert sw["o_index"] == O_IDX and sw["h_index"] == H_IDX and sw["q_O"] == -1.2 and sw["q_H"] == 0.2 and sw["moh_angle"] is None
    assert sw["resname"] == HYDROXIDE_RESNAME and "<Residue name=\"OHM\">" in sw["template_xml"]
    assert any("氫氧根" in c and "protein-OH" in c and "沒有 M–O–H 角項" in c for c in p["caveats"])
    assert "氫氧根（OH⁻）" in p["why"]
    # Zn–H(OH) is 1-3 (excluded), no M–O–H angle without fitted data, but the His rings keep their M–D–X angles
    nbr_bonds = [(1, 2), (3, 4), (5, 6), (O_IDX, H_IDX)]
    pos = np.array([a["xyz"] for a in atoms]) / 10.0
    t = bonded_metal_terms(nbr_bonds, [p], pos)
    assert (0, H_IDX) in t["excl13"] and "angles_moh" not in t and {(d, x) for _m, d, x, _ in t["angles"]} == {(1, 2), (3, 4), (5, 6)}


def test_fitted_moh_angle_is_the_only_way_to_get_an_moh_term():
    atoms = _oh_site()
    data = {**JSON_DATA, "site_water": {**BLOCK, "angle_MOH": {"k_kcal_rad2": 30.0, "theta0_deg": 115.0}}}
    p = plan_site(find_sites(atoms)[0], "bonded", _xyz_of(atoms), params={"source": "json", "data": data}, residue_atoms=RES_ATOMS,
                  water_state="hydroxide")
    assert p["status"] == AUTO_FIXED, p["why"]
    assert p["site_water"]["moh_angle"] == {"theta0_deg": 115.0, "k_kcal_rad2": 30.0, "k": pytest.approx(30.0 * 4.184)}
    assert "M–O–H 角使用擬合參數" in " ".join(p["caveats"])
    pos = np.array([a["xyz"] for a in atoms]) / 10.0
    t = bonded_metal_terms([(1, 2), (3, 4), (5, 6), (O_IDX, H_IDX)], [p], pos)
    assert t["angles_moh"] == [(0, O_IDX, H_IDX, pytest.approx(math.radians(115.0)), pytest.approx(30.0 * 4.184))]


@pytest.mark.parametrize("block,needle", [
    ({"state": "hydroxide", "charges": {"O": -1.2}, "bond": BLOCK["bond"]}, "缺少 H"),                          # missing H
    ({"state": "hydroxide", "charges": {"O": -0.9, "H": 0.2}, "bond": BLOCK["bond"]}, "不是整數"),             # −0.7: inconsistent net charge
    ({"state": "hydroxide", "charges": {"O": -0.5, "H": 0.5}, "bond": BLOCK["bond"]}, "要求 -1"),              # a water, not OH-
    ({"state": "hydroxide", "charges": {"O": -1.1, "H": 0.1}, "metal_charge": 1.5, "bond": BLOCK["bond"]}, "不是整數"),
    ({"state": "hydroxide", "charges": {"O": -1.1, "H": 0.1}, "metal_charge": 3.0, "bond": BLOCK["bond"]}, "要求 +1"),
    ({"state": "water", "charges": {"O": -1.2, "H": 0.2}, "bond": BLOCK["bond"]}, "state"),
    ({"state": "hydroxide", "bond": BLOCK["bond"]}, "charges 缺少"),
    ({"state": "hydroxide", "charges": BLOCK["charges"], "bond": {"k_kcal_A2": 900.0}}, "超出合理範圍"),
    ({"state": "hydroxide", "charges": BLOCK["charges"], "bond": {"k_kcal_A2": 90.0, "r0_A": 2.6}}, "差 >"),    # M–O r0 far from the crystal
])
def test_invalid_site_water_blocks_stop_the_site(block, needle):
    atoms = _oh_site()
    p = plan_site(find_sites(atoms)[0], "bonded", _xyz_of(atoms),
                  params={"source": "json", "data": {**JSON_DATA, "site_water": block}}, residue_atoms=RES_ATOMS, water_state="hydroxide")
    assert p["status"] == NEEDS_HUMAN and needle in p["why"], p["why"]
    assert "改用幾何鍵結模型" in " ".join(p["options"])


def test_consistent_metal_charge_is_applied():
    atoms = _oh_site()
    data = {**JSON_DATA, "site_water": {**BLOCK, "charges": {"O": -1.1, "H": 0.1}, "metal_charge": 2.0}}
    p = plan_site(find_sites(atoms)[0], "bonded", _xyz_of(atoms), params={"source": "json", "data": data}, residue_atoms=RES_ATOMS,
                  water_state="hydroxide")
    assert p["status"] == AUTO_FIXED and p["charges"] == {str(O_IDX): -1.1, str(H_IDX): 0.1, "0": 2.0}


def test_hessian_source_fits_the_metal_oxygen_bond(tmp_path):
    """The QM cluster that write_qm_cluster writes (Zn, three His, OH-) gives the M–O force constant like any donor."""
    from test_metal_params import _fchk_text
    k_b, k_a, kb_oh = 60.0, 30.0, 85.0
    dirs = np.vstack([DIRS, D4])
    pts = [("Zn", ZN)]
    for i in range(3):
        pts += [("N", ZN + R0 * dirs[i]), ("C", ZN + (R0 + 1.35) * dirs[i])]
    o = ZN + 1.95 * D4
    side = np.cross(D4, [0, 0, 1.0]); side /= np.linalg.norm(side)
    pts += [("O", o), ("H", o + 0.96 * (0.35 * D4 + 0.94 * side))]
    z = [{"Zn": 30, "N": 7, "C": 6, "O": 8, "H": 1}[e] for e, _ in pts]
    order = [5, 0, 7, 3, 2, 8, 6, 1, 4]                                    # reordered: the match is by geometry, not by order
    xyz = np.array([pts[i][1] - ZN for i in order]); z = [z[i] for i in order]
    pos_of = {old: new for new, old in enumerate(order)}
    bonds = [(0, 1, k_b), (0, 3, k_b), (0, 5, k_b), (1, 2, 400.0), (3, 4, 400.0), (5, 6, 400.0), (0, 7, kb_oh), (7, 8, 500.0)]
    bonds = [(pos_of[a], pos_of[b], k) for a, b, k in bonds]
    angles = [(pos_of[a], pos_of[m], pos_of[b]) for a, m, b in [(1, 0, 3), (1, 0, 5), (3, 0, 5), (1, 0, 7), (3, 0, 7), (5, 0, 7)]]
    xb = xyz / BOHR_TO_A

    def energy(x):
        x = x.reshape(-1, 3); e = 0.0
        for i, j, k in bonds:
            kk = k / 627.509474 * BOHR_TO_A ** 2
            e += 0.5 * kk * (np.linalg.norm(x[i] - x[j]) - np.linalg.norm(xb[i] - xb[j])) ** 2
        for a, b, c in angles:
            u, v = x[a] - x[b], x[c] - x[b]
            u0, v0 = xb[a] - xb[b], xb[c] - xb[b]
            th = math.acos(np.dot(u, v) / np.linalg.norm(u) / np.linalg.norm(v))
            th0 = math.acos(np.dot(u0, v0) / np.linalg.norm(u0) / np.linalg.norm(v0))
            e += 0.5 * (k_a / 627.509474) * (th - th0) ** 2
        return e
    n3 = 3 * len(z); h = np.zeros((n3, n3)); x0 = xb.reshape(-1); d = 1e-3
    for i in range(n3):
        for j in range(i, n3):
            ei, ej = np.zeros(n3), np.zeros(n3); ei[i] = d; ej[j] = d
            h[i, j] = h[j, i] = (energy(x0 + ei + ej) - energy(x0 + ei - ej) - energy(x0 - ei + ej) + energy(x0 - ei - ej)) / (4 * d * d)
    f = tmp_path / "zn_oh.fchk"; f.write_text(_fchk_text(z, xyz, h))
    atoms = _oh_site(); xo = _xyz_of(atoms)
    spec = {"source": "hessian", "file": str(f), "site_water": {"state": "hydroxide", "charges": {"O": -1.2, "H": 0.2}}}
    p = plan_site(find_sites(atoms)[0], "bonded", xo, params=spec, residue_atoms=RES_ATOMS, water_state="hydroxide")
    assert p["status"] == AUTO_FIXED and p["source"] == "hessian", p["why"]
    w = next(b for b in p["bonds"] if b.get("hydroxide"))
    assert w["k_kcal_A2"] == pytest.approx(kb_oh, rel=0.03) and w["r0_nm"] == pytest.approx(0.195, abs=2e-4)   # the cluster's own M–O
    assert all(b["k_kcal_A2"] == pytest.approx(k_b, rel=0.03) for b in p["bonds"] if not b.get("water"))
    assert len(p["angles"]) == 6 and p["charges"] == {str(O_IDX): -1.2, str(H_IDX): 0.2}


def test_mcpb_hydroxide_residue_gives_bond_angles_charges_and_moh(tmp_path):
    spec = _mcpb_files(tmp_path, hid_charge_sum=1.3 / 3)              # Zn 0.70 + three His summing to +1.3 → +2.0 (as the FF)
    frc = FRCMOD.replace("ZN-Y2   41.20   2.0400\n", "ZN-Y2   41.20   2.0400\nZN-oh   55.00   1.9500\n") \
                .replace("ZN-Y1-CV    50.00   125.00\n", "ZN-Y1-CV    50.00   125.00\nY1-ZN-oh    24.00   110.00\nY2-ZN-oh    23.00   109.00\nho-oh-ZN    20.00   118.00\n")
    (tmp_path / "zn.frcmod").write_text(frc)
    (tmp_path / "OH1.mol2").write_text(_mol2("OH1", [("O1", "oh", -1.10), ("H1", "ho", 0.10)]))
    spec["mol2"].append(str(tmp_path / "OH1.mol2"))
    spec["site_water"] = {"state": "hydroxide", "residue": "OH1"}
    atoms = _oh_site(); site = find_sites(atoms)[0]; xo = _xyz_of(atoms)
    p = plan_site(site, "bonded", xo, params=spec, residue_atoms=RES_ATOMS, water_state="hydroxide")
    assert p["status"] == AUTO_FIXED and p["source"] == "mcpb", p["why"]
    w = next(b for b in p["bonds"] if b.get("hydroxide"))
    assert w["k_kcal_A2"] == pytest.approx(110.0) and w["r0_nm"] == pytest.approx(0.195)
    assert p["charges"][str(O_IDX)] == -1.10 and p["charges"][str(H_IDX)] == 0.10 and p["charges"]["0"] == 0.70
    assert p["site_water"]["moh_angle"]["theta0_deg"] == 118.0 and p["site_water"]["moh_angle"]["k_kcal_rad2"] == pytest.approx(40.0)
    # no OH residue named → the translation refuses instead of guessing
    bad = dict(spec, site_water={"state": "hydroxide"})
    out = resolve_site_params({**site, "donors": site["donors"] + [{**site["waters"][0], "is_site_water": True}],
                               "site_water": {"o_index": O_IDX, "h_index": H_IDX, "block": bad["site_water"]}}, bad, xo, residue_atoms=RES_ATOMS)
    assert out["status"] == NEEDS_HUMAN and "site_water.residue" in out["why"]


# ------------------------------------------------------------------------------------- template + geometry (pure)
def test_hydroxide_template_xml():
    xml = hydroxide_template_xml(-1.2, 0.2)
    root = ET.fromstring(xml)
    res = root.find("Residues").findall("Residue")
    assert len(res) == 1 and res[0].get("name") == "OHM"
    atoms = {a.get("name"): a for a in res[0].findall("Atom")}
    assert set(atoms) == {"O", "H1"} and float(atoms["O"].get("charge")) == -1.2 and float(atoms["H1"].get("charge")) == 0.2
    assert atoms["O"].get("type") == HYDROXIDE_ATOM_TYPES["O"] == "protein-OH" and atoms["H1"].get("type") == "protein-HO"
    assert [(b.get("atomName1"), b.get("atomName2")) for b in res[0].findall("Bond")] == [("O", "H1")]
    assert root.find("AtomTypes") is None and root.find("HarmonicBondForce") is None and root.find("NonbondedForce") is None   # nothing invented
    assert 'name="XYZ"' in hydroxide_template_xml(-1.0, 0.0, resname="XYZ")


def test_choose_hydroxide_h_points_away_from_the_metal():
    m, o = np.array([0.0, 0, 0]), np.array([2.0, 0, 0])
    toward, away = np.array([2.2, 0.9, 0]), np.array([2.9, 0.3, 0])
    assert choose_hydroxide_h(m, o, [toward, away]) == 1 and choose_hydroxide_h(m, o, [away, toward]) == 0


# --------------------------------------------------------------------------------------------- QM cluster input
def _with_water(state, resname="HOH"):
    atoms = _protonated_site_atoms()
    o = ZN + 1.95 * D4
    base = len(atoms)
    hs = [o + 0.96 * np.array([0.3, 0.9, 0.2]) / np.linalg.norm([0.3, 0.9, 0.2]), o + 0.96 * np.array([-0.5, 0.2, 0.85]) / np.linalg.norm([-0.5, 0.2, 0.85])]
    atoms.append({"index": base, "name": "O", "resname": resname, "chain": "A", "resseq": "400", "xyz": o.tolist(), "element": "O", "is_protein": False})
    for k, h in enumerate(hs[:2 if state == "water" else 1]):
        atoms.append({"index": base + 1 + k, "name": f"H{k + 1}", "resname": resname, "chain": "A", "resseq": "400", "xyz": h.tolist(),
                      "element": "H", "is_protein": False})
    return atoms


def test_qm_cluster_includes_the_water_as_h2o(tmp_path):
    atoms = _with_water("water")
    site = find_sites(atoms)[0]
    out = write_qm_cluster(atoms, site, tmp_path / "qm", waters=[{"rid": "A:400", "state": "water"}])
    assert out["status"] == "PASS" and out["charge"] == 0 and out["multiplicity"] == 1
    assert out["waters"] == [{"residue": "A:400", "state": "water", "n_atoms": 3, "charge": 0}]
    assert out["n_atoms"] == 1 + (11 + 1) + (4 + 1) + (6 + 1) + 3
    xyz = (tmp_path / "qm" / "cluster.xyz").read_text(encoding="utf-8").splitlines()
    assert [ln.split()[0] for ln in xyz[-3:]] == ["O", "H", "H"] and "* xyz 0 1" in (tmp_path / "qm" / "orca.inp").read_text(encoding="utf-8")
    readme = (tmp_path / "qm" / "README.md").read_text(encoding="utf-8")
    assert "配位水" in readme and "H₂O" in readme and "三配位" in readme
    # without `waters` the cluster is the pre-D-141 one
    plain = write_qm_cluster(atoms, site, tmp_path / "qm0")
    assert plain["n_atoms"] == out["n_atoms"] - 3 and plain["waters"] == [] and "配位水" not in (tmp_path / "qm0" / "README.md").read_text(encoding="utf-8")


def test_qm_cluster_with_hydroxide_has_adjusted_charge_and_instructions(tmp_path):
    atoms = _with_water("hydroxide", resname=HYDROXIDE_RESNAME)
    site = find_sites(atoms)[0]
    out = write_qm_cluster(atoms, site, tmp_path / "qm", waters=[{"rid": "A:400", "state": "hydroxide"}])
    assert out["status"] == "PASS" and out["charge"] == -1 and out["multiplicity"] == 1           # +2 −1 (CYM) −1 (ASP) −1 (OH-)
    assert out["waters"][0]["n_atoms"] == 2 and out["waters"][0]["charge"] == -1
    assert out["n_atoms"] == 1 + (11 + 1) + (4 + 1) + (6 + 1) + 2
    assert "* xyz -1 1" in (tmp_path / "qm" / "orca.inp").read_text(encoding="utf-8")
    assert "\n-1 1\n" in (tmp_path / "qm" / "gaussian.gjf").read_text(encoding="utf-8")
    assert "charge=-1 mult=1" in (tmp_path / "qm" / "cluster.xyz").read_text(encoding="utf-8")
    readme = (tmp_path / "qm" / "README.md").read_text(encoding="utf-8")
    assert "氫氧根 OH⁻" in readme and "X 光看不到質子" in readme and "metal_water_state" in readme
    assert '"site_water"' in readme and "<RESP 的 O 電荷>" in readme and "RESP" in readme and "沒有預設值" in readme
    # open-shell metal: the explicit qm_charge is the metal's oxidation state, the water's −1 is added
    atoms[0].update(name="FE", resname="FE", element="Fe")
    fe = write_qm_cluster(atoms, find_sites(atoms)[0], tmp_path / "qm_fe", charge=2, multiplicity=5, waters=[{"rid": "A:400", "state": "hydroxide"}])
    assert fe["status"] == "PASS" and fe["charge"] == -1 and "* xyz -1 5" in (tmp_path / "qm_fe" / "orca.inp").read_text(encoding="utf-8")


def test_qm_cluster_refuses_a_water_that_is_not_what_was_asked(tmp_path):
    atoms = _with_water("water")                                                  # H2O in the topology, hydroxide requested
    out = write_qm_cluster(atoms, find_sites(atoms)[0], tmp_path / "qm", waters=[{"rid": "A:400", "state": "hydroxide"}])
    assert out["status"] == NEEDS_HUMAN and "氫氧根" in out["why"] and not (tmp_path / "qm").exists()
    out = write_qm_cluster(atoms, find_sites(atoms)[0], tmp_path / "qm", waters=[{"rid": "A:999", "state": "water"}])
    assert out["status"] == NEEDS_HUMAN
