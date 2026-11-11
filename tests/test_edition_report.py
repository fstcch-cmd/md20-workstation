"""D-181: the Lite part of the report.  It is written from the run's own data, in four languages, and appears only in a
Lite run.  Pure logic plus the synthetic report path of tests/test_report_v2.py (no engine)."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from md20 import edition as E
from md20.report import edition_section as ES
from md20.report import workflow_report as WR
from md20.sampling.assessment import assess_pmf
from md20.util.jsonio import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
LANG4 = ("zh", "en", "ja", "ko")


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_v2 = _load("tests/test_report_v2.py", "report_v2_fixture")           # the synthetic workflow of the report tests


@pytest.fixture
def lite(monkeypatch):
    """Simulate Lite the way tests/test_edition.py does: through the functions, never the environment."""
    monkeypatch.setattr(E, "current", lambda **kw: E.LITE)
    monkeypatch.setattr(E, "build_edition", lambda marker=None: E.LITE)
    monkeypatch.setattr(E, "licence_features", lambda: ["lite", "binding", "hts"])


# ------------------------------------------------------------------------------------------- data builders
def _research_cfg() -> dict:
    """A config that goes beyond every size limit that can be reduced."""
    return {"name": "x", "receptor": {"pdb_id": "3PTB"}, "ligands": [{"name": "BEN", "smiles": "NC(=[NH2+])c1ccccc1"}],
            "md": {"tier": "research", "production_ns": 100.0, "replicas": 3, "systems": ["apo", "docked_single"]},
            "binding": {"enabled": True, "ligands": ["BEN"], "target_replicas": 3, "config": {}}}


def _edition_state(cfg: dict) -> dict:
    """What the workflow stores under state["edition"] after it met the limits and the person accepted the reduction."""
    hits = E.check_config(cfg, E.LITE)
    _, changes = E.clamp_config(cfg, E.LITE)
    return E.state_record(hits, changes, at="2026-11-11T00:00:00")


def _pmf_assessment(**kw) -> dict:
    """A stored assessment of a quick PMF: windows that do not overlap enough, nothing recorded for several checks."""
    pmf = {"coverage": {"continuous": True, "breaks": []}, "method": "mbar", "converged": True, "plateau": True,
           "half_split": {"diff_kj_mol": 1.1},
           "overlap_matrix": {"min_neighbour": 0.012, "matrix": [[1, 0.012, 0.0], [0.012, 1, 0.0], [0.0, 0.0, 1]]}}
    pmf.update(kw)
    return assess_pmf(pmf)


def _binding_result(**kw) -> dict:
    r = {"status": "PASS", "ligand": "BEN", "replicas": 1, "delta_pmf_kj_mol": 24.3, "delta_pmf_err_kj_mol": 1.8,
         "dG_standard_kj_mol": None, "assessment": _pmf_assessment()}
    r.update(kw)
    return r


def _state(**steps) -> dict:
    return {"steps": steps}


# ------------------------------------------------------------------------------------------- source a: limits met
def test_hits_and_reductions_become_items_with_the_real_numbers(lite):
    cfg = _research_cfg()
    st = {"edition": _edition_state(cfg)}
    items = ES.gains(st, cfg, {}, "en")
    by_code = {i["evidence"]["code"]: i for i in items}
    assert by_code["md.production_ns"]["observed"] == "The production run was shortened from 100 ns to 10 ns."
    assert by_code["md.production_ns"]["feature"] == "long_run"
    assert by_code["md.tier"]["observed"] == "The simulation tier was changed from research to teaching."
    assert by_code["md.replicas"]["observed"] == "Independent repeats were reduced from 3 to 1 per system."
    assert by_code["md.replicas"]["feature"] == "replicas"
    assert by_code["binding.replicas"]["observed"] == "Independent pulls per ligand were reduced from 3 to 1."
    assert by_code["binding.max_windows"]["observed"] == "The limit on umbrella windows was reduced from 40 to 12."
    assert by_code["binding.refine_rounds"]["observed"] == "Automatic window refinement was changed from 6 rounds to 0 rounds."
    assert all(i["feature"] == "binding_full" for c, i in by_code.items() if c.startswith("binding."))
    for i in items:                                                         # the gain is the registry sentence of that feature
        assert i["gain"] == E.pro_feature(i["feature"]).gain[1] and i["kind"] == ES.KIND_LIMIT
    assert by_code["md.production_ns"]["evidence"] == {"source": "edition.hits", "code": "md.production_ns", "value": 100.0,
                                                         "limit": 10.0, "clamped": True, "from": 100.0, "to": 10.0}


def test_a_limit_that_was_not_reduced_reads_as_a_limit_reached(lite):
    st = {"edition": E.state_record(E.check_config({"ligands": [{}, {}, {}], "md": {"tier": "teaching"}}, E.LITE)
                                    + E.check_library(25, E.LITE) + E.check_system(n_atoms=41_250, solvent="explicit", edition=E.LITE)
                                    + E.check_config({"md": {"membrane": {"a": 1}}}, E.LITE))}
    items = {i["evidence"]["code"]: i for i in ES.gains(st, {}, {}, "en")}
    assert items["ligands.count"]["observed"] == "Limit reached: This workflow has 3 ligands. Lite takes up to 2 at a time."
    assert items["screen.compounds"]["observed"].endswith("The library has 25 compounds. Lite screens 10 in one run.")
    assert "41,250 atoms" in items["system.atoms"]["observed"] and "30,000" in items["system.atoms"]["observed"]
    assert items["system.atoms"]["feature"] == "large_system" and items["ligands.count"]["feature"] == "multi_ligand_full"
    assert items["feature.membrane"]["feature"] == "membrane" and "Membrane systems" in items["feature.membrane"]["observed"]
    assert not any(i["evidence"]["clamped"] for i in items.values())


def test_nothing_met_nothing_listed(lite):
    # a limit that was not met gives no item: only the hit that happened is listed
    cfg = {"md": {"tier": "teaching", "production_ns": 20.0}, "ligands": [{}]}
    st = {"edition": E.state_record(E.check_config(cfg, E.LITE))}
    items = ES.gains(st, cfg, {}, "en")
    assert [i["evidence"]["code"] for i in items] == ["md.production_ns"]
    assert not any(i["feature"] in ("replicas", "multi_ligand_full", "membrane") for i in items)
    assert ES.gains({"edition": E.state_record()}, {}, {}, "en") == []
    assert ES.gains({}, {}, {}, "en") == [] and ES.gains(None, None, None, "ko") == []


# ------------------------------------------------------------------------------------------- source b: MD repeats
def _md_runs(**n):
    return {"md_runs": {"status": "PASS", "runs": {k: {"run_ids": [f"r{i}" for i in range(v)]} for k, v in n.items()}}}


def test_one_md_repeat_per_system(lite):
    items = ES.gains(_state(**_md_runs(apo=1, docked_BEN=1)), {}, {}, "en")
    assert len(items) == 1 and items[0]["feature"] == "replicas"
    assert items[0]["observed"] == ("2 of 2 systems ran one MD repeat only (apo, docked_BEN), so their results are descriptive "
                                    "and show no spread between repeats.")
    assert items[0]["evidence"]["replicas"] == {"apo": 1, "docked_BEN": 1} and items[0]["evidence"]["single"] == ["apo", "docked_BEN"]
    one = ES.gains(_state(**_md_runs(apo=3, docked_BEN=1)), {}, {}, "en")
    assert "1 of 2 systems" in one[0]["observed"] and one[0]["evidence"]["single"] == ["docked_BEN"]
    assert ES.gains(_state(**_md_runs(apo=3, docked_BEN=3)), {}, {}, "en") == []
    assert ES.gains(_state(**_md_runs(apo=0)), {}, {}, "en") == []                 # nothing ran: nothing to say
    assert ES.gains(_state(), {}, {}, "en") == []


def test_the_single_replica_flag_of_the_replica_set_is_read_too(lite, tmp_path):
    agg = tmp_path / "agg.json"
    atomic_write_json({"schema": "md20.replica_set/1", "flags": ["single_replica"], "n_analysed": 1}, agg)
    st = _state(**_md_runs(apo=2, docked_BEN=3), analysis={"summaries": {"apo": {"replica_set_file": str(agg)}}})
    items = ES.gains(st, {}, {}, "en")
    assert items[0]["evidence"]["single"] == ["apo"] and items[0]["evidence"]["flags"] == {"apo": ["single_replica"]}


# ------------------------------------------------------------------------------------------- source c: binding assessment
def test_overlap_below_threshold_pull_count_and_withheld_dg(lite):
    r = _binding_result(dG_withheld="classroom")
    asm = ES.assessment_inputs({"BEN": r})
    items = ES.gains(_state(), {}, asm, "en")
    texts = {i["evidence"].get("diagnostic") or i["evidence"].get("dG_withheld") or "pulls": i for i in items}
    assert all(i["feature"] == "binding_full" for i in items)
    graph = texts["overlap_graph"]
    assert graph["observed"] == "The umbrella windows of ligand BEN are not connected by overlap at the 0.03 threshold."
    assert graph["evidence"]["threshold"] == 0.03 and graph["evidence"]["value"] is False
    assert texts["pulls"]["observed"] == "Ligand BEN was pulled once, so there is no spread between independent pulls."
    assert "ΔG° was not reported for ligand BEN" in texts["classroom"]["observed"]
    # stored assessment, claim not eligible, two required checks without a record
    unk = [i for i in items if i["evidence"].get("claim") == "path_specific"][0]
    assert unk["evidence"]["unknown"] == ["window_ess", "cumulative_drift"]
    assert unk["observed"] == ("2 sampling checks of ligand BEN could not be evaluated "
                               "(per-window effective samples, cumulative-estimate drift).")


def test_adjacent_overlap_value_is_reported_when_the_graph_is_fine(lite):
    pmf = {"coverage": {"continuous": True, "breaks": []}, "overlap_matrix": {"min_neighbour": 0.012, "matrix": [[1, 0.5], [0.5, 1]]},
           "quality": {"graph_connected": True}}
    r = _binding_result(assessment=assess_pmf(pmf), replicas=3)
    items = ES.gains(_state(), {}, ES.assessment_inputs({"BEN": r}), "en")
    adj = [i for i in items if i["evidence"].get("diagnostic") == "adjacent_overlap_min"][0]
    assert adj["observed"] == "The smallest overlap between neighbouring windows of ligand BEN is 0.012, below the 0.03 threshold."
    assert not any("pulled once" in i["observed"] for i in items)                    # three pulls: no single-pull item


def test_a_good_pmf_and_several_pulls_give_nothing(lite):
    good = {"coverage": {"continuous": True, "breaks": []}, "method": "mbar", "converged": True, "plateau": True,
            "half_split": {"diff_kj_mol": 0.5}, "overlap_matrix": {"min_neighbour": 0.4, "matrix": [[1, 0.4], [0.4, 1]]},
            "quality": {"graph_connected": True, "window_stats": [{"n_effective": 300}]},
            "convergence": {f"{f:.2f}": {"delta_pmf": 24.0} for f in (0.25, 0.5, 0.75, 1.0)}}
    r = _binding_result(assessment=assess_pmf(good), replicas=3)
    assert ES.gains(_state(), {}, ES.assessment_inputs({"BEN": r}), "en") == []


def test_a_result_written_before_the_assessment_is_not_blamed_on_lite(lite):
    """No stored assessment: every diagnostic is unknown because the result is old, not because of an edition limit."""
    r = _binding_result(replicas=3)
    r.pop("assessment")
    assert ES.gains(_state(), {}, ES.assessment_inputs({"BEN": r}), "en") == []


def test_a_pull_that_did_not_finish_is_skipped(lite):
    assert ES.assessment_inputs({"BEN": _binding_result(status="FAILED")}) == {}


def test_a_descriptive_comparison_is_not_an_upgrade_item(lite):
    """Shared-pocket pulls are condition-specific values in the complete edition too (D-96), so nothing is promised."""
    comp = {"contexts": {"multi:docked_multi": {"status": "DESCRIPTIVE", "values": [], "not_compared": []}}}
    assert ES.gains(_state(binding={"comparison": comp}), {}, {}, "en") == []


def test_a_comparison_with_too_few_qualified_ligands(lite):
    comp = {"contexts": {"single": {"status": "INSUFFICIENT", "keys": ["PGA"], "not_compared": [{"key": "BEN", "why": "x"}]},
                         "multi:a": {"status": "INSUFFICIENT", "keys": ["a", "b"], "not_compared": []},       # conditions differ
                         "multi:b": {"status": "INSUFFICIENT", "keys": [], "not_compared": []}}}              # nothing computed
    items = ES.gains(_state(binding={"comparison": comp}), {}, {}, "en")
    assert len(items) == 1 and items[0]["feature"] == "binding_full"
    assert items[0]["observed"] == ("Among the 2 computed ligands in the bound alone context, only 1 passed the sampling "
                                    "assessment, so they cannot be compared.")
    assert items[0]["evidence"]["passed"] == ["PGA"] and items[0]["evidence"]["computed"] == 2


# ------------------------------------------------------------------------------------------- source d and e
def test_implicit_solvent_is_a_note_not_an_upgrade_item(lite):
    items = ES.gains(_state(), {"md": {"solvent": "gbn2"}}, {}, "en")
    assert len(items) == 1 and items[0]["kind"] == ES.KIND_NOTE and items[0]["feature"] == "" and items[0]["gain"] == ""
    o = items[0]["observed"]
    assert "descriptive" in o and "cannot be compared directly with explicit-water or literature values" in o
    assert "Binding free energy needs explicit water, which Lite offers." in o
    assert ES.gains(_state(), {"md": {"solvent": "explicit"}}, {}, "en") == []
    # in implicit solvent the gate withholds ΔG°: that is not a reason to upgrade
    asm = ES.assessment_inputs({"BEN": _binding_result(dG_withheld="gbn2", replicas=3)})
    assert not [i for i in ES.gains(_state(), {"md": {"solvent": "gbn2"}}, asm, "en") if "ΔG° was not reported" in i["observed"]]


def _toolbox_state(tmp_path, **present) -> dict:
    e = {}
    if present.get("tica"):
        e["tica"] = {"status": "ok"}
    if present.get("net"):
        e["hbonds_protein"] = {"network": {"status": "ok"}}
    if present.get("hyd"):
        e["ligands"] = {"L01": {"hydration": {"status": "ok"}}}
    ext = tmp_path / "ext.json"
    atomic_write_json(e, ext)
    comp = {}
    if present.get("common"):
        cb = tmp_path / "cb.json"
        atomic_write_json({"comparable": True}, cb)
        comp["common_basis_file"] = str(cb)
    return _state(analysis={"summaries": {"apo": {"extended_file": str(ext)}}, "comparison": comp})


def test_toolbox_items_are_listed_once_and_only_when_missing(lite, tmp_path):
    items = ES.gains(_toolbox_state(tmp_path), {}, {}, "en")
    assert len(items) == 1 and items[0]["feature"] == "analysis_toolbox"
    assert items[0]["observed"] == ("These analyses of the complete edition were not run for this report (tICA and Markov state "
                                    "models, hydrogen-bond networks, hydration analysis, common principal-component comparison).")
    some = ES.gains(_toolbox_state(tmp_path, tica=True, net=True), {}, {}, "en")
    assert some[0]["evidence"]["missing"] == ["hydration", "common_basis"] and some[0]["evidence"]["present"] == ["tica", "hbond_network"]
    assert ES.gains(_toolbox_state(tmp_path, tica=True, net=True, hyd=True, common=True), {}, {}, "en") == []
    assert ES.gains(_state(analysis={"summaries": {}}), {}, {}, "en") == []          # no MD analysis: nothing was missed
    assert ES.gains(_state(), {}, {}, "en") == []


# ------------------------------------------------------------------------------------------- the four languages
def _rich_items(lang: str) -> list[dict]:
    cfg = {**_research_cfg(), "md": {**_research_cfg()["md"], "solvent": "gbn2"}}
    st = {"edition": _edition_state(cfg), **_state(**_md_runs(apo=1, docked_BEN=1),
                                                     analysis={"summaries": {"apo": {}}},
                                                     binding={"comparison": {"contexts": {"single": {
                                                         "status": "INSUFFICIENT", "keys": ["PGA"], "not_compared": [{"key": "BEN"}]}}}})}
    asm = ES.assessment_inputs({"BEN": _binding_result(dG_withheld="classroom")})
    st["edition"]["hits"] += [h.as_dict() for h in E.check_library(25, E.LITE)]
    return ES.gains(st, cfg, asm, lang)


def test_four_languages_distinct_and_complete(lite):
    per = {l: _rich_items(l) for l in LANG4}
    n = len(per["en"])
    assert n >= 12 and all(len(per[l]) == n for l in LANG4)
    for k in range(n):
        obs = [per[l][k]["observed"] for l in LANG4]
        gain = [per[l][k]["gain"] for l in LANG4]
        assert all(obs) and len(set(obs)) == 4, obs
        assert per["en"][k]["evidence"] == per["zh"][k]["evidence"] == per["ja"][k]["evidence"] == per["ko"][k]["evidence"]
        if per["en"][k]["kind"] == ES.KIND_LIMIT:
            assert all(gain) and len(set(gain)) == 4
    for l in LANG4:
        for it in per[l]:
            for field in ("observed", "gain"):
                assert not re.search(r"[{}]", it[field]), it[field]                   # no leftover placeholder
                assert "None" not in it[field] and "{" not in it[field]
    assert any("100 ns" in i["observed"] and "10 ns" in i["observed"] for i in per["zh"])
    assert any("100 ns" in i["observed"] and "10 ns" in i["observed"] for i in per["ko"])


def test_texts_follow_the_writing_rules(lite):
    """docs/specs/writing_style.md §1, the same regex as tests/test_edition.py::test_texts_follow_the_writing_rules."""
    texts = [t for tpl in ES.ALL_TEXTS for t in tpl]
    for l in LANG4:
        for it in _rich_items(l):
            texts += [it["observed"], it["gain"]]
        texts += [ES.section_html(_rich_items(l), l), ES.footer_mark(l)]
    for t in texts:
        assert not re.search(r"——|—|–|→|／| / ", re.sub(r"<[^>]+>", "", t)), t
    # every template is a four-tuple, and the Korean ones never put a particle directly after a variable
    for tpl in ES.ALL_TEXTS:
        assert len(tpl) == 4 and all(tpl)
        # ({lig} is "<name> 리간드" in Korean, a noun, so a particle after it is fine)
        assert not re.search(r"(?<!\{lig)\}(은|는|이|가|을|를|과|와|로|으로|에서|에|의|도|만)", tpl[3]), tpl[3]
    # no stacked parentheses
    for t in texts:
        assert not re.search(r"[（(][^）)]*[（(]", re.sub(r"<[^>]+>", "", t)), t


# ------------------------------------------------------------------------------------------- the page
def test_empty_list_renders_one_sentence_and_still_the_table():
    for l in LANG4:
        h = ES.section_html([], l)
        assert h.count(ES._T["none"][("zh", "en", "ja", "ko").index(l)]) == 1
        assert "<h3>" not in h and "<table>" in h and E.HOW_TO_UPGRADE[("zh", "en", "ja", "ko").index(l)] in h
        assert h.count("<table>") == 1
        for row in E.comparison_rows(l):
            assert row["item"] in h


def test_items_of_one_feature_share_one_gain_sentence(lite):
    cfg = _research_cfg()
    items = ES.gains({"edition": _edition_state(cfg)}, cfg, ES.assessment_inputs({"BEN": _binding_result()}), "en")
    h = ES.section_html(items, "en")
    assert h.count(E.pro_feature("binding_full").gain[1]) == 1 and h.count("<h3>Full binding free energy</h3>") == 1
    assert h.count(E.pro_feature("long_run").gain[1]) == 1
    assert h.count("<li class=note>") == len(items)


def test_notes_come_after_the_features(lite):
    items = ES.gains(_state(**_md_runs(apo=1)), {"md": {"solvent": "gbn2"}}, {}, "en")
    h = ES.section_html(items, "en")
    assert h.index("Independent repeats and uncertainty") < h.index("Implicit-solvent preview")


def test_edition_of_the_run(monkeypatch):
    assert ES.report_edition({"edition": {"edition": "lite"}}) == E.LITE
    assert ES.report_edition({"edition": {"edition": "full"}}) == E.FULL
    assert ES.report_edition({"steps": {"edition": {"edition": "lite", "hits": []}}}) == E.LITE
    monkeypatch.setattr(E, "current", lambda **kw: E.LITE)
    assert ES.report_edition({}) == E.LITE and ES.report_edition({"edition": {"edition": "bogus"}}) == E.LITE
    assert ES.report_edition({"edition": {"edition": "full"}}) == E.FULL            # the state wins over the running edition


# ------------------------------------------------------------------------------------------- the whole report
def _normalise(html: str) -> str:
    """Drop what differs between two builds of the same input: image metadata, wall-clock times, the provenance stamp."""
    html = re.sub(r"data:image/[a-z+]+;base64,[A-Za-z0-9+/=]+", "IMG", html)
    html = re.sub(r"<!-- HCCLab-MD20 [^>]*-->", "STAMP", html)
    html = re.sub(r"[\u200b\u200c\u2060]+", "ZW", html)
    return re.sub(r"\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d", "TS", html)


def _strip_lite_additions(html: str) -> str:
    html = re.sub(r"<section id=edition-appendix>.*?</section>", "", html, flags=re.S)
    return re.sub(r"<p class=meta data-md20-edition=lite>.*?</p>", "", html, flags=re.S)


def _lite_run(wf, *, repeats: int = 1) -> None:
    """The run of the spec example: one MD repeat per system and a quick PMF with a stored assessment."""
    st = wf.state()
    st["steps"]["md_runs"] = {"status": "PASS", "runs": {k: {"run_ids": [f"{k}_r{i}" for i in range(repeats)]} for k in ("apo", "docked_BEN")}}
    st["steps"]["binding"]["results"]["BEN"].update(_binding_result(dG_withheld="classroom", figures=st["steps"]["binding"]["results"]["BEN"]["figures"]))
    cfg = _research_cfg()
    st["edition"] = _edition_state(cfg)
    atomic_write_json(st, wf.state_path)


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_lite_report_has_the_section_the_table_and_the_mark_once(tmp_path, lite, lang):
    wf = _v2.make_wf(tmp_path, lang)
    _lite_run(wf)
    html = WR.build_workflow_report(wf).read_text(encoding="utf-8")
    assert html.count(f"<section id={ES.SECTION_ID}>") == 1 and html.count("</section>") == 1
    assert html.count(f"{ES.FOOTER_ATTR}=lite") == 1
    i = LANG4.index(lang)
    assert html.count(ES._T["title"][i]) == 1 and html.count(ES._T["table_caption"][i]) == 1
    sec = re.search(r"<section id=edition-appendix>.*?</section>", html, flags=re.S).group(0)
    assert sec.count("<table>") == 1 and sec.count(E.HOW_TO_UPGRADE[i]) == 1
    for row in E.comparison_rows(lang):
        assert row["item"] in sec
    # the appendix is the last thing before the stamp footer, after every existing appendix
    assert html.index("config.json") < html.index(ES.SECTION_ID) < html.index(f"{ES.FOOTER_ATTR}=lite") < html.index("<footer")
    # it carries this run's numbers
    if lang == "en":
        assert "The production run was shortened from 100 ns to 10 ns." in sec
        assert "1 of 1" not in sec and "2 of 2 systems ran one MD repeat only (apo, docked_BEN)" in sec
        assert "not connected by overlap at the 0.03 threshold" in sec and "was pulled once" in sec
    else:
        assert "正式模擬從 100 ns 縮短為 10 ns。" in sec and "2 個系統中有 2 個只跑了 1 次 MD 重複（apo、docked_BEN）" in sec
        assert "在 0.03 的重疊門檻下沒有連成一串" in sec and "只拉離了 1 次" in sec


def test_lite_report_only_adds_to_the_complete_one(tmp_path, monkeypatch):
    """Same input, both editions: apart from the appendix and the mark, the Lite page is the complete page, word for word.
    Each page is built once from its own copy of the workflow, because a build appends to the decision log."""
    pages = {}
    for ed in ("full", "lite"):
        wf = _v2.make_wf(tmp_path / ed, "en")
        _lite_run(wf)
        st = wf.state()
        st["edition"]["edition"] = ed                                                    # the edition of the run is in the state
        atomic_write_json(st, wf.state_path)
        pages[ed] = _normalise(WR.build_workflow_report(wf, tmp_path / f"{ed}.html").read_text(encoding="utf-8"))
    full, lite_html = pages["full"], pages["lite"]
    assert ES.SECTION_ID not in full and ES.FOOTER_ATTR not in full and "Appendix D" not in full
    assert ES.SECTION_ID in lite_html and "Appendix D" in lite_html
    assert _strip_lite_additions(lite_html) == full


def test_complete_edition_calls_nothing_of_the_lite_part(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the complete edition must not touch the Lite section")
    for fn in ("appendix_html", "footer_mark", "gains", "section_html", "assessment_inputs"):
        monkeypatch.setattr(ES, fn, boom)
    monkeypatch.setattr(ES, "is_lite_report", lambda st: False)
    wf = _v2.make_wf(tmp_path, "en")
    html = WR.build_workflow_report(wf).read_text(encoding="utf-8")
    assert "Appendix C" in html and ES.SECTION_ID not in html and ES.FOOTER_ATTR not in html and "Appendix D" not in html


def test_a_lite_report_without_any_observed_limit_says_so(tmp_path, lite):
    wf = _v2.make_wf(tmp_path, "en")
    st = wf.state()
    st["edition"] = E.state_record()
    st["steps"]["binding"]["results"]["BEN"].update(replicas=3, dG_withheld=None)
    atomic_write_json(st, wf.state_path)
    html = WR.build_workflow_report(wf).read_text(encoding="utf-8")
    sec = re.search(r"<section id=edition-appendix>.*?</section>", html, flags=re.S).group(0)
    assert sec.count("This run met no Lite limit.") == 1 and "<li class=note>" not in sec
    assert html.count(f"{ES.FOOTER_ATTR}=lite") == 1 and sec.count("<table>") == 1


def test_run_report_gets_only_the_mark(tmp_path, monkeypatch):
    from md20.project import Project
    from md20.engine import make_protocol, run_protocol, FakeBackend
    from md20.report import build_run_report
    p = Project.create(tmp_path, "rep")
    c = p.new_case("c")
    proto = make_protocol("classroom")
    for s in proto.stages:
        if s.ensemble != "MIN":
            s.length_ps = 10.0; s.checkpoint_interval_ps = 5.0; s.report_interval_ps = 0.2
    r = c.new_run(proto.to_dict())
    run_protocol(r.dir, proto, lambda spec, dt: FakeBackend(timestep_fs=dt, temperature_k=spec.temperature_k, ensemble=spec.ensemble),
                 identity={"case_id": c.case_id, "run_id": r.run_id}, decisions=p.decisions, batch_steps=250)
    full = build_run_report(r, tmp_path / "full.html").read_text(encoding="utf-8")
    assert ES.FOOTER_ATTR not in full
    monkeypatch.setattr(E, "current", lambda **kw: E.LITE)
    lt = build_run_report(r, tmp_path / "lite.html", lang="zh").read_text(encoding="utf-8")
    assert lt.count(f"{ES.FOOTER_ATTR}=lite") == 1 and "由 MD20 Lite 產生" in lt and ES.SECTION_ID not in lt


def test_the_footer_mark_is_short_and_in_four_languages():
    marks = [ES.footer_mark(l) for l in LANG4]
    assert len(set(marks)) == 4 and all("MD20 Lite" in m and m.count(ES.FOOTER_ATTR) == 1 for m in marks)
    assert all(len(re.sub(r"<[^>]+>", "", m)) < 30 for m in marks)


# ------------------------------------------------------------------------------------------- the report template
def test_report_template_lite_variant(tmp_path):
    rt = _load("tools/report_template.py", "report_template_lite")
    assert rt.main(tmp_path, lite=True) == 0
    for lang in ("en", "zh"):
        html = (tmp_path / f"MD20_report_template_lite_{lang}.html").read_text(encoding="utf-8")
        assert html.count(f"<section id={ES.SECTION_ID}>") == 1 and html.count(f"{ES.FOOTER_ATTR}=lite") == 1
        assert "synthetic demo data" in html or "合成示範資料" in html
        assert not (tmp_path / f"MD20_report_template_{lang}.html").exists()           # the default output is a separate file
    assert E.current() == E.FULL                                                       # the variant never switched the edition
