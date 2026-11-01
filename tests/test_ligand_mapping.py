"""REVIEW #16: pose → reference mapping must follow the bond graph, never an element-order coincidence.

Needs RDKit (openmm-stack CI)."""
import numpy as np
import pytest

Chem = pytest.importorskip("rdkit.Chem")
from rdkit.Chem import AllChem  # noqa: E402

from md20.build.ligand import map_pose_onto_reference  # noqa: E402


def _xyz_pose(mol_h, order):
    """Heavy atoms of an embedded molecule, written as a bond-less XYZ block in the given atom order."""
    heavy = Chem.RemoveHs(mol_h)
    conf = heavy.GetConformer()
    lines = [str(len(order)), ""]
    for i in order:
        p = conf.GetAtomPosition(i)
        lines.append(f"{heavy.GetAtomWithIdx(i).GetSymbol()} {p.x:.4f} {p.y:.4f} {p.z:.4f}")
    return Chem.MolFromXYZBlock("\n".join(lines)), heavy


def _embedded(smiles, seed=7):
    m = Chem.AddHs(Chem.MolFromSmiles(smiles))
    AllChem.EmbedMolecule(m, randomSeed=seed)
    return m


def test_shuffled_pose_without_bond_orders_maps_by_graph():
    ref = Chem.AddHs(Chem.MolFromSmiles("NC(=[NH2+])c1ccccc1"))         # benzamidine
    pose_src = _embedded("NC(=[NH2+])c1ccccc1")
    n = pose_src.GetNumHeavyAtoms()
    order = list(np.random.default_rng(3).permutation(n))
    pose, heavy = _xyz_pose(pose_src, order)
    match, method, problems = map_pose_onto_reference(ref, pose)
    assert match is not None, problems
    assert method in ("substructure", "connectivity")
    # every reference heavy atom lands on a pose atom of the same element
    ref_heavy = Chem.RemoveHs(ref)
    assert all(ref_heavy.GetAtomWithIdx(i).GetAtomicNum() == pose.GetAtomWithIdx(j).GetAtomicNum() for i, j in enumerate(match))


def test_same_element_order_but_different_connectivity_is_rejected():
    """Ethanol (C–C–O) reference vs a dimethyl-ether pose (C–O–C) written in the element order C, C, O."""
    ref = Chem.AddHs(Chem.MolFromSmiles("CCO"))
    ether = _embedded("COC")                                          # heavy atoms: C0, O1, C2
    pose, _ = _xyz_pose(ether, [0, 2, 1])                             # element order C, C, O — same as ethanol
    assert [a.GetSymbol() for a in pose.GetAtoms()] == ["C", "C", "O"]
    match, method, problems = map_pose_onto_reference(ref, pose)
    assert match is None and method == "", (match, method)            # the old 'order' fallback accepted this
    assert any("連接" in p for p in problems), problems
