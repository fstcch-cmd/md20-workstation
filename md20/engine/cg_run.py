"""Coarse-grained Martini 3 simulation on OpenMM (D-86).

Same physics as the martini_openmm tutorial (tutorial/run.py): Langevin 310 K, friction 10 ps⁻¹, ε_r 15, 1.1 nm
cut-off, 20 fs.  Stages:
  minimise (5000 iterations)
  nvt      0.2 ns at 10 fs (first contacts after insane are close; the tutorial uses 20 fs directly)
  npt      equil_ns at 20 fs; membranes: MonteCarloMembraneBarostat (XY isotropic, Z free, zero surface tension),
           water: MonteCarloBarostat; 1 bar
  production  production_ns at 20 fs, saved every save_ps, in chunks of chunk_ns
After every chunk the state (XML, platform independent) and progress.json are written, so a run that is paused,
closed or moved to another computer continues from the last chunk.  `should_pause()` is checked between chunks.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from ..build import martini as M

NVT_NS = 0.2
NVT_DT_FS = 10.0


def _write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(path)


def _simulation(man: dict, *, platform_name: str, properties: dict | None, temperature_k: float, dt_fs: float,
                barostat: str | None, seed: int):
    import martini_openmm as martini
    import openmm as mm
    from openmm import app, unit
    conf = app.GromacsGroFile(man["gro"])
    top = martini.MartiniTopFile(man["top"], periodicBoxVectors=conf.getPeriodicBoxVectors(),
                                 epsilon_r=M.CG_EPSILON_R, includeDir=man["workdir"])
    system = top.create_system(nonbonded_cutoff=M.CG_CUTOFF_NM * unit.nanometer)
    T = temperature_k * unit.kelvin
    if barostat == "membrane":
        system.addForce(mm.MonteCarloMembraneBarostat(1.0 * unit.bar, 0.0 * unit.bar * unit.nanometer, T,
                                                      mm.MonteCarloMembraneBarostat.XYIsotropic,
                                                      mm.MonteCarloMembraneBarostat.ZFree, 25))
    elif barostat == "isotropic":
        system.addForce(mm.MonteCarloBarostat(1.0 * unit.bar, T, 25))
    integ = mm.LangevinIntegrator(T, M.CG_FRICTION_PER_PS / unit.picosecond, dt_fs * unit.femtosecond)
    integ.setRandomNumberSeed(seed)
    plat = mm.Platform.getPlatformByName(platform_name)
    sim = app.Simulation(top.topology, system, integ, plat, properties or {})
    return sim, conf


def run_cg(man: dict, run_dir: Path | str, *, platform_name: str = "CPU", properties: dict | None = None,
           temperature_k: float = 310.0, equil_ns: float = 1.0, production_ns: float = 100.0, save_ps: float = 200.0,
           chunk_ns: float = 10.0, seed: int = 1, should_pause=None, progress_cb=None,
           nvt_ns: float = NVT_NS) -> dict:
    """Run (or continue) one CG system.  Returns {"status": COMPLETE | PAUSED | FAILED, ...}."""
    from openmm import app, unit
    rd = Path(run_dir)
    rd.mkdir(parents=True, exist_ok=True)
    prog_path = rd / "progress.json"
    prog = json.loads(prog_path.read_text(encoding="utf-8")) if prog_path.is_file() else {}
    baro = "membrane" if man.get("membrane") else "isotropic"
    plan = {"temperature_k": temperature_k, "equil_ns": equil_ns, "production_ns": production_ns, "save_ps": save_ps,
            "chunk_ns": chunk_ns, "barostat": baro, "timestep_fs": M.CG_TIMESTEP_FS, "nvt_ns": nvt_ns,
            "nvt_timestep_fs": NVT_DT_FS, "platform": platform_name}
    prog.setdefault("stage", "minimise")
    prog.setdefault("production_done_ns", 0.0)
    prog["plan"] = plan
    started = time.time()

    def beat(stage, done, total):
        if progress_cb:
            progress_cb({"status": "RUNNING", "stage": f"cg_{stage}", "completed_local_steps": int(done),
                         "total_steps": int(total), "heartbeat_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                         "elapsed_s": round(time.time() - started, 1)})

    state_xml = rd / "state.xml"
    if prog["stage"] in ("minimise", "nvt"):
        sim, conf = _simulation(man, platform_name=platform_name, properties=properties, temperature_k=temperature_k,
                                dt_fs=NVT_DT_FS, barostat=None, seed=seed)
        sim.context.setPositions(conf.getPositions())
        sim.minimizeEnergy(maxIterations=5000, tolerance=1.0)
        e = sim.context.getState(getEnergy=True).getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
        prog["minimised_kj_mol"] = e
        if not (e == e and abs(e) < 1e12):          # NaN or overflow: overlapping beads that minimisation cannot fix
            _write(prog_path, prog)
            return {"status": "FAILED", "progress": prog, "run_dir": str(rd),
                    "reason": f"最小化後能量不是有限值（{e}），珠子可能重疊；請重建系統。"}
        sim.context.setVelocitiesToTemperature(temperature_k * unit.kelvin, seed)
        n = int(round(nvt_ns * 1e6 / NVT_DT_FS))
        sim.step(n)
        beat("nvt", n, n)
        sim.saveState(str(state_xml))
        del sim
        prog["stage"] = "npt"
        _write(prog_path, prog)
    if prog["stage"] == "npt":
        sim, _ = _simulation(man, platform_name=platform_name, properties=properties, temperature_k=temperature_k,
                             dt_fs=M.CG_TIMESTEP_FS, barostat=baro, seed=seed + 1)
        sim.loadState(str(state_xml))
        n = int(round(equil_ns * 1e6 / M.CG_TIMESTEP_FS))
        sim.step(n)
        beat("npt", n, n)
        sim.saveState(str(state_xml))
        st = sim.context.getState(getEnergy=True)
        v = st.getPeriodicBoxVectors(asNumpy=True).value_in_unit(unit.nanometer)
        prog["equilibrated_box_nm"] = [float(v[0][0]), float(v[1][1]), float(v[2][2])]
        del sim, st
        prog["stage"] = "production"
        _write(prog_path, prog)
    if prog["stage"] == "production":
        sim, _ = _simulation(man, platform_name=platform_name, properties=properties, temperature_k=temperature_k,
                             dt_fs=M.CG_TIMESTEP_FS, barostat=baro, seed=seed + 2 + int(prog["production_done_ns"] * 10))
        sim.loadState(str(state_xml))
        every = max(1, int(round(save_ps * 1000 / M.CG_TIMESTEP_FS)))
        dcd = rd / "production.dcd"
        sim.reporters.append(app.DCDReporter(str(dcd), every, append=dcd.is_file()))
        sim.reporters.append(app.StateDataReporter(str(rd / "production.csv"), every, step=True, time=True,
                                                   potentialEnergy=True, temperature=True, volume=True,
                                                   append=(rd / "production.csv").is_file()))
        total = int(round(production_ns * 1e6 / M.CG_TIMESTEP_FS))
        chunk = max(every, int(round(chunk_ns * 1e6 / M.CG_TIMESTEP_FS)) // every * every)
        done = int(round(prog["production_done_ns"] * 1e6 / M.CG_TIMESTEP_FS))
        while done < total:
            n = min(chunk, total - done)
            t0 = time.time()
            sim.step(n)
            done += n
            sim.saveState(str(state_xml))
            prog["production_done_ns"] = done * M.CG_TIMESTEP_FS / 1e6
            prog["ns_per_day"] = round((n * M.CG_TIMESTEP_FS / 1e6) / max(1e-6, time.time() - t0) * 86400, 1)
            _write(prog_path, prog)
            beat("production", done, total)
            if done < total and callable(should_pause) and should_pause():
                sim.reporters.clear()            # closes the DCD and CSV files before the context is released
                del sim
                return {"status": "PAUSED", "progress": prog, "run_dir": str(rd)}
        sim.reporters.clear()
        del sim
        prog["stage"] = "done"
        _write(prog_path, prog)
    return {"status": "COMPLETE", "progress": prog, "run_dir": str(rd), "dcd": str(rd / "production.dcd")}
