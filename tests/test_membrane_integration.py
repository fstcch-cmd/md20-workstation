"""Membrane systems on a real OpenMM (CI openmm-stack; skipped without openmm): a POPC bilayer (case C) and a short
peptide above it (case B), each run a few hundred steps with MonteCarloMembraneBarostat.  docs/specs/membrane.md §8."""
import json

import numpy as np
import pytest

mm = pytest.importorskip("openmm")
from openmm import app, unit  # noqa: E402

from md20.analysis import membrane as MA  # noqa: E402
from md20.build import membrane as MB  # noqa: E402
from md20.build.gates import NEEDS_HUMAN  # noqa: E402
from md20.engine.backend import OpenMMBackend  # noqa: E402


def _blocking(res):
    return [g for g in (res.gates or {}).get("gates", []) if g["status"] == NEEDS_HUMAN]


def _run_membrane_npt(res, steps=300):
    b = OpenMMBackend(res.system_xml, res.topology_pdb, platform_name="CPU", ensemble="NPT", temperature_k=310.0,
                      timestep_fs=2.0, barostat="membrane", barostat_interval_steps=25, seed=1)
    assert b.info["barostat"] == "MonteCarloMembraneBarostat"
    b.initialize(None, 310.0, 1, True)
    b.minimize(10.0, 500)
    box0 = b.sim.context.getState().getPeriodicBoxVectors(asNumpy=True).value_in_unit(unit.nanometer)
    b.step(steps)
    st = b.sim.context.getState(getPositions=True, getEnergy=True)
    box = st.getPeriodicBoxVectors(asNumpy=True).value_in_unit(unit.nanometer)
    s = b.summary()
    assert s.finite(), s
    # XY isotropic: x and y scale together, so their ratio is unchanged; z moves independently
    assert box[0][0] / box[1][1] == pytest.approx(box0[0][0] / box0[1][1], rel=1e-6)
    xyz = st.getPositions(asNumpy=True).value_in_unit(unit.nanometer)
    b.close()
    return np.asarray(xyz), np.array([box[0][0], box[1][1], box[2][2]])


def test_popc_bilayer_case_c(tmp_path):
    from md20.build.assemble import assemble_system
    res = assemble_system(None, [], tmp_path, membrane={"type": "bilayer", "lipids": {"POPC": 1.0}})
    assert res.status != NEEDS_HUMAN, _blocking(res)
    man = json.loads((tmp_path / "build_manifest.json").read_text(encoding="utf-8"))
    mem = man["membrane"]
    assert mem["builder"] == "openmm_patch_tile" and mem["n_lipids"] == 128 and mem["n_upper"] == mem["n_lower"] == 64
    assert man["restraints"]["lipid_head"]["atoms"] == 128
    assert abs(man["total_charge"]) < 1e-3 and mem["ions_by_replacement"]["salt_pairs"] > 0
    wg = [g for g in (man.get("gates") or {}).get("gates", []) if g["name"] == "water overlaps"]
    assert wg and wg[0]["status"] in ("PASS", "AUTO_FIXED"), wg
    # D-104: live 3D snapshots of the real build (bilayer, then after the water de-clash), all 128 heads drawn
    from md20.build.live3d import read_index, latest_scene
    assert [s["stage"] for s in read_index(tmp_path)["stages"]] == ["bilayer", "declashed"]
    sc, _ = latest_scene(tmp_path)
    # D-112: "H" = head ATOMS (P and N of every POPC → 2 per lipid), not lipids; one phosphate per lipid = 128
    heads_drawn = [a for a in sc["atoms"] if a["k"] == "H"]
    assert sum(a["n"] == "P" for a in heads_drawn) == 128 and len(heads_drawn) == sc["summary"]["n_lipid_heads"] == 256
    assert not any(a["r"] == "HOH" for a in sc["atoms"])
    xyz, box = _run_membrane_npt(res)
    heads = xyz[mem["head_atom_indices"]][None]
    th = MA.thickness_pp(heads, box[None])
    assert 3.2 < th["mean_nm"] < 4.3
    apl = MA.area_per_lipid(box[None], 64, 64)["mean_nm2"]
    assert 0.55 < apl < 0.75


def test_peptide_above_popc_case_b(tmp_path):
    pytest.importorskip("rdkit")
    res = MB.build_membrane_system(tmp_path, {"type": "surface", "lipids": "mammalian", "surface_distance_nm": 1.0},
                                   peptide_sequence="KLAKLAK")
    assert res.status != NEEDS_HUMAN, _blocking(res)
    man = json.loads((tmp_path / "build_manifest.json").read_text(encoding="utf-8"))
    mem = man["membrane"]
    assert mem["builder"] == "openmm_addmembrane" and mem["surface"]["distance_nm"] == 1.0
    pdb = app.PDBFile(res.topology_pdb)
    xyz0 = np.asarray(pdb.positions.value_in_unit(unit.nanometer))
    pep = [a.index for a in pdb.topology.atoms() if a.residue.chain.id == "P" and a.element.symbol != "H"]
    heads = xyz0[mem["head_atom_indices"]]
    box0 = np.array(mem["box_nm"])
    d = MA.insertion_depth(xyz0[pep][None], heads[None], box0[None])
    # starts above the head groups: the deepest heavy atom is 1.0 nm above the upper phosphate plane (± patch roughness)
    assert d["deepest_nm"][0] == pytest.approx(-1.0, abs=0.25)
    # nothing in the water layer above the peptide is closer than the cutoff to the other leaflet's image
    assert box0[2] >= MB.surface_box_z(float(xyz0[:, 2].max()), centre_z=mem["centre_z_nm"], dpp_nm=3.7) - 0.6
    # D-102: solvation must not leave overlapping waters (root cause of the intermittent NaN); the build gate fired
    wg = [g for g in (man.get("gates") or {}).get("gates", []) if g["name"] == "water overlaps"]
    assert wg and wg[0]["status"] in ("PASS", "AUTO_FIXED"), wg
    # D-104: the placed peptide with the target phosphate planes comes first, before the slow bilayer step
    from md20.build.live3d import read_index
    import json as _json
    idx = read_index(tmp_path)
    assert [s["stage"] for s in idx["stages"]] == ["solute", "bilayer", "declashed"]
    first = _json.loads((tmp_path / "live3d" / idx["stages"][0]["file"]).read_text(encoding="utf-8"))
    assert len(first["planes"]) == 2 and all(a["k"] in ("P", "L") for a in first["atoms"])
    xyz, box = _run_membrane_npt(res, steps=400)          # was 200; longer, to catch a late blow-up now that it is fixed
    assert np.isfinite(xyz).all()


@pytest.mark.xfail(reason="grid placer: first run on a real engine (docs/specs/membrane.md §4.3); not yet verified",
                   strict=False)
def test_grid_mixture_popc_pope(tmp_path):
    from md20.build.assemble import assemble_system
    res = assemble_system(None, [], tmp_path, membrane={"type": "bilayer", "lipids": {"POPC": 0.5, "POPE": 0.5}})
    assert res.status != NEEDS_HUMAN, _blocking(res)
    man = json.loads((tmp_path / "build_manifest.json").read_text(encoding="utf-8"))
    assert man["membrane"]["builder"] == "grid"
    _run_membrane_npt(res, steps=200)
