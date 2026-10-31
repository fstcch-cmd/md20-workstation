from pathlib import Path
import datetime as dt

from md20.project import Project
from md20.engine import make_protocol, FakeBackend, run_replicas, JobQueue, PausePolicy, Paused, run_stage, StageSpec
import pytest


def _short(proto):
    for s in proto.stages:
        if s.ensemble != "MIN":
            s.length_ps = 10.0; s.checkpoint_interval_ps = 5.0; s.report_interval_ps = 0.2
    return proto


def _factory(case, proto):
    return lambda spec, dt_: FakeBackend(timestep_fs=dt_, temperature_k=spec.temperature_k, ensemble=spec.ensemble, seed=spec.seed)


def test_replicas_seeds_and_aggregate(tmp_path: Path):
    p = Project.create(tmp_path, "r"); c = p.new_case("c")
    proto = _short(make_protocol("classroom"))
    s = run_replicas(c, proto, _factory(c, proto), n=3, batch_steps=250)
    assert [r["status"] for r in s["runs"]] == ["COMPLETE"] * 3
    seeds = {r.manifest()["protocol"]["stages"][-1]["seed"] for r in c.runs()}
    assert seeds == {2026, 3026, 4026}
    agg = s["aggregate"]
    assert agg["n"] == 3 and agg["stages"]["production"]["temperature_k"]["n"] == 3
    assert abs(agg["stages"]["production"]["temperature_k"]["mean"] - 300) < 5
    assert Path(agg["figures"]["production_overlay"]["png"]).stat().st_size > 1000


def test_pause_policy_rules(tmp_path: Path):
    pf = tmp_path / "PAUSE"
    pol = PausePolicy(pause_file=pf, power_probe=lambda: {"has_battery": True, "on_ac": True})
    assert pol() is None
    pf.touch(); assert "暫停" in pol(); pf.unlink()
    pol = PausePolicy(pause_on_battery=True, power_probe=lambda: {"has_battery": True, "on_ac": False})
    assert "電池" in pol()
    pol = PausePolicy(allowed_hours=(22, 7), clock=lambda: dt.datetime(2026, 1, 1, 12, 0))
    assert "允許時段" in pol()
    pol = PausePolicy(allowed_hours=(22, 7), clock=lambda: dt.datetime(2026, 1, 1, 23, 0))
    assert pol() is None


def test_stage_pauses_and_resumes(tmp_path: Path):
    spec = StageSpec(name="nvt", ensemble="NVT", length_ps=20.0, timestep_fs=2.0, report_interval_ps=0.2, checkpoint_interval_ps=5.0)
    calls = {"n": 0}

    def pause():
        calls["n"] += 1
        return "test pause" if calls["n"] == 3 else None   # pause before chunk 3
    make = lambda s, d: FakeBackend(timestep_fs=d, temperature_k=s.temperature_k, ensemble=s.ensemble)  # noqa: E731
    with pytest.raises(Paused) as ei:
        run_stage(tmp_path / "nvt", spec, make, identity={"r": 1}, initial_state=None, batch_steps=250, should_pause=pause)
    assert ei.value.completed_local_steps == 5000
    res = run_stage(tmp_path / "nvt", spec, make, identity={"r": 1}, initial_state=None, batch_steps=250)
    assert res.status == "PASS" and res.chunks == 4


def test_queue_pause_then_resume_same_runs(tmp_path: Path):
    p = Project.create(tmp_path, "q"); c = p.new_case("c")
    q = JobQueue(p)
    q.add(c.case_id, tier="classroom", replicas=2)
    # monkeypatch protocol shortening via make_protocol wrapper
    import md20.engine.queue as qmod
    orig = qmod.make_protocol if hasattr(qmod, "make_protocol") else None
    from md20.engine import protocol as pmod
    real = pmod.make_protocol
    pmod.make_protocol = lambda *a, **k: _short(real(*a, **k))
    try:
        state = {"n": 0}

        def pause():
            state["n"] += 1
            return "battery" if state["n"] == 4 else None
        j = q.run_next(_factory, should_pause=pause, batch_steps=250)
        assert j["status"] == "PAUSED"
        runs_before = {r.run_id for r in c.runs()}
        j = q.run_next(_factory, should_pause=lambda: None, batch_steps=250)
        assert j["status"] == "COMPLETE"
        runs_after = {r.run_id for r in c.runs()}
        assert len(runs_after) == 2 and runs_before <= runs_after   # resumed, no duplicate runs
        assert q.run_next(_factory) is None
    finally:
        pmod.make_protocol = real
