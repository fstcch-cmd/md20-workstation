"""D-137 (R8): optional bridge from the *existing* adaptive refinement to the action ledger.

`sampling/adaptive.plan_refinement(..., recorder=make_refine_recorder(...))` records what the planner decided in
`<workflow>/autonomy/ledger.jsonl` as **observed** actions.  Observed means: existing workflow automation (bounded by the
workflow's own `max_refine_rounds` / `max_windows`), not governed by an autonomy policy and not charged to any policy
budget.  The point is a single honest record of what automatic refinement did and what it cost, next to what the
controller proposed.

Behaviour is unchanged: the recorder only appends to a side file, never returns anything the planner uses, and any failure
inside it is swallowed by the hook (`adaptive._call_recorder`).  When no recorder is passed nothing here is imported.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .ledger import Ledger
from .model import ACTION_EXTEND, ACTION_REFINE, ActionProposal, BENEFIT_HEURISTIC

SOURCE = "legacy_adaptive_refinement"


def _plan_dict(plan) -> dict:
    return plan.to_dict() if hasattr(plan, "to_dict") else dict(plan or {})


def proposals_from_refine_plan(plan, *, scope: str, costs: dict | None = None, round_no: int | None = None,
                               evidence_prefix: str = "refine_log.json") -> list[ActionProposal]:
    """The planner's insert / extend lists as ActionProposals (inserts and extensions are separate actions).  Estimates use
    only recorded settings (`window_equil_ps`, `window_prod_ps`); missing → unknown (None)."""
    d = _plan_dict(plan)
    costs = costs or {}
    equil, prod = costs.get("window_equil_ps"), costs.get("window_prod_ps")
    out = []

    def est(ps):
        e = {"sim_ns": None if ps is None else round(ps / 1000.0, 6), "gpu_hours": None, "core_hours": None, "storage_gb": None,
             "basis": "heuristic: derived from recorded settings, not measured"}
        return e

    ev = [f"{evidence_prefix}#round{round_no}"] if round_no is not None else [evidence_prefix]
    ins = [i for i in d.get("insert") or [] if isinstance(i, dict) and "center" in i]
    ext = [e for e in d.get("extend") or [] if isinstance(e, dict) and "center" in e]
    if ins:
        centres = sorted(round(float(i["center"]), 4) for i in ins)
        ks = {f"{round(float(i['center']), 4):.4f}": float(i.get("k", 0)) for i in ins}
        per = (float(equil) + float(prod)) if isinstance(equil, (int, float)) and isinstance(prod, (int, float)) else None
        out.append(ActionProposal(
            action_type=ACTION_REFINE, scope=scope, target={"scope": scope, "insert_centres": centres, "k": ks},
            trigger=["plan_refinement.insert"], evidence_ids=ev, affected_claims=["delta_pmf_path_specific", "dG_standard"],
            expected_benefit={"statement": "規劃器補窗（既有自動流程）", "kind": BENEFIT_HEURISTIC},
            estimate=est(None if per is None else per * len(centres)),
            inputs={"round": round_no, "insert": centres, "k": ks}, max_attempts=1))
    if ext:
        centres = sorted(round(float(e["center"]), 4) for e in ext)
        out.append(ActionProposal(
            action_type=ACTION_EXTEND, scope=scope, target={"scope": scope, "window_centres": centres},
            trigger=["plan_refinement.extend"], evidence_ids=ev, affected_claims=["delta_pmf_path_specific", "dG_standard"],
            expected_benefit={"statement": "規劃器延長取樣不足的窗口（既有自動流程）", "kind": BENEFIT_HEURISTIC},
            estimate=est(None if not isinstance(prod, (int, float)) else float(prod) * len(centres)),
            inputs={"round": round_no, "extend": centres}, max_attempts=1))
    return out


def record_refine_plan(workflow_dir: Path | str, plan, *, scope: str, costs: dict | None = None,
                       round_no: int | None = None) -> list[str]:
    """Append the plan's actions to the workflow's ledger as observed actions.  Idempotent: re-planning the same round on a
    resume writes nothing new.  Returns the idempotency keys (new or existing)."""
    ledger = Ledger(Path(workflow_dir) / "autonomy")
    keys = []
    for p in proposals_from_refine_plan(plan, scope=scope, costs=costs, round_no=round_no):
        ledger.observe(p, source=SOURCE, simulated_ps_estimate=(p.estimate.get("sim_ns") or 0.0) * 1000.0 or None,
                       note="計畫階段記錄；實際花費請用 record_refine_result 補記")
        keys.append(p.idempotency_key)
    return keys


def record_refine_result(workflow_dir: Path | str, keys: list[str], *, simulated_ps: float | None, wall_s: float | None = None,
                         ok: bool = True) -> None:
    """Optional: the existing code reports what an executed round actually produced (simulated ps and wall time, kept apart)."""
    ledger = Ledger(Path(workflow_dir) / "autonomy")
    for i, k in enumerate(keys):
        ledger.observe_end(k, simulated_ps=simulated_ps if i == 0 else None, wall_s=wall_s if i == 0 else None, ok=ok)


def make_refine_recorder(workflow_dir: Path | str, *, scope: str, costs: dict | None = None,
                         round_no: int | None = None) -> Callable[[object], None]:
    """The callable to pass as `plan_refinement(..., recorder=...)`."""
    def _rec(plan) -> None:
        record_refine_plan(workflow_dir, plan, scope=scope, costs=costs, round_no=round_no)
    return _rec
