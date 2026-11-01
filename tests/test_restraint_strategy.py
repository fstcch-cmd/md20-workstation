"""Restraint strategies (consultation §1 Q1, D-23): grouped restraints, release in NPT, restrained-RMSD flag."""
import copy

import pytest

from md20.engine.backend import FakeBackend
from md20.engine.chunks import _apply_schedule
from md20.engine.protocol import RESTRAINT_STRATEGIES, make_protocol, production_restraints
from md20.gui.actions import gate_actions
from md20.project.store import Project
from md20.report.workflow_report import _restrained_tag
from md20.workflow import Workflow, WorkflowBlocked, example_config


def test_standard_releases_in_npt_not_nvt():
    p = make_protocol("teaching")
    nvt, npt, prod = p.stage("nvt"), p.stage("npt"), p.stage("production")
    # NVT only heats: master constant, backbone and ligand held, side chains half released
    assert nvt.restraint_scale == 1.0 and nvt.restraint_scale_end is None
    assert nvt.restraint_groups == {"backbone": [1.0, 1.0], "sidechain": [1.0, 0.5], "ligand": [1.0, 1.0]}
    # the release happens at the right density
    assert npt.restraint_scale == 1.0
    assert all(b == 0.0 for _, b in npt.restraint_groups.values())
    assert npt.restraint_groups["sidechain"][0] == nvt.restraint_groups["sidechain"][1]   # continuous
    assert prod.restraint_scale == 0.0 and not prod.restraint_groups
    assert production_restraints(p) == {}


def test_gentle_and_hold_backbone():
    std, gentle = make_protocol("teaching"), make_protocol("teaching", restraints="gentle")
    assert gentle.stage("npt").length_ps == 2 * std.stage("npt").length_ps
    assert gentle.stage("nvt").restraint_groups["sidechain"] == [1.0, 1.0]
    hold = make_protocol("teaching", restraints="hold_backbone")
    assert production_restraints(hold) == {"backbone": pytest.approx(0.05)}
    assert hold.stage("npt").restraint_groups["backbone"] == [1.0, 0.05]          # continuous into production
    assert hold.hash() != std.hash() != gentle.hash()
    with pytest.raises(KeyError):
        make_protocol("teaching", restraints="loose")


def test_production_restraints_legacy_and_dict():
    # legacy protocols without groups: any master scale > 0 in production means everything is restrained
    d = make_protocol("classroom").to_dict()
    d["stages"][-1]["restraint_scale"] = 0.1
    assert production_restraints(d) == {"all": 0.1}
    assert production_restraints({}) == {}


def test_schedule_sets_group_parameters():
    be = FakeBackend(n_atoms=10)
    npt = make_protocol("teaching").stage("npt")
    _apply_schedule(be, npt, 0.5)
    assert be._params["msw_restraint_scale"] == 1.0
    assert be._params["msw_rs_backbone"] == pytest.approx(0.5)
    assert be._params["msw_rs_sidechain"] == pytest.approx(0.25)
    assert be._params["msw_rs_ligand"] == pytest.approx(0.5)
    _apply_schedule(be, npt, 1.0)
    assert be._params["msw_rs_backbone"] == 0.0


def _wf(tmp_path, **md):
    cfg = copy.deepcopy(example_config())
    cfg["md"].update(md)
    return Workflow(Project.create(tmp_path, "p"), cfg)


def test_workflow_strategy_validation(tmp_path):
    assert _wf(tmp_path / "a")._restraint_strategy() == "standard"
    wf = _wf(tmp_path / "b", restraints="hold_backbone")
    assert wf._restraint_strategy() == "hold_backbone"
    with pytest.raises(WorkflowBlocked):
        _wf(tmp_path / "c", restraints="loose")._restraint_strategy()


def test_gate_option_is_one_click():
    gate = {"name": "md", "status": "NEEDS_HUMAN", "options": [f"md.restraints: {k}" for k in RESTRAINT_STRATEGIES]}
    actions, manual = gate_actions(gate, step="md_runs")
    assert not manual and len(actions) == 3
    assert actions[1]["patch"][0]["path"] == ["md", "restraints"] and actions[1]["patch"][0]["value"] == "gentle"


def test_report_flags_restrained_rmsd():
    assert _restrained_tag({"restrained_production": {}}) == ""
    assert "受約束" in _restrained_tag({"restrained_production": {"backbone": 0.05}})
