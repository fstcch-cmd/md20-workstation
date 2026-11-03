"""Interface text and teaching material in four languages (English default; D-51, D-74).  Pure Python, testable
without NiceGUI.

Every string is a (zh, en, ja, ko) tuple resolved with `t(key, lang)`.  Rules from the user's design review still hold:
no lab stamp, no unexplained abbreviations, no "/" as a separator, generic wording (no example molecule baked in).
Style and glossary: docs/specs/writing_style.md.
"""
from __future__ import annotations

import copy

from ..advisor import tx

from ..i18n import LANG_NAMES  # noqa: E402,F401  (D-74)

UI = {
    "app_title": ("MD20 分子模擬工作站", "MD20 Molecular Simulation Workstation",
                  "MD20 分子シミュレーションワークステーション", "MD20 분자 시뮬레이션 워크스테이션"),
    "nav_home": ("首頁", "Home", "ホーム", "홈"),
    "nav_system": ("電腦狀態", "Computer status", "コンピューターの状態", "컴퓨터 상태"),
    "nav_projects": ("專案", "Projects", "プロジェクト", "프로젝트"),
    "language": ("語言", "Language", "言語", "언어"),
    "home_intro": ("從分子對接、分子動力學一路做到結合自由能。每一步都會先檢查輸入。程式自動修正的地方，會說明改了什麼。"
                   "需要你判斷的地方，流程會停下來並列出可以選的做法。",
                   "The full workflow, from molecular docking through molecular dynamics to binding free energy. Every "
                   "step checks its inputs first. When the program corrects something, it tells you what it changed. "
                   "When a decision needs your judgement, the run stops and lists the options.",
                   "分子ドッキングから分子動力学、結合自由エネルギーまでを一通り行います。各ステップはまず入力を確認します。"
                   "プログラムが自動で修正した箇所は、何を変えたかを表示します。判断が必要な箇所ではワークフローが止まり、"
                   "選べる対応を示します。",
                   "분자 도킹부터 분자동역학, 결합 자유 에너지까지 전 과정을 진행합니다. 각 단계는 먼저 입력을 확인합니다. "
                   "프로그램이 자동으로 고친 부분은 무엇을 바꿨는지 알려 줍니다. 판단이 필요한 부분에서는 워크플로가 멈추고 "
                   "선택할 수 있는 방법을 보여 줍니다."),
    "choose_mode": ("選擇工作模式", "Choose a mode", "モードを選択", "모드 선택"),
    "recent": ("最近的流程", "Recent workflows", "最近のワークフロー", "최근 워크플로"),
    "no_recent": ("還沒有流程。", "No workflows yet.", "ワークフローはまだありません。", "아직 워크플로가 없습니다."),
    "open": ("開啟", "Open", "開く", "열기"), "start": ("開始", "Start", "開始", "시작"),
    "create_start": ("建立並開始", "Create and start", "作成して開始", "생성 후 시작"),
    "project_name": ("專案名稱", "Project name", "プロジェクト名", "프로젝트 이름"),
    "workflow_name": ("流程名稱", "Workflow name", "ワークフロー名", "워크플로 이름"),
    "receptor": ("受體", "Receptor", "受容体", "수용체"),
    "pdb_id": ("PDB 編號", "PDB identifier", "PDB 番号", "PDB 번호"),
    "or_upload": ("或上傳結構檔（PDB 或 mmCIF）", "or upload a structure file (PDB or mmCIF)",
                  "または構造ファイルをアップロード（PDB または mmCIF）", "또는 구조 파일 업로드(PDB 또는 mmCIF)"),
    "ph": ("pH", "pH", "pH", "pH"),
    "keep_hetero": ("要保留的輔因子與金屬（殘基名，以空格分隔）", "Cofactors and metals to keep (residue names separated by spaces)",
                    "残す補因子と金属（残基名をスペースで区切る）", "유지할 보조인자와 금속(잔기 이름, 공백으로 구분)"),
    "ligands": ("配體", "Ligands", "リガンド", "리간드"),
    "ligand_help": ("每行寫一個配體，依序是名稱、SMILES 或胜肽序列，最後可以加上共結晶配體的殘基名。"
                    "胜肽序列前面加 peptide:，例如 peptide:GGGGGKP。對接和模擬都直接使用 SMILES 寫出的帶電狀態，"
                    "所以請寫成 pH 7.4 下的形式。",
                    "Write one ligand per line. Give the name, then a SMILES string or peptide sequence, and optionally the "
                    "residue name of a co-crystal ligand. Put peptide: in front of a peptide sequence, for example "
                    "peptide:GGGGGKP. Docking and simulation use the charge state exactly as written in the SMILES, so "
                    "write it for pH 7.4.",
                    "1 行に 1 つのリガンドを書きます。名前、SMILES またはペプチド配列の順に書き、必要なら共結晶リガンドの"
                    "残基名を加えます。ペプチド配列の前には peptide: を付けます。例えば peptide:GGGGGKP のように書きます。"
                    "ドッキングとシミュレーションは SMILES に書かれた荷電状態をそのまま使うので、pH 7.4 での形で書いてください。",
                    "한 줄에 리간드 하나를 씁니다. 이름, SMILES 또는 펩타이드 서열 순서로 쓰고, 필요하면 공결정 리간드의 "
                    "잔기 이름을 덧붙입니다. 펩타이드 서열 앞에는 peptide:를 붙여 peptide:GGGGGKP처럼 씁니다. 도킹과 "
                    "시뮬레이션은 SMILES에 적힌 전하 상태를 그대로 사용하므로 pH 7.4 기준으로 쓰십시오."),
    "site": ("結合位置（對接搜尋區）", "Binding site (docking search box)", "結合部位（ドッキングの探索領域）",
             "결합 부위(도킹 탐색 영역)"),
    "site_residue": ("用共結晶配體定義（殘基名）", "Defined by a co-crystal ligand (residue name)",
                     "共結晶リガンドで指定（残基名）", "공결정 리간드로 지정(잔기 이름)"),
    "site_center": ("或中心座標 x, y, z（Å）", "or centre x, y, z (Å)", "または中心座標 x, y, z（Å）", "또는 중심 좌표 x, y, z (Å)"),
    "site_size": ("尺寸 x, y, z（Å）", "size x, y, z (Å)", "サイズ x, y, z（Å）", "크기 x, y, z (Å)"),
    "site_note": ("留空時會以整個蛋白為搜尋區。這是盲對接，結果的可信度較低。",
                  "Leave empty to search the whole protein. That is blind docking, and the result is less reliable.",
                  "空欄にするとタンパク質全体を探索します。これはブラインドドッキングで、結果の信頼性は低くなります。",
                  "비워 두면 단백질 전체를 탐색합니다. 이는 블라인드 도킹이며 결과의 신뢰도가 낮습니다."),
    "goal": ("研究目標", "Study goal", "研究の目的", "연구 목표"),
    "systems": ("要模擬的系統", "Systems to simulate", "シミュレーションする系", "시뮬레이션할 시스템"),
    "sys_apo": ("只有蛋白（對照）", "Protein alone (reference)", "タンパク質のみ（対照）", "단백질만(대조)"),
    "sys_single": ("每個配體分別與蛋白", "Each ligand with the protein", "リガンドごとにタンパク質と", "리간드별로 단백질과 함께"),
    "sys_multi": ("所有配體一起與蛋白", "All ligands together with the protein", "全リガンドをまとめてタンパク質と",
                  "모든 리간드를 함께 단백질과"),
    "parameters": ("模擬參數", "Simulation parameters", "シミュレーションのパラメーター", "시뮬레이션 매개변수"),
    "recommended": ("建議值", "Recommended", "推奨値", "권장값"), "reason": ("理由", "Reason", "理由", "이유"),
    "value": ("設定值", "Value", "設定値", "설정값"),
    "reset_rec": ("全部恢復建議值", "Reset all to recommended", "すべて推奨値に戻す", "모두 권장값으로 되돌리기"),
    "changed": ("已修改", "changed", "変更済み", "변경됨"),
    "checks": ("合理性檢查", "Plausibility check", "妥当性チェック", "타당성 검사"),
    "checks_ok": ("所有參數都在合理範圍內。", "All parameters are within plausible ranges.",
                  "すべてのパラメーターが妥当な範囲にあります。", "모든 매개변수가 타당한 범위 안에 있습니다."),
    "level_error": ("錯誤", "Error", "エラー", "오류"), "level_warning": ("注意", "Warning", "注意", "주의"),
    "level_info": ("提示", "Note", "ヒント", "참고"),
    "use_suggestion": ("套用建議", "Apply suggestion", "提案を適用", "제안 적용"),
    "estimate": ("時間估計", "Time estimate", "所要時間の見積もり", "예상 소요 시간"),
    "estimate_none": ("還沒有效能測試。到「電腦狀態」頁執行一次，就能依這台電腦的速度估計時間。",
                      "No benchmark yet. Run one on the Computer status page and the time will be estimated for this computer.",
                      "まだベンチマークがありません。「コンピューターの状態」ページで一度実行すると、このコンピューターの速度で"
                      "時間を見積もります。",
                      "아직 성능 테스트가 없습니다. '컴퓨터 상태' 페이지에서 한 번 실행하면 이 컴퓨터의 속도로 시간을 예측합니다."),
    "estimate_text": ("約 {total} 小時。分子動力學 {md} 小時，結合計算 {bind} 小時。系統約有 {atoms} 個原子，這台電腦每天約跑 {speed} ns。",
                      "About {total} h. Molecular dynamics {md} h, binding {bind} h. The system has about {atoms} atoms "
                      "and this computer runs about {speed} ns per day.",
                      "約 {total} 時間です。分子動力学 {md} 時間、結合計算 {bind} 時間です。系は約 {atoms} 原子で、"
                      "このコンピューターは 1 日あたり約 {speed} ns 進みます。",
                      "약 {total}시간입니다. 분자동역학 {md}시간, 결합 계산 {bind}시간입니다. 시스템은 원자 약 {atoms}개이고, "
                      "이 컴퓨터는 하루에 약 {speed} ns를 계산합니다."),
    "errors_block": ("請先修正標示為錯誤的參數。", "Fix the parameters marked as errors first.",
                     "エラーと表示されたパラメーターを先に修正してください。", "오류로 표시된 매개변수를 먼저 수정하십시오."),
    "hts": ("高通量篩選（選用）", "High-throughput screening (optional)", "ハイスループットスクリーニング（任意）",
            "고처리량 스크리닝(선택)"),
    "hts_help": ("上傳化合物表格（Excel 或 CSV）。程式會下載結構、做快速對接並排名。接著你在排名圖上點選要進入正式對接與模擬的化合物。",
                 "Upload a compound table (Excel or CSV). The program downloads the structures, docks them quickly and "
                 "ranks them. You then pick on the ranking chart which compounds go on to full docking and simulation.",
                 "化合物の表（Excel または CSV）をアップロードします。プログラムが構造をダウンロードし、簡易ドッキングを"
                 "行って順位を付けます。その後、順位グラフで本格的なドッキングとシミュレーションに進める化合物を選びます。",
                 "화합물 표(Excel 또는 CSV)를 업로드합니다. 프로그램이 구조를 내려받아 빠르게 도킹하고 순위를 매깁니다. "
                 "그다음 순위 그래프에서 정식 도킹과 시뮬레이션으로 넘길 화합물을 고릅니다."),
    "hts_template": ("下載範例表格", "Download the example table", "サンプルの表をダウンロード", "예시 표 다운로드"),
    "hts_upload": ("上傳化合物表格", "Upload compound table", "化合物の表をアップロード", "화합물 표 업로드"),
    "hts_manual": ("手動上傳結構（下載被阻擋時）", "Upload structures manually (when downloads are blocked)",
                   "構造を手動でアップロード（ダウンロードがブロックされた場合）", "구조 직접 업로드(다운로드가 차단된 경우)"),
    "upload_ok": ("已接受", "Accepted", "受理済み", "수락됨"), "upload_rejected": ("已拒絕", "Rejected", "却下", "거부됨"),
    "status": ("狀態", "Status", "状態", "상태"), "step": ("步驟", "Step", "ステップ", "단계"),
    "time": ("時間", "Time", "時刻", "시간"), "message": ("訊息", "Message", "メッセージ", "메시지"),
    "run_continue": ("開始或繼續", "Start or continue", "開始または再開", "시작 또는 계속"),
    "pause": ("暫停（下一個區段結束時）", "Pause (at the end of the next segment)", "一時停止（次の区切りの終わりで）",
              "일시 정지(다음 구간이 끝날 때)"),
    "open_report": ("開啟報告", "Open report", "レポートを開く", "보고서 열기"),
    "gates": ("閘門", "Gates", "ゲート", "게이트"), "screening": ("篩選", "Screening", "スクリーニング", "스크리닝"),
    "live": ("即時曲線", "Live curves", "リアルタイムのグラフ", "실시간 그래프"),
    "umbrella": ("傘狀採樣的覆蓋範圍", "Umbrella sampling coverage", "アンブレラサンプリングのカバー範囲", "엄브렐라 샘플링 범위"),
    "timeline": ("時間軸", "Timeline", "タイムライン", "타임라인"), "viewer": ("3D 檢視", "3D view", "3D 表示", "3D 보기"),
    "poses": ("對接姿勢（★ 推薦，✔ 已選，點一列可改用該姿勢）",
              "Docking poses (★ recommended, ✔ selected, click a row to use that pose)",
              "ドッキングポーズ（★ 推奨、✔ 選択中、行をクリックするとそのポーズを使います）",
              "도킹 포즈(★ 추천, ✔ 선택됨, 행을 클릭하면 그 포즈를 사용)"),
    "no_gates": ("目前沒有需要注意的閘門。", "No gates need attention.", "今のところ確認が必要なゲートはありません。",
                 "현재 확인이 필요한 게이트가 없습니다."),
    "manual_hint": ("以下要在程式外處理，處理完再重新提供輸入：", "These need work outside the program. Provide the new input when done:",
                    "次の項目はプログラムの外で対応が必要です。対応後に入力し直してください：",
                    "다음 항목은 프로그램 밖에서 처리해야 합니다. 처리 후 입력을 다시 제공하십시오:"),
    "busy": ("流程正在執行。請先暫停，或等它停在閘門再做決定。",
             "The workflow is running. Pause it, or wait until it stops at a gate, before you decide.",
             "ワークフローは実行中です。一時停止するか、ゲートで止まるのを待ってから判断してください。",
             "워크플로가 실행 중입니다. 일시 정지하거나 게이트에서 멈출 때까지 기다린 뒤 결정하십시오."),
    "teaching_mode": ("教學模式", "Teaching mode", "教育用モード", "교육 모드"),
    "paper": ("論文", "Paper", "論文", "논문"),
    "background": ("研究背景", "Background", "研究の背景", "연구 배경"),
    "objectives": ("學習目標", "Learning objectives", "学習目標", "학습 목표"),
    "what_md20_shows": ("這個案例示範的科學檢查", "Scientific checks in this case", "この事例で扱う科学的チェック",
                        "이 사례에서 다루는 과학적 검사"),
    "stages": ("流程與每一步的學習重點", "Workflow and what each step teaches", "ワークフローと各ステップの学習ポイント",
               "워크플로와 단계별 학습 포인트"),
    "discussion": ("討論題", "Discussion questions", "討論課題", "토론 문제"),
    "teach_params": ("這堂課使用快速模式的參數，數值依案例自動建議", "This lesson uses quick-mode parameters recommended for this case",
                     "この授業では、事例に合わせて自動で推奨されたクイックモードのパラメーターを使います",
                     "이 수업은 사례에 맞게 자동 추천된 빠른 모드 매개변수를 사용합니다"),
    "start_lesson": ("開始這個教學案例", "Start this teaching case", "この教材を始める", "이 교육 사례 시작"),
    "doctor_quick": ("快速診斷", "Quick check", "クイック診断", "빠른 진단"),
    "doctor_bench": ("診斷並測試效能", "Check and benchmark", "診断とベンチマーク", "진단 및 성능 테스트"),
    "doctor_wait": ("診斷中…", "Checking…", "診断中…", "진단 중…"),
    "doctor_bench_wait": ("診斷中，效能測試約需 20 秒…", "Checking. The benchmark takes about 20 s…",
                          "診断中です。ベンチマークは約 20 秒かかります…", "진단 중입니다. 성능 테스트는 약 20초 걸립니다…"),
    "confirm_md_title": ("要進入分子動力學嗎？", "Proceed to molecular dynamics?", "分子動力学に進みますか？",
                         "분자동역학으로 진행하시겠습니까?"),
}


