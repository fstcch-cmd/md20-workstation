"""Titles, general explanations and option labels for every gate, in four languages (D-55, D-74).

Gate explanations are written in Chinese where they are created (the decision log stays Chinese, CLAUDE.md).  Outside
the Chinese interface a card shows the translated title and the general explanation of that gate kind from this table;
the recorded Chinese detail (with the run's numbers) stays available under "Details".

Structure:
    GATES[name]    = (title, general)        each a (zh, en, ja, ko) tuple
    OPTIONS[key]   = (en, ja, ko)            the key is the Chinese option text itself; it is stored in config files
                                             and the DecisionLog, so it is never changed and is shown as is in Chinese
    PREFIX         = [(prefix, (en, ja, ko))] for options that carry a value after a fixed prefix
Options are translated by exact text or by prefix; anything not listed is shown as written.
"""
from __future__ import annotations

from ..i18n import pick

T4 = tuple[str, str, str, str]

# name (or name prefix) → (title, general explanation), each (zh, en, ja, ko)
GATES: dict[str, tuple[T4, T4]] = {
    "resolution": (
        ("解析度", "Resolution", "分解能", "해상도"),
        ("晶體結構的解析度偏低，口袋裡的原子位置不確定。",
         "The crystal structure has low resolution, so atom positions in the pocket are uncertain.",
         "結晶構造の分解能が低いため、ポケット内の原子位置が不確かです。",
         "결정 구조의 해상도가 낮아 포켓 안의 원자 위치가 불확실합니다.")),
    "R-free": (
        ("R-free", "R-free", "R-free", "R-free"),
        ("結構的 R-free 偏高，表示模型和實驗數據吻合得不好。",
         "The structure has a high R-free, which means the model fits the experimental data poorly.",
         "構造の R-free が高く、モデルが実験データとよく合っていません。",
         "구조의 R-free가 높습니다. 모델이 실험 데이터와 잘 맞지 않는다는 뜻입니다.")),
    "ligand occupancy": (
        ("配體佔有率", "Ligand occupancy", "リガンドの占有率", "리간드 점유율"),
        ("共結晶配體在晶體中只有部分存在，它的姿勢不確定。",
         "The co-crystal ligand is only partly present in the crystal, so its pose is uncertain.",
         "共結晶リガンドが結晶中に部分的にしか存在しないため、そのポーズは不確かです。",
         "공결정 리간드가 결정 안에 일부만 존재하므로 그 포즈가 불확실합니다.")),
    "pocket occupancy": (
        ("口袋佔有率", "Pocket occupancy", "ポケットの占有率", "포켓 점유율"),
        ("口袋原子有部分佔有率或替代位置。",
         "Some pocket atoms have partial occupancy or alternate positions.",
         "ポケットの原子に部分占有や別位置があります。",
         "포켓 원자 일부에 부분 점유율이나 대체 위치가 있습니다.")),
    "pocket B-factor": (
        ("口袋 B 因子", "Pocket B-factors", "ポケットの B 因子", "포켓 B 인자"),
        ("口袋原子的 B 因子偏高，排列不規則，口袋形狀不確定。",
         "Pocket atoms have high B-factors and are poorly ordered, so the pocket shape is uncertain.",
         "ポケットの原子の B 因子が高く秩序が低いため、ポケットの形が不確かです。",
         "포켓 원자의 B 인자가 높고 배열이 불규칙하여 포켓 모양이 불확실합니다.")),
    "experiment": (
        ("實驗方法", "Experimental method", "実験手法", "실험 방법"),
        ("這個結構不是用 X 光晶體學解出的，請確認它適合分子對接。",
         "The structure was not solved by X-ray crystallography. Check that it is suitable for docking.",
         "この構造は X 線結晶構造解析で決定されたものではありません。分子ドッキングに使えるか確認してください。",
         "이 구조는 X선 결정학으로 풀린 것이 아닙니다. 분자 도킹에 적합한지 확인하십시오.")),
    "missing loops (short)": (
        ("短缺口", "Short missing segments", "短い欠損部位", "짧은 결손 구간"),
        ("主鏈缺了幾小段。沒有 SEQRES 時程式無法知道要補哪些殘基，兩端也會被一條錯誤的鍵接起來。",
         "Short stretches of the backbone are missing. Without SEQRES the program cannot tell which residues to rebuild, "
         "and the two ends would be joined by a false bond.",
         "主鎖の短い区間が欠けています。SEQRES がないと、どの残基を補えばよいか判断できず、両端が誤った結合でつながってしまいます。",
         "주사슬의 짧은 구간이 빠져 있습니다. SEQRES가 없으면 어떤 잔기를 채울지 알 수 없고, 양 끝이 잘못된 결합으로 이어집니다.")),
    "missing loops (long)": (
        ("長缺口", "Long missing loops", "長い欠損ループ", "긴 결손 루프"),
        ("缺了較長的 loop。自動補建的長 loop 不可靠，可能扭曲口袋的動態。",
         "Long loops are missing. Long loops rebuilt automatically are unreliable and can distort the pocket dynamics.",
         "長いループが欠けています。自動で補った長いループは信頼性が低く、ポケットの動きをゆがめることがあります。",
         "긴 루프가 빠져 있습니다. 자동으로 채운 긴 루프는 신뢰하기 어렵고 포켓의 동역학을 왜곡할 수 있습니다.")),
    "unfilled chain breaks": (
        ("未補的主鏈斷裂", "Unfilled chain breaks", "未修復の主鎖切断", "채워지지 않은 주사슬 끊김"),
        ("整理後主鏈仍有斷裂，建模時斷口兩端會被一條錯誤的鍵接起來。",
         "Breaks remain in the backbone after repair. Building would join their ends with a false bond.",
         "修復後も主鎖に切断が残っています。このまま系を作ると、切れ目の両端が誤った結合でつながります。",
         "정리 후에도 주사슬에 끊김이 남아 있습니다. 이대로 계를 만들면 끊긴 양 끝이 잘못된 결합으로 이어집니다.")),
    "chain breaks capped": (
        ("斷鏈已截斷", "Chain breaks capped", "切断部位をキャップ済み", "끊김 부위 캡 처리됨"),
        ("斷裂處已加上中性的 ACE 和 NME 端帽，斷點後的片段各自成為一條鏈。",
         "Chain breaks were capped with neutral ACE and NME groups, and the segment after each break became its own chain.",
         "切断部位に中性の ACE と NME をキャップとして付け、切断後の区間はそれぞれ別の鎖にしました。",
         "끊긴 곳에 중성 ACE와 NME 캡을 붙였고, 끊김 뒤의 구간은 각각 별도의 사슬이 되었습니다.")),
    "hetero groups": (
        ("非蛋白分子", "Non-protein molecules", "タンパク質以外の分子", "단백질이 아닌 분자"),
        ("結構裡有非蛋白分子，可能是配體、緩衝液成分或輔因子。請選擇要保留哪些。",
         "The structure contains non-protein molecules, such as possible ligands, buffer components or cofactors. "
         "Choose which to keep.",
         "構造にタンパク質以外の分子（リガンド、緩衝液成分、補因子の可能性）があります。残すものを選んでください。",
         "구조에 단백질이 아닌 분자가 있습니다. 리간드, 완충액 성분 또는 보조인자일 수 있습니다. 남길 것을 선택하십시오.")),
    "unknown residues": (
        ("未知殘基", "Unknown residues", "不明な残基", "알 수 없는 잔기"),
        ("有殘基對不到標準殘基，例如修飾殘基或共價配體，它們沒有力場參數。",
         "Some residues have no standard mapping, for example modified residues or covalent ligands. "
         "They have no force-field parameters.",
         "標準残基に対応しない残基（修飾残基や共有結合リガンドなど）があり、力場パラメータがありません。",
         "표준 잔기에 대응하지 않는 잔기가 있습니다. 변형 잔기나 공유 결합 리간드 등이며 역장 매개변수가 없습니다.")),
    "duplicate atom names": (
        ("重複原子名", "Duplicate atom names", "原子名の重複", "중복된 원자 이름"),
        ("某個殘基裡有重複的原子名，拓撲無法對應。",
         "A residue contains duplicate atom names, so the topology cannot be matched.",
         "ある残基に同じ原子名が重複しているため、トポロジーを対応づけられません。",
         "한 잔기에 같은 원자 이름이 중복되어 있어 토폴로지를 맞출 수 없습니다.")),
    "nonstandard residues": (
        ("非標準殘基", "Non-standard residues", "非標準残基", "비표준 잔기"),
        ("非標準殘基已換成對應的標準殘基。",
         "Non-standard residues were replaced by their standard equivalents.",
         "非標準残基を対応する標準残基に置き換えました。",
         "비표준 잔기를 대응하는 표준 잔기로 바꾸었습니다.")),
    "numbering jumps": (
        ("編號跳號", "Numbering jumps", "番号の飛び", "번호 건너뜀"),
        ("殘基編號有跳號，但主鏈是連續的。這是編號習慣，不是缺殘基。",
         "Residue numbers jump while the backbone is continuous. This is a numbering convention, and no residues are missing.",
         "残基番号が飛んでいますが、主鎖は連続しています。番号の付け方の問題で、残基の欠損ではありません。",
         "잔기 번호가 건너뛰지만 주사슬은 이어져 있습니다. 번호 매기는 방식의 문제이며 빠진 잔기는 없습니다.")),
    "crystal waters": (
        ("結晶水", "Crystal waters", "結晶水", "결정수"),
        ("結晶水已移除，加溶劑時會重新加水。",
         "Crystal waters were removed. Water is added again during solvation.",
         "結晶水は取り除きました。溶媒和のときに水を改めて加えます。",
         "결정수를 제거했습니다. 용매화 단계에서 물을 다시 넣습니다.")),
    "buffer / additives": (
        ("結晶添加物", "Crystallisation additives", "結晶化添加物", "결정화 첨가물"),
        ("緩衝液成分、甘油等添加物已移除。",
         "Buffer components, glycerol and similar additives were removed.",
         "緩衝液成分やグリセロールなどの添加物を取り除きました。",
         "완충액 성분과 글리세롤 같은 첨가물을 제거했습니다.")),
    "cofactors kept": (
        ("保留的輔因子", "Cofactors kept", "残した補因子", "남긴 보조인자"),
        ("列出的輔因子會留在受體中。",
         "The listed cofactors are kept in the receptor.",
         "一覧の補因子は受容体に残します。",
         "목록의 보조인자는 수용체에 남깁니다.")),
    "co-crystal ligand": (
        ("共結晶配體", "Co-crystal ligand", "共結晶リガンド", "공결정 리간드"),
        ("共結晶配體交給配體流程處理，它的座標當作一個姿勢使用。",
         "The co-crystal ligand is handled by the ligand workflow, and its coordinates are used as a pose.",
         "共結晶リガンドはリガンドのワークフローで扱い、その座標を一つのポーズとして使います。",
         "공결정 리간드는 리간드 워크플로에서 처리하며 그 좌표를 하나의 포즈로 사용합니다.")),
    "existing hydrogens": (
        ("既有氫原子", "Existing hydrogens", "既存の水素原子", "기존 수소 원자"),
        ("檔案裡原有的氫原子已移除，再依選定的 pH 重新加上。",
         "Hydrogens in the file were removed and placed again for the chosen pH.",
         "ファイルにあった水素原子を取り除き、選んだ pH に合わせて付け直しました。",
         "파일에 있던 수소 원자를 제거하고 선택한 pH에 맞춰 다시 붙였습니다.")),
    "altloc": (
        ("替代構象", "Alternate locations", "別位置（altloc）", "대체 위치(altloc)"),
        ("有替代位置的原子只保留佔有率最高的位置。",
         "Atoms with alternate locations were reduced to the most occupied position.",
         "別位置を持つ原子は、占有率が最も高い位置だけを残しました。",
         "대체 위치가 있는 원자는 점유율이 가장 높은 위치만 남겼습니다.")),
    "insertion code": (
        ("插入碼", "Insertion codes", "挿入コード", "삽입 코드"),
        ("有插入碼的殘基已重新編號，原本的編號記在對照表裡。",
         "Residues with insertion codes are renumbered. The original numbering is kept in the mapping.",
         "挿入コードのある残基は番号を付け直しました。元の番号は対応表に残しています。",
         "삽입 코드가 있는 잔기는 번호를 다시 매겼습니다. 원래 번호는 대응표에 남아 있습니다.")),
    "element column": (
        ("元素欄位", "Element column", "元素欄", "원소 열"),
        ("缺少的元素符號依原子名推斷。",
         "Missing element symbols were inferred from atom names.",
         "欠けている元素記号は原子名から推定しました。",
         "빠진 원소 기호는 원자 이름으로부터 추정했습니다.")),
    "atom serial": (
        ("原子序號", "Atom serial numbers", "原子通し番号", "원자 일련번호"),
        ("原子序號超過 PDB 格式的上限，程式內部改用 mmCIF。",
         "Atom serial numbers exceed the PDB limit, so mmCIF is used internally.",
         "原子番号が PDB 形式の上限を超えるため、内部では mmCIF を使います。",
         "원자 일련번호가 PDB 형식의 한도를 넘어 내부에서는 mmCIF를 사용합니다.")),
    "protein": (
        ("蛋白", "Protein", "タンパク質", "단백질"),
        ("找不到蛋白的 Cα 原子，這不是蛋白結構檔。",
         "No protein Cα atoms were found. This is not a protein structure file.",
         "タンパク質の Cα 原子が見つかりません。タンパク質の構造ファイルではありません。",
         "단백질 Cα 원자를 찾을 수 없습니다. 단백질 구조 파일이 아닙니다.")),
    "metal charges": (
        ("金屬電荷", "Metal-site charges", "金属サイトの電荷", "금속 부위 전하"),
        ("擬合出的金屬位點電荷和力場不一致。",
         "The fitted metal-site charges do not agree with the force field.",
         "フィットした金属サイトの電荷が力場と整合しません。",
         "피팅한 금속 부위 전하가 역장과 맞지 않습니다.")),
    "metal": (
        ("金屬位點", "Metal site", "金属サイト", "금속 부위"),
        ("口袋內或附近有金屬離子，需要選一種模型。可以用鍵結模型、加約束的非鍵結模型，或移除。",
         "A metal ion in or near the pocket needs a model. It can be bonded, non-bonded with restraints, or removed.",
         "ポケット内か近くに金属イオンがあり、モデルを選ぶ必要があります。結合モデル、拘束付きの非結合モデル、または除去から選びます。",
         "포켓 안이나 근처에 금속 이온이 있어 모델을 정해야 합니다. 결합 모델, 구속을 건 비결합 모델, 또는 제거 중에서 고릅니다.")),
    "multi-ligand geometry": (
        ("多配體幾何", "Multi-ligand geometry", "複数リガンドの幾何", "다중 리간드 기하"),
        ("選定的姿勢裡有兩個分子重疊，或有一根鍵穿過環（穿環）。能量最小化修不好這種情況，必須排除一個配體或改選另一組聯合姿勢。",
         "In the chosen pose two molecules overlap, or a bond threads through a ring (ring piercing). Minimisation cannot "
         "repair this, so exclude one ligand or choose another joint pose.",
         "選んだポーズで二つの分子が重なっているか、結合が環を貫いています（環貫通）。エネルギー最小化では直せないため、"
         "リガンドを一つ除くか、別の組み合わせポーズを選んでください。",
         "선택한 포즈에서 두 분자가 겹치거나 결합이 고리를 관통합니다(고리 관통). 에너지 최소화로는 고칠 수 없으므로 "
         "리간드 하나를 제외하거나 다른 결합 포즈 조합을 선택하십시오.")),
    "ligand geometry (with hydrogens)": (
        ("配體幾何（含氫）", "Ligand geometry (with hydrogens)", "リガンドの幾何（水素付き）", "리간드 기하(수소 포함)"),
        ("加上全部氫原子後，有配體和別的分子重疊或穿過它的環。輕微的情況會自動推開。",
         "After all hydrogens were added, a ligand overlaps another molecule or threads through one of its rings. "
         "Small cases are nudged apart automatically.",
         "すべての水素原子を付けた後、リガンドが別の分子と重なるか、その環を貫いています。軽い場合は自動で少しずらします。",
         "모든 수소 원자를 붙인 뒤 리간드가 다른 분자와 겹치거나 그 고리를 관통합니다. 가벼운 경우는 자동으로 조금 떼어 놓습니다.")),
    "ligand force-field consistency": (
        ("配體力場一致性", "Ligand force-field consistency", "リガンド力場の一貫性", "리간드 역장 일관성"),
        ("同一個系統裡的配體應使用同一套力場和電荷模型，彼此的作用才能比較。",
         "Ligands in one system should share one force field and charge model, so that their interactions can be compared.",
         "同じ系のリガンドは同じ力場と電荷モデルを使うべきです。そうでないと相互作用を比べられません。",
         "한 계에 있는 리간드는 같은 역장과 전하 모델을 써야 상호작용을 비교할 수 있습니다.")),
    "ligand–metal coordination": (
        ("配體配位金屬", "Ligand coordinates a metal", "リガンドが金属に配位", "리간드의 금속 배위"),
        ("對接出的配體直接和金屬結合。力場裡沒有配體與金屬之間的鍵，沒有專用模型時這種結合模式不可靠。",
         "The docked ligand binds a metal directly. The force field has no ligand–metal bond, so this binding mode is "
         "not reliable without a dedicated model.",
         "ドッキングしたリガンドが金属に直接結合しています。力場にはリガンドと金属の結合がないため、専用のモデルなしではこの結合様式は信頼できません。",
         "도킹된 리간드가 금속에 직접 결합합니다. 역장에는 리간드와 금속 사이의 결합이 없으므로 전용 모델 없이는 이 결합 방식을 신뢰할 수 없습니다.")),
    "CPP": (
        ("穿膜性", "Cell penetration", "膜透過性", "세포 투과성"),
        ("科學限制提醒。標的在細胞內時，胜肽必須能穿過細胞膜。這則提醒不會中止流程。",
         "Scientific limitation notice. For an intracellular target the peptide must cross the cell membrane. "
         "This notice does not stop the workflow.",
         "科学的な限界のお知らせです。標的が細胞内にある場合、ペプチドは細胞膜を通過できる必要があります。このお知らせでワークフローは止まりません。",
         "과학적 한계 안내입니다. 표적이 세포 안에 있으면 펩타이드가 세포막을 통과해야 합니다. 이 안내 때문에 워크플로가 멈추지는 않습니다.")),
    "peptide pocket access": (
        ("活性位可及性", "Binding-site access", "活性部位への到達", "결합 부위 접근성"),
        ("科學限制提醒。請看胜肽能否放進搜尋區，以及選定的姿勢是否真的進入活性位。這則提醒不會中止流程。",
         "Scientific limitation notice. It covers whether the peptide fits the search region and whether the chosen pose "
         "actually enters the site. This notice does not stop the workflow.",
         "科学的な限界のお知らせです。ペプチドが探索領域に収まるか、選んだポーズが実際に活性部位に入っているかを確認してください。"
         "このお知らせでワークフローは止まりません。",
         "과학적 한계 안내입니다. 펩타이드가 탐색 영역에 들어가는지, 선택한 포즈가 실제로 결합 부위에 들어가는지 확인하십시오. "
         "이 안내 때문에 워크플로가 멈추지는 않습니다.")),
    "peptide detected": (
        ("偵測到胜肽", "Peptide detected", "ペプチドを検出", "펩타이드 감지됨"),
        ("這個配體看起來是胜肽。胜肽要用蛋白力場，並自成一條鏈。",
         "The ligand looks like a peptide. Peptides need the protein force field and their own chain.",
         "このリガンドはペプチドのようです。ペプチドにはタンパク質の力場と独立した鎖が必要です。",
         "이 리간드는 펩타이드로 보입니다. 펩타이드에는 단백질 역장과 별도의 사슬이 필요합니다.")),
    "peptide 3D": (
        ("胜肽 3D 結構", "Peptide 3D structure", "ペプチドの 3D 構造", "펩타이드 3D 구조"),
        ("胜肽姿勢沒有可用的 3D 結構。",
         "There is no usable 3D structure for the peptide pose.",
         "ペプチドのポーズに使える 3D 構造がありません。",
         "펩타이드 포즈에 쓸 수 있는 3D 구조가 없습니다.")),
    "peptide pose mapping": (
        ("胜肽姿勢對應", "Peptide pose mapping", "ペプチドのポーズの対応づけ", "펩타이드 포즈 대응"),
        ("對接出的胜肽姿勢對不上它的序列。",
         "The docked peptide pose could not be mapped to the sequence.",
         "ドッキングしたペプチドのポーズを配列に対応づけられませんでした。",
         "도킹된 펩타이드 포즈를 서열에 대응시킬 수 없었습니다.")),
    "peptide topology": (
        ("胜肽拓撲", "Peptide topology", "ペプチドのトポロジー", "펩타이드 토폴로지"),
        ("胜肽的拓撲和序列不符。",
         "The peptide topology does not match its sequence.",
         "ペプチドのトポロジーが配列と一致しません。",
         "펩타이드 토폴로지가 서열과 일치하지 않습니다.")),
    "peptide chain count": (
        ("胜肽鏈數", "Peptide chain count", "ペプチドの鎖の数", "펩타이드 사슬 수"),
        ("胜肽必須剛好是一條鏈。",
         "The peptide must form exactly one chain.",
         "ペプチドはちょうど一本の鎖でなければなりません。",
         "펩타이드는 정확히 사슬 하나여야 합니다.")),
    "peptide–receptor bond": (
        ("胜肽與受體鍵結", "Peptide–receptor bond", "ペプチドと受容体の結合", "펩타이드와 수용체의 결합"),
        ("胜肽和受體之間被建了一根鍵，這絕不應該發生。",
         "A bond was created between the peptide and the receptor. This must never happen.",
         "ペプチドと受容体の間に結合が作られました。これは起きてはいけないことです。",
         "펩타이드와 수용체 사이에 결합이 만들어졌습니다. 절대 일어나서는 안 되는 일입니다.")),
    "termini": (
        ("末端", "Termini", "末端", "말단"),
        ("胜肽的末端已設定。",
         "The peptide termini were set.",
         "ペプチドの末端を設定しました。",
         "펩타이드 말단을 설정했습니다.")),
    "pose mapping": (
        ("姿勢對應", "Pose mapping", "ポーズの対応づけ", "포즈 대응"),
        ("對接出的姿勢對不上參考分子。",
         "The docked pose could not be mapped onto the reference molecule.",
         "ドッキングしたポーズを参照分子に対応づけられませんでした。",
         "도킹된 포즈를 기준 분자에 대응시킬 수 없었습니다.")),
    "3D": (
        ("3D 結構", "3D structure", "3D 構造", "3D 구조"),
        ("無法為配體產生 3D 構形。",
         "A 3D conformer could not be generated for the ligand.",
         "リガンドの 3D 配座を生成できませんでした。",
         "리간드의 3D 형태를 만들 수 없었습니다.")),
    "formal charge": (
        ("形式電荷", "Formal charge", "形式電荷", "형식 전하"),
        ("以 pH 7.4 來說，配體的形式電荷不尋常，請檢查質子化狀態。",
         "The ligand's formal charge is unusual for pH 7.4. Check its protonation.",
         "pH 7.4 としてはリガンドの形式電荷が珍しい値です。プロトン化状態を確認してください。",
         "pH 7.4 기준으로 리간드의 형식 전하가 이례적입니다. 양성자화 상태를 확인하십시오.")),
    "charge sum": (
        ("電荷總和", "Charge sum", "電荷の合計", "전하 합계"),
        ("部分電荷加起來不等於形式電荷。",
         "The partial charges do not add up to the formal charge.",
         "部分電荷の合計が形式電荷と一致しません。",
         "부분 전하의 합이 형식 전하와 같지 않습니다.")),
    "total charge": (
        ("系統總電荷", "Total charge", "系の全電荷", "계의 총 전하"),
        ("系統的總電荷不是整數，或沒有被中和。",
         "The total charge of the system is not an integer or is not neutralised.",
         "系の全電荷が整数でないか、中和されていません。",
         "계의 총 전하가 정수가 아니거나 중화되지 않았습니다.")),
    "parameters": (
        ("參數化", "Parameterisation", "パラメータ化", "매개변수화"),
        ("配體的每一條參數化途徑都失敗了。",
         "No parameterisation route succeeded for the ligand.",
         "リガンドのパラメータ化はどの方法でも成功しませんでした。",
         "리간드의 매개변수화가 어느 경로로도 성공하지 못했습니다.")),
    "ligand": (
        ("配體", "Ligand", "リガンド", "리간드"),
        ("配體無法參數化。",
         "The ligand could not be parameterised.",
         "リガンドをパラメータ化できませんでした。",
         "리간드를 매개변수화할 수 없었습니다.")),
    "force field templates": (
        ("力場樣板", "Force-field templates", "力場テンプレート", "역장 템플릿"),
        ("有殘基沒有力場樣板，金屬或輔因子常有這個情況。",
         "A residue has no force-field template. This is common for metals and cofactors.",
         "力場テンプレートのない残基があります。金属や補因子でよく起こります。",
         "역장 템플릿이 없는 잔기가 있습니다. 금속이나 보조인자에서 흔히 생깁니다.")),
    "force field": (
        ("力場", "Force field", "力場", "역장"),
        ("無法套用力場。",
         "The force field could not be applied.",
         "力場を適用できませんでした。",
         "역장을 적용할 수 없었습니다.")),
    "vacuum smoke test": (
        ("真空測試", "Vacuum smoke test", "真空中の簡易テスト", "진공 간이 시험"),
        ("配體在真空中做短暫能量最小化時失敗，表示參數或幾何有問題。",
         "A short vacuum minimisation of the ligand failed, which points to bad parameters or geometry.",
         "真空中での短いエネルギー最小化に失敗しました。パラメータか幾何に問題があるしるしです。",
         "진공에서 짧은 에너지 최소화가 실패했습니다. 매개변수나 기하에 문제가 있다는 신호입니다.")),
    "single-point energy": (
        ("單點能量", "Single-point energy", "一点エネルギー", "단일점 에너지"),
        ("起始能量不是有限值。",
         "The starting energy is not finite.",
         "開始時のエネルギーが有限の値ではありません。",
         "시작 에너지가 유한한 값이 아닙니다.")),
    "hydrogens": (
        ("加氫", "Hydrogens", "水素の付加", "수소 추가"),
        ("無法一致地加上氫原子。",
         "Hydrogens could not be added consistently.",
         "水素原子を矛盾なく付けられませんでした。",
         "수소 원자를 일관되게 붙일 수 없었습니다.")),
    "chain": (
        ("鏈", "Chain", "鎖", "사슬"),
        ("鏈識別碼互相衝突。",
         "Chain identifiers conflict.",
         "鎖 ID が衝突しています。",
         "사슬 식별자가 서로 충돌합니다.")),
    "padding": (
        ("水盒邊距", "Box padding", "水ボックスの余白", "물 상자 여백"),
        ("水盒邊距對預定的計算來說太小。",
         "The box padding is too small for the planned calculation.",
         "予定している計算には水ボックスの余白が小さすぎます。",
         "계획한 계산에 비해 물 상자 여백이 너무 작습니다.")),
    "ions": (
        ("離子", "Ions", "イオン", "이온"),
        ("鹽的種類不支援，或濃度超出範圍。",
         "The salt type is not supported, or its concentration is out of range.",
         "塩の種類に対応していないか、濃度が範囲外です。",
         "지원하지 않는 염 종류이거나 농도가 범위를 벗어났습니다.")),
    "water fraction": (
        ("水比例", "Water fraction", "水の割合", "물 비율"),
        ("以水盒大小來說，裡面的水異常地少或多。",
         "The box contains unusually little or much water for its size.",
         "ボックスの大きさに対して水が異常に少ないか多いです。",
         "상자 크기에 비해 물이 비정상적으로 적거나 많습니다.")),
    "implicit solvent": (
        ("隱式溶劑", "Implicit solvent", "陰溶媒", "암시적 용매"),
        ("選了隱式溶劑，請先了解它的限制。",
         "Implicit solvent was requested. Check its limitations.",
         "陰溶媒が指定されています。その限界を確認してください。",
         "암시적 용매가 지정되었습니다. 그 한계를 확인하십시오.")),
    "implicit solvent + metal": (
        ("隱式溶劑與金屬", "Implicit solvent with a metal", "陰溶媒と金属", "암시적 용매와 금속"),
        ("這個金屬位點不適合用隱式溶劑。",
         "Implicit solvent is not suitable for this metal site.",
         "この金属サイトには陰溶媒は適していません。",
         "이 금속 부위에는 암시적 용매가 적합하지 않습니다.")),
    "implicit solvent + binding": (
        ("隱式溶劑與結合計算", "Implicit solvent with binding", "陰溶媒と結合計算", "암시적 용매와 결합 계산"),
        ("結合自由能需要週期性水盒，不能用隱式溶劑。",
         "Binding free energy needs a periodic water box, so implicit solvent cannot be used.",
         "結合自由エネルギーには周期境界の水ボックスが必要で、陰溶媒は使えません。",
         "결합 자유 에너지에는 주기적 물 상자가 필요하므로 암시적 용매를 쓸 수 없습니다.")),
    "multi-ligand flat-bottom": (
        ("多配體平底約束", "Multi-ligand restraints", "複数リガンドの平底拘束", "다중 리간드 평저 구속"),
        ("模擬時每個配體都用平底約束留在口袋附近。做自由能計算時會關掉。",
         "During simulation each ligand is kept near the pocket with a flat-bottom restraint. "
         "The restraint is switched off for free-energy work.",
         "シミュレーション中は平底拘束で各リガンドをポケットの近くに保ちます。自由エネルギー計算ではこの拘束を外します。",
         "시뮬레이션 동안 평저 구속으로 각 리간드를 포켓 근처에 둡니다. 자유 에너지 계산에서는 이 구속을 끕니다.")),
    "assembly": (
        ("系統組裝", "System assembly", "系の組み立て", "계 조립"),
        ("無法組裝系統。",
         "The system could not be assembled.",
         "系を組み立てられませんでした。",
         "계를 조립할 수 없었습니다.")),
    "openmm": (
        ("OpenMM", "OpenMM", "OpenMM", "OpenMM"),
        ("這個環境裡沒有 OpenMM。",
         "OpenMM is not available in this environment.",
         "この環境では OpenMM を使えません。",
         "이 환경에서는 OpenMM을 사용할 수 없습니다.")),
    "docking reliability": (
        ("對接可信度", "Docking reliability", "ドッキングの信頼性", "도킹 신뢰도"),
        ("這個配體的對接結果可信度有限。",
         "Docking results for this ligand are of limited reliability.",
         "このリガンドのドッキング結果は信頼性が限られます。",
         "이 리간드의 도킹 결과는 신뢰도가 제한적입니다.")),
    "box size": (
        ("搜尋區大小", "Search box size", "探索ボックスの大きさ", "탐색 상자 크기"),
        ("科學限制提醒。搜尋區很大，最長邊超過 40 Å 或區內超過 300 個殘基。這樣接近盲對接，分數和姿勢的可信度會下降。這則提醒不會中止流程。",
         "Scientific limitation notice. The search box is very large: its longest edge is over 40 Å or it holds more than "
         "300 residues. This behaves like blind docking and makes scores and poses less reliable. "
         "This notice does not stop the workflow.",
         "科学的な限界のお知らせです。探索ボックスがとても大きく、最長辺が 40 Å を超えるか、中に 300 を超える残基があります。"
         "ブラインドドッキングに近くなり、スコアとポーズの信頼性が下がります。このお知らせでワークフローは止まりません。",
         "과학적 한계 안내입니다. 탐색 상자가 매우 큽니다. 가장 긴 변이 40 Å를 넘거나 안에 잔기가 300개를 넘습니다. "
         "블라인드 도킹과 비슷해져 점수와 포즈의 신뢰도가 떨어집니다. 이 안내 때문에 워크플로가 멈추지는 않습니다.")),
    "blind docking": (
        ("盲對接", "Blind docking", "ブラインドドッキング", "블라인드 도킹"),
        ("搜尋區涵蓋整個蛋白。請確認要做盲對接，或指定結合位置。",
         "The search box covers the whole protein. Confirm blind docking or define the site.",
         "探索ボックスがタンパク質全体を覆っています。ブラインドドッキングでよいか確認するか、結合部位を指定してください。",
         "탐색 상자가 단백질 전체를 덮고 있습니다. 블라인드 도킹을 확인하거나 결합 부위를 지정하십시오.")),
    "redocking": (
        ("重新對接自檢", "Redocking check", "再ドッキングによる確認", "재도킹 점검"),
        ("搜尋區是由共結晶配體定出的，但沒有把這個配體重新對接一次來檢查設定。",
         "The box comes from a co-crystal ligand, but that ligand is not redocked to check the setup.",
         "探索ボックスは共結晶リガンドから決めましたが、そのリガンドを再ドッキングして設定を確認していません。",
         "탐색 상자는 공결정 리간드에서 정했지만, 그 리간드를 재도킹해 설정을 점검하지 않았습니다.")),
    "confirm MD": (
        ("確認進入分子動力學", "Proceed to molecular dynamics?", "分子動力学に進みますか", "분자동역학 진행 확인"),
        ("分子對接和姿勢選擇已完成。長時間模擬開始前請先確認。",
         "Docking and pose selection are complete. Confirm before the long simulation starts.",
         "分子ドッキングとポーズ選択が終わりました。長いシミュレーションを始める前に確認してください。",
         "분자 도킹과 포즈 선택이 끝났습니다. 긴 시뮬레이션을 시작하기 전에 확인하십시오.")),
    "long run": (       # engine/longrun.py, docs/specs/long_timescale.md
        ("長時間模擬", "Long simulation", "長時間シミュレーション", "장시간 시뮬레이션"),
        ("正式模擬很長，或硬碟空間不夠。開始前請確認天數與硬碟用量，或改用較省空間的存檔方式。",
         "The production run is very long, or the disk is too small. Confirm the days and disk use before it starts, "
         "or save the trajectory in a way that needs less space.",
         "本計算がとても長いか、ディスクの空きが足りません。開始前に日数とディスク使用量を確認するか、容量の少ない保存方法に"
         "してください。",
         "본 계산이 매우 길거나 디스크 공간이 부족합니다. 시작하기 전에 일수와 디스크 사용량을 확인하거나, 공간을 덜 쓰는 "
         "저장 방식으로 바꾸십시오.")),
    "library": (
        ("化合物庫", "Compound library", "化合物ライブラリ", "화합물 라이브러리"),
        ("無法讀取化合物庫。",
         "The compound library could not be read.",
         "化合物ライブラリを読み込めませんでした。",
         "화합물 라이브러리를 읽을 수 없었습니다.")),
    "library partial": (
        ("化合物庫部分失敗", "Library partly failed", "ライブラリの一部が失敗", "라이브러리 일부 실패"),
        ("有些化合物取不到結構。可以略過它們繼續，或修正化合物庫。",
         "Some compounds could not be obtained. Continue without them or fix the library.",
         "一部の化合物の構造を取得できませんでした。それらを除いて続けるか、ライブラリを修正してください。",
         "일부 화합물의 구조를 가져오지 못했습니다. 그것을 빼고 계속하거나 라이브러리를 고치십시오.")),
    "screen partial": (
        ("篩選部分失敗", "Screening partly failed", "スクリーニングの一部が失敗", "스크리닝 일부 실패"),
        ("有些化合物在篩選對接時失敗。",
         "Some compounds failed in the screening docking.",
         "スクリーニングのドッキングで一部の化合物が失敗しました。",
         "스크리닝 도킹에서 일부 화합물이 실패했습니다.")),
    "screen selection": (
        ("篩選選擇", "Screening selection", "スクリーニングの選択", "스크리닝 선택"),
        ("從篩選排名中選出要進入下一步的化合物。",
         "Choose the compounds to take forward from the screening ranking.",
         "スクリーニングの順位から次に進める化合物を選んでください。",
         "스크리닝 순위에서 다음 단계로 보낼 화합물을 선택하십시오.")),
    "structure_gate": (
        ("結構可信度", "Structure validity", "構造の妥当性", "구조 타당성"),
        ("結構沒有通過可信度檢查。",
         "The structure did not pass a validity check.",
         "構造が妥当性のチェックを通りませんでした。",
         "구조가 타당성 검사를 통과하지 못했습니다.")),
    # D-80 structure prediction (md20/build/fold.py)
    "fold": (
        ("結構預測", "Structure prediction", "構造予測", "구조 예측"),
        ("胜肽的結構預測無法執行，或結果需要你決定。",
         "The peptide structure prediction could not run, or its result needs your decision.",
         "ペプチドの構造予測を実行できないか、結果について判断が必要です。",
         "펩타이드 구조 예측을 실행할 수 없거나 결과에 결정이 필요합니다.")),
    "fold confidence": (
        ("預測可信度（pLDDT）", "Prediction confidence (pLDDT)", "予測の信頼度（pLDDT）", "예측 신뢰도(pLDDT)"),
        ("平均 pLDDT 70 以上可信，50 到 70 偏低（MD 會檢查），低於 50 不可信。預測結構不是實驗結構。",
         "Mean pLDDT of 70 or more is reliable, 50 to 70 is low (MD checks it), below 50 is not reliable. A predicted structure is not an experimental one.",
         "平均 pLDDT が 70 以上なら信頼でき、50 から 70 は低め（MD で確認）、50 未満は信頼できません。予測構造は実験構造ではありません。",
         "평균 pLDDT 70 이상은 신뢰할 수 있고 50에서 70은 낮으며(MD로 확인) 50 미만은 신뢰할 수 없습니다. 예측 구조는 실험 구조가 아닙니다.")),
    "fold placement": (
        ("胜肽姿勢放進受體", "Peptide pose in the receptor", "受容体へのペプチドのポーズ配置", "수용체에 펩타이드 포즈 배치"),
        ("預測的受體以 Cα 疊合到實際受體，只取胜肽姿勢。Cα RMSD 超過 2 Å 時，胜肽可能不在正確位置。",
         "The predicted receptor is superposed onto the actual receptor on Cα atoms and only the peptide pose is taken. "
         "With a Cα RMSD above 2 Å the peptide may be in the wrong place.",
         "予測した受容体を Cα で実際の受容体に重ね、ペプチドのポーズだけを使います。Cα RMSD が 2 Å を超えると、ペプチドが正しい位置にないかもしれません。",
         "예측한 수용체를 Cα로 실제 수용체에 겹치고 펩타이드 포즈만 사용합니다. Cα RMSD가 2 Å를 넘으면 펩타이드가 올바른 위치에 있지 않을 수 있습니다.")),
    "fold interface": (
        ("預測介面（ipTM）", "Predicted interface (ipTM)", "予測された界面（ipTM）", "예측 계면(ipTM)"),
        ("科學限制提醒。ipTM 低於 0.5 時，預測的受體與胜肽介面不可信，請用 MD 與對接交叉檢查。",
         "Scientific limitation notice. With ipTM below 0.5 the predicted receptor and peptide interface is not reliable. Cross-check it with MD and docking.",
         "科学的な制約の注意です。ipTM が 0.5 未満のとき、予測された受容体とペプチドの界面は信頼できません。MD とドッキングで確かめてください。",
         "과학적 한계 안내입니다. ipTM이 0.5 미만이면 예측된 수용체와 펩타이드 계면은 신뢰할 수 없습니다. MD와 도킹으로 교차 확인하십시오.")),
}

