"""Peptide path (brief S1/S10): pure-Python parts + OpenMM topology gate."""
import pytest

from md20.build.peptide import clean_sequence, cpp_gate, cpp_features, net_charge, hydrophobic_moment
from md20.build.gates import PASS, AUTO_FIXED, NEEDS_HUMAN


def test_sequence_validation():
    assert clean_sequence(" kar g ") == "KARG"
    with pytest.raises(ValueError):
        clean_sequence("KXB")
    with pytest.raises(ValueError):
        clean_sequence("K")
    assert net_charge("RRKDE") == 1


def test_cpp_gate_layers():
    g, r = cpp_gate("GRKKRRQRRRPPQ", target_location=None)
    assert g.status == NEEDS_HUMAN and r["status"] == "未評估"
    g, r = cpp_gate("GAGAG", target_location="extracellular")
    assert g.status == PASS and r["status"] == "不適用"
    g, r = cpp_gate("GAGAG", target_location="intracellular", experimental_evidence="Doe 2024 J Pept Sci")
    assert g.status == PASS and r["status"] == "實驗證實"
    g, r = cpp_gate("GRKKRRQRRRPPQ", target_location="intracellular")      # TAT
    assert g.status == AUTO_FIXED and r["status"] == "計算預測" and "預測" in g.explanation and "驗證" in g.explanation
    g, r = cpp_gate("GDGSGEGA", target_location="intracellular")           # anionic, short, no R/K
    assert g.status == NEEDS_HUMAN and r["prediction"] == "不太可能穿膜"
    assert cpp_features("RRRRRRRR")["closest_known_cpp"] == "R8"
    assert hydrophobic_moment("KLALKLALKALKAALKLA") > 0.3


def test_looks_like_peptide():
    pytest.importorskip("rdkit")
    from md20.build.peptide import looks_like_peptide, peptide_smiles
    assert looks_like_peptide(peptide_smiles("GAK"))
    assert not looks_like_peptide("NC(=[NH2+])c1ccccc1")
    assert not looks_like_peptide("CC(=O)Nc1ccc(O)cc1")       # paracetamol: one amide, not a peptide


def test_topology_gate_blocks_merged_peptide():
    app = pytest.importorskip("openmm.app")
    from md20.build.peptide import topology_gate
    top = app.Topology()
    ca, cp = top.addChain("A"), top.addChain("P")
    r1 = top.addResidue("ALA", ca); a1 = top.addAtom("C", app.Element.getBySymbol("C"), r1)
    r2 = top.addResidue("GLY", cp); a2 = top.addAtom("N", app.Element.getBySymbol("N"), r2)
    ok = topology_gate(top, {"A"}, ["P"])
    assert ok.status == PASS
    top.addBond(a1, a2)                     # peptide joined to the receptor backbone
    bad = topology_gate(top, {"A"}, ["P"])
    assert bad.status == NEEDS_HUMAN and "共價鍵" in bad.gates[0].explanation
    assert topology_gate(top, {"A"}, ["P", "Q"]).status == NEEDS_HUMAN    # missing chain


def test_prepare_peptide_maps_pose_and_assigns_chain(tmp_path):
    pytest.importorskip("rdkit")
    from rdkit import Chem
    from rdkit.Chem import AllChem
    from md20.build.peptide import prepare_peptide, peptide_smiles
    m = Chem.AddHs(Chem.MolFromSmiles(peptide_smiles("GAK")))      # stands in for a docking pose SDF (no atom names)
    AllChem.EmbedMolecule(m, randomSeed=1)
    sdf = tmp_path / "pose.sdf"
    w = Chem.SDWriter(str(sdf)); w.write(m); w.close()
    rec = prepare_peptide("GAK", sdf, tmp_path, name="P01", chain_id="P")
    assert rec.status == PASS and rec.mapping == "graph" and rec.provider.startswith("amber14")
    lines = [l for l in open(rec.pdb_path) if l.startswith("ATOM")]
    assert {l[21] for l in lines} == {"P"} and lines[0][22:26].strip() == "1"
    assert {l[17:20] for l in lines} == {"GLY", "ALA", "LYS"} and any(" CA " in l for l in lines)
    bad = tmp_path / "bad.sdf"
    m2 = Chem.AddHs(Chem.MolFromSmiles(peptide_smiles("GAG"))); AllChem.EmbedMolecule(m2, randomSeed=1)
    w = Chem.SDWriter(str(bad)); w.write(m2); w.close()
    rec2 = prepare_peptide("GAK", bad, tmp_path, name="P02", chain_id="Q")
    assert rec2.status == NEEDS_HUMAN


def test_cpp_gate_suggests_redesign_for_non_penetrating():
    """A G-rich, low-charge peptide fails the gate AND must come back with concrete fixes + external predictors."""
    from md20.build.peptide import cpp_gate, cpp_redesign_suggestions, CPP_PREDICTORS
    g, rec = cpp_gate("GGGGGKP", target_location="胞內")
    assert g.status == "NEEDS_HUMAN" and rec["prediction"] == "不太可能穿膜"
    sug = rec["redesign_suggestions"]
    # the user's own ideas (shorter charged core) and cationic enrichment and a CPP conjugate
    assert sug["submotifs"] and sug["cationic"] and sug["conjugates"]
    flat = {c["sequence"] for b in sug.values() for c in b}
    assert "KP" in flat and any(s.startswith("GK") or s == "GKP" for s in flat)
    # enrichment reaches net charge >= +3; conjugates score higher than the original (score 1)
    assert all(c["net_charge"] >= 3 for c in sug["cationic"])
    assert max(c["score"] for c in sug["conjugates"]) >= 6
    # external predictor (BIOPEP-UWM named by the user) surfaced in the gate
    assert any(name == "BIOPEP-UWM" for name, _u, _d in CPP_PREDICTORS)
    assert "BIOPEP-UWM" in g.explanation and "biopep" in g.explanation.lower()
    assert len(cpp_redesign_suggestions("GGGGGKP")["conjugates"]) >= 2


def test_cpp_suggestions_empty_when_already_penetrating():
    """A strong CPP (R8) passes, so no redesign is attached."""
    from md20.build.peptide import cpp_gate
    g, rec = cpp_gate("RRRRRRRR", target_location="胞內")
    assert g.status in ("PASS", "AUTO_FIXED")
    assert "redesign_suggestions" not in rec
