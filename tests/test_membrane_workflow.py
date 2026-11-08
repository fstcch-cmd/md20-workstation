"""Membrane cases B (surface) and C (bilayer) in the workflow, and the membrane acceptance as analysis (pure; the real
build and MD run in CI through tests/test_membrane_integration.py)."""
import copy
import json
from types import SimpleNamespace

import numpy as np
import pytest

from md20.project.store import Project
from md20.util.jsonio import atomic_write_json, load_json
from md20.workflow import Workflow, WorkflowBlocked, example_config, merge_human_decisions


def _cfg(mtype, ligands):
    cfg = copy.deepcopy(example_config())
    cfg["name"] = f"mem_{mtype}"
    cfg["receptor"] = {}
    cfg["ligands"] = ligands
    cfg["binding"] = {"enabled": False, "ligands": [], "config": {}}
    cfg["md"]["membrane"] = {"type": mtype, "lipids": "mammalian"}
    return cfg


@pytest.fixture
def fake_build(monkeypatch):
    calls = []

    def build(out_dir, membrane, *, ligands=None, decisions=None, **kw):
        from md20.build.assemble import BuildResult
        calls.append({"membrane": membrane, "ligands": [getattr(l, "name", None) for l in ligands or []], "kw": kw})
        res = BuildResult(status="PASS", system_xml=str(out_dir / "system.xml"), topology_pdb=str(out_dir / "topology.pdb"),
                          n_atoms=30000)
        atomic_write_json({**res.to_dict(), "membrane": {"head_atom_indices": [0, 1]}}, out_dir / "build_manifest.json")
        return res
    monkeypatch.setattr("md20.build.membrane.build_membrane_system", build)

    def pep(seq, pose, out_dir, *, name="P01", chain_id="P", termini="charged", decisions=None):
        return SimpleNamespace(status="PASS", name=name, pose=pose, gates={"gates": []})
    monkeypatch.setattr("md20.build.peptide.prepare_peptide", pep)
    return calls


def test_bilayer_builds_one_system_without_receptor(tmp_path, fake_build):
    wf = Workflow(Project.create(tmp_path, "p"), _cfg("bilayer", []))
    assert wf.membrane_only_type() == "bilayer"
    built = wf.build_membrane_cases()
    assert list(built) == ["bilayer"] and built["bilayer"]["mode"] == "membrane_bilayer"
    assert fake_build[0]["ligands"] == [] and fake_build[0]["membrane"]["type"] == "bilayer"
    bm = load_json(wf.project.case(built["bilayer"]["case_id"]).build_dir / "build_manifest.json", {})
    assert bm["assembly"]["n_atoms"] == 30000                 # same layout as build_case for the readers
    rows = wf.dec.read()
    assert any(r["stage"] == "workflow.membrane" and "純膜" in r["why"] for r in rows)
    built2 = wf.build_membrane_cases()                         # done: not rebuilt
    assert built2 == built and len(fake_build) == 1


def test_surface_builds_one_system_per_solute(tmp_path, fake_build):
    ligs = [{"name": "PEP", "sequence": "KLAKLAKKLAKLAK"}, {"name": "LIG", "smiles": "CCO"}]
    wf = Workflow(Project.create(tmp_path, "p"), _cfg("surface", ligs))
    import md20.build.ligand as BL
    BL_prepare = BL.prepare_ligand
    try:
        BL.prepare_ligand = lambda ref, pose, out, name="L01", decisions=None: SimpleNamespace(status="PASS", name=name, gates={})
        built = wf.build_membrane_cases()
    finally:
        BL.prepare_ligand = BL_prepare
    assert set(built) == {"surface_PEP", "surface_LIG"}
    assert [c["ligands"] for c in fake_build] == [["PEP"], ["L01"]]
    assert built["surface_LIG"]["ligand_map"] == {"LIG": "L01"} and built["surface_PEP"]["ligand_map"] == {"PEP": "PEP"}


@pytest.mark.parametrize("mtype,ligs,receptor,word", [
    ("surface", [], {}, "沒有配體"),
    ("bilayer", [{"name": "LIG", "smiles": "CCO"}], {}, "純膜"),
    ("surface", [{"name": "LIG", "smiles": "CCO"}], {"pdb_id": "3PTB"}, "不使用受體"),
    ("surface", [{"name": "PEP", "sequence": "KLAKLAK", "fold": "complex"}], {}, "fold: complex"),
])
def test_inputs_that_do_not_fit_stop_with_options(tmp_path, fake_build, mtype, ligs, receptor, word):
    cfg = _cfg(mtype, ligs)
    cfg["receptor"] = receptor
    wf = Workflow(Project.create(tmp_path, "p"), cfg)
    with pytest.raises(WorkflowBlocked, match=word):
        wf.build_membrane_cases()
    g = wf.state()["steps"]["md_cases"]["gates"][0]
    assert g["name"] == "membrane type" and g["options"]
    assert not fake_build


