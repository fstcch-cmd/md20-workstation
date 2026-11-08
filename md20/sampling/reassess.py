"""D-143: re-assess stored umbrella-sampling results with the current `assess_pmf` and write the assessment back.

The D-134 open item "re-assess and write back".  A binding result written before D-96 has no stored assessment, so every
consumer shows its diagnostics but treats the result as not eligible ("awaiting reanalysis").  Here the assessment is
recomputed from the PMF fields that the run stored in each replica's `binding_manifest.json` (no new sampling, no
simulation) and written back next to the result:

  * `<binding dir>/binding_manifest.json`  →  `result.assessment`   (one per replica)
  * `<workflow>/state.json`                →  `steps.binding.results[target].assessment`  (replicas combined by the
    workflow's own rule: a conclusion is eligible only if every replica supports it)

Rules
  * the written assessment carries `provenance = {source: "reassessed", thresholds_version, original_version, at, ...}`;
  * the original file is never overwritten without a backup copy (`<file>.pre-reassess-<UTC stamp>`, never replaced);
  * a diagnostic whose field the run never stored stays `unknown` and keeps the result not eligible: nothing is guessed;
  * eligibility comes from `assess_pmf` alone.  A legacy result becomes eligible only when every required diagnostic passes
    with the current thresholds, and a result whose diagnostics fail is stored as failing, not as "legacy";
  * a result that already has an assessment of the current thresholds version is left alone (idempotent), and a stored
    non-legacy assessment of an older version is re-assessed only on request (`include_outdated`).

Pure Python + numpy; does not edit `assessment.py` or `binding.py`.
"""
from __future__ import annotations

import copy
import shutil
from pathlib import Path
from types import SimpleNamespace

from ..util import atomic_write_json, load_json, now_iso
from .assessment import THRESHOLDS_VERSION, assess_pmf

SOURCE = "reassessed"
BACKUP_TAG = "pre-reassess"


# ------------------------------------------------------------------------------------------------ files
def replica_manifests(wf_dir: Path | str, target: str) -> list[Path]:
    """Every replica's `binding_manifest.json` of one target: the target folder itself (single run, or the first run kept in
    place when more were added) and rep1, rep2 … (the layout of `workflow.binding_replica_dir`)."""
    tdir = Path(wf_dir) / "binding" / target.replace(":", "_")
    first = [tdir / "binding_manifest.json"] if (tdir / "binding_manifest.json").is_file() else []

    def idx(p: Path) -> int:
        n = p.parent.name[3:]
        return int(n) if n.isdigit() else 0
    reps = sorted((p for p in tdir.glob("rep*/binding_manifest.json")), key=idx)
    return first + reps


def backup_file(path: Path | str, stamp: str) -> Path:
    """Copy `path` to `<name>.pre-reassess-<stamp>` (a counter is added instead of ever replacing an earlier backup)."""
    path = Path(path)
    tag = stamp.replace(":", "").replace("-", "")
    dest = path.with_name(f"{path.name}.{BACKUP_TAG}-{tag}")
    n = 1
    while dest.exists():
        n += 1
        dest = path.with_name(f"{path.name}.{BACKUP_TAG}-{tag}-{n}")
    shutil.copy2(path, dest)
    return dest


# ------------------------------------------------------------------------------------------------ decide + compute (pure)
def needs_reassessment(assessment: dict | None, *, include_outdated: bool = False) -> tuple[bool, str]:
    """(do it, why / why not).  Legacy = no stored assessment, or one marked legacy."""
    if not assessment:
        return True, "legacy_no_assessment"
    if assessment.get("legacy"):
        return True, "legacy_marked"
    if assessment.get("thresholds_version") != THRESHOLDS_VERSION:
        if include_outdated:
            return True, "outdated_thresholds"
        return False, "outdated_thresholds_not_requested"
    return False, "current"


def provenance(original: dict | None, *, at: str, backups: list[str] | None = None) -> dict:
    return {"source": SOURCE, "thresholds_version": THRESHOLDS_VERSION,
            "original_version": (original or {}).get("thresholds_version"),
            "original_was_legacy": (not original) or bool(original.get("legacy")),
            "original_eligibility": copy.deepcopy((original or {}).get("eligibility")),
            "at": at, "by": "md20 binding reassess",
            "basis": "stored PMF fields of each replica's binding_manifest.json; no new sampling",
            "backups": list(backups or [])}


def reassess_one_pmf(result: dict) -> dict:
    """The current `assess_pmf` of one replica's stored result dict (`BindingResult.to_dict()` form)."""
    pmf = result.get("pmf") or {}
    return assess_pmf(pmf, dG_withheld=pmf.get("dG_withheld"), has_dG=result.get("dG_standard_kj_mol") is not None)


