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
import math
import numpy as np

MIN_PADDING_NM = 1.0      # D-99: padding = solute-to-image distance; below the 1.0 nm cutoff the protein sees its image

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


# D-99: room for the ligand COM to move / a peptide to extend between the build and the SMD start (equilibration + MD)
SMD_BOX_ALLOWANCE_NM = 0.5
# D-99 general rule: a case not (yet) planned for SMD is still checked; enlarging it pre-emptively is done when it is
# cheap (MD cost ≤ this factor), so a later SMD needs no rebuild; otherwise the build says so before the MD starts
SMD_PROACTIVE_MAX_COST = 1.5

# Monovalent ions OpenMM's Modeller.addSolvent can place; amber14/tip3p.xml carries Joung–Cheatham parameters for
# all of them.  Divalent salts (MgCl2, CaCl2) need a different placement and are not supported yet (gate).
POSITIVE_IONS = {"Na+": "NA", "K+": "K", "Li+": "LI", "Rb+": "RB", "Cs+": "CS"}
NEGATIVE_IONS = {"Cl-": "CL", "Br-": "BR", "F-": "F", "I-": "I"}
ION_RESNAMES = {"NA", "K", "LI", "RB", "CS", "CL", "BR", "F", "I", "MG", "CA", "ZN"}


def resolve_ions(ions: dict | None, ionic_strength_molar: float = 0.15) -> tuple[dict, str | None]:
    """md.ions → {"positive","negative","concentration_molar","neutralize"}; returns (spec, problem).  D-46."""
    spec = {"positive": "Na+", "negative": "Cl-", "concentration_molar": float(ionic_strength_molar), "neutralize": True}
    for k, v in (ions or {}).items():
        if k in spec:
            spec[k] = v
    spec["concentration_molar"] = float(spec["concentration_molar"])
    spec["neutralize"] = bool(spec["neutralize"])
    if spec["positive"] not in POSITIVE_IONS:
        return spec, (f"陽離子 {spec['positive']} 無法自動放置：目前支援 {', '.join(POSITIVE_IONS)}（一價）。"
                      "二價離子（Mg2+、Ca2+）需另外放置與參數化，尚未支援。")
    if spec["negative"] not in NEGATIVE_IONS:
        return spec, f"陰離子 {spec['negative']} 無法自動放置：目前支援 {', '.join(NEGATIVE_IONS)}（一價）。"
    if not 0.0 <= spec["concentration_molar"] <= 2.0:
        return spec, f"鹽濃度 {spec['concentration_molar']} M 超出 0 至 2 M 的合理範圍。"
    return spec, None


def _pairs_numpy(O: np.ndarray, oh_xyz, box, o_o_min_nm: float, oh_min_nm: float, block: int = 2048):
    """SciPy-free twin of the cKDTree search in declash_waters (same pair records, same O-H-first ordering)."""
    n = len(O)
    pairs, oh_min = [], None

    def disp(a, b):
        d = a[:, None, :] - b[None, :, :]
        if box is not None:
            d -= np.round(d / box) * box
        return np.sqrt((d ** 2).sum(-1))
    for s0 in range(0, n, block):
        D = disp(O[s0:s0 + block], O)
        ii, jj = np.where(D < o_o_min_nm)
        for a, j in zip(ii, jj):
            i = s0 + int(a)
            if i < j:
                pairs.append((float(D[a, j]), i, int(j)))
    if oh_xyz is not None and len(oh_xyz):
        arr = np.asarray(oh_xyz, float)
        k = arr.shape[1]
        H = arr.reshape(-1, 3)
        keep = np.all(H < 9e5, axis=1)
        for s0 in range(0, n, block):
            D = disp(O[s0:s0 + block], H)
            ii, hh = np.where(D < oh_min_nm)
            for a, hj in zip(ii, hh):
                i, j = s0 + int(a), int(hj) // k
                if not keep[hj] or i == j:
                    continue
                oh_min = min(oh_min or 9.9, float(D[a, hj]))
                dij = O[i] - O[j]
                if box is not None:
                    dij -= np.round(dij / box) * box
                pairs.append((float(np.linalg.norm(dij)) - 999.0, min(i, j), max(i, j)))
    return pairs, oh_min


def declash_waters(o_xyz: np.ndarray, oh_xyz, box: np.ndarray | None, *, o_o_min_nm: float = 0.21,
                   oh_min_nm: float = 0.14, hard_floor_nm: float = 0.14) -> dict:
    """Which waters to delete so no two overlap (pure, D-102).  OpenMM's addSolvent/addMembrane occasionally places a
    water almost on top of another (seen: O-O down to 0.178 nm, bulk is ~0.28); such a pair survives minimisation as a
    metastable state and the forces blow up to NaN in the first MD steps.  Every MD-prep pipeline removes these.

    o_xyz: (n,3) water O positions; oh_xyz: (n, k, 3) each water's H positions (for inter-molecular O-H overlap);
    box: (3,) orthorhombic lengths or None.  Greedy by increasing distance: of each still-overlapping pair, drop the
    higher-index water (deterministic).  Returns {"remove": [water indices], "min_oo_nm", "min_oh_inter_nm",
    "n_pairs", "unresolvable": [(i, j, d)]}.  A pair below hard_floor where BOTH are flagged by other pairs cannot be
    fixed by removing only one — reported, the caller blocks."""
    n = len(o_xyz)
    out = {"remove": [], "min_oo_nm": None, "min_oh_inter_nm": None, "n_pairs": 0, "unresolvable": []}
    if n < 2:
        return out
    O = np.mod(o_xyz, box) if box is not None else o_xyz

    def mind(a, b):
        d = a - b
        if box is not None:
            d -= np.round(d / box) * box
        return float(np.linalg.norm(d))

    pairs = []
    try:
        from scipy.spatial import cKDTree
        tO = cKDTree(O, boxsize=box) if box is not None else cKDTree(O)
        for i, j in tO.query_pairs(o_o_min_nm, output_type="ndarray"):
            pairs.append((mind(o_xyz[i], o_xyz[j]), int(i), int(j)))
        if oh_xyz is not None and len(oh_xyz):
            arr = np.asarray(oh_xyz, float)
            k = arr.shape[1]
            Hflat = arr.reshape(-1, 3)
            keep = np.all(Hflat < 9e5, axis=1)                                  # padding rows (1e6) are not real H
            H = np.mod(Hflat, box) if box is not None else Hflat
            tH = cKDTree(H, boxsize=box) if box is not None else cKDTree(H)
            m = tO.sparse_distance_matrix(tH, oh_min_nm, output_type="ndarray")
            for rec in m:
                i, hj = int(rec[0]), int(rec[1])
                if not keep[hj]:
                    continue
                j = hj // k
                if i != j:
                    out["min_oh_inter_nm"] = min(out["min_oh_inter_nm"] or 9.9, float(rec[2]))
                    pairs.append((mind(o_xyz[i], o_xyz[j]) - 999.0, min(i, j), max(i, j)))   # O-H clashes first
    except ImportError:
        # no SciPy (the pure-python CI jobs, some minimal installs): the same O-O and O-H checks with numpy, in blocks
        pairs, oh_min = _pairs_numpy(np.asarray(o_xyz, float), oh_xyz, box, o_o_min_nm, oh_min_nm)
        if oh_min is not None:
            out["min_oh_inter_nm"] = oh_min
    if not pairs:
        return out
    oo = [p for p in pairs if p[0] > -900]
    out["min_oo_nm"] = round(min(p[0] for p in oo), 4) if oo else None
    if out["min_oh_inter_nm"] is not None:
        out["min_oh_inter_nm"] = round(out["min_oh_inter_nm"], 4)
    out["n_pairs"] = len(pairs)
    removed: set = set()
    for d, i, j in sorted(pairs):
        if i in removed or j in removed:
            continue
        drop = max(i, j)
        if (d if d > -900 else d + 999.0) < hard_floor_nm and min(i, j) in removed:
            out["unresolvable"].append((i, j, round(d if d > -900 else d + 999.0, 4)))
            continue
        removed.add(drop)
    out["remove"] = sorted(removed)
    return out


