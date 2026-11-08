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
CV_DIVERGENT = 0.25   # D-144: a caution, not a test (n=3: fires 50 % at true CV 0.30, 7 % at 0.15; thresholds_calibration.md)
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
NO_CV_REASON = "差值型、帶正負號或比例型的量不適用 CV；看信賴區間與正負號一致的重複數 k／n"
SCHEMA_REVISION = "1.1"             # D-142: dssp, dccm, hydration, basins, clusters, tica_msm, membrane aggregated per replica


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


def between_replica_stats(items: Iterable[tuple[str, float]], *, cv: bool = True, cv_reason: str = "") -> dict:
    """Mean, sample SD (ddof = 1), SEM and Student-t 95 % CI of one value per replica; ``items`` = (run_id, value).
    Values stay attached to their run_id.  n = 1 -> SD and CI are None and ``between_replica`` says why.
    ``cv=False`` (D-144, D-142): difference-type, signed or proportion observables have no meaningful coefficient of
    variation; ``divergent`` stays None and ``divergent_reason`` says so (use the CI and sign consistency instead)."""
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
    if not cv:
        out["divergent_reason"] = cv_reason or NO_CV_REASON
    if n == 1:
        out["between_replica"] = {"status": "unavailable", "reason": UNAVAILABLE_SINGLE}
        return out
    sd = float(vals.std(ddof=1))
    sem = sd / math.sqrt(n)
    t = t_critical_975(n - 1)
    out.update({"sd": sd, "sem": sem,
                "ci95": {"low": out["mean"] - t * sem, "high": out["mean"] + t * sem, "t": t, "df": n - 1,
                         "half_width": t * sem, "method": "Student-t on per-replica values, n-1 df"}})
    if not cv:
        out["divergent"], out["divergent_reason"] = None, cv_reason or NO_CV_REASON
    elif abs(out["mean"]) > 1e-12:
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


# ================================================================================================ D-142
# Observables that used only the representative replica before (docs/specs/replicas.md §2, §7).  Input per replica:
# ``extended`` (extended.json dict), ``membrane`` (membrane_metrics.json dict or metrics["membrane"]), ``membrane_report``
# (analysis/membrane_report.json).  Missing fields give {"status": "unavailable", "reason": ...}; nothing is invented.
# Difference-type, signed and proportion quantities carry no CV / "divergent" label (D-144): the CI and the number of
# replicas with the same sign (k of n) are used instead.
HYDRATION_MATCH_NM = 0.2              # two water sites of different replicas are "the same site" within this distance
HYDRATION_MIN_REPLICAS_REPRODUCED = 2  # a site seen in only one replica is "not reproduced"
DCCM_LONG_RANGE_SEP = 5               # residue index separation of a "long-range" pair
DCCM_STRONG = 0.5                     # |mean correlation| of a strong pair
DCCM_REPLICA_MIN = 0.3                # a strong pair is "reproducible" if every replica has |C| >= this with the same sign
DCCM_MAX_STORED = 500                 # larger matrices are summarised, not stored element by element
BASIN_RANGE_INCONSISTENT = 0.25       # empirical starting value: a basin whose share spans more than this across replicas
BASIN_MATCH_BINS = 2.0                # basins of different replicas match within this many landscape bins
ROUND = 3


def _unavail(reason: str, **kw) -> dict:
    return {"status": "unavailable", "reason": reason, **kw}


def _bstatus(n: int) -> dict:
    return ({"status": "unavailable", "reason": UNAVAILABLE_NONE} if n == 0 else
            {"status": "unavailable", "reason": UNAVAILABLE_SINGLE} if n == 1 else
            {"status": "ok", "reason": ("n < %d：區間很寬，只供參考" % MIN_REPLICAS) if n < MIN_REPLICAS else ""})


def sign_consistency(items: Iterable[tuple[str, float]]) -> dict:
    """Number of replicas whose value has the same sign as the replica mean (zero counts for neither)."""
    vals = [(str(r), _finite(v)) for r, v in items]
    vals = [(r, v) for r, v in vals if v is not None]
    n = len(vals)
    if not n:
        return {"k": 0, "n": 0, "sign": None, "consistent": None}
    m = float(np.mean([v for _, v in vals]))
    sg = (m > 0) - (m < 0)
    k = sum(1 for _, v in vals if sg != 0 and ((v > 0) - (v < 0)) == sg)
    return {"k": k, "n": n, "sign": sg, "consistent": bool(sg != 0 and k == n)}


