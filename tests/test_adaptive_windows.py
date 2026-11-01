"""Adaptive umbrella refinement on synthetic free-energy profiles with exact biased sampling.

Model: a window with spring k at centre c samples the Boltzmann distribution of F(r) + ½k(r − c)², drawn exactly
on a fine grid.  Steep walls make windows drift downhill — what left breaks in the Colab version's PMFs."""
import math

import numpy as np
import pytest

from md20.sampling.adaptive import (KB_KJ_MOL_K, continuity_report, coverage_view, gaussian_overlap, plan_range,
                                    plan_refinement, spacing_for_overlap)

T = 300.0
KT = KB_KJ_MOL_K * T
GRID = np.linspace(0.2, 3.0, 28001)
PROFILES = {
    # bound well, then a straight 200 kJ/mol/nm wall over 0.3 nm (60 kJ/mol), flat bulk
    "smooth": lambda r: np.where(r < 0.45, 300.0 * (r - 0.45) ** 2, np.where(r < 0.75, 200.0 * (r - 0.45), 60.0)),
    # the same 60 kJ/mol packed into 0.12 nm — windows slide into the well and leave the wall empty
    "sharp": lambda r: np.where(r < 0.45, 800.0 * (r - 0.45) ** 2, np.where(r < 0.57, 500.0 * (r - 0.45), 60.0)),
    # realistic desolvation barrier: 12 kJ/mol, 0.1 nm wide, after a 150 kJ/mol/nm wall
    "desolv": lambda r: np.where(r < 0.45, 800.0 * (r - 0.45) ** 2, np.where(r < 0.65, 150.0 * (r - 0.45), 30.0))
                        + 12.0 * np.exp(-((r - 0.75) / 0.1) ** 2),
    # unphysically sharp: 60 kJ/mol over 0.06 nm, curvature ≈ 33 000 kJ/mol/nm² > any k we allow
    "spike": lambda r: np.where(r < 0.45, 800.0 * (r - 0.45) ** 2, np.where(r < 0.6, 200.0 * (r - 0.45), 30.0))
                       + 60.0 * np.exp(-((r - 0.8) / 0.06) ** 2),
}
COARSE = np.linspace(0.45, 1.6, 9)


def sample(c, k, n=2000, seed=0, prof=PROFILES["smooth"]):
    rng = np.random.default_rng(seed + int(c * 1e4) + int(k))
    u = (prof(GRID) + 0.5 * k * (GRID - c) ** 2) / KT
    p = np.exp(-(u - u.min()))
    p /= p.sum()
    return rng.choice(GRID, size=n, p=p)


def run_adaptive(centres, k0, rounds=8, prof=PROFILES["smooth"], **kw):
    samples = {float(c): sample(c, k0, seed=i, prof=prof) for i, c in enumerate(centres)}
    ks = {float(c): k0 for c in centres}
    history = []
    for rnd in range(rounds):
        plan = plan_refinement(samples, ks, temperature_k=T, **kw)
        history.append(plan)
        if plan.done or not plan.insert:
            break
        for j, ins in enumerate(plan.insert):
            c, k = float(ins["center"]), float(ins["k"])
            samples[c] = sample(c, k, seed=1000 * (rnd + 1) + j, prof=prof)
            ks[c] = k
    return samples, ks, history


def _old_rule(prof, centres, k0=1000.0):
    """The previous binding.py rule: insert at centre midpoints, same k, 2 rounds × ≤ 6."""
    from md20.sampling.pmf import umbrella_quality
    samples = {float(c): sample(c, k0, seed=i, prof=prof) for i, c in enumerate(centres)}
    for _ in range(2):
        q, _, _ = umbrella_quality(samples, target_overlap=0.15)
        new = [float(round(c, 4)) for c in (q.get("insert_centers_nm") or []) if float(round(c, 4)) not in samples][:6]
        for c in new:
            samples[c] = sample(c, k0, seed=77, prof=prof)
    return samples


def _pmf_error(samples, ks, prof):
    from md20.sampling.pmf import pmf_from_windows
    res = pmf_from_windows(samples, force_constant_kj_mol_nm2=ks, temperature_k=T, n_bootstrap=0, prefer_mbar=False)
    g, W = np.asarray(res.grid_nm), np.asarray(res.pmf_kj_mol)
    m = np.isfinite(W) & (g > 0.47) & (g < 1.5)
    ref = prof(g[m]) - prof(g[m]).min()
    W = W[m] - W[m].min()
    return float(np.max(np.abs(W - ref)))


def test_spacing_matches_overlap():
    s = 0.05
    assert abs(gaussian_overlap(0.0, s, spacing_for_overlap(s, 0.25), s) - 0.25) < 0.01


def test_flat_profile_needs_nothing_when_planned_spacing_is_right():
    """No oversampling: correctly spaced windows on a flat stretch get no insertions."""
    k0 = 1000.0
    step = spacing_for_overlap(math.sqrt(KT / k0), 0.3)
    centres = 1.2 + step * np.arange(8)                      # entirely in the flat bulk
    samples, ks, hist = run_adaptive(centres, k0, rounds=3, target_overlap=0.2, min_effective_samples=50)
    assert hist[0].insert == [] and hist[0].continuous and len(samples) == 8


