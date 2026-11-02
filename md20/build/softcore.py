"""Second-layer repair for multi-ligand geometry (D-61): soft-core relaxation.

When the rigid nudge (≤ 2 Å) cannot clear an overlap or a ring piercing, the offending ligand is allowed to pass through
its neighbours: its non-bonded interactions with everything else are switched to a soft-core form whose repulsion is
finite at r = 0, then switched back on gradually (λ = 0.05 → 1).  At low λ a bond threaded through a ring can slide out
and overlapping atoms separate without the huge forces that would eject the ligand; the internal chemistry of the ligand
(bonds, angles, torsions, its own non-bonded terms) stays at full strength throughout.

Everything else is held: protein and other-ligand heavy atoms by strong position restraints, the moving ligand's centroid
by a flat-bottom restraint (free within `hold_nm` of where it started), so the ligand keeps its binding mode and only
untangles.  The free radius is smaller than ACCEPT_RMSD_A on purpose (D-64): inside it the centroid random-walks during
the 6 ps of Langevin dynamics, so a free radius equal to the acceptance limit rejected correctly untangled ligands
(CI 617658e: unthreaded, RMSD 3.38 Å > 3.0 Å on all three OS).  Soft-core form (Beutler et al., 1994):
    U_LJ = λ·4ε [ 1/(α(1−λ) + (r/σ)^6)^2 − 1/(α(1−λ) + (r/σ)^6) ],   α = 0.5
    U_C  = λ·q_i q_j / (4πε0 · sqrt(r² + β(1−λ)))                      β = 0.01 nm²
Each λ: local minimisation, 1 ps Langevin at 300 K, minimisation.  The result is accepted by the caller only if the pure
geometry check (multi_ligand.check) passes and the ligand moved ≤ ACCEPT_RMSD_A — otherwise it is a different pose and a
human decides.
"""
from __future__ import annotations

import numpy as np

LAMBDAS = (0.05, 0.2, 0.4, 0.6, 0.8, 1.0)
ALPHA, BETA_NM2 = 0.5, 0.01
ACCEPT_RMSD_A = 4.0        # D-64 更正: sanity cap only (a flipped or relocated ligand); see ACCEPT_CENTROID_A
ACCEPT_CENTROID_A = 2.5    # binding mode kept = heavy-atom centroid moved ≤ 2.5 Å (plus protein contacts, checked by the caller)
HOLD_NM = 0.2      # D-64: free drift (2 Å) must stay well inside the acceptance limit (3 Å), see below
COULOMB = 138.935456


