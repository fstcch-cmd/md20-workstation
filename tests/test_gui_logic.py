import pytest

from md20.gui.logic import parse_ligand_table, config_from_form, step_rows, set_pose_choice, list_workflows
from md20.project import Project
from md20.workflow import Workflow
from md20.util import atomic_write_json


def test_parse_ligands_and_form():
    ligs = parse_ligand_table("BEN NC(=[NH2+])c1ccccc1 BEN\n# comment\nphenol,Oc1ccccc1")
    assert ligs[0] == {"name": "BEN", "smiles": "NC(=[NH2+])c1ccccc1", "reference_resname": "BEN"}
    assert ligs[1]["name"] == "PHE"
    with pytest.raises(ValueError):
        parse_ligand_table("ABCx C\nABCy CC")            # same 3-char residue name
    cfg = config_from_form(name="t 1", pdb_id="3ptb", ligands_text="BEN NC(=[NH2+])c1ccccc1 BEN", box_residue="ben",
                           systems=["apo", "docked_single"], keep_hetero="ca, zn")
    assert cfg["receptor"] == {"pdb_id": "3PTB"} and cfg["box"] == {"from_residue": "BEN"} and cfg["keep_hetero"] == ["CA", "ZN"]
    assert cfg["binding"]["enabled"] and cfg["name"] == "t_1"
    with pytest.raises(ValueError):
        config_from_form(name="x", pdb_id="1abc", ligands_text="A C", mode="simultaneous")
    apo = config_from_form(name="apo", pdb_id="1abc", ligands_text="", systems=["apo", "docked_single"])
    assert apo["md"]["systems"] == ["apo"] and not apo["binding"]["enabled"]


def test_pose_override_invalidates_downstream(tmp_path):
    p = Project.create(tmp_path, "g")
    wf = Workflow(p, config_from_form(name="w", pdb_id="1abc", ligands_text="BEN C"))
    st = {"steps": {k: {"status": "PASS"} for k in ("receptor_input", "docking", "pose_selection", "md_cases", "md_runs", "analysis", "binding", "report")}}
    atomic_write_json(st, wf.state_path)
    set_pose_choice(wf, "BEN", 3)
    left = set(wf.state()["steps"])
    assert left == {"receptor_input", "docking"} and wf.cfg["pose_choices"] == {"BEN": 3}
    rows = step_rows(wf.state())
    assert [r["status"] for r in rows][:3] == ["PASS", "—", "PASS"]
    assert list_workflows(tmp_path)[0]["workflow"] == "w"


def test_gui_module_imports():
    pytest.importorskip("nicegui")
    import md20.gui.app as gapp
    assert callable(gapp.main)


def test_pose_table_shows_md_screen_verdicts(tmp_path):
    import copy
    from md20.gui.logic import pose_table
    from md20.project.store import Project
    from md20.util.jsonio import atomic_write_json
    from md20.workflow import Workflow, example_config
    wf = Workflow(Project.create(tmp_path, "p"), copy.deepcopy(example_config()))
    poses = [{"rank": r, "score": -8.0 + r * 0.1, "cluster": r, "cluster_size": 1, "contacts": 20, "rmsd_ref": None,
              "recommended": r == 1} for r in (1, 2)]
    atomic_write_json({"entries": [{"name": "BEN", "poses": poses, "reason": "r"}]}, wf.dir / "dock.json")
    wf._mark("docking", result=str(wf.dir / "dock.json"))
    atomic_write_json({"BEN": {"1": {"verdict": "UNSTABLE", "worst_tail_rmsd_A": 4.2}, "2": {"verdict": "STABLE", "worst_tail_rmsd_A": 1.1}}},
                      wf.dir / "pose_screen.json")
    rows = {r["rank"]: r for r in pose_table(wf)}
    assert rows[1]["md_screen"] == "不穩定（4.2 Å）" and rows[2]["md_screen"] == "穩定（1.1 Å）"
