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
                out["contexts"][ctx] = {"status": "INSUFFICIENT", "keys": ok,
                                        "why": f"{ctx}：只有 {len(ok)} 個配體有可用的 PMF，無法比較。"}
            continue
        use_dG = all(results[k].get("dG_standard_kj_mol") is not None for k in ok)
        if use_dG:
            val = {k: float(results[k]["dG_standard_kj_mol"]) for k in ok}       # lower = stronger
            err = {k: results[k].get("dG_err_kj_mol") for k in ok}
            ref = min(ok, key=lambda k: val[k])
            quantity, unit = "ΔΔG°", "kJ/mol"
        else:
            val = {k: -float(results[k]["delta_pmf_kj_mol"]) for k in ok}       # −well depth: lower = stronger
            err = {k: results[k].get("delta_pmf_err_kj_mol") for k in ok}
            ref = min(ok, key=lambda k: val[k])
            quantity, unit = "ΔΔPMF（定性）", "kJ/mol"
        rows = []
        for k in sorted(ok, key=lambda k: val[k]):
            dd = round(val[k] - val[ref], 3)
            s = _sig(err[k], err[ref]) if k != ref else None
            if k == ref:
                verdict = "參考（最強）"
            elif s is None:
                verdict = "缺誤差估計，只給順序、不判定顯著"
            elif abs(dd) < 2 * s:
                verdict = f"與參考不可區分（|Δ| {abs(dd):.1f} < 2σ {2 * s:.1f}）"
            else:
                verdict = f"弱於參考（|Δ| {abs(dd):.1f} ≥ 2σ {2 * s:.1f}）"
            rows.append({"key": k, "value": round(val[k], 3), "err": err[k], "delta": dd,
                         "sigma": None if s is None else round(s, 3), "verdict": verdict})
        why = (f"{ctx}：以 {quantity} 比較（{'所有配體皆有 tier 允許的 ΔG°' if use_dG else '至少一個配體不輸出 ΔG°，退回 ΔPMF 井深，只作定性排序'}）；"
               "差距 < 2σ 視為不可區分。")
        out["contexts"][ctx] = {"status": "PASS", "quantity": quantity, "unit": unit, "reference": ref, "rows": rows, "why": why}
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
            out["co_occupancy"].append({
                "ligand": name, "context": ctx, "shift_kj_mol": d, "sigma": None if s is None else round(s, 3),
                "significant": sig,
                "why": (f"{name} 從共同口袋拉離的 ΔPMF 比單獨結合 {'深' if d > 0 else '淺'} {abs(d):.1f} kJ/mol"
                        + (f"（≥ 2σ {2 * s:.1f}：可能有協同／互斥效應）" if sig else
                           "（在誤差內，不判定協同或互斥）" if s is not None else "（缺誤差，不判定）")
                        + "；注意兩者起始構形不同，這是趨勢不是熱力學循環。")})
    out["notes"] = ["比較只在同一情境內有效（同一受體、同一 protocol）；單獨與共同情境不可直接排名。",
                    "誤差為 bootstrap 估計的 ΔPMF/ΔG° 標準差，不含 replica 間變異；research 等級需 ≥3 replica。"]
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
        out["why"] = (f"{n} 個獨立 replica（不同 MD 起點與亂數種子）：ΔPMF = {out['delta_pmf']} ± {out['delta_pmf_err']} kJ/mol"
                      f"（各 replica：{', '.join(str(round(x, 1)) for x in dp)}）；σ 取 replica 標準誤與 bootstrap 合成中較大者。")
    else:
        out["why"] = "單一 replica；σ 只含 bootstrap 抽樣誤差。"
    return out
