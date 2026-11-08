"""D-142 (docs/specs/replicas.md §2, §7): the observables that used only the representative replica are aggregated across replicas
- apo–complex ΔRMSF (Welch CI), hydration sites, DSSP, PCA basin shares, DCCM, tICA/MSM qualification, membrane metrics - the
report lists every replica's acceptance, and the membrane-only analysis has a cache fingerprint.  No mdtraj/OpenMM: fakes only."""
import copy
import re
from pathlib import Path

import numpy as np
import pytest

from md20.analysis import replica_set as RS
from md20.util.jsonio import atomic_write_json, load_json
from test_replica_analysis import _metrics, _workflow, _doc


# ------------------------------------------------------------------------------------------------ fakes
def _ext(shift: float = 0.0, *, sites=None, n_res: int = 12, tica_ok=True, flat=True, water=True, seed=0) -> dict:
    """An extended.json with just the blocks the replica aggregation reads."""
    rng = np.random.default_rng(seed)
    res = [f"ALA{i}" for i in range(n_res)]
    A = rng.normal(size=(n_res, 4))
    C = np.corrcoef(A + shift * np.arange(n_res)[:, None] * 0.0)
    sites = sites if sites is not None else [{"xyz_nm": [0.1, 0.2, 0.3], "density_ratio": 4.0, "occupancy": 0.8, "distance_to_center_nm": 0.4}]
    ext = {"schema": "md20.extended/3", "errors": {},
           "dssp": {"fraction": {"H": [0.5 + shift] * 10, "E": [0.1] * 10, "C": [0.4 - shift] * 10}, "residues": res,
                    "per_residue": {"H": [min(1.0, 0.5 + shift + 0.01 * i) for i in range(n_res)], "E": [0.1] * n_res}},
           "dccm": {"matrix": C.tolist(), "residues": res},
           "clusters": {"populations": [0.6 - shift, 0.4 + shift], "n_clusters": 2},
           "tica": ({"status": "ok", "lag_ns": 0.2, "timescales_ns": [1.5 + shift, 0.3],
                     "msm": {"eligibility": "exploratory" if tica_ok else "insufficient", "reason": None if tica_ok else "transitions",
                             "its_flat": flat, "transitions": 500, "trajectory_ns": 20.0}}),
           "ligands": {"L01": {"errors": {}, "hydration": ({"status": "ok", "n_frames": 100, "sites": sites} if water else {"status": "no_water"})}}}
    return ext


def _rep(i, level=3.0, ext=None, **kw):
    r = {"run_id": f"run_{i}", "replica_index": i, "status": "COMPLETE", "metrics": _metrics(level), "extended": ext}
    r.update(kw)
    return r


def _rmsf_set(vals_by_run: dict, system: str):
    """Aggregate whose per-residue RMSF is given per run (list of 12 values)."""
    reps = []
    for rid, vals in vals_by_run.items():
        m = _metrics(3.0)
        m["rmsf_ca_A"] = list(vals)
        reps.append({"run_id": rid, "status": "COMPLETE", "metrics": m})
    return RS.aggregate_replica_set(reps, system=system)


# ------------------------------------------------------------------------------------------------ ΔRMSF
def test_delta_rmsf_ci_is_welch_on_per_replica_values_and_matches_scipy():
    ref = {"a1": [1.0 + 0.02 * i for i in range(12)], "a2": [1.1 + 0.02 * i for i in range(12)], "a3": [0.9 + 0.02 * i for i in range(12)]}
    oth = {"c1": [1.6 + 0.02 * i for i in range(12)], "c2": [1.8 + 0.02 * i for i in range(12)], "c3": [1.5 + 0.02 * i for i in range(12)], "c4": [1.7 + 0.02 * i for i in range(12)]}
    A, C = _rmsf_set(ref, "apo"), _rmsf_set(oth, "complex")
    r = RS.delta_rmsf_between_replicas("apo", A["per_residue"]["rmsf_ca_A"], "complex", C["per_residue"]["rmsf_ca_A"], {"comparable": True})
    assert r["status"] == "ok" and (r["n_ref"], r["n_other"]) == (3, 4) and r["n_common"] == 12
    row = r["residues"][0]
    a = np.array([v[0] for v in ref.values()]); b = np.array([v[0] for v in oth.values()])
    assert row["delta_A"] == pytest.approx(b.mean() - a.mean(), abs=1e-3)
    scipy_stats = pytest.importorskip("scipy.stats")
    t = scipy_stats.ttest_ind(b, a, equal_var=False)
    ci = t.confidence_interval(0.95)
    assert row["ci95_low"] == pytest.approx(ci.low, abs=2e-3) and row["ci95_high"] == pytest.approx(ci.high, abs=2e-3)
    assert row["ci_excludes_zero"] is True and row["sign_k"] == 4 and row["sign_n"] == 4          # every complex replica shifts the same way
    assert r["divergent"] is None and "CV" in r["divergent_reason"]                                # D-144: no CV on a difference


