"""General figure language for the report (D-54; spec: docs/specs/report_language.md).

Each figure kind has: a title, a caption (what is drawn), a reading guide (the same in every project) and outcome
scenarios.  `classify_<kind>(data)` decides which scenarios hold for this run and returns filled sentences.
All texts are (zh, en) pairs.  Pure Python + numpy.
"""
from __future__ import annotations

import numpy as np

FIG = {
    "docking_scores": {
        "title": ("對接姿勢分數", "Docking pose scores"),
        "caption": ("每個姿勢的 Vina 分數依名次排列；顏色代表叢集，★ 為選用姿勢。", "Vina score of each pose by rank; colour marks the cluster, ★ the pose used."),
        "read": ("分數越負越好；兩個分數相差小於 1 kcal mol⁻¹ 時在 Vina 誤差內，不能區分。同一叢集出現多個低分姿勢，表示搜尋收斂到同一結合模式。",
                 "More negative is better; scores closer than 1 kcal mol⁻¹ are within Vina's error and cannot be told apart. "
                 "Several low-scoring poses in one cluster mean the search converged on one binding mode."),
    },
    "screen_ranking": {
        "title": ("篩選排名", "Screening ranking"),
        "caption": ("化合物依 Vina 分數排序；灰色帶為與最佳差距 1 kcal mol⁻¹ 以內。", "Compounds ranked by Vina score; the grey band marks scores within 1 kcal mol⁻¹ of the best."),
        "read": ("灰色帶內的化合物彼此不能排序；分數容易隨分子變大而變負，應同時參考配體效率（每個重原子的分數）。",
                 "Compounds inside the grey band cannot be ordered against each other; scores become more negative with molecular "
                 "size, so ligand efficiency (score per heavy atom) should be read alongside."),
    },
    "rmsd": {
        "title": ("主鏈 RMSD", "Backbone RMSD"),
        "caption": ("主鏈原子相對於起始結構的均方根偏差隨時間的變化；每條線為一個系統。", "Root-mean-square deviation of backbone atoms from the starting structure over time; one line per system."),
        "read": ("曲線先上升後進入平台，代表結構已平衡；平台高度反映構形調整的幅度（小於 2 Å 小、2 到 3 Å 中等、大於 3 Å 大）；後半段仍持續上升代表尚未平衡。",
                 "The curve rises and then levels off once the structure has equilibrated; the plateau height reflects how much "
                 "the conformation adjusted (below 2 Å small, 2–3 Å moderate, above 3 Å large); a curve still rising in the "
                 "second half has not equilibrated."),
    },
    "rg": {
        "title": ("迴轉半徑", "Radius of gyration"),
        "caption": ("蛋白迴轉半徑隨時間的變化。", "Radius of gyration of the protein over time."),
        "read": ("數值穩定代表蛋白維持緊密摺疊；持續增加代表部分展開。", "A stable value means the protein stays compactly folded; a steady increase means partial unfolding."),
    },
    "ligand_rmsd": {
        "title": ("配體在口袋中的位移", "Ligand displacement in the pocket"),
        "caption": ("以蛋白口袋對齊後，配體相對於對接姿勢的 RMSD；虛線為 3 Å。", "Ligand RMSD from the docked pose after aligning on the pocket; the dashed line marks 3 Å."),
        "read": ("低於 2 Å 代表維持對接姿勢；2 到 3 Å 為姿勢調整；持續高於 3 Å 代表離開原結合位。短暫超過 3 Å 後回來屬於擺動，不代表解離。",
                 "Below 2 Å the docked pose is kept; 2–3 Å is a pose adjustment; staying above 3 Å means the ligand left the "
                 "docked site. A brief excursion above 3 Å followed by a return is a fluctuation, not dissociation."),
    },
    "rmsf": {
        "title": ("殘基柔性（RMSF）", "Residue flexibility (RMSF)"),
        "caption": ("每個殘基 Cα 原子的均方根擾動；多個系統疊圖，下方為複合物減蛋白單獨的差值。", "Root-mean-square fluctuation of each residue's Cα atom; systems overlaid, with the complex minus protein-alone difference below."),
        "read": ("峰值通常是 loop 與末端；結合後下降的區域多半是結合位或與結合位耦合的區域，上升的區域則是受結合擾動的部位。",
                 "Peaks are usually loops and termini; regions that become more rigid on binding usually line the binding site "
                 "or are coupled to it, while regions that become more flexible are perturbed by binding."),
    },
    "contacts": {
        "title": ("接觸頻率", "Contact frequency"),
        "caption": ("模擬時間中與配體距離小於 4 Å 的時間比例，依頻率排序。", "Fraction of simulation time each residue is within 4 Å of the ligand, sorted."),
        "read": ("75 % 以上為持續接觸，是結合的錨點；25 % 到 75 % 為間歇接觸；低於 25 % 為偶發。", "Above 75 % is a persistent contact that anchors the ligand; 25–75 % is intermittent; below 25 % is occasional."),
    },
    "smd": {
        "title": ("導向分子動力學的拉力與功", "Steered molecular dynamics: force and work"),
        "caption": ("拉力與累積功對彈簧位置作圖。", "Pulling force and accumulated work against the spring position."),
        "read": ("最大拉力對應主要的斷裂事件；功在末段趨平代表配體已完全脫離。功與拉速有關，不是自由能。",
                 "The force maximum marks the main rupture event; work levelling off at the end means the ligand has fully "
                 "detached. The work depends on the pulling speed and is not a free energy."),
    },
    "umbrella": {
        "title": ("傘狀採樣窗口分佈", "Umbrella-sampling window distributions"),
        "caption": ("每個窗口沿反應座標的取樣分佈。", "Sampling distribution of each window along the reaction coordinate."),
        "read": ("相鄰分佈必須互相重疊，自由能剖面才能連續；出現空隙的位置剖面不可信。", "Neighbouring distributions must overlap for the free-energy profile to be continuous; the profile is unreliable where a gap appears."),
    },
    "pmf": {
        "title": ("自由能剖面（PMF）", "Free-energy profile (PMF)"),
        "caption": ("自由能隨配體與口袋距離的變化；陰影為自助法誤差。", "Free energy against the ligand–pocket distance; the shading is the bootstrap error."),
        "read": ("最低點為結合狀態，最低點到末端平台的高度為 ΔPMF；末端必須平坦，否則 ΔPMF 會被低估。", "The minimum is the bound state and its depth below the final plateau is ΔPMF; the end must be flat, otherwise ΔPMF is underestimated."),
    },
}


