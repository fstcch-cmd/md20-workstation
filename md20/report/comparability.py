"""D-120 (F05): which candidate can be compared with which, how far, and why not.

compare_binding gives one table per context.  This module answers the same question for every PAIR of candidates, so a
student sees at a glance where the evidence stops.  It adds no rule of its own:

  * each pair is graded by `multi.context_basis` (the function compare_binding itself uses), applied to the two
    results only, so a cell can never disagree with what compare_binding would say about those two candidates;
  * a result is kept out for the reason `multi.exclusion_of` gives (execution status, legacy, not qualified);
  * the condition signature is the one compare_binding compares (`multi.cond_view`);
  * a field that is not recorded is never "equal" (no condition at all → not comparable).

grade:  ddg          both ΔG° qualified, same conditions → ΔΔG°
        order        both ΔPMF qualified (path-specific), same conditions, but a ΔG° is missing → order of well depths
        descriptive  two ligands pulled from the same shared pocket → values under a co-occupancy condition, no ranking
        none         anything else; `reasons` says why
MD settings (force field, water model, temperature, replicas …) that differ are listed in `notes` only.  They do not
change the grade, because compare_binding does not use them; the student is told so and decides.

Pure Python.  `results` is the workflow's binding results (state steps.binding.results)."""
from __future__ import annotations

from ..sampling.multi import context_basis, cond_view, exclusion_of
from ..sampling.assessment import claim_eligible

SCHEMA = "md20.comparability/1"
GRADES = ("ddg", "order", "descriptive", "none")

GRADE_LABEL = {
    "ddg": ("ΔΔG° 可比", "ΔΔG° comparable", "ΔΔG° を比較できる", "ΔΔG° 비교 가능"),
    "order": ("路徑特定的順序", "path-specific order", "経路固有の順序", "경로 특이적 순서"),
    "descriptive": ("只能描述", "descriptive only", "記述のみ", "기술만 가능"),
    "none": ("不可比", "not comparable", "比較不可", "비교 불가"),
}
GRADE_MEANS = {
    "ddg": ("兩個結果都有合格的 ΔG°，條件相同，可以算 ΔΔG°。",
            "Both results have a qualified ΔG° under the same conditions, so ΔΔG° can be computed.",
            "どちらの結果にも合格した ΔG° があり、条件も同じなので、ΔΔG° を計算できます。",
            "두 결과 모두 적격한 ΔG°가 있고 조건이 같아 ΔΔG°를 계산할 수 있습니다."),
    "order": ("兩個結果的 ΔPMF 都合格且條件相同，但至少一個沒有合格的 ΔG°。只能比各自拉離路徑上的井深順序，不是親和力排名。",
              "Both ΔPMF values are qualified under the same conditions, but at least one result has no qualified ΔG°. "
              "Only the order of well depths along each pull path can be compared. It is not an affinity ranking.",
              "どちらの ΔPMF も合格していて条件も同じですが、少なくとも一方に合格した ΔG° がありません。"
              "比べられるのは各引き離し経路に沿った井戸の深さの順序だけで、親和性の順位ではありません。",
              "두 ΔPMF 모두 적격하고 조건도 같지만 적어도 한쪽에 적격한 ΔG°가 없습니다. "
              "각 당김 경로를 따른 우물 깊이의 순서만 비교할 수 있으며 친화도 순위가 아닙니다."),
    "descriptive": ("共同口袋中的配體各自在不同的旁觀配體與拉離路徑下拉離，只列數值，不排名。",
                    "Ligands in a shared pocket were pulled with different spectators and exit paths. Their values are listed, "
                    "not ranked.",
                    "共通ポケットのリガンドは、傍観リガンドも引き離し経路も異なる条件で引き離されています。値は示しますが順位はつけません。",
                    "공유 포켓의 리간드는 관찰 리간드와 당김 경로가 다른 조건에서 당겨졌습니다. 값만 제시하고 순위는 매기지 않습니다."),
    "none": ("至少一邊沒有合格的結果，或條件不同，或屬於不同情境。原因列在表的下方。",
             "At least one side has no qualified result, or the conditions differ, or the contexts differ. The reasons are "
             "listed below the table.",
             "どちらかの結果が合格していないか、条件が違うか、状況が違います。理由は表の下に示します。",
             "적어도 한쪽에 적격한 결과가 없거나, 조건이 다르거나, 상황이 다릅니다. 이유는 표 아래에 있습니다."),
}

