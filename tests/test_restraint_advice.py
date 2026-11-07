"""D-118: smart restraint advice (advice only, pure Python, synthetic inputs)."""
import copy

import pytest

from md20 import advisor as A
from md20.engine.protocol import RESTRAINT_STRATEGIES, make_protocol, membrane_protocol
from md20.engine.restraint_advice import (RestraintInputs, advise, decision_entry, plddt_low_fraction_from_pdb,
                                           resolution_from_pdb, rough_reasons)
from md20.i18n import LANGS


def base(**kw):
    d = dict(has_ligand=True, ligand_kind="small", structure_source="crystal", resolution_a=1.8, target="md", n_pose_clashes=0)
    d.update(kw)
    return RestraintInputs(**d)


def test_clean_crystal_small_ligand_is_standard():
    a = advise(base())
    assert a["status"] == "advice" and a["strategy"] == "standard" and a["protocol_args"] == {"restraints": "standard"}
    assert a["differences"]["same"] and a["differences"]["changes"] == []


@pytest.mark.parametrize("kw,key", [
    (dict(resolution_a=3.1), "low_resolution"),
    (dict(structure_source="model", resolution_a=None), "model"),
    (dict(structure_source="model", resolution_a=None, plddt_low_fraction=0.3), "low_plddt"),
    (dict(has_gaps=True), "gaps"),
    (dict(n_rebuilt_residues=6), "gaps"),
    (dict(n_pose_clashes=3), "pose_clash"),
    (dict(ligand_kind="peptide"), "peptide"),
    (dict(ligand_kind="mixed"), "peptide"),
    (dict(bonded_metals=["ZN:A1"]), "bonded_metal"),
    (dict(simultaneous_ligands=True), "simultaneous"),
])
def test_rough_start_features_give_gentle(kw, key):
    a = advise(base(**kw))
    assert a["strategy"] == "gentle"
    assert key in {x["key"] for x in a["items"] if x["role"] == "reason"}
    assert any(x["key"] == "gentle_cost" for x in a["items"])


def test_boundaries_do_not_trigger():
    assert advise(base(resolution_a=2.5))["strategy"] == "standard"                 # exactly 2.5 A is not coarser
    assert advise(base(structure_source="crystal", plddt_low_fraction=0.5))["strategy"] == "standard"   # pLDDT is for models
    assert advise(base(has_ligand=False, n_pose_clashes=4))["strategy"] == "standard"    # no ligand, no pose
    assert advise(base(metals=["ZN"]))["strategy"] == "standard"                    # kept ion, not bonded
    assert any(x["key"] == "free_metals" for x in advise(base(metals=["ZN"]))["items"])
    assert advise(base(structure_source="model", plddt_low_fraction=0.02, resolution_a=None))["strategy"] == "gentle"


def test_difference_from_current_setting():
    a = advise(base(resolution_a=3.0))                       # nothing set: default standard
    d = a["differences"]
    assert d["current"] == "standard" and d["current_is_default"] and d["suggested"] == "gentle" and not d["same"]
    kinds = {(c["stage"], c["what"]) for c in d["changes"]}
    assert ("nvt", "sidechain") in kinds and ("npt", "length_ps") in kinds
    nvt_sc = next(c for c in d["changes"] if c["stage"] == "nvt" and c["what"] == "sidechain")
    assert nvt_sc["current"] == [1.0, 0.5] and nvt_sc["suggested"] == [1.0, 1.0]
    same = advise(base(resolution_a=3.0, current="gentle"))["differences"]
    assert same["same"] and not same["current_is_default"]
    bad = advise(base(current="loose"))["differences"]
    assert bad["current_valid"] is False and bad["same"] is False


