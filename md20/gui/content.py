"""Interface text and teaching material (bilingual, English default; D-51).  Pure Python, testable without NiceGUI.

Every string is a (zh, en) pair resolved with `t(key, lang)`.  Rules from the user's design review: no lab stamp,
no unexplained abbreviations, no "/" as a separator in interface text, generic wording (no example molecule baked in).
"""
from __future__ import annotations

import copy

from ..advisor import tx

LANG_NAMES = {"en": "English", "zh": "繁體中文"}

UI = {
    "app_title": ("MD20 分子模擬工作站", "MD20 Molecular Simulation Workstation"),
    "nav_home": ("首頁", "Home"), "nav_system": ("電腦狀態", "Computer status"), "nav_projects": ("專案", "Projects"),
    "language": ("語言", "Language"),
    "home_intro": ("從分子對接到分子動力學與結合自由能的完整流程。每一步都會檢查輸入是否合理，"
                   "自動修正的地方會說明改了什麼，需要你判斷的地方會停下來並提供選項。",
                   "A complete workflow from molecular docking to molecular dynamics and binding free energy. Every step "
                   "checks its inputs; automatic corrections are explained, and decisions that need your judgement stop "
                   "the run with clear options."),
    "choose_mode": ("選擇工作模式", "Choose a mode"),
    "recent": ("最近的流程", "Recent workflows"), "no_recent": ("尚無流程。", "No workflows yet."),
    "open": ("開啟", "Open"), "start": ("開始", "Start"),
    "create_start": ("建立並開始", "Create and start"),
    "project_name": ("專案名稱", "Project name"), "workflow_name": ("流程名稱", "Workflow name"),
    "receptor": ("受體", "Receptor"), "pdb_id": ("PDB 編號", "PDB identifier"),
    "or_upload": ("或上傳結構檔（PDB 或 mmCIF）", "or upload a structure file (PDB or mmCIF)"),
    "ph": ("pH", "pH"), "keep_hetero": ("保留的輔因子與金屬（以空格分隔的殘基名）", "Cofactors and metals to keep (residue names, space separated)"),
    "ligands": ("配體", "Ligands"),
    "ligand_help": ("每行一個配體：名稱、SMILES 或胜肽序列、選填的共結晶殘基名。胜肽請在序列前加 peptide:，例如 peptide:GGGGGKP。"
                    "SMILES 的帶電形式會直接用於對接與模擬，請依 pH 7.4 寫出。",
                    "One ligand per line: name, SMILES or peptide sequence, optional co-crystal residue name. Prefix a "
                    "peptide sequence with peptide:, e.g. peptide:GGGGGKP. The charge state written in the SMILES is "
                    "used for docking and simulation; write it for pH 7.4."),
    "site": ("結合位置（對接搜尋區）", "Binding site (docking search box)"),
    "site_residue": ("由共結晶配體定義（殘基名）", "Defined by a co-crystal ligand (residue name)"),
    "site_center": ("或中心座標 x, y, z（Å）", "or centre x, y, z (Å)"), "site_size": ("尺寸 x, y, z（Å）", "size x, y, z (Å)"),
    "site_note": ("留空則以整個蛋白為搜尋區（盲對接，可信度較低）。", "Leave empty to search the whole protein (blind docking, lower confidence)."),
    "goal": ("研究目標", "Study goal"),
    "systems": ("模擬的系統", "Systems to simulate"),
    "sys_apo": ("蛋白單獨（對照）", "Protein alone (reference)"), "sys_single": ("每個配體各自與蛋白", "Each ligand with the protein"),
    "sys_multi": ("所有配體同時與蛋白", "All ligands together with the protein"),
    "parameters": ("模擬參數", "Simulation parameters"),
    "recommended": ("建議值", "Recommended"), "reason": ("理由", "Reason"), "value": ("設定值", "Value"),
    "reset_rec": ("全部恢復建議值", "Reset all to recommended"),
    "changed": ("已修改", "changed"),
    "checks": ("合理性檢查", "Plausibility check"), "checks_ok": ("所有參數都在合理範圍內。", "All parameters are within plausible ranges."),
    "level_error": ("錯誤", "Error"), "level_warning": ("注意", "Warning"), "level_info": ("提示", "Note"),
    "use_suggestion": ("套用建議", "Apply suggestion"),
    "estimate": ("時間估計", "Time estimate"),
    "estimate_none": ("尚未執行效能測試；請到「電腦狀態」執行一次，即可依本機速度估計時間。",
                      "No benchmark yet; run one on the Computer status page to estimate the time on this computer."),
    "estimate_text": ("約 {total} 小時（分子動力學 {md} 小時，結合計算 {bind} 小時；系統約 {atoms} 個原子，本機約 {speed} ns 每天）",
                      "About {total} h (molecular dynamics {md} h, binding {bind} h; about {atoms} atoms, about {speed} ns per day here)"),
    "errors_block": ("請先修正標示為錯誤的參數。", "Fix the parameters marked as errors first."),
    "hts": ("高通量篩選（選用）", "High-throughput screening (optional)"),
    "hts_help": ("上傳化合物表格（Excel 或 CSV），系統自動下載結構、快速對接並排名；你從排名圖點選要進入正式對接與模擬的化合物。",
                 "Upload a compound table (Excel or CSV); structures are downloaded, docked quickly and ranked, and you pick "
                 "from the ranking chart which compounds go on to full docking and simulation."),
    "hts_template": ("下載範例表格", "Download the example table"),
    "hts_upload": ("上傳化合物表格", "Upload compound table"),
    "hts_manual": ("手動上傳結構（下載被阻擋時）", "Upload structures manually (when downloads are blocked)"),
    "upload_ok": ("已接受", "Accepted"), "upload_rejected": ("已拒絕", "Rejected"),
    "status": ("狀態", "Status"), "step": ("步驟", "Step"), "time": ("時間", "Time"), "message": ("訊息", "Message"),
    "run_continue": ("開始或繼續", "Start or continue"), "pause": ("暫停（在下一個區段結束時）", "Pause (at the end of the next segment)"),
    "open_report": ("開啟報告", "Open report"),
    "gates": ("閘門", "Gates"), "screening": ("篩選", "Screening"), "live": ("即時曲線", "Live curves"),
    "umbrella": ("傘狀採樣覆蓋", "Umbrella coverage"), "timeline": ("時間軸", "Timeline"), "viewer": ("3D 檢視", "3D view"),
    "poses": ("對接姿勢（★ 推薦、✔ 已選；點選一列改用該姿勢）", "Docking poses (★ recommended, ✔ selected; click a row to use that pose)"),
    "no_gates": ("目前沒有需要注意的閘門。", "No gates need attention."),
    "manual_hint": ("需要在程式外處理（處理後重新提供輸入）：", "Needs work outside the program (then provide the new input):"),
    "busy": ("流程執行中；請先暫停或等它停在閘門再做決定。", "The workflow is running; pause it or wait until it stops at a gate."),
    "teaching_mode": ("教學模式", "Teaching mode"), "paper": ("論文", "Paper"),
    "background": ("研究背景", "Background"), "objectives": ("學習目標", "Learning objectives"),
    "what_md20_shows": ("這個案例示範的科學檢查", "Scientific checks this case demonstrates"),
    "stages": ("流程與每一步的學習重點", "Workflow and what each step teaches"),
    "discussion": ("討論題", "Discussion questions"),
    "teach_params": ("本教學使用快速模式參數（依案例自動建議）", "This lesson uses quick-mode parameters (recommended for this case)"),
    "start_lesson": ("開始這個教學案例", "Start this teaching case"),
    "doctor_quick": ("快速診斷", "Quick check"), "doctor_bench": ("診斷並測試效能", "Check and benchmark"),
    "doctor_wait": ("診斷中…", "Checking…"), "doctor_bench_wait": ("診斷中，效能測試約 20 秒…", "Checking; the benchmark takes about 20 s…"),
    "confirm_md_title": ("是否進入分子動力學？", "Proceed to molecular dynamics?"),
}


