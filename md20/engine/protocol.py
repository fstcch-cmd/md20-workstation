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
    # per-group restraint multipliers {group: [start, end]} on top of msw_restraint_scale (groups: backbone,
    # sidechain, ligand — build/assemble.add_position_restraints); empty = every group at 1.0 (single global schedule)
    restraint_groups: dict = field(default_factory=dict)
    freeze: bool = False                        # use the build's frozen-atom set (mass 0) in this stage
    # auto-extension keeps the ramp/restraint schedule of the *original* length: a +50 ps extension must not pull
    # released restraints back up or the thermostat target back down (schedule fraction = time / schedule_length_ps)
    schedule_length_ps: float | None = None

    def steps(self) -> int:
        return max(1, int(round(self.length_ps * 1000.0 / self.timestep_fs)))

    def interval_steps(self, ps: float) -> int:
        return max(1, int(round(ps * 1000.0 / self.timestep_fs)))


def _stage_dict(s: StageSpec) -> dict:
    """asdict without the optional fields at their defaults, so protocols (and their hashes) written before those
    fields existed are unchanged — runs in progress keep resuming."""
    d = asdict(s)
    if not d.get("restraint_groups"):
        d.pop("restraint_groups", None)
    if not d.get("freeze"):
        d.pop("freeze", None)
    if d.get("schedule_length_ps") is None:
        d.pop("schedule_length_ps", None)
    return d


@dataclass
class Protocol:
    tier: str
    hmr: bool
    stages: list[StageSpec]
    replicas: int = 1
    notes: str = ""

    def to_dict(self) -> dict:
        return {"tier": self.tier, "hmr": self.hmr, "replicas": self.replicas, "notes": self.notes,
                "stages": [_stage_dict(s) for s in self.stages]}

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


# Restraint strategies (consultation §1 Q1, D-23).  Each stage: (master msw_restraint_scale [start, end],
# {group: [start, end]}).  The main release happens in NPT (Amber/Desmond practice): releasing in NVT lets the protein
# relax at the wrong density.  Position restraints k ≤ 1000 under a MonteCarloBarostat bias the volume negligibly.
RESTRAINT_STRATEGIES = {
    "standard": {
        "nvt": {"backbone": [1.0, 1.0], "sidechain": [1.0, 0.5], "ligand": [1.0, 1.0]},
        "npt": {"backbone": [1.0, 0.0], "sidechain": [0.5, 0.0], "ligand": [1.0, 0.0]},
        "production": None,
    },
    # rough starting structures (models, rebuilt loops, clashing poses, peptides, bonded metal sites): hold everything
    # through heating, release over an NPT twice as long
    "gentle": {
        "nvt": {"backbone": [1.0, 1.0], "sidechain": [1.0, 1.0], "ligand": [1.0, 1.0]},
        "npt": {"backbone": [1.0, 0.0], "sidechain": [1.0, 0.0], "ligand": [1.0, 0.0]},
        "production": None,
        "npt_length_factor": 2.0,
    },
    # backbone kept at 5 % (50 kJ/mol/nm²) through production — RMSD/RMSF are then *restrained* quantities
    "hold_backbone": {
        "nvt": {"backbone": [1.0, 1.0], "sidechain": [1.0, 0.5], "ligand": [1.0, 1.0]},
        "npt": {"backbone": [1.0, 0.05], "sidechain": [0.5, 0.0], "ligand": [1.0, 0.0]},
        "production": {"backbone": [0.05, 0.05], "sidechain": [0.0, 0.0], "ligand": [0.0, 0.0]},
    },
}


