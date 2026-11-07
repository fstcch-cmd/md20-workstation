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


def _segments(t: np.ndarray, segment_ids: np.ndarray | None, max_dt_factor: float,
              reference_dt_ps: float | None = None) -> np.ndarray:
    """Segment number per frame; a new segment starts at every recorded discontinuity or anomalous time jump.
    `reference_dt_ps` replaces the median step as the yardstick of an anomalous jump (needed when the series arrives in
    chunks and the global median is not yet known)."""
    n = len(t)
    seg = np.zeros(n, int)
    if n < 2:
        return seg
    dt = np.diff(t)
    med = float(reference_dt_ps) if reference_dt_ps else (float(np.median(dt)) if len(dt) else 0.0)
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


# --------------------------------------------------------------------------------------------- resolution record
def resolution_record(time_ps: Iterable[float] | None, *, source_frame_interval_ps: float | None = None,
                      effective_stride: int | None = None, n_frames_source: int | None = None,
                      origin: str | None = None) -> dict:
    """R3 (D-135): what temporal resolution an event/occupancy estimate actually has.

      source_frame_interval_ps  interval between STORED frames of the production DCDs
      effective_stride          every k-th stored frame was analysed (1 = every stored frame; None = not declared)
      effective_interval_ps     interval between the frames that really entered the estimate (median step)
      n_frames_source / n_frames_used / observation_length_ps
      resolution.status         "full"       every stored frame was used;
                                "limited"    effective stride > 1: breaks shorter than the effective interval are
                                             invisible, event durations are upper bounds (not recoverable afterwards);
                                "unverified" the caller did not declare a stride, so full resolution is not claimed
    Never relabels contact persistence as residence time or k_off."""
    t = np.asarray(list(time_ps), float) if time_ps is not None else np.zeros(0)
    n_used = int(len(t))
    dt = np.diff(t) if n_used > 1 else np.zeros(0)
    eff = float(np.median(dt[dt > 0])) if (dt > 0).any() else None
    k = None if effective_stride is None else max(1, int(effective_stride))
    src = source_frame_interval_ps
    if src is None and eff is not None and k:
        src = eff / k
    reasons: list[str] = []
    if k is None:
        status = "unverified"
        reasons.append("the caller did not state the frame stride used to load this trajectory; full stored-frame "
                       "resolution is not claimed")
    elif k > 1:
        status = "limited"
        iv = f"{eff:g} ps" if eff is not None else "the effective interval"
        reasons.append(f"effective stride {k} (every {k}th stored frame, effective interval {iv}): interruptions shorter "
                       f"than {iv} are invisible and event durations are upper bounds; this cannot be recovered from the "
                       "decimated frames, and it is contact persistence, not residence time or k_off")
    else:
        status = "full"
    obs = float(t[-1] - t[0]) + (eff or 0.0) if n_used else 0.0
    return {"schema": "md20.resolution/1", "source_frame_interval_ps": None if src is None else round(float(src), 6),
            "effective_stride": k, "effective_interval_ps": None if eff is None else round(eff, 6),
            "n_frames_source": None if n_frames_source is None else int(n_frames_source), "n_frames_used": n_used,
            "observation_length_ps": round(obs, 6), "origin": origin or "all frames given to the estimator",
            "resolution": {"status": status, "reasons": reasons}}