# Chinese option text (stored in config.json and the DecisionLog) → (en, ja, ko)
OPTIONS: dict[str, tuple[str, str, str]] = {
    "截斷（加 ACE/NME 端帽）": ("Truncate (add ACE and NME caps)", "切り詰める（ACE と NME のキャップを付ける）", "자르기(ACE와 NME 캡 추가)"),
    "以 PDBFixer 補建並接受風險": ("Rebuild with PDBFixer and accept the risk", "PDBFixer で補い、リスクを受け入れる", "PDBFixer로 채우고 위험 감수"),
    "改用 AlphaFold 模型": ("Use an AlphaFold model instead", "AlphaFold モデルに切り替える", "AlphaFold 모델로 변경"),
    "提供含 SEQRES 的原始 PDB（RCSB 下載版）": ("Provide the original PDB with SEQRES (RCSB download)",
                                         "SEQRES を含む元の PDB を用意する（RCSB からダウンロードしたもの）",
                                         "SEQRES가 있는 원본 PDB 제공(RCSB 다운로드본)"),
    "提供含完整 SEQRES 的原始 PDB": ("Provide the original PDB with complete SEQRES", "SEQRES がそろった元の PDB を用意する",
                               "SEQRES가 완전한 원본 PDB 제공"),
    "全部移除（預設）": ("Remove all (default)", "すべて取り除く（既定）", "모두 제거(기본)"),
    "保留並參數化": ("Keep and parameterise", "残してパラメータ化する", "남기고 매개변수화"),
    "保留為參考配體（僅用於 box 定義）": ("Keep as a reference ligand, used only to define the box",
                                "参照リガンドとして残す（探索ボックスの決定にだけ使う）", "기준 리간드로 남기기(탐색 상자 정의에만 사용)"),
    "移除並記錄": ("Remove and record", "取り除いて記録する", "제거하고 기록"),
    "視為配體走參數化階梯": ("Treat as a ligand and parameterise", "リガンドとして扱いパラメータ化する", "리간드로 취급해 매개변수화"),
    "手動提供參數": ("Provide parameters manually", "パラメータを手動で用意する", "매개변수 직접 제공"),
    "換一個更高解析度的結構": ("Use a higher-resolution structure", "より分解能の高い構造に替える", "해상도가 더 높은 구조로 변경"),
    "換結構": ("Use another structure", "別の構造に替える", "다른 구조로 변경"),
    "胞內 intracellular": ("Intracellular", "細胞内", "세포 내"),
    "膜外側 extracellular-membrane": ("Extracellular, at the membrane", "細胞外の膜表面", "세포 밖 막 표면"),
    "分泌／胞外 secreted": ("Secreted or extracellular", "分泌型または細胞外", "분비형 또는 세포 외"),
    "提供實驗證據（文獻或自有數據）": ("Provide experimental evidence (literature or your own data)",
                            "実験的な根拠を示す（文献または自分のデータ）", "실험 근거 제공(문헌 또는 자체 데이터)"),
    "提供實驗證據": ("Provide experimental evidence", "実験的な根拠を示す", "실험 근거 제공"),
    "改設計：縮短為帶電核心（如 GKP、KP）或富集 Arg/Lys": (
        "Redesign by shortening to the charged core (such as GKP or KP) or adding Arg and Lys",
        "設計を変える。帯電したコア（GKP や KP など）まで短くするか、Arg と Lys を増やす",
        "설계 변경. 전하를 띤 핵심(GKP, KP 등)으로 줄이거나 Arg와 Lys를 늘림"),
    "改設計：N 端接 TAT／R8／penetratin 等穿膜載體": (
        "Redesign by attaching a cell-penetrating carrier such as TAT, R8 or penetratin at the N terminus",
        "設計を変える。N 末端に TAT、R8、penetratin などの膜透過キャリアを付ける",
        "설계 변경. N 말단에 TAT, R8, penetratin 같은 세포 투과 운반체를 붙임"),
    "接受預測並繼續": ("Accept the prediction and continue", "予測を受け入れて続ける", "예측을 받아들이고 계속"),
    "以共結晶配體或活性位殘基重新定義搜尋區": ("Redefine the search box from a co-crystal ligand or active-site residues",
                                "共結晶リガンドか活性部位の残基から探索ボックスを決め直す",
                                "공결정 리간드나 활성 부위 잔기로 탐색 상자 다시 정의"),
    "接受並在報告中標註": ("Accept and label it in the report", "受け入れてレポートに明記する", "받아들이고 보고서에 표시"),
    "改選其他 pose（pose 表）": ("Choose another pose in the pose table", "ポーズ表で別のポーズを選ぶ", "포즈 표에서 다른 포즈 선택"),
    "縮小搜尋區到活性位後重新對接": ("Narrow the box to the active site and dock again", "探索ボックスを活性部位まで狭めて再ドッキングする",
                           "탐색 상자를 활성 부위로 좁혀 다시 도킹"),
    "進入分子動力學（md_confirmed）": ("Proceed to molecular dynamics", "分子動力学に進む", "분자동역학으로 진행"),
    "先改選姿勢（在姿勢表點選後再回來確認）": ("Choose another pose first (click it in the pose table, then confirm)",
                                "先に別のポーズを選ぶ（ポーズ表でクリックしてから確認に戻る）",
                                "먼저 다른 포즈 선택(포즈 표에서 클릭한 뒤 돌아와 확인)"),
    "換一個不直接配位金屬的 pose（pose 表點選）": ("Use a pose that does not coordinate the metal (pick it in the pose table)",
                                     "金属に直接配位しないポーズに替える（ポーズ表で選ぶ）",
                                     "금속에 직접 배위하지 않는 포즈로 변경(포즈 표에서 선택)"),
    "以 MCPB.py/QM 參數化配體–金屬鍵後匯入（metal_params）": ("Parameterise the ligand–metal bond with MCPB.py or QM and import it",
                                                "MCPB.py または QM でリガンドと金属の結合をパラメータ化して取り込む",
                                                "MCPB.py 또는 QM으로 리간드와 금속의 결합을 매개변수화해 가져오기"),
    "以 MCPB.py/QM 參數化後匯入": ("Parameterise with MCPB.py or QM and import", "MCPB.py または QM でパラメータ化して取り込む",
                              "MCPB.py 또는 QM으로 매개변수화해 가져오기"),
    "改用 keep_nonbonded（報告標註）": ("Keep as a non-bonded ion (labelled in the report)", "非結合イオンとして残す（レポートに明記）",
                                 "비결합 이온으로 남기기(보고서에 표시)"),
    "改用 keep_nonbonded": ("Keep as a non-bonded ion", "非結合イオンとして残す", "비결합 이온으로 남기기"),
    "remove（若非必要）": ("Remove (if not functionally needed)", "取り除く（機能上必要でなければ）", "제거(기능상 필요 없으면)"),
    "metal_policy: remove（若非必要）": ("Remove the metal (if not functionally needed)", "金属を取り除く（機能上必要でなければ）",
                                    "금속 제거(기능상 필요 없으면)"),
    "metal_params 改為不套用電荷（charges: false）": ("Do not apply the fitted charges", "フィットした電荷を適用しない", "피팅한 전하를 적용하지 않음"),
    "確認 MCPB 模型的質子化狀態": ("Check the protonation states of the MCPB model", "MCPB モデルのプロトン化状態を確認する",
                           "MCPB 모델의 양성자화 상태 확인"),
    "改用幾何鍵結模型（移除 metal_params）": ("Use the geometric bonded model", "幾何から作る結合モデルを使う", "기하 결합 모델 사용"),
    "修正 metal_params 設定": ("Fix the metal parameter settings", "金属パラメータの設定を直す", "금속 매개변수 설정 수정"),
    "md.solvent: explicit（顯式水）": ("Use explicit water", "陽溶媒の水を使う", "명시적 물 사용"),
    "md.solvent: explicit（顯式水，重建並重跑 MD）": ("Use explicit water (rebuild and rerun)", "陽溶媒の水を使う（系を作り直して再実行）",
                                            "명시적 물 사용(다시 만들고 다시 실행)"),
    "md.solvent: gbn2（真的要省算力時用隱式溶劑）": ("Use implicit solvent (only to save computing time)",
                                          "陰溶媒を使う（計算時間を節約したいときだけ）", "암시적 용매 사용(계산 시간을 아껴야 할 때만)"),
    "binding.enabled: false（只做 MD）": ("Skip binding free energy (molecular dynamics only)",
                                       "結合自由エネルギーを省く（分子動力学だけ）", "결합 자유 에너지 생략(분자동역학만)"),
    "screen.allow_partial: true（略過失敗的化合物，報告標註）": ("Continue without the failed compounds (labelled in the report)",
                                                  "失敗した化合物を除いて続ける（レポートに明記）",
                                                  "실패한 화합물을 빼고 계속(보고서에 표시)"),
    "在「篩選」分頁勾選化合物": ("Tick compounds in the Screening tab", "「スクリーニング」タブで化合物にチェックを入れる",
                          "'스크리닝' 탭에서 화합물 선택"),
    "修正化合物庫檔案後重新執行": ("Fix the library file and run again", "ライブラリのファイルを直して再実行する",
                           "라이브러리 파일을 고친 뒤 다시 실행"),
    "檢查失敗原因後重新執行": ("Check the failures and run again", "失敗の原因を確認して再実行する", "실패 원인을 확인한 뒤 다시 실행"),
    "保留口袋內 5 Å 的水": ("Keep waters within 5 Å of the pocket", "ポケットから 5 Å 以内の水を残す", "포켓 5 Å 이내의 물 남기기"),
    "移除（預設）": ("Remove (default)", "取り除く（既定）", "제거(기본)"),
    "保留": ("Keep", "残す", "남기기"),
    "接受推斷": ("Accept the inference", "推定を受け入れる", "추정 수락"),
    "改用 mmCIF 原始檔": ("Use the original mmCIF file", "元の mmCIF ファイルを使う", "원본 mmCIF 파일 사용"),
    "改用原始 mmCIF": ("Use the original mmCIF file", "元の mmCIF ファイルを使う", "원본 mmCIF 파일 사용"),
    "以參考分子為準": ("Follow the reference molecule", "参照分子に合わせる", "기준 분자를 따름"),
    "以序列宣告為胜肽": ("Declare it as a peptide by sequence", "配列を指定してペプチドとして扱う", "서열로 펩타이드임을 지정"),
    "確認為小分子（peptide_policy.allow_small_molecule）": ("Confirm it is a small molecule", "低分子であることを確認する",
                                                    "저분자임을 확인"),
    "確認序列": ("Check the sequence", "配列を確認する", "서열 확인"),
    "改用帶電端（預設）": ("Use charged termini (default)", "帯電した末端にする（既定）", "전하를 띤 말단 사용(기본)"),
    "使用 Sobtop 進階路徑": ("Use the Sobtop advanced route", "Sobtop の上級ルートを使う", "Sobtop 고급 경로 사용"),
    "安裝 openff-toolkit + openff-nagl": ("Install openff-toolkit and openff-nagl", "openff-toolkit と openff-nagl をインストールする",
                                         "openff-toolkit과 openff-nagl 설치"),
    "回報給老師": ("Report it to the instructor", "先生に報告する", "강사에게 알리기"),
    "從 keep_hetero 移除": ("Remove from the kept residues", "残す残基の一覧から外す", "남길 잔기 목록에서 제외"),
    "提供該殘基的參數": ("Provide parameters for this residue", "この残基のパラメータを用意する", "이 잔기의 매개변수 제공"),
    "提供 docking 前的 SDF": ("Provide the SDF used for docking", "ドッキングに使った SDF を用意する", "도킹에 쓴 SDF 제공"),
    "改用 docking 輸出的 SDF": ("Use the SDF written by docking", "ドッキングが出力した SDF を使う", "도킹이 출력한 SDF 사용"),
    "改用 pose SDF（Meeko/Vina --out sdf）": ("Use the pose SDF", "ポーズの SDF を使う", "포즈 SDF 사용"),
    "重新匯出 docking pose": ("Export the docking pose again", "ドッキングのポーズを出力し直す", "도킹 포즈 다시 내보내기"),
    "重新以 pH 質子化（Dimorphite-DL）": ("Re-protonate for the pH", "pH に合わせてプロトン化し直す", "pH에 맞춰 다시 양성자화"),
    "檢查 chain ID 與殘基編號": ("Check chain identifiers and residue numbers", "鎖 ID と残基番号を確認する", "사슬 식별자와 잔기 번호 확인"),
    # D-80 structure prediction
    "不使用預測結構，改用延伸構形（fold: false）": ("Do not use a predicted structure, use the extended build",
                                    "予測構造を使わず、伸びた構造を使う", "예측 구조를 쓰지 않고 펼쳐진 구조 사용"),
    "改用其他摺疊工具（fold_engine）": ("Use another folding tool", "別のフォールディングツールを使う", "다른 폴딩 도구 사용"),
    "上傳預測結構（fold_upload）": ("Upload a predicted structure (AlphaFold Server, ColabFold)",
                             "予測構造をアップロードする（AlphaFold Server、ColabFold）", "예측 구조 업로드(AlphaFold Server, ColabFold)"),
    "仍使用這個預測結構（fold_accept_low: true）": ("Use this predicted structure anyway (labelled in the report)",
                                       "それでもこの予測構造を使う（レポートに明記）", "그래도 이 예측 구조 사용(보고서에 표시)"),
    "安裝摺疊工具（md20 setup-fold）": ("Install a folding tool (md20 setup-fold)", "フォールディングツールをインストールする（md20 setup-fold）",
                                  "폴딩 도구 설치(md20 setup-fold)"),
    "fold_engine: boltz": ("Use Boltz-2", "Boltz-2 を使う", "Boltz-2 사용"),
    "仍使用這個胜肽姿勢（fold_accept_rmsd: true）": ("Use this peptide pose anyway (labelled in the report)",
                                         "それでもこのペプチドのポーズを使う（レポートに明記）", "그래도 이 펩타이드 포즈 사용(보고서에 표시)"),
    "改用對接（fold: true）": ("Dock the predicted peptide instead", "予測したペプチドをドッキングに切り替える", "예측한 펩타이드를 도킹으로 전환"),
    "提供完整受體序列（fold_receptor_seq）": ("Give the full receptor sequence", "受容体の完全な配列を指定する", "수용체 전체 서열 입력"),
}
OPTIONS.update({   # free-text hints of the decision inputs
    "文獻（DOI）或自有實驗數據的簡述": ("Literature (DOI) or a short description of your own data",
                             "文献（DOI）か、自分の実験データの簡単な説明", "문헌(DOI) 또는 자체 실험 데이터의 간단한 설명"),
    "為什麼在未驗證穿膜性的情況下仍要繼續（報告會標註）": ("Why continue without verified cell penetration (labelled in the report)",
                                     "膜透過性を確かめずに続ける理由（レポートに明記されます）",
                                     "세포 투과성을 확인하지 않고 계속하는 이유(보고서에 표시됨)"),
    "為什麼它是擬肽小分子而不是胜肽": ("Why it is a peptidomimetic small molecule rather than a peptide",
                            "ペプチドではなくペプチド模倣の低分子だと考える理由", "펩타이드가 아니라 펩타이드 모방 저분자라고 보는 이유"),
    "為什麼這個結構仍可用（會寫進決策日誌與報告）": ("Why this structure is still usable (recorded in the decision log and the report)",
                                  "この構造がそれでも使える理由（判断ログとレポートに記録されます）",
                                  "이 구조를 그래도 쓸 수 있는 이유(결정 기록과 보고서에 남음)"),
    "備註（為什麼選這些）": ("Note (why these compounds)", "メモ（これらを選んだ理由）", "메모(이 화합물을 고른 이유)"),
    "聯合姿勢名次（數字）": ("Joint pose rank (a number)", "組み合わせポーズの順位（数字）", "결합 포즈 순위(숫자)"),
    "omegafold、esmfold、boltz 或 colabfold": ("omegafold, esmfold, boltz or colabfold", "omegafold、esmfold、boltz、colabfold のいずれか",
                                              "omegafold, esmfold, boltz, colabfold 중 하나"),
    "完整的受體序列（單字母代碼）": ("The full receptor sequence (one-letter codes)", "受容体の完全な配列（1 文字表記）",
                           "수용체 전체 서열(한 글자 기호)"),
})

