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
    """D-96 (A3): "repaired" counts only gates with a recorded change (`diff`); an unchanged limitation — including a
    legacy AUTO_FIXED record without a diff — is an accepted limitation, not a fix."""
    out = []
    if not gates:
        return [F("note", "沒有結構可信度紀錄。", "No structure-validity record is available.",
                  "構造の信頼性の記録はありません。", "구조 신뢰성 기록이 없습니다.")]
    fixed = [g for g in gates if g.get("status") == "AUTO_FIXED" and g.get("diff")]
    lim = [g for g in gates if g.get("limitation") or (g.get("status") == "AUTO_FIXED" and not g.get("diff"))]
    need = [g for g in gates if g.get("status") == "NEEDS_HUMAN"]
    ok = [g for g in gates if g.get("status") == "PASS" and not g.get("limitation")]
    nf, nl, nn, npass = len(fixed), len(lim), len(need), len(ok)
    out.append(F("good" if not nn and not nl else "caution",
                 f"結構檢查共 {len(gates)} 項：{npass} 項通過，{nf} 項實際修正（有修改紀錄），{nl} 項是接受的限制（沒有被修正），{nn} 項需要你決定。",
                 f"Of {len(gates)} structure checks, {npass} passed, {nf} were repaired (with a recorded change), "
                 f"{nl} accepted limitation{'s' if nl != 1 else ''} (not repaired), and {nn} need your decision.",
                 f"構造チェック {len(gates)} 項目のうち、{npass} 項目が合格、{nf} 項目は実際に修正（変更の記録あり）、{nl} 項目は受け入れた制約"
                 f"（修正されていません）、{nn} 項目は判断が必要です。",
                 f"구조 검사 {len(gates)}개 항목 중 {npass}개 통과, {nf}개 실제 수정(변경 기록 있음), {nl}개는 받아들인 제약(수정되지 않음), "
                 f"{nn}개는 결정이 필요합니다."))
    for g in gates:
        if g.get("name") == "resolution" and (g.get("status") != "PASS" or g.get("limitation")):
            out.append(F("note",
                         "解析度比 2.5 Å 差（數值較大）時，側鏈與水分子的位置不確定度較高，判讀口袋內的氫鍵要保守；這是整個結構的數值，不代表每個口袋都一樣。",
                         "At a resolution worse than 2.5 Å (a larger value), side-chain and water positions are uncertain, so read "
                         "pocket hydrogen bonds conservatively; the value describes the whole entry, not each pocket.",
                         "分解能が 2.5 Å より悪い（数値が大きい）と、側鎖や水分子の位置の不確かさが大きくなるため、ポケット内の水素結合は慎重に解釈して"
                         "ください。この値は構造全体のもので、各ポケットに同じとは限りません。",
                         "분해능이 2.5 Å보다 나쁘면(값이 크면) 곁사슬과 물 분자 위치의 불확실성이 커지므로 포켓 안의 수소 결합은 보수적으로 "
                         "해석하십시오. 이 값은 구조 전체의 값이며 모든 포켓에 똑같이 적용되지는 않습니다."))
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
            out += ligand_state_findings(key, rn, l)
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
def ligand_state_findings(key: str, rn: str, l: dict) -> list[dict]:
    """D-97 (A4): what the ligand did, from contacts + pocket COM + RMSD (`analysis.traj.ligand_state`).  RMSD alone
    never decides retention or dissociation; restraints are stated; the RMSD reference is the first production frame."""
    st = l.get("state") or {}
    r20 = l.get("rmsd_last20_A")
    fa, ft = st.get("fraction_all") or {}, st.get("fraction_final_20pct") or {}
    rest = st.get("restraints") or []
    rz = (f"（production 期間有位置約束：{', '.join(rest)}；受約束時留在口袋不代表無約束下穩定）" if rest else "")
    re_ = (f" (positional restraints during production: {', '.join(rest)}; staying in the pocket under restraint is not "
           "stability without restraint)" if rest else "")
    if not fa:            # record written before D-97: RMSD only — say what it cannot tell
        if r20 is None:
            return []
        lvl = "caution" if r20 >= 3.0 else "note"
        return [F(lvl,
                  f"{key} 的配體 {rn}：最後 20 % 的口袋內 RMSD 為 {r20:.1f} Å（參考是第一個 production 幀，不是對接姿勢）。這份紀錄沒有接觸狀態，"
                  "單看 RMSD 無法區分「姿勢改變但仍在口袋」與「離開口袋」。",
                  f"Ligand {rn} in {key}: pocket RMSD over the last 20 % is {r20:.1f} Å (reference: the first production frame, not "
                  "the docking pose). This record has no contact state, and RMSD alone cannot tell a changed pose in the pocket "
                  "from leaving it.",
                  f"{key} のリガンド {rn}：最後の 20 % のポケット内 RMSD は {r20:.1f} Å です（基準は最初の本計算フレームで、ドッキングポーズではありません）。"
                  "この記録には接触状態がなく、RMSD だけではポケット内でのポーズ変化と離脱を区別できません。",
                  f"{key}의 리간드 {rn}: 마지막 20 % 포켓 내 RMSD는 {r20:.1f} Å입니다(기준은 첫 본 시뮬레이션 프레임이며 도킹 포즈가 아님). "
                  "이 기록에는 접촉 상태가 없어 RMSD만으로는 포켓 안의 포즈 변화와 이탈을 구별할 수 없습니다.")]
    pct = lambda d, k: f"{(d.get(k) or 0):.0%}"  # noqa: E731
    if (fa.get("escape_evidence") or 0) > 0:
        t0 = st.get("first_escape_ns")
        tt = f"{t0:.2f} ns" if t0 is not None else "—"
        return [F("caution",
                  f"{key} 的配體 {rn}：有離開口袋的證據（連續多幀沒有任何接觸殘基且質心離口袋增加 ≥ 5 Å，首次在 {tt}；全程 {pct(fa, 'escape_evidence')} 的幀）{rz}。",
                  f"Ligand {rn} in {key}: there is escape evidence (several consecutive frames with no contacting residue and the "
                  f"centre of mass ≥ 5 Å farther from the pocket, first at {tt}; {pct(fa, 'escape_evidence')} of all frames){re_}.",
                  f"{key} のリガンド {rn}：ポケットを離れた証拠があります（接触残基のない連続フレームがあり、重心がポケットから 5 Å 以上離れた。最初は {tt}、"
                  f"全体の {pct(fa, 'escape_evidence')} のフレーム）{rz}。",
                  f"{key}의 리간드 {rn}: 포켓을 떠난 증거가 있습니다(접촉 잔기가 없는 연속 프레임이 있고 질량중심이 포켓에서 5 Å 이상 멀어짐, 처음 {tt}, "
                  f"전체의 {pct(fa, 'escape_evidence')} 프레임){re_}.")]
    if (ft.get("pose_changed_in_pocket") or 0) >= 0.5:
        return [F("note",
                  f"{key} 的配體 {rn}：最後 20 % 時間中 {pct(ft, 'pose_changed_in_pocket')} 的幀姿勢已改變但仍有接觸殘基（RMSD 高但沒有離開口袋）{rz}。",
                  f"Ligand {rn} in {key}: in {pct(ft, 'pose_changed_in_pocket')} of the final 20 % of frames the pose changed but "
                  f"contacting residues remain (high RMSD without leaving the pocket){re_}.",
                  f"{key} のリガンド {rn}：最後の 20 % のフレームのうち {pct(ft, 'pose_changed_in_pocket')} でポーズは変わりましたが接触残基は残っています"
                  f"（RMSD は高いがポケットは離れていません）{rz}。",
                  f"{key}의 리간드 {rn}: 마지막 20 % 프레임 중 {pct(ft, 'pose_changed_in_pocket')}에서 포즈는 바뀌었지만 접촉 잔기가 남아 있습니다"
                  f"(RMSD는 높지만 포켓을 떠나지 않음){re_}.")]
    if (ft.get("pose_retained") or 0) >= 0.5:
        return [F("good" if not rest else "note",
                  f"{key} 的配體 {rn}：最後 20 % 時間中 {pct(ft, 'pose_retained')} 的幀維持起始姿勢且有接觸殘基（參考是第一個 production 幀）{rz}。",
                  f"Ligand {rn} in {key}: in {pct(ft, 'pose_retained')} of the final 20 % of frames it keeps its starting pose with "
                  f"contacting residues (reference: the first production frame){re_}.",
                  f"{key} のリガンド {rn}：最後の 20 % のフレームのうち {pct(ft, 'pose_retained')} で最初のポーズを保ち、接触残基があります"
                  f"（基準は最初の本計算フレーム）{rz}。",
                  f"{key}의 리간드 {rn}: 마지막 20 % 프레임 중 {pct(ft, 'pose_retained')}에서 처음 포즈를 유지하고 접촉 잔기가 있습니다"
                  f"(기준은 첫 본 시뮬레이션 프레임){re_}.")]
    return [F("caution",
              f"{key} 的配體 {rn}：狀態不明確（最後 20 % 時間中 {pct(ft, 'unknown')} 的幀接觸消失但沒有質心離開的證據）{rz}。",
              f"Ligand {rn} in {key}: the state is unclear ({pct(ft, 'unknown')} of the final 20 % of frames lose contact without "
              f"centre-of-mass evidence of leaving){re_}.",
              f"{key} のリガンド {rn}：状態ははっきりしません（最後の 20 % のフレームのうち {pct(ft, 'unknown')} で接触が消えていますが、重心が離れた証拠はありません）{rz}。",
              f"{key}의 리간드 {rn}: 상태가 불분명합니다(마지막 20 % 프레임 중 {pct(ft, 'unknown')}에서 접촉이 사라졌지만 질량중심이 떠난 증거는 없음){re_}.")]


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
        from ..sampling.assessment import claim_status
        cs = claim_status(r, "dG_standard")        # D-134 (R2): the number alone never makes a "good" ΔG° finding
        if r.get("dG_standard_kj_mol") is not None and not cs["eligible"]:
            g = r["dG_standard_kj_mol"]
            out.append(F("caution",
                         f"{name}：算出 ΔG° = {g:.1f} kJ mol⁻¹，但取樣評估未通過、缺漏或為舊版資料，這個數值不當作標準結合自由能，"
                         "只留作診斷值，不比較、不排名。",
                         f"{name}: a ΔG° of {g:.1f} kJ mol⁻¹ was computed, but the sampling assessment failed, is missing or is "
                         "from an older version, so the number is not treated as a standard binding free energy; it is kept as "
                         "a diagnostic value and is not compared or ranked.",
                         f"{name}：ΔG° = {g:.1f} kJ mol⁻¹ が計算されましたが、取得評価が不合格・欠落、または旧版のデータのため、"
                         "標準結合自由エネルギーとしては扱わず、診断値としてだけ残し、比較も順位づけもしません。",
                         f"{name}: ΔG° = {g:.1f} kJ mol⁻¹가 계산되었지만 샘플링 평가가 미통과·누락이거나 구버전 데이터이므로 "
                         "표준 결합 자유 에너지로 쓰지 않고 진단 값으로만 남기며 비교하거나 순위를 매기지 않습니다."))
        elif r.get("dG_standard_kj_mol") is not None:
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
            # D-96 (A2): half-split agreement is ONE diagnostic; it never declares convergence on its own
            conv = hs <= 2.0
            out.append(F("note" if conv else "caution",
                         f"{name}：前後半段的 ΔPMF 相差 {hs:.1f} kJ mol⁻¹" + ("（≤ 2，這一項檢查通過；整體是否合格見取樣評估）。" if conv else "（> 2 kJ mol⁻¹），前後半段不一致，需要更長的窗口。"),
                         f"{name}: first and second halves differ by {hs:.1f} kJ mol⁻¹"
                         + (" (≤ 2, this one check passes; whether the result qualifies overall is given by the sampling assessment)."
                            if conv else " (> 2 kJ mol⁻¹). The halves disagree and longer windows are needed."),
                         f"{name}：前半と後半の ΔPMF の差は {hs:.1f} kJ mol⁻¹ "
                         + ("です（≤ 2、この項目は合格。全体として合格かは取得評価を参照）。" if conv else "（> 2 kJ mol⁻¹）です。前半と後半が一致しないため、ウィンドウを長くする必要があります。"),
                         f"{name}: 전반부와 후반부의 ΔPMF 차이가 {hs:.1f} kJ mol⁻¹"
                         + ("입니다(≤ 2, 이 항목은 통과. 전체 적격 여부는 샘플링 평가 참고)." if conv else "(> 2 kJ mol⁻¹)입니다. 전후반이 일치하지 않으므로 윈도우를 더 길게 해야 합니다.")))
        a = r.get("assessment")
        if a is not None or "half_split" in r:
            from .figure_text import classify_assessment
            for x in classify_assessment(name, a):
                out.append({"level": x["level"], "text": x["text"]})
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