def test_stage_multipliers_come_from_the_engine_and_make_protocol_accepts_them():
    for kw in (dict(), dict(resolution_a=3.0), dict(ligand_kind="peptide", tier="research", production_ns=50.0)):
        i = base(**kw)
        a = advise(i)
        proto = make_protocol(i.tier, production_ns=i.production_ns, **a["protocol_args"])
        for st in proto.stages:
            if st.name == "minimize":
                continue
            t = a["stages"][st.name]
            assert t["groups"] == {g: [float(x), float(y)] for g, (x, y) in st.restraint_groups.items()}
            assert t["length_ps"] == st.length_ps
        assert a["strategy"] in RESTRAINT_STRATEGIES


def test_membrane_adds_lipid_head_group_and_note():
    a = advise(base(membrane=True, resolution_a=3.0))
    proto = membrane_protocol(make_protocol("teaching", restraints="gentle"))
    assert "lipid_head" in a["stages"]["npt"]["groups"]
    assert a["stages"]["npt"]["groups"]["lipid_head"] == list(map(float, proto.stage("npt").restraint_groups["lipid_head"]))
    assert any(x["key"] == "membrane" for x in a["items"])
    assert not any(x["key"] == "membrane" for x in advise(base())["items"])


def test_apo_and_smd_notes():
    assert any(x["key"] == "apo" for x in advise(base(has_ligand=False, ligand_kind=None))["items"])
    s = advise(base(target="smd"))
    assert any(x["key"] == "smd" for x in s["items"])
    assert s["options"][0]["strategy"] == "hold_backbone" and s["options"][0]["suggested"] is False


def test_hold_backbone_is_only_an_option_for_short_clean_md():
    short = advise(base(production_ns=0.5))
    assert short["strategy"] == "standard" and short["options"][0]["suggested"] is True
    assert advise(base(production_ns=10.0))["options"][0]["suggested"] is False
    # a model or a low-confidence backbone must not be locked in place
    assert advise(base(structure_source="model", resolution_a=None, production_ns=0.5))["options"][0]["suggested"] is False
    # the tier default length counts when production_ns is not set: classroom = 2 ns, not short
    assert advise(base(tier="classroom"))["options"][0]["suggested"] is False


def test_current_hold_backbone_is_cautioned_for_smd_and_models():
    for kw in (dict(target="smd"), dict(structure_source="model", resolution_a=None)):
        a = advise(base(current="hold_backbone", **kw))
        assert any(x["role"] == "caution" and x["level"] == "warning" for x in a["items"])
    assert not any(x["role"] == "caution" for x in advise(base(current="hold_backbone", production_ns=0.5))["items"])


def test_never_recommends_freezing_or_truncation():
    a = advise(base(resolution_a=3.0))
    assert a["strategy"] in RESTRAINT_STRATEGIES
    note = next(x for x in a["items"] if x["key"] == "no_freeze")
    assert "OpenMM" in note["text"]


def test_not_enough_information_says_what_is_missing():
    a = advise(RestraintInputs())
    assert a["status"] == "unavailable" and a["strategy"] is None and a["protocol_args"] is None
    assert {m["key"] for m in a["missing"]} == {"has_ligand", "structure_source", "target"}
    assert a["applied"] is False
    assert advise(base(structure_source=None))["status"] == "unavailable"
    smd_apo = advise(base(target="smd", has_ligand=False))
    assert smd_apo["status"] == "unavailable" and [m["key"] for m in smd_apo["missing"]] == ["ligand_for_smd"]
    assert advise(base(tier="huge"))["status"] == "unavailable"


def test_unknown_optional_data_is_listed_not_guessed():
    a = advise(base(resolution_a=None))
    assert a["strategy"] == "standard"
    keys = {x["key"] for x in a["not_considered"]}
    assert "resolution" in keys
    assert "pose_clash" in {x["key"] for x in advise(base(n_pose_clashes=None))["not_considered"]}
    assert "plddt" in {x["key"] for x in advise(base(structure_source="model", resolution_a=None))["not_considered"]}


