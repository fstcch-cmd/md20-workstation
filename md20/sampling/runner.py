"""SMD and umbrella-sampling runner on top of an equilibrated MD20 system.

Inputs: `system.xml` + `topology.pdb` (from build) + an equilibrated State XML (NPT or production).
CV: COM(anchor CA atoms) → COM(ligand heavy atoms) distance, harmonic bias on a
`CustomCentroidBondForce` with global parameters `smd_k` and `smd_r0`.

SMD:     r0(t) = r_start + v·t; records r, r0, force, cumulative work (kJ/mol); saves a State
         XML each time r crosses a planned window centre (window seeds).
Umbrella: one resumable job per window (fixed r0 = centre, k = k_umbrella); CV time series →
         `md20.sampling.pmf.pmf_from_windows` → PMF ± bootstrap, figures, binding summary.

All stages write JSON completion manifests so a laptop can stop and resume.
"""
from __future__ import annotations

import csv
import math
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np

from ..util import atomic_write_json, load_json, now_iso, DecisionLog
from .cv import select_groups, com_distance, pulling_direction, box_clearance_nm
from .windows import plan_windows
from .pmf import pmf_from_windows
from ..analysis.plots import _mpl, _save, PALETTE

KB = 0.00831446261815324


@dataclass
class SMDSpec:
    pull_velocity_nm_per_ps: float = 0.005      # 5 nm/ns (teaching tier: fast but informative)
    k_pull_kj_mol_nm2: float = 2000.0
    pull_distance_nm: float = 1.2
    timestep_fs: float = 2.0
    temperature_k: float = 300.0
    friction_per_ps: float = 1.0
    anchor_restraint_k: float = 200.0           # weak CA restraint on the anchor so the protein is not dragged
    report_interval_ps: float = 0.5
    hmr: bool = False
    seed: int = 2026


@dataclass
class UmbrellaSpec:
    k_umbrella_kj_mol_nm2: float = 1000.0
    window_length_ps: float = 200.0            # teaching tier; research ≥ 2 ns
    equilibration_ps: float = 20.0
    sample_interval_ps: float = 0.2
    target_overlap: float = 0.25
    timestep_fs: float = 2.0
    temperature_k: float = 300.0
    seed: int = 2026


def _make_sim(system_xml, topology_pdb, platform_name, platform_props, *, timestep_fs, temperature_k, friction, seed,
              groups, k_pull, r0, anchor_restraint_k, hmr=False):
    import openmm as mm
    from openmm import app, unit, XmlSerializer
    system = XmlSerializer.deserialize(Path(system_xml).read_text(encoding="utf-8"))
    pdb = app.PDBFile(str(topology_pdb))
    # drop the equilibration position restraints if present (they carry msw_restraint_scale)
    for i in reversed(range(system.getNumForces())):
        f = system.getForce(i)
        if f.getName() == "msw_position_restraints":
            system.removeForce(i)
    # turn off barostat: SMD/US run in NVT at the equilibrated box
    for i in reversed(range(system.getNumForces())):
        if isinstance(system.getForce(i), mm.MonteCarloBarostat):
            system.removeForce(i)
    if hmr:
        from ..engine.backend import apply_hmr
        apply_hmr(system, pdb.topology)
    cv = mm.CustomCentroidBondForce(2, "0.5*smd_k*(distance(g1,g2)-smd_r0)^2")
    cv.addGlobalParameter("smd_k", float(k_pull))
    cv.addGlobalParameter("smd_r0", float(r0))
    cv.addGroup([int(i) for i in groups["anchor"]])
    cv.addGroup([int(i) for i in groups["ligand"]])
    cv.addBond([0, 1], [])
    cv.setUsesPeriodicBoundaryConditions(True)
    cv.setName("md20_cv_bias")
    system.addForce(cv)
    if anchor_restraint_k > 0:
        pos = pdb.positions.value_in_unit(unit.nanometer)
        ar = mm.CustomExternalForce("0.5*anchor_k*periodicdistance(x,y,z,x0,y0,z0)^2")
        ar.addGlobalParameter("anchor_k", float(anchor_restraint_k))
        for p in ("x0", "y0", "z0"):
            ar.addPerParticleParameter(p)
        for i in groups["anchor"]:
            ar.addParticle(int(i), list(pos[int(i)]))
        ar.setName("md20_anchor_restraint")
        system.addForce(ar)
    integ = mm.LangevinMiddleIntegrator(temperature_k * unit.kelvin, friction / unit.picosecond, timestep_fs * unit.femtoseconds)
    integ.setRandomNumberSeed(int(seed))
    sim = app.Simulation(pdb.topology, system, integ, mm.Platform.getPlatformByName(platform_name), platform_props or {})
    masses = np.array([system.getParticleMass(i).value_in_unit(unit.dalton) for i in range(system.getNumParticles())])
    return sim, masses


