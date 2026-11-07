"""D-101: umbrella windows planned from the SMD force curve (prevention), early gap alerts with a cause (shown while
running), the μ(c) inverse aim at k_max, and a coverage figure that always exists.  Synthetic profiles with exact
biased sampling (tests/test_adaptive_windows.py)."""
import numpy as np
import pytest

import test_adaptive_windows as T
from md20.sampling.adaptive import (aim_by_response, bimodality, continuity_report, gap_alerts, plan_from_smd,
                                    plan_refinement, _stats)


def smd_force(prof, friction=30.0, seed=0, lo=0.45, hi=1.6):
    r = np.linspace(lo, hi, 4000)
    return r, np.gradient(prof(r), r) + friction + np.random.default_rng(seed).normal(0, 40, len(r))


def _plan(prof, **kw):
    r, f = smd_force(prof)
    return plan_from_smd(r, f, 0.45, 1.6, k0=1000, k_max=5000, temperature_k=T.T, target_overlap=0.2,
                         max_windows=kw.get("max_windows", 40))


def _refine(samples, ks, prof, rounds=8):
    n_rounds = 0
    for rnd in range(rounds):
        p = plan_refinement(samples, ks, temperature_k=T.T, cv_range=(0.45, 1.6))
        if p.done or not p.insert:
            break
        n_rounds += 1
        for j, ins in enumerate(p.insert):
            c, k = float(ins["center"]), float(ins["k"])
            samples[c], ks[c] = T.sample(c, k, seed=1000 * (rnd + 1) + j, prof=prof), k
    return n_rounds


def test_steep_stretch_gets_stiff_dense_windows_and_flat_stays_uniform():
    p = _plan(T.PROFILES["sharp"])
    assert not p["uniform"] and p["regions"]
    wall = [k for t, k in zip(p["targets"], p["k"]) if 0.45 <= t <= 0.6]
    flat = [k for t, k in zip(p["targets"], p["k"]) if t >= 0.9]
    assert min(wall) >= 3000 and max(flat) == 1000
    t = np.array(p["targets"])
    g_wall = np.diff(t[t <= 0.6]).max()
    g_flat = np.median(np.diff(t[(t >= 0.9) & (t < 1.55)]))
    assert g_wall < g_flat                                         # denser on the wall
    assert all(c >= t - 1e-9 for t, c in zip(p["targets"], p["centers"]))   # centres aimed uphill (outward)


def test_window_at_the_top_of_a_wall_is_held_by_the_wall_slope():
    """A window placed just past the wall sees a flat slope at its own point but slides down the wall."""
    p = _plan(T.PROFILES["sharp"])
    just_past = [k for t, k in zip(p["targets"], p["k"]) if 0.57 < t < 0.65]
    assert just_past and min(just_past) > 1000


def test_sparse_smd_curve_falls_back_to_uniform():
    p = plan_from_smd([0.5, 0.6], [10, 10], 0.45, 1.6, k0=1000, k_max=5000, temperature_k=300, target_overlap=0.2,
                      max_windows=40)
    assert p["uniform"] and p["notes"]


def test_window_budget_is_respected():
    p = _plan(T.PROFILES["sharp"], max_windows=10)
    assert len(p["centers"]) <= 10 and p["spacing_scale"] > 1.0 and any("上限" in n for n in p["notes"])


@pytest.mark.parametrize("name", ["smooth", "sharp", "desolv"])
def test_smd_informed_start_needs_no_more_rounds_than_uniform_and_ends_continuous(name):
    prof = T.PROFILES[name]
    uni = {float(c): T.sample(c, 1000.0, seed=i, prof=prof) for i, c in enumerate(T.COARSE)}
    uk = {c: 1000.0 for c in uni}
    r_uni = _refine(uni, uk, prof)
    p = _plan(prof)
    smd = {float(c): T.sample(c, k, seed=i, prof=prof) for i, (c, k) in enumerate(zip(p["centers"], p["k"]))}
    sk = {float(c): k for c, k in zip(p["centers"], p["k"])}
    r_smd = _refine(smd, sk, prof)
    assert continuity_report(smd)["continuous"]
    assert r_smd <= r_uni and r_smd <= 1


