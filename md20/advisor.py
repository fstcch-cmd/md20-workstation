"""Case-aware parameter advisor (D-49): recommended starting values with reasons, plausibility checks, cost estimate.

Used by every entry point (GUI quick, pro and teaching modes, CLI, report), so the value a user sees in the form, the
reason next to it and the "parameters used" table in the report all come from one place.  Bilingual (English default,
Traditional Chinese): every text is a (zh, en) pair resolved by `lang`.

    feats  = features_from_config(cfg, receptor_text=..., doctor=...)
    rec    = recommend(feats, goal="binding", lang="en")     # {key: {"value", "why"}}
    issues = check(values, feats, lang="en")                 # [{"level", "key", "label", "message", "suggestion"}]
    cfg2   = apply(values, cfg)                              # values written into the workflow config
    est    = estimate_hours(values, feats)

Pure Python (no OpenMM/RDKit), so it is tested everywhere and can run while the user types.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field, asdict

from .engine.protocol import TIERS

METALS = {"ZN", "MG", "CA", "MN", "FE", "FE2", "CU", "CU1", "CO", "NI", "CD", "HG"}
LANGS = ("en", "zh")


def tx(x, lang: str = "en") -> str:
    """Resolve a (zh, en) pair or {"zh","en"} dict; plain strings pass through."""
    if isinstance(x, tuple) and len(x) == 2:
        return x[1] if lang == "en" else x[0]
    if isinstance(x, dict) and ("zh" in x or "en" in x):
        return x.get(lang) or x.get("en") or x.get("zh") or ""
    return "" if x is None else str(x)


GOALS = {
    "teaching": ("課堂示範：完整走過流程、看懂每個閘門", "Classroom demonstration: run the whole workflow and understand every gate"),
    "screening": ("化合物比較：比較多個配體的對接與複合物穩定性", "Compound comparison: rank several ligands by docking and complex stability"),
    "binding": ("結合強度：以 SMD 與傘狀採樣計算自由能剖面", "Binding strength: free-energy profile from SMD and umbrella sampling"),
    "publication": ("發表等級：足夠長、可重複、能報告不確定度", "Publication grade: long enough, replicated, with reported uncertainty"),
}


@dataclass
class CaseFeatures:
    n_residues: int | None = None          # receptor protein residues (None = not known yet)
    n_ligands: int = 1
    ligand_kind: str = "small"             # small | peptide | mixed
    peptide_length: int | None = None
    docking_mode: str = "independent"
    metals: list = field(default_factory=list)
    structure_source: str = "crystal"      # crystal | model
    has_gaps: bool = False
    box_from_site: bool = True
    box_size: list | None = None
    binding: bool = False
    ns_per_day: float | None = None        # measured on this computer (Doctor benchmark)
    bench_atoms: int = 24000
    bench_dt_fs: float = 4.0
    gpu: bool | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# ----------------------------------------------------------------------------------- parameter schema
def P(zh, en, unit="", group="", type="float", **kw):
    return {"label": (zh, en), "unit": unit, "group": group, "type": type, **kw}


GROUPS = {"docking": ("分子對接", "Molecular docking"), "system": ("模擬系統", "Simulation system"),
          "equil": ("平衡流程", "Equilibration"), "prod": ("正式模擬", "Production"),
          "binding": ("結合自由能", "Binding free energy")}
GROUP_ORDER = list(GROUPS)
PARAMS: dict[str, dict] = {
    "docking_mode": P("多配體對接方式", "Multi-ligand docking", group="docking", type="choice",
                      choices={"independent": ("各自對接（每個配體獨立）", "Independent (each ligand alone)"),
                               "simultaneous": ("同時對接（多個配體共存）", "Simultaneous (ligands together)")}),
    "exhaustiveness": P("對接搜尋強度", "Search exhaustiveness", group="docking", type="int", min=1, max=128),
    "n_poses": P("每個配體保留的姿勢數", "Poses kept per ligand", group="docking", type="int", min=1, max=20),
    "solvent": P("溶劑模型", "Solvent model", group="system", type="choice",
                 choices={"explicit": ("顯式水（TIP3P，週期性邊界）", "Explicit water (TIP3P, periodic)"),
                          "gbn2": ("隱式溶劑（GBn2，無水盒）", "Implicit solvent (GBn2, no water box)")}),
    "padding_nm": P("水盒邊距", "Box padding", "nm", "system", min=0.5, max=3.0, step=0.1),
    "box_shape": P("水盒形狀", "Box shape", group="system", type="choice",
                   choices={"dodecahedron": ("菱形十二面體", "Rhombic dodecahedron"), "cube": ("立方體", "Cube")}),
    "ion_positive": P("陽離子", "Cation", group="system", type="choice",
                      choices={k: (k, k) for k in ("Na+", "K+", "Li+", "Rb+", "Cs+")}),
    "ion_negative": P("陰離子", "Anion", group="system", type="choice", choices={k: (k, k) for k in ("Cl-", "Br-", "F-", "I-")}),
    "ion_concentration_molar": P("鹽濃度", "Salt concentration", "M", "system", min=0.0, max=2.0, step=0.01),
    "neutralize": P("以反離子中和淨電荷", "Neutralise net charge", group="system", type="bool"),
    "tier": P("模擬等級", "Simulation tier", group="equil", type="choice",
              choices={"classroom": ("課堂（2 ns）", "Classroom (2 ns)"), "teaching": ("教學（10 ns）", "Teaching (10 ns)"),
                       "research": ("研究（100 ns，2 fs）", "Research (100 ns, 2 fs)")}),
    "restraints": P("位置約束釋放策略", "Restraint release strategy", group="equil", type="choice",
                    choices={"standard": ("標準：在定壓平衡中逐步釋放", "Standard: released during NPT"),
                             "gentle": ("溫和：約束保留到加熱結束，定壓平衡加倍", "Gentle: held through heating, NPT doubled"),
                             "hold_backbone": ("主鏈保留 5 % 到正式模擬", "Backbone held at 5 % in production")}),
    "minimize_iterations": P("能量最小化最大步數", "Minimisation steps (maximum)", "", "equil", type="int", min=100, max=100000),
    "minimize_tolerance": P("能量最小化收斂門檻", "Minimisation tolerance", "kJ mol⁻¹ nm⁻¹", "equil", min=0.1, max=1000),
    "heat_start_k": P("加熱起始溫度", "Heating start temperature", "K", "equil", min=0, max=400, step=10),
    "nvt_ps": P("定容加熱時間", "Heating time (NVT)", "ps", "equil", min=0, max=10000, step=10),
    "npt_ps": P("定壓平衡時間", "Pressure equilibration (NPT)", "ps", "equil", min=0, max=20000, step=10),
    "temperature_k": P("模擬溫度", "Temperature", "K", "prod", min=250, max=400, step=1),
    "pressure_bar": P("壓力", "Pressure", "bar", "prod", min=0.5, max=1000, step=0.5),
    "friction_per_ps": P("Langevin 摩擦係數", "Langevin friction", "ps⁻¹", "prod", min=0.01, max=50, step=0.1),
    "timestep_fs": P("積分步長", "Time step", "fs", "prod", min=0.5, max=5, step=0.5),
    "production_ns": P("正式模擬長度", "Production length", "ns", "prod", min=0.1, max=10000, step=1),
    "replicas": P("獨立重複次數", "Independent replicas", "", "prod", type="int", min=1, max=10),
    "trajectory_interval_ps": P("軌跡存檔間隔", "Trajectory save interval", "ps", "prod", min=1, max=1000),
    "binding": P("計算結合強度（SMD 與傘狀採樣）", "Compute binding strength (SMD and umbrella sampling)", group="binding", type="bool"),
    "pull_distance_nm": P("拉離距離", "Pulling distance", "nm", "binding", min=0.5, max=5, step=0.1),
    "pull_velocity_nm_per_ps": P("拉離速度", "Pulling velocity", "nm ps⁻¹", "binding", min=0.0001, max=0.1, step=0.001),
    "k_pull": P("拉離彈簧常數", "Pulling spring constant", "kJ mol⁻¹ nm⁻²", "binding", min=50, max=20000, step=50),
    "k_umbrella": P("傘狀採樣彈簧常數", "Umbrella spring constant", "kJ mol⁻¹ nm⁻²", "binding", min=50, max=20000, step=50),
    "window_equil_ps": P("每個窗口平衡時間", "Equilibration per window", "ps", "binding", min=0, max=5000, step=10),
    "window_prod_ps": P("每個窗口取樣時間", "Sampling per window", "ps", "binding", min=5, max=20000, step=10),
    "target_overlap": P("相鄰窗口目標重疊", "Target overlap of neighbouring windows", "", "binding", min=0.01, max=0.9, step=0.01),
}
# keys a quick-mode user sees; everything else is pro only (always filled from the recommendation)
QUICK_KEYS = ["docking_mode", "tier", "production_ns", "replicas", "ion_positive", "ion_negative", "ion_concentration_molar",
              "temperature_k", "binding"]


def param_label(key: str, lang: str = "en") -> str:
    return tx(PARAMS.get(key, {}).get("label", (key, key)), lang)


def choice_label(key: str, value, lang: str = "en") -> str:
    ch = PARAMS.get(key, {}).get("choices") or {}
    return tx(ch[value], lang) if value in ch else str(value)


def format_value(key: str, value, lang: str = "en") -> str:
    p = PARAMS.get(key, {})
    if value is None:
        return "—"
    if p.get("type") == "bool":
        return tx(("是", "Yes"), lang) if value else tx(("否", "No"), lang)
    if p.get("type") == "choice":
        return choice_label(key, value, lang)
    txt = f"{value:g}" if isinstance(value, float) else str(value)
    return f"{txt} {p['unit']}".strip() if p.get("unit") else txt


# ----------------------------------------------------------------------------------- features
def _receptor_stats(text: str) -> tuple[int, list[str], bool]:
    res, metals, gaps, last = set(), set(), False, None
    for l in text.splitlines():
        if l.startswith("ATOM") and l[12:16].strip() == "CA":
            try:
                key = (l[21], int(l[22:26]))
                xyz = (float(l[30:38]), float(l[38:46]), float(l[46:54]))
            except ValueError:
                continue
            res.add(key)
            if last and last[0] == key[0] and math.dist(last[1], xyz) > 4.2:
                gaps = True
            last = (key[0], xyz)
        elif l.startswith("HETATM") and l[17:20].strip() in METALS:
            metals.add(l[17:20].strip())
    return len(res), sorted(metals), gaps


def features_from_config(cfg: dict, *, receptor_text: str | None = None, doctor: dict | None = None) -> CaseFeatures:
    ligs = [l for l in cfg.get("ligands") or [] if isinstance(l, dict)]
    peps = [l for l in ligs if l.get("sequence")]
    kind = "peptide" if peps and len(peps) == len(ligs) else ("mixed" if peps else "small")
    keep = {str(k).upper() for k in cfg.get("keep_hetero") or []}
    f = CaseFeatures(n_ligands=max(1, len(ligs)), ligand_kind=kind,
                     peptide_length=max((len(str(l["sequence"]).replace(" ", "")) for l in peps), default=None),
                     docking_mode=(cfg.get("docking") or {}).get("mode", "independent"),
                     metals=sorted(keep & METALS), binding=bool((cfg.get("binding") or {}).get("enabled")))
    b = cfg.get("box") or {}
    f.box_from_site = bool(b.get("from_residue") or b.get("site_residues"))
    f.box_size = list(b["size"]) if b.get("size") else None
    rec = cfg.get("receptor") or {}
    if rec.get("alphafold") or str(rec.get("source", "")).lower() in ("alphafold", "model", "homology"):
        f.structure_source = "model"
    if receptor_text:
        n, metals, gaps = _receptor_stats(receptor_text)
        f.n_residues = n or None
        f.metals = sorted(set(f.metals) | (set(metals) & keep))
        f.has_gaps = gaps
    doctor = doctor or {}
    bench = doctor.get("benchmark") or {}
    if bench.get("ns_per_day"):
        f.ns_per_day = float(bench["ns_per_day"])
        f.bench_atoms = int(bench.get("n_atoms") or 24000)
        f.bench_dt_fs = float(bench.get("timestep_fs") or 4.0)
    plat = doctor.get("platform")
    name = plat.get("name") if isinstance(plat, dict) else plat
    if name:
        f.gpu = str(name) in ("CUDA", "OpenCL", "HIP", "Metal")
    return f


# ----------------------------------------------------------------------------------- recommendations
def _r(value, zh: str, en: str) -> dict:
    return {"value": value, "why": (zh, en)}


def _recommend_raw(f: CaseFeatures, goal: str) -> dict[str, dict]:
    goal = goal if goal in GOALS else "teaching"
    pep = f.ligand_kind in ("peptide", "mixed")
    multi_sim = f.n_ligands > 1 and f.docking_mode == "simultaneous"
    rough_reasons = [r for r, c in ((("含金屬鍵結模型", "a bonded metal site"), bool(f.metals)),
                                    (("受體為預測模型", "a predicted receptor model"), f.structure_source == "model"),
                                    (("受體有補建或截斷的缺口", "rebuilt or capped chain breaks"), f.has_gaps),
                                    (("配體為胜肽", "a peptide ligand"), pep),
                                    (("多配體同時對接", "simultaneous multi-ligand docking"), multi_sim)) if c]
    tier = {"teaching": "classroom", "screening": "teaching", "binding": "teaching", "publication": "research"}[goal]
    t = TIERS[tier]
    o: dict[str, dict] = {}
    o["tier"] = {"classroom": _r(tier, "課堂示範只需完整走過流程；2 ns 足以觀察平衡與閘門行為，但不用於科學結論。",
                                 "A classroom run only has to go through the whole workflow; 2 ns shows equilibration and every "
                                 "gate, but supports no scientific conclusion."),
                 "teaching": _r(tier, "比較配體或估計結合強度時，至少需要 10 ns 讓口袋與配體構形鬆弛。",
                                "Comparing ligands or estimating binding needs at least 10 ns for the pocket and ligand to relax."),
                 "research": _r(tier, "發表等級：2 fs 且不使用氫質量重分配，100 ns 並至少 3 次重複，才能報告不確定度。",
                                "Publication grade: 2 fs without hydrogen mass repartitioning, 100 ns and at least three "
                                "replicas so that an uncertainty can be reported.")}[tier]
    # docking
    if f.n_ligands > 1:
        o["docking_mode"] = _r(f.docking_mode if f.docking_mode in ("independent", "simultaneous") else "independent",
                               "多個配體：各自對接回答「哪個配體較好」；同時對接回答「它們能否同時存在於口袋」，例如萃取物成分的協同作用。",
                               "Several ligands: independent docking answers which ligand binds best; simultaneous docking asks "
                               "whether they can occupy the site together, e.g. synergy between extract components.")
    else:
        o["docking_mode"] = _r("independent", "只有一個配體，各自對接即可。", "A single ligand: independent docking.")
    if pep:
        exh, why = 32, (f"胜肽（{f.peptide_length or '多'} 個殘基）可轉動鍵多、搜尋空間大，搜尋強度至少 32 才能穩定找到低能量姿勢。",
                        f"A peptide ({f.peptide_length or 'several'} residues) has many rotatable bonds; an exhaustiveness "
                        "of at least 32 is needed to find low-energy poses reproducibly.")
    elif multi_sim:
        exh, why = 32, ("同時對接的搜尋空間是所有配體自由度的總和，需要較高搜尋強度。",
                        "Simultaneous docking searches the combined freedom of all ligands and needs a higher exhaustiveness.")
    elif goal == "screening" and f.n_ligands > 20:
        exh, why = 8, ("大量化合物初篩：搜尋強度 8 已足以剔除明顯不合者，入選者再以 16 以上正式對接。",
                       "Large library pre-screen: 8 is enough to discard clear misfits; shortlisted compounds are re-docked at 16 or more.")
    else:
        exh, why = 16, ("藥物大小的小分子以 16 兼顧速度與重現性（Vina 預設 8 的重複性較差）。",
                        "For drug-sized molecules 16 balances speed and reproducibility (Vina's default of 8 is less repeatable).")
    if f.box_size and max(f.box_size) > 30:
        exh = max(exh, 32)
        why = (why[0] + f" 搜尋區最長邊 {max(f.box_size):.0f} Å 偏大，提高到 32。",
               why[1] + f" The longest box edge is {max(f.box_size):.0f} Å, so it is raised to 32.")
    o["exhaustiveness"] = _r(exh, *why)
    o["n_poses"] = _r(9, "保留 9 個姿勢供叢集分析與人工挑選；更多姿勢多半只是相同結合模式的重複。",
                      "Nine poses are enough for clustering and manual choice; more are usually repeats of the same binding mode.")
    # system
    if goal == "teaching" and f.gpu is False and not f.binding and not pep:
        o["solvent"] = _r("gbn2", "本機沒有可用 GPU，課堂示範可用隱式溶劑縮短時間；注意隱式溶劑不能做 SMD 與傘狀採樣，也無法分析水橋。",
                          "No GPU on this computer: implicit solvent shortens a classroom run. It cannot be used for SMD or "
                          "umbrella sampling, and water bridges cannot be analysed.")
    else:
        o["solvent"] = _r("explicit", "顯式水能正確描述氫鍵網路與離子屏蔽，是結合與穩定性分析的標準做法。",
                          "Explicit water describes hydrogen-bond networks and ionic screening; it is the standard for "
                          "binding and stability analysis.")
    want_binding = f.binding or goal in ("binding", "publication")
    pad = 1.2 if want_binding else (1.0 if tier == "research" else 0.8)
    o["padding_nm"] = {0.8: _r(0.8, "蛋白到盒邊 0.8 nm，配合 1.0 nm 截斷距離已可避免與自身鏡像作用，水分子最少。",
                               "0.8 nm from protein to box edge, with a 1.0 nm cut-off, avoids self-image interaction "
                               "with the fewest water molecules."),
                       1.0: _r(1.0, "研究等級留 1.0 nm，蛋白構形改變時仍與鏡像保持足夠距離。",
                               "Research tier keeps 1.0 nm so that conformational change cannot bring the protein near its image."),
                       1.2: _r(1.2, "結合強度計算要把配體拉出口袋 1.5 nm 以上，邊距需容納拉離路徑，否則配體會接近鏡像蛋白。",
                               "Binding calculations pull the ligand 1.5 nm or more out of the pocket; the padding has to "
                               "accommodate that path or the ligand approaches the periodic image of the protein.")}[pad]
    o["box_shape"] = _r("dodecahedron", "菱形十二面體在相同邊距下比立方體少約 29 % 的水，速度較快。",
                        "A rhombic dodecahedron holds about 29 % less water than a cube with the same padding, so it runs faster.")
    o["ion_positive"] = _r("Na+", "生理食鹽水條件；若實驗緩衝液以鉀鹽為主（例如模擬細胞內環境），改為 K+。",
                           "Physiological saline; use K+ if the experimental buffer is potassium-based (e.g. intracellular conditions).")
    o["ion_negative"] = _r("Cl-", "與 Na+ 組成 NaCl；使用 Amber14 的 Joung–Cheatham 單價離子參數。",
                           "With Na+ this is NaCl; Joung–Cheatham monovalent ion parameters from Amber14.")
    o["ion_concentration_molar"] = _r(0.15, "0.15 M 對應生理離子強度；體外酵素試驗請改為實驗緩衝液的鹽濃度。",
                                      "0.15 M matches physiological ionic strength; for an in vitro enzyme assay use the salt "
                                      "concentration of the assay buffer.")
    o["neutralize"] = _r(True, "PME 靜電需要系統淨電荷為零，否則會引入人為的均勻背景電荷。",
                         "PME electrostatics needs a neutral system; otherwise an artificial uniform background charge is added.")
    # equilibration
    if rough_reasons:
        zh = "、".join(r[0] for r in rough_reasons)
        en = ", ".join(r[1] for r in rough_reasons)
        o["restraints"] = _r("gentle", f"{zh}：起始結構較粗糙，約束全部保留到加熱結束，再以加倍長度的定壓平衡釋放。",
                             f"Rough starting structure ({en}): all restraints are held through heating and released "
                             "over an NPT stage of twice the length.")
    else:
        o["restraints"] = _r("standard", "高解析度晶體結構與藥物大小配體：主鏈與配體在定壓平衡中逐步釋放即可。",
                             "High-resolution crystal structure with a drug-sized ligand: backbone and ligand restraints are "
                             "released gradually during NPT.")
    o["minimize_iterations"] = _r(5000, "5000 步對 5 萬原子以內的系統足以消除對接與加氫造成的碰撞。",
                                  "5000 steps remove the clashes left by docking and hydrogen placement for systems up to 50,000 atoms.")
    o["minimize_tolerance"] = _r(10.0, "最大力低於 10 kJ mol⁻¹ nm⁻¹ 即可開始升溫；更嚴格只會增加時間。",
                                 "A maximum force below 10 kJ mol⁻¹ nm⁻¹ is enough to start heating; tighter only costs time.")
    o["heat_start_k"] = _r(50.0, "從 50 K 線性升溫，避免最小化後殘留的高能接觸在第一步就失穩。",
                           "Linear heating from 50 K keeps residual high-energy contacts from blowing up in the first steps.")
    nvt = float(t["nvt_ps"]) * (1.5 if f.metals else 1.0)
    o["nvt_ps"] = _r(nvt, f"{tier} 等級的加熱長度" + ("；含金屬鍵結模型再延長 50 %，讓配位幾何先穩定。" if f.metals else "。"),
                     f"Heating length of the {tier} tier" + ("; extended by 50 % for the bonded metal site so the "
                                                             "coordination geometry settles first." if f.metals else "."))
    npt = float(t["npt_ps"])
    big = bool(f.n_residues and f.n_residues > 600)
    if big:
        npt *= 1.5
    o["npt_ps"] = _r(npt, f"{tier} 等級的定壓平衡長度" + (f"；蛋白有 {f.n_residues} 個殘基，密度收斂較慢，延長 50 %。" if big else "。")
                     + ("溫和策略會自動再加倍。" if rough_reasons else ""),
                     f"NPT length of the {tier} tier" + (f"; {f.n_residues} residues converge in density more slowly, "
                                                         "so it is extended by 50 %." if big else ".")
                     + (" The gentle strategy doubles it." if rough_reasons else ""))
    # production
    o["temperature_k"] = _r(300.0, "300 K 是 Amber 力場參數化與多數文獻採用的溫度；要對應體溫可改為 310 K。",
                            "300 K is the temperature the Amber force fields were parameterised at and most literature uses; "
                            "use 310 K to match body temperature.")
    o["pressure_bar"] = _r(1.0, "常壓。", "Ambient pressure.")
    o["friction_per_ps"] = _r(1.0, "Langevin 1 ps⁻¹ 足以控溫，又不會明顯拖慢構形動態。",
                              "A Langevin friction of 1 ps⁻¹ controls temperature without noticeably slowing conformational dynamics.")
    if f.metals and t["dt"] > 2:
        o["timestep_fs"] = _r(2.0, "含金屬鍵結模型：金屬與配位原子間的鍵力常數高、振動快，4 fs 有失穩風險，改用 2 fs。",
                              "Bonded metal site: metal–ligand bonds are stiff and vibrate fast, so 4 fs risks instability; 2 fs is used.")
    elif t["hmr"]:
        o["timestep_fs"] = _r(float(t["dt"]), "氫質量重分配讓 4 fs 步長穩定，速度約為 2 fs 的兩倍。",
                              "Hydrogen mass repartitioning makes a 4 fs step stable, about twice as fast as 2 fs.")
    else:
        o["timestep_fs"] = _r(float(t["dt"]), "研究等級不使用氫質量重分配，以 2 fs 保留原始動力學。",
                              "The research tier does not repartition hydrogen mass and keeps the original dynamics at 2 fs.")
    prod = float(t["prod_ps"]) / 1000.0
    pz, pe = f"{tier} 等級預設長度。", f"Default length of the {tier} tier."
    if pep and tier == "teaching":
        prod, pz, pe = 20.0, "胜肽構形鬆弛比小分子慢，教學等級延長到 20 ns。", "Peptides relax more slowly than small molecules; teaching tier extended to 20 ns."
    elif multi_sim and tier == "teaching":
        prod, pz, pe = 20.0, "多個配體同時在口袋中，需要更長時間觀察是否有配體離開。", "With several ligands in the pocket, a longer run is needed to see whether any of them leaves."
    o["production_ns"] = _r(prod, pz, pe)
    reps = 3 if goal == "publication" else 1
    o["replicas"] = _r(reps, *(("發表等級需至少 3 次不同初速的獨立重複，才能報告標準差。",
                               "Publication grade needs at least three independent replicas with different initial velocities.")
                              if reps == 3 else ("單次模擬可看趨勢；要下結論請增加到 3 次。",
                                                 "One run shows a trend; use three for a conclusion.")))
    o["trajectory_interval_ps"] = _r(20.0 if prod < 50 else 50.0, "每 20 到 50 ps 存一幀，足以做 RMSD、RMSF 與接觸頻率分析，檔案大小可控。",
                                     "One frame every 20 to 50 ps is enough for RMSD, RMSF and contact frequencies at a manageable file size.")
    # binding
    o["binding"] = _r(bool(want_binding), *(("目標是結合強度：SMD 產生解離路徑，傘狀採樣沿路徑計算自由能剖面。",
                                             "The goal is binding strength: SMD generates a dissociation path and umbrella "
                                             "sampling computes the free-energy profile along it.") if want_binding else
                                            ("本目標不需要自由能；開啟會增加數倍計算時間。",
                                             "This goal does not need a free energy; enabling it multiplies the computing time.")))
    o["pull_distance_nm"] = _r(2.0 if pep else 1.5, *(("胜肽較長，需要拉得更遠才能完全離開蛋白表面。",
                                                       "A peptide is longer and has to be pulled further to leave the protein surface.") if pep else
                                                      ("1.5 nm 讓配體完全脫離口袋，剖面末端應趨於平坦。",
                                                       "1.5 nm takes the ligand fully out of the pocket; the profile should flatten at the end.")))
    slow = pep or goal == "publication"
    o["pull_velocity_nm_per_ps"] = _r(0.005 if slow else 0.01, *(("較慢的拉速減少彈簧振盪與非平衡功；胜肽與發表等級使用 0.005。",
                                                                  "A slower pull reduces spring ringing and non-equilibrium work; "
                                                                  "peptides and publication grade use 0.005.") if slow else
                                                                 ("教學預設 0.01 nm ps⁻¹；SMD 只用來產生窗口起點，自由能由傘狀採樣決定。",
                                                                  "Teaching default 0.01 nm ps⁻¹; SMD only provides window "
                                                                  "starting points, the free energy comes from umbrella sampling.")))
    o["k_pull"] = _r(1000.0, "1000 kJ mol⁻¹ nm⁻² 讓配體跟隨彈簧又不至於過硬。",
                     "1000 kJ mol⁻¹ nm⁻² makes the ligand follow the spring without being too stiff.")
    o["k_umbrella"] = _r(1000.0, "窗口間距 0.05 到 0.1 nm 時，1000 可得到足夠重疊；陡峭區段系統會自動加硬。",
                         "With 0.05 to 0.1 nm window spacing, 1000 gives enough overlap; steep stretches are stiffened automatically.")
    wprod = {"classroom": 50.0, "teaching": 500.0, "research": 2000.0}[tier]
    o["window_prod_ps"] = {"classroom": _r(wprod, "課堂等級只看剖面趨勢，不輸出 ΔG°。", "Classroom tier shows the profile trend only; no ΔG° is reported."),
                           "teaching": _r(wprod, "教學等級要輸出 ΔG°，每個窗口至少 500 ps。", "To report ΔG° at the teaching tier, each window needs at least 500 ps."),
                           "research": _r(wprod, "研究等級每個窗口 2 ns，並以前後半段一致性檢查收斂。",
                                          "Research tier: 2 ns per window, with convergence checked by first-half/second-half agreement.")}[tier]
    o["window_equil_ps"] = _r(max(10.0, wprod / 10.0), "每個窗口先丟棄約 10 % 讓配體在新位置鬆弛。",
                              "About 10 % of each window is discarded while the ligand relaxes at its new position.")
    o["target_overlap"] = _r(0.2, "相鄰窗口分佈重疊至少 0.2，MBAR 才能可靠連接整條剖面。",
                             "Neighbouring windows must overlap by at least 0.2 for MBAR to join the profile reliably.")
    return o


def recommend(f: CaseFeatures, goal: str = "teaching", lang: str = "en") -> dict[str, dict]:
    """Recommended starting value and reason for every parameter, for this case and goal."""
    return {k: {"value": r["value"], "why": tx(r["why"], lang)} for k, r in _recommend_raw(f, goal).items()}


def recommended_values(f: CaseFeatures, goal: str = "teaching") -> dict:
    return {k: r["value"] for k, r in _recommend_raw(f, goal).items()}


# ----------------------------------------------------------------------------------- read / write config
def values_from_config(cfg: dict) -> dict:
    """The parameter values a config really sets (nothing is filled in)."""
    md, dk, b = cfg.get("md") or {}, cfg.get("docking") or {}, cfg.get("binding") or {}
    bc, so, ions = b.get("config") or {}, md.get("stage_overrides") or {}, md.get("ions") or {}
    pairs = [("docking_mode", dk.get("mode")), ("exhaustiveness", dk.get("exhaustiveness")), ("n_poses", dk.get("n_poses")),
             ("solvent", md.get("solvent")), ("padding_nm", md.get("padding_nm")), ("box_shape", md.get("box_shape")),
             ("ion_positive", ions.get("positive")), ("ion_negative", ions.get("negative")),
             ("ion_concentration_molar", ions.get("concentration_molar")), ("neutralize", ions.get("neutralize")),
             ("tier", md.get("tier")), ("restraints", md.get("restraints")), ("production_ns", md.get("production_ns")),
             ("replicas", md.get("replicas")), ("binding", b.get("enabled") if "enabled" in b else None),
             ("minimize_iterations", (so.get("minimize") or {}).get("max_iterations")),
             ("minimize_tolerance", (so.get("minimize") or {}).get("tolerance_kj_mol_nm")),
             ("heat_start_k", (so.get("nvt") or {}).get("start_temperature_k")),
             ("nvt_ps", (so.get("nvt") or {}).get("length_ps")), ("npt_ps", (so.get("npt") or {}).get("length_ps")),
             ("temperature_k", (so.get("production") or {}).get("temperature_k")),
             ("pressure_bar", (so.get("production") or {}).get("pressure_bar")),
             ("friction_per_ps", (so.get("production") or {}).get("friction_per_ps")),
             ("timestep_fs", (so.get("production") or {}).get("timestep_fs")),
             ("trajectory_interval_ps", (so.get("production") or {}).get("trajectory_interval_ps"))]
    pairs += [(k, bc.get(k)) for k in ("pull_distance_nm", "pull_velocity_nm_per_ps", "k_pull", "k_umbrella",
                                       "window_equil_ps", "window_prod_ps", "target_overlap")]
    return {k: v for k, v in pairs if v is not None}


def apply(values: dict, cfg: dict) -> dict:
    """Write parameter values into a copy of the workflow config; keys absent from `values` are left untouched."""
    out = copy.deepcopy(cfg)
    md, dk = out.setdefault("md", {}), out.setdefault("docking", {})
    b = out.setdefault("binding", {"enabled": False, "ligands": [], "config": {}})
    bc = b.setdefault("config", {})
    so = md.setdefault("stage_overrides", {})
    v = {k: x for k, x in values.items() if x is not None and k in PARAMS}
    for k, (node, key) in {"docking_mode": (dk, "mode"), "exhaustiveness": (dk, "exhaustiveness"), "n_poses": (dk, "n_poses"),
                           "solvent": (md, "solvent"), "padding_nm": (md, "padding_nm"), "box_shape": (md, "box_shape"),
                           "tier": (md, "tier"), "restraints": (md, "restraints"), "production_ns": (md, "production_ns"),
                           "replicas": (md, "replicas")}.items():
        if k in v:
            node[key] = v[k]
    if any(k in v for k in ("ion_positive", "ion_negative", "ion_concentration_molar", "neutralize")):
        ions = md.setdefault("ions", {"positive": "Na+", "negative": "Cl-", "concentration_molar": 0.15, "neutralize": True})
        for k, key in (("ion_positive", "positive"), ("ion_negative", "negative"),
                       ("ion_concentration_molar", "concentration_molar"), ("neutralize", "neutralize")):
            if k in v:
                ions[key] = v[k]
    if "binding" in v:
        b["enabled"] = bool(v["binding"])
        if b["enabled"] and not b.get("ligands"):
            b["ligands"] = [l["name"] for l in out.get("ligands") or [] if isinstance(l, dict) and l.get("name")]
    for k in ("pull_distance_nm", "pull_velocity_nm_per_ps", "k_pull", "k_umbrella", "window_equil_ps", "window_prod_ps",
              "target_overlap", "temperature_k"):          # binding keeps its own 2 fs step (no HMR in windows)
        if k in v:
            bc[k] = v[k]

    def st(name):
        return so.setdefault(name, {})
    for k, (stage, key) in {"minimize_iterations": ("minimize", "max_iterations"),
                            "minimize_tolerance": ("minimize", "tolerance_kj_mol_nm"),
                            "heat_start_k": ("nvt", "start_temperature_k"), "nvt_ps": ("nvt", "length_ps"),
                            "npt_ps": ("npt", "length_ps"),
                            "trajectory_interval_ps": ("production", "trajectory_interval_ps")}.items():
        if k in v:
            st(stage)[key] = int(v[k]) if PARAMS[k]["type"] == "int" else float(v[k])
    for k, stages in (("temperature_k", ("nvt", "npt", "production")), ("friction_per_ps", ("nvt", "npt", "production")),
                      ("pressure_bar", ("npt", "production")), ("timestep_fs", ("minimize", "nvt", "npt", "production"))):
        if k in v:
            for name in stages:
                st(name)[k] = float(v[k])
    md["stage_overrides"] = {k: x for k, x in so.items() if x}
    if not md["stage_overrides"]:
        md.pop("stage_overrides")
    return out


# ----------------------------------------------------------------------------------- checks
def _i(level, key, zh, en, suggestion=None) -> dict:
    return {"level": level, "key": key, "text": (zh, en), "suggestion": suggestion}


def check(values: dict, f: CaseFeatures, *, goal: str = "teaching", budget_hours: float | None = None,
          lang: str = "en") -> list[dict]:
    """Plausibility of a parameter set.  level: error (will fail, or physically wrong), warning (runs, but the result
    is weak or misleading), info (worth knowing).  Missing keys are taken from the recommendation."""
    rec = recommended_values(f, goal)
    v = {**rec, **{k: x for k, x in values.items() if x is not None}}
    out: list[dict] = []
    tier = v["tier"]
    hmr = TIERS.get(tier, TIERS["teaching"])["hmr"]
    pep = f.ligand_kind in ("peptide", "mixed")
    explicit = v.get("solvent", "explicit") == "explicit"
    dt = float(v["timestep_fs"])
    if dt > 4.0:
        out.append(_i("error", "timestep_fs", f"步長 {dt:g} fs 超過 4 fs：即使使用氫質量重分配，含氫鍵振動也會讓積分發散。",
                      f"A {dt:g} fs step exceeds 4 fs: even with hydrogen mass repartitioning the integration diverges.",
                      4.0 if hmr else 2.0))
    elif dt > 2.0 and not hmr:
        out.append(_i("error", "timestep_fs", f"{tier} 等級不使用氫質量重分配，{dt:g} fs 會讓含氫鍵振動失穩。",
                      f"The {tier} tier does not repartition hydrogen mass; {dt:g} fs makes bonds to hydrogen unstable.", 2.0))
    elif dt > 2.0 and f.metals:
        out.append(_i("warning", "timestep_fs", "含金屬鍵結模型時 4 fs 有失穩風險（金屬與配位原子間的鍵振動快）。",
                      "With a bonded metal site 4 fs risks instability (metal–ligand bonds vibrate fast).", 2.0))
    T = float(v["temperature_k"])
    if T < 273 or T > 373:
        out.append(_i("error", "temperature_k", f"{T:g} K 在液態水範圍外，TIP3P 水模型與 Amber 力場在此溫度沒有意義。",
                      f"{T:g} K is outside liquid water; TIP3P and the Amber force field are meaningless there.", 300.0))
    elif T > 330:
        out.append(_i("warning", "temperature_k", f"{T:g} K 明顯高於生理溫度，可能使蛋白局部變性；除非刻意做高溫模擬。",
                      f"{T:g} K is well above physiological temperature and may partly unfold the protein, unless intended.", 310.0))
    if float(v["heat_start_k"]) >= T:
        out.append(_i("error", "heat_start_k", "加熱起始溫度不低於目標溫度，等於沒有升溫。",
                      "The heating start temperature is not below the target, so there is no heating.", 50.0))
    if float(v["nvt_ps"]) < 50:
        out.append(_i("warning", "nvt_ps", f"加熱只有 {float(v['nvt_ps']):g} ps，溫度可能尚未穩定就進入定壓平衡。",
                      f"Only {float(v['nvt_ps']):g} ps of heating; temperature may not be stable before NPT.", rec["nvt_ps"]))
    if explicit and float(v["npt_ps"]) < 100:
        out.append(_i("warning", "npt_ps", f"定壓平衡只有 {float(v['npt_ps']):g} ps，水盒密度尚未收斂。",
                      f"Only {float(v['npt_ps']):g} ps of NPT; the box density has not converged.", rec["npt_ps"]))
    if (pep or f.metals or f.structure_source == "model" or f.has_gaps) and v["restraints"] == "standard":
        out.append(_i("warning", "restraints", "起始結構較粗糙（胜肽、金屬、預測模型或補建缺口），標準釋放可能讓結構在升溫時變形。",
                      "The starting structure is rough (peptide, metal, model or rebuilt gaps); the standard release may "
                      "distort it during heating.", "gentle"))
    if v["restraints"] == "hold_backbone":
        out.append(_i("info", "restraints", "正式模擬保留主鏈約束：RMSD 與 RMSF 會被壓低，報告會標註為受約束的數值。",
                      "Backbone restrained in production: RMSD and RMSF are suppressed and are labelled as restrained in the report."))
    prod = float(v["production_ns"])
    if prod < 1:
        out.append(_i("warning", "production_ns", f"正式模擬 {prod:g} ns 只能檢查流程，不足以判斷複合物穩定性。",
                      f"{prod:g} ns of production only checks the workflow; it cannot judge complex stability.", rec["production_ns"]))
    elif goal == "publication" and prod < 50:
        out.append(_i("warning", "production_ns", f"發表等級通常需要 50 ns 以上；{prod:g} ns 審稿時容易被質疑。",
                      f"Publication usually needs 50 ns or more; {prod:g} ns invites reviewer questions.", 100.0))
    if goal == "publication" and int(v["replicas"]) < 3:
        out.append(_i("warning", "replicas", "只有一次模擬無法報告標準差；發表等級建議至少 3 次獨立重複。",
                      "A single run gives no standard deviation; publication grade needs at least three replicas.", 3))
    fr = float(v["friction_per_ps"])
    if fr < 0.1 or fr > 10:
        out.append(_i("warning", "friction_per_ps", f"摩擦係數 {fr:g} ps⁻¹ 偏離常用範圍（0.1 到 5），會扭曲擴散與構形動態。",
                      f"A friction of {fr:g} ps⁻¹ is outside the usual 0.1–5 range and distorts diffusion and dynamics.", 1.0))
    if abs(float(v["pressure_bar"]) - 1.0) > 0.5:
        out.append(_i("info", "pressure_bar", "非常壓條件；請確認這是刻意的（例如高壓實驗）。",
                      "Non-ambient pressure; make sure this is intended (e.g. a high-pressure experiment)."))
    c = float(v["ion_concentration_molar"])
    if c < 0:
        out.append(_i("error", "ion_concentration_molar", "鹽濃度不能為負。", "The salt concentration cannot be negative.", 0.15))
    elif c > 1.0:
        out.append(_i("warning", "ion_concentration_molar", f"{c:g} M 已超出生理範圍，單價離子參數在高濃度下可能析出結晶。",
                      f"{c:g} M is far above physiological; monovalent ion parameters may crystallise at this concentration.", 0.15))
    if not v["neutralize"] and explicit:
        out.append(_i("warning", "neutralize", "不中和淨電荷時，PME 會加入均勻背景電荷，影響帶電配體的結合能。",
                      "Without neutralisation PME adds a uniform background charge that biases charged-ligand binding.", True))
    pad = float(v["padding_nm"])
    if explicit and pad < 0.8:
        out.append(_i("error", "padding_nm", f"邊距 {pad:g} nm 小於 0.8 nm：蛋白會與自身鏡像作用（截斷距離 1.0 nm）。",
                      f"A padding of {pad:g} nm is below 0.8 nm: the protein interacts with its own image (1.0 nm cut-off).", 0.8))
    if v["binding"] and pad < 1.2:
        out.append(_i("warning", "padding_nm", "結合強度計算要把配體拉出口袋，邊距不足時拉離路徑會接近鏡像蛋白。",
                      "Binding calculations pull the ligand out; with this padding the path approaches the periodic image.", 1.2))
    if v["binding"] and not explicit:
        out.append(_i("error", "solvent", "隱式溶劑沒有週期性水盒，無法做 SMD 與傘狀採樣。",
                      "Implicit solvent has no periodic box; SMD and umbrella sampling are not possible.", "explicit"))
    exh = int(v["exhaustiveness"])
    if exh < 8:
        out.append(_i("warning", "exhaustiveness", f"搜尋強度 {exh} 太低，重複對接的結果可能每次不同。",
                      f"An exhaustiveness of {exh} is too low; repeated docking may give different answers.", rec["exhaustiveness"]))
    elif pep and exh < 32:
        out.append(_i("info", "exhaustiveness", "胜肽配體：系統會自動提高到 32。", "Peptide ligand: raised to 32 automatically.", 32))
    if f.box_size and max(f.box_size) > 40:
        out.append(_i("warning", "exhaustiveness", f"搜尋區最長邊 {max(f.box_size):.0f} Å 超過 40 Å，等同盲對接；建議以共結晶配體或活性位殘基定義搜尋區。",
                      f"The longest box edge is {max(f.box_size):.0f} Å (over 40 Å), effectively blind docking; define the "
                      "box from a co-crystal ligand or active-site residues."))
    if v["binding"]:
        vel = float(v["pull_velocity_nm_per_ps"])
        if vel > 0.02:
            out.append(_i("warning", "pull_velocity_nm_per_ps", f"拉速 {vel:g} nm ps⁻¹ 過快，彈簧振盪會讓窗口起點偏離。",
                          f"{vel:g} nm ps⁻¹ is too fast; spring ringing displaces the window starting points.", 0.01))
        elif vel < 0.0005:
            out.append(_i("info", "pull_velocity_nm_per_ps", "拉速很慢：SMD 會很長，但自由能仍由傘狀採樣決定，通常不需要這麼慢。",
                          "Very slow pull: SMD becomes long, while the free energy still comes from umbrella sampling."))
        ku = float(v["k_umbrella"])
        if ku < 300 or ku > 5000:
            out.append(_i("warning", "k_umbrella", f"彈簧常數 {ku:g} 偏離常用範圍（300 到 5000）：太軟窗口重疊過多，太硬則重疊不足。",
                          f"A spring constant of {ku:g} is outside 300–5000: too soft over-broadens windows, too stiff loses overlap.", 1000.0))
        wp = float(v["window_prod_ps"])
        if wp < 20:
            out.append(_i("warning", "window_prod_ps", f"每個窗口只取樣 {wp:g} ps，分佈尚未收斂。",
                          f"Only {wp:g} ps per window; the distributions have not converged.", rec["window_prod_ps"]))
        need = {"teaching": 500.0, "research": 2000.0}.get(tier)
        if need and wp < need:
            out.append(_i("info", "window_prod_ps", f"{tier} 等級要輸出 ΔG° 需每個窗口至少 {need:g} ps；目前長度只輸出自由能剖面。",
                          f"The {tier} tier reports ΔG° only with at least {need:g} ps per window; this length gives the profile only.", need))
        if float(v["window_equil_ps"]) >= wp:
            out.append(_i("error", "window_equil_ps", "窗口平衡時間不短於取樣時間，等於沒有有效樣本。",
                          "Window equilibration is not shorter than sampling, leaving no usable samples.", max(10.0, wp / 10)))
    if budget_hours:
        est = estimate_hours(v, f)
        if est.get("total_hours") and est["total_hours"] > budget_hours:
            out.append(_i("warning", "production_ns", f"估計需要約 {est['total_hours']:.1f} 小時，超過可用時間 {budget_hours:g} 小時。",
                          f"Estimated {est['total_hours']:.1f} h exceeds the available {budget_hours:g} h."))
    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda i: order[i["level"]])
    return [{"level": i["level"], "key": i["key"], "label": param_label(i["key"], lang), "message": tx(i["text"], lang),
             "suggestion": i["suggestion"]} for i in out]


# ----------------------------------------------------------------------------------- cost
def system_atoms(f: CaseFeatures, padding_nm: float = 0.8, solvent: str = "explicit") -> int:
    """Rough atom count of the solvated system (protein with hydrogens, water, ions)."""
    n = f.n_residues or 300
    protein = n * 16
    if solvent == "gbn2":
        return protein
    r_nm = 0.1 * 1.29 * 2.2 * n ** 0.38          # sphere radius ≈ 1.29·Rg, Rg ≈ 2.2·N^0.38 Å
    edge = 2 * (r_nm + padding_nm)
    vol = 0.707 * edge ** 3                        # rhombic dodecahedron ≈ 0.707 a³
    water = max(0.0, vol - n * 0.135) * 33.4 * 3   # 33.4 waters nm⁻³, protein ≈ 0.135 nm³ per residue
    return int(protein + water)


def estimate_hours(values: dict, f: CaseFeatures, goal: str = "teaching") -> dict:
    """Wall-clock estimate from the measured benchmark, scaled by atom count and time step."""
    if not f.ns_per_day:
        return {"total_hours": None, "note": ("尚未在本機執行效能測試，無法估計時間。",
                                              "No benchmark on this computer yet; time cannot be estimated.")}
    v = {**recommended_values(f, goal), **{k: x for k, x in values.items() if x is not None}}
    atoms = system_atoms(f, float(v["padding_nm"]), v.get("solvent", "explicit"))
    speed = f.ns_per_day * (float(v["timestep_fs"]) / f.bench_dt_fs) * (f.bench_atoms / max(atoms, 1000))
    md_ns = (float(v["nvt_ps"]) + float(v["npt_ps"]) * (2 if v["restraints"] == "gentle" else 1)) / 1000 + float(v["production_ns"])
    systems = 1 + (f.n_ligands if v.get("docking_mode", f.docking_mode) == "independent" else 1)
    md_h = md_ns * systems * int(v["replicas"]) / speed * 24
    bind_h = 0.0
    if v["binding"]:
        smd_ps = float(v["pull_distance_nm"]) / float(v["pull_velocity_nm_per_ps"])
        n_win = math.ceil(float(v["pull_distance_nm"]) / 0.08) * 1.4      # initial windows plus adaptive refinement
        bind_ns = (smd_ps + n_win * (float(v["window_equil_ps"]) + float(v["window_prod_ps"]))) / 1000
        bind_h = bind_ns * f.n_ligands / speed * 24
    return {"atoms": atoms, "ns_per_day": round(speed, 1), "md_hours": round(md_h, 1), "binding_hours": round(bind_h, 1),
            "total_hours": round(md_h + bind_h, 1), "systems": systems}


def parameter_table(values: dict, f: CaseFeatures, goal: str = "teaching", lang: str = "en",
                    keys: list | None = None) -> list[dict]:
    """Rows for the GUI form and the report: parameter, value used, recommended value, reason, changed by the user."""
    rec = _recommend_raw(f, goal)
    rows = []
    for g in GROUP_ORDER:
        for k, p in PARAMS.items():
            if p["group"] != g or (keys and k not in keys):
                continue
            r = rec.get(k, {})
            used = values.get(k, r.get("value"))
            rows.append({"group": tx(GROUPS[g], lang), "group_key": g, "key": k, "label": param_label(k, lang),
                         "unit": p["unit"], "type": p["type"], "value": used, "recommended": r.get("value"),
                         "value_text": format_value(k, used, lang), "recommended_text": format_value(k, r.get("value"), lang),
                         "why": tx(r.get("why"), lang), "changed": k in values and values[k] != r.get("value")})
    return rows