# D-115: hard-clash distances ion–water (nm), ≈ 80 % of the first-shell ion–O peak in TIP3P-class water (Joung &
# Cheatham 2008 ion parameters; Li 0.20, Na 0.24, K 0.28, Rb 0.29, Cs 0.31, Mg 0.21, Ca 0.24, Zn 0.21, F 0.27, Cl 0.32,
# Br 0.34, I 0.36).  Anions also have their water H facing them (Cl–H peak ≈ 0.22): H limit = O limit − 0.08.
ION_O_MIN_NM = {"Li": 0.16, "Na": 0.19, "K": 0.22, "Rb": 0.23, "Cs": 0.25, "Mg": 0.17, "Ca": 0.19, "Zn": 0.17,
                "F": 0.22, "Cl": 0.26, "Br": 0.27, "I": 0.29}
ANIONS = {"F", "Cl", "Br", "I"}
ION_ION_MIN_NM = 0.22            # below a contact ion pair (Na–Cl ≈ 0.28): cannot be fixed by removing water


def ion_water_clashes(ion_xyz: np.ndarray, ion_el: list[str], o_xyz: np.ndarray, oh_xyz, box: np.ndarray | None,
                      *, skip_waters=()) -> dict:
    """Pure (D-115).  Waters sitting on an ion.  OpenMM adds ions by REPLACING waters; when the replaced water was one
    of the overlapping pairs D-102 looks for, the ion inherits the overlap (seen: Cl–O 0.193 nm, normal ≈ 0.32) and
    the water–water check no longer sees it.  The ion is kept (charge and salt concentration unchanged); the water is
    removed.  Returns {"remove": [water idx], "pairs": [(ion i, water w, d, "O"|"H")], "min_by_ion": {el: d},
    "ion_ion": [(i, j, d)] (unresolvable)}."""
    out = {"remove": [], "pairs": [], "min_by_ion": {}, "ion_ion": []}
    ion_xyz = np.asarray(ion_xyz, float).reshape(-1, 3)
    o_xyz = np.asarray(o_xyz, float).reshape(-1, 3)
    if not len(ion_xyz):
        return out

    def dvec(a, b):
        d = b - a
        if box is not None:
            d = d - np.round(d / box) * box
        return d

    skip = set(int(x) for x in skip_waters)
    H = np.asarray(oh_xyz, float) if oh_xyz is not None and len(oh_xyz) else None
    rm = set()
    for i, (x, el) in enumerate(zip(ion_xyz, ion_el)):
        lim = ION_O_MIN_NM.get(el)
        if lim is None:
            continue
        if len(o_xyz):
            dO = np.linalg.norm(dvec(x, o_xyz), axis=1)
            for w in np.nonzero(dO < lim)[0]:
                if int(w) not in skip:
                    out["pairs"].append((i, int(w), round(float(dO[w]), 4), "O")); rm.add(int(w))
            if len(dO):
                out["min_by_ion"][el] = round(min(out["min_by_ion"].get(el, 9.9), float(dO.min())), 4)
        if el in ANIONS and H is not None:
            k = H.shape[1]
            flat = H.reshape(-1, 3)
            real = np.all(flat < 9e5, axis=1)
            dH = np.linalg.norm(dvec(x, flat), axis=1)
            for hj in np.nonzero((dH < lim - 0.08) & real)[0]:
                w = int(hj) // k
                if w not in skip:
                    out["pairs"].append((i, w, round(float(dH[hj]), 4), "H")); rm.add(w)
    for i in range(len(ion_xyz)):
        for j in range(i + 1, len(ion_xyz)):
            d = float(np.linalg.norm(dvec(ion_xyz[i], ion_xyz[j])))
            if d < ION_ION_MIN_NM:
                out["ion_ion"].append((i, j, round(d, 4)))
    out["remove"] = sorted(rm)
    return out


