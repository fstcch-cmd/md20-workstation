"""Metal policy and the crystal-geometry bonded model — pure logic (no OpenMM)."""
import numpy as np

from md20.build.metal import find_sites, plan_site, residue_variant, policy_for, site_gates, K_BOND


def _atom(i, name, resname, resseq, xyz, el, prot=True, chain="A"):
    return {"index": i, "name": name, "resname": resname, "chain": chain, "resseq": str(resseq), "xyz": list(xyz),
            "element": el, "is_protein": prot}


def _zn_cys4(extra=()):
    zn = np.array([10.0, 10.0, 10.0])
    t = np.array([[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]]) / np.sqrt(3) * 2.33   # tetrahedral, 2.33 Å
    atoms = [_atom(0, "ZN", "ZN", 301, zn, "Zn", prot=False)]
    for k, v in enumerate(t):
        atoms.append(_atom(k + 1, "SG", "CYS", 50 + k, zn + v, "S"))
        atoms.append(_atom(k + 10, "CB", "CYS", 50 + k, zn + 1.8 * v, "C"))
    return atoms + list(extra)


def test_find_tetrahedral_cys4_site():
    s = find_sites(_zn_cys4())[0]
    assert s["key"] == "ZN:A301" and len(s["donors"]) == 4 and not s["foreign"]
    assert all(abs(d["distance_A"] - 2.33) < 0.01 for d in s["donors"])


def test_bonded_plan_sets_cym_bonds_and_angles():
    atoms = _zn_cys4()
    s = find_sites(atoms)[0]
    p = plan_site(s, "bonded", {a["index"]: a["xyz"] for a in atoms})
    assert p["status"] == "AUTO_FIXED" and p["action"] == "bonded"
    assert set(p["variants"].values()) == {"CYM"} and len(p["variants"]) == 4
    assert len(p["bonds"]) == 4 and abs(p["bonds"][0]["r0_nm"] - 0.233) < 1e-3 and p["bonds"][0]["k"] == K_BOND
    assert len(p["angles"]) == 6 and all(abs(a["theta0_deg"] - 109.47) < 0.1 for a in p["angles"])
    assert "非擬合" in p["caveats"][0] or "非擬合的" in p["caveats"][0]


def test_his_tautomer_follows_coordinating_nitrogen():
    zn = np.array([0.0, 0.0, 0.0])
    atoms = [_atom(0, "ZN", "ZN", 1, zn, "Zn", prot=False),
             _atom(1, "NE2", "HIS", 10, (2.1, 0, 0), "N"), _atom(2, "ND1", "HIS", 11, (0, 2.1, 0), "N"),
             _atom(3, "NE2", "HIE", 12, (0, 0, 2.1), "N"),
             _atom(4, "O", "HOH", 900, (-2.1, 0, 0), "O", prot=False)]
    s = find_sites(atoms)[0]
    assert len(s["waters"]) == 1
    p = plan_site(s, "bonded", {a["index"]: a["xyz"] for a in atoms})
    assert p["variants"] == {"A:10": "HID", "A:11": "HIE", "A:12": "HID"}
    assert any("配位水" in c for c in p["caveats"])


def test_blocking_cases():
    zn = np.zeros(3)
    two = [_atom(0, "ZN", "ZN", 1, zn, "Zn", prot=False), _atom(1, "SG", "CYS", 2, (2.3, 0, 0), "S"),
           _atom(2, "SG", "CYS", 3, (0, 2.3, 0), "S")]
    assert plan_site(find_sites(two)[0], "bonded")["status"] == "NEEDS_HUMAN"            # < 3 protein donors
    lig = _zn_cys4([_atom(99, "O1", "L01", 1, (10.0, 10.0, 12.2), "O", prot=False)])
    p = plan_site(find_sites(lig)[0], "bonded")
    assert p["status"] == "NEEDS_HUMAN" and "非蛋白" in p["why"]                              # ligand–metal bond: not guessed
    both = [_atom(0, "ZN", "ZN", 1, zn, "Zn", prot=False), _atom(1, "ND1", "HIS", 5, (2.1, 0, 0), "N"),
            _atom(2, "NE2", "HIS", 5, (-2.1, 0, 0), "N"), _atom(3, "SG", "CYS", 6, (0, 2.3, 0), "S")]
    assert "兩個氮" in plan_site(find_sites(both)[0], "bonded")["why"]
    assert plan_site(find_sites(_zn_cys4())[0], "weird")["status"] == "NEEDS_HUMAN"


