"""End-to-end real case on CPU: 3PTB (bovine trypsin + benzamidine).  Needs openmm/rdkit/openff + network.

Skips cleanly when the chemistry stack or RCSB is unavailable, so it is a CI-only test.
"""
from pathlib import Path

import pytest

openmm = pytest.importorskip("openmm")
pytest.importorskip("rdkit")
pytest.importorskip("pdbfixer")
pytest.importorskip("openff.toolkit")

from md20.project import Project
from md20.build.pipeline import build_case
from md20.engine import make_protocol, run_protocol, OpenMMBackend
from md20.env import choose_platform
from md20.report import build_run_report


def test_3ptb_build_and_short_md(pdb_3ptb, tmp_path):
    proj = Project.create(tmp_path, "ci")
    case = proj.new_case("trypsin_benzamidine")
    s = build_case(case, receptor=pdb_3ptb, ligand_references=["NC(=[NH2+])c1ccccc1"], cocrystal_resnames=["BEN"],
                   keep_hetero=set(), padding_nm=0.8, run_smoke_test=True)
    assert s["status"] == "PASS", (s.get("blocking"), s.get("blocking_detail"))
    lig = s["ligands"][0]
    assert lig["mapping"] in {"substructure", "order"} and lig["formal_charge"] == 1
    assert lig["provider"] == "openff-sage", lig
    assert lig["smoke_test"]["ok"], lig["smoke_test"]
    asm = s["assembly"]
    assert abs(asm["total_charge"]) < 0.05 and asm["n_ligand_atoms"] == 18 and asm["n_waters"] > 1000
    # short MD on the best platform available (CPU in CI)
    choice = choose_platform(probe_steps=20)
    proto = make_protocol("classroom")
    for st in proto.stages:
        if st.ensemble != "MIN":
            st.length_ps = 6.0; st.checkpoint_interval_ps = 3.0; st.report_interval_ps = 0.1; st.trajectory_interval_ps = 1.0
            st.accept = {}
        else:
            st.max_iterations = 500
    def make(spec, dt):
        return OpenMMBackend(s["system_xml"], s["topology_pdb"], platform_name=choice.name, platform_properties=choice.properties,
                             timestep_fs=dt, temperature_k=spec.temperature_k, ensemble=spec.ensemble,
                             pressure_bar=spec.pressure_bar, hmr=proto.hmr, seed=spec.seed)
    run = case.new_run(proto.to_dict())
    st = run_protocol(run.dir, proto, make, identity={"case_id": case.case_id, "run_id": run.run_id},
                      decisions=proj.decisions, max_extensions=0)
    assert st["status"] == "COMPLETE"
    rep = build_run_report(run)
    html = rep.read_text(encoding="utf-8")
    assert "ff14SB" in html and "openff" in html.lower() and "co-crystal" in html


def test_3ptb_with_peptide_on_own_chain(pdb_3ptb, tmp_path):
    """Peptide built with ff14SB on a free chain, placed outside the protein; must not join the receptor."""
    import numpy as np
    from rdkit import Chem
    from rdkit.Chem import AllChem
    from md20.build.peptide import peptide_smiles
    txt = Path(pdb_3ptb).read_text()
    ca = np.array([[float(l[30:38]), float(l[38:46]), float(l[46:54])] for l in txt.splitlines() if l.startswith("ATOM") and l[12:16] == " CA "])
    m = Chem.AddHs(Chem.MolFromSmiles(peptide_smiles("GAK"))); AllChem.EmbedMolecule(m, randomSeed=3)
    conf = m.GetConformer()
    shift = np.array([ca[:, 0].max() + 8.0, ca[:, 1].mean(), ca[:, 2].mean()]) - conf.GetPositions().mean(0)
    for i in range(m.GetNumAtoms()):
        p = conf.GetAtomPosition(i); conf.SetAtomPosition(i, (p.x + shift[0], p.y + shift[1], p.z + shift[2]))
    sdf = tmp_path / "pep.sdf"; w = Chem.SDWriter(str(sdf)); w.write(m); w.close()
    proj = Project.create(tmp_path, "pep")
    case = proj.new_case("trypsin_peptide")
    s = build_case(case, receptor=pdb_3ptb, ligand_references=[], keep_hetero=set(), padding_nm=0.8, extra_ligand_resnames={"BEN"},
                   peptides=[{"name": "P01", "sequence": "GAK", "pose": str(sdf), "target_location": "extracellular"}])
    assert s["status"] == "PASS", (s.get("blocking"), s.get("blocking_detail"))
    pep = s["ligands"][0]
    assert pep["kind"] == "peptide" and pep["cpp"]["status"] == "不適用"
    gates = {g["name"]: g["status"] for g in s["assembly"]["gates"]["gates"]}
    assert gates.get("peptide topology") == "PASS"
    assert len(s["assembly"]["ligands"][0]["heavy_atom_indices"]) == Chem.MolFromSequence("GAK").GetNumHeavyAtoms()
