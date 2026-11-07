"""D-137 (R8): vocabulary of the bounded-autonomy ledger — action proposals, policy, authorization.

Pure Python, no I/O.  Nothing here launches anything.

* An `ActionProposal` is *data*: what could be done, why (trigger + evidence IDs), what it needs, which claims it
  touches, what it is expected to buy (marked heuristic unless calibrated), what it would cost, and how it recovers.
  Strings inside it (molecule names, document metadata, notes) are only ever recorded, never evaluated or executed.
* A `Policy` is the user's written authorization: which action classes, which budget.  **No policy → recommendation-only.**
* `authorize()` is a deterministic function of (proposal, policy, what is already committed).  The proposal's own
  claim about its authorization class is never trusted: the class is recomputed from `action_type` and `protocol_changes`.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = "md20.autonomy/1"

# ------------------------------------------------------------------------------------------------ action vocabulary
ACTION_REANALYSIS = "reanalysis"
ACTION_EXTEND = "extend_approved_run"
ACTION_REPLICA = "add_independent_replica"
ACTION_REFINE = "refine_approved_umbrella_windows"
ACTION_TYPES = (ACTION_REANALYSIS, ACTION_EXTEND, ACTION_REPLICA, ACTION_REFINE)
ACTION_LABEL_ZH = {
    ACTION_REANALYSIS: "重新分析（不產生新取樣）",
    ACTION_EXTEND: "延長已核准的執行",
    ACTION_REPLICA: "新增獨立重複",
    ACTION_REFINE: "補強已核准的傘狀採樣窗口",
}

CLASS_ROUTINE = "routine_within_policy"
CLASS_NEEDS_APPROVAL = "needs_approval"
CLASS_FORBIDDEN = "forbidden"
AUTH_CLASSES = (CLASS_ROUTINE, CLASS_NEEDS_APPROVAL, CLASS_FORBIDDEN)

# Anything on this list changes the scientific protocol.  The controller never executes a proposal that touches one,
# with or without a budget; it needs a separate, explicit decision outside this module (a new protocol, not a retry).
FORBIDDEN_CHANGES = {
    "force_field": "力場",
    "chemical_identity": "化學身分（配體／受體是哪個分子）",
    "protonation": "質子化假設",
    "restraints": "約束",
    "reference_state": "參考態（標準態／結合態定義）",
    "scientific_model": "科學模型",
    "paid_backend": "付費後端",
    "external_data_exposure": "對外傳送資料",
}

# ------------------------------------------------------------------------------------------------ resources
DIMS = ("sim_ns", "gpu_hours", "core_hours", "storage_gb")
DIM_LABEL_ZH = {"sim_ns": "模擬時間（ns）", "gpu_hours": "GPU 小時", "core_hours": "CPU 核心小時", "storage_gb": "儲存（GB）"}
_EPS = 1e-9

# ------------------------------------------------------------------------------------------------ outcomes
OUT_AUTHORIZED = "authorized"
OUT_NEEDS_APPROVAL = "needs_approval"
OUT_DENIED = "denied"
OUT_RECOMMEND = "recommendation_only"
OUT_BUDGET = "budget_exhausted"
OUT_BLOCKED = "blocked"
OUTCOMES = (OUT_AUTHORIZED, OUT_NEEDS_APPROVAL, OUT_DENIED, OUT_RECOMMEND, OUT_BUDGET, OUT_BLOCKED)

BENEFIT_HEURISTIC = "heuristic"
BENEFIT_CALIBRATED = "calibrated"


# ------------------------------------------------------------------------------------------------ canonical hashing
def _jsonable(o: Any):
    if isinstance(o, Path):
        return str(o)
    if isinstance(o, (set, frozenset, tuple)):
        return sorted(o, key=str) if not isinstance(o, tuple) else list(o)
    if hasattr(o, "tolist"):
        return o.tolist()
    raise TypeError(f"not JSON-serialisable: {type(o).__name__}")


def canonical(obj: Any) -> str:
    """Deterministic JSON (sorted keys, no NaN) — the only thing an idempotency key is computed from."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False, default=_jsonable)


def idempotency_key(action_type: str, scope: str, target: dict, inputs: dict) -> str:
    """sha256 over (action, scope, target, inputs).  The same action on the same target with the same evidence state
    gets the same key, whoever proposes it and however often (duplicate proposal, second worker, GUI reconnect)."""
    return hashlib.sha256(canonical({"v": 1, "action": action_type, "scope": scope, "target": target,
                                     "inputs": inputs}).encode("utf-8")).hexdigest()


