"""Docking analysis figures (D-59): pose similarity, docking funnel, pose positions in the box, contact map across
poses, ligand comparison.  Pure numpy on the pose SDF files and the docking receptor PDB.
Scenario sentences are (zh, en, ja, ko) through figure_text.S (D-74)."""
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
        return [S("good",
                  f"{name}：前 {k} 名姿勢彼此的平均 RMSD 為 {m:.1f} Å（≤ 2 Å），低分姿勢收斂到同一種結合模式。",
                  f"{name}: the top {k} poses differ by {m:.1f} Å RMSD on average (≤ 2 Å), so the low-scoring poses converge on one binding mode.",
                  f"{name}：上位 {k} ポーズ間の平均 RMSD は {m:.1f} Å（≤ 2 Å）で、低スコアのポーズは同じ結合様式に収束しています。",
                  f"{name}: 상위 {k}개 포즈 사이의 평균 RMSD가 {m:.1f} Å(≤ 2 Å)로, 낮은 점수의 포즈들이 같은 결합 모드로 수렴했습니다.")]
    return [S("note",
              f"{name}：前 {k} 名姿勢彼此的平均 RMSD 為 {m:.1f} Å（> 2 Å），分數相近的姿勢採取不同的結合模式，要靠模擬或實驗判斷。",
              f"{name}: the top {k} poses differ by {m:.1f} Å RMSD on average (> 2 Å). Similarly scored poses adopt different "
              "binding modes, and simulation or experiment has to decide between them.",
              f"{name}：上位 {k} ポーズ間の平均 RMSD は {m:.1f} Å（> 2 Å）です。スコアが近いポーズが異なる結合様式をとっているため、"
              "シミュレーションか実験で判断する必要があります。",
              f"{name}: 상위 {k}개 포즈 사이의 평균 RMSD가 {m:.1f} Å(> 2 Å)입니다. 점수가 비슷한 포즈들이 서로 다른 결합 모드를 취하므로 "
              "시뮬레이션이나 실험으로 판단해야 합니다.")]


def classify_funnel(name: str, poses: list[dict]) -> list[dict]:
    from .figure_text import S
    pts = [(p["rmsd_ref"], p["score"]) for p in poses if p.get("rmsd_ref") is not None]
    if len(pts) < 3:
        return []
    r, s = np.array(pts).T
    rr = float(np.corrcoef(r, s)[0, 1]) if np.std(r) > 0 and np.std(s) > 0 else 0.0
    best_r = float(r[np.argmin(s)])
    if best_r <= 2.0 and rr > 0.3:
        return [S("good",
                  f"{name}：分數最好的姿勢距晶體 {best_r:.1f} Å，而且分數隨 RMSD 變大而變差（r = {rr:.2f}），形成對接漏斗。評分函數能辨認正確的結合模式。",
                  f"{name}: the best-scoring pose is {best_r:.1f} Å from the crystal and scores worsen with RMSD (r = {rr:.2f}), "
                  "which is a docking funnel. The scoring function recognises the correct mode.",
                  f"{name}：最もスコアの良いポーズは結晶から {best_r:.1f} Å で、RMSD が大きいほどスコアが悪くなります（r = {rr:.2f}）。"
                  "ドッキングファネルになっており、スコア関数は正しい結合様式を見分けています。",
                  f"{name}: 점수가 가장 좋은 포즈는 결정 구조에서 {best_r:.1f} Å 떨어져 있고, RMSD가 클수록 점수가 나빠집니다(r = {rr:.2f}). "
                  "도킹 깔때기가 나타나므로 점수 함수가 올바른 결합 모드를 알아봅니다.")]
    if best_r <= 2.0:
        return [S("note",
                  f"{name}：最佳姿勢接近晶體（{best_r:.1f} Å），但分數與 RMSD 的關係不明顯（r = {rr:.2f}），對其他姿勢的區辨力有限。",
                  f"{name}: the best pose is close to the crystal ({best_r:.1f} Å) but score and RMSD are weakly related "
                  f"(r = {rr:.2f}). The score discriminates little among the other poses.",
                  f"{name}：最良ポーズは結晶に近い（{best_r:.1f} Å）ものの、スコアと RMSD の関係ははっきりしません（r = {rr:.2f}）。"
                  "ほかのポーズを見分ける力は限られています。",
                  f"{name}: 최고 포즈는 결정 구조에 가깝지만({best_r:.1f} Å) 점수와 RMSD의 관계가 뚜렷하지 않습니다(r = {rr:.2f}). "
                  "다른 포즈를 구별하는 힘은 제한적입니다.")]
    return [S("caution",
              f"{name}：分數最好的姿勢距晶體 {best_r:.1f} Å（> 2 Å），評分函數在這個口袋偏好錯誤的結合模式。",
              f"{name}: the best-scoring pose is {best_r:.1f} Å from the crystal (> 2 Å), so the scoring function prefers a wrong mode in this pocket.",
              f"{name}：最もスコアの良いポーズは結晶から {best_r:.1f} Å（> 2 Å）離れています。このポケットでは、スコア関数が誤った結合様式を好んでいます。",
              f"{name}: 점수가 가장 좋은 포즈가 결정 구조에서 {best_r:.1f} Å(> 2 Å) 떨어져 있습니다. 이 포켓에서는 점수 함수가 잘못된 결합 모드를 선호합니다.")]


