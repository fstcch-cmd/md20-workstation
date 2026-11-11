"""What MD20 Lite looks like in the interface (D-181), as pure logic without NiceGUI.

Three things have to be true, and none of them may nag:
  * the person always knows this is Lite (`badge`);
  * the person can see what the complete edition has (`editions_page`, `preview_page`, `locked_features`);
  * when a setting goes beyond Lite, the person learns it at that moment, with a way forward
    (`field_limits`, `validate_setting`, `advanced_issues`, `config_hits`).

Every function asks `md20.edition` and nothing else for what an edition is, so no limit or feature list is written here.
The wording of a limit comes from `edition.Hit.text`.  In the complete edition every function returns an empty value
(None, an empty list or dict) and the interface is the one it always was.

Text: (zh, en, ja, ko) tuples in the plain wording of docs/specs/writing_style.md.
"""
from __future__ import annotations

import copy
import json

from .. import edition as E
from ..i18n import pick, colon, LANGS

# ------------------------------------------------------------------------------------------------------ text
TEXT = {
    "badge": ("Lite 版", "Lite", "Lite 版", "Lite 판"),
    "badge_hint": ("你正在使用 MD20 Lite。點一下，看看完整版多了什麼。",
                   "You are using MD20 Lite. Select to see what the complete edition adds.",
                   "MD20 Lite を使っています。クリックすると完全版の内容を確認できます。",
                   "MD20 Lite를 사용 중입니다. 눌러서 정식판에 더해지는 것을 확인하십시오."),
    "tag": ("完整版", "Complete edition", "完全版", "정식판"),
    # the editions page
    "ed_title": ("版本比較", "Editions", "エディションの比較", "판 비교"),
    "ed_intro": ("你現在用的是 MD20 Lite。它會從對接、分子動力學、快速 PMF 一路做到報告，只是規模有上限。"
                 "在上限之內，Lite 算出的結果是正確的。",
                 "You are using MD20 Lite. It runs the whole route once, from docking through molecular dynamics and a "
                 "quick PMF to the report, at a limited size. Within its limits the results are correct.",
                 "いまお使いなのは MD20 Lite です。ドッキング、分子動力学、簡易 PMF からレポートまでを一通り実行でき、"
                 "規模に上限があります。上限の範囲内では、結果は正しく出ます。",
                 "지금 MD20 Lite를 사용 중입니다. 도킹, 분자동역학, 빠른 PMF를 거쳐 보고서까지 전 과정을 실행하며 "
                 "규모에만 상한이 있습니다. 상한 안에서는 결과가 올바르게 나옵니다."),
    "col_item": ("項目", "Item", "項目", "항목"),
    "col_lite": ("Lite", "Lite", "Lite", "Lite"),
    "col_full": ("完整版", "Complete edition", "完全版", "정식판"),
    "features_title": ("只有完整版才有的功能", "Only in the complete edition", "完全版だけにある機能", "정식판에만 있는 기능"),
    "features_intro": ("Lite 沒有這些功能。每一項做什麼，寫在下面。",
                       "Lite does not include these features. Each one is described below.",
                       "これらの機能は Lite にはありません。それぞれの内容を下に書きます。",
                       "이 기능들은 Lite에 없습니다. 각 기능이 하는 일을 아래에 적었습니다."),
    "about_feature": ("了解這個功能", "About this feature", "この機能について", "이 기능 알아보기"),
    "upgrade_title": ("取得完整版", "Getting the complete edition", "完全版を入手するには", "정식판 받기"),
    "back": ("回到版本比較", "Back to the editions", "エディションの比較に戻る", "판 비교로 돌아가기"),
    # preview page labels
    "what": ("它做什麼", "What it does", "何をするか", "하는 일"),
    "provide": ("你要提供", "What you provide", "用意するもの", "준비할 것"),
    "get": ("你會得到", "What you get", "得られるもの", "얻는 것"),
    "limits_note": ("要知道的限制", "A limit to know", "知っておく制限", "알아 둘 제한"),
    # pro form
    "lite_cap": ("Lite 上限", "Lite limit", "Lite の上限", "Lite의 상한"),
    "group_link": ("這個功能做什麼", "What this does", "この機能について", "이 기능이 하는 일"),
    # the limit card shown instead of launching
    "card_title": ("這個設定超過 Lite 的範圍", "This setting goes beyond Lite", "この設定は Lite の範囲を超えています",
                   "이 설정은 Lite의 범위를 넘습니다"),
    "card_sub": ("計算還沒有開始。請選一個做法。", "The calculation has not started. Choose how to go on.",
                 "計算はまだ始まっていません。進め方を選んでください。", "계산은 아직 시작되지 않았습니다. 진행 방법을 고르십시오."),
    "can_clamp": ("可以自動縮小", "Can be reduced automatically", "自動で縮小できます", "자동으로 줄일 수 있음"),
    "needs_you": ("需要你決定", "Needs your decision", "判断が必要", "결정 필요"),
    "changes_title": ("縮小後的設定", "Settings after the reduction", "縮小後の設定", "축소 후 설정"),
    "change_line": ("{label}：{old}，改成 {new}", "{label}: {old}, changed to {new}", "{label}：{old}、変更後は {new}",
                    "{label}: {old}, 변경 후 {new}"),
    "partial": ("標示「需要你決定」的項目，自動縮小解決不了。請修改設定，或用完整版打開這個專案。",
                "Reducing sizes cannot solve the items marked as needing your decision. Change the settings, or open the "
                "project in the complete edition.",
                "「判断が必要」と表示した項目は、自動の縮小では解決できません。設定を変更するか、完全版でこのプロジェクトを開いてください。",
                "'결정 필요'로 표시한 항목은 자동 축소로 해결할 수 없습니다. 설정을 바꾸거나 정식판에서 이 프로젝트를 여십시오."),
    "clamp_label": ("自動縮小設定後繼續", "Reduce the settings automatically and continue", "設定を自動で縮小して続ける",
                    "설정을 자동으로 줄이고 계속"),
    "clamp_text": ("MD20 只縮小上面列出的規模，每一項改動都記在決策紀錄。配體和功能都不會被拿掉。",
                   "MD20 reduces only the sizes listed above and records each change in the decision log. No ligand or "
                   "feature is removed.",
                   "MD20 は上に挙げた規模だけを縮小し、変更ごとに決定ログへ記録します。リガンドも機能も取り除きません。",
                   "MD20은 위에 나열한 규모만 줄이고 변경마다 결정 기록에 남깁니다. 리간드와 기능은 제거하지 않습니다."),
    "edit_label": ("修改設定", "Change the settings", "設定を変更する", "설정 바꾸기"),
    "edit_text": ("回到設定頁，把超出的項目改到 Lite 的範圍內。剛建立的流程會保留，還沒有開始計算。",
                  "Go back to the settings and bring the items above within Lite. The workflow you just created is kept and "
                  "has not started.",
                  "設定のページに戻り、超えている項目を Lite の範囲内に直します。作成したワークフローは残り、まだ計算は始まっていません。",
                  "설정 페이지로 돌아가 넘은 항목을 Lite의 범위 안으로 고치십시오. 방금 만든 워크플로는 남아 있고 아직 계산하지 않았습니다."),
    "open_label": ("用完整版打開這個專案", "Open this project in the complete edition", "このプロジェクトを完全版で開く",
                   "이 프로젝트를 정식판에서 열기"),
    "open_text": ("專案資料夾在完整版裡原樣打開，不用轉換，已經算完的部分會保留。",
                  "The project folder opens as it is in the complete edition, with nothing to convert, and what has been "
                  "computed is kept.",
                  "プロジェクトのフォルダーは完全版でそのまま開け、変換は要りません。計算済みの部分は残ります。",
                  "프로젝트 폴더는 정식판에서 그대로 열리며 변환이 필요 없습니다. 이미 계산한 부분은 남습니다."),
    "folder": ("專案資料夾", "Project folder", "プロジェクトのフォルダー", "프로젝트 폴더"),
    "learn_label": ("完整版有什麼", "What the complete edition has", "完全版の内容", "정식판 내용"),
    "copy": ("複製路徑", "Copy the path", "パスをコピー", "경로 복사"),
    "started": ("已縮小設定並開始計算。", "The settings were reduced and the calculation has started.",
                "設定を縮小して計算を始めました。", "설정을 줄이고 계산을 시작했습니다."),
    # quick preview with implicit solvent
    "gbn2_label": ("快速預覽（隱式溶劑）", "Quick preview with implicit solvent", "クイックプレビュー（陰溶媒）",
                   "빠른 미리보기(암시적 용매)"),
    "gbn2_caption": ("只看結構和動態。結果只作描述，不能和顯式水的結果或文獻值直接比較。結合自由能需要顯式水。",
                     "Structure and dynamics only. The results are descriptive, and they cannot be compared directly with "
                     "explicit-water or published values. Binding free energy needs explicit water.",
                     "構造と動きだけを見ます。結果は記述的なもので、陽溶媒の結果や文献値と直接比べることはできません。"
                     "結合自由エネルギーには陽溶媒が必要です。",
                     "구조와 움직임만 봅니다. 결과는 서술용이며 명시적 물의 결과나 문헌 값과 직접 비교할 수 없습니다. "
                     "결합 자유 에너지에는 명시적 물이 필요합니다."),
}