def remove_overlapping_waters(modeller, report, decisions=None, *, o_o_min_nm: float = 0.21) -> dict:
    """D-102: delete waters OpenMM placed overlapping (build-stage repair, not an MD or model change).  AUTO_FIXED with
    a diff when any are removed; PASS when the box is clean; NEEDS_HUMAN only if an overlap cannot be fixed by removing
    a water (e.g. a water fused into the solute)."""
    from openmm import unit
    top = modeller.topology
    xyz = np.asarray(modeller.positions.value_in_unit(unit.nanometer), float)
    bv = top.getPeriodicBoxVectors()
    box = np.array([bv[i][i].value_in_unit(unit.nanometer) for i in range(3)]) if bv else None
    waters, o_idx, h_idx = [], [], []
    for r in top.residues():
        if r.name in {"HOH", "WAT", "TIP3", "SOL"}:
            o = [a.index for a in r.atoms() if a.element is not None and a.element.symbol == "O"]
            h = [a.index for a in r.atoms() if a.element is not None and a.element.symbol == "H"]
            if o:
                waters.append(r)
                o_idx.append(o[0])
                h_idx.append(h)
    if len(waters) < 2:
        return {"removed": 0}
    kmax = max((len(h) for h in h_idx), default=0)
    oh = np.full((len(waters), max(1, kmax), 3), 1e6)
    for w, h in enumerate(h_idx):
        for c, hi in enumerate(h):
            oh[w, c] = xyz[hi]
    plan = declash_waters(xyz[o_idx], oh, box, o_o_min_nm=o_o_min_nm)
    # D-115: ions placed on a water (single-atom residues of a known ion element)
    ions = [r for r in top.residues() if len(list(r.atoms())) == 1 and next(iter(r.atoms())).element is not None
            and next(iter(r.atoms())).element.symbol in ION_O_MIN_NM]
    ion_idx = [next(iter(r.atoms())).index for r in ions]
    ion_el = [next(iter(r.atoms())).element.symbol for r in ions]
    ic = ion_water_clashes(xyz[ion_idx] if ion_idx else np.zeros((0, 3)), ion_el, xyz[o_idx], oh, box,
                           skip_waters=plan["remove"])
    n_ion_w = len(ic["remove"])
    plan["remove"] = sorted(set(plan["remove"]) | set(ic["remove"]))
    info = {"removed": len(plan["remove"]), "min_oo_before_nm": plan["min_oo_nm"], "n_overlap_pairs": plan["n_pairs"],
            "removed_on_ions": n_ion_w, "ion_water_min_nm": ic["min_by_ion"], "n_ions": len(ions)}
    if ic["ion_ion"]:
        report.add(Gate("water overlaps", NEEDS_HUMAN,
                        f"有 {len(ic['ion_ion'])} 對離子彼此重疊（最近 {min(x[2] for x in ic['ion_ion']):.3f} nm < {ION_ION_MIN_NM}），"
                        "刪水無法修復；請重新建模（溶劑化與加離子是隨機的，重建通常就會不同）。",
                        options=["重新建模"], evidence=info))
        return info
    if plan["unresolvable"]:
        report.add(Gate("water overlaps", NEEDS_HUMAN,
                        f"有 {len(plan['unresolvable'])} 處水重疊無法只靠刪水修復（可能水與溶質嵌在一起，最近 "
                        f"{min(u[2] for u in plan['unresolvable']):.3f} nm）；請檢查建模（質子化、pose 幾何）。",
                        options=["檢查配體 pose 與受體質子化後重建"], evidence=info))
        return info
    if not plan["remove"]:
        report.add(Gate("water overlaps", PASS, f"水盒沒有重疊的水（最近 O–O {plan['min_oo_nm']} nm），離子旁也沒有貼太近的水。",
                        evidence=info))
        return info
    modeller.delete([waters[i] for i in plan["remove"]])
    on_ion = (f"其中 {n_ion_w} 個貼在離子上（最近 " + "、".join(f"{k}–O {v:.3f}" for k, v in ic["min_by_ion"].items())
              + " nm；離子保留，電荷與鹽濃度不變）；") if n_ion_w else ""
    oo_txt = f"最近 O–O {plan['min_oo_nm']:.3f} nm < {o_o_min_nm} nm" if plan["min_oo_nm"] is not None else "水與水之間沒有重疊"
    report.add(Gate("water overlaps", AUTO_FIXED,
                    f"移除 {len(plan['remove'])} 個重疊的水（{oo_txt}）；{on_ion}"
                    f"OpenMM 溶劑化偶爾把水放得幾乎重疊，最小化壓不下去、MD 一開始就 NaN；刪掉多餘的一個水是標準建模步驟，"
                    f"不改力場與蛋白。", evidence=info, diff=[f"waters: -{len(plan['remove'])}"]))
    if decisions:
        decisions.record("build.solvate", "declash waters", info,
                         f"移除 {len(plan['remove'])} 個重疊水（{oo_txt}；{n_ion_w} 個貼在離子上）。原因：OpenMM "
                         "addSolvent／addMembrane 偶爾放出幾乎重合的水（O–O 可低到 0.18 nm，正常約 0.28），"
                         "最小化後仍是亞穩態、MD 前幾步力爆成 NaN（Linux 與 Windows 皆會，依建構而定）。刪多餘水是標準去碰撞步驟。",
                         kind="auto_fixed")
    return info


def smd_padding_plan(xyz: np.ndarray, masses: np.ndarray, ca: np.ndarray, ligands: dict, padding_nm: float, *,
                     pull_nm: float, margin_nm: float, allowance_nm: float, shape: str) -> dict:
    """Pure core of `smd_padding` (D-99).  `ligands` = {name: heavy-atom indices}.  Returns a plan:
    {"status": PASS|AUTO_FIXED|NEEDS_HUMAN, "padding_nm", "worst", "per", "evidence"}."""
    from ..sampling.binding import pocket_anchor, smd_half_box_need, solute_radius_nm, padding_for_half_box
    per, unplanned = {}, []
    for name, lig in ligands.items():
        lig = np.asarray(lig, dtype=int)
        anc, used = pocket_anchor(xyz, ca, lig) if len(lig) else (np.array([], dtype=int), 0.0)
        if not len(anc):
            unplanned.append(name)
            continue
        need = smd_half_box_need(xyz, None, anc, lig, masses, pull_nm=pull_nm, margin_nm=margin_nm)
        per[name] = {**{k: round(v, 3) for k, v in need.items()}, "anchor_cutoff_nm": round(used, 2), "n_anchor": int(len(anc))}
    ev = {"ligands": per, "unplanned_ligands": unplanned, "allowance_nm": allowance_nm, "padding_requested_nm": padding_nm,
          "box_shape": shape}
    if not per:
        return {"status": NEEDS_HUMAN, "padding_nm": padding_nm, "worst": None, "per": per, "evidence": ev}
    worst = max(per, key=lambda k: per[k]["need_half_box_nm"])
    half_needed = per[worst]["need_half_box_nm"] + allowance_nm
    R = solute_radius_nm(xyz)
    p_req = math.ceil(padding_for_half_box(R, half_needed) / 0.05 - 1e-9) * 0.05
    vf = {"dodecahedron": 0.7071, "octahedron": 0.7698, "cube": 1.0}[shape]
    w = lambda p: max(2 * R + p, 2 * p)                                   # noqa: E731
    # how far the worst ligand could be pulled in the requested box (same rule, solved for the pull distance)
    max_pull = w(padding_nm) / 2 - (per[worst]["d0_nm"] + per[worst]["ligand_radius_nm"] + margin_nm + allowance_nm)
    ev.update({"solute_radius_nm": round(R, 3), "half_box_needed_nm": round(half_needed, 3),
               "padding_required_nm": round(p_req, 2), "half_box_at_requested_nm": round(w(padding_nm) / 2, 3),
               "max_pull_nm_at_requested": round(max_pull, 2)})
    if p_req <= padding_nm + 1e-9:
        return {"status": PASS, "padding_nm": padding_nm, "worst": worst, "per": per, "evidence": ev}
    v0, v1 = vf * w(padding_nm) ** 3, vf * w(p_req) ** 3
    ev.update({"volume_nm3_before": round(v0, 1), "volume_nm3_after": round(v1, 1), "approx_water_added": int((v1 - v0) * 33.4),
               "cost_factor": round(v1 / v0, 2)})
    return {"status": AUTO_FIXED, "padding_nm": float(round(p_req, 2)), "worst": worst, "per": per, "evidence": ev}