def classify_positions(name: str, cents: np.ndarray, box: dict) -> list[dict]:
    from .figure_text import S
    if len(cents) < 2:
        return []
    spread = float(np.sqrt(((cents - cents.mean(0)) ** 2).sum(1).mean()))
    size = max(box.get("size") or [0])
    if spread <= 3.0:
        return [S("good",
                  f"{name}：所有姿勢的中心彼此平均相距 {spread:.1f} Å（≤ 3 Å），集中在同一個口袋。",
                  f"{name}: pose centres lie within {spread:.1f} Å of each other on average (≤ 3 Å), all in one pocket.",
                  f"{name}：全ポーズの中心は平均 {spread:.1f} Å 以内に集まっており（≤ 3 Å）、同じポケットにあります。",
                  f"{name}: 모든 포즈 중심이 서로 평균 {spread:.1f} Å 이내에 있으며(≤ 3 Å) 같은 포켓에 모여 있습니다.")]
    # cents are in rank order: how many poses sit in the same place as the best-scoring one?
    near = int((np.linalg.norm(cents - cents[0], axis=1) <= 4.0).sum())
    n = len(cents)
    if near / n >= 0.6:
        return [S("note",
                  f"{name}：{n} 個姿勢中有 {near} 個位於第 1 名姿勢 4 Å 內，構成主要結合位置。其餘 {n - near} 個是分數較差的替代位置（搜尋區最長邊 {size:g} Å）。",
                  f"{name}: {near} of {n} poses lie within 4 Å of the top pose and form the main site. The other {n - near} are "
                  f"lower-scoring alternative sites (longest box edge {size:g} Å).",
                  f"{name}：{n} ポーズのうち {near} ポーズが1位のポーズから 4 Å 以内にあり、主な結合位置になっています。"
                  f"残りの {n - near} ポーズはスコアの劣る別の位置です（探索領域の最長辺 {size:g} Å）。",
                  f"{name}: 포즈 {n}개 중 {near}개가 1위 포즈에서 4 Å 이내에 있어 주요 결합 위치를 이룹니다. "
                  f"나머지 {n - near}개는 점수가 낮은 대체 위치입니다(탐색 영역 최장 변 {size:g} Å).")]
    return [S("warn",
              f"{name}：{n} 個姿勢中只有 {near} 個靠近第 1 名姿勢，中心分散 {spread:.1f} Å（搜尋區最長邊 {size:g} Å）。"
              "配體在搜尋區內有幾個互相競爭的位置，單憑對接分數無法決定。請用分子動力學比較，或縮小搜尋區。",
              f"{name}: only {near} of {n} poses lie near the top pose and the centres spread over {spread:.1f} Å (longest box "
              f"edge {size:g} Å). The ligand has several competing sites that docking scores alone cannot decide, so compare "
              "them by simulation or narrow the box.",
              f"{name}：1位のポーズの近くにあるのは {n} ポーズ中 {near} ポーズだけで、中心は {spread:.1f} Å にわたって散らばっています"
              f"（探索領域の最長辺 {size:g} Å）。探索領域内に競合する位置が複数あり、ドッキングスコアだけでは決められません。"
              "分子動力学で比べるか、探索領域を狭めてください。",
              f"{name}: 포즈 {n}개 중 {near}개만 1위 포즈 근처에 있고, 중심이 {spread:.1f} Å에 걸쳐 흩어져 있습니다"
              f"(탐색 영역 최장 변 {size:g} Å). 탐색 영역 안에 경쟁하는 위치가 여러 개 있어 도킹 점수만으로는 정할 수 없습니다. "
              "분자동역학으로 비교하거나 탐색 영역을 좁히십시오.")]


