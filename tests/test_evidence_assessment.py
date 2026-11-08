"""D-134 (R2): one versioned scientific assessment across every output — evidence matrix, captions, executive summary,
comparison and GUI read the same claim record; execution success and a numerical ΔG° never make a supported claim."""
import copy
from types import SimpleNamespace

import pytest

from md20.report import evidence as EV
from md20.report.evidence import evidence_rows, summary
from md20.sampling.assessment import (CLAIM_SCHEMA, assess_pmf, claim_eligible, claim_status, override_record,
                                      resolve_assessment, strongest_claim)
from md20.sampling.multi import compare_binding

COND = {"cv": "com_distance_radial", "temperature_k": 300.0, "backbone_restraint_kj_mol_nm2": 100.0, "spectators": [],
        "anchor": "automatic", "funnel_restraint": False}


FCOND = {**COND, "cv": "axial_projection_z", "funnel_restraint": True, "standard_state": "funnel_cylinder_analytic"}
FCHECKS = {"bound_state": {"status": "pass", "q99_margin_nm": -0.2, "required_below_nm": -0.05},
           "solvation": {"status": "pass", "q01_dmin_nm": 0.8, "required_above_nm": 0.6},
           "bulk_in_cylinder": {"status": "pass", "z_cc_nm": 1.5}}


def _pmf(connected=True, funnel=False, checks=None):
    """A PMF whose solver succeeded.  connected=False: two blocks of windows that never overlap (full graph disconnected)
    while pooled coverage and adjacent overlap inside each block look fine."""
    n = 6
    if connected:
        M = [[1.0 if i == j else (0.3 if abs(i - j) == 1 else 0.0) for j in range(n)] for i in range(n)]
        mn = 0.3
    else:
        M = [[1.0 if i == j else (0.3 if abs(i - j) == 1 and (i < 3) == (j < 3) else 0.0) for j in range(n)] for i in range(n)]
        mn = 0.0
    extra = ({"cv": "axial_projection_z", "standard_state": {"treatment": "funnel_cylinder_analytic"},
              "funnel": {"checks": checks or FCHECKS}} if funnel else
             {"cv": "com_distance_radial", "standard_state": {"treatment": "1 M radial integral (no orientational correction)"}})
    return {**extra, "method": "MBAR", "converged": True, "plateau": True, "pmf_radial_kj_mol": [0, 1, 2],
            "quality": {"window_stats": [{"n_effective": 400.0}] * n},
            "coverage": {"continuous": True, "breaks": []},
            "overlap_matrix": {"matrix": M, "min_neighbour": mn},
            "half_split": {"diff_kj_mol": 0.6},
            "convergence": {"0.25": {"delta_pmf": 19.0}, "0.50": {"delta_pmf": 20.2}, "0.75": {"delta_pmf": 20.1},
                            "1.00": {"delta_pmf": 20.0}}}


def _res(connected=True, dG=-30.0, withheld=None, stored=True, ligand="A", funnel=False, checks=None, **kw):
    r = {"status": "PASS", "ligand": ligand, "context": "single", "delta_pmf_kj_mol": 30.0, "delta_pmf_err_kj_mol": 1.0,
         "dG_standard_kj_mol": dG, "dG_err_kj_mol": 1.0, "dG_withheld": withheld, "replicas": 3,
         "condition": dict(FCOND if funnel else COND)}
    if stored:
        r["assessment"] = assess_pmf(_pmf(connected, funnel, checks), dG_withheld=withheld, has_dG=dG is not None)
    r.update(kw)
    return r


def _wf(tmp_path, results, cfg=None, steps=None):
    st = {"binding": {"results": results}}
    st.update(steps or {})
    return SimpleNamespace(cfg=cfg or {"md": {"replicas": 3}, "binding": {"added": list(results)}},
                           state=lambda: {"steps": st}, dir=tmp_path)


def _brow(rows, t):
    return next(r for r in rows if r["item"] == "binding" and r["subject"] == t)


# ---------------------------------------------------------------------------------------------------- the core defect
def test_disconnected_overlap_with_solver_success_is_not_eligible():
    """Acceptance 3: a solver-success flag or a smooth PMF cannot rescue a disconnected overlap graph."""
    a = assess_pmf(_pmf(connected=False), has_dG=True)
    st = {d["id"]: d["status"] for d in a["diagnostics"]}
    assert st["solver"] == "pass" and st["histogram_coverage"] == "pass" and st["overlap_graph"] == "fail"
    assert not a["eligibility"]["delta_pmf_path_specific"] and not a["eligibility"]["dG_standard"]
    assert not a["eligibility"]["affinity_ranking"]
    r = _res(connected=False)
    for c in ("path_specific", "dG_standard", "affinity_ranking"):
        cs = claim_status(r, c)
        assert cs["eligible"] is False and cs["assessment"] == "fail" and "overlap_graph" in cs["failed"]
        assert "assess_failed" in cs["reasons"]
    assert claim_status(r, "diagnostic_curve")["eligible"] is True        # the curve is still a legal diagnostic
    assert strongest_claim(r) == "diagnostic_curve"


