"""Structured scientific assessment of one umbrella-sampling / PMF result (D-96; spec master_iteration_2026-11-07 §3.1).

Execution status (the calculation ran), scientific assessment (what each diagnostic says) and comparison eligibility
(which conclusions the evidence supports) are three different things.  This module turns the quality fields a binding
manifest already stores (`BindingResult.pmf`) into one object that every downstream consumer — aggregation,
comparison, captions, summaries, GUI — reads, so they cannot contradict one another.

Rules
  * every diagnostic records its method, scope (local / global), status (pass / fail / unknown), value and the
    provenance of its threshold;
  * a missing field is `unknown`, never a pass;
  * a local pass (adjacent overlap, pooled coverage, last-two cumulative estimates) is reported as a local pass;
  * thresholds are empirical, versioned and overridable — they are not universal laws.

Pure Python + numpy; the same function re-assesses legacy manifests (fields absent → unknown → not eligible).
"""
from __future__ import annotations

from typing import Iterable

import numpy as np

SCHEMA = "md20.assessment.pmf/1"
THRESHOLDS_VERSION = "2026-11-07.2"
THRESHOLDS = {
    "overlap_edge_min": (0.03, "edge of the window-overlap graph when only the histogram matrix is stored; same order "
                               "as the MBAR quality report's minimum_overlap (D-43); empirical"),
    "mbar_overlap_edge_min": (0.03, "edge of the MBAR overlap-matrix graph (every window pair, D-43); off-diagonal "
                                    "≥ 0.03 as recommended by Klimovich, Shirts & Mobley 2015 (J Comput Aided Mol Des 29:397)"),
    "window_ess_min": (100.0, "umbrella_quality(min_effective_samples=100) default (D-43); time-correlation ESS, not "
                              "MBAR weight ESS"),
    "half_split_max_kj": (2.0, "D-58 half-split rule (≈ 0.8 kT at 300 K); empirical"),
    "cumulative_drift_max_kj": (2.0, "D-58 cumulative rule applied to every estimate from 50 % of the data on; empirical"),
}

# diagnostics a path-specific ΔPMF needs; anything not `pass` blocks the path-specific claim
REQUIRED_PATH = ("overlap_graph", "window_ess", "solver", "half_split", "cumulative_drift", "endpoint_plateau",
                 "range_coverage")
PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"


def _thr(thresholds: dict | None, key: str) -> float:
    if thresholds and key in thresholds:
        return float(thresholds[key])
    return float(THRESHOLDS[key][0])


def _src(thresholds: dict | None, key: str) -> str:
    if thresholds and key in thresholds:
        return f"user override ({THRESHOLDS_VERSION} default {THRESHOLDS[key][0]})"
    return f"{THRESHOLDS_VERSION}: {THRESHOLDS[key][1]}"


def _diag(id_, method, scope, status, value=None, threshold=None, source=None, note=None) -> dict:
    return {"id": id_, "method": method, "scope": scope, "status": status, "value": value, "threshold": threshold,
            "threshold_source": source, "note": note}


def graph_connected(matrix: Iterable[Iterable[float]], edge_min: float) -> bool | None:
    """Connectivity of the full overlap graph (every pair, not only adjacent windows)."""
    try:
        M = np.asarray(matrix, float)
    except (TypeError, ValueError):
        return None
    if M.ndim != 2 or M.shape[0] != M.shape[1] or M.shape[0] < 2:
        return None
    n = M.shape[0]
    adj = (M >= edge_min)
    seen, stack = {0}, [0]
    while stack:
        i = stack.pop()
        for j in np.nonzero(adj[i])[0]:
            j = int(j)
            if j not in seen:
                seen.add(j)
                stack.append(j)
    return len(seen) == n


def _window_ess(quality: dict) -> float | None:
    ws = quality.get("window_stats")
    if not ws:
        return None
    vals = [w.get("n_effective") for w in ws if isinstance(w, dict) and w.get("n_effective") is not None]
    return float(min(vals)) if vals else None


def _cumulative_drift(conv: dict) -> tuple[float | None, list]:
    pts = []
    for k, v in (conv or {}).items():
        try:
            f = float(k)
        except ValueError:
            continue
        if isinstance(v, dict) and v.get("delta_pmf") is not None:
            pts.append((f, float(v["delta_pmf"])))
    pts.sort()
    if len(pts) < 3 or pts[-1][0] < 0.999:
        return None, pts
    final = pts[-1][1]
    late = [abs(d - final) for f, d in pts[:-1] if f >= 0.5 - 1e-9]
    return (max(late) if late else None), pts