# options that carry a value after a fixed prefix → (en, ja, ko); a label ending in a colon is followed by the value
PREFIX: list[tuple[str, tuple[str, str, str]]] = [
    ("multi_ligand.exclude:", ("Exclude this ligand from the multi-ligand system (recommended):",
                               "このリガンドを複数リガンド系から外す（推奨）：", "이 리간드를 다중 리간드 계에서 제외(권장):")),
    ("multi_ligand.accept_geometry", ("Keep the geometry as it is (not recommended, labelled in the report)",
                                      "幾何をそのまま使う（非推奨、レポートに明記）", "기하를 그대로 유지(권장하지 않음, 보고서에 표시)")),
    ("pose_choices:", ("Choose another pose:", "別のポーズを選ぶ：", "다른 포즈 선택:")),
    ("仍要使用", ("Use anyway", "それでも使う", "그래도 사용")),
    ("ligand_metal: restrain", ("Hold the coordination with a distance restraint (no binding free energy for this ligand)",
                                "距離拘束で配位を保つ（このリガンドの結合自由エネルギーは出しません）",
                                "거리 구속으로 배위 유지(이 리간드의 결합 자유 에너지는 계산하지 않음)")),
    ("box.from_residue:", ("Define the box from residue", "次の残基から探索ボックスを決める：", "다음 잔기로 탐색 상자 정의:")),
    ("box.allow_blind", ("Allow blind docking (labelled in the report)", "ブラインドドッキングを許可する（レポートに明記）",
                         "블라인드 도킹 허용(보고서에 표시)")),
    ("docking.skip_redock", ("Skip the redocking check (labelled in the report)", "再ドッキングによる確認を省く（レポートに明記）",
                             "재도킹 점검 생략(보고서에 표시)")),
    ("md.restraints:", ("Restraint strategy:", "拘束の方針：", "구속 방식:")),
    ("md.ions.positive:", ("Cation:", "陽イオン：", "양이온:")),
    ("md.ions.negative:", ("Anion:", "陰イオン：", "음이온:")),
    ("md.padding_nm", ("Increase the box padding", "水ボックスの余白を広げる", "물 상자 여백 늘리기")),
    ("加入共晶配體", ("Add the co-crystal ligand as a redocking reference (needs its SMILES)",
                  "共結晶リガンドを再ドッキングの参照として加える（SMILES が必要）",
                  "공결정 리간드를 재도킹 기준으로 추가(SMILES 필요)")),
    ("metal_policy: {", ("Metal model:", "金属モデル：", "금속 모델:")),
    ("metal_policy:", ("Metal model:", "金属モデル：", "금속 모델:")),
    ("仍要繼續", ("Continue anyway (labelled in the report)", "それでも続ける（レポートに明記）", "그래도 계속(보고서에 표시)")),
    ("md.long_run_confirmed: true", ("Confirm the days and disk use, and start", "日数とディスク使用量を確認して開始する",
                                     "일수와 디스크 사용량을 확인하고 시작")),
    ("md.production_ns:", ("Shorten the production run to (ns):", "本計算の長さを短くする（ns）：", "본 계산 길이 줄이기(ns):")),
    ("md.long_run.solute_only: true", ("Save the solute only (no water, no counter-ions)", "溶質だけを保存する（水と対イオンは保存しない）",
                                       "용질만 저장(물과 반대 이온은 저장하지 않음)")),
    ("md.long_run.target_gb:", ("Trajectory size limit (GB):", "トラジェクトリの上限（GB）：", "궤적 크기 상한(GB):")),
    ("縮短 md.production_ns", ("Shorten the production run, or move the project folder to a larger disk and try again",
                             "本計算を短くするか、プロジェクトフォルダを容量の大きいディスクに移して再試行する",
                             "본 계산을 줄이거나 프로젝트 폴더를 더 큰 디스크로 옮긴 뒤 다시 시도")),
    ("改用粗粒化 Martini 3", ("Use coarse-grained Martini 3 instead (md20 setup-cg)", "粗視化 Martini 3 を使う（md20 setup-cg）",
                          "조립화 Martini 3 사용(md20 setup-cg)")),
]