def test_execution_plus_numeric_dG_with_failed_sampling_is_never_supported_anywhere(tmp_path):
    bad, good = _res(connected=False, ligand="A"), _res(connected=True, ligand="B")
    assert bad["status"] == "PASS" and bad["dG_standard_kj_mol"] == -30.0
    # evidence matrix
    rows = evidence_rows(_wf(tmp_path, {"A": bad, "B": good}))
    ra, rb = _brow(rows, "A"), _brow(rows, "B")
    assert ra["status"] == "limited" and ra["claim"] == "diagnostic_curve"     # only the descriptive curve is allowed
    assert ra["requested_claim"] == "dG_standard" and ra["requested_eligible"] is False
    assert ra["execution_status"] == "ran" and ra["assessment"]["state"] == "fail"
    assert "overlap_graph" in ra["assessment"]["failed"] and ra["assessment"]["thresholds_version"]
    assert "assess_failed" in ra["reasons"]
    # D-140: a radial 1 M ΔG° is stated as approximate (claim dG_standard) and carries the "not for ranking" reason
    assert rb["status"] == "supported" and rb["claim"] == "dG_standard" and rb["claim_eligibility"] is True
    assert "no_funnel_standard_state" in rb["reasons"]
    # captions / executive summary sentences
    from md20.report.interpret import binding as interpret_binding
    from md20.report.figure_text import classify_assessment
    findings = interpret_binding({"A": bad})
    assert not [f for f in findings if f["level"] == "good"]
    assert any(f["level"] == "caution" and "not treated as a standard binding free energy" in f["text"][1] for f in findings)
    assert classify_assessment("A", bad["assessment"])[0]["level"] == "caution"
    good_findings = interpret_binding({"B": good})
    assert not [f for f in good_findings if f["level"] == "good" and "standard binding free energy" in f["text"][1]]   # radial: approximate
    assert any("not used to compare affinities" in f["text"][1] for f in good_findings)
    fun_findings = interpret_binding({"F": _res(True, funnel=True, ligand="F")})
    assert any(f["level"] == "good" and "funnel restraint" in f["text"][1] for f in fun_findings)
    # comparison: the failed one is out, so nothing is ranked
    comp = compare_binding({"A": bad, "B": good}, contexts={"single": ["A", "B"]})
    c = comp["contexts"]["single"]
    assert c["status"] == "INSUFFICIENT" and [x["key"] for x in c["not_compared"]] == ["A"]
    # GUI candidate rows
    from md20.gui import actions as ACT
    wf = SimpleNamespace(state=lambda: {"steps": {
        "md_cases": {"cases": {"c": {"mode": "docked_single", "ligands": ["A"]}}}, "md_runs": {"runs": {"c": {"status": "COMPLETE"}}},
        "binding": {"results": {"A": bad}}}}, cfg={"binding": {"enabled": True}})
    cand = ACT.binding_candidates(wf)
    assert cand[0]["dG_kj"] == -30.0 and cand[0]["dG_eligible"] is False


def test_matrix_comparison_and_claim_agree_on_a_grid(tmp_path):
    """The consumers can never contradict: supported <=> dG_standard eligible; context_basis use_dG <=> affinity_ranking
    eligible (D-140: ranking needs the funnel treatment; the partner "z" is a qualified funnel result)."""
    from md20.sampling.multi import context_basis
    cases = {"ok": _res(True, ligand="a"), "bad": _res(False, ligand="b"), "legacy": _res(stored=False, ligand="c"),
             "withheld": _res(True, dG=None, withheld="classroom", ligand="d"), "funnel": _res(True, ligand="e", funnel=True),
             "funnel_bad": _res(False, ligand="f", funnel=True)}
    rows = {r["subject"]: r for r in evidence_rows(_wf(tmp_path, cases)) if r["item"] == "binding"}
    for k, r in cases.items():
        el = claim_eligible(r, "dG_standard")
        assert (rows[k]["status"] == "supported") == el
        z = _res(True, ligand="z", funnel=True)
        z["condition"] = dict(r["condition"])            # same signature, so only the ranking rule decides
        assert (context_basis({k: r, "z": z}, [k, "z"])["use_dG"]) == claim_eligible(r, "affinity_ranking")
    assert claim_eligible(cases["ok"], "dG_standard") and not claim_eligible(cases["ok"], "affinity_ranking")
    assert claim_eligible(cases["funnel"], "affinity_ranking")
    assert rows["funnel"]["claim"] == "affinity_ranking" and rows["ok"]["claim"] == "dG_standard"