# condition-signature fields (sampling.binding.binding_condition) and MD settings (analysis.common_basis.conditions)
FIELD = {
    "cv": ("拉離座標", "pulling coordinate", "引き離しの座標", "당김 좌표"),
    "temperature_k": ("溫度", "temperature", "温度", "온도"),
    "backbone_restraint_kj_mol_nm2": ("骨架約束", "backbone restraint", "骨格の拘束", "골격 구속"),
    "n_spectators": ("旁觀配體數", "number of spectator ligands", "傍観リガンドの数", "관찰 리간드 수"),
    "hold_spectators": ("旁觀配體固定", "spectator holding", "傍観リガンドの固定", "관찰 리간드 고정"),
    "anchor": ("anchor", "anchor", "アンカー", "anchor"),
    "funnel_restraint": ("漏斗約束", "funnel restraint", "ファンネル拘束", "깔때기 구속"),
    "standard_state": ("標準態處理", "standard-state treatment", "標準状態の扱い", "표준 상태 처리"),
    "ensemble": ("系綜", "ensemble", "アンサンブル", "앙상블"),
    "restrained": ("正式模擬的約束", "production restraints", "本計算の拘束", "본 계산의 구속"),
    "water_model": ("水模型", "water model", "水モデル", "물 모델"),
    "forcefield": ("力場", "force field", "力場", "힘장"),
    "solvent": ("溶劑", "solvent", "溶媒", "용매"),
    "hmr": ("氫質量重分配", "hydrogen mass repartitioning", "水素質量の再配分", "수소 질량 재분배"),
    "production_ps": ("正式模擬長度", "production length", "本計算の長さ", "본 계산 길이"),
    "replicas": ("重複數", "replica count", "反復数", "반복 수"),
}
# {k} candidate, {d} detail, {f} field, {v} values.  Reasons (they block) → R; limits (why not higher) → LIM; notes → NOTE.
R = {
    "exec_status": ("{k}：執行狀態 {d}，沒有結果", "{k}: run status {d}, no result", "{k}：実行状態 {d}、結果なし",
                    "{k}: 실행 상태 {d}, 결과 없음"),
    "legacy": ("{k}：舊結果沒有儲存評估，等待重新分析", "{k}: no stored assessment, awaiting reanalysis",
               "{k}：保存された評価がなく、再解析待ち", "{k}: 저장된 평가가 없어 재분석 대기"),
    "no_dpmf": ("{k}：沒有 ΔPMF 數值", "{k}: no ΔPMF value", "{k}：ΔPMF の値なし", "{k}: ΔPMF 값 없음"),
    "not_qualified": ("{k}：未通過取樣評估（{d}）", "{k}: did not pass the sampling assessment ({d})",
                      "{k}：取得評価に不合格（{d}）", "{k}: 샘플링 평가 미통과({d})"),
    "different_context": ("屬於不同情境（{d}），不互相比較", "different contexts ({d}), not compared with each other",
                          "状況が異なる（{d}）ため、互いに比較しません", "상황이 달라({d}) 서로 비교하지 않습니다"),
    "context_unknown": ("無法確認是否屬於同一個共同口袋，不假設相同", "cannot confirm that both come from the same shared pocket, "
                        "so they are not assumed equal", "同じ共通ポケットのものか確認できないため、同じとは見なしません",
                        "같은 공유 포켓에서 온 것인지 확인할 수 없어 같다고 가정하지 않습니다"),
    "condition_missing": ("{k}：沒有記錄拉離條件，不假設相同", "{k}: no pull conditions recorded, not assumed equal",
                          "{k}：引き離しの条件の記録がなく、同じとは見なしません", "{k}: 당김 조건 기록이 없어 같다고 가정하지 않습니다"),
    "condition_differs": ("拉離條件不同，{f}（{v}）", "pull conditions differ, {f} ({v})", "引き離しの条件が違います。{f}（{v}）",
                          "당김 조건이 다릅니다. {f}({v})"),
    "unspecified": ("無法確認可以比較", "cannot confirm that they can be compared", "比較できることを確認できません",
                    "비교할 수 있는지 확인할 수 없습니다"),
}
LIM = {
    "no_dG": ("沒有合格 ΔG° 的結果是 {d}，所以只給順序", "No qualified ΔG° for {d}, so only the order is given",
              "合格した ΔG° がない結果は {d} です。順序だけを示します", "적격한 ΔG°가 없는 결과 {d}, 순서만 제시합니다"),
    "shared_pocket": ("共同口袋中各配體的旁觀配體與拉離路徑不同，只列數值，不排名",
                      "In a shared pocket each ligand has different spectators and exit paths, so values are listed, not ranked",
                      "共通ポケットでは各リガンドの傍観リガンドと引き離し経路が異なるため、値は示しますが順位はつけません",
                      "공유 포켓에서는 리간드마다 관찰 리간드와 당김 경로가 달라 값만 제시하고 순위는 매기지 않습니다"),
    "diagnostic_only": ("{d} 未通過取樣評估，只是診斷用的數值", "{d} did not pass the sampling assessment: diagnostic values only",
                        "{d} は取得評価に不合格で、診断用の値です", "{d} 샘플링 평가 미통과, 진단용 값"),
    "co_occupancy_pair": ("同一個配體的單獨結合與共同口袋，位移請看共存效應",
                          "The same ligand alone and in the shared pocket: see the co-occupancy effect for the shift",
                          "同じリガンドの単独結合と共通ポケットのずれは、共存の効果を見てください",
                          "같은 리간드의 단독 결합과 공유 포켓의 차이는 공존 효과를 보세요"),
}
NOTE = {
    "md_differs": ("MD 設定另有差異：{d}。這不在比較資格的判斷內，請自行確認",
                   "MD settings also differ: {d}. This is not part of the eligibility rule, so check it yourself",
                   "MD の設定にも違いがあります：{d}。比較資格の判定には含まれないので、自分で確認してください",
                   "MD 설정에도 차이가 있습니다: {d}. 비교 자격 판정에 포함되지 않으므로 직접 확인하세요"),
    "md_unknown": ("MD 設定無法確認：{d}。不假設相同，這也不在比較資格的判斷內",
                   "MD settings that cannot be confirmed: {d}. They are not assumed equal and are not part of the eligibility rule",
                   "MD の設定で確認できない項目：{d}。同じとは見なしませんが、比較資格の判定には含まれません",
                   "확인할 수 없는 MD 설정: {d}. 같다고 가정하지 않지만 비교 자격 판정에는 포함되지 않습니다"),
    "replicas": ("重複數不同或沒有記錄：{d}", "replica count differs or is not recorded: {d}",
                 "反復数が違うか記録がありません：{d}", "반복 수가 다르거나 기록이 없습니다: {d}"),
}
STATUS_WORD = {"pass": ("通過", "pass", "合格", "통과"), "fail": ("未通過", "fail", "不合格", "미통과"),
               "unknown": ("未知", "unknown", "不明", "알 수 없음")}
