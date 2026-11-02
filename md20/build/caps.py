"""Neutral ACE/NME caps at receptor chain breaks (D-47).

A chain break that is not rebuilt must not become a bond: OpenMM's createStandardBonds() joins consecutive residues of
one chain whatever their distance.  Capping is the standard alternative (Amber/tleap practice): the residue before the
break gets an N-methylamide (NME) and the residue after it an acetyl (ACE), so both ends stay neutral peptide-like
groups instead of artificial charged termini inside the protein.  The segment after the break gets its own chain ID,
which is what keeps the two pieces unbonded.

Only heavy atoms are placed here, with ideal trans-peptide geometry built from the neighbouring backbone; PDBFixer
adds the hydrogens and minimisation relaxes the rest.  Pure Python + numpy, works on PDB text.
"""
from __future__ import annotations

import string

import numpy as np

C_N = 1.33          # peptide C–N (Å)
N_CH3 = 1.46
C_O = 1.23
C_CH3 = 1.52


def _unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


def _in_plane(e: np.ndarray, toward: np.ndarray, angle_deg: float) -> np.ndarray:
    """Unit vector at `angle_deg` from unit vector e, in the plane of e and `toward`, on the side of `toward`."""
    p = _unit(toward - np.dot(toward, e) * e)
    a = np.radians(angle_deg)
    return np.cos(a) * e + np.sin(a) * p


def nme_atoms(ca: np.ndarray, c: np.ndarray, o: np.ndarray) -> dict:
    """NME after a residue with backbone CA, C, O: N trans-peptide, methyl cis to O (trans to CA)."""
    n_dir = _unit(-(_unit(ca - c) + _unit(o - c)))          # bisects the open angle opposite CA and O
    n = c + C_N * n_dir
    ch3 = n + N_CH3 * _in_plane(_unit(c - n), o - c, 121.7)   # angle C–N–CH3 121.7°, methyl on the O side (cis to O)
    return {"N": n, "C": ch3}


def ace_atoms(n: np.ndarray, ca: np.ndarray, c: np.ndarray) -> dict:
    """ACE before a residue with backbone N, CA, C: carbonyl C bonded to N, O cis to CA, methyl trans to CA."""
    cprev = n + C_N * _in_plane(_unit(ca - n), -(c - ca), 121.7)     # C(ace)–N–CA 121.7°
    e = _unit(n - cprev)                                              # from the ACE carbonyl C towards N
    o = cprev + C_O * _in_plane(e, ca - n, 122.7)                     # N–C–O 122.7°, on the CA side
    ch3 = cprev + C_CH3 * _in_plane(e, -(ca - n), 116.0)              # N–C–CH3 116°, opposite side
    return {"CH3": ch3, "C": cprev, "O": o}


def _fmt(serial: int, name: str, resname: str, chain: str, resid: int, icode: str, xyz, element: str) -> str:
    nm = f" {name:<3}" if len(name) < 4 else name
    return (f"ATOM  {serial % 100000:5d} {nm} {resname:>3} {chain}{resid:4d}{icode:1s}   "
            f"{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}{1.0:6.2f}{0.0:6.2f}          {element:>2}")


