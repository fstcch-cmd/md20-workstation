"""D-130 redo (docs/specs/replicas.md §2, evidence_driven_repair_prompt.md R1): every independent replica is analysed,
aggregated with a declared estimand, and shown; one trajectory gives "unavailable", never an invented interval."""
import copy
import math

import numpy as np
import pytest

from md20.analysis import replica_set as RS
from md20.util.jsonio import atomic_write_json, load_json


# ------------------------------------------------------------------------------------------------ helpers
def _metrics(level: float, *, bound: bool = True, contact: float = 0.9, n: int = 40, pocket: float | None = None) -> dict:
    """A metrics.json whose backbone RMSD sits near `level` (flat, tiny ripple so block SE exists)."""
    ripple = 0.05 * np.sin(np.arange(n))
    pocket = (1.5 if bound else 9.0) if pocket is None else pocket
    fr = ({"pose_retained": 0.9, "pose_changed_in_pocket": 0.1, "escape_evidence": 0.0, "unknown": 0.0} if bound else
          {"pose_retained": 0.0, "pose_changed_in_pocket": 0.0, "escape_evidence": 1.0, "unknown": 0.0})
    return {"time_ns": list(np.linspace(0.1, 4.0, n)), "n_frames": n,
            "rmsd_backbone_A": (level + ripple).tolist(), "rg_protein_A": (18 + ripple).tolist(),
            "rmsf_ca_A": [level * 0.5 + i * 0.1 for i in range(12)], "rmsf_residues": [f"ALA{i}" for i in range(12)],
            "ligands": {"L01": {"rmsd_in_pocket_A": (pocket + ripple).tolist(), "contact_residues": [4] * n,
                                "polar_contacts": [2] * n, "com_distance_to_pocket_A": [1.0] * n,
                                "contact_frequency": {"ASP189": contact}, "contact_residue_ids": {"ASP189": "A:ASP189"},
                                "stays_bound": bound, "ligand_state": {"fraction_final_20pct": fr}}}}


def _reps(levels, bounds=None):
    bounds = bounds or [True] * len(levels)
    return [{"run_id": f"run_{i}", "replica_index": i, "status": "COMPLETE", "metrics": _metrics(lv, bound=b, contact=0.9 if b else 0.1)}
            for i, (lv, b) in enumerate(zip(levels, bounds))]


# ------------------------------------------------------------------------------------------------ pure aggregation
def test_t_quantile_table_matches_scipy_when_available():
    assert RS.t_critical_975(2) == pytest.approx(4.3027)               # n = 3
    assert RS.t_critical_975(10_000) == pytest.approx(1.96, abs=0.01)
    stats = pytest.importorskip("scipy.stats")
    for df in (1, 2, 3, 7, 29, 35, 45, 90, 500):
        assert RS.t_critical_975(df) == pytest.approx(stats.t.ppf(0.975, df), abs=2e-3)


def test_three_divergent_replicas_are_all_visible_and_change_the_summary():
    agg = RS.aggregate_replica_set(_reps([2.0, 4.0, 9.0], bounds=[True, True, False]), system="complex", n_requested=3)
    assert agg["schema"] == "md20.replica_set/1" and agg["n_analysed"] == 3
    rm = agg["observables"]["rmsd_backbone_A"]
    assert [x["run_id"] for x in rm["per_replica"]] == ["run_0", "run_1", "run_2"]           # identity kept
    assert rm["mean"] == pytest.approx(5.0, abs=0.1)                                         # not the first replica's 2.0
    vals = np.array([x["value"] for x in rm["per_replica"]])
    assert rm["sd"] == pytest.approx(vals.std(ddof=1))
    half = RS.t_critical_975(2) * vals.std(ddof=1) / math.sqrt(3)
    assert rm["ci95"]["low"] == pytest.approx(vals.mean() - half) and rm["ci95"]["high"] == pytest.approx(vals.mean() + half)
    assert rm["ci95"]["df"] == 2 and rm["divergent"] is True and "divergent:rmsd_backbone_A" in agg["flags"]
    sb = agg["ligands"]["L01"]["stays_bound"]
    assert (sb["k"], sb["n"]) == (2, 3) and sb["consistent"] is False
    assert (agg["ligands"]["L01"]["in_pocket_final20"]["k"], agg["ligands"]["L01"]["in_pocket_final20"]["n"]) == (2, 3)
    assert "inconsistent:L01:stays_bound" in agg["flags"]
    # the first replica alone would have said "stays bound, RMSD 2"
    first_only = RS.aggregate_replica_set(_reps([2.0]))
    assert first_only["observables"]["rmsd_backbone_A"]["mean"] != pytest.approx(rm["mean"], abs=0.5)


