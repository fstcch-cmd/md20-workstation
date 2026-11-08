"""D-108 (F01) / D-134 (R2): research design and evidence coverage — what was planned, what actually ran, and what the
evidence can support, one row per item, so a reader sees the gaps before the results.

Execution and science are separate (D-134).  Every row carries
  execution_status  "ran" | "not_run"            — did the calculation finish; says nothing about its validity
  assessment        None | {state pass/fail/unknown, source, thresholds_version, evidence_ids, failed, unknown}
  claim             None | the claim the row is judged against (dG_standard | path_specific | diagnostic_curve)
  claim_eligibility None | bool                   — may that claim be stated
and the backward-compatible `status` the report renderer uses:
  "supported" the assessment supports the stated claim (or a plain check passed) | "limited" ran; a stated limitation
  narrows what it shows | "missing" planned, not run or failed | "ran" execution only — finished, no scientific claim.
Never "supported" by default: a field that cannot be read is "limited" with the reason "not recorded"; a binding result
is "supported" only through `sampling.assessment.claim_status` — the same record captions, the summary and the comparison read.
Pure: reads the workflow's state.json / config and the analysis files it points to.
"""
from __future__ import annotations

from ..util import load_json

T = {
    "docking": ("對接", "Docking", "ドッキング", "도킹"),
    "md": ("分子動力學", "Molecular dynamics", "分子動力学", "분자동역학"),
    "replicas": ("重複模擬", "Replicas", "反復計算", "반복 계산"),
    "analysis": ("軌跡分析", "Trajectory analysis", "トラジェクトリ解析", "궤적 분석"),
    "compare": ("系統之間的比較", "Comparison between systems", "系どうしの比較", "계 사이 비교"),
    "kinetics": ("慢運動與馬可夫模型", "Slow motions and Markov model", "遅い運動とマルコフモデル", "느린 운동과 마르코프 모델"),
    "binding": ("結合自由能", "Binding free energy", "結合自由エネルギー", "결합 자유 에너지"),
    "auto": ("自動補窗", "Automatic window refinement", "自動補窓", "자동 윈도우 보충"),
}
R = {
    "not_recorded": ("沒有紀錄", "not recorded", "記録なし", "기록 없음"),
    "not_run": ("沒有執行或沒有完成", "not run or not finished", "実行されていないか未完了", "실행하지 않았거나 끝나지 않음"),
    "restrained": ("正式模擬有約束，RMSD／RMSF 被壓低", "restrained production: RMSD/RMSF are held down",
                   "本計算に拘束あり：RMSD／RMSF は抑えられている", "본 계산에 구속 있음: RMSD/RMSF가 눌려 있음"),
    "fewer_replicas": ("完成的重複比計畫少", "fewer replicas finished than planned", "計画より完了した反復が少ない", "계획보다 끝난 반복이 적음"),
    "single": ("只有一條軌跡，沒有重複間的誤差", "one trajectory: no between-replica error", "トラジェクトリ 1 本：反復間の誤差なし",
               "궤적 하나: 반복 간 오차 없음"),
    "partial_analysis": ("部分分析失敗", "some analyses failed", "一部の解析が失敗", "일부 분석 실패"),
    "not_comparable": ("條件不同或無法確認", "conditions differ or cannot be confirmed", "条件が違うか確認できない", "조건이 다르거나 확인 불가"),
    "msm_insufficient": ("轉換太少，不建立結論", "too few transitions: no conclusion", "遷移が少なすぎ：結論なし", "전이가 너무 적음: 결론 없음"),
    "msm_unresolved": ("最慢過程長於模擬三分之一", "slowest process longer than a third of the run", "最も遅い過程が計算の 3 分の 1 より長い",
                       "가장 느린 과정이 계산의 3분의 1보다 김"),
    "msm_exploratory": ("單一軌跡，只能探索", "one trajectory: exploratory only", "1 本のトラジェクトリ：探索的", "궤적 하나: 탐색적"),
    "dg_withheld": ("ΔG° 不輸出", "ΔG° withheld", "ΔG° は出力しない", "ΔG° 출력 안 함"),
    "auto_unsamplable": ("補不起來，k 已到上限，見斷點", "could not be filled, k at its limit, see the breaks",
                         "埋められない：k が上限、途切れを参照", "채울 수 없음: k가 상한, 끊김 참조"),
    "auto_open": ("補窗後仍有斷點", "breaks remain after refinement", "補窓の後も途切れが残る", "보충 후에도 끊김이 남음"),
    "auto_incomplete": ("補窗尚未完成", "refinement not finished", "補窓が未完了", "보충이 끝나지 않음"),
    "not_selected": ("沒有選出姿勢", "no pose selected", "ポーズが選ばれていない", "포즈가 선택되지 않음"),
    # D-134 (R2): execution is not a scientific claim; binding rows read the one versioned assessment
    "execution_only": ("只代表模擬跑完，不是科學上已通過的結論", "the simulation finished; that is execution, not a validated conclusion",
                       "計算が終わっただけで、科学的に検証された結論ではない", "계산이 끝났을 뿐 과학적으로 검증된 결론이 아님"),
    "assess_legacy": ("評估缺漏或舊版，需重新分析", "assessment missing or from an older version: reanalysis needed",
                      "評価がないか旧版：再解析が必要", "평가가 없거나 구버전: 재분석 필요"),
    "assess_failed": ("取樣評估未通過", "the sampling assessment failed", "取得評価が不合格", "샘플링 평가 미통과"),
    "assess_unknown": ("部分取樣診斷沒有紀錄，視為未知", "some sampling diagnostics are not recorded and count as unknown",
                       "一部の取得診断が記録されておらず、不明として扱う", "일부 샘플링 진단이 기록되지 않아 미상으로 취급"),
    "path_specific_only": ("只有沿這條拉離路徑的 PMF（描述性），不是標準 ΔG°",
                           "only the PMF along this pulling path (descriptive), not a standard ΔG°",
                           "この引き離し経路に沿った PMF（記述的）だけで、標準 ΔG° ではない",
                           "이 당김 경로를 따른 PMF(기술적)일 뿐 표준 ΔG°가 아님"),
    "no_curve": ("沒有 PMF 曲線", "no PMF curve", "PMF 曲線がない", "PMF 곡선 없음"),
    # D-140 (A8): the 1 M radial ΔG° is approximate; a ranking needs the funnel restraint with the analytic standard state
    "no_funnel_standard_state": ("ΔG° 沒有漏斗約束與解析標準態校正（1 M 徑向近似），不用於親和力排序",
                                 "the ΔG° has no funnel restraint or analytic standard-state correction (1 M radial approximation) "
                                 "and is not used for affinity ranking",
                                 "この ΔG° にはファンネル拘束も解析的な標準状態補正もなく（1 M 動径近似）、親和性の順位づけには使わない",
                                 "이 ΔG°에는 깔때기 구속과 해석적 표준 상태 보정이 없어(1 M 방사 근사) 친화도 순위에 쓰지 않음"),
}
# the claim a row is judged against (what the row may say when its status is "supported")
C = {
    "affinity_ranking": ("標準結合自由能 ΔG°（漏斗約束加解析標準態校正，可用於親和力排序）",
                         "standard binding free energy ΔG° (funnel restraint with analytic standard-state correction; may be used "
                         "for affinity ranking)",
                         "標準結合自由エネルギー ΔG°（ファンネル拘束と解析的な標準状態補正、親和性の順位づけに使える）",
                         "표준 결합 자유 에너지 ΔG°(깔때기 구속과 해석적 표준 상태 보정, 친화도 순위에 사용 가능)"),
    "dG_standard": ("近似的標準結合自由能 ΔG°（1 M 徑向近似，不用於親和力排序）",
                    "approximate standard binding free energy ΔG° (1 M radial approximation, not for affinity ranking)",
                    "近似的な標準結合自由エネルギー ΔG°（1 M 動径近似、親和性の順位づけには使わない）",
                    "근사 표준 결합 자유 에너지 ΔG°(1 M 방사 근사, 친화도 순위에 쓰지 않음)"),
    "path_specific": ("沿拉離路徑的 PMF 井深（路徑特定，不是內在親和力）", "PMF well depth along the pulling path (path-specific, not an intrinsic affinity)",
                      "引き離し経路に沿った PMF の井戸の深さ（経路固有、固有の親和性ではない）",
                      "당김 경로를 따른 PMF 우물 깊이(경로 특이적, 고유 친화도 아님)"),
    "diagnostic_curve": ("診斷用 PMF 曲線（不比較、不排名）", "diagnostic PMF curve (not compared, not ranked)",
                         "診断用の PMF 曲線（比較も順位づけもしない）", "진단용 PMF 곡선(비교·순위 없음)"),
}


