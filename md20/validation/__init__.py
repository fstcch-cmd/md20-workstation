"""Validation cases built from HCC Lab publications (also used as teaching background)."""
from . import hsieh2024, hsieh2025

CASES = {"hsieh2024": hsieh2024, "hsieh2025": hsieh2025}


def residues_in_box(pdb_text: str, center, size, *, chain: str | None = None) -> set[str]:
    """{"LYS195", …} for protein residues with any atom inside the box (Å)."""
    import numpy as np
    c, h = np.asarray(center, float), np.asarray(size, float) / 2
    out = set()
    for l in pdb_text.splitlines():
        if not l.startswith("ATOM") or (chain and l[21] != chain):
            continue
        try:
            xyz = np.array([float(l[30:38]), float(l[38:46]), float(l[46:54])])
        except ValueError:
            continue
        if np.all(np.abs(xyz - c) <= h):
            out.add(f"{l[17:20].strip()}{int(l[22:26])}")
    return out


def residues_near(pdb_text: str, coords, cutoff: float = 4.0) -> set[str]:
    import numpy as np
    pts = np.asarray(coords, float)
    out = set()
    for l in pdb_text.splitlines():
        if l.startswith("ATOM"):
            try:
                xyz = np.array([float(l[30:38]), float(l[38:46]), float(l[46:54])])
            except ValueError:
                continue
            if np.min(np.linalg.norm(pts - xyz, axis=1)) <= cutoff:
                out.add(f"{l[17:20].strip()}{int(l[22:26])}")
    return out
