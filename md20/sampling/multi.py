"""WP9 — multi-ligand binding: per-ligand PMF in a shared pocket and ΔΔ comparison.

Pure numpy (testable without OpenMM):

* `pull_path_blockers` — before pulling ligand A out of a pocket that also holds ligand B, check that B is
  not sitting on A's exit path (anchor COM → ligand COM direction).  Pulling A *through* B gives a work and
  a PMF that measure B's displacement, not A's binding; the gate stops instead of guessing.
* `compare_binding` — rank ligands within one context ("single" = each ligand alone, "multi:<case>" = each
  ligand pulled from the shared complex) with propagated uncertainty, and the co-occupancy shift
  (ΔPMF_multi − ΔPMF_single) for ligands measured in both.

Honesty rules (also written into the result):
* ΔΔG° is reported only when *every* ligand in the context has an ΔG° the tier allowed; otherwise the
  comparison is ΔΔPMF and labelled qualitative.
* A difference smaller than 2σ (σ = √(σ_a²+σ_b²), bootstrap) is reported as "not distinguishable".
* Without an uncertainty for both members the order is given but never called significant.
"""
from __future__ import annotations

import math

import numpy as np

# D-74: texts read by the report as plain strings ("why", "verdict", "notes") stay in Chinese, as before; the same text in
# all four languages is kept next to them as (zh, en, ja, ko) tuples in "why_i18n", "verdict_i18n" and "notes_i18n".


def pull_path_blockers(anchor_com: np.ndarray, ligand_xyz: np.ndarray, others: dict[str, np.ndarray], *,
                       pull_distance_nm: float, clearance_nm: float = 0.35) -> list[dict]:
    """Other ligands with heavy atoms inside the exit cylinder of the pulled ligand.

    Cylinder axis: anchor COM → ligand COM, from the ligand COM to `pull_distance_nm` beyond it; radius =
    ligand radius + `clearance_nm`.  Coordinates in nm, already imaged consistently (same frame)."""
    lig_com = ligand_xyz.mean(0)
    axis = lig_com - np.asarray(anchor_com, dtype=float)
    n = np.linalg.norm(axis)
    if n < 1e-6:
        return [{"ligand": k, "reason": "anchor 與配體質心重合，拉離方向未定義"} for k in others]
    u = axis / n
    radius = float(np.max(np.linalg.norm(ligand_xyz - lig_com, axis=1))) + clearance_nm if len(ligand_xyz) > 1 else clearance_nm
    out = []
    for name, xyz in others.items():
        v = np.asarray(xyz, dtype=float) - lig_com
        t = v @ u
        perp = np.linalg.norm(v - np.outer(t, u), axis=1)
        inside = (t > 0) & (t < pull_distance_nm) & (perp < radius)
        if inside.any():
            out.append({"ligand": name, "n_atoms_in_path": int(inside.sum()),
                        "nearest_along_path_nm": round(float(t[inside].min()), 3), "path_radius_nm": round(radius, 3)})
    return out