def test_sharp_wall_old_rule_breaks_new_rule_is_continuous():
    """The Colab symptom: on a sharp wall the old midpoint/same-k rule leaves a break; the planner closes it."""
    prof = PROFILES["sharp"]
    old = _old_rule(prof, COARSE)
    assert not continuity_report(old)["continuous"]
    samples, ks, hist = run_adaptive(COARSE, 1000.0, prof=prof, target_overlap=0.2, min_effective_samples=50)
    assert continuity_report(samples)["continuous"] and hist[-1].continuous, [h.notes for h in hist]
    assert max(ks.values()) > 1000.0 and len(samples) <= 30 and len(hist) <= 6
    assert len(hist[0].insert) >= 2                          # coarse → fine: big holes get several windows at once
    assert _pmf_error(samples, ks, prof) < _pmf_error(old, 1000.0, prof)


@pytest.mark.parametrize("name", ["smooth", "desolv"])
def test_realistic_profiles_become_continuous_and_accurate(name):
    prof = PROFILES[name]
    samples, ks, hist = run_adaptive(COARSE, 1000.0, prof=prof, target_overlap=0.2, min_effective_samples=50)
    assert continuity_report(samples)["continuous"] and hist[-1].done
    assert len(samples) <= 25                                # filled, not flooded
    assert _pmf_error(samples, ks, prof) < 1.5               # kJ/mol, worst point over the wall/barrier


def test_unsamplable_spike_is_reported_and_stops():
    """A barrier steeper than k_max cannot be sampled: the planner says so and stops instead of adding windows."""
    samples, ks, hist = run_adaptive(COARSE, 1000.0, prof=PROFILES["spike"], rounds=10, target_overlap=0.2,
                                     min_effective_samples=50)
    assert not hist[-1].continuous and hist[-1].unsamplable
    assert not hist[-1].insert and len(hist) < 10 and len(samples) <= 30
    assert any("k 上限" in n for n in hist[-1].notes)


def test_budget_and_extend_and_ends():
    k0 = 1000.0
    centres = np.linspace(0.45, 1.6, 5)
    samples = {float(c): sample(c, k0, n=60, seed=i) for i, c in enumerate(centres)}
    plan = plan_refinement(samples, k0, temperature_k=T, target_overlap=0.2, min_effective_samples=100,
                           max_new_per_round=3, max_total_windows=7, cv_range=(0.4, 2.0))
    assert len(plan.insert) == 2 and plan.budget_exhausted          # room for 2 under the total cap
    assert {e["center"] for e in plan.extend} == {float(c) for c in centres}   # too few samples → extend, not duplicate
    assert not plan.done


def test_redundant_window_is_flagged():
    k0 = 1000.0
    samples = {1.2: sample(1.2, k0, seed=1), 1.2005: sample(1.2005, k0, seed=2), 1.3: sample(1.3, k0, seed=3)}
    plan = plan_refinement(samples, k0, temperature_k=T, target_overlap=0.2, min_effective_samples=10)
    assert plan.redundant and any("多餘" in n for n in plan.notes)


def test_per_window_k_in_wham_and_mbar():
    """WHAM/MBAR accept one k per window (stiffer springs from refinement) and recover the profile."""
    from md20.sampling.pmf import pmf_from_windows
    prof = PROFILES["sharp"]
    samples, ks, _ = run_adaptive(COARSE, 1000.0, prof=prof, target_overlap=0.2, min_effective_samples=50)
    assert len(set(ks.values())) > 1
    for mbar in (False, True):
        res = pmf_from_windows(samples, force_constant_kj_mol_nm2=ks, temperature_k=T, n_bootstrap=0, prefer_mbar=mbar)
        g, W = np.asarray(res.grid_nm), np.asarray(res.pmf_kj_mol)
        m = np.isfinite(W) & (g > 0.47) & (g < 1.5)
        ref = prof(g[m]) - prof(g[m]).min()
        W = W[m] - W[m].min()
        assert np.sqrt(np.mean((W - ref) ** 2)) < 1.0, (mbar, res.method)


# --------------------------------------------------------------------------- manual range + live coverage
def test_manual_range_fills_the_break_the_user_points_at():
    """The student sees a break on the coverage chart and asks to resample a–b: windows cover it and the break closes."""
    prof = PROFILES["sharp"]
    samples = _old_rule(prof, COARSE)
    ks = {c: 1000.0 for c in samples}
    lo, hi = continuity_report(samples)["breaks"][0]
    plan = plan_range(lo - 0.02, hi + 0.02, samples, ks, temperature_k=T)
    assert plan["k"] > 1000.0 and plan["breaks_in_range"]            # windows there slid away → stiffer
    assert all(lo - 0.05 <= w["center"] <= hi + 0.05 for w in plan["windows"])
    for i, w in enumerate(plan["windows"]):
        samples[w["center"]] = sample(w["center"], w["k"], seed=500 + i, prof=prof)
        ks[w["center"]] = w["k"]
    assert continuity_report(samples)["continuous"]
    with pytest.raises(ValueError):
        plan_range(0.6, 0.6, samples, ks)
    assert plan_range(1.3, 1.4, samples, ks, k=3000.0)["k"] == 3000.0    # the user's k is respected


def test_coverage_view_marks_breaks():
    prof = PROFILES["sharp"]
    samples = _old_rule(prof, COARSE)
    v = coverage_view(samples, {c: 1000.0 for c in samples})
    assert not v["continuous"] and v["breaks"]
    assert len(v["edges"]) == len(v["pooled"]) + 1 and len(v["windows"]) == len(samples)
    assert all(len(w["counts"]) == len(v["pooled"]) for w in v["windows"])
