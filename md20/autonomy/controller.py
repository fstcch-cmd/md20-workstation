"""D-137 (R8): the bounded-autonomy controller.

    assess → propose → authorize → execute → reassess → stop / escalate

* **Default is recommendation-only.**  Without a usable `Policy` (approved by a person, with a budget and allowed action
  classes) the controller records proposals and decisions and executes nothing, even if an executor was supplied.
* **Nothing in this module launches anything by itself.**  Execution goes through the *injected* `executor` callable
  (tests pass fakes; the GUI/CLI would pass a wrapper around the existing Runner/ProcessJob).  The controller builds no
  commands and runs no strings.
* **Idempotent.**  Before an executor is called, `Ledger.claim()` appends `exec_start` under a file lock after re-reading
  the ledger: a duplicate proposal, a second worker or a GUI reconnect finds the first one's record and does not launch.
* **Bounded.**  Technical retries (same proposal, same checkpoint, same protocol — the request is identical every time)
  are capped by the proposal and by the policy and are charged to the budget.  Budget exhaustion, repeated
  no-improvement, an invalid model, an unreadable assessment or insufficient evidence stop the scope; a person resumes it.
* **Deterministic authority.**  Decisions come from the stored assessment objects and the policy.  No model output, no
  document or molecule metadata is ever interpreted as an instruction.
"""
from __future__ import annotations

import os
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..util import now_iso
from .ledger import Ledger, ST_CANCELLED, ST_EXHAUSTED, ST_RUNNING, ST_SUCCEEDED
from .model import (ACTION_LABEL_ZH, AuthorizationDecision, ActionProposal, Policy, authorize, load_policy, remaining_budget,
                    OUT_BUDGET, validate_proposal)
from .rules import AssessmentInputs, build_proposals, improved, summarize, validate_assessment

DEFAULT_NO_IMPROVEMENT_STOP = 2
USE_CONTROLLER_POLICY: Any = object()      # dry_run sentinel: None must mean 'no policy'

# stop / escalation reasons
R_BUDGET, R_NO_IMPROVEMENT, R_UNKNOWN_ASSESSMENT = "budget_exhausted", "no_improvement", "unknown_assessment"
R_INSUFFICIENT, R_INVALID_MODEL, R_GOAL = "insufficient_evidence", "invalid_model", "goal_met"
R_INVALID_CHECKPOINT, R_ATTEMPTS, R_FAILED = "invalid_checkpoint", "attempts_exhausted", "action_failed"


class ActionCancelled(Exception):
    """Raised by an executor that noticed the cancellation request and stopped cleanly."""


class TechnicalError(Exception):
    """A retryable technical failure (disk hiccup, process killed).  Any other exception is NOT retried."""


class CancelToken:
    def __init__(self):
        self._e = threading.Event()

    def cancel(self) -> None:
        self._e.set()

    def is_set(self) -> bool:
        return self._e.is_set()


@dataclass
class ExecutionRequest:
    """What the executor gets.  Identical on every retry of the same proposal: a retry cannot change the protocol."""
    proposal: dict
    key: str
    attempt: int
    max_attempts: int
    checkpoint: dict
    worker: str
    cancelled: Callable[[], bool]


@dataclass
class ExecutionResult:
    status: str = "ok"                         # ok | failed | cancelled
    resources: dict = field(default_factory=dict)      # wall_s, gpu_hours, core_hours, storage_gb — ACTUAL use
    simulated_ps: float | None = None          # simulated time produced — never mixed into `resources`
    error: str | None = None
    error_kind: str | None = None              # technical (retryable) | invalid_model | scientific | unexpected
    assessment: dict | None = None             # post-action assessment (if no separate reassessor)
    outputs: dict = field(default_factory=dict)

    @classmethod
    def coerce(cls, x) -> "ExecutionResult":
        if isinstance(x, cls):
            return x
        if x is None:
            return cls()
        if isinstance(x, dict):
            names = set(cls.__dataclass_fields__)
            return cls(**{k: v for k, v in x.items() if k in names})
        return cls(status="failed", error=f"執行器回傳了無法辨識的結果（{type(x).__name__}）", error_kind="unexpected")


@dataclass
class StepResult:
    scope: str
    proposals: list = field(default_factory=list)
    decisions: dict = field(default_factory=dict)         # key → AuthorizationDecision
    skipped: dict = field(default_factory=dict)           # key → why not considered again (already done / running / …)
    escalations: list = field(default_factory=list)
    stop: dict | None = None                              # {"reason", "detail"}
    summary: dict | None = None


