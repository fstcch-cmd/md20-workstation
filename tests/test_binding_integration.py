"""SMD → umbrella → PMF on Na+/Cl- in TIP3P (real OpenMM, CPU).  Textbook result: contact-ion-pair minimum ≈ 0.28 nm."""
from pathlib import Path

import numpy as np
import pytest

openmm = pytest.importorskip("openmm")

from md20.sampling.binding import run_binding, BindingConfig


def _nacl(d: Path):
    import openmm as mm
    from openmm import app, unit, XmlSerializer
    ff = app.ForceField("amber14-all.xml", "amber14/tip3p.xml")
    top = app.Topology(); ch = top.addChain()
    r1 = top.addResidue("NA", ch); top.addAtom("NA", app.Element.getBySymbol("Na"), r1)
    r2 = top.addResidue("CL", ch); top.addAtom("CL", app.Element.getBySymbol("Cl"), r2)
    mod = app.Modeller(top, [mm.Vec3(1.3, 1.3, 1.3), mm.Vec3(1.58, 1.3, 1.3)] * unit.nanometer)
    mod.addSolvent(ff, model="tip3p", boxSize=mm.Vec3(2.6, 2.6, 2.6) * unit.nanometer)
    system = ff.createSystem(mod.topology, nonbondedMethod=app.PME, nonbondedCutoff=1.0 * unit.nanometer, constraints=app.HBonds)
    (d / "system.xml").write_text(XmlSerializer.serialize(system))
    with open(d / "topology.pdb", "w") as fh:
        app.PDBFile.writeFile(mod.topology, mod.positions, fh)
    return d / "system.xml", d / "topology.pdb"


def test_nacl_pmf(tmp_path):
    sx, tp = _nacl(tmp_path)
    cfg = BindingConfig(pull_distance_nm=0.55, pull_velocity_nm_per_ps=0.02, k_pull=2000, k_umbrella=3000,
                        target_overlap=0.3, window_equil_ps=2.0, window_prod_ps=20.0, sample_every_steps=20)
    res = run_binding(sx, tp, None, tmp_path / "bind", ligand_indices=[1], anchor_indices=[0], config=cfg,
                      platform_name="CPU")
    assert res.status == "PASS"
    assert len(res.windows) >= 6
    assert 0.22 < res.pmf["r_min_nm"] < 0.38, res.pmf
    assert res.delta_pmf_kj_mol is not None and np.isfinite(res.delta_pmf_kj_mol) and res.delta_pmf_kj_mol > 0
    assert res.dG_standard_kj_mol is not None
    for k in ("pmf", "histograms", "smd"):
        assert Path(res.figures[k]["png"]).is_file()
    # resumability: second call reuses SMD and all windows (no new sampling)
    res2 = run_binding(sx, tp, None, tmp_path / "bind", ligand_indices=[1], anchor_indices=[0], config=cfg, platform_name="CPU")
    assert res2.delta_pmf_kj_mol == res.delta_pmf_kj_mol