def _lookup(name: str):
    if name in GATES:
        return name, GATES[name]
    for k in sorted(GATES, key=len, reverse=True):          # "metal ZN:A262" matches "metal", "metal charges ZN" matches "metal charges"
        if name.startswith(k + " "):
            return k, GATES[k]
    return None, None


def gate_title(name: str, lang: str) -> str:
    """Title of a gate in the interface language; the part after a known prefix (residue, ligand name) is kept."""
    k, g = _lookup(name)
    if not g:
        return name
    return pick(g[0], lang) + name[len(k):]


def gate_general(name: str, lang: str = "en") -> str:
    """General explanation of the gate kind ("" for an unknown gate)."""
    g = _lookup(name)[1]
    return pick(g[1], lang) if g else ""


def option_text(option: str, lang: str) -> str:
    """An option in the interface language.  Chinese shows the stored text itself (it is the key)."""
    if option in OPTIONS:
        return pick((option, *OPTIONS[option]), lang)
    for p, labels in PREFIX:
        if option.startswith(p):
            text = pick((option, *labels), lang)
            if text == option:                                   # Chinese interface
                return option
            rest = option[len(p):].split("（")[0].strip(" :{}")
            if rest and (labels[0].endswith(":") or p.endswith(":")):
                return text + ("" if text.endswith("：") else " ") + rest
            return text
    return option


