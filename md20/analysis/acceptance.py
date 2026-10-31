"""Scientific acceptance gates for equilibration stages.

A stage is not "done" because it ran to the last step; it is done when the
final window is at the target temperature (NVT/NPT) and the density has
settled (NPT).  Failing stages get a concrete recommendation (extend by X ps)
rather than a bare failure.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .logs import log_stats


@dataclass
class AcceptanceResult:
    status: str                 # PASS | EXTEND | NEEDS_HUMAN
    checks: list[dict] = field(default_factory=list)
    recommendation: str = ""
    extend_ps: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == "PASS"


def evaluate_acceptance(df: pd.DataFrame, *, ensemble: str, target_temperature_k: float, length_ps: float,
                        temp_tol_k: float = 5.0, density_cv: float = 0.03, last_fraction: float = 0.3,
                        energy_drift_tol_kj_mol_ns: float | None = None) -> AcceptanceResult:
    stats = log_stats(df, last_fraction=last_fraction)
    checks = []
    if stats.get("n", 0) < 5:
        return AcceptanceResult("NEEDS_HUMAN", [{"check": "log", "ok": False, "detail": "log 行數不足，無法驗收"}],
                                "StateData log 幾乎是空的；請確認 report interval 與 stage 長度。")
    ok_all = True
    t = stats.get("temperature_k")
    if t:
        ok = abs(t["mean"] - target_temperature_k) <= temp_tol_k
        checks.append({"check": "temperature", "ok": ok, "mean_k": round(t["mean"], 2), "target_k": target_temperature_k,
                       "tol_k": temp_tol_k, "std_k": round(t["std"], 2)})
        ok_all &= ok
    if ensemble.upper() == "NPT":
        d = stats.get("density_g_ml")
        if d and d["cv"] is not None:
            ok = d["cv"] <= density_cv
            drift_ok = True
            window_ns = length_ps * last_fraction / 1000.0
            change_pct = None
            if d.get("drift_per_ns") is not None and d["mean"]:
                # density should not still be trending: total change across the acceptance window < 0.5 %
                change_pct = 100.0 * d["drift_per_ns"] * window_ns / abs(d["mean"])
                drift_ok = abs(change_pct) <= 0.5
            checks.append({"check": "density_cv", "ok": ok, "cv": round(d["cv"], 4), "limit": density_cv})
            checks.append({"check": "density_drift", "ok": drift_ok, "window_ns": round(window_ns, 4),
                           "change_pct_over_window": round(change_pct, 3) if change_pct is not None else None, "limit_pct": 0.5})
            ok_all &= ok and drift_ok
    if energy_drift_tol_kj_mol_ns is not None and stats.get("total_kj_mol", {}).get("drift_per_ns") is not None:
        drift = stats["total_kj_mol"]["drift_per_ns"]
        ok = abs(drift) <= energy_drift_tol_kj_mol_ns
        checks.append({"check": "energy_drift", "ok": ok, "drift_kj_mol_ns": round(drift, 2)})
        ok_all &= ok
    if ok_all:
        return AcceptanceResult("PASS", checks, "末段溫度／密度皆在容許範圍內。")
    extend = max(50.0, round(0.5 * length_ps, 0))
    failed = [c["check"] for c in checks if not c["ok"]]
    return AcceptanceResult("EXTEND", checks,
                            f"未通過：{', '.join(failed)}。建議自動延長 {extend:.0f} ps 後重新驗收；"
                            "若延長兩次仍未通過，請檢查約束釋放與 barostat 設定。", extend_ps=extend)
