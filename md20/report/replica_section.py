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
        doc.collected += _caution_texts(agg, key)
    return out
