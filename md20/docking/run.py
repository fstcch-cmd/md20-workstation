"""Run AutoDock Vina (python bindings) in `independent` or `simultaneous` mode.

Outputs (out_dir/):
  receptor.pdbqt
  ligands/<name>.pdbqt, <name>_input.sdf
  independent/<name>/pose_01.sdf …       (one SDF per pose, chemistry from Meeko SMILES; props: score, rank)
  simultaneous/pose_01_<name>.sdf …      (joint poses: same rank across ligands belongs together)
  docking_results.json, docking_scores.csv
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np

from ..util import atomic_write_json, now_iso, DecisionLog
from .box import Box
from .poses import analyse_poses, recommend_pose, PoseInfo, pocket_volume, HEAVY_ATOM_VOLUME_A3
from .receptor_pdbqt import receptor_to_pdbqt


@dataclass
class LigandInput:
    name: str
    smiles: str = ""
    sdf: str = ""                      # SDF with bond orders (preferred when available)
    reference_pose: str = ""           # optional crystal pose (PDB/SDF) for RMSD
    reference_resname: str = ""        # or: HETATM residue name inside the receptor file


@dataclass
class DockingResult:
    mode: str
    receptor_pdbqt: str
    box: dict
    params: dict
    entries: list[dict] = field(default_factory=list)   # one per ligand (independent) or one joint entry
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    def entry(self, name: str) -> dict:
        for e in self.entries:
            if e["name"] == name:
                return e
        raise KeyError(name)

    @classmethod
    def load(cls, path: Path | str) -> "DockingResult":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        from dataclasses import fields as _fields
        known = {f.name for f in _fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})      # drops the HCC Lab stamp key `_md20`


# --------------------------------------------------------------------------- ligand prep
def _ligand_mol(lig: LigandInput):
    from rdkit import Chem
    from rdkit.Chem import AllChem
    if lig.sdf:
        mol = next(m for m in Chem.SDMolSupplier(lig.sdf, removeHs=False) if m is not None)
        mol = Chem.AddHs(mol, addCoords=True)
    else:
        mol = Chem.MolFromSmiles(lig.smiles)
        if mol is None:
            raise ValueError(f"{lig.name}: 無法解析 SMILES {lig.smiles}")
        mol = Chem.AddHs(mol)
        params = AllChem.ETKDGv3(); params.randomSeed = 2026
        if AllChem.EmbedMolecule(mol, params) != 0:
            AllChem.EmbedMolecule(mol, randomSeed=2026, useRandomCoords=True)
        try:
            AllChem.MMFFOptimizeMolecule(mol, maxIters=2000)
        except Exception:  # noqa: BLE001
            AllChem.UFFOptimizeMolecule(mol, maxIters=2000)
    mol.SetProp("_Name", lig.name)
    return mol


def _meeko_pdbqt(mol) -> str:
    from meeko import MoleculePreparation
    prep = MoleculePreparation()
    try:  # meeko ≥ 0.5
        from meeko import PDBQTWriterLegacy
        setups = prep.prepare(mol)
        s, ok, err = PDBQTWriterLegacy.write_string(setups[0])
        if not ok:
            raise RuntimeError(err)
        return s
    except ImportError:  # meeko 0.4
        prep.prepare(mol)
        return prep.write_pdbqt_string()


def _poses_to_rdkit(pdbqt_out: str):
    """Docked PDBQT string → list of RDKit mols (one per ligand), each with one conformer per pose."""
    from meeko import PDBQTMolecule, RDKitMolCreate
    pmol = PDBQTMolecule(pdbqt_out, is_dlg=False, skip_typing=True)
    mols = RDKitMolCreate.from_pdbqt_mol(pmol)
    return [m for m in mols if m is not None]


def _heavy_xyz(mol, conf_id: int) -> np.ndarray:
    conf = mol.GetConformer(conf_id)
    return np.array([list(conf.GetAtomPosition(a.GetIdx())) for a in mol.GetAtoms() if a.GetAtomicNum() > 1])


def _reference_heavy(mol, lig: LigandInput, receptor_pdb: Path) -> np.ndarray | None:
    """Reference pose heavy coords in the heavy-atom order of `mol` (bond orders from mol, never from PDB)."""
    from rdkit import Chem
    from ..build.ligand import _pose_heavy_coords, map_pose_onto_reference, extract_hetatm_pose
    src = lig.reference_pose
    if not src and lig.reference_resname:
        src = str(extract_hetatm_pose(receptor_pdb.read_text(encoding="utf-8", errors="ignore"), lig.reference_resname,
                                      receptor_pdb.parent / f"_ref_{lig.name}.pdb"))
    if not src:
        return None
    pose_mol, _ = _pose_heavy_coords(Path(src))
    match, _, _ = map_pose_onto_reference(mol, pose_mol)
    if match is None:
        return None
    conf = pose_mol.GetConformer()
    return np.array([list(conf.GetAtomPosition(j)) for j in match])


def _write_pose_sdf(mol, conf_id: int, path: Path, props: dict) -> None:
    from rdkit import Chem
    m = Chem.Mol(mol)
    conf = Chem.Conformer(mol.GetConformer(conf_id))
    m.RemoveAllConformers(); m.AddConformer(conf, assignId=True)
    for k, v in props.items():
        m.SetProp(k, str(v))
    from ..util.stamp import stamp_rdkit_mol
    stamp_rdkit_mol(m)
    path.parent.mkdir(parents=True, exist_ok=True)
    w = Chem.SDWriter(str(path)); w.write(m); w.close()


def _symmetric_rmsd_fn(mol):
    """RMSD that respects molecular symmetry (ring flips, equivalent N), no alignment (same frame)."""
    from rdkit import Chem
    from rdkit.Chem import rdMolAlign
    heavy = Chem.RemoveHs(mol)
    def to_mol(xyz):
        m = Chem.Mol(heavy); c = m.GetConformer() if m.GetNumConformers() else Chem.Conformer(m.GetNumAtoms())
        if not m.GetNumConformers():
            m.AddConformer(c, assignId=True); c = m.GetConformer()
        for i, p in enumerate(xyz):
            c.SetAtomPosition(i, [float(v) for v in p])
        return m
    def rmsd(a, b):
        try:
            return float(rdMolAlign.CalcRMS(to_mol(a), to_mol(b)))
        except Exception:  # noqa: BLE001
            return float(np.sqrt(np.mean(np.sum((np.asarray(a) - np.asarray(b)) ** 2, axis=1))))
    return rmsd


# --------------------------------------------------------------------------- main
def dock(receptor_pdb: Path | str, ligands: list[LigandInput], box: Box, out_dir: Path | str, *,
         mode: str = "independent", scoring: str = "vina", exhaustiveness: int = 16, n_poses: int = 9,
         energy_range: float = 3.0, seed: int = 2026, cpu: int = 0, decisions: DecisionLog | None = None,
         progress_cb=None) -> DockingResult:
    try:
        from vina import Vina
        vina_exe = None
    except ImportError:
        from .vina_cli import ensure_vina_exe
        Vina, vina_exe = None, ensure_vina_exe()
    if mode not in {"independent", "simultaneous"}:
        raise ValueError("mode 必須是 independent 或 simultaneous")
    if mode == "simultaneous" and len(ligands) < 2:
        raise ValueError("simultaneous 模式至少需要 2 個配體")
    receptor_pdb, out = Path(receptor_pdb), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rec_pdbqt = out / "receptor.pdbqt"
    types = receptor_to_pdbqt(receptor_pdb, rec_pdbqt)
    rec_xyz = np.array([[float(l[30:38]), float(l[38:46]), float(l[46:54])]
                        for l in rec_pdbqt.read_text().splitlines() if l.startswith(("ATOM", "HETATM")) and not l.rstrip().endswith("HD")])
    params = {"scoring": scoring, "exhaustiveness": exhaustiveness, "n_poses": n_poses, "energy_range": energy_range,
              "seed": seed, "cpu": cpu, "receptor_types": types}
    if decisions:
        decisions.record("docking.setup", "mode", mode,
                         "independent：每個配體各自對接並排名（HTS）；simultaneous：多配體同時放進同一 box，回答「能否共同佔位」。")
        decisions.record("docking.setup", "box", box.to_dict(), box.note or "使用者指定的 box。")
    lig_dir = out / "ligands"; lig_dir.mkdir(exist_ok=True)
    mols, pdbqts = {}, {}
    for lig in ligands:
        mol = _ligand_mol(lig)
        mols[lig.name] = mol
        pdbqts[lig.name] = _meeko_pdbqt(mol)
        (lig_dir / f"{lig.name}.pdbqt").write_text(pdbqts[lig.name], encoding="utf-8")
        from rdkit import Chem
        from ..util.stamp import stamp_rdkit_mol
        stamp_rdkit_mol(mol)
        w = Chem.SDWriter(str(lig_dir / f"{lig.name}_input.sdf")); w.write(mol); w.close()
    res = DockingResult(mode=mode, receptor_pdbqt=str(rec_pdbqt), box=box.to_dict(), params=params)

    if decisions:
        decisions.record("docking.setup", "engine", "vina python bindings" if vina_exe is None else f"vina executable {vina_exe}",
                         "優先用 Python bindings；Windows 上 pip 套件無法編譯時改用官方執行檔（結果相同）。")

    def run_vina(ligand_strings):
        if vina_exe is not None:
            from .vina_cli import run_vina_cli
            return run_vina_cli(vina_exe, str(rec_pdbqt), ligand_strings, box.center, box.size, scoring=scoring,
                                exhaustiveness=exhaustiveness, n_poses=n_poses, energy_range=energy_range, seed=seed, cpu=cpu)
        v = Vina(sf_name=scoring, cpu=int(cpu), seed=int(seed), verbosity=0)
        v.set_receptor(str(rec_pdbqt))
        v.set_ligand_from_string(ligand_strings if len(ligand_strings) > 1 else ligand_strings[0])
        v.compute_vina_maps(center=list(box.center), box_size=list(box.size))
        v.dock(exhaustiveness=int(exhaustiveness), n_poses=int(n_poses))
        poses = v.poses(n_poses=int(n_poses), energy_range=float(energy_range))
        energies = np.asarray(v.energies(n_poses=int(n_poses), energy_range=float(energy_range)))[:, 0]
        return poses, energies

    if mode == "independent":
        for i, lig in enumerate(ligands, 1):
            if progress_cb:
                progress_cb({"stage": "docking", "ligand": lig.name, "i": i, "n": len(ligands)})
            pose_str, energies = run_vina([pdbqts[lig.name]])
            (out / "independent" / lig.name).mkdir(parents=True, exist_ok=True)
            (out / "independent" / lig.name / "docked.pdbqt").write_text(pose_str, encoding="utf-8")
            dmol = _poses_to_rdkit(pose_str)[0]
            n = min(dmol.GetNumConformers(), len(energies))
            coords = [_heavy_xyz(dmol, k) for k in range(n)]
            ref = _reference_heavy(dmol, lig, receptor_pdb)
            infos = analyse_poses(coords, list(energies[:n]), receptor_xyz=rec_xyz, reference_xyz=ref,
                                  rmsd=_symmetric_rmsd_fn(dmol))
            pick = recommend_pose(infos)
            recinfo = infos[0].extra.get("recommendation", {})
            sdfs = []
            for k in range(n):
                p = out / "independent" / lig.name / f"pose_{k + 1:02d}.sdf"
                _write_pose_sdf(dmol, k, p, {"score_kcal_mol": f"{energies[k]:.3f}", "rank": k + 1, "ligand": lig.name})
                sdfs.append(str(p))
            res.entries.append({"name": lig.name, "ligands": [lig.name], "smiles": _smiles(mols[lig.name]),
                                "poses": [x.to_dict() for x in infos], "pose_sdfs": {lig.name: sdfs},
                                "recommended_rank": pick.rank if pick else None, "reason": recinfo.get("reason", ""),
                                "recommendation_status": recinfo.get("status", "NEEDS_HUMAN"),
                                "redock_rmsd": pick.rmsd_ref if pick else min((i.rmsd_ref for i in infos if i.rmsd_ref is not None), default=None)})
            if decisions:
                decisions.record("docking.pose", lig.name, f"rank {pick.rank}" if pick else "none", recinfo.get("reason", ""),
                                 kind="auto" if pick else "human")
    else:
        names = [l.name for l in ligands]
        if progress_cb:
            progress_cb({"stage": "docking", "ligand": "+".join(names), "i": 1, "n": 1})
        pose_str, energies = run_vina([pdbqts[n] for n in names])
        (out / "simultaneous").mkdir(parents=True, exist_ok=True)
        (out / "simultaneous" / "docked.pdbqt").write_text(pose_str, encoding="utf-8")
        dmols = _poses_to_rdkit(pose_str)
        if len(dmols) != len(names):
            raise RuntimeError(f"simultaneous 輸出含 {len(dmols)} 個分子，預期 {len(names)}")
        n = min(min(m.GetNumConformers() for m in dmols), len(energies))
        coords, slices, start = [], [], 0
        for m in dmols:
            k = sum(1 for a in m.GetAtoms() if a.GetAtomicNum() > 1)
            slices.append(slice(start, start + k)); start += k
        for k in range(n):
            coords.append(np.vstack([_heavy_xyz(m, k) for m in dmols]))
        refs = [_reference_heavy(m, l, receptor_pdb) for m, l in zip(dmols, ligands)]
        ref = np.vstack(refs) if all(r is not None for r in refs) else None
        infos = analyse_poses(coords, list(energies[:n]), receptor_xyz=rec_xyz, reference_xyz=ref,
                              per_ligand_slices=slices)
        from rdkit import Chem
        charges = [int(Chem.GetFormalCharge(mols[nm])) for nm in names]
        lig_vol = sum(sl.stop - sl.start for sl in slices) * HEAVY_ATOM_VOLUME_A3
        try:
            pv = pocket_volume(rec_xyz, box.center, box.size)
        except Exception:  # noqa: BLE001
            pv = None
        pick = recommend_pose(infos, ligand_charges=charges, pocket_volume_A3=pv, ligand_volume_A3=lig_vol)
        recinfo = infos[0].extra.get("recommendation", {})
        params["pocket_volume_A3"], params["ligand_volume_A3"], params["ligand_charges"] = pv, lig_vol, charges
        sdfs = {nm: [] for nm in names}
        for k in range(n):
            for m, nm in zip(dmols, names):
                p = out / "simultaneous" / f"pose_{k + 1:02d}_{nm}.sdf"
                _write_pose_sdf(m, k, p, {"score_kcal_mol": f"{energies[k]:.3f}", "rank": k + 1, "ligand": nm, "joint": "+".join(names)})
                sdfs[nm].append(str(p))
        res.entries.append({"name": "joint", "ligands": names, "smiles": {nm: _smiles(mols[nm]) for nm in names},
                            "poses": [x.to_dict() for x in infos], "pose_sdfs": sdfs,
                            "recommended_rank": pick.rank if pick else None, "reason": recinfo.get("reason", ""),
                            "recommendation_status": recinfo.get("status", "NEEDS_HUMAN")})
        if decisions:
            decisions.record("docking.pose", "joint " + "+".join(names), f"rank {pick.rank}" if pick else "none",
                             recinfo.get("reason", ""), kind="auto" if pick else "human")
    atomic_write_json(res.to_dict(), out / "docking_results.json")
    _write_csv(res, out / "docking_scores.csv")
    return res


def _smiles(mol) -> str:
    from rdkit import Chem
    return Chem.MolToSmiles(Chem.RemoveHs(mol))


def _write_csv(res: DockingResult, path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["entry", "rank", "score_kcal_mol", "cluster", "cluster_size", "contacts", "rmsd_ref", "min_ll_distance",
                    "recommended"])
        for e in res.entries:
            for p in e["poses"]:
                w.writerow([e["name"], p["rank"], p["score"], p["cluster"], p["cluster_size"], p["contacts"], p["rmsd_ref"],
                            p["min_ll_distance"], p["recommended"]])
