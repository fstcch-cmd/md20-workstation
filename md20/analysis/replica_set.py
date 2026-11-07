"""Cross-replica aggregation (D-130 redo, docs/specs/replicas.md §2, evidence_driven_repair_prompt.md R1).

Pure Python + numpy: no OpenMM, mdtraj or scipy.  Input is what the per-replica analyses already wrote (metrics.json dicts);
output is one dict, schema ``md20.replica_set/1``.

Lineage (stated in the output): case -> independent MD replica -> descendants (SMD pulls, umbrella windows).  Only
independent MD runs started by ``run_replicas`` (own seed) are replicas.  Pulls and windows that share a parent
simulation are descendants: they are listed under their replica, they never raise ``n``.

Rules that make the numbers honest:
  * every observable has a declared estimand: one number per replica first (a time mean over the second half of
    production, a per-residue occupancy, a yes/no outcome), then statistics across replicas.  Frames of one trajectory
    are autocorrelated and are never treated as independent samples.
  * mean, sample SD (ddof = 1) and a Student-t 95 % CI use n = number of replicas.  n = 1 -> between-replica
    uncertainty is "unavailable" with a reason; no interval is ever invented.  n < 3 is flagged (the least n the
    spec asks for), the t interval is still computed for n = 2 and is very wide.
  * within-trajectory variability (block-average standard error of one trajectory) is reported separately from
    between-replica uncertainty and is never combined with it.
  * failed, incomplete and excluded replicas stay in the output with the reason.
  * replicas are never concatenated: event durations and persistence stay per replica (``concatenation: never``).
"""
from __future__ import annotations

import json
import math
from typing import Iterable

import numpy as np

SCHEMA = "md20.replica_set/1"
MIN_REPLICAS = 3                     # docs/specs/replicas.md §3: the least n with a sample SD and a t interval of use
UNAVAILABLE_SINGLE = "單一軌跡無法估計重複間不確定性"
UNAVAILABLE_NONE = "沒有可分析的重複，無法彙總"
# Empirical starting value (like ligand_state thresholds): replicas whose per-replica values have a coefficient of
# variation above this are labelled "divergent" (docs/specs/replicas.md §2: "各條不一致時標註").  Validate per system.
CV_DIVERGENT = 0.25
IN_POCKET_MIN_FRACTION = 0.5          # final-20 % ligand_state: (retained + changed-in-pocket) >= this -> "in pocket"
OCCUPANCY_PERSISTENT = 0.5            # a residue "persists" in a replica when its contact occupancy is >= this
MAX_RESIDUES_LISTED = 30

LINEAGE = {
    "levels": ["case", "replica", "descendant"],
    "replica_definition": "independent MD run started by run_replicas (own seed); the only unit counted in n",
    "descendants_note": "SMD pulls and umbrella windows share one parent replica: listed under it, never counted as replicas",
    "descendants_note_zh": "同一條母軌跡拉出的 SMD 拉動與傘狀採樣視窗是後代，不是獨立重複，不增加重複數。",
}

# observable id -> (unit, series key in metrics.json); a time series becomes one number per replica (second-half mean)
SYSTEM_SERIES = {"rmsd_backbone_A": "Å", "rg_protein_A": "Å"}
LIGAND_SERIES = {"rmsd_in_pocket_A": "Å", "contact_residues": "residues", "polar_contacts": "pairs",
                 "com_distance_to_pocket_A": "Å"}

# ------------------------------------------------------------------------------------------------ Student t
# two-sided 95 % critical values t(0.975, df)
_T975 = {1: 12.7062, 2: 4.3027, 3: 3.1824, 4: 2.7764, 5: 2.5706, 6: 2.4469, 7: 2.3646, 8: 2.3060, 9: 2.2622, 10: 2.2281,
         11: 2.2010, 12: 2.1788, 13: 2.1604, 14: 2.1448, 15: 2.1314, 16: 2.1199, 17: 2.1098, 18: 2.1009, 19: 2.0930,
         20: 2.0860, 21: 2.0796, 22: 2.0739, 23: 2.0687, 24: 2.0639, 25: 2.0595, 26: 2.0555, 27: 2.0518, 28: 2.0484,
         29: 2.0452, 30: 2.0423, 40: 2.0211, 50: 2.0086, 60: 2.0003, 80: 1.9901, 100: 1.9840, 120: 1.9799}
_T975_INF = 1.95996