def t_critical_975_float(df: float) -> float:
    """t(0.975, df) for a non-integer df (Welch–Satterthwaite): linear in 1/df between the neighbouring integers."""
    df = max(1.0, float(df))
    lo = int(math.floor(df))
    if abs(df - lo) < 1e-9:
        return t_critical_975(lo)
    hi = lo + 1
    a, b = t_critical_975(lo), t_critical_975(hi)
    w = (1 / df - 1 / hi) / (1 / lo - 1 / hi)
    return b + (a - b) * w


def _ext_block(reps: list[dict], name: str, ligand: str | None = None):
    """(have, missing): replicas whose extended.json has the block, and why the others do not."""
    have, missing = [], []
    for r in reps:
        ext = r.get("extended")
        if not isinstance(ext, dict) or not ext:
            missing.append({"run_id": r["run_id"], "reason": "沒有 extended.json"})
            continue
        src = (((ext.get("ligands") or {}).get(ligand) or {}) if ligand else ext)
        blk = src.get(name)
        if not isinstance(blk, dict) or not blk:
            err = ((src.get("errors") if ligand else ext.get("errors")) or {}).get(name)
            missing.append({"run_id": r["run_id"], "reason": f"extended.json 沒有 {name}" + (f"（{err}）" if err else "")})
            continue
        have.append((r, blk))
    return have, missing


def _fold(labels) -> list[str]:
    from .traj import residue_keys
    return residue_keys([str(x) for x in labels])


def _stack_stats(M: np.ndarray) -> dict:
    """Per-column mean, sample SD and t CI of a replicas x items matrix."""
    n = M.shape[0]
    out = {"n": n, "mean": M.mean(0).round(4).tolist(), "sd": None, "ci95_low": None, "ci95_high": None,
           "between_replica": _bstatus(n)}
    if n >= 2:
        sd = M.std(0, ddof=1)
        half = t_critical_975(n - 1) * sd / math.sqrt(n)
        out.update({"sd": sd.round(4).tolist(), "ci95_low": (M.mean(0) - half).round(4).tolist(),
                    "ci95_high": (M.mean(0) + half).round(4).tolist()})
    return out


# ------------------------------------------------------------------------------------------------ DSSP
def _dssp(reps: list[dict]) -> dict:
    have, missing = _ext_block(reps, "dssp")
    if not have:
        return _unavail("沒有任何重複有 DSSP 結果", missing=missing)
    n = len(have)
    overall = {}
    for c in ("H", "E", "C"):
        items = []
        for r, b in have:
            fr = (b.get("fraction") or {}).get(c)
            if isinstance(fr, list) and fr:
                items.append((r["run_id"], float(np.mean(fr))))
        if items:
            overall[c] = between_replica_stats(items, cv=False, cv_reason="比例型量不適用 CV；看標準差與信賴區間")
    labs = [_fold(b.get("residues") or []) for _, b in have]
    common = [x for x in labs[0] if all(x in set(l) for l in labs[1:])] if all(labs) else []
    out = {"status": "ok", "n": n, "missing": missing, "overall_fraction": overall,
           "estimand": "per replica: time-mean fraction of frames in H/E/C (display frames); per residue: fraction of frames in H or E; "
                       "then mean/SD/t-CI across replicas",
           "estimand_zh": "每條重複：H／E／C 的幀比例（顯示用抽樣幀）與逐殘基 H、E 比例；再跨重複算平均、標準差與 t 區間",
           "between_replica": _bstatus(n), "per_residue": {}}
    if len(common) < 5:
        out["per_residue_status"] = _unavail("各重複共同的殘基少於 5 個，或缺逐殘基資料", n_common=len(common))
        return out
    for c in ("H", "E"):
        rows, ids = [], []
        for (r, b), lab in zip(have, labs):
            arr = (b.get("per_residue") or {}).get(c)
            if not isinstance(arr, list) or len(arr) != len(lab):
                continue
            pos = {x: i for i, x in enumerate(lab)}
            rows.append([float(arr[pos[x]]) for x in common])
            ids.append(r["run_id"])
        if not rows:
            continue
        st = _stack_stats(np.array(rows, float))
        sd = st["sd"]
        worst = []
        if sd is not None:
            order = np.argsort(-np.array(sd))[:5]
            worst = [{"residue": common[i], "mean": st["mean"][i], "sd": sd[i]} for i in order if sd[i] > 0]
        out["per_residue"][c] = {**st, "residues": common, "run_ids": ids, "least_reproducible": worst}
    return out