def test_divergent_replicas_widen_the_delta_rmsf_interval_and_flip_the_verdict():
    ref = {"a1": [1.0] * 12, "a2": [1.05] * 12, "a3": [0.95] * 12}
    tight = {"c1": [1.5] * 12, "c2": [1.55] * 12, "c3": [1.45] * 12}
    wide = {"c1": [0.6] * 12, "c2": [1.5] * 12, "c3": [2.4] * 12}                                   # same mean 1.5, replicas disagree
    A = _rmsf_set(ref, "apo")["per_residue"]["rmsf_ca_A"]
    rt = RS.delta_rmsf_between_replicas("apo", A, "complex", _rmsf_set(tight, "c")["per_residue"]["rmsf_ca_A"], {"comparable": True})
    rw = RS.delta_rmsf_between_replicas("apo", A, "complex", _rmsf_set(wide, "c")["per_residue"]["rmsf_ca_A"], {"comparable": True})
    assert rt["residues"][0]["delta_A"] == pytest.approx(rw["residues"][0]["delta_A"], abs=1e-6)
    wt = rt["residues"][0]["ci95_high"] - rt["residues"][0]["ci95_low"]
    ww = rw["residues"][0]["ci95_high"] - rw["residues"][0]["ci95_low"]
    assert ww > 5 * wt
    assert rt["n_ci_excludes_zero"] == 12 and rw["n_ci_excludes_zero"] == 0                         # the interval, not the mean, decides "different"
    assert rt["expected_false_positives"] == pytest.approx(0.6) and rw["most_flexible"] == []


def test_delta_rmsf_needs_two_replicas_per_side_and_comparable_systems():
    A3 = _rmsf_set({"a1": [1.0] * 12, "a2": [1.1] * 12, "a3": [0.9] * 12}, "apo")["per_residue"]["rmsf_ca_A"]
    C1 = _rmsf_set({"c1": [1.6] * 12}, "complex")["per_residue"]["rmsf_ca_A"]
    one = RS.delta_rmsf_between_replicas("apo", A3, "complex", C1, {"comparable": True})
    assert one["status"] == "unavailable" and "residues" not in one and "2" in one["reason"] and one["n_other"] == 1
    one_ref = RS.delta_rmsf_between_replicas("apo", C1, "complex", A3, {"comparable": True})
    assert one_ref["status"] == "unavailable"
    nc = RS.delta_rmsf_between_replicas("apo", A3, "complex", A3, {"comparable": False, "differences": [{"field": "temperature_k"}], "unknown": []})
    assert nc["status"] == "not_comparable"
    assert RS.delta_rmsf_between_replicas("apo", None, "complex", A3, None)["status"] == "unavailable"


def test_welch_non_integer_df_is_between_neighbouring_table_values():
    assert RS.t_critical_975_float(5.0) == RS.t_critical_975(5)
    v = RS.t_critical_975_float(5.5)
    assert RS.t_critical_975(6) < v < RS.t_critical_975(5)


# ------------------------------------------------------------------------------------------------ hydration
def test_hydration_sites_are_matched_by_position_and_unreproduced_ones_are_marked():
    s_main = lambda dx, occ: {"xyz_nm": [0.5 + dx, 0.5, 0.5], "density_ratio": 5.0, "occupancy": occ}
    reps = [_rep(0, ext=_ext(sites=[s_main(0.00, 0.9), {"xyz_nm": [1.0, 0.0, 0.0], "density_ratio": 3.0, "occupancy": 0.4}])),
            _rep(1, ext=_ext(sites=[s_main(0.10, 0.7)])),                                       # 0.10 nm away: same site (tolerance 0.2)
            _rep(2, ext=_ext(sites=[s_main(0.35, 0.8)]))]                                       # 0.35 nm away: not the same site
    h = RS.aggregate_replica_set(reps, system="x")["ligands"]["L01"]["hydration"]
    assert h["status"] == "ok" and h["n"] == 3 and h["match_tolerance_nm"] == 0.2
    by_k = sorted(h["sites"], key=lambda s: (-s["detected_k"], s["xyz_nm"]))
    main = by_k[0]
    assert main["detected_k"] == 2 and main["detected_n"] == 3 and main["status"] == "reproduced"
    assert main["occupancy_among_detecting"]["mean"] == pytest.approx(0.8) and main["occupancy_among_detecting"]["sd"] == pytest.approx(0.1414, abs=1e-3)
    others = [s for s in h["sites"] if s is not main]
    assert len(others) == 2 and all(s["status"] == "not_reproduced" and s["detected_k"] == 1 for s in others)
    assert all(s["occupancy_among_detecting"]["sd"] is None for s in others)                    # one replica: no SD
    assert h["n_reproduced"] == 1 and h["n_not_reproduced"] == 2


