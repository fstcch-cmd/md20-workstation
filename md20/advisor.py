"""Case-aware parameter advisor (D-49): recommended starting values with reasons, plausibility checks, cost estimate.

Used by every entry point (GUI quick, pro and teaching modes, CLI, report), so the value a user sees in the form, the
reason next to it and the "parameters used" table in the report all come from one place.  Four languages (D-74:
English default, Traditional Chinese, Japanese, Korean): every text is a (zh, en, ja, ko) tuple resolved by `lang`.

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
from .engine.restraint_advice import (RestraintInputs, advise as _advise_restraints, rough_reasons as _rough_reasons,
                                      resolution_from_pdb, plddt_low_fraction_from_pdb)

METALS = {"ZN", "MG", "CA", "MN", "FE", "FE2", "CU", "CU1", "CO", "NI", "CD", "HG"}
from .i18n import LANGS, pick as tx   # noqa: E402,F401  (D-74: zh, en, ja, ko)


GOALS = {
    "teaching": ("課堂示範：完整走一次流程，看懂每個閘門",
                 "Classroom demonstration: run the whole workflow once and understand every gate",
                 "授業での実演：ワークフローを一通り実行し、各ゲートの意味を理解する",
                 "수업 시연: 워크플로를 처음부터 끝까지 실행하고 각 게이트 이해"),
    "screening": ("化合物比較：用對接與複合物穩定性比較多個配體",
                  "Compound comparison: rank several ligands by docking and complex stability",
                  "化合物の比較：ドッキングと複合体の安定性で複数のリガンドを比べる",
                  "화합물 비교: 도킹과 복합체 안정성으로 여러 리간드 비교"),
    "binding": ("結合強度：用 SMD 與傘狀採樣算出自由能剖面",
                "Binding strength: free-energy profile from SMD and umbrella sampling",
                "結合の強さ：SMD とアンブレラサンプリングで自由エネルギープロファイルを求める",
                "결합 세기: SMD와 엄브렐라 샘플링으로 자유 에너지 프로파일 계산"),
    "publication": ("發表等級：夠長、有獨立重複、能報告不確定度",
                    "Publication grade: long enough, replicated, with an uncertainty",
                    "論文発表レベル：十分な長さ、独立した繰り返し、不確かさの報告",
                    "논문 발표 수준: 충분한 길이, 독립 반복, 불확도 보고"),
}


@dataclass
class CaseFeatures:
    n_residues: int | None = None          # receptor protein residues (None = not known yet)
    n_ligands: int = 1
    ligand_kind: str = "small"             # small | peptide | mixed
    peptide_length: int | None = None
    docking_mode: str = "independent"
    metals: list = field(default_factory=list)          # metals kept in the receptor (non-bonded ions by default)
    bonded_metals: list = field(default_factory=list)   # sites with metal_policy "bonded" (stiff bonded model)
    structure_source: str = "crystal"      # crystal | model
    has_gaps: bool = False
    box_from_site: bool = True
    box_size: list | None = None
    binding: bool = False
    ns_per_day: float | None = None        # measured on this computer (Doctor benchmark)
    bench_atoms: int = 24000
    bench_dt_fs: float = 4.0
    gpu: bool | None = None
    # restraint advice inputs (D-118); None = not known
    has_ligand: bool = True                # False = apo run
    membrane: bool = False
    resolution_a: float | None = None      # crystal resolution, from the PDB header
    plddt_low_fraction: float | None = None   # share of residues with pLDDT < 70 (predicted models)
    n_rebuilt_residues: int | None = None  # residues added by a loop rebuild (build manifest)
    n_pose_clashes: int | None = None      # clashes in the docked pose (docking result)

    def to_dict(self) -> dict:
        return asdict(self)


# ----------------------------------------------------------------------------------- parameter schema
def P(zh, en, ja, ko, unit="", group="", type="float", **kw):
    return {"label": (zh, en, ja, ko), "unit": unit, "group": group, "type": type, **kw}


GROUPS = {"docking": ("分子對接", "Molecular docking", "分子ドッキング", "분자 도킹"),
          "system": ("模擬系統", "Simulation system", "シミュレーション系", "시뮬레이션 계"),
          "equil": ("平衡流程", "Equilibration", "平衡化", "평형"),
          "prod": ("正式模擬", "Production", "本計算", "본 계산"),
          "binding": ("結合自由能", "Binding free energy", "結合自由エネルギー", "결합 자유 에너지")}
GROUP_ORDER = list(GROUPS)
PARAMS: dict[str, dict] = {
    "docking_mode": P("多配體對接方式", "Multi-ligand docking", "複数リガンドのドッキング方法", "다중 리간드 도킹 방식",
                      group="docking", type="choice",
                      choices={"independent": ("各自對接（每個配體單獨對接）", "Independent (each ligand alone)",
                                               "個別ドッキング（リガンドごとに単独）", "개별 도킹(리간드마다 단독)"),
                               "simultaneous": ("同時對接（多個配體一起放進口袋）", "Simultaneous (ligands together)",
                                                "同時ドッキング（複数のリガンドを一緒に）", "동시 도킹(여러 리간드를 함께)")}),
    "exhaustiveness": P("對接搜尋強度", "Search exhaustiveness", "探索の徹底度（exhaustiveness）", "탐색 강도(exhaustiveness)",
                        group="docking", type="int", min=1, max=128),
    "n_poses": P("每個配體保留的姿勢數", "Poses kept per ligand", "リガンドごとに残すポーズ数", "리간드당 유지할 포즈 수",
                 group="docking", type="int", min=1, max=20),
    "solvent": P("溶劑模型", "Solvent model", "溶媒モデル", "용매 모델", group="system", type="choice",
                 choices={"explicit": ("顯式水（TIP3P，週期性邊界）", "Explicit water (TIP3P, periodic)",
                                       "陽溶媒の水（TIP3P、周期境界）", "명시적 물(TIP3P, 주기 경계)"),
                          "gbn2": ("隱式溶劑（GBn2，沒有水盒）", "Implicit solvent (GBn2, no water box)",
                                   "陰溶媒（GBn2、水ボックスなし）", "암시적 용매(GBn2, 물 상자 없음)")}),
    "padding_nm": P("水盒邊距", "Box padding", "水ボックスの余白", "물 상자 여백", "nm", "system", min=0.5, max=3.0, step=0.1),
    "box_for_smd": P("為 SMD 預留水盒", "Box ready for SMD", "SMD 用に水ボックスを確保", "SMD용 물 상자 확보", group="system",
                     type="choice", choices={"auto": ("自動（便宜就先加大，否則事先提醒）", "Auto (enlarge when cheap, otherwise warn before MD)",
                                                      "自動（安ければ先に広げ、そうでなければ MD 前に知らせる）", "자동(저렴하면 미리 넓히고, 아니면 MD 전에 알림)"),
                                             "always": ("一律依 SMD 規則加大", "Always size for SMD", "常に SMD の規則で広げる", "항상 SMD 규칙으로 넓힘"),
                                             "never": ("不檢查", "Do not check", "確認しない", "확인하지 않음")}),
    "box_shape": P("水盒形狀", "Box shape", "水ボックスの形", "물 상자 모양", group="system", type="choice",
                   choices={"dodecahedron": ("菱形十二面體", "Rhombic dodecahedron", "菱形十二面体", "마름모 십이면체"),
                            "cube": ("立方體", "Cube", "立方体", "정육면체")}),
    "ion_positive": P("陽離子", "Cation", "陽イオン", "양이온", group="system", type="choice",
                      choices={k: (k, k, k, k) for k in ("Na+", "K+", "Li+", "Rb+", "Cs+")}),
    "ion_negative": P("陰離子", "Anion", "陰イオン", "음이온", group="system", type="choice",
                      choices={k: (k, k, k, k) for k in ("Cl-", "Br-", "F-", "I-")}),
    "ion_concentration_molar": P("鹽濃度", "Salt concentration", "塩濃度", "염 농도", "M", "system", min=0.0, max=2.0, step=0.01),
    "neutralize": P("用反離子中和淨電荷", "Neutralise net charge", "対イオンで正味電荷を中和", "반대 이온으로 알짜 전하 중화",
                    group="system", type="bool"),
    "tier": P("模擬等級", "Simulation tier", "シミュレーションのレベル", "시뮬레이션 등급", group="equil", type="choice",
              choices={"classroom": ("課堂（2 ns）", "Classroom (2 ns)", "授業（2 ns）", "수업(2 ns)"),
                       "teaching": ("教學（10 ns）", "Teaching (10 ns)", "教育（10 ns）", "교육(10 ns)"),
                       "research": ("研究（100 ns，2 fs）", "Research (100 ns, 2 fs)", "研究（100 ns、2 fs）", "연구(100 ns, 2 fs)")}),
    "restraints": P("位置約束的釋放方式", "Restraint release strategy", "位置拘束の解除方法", "위치 구속 해제 방식",
                    group="equil", type="choice",
                    choices={"standard": ("標準：在定壓平衡中逐步釋放", "Standard: released during NPT",
                                          "標準：NPT 平衡化の中で段階的に解除", "표준: NPT 평형 중 단계적 해제"),
                             "gentle": ("溫和：約束保留到加熱結束，定壓平衡加倍", "Gentle: held through heating, NPT doubled",
                                        "穏やか：加熱終了まで拘束を保持し、NPT は2倍", "완만: 가열 끝까지 구속 유지, NPT 2배"),
                             "hold_backbone": ("主鏈保留 5 % 約束到正式模擬", "Backbone held at 5 % in production",
                                               "本計算でも主鎖の拘束を 5 % 残す", "본 계산에서도 주사슬 구속 5 % 유지")}),
    "minimize_iterations": P("能量最小化最大步數", "Maximum minimisation steps", "エネルギー最小化の最大ステップ数",
                             "에너지 최소화 최대 단계 수", "", "equil", type="int", min=100, max=100000),
    "minimize_tolerance": P("能量最小化收斂門檻", "Minimisation tolerance", "エネルギー最小化の収束しきい値", "에너지 최소화 수렴 기준",
                            "kJ mol⁻¹ nm⁻¹", "equil", min=0.1, max=1000),
    "heat_start_k": P("加熱起始溫度", "Heating start temperature", "加熱の開始温度", "가열 시작 온도", "K", "equil",
                      min=0, max=400, step=10),
    "nvt_ps": P("定容加熱時間", "Heating time (NVT)", "加熱時間（NVT）", "가열 시간(NVT)", "ps", "equil", min=0, max=10000, step=10),
    "npt_ps": P("定壓平衡時間", "Pressure equilibration (NPT)", "圧力平衡化の時間（NPT）", "압력 평형 시간(NPT)", "ps", "equil",
                min=0, max=20000, step=10),
    "temperature_k": P("模擬溫度", "Temperature", "温度", "온도", "K", "prod", min=250, max=400, step=1),
    "pressure_bar": P("壓力", "Pressure", "圧力", "압력", "bar", "prod", min=0.5, max=1000, step=0.5),
    "friction_per_ps": P("Langevin 摩擦係數", "Langevin friction", "Langevin 摩擦係数", "Langevin 마찰 계수", "ps⁻¹", "prod",
                         min=0.01, max=50, step=0.1),
    "timestep_fs": P("積分步長", "Time step", "時間刻み", "시간 간격", "fs", "prod", min=0.5, max=5, step=0.5),
    "production_ns": P("正式模擬長度", "Production length", "本計算の長さ", "본 계산 길이", "ns", "prod", min=0.1, max=10000, step=1),
    "replicas": P("獨立重複次數", "Independent replicas", "独立した繰り返しの回数", "독립 반복 횟수", "", "prod", type="int",
                  min=1, max=10),
    "trajectory_interval_ps": P("軌跡存檔間隔", "Trajectory save interval", "トラジェクトリの保存間隔", "궤적 저장 간격", "ps", "prod",
                                min=1, max=1000),
    "binding": P("計算結合強度（SMD 與傘狀採樣）", "Compute binding strength (SMD and umbrella sampling)",
                 "結合の強さを計算（SMD とアンブレラサンプリング）", "결합 세기 계산(SMD와 엄브렐라 샘플링)", group="binding", type="bool"),
    "pull_distance_nm": P("拉離距離", "Pulling distance", "引き離し距離", "당김 거리", "nm", "binding", min=0.5, max=5, step=0.1),
    "pull_velocity_nm_per_ps": P("拉離速度", "Pulling velocity", "引き離し速度", "당김 속도", "nm ps⁻¹", "binding",
                                 min=0.0001, max=0.1, step=0.001),
    "k_pull": P("拉離彈簧常數", "Pulling spring constant", "引き離しのばね定数", "당김 스프링 상수", "kJ mol⁻¹ nm⁻²", "binding",
                min=50, max=20000, step=50),
    "k_umbrella": P("傘狀採樣彈簧常數", "Umbrella spring constant", "アンブレラサンプリングのばね定数", "엄브렐라 샘플링 스프링 상수",
                    "kJ mol⁻¹ nm⁻²", "binding", min=50, max=20000, step=50),
    "window_equil_ps": P("每個窗口的平衡時間", "Equilibration per window", "ウィンドウごとの平衡化時間", "윈도우당 평형 시간", "ps",
                         "binding", min=0, max=5000, step=10),
    "window_prod_ps": P("每個窗口的取樣時間", "Sampling per window", "ウィンドウごとのサンプリング時間", "윈도우당 샘플링 시간", "ps",
                        "binding", min=5, max=20000, step=10),
    "target_overlap": P("相鄰窗口的目標重疊", "Target overlap of neighbouring windows", "隣接ウィンドウの目標重なり",
                        "인접 윈도우 목표 겹침", "", "binding", min=0.01, max=0.9, step=0.01),
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
        return tx(("是", "Yes", "はい", "예"), lang) if value else tx(("否", "No", "いいえ", "아니요"), lang)
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
    pol = cfg.get("metal_policy") or {}
    f.bonded_metals = sorted(k for k, v in pol.items() if str(v).lower() == "bonded") if isinstance(pol, dict) else []
    b = cfg.get("box") or {}
    f.has_ligand = bool(ligs)
    f.membrane = bool((cfg.get("md") or {}).get("membrane"))
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
        f.resolution_a = resolution_from_pdb(receptor_text) if f.structure_source == "crystal" else None
        f.plddt_low_fraction = plddt_low_fraction_from_pdb(receptor_text) if f.structure_source == "model" else None
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
def restraint_inputs(f: CaseFeatures, goal: str = "teaching", values: dict | None = None) -> RestraintInputs:
    """Case features, goal and the values in the form -> the inputs of the restraint advice (D-118)."""
    values = values or {}
    return RestraintInputs(has_ligand=f.has_ligand, ligand_kind=f.ligand_kind,
                           simultaneous_ligands=f.n_ligands > 1 and f.docking_mode == "simultaneous",
                           membrane=f.membrane, metals=list(f.metals), bonded_metals=list(f.bonded_metals),
                           structure_source=f.structure_source, resolution_a=f.resolution_a,
                           plddt_low_fraction=f.plddt_low_fraction, has_gaps=f.has_gaps,
                           n_rebuilt_residues=f.n_rebuilt_residues, n_pose_clashes=f.n_pose_clashes,
                           target="smd" if (goal == "binding" or f.binding) else "md",
                           tier=values.get("tier") or {"teaching": "classroom", "screening": "teaching", "binding": "teaching",
                                                       "publication": "research"}.get(goal, "teaching"),
                           production_ns=values.get("production_ns"), current=values.get("restraints"))


def restraint_advice(f: CaseFeatures, goal: str = "teaching", values: dict | None = None, lang: str = "en") -> dict:
    """Advice on the restraint release (D-118, spec restraints_freeze_truncation 3.1).  Advice only: nothing in the config
    or the protocol changes until the user adopts `protocol_args["restraints"]` (then it is the ordinary `md.restraints`)."""
    return _advise_restraints(restraint_inputs(f, goal, values), lang)


def _r(value, zh: str, en: str, ja: str, ko: str) -> dict:
    return {"value": value, "why": (zh, en, ja, ko)}


def _recommend_raw(f: CaseFeatures, goal: str) -> dict[str, dict]:
    goal = goal if goal in GOALS else "teaching"
    pep = f.ligand_kind in ("peptide", "mixed")
    multi_sim = f.n_ligands > 1 and f.docking_mode == "simultaneous"
    rough_reasons = [short for _, short in _rough_reasons(restraint_inputs(f, goal))]   # one source with restraint_advice
    tier = {"teaching": "classroom", "screening": "teaching", "binding": "teaching", "publication": "research"}[goal]
    t = TIERS[tier]
    o: dict[str, dict] = {}
    o["tier"] = {"classroom": _r(tier, "課堂示範只要完整走過流程。2 ns 看得到平衡過程與每個閘門的行為，但不能拿來下科學結論。",
                                 "A classroom run only has to go through the whole workflow. 2 ns shows equilibration and "
                                 "every gate, but it supports no scientific conclusion.",
                                 "授業での実演はワークフローを一通り動かせば十分です。2 ns で平衡化と各ゲートの動きは確認できますが、"
                                 "科学的な結論には使えません。",
                                 "수업 시연은 워크플로를 끝까지 실행하기만 하면 됩니다. 2 ns면 평형 과정과 각 게이트의 동작을 볼 수 "
                                 "있지만 과학적 결론에는 쓸 수 없습니다."),
                 "teaching": _r(tier, "比較配體或估計結合強度時，口袋與配體的構形至少要 10 ns 才能鬆弛。",
                                "Comparing ligands or estimating binding needs at least 10 ns for the pocket and the ligand to relax.",
                                "リガンドを比べたり結合の強さを見積もったりするには、ポケットとリガンドの構造が緩和するまで"
                                "少なくとも 10 ns 必要です。",
                                "리간드를 비교하거나 결합 세기를 추정하려면 포켓과 리간드 구조가 이완되도록 최소 10 ns가 필요합니다."),
                 "research": _r(tier, "發表等級用 2 fs，不做氫質量重分配，跑 100 ns 並至少重複 3 次，才能報告不確定度。",
                                "For publication, use 2 fs without hydrogen mass repartitioning, 100 ns and at least three "
                                "replicas, so that an uncertainty can be reported.",
                                "論文発表レベルでは水素質量再分配を使わずに 2 fs で 100 ns 計算し、少なくとも 3 回繰り返します。"
                                "これで不確かさを報告できます。",
                                "논문 발표 수준에서는 수소 질량 재분배 없이 2 fs로 100 ns를 계산하고 최소 3회 반복해야 불확도를 "
                                "보고할 수 있습니다.")}[tier]
    # docking
    if f.n_ligands > 1:
        o["docking_mode"] = _r(f.docking_mode if f.docking_mode in ("independent", "simultaneous") else "independent",
                               "有多個配體。各自對接回答「哪個配體比較好」，同時對接回答「它們能不能一起待在口袋裡」，"
                               "例如萃取物成分之間的協同作用。",
                               "There are several ligands. Independent docking tells you which ligand binds best. Simultaneous "
                               "docking asks whether they can sit in the site together, for example synergy between extract "
                               "components.",
                               "リガンドが複数あります。個別ドッキングは「どのリガンドが最もよく結合するか」を、同時ドッキングは"
                               "「一緒にポケットに入れるか」を調べます。抽出物の成分どうしの相乗作用がその例です。",
                               "리간드가 여러 개입니다. 개별 도킹은 어떤 리간드가 가장 잘 결합하는지 알려 주고, 동시 도킹은 "
                               "리간드들이 포켓에 함께 들어갈 수 있는지 봅니다. 추출물 성분 간 상승 작용이 그 예입니다.")
    else:
        o["docking_mode"] = _r("independent", "只有一個配體，用各自對接就可以。", "Only one ligand, so independent docking is enough.",
                               "リガンドが1つなので、個別ドッキングで十分です。", "리간드가 하나이므로 개별 도킹이면 충분합니다.")
    if pep:
        pl = f.peptide_length
        exh, why = 32, (f"胜肽{f'（{pl} 個殘基）' if pl else ''}可轉動的鍵多，搜尋空間大。搜尋強度至少要 32，才能穩定找到低能量姿勢。",
                        f"A peptide{f' ({pl} residues)' if pl else ''} has many rotatable bonds. An exhaustiveness of at "
                        "least 32 is needed to find low-energy poses reproducibly.",
                        f"ペプチド{f'（{pl} 残基）' if pl else ''}は回転可能な結合が多く、探索空間が広くなります。"
                        "低エネルギーのポーズを安定して見つけるには、探索の徹底度を 32 以上にします。",
                        f"펩타이드{f'({pl}개 잔기)' if pl else ''}는 회전 가능한 결합이 많아 탐색 공간이 넓습니다. 낮은 "
                        "에너지의 포즈를 안정적으로 찾으려면 탐색 강도를 32 이상으로 해야 합니다.")
    elif multi_sim:
        exh, why = 32, ("同時對接要搜尋所有配體自由度的總和，搜尋強度要提高。",
                        "Simultaneous docking searches the combined freedom of all ligands, so it needs a higher exhaustiveness.",
                        "同時ドッキングではすべてのリガンドの自由度を合わせて探索するため、探索の徹底度を上げる必要があります。",
                        "동시 도킹은 모든 리간드의 자유도를 합쳐 탐색하므로 더 높은 탐색 강도가 필요합니다.")
    elif goal == "screening" and f.n_ligands > 20:
        exh, why = 8, ("大量化合物初篩時，搜尋強度 8 已足以剔除明顯不合的分子。入選的化合物再用 16 以上正式對接。",
                       "For a large pre-screen, 8 is enough to discard clear misfits. Shortlisted compounds are re-docked "
                       "at 16 or more.",
                       "大量の化合物の一次スクリーニングでは、明らかに合わないものを除くには 8 で足ります。"
                       "候補に残った化合物は 16 以上で改めてドッキングします。",
                       "대량 화합물 1차 스크리닝에서는 8이면 명백히 맞지 않는 분자를 걸러낼 수 있습니다. 후보로 남은 "
                       "화합물은 16 이상으로 다시 도킹합니다.")
    else:
        exh, why = 16, ("藥物大小的小分子用 16，速度與重現性都過得去。Vina 預設的 8 重複性較差。",
                        "For drug-sized molecules 16 balances speed and reproducibility. Vina's default of 8 is less repeatable.",
                        "薬物サイズの低分子では 16 で速度と再現性のバランスが取れます。Vina の既定値 8 は再現性が劣ります。",
                        "약물 크기의 저분자는 16이면 속도와 재현성이 균형을 이룹니다. Vina 기본값 8은 재현성이 떨어집니다.")
    if f.box_size and max(f.box_size) > 30:
        exh = max(exh, 32)
        edge = f"{max(f.box_size):.0f}"
        why = tuple(a + s for a, s in zip(why, (f"搜尋區最長邊 {edge} Å，偏大，所以提高到 32。",
                                                f" The longest box edge is {edge} Å, so it is raised to 32.",
                                                f"探索領域の最長辺が {edge} Å と大きいため、32 に上げます。",
                                                f" 탐색 영역의 가장 긴 변이 {edge} Å로 커서 32로 올립니다.")))
    o["exhaustiveness"] = _r(exh, *why)
    o["n_poses"] = _r(9, "保留 9 個姿勢，夠做叢集分析和人工挑選。再多通常只是同一種結合模式的重複。",
                      "Nine poses are enough for clustering and for picking by hand. More are usually repeats of the same "
                      "binding mode.",
                      "ポーズを 9 個残せば、クラスタリングと手動での選択に十分です。それ以上は同じ結合様式の繰り返しになることが"
                      "ほとんどです。",
                      "포즈 9개면 클러스터링과 수동 선택에 충분합니다. 그 이상은 대개 같은 결합 모드의 반복입니다.")
    # system
    if goal == "teaching" and f.gpu is False and not f.binding and not pep:
        o["solvent"] = _r("gbn2", "這台電腦沒有可用的 GPU，課堂示範可以改用隱式溶劑縮短時間。隱式溶劑不能做 SMD 與傘狀採樣，"
                                  "也無法分析水橋。",
                          "This computer has no usable GPU, so implicit solvent shortens a classroom run. It cannot be used "
                          "for SMD or umbrella sampling, and water bridges cannot be analysed.",
                          "このコンピュータには使える GPU がないため、授業での実演では陰溶媒で時間を短縮できます。陰溶媒では "
                          "SMD とアンブレラサンプリングはできず、水架橋も解析できません。",
                          "이 컴퓨터에는 사용할 수 있는 GPU가 없어 수업 시연에서는 암시적 용매로 시간을 줄일 수 있습니다. "
                          "암시적 용매로는 SMD와 엄브렐라 샘플링을 할 수 없고 물 다리도 분석할 수 없습니다.")
    else:
        o["solvent"] = _r("explicit", "顯式水能正確描述氫鍵網路與離子屏蔽，結合與穩定性分析一般都用它。",
                          "Explicit water describes hydrogen-bond networks and ionic screening. It is the standard choice "
                          "for binding and stability analysis.",
                          "陽溶媒の水は水素結合ネットワークとイオンによる遮蔽を正しく表せます。結合や安定性の解析では標準的な"
                          "選択です。",
                          "명시적 물은 수소 결합 네트워크와 이온 차폐를 제대로 나타냅니다. 결합과 안정성 분석에서는 표준 "
                          "선택입니다.")
    want_binding = f.binding or goal in ("binding", "publication")
    o["padding_nm"] = _r(2.0, "蛋白和自己的週期鏡像至少隔 2.0 nm（OpenMM 的 padding 是到鏡像的距離，只加一次；等同 GROMACS 的 -d 1.0），"
                            "遠大於 1.0 nm 截斷距離。要計算結合強度時，建模會依拉離路徑自動再加大。",
                         "The protein stays at least 2.0 nm from its own periodic image (in OpenMM the padding is the distance "
                         "to the image, added once; the same as GROMACS -d 1.0), well beyond the 1.0 nm cut-off. For binding "
                         "calculations the build enlarges the box further to fit the pulling path.",
                         "タンパク質と自分の周期イメージの間を 2.0 nm 以上空けます（OpenMM の余白はイメージまでの距離で、一度だけ"
                         "加わります。GROMACS の -d 1.0 と同じ）。カットオフ 1.0 nm より十分に大きく、結合の強さを計算するときは"
                         "引き離し経路に合わせて自動でさらに広げます。",
                         "단백질과 자기 주기 이미지 사이를 2.0 nm 이상 둡니다(OpenMM의 여백은 이미지까지의 거리이며 한 번만 "
                         "더해집니다. GROMACS의 -d 1.0과 같습니다). 1.0 nm 컷오프보다 충분히 크며, 결합 세기를 계산할 때는 "
                         "당김 경로에 맞춰 자동으로 더 넓힙니다.")
    o["box_for_smd"] = _r("always" if want_binding else "auto",
                          "要計算結合強度時，水盒一開始就依拉離路徑加大。沒有排時先檢查：加大很便宜就先加大，否則在 MD 前提醒，"
                          "免得 MD 跑完才發現不能做 SMD。",
                          "When binding strength is calculated, the box is sized for the pulling path from the start. Otherwise "
                          "the build checks anyway: it enlarges the box when that is cheap and warns before the MD when it is "
                          "not, so you do not find out after the MD that SMD is impossible.",
                          "結合の強さを計算するときは、最初から引き離し経路に合わせて水ボックスを広げます。予定がなくても確認し、"
                          "安く済むなら先に広げ、高くつくなら MD の前に知らせます。MD の後で SMD ができないと分かることを防ぎます。",
                          "결합 세기를 계산할 때는 처음부터 당김 경로에 맞춰 물 상자를 넓힙니다. 계획이 없어도 확인하여, 저렴하면 "
                          "미리 넓히고 비싸면 MD 전에 알립니다. MD가 끝난 뒤 SMD를 할 수 없다는 것을 알게 되는 일을 막습니다.")
    o["box_shape"] = _r("dodecahedron", "邊距相同時，菱形十二面體的水比立方體少約 29 %，跑得比較快。",
                        "A rhombic dodecahedron holds about 29 % less water than a cube with the same padding, so it runs faster.",
                        "余白が同じなら、菱形十二面体は立方体より水が約 29 % 少なく、計算が速くなります。",
                        "여백이 같으면 마름모 십이면체는 정육면체보다 물이 약 29 % 적어 더 빨리 계산됩니다.")
    o["ion_positive"] = _r("Na+", "生理食鹽水的條件。實驗緩衝液以鉀鹽為主時，例如模擬細胞內環境，改用 K+。",
                           "Physiological saline. Use K+ if the experimental buffer is potassium-based, for example "
                           "intracellular conditions.",
                           "生理食塩水の条件です。実験の緩衝液がカリウム塩主体の場合、たとえば細胞内環境を模擬するときは K+ にします。",
                           "생리 식염수 조건입니다. 세포 내 환경을 모사하는 경우처럼 실험 완충액이 칼륨염 위주라면 K+로 바꿉니다.")
    o["ion_negative"] = _r("Cl-", "與 Na+ 組成 NaCl，使用 Amber14 的 Joung-Cheatham 單價離子參數。",
                           "Together with Na+ this is NaCl, with the Joung-Cheatham monovalent ion parameters from Amber14.",
                           "Na+ と合わせて NaCl になります。Amber14 の Joung-Cheatham 一価イオンパラメータを使います。",
                           "Na+와 함께 NaCl이 됩니다. Amber14의 Joung-Cheatham 1가 이온 파라미터를 사용합니다.")
    o["ion_concentration_molar"] = _r(0.15, "0.15 M 對應生理離子強度。體外酵素試驗請改成實驗緩衝液的鹽濃度。",
                                      "0.15 M matches physiological ionic strength. For an in vitro enzyme assay, use the salt "
                                      "concentration of the assay buffer.",
                                      "0.15 M は生理的なイオン強度に相当します。in vitro の酵素試験では、試験に使う緩衝液の塩濃度に"
                                      "してください。",
                                      "0.15 M은 생리적 이온 세기에 해당합니다. 시험관 내 효소 시험에서는 실험 완충액의 염 농도로 "
                                      "바꾸십시오.")
    o["neutralize"] = _r(True, "PME 靜電計算需要系統淨電荷為零，否則會多出一個人為的均勻背景電荷。",
                         "PME electrostatics needs a neutral system. Otherwise an artificial uniform background charge is added.",
                         "PME の静電計算では系全体が電気的に中性である必要があります。そうでないと人為的な一様背景電荷が加わります。",
                         "PME 정전기 계산에는 계 전체가 중성이어야 합니다. 그렇지 않으면 인위적인 균일 배경 전하가 더해집니다.")
    # equilibration
    if rough_reasons:
        rz, re_, rj, rk = ("、".join(r[0] for r in rough_reasons), ", ".join(r[1] for r in rough_reasons),
                           "、".join(r[2] for r in rough_reasons), ", ".join(r[3] for r in rough_reasons))
        o["restraints"] = _r("gentle", f"起始結構比較粗糙（{rz}），所以約束全部保留到加熱結束，再用加倍長度的定壓平衡釋放。",
                             f"The starting structure is rough ({re_}). All restraints are held through heating and "
                             "released over an NPT stage of twice the length.",
                             f"出発構造が粗い（{rj}）ため、加熱が終わるまで拘束をすべて保持し、2倍の長さの NPT 平衡化で解除します。",
                             f"시작 구조가 거칠기 때문에({rk}) 가열이 끝날 때까지 모든 구속을 유지하고, 두 배 길이의 NPT "
                             "평형에서 해제합니다.")
    else:
        o["restraints"] = _r("standard", "高解析度晶體結構加上藥物大小的配體，主鏈與配體的約束在定壓平衡中逐步釋放即可。",
                             "With a high-resolution crystal structure and a drug-sized ligand, the backbone and ligand "
                             "restraints can be released step by step during NPT.",
                             "高分解能の結晶構造と薬物サイズのリガンドなら、主鎖とリガンドの拘束は NPT 平衡化の中で段階的に"
                             "解除すれば十分です。",
                             "고분해능 결정 구조와 약물 크기 리간드라면 주사슬과 리간드 구속은 NPT 평형 중에 단계적으로 해제하면 "
                             "됩니다.")
    o["minimize_iterations"] = _r(5000, "5 萬原子以內的系統，5000 步足以消除對接與加氫留下的碰撞。",
                                  "5000 steps remove the clashes left by docking and hydrogen placement in systems up to "
                                  "50,000 atoms.",
                                  "5 万原子までの系なら、5000 ステップでドッキングと水素付加による衝突を取り除けます。",
                                  "5만 원자 이하의 계라면 5000단계로 도킹과 수소 추가가 남긴 충돌을 없앨 수 있습니다.")
    o["minimize_tolerance"] = _r(10.0, "最大力低於 10 kJ mol⁻¹ nm⁻¹ 就可以開始升溫，更嚴格只會多花時間。",
                                 "A maximum force below 10 kJ mol⁻¹ nm⁻¹ is enough to start heating. A tighter value only "
                                 "costs time.",
                                 "最大力が 10 kJ mol⁻¹ nm⁻¹ を下回れば加熱を始められます。それより厳しくしても時間がかかるだけです。",
                                 "최대 힘이 10 kJ mol⁻¹ nm⁻¹ 아래면 가열을 시작해도 됩니다. 더 엄격하게 하면 시간만 더 듭니다.")
    o["heat_start_k"] = _r(50.0, "從 50 K 線性升溫，避免最小化後殘留的高能接觸在頭幾步就讓系統失穩。",
                           "Linear heating from 50 K keeps residual high-energy contacts from blowing up in the first steps.",
                           "50 K から直線的に昇温し、最小化後に残った高エネルギーの接触が最初の数ステップで系を不安定にしないように"
                           "します。",
                           "50 K부터 선형으로 승온하여 최소화 후 남은 고에너지 접촉이 처음 몇 단계에서 계를 불안정하게 만들지 "
                           "않도록 합니다.")
    nvt = float(t["nvt_ps"]) * (1.5 if f.bonded_metals else 1.0)
    bm = bool(f.bonded_metals)
    o["nvt_ps"] = _r(nvt, f"{tier} 等級的加熱長度。" + ("含金屬鍵結模型時再延長 50 %，讓配位幾何先穩定下來。" if bm else ""),
                     f"Heating length of the {tier} tier." + (" It is extended by 50 % for the bonded metal site so the "
                                                              "coordination geometry settles first." if bm else ""),
                     f"{tier} レベルの加熱時間です。" + ("結合モデルの金属部位があるため 50 % 延長し、配位構造を先に安定させます。"
                                                     if bm else ""),
                     f"{tier} 등급의 가열 시간입니다." + (" 결합 모델 금속 부위가 있어 50 % 늘려 배위 구조가 먼저 안정되게 "
                                                     "합니다." if bm else ""))
    npt = float(t["npt_ps"])
    big = bool(f.n_residues and f.n_residues > 600)
    if big:
        npt *= 1.5
    rough = bool(rough_reasons)
    o["npt_ps"] = _r(npt, f"{tier} 等級的定壓平衡長度。" + (f"蛋白有 {f.n_residues} 個殘基，密度收斂較慢，延長 50 %。" if big else "")
                     + ("溫和策略會自動再加倍。" if rough else ""),
                     f"NPT length of the {tier} tier." + (f" With {f.n_residues} residues the density converges more "
                                                          "slowly, so it is extended by 50 %." if big else "")
                     + (" The gentle strategy doubles it." if rough else ""),
                     f"{tier} レベルの NPT 平衡化の長さです。" + (f"タンパク質が {f.n_residues} 残基あり密度の収束が遅いため、"
                                                              "50 % 延長します。" if big else "")
                     + ("穏やかな解除方法ではさらに自動で2倍になります。" if rough else ""),
                     f"{tier} 등급의 NPT 평형 길이입니다." + (f" 단백질 잔기가 {f.n_residues}개라 밀도 수렴이 느려 50 % "
                                                         "늘립니다." if big else "")
                     + (" 완만 방식에서는 자동으로 두 배가 됩니다." if rough else ""))
    # production
    o["temperature_k"] = _r(300.0, "Amber 力場是在 300 K 參數化的，多數文獻也用 300 K。要對應體溫可以改成 310 K。",
                            "The Amber force fields were parameterised at 300 K and most literature uses it. Use 310 K to "
                            "match body temperature.",
                            "Amber 力場は 300 K でパラメータ化されており、多くの文献も 300 K を使っています。体温に合わせるなら "
                            "310 K にします。",
                            "Amber 역장은 300 K에서 파라미터화되었고 대부분의 문헌도 300 K를 씁니다. 체온에 맞추려면 310 K로 "
                            "바꿉니다.")
    o["pressure_bar"] = _r(1.0, "常壓。", "Ambient pressure.", "常圧です。", "상압입니다.")
    o["friction_per_ps"] = _r(1.0, "Langevin 摩擦 1 ps⁻¹ 足以控溫，也不會明顯拖慢構形變化。",
                              "A Langevin friction of 1 ps⁻¹ controls temperature without noticeably slowing conformational dynamics.",
                              "Langevin 摩擦 1 ps⁻¹ で温度を十分に制御でき、構造変化もほとんど遅くなりません。",
                              "Langevin 마찰 1 ps⁻¹이면 온도를 충분히 제어하면서 구조 변화도 크게 늦추지 않습니다.")
    if f.bonded_metals and t["dt"] > 2:
        o["timestep_fs"] = _r(2.0, "含金屬鍵結模型時，金屬與配位原子之間的鍵很硬、振動快，4 fs 有失穩風險，所以改用 2 fs。",
                              "With a bonded metal site the metal-ligand bonds are stiff and vibrate fast. 4 fs risks "
                              "instability, so 2 fs is used.",
                              "結合モデルの金属部位では金属と配位原子の結合が硬く、振動が速いため、4 fs では不安定になるおそれが"
                              "あります。そのため 2 fs を使います。",
                              "결합 모델 금속 부위에서는 금속과 배위 원자 사이 결합이 단단하고 진동이 빨라 4 fs에서는 불안정해질 "
                              "수 있습니다. 그래서 2 fs를 씁니다.")
    elif t["hmr"]:
        o["timestep_fs"] = _r(float(t["dt"]), "氫質量重分配讓 4 fs 步長保持穩定，速度約是 2 fs 的兩倍。",
                              "Hydrogen mass repartitioning keeps a 4 fs step stable, about twice as fast as 2 fs.",
                              "水素質量再分配により 4 fs の時間刻みでも安定し、速度は 2 fs のおよそ2倍です。",
                              "수소 질량 재분배 덕분에 4 fs 시간 간격도 안정적이며 속도는 2 fs의 약 두 배입니다.")
    else:
        o["timestep_fs"] = _r(float(t["dt"]), "研究等級不做氫質量重分配，用 2 fs 保留原本的動力學。",
                              "The research tier does not repartition hydrogen mass and keeps the original dynamics at 2 fs.",
                              "研究レベルでは水素質量再分配を行わず、2 fs で本来の動力学を保ちます。",
                              "연구 등급은 수소 질량 재분배를 하지 않고 2 fs로 원래 동역학을 유지합니다.")
    prod = float(t["prod_ps"]) / 1000.0
    pwhy = (f"{tier} 等級的預設長度。", f"Default length of the {tier} tier.", f"{tier} レベルの既定の長さです。",
            f"{tier} 등급의 기본 길이입니다.")
    if pep and tier == "teaching":
        prod, pwhy = 20.0, ("胜肽構形鬆弛比小分子慢，教學等級延長到 20 ns。",
                            "Peptides relax more slowly than small molecules, so the teaching tier is extended to 20 ns.",
                            "ペプチドは低分子より構造の緩和が遅いため、教育レベルでは 20 ns に延長します。",
                            "펩타이드는 저분자보다 구조 이완이 느려 교육 등급에서 20 ns로 늘립니다.")
    elif multi_sim and tier == "teaching":
        prod, pwhy = 20.0, ("口袋裡同時有多個配體，要跑久一點才看得出有沒有配體離開。",
                            "With several ligands in the pocket, a longer run is needed to see whether any of them leaves.",
                            "ポケットに複数のリガンドがあるため、どれかが離れるかを見るには長めの計算が必要です。",
                            "포켓에 여러 리간드가 함께 있으므로 그중 하나가 떠나는지 보려면 더 긴 계산이 필요합니다.")
    o["production_ns"] = _r(prod, *pwhy)
    reps = 3 if goal == "publication" else 1
    o["replicas"] = _r(reps, *(("發表等級至少要用不同初速做 3 次獨立重複，才能報告標準差。",
                               "Publication grade needs at least three independent replicas with different initial velocities.",
                               "論文発表レベルでは、初速度を変えた独立な繰り返しを少なくとも 3 回行い、標準偏差を報告します。",
                               "논문 발표 수준에서는 초기 속도를 달리한 독립 반복을 최소 3회 해야 표준편차를 보고할 수 있습니다.")
                              if reps == 3 else ("跑一次可以看趨勢，要下結論請增加到 3 次。",
                                                 "One run shows a trend. Use three for a conclusion.",
                                                 "1 回の計算で傾向はわかります。結論を出すには 3 回にしてください。",
                                                 "한 번 계산하면 경향은 볼 수 있습니다. 결론을 내려면 3회로 늘리십시오.")))
    o["trajectory_interval_ps"] = _r(20.0 if prod < 50 else 50.0,
                                     "每 20 到 50 ps 存一幀，夠做 RMSD、RMSF 與接觸頻率分析，檔案也不會太大。",
                                     "One frame every 20 to 50 ps is enough for RMSD, RMSF and contact frequencies, and the "
                                     "file stays a manageable size.",
                                     "20 から 50 ps ごとに 1 フレーム保存すれば、RMSD、RMSF、接触頻度の解析に十分で、ファイルも"
                                     "大きくなりすぎません。",
                                     "20에서 50 ps마다 한 프레임을 저장하면 RMSD, RMSF, 접촉 빈도 분석에 충분하고 파일 크기도 "
                                     "적당합니다.")
    # binding
    o["binding"] = _r(bool(want_binding), *(("目標是結合強度。SMD 產生解離路徑，傘狀採樣再沿這條路徑計算自由能剖面。",
                                             "The goal is binding strength. SMD generates a dissociation path, and umbrella "
                                             "sampling computes the free-energy profile along it.",
                                             "目的は結合の強さです。SMD で解離経路を作り、アンブレラサンプリングでその経路に沿った"
                                             "自由エネルギープロファイルを計算します。",
                                             "목표는 결합 세기입니다. SMD로 해리 경로를 만들고, 엄브렐라 샘플링으로 그 경로를 "
                                             "따라 자유 에너지 프로파일을 계산합니다.") if want_binding else
                                            ("這個目標不需要自由能。打開會讓計算時間增加好幾倍。",
                                             "This goal does not need a free energy. Turning it on multiplies the computing time.",
                                             "この目的では自由エネルギーは必要ありません。オンにすると計算時間が数倍になります。",
                                             "이 목표에는 자유 에너지가 필요 없습니다. 켜면 계산 시간이 몇 배로 늘어납니다.")))
    o["pull_distance_nm"] = _r(2.0 if pep else 1.5, *(("胜肽比較長，要拉得更遠才能完全離開蛋白表面。",
                                                       "A peptide is longer and has to be pulled further to leave the protein surface.",
                                                       "ペプチドは長いため、タンパク質表面から完全に離すにはさらに遠くまで引き離す"
                                                       "必要があります。",
                                                       "펩타이드는 길어서 단백질 표면에서 완전히 떨어지려면 더 멀리 당겨야 합니다.")
                                                      if pep else
                                                      ("1.5 nm 可以讓配體完全離開口袋，剖面末端應該趨於平坦。",
                                                       "1.5 nm takes the ligand fully out of the pocket. The profile should "
                                                       "flatten at the end.",
                                                       "1.5 nm でリガンドはポケットから完全に出ます。プロファイルの末端は平らになるはずです。",
                                                       "1.5 nm면 리간드가 포켓을 완전히 벗어납니다. 프로파일 끝은 평평해져야 합니다.")))
    # D-63: 0.005 for every goal.  At 0.01 nm/ps the 3PTB pull did ~355 kJ/mol of work against a ~100 kJ/mol free-energy
    # change (~100 kT dissipated), so the window starting structures carried a disturbed pocket; SMD is a small part of
    # the cost (1.5 nm at 0.005 nm/ps = 300 ps against tens of ns of windows).
    o["pull_velocity_nm_per_ps"] = _r(0.005, "用 0.005 nm ps⁻¹。拉得太快時，大部分的功會變成耗散，窗口起點會帶著被擾動的口袋。"
                                             "SMD 只占總時間的一小部分，放慢的代價很小。自由能仍由傘狀採樣決定。",
                                      "0.005 nm ps⁻¹ is used. A faster pull turns most of the work into dissipation, and the "
                                      "window starting points then carry a disturbed pocket. SMD is a small part of the total "
                                      "time, so slowing it costs little. The free energy still comes from umbrella sampling.",
                                      "0.005 nm ps⁻¹ を使います。速く引きすぎると仕事の大半が散逸になり、ウィンドウの出発点が乱れた"
                                      "ポケットを抱えたままになります。SMD は全体の計算時間のごく一部なので、遅くしても負担はわずか"
                                      "です。自由エネルギーは引き続きアンブレラサンプリングで決まります。",
                                      "0.005 nm ps⁻¹을 씁니다. 너무 빨리 당기면 일의 대부분이 소산되고, 윈도우 시작점이 교란된 "
                                      "포켓을 그대로 가져갑니다. SMD는 전체 시간의 작은 부분이라 느리게 해도 부담이 적습니다. "
                                      "자유 에너지는 여전히 엄브렐라 샘플링으로 정해집니다.")
    o["k_pull"] = _r(1000.0, "1000 kJ mol⁻¹ nm⁻² 讓配體跟得上彈簧，又不會太硬。",
                     "1000 kJ mol⁻¹ nm⁻² makes the ligand follow the spring without being too stiff.",
                     "1000 kJ mol⁻¹ nm⁻² ならリガンドがばねに追従し、硬すぎることもありません。",
                     "1000 kJ mol⁻¹ nm⁻²면 리간드가 스프링을 따라가면서도 너무 단단하지 않습니다.")
    o["k_umbrella"] = _r(1000.0, "窗口間距 0.05 到 0.1 nm 時，1000 就有足夠的重疊。剖面陡峭的區段系統會自動加硬。",
                         "With 0.05 to 0.1 nm window spacing, 1000 gives enough overlap. Steep stretches are stiffened "
                         "automatically.",
                         "ウィンドウ間隔が 0.05 から 0.1 nm なら、1000 で十分な重なりが得られます。急な区間は自動で硬くします。",
                         "윈도우 간격이 0.05에서 0.1 nm면 1000으로 충분히 겹칩니다. 가파른 구간은 자동으로 더 단단하게 합니다.")
    wprod = {"classroom": 50.0, "teaching": 500.0, "research": 2000.0}[tier]
    o["window_prod_ps"] = {"classroom": _r(wprod, "課堂等級只看剖面趨勢，不輸出 ΔG°。",
                                           "The classroom tier shows the profile trend only. No ΔG° is reported.",
                                           "授業レベルではプロファイルの傾向だけを見ます。ΔG° は出力しません。",
                                           "수업 등급은 프로파일 경향만 봅니다. ΔG°는 출력하지 않습니다."),
                           "teaching": _r(wprod, "教學等級要輸出 ΔG°，每個窗口至少 500 ps。",
                                          "To report ΔG° at the teaching tier, each window needs at least 500 ps.",
                                          "教育レベルで ΔG° を出すには、各ウィンドウに少なくとも 500 ps 必要です。",
                                          "교육 등급에서 ΔG°를 출력하려면 윈도우마다 최소 500 ps가 필요합니다."),
                           "research": _r(wprod, "研究等級每個窗口 2 ns，並比對前後半段是否一致來檢查收斂。",
                                          "The research tier uses 2 ns per window and checks convergence by comparing the "
                                          "first and second halves.",
                                          "研究レベルではウィンドウごとに 2 ns とし、前半と後半が一致するかで収束を確認します。",
                                          "연구 등급은 윈도우마다 2 ns로 하고, 전반부와 후반부가 일치하는지로 수렴을 확인합니다.")}[tier]
    o["window_equil_ps"] = _r(max(10.0, wprod / 10.0), "每個窗口先丟掉約 10 %，讓配體在新位置鬆弛。",
                              "About 10 % of each window is discarded while the ligand relaxes at its new position.",
                              "各ウィンドウの最初の約 10 % は、リガンドが新しい位置で緩和する間として捨てます。",
                              "각 윈도우의 처음 약 10 %는 리간드가 새 위치에서 이완되는 동안이므로 버립니다.")
    o["target_overlap"] = _r(0.2, "相鄰窗口的分佈重疊至少要 0.2，MBAR 才能可靠地接起整條剖面。",
                             "Neighbouring windows must overlap by at least 0.2 for MBAR to join the profile reliably.",
                             "隣接ウィンドウの分布の重なりが 0.2 以上あれば、MBAR でプロファイル全体を確実につなげます。",
                             "인접 윈도우의 분포가 최소 0.2 겹쳐야 MBAR가 프로파일 전체를 신뢰성 있게 이을 수 있습니다.")
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
def _i(level, key, zh, en, ja, ko, suggestion=None) -> dict:
    return {"level": level, "key": key, "text": (zh, en, ja, ko), "suggestion": suggestion}


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
        out.append(_i("error", "timestep_fs", f"步長 {dt:g} fs 超過 4 fs。即使用了氫質量重分配，含氫鍵的振動也會讓積分發散。",
                      f"A {dt:g} fs step is over 4 fs. Even with hydrogen mass repartitioning, the bonds to hydrogen make "
                      "the integration diverge.",
                      f"時間刻み {dt:g} fs は 4 fs を超えています。水素質量再分配を使っても、水素を含む結合の振動で積分が発散します。",
                      f"시간 간격 {dt:g} fs는 4 fs를 넘습니다. 수소 질량 재분배를 써도 수소가 포함된 결합의 진동 때문에 "
                      "적분이 발산합니다.",
                      4.0 if hmr else 2.0))
    elif dt > 2.0 and not hmr:
        out.append(_i("error", "timestep_fs", f"{tier} 等級不做氫質量重分配，{dt:g} fs 會讓含氫的鍵振動失穩。",
                      f"The {tier} tier does not repartition hydrogen mass, so {dt:g} fs makes bonds to hydrogen unstable.",
                      f"{tier} レベルでは水素質量再分配を行わないため、{dt:g} fs では水素を含む結合が不安定になります。",
                      f"{tier} 등급은 수소 질량 재분배를 하지 않으므로 {dt:g} fs에서는 수소가 포함된 결합이 불안정해집니다.",
                      2.0))
    elif dt > 2.0 and f.bonded_metals:
        out.append(_i("warning", "timestep_fs", "含金屬鍵結模型時，金屬與配位原子之間的鍵振動快，4 fs 有失穩風險。",
                      "With a bonded metal site, 4 fs risks instability because metal-ligand bonds vibrate fast.",
                      "結合モデルの金属部位では金属と配位原子の結合の振動が速く、4 fs では不安定になるおそれがあります。",
                      "결합 모델 금속 부위에서는 금속과 배위 원자 사이 결합의 진동이 빨라 4 fs에서는 불안정해질 수 있습니다.",
                      2.0))
    T = float(v["temperature_k"])
    if T < 273 or T > 373:
        out.append(_i("error", "temperature_k", f"{T:g} K 不在液態水的範圍內，TIP3P 水模型與 Amber 力場在這個溫度沒有意義。",
                      f"{T:g} K is outside the liquid range of water. TIP3P and the Amber force field mean nothing there.",
                      f"{T:g} K は液体の水の範囲外です。この温度では TIP3P 水モデルと Amber 力場に意味がありません。",
                      f"{T:g} K는 액체 물의 범위를 벗어납니다. 이 온도에서는 TIP3P 물 모델과 Amber 역장이 의미가 없습니다.",
                      300.0))
    elif T > 330:
        out.append(_i("warning", "temperature_k", f"{T:g} K 明顯高於生理溫度，可能讓蛋白局部變性。除非你本來就要做高溫模擬。",
                      f"{T:g} K is well above physiological temperature and may partly unfold the protein. Use it only "
                      "if you intend a high-temperature run.",
                      f"{T:g} K は生理的な温度よりかなり高く、タンパク質が部分的に変性するおそれがあります。高温シミュレーションを"
                      "意図している場合だけ使ってください。",
                      f"{T:g} K는 생리적 온도보다 훨씬 높아 단백질이 부분적으로 변성될 수 있습니다. 고온 시뮬레이션이 목적일 "
                      "때만 쓰십시오.",
                      310.0))
    if float(v["heat_start_k"]) >= T:
        out.append(_i("error", "heat_start_k", "加熱起始溫度不低於目標溫度，等於沒有升溫。",
                      "The heating start temperature is not below the target, so there is no heating.",
                      "加熱の開始温度が目標温度より低くないため、昇温になっていません。",
                      "가열 시작 온도가 목표 온도보다 낮지 않아 승온이 일어나지 않습니다.", 50.0))
    if float(v["nvt_ps"]) < 50:
        out.append(_i("warning", "nvt_ps", f"加熱只有 {float(v['nvt_ps']):g} ps，溫度可能還沒穩定就進入定壓平衡。",
                      f"Only {float(v['nvt_ps']):g} ps of heating. The temperature may not be stable before NPT starts.",
                      f"加熱が {float(v['nvt_ps']):g} ps しかありません。温度が安定する前に NPT 平衡化に入るおそれがあります。",
                      f"가열이 {float(v['nvt_ps']):g} ps뿐입니다. 온도가 안정되기 전에 NPT 평형으로 넘어갈 수 있습니다.",
                      rec["nvt_ps"]))
    if explicit and float(v["npt_ps"]) < 100:
        out.append(_i("warning", "npt_ps", f"定壓平衡只有 {float(v['npt_ps']):g} ps，水盒密度還沒收斂。",
                      f"Only {float(v['npt_ps']):g} ps of NPT. The box density has not converged.",
                      f"NPT 平衡化が {float(v['npt_ps']):g} ps しかなく、水ボックスの密度が収束していません。",
                      f"NPT 평형이 {float(v['npt_ps']):g} ps뿐이라 물 상자 밀도가 수렴하지 않았습니다.", rec["npt_ps"]))
    if (pep or f.bonded_metals or f.structure_source == "model" or f.has_gaps) and v["restraints"] == "standard":
        out.append(_i("warning", "restraints", "起始結構比較粗糙（胜肽、金屬、預測模型或補建的缺口），標準釋放可能讓結構在升溫時變形。",
                      "The starting structure is rough (peptide, metal, predicted model or rebuilt gaps). The standard "
                      "release may distort it during heating.",
                      "出発構造が粗い（ペプチド、金属、予測モデル、補完した欠損のいずれか）ため、標準の解除では昇温中に構造が"
                      "崩れるおそれがあります。",
                      "시작 구조가 거칠어서(펩타이드, 금속, 예측 모델 또는 보완한 결손) 표준 해제 방식에서는 승온 중 구조가 "
                      "변형될 수 있습니다.", "gentle"))
    if v["restraints"] == "hold_backbone":
        out.append(_i("info", "restraints", "正式模擬仍保留主鏈約束，RMSD 與 RMSF 會被壓低，報告會把它們標為受約束的數值。",
                      "The backbone stays restrained in production. RMSD and RMSF are suppressed, and the report labels "
                      "them as restrained values.",
                      "本計算でも主鎖の拘束が残ります。RMSD と RMSF は小さく出るため、レポートでは拘束下の値として表示します。",
                      "본 계산에서도 주사슬 구속이 남습니다. RMSD와 RMSF가 낮게 나오므로 보고서에는 구속된 값으로 표시합니다."))
    adv = restraint_advice(f, goal, v, lang)                     # D-118: advice beyond what the rules above cover
    if adv["status"] == "advice":
        order = ("zh", "en", "ja", "ko")
        if adv["strategy"] != v["restraints"] and v["restraints"] in ("standard", "gentle") \
                and not any(i["key"] == "restraints" for i in out):
            out.append(_i("info", "restraints", *[adv["summary_all"][k] for k in order], adv["strategy"]))
        for it in adv["items"]:
            if it["role"] == "caution":
                out.append(_i("warning", "restraints", *[it["text_all"][k] for k in order], adv["strategy"]))
    prod = float(v["production_ns"])
    if prod < 1:
        out.append(_i("warning", "production_ns", f"正式模擬 {prod:g} ns 只能檢查流程能不能跑，不足以判斷複合物穩定性。",
                      f"{prod:g} ns of production only checks that the workflow runs. It cannot judge complex stability.",
                      f"本計算 {prod:g} ns ではワークフローが動くかを確認できるだけで、複合体の安定性は判断できません。",
                      f"본 계산 {prod:g} ns로는 워크플로가 돌아가는지만 확인할 수 있고 복합체 안정성은 판단할 수 없습니다.",
                      rec["production_ns"]))
    elif goal == "publication" and prod < 50:
        out.append(_i("warning", "production_ns", f"發表等級通常需要 50 ns 以上，{prod:g} ns 在審稿時容易被質疑。",
                      f"Publication usually needs 50 ns or more. Reviewers are likely to question {prod:g} ns.",
                      f"論文発表には通常 50 ns 以上が必要です。{prod:g} ns では査読で指摘されやすくなります。",
                      f"논문 발표에는 보통 50 ns 이상이 필요합니다. {prod:g} ns는 심사에서 지적받기 쉽습니다.", 100.0))
    if prod > 100:
        # long runs (engine/longrun.py): days, disk and the save interval the run will use; > 1 µs needs a confirmation
        lp = long_run_plan(v, f)
        line = lp["summary"]
        if prod > 10000:
            out.append(_i("error", "production_ns", f"正式模擬上限是 10000 ns（10 µs）。{line[0]}",
                          f"The production limit is 10000 ns (10 µs). {line[1]}",
                          f"本計算の上限は 10000 ns（10 µs）です。{line[2]}",
                          f"본 계산 상한은 10000 ns(10 µs)입니다. {line[3]}", 10000.0))
        elif prod > 1000:
            out.append(_i("warning", "production_ns", f"超過 1 µs，開始前會請你確認。{line[0]}",
                          f"Longer than 1 µs, so you will be asked to confirm before it starts. {line[1]}",
                          f"1 µs を超えるため、開始前に確認を求めます。{line[2]}",
                          f"1 µs를 넘으므로 시작 전에 확인을 요청합니다. {line[3]}"))
        else:
            out.append(_i("info", "production_ns", f"長時間模擬。{line[0]}", f"Long simulation. {line[1]}",
                          f"長時間シミュレーションです。{line[2]}", f"장시간 시뮬레이션입니다. {line[3]}"))
    if goal == "publication" and int(v["replicas"]) < 3:
        out.append(_i("warning", "replicas", "只跑一次無法報告標準差。發表等級建議至少 3 次獨立重複。",
                      "A single run gives no standard deviation. Publication grade needs at least three replicas.",
                      "1 回だけでは標準偏差を報告できません。論文発表レベルでは独立した繰り返しを少なくとも 3 回行ってください。",
                      "한 번만 계산하면 표준편차를 보고할 수 없습니다. 논문 발표 수준에서는 최소 3회 독립 반복을 권합니다.", 3))
    fr = float(v["friction_per_ps"])
    if fr < 0.1 or fr > 10:
        out.append(_i("warning", "friction_per_ps", f"摩擦係數 {fr:g} ps⁻¹ 不在常用範圍（0.1 到 5）內，會扭曲擴散與構形動態。",
                      f"A friction of {fr:g} ps⁻¹ is outside the usual range of 0.1 to 5 and distorts diffusion and dynamics.",
                      f"摩擦係数 {fr:g} ps⁻¹ は通常の範囲（0.1 から 5）を外れており、拡散と構造の動きがゆがみます。",
                      f"마찰 계수 {fr:g} ps⁻¹은 일반 범위(0.1에서 5)를 벗어나 확산과 구조 동역학이 왜곡됩니다.", 1.0))
    if abs(float(v["pressure_bar"]) - 1.0) > 0.5:
        out.append(_i("info", "pressure_bar", "壓力不是常壓，請確認這是刻意設定的，例如高壓實驗。",
                      "The pressure is not ambient. Check that this is intended, for example a high-pressure experiment.",
                      "常圧ではありません。高圧実験など、意図した設定か確認してください。",
                      "상압이 아닙니다. 고압 실험처럼 의도한 설정인지 확인하십시오."))
    c = float(v["ion_concentration_molar"])
    if c < 0:
        out.append(_i("error", "ion_concentration_molar", "鹽濃度不能是負的。", "The salt concentration cannot be negative.",
                      "塩濃度は負にできません。", "염 농도는 음수일 수 없습니다.", 0.15))
    elif c > 1.0:
        out.append(_i("warning", "ion_concentration_molar", f"{c:g} M 遠超過生理範圍，單價離子參數在這麼高的濃度下可能析出結晶。",
                      f"{c:g} M is far above physiological. Monovalent ion parameters may crystallise at this concentration.",
                      f"{c:g} M は生理的な範囲を大きく超えています。この濃度では一価イオンのパラメータで結晶が析出するおそれがあります。",
                      f"{c:g} M은 생리적 범위를 크게 넘습니다. 이 농도에서는 1가 이온 파라미터로 결정이 석출될 수 있습니다.",
                      0.15))
    if not v["neutralize"] and explicit:
        out.append(_i("warning", "neutralize", "不中和淨電荷時，PME 會加上均勻背景電荷，帶電配體的結合能會因此偏差。",
                      "Without neutralisation, PME adds a uniform background charge that biases the binding of charged ligands.",
                      "正味電荷を中和しないと、PME が一様な背景電荷を加えるため、電荷を持つリガンドの結合エネルギーに偏りが出ます。",
                      "알짜 전하를 중화하지 않으면 PME가 균일 배경 전하를 더해 전하를 띤 리간드의 결합 에너지가 치우칩니다.", True))
    pad = float(v["padding_nm"])
    if explicit and pad < 1.0:
        out.append(_i("error", "padding_nm", f"邊距 {pad:g} nm 小於截斷距離 1.0 nm：OpenMM 的邊距是蛋白到自己鏡像的距離，蛋白會直接和鏡像作用。",
                      f"A padding of {pad:g} nm is below the 1.0 nm cut-off: in OpenMM the padding is the distance from the "
                      "protein to its own image, so the protein interacts with its image.",
                      f"余白 {pad:g} nm はカットオフ 1.0 nm 未満です。OpenMM の余白はタンパク質から自分のイメージまでの距離なので、"
                      "タンパク質がイメージと直接相互作用します。",
                      f"여백 {pad:g} nm는 컷오프 1.0 nm보다 작습니다. OpenMM의 여백은 단백질에서 자기 이미지까지의 거리라서 "
                      "단백질이 이미지와 직접 상호작용합니다.", 2.0))
    elif explicit and pad < 2.0:
        out.append(_i("warning", "padding_nm", f"邊距 {pad:g} nm 低於預設 2.0 nm：蛋白與鏡像之間只有 {pad:g} nm，構形改變時可能靠近截斷距離。",
                      f"A padding of {pad:g} nm is below the default 2.0 nm: only {pad:g} nm separates the protein from its "
                      "image, which a conformational change can bring close to the cut-off.",
                      f"余白 {pad:g} nm は既定の 2.0 nm 未満です。タンパク質とイメージの間は {pad:g} nm しかなく、構造変化で"
                      "カットオフに近づくことがあります。",
                      f"여백 {pad:g} nm는 기본값 2.0 nm보다 작습니다. 단백질과 이미지 사이가 {pad:g} nm뿐이라 구조가 바뀌면 "
                      "컷오프에 가까워질 수 있습니다.", 2.0))
    if v["binding"] and explicit:
        out.append(_i("info", "padding_nm", "結合強度計算：建模時會依拉離路徑、配體大小與安全距離自動加大水盒（box size for SMD）。",
                      "Binding calculation: the build enlarges the box to fit the pulling path, the ligand size and the safety "
                      "margin (box size for SMD).",
                      "結合の強さの計算：モデル構築時に、引き離し経路・リガンドの大きさ・安全距離に合わせて水ボックスを自動で"
                      "広げます（box size for SMD）。",
                      "결합 세기 계산: 모델 구축 때 당김 경로, 리간드 크기, 안전 거리에 맞춰 물 상자를 자동으로 넓힙니다"
                      "(box size for SMD).", None))
    if v["binding"] and not explicit:
        out.append(_i("error", "solvent", "隱式溶劑沒有週期性水盒，不能做 SMD 與傘狀採樣。",
                      "Implicit solvent has no periodic box, so SMD and umbrella sampling are not possible.",
                      "陰溶媒には周期的な水ボックスがないため、SMD とアンブレラサンプリングはできません。",
                      "암시적 용매에는 주기적 물 상자가 없어 SMD와 엄브렐라 샘플링을 할 수 없습니다.", "explicit"))
    exh = int(v["exhaustiveness"])
    if exh < 8:
        out.append(_i("warning", "exhaustiveness", f"搜尋強度 {exh} 太低，重複對接時每次結果可能不同。",
                      f"An exhaustiveness of {exh} is too low. Repeated docking may give different answers.",
                      f"探索の徹底度 {exh} は低すぎます。ドッキングを繰り返すたびに結果が変わるおそれがあります。",
                      f"탐색 강도 {exh}는 너무 낮습니다. 도킹을 반복할 때마다 결과가 달라질 수 있습니다.", rec["exhaustiveness"]))
    elif pep and exh < 32:
        out.append(_i("info", "exhaustiveness", "胜肽配體，系統會自動提高到 32。", "Peptide ligand, so it is raised to 32 automatically.",
                      "ペプチドのリガンドなので、自動で 32 に上げます。", "펩타이드 리간드이므로 자동으로 32로 올립니다.", 32))
    if f.box_size and max(f.box_size) > 40:
        edge = f"{max(f.box_size):.0f}"
        out.append(_i("warning", "exhaustiveness", f"搜尋區最長邊 {edge} Å，超過 40 Å，等於盲對接。建議用共結晶配體或活性位殘基來定義搜尋區。",
                      f"The longest box edge is {edge} Å, over 40 Å, which is effectively blind docking. Define the box "
                      "from a co-crystal ligand or from active-site residues.",
                      f"探索領域の最長辺が {edge} Å で 40 Å を超えており、実質的にブラインドドッキングです。共結晶リガンドか"
                      "活性部位の残基から探索領域を決めてください。",
                      f"탐색 영역의 가장 긴 변이 {edge} Å로 40 Å를 넘어 사실상 블라인드 도킹입니다. 공결정 리간드나 활성 "
                      "부위 잔기로 탐색 영역을 정하십시오."))
    if v["binding"]:
        vel = float(v["pull_velocity_nm_per_ps"])
        if vel > 0.02:
            out.append(_i("warning", "pull_velocity_nm_per_ps", f"拉速 {vel:g} nm ps⁻¹ 太快，彈簧振盪會讓窗口起點偏掉。",
                          f"{vel:g} nm ps⁻¹ is too fast. Spring ringing displaces the window starting points.",
                          f"引き離し速度 {vel:g} nm ps⁻¹ は速すぎます。ばねの振動でウィンドウの出発点がずれます。",
                          f"당김 속도 {vel:g} nm ps⁻¹은 너무 빠릅니다. 스프링 진동 때문에 윈도우 시작점이 어긋납니다.", 0.01))
        elif vel < 0.0005:
            out.append(_i("info", "pull_velocity_nm_per_ps", "拉速很慢，SMD 會很長。自由能仍由傘狀採樣決定，通常不需要這麼慢。",
                          "A very slow pull makes SMD long, while the free energy still comes from umbrella sampling. It "
                          "rarely needs to be this slow.",
                          "引き離しがとても遅く、SMD が長くなります。自由エネルギーはアンブレラサンプリングで決まるので、通常ここまで"
                          "遅くする必要はありません。",
                          "당김 속도가 매우 느려 SMD가 길어집니다. 자유 에너지는 엄브렐라 샘플링으로 정해지므로 보통 이렇게 "
                          "느릴 필요는 없습니다."))
        ku = float(v["k_umbrella"])
        if ku < 300 or ku > 5000:
            out.append(_i("warning", "k_umbrella", f"彈簧常數 {ku:g} 不在常用範圍（300 到 5000）內。太軟時窗口重疊過多，太硬則重疊不足。",
                          f"A spring constant of {ku:g} is outside the usual 300 to 5000. Too soft over-broadens the "
                          "windows, too stiff loses overlap.",
                          f"ばね定数 {ku:g} は通常の範囲（300 から 5000）を外れています。柔らかすぎるとウィンドウが重なりすぎ、"
                          "硬すぎると重なりが足りなくなります。",
                          f"스프링 상수 {ku:g}는 일반 범위(300에서 5000)를 벗어납니다. 너무 무르면 윈도우가 지나치게 겹치고, "
                          "너무 단단하면 겹침이 부족합니다.", 1000.0))
        wp = float(v["window_prod_ps"])
        if wp < 20:
            out.append(_i("warning", "window_prod_ps", f"每個窗口只取樣 {wp:g} ps，分佈還沒收斂。",
                          f"Only {wp:g} ps per window. The distributions have not converged.",
                          f"ウィンドウごとのサンプリングが {wp:g} ps しかなく、分布が収束していません。",
                          f"윈도우당 샘플링이 {wp:g} ps뿐이라 분포가 수렴하지 않았습니다.", rec["window_prod_ps"]))
        need = {"teaching": 500.0, "research": 2000.0}.get(tier)
        if need and wp < need:
            out.append(_i("info", "window_prod_ps", f"{tier} 等級要輸出 ΔG°，每個窗口至少要 {need:g} ps。目前的長度只會輸出自由能剖面。",
                          f"The {tier} tier reports ΔG° only with at least {need:g} ps per window. This length gives the "
                          "profile only.",
                          f"{tier} レベルで ΔG° を出すには、ウィンドウごとに少なくとも {need:g} ps 必要です。今の長さでは"
                          "自由エネルギープロファイルだけを出力します。",
                          f"{tier} 등급에서 ΔG°를 출력하려면 윈도우마다 최소 {need:g} ps가 필요합니다. 지금 길이로는 자유 에너지 "
                          "프로파일만 출력합니다.", need))
        if float(v["window_equil_ps"]) >= wp:
            out.append(_i("error", "window_equil_ps", "窗口平衡時間不短於取樣時間，等於沒有可用的樣本。",
                          "Window equilibration is not shorter than sampling, which leaves no usable samples.",
                          "ウィンドウの平衡化時間がサンプリング時間より短くないため、使えるサンプルが残りません。",
                          "윈도우 평형 시간이 샘플링 시간보다 짧지 않아 쓸 수 있는 샘플이 남지 않습니다.", max(10.0, wp / 10)))
    if budget_hours:
        est = estimate_hours(v, f)
        if est.get("total_hours") and est["total_hours"] > budget_hours:
            h = est["total_hours"]
            out.append(_i("warning", "production_ns", f"估計約需 {h:.1f} 小時，超過可用時間 {budget_hours:g} 小時。",
                          f"The estimate is about {h:.1f} h, more than the {budget_hours:g} h available.",
                          f"見積もりは約 {h:.1f} 時間で、使える時間 {budget_hours:g} 時間を超えています。",
                          f"예상 시간은 약 {h:.1f}시간으로, 사용할 수 있는 {budget_hours:g}시간을 넘습니다."))
    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda i: order[i["level"]])
    return [{"level": i["level"], "key": i["key"], "label": param_label(i["key"], lang), "message": tx(i["text"], lang),
             "suggestion": i["suggestion"]} for i in out]


# ----------------------------------------------------------------------------------- cost
def system_atoms(f: CaseFeatures, padding_nm: float = 2.0, solvent: str = "explicit") -> int:
    """Rough atom count of the solvated system (protein with hydrogens, water, ions)."""
    n = f.n_residues or 300
    protein = n * 16
    if solvent == "gbn2":
        return protein
    r_nm = 0.1 * 1.29 * 2.2 * n ** 0.38          # sphere radius ≈ 1.29·Rg, Rg ≈ 2.2·N^0.38 Å
    edge = 2 * r_nm + padding_nm                   # OpenMM: box width = 2R + padding (padding added once; D-99)
    vol = 0.707 * edge ** 3                        # rhombic dodecahedron ≈ 0.707 a³
    water = max(0.0, vol - n * 0.135) * 33.4 * 3   # 33.4 waters nm⁻³, protein ≈ 0.135 nm³ per residue
    return int(protein + water)


def estimate_hours(values: dict, f: CaseFeatures, goal: str = "teaching") -> dict:
    """Wall-clock estimate from the measured benchmark, scaled by atom count and time step."""
    if not f.ns_per_day:
        return {"total_hours": None, "note": ("這台電腦還沒做效能測試，無法估計時間。",
                                              "No benchmark has been run on this computer yet, so time cannot be estimated.",
                                              "このコンピュータではまだベンチマークを実行していないため、時間を見積もれません。",
                                              "이 컴퓨터에서 아직 벤치마크를 실행하지 않아 시간을 추정할 수 없습니다.")}
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
    out = {"atoms": atoms, "ns_per_day": round(speed, 1), "md_hours": round(md_h, 1), "binding_hours": round(bind_h, 1),
           "total_hours": round(md_h + bind_h, 1), "systems": systems}
    if float(v["production_ns"]) > 100:        # long runs: days and disk (engine/longrun.py)
        lp = long_run_plan(values, f, goal)
        out.update({"days": round(out["total_hours"] / 24.0, 1), "disk_gb": lp["total_gb"],
                    "trajectory_interval_ps": lp["trajectory_interval_ps"], "solute_only": lp["solute_only"]})
    return out


def long_run_plan(values: dict, f: CaseFeatures, goal: str = "teaching", *, disk_free_gb: float | None = None) -> dict:
    """Plan for the production stage with these values (engine/longrun.py): days, disk, save interval, gates.
    `summary` is a (zh, en, ja, ko) line for the form."""
    from .engine.longrun import plan_long_run, summary_text
    v = {**recommended_values(f, goal), **{k: x for k, x in values.items() if x is not None}}
    solvent = v.get("solvent", "explicit")
    atoms = system_atoms(f, float(v["padding_nm"]), solvent)
    solute = (f.n_residues or 300) * 16 if solvent == "explicit" else None
    bench = {"ns_per_day": f.ns_per_day, "n_atoms": f.bench_atoms, "timestep_fs": f.bench_dt_fs} if f.ns_per_day else None
    systems = 1 + (f.n_ligands if v.get("docking_mode", f.docking_mode) == "independent" else 1)
    plan = plan_long_run(n_atoms=atoms, production_ns=float(v["production_ns"]), timestep_fs=float(v["timestep_fs"]),
                         bench=bench, n_solute_atoms=solute, disk_free_gb=disk_free_gb, confirmed=True,
                         replicas=int(v["replicas"]) * systems,
                         base_trajectory_ps=float(v.get("trajectory_interval_ps") or 20.0))
    d = plan.to_dict()
    d["summary"] = summary_text(plan)
    return d


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
