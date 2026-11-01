"""Periodic-boundary "re-centering" (立體歸零) — pure numpy so the rule is testable without mdtraj/OpenMM.

The symptom this fixes: OpenMM writes every molecule wrapped into the primary box (DCDReporter
enforcePeriodicBox=True), the protein diffuses across the box during a long run, and in the viewer the
protein "jumps" sides while a ligand, a second chain or a peptide ends up on the opposite face — it
*looks* dissociated although it never left the pocket.  Nothing about the physics is wrong (the
CMMotionRemover only removes the whole system's drift; a protein diffusing in water is real), so this is a
coordinate transformation applied **after** the simulation, never a force.

Rule (Chodera-lab/mdtraj convention, made explicit):
  1. anchor = all protein chains + metals bonded to them (from the build manifest, never guessed by size);
     every anchor molecule is made whole and placed in the image closest to the anchor centroid;
  2. every other molecule (ligand, peptide, ion, water) is made whole and moved to the image whose centroid
     is closest to the anchor centroid (minimum image of the centroid, not of single atoms);
  3. the anchor centroid is translated to the box centre; optionally the frames are superposed on Cα.
Only orthorhombic boxes are handled analytically here; triclinic vectors are reduced to their diagonal
(mdtraj's image_molecules handles the general case in traj.py when available).
"""
from __future__ import annotations

import numpy as np


def _wrap_delta(d: np.ndarray, box: np.ndarray) -> np.ndarray:
    """Minimum-image displacement for an orthorhombic box (box = diagonal lengths)."""
    return d - box * np.round(d / box)


def make_whole(xyz: np.ndarray, molecules: list[np.ndarray], bonds_of: dict[int, list[tuple[int, int]]], box: np.ndarray) -> np.ndarray:
    """Unwrap each molecule so no bond crosses the boundary (walk the bond graph from the first atom)."""
    out = xyz.copy()
    for mol in molecules:
        if len(mol) < 2:
            continue
        mol_set = set(int(i) for i in mol)
        seen = {int(mol[0])}
        stack = [int(mol[0])]
        while stack:
            i = stack.pop()
            for a, b in bonds_of.get(i, ()):
                j = b if a == i else a
                if j in mol_set and j not in seen:
                    out[j] = out[i] + _wrap_delta(out[j] - out[i], box)
                    seen.add(j)
                    stack.append(j)
    return out


def recenter_frame(xyz: np.ndarray, box: np.ndarray, anchor_molecules: list[np.ndarray], other_molecules: list[np.ndarray],
                   bonds_of: dict[int, list[tuple[int, int]]] | None = None, *, to_box_center: bool = True) -> np.ndarray:
    """One frame → anchored, whole, centred coordinates (same shape, nm).  `box`: (3,) diagonal lengths."""
    box = np.asarray(box, float)
    out = make_whole(np.asarray(xyz, float), anchor_molecules + other_molecules, bonds_of or {}, box)
    anchor_idx = np.concatenate(anchor_molecules) if anchor_molecules else np.array([], dtype=int)
    if len(anchor_idx) == 0:
        return out
    # 1. gather the anchor molecules around the first one (multi-chain proteins must stay together)
    ref = out[anchor_molecules[0]].mean(0)
    for mol in anchor_molecules[1:]:
        c = out[mol].mean(0)
        out[mol] += _wrap_delta(c - ref, box) - (c - ref)      # shift by whole box vectors only
    centroid = out[anchor_idx].mean(0)
    # 2. every other molecule to the image closest to the anchor centroid
    for mol in other_molecules:
        c = out[mol].mean(0)
        out[mol] += _wrap_delta(c - centroid, box) - (c - centroid)
    # 3. anchor centroid → box centre
    if to_box_center:
        out += box / 2.0 - centroid
    return out


def split_molecules(n_atoms: int, bonds: list[tuple[int, int]]) -> list[np.ndarray]:
    """Connected components of the bond graph (what mdtraj calls molecules)."""
    parent = list(range(n_atoms))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for a, b in bonds:
        ra, rb = find(int(a)), find(int(b))
        if ra != rb:
            parent[ra] = rb
    groups: dict[int, list[int]] = {}
    for i in range(n_atoms):
        groups.setdefault(find(i), []).append(i)
    return [np.array(v, dtype=int) for v in groups.values()]


def anchor_and_others(molecules: list[np.ndarray], anchor_atoms: set[int]) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """A molecule is an anchor when any of its atoms is in `anchor_atoms` (protein chains, bonded metals)."""
    anchors, others = [], []
    for m in molecules:
        (anchors if any(int(i) in anchor_atoms for i in m) else others).append(m)
    return anchors, others


def apparent_vs_true_distance(raw_xyz: np.ndarray, centred_xyz: np.ndarray, ligand_idx: np.ndarray, pocket_idx: np.ndarray) -> dict:
    """The honesty check: ligand–pocket centroid distance before and after re-centering (nm)."""
    raw = float(np.linalg.norm(raw_xyz[ligand_idx].mean(0) - raw_xyz[pocket_idx].mean(0)))
    true = float(np.linalg.norm(centred_xyz[ligand_idx].mean(0) - centred_xyz[pocket_idx].mean(0)))
    return {"apparent_nm": round(raw, 4), "true_nm": round(true, 4), "pbc_artifact": bool(raw - true > 0.5)}
