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
    assert wf._padding_nm(["BEN"]) >= 1.5
    assert wf._padding_nm([]) == 1.0                       # apo is never pulled from
    assert wf._padding_nm(["BEN"], screen=True) == 1.0     # nor is the short-MD pose screen
    wf.cfg["binding"]["config"] = {"pull_distance_nm": 1.8}   # the key binding actually uses
    assert wf._padding_nm(["BEN"]) == 2.3
    wf.cfg["binding"]["config"] = {"pull_distance_nm": 0.6}
    assert wf._padding_nm(["BEN"]) == 1.5                  # floor
    wf.cfg["binding"]["enabled"] = False
    assert wf._padding_nm(["BEN"]) == 1.0


# --- regression: binding/analysis must read ligand atom indices from the post-assembly records -----------------
def _manifest_as_build_case_writes_it():
    """Shape of build_manifest.json after build_case(): top-level ligands are pre-assembly records (no indices);
    the indices are inside assembly.ligands (this is what broke test_full_workflow_3ptb on Ubuntu CI)."""
    pre = {"name": "L01", "resname": "L01", "status": "PASS"}
    post = {**pre, "atom_indices": [100, 101, 102, 103], "heavy_atom_indices": [100, 102]}
    return {"ligands": [pre], "assembly": {"ligands": [post]}, "system_xml": "s.xml", "topology_pdb": "t.pdb"}


def test_manifest_ligands_prefers_assembly_records():
    from md20.workflow import manifest_ligands
    bm = _manifest_as_build_case_writes_it()
    assert manifest_ligands(bm)[0]["heavy_atom_indices"] == [100, 102]
    # legacy/pre-assembly-only manifest → records without indices (caller blocks, never guesses)
    assert not manifest_ligands({"ligands": [{"name": "L01"}]})[0].get("heavy_atom_indices")
    assert manifest_ligands({}) == []


def _binding_fixture(tmp_path, bm):
    from md20.util.jsonio import atomic_write_json
    wf = _wf(tmp_path)
    case = wf.project.new_case("p_docked_BEN")
    case.build_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(bm, case.build_dir / "build_manifest.json")
    built = {"docked_BEN": {"case_id": case.case_id, "mode": "docked_single", "ligands": ["BEN"], "ligand_map": {"BEN": "L01"}}}
    runs = {"docked_BEN": {"case_id": case.case_id, "run_ids": ["r1"]}}
    return wf, built, runs


def test_binding_uses_assembly_indices(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import md20.sampling.binding as B
    seen = {}

    def fake_run_binding(system_xml, topology_pdb, start, out_dir, *, ligand_indices, ligand_resname, **kw):
        seen.update(indices=ligand_indices, resname=ligand_resname)
        return SimpleNamespace(status="PASS", caveats=[], pmf={}, smd={}, figures={}, delta_pmf_kj_mol=-10.0,
                               dG_standard_kj_mol=None, dG_standard_kcal_mol=None)

    monkeypatch.setattr(B, "run_binding", fake_run_binding)
    wf, built, runs = _binding_fixture(tmp_path, _manifest_as_build_case_writes_it())
    out = wf.binding(runs, built, SimpleNamespace(name="CPU", properties={}))
    assert seen == {"indices": [100, 102], "resname": "L01"}
    assert out["BEN"]["status"] == "PASS"


def test_binding_blocks_without_indices(tmp_path):
    from types import SimpleNamespace
    wf, built, runs = _binding_fixture(tmp_path, {"ligands": [{"name": "L01"}], "system_xml": "s", "topology_pdb": "t"})
    with pytest.raises(WorkflowBlocked, match="原子索引"):
        wf.binding(runs, built, SimpleNamespace(name="CPU", properties={}))


def test_gbn2_protocol_and_binding_gate(tmp_path):
    """GBn2: NPT stages become NVT without density acceptance; binding is blocked; the GUI can switch back."""
    from md20.engine import make_protocol
    from md20.engine.protocol import implicit_solvent_protocol
    p = make_protocol("teaching")
    q = implicit_solvent_protocol(p)
    assert [s.ensemble for s in q.stages] == ["MIN", "NVT", "NVT", "NVT"] and [s.ensemble for s in p.stages][2] == "NPT"
    assert all("density_cv" not in (s.accept or {}) for s in q.stages)
    assert [s.restraint_scale for s in q.stages] == [s.restraint_scale for s in p.stages]   # release schedule kept
    assert p.hash() != q.hash()
    wf = _wf(tmp_path)
    wf.cfg["md"]["solvent"] = "gbn2"
    assert wf._solvent() == "gbn2" and wf._solvent(screen=True) == "gbn2"
    wf.cfg["docking"]["pose_md_screen"] = {"solvent": "explicit"}
    assert wf._solvent(screen=True) == "explicit"
    with pytest.raises(WorkflowBlocked, match="隱式溶劑"):
        wf.binding({}, {}, None)
    from md20.gui.views import gate_cards
    card = next(c for c in gate_cards(wf) if c["title"] == "implicit solvent + binding")
    assert {a["patch"][0]["path"][0] for a in card["actions"]} == {"md", "binding"}
