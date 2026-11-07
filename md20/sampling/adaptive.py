"""Adaptive umbrella windows: coarse → fine gap filling until the CV is sampled continuously, without oversampling.

Why the old scheme left holes (and the Colab version too): new windows went to the midpoint between two window
*centres* with the same k.  On a steep stretch of the PMF a window does not sample around its centre — the
free-energy slope pushes its distribution downhill by ≈ slope/k — so the real hole lies between the neighbours'
*distributions*, not their centres, and a midpoint window with the same k slides to the same side and the hole
stays.  A fixed small number of rounds then stops with the break still there, and WHAM/MBAR join the pieces
with an arbitrary offset (a step in the PMF figure).

This planner works on what each window actually sampled:

1. Order windows by their sampled mean μ (not by centre) and measure the overlap of every neighbouring pair.
2. Big holes first: a hole is the stretch between μ_L + σ_L and μ_R − σ_R.  The number of windows needed to
   cover it is computed from the spacing that gives the target overlap, and they are placed evenly *in the
   hole* — one round closes a large gap instead of bisecting it over many rounds.
3. New windows are aimed, and stiffened only where needed: a biased window settles where F′(μ) + k(μ − c) = 0,
   so its centre is placed at c = t + F′/k (≤ 1σ per round) to sample around the intended t (F′ from the neighbours' drift); k is
   raised only to keep that drift within ~2σ (k ≥ slope²/4kT) and capped (`k_max`) — on a straight slope a
   drifted window still samples a full Gaussian; holes open where windows slide past a curvature change.
4. No oversampling: pairs at or above the target overlap get nothing; windows that are merely short of samples
   are *extended*, not duplicated; a window whose mean lands within 0.3 σ of a neighbour is reported as
   redundant (and the k there is raised next time instead of adding more of the same); every round and the
   total are budgeted.

Rounds repeat (coarse → fine: large holes, then the small residual ones) until every neighbouring pair reaches
the target overlap and every window has enough decorrelated samples, or the budget runs out — in which case
the result says exactly where the PMF is still discontinuous, and the binding step withholds ΔG°.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

import numpy as np

KB_KJ_MOL_K = 0.00831446261815324

# D-119: minimum spacing between window centres (fraction of the narrower σ; floor in nm) and the k ratio at which a
# window at nearly the same centre counts as a different distribution.  0.1σ blocks only clear duplicates (hole/break fills); endpoints use 0.3σ.
MIN_SEP_SIGMA = 0.1
MIN_SEP_SIGMA_ENDPOINT = 0.3      # an endpoint window beside an existing one adds no coverage: use the 'redundant' 0.3σ
MIN_SEP_FLOOR_NM = 2e-3
STIFFER_RATIO = 1.5


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def gaussian_overlap(mu1: float, s1: float, mu2: float, s2: float) -> float:
    """Overlap coefficient ∫min(p1, p2) of two normal densities (numerical, robust for unequal widths)."""
    lo, hi = min(mu1 - 6 * s1, mu2 - 6 * s2), max(mu1 + 6 * s1, mu2 + 6 * s2)
    x = np.linspace(lo, hi, 2001)
    p1 = np.exp(-0.5 * ((x - mu1) / s1) ** 2) / (s1 * math.sqrt(2 * math.pi))
    p2 = np.exp(-0.5 * ((x - mu2) / s2) ** 2) / (s2 * math.sqrt(2 * math.pi))
    return float(np.trapezoid(np.minimum(p1, p2), x) if hasattr(np, "trapezoid") else np.trapz(np.minimum(p1, p2), x))


def spacing_for_overlap(sigma: float, target_overlap: float) -> float:
    """Distance between two windows of width σ whose overlap coefficient equals the target: 2σ·Φ⁻¹(1 − OVL/2)."""
    from .windows import _norm_ppf
    return 2.0 * sigma * (-_norm_ppf(target_overlap / 2.0))


def empirical_overlap(a: np.ndarray, b: np.ndarray) -> float:
    from ._mdh_legacy import overlap_coefficient
    try:
        return overlap_coefficient(a, b)
    except Exception:  # noqa: BLE001  (too few samples)
        return 0.0


@dataclass
class WindowStat:
    center: float
    k: float
    mu: float
    sd: float
    n: int
    n_eff: float
    drift: float          # μ − centre
    slope: float          # |k·(centre − μ)|  kJ/mol/nm, local free-energy slope estimate


@dataclass
class RefinePlan:
    insert: list[dict] = field(default_factory=list)      # {"center", "k", "why", "hole": [lo, hi]}
    extend: list[dict] = field(default_factory=list)      # {"center", "why"}
    redundant: list[float] = field(default_factory=list)
    pairs: list[dict] = field(default_factory=list)       # neighbour diagnostics in μ order
    holes: list[dict] = field(default_factory=list)
    continuous: bool = False
    done: bool = False
    budget_exhausted: bool = False
    unsamplable: list = field(default_factory=list)        # breaks still open at k_max
    skipped: list[dict] = field(default_factory=list)      # D-119: proposals dropped as near-duplicates, each with its reason
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _stats(samples: dict[float, np.ndarray], ks: dict[float, float], discard_fraction: float) -> list[WindowStat]:
    from ._mdh_legacy import _fallback_statistical_inefficiency
    out = []
    for c, x in samples.items():
        x = np.asarray(x, float)
        x = x[int(len(x) * discard_fraction):] if len(x) > 20 else x
        mu, sd = float(np.mean(x)), float(np.std(x, ddof=1)) if len(x) > 1 else 0.0
        try:
            g = max(1.0, float(_fallback_statistical_inefficiency(x)))
        except Exception:  # noqa: BLE001
            g = 1.0
        k = float(ks[c])
        out.append(WindowStat(center=float(c), k=k, mu=mu, sd=max(sd, 1e-6), n=len(x), n_eff=len(x) / g,
                              drift=mu - float(c), slope=abs(k * (float(c) - mu))))
    return sorted(out, key=lambda w: w.mu)


def aim_by_response(ws: list, lo: float, hi: float, k: float, kT: float, target_overlap: float) -> dict | None:
    """Local linear inverse of the windows' response μ(c) at one k (D-101; spec §8 question 3): with ≥ 2 windows of
    that k around a hole, fit μ = μ₀ + g·(c − c₀) and place centres so the windows land IN the hole.  None when the
    windows barely respond (g < 0.15: they are stuck — a real barrier at this k) or there is too little to fit."""
    pts = [(w.center, w.mu) for w in ws if abs(w.k - k) < 1e-6]
    if len(pts) < 2:
        return None
    cs, mus = np.array([p[0] for p in pts]), np.array([p[1] for p in pts])
    if np.ptp(cs) < 1e-4:
        return None
    g = float(np.polyfit(cs, mus, 1)[0])
    if g < 0.15:
        return None
    lo, hi = min(lo, hi), max(lo, hi)
    step = spacing_for_overlap(math.sqrt(kT / k), target_overlap)
    n = max(1, int(math.ceil((hi - lo) / step)))
    out = []
    for i in range(n):
        t = lo + (hi - lo) * (i + 0.5) / n
        j = int(np.argmin(np.abs(mus - t)))
        out.append(float(cs[j] + (t - mus[j]) / g))
    return {"centers": out, "slope": g}


def plan_refinement(samples: dict[float, np.ndarray], ks: dict[float, float] | float, *, temperature_k: float = 300.0,
                    target_overlap: float = 0.2, min_effective_samples: float = 100.0, k_max: float = 5000.0,
                    max_new_per_round: int = 12, max_total_windows: int = 60, discard_fraction: float = 0.1,
                    cv_range: tuple[float, float] | None = None, extensions_done: dict[float, int] | None = None,
                    max_extensions: int = 2, recorder=None) -> RefinePlan:
    """One refinement round.  `samples`: {centre: CV samples (nm)}; `ks`: {centre: k} or one k (kJ/mol/nm²).
    `extensions_done`: {centre: times already extended}; after `max_extensions` a window with few effective samples
    is reported in `notes` (a wider error bar) instead of being extended for ever — otherwise correlated CVs kept
    every window in `extend` for all rounds and the refinement never reached `done` (cost ×6 for nothing)."""
    if not isinstance(ks, dict):
        ks = {c: float(ks) for c in samples}
    kT = KB_KJ_MOL_K * temperature_k
    plan = RefinePlan()
    st = _stats(samples, ks, discard_fraction)
    by_c = {w.center: w for w in st}
    ext_done = extensions_done or {}
    # --- windows that need more samples (extend, never duplicate; bounded)
    short = []
    for w in st:
        if w.n_eff < min_effective_samples:
            if ext_done.get(w.center, 0) < max_extensions:
                plan.extend.append({"center": w.center, "why": f"有效樣本 {w.n_eff:.0f} < {min_effective_samples:.0f}（相關時間長）；"
                                                               f"延長此 window（第 {ext_done.get(w.center, 0) + 1}/{max_extensions} 次），不另加 window。"})
            else:
                short.append(f"{w.center:.3f} nm（n_eff {w.n_eff:.0f}）")
    if short:
        plan.notes.append(f"{len(short)} 個 window 延長 {max_extensions} 次後有效樣本仍 < {min_effective_samples:.0f}：{', '.join(short[:6])}"
                          + ("…" if len(short) > 6 else "") + "；不再延長，誤差由 bootstrap 反映。")
    # --- neighbours in μ order
    proposals: list[dict] = []
    cont = continuity_report(samples, discard_fraction=discard_fraction)

    def _break_in(lo_: float, hi_: float) -> bool:
        return any(bl < max(lo_, hi_) and bh > min(lo_, hi_) for bl, bh in cont["breaks"])

    for a, b in zip(st[:-1], st[1:]):
        ovl = empirical_overlap(np.asarray(samples[a.center]), np.asarray(samples[b.center]))
        pair = {"left": a.center, "right": b.center, "mu": [round(a.mu, 4), round(b.mu, 4)], "overlap": round(ovl, 3)}
        plan.pairs.append(pair)
        if abs(b.mu - a.mu) < 0.3 * min(a.sd, b.sd):
            plan.redundant.append(b.center if b.n <= a.n else a.center)
        if ovl >= target_overlap:
            continue
        # the hole between the two *sampled* distributions
        lo, hi = a.mu + a.sd, b.mu - b.sd
        slope = max(a.slope, b.slope)
        # stiffen only as much as needed for the drift to stay within ~2σ (k ≥ slope²/4kT): on a straight slope a drifted
        # window still samples a full Gaussian; what opens holes is sliding past a change of curvature into a well
        k_new = max(min(a.k, b.k), slope ** 2 / (4.0 * kT))
        k_new = float(min(k_new, k_max))
        # D-101 futility: windows were already placed between these two means and slid out
        tried_in = [w for w in st if a.mu < w.center < b.mu and w.center not in (a.center, b.center)]
        if tried_in and not _break_in(lo, hi):
            pair["histogram_continuous"] = True
            plan.notes.append(f"{a.center:.3f}/{b.center:.3f} nm 成對重疊 {ovl:.2f} 偏低，但中間已有 window 且合併直方圖在此連續："
                              "取樣已連續（成對重疊被滑動的 window 拉低），不再加 window。")
            continue
        in_hole = [w for w in tried_in if min(lo, hi) - 1e-3 <= w.center <= max(lo, hi) + 1e-3]   # aimed at THIS hole
        if k_new >= k_max - 1e-6:
            aimed = aim_by_response(in_hole + [a, b], lo, hi, k_max, kT, target_overlap)
            if aimed is not None:
                why = (f"{lo:.3f}–{hi:.3f} nm：k 已在上限，改用已跑 window 的實際反應 μ(c)（dμ/dc ≈ {aimed['slope']:.2f}）反解中心，"
                       f"讓 window 落在洞裡（不再只偏移 1σ）。")
                for c in aimed["centers"]:
                    proposals.append({"center": round(float(c), 4), "k": round(k_max, 1), "why": why, "gap": (b.mu - a.mu) + 0.5})
                hole = {"between": [a.center, b.center], "mu": [round(a.mu, 4), round(b.mu, 4)], "overlap": round(ovl, 3),
                        "hole_nm": [round(lo, 4), round(hi, 4)], "n_new": len(aimed["centers"]), "k_new": round(k_max, 1),
                        "aimed_by_response": True}
                plan.holes.append(hole)
                continue
        if in_hole and k_new >= k_max - 1e-6 and all(w.k >= k_max - 1e-6 for w in in_hole) and len(in_hole) >= 3:
            plan.notes.append(f"{lo:.3f}–{hi:.3f} nm：已在 k 上限 {k_max:.0f} 放過 window 仍滑走（曲率比彈簧陡）；不再加 window。")
            plan.unsamplable.append([round(min(lo, hi), 4), round(max(lo, hi), 4)])
            continue
        sig_new = math.sqrt(kT / k_new)
        step = spacing_for_overlap(sig_new, target_overlap)
        span = b.mu - a.mu
        n = max(1, int(math.ceil(span / step)) - 1)               # windows strictly between the two means
        centres = [a.mu + span * (i + 1) / (n + 1) for i in range(n)]
        # a biased window settles where F'(μ) + k(μ − c) = 0, i.e. it drifts by −F'/k.  Neighbours give F' ≈ −k·drift;
        # to sample at t, put the centre at c = t + F'(t)/k_new (capped at σ_new so a bad slope estimate cannot throw it far)
        fprime = 0.5 * (-a.k * a.drift - b.k * b.drift)
        # ≤ 1σ per round: rounds iterate, and a larger aim from a two-window slope estimate overshoots (tested)
        shift = max(-sig_new, min(sig_new, fprime / k_new))
        centres = [c + shift for c in centres]
        hole = {"between": [a.center, b.center], "mu": [round(a.mu, 4), round(b.mu, 4)], "overlap": round(ovl, 3),
                "hole_nm": [round(lo, 4), round(hi, 4)], "n_new": n, "k_new": round(k_new, 1)}
        plan.holes.append(hole)
        why = (f"{a.center:.3f}/{b.center:.3f} nm 兩個 window 實際取樣（μ {a.mu:.3f}/{b.mu:.3f} nm）重疊只有 {ovl:.2f}"
               f"（目標 {target_overlap:.2f}）；在兩個分佈之間補 {n} 個"
               + (f"，此段斜率約 {slope:.0f} kJ/mol/nm，k 提高到 {k_new:.0f} 讓 window 留在原位" if k_new > min(a.k, b.k) * 1.01 else "")
               + "。")
        for c in centres:
            proposals.append({"center": round(float(c), 4), "k": round(k_new, 1), "why": why, "gap": span})
    # --- ends: does the sampled range cover the requested CV range?
    if cv_range is not None and st:
        first, last = st[0], st[-1]
        for edge, w, sign in ((cv_range[0], first, -1), (cv_range[1], last, +1)):
            if sign * (edge - (w.mu + sign * w.sd)) > 0.5 * w.sd:
                proposals.append({"center": round(float(edge), 4), "k": round(w.k, 1), "gap": abs(edge - w.mu), "kind": "endpoint",
                                  "why": f"CV 範圍端點 {edge:.3f} nm 沒被取樣（最近的 window 只到 {w.mu + sign * w.sd:.3f} nm）；補端點 window。"})
    # --- the pooled histogram is the ground truth: pairwise overlap can look fine while nothing sits on a barrier top
    #     (a window there with k < |F''| slides off to both sides and overlaps both neighbours)
    plan.notes.append(f"合併直方圖斷點：{cont['breaks'] or '無'}")
    centres_all = np.array([w.center for w in st])
    for lo, hi in cont["breaks"]:
        mid = 0.5 * (lo + hi)
        if any(lo - 1e-3 <= p["center"] <= hi + 1e-3 for p in proposals):
            continue
        if any(ul <= hi and uh >= lo for ul, uh in plan.unsamplable):
            continue
        near = [by_c[c] for c in centres_all[np.argsort(np.abs(centres_all - mid))[:2]]]
        k_near = max(w.k for w in near)
        tried = [w for w in st if lo - 1e-3 <= w.center <= hi + 1e-3]       # a window was put here and slid away
        if tried:
            k_near = max(k_near, max(w.k for w in tried))
            if k_near < k_max - 1e-6:
                k_near = k_max / 2.0                    # doubling below jumps straight to k_max: no slow escalation
        # D-101: "at k_max" only proves futility when a k_max window was actually placed IN the break (an SMD-informed
        # plan starts steep stretches at k_max, so neighbours at k_max alone prove nothing)
        tried_kmax = [w for w in tried if w.k >= k_max - 1e-6]
        if k_near >= k_max - 1e-6 and len(tried_kmax) >= 2:
            plan.notes.append(f"{lo:.3f}–{hi:.3f} nm 在 k 上限 {k_max:.0f} 仍取樣不到（能障曲率比彈簧陡）；"
                              "不再加 window。可提高 k_max，或接受此段 PMF 不連續（ΔG° 不輸出）。")
            plan.unsamplable.append([lo, hi])
            continue
        k_new = float(min(k_max, 2.0 * k_near))
        step = spacing_for_overlap(math.sqrt(kT / k_new), target_overlap)
        n = max(1, int(math.ceil((hi - lo) / step)))
        for i in range(n):
            c = lo + (hi - lo) * (i + 0.5) / n
            proposals.append({"center": round(float(c), 4), "k": round(k_new, 1), "gap": hi - lo + 1.0,   # breaks first
                              "why": f"{lo:.3f}–{hi:.3f} nm 合併樣本幾乎為零（PMF 會在此斷開）；附近 window 滑離此處，"
                                     f"補 window 並把 k 提高到 {k_new:.0f}（{k_near:.0f} 的兩倍）。"})
    # coarse → fine: largest holes first, then budget
    proposals.sort(key=lambda p: -p["gap"])
    room = max(0, max_total_windows - len(samples))
    take = min(max_new_per_round, room)
    # D-119 (REVIEW #18): a proposal is a near-duplicate when its centre is within MIN_SEP_SIGMA·σ of an existing or
    # already-taken centre and is not materially stiffer (k ≥ STIFFER_RATIO × that window's k).  Same-k windows that
    # close sample the same distribution; the old code stepped 2 pm aside up to 10 times, "added" a window that
    # sampled nothing new, and the same endpoint proposal came back every round until `rounds` ran out.  Near-
    # duplicates are dropped with a reason (plan.skipped + notes), never silently.  A materially stiffer window at
    # nearly the same centre IS a different distribution (the break logic raises k there on purpose): it keeps its
    # centre nudged to a free key (a key can hold one window).
    occupied: list[tuple[float, float]] = [(float(c), float(ks[c])) for c in samples]
    for p in proposals:
        if len(plan.insert) >= take:
            break
        c0, kp = float(p["center"]), float(p["k"])
        sig_p = math.sqrt(kT / kp)
        clash = None
        for (oc, ok) in occupied:
            frac = MIN_SEP_SIGMA_ENDPOINT if p.get("kind") == "endpoint" else MIN_SEP_SIGMA
            sep = max(MIN_SEP_FLOOR_NM, frac * min(sig_p, math.sqrt(kT / ok)))
            if abs(oc - c0) < sep and kp < STIFFER_RATIO * ok:
                clash = (oc, ok, sep)
                break
        if clash is not None:
            oc, ok, sep = clash
            reason = (f"提案 {c0:.3f} nm（k {kp:.0f}）與已有 window {oc:.3f} nm（k {ok:.0f}）距離 {abs(oc - c0):.4f} nm "
                      f"< 最小間距 {sep:.4f} nm（{frac}σ），且 k 沒有明顯更硬（< {STIFFER_RATIO}×）：兩者會取樣同一段分佈，"
                      "放棄此提案而不是挪 2 pm 假新增；該處若仍取樣不足，請提高 k 或手動補採樣。")
            plan.skipped.append({"center": c0, "k": kp, "near": oc, "near_k": ok, "min_sep_nm": round(sep, 5),
                                 "reason": reason})
            plan.notes.append(reason)
            continue
        c, moved = c0, 0
        while any(abs(oc - c) < 1e-3 for oc, _ in occupied):
            c, moved = round(c + 2e-3, 4), moved + 1
            if moved > 10:
                break
        if moved > 10:
            reason = f"{c0:.3f} nm 附近連續 10 個 key 都被占用，提案被放棄。"
            plan.skipped.append({"center": c0, "k": kp, "near": None, "near_k": None, "min_sep_nm": None, "reason": reason})
            plan.notes.append(reason)
            continue
        if moved:
            plan.notes.append(f"{c0:.3f} nm 的 window 比附近已有的硬（k {kp:.0f}），中心挪到空著的 key {c:.4f} nm。")
        p["center"] = c
        occupied.append((c, kp))
        plan.insert.append({k: v for k, v in p.items() if k not in ("gap", "kind")})
    n_unfilled = len(proposals) - len(plan.insert) - len(plan.skipped)
    if n_unfilled > 0:
        plan.budget_exhausted = True
        plan.notes.append(f"還有 {n_unfilled} 個缺口未補（每輪上限 {max_new_per_round}、總上限 {max_total_windows}）。")
    pair_ok = all(p["overlap"] >= target_overlap or p.get("histogram_continuous") for p in plan.pairs)
    plan.continuous = (pair_ok and cont["continuous"] and not plan.unsamplable
                       and not any("端點" in p["why"] for p in proposals))
    plan.done = plan.continuous and not plan.extend
    plan.redundant = sorted(set(plan.redundant))
    if plan.redundant:
        plan.notes.append(f"{len(plan.redundant)} 個 window 的取樣與鄰居幾乎重合（多餘）；該段之後以提高 k 取代加 window。")
    if recorder is not None:
        try:
            recorder(plan)
        except Exception:  # noqa: BLE001  (a side-record must never change or break planning)
            pass
    return plan


def continuity_report(samples: dict[float, np.ndarray], *, bins: int = 120, discard_fraction: float = 0.1,
                      min_fraction_of_median: float = 0.1) -> dict:
    """Histogram of all windows together over the sampled range: stretches with (almost) no samples are breaks
    in the PMF.  Independent of the planner's Gaussian model — the check the figure itself depends on."""
    xs = [np.asarray(x, float)[int(len(x) * discard_fraction):] for x in samples.values()]
    allx = np.concatenate(xs) if xs else np.array([])
    if allx.size < 10:
        return {"continuous": False, "breaks": [], "why": "樣本不足"}
    lo, hi = float(np.percentile(allx, 0.5)), float(np.percentile(allx, 99.5))
    h, e = np.histogram(allx, bins=bins, range=(lo, hi))
    # a stretch sampled < 10 % as densely as is typical has PMF error ≳ kT·ln(10) on top of noise: treat as a break
    thr = max(1.0, min_fraction_of_median * float(np.median(h)))
    low = h < thr
    breaks, i = [], 0
    while i < len(low):
        if low[i]:
            j = i
            while j + 1 < len(low) and low[j + 1]:
                j += 1
            breaks.append([round(float(e[i]), 4), round(float(e[j + 1]), 4)])
            i = j + 1
        else:
            i += 1
    return {"continuous": not breaks, "breaks": breaks, "range_nm": [round(lo, 4), round(hi, 4)],
            "bin_nm": round((hi - lo) / bins, 5)}