# D-80 membrane systems (md20/build/membrane.py, md20/analysis/membrane.py, docs/specs/membrane.md)
GATES.update({
    "membrane type": (
        ("膜系統類型", "Membrane system type", "膜系の種類", "막 계 종류"),
        ("膜系統的類型和輸入不一致。protein 是膜蛋白，surface 是膜表面的胜肽或小分子，bilayer 是純膜。",
         "The membrane system type does not match the input. protein is a membrane protein, surface is a peptide or "
         "small molecule on the membrane surface, bilayer is lipids only.",
         "膜系の種類と入力が合っていません。protein は膜タンパク質、surface は膜表面のペプチドか低分子、bilayer は脂質だけの膜です。",
         "막 계 종류와 입력이 맞지 않습니다. protein은 막단백질, surface는 막 표면의 펩타이드나 저분자, bilayer는 지질만 있는 막입니다.")),
    "membrane composition": (
        ("脂質組成", "Lipid composition", "脂質組成", "지질 조성"),
        ("脂質組成無法使用，或比例已換算成分率。",
         "The lipid composition cannot be used, or its ratios were converted to fractions.",
         "脂質組成が使えないか、比率を分率に換算しました。",
         "지질 조성을 쓸 수 없거나, 비율을 분율로 환산했습니다.")),
    "membrane phase": (
        ("膜的相", "Membrane phase", "膜の相", "막의 상"),
        ("模擬溫度接近或低於主要脂質的相轉變溫度，膜會變成凝膠相。請提高溫度或換脂質。",
         "The temperature is near or below the main lipid's phase transition, so the membrane would turn into a gel. "
         "Raise the temperature or choose another lipid.",
         "温度が主な脂質の相転移温度に近いか低いため、膜がゲル相になります。温度を上げるか脂質を変えてください。",
         "온도가 주요 지질의 상전이 온도에 가깝거나 낮아 막이 겔 상이 됩니다. 온도를 올리거나 지질을 바꾸십시오.")),
    "membrane force field": (
        ("脂質力場", "Lipid force field", "脂質の力場", "지질 역장"),
        ("這個組成裡有脂質在 Amber 脂質力場中沒有參數，不能和蛋白力場一起使用。",
         "Some lipids in this composition have no parameters in the Amber lipid force field used with the protein.",
         "この組成には、タンパク質と一緒に使う Amber 脂質力場にパラメータがない脂質があります。",
         "이 조성에는 단백질과 함께 쓰는 Amber 지질 역장에 매개변수가 없는 지질이 있습니다.")),
    "membrane builder": (
        ("建膜方式", "Membrane builder", "膜の作成方法", "막 생성 방식"),
        ("建膜方式的說明，或建膜所需的脂質模板不足。",
         "How the membrane is built, or lipid templates needed to build it are missing.",
         "膜の作り方の説明か、膜を作るための脂質テンプレートが足りません。",
         "막을 만드는 방식에 대한 안내이거나, 막을 만드는 데 필요한 지질 템플릿이 없습니다.")),
    "membrane orientation": (
        ("膜中方向", "Orientation in the membrane", "膜内での向き", "막 안에서의 방향"),
        ("膜蛋白在膜中的方向。已定向的結構照原樣使用，否則由疏水帶掃描決定。疏水帶不明顯時需要你決定。",
         "How the membrane protein sits in the membrane. An oriented structure is used as is, otherwise a hydrophobic-belt "
         "scan decides. If the belt is unclear, you decide.",
         "膜タンパク質の膜内での向きです。向きをそろえた構造はそのまま使い、そうでなければ疎水性ベルトの探索で決めます。ベルトがはっきりしない場合は判断が必要です。",
         "막단백질이 막 안에서 놓이는 방향입니다. 방향을 맞춘 구조는 그대로 쓰고, 아니면 소수성 띠 탐색으로 정합니다. 띠가 분명하지 않으면 결정이 필요합니다.")),
    "membrane surface placement": (
        ("膜表面的起始位置", "Starting position above the membrane", "膜表面での初期位置", "막 표면의 시작 위치"),
        ("胜肽或小分子放在上層磷原子平面上方指定的距離，起始時不接觸頭基。",
         "The peptide or small molecule starts a set distance above the upper phosphate plane, not touching the head groups.",
         "ペプチドか低分子を上側のリン原子面から指定の距離だけ離して置き、最初は頭部基に触れません。",
         "펩타이드나 저분자를 위쪽 인 원자 평면에서 정한 거리만큼 위에 놓아, 처음에는 머리 부분에 닿지 않습니다.")),
    "membrane implicit solvent": (
        ("膜與隱式溶劑", "Membrane and implicit solvent", "膜と陰溶媒", "막과 암시적 용매"),
        ("膜系統需要顯式水。隱式溶劑無法表示脂質頭基和水的作用。",
         "Membrane systems need explicit water. Implicit solvent cannot describe how lipid head groups interact with water.",
         "膜系には陽溶媒の水が必要です。陰溶媒では脂質の頭部基と水の相互作用を表せません。",
         "막 계에는 명시적 물이 필요합니다. 암시적 용매로는 지질 머리 부분과 물의 상호작용을 나타낼 수 없습니다.")),
    "membrane equilibration": (
        ("膜平衡驗收", "Membrane equilibration check", "膜の平衡化チェック", "막 평형 점검"),
        ("檢查每個脂質的面積、膜厚度、疏水核心中的水，以及蛋白是否留在膜中。不合格時先延長平衡一次。",
         "Checks the area per lipid, the bilayer thickness, water in the hydrophobic core and whether the protein stays "
         "in the membrane. If a check fails, equilibration is extended once.",
         "脂質 1 分子あたりの面積、膜の厚さ、疎水性コア中の水、タンパク質が膜に残っているかを確認します。不合格なら平衡化を 1 回延長します。",
         "지질당 면적, 막 두께, 소수성 중심부의 물, 단백질이 막 안에 남아 있는지를 확인합니다. 통과하지 못하면 평형화를 한 번 연장합니다.")),
    "membrane binding": (
        ("膜系統的結合自由能", "Binding free energy in a membrane", "膜系の結合自由エネルギー", "막 계의 결합 자유 에너지"),
        ("膜系統還不能做 SMD 與傘狀採樣。拉離方向可能穿過脂雙層，結果不可信。",
         "SMD and umbrella sampling are not available for membrane systems yet. The pulling path may cross the bilayer, "
         "so the result would not be reliable.",
         "膜系ではまだ SMD とアンブレラサンプリングを行えません。引き離しの経路が脂質二重膜を横切ることがあり、結果を信頼できません。",
         "막 계에서는 아직 SMD와 엄브렐라 샘플링을 할 수 없습니다. 당김 경로가 지질 이중층을 지날 수 있어 결과를 믿을 수 없습니다.")),
})
OPTIONS.update({
    "使用 CHARMM-GUI 建好的系統（尚未支援匯入）": ("Use a system built with CHARMM-GUI (import not supported yet)",
                                     "CHARMM-GUI で作った系を使う（読み込みは未対応）", "CHARMM-GUI로 만든 계 사용(가져오기는 아직 지원하지 않음)"),
    "下載 OPM 定向結構後重新上傳": ("Download the oriented structure from OPM and upload it again",
                         "OPM から向きをそろえた構造をダウンロードして再アップロードする", "OPM에서 방향을 맞춘 구조를 받아 다시 업로드"),
    "再延長平衡（md.stage_overrides.npt.length_ps）": ("Extend equilibration again", "平衡化をもう一度延長する", "평형화 다시 연장"),
    "檢查脂質組成與溫度": ("Check the lipid composition and the temperature", "脂質組成と温度を確認する", "지질 조성과 온도 확인"),
})
PREFIX += [
    ("md.membrane.lipids:", ("Membrane lipids:", "膜の脂質：", "막 지질:")),
    ("md.membrane.type:", ("Membrane system type:", "膜系の種類：", "막 계 종류:")),
    ("md.membrane.temperature_k:", ("Temperature (K):", "温度（K）：", "온도(K):")),
    ("md.membrane.templates_dir", ("Provide a folder with one template PDB per lipid", "脂質ごとに 1 つのテンプレート PDB を入れたフォルダを指定する",
                                   "지질마다 템플릿 PDB 하나가 든 폴더 지정")),
    ("md.membrane.oriented", ("The structure is already oriented (OPM)", "構造は向きをそろえ済み（OPM）", "구조는 이미 방향을 맞춤(OPM)")),
    ("md.membrane.surface_distance_nm:", ("Starting distance above the membrane (nm):", "膜からの初期距離（nm）：",
                                          "막 위 시작 거리(nm):")),
    ("md.membrane.surface_orientation:", ("Starting orientation:", "初期の向き：", "시작 방향:")),
]

