"""D-65: ΔPMF is a well depth only when the profile is flat at the far end (checked up to the outermost window mean)."""
from types import SimpleNamespace

import numpy as np

from md20.sampling.binding import radial_pmf


def _pres(g, w, sampled_hi=None):
    q = {"sampled_nm": [float(g[0]), sampled_hi]} if sampled_hi is not None else {}
    return SimpleNamespace(grid_nm=g, pmf_kj_mol=w, err_kj_mol=None, quality=q)


def _profile(g, depth=40.0, width=0.15, r0=0.25):
    raw = depth * (1 - np.exp(-((g - r0).clip(0) / width) ** 2))   # well at r0, flat beyond ~0.6 nm
    return raw - 2 * 2.494 * np.log(g)                               # the raw PMF carries −2kT ln r


def test_flat_tail_is_a_plateau():
    g = np.linspace(0.15, 1.8, 200)
    rp = radial_pmf(_pres(g, _profile(g)), 300.0)
    assert rp["plateau"] and abs(rp["delta_pmf"] - 40.0) < 3


def test_truncated_curve_is_not_a_plateau():          # laptop 3PTB: the curve stopped at ~0.5 nm while still rising
    g = np.linspace(0.15, 0.5, 60)
    rp = radial_pmf(_pres(g, _profile(g, depth=130.0, width=0.45)), 300.0)   # still climbing steeply at the cut
    assert not rp["plateau"] and rp["tail_rise_kj_mol"] > 2.5


def test_edge_bins_beyond_the_outermost_window_are_ignored():
    g = np.linspace(0.15, 1.9, 220)
    w = _profile(g)
    w[g > 1.72] -= 25 * (g[g > 1.72] - 1.72) / 0.18                   # single-window tail artefact at the very end
    assert not radial_pmf(_pres(g, w), 300.0)["plateau"]
    assert radial_pmf(_pres(g, w, sampled_hi=1.7), 300.0)["plateau"]
