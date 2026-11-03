"""Data-driven interpretation for the workflow report (D-52).

Each function reads the numbers a step produced and returns findings: {"level": good|note|caution, "text": (zh, en, ja, ko)}.
Thresholds are stated in the text itself, so a reader can see why a sentence was written.  Pure Python + numpy.
"""
from __future__ import annotations

import numpy as np


def F(level: str, zh: str, en: str, ja: str = "", ko: str = "") -> dict:
    """One finding.  Positional order zh, en, ja, ko (D-74); missing Japanese or Korean falls back to English."""
    return {"level": level, "text": (zh, en, ja or en, ko or en)}


# ----------------------------------------------------------------------------------- structure
def structure(gates: list[dict]) -> list[dict]:
    out = []
    n = {s: sum(1 for g in gates if g.get("status") == s) for s in ("PASS", "AUTO_FIXED", "NEEDS_HUMAN")}
    if not gates:
        return [F("note", "沒有結構可信度紀錄。", "No structure-validity record is available.",
                  "構造の信頼性の記録はありません。", "구조 신뢰성 기록이 없습니다.")]
    out.append(F("good" if not n["NEEDS_HUMAN"] else "caution",
                 f"結構檢查共 {len(gates)} 項，{n['PASS']} 項通過，{n['AUTO_FIXED']} 項已自動修正並記錄，{n['NEEDS_HUMAN']} 項需要你決定。",
                 f"Of {len(gates)} structure checks, {n['PASS']} passed, {n['AUTO_FIXED']} were corrected automatically and "
                 f"recorded, and {n['NEEDS_HUMAN']} need your decision.",
                 f"構造チェック {len(gates)} 項目のうち、{n['PASS']} 項目が合格、{n['AUTO_FIXED']} 項目は自動で修正済み（記録あり）、"
                 f"{n['NEEDS_HUMAN']} 項目は判断が必要です。",
                 f"구조 검사 {len(gates)}개 항목 중 {n['PASS']}개 통과, {n['AUTO_FIXED']}개 자동 수정됨(기록됨), "
                 f"{n['NEEDS_HUMAN']}개는 결정이 필요합니다."))
    for g in gates:
        if g.get("name") == "resolution" and g.get("status") != "PASS":
            out.append(F("note",
                         "解析度低於 2.5 Å 時，側鏈與水分子的位置不確定度較高，判讀口袋內的氫鍵要保守。",
                         "Below 2.5 Å resolution, side-chain and water positions are uncertain, so read pocket hydrogen bonds conservatively.",
                         "分解能が 2.5 Å より低いと側鎖や水分子の位置の不確かさが大きくなるため、ポケット内の水素結合は慎重に解釈してください。",
                         "분해능이 2.5 Å보다 낮으면 곁사슬과 물 분자 위치의 불확실성이 커지므로 포켓 안의 수소 결합은 보수적으로 해석하십시오."))
    return out