def test_hydration_replica_without_water_is_listed_with_reason_not_counted_as_zero():
    reps = [_rep(0, ext=_ext()), _rep(1, ext=_ext()), _rep(2, ext=_ext(water=False))]
    h = RS.aggregate_replica_set(reps, system="x")["ligands"]["L01"]["hydration"]
    assert h["n"] == 2 and h["sites"][0]["detected_k"] == 2
    assert [m["run_id"] for m in h["missing"]] == ["run_2"] and "no_water" in h["missing"][0]["reason"]


# ------------------------------------------------------------------------------------------------ DSSP, DCCM, clusters
def test_dssp_fractions_aggregate_per_replica_then_across():
    reps = [_rep(i, ext=_ext(shift=s)) for i, s in enumerate([0.0, 0.1, 0.2])]
    d = RS.aggregate_replica_set(reps, system="x")["structure"]["dssp"]
    assert d["status"] == "ok" and d["n"] == 3
    H = d["overall_fraction"]["H"]
    assert H["mean"] == pytest.approx(0.6) and H["sd"] == pytest.approx(0.1) and H["n"] == 3
    assert H["divergent"] is None and "CV" in H["divergent_reason"]                              # proportions carry no CV label
    pr = d["per_residue"]["H"]
    assert pr["n"] == 3 and len(pr["mean"]) == 12 and pr["sd"][0] == pytest.approx(0.1)
    assert pr["ci95_low"][0] < pr["mean"][0] < pr["ci95_high"][0]


def test_dccm_is_element_wise_mean_and_sd_with_long_range_summary():
    reps = [_rep(i, ext=_ext(seed=i)) for i in range(3)]
    d = RS.aggregate_replica_set(reps, system="x")["structure"]["dccm"]
    assert d["status"] == "ok" and d["n"] == 3 and d["n_residues"] == 12
    mats = np.array([np.array(r["extended"]["dccm"]["matrix"]) for r in reps])
    assert np.allclose(np.array(d["mean"]), mats.mean(0), atol=6e-3) and np.allclose(np.array(d["sd"]), mats.std(0, ddof=1), atol=6e-3)
    lr = d["long_range"]
    assert lr["mean_abs_correlation"]["n"] == 3 and lr["mean_abs_correlation"]["sd"] is not None and lr["mean_element_sd"] > 0
    assert d["thresholds"]["min_separation"] == 5
    for p in lr["top_pairs"]:
        assert 0 <= p["sign_k"] <= 3 and p["sign_n"] == 3 and p["divergent"] is None          # signed element: no CV


def test_clusters_aggregate_only_label_free_numbers():
    reps = [_rep(i, ext=_ext(shift=0.05 * i)) for i in range(3)]
    c = RS.aggregate_replica_set(reps, system="x")["structure"]["clusters"]
    assert c["identity_matched"] is False and c["n_clusters"]["mean"] == 2 and c["largest_cluster_share"]["n"] == 3


# ------------------------------------------------------------------------------------------------ PCA basin shares
def _cb(share_by_name: dict, system="complex", *, basins_per=2):
    """A fake analysis_common.json: replicas sit in two basins on shared axes with the given share in basin 0."""
    per, labels = {}, {}
    rng = np.random.default_rng(1)
    for name, s in share_by_name.items():
        n = 200
        k = int(s * n)
        P = np.vstack([rng.normal([0, 0], 0.05, size=(k, 2)), rng.normal([3, 3], 0.05, size=(n - k, 2))])
        per[name] = {"landscape": {"basins": [[0.0, 0.0, 0.0, round(s, 3)], [3.0, 3.0, 0.2, round(1 - s, 3)]]}, "projection": P.tolist()}
        labels[name] = {"system": system, "run_id": name.split("/")[-1]}
    return {"status": "ok", "xedges": np.linspace(-1, 4, 13).tolist(), "yedges": np.linspace(-1, 4, 13).tolist(), "per_system": per,
            "trajectory_labels": labels}


