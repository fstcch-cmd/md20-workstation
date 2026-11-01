"""Engine tests that run without OpenMM (FakeBackend)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from md20.engine import make_protocol, run_stage, run_protocol, FakeBackend, NeedsHuman, StageSpec
from md20.util import DecisionLog, load_json
from md20.analysis import read_state_log, evaluate_acceptance


def _factory(**kw):
    def make(spec: StageSpec, dt: float):
        return FakeBackend(timestep_fs=dt, temperature_k=spec.temperature_k, ensemble=spec.ensemble, **kw)
    return make


def test_stage_runs_and_seals(tmp_path: Path):
    spec = StageSpec(name="nvt", ensemble="NVT", length_ps=20.0, timestep_fs=2.0, temperature_k=300.0,
                     start_temperature_k=50.0, report_interval_ps=0.2, trajectory_interval_ps=2.0,
                     checkpoint_interval_ps=5.0)
    res = run_stage(tmp_path / "nvt", spec, _factory(), identity={"run": "r1"}, initial_state=None, batch_steps=200)
    assert res.status == "PASS"
    assert res.chunks == 4 and res.steps == 10000
    comp = load_json(tmp_path / "nvt" / "nvt_complete.json")
    assert comp["status"] == "PASS" and comp["state_sha256"]
    df = read_state_log(res.log_path)
    assert len(df) == 100 and df["step"].is_monotonic_increasing
    # heating ramp reached target
    assert abs(df["temperature_k"].iloc[-1] - 300) < 15


def test_resume_discards_damaged_chunk_and_continues(tmp_path: Path):
    spec = StageSpec(name="npt", ensemble="NPT", length_ps=20.0, timestep_fs=2.0, report_interval_ps=0.2,
                     checkpoint_interval_ps=5.0)
    sdir = tmp_path / "npt"
    run_stage(sdir, spec, _factory(), identity={"run": "r1"}, initial_state=None, batch_steps=250)
    # damage chunk 3's log and delete the completion manifest → should redo chunks 3-4 only
    (sdir / "chunk_00003.log").write_text("corrupt", encoding="utf-8")
    (sdir / "npt_complete.json").unlink()
    dec = DecisionLog(tmp_path / "decisions.jsonl")
    res = run_stage(sdir, spec, _factory(), identity={"run": "r1"}, initial_state=None, decisions=dec, batch_steps=250)
    assert res.status == "PASS" and res.chunks == 4
    kinds = [d["what"] for d in dec.read()]
    assert "resume" in kinds
    assert (sdir / "chunk_00003.log").read_text(encoding="utf-8").startswith("#")  # re-written, not "corrupt"
    prog = load_json(sdir / "npt_progress.json")
    assert [c["chunk"] for c in prog["chunks"]] == [1, 2, 3, 4]


def test_identity_mismatch_is_needs_human(tmp_path: Path):
    spec = StageSpec(name="nvt", ensemble="NVT", length_ps=4.0, timestep_fs=2.0, report_interval_ps=0.2, checkpoint_interval_ps=2.0)
    run_stage(tmp_path / "nvt", spec, _factory(), identity={"run": "r1"}, initial_state=None)
    with pytest.raises(NeedsHuman):
        run_stage(tmp_path / "nvt", spec, _factory(), identity={"run": "r2"}, initial_state=None)


def test_watchdog_retries_then_escalates(tmp_path: Path):
    spec = StageSpec(name="nvt", ensemble="NVT", length_ps=10.0, timestep_fs=2.0, report_interval_ps=0.2, checkpoint_interval_ps=5.0)
    dec = DecisionLog(tmp_path / "decisions.jsonl")
    # NaN appears at absolute step 3000 (inside chunk 2) regardless of dt → every retry fails → NEEDS_HUMAN
    with pytest.raises(NeedsHuman) as ei:
        run_stage(tmp_path / "nvt", spec, _factory(nan_at_step=3000), identity={"run": "r1"}, initial_state=None,
                  max_retries=2, batch_steps=250, decisions=dec)
    assert "chunk 2" in str(ei.value)
    prog = load_json(tmp_path / "nvt" / "nvt_progress.json")
    assert prog["status"] == "NEEDS_HUMAN" and len(prog["chunks"]) == 1
    assert sum(1 for d in dec.read() if d["what"] == "watchdog") == 2
    assert [e["timestep_fs"] for e in prog["watchdog_events"]] == [2.0, 1.0, 0.5]


def test_watchdog_recovers_when_smaller_dt_is_stable(tmp_path: Path):
    """Backend that fails only at dt=2.0 fs: engine halves dt, finishes the chunk, restores dt."""
    spec = StageSpec(name="nvt", ensemble="NVT", length_ps=10.0, timestep_fs=2.0, report_interval_ps=0.2, checkpoint_interval_ps=5.0)
    dec = DecisionLog(tmp_path / "decisions.jsonl")

    def make(spec_: StageSpec, dt: float):
        return FakeBackend(timestep_fs=dt, temperature_k=spec_.temperature_k, ensemble=spec_.ensemble,
                           nan_at_step=3000 if dt >= 2.0 else None)
    res = run_stage(tmp_path / "nvt", spec, make, identity={"run": "r1"}, initial_state=None, batch_steps=250, decisions=dec)
    assert res.status == "PASS" and res.chunks == 2
    whats = [d["what"] for d in dec.read()]
    assert whats.count("watchdog") == 1 and "timestep" in whats
    prog = load_json(tmp_path / "nvt" / "nvt_progress.json")
    assert prog["chunks"][1]["timestep_fs"] == 1.0
    # the halved-dt chunk must still simulate its full 5 ps (twice the integrator steps), so the stage ends at 10 ps —
    # previously the chunk was counted in steps and the stage silently finished at 7.5 ps
    c2 = prog["chunks"][1]
    assert c2["steps"] == 2500 and c2["integrator_steps"] == 5000 and c2["simulated_ps"] == 5.0
    assert abs(c2["summary"]["time_ps"] - 10.0) < 1e-6
    assert abs(prog["chunks"][0]["summary"]["time_ps"] - 5.0) < 1e-6


def test_watchdog_retry_restarts_at_ramp_temperature(tmp_path: Path):
    """A NaN after the heating ramp must not restart the system at the 50 K start temperature."""
    spec = StageSpec(name="nvt", ensemble="NVT", length_ps=10.0, timestep_fs=2.0, temperature_k=300.0, start_temperature_k=50.0,
                     ramp_fraction=0.3, report_interval_ps=0.2, checkpoint_interval_ps=5.0)
    seen = []

    class Probe(FakeBackend):
        def initialize(self, state, temperature_k, seed, regenerate_velocities=False):
            seen.append(float(temperature_k))
            return super().initialize(state, temperature_k, seed, regenerate_velocities)

    def make(spec_: StageSpec, dt: float):
        return Probe(timestep_fs=dt, temperature_k=spec_.temperature_k, ensemble=spec_.ensemble,
                     nan_at_step=3000 if dt >= 2.0 else None)
    res = run_stage(tmp_path / "nvt", spec, make, identity={"run": "r1"}, initial_state=None, batch_steps=250)
    assert res.status == "PASS"
    assert seen[0] == 50.0 and seen[1] == 300.0          # first start at ramp start; the retry at chunk 2 (frac 0.5 > ramp) at 300 K


def test_extension_keeps_schedule_of_original_length(tmp_path: Path):
    """Auto-extend (+50 ps on a 100 ps stage) must not re-tighten restraints already released, nor move the thermostat."""
    scales, temps = [], []

    class Probe(FakeBackend):
        def set_global_parameter(self, name, value):
            if name == "msw_restraint_scale":
                scales.append(float(value))
            return super().set_global_parameter(name, value)

        def set_temperature(self, t):
            temps.append(float(t))
            return super().set_temperature(t)

    def make(spec_: StageSpec, dt: float):
        return Probe(timestep_fs=dt, temperature_k=spec_.temperature_k, ensemble=spec_.ensemble)
    base = StageSpec(name="nvt", ensemble="NVT", length_ps=20.0, timestep_fs=2.0, temperature_k=300.0, start_temperature_k=50.0,
                     ramp_fraction=0.8, restraint_scale=1.0, restraint_scale_end=0.2, report_interval_ps=0.2, checkpoint_interval_ps=10.0)
    run_stage(tmp_path / "nvt", base, make, identity={"run": "r1"}, initial_state=None, batch_steps=500)
    assert abs(scales[-1] - 0.2) < 1e-9 and abs(temps[-1] - 300.0) < 1e-9
    # extend the same chunk sequence the way runner does (schedule stays pinned to the original 20 ps)
    import dataclasses
    ext = dataclasses.replace(base, length_ps=30.0, schedule_length_ps=20.0)
    (tmp_path / "nvt" / "nvt_complete.json").unlink()
    n0 = len(scales)
    res = run_stage(tmp_path / "nvt", ext, make, identity={"run": "r1"}, initial_state=None, batch_steps=500)
    assert res.status == "PASS" and res.chunks == 3
    assert all(abs(v - 0.2) < 1e-9 for v in scales[n0:]) and all(abs(t - 300.0) < 1e-9 for t in temps[n0:])
    # without the pin, the old behaviour would have pulled the restraint back up to ≈0.47 at the start of the extension
    assert all(b <= a + 1e-9 for a, b in zip(scales, scales[1:]))


def test_full_protocol_with_plots(tmp_path: Path):
    proto = make_protocol("classroom")
    # shrink lengths so the fake run is fast
    for s in proto.stages:
        if s.ensemble != "MIN":
            s.length_ps = 20.0; s.checkpoint_interval_ps = 10.0; s.report_interval_ps = 0.2
    dec = DecisionLog(tmp_path / "decisions.jsonl")
    status = run_protocol(tmp_path / "run1", proto, _factory(), identity={"case": "c1"}, decisions=dec, batch_steps=250)
    assert status["status"] == "COMPLETE"
    assert set(status["results"]) >= {"minimize", "nvt", "npt", "production"}
    figs = list((tmp_path / "run1" / "figures").glob("*.png"))
    names = {f.stem for f in figs}
    assert {"minimize_energy", "nvt_timeseries", "npt_timeseries", "production_timeseries", "run_overview"} <= names
    assert all(f.stat().st_size > 1000 for f in figs)
    # decision log is a readable teaching artefact
    md = dec.to_markdown()
    assert "restraint ladder" in md


def test_acceptance_extend_recommendation():
    import pandas as pd, numpy as np
    df = pd.DataFrame({"time_ps": np.linspace(0, 100, 200), "temperature_k": np.full(200, 280.0),
                       "density_g_ml": np.linspace(0.9, 1.0, 200), "potential_kj_mol": np.zeros(200)})
    acc = evaluate_acceptance(df, ensemble="NPT", target_temperature_k=300, length_ps=100)
    assert acc.status == "EXTEND" and acc.extend_ps == 50.0
    assert any(c["check"] == "temperature" and not c["ok"] for c in acc.checks)


def test_device_error_rebuilds_context_and_continues(tmp_path: Path):
    """WP11: a transient GPU/driver error mid-stage → rebuild context from the last good chunk, no lost chunks."""
    spec = StageSpec(name="npt", ensemble="NPT", length_ps=20.0, timestep_fs=2.0, report_interval_ps=0.2,
                     checkpoint_interval_ps=5.0)
    fired = {"n": 0}

    class Flaky(FakeBackend):
        def step(self, n):
            if self._step >= 6000 and fired["n"] == 0:
                fired["n"] += 1
                raise RuntimeError("CUDA_ERROR_LAUNCH_FAILED (simulated driver reset)")
            return super().step(n)

    def make(spec_, dt):
        return Flaky(timestep_fs=dt, temperature_k=spec_.temperature_k, ensemble=spec_.ensemble)

    log = DecisionLog(tmp_path / "decisions.jsonl")
    res = run_stage(tmp_path / "npt", spec, make, identity={"run": "r1"}, initial_state=None, batch_steps=250,
                    decisions=log)
    assert res.status == "PASS" and res.steps == 10000 and fired["n"] == 1
    assert any(d.get("what") == "context rebuild" for d in log.read())


def test_persistent_device_error_needs_human(tmp_path: Path):
    spec = StageSpec(name="npt", ensemble="NPT", length_ps=20.0, timestep_fs=2.0, report_interval_ps=0.2,
                     checkpoint_interval_ps=5.0)

    class Broken(FakeBackend):
        def step(self, n):
            if self._step >= 3000:
                raise RuntimeError("OpenCL error -5")
            return super().step(n)

    with pytest.raises(NeedsHuman, match="運算裝置"):
        run_stage(tmp_path / "npt", spec, lambda s, dt: Broken(timestep_fs=dt, ensemble="NPT"), identity={"run": "r1"},
                  initial_state=None, batch_steps=250)


def test_short_stage_gets_dense_log_and_passes(tmp_path: Path):
    """WP5 regression: a 2 ps screen stage with the tier's 0.5 ps report interval left 4 log rows → 'log almost empty'
    → two useless +0 ps extensions → NEEDS_HUMAN.  Now the interval is densified (and logged) up front."""
    proto = make_protocol("classroom")
    for s in proto.stages:
        if s.ensemble != "MIN":
            s.length_ps = 2.0; s.checkpoint_interval_ps = 2.0; s.report_interval_ps = 0.5
    dec = DecisionLog(tmp_path / "decisions.jsonl")
    status = run_protocol(tmp_path / "run1", proto, _factory(), identity={"case": "c1"}, decisions=dec, batch_steps=50)
    assert status["status"] == "COMPLETE", status
    assert len(read_state_log(tmp_path / "run1" / "stages" / "nvt" / "nvt.log")) >= 20
    assert any(d.get("what") == "report_interval_ps" for d in dec.read())


def test_unextendable_acceptance_fails_fast(tmp_path: Path, monkeypatch):
    """Acceptance that extension cannot fix (extend_ps 0) → NEEDS_HUMAN after one attempt, no wasted re-runs."""
    from md20.analysis.acceptance import AcceptanceResult
    import md20.engine.runner as runner
    calls = {"n": 0}

    def fake_eval(*a, **k):
        calls["n"] += 1
        return AcceptanceResult("NEEDS_HUMAN", [], "StateData log 幾乎是空的", extend_ps=0.0)
    monkeypatch.setattr(runner, "evaluate_acceptance", fake_eval)
    proto = make_protocol("classroom")
    for s in proto.stages:
        if s.ensemble != "MIN":
            s.length_ps = 4.0; s.checkpoint_interval_ps = 4.0; s.report_interval_ps = 0.2
    with pytest.raises(NeedsHuman, match="nvt 未通過驗收"):
        run_protocol(tmp_path / "run1", proto, _factory(), identity={"case": "c1"}, batch_steps=50)
    assert calls["n"] == 1
