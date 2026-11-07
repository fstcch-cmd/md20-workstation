"""Smart restraint advice (D-118, spec restraints_freeze_truncation §3.1): which release strategy fits this system, and why.

Advice only.  Nothing here changes a protocol, a config or a build: the result names a strategy that
`make_protocol(restraints=…)` accepts, the per-stage group multipliers that strategy produces (taken from
`make_protocol` itself, so they cannot drift from the engine), a reason in four languages for each item, and the
difference from what the config sets now.  The user adopts it (one click in the advisor) or ignores it.

Not offered on purpose (spec §2): freezing atoms to save time (OpenMM computes every force on frozen atoms, so it saves
almost nothing) and pocket truncation (a different scientific model).  Not enough information gives status
"unavailable" and names what is missing; the function does not guess.

Pure Python (no OpenMM, no RDKit).  Language order everywhere: zh, en, ja, ko.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

from ..i18n import LANGS, pick
from .protocol import RESTRAINT_STRATEGIES, TIERS, make_protocol, membrane_protocol

# Judgment thresholds (spec §3.1 for the first one; the second is a teaching-grade rule of thumb, not a literature value).
RESOLUTION_ROUGH_A = 2.5          # crystal resolution coarser than this: positions are uncertain
PLDDT_LOW = 70.0                  # AlphaFold "low confidence" starts below this
LOW_CONF_FRACTION = 0.10          # at least this share of residues below PLDDT_LOW counts as a low-confidence region
SHORT_PRODUCTION_NS = 1.0         # below this a run only tests the pipeline (hold_backbone becomes an option)

_ORDER = ("zh", "en", "ja", "ko")


def _t(zh: str, en: str, ja: str, ko: str) -> dict:
    return {"zh": zh, "en": en, "ja": ja, "ko": ko}


def _tuple(t: dict) -> tuple:
    return tuple(t[k] for k in _ORDER)


@dataclass
class RestraintInputs:
    """What is known about the system.  None means "not known", which is different from False or 0."""
    has_ligand: bool | None = None            # False = apo run
    ligand_kind: str | None = None            # small | peptide | mixed
    simultaneous_ligands: bool = False        # several ligands docked together
    membrane: bool = False
    metals: list = field(default_factory=list)          # metals kept in the receptor
    bonded_metals: list = field(default_factory=list)   # sites modelled with bonds
    structure_source: str | None = None       # crystal | model
    resolution_a: float | None = None         # crystal resolution in angstrom
    plddt_low_fraction: float | None = None   # share of residues with pLDDT below 70 (models)
    has_gaps: bool = False                    # chain breaks, capped or rebuilt
    n_rebuilt_residues: int | None = None     # residues added by a loop rebuild
    n_pose_clashes: int | None = None         # clashes in the docked pose (None = no pose or not checked yet)
    target: str | None = None                 # md (MD only) | smd (SMD or umbrella follows)
    tier: str = "teaching"
    production_ns: float | None = None        # None = the tier's default length
    current: str | None = None                # md.restraints now (None = not set, i.e. the default "standard")

    def to_dict(self) -> dict:
        return asdict(self)


# ----------------------------------------------------------------------------------------------- reading a structure file
def resolution_from_pdb(text: str) -> float | None:
    """Crystal resolution from the REMARK   2 line of a PDB file (None for NMR, models or a missing line)."""
    for line in text.splitlines():
        if line.startswith("REMARK   2 RESOLUTION."):
            for tok in line[22:].replace("ANGSTROMS", " ").split():
                try:
                    return float(tok)
                except ValueError:
                    continue
            return None
        if line.startswith(("ATOM", "HETATM")):
            break
    return None


def plddt_low_fraction_from_pdb(text: str) -> float | None:
    """Share of residues whose CA B-factor (pLDDT in AlphaFold files) is below 70.  None when there is no CA atom."""
    vals = []
    for line in text.splitlines():
        if line.startswith("ATOM") and line[12:16].strip() == "CA":
            try:
                vals.append(float(line[60:66]))
            except ValueError:
                continue
    return sum(v < PLDDT_LOW for v in vals) / len(vals) if vals else None


# ----------------------------------------------------------------------------------------------- reasons
def _low_conf(i: RestraintInputs) -> bool:
    return bool(i.structure_source == "model" and i.plddt_low_fraction is not None
                and i.plddt_low_fraction >= LOW_CONF_FRACTION)


def rough_reasons(i: RestraintInputs) -> list[tuple[str, tuple]]:
    """[(key, short phrase in four languages)] for every feature that calls for the gentle release.  The advisor builds its
    parameter reason from these, so the recommended value and this advice always agree."""
    out: list[tuple[str, tuple]] = []
    if i.bonded_metals:
        out.append(("bonded_metal", ("含金屬鍵結模型", "a bonded metal site", "結合モデルの金属部位", "결합 모델 금속 부위")))
    if i.structure_source == "model":
        out.append(("model", ("受體是預測模型", "a predicted receptor model", "受容体が予測モデル", "예측 모델 수용체")))
    if _low_conf(i):
        out.append(("low_plddt", ("預測模型有低信心區（pLDDT 低於 70）", "low-confidence regions (pLDDT below 70)",
                                  "低信頼度の領域（pLDDT 70 未満）", "낮은 신뢰도 영역(pLDDT 70 미만)")))
    if i.has_gaps or (i.n_rebuilt_residues or 0) > 0:
        out.append(("gaps", ("受體有補建或封端的斷鏈", "rebuilt or capped chain breaks",
                             "補完またはキャップした鎖の切れ目", "보완하거나 캡을 씌운 사슬 끊김")))
    if i.ligand_kind in ("peptide", "mixed"):
        out.append(("peptide", ("配體是胜肽", "a peptide ligand", "ペプチドのリガンド", "펩타이드 리간드")))
    if i.simultaneous_ligands:
        out.append(("simultaneous", ("多配體同時對接", "simultaneous multi-ligand docking", "複数リガンドの同時ドッキング",
                                     "다중 리간드 동시 도킹")))
    if i.structure_source == "crystal" and i.resolution_a is not None and i.resolution_a > RESOLUTION_ROUGH_A:
        r = i.resolution_a
        out.append(("low_resolution", (f"解析度 {r:g} Å 低於 2.5 Å 的門檻", f"a resolution of {r:g} Å, coarser than 2.5 Å",
                                       f"分解能 {r:g} Å が 2.5 Å の目安より粗い", f"해상도 {r:g} Å로 2.5 Å 기준보다 거침")))
    if i.has_ligand and (i.n_pose_clashes or 0) > 0:
        n = i.n_pose_clashes
        out.append(("pose_clash", (f"對接姿勢有 {n} 處碰撞", f"{n} clashes in the docked pose", f"ドッキングポーズに {n} 件の衝突",
                                   f"도킹 포즈에 충돌 {n}건")))
    return out


def _reason_text(key: str, i: RestraintInputs) -> dict:
    if key == "bonded_metal":
        return _t("含金屬鍵結模型。金屬與配位原子之間的鍵很硬，升溫時容易出問題，所以約束保留到溫度穩定。",
                  "The system has a bonded metal site. The metal-ligand bonds are stiff and can fail during heating, so "
                  "the restraints stay on until the temperature is stable.",
                  "金属部位に結合モデルを使っています。金属と配位原子の結合は硬く、昇温中に問題が出やすいため、"
                  "温度が安定するまで拘束を残します。",
                  "금속 부위에 결합 모델을 씁니다. 금속과 배위 원자 사이 결합은 단단해 승온 중 문제가 생기기 쉬우므로 "
                  "온도가 안정될 때까지 구속을 유지합니다.")
    if key == "model":
        return _t("受體是預測模型。側鏈與 loop 的位置沒有實驗確認，先全部約束，等溶劑鬆弛後再釋放。",
                  "The receptor is a predicted model. Side chain and loop positions have no experimental support, so "
                  "everything is restrained first and released after the solvent has relaxed.",
                  "受容体は予測モデルです。側鎖とループの位置は実験で確認されていないため、まずすべて拘束し、"
                  "溶媒が緩和してから解除します。",
                  "수용체가 예측 모델입니다. 곁사슬과 루프의 위치는 실험으로 확인되지 않았으므로 먼저 모두 구속하고 "
                  "용매가 이완된 뒤에 해제합니다.")
    if key == "low_plddt":
        pct = (i.plddt_low_fraction or 0.0) * 100
        return _t(f"預測模型中有 {pct:.0f}% 的殘基 pLDDT 低於 70。這些區域的位置信心低，升溫時容易亂動。"
                  "目前約束只能分主鏈、側鏈、配體三組，不能只約束某幾個殘基，所以整體放慢。",
                  f"{pct:.0f}% of the residues in the model have a pLDDT below 70. Their positions are uncertain and "
                  "they tend to wander during heating. Restraints come in three groups (backbone, side chains, ligand) "
                  "and cannot target single residues, so the whole release is slowed down.",
                  f"モデルの残基の {pct:.0f}% で pLDDT が 70 未満です。これらの領域は位置の信頼度が低く、昇温中に動きやすくなります。"
                  "拘束は主鎖、側鎖、リガンドの3グループ単位で、特定の残基だけには掛けられないため、全体の解除を遅くします。",
                  f"모델 잔기의 {pct:.0f}%에서 pLDDT가 70 미만입니다. 이 영역은 위치 신뢰도가 낮아 승온 중 움직이기 쉽습니다. "
                  "구속은 주사슬, 곁사슬, 리간드 세 그룹 단위이고 특정 잔기에만 걸 수 없으므로 전체 해제를 늦춥니다.")
    if key == "gaps":
        n = i.n_rebuilt_residues
        extra = (_t(f"補建了 {n} 個殘基。", f"{n} residues were rebuilt. ", f"{n} 残基を補完しました。",
                    f"{n}개 잔기를 보완했습니다. ") if n else _t("", "", "", ""))
        base = _t("受體有補建或封端的斷鏈。補建的 loop 構形是估計值，需要溶劑先鬆弛。",
                  "The receptor has rebuilt or capped chain breaks. A rebuilt loop is an estimate and needs the solvent "
                  "to relax first.",
                  "受容体に補完またはキャップした鎖の切れ目があります。補完したループの構造は推定値で、先に溶媒が"
                  "緩和する必要があります。",
                  "수용체에 보완하거나 캡을 씌운 사슬 끊김이 있습니다. 보완한 루프 구조는 추정값이므로 먼저 용매가 "
                  "이완되어야 합니다.")
        return {k: extra[k] + base[k] for k in _ORDER}
    if key == "peptide":
        return _t("配體是胜肽。胜肽的構形多，結合姿勢也比較不穩，所以約束保留到加熱結束。",
                  "The ligand is a peptide. A peptide has many conformations and its pose is less stable, so the "
                  "restraints are held through heating.",
                  "リガンドはペプチドです。ペプチドは取りうる構造が多くポーズも不安定なため、加熱が終わるまで拘束を保持します。",
                  "리간드가 펩타이드입니다. 펩타이드는 구조가 다양하고 포즈도 덜 안정적이므로 가열이 끝날 때까지 "
                  "구속을 유지합니다.")
    if key == "simultaneous":
        return _t("多個配體同時對接，配體之間靠得近，姿勢比單一配體更容易互相碰撞。",
                  "Several ligands were docked together. They sit close to each other, so the poses clash more easily "
                  "than a single ligand does.",
                  "複数のリガンドを同時にドッキングしています。リガンドどうしが近く、単独の場合よりポーズが衝突しやすくなります。",
                  "여러 리간드를 동시에 도킹했습니다. 리간드끼리 가까워 단일 리간드보다 포즈가 충돌하기 쉽습니다.")
    if key == "low_resolution":
        r = i.resolution_a
        return _t(f"晶體解析度 {r:g} Å，粗於 2.5 Å，原子位置的不確定度大，起始結構可能有不合理的接觸。",
                  f"The crystal resolution is {r:g} Å, coarser than 2.5 Å. Atom positions are uncertain and the "
                  "starting structure may contain unrealistic contacts.",
                  f"結晶の分解能は {r:g} Å で 2.5 Å より粗く、原子位置の不確かさが大きいため、出発構造に不自然な接触が"
                  "含まれる可能性があります。",
                  f"결정 해상도가 {r:g} Å로 2.5 Å보다 거칠어 원자 위치의 불확실성이 크고, 시작 구조에 비현실적인 접촉이 "
                  "있을 수 있습니다.")
    if key == "pose_clash":
        n = i.n_pose_clashes
        return _t(f"對接姿勢有 {n} 處碰撞。碰撞在最小化與升溫時會產生很大的力，所以約束保留得久一些。",
                  f"The docked pose has {n} clashes. Clashes produce large forces during minimisation and heating, so "
                  "the restraints are kept longer.",
                  f"ドッキングポーズに {n} 件の衝突があります。衝突は最小化と昇温の間に大きな力を生むため、拘束を長めに残します。",
                  f"도킹 포즈에 충돌이 {n}건 있습니다. 충돌은 최소화와 승온 중에 큰 힘을 만들므로 구속을 더 오래 유지합니다.")
    raise KeyError(key)


# ----------------------------------------------------------------------------------------------- protocol facts
def _stage_table(strategy: str, i: RestraintInputs) -> dict:
    """{stage: {"master": [a, b], "groups": {...}, "length_ps": x}} exactly as the engine will build it."""
    proto = make_protocol(i.tier, restraints=strategy, production_ns=i.production_ns)
    if i.membrane:
        proto = membrane_protocol(proto)
    out = {}
    for st in proto.stages:
        if st.name == "minimize":
            continue
        end = st.restraint_scale if st.restraint_scale_end is None else st.restraint_scale_end
        out[st.name] = {"master": [float(st.restraint_scale), float(end)], "length_ps": float(st.length_ps),
                        "groups": {g: [float(a), float(b)] for g, (a, b) in (st.restraint_groups or {}).items()}}
    return out


def _diff(current: str, suggested: str, i: RestraintInputs) -> dict:
    cur, new = _stage_table(current, i), _stage_table(suggested, i)
    changes = []
    for stage in ("nvt", "npt", "production"):
        a, b = cur.get(stage, {}), new.get(stage, {})
        for g in sorted(set(a.get("groups", {})) | set(b.get("groups", {}))):
            x, y = a.get("groups", {}).get(g, [0.0, 0.0]), b.get("groups", {}).get(g, [0.0, 0.0])
            if x != y:
                changes.append({"stage": stage, "what": g, "current": x, "suggested": y})
        if a.get("length_ps") != b.get("length_ps"):
            changes.append({"stage": stage, "what": "length_ps", "current": a.get("length_ps"), "suggested": b.get("length_ps")})
    return {"current": current, "suggested": suggested, "same": current == suggested and not changes, "changes": changes}


def decision_entry(advice: dict) -> dict:
    """Arguments for DecisionLog.record(…) when the user adopts the advice (the Chinese reason is the log convention).
    Nothing is written here."""
    return {"stage": "md.restraints", "what": "約束策略建議", "choice": advice.get("strategy"),
            "why": advice.get("summary_all", {}).get("zh", ""), "kind": "human",
            "evidence": {"reasons": [x["key"] for x in advice.get("items", []) if x.get("role") == "reason"],
                         "not_considered": [x["key"] for x in advice.get("not_considered", [])],
                         "current": (advice.get("differences") or {}).get("current")}}


# ----------------------------------------------------------------------------------------------- the advice
def _missing(i: RestraintInputs) -> list[dict]:
    m = []
    if i.has_ligand is None:
        m.append({"key": "has_ligand", "text": _t("是否有配體（apo 或複合物）", "whether there is a ligand (apo or complex)",
                                                   "リガンドの有無（アポか複合体か）", "리간드 유무(아포 또는 복합체)")})
    if i.structure_source not in ("crystal", "model"):
        m.append({"key": "structure_source", "text": _t("受體來源（晶體結構或預測模型）",
                                                        "the receptor source (crystal structure or predicted model)",
                                                        "受容体の由来（結晶構造か予測モデルか）",
                                                        "수용체 출처(결정 구조 또는 예측 모델)")})
    if i.target not in ("md", "smd"):
        m.append({"key": "target", "text": _t("目標（只做 MD，或之後要做 SMD）", "the goal (MD only, or SMD afterwards)",
                                               "目的（MD のみか、その後 SMD まで行うか）", "목표(MD만 또는 이후 SMD까지)")})
    if i.tier not in TIERS:
        m.append({"key": "tier", "text": _t(f"可辨識的 tier（目前是 {i.tier}）", f"a known tier (got {i.tier})",
                                            f"既知の tier（現在は {i.tier}）", f"알려진 tier(현재 {i.tier})")})
    if i.target == "smd" and i.has_ligand is False:
        m.append({"key": "ligand_for_smd", "text": _t("SMD 需要配體，但目前沒有配體", "a ligand, because SMD needs one and this run has none",
                                                       "リガンド（SMD に必要ですが、現在はありません）",
                                                       "리간드(SMD에 필요하지만 현재 없음)")})
    return m


def _resolve(t: dict, lang: str) -> str:
    return pick(_tuple(t), lang)


def advise(i: RestraintInputs, lang: str = "en") -> dict:
    """Advice for one system.  status "advice" or "unavailable".  Never changes anything (applied is always False)."""
    lang = lang if lang in LANGS else "en"
    miss = _missing(i)
    if miss:
        listing = {k: ", ".join(_resolve(m["text"], k) for m in miss) for k in _ORDER}
        msg = _t(f"資料不足，無法建議約束策略。還缺這些資料：{listing['zh']}。", f"Not enough information to advise on restraints. "
                 f"Missing: {listing['en']}.", f"情報が足りないため、拘束戦略は提案できません。不足しているのは次のとおりです：{listing['ja']}。",
                 f"정보가 부족해 구속 전략을 제안할 수 없습니다. 부족한 항목은 다음과 같습니다: {listing['ko']}.")
        return {"status": "unavailable", "applied": False, "strategy": None, "protocol_args": None, "summary": _resolve(msg, lang),
                "summary_all": msg, "missing": [{"key": m["key"], "text": _resolve(m["text"], lang), "text_all": m["text"]} for m in miss],
                "items": [], "options": [], "not_considered": [], "differences": None, "stages": {}}

    reasons = rough_reasons(i)
    strategy = "gentle" if reasons else "standard"
    items: list[dict] = []

    def add(key, level, text, role="note"):
        items.append({"key": key, "level": level, "role": role, "text": _resolve(text, lang), "text_all": text})

    for key, _ in reasons:
        add(key, "info", _reason_text(key, i), "reason")
    if not reasons:
        add("standard", "info", _t("沒有找到需要放慢釋放的特徵，主鏈與配體的約束在定壓平衡中逐步釋放就夠了。",
                                   "Nothing here calls for a slower release. Releasing the backbone and ligand restraints step by "
                                   "step during NPT is enough.",
                                   "解除を遅くすべき特徴は見つかりませんでした。主鎖とリガンドの拘束は NPT 平衡化の中で段階的に"
                                   "解除すれば十分です。",
                                   "해제를 늦춰야 할 특징이 발견되지 않았습니다. 주사슬과 리간드 구속은 NPT 평형 중에 단계적으로 "
                                   "해제하면 충분합니다."), "reason")

    stages = _stage_table(strategy, i)
    if strategy == "gentle":
        std_npt = _stage_table("standard", i)["npt"]["length_ps"]
        extra = stages["npt"]["length_ps"] - std_npt
        prod = stages["production"]["length_ps"]
        add("gentle_cost", "info", _t(f"溫和釋放讓定壓平衡從 {std_npt:g} ps 延長到 {stages['npt']['length_ps']:g} ps，多花 {extra:g} ps，"
                                      f"約為正式模擬長度的 {100 * extra / prod:.0f}%。",
                                      f"The gentle release lengthens NPT from {std_npt:g} ps to {stages['npt']['length_ps']:g} ps. "
                                      f"That is {extra:g} ps more, about {100 * extra / prod:.0f}% of the production length.",
                                      f"穏やかな解除では NPT 平衡化が {std_npt:g} ps から {stages['npt']['length_ps']:g} ps に延び、"
                                      f"{extra:g} ps 増えます。本計算の長さの約 {100 * extra / prod:.0f}% です。",
                                      f"완만한 해제는 NPT 평형을 {std_npt:g} ps에서 {stages['npt']['length_ps']:g} ps로 늘려 "
                                      f"{extra:g} ps가 더 듭니다. 본 계산 길이의 약 {100 * extra / prod:.0f}%입니다."))
    if i.has_ligand is False:
        add("apo", "info", _t("這是沒有配體的 apo 系統，配體組的倍率不會作用在任何原子上。",
                              "This is an apo system. The ligand group multipliers act on no atoms.",
                              "リガンドのないアポ系なので、リガンドグループの倍率はどの原子にも作用しません。",
                              "리간드가 없는 아포 계이므로 리간드 그룹 배율은 어떤 원자에도 작용하지 않습니다."))
    if i.metals and not i.bonded_metals:
        add("free_metals", "info", _t("受體保留的金屬離子以非鍵結離子處理，不在任何約束組內，位置由力場決定。",
                                      "Metal ions kept in the receptor are non-bonded ions. They belong to no restraint group and "
                                      "their positions follow the force field.",
                                      "受容体に残した金属イオンは非結合イオンとして扱われ、どの拘束グループにも入らず、"
                                      "位置は力場で決まります。",
                                      "수용체에 남긴 금속 이온은 비결합 이온으로 처리되며 어떤 구속 그룹에도 속하지 않고 "
                                      "위치는 힘장이 결정합니다."))
    if i.membrane:
        add("membrane", "info", _t("膜系統另有脂質頭基的 z 約束組（lipid_head），隨蛋白一起在定壓平衡中釋放。"
                                   "它由膜流程自動加入，不在這項建議的選擇範圍內。",
                                   "A membrane system also has a lipid head group z restraint (lipid_head), released together "
                                   "with the protein during NPT. The membrane workflow adds it automatically and this advice "
                                   "does not change it.",
                                   "膜系には脂質頭部の z 拘束グループ（lipid_head）もあり、タンパク質と一緒に NPT 平衡化で解除されます。"
                                   "膜ワークフローが自動で追加するもので、この提案では変更しません。",
                                   "막 계에는 지질 머리 그룹의 z 구속 그룹(lipid_head)도 있으며 단백질과 함께 NPT 평형에서 "
                                   "해제됩니다. 막 워크플로가 자동으로 추가하며 이 제안은 그것을 바꾸지 않습니다."))
    if i.target == "smd":
        add("smd", "info", _t("之後的拉離與傘狀採樣另有約束設定（側鏈與配體不約束，只留主鏈），這項建議只管前面的平衡階段。",
                              "The pulling and umbrella stages that follow have their own restraint setup (side chains and "
                              "ligand free, backbone only). This advice covers the equilibration before them.",
                              "その後の引き離しとアンブレラサンプリングには別の拘束設定があり（側鎖とリガンドは拘束せず、主鎖のみ）、"
                              "この提案は手前の平衡化だけを対象にします。",
                              "이후의 당김과 엄브렐라 샘플링에는 별도의 구속 설정이 있으며(곁사슬과 리간드는 구속하지 않고 주사슬만 유지) "
                              "이 제안은 그 앞의 평형 단계만 다룹니다."))
    add("no_freeze", "info", _t("不建議為了省時間而凍結原子。OpenMM 對凍結原子的力照樣計算，省下的時間很少。口袋截斷會改變科學模型，"
                                "這裡不提供。",
                                "Freezing atoms to save time is not advised. OpenMM still computes every force on frozen atoms, so "
                                "little time is saved. Pocket truncation changes the scientific model and is not offered here.",
                                "時間短縮のための原子凍結はお勧めしません。OpenMM は凍結した原子の力も計算するため、"
                                "節約できる時間はわずかです。ポケットの切り出しは科学モデルを変えるため、ここでは提供しません。",
                                "시간을 아끼려고 원자를 동결하는 것은 권하지 않습니다. OpenMM은 동결한 원자의 힘도 계산하므로 "
                                "절약되는 시간이 거의 없습니다. 포켓 절단은 과학적 모델을 바꾸므로 여기서는 제공하지 않습니다."))

    # hold_backbone is an option for short runs, never the default
    prod_ns = i.production_ns if i.production_ns is not None else TIERS[i.tier]["prod_ps"] / 1000.0
    options = []
    if i.target == "smd":
        o = (False, _t("之後要做 SMD 時不建議。正式模擬保留主鏈約束，口袋無法重排，RMSD 和 RMSF 也只是受約束的數值。",
                       "Not advised when SMD follows. A restrained backbone keeps the pocket from rearranging, and RMSD and "
                       "RMSF become restrained values.",
                       "後で SMD を行う場合はお勧めしません。主鎖の拘束が残るとポケットが再配置できず、RMSD と RMSF も"
                       "拘束下の値になります。",
                       "이후 SMD를 할 때는 권하지 않습니다. 주사슬 구속이 남으면 포켓이 재배열되지 못하고 RMSD와 RMSF도 "
                       "구속된 값이 됩니다."))
    elif i.structure_source == "model" or _low_conf(i):
        o = (False, _t("起始主鏈本身信心不足，約束會把預測的誤差一起固定下來，不建議。",
                       "The starting backbone is not trustworthy, and a restraint would lock the prediction's errors in. "
                       "Not advised.",
                       "出発構造の主鎖自体の信頼度が低く、拘束すると予測の誤差も固定してしまうため、お勧めしません。",
                       "시작 주사슬 자체의 신뢰도가 낮아 구속하면 예측의 오차까지 고정되므로 권하지 않습니다."))
    elif prod_ns < SHORT_PRODUCTION_NS:
        o = (True, _t(f"正式模擬只有 {prod_ns:g} ns，只能檢查流程。可以改用 hold_backbone，讓主鏈保留 5% 約束，結構不容易走樣。"
                      "報告會把 RMSD 和 RMSF 標為受約束，不能當作穩定的證據。",
                      f"Production is only {prod_ns:g} ns, which checks the pipeline and little else. hold_backbone keeps "
                      "the backbone at 5% restraint so the structure stays close to the start. The report labels RMSD and "
                      "RMSF as restrained, and they are no evidence of stability.",
                      f"本計算は {prod_ns:g} ns しかなく、ワークフローの確認にしか使えません。hold_backbone にすると主鎖の拘束を "
                      "5% 残して構造が崩れにくくなります。レポートでは RMSD と RMSF を拘束下の値として表示し、安定性の証拠にはなりません。",
                      f"본 계산이 {prod_ns:g} ns뿐이라 워크플로 확인에만 쓸 수 있습니다. hold_backbone을 쓰면 주사슬 구속을 5% "
                      "남겨 구조가 덜 무너집니다. 보고서는 RMSD와 RMSF를 구속된 값으로 표시하며 안정성의 증거가 되지 않습니다."))
    else:
        o = (False, _t(f"正式模擬有 {prod_ns:g} ns，建議讓主鏈自由。保留約束時的低 RMSD 不代表結構穩定。",
                       f"Production is {prod_ns:g} ns, long enough to leave the backbone free. A low RMSD under a restraint "
                       "does not show that the structure is stable.",
                       f"本計算は {prod_ns:g} ns あるので、主鎖は自由にすることをお勧めします。拘束下で RMSD が低くても、構造が"
                       "安定している証拠にはなりません。",
                       f"본 계산이 {prod_ns:g} ns이므로 주사슬을 자유롭게 두기를 권합니다. 구속 상태에서 RMSD가 낮아도 구조가 "
                       "안정적이라는 증거는 아닙니다."))
    options.append({"strategy": "hold_backbone", "suggested": o[0], "role": "option", "text": _resolve(o[1], lang), "text_all": o[1]})

    # what the user has now
    cur_name = i.current or "standard"
    cur_valid = cur_name in RESTRAINT_STRATEGIES
    diff = _diff(cur_name, strategy, i) if cur_valid else {"current": cur_name, "suggested": strategy, "same": False, "changes": []}
    diff["current_valid"] = cur_valid
    diff["current_is_default"] = i.current is None
    if cur_valid and cur_name == "hold_backbone" and (i.target == "smd" or i.structure_source == "model" or _low_conf(i)):
        add("current_hold_backbone", "warning", options[0]["text_all"], "caution")

    not_considered = []

    def nc(key, text):
        not_considered.append({"key": key, "text": _resolve(text, lang), "text_all": text})
    if i.structure_source == "crystal" and i.resolution_a is None:
        nc("resolution", _t("沒有提供晶體解析度，所以沒有用它判斷。", "No crystal resolution was given, so it was not used.",
                            "結晶の分解能が与えられていないため、判断に使っていません。", "결정 해상도가 주어지지 않아 판단에 쓰지 않았습니다."))
    if i.structure_source == "model" and i.plddt_low_fraction is None:
        nc("plddt", _t("沒有 pLDDT 資料，所以沒有判斷低信心區。預測模型本身已經使用溫和釋放。",
                       "No pLDDT values were given, so low-confidence regions were not assessed. A predicted model already gets "
                       "the gentle release.",
                       "pLDDT の値が与えられていないため、低信頼度領域は評価していません。予測モデルは、それだけで穏やかな解除になります。",
                       "pLDDT 값이 주어지지 않아 낮은 신뢰도 영역은 평가하지 않았습니다. 예측 모델은 그 자체로 완만한 해제를 씁니다."))
    if i.has_ligand and i.n_pose_clashes is None:
        nc("pose_clash", _t("尚未檢查對接姿勢的碰撞。有姿勢之後會重新評估。",
                            "Clashes in the docked pose have not been checked yet. The advice is reassessed once a pose exists.",
                            "ドッキングポーズの衝突はまだ調べていません。ポーズができたら再評価します。",
                            "도킹 포즈의 충돌은 아직 확인하지 않았습니다. 포즈가 생기면 다시 평가합니다."))

    if strategy == "gentle":
        names = _t("、".join(s[0] for _, s in reasons), ", ".join(s[1] for _, s in reasons),
                   "、".join(s[2] for _, s in reasons), ", ".join(s[3] for _, s in reasons))
        summary = _t(f"建議溫和釋放（gentle）。起始結構比較粗糙（{names['zh']}），約束全部保留到加熱結束，再用加倍長度的定壓平衡釋放。",
                     f"Gentle release is advised. The starting structure is rough ({names['en']}). All restraints are held "
                     "through heating and released over an NPT stage of twice the length.",
                     f"穏やかな解除（gentle）をお勧めします。出発構造が粗い（{names['ja']}）ため、加熱が終わるまで拘束をすべて保持し、"
                     "2倍の長さの NPT 平衡化で解除します。",
                     f"완만한 해제(gentle)를 권합니다. 시작 구조가 거칠기 때문에({names['ko']}) 가열이 끝날 때까지 모든 구속을 "
                     "유지하고 두 배 길이의 NPT 평형에서 해제합니다.")
    else:
        body = items[0]["text_all"]
        lead = _t("建議標準釋放（standard）。", "Standard release is advised. ", "標準の解除（standard）をお勧めします。",
                  "표준 해제(standard)를 권합니다. ")
        summary = {k: lead[k] + body[k] for k in _ORDER}

    return {"status": "advice", "applied": False, "strategy": strategy, "protocol_args": {"restraints": strategy},
            "summary": _resolve(summary, lang), "summary_all": summary, "stages": stages, "items": items, "options": options,
            "not_considered": not_considered, "differences": diff, "missing": []}
