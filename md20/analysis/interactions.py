"""Chemically defined ligand–protein interactions and complete dynamic contact search (D-97; spec A5, A6, F07, F08).

One perception layer for the static pose diagram (`report/chem.pose_contacts`) and the trajectory fingerprint
(`analysis/extended.py`), so a "salt bridge" means the same thing everywhere.

Definitions (geometric cut-offs are documented, empirical and overridable — not universal laws):
  * ``salt_bridge``                 ligand atom and protein atom carry formal charges of OPPOSITE sign, ≤ 0.40 nm.
  * ``like_charge_proximity``       same sign, ≤ 0.40 nm (repulsive; never called a salt bridge).
  * ``charged_proximity_ligand_charge_unknown``
                                    a protein charged group within 0.40 nm of a ligand N/O when the ligand's atom-level
                                    formal charges are not available.  NOT a salt bridge: the charge of the ligand
                                    group is unknown, and partial-charge signs are not used as a substitute.
  * ``polar_proximity``             ligand N/O within 0.35 nm of protein N/O.  Distance only — a candidate, not a
                                    hydrogen bond.  A hydrogen bond needs a donor–H···acceptor geometry
                                    (`extended.py` Wernet–Nilsson); it is reported there, under its own name.
  * ``hydrophobic``                 ligand C within 0.40 nm of a side-chain C of a hydrophobic residue.
A residue can carry several labels in the same frame; labels are not ranked by strength.

Protein formal charges follow the residue name (the protonation state chosen at build time): ASP/GLU −1 (ASH/GLH 0),
LYS +1 (LYN 0), ARG +1, HIP +1 (HIS/HID/HIE 0).  Terminal charges are not assigned (stated in `PROTEIN_CHARGE_NOTE`).

Contacts are searched over EVERY frame (A6): a first pass finds, frame by frame, every atom pair inside the cut-off
(minimum image, orthorhombic or triclinic box), the union of those pairs is the candidate set, and a second pass
evaluates the candidate set over all frames in chunks.  Nothing depends on the first frame.

Residues are identified by chain, residue name, number and insertion code (`residue_key`), so ASP189 on chains A
and B stay distinct.  Pure numpy.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np

SCHEMA = "md20.fingerprint/2"
LABELS = ("salt_bridge", "like_charge_proximity", "charged_proximity_ligand_charge_unknown", "polar_proximity", "hydrophobic")
BIT = {k: 1 << i for i, k in enumerate(LABELS)}
CUTOFF_NM = {"charged": 0.40, "polar": 0.35, "hydrophobic": 0.40}
SEARCH_NM = max(CUTOFF_NM.values())
CUTOFF_SOURCE = "2026-11-07.1: common geometric criteria (salt bridge ≤ 4.0 Å between charged heavy atoms; polar heavy-atom " \
                "distance ≤ 3.5 Å; C···C ≤ 4.0 Å); empirical"

NEG = {("ASP", "OD1"), ("ASP", "OD2"), ("GLU", "OE1"), ("GLU", "OE2")}
POS = {("LYS", "NZ"), ("ARG", "NH1"), ("ARG", "NH2"), ("ARG", "NE"), ("HIP", "ND1"), ("HIP", "NE2")}
HYDROPHOBIC_RES = {"ALA", "VAL", "LEU", "ILE", "MET", "PHE", "TRP", "PRO", "TYR", "CYS"}
PROTEIN_CHARGE_NOTE = "protein charges from residue names (ASP/GLU −, ASH/GLH 0, LYS +, LYN 0, ARG +, HIP +, HIS/HID/HIE 0); " \
                      "terminal charges not assigned"


def protein_charge_sign(resname: str, atom_name: str) -> int:
    key = (str(resname).upper(), str(atom_name).upper())
    return -1 if key in NEG else (1 if key in POS else 0)


def residue_key(chain: str | None, resname: str, resseq: int | str, icode: str | None = "") -> str:
    """Stable residue identity: ``A:ASP189`` (``A:ASP189A`` with an insertion code; ``?:`` when the chain is unknown)."""
    c = (chain or "").strip() or "?"
    return f"{c}:{str(resname).upper()}{resseq}{(icode or '').strip()}"


# ------------------------------------------------------------------------------------------ geometry
def _images(box: np.ndarray) -> np.ndarray:
    s = np.array([-1, 0, 1])
    shifts = np.array(np.meshgrid(s, s, s, indexing="ij")).reshape(3, -1).T          # (27, 3) integer shifts
    return shifts @ box                                                             # (27, 3) lattice vectors


def min_image_distances(a: np.ndarray, b: np.ndarray, box: np.ndarray | None) -> np.ndarray:
    """|a_i − b_j| under the minimum-image convention.  `box` = (3, 3) box vectors as rows (nm) or None (no PBC).
    Fractional wrapping first, then the 27 neighbouring images — exact also for reduced triclinic boxes
    (rhombic dodecahedron, D-22)."""
    d = a[:, None, :] - b[None, :, :]
    if box is None:
        return np.linalg.norm(d, axis=-1)
    box = np.asarray(box, float)
    if box.shape == (3,):
        box = np.diag(box)
    inv = np.linalg.inv(box)
    f = d @ inv
    d = (f - np.round(f)) @ box
    best = np.full(d.shape[:2], np.inf)
    for v in _images(box):
        best = np.minimum(best, np.linalg.norm(d + v, axis=-1))
    return best


def dynamic_pairs(xyz: np.ndarray, a_idx: Iterable[int], b_idx: Iterable[int], *, cutoff_nm: float = SEARCH_NM,
                  boxes: np.ndarray | None = None, chunk: int = 200) -> dict:
    """Complete contact search (A6).  xyz (F, N, 3) nm; boxes (F, 3, 3) or None.

    Returns {"pairs": (P, 2) atom indices, "dist": (F, P) nm, "n_first_frame_pairs": int, "chunk": chunk}; `pairs`
    is the union over all frames of pairs within `cutoff_nm`, so a contact that forms late is never missed."""
    xyz = np.asarray(xyz, float)
    A, B = np.asarray(list(a_idx), int), np.asarray(list(b_idx), int)
    F = xyz.shape[0]
    if not len(A) or not len(B) or not F:
        return {"pairs": np.zeros((0, 2), int), "dist": np.zeros((F, 0)), "n_first_frame_pairs": 0, "chunk": chunk}
    found = set()
    first = 0
    for f in range(F):
        box = None if boxes is None else boxes[f]
        Bf = B
        if box is None:
            # exact prefilter (no PBC): a B atom farther than R + cutoff from the A centroid cannot be within the cut-off
            # of any A atom (triangle inequality), so skipping it loses nothing
            c = xyz[f, A].mean(0)
            R = float(np.linalg.norm(xyz[f, A] - c, axis=1).max())
            Bf = B[np.linalg.norm(xyz[f, B] - c, axis=1) <= R + cutoff_nm + 1e-9]
            if not len(Bf):
                continue
        D = min_image_distances(xyz[f, A], xyz[f, Bf], box)
        ii, jj = np.nonzero(D <= cutoff_nm)
        if f == 0:
            first = len(ii)
        found.update(zip(A[ii].tolist(), Bf[jj].tolist()))
    pairs = np.array(sorted(found), int).reshape(-1, 2)
    dist = np.zeros((F, len(pairs)))
    if len(pairs):
        ai = {a: k for k, a in enumerate(A)}
        bi = {b: k for k, b in enumerate(B)}
        pa, pb = np.array([ai[p] for p in pairs[:, 0]]), np.array([bi[p] for p in pairs[:, 1]])
        for s in range(0, F, max(1, chunk)):                     # second pass in chunks; chunk edges never cut anything
            for f in range(s, min(F, s + chunk)):
                box = None if boxes is None else boxes[f]
                X, Y = xyz[f, A[pa]], xyz[f, B[pb]]
                d = X - Y
                if box is not None:
                    bx = np.asarray(box, float)
                    bx = np.diag(bx) if bx.shape == (3,) else bx
                    fr = d @ np.linalg.inv(bx)
                    d = (fr - np.round(fr)) @ bx
                    dist[f] = np.min(np.stack([np.linalg.norm(d + v, axis=-1) for v in _images(bx)]), axis=0)
                else:
                    dist[f] = np.linalg.norm(d, axis=-1)
    return {"pairs": pairs, "dist": dist, "n_first_frame_pairs": int(first), "chunk": chunk}


# ------------------------------------------------------------------------------------------ chemistry
def pair_labels(lig_elem: str, lig_sign: int | None, prot_elem: str, prot_res: str, prot_atom: str, d_nm: float,
                *, sidechain_carbon: bool = True) -> set[str]:
    """Labels for ONE ligand–protein atom pair at distance d (nm).  lig_sign None = ligand charge unknown."""
    out = set()
    ps = protein_charge_sign(prot_res, prot_atom)
    le, pe = str(lig_elem).upper(), str(prot_elem).upper()
    if ps and d_nm <= CUTOFF_NM["charged"]:
        if lig_sign is None:
            if le in ("N", "O"):
                out.add("charged_proximity_ligand_charge_unknown")
        elif lig_sign * ps < 0:
            out.add("salt_bridge")
        elif lig_sign * ps > 0:
            out.add("like_charge_proximity")
    if le in ("N", "O") and pe in ("N", "O") and d_nm <= CUTOFF_NM["polar"]:
        out.add("polar_proximity")
    if le == "C" and pe == "C" and sidechain_carbon and str(prot_res).upper() in HYDROPHOBIC_RES \
            and d_nm <= CUTOFF_NM["hydrophobic"]:
        out.add("hydrophobic")
    return out


def fingerprint(dyn: dict, atoms: dict, *, ligand_charges: dict[int, int] | None = None, time_ps=None) -> dict:
    """Multi-label residue fingerprint from `dynamic_pairs` output.

    atoms[i] = {"element", "resname", "name", "res_key", "sidechain_carbon"} for every protein atom index in `pairs`,
    and {"element"} for ligand atoms.  ligand_charges = {ligand atom index: ±1} for atoms with a formal charge (all
    other ligand atoms are neutral); None = unknown → no salt bridge can be called."""
    pairs, dist = dyn["pairs"], dyn["dist"]
    F = dist.shape[0]
    known = ligand_charges is not None
    res_bits: dict[str, np.ndarray] = {}
    for k, (li, pj) in enumerate(pairs.tolist()):
        la, pa = atoms[li], atoms[pj]
        sign = (ligand_charges or {}).get(li, 0) if known else None
        rk = pa["res_key"]
        col = dist[:, k]
        # evaluate labels frame-wise only where the pair is inside the largest cut-off
        inside = np.nonzero(col <= SEARCH_NM)[0]
        if not len(inside):
            continue
        bits = res_bits.setdefault(rk, np.zeros(F, np.int64))
        for f in inside:
            for lab in pair_labels(la["element"], sign, pa["element"], pa["resname"], pa["name"], float(col[f]),
                                   sidechain_carbon=pa.get("sidechain_carbon", True)):
                bits[f] |= BIT[lab]
    residues = sorted(res_bits, key=lambda r: -int((res_bits[r] > 0).sum()))
    occ = {lab: {r: round(float(((res_bits[r] & BIT[lab]) > 0).mean()), 4) for r in residues
                 if ((res_bits[r] & BIT[lab]) > 0).any()} for lab in LABELS}
    return {"schema": SCHEMA, "labels": list(LABELS), "bits": {k: BIT[k] for k in LABELS}, "residues": residues,
            "bitmask": [res_bits[r].tolist() for r in residues], "occupancy": occ,
            "ligand_charge": "atom-level formal charges" if known else "unknown (no salt bridge can be called)",
            "cutoffs_nm": dict(CUTOFF_NM), "cutoff_source": CUTOFF_SOURCE, "protein_charges": PROTEIN_CHARGE_NOTE,
            "n_frames": int(F), "time_ps": None if time_ps is None else [float(x) for x in time_ps],
            "search": {"method": "complete per-frame neighbour search (minimum image), union of pairs", "cutoff_nm": SEARCH_NM,
                       "n_pairs": int(len(pairs)), "n_first_frame_pairs": int(dyn.get("n_first_frame_pairs", 0))},
            "hbond": "not part of this fingerprint: distance-only N/O pairs are polar_proximity; geometric hydrogen bonds "
                     "(donor–H···acceptor, Wernet–Nilsson) are reported separately"}


def legacy_matrix(fp: dict) -> list[list[int]]:
    """0 none / 1 hydrophobic / 2 polar proximity / 3 salt bridge — only for reading the old single-class figure.
    Concurrent labels stay in `bitmask`; this is a display fallback, not a strength ranking."""
    out = []
    for row in fp.get("bitmask") or []:
        r = []
        for v in row:
            r.append(3 if v & BIT["salt_bridge"] else (2 if v & BIT["polar_proximity"] else (1 if v & BIT["hydrophobic"] else
                                                                                          (4 if v else 0))))
        out.append(r)
    return out


def initial_vs_new(fp: dict, *, initial_frames: int = 1) -> dict:
    """F07: residues in contact (any label) during the first `initial_frames` frames vs residues that only appear later.
    A lost initial contact is not by itself evidence of a worse pose."""
    res = fp.get("residues") or []
    bm = [np.asarray(r) for r in fp.get("bitmask") or []]
    init = [r for r, b in zip(res, bm) if (b[:initial_frames] > 0).any()]
    new = [r for r, b in zip(res, bm) if not (b[:initial_frames] > 0).any() and (b > 0).any()]
    keep = {r: round(float((b[initial_frames:] > 0).mean()), 4) if len(b) > initial_frames else None
            for r, b in zip(res, bm) if r in init}
    return {"initial": init, "new": new, "initial_retention": keep, "initial_frames": int(initial_frames),
            "note": "losing an initial docking contact does not by itself make a pose worse"}


def water_unavailable(reason: str) -> dict:
    """Missing solvent coordinates → unavailable, never an observed zero (A5, spec Test 19)."""
    return {"status": "unavailable", "reason": reason, "count": None, "residues": None}


def atoms_from_topology(top, indices: Iterable[int]) -> dict:
    """mdtraj topology → the `atoms` mapping `fingerprint` needs.  Chain ids come from `chain.chain_id` when present
    (mdtraj ≥ 1.9.8), else the chain index; insertion codes are not kept by mdtraj and stay empty."""
    out = {}
    for i in indices:
        a = top.atom(int(i))
        r = a.residue
        ch = getattr(r.chain, "chain_id", None) or str(r.chain.index)
        out[int(i)] = {"element": a.element.symbol if a.element is not None else "", "resname": r.name, "name": a.name,
                       "res_key": residue_key(ch, r.name, r.resSeq, ""),
                       "sidechain_carbon": bool(getattr(a, "is_sidechain", True))}
    return out


def display_labels(keys: Iterable[str]) -> dict[str, str]:
    """Short labels for figures (``ASP189``) when unambiguous; the chain prefix is kept wherever two chains share a
    residue name and number."""
    keys = list(keys)
    short = {k: k.split(":", 1)[1] for k in keys}
    dup = {v for v in short.values() if list(short.values()).count(v) > 1}
    return {k: (k if short[k] in dup else short[k]) for k in keys}