def make_protocol(tier: str = "teaching", *, seed: int = 2026, replicas: int | None = None,
                  production_ns: float | None = None, restraints: str = "standard") -> Protocol:
    if tier not in TIERS:
        raise KeyError(f"未知 tier：{tier}（可用：{', '.join(TIERS)}）")
    if restraints not in RESTRAINT_STRATEGIES:
        raise KeyError(f"未知約束策略：{restraints}（可用：{', '.join(RESTRAINT_STRATEGIES)}）")
    t = TIERS[tier]
    rs = RESTRAINT_STRATEGIES[restraints]
    dt = t["dt"]
    prod_ps = float(production_ns) * 1000.0 if production_ns is not None else t["prod_ps"]
    prod_groups = rs.get("production")
    stages = [
        # minimization ladder 1.0 → 0.5 → 0 on the master scale; ligand k (1000) ≥ backbone k: a docked pose drifts
        # most easily before the solvent has relaxed
        StageSpec(name="minimize", ensemble="MIN", timestep_fs=dt, restraint_scale=1.0,
                  max_iterations=5000, tolerance_kj_mol_nm=10.0, seed=seed),
        # Heating 50 → 300 K with the backbone and ligand held; only side chains start to relax
        StageSpec(name="nvt", ensemble="NVT", length_ps=t["nvt_ps"], timestep_fs=dt, temperature_k=300.0,
                  start_temperature_k=50.0, restraint_scale=1.0, restraint_groups=_copy_groups(rs["nvt"]),
                  report_interval_ps=0.5, trajectory_interval_ps=10.0, checkpoint_interval_ps=25.0,
                  regenerate_velocities=True, seed=seed, accept={"temp_tol_k": 5.0, "last_fraction": 0.3}),
        # Pressure coupling at the right density; the restraints are released here
        StageSpec(name="npt", ensemble="NPT", length_ps=t["npt_ps"] * float(rs.get("npt_length_factor", 1.0)),
                  timestep_fs=dt, temperature_k=300.0, restraint_scale=1.0, restraint_groups=_copy_groups(rs["npt"]),
                  report_interval_ps=1.0, trajectory_interval_ps=10.0, checkpoint_interval_ps=50.0, seed=seed,
                  accept={"temp_tol_k": 5.0, "density_cv": 0.03, "last_fraction": 0.3}),
        StageSpec(name="production", ensemble="NPT", length_ps=prod_ps, timestep_fs=dt, temperature_k=300.0,
                  restraint_scale=1.0 if prod_groups else 0.0, restraint_groups=_copy_groups(prod_groups or {}),
                  report_interval_ps=2.0, trajectory_interval_ps=20.0,
                  checkpoint_interval_ps=200.0, seed=seed, accept={"temp_tol_k": 5.0, "density_cv": 0.03}),
    ]
    notes = t["notes"]
    if restraints != "standard":
        notes += f" 約束策略：{restraints}。"
    return Protocol(tier=tier, hmr=bool(t["hmr"]), stages=stages,
                    replicas=int(replicas if replicas is not None else (3 if tier == "research" else 1)),
                    notes=notes)


def _copy_groups(g: dict) -> dict:
    return {k: [float(a), float(b)] for k, (a, b) in g.items()}


def production_restraints(protocol: dict | Protocol) -> dict:
    """Groups still restrained in production {group: max multiplier}; empty = free production.  Used to flag RMSD/RMSF
    as *restrained* (consultation §1 Q1: a low RMSD under a backbone restraint is not evidence of stability)."""
    d = protocol.to_dict() if isinstance(protocol, Protocol) else (protocol or {})
    for st in d.get("stages") or []:
        if st.get("name") != "production":
            continue
        master = float(st.get("restraint_scale", 0.0) or 0.0)
        if st.get("restraint_scale_end") is not None:
            master = max(master, float(st["restraint_scale_end"]))
        if master <= 0:
            return {}
        groups = st.get("restraint_groups") or {}
        if not groups:
            return {"all": master}
        return {g: master * max(float(a), float(b)) for g, (a, b) in groups.items() if max(float(a), float(b)) > 0}
    return {}


def implicit_solvent_protocol(proto: Protocol) -> Protocol:
    """GBn2 has no box: NPT stages become NVT (the restraint release they carry is kept) and the density acceptance is
    dropped.  Only used when the build is implicit, so explicit-solvent protocols and their hashes are unchanged."""
    import copy
    out = copy.deepcopy(proto)
    for st in out.stages:
        if st.ensemble == "NPT":
            st.ensemble = "NVT"
            st.accept = {k: v for k, v in (st.accept or {}).items() if k != "density_cv"}
    out.notes = (out.notes + " " if out.notes else "") + "隱式溶劑（GBn2）：無週期盒，全部 NVT。"
    return out