# ----------------------------------------------------------------------------------- D-82: score, fold, membrane, long run, CG
NO_SCORE = ("預測複合物，沒有對接分數", "predicted complex, no docking score", "予測複合体（ドッキングスコアなし）", "예측 복합체, 도킹 점수 없음")   # same words as gui/advanced.py


def score_text(score, lang: str = "en", nd: int = 2, unit: bool = False) -> str:
    """A docking score for display.  A peptide placed from a predicted complex has no score (None): say so, never "None"."""
    from ..i18n import pick
    if score is None:
        return pick(NO_SCORE, lang)
    return f"{float(score):.{nd}f}" + (" kcal mol⁻¹" if unit else "")


def fold(name: str, rec: dict) -> list[dict]:
    """Section-level findings of one folded peptide (state["fold"][name])."""
    if not rec or rec.get("status") == "SKIPPED_SHORT":
        if rec and rec.get("status") == "SKIPPED_SHORT":
            n = len(rec.get("peptide_sequence") or (rec.get("request") or {}).get("sequence") or "")
            return [F("note", f"{name}：胜肽只有 {n} 個殘基（< 10），不做結構預測，使用延伸構形對接。",
                      f"{name}: the peptide has only {n} residues (< 10), so it was not folded and the extended build was docked.",
                      f"{name}：ペプチドは {n} 残基（< 10）しかないため構造予測はせず、伸びた構造でドッキングしました。",
                      f"{name}: 펩타이드가 잔기 {n}개(< 10)뿐이라 구조 예측을 하지 않고 늘어난 구조로 도킹했습니다.")]
        return []
    out = []
    eng, dev, rt = rec.get("engine") or "—", rec.get("device") or "—", rec.get("runtime_s")
    rts = f"{rt:g} s" if isinstance(rt, (int, float)) else "—"
    out.append(F("note", f"{name}：結構由 {eng} 預測（{dev}，{rts}），結果是預測，不是實驗結構。",
                 f"{name}: the structure was predicted with {eng} ({dev}, {rts}). It is a prediction, not an experimental structure.",
                 f"{name}：構造は {eng} で予測しました（{dev}、{rts}）。予測であり、実験構造ではありません。",
                 f"{name}: 구조는 {eng}로 예측했습니다({dev}, {rts}). 예측이며 실험 구조가 아닙니다."))
    req = rec.get("request") or {}
    m = rec.get("mean_plddt")
    if req.get("accept_low") and m is not None and m < 50:
        out.append(F("caution", f"{name}：pLDDT {m:.1f} 低於 50，使用者選擇仍使用這個預測。所有以它為起點的結果都要保守看待。",
                     f"{name}: pLDDT {m:.1f} is below 50 and the user chose to use the prediction anyway. Read every result built on it conservatively.",
                     f"{name}：pLDDT {m:.1f} は 50 未満ですが、ユーザーはこの予測を使うことを選びました。これを出発点とする結果はすべて慎重に解釈してください。",
                     f"{name}: pLDDT {m:.1f}가 50 미만이지만 사용자가 이 예측을 쓰기로 했습니다. 이를 출발점으로 한 모든 결과는 신중하게 해석하십시오."))
    pl = rec.get("placement") or {}
    if req.get("mode") == "complex" or pl:
        if pl.get("receptor_source") == "predicted":
            out.append(F("caution", f"{name}：沒有實際受體結構，受體也是預測的。MD 在預測的受體上進行，結合位的形狀未經實驗驗證。",
                         f"{name}: there is no actual receptor structure, so the receptor is predicted too. MD runs on a predicted receptor and the site shape is not validated experimentally.",
                         f"{name}：実際の受容体構造がないため、受容体も予測構造です。MD は予測した受容体で行っており、結合部位の形は実験で確かめられていません。",
                         f"{name}: 실제 수용체 구조가 없어 수용체도 예측 구조입니다. MD는 예측한 수용체에서 수행되며 결합 부위 모양은 실험으로 검증되지 않았습니다."))
        elif pl.get("rmsd_ca") is not None:
            r, n = float(pl["rmsd_ca"]), int(pl.get("n_matched") or 0)
            ok = r <= 2.0
            out.append(F("good" if ok else "caution",
                         f"{name}：預測複合物以 {n} 個 Cα 疊合到實際受體（RMSD {r:.2f} Å，門檻 2.0 Å），只取胜肽姿勢，不經對接直接進入 MD，所以沒有對接分數。"
                         + ("" if ok else "RMSD 超過門檻，是使用者選擇仍使用。"),
                         f"{name}: the predicted complex was superposed on the actual receptor with {n} Cα (RMSD {r:.2f} Å, threshold 2.0 Å). "
                         "Only the peptide pose was taken and it went to MD without docking, so there is no docking score."
                         + ("" if ok else " The RMSD exceeds the threshold and the user chose to use it anyway."),
                         f"{name}：予測複合体を Cα {n} 個で実際の受容体に重ね合わせ（RMSD {r:.2f} Å、しきい値 2.0 Å）、ペプチドのポーズだけを取り出してドッキングを経ずに MD に進めました。そのためドッキングスコアはありません。"
                         + ("" if ok else "RMSD はしきい値を超えていますが、ユーザーが使用を選びました。"),
                         f"{name}: 예측 복합체를 Cα {n}개로 실제 수용체에 겹치고(RMSD {r:.2f} Å, 기준 2.0 Å) 펩타이드 포즈만 가져와 도킹 없이 MD로 보냈습니다. 그래서 도킹 점수가 없습니다."
                         + ("" if ok else " RMSD가 기준을 넘었지만 사용자가 사용하기로 했습니다.")))
    return out


