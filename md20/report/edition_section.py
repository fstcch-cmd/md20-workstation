"""The Lite part of the report (D-181): what THIS run lacked and what the complete edition would add for exactly that.

The report is where a Lite user decides about the complete edition, so this page is written from the run's own data and
nothing else.  There is no fixed advertising copy.  Every item has the same parts:

    {"feature": <edition.PRO_FEATURES id>, "kind": "limit", "observed": <one sentence with the run's numbers>,
     "gain": <the registry sentence of that feature>, "evidence": {...the numbers and where they came from...}}

Sources (docs/specs/lite_edition.md §7), each read from what the report already holds, never recomputed:

  a  `state["edition"]`: the limits the run met (`hits`) and the reductions that were applied (`clamped`).
  b  the MD repeats that really exist (`replica_section.replica_counts`) and the `single_replica` flag of the replica sets.
  c  the binding results: the stored assessment and the claim records (`sampling.assessment`), the number of pulls,
     the withheld ΔG° and the comparison status of `sampling.multi.compare_binding`.
  d  implicit solvent (`md.solvent: gbn2`): a plain note, not an upgrade pitch.
  e  the analyses of the complete toolbox that the analysis step did not write.

What is deliberately NOT an item, because the complete edition would give the same result:
  * a comparison marked DESCRIPTIVE (shared-pocket pulls are condition-specific values in both editions, D-96);
  * diagnostics that are `unknown` only because the result was written before D-96 (they wait for reanalysis);
  * a limit that was not met.

Nothing observed means no item.  An empty list renders one sentence saying that this run met no Lite limit.
Pure Python: it reads the state dict and, like the rest of the report, the small JSON files the state points to.
Text is `(zh, en, ja, ko)` tuples (docs/specs/writing_style.md); the Korean sentences never put a particle directly after a variable.
"""
from __future__ import annotations

from .. import edition as E
from ..i18n import colon, norm, pick
from ..util import load_json
from .html import _esc

KIND_LIMIT, KIND_NOTE = "limit", "note"
SECTION_ID = "edition-appendix"
FOOTER_ATTR = "data-md20-edition"

# ------------------------------------------------------------------------------------------------ fixed text
_T = {
    "title": ("附錄 D　這次執行與完整版的差別", "Appendix D  What the complete edition would add to this run",
              "付録 D　この実行に完全版が加えるもの", "부록 D  이 실행에 정식판이 더하는 것"),
    "intro": ("這一節只寫這次執行實際碰到的 Lite 限制。數字都來自這份報告自己的資料。",
              "This appendix lists only the Lite limits this run actually met. The numbers come from the data in this report.",
              "この付録には、この実行で実際に当たった Lite の制限だけを書いています。数値はすべてこのレポート自身のデータから取っています。",
              "이 부록에는 이 실행에서 실제로 걸린 Lite의 제한만 적었습니다. 수치는 모두 이 보고서 자체의 데이터에서 가져왔습니다."),
    "none": ("這次執行沒有碰到 Lite 的任何限制。", "This run met no Lite limit.",
             "この実行は Lite の制限に当たりませんでした。", "이 실행은 Lite의 제한에 걸리지 않았습니다."),
    "note_title": ("隱式溶劑的快速預覽", "Implicit-solvent preview", "陰溶媒による簡易プレビュー", "암시적 용매 빠른 미리보기"),
    "other_title": ("其他限制", "Other limits", "その他の制限", "그 밖의 제한"),
    "table_caption": ("Lite 與完整版的對照", "Lite and the complete edition side by side",
                      "Lite と完全版の比較", "Lite와 정식판 비교"),
    "col_item": ("項目", "Item", "項目", "항목"),
    "reached": ("碰到的上限", "Limit reached", "当たった上限", "걸린 상한"),
    "mark": ("由 MD20 Lite 產生", "Made with MD20 Lite", "MD20 Lite で作成", "MD20 Lite로 생성"),
}

