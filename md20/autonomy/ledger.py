"""D-137 (R8): the append-only action ledger.

`<workflow>/autonomy/ledger.jsonl` — one JSON object per line, never rewritten.  Every state-changing call takes the
cross-platform `FileLock` (msvcrt on Windows, flock on POSIX, lock directory as a last resort), re-reads the file,
decides, and appends — so a duplicate proposal, a second worker or a reconnecting GUI sees the first one's records
*before* it can launch anything.  Launch happens only after `claim()` has durably appended `exec_start`.

Events: proposed · authorization · approval · exec_start · exec_end · post_assessment · cancel_requested · stop · resume ·
escalate · observed · observed_end.  `state.json` is a derived snapshot (atomic write, rebuilt from the JSONL when it is
stale or missing); the JSONL is the only source of truth.

Recorded resource use is kept apart from simulated time: `exec_end.resources` (wall seconds, GPU/core hours, storage) vs
`exec_end.simulated_ps`.  Failed, cancelled and retried attempts are all charged (operational cost); a missing report is
charged at the proposal's estimate and labelled so.
"""
from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..util import FileLock, atomic_write_json, now_iso
from .model import (DIMS, SCHEMA, ActionProposal, AuthorizationDecision, Policy, authorize, remaining_budget,
                    OUT_AUTHORIZED, OUT_BUDGET)

LEDGER_NAME = "ledger.jsonl"
STATE_NAME = "state.json"
LOCK_NAME = "ledger.lock"

# proposal statuses
ST_PROPOSED, ST_AUTHORIZED, ST_AWAITING, ST_RECOMMENDED = "proposed", "authorized", "awaiting_approval", "recommended"
ST_DENIED, ST_BLOCKED, ST_RUNNING, ST_SUCCEEDED = "denied", "blocked", "running", "succeeded"
ST_FAILED, ST_CANCELLED, ST_ESCALATED, ST_EXHAUSTED, ST_OBSERVED = "failed", "cancelled", "escalated", "attempts_exhausted", "observed"
STICKY = {ST_RUNNING, ST_SUCCEEDED, ST_CANCELLED, ST_EXHAUSTED}      # an authorization/escalation event never overwrites these
_OUTCOME_STATUS = {"authorized": ST_AUTHORIZED, "needs_approval": ST_AWAITING, "recommendation_only": ST_RECOMMENDED,
                   "denied": ST_DENIED, "blocked": ST_BLOCKED, "budget_exhausted": ST_AWAITING}


# ------------------------------------------------------------------------------------------------ state
@dataclass
class ProposalState:
    key: str
    proposal: dict
    scope: str
    source: str = "controller"
    status: str = ST_PROPOSED
    attempts: list = field(default_factory=list)
    authorization: dict | None = None
    approvals: list = field(default_factory=list)
    cancel_requested: dict | None = None
    post_assessment: dict | None = None
    last_reason: str | None = None
    last_error_kind: str | None = None

    @property
    def running(self) -> dict | None:
        return next((a for a in self.attempts if a.get("ended_at") is None), None)

    def snapshot(self) -> dict:
        return {"status": self.status, "action": self.proposal.get("action_type"), "scope": self.scope,
                "attempts": len(self.attempts), "last_reason": self.last_reason, "source": self.source}


@dataclass
class LedgerState:
    proposals: dict = field(default_factory=dict)          # key → ProposalState
    scopes: dict = field(default_factory=dict)             # scope → {"stopped": {...}|None, "streak": int, "escalations": [...]}
    spent: dict = field(default_factory=lambda: {d: 0.0 for d in DIMS})
    reserved: dict = field(default_factory=lambda: {d: 0.0 for d in DIMS})
    observed_ps: float = 0.0
    last_seq: int = 0
    bad_lines: int = 0

    def committed(self) -> dict:
        return {d: round(self.spent[d] + self.reserved[d], 9) for d in DIMS}

    def scope(self, name: str) -> dict:
        return self.scopes.setdefault(name, {"stopped": None, "streak": 0, "escalations": []})

    def snapshot(self) -> dict:
        return {"schema": SCHEMA, "last_seq": self.last_seq, "bad_lines": self.bad_lines,
                "spent": dict(self.spent), "reserved": dict(self.reserved),
                "scopes": {k: {"stopped": v["stopped"], "streak": v["streak"]} for k, v in self.scopes.items()},
                "proposals": {k: v.snapshot() for k, v in self.proposals.items()}}