SELF = ("—", "—", "—", "—")


# ------------------------------------------------------------------------------------------------ the matrix
def context_of(key: str, r: dict | None) -> str:
    """'single' or 'multi:<case>' ('multi:?' when a shared-pocket result does not say which case)."""
    c = (r or {}).get("context")
    if c:
        return str(c)
    return "multi:?" if str(key).startswith("multi:") else "single"


def _path_ok(r, e):
    return e.get("delta_pmf_path_specific")


def _candidate_reasons(k: str, r: dict) -> list[dict]:
    """Why this one result cannot enter a path-specific comparison (same checks as compare_binding)."""
    x = exclusion_of(r, _path_ok)
    if x:
        code, text = x
        a = r.get("assessment") or {}
        items = list(a.get("reasons") or [])
        return [{"code": code, "key": k, "detail": r.get("status") if code == "exec_status" else text, "items": items}]
    if r.get("delta_pmf_kj_mol") is None:
        return [{"code": "no_dpmf", "key": k}]
    return []


def _cond_diff(ka: str, ra: dict, kb: str, rb: dict) -> list[dict]:
    va, vb = cond_view(ra) or {}, cond_view(rb) or {}
    return [{"field": f, "values": {ka: va.get(f), kb: vb.get(f)}} for f in sorted(set(va) | set(vb)) if va.get(f) != vb.get(f)]


