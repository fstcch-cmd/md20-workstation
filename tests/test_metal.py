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
