"""D-144: calibration-backed behaviour of the empirical reporting thresholds (pure numpy)."""
import numpy as np

from md20.analysis.extended import cluster_sensitivity, pca_sensitivity
from md20.analysis.replica_set import CV_DIVERGENT, between_replica_stats


def _two_state_drift(n=250, nat=20, seed=3):
    """first half fluctuates along one direction, second half along an orthogonal one (slow, unconverged sampling)"""
    rng = np.random.default_rng(seed)
    X = rng.normal(scale=0.05, size=(n, nat, 3))
    a, b = np.zeros((nat, 3)), np.zeros((nat, 3))
    a[:, 0], b[:, 1] = 1.0, 1.0
    h = n // 2
    X[:h] += 1.5 * rng.normal(size=(h, 1, 1)) * a      # larger, so the pooled PC1 is a in both even and odd
    X[h:] += rng.normal(size=(n - h, 1, 1)) * b
    return X


def test_pca_consistency_uses_chronological_halves_not_interleaved():
    s = pca_sensitivity(_two_state_drift())
    assert s["interleaved_halves"]["pc1_abs_cos"] >= 0.9          # even/odd agree — subsample noise only
    assert s["block_halves"]["pc1_abs_cos"] < 0.5                  # first/second halves disagree
    assert s["consistent"] is False
    assert "not used for `consistent`" in s["interleaved_halves"]["note"]


def test_pca_consistent_for_stationary_sampling():
    rng = np.random.default_rng(0)
    X = rng.normal(scale=0.05, size=(250, 20, 3))
    d = np.zeros((20, 3)); d[:, 0] = 1.0
    X += rng.normal(size=(250, 1, 1)) * d
    assert pca_sensitivity(X)["consistent"] is True


def test_cluster_consistency_uses_chronological_halves():
    # first half all state A; second half alternates B, C: even/odd populations equal, halves differ (1.0 vs 0.5)
    lab = np.r_[np.zeros(100), np.tile([1, 2], 50)]
    D = np.where(lab[:, None] == lab[None, :], 0.5, 5.0)
    np.fill_diagonal(D, 0.0)
    c = cluster_sensitivity(D, 2.0)
    assert c["largest_population_abs_diff"] <= 0.05 and c["block_largest_population_abs_diff"] >= 0.5
    assert c["consistent"] is False


def test_cv_flag_is_a_caution_with_known_operating_characteristics():
    """n=3: the CV>0.25 flag misses half of true CV 0.30 cases and fires ~7 % at true CV 0.15 (calibration doc)"""
    rng = np.random.default_rng(20261108)
    x = rng.normal(1.0, 0.15, size=(40_000, 3))
    fp = float(((x.std(1, ddof=1) / x.mean(1)) > CV_DIVERGENT).mean())
    assert 0.04 < fp < 0.10
    assert between_replica_stats([("a", 2.0), ("b", 2.1), ("c", 1.9)])["divergent"] is False
