"""D-122 (F17): what the automatic window refinement did for one binding calculation, what it cost, and what it changed.

Report and analysis only.  Nothing here changes a threshold or an action; the planner (`sampling/adaptive.py`) and the
binding loop keep their behaviour.  Everything comes from files the run already wrote:

  refine_log.json       one entry per planner pass: insert / extend / holes / unsamplable / notes / continuous
  coverage.json         final pooled-histogram continuity (breaks) and the window count
  binding_manifest.json the run's config (window_equil_ps, window_prod_ps, ...) and the stored PMF coverage
  smd.json              informed_plan (the first batch of windows)

Rules: a missing value is "not recorded" (None), never a guess.  Simulated time is derived only from recorded settings:
an inserted window costs window_equil_ps + window_prod_ps, an extension costs window_prod_ps (no re-equilibration);
NaN retries (same simulated time, run twice at most) are not counted.  The state "before" a round is the planner's own
view at the start of that pass; the state "after" it is the next pass's view, or, after the last action, the final
continuity stored with the result (only continuity and breaks, because the planner did not run again).

Pure: dicts in, dicts and strings out.
"""
from __future__ import annotations

import ast
from pathlib import Path

from ..i18n import pick
from ..util import load_json

NOTES_BREAKS_PREFIX = "合併直方圖斷點："
_SKIP_MARKERS = ("放棄此提案", "提案被放棄")          # the planner's own wording of a dropped proposal (D-119)
_BUDGET_MARKER = "個缺口未補"

OUTCOMES = ("continuous", "no_action_needed", "unsamplable", "open", "incomplete", "unknown", "no_record")
_WHY_NEEDLES = {"endpoint": "端點", "break": "合併樣本幾乎為零", "aimed": "實際反應", "overlap": "重疊只有"}   # the planner's own wording


# ---------------------------------------------------------------------------------------------------- reading files
def result_dir(r: dict | None) -> Path | None:
    """The binding output folder of a stored result, from the figure paths it recorded (None when there are none)."""
    figs = (r or {}).get("figures") or {}
    for k in ("pmf", "smd", "histograms", "umbrella_coverage"):
        png = (figs.get(k) or {}).get("png") if isinstance(figs.get(k), dict) else None
        if png:
            return Path(png).parent
    return None


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _breaks_from_notes(notes) -> list | None:
    """The pooled-histogram breaks the planner printed into its notes at that pass; None when it did not."""
    for n in notes or []:
        if isinstance(n, str) and n.startswith(NOTES_BREAKS_PREFIX):
            rest = n[len(NOTES_BREAKS_PREFIX):].strip()
            if rest == "無":
                return []
            try:
                return [[float(a), float(b)] for a, b in ast.literal_eval(rest)]
            except (ValueError, SyntaxError, TypeError):
                return None
    return None


def _state(e: dict) -> dict:
    """The planner's view at the start of one pass."""
    holes = [h for h in (e.get("holes") or []) if isinstance(h, dict)]
    ov = [v for v in (_num(h.get("overlap")) for h in holes) if v is not None]
    cont = e.get("continuous")
    brk = _breaks_from_notes(e.get("notes"))
    return {"continuous": cont if isinstance(cont, bool) else None, "n_holes": len(holes),
            "min_overlap": min(ov) if ov else None, "n_breaks": None if brk is None else len(brk), "breaks": brk,
            "unsamplable": [list(u) for u in (e.get("unsamplable") or [])], "source": "pass"}