def test_pca_basin_shares_need_a_common_basis_otherwise_not_comparable():
    r = RS.pca_basin_shares(None, "complex")
    assert r["status"] == "not_comparable" and "共同基底" in r["reason"]
    agg = RS.aggregate_replica_set([_rep(0, ext=_ext()), _rep(1, ext=_ext())], system="complex")
    assert agg["structure"]["pca_basins"]["status"] == "not_comparable"                       # default without a common basis
    assert RS.pca_basin_shares(_cb({"complex/r1": 0.5}), "complex", within_comparable=False)["status"] == "not_comparable"


def test_pca_basin_shares_mean_sd_across_replicas_and_flag_unconverged():
    ok = RS.pca_basin_shares(_cb({"complex/r1": 0.50, "complex/r2": 0.55, "complex/r3": 0.45}), "complex")
    assert ok["status"] == "ok" and ok["n"] == 3 and len(ok["basins"]) == 2 and ok["inconsistent_basins"] == []
    b0 = next(b for b in ok["basins"] if abs(b["xy"][0]) < 0.5)
    assert b0["share"]["mean"] == pytest.approx(0.5, abs=0.02) and b0["share"]["sd"] == pytest.approx(0.05, abs=0.01)
    assert b0["share"]["divergent"] is None
    bad = RS.pca_basin_shares(_cb({"complex/r1": 0.9, "complex/r2": 0.5, "complex/r3": 0.2}), "complex")
    assert set(bad["inconsistent_basins"]) == {1, 2} and "未收斂" in bad["interpretation"]
    agg = RS.aggregate_replica_set([_rep(0), _rep(1), _rep(2)], system="complex")
    RS.attach_basin_shares(agg, _cb({"complex/r1": 0.9, "complex/r2": 0.5, "complex/r3": 0.2}), within_comparable=True)
    assert "unconverged:pca_basins" in agg["flags"] and agg["structure"]["pca_basins"]["status"] == "ok"


def test_pca_basin_shares_single_replica_has_no_uncertainty():
    r = RS.pca_basin_shares(_cb({"complex": 0.6}), "complex")
    assert r["status"] == "ok" and r["n"] == 1 and r["between_replica"]["status"] == "unavailable"
    assert all(b["share"]["sd"] is None and b["range"] is None for b in r["basins"])


# ------------------------------------------------------------------------------------------------ tICA / MSM
def test_tica_msm_is_qualified_per_replica_and_never_pooled():
    reps = [_rep(0, ext=_ext()), _rep(1, ext=_ext(tica_ok=False)), _rep(2, ext=_ext(flat=False))]
    t = RS.aggregate_replica_set(reps, system="x")["structure"]["tica_msm"]
    assert t["pooled"] is False and (t["qualifies_k"], t["qualifies_n"]) == (2, 3)
    assert [x["qualifies"] for x in t["per_replica"]] == [True, False, True]
    assert t["per_replica"][1]["slowest_timescale_ns"] is None and t["per_replica"][1]["msm_reason"] == "transitions"
    assert t["rate_reportable"] is False and "不報速率" in t["rate_reason"]
    assert not any(k in t for k in ("mean", "sd", "ci95", "timescale_mean", "rate"))               # no pooled number exists
    all_ok = RS.aggregate_replica_set([_rep(i, ext=_ext()) for i in range(3)], system="x")["structure"]["tica_msm"]
    assert all_ok["rate_reportable"] is True and all_ok["its_flat_k"] == 3                          # still no rate value, only permission


# ------------------------------------------------------------------------------------------------ membrane
def _mem(dpp, apl, depth, crossed=False, status="PASS", cw=(2, 2, 3, 3)):
    return {"dpp_mean_nm": dpp, "apl_mean_nm2": apl, "core_water": list(cw), "acceptance": {"status": status},
            "insertion": {"PEP": {"mean_com_depth_nm": depth, "mean_deepest_nm": depth + 0.2, "crossed_centre": crossed}}}


def test_membrane_metrics_per_replica_and_aggregate():
    reps = [_rep(0, membrane=_mem(3.8, 0.64, 0.5)), _rep(1, membrane=_mem(3.9, 0.66, 0.7, True, "AUTO_FIXED")), _rep(2, membrane=_mem(3.7, 0.65, 0.6))]
    reps[0]["membrane_report"] = {"scd": {"sn1:C32": -0.2}}
    reps[1]["membrane_report"] = {"scd": {"sn1:C32": -0.22}}
    m = RS.aggregate_replica_set(reps, system="x")["membrane"]
    assert m["status"] == "ok" and m["n"] == 3
    d = m["observables"]["dpp_mean_nm"]
    assert d["mean"] == pytest.approx(3.8) and d["sd"] == pytest.approx(0.1) and [x["run_id"] for x in d["per_replica"]] == ["run_0", "run_1", "run_2"]
    assert m["observables"]["core_water"]["mean"] == pytest.approx(3.0)                              # second half of each series
    sol = m["solutes"]["PEP"]
    assert sol["crossed_centre"]["k"] == 1 and sol["crossed_centre"]["n"] == 3 and sol["mean_com_depth_nm"]["divergent"] is None
    assert m["acceptance_pass"]["k"] == 2 and m["acceptance_pass"]["n"] == 3
    assert m["scd"]["n"] == 2 and m["scd"]["order_parameter"]["sn1:C32"]["mean"] == pytest.approx(-0.21)


