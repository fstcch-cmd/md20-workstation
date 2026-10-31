"""Ligand preparation: one RDKit molecule is the source of truth.

* chemistry (bond orders, stereo, formal charge, protonation) comes from the
  reference used *before* docking (SDF with bond orders, or SMILES);
* the docking pose contributes coordinates only, mapped heavy-atom-by-heavy-atom
  onto the reference graph; if the mapping fails we stop and say which atoms
  did not match — we never re-perceive bonds from a PDB/PDBQT;
* parameters come from a ladder: OpenFF Sage (+NAGL charges) → GAFF2/AM1-BCC
  (needs AmberTools) → NEEDS_HUMAN with the offending atoms;
* a vacuum smoke test (minimize + short MD) runs before the expensive solvated
  build so bad parameters surface in seconds.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path

from ..util import now_iso, DecisionLog, atomic_write_json
from .gates import Gate, GateReport, PASS, AUTO_FIXED, NEEDS_HUMAN


@dataclass
class LigandRecord:
    name: str                       # L01, L02 …
    resname: str                    # 3-letter residue name used in topology (L01 → "L01")
    smiles: str = ""
    formal_charge: int = 0
    n_heavy: int = 0
    n_atoms: int = 0
    sdf_path: str = ""              # final SDF: reference chemistry + pose coordinates + hydrogens
    pose_source: str = ""
    mapping: str = ""               # "substructure" | "order" | "sdf-direct"
    provider: str = ""              # "openff-sage" | "gaff2" | ""
    charge_method: str = ""
    charge_sum: float | None = None
    smoke_test: dict = field(default_factory=dict)
    gates: dict = field(default_factory=dict)
    status: str = PASS

    def to_dict(self) -> dict:
        return asdict(self)


def extract_hetatm_pose(pdb_text: str, resname: str, out_path: Path | str, *, chain: str | None = None,
                        resid: int | None = None) -> Path:
    """Write the HETATM records of one co-crystal ligand instance to a PDB file (coordinates only)."""
    lines, picked = [], None
    for line in pdb_text.splitlines():
        if not line.startswith("HETATM") or line[17:20].strip() != resname:
            continue
        key = (line[21].strip(), line[22:26].strip())
        if chain is not None and key[0] != chain:
            continue
        if resid is not None and key[1] != str(resid):
            continue
        if picked is None:
            picked = key
        if key != picked:
            continue
        if line[16].strip() not in {"", "A"}:
            continue
        lines.append(line)
    if not lines:
        raise ValueError(f"PDB 中找不到 HETATM 殘基 {resname}")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\nEND\n", encoding="utf-8")
    return out_path


# --------------------------------------------------------------------------- chemistry
def _load_reference(ref: str | Path):
    from rdkit import Chem
    ref = str(ref)
    p = Path(ref)
    if p.is_file():
        suf = p.suffix.lower()
        if suf in {".sdf", ".mol"}:
            supplier = Chem.SDMolSupplier(ref, removeHs=False) if suf == ".sdf" else [Chem.MolFromMolFile(ref, removeHs=False)]
            mols = [m for m in supplier if m is not None]
            if not mols:
                raise ValueError(f"無法讀取參考分子：{ref}")
            mol = mols[0]
        else:
            raise ValueError("參考分子必須是 SDF/MOL（含鍵序）或 SMILES 字串；PDB/PDBQT 不含鍵序，拒絕作為參考。")
    else:
        mol = Chem.MolFromSmiles(ref)
        if mol is None:
            raise ValueError(f"無法解析 SMILES：{ref}")
    mol = Chem.AddHs(mol, addCoords=mol.GetNumConformers() > 0)
    Chem.SanitizeMol(mol)
    Chem.AssignStereochemistryFrom3D(mol) if mol.GetNumConformers() else Chem.AssignStereochemistry(mol, cleanIt=True, force=True)
    return mol


def _pose_heavy_coords(pose: Path):
    """Return (heavy RDKit mol without bond orders, coords) from a pose file."""
    from rdkit import Chem
    suf = pose.suffix.lower()
    if suf == ".sdf":
        m = next((x for x in Chem.SDMolSupplier(str(pose), removeHs=False) if x is not None), None)
        if m is None:
            raise ValueError(f"無法讀取 pose SDF：{pose}")
        return Chem.RemoveHs(m, sanitize=False), "sdf"
    if suf in {".pdb", ".pdbqt"}:
        lines = []
        for line in pose.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith(("ATOM", "HETATM")):
                # PDBQT: columns 70-76 charge, 77-79 AD type; rewrite element from AD type
                if suf == ".pdbqt":
                    ad = line[77:79].strip()
                    elem = {"A": "C", "NA": "N", "OA": "O", "SA": "S", "HD": "H", "HS": "H", "Cl": "Cl", "CL": "Cl",
                            "Br": "Br", "BR": "Br", "F": "F", "I": "I", "P": "P", "C": "C", "N": "N", "O": "O", "S": "S"}.get(ad, ad[:1])
                    line = line[:76].ljust(76) + f"{elem:>2}"
                lines.append(line[:80])
            elif line.startswith("ENDMDL"):
                break
        block = "\n".join(lines) + "\nEND\n"
        m = Chem.MolFromPDBBlock(block, removeHs=False, sanitize=False, proximityBonding=True)
        if m is None:
            raise ValueError(f"無法解析 pose：{pose}")
        return Chem.RemoveHs(m, sanitize=False), suf.lstrip(".")
    raise ValueError(f"不支援的 pose 格式：{suf}")


def map_pose_onto_reference(ref_mol, pose_mol) -> tuple[list[int] | None, str, list[str]]:
    """Map pose heavy atoms → reference heavy atoms.  Returns (match, method, problems)."""
    from rdkit import Chem
    from rdkit.Chem import AllChem
    ref_heavy = Chem.RemoveHs(ref_mol)
    problems: list[str] = []
    if pose_mol.GetNumAtoms() != ref_heavy.GetNumAtoms():
        problems.append(f"重原子數不同：pose {pose_mol.GetNumAtoms()} vs 參考 {ref_heavy.GetNumAtoms()}")
        return None, "", problems
    # 1) assign bond orders from template, then exact substructure match
    try:
        templ = AllChem.AssignBondOrdersFromTemplate(ref_heavy, pose_mol)
        match = templ.GetSubstructMatch(ref_heavy, useChirality=False)
        if match and len(match) == ref_heavy.GetNumAtoms():
            return list(match), "substructure", problems
    except Exception as exc:  # noqa: BLE001
        problems.append(f"template bond-order assignment failed: {type(exc).__name__}: {exc}")
    # 2) element-wise order match (same atom order, e.g. Meeko preserves it)
    same = all(a.GetAtomicNum() == b.GetAtomicNum() for a, b in zip(ref_heavy.GetAtoms(), pose_mol.GetAtoms()))
    if same:
        problems.append("使用原子順序對應（元素逐一相同）；請確認 pose 與參考來自同一準備流程。")
        return list(range(ref_heavy.GetNumAtoms())), "order", problems
    mism = [f"{i}:{a.GetSymbol()}≠{b.GetSymbol()}" for i, (a, b) in enumerate(zip(ref_heavy.GetAtoms(), pose_mol.GetAtoms()))
            if a.GetAtomicNum() != b.GetAtomicNum()]
    problems.append("元素序列不一致：" + ", ".join(mism[:10]))
    return None, "", problems


def apply_pose_coordinates(ref_mol, pose_mol, match: list[int]):
    """Set reference heavy-atom coordinates from the pose, then place hydrogens."""
    from rdkit import Chem
    from rdkit.Chem import AllChem
    from rdkit.Geometry import Point3D
    ref_heavy_idx = [a.GetIdx() for a in ref_mol.GetAtoms() if a.GetAtomicNum() > 1]
    conf_pose = pose_mol.GetConformer()
    mol = Chem.Mol(ref_mol)
    if mol.GetNumConformers() == 0:
        AllChem.EmbedMolecule(mol, randomSeed=2026)
    conf = mol.GetConformer()
    # match[i] is the pose atom index for reference-heavy atom i
    for i, pose_idx in enumerate(match):
        p = conf_pose.GetAtomPosition(pose_idx)
        conf.SetAtomPosition(ref_heavy_idx[i], Point3D(p.x, p.y, p.z))
    # re-place hydrogens around fixed heavy atoms
    heavy = Chem.RemoveHs(mol)
    heavy_conf = heavy.GetConformer()
    mol_h = Chem.AddHs(heavy, addCoords=True)
    # optimise only hydrogens with MMFF to remove clashes
    try:
        props = AllChem.MMFFGetMoleculeProperties(mol_h)
        ff = AllChem.MMFFGetMoleculeForceField(mol_h, props)
        for a in mol_h.GetAtoms():
            if a.GetAtomicNum() > 1:
                ff.AddFixedPoint(a.GetIdx())
        ff.Minimize(maxIts=200)
    except Exception:  # noqa: BLE001
        pass
    return mol_h


# --------------------------------------------------------------------------- parameters
def parameter_ladder(mol, *, prefer: tuple[str, ...] = ("openff-sage", "gaff2"), decisions: DecisionLog | None = None) -> dict:
    """Try providers in order; return {"provider", "generator", "charge_method", "errors"}."""
    errors = {}
    for name in prefer:
        try:
            if name == "openff-sage":
                from openff.toolkit import Molecule
                from openmmforcefields.generators import SMIRNOFFTemplateGenerator
                offmol = Molecule.from_rdkit(mol, allow_undefined_stereo=True)
                charge_method = "nagl"
                try:
                    from openff.toolkit.utils.nagl_wrapper import NAGLToolkitWrapper  # noqa: F401
                    offmol.assign_partial_charges("openff-gnn-am1bcc-0.1.0-rc.3.pt", toolkit_registry=NAGLToolkitWrapper())
                except Exception as exc:  # noqa: BLE001
                    charge_method = "am1bcc"
                    errors["nagl"] = f"{type(exc).__name__}: {exc}"
                    offmol.assign_partial_charges("am1bcc")  # needs AmberTools (sqm); not on Windows
                gen = SMIRNOFFTemplateGenerator(molecules=[offmol], forcefield="openff-2.2.0.offxml")
                if decisions:
                    decisions.record("build.ligand", "parameters", "OpenFF Sage 2.2 + " + charge_method,
                                     "預設路徑：純 Python、三平台一致；NAGL 為 ML 電荷（AM1-BCC 等級），無需 QM。")
                return {"provider": "openff-sage", "generator": gen, "charge_method": charge_method, "errors": errors,
                        "offmol": offmol}
            if name == "gaff2":
                from openff.toolkit import Molecule
                from openmmforcefields.generators import GAFFTemplateGenerator
                offmol = Molecule.from_rdkit(mol, allow_undefined_stereo=True)
                gen = GAFFTemplateGenerator(molecules=[offmol], forcefield="gaff-2.11")
                if decisions:
                    decisions.record("build.ligand", "parameters", "GAFF2 + AM1-BCC (antechamber)",
                                     "OpenFF 不可用時的替代；需要 AmberTools（Windows 原生不提供）。")
                return {"provider": "gaff2", "generator": gen, "charge_method": "am1bcc", "errors": errors, "offmol": offmol}
        except Exception as exc:  # noqa: BLE001
            errors[name] = f"{type(exc).__name__}: {str(exc)[:400]}"
    return {"provider": "", "generator": None, "charge_method": "", "errors": errors}


def vacuum_smoke_test(mol, generator, *, md_ps: float = 1.0, timestep_fs: float = 1.0) -> dict:
    """Minimize + short vacuum MD of the ligand alone.  Catches bad parameters in seconds."""
    import numpy as np
    import openmm as mm
    from openmm import app, unit
    from openff.toolkit import Molecule
    offmol = Molecule.from_rdkit(mol, allow_undefined_stereo=True)
    top = offmol.to_topology().to_openmm()
    ff = app.ForceField()
    ff.registerTemplateGenerator(generator.generator)
    system = ff.createSystem(top, nonbondedMethod=app.NoCutoff, constraints=app.HBonds)
    integ = mm.LangevinMiddleIntegrator(300 * unit.kelvin, 1 / unit.picosecond, timestep_fs * unit.femtoseconds)
    sim = app.Simulation(top, system, integ, mm.Platform.getPlatformByName("CPU"))
    pos = mol.GetConformer().GetPositions() / 10.0
    sim.context.setPositions(pos * unit.nanometer)
    e0 = sim.context.getState(getEnergy=True).getPotentialEnergy()._value
    sim.minimizeEnergy(maxIterations=500)
    e1 = sim.context.getState(getEnergy=True).getPotentialEnergy()._value
    sim.context.setVelocitiesToTemperature(300 * unit.kelvin, 1)
    sim.step(int(md_ps * 1000 / timestep_fs))
    st = sim.context.getState(getEnergy=True, getPositions=True)
    e2 = st.getPotentialEnergy()._value
    xyz = st.getPositions(asNumpy=True)._value
    # bond length sanity vs. reference geometry (heavy-heavy)
    conf = mol.GetConformer()
    dev = []
    for b in mol.GetBonds():
        i, j = b.GetBeginAtomIdx(), b.GetEndAtomIdx()
        if mol.GetAtomWithIdx(i).GetAtomicNum() > 1 and mol.GetAtomWithIdx(j).GetAtomicNum() > 1:
            r0 = np.linalg.norm(np.array(conf.GetAtomPosition(i)) - np.array(conf.GetAtomPosition(j))) / 10.0
            r1 = float(np.linalg.norm(xyz[i] - xyz[j]))
            dev.append(abs(r1 - r0) / r0)
    max_dev = float(max(dev)) if dev else 0.0
    finite = all(np.isfinite([e0, e1, e2])) and np.isfinite(xyz).all()
    ok = finite and max_dev < 0.15
    return {"ok": bool(ok), "e_initial": e0, "e_minimized": e1, "e_after_md": e2, "max_bond_deviation": max_dev,
            "md_ps": md_ps, "note": "" if ok else ("能量非有限" if not finite else "鍵長偏離參考 >15%，參數可疑")}


# --------------------------------------------------------------------------- driver
def prepare_ligand(reference: str | Path, pose: Path | str | None, out_dir: Path | str, *, name: str = "L01",
                   expected_charge: int | None = None, decisions: DecisionLog | None = None,
                   run_smoke_test: bool = True) -> LigandRecord:
    from rdkit import Chem
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rec = LigandRecord(name=name, resname=name[:3].upper())
    report = GateReport()
    ref = _load_reference(reference)
    rec.smiles = Chem.MolToSmiles(Chem.RemoveHs(ref))
    rec.formal_charge = int(Chem.GetFormalCharge(ref))
    rec.n_heavy = ref.GetNumHeavyAtoms()
    if expected_charge is not None and expected_charge != rec.formal_charge:
        report.add(Gate("formal charge", NEEDS_HUMAN,
                        f"參考分子形式電荷 {rec.formal_charge} 與預期 {expected_charge} 不符；通常是質子化狀態設定錯誤（docking 與 MD 的 pH 不一致）。",
                        options=["以參考分子為準", "重新以 pH 質子化（Dimorphite-DL）"]))
    mol = ref
    if pose is not None:
        pose = Path(pose)
        rec.pose_source = str(pose)
        pose_mol, kind = _pose_heavy_coords(pose)
        match, method, problems = map_pose_onto_reference(ref, pose_mol)
        if match is None:
            report.add(Gate("pose mapping", NEEDS_HUMAN,
                            "docking pose 的原子無法對應到參考分子；不猜測鍵結。" + " ".join(problems),
                            options=["提供 docking 前的 SDF", "改用 pose SDF（Meeko/Vina --out sdf）"], evidence={"problems": problems}))
        else:
            rec.mapping = method
            if method == "order":
                report.add(Gate("pose mapping", AUTO_FIXED, problems[-1]))
            else:
                report.add(Gate("pose mapping", PASS, f"{rec.n_heavy} 個重原子以子結構比對一一對應。"))
            mol = apply_pose_coordinates(ref, pose_mol, match)
            report.add(Gate("hydrogens", AUTO_FIXED, "pose 的氫全部捨棄，依參考化學重新加氫並以 MMFF 鬆弛（重原子固定）。"))
    else:
        if mol.GetNumConformers() == 0:
            from rdkit.Chem import AllChem
            AllChem.EmbedMolecule(mol, randomSeed=2026)
            AllChem.MMFFOptimizeMolecule(mol)
            report.add(Gate("3D", AUTO_FIXED, "參考分子無 3D 座標，以 ETKDG + MMFF 產生。"))
    rec.n_atoms = mol.GetNumAtoms()
    mol.SetProp("_Name", name)
    sdf = out_dir / f"{name}.sdf"
    w = Chem.SDWriter(str(sdf)); w.write(mol); w.close()
    rec.sdf_path = str(sdf)
    if report.ok:
        ladder = parameter_ladder(mol, decisions=decisions)
        rec.provider, rec.charge_method = ladder["provider"], ladder["charge_method"]
        if not ladder["generator"]:
            report.add(Gate("parameters", NEEDS_HUMAN,
                            "所有參數化路徑都失敗。OpenFF：%s；GAFF2：%s" % (ladder["errors"].get("openff-sage", "—"), ladder["errors"].get("gaff2", "—")),
                            options=["安裝 openff-toolkit + openff-nagl", "使用 Sobtop 進階路徑", "回報給老師"],
                            evidence=ladder["errors"]))
        else:
            try:
                q = [float(x) for x in ladder["offmol"].partial_charges.magnitude]
                rec.charge_sum = float(sum(q))
                if abs(rec.charge_sum - rec.formal_charge) > 0.05:
                    report.add(Gate("charge sum", NEEDS_HUMAN, f"部分電荷總和 {rec.charge_sum:.3f} 與形式電荷 {rec.formal_charge} 不符。"))
                else:
                    report.add(Gate("charge sum", PASS, f"部分電荷總和 {rec.charge_sum:.3f} = 形式電荷 {rec.formal_charge}。"))
            except Exception as exc:  # noqa: BLE001
                report.add(Gate("charge sum", AUTO_FIXED, f"無法讀取部分電荷（{exc}），改在組裝後檢查總電荷。"))
            if run_smoke_test and report.ok:
                try:
                    rec.smoke_test = vacuum_smoke_test(mol, ladder["generator"])
                    report.add(Gate("vacuum smoke test", PASS if rec.smoke_test["ok"] else NEEDS_HUMAN,
                                    ("真空最小化 + 1 ps MD 穩定；參數可用。" if rec.smoke_test["ok"] else
                                     "真空 MD 不穩定：" + rec.smoke_test["note"]), evidence=rec.smoke_test))
                except Exception as exc:  # noqa: BLE001
                    report.add(Gate("vacuum smoke test", NEEDS_HUMAN, f"煙霧測試本身失敗：{type(exc).__name__}: {exc}"))
    rec.gates = report.to_dict()
    rec.status = report.status
    atomic_write_json({**rec.to_dict(), "created_at": now_iso()}, out_dir / f"{name}_manifest.json")
    return rec