def test_per_residue_rmsf_and_contact_occupancy_across_replicas():
    agg = RS.aggregate_replica_set(_reps([2.0, 4.0, 9.0], bounds=[True, True, False]))
    r = agg["per_residue"]["rmsf_ca_A"]
    assert r["n"] == 3 and len(r["residues"]) == 12 and len(r["sd"]) == 12 and set(r["per_replica"]) == {"run_0", "run_1", "run_2"}
    co = agg["ligands"]["L01"]["contact_occupancy"]["residues"][0]
    assert co["residue"] == "ASP189" and co["persistent_k"] == 2 and co["persistent_n"] == 3
    assert co["mean"] == pytest.approx((0.9 + 0.9 + 0.1) / 3)


def test_one_replica_gives_unavailable_between_replica_uncertainty_not_an_interval():
    agg = RS.aggregate_replica_set(_reps([3.0]), system="complex")
    assert agg["n_analysed"] == 1 and "single_replica" in agg["flags"]
    assert agg["between_replica"] == {"status": "unavailable", "reason": "單一軌跡無法估計重複間不確定性"}
    rm = agg["observables"]["rmsd_backbone_A"]
    assert rm["sd"] is None and rm["ci95"] is None and rm["sem"] is None
    assert rm["between_replica"]["status"] == "unavailable"
    assert rm["mean"] == pytest.approx(3.0, abs=0.1)                                         # the single value is reported as such
    assert rm["within_trajectory"]["per_replica"][0]["status"] == "ok"                       # within-trajectory kept separately
    assert agg["ligands"]["L01"]["stays_bound"]["between_replica"]["status"] == "unavailable"
    assert agg["per_residue"]["rmsf_ca_A"]["sd"] is None


def test_within_trajectory_and_between_replica_are_separate_numbers():
    agg = RS.aggregate_replica_set(_reps([2.0, 4.0, 9.0]))
    rm = agg["observables"]["rmsd_backbone_A"]
    se = [w["block_se"] for w in rm["within_trajectory"]["per_replica"]]
    assert len(se) == 3 and all(x < 0.2 for x in se)           # ripple only
    assert rm["sd"] > 2.0                                      # the spread between replicas is not the block SE
    assert "sem_within" not in rm and rm["ci95"]["half_width"] > 5 * max(se)


def test_pulls_and_windows_of_one_parent_do_not_increase_the_replica_count():
    rep = _reps([3.0])[0]
    rep["descendants"] = {"pulls": 5, "windows": 24}
    agg = RS.aggregate_replica_set([rep], system="complex")
    assert agg["n_analysed"] == 1 and agg["n_listed"] == 1 and "single_replica" in agg["flags"]
    assert agg["replicas"][0]["descendants"] == {"pulls": 5, "windows": 24}                  # listed under the parent
    assert agg["lineage"]["levels"] == ["case", "replica", "descendant"]
    assert agg["observables"]["rmsd_backbone_A"]["n"] == 1


def test_failed_incomplete_and_excluded_replicas_are_kept_with_reasons():
    reps = _reps([2.0, 2.2, 2.4])
    reps.append({"run_id": "run_x", "replica_index": 3, "status": "NEEDS_HUMAN", "metrics": None, "reason": "NPT 密度未通過"})
    reps.append({"run_id": "run_y", "replica_index": 4, "status": "COMPLETE", "metrics": None, "analysis_status": "FAILED",
                 "reason": "分析失敗：boom"})
    agg = RS.aggregate_replica_set(reps, n_requested=5)
    assert agg["n_analysed"] == 3 and agg["n_listed"] == 5 and "excluded_replicas" in agg["flags"]
    assert {x["run_id"]: x["reason"] for x in agg["excluded"]} == {"run_x": "NPT 密度未通過", "run_y": "分析失敗：boom"}
    assert all(not r["analysed"] for r in agg["replicas"] if r["run_id"] in ("run_x", "run_y"))
    assert agg["observables"]["rmsd_backbone_A"]["n"] == 3


