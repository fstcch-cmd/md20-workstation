"""Docking search box: from a reference ligand / residue, explicit centre+size, or the whole receptor."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np


@dataclass
class Box:
    center: tuple[float, float, float]   # Å
    size: tuple[float, float, float]     # Å
    source: str = "manual"
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def contains(self, xyz: np.ndarray, margin: float = 0.0) -> np.ndarray:
        c, h = np.asarray(self.center), np.asarray(self.size) / 2 + margin
        return np.all(np.abs(np.asarray(xyz) - c) <= h, axis=-1)


def box_from_coords(xyz: np.ndarray, *, padding: float = 6.0, min_size: float = 18.0, max_size: float = 32.0,
                    source: str = "reference ligand") -> Box:
    xyz = np.asarray(xyz, dtype=float)
    lo, hi = xyz.min(axis=0), xyz.max(axis=0)
    center = (lo + hi) / 2
    size = np.clip(hi - lo + 2 * padding, min_size, max_size)
    note = (f"以 {source} 的範圍加上每邊 {padding} Å 為 box（最小 {min_size} Å、最大 {max_size} Å）；"
            "box 太大會降低搜尋效率，太小會切掉口袋。")
    return Box(tuple(round(float(x), 3) for x in center), tuple(round(float(x), 2) for x in size), source, note)


def _pdb_xyz(lines) -> np.ndarray:
    return np.array([[float(l[30:38]), float(l[38:46]), float(l[46:54])] for l in lines])


def box_from_pdb_residue(pdb: Path | str, resname: str, **kw) -> Box:
    lines = [l for l in Path(pdb).read_text(encoding="utf-8", errors="ignore").splitlines()
             if l.startswith(("ATOM", "HETATM")) and l[17:20].strip() == resname and l[16] in " A"]
    if not lines:
        raise ValueError(f"{pdb} 中找不到殘基 {resname}，無法定義 box")
    # first instance only
    key = (lines[0][21], lines[0][22:27])
    lines = [l for l in lines if (l[21], l[22:27]) == key]
    return box_from_coords(_pdb_xyz(lines), source=f"co-crystal {resname}", **kw)


def box_whole_receptor(pdb: Path | str, *, padding: float = 4.0) -> Box:
    lines = [l for l in Path(pdb).read_text(encoding="utf-8", errors="ignore").splitlines() if l.startswith("ATOM")]
    b = box_from_coords(_pdb_xyz(lines), padding=padding, min_size=20.0, max_size=126.0, source="whole receptor")
    b.note = "盲對接（整個受體）：搜尋空間大，請把 exhaustiveness 提高到 ≥ 32，並把結果當作口袋探索而不是結合模式。"
    return b
