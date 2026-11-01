from md20.build.structure_gate import structure_confidence, header_info

HDR = """EXPDTA    X-RAY DIFFRACTION
REMARK   2 RESOLUTION.    {res} ANGSTROMS.
REMARK   3   FREE R VALUE                     : {rf}
"""


def _atom(i, name, resn, chain, seq, x, y, z, occ=1.0, b=20.0, het=False):
    rec = "HETATM" if het else "ATOM  "
    return f"{rec}{i:5d} {name:<4} {resn:>3} {chain}{seq:4d}    {x:8.3f}{y:8.3f}{z:8.3f}{occ:6.2f}{b:6.2f}\n"


def _pdb(res=1.8, rf=0.22, lig_occ=1.0, pocket_occ=1.0, metal=None):
    s = HDR.format(res=res, rf=rf)
    for k in range(20):
        s += _atom(k + 1, "CA", "ALA", "A", k + 1, 3.0 + 0.1 * k, 0.0, 0.0, occ=pocket_occ)
    s += _atom(30, "C1", "LIG", "A", 300, 0.0, 0.0, 0.0, occ=lig_occ, het=True)
    if metal:
        s += _atom(31, metal, metal, "A", 301, 2.0, 0.0, 0.0, het=True)
    return s + "END\n"


def _st(rep, name):
    return [g.status for g in rep.gates if g.name == name]


def test_header():
    h = header_info(_pdb(2.1, 0.25))
    assert h["resolution_A"] == 2.1 and h["r_free"] == 0.25 and "X-RAY" in h["method"]


def test_good_structure_passes():
    rep = structure_confidence(_pdb(), ligand_resname="LIG")
    assert rep.status == "PASS", rep.to_markdown()


def test_bad_resolution_rfree_occupancy_block():
    assert _st(structure_confidence(_pdb(res=3.6), ligand_resname="LIG"), "resolution") == ["NEEDS_HUMAN"]
    assert _st(structure_confidence(_pdb(rf=0.35), ligand_resname="LIG"), "R-free") == ["NEEDS_HUMAN"]
    assert _st(structure_confidence(_pdb(lig_occ=0.5), ligand_resname="LIG"), "ligand occupancy") == ["NEEDS_HUMAN"]
    assert _st(structure_confidence(_pdb(pocket_occ=0.3), ligand_resname="LIG"), "pocket occupancy") == ["NEEDS_HUMAN"]


def test_metal_in_pocket():
    assert _st(structure_confidence(_pdb(metal="ZN"), ligand_resname="LIG"), "metal") == ["NEEDS_HUMAN"]
    assert _st(structure_confidence(_pdb(metal="ZN"), ligand_resname="LIG", metal_policy={"ZN": "keep_nonbonded"}),
               "metal") == ["AUTO_FIXED"]
    assert _st(structure_confidence(_pdb(metal="MG"), ligand_resname="LIG"), "metal") == ["AUTO_FIXED"]


def test_3ptb_is_trusted(pdb_3ptb):
    rep = structure_confidence(pdb_3ptb.read_text(), ligand_resname="BEN")
    assert rep.status != "NEEDS_HUMAN", rep.to_markdown()
    assert header_info(pdb_3ptb.read_text())["resolution_A"] < 2.0