def test_replicas_are_never_concatenated():
    agg = RS.aggregate_replica_set(_reps([2.0, 4.0]))
    assert agg["concatenation"] == "never"
    # per-frame data of different replicas never meet: statistics come only from one value per replica
    assert agg["observables"]["rmsd_backbone_A"]["n"] == 2


def test_empty_input_is_unavailable_not_an_error():
    agg = RS.aggregate_replica_set([])
    assert agg["n_analysed"] == 0 and "no_analysed_replica" in agg["flags"] and agg["between_replica"]["status"] == "unavailable"


def test_merge_replica_conditions_blocks_a_disagreement_and_keeps_unknown():
    from md20.analysis.common_basis import comparability
    base = {"temperature_k": 300, "ensemble": "NPT", "production_ps": 1000, "restrained": [], "water_model": "tip3p",
            "forcefield": ["a.xml"], "solvent": "explicit", "hmr": True}
    merged, within = RS.merge_replica_conditions({"r1": base, "r2": {**base, "temperature_k": 310}})
    assert within["comparable"] is False and merged["temperature_k"].startswith("replicas differ")
    assert comparability({"apo": base, "holo": merged})["comparable"] is False
    merged, within = RS.merge_replica_conditions({"r1": base, "r2": {**base, "hmr": None}})
    assert merged["hmr"] is None and "hmr" in within["unknown"]
    merged, within = RS.merge_replica_conditions({"r1": base, "r2": dict(base)})
    assert merged == base and within["comparable"] is True


# ------------------------------------------------------------------------------------------------ workflow
def _workflow(tmp_path, monkeypatch, level_by_run, *, systems=("complex",), temps=None):
    """A Workflow whose per-run analysis is faked: writes metrics for each run_id."""
    from md20.project.store import Project
    from md20.workflow import Workflow, example_config
    cfg = copy.deepcopy(example_config())
    cfg["md"].pop("membrane", None)
    wf = Workflow(Project.create(tmp_path, "p"), cfg)
    runs, calls = {}, []
    temps = temps or {}
    for key in systems:
        case = wf.project.new_case(key)
        case.build_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json({"topology_pdb": "t.pdb", "assembly": {"ligands": []}, "solvent": "explicit", "water_model": "tip3p",
                           "forcefields": ["amber14-all.xml", "amber14/tip3p.xml"]}, case.build_dir / "build_manifest.json")
        rids = []
        for i, (rid, lv) in enumerate(level_by_run[key].items()):
            rd = case.dir / "runs" / rid
            rd.mkdir(parents=True, exist_ok=True)
            atomic_write_json({"status": "COMPLETE", "replica_index": i, "replica_group": f"g_{key}",
                               "protocol": {"hmr": True, "stages": [{"name": "production", "temperature_k": temps.get(rid, 300.0),
                                                                     "ensemble": "NPT", "length_ps": 1000.0}]}}, rd / "run.json")
            rids.append(rid)
        runs[key] = {"case_id": case.case_id, "group_id": f"g_{key}", "status": "COMPLETE", "run_ids": rids}

    def fake(run_dir, top, **kw):
        calls.append(run_dir.name)
        lv = next(v for k in level_by_run.values() for r, v in k.items() if r == run_dir.name)
        (run_dir / "analysis").mkdir(parents=True, exist_ok=True)
        atomic_write_json(_metrics(lv, bound=lv < 8), run_dir / "analysis" / "metrics.json")
        n = 12
        atomic_write_json({"labels": [f"A:ALA{i}" for i in range(n)], "time_ns": list(range(30))}, run_dir / "analysis" / "ca_labels.json")
        rng = np.random.default_rng(len(calls))
        np.save(run_dir / "analysis" / "ca_xyz.npy", rng.normal(size=(30, n, 3)) * lv)
        man = {"status": "PASS", "metrics_file": str(run_dir / "analysis" / "metrics.json"), "n_frames": 40,
               "rmsd_backbone_mean_A": lv, "ligands": {}, "restrained_production": [], "figures": {}}
        atomic_write_json(man, run_dir / "analysis" / "analysis_manifest.json")
        return man
    monkeypatch.setattr("md20.analysis.traj.analyse_run", fake)
    return wf, runs, calls