def _md_notes(ka, kb, md_conditions, results) -> list[dict]:
    notes = []
    if md_conditions is not None:
        from ..analysis.common_basis import comparability as md_comparability
        c = md_comparability({ka: md_conditions.get(ka) or {}, kb: md_conditions.get(kb) or {}})
        if c["differences"]:
            notes.append({"code": "md_differs", "fields": [d["field"] for d in c["differences"]],
                          "values": {d["field"]: d["values"] for d in c["differences"]}})
        if c["unknown"]:
            notes.append({"code": "md_unknown", "fields": list(c["unknown"])})
    ra, rb = results[ka].get("replicas"), results[kb].get("replicas")
    if ra is None or rb is None or ra != rb:
        notes.append({"code": "replicas", "fields": ["replicas"], "values": {"replicas": {ka: ra, kb: rb}}})
    return notes


def _cell(ka: str, kb: str, results: dict, md_conditions) -> dict:
    ra, rb = results[ka], results[kb]
    ca, cb = context_of(ka, ra), context_of(kb, rb)
    reasons, limits = [], []
    cell_reasons = _candidate_reasons(ka, ra) + _candidate_reasons(kb, rb)
    grade = "none"
    if ca != cb:
        reasons += cell_reasons + [{"code": "different_context", "contexts": [ca, cb]}]
        if ra.get("ligand") and ra.get("ligand") == rb.get("ligand"):
            limits.append({"code": "co_occupancy_pair"})
    elif ca.startswith("multi"):
        if "?" in ca:
            reasons += cell_reasons + [{"code": "context_unknown"}]
        else:
            executed = [k for k in (ka, kb) if results[k].get("status") == "PASS"
                        and results[k].get("delta_pmf_kj_mol") is not None]
            if len(executed) == 2:
                grade = "descriptive"
                limits.append({"code": "shared_pocket"})
                weak = [k for k in (ka, kb) if exclusion_of(results[k], _path_ok)]
                if weak:
                    limits.append({"code": "diagnostic_only", "keys": weak})
            else:
                reasons += [x for x in cell_reasons if x["code"] in ("exec_status", "no_dpmf", "legacy", "not_qualified")
                            and x["key"] not in executed]
    else:
        basis = context_basis(results, [ka, kb])
        if basis["enough"]:
            grade = "ddg" if basis["use_dG"] else "order"
            if grade == "order":
                lacking = [k for k in (ka, kb) if not (results[k].get("dG_standard_kj_mol") is not None and
                                                       claim_eligible(results[k], "dG_standard"))]
                limits.append({"code": "no_dG", "keys": lacking,
                               "withheld": {k: results[k].get("dG_withheld") for k in lacking if results[k].get("dG_withheld")}})
        else:
            reasons += cell_reasons
            if not cell_reasons and basis["cond_bad"]:
                missing = [k for k in (ka, kb) if cond_view(results[k]) is None]
                reasons += [{"code": "condition_missing", "key": k} for k in missing]
                if not missing:
                    reasons += [{"code": "condition_differs", "field": d["field"], "values": d["values"]}
                                for d in _cond_diff(ka, ra, kb, rb)]
    if grade == "none" and not reasons:
        reasons.append({"code": "unspecified"})
    return {"a": ka, "b": kb, "grade": grade, "reasons": reasons, "limits": limits, "notes": _md_notes(ka, kb, md_conditions, results)}


def comparability_matrix(results: dict, *, md_conditions: dict | None = None) -> dict:
    """N×N grades for every pair of binding results.  `md_conditions` = {result key: common_basis.conditions(...)} for
    the MD settings notes (omit it and no MD note is made).  Symmetric; the diagonal is "self"."""
    keys = [k for k, r in (results or {}).items() if isinstance(r, dict)]
    keys.sort(key=lambda k: (context_of(k, results[k]) != "single", context_of(k, results[k])))     # stable: singles first
    cells: dict[str, dict] = {k: {} for k in keys}
    summary = {g: 0 for g in GRADES}
    for i, a in enumerate(keys):
        cells[a][a] = {"a": a, "b": a, "grade": "self", "reasons": [], "limits": [], "notes": []}
        for b in keys[i + 1:]:
            c = _cell(a, b, results, md_conditions)
            cells[a][b] = c
            cells[b][a] = {**c, "a": b, "b": a}
            summary[c["grade"]] += 1
    return {"schema": SCHEMA, "candidates": keys, "contexts": {k: context_of(k, results[k]) for k in keys},
            "cells": cells, "summary": summary}