def assess_pmf(pmf: dict | None, *, dG_withheld: str | None = None, has_dG: bool = True,
               thresholds: dict | None = None) -> dict:
    """Assessment of one PMF (`BindingResult.pmf` dict or the same fields from a manifest)."""
    pmf = pmf or {}
    q = pmf.get("quality") or {}
    diags = []
    cov = pmf.get("coverage")
    if cov is None:
        diags.append(_diag("histogram_coverage", "pooled CV histogram has no gap", "local", UNKNOWN))
    else:
        diags.append(_diag("histogram_coverage", "pooled CV histogram has no gap", "local",
                           PASS if cov.get("continuous") and not cov.get("breaks") else FAIL, value=cov.get("breaks") or []))
    ov = pmf.get("overlap_matrix") or {}
    mn = ov.get("min_neighbour") if isinstance(ov, dict) else None
    diags.append(_diag("adjacent_overlap_min", "smallest histogram overlap between windows adjacent by centre", "local",
                       UNKNOWN if mn is None else (PASS if mn >= _thr(thresholds, "overlap_edge_min") else FAIL),
                       value=mn, threshold=_thr(thresholds, "overlap_edge_min"), source=_src(thresholds, "overlap_edge_min"),
                       note="local: a low adjacent value does not by itself disconnect the full graph"))
    gc = q.get("graph_connected")
    method = "overlap graph over every window pair (MBAR quality report, equilibrated samples)"
    if gc is None and isinstance(ov, dict) and ov.get("matrix") is not None:
        gc = graph_connected(ov["matrix"], _thr(thresholds, "overlap_edge_min"))
        method = "overlap graph over every window pair (histogram overlap matrix)"
    diags.append(_diag("overlap_graph", method, "global", UNKNOWN if gc is None else (PASS if gc else FAIL), value=gc,
                       threshold=_thr(thresholds, "overlap_edge_min"), source=_src(thresholds, "overlap_edge_min")))
    # D-113: the MBAR estimator's own overlap matrix (stored from D-113 on).  WHAM has none → unknown, which does NOT
    # block (otherwise every WHAM PMF would be blocked); a stored matrix whose graph is disconnected DOES block.
    mo = q.get("mbar_overlap") if isinstance(q.get("mbar_overlap"), dict) else None
    mgc = graph_connected(mo["matrix"], _thr(thresholds, "mbar_overlap_edge_min")) if mo and mo.get("matrix") is not None else None
    diags.append(_diag("mbar_overlap", "MBAR overlap matrix: graph over every window pair connected", "global",
                       UNKNOWN if mgc is None else (PASS if mgc else FAIL),
                       value=None if mo is None else {"connected": mgc, "min_adjacent": mo.get("min_adjacent"),
                                                      "scalar": mo.get("scalar")},
                       threshold=_thr(thresholds, "mbar_overlap_edge_min"), source=_src(thresholds, "mbar_overlap_edge_min"),
                       note=("no MBAR matrix (WHAM estimate or result written before D-113); not required"
                             if mo is None else mo.get("note"))))
    ess = _window_ess(q)
    diags.append(_diag("window_ess", "smallest per-window effective sample count (statistical inefficiency, after "
                                     "equilibration detection)", "global",
                       UNKNOWN if ess is None else (PASS if ess >= _thr(thresholds, "window_ess_min") else FAIL),
                       value=None if ess is None else round(ess, 1), threshold=_thr(thresholds, "window_ess_min"),
                       source=_src(thresholds, "window_ess_min")))
    conv_ok = pmf.get("converged")
    xc = q.get("solver_cross_check") or {}
    if conv_ok is None:
        st = UNKNOWN
    elif conv_ok:
        st = PASS
    else:
        st = PASS if (xc.get("abs_diff_kj_mol") is not None and xc["abs_diff_kj_mol"] <= 2.0) else FAIL
    diags.append(_diag("solver", f"{pmf.get('method') or 'unknown'} solver tolerance (WHAM cross-check accepted ≤ 2 kJ/mol)",
                       "global", st, value=xc.get("abs_diff_kj_mol")))
    hs = (pmf.get("half_split") or {}).get("diff_kj_mol")
    diags.append(_diag("half_split", "|ΔPMF(first half) − ΔPMF(second half)| of every window", "global",
                       UNKNOWN if hs is None else (PASS if hs <= _thr(thresholds, "half_split_max_kj") else FAIL), value=hs,
                       threshold=_thr(thresholds, "half_split_max_kj"), source=_src(thresholds, "half_split_max_kj")))
    drift, pts = _cumulative_drift(pmf.get("convergence") or {})
    diags.append(_diag("cumulative_drift", "max |ΔPMF(f) − ΔPMF(100 %)| for cumulative fractions f ≥ 50 %", "global",
                       UNKNOWN if drift is None else (PASS if drift <= _thr(thresholds, "cumulative_drift_max_kj") else FAIL),
                       value=None if drift is None else round(drift, 3), threshold=_thr(thresholds, "cumulative_drift_max_kj"),
                       source=_src(thresholds, "cumulative_drift_max_kj"),
                       note="estimates: " + ", ".join(f"{f:.2f}→{d:.2f}" for f, d in pts) if pts else None))
    pl = pmf.get("plateau")          # binding.py writes it explicitly from D-96 on; older manifests → unknown
    diags.append(_diag("endpoint_plateau", "PMF tail flat within 1 kT (D-65)", "global",
                       UNKNOWN if pl is None else (PASS if pl else FAIL), value=pl,
                       note="a flat tail does not prove a contact-free bulk state"))
    tr = q.get("pmf_truncated")
    if not pmf:
        rc = UNKNOWN
    elif tr and not tr.get("replaced_by"):
        rc = FAIL
    else:
        rc = PASS
    diags.append(_diag("range_coverage", "PMF finite over the whole sampled range", "global", rc, value=tr or None))

    by = {d["id"]: d for d in diags}
    failed = [d["id"] for d in diags if d["status"] == FAIL]
    unknown = [d["id"] for d in diags if d["status"] == UNKNOWN]
    req_bad = [i for i in REQUIRED_PATH if by[i]["status"] != PASS]
    if by["mbar_overlap"]["status"] == FAIL:          # D-113: required when the matrix exists
        req_bad.append("mbar_overlap")
    adequate = None if (not failed and any(i in unknown for i in REQUIRED_PATH)) else (not req_bad)
    conflicts = []
    for loc in ("histogram_coverage", "adjacent_overlap_min"):
        if by[loc]["status"] == PASS and by["overlap_graph"]["status"] == FAIL:
            conflicts.append(f"{loc} passes locally but the full overlap graph is disconnected")
    if by["adjacent_overlap_min"]["status"] == FAIL and by["overlap_graph"]["status"] == PASS:
        conflicts.append("adjacent_overlap_min fails locally but other windows bridge the gap: the full graph is connected")
    if by["overlap_graph"]["status"] == PASS and by["mbar_overlap"]["status"] == FAIL:
        conflicts.append("histogram overlap graph is connected but the MBAR overlap matrix is not: the estimator cannot "
                         "transfer weight between some windows")
    if by["half_split"]["status"] == PASS and by["cumulative_drift"]["status"] == FAIL:
        conflicts.append("half_split passes but the cumulative estimates are still drifting")
    if by["cumulative_drift"]["status"] == PASS and by["half_split"]["status"] == FAIL:
        conflicts.append("cumulative estimates are stable but the two halves disagree")
    path_ok = not req_bad
    dg_ok = path_ok and not dG_withheld and has_dG
    reasons = [f"{i}: {by[i]['status']}" for i in req_bad]
    if dG_withheld:
        reasons.append(f"ΔG° withheld: {dG_withheld}")
    return {
        "schema": SCHEMA, "thresholds_version": THRESHOLDS_VERSION, "diagnostics": diags,
        "failed": failed, "unknown": unknown, "sampling_adequate": adequate, "conflicts": conflicts,
        "eligibility": {
            "delta_pmf_curve": bool(pmf.get("pmf_radial_kj_mol") is not None or pmf.get("grid_nm") is not None),
            "delta_pmf_path_specific": bool(path_ok),
            "dG_standard": bool(dg_ok),
            # an affinity ranking needs a qualified ΔG° *and* a compatible comparison; compare_binding decides the latter
            "affinity_ranking": bool(dg_ok),
        },
        "reasons": reasons,
        "permitted": (["diagnostic PMF curve"] + (["path-specific well depth under the recorded conditions"] if path_ok else [])
                      + (["standard binding free energy under the 1 M radial approximation"] if dg_ok else [])),
        "prohibited": (["affinity ranking", "'strongest' label", "ΔΔG°"] if not dg_ok else [])
                      + (["any well-depth comparison"] if not path_ok else [])
                      + ["SMD work or peak force as binding free energy", "intrinsic affinity from a co-occupancy pull"],
    }