# the reduction that was applied: {req} what was asked for, {to} what Lite ran
_CLAMPED = {
    "md.production_ns": ("正式模擬從 {req} ns 縮短為 {to} ns。", "The production run was shortened from {req} ns to {to} ns.",
                         "本計算を {req} ns から {to} ns に短縮しました。", "본 계산을 {req} ns에서 {to} ns로 줄였습니다."),
    "md.tier": ("模擬等級從 {req} 改為 {to}。", "The simulation tier was changed from {req} to {to}.",
                "計算の等級を {req} から {to} に変更しました。", "계산 등급을 {req} 등급에서 {to} 등급으로 바꿨습니다."),
    "md.replicas": ("每個系統的獨立重複從 {req} 次減為 {to} 次。", "Independent repeats were reduced from {req} to {to} per system.",
                    "一つの系の独立した繰り返しを {req} 回から {to} 回に減らしました。",
                    "시스템마다 독립 반복을 {req} 회에서 {to} 회로 줄였습니다."),
    "binding.replicas": ("每個配體的獨立拉離從 {req} 次減為 {to} 次。", "Independent pulls per ligand were reduced from {req} to {to}.",
                         "リガンドごとの独立した引き離しを {req} 回から {to} 回に減らしました。",
                         "리간드마다 독립 당김을 {req} 회에서 {to} 회로 줄였습니다."),
    "binding.max_windows": ("傘狀採樣窗口數的上限從 {req} 個減為 {to} 個。",
                            "The limit on umbrella windows was reduced from {req} to {to}.",
                            "アンブレラサンプリングのウィンドウ数の上限を {req} 個から {to} 個に減らしました。",
                            "엄브렐라 샘플링 윈도우 수의 상한을 {req} 개에서 {to} 개로 줄였습니다."),
    "binding.window_ps": ("每個窗口的取樣時間從 {req} ps 縮短為 {to} ps。",
                          "Sampling per window was shortened from {req} ps to {to} ps.",
                          "各ウィンドウのサンプリング時間を {req} ps から {to} ps に短縮しました。",
                          "윈도우마다 샘플링 시간을 {req} ps에서 {to} ps로 줄였습니다."),
    "binding.refine_rounds": ("自動補窗口從 {req} 輪改為 {to} 輪。",
                              "Automatic window refinement was changed from {req} rounds to {to} rounds.",
                              "ウィンドウの自動追加を {req} 回から {to} 回に変更しました。",
                              "윈도우 자동 추가를 {req} 회에서 {to} 회로 바꿨습니다."),
}

_REPLICAS = ("{total} 個系統中有 {n} 個只跑了 1 次 MD 重複（{names}），結果只能描述，看不到重複之間的差異。",
             "{n} of {total} systems ran one MD repeat only ({names}), so their results are descriptive and show no spread between repeats.",
             "{total} 個の系のうち {n} 個は MD の繰り返しが 1 回だけで（{names}）、結果は記述にとどまり、繰り返しの間のばらつきは見えません。",
             "시스템 {total}개 중 {n}개({names})는 MD 반복이 1회뿐이라 결과는 기술에 그치며 반복 간 편차를 볼 수 없습니다.")

_LIG = ("配體 {name}", "ligand {name}", "リガンド {name}", "{name} 리간드")        # how a binding target is named in a sentence

_OVERLAP_GRAPH = ("{lig} 的傘狀採樣窗口，在 {thr} 的重疊門檻下沒有連成一串。",
                  "The umbrella windows of {lig} are not connected by overlap at the {thr} threshold.",
                  "{lig} のアンブレラサンプリングのウィンドウは、重なりの閾値 {thr} ではつながっていません。",
                  "{lig}의 엄브렐라 샘플링 윈도우는 겹침 문턱값 {thr} 기준으로 이어지지 않습니다.")
_OVERLAP_MBAR = ("{lig} 的 MBAR 重疊矩陣，在 {thr} 的重疊門檻下沒有連成一串。",
                 "The MBAR overlap matrix of {lig} is not connected at the {thr} threshold.",
                 "{lig} の MBAR 重なり行列は、重なりの閾値 {thr} ではつながっていません。",
                 "{lig}의 MBAR 겹침 행렬은 겹침 문턱값 {thr} 기준으로 이어지지 않습니다.")
_OVERLAP_ADJ = ("{lig} 相鄰窗口之間最小的重疊是 {value}，低於門檻 {thr}。",
                "The smallest overlap between neighbouring windows of {lig} is {value}, below the {thr} threshold.",
                "{lig} の隣り合うウィンドウの間の最小の重なりは {value} で、閾値 {thr} を下回っています。",
                "{lig}의 이웃 윈도우 사이 최소 겹침 값: {value}. 문턱값 {thr} 미만입니다.")
_UNKNOWN = ("{lig} 有 {n} 項取樣檢查沒有紀錄，無法評估（{names}）。",
            "{n} sampling checks of {lig} could not be evaluated ({names}).",
            "{lig} では、取得の確認 {n} 項目が評価できませんでした（{names}）。",
            "{lig}의 샘플링 점검 {n}개 항목은 평가하지 못했습니다({names}).")
