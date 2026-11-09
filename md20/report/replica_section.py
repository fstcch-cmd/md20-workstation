"""Report section for the cross-replica aggregation (D-130 redo): per-replica table, mean ± SD with the Student-t 95 % CI,
k of n replicas, the overlay figure, and the plain statement when only one trajectory exists.

Kept out of workflow_report.py on purpose (small hook there, text here).  Reads the files `Workflow.analyse` wrote
(`analysis_replicas_<system>.json`, md20/analysis/replica_set.py); computes nothing new, so the report and the JSON can
never disagree.  Text is (zh, en, ja, ko) tuples (docs/specs/writing_style.md).
"""
from __future__ import annotations

from pathlib import Path

from ..advisor import tx
from ..util import load_json
from . import interpret as I
from .html import _esc

_UNAVAILABLE = ("不可得，單一軌跡無法估計重複間不確定性", "Unavailable. One trajectory cannot give between-replica uncertainty.",
                "算出できません。軌跡が 1 本だけなので、反復間の不確かさを推定できません。",
                "계산할 수 없습니다. 궤적이 하나뿐이라 반복 간 불확실성을 추정할 수 없습니다.")


def replica_counts(wf) -> dict:
    """{system key: number of replicas that really exist} from the stored MD record; empty when nothing ran."""
    runs = (wf.state()["steps"].get("md_runs") or {}).get("runs") or {}
    return {k: len(r.get("run_ids") or []) for k, r in runs.items() if isinstance(r, dict)}


def configured_or_actual(cfg: dict, wf=None) -> int:
    """The number of replicas for the methods sentence: the smallest real count when runs exist, else the configured number
    (default 3, engine/replica_plan.py), never a hard-coded 1."""
    from ..engine.replica_plan import configured_replicas
    if wf is not None:
        counts = [n for n in replica_counts(wf).values() if n > 0]
        if counts:
            return min(counts)
    return configured_replicas(cfg)[0]


def _pm(st: dict, nd: int = 2) -> str:
    if st.get("mean") is None:
        return "—"
    if st.get("sd") is None:
        return f"{st['mean']:.{nd}f}"
    return f"{st['mean']:.{nd}f} ± {st['sd']:.{nd}f}"


def _ci(st: dict, nd: int = 2) -> str:
    c = st.get("ci95")
    return "—" if not c else f"[{c['low']:.{nd}f}, {c['high']:.{nd}f}]"


def _kn(L: str, k: int, n: int) -> str:
    return tx((f"{n} 條中有 {k} 條", f"{k} of {n} replicas", f"{n} 本中 {k} 本", f"{n}개 중 {k}개"), L)


_OBS_NAME = {
    "rmsd_backbone_A": ("主鏈 RMSD（後半段平均，Å）", "Backbone RMSD (second-half mean, Å)", "主鎖 RMSD（後半の平均、Å）", "주사슬 RMSD (후반부 평균, Å)"),
    "rg_protein_A": ("蛋白質 Rg（後半段平均，Å）", "Protein Rg (second-half mean, Å)", "タンパク質の Rg（後半の平均、Å）", "단백질 Rg (후반부 평균, Å)"),
    "rmsd_in_pocket_A": ("口袋 RMSD（後半段平均，Å）", "Pocket RMSD (second-half mean, Å)", "ポケット RMSD（後半の平均、Å）", "포켓 RMSD (후반부 평균, Å)"),
    "contact_residues": ("接觸殘基數（後半段平均）", "Contacting residues (second-half mean)", "接触残基数（後半の平均）", "접촉 잔기 수 (후반부 평균)"),
    "polar_contacts": ("極性接觸對數（後半段平均）", "Polar contact pairs (second-half mean)", "極性接触ペア数（後半の平均）", "극성 접촉 쌍 수 (후반부 평균)"),
    "com_distance_to_pocket_A": ("質心離口袋距離（後半段平均，Å）", "COM distance to pocket (second-half mean, Å)",
                                 "ポケットからの重心距離（後半の平均、Å）", "포켓까지 질량 중심 거리 (후반부 평균, Å)"),
}


