"""D-135: analyse_run wiring without mdtraj — loading, metrics, centred export and plots are replaced by stand-ins;
what is checked is the new part: resolution records, staging/commit of the outputs, the fingerprint in the manifest and
the fallback when the streamed persistence cannot run."""
import json

import numpy as np

from md20.analysis import traj as TJ
from md20.analysis.fingerprint import analysis_fingerprint, reuse_decision
from md20.util import load_json

from test_extended_fingerprint_wiring import _system, fake_mdtraj  # noqa: F401


def _run(tmp_path):
    run = tmp_path / "run1"
    stage = run / "stages" / "production"
    stage.mkdir(parents=True)
    dcd = stage / "chunk_00001.dcd"
    dcd.write_bytes(b"x" * 400)
    (stage / "production_complete.json").write_text(json.dumps({
        "state_sha256": "s", "timestep_fs": 2.0, "backend_info": {"dcd_atoms": "all", "dcd_atom_count": 8},
        "result": {"dcd_paths": [str(dcd)], "steps": 1000}}))
    (run / "run.json").write_text(json.dumps({"protocol_hash": "p", "protocol": {}}))
    top = tmp_path / "t.pdb"
    top.write_text("x\n")
    return run, top


def _patch(monkeypatch):
    traj = _system()
    monkeypatch.setattr(TJ, "load_production", lambda *a, **k: traj)
    monkeypatch.setattr(TJ, "compute_metrics", lambda t, g: {"time_ns": [0.0], "n_frames": t.n_frames, "ligands": {}})
    monkeypatch.setattr(TJ, "export_centered", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no mdtraj")))
    monkeypatch.setattr(TJ, "plot_metrics", lambda *a, **k: {"timeseries": {}})


def test_analyse_run_stores_fingerprint_resolution_and_is_reused_when_unchanged(tmp_path, monkeypatch, fake_mdtraj):  # noqa: F811
    run, top = _run(tmp_path)
    _patch(monkeypatch)
    groups = {"L01": [0, 1]}
    fp = analysis_fingerprint(run, top, ligand_groups=groups)
    man = TJ.analyse_run(run, top, ligand_groups=groups, fingerprint=fp, provenance={"reason": "test"})
    adir = run / "analysis"
    stored = load_json(adir / "analysis_manifest.json")
    assert stored["status"] == "PASS" and stored["fingerprint"]["digest"] == fp["digest"] == man["fingerprint"]["digest"]
    assert stored["analysis_version"] and stored["resolution"]["effective_stride"] == 1
    assert stored["resolution"]["resolution"]["status"] == "full"
    assert set(stored["outputs"]) >= {"metrics.json", "extended.json", "ca_labels.json", "ca_xyz.npy"}
    ext = load_json(adir / "extended.json")
    assert ext["ligands"]["L01"]["fingerprint"]["persistence"]["status"] == "computed"
    d = reuse_decision(run, analysis_fingerprint(run, top, ligand_groups=groups))
    assert d["reuse"] is True
    assert reuse_decision(run, analysis_fingerprint(run, top, ligand_groups={"L01": [0]}))["changed"] == ["selections"]


def test_strided_analysis_is_limited_and_a_failed_stream_is_recorded_not_hidden(tmp_path, monkeypatch, fake_mdtraj):  # noqa: F811
    run, top = _run(tmp_path)
    _patch(monkeypatch)
    TJ.analyse_run(run, top, ligand_groups={"L01": [0, 1]}, stride=4)       # mdtraj is the stub: the streaming pass fails
    adir = run / "analysis"
    man = load_json(adir / "analysis_manifest.json")
    assert man["resolution"]["effective_stride"] == 4 and man["resolution"]["resolution"]["status"] == "limited"
    assert "streamed_persistence_error" in man
    pers = load_json(adir / "extended.json")["ligands"]["L01"]["fingerprint"]["persistence"]
    assert pers["status"] == "limited" and "invisible" in pers["reason"]
    assert not list(adir.glob(".staging-*"))