# --------------------------------------------------------------------------------------------- event accumulator
class EventAccumulator:
    """Event tables for many interactions of ONE run, fed chunk by chunk (D-135, R3).

    State carried across chunks: the open run of every interaction, the previous frame's time and segment id, the
    reference step used to recognise anomalous time jumps.  A run never crosses a segment break (recorded
    `segment_ids` change, non-positive step, or a step larger than `max_dt_factor` × the reference step); separate
    runs/replicas get separate accumulators and are never concatenated.  `events()` is this class fed in one piece,
    so chunked and unchunked results are identical by construction (tested)."""

    def __init__(self, *, run_id: str, max_gap_ps: float = 0.0, max_dt_factor: float = 1.5,
                 reference_dt_ps: float | None = None):
        self.run_id, self.max_gap_ps, self.max_dt_factor = run_id, float(max_gap_ps), float(max_dt_factor)
        self.ref = float(reference_dt_ps) if reference_dt_ps else None
        self.ref_declared = bool(reference_dt_ps)
        self.t: list[float] = []
        self.seg: list[int] = []
        self._last_sid = None
        self._state: dict = {}                      # key → {"runs": [(a, b)], "open": start index or None}
        self.n_updates = 0

    @property
    def n(self) -> int:
        return len(self.t)

    def keys(self) -> list:
        return list(self._state)

    def update(self, on: dict, time_ps: Iterable[float], segment_ids: Iterable | None = None) -> None:
        t = np.asarray(list(time_ps), float)
        m = len(t)
        sid = None if segment_ids is None else np.asarray(list(segment_ids))
        if sid is not None and len(sid) != m:
            raise ValueError("segment_ids and time_ps must have the same length")
        arrs = {k: np.asarray(v, bool) for k, v in on.items()}
        for k, a in arrs.items():
            if len(a) != m:
                raise ValueError("on and time_ps must have the same length")
        if not m:
            return
        n0 = self.n
        steps = np.diff(np.concatenate([[self.t[-1]], t])) if n0 else np.diff(t)    # step INTO frames (n0 ? 0 : 1) …
        if self.ref is None and len(steps) and (steps > 0).any():
            self.ref = float(np.median(steps))                     # first data with ≥ 2 frames fixes the yardstick
        b = steps <= 0
        if self.ref and self.ref > 0:
            b |= steps > self.max_dt_factor * self.ref
        if sid is not None:
            prev_sid = np.concatenate([[self._last_sid], sid]) if n0 and self._last_sid is not None else sid
            if n0 and self._last_sid is None:
                b = b | np.concatenate([[False], sid[1:] != sid[:-1]])
            else:
                b = b | (prev_sid[1:] != prev_sid[:-1])
        brk = b if n0 else np.concatenate([[False], b])          # brk[i]: frame i starts a new segment
        seg = (self.seg[-1] if n0 else 0) + np.cumsum(brk)
        self.t += t.tolist()
        self.seg += seg.tolist()
        if sid is not None:
            self._last_sid = sid[-1]
        for k in list(arrs):
            self._state.setdefault(k, {"runs": [], "open": None})
        zeros = np.zeros(m, bool)
        for k, st in self._state.items():
            a = arrs.get(k, zeros)
            was_open = st["open"] is not None
            if was_open and (brk[0] or not a[0]):                   # the carried run ends at the last stored frame
                st["runs"].append((st["open"], n0 - 1)); st["open"] = None; was_open = False
            prev = np.empty(m, bool)
            prev[0] = was_open
            prev[1:] = a[:-1] & ~brk[1:]
            nxt = np.empty(m, bool)
            nxt[:-1] = a[1:] & ~brk[1:]
            nxt[-1] = True                                         # the last frame's successor is unknown until later
            starts = (np.nonzero(a & ~prev)[0] + n0).tolist()
            ends = (np.nonzero(a & ~nxt)[0] + n0).tolist()
            starts_all = ([st["open"]] if was_open else []) + starts
            for s_, e_ in zip(starts_all, ends):
                st["runs"].append((int(s_), int(e_)))
            st["open"] = int(starts_all[-1]) if len(starts_all) > len(ends) else None
        self.n_updates += 1

    # ------------------------------------------------------------------------------------------ result
    def result(self, key, *, window: tuple[float, float] | None = None, resolution: dict | None = None) -> dict:
        t = np.asarray(self.t, float)
        seg = np.asarray(self.seg, int)
        n = len(t)
        st = self._state.get(key, {"runs": [], "open": None})
        runs = list(st["runs"]) + ([(st["open"], n - 1)] if st["open"] is not None else [])
        dt = np.diff(t)
        frame_ps = float(np.median(dt[dt > 0])) if (len(dt) and (dt > 0).any()) else None
        first = {int(s): int(np.argmax(seg == s)) for s in np.unique(seg)} if n else {}
        last = {int(s): int(n - 1 - np.argmax(seg[::-1] == s)) for s in np.unique(seg)} if n else {}
        merged: list[list] = []
        for a, b in runs:
            if merged and self.max_gap_ps > 0 and seg[a] == seg[merged[-1][1]]:
                prev = merged[-1][1]
                off_ps = float(t[a] - t[prev]) - (frame_ps or 0.0)        # time spent off between the two runs
                if off_ps <= self.max_gap_ps + 1e-9:
                    merged[-1][2].append({"from_frame": int(prev + 1), "frames": int(a - prev - 1), "off_ps": round(off_ps, 6)})
                    merged[-1][1] = b
                    continue
            merged.append([a, b, []])
        out_events = []
        for a, b, gaps in merged:
            # duration counts each stored frame as one interval of the local cadence (half-open, so a single
            # on-frame lasts one frame interval); this is a resolution-limited estimate, not an exact lifetime
            dur = float(t[b] - t[a]) + (frame_ps or 0.0)
            s = int(seg[a])
            ev = {"run_id": self.run_id, "segment": s, "start_frame": int(a), "end_frame": int(b),
                  "start_ps": float(t[a]), "end_ps": float(t[b]), "duration_ps": round(dur, 6),
                  "interruptions": len(gaps), "interrupted_frames": int(sum(g["frames"] for g in gaps)),
                  "left_censored": bool(a == first[s]), "right_censored": bool(b == last[s])}
            if window is not None:
                ev["in_window"] = bool(t[a] >= window[0] and t[b] <= window[1])
            out_events.append(ev)
        # time-weighted occupancy: each frame weighted by its own interval (irregular timestamps allowed)
        w = np.full(n, frame_ps or 1.0)
        if n > 1:
            same = seg[1:] == seg[:-1]
            w[:-1] = np.where(same, np.clip(np.diff(t), 0, None), frame_ps or 1.0)   # no weight across a discontinuity
        cw = np.concatenate([[0.0], np.cumsum(w)])
        on_w = sum(float(cw[b + 1] - cw[a]) for a, b in runs)
        occ = float(on_w / w.sum()) if n and w.sum() > 0 else (None if not n else 0.0)
        limited = []
        stride_limited = bool(resolution and (resolution.get("resolution") or {}).get("status") == "limited")
        cadence_limited = False
        if frame_ps is not None and self.max_gap_ps > 0 and frame_ps > self.max_gap_ps:
            cadence_limited = True
            limited.append(f"stored frame interval {frame_ps:g} ps > allowed interruption {self.max_gap_ps:g} ps: shorter breaks are "
                           "invisible, so event durations are upper bounds and cannot be recovered from this trajectory")
        if self.max_gap_ps == 0 and frame_ps is not None:
            limited.append(f"continuous definition at the stored cadence ({frame_ps:g} ps): a break shorter than one frame is "
                           "not observed")
        if stride_limited:
            limited += list(resolution["resolution"]["reasons"])
        out = {"schema": SCHEMA, "run_id": self.run_id, "n_frames": int(n), "frame_interval_ps": frame_ps,
               "observation_ps": float(t[-1] - t[0]) + (frame_ps or 0.0) if n else 0.0,
               "n_segments": int(seg.max() + 1) if n else 0, "definition": "intermittent" if self.max_gap_ps > 0 else "continuous",
               "max_gap_ps": float(self.max_gap_ps), "occupancy_time_weighted": None if occ is None else round(occ, 6),
               "events": out_events, "limitations": limited,
               "status": "limited" if (stride_limited or cadence_limited) else "computed",
               "note": "contact persistence is not ligand residence time or k_off"}
        if resolution is not None:
            out["resolution"] = resolution
        return out