def _skipped(e: dict) -> list[dict]:
    """Proposals dropped as near-duplicates (D-119).  Structured when the entry carries `skipped`; otherwise the
    planner's notes that say so (raw Chinese text, marked)."""
    sk = e.get("skipped")
    if isinstance(sk, list) and sk:
        return [{"center": _num(s.get("center")), "k": _num(s.get("k")), "near": _num(s.get("near")),
                 "near_k": _num(s.get("near_k")), "min_sep_nm": _num(s.get("min_sep_nm")), "reason": s.get("reason", ""),
                 "source": "skipped"} for s in sk if isinstance(s, dict)]
    return [{"center": None, "k": None, "near": None, "near_k": None, "min_sep_nm": None, "reason": n, "source": "notes"}
            for n in (e.get("notes") or []) if isinstance(n, str) and any(m in n for m in _SKIP_MARKERS)]


def _why_code(why: str) -> str:
    for code, needle in _WHY_NEEDLES.items():
        if needle in (why or ""):
            return code
    return "other"


def _centers(items) -> list[float]:
    out = []
    for x in items or []:
        v = _num(x.get("center") if isinstance(x, dict) else x)
        if v is not None:
            out.append(v)
    return out


# ---------------------------------------------------------------------------------------------------- the summary
def summarize(bdir) -> dict:
    """Read the binding folder's files and summarise (see `summarize_data`).  No folder: "no_record"."""
    if not bdir:
        return summarize_data(None)
    d = Path(bdir)
    return summarize_data(load_json(d / "refine_log.json", None), load_json(d / "coverage.json", None),
                          load_json(d / "binding_manifest.json", None), load_json(d / "smd.json", None))


