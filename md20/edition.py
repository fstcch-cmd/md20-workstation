"""MD20 editions (D-181): the complete edition and MD20 Lite.

Lite is the edition handed to people outside the lab.  It runs the whole route once, docking to molecular dynamics to a
quick PMF to the report, at a limited size.  The complete edition lifts the size limits and adds the features Lite only
describes.  A Lite project opens in the complete edition unchanged, so nothing has to be redone after an upgrade.

This module is the only place that knows what an edition is:

* which edition is running (`build_edition`, `current`);
* the size limits of each edition (`LIMITS`);
* the features that exist only in the complete edition (`PRO_FEATURES`), with the four-language text the interface
  and the report show for them, and the source modules `tools/build_lite.py` removes from a Lite package;
* the checks (`check_config`, `check_system`, `check_library`) and the automatic reduction (`clamp_config`).

Nothing else in MD20 may hard-code "if lite".  Ask this module.

How the edition is decided
--------------------------
1. The package: `tools/build_lite.py` writes `md20/_edition.json` into a Lite package and removes the complete-edition
   modules from it.  A package that carries the marker is Lite whatever licence is installed, because the code for the
   complete features is not there.
2. The licence: a valid licence whose `features` list contains `lite` makes a complete package behave as Lite (same
   limits, same texts).  `features` is an existing field of licence format v2 that the verifier reads as a list of
   words, so no change of the licence format, of the verifier or of the released versions is needed.  A Lite licence
   is issued as, for example, `features: ["lite", "binding", "hts"]`.

There is no environment variable, setting or parameter that changes the edition (tests check this source).  A marker
that cannot be read counts as Lite: the marker only exists in a Lite package.

Honest limits
-------------
The size limits are numbers in this file.  In a source distribution anyone can edit them, so a Lite package should be
built with the compiled core (docs/specs/licensing.md §13), which includes this module.  What cannot be edited back in
is the code of the complete-edition features: it is not shipped.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

from .i18n import pick

FULL = "full"
LITE = "lite"
EDITIONS = (FULL, LITE)
LITE_FLAG = "lite"                       # word in a licence's `features` that selects Lite on a complete package
MARKER_NAME = "_edition.json"
MARKER_SCHEMA = "md20-edition/1"
_MARKER = Path(__file__).with_name(MARKER_NAME)

EDITION_NAMES = {
    FULL: ("MD20 完整版", "MD20 complete edition", "MD20 完全版", "MD20 정식판"),
    LITE: ("MD20 Lite", "MD20 Lite", "MD20 Lite", "MD20 Lite"),
}


# ---------------------------------------------------------------------------------------------- which edition
def marker_document(version: str = "") -> dict:
    """The content `tools/build_lite.py` writes to `md20/_edition.json`."""
    return {"schema": MARKER_SCHEMA, "edition": LITE, "version": str(version)}


def build_edition(marker: Path | None = None) -> str:
    """Edition of this package.  No marker file: complete.  A marker file, readable or not: Lite."""
    p = _MARKER if marker is None else Path(marker)
    try:
        if not p.is_file():
            return FULL
    except OSError:
        return LITE
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001  (a damaged marker is still a marker)
        return LITE
    return FULL if isinstance(doc, dict) and doc.get("edition") == FULL and doc.get("schema") == MARKER_SCHEMA else LITE


def licence_features() -> list | None:
    """`features` of the valid licence in use: None when there is no valid licence or the licence has every feature.
    Never raises."""
    try:
        from .util import license as _lic
        st = _lic.status()
        return list(st.features) if st.ok and st.features is not None else None
    except Exception:  # noqa: BLE001  (asking for the edition must never break a run or a page)
        return None


_UNSET = object()


def current(*, features=_UNSET, marker: Path | None = None) -> str:
    """The edition in effect: Lite when the package is Lite or the licence carries the `lite` word, else complete.
    `features` and `marker` are for tests and for callers that already hold a licence status."""
    if build_edition(marker) == LITE:
        return LITE
    f = licence_features() if features is _UNSET else features
    return LITE if f is not None and LITE_FLAG in f else FULL


def is_lite(**kw) -> bool:
    return current(**kw) == LITE


def name(edition: str | None = None, lang: str = "en") -> str:
    return pick(EDITION_NAMES[edition or current()], lang)


# ---------------------------------------------------------------------------------------------- size limits
@dataclass(frozen=True)
class Limits:
    """Size limits of one edition.  None means no limit."""
    max_atoms: int | None = None               # atoms of one explicit-solvent system
    max_atoms_implicit: int | None = None      # atoms of one implicit-solvent (GBn2) system
    max_protein_residues: int | None = None
    max_ligands: int | None = None             # ligands in one workflow (and in one multi-ligand docking)
    max_screen_compounds: int | None = None    # rows of a screening library
    max_production_ns: float | None = None
    max_replicas: int | None = None            # independent MD repeats of one system
    max_binding_replicas: int | None = None    # independent pulls of one ligand
    max_windows: int | None = None             # umbrella windows of one PMF
    max_window_ps: float | None = None         # sampling time of one window
    max_refine_rounds: int | None = None       # automatic refinement rounds of the windows
    md_tiers: tuple | None = None              # allowed `md.tier` values; None = all

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["md_tiers"] = list(self.md_tiers) if self.md_tiers is not None else None
        return d


LIMITS: dict[str, Limits] = {
    FULL: Limits(),
    # Chosen so that a single-domain protein with one or two ligands in the smallest water box finishes on a student
    # laptop (docs/specs/lite_edition.md §3).  The two features the owner uses most, multi-ligand docking and
    # screening, are open at a small size so that people try them, and the real size stays with the complete edition.
    LITE: Limits(max_atoms=30_000, max_atoms_implicit=6_000, max_protein_residues=400, max_ligands=2,
                 max_screen_compounds=10, max_production_ns=10.0, max_replicas=1, max_binding_replicas=1,
                 max_windows=12, max_window_ps=500.0, max_refine_rounds=0, md_tiers=("classroom", "teaching")),
}


def limits(edition: str | None = None) -> Limits:
    return LIMITS[edition or current()]


# ---------------------------------------------------------------------------------------------- complete-only features
@dataclass(frozen=True)
class ProFeature:
    """A feature that exists only in the complete edition."""
    id: str
    title: tuple                 # (zh, en, ja, ko)
    gain: tuple                  # one sentence: what the complete edition gives you here
    modules: tuple = ()          # source files removed from a Lite package (relative to the repository root)
    preview: bool = False        # the Lite interface shows a description page for it


PRO_FEATURES: tuple[ProFeature, ...] = (
    ProFeature(
        "membrane",
        ("膜系統", "Membrane systems", "膜系", "막 시스템"),
        ("完整版會建好脂雙層，放入膜蛋白或讓胜肽和藥物貼在膜表面，再接著做分子動力學。",
         "The complete edition builds the lipid bilayer, places a membrane protein in it or a peptide or drug on its surface, and runs the molecular dynamics from there.",
         "完全版では脂質二重層を組み立て、膜タンパク質を埋め込むか、ペプチドや薬物を膜表面に置いて分子動力学まで進めます。",
         "정식판은 지질 이중층을 만들고 막 단백질을 넣거나 펩타이드와 약물을 막 표면에 놓은 뒤 분자동역학까지 진행합니다."),
        modules=("md20/build/membrane.py", "md20/analysis/membrane.py"), preview=True),
    ProFeature(
        "fold",
        ("胜肽序列一鍵摺疊", "Folding a peptide from its sequence", "配列からのペプチド折りたたみ", "서열에서 펩타이드 접기"),
        ("完整版可以直接貼上胜肽序列，由程式預測結構後接著對接。",
         "In the complete edition you paste a peptide sequence, the program predicts its structure and docking continues from it.",
         "完全版ではペプチドの配列を貼り付けるだけで構造を予測し、そのままドッキングに進めます。",
         "정식판에서는 펩타이드 서열을 붙여 넣으면 구조를 예측하고 바로 도킹으로 이어집니다."),
        modules=("md20/build/fold.py",), preview=True),
    ProFeature(
        "cg",
        ("粗粒化模擬", "Coarse-grained simulation", "粗視化シミュレーション", "조립화 시뮬레이션"),
        ("完整版提供 Martini 3 粗粒化流程，適合大型膜系統和較長的時間尺度。",
         "The complete edition has a Martini 3 coarse-grained route for large membrane systems and longer time scales.",
         "完全版には Martini 3 の粗視化ルートがあり、大きな膜系や長い時間スケールに向いています。",
         "정식판에는 Martini 3 조립화 경로가 있어 큰 막 시스템과 긴 시간 규모에 알맞습니다."),
        modules=("md20/build/martini.py", "md20/build/cg_system.py")),
    ProFeature(
        "long_run",
        ("微秒級長時間模擬", "Microsecond-scale runs", "マイクロ秒規模の長時間計算", "마이크로초 규모의 장시간 계산"),
        ("完整版可以把正式模擬排到微秒級，分段執行並自動續跑。",
         "The complete edition schedules production runs up to the microsecond scale, in segments that resume by themselves.",
         "完全版では本計算をマイクロ秒規模まで計画でき、区切って実行し自動で再開します。",
         "정식판은 본 계산을 마이크로초 규모까지 계획하고 구간별로 실행하며 자동으로 이어서 실행합니다."),
        modules=("md20/engine/longrun.py",)),
    ProFeature(
        "replicas",
        ("獨立重複與不確定度", "Independent repeats and uncertainty", "独立した繰り返しと不確かさ", "독립 반복과 불확도"),
        ("完整版會依分析需要自動安排三次以上的獨立重複，報告的每個數值都附上重複之間的差異。",
         "The complete edition plans three or more independent repeats where the analysis needs them, and every number in the report comes with the spread between repeats.",
         "完全版では解析に必要なだけ三回以上の独立した繰り返しを自動で計画し、レポートの数値には繰り返し間のばらつきが付きます。",
         "정식판은 분석에 필요한 만큼 세 번 이상의 독립 반복을 자동으로 계획하고 보고서의 모든 수치에 반복 간 편차를 함께 제시합니다.")),
    ProFeature(
        "binding_full",
        ("完整的結合自由能", "Full binding free energy", "完全な結合自由エネルギー", "완전한 결합 자유 에너지"),
        ("完整版會自動補窗口直到相鄰窗口重疊足夠，並以多次獨立拉離給出 ΔG° 和誤差。",
         "The complete edition adds windows until neighbouring windows overlap enough, and reports ΔG° with its error from several independent pulls.",
         "完全版では隣り合うウィンドウが十分に重なるまでウィンドウを追加し、複数回の独立した引き離しから ΔG° と誤差を報告します。",
         "정식판은 이웃한 윈도우가 충분히 겹칠 때까지 윈도우를 추가하고 여러 번의 독립 당김으로 ΔG°와 오차를 보고합니다."),
        modules=("md20/sampling/adaptive.py",)),
    ProFeature(
        "screen_full",
        ("大型化合物庫篩選", "Screening a large compound library", "大規模な化合物ライブラリのスクリーニング", "대규모 화합물 라이브러리 스크리닝"),
        ("完整版一次可以篩選數百個化合物，排名後挑選要送進分子動力學的配體。",
         "The complete edition screens several hundred compounds in one run, ranks them and lets you pick the ligands that go on to molecular dynamics.",
         "完全版では一度に数百の化合物をスクリーニングし、順位付けのあと分子動力学に進めるリガンドを選べます。",
         "정식판은 한 번에 수백 개의 화합물을 스크리닝하고 순위를 매긴 뒤 분자동역학으로 보낼 리간드를 고를 수 있습니다.")),
    ProFeature(
        "multi_ligand_full",
        ("三個以上配體同時對接", "Docking three or more ligands together", "三つ以上のリガンドの同時ドッキング", "세 개 이상 리간드의 동시 도킹"),
        ("完整版不限制同時對接的配體數，並分析它們共存時的互相影響。",
         "The complete edition has no limit on the number of ligands docked together and analyses how they affect each other.",
         "完全版では同時にドッキングするリガンドの数に制限がなく、共存時の相互作用も解析します。",
         "정식판은 동시에 도킹하는 리간드 수에 제한이 없고 함께 있을 때의 상호 영향도 분석합니다.")),
    ProFeature(
        "analysis_toolbox",
        ("進階分析工具箱", "Advanced analysis toolbox", "高度な解析ツール", "고급 분석 도구"),
        ("完整版多了 tICA 和馬可夫狀態模型、氫鍵網路、水合分析，以及跨系統的共同主成分比較。",
         "The complete edition adds tICA and Markov state models, hydrogen-bond networks, hydration analysis and a common principal-component comparison across systems.",
         "完全版には tICA とマルコフ状態モデル、水素結合ネットワーク、水和解析、系をまたいだ共通主成分での比較が加わります。",
         "정식판에는 tICA와 마르코프 상태 모형, 수소 결합 네트워크, 수화 분석, 시스템 간 공통 주성분 비교가 더해집니다."),
        modules=("md20/analysis/extended.py",)),
    ProFeature(
        "autonomy",
        ("自動檢查與補跑", "Automatic checking and follow-up runs", "自動チェックと追加計算", "자동 점검과 추가 계산"),
        ("完整版會在結果不夠可靠時自己安排補跑，並把每一步的理由記下來。",
         "The complete edition schedules follow-up runs by itself when a result is not reliable enough, and records the reason for each step.",
         "完全版では結果の信頼性が足りないときに追加計算を自分で計画し、各ステップの理由を記録します。",
         "정식판은 결과의 신뢰도가 부족하면 추가 계산을 스스로 계획하고 각 단계의 이유를 기록합니다."),
        modules=("md20/autonomy/cli.py", "md20/autonomy/controller.py", "md20/autonomy/executors.py",
                 "md20/autonomy/ledger.py", "md20/autonomy/model.py", "md20/autonomy/rules.py")),
    ProFeature(
        "large_system",
        ("大型系統", "Large systems", "大きな系", "큰 시스템"),
        ("完整版不限制系統大小，多結構域蛋白、複合體和較大的水盒都可以直接計算。",
         "The complete edition has no size limit, so multi-domain proteins, complexes and larger water boxes run as they are.",
         "完全版には系の大きさの制限がなく、複数ドメインのタンパク質や複合体、大きな水ボックスもそのまま計算できます。",
         "정식판은 시스템 크기에 제한이 없어 여러 도메인 단백질, 복합체, 더 큰 물 상자도 그대로 계산할 수 있습니다.")),
)
_PRO = {f.id: f for f in PRO_FEATURES}


def pro_feature(fid: str) -> ProFeature:
    return _PRO[fid]


def pro_modules() -> tuple[str, ...]:
    """Every source file a Lite package does not ship, sorted."""
    return tuple(sorted({m for f in PRO_FEATURES for m in f.modules}))


class UpgradeRequired(RuntimeError):
    """Raised when something that exists only in the complete edition is called in Lite."""

    def __init__(self, feature: str = "", what: str = ""):
        self.feature = feature
        self.what = what
        f = _PRO.get(feature)
        self.texts = tuple(upgrade_text(feature, l) for l in ("zh", "en", "ja", "ko")) if f else (what,) * 4
        super().__init__(self.texts[1] or what or feature)


def upgrade_text(fid: str, lang: str = "en") -> str:
    """'<feature> is part of the complete edition. <what you gain>' in one language."""
    f = _PRO[fid]
    lead = pick(("「{t}」屬於 MD20 完整版。", "{t} is part of the MD20 complete edition.", "「{t}」は MD20 完全版の機能です。",
                 "{t} 기능은 MD20 정식판에 있습니다."), lang).format(t=pick(f.title, lang))
    return lead + ("" if lang in ("zh", "ja") else " ") + pick(f.gain, lang)


HOW_TO_UPGRADE = (
    "需要完整版時，請聯絡 HCC Lab。這個專案可以用完整版直接打開，已經算完的部分不用重做。",
    "For the complete edition, contact HCC Lab. This project opens in the complete edition as it is, and what has been computed is kept.",
    "完全版が必要なときは HCC Lab にご連絡ください。このプロジェクトは完全版でそのまま開けて、計算済みの部分はやり直す必要がありません。",
    "정식판이 필요하면 HCC Lab에 문의하십시오. 이 프로젝트는 정식판에서 그대로 열리며 이미 계산한 부분은 다시 하지 않아도 됩니다.",
)


# ---------------------------------------------------------------------------------------------- hits
SCALE = "scale"          # a size limit; `clamp_config` can bring the config under it
FEATURE = "feature"      # a complete-only feature; the config has to drop it


@dataclass
class Hit:
    """One place where a config or a built system goes beyond the edition in effect."""
    code: str                      # stable identifier, e.g. "md.production_ns", "feature.membrane"
    kind: str                      # SCALE | FEATURE
    value: object = None           # what was asked for
    limit: object = None           # what this edition allows
    feature: str = ""              # PRO_FEATURES id that lifts it
    can_clamp: bool = False
    extra: dict = field(default_factory=dict)

    def text(self, lang: str = "en") -> str:
        t = _HIT_TEXT.get(self.code) or _HIT_TEXT["feature"]
        body = pick(t, lang).format(value=_fmt(self.value), limit=_fmt(self.limit),
                                    title=pick(_PRO[self.feature].title, lang) if self.feature in _PRO else self.feature)
        gain = pick(_PRO[self.feature].gain, lang) if self.feature in _PRO else ""
        sep = "" if lang in ("zh", "ja") else " "
        return body + (sep + gain if gain and self.kind == SCALE else "")

    def texts(self) -> tuple:
        return tuple(self.text(l) for l in ("zh", "en", "ja", "ko"))

    def as_dict(self) -> dict:
        return {"code": self.code, "kind": self.kind, "value": self.value, "limit": self.limit, "feature": self.feature,
                "can_clamp": self.can_clamp, "text": dict(zip(("zh", "en", "ja", "ko"), self.texts()))}


def _fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, int) and not isinstance(v, bool) and abs(v) >= 10_000:
        return f"{v:,}"
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)
    return str(v)


_HIT_TEXT = {
    "md.production_ns": ("正式模擬設為 {value} ns，Lite 最長 {limit} ns。", "The production run is set to {value} ns. Lite runs up to {limit} ns.",
                         "本計算が {value} ns に設定されています。Lite は {limit} ns までです。", "본 계산이 {value} ns로 설정되어 있습니다. Lite는 {limit} ns까지입니다."),
    "md.tier": ("模擬等級設為 {value}，Lite 可以用的等級是 {limit}。", "The simulation tier is {value}. Lite offers {limit}.",
                "計算の等級が {value} になっています。Lite で使える等級は {limit} です。", "계산 등급이 {value}입니다. Lite에서 쓸 수 있는 등급은 {limit}입니다."),
    "md.replicas": ("獨立重複設為 {value} 次，Lite 每個系統跑 {limit} 次。", "{value} independent repeats are requested. Lite runs {limit} per system.",
                    "独立した繰り返しが {value} 回に設定されています。Lite は一つの系につき {limit} 回です。", "독립 반복이 {value} 회로 설정되어 있습니다. Lite는 시스템마다 {limit} 회입니다."),
    "ligands.count": ("這個流程有 {value} 個配體，Lite 一次最多 {limit} 個。", "This workflow has {value} ligands. Lite takes up to {limit} at a time.",
                      "このワークフローにはリガンドが {value} 個あります。Lite は一度に {limit} 個までです。", "이 워크플로에는 리간드가 {value} 개 있습니다. Lite는 한 번에 {limit} 개까지입니다."),
    "binding.replicas": ("每個配體的獨立拉離設為 {value} 次，Lite 做 {limit} 次。", "{value} independent pulls per ligand are requested. Lite does {limit}.",
                         "リガンドごとの独立した引き離しが {value} 回に設定されています。Lite は {limit} 回です。", "리간드마다 독립 당김이 {value} 회로 설정되어 있습니다. Lite는 {limit} 회입니다."),
    "binding.max_windows": ("傘狀採樣窗口上限設為 {value} 個，Lite 最多 {limit} 個。", "Up to {value} umbrella windows are requested. Lite uses up to {limit}.",
                            "アンブレラサンプリングのウィンドウ上限が {value} 個になっています。Lite は {limit} 個までです。", "엄브렐라 샘플링 윈도우 상한이 {value} 개입니다. Lite는 {limit} 개까지입니다."),
    "binding.window_ps": ("每個窗口取樣 {value} ps，Lite 每個窗口最長 {limit} ps。", "Each window samples {value} ps. Lite samples up to {limit} ps per window.",
                          "各ウィンドウのサンプリングが {value} ps です。Lite は一つのウィンドウにつき {limit} ps までです。", "윈도우마다 {value} ps를 샘플링합니다. Lite는 윈도우마다 {limit} ps까지입니다."),
    "binding.refine_rounds": ("自動補窗口設為 {value} 輪，Lite 不自動補窗口。", "{value} automatic refinement rounds are requested. Lite does not add windows by itself.",
                              "ウィンドウの自動追加が {value} 回に設定されています。Lite は自動で追加しません。", "윈도우 자동 추가가 {value} 회로 설정되어 있습니다. Lite는 자동으로 추가하지 않습니다."),
    "screen.compounds": ("化合物庫有 {value} 筆，Lite 一次篩選 {limit} 筆。", "The library has {value} compounds. Lite screens {limit} in one run.",
                         "ライブラリには化合物が {value} 件あります。Lite は一度に {limit} 件までです。", "라이브러리에 화합물이 {value} 건 있습니다. Lite는 한 번에 {limit} 건까지입니다."),
    "system.atoms": ("這個系統有 {value} 個原子，Lite 的上限是 {limit} 個。", "This system has {value} atoms. The Lite limit is {limit}.",
                     "この系の原子数は {value} です。Lite の上限は {limit} です。", "이 시스템의 원자 수는 {value} 개입니다. Lite의 상한은 {limit} 개입니다."),
    "system.residues": ("這個蛋白有 {value} 個殘基，Lite 的上限是 {limit} 個。", "This protein has {value} residues. The Lite limit is {limit}.",
                        "このタンパク質の残基数は {value} です。Lite の上限は {limit} です。", "이 단백질의 잔기 수는 {value} 개입니다. Lite의 상한은 {limit} 개입니다."),
    "feature": ("這個設定用到「{title}」，Lite 沒有這項功能。", "This configuration uses {title}, which Lite does not include.",
                "この設定は「{title}」を使いますが、Lite にはこの機能がありません。", "이 설정은 {title} 기능을 사용하지만 Lite에는 이 기능이 없습니다."),
}

# binding.config defaults the checks need when the config leaves them out (kept equal to BindingConfig; a test compares)
_BINDING_DEFAULTS = {"max_windows": 40, "window_prod_ps": 50.0, "max_refine_rounds": 6}
# production length of each md.tier in ns when md.production_ns is not set (kept equal to engine.protocol.TIERS; a test compares)
_TIER_NS = {"classroom": 2.0, "teaching": 10.0, "research": 100.0}
_DEFAULT_TIER = "teaching"


def _ligand_uses_fold(l: dict) -> bool:
    """`ligands[i].fold` asks for a structure prediction from the sequence (md20/build/fold.py)."""
    return isinstance(l, dict) and bool(l.get("fold"))


def check_config(cfg: dict, edition: str | None = None) -> list[Hit]:
    """Everything in a workflow config that goes beyond the edition, decided from the config alone, so the check can sit
    at the entrance and change nothing in the science.  Empty for the complete edition."""
    lim = limits(edition)
    if lim == LIMITS[FULL]:
        return []
    cfg = cfg or {}
    md = cfg.get("md") or {}
    b = cfg.get("binding") or {}
    bc = b.get("config") or {}
    hits: list[Hit] = []

    # complete-only features
    if md.get("membrane"):
        hits.append(Hit("feature.membrane", FEATURE, feature="membrane"))
    if md.get("resolution") == "cg":
        hits.append(Hit("feature.cg", FEATURE, feature="cg"))
    if any(_ligand_uses_fold(l) for l in cfg.get("ligands") or []):
        hits.append(Hit("feature.fold", FEATURE, feature="fold"))
    if md.get("long_run") or md.get("long_run_confirmed"):
        hits.append(Hit("feature.long_run", FEATURE, feature="long_run"))
    if cfg.get("autonomy"):
        hits.append(Hit("feature.autonomy", FEATURE, feature="autonomy"))

    # sizes
    tier = md.get("tier") or _DEFAULT_TIER
    if lim.md_tiers is not None and tier not in lim.md_tiers:
        hits.append(Hit("md.tier", SCALE, tier, list(lim.md_tiers), "long_run", True))
    ns = md.get("production_ns")
    ns = float(ns) if ns is not None else _TIER_NS.get(tier if (lim.md_tiers is None or tier in lim.md_tiers) else lim.md_tiers[-1])
    if lim.max_production_ns is not None and ns is not None and ns > lim.max_production_ns:
        hits.append(Hit("md.production_ns", SCALE, ns, lim.max_production_ns, "long_run", True))
    rep = md.get("replicas")
    if lim.max_replicas is not None and isinstance(rep, int) and not isinstance(rep, bool) and rep > lim.max_replicas:
        hits.append(Hit("md.replicas", SCALE, rep, lim.max_replicas, "replicas", True))
    n_lig = len(cfg.get("ligands") or [])
    if lim.max_ligands is not None and n_lig > lim.max_ligands:
        hits.append(Hit("ligands.count", SCALE, n_lig, lim.max_ligands, "multi_ligand_full", False))
    if b.get("enabled") or b.get("added") or b.get("alone"):
        tr = b.get("target_replicas")
        vals = [v for v in (tr.values() if isinstance(tr, dict) else [tr, b.get("replicas")])
                if isinstance(v, int) and not isinstance(v, bool)]
        if lim.max_binding_replicas is not None and vals and max(vals) > lim.max_binding_replicas:
            hits.append(Hit("binding.replicas", SCALE, max(vals), lim.max_binding_replicas, "binding_full", True))
        mw = bc.get("max_windows", _BINDING_DEFAULTS["max_windows"])
        if lim.max_windows is not None and mw > lim.max_windows:
            hits.append(Hit("binding.max_windows", SCALE, mw, lim.max_windows, "binding_full", True))
        wp = float(bc.get("window_prod_ps", _BINDING_DEFAULTS["window_prod_ps"]))
        if lim.max_window_ps is not None and wp > lim.max_window_ps:
            hits.append(Hit("binding.window_ps", SCALE, wp, lim.max_window_ps, "binding_full", True))
        rr = bc.get("max_refine_rounds", _BINDING_DEFAULTS["max_refine_rounds"])
        if lim.max_refine_rounds is not None and rr > lim.max_refine_rounds:
            hits.append(Hit("binding.refine_rounds", SCALE, rr, lim.max_refine_rounds, "binding_full", True))
    return hits


def clamp_config(cfg: dict, edition: str | None = None) -> tuple[dict, list[dict]]:
    """A copy of the config brought under the size limits, and the list of changes ({key, from, to, code}).
    Only sizes are reduced.  Complete-only features and the number of ligands are left alone: which feature to drop
    and which ligands to keep is the user's choice."""
    lim = limits(edition)
    out = copy.deepcopy(cfg or {})
    changes: list[dict] = []

    def put(path: tuple, new, code: str) -> None:
        node = out
        for k in path[:-1]:
            nxt = node.get(k)
            if not isinstance(nxt, dict):
                nxt = node[k] = {}
            node = nxt
        old = node.get(path[-1])
        if old != new:
            node[path[-1]] = new
            changes.append({"key": ".".join(path), "from": old, "to": new, "code": code})

    for h in check_config(out, edition):
        if not h.can_clamp:
            continue
        if h.code == "md.tier":
            put(("md", "tier"), lim.md_tiers[-1], h.code)
        elif h.code == "md.production_ns":
            put(("md", "production_ns"), lim.max_production_ns, h.code)
        elif h.code == "md.replicas":
            put(("md", "replicas"), lim.max_replicas, h.code)
        elif h.code == "binding.replicas":
            b = out.setdefault("binding", {})
            tr = b.get("target_replicas")
            if isinstance(tr, dict):
                put(("binding", "target_replicas"), {k: min(v, lim.max_binding_replicas) if isinstance(v, int) else v
                                                    for k, v in tr.items()}, h.code)
            elif isinstance(tr, int):
                put(("binding", "target_replicas"), lim.max_binding_replicas, h.code)
            if isinstance(b.get("replicas"), int) and b["replicas"] > lim.max_binding_replicas:
                put(("binding", "replicas"), lim.max_binding_replicas, h.code)
        elif h.code == "binding.max_windows":
            put(("binding", "config", "max_windows"), lim.max_windows, h.code)
        elif h.code == "binding.window_ps":
            put(("binding", "config", "window_prod_ps"), lim.max_window_ps, h.code)
        elif h.code == "binding.refine_rounds":
            put(("binding", "config", "max_refine_rounds"), lim.max_refine_rounds, h.code)
    # a tier change can leave the production length above the limit (or bring it under it): check once more
    for h in check_config(out, edition):
        if h.code == "md.production_ns":
            put(("md", "production_ns"), lim.max_production_ns, h.code)
    return out, changes