# ------------------------------------------------------------------------------------------------ DCCM
def _dccm(reps: list[dict]) -> dict:
    have, missing = _ext_block(reps, "dccm")
    have = [(r, b) for r, b in have if b.get("matrix")]
    if not have:
        return _unavail("沒有任何重複有 DCCM 矩陣", missing=missing)
    n = len(have)
    labs = [_fold(b.get("residues") or []) for _, b in have]
    if not all(labs):
        return _unavail("DCCM 缺殘基標籤，無法對齊重複", missing=missing)
    common = [x for x in labs[0] if all(x in set(l) for l in labs[1:])]
    N = len(common)
    if N < DCCM_LONG_RANGE_SEP + 2:
        return _unavail("各重複共同的殘基太少，無法彙總 DCCM", n_common=N, missing=missing)
    mats = []
    for (r, b), lab in zip(have, labs):
        pos = {x: i for i, x in enumerate(lab)}
        idx = [pos[x] for x in common]
        mats.append(np.asarray(b["matrix"], float)[np.ix_(idx, idx)])
    C = np.array(mats)
    mean = C.mean(0)
    iu = np.triu_indices(N, k=DCCM_LONG_RANGE_SEP)
    per_rep = [(r["run_id"], float(np.abs(C[i][iu]).mean())) for i, (r, _) in enumerate(have)]
    out = {"status": "ok", "n": n, "missing": missing, "n_residues": N, "residues": common if N <= DCCM_MAX_STORED else None,
           "estimand": "element-wise mean and sample SD of each replica's Cα cross-correlation matrix (common residues); long-range "
                       f"pairs have residue index separation >= {DCCM_LONG_RANGE_SEP}",
           "estimand_zh": f"各重複的 Cα 互相關矩陣逐元素取平均與樣本標準差（共同殘基）；遠距離＝殘基序號相差 ≥ {DCCM_LONG_RANGE_SEP}",
           "between_replica": _bstatus(n),
           "long_range": {"mean_abs_correlation": between_replica_stats(per_rep), "n_pairs": int(len(iu[0]))},
           "thresholds": {"strong": DCCM_STRONG, "replica_min": DCCM_REPLICA_MIN, "min_separation": DCCM_LONG_RANGE_SEP}}
    lr_mean = mean[iu]
    strong = np.abs(lr_mean) >= DCCM_STRONG
    if n >= 2:
        sd = C.std(0, ddof=1)
        out["long_range"]["mean_element_sd"] = round(float(sd[iu].mean()), 4)
        sgn = np.sign(lr_mean)
        same = (np.sign(C[:, iu[0], iu[1]]) == sgn[None, :]) & (np.abs(C[:, iu[0], iu[1]]) >= DCCM_REPLICA_MIN)
        repro = same.all(0) & strong
        out["long_range"].update({"n_strong_pairs": int(strong.sum()), "n_strong_reproducible": int(repro.sum()),
                                  "reproducible_definition": f"|mean| >= {DCCM_STRONG} and, in every replica, the same sign with |C| >= {DCCM_REPLICA_MIN}"})
        order = np.argsort(-np.abs(lr_mean))[:10]
        out["long_range"]["top_pairs"] = [
            {"i": common[iu[0][o]], "j": common[iu[1][o]], "mean": round(float(lr_mean[o]), 3),
             "sd": round(float(sd[iu[0][o], iu[1][o]]), 3),
             "sign_k": int((np.sign(C[:, iu[0][o], iu[1][o]]) == sgn[o]).sum()), "sign_n": n,
             "divergent": None, "divergent_reason": NO_CV_REASON} for o in order]
        if N <= DCCM_MAX_STORED:
            out["mean"], out["sd"] = mean.round(2).tolist(), sd.round(2).tolist()
    else:
        out["long_range"]["n_strong_pairs"] = int(strong.sum())
        out["long_range"]["n_strong_reproducible"] = None
        out["long_range"]["reproducible_reason"] = UNAVAILABLE_SINGLE
        if N <= DCCM_MAX_STORED:
            out["mean"], out["sd"] = mean.round(2).tolist(), None
    return out


# ------------------------------------------------------------------------------------------------ clusters, PCA basins
def _clusters(reps: list[dict]) -> dict:
    have, missing = _ext_block(reps, "clusters")
    have = [(r, b) for r, b in have if b.get("populations")]
    if not have:
        return _unavail("沒有任何重複有分群結果", missing=missing)
    n = len(have)
    return {"status": "ok", "n": n, "missing": missing, "between_replica": _bstatus(n),
            "identity_matched": False,
            "note": "clusters are defined inside each replica (own RMSD matrix); cluster labels are NOT matched across replicas, so only "
                    "label-free numbers are aggregated. Shares per cluster across replicas need the common PCA basin shares.",
            "note_zh": "分群是每條重複各自做的，群編號不對應，所以只彙總與編號無關的數（群數、最大群占比）；逐群占比要看共同基底的低谷佔比。",
            "n_clusters": between_replica_stats([(r["run_id"], b.get("n_clusters", len(b["populations"]))) for r, b in have]),
            "largest_cluster_share": between_replica_stats([(r["run_id"], max(b["populations"])) for r, b in have])}


