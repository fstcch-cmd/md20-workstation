"""Bonded Zn model on carbonic anhydrase II (real OpenMM; heavy → Ubuntu CI job)."""
import os

import numpy as np
import pytest

if os.environ.get("MD20_HEAVY") != "1":
    pytest.skip("set MD20_HEAVY=1 to run the metal integration test", allow_module_level=True)
pytest.importorskip("openmm"); pytest.importorskip("pdbfixer")

from md20.build.receptor import prepare_receptor
from md20.build.assemble import assemble_system


def test_bonded_zinc_ca2(pdb_ca2, tmp_path):
    import openmm as mm
    from openmm import app, unit, XmlSerializer
    rman = prepare_receptor(pdb_ca2, tmp_path / "rec", keep_hetero={"ZN"}, human_choices={"hetero groups": "移除"})
    assert rman["status"] != "NEEDS_HUMAN", rman.get("gates")
    # D-152: CA II's Glu106 is a second-shell carboxylate that collapses onto Zn in a point-charge model (CI: 1.74 Å),
    # so a plain bonded request stops at the competing-carboxylate gate instead of building a collapsing model.
    gated = assemble_system(rman["receptor_pdb"], [], tmp_path / "gated", padding_nm=1.0, metal_policy={"ZN": "bonded"})
    assert gated.status == "NEEDS_HUMAN" and "competing carboxylate" in str(gated.gates)
    # the user chooses to restrain it: exclude the Zn–carboxylate nonbonded pair and add a flat-bottom lower wall at
    # the crystal distance.  Now the model builds, and the carboxylate no longer collapses.
    res = assemble_system(rman["receptor_pdb"], [], tmp_path / "sys", padding_nm=1.0, metal_policy={"ZN": "bonded"},
                          metal_carboxylate={"ZN": "restrain"})
    assert res.status != "NEEDS_HUMAN", res.gates
    assert res.restraints["metals"].get("competing_carboxylate_walls", 0) >= 1
    plans = res.restraints["metals"]["plans"]
    zn = [p for p in plans if p["key"].startswith("ZN")]
    assert len(zn) == 1 and zn[0]["action"] == "bonded", plans
    p = zn[0]
    # D-133: His94, His96, His119 + the crystal zinc water (kept for a bonded site; tetrahedral as in 3KS3)
    assert len(p["bonds"]) == 4, p["bonds"]
    assert sum(1 for b in p["bonds"] if b.get("water")) == 1, p["bonds"]
    assert set(p["variants"].values()) <= {"HID", "HIE"} and len(p["variants"]) == 3
    assert res.restraints["metals"]["exclusions"] >= 4   # 3 His + water, plus the restrained Glu106 carboxylate (D-152)
    assert res.restraints["metals"]["exclusions_13"] >= 6 and res.restraints["metals"]["angles_mdx"] >= 6   # CE1/CD2 per His
    qm = p["qm_input"]                                                       # QM small-model input for the upgrade path
    assert qm["status"] == "PASS" and qm["charge"] == 2 and qm["multiplicity"] == 1 and len(qm["residues"]) == 3
    assert (tmp_path / "sys" / "metal_qm" / "ZN_A262" / "orca.inp").is_file() or any("orca.inp" in f for f in qm["files"])
    system = XmlSerializer.deserialize(open(res.system_xml, encoding="utf-8").read())
    names = {system.getForce(i).getName() for i in range(system.getNumForces())}
    assert {"msw_metal_bonds", "msw_metal_angles"} <= names
    # topology: the tautomer matches the coordinating nitrogen (no H on the N bound to Zn)
    pdb = app.PDBFile(res.topology_pdb)
    atoms = list(pdb.topology.atoms())
    for b in [b for b in p["bonds"] if not b.get("water")]:
        donor = atoms[b["donor"]]
        hname = "HE2" if donor.name == "NE2" else "HD1"
        assert hname not in {a.name for a in donor.residue.atoms()}, (donor.residue, donor.name)
    # geometry survives minimisation + 2 ps MD (nonbonded Zn without the model typically drifts or collapses)
    # A single frame after 2 ps from crystal coordinates is a noisy measurement (unequilibrated solvent, random
    # velocities): the same code passed and failed on CI.  Judge the model the way it is meant: seeded, the *mean*
    # bond length over the second half of a short run within 0.3 Å of r0, and no frame beyond 0.8 Å (a real escape).
    integ = mm.LangevinMiddleIntegrator(300 * unit.kelvin, 1 / unit.picosecond, 0.002 * unit.picoseconds)
    integ.setRandomNumberSeed(2026)
    ctx = mm.Context(system, integ, mm.Platform.getPlatformByName("CPU"))
    ctx.setPositions(pdb.positions)
    if "msw_restraint_scale" in ctx.getParameters():
        ctx.setParameter("msw_restraint_scale", 0.0)
    mm.LocalEnergyMinimizer.minimize(ctx, maxIterations=500)
    ctx.setVelocitiesToTemperature(300 * unit.kelvin, 2026)
    integ.step(1000)                                    # 2 ps transient, discarded
    traces = {b["label"]: [] for b in p["bonds"]}
    # D-34 diagnosis: which non-bonded atoms crowd the metal (a water/hydroxide moving into the 4th site, or a
    # backbone O) — the 0.3 Å mean stretch must be explained before the model is changed
    zn = p["bonds"][0]["metal"]
    donors = {b["donor"] for b in p["bonds"]}
    heavy = np.array([a.index for a in atoms if a.element is not None and a.element.symbol != "H"
                      and a.index != zn and a.index not in donors])
    crowd: dict[str, list[float]] = {}
    for _ in range(20):                                 # 2 ps sampled every 0.1 ps
        integ.step(50)
        xyz = ctx.getState(getPositions=True).getPositions(asNumpy=True).value_in_unit(unit.nanometer)
        for b in p["bonds"]:
            traces[b["label"]].append(float(np.linalg.norm(xyz[b["metal"]] - xyz[b["donor"]])))
        d = np.linalg.norm(xyz[heavy] - xyz[zn], axis=1)
        for i in heavy[d < 0.30]:
            a = atoms[int(i)]
            crowd.setdefault(f"{a.residue.name}{a.residue.id}:{a.name}", []).append(float(np.linalg.norm(xyz[int(i)] - xyz[zn])))
    diag = {"bonds_mean_A": {k: round(float(np.mean(v)) * 10, 3) for k, v in traces.items()},
            "r0_A": {b["label"]: round(b["r0_nm"] * 10, 3) for b in p["bonds"]},
            "nonbonded_within_3A": {k: [len(v), round(float(np.mean(v)) * 10, 2)] for k, v in sorted(crowd.items())}}
    # D-152 regression: Glu106 OE1 collapsed onto Zn (1.74 Å, every frame) under the plain bonded model; with the
    # user's restrain decision (nonbonded exclusion + lower wall at the crystal distance) it must no longer collapse
    assert not any(k.startswith("GLU") and (":OE" in k or ":OD" in k) and v[1] < 2.6 for k, v in diag["nonbonded_within_3A"].items()), diag
    for b in p["bonds"]:
        tr = np.array(traces[b["label"]])
        assert abs(tr.mean() - b["r0_nm"]) < 0.03, (b["label"], tr.mean(), tr.std(), b["r0_nm"], diag)
        assert tr.max() - b["r0_nm"] < 0.08, (b["label"], tr.max(), b["r0_nm"], diag)


