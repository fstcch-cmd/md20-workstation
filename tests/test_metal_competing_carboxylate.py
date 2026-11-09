"""D-152: a non-coordinating anionic carboxylate near a bonded metal is a NEEDS_HUMAN gate (point-charge collapse,
CI: CA II Glu106 → Zn 1.74 Å), not a silently-built collapsing model.  The user may choose to restrain it."""
import numpy as np

from md20.build.metal import find_sites, plan_site, carboxylate_for, COMPETING_COO_A


def _atom(i, name, resname, resseq, xyz, el, prot=True, chain="A"):
    return {"index": i, "name": name, "resname": resname, "chain": chain, "resseq": str(resseq), "xyz": list(xyz),
            "element": el, "is_protein": prot}


def _zn_his3_plus_glu(glu_dist=3.9):
    """Zn + 3 His N (coordinating, ~2.0 Å) + a Glu carboxylate O at glu_dist (second shell, outside the cutoff)."""
    t = np.array([[1, 1, 1], [1, -1, -1], [-1, 1, -1]]) / np.sqrt(3)
    atoms = [_atom(0, "ZN", "ZN", 262, (0, 0, 0), "Zn", prot=False),
             _atom(1, "NE2", "HIS", 94, 2.03 * t[0], "N"), _atom(2, "NE2", "HIS", 96, 2.04 * t[1], "N"),
             _atom(3, "ND1", "HIS", 119, 2.02 * t[2], "N"),
             _atom(4, "OE1", "GLU", 106, (-glu_dist / np.sqrt(3),) * 3, "O"),
             _atom(5, "CD", "GLU", 106, (-(glu_dist + 1.3) / np.sqrt(3),) * 3, "C")]
    return atoms


def test_competing_carboxylate_is_detected_within_range_not_as_a_donor():
    s = find_sites(_zn_his3_plus_glu(3.9))[0]
    assert [d["resseq"] for d in s["donors"]] == ["94", "96", "119"]      # Glu is NOT a coordinating donor
    comp = s["competing_carboxylates"]
    assert [c["name"] for c in comp] == ["OE1"] and comp[0]["resname"] == "GLU"
    # a carboxylate beyond COMPETING_COO_A is not flagged
    assert find_sites(_zn_his3_plus_glu(COMPETING_COO_A + 1.0))[0]["competing_carboxylates"] == []


def test_bonded_with_a_competing_carboxylate_and_no_decision_is_needs_human():
    s = find_sites(_zn_his3_plus_glu())[0]
    p = plan_site(s, "bonded", {a["index"]: a["xyz"] for a in _zn_his3_plus_glu()})
    assert p["status"] == "NEEDS_HUMAN" and p["gate_name"].startswith("competing carboxylate")
    assert "GLU106:OE1" in p["why"] and any("restrain" in o for o in p["options"])
    assert any("coordinate" in o for o in p["options"]) and any("keep_nonbonded" in o for o in p["options"])


def test_user_restrain_decision_excludes_nonbonded_and_adds_a_lower_wall():
    atoms = _zn_his3_plus_glu()
    s = find_sites(atoms)[0]
    p = plan_site(s, "bonded", {a["index"]: a["xyz"] for a in atoms}, carboxylate="restrain")
    assert p["status"] == "AUTO_FIXED"
    cr = p["competing_restraints"]
    assert len(cr) == 1 and cr[0]["donor"] == 4 and cr[0]["label"] == "GLU106:OE1"
    assert abs(cr[0]["r0_nm"] - 3.9 / 10.0) < 0.02 and cr[0]["k"] > 0
    assert any("排除" in c and "D-152" in c for c in p["caveats"])


def test_accept_decision_builds_but_warns_it_is_unusable():
    atoms = _zn_his3_plus_glu()
    p = plan_site(find_sites(atoms)[0], "bonded", {a["index"]: a["xyz"] for a in atoms}, carboxylate="accept")
    assert p["status"] == "AUTO_FIXED" and not p.get("competing_restraints")
    assert any("非物理" in c or "不可用" in c for c in p["caveats"])


def test_carboxylate_for_reads_the_site_decision():
    assert carboxylate_for("ZN:A262", {"ZN:A262": "Restrain"}) == "restrain"
    assert carboxylate_for("ZN:A262", {"ZN": "accept"}) == "accept"
    assert carboxylate_for("ZN:A262", None) is None


def test_a_bonded_site_with_no_competing_carboxylate_is_unaffected():
    # the CA-II-like His3 + water site (no Glu) still plans normally
    from test_metal_site_water import _ca2_like
    atoms = _ca2_like()
    p = plan_site(find_sites(atoms)[0], "bonded", {a["index"]: a["xyz"] for a in atoms})
    assert p["status"] == "AUTO_FIXED" and not p.get("competing_restraints")


# ------------------------------------------------------------------------------------------------------- D-165
def _fitted_plan(spec, atoms=None, **kw):
    atoms = atoms or _zn_his3_plus_glu()
    xyz = {a["index"]: a["xyz"] for a in atoms}
    return plan_site(find_sites(atoms)[0], "bonded", xyz, params=spec, **kw)


