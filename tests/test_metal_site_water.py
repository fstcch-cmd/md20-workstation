"""D-133: the crystal water that completes a metal's coordination (CA II: Zn + His94/His96/His119 + water) is kept
for a `bonded` site — pure logic (no OpenMM).  CI diagnosis that motivated it: with the water removed, Glu106 OE1
collapsed onto Zn (1.74 Å) and all three Zn–N bonds stretched (HIS119:ND1 2.36 vs r0 2.02 Å)."""
import numpy as np

from md20.build.metal import (bonded_metal_terms, find_sites, plan_site, site_water_ligand_gate, site_waters_to_add,
                              read_site_waters, BONDED_POLICIES)
from md20.build.receptor import metal_site_water_lines


def _atom(i, name, resname, resseq, xyz, el, prot=True, chain="A"):
    return {"index": i, "name": name, "resname": resname, "chain": chain, "resseq": str(resseq), "xyz": list(xyz),
            "element": el, "is_protein": prot}


def _ca2_like(with_water=True):
    """Zn with three His N at 2.0 Å (tetrahedral directions) and the fourth vertex occupied by a water O."""
    t = np.array([[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]]) / np.sqrt(3)
    atoms = [_atom(0, "ZN", "ZN", 262, (0, 0, 0), "Zn", prot=False),
             _atom(1, "NE2", "HIS", 94, 2.03 * t[0], "N"), _atom(2, "NE2", "HIS", 96, 2.04 * t[1], "N"),
             _atom(3, "ND1", "HIS", 119, 2.02 * t[2], "N")]
    if with_water:
        atoms.append(_atom(4, "O", "HOH", 400, 1.98 * t[3], "O", prot=False))
    return atoms


def test_bonded_site_binds_the_crystal_water_as_fourth_partner():
    atoms = _ca2_like()
    s = find_sites(atoms)[0]
    assert s["waters"][0]["index"] == 4
    p = plan_site(s, "bonded", {a["index"]: a["xyz"] for a in atoms})
    assert p["status"] == "AUTO_FIXED" and p["action"] == "bonded" and p["policy"] == "bonded"
    assert len(p["bonds"]) == 4 and [b.get("water", False) for b in p["bonds"]] == [False, False, False, True]
    w = p["bonds"][3]
    assert w["label"] == "HOH400:O" and abs(w["r0_nm"] - 0.198) < 1e-3
    assert len(p["angles"]) == 6 and all(abs(a["theta0_deg"] - 109.47) < 0.2 for a in p["angles"])
    assert "四配位" in p["why"]
    assert any("TIP3P" in c and "D-133" in c for c in p["caveats"])
    assert p["variants"] == {"A:94": "HID", "A:96": "HID", "A:119": "HIE"}       # the water does not change tautomers


def test_bonded_open_keeps_the_pre_d133_open_site():
    atoms = _ca2_like()
    p = plan_site(find_sites(atoms)[0], "bonded_open", {a["index"]: a["xyz"] for a in atoms})
    assert p["action"] == "bonded" and len(p["bonds"]) == 3 and not any(b.get("water") for b in p["bonds"])
    assert len(p["angles"]) == 3 and "三配位" in p["why"]
    assert any("bonded_open" in c for c in p["caveats"])
    assert set(BONDED_POLICIES) == {"bonded", "bonded_open"}


def test_protein_donor_gate_still_counts_protein_only():
    """two His + water is still an incomplete protein site: the water never rescues the < 3 donor gate"""
    atoms = [a for a in _ca2_like() if a["index"] != 3]
    p = plan_site(find_sites(atoms)[0], "bonded", {a["index"]: a["xyz"] for a in atoms})
    assert p["status"] == "NEEDS_HUMAN" and "< 3" in p["why"]


def test_fitted_params_do_not_bind_the_water():
    atoms = _ca2_like()
    s = find_sites(atoms)[0]
    sites, plans = [s], [plan_site(s, "bonded")]
    waters = [{"resname": "HOH", "resseq": "400", "xyz": atoms[4]["xyz"]}]
    assert len(site_waters_to_add(sites, plans, waters)) == 1
    assert site_waters_to_add(sites, plans, waters, metal_params={"ZN": {"source": "json"}}) == []
    assert site_waters_to_add(sites, [plan_site(s, "bonded_open")], waters) == []
    assert site_waters_to_add(sites, [plan_site(s, "keep_nonbonded")], waters) == []
    far = [{"resname": "HOH", "resseq": "401", "xyz": (5.0, 0, 0)}]
    assert site_waters_to_add(sites, plans, far) == []