def classify_contact_map(name: str, residues: list[str], M: np.ndarray) -> list[dict]:
    from .figure_text import S
    if not len(residues) or M.size == 0:
        return []
    frac = M.mean(1)
    core = [r for r, f in zip(residues, frac) if f >= 0.7]
    if core:
        cz, ce = "、".join(core[:8]), ", ".join(core[:8])
        return [S("good",
                  f"{name}：{len(core)} 個殘基在 70 % 以上的姿勢中都有接觸（{cz}），構成穩定的結合位核心。",
                  f"{name}: {len(core)} residues are contacted by at least 70 % of the poses ({ce}), forming a consistent binding-site core.",
                  f"{name}：{len(core)} 個の残基が 70 % 以上のポーズで接触しており（{cz}）、安定した結合部位の中心をなしています。",
                  f"{name}: 잔기 {len(core)}개가 포즈의 70 % 이상과 접촉하며({ce}) 일관된 결합 부위 핵심을 이룹니다.")]
    return [S("note",
              f"{name}：沒有殘基被多數姿勢共同接觸，各姿勢的結合位置不一致。",
              f"{name}: no residue is contacted by most poses, so the poses do not share a binding site.",
              f"{name}：大多数のポーズに共通して接触する残基はありません。ポーズごとに結合位置が異なります。",
              f"{name}: 대부분의 포즈가 공통으로 접촉하는 잔기가 없습니다. 포즈마다 결합 위치가 다릅니다.")]


