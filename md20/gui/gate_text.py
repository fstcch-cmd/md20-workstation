"""English titles, general explanations and option labels for every gate (D-55).

Gate explanations are written in Chinese where they are created (the decision log stays Chinese, CLAUDE.md).  In the
English interface a card shows the English title and the general explanation of that gate kind from this table; the
recorded Chinese detail (with the run's numbers) stays available under "Details".  Options are translated by exact
text or by prefix; anything not listed is shown as written.
"""
from __future__ import annotations

# name (or name prefix) → (title zh, title en, general explanation en)
GATES: dict[str, tuple[str, str, str]] = {
    "resolution": ("解析度", "Resolution", "The crystal structure's resolution is low, so atom positions in the pocket are uncertain."),
    "R-free": ("R-free", "R-free", "The structure's R-free is high, a sign the model fits the experimental data poorly."),
    "ligand occupancy": ("配體佔有率", "Ligand occupancy", "The co-crystal ligand is only partly present in the crystal, so its pose is uncertain."),
    "pocket occupancy": ("口袋佔有率", "Pocket occupancy", "Pocket atoms have partial occupancy or alternate positions."),
    "pocket B-factor": ("口袋 B 因子", "Pocket B-factors", "Pocket atoms are poorly ordered (high B-factors), so the pocket shape is uncertain."),
    "experiment": ("實驗方法", "Experimental method", "The structure was not solved by X-ray crystallography; check that it suits docking."),
    "missing loops (short)": ("短缺口", "Short missing segments", "Short stretches of the backbone are missing; without SEQRES the program cannot tell which residues to rebuild, and the two ends would otherwise be joined by a false bond."),
    "missing loops (long)": ("長缺口", "Long missing loops", "Long loops are missing; automatically rebuilt long loops are unreliable and can distort the pocket dynamics."),
    "unfilled chain breaks": ("未補的主鏈斷裂", "Unfilled chain breaks", "Breaks remain in the backbone after repair; building would join their ends with a false bond."),
    "chain breaks capped": ("斷鏈已截斷", "Chain breaks capped", "Chain breaks were capped with neutral ACE and NME groups and the segment after each break became its own chain."),
    "hetero groups": ("非蛋白分子", "Non-protein molecules", "The structure contains non-protein molecules (possible ligands, buffer components or cofactors); choose which to keep."),
    "unknown residues": ("未知殘基", "Unknown residues", "Residues without a standard mapping (modified residues or covalent ligands) have no force-field parameters."),
    "duplicate atom names": ("重複原子名", "Duplicate atom names", "A residue contains duplicate atom names, so the topology cannot be matched."),
    "nonstandard residues": ("非標準殘基", "Non-standard residues", "Non-standard residues were replaced by their standard equivalents."),
    "numbering jumps": ("編號跳號", "Numbering jumps", "Residue numbers jump while the backbone is continuous: a numbering convention, not missing residues."),
    "crystal waters": ("結晶水", "Crystal waters", "Crystal waters were removed; water is added again during solvation."),
    "buffer / additives": ("結晶添加物", "Crystallisation additives", "Buffer components, glycerol and similar additives were removed."),
    "cofactors kept": ("保留的輔因子", "Cofactors kept", "Listed cofactors are kept in the receptor."),
    "co-crystal ligand": ("共結晶配體", "Co-crystal ligand", "The co-crystal ligand is handled by the ligand workflow (its coordinates are used as a pose)."),
    "existing hydrogens": ("既有氫原子", "Existing hydrogens", "Hydrogens in the file were removed and placed again for the chosen pH."),
    "altloc": ("替代構象", "Alternate locations", "Atoms with alternate locations were reduced to the most occupied position."),
    "insertion code": ("插入碼", "Insertion codes", "Residues with insertion codes are renumbered; the original numbering is kept in the mapping."),
    "element column": ("元素欄位", "Element column", "Missing element symbols were inferred from atom names."),
    "atom serial": ("原子序號", "Atom serial numbers", "Atom serial numbers exceed the PDB limit; mmCIF is used internally."),
    "protein": ("蛋白", "Protein", "No protein Cα atoms were found: this is not a protein structure file."),
    "metal charges": ("金屬電荷", "Metal-site charges", "The fitted metal-site charges are inconsistent with the force field."),
    "metal": ("金屬位點", "Metal site", "A metal ion in or near the pocket needs a model: bonded, non-bonded with restraints, or removed."),
    "ligand–metal coordination": ("配體配位金屬", "Ligand coordinates a metal", "The docked ligand binds a metal directly; the force field has no ligand–metal bond, so this binding mode is not reliable without a dedicated model."),
    "CPP": ("穿膜性", "Cell penetration", "Scientific-limitation notice: for an intracellular target the peptide must cross the cell membrane. This notice does not stop the workflow."),
    "peptide pocket access": ("活性位可及性", "Binding-site access", "Scientific-limitation notice: whether the peptide fits the search region and whether the chosen pose actually enters the site. This notice does not stop the workflow."),
    "peptide detected": ("偵測到胜肽", "Peptide detected", "The ligand looks like a peptide; peptides need the protein force field and their own chain."),
    "peptide 3D": ("胜肽 3D 結構", "Peptide 3D structure", "No usable 3D structure for the peptide pose."),
    "peptide pose mapping": ("胜肽姿勢對應", "Peptide pose mapping", "The docked peptide pose could not be mapped to the sequence."),
    "peptide topology": ("胜肽拓撲", "Peptide topology", "The peptide's topology does not match its sequence."),
    "peptide chain count": ("胜肽鏈數", "Peptide chain count", "The peptide must form exactly one chain."),
    "peptide–receptor bond": ("胜肽與受體鍵結", "Peptide–receptor bond", "A bond was created between peptide and receptor, which must never happen."),
    "termini": ("末端", "Termini", "The peptide termini were set."),
    "pose mapping": ("姿勢對應", "Pose mapping", "The docked pose could not be mapped onto the reference molecule."),
    "3D": ("3D 結構", "3D structure", "A 3D conformer could not be generated for the ligand."),
    "formal charge": ("形式電荷", "Formal charge", "The ligand's formal charge is unusual for pH 7.4; check its protonation."),
    "charge sum": ("電荷總和", "Charge sum", "Partial charges do not add up to the formal charge."),
    "total charge": ("系統總電荷", "Total charge", "The system's total charge is not an integer or not neutralised."),
    "parameters": ("參數化", "Parameterisation", "No parameterisation route succeeded for the ligand."),
    "ligand": ("配體", "Ligand", "The ligand could not be parameterised."),
    "force field templates": ("力場樣板", "Force-field templates", "A residue has no force-field template (common for metals or cofactors)."),
    "force field": ("力場", "Force field", "The force field could not be applied."),
    "vacuum smoke test": ("真空測試", "Vacuum smoke test", "A short vacuum minimisation of the ligand failed, a sign of bad parameters or geometry."),
    "single-point energy": ("單點能量", "Single-point energy", "The starting energy is not finite."),
    "hydrogens": ("加氫", "Hydrogens", "Hydrogens could not be added consistently."),
    "chain": ("鏈", "Chain", "Chain identifiers conflict."),
    "padding": ("水盒邊距", "Box padding", "The box padding is too small for the planned calculation."),
    "ions": ("離子", "Ions", "The salt type or concentration is not supported or out of range."),
    "water fraction": ("水比例", "Water fraction", "The box contains unusually little or much water for its size."),
    "implicit solvent": ("隱式溶劑", "Implicit solvent", "Implicit solvent was requested; check its limitations."),
    "implicit solvent + metal": ("隱式溶劑與金屬", "Implicit solvent with a metal", "Implicit solvent is not suitable for this metal site."),
    "implicit solvent + binding": ("隱式溶劑與結合計算", "Implicit solvent with binding", "Binding free energy needs a periodic water box; implicit solvent cannot be used."),
    "multi-ligand flat-bottom": ("多配體平底約束", "Multi-ligand restraints", "Each ligand is kept near the pocket with a flat-bottom restraint during simulation (switched off for free-energy work)."),
    "assembly": ("系統組裝", "System assembly", "The system could not be assembled."),
    "openmm": ("OpenMM", "OpenMM", "OpenMM is not available in this environment."),
    "docking reliability": ("對接可信度", "Docking reliability", "Docking results for this ligand are of limited reliability."),
    "box size": ("搜尋區大小", "Search box size", "Scientific-limitation notice: the search box is very large (longest edge over 40 Å or more than 300 residues inside), which behaves like blind docking and lowers the reliability of scores and poses. This notice does not stop the workflow."),
    "blind docking": ("盲對接", "Blind docking", "The search box covers the whole protein; confirm blind docking or define the site."),
    "redocking": ("重新對接自檢", "Redocking check", "The box comes from a co-crystal ligand, but that ligand is not redocked to check the setup."),
    "confirm MD": ("確認進入分子動力學", "Proceed to molecular dynamics?", "Docking and pose selection are complete; confirm before the long simulation starts."),
    "library": ("化合物庫", "Compound library", "The compound library could not be read."),
    "library partial": ("化合物庫部分失敗", "Library partly failed", "Some compounds could not be obtained; continue without them or fix the library."),
    "screen partial": ("篩選部分失敗", "Screening partly failed", "Some compounds failed in screening docking."),
    "screen selection": ("篩選選擇", "Screening selection", "Choose the compounds to take forward from the screening ranking."),
    "structure_gate": ("結構可信度", "Structure validity", "The structure did not pass a validity check."),
}