def _t(key: str, lang: str) -> str:
    return pick(TEXT[key], lang)


def _sep(lang: str) -> str:
    return "" if lang in ("zh", "ja") else " "


def is_lite() -> bool:
    """True when the edition in effect is Lite.  Asks `md20.edition`; nothing here decides it."""
    return E.current() == E.LITE


def css() -> str:
    """Styles for the edition elements, using the tokens of gui/theme.py.  Empty in the complete edition, so its pages
    carry no extra rule."""
    if not is_lite():
        return ""
    return """<style>
.md20-header a.md20-edbadge { display: inline-flex; align-items: center; padding: 1px 10px; margin-left: 4px;
  border: 1px solid var(--md20-primary); border-radius: 999px; background: var(--md20-primary-soft);
  color: var(--md20-primary) !important; font-size: 12.5px; font-weight: 650; line-height: 20px; }
.md20-header a.md20-edbadge:hover { background: var(--md20-surface); }
.md20-edtag { display: inline-block; padding: 0 8px; border: 1px solid var(--md20-line-strong); border-radius: 999px;
  color: var(--md20-ink-muted); font-size: 12px; line-height: 18px; white-space: nowrap; vertical-align: middle; }
.md20-edlimit { color: var(--md20-ink-muted); font-size: 12.5px; line-height: 1.5; max-width: 72ch; }
.md20-edlimit--over { color: var(--md20-needs); }
.md20-edhit { border-top: 1px solid var(--md20-line); padding: 8px 0 8px 0; }
.md20-edhit:first-of-type { border-top: 0; }
.md20-edrow { border-top: 1px solid var(--md20-line); padding: 12px 0; }
.md20-edrow:first-of-type { border-top: 0; }
.md20-edup { background: var(--md20-primary-soft); border: 1px solid var(--md20-line); border-radius: var(--md20-r-section);
  padding: 14px 18px; }
.md20-edfig { max-width: 560px; border: 1px solid var(--md20-line); border-radius: var(--md20-r-section); }
</style>"""


