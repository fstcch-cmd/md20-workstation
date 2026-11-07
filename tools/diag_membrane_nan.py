"""Diagnose the intermittent NaN of tests/test_membrane_integration.py::test_peptide_above_popc_case_b (DECISIONS 11/07).

Follows the test's path exactly (build_membrane_system → OpenMMBackend CPU, NPT 310 K, 2 fs, membrane barostat every
25 steps) but stops every 10 steps to record energy, max force and max speed, and — when a step blows up — which atoms
were hottest just before (residue, chain, nearest non-bonded neighbour).  Separates the sources of randomness:

  build      several independent builds; positions hashed (does addMembrane give the same start every time?)
  dynamics   several velocity seeds from one build
  minimise   500 iterations (the test) vs 5000 (the workflow's minimise stage)

Round 2 (cross-OS): --from-builds DIR runs the dynamics on builds made elsewhere (DIR/build*/system.xml +
topology.pdb), so "the structure built on Windows is bad" and "the dynamics on Windows is bad" can be told apart.
Every build also records what each chain is (residues, z range) and the closest intermolecular water contacts.

Usage:  python tools/diag_membrane_nan.py OUT_DIR [--builds 3] [--seeds 1,2,3] [--steps 200] [--from-builds DIR]
Set OPENMM_CPU_THREADS=1 in the environment for a single-threaded (deterministic summation) pass.
Writes OUT_DIR/diag.json and prints one line per run plus a summary.  Not a test; changes nothing in md20.

Exit code: ALWAYS 0 by design (diagnostic collection must not be lost to a red job, and a green job from this script
proves nothing scientific).  Whether the artifact is complete is decided by the separate tools/validate_membrane_diag.py
(D-136), which reads the "protocol" block and the "finished" marker this script writes (output fields only; the
simulation itself is unchanged).  Seeds: run["seed"] seeds BOTH the velocity generation and the Langevin integrator;
the build uses the membrane plan's own seed (recorded as build["construction_seed"], never varied here); the
barostat RNG seed is not set by this script or by md20 (OpenMM default).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

import numpy as np


def _atoms(top):
    return [(a.index, a.name, a.element.symbol if a.element is not None else "?", a.residue.name, a.residue.id,
             a.residue.chain.id) for a in top.atoms()]


def _bonded(top):
    nb: dict[int, set] = {}
    for a, b in top.bonds():
        nb.setdefault(a.index, set()).add(b.index)
        nb.setdefault(b.index, set()).add(a.index)
    return nb


def _nearest(xyz, box, i, nb):
    d = xyz - xyz[i]
    d -= np.round(d / box) * box
    r = np.sqrt((d * d).sum(1))
    r[i] = np.inf
    for j in nb.get(i, ()):
        r[j] = np.inf
    j = int(np.argmin(r))
    return j, float(r[j])


def _describe(idx, atoms, xyz=None, box=None, nb=None, extra=None):
    out = []
    for k, i in enumerate(idx):
        a = atoms[i]
        row = {"atom": int(i), "name": a[1], "el": a[2], "res": f"{a[3]}{a[4]}", "chain": a[5]}
        if extra is not None:
            row["value"] = round(float(extra[k]), 1)
        if xyz is not None:
            j, r = _nearest(xyz, box, i, nb)
            b = atoms[j]
            row["nearest"] = {"atom": j, "name": b[1], "res": f"{b[3]}{b[4]}", "chain": b[5], "r_nm": round(r, 4)}
        out.append(row)
    return out


def _snapshot(ctx, unit):
    st = ctx.getState(getPositions=True, getVelocities=True, getForces=True, getEnergy=True)
    xyz = np.asarray(st.getPositions(asNumpy=True).value_in_unit(unit.nanometer))
    v = np.asarray(st.getVelocities(asNumpy=True).value_in_unit(unit.nanometer / unit.picosecond))
    f = np.asarray(st.getForces(asNumpy=True).value_in_unit(unit.kilojoule_per_mole / unit.nanometer))
    bv = st.getPeriodicBoxVectors(asNumpy=True).value_in_unit(unit.nanometer)
    box = np.array([bv[0][0], bv[1][1], bv[2][2]])
    pe = st.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
    return xyz, v, f, box, pe


def structure_stats(top, xyz, box) -> dict:
    """Chains (residue names, counts, z range) and intermolecular water contacts right after the build."""
    chains: dict = {}
    for r in top.residues():
        c = chains.setdefault(r.chain.id, {"n_res": 0, "resnames": {}, "atoms": []})
        c["n_res"] += 1
        c["resnames"][r.name] = c["resnames"].get(r.name, 0) + 1
        c["atoms"].extend(a.index for a in r.atoms())
    for c in chains.values():
        z = xyz[c.pop("atoms"), 2]
        c["z_nm"] = [round(float(z.min()), 3), round(float(z.max()), 3)]
        c["resnames"] = dict(sorted(c["resnames"].items(), key=lambda kv: -kv[1])[:4])
    ow = [(a.index, a.residue.chain.id, a.residue.index) for a in top.atoms() if a.residue.name == "HOH" and a.element is not None and a.element.symbol == "O"]
    hw = [(a.index, a.residue.chain.id, a.residue.index) for a in top.atoms() if a.residue.name == "HOH" and a.element is not None and a.element.symbol == "H"]
    out = {"chains": chains, "box_nm": [round(float(x), 3) for x in box]}
    try:
        from scipy.spatial import cKDTree
        O = np.mod(xyz[[i for i, _, _ in ow]], box)
        H = np.mod(xyz[[i for i, _, _ in hw]], box)
        tO = cKDTree(O, boxsize=box)
        pairs = tO.query_pairs(0.24, output_type="ndarray")
        d = np.linalg.norm(((O[pairs[:, 0]] - O[pairs[:, 1]]) + box / 2) % box - box / 2, axis=1) if len(pairs) else np.zeros(0)
        cross = [ow[i][1] != ow[j][1] for i, j in pairs] if len(pairs) else []
        out["water_OO_lt_0.24"] = int(len(pairs))
        out["water_OO_lt_0.22"] = int((d < 0.22).sum())
        out["water_OO_min"] = round(float(d.min()), 4) if len(d) else None
        out["water_OO_lt_0.24_cross_chain"] = int(sum(cross))
        tH = cKDTree(H, boxsize=box)
        close = tO.sparse_distance_matrix(tH, 0.14, output_type="ndarray")
        inter = [(int(i), int(j), float(dd)) for i, j, dd in close if ow[int(i)][2] != hw[int(j)][2]]
        out["water_OH_inter_lt_0.14"] = len(inter)
        out["water_OH_inter_min"] = round(min(x[2] for x in inter), 4) if inter else None
        by = {}
        for i, j, _ in inter:
            k = f"{ow[i][1]}-{hw[j][1]}"
            by[k] = by.get(k, 0) + 1
        out["water_OH_inter_lt_0.14_by_chain"] = by
        # D-115: ion–water O distances (an ion that replaced one water of an overlapping pair sits on the other)
        ions = [(a.index, a.element.symbol) for a in top.atoms() if a.element is not None and len(list(a.residue.atoms())) == 1
                and a.element.symbol in ("Na", "Cl", "K", "Mg", "Ca", "Zn", "Li", "Br", "F", "I", "Rb", "Cs")]
        ion_min = {}
        for i, el in ions:
            dd, _ = tO.query(np.mod(xyz[i], box))
            ion_min[el] = round(min(ion_min.get(el, 9.9), float(dd)), 4)
        out["ion_water_O_min"] = ion_min
        from md20.build.assemble import ION_O_MIN_NM
        out["ions_on_water"] = sum(1 for i, el in ions if tO.query(np.mod(xyz[i], box))[0] < ION_O_MIN_NM.get(el, 0))
    except Exception as exc:  # noqa: BLE001
        out["water_stats_error"] = f"{type(exc).__name__}: {exc}"
    return out


def run_one(res, atoms, nb, *, min_iter: int, seed: int, steps: int, unit) -> dict:
    from md20.engine.backend import OpenMMBackend
    t0 = time.time()
    b = OpenMMBackend(res.system_xml, res.topology_pdb, platform_name="CPU", ensemble="NPT", temperature_k=310.0,
                      timestep_fs=2.0, barostat="membrane", barostat_interval_steps=25, seed=seed)
    b.initialize(None, 310.0, seed, True)
    ctx = b.sim.context
    xyz, v, f, box, pe0 = _snapshot(ctx, unit)
    b.minimize(10.0, min_iter)
    xyz, v, f, box, pe = _snapshot(ctx, unit)
    fm = np.sqrt((f * f).sum(1))
    top = np.argsort(fm)[::-1][:6]
    out = {"min_iter": min_iter, "seed": seed, "pe_start": round(pe0, 1), "pe_min": round(pe, 1),
           "fmax_after_min": round(float(fm.max()), 1), "n_atoms_f_gt_1e4": int((fm > 1e4).sum()),
           "n_atoms_f_gt_1e3": int((fm > 1e3).sum()),
           "top_force_after_min": _describe(top, atoms, xyz, box, nb, fm[top]), "chunks": [], "nan_at_step": None}
    last = None
    for k in range(0, steps, 10):
        try:
            b.step(10)
            xyz, v, f, box, pe = _snapshot(ctx, unit)
            if not (np.isfinite(xyz).all() and np.isfinite(pe)):
                raise ArithmeticError("non-finite state")
        except Exception as exc:  # noqa: BLE001
            out["nan_at_step"] = k + 10
            out["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
            if last is not None:
                lxyz, lv, lf, lbox, lpe = last
                sp = np.sqrt((lv * lv).sum(1))
                lfm = np.sqrt((lf * lf).sum(1))
                ts, tf = np.argsort(sp)[::-1][:6], np.argsort(lfm)[::-1][:6]
                out["before_nan"] = {"step": k, "pe": round(lpe, 1), "box_nm": [round(x, 3) for x in lbox],
                                     "hottest_speed": _describe(ts, atoms, lxyz, lbox, nb, sp[ts]),
                                     "hottest_force": _describe(tf, atoms, lxyz, lbox, nb, lfm[tf])}
            break
        fm = np.sqrt((f * f).sum(1))
        sp = np.sqrt((v * v).sum(1))
        out["chunks"].append([k + 10, round(pe, 0), round(float(fm.max()), 0), round(float(sp.max()), 2),
                              [round(x, 3) for x in box]])
        last = (xyz, v, f, box, pe)
    b.close()
    out["seconds"] = round(time.time() - t0, 1)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--builds", type=int, default=3)
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--long-min", type=int, default=5000)
    ap.add_argument("--from-builds", default=None, help="run dynamics on builds in this folder instead of building")
    a = ap.parse_args(argv)
    from openmm import app, unit, Platform, version
    from md20.build import membrane as MB
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    seeds = [int(s) for s in a.seeds.split(",") if s]
    report = {"openmm": version.full_version, "platform_threads": os.environ.get("OPENMM_CPU_THREADS", "default"),
              "cpu_count": os.cpu_count(), "python": sys.version.split()[0], "builds": []}
    try:
        report["cpu_threads_property"] = Platform.getPlatformByName("CPU").getPropertyDefaultValue("Threads")
    except Exception:  # noqa: BLE001
        pass
    try:
        report["platforms"] = [Platform.getPlatform(i).getName() for i in range(Platform.getNumPlatforms())]
    except Exception:  # noqa: BLE001
        pass
    import types
    sources = sorted(Path(a.from_builds).glob("build*")) if a.from_builds else [None] * a.builds
    report["from_builds"] = a.from_builds
    # D-136: what was requested, so tools/validate_membrane_diag.py can tell a complete artifact from a partial one.
    # Output fields only; nothing below changes how a build or a run is performed.
    try:
        _construction_seed = MB.DEFAULTS.get("seed") if not a.from_builds else None
    except Exception:  # noqa: BLE001
        _construction_seed = None
    report["protocol"] = {
        "schema": "md20.membrane_diag/2", "builds_requested": len(sources), "velocity_seeds": seeds, "steps": a.steps,
        "chunk_steps": 10, "min_iter_short": 500, "min_iter_long": a.long_min, "runs_per_build": len(seeds) + 1,
        "from_builds": a.from_builds, "construction_seed": _construction_seed, "construction_seed_varied": False,
        "seed_roles": {"run.seed": "velocity generation and Langevin integrator seed",
                       "construction_seed": "membrane plan seed (lipid layout, solute orientation); the same for every build here",
                       "not_controlled": ["MonteCarloMembraneBarostat RNG seed (not set by md20; OpenMM default)",
                                          "CPU force-summation order unless OPENMM_CPU_THREADS=1"]},
    }
    report["finished"] = False
    for k, src in enumerate(sources):
        bdir = src if src is not None else out / f"build{k}"
        t0 = time.time()
        rec: dict = {"build": k, "source": str(src) if src else "built here",
                     "construction_seed": report["protocol"]["construction_seed"]}
        try:
            if src is None:
                res = MB.build_membrane_system(bdir, {"type": "surface", "lipids": "mammalian", "surface_distance_nm": 1.0},
                                               peptide_sequence="KLAKLAK")
            else:
                res = types.SimpleNamespace(status="(loaded)", system_xml=str(bdir / "system.xml"),
                                            topology_pdb=str(bdir / "topology.pdb"))
            rec["status"] = res.status
            rec["build_seconds"] = round(time.time() - t0, 1)
            pdb = app.PDBFile(res.topology_pdb)
            xyz = np.asarray(pdb.positions.value_in_unit(unit.nanometer))
            rec["n_atoms"] = len(xyz)
            rec["xyz_sha"] = hashlib.sha256(np.round(xyz, 3).tobytes()).hexdigest()[:16]
            rec["n_water"] = sum(1 for r in pdb.topology.residues() if r.name == "HOH")
            atoms, nb = _atoms(pdb.topology), _bonded(pdb.topology)
            man = json.loads((bdir / "build_manifest.json").read_text(encoding="utf-8")) if (bdir / "build_manifest.json").exists() else {}
            rec["box_nm"] = man.get("membrane", {}).get("box_nm")
            bv = pdb.topology.getPeriodicBoxVectors().value_in_unit(unit.nanometer)
            rec["structure"] = structure_stats(pdb.topology, xyz, np.array([bv[0][0], bv[1][1], bv[2][2]]))
            # D-115: what the build-stage declash saw BEFORE removing (water–water and ion–water), from the gate
            wg = [g for g in (man.get("gates") or {}).get("gates", []) if g.get("name") == "water overlaps"]
            rec["structure"]["declash_gate"] = ({"status": wg[0]["status"], **(wg[0].get("evidence") or {})} if wg else None)
            print(f"build{k} STRUCT " + json.dumps(rec["structure"], ensure_ascii=False), flush=True)
            rec["runs"] = []
            for s in seeds:
                r = run_one(res, atoms, nb, min_iter=500, seed=s, steps=a.steps, unit=unit)
                rec["runs"].append(r)
                print(f"build{k} sha={rec['xyz_sha']} min=500 seed={s}: fmax_min={r['fmax_after_min']} "
                      f"n>1e3={r['n_atoms_f_gt_1e3']} nan_at={r['nan_at_step']} top={r['top_force_after_min'][0]}", flush=True)
            r = run_one(res, atoms, nb, min_iter=a.long_min, seed=seeds[0], steps=a.steps, unit=unit)
            rec["runs"].append(r)
            print(f"build{k} sha={rec['xyz_sha']} min={a.long_min} seed={seeds[0]}: fmax_min={r['fmax_after_min']} "
                  f"nan_at={r['nan_at_step']}", flush=True)
        except Exception as exc:  # noqa: BLE001
            rec["error"] = traceback.format_exc()[-2000:]
            print(f"build{k}: ERROR {exc}", flush=True)
        report["builds"].append(rec)
        (out / "diag.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    report["finished"] = True          # D-136: written only when every requested build was attempted
    (out / "diag.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    runs = [r for b in report["builds"] for r in b.get("runs", [])]
    nan = [r for r in runs if r["nan_at_step"]]
    shas = sorted({b.get("xyz_sha") for b in report["builds"] if b.get("xyz_sha")})
    print(f"SUMMARY from={a.from_builds or 'here'} platforms={report.get('platforms')} threads={report['platform_threads']} builds={len(report['builds'])} distinct_starts={len(shas)} "
          f"runs={len(runs)} nan={len(nan)} nan_500={sum(1 for r in nan if r['min_iter'] == 500)} "
          f"nan_long={sum(1 for r in nan if r['min_iter'] != 500)}", flush=True)
    for r in nan:
        print("NAN", json.dumps({k: r.get(k) for k in ("min_iter", "seed", "nan_at_step", "fmax_after_min", "error",
                                                         "top_force_after_min", "before_nan")}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
