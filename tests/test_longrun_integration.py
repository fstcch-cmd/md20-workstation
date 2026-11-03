"""Real-engine checks for long runs and the Martini 3 path.  Skipped without OpenMM (and, for Martini, without
martini_openmm plus a prepared system in MD20_CG_TEST_DIR); run in CI openmm-stack and on the laptop."""
import os
from pathlib import Path

import pytest

openmm = pytest.importorskip("openmm")

from md20.engine import OpenMMBackend                       # noqa: E402
from md20.engine.chunks import run_stage                    # noqa: E402
from md20.engine.longrun import dcd_frame_bytes             # noqa: E402
from md20.engine.protocol import StageSpec                  # noqa: E402
from md20.util import load_json                             # noqa: E402


@pytest.fixture(scope="module")
def box_with_solute(tmp_path_factory):
    """TIP3P box in which two waters are renamed LIG in the topology PDB: 6 'solute' atoms for the subset rule."""
    from openmm import app, unit, XmlSerializer
    d = tmp_path_factory.mktemp("lrbox")
    ff = app.ForceField("amber14/tip3p.xml")
    modeller = app.Modeller(app.Topology(), [])
    modeller.addSolvent(ff, model="tip3p", boxSize=(2.0, 2.0, 2.0) * unit.nanometer)
    system = ff.createSystem(modeller.topology, nonbondedMethod=app.PME, nonbondedCutoff=0.9 * unit.nanometer,
                             constraints=app.HBonds, rigidWater=True)
    (d / "system.xml").write_text(XmlSerializer.serialize(system))
    for r in list(modeller.topology.residues())[:2]:
        r.name = "LIG"
    with open(d / "topology.pdb", "w") as fh:
        app.PDBFile.writeFile(modeller.topology, modeller.positions, fh)
    return d


def test_solute_only_dcd_and_pruned_chunks(box_with_solute, tmp_path):
    from md20.env import choose_platform
    choice = choose_platform(probe_steps=20)
    spec = StageSpec(name="production", ensemble="NVT", length_ps=2.0, timestep_fs=2.0, report_interval_ps=0.1,
                     trajectory_interval_ps=0.2, checkpoint_interval_ps=0.4, trajectory_atoms="solute",
                     keep_chunk_states=2)

    def make(s, dt):
        return OpenMMBackend(box_with_solute / "system.xml", box_with_solute / "topology.pdb", platform_name=choice.name,
                             platform_properties=choice.properties, timestep_fs=dt, temperature_k=s.temperature_k,
                             ensemble=s.ensemble, seed=s.seed, trajectory_atoms=s.trajectory_atoms)
    sdir = tmp_path / "run" / "stages" / "production"
    res = run_stage(sdir, spec, make, identity={"case_id": "lr"}, initial_state=None)
    comp = load_json(sdir / "production_complete.json")
    info = comp["backend_info"]
    assert info["dcd_atoms"] == "solute" and info["dcd_atom_count"] == 6, info
    assert sorted(p.name for p in sdir.glob("chunk_*.xml")) == ["chunk_00004.xml", "chunk_00005.xml"]
    frames = 0
    for p in res.dcd_paths:
        size = Path(p).stat().st_size
        assert (size - 276) % dcd_frame_bytes(6) == 0, (p, size)      # header + whole 6-atom frames
        frames += (size - 276) // dcd_frame_bytes(6)
    assert frames == 10
    md = pytest.importorskip("mdtraj")
    from md20.analysis.stream import production_topology, iter_chunks, StreamingMetrics
    top, subset = production_topology(tmp_path / "run", box_with_solute / "topology.pdb")
    assert len(subset) == 6
    t = md.load(res.dcd_paths, top=top)
    assert t.n_atoms == 6 and t.n_frames == 10
    sm = StreamingMetrics(rmsf_atoms=list(range(6)))
    for ch in iter_chunks(res.dcd_paths, top, chunk=3):
        sm.update(ch.xyz, ch.time)
    assert sm.result()["n_frames"] == 10 and len(sm.result()["rmsf_A"]) == 6


def test_martini_openmm_builds_a_system(tmp_path):
    """Needs `md20 setup-cg` and a prepared Martini 3 system (system.gro, system.top and its itp files) in
    MD20_CG_TEST_DIR, e.g. a copy of martini_openmm/tests/popc_m3/openmm.  Not provisioned in CI yet."""
    pytest.importorskip("martini_openmm")
    src = os.environ.get("MD20_CG_TEST_DIR")
    if not src or not (Path(src) / "system.top").is_file():
        pytest.skip("MD20_CG_TEST_DIR with system.gro and system.top is not set")
    from md20.build.martini import build_openmm_system
    out = build_openmm_system(Path(src) / "system.gro", Path(src) / "system.top", tmp_path / "system.xml",
                              include_dir=src)
    assert out["n_particles"] > 0 and (tmp_path / "system.xml").stat().st_size > 0
