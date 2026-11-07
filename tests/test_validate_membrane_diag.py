"""D-136 (R5): the membrane diagnostic artifact validator, on synthetic artifact JSON (pure Python, no OpenMM).

diag_membrane_nan.py always exits 0 by design; tools/validate_membrane_diag.py decides whether its artifact is
complete and reports (never judges) the observed NaN counts.  These tests pin that split."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("validate_membrane_diag", ROOT / "tools" / "validate_membrane_diag.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


V = _load()
SEEDS = [1, 2, 3]
STEPS = 200


def _run(min_iter, seed, nan_at=None):
    r = {"min_iter": min_iter, "seed": seed, "pe_start": 1.0, "pe_min": -5.0, "fmax_after_min": 900.0,
         "n_atoms_f_gt_1e4": 0, "n_atoms_f_gt_1e3": 0, "top_force_after_min": [], "nan_at_step": nan_at, "seconds": 3.0}
    if nan_at:
        r["chunks"] = [[s, -5.0, 900.0, 1.0, [5.0, 5.0, 8.0]] for s in range(10, nan_at, 10)]
        r["error"] = "OpenMMException: Particle coordinate is NaN"
    else:
        r["chunks"] = [[s, -5.0, 900.0, 1.0, [5.0, 5.0, 8.0]] for s in range(10, STEPS + 1, 10)]
    return r


def _build(i, nan=()):
    """nan: set of (min_iter, seed) that blow up."""
    runs = [_run(500, s, 40 if (500, s) in nan else None) for s in SEEDS]
    runs.append(_run(5000, SEEDS[0], 40 if (5000, SEEDS[0]) in nan else None))
    return {"build": i, "source": "built here", "construction_seed": 2026, "status": "PASS", "n_atoms": 5000,
            "xyz_sha": f"sha{i:013d}", "n_water": 1000, "runs": runs}


def _report(n_builds=4, nan_by_build=None, **over):
    nan_by_build = nan_by_build or {}
    rep = {"openmm": "8.2", "python": "3.11", "platform_threads": "default", "cpu_count": 4,
           "protocol": {"schema": "md20.membrane_diag/2", "builds_requested": n_builds, "velocity_seeds": SEEDS, "steps": STEPS,
                        "chunk_steps": 10, "min_iter_short": 500, "min_iter_long": 5000, "runs_per_build": 4,
                        "from_builds": None, "construction_seed": 2026, "construction_seed_varied": False},
           "builds": [_build(i, nan_by_build.get(i, ())) for i in range(n_builds)], "finished": True}
    rep.update(over)
    return rep


def codes(res, severity=None):
    return sorted({p["code"] for p in res["problems"] if severity in (None, p["severity"])})


def test_complete_artifact_is_ok_and_has_zero_nan():
    res = V.validate(_report())
    assert res["complete"] and codes(res, "error") == []
    assert res["counts"]["runs_expected"] == res["counts"]["runs_recorded"] == 16
    assert res["observed"]["nan"] == 0


def test_nan_counts_are_reported_but_do_not_fail_a_complete_artifact():
    rep = _report(nan_by_build={1: {(500, 2)}, 2: {(500, 1), (500, 2), (500, 3), (5000, 1)}})
    res = V.validate(rep)
    assert res["complete"], res["problems"]
    o = res["observed"]
    assert o["nan"] == 5 and o["short_minimisation"]["nan"] == 4 and o["long_minimisation"]["nan"] == 1
    assert o["variation"]["builds_with_any_nan"] == [1, 2]
    assert o["variation"]["builds_with_all_seeds_nan"] == [2]
    assert o["variation"]["builds_where_outcome_depends_on_velocity_seed"] == [1]      # velocity-seed sensitive
    assert o["short_minimisation"]["by_velocity_seed"]["2"] == {"runs": 4, "nan": 2}


def test_construction_and_velocity_variation_are_separated():
    rep = _report()
    res = V.validate(rep)
    c = res["observed"]["construction"]
    assert c["builds"] == 4 and c["distinct_start_structures"] == 4
    assert c["construction_seeds_recorded"] == [2026]
    assert "seed does not control" in c["note"]            # same construction seed, different structures
    # a seed that fails in some builds only = construction sensitive
    res = V.validate(_report(nan_by_build={0: {(500, 3)}}))
    assert res["observed"]["variation"]["velocity_seeds_where_outcome_depends_on_build"] == [3]
    # legacy artifact without construction seed: stated as not recorded
    rep = _report()
    for b in rep["builds"]:
        b.pop("construction_seed")
    assert V.validate(rep, {"builds": 4, "seeds": SEEDS, "steps": STEPS, "long_min": 5000})["observed"]["construction"]["construction_seed_unrecorded"]


def test_missing_run_record_fails():
    rep = _report()
    del rep["builds"][2]["runs"][1]
    res = V.validate(rep)
    assert not res["complete"] and "MISSING_RUN" in codes(res, "error")


def test_missing_build_record_fails():
    rep = _report()
    rep["builds"].pop()
    res = V.validate(rep)
    assert not res["complete"] and "MISSING_BUILD" in codes(res, "error")


def test_build_error_fails():
    rep = _report()
    rep["builds"][1] = {"build": 1, "source": "built here", "error": "Traceback...\nValueError: could not place the peptide"}
    res = V.validate(rep)
    assert not res["complete"]
    assert {"BUILD_ERROR", "MISSING_RUN"} <= set(codes(res, "error"))


def test_unfinished_artifact_fails():
    rep = _report(finished=False)
    res = V.validate(rep)
    assert not res["complete"] and "NOT_FINISHED" in codes(res, "error")


def test_truncated_clean_run_fails():
    rep = _report()
    rep["builds"][0]["runs"][0]["chunks"] = rep["builds"][0]["runs"][0]["chunks"][:5]
    res = V.validate(rep)
    assert not res["complete"] and "TRUNCATED_RUN" in codes(res, "error")


def test_run_without_nan_flag_is_malformed():
    rep = _report()
    del rep["builds"][0]["runs"][0]["nan_at_step"]
    assert "MALFORMED_RUN" in codes(V.validate(rep), "error")


def test_protocol_mismatch_between_request_and_artifact_fails():
    res = V.validate(_report(n_builds=2), {"builds": 4})
    assert not res["complete"] and "PROTOCOL_MISMATCH" in codes(res, "error")


def test_cli_expectation_catches_a_shortened_artifact_without_protocol_block():
    rep = _report(n_builds=2)
    del rep["protocol"]
    res = V.validate(rep, {"builds": 4, "seeds": SEEDS, "steps": STEPS, "long_min": 5000})
    assert not res["complete"] and "MISSING_BUILD" in codes(res, "error") and "LEGACY_ARTIFACT" in codes(res, "warning")


def test_no_protocol_and_no_expectation_cannot_be_judged():
    rep = _report()
    del rep["protocol"]
    res = V.validate(rep)
    assert not res["complete"] and "NO_EXPECTATION" in codes(res, "error")


def test_cross_run_with_no_builds_found_fails():
    rep = _report(n_builds=0)
    rep["protocol"]["from_builds"] = "other"
    res = V.validate(rep)
    assert not res["complete"] and "NO_BUILDS_EXPECTED" in codes(res, "error")


def test_nonfinite_value_in_clean_run_is_flagged_not_hidden():
    rep = _report()
    rep["builds"][0]["runs"][0]["fmax_after_min"] = float("nan")
    res = V.validate(rep)
    assert "NONFINITE_VALUE" in codes(res, "warning")
    assert res["observed"]["nonfinite_values_in_clean_runs"] >= 1


def test_not_an_object_and_missing_file(tmp_path, capsys):
    assert not V.validate([1, 2])["complete"]
    assert V.main([str(tmp_path)]) == 1                       # directory without diag.json
    (tmp_path / "diag.json").write_text("{not json", encoding="utf-8")
    assert V.main([str(tmp_path)]) == 1


def test_cli_exit_codes_json_and_markdown(tmp_path):
    ok = tmp_path / "ok"
    ok.mkdir()
    (ok / "diag.json").write_text(json.dumps(_report(nan_by_build={0: {(500, 1)}})), encoding="utf-8")
    md, js = tmp_path / "s.md", tmp_path / "v.json"
    md.write_text("existing\n", encoding="utf-8")
    assert V.main([str(ok), "--expect-builds", "4", "--expect-seeds", "1,2,3", "--expect-steps", "200",
                   "--json", str(js), "--markdown", str(md)]) == 0
    out = json.loads(js.read_text(encoding="utf-8"))
    assert out["complete"] and "qualification" in out["disclaimer"]
    text = md.read_text(encoding="utf-8")
    assert text.startswith("existing") and "Observed NaN" in text
    bad = tmp_path / "bad"
    bad.mkdir()
    rep = _report()
    rep["builds"].pop()
    (bad / "diag.json").write_text(json.dumps(rep), encoding="utf-8")
    assert V.main([str(ok), str(bad)]) == 1                   # one bad artifact fails the whole call
    with pytest.raises(SystemExit) as e:
        V.main([str(ok), "--expect-seeds", "x"])
    assert e.value.code == 2
