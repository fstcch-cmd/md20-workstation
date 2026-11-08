"""Shared fixtures for the D-143 tests: a workflow on disk (state.json, config.json, binding manifests, a run) and a stub Workflow.
No OpenMM: real engine runs use the FakeBackend, everything else is files."""
from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from md20.engine import FakeBackend, make_protocol, run_protocol
from md20.project import Project
from md20.util import atomic_write_json, load_json
from md20.util.decisions import ScopedDecisionLog


def good_pmf() -> dict:
    n = 5
    M = [[1.0 if i == j else (0.3 if abs(i - j) == 1 else 0.0) for j in range(n)] for i in range(n)]
    return {"method": "MBAR", "converged": True, "plateau": True, "pmf_radial_kj_mol": [0, 1, 2], "grid_nm": [0.1, 0.2, 0.3],
            "quality": {"graph_connected": True, "window_stats": [{"n_effective": 400.0}] * n},
            "coverage": {"continuous": True, "breaks": []},
            "overlap_matrix": {"matrix": M, "min_neighbour": 0.3},
            "half_split": {"diff_kj_mol": 0.6},
            "convergence": {"0.25": {"delta_pmf": 19.0}, "0.50": {"delta_pmf": 20.2}, "0.75": {"delta_pmf": 20.1},
                            "1.00": {"delta_pmf": 20.0}}}


def legacy_pmf() -> dict:
    """Written before D-96: no plateau flag, no window statistics, no convergence curve."""
    p = good_pmf()
    for k in ("plateau", "convergence"):
        p.pop(k)
    p["quality"] = {"graph_connected": True}
    return p


def failing_pmf() -> dict:
    p = good_pmf()
    p["half_split"] = {"diff_kj_mol": 9.0}
    return p


def small_protocol():
    proto = make_protocol("classroom", replicas=1)
    for s in proto.stages:
        if s.ensemble != "MIN":
            s.length_ps, s.checkpoint_interval_ps, s.report_interval_ps = 40.0, 10.0, 0.2
    return proto


def fake_factory(spec, dt):
    return FakeBackend(timestep_fs=dt, temperature_k=spec.temperature_k, ensemble=spec.ensemble)


def real_fake_run(case, reason="kit"):
    """A finished run made by the real engine with the FakeBackend (run.json gets the checkpoint fingerprint)."""
    proto = small_protocol()
    run = case.new_run(proto.to_dict(), reason=reason)
    ident = {"case_id": case.case_id, "run_id": run.run_id, "project_uuid": case.project.uuid}
    run_protocol(run.dir, proto, fake_factory, identity=ident, decisions=case.project.decisions, batch_steps=500)
    return run


def build_workflow(tmp_path: Path, *, name="wf1", pmf=None, assessed=False, replicas_in_state=1, real_run=False,
                   fingerprint=True, target="L1") -> SimpleNamespace:
    """A project with one case, one finished MD run, and one finished binding target `target`.
    `pmf`: the PMF fields stored in the target's binding_manifest.json (default: legacy).  `assessed`: also store a D-96+
    assessment in state.json (so the result is not legacy)."""
    from md20.sampling.assessment import assess_pmf
    project = Project.create(tmp_path, "proj")
    case = project.new_case("c")
    atomic_write_json({"assembly": {"n_atoms": 24000}}, case.build_dir / "build_manifest.json")
    if real_run:
        run = real_fake_run(case)
    else:
        run = case.new_run(small_protocol().to_dict(), reason="kit")
        rj = run.manifest()
        rj.update({"status": "COMPLETE", "protocol_hash": "h1"})
        sd = run.dir / "stages" / "production"
        sd.mkdir(parents=True)
        (sd / "production_state.xml").write_text("<State/>" * 50, encoding="utf-8")
        run.save_manifest(rj)
    rj = run.manifest()
    if not fingerprint:
        rj.pop("checkpoint_fingerprint", None)
        run.save_manifest(rj)
    wf_dir = project.dir / "workflows" / name
    wf_dir.mkdir(parents=True)
    cfg = {"name": name, "md": {"replicas": 1}, "binding": {"enabled": True}}
    atomic_write_json(cfg, wf_dir / "config.json")
    pm = pmf if pmf is not None else legacy_pmf()
    res = {"status": "PASS", "ligand": target, "replicas": 1, "delta_pmf_kj_mol": 20.0, "dG_standard_kj_mol": -30.0, "dG_withheld": None,
           "replica_sources": [{"replica": 0, "md_run_id": run.run_id}]}
    if assessed:
        res["assessment"] = assess_pmf(pm, dG_withheld=None, has_dG=True)
    bdir = wf_dir / "binding" / target
    atomic_write_json({"status": "PASS", "config": {"window_equil_ps": 10.0, "window_prod_ps": 50.0, "sample_every_steps": 50,
                                                    "timestep_fs": 2.0},
                       "result": {"status": "PASS", "pmf": pm, "dG_standard_kj_mol": -30.0, "delta_pmf_kj_mol": 20.0}},
                      bdir / "binding_manifest.json")
    (bdir / "windows").mkdir()
    np.save(bdir / "windows" / "w_0.5000_cv.npy", np.linspace(0.4, 0.6, 100))
    state = {"steps": {"md_cases": {"status": "PASS", "cases": {"docked": {"case_id": case.case_id, "mode": "docked_single", "ligands": [target]}}},
                       "md_runs": {"status": "PASS", "runs": {"docked": {"case_id": case.case_id, "group_id": "g", "status": "COMPLETE",
                                                                         "run_ids": [run.run_id] * replicas_in_state}}},
                       "binding": {"status": "PASS", "results": {target: res}}}}
    atomic_write_json(state, wf_dir / "state.json")
    return SimpleNamespace(project=project, case=case, run=run, wf_dir=wf_dir, name=name, target=target, cfg=cfg)


class StubWorkflow:
    """The slice of `Workflow` the executors call, with the heavy parts replaced by recorders that write the files the real
    ones would write."""

    def __init__(self, kit, *, run_md=None, binding=None, analyse=None):
        self.project, self.name, self.cfg, self.dir = kit.project, kit.name, copy.deepcopy(kit.cfg), kit.wf_dir
        self.state_path = self.dir / "state.json"
        self.dec = ScopedDecisionLog(kit.project.decisions, kit.name)
        self.calls = []
        self._run_md, self._binding, self._analyse = run_md, binding, analyse
        self.kit = kit

    def state(self):
        return load_json(self.state_path, {"steps": {}})

    def completed_replicas(self):
        out = {}
        for key, r in (self.state()["steps"].get("md_runs") or {}).get("runs", {}).items():
            case = self.project.case(r["case_id"])
            out[key] = sum(1 for rid in r["run_ids"] if (case.dir / "runs" / rid / "run.json").is_file()
                           and load_json(case.dir / "runs" / rid / "run.json", {}).get("status") == "COMPLETE")
        return out

    def run_md(self, built, make_factory, should_pause=None, progress_cb=None):
        self.calls.append(("run_md", self.cfg["md"]["replicas"]))
        return self._run_md(self) if self._run_md else (self.state()["steps"]["md_runs"]["runs"])

    def analyse(self, runs):
        self.calls.append(("analyse", sorted(runs)))
        return self._analyse(self) if self._analyse else {}

    def binding(self, runs, built, platform, should_pause=None, progress_cb=None):
        self.calls.append(("binding", copy.deepcopy(self.cfg.get("binding", {}).get("manual_windows"))))
        return self._binding(self) if self._binding else {}

    def _binding_targets(self, runs, built):
        return [], {"single": [self.kit.target]}
