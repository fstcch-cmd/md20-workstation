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
    res = assemble_system(rman["receptor_pdb"], [], tmp_path / "sys", padding_nm=0.8, metal_policy={"ZN": "bonded"})
    assert res.status != "NEEDS_HUMAN", res.gates
    plans = res.restraints["metals"]["plans"]
    zn = [p for p in plans if p["key"].startswith("ZN")]
    assert len(zn) == 1 and zn[0]["action"] == "bonded", plans
    p = zn[0]
    assert len(p["bonds"]) == 3, p["bonds"]                                    # His94, His96, His119
    assert set(p["variants"].values()) <= {"HID", "HIE"} and len(p["variants"]) == 3
    assert res.restraints["metals"]["exclusions"] == 3
    qm = p["qm_input"]                                                       # QM small-model input for the upgrade path
    assert qm["status"] == "PASS" and qm["charge"] == 2 and qm["multiplicity"] == 1 and len(qm["residues"]) == 3
    assert (tmp_path / "sys" / "metal_qm" / "ZN_A262" / "orca.inp").is_file() or any("orca.inp" in f for f in qm["files"])
    system = XmlSerializer.deserialize(open(res.system_xml, encoding="utf-8").read())
    names = {system.getForce(i).getName() for i in range(system.getNumForces())}
    assert {"msw_metal_bonds", "msw_metal_angles"} <= names
    # topology: the tautomer matches the coordinating nitrogen (no H on the N bound to Zn)
    pdb = app.PDBFile(res.topology_pdb)
    atoms = list(pdb.topology.atoms())
    for b in p["bonds"]:
        donor = atoms[b["donor"]]
        hname = "HE2" if donor.name == "NE2" else "HD1"
        assert hname not in {a.name for a in donor.residue.atoms()}, (donor.residue, donor.name)
    # geometry survives minimisation + 2 ps MD (nonbonded Zn without the model typically drifts or collapses)
    integ = mm.LangevinMiddleIntegrator(300 * unit.kelvin, 1 / unit.picosecond, 0.002 * unit.picoseconds)
    ctx = mm.Context(system, integ, mm.Platform.getPlatformByName("CPU"))
    ctx.setPositions(pdb.positions)
    if "msw_restraint_scale" in ctx.getParameters():
        ctx.setParameter("msw_restraint_scale", 0.0)
    mm.LocalEnergyMinimizer.minimize(ctx, maxIterations=500)
    integ.step(1000)
    xyz = ctx.getState(getPositions=True).getPositions(asNumpy=True).value_in_unit(unit.nanometer)
    for b in p["bonds"]:
        d = np.linalg.norm(xyz[b["metal"]] - xyz[b["donor"]])
        assert abs(d - b["r0_nm"]) < 0.03, (b["label"], d, b["r0_nm"])


def test_fitted_zinc_params_json_ca2(pdb_ca2, tmp_path):
    """metal_params (json source) replace the geometric constants and are checked against the crystal site."""
    import json
    from openmm import XmlSerializer
    import openmm as mm
    rman = prepare_receptor(pdb_ca2, tmp_path / "rec", keep_hetero={"ZN"}, human_choices={"hetero groups": "移除"})
    good = tmp_path / "zn.json"
    good.write_text(json.dumps({"bonds": {"N": {"k_kcal_A2": 80.0}}, "angles": {"default": {"k_kcal_rad2": 35.0}},
                                "charges": {"metal": 2.0}}))
    res = assemble_system(rman["receptor_pdb"], [], tmp_path / "sys", padding_nm=0.8, metal_policy={"ZN": "bonded"},
                          metal_params={"ZN": {"source": "json", "file": str(good)}})
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
    res2 = assemble_system(rman["receptor_pdb"], [], tmp_path / "sys2", padding_nm=0.8, metal_policy={"ZN": "bonded"},
                           metal_params={"ZN": {"source": "json", "file": str(bad)}})
    assert res2.status == "NEEDS_HUMAN"
    g = next(g for g in res2.gates["gates"] if g["name"].startswith("metal ZN"))
    assert "與晶體" in g["explanation"] and any("幾何鍵結模型" in o for o in g["options"])
