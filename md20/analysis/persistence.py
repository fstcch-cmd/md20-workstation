"""Interaction persistence: event tables, censoring and an estimator-cadence contract (D-97; spec F09 §6.4.1, A12).

Input is ONE trajectory's boolean series for one interaction (atom- or residue-level, from `interactions.py`), with
the real time of every STORED frame — never the display-decimated frames of `extended.frame_indices`.

  * continuous event   = maximal run of consecutive "on" frames;
  * intermittent event = continuous events merged across "off" gaps no longer than `max_gap_ps` (physical time);
  * left-censored      = already on in the first frame (onset unknown);
  * right-censored     = still on in the last frame (termination unknown);
  * a real discontinuity (`segment_ids` change, or a time step larger than `max_dt_factor` × the median step) ends an
    event and is never bridged; separate runs are analysed separately and never concatenated.

Survival: Kaplan–Meier estimate of event duration with right-censoring.  Left-censored events have an unknown onset
and are EXCLUDED from the estimate (conditioning on observed onset) — they are counted and reported.  A lifetime is
only reported when the estimate actually drops to 1/e inside the observation window and at least `min_events`
uncensored events exist; otherwise `lifetime_ps` is None with the reason.

Cadence contract: if the stored frame interval exceeds `max_gap_ps`, interruptions shorter than one frame are
invisible; the analysis is then `limited` and durations are upper bounds — they cannot be recovered afterwards.

Contact persistence is not ligand residence time, not k_off, and not experimentally validated binding stability.
"""
from __future__ import annotations

import math
from typing import Iterable

import numpy as np

SCHEMA = "md20.persistence/1"


def _segments(t: np.ndarray, segment_ids: np.ndarray | None, max_dt_factor: float) -> np.ndarray:
    """Segment number per frame; a new segment starts at every recorded discontinuity or anomalous time jump."""
    n = len(t)
    seg = np.zeros(n, int)
    if n < 2:
        return seg
    dt = np.diff(t)
    med = float(np.median(dt)) if len(dt) else 0.0
    brk = np.zeros(n - 1, bool)
    if med > 0:
        brk |= dt > max_dt_factor * med
    brk |= dt <= 0
    if segment_ids is not None:
        s = np.asarray(segment_ids)
        brk |= s[1:] != s[:-1]
    seg[1:] = np.cumsum(brk)
    return seg


def _runs(on: np.ndarray) -> list[tuple[int, int]]:
    """(first, last) frame index of every maximal run of True."""
    out, start = [], None
    for i, v in enumerate(on):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i - 1)); start = None
    if start is not None:
        out.append((start, len(on) - 1))
    return out


def events(on: Iterable[bool], time_ps: Iterable[float], *, run_id: str, max_gap_ps: float = 0.0,
           segment_ids: Iterable | None = None, max_dt_factor: float = 1.5, window: tuple[float, float] | None = None) -> dict:
    """Event table for one interaction in one run."""
    on = np.asarray(list(on), bool)
    t = np.asarray(list(time_ps), float)
    if len(on) != len(t):
        raise ValueError("on and time_ps must have the same length")
    n = len(t)
    seg = _segments(t, None if segment_ids is None else np.asarray(list(segment_ids)), max_dt_factor)
    dt = np.diff(t)
    frame_ps = float(np.median(dt[dt > 0])) if (len(dt) and (dt > 0).any()) else None
    out_events = []
    for s in np.unique(seg):
        idx = np.nonzero(seg == s)[0]
        runs = [(idx[a], idx[b]) for a, b in _runs(on[idx])]
        merged: list[list] = []
        for a, b in runs:
            if merged and max_gap_ps > 0:
                prev = merged[-1][1]
                off_ps = float(t[a] - t[prev]) - (frame_ps or 0.0)        # time spent off between the two runs
                if off_ps <= max_gap_ps + 1e-9:
                    merged[-1][2].append({"from_frame": int(prev + 1), "frames": int(a - prev - 1), "off_ps": round(off_ps, 6)})
                    merged[-1][1] = b
                    continue
            merged.append([a, b, []])
        for a, b, gaps in merged:
            # duration counts each stored frame as one interval of the local cadence (half-open, so a single
            # on-frame lasts one frame interval); this is a resolution-limited estimate, not an exact lifetime
            dur = float(t[b] - t[a]) + (frame_ps or 0.0)
            ev = {"run_id": run_id, "segment": int(s), "start_frame": int(a), "end_frame": int(b),
                  "start_ps": float(t[a]), "end_ps": float(t[b]), "duration_ps": round(dur, 6),
                  "interruptions": len(gaps), "interrupted_frames": int(sum(g["frames"] for g in gaps)),
                  "left_censored": bool(a == idx[0]), "right_censored": bool(b == idx[-1])}
            if window is not None:
                ev["in_window"] = bool(t[a] >= window[0] and t[b] <= window[1])
            out_events.append(ev)
    # time-weighted occupancy: each frame weighted by its own interval (irregular timestamps allowed)
    w = np.full(n, frame_ps or 1.0)
    if n > 1:
        same = seg[1:] == seg[:-1]
        w[:-1] = np.where(same, np.clip(np.diff(t), 0, None), frame_ps or 1.0)   # no weight across a discontinuity
    occ = float((w * on).sum() / w.sum()) if n else None
    limited = []
    if frame_ps is not None and max_gap_ps > 0 and frame_ps > max_gap_ps:
        limited.append(f"stored frame interval {frame_ps:g} ps > allowed interruption {max_gap_ps:g} ps: shorter breaks are "
                       "invisible, so event durations are upper bounds and cannot be recovered from this trajectory")
    if max_gap_ps == 0 and frame_ps is not None:
        limited.append(f"continuous definition at the stored cadence ({frame_ps:g} ps): a break shorter than one frame is "
                       "not observed")
    return {"schema": SCHEMA, "run_id": run_id, "n_frames": int(n), "frame_interval_ps": frame_ps,
            "observation_ps": float(t[-1] - t[0]) + (frame_ps or 0.0) if n else 0.0,
            "n_segments": int(seg.max() + 1) if n else 0, "definition": "intermittent" if max_gap_ps > 0 else "continuous",
            "max_gap_ps": float(max_gap_ps), "occupancy_time_weighted": None if occ is None else round(occ, 6),
            "events": out_events, "limitations": limited,
            "note": "contact persistence is not ligand residence time or k_off"}