def pca_basin_shares(cb: dict | None, system: str, *, within_comparable: bool = True) -> dict:
    """Basin shares of the replicas of ``system`` on the COMMON PCA basis (analysis_common.json).  Basins of different replicas are
    matched by position on the shared axes (within BASIN_MATCH_BINS landscape bins, greedy by population); each replica's frames
    (the stored uniform subsample of its projection) are then assigned to the nearest matched basin centre, so a replica without
    that basin still gets its real share.  Without a common basis, or when the replicas' conditions differ, the shares are not
    comparable and the result says so."""
    if not isinstance(cb, dict) or cb.get("status") != "ok":
        return {"status": "not_comparable",
                "reason": "沒有共同基底：每條重複各自做 PCA，軸不同，低谷佔比不能互相比較（只有 ≥ 2 個系統時才會建立共同基底）",
                "reason_en": "no common basis: each replica has its own PCA axes, so basin shares are not comparable"}
    if not within_comparable:
        return {"status": "not_comparable", "reason": "同一系統的重複之間條件不同或無法確認，低谷佔比不能彙總"}
    labels = cb.get("trajectory_labels") or {}
    names = [n for n, l in labels.items() if l.get("system") == system and n in (cb.get("per_system") or {})]
    if not names:
        return _unavail("共同基底裡沒有這個系統的重複")
    xe, ye = np.asarray(cb["xedges"], float), np.asarray(cb["yedges"], float)
    tol = BASIN_MATCH_BINS * max(float(xe[1] - xe[0]), float(ye[1] - ye[0]))
    cand = []
    for n in names:
        for b in ((cb["per_system"][n].get("landscape") or {}).get("basins") or []):
            cand.append((float(b[3]) if len(b) > 3 else 0.0, n, np.array(b[:2], float)))
    cand.sort(key=lambda x: -x[0])
    groups: list[dict] = []
    for pop, n, xy in cand:
        best, bd = None, None
        for g in groups:
            d = float(np.linalg.norm(g["xy"] - xy))
            if n not in g["members"] and d <= tol and (bd is None or d < bd):
                best, bd = g, d
        if best is None:
            groups.append({"xy": xy.copy(), "members": {n: pop}})
        else:
            best["members"][n] = pop
            best["xy"] = (best["xy"] * (len(best["members"]) - 1) + xy) / len(best["members"])
    if not groups:
        return _unavail("各重複的地形都沒有低谷", n_replicas=len(names))
    centres = np.array([g["xy"] for g in groups])
    shares = {}
    for n in names:
        P = np.asarray(cb["per_system"][n].get("projection") or [], float)
        if P.ndim != 2 or len(P) < 20:
            continue
        lab = np.argmin(((P[:, None, :2] - centres[None]) ** 2).sum(-1), axis=1)
        shares[n] = (np.bincount(lab, minlength=len(groups)) / len(P)).tolist()
    n_rep = len(shares)
    if n_rep == 0:
        return _unavail("共同基底裡沒有可用的投影（幀數不足）")
    basins = []
    for gi, g in enumerate(groups):
        items = [(labels[n]["run_id"], shares[n][gi]) for n in shares]
        st = between_replica_stats(items, cv=False, cv_reason="比例型量不適用 CV；看各條占比的範圍")
        rng = (st["max"] - st["min"]) if st["max"] is not None else None
        basins.append({"basin": gi + 1, "xy": [round(float(v), 3) for v in g["xy"]], "own_basin_in_replicas": len(g["members"]),
                       "share": st, "range": None if rng is None or n_rep < 2 else round(rng, 3),
                       "inconsistent": None if n_rep < 2 else bool(rng > BASIN_RANGE_INCONSISTENT)})
    basins.sort(key=lambda b: -(b["share"]["mean"] or 0))
    incons = [b["basin"] for b in basins if b["inconsistent"]]
    return {"status": "ok", "n": n_rep, "between_replica": _bstatus(n_rep), "match_tolerance": round(tol, 3),
            "estimand": "per replica: share of its stored projection frames nearest to each matched basin centre on the common PCA axes; "
                        "then mean/SD/t-CI across replicas",
            "estimand_zh": "共同 PCA 軸上，每條重複的投影幀離各低谷中心最近的比例；再跨重複算平均、標準差與 t 區間",
            "basins": basins, "inconsistent_basins": incons, "range_threshold": BASIN_RANGE_INCONSISTENT,
            "interpretation": ("各條重複的低谷佔比差異大：這是取樣到的分布，未收斂。" if incons else
                               "各條重複的低谷佔比一致（範圍在門檻內）；仍不保證自由能地形已收斂。") if n_rep >= 2 else UNAVAILABLE_SINGLE}