def plan_range(lo_nm: float, hi_nm: float, samples: dict[float, np.ndarray], ks: dict[float, float] | float, *,
               temperature_k: float = 300.0, target_overlap: float = 0.2, k: float | None = None,
               k_max: float = 5000.0, base_k: float = 1000.0) -> dict:
    """Manual "resample from a to b": windows that cover [lo, hi] at the target overlap.

    k: the user's choice, else — if the pooled histogram still has a break inside the range — twice the stiffest
    spring already used there (those windows slid away; same k would slide again), else the k already used
    there (or `base_k`).  Centres are spread evenly from lo to hi; keys never collide with existing windows."""
    lo, hi = sorted((float(lo_nm), float(hi_nm)))
    if hi - lo < 1e-4:
        raise ValueError("範圍太窄（需要 a < b，單位 nm）")
    if not isinstance(ks, dict):
        ks = {c: float(ks) for c in samples}
    kT = KB_KJ_MOL_K * temperature_k
    inside = [c for c in samples if lo - 0.05 <= c <= hi + 0.05]
    k_here = max((ks[c] for c in inside), default=base_k)
    breaks = [b for b in continuity_report(samples)["breaks"] if b[1] >= lo and b[0] <= hi] if len(samples) >= 2 else []
    # local free-energy slope from the windows around the range (F' ≈ −k·drift), as in plan_refinement
    st = _stats({c: samples[c] for c in samples}, ks, 0.1) if samples else []
    near = [w for w in st if lo - 0.15 <= w.center <= hi + 0.15]
    fprime = float(np.mean([-w.k * w.drift for w in near])) if near else 0.0
    slope = max((abs(w.k * w.drift) for w in near), default=0.0)
    if k is not None:
        k_new, how = float(k), "使用者指定"
    elif breaks:
        k_new, how = max(min(k_max, 2.0 * k_here), slope ** 2 / (4.0 * kT)), f"此段仍有斷點 {breaks}，原有 window 滑離 → 提高 k"
    else:
        k_new, how = max(k_here, slope ** 2 / (4.0 * kT)), "依此段斜率決定 k"
    k_new = float(min(max(k_new, 100.0), k_max))
    sig = math.sqrt(kT / k_new)
    # aim uphill so each window samples where it is placed; ≤ 3σ (one shot, unlike the iterating planner)
    shift = max(-3 * sig, min(3 * sig, fprime / k_new))
    step = spacing_for_overlap(sig, target_overlap)
    n = max(2, int(math.ceil((hi - lo) / step)) + 1)
    existing = np.array(sorted(samples)) if samples else np.zeros(0)
    out = []
    for i in range(n):
        c = round(lo + (hi - lo) * i / (n - 1) + shift, 4)
        while existing.size and np.min(np.abs(existing - c)) < 1e-3:
            c = round(c + 2e-3, 4)
        out.append({"center": c, "k": round(k_new, 1),
                    "why": f"使用者要求補採樣 {lo:.3f}–{hi:.3f} nm；{how}（k = {k_new:.0f}），間距 {step:.3f} nm（目標重疊 {target_overlap:.2f}）。"})
    return {"windows": out, "k": k_new, "spacing_nm": step, "breaks_in_range": breaks}