def smd_padding(modeller, lig_atom_ranges, padding_nm: float, smd_box: dict, shape: str, report, decisions=None) -> float:
    """D-99: the padding a pulled case needs, from the SAME rule the SMD step checks (sampling.binding: pocket-Cα anchor,
    d0 + pull + ligand radius + margin ≤ half box) and OpenMM's real box formula (width = 2R + padding), plus an
    allowance for the ligand moving / a peptide extending during MD.  Returns the padding to use (never smaller)."""
    from openmm import unit
    xyz = np.asarray(modeller.positions.value_in_unit(unit.nanometer), float)
    atoms = list(modeller.topology.atoms())
    masses = np.array([a.element.mass.value_in_unit(unit.dalton) if a.element is not None else 0.0 for a in atoms])
    in_lig = {i for _, a, b in lig_atom_ranges for i in range(a, b)}
    ca = np.array([a.index for a in atoms if a.name == "CA" and a.element is not None and a.element.symbol == "C"
                   and a.index not in in_lig], dtype=int)
    present = [n for n, _, _ in lig_atom_ranges]
    # names in the config may differ from the topology names (renamed L01…): no match → size for every ligand
    wanted = (set(smd_box.get("ligands") or []) & set(present)) or set(present)
    ligs = {n: [i for i in range(a, b) if atoms[i].element is not None and atoms[i].element.symbol != "H"]
            for n, a, b in lig_atom_ranges if n in wanted}
    pull, margin = float(smd_box.get("pull_nm", 1.5)), float(smd_box.get("margin_nm", 1.0))
    allow = float(smd_box.get("allowance_nm", SMD_BOX_ALLOWANCE_NM))
    plan = smd_padding_plan(xyz, masses, ca, ligs, padding_nm, pull_nm=pull, margin_nm=margin, allowance_nm=allow, shape=shape)
    plan = apply_smd_mode(plan, smd_box.get("mode", "enforce"), padding_nm)
    report.add(smd_box_gate(plan, pull_nm=pull, margin_nm=margin))
    if decisions and plan["status"] == AUTO_FIXED:
        decisions.record("build.box", "padding for SMD", plan["padding_nm"],
                         f"這個案例之後要做 SMD／傘狀採樣：依 SMD 步驟同一條規則（d0 + 拉離 + 配體半徑 + 安全距離 ≤ 盒子半長）"
                         f"加上 {allow} nm 的 MD 漂移餘裕，以 OpenMM 實際的盒子公式（盒寬 = 2×溶質半徑 + padding）算出 padding "
                         f"{plan['padding_nm']:.2f} nm（原 {padding_nm}）。先前固定的「拉離距離 + 0.5」沒有算配體半徑、d0 和安全距離，"
                         f"胜肽（半徑大）會建出 SMD 不能用的盒子。")
    return plan["padding_nm"]


def apply_smd_mode(plan: dict, mode: str, padding_nm: float) -> dict:
    """D-99 general rule.  enforce = SMD is planned: enlarge whatever it costs.  advise = SMD is not planned now but
    may be later: enlarge only when cheap (≤ SMD_PROACTIVE_MAX_COST); otherwise keep the box and say — before the MD —
    what a later SMD would need.  advise never blocks (no anchor → notice, not NEEDS_HUMAN)."""
    plan = {**plan, "mode": mode}
    if mode != "advise":
        return plan
    if plan["status"] == NEEDS_HUMAN:
        return {**plan, "status": "ADVISE_NO_ANCHOR"}
    if plan["status"] == AUTO_FIXED:
        f = plan["evidence"].get("cost_factor", 99.0)
        if f > SMD_PROACTIVE_MAX_COST:
            return {**plan, "status": "ADVISE_TOO_COSTLY", "padding_nm": padding_nm}
        return {**plan, "proactive": True}
    return plan


