"""MD protocol: tiers, stage specifications and a stable hash for identity checks.

A protocol is data, not code: it is written into run.json and hashed; any
later change creates a *new* run (never an in-place edit of a started one),
exactly as the Colab v6.1 design required.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict


@dataclass
class StageSpec:
    name: str                     # minimize | nvt | npt | production
    ensemble: str                 # "MIN" | "NVT" | "NPT"
    length_ps: float = 0.0
    timestep_fs: float = 2.0
    temperature_k: float = 300.0
    start_temperature_k: float | None = None   # linear ramp if set (heating)
    ramp_fraction: float = 0.6                 # fraction of the stage used for the ramp; the rest holds at target
    pressure_bar: float = 1.0
    friction_per_ps: float = 1.0
    restraint_scale: float = 1.0               # multiplies msw_restraint_scale global parameter
    restraint_scale_end: float | None = None   # linear release inside the stage if set
    report_interval_ps: float = 1.0
    trajectory_interval_ps: float = 10.0
    checkpoint_interval_ps: float = 50.0
    barostat_interval_steps: int = 25
    max_iterations: int = 5000                 # minimize only
    tolerance_kj_mol_nm: float = 10.0          # minimize only
    regenerate_velocities: bool = False
    seed: int = 2026
    accept: dict = field(default_factory=dict)  # acceptance thresholds, e.g. {"temp_tol_k":5,"density_cv":0.03}

    def steps(self) -> int:
        return max(1, int(round(self.length_ps * 1000.0 / self.timestep_fs)))

    def interval_steps(self, ps: float) -> int:
        return max(1, int(round(ps * 1000.0 / self.timestep_fs)))


@dataclass
class Protocol:
    tier: str
    hmr: bool
    stages: list[StageSpec]
    replicas: int = 1
    notes: str = ""

    def to_dict(self) -> dict:
        return {"tier": self.tier, "hmr": self.hmr, "replicas": self.replicas, "notes": self.notes,
                "stages": [asdict(s) for s in self.stages]}

    @classmethod
    def from_dict(cls, d: dict) -> "Protocol":
        return cls(tier=d["tier"], hmr=bool(d.get("hmr", False)), replicas=int(d.get("replicas", 1)),
                   notes=d.get("notes", ""), stages=[StageSpec(**s) for s in d["stages"]])

    def hash(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()[:16]

    def stage(self, name: str) -> StageSpec:
        for s in self.stages:
            if s.name == name:
                return s
        raise KeyError(name)

    def total_ns(self) -> float:
        return sum(s.length_ps for s in self.stages if s.ensemble != "MIN") / 1000.0


# Teaching tiers.  Lengths are deliberately short; the point is a *complete*
# pipeline that finishes on a laptop, with acceptance tests, not a long run.
TIERS = {
    "classroom": dict(hmr=True, dt=4.0, nvt_ps=100.0, npt_ps=200.0, prod_ps=2000.0,
                      notes="課堂 tier：2 ns production，CPU 筆電可在數小時內完成；用於學習流程與驗收，不用於下科學結論。"),
    "teaching": dict(hmr=True, dt=4.0, nvt_ps=200.0, npt_ps=500.0, prod_ps=10000.0,
                     notes="教學 tier：10 ns production + HMR 4 fs；CPU 筆電約 1–3 天，筆電 GPU 數小時。"),
    "research": dict(hmr=False, dt=2.0, nvt_ps=500.0, npt_ps=1000.0, prod_ps=100000.0,
                     notes="研究 tier：2 fs、100 ns；需要獨立 GPU，建議 ≥3 replica。"),
}


def make_protocol(tier: str = "teaching", *, seed: int = 2026, replicas: int | None = None,
                  production_ns: float | None = None) -> Protocol:
    if tier not in TIERS:
        raise KeyError(f"未知 tier：{tier}（可用：{', '.join(TIERS)}）")
    t = TIERS[tier]
    dt = t["dt"]
    prod_ps = float(production_ns) * 1000.0 if production_ns is not None else t["prod_ps"]
    stages = [
        StageSpec(name="minimize", ensemble="MIN", timestep_fs=dt, restraint_scale=1.0,
                  max_iterations=5000, tolerance_kj_mol_nm=10.0, seed=seed),
        # Heating 50 → 300 K under full restraints, then hold.
        StageSpec(name="nvt", ensemble="NVT", length_ps=t["nvt_ps"], timestep_fs=dt, temperature_k=300.0,
                  start_temperature_k=50.0, restraint_scale=1.0, report_interval_ps=0.5,
                  trajectory_interval_ps=10.0, checkpoint_interval_ps=25.0, regenerate_velocities=True,
                  seed=seed, accept={"temp_tol_k": 5.0, "last_fraction": 0.3}),
        # Pressure coupling with restraints released linearly 1.0 → 0.0.
        StageSpec(name="npt", ensemble="NPT", length_ps=t["npt_ps"], timestep_fs=dt, temperature_k=300.0,
                  restraint_scale=1.0, restraint_scale_end=0.0, report_interval_ps=1.0,
                  trajectory_interval_ps=10.0, checkpoint_interval_ps=50.0, seed=seed,
                  accept={"temp_tol_k": 5.0, "density_cv": 0.03, "last_fraction": 0.3}),
        StageSpec(name="production", ensemble="NPT", length_ps=prod_ps, timestep_fs=dt, temperature_k=300.0,
                  restraint_scale=0.0, report_interval_ps=2.0, trajectory_interval_ps=20.0,
                  checkpoint_interval_ps=200.0, seed=seed, accept={"temp_tol_k": 5.0, "density_cv": 0.03}),
    ]
    return Protocol(tier=tier, hmr=bool(t["hmr"]), stages=stages,
                    replicas=int(replicas if replicas is not None else (3 if tier == "research" else 1)),
                    notes=t["notes"])
