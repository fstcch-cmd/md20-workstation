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


# =========================================================================================== D-58: extended figures
FIG.update({
    "equil_quality": {
        "title": ("平衡過程品質", "Equilibration quality"),
        "caption": ("各階段（加熱、定壓平衡、正式模擬）的溫度、位能、密度與盒體積隨時間的變化。", "Temperature, potential energy, density and box volume over time in each stage (heating, pressure equilibration, production)."),
        "read": ("溫度應在目標值附近穩定擾動；密度與盒體積在定壓平衡後段應進入平台；位能持續下降代表結構仍在鬆弛。",
                 "Temperature should fluctuate around its target; density and box volume should level off by the end of pressure equilibration; a potential energy still falling means the structure is still relaxing."),
    },
    "minimization": {
        "title": ("能量最小化", "Energy minimisation"),
        "caption": ("各約束階段最小化後的位能。", "Potential energy after each restrained minimisation stage."),
        "read": ("位能應逐階段下降；大幅下降代表起始結構有碰撞已被消除，最後一階段仍大幅下降代表結構需要更多最小化。",
                 "Energy should fall stage by stage; a large drop means clashes in the starting structure were removed, a large drop in the last stage means more minimisation is needed."),
    },
    "replicas": {
        "title": ("獨立重複的比較", "Independent replicas"),
        "caption": ("各重複（不同初速）的溫度與位能。", "Temperature and potential energy of each replica (different initial velocities)."),
        "read": ("各重複應落在相同範圍；若某一重複明顯偏離，代表系統有多個狀態或該重複出現問題。",
                 "Replicas should overlap; one that departs clearly points to several states or a problem in that replica."),
    },
    "hbond_count": {
        "title": ("配體與蛋白的氫鍵數", "Ligand–protein hydrogen bonds"),
        "caption": ("每一幀配體與蛋白之間的氫鍵數（Wernet–Nilsson 幾何判準）。", "Number of ligand–protein hydrogen bonds per frame (Wernet–Nilsson geometric criterion)."),
        "read": ("平均兩個以上代表極性作用是結合的主要錨點；接近零代表結合主要靠疏水與凡得瓦作用。數目隨時間下降代表極性作用逐漸喪失。",
                 "Two or more on average means polar interactions anchor the ligand; near zero means binding relies on hydrophobic and van der Waals contacts. A falling count means polar interactions are being lost."),
    },
    "hbond_occupancy": {
        "title": ("氫鍵佔有率", "Hydrogen-bond occupancy"),
        "caption": ("每一組供體與受體之間氫鍵存在的時間比例（供體 → 受體）。", "Fraction of time each donor–acceptor hydrogen bond exists (donor → acceptor)."),
        "read": ("50 % 以上為穩定氫鍵；20 % 到 50 % 為間歇；同一殘基多組氫鍵代表關鍵作用位。", "Above 50 % is a stable hydrogen bond, 20–50 % intermittent; several bonds to one residue mark a key interaction site."),
    },
    "com_distance": {
        "title": ("配體與口袋的質心距離", "Ligand–pocket centre-of-mass distance"),
        "caption": ("配體質心到口袋原子質心的距離，以及配體與蛋白的極性接觸數（N、O 原子間 3.5 Å 內）。", "Distance between the centres of mass of ligand and pocket, and the number of ligand–protein polar contacts (N and O atoms within 3.5 Å)."),
        "read": ("距離穩定代表配體留在原位；持續增加代表逐漸離開；極性接觸同時減少則代表結合正在瓦解。", "A steady distance means the ligand stays in place; a rising distance means it is leaving; fewer polar contacts at the same time mean the binding is breaking up."),
    },
    "ligand_burial": {
        "title": ("配體埋藏程度", "Ligand burial"),
        "caption": ("配體被蛋白遮蔽的表面比例（1 − 複合物中的溶劑可及面積 ÷ 單獨配體的溶劑可及面積）。", "Fraction of the ligand surface shielded by the protein (1 − solvent-accessible area in the complex ÷ area of the free ligand)."),
        "read": ("70 % 以上代表深埋於口袋；40 % 到 70 % 為部分埋藏；低於 40 % 代表大部分暴露在溶劑中，屬於表面結合。", "Above 70 % the ligand is deeply buried; 40–70 % partly buried; below 40 % mostly exposed to solvent, i.e. surface binding."),
    },
    "protein_sasa": {
        "title": ("蛋白溶劑可及面積", "Protein solvent-accessible surface area"),
        "caption": ("蛋白總溶劑可及面積隨時間的變化。", "Total solvent-accessible surface area of the protein over time."),
        "read": ("穩定代表摺疊維持；持續增加代表疏水核心暴露或展開。", "A stable value means the fold is kept; a steady increase means the hydrophobic core is opening or unfolding."),
    },
    "dssp": {
        "title": ("二級結構", "Secondary structure"),
        "caption": ("α 螺旋、β 摺板與其他結構所占比例隨時間的變化（DSSP）。", "Fractions of α-helix, β-strand and other structure over time (DSSP)."),
        "read": ("比例穩定代表二級結構保持；螺旋或摺板比例下降代表局部展開。", "Stable fractions mean the secondary structure is kept; a falling helix or strand fraction means local unfolding."),
    },
    "hbond_protein": {
        "title": ("蛋白內部氫鍵", "Protein internal hydrogen bonds"),
        "caption": ("蛋白分子內氫鍵總數隨時間的變化。", "Total number of hydrogen bonds within the protein over time."),
        "read": ("數目穩定代表結構完整；持續下降代表結構逐漸鬆散。", "A steady number means an intact structure; a steady decrease means the structure is loosening."),
    },
    "pca_landscape": {
        "title": ("構形自由能地形（主成分分析）", "Conformational free-energy landscape (principal component analysis)"),
        "caption": ("Cα 座標的前兩個主成分構成的自由能地形，顏色越深能量越低。", "Free-energy landscape on the first two principal components of Cα coordinates; darker is lower free energy."),
        "read": ("單一深谷代表蛋白停留在一個主要構形；多個谷代表多個構形狀態與其間的轉換。前兩個主成分解釋的變異越高，地形越能代表整體運動。",
                 "One deep basin means one dominant conformation; several basins mean several states and transitions between them. The more variance the two components explain, the better the map represents the overall motion."),
    },
    "clusters": {
        "title": ("構形叢集", "Conformational clusters"),
        "caption": ("以 Cα 與配體 RMSD（2 Å 門檻）分群後各叢集的比例，以及每一幀所屬的叢集。", "Population of each cluster from Cα and ligand RMSD (2 Å cutoff), and the cluster of each frame over time."),
        "read": ("最大叢集超過 60 % 代表有主導的結合構形；多個比例相近的叢集代表結合模式在模擬中變動。代表結構為每個叢集中心的幀。",
                 "A largest cluster above 60 % means a dominant bound conformation; several clusters of similar size mean the binding mode changes during the simulation. The representative structure is the centre frame of each cluster."),
    },
    "dccm": {
        "title": ("動態交互相關（DCCM）", "Dynamic cross-correlation (DCCM)"),
        "caption": ("Cα 位移之間的相關係數：紅色同向運動、藍色反向運動。", "Correlation of Cα displacements: red moves together, blue moves in opposite directions."),
        "read": ("對角線附近的相關來自鏈上相鄰殘基；遠離對角線的強相關代表區域之間的協同運動，結合前後的差異可指出受配體影響的長距離耦合。",
                 "Correlation near the diagonal comes from neighbouring residues; strong correlation far from the diagonal shows coordinated motion between regions, and its change on binding points to long-range coupling affected by the ligand."),
    },
    "fingerprint": {
        "title": ("作用指紋", "Interaction fingerprint"),
        "caption": ("每個殘基與配體在每一幀的作用類型（離子、極性、疏水）。", "Interaction type between each residue and the ligand in every frame (ionic, polar, hydrophobic)."),
        "read": ("整列連續著色代表持續作用；斷斷續續代表間歇作用；作用類型改變代表結合模式在調整。", "A continuously coloured row is a persistent interaction; a broken row is intermittent; a change of type means the binding mode is adjusting."),
    },
    "water_bridges": {
        "title": ("水橋", "Water bridges"),
        "caption": ("同時與配體及蛋白極性原子相距 3.5 Å 內的水分子數。", "Number of water molecules within 3.5 Å of both a ligand and a protein polar atom."),
        "read": ("平均一個以上代表水分子參與結合，取代或移除這些水可能改變親和力；接近零代表配體與蛋白直接接觸。", "One or more on average means water takes part in binding and displacing it may change affinity; near zero means direct ligand–protein contact."),
    },
    "overlap_matrix": {
        "title": ("窗口重疊矩陣", "Window overlap matrix"),
        "caption": ("每兩個傘狀採樣窗口分佈之間的重疊程度。", "Overlap between the sampling distributions of every pair of umbrella windows."),
        "read": ("相鄰窗口（對角線旁）重疊應至少 0.2；低於 0.05 的位置等於斷開，該處的自由能不可信。", "Neighbouring windows (next to the diagonal) should overlap by at least 0.2; below 0.05 the profile is effectively broken there."),
    },
    "pmf_convergence": {
        "title": ("自由能剖面的收斂", "Convergence of the free-energy profile"),
        "caption": ("只用每個窗口前 25 %、50 %、75 % 與全部取樣計算的自由能剖面。", "Free-energy profiles computed from the first 25 %, 50 %, 75 % and all of each window's samples."),
        "read": ("曲線隨取樣增加而重合代表已收斂；井深仍持續變化代表需要更長的窗口。", "Curves that coincide as sampling grows mean convergence; a depth that keeps changing means longer windows are needed."),
    },
    "properties": {
        "title": ("化合物性質分佈", "Compound property distributions"),
        "caption": ("化合物的分子量、logP、極性表面積、氫鍵供體與受體及可轉動鍵分佈；虛線為類藥性門檻。", "Distributions of molecular weight, logP, polar surface area, hydrogen-bond donors and acceptors and rotatable bonds; dashed lines are drug-likeness limits."),
        "read": ("落在虛線外的化合物口服吸收或穿膜的機率較低（Lipinski 與 Veber 規則）；天然物常違反一到兩項，屬經驗規則而非排除條件。",
                 "Compounds beyond the dashed lines are less likely to be orally absorbed or membrane-permeable (Lipinski and Veber rules); natural products often break one or two, so these are guidelines rather than exclusion criteria."),
    },
    "chem_space": {
        "title": ("化學空間", "Chemical space"),
        "caption": ("以分子指紋的主成分將化合物投影到平面，顏色為對接分數。", "Compounds projected on the principal components of their molecular fingerprints, coloured by docking score."),
        "read": ("相近的點代表結構相似；高分化合物集中在一區代表某一結構類型有利結合，分散則代表多種骨架都可能結合。", "Nearby points are structurally similar; high-scoring compounds grouped in one region point to a favourable scaffold, scattered ones to several possible scaffolds."),
    },
    "interaction_2d": {
        "title": ("二維作用圖", "Two-dimensional interaction diagram"),
        "caption": ("選用姿勢中配體每個原子最近的蛋白殘基與作用類型：藍色氫鍵、紅色離子、金色疏水、灰色其他接觸。", "Nearest protein residue and interaction class for each ligand atom in the chosen pose: blue hydrogen bond, red ionic, gold hydrophobic, grey other contact."),
        "read": ("標示殘基即對接姿勢的接觸點；與模擬中的作用指紋比對，可看出哪些作用在動態下維持。", "Labelled residues are the contacts of the docked pose; comparing them with the simulation's interaction fingerprint shows which interactions survive in dynamics."),
    },
    "screen_hist": {
        "title": ("篩選分數分佈", "Screening score distribution"),
        "caption": ("所有化合物的 Vina 分數分佈。", "Distribution of Vina scores of all compounds."),
        "read": ("分佈左側的長尾是值得進一步研究的候選；整體分佈狹窄代表化合物庫與標靶的差異性不大。", "The long tail on the left holds candidates worth pursuing; a narrow distribution means the library differs little against this target."),
    },
    "screen_scatter": {
        "title": ("分數與分子大小", "Score against molecular size"),
        "caption": ("Vina 分數對重原子數作圖。", "Vina score against heavy-atom count."),
        "read": ("分數隨分子變大而變負是評分函數的已知偏差；落在趨勢下方（同樣大小但分數更好）的化合物配體效率較高。", "Scores becoming more negative with size is a known bias of the scoring function; compounds below the trend (better score at the same size) have higher ligand efficiency."),
    },
})


