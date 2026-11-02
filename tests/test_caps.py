"""D-47: ACE/NME caps at chain breaks — geometry, chain split, renumbered serials, no gap left (pure Python)."""
import numpy as np
import pytest

from md20.build.caps import cap_chain_breaks, nme_atoms, ace_atoms
from md20.build.receptor import inspect_pdb_text


def _backbone(n_res, chain="A", start=1, gap_after=None, gap_len=0):
    """Extended β-strand backbone with realistic N, CA, C, O positions (3.3 Å rise per residue)."""
    lines, serial, resid = [], 1, start
    tmpl = {"N": (-1.20, 0.45, 0.0), "CA": (0.0, 0.0, 0.0), "C": (1.20, 0.80, 0.0), "O": (1.20, 2.03, 0.0)}
    x = 0.0
    for i in range(n_res):
        flip = -1 if i % 2 else 1
        for name, (dx, dy, dz) in tmpl.items():
            lines.append(f"ATOM  {serial:5d}  {name:<3} ALA {chain}{resid:4d}    {x + dx:8.3f}{flip * dy:8.3f}{dz:8.3f}  1.00  0.00           {name[0]:>1}")
            serial += 1
        resid += 1
        x += 3.3
        if gap_after is not None and i == gap_after:
            resid += gap_len
            x += 3.3 * gap_len
    return "\n".join(lines + ["TER", "END"]) + "\n"


def test_cap_geometry():
    N, CA, C, O = map(np.array, ([0.0, 1.32, 0.0], [0.0, 0.0, 0.0], [1.42, -0.55, 0.0], [1.62, -1.77, 0.0]))
    nm, ac = nme_atoms(CA, C, O), ace_atoms(N, CA, C)
    assert abs(np.linalg.norm(nm["N"] - C) - 1.33) < 1e-6 and abs(np.linalg.norm(nm["C"] - nm["N"]) - 1.46) < 1e-6
    assert abs(np.linalg.norm(ac["C"] - N) - 1.33) < 1e-6 and abs(np.linalg.norm(ac["O"] - ac["C"]) - 1.23) < 1e-6
    # methyl carbons point away from the residue they cap
    assert np.linalg.norm(nm["C"] - CA) > np.linalg.norm(nm["N"] - CA)
    assert np.linalg.norm(ac["CH3"] - CA) > np.linalg.norm(ac["C"] - CA)


def test_cap_chain_breaks_splits_and_removes_gap():
    text = _backbone(8, gap_after=3, gap_len=5)
    assert inspect_pdb_text(text).gaps == [("A", 4, 10)]
    new, recs = cap_chain_breaks(text, [("A", 4)])
    assert len(recs) == 1 and recs[0]["after"] == 10 and recs[0]["new_chain"] != "A"
    lines = [l for l in new.splitlines() if l.startswith("ATOM")]
    nme = [l for l in lines if l[17:20] == "NME"]
    ace = [l for l in lines if l[17:20] == "ACE"]
    assert [l[12:16].strip() for l in nme] == ["N", "C"] and nme[0][21] == "A" and int(nme[0][22:26]) == 5
    assert [l[12:16].strip() for l in ace] == ["CH3", "C", "O"] and ace[0][21] == recs[0]["new_chain"] and int(ace[0][22:26]) == 9
    assert all(l[21] == recs[0]["new_chain"] for l in lines if l[17:20] == "ALA" and int(l[22:26]) >= 10)
    assert [int(l[6:11]) for l in lines] == list(range(1, len(lines) + 1))       # serials renumbered
    assert inspect_pdb_text(new).gaps == []                                       # no break left inside a chain
    # the caps sit next to the residues they cap (bonded distances)
    xyz = lambda l: np.array([float(l[30:38]), float(l[38:46]), float(l[46:54])])  # noqa: E731
    c4 = next(l for l in lines if l[17:20] == "ALA" and int(l[22:26]) == 4 and l[12:16].strip() == "C")
    n10 = next(l for l in lines if l[17:20] == "ALA" and int(l[22:26]) == 10 and l[12:16].strip() == "N")
    assert abs(np.linalg.norm(xyz(nme[0]) - xyz(c4)) - 1.33) < 0.01
    assert abs(np.linalg.norm(xyz(ace[1]) - xyz(n10)) - 1.33) < 0.01


def test_two_breaks_and_missing_atoms():
    text = _backbone(12, gap_after=3, gap_len=4)
    new, recs = cap_chain_breaks(text, [("A", 4), ("A", 99)])
    assert len([r for r in recs if "error" not in r]) == 1 and any("error" in r for r in recs)
    broken = "\n".join(l for l in text.splitlines() if not (l.startswith("ATOM") and int(l[22:26]) == 4 and l[12:16].strip() == "O"))
    _, recs = cap_chain_breaks(broken, [("A", 4)])
    assert "error" in recs[0]


def test_capping_through_prepare_receptor(pdb_3ptb, tmp_path):
    """Real stack: 3PTB without SEQRES and with residues 70–73 deleted → short-gap gate; choosing the cap option
    builds ACE/NME with hydrogens and leaves no chain break."""
    pytest.importorskip("pdbfixer")
    from md20.build.receptor import prepare_receptor
    lines = [l for l in pdb_3ptb.read_text().splitlines()
             if not l.startswith("SEQRES") and not (l.startswith("ATOM") and 70 <= int(l[22:26]) <= 73)]
    src = tmp_path / "gap.pdb"; src.write_text("\n".join(lines) + "\n")
    man = prepare_receptor(src, tmp_path / "a", keep_hetero={"CA"}, ligand_resnames={"BEN"})
    assert man["status"] == "NEEDS_HUMAN"
    man = prepare_receptor(src, tmp_path / "b", keep_hetero={"CA"}, ligand_resnames={"BEN"},
                           human_choices={"missing loops (short)": "截斷（加 ACE/NME 端帽）"})
    assert man["status"] != "NEEDS_HUMAN", man["gates"]
    out = open(man["receptor_pdb"]).read()
    assert " ACE " in out and " NME " in out and not inspect_pdb_text(out).gaps
    assert man["capped_breaks"] and man["capped_breaks"][0]["before"] == 69
    hs = [l for l in out.splitlines() if l[17:20] in ("ACE", "NME") and l[76:78].strip() == "H"]
    assert len(hs) >= 6                                   # methyl hydrogens on both caps (+ amide H on NME)