def membrane(key: str, summ: dict) -> list[dict]:
    """Section-level findings of one membrane system (membrane_summary JSON): core water and the membrane type."""
    out = []
    cw = summ.get("core_water")
    n = int(summ.get("n_lipids") or 0)
    if cw and not (summ.get("acceptance") or {}).get("status"):
        m = float(np.mean(cw))
        lim = max(1.0, 0.01 * n)
        out.append(F("good" if m <= lim else "caution",
                     f"{key}：疏水核心（膜中心 ±0.5 nm）平均 {m:.1f} 個水分子（上限 {lim:.0f}，即 1 和脂質數 1 % 的較大者）"
                     + ("，膜沒有孔洞。" if m <= lim else "，超過上限，膜可能有孔洞或缺陷。"),
                     f"{key}: the hydrophobic core (±0.5 nm of the centre) holds {m:.1f} water molecules on average (limit {lim:.0f}, the larger of 1 and 1 % of the lipids)"
                     + (", so the membrane has no pore." if m <= lim else ", above the limit, so the membrane may have a pore or defect."),
                     f"{key}：疎水性コア（膜中心 ±0.5 nm）の水分子は平均 {m:.1f} 個（上限 {lim:.0f}、1 と脂質数の 1 % の大きい方）"
                     + ("で、膜に孔はありません。" if m <= lim else "で上限を超えており、膜に孔や欠陥がある可能性があります。"),
                     f"{key}: 소수성 중심부(막 중심 ±0.5 nm)의 물 분자는 평균 {m:.1f}개(상한 {lim:.0f}, 1과 지질 수의 1 % 중 큰 값)"
                     + ("로 막에 구멍이 없습니다." if m <= lim else "로 상한을 넘어 막에 구멍이나 결함이 있을 수 있습니다.")))
    acc = summ.get("acceptance") or {}
    if acc.get("status"):
        ev = acc.get("evidence") or {}
        failed = [k for k, v in (ev.get("checks") or {}).items() if not v]
        if not ev.get("checked", True):
            out.append(F("caution", f"{key}：軌跡沒有存水分子，無法事後做膜平衡驗收，膜的結果要當作未經驗收解讀。",
                         f"{key}: the trajectory has no water, so the membrane acceptance could not be checked afterwards. Read the membrane results as unchecked.",
                         f"{key}：軌跡に水分子が保存されていないため、膜の平衡の検査を後から行えません。膜の結果は未検査として解釈してください。",
                         f"{key}: 궤적에 물 분자가 저장되지 않아 막 평형 검수를 나중에 할 수 없습니다. 막 결과는 검수되지 않은 것으로 해석하십시오."))
        elif acc["status"] == "PASS":
            out.append(F("good", f"{key}：以正式模擬後半段做膜平衡驗收（面積 ±6 %、厚度 ±0.3 nm、疏水核心的水），全部通過。",
                         f"{key}: the membrane acceptance on the second half of production (area ±6 %, thickness ±0.3 nm, water in the core) passes.",
                         f"{key}：本計算の後半で行った膜の平衡の検査（面積 ±6 %、厚さ ±0.3 nm、疎水性コアの水）にすべて合格しました。",
                         f"{key}: 본 시뮬레이션 후반부로 한 막 평형 검수(면적 ±6 %, 두께 ±0.3 nm, 소수성 중심부의 물)를 모두 통과했습니다."))
        else:
            fz, fe = "、".join(failed) or "—", ", ".join(failed) or "—"
            out.append(F("caution", f"{key}：膜平衡驗收沒有通過（{fz}）。驗收只在分析時執行，沒有自動延長平衡。面積、厚度與接觸結果要當作未平衡的膜解讀。",
                         f"{key}: the membrane acceptance fails ({fe}). It runs only at analysis time, so equilibration was not extended. "
                         "Read area, thickness and contacts as those of an unequilibrated membrane.",
                         f"{key}：膜の平衡の検査に不合格です（{fz}）。検査は解析時にだけ行うため、平衡化は自動では延長していません。面積、厚さ、接触の結果は平衡に達していない膜のものとして解釈してください。",
                         f"{key}: 막 평형 검수를 통과하지 못했습니다({fe}). 검수는 분석할 때만 하므로 평형화를 자동으로 늘리지 않았습니다. 면적, 두께, 접촉 결과는 평형에 도달하지 않은 막의 것으로 해석하십시오."))
    if summ.get("type") == "surface":
        out.append(F("note", f"{key}：這是膜表面接觸系統（只有一片膜，溶質放在膜上方），模擬的是吸附，不是穿膜。",
                     f"{key}: this is a membrane-surface system (one bilayer with the solute placed above it). It simulates adsorption, not permeation.",
                     f"{key}：これは膜表面接触の系（膜 1 枚の上に溶質を置いた系）で、透過ではなく吸着をシミュレーションしています。",
                     f"{key}: 막 표면 접촉 시스템(막 한 장 위에 용질을 놓은 시스템)으로, 투과가 아니라 흡착을 시뮬레이션합니다."))
    return out


