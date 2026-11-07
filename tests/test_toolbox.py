"""D-105: analysis toolbox — tICA, k-means, MSM eligibility, H-bond network, hydration sites (pure numpy)."""
import numpy as np


def _two_state_chain(n, p, seed=1):
    rng = np.random.default_rng(seed)
    s = np.zeros(n, int)
    for i in range(1, n):
        s[i] = 1 - s[i - 1] if rng.random() < p else s[i - 1]
    return s


def test_tica_finds_the_slow_coordinate_not_the_large_one():
    from md20.analysis.toolbox import tica
    rng = np.random.default_rng(0)
    s = _two_state_chain(3000, 0.01)
    slow = s + 0.1 * rng.normal(size=3000)              # small variance, slow switching
    fast = 5.0 * rng.normal(size=3000)                  # large variance, no memory (PCA would pick this)
    X = np.c_[fast, slow, rng.normal(size=(3000, 3))]
    r = tica(X, lag=5, n_components=2, n_pca=5)
    assert r["status"] == "ok"
    c = abs(np.corrcoef(np.asarray(r["projection"])[:, 0], slow)[0, 1])
    assert c > 0.9
    assert r["timescales_frames"][0] > 20                # true relaxation time −1/ln(1−2p) ≈ 49.5 frames


def test_tica_refuses_too_short_input():
    from md20.analysis.toolbox import tica
    assert tica(np.zeros((40, 3)), lag=10)["status"] == "insufficient"


def test_kmeans_is_deterministic_and_separates_blobs():
    from md20.analysis.toolbox import kmeans
    rng = np.random.default_rng(3)
    X = np.r_[rng.normal(0, 0.1, (50, 2)), rng.normal(5, 0.1, (50, 2))]
    a, _ = kmeans(X, 2, seed=7)
    b, _ = kmeans(X, 2, seed=7)
    assert np.array_equal(a, b) and len(set(a[:50])) == 1 and len(set(a[50:])) == 1 and a[0] != a[-1]


def test_msm_recovers_a_known_timescale_and_labels_it_exploratory():
    from md20.analysis.toolbox import msm
    d = _two_state_chain(20000, 0.01)
    r = msm(d, lags=[1, 5, 10, 20], n_states=2, dt_ns=0.01)
    true_ns = -0.01 / np.log(1 - 2 * 0.01)
    assert r["eligibility"] == "exploratory" and r["its_flat"]
    assert abs(r["its_ns"][-1][0] - true_ns) / true_ns < 0.25
    assert abs(r["stationary"][0] - 0.5) < 0.1


def test_msm_says_unresolved_or_insufficient_instead_of_printing_rates():
    from md20.analysis.toolbox import msm
    rare = _two_state_chain(600, 0.002, seed=5)          # about one switch in the whole run
    r = msm(rare, lags=[1, 2, 5], n_states=2, dt_ns=0.01)
    assert r["eligibility"] in ("insufficient", "unresolved")
    stuck = np.zeros(500, int)
    assert msm(stuck, lags=[1, 2], n_states=3, dt_ns=0.01)["eligibility"] == "insufficient"


def test_hbond_network_edges_hubs_components():
    from md20.analysis.toolbox import hbond_network
    frames = [[("ASP10", "ARG20"), ("ARG20", "GLU30"), ("SER5", "THR6")] for _ in range(8)] + \
             [[("ASP10", "ARG20"), ("LYS40", "GLU30")] for _ in range(2)]
    r = hbond_network(frames, min_occupancy=0.3)
    pairs = {tuple(e[:2]): e[2] for e in r["edges"]}
    assert pairs[("ARG20", "ASP10")] == 1.0 and pairs[("ARG20", "GLU30")] == 0.8 and ("GLU30", "LYS40") not in pairs
    assert r["hubs"][0] == ["ARG20", 2]
    assert ["ARG20", "ASP10", "GLU30"] in r["components"]
    assert hbond_network([])["status"] == "insufficient"


def test_hydration_finds_a_bound_water_and_not_bulk_noise():
    from md20.analysis.toolbox import hydration_sites, BULK_WATER_PER_NM3
    rng = np.random.default_rng(4)
    site = np.array([0.4, 0.0, 0.0])
    frames = []
    for _ in range(200):
        n_bulk = rng.poisson(BULK_WATER_PER_NM3 * (2.4 ** 3))
        bulk = rng.uniform(-1.2, 1.2, (n_bulk, 3))
        frames.append(np.r_[bulk, site + rng.normal(0, 0.03, (1, 3))])
    r = hydration_sites(frames, [0, 0, 0], radius_nm=1.0, min_ratio=3.0)
    assert r["status"] == "ok" and r["sites"]
    best = r["sites"][0]
    assert np.linalg.norm(np.array(best["xyz_nm"]) - site) < 0.12 and best["occupancy"] > 0.9
    assert len(r["sites"]) <= 3                              # bulk fluctuations do not make many fake sites
    assert hydration_sites(frames[:5], [0, 0, 0])["status"] == "insufficient"
