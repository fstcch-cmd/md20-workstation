"""D-135 (R4): analysis cache fingerprint, reuse decision and atomic regeneration.  Pure Python; no mdtraj, no MD."""
import json
import os
from pathlib import Path

import pytest

from md20.analysis import fingerprint as FP
from md20.analysis.fingerprint import (analysis_fingerprint, reuse_decision, write_manifest_atomic, begin_staging,
                                       commit_staging, recover_interrupted, parts_for)
from md20.util import load_json


GROUPS = {"L01": [10, 11, 12]}


def _make_run(tmp_path: Path, *, dcd_bytes=b"A" * 300):
    run = tmp_path / "run1"
    stage = run / "stages" / "production"
    stage.mkdir(parents=True)
    dcd = stage / "chunk_00001.dcd"
    dcd.write_bytes(dcd_bytes)
    (stage / "production_complete.json").write_text(json.dumps({
        "status": "PASS", "state_sha256": "abc", "timestep_fs": 2.0, "backend_info": {"dcd_atoms": "all", "dcd_atom_count": 100},
        "result": {"dcd_paths": [str(dcd)], "steps": 5000}}))
    (run / "run.json").write_text(json.dumps({"protocol_hash": "p1", "protocol": {"stages": []}}))
    top = tmp_path / "top.pdb"
    top.write_text("ATOM      1  N   ALA A   1       0.000   0.000   0.000\n")
    return run, top, dcd


def _fp(run, top, **kw):
    kw.setdefault("ligand_groups", GROUPS)
    kw.setdefault("metal_indices", [])
    kw.setdefault("ligand_charges", {"L01": {10: -1}})
    return analysis_fingerprint(run, top, **kw)


def _commit(run, fp, reason="first", figs=True):
    fig = run / "figures"
    fig.mkdir(exist_ok=True)
    (fig / "a.png").write_bytes(b"png")
    adir = run / "analysis"
    man = {"status": "PASS", "metrics_file": str(adir / "metrics.json"), "extended_file": str(adir / "extended.json"),
           "figures": {"timeseries": {"png": str(fig / "a.png")}} if figs else {}}
    return write_manifest_atomic(run, man, fingerprint=fp, outputs={"metrics.json": {"v": 1, "r": reason},
                                                                    "extended.json": {"e": 1}},
                                 provenance={"reason": reason})


# ------------------------------------------------------------------------------------------------ reuse / recompute
def test_unchanged_inputs_are_reused_and_the_fingerprint_is_stable(tmp_path):
    run, top, _ = _make_run(tmp_path)
    fp = _fp(run, top)
    assert fp["digest"] == _fp(run, top)["digest"] and fp["analysis_version"] == FP.ANALYSIS_VERSION
    final = _commit(run, fp)
    assert final["fingerprint"]["digest"] == fp["digest"] and final["analysis_version"] == FP.ANALYSIS_VERSION
    d = reuse_decision(run, _fp(run, top))
    assert d["reuse"] is True and d["reason"] == "unchanged" and d["changed"] == [] and d["recompute_parts"] == []