def test_other_policies_and_defaults():
    s = find_sites(_zn_cys4())[0]
    assert plan_site(s, "remove")["action"] == "remove"
    assert plan_site(s, "keep_nonbonded")["action"] == "keep_nonbonded"
    d = plan_site(s, None)
    assert d["status"] == "PASS" and d["action"] == "default_nonbonded"
    assert policy_for("ZN:A301", {"ZN": "remove", "ZN:A301": "bonded"}) == "bonded"
    assert policy_for("ZN:B9", {"ZN": "remove"}) == "remove"
    assert [g.status for g in site_gates([plan_site(s, "bonded")])] == ["AUTO_FIXED"]


def test_calcium_coordinated_by_protein_is_not_mistaken_for_calpha():
    atoms = [_atom(0, "CA", "ALA", 5, (0, 0, 0), "C"), _atom(1, "CA", "CA", 480, (5, 5, 5), "Ca", prot=False)]
    sites = find_sites(atoms)
    assert [s["key"] for s in sites] == ["CA:A480"]


def test_residue_variant_from_hydrogens():
    assert residue_variant("HIS", {"HD1"}) == "HID" and residue_variant("HIS", {"HE2"}) == "HIE"
    assert residue_variant("HIS", {"HD1", "HE2"}) == "HIP"
    assert residue_variant("CYS", {"HG"}) == "CYS" and residue_variant("CYS", {"SG"}) == "CYX"   # no HG = disulfide
    assert residue_variant("ASP", {"HD2"}) == "ASH" and residue_variant("GLU", set()) == "GLU"
    assert residue_variant("LYS", {"HZ1", "HZ2"}) == "LYN" and residue_variant("ALA", set()) is None


def test_bonded_metal_terms_exclude_13_scale_14_and_add_mdx_angles():
    """CI regression (3KS3): with only 1-2 exclusions Zn²⁺ was repelled by the imidazole ring next to NE2 and
    Zn–NE2 drifted 2.03 → 2.56 Å.  Metal–donor is now treated like any covalent bond."""
    import math
    import numpy as np
    from md20.build.metal import bonded_metal_terms
    # Zn(0)–NE2(1); NE2–CE1(2), NE2–CD2(3); CE1–HE1(4), CE1–ND1(5); CD2–HD2(6), CD2–CG(7);  second donor SG(8)–CB(9)–CA(10)
    bonds = [(1, 2), (1, 3), (2, 4), (2, 5), (3, 6), (3, 7), (8, 9), (9, 10)]
    pos = np.zeros((11, 3))
    pos[1] = [0.2, 0, 0]; pos[2] = [0.27, 0.11, 0]; pos[3] = [0.27, -0.11, 0]; pos[8] = [-0.23, 0, 0]; pos[9] = [-0.3, 0.15, 0]
    pos[4] = [0.25, 0.21, 0]; pos[5] = [0.38, 0.08, 0]; pos[6] = [0.25, -0.21, 0]; pos[7] = [0.38, -0.08, 0]; pos[10] = [-0.45, 0.15, 0]
    plans = [{"action": "bonded", "metal_index": 0, "bonds": [{"donor": 1}, {"donor": 8}]},
             {"action": "keep_nonbonded", "metal_index": 0, "bonds": []}]
    t = bonded_metal_terms(bonds, plans, pos)
    # metal-centred 1-3/1-4 plus the through-metal pairs: NE2–SG is 1-3 (D–M–D′); NE2–CB and SG–CE1/CD2 are 1-4
    assert t["excl13"] == [(0, 2), (0, 3), (0, 9), (1, 8)]
    assert t["pairs14"] == [(0, 4), (0, 5), (0, 6), (0, 7), (0, 10), (1, 9), (2, 8), (3, 8)]
    ang = {(d, x): th for _m, d, x, th in t["angles"]}
    assert set(ang) == {(1, 2), (1, 3), (8, 9)}
    u, v = pos[0] - pos[1], pos[2] - pos[1]
    assert math.isclose(ang[(1, 2)], math.acos(np.dot(u, v) / np.linalg.norm(u) / np.linalg.norm(v)))
    assert bonded_metal_terms(bonds, plans[1:], pos) == {"excl13": [], "pairs14": [], "angles": []}