def test_membrane_only_metrics_json_with_membrane_key_is_read():
    reps = []
    for i in range(2):
        reps.append({"run_id": f"r{i}", "status": "COMPLETE", "metrics": {"n_frames": 5, "membrane": _mem(3.8 + 0.1 * i, 0.6, 0.5)}})
    m = RS.aggregate_replica_set(reps, system="bilayer")["membrane"]
    assert m["status"] == "ok" and m["observables"]["dpp_mean_nm"]["n"] == 2


# ------------------------------------------------------------------------------------------------ n = 1 and missing data
def test_single_replica_is_unavailable_for_every_new_observable():
    r = _rep(0, ext=_ext(), membrane=_mem(3.8, 0.64, 0.5))
    agg = RS.aggregate_replica_set([r], system="x")
    st = agg["structure"]
    for k in ("dssp", "dccm", "tica_msm", "clusters"):
        assert st[k]["between_replica"]["status"] == "unavailable" and st[k]["between_replica"]["reason"] == RS.UNAVAILABLE_SINGLE, k
    assert st["dssp"]["overall_fraction"]["H"]["sd"] is None and st["dssp"]["per_residue"]["H"]["sd"] is None
    assert st["dccm"]["sd"] is None and st["dccm"]["long_range"]["n_strong_reproducible"] is None
    assert st["clusters"]["n_clusters"]["ci95"] is None
    h = agg["ligands"]["L01"]["hydration"]
    assert h["sites"][0]["status"] == "unavailable" and h["sites"][0]["occupancy_among_detecting"]["ci95"] is None
    assert agg["membrane"]["between_replica"]["status"] == "unavailable" and agg["membrane"]["observables"]["dpp_mean_nm"]["ci95"] is None


def test_missing_extended_or_blocks_give_unavailable_with_reason_not_numbers():
    agg = RS.aggregate_replica_set([_rep(0), _rep(1)], system="x")                                   # no extended.json at all
    st = agg["structure"]
    for k in ("dssp", "dccm", "tica_msm", "clusters"):
        assert st[k]["status"] == "unavailable" and "沒有" in st[k]["reason"] and len(st[k]["missing"]) == 2, k
    assert agg["ligands"]["L01"]["hydration"]["status"] == "unavailable"
    assert agg["membrane"]["status"] == "unavailable"
    e = _ext()
    e.pop("dssp"); e["errors"]["dssp"] = "ValueError: boom"
    agg = RS.aggregate_replica_set([_rep(0, ext=e), _rep(1, ext=_ext())], system="x")
    d = agg["structure"]["dssp"]
    assert d["status"] == "ok" and d["n"] == 1 and "boom" in d["missing"][0]["reason"] and d["between_replica"]["status"] == "unavailable"
    assert agg["replicas"][0]["extended_errors"] == {"dssp": "ValueError: boom"}


# ------------------------------------------------------------------------------------------------ report
@pytest.mark.parametrize("lang,needle", [("zh", "3 條中有 2 條"), ("en", "2 of 3 replicas"), ("ja", "3 本中 2 本"), ("ko", "3개 중 2개")])
def test_report_shows_structure_hydration_tica_membrane_in_four_languages(tmp_path, lang, needle):
    from md20.report.replica_section import replica_html
    reps = [_rep(0, ext=_ext(seed=0), membrane=_mem(3.8, 0.64, 0.5)), _rep(1, ext=_ext(seed=1), membrane=_mem(3.9, 0.65, 0.6)),
            _rep(2, ext=_ext(seed=2, tica_ok=False), membrane=_mem(3.7, 0.66, 0.7))]
    agg = RS.aggregate_replica_set(reps, system="complex", n_requested=3)
    RS.attach_basin_shares(agg, _cb({"complex/r1": 0.9, "complex/r2": 0.5, "complex/r3": 0.2}), within_comparable=True)
    p = tmp_path / "analysis_replicas_complex.json"
    atomic_write_json(agg, p)
    doc = _doc(lang)
    html = replica_html(doc, None, {"complex": {"replica_set_file": str(p)}})
    assert needle in html                                                                            # tICA qualification and hydration k of n
    assert "run_2" in html and "<h4>" in html and "S_CD" not in html
    assert html.count("<table>") >= 8
    assert any(f["level"] == "caution" and "complex" in f["text"][0] for f in doc.collected)         # unconverged basins flagged