@pytest.mark.parametrize("what", ["topology", "selection", "charges", "metals", "protocol", "dcd", "memory", "extra", "membrane"])
def test_changed_inputs_recompute_and_name_the_changed_component(tmp_path, monkeypatch, what):
    run, top, dcd = _make_run(tmp_path)
    _commit(run, _fp(run, top))
    kw, expect = {}, None
    if what == "topology":
        top.write_text(top.read_text() + "ATOM      2  CA  ALA A   1       1.000   0.000   0.000\n"); expect = ["topology"]
    elif what == "selection":
        kw["ligand_groups"] = {"L01": [10, 11]}; expect = ["selections"]
    elif what == "charges":
        kw["ligand_charges"] = {"L01": {10: 1}}; expect = ["selections"]
    elif what == "metals":
        kw["metal_indices"] = [5]; expect = ["selections"]
    elif what == "membrane":
        kw["membrane"] = True; expect = ["selections"]
    elif what == "protocol":
        (run / "run.json").write_text(json.dumps({"protocol_hash": "p2"})); expect = ["protocol"]
    elif what == "dcd":
        dcd.write_bytes(b"B" * 300)                            # same size, other content (a replaced file)
        expect = [k for k in _fp(run, top)["components"] if k.startswith("dcd:")]
    elif what == "memory":
        monkeypatch.setenv("MD20_ANALYSIS_MEM_GB", "1"); expect = ["analysis_memory_gb"]
    elif what == "extra":
        kw["extra"] = {"temperature": 310}; expect = ["extra:temperature"]
    d = reuse_decision(run, _fp(run, top, **kw))
    assert d["reuse"] is False and d["reason"] == "changed" and d["changed"] == sorted(expect)
    assert d["recompute_parts"] == ["core", "extended"]


def test_schema_and_threshold_changes_name_what_changed_and_the_affected_parts(tmp_path, monkeypatch):
    run, top, _ = _make_run(tmp_path)
    _commit(run, _fp(run, top))
    from md20.analysis import persistence as PS, extended as EX, traj as TJ
    from md20.sampling import assessment as AS

    monkeypatch.setattr(PS, "SCHEMA", "md20.persistence/2")
    d = reuse_decision(run, _fp(run, top))
    assert (d["reuse"], d["changed"], d["recompute_parts"]) == (False, ["persistence_schema"], ["extended"])
    monkeypatch.undo()

    monkeypatch.setattr(EX, "EXTENDED_SCHEMA", "md20.extended/99")
    assert reuse_decision(run, _fp(run, top))["changed"] == ["extended_schema"]
    monkeypatch.undo()

    monkeypatch.setattr(EX, "MAX_FRAMES", 100)
    d = reuse_decision(run, _fp(run, top))
    assert d["changed"] == ["extended_thresholds"] and d["recompute_parts"] == ["extended"]
    monkeypatch.undo()

    monkeypatch.setitem(TJ.LIGAND_STATE_THRESHOLDS, "pose_rmsd_A", 3.5)
    d = reuse_decision(run, _fp(run, top))
    assert d["changed"] == ["ligand_state_thresholds"] and d["recompute_parts"] == ["core", "extended"]
    monkeypatch.undo()

    monkeypatch.setattr(AS, "THRESHOLDS_VERSION", "9999")
    d = reuse_decision(run, _fp(run, top))
    assert d["changed"] == ["assessment_thresholds_version"] and d["recompute_parts"] == ["assessment"]
    monkeypatch.undo()

    monkeypatch.setattr(FP, "ANALYSIS_VERSION", "2099-01-01.1")
    d = reuse_decision(run, _fp(run, top))
    assert d["changed"] == ["analysis_version"] and d["reason"] == "changed"
    assert parts_for(["analysis_version"]) == ["core", "extended"]
    assert reuse_decision(run, _fp(run, top))["reuse"] is False


def test_legacy_pass_manifest_without_fingerprint_is_not_reused(tmp_path):
    run, top, _ = _make_run(tmp_path)
    adir = run / "analysis"
    adir.mkdir()
    (adir / "metrics.json").write_text("{}")
    (adir / "analysis_manifest.json").write_text(json.dumps({"status": "PASS", "metrics_file": str(adir / "metrics.json")}))
    d = reuse_decision(run, _fp(run, top))
    assert d["reuse"] is False and d["reason"] == "legacy" and d["recompute_parts"] == ["core", "extended"]
    # regenerating keeps the legacy manifest as the previous one, flagged legacy
    _commit(run, _fp(run, top), reason="legacy migration")
    prev = load_json(adir / "analysis_manifest.prev.json", {})
    assert prev["superseded"]["legacy"] is True and prev["superseded"]["reason"] == "legacy migration"
    assert (adir / "analysis_manifest.json").is_file() and reuse_decision(run, _fp(run, top))["reuse"] is True


