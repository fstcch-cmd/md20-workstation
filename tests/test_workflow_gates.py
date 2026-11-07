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
    assert wf._padding_nm([]) == 0.8                       # apo is never pulled from; teaching tier default 0.8 nm
    assert wf._padding_nm(["BEN"], screen=True) == 0.8     # nor is the short-MD pose screen
    wf.cfg["binding"]["config"] = {"pull_distance_nm": 1.8}   # the key binding actually uses
    assert wf._padding_nm(["BEN"]) == 2.3
    wf.cfg["binding"]["config"] = {"pull_distance_nm": 0.6}
    assert wf._padding_nm(["BEN"]) == 1.5                  # floor
    wf.cfg["binding"]["enabled"] = False
    assert wf._padding_nm(["BEN"]) == 0.8
    wf.cfg["md"]["tier"] = "research"
    assert wf._padding_nm([]) == 1.0
    wf.cfg["md"]["padding_nm"] = 1.2                       # explicit value always wins
    assert wf._padding_nm([]) == 1.2 and wf._padding_nm(["BEN"], screen=True) == 0.8
    assert any(r["what"] == "padding_nm" and "預設" in r["why"] for r in wf.dec.read())


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


def test_teaching_tier_runs_the_windows_it_requires(tmp_path):
    """D-41: teaching/research default to the window length their ΔG° rule requires; classroom and explicit values
    are left alone."""
    wf = _wf(tmp_path / "t")
    wf.cfg["md"]["tier"] = "teaching"
    assert wf._binding_config({}).window_prod_ps == 500.0 and wf._binding_config({}).window_equil_ps == 50.0
    assert wf._binding_config({"config": {"window_prod_ps": 80}}).window_prod_ps == 80
    wf.cfg["md"]["tier"] = "research"
    assert wf._binding_config({}).window_prod_ps == 2000.0
    wf.cfg["md"]["tier"] = "classroom"
    assert wf._binding_config({}).window_prod_ps == 50.0


def test_oversized_box_is_a_notice_not_a_block(tmp_path):
    """D-56 (REVIEW #6): a box over 40 Å is flagged in state["advisories"] and shown as a card; the run is not blocked."""
    from md20.gui.views import gate_cards
    cfg = copy.deepcopy(example_config()); cfg["box"] = {"center": [0, 0, 0], "size": [36, 51, 45]}
    wf = Workflow(Project.create(tmp_path, "p"), cfg)
    wf._box_size_notice(_raw(tmp_path))
    adv = wf.state()["advisories"]["box size"]
    assert adv["advisory"] and "51 Å" in adv["explanation"] and adv["evidence"]["grid_points"] > 1_000_000
    card = next(c for c in gate_cards(wf) if c["title"] == "box size")
    assert card["advisory"] and card["status"] == "AUTO_FIXED"
    wf.cfg["box"] = {"center": [0, 0, 0], "size": [22, 22, 22]}
    wf._box_size_notice(_raw(tmp_path))
    assert "box size" not in wf.state()["advisories"]


def _sdf(path, xyz):
    """Minimal V2000 SDF of carbons in a ring (bonds i–i+1) for the multi-ligand geometry check."""
    import numpy as np
    xyz = np.asarray(xyz, float); n = len(xyz)
    atoms = "".join(f"{x:10.4f}{y:10.4f}{z:10.4f} C   0  0  0  0  0  0  0  0  0  0  0  0\n" for x, y, z in xyz)
    bonds = "".join(f"{i + 1:3d}{(i + 1) % n + 1:3d}  1  0\n" for i in range(n))
    path.write_text(f"x\n  test\n\n{n:3d}{n:3d}  0  0  0  0  0  0  0  0999 V2000\n{atoms}{bonds}M  END\n$$$$\n")
    return str(path)


def _clash(d):
    return {"code": "geometry_repairable", "rule": "ligand_clash", "text": f"配體間 {d} Å < 3.3（碰撞）"}


def test_all_joint_poses_clashing_takes_the_least_risk_pose(tmp_path):   # D-78
    import types
    import numpy as np
    ang = np.linspace(0, 2 * np.pi, 7)[:-1]
    ring = np.c_[1.39 * np.cos(ang), 1.39 * np.sin(ang), np.zeros(6)]
    wf = _wf(tmp_path, md={"systems": ["apo", "docked_multi"], "tier": "classroom"})
    # pose 1: B's ring is threaded through A (unfixable by a nudge); pose 2: B sits 1.9 Å above A (a small nudge clears it)
    rod = np.array([[0.2, 0, -0.77], [0.2, 0, 0.77], [0.2, 0, 2.2], [0.2, 0, 3.6], [0.2, 1.4, 3.6], [0.2, 1.4, 2.2]])
    sd = {"A": [_sdf(tmp_path / "a1.sdf", ring), _sdf(tmp_path / "a2.sdf", ring)],
          "B": [_sdf(tmp_path / "b1.sdf", rod), _sdf(tmp_path / "b2.sdf", ring + [0, 0, 1.9])]}
    poses = [{"rank": 1, "score": -10.0, "clash": True, "min_ll_distance": 0.2, "rejected": ["配體間 0.2 Å < 3.3（碰撞）"],
              "rejection_codes": [_clash(0.2)]},
             {"rank": 2, "score": -9.6, "clash": True, "min_ll_distance": 1.9, "rejected": ["配體間 1.9 Å < 3.3（碰撞）"],
              "rejection_codes": [_clash(1.9)]}]
    e = {"name": "joint", "ligands": ["A", "B"], "smiles": {"A": "c1ccccc1", "B": "c1ccccc1"}, "poses": poses,
         "pose_sdfs": sd, "recommended_rank": None, "reason": "沒有任何 pose 通過保守條件，不自動選擇。"}
    sel = wf.choose_poses(types.SimpleNamespace(mode="simultaneous", entries=[e]))
    assert sel["ligands"]["A"]["rank"] == 2 and sel["ligands"]["B"]["rank"] == 2      # did not stop; lowest risk first
    rows = wf.state()["least_risk_poses"]["joint"]
    assert [r["rank"] for r in rows][0] == 2 and rows[0]["tier"] <= rows[1]["tier"]
    last = [d for d in wf.dec.read() if d["stage"] == "workflow.pose"][-1]
    assert last["kind"] == "auto_fixed" and "風險" in last["why"]


def test_failed_redocking_still_stops(tmp_path):   # D-78: the docking setup itself is not trustworthy
    import types
    wf = _wf(tmp_path)
    e = {"name": "joint", "ligands": ["A"], "poses": [{"rank": 1, "score": -5.0, "rejected": []}], "pose_sdfs": {"A": ["x"]},
         "recommended_rank": None, "reason": "Redocking 自檢未通過：RMSD 4.0 Å > 2.0 Å"}
    with pytest.raises(WorkflowBlocked):
        wf.choose_poses(types.SimpleNamespace(mode="simultaneous", entries=[e]))