def check_system(*, n_atoms: int | None = None, n_protein_residues: int | None = None, solvent: str = "explicit",
                 edition: str | None = None) -> list[Hit]:
    """Size of a built system against the edition.  Called after the build, when the atom count is known."""
    lim = limits(edition)
    hits: list[Hit] = []
    cap = lim.max_atoms_implicit if solvent == "gbn2" else lim.max_atoms
    if cap is not None and n_atoms is not None and n_atoms > cap:
        hits.append(Hit("system.atoms", SCALE, int(n_atoms), cap, "large_system", False, {"solvent": solvent}))
    if lim.max_protein_residues is not None and n_protein_residues is not None and n_protein_residues > lim.max_protein_residues:
        hits.append(Hit("system.residues", SCALE, int(n_protein_residues), lim.max_protein_residues, "large_system", False))
    return hits


def check_library(n_compounds: int, edition: str | None = None) -> list[Hit]:
    """Size of a screening library against the edition."""
    lim = limits(edition)
    if lim.max_screen_compounds is not None and n_compounds > lim.max_screen_compounds:
        return [Hit("screen.compounds", SCALE, int(n_compounds), lim.max_screen_compounds, "screen_full", False)]
    return []


# ---------------------------------------------------------------------------------------------- report and interface
def comparison_rows(lang: str = "en") -> list[dict]:
    """Lite next to the complete edition, one row per limit, for the report and the interface."""
    lite, none = LIMITS[LITE], pick(("不限", "no limit", "制限なし", "제한 없음"), lang)
    rows = [
        (("每個系統的原子數", "Atoms per system", "一つの系の原子数", "시스템당 원자 수"), f"{lite.max_atoms:,}"),
        (("蛋白殘基數", "Protein residues", "タンパク質の残基数", "단백질 잔기 수"), str(lite.max_protein_residues)),
        (("同一流程的配體數", "Ligands in one workflow", "一つのワークフローのリガンド数", "한 워크플로의 리간드 수"), str(lite.max_ligands)),
        (("一次篩選的化合物數", "Compounds screened in one run", "一度にスクリーニングする化合物数", "한 번에 스크리닝하는 화합물 수"), str(lite.max_screen_compounds)),
        (("正式模擬長度", "Production length", "本計算の長さ", "본 계산 길이"), f"{lite.max_production_ns:g} ns"),
        (("每個系統的獨立重複", "Independent repeats per system", "一つの系の独立した繰り返し", "시스템당 독립 반복"), str(lite.max_replicas)),
        (("傘狀採樣窗口數", "Umbrella windows", "アンブレラサンプリングのウィンドウ数", "엄브렐라 샘플링 윈도우 수"), str(lite.max_windows)),
    ]
    return [{"item": pick(t, lang), "lite": v, "full": none} for t, v in rows]


def summary(lang: str = "en") -> dict:
    """What the interface needs to draw the edition badge, the locked features and the comparison table."""
    ed = current()
    return {"edition": ed, "name": name(ed, lang), "limits": limits(ed).as_dict(),
            "locked": [{"id": f.id, "title": pick(f.title, lang), "gain": pick(f.gain, lang), "preview": f.preview}
                       for f in PRO_FEATURES] if ed == LITE else [],
            "comparison": comparison_rows(lang) if ed == LITE else [],
            "how_to_upgrade": pick(HOW_TO_UPGRADE, lang) if ed == LITE else ""}