def coverage_view(samples: dict[float, np.ndarray], ks: dict[float, float] | float | None = None, *, bins: int = 120,
                  discard_fraction: float = 0.1) -> dict:
    """Data for the live coverage chart: per-window histograms + the pooled count per bin + breaks (red)."""
    xs = {c: np.asarray(x, float)[int(len(x) * discard_fraction):] for c, x in samples.items() if len(x)}
    if not xs:
        return {"edges": [], "pooled": [], "windows": [], "breaks": [], "continuous": False}
    allx = np.concatenate(list(xs.values()))
    lo, hi = float(allx.min()), float(allx.max())
    edges = np.linspace(lo, hi if hi > lo else lo + 1e-3, bins + 1)
    pooled, _ = np.histogram(allx, bins=edges)
    wins = []
    for c in sorted(xs):
        h, _ = np.histogram(xs[c], bins=edges)
        kk = (ks.get(c) if isinstance(ks, dict) else ks) if ks is not None else None
        wins.append({"center": round(float(c), 4), "k": kk, "n": int(len(xs[c])), "mean": round(float(xs[c].mean()), 4),
                     "counts": h.tolist()})
    cont = continuity_report(samples, discard_fraction=discard_fraction)
    return {"edges": [round(float(e), 4) for e in edges], "pooled": pooled.tolist(), "windows": wins,
            "breaks": cont["breaks"], "continuous": cont["continuous"]}