def test_workflow_analyse_runs_every_replica_and_keeps_summaries_compatible(tmp_path, monkeypatch):
    wf, runs, calls = _workflow(tmp_path, monkeypatch, {"complex": {"r1": 2.0, "r2": 4.0, "r3": 9.0}})
    res = wf.analyse(runs)
    assert sorted(calls) == ["r1", "r2", "r3"]                                  # not only run_ids[0]
    s = res["summaries"]["complex"]
    assert s["metrics_file"].endswith("r1/analysis/metrics.json") and s["rmsd_backbone_mean_A"] == 2.0      # old fields = first replica
    assert [x["run_id"] for x in s["replicas"]] == ["r1", "r2", "r3"] and all(x["analysed"] for x in s["replicas"])
    assert s["n_replicas_analysed"] == 3 and s["representative_run_id"] == "r1"
    agg = load_json(s["replica_set_file"], {})
    assert agg["schema"] == "md20.replica_set/1" and agg["n_analysed"] == 3 and agg["n_requested"] == 3
    assert agg["observables"]["rmsd_backbone_A"]["mean"] == pytest.approx(5.0, abs=0.1)
    assert s["replica_overlay"].endswith(".png")
    assert wf.state()["steps"]["analysis"]["summaries"]["complex"]["replica_set_file"] == s["replica_set_file"]


def test_workflow_analyse_reuses_stored_manifests_per_run(tmp_path, monkeypatch):
    wf, runs, calls = _workflow(tmp_path, monkeypatch, {"complex": {"r1": 2.0, "r2": 4.0}})
    wf.analyse(runs)
    calls.clear()
    wf.analyse(runs)
    assert calls == []                                                          # every replica's PASS manifest is reused


def test_workflow_one_failing_replica_is_kept_with_reason_and_does_not_hide_the_others(tmp_path, monkeypatch):
    wf, runs, calls = _workflow(tmp_path, monkeypatch, {"complex": {"r1": 2.0, "r2": 4.0, "r3": 3.0}})
    real = __import__("md20.analysis.traj", fromlist=["analyse_run"]).analyse_run

    def flaky(run_dir, top, **kw):
        if run_dir.name == "r2":
            raise RuntimeError("boom")
        return real(run_dir, top, **kw)
    monkeypatch.setattr("md20.analysis.traj.analyse_run", flaky)
    s = wf.analyse(runs)["summaries"]["complex"]
    by = {x["run_id"]: x for x in s["replicas"]}
    assert by["r2"]["analysed"] is False and "boom" in by["r2"]["reason"] and by["r1"]["analysed"] and by["r3"]["analysed"]
    agg = load_json(s["replica_set_file"], {})
    assert agg["n_analysed"] == 2 and [x["run_id"] for x in agg["excluded"]] == ["r2"]


def test_workflow_single_replica_has_unavailable_uncertainty(tmp_path, monkeypatch):
    wf, runs, calls = _workflow(tmp_path, monkeypatch, {"complex": {"r1": 3.0}})
    s = wf.analyse(runs)["summaries"]["complex"]
    agg = load_json(s["replica_set_file"], {})
    assert agg["between_replica"]["reason"] == "單一軌跡無法估計重複間不確定性" and "single_replica" in agg["flags"]


def test_incompatible_replica_conditions_block_the_comparison_but_not_the_analyses(tmp_path, monkeypatch):
    lv = {"apo": {"a1": 2.0, "a2": 2.5}, "complex": {"c1": 3.0, "c2": 3.5}}
    wf, runs, calls = _workflow(tmp_path, monkeypatch, lv, systems=("apo", "complex"), temps={"c2": 310.0})   # c2 differs
    res = wf.analyse(runs)
    cmp_ = res["comparison"]["comparability"]
    assert cmp_["comparable"] is False and any(d["field"] == "temperature_k" for d in cmp_["differences"])
    assert cmp_["within_system"]["complex"]["comparable"] is False and cmp_["within_system"]["apo"]["comparable"] is True
    assert set(cmp_["replica_conditions"]["complex"]) == {"c1", "c2"}                      # every replica's run.json was read
    assert sorted(calls) == ["a1", "a2", "c1", "c2"]                                       # all four analysed regardless
    for k in ("apo", "complex"):
        assert res["summaries"][k]["n_replicas_analysed"] == 2
        assert load_json(res["summaries"][k]["replica_set_file"], {})["n_analysed"] == 2   # unrelated analyses intact
    assert res["comparison"]["delta_rmsf"]["status"] == "not_comparable"                   # only the comparison is refused