def t(key: str, lang: str = "en", **fmt) -> str:
    s = tx(UI.get(key, (key, key)), lang)
    return s.format(**fmt) if fmt else s


# ------------------------------------------------------------------------------------------- modes
MODES = {
    "teach_small": {"title": ("教學模式一：多個小分子", "Teaching mode 1: several small molecules",
                              "教育用モード 1：複数の低分子", "교육 모드 1: 여러 저분자"),
                    "text": ("用論文中萃取物的六個代謝物同時對接 NF-κB p65。學習多配體對接、檢查結構是否可信，以及複合物是否穩定。",
                             "Six metabolites from a published extract study are docked together to NF-κB p65. You learn "
                             "multi-ligand docking, how to check that a structure is valid, and whether the complex stays stable.",
                             "論文の抽出物に含まれる 6 種類の代謝物を NF-κB p65 に同時にドッキングします。複数リガンドの"
                             "ドッキング、構造の信頼性の確認、複合体の安定性を学びます。",
                             "논문에 나온 추출물의 대사물 6종을 NF-κB p65에 동시에 도킹합니다. 다중 리간드 도킹, 구조 신뢰성 "
                             "확인, 복합체 안정성을 배웁니다."),
                    "case": "hsieh2024", "route": "/teach/hsieh2024"},
    "teach_peptide": {"title": ("教學模式二：胜肽", "Teaching mode 2: peptide", "教育用モード 2：ペプチド", "교육 모드 2: 펩타이드"),
                      "text": ("用論文中的甘胺酸豐富胜肽對接 Keap1。學習胜肽配體的處理方式，以及穿膜性和活性位可及性帶來的科學限制。",
                               "A glycine-rich peptide from a published study is docked to Keap1. You learn how peptide "
                               "ligands are handled, and the scientific limits set by cell penetration and by access to "
                               "the binding site.",
                               "論文のグリシンに富むペプチドを Keap1 にドッキングします。ペプチドリガンドの扱い方と、"
                               "膜透過性や活性部位への到達性による科学的な制約を学びます。",
                               "논문의 글리신이 풍부한 펩타이드를 Keap1에 도킹합니다. 펩타이드 리간드를 다루는 방법과, "
                               "세포막 투과성 및 활성 부위 접근성에서 오는 과학적 한계를 배웁니다."),
                      "case": "hsieh2025", "route": "/teach/hsieh2025"},
    "quick": {"title": ("快速模式", "Quick mode", "クイックモード", "빠른 모드"),
              "text": ("輸入受體和配體，選好研究目標就能開始。其他參數會依你的案例自動建議。",
                       "Enter the receptor and ligands, choose a goal and start. Every other parameter is recommended "
                       "for your case.",
                       "受容体とリガンドを入力し、研究の目的を選べば開始できます。その他のパラメーターは事例に合わせて"
                       "自動で推奨されます。",
                       "수용체와 리간드를 입력하고 연구 목표를 고르면 바로 시작할 수 있습니다. 나머지 매개변수는 사례에 "
                       "맞게 자동으로 추천됩니다."),
              "route": "/new/quick"},
    "pro": {"title": ("專業模式", "Professional mode", "プロフェッショナルモード", "전문가 모드"),
            "text": ("每個參數都可以調整，包括對接、水盒與離子、能量最小化、加熱、定壓平衡、正式模擬、拉離和傘狀採樣。"
                     "數值先從依案例給的建議值開始，你改的每個值都會即時檢查是否合理。",
                     "Every parameter can be changed, including docking, the water box and ions, minimisation, heating, "
                     "pressure equilibration, production, pulling and umbrella sampling. Values start from "
                     "recommendations for your case, and each change is checked for plausibility as you make it.",
                     "ドッキング、水ボックスとイオン、エネルギー最小化、加熱、定圧平衡化、本計算、引き離し、"
                     "アンブレラサンプリングまで、すべてのパラメーターを調整できます。値は事例に合わせた推奨値から始まり、"
                     "変更した値はその場で妥当性を確認します。",
                     "도킹, 물 상자와 이온, 에너지 최소화, 가열, 정압 평형, 본 시뮬레이션, 당김, 엄브렐라 샘플링까지 모든 "
                     "매개변수를 조정할 수 있습니다. 값은 사례에 맞춘 권장값에서 시작하며, 바꾼 값은 즉시 타당성을 "
                     "검사합니다."),
            "route": "/new/pro"},
}

