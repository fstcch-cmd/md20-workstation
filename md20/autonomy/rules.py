"""D-137 (R8): deterministic rules — existing assessment objects in, `ActionProposal`s out.

Authority is the scientific assessment (`md20.sampling.assessment`, schema `md20.assessment.pmf/1`) and the planner's own
`RefinePlan` (`md20.sampling.adaptive`).  This module only maps "which diagnostic is failing / unknown" to "which of the
four supported actions addresses it", and states preconditions and comparison consequences.  It never reads a ΔG value:
the decision to act depends on whether the evidence is adequate, not on whether the number looks favourable.

Everything in the inputs is data.  Names, notes and document metadata are copied into the proposal as strings and never
interpreted.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .model import (ACTION_EXTEND, ACTION_REANALYSIS, ACTION_REFINE, ACTION_REPLICA, ActionProposal, BENEFIT_HEURISTIC,
                    DIMS, canonical)

ASSESSMENT_SCHEMA = "md20.assessment.pmf/1"
_STATUS = ("pass", "fail", "unknown")
# diagnostics a sampling-density action (new windows) addresses / a sampling-length action (longer runs) addresses
COVERAGE_DIAGS = ("histogram_coverage", "adjacent_overlap_min", "overlap_graph", "mbar_overlap")
LENGTH_DIAGS = ("window_ess", "half_split", "cumulative_drift")
REANALYSIS_DIAGS = ("solver",)
PROTOCOL_DIAGS = ("endpoint_plateau", "range_coverage")        # fixing these changes the CV range: a protocol decision
CLAIM_KEYS = ("delta_pmf_path_specific", "dG_standard", "affinity_ranking")
PRIORITY = {ACTION_REANALYSIS: 0, ACTION_REFINE: 1, ACTION_EXTEND: 2, ACTION_REPLICA: 3}


# ------------------------------------------------------------------------------------------------ inputs
@dataclass
class AssessmentInputs:
    """Everything `Controller.step` reads.  All fields optional except `scope`; absent evidence means 'not available'."""
    scope: str
    assessment: dict | None = None            # assess_pmf() / combine_assessments() output
    assessment_id: str | None = None          # e.g. "binding_manifest.json@2026-11-07T10:00:00Z"
    refine_plan: dict | None = None           # RefinePlan.to_dict() of the planner's current pass
    approved_run: dict | None = None          # {"run_id", "protocol_hash", "checkpoint": {...}, "extensions_done", "max_extensions"}
    replicas: dict | None = None              # {"done", "required", "system_ready"}
    reanalysis: dict | None = None            # {"available": bool}  stored samples still on disk
    costs: dict = field(default_factory=dict) # window_equil_ps, window_prod_ps, replica_ns, ns_per_day, gb_per_ns, reanalysis_core_hours, ...
    invalid_models: list = field(default_factory=list)
    evidence_ids: dict = field(default_factory=dict)   # diagnostic id → [evidence IDs]
    max_attempts: int = 2

    @classmethod
    def from_any(cls, x) -> "AssessmentInputs":
        if isinstance(x, cls):
            return x
        if not isinstance(x, dict):
            raise TypeError("assessment_inputs 必須是 AssessmentInputs 或 dict")
        names = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in x.items() if k in names})


# ------------------------------------------------------------------------------------------------ assessment checks
def validate_assessment(a) -> list[str]:
    """Problems that make an assessment uninterpretable (empty = usable).  Unknown *status values* are the problem; an
    honest `unknown` diagnostic is fine (it is what reanalysis is for)."""
    if not isinstance(a, dict) or not a:
        return ["沒有評估物件"]
    out = []
    if a.get("schema") != ASSESSMENT_SCHEMA:
        out.append(f"評估 schema 不認得：{str(a.get('schema'))[:60]!r}")
    diags = a.get("diagnostics")
    if not isinstance(diags, list) or not diags:
        out.append("評估沒有 diagnostics 清單")
    else:
        for d in diags:
            if not isinstance(d, dict) or not isinstance(d.get("id"), str) or d.get("status") not in _STATUS:
                out.append(f"診斷項目格式或狀態無效：{str(d)[:80]}")
                break
    if a.get("sampling_adequate") not in (True, False, None):
        out.append("sampling_adequate 不是 True/False/None")
    return out


def summarize(a: dict) -> dict:
    """The part of an assessment the controller compares before/after.  No energies."""
    diags = [d for d in a.get("diagnostics", []) if isinstance(d, dict)]
    ids = lambda s: sorted(d["id"] for d in diags if d.get("status") == s)  # noqa: E731
    s = {"pass": ids("pass"), "fail": ids("fail"), "unknown": ids("unknown"), "sampling_adequate": a.get("sampling_adequate"),
         "legacy": bool(a.get("legacy")), "thresholds_version": a.get("thresholds_version"),
         "ineligible_claims": sorted(k for k in CLAIM_KEYS if not (a.get("eligibility") or {}).get(k))}
    s["n_pass"] = len(s["pass"])
    s["digest"] = hashlib.sha256(canonical({k: s[k] for k in ("pass", "fail", "unknown", "sampling_adequate", "thresholds_version")}
                                           ).encode("utf-8")).hexdigest()[:16]
    return s


def improved(before: dict, after: dict, action_type: str) -> bool:
    """Deterministic 'did the evidence get better': more passing diagnostics, or adequacy reached; for reanalysis also
    fewer unknowns (turning unknown into an honest fail is information, not a regression)."""
    if after.get("sampling_adequate") is True and before.get("sampling_adequate") is not True:
        return True
    if after.get("n_pass", 0) > before.get("n_pass", 0):
        return True
    if action_type == ACTION_REANALYSIS and len(after.get("unknown", [])) < len(before.get("unknown", [])):
        return True
    return False


# ------------------------------------------------------------------------------------------------ cost estimates
def _round(x):
    return None if x is None else round(float(x), 6)


def _est(sim_ps: float | None, costs: dict, *, reanalysis: bool = False) -> dict:
    """Estimates derived only from recorded settings (same rule as report/auto_actions.py): unknown stays None."""
    e = {d: None for d in DIMS}
    e["basis"] = "heuristic: derived from recorded settings, not measured"
    if reanalysis:
        e["sim_ns"], e["gpu_hours"] = 0.0, 0.0
        e["core_hours"] = _round(costs.get("reanalysis_core_hours"))
        e["storage_gb"] = _round(costs.get("reanalysis_storage_gb"))
        return e
    if sim_ps is None:
        return e
    ns = sim_ps / 1000.0
    e["sim_ns"] = _round(ns)
    npd = costs.get("ns_per_day")
    if isinstance(npd, (int, float)) and npd > 0:
        e["gpu_hours"] = _round(ns / float(npd) * 24.0)
    cph = costs.get("core_hours_per_ns")
    if isinstance(cph, (int, float)) and cph >= 0:
        e["core_hours"] = _round(ns * float(cph))
    gpn = costs.get("gb_per_ns")
    if isinstance(gpn, (int, float)) and gpn >= 0:
        e["storage_gb"] = _round(ns * float(gpn))
    return e


def _ps(costs: dict, key: str):
    v = costs.get(key)
    return float(v) if isinstance(v, (int, float)) and v >= 0 else None


# ------------------------------------------------------------------------------------------------ proposal builders
def _ev(inp: AssessmentInputs, digest: str, diags: list[str]) -> list[str]:
    out = [f"assessment@{digest}:{d}" for d in diags]
    if inp.assessment_id:
        out.append(f"assessment_id:{inp.assessment_id}")
    for d in diags:
        out.extend(str(x) for x in (inp.evidence_ids or {}).get(d, []))
    return list(dict.fromkeys(out))


def _checkpoint(run: dict | None) -> tuple[dict, bool | None]:
    cp = (run or {}).get("checkpoint") if isinstance(run, dict) else None
    if not isinstance(cp, dict) or not cp.get("path"):
        return {"required": True, "path": None, "fingerprint": None}, (None if run is None else False)
    return {"required": True, "path": str(cp["path"]), "fingerprint": cp.get("fingerprint")}, True


def _recovery(n: int) -> str:
    return (f"失敗時只重試技術性失敗，最多 {n} 次（含第一次）；每次都從同一個通過驗證的 checkpoint 與同一組協定參數開始，"
            "不改力場、約束、參數或種子以外的任何設定；檢查點無效、模型無效或科學性失敗一律停下交給使用者，不重試。")


def build_proposals(inp: AssessmentInputs, summary: dict) -> tuple[list[ActionProposal], list[dict]]:
    """(proposals, escalations).  `escalations` are findings no supported routine action can address (e.g. a PMF range that
    needs changing: a protocol decision) — each `{"reason", "detail", "options"}`."""
    a, digest, scope = inp.assessment, summary["digest"], inp.scope
    fails, unknown = set(summary["fail"]), set(summary["unknown"])
    costs = inp.costs or {}
    claims = summary["ineligible_claims"] or list(CLAIM_KEYS)
    base = {k: summary[k] for k in ("pass", "fail", "unknown", "sampling_adequate", "n_pass", "digest")}
    props: list[ActionProposal] = []
    esc: list[dict] = []
    plan = inp.refine_plan if isinstance(inp.refine_plan, dict) else None

    def make(action, target, trigger, prereqs, estimate, inputs, benefit, consequences, checkpoint=None):
        return ActionProposal(
            action_type=action, scope=scope, target=target, trigger=list(trigger), evidence_ids=_ev(inp, digest, list(trigger)),
            prerequisites=prereqs, affected_claims=list(claims),
            expected_benefit={"statement": benefit, "kind": BENEFIT_HEURISTIC, "calibration_ref": None},
            estimate=estimate, protocol_changes=[], inputs={"assessment_digest": digest, **inputs},
            max_attempts=int(inp.max_attempts), checkpoint=checkpoint or {"required": False, "path": None, "fingerprint": None},
            recovery_plan=_recovery(int(inp.max_attempts)), comparison_consequences=consequences, baseline=base)

    # --- 1. reanalysis: unknown diagnostics, a legacy assessment, or a solver that did not converge
    re_trigger = sorted(unknown | (fails & set(REANALYSIS_DIAGS)))
    if summary["legacy"] or re_trigger:
        avail = (inp.reanalysis or {}).get("available") if isinstance(inp.reanalysis, dict) else None
        props.append(make(
            ACTION_REANALYSIS, {"scope": scope, "what": "stored window samples"}, re_trigger or ["legacy_assessment"],
            [{"id": "samples_on_disk", "description": "原始視窗樣本仍在磁碟上", "satisfied": avail if isinstance(avail, bool) else None}],
            _est(0.0, costs, reanalysis=True), {"unknown": sorted(unknown), "solver_failed": "solver" in fails},
            "把「未知」的診斷變成有根據的通過或不通過（資訊增加；不保證通過）。",
            ["不產生新取樣，已報告的取樣量不變。", f"重新分析要用同一版門檻（{summary.get('thresholds_version')}）；"
             "與其他候選比較時，被比較者必須用同一版分析。", "診斷由未知變成失敗是如實的結果，不是退步。"]))

    # --- 2. refine: coverage / overlap diagnostics failing and the planner has windows to insert
    cov = sorted(fails & set(COVERAGE_DIAGS))
    if cov:
        ins = (plan or {}).get("insert") or []
        if ins:
            centres = sorted(round(float(i["center"]), 4) for i in ins if isinstance(i, dict) and "center" in i)
            ks = {f"{round(float(i['center']), 4):.4f}": float(i.get("k", 0)) for i in ins if isinstance(i, dict) and "center" in i}
            per = (_ps(costs, "window_equil_ps") or 0.0) + (_ps(costs, "window_prod_ps") or 0.0) \
                if _ps(costs, "window_prod_ps") is not None and _ps(costs, "window_equil_ps") is not None else None
            props.append(make(
                ACTION_REFINE, {"scope": scope, "insert_centres": centres, "k": ks}, cov,
                [{"id": "planner_plan", "description": "規劃器（plan_refinement）本輪有要插入的窗口", "satisfied": True},
                 {"id": "within_approved_k", "description": "新窗口的 k 不超過已核准的 k_max（規劃器已限制）", "satisfied": True},
                 {"id": "within_window_cap", "description": "未超過規劃器的窗口總數上限", "satisfied": not bool((plan or {}).get("budget_exhausted"))}],
                _est(None if per is None else per * len(centres), costs),
                {"insert": centres, "k": ks, "round_notes": len((plan or {}).get("notes") or [])},
                f"補上 {len(centres)} 個窗口，目標是消除取樣缺口／重疊不足；是否真的連續要等重新評估（啟發式估計，未校準）。",
                ["PMF 與 ΔPMF 會因新窗口重算，不確定度也要重算；補窗是依資料決定的適應性程序，須在報告註明。",
                 "與其他候選比較時，雙方都要在同一個窗口覆蓋判準下評估，不能只替有利的候選補窗。"]))
        else:
            esc.append({"reason": "insufficient_evidence", "detail": "覆蓋／重疊診斷失敗，但規劃器沒有可插入的窗口（沒有規劃或已無可補）："
                        + "、".join(cov), "options": ["手動指定要補採樣的區間", "提高 k_max（改變協定，需另行核准）", "接受 ΔG° 不可報告"]})
        if (plan or {}).get("unsamplable"):
            esc.append({"reason": "unsamplable", "detail": f"規劃器標示 {len(plan['unsamplable'])} 段在 k_max 下仍無法取樣；"
                        "再補窗無效，改 k 或 CV 是協定決定。", "options": ["改用其他 CV", "提高 k_max（需另行核准）", "接受 ΔG° 不可報告"]})

    # --- 3. extend: window ESS / half-split / cumulative drift failing
    ln = sorted(fails & set(LENGTH_DIAGS))
    if ln:
        ext = (plan or {}).get("extend") or []
        centres = sorted(round(float(e["center"]), 4) for e in ext if isinstance(e, dict) and "center" in e)
        run = inp.approved_run if isinstance(inp.approved_run, dict) else None
        cp, cp_ok = _checkpoint(run)
        done, mx = (run or {}).get("extensions_done"), (run or {}).get("max_extensions")
        under_cap = None if not (isinstance(done, int) and isinstance(mx, int)) else done < mx
        prod = _ps(costs, "window_prod_ps")
        n_win = len(centres) if centres else (run or {}).get("n_windows")
        sim = prod * n_win if (prod is not None and isinstance(n_win, int)) else None
        props.append(make(
            ACTION_EXTEND, {"scope": scope, "run_id": (run or {}).get("run_id"), "window_centres": centres}, ln,
            [{"id": "approved_run", "description": "有已核准的執行可延長（run_id 與協定雜湊）",
              "satisfied": None if run is None else bool(run.get("run_id") and run.get("protocol_hash"))},
             {"id": "checkpoint_present", "description": "有可續跑的檢查點（執行時還會驗證指紋）", "satisfied": cp_ok},
             {"id": "extension_cap", "description": "延長次數未達上限（避免無止境延長）", "satisfied": under_cap}],
            _est(sim, costs), {"run_id": (run or {}).get("run_id"), "protocol_hash": (run or {}).get("protocol_hash"),
                               "centres": centres, "extensions_done": done},
            "用同一個協定增加取樣長度，降低統計誤差與漂移（啟發式估計，未校準；相關時間長時效益可能有限）。",
            ["同協定延長：該系統的取樣量變大，與未延長的候選比較要註明取樣量差異，或把被比較者延長到同一標準。",
             "延長後要重新評估；不可只延長結果看起來有利的系統。"], checkpoint=cp))

    # --- 4. add an independent replica
    rep = inp.replicas if isinstance(inp.replicas, dict) else None
    if rep and isinstance(rep.get("done"), int) and isinstance(rep.get("required"), int) and rep["done"] < rep["required"]:
        run = inp.approved_run if isinstance(inp.approved_run, dict) else None
        ns = _ps(costs, "replica_ns")
        props.append(make(
            ACTION_REPLICA, {"scope": scope, "replica_index": rep["done"]}, ["replicas_below_required"],
            [{"id": "system_ready", "description": "已建好、已核准的系統可作為新重複的起點", "satisfied": rep.get("system_ready") if isinstance(rep.get("system_ready"), bool) else None},
             {"id": "same_protocol", "description": "沿用同一份協定與（不同的）種子", "satisfied": True if run is None or run.get("protocol_hash") else None}],
            _est(None if ns is None else ns * 1000.0, costs),
            {"done": rep["done"], "required": rep["required"]},
            f"目前 {rep['done']} 條、需要 {rep['required']} 條；補上一條才能估計重複間的不確定度（啟發式，未校準）。",
            ["跨重複彙總要重算；每條重複都必須合格才算（不挑有利的重複）。",
             "比較的兩邊重複數應相同；新重複用不同種子，其餘協定不變。"]))

    # --- 5. things no routine action can fix
    pr = sorted(fails & set(PROTOCOL_DIAGS))
    if pr:
        esc.append({"reason": "protocol_decision_needed", "detail": "診斷失敗但修正會改變 CV 範圍或參考態：" + "、".join(pr),
                    "options": ["由使用者決定是否改變 CV 範圍（新協定）", "接受 ΔG° 不可報告"]})
    # every failing diagnostic is handled above (a proposal, possibly blocked, or an escalation) except ones this module
    # does not know: say so instead of ignoring them
    handled = set(re_trigger) | set(cov) | set(ln) | set(pr) | {"solver"}
    left = sorted(fails - handled)
    if left:
        esc.append({"reason": "insufficient_evidence", "detail": "有失敗的診斷但沒有可套用的例行行動：" + "、".join(left),
                    "options": ["由使用者檢查評估", "接受 ΔG° 不可報告"]})
    props.sort(key=lambda p: PRIORITY[p.action_type])
    return props, esc
