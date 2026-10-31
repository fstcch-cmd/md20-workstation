"""PMF / umbrella tests on synthetic data with a known answer (no OpenMM)."""
import numpy as np
import pytest

from md20.sampling import plan_windows, pmf_from_windows, umbrella_quality

KT = 0.00831446261815324 * 300.0


def _synthetic_windows(centers, k, n=4000, seed=1, pmf_fn=None):
    """Sample x from exp(-(U(x) + k/2 (x-c)^2)/kT) by Metropolis for each window."""
    rng = np.random.default_rng(seed)
    pmf_fn = pmf_fn or (lambda x: 0.0 * x)
    out = {}
    for c in centers:
        x = c; samples = []
        for _ in range(n * 5):
            y = x + rng.normal(0, 0.03)
            du = (pmf_fn(y) + 0.5 * k * (y - c) ** 2) - (pmf_fn(x) + 0.5 * k * (x - c) ** 2)
            if du <= 0 or rng.random() < np.exp(-du / KT):
                x = y
            samples.append(x)
        out[float(c)] = np.asarray(samples[::5])
    return out


def test_plan_windows_spacing_and_overlap():
    plan = plan_windows(0.3, 1.5, force_constant_kj_mol_nm2=1000.0, target_overlap=0.25)
    assert 0.24 < plan.expected_overlap < 0.26
    assert plan.centers_nm[0] == 0.3 and plan.centers_nm[-1] == pytest.approx(1.5)
    diffs = np.diff(plan.centers_nm)[:-1]
    assert np.allclose(diffs, plan.spacing_nm)
    cv = np.linspace(0.3, 1.5, 500)
    plan2 = plan_windows(0.3, 1.5, smd_cv_nm=cv)
    assert len(plan2.seed_frames) == len(plan2.centers_nm)
    assert max(abs(np.array(plan2.seed_cv_nm) - np.array(plan2.centers_nm))) < 0.01


def test_wham_recovers_flat_pmf(tmp_path):
    centers = list(np.arange(0.5, 1.31, 0.1))
    samples = _synthetic_windows(centers, k=1000.0)
    res = pmf_from_windows(samples, force_constant_kj_mol_nm2=1000.0, temperature_k=300.0, out_dir=tmp_path,
                           n_bootstrap=20, prefer_mbar=False)
    inner = (res.grid_nm > 0.6) & (res.grid_nm < 1.2) & np.isfinite(res.pmf_kj_mol)
    assert res.delta_pmf_kj_mol < 6.0           # flat within a couple of kT (sampling noise)
    assert np.nanstd(res.pmf_kj_mol[inner]) < 1.5
    assert res.quality["graph_connected"] is True
    assert (tmp_path / "pmf.png").stat().st_size > 1000 and (tmp_path / "umbrella_histograms.png").exists()


def test_wham_recovers_harmonic_well():
    centers = list(np.arange(0.4, 1.41, 0.1))
    k_well = 300.0
    samples = _synthetic_windows(centers, k=1000.0, pmf_fn=lambda x: 0.5 * k_well * (x - 0.9) ** 2, seed=3)
    res = pmf_from_windows(samples, force_constant_kj_mol_nm2=1000.0, n_bootstrap=0, prefer_mbar=False)
    g, p = res.grid_nm, res.pmf_kj_mol
    m = np.isfinite(p) & (abs(g - 0.9) < 0.35)
    ref = 0.5 * k_well * (g[m] - 0.9) ** 2
    assert abs(g[m][np.argmin(p[m])] - 0.9) < 0.05
    assert np.sqrt(np.mean((p[m] - ref) ** 2)) < 2.5   # kJ/mol


def test_quality_detects_gap():
    centers = [0.5, 0.6, 0.7, 1.1, 1.2]          # gap between 0.7 and 1.1
    samples = _synthetic_windows(centers, k=1000.0, n=1500)
    rep, _, _ = umbrella_quality(samples)
    assert rep["graph_connected"] is False
    assert any(0.7 < c < 1.1 for c in rep["insert_centers_nm"])