def reassess_target(result: dict, replica_results: list[dict], *, original: dict | None = None, at: str | None = None) -> dict:
    """The new workflow-level assessment of one target from the stored replica results, with provenance.  `result` is the
    workflow's result for the target (its ΔG° after the tier rule decides whether ΔG°-based eligibility survives)."""
    from ..workflow import Workflow            # the same combination rule the workflow applies when it computes a result
    reps = [SimpleNamespace(assessment=reassess_one_pmf(r), pmf=r.get("pmf") or {},
                            dG_standard_kj_mol=r.get("dG_standard_kj_mol")) for r in replica_results]
    a = Workflow._binding_assessment(reps, result.get("dG_standard_kj_mol"), result.get("dG_withheld"))
    a = copy.deepcopy(a)
    for k in ("legacy", "reassessed_from_manifest", "eligibility_if_stored"):
        a.pop(k, None)
    a["provenance"] = provenance(original, at=at or now_iso())
    return a


# ------------------------------------------------------------------------------------------------ the workflow-level job
def reassess_workflow(wf_dir: Path | str, *, targets: list[str] | None = None, include_outdated: bool = False,
                      dry_run: bool = False, wf=None, at: str | None = None, kind: str = "human") -> dict:
    """Re-assess the finished binding targets of one workflow and write the assessments back.

    Returns a JSON-able report: per target `status` (reassessed | would_reassess | skipped | error), the eligibility before
    and after, which diagnostics are still unknown, and the backup files.  `dry_run` writes nothing.  `wf` (a Workflow) lets
    the comparison be recomputed from the new assessments; without it the stored comparison is flagged stale."""
    wf_dir = Path(wf_dir)
    at = at or now_iso()
    state_path = wf_dir / "state.json"
    st = load_json(state_path, {"steps": {}})
    b = (st.get("steps") or {}).get("binding") or {}
    results = b.get("results") or {}
    rep = {"workflow_dir": str(wf_dir), "thresholds_version": THRESHOLDS_VERSION, "at": at, "dry_run": bool(dry_run),
           "targets": {}, "changed": [], "comparison": None, "state_backup": None}
    todo: dict[str, dict] = {}
    for name, res in results.items():
        if targets and name not in targets:
            continue
        if not isinstance(res, dict) or res.get("status") != "PASS":
            rep["targets"][name] = {"status": "skipped", "why": "not_finished"}
            continue
        orig = res.get("assessment")
        go, why = needs_reassessment(orig, include_outdated=include_outdated)
        if not go:
            rep["targets"][name] = {"status": "skipped", "why": why}
            continue
        paths = replica_manifests(wf_dir, name)
        if not paths:
            rep["targets"][name] = {"status": "skipped", "why": "no_stored_pmf"}
            continue
        reps = []
        for p in paths:
            r = (load_json(p, {}) or {}).get("result") or {}
            if not r.get("pmf"):
                reps = []
                break
            reps.append(r)
        if not reps:
            rep["targets"][name] = {"status": "skipped", "why": "no_stored_pmf"}
            continue
        todo[name] = {"orig": orig, "why": why, "paths": paths, "replicas": reps}
    for name in list(targets or []):
        if name not in results and name not in rep["targets"]:
            rep["targets"][name] = {"status": "skipped", "why": "unknown_target"}
    new_assessments: dict[str, dict] = {}
    for name, t in todo.items():
        try:
            a = reassess_target(results[name], t["replicas"], original=t["orig"], at=at)
        except Exception as exc:  # noqa: BLE001 - one target failing must not hide the others
            rep["targets"][name] = {"status": "error", "why": f"{type(exc).__name__}: {exc}"}
            continue
        new_assessments[name] = a
        before = (t["orig"] or {}).get("eligibility")
        if not before:                       # what every consumer showed until now: the legacy view of the same result
            from .assessment import resolve_assessment
            before = resolve_assessment(results[name], t["replicas"][0].get("pmf"))[0].get("eligibility") or {}
        rep["targets"][name] = {"status": "would_reassess" if dry_run else "reassessed", "why": t["why"],
                                "eligibility_before": before, "eligibility_after": a.get("eligibility"),
                                "unknown": a.get("unknown"), "failed": a.get("failed"),
                                "became_eligible": [k for k, v in (a.get("eligibility") or {}).items()
                                                    if v and not before.get(k)],
                                "replicas": len(t["replicas"]), "backups": []}
    if dry_run or not new_assessments:
        return rep
    # ---- write back: replica manifests first, the workflow state (what every consumer reads) last
    for name, a in new_assessments.items():
        t = todo[name]
        backups = rep["targets"][name]["backups"]
        for p, r in zip(t["paths"], t["replicas"]):
            man = load_json(p, {}) or {}
            bk = backup_file(p, at)
            backups.append(str(bk))
            man.setdefault("result", {})["assessment"] = {**reassess_one_pmf(r), "provenance": provenance(
                (r or {}).get("assessment"), at=at, backups=[str(bk)])}
            atomic_write_json(man, p, backup=False)
    st = load_json(state_path, {"steps": {}})
    bk_state = backup_file(state_path, at)
    rep["state_backup"] = str(bk_state)
    bres = st["steps"]["binding"]["results"]
    for name, a in new_assessments.items():
        a["provenance"]["backups"] = rep["targets"][name]["backups"] + [str(bk_state)]
        bres[name]["assessment"] = a
        rep["changed"].append(name)
    comp = _recompute_comparison(wf, bres)
    if comp is not None:
        st["steps"]["binding"]["comparison"] = comp
        rep["comparison"] = "recomputed"
    else:
        st["steps"]["binding"]["comparison_stale"] = {"since": at, "why": "assessments were rewritten; rebuild the comparison/report"}
        rep["comparison"] = "stale"
    st["steps"]["binding"].setdefault("reassessed", []).append({"at": at, "targets": list(new_assessments),
                                                                "thresholds_version": THRESHOLDS_VERSION})
    atomic_write_json(st, state_path)
    _record_decision(wf, rep, kind)
    return rep