def test_all_four_languages_complete_and_distinct():
    cases = [base(), base(resolution_a=3.0, ligand_kind="peptide", n_pose_clashes=2, has_gaps=True, n_rebuilt_residues=5),
             base(structure_source="model", resolution_a=None, plddt_low_fraction=0.4, bonded_metals=["ZN"], membrane=True,
                  target="smd", current="hold_backbone", simultaneous_ligands=True),
             base(has_ligand=False, metals=["ZN"], production_ns=0.5), RestraintInputs(), base(target="smd", has_ligand=False)]
    for i in cases:
        for lang in LANGS:
            a = advise(i, lang)
            texts = [a["summary"]] + [x["text"] for x in a["items"] + a["options"] + a["not_considered"]]
            assert all(t and t.strip() for t in texts)
        a = advise(i)
        for t in [a["summary_all"]] + [x["text_all"] for x in a["items"] + a["options"] + a["not_considered"]]:
            assert set(t) == {"zh", "en", "ja", "ko"} and all(t.values())
            assert len(set(t.values())) == 4
    for _, short in rough_reasons(cases[2]):
        assert len(short) == 4 and all(short)
    a = advise(cases[1])
    assert "Å" in a["summary_all"]["ja"] and "3" in a["summary_all"]["ko"]
    assert not any(c in a["summary_all"]["en"] for c in "—–→")


def test_advice_changes_nothing():
    i = base(resolution_a=3.0)
    before = copy.deepcopy(i.to_dict())
    p0 = make_protocol("teaching").hash()
    a = advise(i)
    assert i.to_dict() == before and a["applied"] is False and make_protocol("teaching").hash() == p0
    f = A.CaseFeatures(resolution_a=3.0)
    cfg = {"md": {"tier": "teaching"}}
    snapshot = copy.deepcopy(cfg)
    A.restraint_advice(f, "teaching", A.values_from_config(cfg))
    A.check(A.values_from_config(cfg), f)
    assert cfg == snapshot


def test_decision_entry_is_chinese_and_not_written():
    e = decision_entry(advise(base(resolution_a=3.0)))
    assert e["choice"] == "gentle" and "溫和" in e["why"] and "low_resolution" in e["evidence"]["reasons"]


# ------------------------------------------------------------------------ structure file readers
def test_header_readers():
    pdb = "REMARK   2 RESOLUTION.    2.10 ANGSTROMS.\nATOM      1  N   ALA A   1      0.0 0.0 0.0\n"
    assert resolution_from_pdb(pdb) == 2.1
    assert resolution_from_pdb("REMARK   2 RESOLUTION. NOT APPLICABLE.\n") is None
    assert resolution_from_pdb("ATOM      1  N   ALA A   1\n") is None

    def ca(n, b):
        return f"ATOM  {n:5d}  CA  ALA A{n:4d}    {0.0:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00{b:6.2f}           C\n"
    txt = "".join(ca(n, b) for n, b in enumerate([95, 91, 65, 40, 88, 90, 92, 93, 94, 96], 1))
    assert plddt_low_fraction_from_pdb(txt) == pytest.approx(0.2)
    assert plddt_low_fraction_from_pdb("HEADER\n") is None


# ------------------------------------------------------------------------ advisor integration
def _rec(f, goal="teaching"):
    return A.recommended_values(f, goal)["restraints"]


def test_advisor_recommendation_and_advice_agree():
    feats = [A.CaseFeatures(), A.CaseFeatures(ligand_kind="peptide"), A.CaseFeatures(resolution_a=3.0),
             A.CaseFeatures(structure_source="model", plddt_low_fraction=0.3), A.CaseFeatures(n_pose_clashes=2),
             A.CaseFeatures(has_gaps=True), A.CaseFeatures(bonded_metals=["ZN:A1"]), A.CaseFeatures(resolution_a=2.0),
             A.CaseFeatures(n_ligands=2, docking_mode="simultaneous")]
    for f in feats:
        for goal in ("teaching", "binding"):
            adv = A.restraint_advice(f, goal)
            assert adv["status"] == "advice" and _rec(f, goal) == adv["strategy"]


def test_advisor_unchanged_for_default_features():
    assert _rec(A.CaseFeatures()) == "standard" and _rec(A.CaseFeatures(ligand_kind="peptide")) == "gentle"
    why = A.recommend(A.CaseFeatures(resolution_a=3.2), "teaching", "en")["restraints"]["why"]
    assert "3.2 Å" in why and "rough" in why