# ----------------------------------------------------------------------------------- docking
def docking(res: dict, sel: dict) -> list[dict]:
    out = []
    chosen = {v.get("entry"): v for v in (sel.get("ligands") or {}).values()}
    for e in res.get("entries") or []:
        poses = e.get("poses") or []
        if not poses:
            continue
        name = e["name"]
        best = min(p["score"] for p in poses)
        c = chosen.get(name, {})
        rank = c.get("rank") or e.get("recommended_rank") or 1
        p = poses[rank - 1] if 0 < rank <= len(poses) else poses[0]
        scores = sorted(q["score"] for q in poses)
        gap = scores[1] - scores[0] if len(scores) > 1 else None
        frac = min(1.0, (p.get("cluster_size") or 1) / max(1, len(poses)))
        cs = p.get("cluster_size", 1)
        out.append(F("good" if frac >= 0.3 else "note",
                     f"{name}：最佳分數 {best:.2f} kcal mol⁻¹，選用第 {rank} 名（{p['score']:.2f} kcal mol⁻¹），所屬叢集含 {cs} 個姿勢（{frac:.0%}）。",
                     f"{name}: best score {best:.2f} kcal mol⁻¹. Pose {rank} was used ({p['score']:.2f} kcal mol⁻¹) and its "
                     f"cluster holds {cs} poses ({frac:.0%}).",
                     f"{name}：最良スコアは {best:.2f} kcal mol⁻¹ です。採用したのは {rank} 位のポーズ（{p['score']:.2f} kcal mol⁻¹）で、"
                     f"そのクラスターには {cs} 個のポーズ（{frac:.0%}）が含まれます。",
                     f"{name}: 최고 점수는 {best:.2f} kcal mol⁻¹입니다. 선택한 포즈는 {rank}위({p['score']:.2f} kcal mol⁻¹)이며, "
                     f"해당 클러스터에 포즈 {cs}개({frac:.0%})가 있습니다."))
        if gap is not None and gap < 1.0:
            out.append(F("note",
                         f"{name}：前兩名分數相差 {gap:.2f} kcal mol⁻¹，小於 Vina 約 1 到 2 kcal mol⁻¹ 的誤差，排名本身不能決定結合模式。"
                         "叢集大小與後續模擬的穩定性更值得參考。",
                         f"{name}: the top two poses differ by {gap:.2f} kcal mol⁻¹, below Vina's error of about 1–2 kcal mol⁻¹. "
                         "The ranking alone does not decide the binding mode. Cluster size and stability in simulation tell you more.",
                         f"{name}：上位2ポーズのスコア差は {gap:.2f} kcal mol⁻¹ で、Vina の誤差（約 1〜2 kcal mol⁻¹）より小さくなっています。"
                         "順位だけでは結合様式を決められません。クラスターの大きさとシミュレーションでの安定性のほうが参考になります。",
                         f"{name}: 상위 두 포즈의 점수 차이는 {gap:.2f} kcal mol⁻¹로 Vina 오차(약 1~2 kcal mol⁻¹)보다 작습니다. "
                         "순위만으로는 결합 모드를 정할 수 없습니다. 클러스터 크기와 시뮬레이션에서의 안정성이 더 참고가 됩니다."))
        if frac < 0.3:
            out.append(F("caution",
                         f"{name}：選用姿勢的叢集很小，搜尋沒有收斂到一致的結合模式。請提高搜尋強度或縮小搜尋區。",
                         f"{name}: the chosen pose belongs to a small cluster, so the search did not converge on one binding mode. "
                         "Increase the exhaustiveness or narrow the search box.",
                         f"{name}：採用したポーズのクラスターが小さく、探索は1つの結合様式に収束していません。"
                         "探索の徹底度（exhaustiveness）を上げるか、探索領域を狭めてください。",
                         f"{name}: 선택한 포즈의 클러스터가 작아 탐색이 하나의 결합 모드로 수렴하지 않았습니다. "
                         "탐색 강도(exhaustiveness)를 높이거나 탐색 영역을 좁히십시오."))
        r = p.get("rmsd_ref")
        if r is not None:
            if r <= 2.0:
                out.append(F("good",
                             f"{name}：與共結晶姿勢的 RMSD 為 {r:.2f} Å（≤ 2 Å），重新對接成功，搜尋區與參數可信。",
                             f"{name}: RMSD to the co-crystal pose is {r:.2f} Å (≤ 2 Å). Redocking succeeded, so the box and settings are credible.",
                             f"{name}：共結晶ポーズとの RMSD は {r:.2f} Å（≤ 2 Å）です。再ドッキングは成功しており、探索領域と設定は信頼できます。",
                             f"{name}: 공결정 포즈와의 RMSD가 {r:.2f} Å(≤ 2 Å)입니다. 재도킹이 성공했으므로 탐색 영역과 설정을 믿을 수 있습니다."))
            else:
                out.append(F("caution",
                             f"{name}：與共結晶姿勢的 RMSD 為 {r:.2f} Å（> 2 Å），重新對接沒能重現晶體結構，其他配體的姿勢也要保守看待。",
                             f"{name}: RMSD to the co-crystal pose is {r:.2f} Å (> 2 Å). Redocking did not reproduce the crystal, "
                             "so treat other poses from this setup with caution.",
                             f"{name}：共結晶ポーズとの RMSD は {r:.2f} Å（> 2 Å）です。再ドッキングで結晶構造を再現できなかったため、"
                             "ほかのリガンドのポーズも慎重に扱ってください。",
                             f"{name}: 공결정 포즈와의 RMSD가 {r:.2f} Å(> 2 Å)입니다. 재도킹이 결정 구조를 재현하지 못했으므로 "
                             "다른 리간드의 포즈도 신중하게 보십시오."))
        if name == "joint" and p.get("min_ll_distance") is not None:
            ll = p["min_ll_distance"]
            out.append(F("note",
                         f"同時對接的配體間最短距離為 {ll} Å。分數是所有配體的總和，不能直接和單一配體的分數比較。",
                         f"In simultaneous docking the shortest ligand–ligand distance is {ll} Å. The score is the sum over all "
                         "ligands and cannot be compared directly with a single-ligand score.",
                         f"同時ドッキングでのリガンド間の最短距離は {ll} Å です。スコアは全リガンドの合計なので、単一リガンドのスコアとは直接比べられません。",
                         f"동시 도킹에서 리간드 사이 최단 거리는 {ll} Å입니다. 점수는 모든 리간드의 합이므로 단일 리간드 점수와 직접 비교할 수 없습니다."))
    return out