def _sig(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return math.sqrt(a * a + b * b)


def compare_binding(results: dict, *, contexts: dict[str, list[str]]) -> dict:
    """`results[key]` is a workflow binding result; `contexts[ctx]` lists result keys measured in the same context.

    Larger ΔPMF / more negative ΔG° = stronger binding.  Returns per-context rankings and co-occupancy shifts."""
    out = {"contexts": {}, "co_occupancy": [], "notes": []}
    for ctx, keys in contexts.items():
        ok = [k for k in keys if (results.get(k) or {}).get("status") == "PASS" and results[k].get("delta_pmf_kj_mol") is not None]
        if len(ok) < 2:
            if keys:
                w = (f"{ctx}：只有 {len(ok)} 個配體有可用的 PMF，無法比較。",
                     f"{ctx}: only {len(ok)} ligand(s) have a usable PMF, so there is nothing to compare.",
                     f"{ctx}：使える PMF があるリガンドが {len(ok)} 個しかないため、比較できません。",
                     f"{ctx}: 사용할 수 있는 PMF가 있는 리간드가 {len(ok)}개뿐이라 비교할 수 없습니다.")
                out["contexts"][ctx] = {"status": "INSUFFICIENT", "keys": ok, "why": w[0], "why_i18n": w}
            continue
        use_dG = all(results[k].get("dG_standard_kj_mol") is not None for k in ok)
        if use_dG:
            val = {k: float(results[k]["dG_standard_kj_mol"]) for k in ok}       # lower = stronger
            err = {k: results[k].get("dG_err_kj_mol") for k in ok}
            ref = min(ok, key=lambda k: val[k])
            quantity, unit = "ΔΔG°", "kJ/mol"
            q4 = (quantity,) * 4
        else:
            val = {k: -float(results[k]["delta_pmf_kj_mol"]) for k in ok}       # −well depth: lower = stronger
            err = {k: results[k].get("delta_pmf_err_kj_mol") for k in ok}
            ref = min(ok, key=lambda k: val[k])
            quantity = "ΔΔPMF（定性）"
            unit = "kJ/mol"
            q4 = (quantity, "ΔΔPMF (qualitative)", "ΔΔPMF（定性的）", "ΔΔPMF(정성적)")
        rows = []
        for k in sorted(ok, key=lambda k: val[k]):
            dd = round(val[k] - val[ref], 3)
            s = _sig(err[k], err[ref]) if k != ref else None
            if k == ref:
                v4 = ("參考（最強）", "reference (strongest)", "基準（最も強い）", "기준(가장 강함)")
            elif s is None:
                v4 = ("缺誤差估計，只給順序，不判斷是否顯著", "no error estimate, order only, significance not judged",
                      "誤差の推定がないため、順位だけを示し有意性は判断しません", "오차 추정이 없어 순서만 제시하고 유의성은 판단하지 않음")
            elif abs(dd) < 2 * s:
                cmp = f"|Δ| {abs(dd):.1f} < 2σ {2 * s:.1f}"
                v4 = (f"與參考不可區分（{cmp}）", f"not distinguishable from the reference ({cmp})",
                      f"基準と区別できません（{cmp}）", f"기준과 구별되지 않음({cmp})")
            else:
                cmp = f"|Δ| {abs(dd):.1f} ≥ 2σ {2 * s:.1f}"
                v4 = (f"弱於參考（{cmp}）", f"weaker than the reference ({cmp})", f"基準より弱い（{cmp}）", f"기준보다 약함({cmp})")
            rows.append({"key": k, "value": round(val[k], 3), "err": err[k], "delta": dd,
                         "sigma": None if s is None else round(s, 3), "verdict": v4[0], "verdict_i18n": v4})
        reason = (("所有配體都有等級允許輸出的 ΔG°", "Every ligand has a ΔG° that its tier allows",
                   "すべてのリガンドにレベルで許された ΔG° があります", "모든 리간드에 등급이 허용한 ΔG°가 있습니다")
                  if use_dG else
                  ("至少一個配體沒有輸出 ΔG°，所以改用 ΔPMF 井深，只做定性排序",
                   "At least one ligand has no ΔG°, so ΔPMF well depths give a qualitative ranking only",
                   "ΔG° が出ていないリガンドが少なくとも1つあるため、ΔPMF の井戸の深さで定性的に順位づけするだけです",
                   "ΔG°가 없는 리간드가 하나 이상 있어 ΔPMF 우물 깊이로 정성적 순위만 매깁니다"))
        why = (f"{ctx}：以 {q4[0]} 比較。{reason[0]}。差距小於 2σ 視為不可區分。",
               f"{ctx}: compared by {q4[1]}. {reason[1]}. A difference below 2σ counts as not distinguishable.",
               f"{ctx}：{q4[2]} で比較します。{reason[2]}。差が 2σ 未満なら区別できないとみなします。",
               f"{ctx}: {q4[3]}로 비교합니다. {reason[3]}. 차이가 2σ보다 작으면 구별되지 않는 것으로 봅니다.")
        out["contexts"][ctx] = {"status": "PASS", "quantity": quantity, "unit": unit, "reference": ref, "rows": rows,
                                "why": why[0], "why_i18n": why}
    # co-occupancy: the same ligand pulled alone vs from the shared complex
    singles = {results[k].get("ligand", k): k for k in contexts.get("single", [])}
    for ctx, keys in contexts.items():
        if not ctx.startswith("multi"):
            continue
        for k in keys:
            r = results.get(k) or {}
            name = r.get("ligand")
            sk = singles.get(name)
            rs = results.get(sk) or {}
            if r.get("status") != "PASS" or rs.get("status") != "PASS" or r.get("delta_pmf_kj_mol") is None \
                    or rs.get("delta_pmf_kj_mol") is None:
                continue
            d = round(float(r["delta_pmf_kj_mol"]) - float(rs["delta_pmf_kj_mol"]), 3)
            s = _sig(r.get("delta_pmf_err_kj_mol"), rs.get("delta_pmf_err_kj_mol"))
            sig = s is not None and abs(d) >= 2 * s
            deep, x = d > 0, f"{abs(d):.1f}"
            if sig:
                tail = (f"，已達 2σ（{2 * s:.1f}），可能有協同或互斥效應",
                        f", which reaches 2σ ({2 * s:.1f}) and may mean cooperativity or competition",
                        f"、2σ（{2 * s:.1f}）以上なので協同または競合の可能性があります",
                        f"으며 2σ({2 * s:.1f}) 이상이라 협동 또는 경쟁 효과가 있을 수 있습니다")
            elif s is not None:
                tail = ("，在誤差範圍內，不判斷協同或互斥", ", within the error, so neither cooperativity nor competition is claimed",
                        "、誤差の範囲内なので協同とも競合とも判断しません", "지만 오차 범위 안이라 협동이나 경쟁을 판단하지 않습니다")
            else:
                tail = ("，沒有誤差估計，不做判斷", ", with no error estimate, so nothing is judged",
                        "、誤差の推定がないため判断しません", "지만 오차 추정이 없어 판단하지 않습니다")
            w = (f"{name} 從共同口袋拉離的 ΔPMF 比單獨結合時{'深' if deep else '淺'} {x} kJ/mol{tail[0]}。"
                 "這只是單一路徑，有沒有協同要看下方熱力學循環兩條路徑閉合後的平均。",
                 f"{name}: the ΔPMF pulled from the shared pocket is {'deeper' if deep else 'shallower'} than alone by {x} kJ/mol"
                 f"{tail[1]}. This is a single leg. Cooperativity is judged from the thermodynamic cycle below, averaged once "
                 "both legs close.",
                 f"{name} を共通ポケットから引き離したときの ΔPMF は、単独結合より {x} kJ/mol {'深く' if deep else '浅く'}"
                 f"{tail[2]}。これは片方の経路だけの値です。協同性は下の熱力学サイクルで、両経路が閉じた後の平均から判断します。",
                 f"공동 포켓에서 당긴 {name}의 ΔPMF는 단독 결합보다 {x} kJ/mol {'깊' if deep else '얕'}{tail[3]}. 이것은 "
                 "한쪽 경로의 값입니다. 협동 여부는 아래 열역학 순환에서 두 경로가 닫힌 뒤의 평균으로 판단합니다.")
            out["co_occupancy"].append({
                "ligand": name, "context": ctx, "shift_kj_mol": d, "sigma": None if s is None else round(s, 3),
                "significant": sig, "why": w[0], "why_i18n": w})
    notes = [("比較只在同一情境內有效，也就是同一個受體、同一套 protocol。單獨與共同口袋兩種情境不能直接互相排名。",
              "A comparison holds only within one context, meaning the same receptor and the same protocol. The single "
              "and shared-pocket contexts cannot be ranked against each other.",
              "比較は同じ条件の中でだけ有効です。つまり同じ受容体、同じ protocol です。単独と共通ポケットの結果を直接並べて"
              "順位づけすることはできません。",
              "비교는 같은 조건 안에서만 유효합니다. 즉 같은 수용체, 같은 protocol이어야 합니다. 단독과 공동 포켓 결과는 "
              "서로 직접 순위를 매길 수 없습니다."),
             ("誤差是 bootstrap 估計的 ΔPMF 或 ΔG° 標準差，不含 replica 之間的變異。research 等級需要至少 3 個 replica。",
              "The error is the bootstrap standard deviation of ΔPMF or ΔG° and does not include variation between "
              "replicas. The research tier needs at least 3 replicas.",
              "誤差は bootstrap で推定した ΔPMF または ΔG° の標準偏差で、replica 間のばらつきは含みません。research レベルでは"
              "少なくとも 3 個の replica が必要です。",
              "오차는 bootstrap으로 추정한 ΔPMF 또는 ΔG°의 표준편차이며 replica 간 변동은 포함하지 않습니다. research "
              "등급에는 replica가 최소 3개 필요합니다.")]
    out["notes"] = [x[0] for x in notes]
    out["notes_i18n"] = notes
    return out


def delta_pmf_error(grid: np.ndarray, err: np.ndarray | None, i_min: int, tail: int) -> float | None:
    """σ of the well depth: bootstrap SD at the minimum and averaged over the bulk tail (assumed independent)."""
    if err is None:
        return None
    e = np.asarray(err, dtype=float)
    if not len(e) or not np.all(np.isfinite(e[[i_min]])) or not np.isfinite(e[-tail:]).all():
        return None
    return round(math.sqrt(float(e[i_min]) ** 2 + float(np.mean(e[-tail:])) ** 2), 3)


def aggregate_binding_replicas(reps: list) -> dict:
    """Combine independent binding replicas (BindingResult-like objects).

    Mean over replicas; σ of the mean = max(SD/√n across replicas, √(Σσ_i²)/n from the bootstraps) — the larger
    of the two, because replica scatter captures path/sampling variance that a single bootstrap cannot.
    ΔG° only if every replica produced one (else withheld with the reason).  Half-split: the worst replica."""
    n = len(reps)
    dp = [r.delta_pmf_kj_mol for r in reps]
    per = [{"delta_pmf_kj_mol": r.delta_pmf_kj_mol, "delta_pmf_err_kj_mol": getattr(r, "delta_pmf_err_kj_mol", None),
            "dG_standard_kj_mol": r.dG_standard_kj_mol, "dG_err_kj_mol": getattr(r, "dG_err_kj_mol", None),
            "half_split": (r.pmf or {}).get("half_split")} for r in reps]

    def combine(vals, errs):
        v = np.asarray(vals, dtype=float)
        mean = float(v.mean())
        sem = float(v.std(ddof=1) / math.sqrt(n)) if n > 1 else None
        boot = math.sqrt(sum(e * e for e in errs)) / n if all(e is not None for e in errs) else None
        cands = [x for x in (sem, boot) if x is not None]
        return round(mean, 3), (round(max(cands), 3) if cands else None)

    out = {"n": n, "per_replica": per}
    if any(x is None for x in dp):
        out.update(delta_pmf=None, delta_pmf_err=None)
    else:
        out["delta_pmf"], out["delta_pmf_err"] = combine(dp, [p["delta_pmf_err_kj_mol"] for p in per])
    dgs = [r.dG_standard_kj_mol for r in reps]
    if all(x is not None for x in dgs):
        out["dG"], out["dG_err"] = combine(dgs, [p["dG_err_kj_mol"] for p in per])
        out["dG_kcal"], out["dG_withheld"] = round(out["dG"] / 4.184, 3), None
    else:
        out.update(dG=None, dG_err=None, dG_kcal=None,
                   dG_withheld=next(((r.pmf or {}).get("dG_withheld") for r in reps if (r.pmf or {}).get("dG_withheld")),
                                    "至少一個 replica 未輸出 ΔG°"))
    hs = [p["half_split"] for p in per if p["half_split"] and "diff_kj_mol" in p["half_split"]]
    out["half_split"] = max(hs, key=lambda h: h["diff_kj_mol"]) if hs else (per[0]["half_split"] if per else None)
    if n > 1 and out.get("delta_pmf") is not None:
        val = f"ΔPMF = {out['delta_pmf']} ± {out['delta_pmf_err']} kJ/mol"
        each = ", ".join(str(round(x, 1)) for x in dp)
        w = (f"{n} 個獨立 replica，MD 起點與亂數種子都不同。{val}。各 replica 的值為 {each}。"
             "σ 取 replica 標準誤與 bootstrap 合成誤差中較大的一個。",
             f"{n} independent replicas with different MD starting points and random seeds. {val}. Per replica: {each}. "
             "σ is the larger of the replica standard error and the combined bootstrap error.",
             f"独立した replica が {n} 個あり、MD の出発点と乱数シードはそれぞれ異なります。{val}。各 replica の値は {each} です。"
             "σ には replica の標準誤差と bootstrap の合成誤差のうち大きいほうを使います。",
             f"독립 replica {n}개로, MD 시작점과 난수 시드가 모두 다릅니다. {val}. 각 replica 값은 {each}입니다. "
             "σ는 replica 표준오차와 bootstrap 합성 오차 중 큰 값을 씁니다.")
    else:
        w = ("只有一個 replica，σ 只含 bootstrap 抽樣誤差。", "A single replica. σ contains only the bootstrap sampling error.",
             "replica は 1 個だけなので、σ には bootstrap のサンプリング誤差しか含まれません。",
             "replica가 하나뿐이라 σ에는 bootstrap 샘플링 오차만 들어 있습니다.")
    out["why"], out["why_i18n"] = w[0], w
    return out


# ------------------------------------------------------------------------------------------- D-61 cooperativity
CLOSURE_FALLBACK_KJ = 4.0      # without error bars, a cycle that misses by more than this is called not closed


def cooperativity(results: dict, contexts: dict[str, list[str]]) -> list[dict]:
    """Thermodynamic cycle for ligand pairs that were pulled both alone and from the shared complex.

        P + A + B  ──ΔG(A)──▶  PA  ──ΔG(B|A)──▶  PAB
             └──ΔG(B)──▶  PB  ──ΔG(A|B)──┘
    Path independence: ΔG(A|B) − ΔG(A) = ΔG(B|A) − ΔG(B) ≡ ΔΔG_coop (negative = positive cooperativity: each ligand binds
    more strongly when the other is present).  Both legs are measured independently, so their disagreement — the cycle
    closure error — is a direct test of convergence: it must be within 2σ (σ from the four bootstrap/replica errors;
    4 kJ/mol when errors are missing) before any cooperativity is claimed.

    Uses ΔG° when all four values have one (tier allowed it), otherwise −ΔPMF well depths (qualitative, labelled).
    Contexts with more than two ligands: each ligand's shift is "all others present", so a pairwise cycle does not
    exist; the per-ligand shifts are reported without a closure test."""
    singles = {results[k].get("ligand", k): k for k in contexts.get("single", []) if k in results}
    out = []
    for ctx, keys in contexts.items():
        if not ctx.startswith("multi"):
            continue
        legs = {}
        for k in keys:
            r, name = results.get(k) or {}, (results.get(k) or {}).get("ligand")
            rs = results.get(singles.get(name, ""), {})
            if r.get("status") == "PASS" and rs.get("status") == "PASS":
                legs[name] = (r, rs)
        names = sorted(legs)
        missing = sorted({(results.get(k) or {}).get("ligand", k.split(":", 1)[-1]) for k in keys} - set(names))
        if len(names) < 2:
            out.append({"context": ctx, "status": "INSUFFICIENT", "ligands": names, "missing": missing,
                        "why": (f"{ctx}：協同自由能需要每個配體都有「單獨」和「共同口袋」兩種拉離結果。缺少 {', '.join(missing) or '—'}。"
                                "請在 md.systems 同時放入 docked_single 與 docked_multi。",
                                f"{ctx}: cooperativity needs every ligand pulled both alone and from the shared pocket. Missing: "
                                f"{', '.join(missing) or '—'}. Include both docked_single and docked_multi in md.systems.",
                                f"{ctx}：協同自由エネルギーには、各リガンドについて「単独」と「共通ポケット」の両方の引き離し結果が"
                                f"必要です。不足：{', '.join(missing) or '—'}。md.systems に docked_single と docked_multi の両方を"
                                "入れてください。",
                                f"{ctx}: 협동 자유 에너지를 구하려면 모든 리간드에 대해 '단독'과 '공동 포켓' 두 가지 당김 결과가 "
                                f"필요합니다. 부족: {', '.join(missing) or '—'}. md.systems에 docked_single과 docked_multi를 모두 "
                                "넣으십시오.")})
            continue
        use_dG = all(r.get("dG_standard_kj_mol") is not None and rs.get("dG_standard_kj_mol") is not None for r, rs in legs.values())

        def leg(name):
            r, rs = legs[name]
            if use_dG:
                v = float(r["dG_standard_kj_mol"]) - float(rs["dG_standard_kj_mol"])
                e = _sig(r.get("dG_err_kj_mol"), rs.get("dG_err_kj_mol"))
            else:   # deeper well = stronger binding → ΔG-like quantity is −ΔPMF
                v = -(float(r["delta_pmf_kj_mol"]) - float(rs["delta_pmf_kj_mol"]))
                e = _sig(r.get("delta_pmf_err_kj_mol"), rs.get("delta_pmf_err_kj_mol"))
            return round(v, 3), (None if e is None else round(e, 3))

        shifts = {n: leg(n) for n in names}
        rec = {"context": ctx, "ligands": names, "quantity": "ΔΔG°" if use_dG else "−ΔΔPMF（定性）", "missing": missing,
               "shifts": {n: {"value": v, "err": e} for n, (v, e) in shifts.items()}}
        if len(names) != 2:
            nl = len(names)
            rec.update(status="PER_LIGAND", why=(f"{ctx}：{nl} 個配體。每個配體的位移是「其他配體都在」時的效果，沒有成對的熱力學循環，"
                                                 "所以不做閉合檢驗。",
                                                 f"{ctx}: {nl} ligands. Each shift is the effect of all the others being present, "
                                                 "so there is no pairwise cycle and no closure test.",
                                                 f"{ctx}：リガンドは {nl} 個です。各リガンドのずれは「ほかのリガンドがすべてある」ときの"
                                                 "効果なので、対になる熱力学サイクルがなく、閉合の検定は行いません。",
                                                 f"{ctx}: 리간드 {nl}개. 각 리간드의 변화는 '다른 리간드가 모두 있을 때'의 효과이므로 "
                                                 "짝을 이루는 열역학 순환이 없어 닫힘 검정을 하지 않습니다."))
            out.append(rec)
            continue
        (a, (va, ea)), (b, (vb, eb)) = shifts.items()
        closure = round(va - vb, 3)
        s_cl = _sig(ea, eb)
        coop = round((va + vb) / 2, 3)
        s_coop = None if s_cl is None else round(s_cl / 2, 3)
        rec.update(coop_kj_mol=coop, coop_err_kj_mol=s_coop, closure_kj_mol=closure, closure_sigma=s_cl)
        lim = 2 * s_cl if s_cl is not None else CLOSURE_FALLBACK_KJ
        x, lim_txt = f"{abs(closure):.1f}", f"{'2σ ' if s_cl is not None else ''}{lim:.1f}"
        if abs(closure) > lim:
            rec.update(status="NOT_CLOSED", why=(
                f"{a}+{b}：兩條路徑的協同估計相差 {x} kJ/mol，超過 {lim_txt}，循環沒有閉合。這表示採樣還沒收斂，"
                "或兩個起始構形差太多，所以不報告協同效應。請增加 replica 或延長每個窗口。",
                f"{a}+{b}: the two legs disagree by {x} kJ/mol, more than {lim_txt}, so the cycle does not close. Sampling "
                "has not converged or the starting structures differ too much, and no cooperativity is reported. Add "
                "replicas or lengthen the windows.",
                f"{a}+{b}：2つの経路の協同性の推定値が {x} kJ/mol 異なり、{lim_txt} を超えているため、サイクルが閉じていません。"
                "サンプリングが収束していないか、出発構造の違いが大きすぎます。協同効果は報告しません。replica を増やすか、"
                "各ウィンドウを長くしてください。",
                f"{a}+{b}: 두 경로의 협동 추정값이 {x} kJ/mol 차이 나 {lim_txt}를 넘으므로 순환이 닫히지 않습니다. 샘플링이 "
                "수렴하지 않았거나 시작 구조 차이가 너무 큽니다. 협동 효과는 보고하지 않습니다. replica를 늘리거나 각 윈도우를 "
                "늘리십시오."))
        elif s_coop is not None and abs(coop) < 2 * s_coop:
            cv = f"{coop:+.1f} ± {s_coop:.1f} kJ/mol"
            rec.update(status="NONE", why=(f"{a}+{b}：循環閉合，兩條路徑差 {x} kJ/mol。協同 {cv} 在 2σ 以內，沒有偵測到協同或互斥。",
                                           f"{a}+{b}: the cycle closes, with the legs {x} kJ/mol apart. Cooperativity of {cv} "
                                           "is within 2σ, so no cooperativity or competition is detected.",
                                           f"{a}+{b}：サイクルは閉じています（経路の差 {x} kJ/mol）。協同性 {cv} は 2σ 以内で、"
                                           "協同も競合も検出されません。",
                                           f"{a}+{b}: 순환이 닫힙니다(경로 차이 {x} kJ/mol). 협동 {cv}은 2σ 이내이므로 협동도 "
                                           "경쟁도 검출되지 않습니다."))
        elif s_coop is None:
            cv = f"{coop:+.1f} kJ/mol"
            rec.update(status="UNCERTAIN", why=(f"{a}+{b}：循環閉合，協同 {cv}，但沒有誤差估計，只給方向，不判斷是否顯著。",
                                                f"{a}+{b}: the cycle closes and cooperativity is {cv}. Without error estimates "
                                                "only the direction is given, not significance.",
                                                f"{a}+{b}：サイクルは閉じており、協同性は {cv} です。誤差の推定がないため、向きだけを示し、"
                                                "有意性は判断しません。",
                                                f"{a}+{b}: 순환이 닫히고 협동은 {cv}입니다. 오차 추정이 없어 방향만 제시하고 유의성은 "
                                                "판단하지 않습니다."))
        else:
            kind = ("正協同，兩者同時存在時各自結合更強", "positive cooperativity: each ligand binds more strongly with the other present",
                    "正の協同性で、両方があるとそれぞれがより強く結合します", "양의 협동으로, 함께 있을 때 각각 더 강하게 결합합니다") \
                if coop < 0 else ("負協同，也就是互斥，同時存在時各自結合較弱",
                                  "negative cooperativity (competition): each binds more weakly with the other present",
                                  "負の協同性（競合）で、両方があるとそれぞれの結合が弱くなります",
                                  "음의 협동(경쟁)으로, 함께 있을 때 각각 더 약하게 결합합니다")
            cv = f"ΔΔG_coop = {coop:+.1f} ± {s_coop:.1f} kJ/mol"
            rec.update(status="COOPERATIVE" if coop < 0 else "ANTICOOPERATIVE",
                       why=(f"{a}+{b}：循環閉合，兩條路徑差 {x} kJ/mol。{cv}，達到 2σ，屬於{kind[0]}。",
                            f"{a}+{b}: the cycle closes, with the legs {x} kJ/mol apart. {cv} (≥ 2σ). This is {kind[1]}.",
                            f"{a}+{b}：サイクルは閉じています（経路の差 {x} kJ/mol）。{cv} で 2σ 以上あり、{kind[2]}。",
                            f"{a}+{b}: 순환이 닫힙니다(경로 차이 {x} kJ/mol). {cv}로 2σ 이상이며, {kind[3]}."))
        if not use_dG:
            rec["why"] = tuple(w + q for w, q in zip(rec["why"], ("以 ΔPMF 井深計算，屬定性結果。",
                                                                  " This uses ΔPMF well depths and is qualitative.",
                                                                  "ΔPMF の井戸の深さから求めた定性的な結果です。",
                                                                  " ΔPMF 우물 깊이로 계산한 정성적 결과입니다.")))
        out.append(rec)
    return out