def test_check_shows_the_advice_as_a_suggestion():
    f = A.CaseFeatures(resolution_a=3.2)
    v = A.recommended_values(f)
    v["restraints"] = "standard"
    iss = [i for i in A.check(v, f) if i["key"] == "restraints"]
    assert iss and iss[0]["level"] == "info" and iss[0]["suggestion"] == "gentle"
    v["restraints"] = "gentle"
    assert not [i for i in A.check(v, f) if i["key"] == "restraints"]
    # no duplicate when an older rule already warns
    f2 = A.CaseFeatures(ligand_kind="peptide")
    assert len([i for i in A.check({"restraints": "standard"}, f2) if i["key"] == "restraints"]) == 1
    # hold_backbone with SMD gets a warning
    fb = A.CaseFeatures(binding=True)
    w = [i for i in A.check({"restraints": "hold_backbone"}, fb, goal="binding") if i["key"] == "restraints" and i["level"] == "warning"]
    assert w and w[0]["suggestion"] == "standard"
    for lang in LANGS:
        assert all(i["message"] for i in A.check({"restraints": "standard"}, f, lang=lang))


def test_features_from_config_reads_header_values():
    cfg = {"ligands": [{"name": "L", "smiles": "CCO"}], "md": {"membrane": {"type": "bilayer"}}}
    f = A.features_from_config(cfg, receptor_text="REMARK   2 RESOLUTION.    3.40 ANGSTROMS.\n"
                                                  "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C\n")
    assert f.resolution_a == 3.4 and f.membrane and f.has_ligand and f.plddt_low_fraction is None
    assert A.features_from_config({"md": {}}).has_ligand is False
    m = A.features_from_config({"ligands": [{"name": "L"}], "receptor": {"alphafold": True}},
                               receptor_text="ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 40.00           C\n"
                                             "ATOM      2  CA  ALA A   2       3.800   0.000   0.000  1.00 90.00           C\n")
    assert m.structure_source == "model" and m.plddt_low_fraction == 0.5 and m.resolution_a is None


# ------------------------------------------------------------------------ D-123: inputs from build and docking records
from md20.engine.restraint_advice import (capped_breaks_from_manifest, features_from_records, pose_clashes_from_selection,
                                           rebuilt_residues_from_manifest)

REBUILT = {"(0, 45)": ["GLY", "SER"], "(0, 80)": ["ALA", "ALA", "THR"]}


def _bm(**rec):
    """A build_manifest.json as build_case writes it: the receptor manifest sits under "receptor"."""
    return {"status": "PASS", "receptor": {"status": "PASS", **rec}, "ligands": []}


def _sel(**per_lig):
    return {"mode": "simultaneous", "ligands": per_lig}


def _joint(entry="E", rejections=(), lig_names=("A", "B")):
    return {n: {"rank": 1, "entry": entry, "docking_rejections": list(rejections)} for n in lig_names}


def test_rebuilt_residues_read_from_the_manifest_keys():
    assert rebuilt_residues_from_manifest(_bm(missing_residues_added=REBUILT)) == 5
    assert rebuilt_residues_from_manifest({"missing_residues_added": REBUILT}) == 5      # a receptor manifest itself
    assert rebuilt_residues_from_manifest(_bm(missing_residues_added={})) == 0           # the manifest says: none rebuilt
    # not readable -> unknown, never 0
    assert rebuilt_residues_from_manifest(_bm()) is None                                 # receptor blocked before the repair
    assert rebuilt_residues_from_manifest(_bm(missing_residues_added=["GLY"])) is None
    assert rebuilt_residues_from_manifest(_bm(missing_residues_added={"(0, 1)": "GLY"})) is None
    assert rebuilt_residues_from_manifest({}) is None and rebuilt_residues_from_manifest(None) is None
    assert rebuilt_residues_from_manifest({"receptor": "x"}) is None


