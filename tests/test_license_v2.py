"""D-128 (layer 3): licence format v2 (tier, features, org, seats, max_version, issuer_key), feature gates, the evaluation
notice on outputs, the licence id on outputs, and the signed revocation list.  v1 licences keep working (tests/test_license.py)."""
import base64
import copy
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from md20 import cli
from md20.util import license as L
from md20.util import stamp
import _license_testkit as K


@pytest.fixture
def machine(monkeypatch):
    monkeypatch.setattr(L, "machine_code", lambda: "AAAA-BBBB-CCCC-DDDD")
    L._reset_cache()
    return "AAAA-BBBB-CCCC-DDDD"


def _only(license_env, doc):
    license_env.clear()
    license_env.put(doc)
    return L.status()


def _v2(license_env, **kw):
    kw.setdefault("days", 30)
    kw.setdefault("issuer_key", "auto")
    return license_env.issue("Zed", **kw)


# ------------------------------------------------------------------------------------------------ the payload
def test_a_v2_licence_without_optional_fields_behaves_like_v1(license_env):
    st = _only(license_env, license_env.issue("Zed", version=2, days=30))
    assert st.ok and st.schema == L.SCHEMA_V2 and st.tier == "" and st.features is None and st.seats is None and st.max_version is None
    assert all(st.allows(f) for f in L.FEATURES)
    old = _only(license_env, license_env.issue("Old", days=30))
    assert old.ok and old.schema == L.SCHEMA and all(old.allows(f) for f in L.FEATURES)


def test_v2_fields_are_read(license_env, machine):
    st = _only(license_env, _v2(license_env, tier="research", features=["hts", "Binding"], org=" Lab A ", seats=3, max_version="0.9",
                                machines=["AAAA-BBBB-CCCC-DDDD"]))
    assert st.ok and st.tier == "research" and st.features == ["binding", "hts"] and st.org == "Lab A" and st.seats == 3
    assert st.allows("hts") and not st.allows("cg")
    assert _only(license_env, _v2(license_env, features=["binding", "all"])).features is None       # "all" anywhere = every feature
    assert _only(license_env, _v2(license_env, features=[])).features == []                          # an empty list is "none", not "all"


@pytest.mark.parametrize("kw", [dict(tier="student"), dict(tier=7), dict(features="binding"), dict(features=[1]), dict(org=5), dict(seats=0),
                                dict(seats=True), dict(seats="2"), dict(max_version="one"), dict(max_version=3), dict(issuer_key="x"),
                                dict(issuer_key="0" * 64),                                   # not the fingerprint of the signing key
                                dict(seats=1, machines=["1111-2222-3333-4444", "AAAA-BBBB-CCCC-DDDD"]),
                                dict(tier="site"), dict(tier="site", org="U", machines=["1111-2222-3333-4444"])])
def test_malformed_v2_fields_are_refused_even_when_signed(license_env, kw):
    st = _only(license_env, _v2(license_env, **kw))
    assert st.state == L.BAD_SIGNATURE and "malformed" in st.detail


def test_a_site_licence_is_bound_to_the_organisation_not_to_a_computer(license_env, machine):
    st = _only(license_env, _v2(license_env, tier="site", org="NKUST", features=["all"]))
    assert st.ok and st.machines == [] and st.org == "NKUST"


def test_issuer_key_must_be_the_key_that_signed(license_env):
    assert _only(license_env, _v2(license_env, tier="teaching")).ok
    fp = L.key_fingerprint(license_env.pub)
    assert re.fullmatch(r"[0-9a-f]{64}", fp)
    assert _only(license_env, license_env.issue("Zed", days=3, issuer_key=fp)).ok