def attach_basin_shares(agg: dict, cb: dict | None, *, within_comparable: bool = True) -> dict:
    """Write the basin shares into an aggregate (``structure.pca_basins``) and its flags."""
    res = pca_basin_shares(cb, agg.get("system", ""), within_comparable=within_comparable)
    agg.setdefault("structure", {})["pca_basins"] = res
    agg["flags"] = [f for f in agg.get("flags", []) if f != "unconverged:pca_basins"]
    if res.get("inconsistent_basins"):
        agg["flags"].append("unconverged:pca_basins")
    return agg


# ------------------------------------------------------------------------------------------------ tICA / MSM (never pooled)
def _tica_msm(reps: list[dict]) -> dict:
    have, missing = _ext_block(reps, "tica")
    if not have:
        return _unavail("沒有任何重複有 tICA／MSM 結果", missing=missing)
    rows = []
    for r, b in have:
        m = b.get("msm") or {}
        ok = b.get("status") == "ok"
        el = m.get("eligibility") if ok else None
        ts = [v for v in (b.get("timescales_ns") or []) if v is not None]
        rows.append({"run_id": r["run_id"], "tica_status": b.get("status"), "reason": b.get("reason"),
                     "lag_ns": b.get("lag_ns"), "msm_eligibility": el, "msm_reason": m.get("reason"),
                     "its_flat": m.get("its_flat") if el == "exploratory" else None, "transitions": m.get("transitions"),
                     "trajectory_ns": m.get("trajectory_ns"),
                     "qualifies": bool(el == "exploratory"),
                     "slowest_timescale_ns": ts[0] if (ts and el == "exploratory") else None})
    n = len(rows)
    k = sum(1 for x in rows if x["qualifies"])
    flat = sum(1 for x in rows if x["qualifies"] and x["its_flat"])
    return {"status": "ok", "n": n, "missing": missing, "pooled": False,
            "note": "trajectories are never pooled into one rate: each replica is qualified on its own (D-105: enough transitions, "
                    "connected, slowest process shorter than a third of the run). No mean timescale or rate is reported.",
            "note_zh": "不把各條軌跡合併估計速率：每條各自檢查資格（D-105：轉換次數夠、連通、最慢過程短於模擬的三分之一）；不報平均時間尺度或速率。",
            "qualifies_k": k, "qualifies_n": n, "its_flat_k": flat, "its_flat_n": k, "per_replica": rows,
            "between_replica": _bstatus(n),
            "rate_reportable": bool(k >= MIN_REPLICAS and flat == k),
            "rate_reason": ("" if (k >= MIN_REPLICAS and flat == k) else
                            f"{n} 條中 {k} 條合格（至少需要 {MIN_REPLICAS} 條都合格且時間尺度對延遲時間持平），不報速率")}