def _caution_texts(agg: dict, key: str) -> list[dict]:
    out = []
    flags = agg.get("flags") or []
    n = agg.get("n_analysed", 0)
    if "single_replica" in flags:
        out.append(I.F("caution",
                       f"{key} 只有一條可分析的軌跡，無法估計重複之間的不確定性。這裡的數字描述的是這一次模擬，不代表系統的平均行為。",
                       f"{key} has one analysable trajectory, so the uncertainty between replicas cannot be estimated. The numbers describe this one run, not the average behaviour of the system.",
                       f"{key} は解析できる軌跡が 1 本だけなので、反復間の不確かさを推定できません。数値はこの 1 回の計算を表すもので、系の平均的な挙動ではありません。",
                       f"{key}는 분석할 수 있는 궤적이 하나뿐이라 반복 간 불확실성을 추정할 수 없습니다. 수치는 이 한 번의 계산을 나타낼 뿐 시스템의 평균 거동이 아닙니다."))
    elif "below_recommended_n" in flags:
        out.append(I.F("caution",
                       f"{key} 只有 {n} 條重複，少於建議的 {agg.get('min_recommended', 3)} 條，信賴區間很寬，只能當參考。",
                       f"{key} has {n} replicas, fewer than the recommended {agg.get('min_recommended', 3)}. The confidence interval is very wide and is only a rough guide.",
                       f"{key} の反復は {n} 本で、推奨の {agg.get('min_recommended', 3)} 本より少ないため、信頼区間はとても広く、目安にしかなりません。",
                       f"{key}의 반복은 {n}개로 권장 {agg.get('min_recommended', 3)}개보다 적습니다. 신뢰구간이 매우 넓어 참고용으로만 쓸 수 있습니다."))
    if "excluded_replicas" in flags:
        out.append(I.F("caution",
                       f"{key} 有 {len(agg.get('excluded') or [])} 條重複沒有納入彙總（沒有完成或分析失敗），原因列在表中。",
                       f"{key} has {len(agg.get('excluded') or [])} replica(s) left out of the summary (not finished or analysis failed). The reasons are in the table.",
                       f"{key} では {len(agg.get('excluded') or [])} 本の反復が集計に含まれていません（未完了または解析に失敗）。理由は表にあります。",
                       f"{key}에서 반복 {len(agg.get('excluded') or [])}개가 요약에서 빠졌습니다(미완료 또는 분석 실패). 이유는 표에 있습니다."))
    div = [f.split(":", 1)[1] for f in flags if f.startswith("divergent:")]
    if div:
        out.append(I.F("caution",
                       f"{key} 的重複彼此差很多（{'、'.join(div)}）。單一軌跡的結果不能代表這個系統，平均值只是各條的折衷。",
                       f"The replicas of {key} differ a lot ({', '.join(div)}). One trajectory does not represent the system, and the mean is only a compromise between them.",
                       f"{key} の反復どうしの差が大きいです（{'、'.join(div)}）。1 本の軌跡は系を代表せず、平均値は各軌跡の折衷にすぎません。",
                       f"{key}의 반복들이 서로 많이 다릅니다({', '.join(div)}). 궤적 하나는 시스템을 대표하지 못하고 평균은 각 궤적의 절충일 뿐입니다."))
    inc = [f.split(":", 1)[1] for f in flags if f.startswith("inconsistent:")]
    if inc:
        out.append(I.F("caution",
                       f"{key} 的配體結果在重複之間不一致（{'、'.join(inc)}）。不能用其中一條軌跡下結論，請同時看 k／n。",
                       f"The ligand outcome of {key} is not the same in every replica ({', '.join(inc)}). Do not conclude from one trajectory. Read the k of n counts.",
                       f"{key} のリガンドの結果は反復の間で一致していません（{'、'.join(inc)}）。1 本の軌跡だけで結論を出さず、k／n を確認してください。",
                       f"{key}의 리간드 결과가 반복마다 일치하지 않습니다({', '.join(inc)}). 궤적 하나로 결론을 내리지 말고 k／n을 확인하십시오."))
    return out