def test_max_version_follows_pep440(license_env, monkeypatch):
    doc = _v2(license_env, max_version="0.1.0")
    for version, expect in (("0.1.0a19", L.VALID), ("0.1.0rc1", L.VALID), ("0.1.0", L.VALID), ("0.1.0.post1", L.VERSION_LIMIT), ("0.1.1", L.VERSION_LIMIT),
                            ("0.2.0a1", L.VERSION_LIMIT), ("1.0", L.VERSION_LIMIT)):
        monkeypatch.setattr(L, "_app_version", lambda v=version: v)
        assert _only(license_env, doc).state == expect, version
    monkeypatch.setattr(L, "_app_version", lambda: "0.1.1")
    st = _only(license_env, doc)
    assert not st.ok and "0.1.0" in st.message("en") and "0.1.1" in st.message("en") and st.max_version == "0.1.0"
    assert all("0.1.0" in st.message(l) for l in L.LANG_ORDER)
    monkeypatch.setattr(L, "_app_version", lambda: "unreadable version")
    assert _only(license_env, doc).state == L.VERSION_LIMIT                      # cannot compare: blocked, not guessed


def test_the_shipped_version_is_pep440():
    from packaging.version import Version
    from md20 import __version__
    Version(__version__)


def test_v2_and_v1_prefixes_do_not_cross(license_env):
    v2 = license_env.issue("Zed", version=2, days=3)
    flipped = copy.deepcopy(v2); flipped["payload"]["schema"] = L.SCHEMA
    assert L.evaluate(flipped).state == L.BAD_SIGNATURE
    v1 = license_env.issue("Zed", days=3)
    flipped = copy.deepcopy(v1); flipped["payload"]["schema"] = L.SCHEMA_V2
    assert L.evaluate(flipped).state == L.BAD_SIGNATURE
    # a v1 signature carrying v2 fields does not make them take effect (and cannot be signed by anyone but the owner anyway)
    pad, algo = K.pss_for_signing()
    p = {**v1["payload"], "features": ["hts"], "tier": "evaluation"}
    doc = {"payload": p, "sig": base64.b64encode(license_env.key.sign(L.DOMAIN + L.canonical(p), pad, algo)).decode()}
    st = L.evaluate(doc)
    assert st.ok and st.features is None and st.tier == ""


def test_status_summary_and_cli_show_the_v2_fields(license_env, capsys):
    _only(license_env, _v2(license_env, tier="commercial", features=["hts"], org="Co", seats=2, max_version="2.0"))
    assert cli.main(["license", "status"]) == 0
    out = capsys.readouterr().out
    assert "tier: commercial" in out and "features: hts" in out and "org: Co" in out and "seats: 2" in out and "max version: 2.0" in out
    assert L.status().summary()["features"] == ["hts"]


# ------------------------------------------------------------------------------------------------ feature gates
def _cfg(**over):
    from md20.workflow import example_config
    cfg = example_config()
    cfg.update(over)
    return cfg


def test_required_features_come_from_the_config_alone():
    from md20.workflow import required_features as rf
    assert rf({}) == [] and rf(None) == []
    assert rf({"binding": {"enabled": True}}) == ["binding"]
    assert rf({"binding": {"enabled": False}}) == []
    assert rf({"binding": {"added": ["BEN"]}}) == ["binding"]
    assert rf({"binding": {"alone": {"BEN": True}}}) == ["binding"] and rf({"binding": {"alone": {"BEN": False}}}) == []
    assert rf({"md": {"membrane": {"type": "bilayer"}}}) == ["membrane"]
    assert rf({"screen": {"library": "x.xlsx"}}) == ["hts"]
    assert rf({"md": {"resolution": "cg"}, "binding": {"enabled": True}}) == ["cg"]          # coarse grained never computes a binding free energy
    assert rf({"md": {"resolution": "cg", "membrane": {"type": "bilayer"}}, "screen": {"library": "x"}}) == ["cg", "hts", "membrane"]
    assert rf({"md": {"resolution": "aa"}}) == []


def test_require_with_a_feature(license_env):
    _only(license_env, _v2(license_env, features=["hts"]))
    assert L.require("x", feature="hts").ok
    with pytest.raises(L.FeatureNotLicensed) as e:
        L.require("x", feature="binding")
    assert isinstance(e.value, L.LicenseRequired) and e.value.feature == "binding"
    with pytest.raises(ValueError):
        L.require("x", feature="teleport")
    with pytest.raises(L.FeatureNotLicensed):
        L.require_features("x", ["hts", "cg"])
    L.require_features("x", ["hts"])
    L.require_features("x", [])
    license_env.clear()
    with pytest.raises(L.LicenseRequired) as e:
        L.require("x", feature="hts")
    assert not isinstance(e.value, L.FeatureNotLicensed)                      # no licence at all is the older, plainer error


