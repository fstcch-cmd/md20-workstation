"""Receptor inspection + gates run without any chemistry dependency."""
from md20.build.receptor import inspect_pdb_text, gate_inspection, COFACTOR_KEEP_DEFAULT
from md20.build.gates import PASS, AUTO_FIXED, NEEDS_HUMAN, GateReport, Gate


def _atom(serial, name, resname, chain, resid, x=0.0, rec="ATOM", altloc=" ", icode=" ", element=None):
    element = element if element is not None else name[0]
    return (f"{rec:<6}{serial:>5} {name:<4}{altloc}{resname:>3} {chain}{resid:>4}{icode}   "
            f"{x:8.3f}{0.0:8.3f}{0.0:8.3f}{1.0:6.2f}{0.0:6.2f}          {element:>2}")


def _protein(n=5, chain="A", start=1, gap_after=None, gap_len=0, numbering_only=False):
    """CA atoms placed 3.8 Å apart along x per *physical* residue; a gap adds physical distance unless numbering_only."""
    lines = []
    serial = 1
    resid = start
    pos = 0
    for i in range(n):
        for name in ("N", "CA", "C", "O"):
            lines.append(_atom(serial, name, "ALA", chain, resid, x=3.8 * pos)); serial += 1
        resid += 1
        pos += 1
        if gap_after is not None and i == gap_after:
            resid += gap_len
            if not numbering_only:
                pos += gap_len
    return lines, serial


def test_clean_protein_passes():
    lines, _ = _protein(5)
    insp = inspect_pdb_text("\n".join(lines))
    assert insp.ca_count == 5 and insp.chains == {"A": 5} and not insp.gaps
    rep = gate_inspection(insp, keep_hetero=COFACTOR_KEEP_DEFAULT)
    assert rep.status == PASS and rep.ok


def test_docking_damaged_pdb_is_flagged():
    lines, serial = _protein(4)
    # docking-style ligand with no element column, LIG name, duplicate atom names, hydrogens
    lines.append(_atom(serial, "C1", "LIG", "A", 1, rec="HETATM", element=""))
    lines.append(_atom(serial + 1, "C1", "LIG", "A", 1, rec="HETATM", element=""))
    lines.append(_atom(serial + 2, "H", "LIG", "A", 1, rec="HETATM", element="H"))
    lines.append(_atom(serial + 3, "O", "HOH", "W", 1, rec="HETATM"))
    lines.append(_atom(serial + 4, "SE", "MSE", "A", 9, element="SE"))
    insp = inspect_pdb_text("\n".join(lines))
    assert insp.missing_element_column == 2 and insp.hydrogens == 1 and insp.waters == 1
    assert insp.hetero_residues == {"LIG": 1} and insp.nonstandard_residues == {"MSE": 1}
    assert insp.duplicate_atom_names and insp.duplicate_atom_names[0]["atoms"] == ["C1"]
    rep = gate_inspection(insp, keep_hetero=COFACTOR_KEEP_DEFAULT)
    names = {g.name: g.status for g in rep.gates}
    assert names["hetero groups"] == NEEDS_HUMAN
    assert names["duplicate atom names"] == NEEDS_HUMAN
    assert names["nonstandard residues"] == AUTO_FIXED
    assert names["existing hydrogens"] == AUTO_FIXED
    assert rep.status == NEEDS_HUMAN
    md = rep.to_markdown()
    assert "⛔" in md and "選項" in md


def test_long_gap_needs_human_short_gap_auto():
    lines, _ = _protein(6, gap_after=2, gap_len=3)     # 3 missing residues → auto
    rep = gate_inspection(inspect_pdb_text("\n".join(lines)), keep_hetero=set())
    assert {g.name: g.status for g in rep.gates}["missing loops (short)"] == AUTO_FIXED
    lines, _ = _protein(6, gap_after=2, gap_len=12)    # 12 missing → human
    rep = gate_inspection(inspect_pdb_text("\n".join(lines)), keep_hetero=set())
    g = {g.name: g for g in rep.gates}["missing loops (long)"]
    assert g.status == NEEDS_HUMAN and "AlphaFold" in " ".join(g.options)