_JSON = {"bonds": {"N": {"k_kcal_A2": 60.0}}, "angles": {"default": {"k_kcal_rad2": 30.0}}}


def test_fitted_params_that_do_not_cover_the_carboxylate_stop_at_the_gate():
    p = _fitted_plan({"source": "json", "data": _JSON})
    assert p["status"] == "NEEDS_HUMAN" and p["gate_name"].startswith("competing carboxylate")
    assert "沒有涵蓋" in p["why"] and "GLU106:OE1" in p["why"]
    assert any("restrain" in o for o in p["options"]) and any("covers_residues" in o for o in p["options"])
    assert any("GLH" in o for o in p["options"]) and any("accept" in o for o in p["options"])
    assert p["evidence"]["carboxylate_coverage"]["uncovered"] == ["GLU106:OE1"]


def test_fitted_params_covering_the_carboxylate_pass_with_a_recorded_reason():
    for tok in ("A:106", "GLU106", "106"):
        p = _fitted_plan({"source": "json", "data": {**_JSON, "covers_residues": [tok]}})
        assert p["status"] == "AUTO_FIXED" and p["action"] == "bonded" and not p.get("competing_restraints"), tok
        assert "已被擬合參數來源涵蓋" in p["why"] and any("D-165" in c for c in p["caveats"])
    # also: explicit list next to `source` (hessian has no way to show it), and json charges for that very oxygen
    q = _fitted_plan({"source": "json", "data": {**_JSON, "charges": {"A:106": {"OE1": -0.8}}}},
                     residue_atoms={"A:106": {"OE1": 4}})
    assert "電荷表含該羧基氧" in q["why"]


def test_unreadable_or_hessian_only_sources_are_not_assumed_to_cover_it():
    assert _fitted_plan({"source": "hessian", "file": "x.fchk"})["status"] == "NEEDS_HUMAN"
    from md20.build.metal_params import carboxylate_coverage
    comp = find_sites(_zn_his3_plus_glu())[0]["competing_carboxylates"]
    c = carboxylate_coverage({"source": "json", "file": "/nonexistent/zn.json"}, comp)
    assert not c["all_covered"] and "讀取擬合參數來源失敗" in c["unreadable"]
    assert _fitted_plan({"source": "json", "file": "/nonexistent/zn.json"})["status"] == "NEEDS_HUMAN"
    # charges for another atom / another residue do not count
    assert _fitted_plan({"source": "json", "data": {**_JSON, "charges": {"A:106": {"OE2": -0.8}}}})["status"] == "NEEDS_HUMAN"
    assert _fitted_plan({"source": "json", "data": {**_JSON, "covers_residues": ["A:107"]}})["status"] == "NEEDS_HUMAN"


def test_mcpb_pdb_listing_the_carboxylate_oxygen_covers_it(tmp_path):
    from md20.build.metal_params import carboxylate_coverage
    comp = find_sites(_zn_his3_plus_glu())[0]["competing_carboxylates"]
    line = "ATOM      1 {:<4s} GLU A{:4d}       0.000   0.000   0.000  1.00  0.00           O\n"
    pdb = tmp_path / "m.pdb"
    pdb.write_text(line.format("OE1", 106))
    assert carboxylate_coverage({"source": "mcpb", "pdb": str(pdb)}, comp)["all_covered"]
    pdb.write_text(line.format("OE1", 107))
    assert not carboxylate_coverage({"source": "mcpb", "pdb": str(pdb)}, comp)["all_covered"]


def test_user_decisions_still_resolve_the_fitted_gate():
    spec = {"source": "json", "data": _JSON}
    r = _fitted_plan(spec, carboxylate="restrain")
    assert r["status"] == "AUTO_FIXED" and len(r["competing_restraints"]) == 1
    a = _fitted_plan(spec, carboxylate="accept")
    assert a["status"] == "AUTO_FIXED" and any("非物理" in c for c in a["caveats"])


def test_geometric_water_model_behaviour_is_unchanged():
    atoms = _zn_his3_plus_glu()
    p = plan_site(find_sites(atoms)[0], "bonded", {a["index"]: a["xyz"] for a in atoms})
    assert p["status"] == "NEEDS_HUMAN" and any("coordinate" in o for o in p["options"])
    assert not any("covers_residues" in o for o in p["options"])


def test_hydroxide_path_is_gated_the_same_way():
    # hydroxide mode needs the block + a crystal water on the final pass; the first pass already sees the carboxylate
    spec = {"source": "json", "data": {**_JSON, "site_water": {"state": "hydroxide", "charges": {"O": -1.2, "H": 0.2},
                                                               "bond": {"k_kcal_A2": 80.0}}}}
    p = plan_site(find_sites(_zn_his3_plus_glu())[0], "bonded", None, params=spec, water_state="hydroxide")
    assert p["status"] == "NEEDS_HUMAN" and p["gate_name"].startswith("competing carboxylate")
    spec["data"]["covers_residues"] = ["GLU106"]
    p2 = plan_site(find_sites(_zn_his3_plus_glu())[0], "bonded", None, params=spec, water_state="hydroxide")
    assert p2["status"] == "AUTO_FIXED"
