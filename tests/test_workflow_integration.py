"""Full workflow on 3PTB (docking → apo + docked MD → analysis → SMD/umbrella → report).

Heavy: runs only when MD20_HEAVY=1 (CI ubuntu job) and the full chemistry stack is installed.
"""
import os
from pathlib import Path

import pytest

if os.environ.get("MD20_HEAVY") != "1":
    pytest.skip("set MD20_HEAVY=1 to run the full workflow test", allow_module_level=True)
pytest.importorskip("vina"); pytest.importorskip("openmm"); pytest.importorskip("openff.toolkit"); pytest.importorskip("mdtraj")

from md20.project import Project
from md20.workflow import Workflow, example_config
from md20.engine.factory import make_backend_factory
from md20.env import choose_platform


def test_full_workflow_3ptb(pdb_3ptb, tmp_path):
    cfg = example_config()
    cfg["receptor"] = {"file": str(pdb_3ptb)}
    cfg["docking"].update({"exhaustiveness": 4, "n_poses": 5})
    short = {"length_ps": 6.0, "checkpoint_interval_ps": 3.0, "report_interval_ps": 0.2, "trajectory_interval_ps": 0.5, "accept": {}}
    cfg["md"] = {"systems": ["apo", "docked_single"], "tier": "classroom", "production_ns": 0.01, "padding_nm": 0.8, "replicas": 1,
                 "stage_overrides": {"minimize": {"max_iterations": 300}, "nvt": short, "npt": short,
                                     "production": {**short, "length_ps": 10.0, "checkpoint_interval_ps": 5.0}}}
    cfg["binding"] = {"enabled": True, "ligands": ["BEN"],
                      "config": {"pull_distance_nm": 0.6, "pull_velocity_nm_per_ps": 0.05, "k_umbrella": 1500.0,
                                 "window_equil_ps": 1.0, "window_prod_ps": 5.0, "sample_every_steps": 25, "max_windows": 12}}
    proj = Project.create(tmp_path, "wf")
    wf = Workflow(proj, cfg)
    platform = choose_platform(probe_steps=20)
    out = wf.run(lambda case, proto: make_backend_factory(case, proto, platform=platform), platform)
    assert out["status"] == "COMPLETE", wf.state()
    st = wf.state()["steps"]
    assert st["pose_selection"]["selection"]["ligands"]["BEN"]["rank"] >= 1
    assert set(st["md_runs"]["runs"]) == {"apo", "docked_BEN"}
    assert st["analysis"]["comparison"]["figures"]["compare"]
    b = out["binding"]["BEN"]
    assert b["status"] == "PASS" and b["delta_pmf_kj_mol"] is not None
    html = Path(out["report"]).read_text(encoding="utf-8")
    assert "分子對接" in html and "ΔPMF" in html and "apo" in html
    # idempotent re-run: everything is skipped
    out2 = wf.run(lambda case, proto: make_backend_factory(case, proto, platform=platform), platform)
    assert out2["status"] == "COMPLETE"