def S(level, zh, en):
    return {"level": level, "text": (zh, en)}


def _plateau(t, y):
    t, y = np.asarray(t, float), np.asarray(y, float)
    n = len(y)
    h = y[n // 2:]
    th = t[n // 2:] if len(t) >= n else np.arange(len(h), dtype=float)
    drift = float(np.polyfit(th, h, 1)[0] * (th[-1] - th[0])) if len(h) > 2 and th[-1] > th[0] else 0.0
    return float(h.mean()), float(h.std()), drift


# ------------------------------------------------------------------------------------------- classifiers
def classify_docking_scores(name: str, poses: list[dict], chosen_rank: int | None) -> list[dict]:
    if not poses:
        return []
    sc = sorted(p["score"] for p in poses)
    gap = sc[1] - sc[0] if len(sc) > 1 else None
    rank = chosen_rank or 1
    p = next((q for q in poses if q["rank"] == rank), poses[0])
    frac = min(1.0, (p.get("cluster_size") or 1) / max(1, len(poses)))
    out = []
    if gap is not None and gap >= 1.0 and frac >= 0.3:
        out.append(S("good", f"{name} 的最佳姿勢（{sc[0]:.2f} kcal mol⁻¹）比第二名低 {gap:.2f} kcal mol⁻¹（≥ 1），且所屬叢集占全部姿勢的 {frac:.0%}，結合模式明確。",
                     f"For {name} the best pose ({sc[0]:.2f} kcal mol⁻¹) is {gap:.2f} kcal mol⁻¹ below the second (≥ 1) and its "
                     f"cluster holds {frac:.0%} of all poses, so the binding mode is clear."))
    elif gap is not None and gap < 1.0:
        out.append(S("note", f"{name} 前兩名分數相差 {gap:.2f} kcal mol⁻¹（< 1），在 Vina 誤差內等價；結合模式不能只由分數決定，需以模擬中的穩定性判斷。",
                     f"For {name} the top two poses differ by {gap:.2f} kcal mol⁻¹ (< 1), equivalent within Vina's error; the "
                     "binding mode cannot be decided from the score alone and is judged by stability in simulation."))
    if frac < 0.3:
        out.append(S("caution", f"{name} 選用姿勢的叢集只占 {frac:.0%}（< 30 %），低分姿勢分散在不同叢集，搜尋未收斂；建議提高搜尋強度或縮小搜尋區。",
                     f"For {name} the chosen pose's cluster holds only {frac:.0%} (< 30 %); low-scoring poses are spread over "
                     "different clusters and the search did not converge; raise the exhaustiveness or narrow the box."))
    r = p.get("rmsd_ref")
    if r is not None:
        out.append(S("good", f"重新對接與共結晶姿勢的 RMSD 為 {r:.2f} Å（≤ 2 Å），對接設定能重現晶體結構。",
                     f"Redocking reproduces the co-crystal pose at {r:.2f} Å RMSD (≤ 2 Å), so the docking setup is credible.")
                   if r <= 2.0 else
                   S("caution", f"重新對接與共結晶姿勢的 RMSD 為 {r:.2f} Å（> 2 Å），對接設定未能重現晶體結構，其他姿勢也應保守看待。",
                     f"Redocking deviates from the co-crystal pose by {r:.2f} Å (> 2 Å); the setup does not reproduce the "
                     "crystal, so the other poses should also be read with caution."))
    return out


def classify_screen(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    sc = [r["score"] for r in rows]
    out = []
    if len(sc) > 1 and sc[1] - sc[0] >= 1.0:
        out.append(S("good", f"{rows[0]['name']} 領先第二名 {sc[1] - sc[0]:.2f} kcal mol⁻¹（≥ 1），是明確的首選。",
                     f"{rows[0]['name']} leads the second compound by {sc[1] - sc[0]:.2f} kcal mol⁻¹ (≥ 1) and is a clear first choice."))
    near = [r for r in rows if r["score"] - sc[0] < 1.0]
    if len(near) >= 3:
        out.append(S("note", f"{len(near)} 個化合物落在與最佳差 1 kcal mol⁻¹ 的範圍內（{', '.join(r['name'] for r in near[:6])}），彼此的順序沒有意義，應一起進入下一步或以配體效率與化學多樣性挑選。",
                     f"{len(near)} compounds fall within 1 kcal mol⁻¹ of the best ({', '.join(r['name'] for r in near[:6])}); their "
                     "order carries no meaning, so take them forward together or choose by ligand efficiency and chemical diversity."))
    ha = np.array([r.get("heavy_atoms") or np.nan for r in rows], float)
    ok = np.isfinite(ha)
    if ok.sum() >= 6:
        rr = float(np.corrcoef(ha[ok], np.asarray(sc)[ok])[0, 1])
        if rr <= -0.6:
            out.append(S("caution", f"分數與重原子數的相關係數為 {rr:.2f}（≤ −0.6），排名主要反映分子大小；請以配體效率排序後再選擇。",
                         f"Score and heavy-atom count correlate at r = {rr:.2f} (≤ −0.6); the ranking mostly reflects molecular size, "
                         "so rank by ligand efficiency before choosing."))
    return out


def classify_rmsd(series: dict) -> list[dict]:
    """series: {system: (t_ns, rmsd_A)}"""
    out, means = [], {}
    for key, (t, y) in series.items():
        if len(y) < 8:
            continue
        m, sd, drift = _plateau(t, y)
        means[key] = m
        tail = f"後半段 {m:.2f} ± {sd:.2f} Å，漂移 {drift:+.2f} Å", f"second half {m:.2f} ± {sd:.2f} Å, drift {drift:+.2f} Å"
        if abs(drift) > 0.5:
            out.append(S("caution", f"{key}：RMSD 在後半段仍持續變化（{tail[0]}，> 0.5 Å），結構尚未平衡；需要延長模擬，後續分析只能定性參考。",
                         f"{key}: RMSD is still changing in the second half ({tail[1]}, > 0.5 Å); the structure has not equilibrated, "
                         "a longer simulation is needed and later analyses are qualitative only."))
        elif m > 3.0:
            out.append(S("caution", f"{key}：RMSD 平台高於 3 Å（{tail[0]}），蛋白發生大幅重排；需確認起始結構或約束策略是否合適。",
                         f"{key}: the RMSD plateau is above 3 Å ({tail[1]}); the protein rearranged substantially, so check the "
                         "starting structure and the restraint strategy."))
        elif m > 2.0:
            out.append(S("note", f"{key}：RMSD 經過調整後進入 2 到 3 Å 的平台（{tail[0]}），屬中度構形調整，常見於 loop 鬆弛。",
                         f"{key}: after an adjustment RMSD levels off at 2–3 Å ({tail[1]}), a moderate conformational change typical of loop relaxation."))
        else:
            out.append(S("good", f"{key}：RMSD 進入低於 2 Å 的平台（{tail[0]}），結構穩定且已平衡。",
                         f"{key}: RMSD levels off below 2 Å ({tail[1]}); the structure is stable and equilibrated."))
    ref = next((k for k in means if k.lower().startswith("apo")), None)
    if ref is not None:
        for k, m in means.items():
            if k == ref:
                continue
            d = m - means[ref]
            if d <= -0.3:
                out.append(S("good", f"{k} 的平台比蛋白單獨低 {abs(d):.2f} Å（≥ 0.3），配體結合使蛋白更穩定。",
                             f"{k} plateaus {abs(d):.2f} Å below the protein alone (≥ 0.3); ligand binding stabilises the protein."))
            elif d >= 0.3:
                out.append(S("note", f"{k} 的平台比蛋白單獨高 {d:.2f} Å（≥ 0.3），配體結合使蛋白構形調整較大。",
                             f"{k} plateaus {d:.2f} Å above the protein alone (≥ 0.3); the protein adjusts more with the ligand bound."))
            else:
                out.append(S("note", f"{k} 與蛋白單獨的平台相差 {d:+.2f} Å（小於 0.3），整體構形穩定性相當。",
                             f"{k} and the protein alone plateau within {d:+.2f} Å (less than 0.3); overall stability is comparable."))
    return out


def classify_rg(series: dict) -> list[dict]:
    out = []
    for key, (t, y) in series.items():
        y = np.asarray(y, float)
        if len(y) < 10:
            continue
        start = float(y[: max(1, len(y) // 10)].mean())
        m, sd, _ = _plateau(t, y)
        change = (m - start) / start
        if change > 0.05:
            out.append(S("caution", f"{key}：迴轉半徑由 {start:.2f} Å 增加到 {m:.2f} Å（{change:+.1%}，> 5 %），蛋白明顯擴張，可能部分展開。",
                         f"{key}: radius of gyration grows from {start:.2f} Å to {m:.2f} Å ({change:+.1%}, > 5 %); the protein expands markedly and may be partly unfolding."))
        elif change > 0.02:
            out.append(S("note", f"{key}：迴轉半徑由 {start:.2f} Å 增加到 {m:.2f} Å（{change:+.1%}），輕微擴張，多為表面 loop 鬆弛。",
                         f"{key}: radius of gyration grows from {start:.2f} Å to {m:.2f} Å ({change:+.1%}), a slight expansion usually from surface loops."))
        else:
            out.append(S("good", f"{key}：迴轉半徑維持在 {m:.2f} ± {sd:.2f} Å，蛋白保持緊密摺疊。",
                         f"{key}: radius of gyration stays at {m:.2f} ± {sd:.2f} Å; the protein remains compactly folded."))
    return out


def classify_ligand_rmsd(key: str, lig: str, t, y) -> list[dict]:
    t, y = np.asarray(t, float), np.asarray(y, float)
    if len(y) < 5:
        return []
    last = float(y[-max(1, len(y) // 5):].mean())
    mx = float(y.max())
    if last >= 3.0:
        above = y >= 3.0
        idx = next((i for i in range(len(y)) if above[i:].all()), None)
        when = (f"，約在 {t[idx]:.1f} ns 之後持續高於 3 Å" if idx is not None and idx < len(t) else "",
                f", staying above 3 Å from about {t[idx]:.1f} ns" if idx is not None and idx < len(t) else "")
        return [S("caution", f"{key} 的 {lig}：最後 20 % 時間平均 {last:.1f} Å{when[0]}，配體離開了對接位置；這個對接姿勢在動態下不成立，對接分數不能作為結合證據。",
                  f"{lig} in {key}: {last:.1f} Å on average over the last 20 %{when[1]}; the ligand left the docked position, so the "
                  "docked pose does not hold in dynamics and its score is not evidence of binding.")]
    if mx > 3.0 and last < 2.0:
        return [S("note", f"{key} 的 {lig}：曾短暫偏離到 {mx:.1f} Å，之後回到口袋（最後 20 % 為 {last:.1f} Å），屬於結合狀態下的擺動。",
                  f"{lig} in {key}: briefly moved out to {mx:.1f} Å and returned (last 20 %: {last:.1f} Å), a fluctuation within the bound state.")]
    if last >= 2.0:
        return [S("note", f"{key} 的 {lig}：留在口袋內但姿勢調整（最後 20 % 為 {last:.1f} Å，2 到 3 Å），模擬中的結合模式與對接姿勢不完全相同。",
                  f"{lig} in {key}: stays in the pocket but adjusts its pose (last 20 %: {last:.1f} Å, 2–3 Å); the simulated binding mode differs somewhat from the docked one.")]
    return [S("good", f"{key} 的 {lig}：全程維持對接姿勢（最後 20 % 為 {last:.1f} Å，< 2 Å），結合模式在模擬時間內穩定。",
              f"{lig} in {key}: keeps the docked pose throughout (last 20 %: {last:.1f} Å, < 2 Å); the binding mode is stable over the simulated time.")]


def classify_rmsf(names: list[str], ref: np.ndarray, other: np.ndarray, label: str) -> list[dict]:
    ref, other = np.asarray(ref, float), np.asarray(other, float)
    n = min(len(ref), len(other))
    if n < 5:
        return []
    d = other[:n] - ref[:n]
    out = []
    order = np.argsort(d)
    rig = [(names[i] if i < len(names) else str(i), d[i]) for i in order[:6] if d[i] <= -0.3]
    if rig:
        out.append(S("good", f"{label} 中柔性下降最多的殘基：" + "、".join(f"{a}（{b:+.2f} Å）" for a, b in rig) + "；這些位置多半構成結合位或與之耦合。",
                     f"Residues that become most rigid in {label}: " + ", ".join(f"{a} ({b:+.2f} Å)" for a, b in rig) + "; they usually form or couple to the binding site."))
    if float(d.mean()) >= 0.2:
        out.append(S("caution", f"{label} 的平均 RMSF 比蛋白單獨高 {d.mean():.2f} Å（≥ 0.2），結合使蛋白整體變得較不穩定。",
                     f"Mean RMSF in {label} is {d.mean():.2f} Å above the protein alone (≥ 0.2); binding makes the protein less stable overall."))
    elif not rig:
        out.append(S("note", f"{label} 與蛋白單獨的柔性分佈相當（平均差 {d.mean():+.2f} Å），沒有明顯受結合影響的區域。",
                     f"Flexibility in {label} matches the protein alone (mean difference {d.mean():+.2f} Å); no region is clearly affected by binding."))
    return out


def classify_contacts(key: str, lig: str, freq: dict) -> list[dict]:
    items = sorted(freq.items(), key=lambda kv: -kv[1])
    if not items:
        return [S("caution", f"{key} 的 {lig}：模擬中沒有持續的口袋接觸。", f"{lig} in {key}: no sustained pocket contact during the simulation.")]
    anchors = [(a, b) for a, b in items if b >= 0.75]
    txt_zh = "、".join(f"{a}（{b:.0%}）" for a, b in (anchors or items)[:6])
    txt_en = ", ".join(f"{a} ({b:.0%})" for a, b in (anchors or items)[:6])
    if len(anchors) >= 3:
        return [S("good", f"{key} 的 {lig} 有 {len(anchors)} 個持續接觸的錨點殘基（≥ 75 %）：{txt_zh}；結合由多點作用穩定。",
                  f"{lig} in {key} has {len(anchors)} persistent anchor residues (≥ 75 %): {txt_en}; binding is held by several contacts.")]
    if anchors:
        return [S("note", f"{key} 的 {lig} 只有 {len(anchors)} 個持續接觸的殘基：{txt_zh}；結合依賴少數作用點，對突變或結構差異較敏感。",
                  f"{lig} in {key} has only {len(anchors)} persistent contact{'s' if len(anchors) > 1 else ''} ({txt_en}); binding relies on few "
                  "interactions and is sensitive to mutations or structural differences.")]
    top = items[0][1]
    lvl = "caution" if top < 0.5 else "note"
    return [S(lvl, f"{key} 的 {lig} 沒有持續接觸（最高 {top:.0%}：{txt_zh}），配體在口袋內移動，結合鬆散。",
              f"{lig} in {key} has no persistent contact (highest {top:.0%}: {txt_en}); the ligand moves within the pocket and binds loosely.")]


def classify_smd(pos, force, work, name: str) -> list[dict]:
    pos, force, work = (np.asarray(x, float) for x in (pos, force, work))
    if len(force) < 10:
        return []
    out = []
    i = int(np.argmax(force))
    fmax = float(force[i])
    k = max(3, len(force) // 25)
    sm = np.convolve(force, np.ones(k) / k, mode="same")
    peaks = [j for j in range(1, len(sm) - 1) if sm[j] > sm[j - 1] and sm[j] >= sm[j + 1] and sm[j] >= 0.5 * sm.max()]
    merged = []
    for j in peaks:
        if not merged or pos[j] - pos[merged[-1]] > 0.15:
            merged.append(j)
    if len(merged) >= 2:
        out.append(S("note", f"{name}：拉力出現 {len(merged)} 個主要峰（位置 " + "、".join(f"{pos[j]:.2f}" for j in merged) + " nm），配體分段脫離，每一段對應一組作用被打斷。",
                     f"{name}: the force shows {len(merged)} main peaks (at " + ", ".join(f"{pos[j]:.2f}" for j in merged) + " nm); the ligand "
                     "detaches in stages, each breaking a set of interactions."))
    else:
        out.append(S("note", f"{name}：最大拉力 {fmax:.0f} kJ mol⁻¹ nm⁻¹ 出現在 {pos[i]:.2f} nm，為單一主要斷裂事件。",
                     f"{name}: a single main rupture with a peak force of {fmax:.0f} kJ mol⁻¹ nm⁻¹ at {pos[i]:.2f} nm."))
    n20 = max(2, len(work) // 5)
    rise = float(work[-1] - work[-n20])
    total = float(work[-1] - work[0]) or 1.0
    if abs(rise / total) < 0.05:
        out.append(S("good", f"{name}：功在最後 20 % 增加不到 5 %，配體已完全脫離口袋。", f"{name}: the work rises by less than 5 % over the last 20 %; the ligand has fully detached."))
    else:
        out.append(S("caution", f"{name}：功在最後 20 % 仍增加 {rise / total:.0%}，配體可能尚未完全脫離；建議加長拉離距離。",
                     f"{name}: the work still rises by {rise / total:.0%} over the last 20 %, so the ligand may not have fully detached; increase the pulling distance."))
    return out


def classify_umbrella(coverage: dict, name: str) -> list[dict]:
    if not coverage:
        return []
    br = coverage.get("breaks") or []
    if coverage.get("continuous") and not br:
        return [S("good", f"{name}：{coverage.get('n_windows', '多')} 個窗口的分佈在整條路徑上互相重疊，剖面連續。",
                  f"{name}: the {coverage.get('n_windows', '')} windows overlap along the whole path, so the profile is continuous.")]
    where = "、".join(f"{b[0]:.2f}–{b[1]:.2f} nm" if isinstance(b, (list, tuple)) and len(b) == 2 else str(b) for b in br[:5])
    return [S("caution", f"{name}：分佈在 {where} 出現空隙，這些位置的自由能剖面不可信；需要補窗口。",
              f"{name}: the distributions leave gaps at {where}; the profile is unreliable there and windows must be added.")]


def classify_pmf(grid, W, err, name: str) -> list[dict]:
    g, W = np.asarray(grid, float), np.asarray(W, float)
    if len(W) < 6:
        return []
    i = int(np.nanargmin(W))
    tail = W[g >= g[-1] - 0.2]
    gt = g[g >= g[-1] - 0.2]
    depth = float(np.nanmean(tail) - W[i])
    slope = float(np.polyfit(gt, tail, 1)[0]) if len(tail) >= 3 else 0.0
    out = [S("note", f"{name}：最低點在 {g[i]:.2f} nm，相對末端平台的井深約 {depth:.1f} kJ mol⁻¹（{depth / 4.184:.1f} kcal mol⁻¹）。",
             f"{name}: the minimum lies at {g[i]:.2f} nm, about {depth:.1f} kJ mol⁻¹ ({depth / 4.184:.1f} kcal mol⁻¹) below the final plateau.")]
    if abs(slope) > 2.0:
        out.append(S("caution", f"{name}：剖面末端仍有斜率（{slope:.1f} kJ mol⁻¹ nm⁻¹，> 2），配體尚未到達完全解離的平台，井深可能被低估；需加長路徑。",
                     f"{name}: the end of the profile still slopes ({slope:.1f} kJ mol⁻¹ nm⁻¹, > 2); the fully dissociated plateau is not reached and the depth may be underestimated; extend the path."))
    else:
        out.append(S("good", f"{name}：剖面末端平坦（斜率 {slope:.1f} kJ mol⁻¹ nm⁻¹），已到達解離狀態。",
                     f"{name}: the end of the profile is flat (slope {slope:.1f} kJ mol⁻¹ nm⁻¹), so the dissociated state is reached."))
    if depth > 80:
        out.append(S("caution", f"{name}：井深超過 80 kJ mol⁻¹，對多數藥物大小的分子不合理，常見原因是窗口取樣不足或拉離路徑扭曲蛋白。",
                     f"{name}: a depth above 80 kJ mol⁻¹ is implausible for most drug-sized molecules; insufficient sampling or a "
                     "pulling path that distorts the protein are the usual causes."))
    if err is not None:
        e = np.asarray(err, float)
        emax = float(np.nanmax(e[np.isfinite(e)])) if np.isfinite(e).any() else 0.0
        if depth > 0 and emax > 0.2 * depth:
            out.append(S("caution", f"{name}：最大誤差 {emax:.1f} kJ mol⁻¹ 超過井深的 20 %，取樣不足以支持定量比較。",
                         f"{name}: the largest error, {emax:.1f} kJ mol⁻¹, exceeds 20 % of the depth; sampling does not support a quantitative comparison."))
    return out
