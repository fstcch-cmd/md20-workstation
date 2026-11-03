"""Report sections for the D-80/D-81 subsystems (D-82): structure prediction, membrane systems, long runs and
coarse-grained Martini.  Each section appears only when its data exist and follows the five-part order of
workflow_report (what, meaning, parameters used vs recommended, numbered figures and tables, interpretation).

Data read (contract, docs/specs/report_language.md §F43–F57):
  state["fold"][ligand]                          written by Workflow._fold_peptide / _fold_complex (build/fold.py)
  analysis.summaries[system]["membrane_metrics_file"]  analysis/membrane_run.py (APL, P–P, core water, insertion per
                                                 solute, acceptance gate), written by Workflow.analyse
  analysis.summaries[system]["membrane_file"]    richer JSON from analysis/membrane_report.membrane_report_data
                                                 (density, S_CD, head-group residence, tilt, thickness map); merged over the above
  state["long_run"][system]                      LongRunPlan.to_dict() written by Workflow._plan_long_run
                                                 (+ optional "actual": {"production_ns", "disk_gb", "days"})
  metrics / stream_metrics.json                  rmsd_backbone_A, rmsf_first_half_A, rmsf_second_half_A (analysis/stream.py)
  extended clusters labels                       analysis/extended (cluster timeline)
  state["coarse_grained"][name]                  {"plan": CGPlan.to_dict(), "membrane_file" | "membrane": {...}, "settings": {...}}
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..advisor import tx
from ..i18n import colon, norm
from ..util import load_json
from . import figure_text as FT
from . import figures as FG
from . import interpret as I

SUB_SECTIONS = {
    "fold": {
        "title": ("胜肽結構預測（一鍵摺疊）", "Peptide structure prediction (one-click folding)", "ペプチドの構造予測（ワンクリック折りたたみ）",
                  "펩타이드 구조 예측(원클릭 폴딩)"),
        "what": ("由胜肽序列預測三維結構，或連同受體一起預測複合物。單獨胜肽的預測結構在對接時固定主鏈。複合物的預測以序列比對配對的 Cα 疊合到實際受體，只取胜肽姿勢，不經對接直接進入 MD。",
                 "The three-dimensional structure is predicted from the peptide sequence, or the complex is predicted together "
                 "with the receptor. A predicted single peptide is docked with its backbone held fixed. For a complex, the "
                 "sequence-matched Cα are superposed on the actual receptor, only the peptide pose is taken, and it goes to MD without docking.",
                 "ペプチドの配列から立体構造を予測するか、受容体と一緒に複合体として予測します。単独のペプチドの予測構造は、ドッキングで主鎖を固定して使います。"
                 "複合体の予測では配列アラインメントで対応づけた Cα を実際の受容体に重ね合わせ、ペプチドのポーズだけを取り出してドッキングを経ずに MD に進めます。",
                 "펩타이드 서열로 3차원 구조를 예측하거나 수용체와 함께 복합체로 예측합니다. 단독 펩타이드의 예측 구조는 도킹할 때 주사슬을 고정해서 씁니다. "
                 "복합체 예측에서는 서열 정렬로 짝지은 Cα를 실제 수용체에 겹치고 펩타이드 포즈만 가져와 도킹 없이 MD로 보냅니다."),
        "meaning": ("胜肽很柔軟，從延伸構形對接常找不到正確的摺疊。預測結構給出合理的起始構形，但它是模型的推測：pLDDT 與 ipTM 只是模型的自信程度，不是和實驗比較的誤差。"
                    "沒有對接分數的胜肽，結合的強弱只能由 MD 與自由能計算判斷。",
                    "Peptides are flexible, and docking from an extended build often misses the right fold. A predicted structure "
                    "gives a reasonable start, but it is the model's guess. pLDDT and ipTM measure the model's confidence, not "
                    "an error against experiment. For a peptide without a docking score, binding strength can only be judged "
                    "from MD and free-energy calculations.",
                    "ペプチドは柔らかく、伸びた構造からドッキングすると正しい折りたたみが見つからないことがよくあります。予測構造は妥当な初期構造を与えますが、それはモデルの推測です。"
                    "pLDDT と ipTM はモデルの確信度で、実験との誤差ではありません。ドッキングスコアのないペプチドでは、結合の強さは MD と自由エネルギー計算でしか判断できません。",
                    "펩타이드는 유연해서 늘어난 구조에서 도킹하면 올바른 접힘을 찾지 못하는 경우가 많습니다. 예측 구조는 타당한 시작 구조를 주지만 모델의 추측입니다. "
                    "pLDDT와 ipTM은 모델의 확신도이며 실험과 비교한 오차가 아닙니다. 도킹 점수가 없는 펩타이드는 결합 세기를 MD와 자유 에너지 계산으로만 판단할 수 있습니다."),
    },
    "membrane": {
        "title": ("膜系統", "Membrane system", "膜の系", "막 시스템"),
        "what": ("在脂雙層中模擬膜蛋白，或模擬胜肽與小分子在膜表面的吸附，或只模擬膜本身。分析每個脂質的面積、厚度、密度剖面、脂肪鏈序參數，以及溶質的插入深度、與頭基的接觸和傾角。",
                 "A membrane protein is simulated in a lipid bilayer, a peptide or small molecule is simulated adsorbing on a "
                 "membrane surface, or the membrane alone is simulated. The analysis covers area per lipid, thickness, density "
                 "profile and acyl-chain order, and for the solute its insertion depth, head-group contacts and tilt.",
                 "脂質二重膜の中で膜タンパク質をシミュレーションするか、ペプチドや低分子が膜表面に吸着する様子をシミュレーションするか、膜だけをシミュレーションします。"
                 "脂質あたりの面積、厚さ、密度分布、アシル鎖の秩序と、溶質の挿入の深さ、頭部基との接触、傾きを解析します。",
                 "지질 이중층 안에서 막단백질을 시뮬레이션하거나, 펩타이드나 저분자가 막 표면에 흡착하는 과정을 시뮬레이션하거나, 막만 시뮬레이션합니다. "
                 "지질당 면적, 두께, 밀도 분포, 아실 사슬 질서와 용질의 삽입 깊이, 머리 부분과의 접촉, 기울기를 분석합니다."),
        "meaning": ("膜蛋白在水中會變形，抗菌胜肽的作用發生在膜上，所以這些系統必須有膜。膜本身要先平衡：面積、厚度與序參數落在實驗範圍，溶質的結果才有意義。"
                    "表面接觸的模擬回答吸附在哪裡、靠哪些殘基、躺著還是插入。它不回答能不能穿過膜。",
                    "A membrane protein deforms in water, and antimicrobial peptides act on membranes, so these systems need a "
                    "bilayer. The membrane itself must equilibrate first. Only when area, thickness and order fall in the "
                    "experimental range do the solute results mean anything. A surface simulation answers where the solute "
                    "adsorbs, through which residues, and whether it lies flat or inserts. It does not answer whether it crosses the membrane.",
                    "膜タンパク質は水中では変形し、抗菌ペプチドは膜の上で働くため、これらの系には膜が必要です。まず膜自体が平衡に達している必要があり、面積、厚さ、秩序が実験の範囲に入って初めて溶質の結果に意味が出ます。"
                    "表面接触のシミュレーションは、どこに、どの残基で吸着し、寝ているのか入り込んでいるのかに答えます。膜を通過できるかには答えません。",
                    "막단백질은 물속에서 변형되고 항균 펩타이드는 막 위에서 작용하므로 이 시스템에는 막이 필요합니다. 먼저 막 자체가 평형에 도달해야 합니다. 면적, 두께, 질서가 실험 범위에 들어가야 용질 결과에 의미가 있습니다. "
                    "표면 접촉 시뮬레이션은 어디에, 어떤 잔기로 흡착하는지, 누워 있는지 삽입되는지에 답합니다. 막을 통과할 수 있는지에는 답하지 않습니다."),
    },
    "longrun": {
        "title": ("長時間模擬與收斂", "Long simulation and convergence", "長時間シミュレーションと収束", "장시간 시뮬레이션과 수렴"),
        "what": ("正式模擬超過 100 ns 時，MD20 先規劃存檔間隔、分段長度與硬碟用量，必要時只存溶質，並以分段串流的方式分析整條軌跡。本節比較規劃與實際，並檢查軌跡是否收斂。",
                 "For production longer than 100 ns, MD20 first plans the save interval, chunk length and disk use, saves only "
                 "the solute when needed, and analyses the whole trajectory chunk by chunk. This section compares the plan with "
                 "what happened and checks whether the trajectory has converged.",
                 "本計算が 100 ns を超える場合、MD20 はまず保存間隔、区間の長さ、ディスク使用量を計画し、必要なら溶質だけを保存し、軌跡全体を区間ごとに読み込んで解析します。"
                 "この節では計画と実績を比べ、軌跡が収束しているかを確かめます。",
                 "본 시뮬레이션이 100 ns를 넘으면 MD20은 먼저 저장 간격, 구간 길이, 디스크 사용량을 계획하고, 필요하면 용질만 저장하며, 궤적 전체를 구간별로 읽어 분석합니다. "
                 "이 절에서는 계획과 실제를 비교하고 궤적이 수렴했는지 확인합니다."),
        "meaning": ("時間越長，越能看到稀有的構形轉換，但只有收斂的軌跡才能代表平衡性質。前後兩半一致，是軌跡內部收斂的必要條件，不是充分條件：一條軌跡可能一直停在同一個能量盆地，"
                    "要用獨立重複確認。",
                    "A longer run shows rarer conformational transitions, but only a converged trajectory represents equilibrium "
                    "properties. Agreement between the two halves is necessary for convergence within a trajectory, not "
                    "sufficient. One trajectory can stay in one basin, and independent replicas are needed to confirm it.",
                    "計算が長いほどまれな構造遷移が見えますが、平衡の性質を表せるのは収束した軌跡だけです。前半と後半が一致することは軌跡内の収束の必要条件で、十分条件ではありません。"
                    "1 本の軌跡は同じエネルギーの谷にとどまり続けることがあり、独立な繰り返しで確かめる必要があります。",
                    "시뮬레이션이 길수록 드문 구조 전이를 볼 수 있지만 평형 성질을 나타내는 것은 수렴한 궤적뿐입니다. 전반부와 후반부의 일치는 궤적 내부 수렴의 필요조건이지 충분조건이 아닙니다. "
                    "궤적 하나가 한 에너지 분지에 계속 머물 수 있으므로 독립 반복으로 확인해야 합니다."),
    },
    "cg": {
        "title": ("粗粒化模擬（Martini 3）", "Coarse-grained simulation (Martini 3)", "粗視化シミュレーション（Martini 3）", "조립화 시뮬레이션(Martini 3)"),
        "what": ("以 martinize2 把蛋白轉成珠子模型、insane 建膜，再用 martini_openmm 在 OpenMM 執行。每顆珠子約代表 4 個重原子，時間步 20 fs。",
                 "martinize2 converts the protein to a bead model, insane builds the membrane, and martini_openmm runs it in "
                 "OpenMM. Each bead stands for about 4 heavy atoms and the time step is 20 fs.",
                 "martinize2 でタンパク質をビーズモデルに変換し、insane で膜を作り、martini_openmm で OpenMM 上で実行します。ビーズ 1 個はおよそ 4 個の重原子にあたり、時間刻みは 20 fs です。",
                 "martinize2로 단백질을 비드 모델로 바꾸고 insane으로 막을 만든 뒤 martini_openmm으로 OpenMM에서 실행합니다. 비드 하나가 중원자 약 4개이며 시간 간격은 20 fs입니다."),
        "meaning": ("粗粒化能在筆電上跑到微秒以上，適合看膜破壞、脂質重排與胜肽聚集。代價是沒有原子細節：沒有氫鍵、二級結構由彈性網路固定，動態比真實快。"
                    "要談原子層級的結合，必須轉回全原子再做短模擬。",
                    "Coarse-graining reaches microseconds and beyond on a laptop and suits membrane disruption, lipid "
                    "rearrangement and peptide aggregation. The price is atomic detail: there are no hydrogen bonds, the "
                    "secondary structure is held by an elastic network and the dynamics run faster than real ones. Atomic-level "
                    "binding needs a back-mapping to all atoms and a short atomistic run.",
                    "粗視化ならノートパソコンでもマイクロ秒以上の計算ができ、膜の破壊、脂質の再配置、ペプチドの凝集を見るのに向いています。代わりに原子の細部はありません。"
                    "水素結合はなく、二次構造は弾性ネットワークで固定され、動きは実際より速くなります。原子レベルの結合を論じるには、全原子に戻して短い計算をする必要があります。",
                    "조립화는 노트북에서도 마이크로초 이상까지 계산할 수 있어 막 파괴, 지질 재배열, 펩타이드 응집을 보기에 알맞습니다. 대신 원자 수준의 세부가 없습니다. "
                    "수소 결합이 없고 이차 구조는 탄성 네트워크로 고정되며 동역학이 실제보다 빠릅니다. 원자 수준의 결합을 논하려면 전원자로 되돌려 짧은 시뮬레이션을 해야 합니다."),
    },
}

_T = {
    "yes": ("是", "yes", "はい", "예"), "no": ("否", "no", "いいえ", "아니요"),
    "peptide": ("胜肽", "Peptide", "ペプチド", "펩타이드"), "mode": ("方式", "Mode", "方式", "방식"),
    "engine": ("預測引擎", "Engine", "予測エンジン", "예측 엔진"), "score": ("對接分數（kcal mol⁻¹）", "Docking score (kcal mol⁻¹)",
                                                                      "ドッキングスコア（kcal mol⁻¹）", "도킹 점수 (kcal mol⁻¹)"),
    "single": ("單獨胜肽", "peptide alone", "ペプチド単独", "펩타이드 단독"), "complex": ("受體＋胜肽複合物", "receptor + peptide complex",
                                                                                "受容体＋ペプチド複合体", "수용체 + 펩타이드 복합체"),
    "docked": ("見分子對接一節", "see the docking section", "ドッキングの節を参照", "도킹 절 참고"),
    "system": ("系統", "System", "系", "시스템"), "quantity": ("量", "Quantity", "量", "양"), "value": ("數值", "Value", "値", "값"),
}


def _t(key: str, L: str) -> str:
    return tx(_T[key], L)


def _W():
    from . import workflow_report as W
    return W


def _params(doc, rows: list[tuple], caption) -> str:
    """rows: (label 4-tuple, used, recommended, reason 4-tuple, changed)."""
    W, L = _W(), doc.lang
    out = []
    for lab, used, rec, why, changed in rows:
        tag = f"<span class='tag changed'>{W._esc(tx(W.H['changed'], L))}</span>" if changed else ""
        out.append([W._esc(tx(lab, L)), W._esc(str(used)) + tag, W._esc(str(rec)), W._esc(tx(why, L))])
    return doc.table([tx(W.H["parameter"], L), tx(W.H["value"], L), tx(W.H["recommended"], L), tx(W.H["reason"], L)], out, caption)


def _run_dir(wf, key: str) -> Path | None:
    st = wf.state()["steps"]
    c = ((st.get("md_cases") or {}).get("cases") or {}).get(key) or {}
    r = ((st.get("md_runs") or {}).get("runs") or {}).get(key) or {}
    if not c.get("case_id") or not r.get("run_ids"):
        return None
    try:
        from ..project import Run
        return Run(wf.project.case(c["case_id"]), r["run_ids"][0]).dir
    except Exception:  # noqa: BLE001
        return None


# ============================================================================================ fold
def fold_geometry(rec: dict) -> dict | None:
    """Per-residue deviation of the predicted receptor from the actual one after the stored superposition, and the
    peptide–receptor contact map of the placed complex.  Pure Python + numpy (build/fold.py parsers)."""
    from ..build import fold as F
    pl = rec.get("placement") or {}
    req = rec.get("request") or {}
    if not pl or not rec.get("pdb_path") or not Path(rec["pdb_path"]).is_file():
        return None
    try:
        pred = F.residues(F.read_structure(rec["pdb_path"]))
    except Exception:  # noqa: BLE001
        return None
    pc = rec.get("peptide_chain")
    out: dict = {"receptor_source": pl.get("receptor_source")}
    actual = pl.get("receptor_source") == "actual" and req.get("reference") and Path(req["reference"]).is_file()
    pep_pdb = pl.get("peptide_pdb")
    pep = (F.residues(F.read_structure(pep_pdb)).get(pc) if pep_pdb and Path(pep_pdb).is_file() else None) or pred.get(pc) or []
    if actual:
        ref = F.residues(F.read_structure(req["reference"]))
        R, t = (np.asarray(pl["transform"][0], float), np.asarray(pl["transform"][1], float)) if pl.get("transform") else (np.eye(3), np.zeros(3))
        labels, dev, xyz_ref = [], [], []
        for c, rc in (pl.get("chain_map") or {}).items():
            if c not in pred or rc not in ref:
                continue
            ps, rs = "".join(x["one"] for x in pred[c]), "".join(x["one"] for x in ref[rc])
            for i, j in F.align(ps, rs):
                a, b = pred[c][i]["atoms"].get("CA"), ref[rc][j]["atoms"].get("CA")
                if a and b:
                    p = np.array([a["x"], a["y"], a["z"]]) @ R.T + t
                    q = np.array([b["x"], b["y"], b["z"]])
                    labels.append(f"{ref[rc][j]['resname']}{ref[rc][j]['resseq']}")
                    dev.append(float(np.linalg.norm(p - q)))
                    xyz_ref.append(q)
        receptor = ref
    else:
        receptor = {c: v for c, v in pred.items() if c != pc}
        labels, dev, xyz_ref = [], [], []
    P = np.array([(a["x"], a["y"], a["z"]) for r in pep for a in r["atoms"].values()]) if pep else np.zeros((0, 3))
    if dev:
        Q = np.asarray(xyz_ref)
        near = np.sqrt(((Q[:, None, :] - P[None, :, :]) ** 2).sum(-1)).min(1) <= 10.0 if len(P) else np.zeros(len(Q), bool)
        out.update(labels=labels, dev=dev, pocket=near.tolist())
    if len(P):
        rows = [f"{r['resname']}{r['resseq']}" for r in pep]
        pep_xyz = [np.array([(a["x"], a["y"], a["z"]) for a in r["atoms"].values()]) for r in pep]
        cols, mats = [], []
        for c, rs in receptor.items():
            if c == pc and not actual:
                continue
            for r in rs:
                X = np.array([(a["x"], a["y"], a["z"]) for a in r["atoms"].values()])
                d = [float(np.sqrt(((X[:, None, :] - Y[None, :, :]) ** 2).sum(-1)).min()) for Y in pep_xyz]
                if min(d) <= 8.0:
                    cols.append(f"{r['resname']}{r['resseq']}")
                    mats.append(d)
        if cols:
            out.update(rows=rows, cols=cols, M=np.asarray(mats).T.round(2).tolist())
    return out


def fold_section(doc, wf) -> str:
    W = _W()
    folds = {k: v for k, v in (wf.state().get("fold") or {}).items() if isinstance(v, dict)}
    if not folds:
        return ""
    from ..build import fold as F
    L = doc.lang
    doc.section = tx(SUB_SECTIONS["fold"]["title"], L)
    lig = {l.get("name"): l for l in wf.cfg.get("ligands") or []}
    rows = []
    for name, rec in folds.items():
        req = rec.get("request") or {}
        complex_ = req.get("mode") == "complex"
        rec_engine = "boltz" if complex_ else "omegafold"
        used = req.get("engine") or "auto"
        rows.append(((f"{name}：預測引擎", f"{name}: engine", f"{name}：予測エンジン", f"{name}: 예측 엔진"),
                     f"{used} → {rec.get('engine') or '—'}", f"auto → {rec_engine}",
                     ("auto 依可用性與顯示卡記憶體選擇。單獨胜肽預設 OmegaFold（單序列、Apache-2.0），複合物預設 Boltz-2（可預測受體＋胜肽）。",
                      "auto chooses by availability and GPU memory. A single peptide defaults to OmegaFold (single sequence, "
                      "Apache-2.0) and a complex to Boltz-2 (predicts receptor + peptide).",
                      "auto は利用できるエンジンと GPU メモリで選びます。単独のペプチドは OmegaFold（単一配列、Apache-2.0）、複合体は Boltz-2（受容体＋ペプチドを予測可能）が既定です。",
                      "auto는 사용 가능 여부와 GPU 메모리로 고릅니다. 단독 펩타이드는 OmegaFold(단일 서열, Apache-2.0), 복합체는 Boltz-2(수용체 + 펩타이드 예측 가능)가 기본입니다."),
                     used not in ("auto", rec.get("engine"))))
        rows.append(((f"{name}：低 pLDDT 仍使用", f"{name}: use despite low pLDDT", f"{name}：低い pLDDT でも使用", f"{name}: 낮은 pLDDT에도 사용"),
                     _t("yes" if req.get("accept_low") else "no", L), _t("no", L),
                     ("pLDDT 平均 ≥ 70 通過，50 到 70 標註後使用，< 50 停下來讓你決定。", "Mean pLDDT ≥ 70 passes, 50–70 is used with a label, "
                      "and below 50 the workflow stops for your decision.", "平均 pLDDT ≥ 70 は合格、50〜70 は注記して使用、50 未満では止まって判断を求めます。",
                      "평균 pLDDT ≥ 70은 통과, 50~70은 표시 후 사용, 50 미만은 멈추고 결정을 요청합니다."), bool(req.get("accept_low"))))
        if complex_:
            rows.append(((f"{name}：疊合的 Cα RMSD 上限", f"{name}: Cα RMSD limit of the superposition", f"{name}：重ね合わせの Cα RMSD の上限",
                          f"{name}: 겹침 Cα RMSD 상한"),
                         f"{F.SUP_MAX_RMSD:g} Å" + (" (" + tx(("使用者接受超過", "user accepted above", "超過をユーザーが許可", "초과를 사용자가 허용"), L) + ")" if req.get("accept_rmsd") else ""),
                         f"{F.SUP_MAX_RMSD:g} Å",
                         (f"至少 {F.SUP_MIN_MATCHED} 個序列相同的 Cα 才疊合。超過 2 Å 代表預測的受體和實際受體不同，胜肽姿勢不能直接搬。",
                          f"At least {F.SUP_MIN_MATCHED} identical sequence-matched Cα are needed. Above 2 Å the predicted receptor differs "
                          "from the actual one and the peptide pose cannot simply be transferred.",
                          f"配列が一致する Cα が {F.SUP_MIN_MATCHED} 個以上あるときだけ重ね合わせます。2 Å を超えると予測した受容体は実際と異なり、ペプチドのポーズをそのまま移せません。",
                          f"서열이 같은 Cα가 {F.SUP_MIN_MATCHED}개 이상일 때만 겹칩니다. 2 Å을 넘으면 예측 수용체가 실제와 달라 펩타이드 포즈를 그대로 옮길 수 없습니다."),
                         bool(req.get("accept_rmsd"))))
    params = _params(doc, rows, ("結構預測參數", "Structure-prediction parameters", "構造予測のパラメータ", "구조 예측 매개변수"))
    start = len(doc.collected)
    trs, out, extra = [], "", []
    for name, rec in folds.items():
        req = rec.get("request") or {}
        pl = rec.get("placement") or {}
        complex_ = req.get("mode") == "complex"
        src = {"actual": ("實際受體", "actual receptor", "実際の受容体", "실제 수용체"),
               "predicted": ("預測受體", "predicted receptor", "予測した受容体", "예측 수용체")}.get(pl.get("receptor_source"))
        trs.append([W._esc(name), W._esc(_t("complex" if complex_ else "single", L)), W._esc(rec.get("engine") or "—"),
                    W._fmt(rec.get("mean_plddt"), 1), W._fmt(rec.get("iptm")), W._fmt(pl.get("rmsd_ca")), W._fmt(pl.get("pocket_rmsd_ca")),
                    str(pl.get("n_matched") or "—"), W._esc(tx(src, L) if src else "—"),
                    W._esc(I.score_text(None, L) if complex_ else _t("docked", L))])
        by = rec.get("plddt_by_chain") or ({rec.get("peptide_chain") or "A": rec.get("per_residue_plddt")} if rec.get("per_residue_plddt") else {})
        if by:
            out += doc.figure_block(FG.plddt_profile(by, doc.figdir / f"fold_plddt_{name}.png", peptide_chain=rec.get("peptide_chain")),
                                    "fold_plddt", FT.classify_fold_plddt(name, rec), name)
        geo = fold_geometry(rec) if complex_ else None
        if geo and geo.get("dev"):
            out += doc.figure_block(FG.residue_deviation(geo["labels"], geo["dev"], doc.figdir / f"fold_sup_{name}.png", pocket_mask=geo.get("pocket")),
                                    "fold_superposition",
                                    FT.classify_fold_superposition(name, geo["dev"], geo["labels"], pl.get("rmsd_ca"), pl.get("pocket_rmsd_ca"),
                                                                   geo.get("pocket"), F.SUP_MAX_RMSD), name)
        if geo and geo.get("M"):
            out += doc.figure_block(FG.contact_matrix(geo["rows"], geo["cols"], geo["M"], doc.figdir / f"fold_contacts_{name}.png"),
                                    "fold_contacts", FT.classify_fold_contacts(name, geo["rows"], geo["cols"], geo["M"]), name)
        notes = [n for n in (rec.get("notes") or []) if isinstance(n, dict)]
        if notes:
            out += "<ul class=muted>" + "".join(f"<li>{W._esc(tx(n, L))}</li>" for n in notes) + "</ul>"
        extra += I.fold(name, rec)
    tab = doc.table([_t("peptide", L), _t("mode", L), _t("engine", L), tx(("平均 pLDDT", "Mean pLDDT", "平均 pLDDT", "평균 pLDDT"), L), "ipTM",
                     tx(("疊合 Cα RMSD（Å）", "Superposition Cα RMSD (Å)", "重ね合わせ Cα RMSD（Å）", "겹침 Cα RMSD (Å)"), L),
                     tx(("結合位 Cα RMSD（Å）", "Site Cα RMSD (Å)", "結合部位 Cα RMSD（Å）", "결합 부위 Cα RMSD (Å)"), L),
                     tx(("配對 Cα", "Matched Cα", "対応 Cα", "짝지은 Cα"), L), tx(("受體", "Receptor", "受容体", "수용체"), L), _t("score", L)],
                    trs, ("結構預測結果", "Structure-prediction results", "構造予測の結果", "구조 예측 결과"), {3, 4, 5, 6, 7})
    findings = doc.collected[start:] + extra
    doc.collected += extra
    return W._section(doc, doc.next(), "fold", params, tab + out, findings)


# ============================================================================================ membrane
def adapt_membrane_metrics(mm: dict, time_ns=None) -> dict:
    """analysis/membrane_run.membrane_summary output → the report schema (membrane_report.py docstring)."""
    if not mm or mm.get("status") == "SKIPPED":
        return {}
    n = len(mm.get("dpp_nm") or [])
    t = list(time_ns or [])
    d = {"resolution": "atomistic", "type": mm.get("type"), "n_lipids": mm.get("n_lipids"),
         "time_ns": t if len(t) == n else list(range(n)), "time_is_frames": len(t) != n,
         "dpp_nm": mm.get("dpp_nm") or [], "apl_nm2": mm.get("apl_nm2") or [], "core_water": mm.get("core_water") or [],
         "approximate_apl": mm.get("type") == "protein", "acceptance": mm.get("acceptance")}
    ref = ((mm.get("acceptance") or {}).get("evidence") or {}).get("reference")
    if ref:
        d["reference"] = ref
    ins = mm.get("insertion") or {}
    if ins:
        d["insertion_by"] = {k: v for k, v in ins.items() if isinstance(v, dict)}
    return d


def _membrane_data(wf) -> dict:
    sums = (wf.state()["steps"].get("analysis") or {}).get("summaries") or {}
    out = {}
    for key, s in sums.items():
        s = s or {}
        d: dict = {}
        if s.get("membrane_metrics_file"):
            m = load_json(s.get("metrics_file"), {}) if s.get("metrics_file") else {}
            t = m.get("time_ns")
            if not t:
                a = long_run_actual(_run_dir(wf, key)).get("production_ns")
                nf = len(load_json(s["membrane_metrics_file"], {}).get("dpp_nm") or [])
                t = np.linspace(0, a, nf).round(4).tolist() if a and nf else None
            d = adapt_membrane_metrics(load_json(s["membrane_metrics_file"], {}), t)
        if s.get("membrane_file"):
            d.update(load_json(s["membrane_file"], {}))
        if d and d.get("resolution", "atomistic") != "coarse-grained" and (d.get("dpp_nm") or d.get("density")):
            out[key] = d
    return out


def _membrane_figures(doc, key: str, d: dict, cg: bool = False) -> str:
    out = ""
    sub = key + (" (CG)" if cg else "")
    t = d.get("time_ns") or []
    if not cg and d.get("apl_nm2"):
        out += doc.figure_block(FG.membrane_equil(t, d["apl_nm2"], d.get("dpp_nm") or [], d.get("reference"), doc.figdir / f"mem_equil_{key}.png"),
                                "membrane_equil", FT.classify_membrane_equil(key, t, d["apl_nm2"], d.get("dpp_nm") or [], d.get("reference"),
                                                                             d.get("approximate_apl", False)), sub)
    if d.get("density"):
        out += doc.figure_block(FG.density_profile(d["density"], doc.figdir / f"mem_density_{key}{'_cg' if cg else ''}.png"), "membrane_density",
                                FT.classify_density(sub, d["density"]), sub)
    if not cg and d.get("scd"):
        out += doc.figure_block(FG.scd_plot(FT.scd_series(d["scd"]), doc.figdir / f"mem_scd_{key}.png"), "membrane_scd", FT.classify_scd(key, d["scd"]), key)
    ins_all = dict(d.get("insertion_by") or {})
    if (d.get("insertion") or {}).get("com_depth_nm"):
        ins_all[""] = d["insertion"]
    for nm, ins in ins_all.items():
        if not ins.get("com_depth_nm"):
            continue
        s2 = f"{sub} {nm}".strip()
        out += doc.figure_block(FG.insertion_plot(t, ins["com_depth_nm"], ins.get("deepest_nm"), doc.figdir / f"mem_depth_{key}{('_' + nm) if nm else ''}.png"),
                                "insertion_depth", FT.classify_insertion(s2, t, ins["com_depth_nm"], ins.get("deepest_nm"), ins.get("crossed_centre", False)), s2)
    hg = d.get("headgroup_contacts") or []
    if hg:
        out += doc.figure_block(FG.bars([(r["residue"], r["fraction"]) for r in hg], "Fraction of time within 0.4 nm of a head group",
                                        doc.figdir / f"mem_contacts_{key}.png", thresholds=(0.5, 0.2)),
                                "headgroup_residence", FT.classify_headgroup(sub, hg), sub)
    if d.get("tilt_deg"):
        out += doc.figure_block(FG.tilt_hist(d["tilt_deg"], doc.figdir / f"mem_tilt_{key}.png"), "peptide_tilt", FT.classify_tilt(sub, d["tilt_deg"]), sub)
    if d.get("thickness_map"):
        out += doc.figure_block(FG.thickness_map_plot(d["thickness_map"], doc.figdir / f"mem_map_{key}{'_cg' if cg else ''}.png", d.get("solute_xy_nm")),
                                "thickness_map", FT.classify_thickness_map(sub, d["thickness_map"]), sub)
    return out


def _membrane_table(doc, data: dict) -> str:
    W, L = _W(), doc.lang
    rows = []
    for key, d in data.items():
        a, p = np.asarray(d.get("apl_nm2") or [np.nan], float), np.asarray(d.get("dpp_nm") or [np.nan], float)
        a2, p2 = a[len(a) // 2:], p[len(p) // 2:]
        ref = d.get("reference") or {}
        ins = (d.get("insertion") or {}).get("com_depth_nm") or next((v.get("com_depth_nm") for v in (d.get("insertion_by") or {}).values()), None)
        comp = ", ".join(f"{k} {v:g}" for k, v in (d.get("composition") or {}).items()) or "—"
        rows.append([W._esc(key), W._esc(d.get("type") or "—"), W._esc(comp), W._fmt(d.get("temperature_k"), 0),
                     f"{np.nanmean(a2):.3f} ± {np.nanstd(a2):.3f}", W._fmt(ref.get("apl_nm2"), 3),
                     f"{np.nanmean(p2):.2f} ± {np.nanstd(p2):.2f}", W._fmt(ref.get("dpp_nm")),
                     W._fmt(np.mean(ins[len(ins) // 2:]) if ins else None)])
    return doc.table([_t("system", L), tx(("類型", "Type", "種類", "유형"), L), tx(("脂質組成", "Lipids", "脂質組成", "지질 조성"), L), "T (K)",
                      tx(("面積（nm²，後半段）", "APL (nm², second half)", "面積（nm²、後半）", "면적 (nm², 후반부)"), L),
                      tx(("參考面積", "Reference APL", "参照面積", "참고 면적"), L),
                      tx(("P–P 厚度（nm，後半段）", "P–P (nm, second half)", "P–P 厚さ（nm、後半）", "P–P 두께 (nm, 후반부)"), L),
                      tx(("參考厚度", "Reference P–P", "参照厚さ", "참고 두께"), L),
                      tx(("插入深度（nm，後半段）", "Depth (nm, second half)", "挿入の深さ（nm、後半）", "삽입 깊이 (nm, 후반부)"), L)],
                     rows, ("膜性質摘要（參考值待查證，見 membrane.md §3.1）", "Membrane properties (reference values to be confirmed, membrane.md §3.1)",
                            "膜の性質のまとめ（参照値は要確認、membrane.md §3.1）", "막 성질 요약 (참고값 확인 필요, membrane.md §3.1)"), {3, 4, 5, 6, 7, 8})


def membrane_section(doc, wf) -> str:
    W = _W()
    spec = (wf.cfg.get("md") or {}).get("membrane")
    data = _membrane_data(wf)
    if not spec and not data:
        return ""
    from ..build import membrane as BM
    L = doc.lang
    doc.section = tx(SUB_SECTIONS["membrane"]["title"], L)
    s = {**BM.DEFAULTS, **(spec or {})}
    temp = BM.membrane_temperature(spec)
    lip = s.get("lipids")
    lip_txt = lip if isinstance(lip, str) else ", ".join(f"{k} {v}" for k, v in (lip or {}).items()) if isinstance(lip, dict) else str(lip)
    rows = [(("膜系統類型", "Membrane type", "膜の系の種類", "막 시스템 유형"), s.get("type"), "—",
             ("protein：膜蛋白嵌入脂雙層。surface：胜肽或小分子在膜表面。bilayer：只有膜。依研究問題決定，沒有預設建議。",
              "protein: a membrane protein in the bilayer. surface: a peptide or small molecule on the surface. bilayer: membrane only. "
              "The research question decides, so there is no default recommendation.",
              "protein は膜タンパク質を二重膜に埋め込んだ系、surface はペプチドや低分子を膜表面に置いた系、bilayer は膜だけの系です。研究の問いで決まるため既定の推奨はありません。",
              "protein은 막단백질을 이중층에 넣은 시스템, surface는 펩타이드나 저분자를 막 표면에 둔 시스템, bilayer는 막만 있는 시스템입니다. 연구 질문으로 정하므로 기본 권장값은 없습니다."), False),
            (("脂質組成", "Lipid composition", "脂質組成", "지질 조성"), lip_txt, "mammalian (POPC)",
             ("mammalian 是 POPC，bacterial 是 POPE:POPG 3:1。格蘭氏陽性菌的組成需要 CHARMM36 才有心磷脂與 lysyl-PG 參數，目前會擋下。",
              "mammalian is POPC and bacterial is POPE:POPG 3:1. A Gram-positive composition needs CHARMM36 for cardiolipin and "
              "lysyl-PG parameters and is blocked for now.",
              "mammalian は POPC、bacterial は POPE:POPG 3:1 です。グラム陽性菌の組成ではカルジオリピンとリシル PG のパラメータに CHARMM36 が必要なため、現在は止めています。",
              "mammalian은 POPC, bacterial은 POPE:POPG 3:1입니다. 그람 양성균 조성은 카디오리핀과 리실-PG 매개변수에 CHARMM36이 필요해 현재는 막습니다."),
             "lipids" in (spec or {}) and lip != "mammalian"),
            (("膜溫度", "Membrane temperature", "膜の温度", "막 온도"), f"{temp:g} K", "310 K",
             ("生理溫度，且比 POPE 的相轉變溫度（約 298 K）高 12 K。主要脂質在 Tm + 5 K 以下會擋下。",
              "Physiological, and 12 K above the transition of POPE (about 298 K). A majority lipid below Tm + 5 K is blocked.",
              "生理的な温度で、POPE の相転移温度（約 298 K）より 12 K 高い値です。主成分の脂質が Tm + 5 K 未満なら止めます。",
              "생리적 온도이며 POPE의 상전이 온도(약 298 K)보다 12 K 높습니다. 주성분 지질이 Tm + 5 K 미만이면 막습니다."), abs(temp - 310.0) > 0.01),
            (("側向邊界（nm）", "Lateral padding (nm)", "側方の余白（nm）", "측면 여백 (nm)"), s.get("lateral_padding_nm"), BM.DEFAULTS["lateral_padding_nm"],
             ("蛋白到盒邊的側向距離。太小時蛋白會和自己的週期影像作用。", "Lateral distance from the protein to the box edge. Too small and the protein "
              "interacts with its own periodic image.", "タンパク質からボックス端までの横方向の距離です。小さすぎるとタンパク質が自分の周期像と相互作用します。",
              "단백질에서 상자 가장자리까지의 측면 거리입니다. 너무 작으면 단백질이 자신의 주기 이미지와 상호작용합니다."),
             s.get("lateral_padding_nm") != BM.DEFAULTS["lateral_padding_nm"]),
            (("水層厚度（nm）", "Water layer (nm)", "水層の厚さ（nm）", "물층 두께 (nm)"), s.get("water_nm"), BM.DEFAULTS["water_nm"],
             ("膜兩側的水層，讓頭基與溶質不會碰到上下的週期影像。", "Water on each side, so head groups and solute do not reach the periodic image above or below.",
              "膜の両側の水層で、頭部基と溶質が上下の周期像に届かないようにします。", "막 양쪽의 물층으로 머리 부분과 용질이 위아래 주기 이미지에 닿지 않게 합니다."),
             s.get("water_nm") != BM.DEFAULTS["water_nm"])]
    if s.get("type") == "surface":
        rows.append((("溶質到磷平面的距離（nm）", "Solute distance above the phosphate plane (nm)", "溶質とリン原子面の距離（nm）", "용질과 인 원자 평면 사이 거리 (nm)"),
                     s.get("surface_distance_nm"), BM.DEFAULTS["surface_distance_nm"],
                     ("起始時最低的重原子在上葉磷平面上方的距離。太近會一開始就重疊，太遠吸附要很久。",
                      "Height of the lowest heavy atom above the upper phosphate plane at the start. Too close overlaps at the start; too far takes long to adsorb.",
                      "開始時に最も低い重原子が上側のリン原子面からどれだけ上にあるかです。近すぎると最初から重なり、遠すぎると吸着に時間がかかります。",
                      "시작할 때 가장 낮은 중원자가 위층 인 원자 평면보다 얼마나 위에 있는지입니다. 너무 가까우면 처음부터 겹치고 너무 멀면 흡착에 오래 걸립니다."),
                     s.get("surface_distance_nm") != BM.DEFAULTS["surface_distance_nm"]))
    rows.append((("壓力耦合", "Pressure coupling", "圧力の制御", "압력 결합"), "MonteCarloMembraneBarostat", "MonteCarloMembraneBarostat",
                 ("膜面 x、y 一起縮放，z 獨立，表面張力 0。等向壓力耦合會把膜壓扁或拉開。", "x and y scale together, z independently, zero surface "
                  "tension. Isotropic coupling would squash or stretch the membrane.", "膜面の x と y は一緒に、z は独立に伸縮し、表面張力は 0 です。等方的な圧力制御では膜がつぶれたり引き伸ばされたりします。",
                  "막 평면의 x와 y는 함께, z는 따로 늘고 줄며 표면 장력은 0입니다. 등방 압력 결합은 막을 짓누르거나 늘립니다."), False))
    params = _params(doc, rows, ("膜系統參數", "Membrane parameters", "膜の系のパラメータ", "막 시스템 매개변수"))
    start = len(doc.collected)
    out, extra = "", []
    if data:
        out += _membrane_table(doc, data)
    for key, d in data.items():
        out += _membrane_figures(doc, key, d)
        extra += I.membrane(key, d)
    findings = doc.collected[start:] + extra
    doc.collected += extra
    return W._section(doc, doc.next(), "membrane", params, out, findings)


# ============================================================================================ long run
def run_dir_size_gb(path: Path | None) -> float | None:
    if not path or not Path(path).is_dir():
        return None
    return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file()) / 1e9


def long_run_actual(run_dir: Path | None) -> dict:
    """Completed production (ns) from the stage records and the size of the run folder."""
    out: dict = {}
    if not run_dir:
        return out
    sd = Path(run_dir) / "stages" / "production"
    comp = load_json(sd / "production_complete.json", {})
    res = comp.get("result") or {}
    if res.get("steps") and comp.get("timestep_fs"):
        out["production_ns"] = round(float(res["steps"]) * float(comp["timestep_fs"]) / 1e6, 3)
    else:
        prog = load_json(sd / "production_progress.json", {})
        ts = prog.get("timestep_fs") or comp.get("timestep_fs")
        if prog.get("completed_local_steps") is not None and ts:
            out["production_ns"] = round(float(prog["completed_local_steps"]) * float(ts) / 1e6, 3)
    g = run_dir_size_gb(run_dir)
    if g is not None:
        out["disk_gb"] = round(g, 3)
    return out


def _convergence_data(wf, key: str) -> dict:
    sums = (wf.state()["steps"].get("analysis") or {}).get("summaries") or {}
    s = sums.get(key) or {}
    m = load_json(s.get("metrics_file"), {}) if s.get("metrics_file") else {}
    sm = load_json(m.get("stream_metrics_file") or s.get("stream_metrics_file"), {}) if (m.get("stream_metrics_file") or s.get("stream_metrics_file")) else {}
    src = sm if sm.get("rmsd_backbone_A") else m
    ext = load_json(s.get("extended_file"), {}) if s.get("extended_file") else {}
    return {"time_ns": src.get("time_ns") or m.get("time_ns") or [], "rmsd": src.get("rmsd_backbone_A") or [],
            "residues": src.get("rmsf_residues") or m.get("rmsf_residues") or [],
            "rmsf_a": src.get("rmsf_first_half_A") or m.get("rmsf_first_half_A") or [],
            "rmsf_b": src.get("rmsf_second_half_A") or m.get("rmsf_second_half_A") or [],
            "labels": (ext.get("clusters") or {}).get("labels") or [], "cl_time": ext.get("time_ns") or []}


def longrun_section(doc, wf) -> str:
    W = _W()
    plans = {k: v for k, v in (wf.state().get("long_run") or {}).items() if isinstance(v, dict) and v.get("production_ns")}
    if not plans:
        return ""
    from ..engine import longrun as LR
    L = doc.lang
    doc.section = tx(SUB_SECTIONS["longrun"]["title"], L)
    lr = (wf.cfg.get("md") or {}).get("long_run") or {}
    p0 = next(iter(plans.values()))
    rows = [(("正式模擬長度（ns）", "Production length (ns)", "本計算の長さ（ns）", "본 시뮬레이션 길이 (ns)"), f"{p0['production_ns']:g}", f"≤ {LR.MAX_PRODUCTION_NS:g}",
             (f"超過 {LR.PLAN_ABOVE_NS:g} ns 才規劃。超過 {LR.CONFIRM_ABOVE_NS:g} ns 要你確認天數與硬碟。超過 {LR.MAX_PRODUCTION_NS:g} ns 建議改用粗粒化。",
              f"Planned above {LR.PLAN_ABOVE_NS:g} ns. Above {LR.CONFIRM_ABOVE_NS:g} ns you confirm the days and disk. Above "
              f"{LR.MAX_PRODUCTION_NS:g} ns coarse-graining is recommended.",
              f"{LR.PLAN_ABOVE_NS:g} ns を超えると計画を立て、{LR.CONFIRM_ABOVE_NS:g} ns を超えると日数とディスクの確認が必要です。{LR.MAX_PRODUCTION_NS:g} ns を超える場合は粗視化を勧めます。",
              f"{LR.PLAN_ABOVE_NS:g} ns를 넘으면 계획을 세우고, {LR.CONFIRM_ABOVE_NS:g} ns를 넘으면 일수와 디스크를 확인해야 합니다. {LR.MAX_PRODUCTION_NS:g} ns를 넘으면 조립화를 권합니다."), False),
            (("軌跡存檔間隔（ps）", "Trajectory interval (ps)", "軌跡の保存間隔（ps）", "궤적 저장 간격 (ps)"), f"{p0.get('trajectory_interval_ps', 0):g}",
             f"≤ {LR.MAX_FRAME_PS:g}", ("從 20 ps 起取第一個讓軌跡不超過目標大小的間隔。", "The first interval from 20 ps upward that keeps the trajectory "
                                       "within the target size.", "20 ps から順に、軌跡が目標の大きさに収まる最初の間隔を選びます。",
                                       "20 ps부터 차례로 궤적이 목표 크기 안에 드는 첫 간격을 고릅니다."), False),
            (("軌跡目標大小（GB）", "Trajectory target (GB)", "軌跡の目標サイズ（GB）", "궤적 목표 크기 (GB)"), f"{float(lr.get('target_gb') or LR.DEFAULT_TARGET_GB):g}",
             f"{LR.DEFAULT_TARGET_GB:g}", ("學生筆電的硬碟有限。20 GB 讓 1 µs 的蛋白系統仍保有足夠的幀。", "Student laptops have limited disks. 20 GB still keeps enough "
                                          "frames for a 1 µs protein system.", "学生のノートパソコンはディスクが限られています。20 GB なら 1 µs のタンパク質系でも十分なフレームが残ります。",
                                          "학생 노트북은 디스크가 제한적입니다. 20 GB면 1 µs 단백질 시스템에서도 충분한 프레임이 남습니다."),
             lr.get("target_gb") not in (None, LR.DEFAULT_TARGET_GB)),
            (("只存溶質", "Save solute only", "溶質のみ保存", "용질만 저장"), _t("yes" if p0.get("solute_only") else "no", L),
             tx(("自動", "automatic", "自動", "자동"), L), ("全系統要拉到 100 ps 以上一幀時，自動改成只存溶質，避免動態分析太稀疏。",
                                                         "When saving the whole system would need more than 100 ps per frame, only the solute is saved so dynamics are not too sparse.",
                                                         "系全体の保存に 1 フレーム 100 ps 以上が必要になるときは、動きの解析が粗くならないよう溶質だけを保存します。",
                                                         "전체 계를 저장하려면 프레임당 100 ps 이상이 필요할 때는 동역학 분석이 너무 성기지 않도록 용질만 저장합니다."),
             lr.get("solute_only") is not None),
            (("分段長度（ps）", "Chunk length (ps)", "区間の長さ（ps）", "구간 길이 (ps)"), f"{p0.get('checkpoint_interval_ps', 0):g}", "max(200, L / 500)",
             (f"當機最多損失一段。每段計算時間不超過 {LR.MAX_CHUNK_WALL_HOURS:g} 小時。", f"A crash loses at most one chunk. Each chunk takes at most "
              f"{LR.MAX_CHUNK_WALL_HOURS:g} hour of computing.", f"異常終了しても失うのは 1 区間までで、各区間の計算時間は {LR.MAX_CHUNK_WALL_HOURS:g} 時間以内です。",
              f"비정상 종료 시 잃는 것은 한 구간까지이며 구간마다 계산 시간은 {LR.MAX_CHUNK_WALL_HOURS:g}시간 이내입니다."), False),
            (("保留的分段狀態檔", "Chunk states kept", "残す区間の状態ファイル", "남기는 구간 상태 파일"), str(p0.get("keep_chunk_states", 0)), str(LR.KEEP_CHUNK_STATES),
             ("只保留最新幾段的 State XML 與 checkpoint。軌跡與紀錄檔全部保留。", "Only the newest chunk State XML and checkpoints are kept. Trajectories and logs are all kept.",
              "最新の数区間の State XML と checkpoint だけを残し、軌跡と記録ファイルはすべて残します。", "최신 몇 구간의 State XML과 checkpoint만 남기고 궤적과 기록 파일은 모두 남깁니다."), False)]
    params = _params(doc, rows, ("長時間模擬的規劃", "Long-run plan", "長時間シミュレーションの計画", "장시간 시뮬레이션 계획"))
    start = len(doc.collected)
    out, extra, trs = "", [], []
    for key, plan in plans.items():
        actual = {**long_run_actual(_run_dir(wf, key)), **(plan.get("actual") or {})}
        trs.append([W._esc(key), f"{plan['production_ns']:g}", W._fmt(actual.get("production_ns"), 1), W._fmt(plan.get("days"), 1), W._fmt(actual.get("days"), 1),
                    W._fmt((plan.get("total_gb") or 0) / max(1, int(plan.get("replicas") or 1)), 1), W._fmt(actual.get("disk_gb"), 1),
                    f"{plan.get('n_frames', 0):,}", _t("yes" if plan.get("solute_only") else "no", L)])
        out += doc.figure_block(FG.longrun_plot(plan, actual, doc.figdir / f"longrun_{key}.png"), "longrun_plan", FT.classify_longrun(key, plan, actual), key)
        cv = _convergence_data(wf, key)
        if cv["rmsf_a"] and cv["rmsf_b"]:
            out += doc.figure_block(FG.rmsf_halves(cv["residues"], cv["rmsf_a"], cv["rmsf_b"], doc.figdir / f"conv_rmsf_{key}.png"), "convergence_rmsf",
                                    FT.classify_rmsf_halves(key, cv["rmsf_a"], cv["rmsf_b"]), key)
        if len(cv["rmsd"]) >= 20:
            out += doc.figure_block(FG.rmsd_halves(cv["rmsd"], doc.figdir / f"conv_rmsd_{key}.png"), "convergence_rmsd", FT.classify_rmsd_halves(key, cv["rmsd"]), key)
        if len(cv["labels"]) >= 20:
            P, ids = FT.cluster_windows(cv["labels"])
            tt = np.asarray(cv["cl_time"] or np.arange(len(cv["labels"])), float)
            edges = np.linspace(tt[0], tt[-1], len(P) + 1) if len(tt) else np.arange(len(P) + 1)
            out += doc.figure_block(FG.cluster_timeline_plot(P, ids, edges, doc.figdir / f"conv_clusters_{key}.png"), "cluster_timeline",
                                    FT.classify_cluster_timeline(key, cv["labels"]), key)
        extra += I.long_run(key, plan)
    tab = doc.table([_t("system", L), tx(("規劃（ns）", "Planned (ns)", "計画（ns）", "계획 (ns)"), L), tx(("完成（ns）", "Completed (ns)", "完了（ns）", "완료 (ns)"), L),
                     tx(("估計天數", "Estimated days", "見積もり日数", "예상 일수"), L), tx(("實際天數", "Actual days", "実際の日数", "실제 일수"), L),
                     tx(("規劃硬碟（GB，每份）", "Planned disk (GB per replica)", "計画ディスク（GB、1 回分）", "계획 디스크 (GB, 1회분)"), L),
                     tx(("實際資料夾（GB）", "Actual folder (GB)", "実際のフォルダ（GB）", "실제 폴더 (GB)"), L),
                     tx(("幀數", "Frames", "フレーム数", "프레임 수"), L), tx(("只存溶質", "Solute only", "溶質のみ", "용질만"), L)],
                    trs, ("長時間模擬：規劃與實際", "Long run: plan and actual", "長時間シミュレーション：計画と実績", "장시간 시뮬레이션: 계획과 실제"), {1, 2, 3, 4, 5, 6, 7})
    findings = doc.collected[start:] + extra
    doc.collected += extra
    return W._section(doc, doc.next(), "longrun", params, tab + out, findings)


# ============================================================================================ coarse-grained
def _cg_data(rec: dict) -> dict:
    if isinstance(rec.get("membrane"), dict):
        return rec["membrane"]
    return load_json(rec["membrane_file"], {}) if rec.get("membrane_file") else {}


def cg_section(doc, wf) -> str:
    W = _W()
    cgs = {k: v for k, v in (wf.state().get("coarse_grained") or {}).items() if isinstance(v, dict)}
    if not cgs:
        return ""
    from ..build import martini as MA
    L = doc.lang
    doc.section = tx(SUB_SECTIONS["cg"]["title"], L)
    rec0 = next(iter(cgs.values()))
    st = {}
    for s_ in (rec0.get("plan") or {}).get("steps") or []:
        st.update(s_.get("settings") or {})
    st.update(rec0.get("settings") or {})
    why_ff = ("martini_openmm 教學的設定（Langevin、ε_r 15、截斷 1.1 nm），和 Martini 3 的參數化一致。",
              "The martini_openmm tutorial settings (Langevin, ε_r 15, 1.1 nm cut-off), consistent with the Martini 3 parametrisation.",
              "martini_openmm のチュートリアルの設定（Langevin、ε_r 15、カットオフ 1.1 nm）で、Martini 3 のパラメータ化と一致しています。",
              "martini_openmm 튜토리얼 설정(Langevin, ε_r 15, 절단 1.1 nm)으로 Martini 3 매개변수화와 일치합니다.")
    rows = [(("時間步（fs）", "Time step (fs)", "時間刻み（fs）", "시간 간격 (fs)"), f"{st.get('timestep_fs', MA.CG_TIMESTEP_FS):g}", f"{MA.CG_TIMESTEP_FS:g}", why_ff,
             st.get("timestep_fs", MA.CG_TIMESTEP_FS) != MA.CG_TIMESTEP_FS),
            (("相對介電常數 ε_r", "Relative permittivity ε_r", "比誘電率 ε_r", "상대 유전율 ε_r"), f"{st.get('epsilon_r', MA.CG_EPSILON_R):g}", f"{MA.CG_EPSILON_R:g}", why_ff,
             st.get("epsilon_r", MA.CG_EPSILON_R) != MA.CG_EPSILON_R),
            (("非鍵截斷（nm）", "Non-bonded cut-off (nm)", "非結合カットオフ（nm）", "비결합 절단 거리 (nm)"), f"{st.get('cutoff_nm', MA.CG_CUTOFF_NM):g}", f"{MA.CG_CUTOFF_NM:g}", why_ff,
             st.get("cutoff_nm", MA.CG_CUTOFF_NM) != MA.CG_CUTOFF_NM),
            (("摩擦係數（ps⁻¹）", "Friction (ps⁻¹)", "摩擦係数（ps⁻¹）", "마찰 계수 (ps⁻¹)"), f"{st.get('friction_per_ps', MA.CG_FRICTION_PER_PS):g}", f"{MA.CG_FRICTION_PER_PS:g}", why_ff,
             st.get("friction_per_ps", MA.CG_FRICTION_PER_PS) != MA.CG_FRICTION_PER_PS),
            (("彈性網路（力常數、下限、上限）", "Elastic network (force constant, lower, upper)", "弾性ネットワーク（力の定数、下限、上限）", "탄성 네트워크 (힘 상수, 하한, 상한)"),
             " / ".join(MA.ELASTIC.values()), " / ".join(MA.ELASTIC.values()),
             ("Martini 3 教學常用值，固定蛋白的二級與三級結構。原始出處待審查。", "Common Martini 3 tutorial values that hold the protein's secondary and tertiary "
              "structure. The original source is still to be reviewed.", "Martini 3 のチュートリアルでよく使う値で、タンパク質の二次・三次構造を固定します。出典は確認待ちです。",
              "Martini 3 튜토리얼에서 흔히 쓰는 값으로 단백질의 이차·삼차 구조를 고정합니다. 원래 출처는 검토 중입니다."), False)]
    params = _params(doc, rows, ("粗粒化參數", "Coarse-grained parameters", "粗視化のパラメータ", "조립화 매개변수"))
    start = len(doc.collected)
    out, extra, trs = "", [], []
    for name, rec in cgs.items():
        plan = rec.get("plan") or {}
        for s_ in plan.get("steps") or []:
            trs.append([W._esc(name), W._esc(s_.get("name")), W._esc(s_.get("kind")), W._esc(", ".join(s_.get("outputs") or []))])
        d = _cg_data(rec)
        if d:
            out += doc.figure_block(FG.cg_membrane_plot(d, doc.figdir / f"cg_membrane_{name}.png"), "cg_membrane", FT.classify_cg_membrane(name, d), name + " (CG)")
            out += _membrane_figures(doc, name, d, cg=True)
        extra += I.coarse_grained(name, rec)
        extra += I.coarse_grained_results(name, d)
    if trs:
        out = doc.table([tx(("粗粒化系統", "CG system", "粗視化の系", "조립화 시스템"), L), tx(("步驟", "Step", "段階", "단계"), L),
                         tx(("類型", "Kind", "種類", "유형"), L), tx(("產出", "Outputs", "出力", "출력"), L)], trs,
                        ("粗粒化的建模步驟", "Coarse-grained build steps", "粗視化の構築手順", "조립화 구축 단계")) + out
    findings = doc.collected[start:] + extra
    doc.collected += extra
    return W._section(doc, doc.next(), "cg", params, out, findings)


# ============================================================================================ methods and limitations
def methods_sentences(wf, lang: str) -> str:
    """Methods-paragraph sentences for the subsystems present (ja: である調, ko: -했다)."""
    lg = norm(lang)
    st = wf.state()
    out = []
    folds = {k: v for k, v in (st.get("fold") or {}).items() if isinstance(v, dict) and v.get("engine")}
    for name, r in folds.items():
        eng, m = r.get("engine"), r.get("mean_plddt")
        ms = f"{m:.1f}" if m is not None else "—"
        pl = r.get("placement") or {}
        cx = (r.get("request") or {}).get("mode") == "complex"
        if lg == "zh":
            s = f"胜肽 {name} 的三維結構以 {eng} {'與受體一起預測為複合物' if cx else '由序列預測'}（胜肽平均 pLDDT {ms}）。"
            if cx and pl.get("rmsd_ca") is not None:
                s += f"預測的受體以序列比對配對的 {pl.get('n_matched')} 個 Cα 經 Kabsch 疊合到實際受體（Cα RMSD {pl['rmsd_ca']:.2f} Å），只取胜肽座標，不經對接直接作為 MD 的起始姿勢。"
            elif not cx:
                s += "對接時固定預測結構的主鏈二面角。"
        elif lg == "ja":
            s = f"ペプチド {name} の立体構造は {eng} により{'受容体との複合体として予測した' if cx else '配列から予測した'}（ペプチドの平均 pLDDT {ms}）。"
            if cx and pl.get("rmsd_ca") is not None:
                s += f"予測した受容体は配列アラインメントで対応づけた {pl.get('n_matched')} 個の Cα を用いて Kabsch 法で実際の受容体に重ね合わせ（Cα RMSD {pl['rmsd_ca']:.2f} Å）、ペプチドの座標のみをドッキングを経ずに MD の初期ポーズとした。"
            elif not cx:
                s += "ドッキングでは予測構造の主鎖二面角を固定した。"
        elif lg == "ko":
            s = f"펩타이드 {name}의 3차원 구조는 {eng}로 {'수용체와 함께 복합체로 예측했다' if cx else '서열로부터 예측했다'}(펩타이드 평균 pLDDT {ms}). "
            if cx and pl.get("rmsd_ca") is not None:
                s += f"예측한 수용체는 서열 정렬로 짝지은 Cα {pl.get('n_matched')}개를 이용해 Kabsch 방법으로 실제 수용체에 겹쳤고(Cα RMSD {pl['rmsd_ca']:.2f} Å), 펩타이드 좌표만 도킹 없이 MD의 시작 포즈로 사용했다. "
            elif not cx:
                s += "도킹할 때 예측 구조의 주사슬 이면각을 고정했다. "
        else:
            s = f"The three-dimensional structure of peptide {name} was predicted with {eng} {'together with the receptor as a complex' if cx else 'from its sequence'} (mean peptide pLDDT {ms}). "
            if cx and pl.get("rmsd_ca") is not None:
                s += (f"The predicted receptor was superposed on the actual receptor by Kabsch fitting of {pl.get('n_matched')} sequence-matched Cα "
                      f"(Cα RMSD {pl['rmsd_ca']:.2f} Å), and only the peptide coordinates were used as the MD starting pose, without docking. ")
            elif not cx:
                s += "Its backbone dihedrals were held fixed during docking. "
        out.append(s)
    spec = (wf.cfg.get("md") or {}).get("membrane")
    if spec:
        from ..build import membrane as BM
        s_ = {**BM.DEFAULTS, **spec}
        lip = s_.get("lipids")
        comp = BM.PRESETS[lip]["lipids"] if isinstance(lip, str) and lip in BM.PRESETS else (lip if isinstance(lip, dict) else {})
        lt = (f"{lip} " if isinstance(lip, str) else "") + "(" + ", ".join(f"{k} {v:g}" for k, v in comp.items()) + ")" if comp else str(lip)
        T = BM.membrane_temperature(spec)
        if lg == "zh":
            out.append(f"膜系統（{s_['type']}，脂質 {lt}）以 OpenMM 建膜，膜兩側各留 {s_['water_nm']} nm 水層。模擬溫度 {T:g} K，NPT 階段使用 MonteCarloMembraneBarostat（x、y 等向，z 獨立，表面張力 0），"
                       "脂質頭基的 z 約束在平衡階段逐步釋放。每個脂質的面積、P–P 厚度、密度剖面、−S_CD、插入深度、與頭基的接觸（0.4 nm）及胜肽傾角以 MD20 的 numpy 程式計算。")
        elif lg == "ja":
            out.append(f"膜の系（{s_['type']}、脂質 {lt}）は OpenMM で構築し、膜の両側に {s_['water_nm']} nm の水層を置いた。温度は {T:g} K とし、NPT 段階では MonteCarloMembraneBarostat（x と y は等方的、z は独立、表面張力 0）を用い、"
                       "脂質頭部基の z 方向の拘束は平衡化の間に段階的に外した。脂質あたりの面積、P–P 厚さ、密度分布、−S_CD、挿入の深さ、頭部基との接触（0.4 nm）、ペプチドの傾きは MD20 の numpy プログラムで計算した。")
        elif lg == "ko":
            out.append(f"막 시스템({s_['type']}, 지질 {lt})은 OpenMM으로 구축했고 막 양쪽에 {s_['water_nm']} nm 물층을 두었다. 온도는 {T:g} K였으며 NPT 단계에서는 MonteCarloMembraneBarostat(x와 y는 등방, z는 독립, 표면 장력 0)를 사용했고 "
                       "지질 머리 부분의 z 구속은 평형화 동안 단계적으로 풀었다. 지질당 면적, P–P 두께, 밀도 분포, −S_CD, 삽입 깊이, 머리 부분과의 접촉(0.4 nm), 펩타이드 기울기는 MD20의 numpy 프로그램으로 계산했다. ")
        else:
            out.append(f"The membrane system ({s_['type']}, lipids {lt}) was built with OpenMM with {s_['water_nm']} nm of water on each side. It was simulated at {T:g} K "
                       "with a MonteCarloMembraneBarostat in the NPT stages (x and y coupled isotropically, z independently, zero surface tension), "
                       "and the z restraints on the lipid head groups were released during equilibration. Area per lipid, P–P thickness, density profiles, −S_CD, "
                       "insertion depth, head-group contacts (0.4 nm) and peptide tilt were computed with MD20's numpy routines. ")
    plans = {k: v for k, v in (st.get("long_run") or {}).items() if isinstance(v, dict) and v.get("production_ns")}
    for key, p in plans.items():
        iv, so = p.get("trajectory_interval_ps", 0), p.get("solute_only")
        if lg == "zh":
            out.append(f"{key} 的正式模擬長 {p['production_ns']:g} ns，分成 {p.get('n_chunks')} 段執行，每 {iv:g} ps 存一幀{'（只存溶質）' if so else ''}。"
                       "RMSD、RMSF 與接觸頻率以分段串流讀取全部幀計算，收斂以前後兩半的 RMSF 與 RMSD 分佈比較。")
        elif lg == "ja":
            out.append(f"{key} の本計算は {p['production_ns']:g} ns で、{p.get('n_chunks')} 区間に分けて実行し、{iv:g} ps ごとにフレームを保存した{'（溶質のみ）' if so else ''}。"
                       "RMSD、RMSF、接触頻度は全フレームを区間ごとに読み込んで計算し、収束は前半と後半の RMSF と RMSD 分布の比較で確認した。")
        elif lg == "ko":
            out.append(f"{key}의 본 시뮬레이션은 {p['production_ns']:g} ns였으며 {p.get('n_chunks')}구간으로 나누어 실행하고 {iv:g} ps마다 프레임을 저장했다{'(용질만)' if so else ''}. "
                       "RMSD, RMSF, 접촉 빈도는 모든 프레임을 구간별로 읽어 계산했고 수렴은 전반부와 후반부의 RMSF와 RMSD 분포를 비교해 확인했다. ")
        else:
            out.append(f"Production for {key} was {p['production_ns']:g} ns, run in {p.get('n_chunks')} chunks with a frame saved every {iv:g} ps"
                       f"{' (solute only)' if so else ''}. RMSD, RMSF and contact frequencies were computed from all frames read chunk by chunk, "
                       "and convergence was checked by comparing the RMSF and RMSD distributions of the two halves. ")
    if st.get("coarse_grained"):
        from ..build import martini as MA
        e = "/".join(MA.ELASTIC.values())
        if lg == "zh":
            out.append(f"粗粒化模擬使用 Martini 3。蛋白以 martinize2 轉換（彈性網路 {e}），膜以 insane 建立，並以 martini_openmm 在 OpenMM 執行（時間步 {MA.CG_TIMESTEP_FS:g} fs，ε_r {MA.CG_EPSILON_R:g}，截斷 {MA.CG_CUTOFF_NM:g} nm，Langevin 摩擦 {MA.CG_FRICTION_PER_PS:g} ps⁻¹）。")
        elif lg == "ja":
            out.append(f"粗視化シミュレーションには Martini 3 を用いた。タンパク質は martinize2 で変換し（弾性ネットワーク {e}）、膜は insane で構築し、martini_openmm により OpenMM で実行した（時間刻み {MA.CG_TIMESTEP_FS:g} fs、ε_r {MA.CG_EPSILON_R:g}、カットオフ {MA.CG_CUTOFF_NM:g} nm、Langevin 摩擦 {MA.CG_FRICTION_PER_PS:g} ps⁻¹）。")
        elif lg == "ko":
            out.append(f"조립화 시뮬레이션에는 Martini 3를 사용했다. 단백질은 martinize2로 변환했고(탄성 네트워크 {e}) 막은 insane으로 구축했으며 martini_openmm으로 OpenMM에서 실행했다(시간 간격 {MA.CG_TIMESTEP_FS:g} fs, ε_r {MA.CG_EPSILON_R:g}, 절단 {MA.CG_CUTOFF_NM:g} nm, Langevin 마찰 {MA.CG_FRICTION_PER_PS:g} ps⁻¹). ")
        else:
            out.append(f"Coarse-grained simulations used Martini 3. The protein was converted with martinize2 (elastic network {e}), the membrane was built with insane, "
                       f"and the system was run in OpenMM with martini_openmm (time step {MA.CG_TIMESTEP_FS:g} fs, ε_r {MA.CG_EPSILON_R:g}, cut-off {MA.CG_CUTOFF_NM:g} nm, "
                       f"Langevin friction {MA.CG_FRICTION_PER_PS:g} ps⁻¹). ")
    return "".join(out)


def limitations(wf, lang: str) -> list[str]:
    st = wf.state()
    L = lang
    items = []
    folds = {k: v for k, v in (st.get("fold") or {}).items() if isinstance(v, dict) and v.get("engine")}
    if folds:
        names = ", ".join(folds)
        items.append(tx((f"{names} 的結構是預測的，不是實驗結構。pLDDT 與 ipTM 是模型的自信程度，高分也不保證正確。結論要以 MD 的穩定性與實驗資料支持。",
                         f"The structures of {names} are predictions, not experimental structures. pLDDT and ipTM are the model's "
                         "confidence and a high value does not guarantee correctness. Conclusions need MD stability and experimental data behind them.",
                         f"{names} の構造は予測であり、実験構造ではありません。pLDDT と ipTM はモデルの確信度で、高い値でも正しいとは限りません。結論には MD での安定性と実験データの裏づけが必要です。",
                         f"{names}의 구조는 예측이며 실험 구조가 아닙니다. pLDDT와 ipTM은 모델의 확신도이며 값이 높아도 맞다는 보장이 없습니다. 결론은 MD 안정성과 실험 자료로 뒷받침해야 합니다."), L))
        if any((v.get("request") or {}).get("mode") == "complex" for v in folds.values()):
            items.append(tx(("由預測複合物放置的胜肽沒有對接分數，不能和對接得到的配體以分數比較強弱。",
                             "Peptides placed from a predicted complex have no docking score and cannot be ranked against docked ligands by score.",
                             "予測複合体から置いたペプチドにはドッキングスコアがなく、ドッキングで得たリガンドとスコアで強さを比べることはできません。",
                             "예측 복합체에서 놓은 펩타이드는 도킹 점수가 없으므로 도킹으로 얻은 리간드와 점수로 세기를 비교할 수 없습니다."), L))
    spec = (wf.cfg.get("md") or {}).get("membrane")
    if spec:
        lip = (spec or {}).get("lipids", "mammalian")
        items.append(tx(("模擬的膜是簡化模型（單一或少數幾種磷脂、兩葉對稱），真實細胞膜含數百種脂質、蛋白與糖。膜的參考值依開發者記憶整理，尚待對照原始文獻。",
                         "The simulated membrane is a simplified model (one or a few phospholipids, symmetric leaflets). Real cell "
                         "membranes hold hundreds of lipids, proteins and sugars. The membrane reference values were compiled from "
                         "memory and still have to be checked against the original papers.",
                         "シミュレーションした膜は単純化したモデル（1 種または数種のリン脂質、対称な二葉）です。実際の細胞膜には数百種類の脂質、タンパク質、糖が含まれます。"
                         "膜の参照値は開発者の記憶に基づいて整理したもので、原著論文との照合が必要です。",
                         "시뮬레이션한 막은 단순화한 모델(한 종 또는 몇 종의 인지질, 대칭인 두 층)입니다. 실제 세포막에는 수백 종의 지질, 단백질, 당이 있습니다. "
                         "막 참고값은 개발자의 기억으로 정리한 것이므로 원 논문과 대조해야 합니다."), L))
        if lip in ("bacterial", "gram_positive") or isinstance(lip, dict):
            items.append(tx(("只模擬細胞膜：格蘭氏陽性菌的肽聚醣細胞壁與格蘭氏陰性菌的外膜（脂多醣）都沒有建模，胜肽要先穿過這些結構才能到達細胞膜。",
                             "Only the cytoplasmic membrane is modelled. The peptidoglycan cell wall of Gram-positive bacteria and the "
                             "outer membrane (lipopolysaccharide) of Gram-negative bacteria are not built, and a peptide has to pass "
                             "them before it reaches the cell membrane.",
                             "細胞膜だけをモデル化しています。グラム陽性菌のペプチドグリカン細胞壁とグラム陰性菌の外膜（リポ多糖）は作っておらず、ペプチドは細胞膜に届く前にこれらを通る必要があります。",
                             "세포막만 모델링했습니다. 그람 양성균의 펩티도글리칸 세포벽과 그람 음성균의 외막(지질다당류)은 만들지 않았으며, 펩타이드는 세포막에 닿기 전에 이 구조를 지나야 합니다."), L))
        if (spec or {}).get("type") == "surface":
            items.append(tx(("膜表面接觸的模擬只描述吸附，不證明胜肽能穿膜或破壞膜。穿膜需要沿膜法線的自由能剖面，MD20 尚未實作。膜系統的結合自由能目前不計算。",
                             "A surface simulation describes adsorption only. It does not show that the peptide crosses or disrupts the "
                             "membrane, which needs a free-energy profile along the normal that MD20 does not implement yet. Binding free energies are not computed for membrane systems.",
                             "膜表面接触のシミュレーションは吸着を表すだけで、ペプチドが膜を通過したり壊したりできることは示しません。それには膜法線方向の自由エネルギープロファイルが必要ですが、MD20 にはまだありません。膜の系では結合自由エネルギーを計算していません。",
                             "막 표면 접촉 시뮬레이션은 흡착만 나타내며 펩타이드가 막을 통과하거나 파괴할 수 있음을 보여 주지 않습니다. 그러려면 막 법선 방향의 자유 에너지 프로파일이 필요하지만 MD20에는 아직 없습니다. 막 시스템의 결합 자유 에너지는 계산하지 않습니다."), L))
    if any(isinstance(v, dict) and v.get("solute_only") for v in (st.get("long_run") or {}).values()):
        items.append(tx(("長時間模擬只存溶質的座標，水與離子的分析（水橋、水的分佈）無法從軌跡重做。",
                         "The long run saved only solute coordinates, so water and ion analyses (water bridges, water distribution) cannot be redone from the trajectory.",
                         "長時間シミュレーションでは溶質の座標だけを保存したため、水やイオンの解析（水架橋、水の分布）は軌跡からやり直せません。",
                         "장시간 시뮬레이션은 용질 좌표만 저장했으므로 물과 이온 분석(물 다리, 물 분포)을 궤적에서 다시 할 수 없습니다."), L))
    if st.get("coarse_grained"):
        items.append(tx(("粗粒化結果不是全原子：每顆珠子約 4 個重原子，沒有氫鍵，二級結構由彈性網路固定，動態比真實快，模擬時間不能直接當真實時間。原子層級的結論要轉回全原子確認。",
                         "Coarse-grained results are not atomistic. Each bead holds about 4 heavy atoms, there are no hydrogen bonds, "
                         "the secondary structure is fixed by an elastic network and dynamics run faster than real ones, so simulated "
                         "time is not real time. Atomic-level conclusions need back-mapping to all atoms.",
                         "粗視化の結果は全原子ではありません。ビーズ 1 個はおよそ 4 個の重原子で、水素結合はなく、二次構造は弾性ネットワークで固定され、動きは実際より速いため、シミュレーション時間をそのまま実時間とみなせません。原子レベルの結論には全原子への変換と確認が必要です。",
                         "조립화 결과는 전원자가 아닙니다. 비드 하나가 중원자 약 4개이고 수소 결합이 없으며 이차 구조는 탄성 네트워크로 고정되고 동역학이 실제보다 빠르므로 시뮬레이션 시간을 그대로 실제 시간으로 볼 수 없습니다. 원자 수준의 결론은 전원자로 되돌려 확인해야 합니다."), L))
    return items


def selection_rows(wf, lang: str) -> list[list[str]]:
    """Ligands in the pose selection that have no docking entry (placed from a predicted complex): name and score text."""
    W = _W()
    sel = ((wf.state()["steps"].get("pose_selection") or {}).get("selection") or {}).get("ligands") or {}
    return [[W._esc(n), W._esc(I.score_text(v.get("score"), lang))] for n, v in sel.items() if v.get("source") == "fold_complex" or v.get("score") is None]


__all__ = ["SUB_SECTIONS", "fold_section", "membrane_section", "longrun_section", "cg_section", "methods_sentences", "limitations",
           "fold_geometry", "long_run_actual", "selection_rows", "colon"]