def replica_html(doc, wf, sums: dict) -> str:
    """The replica section for every system whose analysis wrote a replica-set file.  Findings go to ``doc.collected`` so
    the section interpretation lists them."""
    L = doc.lang
    out = ""
    for key, s in sums.items():
        path = (s or {}).get("replica_set_file")
        agg = load_json(path, {}) if path else {}
        if not agg or agg.get("schema") != "md20.replica_set/1":
            continue
        out += f"<h3>{_esc(tx((f'獨立重複的彙總：{key}', f'Independent replicas: {key}', f'独立した反復の集計：{key}', f'독립 반복 요약: {key}'), L))}</h3>"
        out += "<p class=muted>" + _esc(tx((
            "重複是各自用不同 seed 跑的獨立 MD 軌跡。同一條軌跡拉出來的 SMD 拉動和傘狀採樣視窗不是重複，不會增加條數。各條軌跡不會接在一起，事件長短和持續性都在單條內計算。",
            "A replica is an independent MD run with its own seed. SMD pulls and umbrella windows taken from one trajectory are not replicas and do not raise the count. Trajectories are never joined, so event durations and persistence are computed inside one replica.",
            "反復とは、別の seed で独立に実行した MD 軌跡のことです。1 本の軌跡から引き出した SMD の引き離しやアンブレラのウィンドウは反復ではなく、本数に加えません。軌跡はつなげず、イベントの長さや持続性は 1 本の中で計算します。",
            "반복은 서로 다른 seed로 독립적으로 실행한 MD 궤적입니다. 한 궤적에서 뽑은 SMD 당김과 엄브렐라 윈도우는 반복이 아니며 개수에 더하지 않습니다. 궤적은 이어 붙이지 않고, 사건 길이와 지속성은 한 반복 안에서 계산합니다."), L)) + "</p>"
        n_an, n_listed = agg.get("n_analysed", 0), agg.get("n_listed", 0)
        out += "<p>" + _esc(tx((f"納入彙總：{n_an} 條（共 {n_listed} 條）。", f"Included in the summary: {n_an} (of {n_listed} listed).",
                               f"集計に含めた反復：{n_an} 本（全 {n_listed} 本）。", f"요약에 포함: {n_an}개(전체 {n_listed}개)."), L)) + "</p>"
        lig_names = list((agg.get("ligands") or {}))
        # ---- per-replica table (each replica keeps its identity; within-trajectory SE in brackets)
        obs = agg.get("observables") or {}
        rm = obs.get("rmsd_backbone_A") or {}
        per_val = {x["run_id"]: x["value"] for x in rm.get("per_replica") or []}
        within = {x["run_id"]: x for x in (rm.get("within_trajectory") or {}).get("per_replica") or []}
        lig_val = {ln: {x["run_id"]: x["value"] for x in (((agg["ligands"][ln].get("observables") or {}).get("rmsd_in_pocket_A") or {})
                                                          .get("per_replica") or [])} for ln in lig_names}
        lig_in = {ln: {x["run_id"]: x["value"] for x in ((agg["ligands"][ln].get("in_pocket_final20") or {}).get("per_replica") or [])}
                  for ln in lig_names}
        yes, no, unk = tx(("是", "yes", "はい", "예"), L), tx(("否", "no", "いいえ", "아니오"), L), tx(("未知", "unknown", "不明", "알 수 없음"), L)
        rows = []
        for r in agg.get("replicas") or []:
            rid = r["run_id"]
            w = within.get(rid) or {}
            rmsd = "—" if rid not in per_val else f"{per_val[rid]:.2f}" + (f" (SE {w['block_se']:.2f})" if w.get("block_se") is not None else "")
            cells = [_esc(rid), _esc(str(r.get("status") or "—")),
                     tx(("納入", "included", "含める", "포함"), L) if r.get("analysed") else f"<b class=warn>{_esc(tx(('排除', 'excluded', '除外', '제외'), L))}</b>",
                     rmsd]
            for ln in lig_names:
                v = lig_val[ln].get(rid)
                ip = lig_in[ln].get(rid, None)
                cells.append("—" if v is None else f"{v:.2f} ({yes if ip else no if ip is False else unk})")
            cells.append(_esc(r.get("reason") or ""))
            rows.append(cells)
        head = [tx(("重複（run）", "Replica (run)", "反復（run）", "반복(run)"), L), tx(("MD 狀態", "MD status", "MD の状態", "MD 상태"), L),
                tx(("彙總", "In summary", "集計", "요약"), L), tx(_OBS_NAME["rmsd_backbone_A"], L)]
        head += [tx((f"{ln} 口袋 RMSD（Å，括號：最後 20 % 是否留在口袋）", f"{ln} pocket RMSD (Å; in brackets: in pocket in the last 20 %)",
                     f"{ln} のポケット RMSD（Å、括弧：最後の 20 % でポケット内か）", f"{ln} 포켓 RMSD(Å, 괄호: 마지막 20 %에서 포켓 안인지)"), L) for ln in lig_names]
        head.append(tx(("原因", "Reason", "理由", "이유"), L))
        out += doc.table(head, rows,
                         ("每條重複各自的結果。括號內 SE 是單一軌跡內部的區塊平均標準誤，不是重複之間的不確定性。",
                          "Result of each replica. SE in brackets is the block-average standard error inside one trajectory, not the uncertainty between replicas.",
                          "各反復の結果です。括弧内の SE は 1 本の軌跡の内部のブロック平均の標準誤差で、反復間の不確かさではありません。",
                          "각 반복의 결과입니다. 괄호 안 SE는 한 궤적 내부의 블록 평균 표준오차이며 반복 간 불확실성이 아닙니다."), set(range(3, 4 + len(lig_names))))
        # ---- aggregate table
        arows = []

        def add(name, st):
            if st.get("n", 0) == 0:
                return
            note = "" if (st.get("between_replica") or {}).get("status") == "ok" else _esc(tx(_UNAVAILABLE, L))
            if note == "" and st.get("below_recommended_n"):
                note = _esc(tx(("少於建議條數，區間僅供參考", "fewer than recommended, interval is a rough guide",
                                "推奨より少ないため、区間は目安です", "권장보다 적어 구간은 참고용입니다"), L))
            if st.get("divergent"):
                note += (" " if note else "") + f"<b class=warn>{_esc(tx(('重複之間差異大', 'replicas differ a lot', '反復間の差が大きい', '반복 간 차이가 큼'), L))}</b>"
            arows.append([_esc(name), str(st["n"]), _pm(st), _ci(st), note])
        for k_, st in obs.items():
            add(tx(_OBS_NAME.get(k_, (k_,) * 4), L), st)
        for ln in lig_names:
            for k_, st in (agg["ligands"][ln].get("observables") or {}).items():
                add(f"{ln}: " + tx(_OBS_NAME.get(k_, (k_,) * 4), L), st)
        for ln in lig_names:
            for b, label in (("in_pocket_final20", ("最後 20 % 仍在口袋", "in the pocket in the last 20 %", "最後の 20 % でポケット内", "마지막 20 %에서 포켓 안")),
                             ("stays_bound", ("口袋 RMSD 小於 3 Å（舊旗標）", "pocket RMSD below 3 Å (legacy flag)", "ポケット RMSD が 3 Å 未満（従来のフラグ）", "포켓 RMSD 3 Å 미만(이전 플래그)"))):
                bs = agg["ligands"][ln].get(b) or {}
                if bs.get("n"):
                    extra = f" +{bs['n_unknown']} {tx(('未知', 'unknown', '不明', '알 수 없음'), L)}" if bs.get("n_unknown") else ""
                    arows.append([_esc(f"{ln}: " + tx(label, L)), str(bs["n"]), _esc(_kn(L, bs["k"], bs["n"]) + extra), "—",
                                  "" if bs.get("consistent") else f"<b class=warn>{_esc(tx(('重複之間不一致', 'not the same in every replica', '反復の間で不一致', '반복마다 다름'), L))}</b>"])
        if arows:
            out += doc.table([tx(("觀測量", "Observable", "観測量", "관측량"), L), "n", tx(("平均 ± 標準差（跨重複）", "Mean ± SD (across replicas)", "平均 ± 標準偏差（反復間）", "평균 ± 표준편차(반복 간)"), L),
                              tx(("95 % 信賴區間（t 分布）", "95 % CI (Student t)", "95 % 信頼区間（t 分布）", "95 % 신뢰구간(t 분포)"), L),
                              tx(("備註", "Note", "備考", "비고"), L)], arows,
                             ("跨重複的彙總。每條重複先算出一個數，再算平均與樣本標準差（n−1）；n 是重複的條數，不是幀數。",
                              "Summary across replicas. Each replica gives one number first, then the mean and sample SD (n−1) are taken; n counts replicas, not frames.",
                              "反復間の集計です。各反復でまず 1 つの値を出し、その平均と標本標準偏差（n−1）を求めます。n は反復の本数で、フレーム数ではありません。",
                              "반복 간 요약입니다. 각 반복에서 값 하나를 먼저 구한 뒤 평균과 표본 표준편차(n−1)를 계산합니다. n은 반복 수이며 프레임 수가 아닙니다."), {1, 2, 3})
        # ---- contact occupancy per residue (top rows of the first ligand with data)
        for ln in lig_names:
            co = agg["ligands"][ln].get("contact_occupancy") or {}
            res = (co.get("residues") or [])[:10]
            if not res:
                continue
            crow = [[_esc(x["residue"]), _pm({"mean": x["mean"], "sd": x["sd"]}), _ci(x), _esc(_kn(L, x["persistent_k"], x["persistent_n"]))] for x in res]
            out += doc.table([tx(("殘基", "Residue", "残基", "잔기"), L), tx(("接觸占有率（平均 ± 標準差）", "Contact occupancy (mean ± SD)", "接触占有率（平均 ± 標準偏差）", "접촉 점유율(평균 ± 표준편차)"), L),
                              tx(("95 % 信賴區間", "95 % CI", "95 % 信頼区間", "95 % 신뢰구간"), L), tx(("占有率 ≥ 0.5 的重複", "Replicas with occupancy ≥ 0.5", "占有率 ≥ 0.5 の反復", "점유율 ≥ 0.5인 반복"), L)], crow,
                             (f"{ln} 與口袋殘基的接觸占有率（前 10 名）。某條重複完全沒碰到該殘基記為 0。",
                              f"Contact occupancy between {ln} and pocket residues (top 10). A replica that never touched the residue counts as 0.",
                              f"{ln} とポケット残基の接触占有率（上位 10）。ある反復で一度も接触しなかった残基は 0 として数えます。",
                              f"{ln}와 포켓 잔기의 접촉 점유율(상위 10). 어떤 반복에서 한 번도 닿지 않은 잔기는 0으로 셉니다."), {1, 2})
        ov = s.get("replica_overlay")
        if ov:
            out += doc.figure(ov, (f"{key} 每條重複的主鏈 RMSD 與配體口袋 RMSD（灰色帶為跨重複的平均 ± 標準差）。",
                                   f"Backbone RMSD and ligand pocket RMSD of each replica of {key} (grey band: mean ± SD across replicas).",
                                   f"{key} の各反復の主鎖 RMSD とリガンドのポケット RMSD です（灰色の帯は反復間の平均 ± 標準偏差）。",
                                   f"{key}의 각 반복의 주사슬 RMSD와 리간드 포켓 RMSD입니다(회색 띠는 반복 간 평균 ± 표준편차)."))
        out += structure_html(doc, agg, key)
        doc.collected += _caution_texts(agg, key)
    return out


