"""D-49: case-aware recommendations, plausibility checks and config round trip (pure Python)."""
from md20.advisor import (CaseFeatures, recommend, recommended_values, check, apply, values_from_config, estimate_hours,
                          features_from_config, parameter_table, PARAMS, QUICK_KEYS, system_atoms, format_value)
from md20.workflow import example_config


def _keys(issues, level=None):
    return {i["key"] for i in issues if level is None or i["level"] == level}


def test_every_parameter_has_bilingual_recommendation():
    for goal in ("teaching", "screening", "binding", "publication"):
        for f in (CaseFeatures(), CaseFeatures(ligand_kind="peptide", peptide_length=7), CaseFeatures(metals=["ZN"], bonded_metals=["ZN:A1"], n_residues=800)):
            en, zh = recommend(f, goal, "en"), recommend(f, goal, "zh")
            assert set(en) == set(PARAMS) == set(zh)
            for k in PARAMS:
                assert en[k]["why"] and zh[k]["why"] and en[k]["why"] != zh[k]["why"], (goal, k)
    assert set(QUICK_KEYS) <= set(PARAMS)


def test_recommendations_follow_the_case():
    small = recommended_values(CaseFeatures(), "teaching")
    pep = recommended_values(CaseFeatures(ligand_kind="peptide", peptide_length=7), "screening")
    metal = recommended_values(CaseFeatures(metals=["ZN"], bonded_metals=["ZN:A1"]), "screening")
    ion = recommended_values(CaseFeatures(metals=["CA"]), "screening")      # kept calcium is a non-bonded ion
    assert ion["timestep_fs"] == 4.0 and ion["restraints"] == "standard"
    pub = recommended_values(CaseFeatures(), "publication")
    assert small["tier"] == "classroom" and small["restraints"] == "standard" and small["exhaustiveness"] == 16
    assert pep["exhaustiveness"] == 32 and pep["restraints"] == "gentle" and pep["production_ns"] == 20.0
    assert metal["timestep_fs"] == 2.0 and metal["restraints"] == "gentle" and metal["nvt_ps"] > small["nvt_ps"] * 0
    assert pub["tier"] == "research" and pub["replicas"] == 3 and pub["timestep_fs"] == 2.0 and pub["binding"]
    assert pub["padding_nm"] >= 1.2 and pub["window_prod_ps"] >= 2000
    blind = recommended_values(CaseFeatures(box_size=[36, 51, 45]), "teaching")
    assert blind["exhaustiveness"] == 32
    # the recommendation itself passes its own checks (no error, no warning)
    for f, g in ((CaseFeatures(), "teaching"), (CaseFeatures(ligand_kind="peptide"), "screening"),
                 (CaseFeatures(metals=["ZN"], bonded_metals=["ZN:A1"]), "binding"), (CaseFeatures(), "publication")):
        bad = [i for i in check({}, f, goal=g) if i["level"] in ("error", "warning")]
        assert not bad, (g, bad)


def test_checks_catch_implausible_values():
    f = CaseFeatures()
    iss = check({"timestep_fs": 5.0, "temperature_k": 400.0, "padding_nm": 0.5, "nvt_ps": 10}, f)
    assert {"timestep_fs", "temperature_k", "padding_nm"} <= _keys(iss, "error") and "nvt_ps" in _keys(iss, "warning")
    assert check({"tier": "research", "timestep_fs": 4.0}, f)[0]["key"] == "timestep_fs"        # no HMR at research tier
    iss = check({"binding": True, "solvent": "gbn2", "window_prod_ps": 10, "window_equil_ps": 20, "pull_velocity_nm_per_ps": 0.05}, f)
    assert {"solvent", "window_equil_ps"} <= _keys(iss, "error") and "pull_velocity_nm_per_ps" in _keys(iss, "warning")
    iss = check({"restraints": "standard"}, CaseFeatures(ligand_kind="peptide"))
    assert "restraints" in _keys(iss, "warning")
    zh = check({"timestep_fs": 5.0}, f, lang="zh")[0]
    assert "步長" in zh["message"] and zh["label"] == "積分步長"
    assert any(i["suggestion"] == 4.0 for i in check({"timestep_fs": 5.0}, f))


def test_apply_round_trip_and_workflow_keys():
    cfg = example_config()
    vals = {"tier": "teaching", "production_ns": 20.0, "restraints": "gentle", "nvt_ps": 300.0, "npt_ps": 600.0,
            "temperature_k": 310.0, "timestep_fs": 2.0, "ion_positive": "K+", "ion_concentration_molar": 0.1,
            "binding": True, "window_prod_ps": 500.0, "pull_velocity_nm_per_ps": 0.005, "exhaustiveness": 24}
    out = apply(vals, cfg)
    assert cfg["md"].get("stage_overrides") is None                      # input untouched
    assert out["md"]["ions"]["positive"] == "K+" and out["md"]["ions"]["negative"] == "Cl-"
    so = out["md"]["stage_overrides"]
    assert so["production"]["temperature_k"] == 310.0 and so["nvt"]["timestep_fs"] == 2.0 and so["npt"]["length_ps"] == 600.0
    assert out["binding"]["config"]["window_prod_ps"] == 500.0 and "timestep_fs" not in out["binding"]["config"]
    back = values_from_config(out)
    for k, v in vals.items():
        assert back[k] == v, k
    # every stage override key is a real StageSpec field
    from dataclasses import fields
    from md20.engine.protocol import StageSpec
    names = {x.name for x in fields(StageSpec)}
    assert all(k in names for st in so.values() for k in st)


def test_features_and_estimate():
    pdb = "".join(f"ATOM  {i:5d}  CA  ALA A{i:4d}    {3.8 * i:8.3f}{0:8.3f}{0:8.3f}  1.00  0.00           C\n" for i in range(1, 101))
    pdb += "HETATM 9999 ZN    ZN A 900       0.000   5.000   0.000  1.00  0.00          ZN\n"
    cfg = {**example_config(), "keep_hetero": ["ZN"], "metal_policy": {"ZN:A900": "bonded"}}
    f = features_from_config(cfg, receptor_text=pdb, doctor={"benchmark": {"ns_per_day": 600, "n_atoms": 24000, "timestep_fs": 4},
                                                             "platform": {"name": "CUDA"}})
    assert f.n_residues == 100 and f.metals == ["ZN"] and f.bonded_metals == ["ZN:A900"] and f.gpu and f.ns_per_day == 600
    assert 5000 < system_atoms(f) < 15000
    est = estimate_hours({}, f, "screening")
    assert est["total_hours"] > 0 and est["md_hours"] > 0
    assert estimate_hours({}, CaseFeatures())["total_hours"] is None
    rows = parameter_table({"temperature_k": 310.0}, f, "teaching", "en")
    r = next(x for x in rows if x["key"] == "temperature_k")
    assert r["changed"] and r["value_text"] == "310 K" and r["recommended_text"] == "300 K"
    assert format_value("binding", True, "zh") == "是"