# ------------------------------------------------------------------------------------------------------ badge and lists
def badge(lang: str = "en") -> str | None:
    """Header badge text, or None in the complete edition."""
    return _t("badge", lang) if is_lite() else None


def badge_hint(lang: str = "en") -> str | None:
    return _t("badge_hint", lang) if is_lite() else None


def tag(lang: str = "en") -> str | None:
    """Small tag shown next to a complete-only entry, or None in the complete edition."""
    return _t("tag", lang) if is_lite() else None


def locked_features(lang: str = "en") -> list[dict]:
    """The complete-only features for the interface, from `edition.summary(lang)["locked"]`.  Empty in the complete
    edition.  Each entry also carries the tag text and, for the features that have a description page, its href."""
    out = []
    for f in E.summary(lang)["locked"]:
        out.append({**f, "tag": _t("tag", lang), "href": f"/edition/{f['id']}" if f["preview"] else None})
    return out


def editions_page(lang: str = "en") -> dict:
    """Everything the Editions page shows.  Empty in the complete edition."""
    if not is_lite():
        return {}
    s = E.summary(lang)
    return {"title": _t("ed_title", lang), "intro": _t("ed_intro", lang), "edition": s["name"],
            "columns": [{"name": "item", "label": _t("col_item", lang)}, {"name": "lite", "label": _t("col_lite", lang)},
                        {"name": "full", "label": _t("col_full", lang)}],
            "rows": s["comparison"], "features_title": _t("features_title", lang),
            "features_intro": _t("features_intro", lang), "features": locked_features(lang),
            "about_label": _t("about_feature", lang), "upgrade_title": _t("upgrade_title", lang),
            "upgrade": s["how_to_upgrade"], "back": _t("back", lang)}


# ------------------------------------------------------------------------------------------------------ field limits
def _lim():
    return E.limits()


def _tiers_text(tiers, lang: str) -> str:
    from .. import advisor
    return ", ".join(advisor.choice_label("tier", t, lang) for t in tiers)


_HELP = {
    "production_ns": ("Lite 最長 {n} ns。", "Lite runs up to {n} ns.", "Lite は {n} ns までです。", "Lite는 {n} ns까지 계산합니다."),
    "tier": ("Lite 可以選的等級：{n}。", "Tiers Lite offers: {n}.", "Lite で選べる等級：{n}。", "Lite에서 고를 수 있는 등급: {n}."),
    "replicas": ("Lite 每個系統跑 {n} 次。", "Lite runs {n} per system.", "Lite は一つの系につき {n} 回です。",
                 "Lite는 시스템마다 {n} 회 실행합니다."),
    "ligands": ("Lite 一個流程最多 {n} 個配體。", "Lite takes up to {n} ligands in one workflow.",
                "Lite は一つのワークフローにつきリガンド {n} 個までです。", "Lite는 워크플로 하나에 리간드를 {n} 개까지 받습니다."),
    "library": ("Lite 一次篩選最多 {n} 筆化合物。", "Lite screens up to {n} compounds in one run.",
                "Lite は一度に化合物 {n} 件までスクリーニングします。", "Lite는 한 번에 화합물 {n} 건까지 스크리닝합니다."),
    "max_windows": ("傘狀採樣最多 {n} 個窗口。", "Umbrella sampling uses up to {n} windows.",
                    "アンブレラサンプリングのウィンドウは {n} 個までです。", "엄브렐라 샘플링 윈도우는 {n} 개까지입니다."),
    "window_prod_ps": ("每個窗口最長取樣 {n} ps。", "Each window samples up to {n} ps.",
                       "一つのウィンドウのサンプリングは {n} ps までです。", "윈도우마다 {n} ps까지 샘플링합니다."),
    "binding_replicas": ("每個配體獨立拉離 {n} 次。", "Each ligand gets {n} independent pull.",
                         "リガンドごとの独立した引き離しは {n} 回です。", "리간드마다 독립 당김을 {n} 회 합니다."),
}
_HELP_REFINE_NONE = ("不會自動補窗口。", "Windows are not added automatically.", "ウィンドウは自動で追加しません。",
                     "윈도우를 자동으로 추가하지 않습니다.")