def _num(x):
    """float, or None for missing / non-finite / negative / non-numeric (a bad estimate is 'unknown', never 0)."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v >= 0 else None


# ------------------------------------------------------------------------------------------------ proposal
@dataclass
class ActionProposal:
    action_type: str
    scope: str                                  # the unit the stop rules apply to (workflow / binding calculation)
    target: dict                                # what the action acts on (run id, window centres, replica index)
    trigger: list = field(default_factory=list)            # diagnostic ids / rule names that caused the proposal
    evidence_ids: list = field(default_factory=list)       # IDs of the stored evidence (assessment digest, refine_log round…)
    prerequisites: list = field(default_factory=list)      # [{"id", "description", "satisfied": True|False|None}]
    affected_claims: list = field(default_factory=list)    # claims whose eligibility this action could change
    expected_benefit: dict = field(default_factory=dict)   # {"statement", "kind": heuristic|calibrated, "calibration_ref"}
    estimate: dict = field(default_factory=dict)           # DIMS → float|None (None = unknown), plus "basis"
    protocol_changes: list = field(default_factory=list)   # must be empty; any entry → forbidden
    inputs: dict = field(default_factory=dict)             # the evidence state the proposal was made from (hashed)
    max_attempts: int = 2                                  # total launches including the first; technical retries only
    checkpoint: dict = field(default_factory=dict)         # {"required", "path", "fingerprint"}
    recovery_plan: str = ""
    comparison_consequences: list = field(default_factory=list)
    baseline: dict = field(default_factory=dict)           # assessment summary at proposal time (for the post-action comparison)
    created_at: str = ""
    # computed
    authorization_class: str = ""
    idempotency_key: str = ""
    proposal_id: str = ""

    def __post_init__(self):
        self.target = copy.deepcopy(dict(self.target or {}))
        self.inputs = copy.deepcopy(dict(self.inputs or {}))
        b = dict(self.expected_benefit or {})
        # "calibrated" needs a reference to the calibration; without one it is a heuristic
        if b.get("kind") == BENEFIT_CALIBRATED and not b.get("calibration_ref"):
            b["kind"] = BENEFIT_HEURISTIC
        b.setdefault("kind", BENEFIT_HEURISTIC)
        b.setdefault("calibration_ref", None)
        b.setdefault("statement", "")
        self.expected_benefit = b
        est = {d: _num((self.estimate or {}).get(d)) for d in DIMS}
        est["basis"] = (self.estimate or {}).get("basis", "unspecified")
        self.estimate = est
        if not self.authorization_class:
            self.authorization_class = classify(self)
        if not self.idempotency_key:
            self.idempotency_key = idempotency_key(self.action_type, self.scope, self.target, self.inputs)
        if not self.proposal_id:
            self.proposal_id = "act-" + self.idempotency_key[:16]

    def to_dict(self) -> dict:
        return copy.deepcopy({k: getattr(self, k) for k in self.__dataclass_fields__})

    @classmethod
    def from_dict(cls, d: dict) -> "ActionProposal":
        names = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in (d or {}).items() if k in names})


def classify(p: ActionProposal) -> str:
    """Intrinsic class from the proposal's content only: any protocol change → forbidden; an unsupported action type is
    not routine either.  (Whether a *routine* action may run is up to the policy.)"""
    if p.protocol_changes:
        return CLASS_FORBIDDEN
    if p.action_type not in ACTION_TYPES:
        return CLASS_FORBIDDEN
    return CLASS_ROUTINE


def validate_proposal(p: ActionProposal) -> list[str]:
    """Problems that make a proposal unusable (empty = fine).  Strings are checked for type only, never interpreted."""
    out = []
    if p.action_type not in ACTION_TYPES:
        out.append(f"不支援的行動類型：{str(p.action_type)[:60]!r}")
    if not isinstance(p.scope, str) or not p.scope:
        out.append("缺少 scope")
    if not isinstance(p.target, dict):
        out.append("target 不是物件")
    if not isinstance(p.protocol_changes, list):
        out.append("protocol_changes 不是清單")
    try:
        want = idempotency_key(p.action_type, p.scope, p.target, p.inputs)
    except (TypeError, ValueError) as exc:
        out.append(f"無法計算 idempotency key：{exc}")
    else:
        if p.idempotency_key != want:
            out.append("idempotency key 與內容不符（內容被改過？）")
    if p.authorization_class != classify(p):
        out.append(f"authorization_class 與內容不符（內容判定為 {classify(p)}）")
    if not isinstance(p.max_attempts, int) or isinstance(p.max_attempts, bool) or p.max_attempts < 1:
        out.append("max_attempts 必須是 ≥ 1 的整數")
    return out


# ------------------------------------------------------------------------------------------------ policy
class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class Policy:
    """The user's written authorization.  Every number is a ceiling on *actual* use (retries included).  A dimension
    left None is not authorized at all: an action that needs it is `needs_approval`."""
    policy_id: str
    approved_by: str
    approved_at: str
    allowed_actions: tuple = ()
    max_sim_ns: float | None = None
    max_gpu_hours: float | None = None
    max_core_hours: float | None = None
    max_storage_gb: float | None = None
    max_attempts: int = 2                 # per action, including the first launch
    no_improvement_stop: int = 2          # consecutive executed actions without improvement before stopping

    def limits(self) -> dict:
        return {"sim_ns": self.max_sim_ns, "gpu_hours": self.max_gpu_hours, "core_hours": self.max_core_hours,
                "storage_gb": self.max_storage_gb}

    def effective(self) -> tuple[bool, str]:
        """(usable, why not).  A policy without an approver, an allowed action or any budget authorizes nothing."""
        if not self.approved_by or not self.approved_at:
            return False, "政策沒有核准者或核准時間"
        if not [a for a in self.allowed_actions if a in ACTION_TYPES]:
            return False, "政策沒有允許任何支援的行動類型"
        if not any(v is not None and v > 0 for v in self.limits().values()):
            return False, "政策沒有任何正的預算額度"
        return True, ""

    def to_dict(self) -> dict:
        return {"policy_id": self.policy_id, "approved_by": self.approved_by, "approved_at": self.approved_at,
                "allowed_actions": list(self.allowed_actions), "max_sim_ns": self.max_sim_ns,
                "max_gpu_hours": self.max_gpu_hours, "max_core_hours": self.max_core_hours,
                "max_storage_gb": self.max_storage_gb, "max_attempts": self.max_attempts,
                "no_improvement_stop": self.no_improvement_stop}

    @classmethod
    def from_dict(cls, d: dict) -> "Policy":
        if not isinstance(d, dict):
            raise PolicyError("政策必須是物件")
        kw: dict = {}
        for k in ("policy_id", "approved_by", "approved_at"):
            v = d.get(k)
            if not isinstance(v, str) or not v.strip():
                raise PolicyError(f"政策缺少 {k}")
            kw[k] = v.strip()
        acts = d.get("allowed_actions", [])
        if not isinstance(acts, (list, tuple)) or not all(isinstance(a, str) for a in acts):
            raise PolicyError("allowed_actions 必須是字串清單")
        unknown = [a for a in acts if a not in ACTION_TYPES]
        if unknown:
            raise PolicyError(f"未知的行動類型：{unknown[:3]}")
        kw["allowed_actions"] = tuple(acts)
        for k in ("max_sim_ns", "max_gpu_hours", "max_core_hours", "max_storage_gb"):
            v = d.get(k)
            if v is None:
                kw[k] = None
                continue
            n = _num(v)
            if n is None:
                raise PolicyError(f"{k} 必須是有限的非負數")
            kw[k] = n
        for k, default in (("max_attempts", 2), ("no_improvement_stop", 2)):
            v = d.get(k, default)
            if not isinstance(v, int) or isinstance(v, bool) or v < 1:
                raise PolicyError(f"{k} 必須是 ≥ 1 的整數")
            kw[k] = v
        return cls(**kw)


# ------------------------------------------------------------------------------------------------ decision
@dataclass
class AuthorizationDecision:
    outcome: str
    authorization_class: str
    by: str
    reason: str
    at: str = ""
    policy_id: str | None = None
    details: list = field(default_factory=list)
    remaining: dict = field(default_factory=dict)

    @property
    def executable(self) -> bool:
        return self.outcome == OUT_AUTHORIZED

    def to_dict(self) -> dict:
        return {"outcome": self.outcome, "authorization_class": self.authorization_class, "by": self.by,
                "reason": self.reason, "at": self.at, "policy_id": self.policy_id, "details": list(self.details),
                "remaining": dict(self.remaining)}


def remaining_budget(policy: Policy | None, committed: dict | None) -> dict:
    """limit − committed (spent + in flight) per dimension; None where the policy sets no limit."""
    committed = committed or {}
    out = {}
    for d, lim in (policy.limits() if policy is not None else {}).items():
        out[d] = None if lim is None else round(lim - float(committed.get(d) or 0.0), 6)
    return out


def authorize(p: ActionProposal, policy: Policy | None, *, committed: dict | None = None, approved: bool = False,
              now: str = "") -> AuthorizationDecision:
    """Deterministic authorization.  Order: invalid → forbidden → no usable policy (recommendation only) → unmet
    prerequisite (blocked) → budget exhausted → needs approval → authorized.

    `approved`: a human approved *this* idempotency key.  It lifts only the 'needs approval' reasons (action class not in
    the policy, unknown estimate, resource the policy does not cover).  It never lifts forbidden, blocked, an invalid
    proposal, a missing policy or an exhausted budget."""
    cls = classify(p)
    problems = validate_proposal(p)

    def dec(outcome, reason, by="controller", details=None, cls_=None):
        return AuthorizationDecision(outcome=outcome, authorization_class=cls_ or cls, by=by, reason=reason, at=now,
                                     policy_id=policy.policy_id if policy is not None else None,
                                     details=list(details or []), remaining=remaining_budget(policy, committed))

    if problems:
        return dec(OUT_DENIED, "提案無效：" + "；".join(problems), cls_=CLASS_FORBIDDEN, details=problems)
    if cls == CLASS_FORBIDDEN:
        names = [FORBIDDEN_CHANGES.get(c, str(c)) for c in p.protocol_changes]
        return dec(OUT_DENIED, "提案會改變科學協定（" + "、".join(names) + "）：自主控制器永遠不執行，需要另外的明確決定（新的協定，不是重試）。",
                   details=[str(c) for c in p.protocol_changes])
    usable, why = policy.effective() if policy is not None else (False, "沒有使用者核准的行動政策與計算預算")
    if not usable:
        return dec(OUT_RECOMMEND, f"只提出建議、不執行：{why}。", details=[why])
    by_policy = f"policy:{policy.policy_id}（{policy.approved_by} 於 {policy.approved_at} 核准）"
    unmet = [pr for pr in p.prerequisites if pr.get("satisfied") is not True]
    if unmet:
        det = [f"{pr.get('id')}: {pr.get('description', '')}（{'未滿足' if pr.get('satisfied') is False else '未知'}）" for pr in unmet]
        return dec(OUT_BLOCKED, "先決條件未滿足或未知：" + "；".join(det), by=by_policy, details=det)
    committed = committed or {}
    exhausted, unknown, uncovered = [], [], []
    for d, lim in policy.limits().items():
        est = p.estimate.get(d)
        if lim is None:
            if est is not None and est > 0:
                uncovered.append(d)
            continue
        if est is None:
            unknown.append(d)
        elif float(committed.get(d) or 0.0) + est > lim + _EPS:
            exhausted.append(f"{DIM_LABEL_ZH[d]}：已用/已保留 {float(committed.get(d) or 0.0):.4g} + 此行動 {est:.4g} > 上限 {lim:.4g}")
    if exhausted:
        return dec(OUT_BUDGET, "預算不足：" + "；".join(exhausted), by=by_policy, details=exhausted)
    reasons = []
    if p.action_type not in policy.allowed_actions:
        reasons.append(f"政策未允許「{ACTION_LABEL_ZH.get(p.action_type, p.action_type)}」")
    if unknown:
        reasons.append("無法估計：" + "、".join(DIM_LABEL_ZH[d] for d in unknown))
    if uncovered:
        reasons.append("政策沒有核准的資源：" + "、".join(DIM_LABEL_ZH[d] for d in uncovered))
    if reasons and not approved:
        return dec(OUT_NEEDS_APPROVAL, "需要使用者核准：" + "；".join(reasons), by=by_policy, details=reasons,
                   cls_=CLASS_NEEDS_APPROVAL)
    return dec(OUT_AUTHORIZED, "在使用者核准的政策與預算內" + ("（已由使用者個案核准）" if reasons else "") + "，可例行執行。",
               by=by_policy, details=reasons if approved else [], cls_=CLASS_ROUTINE if not reasons else CLASS_NEEDS_APPROVAL)


# ------------------------------------------------------------------------------------------------ policy files
POLICY_FILE = "autonomy_policy.json"


def load_policy(workflow_dir: Path | str) -> tuple[Policy | None, str]:
    """(policy, note).  A missing file is the default — recommendation-only; an invalid file is also recommendation-only
    (with the reason), never a silently permissive default."""
    from ..util import load_json
    path = Path(workflow_dir) / "autonomy" / POLICY_FILE
    if not path.is_file():
        return None, "沒有行動政策檔：只提出建議"
    try:
        return Policy.from_dict(load_json(path, critical=True)), ""
    except (PolicyError, RuntimeError) as exc:
        return None, f"行動政策檔無效，視為沒有政策：{exc}"


def save_policy(workflow_dir: Path | str, policy: Policy) -> Path:
    """For the *user's* authorization step (a GUI form / CLI the user runs).  Nothing in this package calls it."""
    from ..util import atomic_write_json
    return atomic_write_json(policy.to_dict(), Path(workflow_dir) / "autonomy" / POLICY_FILE)
