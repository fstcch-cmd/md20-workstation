"""Pose analysis and recommendation — pure numpy so it is testable anywhere.

For each ligand (or each *joint* pose in simultaneous mode) we compute:
  score            Vina/Vinardo score (kcal/mol, lower is better)
  cluster          greedy RMSD clustering from the best-scoring pose (cutoff 2 Å)
  cluster_size     how many poses fall in the same cluster (= consensus of the search)
  contacts         receptor heavy atoms within 4 Å of any ligand heavy atom (buried vs. surface)
  rmsd_ref         RMSD to a reference pose (co-crystal) when available
  min_ll_distance  minimum ligand–ligand distance (simultaneous mode; < 2 Å = clash)

Recommendation rule (conservative; written into the decision log as the reason):
  candidates = poses within `score_window` kcal/mol of the best score that pass every rule:
    • buried: contacts ≥ min_contacts (joint poses: *each* ligand separately);
    • joint poses: minimum ligand–ligand heavy-atom distance in [ll_min, ll_max] Å
      (closer = clash; farther = the ligands do not share the pocket);
    • reference available: RMSD to the crystal pose ≤ 2 Å for the pick (redocking self-check).
  pick the candidate in the largest cluster; ties → better score.
  No candidate → no recommendation (`None`) and an explanation; the caller must stop (NEEDS_HUMAN).
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
    contacts_per_ligand: list | None = None
    rejected: list = field(default_factory=list)
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
            if per_ligand_slices and len(per_ligand_slices) > 1:
                info.contacts_per_ligand = [count_contacts(xyz[sl], receptor_xyz) for sl in per_ligand_slices]
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


LL_MIN, LL_MAX = 3.3, 4.5


def _rejections(i: PoseInfo, *, best: float, score_window: float, min_contacts: int, ll_min: float, ll_max: float) -> list[str]:
    r = []
    if i.score > best + score_window:
        r.append(f"分數差 {i.score - best:.1f} > {score_window} kcal/mol")
    if i.contacts_per_ligand is not None:
        shallow = [k for k, c in enumerate(i.contacts_per_ligand) if c < min_contacts]
        if shallow:
            r.append("配體 " + ",".join(str(k + 1) for k in shallow) + f" 接觸 < {min_contacts}（一深一淺）")
    elif i.contacts < min_contacts:
        r.append(f"接觸 {i.contacts} < {min_contacts}（可能在表面）")
    if i.min_ll_distance is not None:
        if i.min_ll_distance < ll_min:
            r.append(f"配體間 {i.min_ll_distance:.1f} Å < {ll_min}（碰撞）")
        elif i.min_ll_distance > ll_max:
            r.append(f"配體間 {i.min_ll_distance:.1f} Å > {ll_max}（未共同佔據口袋）")
    return r


def recommend_pose(infos: list[PoseInfo], *, score_window: float = 1.0, min_contacts: int = 10, ll_min: float = LL_MIN,
                   ll_max: float = LL_MAX, ligand_charges: list[int] | None = None, pocket_volume_A3: float | None = None,
                   ligand_volume_A3: float | None = None, redock_max_rmsd: float = 2.0) -> PoseInfo | None:
    """Conservative recommendation; returns None when no pose passes (caller must raise NEEDS_HUMAN).

    The explanation is always in `infos[0].extra["recommendation"]` (also when None).
    """
    best = min(i.score for i in infos)
    for i in infos:
        i.rejected = _rejections(i, best=best, score_window=score_window, min_contacts=min_contacts, ll_min=ll_min, ll_max=ll_max)
        i.clash = i.min_ll_distance is not None and i.min_ll_distance < ll_min
        i.recommended = False
    notes = []
    if pocket_volume_A3 is not None and ligand_volume_A3 is not None and pocket_volume_A3 < 1.2 * ligand_volume_A3:
        msg = (f"口袋可用體積約 {pocket_volume_A3:.0f} Å³，配體總體積約 {ligand_volume_A3:.0f} Å³：口袋可能只容得下一個配體"
               "（格點粗估）。建議改用 independent 對接或只保留一個配體。")
        infos[0].extra["recommendation"] = {"status": "NEEDS_HUMAN", "reason": msg}
        return None
    if ligand_charges and len(ligand_charges) > 1:
        pos = [q for q in ligand_charges if q > 0]; neg = [q for q in ligand_charges if q < 0]
        if len(pos) > 1 or len(neg) > 1:
            notes.append("警告：同號淨電荷的配體同時在口袋（Vina 沒有靜電項，分數可能高估；MD 釋放後可能互斥），報告會標註")
    cands = [i for i in infos if not i.rejected]
    if not cands:
        why = "；".join(f"rank {i.rank}：{'、'.join(i.rejected)}" for i in infos[:6])
        infos[0].extra["recommendation"] = {"status": "NEEDS_HUMAN", "reason": "沒有任何 pose 通過保守條件，不自動選擇。" + why}
        return None
    pick = sorted(cands, key=lambda i: (-i.cluster_size, i.score))[0]
    if pick.rmsd_ref is not None and pick.rmsd_ref > redock_max_rmsd:
        best_ref = min((i.rmsd_ref for i in infos if i.rmsd_ref is not None), default=None)
        infos[0].extra["recommendation"] = {"status": "NEEDS_HUMAN", "reason":
            f"Redocking 自檢未通過：推薦 pose 與晶體 pose 的 RMSD {pick.rmsd_ref:.2f} Å > {redock_max_rmsd} Å"
            f"（所有 pose 中最小 {best_ref:.2f} Å）。對接設定（box、質子化、受體準備）不可信，請先修正，不往下選 pose。"}
        return None
    pick.recommended = True
    parts = [f"第 {pick.rank} 名 pose（{pick.score:.2f} kcal/mol）"]
    if pick.rank != 1:
        parts.append(f"雖非最佳分數（第 1 名 {best:.2f}），但差距在 {score_window} kcal/mol 內，而 Vina 分數誤差約 1–2 kcal/mol")
    parts.append(f"所屬 cluster 有 {pick.cluster_size} 個 pose（搜尋重複找到同一結合模式，較可靠）")
    if pick.contacts_per_ligand is not None:
        parts.append("各配體與受體接觸 " + "／".join(str(c) for c in pick.contacts_per_ligand) + " 個重原子（皆埋入口袋）")
    elif pick.contacts:
        parts.append(f"與受體 {pick.contacts} 個重原子接觸（{'深埋口袋' if pick.contacts >= 25 else '部分暴露'}）")
    if pick.rmsd_ref is not None:
        parts.append(f"與晶體 pose 的 RMSD {pick.rmsd_ref:.2f} Å（≤ {redock_max_rmsd} Å：重現晶體結合模式）")
    if pick.min_ll_distance is not None:
        parts.append(f"配體間最短距離 {pick.min_ll_distance:.1f} Å（在 {ll_min}–{ll_max} Å：共同佔據且無碰撞）")
    rej = [i for i in infos if i.rejected and i.score <= best + score_window]
    if rej:
        parts.append("分數相近但被排除：" + "；".join(f"rank {i.rank}（{'、'.join(i.rejected)}）" for i in rej[:3]))
    parts += notes
    pick.reason = "；".join(parts) + "。"
    infos[0].extra["recommendation"] = {"status": "AUTO_FIXED" if notes else "PASS", "reason": pick.reason}
    return pick


# --------------------------------------------------------------------------- pocket volume (grid, rough)
def pocket_volume(receptor_xyz: np.ndarray, center, size, *, spacing: float = 1.0, probe: float = 3.0,
                  ray_len: float = 10.0, buried_fraction: float = 0.6) -> float:
    """Empty, buried grid volume (Å³) inside the docking box — a rough LIGSITE-like estimate.

    A grid point counts if it is > `probe` Å from every receptor heavy atom and ≥ `buried_fraction` of 14
    rays (axes + diagonals) hit receptor atoms within `ray_len` Å.
    """
    rec = np.asarray(receptor_xyz, float)
    c, h = np.asarray(center, float), np.asarray(size, float) / 2
    lo, hi = c - h, c + h
    near = rec[np.all((rec >= lo - ray_len) & (rec <= hi + ray_len), axis=1)]
    if not len(near):
        return 0.0
    axes = [np.arange(lo[k], hi[k] + 1e-6, spacing) for k in range(3)]
    grid = np.stack(np.meshgrid(*axes, indexing="ij"), -1).reshape(-1, 3)
    try:
        from scipy.spatial import cKDTree
        tree = cKDTree(near)
        dmin = tree.query(grid)[0]
        hit = lambda pts: tree.query(pts)[0] <= 1.8  # noqa: E731
    except ImportError:
        def _d(pts):
            out = np.empty(len(pts))
            for k in range(0, len(pts), 2000):
                out[k:k + 2000] = np.sqrt(((pts[k:k + 2000, None, :] - near[None]) ** 2).sum(-1)).min(1)
            return out
        dmin = _d(grid)
        hit = lambda pts: _d(pts) <= 1.8  # noqa: E731
    empty = grid[dmin > probe]
    if not len(empty):
        return 0.0
    dirs = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]] +
                    [[a, b, c2] for a in (1, -1) for b in (1, -1) for c2 in (1, -1)], float)
    dirs /= np.linalg.norm(dirs, axis=1)[:, None]
    steps = np.arange(1.0, ray_len + 1e-6, 1.0)
    blocked = np.zeros(len(empty))
    for d in dirs:
        pts = empty[:, None, :] + steps[None, :, None] * d[None, None, :]
        blocked += hit(pts.reshape(-1, 3)).reshape(len(empty), len(steps)).any(1)
    return float((blocked / len(dirs) >= buried_fraction).sum() * spacing ** 3)


HEAVY_ATOM_VOLUME_A3 = 18.0
