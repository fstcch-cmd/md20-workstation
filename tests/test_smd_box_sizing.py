"""D-99: a case that will be pulled is sized at build time by the SAME rule the SMD step checks, with OpenMM's real
box formula (width = 2R + padding — padding is added once).  Reported failure (user 11/07): the GRP teaching case
(peptide on Keap1) was built too small and SMD stopped with "水盒太小"."""
import numpy as np
import pytest

from md20.build.assemble import smd_padding_plan, smd_box_gate
from md20.build.gates import PASS, AUTO_FIXED, NEEDS_HUMAN
from md20.sampling.binding import (padding_for_half_box, pocket_anchor, smd_half_box_need, solute_radius_nm,
                                   BindingConfig)


def openmm_half_box(R, p):
    """OpenMM 8.6.1 modeller.addSolvent(padding=…): width = max(2R + p, 2p); every box vector has length = width."""
    return max(2 * R + p, 2 * p) / 2


@pytest.mark.parametrize("R,H", [(2.2, 4.6), (2.2, 2.0), (0.5, 4.0), (3.0, 3.0), (1.0, 2.0), (0.0, 1.5)])
def test_padding_for_half_box_is_minimal_and_sufficient(R, H):
    p = padding_for_half_box(R, H)
    assert openmm_half_box(R, p) >= H - 1e-9
    if p > 1e-6:
        assert openmm_half_box(R, p - 0.01) < H


def test_padding_is_added_once_not_twice():
    """Correction of the old comments: padding 2.0 nm on a 2.2 nm protein gives half box 3.2, not 4.2."""
    assert openmm_half_box(2.2, 2.0) == pytest.approx(3.2)


def _protein(R=2.2, n=400, seed=0):
    rng = np.random.default_rng(seed)
    v = rng.normal(size=(n, 3))
    v /= np.linalg.norm(v, axis=1)[:, None]
    return v * R * rng.uniform(0.6, 1.0, size=(n, 1))


def _grp_like():
    """A 2.2 nm protein (all atoms are 'CA') and an extended 7-residue peptide lying on its surface (radius ~1 nm)."""
    prot = _protein()
    t = np.linspace(-1.0, 1.0, 21)[:, None]
    pep = np.array([0.0, 0.0, 2.45]) + t * np.array([1.0, 0.0, 0.0])
    xyz = np.vstack([prot, pep])
    ca = np.arange(len(prot))
    lig = np.arange(len(prot), len(xyz))
    return xyz, np.full(len(xyz), 12.0), ca, lig


def test_grp_like_case_old_rule_fails_the_smd_check_new_rule_passes():
    xyz, m, ca, lig = _grp_like()
    cfg = BindingConfig()
    anc, _ = pocket_anchor(xyz, ca, lig)
    need = smd_half_box_need(xyz, None, anc, lig, m, pull_nm=cfg.pull_distance_nm, margin_nm=cfg.box_margin_nm)
    R = solute_radius_nm(xyz)
    old_pad = max(1.5, min(cfg.pull_distance_nm + 0.5, 2.5))            # workflow._padding_nm before D-99
    assert openmm_half_box(R, old_pad) < need["need_half_box_nm"]       # the reported failure, reproduced
    plan = smd_padding_plan(xyz, m, ca, {"GRP": lig}, old_pad, pull_nm=cfg.pull_distance_nm,
                            margin_nm=cfg.box_margin_nm, allowance_nm=0.5, shape="dodecahedron")
    assert plan["status"] == AUTO_FIXED and plan["padding_nm"] > old_pad
    assert openmm_half_box(R, plan["padding_nm"]) >= need["need_half_box_nm"] + 0.5 - 1e-6
    g = smd_box_gate(plan, pull_nm=cfg.pull_distance_nm, margin_nm=cfg.box_margin_nm)
    assert g.status == AUTO_FIXED and g.diff and "padding_nm" in g.diff[0] and "計算量" in g.explanation
    assert plan["evidence"]["volume_nm3_after"] > plan["evidence"]["volume_nm3_before"]


def test_buried_small_ligand_keeps_the_requested_padding():
    prot = _protein(R=3.0)
    lig_xyz = np.array([[0.0, 0.0, 0.0], [0.15, 0.0, 0.0], [0.0, 0.15, 0.0]])      # small, at the centre
    xyz = np.vstack([prot, lig_xyz])
    ca, lig = np.arange(len(prot)), np.arange(len(prot), len(xyz))
    # put a few CA near the centre so the pocket anchor exists
    xyz[:6] = [[0.5, 0, 0], [-0.5, 0, 0], [0, 0.5, 0], [0, -0.5, 0], [0, 0, 0.5], [0, 0, -0.5]]
    plan = smd_padding_plan(xyz, np.full(len(xyz), 12.0), ca, {"L": lig}, 2.0, pull_nm=1.5, margin_nm=1.0,
                            allowance_nm=0.5, shape="dodecahedron")
    assert plan["status"] == PASS and plan["padding_nm"] == 2.0