def screen(rows: list[dict], n_failed: int, selected: list[str]) -> list[dict]:
    if not rows:
        return []
    best = rows[0]
    near = [r for r in rows if r.get("indistinguishable_from_top")]
    bn, bs = best["name"], best["score"]
    out = [F("note",
             f"共 {len(rows)} 個化合物完成篩選（{n_failed} 個無法取得結構或對接失敗，見表）。最佳為 {bn}（{bs:.2f} kcal mol⁻¹）。"
             f"有 {len(near)} 個化合物與最佳相差不到 1 kcal mol⁻¹，它們的名次在誤差內。",
             f"{len(rows)} compounds were screened ({n_failed} could not be obtained or docked, see the table). The best is "
             f"{bn} ({bs:.2f} kcal mol⁻¹). {len(near)} compounds are within 1 kcal mol⁻¹ of it, so their order is within error.",
             f"{len(rows)} 個の化合物をスクリーニングしました（{n_failed} 個は構造を取得できなかったかドッキングに失敗しました。表を参照）。"
             f"最良は {bn}（{bs:.2f} kcal mol⁻¹）です。{len(near)} 個の化合物は最良との差が 1 kcal mol⁻¹ 未満で、順位は誤差の範囲内です。",
             f"화합물 {len(rows)}개를 스크리닝했습니다({n_failed}개는 구조를 얻지 못했거나 도킹에 실패함, 표 참고). "
             f"최고는 {bn}({bs:.2f} kcal mol⁻¹)입니다. 화합물 {len(near)}개가 최고와 1 kcal mol⁻¹ 이내이므로 이들의 순위는 오차 범위 안입니다.")]
    le = sorted([r for r in rows if r.get("ligand_efficiency")], key=lambda r: r["ligand_efficiency"])
    if le and le[0]["name"] != best["name"]:
        ln = le[0]["name"]
        out.append(F("note",
                     f"以每個重原子的分數（配體效率）來看，{ln} 最好。分數最負的化合物不一定最有效率，因為分子越大，分數越容易變負。",
                     f"By score per heavy atom (ligand efficiency), {ln} is best. The most negative score is not necessarily the "
                     "most efficient binder, since larger molecules score more negatively.",
                     f"重原子あたりのスコア（リガンド効率）では {ln} が最も良好です。分子が大きいほどスコアは負になりやすいため、"
                     "スコアが最も負の化合物が最も効率的とは限りません。",
                     f"중원자당 점수(리간드 효율)로는 {ln} 화합물이 가장 좋습니다. 분자가 클수록 점수가 더 음수가 되기 쉬우므로, "
                     "점수가 가장 낮은 화합물이 가장 효율적인 것은 아닙니다."))
    if selected:
        out.append(F("note",
                     "使用者選入正式對接的化合物：" + "、".join(selected) + "。",
                     "Selected for full docking by the user: " + ", ".join(selected) + ".",
                     "ユーザーが本ドッキングに選んだ化合物：" + "、".join(selected) + "。",
                     "사용자가 본 도킹에 선택한 화합물: " + ", ".join(selected) + "."))
    return out