def test_report_pca_not_comparable_and_single_replica_notes(tmp_path):
    from md20.report.replica_section import replica_html
    agg = RS.aggregate_replica_set([_rep(0, ext=_ext())], system="complex")
    p = tmp_path / "a.json"
    atomic_write_json(agg, p)
    html = replica_html(_doc("en"), None, {"complex": {"replica_set_file": str(p)}})
    assert "PCA basin shares" in html and "not comparable" in html
    cells = " ".join(re.findall(r"<td[^>]*>(.*?)</td>", html))
    assert "±" not in cells                                                                          # n = 1: no SD anywhere


def test_report_delta_rmsf_table_states_n_and_false_positive_expectation(tmp_path):
    from md20.report.replica_section import delta_rmsf_html
    A = _rmsf_set({"a1": [1.0] * 12, "a2": [1.05] * 12, "a3": [0.95] * 12}, "apo")["per_residue"]["rmsf_ca_A"]
    C = _rmsf_set({"c1": [1.5] * 12, "c2": [1.55] * 12, "c3": [1.45] * 12}, "complex")["per_residue"]["rmsf_ca_A"]
    ok = RS.delta_rmsf_between_replicas("apo", A, "complex", C, {"comparable": True})
    one = RS.delta_rmsf_between_replicas("apo", A, "complex", _rmsf_set({"c1": [1.5] * 12}, "c")["per_residue"]["rmsf_ca_A"], {"comparable": True})
    p = tmp_path / "d.json"
    atomic_write_json({"schema": "md20.delta_rmsf_replicas/1", "ref": "apo", "pairs": {"complex": ok, "c1only": one}}, p)
    html = delta_rmsf_html(_doc("en"), {"delta_rmsf_replicas_file": str(p)})
    assert "3 replicas of apo, 3 of complex" in html and "no multiple-comparison correction" in html and "c1only versus apo: unavailable" in html
    assert delta_rmsf_html(_doc("en"), {}) == ""


def _stage_record(rdir: Path, stg: str, checks):
    d = rdir / "stages" / stg
    d.mkdir(parents=True, exist_ok=True)
    atomic_write_json({"acceptance": {"checks": checks}}, d / f"{stg}_complete.json")


def test_report_lists_every_replicas_acceptance_not_only_the_first(tmp_path, monkeypatch):
    from md20.report.workflow_report import _acceptance_html, _equil_figures
    wf, runs, _ = _workflow(tmp_path, monkeypatch, {"complex": {"r1": 2.0, "r2": 3.0, "r3": 4.0}})
    case = wf.project.case(runs["complex"]["case_id"])
    good = [{"check": "temperature", "ok": True, "mean": 300}, {"check": "density", "ok": True}]
    bad = [{"check": "temperature", "ok": True}, {"check": "density_drift", "ok": False, "drift": 0.04}]
    for rid, checks in (("r1", good), ("r2", bad), ("r3", good)):
        for stg in ("nvt", "npt"):
            _stage_record(case.dir / "runs" / rid, stg, checks)
    atomic_write_json({"status": "FAILED", "replica_index": 2}, case.dir / "runs" / "r3" / "run.json")
    cases = {"complex": {"case_id": runs["complex"]["case_id"], "ligands": []}}
    html = _acceptance_html(_doc("en"), wf, cases, runs)
    for rid in ("r1", "r2", "r3"):
        assert f"<td class=>{rid}</td>" in html
    assert "FAILED" in html                                                                            # a replica that did not finish is listed, with its status
    assert re.search(r"1/2 <b class=warn>fail：density_drift</b>", html)                               # only r2 fails, and the check is named
    assert html.count("<details") == 1 and "Checks in detail" in html
    assert _acceptance_html(_doc("zh"), wf, {}, runs) == ""
    # equilibration figures: one fold per replica when there are several (run id and status in the summary)
    png = tmp_path / "x.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    for rid in ("r1", "r2", "r3"):
        atomic_write_json({"figures": {"png": str(png)}, "acceptance": {"checks": good}}, case.dir / "runs" / rid / "stages" / "nvt" / "nvt_complete.json")
    eq = _equil_figures(_doc("en"), wf, cases, runs)
    assert eq.count("<details") == 3 and "complex r2 (COMPLETE)" in eq and "complex r3 (FAILED)" in eq
    assert eq.count("<details class=fold open>") == 1                                                  # only the first is open


