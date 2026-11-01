"""Receptor preparation: from the *original* structure file, never from a docking-prepared PDB.

Root causes of "the PDB broke after docking" (from the project diagnosis):
  1. PDBQT→PDB conversion loses bond orders / hydrogens / element columns;
  2. ligand residue names LIG/UNL collide, chain IDs collide;
  3. the receptor was already altered for docking (Meeko/obabel: hydrogens stripped, names changed);
  4. altlocs, insertion codes, MSE/HIS variants, missing loops, missing side-chain atoms;
  5. atom serial overflow above 99,999;
  6. docking protonation ≠ MD protonation.

Strategy: inspect (pure Python, no deps) → PDBFixer repair from the original →
gates with explicit diffs.  The docking receptor is only used to *verify*
that the cleaned receptor is the same protein (sequence/CA count), never as
input to MD.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from ..util import now_iso, DecisionLog, atomic_write_json
from .gates import Gate, GateReport, PASS, AUTO_FIXED, NEEDS_HUMAN

STANDARD_AA = {"ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE", "LEU", "LYS", "MET", "PHE",
               "PRO", "SER", "THR", "TRP", "TYR", "VAL", "HID", "HIE", "HIP", "CYX", "ASH", "GLH", "LYN"}
NONSTANDARD_MAP = {"MSE": "MET", "HSD": "HIS", "HSE": "HIS", "HSP": "HIS", "SEP": "SER", "TPO": "THR", "PTR": "TYR",
                   "CSO": "CYS", "KCX": "LYS", "MLY": "LYS", "CME": "CYS", "HYP": "PRO"}
WATER = {"HOH", "WAT", "TIP3", "TIP", "SOL", "DOD"}
COMMON_IONS = {"NA", "CL", "K", "MG", "CA", "ZN", "MN", "FE", "CU", "CO", "NI", "CD"}
COFACTOR_KEEP_DEFAULT = {"HEM", "HEC", "NAD", "NAP", "NAI", "NDP", "FAD", "FMN", "ATP", "ADP", "GTP", "GDP", "SAM", "SAH",
                         "PLP", "COA", "ZN", "MG", "MN", "FE", "CA", "FE2", "CU"}


@dataclass
class PDBInspection:
    n_atoms: int = 0
    n_hetatm: int = 0
    chains: dict = field(default_factory=dict)          # chain -> residue count
    altlocs: int = 0
    insertion_codes: int = 0
    nonstandard_residues: dict = field(default_factory=dict)
    hetero_residues: dict = field(default_factory=dict)  # resname -> count (excluding water)
    waters: int = 0
    hydrogens: int = 0
    missing_element_column: int = 0
    serial_overflow: bool = False
    duplicate_atom_names: list = field(default_factory=list)
    ca_count: int = 0
    seqres_present: bool = False
    gaps: list = field(default_factory=list)             # (chain, resid_before, resid_after) — physical breaks only
    numbering_jumps: list = field(default_factory=list)  # resid jumps with contiguous backbone (e.g. chymotrypsin numbering)
    format: str = "pdb"

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def inspect_pdb_text(text: str) -> PDBInspection:
    """Pure-Python PDB inspection (no RDKit/OpenMM) so the gate can run anywhere."""
    insp = PDBInspection()
    seen_names: dict[tuple, Counter] = defaultdict(Counter)
    last_res: dict[str, int | None] = {}
    last_ca: dict[str, tuple] = {}
    chain_res: dict[str, set] = defaultdict(set)
    for line in text.splitlines():
        rec = line[:6].strip()
        if rec == "SEQRES":
            insp.seqres_present = True
        if rec not in {"ATOM", "HETATM"}:
            continue
        insp.n_atoms += 1
        serial = line[6:11]
        if "*" in serial:
            insp.serial_overflow = True
        name = line[12:16].strip()
        altloc = line[16].strip()
        resname = line[17:20].strip()
        chain = line[21].strip() or "_"
        try:
            resid = int(line[22:26])
        except ValueError:
            resid = None
        icode = line[26].strip()
        element = line[76:78].strip() if len(line) >= 78 else ""
        if altloc and altloc != "A":
            insp.altlocs += 1
        if icode:
            insp.insertion_codes += 1
        if not element:
            insp.missing_element_column += 1
            element = name[:1]
        if element.upper() == "H":
            insp.hydrogens += 1
        key = (chain, resid, icode, resname)
        seen_names[key][(name, altloc)] += 1        # altloc A and B of the same atom are not duplicates
        if rec == "HETATM":
            insp.n_hetatm += 1
            if resname in WATER:
                insp.waters += 1
            else:
                insp.hetero_residues.setdefault(resname, set()).add((chain, resid, icode))
        else:
            if resname not in STANDARD_AA:
                insp.nonstandard_residues[resname] = insp.nonstandard_residues.get(resname, 0) + 1
            if name == "CA" and altloc in {"", "A"}:
                insp.ca_count += 1
                try:
                    xyz = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
                except ValueError:
                    xyz = None
                prev, prev_xyz = last_res.get(chain), last_ca.get(chain)
                if prev is not None and resid is not None and xyz is not None and prev_xyz is not None:
                    d = sum((a - b) ** 2 for a, b in zip(xyz, prev_xyz)) ** 0.5
                    jump = resid - prev
                    # A real chain break is physical (CA–CA > 4.2 Å), not a numbering jump.
                    # Chymotrypsin/kabat-style numbering jumps with CA–CA ≈ 3.8 Å are NOT missing residues.
                    if d > 4.2:
                        n_missing = jump - 1 if jump > 1 else max(1, round(d / 3.8) - 1)
                        insp.gaps.append((chain, prev, prev + n_missing + 1))
                    elif jump > 1:
                        insp.numbering_jumps.append((chain, prev, resid))
                last_res[chain] = resid
                if xyz is not None:
                    last_ca[chain] = xyz
        if resid is not None and resname not in WATER:
            chain_res[chain].add((resid, icode))
    insp.chains = {c: len(v) for c, v in chain_res.items()}
    insp.hetero_residues = {k: len(v) for k, v in insp.hetero_residues.items()}
    for key, counter in seen_names.items():
        dups = sorted({n for (n, _alt), c in counter.items() if c > 1})
        if dups:
            insp.duplicate_atom_names.append({"residue": key, "atoms": dups})
    return insp


JUNK_HETERO = {"SO4", "PO4", "GOL", "EDO", "PEG", "PG4", "DMS", "ACT", "ACE", "FMT", "MPD", "TRS", "EPE", "MES", "BME", "IPA",
               "NO3", "CIT", "MLI", "NH4", "AZI", "SCN", "BCT", "CO3", "IOD", "BR", "NA", "CL", "K"}


def gate_inspection(insp: PDBInspection, *, keep_hetero: set[str], max_auto_gap: int = 6,
                    ligand_resnames: set[str] = frozenset()) -> GateReport:
    rep = GateReport()
    if insp.serial_overflow:
        rep.add(Gate("atom serial", AUTO_FIXED, "原子序號超過 99,999（PDB 格式限制）；內部改用 PDBx/mmCIF，不影響建模。"))
    if insp.altlocs:
        rep.add(Gate("altloc", AUTO_FIXED, f"發現 {insp.altlocs} 個替代構象原子，保留 occupancy 最高（A）者。",
                     diff=[f"removed altloc atoms: {insp.altlocs}"]))
    if insp.insertion_codes:
        rep.add(Gate("insertion code", AUTO_FIXED, f"{insp.insertion_codes} 個原子含 insertion code；殘基將重新連號，原編號記錄於 mapping。"))
    if insp.missing_element_column:
        rep.add(Gate("element column", AUTO_FIXED, f"{insp.missing_element_column} 個原子缺 element 欄，依原子名第一字元推斷。",
                     options=["接受推斷", "改用 mmCIF 原始檔"]))
    if insp.nonstandard_residues:
        mapped = {k: NONSTANDARD_MAP.get(k) for k in insp.nonstandard_residues}
        unknown = [k for k, v in mapped.items() if v is None]
        known = {k: v for k, v in mapped.items() if v}
        if known:
            rep.add(Gate("nonstandard residues", AUTO_FIXED, "非標準殘基以標準對應取代（例：MSE→MET，Se→S）。",
                         diff=[f"{k} → {v} ({insp.nonstandard_residues[k]} atoms)" for k, v in known.items()]))
        if unknown:
            rep.add(Gate("unknown residues", NEEDS_HUMAN,
                         f"無法自動對應的殘基：{', '.join(unknown)}。它們可能是修飾殘基或共價配體；Amber 力場沒有參數。",
                         options=["移除並記錄", "視為配體走參數化階梯", "手動提供參數"], evidence={"residues": unknown}))
    if insp.numbering_jumps:
        rep.add(Gate("numbering jumps", PASS, f"{len(insp.numbering_jumps)} 處殘基編號跳號但主鏈連續（CA–CA ≈ 3.8 Å），"
                     "屬於編號慣例（例如 chymotrypsin numbering），不是缺失殘基。",
                     diff=[f"chain {c}: {a}→{b}" for c, a, b in insp.numbering_jumps[:12]]))
    long_gaps = [g for g in insp.gaps if g[2] - g[1] - 1 > max_auto_gap]
    short_gaps = [g for g in insp.gaps if g[2] - g[1] - 1 <= max_auto_gap]
    if short_gaps:
        rep.add(Gate("missing loops (short)", AUTO_FIXED, f"{len(short_gaps)} 段 ≤{max_auto_gap} 殘基的缺口由 PDBFixer 依 SEQRES 補建。",
                     diff=[f"chain {c}: {a}…{b} ({b - a - 1} res)" for c, a, b in short_gaps]))
    if long_gaps:
        rep.add(Gate("missing loops (long)", NEEDS_HUMAN,
                     "有超過 %d 殘基的缺失 loop；自動補建的長 loop 構形不可靠，會影響結合口袋附近的動力學。" % max_auto_gap,
                     diff=[f"chain {c}: {a}…{b} ({b - a - 1} res)" for c, a, b in long_gaps],
                     options=["截斷（加 ACE/NME 端帽）", "以 PDBFixer 補建並接受風險", "改用 AlphaFold 模型"]))
    het = {k: v for k, v in insp.hetero_residues.items() if k not in COMMON_IONS}
    lig = [k for k in het if k in ligand_resnames]
    junk = [k for k in het if k in JUNK_HETERO and k not in keep_hetero and k not in ligand_resnames]
    unknown_het = [k for k in het if k not in keep_hetero and k not in ligand_resnames and k not in JUNK_HETERO]
    kept = [k for k in het if k in keep_hetero]
    if lig:
        rep.add(Gate("co-crystal ligand", AUTO_FIXED, "共結晶配體由配體流程處理（座標作為 pose、化學來自參考分子）：" + ", ".join(lig)))
    if junk:
        rep.add(Gate("buffer / additives", AUTO_FIXED, "移除結晶添加物（緩衝鹽、甘油、PEG 等）：" + ", ".join(junk),
                     options=["移除（預設）", "保留"]))
    if kept:
        rep.add(Gate("cofactors kept", PASS, "保留輔因子：" + ", ".join(kept)))
    if unknown_het:
        rep.add(Gate("hetero groups", NEEDS_HUMAN,
                     "受體含非蛋白分子（可能是共結晶配體、緩衝液、甘油、PEG）：" + ", ".join(unknown_het) +
                     "。預設移除；若其中有要保留的輔因子或參考配體，請選擇。",
                     options=["全部移除（預設）", "保留並參數化", "保留為參考配體（僅用於 box 定義）"],
                     evidence={"hetero": unknown_het}))
    if insp.waters:
        rep.add(Gate("crystal waters", AUTO_FIXED, f"移除 {insp.waters} 個結晶水（溶劑化時重新加水）。",
                     options=["移除（預設）", "保留口袋內 5 Å 的水"]))
    if insp.duplicate_atom_names:
        rep.add(Gate("duplicate atom names", NEEDS_HUMAN, "同一殘基內有重複原子名；通常是轉檔或手動編輯造成，拓撲無法對應。",
                     evidence={"examples": insp.duplicate_atom_names[:5]}, options=["改用原始 mmCIF"]))
    if insp.hydrogens:
        rep.add(Gate("existing hydrogens", AUTO_FIXED, f"檔案已有 {insp.hydrogens} 個氫；全部移除後依 pH 重新加氫，避免 docking 階段的質子化狀態誤入 MD。"))
    if insp.ca_count == 0:
        rep.add(Gate("protein", NEEDS_HUMAN, "找不到任何 CA 原子：這不是蛋白質結構檔，或格式不是 PDB。"))
    return rep


# Receptor gate choices that prepare_receptor actually executes.  Anything else (truncate a loop, model with
# AlphaFold, parameterise an unknown residue …) needs work outside the program, so the gate stays NEEDS_HUMAN.
def receptor_choice_action(gate_name: str, choice: str) -> str | None:
    c = str(choice or "")
    if gate_name == "hetero groups":
        if "參考配體" in c or "移除" in c:
            return "remove"            # reference-only ligands leave the receptor; the box still reads the raw file
        if "參數化" in c or c.strip() == "保留":
            return "keep"              # kept in the receptor; force-field templates are checked at build time
    return None


def prepare_receptor(source: Path | str, out_dir: Path | str, *, ph: float = 7.4, keep_hetero: set[str] | None = None,
                     decisions: DecisionLog | None = None, max_auto_gap: int = 6, keep_pocket_waters: bool = False,
                     human_choices: dict | None = None, ligand_resnames: set[str] | None = None,
                     exclude_chains: set[str] | None = None) -> dict:
    """Clean a receptor with PDBFixer.  Returns a manifest with the gate report.

    `human_choices` maps gate name → chosen option string (from the GUI) so a
    NEEDS_HUMAN gate can be resolved on a second call without re-asking.
    """
    source, out_dir = Path(source), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    keep_hetero = set(keep_hetero or COFACTOR_KEEP_DEFAULT)
    human_choices = dict(human_choices or {})
    text = source.read_text(encoding="utf-8", errors="ignore") if source.suffix.lower() in {".pdb", ".ent"} else ""
    exclude_chains = set(exclude_chains or ())
    if text and exclude_chains:
        # e.g. a co-crystal peptide: it is a ligand, never part of the receptor
        text = "\n".join(l for l in text.splitlines() if not (l.startswith(("ATOM", "HETATM", "TER", "ANISOU")) and len(l) > 21 and l[21] in exclude_chains))
        if decisions:
            decisions.record("build.receptor", "excluded chains", sorted(exclude_chains),
                             "這些 chain 是配體（例如共晶胜肽），從受體移除後由配體流程處理，避免被併入受體。")
    insp = inspect_pdb_text(text) if text else PDBInspection(format=source.suffix.lower().lstrip("."))
    report = gate_inspection(insp, keep_hetero=keep_hetero, max_auto_gap=max_auto_gap,
                             ligand_resnames=set(ligand_resnames or ())) if text else GateReport()
    # resolve gates with human choices — only choices the code really carries out (寧可擋也不要猜)
    resolved: dict[str, str] = {}
    for g in report.gates:
        if g.status == NEEDS_HUMAN and g.name in human_choices:
            action = receptor_choice_action(g.name, human_choices[g.name])
            if action is None:
                g.explanation += (f"（你選了「{human_choices[g.name]}」，但這個選項目前不會由程式自動執行；"
                                  "請在外部處理後重新提供結構，閘門維持擋關。）")
                if decisions:
                    decisions.record("build.receptor", g.name, human_choices[g.name],
                                     "使用者的選擇尚未自動化；為避免「選了卻沒做」，閘門維持 NEEDS_HUMAN。", kind="human")
                continue
            resolved[g.name] = action
            g.status = AUTO_FIXED
            g.explanation += f"（使用者選擇：{human_choices[g.name]}）"
            if decisions:
                decisions.record("build.receptor", g.name, human_choices[g.name], "使用者在閘門做出的決定。", kind="human")
    manifest = {"source": str(source), "inspection": insp.to_dict(), "gates": report.to_dict(), "ph": ph,
                "status": report.status, "created_at": now_iso()}
    if not report.ok:
        atomic_write_json(manifest, out_dir / "receptor_manifest.json")
        return manifest
    # ---- PDBFixer repair ----------------------------------------------------
    try:
        from pdbfixer import PDBFixer
        from openmm.app import PDBFile, PDBxFile
    except ImportError as exc:
        manifest["status"] = NEEDS_HUMAN
        manifest["error"] = f"缺少 pdbfixer/openmm：{exc}"
        atomic_write_json(manifest, out_dir / "receptor_manifest.json")
        return manifest
    # Text-level pre-filter: keep ATOM records, keep HETATM only for cofactors/ions in `keep_hetero`
    # (and water if requested).  This replaces PDBFixer.removeHeterogens, which cannot keep a subset.
    filtered = out_dir / "receptor_prefiltered.pdb"
    keep_set = set(keep_hetero)
    if resolved.get("hetero groups") == "keep":
        keep_set |= set(insp.hetero_residues)
    kept_lines, dropped = [], {}
    for line in (text or source.read_text(encoding="utf-8", errors="ignore")).splitlines():
        rec = line[:6].strip()
        if rec == "HETATM":
            resname = line[17:20].strip()
            if resname in WATER:
                if keep_pocket_waters:
                    kept_lines.append(line)
                else:
                    dropped[resname] = dropped.get(resname, 0) + 1
                continue
            if resname in keep_set:
                kept_lines.append(line)
            else:
                dropped[resname] = dropped.get(resname, 0) + 1
            continue
        if rec in {"ATOM", "TER", "END", "ENDMDL", "SEQRES", "CRYST1", "SSBOND", "MODEL", "HEADER"}:
            kept_lines.append(line)
            if rec == "ENDMDL":
                break
    filtered.write_text("\n".join(kept_lines) + "\nEND\n", encoding="utf-8")
    manifest["dropped_hetero"] = dropped
    fixer = PDBFixer(filename=str(filtered))
    fixer.findMissingResidues()
    # drop terminal "missing residues" (PDBFixer would build floppy tails); keep internal gaps ≤ max_auto_gap
    chains = list(fixer.topology.chains())
    kept_missing = {}
    for (ci, ridx), residues in list(fixer.missingResidues.items()):
        chain = chains[ci]
        n_res = len(list(chain.residues()))
        if ridx == 0 or ridx == n_res or len(residues) > max_auto_gap:
            continue
        kept_missing[(ci, ridx)] = residues
    fixer.missingResidues = kept_missing
    fixer.findNonstandardResidues()
    fixer.replaceNonstandardResidues()
    fixer.findMissingAtoms()
    fixer.addMissingAtoms()
    fixer.addMissingHydrogens(pH=ph)
    out_pdb = out_dir / "receptor_clean.pdb"
    with open(out_pdb, "w", encoding="utf-8") as fh:
        PDBFile.writeFile(fixer.topology, fixer.positions, fh, keepIds=True)
    from ..util.stamp import stamp_pdb_file
    stamp_pdb_file(out_pdb)
    out_cif = out_dir / "receptor_clean.cif"
    with open(out_cif, "w", encoding="utf-8") as fh:
        PDBxFile.writeFile(fixer.topology, fixer.positions, fh, keepIds=True)
    n_atoms = fixer.topology.getNumAtoms()
    manifest.update({"receptor_pdb": str(out_pdb), "receptor_cif": str(out_cif), "n_atoms_clean": n_atoms,
                     "missing_residues_added": {str(k): v for k, v in kept_missing.items()},
                     "missing_atoms_added": {str(r): [a.name for a in atoms] for r, atoms in fixer.missingAtoms.items()}})
    if decisions:
        decisions.record("build.receptor", "protonation", f"pH {ph} (PDBFixer)",
                         "依設定 pH 重新加氫；His/Asp/Glu/Lys 狀態由 PDBFixer 的簡單規則決定（M2 之後改用 PROPKA）。")
        if kept_missing:
            decisions.record("build.receptor", "missing loops", list(map(str, kept_missing)),
                             f"補建 ≤{max_auto_gap} 殘基的內部缺口；末端缺失不補（避免無支撐的尾巴）。", kind="auto_fixed")
    atomic_write_json(manifest, out_dir / "receptor_manifest.json")
    return manifest