# ------------------------------------------------------------------------------------------------------------------
# D-101: plan the first windows from the SMD force curve (prevention), and say early where a gap is opening (alerts)
def smd_slope_profile(d_nm, force, lo: float, hi: float, *, bin_nm: float = 0.05) -> dict:
    """Mean SMD force per CV bin (kJ/mol/nm) — an estimate of the free-energy slope F′ along the path.

    The pulling force k_pull·(r0 − d) balances F′ plus friction (∝ pulling speed), so this OVER-estimates |F′| by the
    dissipative part; used only to decide where windows must be denser/stiffer, never as a free energy."""
    d, f = np.asarray(d_nm, float), np.asarray(force, float)
    edges = np.arange(lo, hi + bin_nm, bin_nm)
    mids, mean = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        m = (d >= a) & (d < b)
        if m.sum() >= 3:
            mids.append(0.5 * (a + b))
            mean.append(float(np.mean(f[m])))
    return {"x": np.array(mids), "slope": np.array(mean), "bin_nm": bin_nm}


def plan_from_smd(d_nm, force, lo: float, hi: float, *, k0: float, k_max: float, temperature_k: float,
                  target_overlap: float, max_windows: int) -> dict:
    """Initial windows that anticipate the slope instead of a uniform grid: in each stretch k ≥ F′²/(4kT) (drift ≲ 2σ,
    the refinement rule), spacing from the target overlap at the local σ, centre shifted uphill by F′/k (≤ 1σ) so the
    window samples around its intended place.  Falls back to a uniform plan when the SMD curve is too sparse.
    Returns {"centers", "k", "targets", "regions", "notes", "uniform": bool}."""
    kT = KB_KJ_MOL_K * temperature_k
    prof = smd_slope_profile(d_nm, force, lo, hi)
    notes = []
    if len(prof["x"]) < 3:
        notes.append("SMD 力曲線的點太少，沿用等距規劃。")
        return {"centers": [], "k": [], "targets": [], "regions": [], "notes": notes, "uniform": True}

    def slope_at(x: float) -> float:
        return float(np.interp(x, prof["x"], prof["slope"]))

    s0 = math.sqrt(kT / k0)

    def k_at(x: float) -> float:
        # a window slides DOWNHILL (towards the bound side, smaller CV): its k must hold it against the steepest slope
        # it could slide into — the stretch from 3σ₀ below to 1σ₀ above its place, not the slope at one point
        # (a window at the top of a wall sees a flat slope there and slides all the way down).
        xs = np.linspace(max(lo, x - 3 * s0), min(hi, x + s0), 13)
        s = max(abs(slope_at(v)) for v in xs)
        return float(min(k_max, max(k0, s * s / (4.0 * kT))))

    def build(scale: float) -> tuple[list, list, list]:
        t, out_t = lo, []
        while t <= hi + 1e-9:
            out_t.append(t)
            # the step must suit the stiffest stretch it crosses (else a flat start jumps over the start of a wall)
            step = scale * spacing_for_overlap(math.sqrt(kT / k_at(t)), target_overlap)
            for _ in range(8):
                kk = max(k_at(x) for x in np.linspace(t, min(hi, t + step), 9))
                new = scale * spacing_for_overlap(math.sqrt(kT / kk), target_overlap)
                if new >= step - 1e-9:
                    break
                step = new
            t += step
        if out_t[-1] < hi - 1e-6:
            out_t.append(hi)
        ks_ = [k_at(t) for t in out_t]
        cs = [t + float(np.clip(slope_at(t) / kk, -math.sqrt(kT / kk), math.sqrt(kT / kk))) for t, kk in zip(out_t, ks_)]
        return out_t, ks_, cs

    scale = 1.0
    targets, ks_, centers = build(scale)
    while len(targets) > max_windows and scale < 4.0:
        scale *= 1.15
        targets, ks_, centers = build(scale)
    if scale > 1.0:
        notes.append(f"依力曲線需要的 window 超過上限 {max_windows}，間距放寬為 ×{scale:.2f}（之後由補窗處理殘餘缺口）。")
    steep = [round(float(x), 3) for x, s in zip(prof["x"], prof["slope"]) if s * s / (4.0 * kT) > k0]
    regions = []
    if steep:
        a = b = steep[0]
        for x in steep[1:]:
            if x - b <= prof["bin_nm"] + 1e-9:
                b = x
            else:
                regions.append([a, b]); a = b = x
        regions.append([a, b])
        notes.append("力曲線陡的區段（預先加密、加硬）：" + "、".join(f"{p:.2f}–{q:.2f} nm" for p, q in regions) + "。")
    return {"centers": [round(c, 4) for c in centers], "k": [round(k, 1) for k in ks_], "targets": [round(t, 4) for t in targets],
            "regions": regions, "notes": notes, "uniform": False, "spacing_scale": round(scale, 3)}


