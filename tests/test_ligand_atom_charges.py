"""D-98: atom-level ligand charges from the build record reach the interaction fingerprint, so a salt bridge can be
called on the ligand side — and is still NOT called whenever the charges are missing, misaligned or remapped away.
Resonance delocalisation (carboxylate: both O) is a pure function tested here; the RDKit wrapper is tested where
RDKit exists (CI openmm-stack)."""
import numpy as np
import pytest

from md20.analysis import interactions as IX
from md20.analysis.stream import remap_charges
from md20.build.ligand import LigandRecord, resonance_charge_signs
from md20.workflow import manifest_ligand_charges


# ------------------------------------------------------------------ resonance (pure)
def test_carboxylate_charge_is_shared_by_both_oxygens():
    # acetate heavy atoms: 0 C(methyl) 1 C 2 O(=) 3 O(-); second resonance form moves the charge to atom 2
    signs, method = resonance_charge_signs(4, [0, 0, 0, -1], [[0, 0, -1, 0]])
    assert signs == [0, 0, -1, -1]
    assert "resonance" in method


def test_conflicting_signs_across_forms_keep_input_sign_and_are_reported():
    signs, method = resonance_charge_signs(3, [1, 0, -1], [[-1, 0, 1]])
    assert signs == [1, 0, -1]
    assert "opposite signs" in method


def test_resonance_form_of_wrong_length_is_ignored():
    signs, _ = resonance_charge_signs(2, [0, -1], [[-1, 0, 0]])
    assert signs == [0, -1]


def test_ligand_record_carries_the_new_fields_with_safe_defaults():
    d = LigandRecord(name="L01", resname="L01").to_dict()
    assert d["atom_formal_charges"] == [] and d["atom_charge_signs"] == [] and d["atom_charge_method"] == ""


# ------------------------------------------------------------------ manifest → {name: {topology index: sign}}
def _bm(**lig):
    base = {"name": "L01", "atom_indices": [100, 101, 102, 103], "heavy_atom_indices": [100, 101, 102, 103]}
    return {"assembly": {"ligands": [{**base, **lig}]}}


def test_manifest_prefers_resonance_signs_and_maps_to_topology_indices():
    bm = _bm(atom_formal_charges=[0, 0, 0, -1], atom_charge_signs=[0, 0, -1, -1])
    assert manifest_ligand_charges(bm) == {"L01": {102: -1, 103: -1}}


def test_manifest_falls_back_to_formal_charges():
    assert manifest_ligand_charges(_bm(atom_formal_charges=[1, 0, 0, 0])) == {"L01": {100: 1}}


def test_known_neutral_ligand_is_empty_dict_not_absent():
    assert manifest_ligand_charges(_bm(atom_formal_charges=[0, 0, 0, 0])) == {"L01": {}}


@pytest.mark.parametrize("lig", [
    {},                                                     # manifest before D-98: no charges recorded
    {"atom_formal_charges": [0, -1]},                       # length disagrees with the topology → order not trusted
    {"atom_formal_charges": [0, 0, 0, -1], "kind": "peptide"},
    {"atom_formal_charges": [0, 0, 0, -1], "atom_indices": []},
])
def test_charge_left_unknown_rather_than_guessed(lig):
    assert manifest_ligand_charges(_bm(**lig)) == {}


def test_pre_assembly_manifest_without_indices_gives_unknown():
    assert manifest_ligand_charges({"ligands": [{"name": "L01", "atom_formal_charges": [0, -1]}]}) == {}


# ------------------------------------------------------------------ solute-only remap
def test_remap_keeps_ligand_when_all_charged_atoms_survive():
    assert remap_charges({"L01": {102: -1, 103: -1}}, [5, 102, 103]) == {"L01": {1: -1, 2: -1}}


def test_remap_drops_ligand_that_loses_a_charged_atom():
    """Losing one O of a carboxylate must not quietly make the ligand 'half charged'."""
    assert remap_charges({"L01": {102: -1, 103: -1}, "L02": {}}, [102]) == {"L02": {}}


def test_remap_passthrough_without_subset():
    c = {"L01": {1: 1}}
    assert remap_charges(c, None) is c and remap_charges(None, [1]) is None


