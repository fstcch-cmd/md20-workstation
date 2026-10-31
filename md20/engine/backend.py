"""Simulation backends.

`Backend` is the minimal surface the chunk engine needs.  `OpenMMBackend`
wraps a real OpenMM Simulation; `FakeBackend` produces synthetic but
realistically shaped StateData logs so the resume / watchdog / acceptance /
plotting logic can be unit-tested on any machine without OpenMM.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Protocol as _Protocol


@dataclass
class StateSummary:
    step: int
    time_ps: float
    potential_kj_mol: float
    kinetic_kj_mol: float
    temperature_k: float
    volume_nm3: float
    density_g_ml: float | None

    def finite(self) -> bool:
        vals = [self.potential_kj_mol, self.kinetic_kj_mol, self.temperature_k, self.volume_nm3]
        return all(isinstance(v, (int, float)) and math.isfinite(v) for v in vals) and self.volume_nm3 > 0

    def to_dict(self) -> dict:
        return asdict(self)


class Backend(_Protocol):
    """What the chunk engine calls.  Keep this narrow."""
    n_atoms: int
    platform_name: str

    def set_timestep_fs(self, dt: float) -> None: ...
    def set_temperature(self, kelvin: float) -> None: ...
    def set_pressure(self, bar: float, kelvin: float) -> None: ...
    def set_global_parameter(self, name: str, value: float) -> bool: ...
    def initialize(self, state_path: Path | None, temperature_k: float | None, seed: int,
                   regenerate_velocities: bool) -> None: ...
    def minimize(self, tolerance_kj_mol_nm: float, max_iterations: int) -> None: ...
    def start_reporters(self, log_path: Path, dcd_path: Path | None, report_steps: int, dcd_steps: int,
                        total_steps: int) -> None: ...
    def stop_reporters(self) -> None: ...
    def step(self, n: int) -> None: ...
    def summary(self) -> StateSummary: ...
    def current_step(self) -> int: ...
    def save_state(self, path: Path) -> None: ...
    def save_checkpoint(self, path: Path) -> None: ...
    def write_pdb(self, path: Path) -> None: ...
    def close(self) -> None: ...


def apply_hmr(system, topology, h_mass_amu: float = 3.0) -> int:
    """Hydrogen mass repartitioning in place: H → h_mass_amu, bonded heavy atom loses the difference.
    Water is skipped (rigid). Returns the number of hydrogens changed."""
    from openmm import unit
    bonds: dict[int, list[int]] = {}
    for a, b in topology.bonds():
        bonds.setdefault(a.index, []).append(b.index)
        bonds.setdefault(b.index, []).append(a.index)
    atoms = list(topology.atoms())
    moved = 0
    for atom in atoms:
        if atom.element is None or atom.element.symbol != "H" or atom.residue.name in {"HOH", "WAT", "TIP3", "SOL"}:
            continue
        heavy = [j for j in bonds.get(atom.index, []) if atoms[j].element is not None and atoms[j].element.symbol != "H"]
        if not heavy:
            continue
        cur = system.getParticleMass(atom.index).value_in_unit(unit.amu)
        delta = h_mass_amu - cur
        if abs(delta) < 1e-6:
            continue
        hm = system.getParticleMass(heavy[0]).value_in_unit(unit.amu)
        system.setParticleMass(atom.index, h_mass_amu * unit.amu)
        system.setParticleMass(heavy[0], (hm - delta) * unit.amu)
        moved += 1
    return moved


# --------------------------------------------------------------------------- OpenMM
class OpenMMBackend:
    """Real backend.  Construct from a serialized System XML + topology PDB.

    `hmr=True` repartitions hydrogen masses (3 amu) so 4 fs is stable; the
    repartitioning is applied to the System *before* the Context is created
    and recorded in `info` so the decision log can cite it.
    """

    def __init__(self, system_xml: Path | str, topology_pdb: Path | str, *, platform_name: str,
                 platform_properties: dict | None = None, timestep_fs: float = 2.0,
                 temperature_k: float = 300.0, friction_per_ps: float = 1.0, ensemble: str = "NVT",
                 pressure_bar: float = 1.0, barostat_interval_steps: int = 25, hmr: bool = False,
                 constraint_tolerance: float = 1e-6, seed: int = 0):
        import openmm as mm
        from openmm import app, unit, XmlSerializer
        self.mm, self.app, self.unit = mm, app, unit
        self.system = XmlSerializer.deserialize(Path(system_xml).read_text(encoding="utf-8"))
        pdb = app.PDBFile(str(topology_pdb))
        self.topology, self._positions = pdb.topology, pdb.positions
        self.info: dict = {"hmr": False}
        if hmr:
            self._apply_hmr()
        self._configure_barostat(ensemble.upper() == "NPT", pressure_bar, temperature_k, barostat_interval_steps)
        self.integrator = mm.LangevinMiddleIntegrator(temperature_k * unit.kelvin, friction_per_ps / unit.picosecond,
                                                      timestep_fs * unit.femtoseconds)
        self.integrator.setConstraintTolerance(constraint_tolerance)
        self.integrator.setRandomNumberSeed(int(seed))
        platform = mm.Platform.getPlatformByName(platform_name)
        self.sim = app.Simulation(self.topology, self.system, self.integrator, platform, platform_properties or {})
        self.platform_name = self.sim.context.getPlatform().getName()
        self.n_atoms = self.system.getNumParticles()
        self._ensemble = ensemble.upper()

    # -- setup helpers
    def _apply_hmr(self, h_mass_amu: float = 3.0):
        moved = apply_hmr(self.system, self.topology, h_mass_amu)
        self.info.update({"hmr": True, "hmr_hydrogens_repartitioned": moved, "hmr_h_mass_amu": h_mass_amu})

    def _barostats(self):
        mm = self.mm
        return [self.system.getForce(i) for i in range(self.system.getNumForces())
                if isinstance(self.system.getForce(i), mm.MonteCarloBarostat)]

    def _configure_barostat(self, enabled: bool, pressure_bar: float, temperature_k: float, freq: int):
        mm, unit = self.mm, self.unit
        bars = self._barostats()
        if len(bars) > 1:
            raise RuntimeError("System 含多個 MonteCarloBarostat；拒絕猜測。")
        if not bars:
            if not enabled:
                return
            bar = mm.MonteCarloBarostat(pressure_bar * unit.bar, temperature_k * unit.kelvin, int(freq))
            self.system.addForce(bar)
            bars = [bar]
        bar = bars[0]
        bar.setDefaultPressure(pressure_bar * unit.bar)
        bar.setDefaultTemperature(temperature_k * unit.kelvin)
        bar.setFrequency(int(freq) if enabled else 0)

    # -- Backend API
    def set_timestep_fs(self, dt: float) -> None:
        self.integrator.setStepSize(dt * self.unit.femtoseconds)

    def set_temperature(self, kelvin: float) -> None:
        self.integrator.setTemperature(kelvin * self.unit.kelvin)
        if self._ensemble == "NPT":
            try:
                self.sim.context.setParameter(self.mm.MonteCarloBarostat.Temperature(), kelvin)
            except Exception:  # noqa: BLE001
                pass

    def set_pressure(self, bar: float, kelvin: float) -> None:
        if self._ensemble == "NPT":
            self.sim.context.setParameter(self.mm.MonteCarloBarostat.Pressure(), bar)
            self.sim.context.setParameter(self.mm.MonteCarloBarostat.Temperature(), kelvin)

    def set_global_parameter(self, name: str, value: float) -> bool:
        if name in self.sim.context.getParameters():
            self.sim.context.setParameter(name, float(value))
            return True
        return False

    def initialize(self, state_path, temperature_k, seed, regenerate_velocities) -> None:
        if state_path:
            self.sim.loadState(str(state_path))
        else:
            self.sim.context.setPositions(self._positions)
            self.sim.context.applyConstraints(self.integrator.getConstraintTolerance())
        if temperature_k is not None and (not state_path or regenerate_velocities):
            self.sim.context.setVelocitiesToTemperature(temperature_k * self.unit.kelvin, int(seed))

    def minimize(self, tolerance_kj_mol_nm: float, max_iterations: int) -> None:
        self.sim.minimizeEnergy(tolerance=tolerance_kj_mol_nm * self.unit.kilojoule_per_mole / self.unit.nanometer,
                                maxIterations=int(max_iterations))

    def start_reporters(self, log_path, dcd_path, report_steps, dcd_steps, total_steps) -> None:
        app = self.app
        self.sim.reporters.append(app.StateDataReporter(str(log_path), int(report_steps), step=True, time=True,
                                  potentialEnergy=True, kineticEnergy=True, totalEnergy=True, temperature=True,
                                  volume=True, density=True, speed=True, totalSteps=int(total_steps), separator="\t"))
        if dcd_path is not None:
            self.sim.reporters.append(app.DCDReporter(str(dcd_path), int(dcd_steps), enforcePeriodicBox=True))

    def stop_reporters(self) -> None:
        for r in self.sim.reporters:
            close = getattr(r, "close", None) or getattr(getattr(r, "_out", None), "close", None)
            try:
                if close:
                    close()
            except Exception:  # noqa: BLE001
                pass
        self.sim.reporters.clear()

    def step(self, n: int) -> None:
        self.sim.step(int(n))

    def summary(self) -> StateSummary:
        unit = self.unit
        st = self.sim.context.getState(getEnergy=True)
        pe = st.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
        ke = st.getKineticEnergy().value_in_unit(unit.kilojoule_per_mole)
        vol = st.getPeriodicBoxVolume().value_in_unit(unit.nanometer ** 3)
        dof = 3 * self.n_atoms - self.system.getNumConstraints() - 3
        temp = 2 * ke * 1000 / (dof * 8.314462618) if dof > 0 else float("nan")
        mass_amu = sum(self.system.getParticleMass(i).value_in_unit(unit.amu) for i in range(self.n_atoms))
        density = mass_amu * 1.66053906660e-24 / (vol * 1e-21) if vol > 0 else None
        return StateSummary(step=self.current_step(), time_ps=st.getTime().value_in_unit(unit.picosecond),
                            potential_kj_mol=pe, kinetic_kj_mol=ke, temperature_k=temp, volume_nm3=vol,
                            density_g_ml=density)

    def current_step(self) -> int:
        try:
            return int(self.sim.currentStep)
        except Exception:  # noqa: BLE001
            return int(self.sim.context.getState().getStepCount())

    def save_state(self, path: Path) -> None:
        self.sim.saveState(str(path))

    def save_checkpoint(self, path: Path) -> None:
        self.sim.saveCheckpoint(str(path))

    def write_pdb(self, path: Path) -> None:
        st = self.sim.context.getState(getPositions=True, enforcePeriodicBox=True)
        with open(path, "w", encoding="utf-8") as fh:
            self.app.PDBFile.writeFile(self.sim.topology, st.getPositions(), fh, keepIds=True)

    def close(self) -> None:
        self.stop_reporters()
        del self.sim


# --------------------------------------------------------------------------- Fake
class FakeBackend:
    """Deterministic synthetic backend for tests and GUI development.

    Parameters let tests inject failures:
      nan_at_step   : summary() reports NaN once the absolute step passes this
      explode_scale : how fast temperature runs away after nan_at_step (0 = clean NaN)
    """

    def __init__(self, *, n_atoms: int = 24000, timestep_fs: float = 2.0, temperature_k: float = 300.0,
                 ensemble: str = "NVT", pressure_bar: float = 1.0, nan_at_step: int | None = None,
                 seed: int = 0, speed_steps_per_s: float = 2e5, **_ignored):
        self.n_atoms = n_atoms
        self.platform_name = "Fake"
        self._dt = timestep_fs
        self._target_T = temperature_k
        self._T = temperature_k
        self._ensemble = ensemble.upper()
        self._P = pressure_bar
        self._step = 0
        self._time = 0.0
        self._pe = -3.2e5
        self._vol = 240.0
        self._rng = random.Random(seed)
        self._nan_at = nan_at_step
        self._params: dict[str, float] = {"msw_restraint_scale": 1.0}
        self._log = None
        self._report_steps = 1000
        self._dcd = None
        self._dcd_steps = 1000
        self._next_report = None
        self.info = {"hmr": False}
        self.speed = speed_steps_per_s
        self.timestep_history: list[float] = [timestep_fs]

    # Backend API
    def set_timestep_fs(self, dt: float) -> None:
        self._dt = dt
        self.timestep_history.append(dt)

    def set_temperature(self, kelvin: float) -> None:
        self._target_T = kelvin

    def set_pressure(self, bar: float, kelvin: float) -> None:
        self._P = bar; self._target_T = kelvin

    def set_global_parameter(self, name: str, value: float) -> bool:
        if name in self._params:
            self._params[name] = value
            return True
        return False

    def initialize(self, state_path, temperature_k, seed, regenerate_velocities) -> None:
        if state_path:
            import json
            d = json.loads(Path(state_path).read_text(encoding="utf-8"))
            self._step, self._time, self._pe, self._vol, self._T = d["step"], d["time"], d["pe"], d["vol"], d["T"]
        else:
            self._step, self._time = 0, 0.0
        if temperature_k is not None and (not state_path or regenerate_velocities):
            self._T = temperature_k

    def minimize(self, tolerance_kj_mol_nm: float, max_iterations: int) -> None:
        self._pe -= 5.0e4

    def start_reporters(self, log_path, dcd_path, report_steps, dcd_steps, total_steps) -> None:
        self._log = open(log_path, "w", encoding="utf-8")
        self._log.write('#"Step"\t"Time (ps)"\t"Potential Energy (kJ/mole)"\t"Kinetic Energy (kJ/mole)"\t'
                        '"Total Energy (kJ/mole)"\t"Temperature (K)"\t"Box Volume (nm^3)"\t"Density (g/mL)"\t"Speed (ns/day)"\n')
        self._report_steps = int(report_steps)
        self._next_report = self._step + self._report_steps
        if dcd_path is not None:
            self._dcd = open(dcd_path, "wb"); self._dcd_steps = int(dcd_steps); self._next_dcd = self._step + self._dcd_steps
            self._dcd.write(b"FAKEDCD\x00")

    def stop_reporters(self) -> None:
        for fh in (self._log, self._dcd):
            if fh:
                fh.close()
        self._log = self._dcd = None

    def _advance(self, n: int):
        self._step += n
        self._time += n * self._dt / 1000.0
        # relax toward target temperature; small noise
        self._T += (self._target_T - self._T) * min(1.0, n / 300.0) + self._rng.gauss(0, 1.5)
        self._pe += self._rng.gauss(0, 150.0)
        if self._ensemble == "NPT":
            self._vol += (235.0 - self._vol) * min(1.0, n / 5000.0) + self._rng.gauss(0, 0.05)
        if self._nan_at is not None and self._step >= self._nan_at:
            self._T = float("nan"); self._pe = float("nan")

    def step(self, n: int) -> None:
        remaining = n
        while remaining > 0:
            if self._log is not None and self._next_report is not None:
                take = min(remaining, max(1, self._next_report - self._step))
            else:
                take = remaining
            self._advance(take)
            remaining -= take
            if self._log is not None and self._step >= (self._next_report or 0):
                s = self.summary()
                ke = s.kinetic_kj_mol
                self._log.write(f"{s.step}\t{s.time_ps:.3f}\t{s.potential_kj_mol:.2f}\t{ke:.2f}\t{s.potential_kj_mol + ke:.2f}\t"
                                f"{s.temperature_k:.2f}\t{s.volume_nm3:.3f}\t{s.density_g_ml:.4f}\t{self.speed * self._dt * 86.4 / 1e6:.1f}\n")
                self._log.flush()
                self._next_report = self._step + self._report_steps
            if self._dcd is not None and self._step >= self._next_dcd:
                self._dcd.write(b"F" * 64); self._next_dcd = self._step + self._dcd_steps

    def summary(self) -> StateSummary:
        ke = 0.5 * 3 * self.n_atoms * 8.314462618e-3 * self._T if math.isfinite(self._T) else float("nan")
        dens = self.n_atoms * 6.0 * 1.66053906660e-24 / (self._vol * 1e-21)
        return StateSummary(step=self._step, time_ps=self._time, potential_kj_mol=self._pe, kinetic_kj_mol=ke,
                            temperature_k=self._T, volume_nm3=self._vol, density_g_ml=dens)

    def current_step(self) -> int:
        return self._step

    def save_state(self, path: Path) -> None:
        import json
        Path(path).write_text(json.dumps({"step": self._step, "time": self._time, "pe": self._pe,
                                          "vol": self._vol, "T": self._T, "fake": True}), encoding="utf-8")

    def save_checkpoint(self, path: Path) -> None:
        Path(path).write_bytes(b"FAKECHK" + str(self._step).encode())

    def write_pdb(self, path: Path) -> None:
        Path(path).write_text("REMARK fake\nEND\n", encoding="utf-8")

    def close(self) -> None:
        self.stop_reporters()