def test_bonded_metal_terms_bidentate_donors_keep_force_field_relation():
    """Asp OD1/OD2 both bound to the metal: they are already 1-3 through CG, so no new exception is invented for them."""
    import numpy as np
    from md20.build.metal import bonded_metal_terms
    # M(0); OD1(1)–CG(3)–OD2(2); CG–CB(4)
    bonds = [(1, 3), (2, 3), (3, 4)]
    pos = np.array([[0, 0, 0], [0.2, 0.1, 0], [0.2, -0.1, 0], [0.32, 0, 0], [0.45, 0, 0]], float)
    t = bonded_metal_terms(bonds, [{"action": "bonded", "metal_index": 0, "bonds": [{"donor": 1}, {"donor": 2}]}], pos)
    assert (1, 2) not in t["excl13"] and (0, 3) in t["excl13"]
    assert all(p not in t["pairs14"] for p in [(1, 3), (2, 3), (1, 2)]) and (0, 4) in t["pairs14"]


def test_ligand_coordinating_metal_is_stopped_after_assembly():
    """REVIEW #15: a docked ligand O at 2.1 Å from Zn must stop the build (protein donors and far atoms do not)."""
    from md20.build.metal import ligand_metal_contacts, ligand_metal_gate
    atoms = [
        {"index": 0, "name": "ZN", "resname": "ZN", "chain": "A", "resseq": "262", "xyz": [0, 0, 0], "element": "Zn", "is_protein": False},
        {"index": 1, "name": "NE2", "resname": "HIS", "chain": "A", "resseq": "94", "xyz": [2.05, 0, 0], "element": "N", "is_protein": True},
        {"index": 2, "name": "O1", "resname": "L01", "chain": "L", "resseq": "1", "xyz": [0, 2.1, 0], "element": "O", "is_protein": False},
        {"index": 3, "name": "C1", "resname": "L01", "chain": "L", "resseq": "1", "xyz": [0, 1.9, 0.5], "element": "C", "is_protein": False},
        {"index": 4, "name": "O2", "resname": "L01", "chain": "L", "resseq": "1", "xyz": [0, 0, 3.2], "element": "O", "is_protein": False},
    ]
    c = ligand_metal_contacts(atoms, {2, 3, 4})
    assert [(x["atom"], x["metal"], x["distance_A"]) for x in c] == [("O1", "ZN:A262", 2.1)]
    g = ligand_metal_gate(c)
    assert g.status == "NEEDS_HUMAN" and "配體直接配位金屬" in g.explanation
    assert any(o.startswith("metal_policy: {ZN: remove}") for o in g.options)
    assert ligand_metal_contacts(atoms, {3, 4}) == [] and ligand_metal_gate([]) is None
    from md20.gui.actions import gate_actions                      # the remove option is one click in the GUI
    acts, manual = gate_actions(g.to_dict(), step="md_cases")
    assert [a["patch"][0]["value"] for a in acts] == ["remove"] and len(manual) == 2
