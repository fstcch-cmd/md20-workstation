"""D-87: choose which ligand to pull (also in the all-ligands system), add ligands or one more SMD run after the report,
keep finished targets, combine the runs in the report, and find saved workflows again after the GUI was closed."""
import json

import pytest

from md20.gui import actions as ACT
from md20.gui.logic import config_from_mode, list_workflows
from md20.project import Project
from md20.util import atomic_write_json
from md20.workflow import Workflow, binding_replica_dir


def _wf(tmp_path, binding=None):
    cfg = {"name": "w", "receptor": {"pdb_id": "1VKX"}, "ligands": [{"name": n, "smiles": "CCO"} for n in ("PGA", "CAR", "GLU")],
           "md": {"systems": ["apo", "docked_multi"]}, "binding": binding or {"enabled": False, "ligands": ["PGA"]}}
    wf = Workflow(Project.create(tmp_path, "p"), cfg)
    st = wf.state()
    st["steps"]["md_cases"] = {"status": "PASS", "cases": {
        "apo": {"case_id": "c0", "mode": "apo", "ligands": []},
        "docked_multi": {"case_id": "c1", "mode": "docked_multi", "ligands": ["PGA", "CAR", "GLU"]}}}
    st["steps"]["md_runs"] = {"status": "PASS", "runs": {"apo": {"status": "COMPLETE"}, "docked_multi": {"status": "COMPLETE"}}}
    st["steps"]["report"] = {"status": "PASS", "path": str(tmp_path / "r.html")}
    atomic_write_json(st, wf.state_path)
    return wf


def _built(wf):
    return wf.state()["steps"]["md_cases"]["cases"]


def test_teaching_multi_disabled_then_add_one_ligand(tmp_path):
    wf = _wf(tmp_path)
    runs = wf.state()["steps"]["md_runs"]["runs"]
    assert wf._binding_targets(runs, _built(wf))[0] == []            # hsieh2024 default: binding off
    cands = {c["target"]: c for c in ACT.binding_candidates(wf)}
    assert set(cands) == {"multi:PGA", "multi:CAR", "multi:GLU"} and cands["multi:CAR"]["co_ligands"] == ["PGA", "GLU"]
    ACT.add_binding_targets(wf, ["multi:CAR"], note="lesson")
    targets, ctx = wf._binding_targets(runs, _built(wf))
    assert [t["key"] for t in targets] == ["multi:CAR"] and targets[0]["others"] == ["PGA", "GLU"]
    st = wf.state()["steps"]
    assert "report" not in st                                          # only the report is reopened
    assert json.loads((wf.dir / "config.json").read_text(encoding="utf-8"))["binding"]["added"] == ["multi:CAR"]


def test_finished_target_kept_and_one_more_run(tmp_path):
    wf = _wf(tmp_path, {"enabled": True, "ligands": ["PGA"], "multi": True})
    st = wf.state()
    st["steps"]["binding"] = {"status": "PASS", "results": {"multi:PGA": {"status": "PASS", "replicas": 1,
                                                                         "dG_standard_kj_mol": -12.0}}}
    atomic_write_json(st, wf.state_path)
    ACT.add_binding_targets(wf, ["multi:GLU"])
    b = wf.state()["steps"]["binding"]
    assert b["status"] == "PENDING" and b["results"]["multi:PGA"]["status"] == "PASS"       # kept, not recomputed
    r = ACT.add_smd_run(wf, "multi:PGA")
    assert r["runs"] == 2 and wf.cfg["binding"]["target_replicas"] == {"multi:PGA": 2}
    with pytest.raises(ValueError):
        ACT.add_smd_run(wf, "multi:CAR")                                # nothing finished yet
    with pytest.raises(ValueError):
        ACT.add_binding_targets(wf, ["multi:XXX"])


def test_replica_dirs_keep_the_first_run_in_place(tmp_path):
    base = tmp_path / "multi_PGA"
    assert binding_replica_dir(base, 0, 1) == base
    assert binding_replica_dir(base, 0, 2) == base / "rep1"             # planned with two runs from the start
    base.mkdir(); (base / "binding_manifest.json").write_text("{}")
    assert binding_replica_dir(base, 0, 2) == base                      # ran once, then one more was added
    assert binding_replica_dir(base, 1, 2) == base / "rep2"


def test_form_binding_choice_for_multi_system():
    vals = {"binding": True}
    cfg = config_from_mode(mode="quick", name="x", values=vals, pdb_id="1VKX", ligands_text="PGA CCO\nCAR CCN\nGLU CCC",
                           systems=["apo", "docked_multi"])
    assert cfg["binding"]["enabled"] and cfg["binding"]["ligands"] == ["PGA"] and cfg["binding"]["multi"]
    cfg = config_from_mode(mode="quick", name="x", values=vals, pdb_id="1VKX", ligands_text="PGA CCO\nCAR CCN",
                           systems=["apo", "docked_multi"], binding_ligands=["CAR"])
    assert cfg["binding"]["ligands"] == ["CAR"]
    cfg = config_from_mode(mode="quick", name="x", values=vals, pdb_id="1VKX", ligands_text="PGA CCO\nCAR CCN",
                           systems=["apo", "docked_single"])
    assert cfg["binding"]["ligands"] == ["PGA", "CAR"] and not cfg["binding"]["multi"]


def test_saved_workflows_listed_newest_first(tmp_path):
    for name, t, done in (("old", "2026-11-01T00:00:00+00:00", True), ("new", "2026-11-03T00:00:00+00:00", False)):
        w = tmp_path / "proj" / "workflows" / name
        w.mkdir(parents=True)
        (w / "config.json").write_text("{}")
        steps = {"report": {"status": "PASS", "path": str(w / "r.html"), "at": t}} if done else \
                {"md_runs": {"status": "PASS", "at": t}}
        if done:
            (w / "r.html").write_text("x")
        (w / "state.json").write_text(json.dumps({"steps": steps, "updated_at": t}))
        if not done:
            (w / "running.json").write_text(json.dumps({"pid": 999999999}))      # owner gone: interrupted
    rows = list_workflows(tmp_path)
    assert [r["workflow"] for r in rows] == ["new", "old"]
    assert rows[0]["status"] == "INCOMPLETE" and rows[0]["interrupted"]
    assert rows[1]["status"] == "COMPLETE" and rows[1]["has_report"]
