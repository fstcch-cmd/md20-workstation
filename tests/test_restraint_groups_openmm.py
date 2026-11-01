"""Grouped position restraints on a real OpenMM context (D-23).  Runs in the openmm-stack CI matrix."""
import numpy as np
import pytest

mm = pytest.importorskip("openmm")
from openmm import app, unit  # noqa: E402

from md20.build.assemble import add_position_restraints  # noqa: E402
from md20.sampling.binding import build_pulling_system  # noqa: E402


def _toy():
    top = app.Topology()
    ch = top.addChain()
    ala = top.addResidue("ALA", ch)
    for n, el in (("N", "N"), ("CA", "C"), ("C", "C"), ("O", "O"), ("CB", "C"), ("HA", "H")):
        top.addAtom(n, app.Element.getBySymbol(el), ala)
    lig = top.addResidue("LIG", ch)
    for n, el in (("C1", "C"), ("H1", "H")):
        top.addAtom(n, app.Element.getBySymbol(el), lig)
    hoh = top.addResidue("HOH", ch)
    top.addAtom("O", app.Element.getBySymbol("O"), hoh)
    system = mm.System()
    for _ in range(top.getNumAtoms()):
        system.addParticle(12.0)
    pos = unit.Quantity(np.zeros((top.getNumAtoms(), 3)), unit.nanometer)
    return system, top, pos


def _energy(system, shift_nm=0.1, params=None):
    ctx = mm.Context(system, mm.VerletIntegrator(0.001), mm.Platform.getPlatformByName("Reference"))
    xyz = np.zeros((system.getNumParticles(), 3)); xyz[:, 0] = shift_nm
    ctx.setPositions(xyz * unit.nanometer)
    for k, v in (params or {}).items():
        ctx.setParameter(k, v)
    return ctx.getState(getEnergy=True).getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)


def test_groups_and_counts():
    system, top, pos = _toy()
    info = add_position_restraints(system, top, pos, ligand_resnames={"LIG"})
    assert (info["protein_backbone_atoms"], info["protein_sidechain_atoms"], info["ligand_heavy_atoms"]) == (4, 1, 1)
    one = 0.5 * 1000.0 * 0.01                     # one heavy atom displaced 0.1 nm at k = 1000
    assert _energy(system) == pytest.approx(6 * one)        # H and water unrestrained
    assert _energy(system, params={"msw_rs_backbone": 0.0}) == pytest.approx(2 * one)
    assert _energy(system, params={"msw_rs_sidechain": 0.0, "msw_rs_ligand": 0.0}) == pytest.approx(4 * one)
    assert _energy(system, params={"msw_restraint_scale": 0.5}) == pytest.approx(3 * one)


def test_pulling_system_frees_ligand_and_sidechains():
    system, top, pos = _toy()
    add_position_restraints(system, top, pos, ligand_resnames={"LIG"})
    build_pulling_system(system, np.zeros((top.getNumAtoms(), 3)), anchor=np.array([1]), ligand=np.array([6]))
    f = next(f for f in system.getForces() if f.getName() == "msw_position_restraints")
    ks = [f.getParticleParameters(p)[1][0] for p in range(f.getNumParticles())]
    assert sorted(ks) == [0.0, 0.0, 1000.0, 1000.0, 1000.0, 1000.0]   # CB and ligand freed, backbone kept