_HELP_REFINE_SOME = ("自動補窗口最多 {n} 輪。", "Windows are added automatically for up to {n} rounds.",
                     "ウィンドウの自動追加は {n} 回までです。", "윈도우 자동 추가는 {n} 회까지입니다.")
_HELP_BINDING_PLURAL_EN = "Each ligand gets {n} independent pulls."


def _help(key: str, n, lang: str) -> str:
    if key == "max_refine_rounds":
        return pick(_HELP_REFINE_NONE if not n else _HELP_REFINE_SOME, lang).format(n=n)
    if key == "binding_replicas" and lang == "en" and n != 1:
        return _HELP_BINDING_PLURAL_EN.format(n=n)
    return pick(_HELP[key], lang).format(n=n)


def field_limits(lang: str = "en") -> dict[str, dict]:
    """For each input that has a Lite limit: {"limit": the limit, "help": short text under the field}.  The keys are the
    field ids of the forms (`production_ns`, `tier`, `replicas`, `window_prod_ps` are advisor parameters; `ligands` is the
    ligand box; `library` the screening library upload; `max_windows`, `max_refine_rounds` and `binding_replicas` are the
    binding settings that have no field of their own; `binding` is the binding switch, whose text sums them up).
    Empty in the complete edition."""
    if not is_lite():
        return {}
    L = _lim()
    out: dict[str, dict] = {}

    def put(key, limit, text):
        out[key] = {"limit": limit, "help": text}
    if L.max_production_ns is not None:
        put("production_ns", L.max_production_ns, _help("production_ns", f"{L.max_production_ns:g}", lang))
    if L.md_tiers is not None:
        put("tier", list(L.md_tiers), _help("tier", _tiers_text(L.md_tiers, lang), lang))
    if L.max_replicas is not None:
        put("replicas", L.max_replicas, _help("replicas", L.max_replicas, lang))
    if L.max_ligands is not None:
        put("ligands", L.max_ligands, _help("ligands", L.max_ligands, lang))
    if L.max_screen_compounds is not None:
        put("library", L.max_screen_compounds, _help("library", L.max_screen_compounds, lang))
    if L.max_windows is not None:
        put("max_windows", L.max_windows, _help("max_windows", L.max_windows, lang))
    if L.max_window_ps is not None:
        put("window_prod_ps", L.max_window_ps, _help("window_prod_ps", f"{L.max_window_ps:g}", lang))
    if L.max_binding_replicas is not None:
        put("binding_replicas", L.max_binding_replicas, _help("binding_replicas", L.max_binding_replicas, lang))
    if L.max_refine_rounds is not None:
        put("max_refine_rounds", L.max_refine_rounds, _help("max_refine_rounds", L.max_refine_rounds, lang))
    parts = [out[k]["help"] for k in ("max_windows", "window_prod_ps", "binding_replicas", "max_refine_rounds") if k in out]
    if parts:
        put("binding", {k: out[k]["limit"] for k in ("max_windows", "window_prod_ps", "binding_replicas", "max_refine_rounds")
                        if k in out}, _sep(lang).join(parts))
    return out


# validate_setting: field id -> (a mini config that holds the value, the code of the hit that belongs to the field)
def _mini(key: str, value):
    if key == "production_ns":
        return {"md": {"production_ns": float(value)}}, "md.production_ns"
    if key == "tier":
        return {"md": {"tier": str(value)}}, "md.tier"
    if key == "replicas":
        return {"md": {"replicas": int(float(value))}}, "md.replicas"
    if key == "ligands":
        n = len(value) if isinstance(value, (list, tuple)) else int(float(value))
        return {"ligands": [{} for _ in range(n)]}, "ligands.count"
    if key == "window_prod_ps":
        return {"binding": {"enabled": True, "config": {"window_prod_ps": float(value)}}}, "binding.window_ps"
    if key == "max_windows":
        return {"binding": {"enabled": True, "config": {"max_windows": int(float(value))}}}, "binding.max_windows"
    if key == "max_refine_rounds":
        return {"binding": {"enabled": True, "config": {"max_refine_rounds": int(float(value))}}}, "binding.refine_rounds"
    if key == "binding_replicas":
        return {"binding": {"enabled": True, "target_replicas": int(float(value))}}, "binding.replicas"
    raise KeyError(key)