_ONE_PULL = ("{lig} 只拉離了 1 次，看不到獨立拉離之間的差異。",
             "{Lig} was pulled once, so there is no spread between independent pulls.",
             "{lig} の引き離しは 1 回だけで、独立した引き離しの間のばらつきは見えません。",
             "{lig}의 당김은 1회뿐이라 독립 당김 사이의 편차를 볼 수 없습니다.")
_WITHHELD = ("{lig} 的 ΔG° 沒有輸出，原因寫在結合自由能一節。",
             "ΔG° was not reported for {lig}. The reason is given in the binding free-energy section.",
             "{lig} の ΔG° は出力されていません。理由は結合自由エネルギーの節に書いてあります。",
             "{lig}의 ΔG°는 출력되지 않았습니다. 이유는 결합 자유 에너지 절에 있습니다.")
_NOT_COMPARED = ("{ctx}的 {m} 個配體中，只有 {n} 個通過取樣評估，無法互相比較。",
                 "Among the {m} computed ligands in the {ctx} context, only {n} passed the sampling assessment, so they cannot be compared.",
                 "{ctx}の {m} 個のリガンドのうち、取得評価に合格したのは {n} 個だけで、比較できません。",
                 "{ctx} 상황에서 계산한 리간드 {m}개 중 샘플링 평가를 통과한 것은 {n}개뿐이라 비교할 수 없습니다.")
_IMPLICIT = ("這次分子動力學用隱式溶劑（GBn2），結果只供描述，不能和顯式水或文獻的數值直接比較。結合自由能需要顯式水，Lite 本身就可以使用。",
             "Molecular dynamics used implicit solvent (GBn2). The results are descriptive and cannot be compared directly with "
             "explicit-water or literature values. Binding free energy needs explicit water, which Lite offers.",
             "分子動力学には陰溶媒（GBn2）を使いました。結果は記述にとどまり、陽溶媒の水や文献の値とは直接比較できません。"
             "結合自由エネルギーには陽溶媒の水が必要で、Lite でも使えます。",
             "분자동역학에 암시적 용매(GBn2)를 사용했습니다. 결과는 기술에 그치며 명시적 물이나 문헌 값과 직접 비교할 수 없습니다. "
             "결합 자유 에너지에는 명시적 물이 필요하고 Lite에서도 쓸 수 있습니다.")
_TOOLBOX = ("這份報告沒有做下列完整版的分析（{names}）。", "These analyses of the complete edition were not run for this report ({names}).",
            "この報告には、完全版の次の解析が含まれていません（{names}）。", "이 보고서에는 정식판의 다음 분석이 들어 있지 않습니다({names}).")
_TOOLBOX_PARTS = {
    "tica": ("tICA 與馬可夫狀態模型", "tICA and Markov state models", "tICA とマルコフ状態モデル", "tICA와 마르코프 상태 모형"),
    "hbond_network": ("氫鍵網路", "hydrogen-bond networks", "水素結合ネットワーク", "수소 결합 네트워크"),
    "hydration": ("水合分析", "hydration analysis", "水和解析", "수화 분석"),
    "common_basis": ("共同主成分比較", "common principal-component comparison", "共通主成分での比較", "공통 주성분 비교"),
}

# every text of this module that a person reads (tests check the writing rules on all of it)
ALL_TEXTS = (list(_T.values()) + list(_CLAMPED.values())
             + [_REPLICAS, _LIG, _OVERLAP_GRAPH, _OVERLAP_MBAR, _OVERLAP_ADJ, _UNKNOWN, _ONE_PULL, _WITHHELD, _NOT_COMPARED,
                _IMPLICIT, _TOOLBOX] + list(_TOOLBOX_PARTS.values()))


def _join(parts, lang: str) -> str:
    return ("、" if lang in ("zh", "ja") else ", ").join(parts)


def _scalar(v) -> bool:
    return v is not None and not isinstance(v, (bool, dict, list, tuple))


# ------------------------------------------------------------------------------------------------ the run's edition
def _entry(state: dict | None) -> dict:
    """`state["edition"]` (shape of `edition.state_record`); a workflow that keeps it under `steps` is read as well."""
    st = state or {}
    for rec in (st.get("edition"), (st.get("steps") or {}).get("edition")):
        if isinstance(rec, dict) and any(k in rec for k in ("edition", "hits", "clamped")):
            return rec
    return {}