def test_fitted_zinc_params_json_ca2(pdb_ca2, tmp_path):
    """metal_params (json source) replace the geometric constants and are checked against the crystal site."""
    import json
    from openmm import XmlSerializer
    import openmm as mm
    rman = prepare_receptor(pdb_ca2, tmp_path / "rec", keep_hetero={"ZN"}, human_choices={"hetero groups": "移除"})
    good = tmp_path / "zn.json"
    good.write_text(json.dumps({"bonds": {"N": {"k_kcal_A2": 80.0}}, "angles": {"default": {"k_kcal_rad2": 35.0}},
                                "charges": {"metal": 2.0}}))
    res = assemble_system(rman["receptor_pdb"], [], tmp_path / "sys", padding_nm=1.0, metal_policy={"ZN": "bonded"},
                          metal_params={"ZN": {"source": "json", "file": str(good)}},
                          metal_carboxylate={"ZN": "restrain"})   # D-165: the test json does not cover Glu106
    assert res.status != "NEEDS_HUMAN", res.gates
    p = next(p for p in res.restraints["metals"]["plans"] if p["key"].startswith("ZN"))
    assert p["source"] == "json" and all(abs(b["k"] - 80.0 * 418.4) < 1e-6 for b in p["bonds"])
    assert all(abs(a["k"] - 35.0 * 4.184) < 1e-6 for a in p["angles"]) and p["charges"] == {str(p["metal_index"]): 2.0}
    system = XmlSerializer.deserialize(open(res.system_xml, encoding="utf-8").read())
    hb = next(system.getForce(i) for i in range(system.getNumForces()) if system.getForce(i).getName() == "msw_metal_bonds")
    assert hb.getNumBonds() == 3 and abs(hb.getBondParameters(0)[3]._value - 80.0 * 418.4) < 1e-6
    nb = next(f for f in system.getForces() if isinstance(f, mm.NonbondedForce))
    assert abs(nb.getParticleParameters(p["metal_index"])[0]._value - 2.0) < 1e-9
    # r0 far from the crystal → the build stops instead of using it
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"bonds": {"N": {"k_kcal_A2": 80.0, "r0_A": 2.6}}, "angles": {"default": {"k_kcal_rad2": 35.0}}}))
    res2 = assemble_system(rman["receptor_pdb"], [], tmp_path / "sys2", padding_nm=1.0, metal_policy={"ZN": "bonded"},
                           metal_params={"ZN": {"source": "json", "file": str(bad)}},
                           metal_carboxylate={"ZN": "restrain"})
    assert res2.status == "NEEDS_HUMAN"
    g = next(g for g in res2.gates["gates"] if g["name"].startswith("metal ZN"))
    assert "與晶體" in g["explanation"] and any("幾何鍵結模型" in o for o in g["options"])