def test_no_manifest_and_not_pass(tmp_path):
    run, top, _ = _make_run(tmp_path)
    assert reuse_decision(run, _fp(run, top))["reason"] == "no_manifest"
    adir = run / "analysis"
    adir.mkdir()
    (adir / "analysis_manifest.json").write_text(json.dumps({"status": "FAILED"}))
    assert reuse_decision(run, _fp(run, top))["reason"] == "not_pass"


def test_missing_referenced_files_force_recompute(tmp_path):
    run, top, _ = _make_run(tmp_path)
    fp = _fp(run, top)
    for victim in ("analysis/metrics.json", "analysis/extended.json", "figures/a.png"):
        _commit(run, fp)
        assert reuse_decision(run, fp)["reuse"] is True
        (run / victim).unlink()
        d = reuse_decision(run, fp)
        assert d["reuse"] is False and d["reason"] == "missing_files" and d["missing"], victim
        assert d["recompute_parts"]


def test_replaced_output_is_detected_not_trusted(tmp_path):
    run, top, _ = _make_run(tmp_path)
    fp = _fp(run, top)
    _commit(run, fp)
    (run / "analysis" / "metrics.json").write_text('{"v": 999}')       # same path, other content
    d = reuse_decision(run, fp)
    assert d["reuse"] is False and d["reason"] == "output_modified" and d["modified"] == ["metrics.json"]


def test_missing_dcd_does_not_crash_the_fingerprint_and_counts_as_changed(tmp_path):
    run, top, dcd = _make_run(tmp_path)
    _commit(run, _fp(run, top))
    dcd.unlink()
    fp = _fp(run, top)
    assert any(v == "missing" for k, v in fp["components"].items() if k.startswith("dcd:"))
    assert reuse_decision(run, fp)["reuse"] is False


def test_recorded_chunk_hash_mismatch_is_reported(tmp_path):
    run, top, dcd = _make_run(tmp_path)
    from md20.util.hashing import cheap_fingerprint
    rec = cheap_fingerprint(dcd)
    prog = {"chunks": [{"chunk": 1, "artifacts": {"dcd": {"path": str(dcd), **rec}}}]}
    (run / "stages" / "production" / "production_progress.json").write_text(json.dumps(prog))
    assert _fp(run, top)["details"]["recorded_mismatch"] == []
    dcd.write_bytes(b"C" * 300)
    fp = _fp(run, top)
    assert fp["details"]["recorded_mismatch"] == [dcd.name]
    assert any(v.endswith("differs_from_chunk_manifest") for k, v in fp["components"].items() if k.startswith("dcd:"))


# ------------------------------------------------------------------------------------------------ atomic regeneration
def test_successful_regeneration_keeps_the_previous_result_with_provenance(tmp_path):
    run, top, _ = _make_run(tmp_path)
    fp1 = _fp(run, top)
    m1 = _commit(run, fp1, reason="first")
    top.write_text("changed\n")
    fp2 = _fp(run, top)
    _commit(run, fp2, reason="topology changed")
    adir = run / "analysis"
    assert load_json(adir / "analysis_manifest.json")["fingerprint"]["digest"] == fp2["digest"]
    prev = load_json(adir / "analysis_manifest.prev.json")
    assert prev["fingerprint"]["digest"] == fp1["digest"] and prev["committed_at"] == m1["committed_at"]
    assert prev["superseded"]["by_digest"] == fp2["digest"] and prev["superseded"]["reason"] == "topology changed"
    assert json.loads((adir / "prev" / "metrics.json").read_text())["r"] == "first"
    assert not list(adir.glob(".staging-*")) and not (adir / ".swap_journal.json").exists()


