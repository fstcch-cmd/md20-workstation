"""SMD → umbrella → PMF on Na+/Cl- in TIP3P (real OpenMM, CPU).  Textbook result: contact-ion-pair minimum ≈ 0.28 nm."""
import json
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
    # auto-refinement connects the windows, OR (on a borderline-overlap run) ΔG° is withheld with a reason —
    # both are correct outcomes; the next assertion checks ΔG° is present-or-withheld
    assert res.pmf["quality"]["graph_connected"] or res.pmf.get("dG_withheld"), res.pmf["quality"]
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
    # a water is a blocker only if it lies inside the pull cylinder (Na→Cl axis): 0 < t < pull_distance, perp < radius.
    # Choose one that provably does, rather than guessing a position that may be empty in this solvation.
    pull, radius = 0.45, 0.35                                     # single-atom ligand → radius = clearance_nm
    u = xyz[1] - xyz[0]; u = u / np.linalg.norm(u)
    on_path = []
    for i in ox:
        v = xyz[i] - xyz[1]; t = float(v @ u); perp = float(np.linalg.norm(v - t * u))
        if 0.03 < t < pull and perp < radius:
            on_path.append((perp, i))
    if not on_path:
        pytest.skip("no water sits inside the Cl pull cylinder in this solvation")
    w = min(on_path)[1]
    cfg = BindingConfig(pull_distance_nm=pull, window_prod_ps=5.0, box_margin_nm=0.3)
    res = run_binding(sx, tp, None, tmp_path / "bind_blocked", ligand_indices=[1], anchor_indices=[0], config=cfg,
                      platform_name="CPU", other_ligand_indices={"W": [w]})
    assert res.status == "NEEDS_HUMAN" and "擋住" in res.caveats[0], res.caveats


def test_nacl_funnel(tmp_path):
    """D-140: the funnel force on the NaCl toy (real OpenMM, CPU, kept short: no refinement rounds, 2 ps windows).
    (1) the OpenMM expression gives the energy of the pure-python geometry, also for a ligand in another periodic image;
    (2) run_binding with restraint = "funnel" samples the axial coordinate, records rho, carries the funnel condition and
    the standard-state treatment, and never mixes with a radial run in the same directory.
    ΔG° itself is not asserted (2 ps windows); it is either present or withheld with a reason."""
    import openmm as mm
    from openmm import app, unit, XmlSerializer
    from md20.sampling import funnel as FN
    from md20.sampling.binding import build_pulling_system
    sx, tp = _nacl(tmp_path)
    pdb = app.PDBFile(str(tp))
    pos = np.asarray(pdb.getPositions(asNumpy=True)._value)
    box = np.array([[v.x, v.y, v.z] for v in pdb.topology.getPeriodicBoxVectors()])
    masses = np.ones(len(pos))
    geom, info = FN.estimate_geometry(pos, box, [0], [1], masses, [], r_cyl_nm=0.4, r_cone_nm=0.8, z_cc_nm=0.15)
    # ---- (1) energy of the funnel force alone (force group 31) against the python mirror
    system = build_pulling_system(XmlSerializer.deserialize(sx.read_text()), pos, np.array([0]), np.array([1]), funnel=geom)
    assert [f.getName() for f in system.getForces()].count("md20_funnel") == 1
    ctx = mm.Context(system, mm.VerletIntegrator(0.001), mm.Platform.getPlatformByName("CPU"))
    ctx.setPeriodicBoxVectors(*[mm.Vec3(*row) for row in box])
    u = np.asarray(geom.axis)
    perp = np.cross(u, [0.0, 0.0, 1.0]); perp /= np.linalg.norm(perp)
    for z, rho, image in ((0.28, 0.0, 0), (0.30, 0.70, 0), (0.55, 0.55, 0), (-0.45, 0.1, 0), (0.30, 0.70, 1), (0.55, 0.55, -1)):
        p = pos.copy()
        p[1] = p[0] + z * u + rho * perp + image * box[0]                    # the ligand centroid in a neighbouring image
        ctx.setPositions(p * unit.nanometer)
        e = ctx.getState(getEnergy=True, groups={FN.FUNNEL_FORCE_GROUP}).getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
        assert e == pytest.approx(float(geom.energy(z, rho)), rel=2e-3, abs=2e-2), (z, rho, image, e)
    del ctx
    # ---- (2) a short funnel run
    cfg = BindingConfig(restraint="funnel", funnel_r_cyl_nm=0.4, funnel_r_cone_nm=0.8, funnel_z_cc_nm=0.15,
                        pull_distance_nm=0.5, pull_velocity_nm_per_ps=0.08, k_pull=2000, k_umbrella=1000, box_margin_nm=0.3,
                        target_overlap=0.35, window_equil_ps=0.5, window_prod_ps=2.0, sample_every_steps=20,
                        max_refine_rounds=0, smd_informed_windows=False)
    out = tmp_path / "bind_funnel"
    res = run_binding(sx, tp, None, out, ligand_indices=[1], anchor_indices=[0], config=cfg, platform_name="CPU")
    # D-149: a 2 ps window may not reach the finite-sample floor for WHAM.  Either outcome is correct, and neither may
    # crash: PASS with the funnel PMF, or NEEDS_HUMAN that withholds ΔG°/PMF with a stated reason.  The funnel
    # condition and the recorded z/rho are asserted in both.
    assert res.status in ("PASS", "NEEDS_HUMAN"), res.caveats
    c = res.condition
    assert (c["cv"], c["funnel_restraint"], c["standard_state"]) == ("axial_projection_z", True, "funnel_cylinder_analytic")
    assert res.pmf["cv"] == "axial_projection_z"
    assert json.loads((out / "restraint.json").read_text())["restraint"] == "funnel"
    if res.status == "NEEDS_HUMAN":
        assert res.pmf.get("dG_withheld") and res.dG_standard_kj_mol is None     # withheld, with a reason, not a crash
    else:
        assert res.pmf["jacobian_corrected"] is False
        assert res.pmf["standard_state"]["treatment"] == "funnel_cylinder_analytic" and res.pmf["standard_state"]["a_eff_nm2"] > np.pi * 0.4 ** 2
        chk = res.pmf["funnel"]["checks"]
        assert set(chk) == {"bound_state", "solvation", "bulk_in_cylinder"} and chk["bound_state"]["status"] in ("pass", "fail")
        man = json.loads((out / "binding_manifest.json").read_text())
        assert man["cv"] == "axial_projection_z" and man["funnel"]["pull_extended_to_nm"] > 0.5
        rho_all, wall_all = [], []
        for f in sorted((out / "windows").glob("w_*_cv.npy")):
            z, rho = np.load(f), np.load(str(f).replace("_cv.npy", "_rho.npy"))
            assert len(z) == len(rho) > 10
            rho_all.append(rho); wall_all.append(geom.rho_max(z))
        rho_all, wall_all = np.concatenate(rho_all), np.concatenate(wall_all)
        assert np.mean(rho_all <= wall_all + 0.1) > 0.95
        assert (res.dG_standard_kj_mol is not None) or res.pmf.get("dG_withheld"), "ΔG° missing without a stated reason"
        assert res.assessment["reference_state"] == {"cv": "axial_projection_z", "standard_state": "funnel_cylinder_analytic", "funnel": True}
    # a radial request on this directory is refused instead of mixing the two coordinates
    back = run_binding(sx, tp, None, out, ligand_indices=[1], anchor_indices=[0], config=BindingConfig(), platform_name="CPU")
    assert back.status == "NEEDS_HUMAN"