def test_the_feature_message_is_in_four_languages(license_env):
    _only(license_env, _v2(license_env, tier="teaching", features=["hts"]))
    with pytest.raises(L.FeatureNotLicensed) as e:
        L.require("x", feature="binding")
    zh, en, ja, ko = e.value.texts()
    assert "你的授權不含" in zh and "結合自由能" in zh and "binding" in zh and "teaching" in zh and "hts" in zh
    assert "does not include" in en and "binding free energy" in en
    assert "含まれていません" in ja and "포함되어 있지 않습니다" in ko
    assert "does not include" in str(e.value)
    for f, name in (("membrane", "膜系統"), ("hts", "HTS"), ("cg", "粗粒化")):
        assert name in L.feature_denied_texts(L.status(), f)[0]
    all_features = _only(license_env, _v2(license_env, tier="teaching"))
    assert "全部功能" in L.feature_denied_texts(all_features, "cg")[0]


@pytest.mark.parametrize("feature,cfg_edit", [
    ("binding", lambda c: c.update(binding={"enabled": True, "ligands": ["BEN"]})),
    ("membrane", lambda c: c["md"].update(membrane={"type": "bilayer"})),
    ("hts", lambda c: c.update(screen={"library": "x.xlsx"})),
    ("cg", lambda c: c["md"].update(resolution="cg")),
])
def test_workflow_run_stops_at_the_entrance_without_the_feature(license_env, tmp_path, feature, cfg_edit):
    from md20.project import Project
    from md20.workflow import Workflow, example_config
    cfg = example_config()
    cfg["binding"] = {"enabled": False}
    cfg_edit(cfg)
    wf = Workflow(Project.create(tmp_path / "pr", "p"), cfg)
    others = [f for f in L.FEATURES if f != feature]
    _only(license_env, _v2(license_env, features=others))
    with pytest.raises(L.FeatureNotLicensed) as e:
        wf.run(lambda case, proto: None, platform=None)
    assert e.value.feature == feature
    assert not (wf.dir / "running.json").exists()                          # nothing was started
    # with the feature the gate opens (the run then fails for its own reasons, not for the licence)
    _only(license_env, _v2(license_env, features=[feature]))
    try:
        wf.run(lambda case, proto: None, platform=None)
    except L.LicenseRequired:
        raise
    except Exception:  # noqa: BLE001
        pass


def test_a_workflow_that_needs_nothing_runs_on_any_feature_set(license_env, tmp_path):
    from md20.project import Project
    from md20.workflow import Workflow, example_config
    cfg = example_config(); cfg["binding"] = {"enabled": False}
    wf = Workflow(Project.create(tmp_path / "pr", "p"), cfg)
    _only(license_env, _v2(license_env, features=[]))
    try:
        wf.run(lambda case, proto: None, platform=None)
    except L.LicenseRequired:
        raise
    except Exception:  # noqa: BLE001
        pass


def test_cli_pipeline_exits_13_with_the_feature_message_before_creating_anything(license_env, tmp_path, capsys):
    _only(license_env, _v2(license_env, features=["hts", "cg"]))
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps(_cfg()), encoding="utf-8")                      # example_config has binding enabled
    root = tmp_path / "pr"
    assert cli.main(["--dir", str(root), "pipeline", "run", str(cfg), "--project", "p"]) == cli.EXIT_LICENSE == 13
    err = capsys.readouterr().err
    assert "你的授權不含" in err and "does not include" in err and "含まれていません" in err and "포함되어 있지 않습니다" in err
    assert not (root / "p").exists()
    # the same exit code as no licence, and a licence with the feature gets past the gate
    _only(license_env, _v2(license_env, features=["binding"]))
    rc = None
    try:
        rc = cli.main(["--dir", str(root), "pipeline", "run", str(cfg), "--project", "p", "--fake"])
    except Exception:  # noqa: BLE001
        pass
    assert rc != cli.EXIT_LICENSE


