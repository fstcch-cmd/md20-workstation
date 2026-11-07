"""D-102: remove waters OpenMM placed overlapping, before the system is built.  Root cause of the intermittent
membrane NaN (diagnosis 11/07): solvation left water O-O down to 0.178 nm (bulk ~0.28); such pairs survive
minimisation and blow up to NaN in the first MD steps — on Linux and Windows alike, depending on the build.
Pure geometry here; the real OpenMM deletion path (test_membrane_integration) goes to CI."""
import numpy as np
import pytest

from md20.build.assemble import declash_waters


def _grid(n=6, spacing=0.5):
    """A clean cubic grid of water O positions (no overlaps): nearest neighbour = spacing."""
    pts = [[x * spacing, y * spacing, z * spacing] for x in range(n) for y in range(n) for z in range(n)]
    return np.array(pts, float)


def test_clean_box_removes_nothing():
    plan = declash_waters(_grid(), None, None)
    assert plan["remove"] == [] and plan["min_oo_nm"] is None


def test_one_overlapping_pair_drops_exactly_one_higher_index():
    o = _grid(spacing=0.5)                              # wide grid so the extra water clashes with ONE O only
    o = np.vstack([o, o[10] + [0.0, 0.0, 0.178]])      # a water almost on top of O#10 (the reported 0.178 nm)
    plan = declash_waters(o, None, None, o_o_min_nm=0.21)
    assert plan["remove"] == [len(o) - 1]              # the added (higher-index) water goes, the original stays
    assert plan["min_oo_nm"] == pytest.approx(0.178, abs=1e-3)


def test_threshold_leaves_borderline_contacts():
    o = np.array([[0, 0, 0], [0.23, 0, 0]], float)     # 0.23 nm: close but not a clash
    assert declash_waters(o, None, None, o_o_min_nm=0.21)["remove"] == []


def test_triple_pileup_resolves_to_one_survivor():
    o = np.array([[0, 0, 0], [0.1, 0, 0], [0.18, 0, 0]], float)   # three waters piled up
    plan = declash_waters(o, None, None, o_o_min_nm=0.21)
    assert len(plan["remove"]) == 2 and 0 not in plan["remove"]   # the lowest-index survivor kept


def test_minimum_image_across_the_periodic_boundary():
    box = np.array([2.0, 2.0, 2.0])
    o = np.array([[0.05, 1.0, 1.0], [1.97, 1.0, 1.0]], float)     # 0.08 nm apart across the x boundary
    plan = declash_waters(o, None, box, o_o_min_nm=0.21)
    assert plan["remove"] == [1] and plan["min_oo_nm"] == pytest.approx(0.08, abs=1e-3)


def test_inter_molecular_oh_overlap_is_caught():
    o = np.array([[0, 0, 0], [0.26, 0, 0]], float)               # O-O fine (0.26)
    oh = np.array([[[0.096, 0, 0], [-0.03, 0.09, 0]],            # water 0's H's
                   [[0.13, 0, 0], [0.29, 0.09, 0]]])             # water 1's H at 0.13 from water 0's O
    plan = declash_waters(o, oh, None, o_o_min_nm=0.21, oh_min_nm=0.14)
    assert plan["remove"] == [1]


def test_removes_a_realistic_fraction_and_clears_the_minimum():
    rng = np.random.default_rng(0)
    o = _grid(8, 0.3)
    bad = np.array([o[k] + rng.normal(0, 0.05, 3) for k in rng.choice(len(o), 20, replace=False)])  # 20 near-duplicates
    allo = np.vstack([o, bad])
    plan = declash_waters(allo, None, None, o_o_min_nm=0.21)
    assert 15 <= len(plan["remove"]) <= 25
    kept = np.delete(allo, plan["remove"], axis=0)
    d = np.linalg.norm(kept[:, None] - kept[None], axis=2)
    np.fill_diagonal(d, 9)
    assert d.min() >= 0.21 - 1e-6                                 # no clash left among the survivors
