"""D-158: OpenMM's addSolvent does not enforce a minimum ion–ion separation, so two ions occasionally land closer
than a contact ion pair (< ION_ION_MIN_NM).  A water removal cannot fix an ion–ion overlap.  The general build-stage
repair (the water-declash principle applied to ions) relocates one ion of each overlapping pair to a free water site
that clears every ion; composition (ion count, net charge, ionic strength) is unchanged.  Pure geometry; the OpenMM
apply goes to CI."""
import numpy as np
import pytest

from md20.build.assemble import ION_ION_MIN_NM, plan_ion_declash


def _grid(n=6, spacing=0.4):
    return np.array([[x * spacing, y * spacing, z * spacing] for x in range(n) for y in range(n) for z in range(n)], float)


def test_no_overlap_is_a_no_op():
    ions = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])    # 1 nm apart
    r = plan_ion_declash(ions, _grid(), None)
    assert r["moves"] == [] and r["remove_waters"] == [] and r["unresolved"] == [] and r["n_pairs"] == 0


def test_overlapping_pair_relocates_one_ion_to_a_clearing_water():
    water = _grid()                                        # a 0.4 nm water lattice (plenty of free sites)
    ions = np.array([[1.20, 1.20, 1.20], [1.20, 1.20, 1.36]])   # 0.16 nm apart < 0.22: an overlap
    r = plan_ion_declash(ions, water, None)
    assert r["n_pairs"] == 1 and len(r["moves"]) == 1 and len(r["remove_waters"]) == 1 and r["unresolved"] == []
    assert r["min_ion_ion_nm"] == pytest.approx(0.16, abs=1e-3)
    moved_i, water_j, new_xyz = r["moves"][0]
    # the moved ion now sits on that water's site and clears the other ion
    assert np.allclose(new_xyz, water[water_j])
    other = ions[1 - moved_i]
    assert np.linalg.norm(np.asarray(new_xyz) - other) >= ION_ION_MIN_NM


def test_relocation_target_clears_every_ion_not_just_the_partner():
    water = _grid()
    # three ions: 0 and 1 overlap; 2 sits exactly on a nearby free water the mover must therefore avoid
    ions = np.array([[0.80, 0.80, 0.80], [0.80, 0.80, 0.94], [1.60, 1.60, 1.60]])
    r = plan_ion_declash(ions, water, None)
    assert len(r["moves"]) == 1 and not r["unresolved"]
    _i, _w, new_xyz = r["moves"][0]
    kept = np.asarray(new_xyz)
    # clears BOTH other ions
    for k in (1, 2):
        assert np.linalg.norm(kept - ions[k]) >= ION_ION_MIN_NM


def test_no_free_site_is_unresolved_so_the_caller_can_block():
    # only two candidate waters, both on top of the two ions → no site clears everything
    ions = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 0.16]])
    water = ions.copy()
    r = plan_ion_declash(ions, water, None)
    assert r["moves"] == [] and len(r["unresolved"]) == 1


def test_used_waters_are_not_reused_as_donors():
    water = _grid()
    ions = np.array([[1.20, 1.20, 1.20], [1.20, 1.20, 1.36]])
    # mark every water except a couple as already-removed; the mover must pick one of the remaining free ones
    free = [10, 200]
    used = [i for i in range(len(water)) if i not in free]
    r = plan_ion_declash(ions, water, None, used_waters=used)
    assert len(r["moves"]) == 1
    _i, w, _x = r["moves"][0]
    assert w in free


def test_periodic_box_is_respected():
    box = np.array([2.0, 2.0, 2.0])
    # two ions that look 1.84 nm apart but are 0.16 nm across the periodic boundary
    ions = np.array([[0.08, 0.5, 0.5], [1.92, 0.5, 0.5]])
    water = _grid(n=5, spacing=0.4)
    r = plan_ion_declash(ions, water, box)
    assert r["n_pairs"] == 1 and r["min_ion_ion_nm"] == pytest.approx(0.16, abs=1e-3)
