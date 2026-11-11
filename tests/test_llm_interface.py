# -*- coding: utf-8 -*-
"""L0 (D-178) interface-definition tests. Pure; no engine, no LLM, no I/O beyond capabilities.json."""
from __future__ import annotations

import re
from pathlib import Path

from md20 import advisor
from md20.llm import (
    ACTIONS,
    SAFE_KEYS,
    SCIENCE_SENSITIVE_KEYS,
    action_names,
    capabilities_view,
    safe_key_spec,
    validate_proposed_change,
)

ROOT = Path(__file__).resolve().parents[1]


def test_actions_match_the_guide_table():
    guide = (ROOT / "docs/llm/MD20_LLM_GUIDE.md").read_text(encoding="utf-8")
    # every action name appears as a `code` cell in the guide's §3 table, and vice versa
    for name in action_names():
        assert f"`{name}`" in guide, f"{name} missing from MD20_LLM_GUIDE.md"
    cells = set(re.findall(r"`([a-z_]+)`", guide))
    for name in action_names():
        assert name in cells


def test_no_apply_or_execute_action_exists():
    names = set(action_names())
    for forbidden in ("apply_config", "apply", "execute", "run_now", "write_config", "edit_code", "commit"):
        assert forbidden not in names
    # the contract actions: the original seven plus read_report (L1)
    assert len(ACTIONS) == 8


def test_propose_actions_are_marked_proposal_only():
    for a in ACTIONS:
        assert a["mode"] in ("read", "propose")
        if a["mode"] == "propose" and a["name"] != "write_report_narrative":
            assert "confirm" in a["limits"].lower() or "schema" in a["limits"].lower()


def test_safe_and_sensitive_sets_are_disjoint():
    assert SAFE_KEYS.isdisjoint(SCIENCE_SENSITIVE_KEYS)


def test_every_safe_key_exists_in_params_with_a_range_or_choices():
    for k in SAFE_KEYS:
        assert k in advisor.PARAMS, f"{k} not in advisor.PARAMS"
        spec = safe_key_spec(k)
        assert spec is not None
        assert spec["type"] in ("int", "float", "choice", "bool")


def test_known_science_sensitive_keys_are_classified_and_rejected():
    # the force-field / state / restraint / integrator / SMD knobs must never be proposable
    for k in ("timestep_fs", "temperature_k", "restraints", "k_umbrella", "solvent", "ion_concentration_molar"):
        assert k in SCIENCE_SENSITIVE_KEYS
        v = validate_proposed_change(k, 1.0)
        assert v["status"] == "REJECTED" and "science-sensitive" in v["reason"]


def test_no_params_key_is_silently_unclassified_among_sensitive_candidates():
    # every advisor param is either whitelisted safe or explicitly sensitive — no silent gap
    unclassified = set(advisor.PARAMS) - SAFE_KEYS - SCIENCE_SENSITIVE_KEYS
    assert unclassified == set(), f"unclassified config keys (classify before exposing): {unclassified}"


def test_validate_allows_in_range_safe_value():
    v = validate_proposed_change("production_ns", 5.0)
    assert v["status"] == "ALLOWED" and "confirm" in v["reason"]
    v2 = validate_proposed_change("padding_nm", 1.2)
    assert v2["status"] == "ALLOWED"


def test_validate_rejects_out_of_range_and_wrong_type():
    assert validate_proposed_change("padding_nm", 99.0)["status"] == "REJECTED"   # above max 3.0
    assert validate_proposed_change("replicas", 2.5)["status"] == "REJECTED"      # not int
    assert validate_proposed_change("production_ns", "lots")["status"] == "REJECTED"
    assert validate_proposed_change("replicas", True)["status"] == "REJECTED"     # bool is not an int here


def test_validate_rejects_unknown_key():
    assert validate_proposed_change("totally_made_up", 1)["status"] == "REJECTED"


def test_capabilities_view_hides_implementation_and_keeps_states():
    sample = [{"id": "docking_vina", "feature": "docking", "states": {"implemented": True},
               "implementation": ["md20/docking/run.py::dock"], "last_known_result": {"status": "ok"}}]
    view = capabilities_view(sample)
    assert view[0]["id"] == "docking_vina"
    assert view[0]["states"] == {"implemented": True}
    assert view[0]["last_known_status"] == "ok"
    assert "implementation" not in view[0]   # source paths never exposed to the LLM


def test_capabilities_view_reads_real_manifest():
    view = capabilities_view()
    assert len(view) >= 1 and all("implementation" not in v for v in view)
