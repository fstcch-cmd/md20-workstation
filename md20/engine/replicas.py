"""Multiple independent replicas (different seeds) and their aggregation.

Industry practice: never conclude from one trajectory.  `run_replicas` creates
N runs of the same protocol with seeds `seed + 1000*i`, runs them one after
another (a laptop has one GPU), and `aggregate_replicas` reports per-stage
mean ± SD across replicas plus an overlay figure.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Callable

import numpy as np

from ..analysis import read_state_log, log_stats
from ..analysis.plots import PALETTE, _mpl, _save
from ..project import Case, Run
from ..util import atomic_write_json, load_json, now_iso
from .protocol import Protocol
from .runner import run_protocol
from .chunks import NeedsHuman, Paused


def replica_protocol(base: Protocol, index: int) -> Protocol:
    stages = [dataclasses.replace(s, seed=s.seed + 1000 * index) for s in base.stages]
    return Protocol(tier=base.tier, hmr=base.hmr, stages=stages, replicas=base.replicas, notes=base.notes)


def run_replicas(case: Case, base: Protocol, make_backend: Callable, *, n: int | None = None, identity_extra: dict | None = None,
                 progress_cb=None, should_pause=None, batch_steps: int | None = None, group_id: str | None = None) -> dict:
    """Run (or resume) N replicas.  With `group_id`, existing runs of that group are resumed from file truth."""
    n = int(n or base.replicas or 1)
    group_id = group_id or f"rep_{now_iso().replace(':', '').replace('-', '')}"
    existing = {r.manifest().get("replica_index"): r for r in case.runs() if r.manifest().get("replica_group") == group_id}
    results = []
    for i in range(n):
        proto = replica_protocol(base, i)
        run = existing.get(i)
        if run is not None and run.manifest().get("status") == "COMPLETE":
            results.append({"run_id": run.run_id, "status": "COMPLETE"})
            continue
        if run is None:
            run = case.new_run(proto.to_dict(), reason=f"replica {i + 1}/{n} of {group_id}")
            m = run.manifest(); m.update({"replica_group": group_id, "replica_index": i}); run.save_manifest(m)
        ident = {"case_id": case.case_id, "run_id": run.run_id, "project_uuid": case.project.uuid, **(identity_extra or {})}
        try:
            st = run_protocol(run.dir, proto, make_backend, identity=ident, decisions=case.project.decisions,
                              progress_cb=progress_cb, should_pause=should_pause, batch_steps=batch_steps)
            results.append({"run_id": run.run_id, "status": st["status"]})
        except Paused as exc:
            results.append({"run_id": run.run_id, "status": "PAUSED", "reason": str(exc)})
            break
        except NeedsHuman as exc:
            results.append({"run_id": run.run_id, "status": "NEEDS_HUMAN", "reason": str(exc)})
    summary = {"group_id": group_id, "n_requested": n, "runs": results, "created_at": now_iso()}
    cm = case.manifest(); cm.setdefault("replica_groups", {})[group_id] = summary; case.save_manifest(cm)
    if all(r["status"] == "COMPLETE" for r in results) and len(results) == n:
        summary["aggregate"] = aggregate_replicas(case, group_id)
    return summary


def aggregate_replicas(case: Case, group_id: str, *, out_dir: Path | None = None) -> dict:
    runs = [r for r in case.runs() if r.manifest().get("replica_group") == group_id]
    out_dir = out_dir or (case.dir / "replica_analysis" / group_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    agg = {"group_id": group_id, "n": len(runs), "stages": {}, "figures": {}}
    frames: dict[str, list] = {}
    for stage in ("nvt", "npt", "production"):
        per = []
        for r in runs:
            comp = load_json(r.dir / "stages" / stage / f"{stage}_complete.json", {})
            lp = (comp.get("result") or {}).get("log_path")
            if not lp or not Path(lp).is_file():
                continue
            df = read_state_log(lp)
            frames.setdefault(stage, []).append((r.run_id, df))
            st = log_stats(df, last_fraction=0.3)
            per.append({"run_id": r.run_id, "temperature_k": st.get("temperature_k", {}).get("mean"),
                        "density_g_ml": st.get("density_g_ml", {}).get("mean"),
                        "potential_kj_mol": st.get("potential_kj_mol", {}).get("mean"),
                        "accepted": ((comp.get("acceptance") or {}).get("status") == "PASS")})
        if per:
            def ms(key):
                v = np.array([p[key] for p in per if p[key] is not None], dtype=float)
                return {"mean": float(v.mean()), "sd": float(v.std(ddof=1)) if len(v) > 1 else 0.0, "n": int(len(v))} if len(v) else None
            agg["stages"][stage] = {"per_replica": per, "temperature_k": ms("temperature_k"), "density_g_ml": ms("density_g_ml"),
                                    "potential_kj_mol": ms("potential_kj_mol"), "all_accepted": all(p["accepted"] for p in per)}
    if "production" in frames:
        agg["figures"]["production_overlay"] = _overlay(frames["production"], out_dir / "production_replicas")
    atomic_write_json(agg, out_dir / "replica_aggregate.json")
    return agg


def _overlay(frames: list[tuple[str, "pd.DataFrame"]], out_base: Path) -> dict:  # noqa: F821
    plt = _mpl()
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 4.4), sharex=True)
    for i, (rid, df) in enumerate(frames):
        t = df["time_ps"].to_numpy(dtype=float) / 1000.0
        c = PALETTE[i % len(PALETTE)]
        axes[0].plot(t, df["temperature_k"], color=c, linewidth=1.0, alpha=0.9, label=f"replica {i + 1}")
        if "potential_kj_mol" in df:
            axes[1].plot(t, df["potential_kj_mol"], color=c, linewidth=1.0, alpha=0.9)
    axes[0].set_ylabel("Temperature (K)"); axes[1].set_ylabel("Potential energy (kJ/mol)"); axes[1].set_xlabel("Time (ns)")
    axes[0].set_title(f"Production — {len(frames)} replicas (independent seeds)", loc="left", fontsize=10)
    axes[0].legend(frameon=False, fontsize=7, ncol=min(4, len(frames)))
    return _save(fig, out_base)
