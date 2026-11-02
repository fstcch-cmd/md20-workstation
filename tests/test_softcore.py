"""D-61: soft-core relaxation untangles a bond threaded through a ring (needs OpenMM; runs in CI openmm-stack)."""
import numpy as np
import pytest

mm = pytest.importorskip("openmm")
from openmm import unit  # noqa: E402

from md20.build import multi_ligand as ML, softcore as SC  # noqa: E402


def _system():
    ang = np.linspace(0, 2 * np.pi, 7)[:-1]
    ring = np.c_[0.139 * np.cos(ang), 0.139 * np.sin(ang), np.zeros(6)]
    chain = np.array([[0.03, 0.02, -0.12], [0.03, 0.02, 0.03], [0.03, 0.02, 0.18], [0.03, 0.02, 0.33]])   # end bond threaded
    pos = np.vstack([ring, chain])
    s = mm.System()
    for _ in range(len(pos)):
        s.addParticle(12.0)
    bonds = mm.HarmonicBondForce()
    for i in range(6):
        bonds.addBond(i, (i + 1) % 6, 0.139, 3e5)
    for i in range(3):
        bonds.addBond(6 + i, 7 + i, 0.153, 2.5e5)
    s.addForce(bonds)
    angles = mm.HarmonicAngleForce()
    for i in range(6):
        angles.addAngle(i, (i + 1) % 6, (i + 2) % 6, np.radians(120), 500)
    angles.addAngle(6, 7, 8, np.radians(112), 400); angles.addAngle(7, 8, 9, np.radians(112), 400)
    s.addForce(angles)
    nb = mm.NonbondedForce()
    for _ in range(len(pos)):
        nb.addParticle(0.0, 0.34, 0.36)
    for grp in (range(6), range(6, 10)):
        g = list(grp)
        for a in range(len(g)):
            for b in range(a + 1, len(g)):
                nb.addException(g[a], g[b], 0.0, 0.1, 0.0)
    nb.setNonbondedMethod(mm.NonbondedForce.NoCutoff)
    s.addForce(nb)
    return s, pos


def test_softcore_unthreads_and_keeps_the_ligand_near():
    s, pos = _system()
    ring = ML.Mol("A", ["C"] * 6, pos[:6] * 10)
    chain0 = ML.Mol("B", ["C"] * 4, pos[6:] * 10)
    assert ML.piercings(ring, ring.xyz, chain0, chain0.xyz)
    for seed in (2026, 2027, 2028):                 # the build repair tries the same three seeds
        new = SC.relax(s, pos, moving=list(range(6, 10)), fixed=list(range(6)), platform="Reference", seed=seed)
        chain = ML.Mol("B", ["C"] * 4, new[6:] * 10)
        if not ML.piercings(ring, ring.xyz, chain, chain.xyz):
            break
    assert not ML.piercings(ring, ring.xyz, chain, chain.xyz)
    rmsd = float(np.sqrt(((new[6:] - pos[6:]) ** 2).sum(1).mean())) * 10
    shift = float(np.linalg.norm(new[6:].mean(0) - pos[6:].mean(0))) * 10
    print(f"soft-core unthreading: centroid shift {shift:.2f} A, RMSD {rmsd:.2f} A")
    assert shift <= SC.ACCEPT_CENTROID_A and rmsd <= SC.ACCEPT_RMSD_A and np.allclose(new[:6], pos[:6], atol=0.02)


def test_spectator_hold_force_is_flat_inside_the_band():
    from md20.sampling.binding import add_spectator_hold
    s = mm.System()
    for _ in range(2):
        s.addParticle(12.0)
    pos = np.array([[0.0, 0, 0], [1.0, 0, 0]])
    info = add_spectator_hold(s, pos, None, np.array([0]), {"B": np.array([1])}, np.array([12.0, 12.0]), 0.3)
    assert info["B"]["d0_nm"] == pytest.approx(1.0)
    ctx = mm.Context(s, mm.VerletIntegrator(0.001), mm.Platform.getPlatformByName("Reference"))
    for x, zero in ((1.2, True), (0.75, True), (1.5, False)):
        ctx.setPositions(np.array([[0.0, 0, 0], [x, 0, 0]]) * unit.nanometer)
        e = ctx.getState(getEnergy=True).getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
        assert (e == pytest.approx(0.0)) == zero


def test_free_drift_radius_is_inside_the_acceptance_limit():   # D-64
    import inspect
    assert SC.HOLD_NM * 10 <= SC.ACCEPT_CENTROID_A - 0.5
    assert inspect.signature(SC.softcore_system).parameters["hold_nm"].default == SC.HOLD_NM