def validate_setting(key: str, value, lang: str = "en") -> str | None:
    """None when the value is within Lite (or the edition has no limit on it), otherwise the message, built from
    `edition.check_config` or `edition.check_library` so the wording stays in `edition.py`."""
    if not is_lite() or value is None or value == "":
        return None
    try:
        if key == "library":
            hits = E.check_library(int(float(value)))
        else:
            cfg, code = _mini(key, value)
            hits = [h for h in E.check_config(cfg) if h.code == code]
    except (KeyError, TypeError, ValueError):
        return None
    return hits[0].text(lang) if hits else None


_LITE_PATH = {"tier": "md.tier", "production_ns": "md.production_ns", "replicas": "md.replicas",
              "window_prod_ps": "binding.config.window_prod_ps"}


def lite_value(key: str, value):
    """The value the forms start a field with: the recommendation itself, or, in Lite, the Lite limit when the
    recommendation is above it (`edition.clamp_config` decides; nothing is chosen here).  The form then says so next to
    the field and still shows the recommendation, so the reduction is visible and a person who types a higher value
    gets the message and the limit card.  The complete edition: the value unchanged."""
    if not is_lite() or value is None or key not in _LITE_PATH:
        return value
    try:
        cfg, _ = _mini(key, value)
        for c in E.clamp_config(cfg)[1]:
            if c["key"] == _LITE_PATH[key]:
                return c["to"]
    except (KeyError, TypeError, ValueError):
        pass
    return value


def advanced_issues(adv: dict, ligands: list[dict], lang: str = "en") -> list[dict]:
    """Complete-only features the professional form has switched on (membrane, coarse-grained, folding), in the shape of
    the plausibility panel's issues.  They are warnings, not errors: the start button still leads to the limit card,
    which has the ways forward."""
    if not is_lite():
        return []
    from . import advanced as A
    cfg: dict = {"md": {}, "ligands": []}
    spec = A.membrane_spec(adv or {})
    if spec:
        cfg["md"]["membrane"] = spec
    if (adv or {}).get("resolution") == "cg":
        cfg["md"]["resolution"] = "cg"
    if (adv or {}).get("fold", "off") != "off" and A.peptide_names(ligands or []):
        cfg["ligands"] = [{"fold": True}]
    return [{"level": "warning", "key": h.code, "label": E.name(E.LITE, lang), "message": h.text(lang), "suggestion": None}
            for h in E.check_config(cfg) if h.kind == E.FEATURE]


def form_binding_defaults() -> dict:
    """Binding settings the forms have no field for (number of windows, automatic extra windows), at the Lite limits.
    The forms write them into a new Lite workflow so that the person is not asked about a setting they never saw; the
    helper text under the binding switch tells them.  Empty in the complete edition, whose defaults stay as they are."""
    if not is_lite():
        return {}
    L = _lim()
    out = {}
    if L.max_windows is not None:
        out["max_windows"] = L.max_windows
    if L.max_refine_rounds is not None:
        out["max_refine_rounds"] = L.max_refine_rounds
    return out


# ------------------------------------------------------------------------------------------------------ the limit card
_CHANGE_LABELS = {
    "md.tier": ("tier",), "md.production_ns": ("production_ns",), "md.replicas": ("replicas",),
    "binding.config.window_prod_ps": ("window_prod_ps",),
    "binding.config.max_windows": ("傘狀採樣窗口數的上限", "Umbrella windows at most", "アンブレラサンプリングのウィンドウ数の上限",
                                   "엄브렐라 샘플링 윈도우 수 상한"),
    "binding.config.max_refine_rounds": ("自動補窗口的輪數", "Automatic window refinement rounds", "ウィンドウ自動追加の回数",
                                         "윈도우 자동 추가 횟수"),
    "binding.target_replicas": ("每個配體的獨立拉離次數", "Independent pulls per ligand", "リガンドごとの独立した引き離しの回数",
                                "리간드마다 독립 당김 횟수"),
    "binding.replicas": ("每個配體的獨立拉離次數", "Independent pulls per ligand", "リガンドごとの独立した引き離しの回数",
                         "리간드마다 독립 당김 횟수"),
}
_UNITS = {"md.production_ns": "ns", "binding.config.window_prod_ps": "ps"}


def _value_text(key: str, v, lang: str) -> str:
    from .. import advisor
    if key == "md.tier":
        return advisor.choice_label("tier", v, lang)
    if isinstance(v, dict):
        return ", ".join(f"{k} {x}" for k, x in v.items())
    if v is None:
        return "-"
    txt = f"{v:g}" if isinstance(v, float) else str(v)
    return f"{txt} {_UNITS[key]}" if key in _UNITS else txt