def long_run(key: str, plan: dict) -> list[dict]:
    out = []
    p = float(plan.get("production_ns") or 0)
    reps = int(plan.get("replicas") or 1)
    days = plan.get("days")
    d = (f"估計 {days:.1f} 天", f"an estimated {days:.1f} days", f"見積もり {days:.1f} 日", f"예상 {days:.1f}일") if days is not None else \
        ("沒有效能測試，無法估計天數", "no benchmark, so no estimate of days", "ベンチマークがないため日数は見積もれません", "벤치마크가 없어 일수를 추정할 수 없음")
    tg, iv = float(plan.get("total_gb") or 0), float(plan.get("trajectory_interval_ps") or 0)
    out.append(F("note", f"{key}：規劃 {p:g} ns × {reps} 份，{d[0]}，硬碟約 {tg:.1f} GB，每 {iv:g} ps 存一幀，分成 {plan.get('n_chunks', 0)} 段。",
                 f"{key}: planned {p:g} ns × {reps} replica(s), {d[1]}, about {tg:.1f} GB of disk, one frame every {iv:g} ps in {plan.get('n_chunks', 0)} chunks.",
                 f"{key}：計画は {p:g} ns × {reps} 回、{d[2]}、ディスク約 {tg:.1f} GB、{iv:g} ps ごとに 1 フレーム、{plan.get('n_chunks', 0)} 区間です。",
                 f"{key}: 계획은 {p:g} ns × {reps}회, {d[3]}, 디스크 약 {tg:.1f} GB, {iv:g} ps마다 한 프레임, {plan.get('n_chunks', 0)}구간입니다."))
    if p > 1000:
        out.append(F("note", f"{key}：長度超過 1 µs，使用者已確認天數與硬碟用量後才開始。",
                     f"{key}: longer than 1 µs, started only after the user confirmed the days and disk use.",
                     f"{key}：長さが 1 µs を超えるため、ユーザーが日数とディスク使用量を確認してから開始しました。",
                     f"{key}: 길이가 1 µs를 넘어 사용자가 일수와 디스크 사용량을 확인한 뒤 시작했습니다."))
    if reps < 2:
        out.append(F("note", f"{key}：一條長軌跡不能取代獨立重複。單一長軌跡可能一直停在同一個能量盆地，收斂圖只能檢查軌跡內部的一致性。",
                     f"{key}: one long trajectory is not a substitute for independent replicas. It can stay in one basin, and the convergence plots only check consistency within the trajectory.",
                     f"{key}：1 本の長い軌跡は独立な繰り返しの代わりにはなりません。同じエネルギーの谷にとどまり続けることがあり、収束の図は軌跡の内部での一貫性しか確かめられません。",
                     f"{key}: 긴 궤적 하나가 독립 반복을 대신할 수는 없습니다. 한 에너지 분지에 계속 머물 수 있으며 수렴 그림은 궤적 내부의 일관성만 확인합니다."))
    return out