def report_edition(state: dict | None) -> str:
    """The edition the run was made in: the one the state recorded, else the edition in effect now."""
    ed = _entry(state).get("edition")
    return ed if ed in E.EDITIONS else E.current()


def is_lite_report(state: dict | None) -> bool:
    return report_edition(state) == E.LITE


# ------------------------------------------------------------------------------------------------ the items
def _item(feature: str, observed: str, evidence: dict, lang: str, kind: str = KIND_LIMIT) -> dict:
    gain = pick(E.pro_feature(feature).gain, lang) if feature in {f.id for f in E.PRO_FEATURES} else ""
    return {"feature": feature if gain else "", "kind": kind, "observed": observed, "gain": gain, "evidence": evidence}


def _from_hits(rec: dict, lang: str) -> list[dict]:
    clamps: dict[str, dict] = {}
    for c in rec.get("clamped") or []:
        if isinstance(c, dict) and c.get("code"):
            clamps.setdefault(c["code"], c)
    out = []
    for h in rec.get("hits") or []:
        if not isinstance(h, dict) or not h.get("code"):
            continue
        code, fid = h["code"], h.get("feature") or ""
        title = pick(E.pro_feature(fid).title, lang) if fid in {f.id for f in E.PRO_FEATURES} else fid
        c = clamps.get(code)
        ev = {"source": "edition.hits", "code": code, "value": h.get("value"), "limit": h.get("limit"), "clamped": False}
        if c is not None and code in _CLAMPED:
            req = c.get("from") if _scalar(c.get("from")) else h.get("value")
            to = c.get("to") if _scalar(c.get("to")) else h.get("limit")
            ev.update(clamped=True, **{"from": req, "to": to})
            text = pick(_CLAMPED[code], lang).format(req=E._fmt(req), to=E._fmt(to))
        else:
            # the sentence of the hit itself (edition._HIT_TEXT), so the report and the gate never word a limit twice
            body = pick(E._HIT_TEXT.get(code) or E._HIT_TEXT["feature"], lang).format(
                value=E._fmt(h.get("value")), limit=E._fmt(h.get("limit")), title=title)
            text = pick(_T["reached"], lang) + colon(lang) + body
        out.append(_item(fid, text, ev, lang))
    return out


class _StateView:
    """`replica_section.replica_counts` takes a workflow; this gives it the state we already hold."""

    def __init__(self, state: dict | None):
        self._s = {"steps": (state or {}).get("steps") or {}}

    def state(self) -> dict:
        return self._s


def _from_replicas(state: dict | None, lang: str) -> list[dict]:
    from .replica_section import replica_counts
    counts = {k: n for k, n in replica_counts(_StateView(state)).items() if n > 0}
    if not counts:
        return []
    sums = (((state or {}).get("steps") or {}).get("analysis") or {}).get("summaries") or {}
    flagged = {}
    for k in counts:
        path = (sums.get(k) or {}).get("replica_set_file")
        agg = load_json(path, {}) if path else {}
        if isinstance(agg, dict) and "single_replica" in (agg.get("flags") or []):
            flagged[k] = agg.get("flags")
    one = sorted({k for k, n in counts.items() if n == 1} | set(flagged))
    if not one:
        return []
    ev = {"source": "md_runs", "replicas": {k: counts[k] for k in sorted(counts)}, "single": one, "flags": flagged}
    text = pick(_REPLICAS, lang).format(n=len(one), total=len(counts), names=_join(one, lang))
    return [_item("replicas", text, ev, lang)]


def _lig(name: str, lang: str) -> str:
    return pick(_LIG, lang).format(name=name)


def _fill(tpl: tuple, lang: str, **kw) -> str:
    """Fill a template.  `{Lig}` is `{lig}` with a capital first letter, for an English sentence that starts with it."""
    lig = kw.get("lig", "")
    return pick(tpl, lang).format(Lig=lig[:1].upper() + lig[1:], **kw)


def _pull_count(r: dict) -> int:
    per = r.get("per_replica") or []
    return len(per) if len(per) > 1 else int(r.get("replicas") or 1)


