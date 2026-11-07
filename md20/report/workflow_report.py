"""Workflow report (D-52): project-report grade, bilingual (English default, Traditional Chinese).

Every section follows the same order the user asked for:
  1. what this step is   2. scientific meaning   3. parameters used (value, recommendation for this case, reason)
  4. figures and tables (numbered, with captions)   5. interpretation written from this run's numbers.
Front matter: key findings.  Back matter: methods paragraph ready to paste, limitations, parameter appendix, decision
log, configuration.  Nothing is typed by hand; every number comes from the workflow's own files.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .. import advisor
from ..advisor import tx
from ..util import load_json, now_iso
from . import interpret as I
from . import figures as FG
from . import docking_figs as DF
from .figure_text import FIG
from . import figure_text as FT
from .html import _img, _esc, build_run_report
from . import subsystem_report as SR
from ..i18n import HTML_LANG, LANGS, colon, norm, paren, pick, stop


def _restrained_tag(summary: dict, lang: str = "zh") -> str:
    """D-23: RMSD measured under a production restraint is not evidence of stability, so say so next to the number."""
    r = (summary or {}).get("restrained_production") or {}
    if not r:
        return ""
    g = _esc(", ".join(r))
    return "<br><small>" + pick((f"（受約束：{g}。RMSD 低不代表結構穩定）",
                                 f"(restrained: {g}. A low RMSD is not evidence of stability)",
                                 f"（拘束あり：{g}。RMSD が低くても構造が安定とは言えません）",
                                 f"(구속됨: {g}. RMSD가 낮아도 구조가 안정하다는 뜻은 아닙니다)"), lang) + "</small>"


def _fmt(x, nd: int = 2) -> str:
    return "—" if x is None else f"{float(x):.{nd}f}"


CSS = """
:root{--ink:#1f2933;--muted:#52606d;--line:#d9dee3;--soft:#f4f6f8;--accent:#2f6f9f;--good:#2f7d5b;--warn:#a86a12;--bad:#b8433f}
body{font-family:"Inter","Segoe UI","Noto Sans TC","Microsoft JhengHei",system-ui,sans-serif;color:var(--ink);max-width:1040px;
     margin:2.5rem auto;padding:0 1.5rem;line-height:1.6;font-size:15px}
h1{font-size:1.7rem;margin:0 0 .3rem;font-weight:650}h2{font-size:1.25rem;margin:2.4rem 0 .6rem;padding-bottom:.3rem;border-bottom:2px solid var(--ink)}
h3{font-size:1.02rem;margin:1.4rem 0 .4rem}h4{font-size:.8rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:1.1rem 0 .3rem}
.meta{color:var(--muted);font-size:.85rem}.lead{font-size:.95rem}
table{border-collapse:collapse;width:100%;font-size:.84rem;margin:.4rem 0 .2rem}th,td{border-bottom:1px solid var(--line);padding:.35rem .5rem;
      text-align:left;vertical-align:top}th{background:var(--soft);font-weight:600;border-bottom:1px solid #b9c1c9}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.caption{font-size:.8rem;color:var(--muted);margin:.2rem 0 1rem}.caption b{color:var(--ink)}
figure{margin:1rem 0}figure img{border:1px solid var(--line)}
.box{background:var(--soft);border-left:4px solid var(--accent);padding:.8rem 1rem;margin:1rem 0}
.findings li{margin:.25rem 0}.good::marker{color:var(--good)}.note::marker{color:var(--accent)}.caution::marker{color:var(--bad)}
.tag{display:inline-block;font-size:.72rem;padding:0 .4rem;border-radius:3px;border:1px solid var(--line);color:var(--muted);margin-left:.3rem}
.tag.changed{border-color:var(--warn);color:var(--warn)}.tag.caution{border-color:var(--bad);color:var(--bad)}
.methods{font-family:Georgia,"Noto Serif TC",serif;font-size:.95rem;background:#fff;border:1px solid var(--line);padding:1rem 1.2rem}
details{margin:.6rem 0}summary{cursor:pointer;color:var(--accent)}pre{font-size:.75rem;white-space:pre-wrap}
.muted{color:var(--muted)}.warn{color:var(--warn)}
.figblock{border:1px solid var(--line);border-radius:4px;padding:.8rem 1rem;margin:1.2rem 0;background:#fff}
.figblock img{border:none;max-width:720px;width:100%;display:block;margin:0 auto}.figtext p{margin:.35rem 0;font-size:.9rem}.figtext b{color:var(--ink)}
.figtext ul{margin:.2rem 0 .2rem 1.1rem;padding:0}.figtext li{margin:.15rem 0;font-size:.9rem}
@media print{body{max-width:none;margin:1cm}h2{page-break-after:avoid}figure,table{page-break-inside:avoid}details{display:none}}
"""

H = {  # fixed headings and labels
    "title": ("分子模擬專案報告", "Molecular Simulation Project Report", "分子シミュレーション プロジェクトレポート", "분자 시뮬레이션 프로젝트 보고서"),
    "project": ("專案", "Project", "プロジェクト", "프로젝트"), "workflow": ("流程", "Workflow", "ワークフロー", "워크플로"),
    "generated": ("產生時間", "Generated", "作成日時", "생성 시각"),
    "key_findings": ("重點摘要", "Key findings", "主な結果", "주요 결과"),
    "what": ("這一步是什麼", "What this step is", "このステップの内容", "이 단계의 내용"),
    "meaning": ("科學意義", "Scientific meaning", "科学的な意味", "과학적 의미"),
    "params": ("使用的參數", "Parameters used", "使用したパラメータ", "사용한 매개변수"),
    "results": ("結果", "Results", "結果", "결과"), "interpretation": ("結果解釋", "Interpretation", "結果の解釈", "결과 해석"),
    "parameter": ("參數", "Parameter", "パラメータ", "매개변수"), "value": ("採用值", "Value used", "使用値", "사용값"),
    "recommended": ("本案例建議值", "Recommended for this case", "このケースの推奨値", "이 사례의 권장값"),
    "reason": ("理由", "Reason", "理由", "이유"), "changed": ("使用者修改", "changed by user", "ユーザーが変更", "사용자 변경"),
    "figure": ("圖", "Figure", "図", "그림"), "table": ("表", "Table", "表", "표"),
    "methods": ("方法（可直接用於報告）", "Methods (ready to use in a report)", "方法（そのまま報告書に使えます）", "방법 (보고서에 바로 사용 가능)"),
    "limitations": ("限制與注意事項", "Limitations and caveats", "限界と注意点", "한계와 주의 사항"),
    "appendix_params": ("附錄 A　完整參數表", "Appendix A  Complete parameter table", "付録 A　全パラメータ表", "부록 A  전체 매개변수 표"),
    "appendix_log": ("附錄 B　決策紀錄", "Appendix B  Decision log", "付録 B　判断の記録", "부록 B  결정 기록"),
    "appendix_cfg": ("附錄 C　設定檔", "Appendix C  Configuration file", "付録 C　設定ファイル", "부록 C  설정 파일"),
    "zh_note": ("", "Some automatic explanations and the decision log were recorded in Traditional Chinese and are shown as recorded.",
                "自動説明の一部と判断の記録は繁体字中国語で記録されており、そのまま表示しています。",
                "일부 자동 설명과 결정 기록은 번체 중국어로 기록되어 있어 그대로 표시합니다."),
    "not_run": ("此步驟未執行。", "This step was not run.", "このステップは実行されていません。", "이 단계는 실행되지 않았습니다."),
    "how_to_read": ("如何判讀", "How to read", "読み方", "읽는 법"),
    "in_project": ("本專案的結果", "In this project", "このプロジェクトの結果", "이 프로젝트의 결과"),
    "synthesis_ok": ("數據支持以下結論。", "The data support the following.", "データから次のことが言えます。", "데이터로 다음을 말할 수 있습니다."),
    "synthesis_caution": ("以下結果要保守看待。", "Read the following results with caution.", "次の結果は慎重に解釈してください。",
                          "다음 결과는 신중하게 해석해야 합니다."),
}

SECTION = {
    "design": {
        "title": ("研究設計", "Study design", "研究デザイン", "연구 설계"),
        "what": ("定義標靶蛋白、配體與要回答的問題，並決定模擬哪些系統。",
                 "Defines the target protein, the ligands and the question, and which systems are simulated.",
                 "標的タンパク質、リガンド、答えたい問いを決め、どの系をシミュレーションするかを決めます。",
                 "표적 단백질, 리간드, 답하려는 질문을 정하고 어떤 시스템을 시뮬레이션할지 결정합니다."),
        "meaning": ("同時模擬蛋白單獨與蛋白加配體，才能把配體造成的變化和蛋白本身的熱擾動分開。沒有這個對照，RMSD 或柔性的變化無法歸因於配體。",
                    "Simulating the protein alone next to the complex separates the ligand's effect from the protein's own "
                    "thermal motion. Without that reference, a change in RMSD or flexibility cannot be attributed to the ligand.",
                    "タンパク質単独とリガンド複合体を両方シミュレーションすると、リガンドによる変化とタンパク質自身の熱ゆらぎを区別できます。"
                    "この対照がなければ、RMSD や柔軟性の変化をリガンドの効果とは言えません。",
                    "단백질 단독과 리간드 복합체를 함께 시뮬레이션해야 리간드에 의한 변화와 단백질 자체의 열 요동을 구분할 수 있습니다. "
                    "이 대조가 없으면 RMSD나 유연성의 변화를 리간드 때문이라고 할 수 없습니다."),
    },
    "structure": {
        "title": ("受體結構準備與可信度", "Receptor preparation and structure validity", "受容体構造の準備と信頼性", "수용체 구조 준비와 신뢰성"),
        "what": ("下載或讀入受體結構，移除結晶添加物與水，補齊缺失原子，依 pH 加氫，再檢查解析度、物種與口袋是否完整。",
                 "The receptor is fetched or read in. Crystallisation additives and water are removed, missing atoms are added "
                 "and hydrogens are placed for the chosen pH. Then resolution, species and pocket completeness are checked.",
                 "受容体構造を取得または読み込み、結晶化添加物と水を除き、欠けた原子を補い、pH に合わせて水素を付けます。"
                 "そのうえで分解能、生物種、ポケットが欠けていないかを確認します。",
                 "수용체 구조를 내려받거나 읽어 들이고 결정화 첨가물과 물을 제거한 뒤 빠진 원자를 채우고 pH에 맞춰 수소를 붙입니다. "
                 "그다음 분해능, 생물종, 포켓이 온전한지 확인합니다."),
        "meaning": ("後面所有結果都建立在這個結構上。PDB 編號錯了、口袋殘基缺失或質子化狀態不對，對接與模擬都會給出看起來合理、其實沒有意義的數字。",
                    "Every later result rests on this structure. A wrong PDB identifier, missing pocket residues or a wrong "
                    "protonation state give docking and simulation numbers that look reasonable but mean nothing.",
                    "以降の結果はすべてこの構造に基づきます。PDB ID の誤り、ポケット残基の欠落、プロトン化状態の誤りがあると、"
                    "ドッキングもシミュレーションももっともらしいだけで意味のない数値を出します。",
                    "이후의 모든 결과는 이 구조를 바탕으로 합니다. PDB ID가 틀리거나 포켓 잔기가 빠졌거나 양성자화 상태가 잘못되면 "
                    "도킹과 시뮬레이션 모두 그럴듯하지만 의미 없는 숫자를 냅니다."),
    },
    "screen": {
        "title": ("高通量前期篩選", "High-throughput pre-screening", "ハイスループット事前スクリーニング", "고처리량 사전 스크리닝"),
        "what": ("用較低的搜尋強度快速對接化合物庫裡的每個分子，依分數與配體效率排名，再由使用者選出要進入正式對接的化合物。",
                 "Every compound in the library is docked quickly at a lower exhaustiveness and ranked by score and ligand "
                 "efficiency. The user then picks the compounds that go on to full docking.",
                 "化合物ライブラリの各分子を低い探索の徹底度（exhaustiveness）で素早くドッキングし、スコアとリガンド効率で順位を付けます。"
                 "本ドッキングに進める化合物はユーザーが選びます。",
                 "화합물 라이브러리의 각 분자를 낮은 탐색 강도(exhaustiveness)로 빠르게 도킹하고 점수와 리간드 효율로 순위를 매깁니다. "
                 "본 도킹으로 넘길 화합물은 사용자가 고릅니다."),
        "meaning": ("篩選分數只用來剔除明顯不合適的化合物，它不等於結合自由能。分數差距小於 1 kcal mol⁻¹ 時，名次沒有統計意義。",
                    "Screening scores only remove clear misfits. They are not binding free energies, and a difference below "
                    "1 kcal mol⁻¹ has no statistical meaning.",
                    "スクリーニングのスコアは明らかに合わない化合物を除くためのもので、結合自由エネルギーではありません。"
                    "スコア差が 1 kcal mol⁻¹ 未満なら、順位に統計的な意味はありません。",
                    "스크리닝 점수는 명백히 맞지 않는 화합물을 걸러내는 용도이며 결합 자유 에너지가 아닙니다. "
                    "점수 차이가 1 kcal mol⁻¹ 미만이면 순위에 통계적 의미가 없습니다."),
    },
    "docking": {
        "title": ("分子對接與姿勢選擇", "Molecular docking and pose selection", "分子ドッキングとポーズの選択", "분자 도킹과 포즈 선택"),
        "what": ("在結合位的搜尋區內用 AutoDock Vina 產生配體姿勢，再依分數、叢集大小與接觸殘基選出要進入模擬的姿勢。",
                 "AutoDock Vina generates ligand poses inside the search box. The pose taken into simulation is chosen from "
                 "score, cluster size and contact residues.",
                 "結合部位の探索ボックス内で AutoDock Vina によりリガンドのポーズを生成し、スコア、クラスターの大きさ、接触残基からシミュレーションに使うポーズを選びます。",
                 "결합 부위의 탐색 상자 안에서 AutoDock Vina로 리간드 포즈를 만들고 점수, 클러스터 크기, 접촉 잔기를 보고 시뮬레이션에 쓸 포즈를 고릅니다."),
        "meaning": ("對接給出合理的起始結合模式。它的分數是經驗評分函數，誤差約 1 到 2 kcal mol⁻¹，也沒有考慮蛋白柔性與溶劑。結合穩不穩定要看分子動力學。",
                    "Docking gives a plausible starting binding mode. The score comes from an empirical function with an error "
                    "of about 1 to 2 kcal mol⁻¹ and leaves out protein flexibility and solvent. Molecular dynamics decides "
                    "whether the binding is stable.",
                    "ドッキングはもっともらしい初期の結合様式を与えます。スコアは経験的な関数によるもので、誤差は約 1〜2 kcal mol⁻¹ あり、"
                    "タンパク質の柔軟性と溶媒は考慮されていません。結合が安定かどうかは分子動力学で判断します。",
                    "도킹은 그럴듯한 초기 결합 모드를 줍니다. 점수는 경험적 함수에서 나오며 오차가 약 1~2 kcal mol⁻¹이고 단백질 유연성과 용매를 고려하지 않습니다. "
                    "결합이 안정한지는 분자동역학으로 판단합니다."),
    },
    "peptide": {
        "title": ("胜肽配體的科學限制", "Scientific limitations of the peptide ligand", "ペプチドリガンドの科学的な限界", "펩타이드 리간드의 과학적 한계"),
        "what": ("胜肽配體要檢查兩件事。標靶在細胞內時，胜肽能不能穿膜。選用的姿勢有沒有真的進入結合位。",
                 "A peptide ligand gets two checks. If the target is intracellular, can the peptide cross the cell membrane? "
                 "And does the chosen pose actually enter the binding site?",
                 "ペプチドリガンドでは 2 点を確認します。標的が細胞内にある場合にペプチドが膜を通過できるか、そして選んだポーズが本当に結合部位に入っているかです。",
                 "펩타이드 리간드는 두 가지를 확인합니다. 표적이 세포 안에 있을 때 펩타이드가 막을 통과할 수 있는지, 그리고 고른 포즈가 실제로 결합 부위에 들어가 있는지입니다."),
        "meaning": ("胜肽大又柔軟，對接幾乎總能找到貼在蛋白表面的姿勢。如果胜肽到不了標靶，或沒有進入活性位，結合計算在生物學上的解釋就站不住。"
                    "這兩項只提醒、不擋流程，因為研究目的可能本來就是表面結合或體外試驗。",
                    "Peptides are large and flexible, and docking nearly always finds a pose on the protein surface. If the "
                    "peptide cannot reach the target or does not enter the site, the binding calculation has no biological "
                    "reading. Both checks only warn and never stop the workflow, because surface binding or an in vitro "
                    "assay may be the actual aim.",
                    "ペプチドは大きく柔らかいため、ドッキングではほぼ必ずタンパク質表面に貼り付いたポーズが見つかります。"
                    "ペプチドが標的に届かない、または活性部位に入らない場合、結合計算の生物学的な解釈は成り立ちません。"
                    "研究の目的が表面での結合や in vitro 試験である場合もあるため、この 2 項目は注意を出すだけでワークフローは止めません。",
                    "펩타이드는 크고 유연해서 도킹하면 거의 항상 단백질 표면에 붙은 포즈를 찾습니다. 펩타이드가 표적에 닿지 못하거나 활성 부위에 들어가지 않으면 "
                    "결합 계산의 생물학적 해석이 성립하지 않습니다. 연구 목적이 표면 결합이나 in vitro 시험일 수도 있으므로 이 두 항목은 알림만 하고 워크플로를 멈추지 않습니다."),
    },
    "md": {
        "title": ("分子動力學", "Molecular dynamics", "分子動力学", "분자동역학"),
        "what": ("把蛋白與配體放進水盒並加鹽，依序做能量最小化、升溫與定壓平衡，再跑正式模擬。之後分析主鏈 RMSD、殘基柔性（RMSF）、配體在口袋內的位移與接觸頻率。",
                 "Protein and ligand are placed in a water box with salt, minimised, heated and equilibrated at constant "
                 "pressure, and then run in production. The analysis covers backbone RMSD, residue flexibility (RMSF), "
                 "ligand displacement in the pocket and contact frequencies.",
                 "タンパク質とリガンドを水ボックスに入れて塩を加え、エネルギー最小化、昇温、定圧平衡化を行ってから本計算を実行します。"
                 "その後、主鎖 RMSD、残基の柔軟性（RMSF）、ポケット内でのリガンドの変位、接触頻度を解析します。",
                 "단백질과 리간드를 물 상자에 넣고 염을 더한 뒤 에너지 최소화, 승온, 정압 평형화를 거쳐 본 시뮬레이션을 실행합니다. "
                 "이후 주사슬 RMSD, 잔기 유연성(RMSF), 포켓 안에서의 리간드 변위와 접촉 빈도를 분석합니다."),
        "meaning": ("模擬檢驗對接姿勢在有溫度、溶劑與蛋白柔性時站不站得住。配體離開口袋，代表對接分數不能當作結合的證據。"
                    "蛋白單獨與複合物的柔性差異，指出受配體影響的區域。",
                    "Simulation tests whether the docked pose holds once temperature, solvent and protein flexibility are "
                    "present. A ligand that leaves the pocket means the docking score is not evidence of binding. The "
                    "difference in flexibility between protein alone and complex points to the regions the ligand affects.",
                    "シミュレーションでは、温度、溶媒、タンパク質の柔軟性がある条件でドッキングポーズが保たれるかを確かめます。"
                    "リガンドがポケットから離れた場合、ドッキングスコアは結合の証拠になりません。"
                    "タンパク質単独と複合体の柔軟性の差から、リガンドの影響を受ける領域がわかります。",
                    "시뮬레이션은 온도, 용매, 단백질 유연성이 있는 조건에서 도킹 포즈가 유지되는지 확인합니다. "
                    "리간드가 포켓을 떠나면 도킹 점수는 결합의 증거가 될 수 없습니다. "
                    "단백질 단독과 복합체의 유연성 차이는 리간드의 영향을 받는 영역을 보여 줍니다."),
    },
    "binding": {
        "title": ("結合自由能（SMD 與傘狀採樣）", "Binding free energy (SMD and umbrella sampling)",
                  "結合自由エネルギー（SMD とアンブレラサンプリング）", "결합 자유 에너지 (SMD와 엄브렐라 샘플링)"),
        "what": ("用導向分子動力學（SMD）把配體沿解離路徑拉出口袋，取路徑上的構形作為傘狀採樣的窗口，以 MBAR 合併成自由能剖面（PMF），最後加上體積修正得到標準結合自由能。",
                 "Steered molecular dynamics (SMD) pulls the ligand out of the pocket along a dissociation path. "
                 "Configurations along the path start the umbrella-sampling windows, and MBAR combines them into a "
                 "free-energy profile (PMF). A volume correction then gives the standard binding free energy.",
                 "ステアード分子動力学（SMD）でリガンドを解離経路に沿ってポケットから引き離し、経路上の構造をアンブレラサンプリングのウィンドウの出発点にします。"
                 "MBAR でまとめて自由エネルギープロファイル（PMF）を求め、体積補正を加えて標準結合自由エネルギーを得ます。",
                 "조향 분자동역학(SMD)으로 리간드를 해리 경로를 따라 포켓 밖으로 당기고, 경로 위의 구조를 엄브렐라 샘플링 윈도우의 시작점으로 씁니다. "
                 "MBAR로 합쳐 자유 에너지 프로파일(PMF)을 구하고 부피 보정을 더해 표준 결합 자유 에너지를 얻습니다."),
        "meaning": ("PMF 的井深是把配體帶離口袋所需的自由能，比對接分數更接近實驗量。它取決於取樣夠不夠，也就是窗口有沒有重疊、前後半段是否一致。沒有收斂時只能做定性比較。",
                    "The depth of the PMF is the free energy needed to take the ligand out of the pocket, and it is closer to "
                    "an experimental quantity than a docking score. It depends on enough sampling, meaning overlapping "
                    "windows and agreement between the two halves. Without convergence it only supports a qualitative comparison.",
                    "PMF の井戸の深さはリガンドをポケットから取り出すのに必要な自由エネルギーで、ドッキングスコアより実験値に近い量です。"
                    "ただしサンプリングが十分であること、つまりウィンドウが重なり、前半と後半が一致していることが前提です。収束していなければ定性的な比較にしか使えません。",
                    "PMF 우물의 깊이는 리간드를 포켓에서 빼내는 데 필요한 자유 에너지이며 도킹 점수보다 실험값에 가까운 양입니다. "
                    "다만 샘플링이 충분해야 합니다. 즉 윈도우가 서로 겹치고 앞뒤 절반의 결과가 일치해야 합니다. 수렴하지 않았다면 정성적 비교에만 쓸 수 있습니다."),
    },
}


SECTION.update(SR.SUB_SECTIONS)        # D-82: structure prediction, membrane, long run, coarse-grained


class Doc:
    """Numbered figures and tables."""

    def __init__(self, lang: str, figdir: Path | None = None):
        self.lang, self.nf, self.nt = lang, 0, 0
        self.figdir = figdir or Path(".")
        self.collected: list[dict] = []
        self.index: list[dict] = []          # every figure with its texts, for the interface gallery (D-58)
        self.section = ""

    def t(self, pair) -> str:
        return tx(pair, self.lang)

    def figure(self, path, caption_pair) -> str:
        img = _img(path)
        if not img:
            return ""
        self.nf += 1
        return (f"<figure>{img}<div class=caption><b>{self.t(H['figure'])} {self.nf}.</b> "
                f"{_esc(self.t(caption_pair))}</div></figure>")

    def figure_block(self, path, kind: str, findings: list[dict], subject: str = "") -> str:
        """Figure + caption + how to read (general) + what it shows in this project (scenario sentences)."""
        img = _img(path)
        if not img:
            return ""
        self.nf += 1
        self.collected += findings
        f = FIG[kind]
        title = self.t(f["title"]) + (colon(self.lang) + subject if subject else "")
        items = "".join(f"<li class={x['level']}>{_esc(self.t(x['text']))}</li>" for x in findings)
        self.index.append({"n": self.nf, "kind": kind, "section": self.section, "subject": subject, "path": str(path),
                           "title": self.t(f["title"]), "caption": self.t(f["caption"]), "read": self.t(f["read"]),
                           "findings": [{"level": x["level"], "text": self.t(x["text"])} for x in findings]})
        sep = stop(self.lang)
        return (f"<div class=figblock><figure>{img}<div class=caption><b>{self.t(H['figure'])} {self.nf}.</b> {_esc(title)}{sep}"
                f"{_esc(self.t(f['caption']))}</div></figure><div class=figtext>"
                f"<p><b>{self.t(H['how_to_read'])}</b>　{_esc(self.t(f['read']))}</p>"
                + (f"<p><b>{self.t(H['in_project'])}</b></p><ul class=findings>{items}</ul>" if items else "") + "</div></div>")

    def table(self, headers: list, rows: list[list], caption_pair, num_cols: set | None = None) -> str:
        self.nt += 1
        num_cols = num_cols or set()
        head = "".join(f"<th class={'num' if i in num_cols else ''}>{_esc(h)}</th>" for i, h in enumerate(headers))
        body = "".join("<tr>" + "".join(f"<td class={'num' if i in num_cols else ''}>{c}</td>" for i, c in enumerate(r)) + "</tr>"
                       for r in rows)
        return (f"<div class=caption><b>{self.t(H['table'])} {self.nt}.</b> {_esc(self.t(caption_pair))}</div>"
                f"<table><tr>{head}</tr>{body}</table>")


def _findings_html(findings: list[dict], lang: str) -> str:
    if not findings:
        return ""
    return "<ul class=findings>" + "".join(f"<li class={f['level']}>{_esc(tx(f['text'], lang))}</li>" for f in findings) + "</ul>"


def _synthesis(findings: list[dict], lang: str) -> str:
    """Section-level interpretation: cautions first (what limits the conclusion), then what the data support."""
    if not findings:
        return ""
    cau = [f for f in findings if f["level"] == "caution"]
    good = [f for f in findings if f["level"] == "good"]
    note = [f for f in findings if f["level"] == "note"]
    out = ""
    if good or (note and not cau):
        out += f"<p>{_esc(tx(H['synthesis_ok'], lang))}</p>" + _findings_html((good or note)[:4], lang)
    if cau:
        out += f"<p>{_esc(tx(H['synthesis_caution'], lang))}</p>" + _findings_html(cau, lang)
    return out


def _section(doc: Doc, n: int, key: str, params_html: str, results_html: str, findings: list[dict]) -> str:
    s = SECTION[key]
    L = doc.lang
    return "".join([f"<h2>{n}. {_esc(tx(s['title'], L))}</h2>",
                    f"<h4>{tx(H['what'], L)}</h4><p>{_esc(tx(s['what'], L))}</p>",
                    f"<h4>{tx(H['meaning'], L)}</h4><p>{_esc(tx(s['meaning'], L))}</p>",
                    (f"<h4>{tx(H['params'], L)}</h4>{params_html}" if params_html else ""),
                    f"<h4>{tx(H['results'], L)}</h4>{results_html or '<p class=muted>' + _esc(tx(H['not_run'], L)) + '</p>'}",
                    (f"<h4>{tx(H['interpretation'], L)}</h4>{_synthesis(findings, L)}" if findings else "")])


# ------------------------------------------------------------------------------------------- parameters actually used
def actual_values(wf) -> dict:
    """Parameter values the run really used: the config, then the protocol of the first MD run, then engine defaults."""
    from ..engine.protocol import TIERS, make_protocol
    from ..sampling.binding import BindingConfig
    cfg = wf.cfg
    md, dk, b = cfg.get("md") or {}, cfg.get("docking") or {}, cfg.get("binding") or {}
    tier = md.get("tier", "teaching")
    v = {"tier": tier, "restraints": md.get("restraints") or "standard", "replicas": int(md.get("replicas", 1)),
         "solvent": md.get("solvent", "explicit"), "box_shape": md.get("box_shape", "dodecahedron"),
         "docking_mode": dk.get("mode", "independent"), "exhaustiveness": dk.get("exhaustiveness", 16), "n_poses": dk.get("n_poses", 9),
         "binding": bool(b.get("enabled"))}
    from ..workflow import TIER_PADDING_NM
    v["padding_nm"] = md.get("padding_nm") if md.get("padding_nm") is not None else TIER_PADDING_NM.get(tier, 2.0)
    ions = md.get("ions") or {}
    v.update({"ion_positive": ions.get("positive", "Na+"), "ion_negative": ions.get("negative", "Cl-"),
              "ion_concentration_molar": ions.get("concentration_molar", md.get("ionic_strength_molar", 0.15)),
              "neutralize": ions.get("neutralize", True)})
    proto = None
    runs = (wf.state()["steps"].get("md_runs") or {}).get("runs") or {}
    cases = (wf.state()["steps"].get("md_cases") or {}).get("cases") or {}
    for key, r in runs.items():
        if r.get("run_ids") and key in cases:
            try:
                from ..project import Run
                proto = Run(wf.project.case(cases[key]["case_id"]), r["run_ids"][0]).manifest().get("protocol")
            except Exception:  # noqa: BLE001
                proto = None
            if proto:
                break
    try:
        default = make_protocol(tier, production_ns=md.get("production_ns"), restraints=v["restraints"]).to_dict()
        for s_ in default["stages"]:
            s_.update((md.get("stage_overrides") or {}).get(s_["name"], {}))
    except Exception:  # noqa: BLE001
        default = {"stages": []}
    # D-59: per stage, the run's own protocol wins; stages or fields it lacks (old or partial manifests) fall back to the tier defaults
    st = {s["name"]: dict(s) for s in default.get("stages") or []}
    for s_ in (proto or {}).get("stages") or []:
        st.setdefault(s_["name"], {}).update({k: x for k, x in s_.items() if x is not None})
    mn, nvt, npt, prod = (st.get(k, {}) for k in ("minimize", "nvt", "npt", "production"))
    v.update({"minimize_iterations": mn.get("max_iterations"), "minimize_tolerance": mn.get("tolerance_kj_mol_nm"),
              "heat_start_k": nvt.get("start_temperature_k"), "nvt_ps": nvt.get("length_ps"), "npt_ps": npt.get("length_ps"),
              "temperature_k": prod.get("temperature_k"), "pressure_bar": prod.get("pressure_bar"),
              "friction_per_ps": prod.get("friction_per_ps"), "timestep_fs": prod.get("timestep_fs"),
              "production_ns": (prod.get("length_ps") or 0) / 1000.0 if prod else None,
              "trajectory_interval_ps": prod.get("trajectory_interval_ps")})
    if v["binding"]:
        try:
            bc = wf._binding_config(b)
        except Exception:  # noqa: BLE001
            bc = BindingConfig()
        for k in ("pull_distance_nm", "pull_velocity_nm_per_ps", "k_pull", "k_umbrella", "window_equil_ps", "window_prod_ps",
                  "target_overlap"):
            v[k] = getattr(bc, k)
    _ = TIERS
    return {k: x for k, x in v.items() if x is not None}


def _param_table(doc: Doc, rows: list[dict], caption) -> str:
    L = doc.lang
    out = []
    for r in rows:
        tag = f"<span class='tag changed'>{_esc(tx(H['changed'], L))}</span>" if r["value"] != r["recommended"] and r["key"] in doc.user_keys else ""
        out.append([_esc(r["label"]), _esc(r["value_text"]) + tag, _esc(r["recommended_text"]), _esc(r["why"])])
    return doc.table([tx(H["parameter"], L), tx(H["value"], L), tx(H["recommended"], L), tx(H["reason"], L)], out, caption)


# ------------------------------------------------------------------------------------------- sections
def _design(doc: Doc, wf) -> str:
    L, cfg = doc.lang, wf.cfg
    rec = cfg.get("receptor") or {}
    ligs = cfg.get("ligands") or []
    rows = [[_esc(l.get("name")), _esc(tx(("胜肽", "peptide", "ペプチド", "펩타이드") if l.get("sequence") else
                                          ("小分子", "small molecule", "低分子", "저분자"), L)),
             f"<code>{_esc(l.get('sequence') or l.get('smiles') or l.get('sdf') or '—')}</code>"] for l in ligs]
    systems = (cfg.get("md") or {}).get("systems") or []
    sys_txt = {"apo": ("蛋白單獨", "protein alone", "タンパク質単独", "단백질 단독"),
               "docked_single": ("每個配體各自與蛋白", "each ligand with the protein", "各リガンドとタンパク質", "각 리간드와 단백질"),
               "docked_multi": ("所有配體同時與蛋白", "all ligands together with the protein", "全リガンドを同時にタンパク質と", "모든 리간드를 함께 단백질과")}
    goal = cfg.get("goal")
    c = colon(L)
    p = (f"<p class=lead>{_esc(tx(('受體', 'Receptor', '受容体', '수용체'), L))}{c}<b>{_esc(rec.get('pdb_id') or Path(str(rec.get('file', '—'))).name)}</b>"
         f"{(' · ' + _esc(tx(('排除鏈', 'excluded chains', '除外した鎖', '제외한 사슬'), L)) + ' ' + _esc(', '.join(rec.get('exclude_chains')))) if rec.get('exclude_chains') else ''}"
         f" · pH {cfg.get('ph', 7.4)} · {_esc(tx(('模擬系統', 'Systems', 'シミュレーションする系', '시뮬레이션 시스템'), L))}{c}"
         f"{_esc(', '.join(tx(sys_txt.get(s, (s, s)), L) for s in systems))}"
         + (f" · {_esc(tx(('研究目標', 'Goal', '研究の目的', '연구 목표'), L))}{c}{_esc(tx(advisor.GOALS[goal], L))}" if goal in advisor.GOALS else "") + "</p>")
    val = cfg.get("validation")
    if val:
        p += f"<p class=muted>{_esc(tx(('依據文獻', 'Based on', '参照した文献', '참고 문헌'), L))}{c}{_esc((val.get('paper') or {}).get('citation', ''))}</p>"
    tab = doc.table([tx(("名稱", "Name", "名前", "이름"), L), tx(("種類", "Type", "種類", "종류"), L),
                     tx(("結構（SMILES 或序列）", "Structure (SMILES or sequence)", "構造（SMILES または配列）", "구조 (SMILES 또는 서열)"), L)],
                    rows, ("研究的配體", "Ligands studied", "対象のリガンド", "연구한 리간드")) if rows else ""
    return _section(doc, doc.next(), "design", "", p + tab + _evidence_html(doc, wf), [])


def _evidence_html(doc: Doc, wf) -> str:
    """D-108 (F01): planned vs run vs what the evidence supports, before any result is shown."""
    from . import evidence as EV
    rows = EV.evidence_rows(wf)
    if not rows:
        return ""
    L = doc.lang
    word = {"supported": ("有證據", "supported", "裏付けあり", "근거 있음"), "limited": ("有限制", "limited", "制限あり", "제한 있음"),
            "missing": ("缺", "missing", "欠落", "없음")}
    cls = {"supported": "", "limited": "caution", "missing": "warn"}

    def yn(v):
        if isinstance(v, bool):
            return tx(("是", "yes", "はい", "예"), L) if v else tx(("否", "no", "いいえ", "아니오"), L)
        return _esc(str(v))
    body = []
    for r in rows:
        why = "；".join(tx(EV.R[x], L) if x in EV.R else _esc(x) for x in r["reasons"]) or "—"
        if r.get("detail"):
            why += f"（{_esc(r['detail'])}）"
        body.append([_esc(tx(EV.T[r["item"]], L)), _esc(r["subject"] or "—"), yn(r["planned"]), yn(r["done"]),
                     f"<b class={cls[r['status']]}>{_esc(tx(word[r['status']], L))}</b>" if cls[r["status"]] else _esc(tx(word[r["status"]], L)),
                     why])
    sm = EV.summary(rows)
    head = (f"<p>{_esc(tx(('證據覆蓋：', 'Evidence coverage: ', '裏付けの範囲：', '근거 범위: '), L))}"
            f"{sm['supported']} {_esc(tx(word['supported'], L))} · {sm['limited']} {_esc(tx(word['limited'], L))} · "
            f"{sm['missing']} {_esc(tx(word['missing'], L))}</p>")
    return head + doc.table([tx(("項目", "Item", "項目", "항목"), L), tx(("對象", "Subject", "対象", "대상"), L),
                             tx(("計畫", "Planned", "計画", "계획"), L), tx(("完成", "Done", "完了", "완료"), L),
                             tx(("證據", "Evidence", "裏付け", "근거"), L), tx(("限制或缺口", "Limitation or gap", "制限・欠落", "제한 또는 공백"), L)],
                            body, ("研究設計與證據覆蓋（計畫、實際執行、能支持什麼）", "Study design and evidence coverage (planned, run, what it supports)",
                                   "研究デザインと裏付けの範囲（計画・実行・何を支えるか）", "연구 설계와 근거 범위(계획, 실행, 무엇을 뒷받침하는가)")) \
        + _comparability_html(doc, wf)


def _comparability_html(doc: Doc, wf) -> str:
    """D-120 (F05): candidate x candidate matrix, next to the evidence coverage.  Grades come from the same functions
    compare_binding uses (report/comparability.py); one candidate → says there is nothing to compare."""
    from . import comparability as CP
    st = (wf.state() or {}).get("steps", {})
    results = {k: v for k, v in ((st.get("binding") or {}).get("results") or {}).items() if isinstance(v, dict)}
    if not results:
        return ""
    L = doc.lang
    title = doc.t(("候選之間的可比性", "Comparability between candidates", "候補どうしの比較可能性", "후보 사이의 비교 가능성"))
    if len(results) < 2:
        return (f"<h3>{_esc(title)}</h3><p class=muted>"
                + _esc(doc.t(("只有一個候選，沒有比較。", "There is only one candidate, so there is nothing to compare.",
                              "候補が 1 つだけなので、比較はありません。", "후보가 하나뿐이라 비교가 없습니다."))) + "</p>")
    conds = ((st.get("analysis") or {}).get("comparison") or {}).get("comparability") or {}
    mdc = CP.md_conditions_map(results, (st.get("md_cases") or {}).get("cases") or {}, conds.get("conditions"))
    m = CP.comparability_matrix(results, md_conditions=mdc)
    keys = m["candidates"]
    cls = {"ddg": "{}", "order": "{}", "descriptive": "<span class=muted>{}</span>", "none": "<b class=warn>{}</b>"}
    rows = []
    for a in keys:
        row = [f"<b>{_esc(a)}</b>"]
        for b in keys:
            g = m["cells"][a][b]["grade"]
            row.append("—" if g == "self" else cls[g].format(_esc(doc.t(CP.GRADE_LABEL[g]))))
        rows.append(row)
    out = f"<h3>{_esc(title)}</h3>"
    out += doc.table([""] + keys, rows,
                     ("候選 × 候選：每一對可以比到什麼程度", "Candidate by candidate: how far each pair can be compared",
                      "候補 × 候補：各組をどこまで比較できるか", "후보 × 후보: 각 쌍을 어디까지 비교할 수 있는가"))
    out += "<ul class=muted>" + "".join(f"<li><b>{_esc(doc.t(CP.GRADE_LABEL[g]))}</b>{colon(L)}{_esc(doc.t(CP.GRADE_MEANS[g]))}</li>"
                                        for g in CP.GRADES) + "</ul>"
    detail = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            c = m["cells"][a][b]
            items = [(x, "warn") for x in c["reasons"]] + [(x, "muted") for x in c["limits"] + c["notes"]]
            if not items:
                continue
            ul = "<ul>" + "".join(f"<li class={k}>{_esc(CP.reason_text(x, L))}</li>" for x, k in items) + "</ul>"
            detail.append([_esc(f"{a} × {b}"), _esc(doc.t(CP.GRADE_LABEL[c["grade"]])), ul])
    if detail:
        out += doc.table([doc.t(("組合", "Pair", "組み合わせ", "조합")), doc.t(("等級", "Level", "レベル", "등급")),
                          doc.t(("原因、限制與提醒", "Reasons, limits and reminders", "理由・制限・注意", "이유, 제한, 주의"))], detail,
                         ("每一對的原因", "Reasons for each pair", "各組の理由", "각 쌍의 이유"))
    return out


def _structure(doc: Doc, wf) -> str:
    L = doc.lang
    g = load_json(wf.dir / "structure_gates.json", {})
    gates = g.get("gates") or []
    params = doc.table([tx(H["parameter"], L), tx(H["value"], L)],
                       [["pH", str(wf.cfg.get("ph", 7.4))],
                        [tx(("保留的輔因子與金屬", "Cofactors and metals kept", "残した補因子と金属", "남긴 보조인자와 금속"), L),
                         _esc(", ".join(wf.cfg.get("keep_hetero") or []) or "—")]],
                       ("受體準備參數", "Receptor preparation parameters", "受容体準備のパラメータ", "수용체 준비 매개변수"))
    rows = [[_esc(x.get("name")), _esc(x.get("status")), _esc(x.get("explanation"))] for x in gates]
    prot = (wf.state()["steps"].get("receptor_docking") or {}).get("protonation") or {}
    res = doc.table([tx(("檢查項目", "Check", "確認項目", "확인 항목"), L), tx(("結果", "Result", "結果", "결과"), L),
                     tx(("說明", "Explanation", "説明", "설명"), L)], rows,
                    ("結構可信度檢查", "Structure validity checks", "構造の信頼性チェック", "구조 신뢰성 확인")) if rows else ""
    if prot.get("pocket_flags"):
        res += doc.table([tx(("殘基", "Residue", "残基", "잔기"), L), "pKa", tx(("注意", "Flag", "注意点", "주의"), L)],
                         [[_esc(f["residue"]), f"{f['pka']:.1f}", _esc("；".join(f["flags"]))] for f in prot["pocket_flags"]],
                         ("口袋殘基的 pKa 審查（PROPKA，未自動更改）", "Pocket residue pKa review (PROPKA, not changed automatically)",
                          "ポケット残基の pKa 確認（PROPKA、自動では変更しません）", "포켓 잔기의 pKa 검토 (PROPKA, 자동으로 바꾸지 않음)"), {1})
    return _section(doc, doc.next(), "structure", params, res, I.structure(gates))


def _screen(doc: Doc, wf) -> str:
    doc.section = tx(SECTION["screen"]["title"], doc.lang)
    st = wf.state()["steps"]
    d = st.get("screen_docking") or {}
    if not (wf.cfg.get("screen") or d):
        return ""
    L = doc.lang
    from ..docking.screen import rank_screen, failed_rows
    res = load_json(d.get("results", ""), {}) if d.get("results") else {}
    man = load_json((st.get("screen_library") or {}).get("manifest", ""), {}) if st.get("screen_library") else {}
    scfg = wf.cfg.get("screen") or {}
    rows = rank_screen(res, top_n=int(scfg.get("top_n", 20))) if res else []
    sel = list(scfg.get("select") or [])
    params = doc.table([tx(H["parameter"], L), tx(H["value"], L)],
                       [[tx(("搜尋強度", "Exhaustiveness", "探索の徹底度（exhaustiveness）", "탐색 강도(exhaustiveness)"), L),
                         str((res.get("params") or {}).get("exhaustiveness", scfg.get("exhaustiveness", 8)))],
                        [tx(("每個化合物的姿勢數", "Poses per compound", "化合物あたりのポーズ数", "화합물당 포즈 수"), L),
                         str((res.get("params") or {}).get("n_poses", scfg.get("n_poses", 3)))],
                        [tx(("化合物庫", "Library", "化合物ライブラリ", "화합물 라이브러리"), L), _esc(Path(str(scfg.get("library", "—"))).name)]],
                       ("篩選參數", "Screening parameters", "スクリーニングのパラメータ", "스크리닝 매개변수"))
    out = ""
    start = len(doc.collected)
    if rows:
        sc_f = FT.classify_screen(rows)
        out += doc.figure_block(FG.screen_ranking(rows, doc.figdir / "screen_ranking.png"), "screen_ranking",
                                [x for x in sc_f if "molecular size" not in x["text"][1]])
        out += _screen_extra(doc, d, rows, man, [x for x in sc_f if "molecular size" in x["text"][1]])
    if rows:
        out += doc.table([tx(("名次", "Rank", "順位", "순위"), L), tx(("化合物", "Compound", "化合物", "화합물"), L),
                          tx(("分數（kcal mol⁻¹）", "Score (kcal mol⁻¹)", "スコア（kcal mol⁻¹）", "점수 (kcal mol⁻¹)"), L),
                          tx(("與最佳差距", "Δ to best", "最良との差", "최고와의 차이"), L),
                          tx(("重原子", "Heavy atoms", "重原子数", "중원자 수"), L), tx(("配體效率", "Ligand efficiency", "リガンド効率", "리간드 효율"), L),
                          tx(("選入", "Selected", "選択", "선택"), L)],
                         [[str(r["rank"]), _esc(r["name"]), f"{r['score']:.2f}", f"{r['delta_to_best']:+.2f}", _fmt(r["heavy_atoms"], 0),
                           _fmt(r["ligand_efficiency"], 3), "✔" if r["name"] in sel else ""] for r in rows[:30]],
                         ("篩選排名（前 30 名）", "Screening ranking (top 30)", "スクリーニング順位（上位 30）", "스크리닝 순위 (상위 30)"), {0, 2, 3, 4, 5})
    bad = failed_rows(res, man) if res else []
    if bad:
        out += doc.table([tx(("化合物", "Compound", "化合物", "화합물"), L), tx(("階段", "Stage", "段階", "단계"), L),
                          tx(("原因", "Reason", "原因", "원인"), L)],
                         [[_esc(b["name"]), _esc(b["stage"]), _esc(b.get("error", ""))] for b in bad[:60]],
                         ("沒有納入篩選的化合物", "Compounds not screened", "スクリーニングに含まれなかった化合物", "스크리닝에서 빠진 화합물"))
    extra = I.screen(rows, len(bad), sel)[1:]          # failed count and user selection; the ranking itself is in the figure
    return _section(doc, doc.next(), "screen", params, out, doc.collected[start:] + extra)


def _screen_extra(doc: Doc, d: dict, rows: list[dict], man: dict, size_findings: list) -> str:
    """Score distribution, score against size, compound properties and chemical space (RDKit when available)."""
    from . import chem as CH
    out = ""
    sc = np.asarray([r["score"] for r in rows], float)
    hist = ((d.get("plots") or {}).get("histogram") or {}).get("png")
    if hist and len(sc) >= 5:
        thr = float(sc.mean() - sc.std())
        tail = [r["name"] for r in rows if r["score"] <= thr]
        m, s, n = f"{sc.mean():.2f}", f"{sc.std():.2f}", len(tail)
        out += doc.figure_block(hist, "screen_hist", [FT.S(
            "note",
            f"平均 {m} ± {s} kcal mol⁻¹。有 {n} 個化合物比平均好一個標準差以上（{'、'.join(tail[:6])}）。",
            f"Mean {m} ± {s} kcal mol⁻¹. {n} compounds score more than one standard deviation better than the mean ({', '.join(tail[:6])}).",
            f"平均は {m} ± {s} kcal mol⁻¹ です。平均より 1 標準偏差以上よいスコアの化合物は {n} 個です（{'、'.join(tail[:6])}）。",
            f"평균은 {m} ± {s} kcal mol⁻¹입니다. 평균보다 1 표준편차 이상 좋은 화합물은 {n}개입니다 ({', '.join(tail[:6])}).")])
    scat = ((d.get("plots") or {}).get("scatter") or {}).get("png")
    if scat:
        out += doc.figure_block(scat, "screen_scatter", size_findings or [FT.S(
            "note", "分數與分子大小沒有強相關，排名不是由分子大小決定的。",
            "Score and size are not strongly correlated, so molecular size does not drive the ranking.",
            "スコアと分子の大きさに強い相関はなく、順位は分子の大きさで決まっていません。",
            "점수와 분자 크기 사이에 강한 상관이 없으므로 순위는 분자 크기로 정해지지 않았습니다.")])
    entries = (man or {}).get("entries") or {}
    props, bits, names, scores = [], [], [], []
    for r in rows:
        path = (entries.get(r["name"]) or {}).get("path")
        if not path:
            continue
        pr = CH.properties_from_sdf(path)
        if pr:
            props.append(pr)
            fb = CH.fingerprint_bits(path)
            if fb is not None:
                bits.append(fb); names.append(r["name"]); scores.append(r["score"])
    if props:
        out += doc.figure_block(FG.properties_plot(props, doc.figdir / "screen_properties.png"), "properties", FT.classify_properties(props))
    if len(bits) >= 6:
        xy = CH.chem_space_xy(np.array(bits))
        out += doc.figure_block(FG.chem_space_plot(xy, scores, names, doc.figdir / "screen_chemspace.png"), "chem_space",
                                FT.classify_chem_space(xy, scores, names))
    return out


def _docking_joint(doc: Doc, e: dict, box: dict, prot: list, rank_used: int, charges) -> str:
    """D-60: simultaneous (joint) poses — figures about the arrangement of the ligands, not about one ligand."""
    names = list(e.get("ligands") or (e.get("pose_sdfs") or {}).keys())
    sdfs = e.get("pose_sdfs") or {}
    per = {n: [DF.sdf_heavy(p) if p and Path(p).is_file() else None for p in sdfs.get(n, [])] for n in names}
    n_p = min((len(v) for v in per.values()), default=0)
    out = ""
    scores = [p["score"] for p in e["poses"]]
    joint = [np.vstack([per[n][k] for n in names]) if all(per[n][k] is not None for n in names) else None for k in range(n_p)]
    if any(x is not None for x in joint):
        D = DF.pose_rmsd_matrix(joint)
        out += doc.figure_block(FG.heatmap(D, doc.figdir / "docking_rmsd_joint.png", cmap="viridis_r", vmin=0, vmax=max(1.0, float(np.nanmax(D))),
                                           label="RMSD (Å)", ticks=[str(i + 1) for i in range(len(D))], xlabel="Joint pose rank", ylabel="Joint pose rank"),
                                "pose_rmsd", DF.classify_pose_rmsd("joint", D, scores), "joint")
    if any(p.get("rmsd_ref") is not None for p in e["poses"]):
        out += doc.figure_block(FG.funnel(e["poses"], doc.figdir / "docking_funnel_joint.png"), "funnel", DF.classify_funnel("joint", e["poses"]), "joint")
    out += doc.figure_block(FG.joint_poses(e["poses"], names, doc.figdir / "docking_joint_poses.png", chosen=rank_used), "joint_poses",
                            DF.classify_joint_poses(e["poses"], names, rank_used, charges), "joint")
    cents = {n: np.array([x.mean(0) for x in per[n] if x is not None]) for n in names if any(x is not None for x in per[n])}
    out += doc.figure_block(FG.positions_by_ligand(cents, box, doc.figdir / "docking_joint_positions.png"), "joint_positions",
                            DF.classify_joint_positions(cents), "joint")
    k = (rank_used or 1) - 1
    if prot and all(k < len(per[n]) and per[n][k] is not None for n in names):
        rows, M = DF.subsite_map({n: per[n][k] for n in names}, prot)
        out += doc.figure_block(FG.binary_map(rows, M, doc.figdir / "docking_subsites.png", cols=names, xlabel="Ligand"), "subsites",
                                DF.classify_subsites(rows, M, names), f"joint #{rank_used}")
    return out


_REJ_CODE = {"geometry_repairable": ("可由建模修正的幾何問題", "geometry the build can repair", "モデル構築で修正できる幾何の問題", "모델 구축에서 고칠 수 있는 기하 문제"),
             "model_limitation": ("對接模型的限制", "limit of the docking model", "ドッキングモデルの限界", "도킹 모델의 한계"),
             "hypothesis_change": ("假設不成立", "the hypothesis does not hold", "仮定が成り立たない", "가정이 성립하지 않음")}


def _reject_sentence(r: dict, L: str) -> str:
    """D-110: the docking rejection in the interface language from its rule + params; falls back to the stored
    Chinese text for an older manifest that has no params."""
    rule, pr = r.get("rule"), r.get("params")
    if not rule or pr is None:
        return str(r.get("text") or "")
    if rule == "score_window":
        return tx((f"分數差 {pr['gap']} > {pr['window']} kcal/mol", f"score {pr['gap']} worse than the best by > {pr['window']} kcal/mol",
                   f"スコア差 {pr['gap']} > {pr['window']} kcal/mol", f"점수 차 {pr['gap']} > {pr['window']} kcal/mol"), L)
    if rule == "shallow_ligand":
        ls = ",".join(str(x) for x in pr["ligands"])
        return tx((f"配體 {ls} 接觸 < {pr['min_contacts']}（一深一淺）", f"ligand {ls} has < {pr['min_contacts']} contacts (one deep, one shallow)",
                   f"リガンド {ls} の接触 < {pr['min_contacts']}（片方が浅い）", f"리간드 {ls} 접촉 < {pr['min_contacts']}(한쪽이 얕음)"), L)
    if rule == "surface_pose":
        return tx((f"接觸 {pr['contacts']} < {pr['min_contacts']}（可能在表面）", f"{pr['contacts']} contacts < {pr['min_contacts']} (may be on the surface)",
                   f"接触 {pr['contacts']} < {pr['min_contacts']}（表面の可能性）", f"접촉 {pr['contacts']} < {pr['min_contacts']}(표면일 수 있음)"), L)
    if rule == "ligand_clash":
        return tx((f"配體間 {pr['distance']} Å < {pr['limit']}（碰撞）", f"ligands {pr['distance']} Å apart < {pr['limit']} (clash)",
                   f"リガンド間 {pr['distance']} Å < {pr['limit']}（衝突）", f"리간드 간 {pr['distance']} Å < {pr['limit']}(충돌)"), L)
    if rule == "not_co_occupying":
        return tx((f"配體間 {pr['distance']} Å > {pr['limit']}（未共同佔據口袋）", f"ligands {pr['distance']} Å apart > {pr['limit']} (not co-occupying the pocket)",
                   f"リガンド間 {pr['distance']} Å > {pr['limit']}（ポケットを共有していない）", f"리간드 간 {pr['distance']} Å > {pr['limit']}(포켓을 공유하지 않음)"), L)
    return str(r.get("text") or "")


def _used_pose_rejections(sel: dict, entry: str, L: str) -> str:
    """D-98 (A7): a used pose that docking had rejected keeps its original reasons in the report, with their class,
    whether it was taken by the least-risk fallback or chosen by a person; the build's repair is reported separately."""
    seen, out = set(), ""
    for v in (sel.get("ligands") or {}).values():
        rej = v.get("docking_rejections") or []
        if v.get("entry") != entry or not rej or v.get("rank") in seen:
            continue
        seen.add(v.get("rank"))
        how = (tx(("低風險後備選用（不是推薦）", "Taken by the least-risk fallback (not a recommendation)",
                   "低リスクの代替として選択（推奨ではない）", "저위험 대안으로 선택(추천 아님)"), L) if v.get("fallback") else
               tx(("依使用者指定", "Chosen by the user", "ユーザーの指定", "사용자 지정"), L))
        items = ("；" if L in ("zh", "ja") else "; ").join(
            f"{_reject_sentence(r, L)}{paren(tx(_REJ_CODE.get(r.get('code'), (r.get('code'),) * 4), L), L)}" for r in rej)
        head = tx(("選用的第 {r} 名姿勢在對接層被排除；原始理由（保留）", "The used pose (rank {r}) was rejected at docking; original reasons (kept)",
                   "使用したポーズ（順位 {r}）はドッキングで除外されました。元の理由（保持）", "사용한 포즈(순위 {r})는 도킹에서 제외되었습니다. 원래 이유(유지)"), L)
        tail = tx(("建模後的幾何修正與檢查見下方多配體幾何表", "The repair and re-check during the build are in the multi-ligand geometry table below",
                   "モデル構築での修正と再検査は下の複数リガンド幾何表にあります", "모델 구축 중 수정과 재검사는 아래 다중 리간드 기하 표에 있습니다"), L)
        out += (f"<p class=muted>⚠ {_esc(head.format(r=v.get('rank')))}{colon(L)}{_esc(items)}{stop(L)}"
                f"{_esc(how)}{stop(L)}{_esc(tail)}{stop(L)}</p>")
    return out


def _geometry_table(doc: Doc, rec: dict) -> str:
    """D-60: what the multi-ligand geometry check found and did, per ligand."""
    L = doc.lang
    if not rec or not rec.get("per_ligand"):
        return ""
    excluded = ("排除", "excluded", "除外", "제외")
    rows = []
    for n, v in rec["per_ligand"].items():
        if n in (rec.get("adjusted") or {}):
            a = rec["adjusted"][n]
            act = tx((f"剛體微調 {a['rmsd']} Å", f"nudged {a['rmsd']} Å", f"剛体として {a['rmsd']} Å 微調整", f"강체 미세 조정 {a['rmsd']} Å"), L)
        elif n in (rec.get("excluded") or []):
            act = tx(excluded, L)
        elif rec.get("culprit") == n and rec.get("status") == "DEFERRED":
            act = tx(("交給建模時的軟核鬆弛處理", "handed to the soft-core relaxation at build time",
                      "構築時のソフトコア緩和に任せる", "구축 단계의 소프트코어 완화로 넘김"), L)
        elif rec.get("culprit") == n:
            act = tx(("建議排除（待決定）", "exclusion recommended (pending)", "除外を推奨（判断待ち）", "제외 권장 (결정 대기)"), L)
        else:
            act = "—"
        rows.append([_esc(n), _esc(v.get("contacts")), _esc(v.get("overlaps")), _esc(v.get("piercings")),
                     _esc(tx(("是", "yes", "あり", "예"), L) if v.get("floating") else "—"), _esc(act)])
    for n in rec.get("excluded") or []:
        if n not in rec["per_ligand"]:
            rows.append([_esc(n), "—", "—", "—", "—", _esc(tx(excluded, L))])
    tab = doc.table([tx(("配體", "Ligand", "リガンド", "리간드"), L), tx(("蛋白接觸", "Protein contacts", "タンパク質との接触", "단백질 접촉"), L),
                     tx(("原子重疊", "Overlaps", "原子の重なり", "원자 겹침"), L), tx(("穿環", "Ring piercing", "環の貫通", "고리 관통"), L),
                     tx(("漂浮", "Floating", "浮遊", "떠 있음"), L), tx(("處置", "Action", "対応", "조치"), L)], rows,
                    ("多配體複合物的幾何檢查（進入 MD 前）", "Geometry of the multi-ligand complex (before MD)",
                     "複数リガンド複合体の幾何チェック（MD の前）", "다중 리간드 복합체의 기하 확인 (MD 전)"))
    why = rec.get("why") or ""
    return tab + f"<p>{_esc(tx(tuple(why) if isinstance(why, list) else why, L))}</p>"


def _docking_extra(doc: Doc, e: dict, box: dict, rec_pdb, cmp_rows: list, rank_used: int | None = None, charges=None) -> str:
    """D-59: pose similarity, docking funnel, pose positions in the box and contact residues across poses."""
    out = ""
    prot = DF.receptor_atoms(rec_pdb) if rec_pdb and Path(rec_pdb).is_file() else []
    if e["name"] == "joint" or len(e.get("ligands") or []) > 1:
        return _docking_joint(doc, e, box, prot, rank_used or 1, charges)
    scores = [p["score"] for p in e["poses"]]
    for lig, paths in (e.get("pose_sdfs") or {}).items():
        poses = [DF.sdf_heavy(pth) if pth and Path(pth).is_file() else None for pth in paths]
        if not any(x is not None for x in poses):
            continue
        tag = f"{e['name']}" + (f" {lig}" if lig != e["name"] else "")
        D = DF.pose_rmsd_matrix(poses)
        out += doc.figure_block(FG.heatmap(D, doc.figdir / f"docking_rmsd_{tag}.png", cmap="viridis_r", vmin=0, vmax=max(1.0, float(np.nanmax(D))),
                                           label="RMSD (Å)", ticks=[str(i + 1) for i in range(len(D))], xlabel="Pose rank", ylabel="Pose rank"),
                                "pose_rmsd", DF.classify_pose_rmsd(tag, D, scores), tag)
        if any(p.get("rmsd_ref") is not None for p in e["poses"]):
            out += doc.figure_block(FG.funnel(e["poses"], doc.figdir / f"docking_funnel_{tag}.png"), "funnel", DF.classify_funnel(tag, e["poses"]), tag)
        cents = np.array([x.mean(0) for x in poses if x is not None])
        sc = [s_ for s_, x in zip(scores, poses) if x is not None]
        out += doc.figure_block(FG.pose_positions(cents, sc, box, doc.figdir / f"docking_positions_{tag}.png"), "pose_positions",
                                DF.classify_positions(tag, cents, box), tag)
        if prot:
            rows, M = DF.contact_map(poses, prot)
            out += doc.figure_block(FG.binary_map(rows, M, doc.figdir / f"docking_contacts_{tag}.png"), "pose_contacts",
                                    DF.classify_contact_map(tag, rows, M), tag)
        if e["name"] != "joint" and poses[0] is not None:
            n = len(poses[0])
            cmp_rows.append({"name": lig, "score": float(min(scores)), "heavy": n, "le": float(min(scores)) / max(1, n)})
    return out


def _docking(doc: Doc, wf, vals, f, goal) -> str:
    doc.section = tx(SECTION["docking"]["title"], doc.lang)
    L = doc.lang
    d = wf.state()["steps"].get("docking") or {}
    rows = [r for r in advisor.parameter_table(vals, f, goal, L) if r["group_key"] == "docking"]
    params = _param_table(doc, rows, ("對接參數", "Docking parameters", "ドッキングのパラメータ", "도킹 매개변수"))
    if not d:
        return _section(doc, doc.next(), "docking", params, "", [])
    res = load_json(d["result"], {})
    sel = (wf.state()["steps"].get("pose_selection") or {}).get("selection", {})
    box = res.get("box") or {}
    out = (f"<p>{_esc(tx(('搜尋區中心', 'Box centre', '探索ボックスの中心', '탐색 상자 중심'), L))} {_esc(box.get('center'))} Å · "
           f"{_esc(tx(('尺寸', 'size', 'サイズ', '크기'), L))} {_esc(box.get('size'))} Å · "
           f"{_esc(tx(('來源', 'source', '設定元', '출처'), L))} {_esc(box.get('source'))}</p>")
    chosen = {}
    for v in (sel.get("ligands") or {}).values():
        chosen.setdefault(v.get("entry"), set()).add(v.get("rank"))
    start = len(doc.collected)
    cmp_rows: list[dict] = []
    for e in res.get("entries", []):
        rank_used = min(chosen.get(e["name"], {e.get("recommended_rank") or 1}))
        out += doc.figure_block(FG.docking_scores(e["poses"], rank_used, e["name"], doc.figdir / f"docking_{e['name']}.png"),
                                "docking_scores", FT.classify_docking_scores(e["name"], e["poses"], rank_used), e["name"])
        rec_pdb = (wf.state()["steps"].get("receptor_docking") or {}).get("path")
        out += _docking_extra(doc, e, res.get("box") or {}, rec_pdb, cmp_rows, rank_used, (res.get("params") or {}).get("ligand_charges"))
        for lig, info in (sel.get("ligands") or {}).items():
            if info.get("entry") == e["name"] and info.get("sdf") and rec_pdb and Path(info["sdf"]).is_file():
                from .chem import interaction_diagram
                png, cons = interaction_diagram(info["sdf"], rec_pdb, doc.figdir / f"docking_2d_{lig}.png")
                if png:
                    out += doc.figure_block(png, "interaction_2d", FT.classify_interaction_2d(lig, cons), lig)
        trs = []
        for p in e["poses"]:
            tag = ("✔ " + tx(("選用", "used", "使用", "사용"), L) if p["rank"] in chosen.get(e["name"], set()) else "") + \
                  (" ★ " + tx(("推薦", "recommended", "推奨", "추천"), L) if p.get("recommended") else "") + \
                  (" ⚠ " + tx(("碰撞", "clash", "衝突", "충돌"), L) if p.get("clash") else "")
            joint = p.get("contacts_per_ligand") is not None
            cont = " / ".join(str(c) for c in p["contacts_per_ligand"]) if joint else str(p["contacts"])
            row = [str(p["rank"]), f"{p['score']:.2f}", f"{p['cluster']} ({p['cluster_size']})", cont, _fmt(p.get("rmsd_ref"))]
            if joint:
                row.append(_fmt(p.get("min_ll_distance")))
            trs.append(row + [tag])
        is_joint = bool(e["poses"]) and e["poses"][0].get("contacts_per_ligand") is not None
        head = [tx(("名次", "Rank", "順位", "순위"), L), tx(("分數（kcal mol⁻¹）", "Score (kcal mol⁻¹)", "スコア（kcal mol⁻¹）", "점수 (kcal mol⁻¹)"), L),
                tx(("叢集（大小）", "Cluster (size)", "クラスター（大きさ）", "클러스터 (크기)"), L),
                tx(("接觸殘基數", "Contacts", "接触残基数", "접촉 잔기 수"), L) + (f" ({' / '.join(e.get('ligands') or [])})" if is_joint else ""),
                tx(("與晶體 RMSD（Å）", "RMSD to crystal (Å)", "結晶との RMSD（Å）", "결정 구조와의 RMSD (Å)"), L)] + \
            ([tx(("配體間最短距離（Å）", "Min. ligand–ligand (Å)", "リガンド間の最短距離（Å）", "리간드 간 최단 거리 (Å)"), L)] if is_joint else []) + [""]
        nm = e["name"]
        out += doc.table(head, trs, (f"{nm} 的對接姿勢", f"Docking poses of {nm}", f"{nm} のドッキングポーズ", f"{nm}의 도킹 포즈"),
                         {0, 1, 4, 5} if is_joint else {0, 1, 3, 4})
        if e.get("reason"):
            out += (f"<p class=muted>{_esc(tx(('系統推薦的理由', 'Reason for the recommendation', '推奨の理由', '추천 이유'), L))}"
                    f"{colon(L)}{_esc(e['reason'])}</p>")
        out += _used_pose_rejections(sel, e["name"], L)
    out += _geometry_table(doc, wf.state().get("multi_ligand") or {})
    nos = SR.selection_rows(wf, L)                     # D-82: placed from a predicted complex, no docking entry
    if nos:
        out += doc.table([tx(("配體", "Ligand", "リガンド", "리간드"), L), tx(("分數（kcal mol⁻¹）", "Score (kcal mol⁻¹)", "スコア（kcal mol⁻¹）", "점수 (kcal mol⁻¹)"), L)],
                         nos, ("不經對接、由預測複合物放置的胜肽", "Peptides placed from a predicted complex without docking",
                               "ドッキングを経ずに予測複合体から置いたペプチド", "도킹 없이 예측 복합체에서 놓은 펩타이드"))
    if len(cmp_rows) >= 2:
        out += doc.figure_block(FG.ligand_compare(cmp_rows, doc.figdir / "docking_compare.png"), "ligand_compare", DF.classify_ligand_compare(cmp_rows))
    return _section(doc, doc.next(), "docking", params, out, doc.collected[start:])


_CPP_STATUS = {  # the peptide module records these values in Chinese
    "實驗證實": ("實驗證實", "experimentally confirmed", "実験で確認済み", "실험으로 확인됨"),
    "計算預測": ("計算預測", "computational prediction", "計算による予測", "계산 예측"),
    "未評估": ("未評估", "not assessed", "未評価", "평가 안 함"),
    "不適用": ("不適用", "not applicable", "該当なし", "해당 없음"),
    "可能穿膜": ("可能穿膜", "likely to penetrate", "膜を通過する可能性あり", "막 투과 가능성 있음"),
    "不太可能穿膜": ("不太可能穿膜", "unlikely to penetrate", "膜を通過する可能性は低い", "막 투과 가능성 낮음"),
}


def _peptide(doc: Doc, wf) -> str:
    st = wf.state()
    cpp, acc = st.get("cpp") or {}, st.get("peptide_access") or {}
    if not cpp and not acc:
        return ""
    L = doc.lang
    loc = {"intracellular": ("胞內", "intracellular", "細胞内", "세포 내"),
           "extracellular-membrane": ("膜外側", "extracellular, membrane", "膜の細胞外側", "막 바깥쪽"),
           "secreted": ("分泌或胞外", "secreted or extracellular", "分泌型または細胞外", "분비형 또는 세포 외")}
    unset = ("未指定", "not specified", "未指定", "지정 안 함")
    prm = [[f"<code>{_esc(l.get('sequence'))}</code>", _esc(l.get("name")),
            _esc(tx(loc.get(str(l.get("target_location"))), L) if str(l.get("target_location")) in loc else (l.get("target_location") or tx(unset, L))),
            _esc(l.get("termini", "charged"))] for l in wf.cfg.get("ligands") or [] if l.get("sequence")]
    seq = ("序列", "Sequence", "配列", "서열")
    params = doc.table([tx(seq, L), tx(("名稱", "Name", "名前", "이름"), L), tx(("作用標靶的位置", "Target location", "標的の位置", "표적 위치"), L),
                        tx(("末端", "Termini", "末端", "말단"), L)], prm,
                       ("胜肽設定", "Peptide settings", "ペプチドの設定", "펩타이드 설정")) if prm else ""
    rows = []
    for name, r in cpp.items():
        tr = lambda x: tx(_CPP_STATUS[x], L) if x in _CPP_STATUS else x  # noqa: E731
        rows.append([_esc(name), tx(("穿膜性", "Cell penetration", "膜透過性", "세포막 투과성"), L), _esc(tr(r.get("status", ""))),
                     _esc(tr(r.get("prediction", "—"))), _esc(r.get("explanation", ""))])
    for name, r in acc.items():
        for part, lab in (("precheck", ("對接前的搜尋區與大小", "Before docking: box and size", "ドッキング前の探索ボックスと大きさ", "도킹 전 탐색 상자와 크기")),
                          ("pose", ("選用姿勢的埋藏程度與距離", "Chosen pose: burial and distance", "選んだポーズの埋没度と距離", "선택한 포즈의 매몰도와 거리"))):
            g = r.get(part)
            if g:
                rows.append([_esc(name), tx(lab, L), _esc(g.get("gate", "")), "", _esc(g.get("explanation", ""))])
    out = doc.table([tx(("胜肽", "Peptide", "ペプチド", "펩타이드"), L), tx(("檢查", "Check", "確認項目", "확인 항목"), L),
                     tx(("狀態", "Status", "状態", "상태"), L), tx(("預測", "Prediction", "予測", "예측"), L),
                     tx(("說明", "Explanation", "説明", "설명"), L)], rows,
                    ("胜肽的科學檢查", "Peptide scientific checks", "ペプチドの科学的チェック", "펩타이드 과학적 확인"))
    for name, r in cpp.items():
        sug = r.get("redesign_suggestions") or {}
        if sug:
            items = [c for b in sug.values() for c in b]
            out += doc.table([tx(seq, L), tx(("設計方式", "Design", "設計の方法", "설계 방식"), L),
                              tx(("預測分數", "Predicted score", "予測スコア", "예측 점수"), L), tx(("淨電荷", "Net charge", "正味電荷", "순전하"), L)],
                             [[f"<code>{_esc(c['sequence'])}</code>", _esc(c["how"]), f"{c['score']}/8", f"{c['net_charge']:+d}"] for c in items[:9]],
                             (f"{name} 的替代設計。這些是假設，要用實驗或外部工具確認",
                              f"Redesign options for {name}. These are hypotheses to confirm experimentally or with external predictors",
                              f"{name} の代替設計。仮説なので、実験または外部ツールで確認してください",
                              f"{name}의 대체 설계. 가설이므로 실험이나 외부 도구로 확인해야 합니다"),
                             {2, 3})
    return _section(doc, doc.next(), "peptide", params, out, I.peptide(cpp, acc))


def _md(doc: Doc, wf, vals, f, goal) -> str:
    doc.section = tx(SECTION["md"]["title"], doc.lang)
    L = doc.lang
    rows = [r for r in advisor.parameter_table(vals, f, goal, L) if r["group_key"] in ("system", "equil", "prod")]
    params = _param_table(doc, rows, ("模擬參數", "Simulation parameters", "シミュレーションのパラメータ", "시뮬레이션 매개변수"))
    cases = (wf.state()["steps"].get("md_cases") or {}).get("cases", {})
    runs = (wf.state()["steps"].get("md_runs") or {}).get("runs", {})
    ana = wf.state()["steps"].get("analysis") or {}
    sums = ana.get("summaries") or {}
    if not cases:
        return _section(doc, doc.next(), "md", params, "", [])
    trs = []
    metrics = {}
    restrained = False
    for key, c in cases.items():
        r = runs.get(key, {})
        s = sums.get(key, {})
        restrained = restrained or bool(s.get("restrained_production"))
        if s.get("metrics_file"):
            metrics[key] = load_json(s["metrics_file"], {})
        bound = "; ".join(f"{rn}: {_state_word(v, L)} (RMSD {v['rmsd_last20_A']:.1f} Å)"
                          for rn, v in (s.get("ligands") or {}).items()) or "—"
        link = ""
        if r.get("run_ids"):
            try:
                from ..project import Run
                rp = build_run_report(Run(wf.project.case(c["case_id"]), r["run_ids"][0]), lang=L)
                link = f"<a href='{rp.as_uri()}'>{_esc(tx(('單次模擬報告', 'run report', '個別の計算レポート', '개별 실행 보고서'), L))}</a>"
            except Exception:  # noqa: BLE001
                link = ""
        trs.append([_esc(key), _esc(", ".join(c.get("ligands") or []) or "—"), _esc(r.get("status", "—")),
                    _fmt(s.get("rmsd_backbone_mean_A")) + _restrained_tag(s, L), _esc(bound), link])
    system = ("系統", "System", "系", "시스템")
    out = doc.table([tx(system, L), tx(("配體", "Ligands", "リガンド", "리간드"), L), tx(("狀態", "Status", "状態", "상태"), L),
                     tx(("主鏈 RMSD 平均（Å）", "Mean backbone RMSD (Å)", "主鎖 RMSD の平均（Å）", "주사슬 RMSD 평균 (Å)"), L),
                     tx(("配體（最後 20 % 的口袋 RMSD）", "Ligand (pocket RMSD, last 20 %)", "リガンド（最後の 20 % のポケット RMSD）", "리간드 (마지막 20 %의 포켓 RMSD)"), L), ""],
                    trs, ("各系統的模擬結果摘要", "Summary of the simulated systems", "各系のシミュレーション結果のまとめ", "시스템별 시뮬레이션 결과 요약"), {3})
    # equilibration acceptance per system and stage (from the stage records of the first replica)
    acc_rows = []
    for key, c in cases.items():
        r = runs.get(key, {})
        if not r.get("run_ids"):
            continue
        try:
            from ..project import Run
            rdir = Run(wf.project.case(c["case_id"]), r["run_ids"][0]).dir
        except Exception:  # noqa: BLE001
            continue
        for stg in ("nvt", "npt", "production"):
            acc = (load_json(rdir / "stages" / stg / f"{stg}_complete.json", {}) or {}).get("acceptance") or {}
            for chk in acc.get("checks") or []:
                vals = ", ".join(f"{k} {v}" for k, v in chk.items() if k not in {"check", "ok"})
                acc_rows.append([_esc(key), _esc(stg.upper() if stg != "production" else tx(("正式模擬", "production", "本計算", "본 시뮬레이션"), L)),
                                 _esc(chk.get("check")), (tx(("通過", "pass", "合格", "통과"), L) if chk.get("ok") else
                                                          f"<b class=warn>{_esc(tx(('未通過', 'fail', '不合格', '미통과'), L))}</b>"), _esc(vals)])
    if acc_rows:
        out += doc.table([tx(system, L), tx(("階段", "Stage", "段階", "단계"), L), tx(("驗收項目", "Check", "合否の項目", "검수 항목"), L),
                          tx(("結果", "Result", "結果", "결과"), L), tx(("數值", "Values", "数値", "수치"), L)], acc_rows,
                         ("平衡與正式模擬的驗收檢查（溫度與密度）", "Acceptance checks of equilibration and production (temperature and density)",
                          "平衡化と本計算の合否チェック（温度と密度）", "평형화와 본 시뮬레이션의 검수 (온도와 밀도)"))
    comp = ana.get("comparison") or {}
    start = len(doc.collected)
    ext = {key: load_json(s_.get("extended_file"), {}) for key, s_ in sums.items() if s_.get("extended_file")}
    _repair_times(wf, cases, runs, metrics, ext)           # D-89: analyses made before the time-axis fix
    eq = _equil_figures(doc, wf, cases, runs)
    if eq:
        out += _sub(doc, "平衡過程的品質", "Equilibration quality", "平衡化の品質", "평형화 품질") + eq
    if metrics:
        disp = {key: {v: u for u, v in (c.get("ligand_map") or {}).items()} for key, c in cases.items()}
        out += _md_figures(doc, sums, metrics, ext, disp)
        out += _common_html(doc, comp)                      # D-106: systems on one basis, only when comparable
    else:                                              # older runs without metrics.json: the analysis images as drawn
        for key, s_ in sums.items():
            figs = s_.get("figures") or {}
            if figs.get("timeseries"):
                out += doc.figure_block(figs["timeseries"]["png"], "rmsd", [], key)
            for k, fig in figs.items():
                if k.startswith("contacts_"):
                    out += doc.figure_block(fig["png"], "contacts", [], key)
    findings = doc.collected[start:]
    if restrained:
        findings.append(I.F("caution", "正式模擬保留了主鏈約束，RMSD 與 RMSF 因此被人為壓低，不能當作結構穩定的證據。",
                            "The backbone was restrained in production. RMSD and RMSF are therefore artificially low and are not evidence of stability.",
                            "本計算でも主鎖を拘束していたため、RMSD と RMSF は人為的に低くなっています。構造が安定している証拠にはなりません。",
                            "본 시뮬레이션에서도 주사슬을 구속했기 때문에 RMSD와 RMSF가 인위적으로 낮습니다. 구조가 안정하다는 증거가 될 수 없습니다."))
    return _section(doc, doc.next(), "md", params, out, findings)


def _sub(doc: Doc, zh: str, en: str, ja: str = "", ko: str = "") -> str:
    return f"<h3>{_esc(doc.t((zh, en, ja, ko)))}</h3>"


def _equil_figures(doc: Doc, wf, cases: dict, runs: dict) -> str:
    """Equilibration quality of every system: minimisation ladder, stage logs with their acceptance checks, overview,
    replica overlay (the same figures as the per-run reports, now in the project report)."""
    from ..project import Run
    out = ""
    for key, c in cases.items():
        r = runs.get(key, {})
        if not r.get("run_ids"):
            continue
        try:
            case = wf.project.case(c["case_id"])
            rdir = Run(case, r["run_ids"][0]).dir
        except Exception:  # noqa: BLE001
            continue
        mn = load_json(rdir / "stages" / "minimize" / "minimize_complete.json", {})
        png = ((mn.get("figures") or {}).get("png"))
        if png:
            out += doc.figure_block(png, "minimization", FT.classify_minimization(mn.get("energies_kj_mol") or [], key), key)
        for stg in ("nvt", "npt", "production"):
            comp = load_json(rdir / "stages" / stg / f"{stg}_complete.json", {})
            png = (comp.get("figures") or {}).get("png")
            rows = [{"stage": stg.upper(), **x} for x in ((comp.get("acceptance") or {}).get("checks") or [])]
            if png:
                out += doc.figure_block(png, "equil_quality", FT.classify_equil(rows, f"{key} {stg.upper()}"), f"{key} {stg.upper()}")
        ov = rdir / "figures" / "run_overview.png"
        if ov.is_file():
            out += doc.figure_block(ov, "equil_quality", [], f"{key} overview")
        rep = next(iter(sorted(case.dir.rglob("production_replicas.png"))), None) if hasattr(case, "dir") else None
        if rep:
            out += doc.figure_block(rep, "replicas", [], key)
    return out


def _md_figures(doc: Doc, sums: dict, metrics: dict, ext: dict | None = None, names: dict | None = None) -> str:
    """Protein stability and dynamics, then ligand binding in dynamics — every analysis that exists for the run."""
    names = names or {}

    def lab(k, rn):
        """D-89: the student's ligand name with the residue name used in the topology, e.g. docked_multi PGA (L01)."""
        u = (names.get(k) or {}).get(rn)
        return f"{k} {u} ({rn})" if u and u != rn else f"{k} {rn}"
    ext = ext or {}
    order = sorted(metrics, key=lambda k: (not k.lower().startswith("apo"), k))
    ref = order[0] if order and order[0].lower().startswith("apo") else None
    out = _sub(doc, "蛋白的穩定性與動態", "Protein stability and dynamics", "タンパク質の安定性と動き", "단백질의 안정성과 동역학")
    rmsd = {k: (metrics[k].get("time_ns") or [], metrics[k].get("rmsd_backbone_A") or []) for k in order if metrics[k].get("rmsd_backbone_A")}
    if rmsd:
        out += doc.figure_block(FG.timeseries(rmsd, "Backbone RMSD (Å)", doc.figdir / "md_rmsd.png"), "rmsd", FT.classify_rmsd(rmsd))
    rg = {k: (metrics[k].get("time_ns") or [], metrics[k].get("rg_protein_A") or []) for k in order if metrics[k].get("rg_protein_A")}
    if rg:
        out += doc.figure_block(FG.timeseries(rg, "Radius of gyration (Å)", doc.figdir / "md_rg.png"), "rg", FT.classify_rg(rg))
    sasa = {k: (ext[k].get("time_ns") or [], (ext[k].get("sasa_protein") or {}).get("total_A2") or []) for k in order if (ext.get(k) or {}).get("sasa_protein")}
    if sasa:
        ff = [x for k, (t, y) in sasa.items() for x in FT.classify_growth(k, y, ("溶劑可及面積", "solvent-accessible area", "溶媒接触表面積", "용매 접근 면적"))]
        out += doc.figure_block(FG.timeseries(sasa, "Protein SASA (Å²)", doc.figdir / "md_sasa.png"), "protein_sasa", ff)
    hbp = {k: ((ext[k].get("hbonds_protein") or {}).get("time_ns") or [], (ext[k].get("hbonds_protein") or {}).get("count") or [])
           for k in order if ((ext.get(k) or {}).get("hbonds_protein") or {}).get("count")}      # D-121: unavailable → no line
    if hbp:
        ff = [x for k, (t, y) in hbp.items() for x in FT.classify_growth(k, y, ("內部氫鍵數", "internal hydrogen bonds", "内部水素結合の数", "내부 수소 결합 수"))]
        out += doc.figure_block(FG.timeseries(hbp, "Protein hydrogen bonds", doc.figdir / "md_hbond_protein.png"), "hbond_protein", ff)
    for k in order:
        d = (ext.get(k) or {}).get("dssp")
        if d and d.get("fraction"):
            out += doc.figure_block(FG.dssp_area(ext[k].get("time_ns") or [], d["fraction"], doc.figdir / f"md_dssp_{k}.png"),
                                    "dssp", FT.classify_dssp(k, d["fraction"]), k)
    rf = {k: (metrics[k].get("rmsf_residues") or [], metrics[k].get("rmsf_ca_A") or []) for k in order if metrics[k].get("rmsf_ca_A")}
    if rf:
        keys = list(rf)
        ff = [x for k in keys[1:] for x in FT.classify_rmsf(rf[k][0], rf[keys[0]][1], rf[k][1], k)]
        out += doc.figure_block(FG.rmsf(rf, doc.figdir / "md_rmsf.png"), "rmsf", ff)
    for k in order:
        d = (ext.get(k) or {}).get("dccm")
        if d and d.get("matrix"):
            refm = ((ext.get(ref) or {}).get("dccm") or {}).get("matrix") if ref and k != ref else None
            out += doc.figure_block(FG.heatmap(d["matrix"], doc.figdir / f"md_dccm_{k}.png", label="Correlation", ticks=d.get("residues"),
                                               xlabel="Residue", ylabel="Residue"), "dccm", FT.classify_dccm(k, d["matrix"], refm), k)
    for k in order:
        pc = (ext.get(k) or {}).get("pca")
        if pc and pc.get("landscape"):
            out += doc.figure_block(FG.landscape(pc["landscape"], pc.get("explained"), doc.figdir / f"md_pca_{k}.png"),
                                    "pca_landscape", FT.classify_pca(k, pc), k)
    for k in order:
        cl = (ext.get(k) or {}).get("clusters")
        if cl and cl.get("populations"):
            out += doc.figure_block(FG.clusters_plot(cl, ext[k].get("time_ns") or [], doc.figdir / f"md_clusters_{k}.png"),
                                    "clusters", FT.classify_clusters(k, cl), k)
    out += _toolbox_section(doc, ext, order)                 # D-105: tICA, Markov model, H-bond network
    # ---- ligand binding in dynamics
    lig_keys = [(k, rn) for k in order for rn in (metrics[k].get("ligands") or {})]
    if not lig_keys:
        return out
    out += _sub(doc, "配體在模擬中的結合", "Ligand binding during the simulation", "シミュレーション中のリガンドの結合", "시뮬레이션 중 리간드 결합")
    lig, lf = {}, []
    for k, rn in lig_keys:
        d = metrics[k]["ligands"][rn]
        if d.get("rmsd_in_pocket_A"):
            lig[lab(k, rn)] = (metrics[k].get("time_ns") or [], d["rmsd_in_pocket_A"])
            lf += FT.classify_ligand_rmsd(k, rn, metrics[k].get("time_ns") or np.arange(len(d["rmsd_in_pocket_A"])), d["rmsd_in_pocket_A"])
    if lig:
        out += doc.figure_block(FG.timeseries(lig, "Ligand RMSD in pocket (Å)", doc.figdir / "md_ligand_rmsd.png", threshold=3.0), "ligand_rmsd", lf)
    for k, rn in lig_keys:
        d = metrics[k]["ligands"][rn]
        if d.get("com_distance_to_pocket_A"):
            out += doc.figure_block(FG.two_panel(metrics[k].get("time_ns") or [], d["com_distance_to_pocket_A"], d.get("polar_contacts") or [],
                                                 "COM distance (Å)", "Polar contacts", doc.figdir / f"md_com_{k}_{rn}.png"),
                                    "com_distance", FT.classify_com(lab(k, rn), metrics[k].get("time_ns"), d["com_distance_to_pocket_A"]), lab(k, rn))
    for k in order:                                     # D-60: multi-ligand systems — does co-occupancy hold?
        lld = metrics[k].get("ligand_ligand_distance_A") or {}
        if lld:
            ser = {f"{k} {pair}": (metrics[k].get("time_ns") or [], y) for pair, y in lld.items()}
            out += doc.figure_block(FG.timeseries(ser, "Ligand–ligand distance (Å)", doc.figdir / f"md_ll_{k}.png"), "ll_distance",
                                    DF.classify_ll_distance({pair: (metrics[k].get("time_ns") or [], y) for pair, y in lld.items()},
                                                            restrained=k.startswith("docked_multi")), k)
    bur, bf = {}, []
    for k, rn in lig_keys:
        L = ((ext.get(k) or {}).get("ligands") or {}).get(rn) or {}
        if (L.get("sasa") or {}).get("buried_fraction"):
            bur[lab(k, rn)] = (ext[k].get("time_ns") or [], L["sasa"]["buried_fraction"])
            bf += FT.classify_burial(lab(k, rn), L["sasa"]["buried_fraction"])
    if bur:
        out += doc.figure_block(FG.timeseries(bur, "Buried fraction of ligand surface", doc.figdir / "md_burial.png"), "ligand_burial", bf)
    for k, rn in lig_keys:
        fq = metrics[k]["ligands"][rn].get("contact_frequency") or {}
        if fq:
            out += doc.figure_block(FG.contacts(fq, doc.figdir / f"md_contacts_{k}_{rn}.png"), "contacts", FT.classify_contacts(k, rn, fq), lab(k, rn))
    hb, hf = {}, []
    for k, rn in lig_keys:
        L = ((ext.get(k) or {}).get("ligands") or {}).get(rn) or {}
        if (L.get("hbonds") or {}).get("count") is not None:
            hb[lab(k, rn)] = (ext[k].get("time_ns") or [], L["hbonds"]["count"])
    if hb:
        out += doc.figure_block(FG.timeseries(hb, "Ligand–protein hydrogen bonds", doc.figdir / "md_hbond_count.png"), "hbond_count", FT.classify_hbond_count(hb))
    out += _hydration_tables(doc, ext, lig_keys, lab)          # D-105
    for k, rn in lig_keys:
        L = ((ext.get(k) or {}).get("ligands") or {}).get(rn) or {}
        if L.get("hbonds"):
            out += doc.figure_block(FG.bars(L["hbonds"].get("occupancy") or [], "Occupancy", doc.figdir / f"md_hbond_occ_{k}_{rn}.png"),
                                    "hbond_occupancy", FT.classify_hbond_occupancy(lab(k, rn), L["hbonds"].get("occupancy") or []), lab(k, rn))
        if (L.get("fingerprint") or {}).get("residues"):
            out += doc.figure_block(FG.fingerprint_plot(L["fingerprint"], ext[k].get("time_ns") or [], doc.figdir / f"md_fp_{k}_{rn}.png"),
                                    "fingerprint", FT.classify_fingerprint(lab(k, rn), L["fingerprint"].get("occupancy") or {}), lab(k, rn))
            out += _persistence_html(doc, lab(k, rn), L["fingerprint"])
    wb, wf_ = {}, []
    for k, rn in lig_keys:            # D-97: missing solvent is "unavailable", not an empty or zero chart
        w_ = ((ext.get(k) or {}).get("ligands") or {}).get(rn, {}).get("water_bridges") or {}
        if w_.get("status") in ("unavailable", "not_applicable"):
            out += (f"<p class=muted>{_esc(lab(k, rn))}{colon(doc.lang)}"
                    f"{_esc(tx(('水橋分析無法進行', 'water-bridge analysis unavailable', '水橋の解析はできません', '물 다리 분석 불가'), doc.lang))}"
                    f"{paren(_esc(w_.get('reason', '')), doc.lang)}</p>")
    for k, rn in lig_keys:
        L = ((ext.get(k) or {}).get("ligands") or {}).get(rn) or {}
        if (L.get("water_bridges") or {}).get("count") is not None:
            wb[lab(k, rn)] = (ext[k].get("time_ns") or [], L["water_bridges"]["count"])
            wf_ += FT.classify_water(lab(k, rn), L["water_bridges"])
    if wb:
        out += doc.figure_block(FG.timeseries(wb, "Water bridges", doc.figdir / "md_water.png"), "water_bridges", wf_)
    return out


_CTX_TEXT = {"single": ("單獨結合", "Alone", "単独", "단독"),
             "multi": ("與其他配體共存", "With the other ligands", "ほかのリガンドと共存", "다른 리간드와 공존")}


def _binding(doc: Doc, wf, vals, f, goal) -> str:
    doc.section = tx(SECTION["binding"]["title"], doc.lang)
    L = doc.lang
    b = (wf.state()["steps"].get("binding") or {}).get("results", {})
    if not wf.cfg.get("binding", {}).get("enabled") and not b:
        return ""
    rows = [r for r in advisor.parameter_table(vals, f, goal, L) if r["group_key"] == "binding" and r["key"] != "binding"]
    params = _param_table(doc, rows, ("結合自由能參數", "Binding free-energy parameters", "結合自由エネルギーのパラメータ", "결합 자유 에너지 매개변수"))
    if not b:
        return _section(doc, doc.next(), "binding", params, "", [])
    pm = lambda v, e: "—" if v is None else (f"{v:.1f} ± {e:.1f}" if e is not None else f"{v:.1f}")  # noqa: E731
    trs = [[_esc(n), pm(r.get("delta_pmf_kj_mol"), r.get("delta_pmf_err_kj_mol")),
            pm(r.get("dG_standard_kj_mol"), r.get("dG_err_kj_mol")) if r.get("dG_standard_kj_mol") is not None else tx(("不輸出", "not reported", "出力しない", "출력 안 함"), L),
            _fmt(r.get("dG_standard_kcal_mol"), 1) if r.get("dG_standard_kcal_mol") is not None else "—",
            _fmt(r.get("r_min_nm"), 3), _fmt(r.get("max_force"), 0), _fmt(r.get("work"), 1),
            _esc(tx(_CTX_TEXT["multi" if str(r.get("context", "")).startswith("multi") else "single"], L)),
            str(r.get("replicas") or 1)] for n, r in b.items() if r.get("status", "PASS") == "PASS"]
    out = doc.table([tx(("配體", "Ligand", "リガンド", "리간드"), L), "ΔPMF (kJ mol⁻¹)", "ΔG° (kJ mol⁻¹)", "ΔG° (kcal mol⁻¹)",
                     tx(("結合距離（nm）", "Bound distance (nm)", "結合距離（nm）", "결합 거리 (nm)"), L),
                     tx(("SMD 最大拉力（kJ mol⁻¹ nm⁻¹）", "SMD peak force (kJ mol⁻¹ nm⁻¹)", "SMD の最大の力（kJ mol⁻¹ nm⁻¹）", "SMD 최대 힘 (kJ mol⁻¹ nm⁻¹)"), L),
                     tx(("SMD 功（kJ mol⁻¹）", "SMD work (kJ mol⁻¹)", "SMD の仕事（kJ mol⁻¹）", "SMD 일 (kJ mol⁻¹)"), L),
                     tx(("情境", "Context", "状況", "상황"), L), tx(("SMD 次數", "SMD runs", "SMD の回数", "SMD 횟수"), L)],
                    trs, ("結合自由能結果", "Binding free-energy results", "結合自由エネルギーの結果", "결합 자유 에너지 결과"), {1, 2, 3, 4, 5, 6, 8})
    start = len(doc.collected)
    for name, r in b.items():
        if r.get("status", "PASS") != "PASS":
            continue
        out += f"<h3>{_esc(name)}</h3>"
        per = r.get("per_replica") or []
        if len(per) > 1:          # D-87: every SMD/umbrella run of this target, then the combined value above
            prs = [[str(i + 1), pm(p_.get("delta_pmf_kj_mol"), p_.get("delta_pmf_err_kj_mol")),
                    pm(p_.get("dG_standard_kj_mol"), p_.get("dG_err_kj_mol")) if p_.get("dG_standard_kj_mol") is not None else "—"]
                   for i, p_ in enumerate(per)]
            out += doc.table([tx(("第幾次", "Run", "回", "회차"), L), "ΔPMF (kJ mol⁻¹)", "ΔG° (kJ mol⁻¹)"], prs,
                             ("各次 SMD＋傘狀採樣", "Each SMD and umbrella-sampling run", "各回の SMD と傘サンプリング",
                              "각 회차의 SMD와 우산 샘플링"), {1, 2})
            # D-96 (A9): say how many distinct MD starting points there really were; reuse the aggregation sentence
            prs_md = [str(p_.get("md_run_id") or "?") for p_ in per]
            out += "<p>" + _esc(tx(tuple(r["replicas_why_i18n"]) if isinstance(r.get("replicas_why_i18n"), (list, tuple)) and len(r["replicas_why_i18n"]) == 4 else (
                f"上表 {len(per)} 次拉離的 MD 起點：{'、'.join(prs_md)}。共用同一個起點的拉離只換亂數種子，不是獨立的平衡起點。",
                f"MD starting points of the {len(per)} pulls above: {', '.join(prs_md)}. Pulls that share a starting point "
                "differ only in the random seed and are not independent equilibrium starts.",
                f"上の {len(per)} 回の引き離しの MD 出発点：{'、'.join(prs_md)}。同じ出発点を共有する引き離しは乱数シードだけが異なり、独立した平衡の出発点ではありません。",
                f"위 {len(per)}회 당김의 MD 시작점: {', '.join(prs_md)}. 같은 시작점을 공유하는 당김은 난수 시드만 다르며 독립적인 평형 시작점이 아닙니다."), L)) + "</p>"
        out += _binding_figures(doc, name, r)
        if r.get("dG_withheld"):
            out += (f"<p class=warn>{_esc(tx(('ΔG° 不輸出的原因', 'Why ΔG° is not reported', 'ΔG° を出力しない理由', 'ΔG°를 출력하지 않는 이유'), L))}"
                    f"{colon(L)}{_esc(str(r['dG_withheld']))}</p>")
    comp = (wf.state()["steps"].get("binding") or {}).get("comparison") or {}
    out += _comparison_html(comp, L)
    out += _cooperativity_html(doc, comp.get("cooperativity") or [], b)
    # the profile itself is described under its figure; here the reported numbers and the convergence check
    b_asm = {k: ({**v, "assessment": _assessment_for(v)} if v.get("status", "PASS") == "PASS" else v) for k, v in b.items()}
    findings = doc.collected[start:] + [x for x in I.binding(b_asm) if "ΔG°" in x["text"][1] or "halves" in x["text"][1]
                                         or "assessment" in x["text"][1] or "diagnostics disagree" in x["text"][1]]
    for ctx, c in (comp.get("contexts") or {}).items():
        if c.get("status") in ("PASS", "PATH_SPECIFIC", "DESCRIPTIVE", "INSUFFICIENT") and c.get("why"):
            w = tuple(c.get("why_i18n") or (c["why"],) * 4)
            findings.append(I.F("note", *w))
    return _section(doc, doc.next(), "binding", params, out, findings)


def _binding_manifest_pmf(r: dict) -> dict:
    figs = r.get("figures") or {}
    anchor = next((figs[k]["png"] for k in ("pmf", "smd", "histograms", "umbrella_coverage") if (figs.get(k) or {}).get("png")), None)
    bdir = Path(anchor).parent if anchor else None
    return ((load_json(bdir / "binding_manifest.json", {}) if bdir else {}).get("result") or {}).get("pmf") or {}


def _assessment_for(r: dict) -> dict | None:
    """D-96: the ONE assessment every caption, summary and table of a binding result reads — the stored one, else
    re-assessed from the stored PMF fields (a report rebuild, no MD); missing fields stay unknown, so legacy data
    come out as not qualified.  None when nothing at all is stored."""
    if r.get("assessment"):
        return r["assessment"]
    pm = _binding_manifest_pmf(r)
    if not pm:
        return None
    from ..sampling.assessment import assess_pmf
    a = assess_pmf(pm, dG_withheld=r.get("dG_withheld"), has_dG=r.get("dG_standard_kj_mol") is not None)
    a["reassessed_from_manifest"] = True
    return a


def _binding_figures(doc: Doc, name: str, r: dict) -> str:
    """F8–F10 from the binding output folder (smd.tsv, binding_manifest.json); falls back to the stored images."""
    figs = r.get("figures") or {}
    anchor = next((figs[k]["png"] for k in ("pmf", "smd", "histograms") if figs.get(k)), None)
    bdir = Path(anchor).parent if anchor else None
    out = ""
    arr = None
    if bdir and (bdir / "smd.tsv").is_file():
        try:
            arr = np.loadtxt(bdir / "smd.tsv", ndmin=2)
        except Exception:  # noqa: BLE001
            arr = None
    if arr is not None and arr.shape[0] >= 10 and arr.shape[1] >= 5:
        pos, force, work = arr[:, 1], arr[:, 3], arr[:, 4]
        out += doc.figure_block(FG.smd(pos, force, work, doc.figdir / f"smd_{name}.png"), "smd", FT.classify_smd(pos, force, work, name), name)
    elif figs.get("smd"):
        out += doc.figure_block(figs["smd"]["png"], "smd", [], name)
    out += _smd_contacts_html(doc, name, r, bdir)
    pm = ((load_json(bdir / "binding_manifest.json", {}) if bdir else {}).get("result") or {}).get("pmf") or {}
    # D-96: every caption reads ONE assessment — the stored one, else re-assessed from the stored PMF fields (a report
    # rebuild, no MD); missing fields stay unknown, so legacy data come out as "awaiting reanalysis"
    asm = _assessment_for(r)
    # D-101: the coverage figure (written after every window, breaks red / alerts orange) is preferred; it exists even
    # when the run stopped before the PMF
    cov_fig = figs.get("umbrella_coverage") or (({"png": str(bdir / "umbrella_coverage.png")}
                                                  if bdir and (bdir / "umbrella_coverage.png").is_file() else None))
    if cov_fig and cov_fig.get("png"):
        out += doc.figure_block(cov_fig["png"], "umbrella", FT.classify_umbrella(pm.get("coverage") or {}, name, asm), name)
    elif figs.get("histograms"):
        out += doc.figure_block(figs["histograms"]["png"], "umbrella", FT.classify_umbrella(pm.get("coverage") or {}, name, asm), name)
    if (pm.get("overlap_matrix") or {}).get("matrix"):
        o = pm["overlap_matrix"]
        out += doc.figure_block(FG.heatmap(o["matrix"], doc.figdir / f"overlap_{name}.png", cmap="Blues", vmin=0, vmax=1, label="Overlap",
                                           ticks=[f"{c:.2f}" for c in o.get("centers") or []], xlabel="Window centre (nm)", ylabel="Window centre (nm)"),
                                "overlap_matrix", FT.classify_overlap(name, o, asm), name)
    if pm.get("convergence"):
        out += doc.figure_block(FG.pmf_convergence(pm["convergence"], doc.figdir / f"pmf_conv_{name}.png"), "pmf_convergence",
                                FT.classify_convergence(name, pm["convergence"], asm), name)
    if pm.get("grid_nm") and pm.get("pmf_radial_kj_mol"):
        g, W = pm["grid_nm"], pm["pmf_radial_kj_mol"]
        err = pm.get("err_kj_mol")
        out += doc.figure_block(FG.pmf(g, W, err, doc.figdir / f"pmf_{name}.png"), "pmf",
                                FT.classify_pmf(g, W, err, name) + FT.classify_assessment(name, asm), name)
    elif figs.get("pmf"):
        out += doc.figure_block(figs["pmf"]["png"], "pmf", [], name)
    return out


def _smd_contacts_for(r: dict, bdir) -> dict:
    """D-116: the stored contact-release result of a pull (manifest), else computed from the pull's files, else
    "unavailable".  Never inferred from the force curve."""
    if not bdir:
        return {}
    sc = ((load_json(bdir / "binding_manifest.json", {}).get("result") or {}).get("smd_contacts")) or load_json(bdir / "smd_contacts.json", {})
    if sc:
        return sc
    if (bdir / "smd.tsv").is_file():
        from ..analysis import smd_contacts as SC
        return SC.from_files(bdir)
    return {}


def _smd_contacts_html(doc: Doc, name: str, r: dict, bdir) -> str:
    """D-116 (F13): contact-release figure and the table of contacts released at the force peak; a pull without the
    stored path says so instead of leaving the section silent."""
    L = doc.lang
    sc = _smd_contacts_for(r, bdir)
    if not sc:
        return ""
    if sc.get("status") not in ("ok", "limited"):
        txt = FT.SMD_CONTACTS_UNAVAILABLE.get(sc.get("reason_code") or "no_path_file") or FT.SMD_CONTACTS_UNAVAILABLE["no_path_file"]
        return f"<p class=muted>{_esc(name)}{colon(L)}{_esc(tx(txt, L))}</p>"
    out = doc.figure_block(FG.smd_contacts_map(sc, doc.figdir / f"smd_contacts_{name}.png"), "smd_contacts",
                           FT.classify_smd_contacts(name, sc), name)
    rows = []
    for c in sc.get("contacts") or []:
        if c.get("category") != "at_peak":
            continue
        rows.append([_esc(c.get("label", c["residue"])), f"{c['release_d_nm']:.3f}", f"{c['offset_from_peak_nm']:+.3f}",
                     _esc(tx(("是", "yes", "はい", "예") if c.get("initial") else ("否", "no", "いいえ", "아니오"), L)),
                     _esc(str(c.get("closest_pair_at_first", "")))])
    if rows:
        out += doc.table([tx(("殘基", "Residue", "残基", "잔기"), L),
                          tx(("最後一次接觸的距離 d (nm)", "Distance d at the last contact (nm)", "最後に接触していた距離 d (nm)", "마지막 접촉 때의 거리 d (nm)"), L),
                          tx(("與力峰值的差 (nm)", "Offset from the force peak (nm)", "力のピークとの差 (nm)", "힘 피크와의 차이 (nm)"), L),
                          tx(("起始就有", "Present at the start", "開始時からある", "처음부터 있음"), L),
                          tx(("最先看到時最近的原子對（配體 - 殘基）", "Closest atom pair when first seen (ligand - residue)",
                              "最初に見えたときに最も近い原子対（リガンド - 残基）", "처음 보였을 때 가장 가까운 원자쌍(리간드 - 잔기)"), L)],
                         rows, (f"{name}：在力峰值前後 {sc.get('peak_window_nm', 0.05):g} nm 內斷開的接觸",
                                f"{name}: contacts released within {sc.get('peak_window_nm', 0.05):g} nm of the force peak",
                                f"{name}：力のピークの前後 {sc.get('peak_window_nm', 0.05):g} nm 以内に切れた接触",
                                f"{name}: 힘 피크 앞뒤 {sc.get('peak_window_nm', 0.05):g} nm 안에서 끊어진 접촉"), {1, 2})
    return out


def _cooperativity_html(doc: Doc, coop: list, b: dict) -> str:
    """D-61: thermodynamic cycle per shared pocket — closure first, then cooperativity."""
    L = doc.lang
    out = ""
    for c in coop:
        if c.get("status") == "INSUFFICIENT":
            out += f"<p class=muted>{_esc(tx(tuple(c['why']) if isinstance(c['why'], list) else c['why'], L))}</p>"
            continue
        use_dG = c.get("quantity", "").startswith("ΔΔG")
        rows = []
        for n in c.get("ligands") or []:
            r_with, r_alone = b.get(f"multi:{n}") or {}, b.get(n) or {}
            if use_dG:
                w, a = (r_with.get("dG_standard_kj_mol"), r_with.get("dG_err_kj_mol")), (r_alone.get("dG_standard_kj_mol"), r_alone.get("dG_err_kj_mol"))
            else:
                w = (-(r_with.get("delta_pmf_kj_mol") or 0), r_with.get("delta_pmf_err_kj_mol"))
                a = (-(r_alone.get("delta_pmf_kj_mol") or 0), r_alone.get("delta_pmf_err_kj_mol"))
            rows.append({"ligand": n, "alone": a, "with": w})
        out += _sub(doc, "配體之間的協同作用", "Cooperativity between the ligands", "リガンド間の協同性", "리간드 간 협동성")
        out += doc.figure_block(FG.cooperativity_plot(rows, "ΔG° (kJ mol⁻¹)" if use_dG else "−ΔPMF (kJ mol⁻¹)",
                                                      doc.figdir / f"cooperativity_{c['context'].replace(':', '_')}.png"),
                                "cooperativity", FT.classify_cooperativity(c), c["context"])
        if c.get("closure_kj_mol") is not None:
            shift = tx(("另一配體存在時的變化", "shift with the partner bound", "相手のリガンドがあるときの変化", "상대 리간드가 있을 때의 변화"), L)
            out += doc.table([tx(("量", "Quantity", "量", "양"), L), tx(("數值（kJ mol⁻¹）", "Value (kJ mol⁻¹)", "値（kJ mol⁻¹）", "값 (kJ mol⁻¹)"), L), "σ"],
                             [[_esc(tx(("協同 ΔΔG_coop（兩條路徑的平均）", "Cooperativity ΔΔG_coop (mean of the two legs)",
                                        "協同性 ΔΔG_coop（2 つの経路の平均）", "협동성 ΔΔG_coop (두 경로의 평균)"), L)),
                               f"{c['coop_kj_mol']:+.2f}", _fmt(c.get("coop_err_kj_mol"))],
                              [_esc(tx(("循環閉合誤差（兩條路徑的差）", "Cycle closure error (difference of the two legs)",
                                        "サイクルの閉合誤差（2 つの経路の差）", "순환 닫힘 오차 (두 경로의 차이)"), L)),
                               f"{c['closure_kj_mol']:+.2f}", _fmt(c.get("closure_sigma"))]]
                             + [[_esc(f"{n}{colon(L)}{shift}"), f"{v['value']:+.2f}", _fmt(v.get("err"))]
                                for n, v in (c.get("shifts") or {}).items()],
                             ("協同自由能與循環閉合", "Cooperativity and cycle closure", "協同自由エネルギーとサイクルの閉合", "협동 자유 에너지와 순환 닫힘"), {1, 2})
    return out


def _persistence_html(doc, name: str, fp: dict) -> str:
    """F09/F07 (D-97): residue-level interaction persistence from the stored frames, with censoring and the reason
    when no lifetime is identifiable; initial contacts kept vs contacts formed later."""
    L = doc.lang
    per = (fp.get("persistence") or {})
    out = ""
    ivn = fp.get("initial_vs_new") or {}
    if ivn.get("initial") is not None:
        disp = fp.get("display_labels") or {}
        new = ", ".join(disp.get(r, r) for r in ivn.get("new") or []) or "—"
        out += "<p>" + _esc(tx((f"{name}：起始幀接觸 {len(ivn['initial'])} 個殘基；之後才形成接觸的殘基：{new}。失去起始對接接觸本身不代表姿勢變差。",
                                f"{name}: {len(ivn['initial'])} residues in contact in the first frame; residues that only come into "
                                f"contact later: {new}. Losing an initial docking contact does not by itself make a pose worse.",
                                f"{name}：最初のフレームで接触している残基は {len(ivn['initial'])} 個、後から接触した残基：{new}。最初のドッキングの接触を失うこと"
                                "自体はポーズが悪くなったことを意味しません。",
                                f"{name}: 첫 프레임에서 접촉한 잔기 {len(ivn['initial'])}개, 나중에 접촉한 잔기: {new}. 처음 도킹 접촉을 잃는 것 자체가 "
                                "포즈가 나빠졌다는 뜻은 아닙니다."), L)) + "</p>"
    items = per.get("items") or []
    if per.get("status") != "computed" or not items:
        return out
    disp = fp.get("display_labels") or {}
    from .figures import FP_NAMES
    rows = []
    for it in items:
        lt = f"{it['lifetime_ps']:.0f} ps" if it.get("lifetime_ps") is not None else (it.get("lifetime_reason") or "—")
        rows.append([_esc(disp.get(it["residue"], it["residue"])), _esc(FP_NAMES.get(it["label"], it["label"])),
                     f"{(it.get('occupancy_time_weighted') or 0):.0%}", str(it["n_events"]),
                     str(it.get("n_left_censored_excluded", 0)), _esc(lt), _esc("; ".join(it.get("limitations") or []) or "—")])
    out += doc.table([tx(("殘基", "Residue", "残基", "잔기"), L), tx(("互作", "Interaction", "相互作用", "상호작용"), L),
                      tx(("時間加權佔有率", "Time-weighted occupancy", "時間加重占有率", "시간 가중 점유율"), L),
                      tx(("事件數", "Events", "イベント数", "사건 수"), L),
                      tx(("起點即存在（排除）", "Present at start (excluded)", "開始時から存在（除外）", "시작부터 존재(제외)"), L),
                      tx(("持續時間（1/e）", "Persistence (1/e)", "持続時間（1/e）", "지속 시간(1/e)"), L),
                      tx(("限制", "Limitations", "制約", "제약"), L)], rows,
                     (f"{name}：互作持續性（連續定義、儲存幀；不是配體滯留時間或 k_off）",
                      f"{name}: interaction persistence (continuous definition, stored frames; not ligand residence time or k_off)",
                      f"{name}：相互作用の持続性（連続の定義、保存フレーム。リガンド滞留時間や k_off ではない）",
                      f"{name}: 상호작용 지속성(연속 정의, 저장 프레임. 리간드 체류 시간이나 k_off가 아님)"), {2, 3, 4})
    return out


def _state_word(v: dict, L: str) -> str:
    """D-97 (A4): one word for the ligand-state table from `ligand_state`, never from RMSD alone."""
    ft = ((v.get("state") or {}).get("fraction_final_20pct")) or {}
    fa = ((v.get("state") or {}).get("fraction_all")) or {}
    if not ft:
        return tx(("狀態未記錄（只有 RMSD）", "state not recorded (RMSD only)", "状態の記録なし（RMSD のみ）", "상태 기록 없음(RMSD만)"), L)
    if (fa.get("escape_evidence") or 0) > 0:
        return tx(("有離開證據", "escape evidence", "離脱の証拠あり", "이탈 증거 있음"), L)
    k = max(ft, key=lambda x: ft[x])
    return tx({"pose_retained": ("維持姿勢", "pose retained", "ポーズ維持", "포즈 유지"),
               "pose_changed_in_pocket": ("姿勢改變、仍在口袋", "pose changed, in pocket", "ポーズ変化・ポケット内", "포즈 변화, 포켓 안"),
               "unknown": ("不明確", "unclear", "不明確", "불분명")}.get(k, (k,) * 4), L)


def key_findings(pool: list[dict], limit: int = 10) -> list[dict]:
    """D-96 (A10): de-duplicated key findings.  Every caution is kept whatever its position in the pool (a serious PMF
    problem found late must not be cut by early repeated warnings); good and note findings fill up to `limit`."""
    seen, cau, rest = set(), [], []
    for f_ in pool:
        t = tuple(f_["text"]) if isinstance(f_.get("text"), (list, tuple)) else f_.get("text")
        if t in seen:
            continue
        seen.add(t)
        (cau if f_.get("level") in ("caution", "warn") else rest).append(f_)
    rest = [x for x in rest if x.get("level") == "good"] + [x for x in rest if x.get("level") != "good"]
    return cau + rest[:max(0, limit - len(cau))]


def _ml(d: dict, key: str, lang: str) -> str:
    """A field recorded by sampling.multi in Chinese, in the report language when its 4-language twin exists (D-74)."""
    v = d.get(key + "_i18n")
    return tx(tuple(v), lang) if isinstance(v, (list, tuple)) and len(v) == 4 else str(d.get(key, ""))


def _comparison_html(comp: dict, lang: str = "zh") -> str:
    """WP9: ΔΔ ranking per context and co-occupancy shifts."""
    if not comp or not (comp.get("contexts") or comp.get("co_occupancy")):
        return ""
    L = lang
    t = lambda *x: pick(x, L)  # noqa: E731
    parts = ["<h3>" + t("配體間比較（ΔΔ）", "Comparison between ligands (ΔΔ)", "リガンド間の比較（ΔΔ）", "리간드 간 비교 (ΔΔ)") + "</h3>"]
    for ctx, c in comp.get("contexts", {}).items():
        if ctx == "single":
            label = t("各配體單獨結合", "Each ligand bound alone", "各リガンドが単独で結合", "각 리간드 단독 결합")
        else:
            pk = _esc(ctx.split(":", 1)[1])
            label = t(f"共同口袋（{pk}）", f"Shared pocket ({pk})", f"共通ポケット（{pk}）", f"공유 포켓 ({pk})")
        nc = c.get("not_compared") or []
        nc_html = ("<ul class=muted>" + "".join(
            f"<li>{_esc(x['key'])}{colon(L)}{_esc(t('未納入比較', 'not compared', '比較に含めない', '비교에서 제외'))}"
            f"{paren(_esc(x['why']), L)}</li>" for x in nc) + "</ul>") if nc else ""
        if c.get("status") == "DESCRIPTIVE":       # D-96: shared-pocket pulls are condition-specific values, never ranked
            parts.append(f"<p><b>{label}</b>{colon(L)}{_esc(_ml(c, 'why', L))}</p><ul>" + "".join(
                f"<li>{_esc(v['key'])}{colon(L)}ΔPMF {v['delta_pmf_kj_mol']:.2f}"
                + ("" if v.get("err") is None else f" ± {v['err']}") + " kJ/mol"
                + ("" if v.get("qualified") else paren(_esc(t('僅診斷，未通過取樣評估', 'diagnostic only, sampling assessment not passed',
                                                            '診断のみ、取得評価は不合格', '진단용, 샘플링 평가 미통과')), L))
                + "</li>" for v in c.get("values") or []) + "</ul>" + nc_html)
            continue
        if c.get("status") not in ("PASS", "PATH_SPECIFIC"):
            parts.append(f"<p class=muted>{label}{colon(L)}{_esc(_ml(c, 'why', L))}</p>" + nc_html)
            continue
        parts.append(f"<p><b>{label}</b>{colon(L)}{_esc(_ml(c, 'why', L))}</p><table><tr><th>{t('配體', 'Ligand', 'リガンド', '리간드')}</th>"
                     f"<th class=num>{_esc(c['quantity'])} ({_esc(c['unit'])})</th><th class=num>σ</th>"
                     f"<th>{t('判定', 'Verdict', '判定', '판정')}</th></tr>")
        for r in c["rows"]:
            parts.append(f"<tr><td>{_esc(r['key'])}</td><td class=num>{r['delta']:+.2f}</td><td class=num>{'—' if r['sigma'] is None else r['sigma']}</td>"
                         f"<td>{_esc(_ml(r, 'verdict', L))}</td></tr>")
        parts.append("</table>" + nc_html)
    if comp.get("co_occupancy"):
        parts.append("<p><b>" + t("共存效應", "Co-occupancy effect", "共存の効果", "공존 효과") + "</b>"
                     + paren(t("共同口袋減去單獨結合", "shared pocket minus alone", "共通ポケットから単独結合を引いた値", "공유 포켓에서 단독 결합을 뺀 값"), L)
                     + "</p><ul>" + "".join(f"<li>{_esc(_ml(c, 'why', L))}</li>" for c in comp["co_occupancy"]) + "</ul>")
    parts.append("<ul class=muted>" + "".join(f"<li>{_esc(tx(tuple(n), L) if isinstance(n, (list, tuple)) else n)}</li>" for n in (comp.get("notes_i18n") or comp.get("notes", []))) + "</ul>")
    return "".join(parts)


def _binding_section(wf, lang: str = "zh") -> str:
    """Binding section on its own (kept for callers and tests)."""
    doc = Doc(lang, wf.dir / "report_figures")
    doc.user_keys = set(advisor.values_from_config(wf.cfg))
    n = {"i": 0}
    doc.next = lambda: n.__setitem__("i", n["i"] + 1) or n["i"]
    vals = actual_values(wf)
    return _binding(doc, wf, vals, advisor.features_from_config(wf.cfg), wf.cfg.get("goal") or "binding")


# ------------------------------------------------------------------------------------------- methods and limitations
def methods_text(wf, vals: dict, lang: str) -> str:
    cfg = wf.cfg
    rec = cfg.get("receptor") or {}
    rid = rec.get("pdb_id") or Path(str(rec.get("file", "the supplied structure"))).name
    ligs = cfg.get("ligands") or []
    peps = [l for l in ligs if l.get("sequence")]
    small = len(peps) < len(ligs)
    sim = vals.get("docking_mode") == "simultaneous"
    hmr = vals.get("timestep_fs", 2) > 2
    box = {"dodecahedron": ("菱形十二面體", "rhombic dodecahedral", "菱形十二面体", "마름모십이면체"),
           "cube": ("立方體", "cubic", "立方体", "정육면체")}.get(vals.get("box_shape"), ("", "", "", ""))
    salt = f"{vals.get('ion_positive', 'Na+')[:-1]}{vals.get('ion_negative', 'Cl-')[:-1]}"
    ph = cfg.get("ph", 7.4)
    v = vals.get
    lg = norm(lang)
    if lg == "zh":
        s = [f"受體結構（{rid}）以 PDBFixer 移除結晶添加物與水、補齊缺失的重原子，並於 pH {ph} 加氫。"]
        if ligs:
            s.append(f"{len(ligs)} 個配體以 AutoDock Vina {'同時' if sim else '分別'}對接（搜尋強度 {v('exhaustiveness')}，每個配體保留 {v('n_poses')} 個姿勢），"
                     "再依分數、叢集大小與接觸殘基選定起始姿勢。")
        s.append("蛋白" + ("與胜肽" if peps else "") + "使用 Amber ff14SB 力場" + ("，小分子配體使用 OpenFF Sage 2.2（部分電荷以 NAGL 或 AM1-BCC 計算）" if small else "")
                 + f"。系統置於{box[0]} TIP3P 水盒（蛋白到盒邊 {v('padding_nm')} nm），以 {salt} 中和淨電荷並調整到 {v('ion_concentration_molar')} M。")
        s.append("長程靜電以 PME 計算，非鍵截斷 1.0 nm，含氫的鍵以 HBonds 約束" + ("，並做氫質量重分配（3 amu）" if hmr else "")
                 + f"。系統先做能量最小化（最多 {v('minimize_iterations')} 步），在 NVT 下由 {v('heat_start_k'):g} K 升溫到 {v('temperature_k'):g} K（{v('nvt_ps'):g} ps），"
                 f"再於 NPT（{v('pressure_bar'):g} bar，Monte Carlo 恆壓器）平衡 {v('npt_ps'):g} ps，期間逐步釋放位置約束（{v('restraints')} 策略）。")
        s.append(f"正式模擬使用 Langevin 中點積分器（摩擦係數 {v('friction_per_ps'):g} ps⁻¹，步長 {v('timestep_fs'):g} fs），長度 {v('production_ns'):g} ns，"
                 f"獨立重複 {v('replicas')} 次，每 {v('trajectory_interval_ps'):g} ps 存一幀。所有模擬以 OpenMM 執行，主鏈 RMSD、Cα RMSF、配體口袋 RMSD 與接觸頻率以 MDTraj 計算。")
        if v("binding"):
            s.append(f"結合自由能的計算先以導向分子動力學產生解離路徑（拉速 {v('pull_velocity_nm_per_ps'):g} nm ps⁻¹，彈簧常數 {v('k_pull'):g} kJ mol⁻¹ nm⁻²，拉離 {v('pull_distance_nm'):g} nm）。"
                     f"沿路徑設置傘狀採樣窗口（彈簧常數 {v('k_umbrella'):g} kJ mol⁻¹ nm⁻²，每個窗口平衡 {v('window_equil_ps'):g} ps、取樣 {v('window_prod_ps'):g} ps，依重疊程度自適應加窗），"
                     "以 MBAR 合併成自由能剖面。誤差以自助法估計，收斂以前後半段是否一致來檢查。")
        return "".join(s)
    if lg == "ja":
        s = [f"受容体構造（{rid}）は PDBFixer で結晶化添加物と水を除き、欠けた重原子を補い、pH {ph} で水素を付加した。"]
        if ligs:
            s.append(f"{len(ligs)} 個のリガンドを AutoDock Vina で{'同時に' if sim else '個別に'}ドッキングし（探索の徹底度 {v('exhaustiveness')}、リガンドあたり {v('n_poses')} ポーズ）、"
                     "スコア、クラスターの大きさ、接触残基から初期ポーズを選んだ。")
        s.append("タンパク質" + ("とペプチド" if peps else "") + "には Amber ff14SB 力場を用い" + ("、低分子リガンドには OpenFF Sage 2.2 を用いた（部分電荷は NAGL または AM1-BCC で計算）" if small else "た")
                 + f"。系は{box[2] + 'の' if box[2] else ''} TIP3P 水ボックスに入れ（タンパク質からボックス端まで {v('padding_nm')} nm）、{salt} で正味電荷を中和して {v('ion_concentration_molar')} M に調整した。")
        s.append("長距離静電相互作用は PME で計算し、非結合カットオフは 1.0 nm、水素を含む結合は HBonds で拘束した" + ("。水素質量の再分配（3 amu）も行った" if hmr else "")
                 + f"。エネルギー最小化（最大 {v('minimize_iterations')} ステップ）の後、NVT で {v('heat_start_k'):g} K から {v('temperature_k'):g} K まで昇温し（{v('nvt_ps'):g} ps）、"
                 f"NPT（{v('pressure_bar'):g} bar、Monte Carlo バロスタット）で {v('npt_ps'):g} ps 平衡化しながら位置拘束を段階的に外した（{v('restraints')} 方式）。")
        s.append(f"本計算は Langevin 中点積分法（摩擦係数 {v('friction_per_ps'):g} ps⁻¹、時間刻み {v('timestep_fs'):g} fs）で {v('production_ns'):g} ns 行った。"
                 f"独立な計算の数は {v('replicas')} で、{v('trajectory_interval_ps'):g} ps ごとにフレームを保存した。シミュレーションはすべて OpenMM で実行し、"
                 "主鎖 RMSD、Cα RMSF、リガンドのポケット内 RMSD、接触頻度は MDTraj で計算した。")
        if v("binding"):
            s.append(f"結合自由エネルギーは、まずステアード分子動力学で解離経路を作り（引き離し速度 {v('pull_velocity_nm_per_ps'):g} nm ps⁻¹、ばね定数 {v('k_pull'):g} kJ mol⁻¹ nm⁻²、"
                     f"引き離し距離 {v('pull_distance_nm'):g} nm）、経路に沿ってアンブレラサンプリングのウィンドウを置いた（ばね定数 {v('k_umbrella'):g} kJ mol⁻¹ nm⁻²、"
                     f"ウィンドウごとに平衡化 {v('window_equil_ps'):g} ps、サンプリング {v('window_prod_ps'):g} ps、重なりに応じてウィンドウを適応的に追加）。"
                     "ウィンドウは MBAR で自由エネルギープロファイルにまとめた。誤差はブートストラップ法で見積もり、収束は前半と後半の一致で確認した。")
        return "".join(s)
    if lg == "ko":
        s = [f"수용체 구조({rid})는 PDBFixer로 결정화 첨가물과 물을 제거하고 빠진 중원자를 채운 뒤 pH {ph}에서 수소를 붙였다. "]
        if ligs:
            s.append(f"리간드 {len(ligs)}개를 AutoDock Vina로 {'동시에' if sim else '각각'} 도킹하고(탐색 강도 {v('exhaustiveness')}, 리간드당 포즈 {v('n_poses')}개), "
                     "점수, 클러스터 크기, 접촉 잔기를 보고 시작 포즈를 골랐다. ")
        s.append("단백질" + ("과 펩타이드" if peps else "") + "에는 Amber ff14SB 힘장을 사용했다" + (". 저분자 리간드에는 OpenFF Sage 2.2를 사용했다(부분 전하는 NAGL 또는 AM1-BCC로 계산)" if small else "")
                 + f". 시스템은 {box[3]} TIP3P 물 상자에 넣고(단백질에서 상자 가장자리까지 {v('padding_nm')} nm) {salt}로 순전하를 중화한 뒤 {v('ion_concentration_molar')} M로 맞췄다. ")
        s.append("장거리 정전기는 PME로 계산했고 비결합 절단 거리는 1.0 nm, 수소를 포함한 결합은 HBonds로 구속했다" + (". 수소 질량 재분배(3 amu)도 적용했다" if hmr else "")
                 + f". 에너지 최소화(최대 {v('minimize_iterations')} 단계) 후 NVT에서 {v('heat_start_k'):g} K에서 {v('temperature_k'):g} K까지 승온하고({v('nvt_ps'):g} ps), "
                 f"NPT({v('pressure_bar'):g} bar, Monte Carlo 바로스탯)에서 {v('npt_ps'):g} ps 동안 평형화하면서 위치 구속을 단계적으로 풀었다({v('restraints')} 방식). ")
        s.append(f"본 시뮬레이션은 Langevin 중점 적분기(마찰 계수 {v('friction_per_ps'):g} ps⁻¹, 시간 간격 {v('timestep_fs'):g} fs)로 {v('production_ns'):g} ns 동안 수행했다. "
                 f"독립 반복 수는 {v('replicas')}회이며 {v('trajectory_interval_ps'):g} ps마다 프레임을 저장했다. 모든 시뮬레이션은 OpenMM으로 실행했고 "
                 "주사슬 RMSD, Cα RMSF, 리간드 포켓 RMSD, 접촉 빈도는 MDTraj로 계산했다. ")
        if v("binding"):
            s.append(f"결합 자유 에너지는 먼저 조향 분자동역학으로 해리 경로를 만들었다(당김 속도 {v('pull_velocity_nm_per_ps'):g} nm ps⁻¹, 용수철 상수 {v('k_pull'):g} kJ mol⁻¹ nm⁻², "
                     f"당김 거리 {v('pull_distance_nm'):g} nm). 경로를 따라 엄브렐라 샘플링 윈도우를 두었다(용수철 상수 {v('k_umbrella'):g} kJ mol⁻¹ nm⁻², "
                     f"윈도우마다 평형화 {v('window_equil_ps'):g} ps, 샘플링 {v('window_prod_ps'):g} ps, 겹침 정도에 따라 윈도우를 적응적으로 추가). "
                     "윈도우는 MBAR로 합쳐 자유 에너지 프로파일을 얻었다. 오차는 부트스트랩으로 추정했고 수렴은 앞뒤 절반의 일치로 확인했다.")
        return "".join(s)
    s = [f"The receptor structure ({rid}) was prepared with PDBFixer. Crystallisation additives and water were removed, "
         f"missing heavy atoms were added and hydrogens were placed at pH {ph}. "]
    if ligs:
        s.append(f"{len(ligs)} ligand{'s were' if len(ligs) > 1 else ' was'} docked {'simultaneously' if sim else 'independently'} with AutoDock Vina "
                 f"(exhaustiveness {v('exhaustiveness')}, {v('n_poses')} poses per ligand), and the starting pose was chosen from score, "
                 "cluster size and contact residues. ")
    s.append("The protein" + (" and peptide" if peps else "") + " were described with Amber ff14SB"
             + (" and small-molecule ligands with OpenFF Sage 2.2 (partial charges from NAGL or AM1-BCC)" if small else "")
             + f". Each system was solvated in a {box[1]} TIP3P water box with {v('padding_nm')} nm between protein and box edge, "
             f"neutralised and brought to {v('ion_concentration_molar')} M {salt}. ")
    s.append("Long-range electrostatics used PME with a 1.0 nm non-bonded cut-off. Bonds to hydrogen were constrained"
             + (" and hydrogen masses were repartitioned to 3 amu" if hmr else "") + ". "
             f"After energy minimisation (up to {v('minimize_iterations')} steps), the system was heated from {v('heat_start_k'):g} K to "
             f"{v('temperature_k'):g} K under NVT ({v('nvt_ps'):g} ps) and equilibrated under NPT ({v('pressure_bar'):g} bar, "
             f"Monte Carlo barostat) for {v('npt_ps'):g} ps while position restraints were released ({v('restraints')} strategy). ")
    s.append(f"Production used a Langevin middle integrator (friction {v('friction_per_ps'):g} ps⁻¹, time step {v('timestep_fs'):g} fs) "
             f"for {v('production_ns'):g} ns in {v('replicas')} independent replica{'s' if v('replicas', 1) > 1 else ''}, "
             f"saving a frame every {v('trajectory_interval_ps'):g} ps. All simulations were run with OpenMM. Backbone RMSD, Cα RMSF, "
             "ligand pocket RMSD and contact frequencies were computed with MDTraj. ")
    if v("binding"):
        s.append(f"For binding free energies, steered molecular dynamics first produced a dissociation path (pulling velocity {v('pull_velocity_nm_per_ps'):g} nm ps⁻¹, "
                 f"spring constant {v('k_pull'):g} kJ mol⁻¹ nm⁻², pulling distance {v('pull_distance_nm'):g} nm). Umbrella-sampling windows were "
                 f"placed along the path (spring constant {v('k_umbrella'):g} kJ mol⁻¹ nm⁻², {v('window_equil_ps'):g} ps equilibration "
                 f"and {v('window_prod_ps'):g} ps sampling per window, with windows added adaptively by overlap) and combined with MBAR. "
                 "Errors were estimated by bootstrapping, and convergence was checked by agreement between the first and second halves.")
    return "".join(s)


def _limitations(doc: Doc, wf) -> list[str]:
    L = doc.lang
    items = []
    for name, r in (wf.state().get("cpp") or {}).items():
        if r.get("limitation"):
            items.append(f"{name}: {r['limitation']}")
    for name, g in (wf.state().get("advisories") or {}).items():
        items.append(g.get("explanation", ""))
    st_ = wf.state()
    multi = (st_["steps"].get("pose_selection") or {}).get("selection", {}).get("mode") == "simultaneous" or bool(st_.get("multi_ligand"))
    if multi:     # D-60: what a multi-ligand system can and cannot say
        items.append(tx(("這是多配體系統。Vina 分數沒有靜電項，聯合姿勢裡配體之間的作用只是粗略估計。"
                         "每個配體的部分電荷是各自計算的固定電荷（AM1-BCC 類），不含配體之間的極化，相鄰帶電基團的作用可能被高估或低估。"
                         "模擬中的平底限制讓配體不會完全離開口袋，所以兩個配體能否一直共同佔位，要在不加限制的重跑中確認。",
                         "This is a multi-ligand system. The Vina score has no electrostatic term, so ligand–ligand interactions in "
                         "joint poses are only rough estimates. Each ligand's partial charges are fixed AM1-BCC-type charges computed "
                         "for that ligand alone, without mutual polarisation, so neighbouring charged groups may be over- or "
                         "under-stabilised. The flat-bottom restraint keeps every ligand from leaving the pocket, so sustained "
                         "co-occupancy has to be confirmed in an unrestrained rerun.",
                         "これは複数リガンドの系です。Vina のスコアには静電項がないため、同時ポーズでのリガンド間の相互作用は大まかな見積もりにすぎません。"
                         "各リガンドの部分電荷はそれぞれ単独で計算した固定電荷（AM1-BCC 系）で、リガンド間の分極を含まないため、隣り合う荷電基の相互作用は過大にも過小にも評価され得ます。"
                         "シミュレーション中はフラットボトム拘束でリガンドがポケットから完全には離れないため、共存が保たれるかどうかは拘束なしの再計算で確認する必要があります。",
                         "다중 리간드 시스템입니다. Vina 점수에는 정전기 항이 없으므로 동시 포즈에서 리간드 간 상호작용은 대략적인 추정일 뿐입니다. "
                         "각 리간드의 부분 전하는 리간드마다 따로 계산한 고정 전하(AM1-BCC 계열)이며 리간드 간 분극을 포함하지 않으므로, 이웃한 하전기의 상호작용이 과대 또는 과소 평가될 수 있습니다. "
                         "시뮬레이션 중에는 평평한 바닥 구속 때문에 리간드가 포켓을 완전히 떠나지 않으므로, 공존이 유지되는지는 구속 없이 다시 계산해서 확인해야 합니다."), L))
        ml = st_.get("multi_ligand") or {}
        if ml.get("status") == "ACCEPTED":
            items.append(tx(("使用者讓有原子重疊或穿環的多配體構型照原樣進入 MD。能量最小化可能把配體推離原本的位置，相關結果要保守看待。",
                             "The user let a multi-ligand geometry with overlaps or ring piercing enter MD as it was. Minimisation "
                             "may have pushed a ligand away from its pose, so read the related results conservatively.",
                             "ユーザーは原子の重なりや環の貫通がある複数リガンドの構造をそのまま MD に進めました。"
                             "エネルギー最小化でリガンドが元の位置から押し出された可能性があるため、関連する結果は慎重に解釈してください。",
                             "사용자가 원자 겹침이나 고리 관통이 있는 다중 리간드 구조를 그대로 MD에 넣었습니다. "
                             "에너지 최소화 과정에서 리간드가 원래 자리에서 밀려났을 수 있으므로 관련 결과는 신중하게 해석해야 합니다."), L))
    for name, r in (wf.state().get("peptide_access") or {}).items():
        for part in ("precheck", "pose"):
            g = r.get(part) or {}
            if g.get("advisory"):
                items.append(f"{name}: {g.get('explanation', '')}")
    for name, r in ((wf.state()["steps"].get("binding") or {}).get("results") or {}).items():
        items += [f"{name}: {c}" for c in r.get("caveats") or []]
    tier = (wf.cfg.get("md") or {}).get("tier", "teaching")
    if tier == "classroom":
        items.append(tx(("這個流程用的是課堂等級（2 ns），只適合學習與檢查流程，不足以支持科學結論。",
                         "This workflow used the classroom tier (2 ns). It is for learning and checking the workflow and does not support scientific conclusions.",
                         "このワークフローは授業用の等級（2 ns）で実行しました。手順の学習と確認のためのもので、科学的な結論の根拠にはなりません。",
                         "이 워크플로는 수업용 등급(2 ns)으로 실행했습니다. 절차를 배우고 확인하는 용도이며 과학적 결론의 근거가 되지 못합니다."), L))
    if int((wf.cfg.get("md") or {}).get("replicas", 1)) < 3:
        items.append(tx(("只跑了一次模擬，無法報告重複之間的標準差。", "Only one replica was run, so no standard deviation between replicas can be reported.",
                         "シミュレーションは 1 回だけなので、繰り返し間の標準偏差は報告できません。",
                         "시뮬레이션을 한 번만 실행했으므로 반복 간 표준편차를 보고할 수 없습니다."), L))
    items.append(tx(("對接分數是經驗評分，誤差約 1 到 2 kcal mol⁻¹，不要直接當成結合親和力。",
                     "Docking scores are empirical, with an error of about 1 to 2 kcal mol⁻¹. Do not read them as binding affinities.",
                     "ドッキングスコアは経験的な評価値で、誤差は約 1〜2 kcal mol⁻¹ です。結合親和性としてそのまま読まないでください。",
                     "도킹 점수는 경험적 평가값이며 오차가 약 1~2 kcal mol⁻¹입니다. 결합 친화도로 그대로 읽지 마십시오."), L))
    return items


# ------------------------------------------------------------------------------------------- build
def _repair_times(wf, cases: dict, runs: dict, metrics: dict, ext: dict) -> None:
    """D-89: trajectories analysed before the fix carry mdtraj's per-file frame numbers as time (0–9 ps, 0–9 ps …),
    which drew every line back to zero.  When a stored time axis does not increase, rebuild it from the production
    record of the first replica (total steps × time step over all saved frames); the extended analysis used
    frame_indices() of the same trajectory, so its frames get the matching times.  If the record cannot be read the
    figures fall back to frame numbers (figures.time_axis)."""
    from ..analysis.extended import frame_indices
    for key, m in metrics.items():
        t = m.get("time_ns") or []
        if len(t) < 2 or np.all(np.diff(np.asarray(t, float)) > 0):
            continue
        real = None
        try:
            from ..project import Run
            from ..analysis.stream import production_times_ps
            r = runs.get(key) or {}
            if r.get("run_ids") and key in cases:
                ps = production_times_ps(Run(wf.project.case(cases[key]["case_id"]), r["run_ids"][0]).dir)
                real = None if ps is None else np.asarray(ps, float) / 1000.0
        except Exception:  # noqa: BLE001
            real = None
        if real is None or len(real) != len(t):
            continue
        m["time_ns"] = real.tolist()
        e = ext.get(key) or {}
        if e.get("time_ns"):
            idx = frame_indices(len(real))
            if len(idx) == len(e["time_ns"]):
                e["time_ns"] = real[idx].tolist()
                hp = e.get("hbonds_protein") or {}
                if hp.get("time_ns"):
                    step = max(1, len(idx) // 100)
                    hp["time_ns"] = real[idx][::step].tolist()


def build_workflow_report(wf, out_path: Path | None = None, *, lang: str | None = None, banner_html: str = "") -> Path:
    """banner_html: trusted markup placed above the title (the report template marks itself as synthetic data)."""
    out_path = Path(out_path) if out_path else wf.dir / "workflow_report.html"
    L = lang or wf.cfg.get("language") or "en"
    L = L if L in LANGS else "en"
    doc = Doc(L, wf.dir / "report_figures")
    FG.reset_colours()                         # D-89: one colour per series, the same in every figure of this report
    counter = {"n": 0}

    def nxt():
        counter["n"] += 1
        return counter["n"]
    doc.next = nxt
    cfg = wf.cfg
    goal = cfg.get("goal") or {"classroom": "teaching", "teaching": "screening", "research": "publication"}.get((cfg.get("md") or {}).get("tier"), "teaching")
    vals = actual_values(wf)
    doc.user_keys = set(advisor.values_from_config(cfg))
    f = advisor.features_from_config(cfg)
    body = [_design(doc, wf), _structure(doc, wf), SR.fold_section(doc, wf), _screen(doc, wf), _docking(doc, wf, vals, f, goal),
            _peptide(doc, wf), _md(doc, wf, vals, f, goal), SR.membrane_section(doc, wf), SR.longrun_section(doc, wf),
            _binding(doc, wf, vals, f, goal), SR.cg_section(doc, wf)]
    # key findings: the same sentences the figures carry (cautions first), plus the peptide and structure notes
    st = wf.state()
    pool = I.peptide(st.get("cpp") or {}, st.get("peptide_access") or {}) + doc.collected + \
        I.structure((load_json(wf.dir / "structure_gates.json", {}) or {}).get("gates") or [])[:1]
    key = key_findings(pool)
    stages = ("workflow", "docking", "binding", "build", "engine", "screen", "gui", "peptide", "analysis", "structure")
    dec = getattr(wf, "dec", None)
    if hasattr(dec, "unattributed"):          # D-96 (A10): this workflow's rows; unattributed ones listed apart, never guessed
        rows_log = [r for r in dec.read() if str(r.get("stage", "")).startswith(stages)]
        rows_unknown = [r for r in dec.unattributed() if str(r.get("stage", "")).startswith(stages)]
    else:
        rows_log, rows_unknown = [r for r in wf.project.decisions.read() if str(r.get("stage", "")).startswith(stages)], []
    log = doc.table([tx(("時間", "Time", "日時", "시각"), L), tx(("階段", "Stage", "段階", "단계"), L), tx(("項目", "Item", "項目", "항목"), L),
                     tx(("選擇", "Choice", "選択", "선택"), L), tx(("類型", "Type", "種類", "유형"), L), tx(("理由", "Reason", "理由", "이유"), L)],
                    [[_esc(str(r.get("at", ""))[:19].replace("T", " ")), _esc(r.get("stage", "")), _esc(r.get("what", "")),
                      f"<code>{_esc(r.get('choice', ''))}</code>", _esc(r.get("kind", "")), _esc(r.get("why", ""))] for r in rows_log],
                    ("自動與人工的決策（依時間排列）", "Automatic and human decisions (chronological)",
                     "自動と手動の判断（時系列）", "자동 및 수동 결정 (시간순)"))
    if rows_unknown:
        log += (f"<p class=muted>{_esc(tx(('下列紀錄沒有流程標記（專案層級的步驟，或 D-96 之前寫入），無法確認是否屬於本流程，只列出不歸屬。', 'The records below carry no workflow id (project-level steps, or written before D-96); whether they belong to this workflow cannot be confirmed, so they are listed without attribution.', '以下の記録にはワークフローの識別子がありません（プロジェクト単位の手順、または D-96 以前の記録）。このワークフローのものか確認できないため、帰属させずに示します。', '아래 기록에는 워크플로 식별자가 없습니다(프로젝트 단위 단계 또는 D-96 이전 기록). 이 워크플로의 것인지 확인할 수 없어 귀속하지 않고 나열합니다.'), L))}</p>"
                + doc.table([tx(("時間", "Time", "日時", "시각"), L), tx(("階段", "Stage", "段階", "단계"), L), tx(("項目", "Item", "項目", "항목"), L),
                             tx(("選擇", "Choice", "選択", "선택"), L), tx(("理由", "Reason", "理由", "이유"), L)],
                            [[_esc(str(r.get("at", ""))[:19].replace("T", " ")), _esc(r.get("stage", "")), _esc(r.get("what", "")),
                              f"<code>{_esc(r.get('choice', ''))}</code>", _esc(r.get("why", ""))] for r in rows_unknown],
                            ("歸屬不明的決策紀錄", "Decision records of unknown attribution", "帰属不明の判断記録", "귀속 불명의 결정 기록")))
    n_meth = nxt()
    n_lim = nxt()
    html = [f"<!doctype html><html lang={HTML_LANG[L]}><head><meta charset=utf-8>"
            f"<title>{_esc(tx(H['title'], L))} · {_esc(wf.name)}</title><style>{CSS}</style></head><body>" + banner_html,
            f"<h1>{_esc(tx(H['title'], L))}</h1>",
            f"<p class=meta>{_esc(tx(H['project'], L))}{colon(L)}{_esc(wf.project.name)} · {_esc(tx(H['workflow'], L))}{colon(L)}{_esc(wf.name)} · "
            f"{_esc(tx(H['generated'], L))}{colon(L)}{now_iso()[:19].replace('T', ' ')} UTC</p>",
            (f"<p class=meta>{_esc(tx(H['zh_note'], L))}</p>" if L != "zh" else ""),
            f"<div class=box><b>{_esc(tx(H['key_findings'], L))}</b>{_findings_html(key, L) or '<p class=muted>—</p>'}</div>",
            *body,
            f"<h2>{n_meth}. {_esc(tx(H['methods'], L))}</h2><div class=methods>{_esc(methods_text(wf, vals, L) + SR.methods_sentences(wf, L))}</div>",
            f"<h2>{n_lim}. {_esc(tx(H['limitations'], L))}</h2><ul>" + "".join(f"<li>{_esc(x)}</li>" for x in _limitations(doc, wf) + SR.limitations(wf, L)) + "</ul>",
            _viewer_section(wf, L),
            f"<h2>{_esc(tx(H['appendix_params'], L))}</h2>" + _param_table(doc, advisor.parameter_table(vals, f, goal, L),
                                                                         ("全部參數的採用值、本案例建議值與理由", "All parameters with the value used, the recommendation for this case and the reason",
                                                                          "全パラメータの使用値、このケースの推奨値と理由", "전체 매개변수의 사용값, 이 사례의 권장값과 이유")),
            f"<h2>{_esc(tx(H['appendix_log'], L))}</h2>{log}",
            f"<h2>{_esc(tx(H['appendix_cfg'], L))}</h2><details><summary>config.json</summary><pre>{_esc(json.dumps(cfg, ensure_ascii=False, indent=1))}</pre></details>",
            __import__("md20.util.stamp", fromlist=["html_footer"]).html_footer(), "</body></html>"]
    out_path.write_text("".join(html), encoding="utf-8")
    try:
        from ..util import atomic_write_json
        doc.figdir.mkdir(parents=True, exist_ok=True)
        atomic_write_json({"lang": L, "report": str(out_path), "created_at": now_iso(), "figures": doc.index},
                          doc.figdir / f"index_{L}.json", backup=False)
    except Exception:  # noqa: BLE001
        pass
    return out_path


def _viewer_section(wf, lang: str = "zh") -> str:
    """WP13: offline 3D view (inline JS) of each docked case — production trajectory if available, else the start."""
    try:
        from ..gui.views import viewer_targets, scene_for, viewer_html
    except Exception:  # noqa: BLE001
        return ""
    parts = []
    by_key: dict = {}
    for t in viewer_targets(wf, lang=lang):
        if t["key"] == "apo":
            continue
        by_key[t["key"]] = t if t["mode"] == "traj" or t["key"] not in by_key else by_key[t["key"]]
    for key, t in by_key.items():
        try:
            sc = scene_for(t, max_frames=40)
        except Exception:  # noqa: BLE001  (e.g. no mdtraj): fall back to the start structure
            try:
                sc = scene_for({**t, "mode": "start"})
                t = {**t, "label": key + colon(lang) + pick(("建模起始結構", "starting structure from the build", "構築した初期構造", "구축된 시작 구조"), lang)}
            except Exception:  # noqa: BLE001
                continue
        parts.append(f"<h3>{_esc(t['label'])}</h3>" + viewer_html(sc, standalone=False, height_px=380, lang=lang))
    if not parts:
        return ""
    return ("<h2>" + pick(("3D 檢視（離線可用。拖曳可旋轉，軌跡可以播放）", "3D view (works offline. Drag to rotate and play the trajectory)",
                           "3D 表示（オフラインで使えます。ドラッグで回転、軌跡は再生できます）", "3D 보기 (오프라인 사용 가능. 드래그하면 회전하고 궤적을 재생할 수 있습니다)"), lang)
            + "</h2>" + "".join(parts))


def _toolbox_section(doc, ext: dict, order: list) -> str:
    """D-105: slow motions (tICA), Markov-model timescales with their eligibility, side-chain H-bond network."""
    out = ""
    for k in order:
        ti = (ext.get(k) or {}).get("tica") or {}
        if ti.get("status") == "ok" and (ti.get("landscape") or {}).get("G"):
            out += doc.figure_block(FG.landscape(ti["landscape"], None, doc.figdir / f"md_tica_{k}.png", axes=("tIC1", "tIC2")), "tica_landscape",
                                    FT.classify_tica(k, ti), k)
            m = ti.get("msm") or {}
            if len(m.get("lags_ns") or []) >= 2:
                out += doc.figure_block(FG.implied_timescales(m, doc.figdir / f"md_its_{k}.png"), "msm_its", FT.classify_msm(k, m), k)
    for k in order:
        net = ((ext.get(k) or {}).get("hbonds_protein") or {}).get("network") or {}
        if net.get("status") == "ok" and net.get("edges"):
            rows = [[_esc(a), _esc(b), f"{o:.0%}"] for a, b, o in net["edges"][:15]]
            out += doc.table([doc.t(("殘基", "Residue", "残基", "잔기")), doc.t(("殘基", "Residue", "残基", "잔기")),
                              doc.t(("出現比例", "Occupancy", "出現率", "출현 비율"))], rows,
                             (f"{k}：持續的側鏈氫鍵（≥ {net['min_occupancy']:.0%} 的幀）",
                              f"{k}: persistent side-chain hydrogen bonds (≥ {net['min_occupancy']:.0%} of frames)",
                              f"{k}：持続する側鎖の水素結合（フレームの {net['min_occupancy']:.0%} 以上）",
                              f"{k}: 지속되는 곁사슬 수소 결합(프레임의 {net['min_occupancy']:.0%} 이상)"), num_cols={2})
            hubs = "、".join(f"{r}（{n}）" for r, n in net.get("hubs", [])[:5])
            hubs_en = ", ".join(f"{r} ({n})" for r, n in net.get("hubs", [])[:5])
            comp = max((len(c) for c in net.get("components") or []), default=0)
            out += _findings_html([FT.S("note",
                                        f"{k}：連結最多的殘基是 {hubs}；最大的氫鍵網路有 {comp} 個殘基。網路中心的殘基若突變，最可能改變局部結構。",
                                        f"{k}: the most connected residues are {hubs_en}; the largest network holds {comp} residues. "
                                        "Mutating a hub residue is the most likely to change the local structure.",
                                        f"{k}：つながりが最も多い残基は {hubs} です。最大のネットワークは {comp} 残基です。中心の残基を変異させると局所構造が最も変わりやすくなります。",
                                        f"{k}: 연결이 가장 많은 잔기는 {hubs_en}입니다. 가장 큰 네트워크는 잔기 {comp}개입니다. 중심 잔기를 돌연변이시키면 국소 구조가 가장 바뀌기 쉽습니다.")],
                                  doc.lang)
    return out


def _hydration_tables(doc, ext: dict, lig_keys: list, lab) -> str:
    """D-105: water sites around each ligand (density relative to bulk water and how often a water sits there)."""
    out = ""
    for k, rn in lig_keys:
        h = (((ext.get(k) or {}).get("ligands") or {}).get(rn) or {}).get("hydration") or {}
        if h.get("status") == "no_water":
            out += _findings_html([FT.S("note", f"{lab(k, rn)}：軌跡只存溶質，沒有水，無法分析水合位點。",
                                        f"{lab(k, rn)}: the trajectory keeps only the solute, so hydration sites cannot be analysed.",
                                        f"{lab(k, rn)}：トラジェクトリには溶質しかなく、水和サイトは解析できません。",
                                        f"{lab(k, rn)}: 궤적에 용질만 있어 수화 위치를 분석할 수 없습니다.")], doc.lang)
            continue
        if h.get("status") != "ok" or not h.get("sites"):
            continue
        rows = [[str(i + 1), f"{x['density_ratio']:.1f}", f"{x['occupancy']:.0%}", f"{10 * x['distance_to_center_nm']:.1f}"]
                for i, x in enumerate(h["sites"])]
        out += doc.table([doc.t(("位點", "Site", "サイト", "위치")), doc.t(("密度／體相水", "Density / bulk", "密度／バルク", "밀도/벌크")),
                          doc.t(("有水的時間", "Time occupied", "水がいる時間", "물이 있는 시간")),
                          doc.t(("離配體中心 (Å)", "From ligand centre (Å)", "リガンド中心から (Å)", "리간드 중심에서 (Å)"))], rows,
                         (f"{lab(k, rn)}：配體周圍 1 nm 內的水合位點", f"{lab(k, rn)}: hydration sites within 1 nm of the ligand",
                          f"{lab(k, rn)}：リガンドから 1 nm 以内の水和サイト", f"{lab(k, rn)}: 리간드 1 nm 이내의 수화 위치"), num_cols={1, 2, 3})
        stay = [x for x in h["sites"] if x["occupancy"] >= 0.8]
        out += _findings_html([FT.S("note",
                                    f"{lab(k, rn)}：{len(stay)} 個位點八成以上時間有水。這些水可能在配體與蛋白之間搭橋；設計衍生物時，取代它們或保留它們會改變結合。",
                                    f"{lab(k, rn)}: {len(stay)} sites hold a water more than 80% of the time. Such waters may bridge "
                                    "ligand and protein; replacing or keeping them in a derivative changes the binding.",
                                    f"{lab(k, rn)}：{len(stay)} か所で 8 割以上の時間に水がいます。これらはリガンドとタンパク質を橋渡ししている可能性があり、誘導体で置き換えるか残すかで結合が変わります。",
                                    f"{lab(k, rn)}: {len(stay)}곳에 80% 이상의 시간 동안 물이 있습니다. 이런 물은 리간드와 단백질을 잇는 다리일 수 있어 유도체에서 치환하거나 남기면 결합이 달라집니다.")],
                              doc.lang)
    return out


def _common_html(doc, comp: dict) -> str:
    """D-106 (A11/F12/F10): comparability of the systems, their landscapes on one PCA basis and the representative
    frames of each basin."""
    out = ""
    cmp_ok = comp.get("comparability") or {}
    cb = load_json(comp.get("common_basis_file"), {}) if comp.get("common_basis_file") else {}
    if not cmp_ok and not cb:
        return ""
    out += _sub(doc, "系統之間的比較", "Comparison between systems", "系どうしの比較", "계 사이 비교")
    if cmp_ok and not cmp_ok.get("comparable"):
        diff = "、".join(d["field"] for d in cmp_ok.get("differences") or []) or "—"
        unk = "、".join(cmp_ok.get("unknown") or []) or "—"
        out += _findings_html([FT.S("caution",
                                    f"條件不同：{diff}；無法確認：{unk}。apo 與複合物的 RMSF 差異不計算，地形只並列。差異可能來自設定，不一定來自配體。",
                                    f"Conditions differ: {diff}; not confirmed: {unk}. The apo–complex RMSF difference is not computed and the "
                                    "maps are only shown side by side. A difference may come from the settings rather than the ligand.",
                                    f"条件の違い：{diff}。確認できない項目：{unk}。apo と複合体の RMSF の差は計算せず、地形は並べるだけです。差は設定から来ている可能性があります。",
                                    f"다른 조건: {diff}. 확인할 수 없는 항목: {unk}. apo와 복합체의 RMSF 차이는 계산하지 않고 지형은 나란히만 보입니다. 차이가 설정에서 왔을 수 있습니다.")],
                              doc.lang)
    if cb.get("status") == "ok":
        out += doc.figure_block(FG.common_landscape(cb, doc.figdir / "md_common_landscape.png"), "common_landscape", FT.classify_common(cb))
        rows = [[_esc(r["system"]), str(r["basin"]), str(r["frame"]), "—" if r.get("time_ns") is None else f"{r['time_ns']:.2f}",
                 "—" if r.get("population") is None else f"{r['population']:.0%}"] for r in cb.get("representatives") or []]
        if rows:
            out += doc.table([doc.t(("系統", "System", "系", "계")), doc.t(("低谷", "Basin", "谷", "골")),
                              doc.t(("代表幀（分析抽樣後）", "Representative frame (analysis sample)", "代表フレーム（解析用サンプル）", "대표 프레임(분석 표본)")),
                              doc.t(("時間 (ns)", "Time (ns)", "時間 (ns)", "시간 (ns)")), doc.t(("比例", "Share", "割合", "비율"))], rows,
                             ("每個低谷的代表結構（離低谷最低點最近的實際幀）", "Representative structure of each basin (the actual frame closest to the basin minimum)",
                              "各谷の代表構造（谷の最低点に最も近い実際のフレーム）", "골마다 대표 구조(골 최저점에 가장 가까운 실제 프레임)"), num_cols={1, 2, 3, 4})
    return out
