"""Receptor inspection + gates run without any chemistry dependency."""
from md20.build.receptor import inspect_pdb_text, gate_inspection, COFACTOR_KEEP_DEFAULT
from md20.build.gates import PASS, AUTO_FIXED, NEEDS_HUMAN, GateReport, Gate


def _atom(serial, name, resname, chain, resid, x=0.0, rec="ATOM", altloc=" ", icode=" ", element=None):
    element = element if element is not None else name[0]
    return (f"{rec:<6}{serial:>5} {name:<4}{altloc}{resname:>3} {chain}{resid:>4}{icode}   "
            f"{x:8.3f}{0.0:8.3f}{0.0:8.3f}{1.0:6.2f}{0.0:6.2f}          {element:>2}")


def _protein(n=5, chain="A", start=1, gap_after=None, gap_len=0):
    lines = []
    serial = 1
    resid = start
    for i in range(n):
        for name in ("N", "CA", "C", "O"):
            lines.append(_atom(serial, name, "ALA", chain, resid)); serial += 1
        resid += 1
        if gap_after is not None and i == gap_after:
            resid += gap_len
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
