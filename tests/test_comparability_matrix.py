"""D-120 (F05): candidate x candidate comparability matrix — grades come from compare_binding's own judgement."""
import copy
import itertools
from types import SimpleNamespace

import pytest

from md20.report.comparability import (GRADES, comparability_matrix, md_conditions_map, reason_text, R, LIM, NOTE)
from md20.sampling.multi import compare_binding

COND = {"cv": "com_distance_radial", "temperature_k": 300.0, "backbone_restraint_kj_mol_nm2": 100.0, "spectators": [],
        "anchor": "automatic", "funnel_restraint": False}


def _a(dG=True, path=True, reasons=()):
    return {"eligibility": {"delta_pmf_curve": True, "delta_pmf_path_specific": path, "dG_standard": dG and path,
                            "affinity_ranking": dG and path}, "reasons": list(reasons)}


def _r(dpmf=30.0, dG=-25.0, ligand=None, context="single", status="PASS", assessment="ok", cond="ok", replicas=3, **kw):
    r = {"status": status, "ligand": ligand, "context": context, "delta_pmf_kj_mol": dpmf, "delta_pmf_err_kj_mol": 1.0,
         "dG_standard_kj_mol": dG, "replicas": replicas}
    if assessment == "ok":
        r["assessment"] = _a(dG=dG is not None)
    elif assessment:
        r["assessment"] = assessment
    if cond == "ok":
        r["condition"] = dict(COND)
    elif cond:
        r["condition"] = cond
    r.update(kw)
    return r


def _grade(m, a, b):
    return m["cells"][a][b]["grade"]


def _codes(m, a, b, kind="reasons"):
    return [x["code"] for x in m["cells"][a][b][kind]]


def test_all_qualified_gives_ddg_and_agrees_with_compare_binding():
    res = {"A": _r(30, -25, "A"), "B": _r(20, -15, "B")}
    m = comparability_matrix(res)
    assert _grade(m, "A", "B") == _grade(m, "B", "A") == "ddg"
    assert m["cells"]["A"]["A"]["grade"] == "self"
    assert compare_binding(res, contexts={"single": ["A", "B"]})["contexts"]["single"]["status"] == "PASS"
    assert m["summary"]["ddg"] == 1


def test_only_path_specific_with_same_conditions_gives_order_and_says_why_not_ddg():
    res = {"A": _r(30, None, "A"), "B": _r(20, -15, "B")}
    res["A"]["dG_withheld"] = "no plateau"
    m = comparability_matrix(res)
    assert _grade(m, "A", "B") == "order"
    lim = m["cells"]["A"]["B"]["limits"][0]
    assert lim["code"] == "no_dG" and lim["keys"] == ["A"] and lim["withheld"] == {"A": "no plateau"}
    assert compare_binding(res, contexts={"single": ["A", "B"]})["contexts"]["single"]["status"] == "PATH_SPECIFIC"


def test_different_conditions_are_not_comparable_and_name_the_field():
    hot = dict(COND, temperature_k=310.0, anchor="user residues")
    res = {"A": _r(30, -25, "A"), "B": _r(20, -15, "B", cond=hot)}
    m = comparability_matrix(res)
    assert _grade(m, "A", "B") == "none"
    diff = {x["field"]: x["values"] for x in m["cells"]["A"]["B"]["reasons"] if x["code"] == "condition_differs"}
    assert set(diff) == {"temperature_k", "anchor"} and diff["temperature_k"] == {"A": 300.0, "B": 310.0}
    assert compare_binding(res, contexts={"single": ["A", "B"]})["contexts"]["single"]["status"] == "INSUFFICIENT"


def test_spectator_list_is_compared_by_count_like_compare_binding():
    res = {"A": _r(30, -25, "A", cond=dict(COND, spectators=["x"])), "B": _r(20, -15, "B", cond=dict(COND, spectators=["y"]))}
    assert _grade(comparability_matrix(res), "A", "B") == "ddg"          # same count → same signature, as in compare_binding
    res["B"]["condition"]["spectators"] = ["y", "z"]
    m = comparability_matrix(res)
    assert _grade(m, "A", "B") == "none" and m["cells"]["A"]["B"]["reasons"][0]["field"] == "n_spectators"


def test_unknown_fields_are_never_equal_or_qualified():
    res = {"A": _r(30, -25, "A"), "B": _r(20, -15, "B", cond=None), "C": _r(25, -20, "C", assessment=None),
           "D": _r(None, None, "D"), "E": _r(10, -5, "E", status="NEEDS_HUMAN")}
    m = comparability_matrix(res)
    assert _codes(m, "A", "B") == ["condition_missing"]
    assert _codes(m, "A", "C") == ["legacy"]
    assert "no_dpmf" in _codes(m, "A", "D")
    assert _codes(m, "A", "E") == ["exec_status"]
    for k in "BCDE":
        assert _grade(m, "A", k) == "none"
    # no condition at all on either side: not "equal because both empty"
    both = comparability_matrix({"A": _r(cond=None), "B": _r(cond=None)})
    assert _grade(both, "A", "B") == "none" and _codes(both, "A", "B") == ["condition_missing"] * 2