def combine_assessments(items: list[dict]) -> dict:
    """Replica aggregate: a conclusion is eligible only if every replica supports it (no favourable-replica picking)."""
    items = [a for a in items if a]
    if not items:
        return assess_pmf(None)
    out = dict(items[0])
    g = lambda a, k: a.get(k) or []  # noqa: E731
    out["per_replica"] = [{"failed": g(a, "failed"), "unknown": g(a, "unknown"), "eligibility": a.get("eligibility") or {}}
                          for a in items]
    keys = sorted({k for a in items for k in (a.get("eligibility") or {})})
    out["eligibility"] = {k: all((a.get("eligibility") or {}).get(k) for a in items) for k in keys}
    for k in ("failed", "unknown", "conflicts", "reasons"):
        out[k] = sorted({x for a in items for x in g(a, k)})
    sa = [a.get("sampling_adequate") for a in items]
    out["sampling_adequate"] = False if False in sa else (None if None in sa else True)
    return out


def legacy_assessment(result: dict) -> dict:
    """A workflow binding result written before D-96 has no assessment: everything unknown → awaiting reanalysis."""
    a = assess_pmf(None)
    a["legacy"] = True
    a["reasons"] = ["no stored assessment (result written before D-96): awaiting reanalysis"]
    return a


def eligibility_of(result: dict) -> dict:
    a = (result or {}).get("assessment")
    if not a:
        return legacy_assessment(result or {})["eligibility"] | {"legacy": True}
    return a.get("eligibility") or {}
