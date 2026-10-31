"""Enhanced sampling: umbrella-window quality, WHAM/MBAR PMF, window planning.

`_mdh_legacy` is the 0913 hardening library (salvaged verbatim); `pmf` wraps the
parts we use with tests and figures; `windows` plans umbrella windows from an
SMD trajectory (new).
"""
from .pmf import umbrella_quality, pmf_from_windows, PMFResult
from .windows import plan_windows, WindowPlan

__all__ = ["umbrella_quality", "pmf_from_windows", "PMFResult", "plan_windows", "WindowPlan"]