def test_single_replica_equilibration_figures_keep_the_old_layout(tmp_path, monkeypatch):
    from md20.report.workflow_report import _equil_figures
    wf, runs, _ = _workflow(tmp_path, monkeypatch, {"complex": {"r1": 2.0}})
    case = wf.project.case(runs["complex"]["case_id"])
    png = tmp_path / "x.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    atomic_write_json({"figures": {"png": str(png)}, "acceptance": {"checks": []}}, case.dir / "runs" / "r1" / "stages" / "nvt" / "nvt_complete.json")
    eq = _equil_figures(_doc("en"), wf, {"complex": {"case_id": runs["complex"]["case_id"]}}, runs)
    assert "<details" not in eq and "complex NVT" in eq


# ------------------------------------------------------------------------------------------------ workflow wiring
def _workflow_with_extended(tmp_path, monkeypatch, levels, **kw):
    wf, runs, calls = _workflow(tmp_path, monkeypatch, levels, **kw)
    base = __import__("md20.analysis.traj", fromlist=["analyse_run"]).analyse_run

    def with_ext(run_dir, top, **k):
        man = base(run_dir, top, **k)
        i = len(calls)
        atomic_write_json(_ext(seed=i), run_dir / "analysis" / "extended.json")
        man = {**man, "extended_file": str(run_dir / "analysis" / "extended.json")}
        atomic_write_json(man, run_dir / "analysis" / "analysis_manifest.json")
        return man
    monkeypatch.setattr("md20.analysis.traj.analyse_run", with_ext)
    return wf, runs, calls


def test_workflow_aggregates_extended_blocks_delta_rmsf_and_basin_shares(tmp_path, monkeypatch):
    lv = {"apo": {"a1": 2.0, "a2": 2.5, "a3": 2.2}, "complex": {"c1": 3.0, "c2": 3.5, "c3": 4.0}}
    wf, runs, _ = _workflow_with_extended(tmp_path, monkeypatch, lv, systems=("apo", "complex"))
    res = wf.analyse(runs)
    agg = load_json(res["summaries"]["complex"]["replica_set_file"], {})
    assert agg["structure"]["dssp"]["n"] == 3 and agg["structure"]["tica_msm"]["qualifies_n"] == 3 and agg["ligands"]["L01"]["hydration"]["n"] == 3
    assert "dssp" in agg["replicas"][0]["extended_blocks"]
    pb = agg["structure"]["pca_basins"]
    assert pb["status"] == "ok" and pb["n"] == 3                                                        # a common basis exists (2 systems): shares come from it
    d = load_json(res["comparison"]["delta_rmsf_replicas_file"], {})
    assert d["ref"] == "apo" and d["pairs"]["complex"]["status"] == "ok" and (d["pairs"]["complex"]["n_ref"], d["pairs"]["complex"]["n_other"]) == (3, 3)
    assert "residues" not in res["comparison"]["delta_rmsf_replicas"]["complex"]


def test_workflow_single_replicas_give_unavailable_delta_rmsf_and_no_basin_shares(tmp_path, monkeypatch):
    lv = {"apo": {"a1": 2.0}, "complex": {"c1": 3.0}}
    wf, runs, _ = _workflow_with_extended(tmp_path, monkeypatch, lv, systems=("apo", "complex"))
    res = wf.analyse(runs)
    p = res["comparison"]["delta_rmsf_replicas"]["complex"]
    assert p["status"] == "unavailable" and p["between_replica"]["status"] == "unavailable"
    agg = load_json(res["summaries"]["complex"]["replica_set_file"], {})
    assert agg["structure"]["dssp"]["between_replica"]["status"] == "unavailable"


def test_workflow_not_comparable_systems_get_no_delta_rmsf(tmp_path, monkeypatch):
    lv = {"apo": {"a1": 2.0, "a2": 2.5}, "complex": {"c1": 3.0, "c2": 3.5}}
    wf, runs, _ = _workflow_with_extended(tmp_path, monkeypatch, lv, systems=("apo", "complex"), temps={"c2": 310.0})
    res = wf.analyse(runs)
    assert res["comparison"]["delta_rmsf_replicas"]["complex"]["status"] == "not_comparable"
    agg = load_json(res["summaries"]["complex"]["replica_set_file"], {})
    assert agg["structure"]["pca_basins"]["status"] == "not_comparable"                                # replicas of 'complex' differ in temperature