def fold(records: list[dict], bad_lines: int = 0) -> LedgerState:
    st = LedgerState(bad_lines=bad_lines)
    for r in records:
        ev, key = r.get("event"), r.get("key")
        st.last_seq = max(st.last_seq, int(r.get("seq") or 0))
        ps: ProposalState | None = st.proposals.get(key) if key else None
        if ev in ("proposed", "observed"):
            if key and key not in st.proposals:
                p = r.get("proposal") or {}
                st.proposals[key] = ProposalState(key=key, proposal=p, scope=str(r.get("scope") or p.get("scope") or ""),
                                                  source=("controller" if ev == "proposed" else str(r.get("source") or "observed")),
                                                  status=ST_PROPOSED if ev == "proposed" else ST_OBSERVED)
                if ev == "observed":
                    st.observed_ps += float(r.get("simulated_ps_estimate") or 0.0)
        elif ev == "authorization" and ps is not None:
            ps.authorization = r.get("decision")
            if ps.status not in STICKY:
                ps.status = _OUTCOME_STATUS.get((r.get("decision") or {}).get("outcome"), ps.status)
            ps.last_reason = (r.get("decision") or {}).get("reason")
        elif ev == "approval" and ps is not None:
            ps.approvals.append({"by": r.get("by"), "at": r.get("at"), "note": r.get("note")})
            if ps.status in (ST_AWAITING, ST_PROPOSED):
                ps.status = ST_AUTHORIZED
        elif ev == "exec_start" and ps is not None:
            ps.attempts.append({"attempt": r.get("attempt"), "started_at": r.get("at"), "worker": r.get("worker"),
                                "pid": r.get("pid"), "host": r.get("host"), "reserved": r.get("reserved") or {},
                                "ended_at": None, "status": None})
            ps.status = ST_RUNNING
            for d in DIMS:
                st.reserved[d] += float((r.get("reserved") or {}).get(d) or 0.0)
        elif ev == "exec_end" and ps is not None:
            a = next((x for x in ps.attempts if x.get("attempt") == r.get("attempt") and x.get("ended_at") is None), None)
            if a is not None:
                for d in DIMS:
                    st.reserved[d] = max(0.0, st.reserved[d] - float(a["reserved"].get(d) or 0.0))
                a.update(ended_at=r.get("at"), status=r.get("status"), resources=r.get("resources") or {},
                         simulated_ps=r.get("simulated_ps"), charged=r.get("charged") or {},
                         charged_from=r.get("charged_from") or {}, error=r.get("error"), error_kind=r.get("error_kind"))
            for d in DIMS:
                st.spent[d] += float((r.get("charged") or {}).get(d) or 0.0)
            ps.last_error_kind = r.get("error_kind")
            ps.last_reason = r.get("error") or ps.last_reason
            s = r.get("status")
            ps.status = (ST_SUCCEEDED if s == "ok" else ST_CANCELLED if s == "cancelled" else ST_FAILED)
        elif ev == "post_assessment" and ps is not None:
            ps.post_assessment = r.get("summary")
            sc = st.scope(ps.scope)
            sc["streak"] = 0 if r.get("improved") else sc["streak"] + 1
        elif ev == "cancel_requested" and ps is not None:
            ps.cancel_requested = {"by": r.get("by"), "at": r.get("at")}
            if ps.running is None and ps.status != ST_SUCCEEDED:
                ps.status = ST_CANCELLED
        elif ev == "escalate":
            reason = r.get("reason")
            if ps is not None:
                ps.last_reason = f"{reason}: {r.get('detail') or ''}".strip()
                if ps.status not in STICKY:
                    ps.status = ST_ESCALATED
                if reason == "attempts_exhausted" and ps.status != ST_SUCCEEDED:
                    ps.status = ST_EXHAUSTED
            scope = r.get("scope") or (ps.scope if ps is not None else None)
            if scope:
                st.scope(scope)["escalations"].append({"reason": reason, "detail": r.get("detail"), "at": r.get("at"),
                                                       "key": key, "options": r.get("options")})
        elif ev == "stop":
            st.scope(str(r.get("scope")))["stopped"] = {"reason": r.get("reason"), "detail": r.get("detail"), "at": r.get("at")}
        elif ev == "resume":
            sc = st.scope(str(r.get("scope")))
            sc["stopped"], sc["streak"] = None, 0
    return st


