"""D-62: MBAR bootstrap warm start / solver reuse, and the PMF-must-span-the-sampled-range guard.

pymbar is replaced by a small numpy stand-in (self-consistent MBAR iteration) so these run without pymbar; the real
pymbar path is exercised by the openmm-stack CI jobs."""
import sys
import types

import numpy as np
import pytest

from md20.sampling import _mdh_legacy as mdh
from md20.sampling.pmf import pmf_from_windows, pmf_coverage, pmf_span_needed

KT = mdh.KB_KJ_MOL_K * 300.0


def _windows(k=1000.0, lo=0.2, hi=1.5, step=0.05, n=600, seed=1):
    rng = np.random.default_rng(seed)
    centers = np.round(np.arange(lo, hi + 1e-9, step), 4)
    sig = np.sqrt(KT / k)
    # flat free energy: each window samples a Gaussian at its centre (AR(1)-correlated like MD)
    out = {}
    for c in centers:
        x = np.empty(n); x[0] = c
        for i in range(1, n):
            x[i] = c + 0.6 * (x[i - 1] - c) + np.sqrt(1 - 0.36) * sig * rng.standard_normal()
        out[float(c)] = x
    return out


def _fake_pymbar(calls, *, fallback_without_warm=False, reject=(), bad_fk=False):
    class MBAR:
        def __init__(self, u_kn, N_k, maximum_iterations=10000, relative_tolerance=1e-7, verbose=False, **kw):
            for name in reject:
                if name in kw:
                    raise TypeError(f"unexpected keyword {name}")
            calls.append(dict(kw))
            if fallback_without_warm and "initial_f_k" not in kw and kw.get("solver_protocol") is None:
                print("Failed to reach a solution to within tolerance with hybr: trying next method")
            K = len(N_k)
            self._u, self._N = np.asarray(u_kn, float), np.asarray(N_k, float)
            if bad_fk:
                self.f_k = np.linspace(0.0, 4000.0, K)             # wildly wrong: far windows' weights underflow
                return
            f = np.zeros(K) if "initial_f_k" not in kw else np.asarray(kw["initial_f_k"], float).copy()
            logN = np.log(N_k)
            for _ in range(2000):
                a = logN[:, None] + f[:, None] - u_kn
                m = a.max(0)
                log_den = m + np.log(np.exp(a - m).sum(0))
                b = -u_kn - log_den
                mb = b.max(1)
                f_new = -(mb + np.log(np.exp(b - mb[:, None]).sum(1)))
                f_new -= f_new[0]
                if np.max(np.abs(f_new - f)) < 1e-9:
                    f = f_new
                    break
                f = f_new
            self.f_k = f

            self._u, self._N = np.asarray(u_kn, float), np.asarray(N_k, float)

        def compute_overlap(self):
            # D-113: the real MBAR definition, O_ij = sum_n W_ni W_nj N_j (W = per-sample weights in each state)
            f, u, N = np.asarray(self.f_k, float), self._u, self._N
            a = np.log(N)[:, None] + f[:, None] - u
            m = a.max(0)
            log_den = m + np.log(np.exp(a - m).sum(0))
            W = np.exp(f[:, None] - u - log_den).T                      # (n_samples, K)
            O = (W.T @ W) * N[None, :]
            ev = np.sort(np.linalg.eigvals(O).real)[::-1]
            return {"matrix": O, "scalar": float(1.0 - ev[1]), "eigenvalues": ev}

    mod = types.ModuleType("pymbar")
    mod.MBAR = MBAR
    return mod


def _eq(samples):
    c = sorted(samples)
    return c, [samples[x] for x in c]


def test_bootstrap_replicates_warm_start_from_base_fk(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "pymbar", _fake_pymbar(calls))
    centers, eq = _eq(_windows())
    res = mdh.bootstrap_pmf_1d(eq, centers, 1000.0, 300.0, n_bootstrap=8, seed=3)
    assert res["method"] == "PyMBAR-MBAR" and res["bootstrap_success"] == 8
    assert "initial_f_k" not in calls[0]                                   # base: cold
    assert all("initial_f_k" in c for c in calls[1:]) and len(calls) == 9  # every replicate: warm
    np.testing.assert_allclose(calls[1]["initial_f_k"], res["f_k_dimensionless"])
    assert res["bootstrap_warm_start"] is True and res["bootstrap_solver_protocol"] is None


def test_base_fallback_sends_replicates_to_robust_protocol(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "pymbar", _fake_pymbar(calls, fallback_without_warm=True))
    centers, eq = _eq(_windows())
    res = mdh.bootstrap_pmf_1d(eq, centers, 1000.0, 300.0, n_bootstrap=5, seed=3)
    assert res["solver_fallback"] is True
    assert all(c.get("solver_protocol") == "robust" for c in calls[1:])
    assert res["bootstrap_solver_protocol"] == "robust"


