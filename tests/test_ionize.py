"""Ligand protonation at pH 7.4 (consultation §0.1).  Needs RDKit → openmm-stack CI.

Expected net charges are textbook pKa classes; anything near pH 7.4 must be left neutral and noted, never guessed."""
import pytest

Chem = pytest.importorskip("rdkit.Chem")

from md20.docking.ionize import ionize  # noqa: E402

CASES = [
    # (name, SMILES as a database gives it, expected net charge at pH 7.4, expected number of charged atoms)
    ("acetic acid", "CC(=O)O", -1, 1),
    ("aspirin", "CC(=O)Oc1ccccc1C(=O)O", -1, 1),
    ("ethylamine", "CCN", +1, 1),
    ("trimethylamine", "CN(C)C", +1, 1),
    ("morpholine", "C1COCCN1", +1, 1),
    ("piperazine (pKa2 5.6 → one cation)", "C1CNCCN1", +1, 1),
    ("glycine (zwitterion)", "NCC(=O)O", 0, 2),
    ("lysine", "NCCCC[C@H](N)C(=O)O", +1, 3),
    ("benzamidine", "NC(=N)c1ccccc1", +1, 1),
    ("arginine side chain (guanidine)", "CCCNC(=N)N", +1, 1),
    ("acylguanidine (not basic)", "CC(=O)NC(=N)N", 0, 0),
    ("methanesulfonic acid", "CS(=O)(=O)O", -1, 1),
    ("methyl phosphate (first OH only)", "COP(=O)(O)O", -1, 1),
    ("5-methyltetrazole", "Cc1nnn[nH]1", -1, 1),
    ("aniline", "Nc1ccccc1", 0, 0),
    ("acetamide", "CC(N)=O", 0, 0),
    ("methanesulfonamide", "CS(N)(=O)=O", 0, 0),
    ("phenol", "Oc1ccccc1", 0, 0),
    ("pyridine", "c1ccncc1", 0, 0),
    ("imidazole (pKa ~7, left neutral)", "c1c[nH]cn1", 0, 0),
    ("caffeine", "Cn1cnc2c1c(=O)n(C)c(=O)n2C", 0, 0),
    ("acetohydroxamic acid (pKa ~9)", "CC(=O)NO", 0, 0),
    ("nitrobenzene (charge-separated but neutral)", "O=[N+]([O-])c1ccccc1", 0, 2),
]


@pytest.mark.parametrize("name,smiles,net,n_charged", CASES, ids=[c[0] for c in CASES])
def test_textbook_ionisation(name, smiles, net, n_charged):
    mol, res = ionize(Chem.MolFromSmiles(smiles))
    assert Chem.GetFormalCharge(mol) == net, (name, Chem.MolToSmiles(mol), res.to_dict())
    assert sum(1 for a in mol.GetAtoms() if a.GetFormalCharge() != 0) == n_charged, (name, Chem.MolToSmiles(mol))
    assert res.net_charge_after == net


def test_explicit_charge_state_is_preserved_and_as_given_disables():
    benz = Chem.MolFromSmiles("NC(=[NH2+])c1ccccc1")              # already the cation (example_config)
    mol, res = ionize(benz)
    assert Chem.GetFormalCharge(mol) == +1 and not res.changes
    mol, res = ionize(Chem.MolFromSmiles("CCN"), mode="as_given")
    assert Chem.GetFormalCharge(mol) == 0 and res.mode == "as_given" and "使用輸入" in res.why()


def test_ambiguous_groups_are_noted_not_guessed():
    _, res = ionize(Chem.MolFromSmiles("Cc1c[nH]cn1"))
    assert not res.changes and any("imidazole" in a for a in res.ambiguous) and "不猜" in res.why()
    _, res = ionize(Chem.MolFromSmiles("CCN"), ph=4.0)              # rule set only valid near 7.4
    assert not res.changes and res.ambiguous


def test_sdf_path_keeps_heavy_atom_coordinates():
    """A 3D structure (PubChem SDF) keeps its heavy-atom coordinates; only hydrogens change."""
    from rdkit.Chem import AllChem
    from md20.docking.run import LigandInput, _ligand_mol
    import json
    import tempfile
    import numpy as np
    m = Chem.AddHs(Chem.MolFromSmiles("NCC(=O)O"))
    AllChem.EmbedMolecule(m, randomSeed=1)
    with tempfile.NamedTemporaryFile("w", suffix=".sdf", delete=False) as fh:
        w = Chem.SDWriter(fh.name); w.write(m); w.close()
        path = fh.name
    out = _ligand_mol(LigandInput(name="GLY", sdf=path))
    rec = json.loads(out.GetProp("md20_protonation"))
    assert rec["net_charge_after"] == 0 and len(rec["changes"]) == 2              # NH3+ and COO-
    heavy_in = m.GetConformer().GetPositions()[[a.GetIdx() for a in m.GetAtoms() if a.GetAtomicNum() > 1]]
    heavy_out = out.GetConformer().GetPositions()[[a.GetIdx() for a in out.GetAtoms() if a.GetAtomicNum() > 1]]
    assert np.allclose(heavy_in, heavy_out, atol=1e-4)
    assert sum(1 for a in out.GetAtoms() if a.GetAtomicNum() == 1) == 5           # NH3+ (3) + CH2 (2), no COOH H