# ------------------------------------------------------------------------------------------- teaching cases
TEACHING = {
    "hsieh2024": {
        "title": ("多配體同時對接：發酵臺灣藜芽萃取物代謝物與 NF-κB p65",
                  "Simultaneous multi-ligand docking: fermented djulis sprout metabolites on NF-κB p65",
                  "複数リガンドの同時ドッキング：発酵台湾キヌアスプラウト抽出物の代謝物と NF-κB p65",
                  "다중 리간드 동시 도킹: 발효 대만 퀴노아 새싹 추출물의 대사물과 NF-κB p65"),
        "background": (
            "PM2.5 會活化肺泡巨噬細胞的 NF-κB 發炎路徑。論文用發酵臺灣藜芽的水萃物處理 MH-S 細胞，發炎指標下降。"
            "作者以 LC-MS/MS 找出萃取物中含量最高的六個代謝物，再用 AutoDock Vina 把六個分子同時放進 p65 次單元的"
            "同一個搜尋區，得到總結合能 −13.86 kcal mol⁻¹ 與 24 個氫鍵。這個案例要回答兩個問題。同時對接的分數代表什麼？"
            "複合物動起來以後，這些分子還留在口袋裡嗎？",
            "PM2.5 activates the NF-κB inflammatory pathway in alveolar macrophages. In the study, a water extract of "
            "fermented djulis sprouts lowered inflammatory markers in MH-S cells. LC-MS/MS identified the six most "
            "abundant metabolites, and AutoDock Vina placed all six together in one search box on the p65 subunit. The "
            "collective score was −13.86 kcal mol⁻¹ with 24 hydrogen bonds. This case asks two questions. What does a "
            "simultaneous-docking score mean? And do the molecules stay in the pocket once the complex starts to move?",
            "PM2.5 は肺胞マクロファージの NF-κB 炎症経路を活性化します。論文では、発酵させた台湾キヌア（djulis）"
            "スプラウトの水抽出物で MH-S 細胞を処理し、炎症マーカーが低下しました。LC-MS/MS で抽出物中に最も多い "
            "6 種類の代謝物を同定し、AutoDock Vina で 6 分子を p65 サブユニットの同じ探索領域に同時に配置しました。"
            "合計の結合エネルギーは −13.86 kcal mol⁻¹、水素結合は 24 本でした。この事例では二つの問いを扱います。"
            "同時ドッキングのスコアは何を意味するのでしょうか。複合体が動き出した後も、分子はポケットにとどまるのでしょうか。",
            "PM2.5는 폐포 대식세포의 NF-κB 염증 경로를 활성화합니다. 논문에서는 발효한 대만 퀴노아(djulis) 새싹의 물 "
            "추출물로 MH-S 세포를 처리했고 염증 지표가 낮아졌습니다. LC-MS/MS로 추출물에서 가장 많은 대사물 6종을 "
            "확인한 뒤, AutoDock Vina로 6개 분자를 p65 소단위의 같은 탐색 영역에 동시에 배치했습니다. 총 결합 에너지는 "
            "−13.86 kcal mol⁻¹, 수소 결합은 24개였습니다. 이 사례는 두 가지 질문을 다룹니다. 동시 도킹 점수는 무엇을 "
            "뜻할까요? 복합체가 움직이기 시작한 뒤에도 분자들이 포켓에 남아 있을까요?"),
        "objectives": [
            ("理解各自對接和同時對接回答的是不同的問題。",
             "Understand that independent and simultaneous docking answer different questions.",
             "個別ドッキングと同時ドッキングでは、答える問いが違うことを理解します。",
             "개별 도킹과 동시 도킹이 서로 다른 질문에 답한다는 것을 이해합니다."),
            ("先檢查結構本身，看 PDB 編號、物種、解析度與搜尋區是否和論文描述一致。",
             "Check the structure itself first. Do the identifier, species, resolution and search box match what the "
             "paper describes?",
             "まず構造そのものを確認します。PDB 番号、生物種、分解能、探索領域が論文の記述と合っているかを見ます。",
             "먼저 구조 자체를 확인합니다. PDB 번호, 생물종, 분해능, 탐색 영역이 논문 설명과 맞는지 봅니다."),
            ("用分子動力學比較只有蛋白和六配體複合物兩個系統的均方根偏差（RMSD）、均方根波動（RMSF）與接觸頻率。",
             "Use molecular dynamics to compare the root-mean-square deviation (RMSD), root-mean-square fluctuation "
             "(RMSF) and contact frequencies of the protein alone and of the six-ligand complex.",
             "分子動力学で、タンパク質のみの系と 6 リガンド複合体について、二乗平均平方根偏差（RMSD）、"
             "二乗平均平方根揺らぎ（RMSF）、接触頻度を比べます。",
             "분자동역학으로 단백질만 있는 시스템과 6-리간드 복합체의 평균 제곱근 편차(RMSD), 평균 제곱근 요동(RMSF), "
             "접촉 빈도를 비교합니다."),
            ("判斷對接分數和動態穩定性，哪一個能支持論文的結論。",
             "Judge whether the docking score or the dynamic stability supports the conclusion.",
             "ドッキングスコアと動的な安定性のどちらが結論を支えるかを判断します。",
             "도킹 점수와 동적 안정성 중 어느 쪽이 결론을 뒷받침하는지 판단합니다."),
        ],
        "checks": [
            ("結構可信度：論文印的 PDB 1VKF 其實是 Thermotoga 的甘油操縱子蛋白。用座標比對論文列出的 11 個氫鍵殘基，"
             "正確的 NF-κB p50 與 p65 結構是 1VKX。",
             "Structure validity: the printed PDB 1VKF is in fact a glycerol-operon protein from Thermotoga. Matching "
             "the paper's 11 hydrogen-bond residues by coordinates shows that the right NF-κB p50 and p65 structure is 1VKX.",
             "構造の信頼性：論文に印刷された PDB 1VKF は、実際には Thermotoga のグリセロールオペロンのタンパク質です。"
             "論文の 11 個の水素結合残基を座標で照合すると、正しい NF-κB p50 と p65 の構造は 1VKX です。",
             "구조 신뢰성: 논문에 인쇄된 PDB 1VKF는 실제로 Thermotoga의 글리세롤 오페론 단백질입니다. 논문의 수소 결합 "
             "잔기 11개를 좌표로 대조하면 올바른 NF-κB p50과 p65 구조는 1VKX입니다."),
            ("非蛋白分子：1VKX 含有 κB DNA。論文寫「移除非蛋白分子」，所以 DNA 鏈 C 和 D 當作排除鏈處理，並記錄在報告裡。",
             "Non-protein molecules: 1VKX contains κB DNA. The paper says non-protein molecules were removed, so DNA "
             "chains C and D are excluded and this is recorded in the report.",
             "タンパク質以外の分子：1VKX には κB DNA が含まれます。論文には「タンパク質以外の分子を除去した」とあるので、"
             "DNA の C 鎖と D 鎖は除外鎖として扱い、レポートに記録します。",
             "단백질이 아닌 분자: 1VKX에는 κB DNA가 들어 있습니다. 논문에 \"단백질이 아닌 분자를 제거했다\"고 되어 "
             "있으므로 DNA 사슬 C와 D를 제외 사슬로 처리하고 보고서에 기록합니다."),
            ("帶電狀態：在 pH 7.4 下，有機酸是羧酸根，肉鹼是兩性離子。對接分數不受電荷影響，模擬和結合能則會受影響。",
             "Charge state: at pH 7.4 the organic acids are carboxylates and carnitine is a zwitterion. The docking "
             "score ignores charge. The simulation and the binding energy do not.",
             "荷電状態：pH 7.4 では有機酸はカルボキシレート、カルニチンは両性イオンです。ドッキングスコアは電荷の"
             "影響を受けませんが、シミュレーションと結合エネルギーは影響を受けます。",
             "전하 상태: pH 7.4에서 유기산은 카복실레이트, 카르니틴은 쯔비터이온입니다. 도킹 점수는 전하의 영향을 "
             "받지 않지만 시뮬레이션과 결합 에너지는 영향을 받습니다."),
            ("同時對接的配體碰撞檢查：同一個姿勢裡配體彼此太近時，會被擋下。",
             "Clash check in a simultaneous pose: a pose is blocked when its ligands sit too close to each other.",
             "同時ドッキングでのリガンド同士の衝突チェック：同じポーズ内でリガンド同士が近すぎると、そこで止めます。",
             "동시 도킹의 리간드 충돌 검사: 같은 포즈에서 리간드끼리 너무 가까우면 진행을 막습니다."),
        ],
        "stages": [
            (("取得並檢查結構", "Fetch and check the structure", "構造を取得して確認", "구조 가져오기와 확인"),
             ("比對物種、解析度和搜尋區裡的殘基。", "Compare the species, the resolution and the residues in the box.",
              "生物種、分解能、探索領域内の残基を照合します。", "생물종, 분해능, 탐색 영역 안의 잔기를 대조합니다.")),
            (("同時對接六個代謝物", "Dock the six metabolites together", "6 種類の代謝物を同時にドッキング", "대사물 6종 동시 도킹"),
             ("課堂上預設的搜尋強度是 8。論文用 32，但六個配體同時對接時，在 RTX 4060 筆電上跑了 2 小時以上仍未完成。"
              "研究等級或專業模式可以改回 32。每個姿勢都會檢查配體之間是否碰撞。",
              "Exhaustiveness is 8 in class. The paper used 32, but docking six ligands together had not finished after "
              "more than 2 h on an RTX 4060 laptop. The research tier or professional mode restores 32. Every pose is "
              "checked for clashes between ligands.",
              "授業での探索の徹底度（exhaustiveness）は 8 です。論文は 32 を使いましたが、6 リガンドの同時ドッキングは "
              "RTX 4060 搭載のノートパソコンで 2 時間以上たっても終わりませんでした。研究レベルまたはプロフェッショナル"
              "モードでは 32 に戻せます。各ポーズでリガンド同士の衝突を確認します。",
              "수업에서 탐색 강도(exhaustiveness)는 8입니다. 논문은 32를 사용했지만, 리간드 6개를 동시에 도킹하면 "
              "RTX 4060 노트북에서 2시간이 넘도록 끝나지 않았습니다. 연구 등급이나 전문가 모드에서는 32로 되돌릴 수 "
              "있습니다. 모든 포즈에서 리간드 간 충돌을 검사합니다.")),
            (("選擇並確認姿勢", "Choose and confirm the pose", "ポーズを選んで確定", "포즈 선택과 확정"),
             ("看分數、叢集大小和接觸殘基，再決定要不要進入模擬。",
              "Look at the score, the cluster size and the contact residues, then decide whether to simulate.",
              "スコア、クラスターの大きさ、接触残基を見てから、シミュレーションに進むかを決めます。",
              "점수, 클러스터 크기, 접촉 잔기를 보고 시뮬레이션으로 넘어갈지 결정합니다.")),
            (("建模與平衡", "Build and equilibrate", "系の構築と平衡化", "시스템 구축과 평형"),
             ("加水、加鹽，再做能量最小化、加熱和定壓平衡。每個階段都有驗收標準。",
              "Add water and salt, then minimise, heat and equilibrate at constant pressure. Each stage has acceptance criteria.",
              "水と塩を加え、エネルギー最小化、加熱、定圧平衡化を行います。各段階に合格基準があります。",
              "물과 염을 넣고 에너지 최소화, 가열, 정압 평형을 진행합니다. 단계마다 합격 기준이 있습니다.")),
            (("正式模擬與分析", "Production and analysis", "本計算と解析", "본 시뮬레이션과 분석"),
             ("比較只有蛋白和複合物兩個系統，看有沒有配體離開口袋。",
              "Compare the protein alone with the complex, and check whether any ligand leaves the pocket.",
              "タンパク質のみの系と複合体を比べ、ポケットから離れるリガンドがあるかを確認します。",
              "단백질만 있는 시스템과 복합체를 비교하고, 포켓을 떠나는 리간드가 있는지 확인합니다.")),
        ],
        "discussion": [
            ("六個分子的總分 −13.86 kcal mol⁻¹，能不能直接和單一藥物的分數比較？為什麼？",
             "Can the collective −13.86 kcal mol⁻¹ for six molecules be compared directly with a single drug's score? Why?",
             "6 分子の合計スコア −13.86 kcal mol⁻¹ は、単一の薬のスコアとそのまま比べられますか。なぜですか。",
             "분자 6개의 총점 −13.86 kcal mol⁻¹을 단일 약물의 점수와 바로 비교할 수 있습니까? 그 이유는 무엇입니까?"),
            ("含量最高的焦麩胺酸（95 ppb）在模擬中穩定嗎？對生物活性來說，含量和結合能哪一個比較重要？",
             "Is pyroglutamic acid, the most abundant metabolite at 95 ppb, stable in the simulation? Which matters "
             "more for activity, abundance or affinity?",
             "最も多いピログルタミン酸（95 ppb）はシミュレーション中に安定ですか。生物活性にとって、含有量と結合の"
             "強さのどちらが重要ですか。",
             "가장 많은 피로글루탐산(95 ppb)은 시뮬레이션에서 안정합니까? 생물 활성에는 함량과 결합 세기 중 무엇이 더 "
             "중요합니까?"),
            ("如果某個配體在 2 ns 內就離開口袋，論文的結論要怎麼修正？",
             "If a ligand leaves the pocket within 2 ns, how should the paper's conclusion change?",
             "あるリガンドが 2 ns 以内にポケットを離れたら、論文の結論はどう修正すべきですか。",
             "어떤 리간드가 2 ns 안에 포켓을 떠난다면 논문의 결론을 어떻게 고쳐야 합니까?"),
        ],
    },
    "hsieh2025": {
        "title": ("胜肽配體：發酵臺灣藜胜肽 GGGGGKP 與 Keap1", "Peptide ligand: the fermented-djulis peptide GGGGGKP on Keap1",
                  "ペプチドリガンド：発酵台湾キヌア由来のペプチド GGGGGKP と Keap1",
                  "펩타이드 리간드: 발효 대만 퀴노아 유래 펩타이드 GGGGGKP와 Keap1"),
        "background": (
            "Keap1 與 Nrf2 結合，促使 Nrf2 降解。抑制 Keap1 可以活化抗氧化基因。論文從天貝式發酵的臺灣藜分離出甘胺酸"
            "豐富胜肽 GRP（Gly-Gly-Gly-Gly-Gly-Lys-Pro），它在細胞與線蟲老化模型中有抗氧化和抗老化效果。作者用分子對接"
            "得到它與 Keap1 BTB 區的結合能 −5.22 kcal mol⁻¹。胜肽配體要面對小分子沒有的問題。它能進入細胞、到達胞內的 "
            "Keap1 嗎？它真的能進入結合位嗎？",
            "Keap1 binds Nrf2 and drives its degradation, so inhibiting Keap1 switches on antioxidant genes. The study "
            "isolated the glycine-rich peptide GRP (Gly-Gly-Gly-Gly-Gly-Lys-Pro) from tempeh-like fermented djulis. It "
            "had antioxidant and anti-ageing effects in cells and in C. elegans, and docking to the Keap1 BTB domain "
            "gave −5.22 kcal mol⁻¹. A peptide raises questions a small molecule does not. Can it enter the cell and "
            "reach Keap1 in the cytosol? Can it actually get into the binding site?",
            "Keap1 は Nrf2 に結合してその分解を促します。Keap1 を阻害すると抗酸化遺伝子が働きます。論文ではテンペ風に"
            "発酵させた台湾キヌア（djulis）から、グリシンに富むペプチド GRP（Gly-Gly-Gly-Gly-Gly-Lys-Pro）を分離しました。"
            "細胞と線虫の老化モデルで抗酸化作用と抗老化作用を示し、分子ドッキングでは Keap1 の BTB ドメインとの結合"
            "エネルギーが −5.22 kcal mol⁻¹ でした。ペプチドリガンドには低分子にはない問いがあります。細胞に入り、"
            "細胞質の Keap1 まで届くのでしょうか。本当に結合部位に入れるのでしょうか。",
            "Keap1은 Nrf2와 결합해 분해를 촉진합니다. Keap1을 억제하면 항산화 유전자가 활성화됩니다. 논문에서는 템페 "
            "방식으로 발효한 대만 퀴노아(djulis)에서 글리신이 풍부한 펩타이드 GRP(Gly-Gly-Gly-Gly-Gly-Lys-Pro)를 "
            "분리했습니다. 세포와 예쁜꼬마선충 노화 모델에서 항산화와 항노화 효과를 보였고, 분자 도킹에서 Keap1 BTB "
            "도메인과의 결합 에너지는 −5.22 kcal mol⁻¹였습니다. 펩타이드 리간드에는 저분자에 없는 질문이 있습니다. "
            "세포 안으로 들어가 세포질의 Keap1에 닿을 수 있을까요? 실제로 결합 부위에 들어갈 수 있을까요?"),
        "objectives": [
            ("了解胜肽配體和小分子在力場、柔軟度、搜尋強度與模擬長度上的差異。",
             "Learn how peptide ligands differ from small molecules in force field, flexibility, search effort and "
             "simulation length.",
             "ペプチドリガンドと低分子の違いを、力場、柔軟性、探索の徹底度、シミュレーションの長さの面から学びます。",
             "펩타이드 리간드와 저분자가 힘장, 유연성, 탐색 강도, 시뮬레이션 길이에서 어떻게 다른지 배웁니다."),
            ("理解標靶在細胞內時，穿膜性是前提，也了解用序列預測穿膜性的限制。",
             "Understand why cell penetration is a prerequisite for an intracellular target, and what sequence-based "
             "prediction cannot tell you.",
             "標的が細胞内にある場合は膜透過性が前提になることと、配列からの予測の限界を理解します。",
             "표적이 세포 안에 있을 때 세포막 투과성이 전제 조건이라는 점과, 서열 기반 예측의 한계를 이해합니다."),
            ("判斷一個姿勢是嵌進結合位，還是只貼在蛋白表面。",
             "Tell a pose that sits in the binding site from one that only lies on the surface.",
             "ポーズが結合部位に入り込んでいるのか、表面に載っているだけなのかを見分けます。",
             "포즈가 결합 부위에 들어가 있는지, 표면에 붙어 있을 뿐인지 구별합니다."),
            ("分辨共價鍵和凡得瓦接觸。", "Tell covalent bonds apart from van der Waals contacts.",
             "共有結合とファンデルワールス接触を区別します。", "공유 결합과 반데르발스 접촉을 구별합니다."),
        ],
        "checks": [
            ("穿膜性（科學限制提醒）：GGGGGKP 淨電荷 +1，只有一個離胺酸，依序列預測不太可能穿膜，而 Keap1 位在細胞質。"
             "程式會提醒並提出替代設計，但不會擋下流程。",
             "Cell penetration (a scientific-limitation notice): GGGGGKP has a net charge of +1 and a single lysine, so "
             "it is predicted not to penetrate, while Keap1 is in the cytosol. The workflow flags this and suggests "
             "redesigns, but it does not stop.",
             "膜透過性（科学的な制約のお知らせ）：GGGGGKP は正味電荷 +1 でリシンは 1 つだけなので、配列からは膜を透過"
             "しにくいと予測されます。一方、Keap1 は細胞質にあります。ワークフローは注意を表示して代わりの設計を提案"
             "しますが、処理は止めません。",
             "세포막 투과성(과학적 한계 알림): GGGGGKP는 순전하가 +1이고 라이신이 하나뿐이어서, 서열로는 막을 투과하기 "
             "어렵다고 예측됩니다. Keap1은 세포질에 있습니다. 워크플로는 이를 알리고 대안 설계를 제안하지만 진행을 "
             "멈추지는 않습니다."),
            ("活性位可及性：論文的搜尋區 36 × 51 × 45 Å 比整個 BTB 區還大，等於是盲對接。程式會檢查姿勢被埋住的比例。",
             "Binding-site access: the paper's 36 × 51 × 45 Å box is larger than the whole BTB domain, so it is in "
             "effect blind docking. The workflow measures how buried the pose is.",
             "活性部位への到達性：論文の探索領域 36 × 51 × 45 Å は BTB ドメイン全体より大きく、実質的にはブラインド"
             "ドッキングです。ワークフローはポーズの埋没の割合を確認します。",
             "활성 부위 접근성: 논문의 탐색 영역 36 × 51 × 45 Å는 BTB 도메인 전체보다 커서 사실상 블라인드 도킹입니다. "
             "워크플로는 포즈가 얼마나 묻혀 있는지 측정합니다."),
            ("用詞：論文把非氫鍵的接觸稱為「covalent bonding」。對接和 Amber 力場裡沒有共價化學，這些其實是凡得瓦與"
             "疏水接觸。CDDO 與 Cys151 的結合才是共價鍵。",
             "Terminology: the paper calls the non-hydrogen-bond contacts \"covalent bonding\". Docking and the Amber "
             "force field contain no covalent chemistry, so these are van der Waals and hydrophobic contacts. CDDO's "
             "binding to Cys151 is covalent.",
             "用語：論文は水素結合以外の接触を「covalent bonding」と呼んでいます。ドッキングと Amber 力場には共有結合の"
             "化学は含まれないので、これらはファンデルワールス接触と疎水性接触です。CDDO と Cys151 の結合は共有結合です。",
             "용어: 논문은 수소 결합이 아닌 접촉을 \"covalent bonding\"이라고 부릅니다. 도킹과 Amber 힘장에는 공유 결합 "
             "화학이 없으므로 이것은 반데르발스 접촉과 소수성 접촉입니다. CDDO와 Cys151의 결합이 공유 결합입니다."),
            ("分數的不確定度：柔軟的七肽在 Vina 得到約 −5 kcal mol⁻¹，落在方法誤差內，要靠模擬中的穩定性判斷。",
             "Score uncertainty: about −5 kcal mol⁻¹ for a flexible heptapeptide is within Vina's error, so stability "
             "in the simulation decides.",
             "スコアの不確かさ：柔軟な 7 残基ペプチドで Vina のスコアが約 −5 kcal mol⁻¹ というのは手法の誤差の範囲内です。"
             "判断はシミュレーション中の安定性で行います。",
             "점수의 불확실성: 유연한 7잔기 펩타이드에서 Vina 점수 약 −5 kcal mol⁻¹은 방법의 오차 범위 안에 있습니다. "
             "판단은 시뮬레이션에서의 안정성으로 합니다."),
        ],
        "stages": [
            (("胜肽前置檢查", "Peptide pre-checks", "ペプチドの事前チェック", "펩타이드 사전 검사"),
             ("檢查穿膜性和搜尋區大小，結果寫進報告的科學限制段落。",
              "Cell penetration and box size are checked and written to the limitations section of the report.",
              "膜透過性と探索領域の大きさを確認し、結果をレポートの「科学的な制約」の節に書きます。",
              "세포막 투과성과 탐색 영역 크기를 검사하고, 결과를 보고서의 과학적 한계 항목에 씁니다.")),
            (("對接", "Docking", "ドッキング", "도킹"),
             ("胜肽會自動用搜尋強度 32 對接。", "The peptide is docked at exhaustiveness 32 automatically.",
              "ペプチドは自動的に探索の徹底度 32 でドッキングします。", "펩타이드는 자동으로 탐색 강도 32로 도킹합니다.")),
            (("姿勢可及性", "Pose access", "ポーズの到達性", "포즈 접근성"),
             ("看埋藏比例、接觸比例和到結合位的距離。", "Look at burial, contact fraction and the distance to the site.",
              "埋没の割合、接触の割合、結合部位までの距離を見ます。", "묻힘 비율, 접촉 비율, 결합 부위까지의 거리를 봅니다.")),
            (("建模與溫和平衡", "Build and gentle equilibration", "系の構築と穏やかな平衡化", "시스템 구축과 완만한 평형"),
             ("胜肽用 ff14SB 建模，約束一直保留到加熱結束。", "The peptide uses ff14SB, and restraints are kept until heating ends.",
              "ペプチドは ff14SB で構築し、拘束は加熱が終わるまで残します。",
              "펩타이드는 ff14SB로 구축하고, 구속은 가열이 끝날 때까지 유지합니다.")),
            (("正式模擬與分析", "Production and analysis", "本計算と解析", "본 시뮬레이션과 분석"),
             ("看胜肽是否留在結合位，以及哪些殘基持續接觸。",
              "Check whether the peptide stays in the site and which residues keep contact.",
              "ペプチドが結合部位にとどまるか、どの残基が接触し続けるかを確認します。",
              "펩타이드가 결합 부위에 남아 있는지, 어떤 잔기가 계속 접촉하는지 확인합니다.")),
        ],
        "discussion": [
            ("如果穿膜預測沒有通過，細胞實驗中的抗氧化效果可能來自什麼機制？",
             "If the peptide is predicted not to penetrate, what else could explain the antioxidant effect in cells?",
             "膜透過の予測が否定的なら、細胞実験での抗酸化作用はどんな仕組みによるのでしょうか。",
             "세포막 투과 예측이 부정적이라면, 세포 실험에서 본 항산화 효과는 어떤 기전에서 올 수 있습니까?"),
            ("把搜尋區縮小到 Cys151 附近重新對接，結果會有什麼改變？",
             "How do the results change when the box is narrowed to the region around Cys151?",
             "探索領域を Cys151 の周辺に絞ってドッキングし直すと、結果はどう変わりますか。",
             "탐색 영역을 Cys151 주변으로 좁혀 다시 도킹하면 결과가 어떻게 달라집니까?"),
            ("提高淨電荷的替代設計（例如 GGGKKKP）在對接和模擬中還會結合嗎？",
             "Does a redesign with a higher net charge, such as GGGKKKP, still bind in docking and simulation?",
             "正味電荷を高めた代わりの設計（例えば GGGKKKP）は、ドッキングとシミュレーションでも結合しますか。",
             "순전하를 높인 대안 설계(예: GGGKKKP)는 도킹과 시뮬레이션에서도 결합합니까?"),
        ],
    },
}


def teaching_config(case: str, *, lang: str = "en") -> dict:
    """Workflow config for a teaching case: the paper's setup plus quick-mode recommendations (classroom goal)."""
    from ..validation import CASES
    from .. import advisor
    mod = CASES[case]
    cfg = copy.deepcopy(mod.workflow_config(tier="classroom"))
    f = advisor.features_from_config(cfg)
    vals = advisor.recommended_values(f, "teaching")
    # what the paper's setup states (docking mode, exhaustiveness, padding …) stays; everything else is recommended
    for k in advisor.values_from_config(cfg):
        vals.pop(k, None)
    out = advisor.apply(vals, cfg)
    out["confirm_before_md"] = True
    out["language"] = lang
    out["gui_mode"] = f"teach:{case}"
    return out