@dataclass
class ExecutionOutcome:
    key: str
    action_type: str
    status: str = "not_executed"      # ok | failed | cancelled | not_executed
    reason: str = ""
    attempts: int = 0
    decision: AuthorizationDecision | None = None
    stop: dict | None = None
    improved: bool | None = None


@dataclass
class CycleReport:
    step: StepResult
    executed: list = field(default_factory=list)
    stop: dict | None = None


def default_checkpoint_validator(cp: dict) -> tuple[bool, str]:
    """A required checkpoint must be a non-empty file whose cheap fingerprint (size + edge hash) matches the one recorded
    when the run was approved.  No fingerprint recorded → cannot be verified → invalid (better blocked than guessed)."""
    if not isinstance(cp, dict) or not cp.get("required"):
        return True, ""
    path = cp.get("path")
    if not path:
        return False, "提案要求檢查點但沒有路徑"
    pth = Path(str(path))
    if not pth.is_file() or pth.stat().st_size == 0:
        return False, f"檢查點不存在或是空檔：{pth.name}"
    fp = cp.get("fingerprint")
    if not isinstance(fp, dict):
        return False, "檢查點沒有核准時記錄的指紋，無法確認未損毀"
    from ..util import verify_cheap_fingerprint
    try:
        ok = verify_cheap_fingerprint(pth, fp)
    except OSError as exc:
        return False, f"讀取檢查點失敗：{exc}"
    return (True, "") if ok else (False, f"檢查點內容與核准時的指紋不符（可能損毀或被換過）：{pth.name}")