def classify_ligand_compare(rows: list[dict]) -> list[dict]:
    from .figure_text import S
    if len(rows) < 2:
        return []
    by_s = sorted(rows, key=lambda r: r["score"])
    by_le = sorted([r for r in rows if r.get("le") is not None], key=lambda r: r["le"])
    bn, bs = by_s[0]["name"], by_s[0]["score"]
    ln, lv = (by_le[0]["name"], by_le[0]["le"]) if by_le else (None, None)
    out = [S("note",
             f"分數最好的是 {bn}（{bs:.2f} kcal mol⁻¹）" + (f"，配體效率最好的是 {ln}（每個重原子 {lv:.2f} kcal mol⁻¹）" if by_le else "") + "。",
             f"The best score belongs to {bn} ({bs:.2f} kcal mol⁻¹)"
             + (f", and the best ligand efficiency to {ln} ({lv:.2f} kcal mol⁻¹ per heavy atom)" if by_le else "") + ".",
             f"スコアが最も良いのは {bn}（{bs:.2f} kcal mol⁻¹）" + (f"、リガンド効率が最も良いのは {ln}（重原子あたり {lv:.2f} kcal mol⁻¹）" if by_le else "") + "です。",
             f"점수가 가장 좋은 리간드는 {bn}({bs:.2f} kcal mol⁻¹)"
             + (f", 리간드 효율이 가장 좋은 리간드는 {ln}(중원자당 {lv:.2f} kcal mol⁻¹)" if by_le else "") + "입니다.")]
    if len(by_s) > 1 and by_s[1]["score"] - by_s[0]["score"] < 1.0:
        diff = by_s[1]["score"] - by_s[0]["score"]
        out.append(S("note",
                     f"前兩個配體的分數相差 {diff:.2f} kcal mol⁻¹（< 1），在誤差內無法排序。",
                     f"The top two ligands differ by {diff:.2f} kcal mol⁻¹ (< 1) and cannot be ordered within error.",
                     f"上位2つのリガンドのスコア差は {diff:.2f} kcal mol⁻¹（< 1）で、誤差の範囲内では順位をつけられません。",
                     f"상위 두 리간드의 점수 차이는 {diff:.2f} kcal mol⁻¹(< 1)로, 오차 범위 안에서는 순위를 매길 수 없습니다."))
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
        few = lvl == "note"
        out.append(S(lvl,
                     f"{n} 個聯合姿勢中有 {len(ok)} 個同時滿足共同佔位（配體間 {ll_min}–{ll_max} Å），且每個配體都埋入口袋"
                     + ("。共同佔位只是搜尋結果中的少數，應當作待驗證的假說。" if few else "。"),
                     f"{len(ok)} of {n} joint poses show co-occupancy (ligands {ll_min}–{ll_max} Å apart) with every ligand buried"
                     + (". Co-occupancy is a minority outcome of the search and should be treated as a hypothesis to test." if few else "."),
                     f"{n} 個の共同ポーズのうち {len(ok)} 個が同時占有（リガンド間 {ll_min}–{ll_max} Å）を満たし、どのリガンドもポケットに埋まっています"
                     + ("。同時占有は探索結果の少数派なので、検証が必要な仮説として扱ってください。" if few else "。"),
                     f"공동 포즈 {n}개 중 {len(ok)}개가 동시 점유(리간드 간 {ll_min}–{ll_max} Å)를 만족하며 모든 리간드가 포켓에 묻혀 있습니다"
                     + (". 동시 점유는 탐색 결과 중 소수이므로 검증해야 할 가설로 다루십시오." if few else ".")))
    else:
        out.append(S("warn",
                     "沒有任何聯合姿勢同時滿足共同佔位與每個配體埋入，口袋可能容不下全部配體。",
                     "No joint pose combines co-occupancy with every ligand buried. The pocket may not hold all the ligands.",
                     "同時占有とすべてのリガンドの埋没を両立する共同ポーズはありません。ポケットにすべてのリガンドが入りきらない可能性があります。",
                     "동시 점유와 모든 리간드의 매몰을 함께 만족하는 공동 포즈가 없습니다. 포켓이 모든 리간드를 수용하지 못할 수 있습니다."))
    if clash:
        rk = ", ".join(map(str, clash[:6]))
        out.append(S("note",
                     f"名次 {rk} 的配體彼此過近（< {ll_min} Å），已排除。",
                     f"Ranks {rk} place the ligands too close (< {ll_min} Å) and were excluded.",
                     f"順位 {rk} のポーズはリガンド同士が近すぎる（< {ll_min} Å）ため除外しました。",
                     f"순위 {rk} 포즈는 리간드끼리 너무 가까워(< {ll_min} Å) 제외했습니다."))
    if charges and (sum(1 for q in charges if q > 0) > 1 or sum(1 for q in charges if q < 0) > 1):
        out.append(S("caution",
                     "有兩個以上同號帶電的配體同時在口袋中。Vina 沒有靜電項，會低估它們之間的互斥，模擬中它們可能分開。",
                     "Two or more ligands carry charges of the same sign. Vina has no electrostatic term and underestimates their "
                     "repulsion, so they may separate in simulation.",
                     "同じ符号の電荷をもつリガンドが2つ以上ポケットにあります。Vina には静電項がないため反発が過小評価され、シミュレーションでは離れる可能性があります。",
                     "같은 부호의 전하를 띤 리간드가 두 개 이상 포켓에 있습니다. Vina에는 정전기 항이 없어 이들 사이의 반발을 과소평가하므로 "
                     "시뮬레이션에서 떨어질 수 있습니다."))
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
        out.append(S("caution",
                     f"配體互換位置 {swaps} 次，也就是某個姿勢中，配體落在另一個配體第 1 名的位置。哪個配體佔哪個子位點，對接無法決定。",
                     f"Ligands exchange sites {swaps} time(s), meaning a ligand sits where another ligand sat in the top pose. "
                     "Docking does not decide which ligand occupies which subsite.",
                     f"リガンドの位置の入れ替わりが {swaps} 回あります。あるポーズで、リガンドが別のリガンドの1位の位置に入っているということです。"
                     "どのリガンドがどのサブサイトを占めるかは、ドッキングでは決められません。",
                     f"리간드가 자리를 바꾼 경우가 {swaps}번 있습니다. 어떤 포즈에서 한 리간드가 다른 리간드의 1위 포즈 위치에 들어갔다는 뜻입니다. "
                     "어느 리간드가 어느 하위 부위를 차지하는지는 도킹으로 정할 수 없습니다."))
    if loose:
        lz, le = "、".join(loose), ", ".join(loose)
        out.append(S("note",
                     f"{lz} 的位置在各姿勢之間分散（> 3 Å），結合位置較不確定。",
                     f"The position of {le} varies across poses (> 3 Å), so its site is less certain.",
                     f"{lz} の位置はポーズによってばらついており（> 3 Å）、結合位置はあまり確かではありません。",
                     f"{le}의 위치가 포즈마다 흩어져 있어(> 3 Å) 결합 위치가 덜 확실합니다."))
    if not out:
        out.append(S("good",
                     "每個配體在各姿勢中都停在自己的位置，沒有互換，排列一致。",
                     "Each ligand keeps its own site across the poses without exchanging places, so the arrangement is consistent.",
                     "各リガンドはどのポーズでも自分の位置にとどまり、入れ替わりはありません。配置は一貫しています。",
                     "각 리간드가 모든 포즈에서 자기 자리를 지키며 자리를 바꾸지 않습니다. 배치가 일관됩니다."))
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
        sz, se = "、".join(shared[:6]), ", ".join(shared[:6])
        out.append(S("note",
                     f"{len(shared)} 個殘基同時接觸兩個以上的配體（{sz}）。配體共用同一個子位點、彼此相鄰，可能互相影響或競爭。",
                     f"{len(shared)} residues touch two or more ligands ({se}). The ligands share a subsite side by side and may "
                     "influence or compete with each other.",
                     f"{len(shared)} 個の残基が2つ以上のリガンドに同時に接触しています（{sz}）。リガンドは同じサブサイトを隣り合って共有しており、"
                     "互いに影響し合うか競合する可能性があります。",
                     f"잔기 {len(shared)}개가 두 개 이상의 리간드와 동시에 접촉합니다({se}). 리간드들이 같은 하위 부위를 나란히 공유하므로 "
                     "서로 영향을 주거나 경쟁할 수 있습니다."))
    elif shared:
        sz, se = "、".join(shared), ", ".join(shared)
        out.append(S("good",
                     f"配體各自佔據不同的子位點，只在 {sz} 交界。",
                     f"The ligands occupy separate subsites that meet only at {se}.",
                     f"リガンドはそれぞれ別のサブサイトを占めており、{sz} で接しているだけです。",
                     f"리간드가 각자 다른 하위 부위를 차지하며 {se}에서만 맞닿습니다."))
    else:
        out.append(S("good",
                     "配體佔據完全不同的子位點，沒有共同接觸的殘基。",
                     "The ligands occupy fully separate subsites with no residue in common.",
                     "リガンドは完全に別々のサブサイトを占めており、共通して接触する残基はありません。",
                     "리간드가 완전히 분리된 하위 부위를 차지하며 공통으로 접촉하는 잔기가 없습니다."))
    thin = [n for n, v in own.items() if len(v) + len(shared) < 4]
    if thin:
        tz, te = "、".join(thin), ", ".join(thin)
        out.append(S("caution",
                     f"{tz} 只接觸少數殘基，主要靠其他配體固定，模擬中比較可能離開。",
                     f"{te} touches only a few residues and is held mainly by the other ligand(s). It is the more likely to leave in simulation.",
                     f"{tz} は少数の残基にしか接触しておらず、主にほかのリガンドによって固定されています。シミュレーションでは離れやすいと考えられます。",
                     f"{te}: 소수의 잔기와만 접촉하며 주로 다른 리간드에 의해 고정됩니다. 시뮬레이션에서 떠날 가능성이 더 큽니다."))
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
            out.append(S("good",
                         f"{nm}：配體中心距離從 {a:.1f} Å 變為 {b:.1f} Å（變化 ≤ 2 Å），共同佔位在模擬中維持。",
                         f"{nm}: the ligand centroids go from {a:.1f} to {b:.1f} Å apart (change ≤ 2 Å), so co-occupancy holds during the simulation.",
                         f"{nm}：リガンド中心間の距離は {a:.1f} Å から {b:.1f} Å になりました（変化 ≤ 2 Å）。同時占有はシミュレーション中も保たれています。",
                         f"{nm}: 리간드 중심 거리가 처음 {a:.1f} Å, 마지막 {b:.1f} Å입니다(변화 ≤ 2 Å). 동시 점유가 시뮬레이션 동안 유지됩니다."))
        elif dlt <= 5.0:
            out.append(S("note",
                         f"{nm}：距離從 {a:.1f} Å 變為 {b:.1f} Å，配體重新排列，但仍然相鄰。",
                         f"{nm}: the distance changes from {a:.1f} to {b:.1f} Å. The ligands rearrange but stay neighbours.",
                         f"{nm}：距離は {a:.1f} Å から {b:.1f} Å に変わりました。リガンドは並び直していますが、まだ隣り合っています。",
                         f"{nm}: 거리가 처음 {a:.1f} Å, 마지막 {b:.1f} Å입니다. 리간드가 재배열되었지만 여전히 이웃해 있습니다."))
        else:
            out.append(S("warn",
                         f"{nm}：距離從 {a:.1f} Å 增加到 {b:.1f} Å（> 5 Å），共同佔位沒有維持，模擬不支持對接得到的聯合姿勢。",
                         f"{nm}: the distance grows from {a:.1f} to {b:.1f} Å (> 5 Å). Co-occupancy is not maintained and the "
                         "simulation does not support the joint docking pose.",
                         f"{nm}：距離が {a:.1f} Å から {b:.1f} Å に増えました（> 5 Å）。同時占有は保たれておらず、ドッキングで得た共同ポーズはシミュレーションで支持されません。",
                         f"{nm}: 거리가 처음 {a:.1f} Å에서 마지막 {b:.1f} Å까지 늘었습니다(> 5 Å). 동시 점유가 유지되지 않으므로 "
                         "시뮬레이션이 도킹 공동 포즈를 뒷받침하지 않습니다."))
    if out and restrained:
        out.append(S("caution",
                     "這個系統的配體質心有平底限制（離口袋中心 ±4 Å 內不施力），完全離開會被限制擋住。距離穩定只說明配體在口袋內的排列，"
                     "不能當作共同佔位自發穩定的證據。要驗證，請關閉限制再跑一次。",
                     "Each ligand centroid in this system is held by a flat-bottom restraint, with no force within ±4 Å of the "
                     "pocket centre, so full departure is prevented by construction. A steady distance describes the arrangement "
                     "inside the pocket and is not evidence that co-occupancy is stable on its own. To test that, rerun without "
                     "the restraint.",
                     "この系では各リガンドの重心に平底型の拘束をかけています（ポケット中心から ±4 Å 以内では力がかかりません）。"
                     "そのため完全に離れることは拘束で防がれています。距離が安定していても、ポケット内での配置を示すだけで、"
                     "同時占有がそれ自体で安定している根拠にはなりません。確かめるには拘束を外してもう一度実行してください。",
                     "이 시스템에서는 각 리간드 질량 중심에 평저형 구속을 걸었습니다(포켓 중심에서 ±4 Å 이내에서는 힘이 없음). "
                     "따라서 완전히 떠나는 것은 구속으로 막혀 있습니다. 거리가 안정적이어도 포켓 안의 배치를 보여 줄 뿐, "
                     "동시 점유가 스스로 안정하다는 근거는 아닙니다. 확인하려면 구속을 끄고 다시 실행하십시오."))
    return out
