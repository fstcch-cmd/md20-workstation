from md20.engine.progress_text import StageMeter


def test_stage_meter_line():
    m = StageMeter()
    ev = lambda d, t: {"stage": "npt", "case_id": "c", "completed_local_steps": d, "total_steps": 100000,  # noqa: E731
                       "temperature_k": 300.04, "elapsed_s": t, "timestep_fs": 4.0}
    assert "left" not in m.line(ev(1000, 10))
    line = m.line(ev(11000, 110))
    assert "[npt]  11.0 %" in line and "T 300.0 K" in line and "14 min left in stage" in line and "35 ns/day" in line
    assert m.line({"stage": "umbrella", "window": 3, "n_windows": 24}).endswith("window 3 of 24")
    assert m.line({"stage": "other"}) is None