# ------------------------------------------------------------------------------------------------ hydration sites
def _hydration(reps: list[dict], ligand: str) -> dict:
    have, missing = _ext_block(reps, "hydration", ligand)
    ok = []
    for r, b in have:
        if b.get("status") == "ok":
            ok.append((r["run_id"], b.get("sites") or []))
        else:
            missing.append({"run_id": r["run_id"], "reason": f"hydration 狀態是 {b.get('status')}（沒有水分子或幀數不足）"})
    if not ok:
        return _unavail("沒有任何重複有水合位點結果", missing=missing)
    n = len(ok)
    cand = sorted(((s.get("occupancy", 0.0), rid, np.array(s["xyz_nm"], float), s) for rid, ss in ok for s in ss if s.get("xyz_nm")),
                  key=lambda x: -x[0])
    groups: list[dict] = []
    for occ, rid, xyz, s in cand:
        best, bd = None, None
        for g in groups:
            d = float(np.linalg.norm(g["xyz"] - xyz))
            if rid not in g["members"] and d <= HYDRATION_MATCH_NM and (bd is None or d < bd):
                best, bd = g, d
        if best is None:
            groups.append({"xyz": xyz.copy(), "members": {rid: s}})
        else:
            best["members"][rid] = s
            best["xyz"] = (best["xyz"] * (len(best["members"]) - 1) + xyz) / len(best["members"])
    sites = []
    for g in groups:
        det = g["members"]
        k = len(det)
        st = between_replica_stats([(rid, s.get("occupancy")) for rid, s in det.items()], cv=False,
                                   cv_reason="占有率是比例型量，不適用 CV")
        if n == 1:
            status = "unavailable"
        else:
            status = "reproduced" if k >= HYDRATION_MIN_REPLICAS_REPRODUCED else "not_reproduced"
        sites.append({"xyz_nm": [round(float(v), 3) for v in g["xyz"]], "detected_k": k, "detected_n": n, "status": status,
                      "occupancy_among_detecting": st,
                      "mean_density_ratio": round(float(np.mean([s.get("density_ratio", 0.0) for s in det.values()])), 2),
                      "spread_nm": round(float(max(np.linalg.norm(np.array(s["xyz_nm"]) - g["xyz"]) for s in det.values())), 3)})
    sites.sort(key=lambda x: (-x["detected_k"], -(x["occupancy_among_detecting"]["mean"] or 0)))
    return {"status": "ok", "n": n, "missing": missing, "between_replica": _bstatus(n),
            "match_tolerance_nm": HYDRATION_MATCH_NM,
            "matching": f"greedy by occupancy: a site joins the nearest existing group within {HYDRATION_MATCH_NM} nm (group centroid) "
                        "that has no site from the same replica yet; positions are in each replica's own superposed frame",
            "matching_zh": f"依占有率由高到低貪婪配對：與最近、且還沒有同一條重複位點的群組相距 ≤ {HYDRATION_MATCH_NM} nm 就歸為同一位點；"
                           "座標在各重複各自的疊合座標系中",
            "estimand": "per replica site occupancy (fraction of frames with a water O within the site radius), for the replicas in which "
                        "the site was detected (density >= the detection ratio); a replica that did not detect it has no occupancy value, "
                        "not zero",
            "estimand_zh": "位點占有率只在偵測到該位點的重複裡有值（密度達偵測門檻）；沒偵測到的重複不是 0，而是沒有值",
            "sites": sites[:15], "n_sites_total": len(sites),
            "n_reproduced": sum(1 for s in sites if s["status"] == "reproduced"),
            "n_not_reproduced": sum(1 for s in sites if s["status"] == "not_reproduced")}


