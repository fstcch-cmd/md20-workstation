"""D-108 (F01): research design and evidence coverage — what was planned, what actually ran, and what the evidence can
support, one row per item, so a reader sees the gaps before the results.

status: "supported" (ran and passed its checks) | "limited" (ran; a stated limitation narrows what it shows) |
        "missing" (planned, not run or failed) — never "supported" by default: a field that cannot be read is "limited"
        with the reason "not recorded".
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
    "not_selected": ("沒有選出姿勢", "no pose selected", "ポーズが選ばれていない", "포즈가 선택되지 않음"),
}


def _row(item, subject, planned, done, status, reasons=()):
    return {"item": item, "subject": subject, "planned": planned, "done": done, "status": status, "reasons": list(reasons)}


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
    planned_reps = int(md.get("replicas") or 1)
    for key in cases:
        r = runs.get(key) or {}
        done = r.get("status") == "COMPLETE"
        rows.append(_row("md", key, True, done, "supported" if done else "missing", () if done else ("not_run",)))
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
        if r.get("status") != "PASS":
            rows.append(_row("binding", t, True, False, "missing", ("not_run",)))
        elif r.get("dG_standard_kj_mol") is None:
            rows.append(_row("binding", t, True, True, "limited", ("dg_withheld",), ))
            rows[-1]["detail"] = r.get("dG_withheld")
        else:
            rows.append(_row("binding", t, True, True, "supported"))
    return rows


def summary(rows: list[dict]) -> dict:
    out = {"supported": 0, "limited": 0, "missing": 0}
    for r in rows:
        out[r["status"]] = out.get(r["status"], 0) + 1
    return out