def summarize_data(refine_log, coverage=None, manifest=None, smd=None) -> dict:
    cfg = (manifest or {}).get("config") or {}
    eq, prod = _num(cfg.get("window_equil_ps")), _num(cfg.get("window_prod_ps"))
    out = {"outcome": "no_record", "rounds": [], "initial": None, "final": None, "totals": {},
           "settings": {"window_equil_ps": eq, "window_prod_ps": prod, "target_overlap": _num(cfg.get("target_overlap")),
                        "k_umbrella_max": _num(cfg.get("k_umbrella_max")),
                        "max_refine_rounds": _num(cfg.get("max_refine_rounds"))},
           "budget_limited": False}
    passes = [e for e in (refine_log if isinstance(refine_log, list) else []) if isinstance(e, dict)]
    if not passes:
        return out
    # --- final continuity: what the PMF stage stored, else the coverage file; both are the pooled histogram's verdict
    pm_cov = (((manifest or {}).get("result") or {}).get("pmf") or {}).get("coverage") or {}
    cov = coverage if isinstance(coverage, dict) else {}
    final = None
    for src, c in (("pmf", pm_cov), ("coverage", cov)):
        if isinstance(c.get("continuous"), bool):
            brk = c.get("breaks")
            final = {"continuous": c["continuous"], "breaks": [list(b) for b in brk] if isinstance(brk, list) else None,
                     "n_breaks": len(brk) if isinstance(brk, list) else None, "n_holes": None, "min_overlap": None,
                     "unsamplable": [list(u) for u in (c.get("unsamplable") or [])],
                     "n_windows": c.get("n_windows") or (len(cov.get("windows") or []) or None), "source": src}
            break
    last = passes[-1]
    last_acted = bool(last.get("insert") or last.get("extend"))
    if final is None and not last_acted:           # the terminal pass is itself the final state
        final = {**_state(last), "n_windows": None, "source": "last_pass"}
    if final is not None and not final.get("unsamplable"):
        final["unsamplable"] = [list(u) for u in (last.get("unsamplable") or [])]
    out["final"] = final
    # --- first batch
    informed = (smd or {}).get("informed_plan") if isinstance(smd, dict) else None
    n0, how = None, None
    if isinstance(informed, dict) and not informed.get("uniform") and informed.get("centers"):
        n0, how = len(informed["centers"]), "informed"
    elif isinstance(smd, dict) and isinstance((smd.get("plan") or {}).get("centers_nm"), list):
        n0, how = len(smd["plan"]["centers_nm"]), "uniform"
    if n0:
        out["initial"] = {"n_windows": n0, "plan": how,
                          "cost_ps": n0 * (eq + prod) if eq is not None and prod is not None else None}
    # --- one row per pass that acted
    rounds, budget = [], False
    for i, e in enumerate(passes):
        ins = [x for x in (e.get("insert") or []) if isinstance(x, dict)]
        ext = _centers(e.get("extend"))
        sk = _skipped(e)
        budget = budget or any(isinstance(n, str) and _BUDGET_MARKER in n for n in (e.get("notes") or []))
        if not (ins or ext or sk):
            continue
        ins_cost = 0.0 if not ins else (len(ins) * (eq + prod) if eq is not None and prod is not None else None)
        ext_cost = 0.0 if not ext else (len(ext) * prod if prod is not None else None)
        cost = None if ins_cost is None or ext_cost is None else ins_cost + ext_cost
        if i + 1 < len(passes):
            after = _state(passes[i + 1])
        else:
            after = final if (final is not None and (ins or ext)) else (_state(e) if not (ins or ext) else None)
        ks = sorted({round(float(x["k"]), 1) for x in ins if _num(x.get("k")) is not None})
        codes: dict[str, int] = {}
        for x in ins:
            c_ = _why_code(x.get("why", ""))
            codes[c_] = codes.get(c_, 0) + 1
        rounds.append({"round": e.get("round", i + 1), "completed": bool(e.get("completed")),
                       "inserted": [{"center": _num(x.get("center")), "k": _num(x.get("k")), "why": x.get("why", ""),
                                     "code": _why_code(x.get("why", ""))} for x in ins],
                       "extended": ext, "skipped": sk, "k_values": ks, "reason_counts": codes,
                       "cost_ps": cost, "cost_known": cost is not None,
                       "before": _state(e), "after": after, "unsamplable": [list(u) for u in (e.get("unsamplable") or [])]})
    out["rounds"] = rounds
    out["budget_limited"] = budget
    acting = [r for r in rounds if r["inserted"] or r["extended"]]
    costs = [r["cost_ps"] for r in acting]
    out["totals"] = {"rounds": len(acting), "inserted": sum(len(r["inserted"]) for r in acting),
                     "extended": sum(len(r["extended"]) for r in acting), "skipped": sum(len(r["skipped"]) for r in rounds),
                     "cost_ps": None if any(c is None for c in costs) else float(sum(costs)),
                     "cost_known": all(c is not None for c in costs)}
    # --- how it ended
    fc = final["continuous"] if final else None
    uns = (final or {}).get("unsamplable") or []
    if any(not r["completed"] for r in acting):
        out["outcome"] = "incomplete"
    elif fc is True:
        out["outcome"] = "continuous" if acting else "no_action_needed"
    elif fc is False:
        out["outcome"] = "unsamplable" if uns else "open"
    else:
        out["outcome"] = "unknown"
    return out


# ---------------------------------------------------------------------------------------------------- evidence row
def evidence_status(s: dict) -> tuple[str, list[str], bool]:
    """(status, reason codes for evidence.R, done) of the "automatic actions" row.  Never "supported" without a record."""
    o = s.get("outcome")
    if o in ("continuous", "no_action_needed"):
        return "supported", [], True
    if o == "unsamplable":
        return "limited", ["auto_unsamplable"], True
    if o == "open":
        return "limited", ["auto_open"], True
    if o == "incomplete":
        return "limited", ["auto_incomplete"], False
    return "limited", ["not_recorded"], False