# D-86 coarse-grained Martini 3 (md20/build/cg_system.py, Workflow._run_cg)
GATES.update({
    "cg small molecule": (('粗粒化：小分子配體', 'Coarse-grained: small-molecule ligand', '粗視化：低分子リガンド', '조립화: 저분자 리간드'),
        ('Martini 3 沒有小分子的通用參數，粗粒化只能放胜肽或蛋白。',
         'Martini 3 has no general parameters for small molecules, so a coarse-grained system can hold only peptides or proteins.',
         'Martini 3 には低分子の汎用パラメータがないため、粗視化の系に入れられるのはペプチドかタンパク質だけです。',
         'Martini 3에는 저분자의 범용 매개변수가 없어 조립화 계에는 펩타이드나 단백질만 넣을 수 있습니다.')),
    "cg no_solute": (('粗粒化：缺少結構', 'Coarse-grained: no structure', '粗視化：構造がない', '조립화: 구조 없음'),
        ('這個粗粒化系統需要蛋白或胜肽的結構。',
         'This coarse-grained system needs a protein or peptide structure.',
         'この粗視化の系にはタンパク質かペプチドの構造が必要です。',
         '이 조립화 계에는 단백질이나 펩타이드 구조가 필요합니다.')),
    "cg asymmetric": (('粗粒化：不對稱膜', 'Coarse-grained: asymmetric bilayer', '粗視化：非対称膜', '조립화: 비대칭 막'),
        ('粗粒化目前只建上下層組成相同的脂雙層。',
         'Coarse-grained bilayers are built only with the same composition in both leaflets for now.',
         '粗視化では今のところ上下の層が同じ組成の膜だけを作ります。',
         '조립화에서는 지금은 위아래 층 조성이 같은 막만 만듭니다.')),
    "cg not_installed": (('粗粒化：工具沒有安裝', 'Coarse-grained: tools not installed', '粗視化：ツールがない', '조립화: 도구 미설치'),
        ('粗粒化工具還沒有安裝。在電腦狀態頁按「一鍵安裝」，或執行 md20 setup-cg --yes。',
         'The coarse-grained tools are not installed. Press Install now on the computer status page, or run md20 setup-cg --yes.',
         '粗視化ツールがインストールされていません。パソコンの状態のページで「今すぐインストール」を押すか、md20 setup-cg --yes を実行してください。',
         "조립화 도구가 설치되지 않았습니다. 컴퓨터 상태 페이지에서 '지금 설치'를 누르거나 md20 setup-cg --yes를 실행하십시오.")),
    "cg forcefield_files": (('粗粒化：缺少力場檔', 'Coarse-grained: force-field files missing', '粗視化：力場ファイルがない', '조립화: 역장 파일 없음'),
        ('Martini 3 力場檔不在。md20 setup-cg --yes 會一併下載。',
         'The Martini 3 force-field files are missing. md20 setup-cg --yes downloads them.',
         'Martini 3 の力場ファイルがありません。md20 setup-cg --yes で一緒にダウンロードされます。',
         'Martini 3 역장 파일이 없습니다. md20 setup-cg --yes가 함께 내려받습니다.')),
    "cg lipid_not_in_martini3": (('粗粒化：脂質沒有參數', 'Coarse-grained: lipid not in Martini 3', '粗視化：脂質のパラメータがない', '조립화: 지질 매개변수 없음'),
        ('選的脂質不在 Martini 3 磷脂檔裡。',
         'A chosen lipid is not in the Martini 3 phospholipid file.',
         '選んだ脂質が Martini 3 のリン脂質ファイルにありません。',
         '고른 지질이 Martini 3 인지질 파일에 없습니다.')),
    "cg orientation": (('粗粒化：膜蛋白方向', 'Coarse-grained: membrane protein orientation', '粗視化：膜タンパク質の向き', '조립화: 막단백질 방향'),
        ('蛋白的疏水帶不明確，無法自動決定在膜中的方向。',
         "The protein's hydrophobic belt is not clear, so its orientation in the membrane cannot be set automatically.",
         'タンパク質の疎水帯がはっきりせず、膜内の向きを自動で決められません。',
         '단백질의 소수성 띠가 분명하지 않아 막 안의 방향을 자동으로 정할 수 없습니다.')),
    "cg belt_offset": (('粗粒化：疏水帶位置', 'Coarse-grained: hydrophobic belt position', '粗視化：疎水帯の位置', '조립화: 소수성 띠 위치'),
        ('建好的系統裡，蛋白疏水帶中心離膜中心太遠。',
         "In the built system the protein's hydrophobic belt is too far from the bilayer centre.",
         '作った系で、タンパク質の疎水帯の中心が膜の中心から離れすぎています。',
         '만든 계에서 단백질 소수성 띠 중심이 막 중심에서 너무 멉니다.')),
    "cg surface_overlap": (('粗粒化：胜肽與膜重疊', 'Coarse-grained: peptide overlaps the membrane', '粗視化：ペプチドが膜と重なる', '조립화: 펩타이드와 막 겹침'),
        ('胜肽放得太靠近膜，與頭基重疊。',
         'The peptide was placed too close to the membrane and overlaps the head groups.',
         'ペプチドが膜に近すぎて、頭部基と重なっています。',
         '펩타이드가 막에 너무 가까워 머리 부분과 겹칩니다.')),
    "cg tool_failed": (('粗粒化：工具執行失敗', 'Coarse-grained: a tool failed', '粗視化：ツールの実行に失敗', '조립화: 도구 실행 실패'),
        ('martinize2 或 insane 執行失敗，訊息在 cg_build.log。',
         'martinize2 or insane failed; the messages are in cg_build.log.',
         'martinize2 か insane が失敗しました。メッセージは cg_build.log にあります。',
         'martinize2 또는 insane이 실패했습니다. 메시지는 cg_build.log에 있습니다.')),
    "cg no_output": (('粗粒化：缺少輸出檔', 'Coarse-grained: output missing', '粗視化：出力がない', '조립화: 출력 없음'),
        ('工具結束了，但沒有產生預期的檔案。',
         'A tool finished without writing the expected file.',
         'ツールは終わりましたが、予定のファイルがありません。',
         '도구가 끝났지만 예상한 파일이 없습니다.')),
    "cg martini_openmm": (('粗粒化：無法建立 OpenMM 系統', 'Coarse-grained: OpenMM system not created', '粗視化：OpenMM の系を作れない', '조립화: OpenMM 계 생성 실패'),
        ('martini_openmm 讀不了拓撲。',
         'martini_openmm could not read the topology.',
         'martini_openmm がトポロジーを読めませんでした。',
         'martini_openmm이 토폴로지를 읽지 못했습니다.')),
    "cg count_mismatch": (('粗粒化：珠子數不一致', 'Coarse-grained: bead counts differ', '粗視化：ビーズ数の不一致', '조립화: 비드 수 불일치'),
        ('拓撲和座標的珠子數不同。',
         'The topology and the coordinates have different numbers of beads.',
         'トポロジーと座標のビーズ数が違います。',
         '토폴로지와 좌표의 비드 수가 다릅니다.')),
    "cg minimise": (('粗粒化：最小化失敗', 'Coarse-grained: minimisation failed', '粗視化：最小化の失敗', '조립화: 최소화 실패'),
        ('最小化後能量不是有限值，珠子可能重疊。請重建系統。',
         'The energy after minimisation is not finite; beads may overlap. Rebuild the system.',
         '最小化後のエネルギーが有限ではなく、ビーズが重なっている可能性があります。系を作り直してください。',
         '최소화 후 에너지가 유한하지 않아 비드가 겹쳤을 수 있습니다. 계를 다시 만드십시오.')),
    "cg dssp": (('粗粒化：二級結構', 'Coarse-grained: secondary structure', '粗視化：二次構造', '조립화: 이차 구조'),
        ('無法計算蛋白的二級結構。',
         "The protein's secondary structure could not be computed.",
         'タンパク質の二次構造を計算できませんでした。',
         '단백질의 이차 구조를 계산할 수 없습니다.')),
})

