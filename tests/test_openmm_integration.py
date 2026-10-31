"""Real-OpenMM integration tests.  Skipped automatically when openmm is not installed.

Run on a machine with the `md` extra installed:  pytest tests/test_openmm_integration.py -v
No input files are needed: a small TIP3P water box is built in code.
"""
from pathlib import Path

import pytest

openmm = pytest.importorskip("openmm")

from md20.env import choose_platform, run_doctor
from md20.engine import OpenMMBackend, make_protocol, run_protocol
from md20.util import DecisionLog, load_json


@pytest.fixture(scope="module")
def water_box(tmp_path_factory):
    from openmm import app, unit, XmlSerializer
    d = tmp_path_factory.mktemp("box")
    ff = app.ForceField("amber14/tip3p.xml")
    top = app.Topology()
    modeller = app.Modeller(top, [])
    modeller.addSolvent(ff, model="tip3p", boxSize=(2.2, 2.2, 2.2) * unit.nanometer)
    system = ff.createSystem(modeller.topology, nonbondedMethod=app.PME, nonbondedCutoff=0.9 * unit.nanometer,
                             constraints=app.HBonds, rigidWater=True)
    (d / "system.xml").write_text(XmlSerializer.serialize(system))
    with open(d / "topology.pdb", "w") as fh:
        app.PDBFile.writeFile(modeller.topology, modeller.positions, fh)
    return d


def test_platform_ladder_returns_working_platform():
    choice = choose_platform(probe_steps=50)
    assert choice.name in {"CUDA", "HIP", "OpenCL", "CPU", "Reference"}
    assert choice.probe_seconds is not None


def test_doctor_runs(tmp_path):
    rep = run_doctor(do_benchmark=True, benchmark_seconds=2.0, save=False)
    assert rep.platform, rep.to_markdown()
    assert rep.benchmark and rep.benchmark.get("ns_per_day", 0) > 0, f"benchmark failed: {rep.benchmark}\n{rep.to_markdown()}"


def test_backend_hmr_and_summary(water_box):
    choice = choose_platform(probe_steps=20)
    b = OpenMMBackend(water_box / "system.xml", water_box / "topology.pdb", platform_name=choice.name,
                      platform_properties=choice.properties, hmr=True, timestep_fs=4.0)
    assert b.info["hmr"] is True  # water is rigid → no repartitioning counted, but flag is set
    b.initialize(None, 300.0, 1, True)
    b.minimize(10.0, 100)
    s = b.summary()
    assert s.finite() and s.volume_nm3 > 0
    b.close()


def test_full_protocol_real(water_box, tmp_path):
    choice = choose_platform(probe_steps=20)
    proto = make_protocol("classroom")
    for s in proto.stages:
        if s.ensemble != "MIN":
            # 10 ps per stage: short enough for a laptop test, long enough for the 50→300 K ramp (6 ps) to be physical
            s.length_ps = 10.0; s.checkpoint_interval_ps = 5.0; s.report_interval_ps = 0.1; s.trajectory_interval_ps = 1.0
        s.accept = {}  # a 10 ps box will not meet density gates; this test checks mechanics only

    def make(spec, dt):
        return OpenMMBackend(water_box / "system.xml", water_box / "topology.pdb", platform_name=choice.name,
                             platform_properties=choice.properties, timestep_fs=dt, temperature_k=spec.temperature_k,
                             ensemble=spec.ensemble, pressure_bar=spec.pressure_bar, hmr=proto.hmr, seed=spec.seed)
    dec = DecisionLog(tmp_path / "d.jsonl")
    st = run_protocol(tmp_path / "run", proto, make, identity={"case_id": "t"}, decisions=dec, max_extensions=0)
    assert st["status"] == "COMPLETE"
    comp = load_json(tmp_path / "run" / "stages" / "production" / "production_complete.json")
    assert comp["status"] == "PASS" and comp["platform"] == choice.name
    assert Path(comp["result"]["dcd_paths"][0]).stat().st_size > 0
    assert (tmp_path / "run" / "figures" / "production_timeseries.png").exists()