def _recompute_comparison(wf, results: dict) -> dict | None:
    """The comparison of the finished targets from their (new) assessments, exactly as `Workflow.binding` builds it.  None
    when it cannot be rebuilt here (no Workflow, or its cases are missing); the caller then flags the stored one as stale."""
    if wf is None:
        return None
    try:
        from .multi import compare_binding, cooperativity
        state = wf.state()["steps"]
        built = (state.get("md_cases") or {}).get("cases") or {}
        runs = (state.get("md_runs") or {}).get("runs") or {}
        _targets, contexts = wf._binding_targets(runs, built)
        ctx = {k: v for k, v in contexts.items() if v}
        comparison = compare_binding(results, contexts=ctx)
        comparison["cooperativity"] = cooperativity(results, ctx)
        return comparison
    except Exception:  # noqa: BLE001
        return None


def _record_decision(wf, rep: dict, kind: str) -> None:
    if wf is None:
        return
    try:
        for name in rep["changed"]:
            t = rep["targets"][name]
            now = [k for k in t.get("became_eligible") or []]
            wf.dec.record("binding.reassess", name, f"reassessed ({t['why']})",
                          f"{name} 的結合結果用目前的評估規則（門檻版本 {THRESHOLDS_VERSION}）由已儲存的 PMF 欄位重新評估並寫回；沒有新的取樣。"
                          + (f"現在成立的結論：{', '.join(now)}。" if now else "沒有新增成立的結論。")
                          + (f"仍為未知的診斷：{', '.join(t.get('unknown') or [])}（缺資料，不推測）。" if t.get("unknown") else "")
                          + "原檔已備份（*.pre-reassess-*），評估內附來源與時間。", kind=kind, backups=t.get("backups"))
    except Exception:  # noqa: BLE001 - the record is a convenience; the files already hold the provenance
        pass


# ------------------------------------------------------------------------------------------------ text
def report_lines(rep: dict) -> list[str]:
    """Plain Chinese lines for the command line (the command line stays Chinese, docs/specs/writing_style.md §3)."""
    out = [f"重新評估（門檻版本 {rep['thresholds_version']}，{'試算，沒有寫任何檔案' if rep['dry_run'] else '已寫回'}）"]
    why = {"not_finished": "結合計算尚未完成", "current": "已經是目前版本的評估", "no_stored_pmf": "找不到已儲存的 PMF 欄位",
           "outdated_thresholds_not_requested": "舊版門檻的評估（要重評請加 --include-outdated）", "unknown_target": "沒有這個結合目標"}
    for name, t in rep["targets"].items():
        if t["status"] in ("reassessed", "would_reassess"):
            gained = "、".join(t.get("became_eligible") or []) or "無"
            tail = (f"；仍未知：{'、'.join(t['unknown'])}" if t.get("unknown") else "") + \
                   (f"；不通過：{'、'.join(t['failed'])}" if t.get("failed") else "")
            out.append(f"  {name}：{'會重新評估' if t['status'] == 'would_reassess' else '已重新評估'}，新增成立的結論：{gained}{tail}")
        elif t["status"] == "error":
            out.append(f"  {name}：失敗（{t['why']}）")
        else:
            out.append(f"  {name}：略過（{why.get(t['why'], t['why'])}）")
    if rep.get("state_backup"):
        out.append(f"  原狀態檔備份：{rep['state_backup']}")
    if rep.get("comparison") == "stale":
        out.append("  比較表沒有重算，請重新整理報告。")
    elif rep.get("changed"):
        out.append("  報告尚未重建，請在 GUI 重新整理報告或重新執行流程。")
    return out
