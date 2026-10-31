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
