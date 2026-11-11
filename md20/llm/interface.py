# -*- coding: utf-8 -*-
"""L0 interface definition for the LLM orchestration track (D-178).

Pure contract + validation. No server, no LLM calls, no side effects, no apply path.
Grounded on existing sources of truth: parameter ranges come from ``md20.advisor.PARAMS``
and the capability list from ``docs/capabilities.json`` — this module invents no numbers.

Two policy decisions from the spec review (D-177) are encoded here:
- propose-only: every write-ish action is a *proposal*; MD20 applies it only after the
  user confirms. This module has no code that applies anything.
- whitelist safe keys + ranges: ``propose_config_change`` may only touch resource/
  sampling/output knobs within their legal range; science-sensitive keys (force field,
  thermodynamic state, restraints, integrator, ionic environment, solvent model, SMD/
  umbrella force constants) are not proposable here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from md20 import advisor
from md20 import workflow as _wf
from md20.util.paths import safe_name

_ROOT = Path(__file__).resolve().parents[2]
_CAPABILITIES = _ROOT / "docs" / "capabilities.json"

# --- Action contract (matches docs/llm/MD20_LLM_GUIDE.md §3) -----------------------------
# mode "read": read-only. mode "propose": returns a proposal only; MD20 applies after the
# user confirms (D-177). There is deliberately no "apply"/"execute"/"write_config" action.
ACTIONS: tuple[dict[str, Any], ...] = (
    {"name": "read_capabilities", "mode": "read",
     "summary": "Read which features exist and how well verified (capabilities.json projection).",
     "limits": "read-only; implementation paths hidden"},
    {"name": "plan_workflow", "mode": "propose",
     "summary": "Submit a draft config.json for a run.",
     "limits": "schema-validated; runs only after the user confirms"},
    {"name": "read_report", "mode": "read",
     "summary": "Read a workflow's status, step statuses and the report text (paged).",
     "limits": "read-only; names and statuses only, no gate messages or options (those are read_problem)"},
    {"name": "read_problem", "mode": "read",
     "summary": "Read the currently blocking gate: stage, reason, evidence numbers, legal options.",
     "limits": "read-only"},
    {"name": "select_gate_option", "mode": "propose",
     "summary": "Choose one of the options the gate offered.",
     "limits": "must be one of the offered options; proposal only, user confirms"},
    {"name": "propose_config_change", "mode": "propose",
     "summary": "Suggest changing one setting.",
     "limits": "whitelisted safe keys only, within range; science-sensitive keys not proposable; proposal only, user confirms"},
    {"name": "read_file", "mode": "read",
     "summary": "Read part of a file in the user's project folder.",
     "limits": "project folder only; no engine/source/system paths; large trajectories not served raw"},
    {"name": "write_report_narrative", "mode": "propose",
     "summary": "Write the report's narrative sections (summary, domain context, next steps).",
     "limits": "narrative slots only; cannot change numbers or figures"},
)


# Actions the L1 (MCP) adapter exposes. read_problem / select_gate_option / propose_config_change / read_file /
# write_report_narrative are L2+ and are deliberately not exposed yet.
L1_EXPOSED: tuple[str, ...] = ("read_capabilities", "plan_workflow", "read_report")


def action_names() -> list[str]:
    return [a["name"] for a in ACTIONS]


# --- Config-key exposure whitelist (D-177 decision 2) ------------------------------------
# SAFE: resource / sampling / output knobs. Changing one affects cost, sampling budget, or
# output granularity, not the physical model. Each must exist in advisor.PARAMS, which
# supplies the type and legal range used by validate_proposed_change.
SAFE_KEYS: frozenset[str] = frozenset({
    "exhaustiveness", "n_poses",          # docking search effort / output count
    "padding_nm",                         # water-box margin (canonical safe "enlarge box" retry)
    "minimize_iterations", "minimize_tolerance",  # minimisation numerics
    "nvt_ps", "npt_ps",                   # equilibration durations
    "production_ns", "replicas",          # production length / independent repeats
    "trajectory_interval_ps",             # output save interval
    "window_equil_ps", "window_prod_ps",  # umbrella sampling budget per window
    "target_overlap",                     # umbrella coverage target (drives window count)
})

# SCIENCE-SENSITIVE: never proposable here. Kept explicit so a future PARAMS addition is a
# deliberate classification, not a silent leak into the safe set (guarded by a test).
SCIENCE_SENSITIVE_KEYS: frozenset[str] = frozenset({
    "solvent", "box_shape", "box_for_smd",                 # solvation model / geometry
    "ion_positive", "ion_negative", "ion_concentration_molar", "neutralize",  # ionic environment
    "restraints",                                          # restraint release strategy
    "heat_start_k", "temperature_k", "pressure_bar", "friction_per_ps",       # thermodynamic state
    "timestep_fs",                                         # integrator stability
    "tier",                                                # preset that also changes timestep
    "docking_mode", "binding",                             # workflow-mode toggles (go via plan_workflow)
    "pull_distance_nm", "pull_velocity_nm_per_ps", "k_pull", "k_umbrella",     # SMD/umbrella force params
})


def _param_spec(key: str) -> dict[str, Any] | None:
    """Type/range/choices of any advisor.PARAMS key (the single source of truth), else None."""
    p = advisor.PARAMS.get(key)
    if p is None:
        return None
    spec: dict[str, Any] = {"type": p.get("type"), "unit": p.get("unit", "")}
    for f in ("min", "max", "step"):
        if f in p:
            spec[f] = p[f]
    if "choices" in p:
        spec["choices"] = sorted(p["choices"])
    return spec


def safe_key_spec(key: str) -> dict[str, Any] | None:
    """Type/range/choices for a whitelisted safe key (from advisor.PARAMS), else None."""
    if key not in SAFE_KEYS:
        return None
    return _param_spec(key)


def _value_problem(spec: dict[str, Any], value: Any) -> str | None:
    """Shared type/range/choices check. Returns the reason the value is not acceptable, or None when it is."""
    t = spec.get("type")
    if t in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"expected {t}"
        if value != value or value in (float("inf"), float("-inf")):
            return "expected a finite number"
        if t == "int" and int(value) != value:
            return "expected an integer"
        lo, hi = spec.get("min"), spec.get("max")
        if lo is not None and value < lo:
            return f"below minimum {lo}"
        if hi is not None and value > hi:
            return f"above maximum {hi}"
    elif t == "choice":
        if value not in spec.get("choices", []):
            return f"not one of {spec.get('choices')}"
    elif t == "bool":
        if not isinstance(value, bool):
            return "expected bool"
    return None


def validate_proposed_change(key: str, value: Any) -> dict[str, Any]:
    """Validate a proposed single-setting change. Pure: returns a verdict, applies nothing.

    status is ALLOWED only when the key is whitelisted and the value is in type/range.
    REJECTED otherwise, with a reason. This never writes config and never triggers a run;
    an ALLOWED verdict still only means "a human may confirm this", per D-177.
    """
    if key in SCIENCE_SENSITIVE_KEYS:
        return {"key": key, "value": value, "status": "REJECTED",
                "reason": "science-sensitive key: not proposable by an LLM; needs a human decision"}
    if key not in SAFE_KEYS:
        return {"key": key, "value": value, "status": "REJECTED",
                "reason": "key is not on the safe whitelist"}
    spec = safe_key_spec(key)
    if spec is None:  # whitelisted but missing from PARAMS — treat as not proposable
        return {"key": key, "value": value, "status": "REJECTED",
                "reason": "no range definition available for this key"}
    problem = _value_problem(spec, value)
    if problem:
        return {"key": key, "value": value, "status": "REJECTED", "reason": problem}
    return {"key": key, "value": value, "status": "ALLOWED",
            "reason": "within range; a human must confirm before MD20 applies it"}


# --- Workflow draft validation (plan_workflow) -------------------------------------------
# Top-level config keys that md20 actually reads, derived from the code (not guessed):
#  - md20/workflow.py: Workflow.__init__/steps read self.cfg.get/[...] of name, receptor, ph, keep_hetero, box,
#    ligands, docking, md, binding, screen, goal (advisor goal, ~line 1543), confirm_before_md (~line 2272);
#    required_features() reads md, binding, screen.
#  - md20/advisor.py: features_from_config/values_from_config read ligands, keep_hetero, docking, binding,
#    metal_policy, box, md, receptor.
#  - md20/engine/replica_plan.py: reads md, ligands.
#  - md20/workflow.py DECISION_KEYS: the gate-decision top-level keys pose_choices, human_choices,
#    structure_override, metal_policy, metal_params, metal_water_state, metal_carboxylate, peptide_policy,
#    md_confirmed, ligand_metal, multi_ligand. Allowed to be present but must be empty (see rule 3).
# Anything else is unknown to MD20 and is rejected rather than guessed at.
KNOWN_DRAFT_KEYS: frozenset[str] = frozenset({
    "name", "receptor", "ph", "keep_hetero", "box", "ligands", "docking", "md", "binding", "screen",
    "goal", "confirm_before_md",
}) | frozenset(path[0] for path in _wf.DECISION_KEYS)

# DECISION_KEYS paths that are ordinary planning parameters, not gate decisions (D-184). ``md.replicas`` is carried
# across re-runs like a decision, but the replica plan never stops a run (engine/replica_plan.py, D-131) and the key is
# on SAFE_KEYS, so a draft may set it; it is still range-checked through advisor.PARAMS. Every other DECISION_KEYS
# path (including ``screen.next_mode``) stays a person's choice at a gate.
PLANNABLE_DECISION_PATHS: frozenset[tuple[str, ...]] = frozenset({("md", "replicas")})

_NESTED_DICT_KEYS = ("receptor", "box", "docking", "md", "binding", "screen")


def _is_empty(v: Any) -> bool:
    """None, False, or an empty string/list/dict; a number (even 0) counts as a set value."""
    return v is None or v is False or (isinstance(v, (str, list, dict)) and len(v) == 0)


def validate_workflow_draft(draft: Any) -> dict[str, Any]:
    """Validate a draft config.json for plan_workflow. Pure: writes nothing, applies nothing, runs nothing.

    Returns {"status": "ALLOWED"|"REJECTED", "errors", "warnings", "human_review", "required_features"}.
    ALLOWED only means "a person may review this and run it themselves"; the licence check at
    `pipeline run` remains the real gate. Rules (block rather than guess):
    1. dict with a safe non-empty ``name`` and a dict ``receptor``;
    2. top-level keys must be in KNOWN_DRAFT_KEYS;
    3. no human-decision key (workflow.DECISION_KEYS, per-ligand LIGAND_DECISION_KEYS) may carry a value:
       only a person sets those at a gate (principle 2);
    4. every parameter the config sets must be in range per advisor.PARAMS; science-sensitive ones are listed
       in ``human_review`` instead of being waved through;
    5. advisor.check() errors reject, warnings are passed on; an evaluation failure rejects.
    """
    wf = _wf
    errors: list[str] = []
    warnings: list[str] = []
    review: list[dict[str, Any]] = []
    feats: list[str] = []

    def result() -> dict[str, Any]:
        return {"status": "REJECTED" if errors else "ALLOWED", "errors": errors, "warnings": warnings,
                "human_review": review, "required_features": feats}

    if not isinstance(draft, dict):
        errors.append("draft must be a JSON object")
        return result()
    try:
        json.dumps(draft, allow_nan=False)
    except (TypeError, ValueError):
        errors.append("draft must be plain JSON (no NaN/Infinity or non-JSON values)")
        return result()

    name = draft.get("name")
    if not isinstance(name, str) or not name or safe_name(name) != name:
        errors.append("name must be a non-empty string of letters, digits, '_', '.' or '-' (no other characters)")
    if not isinstance(draft.get("receptor"), dict):
        errors.append("receptor must be an object (e.g. {\"pdb_id\": \"3PTB\"})")
    for k in sorted(set(draft) - KNOWN_DRAFT_KEYS, key=str):
        errors.append(f"unknown top-level key: {k!r}")
    for k in _NESTED_DICT_KEYS:
        if k in draft and draft[k] is not None and not isinstance(draft[k], dict):
            errors.append(f"{k} must be an object")
    ligs = draft.get("ligands")
    if ligs is not None and (not isinstance(ligs, list) or not all(isinstance(l, dict) for l in ligs)):
        errors.append("ligands must be a list of objects")

    # rule 3: human-decision keys
    msg = "human-decision key: only a person can set this at a gate"
    for path in wf.DECISION_KEYS:
        if path in PLANNABLE_DECISION_PATHS:
            continue          # range-checked as a parameter below (rule 4)
        has, val = wf._get_path(draft, path)
        if has and not _is_empty(val):
            errors.append(f"{'.'.join(path)}: {msg}")
    if isinstance(ligs, list):
        for i, l in enumerate(ligs):
            if isinstance(l, dict):
                for k in wf.LIGAND_DECISION_KEYS:
                    if not _is_empty(l.get(k)):
                        errors.append(f"ligands[{i}].{k}: {msg}")

    structural_ok = not errors
    # rules 4-6 need a structurally sound draft; otherwise helpers could trip on odd shapes
    if structural_ok:
        try:
            values = advisor.values_from_config(draft)
        except Exception:  # noqa: BLE001 - never let a malformed draft through
            errors.append("could not evaluate parameters")
            values = None
        if values is not None:
            for key in sorted(values):
                spec = _param_spec(key)
                if spec is None:
                    continue
                problem = _value_problem(spec, values[key])
                if problem:
                    errors.append(f"{key}: {problem} (got {values[key]!r})")
                elif key in SCIENCE_SENSITIVE_KEYS:
                    review.append({"key": key, "value": values[key]})
            try:
                feats = wf.required_features(draft)
            except Exception:  # noqa: BLE001
                errors.append("could not evaluate required features")
            if not errors:
                try:
                    goal = draft.get("goal")
                    if goal not in advisor.GOALS:     # same fallback Workflow uses
                        goal = "binding" if (draft.get("binding") or {}).get("enabled") else "teaching"
                    for item in advisor.check(values, advisor.features_from_config(draft), goal=goal, lang="en"):
                        text = str(item.get("message") or item.get("key"))     # check() already localises to English
                        if item.get("level") == "error":
                            errors.append(f"{item.get('key')}: {text}")
                        elif item.get("level") == "warning":
                            warnings.append(f"{item.get('key')}: {text}")
                except Exception:  # noqa: BLE001
                    errors.append("could not evaluate parameters")
    return result()


def capabilities_view(features: Any = None) -> list[dict[str, Any]]:
    """Read-only projection of capabilities.json for read_capabilities.

    Exposes id, feature (title), verification states and last-known result. Hides
    implementation paths and other internals (guide §1 rule 5: the LLM does not see source).
    Accepts a features list/dict for testing, or reads docs/capabilities.json by default.
    """
    if features is None:
        data = json.loads(_CAPABILITIES.read_text(encoding="utf-8"))
        features = data.get("features", [])
    if isinstance(features, dict):
        features = list(features.values())
    out: list[dict[str, Any]] = []
    for f in features:
        lkr = f.get("last_known_result")
        out.append({
            "id": f.get("id"),
            "feature": f.get("feature"),
            "states": f.get("states"),
            "last_known_status": (lkr.get("status") if isinstance(lkr, dict) else lkr),
            "released_installer": f.get("released_installer"),
        })
    return out