def t(key: str, lang: str = "en", **fmt) -> str:
    s = tx(UI.get(key, (key, key)), lang)
    return s.format(**fmt) if fmt else s


# ------------------------------------------------------------------------------------------- modes
MODES = {
    "teach_small": {"title": ("教學模式一：多種小分子", "Teaching mode 1: several small molecules"),
                    "text": ("以論文中萃取物的六個代謝物同時對接 NF-κB p65，學習多配體對接、結構可信度與複合物穩定性。",
                             "Six extract metabolites docked together to NF-κB p65 from a published study: multi-ligand "
                             "docking, structure validity and complex stability."),
                    "case": "hsieh2024", "route": "/teach/hsieh2024"},
    "teach_peptide": {"title": ("教學模式二：胜肽", "Teaching mode 2: peptide"),
                      "text": ("以論文中的甘胺酸豐富胜肽對接 Keap1，學習胜肽配體、穿膜性與活性位可及性的科學限制。",
                               "A glycine-rich peptide docked to Keap1 from a published study: peptide ligands, cell "
                               "penetration and access to the binding site."),
                      "case": "hsieh2025", "route": "/teach/hsieh2025"},
    "quick": {"title": ("快速模式", "Quick mode"),
              "text": ("輸入受體與配體並選擇研究目標，其餘參數依你的案例自動建議，可直接開始。",
                       "Enter the receptor and ligands and choose a goal; every other parameter is recommended for your case."),
              "route": "/new/quick"},
    "pro": {"title": ("專業模式", "Professional mode"),
            "text": ("所有參數都可調整：對接、水盒與離子、能量最小化、加熱、定壓平衡、正式模擬、拉離與傘狀採樣。"
                     "系統先依案例給建議值，並即時檢查你改的值是否合理。",
                     "Every parameter is adjustable: docking, box and ions, minimisation, heating, pressure equilibration, "
                     "production, pulling and umbrella sampling. Values start from case-specific recommendations and every "
                     "change is checked for plausibility."),
            "route": "/new/pro"},
}