def events(on: Iterable[bool], time_ps: Iterable[float], *, run_id: str, max_gap_ps: float = 0.0,
           segment_ids: Iterable | None = None, max_dt_factor: float = 1.5, window: tuple[float, float] | None = None,
           reference_dt_ps: float | None = None, resolution: dict | None = None) -> dict:
    """Event table for one interaction in one run (the unchunked form of `EventAccumulator`)."""
    on = np.asarray(list(on), bool)
    t = np.asarray(list(time_ps), float)
    if len(on) != len(t):
        raise ValueError("on and time_ps must have the same length")
    acc = EventAccumulator(run_id=run_id, max_gap_ps=max_gap_ps, max_dt_factor=max_dt_factor, reference_dt_ps=reference_dt_ps)
    acc.update({"x": on}, t, segment_ids)
    if not len(t):
        acc._state.setdefault("x", {"runs": [], "open": None})
    return acc.result("x", window=window, resolution=resolution)


def select_interactions(occupancy: dict, *, min_occupancy: float = 0.1, top: int = 12) -> list[tuple[str, str]]:
    """(residue, label) pairs worth an event table: per label the `top` residues whose occupancy ≥ min_occupancy.
    `occupancy` = {label: {residue: fraction of frames}} (interactions.fingerprint)."""
    out = []
    for lab, occ in (occupancy or {}).items():
        for r, v in sorted(occ.items(), key=lambda kv: -kv[1])[:top]:
            if v >= min_occupancy:
                out.append((r, lab))
    return out


def persistence_report(acc: EventAccumulator, selected: list[tuple[str, str]], *, resolution: dict | None = None,
                       source: str = "stored frames given to the estimator") -> dict:
    """Per-interaction event tables + lifetime for the selected (residue, label) pairs of one run.  `status` is
    "limited" when the resolution is limited (effective stride > 1) or the cadence exceeds the allowed interruption,
    "unverified" when no stride was declared; otherwise "computed"."""
    items = []
    any_limited = False
    for r, lab in selected:
        ev = acc.result((r, lab), resolution=resolution)
        sv = survival([ev])
        lim = ev["status"] == "limited"
        any_limited |= lim
        item = {"residue": r, "label": lab, "occupancy_time_weighted": ev["occupancy_time_weighted"],
                "n_events": len(ev["events"]), "events": ev["events"], "limitations": ev["limitations"],
                "lifetime_ps": sv["lifetime_ps"], "lifetime_reason": sv.get("lifetime_reason"),
                "n_left_censored_excluded": sv["n_left_censored_excluded"], "status": ev["status"]}
        if lim:
            item["lifetime_qualifier"] = "upper bound at the effective resolution; not a residence time or k_off"
        items.append(item)
    rstat = ((resolution or {}).get("resolution") or {}).get("status")
    status = "limited" if (rstat == "limited" or any_limited) else ("unverified" if rstat == "unverified" else "computed")
    out = {"status": status, "definition": "continuous" if acc.max_gap_ps <= 0 else "intermittent",
           "max_gap_ps": acc.max_gap_ps, "items": items, "source": source,
           "note": "contact persistence is not ligand residence time, not k_off, and not experimentally validated stability"}
    if resolution is not None:
        out["resolution"] = resolution
        if rstat == "limited":
            out["reason"] = "; ".join(resolution["resolution"]["reasons"])
    return out


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
