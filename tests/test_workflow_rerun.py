"""Re-running a workflow must not lose human decisions nor reuse results that belong to a different case."""
import copy
import json

from md20.cli import main
from md20.gui.actions import apply_gate_action
from md20.project.store import Project
from md20.util import load_json, atomic_write_json
from md20.workflow import Workflow, merge_human_decisions, example_config


def test_merge_human_decisions_carries_gate_choices_only_when_new_config_lacks_them():
    new = example_config()
    old = copy.deepcopy(new)
    old["pose_choices"] = {"BEN": 3}
    old["human_choices"] = {"receptor": {"hetero": "remove"}}
    old["docking"]["skip_redock"] = True
    old["metal_policy"] = {"ZN:A:262": "bonded"}
    old["screen"] = {"select": ["c1"], "next_mode": "simultaneous"}
    old["ligands"][0]["cpp_override"] = "reason"
    merged, carried = merge_human_decisions(new, old)
    assert merged["pose_choices"] == {"BEN": 3} and merged["docking"]["skip_redock"] is True
    assert merged["metal_policy"] == {"ZN:A:262": "bonded"} and merged["screen"]["select"] == ["c1"]
    assert merged["ligands"][0]["cpp_override"] == "reason"
    assert set(carried) >= {"pose_choices", "docking.skip_redock", "metal_policy", "screen.select", "ligands[BEN].cpp_override"}
    # the student's file wins where it sets the key itself
    new2 = copy.deepcopy(new); new2["pose_choices"] = {"BEN": 1}
    m2, c2 = merge_human_decisions(new2, old)
    assert m2["pose_choices"] == {"BEN": 1} and "pose_choices" not in c2
    # unrelated keys from the old config never leak into the new one
    old["md"]["tier"] = "research"
    m3, _ = merge_human_decisions(new, old)
    assert m3["md"]["tier"] == "teaching"


def test_pipeline_run_keeps_decisions_written_by_gui(tmp_path, monkeypatch, capsys):
    """CLI reruns from the student's original file; the GUI had written pose_choices into the workflow config.json."""
    cfg = example_config()
    cfg["receptor"] = {"file": str(tmp_path / "missing.pdb")}
    f = tmp_path / "cfg.json"; f.write_text(json.dumps(cfg), encoding="utf-8")
    proj = Project.create(tmp_path / "projects", "P")
    wf = Workflow(proj, cfg)
    action = {"label": "docking.skip_redock: true", "patch": [{"path": ["docking", "skip_redock"], "value": True}],
              "from_step": "docking_preflight", "gate": "redocking"}
    apply_gate_action(wf, action)
    assert load_json(wf.dir / "config.json")["docking"]["skip_redock"] is True
    captured = {}

    def fake_run(self, *a, **k):
        captured["cfg"] = copy.deepcopy(self.cfg)
        return {"status": "COMPLETE", "report": ""}
    monkeypatch.setattr(Workflow, "run", fake_run)
    monkeypatch.setattr("md20.env.choose_platform", lambda: type("P", (), {"name": "CPU"})())
    rc = main(["--dir", str(tmp_path / "projects"), "pipeline", "run", str(f), "--project", "P", "--fake"])
    assert rc == 0
    assert captured["cfg"]["docking"]["skip_redock"] is True                # not clobbered by the original file
    assert load_json(wf.dir / "config.json")["docking"]["skip_redock"] is True
    assert "沿用" in capsys.readouterr().out


def test_workflow_init_does_not_rewrite_identical_config(tmp_path):
    cfg = example_config()
    proj = Project.create(tmp_path, "P")
    wf = Workflow(proj, cfg)
    p = wf.dir / "config.json"
    m = p.stat().st_mtime_ns
    Workflow(proj, json.loads(p.read_text(encoding="utf-8")))
    assert p.stat().st_mtime_ns == m
    import pytest
    with pytest.raises(FileNotFoundError):
        Workflow.open(proj, "nope")
    assert not (proj.dir / "workflows" / "nope").exists()


def test_metal_params_none_means_geometric_model(tmp_path):
    cfg = example_config()
    cfg["metal_params"] = {"ZN:A:262": None, "FE:B:1": {"file": "fe.json"}}
    wf = Workflow(Project.create(tmp_path, "P"), cfg)
    mp = wf._metal_params()
    assert set(mp) == {"FE:B:1"} and mp["FE:B:1"]["file"].endswith("fe.json")
    cfg["metal_params"] = {"ZN:A:262": None}
    assert Workflow(Project.create(tmp_path / "b", "P"), cfg)._metal_params() == {}


def test_run_md_does_not_reuse_runs_of_another_case(tmp_path, monkeypatch):
    cfg = example_config()
    wf = Workflow(Project.create(tmp_path, "P"), cfg)
    wf._mark("md_runs", runs={"docked_BEN": {"case_id": "old_case", "status": "COMPLETE", "run_ids": ["r1"]}})
    called = []
    monkeypatch.setattr("md20.engine.run_replicas", lambda case, proto, fac, **k: (called.append(case.case_id) or
                        {"runs": [{"status": "COMPLETE", "run_id": "r9"}]}))
    monkeypatch.setattr("md20.engine.make_protocol", lambda *a, **k: type("Pr", (), {"stages": [], "replicas": 1})())
    new_case = wf.project.new_case("docked_new")
    runs = wf.run_md({"docked_BEN": {"case_id": new_case.case_id}}, lambda c, p: None)
    assert called == [new_case.case_id]
    assert runs["docked_BEN"]["case_id"] == new_case.case_id and runs["docked_BEN"]["run_ids"] == ["r9"]
    assert any(r["choice"] == "rebuilt case" for r in wf.dec.read())
    # unchanged case → reused, no new run
    called.clear()
    wf.run_md({"docked_BEN": {"case_id": new_case.case_id}}, lambda c, p: None)
    assert called == []


def test_fetch_pdb_rejects_truncated_or_html(tmp_path, monkeypatch):
    import io
    from md20.workflow import fetch_pdb

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
    body = {"b": b"<html>rate limited</html>"}
    monkeypatch.setattr("md20.workflow.urllib.request.urlopen", lambda req, timeout=0: Resp(body["b"]))
    dst = tmp_path / "1ABC.pdb"
    import pytest
    with pytest.raises(RuntimeError):
        fetch_pdb("1ABC", dst)
    assert not dst.exists() and not list(tmp_path.glob("*.part"))
    body["b"] = b"ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N\n"       # cut off: no END
    with pytest.raises(RuntimeError):
        fetch_pdb("1ABC", dst)
    body["b"] += b"END\n"
    assert fetch_pdb("1ABC", dst) == dst and dst.read_text().endswith("END\n")


def test_bad_pdb_id_blocks(tmp_path):
    from md20.workflow import WorkflowBlocked
    cfg = example_config(); cfg["receptor"] = {"pdb_id": "../x"}
    wf = Workflow(Project.create(tmp_path, "P"), cfg)
    import pytest
    with pytest.raises(WorkflowBlocked, match="PDB ID"):
        wf.fetch_receptor()