def test_unqualified_assessment_lists_its_reasons():
    bad = {"eligibility": {"delta_pmf_path_specific": False, "dG_standard": False}, "reasons": ["overlap_graph: fail", "window_ess: unknown"]}
    m = comparability_matrix({"A": _r(), "B": _r(assessment=bad)})
    x = m["cells"]["A"]["B"]["reasons"][0]
    assert x["code"] == "not_qualified" and x["key"] == "B" and x["items"] == ["overlap_graph: fail", "window_ess: unknown"]
    assert "overlap" in reason_text(x, "en").lower() and "重疊" in reason_text(x, "zh")


@pytest.mark.parametrize("variant", list(itertools.product(("ok", "nodg", "unq", "legacy", "failed"), repeat=2)))
def test_every_pair_agrees_with_compare_binding_on_the_same_two_results(variant):
    def make(kind, name):
        if kind == "ok":
            return _r(30, -25, name)
        if kind == "nodg":
            return _r(28, None, name)
        if kind == "unq":
            return _r(26, -20, name, assessment=_a(path=False, reasons=["half_split: fail"]))
        if kind == "legacy":
            return _r(24, -18, name, assessment=None)
        return _r(22, -10, name, status="NEEDS_HUMAN")
    for temp in (300.0, 310.0):
        res = {"A": make(variant[0], "A"), "B": make(variant[1], "B")}
        res["B"]["condition"] = dict(COND, temperature_k=temp)
        m = comparability_matrix(res)
        ctx = compare_binding(res, contexts={"single": ["A", "B"]})["contexts"].get("single") or {"status": "INSUFFICIENT"}
        expect = {"PASS": "ddg", "PATH_SPECIFIC": "order", "INSUFFICIENT": "none"}[ctx["status"]]
        assert _grade(m, "A", "B") == expect, (variant, temp)
        assert (_grade(m, "A", "B") == "none") == bool(m["cells"]["A"]["B"]["reasons"])      # none always says why


def test_pair_is_finer_than_the_group_table_and_symmetric():
    hot = dict(COND, temperature_k=320.0)
    res = {"A": _r(30, -25, "A"), "B": _r(20, -15, "B"), "C": _r(25, -20, "C", cond=hot)}
    assert compare_binding(res, contexts={"single": ["A", "B", "C"]})["contexts"]["single"]["status"] == "INSUFFICIENT"
    m = comparability_matrix(res)
    assert _grade(m, "A", "B") == "ddg" and _grade(m, "A", "C") == _grade(m, "B", "C") == "none"
    for a, b in itertools.permutations("ABC", 2):
        assert _grade(m, a, b) == _grade(m, b, a)
    assert sum(m["summary"].values()) == 3


def test_shared_pocket_is_descriptive_and_cross_context_is_not_comparable():
    ctx = "multi:docked_multi"
    res = {"A": _r(30, -25, "A"), "multi:A": _r(36, -30, "A", context=ctx),
           "multi:B": _r(10, None, "B", context=ctx, assessment=_a(path=False, reasons=["half_split: fail"])),
           "multi:C": _r(10, None, "C", context=ctx, status="NEEDS_HUMAN")}
    m = comparability_matrix(res)
    assert _grade(m, "multi:A", "multi:B") == "descriptive"
    assert _codes(m, "multi:A", "multi:B", "limits") == ["shared_pocket", "diagnostic_only"]
    assert _grade(m, "multi:A", "multi:C") == "none" and _codes(m, "multi:A", "multi:C") == ["exec_status"]
    assert _grade(m, "A", "multi:A") == "none" and "different_context" in _codes(m, "A", "multi:A")
    assert _codes(m, "A", "multi:A", "limits") == ["co_occupancy_pair"]
    assert compare_binding(res, contexts={"single": ["A"], ctx: ["multi:A", "multi:B"]})["contexts"][ctx]["status"] == "DESCRIPTIVE"
    unknown_case = {"multi:A": _r(context=None), "multi:B": _r(context=None)}
    assert "context_unknown" in _codes(comparability_matrix(unknown_case), "multi:A", "multi:B")


def test_md_settings_are_notes_only_and_unknown_is_listed():
    res = {"A": _r(30, -25, "A"), "B": _r(20, -15, "B")}
    md = {"A": {"temperature_k": 300.0, "ensemble": "NPT", "restrained": [], "water_model": "tip3p", "forcefield": ["amber14/protein.ff14SB.xml"],
                "solvent": "explicit", "hmr": False, "production_ps": 1000},
          "B": {"temperature_k": 300.0, "ensemble": "NPT", "restrained": [], "water_model": "opc", "forcefield": ["amber14/protein.ff14SB.xml"],
                "solvent": "explicit", "hmr": None, "production_ps": 1000}}
    m = comparability_matrix(res, md_conditions=md)
    assert _grade(m, "A", "B") == "ddg"                                   # not part of compare_binding's rule
    notes = {n["code"]: n for n in m["cells"]["A"]["B"]["notes"]}
    assert notes["md_differs"]["fields"] == ["water_model"] and notes["md_unknown"]["fields"] == ["hmr"]
    assert not [n for n in comparability_matrix(res)["cells"]["A"]["B"]["notes"] if n["code"].startswith("md_")]
    assert "replicas" not in {n["code"] for n in m["cells"]["A"]["B"]["notes"]}
    res["B"]["replicas"] = 1
    assert "replicas" in {n["code"] for n in comparability_matrix(res)["cells"]["A"]["B"]["notes"]}