def _from_binding(state: dict | None, assessments: dict | None, cfg: dict | None, lang: str) -> list[dict]:
    from .figure_text import _DIAG_NAME
    out = []
    gbn2 = ((cfg or {}).get("md") or {}).get("solvent") == "gbn2"
    for name, info in (assessments or {}).items():
        r = info.get("result") or {}
        if r.get("status", "PASS") != "PASS":
            continue                                    # a pull that did not finish has no sampling to criticise
        diag = {d["id"]: d for d in (info.get("assessment") or {}).get("diagnostics") or [] if isinstance(d, dict)}
        lig = _lig(name, lang)
        # 1. overlap below the threshold (the run's own diagnostic values)
        for did, tpl in (("overlap_graph", _OVERLAP_GRAPH), ("mbar_overlap", _OVERLAP_MBAR), ("adjacent_overlap_min", _OVERLAP_ADJ)):
            d = diag.get(did)
            if d and d.get("status") == "fail":
                thr = d.get("threshold")
                val = d.get("value") if did == "adjacent_overlap_min" else None
                text = _fill(tpl, lang, lig=lig, thr=E._fmt(thr), value=E._fmt(val))
                out.append(_item("binding_full", text, {"source": "assessment", "target": name, "diagnostic": did,
                                                        "value": d.get("value"), "threshold": thr}, lang))
                break
        # 2. checks that could not be evaluated: only for an assessment the run itself stored (an old result waits for reanalysis)
        cps = info.get("path_specific") or {}
        unk = [i for i in cps.get("unknown") or [] if i not in (cps.get("failed") or [])]
        if cps.get("assessment_source") == "stored" and not cps.get("eligible") and unk:
            names = _join([pick(_DIAG_NAME.get(i, (i,) * 4), lang) for i in unk], lang)
            out.append(_item("binding_full", _fill(_UNKNOWN, lang, lig=lig, n=len(unk), names=names),
                             {"source": "claim_status", "target": name, "claim": "path_specific", "unknown": unk}, lang))
        # 3. one pull
        n_pull = _pull_count(r)
        if n_pull == 1:
            out.append(_item("binding_full", _fill(_ONE_PULL, lang, lig=lig),
                             {"source": "binding.results", "target": name, "pulls": 1}, lang))
        # 4. ΔG° withheld (in implicit solvent the gate is the cause, which Lite does not change: no upgrade claim)
        if r.get("dG_withheld") and not gbn2:
            out.append(_item("binding_full", _fill(_WITHHELD, lang, lig=lig),
                             {"source": "binding.results", "target": name, "dG_withheld": r.get("dG_withheld"),
                              "dG_standard_eligible": bool((info.get("dG_standard") or {}).get("eligible"))}, lang))
    # 5. a comparison that cannot be made because too few ligands passed the sampling assessment
    from .comparability import context_label
    comp = (((state or {}).get("steps") or {}).get("binding") or {}).get("comparison") or {}
    for ctx, c in (comp.get("contexts") or {}).items():
        if not isinstance(c, dict) or c.get("status") != "INSUFFICIENT":
            continue
        passed, left_out = list(c.get("keys") or []), list(c.get("not_compared") or [])
        if len(passed) >= 2 or not left_out:
            continue                                    # different conditions, or nothing was computed to compare
        m = len(passed) + len(left_out)
        text = pick(_NOT_COMPARED, lang).format(ctx=context_label(ctx, lang), m=m, n=len(passed))
        out.append(_item("binding_full", text, {"source": "binding.comparison", "context": ctx, "computed": m,
                                                "passed": passed, "status": c.get("status")}, lang))
    return out


def _from_solvent(cfg: dict | None, lang: str) -> list[dict]:
    if ((cfg or {}).get("md") or {}).get("solvent") != "gbn2":
        return []
    return [_item("", pick(_IMPLICIT, lang), {"source": "config", "md.solvent": "gbn2"}, lang, KIND_NOTE)]


def _toolbox_present(state: dict | None) -> dict[str, bool] | None:
    """Which toolbox analyses the analysis step wrote.  None when no MD analysis exists at all (then nothing was missed)."""
    an = (((state or {}).get("steps") or {}).get("analysis") or {})
    sums = an.get("summaries") or {}
    if not sums:
        return None
    present = {k: False for k in _TOOLBOX_PARTS}
    for s in sums.values():
        path = (s or {}).get("extended_file")
        e = load_json(path, {}) if path else {}
        if not isinstance(e, dict):
            continue
        if (e.get("tica") or {}).get("status") == "ok":
            present["tica"] = True
        if (((e.get("hbonds_protein") or {}).get("network") or {}).get("status")) == "ok":
            present["hbond_network"] = True
        if any(((l or {}).get("hydration") or {}).get("status") == "ok" for l in (e.get("ligands") or {}).values()):
            present["hydration"] = True
    cb = (an.get("comparison") or {}).get("common_basis_file")
    if cb and load_json(cb, {}):
        present["common_basis"] = True
    return present


