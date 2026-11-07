"""D-136 (R7): the capability manifest (docs/capabilities.json -> docs/CAPABILITIES.md) is current and cannot lie.

Runs the same logic as `python tools/capability_manifest.py --check` (also a CI step), plus negative cases showing the
check catches: a missing path, a state inferred from the wrong evidence, a non-blocking job cited as qualification, a
claimed release that was never published, version drift, and a stale generated .md.  Pure Python."""
import copy
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("capability_manifest", ROOT / "tools" / "capability_manifest.py")
    mod = importlib.util.module_from_spec(spec)
    import sys
    sys.modules["capability_manifest"] = mod
    spec.loader.exec_module(mod)
    return mod


CM = _load()


@pytest.fixture()
def manifest():
    return CM.load()


@pytest.fixture()
def fake_root(tmp_path):
    """A minimal tree for the version / workflow checks, so a test can break one thing at a time."""
    shutil.copytree(ROOT / ".github", tmp_path / ".github")
    (tmp_path / "md20").mkdir()
    for f in ("pyproject.toml", "README.md"):
        shutil.copy(ROOT / f, tmp_path / f)
    shutil.copy(ROOT / "md20" / "__init__.py", tmp_path / "md20" / "__init__.py")
    (tmp_path / "docs" / "releases").mkdir(parents=True)
    for d in ("v0.1.0a18.md", "v0.1.0a19.md"):
        (tmp_path / "docs" / "releases" / d).write_text("draft", encoding="utf-8")
    return tmp_path


def feature(m, fid):
    return next(f for f in m["features"] if f["id"] == fid)


def test_the_real_manifest_passes_every_check():
    assert CM.run_checks() == []


def test_markdown_is_generated_not_hand_edited(manifest, tmp_path):
    assert (ROOT / "docs" / "CAPABILITIES.md").read_text(encoding="utf-8") == CM.render_markdown(manifest)
    md = tmp_path / "C.md"
    md.write_text(CM.render_markdown(manifest) + "edited by hand\n", encoding="utf-8")
    assert any("out of sync" in p for p in CM.check_markdown_in_sync(manifest, md))
    assert any("missing" in p for p in CM.check_markdown_in_sync(manifest, tmp_path / "none.md"))


def test_every_main_feature_is_covered(manifest):
    ids = {f["id"] for f in manifest["features"]}
    for need in ("docking_vina", "receptor_ligand_build", "metal_bonded_zinc", "membrane_build", "md_openmm_restart", "replicas",
                 "smd_umbrella_pmf", "adaptive_windows", "assessment", "interactions_persistence", "common_basis_comparison",
                 "toolbox_tica_msm", "reports", "gui_worker", "licence_l2_l3_verification", "installer"):
        assert need in ids, need


def test_the_five_states_are_not_conflated(manifest):
    """Spot checks on honest content: zinc fails, nothing is benchmarked 'yes', unreleased features say so."""
    z = feature(manifest, "metal_bonded_zinc")
    assert z["states"]["real_engine_tested"] == "failing" and z["last_known_result"]["status"] == "fail"
    assert all(f["states"]["scientifically_benchmarked"] != "yes" for f in manifest["features"])
    assert feature(manifest, "toolbox_tica_msm")["released_installer"] == "unreleased (main only)"
    assert feature(manifest, "toolbox_tica_msm")["states"]["real_engine_tested"] == "no"
    assert feature(manifest, "licence_l4_distribution_protection")["states"]["implemented"] == "no"
    assert feature(manifest, "replicas")["states"]["implemented"] == "partial"      # analysis aggregation pending D-130
    assert "D-130" in " ".join(feature(manifest, "replicas")["restrictions"])


def test_missing_implementation_path_symbol_and_test_file_are_caught(manifest):
    m = copy.deepcopy(manifest)
    f = feature(m, "docking_vina")
    f["implementation"] = ["md20/docking/nope.py", "md20/docking/run.py::no_such_function"]
    f["tests"] = f["tests"] + [{"file": "tests/test_does_not_exist.py", "type": "unit", "ci_job": "ci.yml:pure-python"}]
    p = "\n".join(CM.check_features(m, ROOT))
    assert "implementation path not found: md20/docking/nope.py" in p
    assert "symbol no_such_function not defined" in p
    assert "test file not found: tests/test_does_not_exist.py" in p


def test_real_engine_state_needs_a_real_engine_test_in_a_blocking_job(manifest):
    m = copy.deepcopy(manifest)
    f = feature(m, "toolbox_tica_msm")
    f["states"]["real_engine_tested"] = "yes"                       # inferred from synthetic tests: must be refused
    p = "\n".join(CM.check_features(m, ROOT))
    assert "toolbox_tica_msm: real_engine_tested=yes without a real_engine test in a BLOCKING real-engine job" in p


def test_diagnostic_or_benchmark_job_cannot_qualify(manifest):
    m = copy.deepcopy(manifest)
    f = feature(m, "docking_vina")
    f["states"]["scientifically_benchmarked"] = "yes"               # paper-docking is non-blocking
    assert any("needs a BLOCKING benchmark job" in p for p in CM.check_features(m, ROOT))
    m = copy.deepcopy(manifest)
    f = feature(m, "membrane_build")
    f["tests"] = [t for t in f["tests"] if t["type"] != "real_engine"]     # leaves only unit + diagnostic evidence
    assert any("membrane_build: real_engine_tested=partial without" in p for p in CM.check_features(m, ROOT))
    m = copy.deepcopy(manifest)
    for j in m["ci_jobs"]:
        if j["id"] == "diag-membrane.yml:build":
            j["blocking"], j["counts_for"] = True, ["real_engine_tested"]
    assert any("must be non-blocking and count for nothing" in p for p in CM.check_ci_jobs(m, ROOT))


