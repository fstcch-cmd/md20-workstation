"""D-96: structured PMF assessment — spec master_iteration_2026-11-07 A1/A2, acceptance Tests 1–3."""
import copy

from md20.sampling.assessment import assess_pmf, combine_assessments, graph_connected


def _good():
    n = 5
    M = [[1.0 if i == j else (0.3 if abs(i - j) == 1 else 0.0) for j in range(n)] for i in range(n)]
    return {"method": "MBAR", "converged": True, "plateau": True, "pmf_radial_kj_mol": [0, 1, 2],
            "quality": {"graph_connected": True, "window_stats": [{"n_effective": 400.0}] * n},
            "coverage": {"continuous": True, "breaks": []},
            "overlap_matrix": {"matrix": M, "min_neighbour": 0.3},
            "half_split": {"diff_kj_mol": 0.6},
            "convergence": {"0.25": {"delta_pmf": 19.0}, "0.50": {"delta_pmf": 20.2}, "0.75": {"delta_pmf": 20.1},
                            "1.00": {"delta_pmf": 20.0}}}


def _st(a, i):
    return next(d for d in a["diagnostics"] if d["id"] == i)["status"]


def test_all_diagnostics_pass_gives_path_specific_and_dG():
    a = assess_pmf(_good())
    assert a["sampling_adequate"] is True and not a["conflicts"]
    assert a["eligibility"]["delta_pmf_path_specific"] and a["eligibility"]["dG_standard"]
    assert all(d["threshold_source"] for d in a["diagnostics"] if d["threshold"] is not None)
    assert a["thresholds_version"]


def test_missing_fields_are_unknown_never_pass():
    a = assess_pmf({"pmf_radial_kj_mol": [0, 1]})
    assert a["eligibility"]["delta_pmf_path_specific"] is False and a["sampling_adequate"] is None
    assert {"overlap_graph", "window_ess", "half_split", "endpoint_plateau"} <= set(a["unknown"])
    assert assess_pmf(None)["eligibility"]["delta_pmf_path_specific"] is False


def test_low_adjacent_overlap_but_full_graph_bridged():
    """A2 counterexample 1: adjacent 0.02 is a local failure; the full graph is still connected via window 1↔3."""
    p = _good()
    M = copy.deepcopy(p["overlap_matrix"]["matrix"])
    M[1][2] = M[2][1] = 0.02
    M[1][3] = M[3][1] = 0.1
    p["overlap_matrix"] = {"matrix": M, "min_neighbour": 0.02}
    p["quality"].pop("graph_connected")            # force the histogram-matrix path
    a = assess_pmf(p)
    assert _st(a, "adjacent_overlap_min") == "fail" and _st(a, "overlap_graph") == "pass"
    assert any("bridge" in c for c in a["conflicts"])
    assert a["eligibility"]["delta_pmf_path_specific"]          # the local fail alone does not disconnect


def test_pooled_coverage_without_gaps_but_disconnected_graph():
    """A2 counterexample 2."""
    p = _good()
    p["quality"]["graph_connected"] = False
    a = assess_pmf(p)
    assert _st(a, "histogram_coverage") == "pass" and _st(a, "overlap_graph") == "fail"
    assert any("disconnected" in c for c in a["conflicts"])
    assert not a["eligibility"]["delta_pmf_path_specific"] and not a["eligibility"]["affinity_ranking"]


def test_small_half_split_but_cumulative_drift():
    """A2 counterexample 3 / Test 3: no overall convergence claim when the diagnostics disagree."""
    p = _good()
    p["convergence"] = {"0.25": {"delta_pmf": 10.0}, "0.50": {"delta_pmf": 12.0}, "0.75": {"delta_pmf": 14.0},
                        "1.00": {"delta_pmf": 16.0}}
    a = assess_pmf(p)
    assert _st(a, "half_split") == "pass" and _st(a, "cumulative_drift") == "fail"
    assert a["sampling_adequate"] is False and any("drifting" in c for c in a["conflicts"])


def test_small_bootstrap_error_does_not_override_invalid_model():
    """Test 1: an unflat endpoint blocks the claim whatever the error bars."""
    p = _good()
    p["plateau"] = False
    p["err_kj_mol"] = [0.01, 0.01, 0.01]
    assert not assess_pmf(p)["eligibility"]["delta_pmf_path_specific"]


def test_withheld_dG_keeps_path_specific_but_blocks_ranking():
    a = assess_pmf(_good(), dG_withheld="classroom tier")
    assert a["eligibility"]["delta_pmf_path_specific"] and not a["eligibility"]["dG_standard"]
    assert "affinity ranking" in a["prohibited"]


def test_replica_combination_needs_every_replica():
    good, bad = assess_pmf(_good()), assess_pmf({**_good(), "plateau": False})
    c = combine_assessments([good, bad])
    assert not c["eligibility"]["delta_pmf_path_specific"] and c["sampling_adequate"] is False


def test_graph_connected_helper():
    assert graph_connected([[1, 0.1, 0], [0.1, 1, 0.1], [0, 0.1, 1]], 0.05) is True
    assert graph_connected([[1, 0.0], [0.0, 1]], 0.05) is False
    assert graph_connected([[1]], 0.05) is None
