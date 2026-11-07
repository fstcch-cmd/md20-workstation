"""D-115: an ion placed on a water (OpenMM adds ions by replacing waters; a replaced member of an overlapping water
pair leaves the ion sitting on the other water — CI diagnosis: Cl–O 0.193 nm, then chain-4 waters at ~100 nm/ps and
NaN within 10–40 steps).  D-102's water–water check cannot see it.  Pure geometry; the real path goes to CI."""
import numpy as np
import pytest

from md20.build.assemble import ION_O_MIN_NM, declash_waters, ion_water_clashes


def _grid(n=5, spacing=0.5):
    return np.array([[x * spacing, y * spacing, z * spacing] for x in range(n) for y in range(n) for z in range(n)], float)


def test_cl_on_a_water_removes_that_water_and_keeps_the_ion():
    o = _grid()
    ion = o[7] + [0.0, 0.0, 0.193]                         # the distance seen in the CI NaN build
    r = ion_water_clashes(ion[None], ["Cl"], o, None, None)
    assert r["remove"] == [7] and r["pairs"][0][3] == "O" and r["min_by_ion"]["Cl"] == pytest.approx(0.193, abs=1e-3)


def test_normal_first_shell_is_left_alone():
    o = _grid(spacing=1.0)                                 # only one water near the ion
    for el, peak in (("Na", 0.24), ("Cl", 0.32), ("K", 0.28)):
        r = ion_water_clashes((o[7] + [0, 0, peak])[None], [el], o, None, None)
        assert r["remove"] == [], el


def test_anion_water_hydrogen_clash():
    o = _grid()
    oh = np.full((len(o), 2, 3), 1e6)
    oh[3, 0] = o[3] + [0.0957, 0, 0]
    ion = oh[3, 0] + [0.15, 0, 0]                          # Cl 0.15 nm from an H, ~0.25 from its O
    r = ion_water_clashes(ion[None], ["Cl"], o, oh, None)
    assert 3 in r["remove"] and any(p[3] == "H" for p in r["pairs"])
    # a cation is not checked against H (water H points away from cations)
    assert ion_water_clashes(ion[None], ["Na"], o, oh, None)["remove"] == []


def test_minimum_image_across_the_box():
    box = np.array([2.5, 2.5, 2.5])
    o = _grid()                                            # 0 … 2.0 nm
    ion = np.array([[2.5 - 0.09, 0.0, 0.0]])               # 0.09 nm from O#0 through the periodic boundary
    assert ion_water_clashes(ion, ["Na"], o, None, box)["remove"] == [0]
    assert ion_water_clashes(ion, ["Na"], o, None, None)["remove"] == []


def test_waters_already_removed_are_not_counted_twice():
    o = _grid()
    o2 = np.vstack([o, o[7] + [0, 0, 0.18]])              # water–water overlap → declash drops the extra one
    plan = declash_waters(o2, None, None)
    r = ion_water_clashes((o2[-1] + [0, 0, 0.01])[None], ["Na"], o2, None, None, skip_waters=plan["remove"])
    assert len(o2) - 1 not in r["remove"] and 7 in r["remove"]


def test_two_ions_on_top_of_each_other_are_unresolvable():
    r = ion_water_clashes(np.array([[1.0, 1.0, 1.0], [1.0, 1.0, 1.1]]), ["Na", "Cl"], _grid(), None, None)
    assert r["ion_ion"] and r["ion_ion"][0][2] == pytest.approx(0.1)


def test_thresholds_are_below_every_first_shell_peak():
    peak = {"Li": 0.20, "Na": 0.24, "K": 0.28, "Rb": 0.29, "Cs": 0.31, "Mg": 0.21, "Ca": 0.24, "Zn": 0.21,
            "F": 0.27, "Cl": 0.32, "Br": 0.34, "I": 0.36}
    assert set(peak) == set(ION_O_MIN_NM)
    assert all(0.7 * peak[e] <= ION_O_MIN_NM[e] <= 0.85 * peak[e] for e in peak)
