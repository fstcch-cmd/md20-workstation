"""D-53: ligand that coordinates a metal directly — distance-restraint fallback (opt-in), binding skipped."""
import pytest

from md20.build.metal import ligand_metal_gate, LM_FLAT_NM, LM_K
from md20.gui.actions import gate_actions, apply_patch

C = [{"metal": "ZN:A301", "ligand_resname": "L01", "atom": "O1", "element": "O", "distance_A": 2.05, "metal_index": 10, "atom_index": 20}]


def test_gate_blocks_by_default_and_restrain_is_opt_in():
    g = ligand_metal_gate(C)
    assert g.status == "NEEDS_HUMAN" and any(o.startswith("ligand_metal: restrain") for o in g.options)
    g2 = ligand_metal_gate(C, "restrain")
    assert g2.status == "AUTO_FIXED" and "不計算" in g2.explanation and g2.diff
    acts, manual = gate_actions(g.to_dict(), step="md_cases")
    act = next(a for a in acts if a["label"].startswith("ligand_metal"))
    assert apply_patch({}, act["patch"]) == {"ligand_metal": "restrain"} and act["from_step"] == "md_cases"
    from md20.workflow import DECISION_KEYS
    assert ("ligand_metal",) in DECISION_KEYS


def test_restraint_force_is_flat_bottom():
    mm = pytest.importorskip("openmm")
    from openmm import unit
    from md20.build.metal import add_ligand_metal_restraints
    for d_nm, expect in ((0.205, 0.0), (0.205 + LM_FLAT_NM + 0.02, LM_K * 0.02 ** 2), (0.205 - LM_FLAT_NM - 0.03, LM_K * 0.03 ** 2)):
        sysm = mm.System()
        for _ in range(21):
            sysm.addParticle(1.0)
        recs = add_ligand_metal_restraints(sysm, C, periodic=False)
        assert recs[0]["lo_nm"] == pytest.approx(0.205 - LM_FLAT_NM) and recs[0]["hi_nm"] == pytest.approx(0.205 + LM_FLAT_NM)
        ctx = mm.Context(sysm, mm.VerletIntegrator(0.001), mm.Platform.getPlatformByName("Reference"))
        pos = [mm.Vec3(0, 0, 0)] * 21
        pos[20] = mm.Vec3(d_nm, 0, 0)
        ctx.setPositions(pos)
        e = ctx.getState(getEnergy=True).getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
        assert e == pytest.approx(expect, abs=1e-6)
