# -*- coding: utf-8 -*-
"""L0 of the LLM orchestration track (D-161, assigned 2026-11-10 → D-178).

This package is the **interface definition only**: the contract that later adapters
(L1 MCP, BYO-key panel, REST) will implement against. It is NOT a running server, it
does NOT call any LLM, and it NEVER applies a change. Mid-run remedies are propose-only
and applied by MD20 after the user confirms (D-177). Nothing here touches the engine,
the force field, or any science-sensitive setting.
"""
from .interface import (
    ACTIONS,
    SAFE_KEYS,
    SCIENCE_SENSITIVE_KEYS,
    action_names,
    capabilities_view,
    safe_key_spec,
    validate_proposed_change,
)

__all__ = [
    "ACTIONS",
    "SAFE_KEYS",
    "SCIENCE_SENSITIVE_KEYS",
    "action_names",
    "capabilities_view",
    "safe_key_spec",
    "validate_proposed_change",
]