def test_failed_membrane_build_blocks_with_the_gates(tmp_path, monkeypatch):
    from md20.build.assemble import BuildResult

    def build(out_dir, membrane, **kw):
        res = BuildResult(status="NEEDS_HUMAN", gates={"gates": [{"name": "membrane phase", "status": "NEEDS_HUMAN",
                                                                  "explanation": "凝膠相", "options": ["md.membrane.temperature_k: 324"]}]})
        atomic_write_json(res.to_dict(), out_dir / "build_manifest.json")
        return res
    monkeypatch.setattr("md20.build.membrane.build_membrane_system", build)
    wf = Workflow(Project.create(tmp_path, "p"), _cfg("bilayer", []))
    with pytest.raises(WorkflowBlocked, match="凝膠相"):
        wf.build_membrane_cases()
    from md20.gui.views import gate_cards
    cards = gate_cards(wf, lang="en")
    assert any(c["title"] == "membrane phase" for c in cards)


def test_run_goes_through_the_membrane_path_without_receptor(tmp_path, fake_build, monkeypatch):
    wf = Workflow(Project.create(tmp_path, "p"), _cfg("bilayer", []))
    seen = []
    monkeypatch.setattr(Workflow, "fetch_receptor", lambda self: pytest.fail("no receptor for a bilayer"))
    monkeypatch.setattr(Workflow, "run_md", lambda self, built, mf, **kw: seen.append("md") or {k: {"status": "COMPLETE"} for k in built})
    monkeypatch.setattr(Workflow, "analyse", lambda self, runs: seen.append("analysis") or {})
    monkeypatch.setattr("md20.report.workflow_report.build_workflow_report", lambda wf: tmp_path / "r.html")
    out = wf._run(lambda c, p: None, None)
    assert out["status"] == "COMPLETE" and seen == ["md", "analysis"]


def test_binding_stays_blocked_for_membrane_only(tmp_path, fake_build):
    cfg = _cfg("surface", [{"name": "PEP", "sequence": "KLAKLAKKLAKLAK"}])
    cfg["binding"] = {"enabled": True, "ligands": ["PEP"], "config": {}}
    wf = Workflow(Project.create(tmp_path, "p"), cfg)
    with pytest.raises(WorkflowBlocked):
        wf.binding({}, {}, None)
    assert wf.state()["steps"]["binding"]["gates"][0]["name"] == "membrane binding"


def test_long_run_reads_atom_count_from_the_assembly_record(tmp_path):
    from md20.engine import make_protocol
    cfg = copy.deepcopy(example_config()); cfg["md"].update({"production_ns": 2000, "ns_per_day": 300})
    wf = Workflow(Project.create(tmp_path, "p"), cfg)
    b = tmp_path / "case" / "build"; b.mkdir(parents=True)
    # build_case() layout: counts only under "assembly"
    (b / "build_manifest.json").write_text(json.dumps({"status": "PASS", "assembly": {"n_atoms": 32000, "n_protein_atoms": 3200}}))
    case = SimpleNamespace(case_id="c1", build_dir=b, dir=tmp_path / "case")
    with pytest.raises(WorkflowBlocked, match="1 µs"):          # the plan's own gate, not "build 沒有原子數"
        wf._plan_long_run("apo", case, make_protocol("teaching", production_ns=2000), {})


def test_oriented_choice_is_kept_on_rerun():
    new = {"md": {"membrane": {"type": "protein"}}}
    old = {"md": {"membrane": {"type": "protein", "oriented": True}}}
    merged, carried = merge_human_decisions(new, old)
    assert merged["md"]["membrane"]["oriented"] is True and "md.membrane.oriented" in carried


def test_confirm_message_for_predicted_complex(tmp_path):
    cfg = copy.deepcopy(example_config()); cfg["confirm_before_md"] = True
    wf = Workflow(Project.create(tmp_path, "p"), cfg)
    with pytest.raises(WorkflowBlocked) as e:
        wf.confirm_md({"ligands": {"PEP": {"rank": 1, "score": None}, "BEN": {"rank": 1, "score": -6.1}}})
    assert "預測複合物，沒有對接分數" in str(e.value) and "None" not in str(e.value) and "-6.1 kcal/mol" in str(e.value)


# ---------------------------------------------------------------------------- acceptance on synthetic coordinates
def _bilayer(F=6, n=64, apl=0.643, dpp=3.70, core_water=0, seed=1):
    rng = np.random.default_rng(seed)
    L = np.sqrt(n * apl)
    up = np.c_[rng.uniform(0, L, (n, 2)), np.full(n, 5 + dpp / 2)]
    lo = np.c_[rng.uniform(0, L, (n, 2)), np.full(n, 5 - dpp / 2)]
    heads = np.r_[up, lo]
    water = np.c_[rng.uniform(0, L, (200, 2)), rng.choice([1.0, 9.0], 200)]
    water[:core_water, 2] = 5.0
    pep = np.c_[np.full(5, L / 2), np.full(5, L / 2), 5 + dpp / 2 + 1.0 + np.arange(5) * 0.1]
    xyz = np.r_[heads, water, pep]
    X = np.repeat(xyz[None], F, 0) + rng.normal(0, 0.01, (F, len(xyz), 3))
    box = np.tile([L, L, 10.0], (F, 1))
    idx = {"head": list(range(2 * n)), "water": list(range(2 * n, 2 * n + 200)), "pep": list(range(2 * n + 200, len(xyz)))}
    return X, box, idx


