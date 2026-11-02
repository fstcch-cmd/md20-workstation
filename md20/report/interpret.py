"""Data-driven interpretation for the workflow report (D-52).

Each function reads the numbers a step produced and returns findings: {"level": good|note|caution, "text": (zh, en)}.
Thresholds are stated in the text itself, so a reader can see why a sentence was written.  Pure Python + numpy.
"""
from __future__ import annotations

import numpy as np


def F(level: str, zh: str, en: str) -> dict:
    return {"level": level, "text": (zh, en)}


# ----------------------------------------------------------------------------------- structure
def structure(gates: list[dict]) -> list[dict]:
    out = []
    n = {s: sum(1 for g in gates if g.get("status") == s) for s in ("PASS", "AUTO_FIXED", "NEEDS_HUMAN")}
    if not gates:
        return [F("note", "沒有結構可信度紀錄。", "No structure-validity record is available.")]
    out.append(F("good" if not n["NEEDS_HUMAN"] else "caution",
                 f"結構檢查共 {len(gates)} 項：{n['PASS']} 項通過、{n['AUTO_FIXED']} 項已自動處理並記錄、{n['NEEDS_HUMAN']} 項需人工判斷。",
                 f"{len(gates)} structure checks: {n['PASS']} passed, {n['AUTO_FIXED']} handled automatically and recorded, "
                 f"{n['NEEDS_HUMAN']} needing a decision."))
    for g in gates:
        if g.get("name") == "resolution" and g.get("status") != "PASS":
            out.append(F("note", "解析度低於 2.5 Å 時側鏈與水分子的位置不確定度較高，口袋內的氫鍵判讀應保守。",
                         "Below 2.5 Å resolution, side-chain and water positions are uncertain; read pocket hydrogen bonds conservatively."))
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
        txt_zh = f"{name}：最佳分數 {best:.2f} kcal mol⁻¹，選用第 {rank} 名（{p['score']:.2f} kcal mol⁻¹），所屬叢集含 {p.get('cluster_size', 1)} 個姿勢（{frac:.0%}）。"
        txt_en = (f"{name}: best score {best:.2f} kcal mol⁻¹; pose {rank} was used ({p['score']:.2f} kcal mol⁻¹), whose "
                  f"cluster holds {p.get('cluster_size', 1)} poses ({frac:.0%}).")
        out.append(F("good" if frac >= 0.3 else "note", txt_zh, txt_en))
        if gap is not None and gap < 1.0:
            out.append(F("note", f"{name}：前兩名分數相差 {gap:.2f} kcal mol⁻¹，小於 Vina 約 1 到 2 kcal mol⁻¹ 的誤差，排名本身不能決定結合模式；"
                                 "叢集大小與後續模擬的穩定性更有參考價值。",
                         f"{name}: the top two poses differ by {gap:.2f} kcal mol⁻¹, below Vina's error of about 1–2 kcal mol⁻¹; "
                         "the ranking alone does not decide the binding mode, cluster size and simulation stability matter more."))
        if frac < 0.3:
            out.append(F("caution", f"{name}：選用姿勢的叢集很小，搜尋未收斂到一致的結合模式，建議提高搜尋強度或縮小搜尋區。",
                         f"{name}: the chosen pose belongs to a small cluster, so the search did not converge on one binding "
                         "mode; increase the exhaustiveness or narrow the search box."))
        r = p.get("rmsd_ref")
        if r is not None:
            if r <= 2.0:
                out.append(F("good", f"{name}：與共結晶姿勢的 RMSD 為 {r:.2f} Å（≤ 2 Å），重新對接成功，搜尋區與參數可信。",
                             f"{name}: RMSD to the co-crystal pose is {r:.2f} Å (≤ 2 Å); redocking succeeded, so the box and settings are credible."))
            else:
                out.append(F("caution", f"{name}：與共結晶姿勢的 RMSD 為 {r:.2f} Å（> 2 Å），重新對接未能重現晶體結構，其他配體的姿勢也需保守看待。",
                             f"{name}: RMSD to the co-crystal pose is {r:.2f} Å (> 2 Å); redocking did not reproduce the crystal, so "
                             "other poses from this setup should be treated with caution."))
        if name == "joint" and p.get("min_ll_distance") is not None:
            out.append(F("note", f"同時對接：配體間最短距離 {p['min_ll_distance']} Å；分數為所有配體的總和，不能與單一配體的分數直接比較。",
                         f"Simultaneous docking: shortest ligand–ligand distance {p['min_ll_distance']} Å; the score is the sum over "
                         "all ligands and cannot be compared directly with a single-ligand score."))
    return out