def md_conditions_map(results: dict, cases: dict, conditions: dict | None) -> dict | None:
    """{result key: MD conditions of the run it was pulled from}.  `cases` = state md_cases.cases, `conditions` =
    analysis.comparison.comparability.conditions (None when not recorded → None: no MD note)."""
    if conditions is None:
        return None
    out = {}
    for k, r in (results or {}).items():
        if not isinstance(r, dict):
            continue
        ctx = context_of(k, r)
        if ctx.startswith("multi:") and "?" not in ctx:
            run_key = ctx.split(":", 1)[1]
        else:
            run_key = next((ck for ck, c in (cases or {}).items()
                            if isinstance(c, dict) and c.get("mode") == "docked_single" and k in (c.get("ligands") or [])), None)
        if run_key in conditions:
            out[k] = conditions[run_key]
    return out


# ------------------------------------------------------------------------------------------------ text
def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v) or "—"
    if isinstance(v, dict):
        return ", ".join(f"{a}={b}" for a, b in v.items())
    return str(v)


def _pick(t, lang):
    from ..i18n import pick
    return pick(t, lang)


def context_label(ctx: str, lang: str) -> str:
    if ctx == "single":
        return _pick(("單獨結合", "bound alone", "単独結合", "단독 결합"), lang)
    case = ctx.split(":", 1)[1] if ":" in ctx else ctx
    return _pick((f"共同口袋 {case}", f"shared pocket {case}", f"共通ポケット {case}", f"공유 포켓 {case}"), lang)


def _field(f: str, lang: str) -> str:
    return _pick(FIELD[f], lang) if f in FIELD else f


def _diag_items(items: list[str], lang: str) -> str:
    """'overlap_graph: fail' → localised diagnostic name and status; anything else is shown as stored."""
    from .figure_text import _DIAG_NAME
    out = []
    for s in items:
        i, _, st = str(s).partition(": ")
        if i in _DIAG_NAME and st in STATUS_WORD:
            out.append(f"{_pick(_DIAG_NAME[i], lang)} {_pick(STATUS_WORD[st], lang)}")
        else:
            out.append(str(s))
    return ("、" if lang in ("zh", "ja") else ", ").join(out)


def reason_text(x: dict, lang: str) -> str:
    """One reason, limit or note of a cell in `lang` (plain text)."""
    code = x["code"]
    table = R if code in R else LIM if code in LIM else NOTE
    t = _pick(table[code], lang)
    sep = "、" if lang in ("zh", "ja") else ", "
    if code == "exec_status":
        return t.format(k=x["key"], d=x.get("detail"))
    if code == "not_qualified":
        d = _diag_items(x.get("items") or [], lang) or _pick(("原因未記錄", "reason not recorded", "理由の記録なし", "이유 기록 없음"), lang)
        return t.format(k=x["key"], d=d)
    if code in ("legacy", "no_dpmf", "condition_missing"):
        return t.format(k=x["key"])
    if code == "different_context":
        return t.format(d=" · ".join(context_label(c, lang) for c in x["contexts"]))
    if code == "condition_differs":
        v = sep.join(f"{k} {_fmt(val)}" for k, val in x["values"].items())
        return t.format(f=_field(x["field"], lang), v=v)
    if code == "no_dG":
        d = sep.join(x["keys"])
        w = x.get("withheld") or {}
        if w:
            d += " (" + "; ".join(f"{k}: {v}" for k, v in w.items()) + ")"
        return t.format(d=d)
    if code == "diagnostic_only":
        return t.format(d=sep.join(x["keys"]))
    if code in ("md_differs", "md_unknown"):
        return t.format(d=sep.join(_field(f, lang) for f in x["fields"]))
    if code == "replicas":
        vals = x["values"]["replicas"]
        return t.format(d=sep.join(f"{k} {_fmt(v)}" for k, v in vals.items()))
    return t