# ------------------------------------------------------------------------------------------------ D-142
def _unavail_reason(blk: dict | None) -> str:
    return (blk or {}).get("reason") or ""


def _stat_row(L, name, st: dict, nd: int = 3, note: str = "") -> list:
    return [_esc(name), str(st.get("n", "")), _pm(st, nd), _ci(st, nd), note]


_MEM_NAME = {
    "dpp_mean_nm": ("磷酸頭基間距（膜厚，nm）", "Phosphate–phosphate distance (thickness, nm)", "リン酸頭部間の距離（膜厚、nm）", "인산 머리기 간 거리(막 두께, nm)"),
    "apl_mean_nm2": ("單脂面積（nm²）", "Area per lipid (nm²)", "脂質 1 分子あたりの面積（nm²）", "지질당 면적(nm²)"),
    "core_water": ("疏水核心的水分子數", "Water molecules in the hydrophobic core", "疎水性コアの水分子数", "소수성 핵심의 물 분자 수"),
}


def structure_html(doc, agg: dict, key: str) -> str:
    """DSSP, DCCM, PCA basin shares, clusters, tICA/MSM qualification, hydration sites and membrane metrics across replicas
    (D-142).  Reads the aggregate written by ``Workflow.analyse``; blocks that could not be computed are listed with their reason."""
    L = doc.lang
    T = lambda zh, en, ja, ko: tx((zh, en, ja, ko), L)             # noqa: E731
    st_ = agg.get("structure") or {}
    out, na = "", []
    kn = lambda k, n: _kn(L, k, n)                                  # noqa: E731
    h = tx((f"{key}：結構與動態的跨重複彙總", f"{key}: structure and dynamics across replicas", f"{key}：構造と動きの反復間の集計",
            f"{key}: 구조와 동역학의 반복 간 요약"), L)
    head_stat = [T("項目", "Item", "項目", "항목"), "n", T("平均 ± 標準差", "Mean ± SD", "平均 ± 標準偏差", "평균 ± 표준편차"),
                 T("95 % 信賴區間", "95 % CI", "95 % 信頼区間", "95 % 신뢰구간"), T("備註", "Note", "備考", "비고")]
    # ---- DSSP
    d = st_.get("dssp") or {}
    if d.get("status") == "ok":
        names = {"H": T("螺旋 H 的幀比例", "Helix (H) fraction", "ヘリックス H の割合", "나선 H 비율"),
                 "E": T("β 股 E 的幀比例", "Strand (E) fraction", "ストランド E の割合", "스트랜드 E 비율"),
                 "C": T("無規則 C 的幀比例", "Coil (C) fraction", "コイル C の割合", "코일 C 비율")}
        rows = [_stat_row(L, names[c], v, 3) for c, v in (d.get("overall_fraction") or {}).items()]
        out += doc.table(head_stat, rows, (f"{key} 二級結構比例（每條重複先取時間平均，再跨重複彙總）。",
                                           f"Secondary structure of {key} (time mean per replica, then across replicas).",
                                           f"{key} の二次構造の割合（反復ごとに時間平均し、反復間で集計）。",
                                           f"{key}의 이차 구조 비율(반복마다 시간 평균을 낸 뒤 반복 간 요약)."), {1, 2, 3})
        worst = []
        for c in ("H", "E"):
            for w in ((d.get("per_residue") or {}).get(c) or {}).get("least_reproducible") or []:
                worst.append([_esc(w["residue"]), c, f"{w['mean']:.2f} ± {w['sd']:.2f}"])
        if worst:
            out += doc.table([T("殘基", "Residue", "残基", "잔기"), T("結構", "Type", "種類", "유형"),
                              T("占比 平均 ± 標準差", "Fraction mean ± SD", "割合 平均 ± 標準偏差", "비율 평균 ± 표준편차")], worst[:10],
                             ("重複之間差異最大的殘基（標準差最大的前幾名）。", "Residues that differ most between replicas (largest SD).",
                              "反復間で最も差が大きい残基（標準偏差が大きい順）。", "반복 간 차이가 가장 큰 잔기(표준편차가 큰 순)."), {2})
    else:
        na.append((T("二級結構", "Secondary structure", "二次構造", "이차 구조"), _unavail_reason(d)))
    # ---- DCCM
    d = st_.get("dccm") or {}
    if d.get("status") == "ok":
        lr = d.get("long_range") or {}
        rows = [_stat_row(L, T("遠距離殘基對的平均 |相關|", "Mean |correlation| of long-range pairs", "遠距離ペアの平均 |相関|", "원거리 쌍의 평균 |상관|"),
                          lr.get("mean_abs_correlation") or {}, 3)]
        out += doc.table(head_stat, rows, (f"{key} 的 DCCM（遠距離＝殘基序號相差 ≥ {d['thresholds']['min_separation']}；矩陣逐元素的平均與標準差存在彙總檔）。",
                                           f"DCCM of {key} (long-range = residue index separation ≥ {d['thresholds']['min_separation']}; element-wise mean and SD are in the replica-set file).",
                                           f"{key} の DCCM（遠距離＝残基番号の差が {d['thresholds']['min_separation']} 以上。要素ごとの平均と標準偏差は集計ファイルにあります）。",
                                           f"{key}의 DCCM(원거리 = 잔기 번호 차이 ≥ {d['thresholds']['min_separation']}; 원소별 평균과 표준편차는 요약 파일에 있음)."), {1, 2, 3})
        if lr.get("top_pairs"):
            out += doc.table([T("殘基對", "Residue pair", "残基ペア", "잔기 쌍"), T("相關 平均 ± 標準差", "Correlation mean ± SD", "相関 平均 ± 標準偏差", "상관 평균 ± 표준편차"),
                              T("正負號一致的重複", "Replicas with the same sign", "符号が一致した反復", "부호가 일치한 반복")],
                             [[_esc(f"{x['i']} – {x['j']}"), f"{x['mean']:+.2f} ± {x['sd']:.2f}", _esc(kn(x["sign_k"], x["sign_n"]))] for x in lr["top_pairs"][:8]],
                             (f"相關最強的遠距離殘基對。強相關對 {lr.get('n_strong_pairs', 0)} 個，其中每條重複都同號且 |C| ≥ {d['thresholds']['replica_min']} 的有 {lr.get('n_strong_reproducible')} 個。",
                              f"Strongest long-range pairs. {lr.get('n_strong_pairs', 0)} strong pairs; {lr.get('n_strong_reproducible')} have the same sign with |C| ≥ {d['thresholds']['replica_min']} in every replica.",
                              f"相関が最も強い遠距離ペア。強い相関のペアは {lr.get('n_strong_pairs', 0)} 個で、全反復で同符号かつ |C| ≥ {d['thresholds']['replica_min']} のものは {lr.get('n_strong_reproducible')} 個です。",
                              f"상관이 가장 강한 원거리 쌍. 강한 쌍 {lr.get('n_strong_pairs', 0)}개 중 모든 반복에서 같은 부호이고 |C| ≥ {d['thresholds']['replica_min']}인 것은 {lr.get('n_strong_reproducible')}개."), {1})
        if d.get("mean"):
            from .replica_figs import dccm_replicas
            from .figure_text import S
            png = dccm_replicas(d["mean"], d.get("sd"), doc.figdir / f"md_dccm_replicas_{key}.png", ticks=d.get("residues"))
            nsr = lr.get("n_strong_reproducible")
            fnd = [S("note", f"{key}：{d['n']} 條重複的 DCCM 平均。遠距離的強相關對 {lr.get('n_strong_pairs', 0)} 個，每條重複都同號的有 {nsr if nsr is not None else '不可得（單一軌跡）'} 個。",
                     f"{key}: DCCM averaged over {d['n']} replicas. {lr.get('n_strong_pairs', 0)} strong long-range pairs; {nsr if nsr is not None else 'not available (single trajectory)'} keep the same sign in every replica.",
                     f"{key}：{d['n']} 本の反復で平均した DCCM。遠距離の強い相関ペアは {lr.get('n_strong_pairs', 0)} 個で、全反復で同符号のものは {nsr if nsr is not None else '算出不可（単一の軌跡）'} 個です。",
                     f"{key}: 반복 {d['n']}개로 평균한 DCCM. 원거리 강한 상관 쌍 {lr.get('n_strong_pairs', 0)}개 중 모든 반복에서 같은 부호인 것은 {nsr if nsr is not None else '계산 불가(단일 궤적)'}개.")]
            out += doc.figure_block(png, "dccm_replicas", fnd, key)
    else:
        na.append((T("DCCM", "DCCM", "DCCM", "DCCM"), _unavail_reason(d)))
    # ---- PCA basin shares (common basis only) and clusters
    d = st_.get("pca_basins") or {}
    if d.get("status") == "ok":
        rows = []
        for b in d["basins"][:8]:
            flag = ("" if b["inconsistent"] is None else
                    f"<b class=warn>{_esc(T('重複之間差異大', 'differs between replicas', '反復間で差が大きい', '반복 간 차이가 큼'))}</b>" if b["inconsistent"] else "")
            rows.append([str(b["basin"]), f"({b['xy'][0]:.1f}, {b['xy'][1]:.1f})", _pm(b["share"], 2), _ci(b["share"], 2),
                         "—" if b["range"] is None else f"{b['range']:.2f}", flag])
        out += doc.table([T("低谷", "Basin", "谷", "골"), T("中心（共同 PC 軸）", "Centre (common PC axes)", "中心（共通の PC 軸）", "중심(공통 PC 축)"),
                          T("占比 平均 ± 標準差", "Share mean ± SD", "割合 平均 ± 標準偏差", "비율 평균 ± 표준편차"), T("95 % 信賴區間", "95 % CI", "95 % 信頼区間", "95 % 신뢰구간"),
                          T("範圍（最大 − 最小）", "Range (max − min)", "範囲（最大 − 最小）", "범위(최대 − 최소)"), T("備註", "Note", "備考", "비고")], rows,
                         (f"{key} 在共同基底上各低谷的佔比（每條重複各自的占比，再跨重複彙總）。{d.get('interpretation', '')}",
                          f"Basin shares of {key} on the common basis (one share per replica, then across replicas). " + ("Replicas differ a lot: this is a sampled distribution, not converged." if d.get("inconsistent_basins") else "Shares agree within the threshold; this does not prove convergence."),
                          f"{key} の共通基底での谷の割合（反復ごとの割合を反復間で集計）。" + ("反復間の差が大きく、これはサンプリングした分布で収束していません。" if d.get("inconsistent_basins") else "割合はしきい値内で一致していますが、収束の証明ではありません。"),
                          f"{key}의 공통 기저에서 골별 비율(반복마다 비율을 구해 반복 간 요약). " + ("반복 간 차이가 커서 표본 분포일 뿐 수렴하지 않았습니다." if d.get("inconsistent_basins") else "비율이 기준 안에서 일치하지만 수렴의 증명은 아닙니다.")), {2, 3, 4})
        if d.get("inconsistent_basins"):
            doc.collected.append(I.F("caution",
                                     f"{key} 的低谷佔比在重複之間差很多：地形是取樣到的分布，未收斂。",
                                     f"The basin shares of {key} differ a lot between replicas: the landscape is a sampled distribution and has not converged.",
                                     f"{key} の谷の割合は反復間で大きく異なります。地形はサンプリングした分布で、収束していません。",
                                     f"{key}의 골 비율이 반복 간에 크게 다릅니다. 지형은 표본 분포이며 수렴하지 않았습니다."))
    else:
        na.append((T("PCA 低谷佔比", "PCA basin shares", "PCA の谷の割合", "PCA 골 비율"), (d.get("reason") or "") + ("" if d.get("status") != "not_comparable" else
                  T("（不可比）", " (not comparable)", "（比較不可）", "(비교 불가)"))))
    d = st_.get("clusters") or {}
    if d.get("status") == "ok":
        out += doc.table(head_stat, [_stat_row(L, T("群數", "Number of clusters", "クラスター数", "클러스터 수"), d["n_clusters"], 1),
                                     _stat_row(L, T("最大群的占比", "Share of the largest cluster", "最大クラスターの割合", "가장 큰 클러스터의 비율"), d["largest_cluster_share"], 2)],
                         (f"{key} 的分群：分群在每條重複內各自進行，群編號不對應，所以只彙總與編號無關的數。",
                          f"Clusters of {key}: made inside each replica, labels are not matched, so only label-free numbers are combined.",
                          f"{key} のクラスタリング：反復ごとに行い、クラスター番号は対応しないため、番号に依存しない値だけを集計しています。",
                          f"{key}의 클러스터링: 반복마다 따로 수행해 번호가 대응하지 않으므로 번호와 무관한 값만 요약합니다."), {1, 2, 3})
    else:
        na.append((T("分群", "Clusters", "クラスタリング", "클러스터링"), _unavail_reason(d)))
    # ---- tICA / MSM
    d = st_.get("tica_msm") or {}
    if d.get("status") == "ok":
        rows = []
        for x in d["per_replica"]:
            el = x.get("msm_eligibility") or x.get("tica_status") or "—"
            rows.append([_esc(x["run_id"]), _esc(str(el)), "—" if x.get("lag_ns") is None else f"{x['lag_ns']}",
                         "—" if x.get("slowest_timescale_ns") is None else f"{x['slowest_timescale_ns']:.3g}",
                         "—" if x.get("its_flat") is None else (T("是", "yes", "はい", "예") if x["its_flat"] else T("否", "no", "いいえ", "아니오"))])
        out += doc.table([T("重複（run）", "Replica (run)", "反復（run）", "반복(run)"), T("資格", "Eligibility", "適格性", "적격성"), T("延遲（ns）", "Lag (ns)", "遅れ（ns）", "지연(ns)"),
                          T("最慢時間尺度（ns）", "Slowest timescale (ns)", "最も遅い時間スケール（ns）", "가장 느린 시간 척도(ns)"),
                          T("對延遲持平", "Level with lag", "遅れに対して平ら", "지연에 대해 평평")], rows,
                         (f"{key} 的 tICA／馬可夫模型：{d['qualifies_n']} 條中 {d['qualifies_k']} 條合格。軌跡不合併、不報平均時間尺度或速率。" + ("" if d.get("rate_reportable") else d.get("rate_reason", "")),
                          f"tICA / Markov model of {key}: {d['qualifies_k']} of {d['qualifies_n']} replicas qualify. Trajectories are never pooled and no mean timescale or rate is reported.",
                          f"{key} の tICA／マルコフモデル：{d['qualifies_n']} 本中 {d['qualifies_k']} 本が適格です。軌跡は統合せず、平均の時間スケールや速度は示しません。",
                          f"{key}의 tICA／마르코프 모델: {d['qualifies_n']}개 중 {d['qualifies_k']}개가 적격입니다. 궤적은 합치지 않으며 평균 시간 척도나 속도는 제시하지 않습니다."), {2, 3})
    else:
        na.append((T("tICA／馬可夫模型", "tICA / Markov model", "tICA／マルコフモデル", "tICA／마르코프 모델"), _unavail_reason(d)))
    # ---- hydration sites per ligand
    for ln, lig in (agg.get("ligands") or {}).items():
        d = lig.get("hydration") or {}
        if d.get("status") != "ok":
            na.append((T(f"{ln} 水合位點", f"{ln} hydration sites", f"{ln} の水和サイト", f"{ln} 수화 위치"), _unavail_reason(d)))
            continue
        rows = []
        for x in d["sites"][:10]:
            lab = {"reproduced": T("重現", "reproduced", "再現", "재현"), "not_reproduced": f"<b class=warn>{_esc(T('未重現', 'not reproduced', '再現せず', '재현 안 됨'))}</b>",
                   "unavailable": "—"}[x["status"]]
            rows.append([_esc("(" + ", ".join(f"{v:.2f}" for v in x["xyz_nm"]) + ")"), _esc(kn(x["detected_k"], x["detected_n"])),
                         _pm(x["occupancy_among_detecting"], 2), lab])
        out += doc.table([T("位點座標（nm）", "Site position (nm)", "サイト座標（nm）", "위치 좌표(nm)"), T("偵測到的重複", "Replicas that detected it", "検出した反復", "검출한 반복"),
                          T("占有率 平均 ± 標準差（只含偵測到的重複）", "Occupancy mean ± SD (detecting replicas only)", "占有率 平均 ± 標準偏差（検出した反復のみ）", "점유율 평균 ± 표준편차(검출한 반복만)"),
                          T("狀態", "Status", "状態", "상태")], rows,
                         (f"{ln} 周圍的水合位點。不同重複的位點距離 ≤ {d['match_tolerance_nm']} nm 視為同一個；只在一條重複出現的位點標「未重現」。",
                          f"Hydration sites around {ln}. Sites of different replicas within {d['match_tolerance_nm']} nm count as the same; a site seen in one replica only is marked not reproduced.",
                          f"{ln} の周りの水和サイト。反復間で {d['match_tolerance_nm']} nm 以内のサイトは同一とみなし、1 本の反復にしか現れないサイトは再現せずと表示します。",
                          f"{ln} 주변의 수화 위치. 반복 간 {d['match_tolerance_nm']} nm 이내의 위치는 같은 것으로 보고, 한 반복에서만 나타난 위치는 재현 안 됨으로 표시합니다."), {2})
    # ---- membrane
    d = agg.get("membrane") or {}
    if d.get("status") == "ok":
        rows = [_stat_row(L, tx(_MEM_NAME.get(k_, (k_,) * 4), L), o, 3, ("" if not o.get("divergent") else f"<b class=warn>{_esc(T('重複之間差異大', 'replicas differ a lot', '反復間の差が大きい', '반복 간 차이가 큼'))}</b>"))
                for k_, o in (d.get("observables") or {}).items()]
        for nm, sol in (d.get("solutes") or {}).items():
            rows.append(_stat_row(L, f"{nm}: " + T("平均插入深度（nm）", "mean insertion depth (nm)", "平均挿入深さ（nm）", "평균 삽입 깊이(nm)"), sol["mean_com_depth_nm"], 3))
            cc = sol["crossed_centre"]
            rows.append([_esc(f"{nm}: " + T("穿過膜中心", "crossed the membrane centre", "膜の中心を横切った", "막 중심을 통과")), str(cc["n"]), _esc(kn(cc["k"], cc["n"])), "—", ""])
        if d.get("acceptance_pass"):
            ap = d["acceptance_pass"]
            rows.append([_esc(T("膜平衡驗收通過", "membrane equilibration accepted", "膜平衡化の検収に合格", "막 평형 검수 통과")), str(ap["n"]), _esc(kn(ap["k"], ap["n"])), "—", ""])
        if rows:
            out += doc.table(head_stat, rows, (f"{key} 的膜指標（每條重複取後半段平均，再跨重複彙總）。",
                                               f"Membrane metrics of {key} (second-half mean per replica, then across replicas).",
                                               f"{key} の膜の指標（反復ごとに後半の平均を取り、反復間で集計）。",
                                               f"{key}의 막 지표(반복마다 후반부 평균을 낸 뒤 반복 간 요약)."), {1, 2, 3})
    if na:
        out += ("<p class=muted>" + _esc(T("沒有彙總的項目：", "Not aggregated: ", "集計できなかった項目：", "요약하지 못한 항목: ")) +
                _esc("；".join(f"{a}（{b}）" if b else str(a) for a, b in na)) + "</p>")
    return (f"<h4>{_esc(h)}</h4>" + out) if out else out