def bimodality(x) -> float:
    """Sarle's bimodality coefficient (skew² + 1)/(kurtosis + 3(n−1)²/((n−2)(n−3))); > 0.555 suggests two modes."""
    x = np.asarray(x, float)
    n = len(x)
    if n < 20 or np.std(x) <= 0:
        return 0.0
    z = (x - x.mean()) / x.std()
    g, k = float(np.mean(z ** 3)), float(np.mean(z ** 4)) - 3.0
    return float((g * g + 1.0) / (k + 3.0 * (n - 1) ** 2 / ((n - 2) * (n - 3))))


def gap_alerts(samples: dict[float, np.ndarray], ks: dict[float, float], *, planned=None, temperature_k: float = 300.0,
               target_overlap: float = 0.2, k_max: float = 5000.0, discard_fraction: float = 0.1) -> list[dict]:
    """Early warning after every finished window: neighbouring FINISHED windows (in planned order — a window not yet
    run is pending, not a gap) whose sampled distributions overlap less than the target, each with a likely cause and
    what the automatic refinement will do.  Pure; written to coverage.json and the live progress line."""
    stats = {w.center: w for w in _stats(samples, ks, discard_fraction)}
    breaks = continuity_report(samples, discard_fraction=discard_fraction)["breaks"] if len(samples) >= 2 else []
    order = sorted(set(float(c) for c in (planned or [])) | set(stats))
    done = [c for c in order if c in stats]
    out = []
    for i in range(len(done) - 1):
        a, b = done[i], done[i + 1]
        if any(a < c < b and c not in stats for c in order):
            continue                                    # a planned window between them has not run yet
        L, R = sorted((stats[a], stats[b]), key=lambda w: w.mu)
        ov = empirical_overlap(np.asarray(samples[L.center])[int(len(samples[L.center]) * discard_fraction):],
                               np.asarray(samples[R.center])[int(len(samples[R.center]) * discard_fraction):])
        lo_, hi_ = sorted((L.mu + L.sd, R.mu - R.sd))
        in_break = any(bl < hi_ + 1e-9 and bh > lo_ - 1e-9 for bl, bh in breaks)
        # only what the user should see early: a real hole (pooled histogram break) or overlap under half the target;
        # a pair just under the target is routine refinement work, not news
        if ov >= target_overlap or (ov >= 0.5 * target_overlap and not in_break):
            continue
        cause, why = "spacing", "兩個 window 的取樣分佈離得太遠（間距大於目標重疊所需）"
        drifted = [w for w in (L, R) if abs(w.drift) > 2 * w.sd]
        bim = [w for w in (L, R) if bimodality(samples[w.center]) > 0.555]
        if bim:
            cause, why = "barrier", (f"window {bim[0].center:.3f} nm 內出現雙峰：兩峰之間是能障頂端，彈簧不夠硬（k {bim[0].k:.0f}）"
                                     "就會往兩邊滑")
        elif drifted:
            w = drifted[0]
            cause, why = "drift", (f"window {w.center:.3f} nm 被自由能斜坡推走 {w.drift:+.3f} nm（約 {abs(w.drift) / w.sd:.1f}σ，"
                                   f"斜率約 {w.slope:.0f} kJ/mol/nm）")
        if max(L.k, R.k) >= k_max - 1e-6 and cause in ("barrier", "drift"):
            cause += "_at_kmax"
            why += f"；k 已到上限 {k_max:.0f}，再加 window 也補不起來，需要提高 k_umbrella_max 或改用其他取樣法"
        lo, hi = L.mu + L.sd, R.mu - R.sd
        out.append({"lo": round(float(min(lo, hi)), 4), "hi": round(float(max(lo, hi)), 4), "overlap": round(float(ov), 3),
                    "windows": [round(L.center, 4), round(R.center, 4)], "cause": cause, "why": why,
                    "action": ("自動補窗會在這段放更硬、預先偏移的 window" if not cause.endswith("_at_kmax")
                               else "自動補窗無法處理；請在覆蓋圖上指定區間補採樣並提高 k，或回報老師")})
    return out