def _from_toolbox(state: dict | None, lang: str) -> list[dict]:
    present = _toolbox_present(state)
    if present is None:
        return []
    missing = [k for k in _TOOLBOX_PARTS if not present[k]]
    if not missing:
        return []
    names = _join([pick(_TOOLBOX_PARTS[k], lang) for k in missing], lang)
    return [_item("analysis_toolbox", pick(_TOOLBOX, lang).format(names=names),
                  {"source": "analysis", "missing": missing, "present": [k for k in _TOOLBOX_PARTS if present[k]]}, lang)]


def assessment_inputs(results: dict | None, *, assessment_for=None, claim_of=None) -> dict:
    """The binding results with the objects `gains` reads: the assessment and the claim records of the run.
    The workflow report passes its own `_assessment_for` and `_claim_of`, which can also read a manifest; the defaults
    read the result alone."""
    from ..sampling.assessment import claim_status, resolve_assessment
    af = assessment_for or (lambda r: resolve_assessment(r)[0])
    co = claim_of or (lambda r, c: claim_status(r, c))
    out = {}
    for name, r in (results or {}).items():
        if isinstance(r, dict) and r.get("status", "PASS") == "PASS":
            out[name] = {"result": r, "assessment": af(r), "path_specific": co(r, "path_specific"), "dG_standard": co(r, "dG_standard")}
    return out


def gains(state: dict | None, cfg: dict | None, assessments: dict | None, lang: str = "en") -> list[dict]:
    """Everything this run lacked that the complete edition would give, each with the run's own numbers.  Empty when the
    run met no Lite limit.  `assessments` is the output of `assessment_inputs`."""
    lang = norm(lang)
    return (_from_hits(_entry(state), lang) + _from_replicas(state, lang) + _from_binding(state, assessments, cfg, lang)
            + _from_solvent(cfg, lang) + _from_toolbox(state, lang))


# ------------------------------------------------------------------------------------------------ the page
def _plain_table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


def section_html(items: list[dict], lang: str = "en", *, doc=None) -> str:
    """The appendix: heading, the observed items grouped by feature, the Lite and complete comparison table, how to upgrade.
    `doc` (the report's `Doc`) numbers the table like every other table of the report."""
    L = norm(lang)
    t = lambda k: pick(_T[k], L)  # noqa: E731
    limits_ = [i for i in items if i.get("kind", KIND_LIMIT) == KIND_LIMIT]
    notes = [i for i in items if i.get("kind") == KIND_NOTE]
    out = [f"<section id={SECTION_ID}><h2>{_esc(t('title'))}</h2><p class=muted>{_esc(t('intro'))}</p>"]
    if not limits_:
        out.append(f"<p>{_esc(t('none'))}</p>")
    groups: dict[str, list[dict]] = {}
    for i in limits_:
        groups.setdefault(i.get("feature") or "", []).append(i)
    for fid, group in groups.items():
        title = pick(E.pro_feature(fid).title, L) if fid else t("other_title")
        out.append(f"<h3>{_esc(title)}</h3><ul class=findings>"
                   + "".join(f"<li class=note>{_esc(i['observed'])}</li>" for i in group) + "</ul>")
        if group[0].get("gain"):
            out.append(f"<p>{_esc(group[0]['gain'])}</p>")
    for n in notes:
        out.append(f"<h3>{_esc(t('note_title'))}</h3><p>{_esc(n['observed'])}</p>")
    rows = E.comparison_rows(L)
    headers = [t("col_item"), E.name(E.LITE, L), E.name(E.FULL, L)]
    cells = [[r["item"], r["lite"], r["full"]] for r in rows]
    if doc is not None:
        out.append(doc.table(headers, [[_esc(c) for c in r] for r in cells], _T["table_caption"], {1}))
    else:
        out.append(f"<div class=caption>{_esc(t('table_caption'))}</div>" + _plain_table(headers, cells))
    out.append(f"<p>{_esc(pick(E.HOW_TO_UPGRADE, L))}</p></section>")
    return "".join(out)


def appendix_html(doc, state: dict | None, cfg: dict | None, lang: str, assessments: dict | None) -> str:
    """What the workflow report appends in a Lite run."""
    return section_html(gains(state, cfg, assessments, lang), lang, doc=doc)


def footer_mark(lang: str = "en") -> str:
    """The short mark for the page footer, put just before the stamp footer."""
    return f"<p class=meta {FOOTER_ATTR}=lite>{_esc(pick(_T['mark'], norm(lang)))}</p>"
