"""Pose analysis and recommendation — pure numpy so it is testable anywhere.

For each ligand (or each *joint* pose in simultaneous mode) we compute:
  score            Vina/Vinardo score (kcal/mol, lower is better)
  cluster          greedy RMSD clustering from the best-scoring pose (cutoff 2 Å)
  cluster_size     how many poses fall in the same cluster (= consensus of the search)
  contacts         receptor heavy atoms within 4 Å of any ligand heavy atom (buried vs. surface)
  rmsd_ref         RMSD to a reference pose (co-crystal) when available
  min_ll_distance  minimum ligand–ligand distance (simultaneous mode; < 2 Å = clash)

Recommendation rule (written into the decision log as the reason):
  candidates = poses within `score_window` kcal/mol of the best score and without clashes;
  pick the candidate in the largest cluster; ties → better score.
  Rationale: Vina's score error is ~1–2 kcal/mol, so several near-best poses are equally plausible;
  a pose the search finds repeatedly is more robust than a single best-scoring outlier.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field

import numpy as np


@dataclass
class PoseInfo:
    rank: int                 # 1-based Vina rank
    score: float
    cluster: int = 0
    cluster_size: int = 1
    contacts: int = 0
    rmsd_ref: float | None = None
    min_ll_distance: float | None = None
    clash: bool = False
    recommended: bool = False
    reason: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def plain_rmsd(a: np.ndarray, b: np.ndarray) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    return float(np.sqrt(np.mean(np.sum((a - b) ** 2, axis=1))))


def cluster_poses(coords: list[np.ndarray], scores: list[float], cutoff: float = 2.0, rmsd=plain_rmsd) -> list[int]:
    """Greedy leader clustering in score order.  Returns cluster id per pose (0 = cluster of the best pose)."""
    order = np.argsort(scores)
    leaders: list[int] = []
    labels = [-1] * len(coords)
    for i in order:
        for cid, L in enumerate(leaders):
            if rmsd(coords[i], coords[L]) <= cutoff:
                labels[i] = cid
                break
        else:
            leaders.append(int(i))
            labels[i] = len(leaders) - 1
    return labels


def count_contacts(lig_xyz: np.ndarray, rec_xyz: np.ndarray, cutoff: float = 4.0) -> int:
    lig, rec = np.asarray(lig_xyz, float), np.asarray(rec_xyz, float)
    # bounding-box prefilter keeps this fast on big receptors
    lo, hi = lig.min(0) - cutoff, lig.max(0) + cutoff
    near = rec[np.all((rec >= lo) & (rec <= hi), axis=1)]
    if not len(near):
        return 0
    d2 = ((near[:, None, :] - lig[None, :, :]) ** 2).sum(-1)
    return int(np.any(d2 <= cutoff * cutoff, axis=1).sum())


def analyse_poses(pose_coords: list[np.ndarray], scores: list[float], *, receptor_xyz: np.ndarray | None = None,
                  reference_xyz: np.ndarray | None = None, rmsd=plain_rmsd, cluster_cutoff: float = 2.0,
                  per_ligand_slices: list[slice] | None = None, clash_cutoff: float = 2.0) -> list[PoseInfo]:
    """`pose_coords[k]` = heavy-atom coordinates of pose k (concatenated over ligands for joint poses)."""
    labels = cluster_poses(pose_coords, scores, cluster_cutoff, rmsd)
    sizes = {c: labels.count(c) for c in set(labels)}
    infos = []
    for k, (xyz, s) in enumerate(zip(pose_coords, scores)):
        info = PoseInfo(rank=k + 1, score=float(s), cluster=labels[k], cluster_size=sizes[labels[k]])
        if receptor_xyz is not None:
            info.contacts = count_contacts(xyz, receptor_xyz)
        if reference_xyz is not None and len(reference_xyz) == len(xyz):
            info.rmsd_ref = round(rmsd(xyz, reference_xyz), 3)
        if per_ligand_slices and len(per_ligand_slices) > 1:
            dmin = np.inf
            for i in range(len(per_ligand_slices)):
                for j in range(i + 1, len(per_ligand_slices)):
                    a, b = xyz[per_ligand_slices[i]], xyz[per_ligand_slices[j]]
                    dmin = min(dmin, float(np.sqrt(((a[:, None] - b[None]) ** 2).sum(-1)).min()))
            info.min_ll_distance = round(dmin, 2)
            info.clash = dmin < clash_cutoff
        infos.append(info)
    return infos


def recommend_pose(infos: list[PoseInfo], *, score_window: float = 1.0, min_contacts: int = 10) -> PoseInfo:
    best = min(i.score for i in infos)
    cands = [i for i in infos if i.score <= best + score_window and not i.clash]
    if not cands:
        cands = [i for i in infos if not i.clash] or infos
    buried = [i for i in cands if i.contacts >= min_contacts]
    pool = buried or cands
    pick = sorted(pool, key=lambda i: (-i.cluster_size, i.score))[0]
    for i in infos:
        i.recommended = i is pick
    parts = [f"第 {pick.rank} 名 pose（{pick.score:.2f} kcal/mol）"]
    if pick.rank != 1:
        parts.append(f"雖非最佳分數（第 1 名 {best:.2f}），但差距在 {score_window} kcal/mol 內，而 Vina 分數誤差約 1–2 kcal/mol")
    parts.append(f"所屬 cluster 有 {pick.cluster_size} 個 pose（搜尋重複找到同一結合模式，較可靠）")
    if pick.contacts:
        parts.append(f"與受體 {pick.contacts} 個重原子接觸（{'深埋口袋' if pick.contacts >= 25 else '部分暴露'}）")
    if pick.rmsd_ref is not None:
        parts.append(f"與晶體 pose 的 RMSD {pick.rmsd_ref:.2f} Å（{'≤ 2 Å：重現晶體結合模式' if pick.rmsd_ref <= 2 else '> 2 Å：與晶體不同，請檢查 box 與質子化'}）")
    if pick.min_ll_distance is not None:
        parts.append(f"配體間最短距離 {pick.min_ll_distance:.1f} Å（無碰撞）")
    if not buried and cands:
        parts.append(f"注意：候選 pose 與受體接觸都少於 {min_contacts}，可能落在表面")
    pick.reason = "；".join(parts) + "。"
    return pick