# ------------------------------------------------------------------ end to end: the partner oxygen makes a salt bridge
def _atoms():
    return {0: {"element": "C"}, 1: {"element": "C"}, 2: {"element": "O"}, 3: {"element": "O"},
            10: {"element": "N", "resname": "LYS", "name": "NZ", "res_key": IX.residue_key("A", "LYS", 60)}}


def test_partner_oxygen_of_carboxylate_forms_salt_bridge_only_with_delocalised_signs():
    X = np.full((1, 11, 3), 50.0)
    X[0, :4] = [[0.3, 0, 0], [0.15, 0, 0], [0, 0, 0], [0.2, 0.12, 0]]
    X[0, 10] = [-0.3, 0, 0]                                 # LYS NZ 3.0 Å from atom 2 (the O WITHOUT the formal −1)
    dyn = IX.dynamic_pairs(X, [0, 1, 2, 3], [10])
    raw = manifest_ligand_charges(_bm(atom_indices=[0, 1, 2, 3], atom_formal_charges=[0, 0, 0, -1]))["L01"]
    deloc = manifest_ligand_charges(_bm(atom_indices=[0, 1, 2, 3], atom_formal_charges=[0, 0, 0, -1],
                                        atom_charge_signs=[0, 0, -1, -1]))["L01"]
    assert IX.fingerprint(dyn, _atoms(), ligand_charges=raw)["occupancy"]["salt_bridge"] == {}
    assert IX.fingerprint(dyn, _atoms(), ligand_charges=deloc)["occupancy"]["salt_bridge"] == {"A:LYS60": 1.0}
    unknown = IX.fingerprint(dyn, _atoms(), ligand_charges=manifest_ligand_charges(_bm()).get("L01"))
    assert unknown["occupancy"]["salt_bridge"] == {} and unknown["occupancy"]["charged_proximity_ligand_charge_unknown"]


# ------------------------------------------------------------------ RDKit wrapper (CI openmm-stack)
def test_rdkit_acetate_and_neutral_molecule():
    Chem = pytest.importorskip("rdkit.Chem")
    from md20.build.ligand import charged_group_signs
    ac = Chem.MolFromSmiles("CC(=O)[O-]")
    signs, method = charged_group_signs(ac)
    o = [a.GetIdx() for a in ac.GetAtoms() if a.GetSymbol() == "O"]
    assert [signs[i] for i in o] == [-1, -1], method
    assert sum(1 for s in signs if s) == 2
    amm = Chem.AddHs(Chem.MolFromSmiles("CC[NH3+]"))
    s2, _ = charged_group_signs(amm)
    assert [a.GetSymbol() for a in amm.GetAtoms() if s2[a.GetIdx()]] == ["N"]
    neutral, m3 = charged_group_signs(Chem.MolFromSmiles("CC(=O)O"))
    assert not any(neutral) and "no formal charges" in m3


# ------------------------------------------------------------------ workflow → analyse_run wiring
def test_workflow_analyse_passes_manifest_charges_to_analysis(tmp_path, monkeypatch):
    import copy
    from md20.project.store import Project
    from md20.util.jsonio import atomic_write_json
    from md20.workflow import Workflow, example_config
    cfg = copy.deepcopy(example_config())
    cfg["md"].pop("membrane", None)
    wf = Workflow(Project.create(tmp_path, "p"), cfg)
    case = wf.project.new_case("c")
    case.build_dir.mkdir(parents=True, exist_ok=True)
    lig = {"name": "L01", "atom_indices": [7, 8, 9], "heavy_atom_indices": [7, 8, 9],
           "atom_formal_charges": [0, 0, -1], "atom_charge_signs": [0, -1, -1]}
    atomic_write_json({"topology_pdb": "t.pdb", "assembly": {"ligands": [lig]}}, case.build_dir / "build_manifest.json")
    seen = {}

    def fake(run_dir, top, **kw):
        seen.update(kw)
        (run_dir / "analysis").mkdir(parents=True, exist_ok=True)
        atomic_write_json({"n_frames": 1}, run_dir / "analysis" / "metrics.json")
        return {"status": "PASS", "metrics_file": str(run_dir / "analysis" / "metrics.json")}
    monkeypatch.setattr("md20.analysis.traj.analyse_run", fake)
    wf.analyse({"complex": {"case_id": case.case_id, "run_ids": ["r1"]}})
    assert seen["ligand_charges"] == {"L01": {8: -1, 9: -1}}
    assert seen["ligand_groups"] == {"L01": [7, 8, 9]}
