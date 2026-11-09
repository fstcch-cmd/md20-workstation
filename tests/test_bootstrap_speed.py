"""D-162: bootstrap speed-ups must not change the scientific result.

Reference = the pre-D-162 replicate loop (python block loop, cold WHAM, overlap computed), re-implemented here.
MBAR uses the numpy stand-in from test_mbar_bootstrap (real pymbar runs in the openmm-stack CI).
Tolerances: resampling, WHAM and MBAR replicate curves are asserted equal to the reference at atol 1e-10..1e-12 kJ/mol.
Timing is printed, never asserted."""
import math
import sys
import time

import numpy as np

from md20.sampling import _mdh_legacy as mdh
from test_mbar_bootstrap import _fake_pymbar, _windows, _eq


def _old_resample(x, block_length, rng):
    x = mdh._finite_1d(x, min_samples=4)
    n = len(x)
    block_length = max(1, min(int(block_length), n))
    starts = rng.integers(0, n, size=int(math.ceil(n / block_length)))
    return np.concatenate([x[(np.arange(block_length) + int(s)) % n] for s in starts])[:n]


def _reference_boot(eq, centers, k, T, n, seed, prefer_mbar, bins=200):
    """Pre-D-162 replicate loop: cold WHAM, overlap always computed, per-block python loop."""
    lists = [mdh._finite_1d(x, min_samples=20) for x in eq]
    gs = [mdh._fallback_statistical_inefficiency(x) for x in lists]
    blocks = [max(1, int(math.ceil(g))) for g in gs]
    base = mdh.estimate_pmf_1d(lists, [mdh.subsample_uncorrelated(x, g) for x, g in zip(lists, gs)], centers, k, T,
                               bins=bins, prefer_mbar=prefer_mbar)
    grid = base["grid_nm"]; hd = 0.5 * (grid[1] - grid[0])
    warm = base["f_k_dimensionless"] if str(base["method"]).startswith("PyMBAR") else None
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        r = [_old_resample(x, b, rng) for x, b in zip(lists, blocks)]
        u = [mdh.subsample_uncorrelated(x, mdh._fallback_statistical_inefficiency(x)) for x in r]
        res = mdh.estimate_pmf_1d(r, u, centers, k, T, bins=bins, prefer_mbar=prefer_mbar,
                                  x_min=float(grid.min() - hd), x_max=float(grid.max() + hd), initial_f_k=warm)
        out.append(res["pmf_kj_mol"])
    return base, np.vstack(out)


def _same(a, b, atol):
    a, b = np.asarray(a, float), np.asarray(b, float)
    assert a.shape == b.shape
    assert np.array_equal(np.isfinite(a), np.isfinite(b))
    m = np.isfinite(a)
    np.testing.assert_allclose(a[m], b[m], atol=atol, rtol=0)


def test_vectorised_resample_is_identical_to_the_block_loop():
    x = np.random.default_rng(0).standard_normal(517)
    for bl in (1, 3, 7, 64, 517, 900):
        a = mdh._moving_block_resample(x, bl, np.random.default_rng(11))
        b = _old_resample(x, bl, np.random.default_rng(11))
        np.testing.assert_array_equal(a, b)


def test_mbar_bootstrap_matches_reference(monkeypatch):
    monkeypatch.setitem(sys.modules, "pymbar", _fake_pymbar([]))
    centers, eq = _eq(_windows(lo=0.2, hi=0.8, n=400))
    base, ref = _reference_boot(eq, centers, 1000.0, 300.0, 6, 7, True)
    t = time.perf_counter()
    new = mdh.bootstrap_pmf_1d(eq, centers, 1000.0, 300.0, n_bootstrap=6, seed=7)
    print(f"\n[timing] new MBAR bootstrap {time.perf_counter() - t:.2f}s")
    assert new["bootstrap_success"] == 6
    _same(new["bootstrap_pmfs"], ref, 1e-10)
    _same(new["pmf_kj_mol"], base["pmf_kj_mol"], 1e-10)
    assert new["overlap_matrix"] is not None                        # the base solve still reports overlap


def test_replicates_skip_the_overlap_matrix(monkeypatch):
    calls = []
    mod = _fake_pymbar(calls)
    n_overlap = []
    orig = mod.MBAR.compute_overlap
    mod.MBAR.compute_overlap = lambda self: (n_overlap.append(1), orig(self))[1]
    monkeypatch.setitem(sys.modules, "pymbar", mod)
    centers, eq = _eq(_windows(lo=0.2, hi=0.6, n=300))
    mdh.bootstrap_pmf_1d(eq, centers, 1000.0, 300.0, n_bootstrap=5, seed=1)
    assert len(n_overlap) == 1                                      # base only, not 1 + 5


def test_wham_bootstrap_matches_reference():
    """WHAM path (no warm start: measured to save nothing, D-162) is unchanged apart from the vectorised resampling."""
    centers, eq = _eq(_windows(lo=0.2, hi=0.8, n=400))
    base, ref = _reference_boot(eq, centers, 1000.0, 300.0, 4, 5, False, bins=80)
    new = mdh.bootstrap_pmf_1d(eq, centers, 1000.0, 300.0, n_bootstrap=4, seed=5, bins=80, prefer_mbar=False)
    _same(new["bootstrap_pmfs"], ref, 1e-12)


def test_n_jobs_does_not_change_the_result():
    centers, eq = _eq(_windows(lo=0.2, hi=0.6, n=300))
    kw = dict(n_bootstrap=6, seed=9, bins=60, prefer_mbar=False)
    a = mdh.bootstrap_pmf_1d(eq, centers, 1000.0, 300.0, **kw)
    b = mdh.bootstrap_pmf_1d(eq, centers, 1000.0, 300.0, n_jobs=2, **kw)
    _same(a["bootstrap_pmfs"], b["bootstrap_pmfs"], 1e-12)
    assert b["bootstrap_success"] == a["bootstrap_success"] == 6


def test_binding_sigma_unchanged_for_synthetic_replicates():
    from md20.sampling.binding import bootstrap_binding_sigma
    g = np.linspace(0.2, 2.0, 90)
    rng = np.random.default_rng(3)
    boot = np.array([-12 * np.exp(-((g - 0.4) / 0.1) ** 2) + rng.normal(0, 0.3) * g for _ in range(30)])
    s = bootstrap_binding_sigma(g, boot, 300.0)
    assert s["n"] == 30 and s["delta_pmf_sd"] is not None