def change_lines(changes: list[dict], lang: str = "en") -> list[str]:
    """One plain line for each reduction `edition.clamp_config` would make."""
    from .. import advisor
    out = []
    for c in changes:
        spec = _CHANGE_LABELS.get(c["key"])
        label = advisor.param_label(spec[0], lang) if spec and len(spec) == 1 else pick(spec, lang) if spec else c["key"]
        out.append(pick(TEXT["change_line"], lang).format(label=label, old=_value_text(c["key"], c["from"], lang),
                                                          new=_value_text(c["key"], c["to"], lang)))
    return out


def config_hits(cfg: dict, lang: str = "en", folder: str | None = None) -> dict:
    """What the start action shows before it launches.  Empty ({}) when nothing goes beyond the edition, which is always
    the case in the complete edition.  Otherwise:

      hits     every limit met: {code, kind, feature, text, can_clamp, state}  (state: "autofix" or "needs")
      clearable  True when reducing the sizes would leave nothing behind
      changes  the reductions that `edition.clamp_config` would make, as plain lines
      choices  what the person can do: "clamp" (only when it clears everything and sets `edition.accept_clamp`), "edit",
               "open_full" (explains that the project folder opens as it is, with `folder` when known) and "learn"
      upgrade  the one line on how to get the complete edition

    A config that already carries `edition.accept_clamp` is judged as the workflow will see it: after the reduction, so
    only what a reduction cannot clear is left."""
    if not is_lite():
        return {}
    cfg = cfg or {}
    work, changes = (E.clamp_config(cfg) if E.accepted(cfg) else (cfg, []))
    hits = E.check_config(work)
    if not hits:
        return {}
    reduced, plan = E.clamp_config(cfg)
    clearable = not E.check_config(reduced)
    rows = [{"code": h.code, "kind": h.kind, "feature": h.feature, "text": h.text(lang), "can_clamp": h.can_clamp,
             "state": "autofix" if h.can_clamp else "needs",
             "tag": _t("can_clamp" if h.can_clamp else "needs_you", lang)} for h in hits]
    choices = []
    show_clamp = clearable and not E.accepted(cfg)
    if show_clamp:
        choices.append({"id": "clamp", "label": _t("clamp_label", lang), "text": _t("clamp_text", lang), "primary": True,
                        "decision": {"edition": {"accept_clamp": True}}})
    choices.append({"id": "edit", "label": _t("edit_label", lang), "text": _t("edit_text", lang), "primary": not show_clamp})
    open_text = _t("open_text", lang) + (_sep(lang) + _t("folder", lang) + colon(lang) + str(folder) if folder else "")
    choices.append({"id": "open_full", "label": _t("open_label", lang), "text": open_text, "folder": str(folder) if folder else "",
                    "primary": False})
    choices.append({"id": "learn", "label": _t("learn_label", lang), "text": "", "href": "/edition", "primary": False})
    return {"title": _t("card_title", lang), "sub": _t("card_sub", lang), "hits": rows, "clearable": clearable,
            "changes": change_lines(plan, lang) if show_clamp else [],
            "changes_title": _t("changes_title", lang), "partial": "" if clearable else _t("partial", lang),
            "choices": choices, "upgrade": pick(E.HOW_TO_UPGRADE, lang)}


def accept_clamp(wf, note: str = "") -> dict:
    """The person chose "reduce the settings automatically and continue": write the decision key `edition.accept_clamp`
    to the workflow's config.json and log it as a human decision.  The workflow applies the reduction and logs each
    change when it runs.  Nothing is dropped from the state here."""
    from ..util import atomic_write_json, load_json
    path = wf.dir / "config.json"
    cfg = load_json(path, wf.cfg)
    planned = E.clamp_config(cfg)[1]
    new = copy.deepcopy(cfg)
    node = new.get(E.ACCEPT_KEY[0])
    if not isinstance(node, dict):
        node = new[E.ACCEPT_KEY[0]] = {}
    node[E.ACCEPT_KEY[1]] = True
    atomic_write_json(new, path)
    wf.cfg = new
    what = ("使用者在 Lite 限制卡片選擇自動縮小設定後繼續（edition.accept_clamp）。預計縮小的項目："
            + ("、".join(f"{c['key']} 由 {c['from']} 改為 {c['to']}" for c in planned) or "無")
            + "。縮小由流程執行並逐項記錄，配體與功能不會被拿掉。" + (f" 使用者備註：{note}" if note else ""))
    wf.dec.record("gui.edition", E.ACCEPT_KEY[1], True, what, kind="human",
                  patch=[{"path": list(E.ACCEPT_KEY), "value": True}], planned=planned)
    return {"config": new, "planned": planned}