def _row(item, subject, planned, done, status, reasons=(), *, assessment=None, claim=None, claim_eligibility=None,
         requested=None, requested_eligible=None):
    """claim = the strongest claim the row may state; requested = the claim the study asked for (they differ when the
    evidence supports only a weaker statement)."""
    return {"item": item, "subject": subject, "planned": planned, "done": done, "status": status, "reasons": list(reasons),
            "execution_status": "ran" if done else "not_run", "assessment": assessment, "claim": claim,
            "claim_eligibility": claim_eligibility, "requested_claim": requested or claim,
            "requested_eligible": claim_eligibility if requested_eligible is None else requested_eligible}


def _binding_row(t: str, r: dict) -> dict:
    """The binding row is decided by the SAME claim_status record as the comparison, captions and summary."""
    from ..sampling.assessment import claim_status
    dg, path = claim_status(r, "dG_standard"), claim_status(r, "path_specific")
    rank = claim_status(r, "affinity_ranking")
    asm = {"state": path["assessment"], "source": path["assessment_source"], "thresholds_version": path["thresholds_version"],
           "evidence_ids": path["evidence_ids"], "failed": path["failed"], "unknown": path["unknown"],
           "overrides": path["overrides"]}
    if not path["executed"]:
        return _row("binding", t, True, False, "missing", ("not_run",), assessment=asm, claim="dG_standard", claim_eligibility=False)
    if rank["eligible"]:                       # D-140: funnel + analytic standard state: the only ΔG° that may rank affinities
        return _row("binding", t, True, True, "supported", assessment=asm, claim="affinity_ranking", claim_eligibility=True)
    if dg["eligible"]:                         # 1 M radial approximation: stated as approximate, not for ranking
        return _row("binding", t, True, True, "supported", ("no_funnel_standard_state",), assessment=asm, claim="dG_standard",
                    claim_eligibility=True)
    if path["eligible"]:
        reasons = ["path_specific_only"] + (["dg_withheld"] if r.get("dG_withheld") or r.get("dG_standard_kj_mol") is None else [])
        row = _row("binding", t, True, True, "limited", reasons, assessment=asm, claim="path_specific", claim_eligibility=True,
                   requested="dG_standard", requested_eligible=False)
    else:
        reasons = list(path["reasons"]) + (["dg_withheld"] if r.get("dG_withheld") else [])
        row = _row("binding", t, True, True, "limited", reasons, assessment=asm,
                   claim="diagnostic_curve", claim_eligibility=claim_status(r, "diagnostic_curve")["eligible"],
                   requested="dG_standard", requested_eligible=False)
    if r.get("dG_withheld"):
        row["detail"] = r["dG_withheld"]
    return row


