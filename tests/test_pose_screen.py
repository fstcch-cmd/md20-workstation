"""WP5: short-MD pose screen — pure logic and choose_poses integration (no OpenMM)."""
import copy
from types import SimpleNamespace

import pytest

from md20.docking.pose_screen import (PoseScreenConfig, screen_candidates, assess_ligand, assess_pose, decide,
                                      STABLE, UNSTABLE, FAILED)
from md20.project.store import Project
from md20.workflow import Workflow, WorkflowBlocked, example_config

CFG = PoseScreenConfig(enabled=True)


def _entry():
    poses = [
        {"rank": 1, "score": -8.0, "cluster": 0, "cluster_size": 4, "rejected": []},
        {"rank": 2, "score": -7.9, "cluster": 0, "cluster_size": 4, "rejected": []},      # same mode as rank 1
        {"rank": 3, "score": -7.6, "cluster": 1, "cluster_size": 2, "rejected": []},
        {"rank": 4, "score": -7.5, "cluster": 2, "cluster_size": 3, "rejected": ["接觸 3 < 10（可能在表面）"]},
        {"rank": 5, "score": -7.4, "cluster": 3, "cluster_size": 1, "rejected": []},
    ]
    return {"name": "BEN", "ligands": ["BEN"], "smiles": "C", "poses": poses, "recommended_rank": 1,
            "reason": "第 1 名", "pose_sdfs": {"BEN": [f"p{i}.sdf" for i in range(1, 6)]}}


def _lig(rmsd, contacts):
    return {"rmsd_in_pocket_A": rmsd, "contact_residues": contacts}


STABLE_M = {"ligands": {"BEN": _lig([0, 0.8, 1.0, 1.1, 1.2, 1.0], [10, 10, 9, 9, 10, 9])}}
LEAVES_M = {"ligands": {"BEN": _lig([0, 2.0, 4.5, 7.0, 9.5, 12.0], [10, 8, 4, 2, 0, 0])}}


def test_candidates_recommended_first_one_per_cluster_skip_rejected():
    assert screen_candidates(_entry(), 3) == [1, 3, 5]     # rank 2 same cluster as 1; rank 4 rejected by docking rules
    assert screen_candidates(_entry(), 1) == [1]


def test_assess_ligand_stable_and_unstable():
    assert assess_ligand(STABLE_M["ligands"]["BEN"], CFG)["verdict"] == STABLE
    a = assess_ligand(LEAVES_M["ligands"]["BEN"], CFG)
    assert a["verdict"] == UNSTABLE and any("RMSD" in r for r in a["reasons"]) and any("保留率" in r for r in a["reasons"])
    assert assess_ligand(_lig([float("nan"), 1.0], [5, 5]), CFG)["verdict"] == FAILED


def test_joint_pose_needs_every_ligand_stable():
    m = {"ligands": {"A": STABLE_M["ligands"]["BEN"], "B": LEAVES_M["ligands"]["BEN"]}}
    assert assess_pose(m, ["A", "B"], CFG)["verdict"] == UNSTABLE
    assert assess_pose(m, ["A", "C"], CFG)["verdict"] == FAILED      # missing ligand in analysis → never a pass
    assert assess_pose(None, ["A"], CFG, error="boom")["verdict"] == FAILED


def test_decide_three_states():
    e = _entry()
    s, u = assess_pose(STABLE_M, ["BEN"], CFG), assess_pose(LEAVES_M, ["BEN"], CFG)
    d = decide(e, {1: s, 3: u}, CFG)
    assert d["status"] == "PASS" and d["rank"] == 1
    d = decide(e, {1: u, 3: s, 5: u}, CFG)
    assert d["status"] == "AUTO_FIXED" and d["rank"] == 3 and "自動改用" in d["why"]
    d = decide(e, {1: u, 3: u}, CFG)
    assert d["status"] == "NEEDS_HUMAN" and d["rank"] is None and d["options"]
    d = decide(e, {1: assess_pose(None, ["BEN"], CFG, error="NaN"), 3: s}, CFG)
    assert d["status"] == "NEEDS_HUMAN"            # recommended failed to simulate → do not quietly substitute


def test_default_enabled_only_for_research():
    assert PoseScreenConfig.from_cfg(None, tier="research").enabled
    assert not PoseScreenConfig.from_cfg(None, tier="teaching").enabled
    assert PoseScreenConfig.from_cfg({"enabled": True, "top_n": 2}, tier="classroom").top_n == 2