def smd_box_gate(plan: dict, *, pull_nm: float, margin_nm: float) -> Gate:
    ev, worst = plan["evidence"], plan["worst"]
    if plan["status"] == "ADVISE_NO_ANCHOR":
        return Gate("box size for SMD", PASS,
                    "之後若要做 SMD：配體附近 1.6 nm 內找不到口袋 Cα，無法事先估算拉離需要的水盒（現在不影響 MD）。",
                    options=["binding.config.anchor_residues 指定 anchor 後重建"], evidence=ev, advisory=True)
    if plan["status"] == "ADVISE_TOO_COSTLY":
        w = plan["per"][worst]
        mp = ev.get("max_pull_nm_at_requested")
        return Gate("box size for SMD", PASS,
                    f"這個案例目前沒有排 SMD。現在的水盒（padding {ev['padding_requested_nm']} nm）"
                    + (f"最多只能把 {worst} 拉離 {mp:.2f} nm" if mp is not None and mp > 0 else f"不夠把 {worst} 拉離")
                    + f"；若之後要做 SMD（拉離 {pull_nm} nm）需要 padding {ev['padding_required_nm']:.2f} nm，MD 計算量約 ×{ev['cost_factor']:.1f}，"
                    f"所以沒有先加大。要做的話**現在**加大，比 MD 跑完再重建省事。",
                    options=["md.box_for_smd: always（現在就依 SMD 規則加大）",
                             f"md.padding_nm: {ev['padding_required_nm']:.2f}",
                             "維持現狀（之後要做 SMD 時再重建）"],
                    evidence=ev, advisory=True, limitation={"what": "SMD not possible in this box",
                                                            "padding_required_nm": ev["padding_required_nm"],
                                                            "max_pull_nm": mp})
    if plan["status"] == NEEDS_HUMAN:
        return Gate("box size for SMD", NEEDS_HUMAN,
                    f"要拉離的配體 {', '.join(ev['unplanned_ligands']) or '—'} 附近找不到口袋 Cα（1.6 nm 內），無法依 SMD 規則決定水盒大小。",
                    options=["binding.config.anchor_residues 指定 anchor", f"md.padding_nm 自行指定（目前 {ev['padding_requested_nm']}）"],
                    evidence=ev)
    w = plan["per"][worst]
    if plan["status"] == PASS:
        return Gate("box size for SMD", PASS,
                    f"padding {ev['padding_requested_nm']} nm 已足夠拉離 {worst}（盒子半長 {ev['half_box_at_requested_nm']:.2f} ≥ 需要的 "
                    f"{ev['half_box_needed_nm']:.2f} nm，含 MD 漂移餘裕 {ev['allowance_nm']} nm）。", evidence=ev)
    pre = "（這個案例目前沒有排 SMD，但加大的代價很小，先加大，之後做 SMD 不必重建）" if plan.get("proactive") else ""
    return Gate("box size for SMD", AUTO_FIXED,
                pre + f"要拉離 {worst}：d0 {w['d0_nm']:.2f} + 拉離 {pull_nm} + 配體半徑 {w['ligand_radius_nm']:.2f} + 安全距離 {margin_nm} "
                f"+ MD 漂移餘裕 {ev['allowance_nm']} = 盒子半長需 {ev['half_box_needed_nm']:.2f} nm；溶質半徑 {ev['solute_radius_nm']:.2f} nm，"
                f"padding 由 {ev['padding_requested_nm']} 提高到 {plan['padding_nm']:.2f} nm（盒子約 {ev['volume_nm3_before']:.0f} → "
                f"{ev['volume_nm3_after']:.0f} nm³，水約多 {ev['approx_water_added']:,} 個，MD 計算量約 ×{ev['volume_nm3_after'] / ev['volume_nm3_before']:.1f}）。",
                evidence=ev, diff=[f"padding_nm: {ev['padding_requested_nm']} → {plan['padding_nm']:.2f}"])