def screen(rows: list[dict], n_failed: int, selected: list[str]) -> list[dict]:
    if not rows:
        return []
    best = rows[0]
    near = [r for r in rows if r.get("indistinguishable_from_top")]
    out = [F("note", f"共 {len(rows)} 個化合物完成篩選（{n_failed} 個無法取得結構或對接失敗，見表）。最佳為 {best['name']}（{best['score']:.2f} kcal mol⁻¹）；"
                     f"{len(near)} 個化合物與最佳差距小於 1 kcal mol⁻¹，彼此的名次在誤差內。",
             f"{len(rows)} compounds were screened ({n_failed} could not be obtained or docked; see the table). The best is "
             f"{best['name']} ({best['score']:.2f} kcal mol⁻¹); {len(near)} compounds are within 1 kcal mol⁻¹ of it, so their order is within error.")]
    le = sorted([r for r in rows if r.get("ligand_efficiency")], key=lambda r: r["ligand_efficiency"])
    if le and le[0]["name"] != best["name"]:
        out.append(F("note", f"以每個重原子的分數（配體效率）來看，{le[0]['name']} 最佳；分數最負的化合物不一定最有效率，分子越大分數越容易變負。",
                     f"By score per heavy atom (ligand efficiency), {le[0]['name']} is best; the most negative score is not "
                     "necessarily the most efficient binder, since larger molecules score more negatively."))
    if selected:
        out.append(F("note", "使用者選入正式對接：" + "、".join(selected) + "。", "Selected for full docking by the user: " + ", ".join(selected) + "."))
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
            if pl:
                zh += f"，後半段 {pl['mean_last_half']:.2f} ± {pl['sd_last_half']:.2f} Å、漂移 {pl['drift_last_half']:+.2f} Å"
                en += f", second half {pl['mean_last_half']:.2f} ± {pl['sd_last_half']:.2f} Å with a drift of {pl['drift_last_half']:+.2f} Å"
            zh += "（< 2 Å 屬穩定，2 到 3 Å 為中度構形調整，> 3 Å 代表明顯重排）。"
            en += " (below 2 Å is stable, 2–3 Å a moderate adjustment, above 3 Å a clear rearrangement)."
            out.append(F(lvl, zh, en))
            if pl and abs(pl["drift_last_half"]) > 0.5:
                out.append(F("caution", f"{key}：後半段 RMSD 仍在變化（漂移 {pl['drift_last_half']:+.2f} Å），尚未達到平台，建議延長模擬。",
                             f"{key}: RMSD is still changing in the second half (drift {pl['drift_last_half']:+.2f} Å) and has not "
                             "reached a plateau; extend the simulation."))
        for rn, l in (s.get("ligands") or {}).items():
            r20 = l.get("rmsd_last20_A")
            if not l.get("stays_bound"):
                out.append(F("caution", f"{key} 的配體 {rn}：最後 20 % 時間的口袋內 RMSD 為 {r20:.1f} Å（≥ 3 Å），配體離開或明顯偏離原結合位；"
                                        "對接姿勢在動態下不穩定，不應以對接分數作為結合證據。",
                             f"Ligand {rn} in {key}: pocket RMSD over the last 20 % is {r20:.1f} Å (≥ 3 Å); the ligand left or "
                             "moved away from the docked site, so the docking score is not evidence of binding."))
            elif r20 is not None and r20 > 2.0:
                out.append(F("note", f"{key} 的配體 {rn}：留在口袋內，但最後 20 % 的 RMSD 為 {r20:.1f} Å，結合模式有調整。",
                             f"Ligand {rn} in {key}: stays in the pocket, but its RMSD over the last 20 % is {r20:.1f} Å, so the binding mode shifted."))
            else:
                out.append(F("good", f"{key} 的配體 {rn}：維持對接姿勢（最後 20 % 的 RMSD {r20:.1f} Å），結合模式在模擬時間內穩定。",
                             f"Ligand {rn} in {key}: keeps the docked pose (RMSD {r20:.1f} Å over the last 20 %); the binding mode is "
                             "stable over the simulated time."))
            tc = l.get("top_contacts") or []
            if tc:
                txt = "、".join(f"{a}（{b:.0%}）" for a, b in tc[:5])
                out.append(F("note", f"{key} 的配體 {rn} 最常接觸的殘基：{txt}。", f"Most frequent contacts of {rn} in {key}: "
                             + ", ".join(f"{a} ({b:.0%})" for a, b in tc[:5]) + "."))
    if apo.get("rmsd_backbone_mean_A") is not None:
        for key, s in summaries.items():
            if key == "apo" or s.get("rmsd_backbone_mean_A") is None:
                continue
            d = s["rmsd_backbone_mean_A"] - apo["rmsd_backbone_mean_A"]
            if abs(d) >= 0.3:
                out.append(F("note", f"{key} 與蛋白單獨相比主鏈 RMSD {'高' if d > 0 else '低'} {abs(d):.2f} Å："
                                     + ("配體結合使蛋白更穩定。" if d < 0 else "配體結合後蛋白的構形調整較大。"),
                             f"{key} versus the protein alone: backbone RMSD is {abs(d):.2f} Å {'higher' if d > 0 else 'lower'}; "
                             + ("binding stabilises the protein." if d < 0 else "the protein adjusts more with the ligand bound.")))
    if restrained:
        out.append(F("caution", "正式模擬保留了主鏈約束，RMSD 與 RMSF 被人為壓低，不能作為結構穩定的證據。",
                     "The backbone was restrained in production; RMSD and RMSF are artificially suppressed and are not evidence of stability."))
    return out