def test_alerts_only_for_real_gaps_with_cause_and_never_for_pending_windows():
    for name, cause in (("smooth", "drift"), ("sharp", "barrier"), ("desolv", "drift")):
        prof = T.PROFILES[name]
        s = {float(c): T.sample(c, 1000.0, seed=i, prof=prof) for i, c in enumerate(T.COARSE)}
        al = gap_alerts(s, {c: 1000.0 for c in s}, planned=list(s), temperature_k=T.T)
        assert len(al) == 1 and al[0]["cause"] == cause, (name, al)
    rng = np.random.default_rng(1)
    s = {0.5: rng.normal(0.5, 0.05, 500), 0.7: rng.normal(0.7, 0.05, 500)}
    assert gap_alerts(s, {0.5: 1000, 0.7: 1000}, planned=[0.5, 0.6, 0.7]) == []        # 0.6 not run yet
    assert gap_alerts(s, {0.5: 1000, 0.7: 1000}, planned=[0.5, 0.7])[0]["cause"] == "spacing"


def test_alert_at_k_max_asks_for_a_decision():
    prof = T.PROFILES["spike"]
    s = {float(c): T.sample(c, 5000.0, seed=i, prof=prof) for i, c in enumerate(np.linspace(0.62, 1.0, 12))}
    al = gap_alerts(s, {c: 5000.0 for c in s}, planned=list(s), temperature_k=T.T, k_max=5000.0)
    assert al and any(a["cause"].endswith("_at_kmax") and "無法" in a["action"] for a in al)


def test_bimodality_coefficient():
    rng = np.random.default_rng(0)
    assert bimodality(rng.normal(0, 1, 2000)) < 0.555
    assert bimodality(np.r_[rng.normal(-2, 0.3, 1000), rng.normal(2, 0.3, 1000)]) > 0.555


def test_aim_by_response_inverts_mu_of_c_and_gives_up_when_stuck():
    from types import SimpleNamespace as W
    moving = [W(center=0.60, mu=0.50, k=5000.0), W(center=0.70, mu=0.62, k=5000.0)]   # dμ/dc = 1.2
    a = aim_by_response(moving, 0.53, 0.58, 5000.0, T.KT, 0.2)
    assert a and all(0.6 < c < 0.7 for c in a["centers"])
    stuck = [W(center=0.60, mu=0.50, k=5000.0), W(center=0.70, mu=0.505, k=5000.0)]
    assert aim_by_response(stuck, 0.53, 0.58, 5000.0, T.KT, 0.2) is None


def test_refinement_stops_inserting_where_the_pooled_histogram_is_already_continuous():
    """Pairwise overlap pulled down by a slid window must not keep adding windows round after round."""
    prof = T.PROFILES["sharp"]
    p = _plan(prof)
    s = {float(c): T.sample(c, k, seed=i, prof=prof) for i, (c, k) in enumerate(zip(p["centers"], p["k"]))}
    ks = {float(c): k for c, k in zip(p["centers"], p["k"])}
    _refine(s, ks, prof)
    last = plan_refinement(s, ks, temperature_k=T.T, cv_range=(0.45, 1.6))
    assert last.done and not last.insert


def test_coverage_figure_marks_breaks_and_alerts(tmp_path):
    from md20.analysis.plots import plot_umbrella_histograms
    prof = T.PROFILES["sharp"]
    s = {float(c): T.sample(c, 1000.0, seed=i, prof=prof) for i, c in enumerate(T.COARSE)}
    out = plot_umbrella_histograms(s, tmp_path / "cov", breaks=[[0.5, 0.77]],
                                   alerts=gap_alerts(s, {c: 1000.0 for c in s}, planned=list(s)), cv_range=(0.45, 1.6))
    assert (tmp_path / "cov.png").is_file() and out.get("png")


def test_empty_coverage_says_why_and_alerts_reach_the_progress_line():
    from md20.gui.views import coverage_summary
    from md20.engine.progress_text import StageMeter
    assert "SMD" in coverage_summary({"status": "RUNNING"}, lang="zh")
    assert "first window" in coverage_summary({"status": "RUNNING"}, lang="en")
    cov = {"status": "RUNNING", "windows": [{}, {}], "continuous": False, "breaks": [[0.5, 0.6]],
           "alerts": [{"lo": 0.5, "hi": 0.6, "cause": "drift"}]}
    assert "⚠" in coverage_summary(cov, lang="zh") and "推走" in coverage_summary(cov, lang="zh")
    line = StageMeter().line({"stage": "umbrella", "window": 3, "n": 9,
                                     "alerts": [{"lo": 0.5, "hi": 0.6, "cause": "drift"}]})
    assert line and "gap" in line and "drift" in line
