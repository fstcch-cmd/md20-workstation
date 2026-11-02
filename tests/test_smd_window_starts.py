"""D-45: window start frames are taken where the spring is relaxed, not at an overshoot; SMD ringing is measured."""
import numpy as np

from md20.sampling.binding import WindowStartPicker, smd_ringing


def _run(trace, centers, **kw):
    pk = WindowStartPicker(centers, **kw)
    picked = {}
    for i, (r0, d) in enumerate(trace):
        for w, rec in pk.offer(d, r0, lambda i=i: f"state{i}"):
            picked[w] = (rec["xml"], rec["pick"], rec["cv"])
    for w, rec in pk.flush():
        picked[w] = (rec["xml"], rec["pick"], rec["cv"])
    return picked


def test_overshoot_is_skipped_for_a_relaxed_frame():
    # spring moves 0.002 nm per record; the ligand slips at r0 = 0.50 and rings ±0.12 nm before settling
    r0 = np.arange(0.20, 1.00, 0.002)
    d = np.where(r0 < 0.50, 0.22, r0 + 0.12 * np.exp(-(r0 - 0.50) / 0.05) * np.cos((r0 - 0.50) / 0.012))
    picked = _run(list(zip(r0, d)), [0.60])
    xml, how, cv = picked[0]
    i = int(xml[5:])
    assert how == "relaxed" and abs(cv - 0.60) <= 0.05 and abs(r0[i] - d[i]) <= 0.05
    first_cross = int(np.argmax(d >= 0.60))
    assert i > first_cross                    # the first crossing (an overshoot) was not used


def test_fallback_keeps_first_crossing_and_never_skips_a_window():
    # ligand lags far behind the spring the whole way (never relaxed)
    r0 = np.arange(0.2, 2.0, 0.002)
    d = 0.2 + 0.3 * (r0 - 0.2)
    picked = _run(list(zip(r0, d)), [0.3, 0.5, 0.7])
    assert [picked[w][1] for w in (0, 1, 2)] == ["first_crossing"] * 3
    assert picked[0][2] >= 0.3 and picked[1][2] >= 0.5


def test_ringing_diagnostic():
    t = np.arange(0, 100) * 0.2
    r0 = 0.2 + 0.002 * np.arange(100)
    d = r0 + 0.15 * np.sin(np.arange(100))
    arr = np.column_stack([t, r0, d, 1000 * (r0 - d), np.zeros(100)])
    diag = smd_ringing(arr)
    assert diag["max_cv_jump_nm"] > 0.1 and diag["fraction_backward_steps"] > 0.2 and diag["record_interval_ps"] == 0.2
