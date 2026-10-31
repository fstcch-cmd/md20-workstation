"""Real docking on CI: redocking validation and simultaneous mode (needs vina + meeko + rdkit + pdbfixer)."""
from pathlib import Path

import pytest

pytest.importorskip("vina")
pytest.importorskip("meeko")
pytest.importorskip("pdbfixer")

from md20.build.receptor import prepare_receptor
from md20.docking import dock, LigandInput, box_from_pdb_residue
from md20.util import DecisionLog

BEN = "NC(=[NH2+])c1ccccc1"


@pytest.fixture(scope="module")
def trypsin(pdb_3ptb, tmp_path_factory):
    d = tmp_path_factory.mktemp("rec")
    man = prepare_receptor(pdb_3ptb, d, keep_hetero=set(), ligand_resnames={"BEN"})
    assert man["status"] != "NEEDS_HUMAN", man["gates"]
    return Path(man["receptor_pdb"]), box_from_pdb_residue(pdb_3ptb, "BEN")


def test_redocking_benzamidine(trypsin, pdb_3ptb, tmp_path):
    rec, box = trypsin
    dec = DecisionLog(tmp_path / "d.jsonl")
    res = dock(rec, [LigandInput("BEN", smiles=BEN, reference_pose=str(_ref(pdb_3ptb, tmp_path)))], box, tmp_path / "dock",
               exhaustiveness=8, n_poses=9, decisions=dec)
    e = res.entry("BEN")
    best = e["poses"][0]
    assert best["score"] < -4.0, e["poses"]
    rec_pose = next(p for p in e["poses"] if p["recommended"])
    assert rec_pose["rmsd_ref"] is not None and rec_pose["rmsd_ref"] < 2.0, e   # redocking reproduces crystal pose
    assert rec_pose["contacts"] >= 10 and "kcal/mol" in e["reason"]
    assert Path(e["pose_sdfs"]["BEN"][0]).is_file()
    assert (tmp_path / "dock" / "docking_scores.csv").is_file()


def test_simultaneous_two_ligands(trypsin, tmp_path):
    rec, box = trypsin
    box.size = (24.0, 24.0, 24.0)
    res = dock(rec, [LigandInput("BEN", smiles=BEN), LigandInput("PHL", smiles="Oc1ccccc1")], box, tmp_path / "sim",
               mode="simultaneous", exhaustiveness=8, n_poses=5)
    e = res.entry("joint")
    assert e["ligands"] == ["BEN", "PHL"] and len(e["pose_sdfs"]["BEN"]) == len(e["pose_sdfs"]["PHL"])
    pick = next(p for p in e["poses"] if p["recommended"])
    assert not pick["clash"] and pick["min_ll_distance"] is not None


def _ref(pdb_3ptb, tmp_path):
    from md20.build import extract_hetatm_pose
    return extract_hetatm_pose(Path(pdb_3ptb).read_text(), "BEN", tmp_path / "ben_ref.pdb")
