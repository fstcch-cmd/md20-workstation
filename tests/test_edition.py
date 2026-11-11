"""D-181: editions (complete, Lite).  Pure logic: no engine, no licence file, no network."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from md20 import edition as E
from md20.i18n import LANGS

ROOT = Path(__file__).resolve().parents[1]
LANG4 = ("zh", "en", "ja", "ko")


def _cfg(**md) -> dict:
    return {"name": "x", "receptor": {"pdb_id": "3PTB"}, "ligands": [{"name": "BEN", "smiles": "NC(=[NH2+])c1ccccc1"}],
            "md": {"systems": ["apo", "docked_single"], "tier": "teaching", **md},
            "binding": {"enabled": False, "ligands": [], "config": {}}}


# ------------------------------------------------------------------------------------------- which edition
def test_source_tree_is_the_complete_edition():
    assert not (ROOT / "md20" / E.MARKER_NAME).exists(), "the Lite marker must never be committed"
    assert E.build_edition() == E.FULL


def test_marker_makes_the_package_lite(tmp_path):
    m = tmp_path / E.MARKER_NAME
    assert E.build_edition(m) == E.FULL                      # no file
    m.write_text(json.dumps(E.marker_document("0.1.0")), encoding="utf-8")
    assert E.build_edition(m) == E.LITE
    assert E.current(features=None, marker=m) == E.LITE      # a licence with every feature does not lift a Lite package


@pytest.mark.parametrize("content", ["", "not json", "[]", '{"edition": "full"}', '{"schema": "x", "edition": "full"}'])
def test_damaged_or_edited_marker_is_still_lite(tmp_path, content):
    m = tmp_path / E.MARKER_NAME
    m.write_text(content, encoding="utf-8")
    assert E.build_edition(m) == E.LITE


def test_the_lite_word_in_licence_features_selects_lite_on_a_complete_package(tmp_path):
    missing = tmp_path / "none.json"
    assert E.current(features=["binding", "hts", "lite"], marker=missing) == E.LITE
    for f in (None, [], ["binding"], ["binding", "membrane", "hts", "cg"]):
        assert E.current(features=f, marker=missing) == E.FULL


def test_the_verifier_reads_a_lite_licence_without_any_change():
    """`lite` travels in the existing v2 `features` field: the verifier keeps unknown words, and the feature gate only
    asks for the four real features, so a Lite licence needs no new licence format."""
    from md20.util import license as L
    assert E.LITE_FLAG not in L.FEATURES and E.LITE_FLAG not in L.TIERS
    extra = L._parse_v2({"features": ["Lite", "binding", "hts"]}, b"", [])
    assert extra["features"] == ["binding", "hts", "lite"]
    st = L.LicenseStatus(L.VALID, features=extra["features"])
    assert st.allows("binding") and st.allows("hts") and not st.allows("membrane") and not st.allows("cg")
    assert E.current(features=st.features, marker=Path("does-not-exist.json")) == E.LITE


def test_nothing_outside_the_package_and_licence_changes_the_edition():
    src = (ROOT / "md20" / "edition.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    code = re.sub(r'""".*?"""', "", code, flags=re.S)
    assert not re.search(r"\benviron\b|getenv|\bargv\b|\bargparse\b", code)


# ------------------------------------------------------------------------------------------- limits
def test_complete_edition_has_no_limits_and_no_hits():
    assert all(v is None for v in E.LIMITS[E.FULL].as_dict().values())
    big = _cfg(tier="research", replicas=5, production_ns=1000.0, membrane={"lipids": "POPC"})
    big["ligands"] = [{"name": f"L{i}", "smiles": "C"} for i in range(8)]
    assert E.check_config(big, E.FULL) == []
    assert E.check_system(n_atoms=10**7, n_protein_residues=10**5, edition=E.FULL) == []
    assert E.check_library(10**4, E.FULL) == []
    assert E.clamp_config(big, E.FULL) == (big, [])


def test_defaults_this_module_copies_stay_equal_to_their_sources():
    from md20.engine.protocol import TIERS
    from md20.sampling.binding import BindingConfig
    assert {k: v["prod_ps"] / 1000.0 for k, v in TIERS.items()} == E._TIER_NS
    b = BindingConfig()
    assert E._BINDING_DEFAULTS == {"max_windows": b.max_windows, "window_prod_ps": b.window_prod_ps,
                                   "max_refine_rounds": b.max_refine_rounds}
    assert set(E.LIMITS[E.LITE].md_tiers) <= set(TIERS)


def test_a_plain_teaching_config_passes_lite():
    assert E.check_config(_cfg(), E.LITE) == []
    assert E.check_config(_cfg(tier="classroom", replicas=1, production_ns=5), E.LITE) == []
    assert E.check_config({}, E.LITE) == [] and E.check_config(None, E.LITE) == []


@pytest.mark.parametrize("change, code", [
    (dict(tier="research"), "md.tier"),
    (dict(production_ns=50), "md.production_ns"),
    (dict(replicas=3), "md.replicas"),
    (dict(membrane={"lipids": "POPC"}), "feature.membrane"),
    (dict(resolution="cg"), "feature.cg"),
    (dict(long_run={"total_ns": 1000}), "feature.long_run"),
])
def test_md_settings_beyond_lite_are_reported(change, code):
    assert code in [h.code for h in E.check_config(_cfg(**change), E.LITE)]


def test_research_tier_is_reported_once_for_its_length():
    codes = [h.code for h in E.check_config(_cfg(tier="research"), E.LITE)]
    assert codes == ["md.tier"]            # after the tier is brought down the default length is within the limit


def test_ligand_count_fold_and_autonomy():
    c = _cfg()
    c["ligands"] = [{"name": f"L{i}", "smiles": "C"} for i in range(3)]
    (h,) = E.check_config(c, E.LITE)
    assert (h.code, h.value, h.limit, h.can_clamp) == ("ligands.count", 3, 2, False)
    c = _cfg()
    c["ligands"] = [{"name": "P", "sequence": "ACDEFGHIK"}]
    assert E.check_config(c, E.LITE) == []                    # a peptide with no fold request is fine
    c["ligands"][0]["fold"] = True
    assert [h.code for h in E.check_config(c, E.LITE)] == ["feature.fold"]
    c["ligands"][0]["fold"] = "complex"
    assert [h.code for h in E.check_config(c, E.LITE)] == ["feature.fold"]
    c = _cfg()
    c["autonomy"] = {"enabled": True}
    assert [h.code for h in E.check_config(c, E.LITE)] == ["feature.autonomy"]


def test_binding_limits_apply_only_when_binding_is_on():
    c = _cfg()
    c["binding"] = {"enabled": False, "config": {"max_windows": 40, "window_prod_ps": 1000.0}}
    assert E.check_config(c, E.LITE) == []
    c["binding"]["enabled"] = True
    c["binding"]["target_replicas"] = {"BEN": 3}
    assert sorted(h.code for h in E.check_config(c, E.LITE)) == ["binding.max_windows", "binding.refine_rounds",
                                                               "binding.replicas", "binding.window_ps"]
    c2 = _cfg()
    c2["binding"] = {"enabled": True, "config": {}}           # defaults: 40 windows, 6 refinement rounds
    assert sorted(h.code for h in E.check_config(c2, E.LITE)) == ["binding.max_windows", "binding.refine_rounds"]


def test_clamp_brings_sizes_under_the_limits_and_lists_every_change():
    c = _cfg(tier="research", replicas=3, production_ns=200)
    c["binding"] = {"enabled": True, "target_replicas": {"BEN": 3}, "config": {"window_prod_ps": 2000.0}}
    before = copy.deepcopy(c)
    out, changes = E.clamp_config(c, E.LITE)
    assert c == before, "the input is not modified"
    assert E.check_config(out, E.LITE) == []
    lim = E.LIMITS[E.LITE]
    assert out["md"]["tier"] == "teaching" and out["md"]["replicas"] == 1 and out["md"]["production_ns"] == lim.max_production_ns
    assert out["binding"]["target_replicas"] == {"BEN": 1}
    assert out["binding"]["config"] == {"window_prod_ps": lim.max_window_ps, "max_windows": lim.max_windows,
                                        "max_refine_rounds": lim.max_refine_rounds}
    keys = {ch["key"] for ch in changes}
    assert keys == {"md.tier", "md.replicas", "md.production_ns", "binding.target_replicas", "binding.config.window_prod_ps",
                    "binding.config.max_windows", "binding.config.max_refine_rounds"}
    assert all(set(ch) == {"key", "from", "to", "code"} for ch in changes)
    assert E.clamp_config(out, E.LITE) == (out, []), "clamping twice changes nothing"


def test_clamp_never_drops_a_feature_or_a_ligand():
    c = _cfg(membrane={"lipids": "POPC"}, replicas=3)
    c["ligands"] = [{"name": f"L{i}", "smiles": "C"} for i in range(4)]
    out, changes = E.clamp_config(c, E.LITE)
    assert out["md"]["membrane"] == {"lipids": "POPC"} and len(out["ligands"]) == 4
    assert [ch["key"] for ch in changes] == ["md.replicas"]
    assert sorted(h.code for h in E.check_config(out, E.LITE)) == ["feature.membrane", "ligands.count"]


def test_system_and_library_size():
    lim = E.LIMITS[E.LITE]
    assert E.check_system(n_atoms=lim.max_atoms, n_protein_residues=lim.max_protein_residues, edition=E.LITE) == []
    hits = E.check_system(n_atoms=lim.max_atoms + 1, n_protein_residues=lim.max_protein_residues + 1, edition=E.LITE)
    assert [h.code for h in hits] == ["system.atoms", "system.residues"] and not any(h.can_clamp for h in hits)
    assert E.check_system(n_atoms=lim.max_atoms_implicit + 1, solvent="gbn2", edition=E.LITE)[0].limit == lim.max_atoms_implicit
    assert E.check_system(n_atoms=lim.max_atoms_implicit + 1, solvent="explicit", edition=E.LITE) == []
    assert E.check_system(edition=E.LITE) == []
    assert E.check_library(lim.max_screen_compounds, E.LITE) == []
    (h,) = E.check_library(lim.max_screen_compounds + 1, E.LITE)
    assert (h.code, h.limit) == ("screen.compounds", lim.max_screen_compounds)


# ------------------------------------------------------------------------------------------- registry and texts
def test_languages_match_the_project():
    assert tuple(LANGS)[:4] == LANG4 or set(LANG4) <= set(LANGS)


def test_every_pro_feature_has_four_languages_and_existing_modules():
    ids = [f.id for f in E.PRO_FEATURES]
    assert len(ids) == len(set(ids))
    for f in E.PRO_FEATURES:
        assert len(f.title) == 4 and all(f.title) and len(f.gain) == 4 and all(f.gain), f.id
        for m in f.modules:
            assert (ROOT / m).is_file(), f"{f.id}: {m} does not exist"
            assert not m.endswith("__init__.py"), "a package __init__ is never removed"
    assert E.pro_modules() == tuple(sorted(set(E.pro_modules())))


def test_modules_a_lite_package_needs_are_never_listed_as_pro():
    keep = {"md20/edition.py", "md20/util/license.py", "md20/workflow.py", "md20/cli.py", "md20/i18n.py",
            "md20/build/assemble.py", "md20/build/pipeline.py", "md20/sampling/binding.py", "md20/engine/chunks.py"}
    assert not keep & set(E.pro_modules())


def test_every_hit_reads_in_four_languages_with_no_placeholder_left():
    c = _cfg(tier="research", replicas=3, production_ns=200, membrane={"x": 1}, resolution="cg", long_run={"a": 1})
    c["ligands"] = [{"name": f"L{i}", "smiles": "C", "fold": True} for i in range(3)]
    c["autonomy"] = {"enabled": True}
    c["binding"] = {"enabled": True, "target_replicas": 4, "config": {"window_prod_ps": 9999.0}}
    hits = (E.check_config(c, E.LITE) + E.check_system(n_atoms=99999, n_protein_residues=999, edition=E.LITE)
            + E.check_library(500, E.LITE))
    assert {h.code for h in hits} >= {"md.production_ns", "md.replicas", "ligands.count", "binding.replicas",
                                      "binding.max_windows", "binding.window_ps", "binding.refine_rounds", "feature.membrane",
                                      "feature.cg", "feature.fold", "feature.long_run", "feature.autonomy", "system.atoms",
                                      "system.residues", "screen.compounds"}
    for h in hits:
        assert h.kind in (E.SCALE, E.FEATURE) and h.feature in {f.id for f in E.PRO_FEATURES}, h.code
        texts = h.texts()
        assert len(texts) == 4 and len(set(texts)) == 4, h.code
        for t in texts:
            assert t and "{" not in t and "}" not in t, (h.code, t)
        d = h.as_dict()
        assert set(d["text"]) == set(LANG4) and json.dumps(d, ensure_ascii=False)


def test_texts_follow_the_writing_rules():
    """docs/specs/writing_style.md §1: no dashes joining clauses, no slash for 'or', no arrows in sentences."""
    texts = [t for f in E.PRO_FEATURES for t in f.title + f.gain] + list(E.HOW_TO_UPGRADE)
    texts += [t for v in E._HIT_TEXT.values() for t in v] + [E.upgrade_text(f.id, l) for f in E.PRO_FEATURES for l in LANG4]
    for t in texts:
        assert not re.search(r"——|—|–|→|／| / ", t), t


def test_upgrade_required_carries_the_four_texts():
    e = E.UpgradeRequired("membrane")
    assert e.feature == "membrane" and len(e.texts) == 4 and all(e.texts) and str(e) == e.texts[1]
    assert E.UpgradeRequired(what="x").texts == ("x",) * 4


def test_summary_and_comparison():
    assert E.summary("zh")["edition"] == E.FULL and E.summary("zh")["locked"] == []
    for lang in LANG4:
        rows = E.comparison_rows(lang)
        assert len(rows) >= 6 and all(r["item"] and r["lite"] and r["full"] for r in rows)
    assert E.name(E.LITE, "en") == "MD20 Lite"


# ------------------------------------------------------------------------------------------- workflow contract
def test_gate_offers_the_reduction_only_when_it_helps():
    hits = E.check_config(_cfg(replicas=3), E.LITE)
    g = E.gate(hits, "zh")
    assert g["name"] == E.GATE_NAME and g["status"] == "NEEDS_HUMAN" and "edition.accept_clamp" in g["options"][0]
    assert len(g["options"]) == 4 and g["evidence"]["hits"][0]["code"] == "md.replicas"
    only_feature = E.check_config(_cfg(membrane={"a": 1}), E.LITE)
    g2 = E.gate(only_feature, "en")
    assert len(g2["options"]) == 3 and not any("accept_clamp" in o for o in g2["options"])
    for lang in LANG4:
        assert E.gate(hits, lang)["explanation"]


def test_accepted_reads_the_decision_key():
    assert not E.accepted({}) and not E.accepted(None) and not E.accepted({"edition": "lite"})
    assert not E.accepted({"edition": {"accept_clamp": False}})
    assert E.accepted({"edition": {"accept_clamp": True}})
    assert E.ACCEPT_KEY == ("edition", "accept_clamp")


def test_state_record_keeps_each_limit_once():
    hits = E.check_config(_cfg(replicas=3), E.LITE)
    rec = E.state_record(hits + hits + [hits[0].as_dict()], [{"key": "md.replicas", "from": 3, "to": 1, "code": "md.replicas"}],
                         at="2026-11-11T00:00:00Z")
    assert [h["code"] for h in rec["hits"]] == ["md.replicas"] and rec["clamped"][0]["to"] == 1
    assert rec["edition"] == E.FULL and json.dumps(rec, ensure_ascii=False)
