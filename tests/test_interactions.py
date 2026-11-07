"""D-97: chemically defined interactions, complete dynamic contacts (A5, A6) and persistence with censoring (F09, A12).
Spec acceptance Tests 5, 6, 19, 25, 36."""
import numpy as np
import pytest

from md20.analysis import interactions as IX
from md20.analysis.persistence import events, persistence_for_runs, survival, kaplan_meier


def _atoms():
    # 0 ligand O (carboxylate-like), 1 ligand C, 2 ligand N; protein: 10 ASP OD1 chain A, 11 ASP OD1 chain B (same number!),
    # 12 LYS NZ, 13 LEU CD1, 14 SER OG
    return {0: {"element": "O"}, 1: {"element": "C"}, 2: {"element": "N"},
            10: {"element": "O", "resname": "ASP", "name": "OD1", "res_key": IX.residue_key("A", "ASP", 189)},
            11: {"element": "O", "resname": "ASP", "name": "OD1", "res_key": IX.residue_key("B", "ASP", 189)},
            12: {"element": "N", "resname": "LYS", "name": "NZ", "res_key": IX.residue_key("A", "LYS", 60)},
            13: {"element": "C", "resname": "LEU", "name": "CD1", "res_key": IX.residue_key("A", "LEU", 99)},
            14: {"element": "O", "resname": "SER", "name": "OG", "res_key": IX.residue_key("A", "SER", 190)}}


def _xyz(frames):
    X = np.full((len(frames), 15, 3), 50.0)
    for f, pos in enumerate(frames):
        for i, p in pos.items():
            X[f, i] = p
    return X


def test_anionic_ligand_near_asp_is_not_a_salt_bridge_but_near_lys_is():
    """Test 5: charge signs decide; an anionic ligand next to deprotonated ASP is like-charge proximity."""
    X = _xyz([{0: [0, 0, 0], 10: [0.3, 0, 0], 12: [-0.3, 0, 0]}])
    dyn = IX.dynamic_pairs(X, [0, 1, 2], [10, 11, 12, 13, 14])
    fp = IX.fingerprint(dyn, _atoms(), ligand_charges={0: -1})
    occ = fp["occupancy"]
    assert occ["like_charge_proximity"] == {"A:ASP189": 1.0}
    assert occ["salt_bridge"] == {"A:LYS60": 1.0} and "A:ASP189" not in occ["salt_bridge"]


def test_neutral_ligand_and_unknown_ligand_charge_never_make_salt_bridges():
    X = _xyz([{0: [0, 0, 0], 12: [0.3, 0, 0]}])
    dyn = IX.dynamic_pairs(X, [0], [12])
    assert IX.fingerprint(dyn, _atoms(), ligand_charges={})["occupancy"]["salt_bridge"] == {}          # neutral
    unk = IX.fingerprint(dyn, _atoms(), ligand_charges=None)
    assert unk["occupancy"]["salt_bridge"] == {} and unk["occupancy"]["charged_proximity_ligand_charge_unknown"]
    assert "unknown" in unk["ligand_charge"]


def test_distance_only_polar_pair_is_proximity_not_hbond_and_types_coexist():
    """Test 5: a N/O pair at 3.0 Å is polar_proximity, never hbond; a salt bridge and polar proximity coexist."""
    X = _xyz([{0: [0, 0, 0], 12: [0.30, 0, 0], 14: [0, 0.30, 0]}])
    fp = IX.fingerprint(IX.dynamic_pairs(X, [0], [12, 14]), _atoms(), ligand_charges={0: -1})
    assert "hbond" not in fp["occupancy"] and "hbond" not in fp["labels"]
    i = fp["residues"].index("A:LYS60")
    v = fp["bitmask"][i][0]
    assert v & IX.BIT["salt_bridge"] and v & IX.BIT["polar_proximity"]                      # multi-label, not ranked
    assert fp["occupancy"]["polar_proximity"]["A:SER190"] == 1.0


def test_same_residue_number_on_two_chains_stays_distinct():
    """Test 6."""
    X = _xyz([{0: [0, 0, 0], 10: [0.3, 0, 0], 11: [-0.3, 0, 0]}])
    fp = IX.fingerprint(IX.dynamic_pairs(X, [0], [10, 11]), _atoms(), ligand_charges={})
    assert {"A:ASP189", "B:ASP189"} <= set(fp["residues"])


def test_contact_forming_late_is_found_although_far_in_frame_0():
    """Test 6 / A6: the old first-frame filter (pairs within 1.2 nm in frame 0) would miss this."""
    frames = [{1: [0, 0, 0], 13: [3.0, 0, 0]}] * 5 + [{1: [0, 0, 0], 13: [0.35, 0, 0]}] * 5
    dyn = IX.dynamic_pairs(_xyz(frames), [1], [13])
    assert dyn["n_first_frame_pairs"] == 0 and len(dyn["pairs"]) == 1
    fp = IX.fingerprint(dyn, _atoms(), ligand_charges={})
    assert fp["occupancy"]["hydrophobic"]["A:LEU99"] == 0.5
    new = IX.initial_vs_new(fp)
    assert new["new"] == ["A:LEU99"] and new["initial"] == []