@pytest.mark.parametrize("fail_on", ["metrics.json", "analysis_manifest.json"])
def test_interrupted_swap_cannot_replace_a_complete_result_with_a_partial_one(tmp_path, fail_on):
    run, top, _ = _make_run(tmp_path)
    fp1 = _fp(run, top)
    _commit(run, fp1, reason="first")
    adir = run / "analysis"
    before = {n: (adir / n).read_bytes() for n in ("analysis_manifest.json", "metrics.json", "extended.json")}
    top.write_text("changed\n")
    fp2 = _fp(run, top)

    def boom(stage, name):
        if name == fail_on:
            raise KeyboardInterrupt("simulated crash during the swap")

    fig = run / "figures"
    man = {"status": "PASS", "metrics_file": str(adir / "metrics.json"), "extended_file": str(adir / "extended.json"),
           "figures": {"t": {"png": str(fig / "a.png")}}}
    with pytest.raises(KeyboardInterrupt):
        write_manifest_atomic(run, man, fingerprint=fp2, outputs={"metrics.json": {"v": 2}, "extended.json": {"e": 2}},
                              provenance={"reason": "second"}, _hook=boom)
    assert (adir / "analysis_manifest.json").read_bytes() == before["analysis_manifest.json"]      # old manifest untouched
    d = reuse_decision(run, fp1)                                # recovery runs first: partial outputs are rolled back
    assert d["reuse"] is True and d["reason"] == "unchanged" and any("rolled back" in n for n in d["notes"])
    for n in ("metrics.json", "extended.json"):
        assert (adir / n).read_bytes() == before[n], n
    assert not (adir / ".swap_journal.json").exists() and not list(adir.glob(".staging-*"))
    # the new inputs still say "recompute", never "reuse the old result"
    assert reuse_decision(run, fp2)["reason"] == "changed"


def test_a_crash_before_any_swap_leaves_everything_untouched(tmp_path):
    run, top, _ = _make_run(tmp_path)
    fp1 = _fp(run, top)
    _commit(run, fp1)
    adir = run / "analysis"
    snapshot = {p.name: p.read_bytes() for p in adir.iterdir() if p.is_file()}
    st = begin_staging(run)
    (st / "metrics.json").write_text('{"half": true}')          # regeneration died while writing: never committed
    assert {p.name: p.read_bytes() for p in adir.iterdir() if p.is_file()} == snapshot
    assert reuse_decision(run, fp1)["reuse"] is True
    begin_staging(run)                                          # the next attempt cleans the stale staging directory
    assert len(list(adir.glob(".staging-*"))) == 1


def test_a_first_time_crash_removes_files_the_interrupted_swap_created(tmp_path):
    run, top, _ = _make_run(tmp_path)
    fp = _fp(run, top)

    def boom(stage, name):
        if name == "metrics.json":                             # files are swapped in sorted order: extended.json goes first
            raise RuntimeError("crash")
    adir = run / "analysis"
    with pytest.raises(RuntimeError):
        write_manifest_atomic(run, {"status": "PASS"}, fingerprint=fp, outputs={"metrics.json": {"a": 1}, "extended.json": {"b": 1}},
                              _hook=boom)
    assert (adir / "extended.json").exists()                    # swapped before the crash …
    assert reuse_decision(run, fp)["reason"] == "no_manifest"   # … rolled back, and with no manifest nothing is reused
    assert not (adir / "extended.json").exists()


def test_completed_swap_with_leftover_journal_is_cleaned_not_rolled_back(tmp_path):
    run, top, _ = _make_run(tmp_path)
    fp = _fp(run, top)
    final = _commit(run, fp)
    adir = run / "analysis"
    (adir / ".swap_journal.json").write_text(json.dumps({"files": ["metrics.json", "extended.json", "analysis_manifest.json"],
                                                          "new_files": [], "new_commit_id": final["commit_id"]}))
    notes = recover_interrupted(run)
    assert notes and "completed" in notes[0] and (adir / "metrics.json").is_file()
    assert reuse_decision(run, fp)["reuse"] is True
