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


def safe_key_spec(key: str) -> dict[str, Any] | None:
    """Type/range/choices for a whitelisted safe key (from advisor.PARAMS), else None."""
    if key not in SAFE_KEYS:
        return None
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
    t = spec.get("type")
    if t in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return {"key": key, "value": value, "status": "REJECTED", "reason": f"expected {t}"}
        if t == "int" and int(value) != value:
            return {"key": key, "value": value, "status": "REJECTED", "reason": "expected an integer"}
        lo, hi = spec.get("min"), spec.get("max")
        if lo is not None and value < lo:
            return {"key": key, "value": value, "status": "REJECTED", "reason": f"below minimum {lo}"}
        if hi is not None and value > hi:
            return {"key": key, "value": value, "status": "REJECTED", "reason": f"above maximum {hi}"}
    elif t == "choice":
        if value not in spec.get("choices", []):
            return {"key": key, "value": value, "status": "REJECTED",
                    "reason": f"not one of {spec.get('choices')}"}
    elif t == "bool":
        if not isinstance(value, bool):
            return {"key": key, "value": value, "status": "REJECTED", "reason": "expected bool"}
    return {"key": key, "value": value, "status": "ALLOWED",
            "reason": "within range; a human must confirm before MD20 applies it"}


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