# ---------------------------------------------------------------------------------------------------- report text
HEAD = {
    "title": ("自動補窗的效益與資源", "What the automatic refinement did and cost", "自動補窓の効果と資源", "자동 보충 윈도우의 효과와 자원"),
    "round": ("輪次", "Round", "ラウンド", "회차"),
    "action": ("動作", "Action", "動作", "동작"),
    "cost": ("多花的模擬時間（ps）", "Extra simulated time (ps)", "追加のシミュレーション時間（ps）", "추가 시뮬레이션 시간(ps)"),
    "effect": ("效果（前後）", "Effect (before and after)", "効果（前後）", "효과(전후)"),
    "caption": ("自動補窗每一輪的動作、成本與效果", "Automatic window refinement: action, cost and effect of each round",
                "自動補窓の各ラウンドの動作・コスト・効果", "자동 윈도우 보충의 회차별 동작, 비용, 효과"),
    "first": ("第一批", "First batch", "最初のバッチ", "첫 배치"),
    "skipped_title": ("放棄的提案", "Proposals dropped", "見送った提案", "포기한 제안"),
    "unknown": ("無紀錄", "not recorded", "記録なし", "기록 없음"),
    "no_gap": ("無缺口", "no gap", "ギャップなし", "간격 없음"),
    "yes": ("是", "yes", "はい", "예"),
    "no": ("否", "no", "いいえ", "아니오"),
    "incomplete_tag": ("（計畫值，這一輪尚未完成）", " (planned; this round is not finished)", "（計画値、このラウンドは未完了）",
                       "(계획값, 이 회차는 아직 끝나지 않음)"),
    "note": ("成本只計入已記錄的設定（每個新窗口 平衡時間＋取樣時間，每次延長 取樣時間）；NaN 重試與等待時間不計。重疊最小值是規劃器在缺口處記下的值。",
             "Cost uses recorded settings only (equilibration plus production for a new window, production for an extension). NaN retries and waiting time are not counted. "
             "The minimum overlap is the value the planner recorded at the gaps.",
             "コストは記録された設定だけから計算します（新しいウィンドウは平衡化時間と本計算時間、延長は本計算時間）。NaN の再試行と待ち時間は含みません。"
             "重なりの最小値は、プランナーがギャップで記録した値です。",
             "비용은 기록된 설정만으로 계산합니다(새 윈도우는 평형 시간과 본 계산 시간, 연장은 본 계산 시간). NaN 재시도와 대기 시간은 포함하지 않습니다. "
             "겹침의 최솟값은 플래너가 간격에서 기록한 값입니다."),
}
ACT = {
    "insert": ("插入 {n} 個窗口：{cs} nm", "Inserted {n} windows at {cs} nm", "ウィンドウを {n} 個挿入：{cs} nm", "윈도우 {n}개 삽입: {cs} nm"),
    "k": ("k 為 {ks} kJ mol⁻¹ nm⁻²", "k = {ks} kJ mol⁻¹ nm⁻²", "k は {ks} kJ mol⁻¹ nm⁻²", "k는 {ks} kJ mol⁻¹ nm⁻²"),
    "extend": ("延長 {n} 個窗口（有效樣本不足）：{cs} nm", "Extended {n} windows (too few effective samples) at {cs} nm",
               "ウィンドウを {n} 個延長（有効サンプル不足）：{cs} nm", "윈도우 {n}개 연장(유효 샘플 부족): {cs} nm"),
    "skip": ("放棄 {n} 個重複提案", "Dropped {n} duplicate proposals", "重複する提案を {n} 件見送り", "중복 제안 {n}개 포기"),
    "none": ("沒有新增或延長", "Nothing inserted or extended", "追加も延長もなし", "추가나 연장 없음"),
    "why": ("原因：{w}", "Reason: {w}", "理由：{w}", "이유: {w}"),
}
WHY = {
    "overlap": ("相鄰窗口重疊不足", "neighbouring windows overlap too little", "隣のウィンドウの重なりが不足", "이웃 윈도우의 겹침 부족"),
    "break": ("合併直方圖有斷點", "the pooled histogram has a break", "統合ヒストグラムに途切れがある", "통합 히스토그램에 끊김이 있음"),
    "endpoint": ("CV 範圍端點沒有取樣", "an end of the CV range is not sampled", "CV 範囲の端がサンプリングされていない", "CV 범위의 끝이 샘플링되지 않음"),
    "aimed": ("k 已在上限，依已跑窗口的反應重新定位", "k is at its limit, aimed from the windows' measured response",
              "k が上限のため、実行済みウィンドウの応答から位置を再設定", "k가 상한이라 실행된 윈도우의 반응으로 위치를 다시 정함"),
    "other": ("其他（見紀錄原文）", "other (see the logged text)", "その他（記録の原文を参照）", "기타(기록 원문 참조)"),
}
EFF = {
    "overlap": ("重疊最小值 {a} → {b}", "Minimum overlap {a} → {b}", "重なりの最小値 {a} → {b}", "겹침 최솟값 {a} → {b}"),
    "breaks": ("斷點 {a} → {b}", "Breaks {a} → {b}", "途切れ {a} → {b}", "끊김 {a} → {b}"),
    "cont": ("連續 {a} → {b}", "Continuous {a} → {b}", "連続 {a} → {b}", "연속 {a} → {b}"),
}
SKIP = {
    "pair": ("第 {r} 輪：提案 {c} nm（k {k}）與已有窗口 {n} nm（k {nk}）只差 {d} nm，小於最小間距 {s} nm，放棄。",
             "Round {r}: the proposal at {c} nm (k {k}) is {d} nm from the existing window at {n} nm (k {nk}), below the minimum spacing {s} nm, so it was dropped.",
             "第 {r} ラウンド：{c} nm（k {k}）の提案は既存のウィンドウ {n} nm（k {nk}）と {d} nm しか離れておらず、最小間隔 {s} nm より近いため見送りました。",
             "{r}회차: {c} nm(k {k}) 제안은 기존 윈도우 {n} nm(k {nk})와 {d} nm밖에 떨어져 있지 않아 최소 간격 {s} nm보다 가까우므로 포기했습니다."),
    "raw": ("第 {r} 輪（紀錄原文）：{t}", "Round {r} (logged text, in Chinese): {t}", "第 {r} ラウンド（記録の原文、中国語）：{t}",
            "{r}회차(기록 원문, 중국어): {t}"),
}
SUM = {
    "work": ("補窗 {n} 輪，新增 {a} 個窗口，延長 {e} 次，多花 {ps} ps。",
             "Refinement took {n} rounds, added {a} windows and extended {e}, costing {ps} ps of extra simulation.",
             "補窓は {n} ラウンドで、ウィンドウを {a} 個追加し、{e} 回延長し、追加で {ps} ps のシミュレーションを使いました。",
             "{n}회 보충으로 윈도우 {a}개를 추가하고 {e}회 연장했으며, 추가 시뮬레이션은 {ps} ps입니다."),
    "work_nocost": ("補窗 {n} 輪，新增 {a} 個窗口，延長 {e} 次。多花的模擬時間無法推算，因為設定沒有紀錄。",
                    "Refinement took {n} rounds, added {a} windows and extended {e}. The extra simulated time cannot be derived because the settings were not recorded.",
                    "補窓は {n} ラウンドで、ウィンドウを {a} 個追加し、{e} 回延長しました。設定が記録されていないため、追加のシミュレーション時間は計算できません。",
                    "{n}회 보충으로 윈도우 {a}개를 추가하고 {e}회 연장했습니다. 설정이 기록되지 않아 추가 시뮬레이션 시간은 계산할 수 없습니다."),
    "share": ("第一批 {n0} 個窗口約 {c0} ps，補窗多了約 {pct}%。", "The first {n0} windows cost about {c0} ps, so refinement added about {pct}%.",
              "最初の {n0} 個のウィンドウは約 {c0} ps で、補窓で約 {pct}% 増えました。",
              "첫 {n0}개 윈도우의 비용은 약 {c0} ps이며, 보충으로 약 {pct}% 늘었습니다."),
    "ovl": ("重疊最小值從 {a} 提高到 {b}。", "The minimum overlap rose from {a} to {b}.", "重なりの最小値は {a} から {b} に上がりました。",
            "겹침 최솟값은 보충 전 {a}, 보충 후 {b}입니다."),
    "ovl_gone": ("缺口處的重疊最小值原為 {a}，補窗後沒有低於目標的缺口。", "The minimum overlap at the gaps was {a}; after refinement no gap is below the target.",
                 "ギャップでの重なりの最小値は {a} でしたが、補窓後は目標を下回るギャップがありません。",
                 "보충 전 간격의 겹침 최솟값은 {a}입니다. 보충 후에는 목표보다 낮은 간격이 없습니다."),
    "continuous": ("取樣已連續。", "Sampling is now continuous.", "サンプリングは連続になりました。", "샘플링이 연속이 되었습니다."),
    "unsamplable": ("k 已到上限，{rg} 補不起來，見斷點。", "k is at its limit and {rg} cannot be filled, see the breaks.",
                    "k が上限に達しており、{rg} は埋められません。途切れを参照してください。",
                    "k가 상한에 도달해 {rg}는 채울 수 없습니다. 끊김을 참고하세요."),
    "unsamplable_nr": ("k 已到上限，有區段補不起來，見斷點。", "k is at its limit and some stretches cannot be filled, see the breaks.",
                       "k が上限に達しており、埋められない区間があります。途切れを参照してください。",
                       "k가 상한에 도달해 채울 수 없는 구간이 있습니다. 끊김을 참고하세요."),
    "open": ("補窗結束後仍有斷點 {rg}。", "Breaks remain after refinement at {rg}.", "補窓の後も {rg} に途切れが残っています。",
             "보충 후에도 {rg}에 끊김이 남아 있습니다."),
    "open_nr": ("補窗結束後取樣仍不連續。", "Sampling is still discontinuous after refinement.", "補窓の後もサンプリングは不連続です。",
                "보충 후에도 샘플링이 불연속입니다."),
    "budget": ("每輪或總窗口數的上限已經用完。", "The per-round or total window limit was used up.", "ラウンドごと、または合計のウィンドウ数の上限を使い切りました。",
               "회차별 또는 전체 윈도우 수 상한을 모두 사용했습니다."),
    "incomplete": ("補窗還沒有完成，以上是目前的紀錄。", "Refinement is not finished, this is the record so far.",
                   "補窓はまだ終わっていません。ここまでの記録です。", "보충이 아직 끝나지 않았습니다. 지금까지의 기록입니다."),
    "unknown": ("補窗後是否連續沒有紀錄。", "Whether sampling ended up continuous is not recorded.", "補窓の後に連続になったかは記録されていません。",
                "보충 후 연속이 되었는지는 기록되어 있지 않습니다."),
    "no_action": ("第一批窗口已經連續，沒有補窗。", "The first windows were already continuous, so nothing was refined.",
                  "最初のウィンドウで既に連続していたため、補窓はしていません。", "첫 윈도우가 이미 연속이어서 보충하지 않았습니다."),
    "no_record": ("沒有補窗紀錄（這個結果沒有 refine_log.json）。", "No refinement record (this result has no refine_log.json).",
                  "補窓の記録がありません（この結果には refine_log.json がありません）。", "보충 기록이 없습니다(이 결과에는 refine_log.json이 없음)."),
}