def test_unknown_conditions_in_any_replica_block_the_comparison(tmp_path, monkeypatch):
    lv = {"apo": {"a1": 2.0, "a2": 2.5}, "complex": {"c1": 3.0, "c2": 3.5}}
    wf, runs, calls = _workflow(tmp_path, monkeypatch, lv, systems=("apo", "complex"))
    (wf.project.case(runs["complex"]["case_id"]).dir / "runs" / "c2" / "run.json").unlink()   # no record for one replica
    cmp_ = wf.analyse(runs)["comparison"]["comparability"]
    assert cmp_["comparable"] is False and "temperature_k" in cmp_["unknown"]


def test_common_basis_takes_every_replica_as_its_own_trajectory(tmp_path, monkeypatch):
    lv = {"apo": {"a1": 2.0, "a2": 2.5}, "complex": {"c1": 3.0, "c2": 3.5, "c3": 4.0}}
    wf, runs, calls = _workflow(tmp_path, monkeypatch, lv, systems=("apo", "complex"))
    comp = wf.analyse(runs)["comparison"]
    assert comp["comparability"]["comparable"] is True
    cb = load_json(comp["common_basis_file"], {})
    assert cb["status"] == "ok"
    assert set(cb["systems"]) == {"apo/a1", "apo/a2", "complex/c1", "complex/c2", "complex/c3"}
    assert cb["trajectory_labels"]["complex/c3"] == {"system": "complex", "run_id": "c3"}
    assert all(cb["per_system"][n]["n_frames"] == 30 for n in cb["systems"])                # not joined end to end


# ------------------------------------------------------------------------------------------------ report
def _doc(lang):
    from md20.report.workflow_report import Doc
    return Doc(lang)


def _summary_for(tmp_path, reps, key="complex"):
    agg = RS.aggregate_replica_set(reps, system=key, n_requested=3)
    p = tmp_path / f"analysis_replicas_{key}.json"
    atomic_write_json(agg, p)
    return {key: {"replica_set_file": str(p)}}


@pytest.mark.parametrize("lang", ["zh", "en", "ja", "ko"])
def test_report_shows_per_replica_table_mean_sd_ci_and_k_of_n(tmp_path, lang):
    from md20.report.replica_section import replica_html
    doc = _doc(lang)
    html = replica_html(doc, None, _summary_for(tmp_path, _reps([2.0, 4.0, 9.0], bounds=[True, True, False])))
    for rid in ("run_0", "run_1", "run_2"):
        assert rid in html
    assert " ± " in html and "[" in html                                       # mean ± SD and the CI
    assert {"zh": "3 條中有 2 條", "en": "2 of 3 replicas", "ja": "3 本中 2 本", "ko": "3개 중 2개"}[lang] in html
    assert "ASP189" in html
    assert any(f["level"] == "caution" for f in doc.collected)                 # divergent replicas are called out


@pytest.mark.parametrize("lang,needle", [("zh", "單一軌跡無法估計重複間不確定性"), ("en", "cannot give between-replica uncertainty"),
                                           ("ja", "反復間の不確かさを推定できません"), ("ko", "반복 간 불확실성을 추정할 수 없습니다")])
def test_report_single_replica_says_unavailable_in_four_languages(tmp_path, lang, needle):
    from md20.report.replica_section import replica_html
    doc = _doc(lang)
    html = replica_html(doc, None, _summary_for(tmp_path, _reps([3.0])))
    assert needle in html
    import re
    cells = " ".join(re.findall(r"<td[^>]*>(.*?)</td>", html))
    assert "±" not in cells and "[" not in cells                                # no SD or interval is printed for n = 1
    assert any(f["level"] == "caution" for f in doc.collected)


def test_report_replica_count_uses_actual_runs_not_a_default_of_one(tmp_path, monkeypatch):
    from md20.report.workflow_report import _replica_count
    wf, runs, _ = _workflow(tmp_path, monkeypatch, {"complex": {"r1": 2.0, "r2": 3.0, "r3": 4.0}})
    wf.cfg["md"].pop("replicas", None)
    assert _replica_count(wf) == 3                                              # config silent -> 3, never 1
    wf._mark("md_runs", runs=runs)
    assert _replica_count(wf) == 3
    runs["complex"]["run_ids"] = ["r1", "r2"]
    wf._mark("md_runs", runs=runs)
    assert _replica_count(wf) == 2                                              # the real count wins
