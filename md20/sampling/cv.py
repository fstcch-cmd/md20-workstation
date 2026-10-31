"""Collective variable helpers (pure numpy): COM distance with minimum image, group selection."""
from __future__ import annotations

import numpy as np

PROTEIN_RES = {"ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE", "LEU", "LYS", "MET", "PHE", "PRO",
               "SER", "THR", "TRP", "TYR", "VAL", "HID", "HIE", "HIP", "CYX", "ASH", "GLH", "LYN", "ACE", "NME"}


def minimum_image(d: np.ndarray, box: np.ndarray) -> np.ndarray:
    """Wrap displacement(s) `d` (…,3) into the primary cell of an orthorhombic box (diagonal lengths)."""
    return d - box * np.round(d / box)


def com(xyz: np.ndarray, masses: np.ndarray | None = None) -> np.ndarray:
    if masses is None:
        return xyz.mean(axis=0)
    m = masses[:, None]
    return (xyz * m).sum(axis=0) / m.sum()


def com_distance(xyz: np.ndarray, g1: np.ndarray, g2: np.ndarray, box: np.ndarray | None,
                 masses: np.ndarray | None = None) -> float:
    """COM–COM distance between atom-index groups, minimum-image if `box` (3 diagonal lengths) is given."""
    c1 = com(xyz[g1], None if masses is None else masses[g1])
    c2 = com(xyz[g2], None if masses is None else masses[g2])
    d = c2 - c1
    if box is not None:
        d = minimum_image(d, box)
    return float(np.linalg.norm(d))


def select_groups(topology, positions_nm: np.ndarray, *, ligand_resnames: set[str], pocket_cutoff_nm: float = 0.8,
                  anchor_residues: list[tuple[str, int]] | None = None) -> dict:
    """Ligand heavy atoms + anchor CA atoms (pocket residues within cutoff, or user list of (chain, resid))."""
    lig, anchor, backbone_all = [], [], []
    lig_xyz = []
    atoms = list(topology.atoms())
    for a in atoms:
        heavy = a.element is not None and a.element.symbol != "H"
        if a.residue.name in ligand_resnames and heavy:
            lig.append(a.index); lig_xyz.append(positions_nm[a.index])
        elif a.residue.name in PROTEIN_RES and a.name == "CA":
            backbone_all.append(a)
    if not lig:
        raise ValueError(f"找不到配體重原子（resnames={sorted(ligand_resnames)}）")
    lig_xyz = np.asarray(lig_xyz)
    if anchor_residues:
        want = {(c, r) for c, r in anchor_residues}
        anchor = [a.index for a in backbone_all if (a.residue.chain.id, int(a.residue.id)) in want]
        reason = f"使用者指定 anchor 殘基 {len(anchor)} 個 CA"
    else:
        for a in backbone_all:
            d = np.linalg.norm(lig_xyz - positions_nm[a.index], axis=1).min()
            if d <= pocket_cutoff_nm:
                anchor.append(a.index)
        reason = f"自動選取配體 {pocket_cutoff_nm:.1f} nm 內的口袋殘基 CA 作為 anchor（{len(anchor)} 個）"
    if len(anchor) < 3:
        raise ValueError("anchor 原子不足 3 個；請放寬 pocket_cutoff 或手動指定 anchor 殘基")
    return {"ligand": np.asarray(lig, dtype=int), "anchor": np.asarray(anchor, dtype=int), "reason": reason}


def pulling_direction(xyz: np.ndarray, groups: dict, box: np.ndarray | None) -> np.ndarray:
    d = com(xyz[groups["ligand"]]) - com(xyz[groups["anchor"]])
    if box is not None:
        d = minimum_image(d, box)
    n = np.linalg.norm(d)
    return d / n if n > 0 else np.array([1.0, 0.0, 0.0])


def box_clearance_nm(xyz: np.ndarray, groups: dict, box: np.ndarray, direction: np.ndarray) -> float:
    """How far the ligand COM can travel along `direction` before reaching half a box length from the anchor
    (beyond that, the periodic image of the protein is closer than the protein itself)."""
    c = com(xyz[groups["ligand"]]) - com(xyz[groups["anchor"]])
    c = minimum_image(c, box)
    current = float(np.dot(c, direction))
    # distance to the half-box boundary along the direction (conservative: use the smallest box length)
    return float(0.5 * box.min() - current)