def test_no_pocket_anchor_blocks_instead_of_guessing():
    prot = _protein()
    far = np.array([[9.0, 9.0, 9.0], [9.1, 9.0, 9.0]])
    xyz = np.vstack([prot, far])
    plan = smd_padding_plan(xyz, np.full(len(xyz), 12.0), np.arange(len(prot)), {"X": [len(prot), len(prot) + 1]}, 2.0,
                            pull_nm=1.5, margin_nm=1.0, allowance_nm=0.5, shape="dodecahedron")
    assert plan["status"] == NEEDS_HUMAN and plan["padding_nm"] == 2.0
    assert smd_box_gate(plan, pull_nm=1.5, margin_nm=1.0).status == NEEDS_HUMAN


def test_pocket_anchor_matches_the_previous_select_groups_rule():
    xyz, _, ca, lig = _grp_like()
    sel, used = pocket_anchor(xyz, ca, lig)
    d = np.min(np.linalg.norm(xyz[ca][:, None] - xyz[lig][None], axis=2), axis=1)
    assert set(sel) == set(ca[d <= used + 1e-9]) and len(sel) >= 4


def test_workflow_checks_every_ligand_case_and_sets_the_mode(tmp_path):
    """General rule: every ligand case is checked; enforce when SMD is planned, advise when it may come later."""
    from md20.project.store import Project
    from md20.workflow import Workflow, example_config
    cfg = example_config()
    cfg["binding"] = {"enabled": True, "ligands": ["BEN"], "config": {"pull_distance_nm": 2.0}}
    wf = Workflow(Project.create(tmp_path, "p"), cfg)
    assert wf._smd_box(["BEN"]) == {"pull_nm": 2.0, "margin_nm": 1.0, "allowance_nm": 0.5, "ligands": ["BEN"], "mode": "enforce"}
    assert wf._smd_box(["BEN"], screen=True) is None and wf._smd_box([]) is None
    wf.cfg["binding"]["enabled"] = False
    assert wf._smd_box(["BEN"])["mode"] == "advise"                  # not planned now — still checked
    wf.cfg["md"]["box_for_smd"] = "always"
    assert wf._smd_box(["BEN"])["mode"] == "enforce"
    wf.cfg["md"]["box_for_smd"] = "never"
    assert wf._smd_box(["BEN"]) is None


def _plan(pad, mode, R=2.2):
    from md20.build.assemble import apply_smd_mode
    xyz, m, ca, lig = _grp_like()
    p = smd_padding_plan(xyz, m, ca, {"GRP": lig}, pad, pull_nm=1.5, margin_nm=1.0, allowance_nm=0.5, shape="dodecahedron")
    return apply_smd_mode(p, mode, pad)


def test_advise_mode_keeps_an_expensive_box_and_warns_before_md():
    plan = _plan(2.0, "advise")
    assert plan["status"] == "ADVISE_TOO_COSTLY" and plan["padding_nm"] == 2.0
    g = smd_box_gate(plan, pull_nm=1.5, margin_nm=1.0)
    assert g.status == PASS and g.advisory and g.limitation["padding_required_nm"] > 2.0
    assert any(o.startswith("md.box_for_smd: always") for o in g.options) and "現在" in g.explanation


def test_advise_mode_enlarges_when_cheap():
    plan = _plan(4.0, "advise")            # 4.0 → ~4.2: a few percent more water
    assert plan["status"] == AUTO_FIXED and plan.get("proactive") and plan["evidence"]["cost_factor"] <= 1.5
    g = smd_box_gate(plan, pull_nm=1.5, margin_nm=1.0)
    assert g.status == AUTO_FIXED and "沒有排 SMD" in g.explanation


def test_advise_mode_never_blocks_without_anchor():
    from md20.build.assemble import apply_smd_mode
    prot = _protein()
    xyz = np.vstack([prot, [[9.0, 9.0, 9.0], [9.1, 9.0, 9.0]]])
    p = smd_padding_plan(xyz, np.full(len(xyz), 12.0), np.arange(len(prot)), {"X": [len(prot), len(prot) + 1]}, 2.0,
                         pull_nm=1.5, margin_nm=1.0, allowance_nm=0.5, shape="dodecahedron")
    g = smd_box_gate(apply_smd_mode(p, "advise", 2.0), pull_nm=1.5, margin_nm=1.0)
    assert g.status == PASS and g.advisory


def test_box_for_smd_options_are_one_click():
    from md20.gui.actions import gate_actions
    g = smd_box_gate(_plan(2.0, "advise"), pull_nm=1.5, margin_nm=1.0).to_dict()
    acts, _ = gate_actions(g, step="md_cases")
    paths = [a["patch"][0]["path"] for a in acts]
    assert ["md", "box_for_smd"] in paths and ["md", "padding_nm"] in paths