# ------------------------------------------------------------------------------------------------ membrane-only fingerprint
def _membrane_only_workflow(tmp_path, monkeypatch):
    from md20.project.store import Project
    from md20.workflow import Workflow, example_config
    cfg = copy.deepcopy(example_config())
    cfg["receptor"], cfg["ligands"] = {}, []
    cfg["binding"] = {"enabled": False, "ligands": [], "config": {}}
    cfg["md"]["membrane"] = {"type": "bilayer", "lipids": "mammalian"}
    wf = Workflow(Project.create(tmp_path, "p"), cfg)
    case = wf.project.new_case("c")
    case.build_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json({"topology_pdb": "t.pdb", "membrane": {"head_atom_indices": [0, 1], "plan": {"type": "bilayer"}}},
                      case.build_dir / "build_manifest.json")
    rd = case.dir / "runs" / "r1"
    rd.mkdir(parents=True)
    atomic_write_json({"status": "COMPLETE", "replica_index": 0}, rd / "run.json")
    calls = []

    def fake_membrane(run_dir, bm, *, label="", decisions=None, out_dir=None):
        calls.append(str(out_dir))
        w = Path(out_dir) if out_dir else run_dir / "analysis"
        w.mkdir(parents=True, exist_ok=True)
        s = {"n_frames": 5, "dpp_mean_nm": 3.8, "acceptance": {"status": "PASS", "name": "membrane equilibration", "explanation": "ok", "options": []}}
        atomic_write_json(s, w / "membrane_metrics.json", backup=False)
        return s
    monkeypatch.setattr("md20.analysis.membrane_run.analyse_membrane_run", fake_membrane)
    runs = {"bilayer": {"case_id": case.case_id, "run_ids": ["r1"]}}
    return wf, runs, rd, calls


def test_membrane_only_manifest_gets_a_fingerprint_and_is_reused(tmp_path, monkeypatch):
    wf, runs, rd, calls = _membrane_only_workflow(tmp_path, monkeypatch)
    wf.analyse(runs)
    man = load_json(rd / "analysis" / "analysis_manifest.json", {})
    assert man["status"] == "PASS" and man["kind"] == "membrane"
    fp = man["fingerprint"]
    assert fp["components"]["extra:membrane_analysis_version"] and fp["components"]["extra:kind"] and fp["components"]["extra:head_atom_indices"]
    assert set(man["outputs"]) == {"membrane_metrics.json", "metrics.json"} and man["commit_id"]
    assert (rd / "analysis" / "membrane_metrics.json").is_file() and (rd / "analysis" / "metrics.json").is_file()
    assert not list((rd / "analysis").glob(".staging-*"))
    calls.clear()
    wf.analyse(runs)
    assert calls == []                                                                                  # unchanged fingerprint: reused, nothing recomputed


def test_legacy_membrane_only_manifest_is_recomputed_never_the_md(tmp_path, monkeypatch):
    wf, runs, rd, calls = _membrane_only_workflow(tmp_path, monkeypatch)
    adir = rd / "analysis"
    adir.mkdir(parents=True)
    atomic_write_json({"n_frames": 5, "membrane": {}}, adir / "metrics.json")
    atomic_write_json({"status": "PASS", "kind": "membrane", "metrics_file": str(adir / "metrics.json"), "n_frames": 5,
                       "membrane_metrics_file": str(adir / "membrane_metrics.json"), "membrane_acceptance": None}, adir / "analysis_manifest.json")   # as written before D-142
    md_calls = []
    monkeypatch.setattr("md20.workflow.Workflow.run_md", lambda *a, **k: md_calls.append(1))
    wf.analyse(runs)
    assert len(calls) == 1 and md_calls == []                                                           # analysis recomputed once, MD untouched
    man = load_json(adir / "analysis_manifest.json", {})
    assert "fingerprint" in man
    prev = load_json(adir / "analysis_manifest.prev.json", {})
    assert prev["superseded"]["legacy"] is True and (adir / "prev" / "metrics.json").is_file()         # the old result is kept


def test_membrane_only_fingerprint_changes_with_the_membrane_plan(tmp_path, monkeypatch):
    wf, runs, rd, calls = _membrane_only_workflow(tmp_path, monkeypatch)
    wf.analyse(runs)
    case = wf.project.case(runs["bilayer"]["case_id"])
    bm = load_json(case.build_dir / "build_manifest.json", {})
    bm["membrane"]["head_atom_indices"] = [0, 1, 2]
    atomic_write_json(bm, case.build_dir / "build_manifest.json")
    calls.clear()
    wf.analyse(runs)
    assert len(calls) == 1                                                                               # another head-group selection: recomputed