def test_cli_resume_skips_the_workflow_it_cannot_run_and_ends_with_13(license_env, tmp_path, capsys):
    from md20.project import Project
    from md20.workflow import Workflow
    _only(license_env, _v2(license_env, features=["hts"]))
    Workflow(Project.create(tmp_path / "pr", "p"), _cfg())
    assert cli.main(["--dir", str(tmp_path / "pr"), "resume"]) == cli.EXIT_LICENSE
    assert "你的授權不含" in capsys.readouterr().err


def test_gui_start_process_refuses_before_launching_anything(license_env, tmp_path, monkeypatch):
    from md20.project import Project
    from md20.workflow import Workflow
    from md20.gui import logic as GL
    from md20.gui import worker as W
    wf = Workflow(Project.create(tmp_path / "pr", "p"), _cfg())
    _only(license_env, _v2(license_env, features=["hts"]))
    started = []
    runner = GL.Runner(launcher=lambda w: started.append(w) or type("P", (), {"poll": lambda self: None})())
    monkeypatch.delenv("MD20_GUI_FAKE_RUN", raising=False)
    with pytest.raises(L.FeatureNotLicensed) as e:
        runner.start_process(wf)
    assert started == [] and "你的授權不含" in e.value.texts()[0]
    info = W.run_worker(wf.project.dir, wf.name)                              # a worker started anyway says so in four languages
    assert info["status"] == "ERROR" and len(info["message"]) == 4 and "你的授權不含" in info["message"][0]
    _only(license_env, _v2(license_env, features=["binding"]))
    runner.start_process(wf)
    assert len(started) == 1


def test_the_gui_card_logic_is_wired_to_the_exception():
    src = (Path(cli.__file__).parent / "gui" / "app.py").read_text(encoding="utf-8")
    assert "FeatureNotLicensed" in src and "feature_block" in src and "data-testid=feature-card" in src


def test_no_environment_variable_or_option_opens_a_feature(license_env):
    src = Path(L.__file__).read_text(encoding="utf-8")
    assert not re.search(r"\benviron\b|getenv|\bargv\b", src)
    wsrc = (Path(cli.__file__).parent / "workflow.py").read_text(encoding="utf-8")
    block = wsrc[wsrc.index("def required_features"):wsrc.index("def example_config")]
    assert "environ" not in block and "getenv" not in block
    _only(license_env, _v2(license_env, features=["hts"]))
    import os
    for k in ("MD20_LICENSE_FEATURES", "MD20_FEATURES", "MD20_ALL_FEATURES", "MD20_NO_LICENSE", "MD20_DEV", "CI"):
        os.environ[k] = "1"
    try:
        with pytest.raises(L.FeatureNotLicensed):
            L.require("x", feature="binding")
    finally:
        for k in ("MD20_LICENSE_FEATURES", "MD20_FEATURES", "MD20_ALL_FEATURES", "MD20_NO_LICENSE", "MD20_DEV", "CI"):
            os.environ.pop(k, None)


# ------------------------------------------------------------------------------------------------ evaluation notice
def _evaluation(license_env, **kw):
    kw.setdefault("tier", "evaluation")
    return _only(license_env, _v2(license_env, **kw))


def test_html_footer_and_licence_id(license_env):
    foot = stamp.html_footer()
    lid = L.status().license_id
    assert f"Licence ID: {lid}" in foot and "評估版" not in foot                  # an ordinary licence: id, no notice
    st = _evaluation(license_env)
    foot = stamp.html_footer()
    assert f"Licence ID: {st.license_id}" in foot
    for t in stamp.EVAL_NOTICE:
        assert t in foot
    assert "評估版，不得用於決策" in foot
    license_env.clear()
    assert "Licence ID" not in stamp.html_footer()


def test_html_footer_escapes_the_licensee(license_env):
    license_env.clear()
    license_env.put(license_env.issue("<b>X</b> & Y", days=3))
    foot = stamp.html_footer()
    assert "<b>X</b>" not in foot and "&lt;b&gt;X&lt;/b&gt; &amp; Y" in foot


