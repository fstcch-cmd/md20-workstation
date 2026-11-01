"""Receptor PDB → PDBQT without OpenBabel / Meeko-receptor tooling.

Input is the PDBFixer-cleaned receptor (explicit hydrogens, standard Amber residue names).
AutoDock Vina's scoring function ignores partial charges, so charges are written as 0.000; only
the AD4 atom types matter:

  C  aliphatic carbon          A   aromatic carbon (PHE/TYR/TRP/HIS ring atoms)
  N  nitrogen (non-acceptor)   NA  acceptor nitrogen (HIS ring N without H)
  OA oxygen                    SA  sulphur
  HD polar hydrogen (bonded to N/O); non-polar hydrogens are dropped (Vina is united-atom)
  metals keep their element symbol (Zn, Mg, Ca, Fe, Mn, …)
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np

AROMATIC = {
    "PHE": {"CG", "CD1", "CD2", "CE1", "CE2", "CZ"},
    "TYR": {"CG", "CD1", "CD2", "CE1", "CE2", "CZ"},
    "TRP": {"CG", "CD1", "CD2", "NE1", "CE2", "CE3", "CZ2", "CZ3", "CH2"},
    "HIS": {"CG", "ND1", "CD2", "CE1", "NE2"}, "HID": {"CG", "ND1", "CD2", "CE1", "NE2"},
    "HIE": {"CG", "ND1", "CD2", "CE1", "NE2"}, "HIP": {"CG", "ND1", "CD2", "CE1", "NE2"},
}
METALS = {"ZN": "Zn", "MG": "Mg", "CA": "Ca", "FE": "Fe", "MN": "Mn", "CU": "Cu", "CO": "Co", "NI": "Ni",
          "CD": "Cd", "NA": "Na", "K": "K", "HG": "Hg"}
HALOGEN = {"F": "F", "CL": "Cl", "BR": "Br", "I": "I"}


def _element(line: str) -> str:
    el = line[76:78].strip().upper() if len(line) >= 78 else ""
    if not el:
        name = line[12:16].strip()
        el = name[:2].upper() if name[:2].upper() in METALS and line.startswith("HETATM") else name[:1].upper()
    return el


def ad4_type(element: str, resname: str, name: str, *, has_h: bool, is_hetatm: bool) -> str | None:
    """AD4 type for one heavy atom; None means 'drop'."""
    el = element.upper()
    if is_hetatm and el in METALS and resname.strip().upper() in METALS:
        return METALS[el]
    if el == "C":
        return "A" if name in AROMATIC.get(resname, set()) else "C"
    if el == "N":
        if resname in AROMATIC and name in AROMATIC[resname] and not has_h:
            return "NA"
        return "N"
    if el == "O":
        return "OA"
    if el == "S":
        return "SA"
    if el == "P":
        return "P"
    if el in HALOGEN:
        return HALOGEN[el]
    if el in METALS:
        return METALS[el]
    return None


def receptor_to_pdbqt(pdb_in: Path | str, pdbqt_out: Path | str) -> dict:
    """Write a rigid-receptor PDBQT.  Returns counts per AD type (useful for the decision log)."""
    lines = [l for l in Path(pdb_in).read_text(encoding="utf-8", errors="ignore").splitlines()
             if l.startswith(("ATOM", "HETATM"))]
    atoms = []
    for l in lines:
        try:
            xyz = (float(l[30:38]), float(l[38:46]), float(l[46:54]))
        except ValueError:
            continue
        atoms.append({"line": l, "el": _element(l), "res": (l[21], l[22:27]), "resname": l[17:20].strip(),
                      "name": l[12:16].strip(), "xyz": np.array(xyz), "het": l.startswith("HETATM")})
    by_res = defaultdict(list)
    for i, a in enumerate(atoms):
        by_res[a["res"]].append(i)
    # attach every H to its nearest heavy atom in the same residue (≤ 1.25 Å)
    h_parent: dict[int, int] = {}
    heavy_has_h: set[int] = set()
    for idxs in by_res.values():
        heavy = [i for i in idxs if atoms[i]["el"] != "H"]
        if not heavy:
            continue
        hxyz = np.array([atoms[i]["xyz"] for i in heavy])
        for i in idxs:
            if atoms[i]["el"] != "H":
                continue
            d = np.linalg.norm(hxyz - atoms[i]["xyz"], axis=1)
            j = int(np.argmin(d))
            if d[j] <= 1.25:
                h_parent[i] = heavy[j]
                heavy_has_h.add(heavy[j])
    out, counts, serial = [], defaultdict(int), 0
    for i, a in enumerate(atoms):
        if a["el"] == "H":
            p = h_parent.get(i)
            if p is None or atoms[p]["el"] not in {"N", "O"}:
                continue  # non-polar H: united-atom
            t = "HD"
        else:
            t = ad4_type(a["el"], a["resname"], a["name"], has_h=i in heavy_has_h, is_hetatm=a["het"])
            if t is None:
                counts["dropped"] += 1
                continue
        serial += 1
        l = a["line"]
        rec = "HETATM" if a["het"] else "ATOM  "
        out.append(f"{rec}{serial % 100000:5d} {l[12:16]}{' '}{l[17:20]} {l[21]}{l[22:26]}{l[26]}   "
                   f"{a['xyz'][0]:8.3f}{a['xyz'][1]:8.3f}{a['xyz'][2]:8.3f}{1.0:6.2f}{0.0:6.2f}    {0.0:+6.3f} {t:<2s}")
        counts[t] += 1
    from ..util.stamp import pdb_remarks
    Path(pdbqt_out).write_text("\n".join(pdb_remarks() + out) + "\nTER\n", encoding="utf-8")
    return dict(counts)
