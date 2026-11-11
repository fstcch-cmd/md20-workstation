"""D-181: what MD20 Lite looks like in the interface.  Pure logic (md20/gui/edition_ui.py); no NiceGUI, no engine.

Lite is simulated by patching `md20.edition.current` (and `build_edition`, `licence_features`), never through the
environment: no variable, setting or flag can change the edition."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from md20 import edition as E
from md20.gui import edition_ui as U
from md20.i18n import LANGS, pick

ROOT = Path(__file__).resolve().parents[1]
LANG4 = ("zh", "en", "ja", "ko")
RULE = re.compile(r"——|—|–|→|／| / ")          # tests/test_edition.py::test_texts_follow_the_writing_rules
KO_PARTICLE = re.compile(r"\}[가-힣]")          # Korean: no particle directly after a variable


@pytest.fixture
def lite(monkeypatch):
    monkeypatch.setattr(E, "current", lambda **kw: E.LITE)
    monkeypatch.setattr(E, "build_edition", lambda marker=None: E.LITE)
    monkeypatch.setattr(E, "licence_features", lambda: ["lite", "binding", "hts"])
    return E.LITE


def _cfg(**md) -> dict:
    return {"name": "x", "receptor": {"pdb_id": "3PTB"}, "ligands": [{"name": "BEN", "smiles": "NC(=[NH2+])c1ccccc1"}],
            "md": {"systems": ["apo", "docked_single"], "tier": "teaching", **md},
            "binding": {"enabled": False, "ligands": [], "config": {}}}


def _all_texts(lang_tuples) -> list[str]:
    out = []
    for x in lang_tuples:
        out += list(x) if isinstance(x, tuple) else [x]
    return out


# ------------------------------------------------------------------------------------------- the complete edition
def test_the_source_tree_is_the_complete_edition_and_every_function_is_empty():
    assert E.current() == E.FULL
    for lang in LANG4:
        assert U.badge(lang) is None and U.badge_hint(lang) is None and U.tag(lang) is None
        assert U.locked_features(lang) == [] and U.field_limits(lang) == {} and U.editions_page(lang) == {}
        assert U.advanced_issues({"membrane_type": "bilayer", "resolution": "cg", "fold": "dock"}, [{"sequence": "AAAAAAAAAA"}], lang) == []
        for fid in ("membrane", "fold", "cg"):
            assert U.preview_page(fid, lang) is None
        assert U.gbn2_preview_offer({"platform": {"name": "CUDA"}}, lang)["show"] is False
        assert U.validate_setting("production_ns", 1000, lang) is None and U.validate_setting("ligands", 9, lang) is None
        big = _cfg(tier="research", replicas=5, production_ns=1000.0, membrane={"lipids": "POPC"})
        big["ligands"] = [{"name": f"L{i}", "smiles": "C"} for i in range(8)]
        assert U.config_hits(big, lang, "/p") == {}
    assert U.css() == "" and U.form_binding_defaults() == {} and not U.is_lite()


# ------------------------------------------------------------------------------------------- badge, list, page
def test_badge_and_locked_features(lite):
    assert U.badge("en") == "Lite" and U.badge("zh") == "Lite 版" and all(U.badge_hint(l) and U.tag(l) for l in LANG4)
    for lang in LANG4:
        rows = U.locked_features(lang)
        assert [r["id"] for r in rows] == [f.id for f in E.PRO_FEATURES] == [r["id"] for r in E.summary(lang)["locked"]]
        for r, f in zip(rows, E.PRO_FEATURES):
            assert r["href"] == (f"/edition/{f.id}" if f.preview else None) and r["tag"] == U.tag(lang)
            assert r["title"] and r["gain"]
    assert U.css().startswith("<style>") and "md20-edbadge" in U.css()


def test_editions_page_has_the_comparison_the_features_and_the_upgrade_line(lite):
    seen = set()
    for lang in LANG4:
        page = U.editions_page(lang)
        assert page["rows"] == E.comparison_rows(lang) and page["upgrade"] == E.summary(lang)["how_to_upgrade"]
        assert [c["name"] for c in page["columns"]] == ["item", "lite", "full"]
        assert len(page["features"]) == len(E.PRO_FEATURES)
        for key in ("title", "intro", "features_title", "features_intro", "about_label", "upgrade_title", "back"):
            assert page[key]
        seen.add(page["intro"])
    assert len(seen) == 4
    # no prices, no links, no contact details beyond the one string the registry holds
    for lang in LANG4:
        flat = json.dumps(U.editions_page(lang), ensure_ascii=False)
        assert not re.search(r"https?://|@|\$|USD|NT\$|price|價格|価格|가격", flat)


# ------------------------------------------------------------------------------------------- field limits
def test_field_limits_equal_the_lite_limits(lite):
    L = E.LIMITS[E.LITE]
    fl = U.field_limits("en")
    assert fl["production_ns"]["limit"] == L.max_production_ns
    assert fl["tier"]["limit"] == list(L.md_tiers)
    assert fl["replicas"]["limit"] == L.max_replicas
    assert fl["ligands"]["limit"] == L.max_ligands
    assert fl["library"]["limit"] == L.max_screen_compounds
    assert fl["max_windows"]["limit"] == L.max_windows
    assert fl["window_prod_ps"]["limit"] == L.max_window_ps
    assert fl["max_refine_rounds"]["limit"] == L.max_refine_rounds
    assert fl["binding_replicas"]["limit"] == L.max_binding_replicas
    assert fl["binding"]["limit"] == {"max_windows": L.max_windows, "window_prod_ps": L.max_window_ps,
                                      "binding_replicas": L.max_binding_replicas, "max_refine_rounds": L.max_refine_rounds}
    # the keys the forms use are real field ids of the forms
    from md20.advisor import PARAMS
    for k in ("production_ns", "tier", "replicas", "window_prod_ps", "binding"):
        assert k in PARAMS
    # the numbers in the helper text are the limits
    assert "10 ns" in fl["production_ns"]["help"] and "500 ps" in fl["window_prod_ps"]["help"]
    assert "12 windows" in fl["max_windows"]["help"] and "2 ligands" in fl["ligands"]["help"] and "10 compounds" in fl["library"]["help"]


def test_field_limit_texts_read_in_four_languages_with_no_placeholder(lite):
    by_key: dict[str, set] = {}
    for lang in LANG4:
        for k, v in U.field_limits(lang).items():
            assert v["help"] and "{" not in v["help"] and "}" not in v["help"], (k, lang)
            assert not RULE.search(v["help"]), v["help"]
            by_key.setdefault(k, set()).add(v["help"])
    assert all(len(v) == 4 for v in by_key.values()), {k: len(v) for k, v in by_key.items() if len(v) != 4}


@pytest.mark.parametrize("key, ok, over", [
    ("production_ns", 10, 10.5), ("production_ns", 2, 100), ("tier", "classroom", "research"), ("tier", "teaching", "research"),
    ("replicas", 1, 3), ("ligands", 2, 3), ("ligands", [{}, {}], [{}, {}, {}]), ("library", 10, 11),
    ("max_windows", 12, 13), ("window_prod_ps", 500, 501), ("max_refine_rounds", 0, 1), ("binding_replicas", 1, 2)])
def test_validate_setting_is_none_within_lite_and_a_message_beyond_it(lite, key, ok, over):
    for lang in LANG4:
        assert U.validate_setting(key, ok, lang) is None
        msg = U.validate_setting(key, over, lang)
        assert msg and "{" not in msg and not RULE.search(msg), (key, lang, msg)


def test_validate_setting_wording_comes_from_edition_hits(lite):
    for lang in LANG4:
        assert U.validate_setting("production_ns", 50, lang) == E.Hit("md.production_ns", E.SCALE, 50.0, 10.0, "long_run", True).text(lang)
        assert U.validate_setting("ligands", 3, lang) == E.Hit("ligands.count", E.SCALE, 3, 2, "multi_ligand_full").text(lang)
        assert U.validate_setting("library", 11, lang) == E.check_library(11)[0].text(lang)
    assert len({U.validate_setting("replicas", 3, l) for l in LANG4}) == 4
    for bad in (None, "", "abc", [None]):
        assert U.validate_setting("production_ns", bad, "en") is None
    assert U.validate_setting("no_such_field", 5, "en") is None


def test_advanced_issues_name_the_features_the_form_switched_on(lite):
    adv = {"membrane_type": "none", "lipids": "mammalian", "oriented": False, "surface_distance_nm": 1.0, "fold": "off",
           "fold_engine": "auto", "fold_receptor_seq": "", "fold_upload": "", "long_run_confirmed": False, "resolution": "aa"}
    pep = [{"name": "PEP", "sequence": "KLAKLAKKLAKLAK"}]
    assert U.advanced_issues(adv, pep, "en") == []
    got = U.advanced_issues({**adv, "membrane_type": "surface", "resolution": "cg", "fold": "dock"}, pep, "en")
    assert sorted(i["key"] for i in got) == ["feature.cg", "feature.fold", "feature.membrane"]
    assert all(i["level"] == "warning" and i["label"] == "MD20 Lite" and i["suggestion"] is None for i in got)
    assert U.advanced_issues({**adv, "fold": "dock"}, [{"name": "LIG", "smiles": "CCO"}], "en") == []      # no peptide, no folding
    assert len({U.advanced_issues({**adv, "membrane_type": "bilayer"}, [], l)[0]["message"] for l in LANG4}) == 4


def test_lite_value_starts_a_field_at_the_limit_only_when_the_recommendation_is_above_it(lite):
    L = E.LIMITS[E.LITE]
    assert U.lite_value("tier", "research") == "teaching" and U.lite_value("tier", "classroom") == "classroom"
    assert U.lite_value("production_ns", 100.0) == L.max_production_ns and U.lite_value("production_ns", 2.0) == 2.0
    assert U.lite_value("production_ns", L.max_production_ns) == L.max_production_ns
    assert U.lite_value("replicas", 3) == L.max_replicas and U.lite_value("replicas", 1) == 1
    assert U.lite_value("window_prod_ps", 2000.0) == L.max_window_ps and U.lite_value("window_prod_ps", 50.0) == 50.0
    for other in ("docking_mode", "solvent", "padding_nm", "binding"):
        assert U.lite_value(other, "x") == "x"
    assert U.lite_value("replicas", None) is None and U.lite_value("replicas", "abc") == "abc"
    # whatever it returns passes the entrance check and the field's own message
    for key, v in (("tier", "research"), ("production_ns", 100.0), ("replicas", 3), ("window_prod_ps", 2000.0)):
        assert U.validate_setting(key, U.lite_value(key, v), "en") is None


def test_lite_value_changes_nothing_in_the_complete_edition():
    assert U.lite_value("tier", "research") == "research" and U.lite_value("replicas", 3) == 3
    assert U.lite_value("production_ns", 1000.0) == 1000.0 and U.lite_value("window_prod_ps", 2000.0) == 2000.0


def test_form_binding_defaults_are_the_lite_limits(lite):
    L = E.LIMITS[E.LITE]
    assert U.form_binding_defaults() == {"max_windows": L.max_windows, "max_refine_rounds": L.max_refine_rounds}
    # a binding config with these written in passes the entrance check on the binding sizes
    c = _cfg(); c["binding"] = {"enabled": True, "config": U.form_binding_defaults()}
    assert E.check_config(c) == []


# ------------------------------------------------------------------------------------------- the limit card
def test_a_plain_config_has_no_hits_in_lite(lite):
    assert U.config_hits(_cfg(), "en", "/p") == {} and U.config_hits({}, "en") == {} and U.config_hits(None, "en") == {}


def test_hits_that_can_be_reduced_offer_the_reduction(lite):
    cfg = _cfg(replicas=3, production_ns=50)
    for lang in LANG4:
        res = U.config_hits(cfg, lang, "/projects/P")
        assert [h["code"] for h in res["hits"]] == ["md.production_ns", "md.replicas"]
        assert all(h["can_clamp"] and h["state"] == "autofix" for h in res["hits"]) and res["clearable"] and not res["partial"]
        assert [c["id"] for c in res["choices"]] == ["clamp", "edit", "open_full", "learn"]
        clamp = res["choices"][0]
        assert clamp["primary"] and clamp["decision"] == {"edition": {"accept_clamp": True}}
        assert (E.ACCEPT_KEY[0], E.ACCEPT_KEY[1]) == ("edition", "accept_clamp")
        assert len(res["changes"]) == 2 and all("{" not in c for c in res["changes"])
        assert res["upgrade"] == pick(E.HOW_TO_UPGRADE, lang)
        o = next(c for c in res["choices"] if c["id"] == "open_full")
        assert o["folder"] == "/projects/P" and "/projects/P" in o["text"]
        assert next(c for c in res["choices"] if c["id"] == "learn")["href"] == "/edition"
    zh = U.config_hits(cfg, "zh")["changes"]
    assert any("10 ns" in c for c in zh) and any("1" in c for c in zh)


def test_hits_that_need_a_decision_withhold_the_reduction(lite):
    c = _cfg(membrane={"lipids": "POPC"})
    c["ligands"] = [{"name": f"L{i}", "smiles": "C"} for i in range(3)]
    res = U.config_hits(c, "en")
    assert sorted(h["code"] for h in res["hits"]) == ["feature.membrane", "ligands.count"]
    assert all(h["state"] == "needs" and not h["can_clamp"] for h in res["hits"])
    assert [x["id"] for x in res["choices"]] == ["edit", "open_full", "learn"] and res["choices"][0]["primary"]
    assert res["clearable"] is False and res["partial"]
    # a mix: the sizes could be reduced, but something is left, so reducing alone is not offered
    c2 = copy.deepcopy(c); c2["md"]["replicas"] = 3
    r2 = U.config_hits(c2, "en")
    assert not r2["clearable"] and r2["partial"] and "clamp" not in [x["id"] for x in r2["choices"]]
    assert {h["state"] for h in r2["hits"]} == {"autofix", "needs"}
    assert r2["changes"] == []
    # nothing is ever dropped or edited in the config by looking at the hits
    assert c2["md"]["replicas"] == 3 and len(c2["ligands"]) == 3 and "edition" not in c2


def test_an_accepted_reduction_leaves_only_what_a_reduction_cannot_clear(lite):
    c = _cfg(replicas=3, production_ns=50)
    c["edition"] = {"accept_clamp": True}
    assert U.config_hits(c, "en") == {}                                   # the workflow will apply the reduction
    c["ligands"] = [{"name": f"L{i}", "smiles": "C"} for i in range(3)]
    res = U.config_hits(c, "en")
    assert [h["code"] for h in res["hits"]] == ["ligands.count"]
    assert [x["id"] for x in res["choices"]] == ["edit", "open_full", "learn"]


def test_hit_texts_in_four_languages_are_distinct_without_placeholders(lite):
    c = _cfg(tier="research", replicas=3, production_ns=200, membrane={"x": 1}, resolution="cg")
    c["ligands"] = [{"name": f"L{i}", "smiles": "C", "fold": True} for i in range(3)]
    c["binding"] = {"enabled": True, "target_replicas": 4, "config": {"window_prod_ps": 9999.0}}
    per = {code: set() for code in ("md.tier", "md.replicas", "ligands.count", "feature.membrane", "feature.cg", "feature.fold",
                                    "binding.max_windows", "binding.window_ps")}
    for lang in LANG4:
        res = U.config_hits(c, lang, "/p")
        for h in res["hits"]:
            assert "{" not in h["text"] and "}" not in h["text"] and h["tag"], h
            if h["code"] in per:
                per[h["code"]].add(h["text"])
        for ch in res["choices"]:
            assert ch["label"] and "{" not in ch["label"] + ch["text"]
        assert res["title"] and res["sub"] and res["changes_title"]
    assert all(len(v) == 4 for v in per.values()), {k: len(v) for k, v in per.items()}


def test_accept_clamp_writes_the_decision_key_and_logs_it(lite, tmp_path):
    from md20.gui.logic import config_from_form
    from md20.project import Project
    from md20.util import load_json
    from md20.workflow import Workflow
    cfg = config_from_form(name="w", pdb_id="1abc", ligands_text="BEN C")
    cfg["md"]["replicas"] = 3
    wf = Workflow(Project.create(tmp_path, "p"), cfg)
    before = copy.deepcopy(load_json(wf.dir / "config.json", {}))
    assert U.config_hits(before, "en")["clearable"]
    out = U.accept_clamp(wf, note="classroom")
    after = load_json(wf.dir / "config.json", {})
    assert E.accepted(after) and E.accepted(wf.cfg) and after["edition"] == {"accept_clamp": True}
    after_wo = {k: v for k, v in after.items() if k != "edition"}
    assert after_wo == {k: v for k, v in before.items() if k != "edition"}, "only the decision key is added"
    assert U.config_hits(after, "en") == {}
    assert [c["key"] for c in out["planned"]] == [c["key"] for c in E.clamp_config(before)[1]]
    rows = [r for r in wf.dec.read() if r["stage"] == "gui.edition"]
    assert len(rows) == 1 and rows[0]["kind"] == "human" and rows[0]["choice"] is True
    assert "edition.accept_clamp" in rows[0]["what"] + rows[0]["why"] and "classroom" in rows[0]["why"]
    assert re.search(r"[\u4e00-\u9fff]", rows[0]["why"]), "the DecisionLog reason stays in Traditional Chinese"
    U.accept_clamp(wf)                                                      # twice: still one key
    assert load_json(wf.dir / "config.json", {})["edition"] == {"accept_clamp": True}


def test_copy_js_quotes_the_path():
    assert U.copy_js('C:\\a"b') == 'navigator.clipboard.writeText("C:\\\\a\\"b")'


# ------------------------------------------------------------------------------------------- description pages
def test_preview_pages_exist_for_exactly_the_preview_features(lite):
    ids = {f.id for f in E.PRO_FEATURES if f.preview}
    assert ids == {"membrane", "fold"} and set(U.PREVIEW) == ids
    for f in E.PRO_FEATURES:
        for lang in LANG4:
            page = U.preview_page(f.id, lang)
            assert (page is not None) == f.preview, f.id
    assert U.preview_page("no_such_feature", "en") is None


def test_preview_pages_are_text_in_four_languages(lite):
    for fid in U.PREVIEW:
        seen = {k: set() for k in ("title", "what", "limits")}
        for lang in LANG4:
            p = U.preview_page(fid, lang)
            assert p["id"] == fid and p["title"] == E.pro_feature(fid).title[LANG4.index(lang)] and p["tag"] == U.tag(lang)
            assert p["what"] and p["provide"] and p["get"] and p["limits"]
            assert p["upgrade"] == pick(E.HOW_TO_UPGRADE, lang)
            n = len([s for s in re.split(r"[。.]", p["what"]) if s.strip()])
            assert 2 <= n <= 4, (fid, lang, n)                                 # "two to four plain sentences"
            assert p["figure"] == fid and set(p["labels"]) >= {"what", "provide", "get", "back"}
            assert not re.search(r"\.(png|jpg|svg)|<img|https?://", json.dumps(p)), "text only: no fabricated image"
            for k in seen:
                seen[k].add(p[k])
        assert all(len(v) == 4 for v in seen.values()), fid
    # the temperature quoted in the text is the membrane module's default
    from md20.build import membrane
    assert "310 K" in U.preview_page("membrane", "en")["what"]
    assert {membrane.PRESETS[k]["temperature_k"] for k in ("mammalian", "bacterial")} == {310.0}


def test_the_example_figure_slot_is_named_and_not_filled():
    static = ROOT / "md20" / "gui" / "static" / "edition"
    assert not static.exists() or not any(static.iterdir()), "no result image is shipped before a real figure exists"


# ------------------------------------------------------------------------------------------- implicit-solvent preview
class _Choice:
    def __init__(self, name, is_gpu):
        self.name, self.is_gpu = name, is_gpu


@pytest.mark.parametrize("info", ["CUDA", "OpenCL", "HIP", {"name": "CUDA"}, {"platform": {"name": "OpenCL"}},
                                  {"is_gpu": True}, _Choice("CUDA", True), _Choice("OpenCL", None)])
def test_the_quick_preview_is_offered_on_a_gpu_platform(lite, info):
    for lang in LANG4:
        o = U.gbn2_preview_offer(info, lang)
        assert o["show"] is True and o["label"] and o["caption"]


@pytest.mark.parametrize("info", [None, "", "CPU", "Reference", {"name": "CPU"}, {"platform": None}, {"platform": {"name": "CPU"}},
                                  {"is_gpu": False}, _Choice("CPU", False), {}, 3])
def test_the_quick_preview_is_not_offered_without_a_gpu(lite, info):
    assert U.gbn2_preview_offer(info, "en") == {"show": False, "label": "", "caption": ""}


def test_the_quick_preview_caption_says_what_it_is(lite):
    caps = {l: U.gbn2_preview_offer("CUDA", l)["caption"] for l in LANG4}
    assert len(set(caps.values())) == 4 and "descriptive" in caps["en"] and "explicit water" in caps["en"]
    assert "binding free energy" in caps["en"].lower()
    assert not any(RULE.search(c) for c in caps.values())


# ------------------------------------------------------------------------------------------- the writing rules
def _every_text(lite_on: bool):
    texts = _all_texts(U.TEXT.values())
    texts += _all_texts(U._HELP.values()) + list(U._HELP_REFINE_NONE) + list(U._HELP_REFINE_SOME) + [U._HELP_BINDING_PLURAL_EN]
    for p in U.PREVIEW.values():
        texts += list(p["what"]) + list(p["limits"]) + [t for item in p["provide"] + p["get"] for t in item]
    texts += [t for spec in U._CHANGE_LABELS.values() if len(spec) == 4 for t in spec]
    return texts


def test_texts_follow_the_writing_rules(lite):
    texts = _every_text(True)
    for lang in LANG4:
        for page in (U.editions_page(lang), U.preview_page("membrane", lang), U.preview_page("fold", lang),
                     U.config_hits(_cfg(replicas=3, production_ns=50, membrane={"a": 1}), lang, "/p")):
            texts += [t for t in _walk_strings(page)]
    for t in texts:
        assert not RULE.search(t), t
        assert not re.search(r"值得注意|需要注意的是|總而言之|此外|旨在|確保|關鍵在於|It's worth noting|crucial|ensure|seamless|robust|leverage|delve|In summary", t), t
    for t in _every_text(True):
        assert not KO_PARTICLE.search(t), t
    # Japanese in desu and masu, never the plain written style of the report's method section
    for t in (U.TEXT["ed_intro"][2], U.PREVIEW["fold"]["what"][2], U.PREVIEW["membrane"]["what"][2]):
        assert not re.search(r"である。|だ。", t), t


def _walk_strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from _walk_strings(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from _walk_strings(v)


def test_every_tuple_has_four_languages():
    for k, v in U.TEXT.items():
        assert isinstance(v, tuple) and len(v) == 4 and all(v), k
    for k, v in U._HELP.items():
        assert len(v) == 4 and all(v), k
    for fid, p in U.PREVIEW.items():
        for key in ("what", "limits"):
            assert len(p[key]) == 4 and all(p[key])
        for item in p["provide"] + p["get"]:
            assert len(item) == 4 and all(item)
    for k, v in U._CHANGE_LABELS.items():
        assert len(v) in (1, 4), k
    # the helper texts' placeholders are exactly {n}
    for k, v in list(U._HELP.items()) + [("refine", U._HELP_REFINE_SOME)]:
        for t in v:
            assert re.findall(r"\{(\w+)\}", t) == ["n"], (k, t)


def test_the_module_decides_nothing_about_the_edition_by_itself():
    src = (ROOT / "md20" / "gui" / "edition_ui.py").read_text(encoding="utf-8")
    code = re.sub(r'""".*?"""', "", src, flags=re.S)
    code = "\n".join(l for l in code.splitlines() if not l.lstrip().startswith("#"))
    assert not re.search(r"\benviron\b|getenv|\bargv\b|== *['\"]lite['\"]|is_lite *=|LIMITS *\[", code), "ask md20.edition"
    # none of the Lite limit numbers is written here as a literal
    lim = E.LIMITS[E.LITE]
    for n in (lim.max_atoms, lim.max_atoms_implicit, lim.max_protein_residues, 30000, 6000, 400):
        assert not re.search(rf"\b{n}\b", code), n


def test_the_pages_are_wired_without_a_lite_branch_in_the_complete_edition():
    """The complete edition's pages are built by the same code; every addition asks edition_ui and gets nothing."""
    app = (ROOT / "md20" / "gui" / "app.py").read_text(encoding="utf-8")
    pages = (ROOT / "md20" / "gui" / "pages_v2.py").read_text(encoding="utf-8")
    for src in (app, pages):
        assert "edition_ui" in src
        assert not re.search(r"current\(\) *==|\"lite\"|'lite'", src), "the interface asks edition_ui, never the edition directly"
    assert "/edition" in pages and "edition-card" in app and "edition-badge" in app
