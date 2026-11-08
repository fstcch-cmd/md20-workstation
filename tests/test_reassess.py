"""D-143 / D-134 open item: re-assess stored binding results with the current rules and write the assessment back."""
import json
from pathlib import Path

import pytest

from md20.sampling.assessment import THRESHOLDS_VERSION, claim_status
from md20.sampling.reassess import (backup_file, needs_reassessment, reassess_workflow, replica_manifests, report_lines)
from md20.util import load_json
from test_autonomy_kit import StubWorkflow, build_workflow, failing_pmf, good_pmf, legacy_pmf


def _result(kit):
    return load_json(kit.wf_dir / "state.json")["steps"]["binding"]["results"][kit.target]


def test_legacy_result_is_eligible_only_if_current_diagnostics_pass(tmp_path):
    kit = build_workflow(tmp_path / "ok", pmf=good_pmf())                 # legacy: no assessment stored, but every field is there
    before = claim_status(_result(kit), "dG_standard")
    assert before["eligible"] is False and "assess_legacy" in before["reasons"]
    rep = reassess_workflow(kit.wf_dir, at="2026-11-08T01:02:03Z")
    t = rep["targets"][kit.target]
    assert t["status"] == "reassessed" and "dG_standard" in t["became_eligible"]
    after = claim_status(_result(kit), "dG_standard")
    assert after["eligible"] is True and after["assessment"] == "pass"
    a = _result(kit)["assessment"]
    p = a["provenance"]
    assert p["source"] == "reassessed" and p["thresholds_version"] == THRESHOLDS_VERSION
    assert p["original_version"] is None and p["original_was_legacy"] is True and p["at"] == "2026-11-08T01:02:03Z"
    assert "legacy" not in a


def test_legacy_result_whose_diagnostics_fail_stays_ineligible_and_says_why(tmp_path):
    kit = build_workflow(tmp_path, pmf=failing_pmf())
    reassess_workflow(kit.wf_dir)
    c = claim_status(_result(kit), "dG_standard")
    assert c["eligible"] is False and c["assessment"] == "fail" and "assess_failed" in c["reasons"]
    assert "half_split" in c["failed"]


def test_missing_fields_stay_unknown_and_ineligible_nothing_is_guessed(tmp_path):
    kit = build_workflow(tmp_path, pmf=legacy_pmf())
    rep = reassess_workflow(kit.wf_dir)
    t = rep["targets"][kit.target]
    assert {"window_ess", "cumulative_drift", "endpoint_plateau"} <= set(t["unknown"])
    c = claim_status(_result(kit), "dG_standard")
    assert c["eligible"] is False and c["assessment"] == "unknown"
    assert not t["became_eligible"]


def test_original_files_are_backed_up_never_overwritten(tmp_path):
    kit = build_workflow(tmp_path, pmf=good_pmf())
    man = replica_manifests(kit.wf_dir, kit.target)[0]
    state0, man0 = (kit.wf_dir / "state.json").read_bytes(), man.read_bytes()
    rep = reassess_workflow(kit.wf_dir, at="2026-11-08T01:02:03Z")
    sb = Path(rep["state_backup"])
    assert sb.name.startswith("state.json.pre-reassess-") and sb.read_bytes() == state0
    mb = Path(rep["targets"][kit.target]["backups"][0])
    assert mb.read_bytes() == man0
    # the replica manifest carries it too
    assert load_json(man)["result"]["assessment"]["provenance"]["source"] == "reassessed"
    # a backup name is never reused
    again = backup_file(man, "2026-11-08T01:02:03Z")
    assert again != mb and again.exists() and mb.read_bytes() == man0


def test_idempotent_and_current_version_is_left_alone(tmp_path):
    kit = build_workflow(tmp_path, pmf=good_pmf())
    reassess_workflow(kit.wf_dir)
    s1 = (kit.wf_dir / "state.json").read_bytes()
    rep = reassess_workflow(kit.wf_dir)
    assert rep["targets"][kit.target] == {"status": "skipped", "why": "current"} and (kit.wf_dir / "state.json").read_bytes() == s1
    assert needs_reassessment({"thresholds_version": THRESHOLDS_VERSION}) == (False, "current")