def test_json_stamp_marks_evaluation(license_env):
    rec = stamp.stamp_record()
    assert "eval" not in rec and "tier" not in rec["lic"]
    st = _evaluation(license_env)
    rec = stamp.stamp_record()
    assert rec["lic"] == {"id": st.license_id, "who": "Zed", "tier": "evaluation"} and rec["eval"] == " / ".join(stamp.EVAL_NOTICE)


def test_pdb_remarks_carry_the_licence_in_seven_bit_ascii(license_env, tmp_path):
    license_env.clear()
    license_env.put(license_env.issue("王小明", days=3))
    lid = L.status().license_id
    lines = stamp.pdb_remarks()
    assert f"REMARK 999 LICENCE ID {lid}" in lines and any(l.startswith("REMARK 999 LICENSEE ") for l in lines)
    assert all(len(l) <= 80 for l in lines) and all(l.isascii() for l in lines) and not any("EVALUATION" in l for l in lines)
    st = _evaluation(license_env)
    lines = stamp.pdb_remarks()
    assert "REMARK 999 EVALUATION VERSION - NOT FOR USE IN DECISIONS" in lines and all(l.isascii() and len(l) <= 80 for l in lines)
    pdb = tmp_path / "a.pdb"; pdb.write_text("ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N\nEND\n")
    stamp.stamp_pdb_file(pdb)
    assert pdb.read_text(encoding="ascii").count("LICENCE ID") == 1
    assert stamp.find_markers(pdb)["license_id"] == st.license_id and stamp.find_markers(pdb)["evaluation"]
    stamp.stamp_pdb_file(pdb)                                                  # still idempotent
    assert pdb.read_text(encoding="ascii").count("LICENCE ID") == 1


def test_figure_metadata_has_licence_and_notice(license_env):
    lid = L.status().license_id
    assert stamp.figure_metadata("png")["md20:lic"] == lid and "Disclaimer" not in stamp.figure_metadata("png")
    assert stamp.figure_metadata("svg")["Identifier"] == f"md20-license:{lid}" and "Title" not in stamp.figure_metadata("svg")
    assert f"lic:{lid}" in stamp.figure_metadata("pdf")["Keywords"]
    _evaluation(license_env)
    for fmt, key in (("png", "Disclaimer"), ("svg", "Title"), ("pdf", "Title")):
        assert stamp.figure_metadata(fmt)[key] == " / ".join(stamp.EVAL_NOTICE), fmt
    license_env.clear()
    assert "md20:lic" not in stamp.figure_metadata("png") and "Identifier" not in stamp.figure_metadata("svg")