def assemble_system(receptor_pdb: Path | str, ligands: list[LigandRecord], out_dir: Path | str, *,
                    padding_nm: float = 1.0, ionic_strength_molar: float = 0.15, box_shape: str = "dodecahedron",
                    water_model: str = "tip3p", decisions: DecisionLog | None = None,
                    nonbonded_cutoff_nm: float = 1.0, forcefield_files: tuple[str, ...] = AMBER_PROTEIN,
                    flat_bottom: bool | None = None, metal_policy: dict | None = None, ph: float = 7.4,
                    metal_params: dict | None = None, solvent: str = "explicit", ions: dict | None = None,
                    ligand_metal: str | None = None, accept_geometry: bool = False,
                    membrane: dict | None = None, smd_box: dict | None = None) -> BuildResult:
    """`smd_box` (D-99) = {"pull_nm", "margin_nm", "allowance_nm", "ligands": [names] | None}: the case will be pulled
    (SMD/umbrella), so the water box is sized with the SMD box rule before solvation instead of a fixed padding.
    `membrane` = md.membrane (docs/specs/membrane.md): the bilayer replaces the water box; receptor_pdb may be None
    for a solute-only surface system (case B) or a pure bilayer (case C, no ligands either)."""
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
    mplan, membrane_info = None, {}
    if membrane:
        from .membrane import plan_membrane
        mplan, mrep = plan_membrane(membrane, has_solute=receptor_pdb is not None or bool(ligands), solvent=solvent)
        for g in mrep.gates:
            report.add(g)
            if decisions and g.status != PASS:
                decisions.record("build.membrane", g.name, g.status, g.explanation,
                                 kind="human" if g.status == NEEDS_HUMAN else "auto_fixed")
        if not report.ok:
            res = BuildResult(status=NEEDS_HUMAN, gates=report.to_dict(), solvent=solvent)
            atomic_write_json({**res.to_dict(), "membrane": {"plan": mplan.to_dict() if mplan else None}}, out_dir / "build_manifest.json")
            return res
        forcefield_files = tuple(forcefield_files) + tuple(f for f in mplan.forcefield_files if f not in forcefield_files)
    if receptor_pdb is not None:
        pdb = app.PDBFile(str(receptor_pdb))
        modeller = app.Modeller(pdb.topology, pdb.positions)
    else:
        modeller = app.Modeller(app.Topology(), unit.Quantity([], unit.nanometer))
    ff = app.ForceField(*forcefield_files)
    from .metal import apply_metal_policy, add_metal_forces, site_gates
    metal_plans = apply_metal_policy(modeller, ff, metal_policy, ph=ph, metal_params=metal_params,
                                     qm_dir=out_dir / "metal_qm") if receptor_pdb is not None else []
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
    small = [r for r in ligands if getattr(r, "kind", "small") != "peptide"]
    ladders = _consistent_ladders(small, decisions, report)
    for rec in small:
        ladder = ladders.get(rec.name) or {}
        if not ladder.get("generator"):
            report.add(Gate(f"ligand {rec.name} parameters", NEEDS_HUMAN, "組裝階段無法重建配體參數：" + str(ladder.get("errors"))))
        else:
            ff.registerTemplateGenerator(ladder["generator"].generator)
            generators.append(ladder["provider"])
    if len(lig_atom_ranges) >= 1:
        _geometry_backstop(modeller, lig_atom_ranges, n_protein, report, decisions, accept_geometry, ff=ff)
    if lig_atom_ranges:
        # REVIEW #15: metal sites were planned on the receptor alone; check the assembled complex for a docked
        # ligand that coordinates a metal directly
        from .metal import _atoms_of, ligand_metal_contacts, ligand_metal_gate
        import numpy as _np2
        lig_set = {i for _, a, b in lig_atom_ranges for i in range(a, b)}
        lm_contacts = ligand_metal_contacts(
            _atoms_of(modeller.topology, _np2.asarray(modeller.positions.value_in_unit(unit.nanometer))), lig_set)
        g = ligand_metal_gate(lm_contacts, ligand_metal)
        if g is not None:
            report.add(g)
            if decisions:
                decisions.record("build.metal", g.name, g.status, g.explanation, kind="human")
    else:
        lm_contacts = []
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
                             "隱式溶劑：不加水與離子、無週期盒、無 PME，原子數少 80–90%；**有 GPU（CUDA/OpenCL）時**才明顯較快——CPU 上 GB 力（O(N²)）可能比顯式水還慢（D-25）。適合短 MD 篩 pose 與教學 MD；"
                             "不適合金屬位點、水橋接的結合、SMD/傘狀採樣（溶劑化能障會失真）。")
    else:
        # solvate — the box is where the compute goes (80–90 % of the atoms are water), so: smallest shape that keeps
        # the protein ≥ padding from its own image in every orientation (rhombic dodecahedron: 71 % of the cube's
        # volume for the same image distance), and padding no larger than the solvation shell needs.
        # D-99 correction: OpenMM adds padding ONCE (width = 2R + padding), so padding is the solute-to-own-image
        # distance, not the solute-to-edge distance (earlier comments said "2×padding" / "to the box edge").
        if padding_nm < max(MIN_PADDING_NM, nonbonded_cutoff_nm):
            lim = max(MIN_PADDING_NM, nonbonded_cutoff_nm)
            report.add(Gate("padding", NEEDS_HUMAN,
                            f"padding {padding_nm} nm 小於非鍵截斷 {lim} nm：OpenMM 的 padding 是溶質到自己週期影像的距離（只加一次），"
                            "比截斷小時蛋白會直接與自己的影像作用；省下的算力會換來錯的結果。",
                            options=["md.padding_nm: 2.0（預設，等同 GROMACS -d 1.0）", f"md.padding_nm ≥ {lim}（最低）",
                                     "md.solvent: gbn2（真的要省算力時用隱式溶劑）"]))
            res = BuildResult(status=NEEDS_HUMAN, gates=report.to_dict(), solvent=solvent)
            atomic_write_json(res.to_dict(), out_dir / "build_manifest.json")
            return res
        ion_spec, ion_problem = resolve_ions(ions, ionic_strength_molar)
        if ion_problem:
            report.add(Gate("ions", NEEDS_HUMAN, ion_problem,
                            options=["md.ions.positive: Na+（或 K+、Li+、Rb+、Cs+）", "md.ions.negative: Cl-（或 Br-、F-、I-）"]))
            res = BuildResult(status=NEEDS_HUMAN, gates=report.to_dict(), solvent=solvent)
            atomic_write_json(res.to_dict(), out_dir / "build_manifest.json")
            return res
        if mplan is not None:
            # the bilayer (with its water and ions) replaces the water box (md20/build/membrane.py)
            from . import membrane as MB
            try:
                if mplan.type == "bilayer":
                    modeller, membrane_info = MB.build_bilayer(ff, mplan, ion_spec=ion_spec, report=report, decisions=decisions,
                                                               live_dir=out_dir)
                else:
                    membrane_info = MB.add_membrane(modeller, ff, mplan, ion_spec=ion_spec, report=report, decisions=decisions,
                                                    live_dir=out_dir)
            except Exception as exc:  # noqa: BLE001
                report.add(Gate("membrane builder", NEEDS_HUMAN, f"建膜失敗：{type(exc).__name__}: {exc}",
                                options=["md.membrane.lipids: mammalian", "回報給老師"]))
            if not report.ok:
                res = BuildResult(status=NEEDS_HUMAN, gates=report.to_dict(), solvent=solvent)
                atomic_write_json({**res.to_dict(), "membrane": membrane_info}, out_dir / "build_manifest.json")
                return res
        shape = {"cube": "cube", "dodecahedron": "dodecahedron", "octahedron": "octahedron"}[box_shape]
        if smd_box and mplan is None and lig_atom_ranges:
            padding_nm = smd_padding(modeller, lig_atom_ranges, padding_nm, smd_box, shape, report, decisions)
        if mplan is None:
            modeller.addSolvent(ff, model=water_model, padding=padding_nm * unit.nanometer, boxShape=shape,
                                positiveIon=ion_spec["positive"], negativeIon=ion_spec["negative"],
                                ionicStrength=ion_spec["concentration_molar"] * unit.molar, neutralize=ion_spec["neutralize"])
        ionic_strength_molar = ion_spec["concentration_molar"]
        if decisions and mplan is None:
            vecs = modeller.topology.getPeriodicBoxVectors()
            vol = abs(float(np.linalg.det(np.array([[v.x, v.y, v.z] for v in vecs])))) if vecs else 0.0
            n_w = sum(1 for r in modeller.topology.residues() if r.name in {"HOH", "WAT"})
            cube_equiv = {"dodecahedron": 1.0 / 0.7071, "octahedron": 1.0 / 0.7698, "cube": 1.0}[shape]
            decisions.record("build.solvate", "box",
                             {"shape": shape, "padding_nm": padding_nm, "ionic_strength_M": ionic_strength_molar, "volume_nm3": round(vol, 1),
                              "n_water": n_w},
                             f"{shape}、padding {padding_nm} nm、{n_w} 個水、體積 {vol:.0f} nm³"
                             + (f"（同樣影像距離的立方盒要多 {100 * (cube_equiv - 1):.0f}% 水）" if shape != "cube" else "")
                             + f"；{ion_spec['positive']}{ion_spec['negative']} 鹽濃度 {ion_spec['concentration_molar']} M"
                             + ("，並以同種離子中和溶質淨電荷" if ion_spec["neutralize"] else "，不中和淨電荷（PME 會加均勻背景電荷）")
                             + "（離子數見 build_manifest 的 n_ions；鹽只佔原子數 < 1%，算力在水）。"
                             "padding 是溶質到自己週期影像的最小距離（OpenMM：盒寬 = 2×溶質半徑 + padding，只加一次；D-99 更正）。")
    if not implicit:
        # D-102: remove waters OpenMM placed overlapping (membrane + plain solvent) before the system is built, or the
        # first MD steps NaN.  A NEEDS_HUMAN here means an overlap a water removal cannot fix (water fused into solute).
        wat = remove_overlapping_waters(modeller, report, decisions)
        if mplan is not None and report.ok and (membrane_info or {}).get("lipid_atom_ranges"):
            # D-104: last live 3D snapshot of a membrane build; indices recomputed because waters were deleted
            from . import membrane as MB
            from .live3d import snapshot_modeller
            n0 = int(membrane_info["lipid_atom_ranges"][0][0])
            lip = MB.lipid_atom_indices(modeller.topology, n0)
            snapshot_modeller(out_dir, "declashed", modeller, lipid_indices=lip, head_indices=MB.head_atoms(modeller.topology, lip),
                              note=f"removed {int((wat or {}).get('removed', 0))} waters")
        if not report.ok:
            res = BuildResult(status=NEEDS_HUMAN, gates=report.to_dict(), solvent=solvent)
            atomic_write_json(res.to_dict(), out_dir / "build_manifest.json")
            return res
    counts = {}
    n_water = 0
    for res_ in modeller.topology.residues():
        if res_.name in {"HOH", "WAT"}:
            n_water += 1
        elif res_.name in ION_RESNAMES:
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
    if membrane_info.get("head_atom_indices"):
        from .membrane import add_headgroup_restraints
        restr["lipid_head"] = add_headgroup_restraints(system, modeller.topology, modeller.positions,
                                                       membrane_info["head_atom_indices"])
    if lm_contacts and ligand_metal == "restrain":
        # atom indices are stable: solvent and ions are appended after the contacts were measured (D-53)
        from .metal import add_ligand_metal_restraints
        restr["ligand_metal"] = add_ligand_metal_restraints(system, lm_contacts, periodic=not implicit)
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
    atomic_write_json({**res.to_dict(), "created_at": now_iso(), **({"implicit_solvent": gb_info} if implicit else {}),
                       **({"membrane": membrane_info} if membrane_info else {})},
                      out_dir / "build_manifest.json")
    return res