def test_capped_breaks_read_from_the_manifest():
    assert capped_breaks_from_manifest(_bm(capped_breaks=[{"chain": "A", "before": 10, "after": 14, "new_chain": "B"}])) == 1
    assert capped_breaks_from_manifest(_bm(capped_breaks=[])) == 0
    assert capped_breaks_from_manifest(_bm()) is None and capped_breaks_from_manifest(None) is None


def test_pose_clashes_from_the_selection():
    clash = [{"code": "geometry_repairable", "rule": "ligand_clash", "params": {}, "text": "x"}]
    other = [{"code": "model_limitation", "rule": "score_window", "params": {}, "text": "y"}]
    assert pose_clashes_from_selection(_sel(**_joint(rejections=clash))) == 1
    assert pose_clashes_from_selection(_sel(**_joint(rejections=other))) == 0
    assert pose_clashes_from_selection(_sel(**_joint(rejections=[]))) == 0
    two = {**_joint("E1", clash), **_joint("E2", [], ("C", "D"))}
    assert pose_clashes_from_selection(_sel(**two)) == 1
    # unknown: no selection, nothing joint (docking only measures ligand-ligand distance), or an older record
    assert pose_clashes_from_selection(None) is None and pose_clashes_from_selection({}) is None
    assert pose_clashes_from_selection(_sel(A={"rank": 1, "entry": "A", "docking_rejections": clash})) is None
    assert pose_clashes_from_selection(_sel(A={"rank": 1, "entry": "E"}, B={"rank": 1, "entry": "E"})) is None
    assert pose_clashes_from_selection(_sel(A={"rank": 1, "entry": "A", "source": "fold_complex"})) is None


def test_features_from_records_takes_the_largest_count_and_keeps_unknown():
    r = features_from_records(manifests=[_bm(missing_residues_added={"(0, 1)": ["GLY"]}), _bm(missing_residues_added=REBUILT), _bm()])
    assert r["n_rebuilt_residues"] == 5 and r["n_capped_breaks"] is None and r["n_pose_clashes"] is None
    assert r["sources"]["n_rebuilt_residues"] and r["sources"]["n_pose_clashes"] is None
    none = features_from_records(manifests=[_bm(), {}], pose_selection=None)
    assert none["n_rebuilt_residues"] is None and none["n_capped_breaks"] is None and none["n_pose_clashes"] is None
    assert features_from_records()["n_rebuilt_residues"] is None


def test_records_change_the_advice():
    f = A.CaseFeatures(resolution_a=1.8)
    plain = A.restraint_advice(f, "teaching")
    assert plain["strategy"] == "standard" and "pose_clash" in {x["key"] for x in plain["not_considered"]}
    g = A.features_with_records(f, manifests=[_bm(missing_residues_added=REBUILT)])
    adv = A.restraint_advice(g, "teaching")
    assert g.n_rebuilt_residues == 5 and adv["strategy"] == "gentle"
    reason = next(x for x in adv["items"] if x["key"] == "gaps")
    assert "5" in reason["text_all"]["zh"] and "5 residues" in reason["text_all"]["en"]
    assert f.n_rebuilt_residues is None                                                   # the original is not touched
    # read as 0: no reason, and the pose clash input (still unknown) stays listed
    z = A.features_with_records(f, manifests=[_bm(missing_residues_added={})])
    assert z.n_rebuilt_residues == 0 and A.restraint_advice(z, "teaching")["strategy"] == "standard"
    # capped breaks mean a gap in the chain
    c = A.features_with_records(f, manifests=[_bm(capped_breaks=[{"chain": "A"}])])
    assert c.has_gaps and A.restraint_advice(c, "teaching")["strategy"] == "gentle"
    # a clashing joint pose
    clash = [{"code": "geometry_repairable", "rule": "ligand_clash"}]
    p = A.features_with_records(A.CaseFeatures(n_ligands=2, docking_mode="simultaneous"), pose_selection=_sel(**_joint(rejections=clash)))
    assert p.n_pose_clashes == 1
    assert "pose_clash" in {x["key"] for x in A.restraint_advice(p, "teaching")["items"] if x["role"] == "reason"}
    # nothing readable: features unchanged, not_considered still lists it
    u = A.features_with_records(f, manifests=[_bm()], pose_selection=None)
    assert u == f