def test_benchmark_scope_and_state_must_agree(manifest):
    m = copy.deepcopy(manifest)
    feature(m, "assessment")["benchmark_scope"] = "matches experiment"
    assert any("benchmark_scope describes a benchmark" in p for p in CM.check_features(m, ROOT))
    m = copy.deepcopy(manifest)
    feature(m, "docking_vina")["benchmark_scope"] = "none"
    assert any("benchmark_scope is none" in p for p in CM.check_features(m, ROOT))


def test_evidence_needs_commit_and_url_and_stale_needs_files(manifest):
    m = copy.deepcopy(manifest)
    r = feature(m, "hts_screen")["last_known_result"]
    r["evidence_url"] = ""
    assert any("needs a commit and an https://github.com/ evidence_url" in p for p in CM.check_features(m, ROOT))
    m = copy.deepcopy(manifest)
    feature(m, "hts_screen")["last_known_result"]["status"] = "stale"
    assert any("must list changed_since_evidence" in p for p in CM.check_features(m, ROOT))


def test_released_installer_must_be_a_published_tag(manifest):
    m = copy.deepcopy(manifest)
    feature(m, "reports")["released_installer"] = "v0.1.0a19"      # never published
    assert any("neither" in p for p in CM.check_features(m, ROOT))
    m = copy.deepcopy(manifest)
    feature(m, "reports")["released_installer"] = "v0.1.0a18 (older code)"
    assert any("neither" in p or "unpublished tag" in p for p in CM.check_features(m, ROOT))


def test_versions_agree_with_published_tags(manifest, fake_root):
    assert CM.check_versions(manifest, fake_root) == []
    (fake_root / "md20" / "__init__.py").write_text('__version__ = "0.1.0a19"\n', encoding="utf-8")
    p = "\n".join(CM.check_versions(manifest, fake_root))
    assert "!= pyproject.toml version" in p
    (fake_root / "md20" / "__init__.py").write_text('__version__ = "0.1.0a20.dev0"\n', encoding="utf-8")
    rd = fake_root / "README.md"
    rd.write_text(rd.read_text(encoding="utf-8") + "\n下載 MD20-Windows-v0.1.0a19.zip\n", encoding="utf-8")
    assert any("v0.1.0a19, which was never published" in p for p in CM.check_versions(manifest, fake_root))
    m = copy.deepcopy(manifest)
    m["versions"]["package_version"] = "0.1.0a17"
    assert any("manifest package_version" in p for p in CM.check_versions(m, fake_root))


def test_the_real_tree_names_no_unpublished_release_to_students():
    m = CM.load()
    assert CM.check_versions(m, ROOT) == []
    pub = set(m["versions"]["published_releases"])
    for f in [ROOT / "README.md", ROOT / "docs" / "WINDOWS_QUICKSTART.md", *(ROOT / "docs" / "students").glob("*.md")]:
        for tag in CM.TAG_RE.findall(f.read_text(encoding="utf-8")):
            assert tag in pub or "從未" in f.read_text(encoding="utf-8"), (f, tag)


def test_workflow_scan_sees_the_real_nonblocking_jobs():
    wf = CM.scan_workflows(ROOT)
    pd = wf["ci.yml"]["paper-docking"]
    assert pd["continue_on_error"] and "not qualification" in pd["name"].lower()
    assert "build" in wf["diag-membrane.yml"] and "not qualification" in wf["diag-membrane.yml"]["build"]["name"].lower()
    assert not wf["ci.yml"]["pure-python"]["continue_on_error"]
    assert set(wf["ci.yml"]) >= {"pure-python", "openmm-stack", "heavy", "paper-docking", "installer-windows", "installer-macos"}


def test_unlabelled_nonblocking_job_unlisted_job_and_missing_ci_step_are_caught(manifest, fake_root):
    assert CM.check_ci_jobs(manifest, fake_root) == []
    ci = fake_root / ".github" / "workflows" / "ci.yml"
    text = ci.read_text(encoding="utf-8")
    ci.write_text(text.replace('name: "paper-docking (BENCHMARK, non-blocking - not qualification)"\n', ""), encoding="utf-8")
    assert any("must say 'not qualification'" in p for p in CM.check_ci_jobs(manifest, fake_root))
    ci.write_text(text.replace("tools/capability_manifest.py --check", "true"), encoding="utf-8")
    assert any("does not run" in p for p in CM.check_ci_jobs(manifest, fake_root))
    ci.write_text(text + "\n  sneaky:\n    runs-on: ubuntu-latest\n    continue-on-error: true\n    steps: []\n", encoding="utf-8")
    assert any("ci.yml:sneaky is not listed" in p for p in CM.check_ci_jobs(manifest, fake_root))
    # a job that hides failures must be listed as non-blocking
    m = copy.deepcopy(manifest)
    for j in m["ci_jobs"]:
        if j["id"] == "ci.yml:paper-docking":
            j["blocking"] = True
    ci.write_text(text, encoding="utf-8")
    assert any("continue-on-error but the manifest says blocking" in p for p in CM.check_ci_jobs(m, fake_root))


def test_cli_check_exit_codes(tmp_path, capsys):
    assert CM.main(["--check"]) == 0
    assert "capability manifest OK" in capsys.readouterr().out
    # --stale never fails (shallow clones cannot compare)
    assert CM.main(["--stale"]) == 0


def test_json_is_valid_utf8_and_schema(manifest):
    assert manifest["schema"] == "md20.capabilities/1"
    json.dumps(manifest, ensure_ascii=False)