def test_qualified_result_is_supported_and_versioned(tmp_path):
    r = _res(True)
    cs = claim_status(r, "dG_standard")
    assert cs["schema"] == CLAIM_SCHEMA and cs["eligible"] and cs["assessment"] == "pass" and cs["assessment_source"] == "stored"
    assert cs["thresholds_version"] and cs["evidence_ids"] and cs["diagnostics"] and cs["execution_status"] == "PASS"
    assert _brow(evidence_rows(_wf(tmp_path, {"A": r})), "A")["status"] == "supported"


def test_path_specific_only_when_dG_is_withheld(tmp_path):
    r = _res(True, dG=None, withheld="classroom")
    row = _brow(evidence_rows(_wf(tmp_path, {"A": r})), "A")
    assert row["status"] == "limited" and row["claim"] == "path_specific" and row["claim_eligibility"] is True
    assert row["reasons"][0] == "path_specific_only" and "dg_withheld" in row["reasons"] and row["detail"] == "classroom"
    assert claim_status(r, "dG_standard")["eligible"] is False and claim_status(r, "path_specific")["eligible"]


def test_stored_flag_cannot_outvote_a_missing_or_withheld_value():
    r = _res(True)
    r["dG_standard_kj_mol"] = None
    assert claim_status(r, "dG_standard")["eligible"] is False
    r2 = _res(True, withheld="no plateau")
    assert claim_status(r2, "dG_standard")["eligible"] is False and "dg_withheld" in claim_status(r2, "dG_standard")["reasons"]


# ---------------------------------------------------------------------------------------------------- legacy
def test_legacy_result_without_assessment_is_limited_and_needs_reanalysis(tmp_path):
    r = _res(True, stored=False)
    assert "assessment" not in r
    row = _brow(evidence_rows(_wf(tmp_path, {"A": r})), "A")
    assert row["status"] == "limited" and row["requested_eligible"] is False
    assert "assess_legacy" in row["reasons"] and row["assessment"]["state"] == "unknown"
    assert row["assessment"]["source"] == "legacy"
    assert "需要重新分析" in EV.R["assess_legacy"][0] or "重新分析" in EV.R["assess_legacy"][0]
    cs = claim_status(r, "dG_standard")
    assert cs["assessment"] == "unknown" and not cs["eligible"]
    comp = compare_binding({"A": r, "B": _res(True, ligand="B")}, contexts={"single": ["A", "B"]})
    assert comp["contexts"]["single"]["status"] == "INSUFFICIENT"
    assert "awaiting reanalysis" in comp["contexts"]["single"]["not_compared"][0]["why"]


def test_reassessed_legacy_shows_diagnostics_but_stays_unqualified():
    r = _res(True, stored=False)
    a, src = resolve_assessment(r, _pmf(True))
    assert src == "reassessed" and a["legacy"] and a["failed"] == []
    assert not a["eligibility"]["delta_pmf_path_specific"] and not a["eligibility"]["dG_standard"]
    cs = claim_status(r, "dG_standard", pmf=_pmf(True))
    assert cs["assessment_source"] == "reassessed" and not cs["eligible"] and "assess_legacy" in cs["reasons"]
    cs2 = claim_status(_res(False, stored=False), "path_specific", pmf=_pmf(False))
    assert cs2["assessment"] == "fail" and "overlap_graph" in cs2["failed"]
    from md20.report.figure_text import classify_assessment
    out = classify_assessment("A", a)
    assert len(out) == 1 and out[0]["level"] == "caution" and "reanalysis" in out[0]["text"][1]


def test_missing_fields_are_unknown_never_pass():
    r = {"status": "PASS", "dG_standard_kj_mol": -20.0, "assessment": assess_pmf({"pmf_radial_kj_mol": [0, 1]})}
    cs = claim_status(r, "dG_standard")
    assert cs["assessment"] == "unknown" and not cs["eligible"] and "assess_unknown" in cs["reasons"]
    assert {"overlap_graph", "window_ess"} <= set(cs["unknown"])


def test_not_executed_is_missing(tmp_path):
    row = _brow(evidence_rows(_wf(tmp_path, {"A": {"status": "FAILED"}})), "A")
    assert row["status"] == "missing" and row["execution_status"] == "not_run" and row["claim_eligibility"] is False