def copy_js(text: str) -> str:
    """JavaScript that copies `text` to the clipboard (the text is JSON-quoted)."""
    return f"navigator.clipboard.writeText({json.dumps(str(text))})"


# ------------------------------------------------------------------------------------------------------ preview pages
PREVIEW: dict[str, dict] = {
    "membrane": {
        "what": ("膜蛋白，或在細胞膜上作用的胜肽和藥物，周圍需要脂雙層。完整版會建好脂雙層，把你的蛋白放進去，或把胜肽和藥物放在膜表面上方。"
                 "水和離子會一併加好，然後接著做分子動力學。膜的組成可以選，預設溫度是 310 K。",
                 "A membrane protein, or a peptide or drug that acts on a cell membrane, needs a lipid bilayer around it. "
                 "The complete edition builds the bilayer and either sets your protein into it or places the peptide or drug "
                 "above its surface. Water and ions are added, and the molecular dynamics runs from there. You choose the lipid "
                 "composition, and the default temperature is 310 K.",
                 "膜タンパク質や、細胞膜に働くペプチドと薬物には、周りに脂質二重膜が必要です。完全版は脂質二重膜を組み立て、"
                 "タンパク質を埋め込むか、ペプチドや薬物を膜表面の上に置きます。水とイオンを加えたあと、分子動力学まで進めます。"
                 "脂質の組成は選べて、既定の温度は 310 K です。",
                 "막단백질이나 세포막에 작용하는 펩타이드와 약물에는 둘레에 지질 이중층이 필요합니다. 정식판은 지질 이중층을 만들고 "
                 "단백질을 그 안에 넣거나 펩타이드와 약물을 막 표면 위에 놓습니다. 물과 이온을 더한 뒤 분자동역학까지 진행합니다. "
                 "지질 조성을 고를 수 있고 기본 온도는 310 K입니다."),
        "provide": [("蛋白質結構（PDB 編號或檔案），或要放在膜表面的胜肽或小分子",
                     "A protein structure (a PDB ID or a file), or a peptide or small molecule for the membrane surface",
                     "タンパク質の構造（PDB ID またはファイル）、または膜表面に置くペプチドか低分子",
                     "단백질 구조(PDB ID 또는 파일), 또는 막 표면에 놓을 펩타이드나 저분자"),
                    ("脂質組成，例如哺乳類細胞膜或細菌內膜", "A lipid composition, for example a mammalian cell membrane or a bacterial inner membrane",
                     "脂質の組成（例：哺乳類の細胞膜、細菌の内膜）", "지질 조성(예: 포유류 세포막, 세균 내막)"),
                    ("蛋白是否已經依膜的方向擺好", "Whether the protein is already oriented in the membrane",
                     "タンパク質がすでに膜に対する向きで置かれているか", "단백질이 이미 막 방향으로 놓여 있는지")],
        "get": [("可以直接做分子動力學的膜系統", "A membrane system ready for molecular dynamics",
                 "そのまま分子動力学に使える膜の系", "바로 분자동역학에 쓸 수 있는 막 시스템"),
                ("報告裡的膜分析：每個脂質的面積、膜的厚度、膜核心的水", "Membrane analysis in the report: area per lipid, membrane thickness and water in the core",
                 "レポートの膜の解析：脂質一つあたりの面積、膜の厚さ、膜の中心部の水", "보고서의 막 분석: 지질당 면적, 막 두께, 막 중심부의 물")],
        "limits": ("膜系統目前不計算結合自由能。", "Membrane systems do not compute binding free energy yet.",
                   "膜の系では、結合自由エネルギーはまだ計算できません。", "막 시스템에서는 결합 자유 에너지를 아직 계산하지 않습니다."),
        "figure": "membrane",
    },
    "fold": {
        "what": ("胜肽的結構常常不知道。完整版可以讓你直接貼上胜肽序列，由程式預測結構，再接著對接。也可以預測受體和胜肽的複合物，不經過對接。"
                 "預測結果一律標示為預測，並附上可信度檢查。",
                 "The structure of a peptide is often not known. In the complete edition you paste the peptide sequence, the "
                 "program predicts its structure, and docking continues from it. You can also predict the receptor and peptide "
                 "complex and skip docking. The result is always labelled as a prediction and comes with a confidence check.",
                 "ペプチドの構造は分かっていないことがよくあります。完全版ではペプチドの配列を貼り付けるだけで構造を予測し、"
                 "そのままドッキングに進めます。受容体とペプチドの複合体を予測して、ドッキングを省くこともできます。"
                 "結果は必ず予測として表示し、信頼度の確認が付きます。",
                 "펩타이드의 구조는 알려져 있지 않은 경우가 많습니다. 정식판에서는 펩타이드 서열을 붙여 넣으면 구조를 예측하고 "
                 "바로 도킹으로 이어집니다. 수용체와 펩타이드의 복합체를 예측해 도킹을 건너뛸 수도 있습니다. "
                 "결과는 항상 예측으로 표시하며 신뢰도 확인이 함께 나옵니다."),
        "provide": [("胜肽的胺基酸序列", "The amino acid sequence of the peptide", "ペプチドのアミノ酸配列", "펩타이드의 아미노산 서열"),
                    ("預測複合物時，再加上受體的序列", "For a complex, also the sequence of the receptor",
                     "複合体を予測するときは、受容体の配列も", "복합체를 예측할 때는 수용체의 서열도"),
                    ("也可以改交一個你已經有的預測結構檔", "Or a predicted structure file you already have",
                     "すでに持っている予測構造のファイルでも構いません", "이미 가진 예측 구조 파일로 대신할 수도 있음")],
        "get": [("預測的胜肽結構，附每個殘基的可信度", "A predicted peptide structure with a confidence value for each residue",
                 "予測したペプチドの構造と、残基ごとの信頼度", "예측한 펩타이드 구조와 잔기별 신뢰도"),
                ("對接用的起始構形，或可以直接做分子動力學的預測複合物", "A starting conformation for docking, or a predicted complex ready for molecular dynamics",
                 "ドッキング用の初期構造、またはそのまま分子動力学に使える予測複合体", "도킹용 시작 구조, 또는 바로 분자동역학에 쓸 수 있는 예측 복합체")],
        "limits": ("預測用的工具要另外安裝。", "The prediction tools are installed separately.",
                   "予測に使うツールは別にインストールします。", "예측에 쓰는 도구는 따로 설치합니다."),
        "figure": "fold",
    },
}