# ------------------------------------------------------------------------------------------- teaching cases
TEACHING = {
    "hsieh2024": {
        "title": ("多配體同時對接：發酵臺灣藜芽萃取物代謝物與 NF-κB p65", "Simultaneous multi-ligand docking: fermented djulis sprout metabolites on NF-κB p65"),
        "background": (
            "PM2.5 會活化肺泡巨噬細胞的 NF-κB 發炎路徑。論文以發酵臺灣藜芽水萃物處理 MH-S 細胞，發炎指標下降；"
            "LC-MS/MS 鑑定出萃取物中含量最高的六個代謝物，並以 AutoDock Vina 把六個分子同時放入 p65 次單元的同一搜尋區，"
            "得到總結合能 −13.86 kcal mol⁻¹ 與 24 個氫鍵。問題在於：同時對接的分數代表什麼？這些分子在動態下是否仍留在口袋？",
            "PM2.5 activates the NF-κB inflammatory pathway in alveolar macrophages. The study treated MH-S cells with a "
            "water extract of fermented djulis sprouts and saw lower inflammatory markers; LC-MS/MS identified the six most "
            "abundant metabolites, and AutoDock Vina placed all six together in one search box on the p65 subunit, giving "
            "a collective score of −13.86 kcal mol⁻¹ and 24 hydrogen bonds. The questions: what does a simultaneous-docking "
            "score mean, and do the molecules stay in the pocket once the complex moves?"),
        "objectives": [
            ("理解各自對接與同時對接回答的是不同問題。", "Understand that independent and simultaneous docking answer different questions."),
            ("學會先檢查結構本身：PDB 編號、物種、解析度與搜尋區是否對應論文描述。", "Check the structure itself first: identifier, species, resolution and whether the box matches the paper."),
            ("以分子動力學比較蛋白單獨與六配體複合物的 RMSD、RMSF 與接觸頻率。", "Compare RMSD, RMSF and contact frequencies of the protein alone and with all six ligands."),
            ("判斷對接分數與動態穩定性哪一個能支持結論。", "Judge whether the docking score or the dynamic stability supports the conclusion."),
        ],
        "checks": [
            ("結構可信度：論文印的 PDB 1VKF 其實是 Thermotoga 的甘油操縱子蛋白；以座標比對論文的 11 個氫鍵殘基，正確的 NF-κB p50與p65 結構是 1VKX。",
             "Structure validity: the printed PDB 1VKF is a Thermotoga glycerol-operon protein; matching the paper's 11 "
             "hydrogen-bond residues by coordinates identifies the NF-κB p50 and p65 structure as 1VKX."),
            ("非蛋白分子：1VKX 含 κB DNA，論文寫「移除非蛋白分子」，因此 DNA 鏈 C 與 D 以排除鏈處理並記錄在報告。",
             "Non-protein molecules: 1VKX contains κB DNA; following \"non-protein molecules removed\", chains C and D are excluded and recorded."),
            ("帶電狀態：有機酸在 pH 7.4 為羧酸根、肉鹼為兩性離子；對接分數不受電荷影響，但模擬與結合能會。",
             "Charge state: the organic acids are carboxylates and carnitine is zwitterionic at pH 7.4; docking ignores charge, simulation does not."),
            ("同時對接的配體碰撞檢查：姿勢中配體彼此過近會被擋下。", "Clash check between ligands in a simultaneous pose: ligands too close to each other are blocked."),
        ],
        "stages": [
            (("取得與檢查結構", "Fetch and check the structure"), ("比對物種、解析度與搜尋區殘基。", "Species, resolution and residues in the box.")),
            (("同時對接六個代謝物", "Dock the six metabolites together"), ("課堂預設搜尋強度 8（論文為 32：六個配體同時對接在 RTX 4060 筆電上 2 小時以上仍未完成；研究等級或專業模式可改回 32）；每個姿勢檢查配體間碰撞。",
              "Exhaustiveness 8 in class (the paper used 32: six ligands docked together did not finish in over 2 h on an RTX 4060 laptop; research tier or professional mode restores 32); every pose is checked for clashes between ligands.")),
            (("選擇姿勢並確認", "Choose and confirm the pose"), ("看分數、叢集大小與接觸殘基，再決定是否進入模擬。", "Score, cluster size and contact residues; then decide whether to simulate.")),
            (("建模與平衡", "Build and equilibrate"), ("加水、加鹽、能量最小化、加熱、定壓平衡；每階段有驗收標準。", "Water, salt, minimisation, heating and pressure equilibration, each with acceptance criteria.")),
            (("正式模擬與分析", "Production and analysis"), ("比較蛋白單獨與複合物；觀察是否有配體離開口袋。", "Protein alone versus complex; does any ligand leave the pocket?")),
        ],
        "discussion": [
            ("六個分子的總分 −13.86 kcal mol⁻¹ 能否與單一藥物的分數直接比較？為什麼？", "Can the collective −13.86 kcal mol⁻¹ be compared with a single drug's score? Why?"),
            ("含量最高的焦麩胺酸（95 ppb）在模擬中是否穩定？含量與結合能哪個對生物活性較重要？", "Is the most abundant metabolite, pyroglutamic acid (95 ppb), stable in the simulation? Which matters more for activity, abundance or affinity?"),
            ("如果某個配體在 2 ns 內離開口袋，論文的結論需要怎麼修正？", "If a ligand leaves the pocket within 2 ns, how should the paper's conclusion change?"),
        ],
    },
    "hsieh2025": {
        "title": ("胜肽配體：發酵臺灣藜胜肽 GGGGGKP 與 Keap1", "Peptide ligand: the fermented-djulis peptide GGGGGKP on Keap1"),
        "background": (
            "Keap1 與 Nrf2 結合並促使其降解；抑制 Keap1 可活化抗氧化基因。論文由天貝式發酵臺灣藜分離出甘胺酸豐富胜肽 GRP"
            "（Gly-Gly-Gly-Gly-Gly-Lys-Pro），在細胞與線蟲老化模型中具抗氧化與抗老化效果，並以分子對接得到與 Keap1 BTB 區的"
            "結合能 −5.22 kcal mol⁻¹。胜肽配體的科學問題比小分子多：它能否進入細胞到達胞內的 Keap1？它能否真正進入結合位？",
            "Keap1 binds Nrf2 and drives its degradation; inhibiting Keap1 switches on antioxidant genes. The study isolated "
            "the glycine-rich peptide GRP (Gly-Gly-Gly-Gly-Gly-Lys-Pro) from tempeh-like fermented djulis, showed antioxidant "
            "and anti-ageing effects in cells and C. elegans, and docked it to the Keap1 BTB domain at −5.22 kcal mol⁻¹. "
            "A peptide raises questions a small molecule does not: can it enter the cell to reach cytosolic Keap1, and can "
            "it actually get into the binding site?"),
        "objectives": [
            ("學會胜肽配體與小分子的差異：力場、柔軟度、搜尋強度與模擬長度。", "How peptide ligands differ from small molecules: force field, flexibility, search effort and simulation length."),
            ("理解穿膜性是胞內標靶的前提，以及序列預測的限制。", "Why cell penetration is a prerequisite for an intracellular target, and the limits of sequence-based prediction."),
            ("判斷姿勢是嵌入結合位還是貼在表面。", "Tell a pose that sits in the binding site from one that lies on the surface."),
            ("區分「共價鍵」與凡得瓦接觸。", "Distinguish covalent bonds from van der Waals contacts."),
        ],
        "checks": [
            ("穿膜性（科學限制提醒）：GGGGGKP 淨電荷 +1、只有一個離胺酸，序列預測不太可能穿膜；Keap1 在細胞質，系統會提醒並提出替代設計，但不阻擋流程。",
             "Cell penetration (scientific-limitation notice): GGGGGKP has a net charge of +1 and a single lysine and is "
             "predicted not to penetrate; Keap1 is cytosolic. The workflow flags this and suggests redesigns, but does not stop."),
            ("活性位可及性：論文的搜尋區 36 × 51 × 45 Å 比整個 BTB 區還大，等同盲對接；系統會檢查姿勢的埋藏比例。",
             "Binding-site access: the paper's 36 × 51 × 45 Å box is larger than the whole BTB domain, effectively blind "
             "docking; the workflow measures how buried the pose is."),
            ("用詞：論文稱非氫鍵接觸為「covalent bonding」，對接與 Amber 力場沒有共價化學，這些是凡得瓦與疏水接觸；CDDO 與 Cys151 的結合才是共價。",
             "Terminology: the paper calls the non-hydrogen-bond contacts \"covalent bonding\"; docking and the Amber force "
             "field have no covalent chemistry, these are van der Waals and hydrophobic contacts. CDDO's binding to Cys151 is covalent."),
            ("分數的不確定度：柔軟的七肽在 Vina 約 −5 kcal mol⁻¹，落在方法誤差內，需以模擬穩定性判斷。",
             "Score uncertainty: about −5 kcal mol⁻¹ for a flexible heptapeptide is within Vina's error; simulation stability decides."),
        ],
        "stages": [
            (("胜肽前置檢查", "Peptide pre-checks"), ("穿膜性與搜尋區大小；結果寫入報告的科學限制段落。", "Cell penetration and box size; written to the report's limitations section.")),
            (("對接", "Docking"), ("胜肽自動以搜尋強度 32 對接。", "The peptide is docked at exhaustiveness 32.")),
            (("姿勢可及性", "Pose access"), ("埋藏比例、接觸比例與到結合位的距離。", "Burial, contact fraction and distance to the site.")),
            (("建模與溫和平衡", "Build and gentle equilibration"), ("胜肽以 ff14SB 建模，約束保留到加熱結束。", "The peptide uses ff14SB; restraints are held through heating.")),
            (("正式模擬與分析", "Production and analysis"), ("胜肽是否留在結合位、哪些殘基持續接觸。", "Does the peptide stay, and which residues keep contact?")),
        ],
        "discussion": [
            ("如果穿膜預測不通過，細胞實驗的抗氧化效果可能來自什麼機制？", "If the peptide is predicted not to penetrate, what else could explain the antioxidant effect in cells?"),
            ("把搜尋區縮小到 Cys151 附近重新對接，結果會如何改變？", "How do the results change when the box is reduced to the region around Cys151?"),
            ("提高淨電荷的替代設計（例如 GGGKKKP）在對接與模擬中是否仍結合？", "Does a redesign with a higher net charge (e.g. GGGKKKP) still bind in docking and simulation?"),
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