def cap_chain_breaks(text: str, breaks: list[tuple[str, int]]) -> tuple[str, list[dict]]:
    """Cap each break given as (chain, resid of the residue BEFORE the break).

    Returns the new PDB text and one record per cap: {"chain", "before", "after", "new_chain", "nme", "ace"}.
    A break whose backbone atoms are incomplete is reported with "error" and left untouched.
    """
    lines = text.splitlines()
    atoms = [l for l in lines if l.startswith(("ATOM", "HETATM"))]
    used_chains = {l[21] for l in atoms}
    spare = [ch for ch in string.ascii_uppercase + string.digits + string.ascii_lowercase if ch not in used_chains]

    def res_key(l):
        return (l[21], l[22:27])

    # residue order per chain (ATOM records only, file order)
    order: dict[str, list[tuple[str, str]]] = {}
    for l in atoms:
        if l.startswith("ATOM"):
            k = res_key(l)
            lst = order.setdefault(l[21], [])
            if not lst or lst[-1] != k:
                lst.append(k)

    def xyz(chain, rkey, name):
        for l in atoms:
            if res_key(l) == (chain, rkey) and l[12:16].strip() == name and l[16] in (" ", "A"):
                return np.array([float(l[30:38]), float(l[38:46]), float(l[46:54])])
        return None

    records, plan = [], []
    for chain, before in sorted(breaks, key=lambda b: (b[0], b[1])):
        keys = order.get(chain, [])
        idx = next((i for i, k in enumerate(keys) if int(k[1][:4]) == int(before) and k[1][4] == " "), None)
        rec = {"chain": chain, "before": int(before)}
        if idx is None or idx + 1 >= len(keys):
            rec["error"] = "找不到斷點兩側的殘基"
            records.append(rec); continue
        bk, ak = keys[idx][1], keys[idx + 1][1]
        ca1, c1, o1 = (xyz(chain, bk, a) for a in ("CA", "C", "O"))
        n2, ca2, c2 = (xyz(chain, ak, a) for a in ("N", "CA", "C"))
        if any(v is None for v in (ca1, c1, o1, n2, ca2, c2)):
            rec["error"] = "斷點兩側殘基缺主鏈原子（CA、C、O 或 N）"
            records.append(rec); continue
        if not spare:
            rec["error"] = "chain ID 已用完"
            records.append(rec); continue
        rec.update(after=int(ak[:4]), new_chain=spare.pop(0), nme=nme_atoms(ca1, c1, o1), ace=ace_atoms(n2, ca2, c2))
        records.append(rec)
        plan.append((chain, bk, ak, rec))

    # rewrite: NME after the last atom of `before`; TER; ACE; the rest of that chain segment gets the new chain ID
    out, serial = [], 0
    relabel: dict[tuple[str, str], str] = {}
    for chain, bk, ak, rec in plan:
        keys = order[chain]
        start = keys.index((chain, ak))
        nxt = [p for p in plan if p[0] == chain and keys.index((chain, p[2])) > start]
        stop = min((keys.index((chain, p[2])) for p in nxt), default=len(keys))
        for k in keys[start:stop]:
            relabel[k] = rec["new_chain"]
    last_atom_of = {}
    for i, l in enumerate(lines):
        if l.startswith("ATOM"):
            last_atom_of[res_key(l)] = i
    insert_after = {last_atom_of[(c, bk)]: (c, bk, ak, rec) for c, bk, ak, rec in plan}
    for i, l in enumerate(lines):
        if l.startswith(("ATOM", "HETATM")):
            k = res_key(l)
            if k in relabel and l.startswith("ATOM"):
                l = l[:21] + relabel[k] + l[22:]
        if l.startswith("TER") and len(l) > 21:
            # a TER after a relabelled residue must carry the new chain ID
            prev = next((x for x in reversed(out) if x.startswith("ATOM")), None)
            if prev is not None:
                l = l[:21] + prev[21] + l[22:] if len(l) > 22 else l
        out.append(l)
        if i in insert_after:
            c, bk, ak, rec = insert_after[i]
            cur_chain = relabel.get((c, bk), c)
            nme_id, ace_id = rec["before"] + 1, rec["after"] - 1
            ace_icode = "A" if ace_id == nme_id else " "
            out.append(_fmt(serial, "N", "NME", cur_chain, nme_id, " ", rec["nme"]["N"], "N"))
            out.append(_fmt(serial, "C", "NME", cur_chain, nme_id, " ", rec["nme"]["C"], "C"))
            out.append(f"TER   {serial % 100000:5d}      NME {cur_chain}{nme_id:4d}")
            for nm, el in (("CH3", "C"), ("C", "C"), ("O", "O")):
                out.append(_fmt(serial, nm, "ACE", rec["new_chain"], ace_id, ace_icode.strip(), rec["ace"][nm], el))
    # renumber serials so PDB readers are happy
    final, n = [], 0
    for l in out:
        if l.startswith(("ATOM", "HETATM")):
            n += 1
            l = l[:6] + f"{n % 100000:5d}" + l[11:]
        final.append(l)
    for r in records:
        for k in ("nme", "ace"):
            if k in r:
                r[k] = {a: [round(float(x), 3) for x in v] for a, v in r[k].items()}
    return "\n".join(final) + ("\n" if text.endswith("\n") else ""), records