def preview_page(feature_id: str, lang: str = "en") -> dict | None:
    """The description page of a complete-only feature that has `preview=True`; None for any other id and in the
    complete edition.  Text only.  `figure` names the slot for an example figure: the page shows
    `md20/gui/static/edition/<figure>.png` when that file exists and nothing otherwise, so no result image or number is
    ever made up."""
    if not is_lite():
        return None
    try:
        f = E.pro_feature(feature_id)
    except KeyError:
        return None
    if not f.preview:
        return None
    p = PREVIEW.get(feature_id)
    title = pick(f.title, lang)
    if p is None:                                   # a feature marked preview without its own text: the registry's sentence
        return {"id": f.id, "title": title, "tag": _t("tag", lang), "what": pick(f.gain, lang), "provide": [], "get": [],
                "limits": "", "figure": f.id, "labels": _labels(lang), "upgrade": pick(E.HOW_TO_UPGRADE, lang)}
    return {"id": f.id, "title": title, "tag": _t("tag", lang), "what": pick(p["what"], lang),
            "provide": [pick(x, lang) for x in p["provide"]], "get": [pick(x, lang) for x in p["get"]],
            "limits": pick(p["limits"], lang), "figure": p["figure"], "labels": _labels(lang),
            "upgrade": pick(E.HOW_TO_UPGRADE, lang)}


def _labels(lang: str) -> dict:
    return {"what": _t("what", lang), "provide": _t("provide", lang), "get": _t("get", lang), "limits": _t("limits_note", lang),
            "back": _t("back", lang), "upgrade": _t("upgrade_title", lang)}


# ------------------------------------------------------------------------------------------------------ implicit-solvent preview
_GPU_PLATFORMS = ("CUDA", "HIP", "OpenCL", "Metal")


def _platform_gpu(info) -> bool:
    """True when `info` names a usable GPU platform.  `info` may be a platform name, a dict (`{"name": ...}`, `{"is_gpu":
    ...}` or the Doctor dict `{"platform": {"name": ...}}`) or an object with `.name` and `.is_gpu` (PlatformChoice)."""
    if info is None:
        return False
    if isinstance(info, str):
        return info in _GPU_PLATFORMS
    if isinstance(info, dict):
        if "platform" in info:
            return _platform_gpu(info["platform"])
        if info.get("is_gpu") is not None:
            return bool(info["is_gpu"])
        return str(info.get("name") or "") in _GPU_PLATFORMS
    if getattr(info, "is_gpu", None) is not None:
        return bool(info.is_gpu)
    return str(getattr(info, "name", "") or "") in _GPU_PLATFORMS


def gbn2_preview_offer(platform_info, lang: str = "en") -> dict:
    """Whether the quick mode of Lite offers the "quick preview with implicit solvent" switch, and its text.  Offered
    only when a GPU platform is usable: GBn2 is fast only on a GPU (on a CPU it is slower than explicit water, D-25).
    The switch changes nothing but `md.solvent`; the existing gates keep blocking binding free energy and metal sites
    under GBn2.  (The FLOW developer has a similar helper elsewhere; this one is self-contained so the lead can unify.)"""
    off = {"show": False, "label": "", "caption": ""}
    if not is_lite() or not _platform_gpu(platform_info):
        return off
    return {"show": True, "label": _t("gbn2_label", lang), "caption": _t("gbn2_caption", lang)}