def rigidified(items: list[dict]) -> list[dict]:
    if not items:
        return []
    txt_zh = "、".join(f"{x['residue']}（{x['delta_rmsf_A']:+.2f} Å）" for x in items[:6])
    txt_en = ", ".join(f"{x['residue']} ({x['delta_rmsf_A']:+.2f} Å)" for x in items[:6])
    return [F("note", f"結合後柔性下降最多的殘基：{txt_zh}；這些殘基通常位於結合位或與其耦合的區域。",
              f"Residues whose flexibility drops most on binding: {txt_en}; they usually line the site or are coupled to it.")]


# ----------------------------------------------------------------------------------- binding
def binding(results: dict) -> list[dict]:
    out = []
    for name, r in (results or {}).items():
        d, e = r.get("delta_pmf_kj_mol"), r.get("delta_pmf_err_kj_mol")
        if d is None:
            continue
        kcal = d / 4.184
        txt_zh = f"{name}：自由能剖面的井深 ΔPMF = {d:.1f}" + (f" ± {e:.1f}" if e is not None else "") + f" kJ mol⁻¹（{kcal:.1f} kcal mol⁻¹）。"
        txt_en = f"{name}: depth of the free-energy profile ΔPMF = {d:.1f}" + (f" ± {e:.1f}" if e is not None else "") + f" kJ mol⁻¹ ({kcal:.1f} kcal mol⁻¹)."
        out.append(F("note", txt_zh, txt_en))
        if r.get("dG_standard_kj_mol") is not None:
            g = r["dG_standard_kj_mol"]
            out.append(F("good", f"{name}：標準結合自由能 ΔG° = {g:.1f} kJ mol⁻¹（{g / 4.184:.1f} kcal mol⁻¹），已含體積修正。",
                         f"{name}: standard binding free energy ΔG° = {g:.1f} kJ mol⁻¹ ({g / 4.184:.1f} kcal mol⁻¹), including the volume correction."))
        else:
            out.append(F("note", f"{name}：未輸出 ΔG°（原因見下方說明）；ΔPMF 只適合同一設定下的配體互相比較。",
                         f"{name}: ΔG° is not reported (see the reason below); ΔPMF is only suitable for comparing ligands run with the same settings."))
        hs = (r.get("half_split") or {}).get("diff_kj_mol")
        if hs is not None:
            out.append(F("good" if hs <= 2.0 else "caution",
                         f"{name}：前後半段的 ΔPMF 相差 {hs:.1f} kJ mol⁻¹" + ("，取樣已收斂。" if hs <= 2.0 else "（> 2 kJ mol⁻¹），取樣尚未收斂，需要更長的窗口。"),
                         f"{name}: first and second halves differ by {hs:.1f} kJ mol⁻¹" + (", so sampling has converged." if hs <= 2.0 else
                                                                                           " (> 2 kJ mol⁻¹); sampling has not converged and longer windows are needed.")))
        if d > 80:
            out.append(F("caution", f"{name}：井深超過 80 kJ mol⁻¹，對多數藥物大小的分子不合理，常見原因是窗口取樣不足或拉離路徑扭曲蛋白。",
                         f"{name}: a depth above 80 kJ mol⁻¹ is implausible for most drug-sized molecules; insufficient window sampling "
                         "or a pulling path that distorts the protein are the usual causes."))
    return out


def peptide(cpp: dict, access: dict) -> list[dict]:
    out = []
    for name, r in (cpp or {}).items():
        if r.get("limitation"):
            out.append(F("caution", f"{name}（穿膜性）：{r['limitation']}", f"{name} (cell penetration): {r['limitation']}"))
        elif r.get("status"):
            out.append(F("good", f"{name}（穿膜性）：{r.get('status')}。", f"{name} (cell penetration): {r.get('status')}."))
    for name, r in (access or {}).items():
        p = r.get("pose") or {}
        if p:
            bur, dist = p.get("burial_fraction"), p.get("site_min_distance_A")
            zh = f"{name}（活性位可及性）：選用姿勢的埋藏比例 {bur:.0%}" + (f"，距結合位最近 {dist:.1f} Å" if dist is not None else "") + "。"
            en = f"{name} (site access): burial of the chosen pose {bur:.0%}" + (f", closest approach to the site {dist:.1f} Å" if dist is not None else "") + "."
            out.append(F("good" if p.get("gate") == "PASS" else "caution", zh, en))
    return out


def headline(sections: list[list[dict]]) -> list[dict]:
    """Key findings: every caution first, then the first finding of each section."""
    flat = [f for s in sections for f in s]
    cautions = [f for f in flat if f["level"] == "caution"]
    firsts = [s[0] for s in sections if s and s[0]["level"] != "caution"]
    return (cautions + firsts)[:10]