# ---------------------------------------------------------------------------------------------------- overrides
def test_human_override_is_recorded_but_never_turns_fail_into_pass():
    r = _res(False)
    ov = override_record("dG_standard", "student", "report it anyway", "2026-11-07T00:00:00Z")
    cs = claim_status(r, "dG_standard", overrides=[ov])
    assert cs["eligible"] is False and cs["assessment"] == "fail"
    assert cs["overrides"][0]["why"] == "report it anyway" and cs["overrides"][0]["effect"] == "recorded decision only"
    r["overrides"] = [ov]                                              # also read from the result
    assert claim_status(r, "dG_standard")["overrides"] and not claim_eligible(r, "dG_standard")
    assert claim_status(r, "path_specific")["overrides"] == []         # scoped to the claim it names


# ---------------------------------------------------------------------------------------------------- MD row, replicas
def test_md_complete_is_execution_not_a_scientific_claim(tmp_path):
    steps = {"md_cases": {"cases": {"apo": {}, "holo": {}}},
             "md_runs": {"runs": {"apo": {"status": "COMPLETE", "run_ids": ["a", "b", "c"]}}}}
    rows = evidence_rows(_wf(tmp_path, {}, {"md": {"replicas": 3}}, steps))
    md = {r["subject"]: r for r in rows if r["item"] == "md"}
    assert md["apo"]["status"] == "ran" and md["apo"]["execution_status"] == "ran" and md["apo"]["claim"] is None
    assert md["apo"]["reasons"] == ["execution_only"] and md["holo"]["status"] == "missing"
    sm = summary(rows)
    assert sm["ran"] == 1 and sm["supported"] == 1          # the only supported row is the replica count
    assert not [r for r in rows if r["item"] == "md" and r["status"] == "supported"]


def test_planned_replicas_follow_the_replica_plan_default_three(tmp_path):
    from md20.engine.replica_plan import configured_replicas, DEFAULT_REPLICAS
    assert DEFAULT_REPLICAS == 3 and configured_replicas({"md": {}})[0] == 3
    steps = {"md_cases": {"cases": {"apo": {}}}, "md_runs": {"runs": {"apo": {"status": "COMPLETE", "run_ids": ["a"]}}}}
    row = next(r for r in evidence_rows(_wf(tmp_path, {}, {"md": {}}, steps)) if r["item"] == "replicas")
    assert row["planned"] == 3 and row["reasons"] == ["fewer_replicas"]
    row = next(r for r in evidence_rows(_wf(tmp_path, {}, {"md": {"replicas": 1}}, steps)) if r["item"] == "replicas")
    assert row["planned"] == 1 and row["reasons"] == ["single"]
    row = next(r for r in evidence_rows(_wf(tmp_path, {}, {"md": {"replicas": 2}}, steps)) if r["item"] == "replicas")
    assert row["planned"] == 2


# ---------------------------------------------------------------------------------------------------- four languages
NEW_REASONS = ("execution_only", "assess_legacy", "assess_failed", "assess_unknown", "path_specific_only", "no_curve")


def test_every_new_reason_and_claim_has_four_languages():
    for k in NEW_REASONS:
        assert k in EV.R, k
    for table in (EV.R, EV.C):
        for k, v in table.items():
            assert len(v) == 4 and all(isinstance(x, str) and x.strip() for x in v), k
    for c in ("dG_standard", "path_specific", "diagnostic_curve"):
        assert c in EV.C


def test_every_reason_code_the_claim_record_can_emit_has_a_text():
    emitted = set()
    for r in (_res(True), _res(False), _res(stored=False), _res(True, dG=None, withheld="x"), {"status": "FAILED"},
              {"status": "PASS", "assessment": assess_pmf(None)}):
        for c in ("diagnostic_curve", "path_specific", "dG_standard", "affinity_ranking"):
            emitted |= set(claim_status(r, c)["reasons"])
    assert emitted and emitted <= set(EV.R)


def test_report_evidence_table_renders_in_all_languages(tmp_path):
    from md20.report import workflow_report as WR
    bad = _res(False)
    wf = _wf(tmp_path, {"A": bad}, steps={"md_cases": {"cases": {"apo": {}}},
                                          "md_runs": {"runs": {"apo": {"status": "COMPLETE", "run_ids": ["a", "b", "c"]}}}})
    for lang in ("zh", "en", "ja", "ko"):
        doc = WR.Doc(lang, tmp_path)
        html = WR._evidence_html(doc, wf)
        assert EV.R["assess_failed"][{"zh": 0, "en": 1, "ja": 2, "ko": 3}[lang]] in html
        assert EV.R["execution_only"][{"zh": 0, "en": 1, "ja": 2, "ko": 3}[lang]] in html


def test_report_gdelta_column_hides_unqualified_number(tmp_path):
    from md20.report import workflow_report as WR
    assert WR._claim_of(_res(False), "dG_standard")["eligible"] is False
    assert WR._claim_of(_res(True), "dG_standard")["eligible"] is True
    assert WR._claim_of(_res(True, stored=False), "dG_standard")["assessment_source"] == "legacy"
