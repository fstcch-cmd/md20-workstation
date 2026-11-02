"""Docking analysis figures (D-59): pose similarity, docking funnel, pose positions in the box, contact map across
poses, ligand comparison.  Pure numpy on the pose SDF files and the docking receptor PDB."""
from __future__ import annotations

from pathlib import Path

import numpy as np


def sdf_heavy(path) -> np.ndarray | None:
    """Heavy-atom coordinates of the first molecule in a V2000 SDF (Å)."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
        n = int(lines[3][:3])
    except Exception:  # noqa: BLE001
        return None
    xyz = []
    for l in lines[4:4 + n]:
        p = l.split()
        if len(p) >= 4 and p[3] != "H":
            xyz.append([float(p[0]), float(p[1]), float(p[2])])
    return np.asarray(xyz, float) if xyz else None


def receptor_atoms(pdb_path) -> list[dict]:
    out = []
    for l in Path(pdb_path).read_text(encoding="utf-8", errors="ignore").splitlines():
        if l.startswith("ATOM"):
            el = (l[76:78].strip() or l[12:16].strip()[:1]).upper()
            if el == "H":
                continue
            try:
                out.append({"xyz": [float(l[30:38]), float(l[38:46]), float(l[46:54])], "res": f"{l[17:20].strip()}{int(l[22:26])}"})
            except ValueError:
                continue
    return out


def pose_rmsd_matrix(poses: list[np.ndarray]) -> np.ndarray:
    """Symmetry-unaware RMSD between poses in the receptor frame (same atom order, no superposition)."""
    n = len(poses)
    D = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            if poses[i] is not None and poses[j] is not None and len(poses[i]) == len(poses[j]):
                D[i, j] = D[j, i] = float(np.sqrt(((poses[i] - poses[j]) ** 2).sum(1).mean()))
            else:
                D[i, j] = D[j, i] = np.nan
    return D


def contact_map(poses: list[np.ndarray], prot: list[dict], cutoff: float = 4.0) -> tuple[list[str], np.ndarray]:
    """Residues (rows) × poses (columns): 1 when any heavy atom of the pose is within the cutoff of the residue."""
    if not prot:
        return [], np.zeros((0, len(poses)))
    P = np.array([a["xyz"] for a in prot], float)
    res = np.array([a["res"] for a in prot])
    hits = []
    for x in poses:
        if x is None:
            hits.append(set()); continue
        d = np.linalg.norm(P[:, None, :] - x[None, :, :], axis=-1).min(1)
        hits.append(set(res[d <= cutoff].tolist()))
    allr = sorted(set().union(*hits), key=lambda r: (int("".join(c for c in r if c.isdigit()) or 0), r))
    M = np.array([[1 if r in h else 0 for h in hits] for r in allr], int) if allr else np.zeros((0, len(poses)))
    return allr, M


def classify_pose_rmsd(name: str, D: np.ndarray, scores: list[float]) -> list[dict]:
    from .figure_text import S
    if D.size < 4:
        return []
    k = min(3, len(D))
    sub = D[:k, :k][np.triu_indices(k, 1)]
    sub = sub[np.isfinite(sub)]
    if not len(sub):
        return []
    m = float(sub.mean())
    if m <= 2.0:
        return [S("good", f"{name}：前 {k} 名姿勢彼此平均 RMSD {m:.1f} Å（≤ 2 Å），低分姿勢收斂到同一結合模式。",
                  f"{name}: the top {k} poses differ by {m:.1f} Å RMSD on average (≤ 2 Å); low-scoring poses converge on one binding mode.")]
    return [S("note", f"{name}：前 {k} 名姿勢彼此平均 RMSD {m:.1f} Å（> 2 Å），分數相近的姿勢採取不同結合模式，需以模擬或實驗判斷。",
              f"{name}: the top {k} poses differ by {m:.1f} Å RMSD on average (> 2 Å); similarly scored poses adopt different binding modes, to be decided by simulation or experiment.")]


def classify_funnel(name: str, poses: list[dict]) -> list[dict]:
    from .figure_text import S
    pts = [(p["rmsd_ref"], p["score"]) for p in poses if p.get("rmsd_ref") is not None]
    if len(pts) < 3:
        return []
    r, s = np.array(pts).T
    rr = float(np.corrcoef(r, s)[0, 1]) if np.std(r) > 0 and np.std(s) > 0 else 0.0
    best_r = float(r[np.argmin(s)])
    if best_r <= 2.0 and rr > 0.3:
        return [S("good", f"{name}：分數最好的姿勢距晶體 {best_r:.1f} Å，且分數隨 RMSD 變差（r = {rr:.2f}），呈現對接漏斗，評分函數能辨認正確結合模式。",
                  f"{name}: the best-scoring pose is {best_r:.1f} Å from the crystal and scores worsen with RMSD (r = {rr:.2f}), a docking funnel: the scoring function recognises the correct mode.")]
    if best_r <= 2.0:
        return [S("note", f"{name}：最佳姿勢接近晶體（{best_r:.1f} Å），但分數與 RMSD 的關係不明顯（r = {rr:.2f}），其他姿勢的分數區辨力有限。",
                  f"{name}: the best pose is close to the crystal ({best_r:.1f} Å) but score and RMSD are weakly related (r = {rr:.2f}); the score discriminates little among the other poses.")]
    return [S("caution", f"{name}：分數最好的姿勢距晶體 {best_r:.1f} Å（> 2 Å），評分函數在此口袋偏好錯誤的結合模式。",
              f"{name}: the best-scoring pose is {best_r:.1f} Å from the crystal (> 2 Å); the scoring function prefers a wrong mode in this pocket.")]


def classify_positions(name: str, cents: np.ndarray, box: dict) -> list[dict]:
    from .figure_text import S
    if len(cents) < 2:
        return []
    spread = float(np.sqrt(((cents - cents.mean(0)) ** 2).sum(1).mean()))
    size = max(box.get("size") or [0])
    if spread <= 3.0:
        return [S("good", f"{name}：所有姿勢的中心彼此平均相距 {spread:.1f} Å（≤ 3 Å），集中在同一個口袋。",
                  f"{name}: pose centres lie within {spread:.1f} Å of each other on average (≤ 3 Å), all in one pocket.")]
    # cents are in rank order: how many poses sit in the same place as the best-scoring one?
    near = int((np.linalg.norm(cents - cents[0], axis=1) <= 4.0).sum())
    n = len(cents)
    if near / n >= 0.6:
        return [S("note", f"{name}：{near}/{n} 個姿勢位於第 1 名姿勢 4 Å 內，構成主要結合位置；其餘 {n - near} 個是分數較差的替代位置（搜尋區最長邊 {size:g} Å）。",
                  f"{name}: {near} of {n} poses lie within 4 Å of the top pose and form the main site; the other {n - near} are lower-scoring "
                  f"alternative sites (longest box edge {size:g} Å).")]
    return [S("warn", f"{name}：只有 {near}/{n} 個姿勢靠近第 1 名姿勢，中心分散 {spread:.1f} Å（搜尋區最長邊 {size:g} Å）；配體在搜尋區內有數個競爭位置，"
                      "單憑對接分數無法決定，建議以分子動力學比較或縮小搜尋區。",
              f"{name}: only {near} of {n} poses lie near the top pose and the centres spread over {spread:.1f} Å (longest box edge {size:g} Å); "
              "the ligand has several competing sites that docking scores alone cannot decide, so compare them by simulation or narrow the box.")]


def classify_contact_map(name: str, residues: list[str], M: np.ndarray) -> list[dict]:
    from .figure_text import S
    if not len(residues) or M.size == 0:
        return []
    frac = M.mean(1)
    core = [r for r, f in zip(residues, frac) if f >= 0.7]
    if core:
        return [S("good", f"{name}：{len(core)} 個殘基在 70 % 以上的姿勢中都被接觸（{'、'.join(core[:8])}），構成穩定的結合位核心。",
                  f"{name}: {len(core)} residues are contacted by at least 70 % of the poses ({', '.join(core[:8])}), forming a consistent binding-site core.")]
    return [S("note", f"{name}：沒有殘基被多數姿勢共同接觸，各姿勢的結合位置不一致。", f"{name}: no residue is contacted by most poses; the poses do not share a binding site.")]


def classify_ligand_compare(rows: list[dict]) -> list[dict]:
    from .figure_text import S
    if len(rows) < 2:
        return []
    by_s = sorted(rows, key=lambda r: r["score"])
    by_le = sorted([r for r in rows if r.get("le") is not None], key=lambda r: r["le"])
    out = [S("note", f"分數最好的是 {by_s[0]['name']}（{by_s[0]['score']:.2f} kcal mol⁻¹）" +
             (f"；配體效率最好的是 {by_le[0]['name']}（{by_le[0]['le']:.2f} kcal mol⁻¹ 每重原子）" if by_le else "") + "。",
             f"The best score belongs to {by_s[0]['name']} ({by_s[0]['score']:.2f} kcal mol⁻¹)" +
             (f"; the best ligand efficiency to {by_le[0]['name']} ({by_le[0]['le']:.2f} kcal mol⁻¹ per heavy atom)" if by_le else "") + ".")]
    if len(by_s) > 1 and by_s[1]["score"] - by_s[0]["score"] < 1.0:
        out.append(S("note", f"前兩個配體分數相差 {by_s[1]['score'] - by_s[0]['score']:.2f} kcal mol⁻¹（< 1），在誤差內不能排序。",
                     f"The top two ligands differ by {by_s[1]['score'] - by_s[0]['score']:.2f} kcal mol⁻¹ (< 1) and cannot be ordered within error."))
    return out


# ------------------------------------------------------------------------------------------- D-60 multi-ligand
def classify_joint_poses(poses: list[dict], names: list[str], chosen: int | None, charges: list[int] | None = None,
                         ll_min: float = 3.3, ll_max: float = 4.5, min_contacts: int = 10) -> list[dict]:
    from .figure_text import S
    if not poses or poses[0].get("min_ll_distance") is None:
        return []
    ok = [p for p in poses if p.get("min_ll_distance") is not None and ll_min <= p["min_ll_distance"] <= ll_max
          and all(c >= min_contacts for c in (p.get("contacts_per_ligand") or [0]))]
    clash = [p["rank"] for p in poses if (p.get("min_ll_distance") or 99) < ll_min]
    n = len(poses)
    out = []
    if ok:
        lvl = "good" if len(ok) / n >= 1 / 3 else "note"
        out.append(S(lvl, f"{len(ok)}/{n} 個聯合姿勢同時滿足共同佔位（配體間 {ll_min}–{ll_max} Å）且每個配體都埋入口袋"
                          + ("；共同佔位只是搜尋結果中的少數，應視為待驗證的假說。" if lvl == "note" else "。"),
                     f"{len(ok)} of {n} joint poses show co-occupancy (ligands {ll_min}–{ll_max} Å apart) with every ligand buried"
                     + ("; co-occupancy is a minority outcome of the search and should be treated as a hypothesis to test." if lvl == "note" else ".")))
    else:
        out.append(S("warn", f"沒有任何聯合姿勢同時滿足共同佔位與每個配體埋入；口袋可能容不下全部配體。",
                     "No joint pose combines co-occupancy with every ligand buried; the pocket may not hold all the ligands."))
    if clash:
        out.append(S("note", f"名次 {', '.join(map(str, clash[:6]))} 的配體彼此過近（< {ll_min} Å），已排除。",
                     f"Ranks {', '.join(map(str, clash[:6]))} place the ligands too close (< {ll_min} Å) and were excluded."))
    if charges and (sum(1 for q in charges if q > 0) > 1 or sum(1 for q in charges if q < 0) > 1):
        out.append(S("caution", "有兩個以上同號帶電的配體同時在口袋；Vina 沒有靜電項，會低估它們的互斥，模擬中可能分開。",
                     "Two or more ligands carry charges of the same sign; Vina has no electrostatic term and underestimates their "
                     "repulsion, so they may separate in simulation."))
    return out


def classify_joint_positions(cents: dict) -> list[dict]:
    """cents: {ligand: (n_poses × 3)} in joint-rank order."""
    from .figure_text import S
    names = [n for n, X in cents.items() if len(X) >= 2]
    if len(names) < 2:
        return []
    out = []
    spread = {n: float(np.sqrt(((np.asarray(cents[n]) - np.asarray(cents[n]).mean(0)) ** 2).sum(1).mean())) for n in names}
    loose = [n for n, v in spread.items() if v > 3.0]
    # site exchange: in some pose, ligand A sits where another ligand sat in the top pose
    swaps = 0
    k = min(len(cents[n]) for n in names)
    for r in range(1, k):
        for a in names:
            for b in names:
                if a != b and np.linalg.norm(np.asarray(cents[a])[r] - np.asarray(cents[b])[0]) < 2.0:
                    swaps += 1
    if swaps:
        out.append(S("caution", f"有 {swaps} 次配體互換位置（某姿勢中配體落在另一配體第 1 名的位置）；哪個配體佔哪個子位點，對接無法決定。",
                     f"Ligands exchange sites {swaps} time(s) (a ligand sits where another ligand sat in the top pose); docking does not "
                     "decide which ligand occupies which subsite."))
    if loose:
        out.append(S("note", f"{'、'.join(loose)} 的位置在各姿勢間分散（> 3 Å），其結合位置較不確定。",
                     f"The position of {', '.join(loose)} varies across poses (> 3 Å); its site is less certain."))
    if not out:
        out.append(S("good", "每個配體在各姿勢中都停在自己的位置，未互換，排列一致。",
                     "Each ligand keeps its own site across the poses without exchanging places; the arrangement is consistent."))
    return out


def subsite_map(lig_xyz: dict, prot: list[dict], cutoff: float = 4.0) -> tuple[list[str], np.ndarray]:
    """Residues (rows) × ligands (columns) for one joint pose."""
    names = list(lig_xyz)
    res, M = contact_map([lig_xyz[n] for n in names], prot, cutoff)
    return res, M


def classify_subsites(residues: list[str], M: np.ndarray, names: list[str]) -> list[dict]:
    from .figure_text import S
    if M.size == 0 or len(names) < 2:
        return []
    shared = [r for r, row in zip(residues, M) if row.sum() >= 2]
    own = {n: [r for r, row in zip(residues, M) if row[k] and row.sum() == 1] for k, n in enumerate(names)}
    out = []
    if len(shared) >= 3:
        out.append(S("note", f"{len(shared)} 個殘基同時接觸兩個以上配體（{'、'.join(shared[:6])}）：配體共用同一子位點、彼此相鄰，可能互相影響或競爭。",
                     f"{len(shared)} residues touch two or more ligands ({', '.join(shared[:6])}): the ligands share a subsite side by "
                     "side and may influence or compete with each other."))
    elif shared:
        out.append(S("good", f"配體各自佔據不同子位點，只在 {'、'.join(shared)} 交界。",
                     f"The ligands occupy separate subsites that meet only at {', '.join(shared)}."))
    else:
        out.append(S("good", "配體佔據完全不同的子位點，沒有共同接觸的殘基。", "The ligands occupy fully separate subsites with no residue in common."))
    thin = [n for n, v in own.items() if len(v) + len(shared) < 4]
    if thin:
        out.append(S("caution", f"{'、'.join(thin)} 只接觸少數殘基，主要靠其他配體固定，模擬中較可能離開。",
                     f"{', '.join(thin)} touches only a few residues and is held mainly by the other ligand(s); it is the more likely to leave in simulation."))
    return out


def classify_ll_distance(series: dict, restrained: bool = False) -> list[dict]:
    """series: {pair: (t_ns, distance_A)} between ligand centroids during MD.  `restrained`: the multi-ligand build holds
    each ligand centroid within ±4 Å of the pocket (flat-bottom), so complete departure cannot happen by construction."""
    from .figure_text import S
    out = []
    for pair, (t, y) in series.items():
        y = np.asarray(y, float)
        if len(y) < 5:
            continue
        a, b = float(y[:max(1, len(y) // 10)].mean()), float(y[-max(1, len(y) // 5):].mean())
        dlt = b - a
        nm = pair.replace("-", "–")
        if abs(dlt) <= 2.0:
            out.append(S("good", f"{nm}：配體中心距離由 {a:.1f} Å 到 {b:.1f} Å（變化 ≤ 2 Å），共同佔位在模擬中維持。",
                         f"{nm}: the ligand centroids go from {a:.1f} to {b:.1f} Å (change ≤ 2 Å); co-occupancy holds during the simulation."))
        elif dlt <= 5.0:
            out.append(S("note", f"{nm}：距離由 {a:.1f} Å 變為 {b:.1f} Å，配體重新排列但仍相鄰。",
                         f"{nm}: the distance changes from {a:.1f} to {b:.1f} Å; the ligands rearrange but stay neighbours."))
        else:
            out.append(S("warn", f"{nm}：距離由 {a:.1f} Å 增加到 {b:.1f} Å（> 5 Å），共同佔位沒有維持，對接的聯合姿勢不被模擬支持。",
                         f"{nm}: the distance grows from {a:.1f} to {b:.1f} Å (> 5 Å); co-occupancy is not maintained and the joint docking pose is not supported by the simulation."))
    if out and restrained:
        out.append(S("caution", "此系統的配體質心有平底限制（離口袋中心 ±4 Å 內無力），完全離開被限制擋住；距離穩定只說明配體在口袋內的排列，"
                                "不能當作共同佔位自發穩定的證據。要驗證，需關閉限制再跑一次。",
                     "Each ligand centroid in this system is held by a flat-bottom restraint (no force within ±4 Å of the pocket "
                     "centre), so full departure is prevented by construction; a steady distance describes the arrangement inside "
                     "the pocket and is not evidence that co-occupancy is stable on its own. To test that, rerun without the restraint."))
    return out