# ----------------------------------------------------------------------------------- molecular dynamics
def _plateau(series, time_ns=None) -> dict:
    y = np.asarray(series, float)
    if y.size < 8:
        return {}
    n = y.size
    last = y[n // 2:]
    x = np.asarray(time_ns, float)[n // 2:] if time_ns is not None and len(time_ns) >= n else np.arange(last.size, dtype=float)
    slope = float(np.polyfit(x, last, 1)[0]) if last.size > 2 else 0.0
    span = float(x[-1] - x[0]) if last.size > 1 else 1.0
    return {"mean_last_half": float(last.mean()), "sd_last_half": float(last.std()), "drift_last_half": slope * span,
            "max": float(y.max())}


def md(summaries: dict, metrics: dict | None = None, restrained: bool = False) -> list[dict]:
    """summaries: analysis summaries per system key; metrics: optional metrics.json per key (time series)."""
    out = []
    metrics = metrics or {}
    apo = summaries.get("apo") or {}
    for key, s in summaries.items():
        m = metrics.get(key) or {}
        rm = s.get("rmsd_backbone_mean_A")
        pl = _plateau(m.get("rmsd_backbone_A") or [], m.get("time_ns")) if m else {}
        if rm is not None:
            lvl = "good" if rm < 2.0 else ("note" if rm < 3.0 else "caution")
            zh = f"{key}：主鏈 RMSD 平均 {rm:.2f} Å"
            en = f"{key}: mean backbone RMSD {rm:.2f} Å"
            ja = f"{key}：主鎖 RMSD の平均 {rm:.2f} Å"
            ko = f"{key}: 주사슬 RMSD 평균 {rm:.2f} Å"
            if pl:
                mh, sh, dr = pl["mean_last_half"], pl["sd_last_half"], pl["drift_last_half"]
                zh += f"，後半段 {mh:.2f} ± {sh:.2f} Å，漂移 {dr:+.2f} Å"
                en += f", second half {mh:.2f} ± {sh:.2f} Å with a drift of {dr:+.2f} Å"
                ja += f"、後半 {mh:.2f} ± {sh:.2f} Å、ドリフト {dr:+.2f} Å"
                ko += f", 후반부 {mh:.2f} ± {sh:.2f} Å, 드리프트 {dr:+.2f} Å"
            zh += "。小於 2 Å 屬穩定，2 到 3 Å 是中度構形調整，大於 3 Å 代表明顯重排。"
            en += ". Below 2 Å is stable, 2–3 Å is a moderate adjustment and above 3 Å is a clear rearrangement."
            ja += "。2 Å 未満は安定、2〜3 Å は中程度の構造調整、3 Å を超えると明らかな再配置です。"
            ko += ". 2 Å 미만은 안정, 2~3 Å은 중간 정도의 구조 조정, 3 Å 초과는 뚜렷한 재배열입니다."
            out.append(F(lvl, zh, en, ja, ko))
            if pl and abs(pl["drift_last_half"]) > 0.5:
                dr = pl["drift_last_half"]
                out.append(F("caution",
                             f"{key}：後半段 RMSD 仍在變化（漂移 {dr:+.2f} Å），還沒達到平台。請延長模擬。",
                             f"{key}: RMSD is still changing in the second half (drift {dr:+.2f} Å) and has not reached a "
                             "plateau. Extend the simulation.",
                             f"{key}：後半でも RMSD が変化しており（ドリフト {dr:+.2f} Å）、まだ平坦部に達していません。シミュレーションを延長してください。",
                             f"{key}: 후반부에도 RMSD가 변하고 있어(드리프트 {dr:+.2f} Å) 아직 평탄 구간에 도달하지 않았습니다. 시뮬레이션을 연장하십시오."))
        for rn, l in (s.get("ligands") or {}).items():
            r20 = l.get("rmsd_last20_A")
            if not l.get("stays_bound"):
                out.append(F("caution",
                             f"{key} 的配體 {rn}：最後 20 % 時間的口袋內 RMSD 為 {r20:.1f} Å（≥ 3 Å），配體離開或明顯偏離了原結合位。"
                             "對接姿勢在動態中不穩定，不應拿對接分數當作結合證據。",
                             f"Ligand {rn} in {key}: pocket RMSD over the last 20 % is {r20:.1f} Å (≥ 3 Å). The ligand left or "
                             "moved away from the docked site, so the docking score is not evidence of binding.",
                             f"{key} のリガンド {rn}：最後の 20 % のポケット内 RMSD は {r20:.1f} Å（≥ 3 Å）です。リガンドは元の結合部位を離れたか大きくずれており、"
                             "ドッキングポーズは動的には安定していません。ドッキングスコアを結合の根拠にしないでください。",
                             f"{key}의 리간드 {rn}: 마지막 20 % 동안 포켓 내 RMSD가 {r20:.1f} Å(≥ 3 Å)입니다. 리간드가 원래 결합 부위를 "
                             "떠났거나 크게 벗어났으므로 도킹 점수를 결합의 근거로 볼 수 없습니다."))
            elif r20 is not None and r20 > 2.0:
                out.append(F("note",
                             f"{key} 的配體 {rn}：留在口袋內，但最後 20 % 的 RMSD 為 {r20:.1f} Å，結合模式有調整。",
                             f"Ligand {rn} in {key}: stays in the pocket, but its RMSD over the last 20 % is {r20:.1f} Å, so the binding mode shifted.",
                             f"{key} のリガンド {rn}：ポケット内にとどまっていますが、最後の 20 % の RMSD は {r20:.1f} Å で、結合様式が変化しています。",
                             f"{key}의 리간드 {rn}: 포켓 안에 머물지만 마지막 20 %의 RMSD가 {r20:.1f} Å이므로 결합 모드가 조정되었습니다."))
            else:
                out.append(F("good",
                             f"{key} 的配體 {rn}：維持對接姿勢（最後 20 % 的 RMSD 為 {r20:.1f} Å），結合模式在模擬時間內穩定。",
                             f"Ligand {rn} in {key}: keeps the docked pose (RMSD {r20:.1f} Å over the last 20 %). The binding mode "
                             "is stable over the simulated time.",
                             f"{key} のリガンド {rn}：ドッキングポーズを保っています（最後の 20 % の RMSD は {r20:.1f} Å）。結合様式はシミュレーション時間内で安定です。",
                             f"{key}의 리간드 {rn}: 도킹 포즈를 유지합니다(마지막 20 % RMSD {r20:.1f} Å). 결합 모드가 시뮬레이션 시간 동안 안정적입니다."))
            tc = l.get("top_contacts") or []
            if tc:
                txt = "、".join(f"{a}（{b:.0%}）" for a, b in tc[:5])
                txt_en = ", ".join(f"{a} ({b:.0%})" for a, b in tc[:5])
                out.append(F("note",
                             f"{key} 的配體 {rn} 最常接觸的殘基：{txt}。",
                             f"Most frequent contacts of {rn} in {key}: {txt_en}.",
                             f"{key} のリガンド {rn} が最もよく接触する残基：{txt}。",
                             f"{key}, 리간드 {rn}의 주요 접촉 잔기: {txt_en}."))
    if apo.get("rmsd_backbone_mean_A") is not None:
        for key, s in summaries.items():
            if key == "apo" or s.get("rmsd_backbone_mean_A") is None:
                continue
            d = s["rmsd_backbone_mean_A"] - apo["rmsd_backbone_mean_A"]
            if abs(d) >= 0.3:
                up = d > 0
                out.append(F("note",
                             f"與蛋白單獨相比，{key} 的主鏈 RMSD {'高' if up else '低'} {abs(d):.2f} Å。"
                             + ("配體結合後蛋白的構形調整較大。" if up else "配體結合讓蛋白更穩定。"),
                             f"Compared with the protein alone, the backbone RMSD of {key} is {abs(d):.2f} Å {'higher' if up else 'lower'}. "
                             + ("The protein adjusts more with the ligand bound." if up else "Binding stabilises the protein."),
                             f"タンパク質単独と比べ、{key} の主鎖 RMSD は {abs(d):.2f} Å {'高く' if up else '低く'}なっています。"
                             + ("リガンドが結合すると構造の調整が大きくなります。" if up else "リガンドの結合でタンパク質が安定しています。"),
                             f"단백질 단독과 비교해 {key}의 주사슬 RMSD가 {abs(d):.2f} Å {'높습니다' if up else '낮습니다'}. "
                             + ("리간드가 결합하면 단백질의 구조 조정이 더 큽니다." if up else "리간드 결합으로 단백질이 더 안정해졌습니다.")))
    if restrained:
        out.append(F("caution",
                     "正式模擬保留了主鏈約束，RMSD 與 RMSF 被人為壓低，不能當作結構穩定的證據。",
                     "The backbone was restrained in production. RMSD and RMSF are artificially suppressed and are not evidence of stability.",
                     "本計算で主鎖の拘束を残しているため、RMSD と RMSF は人為的に小さくなっています。構造が安定している根拠にはなりません。",
                     "본 시뮬레이션에서 주사슬 구속을 유지했으므로 RMSD와 RMSF가 인위적으로 낮아졌습니다. 구조 안정성의 근거가 될 수 없습니다."))
    return out


def rigidified(items: list[dict]) -> list[dict]:
    if not items:
        return []
    txt_zh = "、".join(f"{x['residue']}（{x['delta_rmsf_A']:+.2f} Å）" for x in items[:6])
    txt_en = ", ".join(f"{x['residue']} ({x['delta_rmsf_A']:+.2f} Å)" for x in items[:6])
    return [F("note",
              f"結合後柔性下降最多的殘基是 {txt_zh}。這些殘基通常位於結合位，或在與結合位耦合的區域。",
              f"The residues whose flexibility drops most on binding are {txt_en}. They usually line the site or are coupled to it.",
              f"結合後に柔軟性が最も下がった残基は {txt_zh} です。これらは通常、結合部位にあるか、結合部位と連動する領域にあります。",
              f"결합 후 유연성이 가장 많이 낮아진 잔기는 {txt_en}입니다. 이 잔기들은 보통 결합 부위에 있거나 결합 부위와 연동된 영역에 있습니다.")]


# ----------------------------------------------------------------------------------- binding
def binding(results: dict) -> list[dict]:
    out = []
    for name, r in (results or {}).items():
        d, e = r.get("delta_pmf_kj_mol"), r.get("delta_pmf_err_kj_mol")
        if d is None:
            continue
        kcal = d / 4.184
        pm = f" ± {e:.1f}" if e is not None else ""
        out.append(F("note",
                     f"{name}：自由能剖面的井深 ΔPMF = {d:.1f}{pm} kJ mol⁻¹（{kcal:.1f} kcal mol⁻¹）。",
                     f"{name}: depth of the free-energy profile ΔPMF = {d:.1f}{pm} kJ mol⁻¹ ({kcal:.1f} kcal mol⁻¹).",
                     f"{name}：自由エネルギープロファイルの井戸の深さ ΔPMF = {d:.1f}{pm} kJ mol⁻¹（{kcal:.1f} kcal mol⁻¹）。",
                     f"{name}: 자유 에너지 프로파일의 우물 깊이 ΔPMF = {d:.1f}{pm} kJ mol⁻¹({kcal:.1f} kcal mol⁻¹)."))
        if r.get("dG_standard_kj_mol") is not None:
            g = r["dG_standard_kj_mol"]
            out.append(F("good",
                         f"{name}：標準結合自由能 ΔG° = {g:.1f} kJ mol⁻¹（{g / 4.184:.1f} kcal mol⁻¹），已含體積修正。",
                         f"{name}: standard binding free energy ΔG° = {g:.1f} kJ mol⁻¹ ({g / 4.184:.1f} kcal mol⁻¹), including the volume correction.",
                         f"{name}：標準結合自由エネルギー ΔG° = {g:.1f} kJ mol⁻¹（{g / 4.184:.1f} kcal mol⁻¹）。体積補正を含みます。",
                         f"{name}: 표준 결합 자유 에너지 ΔG° = {g:.1f} kJ mol⁻¹({g / 4.184:.1f} kcal mol⁻¹). 부피 보정을 포함합니다."))
        else:
            out.append(F("note",
                         f"{name}：沒有輸出 ΔG°，原因見下方說明。ΔPMF 只適合用來比較同一設定下的配體。",
                         f"{name}: ΔG° is not reported (see the reason below). ΔPMF is only suitable for comparing ligands run with the same settings.",
                         f"{name}：ΔG° は出力していません（理由は下の説明を参照）。ΔPMF は同じ設定で計算したリガンドどうしの比較にだけ使えます。",
                         f"{name}: ΔG°는 출력하지 않았습니다(이유는 아래 설명 참고). ΔPMF는 같은 설정으로 계산한 리간드끼리 비교할 때만 쓸 수 있습니다."))
        hs = (r.get("half_split") or {}).get("diff_kj_mol")
        if hs is not None:
            conv = hs <= 2.0
            out.append(F("good" if conv else "caution",
                         f"{name}：前後半段的 ΔPMF 相差 {hs:.1f} kJ mol⁻¹" + ("，取樣已收斂。" if conv else "（> 2 kJ mol⁻¹），取樣尚未收斂，需要更長的窗口。"),
                         f"{name}: first and second halves differ by {hs:.1f} kJ mol⁻¹"
                         + (", so sampling has converged." if conv else " (> 2 kJ mol⁻¹). Sampling has not converged and longer windows are needed."),
                         f"{name}：前半と後半の ΔPMF の差は {hs:.1f} kJ mol⁻¹ "
                         + ("で、サンプリングは収束しています。" if conv else "（> 2 kJ mol⁻¹）です。サンプリングはまだ収束しておらず、ウィンドウを長くする必要があります。"),
                         f"{name}: 전반부와 후반부의 ΔPMF 차이가 {hs:.1f} kJ mol⁻¹"
                         + ("로 샘플링이 수렴했습니다." if conv else "(> 2 kJ mol⁻¹)입니다. 샘플링이 아직 수렴하지 않았으므로 윈도우를 더 길게 해야 합니다.")))
        if d > 80:
            out.append(F("caution",
                         f"{name}：井深超過 80 kJ mol⁻¹，對多數藥物大小的分子來說不合理。常見原因是窗口取樣不足，或拉離路徑扭曲了蛋白。",
                         f"{name}: a depth above 80 kJ mol⁻¹ is implausible for most drug-sized molecules. The usual causes are "
                         "insufficient window sampling or a pulling path that distorts the protein.",
                         f"{name}：井戸の深さが 80 kJ mol⁻¹ を超えており、薬物サイズの分子の多くでは不自然な値です。"
                         "よくある原因は、ウィンドウのサンプリング不足か、引き離し経路がタンパク質をゆがめていることです。",
                         f"{name}: 우물 깊이가 80 kJ mol⁻¹ 초과로, 대부분의 약물 크기 분자에는 맞지 않는 값입니다. "
                         "흔한 원인은 윈도우 샘플링 부족이나 당김 경로가 단백질을 비트는 경우입니다."))
    return out


def peptide(cpp: dict, access: dict) -> list[dict]:
    out = []
    for name, r in (cpp or {}).items():
        if r.get("limitation"):
            lim = r["limitation"]
            out.append(F("caution", f"{name}（穿膜性）：{lim}", f"{name} (cell penetration): {lim}",
                         f"{name}（細胞膜透過性）：{lim}", f"{name}(세포 투과성): {lim}"))
        elif r.get("status"):
            st = r.get("status")
            out.append(F("good", f"{name}（穿膜性）：{st}。", f"{name} (cell penetration): {st}.",
                         f"{name}（細胞膜透過性）：{st}。", f"{name}(세포 투과성): {st}."))
    for name, r in (access or {}).items():
        p = r.get("pose") or {}
        if p:
            bur, dist = p.get("burial_fraction"), p.get("site_min_distance_A")
            has = dist is not None
            zh = f"{name}（活性位可及性）：選用姿勢的埋藏比例 {bur:.0%}" + (f"，距結合位最近 {dist:.1f} Å" if has else "") + "。"
            en = f"{name} (site access): burial of the chosen pose {bur:.0%}" + (f", closest approach to the site {dist:.1f} Å" if has else "") + "."
            ja = f"{name}（活性部位への到達性）：採用したポーズの埋没率 {bur:.0%}" + (f"、結合部位への最短距離 {dist:.1f} Å" if has else "") + "。"
            ko = f"{name}(활성 부위 접근성): 선택한 포즈의 매몰 비율 {bur:.0%}" + (f", 결합 부위까지 최단 거리 {dist:.1f} Å" if has else "") + "."
            out.append(F("good" if p.get("gate") == "PASS" else "caution", zh, en, ja, ko))
    return out


def headline(sections: list[list[dict]]) -> list[dict]:
    """Key findings: every caution first, then the first finding of each section."""
    flat = [f for s in sections for f in s]
    cautions = [f for f in flat if f["level"] == "caution"]
    firsts = [s[0] for s in sections if s and s[0]["level"] != "caution"]
    return (cautions + firsts)[:10]
