"""D-98 (A7): docking rejections carry a reason code; the least-risk fallback (D-78) only takes poses whose every
rejection is geometry the build can repair and verify — a co-occupancy or model rejection can never be cleared by it."""
import types

import numpy as np
import pytest

from md20.docking.poses import (PoseInfo, recommend_pose, classify_rejections, GEOMETRY_REPAIRABLE, MODEL_LIMITATION,
                                HYPOTHESIS_CHANGE)
from md20.workflow import WorkflowBlocked
from test_workflow_gates import _wf, _sdf


def _joint(rank, score, d, contacts=(20, 20)):
    return PoseInfo(rank=rank, score=score, contacts=sum(contacts), contacts_per_ligand=list(contacts), min_ll_distance=d)


def test_each_rule_has_its_code():
    kw = dict(best=-10.0, score_window=1.0, min_contacts=10, ll_min=3.3, ll_max=4.5)
    assert [c["code"] for c in classify_rejections(_joint(1, -10.0, 2.0), **kw)] == [GEOMETRY_REPAIRABLE]
    assert [c["code"] for c in classify_rejections(_joint(1, -10.0, 6.0), **kw)] == [HYPOTHESIS_CHANGE]
    assert [c["code"] for c in classify_rejections(_joint(1, -10.0, 4.0, (20, 3)), **kw)] == [HYPOTHESIS_CHANGE]
    assert [c["code"] for c in classify_rejections(_joint(1, -8.0, 4.0), **kw)] == [MODEL_LIMITATION]
    single = PoseInfo(rank=1, score=-10.0, contacts=4)
    assert [c["rule"] for c in classify_rejections(single, **kw)] == ["surface_pose"]


def test_recommend_pose_writes_codes_aligned_with_text_and_entry_level_codes():
    infos = [_joint(1, -10.0, 2.0), _joint(2, -9.8, 6.0)]
    assert recommend_pose(infos) is None
    for i in infos:
        assert [c["text"] for c in i.rejection_codes] == i.rejected
        assert "rejection_codes" in i.to_dict()
    assert infos[0].extra["recommendation"]["rule"] == "no_candidate"
    small = [_joint(1, -10.0, 4.0)]
    assert recommend_pose(small, pocket_volume_A3=100.0, ligand_volume_A3=200.0) is None
    assert small[0].extra["recommendation"]["code"] == HYPOTHESIS_CHANGE


def _entry(tmp_path, poses, **extra):
    ang = np.linspace(0, 2 * np.pi, 7)[:-1]
    ring = np.c_[1.39 * np.cos(ang), 1.39 * np.sin(ang), np.zeros(6)]
    n = len(poses)
    sd = {"A": [_sdf(tmp_path / f"a{k}.sdf", ring) for k in range(n)],
          "B": [_sdf(tmp_path / f"b{k}.sdf", ring + [0, 0, 1.9 + k]) for k in range(n)]}
    return {"name": "joint", "ligands": ["A", "B"], "smiles": {"A": "c1ccccc1", "B": "c1ccccc1"}, "poses": poses,
            "pose_sdfs": sd, "recommended_rank": None, "reason": "沒有任何 pose 通過保守條件，不自動選擇。", **extra}


def _pose(rank, score, *codes):
    texts = {GEOMETRY_REPAIRABLE: "配體間 1.9 Å < 3.3（碰撞）", HYPOTHESIS_CHANGE: "配體間 6.0 Å > 4.5（未共同佔據口袋）",
             MODEL_LIMITATION: "分數差 2.0 > 1.0 kcal/mol"}
    rc = [{"code": c, "rule": c, "text": texts[c]} for c in codes]
    return {"rank": rank, "score": score, "clash": GEOMETRY_REPAIRABLE in codes, "min_ll_distance": 1.9,
            "rejected": [x["text"] for x in rc], "rejection_codes": rc}


def _choose(wf, e):
    return wf.choose_poses(types.SimpleNamespace(mode="simultaneous", entries=[e]))


def test_co_occupancy_rejection_cannot_be_cleared_by_the_fallback(tmp_path):
    """Spec A7 test: every pose fails co-occupancy (one also clashes) → stop, never 'least risk'."""
    wf = _wf(tmp_path, md={"systems": ["apo", "docked_multi"], "tier": "classroom"})
    e = _entry(tmp_path, [_pose(1, -10.0, GEOMETRY_REPAIRABLE, HYPOTHESIS_CHANGE), _pose(2, -9.9, HYPOTHESIS_CHANGE)])
    with pytest.raises(WorkflowBlocked) as exc:
        _choose(wf, e)
    msg = str(exc.value)
    assert "不採用低風險後備" in msg and "未共同佔據" in msg and "假設不成立" in msg
    assert "least_risk_poses" not in wf.state()


def test_fallback_skips_poses_with_non_geometric_rejections(tmp_path):
    wf = _wf(tmp_path, md={"systems": ["apo", "docked_multi"], "tier": "classroom"})
    e = _entry(tmp_path, [_pose(1, -10.0, GEOMETRY_REPAIRABLE, MODEL_LIMITATION), _pose(2, -9.6, GEOMETRY_REPAIRABLE)])
    sel = _choose(wf, e)
    assert sel["ligands"]["A"]["rank"] == 2 and sel["ligands"]["A"]["fallback"] is True
    assert sel["ligands"]["A"]["docking_rejections"][0]["code"] == GEOMETRY_REPAIRABLE    # original reason kept
    rows = wf.state()["least_risk_poses"]["joint"]
    assert [r["rank"] for r in rows] == [2] and rows[0]["docking_rejections"]
    last = [d for d in wf.dec.read() if d["stage"] == "workflow.pose"][-1]
    assert "原始理由（保留）" in last["why"] and "碰撞" in last["why"] and "1 個因對接模型限制" in last["why"]


def test_entry_level_pocket_too_small_blocks_the_fallback(tmp_path):
    wf = _wf(tmp_path, md={"systems": ["apo", "docked_multi"], "tier": "classroom"})
    e = _entry(tmp_path, [_pose(1, -10.0, GEOMETRY_REPAIRABLE)], recommendation_code=HYPOTHESIS_CHANGE,
               recommendation_rule="pocket_too_small", reason="口袋可能只容得下一個配體")
    with pytest.raises(WorkflowBlocked) as exc:
        _choose(wf, e)
    assert "pocket_too_small" in str(exc.value)


def test_legacy_docking_result_without_codes_is_not_guessed_from_text(tmp_path):
    wf = _wf(tmp_path, md={"systems": ["apo", "docked_multi"], "tier": "classroom"})
    p = _pose(1, -10.0, GEOMETRY_REPAIRABLE)
    p.pop("rejection_codes")                                   # docking_results.json written before D-98
    with pytest.raises(WorkflowBlocked) as exc:
        _choose(wf, _entry(tmp_path, [p]))
    assert "沒有拒絕代碼" in str(exc.value) and "重新對接" in str(exc.value)


def test_explicit_human_choice_is_unaffected(tmp_path):
    wf = _wf(tmp_path, md={"systems": ["apo", "docked_multi"], "tier": "classroom"})
    wf.cfg["pose_choices"] = {"joint": 1}
    sel = _choose(wf, _entry(tmp_path, [_pose(1, -10.0, HYPOTHESIS_CHANGE)]))
    assert sel["ligands"]["A"]["rank"] == 1 and sel["ligands"]["A"]["fallback"] is False
    assert sel["ligands"]["A"]["docking_rejections"][0]["code"] == HYPOTHESIS_CHANGE   # still on record for the report