class Controller:
    def __init__(self, ledger: Ledger | Path | str, policy: Policy | None = None, executor: Callable | None = None, *,
                 checkpoint_validator: Callable[[dict], tuple[bool, str]] = default_checkpoint_validator,
                 reassessor: Callable[[dict, ExecutionResult], dict | None] | None = None,
                 worker: str | None = None, clock: Callable[[], str] = now_iso):
        self.ledger = ledger if isinstance(ledger, Ledger) else Ledger(ledger, clock=clock)
        self.policy = policy
        self.executor = executor
        self.checkpoint_validator = checkpoint_validator
        self.reassessor = reassessor
        self.worker = worker or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self.clock = clock

    @classmethod
    def for_workflow(cls, workflow_dir: Path | str, executor: Callable | None = None, **kw) -> "Controller":
        """Ledger under `<workflow>/autonomy/`; policy from `autonomy_policy.json` there if the user wrote one."""
        policy, _ = load_policy(workflow_dir)
        return cls(Path(workflow_dir) / "autonomy", policy=policy, executor=executor, **kw)

    # ------------------------------------------------------------------ mode
    @property
    def recommendation_only(self) -> bool:
        return self.executor is None or self.policy is None or not self.policy.effective()[0]

    # ------------------------------------------------------------------ assess → propose
    def _no_improvement_limit(self) -> int:
        return self.policy.no_improvement_stop if self.policy is not None else DEFAULT_NO_IMPROVEMENT_STOP

    def _plan(self, inputs: AssessmentInputs) -> tuple[list[ActionProposal], list[dict], dict | None, dict | None]:
        """Pure: (proposals, escalations, stop, summary).  Reads the ledger only for an already-recorded scope stop and
        for the no-improvement streak."""
        st = self.ledger.state()
        sc = st.scope(inputs.scope)
        if sc["stopped"]:
            s = sc["stopped"]
            return [], [], {"reason": s.get("reason"), "detail": f"此範圍已停止，需使用者恢復：{s.get('detail') or ''}", "persisted": True}, None
        if inputs.invalid_models:
            return [], [], {"reason": R_INVALID_MODEL, "detail": "未解決的無效模型：" + "、".join(str(m)[:60] for m in inputs.invalid_models[:5])}, None
        problems = validate_assessment(inputs.assessment)
        if problems:
            return [], [], {"reason": R_UNKNOWN_ASSESSMENT, "detail": "；".join(problems)}, None
        summ = summarize(inputs.assessment)
        if summ["sampling_adequate"] is True:
            return [], [], {"reason": R_GOAL, "detail": "評估認為取樣已足夠；不需要行動。", "persisted": False}, summ
        if sc["streak"] >= self._no_improvement_limit():
            return [], [], {"reason": R_NO_IMPROVEMENT, "detail": f"連續 {sc['streak']} 個已執行的行動後評估都沒有改善（上限 {self._no_improvement_limit()}）。"}, summ
        props, esc = build_proposals(inputs, summ)
        if not props:
            reason = esc[0]["reason"] if esc else R_INSUFFICIENT
            detail = esc[0]["detail"] if esc else "沒有失敗或未知的診斷可對應到支援的行動，但評估也未判定取樣足夠。"
            return [], esc, {"reason": reason, "detail": detail}, summ
        return props, esc, None, summ

    def step(self, assessment_inputs, *, record: bool = True) -> StepResult:
        inputs = AssessmentInputs.from_any(assessment_inputs)
        props, esc, stop, summ = self._plan(inputs)
        res = StepResult(scope=inputs.scope, escalations=esc, stop=stop, summary=summ)
        if record:
            for e in esc:
                self.ledger.escalate(e["reason"], scope=inputs.scope, detail=e["detail"], options=e.get("options"))
            if stop and stop.get("persisted", True) and stop["reason"] != R_GOAL:
                self.ledger.stop(inputs.scope, stop["reason"], stop["detail"])
        if not record:
            res.proposals = props
            return res
        for p in props:
            ps, new = self.ledger.propose(p)
            res.proposals.append(p)
            if ps.status in (ST_SUCCEEDED, ST_RUNNING, ST_CANCELLED, ST_EXHAUSTED):
                res.skipped[p.idempotency_key] = ps.status
                continue
            res.decisions[p.idempotency_key] = self.authorize(p)
        return res

    # ------------------------------------------------------------------ authorize
    def authorize(self, p: ActionProposal, *, record: bool = True) -> AuthorizationDecision:
        st = self.ledger.state()
        ps = st.proposals.get(p.idempotency_key)
        dec = authorize(p, self.policy, committed=st.committed(), approved=bool(ps and ps.approvals), now=self.clock())
        if record and ps is not None:
            self.ledger.record_authorization(p.idempotency_key, dec)
            if dec.outcome == OUT_BUDGET:
                self.ledger.stop(p.scope, R_BUDGET, dec.reason)
        return dec

    def approve(self, proposal_id_or_key: str, by: str, note: str = "") -> bool:
        """A person approves one proposal (tied to its idempotency key).  Lifts only 'needs approval'; it can never make a
        forbidden proposal executable or create a budget."""
        st = self.ledger.state()
        key = next((k for k, ps in st.proposals.items()
                    if k == proposal_id_or_key or ps.proposal.get("proposal_id") == proposal_id_or_key), None)
        return bool(key) and self.ledger.approve(key, by, note)

    def request_cancel(self, proposal_id_or_key: str, by: str) -> bool:
        st = self.ledger.state()
        key = next((k for k, ps in st.proposals.items()
                    if k == proposal_id_or_key or ps.proposal.get("proposal_id") == proposal_id_or_key), None)
        return bool(key) and self.ledger.request_cancel(key, by)

    def resume(self, scope: str, by: str) -> bool:
        return self.ledger.resume(scope, by)

    # ------------------------------------------------------------------ execute (one proposal, bounded retries)
    def execute(self, p: ActionProposal, *, cancel: CancelToken | None = None) -> ExecutionOutcome:
        key = p.idempotency_key
        out = ExecutionOutcome(key=key, action_type=p.action_type)
        bad = validate_proposal(p)
        if bad:
            out.reason = "提案無效：" + "；".join(bad)
            return out
        self.ledger.propose(p)                                  # idempotent: records it if a caller skipped step()
        dec = self.authorize(p)
        out.decision = dec
        if not dec.executable:
            out.reason = dec.reason
            return out
        if self.executor is None:
            out.reason = "沒有提供執行器：只提出建議。"
            return out
        cp = p.checkpoint or {}
        if cp.get("required"):
            ok, why = self.checkpoint_validator(cp)
            if not ok:
                self.ledger.escalate(R_INVALID_CHECKPOINT, key=key, detail=why,
                                     options=["修復或重新核准檢查點", "改為從頭重做（新協定，需另行決定）", "接受目前的證據不足"])
                out.reason = f"檢查點無效，升級給使用者、不執行：{why}"
                out.stop = {"reason": R_INVALID_CHECKPOINT, "detail": why}
                return out
        while True:
            if cancel is not None and cancel.is_set():
                self.ledger.request_cancel(key, "controller:cancel_token")
            if self.ledger.cancel_requested(key):
                out.status, out.reason = "cancelled", "已取消，沒有啟動。"
                return out
            claim = self.ledger.claim(p, self.policy, worker=self.worker)
            if not claim.ok:
                out.reason = claim.detail or claim.reason
                if claim.reason == "attempts_exhausted":
                    self.ledger.escalate(R_ATTEMPTS, key=key, detail=claim.detail,
                                         options=["使用者檢查失敗原因後重新提出", "放棄此行動"])
                    out.stop = {"reason": R_ATTEMPTS, "detail": claim.detail}
                elif claim.reason == "not_authorized" and claim.decision is not None and claim.decision.outcome == OUT_BUDGET:
                    self.ledger.stop(p.scope, R_BUDGET, claim.decision.reason)
                    out.stop = {"reason": R_BUDGET, "detail": claim.decision.reason}
                if out.attempts:
                    out.status = "failed"
                return out
            out.attempts = claim.attempt
            req = ExecutionRequest(proposal=p.to_dict(), key=key, attempt=claim.attempt, max_attempts=p.max_attempts,
                                   checkpoint=dict(cp), worker=self.worker,
                                   cancelled=lambda: (cancel is not None and cancel.is_set()) or self.ledger.cancel_requested(key))
            t0 = time.monotonic()
            try:
                res = ExecutionResult.coerce(self.executor(req))
            except ActionCancelled:
                res = ExecutionResult(status="cancelled", error="執行器回報已取消")
            except TechnicalError as exc:
                res = ExecutionResult(status="failed", error=f"{type(exc).__name__}: {exc}"[:500], error_kind="technical")
            except KeyboardInterrupt:
                self.ledger.finish(p, claim.attempt, status="cancelled", error="interrupted", resources={"wall_s": round(time.monotonic() - t0, 3)})
                raise
            except Exception as exc:  # noqa: BLE001 - an unexpected exception is a failure, never retried
                res = ExecutionResult(status="failed", error=f"{type(exc).__name__}: {exc}"[:500], error_kind="unexpected")
            resources = dict(res.resources or {})
            resources.setdefault("wall_s", round(time.monotonic() - t0, 3))
            if res.status not in ("ok", "failed", "cancelled"):
                res = ExecutionResult(status="failed", error=f"執行器回傳未知狀態 {str(res.status)[:40]!r}", error_kind="unexpected",
                                      resources=resources, simulated_ps=res.simulated_ps)
            self.ledger.finish(p, claim.attempt, status=res.status, resources=resources, simulated_ps=res.simulated_ps,
                               error=res.error, error_kind=res.error_kind if res.status == "failed" else None)
            if res.status == "ok":
                out.status = "ok"
                self._reassess(p, res, out)
                return out
            if res.status == "cancelled":
                out.status, out.reason = "cancelled", res.error or "已取消"
                return out
            out.status, out.reason = "failed", res.error or "失敗"
            if res.error_kind == R_INVALID_MODEL:
                self.ledger.stop(p.scope, R_INVALID_MODEL, res.error or "執行器回報模型無效")
                out.stop = {"reason": R_INVALID_MODEL, "detail": res.error or ""}
                return out
            if res.error_kind != "technical":
                self.ledger.escalate(R_FAILED, key=key, detail=f"{res.error_kind}: {res.error}",
                                     options=["使用者檢查失敗原因", "放棄此行動"])
                out.stop = {"reason": R_FAILED, "detail": res.error or ""}
                return out
            # technical failure: loop → claim() re-checks cancel / attempt cap / budget; same request, same protocol

    def _reassess(self, p: ActionProposal, res: ExecutionResult, out: ExecutionOutcome) -> None:
        a = self.reassessor(p.to_dict(), res) if self.reassessor is not None else res.assessment
        probs = validate_assessment(a)
        if probs:
            self.ledger.post_assessment(p.idempotency_key, {"valid": False, "problems": probs}, improved=False)
            detail = "行動完成後無法取得可解讀的評估：" + "；".join(probs)
            self.ledger.stop(p.scope, R_UNKNOWN_ASSESSMENT, detail)
            out.stop = {"reason": R_UNKNOWN_ASSESSMENT, "detail": detail}
            return
        after = summarize(a)
        imp = improved(p.baseline or {}, after, p.action_type)
        out.improved = imp
        self.ledger.post_assessment(p.idempotency_key, {"valid": True, **after, "before_n_pass": (p.baseline or {}).get("n_pass")}, imp)
        if after["sampling_adequate"] is True:
            out.stop = {"reason": R_GOAL, "detail": "行動後評估認為取樣足夠。"}
            return
        streak = self.ledger.state().scope(p.scope)["streak"]
        if streak >= self._no_improvement_limit():
            detail = f"連續 {streak} 個已執行的行動後評估都沒有改善（上限 {self._no_improvement_limit()}）：不再花資源。"
            self.ledger.stop(p.scope, R_NO_IMPROVEMENT, detail)
            out.stop = {"reason": R_NO_IMPROVEMENT, "detail": detail}

    # ------------------------------------------------------------------ one cycle / a bounded loop
    def cycle(self, assessment_inputs, *, cancel: CancelToken | None = None) -> CycleReport:
        """step() then, if (and only if) a policy authorizes it, execute at most ONE action: after an action the evidence has
        changed, so the remaining proposals are stale and must be re-derived from a fresh assessment."""
        res = self.step(assessment_inputs)
        rep = CycleReport(step=res, stop=res.stop)
        if res.stop is None:
            gone = next((d for d in res.decisions.values() if d.outcome == OUT_BUDGET), None)
            if gone is not None:
                rep.stop = {"reason": R_BUDGET, "detail": gone.reason}
        if rep.stop or self.recommendation_only:
            return rep
        for p in res.proposals:
            dec = res.decisions.get(p.idempotency_key)
            if dec is None or not dec.executable:
                continue
            out = self.execute(p, cancel=cancel)
            rep.executed.append(out)
            rep.stop = out.stop
            break
        return rep

    def run_until_stop(self, get_inputs: Callable[[], Any], *, max_cycles: int = 3, cancel: CancelToken | None = None) -> list[CycleReport]:
        """Repeat cycle() with a FRESH assessment each time, until something stops, nothing executes, or `max_cycles`."""
        out = []
        for _ in range(max(1, int(max_cycles))):
            rep = self.cycle(get_inputs(), cancel=cancel)
            out.append(rep)
            if rep.stop or not any(e.status == "ok" for e in rep.executed):
                break
        return out

    # ------------------------------------------------------------------ recovery
    def recover_stale(self, is_alive: Callable[[dict], bool | None]) -> list[str]:
        """Close attempts whose worker is provably dead (`is_alive(attempt) is False`).  `None`/True → leave it: an
        unknown worker is assumed to be running and is never relaunched."""
        closed = []
        for key, ps in self.ledger.state().proposals.items():
            a = ps.running
            if a is not None and is_alive(dict(a)) is False and self.ledger.abandon(key, "controller:recover_stale", "worker 已不存在"):
                closed.append(key)
        return closed

    # ------------------------------------------------------------------ dry run
    def dry_run(self, assessment_inputs, policy: Policy | None = USE_CONTROLLER_POLICY) -> dict:
        """What *would* happen, written nowhere.  `policy`: omit to use this controller's; pass None for 'no policy'."""
        inputs = AssessmentInputs.from_any(assessment_inputs)
        pol = self.policy if policy is USE_CONTROLLER_POLICY else policy
        props, esc, stop, summ = self._plan(inputs)
        st = self.ledger.state()
        rows, lines = [], []
        for p in props:
            ps = st.proposals.get(p.idempotency_key)
            dec = authorize(p, pol, committed=st.committed(), approved=bool(ps and ps.approvals), now=self.clock())
            in_ledger = ps.status if ps is not None else None
            would = dec.executable and in_ledger not in (ST_SUCCEEDED, ST_RUNNING, ST_CANCELLED, ST_EXHAUSTED) and self.executor is not None \
                and stop is None
            rows.append({"proposal_id": p.proposal_id, "action_type": p.action_type, "target": p.target, "trigger": p.trigger,
                         "estimate": p.estimate, "expected_benefit": p.expected_benefit, "decision": dec.to_dict(),
                         "ledger_status": in_ledger, "would_execute": bool(would)})
            lines.append(f"{ACTION_LABEL_ZH[p.action_type]}：{dec.outcome} — {dec.reason}"
                         + (f"（帳本狀態：{in_ledger}）" if in_ledger else ""))
        mode = "policy" if (pol is not None and pol.effective()[0]) else "recommendation_only"
        if mode == "recommendation_only":
            lines.insert(0, "目前是只提建議模式：沒有使用者核准的政策與預算，不會執行任何行動。")
        if stop:
            lines.append(f"停止：{stop['reason']} — {stop['detail']}")
        return {"mode": mode, "scope": inputs.scope, "stop": stop, "proposals": rows, "escalations": esc,
                "remaining": remaining_budget(pol, st.committed()), "summary": summ, "text": lines}
