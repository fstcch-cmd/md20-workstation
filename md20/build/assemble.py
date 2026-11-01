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


def add_position_restraints(system, topology, positions, *, k_protein=1000.0, k_ligand=500.0,
                            ligand_resnames: set[str] = frozenset(), ligand_atom_indices: set[int] = frozenset()) -> dict:
    """Harmonic restraints on protein backbone + ligand heavy atoms, scaled by global `msw_restraint_scale`."""
    import openmm as mm
    from openmm import unit
    force = mm.CustomExternalForce("0.5*msw_restraint_scale*k*periodicdistance(x,y,z,x0,y0,z0)^2")
    force.addGlobalParameter("msw_restraint_scale", 1.0)
    for p in ("k", "x0", "y0", "z0"):
        force.addPerParticleParameter(p)
    n_prot = n_lig = 0
    pos = positions.value_in_unit(unit.nanometer)
    backbone = {"CA", "C", "N", "O"}
    for atom in topology.atoms():
        rn = atom.residue.name
        is_lig = rn in ligand_resnames or atom.index in ligand_atom_indices
        if is_lig and atom.element is not None and atom.element.symbol != "H":
            k = k_ligand; n_lig += 1
        elif atom.name in backbone and rn not in {"HOH", "WAT"} and not is_lig and atom.element is not None and atom.element.symbol != "H":
            k = k_protein; n_prot += 1
        else:
            continue
        x, y, z = pos[atom.index]
        force.addParticle(atom.index, [k, x, y, z])
    force.setName("msw_position_restraints")
    system.addForce(force)
    return {"type": "CustomExternalForce", "global_parameter": "msw_restraint_scale", "protein_backbone_atoms": n_prot,
            "ligand_heavy_atoms": n_lig, "k_protein_kj_mol_nm2": k_protein, "k_ligand_kj_mol_nm2": k_ligand}


def assemble_system(receptor_pdb: Path | str, ligands: list[LigandRecord], out_dir: Path | str, *,
                    padding_nm: float = 1.0, ionic_strength_molar: float = 0.15, box_shape: str = "cube",
                    water_model: str = "tip3p", decisions: DecisionLog | None = None,
                    nonbonded_cutoff_nm: float = 1.0, forcefield_files: tuple[str, ...] = AMBER_PROTEIN) -> BuildResult:
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
    n_protein = modeller.topology.getNumAtoms()
    receptor_chain_ids = {c.id for c in modeller.topology.chains()}
    ff = app.ForceField(*forcefield_files)
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
    if not report.ok:
        res = BuildResult(status=NEEDS_HUMAN, gates=report.to_dict())
        atomic_write_json(res.to_dict(), out_dir / "build_manifest.json")
        return res
    n_lig = modeller.topology.getNumAtoms() - n_protein
    # solvate
    shape = {"cube": "cube", "dodecahedron": "dodecahedron", "octahedron": "octahedron"}[box_shape]
    modeller.addSolvent(ff, model=water_model, padding=padding_nm * unit.nanometer, boxShape=shape,
                        ionicStrength=ionic_strength_molar * unit.molar, neutralize=True)
    if decisions:
        decisions.record("build.solvate", "box", f"{shape}, padding {padding_nm} nm, {ionic_strength_molar} M, neutralized",
                         "padding 1.0 nm 在教學 tier 是精度與速度的折衷；研究 tier 建議 1.2 nm。中和 + 生理離子強度。")
    counts = {}
    n_water = 0
    for res_ in modeller.topology.residues():
        if res_.name in {"HOH", "WAT"}:
            n_water += 1
        elif res_.name in {"NA", "CL", "K", "MG", "CA", "ZN"}:
            counts[res_.name] = counts.get(res_.name, 0) + 1
    system = ff.createSystem(modeller.topology, nonbondedMethod=app.PME, nonbondedCutoff=nonbonded_cutoff_nm * unit.nanometer,
                             constraints=app.HBonds, rigidWater=True, removeCMMotion=True)
    lig_index_set = {i for _, a, b in lig_atom_ranges for i in range(a, b)}
    restr = add_position_restraints(system, modeller.topology, modeller.positions, ligand_resnames=lig_names,
                                    ligand_atom_indices=lig_index_set)
    if peptide_chains:
        from .peptide import topology_gate
        for g in topology_gate(modeller.topology, receptor_chain_ids, peptide_chains).gates:
            report.add(g)
    # audits
    total_q = 0.0
    for f in (system.getForce(i) for i in range(system.getNumForces())):
        if isinstance(f, mm.NonbondedForce):
            total_q = sum(f.getParticleParameters(i)[0]._value for i in range(f.getNumParticles()))
    if abs(total_q - round(total_q)) > 0.01 or abs(round(total_q)) > 0:
        report.add(Gate("total charge", NEEDS_HUMAN if abs(total_q) > 0.05 else PASS,
                        f"系統總電荷 {total_q:.3f} e；中和後應為 0。非零通常表示配體電荷或離子數有誤。", evidence={"total_charge": total_q}))
    else:
        report.add(Gate("total charge", PASS, f"系統總電荷 {total_q:.3f} e（已中和）。"))
    n_atoms = system.getNumParticles()
    water_frac = 3 * n_water / n_atoms if n_atoms else 0
    if water_frac < 0.5:
        report.add(Gate("water fraction", AUTO_FIXED, f"水佔 {100 * water_frac:.0f}%，系統偏小或 padding 不足；可接受但請確認 box 大於蛋白最長軸 + 2×padding。"))
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
    from ..util.stamp import stamp_pdb_file, TAG, VISIBLE
    stamp_pdb_file(top_pdb)
    sys_xml = out_dir / "system.xml"
    sys_xml.write_text(f"<!-- {VISIBLE} {TAG} -->\n" + XmlSerializer.serialize(system), encoding="utf-8")
    res = BuildResult(status=report.status, system_xml=str(sys_xml), topology_pdb=str(top_pdb), n_atoms=n_atoms,
                      n_protein_atoms=n_protein, n_ligand_atoms=n_lig, n_waters=n_water, n_ions=counts, box_nm=box_nm,
                      total_charge=total_q, forcefields=list(forcefield_files) + generators,
                      ligands=[{**l.to_dict(), "atom_indices": list(range(a, b)),
                                "heavy_atom_indices": [i for i in range(a, b) if atoms_el[i] != "H"]}
                               for l, (_, a, b) in zip(ligands, lig_atom_ranges)],
                      restraints=restr, gates=report.to_dict(),
                      hashes={"system_xml": sha256_file(sys_xml), "topology_pdb": sha256_file(top_pdb)})
    atomic_write_json({**res.to_dict(), "created_at": now_iso()}, out_dir / "build_manifest.json")
    return res