def test_no_angle_on_the_water_hydrogens_but_13_excluded():
    # Zn 0; His NE2 1 with ring neighbours 2,3; water O 4 with H 5,6
    bonds = [(1, 2), (1, 3), (4, 5), (4, 6)]
    pos = np.zeros((7, 3))
    pos[1] = [0.2, 0, 0]; pos[2] = [0.27, 0.11, 0]; pos[3] = [0.27, -0.11, 0]
    pos[4] = [-0.2, 0, 0]; pos[5] = [-0.25, 0.08, 0]; pos[6] = [-0.25, -0.08, 0]
    plans = [{"action": "bonded", "metal_index": 0, "bonds": [{"donor": 1}, {"donor": 4, "water": True}]}]
    t = bonded_metal_terms(bonds, plans, pos)
    assert (0, 5) in t["excl13"] and (0, 6) in t["excl13"]          # Zn–H(water) is 1-3: no nonbonded term
    assert {(d, x) for _m, d, x, _ in t["angles"]} == {(1, 2), (1, 3)}   # water may rotate


def test_ligand_on_the_site_water_is_stopped():
    plans = [{"key": "ZN:A262", "bonds": [{"donor": 1, "label": "HIS94:NE2"},
                                          {"donor": 4, "label": "HOH400:O", "water": True}]}]
    pos = np.zeros((10, 3)); pos[4] = [0.2, 0, 0]
    pos[8] = [0.21, 0.0, 0.0]                 # a ligand heavy atom 0.1 Å from the water oxygen
    g = site_water_ligand_gate(plans, pos, [8, 9])
    assert g is not None and g.status == "NEEDS_HUMAN" and any("bonded_open" in o for o in g.options)
    pos[8] = [0.6, 0, 0]; pos[9] = [0.7, 0, 0]
    assert site_water_ligand_gate(plans, pos, [8, 9]) is None
    assert site_water_ligand_gate(plans, pos, []) is None


def _pdb_line(rec, serial, name, resname, chain, resseq, xyz, el, altloc=" "):
    return (f"{rec:<6}{serial:>5} {name:<4}{altloc}{resname:>3} {chain}{resseq:>4}    "
            f"{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}  1.00 10.00          {el:>2}")


def test_receptor_sidecar_selects_only_waters_on_kept_metals(tmp_path):
    text = "\n".join([
        _pdb_line("HETATM", 1, "ZN", "ZN", "A", 262, (0, 0, 0), "ZN"),
        _pdb_line("HETATM", 2, "O", "HOH", "A", 400, (1.9, 0.3, 0), "O"),            # on the zinc
        _pdb_line("HETATM", 3, "O", "HOH", "A", 401, (1.9, 0.3, 0.1), "O", altloc="B"),  # second altloc: ignored
        _pdb_line("HETATM", 4, "O", "HOH", "A", 402, (6.0, 0, 0), "O"),              # bulk water
        _pdb_line("HETATM", 5, "CA", "CA", "A", 300, (20, 0, 0), "CA"),
        _pdb_line("HETATM", 6, "O", "HOH", "A", 403, (21.5, 0, 0), "O"),             # on calcium, not kept
    ])
    lines = metal_site_water_lines(text, {"ZN"})
    assert len(lines) == 1 and " 400 " in lines[0]
    assert len(metal_site_water_lines(text, {"ZN", "CA"})) == 2
    assert metal_site_water_lines(text, set()) == []
    f = tmp_path / "metal_site_waters.pdb"
    f.write_text("\n".join(lines) + "\nEND\n")
    w = read_site_waters(f)
    assert w == [{"resname": "HOH", "resseq": "400", "xyz": (1.9, 0.3, 0.0)}]
    assert read_site_waters(tmp_path / "missing.pdb") == []


def test_second_weak_water_is_not_first_shell():
    """D-139 (CI c014e8b, 3KS3): two crystal waters inside the 2.6 Å detection cutoff — the zinc water at 1.90 Å and
    a second one at 2.57 Å.  Only the first-shell water (≤ Harding Zn–O 2.09 + 0.25 Å) is bonded or added back."""
    from md20.build.metal import water_bond_max_A
    atoms = _ca2_like()
    atoms[4]["xyz"] = list(np.asarray(atoms[4]["xyz"]) / 1.98 * 1.90)
    atoms.append(_atom(5, "O", "HOH", 401, (0.2, 2.56, 0.0), "O", prot=False))        # 2.57 Å
    s = find_sites(atoms)[0]
    assert sorted(w["distance_A"] for w in s["waters"]) == [1.9, 2.57]               # still reported
    p = plan_site(s, "bonded", {a["index"]: a["xyz"] for a in atoms})
    assert [b["label"] for b in p["bonds"] if b.get("water")] == ["HOH400:O"] and len(p["bonds"]) == 4
    side = [{"resname": "HOH", "resseq": "400", "xyz": atoms[4]["xyz"]}, {"resname": "HOH", "resseq": "401", "xyz": atoms[5]["xyz"]}]
    assert [w["resseq"] for w in site_waters_to_add([s], [p], side)] == ["400"]
    assert abs(water_bond_max_A("ZN") - 2.34) < 1e-9 and abs(water_bond_max_A("CA") - 2.64) < 1e-9