def _t(x, lang: str, **kw) -> str:
    return pick(x, lang).format(**kw) if kw else pick(x, lang)


def _f(x, nd=2) -> str:
    return f"{x:.{nd}f}"


def _ps(x: float) -> str:
    return f"{x:.0f}" if abs(x - round(x)) < 0.05 else f"{x:.1f}"


def _ranges(rs) -> str:
    return "、".join(f"{a:.3f}–{b:.3f} nm" for a, b in rs[:4]) + ("…" if len(rs) > 4 else "")


def _ranges_for(lang: str, rs) -> str:
    sep = "、" if lang in ("zh", "ja") else ", "
    return sep.join(f"{a:.3f}–{b:.3f} nm" for a, b in rs[:4]) + ("…" if len(rs) > 4 else "")


def _ov(state: dict | None, lang: str) -> str:
    if not state:
        return pick(HEAD["unknown"], lang)
    if state.get("source") == "pass" and state.get("n_holes") == 0 and not state.get("unsamplable"):
        return pick(HEAD["no_gap"], lang)
    v = state.get("min_overlap")
    return pick(HEAD["unknown"], lang) if v is None else _f(v)


def _count(state: dict | None, lang: str) -> str:
    if not state or state.get("n_breaks") is None:
        return pick(HEAD["unknown"], lang)
    return str(state["n_breaks"])