def _halves(y):
    y = np.asarray(y, float)
    n = len(y)
    return float(y[: max(1, n // 10)].mean()), float(y[n // 2:].mean())


def classify_equil(rows: list[dict], key: str) -> list[dict]:
    """rows: acceptance checks [{"stage", "check", "ok", ...}] of one system."""
    if not rows:
        return []
    bad = [r for r in rows if not r.get("ok")]
    if not bad:
        return [S("good", f"{key}：{len(rows)} 項驗收（溫度、密度）全部通過，平衡完成。", f"{key}: all {len(rows)} acceptance checks (temperature, density) pass; equilibration is complete.")]
    return [S("caution", f"{key}：{len(bad)} 項驗收未通過（" + "、".join(f"{r['stage']} {r['check']}" for r in bad) + "），該階段可能未平衡，後續結果需保守看待。",
              f"{key}: {len(bad)} acceptance check(s) fail (" + ", ".join(f"{r['stage']} {r['check']}" for r in bad) + "); that stage may not be equilibrated and later results should be read with caution.")]


def classify_minimization(energies, key: str) -> list[dict]:
    e = np.asarray(energies, float)
    if len(e) < 2:
        return []
    drop = e[0] - e[-1]
    last = e[-2] - e[-1]
    out = [S("good" if drop > 0 else "caution", f"{key}：最小化使位能下降 {drop:,.0f} kJ mol⁻¹。", f"{key}: minimisation lowers the potential energy by {drop:,.0f} kJ mol⁻¹.")]
    if drop > 0 and last > 0.3 * drop:
        out.append(S("note", f"{key}：最後一階段仍下降 {last / drop:.0%}，結構在完全釋放約束後仍有可觀的鬆弛。", f"{key}: the last stage still accounts for {last / drop:.0%} of the drop; the structure relaxes considerably once restraints are released."))
    return out


def classify_hbond_count(series: dict) -> list[dict]:
    out = []
    for name, (t, y) in series.items():
        if len(y) < 5:
            continue
        a, b = _halves(y)
        if b >= 2:
            out.append(S("good", f"{name}：後半段平均 {b:.1f} 個氫鍵（≥ 2），極性作用是結合的主要錨點。", f"{name}: {b:.1f} hydrogen bonds on average in the second half (≥ 2); polar interactions anchor the ligand."))
        elif b >= 0.5:
            out.append(S("note", f"{name}：後半段平均 {b:.1f} 個氫鍵，極性作用有貢獻但不是主要錨點。", f"{name}: {b:.1f} hydrogen bonds on average in the second half; polar interactions contribute but do not anchor the ligand."))
        else:
            out.append(S("note", f"{name}：幾乎沒有氫鍵（平均 {b:.1f}），結合主要依賴疏水與凡得瓦作用。", f"{name}: almost no hydrogen bonds (average {b:.1f}); binding relies on hydrophobic and van der Waals contacts."))
        if a - b >= 1.0:
            out.append(S("caution", f"{name}：氫鍵數由開始的 {a:.1f} 降到 {b:.1f}，極性作用逐漸喪失。", f"{name}: hydrogen bonds fall from {a:.1f} at the start to {b:.1f}; polar interactions are being lost."))
    return out


def classify_hbond_occupancy(name: str, occ: list) -> list[dict]:
    if not occ:
        return [S("note", f"{name}：模擬中沒有出現配體與蛋白的氫鍵。", f"{name}: no ligand–protein hydrogen bond appears in the simulation.")]
    stable = [(k, v) for k, v in occ if v >= 0.5]
    if stable:
        return [S("good", f"{name}：{len(stable)} 組穩定氫鍵（≥ 50 %）：" + "；".join(f"{k}（{v:.0%}）" for k, v in stable[:5]) + "。",
                  f"{name}: {len(stable)} stable hydrogen bond(s) (≥ 50 %): " + "; ".join(f"{k} ({v:.0%})" for k, v in stable[:5]) + ".")]
    k, v = occ[0]
    return [S("note", f"{name}：沒有穩定氫鍵；最常出現的是 {k}（{v:.0%}），氫鍵屬間歇性。", f"{name}: no stable hydrogen bond; the most frequent is {k} ({v:.0%}), so hydrogen bonding is intermittent.")]


def classify_com(name: str, t, d) -> list[dict]:
    d = np.asarray(d, float)
    if len(d) < 5:
        return []
    a, b = _halves(d)
    if b - a > 2.0:
        return [S("caution", f"{name}：質心距離由 {a:.1f} Å 增加到 {b:.1f} Å（> 2 Å），配體正在離開口袋。", f"{name}: the centre-of-mass distance grows from {a:.1f} Å to {b:.1f} Å (> 2 Å); the ligand is leaving the pocket.")]
    return [S("good", f"{name}：質心距離維持在 {b:.1f} Å 附近（變化 {b - a:+.1f} Å），配體留在原位。", f"{name}: the centre-of-mass distance stays near {b:.1f} Å (change {b - a:+.1f} Å); the ligand stays in place.")]


def classify_burial(name: str, frac) -> list[dict]:
    f = np.asarray(frac, float)
    if len(f) < 3:
        return []
    m = float(f[len(f) // 2:].mean())
    if m >= 0.7:
        return [S("good", f"{name}：後半段平均 {m:.0%} 的表面被蛋白遮蔽（≥ 70 %），配體深埋於口袋。", f"{name}: {m:.0%} of the surface is shielded on average in the second half (≥ 70 %); the ligand is deeply buried.")]
    if m >= 0.4:
        return [S("note", f"{name}：平均遮蔽 {m:.0%}（40 % 到 70 %），部分埋藏、部分暴露在溶劑。", f"{name}: {m:.0%} shielded on average (40–70 %), partly buried and partly exposed.")]
    return [S("caution", f"{name}：平均只有 {m:.0%} 被遮蔽（< 40 %），配體大部分暴露在溶劑，屬於表面結合。", f"{name}: only {m:.0%} shielded on average (< 40 %); the ligand is mostly exposed, i.e. surface binding.")]


def classify_growth(name: str, y, what: tuple) -> list[dict]:
    y = np.asarray(y, float)
    if len(y) < 5:
        return []
    a, b = _halves(y)
    ch = (b - a) / a if a else 0.0
    if ch > 0.05:
        return [S("caution", f"{name}：{what[0]}由 {a:,.0f} 增加到 {b:,.0f}（{ch:+.1%}，> 5 %），蛋白可能部分展開。", f"{name}: {what[1]} grows from {a:,.0f} to {b:,.0f} ({ch:+.1%}, > 5 %); the protein may be partly unfolding.")]
    if ch < -0.10 and what[1].startswith("internal"):
        return [S("caution", f"{name}：{what[0]}由 {a:,.0f} 降到 {b:,.0f}（{ch:+.1%}），結構逐漸鬆散。", f"{name}: {what[1]} falls from {a:,.0f} to {b:,.0f} ({ch:+.1%}); the structure is loosening.")]
    return [S("good", f"{name}：{what[0]}維持穩定（{a:,.0f} 到 {b:,.0f}，{ch:+.1%}）。", f"{name}: {what[1]} stays stable ({a:,.0f} to {b:,.0f}, {ch:+.1%}).")]


def classify_dssp(name: str, frac: dict) -> list[dict]:
    out = []
    for c, zh, en in (("H", "螺旋", "helix"), ("E", "摺板", "strand")):
        y = np.asarray(frac.get(c) or [], float)
        if len(y) < 5 or y.max() < 0.02:
            continue
        a, b = _halves(y)
        if a - b > 0.05:
            out.append(S("caution", f"{name}：{zh}比例由 {a:.0%} 降到 {b:.0%}（下降超過 5 個百分點），有局部展開。", f"{name}: {en} content falls from {a:.0%} to {b:.0%} (more than 5 points); there is local unfolding."))
        else:
            out.append(S("good", f"{name}：{zh}比例維持在 {b:.0%}（開始 {a:.0%}），二級結構保持。", f"{name}: {en} content stays at {b:.0%} (start {a:.0%}); secondary structure is kept."))
    return out


def classify_pca(name: str, p: dict) -> list[dict]:
    if not p:
        return []
    ex = p.get("explained") or []
    basins = (p.get("landscape") or {}).get("basins") or []
    var = sum(ex[:2])
    lead = (f"{name}：前兩個主成分解釋 {var:.0%} 的運動", f"{name}: the first two components explain {var:.0%} of the motion")
    if len(basins) <= 1:
        return [S("good", lead[0] + "；地形只有一個主要低谷，蛋白停留在單一構形狀態。", lead[1] + "; the landscape has one main basin, so the protein stays in a single conformational state.")]
    pops = "、".join(f"{b[3]:.0%}" for b in basins if len(b) > 3)
    pops_en = ", ".join(f"{b[3]:.0%}" for b in basins if len(b) > 3)
    return [S("note", lead[0] + f"；地形有 {len(basins)} 個低谷（各約占 {pops} 的時間），蛋白在多個構形狀態之間轉換。",
              lead[1] + f"; the landscape has {len(basins)} basins (about {pops_en} of the time each), so the protein moves between several conformational states.")]


def classify_clusters(name: str, c: dict) -> list[dict]:
    pops = c.get("populations") or []
    if not pops:
        return []
    top = pops[0] if pops else 0
    if top >= 0.6:
        return [S("good", f"{name}：{c.get('n_clusters')} 個叢集中最大者占 {top:.0%}（≥ 60 %），有主導的結合構形。", f"{name}: the largest of {c.get('n_clusters')} clusters holds {top:.0%} (≥ 60 %); there is a dominant bound conformation.")]
    return [S("note", f"{name}：{c.get('n_clusters')} 個叢集，最大者只占 {top:.0%}，構形或結合模式在模擬中變動；請比較各叢集的代表結構。", f"{name}: {c.get('n_clusters')} clusters and the largest holds only {top:.0%}; the conformation or binding mode changes, so compare the representative structures.")]


def classify_dccm(name: str, C, ref=None) -> list[dict]:
    C = np.asarray(C, float)
    n = len(C)
    if n < 10:
        return []
    far = np.abs(np.subtract.outer(np.arange(n), np.arange(n))) > 5
    strong = float((np.abs(C[far]) > 0.6).mean())
    out = [S("note", f"{name}：遠離對角線（相隔 5 個殘基以上）的殘基對中 {strong:.1%} 有強相關（|r| > 0.6）。", f"{name}: {strong:.1%} of residue pairs more than 5 apart are strongly correlated (|r| > 0.6).")]
    if ref is not None and np.asarray(ref).shape == C.shape:
        R = np.asarray(ref, float)
        d = float(np.abs(C[far]).mean() - np.abs(R[far]).mean())
        if abs(d) >= 0.05:
            out.append(S("note", f"{name} 與蛋白單獨相比，長距離相關平均{'增強' if d > 0 else '減弱'} {abs(d):.2f}，配體改變了區域間的協同運動。",
                         f"Compared with the protein alone, long-range correlation in {name} is {abs(d):.2f} {'stronger' if d > 0 else 'weaker'} on average; the ligand changes the coupling between regions."))
    return out


def classify_fingerprint(name: str, occ: dict) -> list[dict]:
    rows = []
    for kind, zh, en in (("ionic", "離子", "ionic"), ("polar", "極性", "polar"), ("hydrophobic", "疏水", "hydrophobic")):
        for r, v in (occ.get(kind) or {}).items():
            if v >= 0.5:
                rows.append((r, v, zh, en))
    if not rows:
        return [S("note", f"{name}：沒有殘基與配體維持一半以上時間的作用，結合模式鬆散。", f"{name}: no residue interacts with the ligand for more than half of the time; the binding mode is loose.")]
    rows.sort(key=lambda x: -x[1])
    return [S("good", f"{name}：持續作用（≥ 50 %）的殘基：" + "、".join(f"{r}（{zh} {v:.0%}）" for r, v, zh, en in rows[:8]) + "。",
              f"{name}: persistent interactions (≥ 50 %): " + ", ".join(f"{r} ({en} {v:.0%})" for r, v, zh, en in rows[:8]) + ".")]


def classify_water(name: str, wb: dict) -> list[dict]:
    c = np.asarray(wb.get("count") or [], float)
    if len(c) < 3:
        return []
    m = float(c.mean())
    res = [r for r, v in (wb.get("residues") or []) if v >= 0.3]
    if m >= 1:
        return [S("note", f"{name}：平均 {m:.1f} 個水橋" + (f"，主要經由 {'、'.join(res[:5])}" if res else "") + "；水分子參與結合，取代這些水的設計可能提高親和力。",
                  f"{name}: {m:.1f} water bridges on average" + (f", mainly through {', '.join(res[:5])}" if res else "") + "; water takes part in binding, and designs that displace it may raise affinity.")]
    return [S("note", f"{name}：水橋很少（平均 {m:.1f}），配體與蛋白以直接接觸為主。", f"{name}: few water bridges ({m:.1f} on average); the ligand contacts the protein directly.")]


def classify_overlap(name: str, o: dict) -> list[dict]:
    if not o or "min_neighbour" not in o:
        return []
    mn = o["min_neighbour"]
    c = o.get("centers") or []
    i = int(np.argmin(o.get("neighbour") or [0]))
    where = f"{c[i]:.2f}–{c[i + 1]:.2f} nm" if len(c) > i + 1 else ""
    if mn >= 0.2:
        return [S("good", f"{name}：相鄰窗口的重疊最低 {mn:.2f}（≥ 0.2），整條路徑取樣連續。", f"{name}: the lowest neighbour overlap is {mn:.2f} (≥ 0.2); sampling is continuous along the path.")]
    if mn >= 0.05:
        return [S("note", f"{name}：最低重疊 {mn:.2f}（在 {where}），低於 0.2 但仍連通；該處誤差較大。", f"{name}: the lowest overlap is {mn:.2f} (at {where}), below 0.2 but still connected; the error is larger there.")]
    return [S("caution", f"{name}：{where} 的重疊只有 {mn:.2f}（< 0.05），剖面在此斷開，需要補窗口。", f"{name}: overlap at {where} is only {mn:.2f} (< 0.05); the profile is broken there and windows must be added.")]


def classify_convergence(name: str, conv: dict) -> list[dict]:
    vals = [(k, v.get("delta_pmf")) for k, v in sorted(conv.items()) if isinstance(v, dict) and v.get("delta_pmf") is not None]
    if len(vals) < 2:
        return []
    d = abs(vals[-1][1] - vals[-2][1])
    if d <= 2.0:
        return [S("good", f"{name}：取樣由 {float(vals[-2][0]):.0%} 增加到全部時井深只變化 {d:.1f} kJ mol⁻¹（≤ 2），自由能已收斂。", f"{name}: the depth changes by only {d:.1f} kJ mol⁻¹ from {float(vals[-2][0]):.0%} to all samples (≤ 2); the free energy has converged.")]
    return [S("caution", f"{name}：取樣由 {float(vals[-2][0]):.0%} 增加到全部時井深仍變化 {d:.1f} kJ mol⁻¹（> 2），尚未收斂，需要更長的窗口。", f"{name}: the depth still changes by {d:.1f} kJ mol⁻¹ from {float(vals[-2][0]):.0%} to all samples (> 2); not converged, longer windows are needed.")]


def classify_properties(props: list[dict]) -> list[dict]:
    if not props:
        return []
    from .chem import lipinski_violations
    v = [lipinski_violations(p) for p in props]
    ok = sum(1 for x in v if x == 0)
    return [S("note", f"{len(props)} 個化合物中 {ok} 個（{ok / len(props):.0%}）完全符合 Lipinski 規則，{sum(1 for x in v if x >= 2)} 個違反兩項以上。",
              f"Of {len(props)} compounds, {ok} ({ok / len(props):.0%}) meet all Lipinski rules and {sum(1 for x in v if x >= 2)} break two or more.")]


def classify_chem_space(xy, scores, names) -> list[dict]:
    xy, s = np.asarray(xy, float), np.asarray(scores, float)
    if len(s) < 6:
        return []
    k = max(3, len(s) // 5)
    top = np.argsort(s)[:k]
    d_all = float(np.mean(np.linalg.norm(xy[:, None] - xy[None], axis=-1)))
    d_top = float(np.mean(np.linalg.norm(xy[top][:, None] - xy[top][None], axis=-1)))
    if d_top < 0.6 * d_all:
        return [S("note", f"分數最好的 {k} 個化合物在化學空間中聚集（彼此距離為整體平均的 {d_top / d_all:.0%}），某一結構類型有利結合。", f"The {k} best-scoring compounds cluster in chemical space (mutual distance {d_top / d_all:.0%} of the average); one structural type favours binding.")]
    return [S("note", f"分數最好的 {k} 個化合物分散在化學空間中，多種骨架都可能結合。", f"The {k} best-scoring compounds are spread across chemical space; several scaffolds may bind.")]


def classify_interaction_2d(name: str, cons: list[dict]) -> list[dict]:
    hit = [c for c in cons if c.get("res")]
    if not hit:
        return []
    kinds = {}
    for c in hit:
        kinds.setdefault(c["kind"], set()).add(c["res"])
    zh = {"hbond": "氫鍵", "ionic": "離子", "hydrophobic": "疏水", "contact": "其他接觸"}
    return [S("note", f"{name}：{len(hit)} 個配體原子與蛋白接觸；" + "；".join(f"{zh[k]}：{'、'.join(sorted(v))}" for k, v in kinds.items()) + "。",
              f"{name}: {len(hit)} ligand atoms contact the protein; " + "; ".join(f"{k}: {', '.join(sorted(v))}" for k, v in kinds.items()) + ".")]