def coarse_grained(name: str, rec: dict) -> list[dict]:
    plan = rec.get("plan") or {}
    out = []
    for i in plan.get("issues") or []:
        t = i.get("text")
        if isinstance(t, (list, tuple)) and len(t) == 4:
            out.append(F("caution", *t))
    if not out and plan.get("status") == "PASS":
        out.append(F("good", f"{name}：粗粒化工具與 Martini 3 力場檔都齊全，計畫的 {len(plan.get('steps') or [])} 個步驟可以執行。",
                     f"{name}: the coarse-grained tools and Martini 3 force-field files are all present, so the {len(plan.get('steps') or [])} planned steps can run.",
                     f"{name}：粗視化ツールと Martini 3 の力場ファイルがそろっており、計画した {len(plan.get('steps') or [])} 段階を実行できます。",
                     f"{name}: 조립화 도구와 Martini 3 역장 파일이 모두 있어 계획한 {len(plan.get('steps') or [])}단계를 실행할 수 있습니다."))
    return out


def coarse_grained_results(name: str, d: dict) -> list[dict]:
    """D-86: protein backbone-bead RMSD and, for surface systems, how often the peptide touched the phosphate beads."""
    out = []
    r = d.get("protein_rmsd_nm") or []
    if r:
        last = float(r[-1])
        lvl = "good" if last < 0.4 else "caution"
        out.append(F(lvl, f"{name}：蛋白骨架珠相對第一幀的 RMSD 最後為 {last:.2f} nm（彈性網路固定三級結構，大於 0.4 nm 表示整體形狀改變，請看軌跡）。",
                     f"{name}: the backbone-bead RMSD from the first frame ends at {last:.2f} nm (the elastic network holds the "
                     "tertiary structure; above 0.4 nm the overall shape has changed, so look at the trajectory).",
                     f"{name}：最初のフレームに対する骨格ビーズの RMSD は最後に {last:.2f} nm です（弾性ネットワークが三次構造を固定"
                     "します。0.4 nm を超えると全体の形が変わっているので、軌跡を確認してください）。",
                     f"{name}: 첫 프레임 대비 골격 비드 RMSD는 마지막에 {last:.2f} nm입니다(탄성 네트워크가 삼차 구조를 고정하며 "
                     "0.4 nm를 넘으면 전체 모양이 바뀐 것이므로 궤적을 확인하십시오)."))
    if "contact_frac" in d:
        c = float(d["contact_frac"])
        dz = d.get("solute_dz_nm") or [0.0]
        out.append(F("note", f"{name}：胜肽有 {c:.0%} 的幀與磷酸珠距離在 0.7 nm 內；最後離磷酸平面 {float(dz[-1]):.2f} nm。"
                     "粗粒化的接觸是珠子層級，不能說明個別氫鍵或鹽橋。",
                     f"{name}: the peptide was within 0.7 nm of the phosphate beads in {c:.0%} of the frames and ended "
                     f"{float(dz[-1]):.2f} nm from the phosphate plane. Coarse-grained contacts are bead-level and say nothing "
                     "about individual hydrogen bonds or salt bridges.",
                     f"{name}：ペプチドはフレームの {c:.0%} でリン酸ビーズから 0.7 nm 以内にあり、最後はリン酸の面から "
                     f"{float(dz[-1]):.2f} nm でした。粗視化の接触はビーズ単位で、個々の水素結合や塩橋はわかりません。",
                     f"{name}: 펩타이드는 프레임의 {c:.0%}에서 인산 비드와 0.7 nm 이내에 있었고 마지막에는 인산 평면에서 "
                     f"{float(dz[-1]):.2f} nm 떨어져 있었습니다. 조립화 접촉은 비드 단위라 개별 수소 결합이나 염다리는 알 수 없습니다."))
    return out