def _consistent_ladders(small: list, decisions, report) -> dict:
    """D-60: every small-molecule ligand in one system gets the same force field and charge model when possible.
    Mixing OpenFF Sage (NAGL charges) with GAFF2 (AM1-BCC) inside one pocket changes the ligand–ligand balance in ways
    no one can attribute afterwards.  Pass 1: each ligand's own preference; pass 2 (mixed): the first provider every
    ligand supports.  If none is common, the mix stays and an advisory gate says so."""
    from rdkit import Chem
    mols = {r.name: Chem.SDMolSupplier(r.sdf_path, removeHs=False)[0] for r in small}
    lad = {r.name: parameter_ladder(mols[r.name], prefer=((r.provider,) if r.provider else ("openff-sage", "gaff2")), decisions=None)
           for r in small}
    kinds = {n: (l.get("provider"), l.get("charge_method")) for n, l in lad.items() if l.get("generator")}
    if len(small) < 2 or len(set(kinds.values())) <= 1:
        return lad
    for target in ("openff-sage", "gaff2"):
        trial = {n: (lad[n] if kinds.get(n, (None,))[0] == target else parameter_ladder(mols[n], prefer=(target,), decisions=None))
                 for n in lad}
        if all(t.get("generator") for t in trial.values()) and len({t.get("charge_method") for t in trial.values()}) == 1:
            if decisions:
                decisions.record("build.ligand_ff", "consistency", target,
                                 f"多配體系統原本混用力場／電荷模型（{kinds}），統一為 {target}，讓配體之間的作用在同一套參數下比較；"
                                 "代價是個別配體可能不是其最佳選項。", kind="auto_fixed")
            report.add(Gate("ligand force-field consistency", AUTO_FIXED,
                            f"多個配體原本使用不同力場或電荷模型（{kinds}），已統一為 {target}。"))
            return trial
    report.add(Gate("ligand force-field consistency", AUTO_FIXED,
                    f"多個配體無法使用同一套力場與電荷模型（{kinds}）；仍可模擬，但配體之間的相對比較含有力場差異，報告會標註。",
                    advisory=True))
    return lad


def _geometry_backstop(modeller, lig_atom_ranges, n_protein, report, decisions, accept: bool, ff=None) -> None:
    """D-60: last check on the assembled complex with every hydrogen (Vina never saw the non-polar ones): overlaps
    and ring piercing per ligand; a rigid nudge ≤ 2 Å RMSD is applied in place (AUTO_FIXED), otherwise NEEDS_HUMAN."""
    from . import multi_ligand as ML
    from openmm import unit
    nm = np.asarray(modeller.positions.value_in_unit(unit.nanometer)) * 10.0
    atoms = list(modeller.topology.atoms())
    el = [(a.element.symbol if a.element is not None else "X") for a in atoms]
    def bonds_in(lo, hi):
        return [(b[0].index - lo, b[1].index - lo) for b in modeller.topology.bonds()
                if lo <= b[0].index < hi and lo <= b[1].index < hi]
    ligs = [ML.Mol(name, el[a:b], nm[a:b], bonds_in(a, b) or None) for name, a, b in lig_atom_ranges]
    around = np.vstack([l.xyz for l in ligs])
    lo, hi = around.min(0) - 10, around.max(0) + 10
    near = [i for i in range(n_protein) if np.all((nm[i] >= lo) & (nm[i] <= hi))]
    keep_res = {atoms[i].residue.index for i in near}
    pidx = [i for i in range(n_protein) if atoms[i].residue.index in keep_res]
    prot = ML.Mol("protein", [el[i] for i in pidx], nm[pidx], is_protein=True) if pidx else None
    r = ML.resolve(ligs, prot, accept=accept, pose_entry=(ligs[0].name if len(ligs) == 1 else "joint"))
    if r["status"] == "PASS":
        return
    if r["adjusted"]:                        # nudges first, so a soft-core repair starts from them
        from openmm import Vec3
        pos = list(modeller.positions.value_in_unit(unit.nanometer))
        for name, a, b in lig_atom_ranges:
            if name in r["adjusted"]:
                for k, x in enumerate(r["adjusted"][name]["xyz"]):
                    pos[a + k] = Vec3(*(x / 10.0))
                for l in ligs:
                    if l.name == name:
                        l.xyz = np.asarray(r["adjusted"][name]["xyz"])
        modeller.positions = unit.Quantity(pos, unit.nanometer)
    if r["status"] == "NEEDS_HUMAN" and ff is not None and not r["auto_excluded"]:
        sc = _softcore_repair(modeller, ff, lig_atom_ranges, ligs, prot, r, decisions)
        if sc is not None:
            report.add(Gate("ligand geometry (with hydrogens)", AUTO_FIXED, sc))
            return
    if r["auto_excluded"] and len(ligs) > 1:
        # removing atoms here would desynchronise every index downstream: the workflow-level check does exclusions
        r["status"] = "ACCEPTED" if accept else "NEEDS_HUMAN"
    if r["status"] == "AUTO_FIXED":
        report.add(Gate("ligand geometry (with hydrogens)", AUTO_FIXED, r["why"][0]))
    elif r["status"] == "ACCEPTED":
        report.add(Gate("ligand geometry (with hydrogens)", AUTO_FIXED, "使用者選擇照原樣建模：" + r["why"][0], advisory=True))
    else:
        report.add(Gate("ligand geometry (with hydrogens)", NEEDS_HUMAN, r["why"][0], options=r["options"]))
    if decisions:
        decisions.record("build.geometry", "+".join(n for n, _, _ in lig_atom_ranges), r["status"], r["why"][0],
                         kind="human" if r["status"] == "NEEDS_HUMAN" else "auto_fixed")


