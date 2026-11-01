"""Binding strength: SMD pulling → umbrella windows → PMF (WHAM/MBAR) → ΔPMF and ΔG° estimate.

Collective variable: distance between the centre of mass of an *anchor* group (pocket Cα atoms
within 8 Å of the ligand) and the ligand heavy atoms, with periodic boundary conditions.

Teaching-level caveats written into every result:
* a 1-D COM-distance PMF does not include orientational/conformational restraint corrections, so
  ΔG° from it is an estimate (typically within a few kJ/mol of the trend, not an absolute number);
* SMD work is path- and speed-dependent (irreversible); only the PMF is a free-energy profile;
* short windows ⇒ check the overlap and half-split convergence figures before trusting the PMF.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable

import numpy as np

from ..util import atomic_write_json, load_json, now_iso, DecisionLog
from ..analysis.plots import PALETTE, _mpl, _save
from .windows import plan_windows, KB_KJ_MOL_K
from .pmf import pmf_from_windows

V0_NM3 = 1.66053906660  # standard-state volume per molecule (1 M) in nm³


@dataclass
class BindingConfig:
    pull_distance_nm: float = 1.5          # how far beyond the bound distance to pull
    pull_velocity_nm_per_ps: float = 0.01  # 10 m/s — fast teaching default; research: 0.001–0.005
    k_pull: float = 1000.0                 # kJ/mol/nm² SMD spring
    k_umbrella: float = 1000.0             # kJ/mol/nm² window spring
    target_overlap: float = 0.25
    window_equil_ps: float = 10.0
    window_prod_ps: float = 50.0
    sample_every_steps: int = 50
    timestep_fs: float = 2.0
    temperature_k: float = 300.0
    friction_per_ps: float = 1.0
    backbone_restraint_scale: float = 0.1  # × 1000 kJ/mol/nm² from the build restraints
    pocket_cutoff_nm: float = 0.8
    max_windows: int = 40
    box_margin_nm: float = 1.0             # d_max + ligand radius + margin must fit in half the box
    seed: int = 2026

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- geometry
def group_com(xyz: np.ndarray, idx: np.ndarray, masses: np.ndarray) -> np.ndarray:
    m = masses[idx]
    return (xyz[idx] * m[:, None]).sum(0) / m.sum()


def min_image(d: np.ndarray, box: np.ndarray) -> np.ndarray:
    """Minimum-image vector for a (possibly triclinic, reduced-form) OpenMM box (rows = box vectors, nm)."""
    d = d.copy()
    for k in (2, 1, 0):
        d -= box[k] * np.round(d[k] / box[k][k])
    return d


def cv_distance(xyz: np.ndarray, box: np.ndarray, anchor: np.ndarray, ligand: np.ndarray, masses: np.ndarray) -> float:
    return float(np.linalg.norm(min_image(group_com(xyz, ligand, masses) - group_com(xyz, anchor, masses), box)))


# --------------------------------------------------------------------------- system setup
def select_groups(topology, positions_nm: np.ndarray, *, ligand_resname: str | None = None,
                  ligand_indices: list[int] | None = None, anchor_indices: list[int] | None = None,
                  pocket_cutoff_nm: float = 0.8, exclude_indices=None) -> tuple[np.ndarray, np.ndarray, dict]:
    atoms = list(topology.atoms())
    excl_res = {atoms[i].residue.index for i in (exclude_indices or [])}   # other ligands (e.g. peptides) never anchor
    if ligand_indices is None:
        ligand_indices = [a.index for a in atoms if a.residue.name == ligand_resname and a.element is not None
                          and a.element.symbol != "H"]
    lig = np.array(ligand_indices, dtype=int)
    if not len(lig):
        raise ValueError(f"找不到配體 {ligand_resname}")
    note = ""
    if anchor_indices is None:
        lig_res = {atoms[i].residue.index for i in lig}   # peptide ligands have their own CA atoms
        ca = np.array([a.index for a in atoms if a.name == "CA" and a.residue.name not in {ligand_resname, "CA"}
                       and a.residue.index not in lig_res and a.residue.index not in excl_res
                       and a.element is not None and a.element.symbol == "C"], dtype=int)
        cutoff = pocket_cutoff_nm
        sel = np.array([], dtype=int)
        while len(sel) < 4 and cutoff <= 1.6 and len(ca):
            d = np.min(np.linalg.norm(positions_nm[ca][:, None, :] - positions_nm[lig][None, :, :], axis=2), axis=1)
            sel = ca[d <= cutoff]
            cutoff += 0.2
        anchor_indices = sel.tolist()
        note = f"口袋 anchor：配體 {cutoff - 0.2:.1f} nm 內的 {len(sel)} 個 Cα"
    anc = np.array(anchor_indices, dtype=int)
    if not len(anc):
        raise ValueError("找不到 anchor 原子")
    return anc, lig, {"anchor_atoms": anc.tolist(), "ligand_atoms": lig.tolist(), "note": note}


def build_pulling_system(system, positions_nm: np.ndarray, anchor: np.ndarray, ligand: np.ndarray):
    """Add the CV bias; free the ligand from build restraints; re-reference backbone restraints; NVT."""
    import openmm as mm
    for i in range(system.getNumForces()):
        f = system.getForce(i)
        if isinstance(f, mm.MonteCarloBarostat):
            f.setFrequency(0)
        if isinstance(f, mm.CustomExternalForce) and f.getName() == "msw_position_restraints":
            lig_set = set(int(x) for x in ligand)
            for p in range(f.getNumParticles()):
                idx, prm = f.getParticleParameters(p)
                k = 0.0 if idx in lig_set else prm[0]
                x, y, z = positions_nm[idx]
                f.setParticleParameters(p, idx, [k, x, y, z])
    bias = mm.CustomCentroidBondForce(2, "0.5*k_cv*(distance(g1,g2)-r0_cv)^2")
    bias.addGlobalParameter("k_cv", 0.0)
    bias.addGlobalParameter("r0_cv", 0.0)
    bias.addGroup([int(i) for i in anchor])
    bias.addGroup([int(i) for i in ligand])
    bias.addBond([0, 1], [])
    bias.setUsesPeriodicBoundaryConditions(True)
    bias.setName("md20_cv_bias")
    system.addForce(bias)
    return system


@dataclass
class BindingResult:
    status: str
    d_bound_nm: float = 0.0
    smd: dict = field(default_factory=dict)
    windows: list = field(default_factory=list)
    pmf: dict = field(default_factory=dict)
    delta_pmf_kj_mol: float | None = None
    delta_pmf_err_kj_mol: float | None = None
    dG_err_kj_mol: float | None = None
    dG_standard_kj_mol: float | None = None
    dG_standard_kcal_mol: float | None = None
    figures: dict = field(default_factory=dict)
    caveats: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _make_context(system, positions, platform_name, properties, cfg: BindingConfig, seed: int):
    import openmm as mm
    from openmm import unit
    integ = mm.LangevinMiddleIntegrator(cfg.temperature_k * unit.kelvin, cfg.friction_per_ps / unit.picosecond,
                                        cfg.timestep_fs * unit.femtoseconds)
    integ.setRandomNumberSeed(int(seed))
    ctx = mm.Context(system, integ, mm.Platform.getPlatformByName(platform_name), properties or {})
    return ctx, integ


def radial_pmf(pres, temperature_k: float) -> dict:
    """Jacobian-corrected radial PMF, well depth and radial-integration ΔG° (1 M)."""
    grid, W = np.asarray(pres.grid_nm), np.asarray(pres.pmf_kj_mol)
    kT = KB_KJ_MOL_K * temperature_k
    ok = np.isfinite(W) & (grid > 0)
    g, W_raw = grid[ok], W[ok]
    # Jacobian (volume-element) correction for a 3-D distance CV: the raw PMF contains −2kT·ln r,
    # which makes large separations look favourable.  w(r) = W(r) + 2kT·ln r is the radial PMF.
    Wv = W_raw + 2.0 * kT * np.log(g)
    Wv = Wv - np.min(Wv)
    err = np.asarray(pres.err_kj_mol)[ok] if pres.err_kj_mol is not None else None
    tail = max(3, len(Wv) // 10)
    w_bulk = float(np.mean(Wv[-tail:]))
    i_min = int(np.argmin(Wv))
    dpmf = round(w_bulk - float(Wv[i_min]), 3)
    beyond = np.where(Wv[i_min:] >= w_bulk - 0.5 * kT)[0]
    r_cut = float(g[i_min + beyond[0]] if len(beyond) else g[-1])
    bound = g <= r_cut
    integrand = 4 * np.pi * g[bound] ** 2 * np.exp(-(Wv[bound] - w_bulk) / kT)
    k_eq = float(np.trapezoid(integrand, g[bound])) if hasattr(np, "trapezoid") else float(np.trapz(integrand, g[bound]))
    dG = round(-kT * math.log(k_eq / V0_NM3), 3) if k_eq > 0 else None
    from .multi import delta_pmf_error
    return {"grid": g, "W": Wv, "W_raw": W_raw - np.min(W_raw), "err": err, "w_bulk": w_bulk, "r_min": float(g[i_min]),
            "r_cut": r_cut, "delta_pmf": dpmf, "delta_pmf_err": delta_pmf_error(g, err, i_min, tail), "dG": dG}


def bootstrap_binding_sigma(grid_nm, boot_pmfs, temperature_k: float, *, min_ok: int = 10) -> dict:
    """σ of ΔPMF and ΔG° from the bootstrap PMF replicates: each replicate goes through the same Jacobian
    correction / well / radial integration as the estimate, so the SD is that of the derived quantity."""
    from types import SimpleNamespace
    out = {"delta_pmf_sd": None, "dG_sd": None, "n": 0}
    if boot_pmfs is None or len(boot_pmfs) == 0:
        return out
    dp, dg = [], []
    for curve in np.asarray(boot_pmfs, dtype=float):
        try:
            r = radial_pmf(SimpleNamespace(grid_nm=grid_nm, pmf_kj_mol=curve, err_kj_mol=None), temperature_k)
        except Exception:  # noqa: BLE001
            continue
        if r["delta_pmf"] is not None and np.isfinite(r["delta_pmf"]):
            dp.append(r["delta_pmf"])
        if r["dG"] is not None and np.isfinite(r["dG"]):
            dg.append(r["dG"])
    out["n"] = len(dp)
    if len(dp) >= min_ok:
        out["delta_pmf_sd"] = round(float(np.std(dp, ddof=1)), 3)
    if len(dg) >= min_ok:
        out["dG_sd"] = round(float(np.std(dg, ddof=1)), 3)
    return out


def _unwrap_near(xyz: np.ndarray, ref: np.ndarray, box: np.ndarray) -> np.ndarray:
    """Images of `xyz` closest to `ref` (orthorhombic/triclinic via min_image on each atom)."""
    return np.asarray(ref) + np.array([min_image(np.asarray(x) - ref, box) for x in xyz])


def _state_xyz_box(ctx):
    st = ctx.getState(getPositions=True)
    xyz = st.getPositions(asNumpy=True)._value
    box = np.array([[v.x, v.y, v.z] for v in st.getPeriodicBoxVectors()])
    return xyz, box


def run_binding(system_xml: Path | str, topology_pdb: Path | str, start_state_xml: Path | str | None, out_dir: Path | str, *,
                ligand_resname: str | None = None, ligand_indices: list[int] | None = None,
                anchor_indices: list[int] | None = None, config: BindingConfig | None = None,
                platform_name: str = "CPU", platform_properties: dict | None = None,
                decisions: DecisionLog | None = None, should_pause: Callable[[], str | None] | None = None,
                progress_cb: Callable[[dict], None] | None = None, positions_override=None,
                other_ligand_indices: dict[str, list[int]] | None = None) -> BindingResult:
    import openmm as mm
    from openmm import app, unit, XmlSerializer
    cfg = config or BindingConfig()
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    wdir = out / "windows"; wdir.mkdir(exist_ok=True)
    system = XmlSerializer.deserialize(Path(system_xml).read_text(encoding="utf-8"))
    pdb = app.PDBFile(str(topology_pdb))
    top = pdb.topology
    if start_state_xml:
        st = XmlSerializer.deserialize(Path(start_state_xml).read_text(encoding="utf-8"))
        pos = st.getPositions(asNumpy=True)._value
        box_vecs = st.getPeriodicBoxVectors()
    else:
        pos = np.asarray(positions_override if positions_override is not None else pdb.getPositions(asNumpy=True)._value)
        box_vecs = top.getPeriodicBoxVectors() or system.getDefaultPeriodicBoxVectors()
    masses = np.array([system.getParticleMass(i).value_in_unit(unit.dalton) for i in range(system.getNumParticles())])
    anchor, ligand, gi = select_groups(top, pos, ligand_resname=ligand_resname, ligand_indices=ligand_indices,
                                       anchor_indices=anchor_indices, pocket_cutoff_nm=cfg.pocket_cutoff_nm,
                                       exclude_indices=[i for v in (other_ligand_indices or {}).values() for i in v])
    system = build_pulling_system(system, pos, anchor, ligand)
    manifest = load_json(out / "binding_manifest.json", {})
    manifest.update({"config": cfg.to_dict(), "groups": gi, "platform": platform_name, "updated_at": now_iso()})
    if decisions:
        decisions.record("binding.setup", "CV", "COM distance anchor–ligand", gi["note"] or "使用者指定 anchor 原子。",
                         k_pull=cfg.k_pull, v=cfg.pull_velocity_nm_per_ps)
    # ------------------------------------------------------------------ SMD
    smd_file = out / "smd.json"
    smd = load_json(smd_file, {})
    ctx, integ = _make_context(system, pos, platform_name, platform_properties, cfg, cfg.seed)
    ctx.setPeriodicBoxVectors(*box_vecs)
    ctx.setPositions(pos * unit.nanometer)
    if "msw_restraint_scale" in ctx.getParameters():
        ctx.setParameter("msw_restraint_scale", cfg.backbone_restraint_scale)
    if "msw_fb_scale" in ctx.getParameters():
        ctx.setParameter("msw_fb_scale", 0.0)   # multi-ligand flat-bottom restraints are off for free-energy work
    xyz, box = _state_xyz_box(ctx)
    d0 = cv_distance(xyz, box, anchor, ligand, masses)
    lig_xyz = xyz[ligand]
    lig_radius = float(np.max(np.linalg.norm(lig_xyz - lig_xyz.mean(0), axis=1))) if len(ligand) > 1 else 0.0
    half_box = 0.5 * float(min(np.linalg.norm(box, axis=1)))
    need = d0 + cfg.pull_distance_nm + lig_radius + cfg.box_margin_nm
    manifest["box_check"] = {"d0_nm": d0, "pull_nm": cfg.pull_distance_nm, "ligand_radius_nm": lig_radius,
                             "margin_nm": cfg.box_margin_nm, "need_half_box_nm": need, "half_box_nm": half_box}
    if need > half_box:
        msg = (f"水盒太小：拉離終點 {d0 + cfg.pull_distance_nm:.2f} nm + 配體半徑 {lig_radius:.2f} + 安全距離 "
               f"{cfg.box_margin_nm:.1f} = {need:.2f} nm，超過盒子半長 {half_box:.2f} nm；配體會接近週期影像，PMF 不可信。"
               f"請以較大 padding 重建（啟用結合計算時工作流程會自動提高），或縮短 pull_distance。")
        manifest.update({"status": "NEEDS_HUMAN", "reason": msg})
        atomic_write_json(json.loads(json.dumps(manifest, default=_np_default)), out / "binding_manifest.json")
        if decisions:
            decisions.record("binding.box", "box size", "NEEDS_HUMAN", msg, kind="human")
        return BindingResult(status="NEEDS_HUMAN", d_bound_nm=d0, caveats=[msg])
    if other_ligand_indices:
        # WP9: in a shared pocket, the exit path of the pulled ligand must be free of the other ligands
        from .multi import pull_path_blockers
        others = {k: _unwrap_near(xyz[np.array(v, dtype=int)], lig_xyz.mean(0), box) for k, v in other_ligand_indices.items() if v}
        acom = (masses[anchor, None] * xyz[anchor]).sum(0) / masses[anchor].sum()
        acom = _unwrap_near(acom[None], lig_xyz.mean(0), box)[0]
        blk = pull_path_blockers(acom, lig_xyz, others, pull_distance_nm=cfg.pull_distance_nm)
        manifest["path_check"] = {"blockers": blk, "others": sorted(others)}
        if blk:
            msg = ("拉離路徑被其他配體擋住：" + "；".join(f"{b['ligand']} 有 {b.get('n_atoms_in_path', '?')} 個重原子在拉離圓柱內"
                                                      f"（沿路徑 {b.get('nearest_along_path_nm', '?')} nm）" for b in blk)
                   + "。穿過另一個配體拉離得到的是推開它的功，不是本配體的結合自由能。")
            manifest.update({"status": "NEEDS_HUMAN", "reason": msg})
            atomic_write_json(json.loads(json.dumps(manifest, default=_np_default)), out / "binding_manifest.json")
            if decisions:
                decisions.record("binding.path", "multi-ligand exit path", "NEEDS_HUMAN", msg, kind="human")
            return BindingResult(status="NEEDS_HUMAN", d_bound_nm=d0, caveats=[msg + "選項：先拉外側配體／只算單獨結合（docked_single）／指定 anchor_indices 改變方向"])
        if decisions:
            decisions.record("binding.path", "multi-ligand exit path", "clear",
                             f"其他配體（{', '.join(sorted(others))}）不在拉離圓柱內；拉離期間它們不加限制（可自由移動），結果含其重排。")
    plan = plan_windows(d0, d0 + cfg.pull_distance_nm, force_constant_kj_mol_nm2=cfg.k_umbrella,
                        temperature_k=cfg.temperature_k, target_overlap=cfg.target_overlap, max_windows=cfg.max_windows)
    if smd.get("status") != "PASS":
        if not start_state_xml:
            mm.LocalEnergyMinimizer.minimize(ctx, maxIterations=500)
        ctx.setVelocitiesToTemperature(cfg.temperature_k * unit.kelvin, cfg.seed)
        ctx.setParameter("k_cv", cfg.k_pull)
        ctx.setParameter("r0_cv", d0)
        integ.step(int(2000 / cfg.timestep_fs))  # 2 ps settle at the bound distance
        dt_ps = cfg.timestep_fs / 1000.0
        n_steps = int(math.ceil(cfg.pull_distance_nm / cfg.pull_velocity_nm_per_ps / dt_ps))
        rec_every = max(1, int(0.2 / dt_ps))  # every 0.2 ps
        rows, work = [], 0.0
        r0 = d0
        next_w = 0
        saved = {}
        for s in range(0, n_steps, rec_every):
            nstep = min(rec_every, n_steps - s)
            dr = cfg.pull_velocity_nm_per_ps * dt_ps * nstep
            xyz, box = _state_xyz_box(ctx)
            d = cv_distance(xyz, box, anchor, ligand, masses)
            force = cfg.k_pull * (r0 - d)
            work += force * dr
            rows.append((s * dt_ps, r0, d, force, work))
            while next_w < len(plan.centers_nm) and d >= plan.centers_nm[next_w]:
                path = wdir / f"w{next_w:03d}_start.xml"
                state = ctx.getState(getPositions=True, getVelocities=True)
                path.write_text(XmlSerializer.serialize(state), encoding="utf-8")
                saved[next_w] = {"path": str(path), "cv": d}
                next_w += 1
            r0 += dr
            ctx.setParameter("r0_cv", r0)
            integ.step(nstep)
            if progress_cb and len(rows) % 50 == 0:
                progress_cb({"stage": "smd", "r0": r0, "d": d, "force": force, "work": work})
        # windows the ligand never reached (lags behind the spring): seed from the last frame
        xyz, box = _state_xyz_box(ctx)
        for w in range(next_w, len(plan.centers_nm)):
            path = wdir / f"w{w:03d}_start.xml"
            path.write_text(XmlSerializer.serialize(ctx.getState(getPositions=True, getVelocities=True)), encoding="utf-8")
            saved[w] = {"path": str(path), "cv": cv_distance(xyz, box, anchor, ligand, masses), "fallback": True}
        arr = np.array(rows)
        np.savetxt(out / "smd.tsv", arr, header="time_ps\tr0_nm\td_nm\tforce_kj_mol_nm\twork_kj_mol", delimiter="\t")
        smd = {"status": "PASS", "d0_nm": d0, "n_steps": n_steps, "max_force_kj_mol_nm": float(arr[:, 3].max()),
               "final_work_kj_mol": float(arr[-1, 4]), "window_starts": {str(k): v for k, v in saved.items()},
               "plan": plan.to_dict(), "sealed_at": now_iso()}
        atomic_write_json(smd, smd_file)
    del ctx, integ
    # ------------------------------------------------------------------ umbrella windows
    eq_steps = int(cfg.window_equil_ps * 1000 / cfg.timestep_fs)
    pr_steps = int(cfg.window_prod_ps * 1000 / cfg.timestep_fs)
    samples: dict[float, np.ndarray] = {}
    finals: dict[float, str] = {}

    def wfile(c: float, kind: str) -> Path:
        return wdir / f"w_{c:.4f}_{kind}"

    def run_window(c: float, start_xml: str, seed: int) -> bool:
        npy = wfile(c, "cv.npy")
        if npy.is_file():
            samples[c] = np.load(npy)
            finals[c] = str(wfile(c, "final.xml"))
            return True
        if should_pause is not None and (reason := should_pause()):
            manifest.update({"status": "PAUSED", "reason": reason, "windows_done": len(samples)})
            atomic_write_json(manifest, out / "binding_manifest.json")
            return False
        ctx, integ = _make_context(system, pos, platform_name, platform_properties, cfg, seed)
        ctx.setState(XmlSerializer.deserialize(Path(start_xml).read_text(encoding="utf-8")))
        if "msw_restraint_scale" in ctx.getParameters():
            ctx.setParameter("msw_restraint_scale", cfg.backbone_restraint_scale)
        if "msw_fb_scale" in ctx.getParameters():
            ctx.setParameter("msw_fb_scale", 0.0)
        ctx.setParameter("k_cv", cfg.k_umbrella)
        ctx.setParameter("r0_cv", float(c))
        integ.step(eq_steps)
        vals = []
        for _ in range(0, pr_steps, cfg.sample_every_steps):
            integ.step(cfg.sample_every_steps)
            xyz, box = _state_xyz_box(ctx)
            vals.append(cv_distance(xyz, box, anchor, ligand, masses))
        arr = np.asarray(vals)
        if not np.all(np.isfinite(arr)):
            raise RuntimeError(f"window {c:.3f} nm 出現 NaN")
        wfile(c, "final.xml").write_text(XmlSerializer.serialize(ctx.getState(getPositions=True, getVelocities=True)), encoding="utf-8")
        np.save(npy, arr)
        samples[c], finals[c] = arr, str(wfile(c, "final.xml"))
        del ctx, integ
        if progress_cb:
            progress_cb({"stage": "umbrella", "window": len(samples), "n": len(centers), "mean": float(arr.mean())})
        return True

    centers = [float(c) for c in smd["plan"]["centers_nm"]]
    for w, c in enumerate(centers):
        if not run_window(c, smd["window_starts"][str(w)]["path"], cfg.seed + 17 * (w + 1)):
            return BindingResult(status="PAUSED", d_bound_nm=d0, smd=smd, caveats=[manifest.get("reason", "")])
    # automatic refinement: add windows where neighbours do not overlap (max 2 rounds, ≤ 12 extra windows)
    from .pmf import umbrella_quality
    added = []
    for rnd in range(2):
        q, _, _ = umbrella_quality(samples, target_overlap=cfg.target_overlap * 0.6)
        new = [float(round(c, 4)) for c in (q.get("insert_centers_nm") or []) if float(round(c, 4)) not in samples][:6]
        if not new:
            break
        for c in new:
            near = min(finals, key=lambda x: abs(x - c))
            if not run_window(c, finals[near], cfg.seed + 7919 + len(samples)):
                return BindingResult(status="PAUSED", d_bound_nm=d0, smd=smd, caveats=[manifest.get("reason", "")])
            added.append(c)
            centers.append(c)
    if added and decisions:
        decisions.record("binding.windows", "auto-refine", [round(c, 3) for c in added],
                         "相鄰 window 的分佈重疊不足（PMF 會斷裂）；自動在缺口中點補 window，起始結構取最近 window 的末態。")
    centers = sorted(samples)
    # ------------------------------------------------------------------ PMF + ΔG
    pres = pmf_from_windows(samples, force_constant_kj_mol_nm2=cfg.k_umbrella, temperature_k=cfg.temperature_k,
                            out_dir=out, n_bootstrap=100)
    res = BindingResult(status="PASS", d_bound_nm=d0, smd=smd, windows=[{"center_nm": c, "n": int(len(samples[c])),
                        "mean_nm": float(samples[c].mean()), "sd_nm": float(samples[c].std()), "added": c in added} for c in centers])
    rp = radial_pmf(pres, cfg.temperature_k)
    g, Wv, err = rp["grid"], rp["W"], rp["err"]
    res.delta_pmf_kj_mol, res.dG_standard_kj_mol = rp["delta_pmf"], rp["dG"]
    bs = bootstrap_binding_sigma(pres.grid_nm, getattr(pres, "boot_pmfs", None), cfg.temperature_k)
    # bootstrap SD of the derived quantities; the point-wise approximation is only a fallback
    res.delta_pmf_err_kj_mol = bs["delta_pmf_sd"] if bs["delta_pmf_sd"] is not None else rp["delta_pmf_err"]
    res.dG_err_kj_mol = bs["dG_sd"]
    if res.dG_standard_kj_mol is not None:
        res.dG_standard_kcal_mol = round(res.dG_standard_kj_mol / 4.184, 3)
    # half-split convergence: first vs second half of every window
    half = {}
    try:
        h1 = {c: v[: len(v) // 2] for c, v in samples.items()}
        h2 = {c: v[len(v) // 2:] for c, v in samples.items()}
        a = radial_pmf(pmf_from_windows(h1, force_constant_kj_mol_nm2=cfg.k_umbrella, temperature_k=cfg.temperature_k,
                                        n_bootstrap=0), cfg.temperature_k)
        b = radial_pmf(pmf_from_windows(h2, force_constant_kj_mol_nm2=cfg.k_umbrella, temperature_k=cfg.temperature_k,
                                        n_bootstrap=0), cfg.temperature_k)
        half = {"first_half_dpmf": a["delta_pmf"], "second_half_dpmf": b["delta_pmf"],
                "diff_kj_mol": round(abs(a["delta_pmf"] - b["delta_pmf"]), 3)}
    except Exception as exc:  # noqa: BLE001
        half = {"error": str(exc)}
    res.pmf = {"method": pres.method, "converged": pres.converged, "quality": pres.quality,
               "bound_cutoff_nm": rp["r_cut"], "w_bulk_kj_mol": rp["w_bulk"], "r_min_nm": rp["r_min"],
               "jacobian_corrected": True, "half_split": half,
               "grid_nm": g.tolist(), "pmf_radial_kj_mol": Wv.tolist(), "pmf_raw_kj_mol": rp["W_raw"].tolist()}
    res.figures = dict(pres.figures)
    from ..analysis.plots import plot_pmf
    res.figures["pmf"] = plot_pmf(g, Wv, err, out / "pmf")
    res.figures["smd"] = _plot_smd(out / "smd.tsv", out / "smd_force_work")
    res.caveats = [
        f"拉離與每個 window 期間，蛋白骨架施加 {cfg.backbone_restraint_scale * 1000:.0f} kJ/mol/nm² 位置限制"
        f"（避免整顆蛋白被拖走）；PMF 不包含蛋白構形重排的自由能。",
        "ΔPMF 是一維 COM 距離 PMF 的井深，不等於實驗結合自由能。",
        "PMF 已做 Jacobian 校正（+2kT·ln r）；未校正的一維距離 PMF 會因 r² 體積項而在遠距離偏低。",
        "ΔG° 以徑向積分與 1 M 標準態估算，未包含方向／構形約束校正；適合比較配體間趨勢。",
        "SMD 的功與拉伸速度有關（不可逆），只有 PMF 是自由能剖面。",
    ]
    if not res.pmf["quality"].get("graph_connected", True) or not pres.converged:
        res.caveats.insert(1, "PMF 未收斂或 window overlap 不足（見直方圖）；不輸出 ΔG°，只保留 ΔPMF 作定性參考。")
        res.dG_standard_kj_mol = res.dG_standard_kcal_mol = None
        res.dG_err_kj_mol = None
        res.pmf["dG_withheld"] = "not converged"
    manifest.update({"status": "PASS", "result": res.to_dict()})
    atomic_write_json(json.loads(json.dumps(manifest, default=_np_default)), out / "binding_manifest.json")
    if decisions:
        decisions.record("binding.result", "ΔPMF / ΔG°", f"{res.delta_pmf_kj_mol} / {res.dG_standard_kj_mol} kJ/mol",
                         "；".join(res.caveats[:2]))
    return res


def _np_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def _plot_smd(tsv: Path, out_base: Path) -> dict:
    plt = _mpl()
    a = np.loadtxt(tsv, delimiter="\t")
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 4.4), sharex=True)
    axes[0].plot(a[:, 2], a[:, 3], color=PALETTE[0])
    axes[0].set_ylabel("Pulling force (kJ/mol/nm)")
    axes[1].plot(a[:, 2], a[:, 4], color=PALETTE[1])
    axes[1].set_ylabel("Work (kJ/mol)"); axes[1].set_xlabel("CV distance (nm)")
    i = int(np.argmax(a[:, 3]))
    axes[0].text(a[i, 2], a[i, 3], f"  rupture force {a[i, 3]:.0f}", fontsize=7, color="#52514e")
    axes[0].set_title("SMD: force and accumulated work vs. distance (irreversible, speed-dependent)", loc="left", fontsize=10)
    return _save(fig, out_base)