def test_md_conditions_map_finds_the_run_of_each_result():
    cases = {"docked_A": {"mode": "docked_single", "ligands": ["A"]}, "docked_multi": {"mode": "docked_multi", "ligands": ["A", "B"]}}
    res = {"A": _r(context="single"), "multi:A": _r(context="multi:docked_multi")}
    conds = {"docked_A": {"temperature_k": 300.0}, "docked_multi": {"temperature_k": 310.0}}
    assert md_conditions_map(res, cases, conds) == {"A": {"temperature_k": 300.0}, "multi:A": {"temperature_k": 310.0}}
    assert md_conditions_map(res, cases, None) is None


def test_every_text_exists_in_four_languages():
    for table in (R, LIM, NOTE):
        for code, t in table.items():
            assert len(t) == 4 and all(t), code
    samples = [{"code": "exec_status", "key": "A", "detail": "X"}, {"code": "legacy", "key": "A"}, {"code": "no_dpmf", "key": "A"},
               {"code": "not_qualified", "key": "A", "items": ["solver: fail"]}, {"code": "different_context", "contexts": ["single", "multi:c"]},
               {"code": "context_unknown"}, {"code": "condition_missing", "key": "A"},
               {"code": "condition_differs", "field": "temperature_k", "values": {"A": 300, "B": 310}}, {"code": "unspecified"},
               {"code": "no_dG", "keys": ["A"], "withheld": {"A": "why"}}, {"code": "shared_pocket"},
               {"code": "diagnostic_only", "keys": ["A"]}, {"code": "co_occupancy_pair"},
               {"code": "md_differs", "fields": ["forcefield"]}, {"code": "md_unknown", "fields": ["hmr"]},
               {"code": "replicas", "fields": ["replicas"], "values": {"replicas": {"A": 1, "B": None}}}]
    for x in samples:
        outs = [reason_text(x, lang) for lang in ("zh", "en", "ja", "ko")]
        assert len(set(outs)) >= 3 and all(o and "{" not in o for o in outs), (x, outs)


# --------------------------------------------------------------------------------------------- report
def _wf(tmp_path, results, conditions=None):
    steps = {"binding": {"results": results},
             "md_cases": {"cases": {"docked_A": {"mode": "docked_single", "ligands": ["A"]},
                                    "docked_B": {"mode": "docked_single", "ligands": ["B"]}}},
             "analysis": {"comparison": {"comparability": {"conditions": conditions}} if conditions is not None else {}}}
    return SimpleNamespace(cfg={}, state=lambda: {"steps": steps}, dir=tmp_path)


@pytest.mark.parametrize("lang,word", [("zh", "不可比"), ("en", "not comparable"), ("ja", "比較不可"), ("ko", "비교 불가")])
def test_report_shows_matrix_for_two_or_more_candidates(tmp_path, lang, word):
    from md20.report.workflow_report import Doc, _comparability_html
    hot = dict(COND, temperature_k=310.0)
    html = _comparability_html(Doc(lang, tmp_path), _wf(tmp_path, {"A": _r(30, -25, "A"), "B": _r(20, -15, "B", cond=hot)}))
    temp = {"zh": "溫度", "en": "temperature", "ja": "温度", "ko": "온도"}[lang]
    assert word in html and "<table>" in html and temp in html
    assert "{" not in html.replace("{}", "")


def test_report_one_candidate_says_nothing_to_compare_and_zero_shows_nothing(tmp_path):
    from md20.report.workflow_report import Doc, _comparability_html
    one = _comparability_html(Doc("en", tmp_path), _wf(tmp_path, {"A": _r(30, -25, "A")}))
    assert "only one candidate" in one and "<table>" not in one
    assert "只有一個候選，沒有比較" in _comparability_html(Doc("zh", tmp_path), _wf(tmp_path, {"A": _r()}))
    assert _comparability_html(Doc("en", tmp_path), _wf(tmp_path, {})) == ""


def test_report_includes_md_note_when_conditions_recorded(tmp_path):
    from md20.report.workflow_report import Doc, _comparability_html
    conds = {"docked_A": {"temperature_k": 300.0, "ensemble": "NPT", "restrained": [], "water_model": "tip3p", "forcefield": ["a.xml"],
                          "solvent": "explicit", "hmr": False, "production_ps": 100},
             "docked_B": {"temperature_k": 300.0, "ensemble": "NPT", "restrained": [], "water_model": "opc", "forcefield": ["a.xml"],
                          "solvent": "explicit", "hmr": False, "production_ps": 100}}
    html = _comparability_html(Doc("en", tmp_path), _wf(tmp_path, {"A": _r(30, -25, "A"), "B": _r(20, -15, "B")}, conds))
    assert "ΔΔG° comparable" in html and "water model" in html