def _softcore_repair(modeller, ff, lig_atom_ranges, ligs, prot, r, decisions) -> str | None:
    """D-61: second layer after the rigid nudge — λ-ramped soft-core relaxation of each unresolved ligand (it may pass
    through its neighbours), everything else held.  Accepted only when the geometry check then passes, the ligand moved
    ≤ 3 Å heavy-atom RMSD and kept ≥ 70 % of its protein contacts; positions are applied in place.  None = not repaired."""
    from . import multi_ligand as ML, softcore as SC
    from openmm import app, unit
    try:
        system = ff.createSystem(modeller.topology, nonbondedMethod=app.NoCutoff, constraints=None, rigidWater=False,
                                 removeCMMotion=False)
    except Exception as exc:  # noqa: BLE001
        if decisions:
            decisions.record("build.geometry", "soft-core", "unavailable", f"無法建立軟核修復用的系統（{type(exc).__name__}: {exc}），改由使用者決定。")
        return None
    pos = np.asarray(modeller.positions.value_in_unit(unit.nanometer))
    atoms = list(modeller.topology.atoms())
    heavy = np.array([a.element is not None and a.element.symbol != "H" for a in atoms])
    rng = {n: (a, b) for n, a, b in lig_atom_ranges}
    by = {l.name: l for l in ligs}
    done, notes_zh = [], []
    for _ in range(len(ligs)):
        bad = ML.culprit(ML.check(ligs, prot))
        if bad is None:
            break
        if bad in done:
            return None
        a, b = rng[bad]
        moving = list(range(a, b))
        fixed = [i for i in range(len(atoms)) if heavy[i] and not (a <= i < b)]
        base = by[bad].xyz.copy()
        base_contacts = ML.protein_contacts(by[bad], base, prot)
        new = None
        for seed in (2026, 2027, 2028):           # Langevin noise decides which way a threaded bond slides out; retry twice
            try:
                cand = SC.relax(system, pos, moving, fixed, seed=seed)
            except Exception as exc:  # noqa: BLE001
                if decisions:
                    decisions.record("build.geometry", f"soft-core {bad}", "failed", f"軟核修復失敗（seed {seed}，{type(exc).__name__}: {exc}）。")
                continue
            t = ML.Mol(bad, by[bad].elements, cand[a:b] * 10.0, by[bad].bonds, False, by[bad].rings)
            new = cand
            if ML.check([t if l.name == bad else l for l in ligs], prot)[bad]["ok"]:
                break
        if new is None:
            return None
        x = new[a:b] * 10.0
        hv = by[bad].heavy
        rmsd = float(np.sqrt(((x[hv] - base[hv]) ** 2).sum(1).mean()))
        shift = float(np.linalg.norm(x[hv].mean(0) - base[hv].mean(0)))
        trial = ML.Mol(bad, by[bad].elements, x, by[bad].bonds, False, by[bad].rings)
        # D-64 更正: pulling a threaded bond out moves that end by about a ring radius plus a contact distance, so the
        # binding mode is judged by the centroid and the protein contacts; the all-atom RMSD only catches a relocation
        if (shift > SC.ACCEPT_CENTROID_A or rmsd > SC.ACCEPT_RMSD_A
                or (prot is not None and ML.protein_contacts(trial, x, prot) < ML.KEEP_CONTACTS * base_contacts)):
            if decisions:
                decisions.record("build.geometry", f"soft-core {bad}", "rejected",
                                 f"軟核修復後 {bad} 質心移動 {shift:.1f} Å（上限 {SC.ACCEPT_CENTROID_A} Å）、RMSD {rmsd:.1f} Å（上限 {SC.ACCEPT_RMSD_A} Å）"
                                 "或失去過多接觸：已是不同姿勢，交由使用者決定。")
            return None
        by[bad].xyz = x
        for i in range(len(ligs)):
            if ligs[i].name == bad:
                ligs[i] = by[bad] = ML.Mol(bad, by[bad].elements, x, by[bad].bonds, False, by[bad].rings)
        pos[a:b] = new[a:b]
        done.append(bad)
        notes_zh.append(f"{bad} 以軟核鬆弛（λ 0.05→1，配體可暫時穿過鄰近原子，其餘原子固定）解開，質心移動 {shift:.1f} Å、重原子 RMSD {rmsd:.1f} Å")
    if ML.culprit(ML.check(ligs, prot)) is not None or not done:
        return None
    from openmm import Vec3
    cur = list(modeller.positions.value_in_unit(unit.nanometer))
    for n in done:
        a, b = rng[n]
        for k in range(a, b):
            cur[k] = Vec3(*pos[k])
    modeller.positions = unit.Quantity(cur, unit.nanometer)
    msg = "；".join(notes_zh) + "；剛體微調無法處理，第二層修復成功，結合模式保留。"
    if decisions:
        decisions.record("build.geometry", "+".join(done), "AUTO_FIXED (soft-core)", msg, kind="auto_fixed")
    return msg