def delta_rmsf_html(doc, comp: dict) -> str:
    """Apo–complex ΔRMSF per residue with the between-replica Welch CI (D-142).  Reads the file written by
    ``Workflow._replica_cross_system``; says plainly when a side has fewer than 2 replicas or the systems are not comparable."""
    path = (comp or {}).get("delta_rmsf_replicas_file")
    data = load_json(path, {}) if path else {}
    if not data or data.get("schema") != "md20.delta_rmsf_replicas/1":
        return ""
    L = doc.lang
    T = lambda zh, en, ja, ko: tx((zh, en, ja, ko), L)             # noqa: E731
    out = f"<h4>{_esc(T('apo 與複合物的逐殘基 ΔRMSF（重複之間的區間）', 'Apo–complex ΔRMSF per residue (between-replica interval)', 'apo と複合体の残基ごとの ΔRMSF（反復間の区間）', 'apo와 복합체의 잔기별 ΔRMSF(반복 간 구간)'))}</h4>"
    for other, p in (data.get("pairs") or {}).items():
        ref = data.get("ref")
        st = p.get("status")
        if st == "not_comparable":
            out += "<p class=muted>" + _esc(T(f"{other} 與 {ref} 的條件不同或無法確認，不計算 ΔRMSF。", f"{other} and {ref} differ in conditions or the conditions are unknown; ΔRMSF is not computed.",
                                              f"{other} と {ref} は条件が異なるか確認できないため、ΔRMSF は計算しません。", f"{other}와 {ref}는 조건이 다르거나 확인할 수 없어 ΔRMSF를 계산하지 않습니다.")) + "</p>"
            continue
        if st != "ok":
            out += "<p class=muted>" + _esc(T(f"{other} 對 {ref}：不可得。", f"{other} versus {ref}: unavailable.", f"{other} と {ref}：算出できません。", f"{other} 대 {ref}: 계산할 수 없습니다.")) + " " + _esc(p.get("reason") or "") + "</p>"
            continue
        rows = []
        for tag, lst in (("up", p.get("most_flexible") or []), ("down", p.get("most_rigidified") or [])):
            for x in lst[:6]:
                rows.append([_esc(x["residue"]), f"{x['delta_A']:+.2f}", f"[{x['ci95_low']:+.2f}, {x['ci95_high']:+.2f}]", _esc(_kn(L, x["sign_k"], x["sign_n"]))])
        if p.get("residues"):
            from .replica_figs import delta_rmsf_replicas
            from .figure_text import S
            png = delta_rmsf_replicas(p["residues"], doc.figdir / f"md_delta_rmsf_replicas_{other}.png", label=other)
            fnd = [S("note", f"{other} 對 {ref}：{p['n_common']} 個殘基中 {p['n_ci_excludes_zero']} 個的區間不含 0，單憑機率預期約 {p['expected_false_positives']} 個。未做多重比較校正。",
                     f"{other} versus {ref}: the interval excludes 0 for {p['n_ci_excludes_zero']} of {p['n_common']} residues; about {p['expected_false_positives']} are expected by chance. No multiple-comparison correction.",
                     f"{other} と {ref}：{p['n_common']} 残基中 {p['n_ci_excludes_zero']} 個で区間が 0 を含みません。偶然だけでも約 {p['expected_false_positives']} 個が見込まれます。多重比較の補正はありません。",
                     f"{other} 대 {ref}: {p['n_common']}개 잔기 중 {p['n_ci_excludes_zero']}개에서 구간이 0을 포함하지 않으며, 우연만으로도 약 {p['expected_false_positives']}개가 예상됩니다. 다중 비교 보정은 없습니다.")]
            out += doc.figure_block(png, "delta_rmsf_replicas", fnd, other)
        if rows:
            out += doc.table([T("殘基", "Residue", "残基", "잔기"), T("ΔRMSF 差值（Å）", "ΔRMSF (Å)", "ΔRMSF の差（Å）", "ΔRMSF 차이(Å)"), T("95 % 信賴區間（Welch）", "95 % CI (Welch)", "95 % 信頼区間（Welch）", "95 % 신뢰구간(Welch)"),
                              T("方向一致的重複", "Replicas with the same direction", "方向が一致した反復", "방향이 일치한 반복")], rows,
                             (f"{other} 減 {ref} 的逐殘基 RMSF 差（{ref} {p['n_ref']} 條、{other} {p['n_other']} 條重複）；只列區間不含 0 的殘基。{p['n_common']} 個殘基中 {p['n_ci_excludes_zero']} 個區間不含 0，單憑機率預期約 {p['expected_false_positives']} 個（未做多重比較校正）。",
                              f"RMSF of {other} minus {ref} per residue ({p['n_ref']} replicas of {ref}, {p['n_other']} of {other}); only residues whose interval excludes 0 are listed. {p['n_ci_excludes_zero']} of {p['n_common']} residues exclude 0; about {p['expected_false_positives']} are expected by chance alone (no multiple-comparison correction).",
                              f"{other} から {ref} を引いた残基ごとの RMSF の差（{ref} {p['n_ref']} 本、{other} {p['n_other']} 本）。区間が 0 を含まない残基のみ掲載。{p['n_common']} 残基中 {p['n_ci_excludes_zero']} 個が 0 を含まず、偶然だけでも約 {p['expected_false_positives']} 個が見込まれます（多重比較の補正なし）。",
                              f"{other}에서 {ref}를 뺀 잔기별 RMSF 차이({ref} {p['n_ref']}개, {other} {p['n_other']}개 반복). 구간이 0을 포함하지 않는 잔기만 나열. {p['n_common']}개 중 {p['n_ci_excludes_zero']}개가 0을 포함하지 않으며 우연만으로도 약 {p['expected_false_positives']}개가 예상됩니다(다중 비교 보정 없음)."), {1})
        else:
            out += "<p class=muted>" + _esc(T(f"{other} 對 {ref}：{p['n_common']} 個殘基的區間都含 0，看不出差異。", f"{other} versus {ref}: the interval contains 0 for all {p['n_common']} residues; no difference is seen.",
                                              f"{other} と {ref}：{p['n_common']} 残基すべてで区間が 0 を含み、差は見えません。", f"{other} 대 {ref}: {p['n_common']}개 잔기 모두 구간이 0을 포함해 차이가 보이지 않습니다.")) + "</p>"
    return out