# ---------------------------------------------------------------- workflow integration with a fake simulator
def _wf(tmp_path, screen=True, choices=None):
    cfg = copy.deepcopy(example_config())
    cfg["docking"]["pose_md_screen"] = {"enabled": screen}
    cfg["pose_choices"] = choices or {}
    return Workflow(Project.create(tmp_path, "p"), cfg)


def _fake_screen(verdicts, calls):
    def f(e, r):
        calls.append(r)
        v = verdicts.get(r)
        if v == "PAUSE":
            return None
        return assess_pose(STABLE_M if v == STABLE else LEAVES_M, e["ligands"], CFG)
    return f


def test_choose_poses_switches_to_stable_pose(tmp_path):
    wf = _wf(tmp_path)
    calls = []
    sel = wf.choose_poses(SimpleNamespace(mode="independent", entries=[_entry()]),
                          screen=_fake_screen({1: UNSTABLE, 3: STABLE, 5: STABLE}, calls))
    assert calls == [1, 3, 5]
    assert sel["ligands"]["BEN"]["rank"] == 3 and sel["ligands"]["BEN"]["md_screen"]["status"] == "AUTO_FIXED"
    logged = wf.dec.by_stage("workflow.pose_screen")
    assert logged and "自動改用" in logged[-1]["why"]


def test_choose_poses_blocks_when_nothing_stable(tmp_path):
    wf = _wf(tmp_path)
    with pytest.raises(WorkflowBlocked, match="都不穩定"):
        wf.choose_poses(SimpleNamespace(mode="independent", entries=[_entry()]),
                        screen=_fake_screen({1: UNSTABLE, 3: UNSTABLE, 5: UNSTABLE}, []))


def test_pause_then_resume_uses_cache(tmp_path):
    wf = _wf(tmp_path)
    calls = []
    res = SimpleNamespace(mode="independent", entries=[_entry()])
    assert wf.choose_poses(res, screen=_fake_screen({1: STABLE, 3: "PAUSE"}, calls)) is None
    calls2 = []
    sel = wf.choose_poses(res, screen=_fake_screen({1: UNSTABLE, 3: STABLE, 5: STABLE}, calls2))
    assert calls2 == [3, 5]                    # rank 1 not re-simulated; its cached STABLE verdict is kept
    assert sel["ligands"]["BEN"]["rank"] == 1


def test_redock_invalidates_screen_cache(tmp_path):
    """After docking_results.json changes, rank 1 is a different pose: cached verdicts must not be reused."""
    from md20.util import atomic_write_json
    wf = _wf(tmp_path)
    res = SimpleNamespace(mode="independent", entries=[_entry()])
    dock_json = wf.dir / "docking" / "docking_results.json"
    atomic_write_json({"v": 1}, dock_json)
    wf._mark("docking", result=str(dock_json), mode="independent")
    calls = []
    wf.choose_poses(res, screen=_fake_screen({1: STABLE, 3: STABLE, 5: STABLE}, calls))
    assert calls
    wf.state()["steps"].pop("pose_selection")
    wf.cfg["pose_choices"] = {"X": 1}                            # changes the selection key so choose_poses runs again
    calls2 = []
    wf.choose_poses(res, screen=_fake_screen({1: STABLE, 3: STABLE, 5: STABLE}, calls2))
    assert calls2 == []                                          # same docking → cache used
    atomic_write_json({"v": 2}, dock_json)                       # re-dock
    wf.cfg["pose_choices"] = {"X": 2}
    calls3 = []
    wf.choose_poses(res, screen=_fake_screen({1: STABLE, 3: STABLE, 5: STABLE}, calls3))
    assert calls3 == calls                                       # everything re-simulated
    assert any(r["what"] == "cache" for r in wf.dec.read())


def test_user_choice_and_disabled_screen_skip_simulation(tmp_path):
    calls = []
    sel = _wf(tmp_path / "a", choices={"BEN": 5}).choose_poses(
        SimpleNamespace(mode="independent", entries=[_entry()]), screen=_fake_screen({}, calls))
    assert sel["ligands"]["BEN"]["rank"] == 5 and calls == []
    sel = _wf(tmp_path / "b", screen=False).choose_poses(
        SimpleNamespace(mode="independent", entries=[_entry()]), screen=_fake_screen({}, calls))
    assert sel["ligands"]["BEN"]["rank"] == 1 and calls == []
    with pytest.raises(WorkflowBlocked, match="模擬器"):
        _wf(tmp_path / "c").choose_poses(SimpleNamespace(mode="independent", entries=[_entry()]))
