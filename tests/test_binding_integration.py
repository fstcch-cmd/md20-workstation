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
    cfg = BindingConfig(pull_distance_nm=0.45, pull_velocity_nm_per_ps=0.02, k_pull=2000, k_umbrella=2500, box_margin_nm=0.3,
                        target_overlap=0.35, window_equil_ps=2.0, window_prod_ps=25.0, sample_every_steps=20)
    res = run_binding(sx, tp, None, tmp_path / "bind", ligand_indices=[1], anchor_indices=[0], config=cfg,
                      platform_name="CPU")
    assert res.status == "PASS"
    assert len(res.windows) >= 6
    assert res.pmf["jacobian_corrected"]
    g, w = np.asarray(res.pmf["grid_nm"]), np.asarray(res.pmf["pmf_radial_kj_mol"])
    cip = w[(g > 0.24) & (g < 0.32)]
    barrier = w[(g > 0.33) & (g < 0.42)]
    assert len(cip) and len(barrier)
    # contact-ion-pair well separated from the solvent-separated pair by a barrier (TIP3P/JC: ~3–6 kJ/mol)
    assert barrier.max() > cip.min() + 1.0, (cip.min(), barrier.max())
    # (the global minimum may be CIP, SSIP or bulk: in TIP3P/JC the NaCl wells are within sampling noise of each other)
    assert res.pmf["quality"]["graph_connected"], "windows should be connected after automatic refinement"
    assert res.delta_pmf_kj_mol is not None and np.isfinite(res.delta_pmf_kj_mol) and res.delta_pmf_kj_mol > 0
    assert (res.dG_standard_kj_mol is not None) or res.pmf.get("dG_withheld"), "ΔG° missing without a stated reason"
    assert "first_half_dpmf" in res.pmf["half_split"], res.pmf["half_split"]
    assert res.delta_pmf_err_kj_mol is None or (np.isfinite(res.delta_pmf_err_kj_mol) and res.delta_pmf_err_kj_mol >= 0)
    assert res.dG_err_kj_mol is None or (np.isfinite(res.dG_err_kj_mol) and res.dG_err_kj_mol >= 0)
    assert "骨架" in res.caveats[0]
    for k in ("pmf", "histograms", "smd"):
        assert Path(res.figures[k]["png"]).is_file()
    # resumability: second call reuses SMD and all windows (no new sampling)
    res2 = run_binding(sx, tp, None, tmp_path / "bind", ligand_indices=[1], anchor_indices=[0], config=cfg, platform_name="CPU")
    assert res2.delta_pmf_kj_mol == res.delta_pmf_kj_mol


def test_box_too_small_blocks(tmp_path):
    sx, tp = _nacl(tmp_path)
    cfg = BindingConfig(pull_distance_nm=1.2, window_prod_ps=5.0)
    res = run_binding(sx, tp, None, tmp_path / "bind_small", ligand_indices=[1], anchor_indices=[0], config=cfg,
                      platform_name="CPU")
    assert res.status == "NEEDS_HUMAN" and "水盒太小" in res.caveats[0]


def test_multi_ligand_exit_path_blocked(tmp_path):
    """WP9 on the real stack: a second 'ligand' (a water placed on Cl-'s exit path) stops the pull before SMD."""
    from openmm import app
    sx, tp = _nacl(tmp_path)
    pdb = app.PDBFile(str(tp))
    xyz = np.asarray(pdb.getPositions(asNumpy=True)._value)
    ox = [a.index for a in pdb.topology.atoms() if a.residue.name == "HOH" and a.element.symbol == "O"]
    target = xyz[1] + np.array([0.25, 0.0, 0.0])                  # beyond Cl along the Na→Cl direction
    w = min(ox, key=lambda i: np.linalg.norm(xyz[i] - target))
    cfg = BindingConfig(pull_distance_nm=0.45, window_prod_ps=5.0, box_margin_nm=0.3)
    res = run_binding(sx, tp, None, tmp_path / "bind_blocked", ligand_indices=[1], anchor_indices=[0], config=cfg,
                      platform_name="CPU", other_ligand_indices={"W": [w]})
    assert res.status == "NEEDS_HUMAN" and "擋住" in res.caveats[0], res.caveats
