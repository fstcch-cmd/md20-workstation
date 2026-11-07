"""D-135 (R3): analysis resolution is separate from plot resolution.  Pure numpy; no mdtraj.

Covers: chunked == unchunked event detection, short interruptions, irregular timestamps, gaps, left/right censoring,
replica boundaries, display stride not touching full-resolution estimates, resolution/qualification records, the
streaming persistence pass, and the PCA/cluster/common-basis sampling sensitivity."""
import numpy as np
import pytest

from md20.analysis import extended as EX
from md20.analysis.persistence import (EventAccumulator, events, persistence_for_runs, resolution_record,
                                       select_interactions, persistence_report)

from test_extended_fingerprint_wiring import _system, fake_mdtraj  # noqa: F401  (stand-in topology + mdtraj stub)


def _strip(d):
    return d


def _chunked(on_by_key, t, sizes, *, segment_ids=None, **kw):
    acc = EventAccumulator(run_id="r", **kw)
    i = 0
    n = len(t)
    for sz in sizes:
        j = min(n, i + sz)
        if j <= i:
            break
        acc.update({k: v[i:j] for k, v in on_by_key.items()}, t[i:j], None if segment_ids is None else segment_ids[i:j])
        i = j
    return acc


# ----------------------------------------------------------------------------------- chunked == unchunked
@pytest.mark.parametrize("size", [1, 2, 3, 7, 50, 1000])
def test_chunked_events_equal_unchunked(size):
    rng = np.random.default_rng(3)
    n = 400
    t = np.arange(n) * 20.0
    on = {k: (rng.random(n) < p) for k, p in (("a", 0.9), ("b", 0.5), ("c", 0.05))}
    on["d"] = np.ones(n, bool)                                # on all the time: left AND right censored
    for max_gap in (0.0, 40.0):
        acc = _chunked(on, t, [size] * (n // size + 1), max_gap_ps=max_gap, reference_dt_ps=20.0)
        for k, v in on.items():
            ref = events(v, t, run_id="r", max_gap_ps=max_gap, reference_dt_ps=20.0)
            assert acc.result(k) == ref, (k, size, max_gap)


def test_chunk_boundary_inside_an_event_is_carried():
    on = np.array([0, 1, 1, 1, 1, 0, 1, 1, 0], bool)
    t = np.arange(9) * 10.0
    for cut in range(1, 9):
        acc = _chunked({"x": on}, t, [cut, 9 - cut], reference_dt_ps=10.0)
        ev = acc.result("x")["events"]
        assert [(e["start_frame"], e["end_frame"]) for e in ev] == [(1, 4), (6, 7)], cut
        assert ev[0]["duration_ps"] == pytest.approx(40.0)


def test_interaction_that_appears_in_a_later_chunk_and_absent_in_others():
    t = np.arange(10) * 5.0
    acc = EventAccumulator(run_id="r", reference_dt_ps=5.0)
    acc.update({"early": np.array([1, 1, 0, 0, 0], bool)}, t[:5])
    acc.update({"late": np.array([0, 0, 1, 1, 1], bool)}, t[5:])
    assert acc.result("early")["events"][0]["end_frame"] == 1 and not acc.result("early")["events"][0]["right_censored"]
    late = acc.result("late")["events"]
    assert len(late) == 1 and late[0]["start_frame"] == 7 and late[0]["right_censored"] and not late[0]["left_censored"]


# ----------------------------------------------------------------------------------- short interruptions, decimation
def test_short_interruption_visible_at_full_cadence_hidden_when_decimated():
    on = np.ones(100, bool)
    on[51] = False                                            # a single-frame break at an odd frame
    t = np.arange(100) * 10.0
    full = events(on, t, run_id="r", resolution=resolution_record(t, effective_stride=1))
    assert len(full["events"]) == 2 and full["status"] == "computed"
    sel = np.arange(0, 100, 2)                                # every 2nd stored frame: the break (odd frame) disappears
    dec_res = resolution_record(t[sel], effective_stride=2, source_frame_interval_ps=10.0, n_frames_source=100)
    dec = events(on[sel], t[sel], run_id="r", resolution=dec_res)
    assert len(dec["events"]) == 1                            # merged: the decimated series cannot see the break
    assert dec["status"] == "limited" and any("upper bounds" in x for x in dec["limitations"])
    assert dec["events"][0]["duration_ps"] >= full["events"][0]["duration_ps"]
    assert dec["resolution"]["effective_interval_ps"] == 20.0 and dec["resolution"]["source_frame_interval_ps"] == 10.0


def test_resolution_record_fields_and_statuses():
    t = np.arange(50) * 40.0
    r = resolution_record(t, source_frame_interval_ps=10.0, effective_stride=4, n_frames_source=197)
    assert {"source_frame_interval_ps", "effective_stride", "effective_interval_ps", "n_frames_source", "n_frames_used",
            "observation_length_ps", "resolution"} <= set(r)
    assert r["effective_interval_ps"] == 40.0 and r["n_frames_used"] == 50 and r["observation_length_ps"] == 49 * 40.0 + 40.0
    assert r["resolution"]["status"] == "limited" and "k_off" in r["resolution"]["reasons"][0]
    assert resolution_record(t, effective_stride=1)["resolution"]["status"] == "full"
    un = resolution_record(t)
    assert un["resolution"]["status"] == "unverified" and un["effective_stride"] is None


# ----------------------------------------------------------------------------------- irregular timestamps, gaps, censoring
def test_irregular_timestamps_weight_occupancy_by_interval_not_frame_count():
    t = np.array([0.0, 10.0, 20.0, 30.0, 40.0, 50.0])
    on = np.array([1, 1, 1, 0, 0, 0], bool)
    assert events(on, t, run_id="r")["occupancy_time_weighted"] == pytest.approx(0.5)
    t2 = np.array([0.0, 10.0, 20.0, 30.0, 44.0, 58.0])        # slightly irregular but below the jump factor
    on2 = np.array([1, 1, 1, 0, 0, 0], bool)
    ev = events(on2, t2, run_id="r")
    assert ev["n_segments"] == 1
    # weights follow the real steps: 10+10+10 ps on of 10+10+10+14+14+10 (the last frame gets the median step)
    assert ev["occupancy_time_weighted"] == pytest.approx(30.0 / 68.0, abs=1e-5)
    assert ev["occupancy_time_weighted"] != pytest.approx(0.5, abs=1e-3)


def test_time_gap_ends_events_and_is_not_bridged_even_across_a_chunk_boundary():
    on = np.ones(8, bool)
    t = np.array([0, 10, 20, 30, 500, 510, 520, 530], float)  # a 470 ps hole between frames 3 and 4
    for sizes in ([8], [4, 4], [3, 5], [1] * 8):
        acc = _chunked({"x": on}, t, sizes, reference_dt_ps=10.0, max_gap_ps=1000.0)
        ev = acc.result("x")["events"]
        assert [(e["start_frame"], e["end_frame"], e["segment"]) for e in ev] == [(0, 3, 0), (4, 7, 1)], sizes
        assert ev[0]["left_censored"] and ev[0]["right_censored"] and ev[1]["left_censored"] and ev[1]["right_censored"]
    # a recorded restart discontinuity (segment_ids) ends the event too, even without a time jump
    acc = _chunked({"x": on}, np.arange(8) * 10.0, [3, 5], segment_ids=[0, 0, 0, 1, 1, 1, 1, 1], reference_dt_ps=10.0)
    assert len(acc.result("x")["events"]) == 2


def test_left_and_right_censoring_flags_and_km_excludes_left_censored():
    on = np.array([1, 1, 0, 1, 1, 0, 0, 1, 1], bool)
    t = np.arange(9) * 2.0
    ev = events(on, t, run_id="r")["events"]
    assert ev[0]["left_censored"] and not ev[0]["right_censored"]
    assert ev[1]["left_censored"] is False and ev[1]["right_censored"] is False
    assert ev[2]["right_censored"] and not ev[2]["left_censored"]
    from md20.analysis.persistence import survival
    sv = survival([events(on, t, run_id="r")])
    assert sv["n_left_censored_excluded"] == 1 and sv["n_right_censored"] == 1


def test_replicas_are_never_concatenated_in_the_stream_either():
    t = np.arange(6) * 10.0
    a = _chunked({"x": np.array([0, 0, 0, 1, 1, 1], bool)}, t, [2, 4], reference_dt_ps=10.0)
    b = _chunked({"x": np.array([1, 1, 1, 0, 0, 0], bool)}, t, [3, 3], reference_dt_ps=10.0)
    ea, eb = a.result("x")["events"], b.result("x")["events"]
    assert len(ea) == 1 and ea[0]["right_censored"] and len(eb) == 1 and eb[0]["left_censored"]
    # concatenated they would have looked like ONE event of 6 frames spanning the replica boundary; they are not
    p = persistence_for_runs({"rA": {"on": [0, 0, 0, 1, 1, 1], "time_ps": t}, "rB": {"on": [1, 1, 1, 0, 0, 0], "time_ps": t}})
    assert p["n_independent_runs"] == 2 and all(len(x["events"]) == 1 for x in p["per_run"])


# ----------------------------------------------------------------------------------- streaming persistence pass (numpy)
def _atoms():
    """ligand O (0) and C (1) + residue A:ASP189 (OD1=2, CA=3), A:LEU99 (CD1=4, CA=5)."""
    def a(el, res, name, key, side=True):
        return {"element": el, "resname": res, "name": name, "res_key": key, "sidechain_carbon": side}
    return {0: a("O", "LIG", "O1", "L:LIG1"), 1: a("C", "LIG", "C1", "L:LIG1"),
            2: a("O", "ASP", "OD1", "A:ASP189"), 3: a("C", "ASP", "CA", "A:ASP189", False),
            4: a("C", "LEU", "CD1", "A:LEU99"), 5: a("C", "LEU", "CA", "A:LEU99", False)}


def _xyz(n=60, break_at=(30,), late_start=40):
    X = np.zeros((n, 6, 3))
    X[:, 0] = [0, 0, 0]; X[:, 1] = [0.15, 0, 0]
    X[:, 2] = [0.3, 0, 0]; X[:, 3] = [0.9, 0, 0]
    X[:, 4] = [3.0, 0, 0]; X[:, 5] = [3.5, 0, 0]
    X[late_start:, 4] = [0.5, 0, 0]
    for b in break_at:
        X[b, 2] = [2.0, 0, 0]                                  # one-frame loss of the polar contact
    return X


def test_streamed_persistence_chunked_equals_whole_and_sees_the_one_frame_break():
    from md20.analysis.stream import PersistenceStream
    X, t = _xyz(), np.arange(60) * 20.0
    res = {}
    for chunk in (60, 17, 5, 1):
        ps = PersistenceStream([0, 1], [2, 3, 4, 5], _atoms(), run_id="L01", reference_dt_ps=20.0)
        for s in range(0, 60, chunk):
            ps.update(X[s:s + chunk], t[s:s + chunk])
        res[chunk] = ps.result(effective_stride=1)
    base = res[60]
    for chunk, r in res.items():
        assert r["items"] == base["items"] and r["occupancy_all_frames"] == base["occupancy_all_frames"], chunk
    pol = next(i for i in base["items"] if i["residue"] == "A:ASP189" and i["label"] == "polar_proximity")
    assert pol["n_events"] == 2 and pol["events"][0]["end_frame"] == 29 and pol["events"][1]["start_frame"] == 31
    assert base["status"] == "computed" and base["resolution"]["resolution"]["status"] == "full"
    assert base["source"] == "streamed_full_cadence" and base["n_chunks"] == 1


def test_decimated_frames_miss_the_break_and_say_so():
    from md20.analysis.stream import PersistenceStream
    X, t = _xyz(break_at=(31,)), np.arange(60) * 20.0
    full = PersistenceStream([0, 1], [2, 3, 4, 5], _atoms(), reference_dt_ps=20.0)
    full.update(X, t)
    dec = PersistenceStream([0, 1], [2, 3, 4, 5], _atoms(), reference_dt_ps=40.0)
    dec.update(X[::2], t[::2])
    f = full.result(effective_stride=1)
    d = dec.result(effective_stride=2, source_frame_interval_ps=20.0, n_frames_source=60)
    nev = lambda r: next(i for i in r["items"] if i["label"] == "polar_proximity")["n_events"]  # noqa: E731
    assert nev(f) == 2 and nev(d) == 1
    assert d["status"] == "limited" and "interruptions shorter" in d["reason"]
    assert all(i["status"] == "limited" and "k_off" in i["lifetime_qualifier"] for i in d["items"])
    assert f["status"] == "computed"


# ----------------------------------------------------------------------------------- display stride vs estimates (extended_metrics)
def test_display_subsample_cap_does_not_change_full_resolution_persistence(fake_mdtraj, monkeypatch):  # noqa: F811
    traj = _system()
    base = EX.extended_metrics(traj, {"L01": [0, 1]}, resolution={"effective_stride": 1})
    monkeypatch.setattr(EX, "MAX_FRAMES", 4)                  # a drastically thinner display/estimator subsample
    thin = EX.extended_metrics(traj, {"L01": [0, 1]}, resolution={"effective_stride": 1})
    assert thin["sampling"]["n_used"] == 4 and base["sampling"]["n_used"] == 20
    a, b = base["ligands"]["L01"]["fingerprint"], thin["ligands"]["L01"]["fingerprint"]
    assert a["persistence"] == b["persistence"] and a["occupancy"] == b["occupancy"] and a["bitmask"] == b["bitmask"]
    assert a["persistence"]["status"] == "computed"


def test_extended_records_resolution_sampling_and_limits_when_strided(fake_mdtraj):  # noqa: F811
    traj = _system()
    unv = EX.extended_metrics(traj, {"L01": [0, 1]})
    assert unv["ligands"]["L01"]["fingerprint"]["persistence"]["status"] == "unverified"
    assert unv["resolution"]["resolution"]["status"] == "unverified"
    lim = EX.extended_metrics(traj, {"L01": [0, 1]}, resolution={"effective_stride": 5, "source_frame_interval_ps": 2.0,
                                                                  "n_frames_source": 96})
    fp = lim["ligands"]["L01"]["fingerprint"]
    assert fp["status"] == "limited" and "invisible" in fp["reason"]
    assert fp["persistence"]["status"] == "limited" and "invisible" in fp["persistence"]["reason"]
    assert all(i["status"] == "limited" and "lifetime_qualifier" in i for i in fp["persistence"]["items"])
    r = lim["resolution"]
    assert r["effective_stride"] == 5 and r["source_frame_interval_ps"] == 2.0 and r["n_frames_source"] == 96
    assert r["effective_interval_ps"] == 10.0 and r["n_frames_used"] == 20
    s = lim["sampling"]
    assert s["n_frames_analysed"] == 20 and s["n_used"] == 20 and "uniform subsample" in s["scheme"]
    assert "ligands.*.fingerprint (contacts and persistence events)" in s["all_analysed_frames_blocks"]
    full = EX.extended_metrics(traj, {"L01": [0, 1]}, resolution={"effective_stride": 1})
    assert full["ligands"]["L01"]["fingerprint"]["status"] == "computed"


def test_pca_block_reports_sampling_and_sensitivity(fake_mdtraj):  # noqa: F811
    out = EX.extended_metrics(_system(), {"L01": [0, 1]}, resolution={"effective_stride": 1})
    p = out["pca"]
    assert p["sampling"]["n_used"] == 20 and p["sensitivity"]["interleaved_halves"]["status"] == "ok"
    assert "converge" in p["sensitivity"]["note"]


# ----------------------------------------------------------------------------------- sensitivity helpers
def test_pca_sensitivity_flags_a_subsample_that_misses_a_rare_motion():
    rng = np.random.default_rng(1)
    n, d = 200, 12
    X = rng.normal(scale=0.3, size=(n, d))
    X[:, 0] += rng.normal(scale=1.0, size=n)                  # broad, visible motion along axis 0
    X[1::10, 5] += 40.0                                       # rare large excursion on odd frames only
    sel = np.arange(0, n, 10)                                 # the subsample never sees it
    sens = EX.pca_sensitivity(X[sel].reshape(len(sel), 4, 3), X.reshape(n, 4, 3))
    assert sens["all_frames"]["status"] == "ok" and sens["all_frames"]["pc1_abs_cos"] < 0.5
    assert sens["consistent"] is False and sens["interleaved_halves"]["status"] == "ok"
    assert "does not show that the landscape has converged" in sens["note"]


def test_pca_sensitivity_consistent_for_a_stationary_motion_and_skips_costly_all_frame_pca():
    rng = np.random.default_rng(2)
    X = rng.normal(scale=0.1, size=(300, 9)) + rng.normal(scale=2.0, size=(300, 1)) * np.linspace(1, 2, 9)
    sens = EX.pca_sensitivity(X[::3].reshape(100, 3, 3), X.reshape(300, 3, 3))
    assert sens["consistent"] is True and sens["interleaved_halves"]["pc1_abs_cos"] > 0.95
    sk = EX.pca_sensitivity(X[::3].reshape(100, 3, 3), X.reshape(300, 3, 3), max_all_elements=10)
    assert sk["all_frames"]["status"] == "skipped"
    assert EX.pca_sensitivity(np.zeros((4, 3, 3)))["interleaved_halves"]["status"] == "insufficient"


def test_cluster_sensitivity_reports_halves():
    rng = np.random.default_rng(4)
    pts = np.concatenate([rng.normal(0, 0.1, (30, 3)), rng.normal(5, 0.1, (30, 3))])
    D = np.linalg.norm(pts[:, None] - pts[None], axis=-1)
    c = EX.cluster_sensitivity(D, 2.0)
    assert c["status"] == "ok" and c["even"]["n_clusters"] == c["odd"]["n_clusters"] == 2 and c["consistent"] is True
    assert EX.cluster_sensitivity(np.zeros((3, 3)))["status"] == "insufficient"


def test_common_basis_reports_interleaved_split_and_sampling_provenance():
    from md20.analysis.common_basis import common_basis, interleaved_split
    rng = np.random.default_rng(5)
    labels = [f"A:{i}" for i in range(1, 16)]
    base = rng.normal(size=(15, 3)) * 5

    def sys_(n, shift, sampling=None):
        x = np.array([base + shift * (1 if rng.random() < 0.5 else -1) + rng.normal(scale=0.05, size=base.shape)
                      for _ in range(n)])
        d = {"labels": labels, "xyz": x, "time_ns": list(range(n))}
        if sampling:
            d["sampling"] = sampling
        return d
    out = common_basis({"apo": sys_(120, 0.3, {"n_kept": 120, "n_frames_analysed": 500}), "holo": sys_(120, 0.3)})
    assert out["status"] == "ok" and "sampling_note" in out
    ps = out["per_system"]
    assert ps["apo"]["sampling"]["n_frames_analysed"] == 500 and ps["holo"]["sampling"]["status"] == "not_recorded"
    assert ps["apo"]["interleaved_split"]["status"] in ("ok", "insufficient")
    p = np.vstack([np.zeros((30, 2)), np.ones((30, 2))])
    il = interleaved_split(p[np.argsort(np.arange(60) % 2, kind="stable")], [[0, 0, 0.0, 0.5], [1, 1, 0.0, 0.5]])
    assert il["status"] == "ok" and "convergence" in il["note"]


def test_save_ca_coordinates_records_the_subsample(tmp_path):
    from md20.analysis.traj import save_ca_coordinates
    from md20.util import load_json
    traj = _system()
    save_ca_coordinates(traj, tmp_path, {"L01": [0, 1]}, max_frames=8, resolution={"effective_stride": 3})
    lab = load_json(tmp_path / "ca_labels.json", {})
    assert np.load(tmp_path / "ca_xyz.npy").shape[0] == 8
    s = lab["sampling"]
    assert s["n_kept"] == 8 and s["n_frames_analysed"] == 20 and s["resolution"]["effective_stride"] == 3
    assert "uniform subsample" in s["scheme"]


def test_select_interactions_and_report_shape():
    occ = {"hydrophobic": {"A:LEU99": 0.5, "A:VAL1": 0.05}, "polar_proximity": {"A:ASP189": 1.0}}
    assert select_interactions(occ) == [("A:LEU99", "hydrophobic"), ("A:ASP189", "polar_proximity")]
    acc = EventAccumulator(run_id="r")
    acc.update({("A:ASP189", "polar_proximity"): np.ones(5, bool)}, np.arange(5) * 1.0)
    rep = persistence_report(acc, [("A:ASP189", "polar_proximity")])
    assert rep["status"] == "computed" and rep["items"][0]["events"][0]["left_censored"]
    assert "not ligand residence time" in rep["note"]