def test_adoption_entry_only_when_the_setting_equals_the_advice():
    f = A.features_with_records(A.CaseFeatures(resolution_a=1.8), manifests=[_bm(missing_residues_added=REBUILT)])
    e = A.adopted_restraint_entry(f, "teaching", {"restraints": "gentle"})
    assert e["choice"] == "gentle" and e["kind"] == "human" and "溫和" in e["why"]
    assert "gaps" in e["evidence"]["reasons"] and e["evidence"]["inputs"]["n_rebuilt_residues"] == 5
    assert A.adopted_restraint_entry(f, "teaching", {}) is None                       # not set: not adopted
    assert A.adopted_restraint_entry(f, "teaching", {"restraints": "standard"}) is None   # set to something else
    assert A.adopted_restraint_entry(f, "teaching", {"restraints": "hold_backbone"}) is None
    assert A.adopted_restraint_entry(A.CaseFeatures(resolution_a=1.8), "teaching", {"restraints": "gentle"}) is None


def _workflow(tmp_path, restraints=None):
    from md20.project.store import Project
    from md20.workflow import Workflow, example_config
    cfg = copy.deepcopy(example_config())
    if restraints is not None:
        cfg["md"]["restraints"] = restraints
    return Workflow(Project.create(tmp_path, "p"), cfg)


def _with_case(wf, manifest):
    from md20.util import atomic_write_json
    case = wf.project.new_case("c1")
    atomic_write_json(manifest, case.build_dir / "build_manifest.json")
    wf._mark("md_cases", cases={"docked_single": {"case_id": case.case_id, "status": "PASS"}})
    return case


def _rows(wf):
    return [r for r in wf.dec.read() if r["stage"] == "md.restraints"]


def test_workflow_writes_the_decision_when_the_advice_is_adopted(tmp_path):
    wf = _workflow(tmp_path, "gentle")
    _with_case(wf, _bm(missing_residues_added=REBUILT))
    assert wf._restraint_strategy() == "gentle"
    wf._restraint_strategy()                                                    # called once per case: no duplicate
    rows = _rows(wf)
    assert len(rows) == 1 and rows[0]["choice"] == "gentle" and rows[0]["kind"] == "human" and rows[0]["workflow"] == wf.name
    assert "溫和" in rows[0]["why"] and "gaps" in rows[0]["evidence"]["reasons"]
    assert rows[0]["evidence"]["inputs"]["n_rebuilt_residues"] == 5
    # a new Workflow object on the same project and state (a re-run) does not repeat it either
    from md20.workflow import Workflow
    Workflow(wf.project, wf.cfg)._restraint_strategy()
    assert len(_rows(wf)) == 1


def test_workflow_writes_nothing_when_the_advice_is_not_adopted(tmp_path):
    for i, setting in enumerate((None, "standard", "hold_backbone")):
        wf = _workflow(tmp_path / str(i), setting)
        _with_case(wf, _bm(missing_residues_added=REBUILT))                      # the advice here is gentle
        assert wf._restraint_strategy() == (setting or "standard")
        assert _rows(wf) == []
    # no record of a rebuild: the advice is standard, so "gentle" is not the advice and is not logged as adopted
    wf = _workflow(tmp_path / "x", "gentle")
    _with_case(wf, _bm())
    wf._restraint_strategy()
    assert _rows(wf) == []


def test_workflow_unreadable_records_stay_unknown(tmp_path):
    wf = _workflow(tmp_path)
    assert wf._restraint_features().n_rebuilt_residues is None and wf._restraint_features().n_pose_clashes is None
    _with_case(wf, {"status": "NEEDS_HUMAN"})
    assert wf._restraint_features().n_rebuilt_residues is None