# D-92 binding target gates (Workflow.binding)
GATES.update({
    "binding path": (("結合自由能：拉離路徑", "Binding free energy: exit path", "結合自由エネルギー：引き離しの経路", "결합 자유 에너지: 당김 경로"),
                     ("這個配體往外拉的每個方向都會碰到口袋裡的其他配體，找不到乾淨的出口。可以先略過它，算其他配體。",
                      "Every way out for this ligand runs into another ligand in the pocket, so no clean exit was found. "
                      "You can leave it out and compute the other ligands.",
                      "このリガンドを引き出すどの方向にも、ポケット内の別のリガンドがあり、きれいな出口が見つかりません。"
                      "このリガンドを飛ばして、ほかのリガンドを計算できます。",
                      "이 리간드를 빼내는 모든 방향에 포켓 안의 다른 리간드가 있어 깨끗한 출구를 찾지 못했습니다. "
                      "이 리간드를 건너뛰고 다른 리간드를 계산할 수 있습니다.")),
    "binding target": (("結合自由能：無法計算", "Binding free energy: cannot be computed", "結合自由エネルギー：計算できない", "결합 자유 에너지: 계산할 수 없음"),
                       ("這個配體的結合自由能無法計算，原因寫在訊息裡。可以先略過它，算其他配體。",
                        "The binding free energy of this ligand cannot be computed; the message says why. You can leave it "
                        "out and compute the other ligands.",
                        "このリガンドの結合自由エネルギーは計算できません。理由はメッセージにあります。飛ばしてほかのリガンドを計算できます。",
                        "이 리간드의 결합 자유 에너지는 계산할 수 없습니다. 이유는 메시지에 있습니다. 건너뛰고 다른 리간드를 계산할 수 있습니다.")),
})
PREFIX.append(("略過 ", ("Leave this ligand out and compute the others", "このリガンドを飛ばしてほかを計算する",
                       "이 리간드를 건너뛰고 다른 리간드 계산")))