def _yn(state: dict | None, lang: str) -> str:
    if not state or state.get("continuous") is None:
        return pick(HEAD["unknown"], lang)
    return pick(HEAD["yes"] if state["continuous"] else HEAD["no"], lang)


def summary_sentence(s: dict, lang: str = "en") -> str:
    """One short paragraph: what was done, what it cost, what it changed, how it ended."""
    sep = "" if lang in ("zh", "ja") else " "
    o = s.get("outcome")
    if o == "no_record":
        return pick(SUM["no_record"], lang)
    t, parts = s.get("totals") or {}, []
    if t.get("rounds"):
        if t.get("cost_known"):
            parts.append(_t(SUM["work"], lang, n=t["rounds"], a=t["inserted"], e=t["extended"], ps=_ps(t["cost_ps"])))
            ini = s.get("initial") or {}
            if ini.get("cost_ps"):
                parts.append(_t(SUM["share"], lang, n0=ini["n_windows"], c0=_ps(ini["cost_ps"]),
                                pct=f"{100.0 * t['cost_ps'] / ini['cost_ps']:.0f}"))
        else:
            parts.append(_t(SUM["work_nocost"], lang, n=t["rounds"], a=t["inserted"], e=t["extended"]))
        acting = [r for r in s["rounds"] if r["inserted"] or r["extended"]]
        first, last = acting[0]["before"], acting[-1]["after"]
        a = first.get("min_overlap")
        if a is not None and last:
            if last.get("source") == "pass" and last.get("n_holes") == 0 and not last.get("unsamplable"):
                parts.append(_t(SUM["ovl_gone"], lang, a=_f(a)))
            elif last.get("min_overlap") is not None:
                parts.append(_t(SUM["ovl"], lang, a=_f(a), b=_f(last["min_overlap"])))
    fin = s.get("final") or {}
    if o == "continuous":
        parts.append(pick(SUM["continuous"], lang))
    elif o == "no_action_needed":
        parts.append(pick(SUM["no_action"], lang))
    elif o == "unsamplable":
        rs = fin.get("unsamplable") or fin.get("breaks") or []
        parts.append(_t(SUM["unsamplable"], lang, rg=_ranges_for(lang, rs)) if rs else pick(SUM["unsamplable_nr"], lang))
    elif o == "open":
        rs = fin.get("breaks") or []
        parts.append(_t(SUM["open"], lang, rg=_ranges_for(lang, rs)) if rs else pick(SUM["open_nr"], lang))
        if s.get("budget_limited"):
            parts.append(pick(SUM["budget"], lang))
    elif o == "incomplete":
        parts.append(pick(SUM["incomplete"], lang))
    else:
        parts.append(pick(SUM["unknown"], lang))
    return sep.join(parts)