def kaplan_meier(durations: Iterable[float], censored: Iterable[bool]) -> dict:
    """Product-limit survival estimate; `censored` = right-censored (still on at the end)."""
    d = np.asarray(list(durations), float)
    c = np.asarray(list(censored), bool)
    order = np.argsort(d, kind="stable")
    d, c = d[order], c[order]
    times, surv, s = [0.0], [1.0], 1.0
    at_risk = len(d)
    i = 0
    while i < len(d):
        ti = d[i]
        deaths = int(((d == ti) & ~c).sum())
        total = int((d == ti).sum())
        if deaths and at_risk:
            s *= 1.0 - deaths / at_risk
            times.append(float(ti)); surv.append(float(s))
        at_risk -= total
        i += total
    return {"time_ps": times, "survival": surv}


def survival(tables: list[dict], *, min_events: int = 5) -> dict:
    """Pooled duration survival over several runs' event tables (each run analysed separately first; events from
    different runs are pooled as independent observations, never joined)."""
    evs = [e for t in tables for e in t["events"]]
    usable = [e for e in evs if not e["left_censored"]]
    n_left = len(evs) - len(usable)
    unc = [e for e in usable if not e["right_censored"]]
    km = kaplan_meier([e["duration_ps"] for e in usable], [e["right_censored"] for e in usable]) if usable else \
        {"time_ps": [0.0], "survival": [1.0]}
    obs = min((t["observation_ps"] for t in tables), default=0.0)
    out = {"schema": SCHEMA, "estimator": "Kaplan–Meier, right-censored; left-censored events excluded (unknown onset)",
           "n_events": len(evs), "n_left_censored_excluded": n_left, "n_right_censored": sum(e["right_censored"] for e in usable),
           "n_uncensored": len(unc), "max_identifiable_lag_ps": obs, "km": km, "lifetime_ps": None,
           "lifetime_definition": "time at which the survival estimate first falls to 1/e (no model fit)",
           "uncertainty": "not estimated (requires independent replicas; frames are not replicas)",
           "limitations": sorted({x for t in tables for x in t["limitations"]})}
    if len(unc) < min_events:
        out["lifetime_reason"] = f"only {len(unc)} uncensored event(s) (< {min_events}); no lifetime is reported"
        return out
    s = np.asarray(km["survival"])
    below = np.nonzero(s <= math.exp(-1))[0]
    if not len(below):
        out["lifetime_reason"] = "the survival estimate never falls to 1/e inside the observation window; the lifetime is " \
                                 "longer than can be identified here"
        return out
    out["lifetime_ps"] = float(km["time_ps"][int(below[0])])
    return out


def persistence_for_runs(series: dict[str, dict], *, max_gap_ps: float = 0.0, min_events: int = 5) -> dict:
    """series[run_id] = {"on": [...], "time_ps": [...], "segment_ids": optional}.  Runs are never concatenated."""
    tables = [events(v["on"], v["time_ps"], run_id=rid, max_gap_ps=max_gap_ps, segment_ids=v.get("segment_ids"))
              for rid, v in series.items()]
    occ = [t["occupancy_time_weighted"] for t in tables if t["occupancy_time_weighted"] is not None]
    return {"schema": SCHEMA, "per_run": tables, "survival": survival(tables, min_events=min_events),
            "occupancy_per_run": {t["run_id"]: t["occupancy_time_weighted"] for t in tables},
            "occupancy_spread": None if len(occ) < 2 else {"min": min(occ), "max": max(occ)},
            "n_independent_runs": len(tables)}
