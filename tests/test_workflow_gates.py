"""Pure-python checks of workflow-level gates (WP2/WP3): no OpenMM, no Vina."""
import copy
import pytest

from md20.project.store import Project
from md20.workflow import Workflow, WorkflowBlocked, example_config

PDB = ("HETATM    1  C1  BEN A   1       0.000   0.000   0.000  1.00  0.00           C\n"
       "HETATM    2  O   HOH A   2       1.000   0.000   0.000  1.00  0.00           O\n"
       "HETATM    3  S   SO4 A   3       2.000   0.000   0.000  1.00  0.00           S\nEND\n")


def _wf(tmp_path, **over):
    cfg = copy.deepcopy(example_config())
    for k, v in over.items():
        cfg[k] = v
    return Workflow(Project.create(tmp_path, "p"), cfg)


def _raw(tmp_path):
    p = tmp_path / "raw.pdb"; p.write_text(PDB); return p


def test_cocrystal_box_requires_redock(tmp_path):
    wf = _wf(tmp_path, ligands=[{"name": "X1", "smiles": "c1ccccc1O"}])
    with pytest.raises(WorkflowBlocked, match="redocking"):
        wf.docking_preflight(_raw(tmp_path))
    wf.cfg["docking"]["skip_redock"] = True
    wf.docking_preflight(_raw(tmp_path))          # explicit consent → recorded, not blocked


def test_redock_present_passes(tmp_path):
    wf = _wf(tmp_path)
    wf.docking_preflight(_raw(tmp_path))


def test_blind_box_with_cocrystal_needs_consent(tmp_path):
    wf = _wf(tmp_path, box={})
    assert wf.cocrystal_ligands(_raw(tmp_path)) == {"BEN"}
    with pytest.raises(WorkflowBlocked, match="allow_blind"):
        wf.docking_preflight(_raw(tmp_path))
    wf.cfg["box"] = {"allow_blind": True}
    wf.docking_preflight(_raw(tmp_path))


def test_no_recommendation_blocks_pose_selection(tmp_path):
    from types import SimpleNamespace
    wf = _wf(tmp_path)
    entry = {"name": "BEN", "ligands": ["BEN"], "smiles": "C", "poses": [{"score": -5.0}], "pose_sdfs": {"BEN": ["a.sdf"]},
             "recommended_rank": None, "reason": "沒有合格候選"}
    res = SimpleNamespace(mode="independent", entries=[entry])
    with pytest.raises(WorkflowBlocked, match="沒有推薦"):
        wf.choose_poses(res)
    wf.cfg["pose_choices"] = {"BEN": 1}
    sel = wf.choose_poses(res)
    assert sel["ligands"]["BEN"]["rank"] == 1


def test_binding_raises_padding(tmp_path):
    wf = _wf(tmp_path)
    assert wf._padding_nm() >= 1.5
    wf.cfg["binding"]["enabled"] = False
    assert wf._padding_nm() == 1.0
