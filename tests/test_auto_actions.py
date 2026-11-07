"""D-122 (F17): automatic window refinement — what each round did, what it cost, what it changed (report only)."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from md20.report import auto_actions as AA

CFG = {"window_equil_ps": 10.0, "window_prod_ps": 50.0, "target_overlap": 0.2, "k_umbrella_max": 5000.0}


def _hole(ov):
    return {"between": [0.5, 0.6], "mu": [0.5, 0.6], "overlap": ov, "hole_nm": [0.52, 0.58], "n_new": 2, "k_new": 2000.0}


def _ins(c, k=2000.0, why="0.500/0.600 nm 兩個 window 實際取樣重疊只有 0.08（目標 0.20）；在兩個分佈之間補 2 個。"):
    return {"center": c, "k": k, "why": why}


def _entry(rnd, insert=(), extend=(), holes=(), cont=False, brk="無", completed=True, unsamplable=(), notes=(), **kw):
    return {"round": rnd, "insert": list(insert), "extend": list(extend), "holes": list(holes), "unsamplable": list(unsamplable),
            "notes": [f"合併直方圖斷點：{brk}", *notes], "continuous": cont, "completed": completed, **kw}


def _two_rounds():
    return [_entry(1, [_ins(0.53), _ins(0.56)], [0.40], [_hole(0.08)], brk="[[0.52, 0.58]]"),
            _entry(2, [_ins(0.545, 3000.0, "0.520–0.580 nm 合併樣本幾乎為零（PMF 會在此斷開）；補 window。")], [], [_hole(0.15)], brk="[[0.54, 0.55]]"),
            _entry(3, [], [], [], cont=True)]


MAN = {"config": CFG}
SMD = {"informed_plan": {"uniform": False, "centers": [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1]}, "plan": {"centers_nm": [0.4, 0.6]}}


def test_multi_round_summary_cost_and_before_after():
    s = AA.summarize_data(_two_rounds(), {"continuous": True, "breaks": []}, MAN, SMD)
    assert s["outcome"] == "continuous"
    r1, r2 = s["rounds"][0], s["rounds"][1]
    assert [x["center"] for x in r1["inserted"]] == [0.53, 0.56] and r1["extended"] == [0.40]
    assert r1["cost_ps"] == 2 * 60 + 50 and r2["cost_ps"] == 60                       # inserts: equil+prod, extension: prod
    assert s["totals"] == {"rounds": 2, "inserted": 3, "extended": 1, "skipped": 0, "cost_ps": 230.0, "cost_known": True}
    assert r1["before"]["min_overlap"] == 0.08 and r1["before"]["n_breaks"] == 1 and r1["before"]["continuous"] is False
    assert r1["after"]["min_overlap"] == 0.15 and r2["before"] is not r1["after"]       # after round 1 = planner's view at round 2
    assert r2["after"]["n_holes"] == 0 and r2["after"]["continuous"] is True and r2["after"]["n_breaks"] == 0
    assert r2["reason_counts"] == {"break": 1} and r1["reason_counts"] == {"overlap": 2}
    assert s["initial"] == {"n_windows": 8, "plan": "informed", "cost_ps": 480.0}


def test_summary_sentence_four_languages():
    s = AA.summarize_data(_two_rounds(), None, MAN, SMD)
    en, zh, ja, ko = (AA.summary_sentence(s, l) for l in ("en", "zh", "ja", "ko"))
    assert "2 rounds, added 3 windows and extended 1, costing 230 ps" in en and "was 0.08; after refinement no gap is below" in en
    assert "補窗 2 輪，新增 3 個窗口，延長 1 次，多花 230 ps" in zh and "取樣已連續" in zh
    assert "230 ps" in ja and "連続" in ja and "230 ps" in ko and "연속" in ko
    assert len({en, zh, ja, ko}) == 4
    assert "about 48%" in en                                                                # 230 / 480 of the first batch


def test_overlap_rise_when_the_last_round_sees_a_number():
    log = [_entry(1, [_ins(0.53)], [], [_hole(0.08)]), _entry(2, [_ins(0.54)], [], [_hole(0.21)]), _entry(3, [], [], [_hole(0.19)], cont=True)]
    s = AA.summarize_data(log, None, MAN, None)
    assert "rose from 0.08 to 0.19" in AA.summary_sentence(s, "en")
    assert s["initial"] is None


def test_cost_unknown_when_settings_not_recorded():
    s = AA.summarize_data(_two_rounds(), {"continuous": True, "breaks": []}, {"config": {"window_prod_ps": 50.0}}, None)
    assert s["rounds"][0]["cost_ps"] is None and s["rounds"][1]["cost_ps"] is None and s["totals"]["cost_ps"] is None
    assert "cannot be derived" in AA.summary_sentence(s, "en")
    cells = [row[2] for row in AA.table(s, "en")["rows"]]
    assert cells == ["not recorded", "not recorded"]
    # an extension-only round needs only window_prod_ps
    s2 = AA.summarize_data([_entry(1, [], [0.4], [], cont=False)], None, {"config": {"window_prod_ps": 50.0}}, None)
    assert s2["rounds"][0]["cost_ps"] == 50.0


def test_unsamplable_at_k_max_says_so_and_names_the_range():
    log = [_entry(1, [_ins(0.53, 5000.0)], [], [_hole(0.05)]), _entry(2, [], [], [], unsamplable=[[0.52, 0.58]], notes=[])]
    cov = {"continuous": False, "breaks": [[0.52, 0.58]]}
    s = AA.summarize_data(log, cov, MAN, None)
    assert s["outcome"] == "unsamplable"
    en = AA.summary_sentence(s, "en")
    assert "k is at its limit" in en and "0.520–0.580 nm" in en and "see the breaks" in en
    assert AA.evidence_status(s)[:2] == ("limited", ["auto_unsamplable"])
    assert "補不起來" in AA.summary_sentence(s, "zh")


def test_open_after_rounds_and_budget_note():
    log = [_entry(1, [_ins(0.53)], [], [_hole(0.05)], notes=["還有 3 個缺口未補（每輪上限 12、總上限 40）。"])]
    s = AA.summarize_data(log, {"continuous": False, "breaks": [[0.7, 0.8]]}, MAN, None)
    assert s["outcome"] == "open" and s["budget_limited"] is True
    en = AA.summary_sentence(s, "en")
    assert "Breaks remain after refinement at 0.700–0.800 nm" in en and "limit was used up" in en
    # after the last action only continuity is known: overlap after is not recorded, breaks are
    r = s["rounds"][0]
    assert r["after"]["n_breaks"] == 1 and r["after"]["min_overlap"] is None
    eff = AA.table(s, "en")["rows"][0][3]
    assert eff[0] == "Minimum overlap 0.05 → not recorded" and eff[1] == "Breaks 0 → 1" and eff[2] == "Continuous no → no"


def test_skipped_reasons_structured_and_from_notes():
    sk = {"center": 0.3, "k": 1000.0, "near": 0.301, "near_k": 1000.0, "min_sep_nm": 0.0123, "reason": "近重複"}
    log = [_entry(1, [_ins(0.53)], [], [_hole(0.1)], skipped=[sk]),
           _entry(2, [], [], [], cont=True, notes=["提案 0.400 nm（k 1000）與已有 window … 放棄此提案而不是挪 2 pm 假新增。"])]
    s = AA.summarize_data(log, None, MAN, None)
    assert s["totals"]["skipped"] == 2
    en = AA.skipped_lines(s, "en")
    assert "0.300 nm (k 1000)" in en[0] and "0.0010 nm from the existing window at 0.301" in en[0] and "minimum spacing 0.0123" in en[0]
    assert "logged text, in Chinese" in en[1] and "放棄此提案" in en[1]
    assert "放棄" in AA.skipped_lines(s, "zh")[0]
    assert any("Dropped 1 duplicate" in x for x in AA.table(s, "en")["rows"][0][1])
    # a round that only dropped proposals still appears, with "nothing inserted"
    assert AA.table(s, "en")["rows"][-1][1] == ["Dropped 1 duplicate proposals"]


def test_no_record_and_never_a_guess():
    for args in ((None,), ([],), ("garbage",)):
        s = AA.summarize_data(*args)
        assert s["outcome"] == "no_record" and s["rounds"] == []
        assert "No refinement record" in AA.summary_sentence(s, "en")
        assert AA.evidence_status(s) == ("limited", ["not_recorded"], False)
    assert AA.summarize(None)["outcome"] == "no_record"
    assert AA.summarize("/nonexistent/dir")["outcome"] == "no_record"


def test_no_action_needed_and_unknown_and_incomplete():
    s = AA.summarize_data([_entry(1, [], [], [], cont=True)], None, MAN, SMD)
    assert s["outcome"] == "no_action_needed" and AA.evidence_status(s)[0] == "supported"
    assert "already continuous" in AA.summary_sentence(s, "en")
    unk = AA.summarize_data([_entry(1, [_ins(0.5)], [], [_hole(0.1)])], None, MAN, None)       # no coverage, last pass acted
    assert unk["outcome"] == "unknown" and "not recorded" in AA.summary_sentence(unk, "en")
    inc = AA.summarize_data([_entry(1, [_ins(0.5)], [], [_hole(0.1)], completed=False)], {"continuous": False, "breaks": []}, MAN, None)
    assert inc["outcome"] == "incomplete" and AA.evidence_status(inc) == ("limited", ["auto_incomplete"], False)
    assert "planned" in AA.table(inc, "en")["rows"][0][2]


def test_garbled_notes_do_not_crash():
    e = _entry(1, [_ins(0.5)], [], [{"overlap": "x"}, "bad"], cont=None)
    e["notes"] = ["合併直方圖斷點：[[1, 2], oops"]
    s = AA.summarize_data([e], None, MAN, None)
    assert s["rounds"][0]["before"]["n_breaks"] is None and s["rounds"][0]["before"]["min_overlap"] is None


def test_files_roundtrip_and_result_dir(tmp_path):
    for name, obj in (("refine_log.json", _two_rounds()), ("coverage.json", {"continuous": True, "breaks": [], "windows": [{}] * 5}),
                      ("binding_manifest.json", MAN), ("smd.json", SMD)):
        (tmp_path / name).write_text(json.dumps(obj), encoding="utf-8")
    assert AA.result_dir({"figures": {"pmf": {"png": str(tmp_path / "pmf.png")}}}) == tmp_path
    assert AA.result_dir({}) is None
    s = AA.summarize(tmp_path)
    assert s["outcome"] == "continuous" and s["final"]["n_windows"] == 5 and s["final"]["source"] == "coverage"


@pytest.mark.parametrize("lang,word", [("zh", "自動補窗的效益與資源"), ("en", "What the automatic refinement did and cost"),
                                       ("ja", "自動補窓の効果と資源"), ("ko", "자동 보충 윈도우의 효과와 자원")])
def test_report_block_renders_in_four_languages(tmp_path, lang, word):
    from md20.report.workflow_report import Doc, _auto_actions_html
    for name, obj in (("refine_log.json", _two_rounds()), ("coverage.json", {"continuous": True, "breaks": []}),
                      ("binding_manifest.json", MAN), ("smd.json", SMD)):
        (tmp_path / name).write_text(json.dumps(obj), encoding="utf-8")
    html = _auto_actions_html(Doc(lang, tmp_path), "BEN", {"figures": {"pmf": {"png": str(tmp_path / "pmf.png")}}})
    assert word in html and "<table>" in html and "230" in html and html.count("<tr>") == 4        # header + first batch + 2 rounds
    assert "→" in html


def test_report_block_without_record_is_one_sentence(tmp_path):
    from md20.report.workflow_report import Doc, _auto_actions_html
    html = _auto_actions_html(Doc("en", tmp_path), "BEN", {"figures": {"pmf": {"png": str(tmp_path / "pmf.png")}}})
    assert "No refinement record" in html and "<table>" not in html


def test_evidence_row_added_per_passed_binding_target(tmp_path):
    from md20.report.evidence import evidence_rows, R, T
    for name, obj in (("refine_log.json", _two_rounds()), ("coverage.json", {"continuous": True, "breaks": []}), ("binding_manifest.json", MAN)):
        (tmp_path / name).write_text(json.dumps(obj), encoding="utf-8")
    res = {"BEN": {"status": "PASS", "dG_standard_kj_mol": -20.0, "figures": {"pmf": {"png": str(tmp_path / "pmf.png")}}},
           "PGA": {"status": "PASS", "dG_standard_kj_mol": -10.0}, "BAD": {"status": "FAILED"}}
    wf = SimpleNamespace(cfg={"binding": {}}, state=lambda: {"steps": {"binding": {"results": res}}}, dir=tmp_path)
    auto = {r["subject"]: r for r in evidence_rows(wf) if r["item"] == "auto"}
    assert set(auto) == {"BEN", "PGA"}                                         # a target that did not pass has no refinement row
    assert auto["BEN"]["status"] == "supported" and auto["PGA"]["status"] == "limited" and auto["PGA"]["reasons"] == ["not_recorded"]
    assert len(T["auto"]) == 4 and all(len(R[k]) == 4 for k in ("auto_unsamplable", "auto_open", "auto_incomplete"))


def test_texts_have_four_distinct_languages():
    for d in (AA.HEAD, AA.ACT, AA.WHY, AA.EFF, AA.SKIP, AA.SUM):
        for k, v in d.items():
            assert isinstance(v, tuple) and len(v) == 4 and all(v), k
    # no placeholder is lost in translation
    import re
    for d in (AA.ACT, AA.EFF, AA.SKIP, AA.SUM):
        for k, v in d.items():
            assert len({tuple(sorted(re.findall(r"\{(\w+)\}", x))) for x in v}) == 1, k