def evidence_rows(wf) -> list[dict]:
    cfg, st = wf.cfg or {}, (wf.state() or {}).get("steps", {})
    md = cfg.get("md") or {}
    rows = []
    # docking
    ligs = [l.get("name") for l in cfg.get("ligands") or [] if isinstance(l, dict) and l.get("name")]
    if ligs and not md.get("membrane"):
        chosen = ((st.get("pose_selection") or {}).get("selection") or {}).get("ligands") or {}
        for n in ligs:
            ok = n in chosen
            rows.append(_row("docking", n, True, ok, "supported" if ok else "missing", () if ok else ("not_selected",)))
    # molecular dynamics, replicas
    cases = (st.get("md_cases") or {}).get("cases") or {}
    runs = (st.get("md_runs") or {}).get("runs") or {}
    from ..engine.replica_plan import configured_replicas
    planned_reps = configured_replicas(cfg)[0]          # D-131: the plan the workflow actually runs (default 3), not "or 1"
    for key in cases:
        r = runs.get(key) or {}
        done = r.get("status") == "COMPLETE"
        # D-134: COMPLETE is execution status, not a scientific claim → "ran", never "supported"
        rows.append(_row("md", key, True, done, "ran" if done else "missing", ("execution_only",) if done else ("not_run",)))
        if done:
            n = len(r.get("run_ids") or [])
            if n < planned_reps:
                rows.append(_row("replicas", key, planned_reps, n, "limited", ("fewer_replicas",)))
            elif n == 1:
                rows.append(_row("replicas", key, planned_reps, n, "limited", ("single",)))
            else:
                rows.append(_row("replicas", key, planned_reps, n, "supported"))
    # trajectory analysis and the kinetics built on it
    ana = st.get("analysis") or {}
    sums = ana.get("summaries") or {}
    for key in [k for k in cases if (runs.get(k) or {}).get("status") == "COMPLETE"]:
        s = sums.get(key)
        if not s:
            rows.append(_row("analysis", key, True, False, "missing", ("not_run",)))
            continue
        reasons = []
        if s.get("restrained_production"):
            reasons.append("restrained")
        if s.get("extended_errors"):
            reasons.append("partial_analysis")
        rows.append(_row("analysis", key, True, True, "limited" if reasons else "supported", reasons))
        ext = load_json(s.get("extended_file"), {}) if s.get("extended_file") else {}
        msm = ((ext.get("tica") or {}).get("msm") or {})
        el = msm.get("eligibility") or ((ext.get("tica") or {}).get("status") == "insufficient" and "insufficient")
        if el:
            rows.append(_row("kinetics", key, True, True, "limited", (f"msm_{el}",)))
    # comparison between systems
    comp = (ana.get("comparison") or {}).get("comparability")
    if len([k for k in cases]) > 1 and ana:
        if comp is None:
            rows.append(_row("compare", "", True, True, "limited", ("not_recorded",)))
        else:
            rows.append(_row("compare", "", True, True, "supported" if comp.get("comparable") else "limited",
                             () if comp.get("comparable") else ("not_comparable",)))
    # binding free energy
    b = cfg.get("binding") or {}
    res = (st.get("binding") or {}).get("results") or {}
    targets = set(res) | set(b.get("added") or [])
    for t in sorted(targets):
        r = res.get(t) or {}
        rows.append(_binding_row(t, r))
        if r.get("status") == "PASS":          # D-122 (F17): what the automatic refinement did, from the run's own files
            from . import auto_actions as AA
            st_, why_, done_ = AA.evidence_status(AA.summarize(AA.result_dir(r)))
            rows.append(_row("auto", t, True, done_, st_, why_))
    return rows


def summary(rows: list[dict]) -> dict:
    out = {"supported": 0, "limited": 0, "missing": 0, "ran": 0}
    for r in rows:
        out[r["status"]] = out.get(r["status"], 0) + 1
    return out