def test_membrane_summary_passes_a_fluid_popc_bilayer():
    from md20.analysis.membrane_run import membrane_summary
    from md20.build.membrane import reference_values
    X, box, idx = _bilayer()
    s = membrane_summary(X, box, head_idx=idx["head"], water_o_idx=idx["water"], solute_groups={"PEP": idx["pep"]},
                         reference=reference_values({"POPC": 1.0}))
    assert s["acceptance"]["status"] == "PASS" and abs(s["apl_mean_nm2"] - 0.643) < 0.01
    assert abs(s["dpp_mean_nm"] - 3.70) < 0.02
    assert -1.3 < s["insertion"]["PEP"]["mean_com_depth_nm"] < -1.0 and not s["insertion"]["PEP"]["crossed_centre"]


def test_membrane_summary_failed_acceptance_is_a_notice_not_a_stop():
    from md20.analysis.membrane_run import membrane_summary
    from md20.build.membrane import reference_values
    X, box, idx = _bilayer(core_water=20)
    s = membrane_summary(X, box, head_idx=idx["head"], water_o_idx=idx["water"], reference=reference_values({"POPC": 1.0}))
    g = s["acceptance"]
    assert g["status"] == "AUTO_FIXED" and g["advisory"] and "core_water" in g["explanation"] and "沒有自動延長" in g["explanation"]


def test_membrane_summary_without_water_says_not_checked():
    from md20.analysis.membrane_run import membrane_summary
    X, box, idx = _bilayer()
    s = membrane_summary(X, box, head_idx=idx["head"], water_o_idx=[], reference={})
    assert s["acceptance"]["advisory"] and s["acceptance"]["evidence"]["checked"] is False


def test_failed_acceptance_becomes_a_gate_card(tmp_path, monkeypatch):
    wf = Workflow(Project.create(tmp_path, "p"), _cfg("bilayer", []))
    case = wf.project.new_case("c")
    case.build_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json({"topology_pdb": "t.pdb"}, case.build_dir / "build_manifest.json")
    acc = {"name": "membrane equilibration", "status": "AUTO_FIXED", "advisory": True, "explanation": "未通過", "options": []}

    def fake(run_dir, bm, label="", decisions=None, **kw):
        (run_dir / "analysis").mkdir(parents=True, exist_ok=True)
        atomic_write_json({"n_frames": 3}, run_dir / "analysis" / "metrics.json")
        return {"status": "PASS", "metrics_file": str(run_dir / "analysis" / "metrics.json"), "membrane_acceptance": acc}
    monkeypatch.setattr("md20.analysis.membrane_run.membrane_only_analysis", fake)
    out = wf.analyse({"bilayer": {"case_id": case.case_id, "run_ids": ["r1"]}})
    assert out["summaries"]["bilayer"]["membrane_acceptance"]["status"] == "AUTO_FIXED"
    from md20.gui.views import gate_cards
    assert any(c["title"] == "membrane equilibration" and c["advisory"] for c in gate_cards(wf, lang="en"))


def test_report_summary_from_a_trajectory_like_object(tmp_path):
    """The report's schema (analysis/membrane_report.py) is written from the loaded trajectory."""
    from md20.analysis.membrane_run import _report_summary
    X, box, idx = _bilayer()
    chain = SimpleNamespace(index=0)
    atoms = []
    for i in range(X.shape[1]):
        pep = i in idx["pep"]
        res = SimpleNamespace(name="LYS" if pep else ("HOH" if i in idx["water"] else "POPC"), index=1000 + i if pep else i,
                              resSeq=i, chain=chain)
        atoms.append(SimpleNamespace(index=i, name="CA" if pep else "P", residue=res))
    traj = SimpleNamespace(xyz=X, unitcell_lengths=box, time=np.arange(len(X)) * 100.0, topology=SimpleNamespace(atoms=atoms))
    p = _report_summary(traj, tmp_path, idx["head"], idx["water"], {"PEP": idx["pep"]},
                        {"type": "surface", "composition": {"upper": {"POPC": 1.0}}, "temperature_k": 310.0})
    s = load_json(p, {})
    assert s["type"] == "surface" and len(s["apl_nm2"]) == len(X) and "insertion" in s and s["headgroup_contacts"]
    assert s["reference"]["apl_nm2"] == pytest.approx(0.643) and "tilt_deg" in s and "water" in s["density"]["groups"]