def test_serial_overflow_and_cofactor():
    lines, serial = _protein(3)
    lines.append(_atom(serial, "FE", "HEM", "A", 200, rec="HETATM", element="FE").replace(f"{serial:>5}", "*****"))
    insp = inspect_pdb_text("\n".join(lines))
    assert insp.serial_overflow
    rep = gate_inspection(insp, keep_hetero=COFACTOR_KEEP_DEFAULT)
    names = {g.name: g.status for g in rep.gates}
    assert names["cofactors kept"] == PASS and names["atom serial"] == AUTO_FIXED


def test_gate_report_status_precedence():
    rep = GateReport([Gate("a", PASS), Gate("b", AUTO_FIXED)])
    assert rep.status == AUTO_FIXED and rep.ok
    rep.add(Gate("c", NEEDS_HUMAN, options=["x"]))
    assert rep.status == NEEDS_HUMAN and not rep.ok and rep.blocking[0].name == "c"


def test_cocrystal_ligand_and_junk_are_auto_handled():
    lines, serial = _protein(4)
    lines.append(_atom(serial, "C1", "BEN", "A", 300, rec="HETATM", element="C"))
    lines.append(_atom(serial + 1, "S", "SO4", "A", 301, rec="HETATM", element="S"))
    lines.append(_atom(serial + 2, "CA", "CA", "A", 302, rec="HETATM", element="CA"))
    insp = inspect_pdb_text("\n".join(lines))
    rep = gate_inspection(insp, keep_hetero=set(), ligand_resnames={"BEN"})
    names = {g.name: g.status for g in rep.gates}
    assert names["co-crystal ligand"] == AUTO_FIXED and names["buffer / additives"] == AUTO_FIXED
    assert "hetero groups" not in names and rep.ok


def test_extract_hetatm_pose(tmp_path):
    from md20.build import extract_hetatm_pose
    lines = [_atom(1, "C1", "BEN", "A", 300, rec="HETATM", element="C"), _atom(2, "C2", "BEN", "A", 300, rec="HETATM", element="C"),
             _atom(3, "C1", "BEN", "B", 300, rec="HETATM", element="C")]
    out = extract_hetatm_pose("\n".join(lines), "BEN", tmp_path / "pose.pdb")
    txt = out.read_text()
    assert txt.count("HETATM") == 2 and " B " not in txt


def test_numbering_jump_is_not_a_gap():
    lines, _ = _protein(6, gap_after=2, gap_len=10, numbering_only=True)   # chymotrypsin-style jump, contiguous backbone
    insp = inspect_pdb_text("\n".join(lines))
    assert not insp.gaps and insp.numbering_jumps
    rep = gate_inspection(insp, keep_hetero=set())
    names = {g.name: g.status for g in rep.gates}
    assert names["numbering jumps"] == PASS and "missing loops (long)" not in names and rep.ok


def test_pocket_protonation_review(tmp_path):
    from md20.build.protonation import pocket_protonation_review
    pdb = tmp_path / "r.pdb"
    pdb.write_text("ATOM      1  CA  ASP A  10       1.000   0.000   0.000  1.00 10.00           C\n"
                   "ATOM      2  CA  HIS A  20      30.000   0.000   0.000  1.00 10.00           C\n"
                   "ATOM      3  CA  LYS A  30       2.000   0.000   0.000  1.00 10.00           C\nEND\n")
    table = [{"residue": "ASP", "resid": 10, "chain": "A", "pka": 7.9, "model_pka": 3.8},
             {"residue": "HIS", "resid": 20, "chain": "A", "pka": 8.0, "model_pka": 6.5},   # far from pocket
             {"residue": "LYS", "resid": 30, "chain": "A", "pka": 10.4, "model_pka": 10.5}]
    out = pocket_protonation_review(table, pdb, (0, 0, 0), ph=7.4)
    assert [f["residue"] for f in out] == ["ASP10A"] and len(out[0]["flags"]) == 2