OPTIONS: dict[str, str] = {
    "截斷（加 ACE/NME 端帽）": "Truncate (add ACE and NME caps)",
    "以 PDBFixer 補建並接受風險": "Rebuild with PDBFixer and accept the risk",
    "改用 AlphaFold 模型": "Use an AlphaFold model instead",
    "提供含 SEQRES 的原始 PDB（RCSB 下載版）": "Provide the original PDB with SEQRES (RCSB download)",
    "提供含完整 SEQRES 的原始 PDB": "Provide the original PDB with complete SEQRES",
    "全部移除（預設）": "Remove all (default)", "保留並參數化": "Keep and parameterise",
    "保留為參考配體（僅用於 box 定義）": "Keep as reference ligand (box definition only)",
    "移除並記錄": "Remove and record", "視為配體走參數化階梯": "Treat as a ligand and parameterise", "手動提供參數": "Provide parameters manually",
    "換一個更高解析度的結構": "Use a higher-resolution structure", "換結構": "Use another structure",
    "胞內 intracellular": "Intracellular", "膜外側 extracellular-membrane": "Extracellular, at the membrane", "分泌／胞外 secreted": "Secreted or extracellular",
    "提供實驗證據（文獻或自有數據）": "Provide experimental evidence (literature or own data)", "提供實驗證據": "Provide experimental evidence",
    "改設計：縮短為帶電核心（如 GKP、KP）或富集 Arg/Lys": "Redesign: shorten to the charged core (e.g. GKP, KP) or enrich Arg and Lys",
    "改設計：N 端接 TAT／R8／penetratin 等穿膜載體": "Redesign: attach a cell-penetrating carrier (TAT, R8, penetratin) at the N terminus",
    "接受預測並繼續": "Accept the prediction and continue",
    "以共結晶配體或活性位殘基重新定義搜尋區": "Redefine the search box from a co-crystal ligand or active-site residues",
    "接受並在報告中標註": "Accept and label in the report", "改選其他 pose（pose 表）": "Choose another pose (pose table)",
    "縮小搜尋區到活性位後重新對接": "Narrow the box to the active site and dock again",
    "進入分子動力學（md_confirmed）": "Proceed to molecular dynamics",
    "先改選姿勢（在姿勢表點選後再回來確認）": "Choose another pose first (click it in the pose table, then confirm)",
    "換一個不直接配位金屬的 pose（pose 表點選）": "Use a pose that does not coordinate the metal (pose table)",
    "以 MCPB.py/QM 參數化配體–金屬鍵後匯入（metal_params）": "Parameterise the ligand–metal bond with MCPB.py or QM and import it",
    "以 MCPB.py/QM 參數化後匯入": "Parameterise with MCPB.py or QM and import",
    "改用 keep_nonbonded（報告標註）": "Keep as a non-bonded ion (labelled in the report)", "改用 keep_nonbonded": "Keep as a non-bonded ion",
    "remove（若非必要）": "Remove (if not functionally needed)", "metal_policy: remove（若非必要）": "Remove the metal (if not functionally needed)",
    "metal_params 改為不套用電荷（charges: false）": "Do not apply the fitted charges", "確認 MCPB 模型的質子化狀態": "Check the protonation states of the MCPB model",
    "改用幾何鍵結模型（移除 metal_params）": "Use the geometric bonded model", "修正 metal_params 設定": "Fix the metal parameter settings",
    "md.solvent: explicit（顯式水）": "Use explicit water", "md.solvent: explicit（顯式水，重建並重跑 MD）": "Use explicit water (rebuild and rerun)",
    "md.solvent: gbn2（真的要省算力時用隱式溶劑）": "Use implicit solvent (only to save computing time)",
    "binding.enabled: false（只做 MD）": "Skip binding free energy (molecular dynamics only)",
    "screen.allow_partial: true（略過失敗的化合物，報告標註）": "Continue without the failed compounds (labelled in the report)",
    "在「篩選」分頁勾選化合物": "Tick compounds in the Screening tab", "修正化合物庫檔案後重新執行": "Fix the library file and run again",
    "檢查失敗原因後重新執行": "Check the failures and run again", "保留口袋內 5 Å 的水": "Keep waters within 5 Å of the pocket",
    "移除（預設）": "Remove (default)", "保留": "Keep", "接受推斷": "Accept the inference", "改用 mmCIF 原始檔": "Use the original mmCIF file",
    "改用原始 mmCIF": "Use the original mmCIF file", "以參考分子為準": "Follow the reference molecule", "以序列宣告為胜肽": "Declare it as a peptide by sequence",
    "確認為小分子（peptide_policy.allow_small_molecule）": "Confirm it is a small molecule", "確認序列": "Check the sequence",
    "改用帶電端（預設）": "Use charged termini (default)", "使用 Sobtop 進階路徑": "Use the Sobtop advanced route",
    "安裝 openff-toolkit + openff-nagl": "Install openff-toolkit and openff-nagl", "回報給老師": "Report to the instructor",
    "從 keep_hetero 移除": "Remove from the kept residues", "提供該殘基的參數": "Provide parameters for this residue",
    "提供 docking 前的 SDF": "Provide the SDF used for docking", "改用 docking 輸出的 SDF": "Use the SDF written by docking",
    "改用 pose SDF（Meeko/Vina --out sdf）": "Use the pose SDF", "重新匯出 docking pose": "Export the docking pose again",
    "重新以 pH 質子化（Dimorphite-DL）": "Re-protonate for the pH", "檢查 chain ID 與殘基編號": "Check chain identifiers and residue numbers",
}
OPTIONS.update({   # free-text hints of the decision inputs
    "文獻（DOI）或自有實驗數據的簡述": "Literature (DOI) or a short description of your own data",
    "為什麼在未驗證穿膜性的情況下仍要繼續（報告會標註）": "Why continue without verified cell penetration (labelled in the report)",
    "為什麼它是擬肽小分子而不是胜肽": "Why it is a peptidomimetic small molecule rather than a peptide",
    "為什麼這個結構仍可用（會寫進決策日誌與報告）": "Why this structure is still usable (recorded in the decision log and the report)",
    "備註（為什麼選這些）": "Note (why these compounds)",
})
PREFIX: list[tuple[str, str]] = [
    ("仍要使用", "Use anyway"), ("ligand_metal: restrain", "Hold the coordination with a distance restraint (no binding free energy for this ligand)"),
    ("box.from_residue:", "Define the box from residue"), ("box.allow_blind", "Allow blind docking (labelled in the report)"),
    ("docking.skip_redock", "Skip the redocking check (labelled in the report)"), ("md.restraints:", "Restraint strategy:"),
    ("md.ions.positive:", "Cation:"), ("md.ions.negative:", "Anion:"), ("md.padding_nm", "Increase the box padding"),
    ("加入共晶配體", "Add the co-crystal ligand as a redocking reference (needs its SMILES)"),
    ("metal_policy: {", "Metal model:"), ("metal_policy:", "Metal model:"), ("仍要繼續", "Continue anyway (labelled in the report)"),
]


def _lookup(name: str):
    if name in GATES:
        return name, GATES[name]
    for k in sorted(GATES, key=len, reverse=True):          # "metal ZN:A262" → "metal", "metal charges ZN" → "metal charges"
        if name.startswith(k + " "):
            return k, GATES[k]
    return None, None


def gate_title(name: str, lang: str) -> str:
    k, g = _lookup(name)
    if not g:
        return name
    return (g[0] if lang == "zh" else g[1]) + name[len(k):]


def gate_general(name: str) -> str:
    return (_lookup(name)[1] or ("", "", ""))[2]


def option_text(option: str, lang: str) -> str:
    if lang == "zh":
        return option
    if option in OPTIONS:
        return OPTIONS[option]
    for p, en in PREFIX:
        if option.startswith(p):
            rest = option[len(p):].split("（")[0].strip(" :{}")
            return f"{en} {rest}" if rest and en.endswith(":") or (rest and p.endswith(":")) else en
    return option