def softcore_system(system, moving: list[int], *, fixed: list[int], positions_nm: np.ndarray, hold_nm: float = HOLD_NM,
                    k_fix: float = 5000.0, k_hold: float = 2000.0, cutoff_nm: float = 1.2):
    """Copy of `system` (vacuum or non-periodic) in which `moving` interacts softly with every other particle.
    Returns (new_system, global parameter name of λ)."""
    import openmm as mm
    sys2 = mm.XmlSerializer.deserialize(mm.XmlSerializer.serialize(system))
    nb = next(f for f in sys2.getForces() if isinstance(f, mm.NonbondedForce))
    mov = set(int(i) for i in moving)
    params = {i: nb.getParticleParameters(i) for i in range(nb.getNumParticles())}
    excl = set()
    for e in range(nb.getNumExceptions()):
        i, j, *_ = nb.getExceptionParameters(e)
        excl.add((min(i, j), max(i, j)))
    # 1) moving atoms lose their ordinary non-bonded parameters (exceptions = 1-2/1-3/1-4 stay untouched)
    for i in mov:
        nb.setParticleParameters(i, 0.0, params[i][1], 0.0)
    # 2) the ligand's own non-excluded pairs keep full LJ + Coulomb
    intra = mm.CustomBondForce("138.935456*qq/r + 4*eps*((sig/r)^12-(sig/r)^6)")
    for name in ("qq", "sig", "eps"):
        intra.addPerBondParameter(name)
    ml = sorted(mov)
    for a in range(len(ml)):
        for b in range(a + 1, len(ml)):
            i, j = ml[a], ml[b]
            if (i, j) in excl:
                continue
            qi, si, ei = (params[i][0]._value, params[i][1]._value, params[i][2]._value)
            qj, sj, ej = (params[j][0]._value, params[j][1]._value, params[j][2]._value)
            intra.addBond(i, j, [qi * qj, 0.5 * (si + sj), float(np.sqrt(ei * ej))])
    sys2.addForce(intra)
    # 3) moving × everything else: soft-core LJ + soft Coulomb, scaled by λ
    sc = mm.CustomNonbondedForce(
        "lam*(4*eps*(1/s^2 - 1/s) + 138.935456*q1*q2/sqrt(r^2 + beta*(1-lam)));"
        "s = alpha*(1-lam) + (r/sig)^6; sig = 0.5*(sig1+sig2); eps = sqrt(eps1*eps2)")
    sc.addGlobalParameter("lam", LAMBDAS[0])
    sc.addGlobalParameter("alpha", ALPHA)
    sc.addGlobalParameter("beta", BETA_NM2)
    for name in ("q", "sig", "eps"):
        sc.addPerParticleParameter(name)
    for i in range(nb.getNumParticles()):
        q, s, e = params[i]
        sc.addParticle([q._value, s._value, e._value])
    for (i, j) in excl:
        sc.addExclusion(i, j)
    others = [i for i in range(nb.getNumParticles()) if i not in mov]
    sc.addInteractionGroup(sorted(mov), others)
    sc.setNonbondedMethod(mm.CustomNonbondedForce.CutoffNonPeriodic)
    sc.setCutoffDistance(cutoff_nm)
    sys2.addForce(sc)
    # 4) hold everything else; keep the moving ligand near where it started
    fix = mm.CustomExternalForce("k_fix*((x-x0)^2+(y-y0)^2+(z-z0)^2)")
    fix.addGlobalParameter("k_fix", k_fix)
    for n in ("x0", "y0", "z0"):
        fix.addPerParticleParameter(n)
    for i in fixed:
        fix.addParticle(int(i), [float(v) for v in positions_nm[i]])
    sys2.addForce(fix)
    # +1e-8 nm²: at the starting point d = 0 and the derivative of sqrt would be 0/0 = NaN (CI d3502f0)
    hold = mm.CustomCentroidBondForce(1, "k_hold*step(d-w)*(d-w)^2; d=sqrt((x1-cx)^2+(y1-cy)^2+(z1-cz)^2+1e-8)")
    c = positions_nm[ml].mean(0)
    for n, v in (("k_hold", k_hold), ("w", hold_nm), ("cx", c[0]), ("cy", c[1]), ("cz", c[2])):
        hold.addGlobalParameter(n, float(v))
    hold.addGroup(ml, [1.0] * len(ml))
    hold.addBond([0], [])
    sys2.addForce(hold)
    for k in range(sys2.getNumForces()):
        f = sys2.getForce(k)
        if isinstance(f, mm.NonbondedForce):        # vacuum, 1.2 nm cut-off: only the neighbourhood of the ligand matters here
            f.setNonbondedMethod(mm.NonbondedForce.CutoffNonPeriodic)
            f.setCutoffDistance(cutoff_nm)
        if isinstance(f, (mm.MonteCarloBarostat,)):
            f.setFrequency(0)
    return sys2


def relax(system, positions_nm: np.ndarray, moving: list[int], fixed: list[int], *, steps_per_lambda: int = 1000,
          seed: int = 2026, platform: str | None = None) -> np.ndarray:
    """λ-ramped soft-core relaxation; returns new positions (nm).  Raises on NaN."""
    import openmm as mm
    from openmm import unit
    sys2 = softcore_system(system, moving, fixed=fixed, positions_nm=positions_nm)
    integ = mm.LangevinMiddleIntegrator(300 * unit.kelvin, 5.0 / unit.picosecond, 0.001 * unit.picoseconds)
    integ.setRandomNumberSeed(int(seed))
    plat = mm.Platform.getPlatformByName(platform) if platform else None
    ctx = mm.Context(sys2, integ, plat) if plat else mm.Context(sys2, integ)
    ctx.setPositions(positions_nm * unit.nanometer)
    for lam in LAMBDAS:
        ctx.setParameter("lam", lam)
        mm.LocalEnergyMinimizer.minimize(ctx, 10.0, 500)
        ctx.setVelocitiesToTemperature(300 * unit.kelvin, int(seed))
        integ.step(int(steps_per_lambda))
        mm.LocalEnergyMinimizer.minimize(ctx, 10.0, 500)
    out = ctx.getState(getPositions=True).getPositions(asNumpy=True).value_in_unit(unit.nanometer)
    del ctx, integ
    if not np.all(np.isfinite(out)):
        raise RuntimeError("soft-core relaxation produced NaN")
    return np.asarray(out)
