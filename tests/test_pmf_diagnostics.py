"""D-43: overlap connectivity by sampled distributions, explicit ΔG° withholding reasons, well-depth plausibility."""
import numpy as np

from md20.sampling import _mdh_legacy as mdh
from md20.sampling.binding import well_depth_hint


def test_slid_stiff_window_does_not_break_connectivity():
    """After refinement a stiff window can sample far from its centre (0.6 nm sampled at 0.34 nm).  Neighbours by
    centre then do not overlap, but the sampled union is continuous — the graph must say connected."""
    rng = np.random.default_rng(1)
    means = {0.30: 0.30, 0.40: 0.38, 0.50: 0.46, 0.60: 0.34, 0.70: 0.54}
    samples = {c: rng.normal(m, 0.03, 3000) for c, m in means.items()}
    rep, eq, _ = mdh.assess_umbrella_samples(samples)
    by_centre = {(p.left_center_nm, p.right_center_nm): p.overlap_coefficient for p in rep.pair_stats}
    assert by_centre[(0.5, 0.6)] < 0.1 and by_centre[(0.6, 0.7)] < 0.1          # the old centre-adjacency test fails
    assert rep.graph_connected
    # a real gap is still a gap
    gap = {0.30: rng.normal(0.30, 0.02, 3000), 0.40: rng.normal(0.36, 0.02, 3000), 0.50: rng.normal(0.60, 0.02, 3000)}
    assert not mdh.assess_umbrella_samples(gap)[0].graph_connected


def test_well_depth_hint():
    msg = well_depth_hint(80.3, 9)                      # benzamidine, laptop classroom run (D-40)
    assert msg and "80" in msg and "teaching" in msg
    assert well_depth_hint(30.0, 9) is None
    assert well_depth_hint(55.0, 9) is None             # ceiling max(40, 6.3 × 9 = 57)
    assert well_depth_hint(float("nan"), 9) is None and well_depth_hint(None, 9) is None