# ------------------------------------------------------------------------------------------------ results
@dataclass
class Claim:
    ok: bool
    reason: str = ""                  # machine reason when refused: already_running | already_done | cancelled | attempts_exhausted | scope_stopped | not_authorized | ledger_corrupt
    attempt: int = 0
    decision: AuthorizationDecision | None = None
    detail: str = ""


class Ledger:
    def __init__(self, directory: Path | str, *, clock: Callable[[], str] = now_iso, lock_timeout: float = 30.0):
        self.dir = Path(directory)
        self.path = self.dir / LEDGER_NAME
        self.state_path = self.dir / STATE_NAME
        self.lock_path = self.dir / LOCK_NAME
        self.clock = clock
        self.lock_timeout = lock_timeout
        self.host = socket.gethostname()

    # ---- reading
    def _read_raw(self) -> tuple[list[dict], int]:
        if not self.path.is_file():
            return [], 0
        data = self.path.read_bytes()
        records, bad = [], 0
        lines = data.split(b"\n")
        unterminated = not data.endswith(b"\n") and bool(data)
        for i, ln in enumerate(lines):
            if not ln.strip():
                continue
            if unterminated and i == len(lines) - 1:
                try:                                     # complete record that only lacks its newline
                    records.append(json.loads(ln.decode("utf-8")))
                except (ValueError, UnicodeDecodeError):
                    pass                                 # torn tail: the append never completed, so it never took effect
                continue
            try:
                row = json.loads(ln.decode("utf-8"))
                if isinstance(row, dict):
                    records.append(row)
                else:
                    bad += 1
            except (ValueError, UnicodeDecodeError):
                bad += 1
        return records, bad

    def records(self) -> list[dict]:
        return self._read_raw()[0]

    def state(self) -> LedgerState:
        recs, bad = self._read_raw()
        return fold(recs, bad)

    def integrity(self) -> dict:
        recs, bad = self._read_raw()
        return {"ok": bad == 0, "bad_lines": bad, "records": len(recs)}

    # ---- writing (call only with the lock held)
    def _repair_tail(self) -> None:
        """A crash mid-append can leave a last line without its newline.  The append had not returned, so nothing was
        launched on its strength: keep a copy in ledger.jsonl.torn and cut it off (or just add the missing newline)."""
        if not self.path.is_file():
            return
        data = self.path.read_bytes()
        if not data or data.endswith(b"\n"):
            return
        cut = data.rfind(b"\n") + 1
        frag = data[cut:]
        try:
            json.loads(frag.decode("utf-8"))
            with open(self.path, "ab") as fh:
                fh.write(b"\n")
            return
        except (ValueError, UnicodeDecodeError):
            pass
        with open(self.path.with_suffix(self.path.suffix + ".torn"), "ab") as fh:
            fh.write(frag + b"\n")
        with open(self.path, "r+b") as fh:
            fh.truncate(cut)

    def _append(self, st: LedgerState, event: str, **fields) -> dict:
        rec = {"seq": st.last_seq + 1, "at": self.clock(), "event": event, **fields}
        line = json.dumps(rec, ensure_ascii=False, sort_keys=True, default=str, allow_nan=False) + "\n"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._repair_tail()
        with open(self.path, "ab") as fh:
            fh.write(line.encode("utf-8"))
            fh.flush()
            os.fsync(fh.fileno())
        st.last_seq = rec["seq"]
        return rec

    def _lock(self) -> FileLock:
        return FileLock(self.lock_path, timeout=self.lock_timeout)

    def _write_snapshot(self) -> None:
        try:
            atomic_write_json(self.state().snapshot(), self.state_path, backup=False)
        except OSError:
            pass                                          # derived cache only (e.g. Windows: a reader holds the file)

    def append(self, event: str, **fields) -> dict:
        with self._lock():
            st = self.state()
            rec = self._append(st, event, **fields)
        self._write_snapshot()
        return rec

    # ---- proposals
    def propose(self, p: ActionProposal, *, source: str = "controller") -> tuple[ProposalState, bool]:
        """Record a proposal once.  A duplicate (same idempotency key) writes nothing and returns the existing state."""
        with self._lock():
            st = self.state()
            existing = st.proposals.get(p.idempotency_key)
            if existing is not None:
                return existing, False
            self._append(st, "proposed", key=p.idempotency_key, scope=p.scope, proposal=p.to_dict(), source=source)
        self._write_snapshot()
        return self.state().proposals[p.idempotency_key], True

    def observe(self, p: ActionProposal, *, source: str, simulated_ps_estimate: float | None = None, note: str = "") -> bool:
        """Record an action that *existing* automation (not this controller, not governed by a policy) plans or took.
        Idempotent per key; never charged against a policy budget."""
        with self._lock():
            st = self.state()
            if p.idempotency_key in st.proposals:
                return False
            self._append(st, "observed", key=p.idempotency_key, scope=p.scope, proposal=p.to_dict(), source=source,
                         simulated_ps_estimate=simulated_ps_estimate, note=note,
                         authorization="existing_workflow_automation（不受自主行動政策管轄）")
        self._write_snapshot()
        return True

    def record_authorization(self, key: str, decision: AuthorizationDecision) -> bool:
        """Append the decision only when it differs from the last recorded one (polling must not grow the file)."""
        with self._lock():
            st = self.state()
            ps = st.proposals.get(key)
            if ps is None:
                return False
            last = ps.authorization or {}
            if last.get("outcome") == decision.outcome and last.get("reason") == decision.reason and \
                    last.get("by") == decision.by:
                return False
            self._append(st, "authorization", key=key, decision=decision.to_dict())
        self._write_snapshot()
        return True

    def approve(self, key: str, by: str, note: str = "") -> bool:
        if not by or not str(by).strip():
            raise ValueError("核准必須記錄是誰核准的")
        with self._lock():
            st = self.state()
            if key not in st.proposals:
                return False
            self._append(st, "approval", key=key, by=str(by).strip(), note=note)
        self._write_snapshot()
        return True

    def request_cancel(self, key: str, by: str) -> bool:
        with self._lock():
            st = self.state()
            ps = st.proposals.get(key)
            if ps is None or ps.cancel_requested is not None:
                return False
            self._append(st, "cancel_requested", key=key, by=by)
        self._write_snapshot()
        return True

    def cancel_requested(self, key: str) -> bool:
        ps = self.state().proposals.get(key)
        return bool(ps and ps.cancel_requested)

    # ---- the one place a launch is decided
    def claim(self, p: ActionProposal, policy: Policy | None, *, worker: str, limit_attempts: int | None = None) -> Claim:
        """Atomically: re-read the ledger under the lock, check idempotency / stop / authorization / budget / attempt
        limit, and append `exec_start` (reserving the estimate).  Only a caller that gets `Claim.ok` may launch."""
        with self._lock():
            st = self.state()
            if st.bad_lines:
                return Claim(False, "ledger_corrupt", detail=f"帳本有 {st.bad_lines} 行無法解析，不執行（需人工檢查）")
            ps = st.proposals.get(p.idempotency_key)
            if ps is None:
                return Claim(False, "not_authorized", detail="提案尚未記入帳本")
            if ps.running is not None:
                a = ps.running
                return Claim(False, "already_running", detail=f"第 {a.get('attempt')} 次執行進行中（{a.get('worker')}，{a.get('started_at')}）")
            if ps.status == ST_SUCCEEDED:
                return Claim(False, "already_done", detail="這個行動（相同標的與證據狀態）已成功執行過")
            if ps.cancel_requested or ps.status == ST_CANCELLED:
                return Claim(False, "cancelled", detail="已被取消")
            if ps.status == ST_EXHAUSTED:
                return Claim(False, "attempts_exhausted", detail="重試次數已用完")
            sc = st.scope(p.scope)
            if sc["stopped"]:
                return Claim(False, "scope_stopped", detail=f"此範圍已停止：{sc['stopped'].get('reason')}")
            dec = authorize(p, policy, committed=st.committed(), approved=bool(ps.approvals), now=self.clock())
            if not dec.executable:
                return Claim(False, "not_authorized", decision=dec, detail=dec.reason)
            cap = min(int(p.max_attempts), int(policy.max_attempts)) if policy is not None else int(p.max_attempts)
            if limit_attempts is not None:
                cap = min(cap, int(limit_attempts))
            n = len(ps.attempts)
            if n >= cap:
                return Claim(False, "attempts_exhausted", decision=dec, detail=f"已嘗試 {n} 次，上限 {cap}")
            if n and ps.last_error_kind not in (None, "technical"):
                return Claim(False, "not_authorized", decision=dec, detail=f"上次失敗類型 {ps.last_error_kind} 不屬於可重試的技術性失敗")
            reserved = {d: (p.estimate.get(d) or 0.0) for d in DIMS}
            self._append(st, "exec_start", key=p.idempotency_key, attempt=n + 1, worker=worker, pid=os.getpid(),
                         host=self.host, reserved=reserved, decision=dec.to_dict())
        self._write_snapshot()
        return Claim(True, attempt=n + 1, decision=dec)

    def finish(self, p: ActionProposal, attempt: int, *, status: str, resources: dict | None = None,
               simulated_ps: float | None = None, error: str | None = None, error_kind: str | None = None) -> dict:
        """Close one attempt.  Charged = what was reported; a dimension the executor did not report is charged at the
        proposal's estimate (and labelled), so a crash or a silent executor cannot make a failed attempt look free."""
        resources = {k: v for k, v in (resources or {}).items() if v is not None}
        charged, source = {}, {}
        for d in DIMS:
            if d == "sim_ns":
                rep = None if simulated_ps is None else float(simulated_ps) / 1000.0
            else:
                rep = resources.get(d)
            if rep is not None:
                charged[d], source[d] = float(rep), "reported"
            else:
                est = p.estimate.get(d)
                charged[d], source[d] = (float(est) if est is not None else 0.0), ("estimate" if est is not None else "unknown")
        with self._lock():
            st = self.state()
            rec = self._append(st, "exec_end", key=p.idempotency_key, attempt=attempt, status=status, resources=resources,
                               simulated_ps=simulated_ps, charged=charged, charged_from=source, error=error,
                               error_kind=error_kind)
        self._write_snapshot()
        return rec

    def post_assessment(self, key: str, summary: dict, improved: bool) -> dict:
        return self.append("post_assessment", key=key, summary=summary, improved=bool(improved))

    def stop(self, scope: str, reason: str, detail: str = "") -> bool:
        """Stop a scope (idempotent: the same active stop is not written twice)."""
        with self._lock():
            st = self.state()
            cur = st.scope(scope)["stopped"]
            if cur and cur.get("reason") == reason:
                return False
            self._append(st, "stop", scope=scope, reason=reason, detail=detail)
        self._write_snapshot()
        return True

    def resume(self, scope: str, by: str) -> bool:
        if not by or not str(by).strip():
            raise ValueError("恢復必須記錄是誰決定的")
        with self._lock():
            st = self.state()
            if not st.scope(scope)["stopped"]:
                return False
            self._append(st, "resume", scope=scope, by=str(by).strip())
        self._write_snapshot()
        return True

    def escalate(self, reason: str, *, key: str | None = None, scope: str | None = None, detail: str = "",
                 options: list | None = None) -> bool:
        """Hand a decision to the user.  Idempotent: the same (key/scope, reason, detail) is recorded once."""
        with self._lock():
            st = self.state()
            ps = st.proposals.get(key) if key else None
            sc = scope or (ps.scope if ps is not None else None)
            seen = (st.scope(sc)["escalations"] if sc else [])
            if any(e.get("reason") == reason and e.get("key") == key and (e.get("detail") or "") == detail for e in seen[-20:]):
                return False
            self._append(st, "escalate", key=key, scope=sc, reason=reason, detail=detail, options=options or [])
        self._write_snapshot()
        return True

    def abandon(self, key: str, by: str, reason: str) -> bool:
        """A human (or a liveness probe) declares the running attempt dead.  Closed as a failed, retryable attempt that is
        charged at its estimate; the next launch is again limited by the attempt cap and the checkpoint check."""
        with self._lock():
            st = self.state()
            ps = st.proposals.get(key)
            a = ps.running if ps is not None else None
            if a is None:
                return False
            p = ActionProposal.from_dict(ps.proposal)
            est = {d: (p.estimate.get(d) or 0.0) for d in DIMS}
            self._append(st, "exec_end", key=key, attempt=a["attempt"], status="abandoned", resources={}, simulated_ps=None,
                         charged=est, charged_from={d: ("estimate" if p.estimate.get(d) is not None else "unknown") for d in DIMS},
                         error=f"{by}: {reason}", error_kind="technical")
        self._write_snapshot()
        return True

    def observe_end(self, key: str, *, simulated_ps: float | None, wall_s: float | None = None, ok: bool = True) -> bool:
        with self._lock():
            st = self.state()
            if key not in st.proposals:
                return False
            self._append(st, "observed_end", key=key, simulated_ps=simulated_ps, wall_s=wall_s, ok=bool(ok))
        self._write_snapshot()
        return True

    # ---- reporting
    def remaining(self, policy: Policy | None) -> dict:
        return remaining_budget(policy, self.state().committed())

    def cost_summary(self) -> dict:
        """Operational cost (every attempt, retries and failures included) kept separate from simulated time.  Legacy
        (observed) refinement actions are reported apart: they ran outside any policy."""
        recs = self.records()
        out = {"attempts": 0, "failed_attempts": 0, "cancelled_attempts": 0, "retries": 0,
               "resources": {"wall_s": 0.0, "gpu_hours": 0.0, "core_hours": 0.0, "storage_gb": 0.0},
               "charged": {d: 0.0 for d in DIMS}, "estimate_charged_attempts": 0,
               "simulated_ps_reported": 0.0, "simulated_ps_successful": 0.0, "by_action": {},
               "observed_legacy": {"actions": 0, "simulated_ps_estimate": 0.0, "simulated_ps_reported": 0.0}}
        st = fold(recs)
        for r in recs:
            ev = r.get("event")
            if ev == "exec_end":
                ps = st.proposals.get(r.get("key"))
                act = (ps.proposal.get("action_type") if ps else None) or "?"
                b = out["by_action"].setdefault(act, {"attempts": 0, "charged": {d: 0.0 for d in DIMS}})
                out["attempts"] += 1
                b["attempts"] += 1
                if r.get("status") not in ("ok",):
                    out["cancelled_attempts" if r.get("status") == "cancelled" else "failed_attempts"] += 1
                for k in out["resources"]:
                    out["resources"][k] += float((r.get("resources") or {}).get(k) or 0.0)
                for d in DIMS:
                    out["charged"][d] += float((r.get("charged") or {}).get(d) or 0.0)
                    b["charged"][d] += float((r.get("charged") or {}).get(d) or 0.0)
                if "estimate" in (r.get("charged_from") or {}).values():
                    out["estimate_charged_attempts"] += 1
                if r.get("simulated_ps") is not None:
                    out["simulated_ps_reported"] += float(r["simulated_ps"])
                    if r.get("status") == "ok":
                        out["simulated_ps_successful"] += float(r["simulated_ps"])
            elif ev == "observed":
                out["observed_legacy"]["actions"] += 1
                out["observed_legacy"]["simulated_ps_estimate"] += float(r.get("simulated_ps_estimate") or 0.0)
            elif ev == "observed_end" and r.get("simulated_ps") is not None:
                out["observed_legacy"]["simulated_ps_reported"] += float(r["simulated_ps"])
        out["retries"] = sum(max(0, len(ps.attempts) - 1) for ps in st.proposals.values())
        return out