def test_outdated_stored_assessment_is_reassessed_only_on_request(tmp_path):
    kit = build_workflow(tmp_path, pmf=good_pmf(), assessed=True)
    st = load_json(kit.wf_dir / "state.json")
    st["steps"]["binding"]["results"][kit.target]["assessment"]["thresholds_version"] = "2020-01-01"
    (kit.wf_dir / "state.json").write_text(json.dumps(st), encoding="utf-8")
    assert reassess_workflow(kit.wf_dir)["targets"][kit.target]["why"] == "outdated_thresholds_not_requested"
    rep = reassess_workflow(kit.wf_dir, include_outdated=True)
    assert rep["targets"][kit.target]["status"] == "reassessed"
    p = _result(kit)["assessment"]["provenance"]
    assert p["original_version"] == "2020-01-01" and p["original_was_legacy"] is False


def test_dry_run_writes_nothing(tmp_path):
    kit = build_workflow(tmp_path, pmf=good_pmf())
    snap = {p: p.read_bytes() for p in kit.wf_dir.rglob("*") if p.is_file()}
    rep = reassess_workflow(kit.wf_dir, dry_run=True)
    assert rep["targets"][kit.target]["status"] == "would_reassess"
    assert snap == {p: p.read_bytes() for p in kit.wf_dir.rglob("*") if p.is_file()}


def test_no_stored_pmf_is_skipped_not_invented(tmp_path):
    kit = build_workflow(tmp_path, pmf=good_pmf())
    replica_manifests(kit.wf_dir, kit.target)[0].unlink()
    assert reassess_workflow(kit.wf_dir)["targets"][kit.target]["why"] == "no_stored_pmf"
    assert "assessment" not in _result(kit)


def test_comparison_recomputed_with_a_workflow_else_flagged_stale(tmp_path):
    kit = build_workflow(tmp_path / "a", pmf=good_pmf())
    rep = reassess_workflow(kit.wf_dir)
    assert rep["comparison"] == "stale"
    assert load_json(kit.wf_dir / "state.json")["steps"]["binding"]["comparison_stale"]
    kit2 = build_workflow(tmp_path / "b", pmf=good_pmf())
    wf = StubWorkflow(kit2)
    rep2 = reassess_workflow(kit2.wf_dir, wf=wf)
    assert rep2["comparison"] == "recomputed" and "comparison" in load_json(kit2.wf_dir / "state.json")["steps"]["binding"]
    rows = wf.dec.by_stage("binding.reassess")
    assert rows and "沒有新的取樣" in rows[0]["why"]


def test_two_replicas_are_combined_so_one_failing_replica_blocks_eligibility(tmp_path):
    kit = build_workflow(tmp_path, pmf=good_pmf())
    rep2 = kit.wf_dir / "binding" / kit.target / "rep2"
    rep2.mkdir()
    man = json.loads(replica_manifests(kit.wf_dir, kit.target)[0].read_text(encoding="utf-8"))
    man["result"]["pmf"] = failing_pmf()
    (rep2 / "binding_manifest.json").write_text(json.dumps(man), encoding="utf-8")
    assert len(replica_manifests(kit.wf_dir, kit.target)) == 2
    rep = reassess_workflow(kit.wf_dir)
    assert rep["targets"][kit.target]["replicas"] == 2
    assert claim_status(_result(kit), "dG_standard")["eligible"] is False


def test_report_lines_are_plain_chinese(tmp_path):
    kit = build_workflow(tmp_path, pmf=good_pmf())
    text = "\n".join(report_lines(reassess_workflow(kit.wf_dir)))
    assert "重新評估" in text and kit.target in text


def test_cli_binding_reassess(tmp_path, capsys):
    from md20.cli import main
    kit = build_workflow(tmp_path, pmf=good_pmf())
    assert main(["--dir", str(tmp_path), "binding", "reassess", str(kit.wf_dir), "--dry-run"]) == 0
    assert "會重新評估" in capsys.readouterr().out and "assessment" not in _result(kit)
    assert main(["--dir", str(tmp_path), "binding", "reassess", kit.name, "--project", "proj"]) == 0
    assert _result(kit)["assessment"]["provenance"]["source"] == "reassessed"
