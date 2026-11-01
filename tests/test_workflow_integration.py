"""Full workflow on 3PTB (docking → apo + docked MD → analysis → SMD/umbrella → report).

Heavy: runs only when MD20_HEAVY=1 (CI ubuntu job) and the full chemistry stack is installed.
"""
import os
from pathlib import Path

import pytest

if os.environ.get("MD20_HEAVY") != "1":
    pytest.skip("set MD20_HEAVY=1 to run the full workflow test", allow_module_level=True)
pytest.importorskip("openmm"); pytest.importorskip("openff.toolkit"); pytest.importorskip("mdtraj")

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
    # PBC re-centering: every analysed run ships a centred DCD and the apparent-vs-true dissociation check
    for key, summ in st["analysis"]["summaries"].items():
        cen = summ.get("centered") or {}
        assert cen.get("centered_dcd") and Path(cen["centered_dcd"]).is_file() and cen["n_frames"] > 0, (key, cen)
        if key != "apo":
            # keyed by the assembled ligand residue name (L01…), not the input name (BEN) — CI f140a49, D-28
            checks = summ.get("pbc_checks") or {}
            assert checks and all(c["true_nm"] < 1.0 for c in checks.values()), checks
    b = out["binding"]["BEN"]
    assert b["status"] == "PASS" and b["delta_pmf_kj_mol"] is not None
    html = Path(out["report"]).read_text(encoding="utf-8")
    assert "分子對接" in html and "ΔPMF" in html and "apo" in html
    assert "md20Mount" in html and "production 軌跡" in html      # WP13: offline 3D trajectory embedded in the report
    # idempotent re-run: everything is skipped
    out2 = wf.run(lambda case, proto: make_backend_factory(case, proto, platform=platform), platform)
    assert out2["status"] == "COMPLETE"


def test_pose_md_screen_3ptb(pdb_3ptb, tmp_path):
    """WP5 on the real stack: docking → short-MD screen of candidate poses → docked MD → analysis with ligand groups."""
    import json
    from md20.workflow import WorkflowBlocked
    cfg = example_config()
    cfg["name"] = "screen"
    cfg["receptor"] = {"file": str(pdb_3ptb)}
    cfg["docking"].update({"exhaustiveness": 4, "n_poses": 5,
                           "pose_md_screen": {"enabled": True, "top_n": 2, "nvt_ps": 2.0, "npt_ps": 2.0,
                                              "production_ps": 10.0, "frame_interval_ps": 0.5}})
    short = {"length_ps": 4.0, "checkpoint_interval_ps": 2.0, "report_interval_ps": 0.2, "trajectory_interval_ps": 0.5, "accept": {}}
    cfg["md"] = {"systems": ["docked_single"], "tier": "classroom", "production_ns": 0.006, "padding_nm": 0.8, "replicas": 1,
                 "stage_overrides": {"minimize": {"max_iterations": 300}, "nvt": short, "npt": short,
                                     "production": {**short, "length_ps": 6.0, "checkpoint_interval_ps": 3.0}}}
    cfg["binding"] = {"enabled": False}
    wf = Workflow(Project.create(tmp_path, "wf"), cfg)
    platform = choose_platform(probe_steps=20)
    try:
        out = wf.run(lambda case, proto: make_backend_factory(case, proto, platform=platform), platform)
    except WorkflowBlocked as exc:          # all poses genuinely unstable is a legitimate gate outcome, not a crash
        assert "都不穩定" in str(exc), str(exc)
        out = None
    cache = json.loads((wf.dir / "pose_screen.json").read_text(encoding="utf-8"))["BEN"]
    assert cache, "screen produced no verdicts"
    assert all(v["verdict"] in ("STABLE", "UNSTABLE") for v in cache.values()), cache   # FAILED = machinery broken
    if out is not None:
        assert out["status"] == "COMPLETE"
        sel = wf.state()["steps"]["pose_selection"]["selection"]["ligands"]["BEN"]
        assert sel["md_screen"]["status"] in ("PASS", "AUTO_FIXED")
        summ = wf.state()["steps"]["analysis"]["summaries"]["docked_BEN"]
        metrics = json.loads(Path(summ["metrics_file"]).read_text(encoding="utf-8"))
        assert "L01" in metrics["ligands"]          # manifest atom indices reached the analysis (regression a72ba6b)