def t_critical_975(df: int) -> float:
    """t(0.975, df) from a table (df 1..30 exact to 4 decimals; larger df interpolated linearly in 1/df, which is
    accurate to ~1e-3).  scipy is not a dependency."""
    df = int(df)
    if df < 1:
        raise ValueError("df must be >= 1")
    if df in _T975:
        return _T975[df]
    ks = sorted(_T975)
    if df > ks[-1]:
        lo, hi, vlo, vhi = ks[-1], None, _T975[ks[-1]], _T975_INF
        x = (1 / df) / (1 / lo)
        return vhi + (vlo - vhi) * x
    lo = max(k for k in ks if k < df)
    hi = min(k for k in ks if k > df)
    w = (1 / df - 1 / hi) / (1 / lo - 1 / hi)
    return _T975[hi] + (_T975[lo] - _T975[hi]) * w


# ------------------------------------------------------------------------------------------------ statistics
def _finite(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def between_replica_stats(items: Iterable[tuple[str, float]]) -> dict:
    """Mean, sample SD (ddof = 1), SEM and Student-t 95 % CI of one value per replica; ``items`` = (run_id, value).
    Values stay attached to their run_id.  n = 1 -> SD and CI are None and ``between_replica`` says why."""
    per = [(str(rid), _finite(v)) for rid, v in items]
    skipped = [rid for rid, v in per if v is None]
    per = [(rid, v) for rid, v in per if v is not None]
    n = len(per)
    out: dict = {"n": n, "per_replica": [{"run_id": rid, "value": v} for rid, v in per], "missing_run_ids": skipped,
                 "mean": None, "sd": None, "sem": None, "ci95": None, "min": None, "max": None, "cv": None,
                 "divergent": None, "below_recommended_n": n < MIN_REPLICAS}
    if n == 0:
        out["between_replica"] = {"status": "unavailable", "reason": UNAVAILABLE_NONE}
        return out
    vals = np.array([v for _, v in per], float)
    out["mean"] = float(vals.mean())
    out["min"], out["max"] = float(vals.min()), float(vals.max())
    if n == 1:
        out["between_replica"] = {"status": "unavailable", "reason": UNAVAILABLE_SINGLE}
        return out
    sd = float(vals.std(ddof=1))
    sem = sd / math.sqrt(n)
    t = t_critical_975(n - 1)
    out.update({"sd": sd, "sem": sem,
                "ci95": {"low": out["mean"] - t * sem, "high": out["mean"] + t * sem, "t": t, "df": n - 1,
                         "half_width": t * sem, "method": "Student-t on per-replica values, n-1 df"}})
    if abs(out["mean"]) > 1e-12:
        out["cv"] = sd / abs(out["mean"])
        out["divergent"] = bool(out["cv"] > CV_DIVERGENT)
    else:
        out["divergent"] = None
    out["between_replica"] = {"status": "ok", "reason": ("n < %d：區間很寬，只供參考" % MIN_REPLICAS) if n < MIN_REPLICAS else ""}
    return out


def binary_summary(items: Iterable[tuple[str, bool | None]]) -> dict:
    """k of n replicas with the outcome.  ``None`` = unknown for that replica (not counted in n, listed)."""
    per = [(str(rid), v) for rid, v in items]
    known = [(rid, bool(v)) for rid, v in per if v is not None]
    unknown = [rid for rid, v in per if v is None]
    k, n = sum(1 for _, v in known if v), len(known)
    return {"k": k, "n": n, "fraction": (k / n) if n else None, "n_unknown": len(unknown), "unknown_run_ids": unknown,
            "per_replica": [{"run_id": rid, "value": v} for rid, v in known],
            "consistent": (k in (0, n)) if n else None,
            "between_replica": ({"status": "unavailable", "reason": UNAVAILABLE_SINGLE} if n == 1 else
                                {"status": "unavailable", "reason": UNAVAILABLE_NONE} if n == 0 else
                                {"status": "ok", "reason": ""})}


def _second_half(y) -> np.ndarray:
    a = np.asarray(y, float)
    a = a[np.isfinite(a)]
    return a[len(a) // 2:] if len(a) else a


def _block_se(y) -> dict:
    """Within-trajectory standard error from block averages (extended.block_average): this describes ONE trajectory
    and is not the uncertainty between replicas."""
    from .extended import block_average
    ba = block_average(y, 5)
    if not ba:
        return {"status": "unavailable", "reason": "second-half series shorter than 10 frames"}
    return {"status": "ok", "block_se": ba["sem"], "n_blocks": 5}


# ------------------------------------------------------------------------------------------------ per replica
def eligible(rep: dict) -> tuple[bool, str]:
    """(analysed?, reason when not).  A replica is analysed only when it finished and its analysis wrote metrics."""
    st = rep.get("status")
    if rep.get("excluded_reason"):
        return False, str(rep["excluded_reason"])
    if st not in (None, "COMPLETE", "PASS"):
        return False, rep.get("reason") or f"重複的狀態是 {st}，未完成，不納入彙總"
    if rep.get("analysis_status") not in (None, "PASS"):
        return False, rep.get("reason") or f"這條的分析狀態是 {rep.get('analysis_status')}，不納入彙總"
    if not rep.get("metrics"):
        return False, rep.get("reason") or "沒有分析指標（metrics.json），不納入彙總"
    return True, ""


def _series_value(m: dict, ligand: str | None, key: str) -> list | None:
    src = (m.get("ligands") or {}).get(ligand) if ligand else m
    y = (src or {}).get(key)
    return y if isinstance(y, (list, tuple)) and len(y) else None


def _in_pocket(state: dict | None) -> bool | None:
    fr = (state or {}).get("fraction_final_20pct")
    if not isinstance(fr, dict):
        return None
    inside = float(fr.get("pose_retained", 0)) + float(fr.get("pose_changed_in_pocket", 0))
    if inside >= IN_POCKET_MIN_FRACTION:
        return True
    if float(fr.get("escape_evidence", 0)) >= IN_POCKET_MIN_FRACTION:
        return False
    return None                                  # contacts lost but no clear escape: unknown, never guessed


def _obs(stats: dict, estimand: str, estimand_zh: str, unit: str, within: list[dict]) -> dict:
    return {"estimand": estimand, "estimand_zh": estimand_zh, "unit": unit, **stats,
            "within_trajectory": {"method": "block-average standard error (5 blocks) of the second half of each trajectory; "
                                            "describes one trajectory only, not between-replica uncertainty",
                                  "per_replica": within}}


def _series_observable(reps: list[dict], ligand: str | None, key: str, unit: str) -> dict | None:
    items, within = [], []
    for r in reps:
        y = _series_value(r["metrics"], ligand, key)
        if y is None:
            continue
        h = _second_half(y)
        if not len(h):
            continue
        items.append((r["run_id"], float(h.mean())))
        within.append({"run_id": r["run_id"], **_block_se(h)})
    if not items:
        return None
    return _obs(between_replica_stats(items),
                f"per-replica mean of {key} over the second half of production; then mean/SD/t-CI across replicas",
                f"每條重複先取後半段 {key} 的時間平均，再跨重複算平均、標準差與 t 分布信賴區間", unit, within)


def _per_residue_rmsf(reps: list[dict]) -> dict | None:
    have = [r for r in reps if r["metrics"].get("rmsf_ca_A") and r["metrics"].get("rmsf_residues")]
    if not have:
        return None
    common = list(have[0]["metrics"]["rmsf_residues"])
    mismatch = []
    for r in have[1:]:
        labs = list(r["metrics"]["rmsf_residues"])
        if labs != common:
            mismatch.append(r["run_id"])
            common = [x for x in common if x in set(labs)]
    cols, ids = [], []
    for r in have:
        pos = {lab: i for i, lab in enumerate(r["metrics"]["rmsf_residues"])}
        y = r["metrics"]["rmsf_ca_A"]
        cols.append([float(y[pos[lab]]) for lab in common])
        ids.append(r["run_id"])
    M = np.array(cols, float)                                  # replicas x residues
    n = M.shape[0]
    out = {"estimand": "Cα RMSF per residue of each replica (whole production); mean/SD/t-CI across replicas per residue",
           "estimand_zh": "每條重複各自的 Cα RMSF（整段正式模擬），逐殘基跨重複算平均、標準差與信賴區間",
           "unit": "Å", "n": n, "residues": common, "mean": M.mean(0).round(4).tolist(),
           "per_replica": {rid: M[i].round(4).tolist() for i, rid in enumerate(ids)},
           "residue_mismatch_run_ids": mismatch, "sd": None, "ci95_low": None, "ci95_high": None,
           "between_replica": {"status": "unavailable", "reason": UNAVAILABLE_SINGLE}}
    if n >= 2:
        sd = M.std(0, ddof=1)
        half = t_critical_975(n - 1) * sd / math.sqrt(n)
        out.update({"sd": sd.round(4).tolist(), "ci95_low": (M.mean(0) - half).round(4).tolist(),
                    "ci95_high": (M.mean(0) + half).round(4).tolist(),
                    "between_replica": {"status": "ok", "reason": ("n < %d：區間很寬，只供參考" % MIN_REPLICAS) if n < MIN_REPLICAS else ""}})
    return out


def _contact_occupancy(reps: list[dict], ligand: str) -> dict | None:
    """Per residue: fraction of frames in contact in each replica; a residue a replica never touched has occupancy 0
    there (the per-replica table lists only residues with at least one contact)."""
    have = [r for r in reps if (r["metrics"].get("ligands") or {}).get(ligand, {}).get("contact_frequency") is not None]
    if not have:
        return None
    rows: dict[str, dict[str, float]] = {}
    for r in have:
        lg = r["metrics"]["ligands"][ligand]
        ids = lg.get("contact_residue_ids") or {}
        for lab, v in (lg.get("contact_frequency") or {}).items():
            rows.setdefault(str(ids.get(lab, lab)), {})[r["run_id"]] = float(v)
    labels = {}
    for r in have:
        for lab, key in ((r["metrics"]["ligands"][ligand].get("contact_residue_ids")) or {}).items():
            labels.setdefault(str(key), lab)
    n = len(have)
    out_rows = []
    for key, per in rows.items():
        items = [(r["run_id"], per.get(r["run_id"], 0.0)) for r in have]
        st = between_replica_stats(items)
        persistent = binary_summary([(rid, v >= OCCUPANCY_PERSISTENT) for rid, v in items])
        out_rows.append({"residue": labels.get(key, key), "residue_key": key, "mean": st["mean"], "sd": st["sd"],
                         "ci95": st["ci95"], "per_replica": st["per_replica"],
                         "persistent_k": persistent["k"], "persistent_n": persistent["n"]})
    out_rows.sort(key=lambda x: -(x["mean"] or 0))
    return {"estimand": "per-replica fraction of frames with the residue within 4 Å of the ligand; mean/SD/t-CI across replicas "
                        f"(absent in a replica = 0); persistent = occupancy >= {OCCUPANCY_PERSISTENT:g} in k of n replicas",
            "estimand_zh": f"每條重複各自的接觸占有率（有接觸的幀比例；某條完全沒碰到記 0），再跨重複彙總；"
                           f"「持續」＝占有率 ≥ {OCCUPANCY_PERSISTENT:g} 的重複數 k／n",
            "unit": "fraction of frames", "n": n, "residues": out_rows[:MAX_RESIDUES_LISTED],
            "n_residues_total": len(out_rows)}


# ------------------------------------------------------------------------------------------------ the aggregate
def aggregate_replica_set(replicas: list[dict], *, system: str = "", n_requested: int | None = None) -> dict:
    """``replicas`` = one dict per run of this system, in replica order::

        {"run_id", "replica_index"?, "status"?, "reason"?, "excluded_reason"?, "analysis_status"?,
         "metrics": metrics.json content or None, "descendants"?: {"pulls": n, "windows": m}}

    Returns the ``md20.replica_set/1`` dict.  Never raises on missing data: what cannot be computed is "unavailable"
    with a reason."""
    reps_all, analysed, excluded = [], [], []
    for i, r in enumerate(replicas or []):
        ok, why = eligible(r)
        entry = {"run_id": str(r.get("run_id")), "replica_index": r.get("replica_index", i), "status": r.get("status"),
                 "analysed": ok, "reason": why, "descendants": dict(r.get("descendants") or {}),
                 "analysis_manifest": r.get("analysis_manifest"), "extended_file": r.get("extended_file")}
        reps_all.append(entry)
        if ok:
            analysed.append({"run_id": entry["run_id"], "metrics": r["metrics"]})
        else:
            excluded.append({"run_id": entry["run_id"], "status": r.get("status"), "reason": why})
    n = len(analysed)
    out: dict = {"schema": SCHEMA, "system": system, "lineage": LINEAGE, "concatenation": "never",
                 "concatenation_note": "replica boundaries are never joined: event durations, persistence and transitions "
                                       "are computed inside one replica and only their per-replica results are combined",
                 "n_requested": n_requested, "n_listed": len(reps_all), "n_analysed": n, "min_recommended": MIN_REPLICAS,
                 "replicas": reps_all, "excluded": excluded, "observables": {}, "ligands": {}, "per_residue": {}}
    flags: list[str] = []
    if n == 0:
        flags.append("no_analysed_replica")
    elif n == 1:
        flags.append("single_replica")
    elif n < MIN_REPLICAS:
        flags.append("below_recommended_n")
    if excluded:
        flags.append("excluded_replicas")
    if n_requested and n_requested > len(reps_all):
        flags.append("fewer_replicas_than_requested")
    out["between_replica"] = ({"status": "unavailable", "reason": UNAVAILABLE_NONE} if n == 0 else
                              {"status": "unavailable", "reason": UNAVAILABLE_SINGLE} if n == 1 else
                              {"status": "ok", "reason": ""})
    for key, unit in SYSTEM_SERIES.items():
        o = _series_observable(analysed, None, key, unit)
        if o:
            out["observables"][key] = o
            if o.get("divergent"):
                flags.append(f"divergent:{key}")
    rm = _per_residue_rmsf(analysed)
    if rm:
        out["per_residue"]["rmsf_ca_A"] = rm
    names = sorted({ln for r in analysed for ln in (r["metrics"].get("ligands") or {})})
    for ln in names:
        reps_l = [r for r in analysed if ln in (r["metrics"].get("ligands") or {})]
        lig: dict = {"n": len(reps_l), "observables": {}}
        for key, unit in LIGAND_SERIES.items():
            o = _series_observable(reps_l, ln, key, unit)
            if o:
                lig["observables"][key] = o
                if o.get("divergent"):
                    flags.append(f"divergent:{ln}:{key}")
        sb = [(r["run_id"], r["metrics"]["ligands"][ln].get("stays_bound")) for r in reps_l]
        ip = [(r["run_id"], _in_pocket(r["metrics"]["ligands"][ln].get("ligand_state"))) for r in reps_l]
        lig["stays_bound"] = {"estimand": "legacy flag per replica: mean pocket RMSD of the last 20 % of frames < 3 Å; k of n replicas",
                              "estimand_zh": "每條重複的舊旗標（最後 20 % 幀的口袋 RMSD 平均 < 3 Å），報告 n 條中 k 條",
                              **binary_summary(sb)}
        lig["in_pocket_final20"] = {"estimand": "per replica: contacting states (retained + changed in pocket) hold >= "
                                                f"{IN_POCKET_MIN_FRACTION:g} of the final 20 % of frames; k of n replicas "
                                                "(neither in pocket nor clear escape = unknown, not counted)",
                                    "estimand_zh": f"每條重複：最後 20 % 幀中仍有接觸的狀態占 ≥ {IN_POCKET_MIN_FRACTION:g} 視為留在口袋；"
                                                   "n 條中 k 條（既非留下也無明確離開 → 未知，不計入 n）",
                                    **binary_summary(ip)}
        for b in ("stays_bound", "in_pocket_final20"):
            if lig[b]["consistent"] is False:
                flags.append(f"inconsistent:{ln}:{b}")
        co = _contact_occupancy(reps_l, ln)
        if co:
            lig["contact_occupancy"] = co
        out["ligands"][ln] = lig
    out["flags"] = flags
    return out


# ------------------------------------------------------------------------------------------------ comparability input
def merge_replica_conditions(conds: dict[str, dict]) -> tuple[dict, dict]:
    """``conds`` = {run_id: conditions(run.json, build manifest)} of the replicas of ONE system ->
    (merged, within).  ``merged`` is the system's view for cross-system comparison: a field all replicas agree on keeps
    its value; a field unknown in any replica is None (unknown, never assumed); a field the replicas disagree on becomes a
    marker string, which differs from every other system's value so the comparison is blocked, not silently resolved.
    ``within`` = the comparability verdict among the replicas themselves."""
    from .common_basis import comparability
    if not conds:
        return {}, {"comparable": False, "differences": [], "unknown": ["no_replica"]}
    rows = list(conds.values())
    fields = sorted({f for c in rows for f in c})
    merged = {}
    for f in fields:
        vals = [c.get(f) for c in rows]
        if any(v is None for v in vals):
            merged[f] = None
        elif all(v == vals[0] for v in vals[1:]):
            merged[f] = vals[0]
        elif f == "production_ps":
            nums = [float(v) for v in vals if isinstance(v, (int, float))]
            ok = len(nums) == len(vals) and min(nums) > 0 and max(nums) / min(nums) <= 1.25
            merged[f] = vals[0] if ok else None
        else:
            distinct = sorted({json.dumps(v, sort_keys=True, ensure_ascii=False, default=str) for v in vals})
            merged[f] = "replicas differ: " + " | ".join(distinct)
    within = comparability(conds) if len(conds) > 1 else {"comparable": True, "differences": [], "unknown": []}
    return merged, within


def headline_lines(agg: dict) -> list[str]:
    """Plain Chinese one-liners for the DecisionLog / logs (the report builds its own four-language text)."""
    n = agg.get("n_analysed", 0)
    out = [f"{agg.get('system') or '系統'}：{n} 條獨立重複納入彙總（列出 {agg.get('n_listed', 0)} 條）"]
    if n == 1:
        out.append(UNAVAILABLE_SINGLE)
    for x in agg.get("excluded") or []:
        out.append(f"排除 {x['run_id']}：{x['reason']}")
    return out