# ------------------------------------------------------------------------------------------------ membrane
def _membrane(reps: list[dict]) -> dict:
    per = []
    for r in reps:
        mem = r.get("membrane")
        if not isinstance(mem, dict) or not mem:
            mem = (r["metrics"] or {}).get("membrane")
        if isinstance(mem, dict) and mem and mem.get("status") != "SKIPPED":
            per.append((r, mem))
    if not per:
        return _unavail("沒有任何重複有膜指標", missing=[{"run_id": r["run_id"], "reason": "沒有 membrane_metrics.json"} for r in reps])
    n = len(per)
    out = {"status": "ok", "n": n, "between_replica": _bstatus(n), "observables": {}, "solutes": {},
           "estimand": "per replica: second-half mean of bilayer thickness, area per lipid, core water; then mean/SD/t-CI across replicas",
           "estimand_zh": "每條重複：膜厚、單脂面積、疏水核心水數在後半段的平均；再跨重複彙總"}

    def put(key, items, unit, zh, **kw):
        if items:
            out["observables"][key] = {"unit": unit, "label_zh": zh, **between_replica_stats(items, **kw)}
    put("dpp_mean_nm", [(r["run_id"], m["dpp_mean_nm"]) for r, m in per if m.get("dpp_mean_nm") is not None], "nm", "磷酸頭基間距（膜厚）")
    put("apl_mean_nm2", [(r["run_id"], m["apl_mean_nm2"]) for r, m in per if m.get("apl_mean_nm2") is not None], "nm²", "單脂面積")
    cw = [(r["run_id"], float(np.mean(m["core_water"][len(m["core_water"]) // 2:]))) for r, m in per if m.get("core_water")]
    put("core_water", cw, "molecules", "疏水核心的水分子數")
    names = sorted({k for _, m in per for k in (m.get("insertion") or {})})
    for nm in names:
        have = [(r, m["insertion"][nm]) for r, m in per if nm in (m.get("insertion") or {})]
        out["solutes"][nm] = {
            "n": len(have),
            "mean_com_depth_nm": between_replica_stats([(r["run_id"], d.get("mean_com_depth_nm")) for r, d in have], cv=False,
                                                      cv_reason="插入深度帶正負號（相對頭基平面），不適用 CV"),
            "mean_deepest_nm": between_replica_stats([(r["run_id"], d.get("mean_deepest_nm")) for r, d in have], cv=False,
                                                    cv_reason="插入深度帶正負號（相對頭基平面），不適用 CV"),
            "crossed_centre": binary_summary([(r["run_id"], bool(d.get("crossed_centre"))) for r, d in have])}
    acc = [(r["run_id"], (m.get("acceptance") or {}).get("status") == "PASS") for r, m in per if m.get("acceptance")]
    if acc:
        out["acceptance_pass"] = binary_summary(acc)
    scd_have = [(r, r.get("membrane_report") or {}) for r, _ in per]
    scd_have = [(r, d["scd"]) for r, d in scd_have if isinstance(d.get("scd"), dict) and d["scd"]]
    if scd_have:
        keys = sorted({k for _, d in scd_have for k in d})
        out["scd"] = {"n": len(scd_have), "unit": "S_CD", "order_parameter": {
            k: between_replica_stats([(r["run_id"], d[k]) for r, d in scd_have if k in d], cv=False,
                                     cv_reason="序參數帶正負號，不適用 CV") for k in keys},
            "note_zh": "序參數 S_CD 逐碳原子，每條重複一個值，跨重複算平均與區間"}
    else:
        out["scd"] = _unavail("沒有序參數（粗粒化或沒有脂質尾端原子名稱）")
    return out


# ------------------------------------------------------------------------------------------------ apo–complex ΔRMSF
def delta_rmsf_between_replicas(ref_name: str, ref: dict | None, other_name: str, other: dict | None,
                                comparability: dict | None = None, *, top: int = 10) -> dict:
    """Per-residue ΔRMSF = mean(other replicas) − mean(ref replicas) with a Welch t 95 % CI (Welch–Satterthwaite df) from the
    PER-REPLICA RMSF values of both sides (``per_residue.rmsf_ca_A`` of the two replica sets).  n per side is stated.  A side with
    fewer than 2 replicas gives "unavailable" (no interval).  Residues are matched by name+number with protonation variants folded.
    Refused when ``comparability`` says the systems are not comparable.  "Different" means the CI excludes 0 for that residue; with
    N residues about 5 % of them exclude 0 by chance alone (no multiple-comparison correction is applied; the expected count is
    reported)."""
    if comparability is not None and not comparability.get("comparable"):
        return {"status": "not_comparable", "differences": comparability.get("differences"), "unknown": comparability.get("unknown"),
                "ref": ref_name, "other": other_name}
    if not ref or not other or not ref.get("per_replica") or not other.get("per_replica"):
        return _unavail("至少一邊沒有逐殘基 RMSF", ref=ref_name, other=other_name)
    n1, n2 = len(ref["per_replica"]), len(other["per_replica"])
    base = {"ref": ref_name, "other": other_name, "n_ref": n1, "n_other": n2, "method": "Welch t, 95 % CI, Welch–Satterthwaite df",
            "multiple_comparisons": "not corrected"}
    if n1 < 2 or n2 < 2:
        return {**base, "status": "unavailable",
                "reason": f"ΔRMSF 的重複間區間要兩邊各至少 2 條（目前 {ref_name} {n1} 條、{other_name} {n2} 條）；不給區間",
                "between_replica": {"status": "unavailable", "reason": UNAVAILABLE_SINGLE}}
    ra, rb = _fold(ref["residues"]), _fold(other["residues"])
    pb = {k: i for i, k in enumerate(rb)}
    keys = [k for k in ra if k in pb]
    if len(keys) < 5:
        return {**base, "status": "insufficient", "n_common": len(keys)}
    ia = [ra.index(k) for k in keys]
    ib = [pb[k] for k in keys]
    A = np.array([np.asarray(v, float)[ia] for v in ref["per_replica"].values()])        # n1 x R
    B = np.array([np.asarray(v, float)[ib] for v in other["per_replica"].values()])
    d = B.mean(0) - A.mean(0)
    v1, v2 = A.var(0, ddof=1) / n1, B.var(0, ddof=1) / n2
    se = np.sqrt(v1 + v2)
    with np.errstate(divide="ignore", invalid="ignore"):
        df = np.where(se > 0, (v1 + v2) ** 2 / (v1 ** 2 / (n1 - 1) + v2 ** 2 / (n2 - 1)), n1 + n2 - 2)
    tcrit = np.array([t_critical_975_float(x) for x in df])
    lo, hi = d - tcrit * se, d + tcrit * se
    excl = (lo > 0) | (hi < 0)
    other_dev = B - A.mean(0)                                                            # each other replica vs the ref mean
    sgn = np.sign(d)
    sign_k = ((np.sign(other_dev) == sgn[None, :]) & (sgn[None, :] != 0)).sum(0)
    rows = [{"residue": keys[i], "delta_A": round(float(d[i]), 3), "ci95_low": round(float(lo[i]), 3), "ci95_high": round(float(hi[i]), 3),
             "ci_excludes_zero": bool(excl[i]), "sign_k": int(sign_k[i]), "sign_n": n2} for i in range(len(keys))]
    sig = [r for r in rows if r["ci_excludes_zero"]]
    top_up = sorted(sig, key=lambda r: -r["delta_A"])[:top]
    top_down = sorted(sig, key=lambda r: r["delta_A"])[:top]
    return {**base, "status": "ok", "n_common": len(keys), "unit": "Å", "residues": rows,
            "n_ci_excludes_zero": len(sig), "expected_false_positives": round(0.05 * len(keys), 1),
            "most_flexible": [r for r in top_up if r["delta_A"] > 0], "most_rigidified": [r for r in top_down if r["delta_A"] < 0],
            "divergent": None, "divergent_reason": NO_CV_REASON,
            "between_replica": _bstatus(min(n1, n2)),
            "reading": "差值的區間不含 0 才稱「不同」；殘基很多時約 5 % 會因機率而不含 0，未做多重比較校正。"}


# ------------------------------------------------------------------------------------------------ the aggregate
def aggregate_replica_set(replicas: list[dict], *, system: str = "", n_requested: int | None = None) -> dict:
    """``replicas`` = one dict per run of this system, in replica order::

        {"run_id", "replica_index"?, "status"?, "reason"?, "excluded_reason"?, "analysis_status"?,
         "metrics": metrics.json content or None, "descendants"?: {"pulls": n, "windows": m},
         "extended"?: extended.json content, "membrane"?: membrane_metrics.json content, "membrane_report"?: membrane_report.json}

    Returns the ``md20.replica_set/1`` dict.  Never raises on missing data: what cannot be computed is "unavailable"
    with a reason."""
    reps_all, analysed, excluded = [], [], []
    for i, r in enumerate(replicas or []):
        ok, why = eligible(r)
        entry = {"run_id": str(r.get("run_id")), "replica_index": r.get("replica_index", i), "status": r.get("status"),
                 "analysed": ok, "reason": why, "descendants": dict(r.get("descendants") or {}),
                 "analysis_manifest": r.get("analysis_manifest"), "extended_file": r.get("extended_file")}
        ext = r.get("extended") if isinstance(r.get("extended"), dict) else {}
        entry["extended_blocks"] = sorted(k for k, v in ext.items() if isinstance(v, dict) and v and k not in ("errors", "ligands"))
        entry["extended_errors"] = dict(ext.get("errors") or {})
        reps_all.append(entry)
        if ok:
            analysed.append({"run_id": entry["run_id"], "metrics": r["metrics"], "extended": r.get("extended"),
                             "membrane": r.get("membrane"), "membrane_report": r.get("membrane_report")})
        else:
            excluded.append({"run_id": entry["run_id"], "status": r.get("status"), "reason": why})
    n = len(analysed)
    out: dict = {"schema": SCHEMA, "system": system, "lineage": LINEAGE, "concatenation": "never",
                 "concatenation_note": "replica boundaries are never joined: event durations, persistence and transitions "
                                       "are computed inside one replica and only their per-replica results are combined",
                 "n_requested": n_requested, "n_listed": len(reps_all), "n_analysed": n, "min_recommended": MIN_REPLICAS,
                 "replicas": reps_all, "excluded": excluded, "observables": {}, "ligands": {}, "per_residue": {},
                 "schema_revision": SCHEMA_REVISION, "structure": {}, "membrane": None}
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
    out["structure"] = {"dssp": _dssp(analysed), "dccm": _dccm(analysed), "clusters": _clusters(analysed),
                        "tica_msm": _tica_msm(analysed),
                        "pca_basins": pca_basin_shares(None, system)}       # replaced by attach_basin_shares when a common basis exists
    out["membrane"] = _membrane(analysed)
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
        lig["hydration"] = _hydration(reps_l, ln)
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