def _state_xyz_box(sim):
    from openmm import unit
    st = sim.context.getState(getPositions=True)
    xyz = st.getPositions(asNumpy=True).value_in_unit(unit.nanometer)
    a, b, c = st.getPeriodicBoxVectors()
    box = np.array([a.x, b.y, c.z])
    return xyz, box


def _load_state_positions(sim, state_xml):
    sim.loadState(str(state_xml))


def run_smd(out_dir: Path | str, *, system_xml, topology_pdb, start_state_xml, ligand_resnames: set[str],
            spec: SMDSpec, platform_name: str = "CPU", platform_props: dict | None = None,
            anchor_residues: list[tuple[str, int]] | None = None, decisions: DecisionLog | None = None,
            window_centers_nm: list[float] | None = None, progress_cb=None) -> dict:
    """Steered MD along the anchor→ligand COM distance.  Returns manifest (also written to smd_manifest.json)."""
    from openmm import app, unit
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    done = load_json(out / "smd_manifest.json", {})
    if done.get("status") == "PASS":
        return done
    pdb = app.PDBFile(str(topology_pdb))
    pos0 = pdb.positions.value_in_unit(unit.nanometer)
    groups = select_groups(pdb.topology, np.asarray(pos0), ligand_resnames=ligand_resnames, anchor_residues=anchor_residues)
    sim, masses = _make_sim(system_xml, topology_pdb, platform_name, platform_props, timestep_fs=spec.timestep_fs,
                            temperature_k=spec.temperature_k, friction=spec.friction_per_ps, seed=spec.seed, groups=groups,
                            k_pull=spec.k_pull_kj_mol_nm2, r0=0.0, anchor_restraint_k=spec.anchor_restraint_k, hmr=spec.hmr)
    _load_state_positions(sim, start_state_xml)
    xyz, box = _state_xyz_box(sim)
    r_start = com_distance(xyz, groups["anchor"], groups["ligand"], box, masses)
    direction = pulling_direction(xyz, groups, box)
    clearance = box_clearance_nm(xyz, groups, box, direction)
    r_end = r_start + spec.pull_distance_nm
    notes = [groups["reason"]]
    if spec.pull_distance_nm > clearance - 0.3:
        notes.append(f"警告：拉伸距離 {spec.pull_distance_nm:.2f} nm 接近水盒半長餘裕 {clearance:.2f} nm；越過後配體會更靠近蛋白的週期鏡像。")
    sim.context.setParameter("smd_r0", r_start)
    # anchor restraint reference = current positions
    st = sim.context.getState(getPositions=True)
    total_ps = spec.pull_distance_nm / spec.pull_velocity_nm_per_ps
    steps_total = int(round(total_ps * 1000 / spec.timestep_fs))
    report_steps = max(1, int(round(spec.report_interval_ps * 1000 / spec.timestep_fs)))
    seeds_wanted = sorted(window_centers_nm or [])
    seeds_done: dict[float, str] = {}
    rows = []
    work = 0.0
    r_prev_r0 = r_start
    t0 = time.monotonic()
    dcd = app.DCDReporter(str(out / "smd.dcd"), report_steps, enforcePeriodicBox=False)
    sim.reporters.append(dcd)
    step = 0
    while step < steps_total:
        n = min(report_steps, steps_total - step)
        sim.step(n); step += n
        t_ps = step * spec.timestep_fs / 1000.0
        r0 = r_start + spec.pull_velocity_nm_per_ps * t_ps
        sim.context.setParameter("smd_r0", r0)
        xyz, box = _state_xyz_box(sim)
        r = com_distance(xyz, groups["anchor"], groups["ligand"], box, masses)
        force = spec.k_pull_kj_mol_nm2 * (r0 - r)          # kJ/mol/nm, positive = pulling outward
        work += force * (r0 - r_prev_r0)                     # W = ∫ F dr0
        r_prev_r0 = r0
        pe = sim.context.getState(getEnergy=True).getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
        if not math.isfinite(pe):
            raise RuntimeError("SMD 期間能量 NaN；請降低拉伸速度或 k。")
        rows.append({"time_ps": t_ps, "r0_nm": r0, "r_nm": r, "force_kj_mol_nm": force, "work_kj_mol": work, "pe_kj_mol": pe})
        for c in seeds_wanted:
            if c not in seeds_done and r >= c:
                p = out / f"seed_{c:.3f}nm.xml"
                sim.saveState(str(p)); seeds_done[c] = str(p)
        if progress_cb:
            progress_cb({"stage": "smd", "time_ps": t_ps, "total_ps": total_ps, "r_nm": r, "work_kj_mol": work,
                         "elapsed_s": round(time.monotonic() - t0, 1)})
    sim.reporters.clear()
    sim.saveState(str(out / "smd_final.xml"))
    with open(out / "smd_trace.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    figs = plot_smd(rows, out / "smd_force_work")
    manifest = {"status": "PASS", "r_start_nm": r_start, "r_end_nm": r_end, "direction": direction.tolist(),
                "box_clearance_nm": clearance, "groups": {"ligand": groups["ligand"].tolist(), "anchor": groups["anchor"].tolist()},
                "spec": asdict(spec), "work_total_kj_mol": work, "max_force_kj_mol_nm": max(r["force_kj_mol_nm"] for r in rows),
                "seeds": {f"{k:.3f}": v for k, v in seeds_done.items()}, "notes": notes, "trace_csv": str(out / "smd_trace.csv"),
                "dcd": str(out / "smd.dcd"), "figures": figs, "platform": platform_name, "created_at": now_iso()}
    atomic_write_json(manifest, out / "smd_manifest.json")
    if decisions:
        decisions.record("sampling.smd", "anchor", groups["reason"], "SMD 的拉伸參考點；anchor CA 加弱約束避免整體蛋白被拖動。")
        decisions.record("sampling.smd", "pulling", f"v={spec.pull_velocity_nm_per_ps} nm/ps, k={spec.k_pull_kj_mol_nm2}",
                         "教學 tier 的快速 SMD：目的為產生 umbrella window 起始構形與初步的力–距離曲線；拉伸功是非平衡量，不是 ΔG。")
    return manifest


def plot_smd(rows: list[dict], out_base: Path) -> dict:
    plt = _mpl()
    r = np.array([x["r_nm"] for x in rows]); f = np.array([x["force_kj_mol_nm"] for x in rows]); w = np.array([x["work_kj_mol"] for x in rows])
    fig, axes = plt.subplots(2, 1, figsize=(6.4, 4.4), sharex=True)
    axes[0].plot(r, f, color=PALETTE[0]); axes[0].set_ylabel("Pulling force (kJ/mol/nm)")
    i = int(np.argmax(f)); axes[0].text(r[i], f[i], f" max {f[i]:.0f}", fontsize=7, color="#52514e")
    axes[1].plot(r, w, color=PALETTE[1]); axes[1].set_ylabel("Work (kJ/mol)"); axes[1].set_xlabel("Anchor–ligand COM distance (nm)")
    axes[0].set_title("Steered MD — force and accumulated work (non-equilibrium)", loc="left", fontsize=10)
    return _save(fig, Path(out_base))


def run_umbrella(out_dir: Path | str, *, system_xml, topology_pdb, smd_manifest: dict, ligand_resnames: set[str],
                 spec: UmbrellaSpec, platform_name: str = "CPU", platform_props: dict | None = None,
                 decisions: DecisionLog | None = None, progress_cb=None, n_bootstrap: int = 100) -> dict:
    """Run every planned window (resumable per window), then compute PMF and a binding summary."""
    from openmm import app, unit
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    r_start, r_end = float(smd_manifest["r_start_nm"]), float(smd_manifest["r_end_nm"])
    plan = plan_windows(r_start, r_end, force_constant_kj_mol_nm2=spec.k_umbrella_kj_mol_nm2,
                        temperature_k=spec.temperature_k, target_overlap=spec.target_overlap)
    atomic_write_json(plan.to_dict(), out / "window_plan.json")
    groups = {"ligand": np.asarray(smd_manifest["groups"]["ligand"]), "anchor": np.asarray(smd_manifest["groups"]["anchor"]),
              "reason": "from smd"}
    seeds = {float(k): v for k, v in (smd_manifest.get("seeds") or {}).items()}
    # choose seed for each centre: the SMD seed state with the closest centre, else the SMD final state
    seed_keys = sorted(seeds)
    samples: dict[float, np.ndarray] = {}
    eq_steps = int(round(spec.equilibration_ps * 1000 / spec.timestep_fs))
    prod_steps = int(round(spec.window_length_ps * 1000 / spec.timestep_fs))
    samp_steps = max(1, int(round(spec.sample_interval_ps * 1000 / spec.timestep_fs)))
    for wi, c in enumerate(plan.centers_nm):
        wdir = out / f"window_{wi:03d}"; wdir.mkdir(exist_ok=True)
        done = load_json(wdir / "window_complete.json", {})
        if done.get("status") == "PASS" and Path(done["cv_csv"]).is_file():
            samples[c] = np.loadtxt(done["cv_csv"], delimiter=",", skiprows=1, usecols=1)
            continue
        seed_state = seeds[min(seed_keys, key=lambda k: abs(k - c))] if seed_keys else smd_manifest.get("final_state")
        sim, masses = _make_sim(system_xml, topology_pdb, platform_name, platform_props, timestep_fs=spec.timestep_fs,
                                temperature_k=spec.temperature_k, friction=1.0, seed=spec.seed + wi, groups=groups,
                                k_pull=spec.k_umbrella_kj_mol_nm2, r0=c, anchor_restraint_k=200.0)
        _load_state_positions(sim, seed_state or (Path(smd_manifest["dcd"]).with_name("smd_final.xml")))
        sim.context.setVelocitiesToTemperature(spec.temperature_k * unit.kelvin, spec.seed + wi)
        sim.step(eq_steps)
        cv = []
        t0 = time.monotonic(); done_steps = 0
        while done_steps < prod_steps:
            sim.step(samp_steps); done_steps += samp_steps
            xyz, box = _state_xyz_box(sim)
            cv.append(com_distance(xyz, groups["anchor"], groups["ligand"], box, masses))
            if progress_cb and len(cv) % 50 == 0:
                progress_cb({"stage": "umbrella", "window": wi + 1, "n_windows": len(plan.centers_nm), "center_nm": c,
                             "done_steps": done_steps, "total_steps": prod_steps, "elapsed_s": round(time.monotonic() - t0, 1)})
        cv = np.asarray(cv)
        csv_path = wdir / "cv.csv"
        np.savetxt(csv_path, np.column_stack([np.arange(len(cv)) * spec.sample_interval_ps, cv]), delimiter=",",
                   header="time_ps,cv_nm", comments="")
        sim.saveState(str(wdir / "window_final.xml"))
        atomic_write_json({"status": "PASS", "center_nm": c, "k": spec.k_umbrella_kj_mol_nm2, "n_samples": int(len(cv)),
                           "mean_nm": float(cv.mean()), "sd_nm": float(cv.std()), "cv_csv": str(csv_path), "seed_state": str(seed_state),
                           "created_at": now_iso()}, wdir / "window_complete.json")
        samples[c] = cv
        del sim
    res = pmf_from_windows(samples, force_constant_kj_mol_nm2=spec.k_umbrella_kj_mol_nm2, temperature_k=spec.temperature_k,
                           out_dir=out, n_bootstrap=n_bootstrap)
    summary = binding_summary(res.grid_nm, res.pmf_kj_mol, res.err_kj_mol, r_start, r_end, spec.temperature_k)
    manifest = {"status": "PASS", "plan": plan.to_dict(), "pmf": res.to_dict(), "binding": summary, "spec": asdict(spec),
                "windows": len(plan.centers_nm), "created_at": now_iso()}
    atomic_write_json(manifest, out / "umbrella_manifest.json")
    if decisions:
        decisions.record("sampling.umbrella", "windows", f"{len(plan.centers_nm)} × {spec.window_length_ps} ps, k={spec.k_umbrella_kj_mol_nm2}",
                         plan.notes[-1] if plan.notes else "自動規劃", kind="auto")
        decisions.record("sampling.umbrella", "binding summary", f"ΔPMF = {summary['delta_pmf_kj_mol']:.1f} kJ/mol",
                         summary["interpretation"], kind="auto")
    return manifest


def binding_summary(grid: np.ndarray, pmf: np.ndarray, err: np.ndarray | None, r_start: float, r_end: float, temperature_k: float) -> dict:
    """Well depth from the PMF plus honest caveats (1-D PMF ≠ standard binding free energy without corrections)."""
    m = np.isfinite(pmf)
    g, p = grid[m], pmf[m]
    i_min = int(np.argmin(p))
    bulk = p[g >= g.max() - 0.15]  # last 0.15 nm as "bulk"
    bulk_mean = float(bulk.mean()) if len(bulk) else float(p[-1])
    delta = bulk_mean - float(p[i_min])
    kT = KB * temperature_k
    e_min = float(err[m][i_min]) if err is not None else None
    e_bulk = float(np.mean(err[m][g >= g.max() - 0.15])) if err is not None and len(bulk) else None
    err_delta = math.sqrt((e_min or 0) ** 2 + (e_bulk or 0) ** 2) if err is not None else None
    interp = (f"PMF 井深 {delta:.1f} kJ/mol（≈ {delta / 4.184:.1f} kcal/mol，{delta / kT:.1f} kT）。"
              "這是沿一維 COM 距離的平均力位能，反映配體離開口袋的能量代價；要換算成標準結合自由能還需要體積／取向的標準態校正與充分收斂，"
              "教學 tier 的短視窗只適合比較不同配體的相對強弱。")
    return {"r_min_nm": float(g[i_min]), "pmf_min_kj_mol": float(p[i_min]), "bulk_pmf_kj_mol": bulk_mean,
            "delta_pmf_kj_mol": delta, "delta_pmf_kcal_mol": delta / 4.184, "delta_pmf_kT": delta / kT,
            "err_kj_mol": err_delta, "r_start_nm": r_start, "r_end_nm": r_end, "interpretation": interp}