def _action_lines(r: dict, lang: str) -> list[str]:
    ins, ext = r["inserted"], r["extended"]
    lines = []
    if ins:
        cs = ", ".join(f"{x['center']:.3f}" for x in ins[:6] if x["center"] is not None) + ("…" if len(ins) > 6 else "")
        lines.append(_t(ACT["insert"], lang, n=len(ins), cs=cs))
        if r["k_values"]:
            lines.append(_t(ACT["k"], lang, ks=" / ".join(f"{k:g}" for k in r["k_values"])))
        order = [c for c in ("overlap", "break", "endpoint", "aimed", "other") if r["reason_counts"].get(c)]
        if order:
            sep = "、" if lang in ("zh", "ja") else ", "
            lines.append(_t(ACT["why"], lang, w=sep.join(f"{pick(WHY[c], lang)} × {r['reason_counts'][c]}" for c in order)))
    if ext:
        cs = ", ".join(f"{c:.3f}" for c in ext[:6]) + ("…" if len(ext) > 6 else "")
        lines.append(_t(ACT["extend"], lang, n=len(ext), cs=cs))
    if r["skipped"]:
        lines.append(_t(ACT["skip"], lang, n=len(r["skipped"])))
    return lines or [pick(ACT["none"], lang)]


def _effect_lines(r: dict, lang: str) -> list[str]:
    b, a = r["before"], r["after"]
    unk = pick(HEAD["unknown"], lang)
    if a is None:
        a = {}
    return [_t(EFF["overlap"], lang, a=_ov(b, lang), b=_ov(a, lang) if a else unk),
            _t(EFF["breaks"], lang, a=_count(b, lang), b=_count(a, lang) if a else unk),
            _t(EFF["cont"], lang, a=_yn(b, lang), b=_yn(a, lang) if a else unk)]