# ------------------------------------------------------------------------------------------------------- D-141
_OH_TEST_JSON = {"bonds": {"N": {"k_kcal_A2": 60.0}}, "angles": {"default": {"k_kcal_rad2": 30.0}},
                 # TEST VALUES that exercise the plumbing (template, topology edit, charges, bonds); not parameters for a real study
                 "site_water": {"state": "hydroxide", "charges": {"O": -1.2, "H": 0.2}, "bond": {"k_kcal_A2": 80.0}}}


def test_hydroxide_site_water_with_fitted_params_ca2(pdb_ca2, tmp_path):
    """D-141 plumbing on CA II: crystal zinc water → OHM (O + one H), template from the fitted charges, M–O bond bonded."""
    import json
    import openmm as mm
    from openmm import app, XmlSerializer
    rman = prepare_receptor(pdb_ca2, tmp_path / "rec", keep_hetero={"ZN"}, human_choices={"hetero groups": "移除"})
    f = tmp_path / "zn_oh.json"
    f.write_text(json.dumps(_OH_TEST_JSON))
    res = assemble_system(rman["receptor_pdb"], [], tmp_path / "sys", padding_nm=1.0, metal_policy={"ZN": "bonded"},
                          metal_params={"ZN": {"source": "json", "file": str(f)}}, metal_water_state={"ZN": "hydroxide"},
                          metal_carboxylate={"ZN": "restrain"})   # D-165: the test json does not cover Glu106
    assert res.status != "NEEDS_HUMAN", res.gates
    p = next(p for p in res.restraints["metals"]["plans"] if p["key"].startswith("ZN"))
    assert p["water_mode"] == "hydroxide" and p["source"] == "json" and len(p["bonds"]) == 4
    wb = [b for b in p["bonds"] if b.get("hydroxide")]
    assert len(wb) == 1 and abs(wb[0]["k"] - 80.0 * 418.4) < 1e-6
    pdb = app.PDBFile(res.topology_pdb)
    oh = [r for r in pdb.topology.residues() if r.name == "OHM"]
    assert len(oh) == 1 and sorted(a.name for a in oh[0].atoms()) == ["H1", "O"]
    system = XmlSerializer.deserialize(open(res.system_xml, encoding="utf-8").read())
    nb = next(f_ for f_ in system.getForces() if isinstance(f_, mm.NonbondedForce))
    o, h = p["site_water"]["o_index"], p["site_water"]["h_index"]
    assert abs(nb.getParticleParameters(o)[0]._value + 1.2) < 1e-6 and abs(nb.getParticleParameters(h)[0]._value - 0.2) < 1e-6
    total = sum(nb.getParticleParameters(i)[0]._value for i in range(nb.getNumParticles()))
    assert abs(total) < 1e-3                                            # neutralised with the hydroxide counted
    hb = next(system.getForce(i) for i in range(system.getNumForces()) if system.getForce(i).getName() == "msw_metal_bonds")
    assert hb.getNumBonds() == 4
    assert (tmp_path / "sys" / "metal_qm" / "ZN_A262" / "hydroxide_template.xml").is_file()


def test_hydroxide_without_parameters_stops_and_writes_the_qm_input(pdb_ca2, tmp_path):
    rman = prepare_receptor(pdb_ca2, tmp_path / "rec", keep_hetero={"ZN"}, human_choices={"hetero groups": "移除"})
    res = assemble_system(rman["receptor_pdb"], [], tmp_path / "sys", padding_nm=1.0, metal_policy={"ZN": "bonded"},
                          metal_water_state={"ZN": "hydroxide"})
    assert res.status == "NEEDS_HUMAN"
    g = next(g for g in res.gates["gates"] if g["name"].startswith("metal water state ZN"))
    assert g["status"] == "NEEDS_HUMAN" and len(g["options"]) == 3
    qm = tmp_path / "sys" / "metal_qm" / "ZN_A262_hydroxide"
    assert "* xyz 1 1" in (qm / "orca.inp").read_text(encoding="utf-8")            # Zn(+2) + three neutral His + OH(−1)
    assert "氫氧根" in (qm / "README.md").read_text(encoding="utf-8")