@pytest.mark.parametrize("fmt", ["png", "svg", "pdf"])
def test_saved_figures_carry_the_licence_id_and_notice(license_env, tmp_path, fmt):
    pytest.importorskip("matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    st = _evaluation(license_env)
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    stamp.watermark_figure(fig)
    assert any("EVALUATION VERSION" in t.get_text() for t in fig.texts)
    out = tmp_path / f"f.{fmt}"
    fig.savefig(out, metadata=stamp.figure_metadata(fmt))
    plt.close(fig)
    found = stamp.find_markers(out)
    assert found["license_id"] == st.license_id, fmt
    data = out.read_bytes()
    if fmt != "pdf":                                                           # a PDF keeps its Info strings UTF-16 encoded
        assert "評估版，不得用於決策".encode("utf-8") in data or fmt == "png" and b"Disclaimer" in data
    assert found["blob"] is None or isinstance(found["blob"], str)


def test_the_analysis_and_report_figure_writers_stamp(license_env, tmp_path):
    pytest.importorskip("matplotlib")
    import numpy as np
    import pandas as pd
    from md20.analysis.plots import plot_stage_log
    st = _evaluation(license_env)
    df = pd.DataFrame({"time_ps": np.arange(50.0), "temperature_k": 300 + np.random.default_rng(0).normal(size=50),
                       "potential_kj_mol": -1000 + np.arange(50.0)})
    res = plot_stage_log(df, tmp_path / "log", title="t", target_temperature_k=300.0, html=False)
    assert stamp.find_markers(res["png"])["license_id"] == st.license_id and stamp.find_markers(res["svg"])["license_id"] == st.license_id
    assert stamp.find_markers(res["png"])["evaluation"]
    from md20.report import figures as RF
    plt = RF._plt()
    fig, ax = plt.subplots(); ax.plot([0, 1])
    png = RF._save(fig, tmp_path / "rf.png")
    assert stamp.find_markers(png)["license_id"] == st.license_id and stamp.find_markers(png)["evaluation"]


def test_a_non_evaluation_licence_draws_no_watermark(license_env):
    pytest.importorskip("matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig = plt.figure()
    stamp.watermark_figure(fig)
    assert not fig.texts
    plt.close(fig)


def test_html_reports_and_plotly_pages_use_the_footer(license_env):
    for path in ("report/html.py", "report/workflow_report.py", "analysis/plots.py"):
        assert "html_footer" in (Path(cli.__file__).parent / path).read_text(encoding="utf-8")


def test_stamp_verify_lists_the_licence_id(license_env, tmp_path, capsys):
    st = _evaluation(license_env)
    f = tmp_path / "out.json"
    f.write_text(json.dumps({"x": 1, "_md20": stamp.stamp_record()}, sort_keys=True), encoding="utf-8")
    assert stamp.find_markers(f)["license_id"] == st.license_id
    h = tmp_path / "r.html"; h.write_text("<html><body>" + stamp.html_footer() + "</body></html>", encoding="utf-8")
    assert stamp.find_markers(h)["license_id"] == st.license_id and stamp.find_markers(h)["evaluation"]
    z = tmp_path / "b.zip"
    import zipfile
    with zipfile.ZipFile(z, "w") as zf:
        zf.comment = stamp.zip_comment(); zf.writestr("a", "x")
    assert stamp.find_markers(z)["license_id"] == st.license_id
    capsys.readouterr()
    assert cli.main(["stamp", "verify", str(f), str(h)]) == 0
    out = capsys.readouterr().out
    assert out.count(f"授權編號：{st.license_id}") == 2 and "評估版標記：有" in out
    plain = tmp_path / "plain.txt"; plain.write_text("hello", encoding="utf-8")
    cli.main(["stamp", "verify", str(plain)])
    assert "授權編號：無" in capsys.readouterr().out


def test_json_files_written_by_the_program_carry_the_licence(license_env, tmp_path):
    from md20.util import atomic_write_json
    st = _only(license_env, _v2(license_env, tier="teaching"))
    p = tmp_path / "x.json"
    atomic_write_json({"a": 1}, p)
    assert json.loads(p.read_text(encoding="utf-8"))["_md20"]["lic"]["id"] == st.license_id
    assert stamp.find_markers(p)["license_id"] == st.license_id


# ------------------------------------------------------------------------------------------------ revocation list
def _rev(license_env, ids, issued_at="2026-11-07T12:00:00Z"):
    return K.sign_revocations(ids, license_env.key, issued_at)


def _write_rev(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")
    L._reset_cache()


def test_a_revoked_licence_is_invalid_and_says_so_in_four_languages(license_env):
    doc = _v2(license_env, tier="teaching")
    st = _only(license_env, doc)
    assert st.ok
    _write_rev(license_env.dir / "revoked.json", _rev(license_env, [doc["payload"]["id"]]))
    st = L.status()
    assert st.state == L.REVOKED and not st.ok and st.license_id == doc["payload"]["id"]
    for lang, word in (("zh", "撤銷"), ("en", "revoked"), ("ja", "失効"), ("ko", "철회")):
        assert word in st.message(lang)
    with pytest.raises(L.LicenseRequired):
        L.require()
    assert L.stamp_info() is None                                        # outputs are no longer stamped as licensed
    with pytest.raises(L.LicenseError) as e:                                 # and a revoked file cannot be installed
        L.install(_save(license_env, doc))
    assert "revoked" in e.value.texts[1]


def _save(license_env, doc, name="in.md20license"):
    p = license_env.dir.parent / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def test_revocation_applies_to_v1_licences_and_to_other_ids_it_does_not(license_env):
    v1 = license_env.issue("Old", days=5)
    other = license_env.issue("Other", days=5)
    license_env.clear()
    license_env.put(v1); license_env.put(other)
    _write_rev(license_env.dir / "revoked.json", _rev(license_env, [v1["payload"]["id"]]))
    states = {L.evaluate(d).state for d in (other,)}
    assert states == {L.VALID} and L.evaluate(v1).state == L.REVOKED
    assert L.status().ok and L.status().license_id == other["payload"]["id"]      # any valid file still wins


def test_a_revocation_list_with_a_bad_signature_is_ignored(license_env):
    doc = _v2(license_env)
    _only(license_env, doc)
    forged = _rev(license_env, [doc["payload"]["id"]])
    forged["payload"]["ids"].append("0" * 16)                                 # changed after signing
    _write_rev(license_env.dir / "revoked.json", forged)
    assert L.status().ok and L.revocations() is None
    from cryptography.hazmat.primitives.asymmetric import rsa
    stranger = K.sign_revocations([doc["payload"]["id"]], rsa.generate_private_key(public_exponent=65537, key_size=2048))
    _write_rev(license_env.dir / "revoked.json", stranger)
    assert L.status().ok
    (license_env.dir / "revoked.json").write_text("not json", encoding="utf-8")
    L._reset_cache()
    assert L.status().ok


def test_revocation_and_licence_prefixes_do_not_cross(license_env):
    doc = _v2(license_env)
    _only(license_env, doc)
    pad, algo = K.pss_for_signing()
    for domain in (L.DOMAIN, L.DOMAIN_V2):
        p = {"schema": L.REV_SCHEMA, "issued_at": "2026-11-07T12:00:00Z", "ids": [doc["payload"]["id"]]}
        wrong = {"payload": p, "sig": base64.b64encode(license_env.key.sign(domain + L.canonical(p), pad, algo)).decode()}
        with pytest.raises(ValueError):
            L.parse_revocations(wrong)
    # and a revocation signature is not a licence
    p = {**doc["payload"], "id": "1" * 16}
    sig = base64.b64encode(license_env.key.sign(L.REV_DOMAIN + L.canonical(p), pad, algo)).decode()
    assert L.evaluate({"payload": p, "sig": sig}).state == L.BAD_SIGNATURE


@pytest.mark.parametrize("edit", [lambda p: p.update(schema="md20-revocations-v2"), lambda p: p.update(issued_at="2026-11-07"),
                                  lambda p: p.update(issued_at="2026-13-45T99:99:99Z"), lambda p: p.update(ids="abc"),
                                  lambda p: p.update(ids=["ABCDEF0123456789"]), lambda p: p.update(ids=[5]), lambda p: p.pop("ids")])
def test_signed_but_malformed_lists_are_not_accepted(license_env, edit):
    p = {"schema": L.REV_SCHEMA, "issued_at": "2026-11-07T12:00:00Z", "ids": ["0123456789abcdef"]}
    edit(p)
    pad, algo = K.pss_for_signing()
    doc = {"payload": p, "sig": base64.b64encode(license_env.key.sign(L.REV_DOMAIN + L.canonical(p), pad, algo)).decode()}
    with pytest.raises(ValueError):
        L.parse_revocations(doc)


def test_the_newest_valid_list_wins_between_app_data_and_the_package(license_env, tmp_path, monkeypatch):
    bundled = tmp_path / "bundled"
    monkeypatch.setattr(L, "BUNDLED_DIR", bundled)
    a, b = "a" * 16, "b" * 16
    _write_rev(bundled / "revoked.json", _rev(license_env, [a], "2026-11-09T00:00:00Z"))
    _write_rev(license_env.dir / "revoked.json", _rev(license_env, [b], "2026-11-08T00:00:00Z"))    # older: does not override
    r = L.revocations()
    assert r.issued_at == "2026-11-09T00:00:00Z" and r.ids == {a}
    _write_rev(license_env.dir / "revoked.json", _rev(license_env, [a, b], "2026-11-10T00:00:00Z"))
    r = L.revocations()
    assert r.issued_at == "2026-11-10T00:00:00Z" and r.ids == {a, b}
    _write_rev(license_env.dir / "revoked.json", _rev(license_env, [b], "2026-11-09T00:00:00Z"))    # same time: merged
    assert L.revocations().ids == {a, b}
    (bundled / "revoked.json").write_text("{}", encoding="utf-8")                                    # a broken list is skipped
    assert L.revocations().ids == {b}


def test_update_revocations_takes_only_newer_valid_lists(license_env, tmp_path, capsys):
    doc = _v2(license_env)
    _only(license_env, doc)
    lid = doc["payload"]["id"]
    new = tmp_path / "new.json"
    new.write_text(json.dumps(_rev(license_env, [lid], "2026-11-08T00:00:00Z")), encoding="utf-8")
    assert cli.main(["license", "update-revocations", str(new)]) == 0
    out = capsys.readouterr().out
    assert "2026-11-08T00:00:00Z" in out and "撤銷清單已更新" in out and "Revocation list updated" in out
    assert (license_env.dir / "revoked.json").is_file() and L.status().state == L.REVOKED
    # older list (anti-downgrade) and the same list again are refused, and the installed one stays
    old = tmp_path / "old.json"
    old.write_text(json.dumps(_rev(license_env, [], "2026-11-01T00:00:00Z") if False else _rev(license_env, ["c" * 16], "2026-11-01T00:00:00Z")), encoding="utf-8")
    assert cli.main(["license", "update-revocations", str(old)]) == 1
    err = capsys.readouterr().err
    assert "不比目前使用的新" in err and "not newer" in err
    assert cli.main(["license", "update-revocations", str(new)]) == 1
    assert L.revocations().issued_at == "2026-11-08T00:00:00Z" and L.revocations().ids == {lid}
    # a newer one replaces it
    newer = tmp_path / "newer.json"
    newer.write_text(json.dumps(_rev(license_env, [lid, "c" * 16], "2026-11-09T00:00:00Z")), encoding="utf-8")
    assert cli.main(["license", "update-revocations", str(newer)]) == 0
    assert L.revocations().ids == {lid, "c" * 16}
    # bad signature, junk, missing file
    forged = _rev(license_env, ["d" * 16], "2026-12-01T00:00:00Z"); forged["payload"]["ids"] = ["e" * 16]
    bad = tmp_path / "bad.json"; bad.write_text(json.dumps(forged), encoding="utf-8")
    junk = tmp_path / "junk.json"; junk.write_text("[]", encoding="utf-8")
    capsys.readouterr()
    for f in (bad, junk):
        assert cli.main(["license", "update-revocations", str(f)]) == 1
    assert "不是有效的撤銷清單" in capsys.readouterr().err
    assert cli.main(["license", "update-revocations", str(tmp_path / "missing.json")]) == 1
    assert L.revocations().issued_at == "2026-11-09T00:00:00Z"


def test_an_older_app_data_list_cannot_be_used_to_step_back_from_the_package_list(license_env, tmp_path, monkeypatch):
    bundled = tmp_path / "bundled"
    monkeypatch.setattr(L, "BUNDLED_DIR", bundled)
    _write_rev(bundled / "revoked.json", _rev(license_env, ["a" * 16], "2026-12-01T00:00:00Z"))
    older = tmp_path / "older.json"; older.write_text(json.dumps(_rev(license_env, [], "2026-11-01T00:00:00Z")), encoding="utf-8")
    with pytest.raises(L.LicenseError):
        L.update_revocations(older)
    assert not (license_env.dir / "revoked.json").exists()


def test_status_command_reports_the_revocation_list(license_env, capsys):
    _only(license_env, _v2(license_env))
    cli.main(["license", "status"])
    assert "revocation list: none" in capsys.readouterr().out
    _write_rev(license_env.dir / "revoked.json", _rev(license_env, ["a" * 16, "b" * 16], "2026-11-08T00:00:00Z"))
    cli.main(["license", "status"])
    assert "revocation list: 2026-11-08T00:00:00Z (2 ids)" in capsys.readouterr().out


def test_the_cli_has_no_signing_command_for_revocations(capsys):
    with pytest.raises(SystemExit):
        cli.main(["license", "revoke", "x"])
    with pytest.raises(SystemExit):
        cli.main(["license", "sign-revocations", "x"])