def test_pymbar_without_the_new_arguments_still_works(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "pymbar", _fake_pymbar(calls, reject=("initial_f_k", "solver_protocol")))
    centers, eq = _eq(_windows())
    res = mdh.bootstrap_pmf_1d(eq, centers, 1000.0, 300.0, n_bootstrap=4, seed=3)
    assert res["bootstrap_success"] == 4 and all(c == {} for c in calls)


def test_warm_start_does_not_change_the_answer(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "pymbar", _fake_pymbar(calls))
    centers, eq = _eq(_windows(lo=0.2, hi=0.8))
    unc = [mdh.subsample_uncorrelated(x, mdh._fallback_statistical_inefficiency(x)) for x in eq]
    cold = mdh.mbar_pmf_1d(unc, centers, 1000.0, 300.0)
    warm = mdh.mbar_pmf_1d(unc, centers, 1000.0, 300.0, initial_f_k=cold["f_k_dimensionless"])
    np.testing.assert_allclose(warm["f_k_dimensionless"], cold["f_k_dimensionless"], atol=1e-6)
    m = np.isfinite(cold["pmf_kj_mol"]) & np.isfinite(warm["pmf_kj_mol"])
    np.testing.assert_allclose(warm["pmf_kj_mol"][m], cold["pmf_kj_mol"][m], atol=1e-6)


def test_truncated_mbar_pmf_is_replaced_by_wham_and_recorded(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "pymbar", _fake_pymbar(calls, bad_fk=True))
    samples = _windows()
    res = pmf_from_windows(samples, force_constant_kj_mol_nm2=1000.0, temperature_k=300.0, n_bootstrap=3)
    t = res.quality.get("pmf_truncated")
    assert t is not None and t["replaced_by"] == "WHAM", t
    assert t["finite_nm"][1] < t["sampled_nm"][1] - 0.1                     # MBAR really stopped early
    fin = np.isfinite(res.pmf_kj_mol)
    assert res.grid_nm[fin].max() >= max(samples) - 0.02 and "WHAM" in res.method
    # flat landscape → no fake well: the PMF over the sampled range stays within a few kT
    lo, hi = pmf_span_needed([samples[c] for c in sorted(samples)])
    inside = fin & (res.grid_nm >= lo) & (res.grid_nm <= hi)
    assert np.ptp(res.pmf_kj_mol[inside]) < 6 * KT


def test_coverage_helper():
    g = np.linspace(0.1, 1.0, 10)
    w = g.copy(); w[6:] = np.nan
    assert pmf_coverage({"grid_nm": g, "pmf_kj_mol": w}, 0.2, 0.9)["ok"] is False
    assert pmf_coverage({"grid_nm": g, "pmf_kj_mol": g}, 0.2, 0.9)["ok"] is True


def test_timing_and_solver_info_reach_the_quality_report(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "pymbar", _fake_pymbar(calls))
    res = pmf_from_windows(_windows(lo=0.2, hi=0.6), force_constant_kj_mol_nm2=1000.0, temperature_k=300.0, n_bootstrap=3)
    sol = res.quality["solver"]
    assert sol["bootstrap_warm_start"] is True and sol["bootstrap_success"] == 3
    assert set(sol["timing_s"]) == {"base_solve", "bootstrap_total", "per_replicate"}


def test_mbar_overlap_matrix_reaches_the_quality_report(monkeypatch):
    """D-113: the matrix mbar_pmf_1d computes is kept (it used to be dropped) and feeds the assessment."""
    from md20.sampling.assessment import assess_pmf
    monkeypatch.setitem(sys.modules, "pymbar", _fake_pymbar([]))
    res = pmf_from_windows(_windows(lo=0.2, hi=0.6), force_constant_kj_mol_nm2=1000.0, temperature_k=300.0, n_bootstrap=0)
    mo = res.quality["mbar_overlap"]
    M = np.asarray(mo["matrix"])
    assert M.shape == (len(mo["centers_nm"]),) * 2 and np.allclose(M.sum(1), 1.0, atol=1e-3)   # rows of O sum to 1
    assert mo["min_adjacent"] > 0.03 and 0 < mo["scalar"] <= 1
    a = assess_pmf({"method": res.method, "quality": res.quality})
    assert next(d for d in a["diagnostics"] if d["id"] == "mbar_overlap")["status"] == "pass"


def test_mbar_overlap_flags_a_gap_the_estimator_cannot_bridge(monkeypatch):
    from md20.sampling.assessment import assess_pmf
    monkeypatch.setitem(sys.modules, "pymbar", _fake_pymbar([]))
    w = _windows(lo=0.2, hi=0.6)
    gap = {c: (x + 0.5 if c > 0.41 else x) for c, x in w.items()}      # the upper half shifted 0.5 nm away: no overlap
    res = pmf_from_windows(gap, force_constant_kj_mol_nm2=1000.0, temperature_k=300.0, n_bootstrap=0)
    assert res.quality["mbar_overlap"]["min_adjacent"] < 0.03
    a = assess_pmf({"method": res.method, "quality": res.quality})
    assert next(d for d in a["diagnostics"] if d["id"] == "mbar_overlap")["status"] == "fail"
