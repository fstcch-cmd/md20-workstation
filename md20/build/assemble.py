"""Assemble receptor + ligand(s) in memory with OpenMM Modeller — no intermediate PDB round-trips.

Output of a successful build (case/build/):
    topology.pdb          full solvated system (coordinate carrier for the engine)
    system.xml            serialized OpenMM System incl. position restraints with
                          global parameter `msw_restraint_scale` (0 = off)
    build_manifest.json   composition, charges, box, force fields, gates, hashes
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
import numpy as np

MIN_PADDING_NM = 0.6      # below this the protein sees its own image inside the 1.0 nm cutoff — never allowed

from ..util import now_iso, DecisionLog, atomic_write_json, sha256_file
from .gates import Gate, GateReport, PASS, AUTO_FIXED, NEEDS_HUMAN
from .ligand import LigandRecord, parameter_ladder

AMBER_PROTEIN = ("amber14/protein.ff14SB.xml", "amber14/tip3p.xml")
AMBER_RNA_DNA = ("amber14/RNA.OL3.xml", "amber14/DNA.OL15.xml")


@dataclass
class BuildResult:
    status: str
    system_xml: str = ""
    topology_pdb: str = ""
    n_atoms: int = 0
    n_protein_atoms: int = 0
    n_ligand_atoms: int = 0
    n_waters: int = 0
    n_ions: dict = field(default_factory=dict)
    box_nm: list = field(default_factory=list)
    solvent: str = "explicit"
    total_charge: float | None = None
    forcefields: list = field(default_factory=list)
    ligands: list = field(default_factory=list)
    restraints: dict = field(default_factory=dict)
    gates: dict = field(default_factory=dict)
    hashes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _ligand_openmm(rec: LigandRecord):
    """RDKit SDF → (openmm Topology, positions nm, openff Molecule) with residue name L01."""
    from rdkit import Chem
    from openff.toolkit import Molecule
    from openmm import unit
    mol = Chem.SDMolSupplier(rec.sdf_path, removeHs=False)[0]
    offmol = Molecule.from_rdkit(mol, allow_undefined_stereo=True)
    offmol.name = rec.resname
    top = offmol.to_topology().to_openmm()
    for res in top.residues():
        res.name = rec.resname
    for chain in top.chains():
        chain.id = rec.name[-1] if rec.name[-1].isalpha() else "L"
    pos = mol.GetConformer().GetPositions() / 10.0
    return top, pos * unit.nanometer, offmol


RESTRAINT_GROUPS = ("backbone", "sidechain", "ligand")
_PROTEIN_RESNAMES = {"ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE", "LEU", "LYS", "MET", "PHE",
                     "PRO", "SER", "THR", "TRP", "TYR", "VAL", "HID", "HIE", "HIP", "HSD", "HSE", "HSP", "CYX", "CYM",
                     "ASH", "GLH", "LYN", "ARN", "SEP", "TPO", "PTR", "MSE", "ACE", "NME", "NMA"}
_BACKBONE = {"CA", "C", "N", "O", "OXT"}


def add_position_restraints(system, topology, positions, *, k_protein=1000.0, k_sidechain=1000.0, k_ligand=1000.0,
                            ligand_resnames: set[str] = frozenset(), ligand_atom_indices: set[int] = frozenset()) -> dict:
    """Grouped harmonic position restraints (consultation §1 Q1, D-23).

    One force ``msw_position_restraints`` with per-particle ``k, x0, y0, z0, grp`` (grp 0 = backbone N/CA/C/O,
    1 = protein side-chain heavy atoms, 2 = ligand heavy atoms); energy
    ``0.5·msw_restraint_scale·msw_rs_<grp>·k·d²``.  Every ``msw_rs_*`` defaults to 1.0, so a protocol without
    ``restraint_groups`` behaves like the old single schedule.  The ligand k (1000) is no longer below the protein's:
    minimization is when a docked pose drifts most easily."""
    import openmm as mm
    from openmm import unit
    force = mm.CustomExternalForce(
        "0.5*msw_restraint_scale*k*(delta(grp)*msw_rs_backbone + delta(grp-1)*msw_rs_sidechain"
        " + delta(grp-2)*msw_rs_ligand)*periodicdistance(x,y,z,x0,y0,z0)^2")
    force.addGlobalParameter("msw_restraint_scale", 1.0)
    for g in RESTRAINT_GROUPS:
        force.addGlobalParameter(f"msw_rs_{g}", 1.0)
    for p in ("k", "x0", "y0", "z0", "grp"):
        force.addPerParticleParameter(p)
    counts = {g: 0 for g in RESTRAINT_GROUPS}
    pos = positions.value_in_unit(unit.nanometer)
    for atom in topology.atoms():
        if atom.element is None or atom.element.symbol == "H":
            continue
        rn = atom.residue.name
        if rn in ligand_resnames or atom.index in ligand_atom_indices:
            grp, k = 2, k_ligand
        elif rn in _PROTEIN_RESNAMES:
            grp, k = (0, k_protein) if atom.name in _BACKBONE else (1, k_sidechain)
        else:
            continue          # water, ions, metals (their own bonded model), cofactors
        counts[RESTRAINT_GROUPS[grp]] += 1
        x, y, z = pos[atom.index]
        force.addParticle(atom.index, [k, x, y, z, float(grp)])
    force.setName("msw_position_restraints")
    system.addForce(force)
    return {"type": "CustomExternalForce", "global_parameter": "msw_restraint_scale",
            "group_parameters": {g: f"msw_rs_{g}" for g in RESTRAINT_GROUPS},
            "protein_backbone_atoms": counts["backbone"], "protein_sidechain_atoms": counts["sidechain"],
            "ligand_heavy_atoms": counts["ligand"], "k_protein_kj_mol_nm2": k_protein,
            "k_sidechain_kj_mol_nm2": k_sidechain, "k_ligand_kj_mol_nm2": k_ligand}


def add_gbn2_force(system, topology, *, solvent_dielectric: float = 78.5, solute_dielectric: float = 1.0) -> dict:
    """Implicit solvent (consultation §1 Q6): OpenMM's GBn2 (Nguyen, Roe & Simmerling 2013) with mbondi3 radii assigned
    by element and bonding (`GBSAGBn2Force.getStandardParameters`), so OpenFF/GAFF ligands get parameters too —
    `implicit/gbn2.xml` only covers the Amber protein residue templates.  Charges come from the NonbondedForce."""
    import openmm as mm
    from openmm.app.internal.customgbforces import GBSAGBn2Force
    nb = next(f for f in system.getForces() if isinstance(f, mm.NonbondedForce))
    gb = GBSAGBn2Force(solventDielectric=solvent_dielectric, soluteDielectric=solute_dielectric, SA="ACE",
                       cutoff=None, kappa=0.0)
    params = GBSAGBn2Force.getStandardParameters(topology)
    for i, prm in enumerate(params):
        q = nb.getParticleParameters(i)[0].value_in_unit(__import__("openmm").unit.elementary_charge)
        gb.addParticle([q] + list(prm))
    gb.finalize()
    gb.setName("msw_gbn2")
    system.addForce(gb)
    return {"model": "GBn2 (igb=8)", "radii": "mbondi3", "surface_area": "ACE", "solvent_dielectric": solvent_dielectric,
            "salt_kappa": 0.0, "n_particles": len(params)}


def make_nonperiodic(system) -> list[str]:
    """Implicit solvent has no box: position restraints written with periodicdistance() and centroid forces flagged
    periodic would make OpenMM treat the System as periodic.  Rewrite them as plain distances."""
    import openmm as mm
    changed = []
    for f in system.getForces():
        if isinstance(f, mm.CustomExternalForce) and "periodicdistance" in f.getEnergyFunction():
            f.setEnergyFunction(f.getEnergyFunction().replace("periodicdistance(x,y,z,x0,y0,z0)",
                                                              "sqrt((x-x0)^2+(y-y0)^2+(z-z0)^2)"))
            changed.append(f.getName())
        elif isinstance(f, mm.CustomCentroidBondForce) and f.usesPeriodicBoundaryConditions():
            f.setUsesPeriodicBoundaryConditions(False)
            changed.append(f.getName())
    return changed


def add_flat_bottom_restraints(system, topology, positions, lig_atom_ranges, *, k=1000.0, width_nm=0.4,
                               pocket_cutoff_nm=0.8) -> list[dict]:
    """WP4: multi-ligand runs — keep each ligand centroid within `width` of its starting distance to the pocket Cα centroid.

    Zero force while the ligand stays in its site; only prevents a ligand drifting into bulk or into the other ligand's
    site during short teaching runs.  Scaled by global `msw_fb_scale` (binding/free-energy steps set it to 0)."""
    import numpy as np
    import openmm as mm
    from openmm import unit
    pos = np.asarray(positions.value_in_unit(unit.nanometer))
    atoms = list(topology.atoms())
    lig_idx = {i for _, a, b in lig_atom_ranges for i in range(a, b)}
    ca = np.array([a.index for a in atoms if a.name == "CA" and a.index not in lig_idx and a.residue.name not in {"CA"}], dtype=int)
    f = mm.CustomCentroidBondForce(2, "0.5*msw_fb_scale*k_fb*max(0, abs(distance(g1,g2)-d0_fb)-w_fb)^2")
    f.addGlobalParameter("msw_fb_scale", 1.0)
    for name in ("k_fb", "d0_fb", "w_fb"):
        f.addPerBondParameter(name)
    out = []
    for name, a, b in lig_atom_ranges:
        heavy = [i for i in range(a, b) if atoms[i].element is not None and atoms[i].element.symbol != "H"]
        if not heavy or not len(ca):
            continue
        d = np.min(np.linalg.norm(pos[ca][:, None, :] - pos[heavy][None, :, :], axis=2), axis=1)
        pocket = ca[d <= pocket_cutoff_nm]
        if len(pocket) < 3:
            pocket = ca[np.argsort(d)[:3]]
        g1 = f.addGroup(heavy, [1.0] * len(heavy))
        g2 = f.addGroup(pocket.tolist(), [1.0] * len(pocket))
        d0 = float(np.linalg.norm(pos[heavy].mean(0) - pos[pocket].mean(0)))
        f.addBond([g1, g2], [k, d0, width_nm])
        out.append({"ligand": name, "pocket_ca": len(pocket), "d0_nm": round(d0, 3), "width_nm": width_nm, "k": k})
    f.setUsesPeriodicBoundaryConditions(True)
    f.setName("msw_flat_bottom")
    system.addForce(f)
    return out


def assemble_system(receptor_pdb: Path | str, ligands: list[LigandRecord], out_dir: Path | str, *,
                    padding_nm: float = 1.0, ionic_strength_molar: float = 0.15, box_shape: str = "dodecahedron",
                    water_model: str = "tip3p", decisions: DecisionLog | None = None,
                    nonbonded_cutoff_nm: float = 1.0, forcefield_files: tuple[str, ...] = AMBER_PROTEIN,
                    flat_bottom: bool | None = None, metal_policy: dict | None = None, ph: float = 7.4,
                    metal_params: dict | None = None, solvent: str = "explicit") -> BuildResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = GateReport()
    try:
        import openmm as mm
        from openmm import app, unit, XmlSerializer
    except ImportError as exc:
        res = BuildResult(status=NEEDS_HUMAN, gates=GateReport([Gate("openmm", NEEDS_HUMAN, f"缺少 openmm：{exc}")]).to_dict())
        atomic_write_json(res.to_dict(), out_dir / "build_manifest.json")
        return res
    pdb = app.PDBFile(str(receptor_pdb))
    modeller = app.Modeller(pdb.topology, pdb.positions)
    ff = app.ForceField(*forcefield_files)
    from .metal import apply_metal_policy, add_metal_forces, site_gates
    metal_plans = apply_metal_policy(modeller, ff, metal_policy, ph=ph, metal_params=metal_params,
                                     qm_dir=out_dir / "metal_qm")
    for g in site_gates(metal_plans):
        report.add(g)
        if decisions and g.status != PASS:
            decisions.record("build.metal", g.name, g.evidence.get("action"), g.explanation,
                             kind="human" if g.status == NEEDS_HUMAN else "auto_fixed")
    if not report.ok:
        res = BuildResult(status=NEEDS_HUMAN, gates=report.to_dict())
        atomic_write_json(res.to_dict(), out_dir / "build_manifest.json")
        return res
    n_protein = modeller.topology.getNumAtoms()
    receptor_chain_ids = {c.id for c in modeller.topology.chains()}
    lig_names = set()
    generators = []
    peptide_chains: list[str] = []
    lig_atom_ranges: list[tuple[str, int, int]] = []
    for rec in ligands:
        start = modeller.topology.getNumAtoms()
        if getattr(rec, "kind", "small") == "peptide":
            pep = app.PDBFile(rec.pdb_path)
            pm = app.Modeller(pep.topology, pep.positions)
            pm.addHydrogens(ff, pH=7.4)
            for ch in pm.topology.chains():
                ch.id = rec.chain_id
            modeller.add(pm.topology, pm.positions)
            peptide_chains.append(rec.chain_id)
            lig_atom_ranges.append((rec.name, start, modeller.topology.getNumAtoms()))
            continue
        top, pos, offmol = _ligand_openmm(rec)
        modeller.add(top, pos)
        lig_atom_ranges.append((rec.name, start, modeller.topology.getNumAtoms()))
        lig_names.add(rec.resname)
        ladder = parameter_ladder(__import__("rdkit.Chem", fromlist=["SDMolSupplier"]).SDMolSupplier(rec.sdf_path, removeHs=False)[0],
                                  prefer=((rec.provider,) if rec.provider else ("openff-sage", "gaff2")), decisions=None)
        if not ladder["generator"]:
            report.add(Gate(f"ligand {rec.name} parameters", NEEDS_HUMAN, "組裝階段無法重建配體參數：" + str(ladder["errors"])))
        else:
            ff.registerTemplateGenerator(ladder["generator"].generator)
            generators.append(ladder["provider"])
    if lig_atom_ranges:
        # REVIEW #15: metal sites were planned on the receptor alone; check the assembled complex for a docked
        # ligand that coordinates a metal directly
        from .metal import _atoms_of, ligand_metal_contacts, ligand_metal_gate
        import numpy as _np2
        lig_set = {i for _, a, b in lig_atom_ranges for i in range(a, b)}
        g = ligand_metal_gate(ligand_metal_contacts(
            _atoms_of(modeller.topology, _np2.asarray(modeller.positions.value_in_unit(unit.nanometer))), lig_set))
        if g is not None:
            report.add(g)
            if decisions:
                decisions.record("build.metal", g.name, "NEEDS_HUMAN", g.explanation, kind="human")
    if not report.ok:
        res = BuildResult(status=NEEDS_HUMAN, gates=report.to_dict())
        atomic_write_json(res.to_dict(), out_dir / "build_manifest.json")
        return res
    n_lig = modeller.topology.getNumAtoms() - n_protein
    implicit = solvent == "gbn2"
    if solvent not in ("explicit", "gbn2"):
        raise ValueError(f"未知的 solvent：{solvent}（可用 explicit / gbn2）")
    if implicit and any(pl.get("action") != "remove" for pl in metal_plans):
        report.add(Gate("implicit solvent + metal", NEEDS_HUMAN,
                        "隱式溶劑（GBn2）不適合金屬位點：沒有水分子配位與屏蔽，+2 金屬的靜電會把位點拉扭。",
                        options=["md.solvent: explicit（顯式水）", "metal_policy: remove（僅限金屬非功能必要）"]))
        res = BuildResult(status=NEEDS_HUMAN, gates=report.to_dict(), solvent=solvent)
        atomic_write_json(res.to_dict(), out_dir / "build_manifest.json")
        return res
    if implicit:
        modeller.topology.setPeriodicBoxVectors(None)
        if decisions:
            decisions.record("build.solvate", "solvent", "GBn2 implicit",
                             "隱式溶劑：不加水與離子、無週期盒、無 PME，原子數少 80–90%，筆電上快很多。適合短 MD 篩 pose 與教學 MD；"
                             "不適合金屬位點、水橋接的結合、SMD/傘狀採樣（溶劑化能障會失真）。")
    else:
        # solvate — the box is where the compute goes (80–90 % of the atoms are water), so: smallest shape that keeps
        # the protein ≥ 2×padding from its own image in every orientation (rhombic dodecahedron: 71 % of the cube's
        # volume for the same image distance), and padding no larger than the solvation shell needs.
        if padding_nm < MIN_PADDING_NM:
            report.add(Gate("padding", NEEDS_HUMAN,
                            f"padding {padding_nm} nm 小於 {MIN_PADDING_NM} nm：蛋白會與自己的週期影像在截斷半徑（1.0 nm）內互相作用，"
                            "溶劑化殼層也不完整；省下的算力會換來錯的結果。",
                            options=[f"md.padding_nm ≥ {MIN_PADDING_NM}（教學 0.8、研究 1.0）", "md.solvent: gbn2（真的要省算力時用隱式溶劑）"]))
            res = BuildResult(status=NEEDS_HUMAN, gates=report.to_dict(), solvent=solvent)
            atomic_write_json(res.to_dict(), out_dir / "build_manifest.json")
            return res
        shape = {"cube": "cube", "dodecahedron": "dodecahedron", "octahedron": "octahedron"}[box_shape]
        modeller.addSolvent(ff, model=water_model, padding=padding_nm * unit.nanometer, boxShape=shape,
                            ionicStrength=ionic_strength_molar * unit.molar, neutralize=True)
        if decisions:
            vecs = modeller.topology.getPeriodicBoxVectors()
            vol = abs(float(np.linalg.det(np.array([[v.x, v.y, v.z] for v in vecs])))) if vecs else 0.0
            n_w = sum(1 for r in modeller.topology.residues() if r.name in {"HOH", "WAT"})
            cube_equiv = {"dodecahedron": 1.0 / 0.7071, "octahedron": 1.0 / 0.7698, "cube": 1.0}[shape]
            decisions.record("build.solvate", "box",
                             {"shape": shape, "padding_nm": padding_nm, "ionic_strength_M": ionic_strength_molar, "volume_nm3": round(vol, 1),
                              "n_water": n_w},
                             f"{shape}、padding {padding_nm} nm、{n_w} 個水、體積 {vol:.0f} nm³"
                             + (f"（同樣影像距離的立方盒要多 {100 * (cube_equiv - 1):.0f}% 水）" if shape != "cube" else "")
                             + f"；離子強度 {ionic_strength_molar} M 並中和（鹽只佔原子數 < 1%，算力在水）。"
                             "padding 是蛋白到盒邊的最小距離：0.8 nm 已含完整溶劑化殼層，再小會碰到自己的週期影像。")
    counts = {}
    n_water = 0
    for res_ in modeller.topology.residues():
        if res_.name in {"HOH", "WAT"}:
            n_water += 1
        elif res_.name in {"NA", "CL", "K", "MG", "CA", "ZN"}:
            counts[res_.name] = counts.get(res_.name, 0) + 1
    try:
        if implicit:
            system = ff.createSystem(modeller.topology, nonbondedMethod=app.NoCutoff, constraints=app.HBonds,
                                     removeCMMotion=True)
        else:
            system = ff.createSystem(modeller.topology, nonbondedMethod=app.PME, nonbondedCutoff=nonbonded_cutoff_nm * unit.nanometer,
                                     constraints=app.HBonds, rigidWater=True, removeCMMotion=True)
    except ValueError as exc:
        report.add(Gate("force field templates", NEEDS_HUMAN, f"力場缺少殘基樣板：{exc}（常見：金屬或輔因子沒有參數）。",
                        options=["metal_policy: remove（若非必要）", "提供該殘基的參數", "從 keep_hetero 移除"]))
        res = BuildResult(status=NEEDS_HUMAN, gates=report.to_dict())
        atomic_write_json(res.to_dict(), out_dir / "build_manifest.json")
        return res
    lig_index_set = {i for _, a, b in lig_atom_ranges for i in range(a, b)}
    import numpy as _np
    metal_info = add_metal_forces(system, metal_plans, _np.asarray(modeller.positions.value_in_unit(unit.nanometer)),
                                  topology=modeller.topology) if metal_plans else {}
    for key, prob in metal_info.get("charge_problems") or []:
        report.add(Gate(f"metal charges {key}", NEEDS_HUMAN, prob,
                        options=["metal_params 改為不套用電荷（charges: false）", "確認 MCPB 模型的質子化狀態"]))
    restr = add_position_restraints(system, modeller.topology, modeller.positions, ligand_resnames=lig_names,
                                    ligand_atom_indices=lig_index_set)
    if flat_bottom is None:
        flat_bottom = len(lig_atom_ranges) > 1
    if flat_bottom and lig_atom_ranges:
        restr["flat_bottom"] = add_flat_bottom_restraints(system, modeller.topology, modeller.positions, lig_atom_ranges)
        report.add(Gate("multi-ligand flat-bottom", AUTO_FIXED,
                        f"多配體系統：每個配體質心對口袋 Cα 質心加平底限制（±0.4 nm 內零力），避免短模擬中配體漂離或互換位置；"
                        f"結合自由能步驟會關閉。共 {len(restr['flat_bottom'])} 個。"))
    gb_info = {}
    if implicit:
        try:
            gb_info = add_gbn2_force(system, modeller.topology)
            gb_info["nonperiodic_rewrites"] = make_nonperiodic(system)
        except Exception as exc:  # noqa: BLE001
            report.add(Gate("implicit solvent", NEEDS_HUMAN, f"無法建立 GBn2 隱式溶劑：{type(exc).__name__}: {exc}",
                            options=["md.solvent: explicit（顯式水）"]))
    if peptide_chains:
        from .peptide import topology_gate
        for g in topology_gate(modeller.topology, receptor_chain_ids, peptide_chains).gates:
            report.add(g)
    # audits
    total_q = 0.0
    for f in (system.getForce(i) for i in range(system.getNumForces())):
        if isinstance(f, mm.NonbondedForce):
            total_q = sum(f.getParticleParameters(i)[0]._value for i in range(f.getNumParticles()))
    if implicit:
        report.add(Gate("total charge", PASS if abs(total_q - round(total_q)) <= 0.01 else NEEDS_HUMAN,
                        f"隱式溶劑不加反離子：系統淨電荷 {total_q:+.3f} e（GBn2 以介電常數屏蔽；非整數表示參數有誤）。",
                        evidence={"total_charge": total_q}))
    elif abs(total_q - round(total_q)) > 0.01 or abs(round(total_q)) > 0:
        report.add(Gate("total charge", NEEDS_HUMAN if abs(total_q) > 0.05 else PASS,
                        f"系統總電荷 {total_q:.3f} e；中和後應為 0。非零通常表示配體電荷或離子數有誤。", evidence={"total_charge": total_q}))
    else:
        report.add(Gate("total charge", PASS, f"系統總電荷 {total_q:.3f} e（已中和）。"))
    n_atoms = system.getNumParticles()
    water_frac = 3 * n_water / n_atoms if n_atoms else 0
    if not implicit and water_frac < 0.4:
        report.add(Gate("water fraction", PASS, f"水佔 {100 * water_frac:.0f}%（小 padding 的緊湊盒子；蛋白到影像的距離仍 ≥ 2×padding）。"))
    box = modeller.topology.getPeriodicBoxVectors()
    box_nm = [[v.x, v.y, v.z] for v in box] if box else []
    # single-point energy must be finite
    integ = mm.VerletIntegrator(0.001)
    ctx = mm.Context(system, integ, mm.Platform.getPlatformByName("CPU"))
    ctx.setPositions(modeller.positions)
    e = ctx.getState(getEnergy=True).getPotentialEnergy()._value
    del ctx
    import math
    report.add(Gate("single-point energy", PASS if math.isfinite(e) else NEEDS_HUMAN,
                    f"初始位能 {e:,.0f} kJ/mol" if math.isfinite(e) else "初始位能 NaN：有重疊原子或壞參數。"))
    atoms_el = [a.element.symbol if a.element is not None else "?" for a in modeller.topology.atoms()]
    top_pdb = out_dir / "topology.pdb"
    with open(top_pdb, "w", encoding="utf-8") as fh:
        app.PDBFile.writeFile(modeller.topology, modeller.positions, fh, keepIds=True)
    from ..util.stamp import stamp_pdb_file
    stamp_pdb_file(top_pdb)
    sys_xml = out_dir / "system.xml"
    # OpenMM's XML reader rejects anything before the root element, so system.xml stays unmodified;
    # its provenance is in build_manifest.json (stamped) together with its SHA-256.
    sys_xml.write_text(XmlSerializer.serialize(system), encoding="utf-8")
    res = BuildResult(status=report.status, system_xml=str(sys_xml), topology_pdb=str(top_pdb), n_atoms=n_atoms,
                      n_protein_atoms=n_protein, n_ligand_atoms=n_lig, n_waters=n_water, n_ions=counts, box_nm=box_nm,
                      total_charge=total_q, forcefields=list(forcefield_files) + generators,
                      ligands=[{**l.to_dict(), "atom_indices": list(range(a, b)),
                                "heavy_atom_indices": [i for i in range(a, b) if atoms_el[i] != "H"]}
                               for l, (_, a, b) in zip(ligands, lig_atom_ranges)],
                      restraints={**restr, "metals": {"plans": metal_plans, **metal_info}} if metal_plans else restr,
                      gates=report.to_dict(), solvent=solvent,
                      hashes={"system_xml": sha256_file(sys_xml), "topology_pdb": sha256_file(top_pdb)})
    atomic_write_json({**res.to_dict(), "created_at": now_iso(), **({"implicit_solvent": gb_info} if implicit else {})},
                      out_dir / "build_manifest.json")
    return res