def table(s: dict, lang: str = "en") -> dict:
    """{"headers", "rows": [[round, [action lines], cost text, [effect lines]]], "caption"} for the report table."""
    rows = []
    ini = s.get("initial")
    if ini:
        plan = {"informed": ("依 SMD 力曲線規劃 {n} 個窗口", "{n} windows planned from the SMD force curve", "SMD の力曲線から {n} 個のウィンドウを計画",
                             "SMD 힘 곡선으로 윈도우 {n}개 계획"),
                "uniform": ("等距規劃 {n} 個窗口", "{n} windows on an even grid", "等間隔で {n} 個のウィンドウを計画", "등간격으로 윈도우 {n}개 계획")}[ini["plan"]]
        rows.append([pick(HEAD["first"], lang), [_t(plan, lang, n=ini["n_windows"])],
                     _ps(ini["cost_ps"]) if ini.get("cost_ps") is not None else pick(HEAD["unknown"], lang), ["—"]])
    for r in s.get("rounds") or []:
        cost = pick(HEAD["unknown"], lang) if r["cost_ps"] is None else _ps(r["cost_ps"])
        if not r["completed"] and r["cost_ps"] is not None:
            cost += pick(HEAD["incomplete_tag"], lang)
        rows.append([str(r["round"]), _action_lines(r, lang), cost, _effect_lines(r, lang)])
    return {"headers": [pick(HEAD[k], lang) for k in ("round", "action", "cost", "effect")], "rows": rows,
            "caption": pick(HEAD["caption"], lang)}


def skipped_lines(s: dict, lang: str = "en") -> list[str]:
    """Each dropped proposal with its reason: structured text when the log has the fields, else the logged note."""
    out = []
    for r in s.get("rounds") or []:
        for k in r["skipped"]:
            if k["source"] == "skipped" and k["near"] is not None and k["center"] is not None:
                out.append(_t(SKIP["pair"], lang, r=r["round"], c=f"{k['center']:.3f}", k=f"{k['k']:g}" if k["k"] is not None else "?",
                              n=f"{k['near']:.3f}", nk=f"{k['near_k']:g}" if k["near_k"] is not None else "?",
                              d=f"{abs(k['near'] - k['center']):.4f}", s=f"{k['min_sep_nm']:.4f}" if k["min_sep_nm"] is not None else "?"))
            else:
                out.append(_t(SKIP["raw"], lang, r=r["round"], t=k["reason"]))
    return out
