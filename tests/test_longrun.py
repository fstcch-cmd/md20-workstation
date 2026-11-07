"""Long production runs (docs/specs/long_timescale.md): planner, gates, protocol overrides, chunk-state pruning."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from md20.engine import make_protocol
from md20.engine.backend import FakeBackend
from md20.engine.chunks import run_stage
from md20.engine.longrun import (plan_long_run, apply_plan, needs_plan, dcd_frame_bytes, solute_atom_indices,
                                 scaled_ns_per_day, summary_text, record_plan, CONFIRM_ABOVE_NS)
from md20.engine.protocol import StageSpec, Protocol
from md20.util import DecisionLog


def test_dcd_frame_bytes_matches_openmm_layout():
    # 48-byte unit cell record + markers, then x, y, z float32 records with markers
    assert dcd_frame_bytes(1000) == 56 + 3 * (4000 + 8)
    assert dcd_frame_bytes(1000, unit_cell=False) == 3 * 4008


def test_solute_rule_drops_water_and_counter_ions_keeps_metals():
    names = ["ALA", "ALA", "L01", "ZN", "HOH", "HOH", "HOH", "NA", "CL", "WAT", "MG"]
    assert solute_atom_indices(names) == [0, 1, 2, 3, 10]


def test_short_run_keeps_protocol_defaults():
    p = plan_long_run(n_atoms=30000, production_ns=50, ns_per_day=300, disk_free_gb=500)
    assert p.trajectory_interval_ps == 20 and p.report_interval_ps == 2
    assert "trajectory_interval_ps" not in (p.stage_overrides.get("production") or {})
    assert not needs_plan(100) and needs_plan(100.5) and needs_plan(50, {"solute_only": True})


def test_one_microsecond_3ptb_like_system():
    p = plan_long_run(n_atoms=32000, production_ns=1000, ns_per_day=330, n_solute_atoms=3300, disk_free_gb=500)
    assert p.status == "AUTO_FIXED"                                   # = 1 µs: no confirmation needed
    assert p.trajectory_gb <= 20.0 and not p.solute_only
    assert abs(p.days - 1000 / 330) < 0.01
    over = p.stage_overrides["production"]
    # chunk is a whole number of both intervals, so frames stay evenly spaced across chunks
    for k in ("trajectory_interval_ps", "report_interval_ps"):
        assert (p.checkpoint_interval_ps / p.__dict__[k]) == pytest.approx(round(p.checkpoint_interval_ps / p.__dict__[k]))
    assert p.n_chunks <= 500 and p.chunk_wall_minutes <= 60.0 + 1e-6
    assert over["keep_chunk_states"] == 3 and p.states_gb < 0.1
    assert 1000 * 1000 / p.report_interval_ps <= 250_000


def test_above_one_microsecond_needs_confirmation_with_days_and_disk():
    p = plan_long_run(n_atoms=32000, production_ns=2000, ns_per_day=330, disk_free_gb=500)
    assert p.status == "NEEDS_HUMAN"
    assert "md.long_run_confirmed: true" in p.options()[0]
    assert "天" in p.message_zh() and "GB" in p.message_zh()
    q = plan_long_run(n_atoms=32000, production_ns=2000, ns_per_day=330, disk_free_gb=500, confirmed=True)
    assert q.status == "AUTO_FIXED"
    # no benchmark: still blocks, and says the days are unknown instead of guessing
    r = plan_long_run(n_atoms=32000, production_ns=2000, disk_free_gb=500)
    assert r.days is None and "無法估計天數" in r.message_zh()


def test_over_ten_microseconds_is_refused():
    p = plan_long_run(n_atoms=32000, production_ns=20000, ns_per_day=330, confirmed=True, disk_free_gb=1e4)
    assert p.status == "NEEDS_HUMAN" and any(i["code"] == "too_long" for i in p.issues)


def test_solute_only_auto_when_full_system_frames_get_too_sparse():
    p = plan_long_run(n_atoms=32000, production_ns=10000, ns_per_day=330, n_solute_atoms=3300, confirmed=True,
                      disk_free_gb=1e4)
    assert p.solute_only and p.saved_atoms == 3300 and p.trajectory_interval_ps <= 100
    assert p.stage_overrides["production"]["trajectory_atoms"] == "solute"
    assert any(d["what"] == "trajectory_atoms" for d in p.decisions)
    full = plan_long_run(n_atoms=32000, production_ns=10000, ns_per_day=330, n_solute_atoms=3300, confirmed=True,
                         solute_only=False, disk_free_gb=1e4)
    assert not full.solute_only and full.trajectory_interval_ps > 100 and full.trajectory_gb <= 20.0


def test_disk_too_small_blocks_with_options():
    p = plan_long_run(n_atoms=120000, production_ns=5000, ns_per_day=80, confirmed=True, n_solute_atoms=12000,
                      solute_only=False, disk_free_gb=15)
    assert p.status == "NEEDS_HUMAN" and any(i["code"] == "disk" for i in p.issues)
    opts = p.options()
    assert any(o.startswith("md.long_run.solute_only: true") for o in opts)
    assert any(o.startswith("md.long_run.target_gb:") for o in opts)
    # the suggested size really fits
    gb = float([o for o in opts if o.startswith("md.long_run.target_gb:")][0].split(":")[1].split("（")[0])
    q = plan_long_run(n_atoms=120000, production_ns=5000, ns_per_day=80, confirmed=True, solute_only=False,
                      target_gb=gb, disk_free_gb=15)
    assert q.status != "NEEDS_HUMAN"


def test_benchmark_scaling_and_summary_text():
    s = scaled_ns_per_day({"ns_per_day": 330, "n_atoms": 24000, "timestep_fs": 4.0}, 48000, 2.0)
    assert s == pytest.approx(330 * 0.5 * 0.5)
    p = plan_long_run(n_atoms=48000, production_ns=500, timestep_fs=2.0,
                      bench={"ns_per_day": 330, "n_atoms": 24000, "timestep_fs": 4.0}, disk_free_gb=100)
    assert p.days == pytest.approx(500 / s, rel=1e-3)
    t = summary_text(p)
    assert len(t) == 4 and "GB" in t[1] and "天" in t[0] and "日" in t[2] and "일" in t[3]


def test_apply_plan_changes_production_only_and_hash():
    proto = make_protocol("research", production_ns=2000)
    before = proto.hash()
    npt = copy.deepcopy(proto.stage("npt").__dict__)
    p = plan_long_run(n_atoms=32000, production_ns=2000, ns_per_day=330, n_solute_atoms=3300, confirmed=True,
                      timestep_fs=2.0, disk_free_gb=500)
    apply_plan(proto, p)
    prod = proto.stage("production")
    assert prod.trajectory_interval_ps == p.trajectory_interval_ps and prod.keep_chunk_states == 3
    assert proto.stage("npt").__dict__ == npt
    assert proto.hash() != before
    record_plan(p, None)        # no decision log: nothing recorded, no error


def test_new_stage_fields_do_not_change_existing_hashes():
    # the fields are dropped from the dict at their defaults: runs started before them keep resuming
    for tier in ("classroom", "teaching", "research"):
        d = make_protocol(tier).to_dict()
        assert all("trajectory_atoms" not in s and "keep_chunk_states" not in s for s in d["stages"])
    proto = make_protocol("teaching")
    assert Protocol.from_dict(json.loads(json.dumps(proto.to_dict()))).hash() == proto.hash()


def _fake(spec, dt):
    return FakeBackend(n_atoms=500, timestep_fs=dt, temperature_k=spec.temperature_k, ensemble=spec.ensemble, seed=spec.seed)


def test_record_plan_writes_chinese_reasons(tmp_path):
    dec = DecisionLog(tmp_path / "d.jsonl")
    p = plan_long_run(n_atoms=32000, production_ns=1000, ns_per_day=330, disk_free_gb=500)
    record_plan(p, dec)
    rows = dec.read()
    assert {r["what"] for r in rows} >= {"checkpoint_interval_ps", "keep_chunk_states", "plan"}
    assert all(any("\u4e00" <= ch <= "\u9fff" for ch in r["why"]) for r in rows)


def test_chunk_state_pruning_and_resume(tmp_path):
    spec = StageSpec(name="production", ensemble="NPT", length_ps=10.0, timestep_fs=2.0, report_interval_ps=0.5,
                     trajectory_interval_ps=1.0, checkpoint_interval_ps=1.0, keep_chunk_states=2)
    res = run_stage(tmp_path / "s", spec, _fake, identity={"case_id": "x"}, initial_state=None)
    assert res.chunks == 10
    xml = sorted(p.name for p in (tmp_path / "s").glob("chunk_*.xml"))
    assert xml == ["chunk_00009.xml", "chunk_00010.xml"]
    assert len(list((tmp_path / "s").glob("chunk_*.log"))) == 10          # logs and DCDs are all kept
    assert len(res.dcd_paths) == 10
    prog = json.loads((tmp_path / "s" / "production_progress.json").read_text())
    assert all(c["artifacts"]["state"].get("pruned") for c in prog["chunks"][:8])
    # resume of a finished stage is idempotent
    (tmp_path / "s" / "production_complete.json").unlink()
    res2 = run_stage(tmp_path / "s", spec, _fake, identity={"case_id": "x"}, initial_state=None)
    assert res2.chunks == 10


def test_damaged_kept_state_falls_back_to_last_unpruned(tmp_path):
    from md20.engine.chunks import _verify_chunks
    spec = StageSpec(name="production", ensemble="NPT", length_ps=6.0, timestep_fs=2.0, report_interval_ps=0.5,
                     trajectory_interval_ps=1.0, checkpoint_interval_ps=1.0, keep_chunk_states=2)
    run_stage(tmp_path / "s", spec, _fake, identity={"case_id": "x"}, initial_state=None)
    prog = json.loads((tmp_path / "s" / "production_progress.json").read_text())
    valid, done, last = _verify_chunks(prog, tmp_path / "s")
    assert len(valid) == 6 and last.name == "chunk_00006.xml"
    (tmp_path / "s" / "chunk_00006.xml").write_text("broken")
    valid, done, last = _verify_chunks(prog, tmp_path / "s")
    assert len(valid) == 5 and last.name == "chunk_00005.xml" and last.is_file()
    (tmp_path / "s" / "chunk_00005.xml").write_text("broken too")
    valid, done, last = _verify_chunks(prog, tmp_path / "s")
    assert valid == [] and done == 0 and last is None          # nothing on disk to resume from: start the stage over


# ------------------------------------------------------------------ workflow gate and one-click options
def _wf_case(tmp_path, cfg_md):
    from md20.project.store import Project
    from md20.workflow import Workflow, example_config
    cfg = copy.deepcopy(example_config())
    cfg["md"].update(cfg_md)
    wf = Workflow(Project.create(tmp_path, "p"), cfg)
    b = tmp_path / "case" / "build"; b.mkdir(parents=True)
    (b / "build_manifest.json").write_text(json.dumps({"n_atoms": 32000, "n_protein_atoms": 3200, "n_ligand_atoms": 9}))
    return wf, SimpleNamespace(case_id="c1", build_dir=b, dir=tmp_path / "case")


def test_workflow_blocks_over_one_microsecond_then_applies_plan(tmp_path):
    from md20.workflow import WorkflowBlocked, DECISION_KEYS
    assert ("md", "long_run_confirmed") in DECISION_KEYS and ("md", "long_run") in DECISION_KEYS
    wf, case = _wf_case(tmp_path, {"production_ns": 2000, "ns_per_day": 330})
    proto = make_protocol("teaching", production_ns=2000, replicas=1)       # the disk figures below are for one replica
    with pytest.raises(WorkflowBlocked, match="1 µs"):
        wf._plan_long_run("docked_single", case, proto, {})
    gate = wf.state()["steps"]["md_runs"]["gates"][0]
    assert gate["name"] == "long run" and gate["evidence"]["days"] > 0
    from md20.gui.actions import gate_actions
    acts, manual = gate_actions(gate, step="md_runs")
    patches = {tuple(a["patch"][0]["path"]): a["patch"][0]["value"] for a in acts}
    assert patches[("md", "long_run_confirmed")] is True and patches[("md", "production_ns")] == 1000.0
    wf.cfg["md"]["long_run_confirmed"] = True
    wf._plan_long_run("docked_single", case, proto, {})
    assert proto.stage("production").keep_chunk_states == 3
    assert proto.stage("npt").trajectory_interval_ps == make_protocol("teaching").stage("npt").trajectory_interval_ps


def test_workflow_leaves_runs_up_to_100_ns_untouched(tmp_path):
    wf, case = _wf_case(tmp_path, {"production_ns": 100})
    proto = make_protocol("research")
    h = proto.hash()
    wf._plan_long_run("apo", case, proto, {})
    assert proto.hash() == h


def test_gate_text_for_long_run_options():
    from md20.gui.gate_text import option_text, gate_title
    assert gate_title("long run", "ja") == "長時間シミュレーション"
    assert option_text("md.production_ns: 1000（縮短到 1 µs）", "en").endswith("1000")
    assert option_text("md.long_run_confirmed: true（確認天數與硬碟用量，開始）", "ko").startswith("일수")


def test_advisor_reports_days_and_disk_for_long_runs():
    from md20 import advisor as A
    f = A.CaseFeatures(n_residues=223, ns_per_day=330, bench_atoms=24000, bench_dt_fs=4.0)
    assert A.PARAMS["production_ns"]["max"] == 10000
    iss = [i for i in A.check({"production_ns": 2000}, f, lang="en") if i["key"] == "production_ns"]
    assert iss and iss[0]["level"] == "warning" and "GB" in iss[0]["message"] and "days" in iss[0]["message"]
    assert not [i for i in A.check({"production_ns": 50}, f, lang="en") if i["key"] == "production_ns"]
    est = A.estimate_hours({"production_ns": 2000}, f)
    assert est["disk_gb"] > 0 and est["days"] > 0
    assert "days" not in A.estimate_hours({"production_ns": 10}, f)