def test_periodic_boundary_crossing_gives_no_spurious_loss_or_contact():
    """Test 6: atoms 0.3 nm apart across the box edge are in contact; a far atom wrapped near the edge is not."""
    box = np.diag([5.0, 5.0, 5.0])
    frames = [{1: [0.1, 1, 1], 13: [4.85, 1, 1]}, {1: [4.95, 1, 1], 13: [0.2, 1, 1]}, {1: [2.5, 1, 1], 13: [0.2, 1, 1]}]
    dyn = IX.dynamic_pairs(_xyz(frames), [1], [13], boxes=np.stack([box] * 3))
    assert np.allclose(dyn["dist"][:2, 0], [0.25, 0.25], atol=1e-6) and dyn["dist"][2, 0] > 2.0
    # a triclinic (dodecahedral-like) box keeps the minimum image exact
    tri = np.array([[5.0, 0, 0], [0, 5.0, 0], [2.5, 2.5, 3.5355]])
    d = IX.min_image_distances(np.array([[0.1, 0.1, 0.1]]), np.array([[2.5, 2.5, 3.5355 + 0.05]]), tri)
    assert d[0, 0] == pytest.approx(np.linalg.norm([-0.1, -0.1, 0.05 - 0.1]), abs=1e-3)


def test_chunked_second_pass_equals_single_pass():
    """Test 36: the processing chunk size never changes the result."""
    rng = np.random.default_rng(1)
    X = rng.uniform(0, 1.2, (37, 15, 3))
    a = IX.dynamic_pairs(X, [0, 1, 2], [10, 12, 13, 14], chunk=1)
    b = IX.dynamic_pairs(X, [0, 1, 2], [10, 12, 13, 14], chunk=1000)
    assert np.array_equal(a["pairs"], b["pairs"]) and np.allclose(a["dist"], b["dist"])


def test_missing_water_is_unavailable_not_zero():
    """Test 19 / A5."""
    w = IX.water_unavailable("trajectory saved without solvent")
    assert w["status"] == "unavailable" and w["count"] is None


# ------------------------------------------------------------------------------------------ persistence (F09)
T = np.arange(12, dtype=float) * 2.0          # 2 ps cadence


def test_continuous_intermittent_and_boundary_flags():
    """Test 25: complete event, brief interruption, event present at the start, event continuing at the end."""
    on = [1, 1, 0, 0, 1, 1, 0, 1, 1, 0, 1, 1]
    c = events(on, T, run_id="r1")
    assert [(e["start_frame"], e["end_frame"]) for e in c["events"]] == [(0, 1), (4, 5), (7, 8), (10, 11)]
    assert c["events"][0]["left_censored"] and c["events"][-1]["right_censored"]
    assert not c["events"][1]["left_censored"] and not c["events"][1]["right_censored"]
    i = events(on, T, run_id="r1", max_gap_ps=2.0)            # one-frame (2 ps) breaks allowed, the two-frame break is not
    assert [(e["start_frame"], e["end_frame"], e["interruptions"]) for e in i["events"]] == [(0, 1, 0), (4, 11, 2)]
    assert i["definition"] == "intermittent" and i["events"][1]["duration_ps"] == pytest.approx(16.0)
    assert all(e["run_id"] == "r1" for e in i["events"])


def test_display_decimation_does_not_change_estimator_input():
    """Test 25 / A12: a brief break visible in the stored frames must not become a continuous contact."""
    on = np.ones(100, bool); on[50] = False
    t = np.arange(100, dtype=float)
    full = events(on, t, run_id="r")
    assert len(full["events"]) == 2                           # the stored trajectory shows the break
    from md20.analysis.extended import frame_indices
    sel = frame_indices(100, max_frames=25)                   # what a plot would show
    assert 50 not in sel and all(on[sel])                     # decimation would hide it — the estimator never sees `sel`


def test_sparse_cadence_is_a_stated_limitation():
    c = events([1, 0, 1, 1], [0, 10, 20, 30], run_id="r", max_gap_ps=2.0)
    assert c["limitations"] and "upper bounds" in c["limitations"][0]


def test_replicas_are_never_concatenated_and_segments_break_events():
    a = {"on": [1, 1, 1], "time_ps": [0, 1, 2]}
    b = {"on": [1, 1, 1], "time_ps": [0, 1, 2]}
    p = persistence_for_runs({"rA": a, "rB": b})
    assert [len(t["events"]) for t in p["per_run"]] == [1, 1] and p["n_independent_runs"] == 2
    seg = events([1, 1, 1, 1], [0, 1, 2, 3], run_id="r", segment_ids=[0, 0, 1, 1])
    assert len(seg["events"]) == 2                            # a recorded trajectory gap is not bridged
    gap = events([1, 1, 1, 1], [0, 1, 50, 51], run_id="r")    # an anomalous time jump is a discontinuity too
    assert len(gap["events"]) == 2


def test_lifetime_only_when_identifiable():
    few = survival([events([0, 1, 0, 1, 0], range(5), run_id="r")])
    assert few["lifetime_ps"] is None and "uncensored" in few["lifetime_reason"]
    on = ([0] + [1] * 3) * 12 + [0]
    ok = survival([events(on, range(len(on)), run_id="r")], min_events=5)
    assert ok["lifetime_ps"] == pytest.approx(3.0) and ok["n_left_censored_excluded"] == 0
    long_ = survival([events([0] + [1] * 20, range(21), run_id="r")])
    assert long_["lifetime_ps"] is None


def test_kaplan_meier_with_censoring():
    km = kaplan_meier([1, 2, 2, 3], [False, False, True, False])
    assert km["survival"] == pytest.approx([1.0, 0.75, 0.5, 0.0])
