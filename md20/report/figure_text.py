"""General figure language for the report (D-54; spec: docs/specs/report_language.md; style: docs/specs/writing_style.md).

Each figure kind has a title, a caption (what is drawn), a reading guide (the same in every project) and outcome
scenarios.  `classify_<kind>(data)` decides which scenarios hold for this run and returns filled sentences.
All texts are (zh, en, ja, ko) tuples (D-74); resolve them with md20.i18n.pick.  Pure Python + numpy.
"""
from __future__ import annotations

import numpy as np

FIG = {
    "docking_scores": {
        "title": ("對接姿勢分數", "Docking pose scores", "ドッキングポーズのスコア", "도킹 포즈 점수"),
        "caption": ("每個姿勢的 Vina 分數依名次排列。顏色代表叢集，★ 是選用的姿勢。",
                    "Vina score of each pose by rank. Colour marks the cluster and ★ marks the pose used.",
                    "各ポーズの Vina スコアを順位順に並べています。色はクラスター、★ は採用したポーズです。",
                    "각 포즈의 Vina 점수를 순위대로 나열했습니다. 색은 클러스터, ★는 선택한 포즈입니다."),
        "read": ("分數越負越好。兩個分數相差不到 1 kcal mol⁻¹ 時落在 Vina 的誤差內，無法區分。同一叢集裡有好幾個低分姿勢，表示搜尋收斂到同一種結合模式。",
                 "More negative is better. Scores less than 1 kcal mol⁻¹ apart are within Vina's error and cannot be told apart. "
                 "Several low-scoring poses in one cluster mean the search converged on one binding mode.",
                 "スコアは負に大きいほど良好です。差が 1 kcal mol⁻¹ 未満の2つのスコアは Vina の誤差の範囲内にあり、区別できません。"
                 "同じクラスターに低スコアのポーズが複数あれば、探索は1つの結合様式に収束しています。",
                 "점수는 음수로 클수록 좋습니다. 두 점수의 차이가 1 kcal mol⁻¹ 미만이면 Vina 오차 범위 안이므로 구별할 수 없습니다. "
                 "같은 클러스터에 낮은 점수의 포즈가 여러 개 있으면 탐색이 하나의 결합 모드로 수렴한 것입니다."),
    },
    "screen_ranking": {
        "title": ("篩選排名", "Screening ranking", "スクリーニングの順位", "스크리닝 순위"),
        "caption": ("化合物依 Vina 分數排序。灰色帶是與最佳分數相差 1 kcal mol⁻¹ 以內的範圍。",
                    "Compounds ranked by Vina score. The grey band covers scores within 1 kcal mol⁻¹ of the best.",
                    "化合物を Vina スコア順に並べています。灰色の帯は最良スコアとの差が 1 kcal mol⁻¹ 以内の範囲です。",
                    "화합물을 Vina 점수 순으로 정렬했습니다. 회색 띠는 최고 점수와의 차이가 1 kcal mol⁻¹ 이내인 범위입니다."),
        "read": ("灰色帶內的化合物彼此排不出先後。分子越大，分數往往越負，所以要同時看配體效率，也就是每個重原子的分數。",
                 "Compounds inside the grey band cannot be ranked against each other. Larger molecules tend to score more "
                 "negatively, so read the ligand efficiency (score per heavy atom) as well.",
                 "灰色の帯の中の化合物どうしは順位をつけられません。分子が大きいほどスコアは負になりやすいため、"
                 "リガンド効率（重原子あたりのスコア）もあわせて見てください。",
                 "회색 띠 안의 화합물끼리는 순위를 매길 수 없습니다. 분자가 클수록 점수가 더 음수가 되기 쉬우므로 "
                 "리간드 효율(중원자당 점수)도 함께 보십시오."),
    },
    "rmsd": {
        "title": ("主鏈 RMSD", "Backbone RMSD", "主鎖 RMSD", "주사슬 RMSD"),
        "caption": ("主鏈原子相對於起始結構的均方根偏差隨時間的變化，每條線是一個系統。",
                    "Root-mean-square deviation of the backbone atoms from the starting structure over time. Each line is one system.",
                    "主鎖原子の初期構造からの二乗平均平方根偏差の時間変化です。線1本が1つの系です。",
                    "주사슬 원자가 시작 구조에서 벗어난 평균 제곱근 편차의 시간 변화입니다. 선 하나가 시스템 하나입니다."),
        "read": ("曲線先上升再進入平台，代表結構已經平衡。平台高度反映構形調整的幅度，小於 2 Å 算小，2 到 3 Å 中等，大於 3 Å 大。後半段還在上升，就是尚未平衡。",
                 "The curve rises and then levels off once the structure has equilibrated. The plateau height shows how much "
                 "the conformation adjusted. Below 2 Å the change is small, 2–3 Å is moderate and above 3 Å is large. A curve "
                 "still rising in the second half has not equilibrated.",
                 "曲線がいったん上昇してから平坦になれば、構造は平衡に達しています。平坦部の高さは構造変化の大きさを表し、"
                 "2 Å 未満は小さく、2〜3 Å は中程度、3 Å を超えると大きな変化です。後半になっても上昇が続く場合は、まだ平衡に達していません。",
                 "곡선이 올라갔다가 평탄해지면 구조가 평형에 도달한 것입니다. 평탄 구간의 높이는 구조 조정의 크기를 나타내며, "
                 "2 Å 미만은 작고 2~3 Å은 중간, 3 Å 초과는 큽니다. 후반부에도 계속 오르면 아직 평형에 도달하지 않은 것입니다."),
    },
    "rg": {
        "title": ("迴轉半徑", "Radius of gyration", "回転半径", "회전 반경"),
        "caption": ("蛋白迴轉半徑隨時間的變化。", "Radius of gyration of the protein over time.",
                    "タンパク質の回転半径の時間変化です。", "단백질 회전 반경의 시간 변화입니다."),
        "read": ("數值穩定代表蛋白維持緊密摺疊，持續增加代表部分展開。",
                 "A stable value means the protein stays compactly folded. A steady increase means partial unfolding.",
                 "値が安定していれば、タンパク質はコンパクトに折りたたまれたままです。増え続ける場合は部分的にほどけています。",
                 "값이 안정적이면 단백질이 조밀하게 접힌 상태를 유지하는 것입니다. 계속 증가하면 부분적으로 풀리고 있는 것입니다."),
    },
    "ligand_rmsd": {
        "title": ("配體在口袋中的位移", "Ligand displacement in the pocket", "ポケット内でのリガンドの変位", "포켓 안에서 리간드의 변위"),
        "caption": ("以蛋白口袋對齊後，配體相對於對接姿勢的 RMSD。虛線是 3 Å。",
                    "Ligand RMSD from the docked pose after aligning on the pocket. The dashed line marks 3 Å.",
                    "ポケットで重ね合わせた後の、ドッキングポーズからのリガンド RMSD です。破線は 3 Å です。",
                    "포켓 기준으로 정렬한 뒤 도킹 포즈에 대한 리간드 RMSD입니다. 점선은 3 Å입니다."),
        "read": ("低於 2 Å 代表維持對接姿勢，2 到 3 Å 是姿勢調整，持續高於 3 Å 代表配體離開了原本的結合位。短暫超過 3 Å 又回來屬於擺動，不代表解離。",
                 "Below 2 Å the docked pose is kept, 2–3 Å is a pose adjustment, and staying above 3 Å means the ligand left "
                 "the docked site. A brief excursion above 3 Å followed by a return is a fluctuation, not dissociation.",
                 "2 Å 未満ならドッキングポーズを保っています。2〜3 Å はポーズの調整で、3 Å を超えたままならリガンドは元の結合部位を離れています。"
                 "一時的に 3 Å を超えて戻ってくる場合はゆらぎであり、解離ではありません。",
                 "2 Å 미만이면 도킹 포즈를 유지하는 것이고, 2~3 Å은 포즈 조정입니다. 3 Å 초과가 계속되면 리간드가 원래 결합 부위를 떠난 것입니다. "
                 "잠시 3 Å을 넘었다가 돌아오는 것은 요동이며 해리가 아닙니다."),
    },
    "rmsf": {
        "title": ("殘基柔性（RMSF）", "Residue flexibility (RMSF)", "残基の柔軟性（RMSF）", "잔기 유연성(RMSF)"),
        "caption": ("每個殘基 Cα 原子的均方根擾動。多個系統疊在一起畫，下方是複合物減去蛋白單獨的差值。",
                    "Root-mean-square fluctuation of each residue's Cα atom, with the systems overlaid. The panel below shows "
                    "the complex minus the protein alone.",
                    "各残基の Cα 原子の二乗平均平方根ゆらぎです。複数の系を重ねて表示し、下段は複合体からタンパク質単独を引いた差です。",
                    "각 잔기 Cα 원자의 평균 제곱근 요동입니다. 여러 시스템을 겹쳐 그렸고, 아래쪽은 복합체에서 단백질 단독을 뺀 차이입니다."),
        "read": ("峰值通常出現在 loop 與末端。結合後柔性下降的區域多半就是結合位，或與結合位耦合。柔性上升的區域則受到結合的擾動。",
                 "Peaks are usually loops and termini. Regions that become more rigid on binding usually line the binding site "
                 "or are coupled to it. Regions that become more flexible are perturbed by binding.",
                 "ピークは通常ループや末端に現れます。結合後に柔軟性が下がる領域は、多くの場合結合部位そのものか、結合部位と連動する領域です。"
                 "柔軟性が上がる領域は結合によって乱されています。",
                 "피크는 보통 루프와 말단에서 나타납니다. 결합 후 유연성이 낮아지는 영역은 대개 결합 부위이거나 결합 부위와 연동된 영역입니다. "
                 "유연성이 높아지는 영역은 결합으로 교란된 부위입니다."),
    },
    "contacts": {
        "title": ("接觸頻率", "Contact frequency", "接触頻度", "접촉 빈도"),
        "caption": ("模擬時間中每個殘基與配體距離小於 4 Å 的時間比例，依頻率排序。",
                    "Fraction of simulation time each residue spends within 4 Å of the ligand, sorted by frequency.",
                    "各残基がリガンドから 4 Å 以内にある時間の割合を、頻度の高い順に並べています。",
                    "각 잔기가 리간드로부터 4 Å 이내에 있는 시간의 비율을 빈도순으로 정렬했습니다."),
        "read": ("75 % 以上是持續接觸，也就是結合的錨點。25 % 到 75 % 是間歇接觸，低於 25 % 是偶發接觸。",
                 "Above 75 % is a persistent contact that anchors the ligand. 25–75 % is intermittent and below 25 % is occasional.",
                 "75 % 以上は持続的な接触で、結合のアンカーになります。25〜75 % は断続的、25 % 未満はまれな接触です。",
                 "75 % 이상은 지속적인 접촉으로 결합의 앵커입니다. 25~75 %는 간헐적, 25 % 미만은 드문 접촉입니다."),
    },
    "smd": {
        "title": ("導向分子動力學的拉力與功", "Force and work in steered molecular dynamics",
                  "ステアード分子動力学の力と仕事", "조향 분자동역학의 힘과 일"),
        "caption": ("拉力與累積功對彈簧位置作圖。", "Pulling force and accumulated work against the spring position.",
                    "引っ張る力と累積仕事を、ばねの位置に対してプロットしています。", "당기는 힘과 누적 일을 스프링 위치에 대해 그렸습니다."),
        "read": ("最大拉力對應主要的斷裂事件。功在末段變平，表示配體已完全脫離。功和拉速有關，它不是自由能。",
                 "The force maximum marks the main rupture event. Work that levels off at the end means the ligand has fully "
                 "detached. The work depends on the pulling speed and is not a free energy.",
                 "最大の力は主な破断イベントに対応します。終盤で仕事が平坦になれば、リガンドは完全に離脱しています。"
                 "仕事は引っ張る速度に依存し、自由エネルギーではありません。",
                 "최대 힘은 주요 파단 사건에 해당합니다. 마지막 구간에서 일이 평탄해지면 리간드가 완전히 떨어져 나간 것입니다. "
                 "일은 당김 속도에 따라 달라지며 자유 에너지가 아닙니다."),
    },
    "umbrella": {
        "title": ("傘狀採樣窗口分佈", "Umbrella-sampling window distributions",
                  "アンブレラサンプリングのウィンドウ分布", "엄브렐라 샘플링 윈도우 분포"),
        "caption": ("每個窗口沿反應座標的取樣分佈。", "Sampling distribution of each window along the reaction coordinate.",
                    "反応座標に沿った各ウィンドウのサンプリング分布です。", "반응 좌표를 따라 그린 각 윈도우의 샘플링 분포입니다."),
        "read": ("相鄰的分佈必須互相重疊，自由能剖面才會連續。出現空隙的位置，剖面不可信。",
                 "Neighbouring distributions must overlap for the free-energy profile to be continuous. Where a gap appears, "
                 "the profile is unreliable.",
                 "隣り合う分布が重なっていなければ、自由エネルギープロファイルは連続しません。すき間がある位置のプロファイルは信頼できません。",
                 "이웃한 분포가 서로 겹쳐야 자유 에너지 프로파일이 연속됩니다. 틈이 생긴 위치에서는 프로파일을 믿을 수 없습니다."),
    },
    "pmf": {
        "title": ("自由能剖面（PMF）", "Free-energy profile (PMF)", "自由エネルギープロファイル（PMF）", "자유 에너지 프로파일(PMF)"),
        "caption": ("自由能隨配體與口袋距離的變化，陰影是自助法（bootstrap）誤差。",
                    "Free energy against the ligand–pocket distance. The shading is the bootstrap error.",
                    "リガンドとポケットの距離に対する自由エネルギーです。影はブートストラップ誤差です。",
                    "리간드와 포켓 사이 거리에 따른 자유 에너지입니다. 음영은 부트스트랩 오차입니다."),
        "read": ("最低點是結合狀態，從最低點到末端平台的高度就是 ΔPMF。末端必須平坦，否則 ΔPMF 會被低估。",
                 "The minimum is the bound state, and its depth below the final plateau is ΔPMF. The end must be flat, "
                 "otherwise ΔPMF is underestimated.",
                 "最低点が結合状態で、最低点から末端の平坦部までの高さが ΔPMF です。末端が平坦でないと ΔPMF は過小評価されます。",
                 "최저점이 결합 상태이고, 최저점에서 끝부분 평탄 구간까지의 높이가 ΔPMF입니다. 끝부분이 평탄하지 않으면 ΔPMF가 과소평가됩니다."),
    },
}


def S(level, zh, en, ja="", ko=""):
    """One scenario sentence.  Positional order zh, en, ja, ko; missing Japanese or Korean falls back to English."""
    return {"level": level, "text": (zh, en, ja or en, ko or en)}


def _plateau(t, y):
    t, y = np.asarray(t, float), np.asarray(y, float)
    n = len(y)
    h = y[n // 2:]
    th = t[n // 2:] if len(t) >= n else np.arange(len(h), dtype=float)
    drift = float(np.polyfit(th, h, 1)[0] * (th[-1] - th[0])) if len(h) > 2 and th[-1] > th[0] else 0.0
    return float(h.mean()), float(h.std()), drift


# ------------------------------------------------------------------------------------------- classifiers
def classify_docking_scores(name: str, poses: list[dict], chosen_rank: int | None) -> list[dict]:
    if not poses:
        return []
    sc = sorted(p["score"] for p in poses)
    gap = sc[1] - sc[0] if len(sc) > 1 else None
    rank = chosen_rank or 1
    p = next((q for q in poses if q["rank"] == rank), poses[0])
    frac = min(1.0, (p.get("cluster_size") or 1) / max(1, len(poses)))
    out = []
    if gap is not None and gap >= 1.0 and frac >= 0.3:
        out.append(S("good",
                     f"{name} 的最佳姿勢（{sc[0]:.2f} kcal mol⁻¹）比第二名低 {gap:.2f} kcal mol⁻¹（≥ 1），所屬叢集占全部姿勢的 {frac:.0%}，結合模式明確。",
                     f"For {name} the best pose ({sc[0]:.2f} kcal mol⁻¹) is {gap:.2f} kcal mol⁻¹ below the second (≥ 1) and its "
                     f"cluster holds {frac:.0%} of all poses, so the binding mode is clear.",
                     f"{name} の最良ポーズ（{sc[0]:.2f} kcal mol⁻¹）は2位より {gap:.2f} kcal mol⁻¹ 低く（≥ 1）、そのクラスターは全ポーズの "
                     f"{frac:.0%} を占めます。結合様式ははっきりしています。",
                     f"{name}의 최고 포즈({sc[0]:.2f} kcal mol⁻¹)는 2위보다 {gap:.2f} kcal mol⁻¹ 낮고(≥ 1), 해당 클러스터가 전체 포즈의 "
                     f"{frac:.0%}를 차지합니다. 결합 모드가 분명합니다."))
    elif gap is not None and gap < 1.0:
        out.append(S("note",
                     f"{name} 的前兩名分數相差 {gap:.2f} kcal mol⁻¹（< 1），在 Vina 的誤差內等價。結合模式不能只看分數決定，要看模擬中的穩定性。",
                     f"For {name} the top two poses differ by {gap:.2f} kcal mol⁻¹ (< 1), equivalent within Vina's error. The "
                     "score alone cannot decide the binding mode, so judge it by stability in simulation.",
                     f"{name} の上位2ポーズのスコア差は {gap:.2f} kcal mol⁻¹（< 1）で、Vina の誤差の範囲内では同等です。"
                     "結合様式はスコアだけでは決められないため、シミュレーションでの安定性で判断します。",
                     f"{name}의 상위 두 포즈는 점수 차이가 {gap:.2f} kcal mol⁻¹(< 1)로 Vina 오차 범위 안에서 같습니다. "
                     "결합 모드는 점수만으로 정할 수 없으므로 시뮬레이션에서의 안정성으로 판단합니다."))
    if frac < 0.3:
        out.append(S("caution",
                     f"{name} 選用姿勢的叢集只占 {frac:.0%}（< 30 %），低分姿勢分散在不同叢集，搜尋沒有收斂。請提高搜尋強度或縮小搜尋區。",
                     f"For {name} the chosen pose's cluster holds only {frac:.0%} (< 30 %). Low-scoring poses are spread over "
                     "different clusters and the search did not converge. Raise the exhaustiveness or narrow the box.",
                     f"{name} で採用したポーズのクラスターは {frac:.0%}（< 30 %）しかありません。低スコアのポーズが複数のクラスターに散らばっており、"
                     "探索は収束していません。探索の徹底度（exhaustiveness）を上げるか、探索領域を狭めてください。",
                     f"{name}에서 선택한 포즈의 클러스터는 {frac:.0%}(< 30 %)에 불과합니다. 낮은 점수의 포즈가 여러 클러스터에 흩어져 있어 "
                     "탐색이 수렴하지 않았습니다. 탐색 강도(exhaustiveness)를 높이거나 탐색 영역을 좁히십시오."))
    r = p.get("rmsd_ref")
    if r is not None:
        out.append(S("good",
                     f"重新對接與共結晶姿勢的 RMSD 為 {r:.2f} Å（≤ 2 Å），對接設定能重現晶體結構。",
                     f"Redocking reproduces the co-crystal pose at {r:.2f} Å RMSD (≤ 2 Å), so the docking setup is credible.",
                     f"再ドッキングで共結晶ポーズを RMSD {r:.2f} Å（≤ 2 Å）で再現できました。ドッキングの設定は信頼できます。",
                     f"재도킹이 공결정 포즈를 RMSD {r:.2f} Å(≤ 2 Å)로 재현했습니다. 도킹 설정을 믿을 수 있습니다.")
                   if r <= 2.0 else
                   S("caution",
                     f"重新對接與共結晶姿勢的 RMSD 為 {r:.2f} Å（> 2 Å），對接設定沒能重現晶體結構，其他姿勢也要保守看待。",
                     f"Redocking deviates from the co-crystal pose by {r:.2f} Å (> 2 Å). The setup does not reproduce the "
                     "crystal, so read the other poses with caution too.",
                     f"再ドッキングと共結晶ポーズの RMSD は {r:.2f} Å（> 2 Å）です。設定が結晶構造を再現できていないため、ほかのポーズも慎重に扱ってください。",
                     f"재도킹 결과가 공결정 포즈와 {r:.2f} Å(> 2 Å) 차이 납니다. 설정이 결정 구조를 재현하지 못했으므로 다른 포즈도 신중하게 보십시오."))
    return out


def classify_screen(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    sc = [r["score"] for r in rows]
    out = []
    if len(sc) > 1 and sc[1] - sc[0] >= 1.0:
        lead, top = sc[1] - sc[0], rows[0]["name"]
        out.append(S("good",
                     f"{top} 領先第二名 {lead:.2f} kcal mol⁻¹（≥ 1），是明確的首選。",
                     f"{top} leads the second compound by {lead:.2f} kcal mol⁻¹ (≥ 1) and is a clear first choice.",
                     f"{top} は2位を {lead:.2f} kcal mol⁻¹ 上回っており（≥ 1）、明確な第一候補です。",
                     f"1위 {top} 화합물이 2위보다 {lead:.2f} kcal mol⁻¹ 앞섭니다(≥ 1). 분명한 첫 번째 후보입니다."))
    near = [r for r in rows if r["score"] - sc[0] < 1.0]
    if len(near) >= 3:
        nz, ne = "、".join(r["name"] for r in near[:6]), ", ".join(r["name"] for r in near[:6])
        out.append(S("note",
                     f"{len(near)} 個化合物與最佳分數相差不到 1 kcal mol⁻¹（{nz}），它們的先後順序沒有意義。請一起帶進下一步，或依配體效率與化學多樣性挑選。",
                     f"{len(near)} compounds fall within 1 kcal mol⁻¹ of the best ({ne}). Their order carries no meaning, so take "
                     "them forward together or choose by ligand efficiency and chemical diversity.",
                     f"{len(near)} 個の化合物が最良スコアから 1 kcal mol⁻¹ 以内にあります（{nz}）。この中での順位には意味がないため、"
                     "まとめて次の段階に進めるか、リガンド効率と化学的多様性で選んでください。",
                     f"화합물 {len(near)}개가 최고 점수와 1 kcal mol⁻¹ 이내입니다({ne}). 이들 사이의 순서는 의미가 없으므로 함께 다음 단계로 "
                     "넘기거나 리간드 효율과 화학적 다양성으로 고르십시오."))
    ha = np.array([r.get("heavy_atoms") or np.nan for r in rows], float)
    ok = np.isfinite(ha)
    if ok.sum() >= 6:
        rr = float(np.corrcoef(ha[ok], np.asarray(sc)[ok])[0, 1])
        if rr <= -0.6:
            out.append(S("caution",
                         f"分數與重原子數的相關係數為 {rr:.2f}（≤ −0.6），排名主要反映分子大小。請先依配體效率排序再挑選。",
                         f"Score and heavy-atom count correlate at r = {rr:.2f} (≤ −0.6), so the ranking mostly reflects molecular "
                         "size. Rank by ligand efficiency before choosing.",
                         f"スコアと重原子数の相関係数は {rr:.2f}（≤ −0.6）で、順位は主に分子の大きさを反映しています。リガンド効率で並べ直してから選んでください。",
                         f"점수와 중원자 수의 상관계수가 {rr:.2f}(≤ −0.6)로, 순위가 주로 분자 크기를 반영합니다. 리간드 효율로 다시 정렬한 뒤 고르십시오."))
    return out


def classify_rmsd(series: dict) -> list[dict]:
    """series: {system: (t_ns, rmsd_A)}"""
    out, means = [], {}
    for key, (t, y) in series.items():
        if len(y) < 8:
            continue
        m, sd, drift = _plateau(t, y)
        means[key] = m
        tail = (f"後半段 {m:.2f} ± {sd:.2f} Å，漂移 {drift:+.2f} Å", f"second half {m:.2f} ± {sd:.2f} Å, drift {drift:+.2f} Å",
                f"後半 {m:.2f} ± {sd:.2f} Å、ドリフト {drift:+.2f} Å", f"후반부 {m:.2f} ± {sd:.2f} Å, 드리프트 {drift:+.2f} Å")
        if abs(drift) > 0.5:
            out.append(S("caution",
                         f"{key}：後半段的 RMSD 仍在變化（{tail[0]}，> 0.5 Å），結構尚未平衡。需要延長模擬，後續分析只能當定性參考。",
                         f"{key}: RMSD is still changing in the second half ({tail[1]}, > 0.5 Å). The structure has not "
                         "equilibrated, so a longer simulation is needed and later analyses are qualitative only.",
                         f"{key}：後半でも RMSD が変化し続けています（{tail[2]}、> 0.5 Å）。構造はまだ平衡に達していません。"
                         "シミュレーションを延長する必要があり、以降の解析は定性的な参考にとどまります。",
                         f"{key}: 후반부에도 RMSD가 계속 변합니다({tail[3]}, > 0.5 Å). 구조가 아직 평형에 도달하지 않았으므로 "
                         "시뮬레이션을 연장해야 하며, 이후 분석은 정성적인 참고로만 쓰십시오."))
        elif m > 3.0:
            out.append(S("caution",
                         f"{key}：RMSD 平台高於 3 Å（{tail[0]}），蛋白發生大幅重排。請確認起始結構與約束策略是否合適。",
                         f"{key}: the RMSD plateau is above 3 Å ({tail[1]}). The protein rearranged substantially, so check the "
                         "starting structure and the restraint strategy.",
                         f"{key}：RMSD の平坦部が 3 Å を超えています（{tail[2]}）。タンパク質が大きく再配置しているため、初期構造と拘束の方針が適切か確認してください。",
                         f"{key}: RMSD 평탄 구간이 3 Å을 넘습니다({tail[3]}). 단백질이 크게 재배열되었으므로 시작 구조와 구속 전략이 적절한지 확인하십시오."))
        elif m > 2.0:
            out.append(S("note",
                         f"{key}：RMSD 經過一段調整後停在 2 到 3 Å 的平台（{tail[0]}），屬於中度構形調整，常見於 loop 鬆弛。",
                         f"{key}: after an adjustment RMSD levels off at 2–3 Å ({tail[1]}), a moderate conformational change "
                         "typical of loop relaxation.",
                         f"{key}：RMSD は調整を経て 2〜3 Å の平坦部に落ち着いています（{tail[2]}）。中程度の構造変化で、ループの緩和によく見られます。",
                         f"{key}: RMSD가 한 차례 조정을 거쳐 2~3 Å 평탄 구간에 머뭅니다({tail[3]}). 중간 정도의 구조 조정이며 루프 이완에서 흔히 보입니다."))
        else:
            out.append(S("good",
                         f"{key}：RMSD 進入低於 2 Å 的平台（{tail[0]}），相對第一幀的整體偏移小。RMSD 平台只是平衡的必要條件之一，不能單獨證明已平衡。",
                         f"{key}: RMSD levels off below 2 Å ({tail[1]}), a small overall deviation from the first frame. An RMSD "
                         "plateau is one necessary sign of equilibration, not proof of it.",
                         f"{key}：RMSD は 2 Å 未満で平坦になっています（{tail[2]}）。最初のフレームからの全体のずれは小さいです。RMSD の平坦化は平衡の"
                         "必要条件の一つにすぎず、それだけで平衡とはいえません。",
                         f"{key}: RMSD가 2 Å 미만에서 평탄해졌습니다({tail[3]}). 첫 프레임 대비 전체 편차가 작습니다. RMSD 평탄은 평형의 필요조건 "
                         "중 하나일 뿐이며 그것만으로 평형을 증명하지는 않습니다."))
    ref = next((k for k in means if k.lower().startswith("apo")), None)
    if ref is not None:
        for k, m in means.items():
            if k == ref:
                continue
            d = m - means[ref]
            if d <= -0.3:
                out.append(S("good",
                             f"{k} 的平台比蛋白單獨低 {abs(d):.2f} Å（≥ 0.3）。這是觀察到的差異；只有一條軌跡、參考構形不同時，不能推論配體讓蛋白更穩定。",
                             f"{k} plateaus {abs(d):.2f} Å below the protein alone (≥ 0.3). This is an observed difference; with single "
                             "trajectories and their own reference frames it does not show that the ligand stabilises the protein.",
                             f"{k} の平坦部はタンパク質単独より {abs(d):.2f} Å 低くなっています（≥ 0.3）。これは観察された差であり、軌跡が1本ずつで基準構造も"
                             "異なるため、リガンドがタンパク質を安定化したとはいえません。",
                             f"{k} 시스템의 평탄 구간이 단백질 단독보다 {abs(d):.2f} Å 낮습니다(≥ 0.3). 관찰된 차이일 뿐이며, 궤적이 하나씩이고 기준 "
                             "구조도 달라 리간드가 단백질을 안정화했다고 할 수 없습니다."))
            elif d >= 0.3:
                out.append(S("note",
                             f"{k} 的平台比蛋白單獨高 {d:.2f} Å（≥ 0.3），這次模擬中有配體時蛋白相對起點偏移較大（觀察到的差異）。",
                             f"{k} plateaus {d:.2f} Å above the protein alone (≥ 0.3): in this simulation the protein deviates more from "
                             "its start with the ligand present (an observed difference).",
                             f"{k} の平坦部はタンパク質単独より {d:.2f} Å 高く（≥ 0.3）、リガンドが結合すると構造の調整が大きくなります。",
                             f"{k} 시스템의 평탄 구간이 단백질 단독보다 {d:.2f} Å 높습니다(≥ 0.3). 리간드가 결합하면 단백질의 구조 조정이 더 큽니다."))
            else:
                out.append(S("note",
                             f"{k} 與蛋白單獨的平台相差 {d:+.2f} Å（小於 0.3），整體構形穩定性相當。",
                             f"{k} and the protein alone plateau within {d:+.2f} Å of each other (less than 0.3), so overall "
                             "stability is comparable.",
                             f"{k} とタンパク質単独の平坦部の差は {d:+.2f} Å（0.3 未満）で、全体の安定性は同程度です。",
                             f"{k} 시스템과 단백질 단독의 평탄 구간 차이는 {d:+.2f} Å(0.3 미만)로, 전체 안정성이 비슷합니다."))
    return out


def classify_rg(series: dict) -> list[dict]:
    out = []
    for key, (t, y) in series.items():
        y = np.asarray(y, float)
        if len(y) < 10:
            continue
        start = float(y[: max(1, len(y) // 10)].mean())
        m, sd, _ = _plateau(t, y)
        change = (m - start) / start
        if change > 0.05:
            out.append(S("caution",
                         f"{key}：迴轉半徑從 {start:.2f} Å 增加到 {m:.2f} Å（{change:+.1%}，> 5 %），蛋白明顯擴張，可能部分展開。",
                         f"{key}: radius of gyration grows from {start:.2f} Å to {m:.2f} Å ({change:+.1%}, > 5 %). The protein "
                         "expands markedly and may be partly unfolding.",
                         f"{key}：回転半径が {start:.2f} Å から {m:.2f} Å に増えています（{change:+.1%}、> 5 %）。"
                         "タンパク質がはっきり膨らんでおり、部分的にほどけている可能性があります。",
                         f"{key}: 회전 반경이 처음 {start:.2f} Å에서 후반 {m:.2f} Å까지 늘었습니다({change:+.1%}, > 5 %). "
                         "단백질이 뚜렷하게 팽창했으며 부분적으로 풀리고 있을 수 있습니다."))
        elif change > 0.02:
            out.append(S("note",
                         f"{key}：迴轉半徑從 {start:.2f} Å 增加到 {m:.2f} Å（{change:+.1%}），輕微擴張，多半來自表面 loop 鬆弛。",
                         f"{key}: radius of gyration grows from {start:.2f} Å to {m:.2f} Å ({change:+.1%}), a slight expansion "
                         "usually from surface loops.",
                         f"{key}：回転半径が {start:.2f} Å から {m:.2f} Å に増えています（{change:+.1%}）。わずかな膨張で、多くは表面ループの緩和によるものです。",
                         f"{key}: 회전 반경이 처음 {start:.2f} Å에서 후반 {m:.2f} Å까지 늘었습니다({change:+.1%}). 약간의 팽창이며 대개 표면 루프의 이완 때문입니다."))
        else:
            out.append(S("good",
                         f"{key}：迴轉半徑維持在 {m:.2f} ± {sd:.2f} Å，蛋白保持緊密摺疊。",
                         f"{key}: radius of gyration stays at {m:.2f} ± {sd:.2f} Å, so the protein remains compactly folded.",
                         f"{key}：回転半径は {m:.2f} ± {sd:.2f} Å で安定しており、タンパク質はコンパクトに折りたたまれたままです。",
                         f"{key}: 회전 반경이 {m:.2f} ± {sd:.2f} Å 수준을 유지합니다. 단백질이 조밀하게 접힌 상태를 유지합니다."))
    return out


def classify_ligand_rmsd(key: str, lig: str, t, y) -> list[dict]:
    t, y = np.asarray(t, float), np.asarray(y, float)
    if len(y) < 5:
        return []
    last = float(y[-max(1, len(y) // 5):].mean())
    mx = float(y.max())
    if last >= 3.0:
        above = y >= 3.0
        idx = next((i for i in range(len(y)) if above[i:].all()), None)
        when = ("", "", "", "")
        if idx is not None and idx < len(t):
            when = (f"，約在 {t[idx]:.1f} ns 之後持續高於 3 Å", f", staying above 3 Å from about {t[idx]:.1f} ns",
                    f"、約 {t[idx]:.1f} ns 以降は 3 Å を超えたまま", f", 약 {t[idx]:.1f} ns 이후 계속 3 Å 초과")
        return [S("caution",
                  f"{key} 的 {lig}：最後 20 % 時間平均 {last:.1f} Å{when[0]}，配體離開了對接位置。這個對接姿勢在動態中站不住，對接分數不能當作結合的證據。",
                  f"{lig} in {key}: {last:.1f} Å on average over the last 20 %{when[1]}. The ligand left the docked position, "
                  "so the docked pose does not hold in dynamics and its score is not evidence of binding.",
                  f"{key} の {lig}：最後の 20 % の平均は {last:.1f} Å{when[2]}です。リガンドはドッキング位置を離れました。"
                  "このドッキングポーズは動的には成り立たず、ドッキングスコアは結合の根拠になりません。",
                  f"{key}의 {lig}: 마지막 20 % 동안 평균 {last:.1f} Å{when[3]}입니다. 리간드가 도킹 위치를 떠났습니다. "
                  "이 도킹 포즈는 동역학에서 유지되지 않으므로 도킹 점수를 결합의 근거로 볼 수 없습니다.")]
    if mx > 3.0 and last < 2.0:
        return [S("note",
                  f"{key} 的 {lig}：曾短暫偏離到 {mx:.1f} Å，之後回到口袋（最後 20 % 為 {last:.1f} Å），屬於結合狀態下的擺動。",
                  f"{lig} in {key}: briefly moved out to {mx:.1f} Å and returned (last 20 %: {last:.1f} Å), a fluctuation "
                  "within the bound state.",
                  f"{key} の {lig}：一時的に {mx:.1f} Å まで外れた後、ポケットに戻っています（最後の 20 % は {last:.1f} Å）。結合状態の中でのゆらぎです。",
                  f"{key}의 {lig}: 잠시 {mx:.1f} Å까지 벗어났다가 포켓으로 돌아왔습니다(마지막 20 %: {last:.1f} Å). 결합 상태 안에서의 요동입니다.")]
    if last >= 2.0:
        return [S("note",
                  f"{key} 的 {lig}：留在口袋內，但姿勢有調整（最後 20 % 為 {last:.1f} Å，介於 2 到 3 Å），模擬中的結合模式與對接姿勢不完全相同。",
                  f"{lig} in {key}: stays in the pocket but adjusts its pose (last 20 %: {last:.1f} Å, 2–3 Å). The simulated "
                  "binding mode differs somewhat from the docked one.",
                  f"{key} の {lig}：ポケット内にとどまっていますが、ポーズは調整されています（最後の 20 % は {last:.1f} Å、2〜3 Å）。"
                  "シミュレーション中の結合様式はドッキングポーズと完全には一致しません。",
                  f"{key}의 {lig}: 포켓 안에 머물지만 포즈가 조정되었습니다(마지막 20 %: {last:.1f} Å, 2~3 Å). "
                  "시뮬레이션의 결합 모드가 도킹 포즈와 완전히 같지는 않습니다.")]
    return [S("good",
              f"{key} 的 {lig}：全程維持對接姿勢（最後 20 % 為 {last:.1f} Å，< 2 Å），結合模式在模擬時間內穩定。",
              f"{lig} in {key}: keeps the docked pose throughout (last 20 %: {last:.1f} Å, < 2 Å). The binding mode is stable "
              "over the simulated time.",
              f"{key} の {lig}：全体を通してドッキングポーズを保っています（最後の 20 % は {last:.1f} Å、< 2 Å）。結合様式はシミュレーション時間内で安定です。",
              f"{key}의 {lig}: 전 구간에서 도킹 포즈를 유지했습니다(마지막 20 %: {last:.1f} Å, < 2 Å). 결합 모드가 시뮬레이션 시간 동안 안정적입니다.")]


def classify_rmsf(names: list[str], ref: np.ndarray, other: np.ndarray, label: str) -> list[dict]:
    ref, other = np.asarray(ref, float), np.asarray(other, float)
    n = min(len(ref), len(other))
    if n < 5:
        return []
    d = other[:n] - ref[:n]
    out = []
    order = np.argsort(d)
    rig = [(names[i] if i < len(names) else str(i), d[i]) for i in order[:6] if d[i] <= -0.3]
    if rig:
        rz = "、".join(f"{a}（{b:+.2f} Å）" for a, b in rig)
        re_ = ", ".join(f"{a} ({b:+.2f} Å)" for a, b in rig)
        out.append(S("good",
                     f"{label} 中柔性下降最多的殘基是 {rz}。這些位置多半構成結合位，或與結合位耦合。",
                     f"Residues that become most rigid in {label} are {re_}. They usually form or couple to the binding site.",
                     f"{label} で柔軟性が最も下がった残基は {rz} です。これらの位置は多くの場合、結合部位そのものか、結合部位と連動しています。",
                     f"{label}에서 유연성이 가장 많이 낮아진 잔기는 {re_}입니다. 이 위치들은 대개 결합 부위를 이루거나 결합 부위와 연동됩니다."))
    dm = float(d.mean())
    if dm >= 0.2:
        out.append(S("caution",
                     f"{label} 的平均 RMSF 比蛋白單獨高 {dm:.2f} Å（≥ 0.2），結合讓蛋白整體變得較不穩定。",
                     f"Mean RMSF in {label} is {dm:.2f} Å above the protein alone (≥ 0.2), so binding makes the protein less stable overall.",
                     f"{label} の平均 RMSF はタンパク質単独より {dm:.2f} Å 高く（≥ 0.2）、結合によってタンパク質全体が不安定になっています。",
                     f"{label}의 평균 RMSF가 단백질 단독보다 {dm:.2f} Å 높습니다(≥ 0.2). 결합으로 단백질 전체가 덜 안정해졌습니다."))
    elif not rig:
        out.append(S("note",
                     f"{label} 與蛋白單獨的柔性分佈相當（平均差 {dm:+.2f} Å），沒有明顯受結合影響的區域。",
                     f"Flexibility in {label} matches the protein alone (mean difference {dm:+.2f} Å). No region is clearly affected by binding.",
                     f"{label} の柔軟性の分布はタンパク質単独と同程度です（平均差 {dm:+.2f} Å）。結合の影響がはっきり出ている領域はありません。",
                     f"{label}의 유연성 분포가 단백질 단독과 비슷합니다(평균 차이 {dm:+.2f} Å). 결합의 영향을 뚜렷하게 받은 영역은 없습니다."))
    return out


def classify_contacts(key: str, lig: str, freq: dict) -> list[dict]:
    items = sorted(freq.items(), key=lambda kv: -kv[1])
    if not items:
        return [S("caution", f"{key} 的 {lig}：模擬中沒有持續的口袋接觸。", f"{lig} in {key}: no sustained pocket contact during the simulation.",
                  f"{key} の {lig}：シミュレーション中、ポケットとの持続的な接触はありません。",
                  f"{key}의 {lig}: 시뮬레이션 동안 포켓과의 지속적인 접촉이 없습니다.")]
    anchors = [(a, b) for a, b in items if b >= 0.75]
    txt_zh = "、".join(f"{a}（{b:.0%}）" for a, b in (anchors or items)[:6])
    txt_en = ", ".join(f"{a} ({b:.0%})" for a, b in (anchors or items)[:6])
    if len(anchors) >= 3:
        return [S("good",
                  f"{key} 的 {lig} 有 {len(anchors)} 個持續接觸的錨點殘基（≥ 75 %），分別是 {txt_zh}。結合由多個作用點穩定住。",
                  f"{lig} in {key} has {len(anchors)} persistent anchor residues (≥ 75 %). They are {txt_en}, so binding is held "
                  "by several contacts.",
                  f"{key} の {lig} には持続的に接触するアンカー残基が {len(anchors)} 個あります（≥ 75 %）。{txt_zh} で、複数の接触点が結合を支えています。",
                  f"{key}의 {lig}에는 지속적으로 접촉하는 앵커 잔기가 {len(anchors)}개 있습니다(≥ 75 %). {txt_en}이며, 여러 접촉점이 결합을 붙잡고 있습니다.")]
    if anchors:
        return [S("note",
                  f"{key} 的 {lig} 只有 {len(anchors)} 個持續接觸的殘基（{txt_zh}），結合依賴少數作用點，對突變或結構差異比較敏感。",
                  f"{lig} in {key} has only {len(anchors)} persistent contact{'s' if len(anchors) > 1 else ''} ({txt_en}). "
                  "Binding relies on few interactions and is sensitive to mutations or structural differences.",
                  f"{key} の {lig} で持続的に接触する残基は {len(anchors)} 個だけです（{txt_zh}）。結合は少数の接触点に頼っており、変異や構造の違いの影響を受けやすくなります。",
                  f"{key}의 {lig}: 지속적으로 접촉하는 잔기가 {len(anchors)}개뿐입니다({txt_en}). 결합이 소수의 접촉점에 의존하므로 돌연변이나 구조 차이에 민감합니다.")]
    top = items[0][1]
    lvl = "caution" if top < 0.5 else "note"
    return [S(lvl,
              f"{key} 的 {lig} 沒有持續接觸（最高 {top:.0%}，{txt_zh}），配體在口袋內移動，結合鬆散。",
              f"{lig} in {key} has no persistent contact (highest {top:.0%}, {txt_en}). The ligand moves within the pocket and binds loosely.",
              f"{key} の {lig} には持続的な接触がありません（最大 {top:.0%}、{txt_zh}）。リガンドはポケット内を動き回っており、結合はゆるやかです。",
              f"{key}의 {lig}: 지속적인 접촉이 없습니다(최대 {top:.0%}, {txt_en}). 리간드가 포켓 안에서 움직이며 느슨하게 결합합니다.")]


def classify_smd(pos, force, work, name: str) -> list[dict]:
    pos, force, work = (np.asarray(x, float) for x in (pos, force, work))
    if len(force) < 10:
        return []
    out = []
    i = int(np.argmax(force))
    fmax = float(force[i])
    k = max(3, len(force) // 25)
    sm = np.convolve(force, np.ones(k) / k, mode="same")
    peaks = [j for j in range(1, len(sm) - 1) if sm[j] > sm[j - 1] and sm[j] >= sm[j + 1] and sm[j] >= 0.5 * sm.max()]
    merged = []
    for j in peaks:
        if not merged or pos[j] - pos[merged[-1]] > 0.15:
            merged.append(j)
    if len(merged) >= 2:
        pz, pe = "、".join(f"{pos[j]:.2f}" for j in merged), ", ".join(f"{pos[j]:.2f}" for j in merged)
        out.append(S("note",
                     f"{name}：拉力出現 {len(merged)} 個主要峰（位置 {pz} nm），配體分段脫離，每一段對應一組作用被打斷。",
                     f"{name}: the force shows {len(merged)} main peaks (at {pe} nm). The ligand detaches in stages, and each "
                     "stage breaks a set of interactions.",
                     f"{name}：力には {len(merged)} 個の主なピークがあります（位置 {pz} nm）。リガンドは段階的に離れ、各段階で一組の相互作用が切れています。",
                     f"{name}: 힘에 주요 피크가 {len(merged)}개 있습니다(위치 {pe} nm). 리간드가 단계적으로 떨어져 나가며, 각 단계에서 상호작용 한 묶음이 끊어집니다."))
    else:
        out.append(S("note",
                     f"{name}：最大拉力 {fmax:.0f} kJ mol⁻¹ nm⁻¹ 出現在 {pos[i]:.2f} nm，是單一的主要斷裂事件。",
                     f"{name}: a single main rupture with a peak force of {fmax:.0f} kJ mol⁻¹ nm⁻¹ at {pos[i]:.2f} nm.",
                     f"{name}：最大の力 {fmax:.0f} kJ mol⁻¹ nm⁻¹ は {pos[i]:.2f} nm に現れ、主な破断は1回です。",
                     f"{name}: 최대 힘 {fmax:.0f} kJ mol⁻¹ nm⁻¹이 {pos[i]:.2f} nm에서 나타나며, 주요 파단은 한 번입니다."))
    n20 = max(2, len(work) // 5)
    rise = float(work[-1] - work[-n20])
    total = float(work[-1] - work[0]) or 1.0
    if abs(rise / total) < 0.05:
        out.append(S("good",
                     f"{name}：功在最後 20 % 增加不到 5 %，配體已完全脫離口袋。",
                     f"{name}: the work rises by less than 5 % over the last 20 %, so the ligand has fully detached.",
                     f"{name}：最後の 20 % で仕事の増加は 5 % 未満です。リガンドはポケットから完全に離脱しています。",
                     f"{name}: 마지막 20 % 구간에서 일의 증가가 5 % 미만입니다. 리간드가 포켓에서 완전히 떨어져 나갔습니다."))
    else:
        out.append(S("caution",
                     f"{name}：功在最後 20 % 仍增加 {rise / total:.0%}，配體可能還沒完全脫離。請加長拉離距離。",
                     f"{name}: the work still rises by {rise / total:.0%} over the last 20 %, so the ligand may not have fully "
                     "detached. Increase the pulling distance.",
                     f"{name}：最後の 20 % でも仕事が {rise / total:.0%} 増えています。リガンドはまだ完全に離脱していない可能性があります。引き離し距離を長くしてください。",
                     f"{name}: 마지막 20 % 구간에서도 일이 {rise / total:.0%} 증가합니다. 리간드가 아직 완전히 떨어지지 않았을 수 있으니 당김 거리를 늘리십시오."))
    return out


def _diag(assessment: dict | None, did: str) -> str | None:
    """Status of one diagnostic in a D-96 Assessment (None when no assessment is attached)."""
    for d in (assessment or {}).get("diagnostics") or []:
        if d.get("id") == did:
            return d.get("status")
    return None


_GRAPH = {
    "pass": ("全部窗口對的重疊圖是連通的", "the overlap graph over all window pairs is connected",
             "すべてのウィンドウ対の重なりグラフはつながっています", "모든 윈도우 쌍의 겹침 그래프는 연결되어 있습니다"),
    "fail": ("但全部窗口對的重疊圖不連通，剖面在斷開處沒有依據", "but the overlap graph over all window pairs is disconnected, so the "
             "profile is unsupported across the break", "しかしすべてのウィンドウ対の重なりグラフはつながっておらず、切れ目をまたぐプロファイルには根拠がありません",
             "그러나 모든 윈도우 쌍의 겹침 그래프가 끊어져 있어 끊긴 곳을 넘는 프로파일은 근거가 없습니다"),
    "unknown": ("全部窗口對的重疊圖連通性沒有紀錄", "the connectivity of the full overlap graph is not recorded",
                "全ウィンドウ対の重なりグラフの連結性は記録されていません", "전체 겹침 그래프의 연결성은 기록되지 않았습니다"),
}


def classify_umbrella(coverage: dict, name: str, assessment: dict | None = None) -> list[dict]:
    """Pooled histogram coverage is a LOCAL check (D-96, A2): it never asserts that the windows overlap or that the
    profile is connected; the full-graph status comes from the Assessment."""
    if not coverage:
        return []
    br = coverage.get("breaks") or []
    gs = _diag(assessment, "overlap_graph")
    if coverage.get("continuous") and not br:
        nw = coverage.get("n_windows")
        g = _GRAPH.get(gs or "unknown")
        lvl = "caution" if gs == "fail" else "note"
        return [S(lvl,
                  f"{name}：{f'{nw} 個' if nw else '所有'}窗口合起來的直方圖在路徑上沒有空隙（這只檢查涵蓋範圍）；{g[0]}。",
                  f"{name}: the pooled histogram of {f'the {nw}' if nw else 'all'} windows has no gap along the path (a coverage "
                  f"check only); {g[1]}.",
                  f"{name}：{f'{nw} 個の' if nw else 'すべての'}ウィンドウを合わせたヒストグラムには経路上のすき間がありません（範囲の確認だけです）。{g[2]}。",
                  f"{name}: {f'{nw}개' if nw else '모든'} 윈도우를 합친 히스토그램에 경로상의 빈틈이 없습니다(범위 확인일 뿐입니다). {g[3]}.")]
    parts = [f"{b[0]:.2f}–{b[1]:.2f} nm" if isinstance(b, (list, tuple)) and len(b) == 2 else str(b) for b in br[:5]]
    wz, we = "、".join(parts), ", ".join(parts)
    return [S("caution",
              f"{name}：分佈在 {wz} 出現空隙，這些位置的自由能剖面不可信，需要補窗口。",
              f"{name}: the distributions leave gaps at {we}. The profile is unreliable there and windows must be added.",
              f"{name}：{wz} で分布にすき間があります。この位置の自由エネルギープロファイルは信頼できないため、ウィンドウを追加する必要があります。",
              f"{name}: {we}에서 분포에 틈이 있습니다. 이 위치의 자유 에너지 프로파일은 믿을 수 없으므로 윈도우를 추가해야 합니다.")]

def classify_pmf(grid, W, err, name: str) -> list[dict]:
    g, W = np.asarray(grid, float), np.asarray(W, float)
    if len(W) < 6:
        return []
    i = int(np.nanargmin(W))
    tail = W[g >= g[-1] - 0.2]
    gt = g[g >= g[-1] - 0.2]
    depth = float(np.nanmean(tail) - W[i])
    slope = float(np.polyfit(gt, tail, 1)[0]) if len(tail) >= 3 else 0.0
    out = [S("note",
             f"{name}：最低點在 {g[i]:.2f} nm，相對末端平台的井深約 {depth:.1f} kJ mol⁻¹（{depth / 4.184:.1f} kcal mol⁻¹）。",
             f"{name}: the minimum lies at {g[i]:.2f} nm, about {depth:.1f} kJ mol⁻¹ ({depth / 4.184:.1f} kcal mol⁻¹) below the final plateau.",
             f"{name}：最低点は {g[i]:.2f} nm にあり、末端の平坦部に対する井戸の深さは約 {depth:.1f} kJ mol⁻¹（{depth / 4.184:.1f} kcal mol⁻¹）です。",
             f"{name}: 최저점은 {g[i]:.2f} nm에 있으며, 끝부분 평탄 구간 대비 우물 깊이는 약 {depth:.1f} kJ mol⁻¹({depth / 4.184:.1f} kcal mol⁻¹)입니다.")]
    if abs(slope) > 2.0:
        out.append(S("caution",
                     f"{name}：剖面末端仍有斜率（{slope:.1f} kJ mol⁻¹ nm⁻¹，> 2），配體還沒到達完全解離的平台，井深可能被低估。請加長路徑。",
                     f"{name}: the end of the profile still slopes ({slope:.1f} kJ mol⁻¹ nm⁻¹, > 2). The fully dissociated plateau "
                     "is not reached and the depth may be underestimated, so extend the path.",
                     f"{name}：プロファイルの末端にまだ傾きがあります（{slope:.1f} kJ mol⁻¹ nm⁻¹、> 2）。完全に解離した平坦部に届いておらず、"
                     "井戸の深さは過小評価されている可能性があります。経路を延長してください。",
                     f"{name}: 프로파일 끝부분에 아직 기울기가 있습니다({slope:.1f} kJ mol⁻¹ nm⁻¹, > 2). 완전 해리 평탄 구간에 도달하지 않아 "
                     "우물 깊이가 과소평가되었을 수 있으니 경로를 늘리십시오."))
    else:
        out.append(S("good",
                     f"{name}：剖面末端平坦（斜率 {slope:.1f} kJ mol⁻¹ nm⁻¹），已到達解離狀態。",
                     f"{name}: the end of the profile is flat (slope {slope:.1f} kJ mol⁻¹ nm⁻¹), so the dissociated state is reached.",
                     f"{name}：プロファイルの末端は平坦で（傾き {slope:.1f} kJ mol⁻¹ nm⁻¹）、解離状態に達しています。",
                     f"{name}: 프로파일 끝부분이 평탄하며(기울기 {slope:.1f} kJ mol⁻¹ nm⁻¹) 해리 상태에 도달했습니다."))
    if depth > 80:
        out.append(S("caution",
                     f"{name}：井深超過 80 kJ mol⁻¹，對多數藥物大小的分子來說不合理。常見原因是窗口取樣不足，或拉離路徑扭曲了蛋白。",
                     f"{name}: a depth above 80 kJ mol⁻¹ is implausible for most drug-sized molecules. The usual causes are "
                     "insufficient sampling or a pulling path that distorts the protein.",
                     f"{name}：井戸の深さが 80 kJ mol⁻¹ を超えており、薬物サイズの分子の多くでは不自然な値です。"
                     "よくある原因は、ウィンドウのサンプリング不足か、引き離し経路がタンパク質をゆがめていることです。",
                     f"{name}: 우물 깊이가 80 kJ mol⁻¹ 초과로, 대부분의 약물 크기 분자에는 맞지 않는 값입니다. "
                     "흔한 원인은 윈도우 샘플링 부족이나 당김 경로가 단백질을 비트는 경우입니다."))
    if err is not None:
        e = np.asarray(err, float)
        emax = float(np.nanmax(e[np.isfinite(e)])) if np.isfinite(e).any() else 0.0
        if depth > 0 and emax > 0.2 * depth:
            out.append(S("caution",
                         f"{name}：最大誤差 {emax:.1f} kJ mol⁻¹ 超過井深的 20 %，取樣不足以支持定量比較。",
                         f"{name}: the largest error, {emax:.1f} kJ mol⁻¹, exceeds 20 % of the depth, so sampling does not support "
                         "a quantitative comparison.",
                         f"{name}：最大誤差 {emax:.1f} kJ mol⁻¹ は井戸の深さの 20 % を超えています。定量的な比較ができるほどのサンプリングではありません。",
                         f"{name}: 최대 오차 {emax:.1f} kJ mol⁻¹이 우물 깊이의 20 %를 넘습니다. 정량적 비교를 뒷받침하기에는 샘플링이 부족합니다."))
    return out


# =========================================================================================== D-58: extended figures
FIG.update({
    "equil_quality": {
        "title": ("平衡過程品質", "Equilibration quality", "平衡化の品質", "평형화 품질"),
        "caption": ("各階段（加熱、定壓平衡、正式模擬）的溫度、位能、密度與盒體積隨時間的變化。",
                    "Temperature, potential energy, density and box volume over time in each stage (heating, pressure equilibration, production).",
                    "各段階（加熱、定圧平衡化、本計算）の温度、ポテンシャルエネルギー、密度、ボックス体積の時間変化です。",
                    "각 단계(가열, 정압 평형화, 본 시뮬레이션)의 온도, 퍼텐셜 에너지, 밀도, 상자 부피의 시간 변화입니다."),
        "read": ("溫度應在目標值附近穩定擾動。密度與盒體積到定壓平衡後段應進入平台。位能持續下降，代表結構還在鬆弛。",
                 "Temperature should fluctuate around its target. Density and box volume should level off by the end of pressure "
                 "equilibration. A potential energy that keeps falling means the structure is still relaxing.",
                 "温度は目標値の周りで安定してゆらぐはずです。密度とボックス体積は定圧平衡化の後半までに平坦になるはずです。"
                 "ポテンシャルエネルギーが下がり続けている場合、構造はまだ緩和の途中です。",
                 "온도는 목표값 근처에서 안정적으로 요동해야 합니다. 밀도와 상자 부피는 정압 평형화 후반까지 평탄해져야 합니다. "
                 "퍼텐셜 에너지가 계속 내려가면 구조가 아직 이완 중인 것입니다."),
    },
    "minimization": {
        "title": ("能量最小化", "Energy minimisation", "エネルギー最小化", "에너지 최소화"),
        "caption": ("各約束階段最小化後的位能。", "Potential energy after each restrained minimisation stage.",
                    "各拘束段階で最小化した後のポテンシャルエネルギーです。", "각 구속 단계에서 최소화한 뒤의 퍼텐셜 에너지입니다."),
        "read": ("位能應逐階段下降。大幅下降代表起始結構中的碰撞已被消除。如果最後一階段仍大幅下降，結構需要更多最小化。",
                 "Energy should fall stage by stage. A large drop means clashes in the starting structure were removed. A large "
                 "drop in the last stage means more minimisation is needed.",
                 "ポテンシャルエネルギーは段階ごとに下がるはずです。大きく下がるのは初期構造の衝突が解消されたためです。"
                 "最後の段階でも大きく下がる場合は、さらに最小化が必要です。",
                 "퍼텐셜 에너지는 단계마다 내려가야 합니다. 크게 내려가는 것은 시작 구조의 충돌이 해소되었기 때문입니다. "
                 "마지막 단계에서도 크게 내려가면 최소화를 더 해야 합니다."),
    },
    "replicas": {
        "title": ("獨立重複的比較", "Independent replicas", "独立した反復計算の比較", "독립 반복 계산 비교"),
        "caption": ("各重複（不同初速）的溫度與位能。", "Temperature and potential energy of each replica (different initial velocities).",
                    "各反復計算（初速度が異なる）の温度とポテンシャルエネルギーです。", "각 반복 계산(초기 속도가 다름)의 온도와 퍼텐셜 에너지입니다."),
        "read": ("各重複應落在相同範圍。若某一次重複明顯偏離，代表系統有多個狀態，或那一次重複出了問題。",
                 "Replicas should overlap. One that departs clearly points to several states or to a problem in that replica.",
                 "各反復計算は同じ範囲に収まるはずです。1つだけはっきり外れる場合は、系に複数の状態があるか、その計算に問題があります。",
                 "각 반복 계산은 같은 범위에 있어야 합니다. 하나가 뚜렷하게 벗어나면 시스템에 여러 상태가 있거나 그 계산에 문제가 있는 것입니다."),
    },
    "hbond_count": {
        "title": ("配體與蛋白的氫鍵數", "Ligand–protein hydrogen bonds", "リガンドとタンパク質の水素結合数", "리간드-단백질 수소 결합 수"),
        "caption": ("每一幀配體與蛋白之間的氫鍵數，以 Wernet–Nilsson 幾何判準計算。",
                    "Number of ligand–protein hydrogen bonds per frame, by the Wernet–Nilsson geometric criterion.",
                    "各フレームでのリガンドとタンパク質の間の水素結合数です（Wernet–Nilsson の幾何学的基準）。",
                    "각 프레임에서 리간드와 단백질 사이의 수소 결합 수입니다(Wernet–Nilsson 기하 기준)."),
        "read": ("平均兩個以上，代表極性作用是結合的主要錨點。接近零代表結合主要靠疏水與凡得瓦作用。數目隨時間下降，代表極性作用逐漸喪失。",
                 "Two or more on average means polar interactions anchor the ligand. Near zero means binding relies on hydrophobic "
                 "and van der Waals contacts. A falling count means polar interactions are being lost.",
                 "平均2本以上なら、極性相互作用が結合の主なアンカーです。ゼロに近ければ、結合は主に疎水性相互作用とファンデルワールス相互作用によります。"
                 "本数が時間とともに減る場合は、極性相互作用が失われつつあります。",
                 "평균 2개 이상이면 극성 상호작용이 결합의 주요 앵커입니다. 0에 가까우면 결합이 주로 소수성 상호작용과 반데르발스 상호작용에 의존합니다. "
                 "수가 시간에 따라 줄면 극성 상호작용이 사라지고 있는 것입니다."),
    },
    "hbond_occupancy": {
        "title": ("氫鍵佔有率", "Hydrogen-bond occupancy", "水素結合の占有率", "수소 결합 점유율"),
        "caption": ("每一組供體與受體之間氫鍵存在的時間比例。標籤中的箭頭由供體指向受體。",
                    "Fraction of time each donor–acceptor hydrogen bond exists. The arrow in each label points from donor to acceptor.",
                    "供与体と受容体の組ごとに、水素結合が存在する時間の割合です。ラベルの矢印は供与体から受容体に向いています。",
                    "주개와 받개 쌍마다 수소 결합이 존재하는 시간의 비율입니다. 표시의 화살표는 주개에서 받개 쪽을 가리킵니다."),
        "read": ("50 % 以上是穩定氫鍵，20 % 到 50 % 是間歇氫鍵。同一殘基有好幾組氫鍵，代表那裡是關鍵作用位。",
                 "Above 50 % is a stable hydrogen bond and 20–50 % is intermittent. Several bonds to one residue mark a key interaction site.",
                 "50 % 以上は安定な水素結合、20〜50 % は断続的な水素結合です。1つの残基に複数の水素結合があれば、そこが重要な相互作用部位です。",
                 "50 % 이상은 안정한 수소 결합, 20~50 %는 간헐적인 수소 결합입니다. 한 잔기에 수소 결합이 여러 개 있으면 그곳이 핵심 상호작용 부위입니다."),
    },
    "com_distance": {
        "title": ("配體與口袋的質心距離", "Ligand–pocket centre-of-mass distance", "リガンドとポケットの重心間距離", "리간드-포켓 질량 중심 거리"),
        "caption": ("配體質心到口袋原子質心的距離，以及配體與蛋白的極性接觸數（N、O 原子相距 3.5 Å 內）。",
                    "Distance between the centres of mass of ligand and pocket, and the number of ligand–protein polar contacts "
                    "(N and O atoms within 3.5 Å).",
                    "リガンドの重心からポケット原子の重心までの距離と、リガンドとタンパク質の極性接触の数（N と O の原子が 3.5 Å 以内）です。",
                    "리간드 질량 중심에서 포켓 원자 질량 중심까지의 거리와 리간드-단백질 극성 접촉 수(N, O 원자 3.5 Å 이내)입니다."),
        "read": ("距離穩定代表配體留在原位，持續增加代表配體逐漸離開。如果極性接觸同時減少，結合正在瓦解。",
                 "A steady distance means the ligand stays in place and a rising distance means it is leaving. If the polar "
                 "contacts drop at the same time, the binding is breaking up.",
                 "距離が安定していればリガンドは元の位置にとどまっています。増え続ける場合は離れつつあります。同時に極性接触が減っていれば、結合が崩れつつあります。",
                 "거리가 안정적이면 리간드가 제자리에 있는 것이고, 계속 늘면 떠나고 있는 것입니다. 동시에 극성 접촉이 줄면 결합이 무너지고 있는 것입니다."),
    },
    "ligand_burial": {
        "title": ("配體埋藏程度", "Ligand burial", "リガンドの埋没度", "리간드 매몰도"),
        "caption": ("配體表面被蛋白遮蔽的比例，算法是 1 − 複合物中的溶劑可及面積 ÷ 單獨配體的溶劑可及面積。",
                    "Fraction of the ligand surface shielded by the protein, computed as 1 − solvent-accessible area in the "
                    "complex ÷ area of the free ligand.",
                    "タンパク質に覆われたリガンド表面の割合で、1 − 複合体中の溶媒接触表面積 ÷ 単独リガンドの溶媒接触表面積 で求めます。",
                    "단백질에 가려진 리간드 표면의 비율이며, 1 − 복합체에서의 용매 접근 표면적 ÷ 단독 리간드의 용매 접근 표면적으로 계산합니다."),
        "read": ("70 % 以上代表深埋在口袋裡，40 % 到 70 % 是部分埋藏。低於 40 % 代表大部分暴露在溶劑中，屬於表面結合。",
                 "Above 70 % the ligand is deeply buried and 40–70 % is partly buried. Below 40 % it is mostly exposed to "
                 "solvent, which is surface binding.",
                 "70 % 以上ならポケットの奥に埋まっており、40〜70 % は部分的な埋没です。40 % 未満なら大部分が溶媒にさらされており、表面での結合です。",
                 "70 % 이상이면 포켓 깊이 묻혀 있고, 40~70 %는 부분적으로 묻힌 상태입니다. 40 % 미만이면 대부분 용매에 노출된 표면 결합입니다."),
    },
    "protein_sasa": {
        "title": ("蛋白溶劑可及面積", "Protein solvent-accessible surface area", "タンパク質の溶媒接触表面積", "단백질 용매 접근 표면적"),
        "caption": ("蛋白總溶劑可及面積隨時間的變化。", "Total solvent-accessible surface area of the protein over time.",
                    "タンパク質全体の溶媒接触表面積の時間変化です。", "단백질 전체 용매 접근 표면적의 시간 변화입니다."),
        "read": ("數值穩定代表摺疊維持，持續增加代表疏水核心暴露或蛋白展開。",
                 "A stable value means the fold is kept. A steady increase means the hydrophobic core is opening or the protein is unfolding.",
                 "値が安定していれば折りたたみは保たれています。増え続ける場合は、疎水性コアが露出しているか、タンパク質がほどけています。",
                 "값이 안정적이면 접힘이 유지되는 것입니다. 계속 늘면 소수성 코어가 드러나거나 단백질이 풀리고 있는 것입니다."),
    },
    "dssp": {
        "title": ("二級結構", "Secondary structure", "二次構造", "이차 구조"),
        "caption": ("α 螺旋、β 摺板與其他結構所占比例隨時間的變化，由 DSSP 判定。",
                    "Fractions of α-helix, β-strand and other structure over time, assigned by DSSP.",
                    "α ヘリックス、β ストランド、その他の構造の割合の時間変化です（DSSP で判定）。",
                    "α 나선, β 가닥, 기타 구조 비율의 시간 변화입니다(DSSP로 판정)."),
        "read": ("比例穩定代表二級結構保持。螺旋或摺板的比例下降，代表局部展開。",
                 "Stable fractions mean the secondary structure is kept. A falling helix or strand fraction means local unfolding.",
                 "割合が安定していれば二次構造は保たれています。ヘリックスやストランドの割合が下がる場合は、局所的にほどけています。",
                 "비율이 안정적이면 이차 구조가 유지되는 것입니다. 나선이나 가닥 비율이 줄면 국소적으로 풀리고 있는 것입니다."),
    },
    "hbond_protein": {
        "title": ("蛋白內部氫鍵", "Protein internal hydrogen bonds", "タンパク質内部の水素結合", "단백질 내부 수소 결합"),
        "caption": ("蛋白分子內氫鍵總數隨時間的變化。", "Total number of hydrogen bonds within the protein over time.",
                    "タンパク質分子内の水素結合の総数の時間変化です。", "단백질 분자 내 수소 결합 총수의 시간 변화입니다."),
        "read": ("數目穩定代表結構完整，持續下降代表結構逐漸鬆散。",
                 "A steady number means an intact structure. A steady decrease means the structure is loosening.",
                 "本数が安定していれば構造は保たれています。減り続ける場合は構造がゆるんできています。",
                 "수가 안정적이면 구조가 온전한 것입니다. 계속 줄면 구조가 느슨해지고 있는 것입니다."),
    },
    "pca_landscape": {
        "title": ("構形自由能地形（主成分分析）", "Conformational free-energy landscape (principal component analysis)",
                  "構造の自由エネルギー地形（主成分分析）", "구조 자유 에너지 지형(주성분 분석)"),
        "caption": ("以 Cα 座標前兩個主成分畫出的自由能地形，顏色越深能量越低。",
                    "Free-energy landscape on the first two principal components of Cα coordinates. Darker is lower free energy.",
                    "Cα 座標の第1・第2主成分で描いた自由エネルギー地形です。色が濃いほど自由エネルギーが低くなります。",
                    "Cα 좌표의 첫 두 주성분으로 그린 자유 에너지 지형입니다. 색이 진할수록 자유 에너지가 낮습니다."),
        "read": ("只有一個深谷，代表蛋白停留在一個主要構形。有多個谷，代表有多個構形狀態，以及它們之間的轉換。前兩個主成分解釋的變異越高，這張地形越能代表整體運動。",
                 "One deep basin means one dominant conformation. Several basins mean several states and transitions between "
                 "them. The more variance the two components explain, the better the map represents the overall motion.",
                 "深い谷が1つだけなら、タンパク質は主な構造1つにとどまっています。谷が複数あれば、複数の構造状態とその間の転移があります。"
                 "2つの主成分で説明される分散が大きいほど、この地形は全体の運動をよく表しています。",
                 "깊은 골이 하나뿐이면 단백질이 하나의 주요 구조에 머무는 것입니다. 골이 여러 개면 여러 구조 상태와 그 사이의 전이가 있는 것입니다. "
                 "두 주성분이 설명하는 분산이 클수록 이 지형이 전체 운동을 잘 나타냅니다."),
    },
    "clusters": {
        "title": ("構形叢集", "Conformational clusters", "構造クラスター", "구조 클러스터"),
        "caption": ("以 Cα 與配體 RMSD（門檻 2 Å）分群後各叢集的比例，以及每一幀所屬的叢集。",
                    "Population of each cluster from Cα and ligand RMSD (2 Å cutoff), and the cluster of each frame over time.",
                    "Cα とリガンドの RMSD（しきい値 2 Å）でクラスタリングした各クラスターの割合と、各フレームが属するクラスターの時間変化です。",
                    "Cα와 리간드 RMSD(기준 2 Å)로 묶은 각 클러스터의 비율과, 프레임마다 속한 클러스터의 시간 변화입니다."),
        "read": ("最大叢集超過 60 % 代表有主導的結合構形。有幾個比例相近的叢集，代表結合模式在模擬中變動。代表結構取每個叢集中心的那一幀。",
                 "A largest cluster above 60 % means a dominant bound conformation. Several clusters of similar size mean the "
                 "binding mode changes during the simulation. The representative structure is the centre frame of each cluster.",
                 "最大のクラスターが 60 % を超えていれば、主要な結合構造があります。同程度の大きさのクラスターが複数あれば、"
                 "シミュレーション中に結合様式が変化しています。代表構造は各クラスターの中心にあるフレームです。",
                 "가장 큰 클러스터가 60 %를 넘으면 지배적인 결합 구조가 있는 것입니다. 비슷한 크기의 클러스터가 여러 개면 시뮬레이션 중에 "
                 "결합 모드가 바뀌는 것입니다. 대표 구조는 각 클러스터 중심의 프레임입니다."),
    },
    "dccm": {
        "title": ("動態交互相關（DCCM）", "Dynamic cross-correlation (DCCM)", "動的相互相関（DCCM）", "동적 교차 상관(DCCM)"),
        "caption": ("Cα 位移之間的相關係數。紅色是同向運動，藍色是反向運動。",
                    "Correlation of Cα displacements. Red means motion in the same direction and blue in opposite directions.",
                    "Cα 変位の間の相関係数です。赤は同じ向きの運動、青は逆向きの運動です。",
                    "Cα 변위 사이의 상관계수입니다. 빨간색은 같은 방향, 파란색은 반대 방향의 운동입니다."),
        "read": ("對角線附近的相關來自鏈上相鄰的殘基。遠離對角線的強相關代表區域之間的協同運動。比較結合前後的差異，可以找出受配體影響的長距離耦合。",
                 "Correlation near the diagonal comes from neighbouring residues on the chain. Strong correlation far from the "
                 "diagonal shows coordinated motion between regions. Comparing it with and without the ligand points to "
                 "long-range coupling affected by binding.",
                 "対角線付近の相関は、鎖上で隣り合う残基によるものです。対角線から離れた強い相関は、領域どうしの協調運動を示します。"
                 "結合の有無で比べると、リガンドの影響を受ける長距離の連動が分かります。",
                 "대각선 근처의 상관은 사슬에서 이웃한 잔기에서 옵니다. 대각선에서 먼 강한 상관은 영역 사이의 협동 운동을 나타냅니다. "
                 "결합 전후를 비교하면 리간드의 영향을 받는 장거리 연동을 찾을 수 있습니다."),
    },
    "fingerprint": {
        "title": ("作用指紋", "Interaction fingerprint", "相互作用フィンガープリント", "상호작용 지문"),
        "caption": ("每個殘基與配體在每一幀的作用類型，分為離子、極性與疏水。",
                    "Interaction type between each residue and the ligand in every frame, classed as ionic, polar or hydrophobic.",
                    "各フレームでの、各残基とリガンドの相互作用の種類（イオン性、極性、疎水性）です。",
                    "프레임마다 각 잔기와 리간드 사이의 상호작용 유형(이온성, 극성, 소수성)입니다."),
        "read": ("整列連續著色代表持續作用，斷斷續續代表間歇作用。作用類型改變，代表結合模式在調整。",
                 "A row coloured without breaks is a persistent interaction and a broken row is intermittent. A change of type "
                 "means the binding mode is adjusting.",
                 "行が途切れずに色づいていれば持続的な相互作用、途切れていれば断続的です。種類が変わる場合は結合様式が調整されています。",
                 "행이 끊김 없이 칠해져 있으면 지속적인 상호작용이고, 끊겨 있으면 간헐적입니다. 유형이 바뀌면 결합 모드가 조정되고 있는 것입니다."),
    },
    "water_bridges": {
        "title": ("水橋", "Water bridges", "水架橋", "물 다리"),
        "caption": ("同時與配體及蛋白極性原子相距 3.5 Å 內的水分子數。",
                    "Number of water molecules within 3.5 Å of both a ligand and a protein polar atom.",
                    "リガンドとタンパク質の極性原子の両方から 3.5 Å 以内にある水分子の数です。",
                    "리간드와 단백질의 극성 원자 양쪽에서 3.5 Å 이내에 있는 물 분자 수입니다."),
        "read": ("平均一個以上代表水分子參與結合，取代或移除這些水可能改變親和力。接近零代表配體與蛋白直接接觸。",
                 "One or more on average means water takes part in binding, and displacing it may change the affinity. Near zero "
                 "means direct ligand–protein contact.",
                 "平均1個以上なら水分子が結合に関わっており、その水を置き換えると親和性が変わる可能性があります。ゼロに近ければ、リガンドとタンパク質は直接接触しています。",
                 "평균 1개 이상이면 물 분자가 결합에 참여하는 것이며, 이 물을 치환하면 친화도가 바뀔 수 있습니다. 0에 가까우면 리간드와 단백질이 직접 접촉합니다."),
    },
    "overlap_matrix": {
        "title": ("窗口重疊矩陣", "Window overlap matrix", "ウィンドウの重なり行列", "윈도우 겹침 행렬"),
        "caption": ("每兩個傘狀採樣窗口的分佈之間的重疊程度。", "Overlap between the sampling distributions of every pair of umbrella windows.",
                    "アンブレラサンプリングのウィンドウの組ごとの、分布の重なりです。", "엄브렐라 샘플링 윈도우 쌍마다 분포가 겹치는 정도입니다."),
        "read": ("相鄰窗口（對角線旁）的重疊至少要 0.2。低於 0.05 的位置等於斷開，該處的自由能不可信。",
                 "Neighbouring windows, next to the diagonal, should overlap by at least 0.2. Below 0.05 the profile is effectively broken there.",
                 "隣り合うウィンドウ（対角線の隣）の重なりは 0.2 以上必要です。0.05 未満の位置は途切れているのと同じで、そこの自由エネルギーは信頼できません。",
                 "이웃한 윈도우(대각선 옆)의 겹침은 0.2 이상이어야 합니다. 0.05 미만인 위치는 끊어진 것과 같아 그곳의 자유 에너지를 믿을 수 없습니다."),
    },
    "pmf_convergence": {
        "title": ("自由能剖面的收斂", "Convergence of the free-energy profile", "自由エネルギープロファイルの収束", "자유 에너지 프로파일의 수렴"),
        "caption": ("只用每個窗口前 25 %、50 %、75 % 與全部取樣算出的自由能剖面。",
                    "Free-energy profiles computed from the first 25 %, 50 %, 75 % and all of each window's samples.",
                    "各ウィンドウの最初の 25 %、50 %、75 %、および全サンプルから計算した自由エネルギープロファイルです。",
                    "각 윈도우의 처음 25 %, 50 %, 75 %와 전체 샘플로 계산한 자유 에너지 프로파일입니다."),
        "read": ("取樣增加時曲線互相重合，代表已收斂。井深還在變，代表窗口需要更長。",
                 "Curves that coincide as sampling grows mean convergence. A depth that keeps changing means longer windows are needed.",
                 "サンプルが増えるにつれて曲線が重なれば収束しています。井戸の深さが変わり続ける場合は、ウィンドウを長くする必要があります。",
                 "샘플이 늘면서 곡선이 겹치면 수렴한 것입니다. 우물 깊이가 계속 바뀌면 윈도우를 더 길게 해야 합니다."),
    },
    "properties": {
        "title": ("化合物性質分佈", "Compound property distributions", "化合物の物性分布", "화합물 물성 분포"),
        "caption": ("化合物的分子量、logP、極性表面積、氫鍵供體與受體以及可轉動鍵的分佈。虛線是類藥性門檻。",
                    "Distributions of molecular weight, logP, polar surface area, hydrogen-bond donors and acceptors and "
                    "rotatable bonds. Dashed lines are drug-likeness limits.",
                    "化合物の分子量、logP、極性表面積、水素結合供与体と受容体、回転可能結合の分布です。破線は薬らしさ（drug-likeness）のしきい値です。",
                    "화합물의 분자량, logP, 극성 표면적, 수소 결합 주개와 받개, 회전 가능 결합의 분포입니다. 점선은 약물 유사성 기준입니다."),
        "read": ("落在虛線外的化合物，口服吸收或穿膜的機率較低（Lipinski 與 Veber 規則）。天然物常違反一到兩項，這些是經驗規則，不是排除條件。",
                 "Compounds beyond the dashed lines are less likely to be orally absorbed or to cross membranes (Lipinski and "
                 "Veber rules). Natural products often break one or two, and these rules are guidelines, not exclusion criteria.",
                 "破線の外にある化合物は、経口吸収や膜透過の可能性が低くなります（Lipinski と Veber の規則）。"
                 "天然物は1〜2項目に違反することが多く、これらは経験則であって除外基準ではありません。",
                 "점선 밖의 화합물은 경구 흡수나 막 투과 가능성이 낮습니다(Lipinski와 Veber 규칙). "
                 "천연물은 한두 항목을 어기는 경우가 많으며, 이 규칙은 경험칙이지 제외 기준이 아닙니다."),
    },
    "chem_space": {
        "title": ("化學空間", "Chemical space", "化学空間", "화학 공간"),
        "caption": ("以分子指紋的主成分把化合物投影到平面，顏色是對接分數。",
                    "Compounds projected on the principal components of their molecular fingerprints, coloured by docking score.",
                    "分子フィンガープリントの主成分で化合物を平面に投影し、ドッキングスコアで色分けしています。",
                    "분자 지문의 주성분으로 화합물을 평면에 투영했으며, 색은 도킹 점수입니다."),
        "read": ("距離近的點結構相似。高分化合物集中在一區，代表某一種結構類型有利結合。分散在各處，則代表多種骨架都可能結合。",
                 "Nearby points are structurally similar. High-scoring compounds grouped in one region point to a favourable "
                 "scaffold, and scattered ones to several possible scaffolds.",
                 "近い点どうしは構造が似ています。高スコアの化合物が1か所に集まっていれば、ある構造タイプが結合に有利です。"
                 "散らばっていれば、複数の骨格が結合しうることを示します。",
                 "가까운 점끼리는 구조가 비슷합니다. 점수가 좋은 화합물이 한곳에 모여 있으면 특정 구조 유형이 결합에 유리한 것이고, "
                 "흩어져 있으면 여러 골격이 결합할 수 있는 것입니다."),
    },
    "interaction_2d": {
        "title": ("二維作用圖", "Two-dimensional interaction diagram", "二次元相互作用図", "2차원 상호작용 도표"),
        "caption": ("選用姿勢中，配體每個原子最近的蛋白殘基與作用類型。藍色是氫鍵，紅色是離子作用，金色是疏水作用，灰色是其他接觸。",
                    "Nearest protein residue and interaction class for each ligand atom in the chosen pose. Blue is a hydrogen "
                    "bond, red ionic, gold hydrophobic and grey any other contact.",
                    "採用したポーズで、リガンドの各原子に最も近いタンパク質残基と相互作用の種類です。青は水素結合、赤はイオン性、金色は疎水性、灰色はその他の接触です。",
                    "선택한 포즈에서 리간드 각 원자에 가장 가까운 단백질 잔기와 상호작용 유형입니다. 파란색은 수소 결합, 빨간색은 이온성, "
                    "금색은 소수성, 회색은 기타 접촉입니다."),
        "read": ("標出的殘基就是對接姿勢的接觸點。和模擬中的作用指紋對照，可以看出哪些作用在動態下維持。",
                 "Labelled residues are the contacts of the docked pose. Comparing them with the interaction fingerprint from "
                 "the simulation shows which interactions survive in dynamics.",
                 "ラベルの付いた残基がドッキングポーズの接触点です。シミュレーションの相互作用フィンガープリントと比べると、どの相互作用が動的に保たれるかが分かります。",
                 "표시된 잔기가 도킹 포즈의 접촉점입니다. 시뮬레이션의 상호작용 지문과 비교하면 어떤 상호작용이 동역학에서 유지되는지 알 수 있습니다."),
    },
    "screen_hist": {
        "title": ("篩選分數分佈", "Screening score distribution", "スクリーニングスコアの分布", "스크리닝 점수 분포"),
        "caption": ("所有化合物的 Vina 分數分佈。", "Distribution of Vina scores of all compounds.",
                    "全化合物の Vina スコアの分布です。", "전체 화합물의 Vina 점수 분포입니다."),
        "read": ("分佈左側的長尾是值得繼續研究的候選。整體分佈狹窄，代表化合物庫對這個標靶的差異不大。",
                 "The long tail on the left holds the candidates worth pursuing. A narrow distribution means the library "
                 "differs little against this target.",
                 "分布の左側に伸びる裾が、さらに調べる価値のある候補です。分布全体が狭い場合は、このターゲットに対してライブラリ内の差が小さいことを示します。",
                 "분포 왼쪽의 긴 꼬리가 더 살펴볼 만한 후보입니다. 분포가 전체적으로 좁으면 이 표적에 대해 라이브러리 안의 차이가 작은 것입니다."),
    },
    "screen_scatter": {
        "title": ("分數與分子大小", "Score against molecular size", "スコアと分子の大きさ", "점수와 분자 크기"),
        "caption": ("Vina 分數對重原子數作圖。", "Vina score against heavy-atom count.",
                    "Vina スコアを重原子数に対してプロットしています。", "Vina 점수를 중원자 수에 대해 그렸습니다."),
        "read": ("分子越大分數越負，是評分函數已知的偏差。落在趨勢線下方的化合物（同樣大小但分數更好）配體效率較高。",
                 "Scores becoming more negative with size is a known bias of the scoring function. Compounds below the trend, "
                 "with a better score at the same size, have higher ligand efficiency.",
                 "分子が大きいほどスコアが負になるのは、スコア関数の既知の偏りです。傾向線より下にある化合物（同じ大きさでスコアが良い）はリガンド効率が高くなります。",
                 "분자가 클수록 점수가 더 음수가 되는 것은 점수 함수의 알려진 편향입니다. 추세선 아래의 화합물(같은 크기에서 점수가 더 좋음)은 리간드 효율이 높습니다."),
    },
})


def _halves(y):
    y = np.asarray(y, float)
    n = len(y)
    return float(y[: max(1, n // 10)].mean()), float(y[n // 2:].mean())


def _lang4(t: tuple) -> tuple:
    """(zh, en) or (zh, en, ja, ko) → four strings; Japanese and Korean fall back to English."""
    zh, en = t[0], t[1]
    ja = t[2] if len(t) > 2 and t[2] else en
    ko = t[3] if len(t) > 3 and t[3] else en
    return zh, en, ja, ko


def classify_equil(rows: list[dict], key: str) -> list[dict]:
    """rows: acceptance checks [{"stage", "check", "ok", ...}] of one system."""
    if not rows:
        return []
    bad = [r for r in rows if not r.get("ok")]
    if not bad:
        return [S("good",
                  f"{key}：{len(rows)} 項驗收（溫度、密度）全部通過，平衡完成。",
                  f"{key}: all {len(rows)} acceptance checks (temperature, density) pass, so equilibration is complete.",
                  f"{key}：{len(rows)} 項目の受け入れ検査（温度、密度）にすべて合格し、平衡化は完了しています。",
                  f"{key}: 검수 {len(rows)}개 항목(온도, 밀도)을 모두 통과했으며 평형화가 끝났습니다.")]
    bz = "、".join(f"{r['stage']} {r['check']}" for r in bad)
    be = ", ".join(f"{r['stage']} {r['check']}" for r in bad)
    return [S("caution",
              f"{key}：{len(bad)} 項驗收未通過（{bz}）。該階段可能還沒平衡，後續結果要保守看待。",
              f"{key}: {len(bad)} acceptance check(s) fail ({be}). That stage may not be equilibrated, so read later results with caution.",
              f"{key}：{len(bad)} 項目の検査が不合格です（{bz}）。その段階は平衡に達していない可能性があるため、以降の結果は慎重に扱ってください。",
              f"{key}: 검수 {len(bad)}개 항목을 통과하지 못했습니다({be}). 해당 단계가 평형에 도달하지 않았을 수 있으므로 이후 결과를 신중하게 보십시오.")]


def classify_minimization(energies, key: str) -> list[dict]:
    e = np.asarray(energies, float)
    if len(e) < 2:
        return []
    drop = e[0] - e[-1]
    last = e[-2] - e[-1]
    out = [S("good" if drop > 0 else "caution",
             f"{key}：最小化讓位能下降 {drop:,.0f} kJ mol⁻¹。",
             f"{key}: minimisation lowers the potential energy by {drop:,.0f} kJ mol⁻¹.",
             f"{key}：最小化でポテンシャルエネルギーが {drop:,.0f} kJ mol⁻¹ 下がりました。",
             f"{key}: 최소화로 퍼텐셜 에너지가 {drop:,.0f} kJ mol⁻¹ 낮아졌습니다.")]
    if drop > 0 and last > 0.3 * drop:
        out.append(S("note",
                     f"{key}：最後一階段仍占總下降的 {last / drop:.0%}，完全釋放約束後結構還有可觀的鬆弛。",
                     f"{key}: the last stage still accounts for {last / drop:.0%} of the drop. The structure relaxes considerably "
                     "once restraints are released.",
                     f"{key}：最後の段階が下降全体の {last / drop:.0%} を占めています。拘束をすべて外した後も構造がかなり緩和しています。",
                     f"{key}: 마지막 단계가 전체 감소의 {last / drop:.0%}를 차지합니다. 구속을 모두 풀고 나서도 구조가 상당히 이완됩니다."))
    return out


def classify_hbond_count(series: dict) -> list[dict]:
    out = []
    for name, (t, y) in series.items():
        if len(y) < 5:
            continue
        a, b = _halves(y)
        if b >= 2:
            out.append(S("good",
                         f"{name}：後半段平均 {b:.1f} 個氫鍵（≥ 2），極性作用是結合的主要錨點。",
                         f"{name}: {b:.1f} hydrogen bonds on average in the second half (≥ 2), so polar interactions anchor the ligand.",
                         f"{name}：後半の水素結合は平均 {b:.1f} 本（≥ 2）で、極性相互作用が結合の主なアンカーです。",
                         f"{name}: 후반부 평균 수소 결합 {b:.1f}개(≥ 2)로, 극성 상호작용이 결합의 주요 앵커입니다."))
        elif b >= 0.5:
            out.append(S("note",
                         f"{name}：後半段平均 {b:.1f} 個氫鍵，極性作用有貢獻，但不是主要錨點。",
                         f"{name}: {b:.1f} hydrogen bonds on average in the second half. Polar interactions contribute but do not anchor the ligand.",
                         f"{name}：後半の水素結合は平均 {b:.1f} 本です。極性相互作用は寄与していますが、主なアンカーではありません。",
                         f"{name}: 후반부 평균 수소 결합 {b:.1f}개입니다. 극성 상호작용이 기여하지만 주요 앵커는 아닙니다."))
        else:
            out.append(S("note",
                         f"{name}：幾乎沒有氫鍵（平均 {b:.1f}），結合主要靠疏水與凡得瓦作用。",
                         f"{name}: almost no hydrogen bonds (average {b:.1f}). Binding relies on hydrophobic and van der Waals contacts.",
                         f"{name}：水素結合はほとんどありません（平均 {b:.1f}）。結合は主に疎水性相互作用とファンデルワールス相互作用によります。",
                         f"{name}: 수소 결합이 거의 없습니다(평균 {b:.1f}). 결합이 주로 소수성 상호작용과 반데르발스 상호작용에 의존합니다."))
        if a - b >= 1.0:
            out.append(S("caution",
                         f"{name}：氫鍵數從開始的 {a:.1f} 降到 {b:.1f}，極性作用逐漸喪失。",
                         f"{name}: hydrogen bonds fall from {a:.1f} at the start to {b:.1f}, so polar interactions are being lost.",
                         f"{name}：水素結合の数が最初の {a:.1f} から {b:.1f} に減り、極性相互作用が失われつつあります。",
                         f"{name}: 수소 결합 수가 처음 {a:.1f}개에서 {b:.1f}개로 줄었습니다. 극성 상호작용이 사라지고 있습니다."))
    return out


def classify_hbond_occupancy(name: str, occ: list) -> list[dict]:
    if not occ:
        return [S("note", f"{name}：模擬中沒有出現配體與蛋白之間的氫鍵。", f"{name}: no ligand–protein hydrogen bond appears in the simulation.",
                  f"{name}：シミュレーション中、リガンドとタンパク質の間に水素結合は現れませんでした。",
                  f"{name}: 시뮬레이션 동안 리간드와 단백질 사이에 수소 결합이 나타나지 않았습니다.")]
    stable = [(k, v) for k, v in occ if v >= 0.5]
    if stable:
        lz = "、".join(f"{k}（{v:.0%}）" for k, v in stable[:5])
        le = ", ".join(f"{k} ({v:.0%})" for k, v in stable[:5])
        return [S("good",
                  f"{name}：有 {len(stable)} 組穩定氫鍵（≥ 50 %），{lz}。",
                  f"{name}: {len(stable)} stable hydrogen bond{'s' if len(stable) > 1 else ''} (≥ 50 %), {le}.",
                  f"{name}：安定な水素結合（≥ 50 %）が {len(stable)} 本あります。{lz} です。",
                  f"{name}: 안정한 수소 결합(≥ 50 %)이 {len(stable)}개 있습니다. {le}.")]
    k, v = occ[0]
    return [S("note",
              f"{name}：沒有穩定氫鍵，最常出現的是 {k}（{v:.0%}），氫鍵屬於間歇性。",
              f"{name}: no stable hydrogen bond. The most frequent is {k} ({v:.0%}), so hydrogen bonding is intermittent.",
              f"{name}：安定な水素結合はありません。最も多いのは {k}（{v:.0%}）で、水素結合は断続的です。",
              f"{name}: 안정한 수소 결합이 없습니다. 가장 자주 나타나는 것은 {k} ({v:.0%})이며, 수소 결합이 간헐적입니다.")]


def classify_com(name: str, t, d) -> list[dict]:
    d = np.asarray(d, float)
    if len(d) < 5:
        return []
    a, b = _halves(d)
    if b - a > 2.0:
        return [S("caution",
                  f"{name}：質心距離從 {a:.1f} Å 增加到 {b:.1f} Å（> 2 Å），配體正在離開口袋。",
                  f"{name}: the centre-of-mass distance grows from {a:.1f} Å to {b:.1f} Å (> 2 Å). The ligand is leaving the pocket.",
                  f"{name}：重心間距離が {a:.1f} Å から {b:.1f} Å に増えています（> 2 Å）。リガンドはポケットから離れつつあります。",
                  f"{name}: 질량 중심 거리가 처음 {a:.1f} Å에서 후반 {b:.1f} Å까지 늘었습니다(> 2 Å). 리간드가 포켓을 떠나고 있습니다.")]
    return [S("good",
              f"{name}：質心距離維持在 {b:.1f} Å 附近（變化 {b - a:+.1f} Å），配體留在原位。",
              f"{name}: the centre-of-mass distance stays near {b:.1f} Å (change {b - a:+.1f} Å), so the ligand stays in place.",
              f"{name}：重心間距離は {b:.1f} Å 付近で安定しており（変化 {b - a:+.1f} Å）、リガンドは元の位置にとどまっています。",
              f"{name}: 질량 중심 거리가 {b:.1f} Å 근처에서 유지됩니다(변화 {b - a:+.1f} Å). 리간드가 제자리에 있습니다.")]


def classify_burial(name: str, frac) -> list[dict]:
    f = np.asarray(frac, float)
    if len(f) < 3:
        return []
    m = float(f[len(f) // 2:].mean())
    if m >= 0.7:
        return [S("good",
                  f"{name}：後半段平均有 {m:.0%} 的表面被蛋白遮蔽（≥ 70 %），配體深埋在口袋裡。",
                  f"{name}: {m:.0%} of the surface is shielded on average in the second half (≥ 70 %), so the ligand is deeply buried.",
                  f"{name}：後半では表面の平均 {m:.0%} がタンパク質に覆われており（≥ 70 %）、リガンドはポケットの奥に埋まっています。",
                  f"{name}: 후반부에 표면의 평균 {m:.0%}가 단백질에 가려져 있습니다(≥ 70 %). 리간드가 포켓 깊이 묻혀 있습니다.")]
    if m >= 0.4:
        return [S("note",
                  f"{name}：平均遮蔽 {m:.0%}（40 % 到 70 %），部分埋藏，部分暴露在溶劑中。",
                  f"{name}: {m:.0%} shielded on average (40–70 %), partly buried and partly exposed.",
                  f"{name}：平均 {m:.0%} が覆われています（40〜70 %）。一部は埋まり、一部は溶媒にさらされています。",
                  f"{name}: 평균 {m:.0%}가 가려져 있습니다(40~70 %). 일부는 묻혀 있고 일부는 용매에 노출되어 있습니다.")]
    return [S("caution",
              f"{name}：平均只有 {m:.0%} 被遮蔽（< 40 %），配體大部分暴露在溶劑中，屬於表面結合。",
              f"{name}: only {m:.0%} shielded on average (< 40 %). The ligand is mostly exposed, which is surface binding.",
              f"{name}：覆われているのは平均 {m:.0%} だけです（< 40 %）。リガンドの大部分が溶媒にさらされた、表面での結合です。",
              f"{name}: 평균 {m:.0%}만 가려져 있습니다(< 40 %). 리간드 대부분이 용매에 노출된 표면 결합입니다.")]


def classify_growth(name: str, y, what: tuple) -> list[dict]:
    """what: the quantity's name, (zh, en) or (zh, en, ja, ko); the English name decides the 'internal' rule."""
    y = np.asarray(y, float)
    if len(y) < 5:
        return []
    a, b = _halves(y)
    ch = (b - a) / a if a else 0.0
    wz, we, wj, wk = _lang4(what)
    if ch > 0.05:
        return [S("caution",
                  f"{name}：{wz}從 {a:,.0f} 增加到 {b:,.0f}（{ch:+.1%}，> 5 %），蛋白可能部分展開。",
                  f"{name}: {we} grows from {a:,.0f} to {b:,.0f} ({ch:+.1%}, > 5 %), so the protein may be partly unfolding.",
                  f"{name}：{wj}が {a:,.0f} から {b:,.0f} に増えています（{ch:+.1%}、> 5 %）。タンパク質が部分的にほどけている可能性があります。",
                  f"{name}: {wk} 값이 {a:,.0f}에서 {b:,.0f}까지 늘었습니다({ch:+.1%}, > 5 %). 단백질이 부분적으로 풀리고 있을 수 있습니다.")]
    if ch < -0.10 and we.startswith("internal"):
        return [S("caution",
                  f"{name}：{wz}從 {a:,.0f} 降到 {b:,.0f}（{ch:+.1%}），結構逐漸鬆散。",
                  f"{name}: {we} falls from {a:,.0f} to {b:,.0f} ({ch:+.1%}), so the structure is loosening.",
                  f"{name}：{wj}が {a:,.0f} から {b:,.0f} に減っています（{ch:+.1%}）。構造がゆるんできています。",
                  f"{name}: {wk} 값이 {a:,.0f}에서 {b:,.0f}까지 줄었습니다({ch:+.1%}). 구조가 느슨해지고 있습니다.")]
    return [S("good",
              f"{name}：{wz}維持穩定（{a:,.0f} 到 {b:,.0f}，{ch:+.1%}）。",
              f"{name}: {we} stays stable ({a:,.0f} to {b:,.0f}, {ch:+.1%}).",
              f"{name}：{wj}は安定しています（{a:,.0f} から {b:,.0f}、{ch:+.1%}）。",
              f"{name}: {wk} 값이 안정적입니다({a:,.0f}에서 {b:,.0f}, {ch:+.1%}).")]


def classify_dssp(name: str, frac: dict) -> list[dict]:
    out = []
    for c, lz, le, lj, lk in (("H", "螺旋", "helix", "ヘリックス", "나선"), ("E", "摺板", "strand", "ストランド", "가닥")):
        y = np.asarray(frac.get(c) or [], float)
        if len(y) < 5 or y.max() < 0.02:
            continue
        a, b = _halves(y)
        if a - b > 0.05:
            out.append(S("caution",
                         f"{name}：{lz}比例從 {a:.0%} 降到 {b:.0%}，下降超過 5 個百分點，有局部展開。",
                         f"{name}: {le} content falls from {a:.0%} to {b:.0%} (more than 5 points), a sign of local unfolding.",
                         f"{name}：{lj}の割合が {a:.0%} から {b:.0%} に下がっています（5 ポイント超の低下）。局所的にほどけています。",
                         f"{name}: {lk} 비율이 {a:.0%}에서 {b:.0%}로 줄었습니다(5 포인트 넘게 감소). 국소적으로 풀리고 있습니다."))
        else:
            out.append(S("good",
                         f"{name}：{lz}比例維持在 {b:.0%}（開始時 {a:.0%}），二級結構保持。",
                         f"{name}: {le} content stays at {b:.0%} (start {a:.0%}), so the secondary structure is kept.",
                         f"{name}：{lj}の割合は {b:.0%} を保っており（開始時 {a:.0%}）、二次構造は維持されています。",
                         f"{name}: {lk} 비율이 {b:.0%}를 유지합니다(시작 {a:.0%}). 이차 구조가 유지됩니다."))
    return out


def classify_pca(name: str, p: dict) -> list[dict]:
    if not p:
        return []
    ex = p.get("explained") or []
    basins = (p.get("landscape") or {}).get("basins") or []
    var = sum(ex[:2])
    lead = (f"{name}：前兩個主成分解釋 {var:.0%} 的運動", f"{name}: the first two components explain {var:.0%} of the motion",
            f"{name}：第1・第2主成分で運動の {var:.0%} を説明できます", f"{name}: 첫 두 주성분이 운동의 {var:.0%}를 설명합니다")
    if len(basins) <= 1:
        return [S("good",
                  lead[0] + "。地形只有一個主要低谷，蛋白停留在單一構形狀態。",
                  lead[1] + ". The landscape has one main basin, so the protein stays in a single conformational state.",
                  lead[2] + "。地形の主な谷は1つで、タンパク質は単一の構造状態にとどまっています。",
                  lead[3] + ". 지형에 주요 골이 하나뿐이므로 단백질이 단일 구조 상태에 머뭅니다.")]
    pops = "、".join(f"{b[3]:.0%}" for b in basins if len(b) > 3)
    pops_en = ", ".join(f"{b[3]:.0%}" for b in basins if len(b) > 3)
    return [S("note",
              lead[0] + f"。地形有 {len(basins)} 個低谷（各約占 {pops} 的時間），蛋白在多個構形狀態之間轉換。",
              lead[1] + f". The landscape has {len(basins)} basins (about {pops_en} of the time each), so the protein moves "
              "between several conformational states.",
              lead[2] + f"。地形には谷が {len(basins)} 個あり（それぞれ時間の約 {pops}）、タンパク質は複数の構造状態の間を行き来しています。",
              lead[3] + f". 지형에 골이 {len(basins)}개 있으며(각각 시간의 약 {pops_en}), 단백질이 여러 구조 상태 사이를 오갑니다.")]


def classify_clusters(name: str, c: dict) -> list[dict]:
    pops = c.get("populations") or []
    if not pops:
        return []
    top = pops[0] if pops else 0
    nc = c.get("n_clusters")
    if top >= 0.6:
        return [S("good",
                  f"{name}：{nc} 個叢集中最大的占 {top:.0%}（≥ 60 %），有主導的結合構形。",
                  f"{name}: the largest of {nc} clusters holds {top:.0%} (≥ 60 %), so there is a dominant bound conformation.",
                  f"{name}：{nc} 個のクラスターのうち最大のものが {top:.0%} を占め（≥ 60 %）、主要な結合構造があります。",
                  f"{name}: 클러스터 {nc}개 중 가장 큰 것이 {top:.0%}를 차지합니다(≥ 60 %). 지배적인 결합 구조가 있습니다.")]
    return [S("note",
              f"{name}：共 {nc} 個叢集，最大的只占 {top:.0%}，構形或結合模式在模擬中變動。請比較各叢集的代表結構。",
              f"{name}: {nc} clusters, and the largest holds only {top:.0%}. The conformation or binding mode changes, so compare "
              "the representative structures.",
              f"{name}：クラスターは {nc} 個で、最大のものでも {top:.0%} しかありません。構造または結合様式がシミュレーション中に変化しています。"
              "各クラスターの代表構造を比べてください。",
              f"{name}: 클러스터가 {nc}개이며 가장 큰 것도 {top:.0%}에 불과합니다. 구조나 결합 모드가 시뮬레이션 중에 바뀌므로 "
              "각 클러스터의 대표 구조를 비교하십시오.")]


def classify_dccm(name: str, C, ref=None) -> list[dict]:
    C = np.asarray(C, float)
    n = len(C)
    if n < 10:
        return []
    far = np.abs(np.subtract.outer(np.arange(n), np.arange(n))) > 5
    strong = float((np.abs(C[far]) > 0.6).mean())
    out = [S("note",
             f"{name}：相隔 5 個殘基以上的殘基對中，有 {strong:.1%} 呈現強相關（|r| > 0.6）。",
             f"{name}: {strong:.1%} of residue pairs more than 5 apart are strongly correlated (|r| > 0.6).",
             f"{name}：5 残基以上離れた残基対のうち {strong:.1%} に強い相関があります（|r| > 0.6）。",
             f"{name}: 5개 잔기 이상 떨어진 잔기 쌍 중 {strong:.1%}에서 강한 상관(|r| > 0.6)이 나타납니다.")]
    if ref is not None and np.asarray(ref).shape == C.shape:
        R = np.asarray(ref, float)
        d = float(np.abs(C[far]).mean() - np.abs(R[far]).mean())
        if abs(d) >= 0.05:
            up = d > 0
            dz, de = ("增強" if up else "減弱"), ("stronger" if up else "weaker")
            dj, dk = ("強く" if up else "弱く"), ("강해졌습니다" if up else "약해졌습니다")
            out.append(S("note",
                         f"與蛋白單獨相比，{name} 的長距離相關平均{dz} {abs(d):.2f}，配體改變了區域之間的協同運動。",
                         f"Compared with the protein alone, long-range correlation in {name} is {abs(d):.2f} {de} on average, so "
                         "the ligand changes the coupling between regions.",
                         f"タンパク質単独と比べて、{name} の長距離相関は平均で {abs(d):.2f} {dj}なっています。リガンドが領域間の協調運動を変えています。",
                         f"단백질 단독과 비교해 {name}의 장거리 상관이 평균 {abs(d):.2f}만큼 {dk}. 리간드가 영역 사이의 협동 운동을 바꿉니다."))
    return out


def classify_fingerprint(name: str, occ: dict) -> list[dict]:
    rows = []
    kinds = (("salt_bridge", ("鹽橋", "salt bridge", "塩橋", "염다리")),
             ("like_charge_proximity", ("同號電荷接近", "like-charge proximity", "同符号電荷の接近", "같은 부호 전하 근접")),
             ("charged_proximity_ligand_charge_unknown", ("帶電殘基接近（配體電荷未知）", "charged proximity, ligand charge unknown",
                                                          "荷電残基の接近（リガンド電荷不明）", "하전 잔기 근접(리간드 전하 미상)")),
             ("polar_proximity", ("極性接近（只看距離）", "polar proximity, distance only", "極性の接近（距離のみ）", "극성 근접(거리만)")),
             ("hydrophobic", ("疏水", "hydrophobic", "疎水性", "소수성")),
             # records written before D-97 (single class; ionic did not check the ligand charge)
             ("ionic", ("帶電接近（舊紀錄）", "charged proximity (old record)", "荷電の接近（旧記録）", "하전 근접(이전 기록)")),
             ("polar", ("極性接近（舊紀錄）", "polar proximity (old record)", "極性の接近（旧記録）", "극성 근접(이전 기록)")))
    for kind, lab in kinds:
        for r, v in (occ.get(kind) or {}).items():
            if v >= 0.5:
                rows.append((r, v, lab))
    if not rows:
        return [S("note",
                  f"{name}：沒有殘基與配體維持一半以上時間的作用，結合模式鬆散。",
                  f"{name}: no residue interacts with the ligand for more than half of the time, so the binding mode is loose.",
                  f"{name}：時間の半分以上リガンドと相互作用し続ける残基はありません。結合様式はゆるやかです。",
                  f"{name}: 시간의 절반 이상 리간드와 상호작용하는 잔기가 없습니다. 결합 모드가 느슨합니다.")]
    rows.sort(key=lambda x: -x[1])
    top = rows[:8]
    return [S("good",
              f"{name}：持續作用（≥ 50 %）的殘基有 " + "、".join(f"{r}（{lab[0]} {v:.0%}）" for r, v, lab in top) + "。",
              f"{name}: persistent interactions (≥ 50 %) with " + ", ".join(f"{r} ({lab[1]} {v:.0%})" for r, v, lab in top) + ".",
              f"{name}：持続的な相互作用（≥ 50 %）がある残基は " + "、".join(f"{r}（{lab[2]} {v:.0%}）" for r, v, lab in top) + " です。",
              f"{name}: 지속적인 상호작용(≥ 50 %)을 하는 잔기는 " + ", ".join(f"{r} ({lab[3]} {v:.0%})" for r, v, lab in top) + "입니다.")]


def classify_water(name: str, wb: dict) -> list[dict]:
    c = np.asarray(wb.get("count") or [], float)
    if len(c) < 3:
        return []
    m = float(c.mean())
    res = [r for r, v in (wb.get("residues") or []) if v >= 0.3]
    rz, re_ = "、".join(res[:5]), ", ".join(res[:5])
    if m >= 1:
        return [S("note",
                  f"{name}：平均 {m:.1f} 個水橋" + (f"，主要經由 {rz}" if res else "") + "。水分子參與結合，設計能取代這些水的分子可能提高親和力。",
                  f"{name}: {m:.1f} water bridges on average" + (f", mainly through {re_}" if res else "")
                  + ". Water takes part in binding, and designs that displace it may raise affinity.",
                  f"{name}：水架橋は平均 {m:.1f} 個" + (f"で、主に {rz} を介しています" if res else "です")
                  + "。水分子が結合に関わっているため、この水を置き換える設計で親和性が上がる可能性があります。",
                  f"{name}: 평균 {m:.1f}개의 물 다리가 있습니다" + (f"(주로 {re_} 경유)" if res else "")
                  + ". 물 분자가 결합에 참여하므로 이 물을 치환하는 설계로 친화도를 높일 수 있습니다.")]
    return [S("note",
              f"{name}：水橋很少（平均 {m:.1f}），配體與蛋白以直接接觸為主。",
              f"{name}: few water bridges ({m:.1f} on average), so the ligand contacts the protein directly.",
              f"{name}：水架橋はほとんどありません（平均 {m:.1f}）。リガンドとタンパク質は主に直接接触しています。",
              f"{name}: 물 다리가 거의 없습니다(평균 {m:.1f}). 리간드와 단백질이 주로 직접 접촉합니다.")]


def classify_overlap(name: str, o: dict, assessment: dict | None = None) -> list[dict]:
    """Adjacent-window overlap is LOCAL (D-96, A2): a low adjacent value does not by itself disconnect the profile —
    other windows may bridge it.  Connectivity is stated from the full-graph diagnostic."""
    if not o or "min_neighbour" not in o:
        return []
    mn = o["min_neighbour"]
    c = o.get("centers") or []
    i = int(np.argmin(o.get("neighbour") or [0]))
    where = f"{c[i]:.2f}–{c[i + 1]:.2f} nm" if len(c) > i + 1 else ""
    gs = _diag(assessment, "overlap_graph")
    if gs is None and o.get("matrix") is not None:
        from ..sampling.assessment import graph_connected, THRESHOLDS
        gc = graph_connected(o["matrix"], THRESHOLDS["overlap_edge_min"][0])
        gs = None if gc is None else ("pass" if gc else "fail")
    g = _GRAPH.get(gs or "unknown")
    if mn >= 0.2:
        lvl = "caution" if gs == "fail" else "good"
        return [S(lvl,
                  f"{name}：相鄰窗口的重疊最低為 {mn:.2f}（≥ 0.2，局部檢查）；{g[0]}。",
                  f"{name}: the lowest adjacent-window overlap is {mn:.2f} (≥ 0.2, a local check); {g[1]}.",
                  f"{name}：隣り合うウィンドウの重なりは最低でも {mn:.2f} です（≥ 0.2、局所的な確認）。{g[2]}。",
                  f"{name}: 이웃한 윈도우의 겹침은 최저 {mn:.2f}입니다(≥ 0.2, 국소 확인). {g[3]}.")]
    if gs == "pass":
        return [S("note",
                  f"{name}：{where} 的相鄰重疊只有 {mn:.2f}（局部偏低），但其他窗口在此處搭起橋梁，全部窗口對的重疊圖仍連通；該處誤差較大。",
                  f"{name}: the adjacent overlap at {where} is only {mn:.2f} (locally low), but other windows bridge it and the "
                  "overlap graph over all window pairs is still connected; the error is larger there.",
                  f"{name}：{where} の隣接ウィンドウの重なりは {mn:.2f} しかありません（局所的に低い）が、ほかのウィンドウが橋渡しをしており、"
                  "全ウィンドウ対の重なりグラフはつながっています。そこでは誤差が大きくなります。",
                  f"{name}: {where}의 이웃 겹침은 {mn:.2f}에 불과하지만(국소적으로 낮음) 다른 윈도우가 이어 주어 전체 윈도우 쌍의 겹침 "
                  "그래프는 연결되어 있습니다. 그 위치의 오차가 큽니다.")]
    lvl = "caution" if (gs == "fail" or mn < 0.05) else "note"
    return [S(lvl,
              f"{name}：{where} 的相鄰重疊只有 {mn:.2f}；{g[0]}。",
              f"{name}: the adjacent overlap at {where} is only {mn:.2f}; {g[1]}.",
              f"{name}：{where} の隣接ウィンドウの重なりは {mn:.2f} しかありません。{g[2]}。",
              f"{name}: {where}의 이웃 겹침은 {mn:.2f}에 불과합니다. {g[3]}.")]

def classify_convergence(name: str, conv: dict, assessment: dict | None = None) -> list[dict]:
    """The change between the last two cumulative estimates is LOCAL (D-96, A2).  "Converged" is never said from it;
    an overall statement comes only from `classify_assessment`."""
    vals = [(k, v.get("delta_pmf")) for k, v in sorted(conv.items()) if isinstance(v, dict) and v.get("delta_pmf") is not None]
    if len(vals) < 2:
        return []
    d = abs(vals[-1][1] - vals[-2][1])
    p = float(vals[-2][0])
    drift = _diag(assessment, "cumulative_drift")
    if d <= 2.0 and drift != "fail":
        return [S("note",
                  f"{name}：取樣從 {p:.0%} 增加到全部時，井深變化 {d:.1f} kJ mol⁻¹（≤ 2）。這只是最後兩個累積估計的比較，不單獨代表收斂。",
                  f"{name}: the depth changes by {d:.1f} kJ mol⁻¹ from {p:.0%} to all samples (≤ 2). This compares only the last "
                  "two cumulative estimates and does not by itself establish convergence.",
                  f"{name}：サンプルを {p:.0%} から全体に増やしたときの井戸の深さの変化は {d:.1f} kJ mol⁻¹ です（≤ 2）。最後の2つの累積推定値の"
                  "比較にすぎず、これだけで収束とはいえません。",
                  f"{name}: 샘플을 {p:.0%}에서 전체로 늘릴 때 우물 깊이 변화는 {d:.1f} kJ mol⁻¹입니다(≤ 2). 마지막 두 누적 추정값의 "
                  "비교일 뿐이며 이것만으로 수렴했다고 할 수 없습니다.")]
    if d <= 2.0:
        return [S("caution",
                  f"{name}：最後兩個累積估計只差 {d:.1f} kJ mol⁻¹，但從 50% 起的累積估計仍在漂移，取樣尚未穩定。",
                  f"{name}: the last two cumulative estimates differ by only {d:.1f} kJ mol⁻¹, but the estimates from 50 % on are "
                  "still drifting, so sampling has not stabilised.",
                  f"{name}：最後の2つの累積推定値の差は {d:.1f} kJ mol⁻¹ だけですが、50% 以降の推定値はまだ動き続けており、サンプリングは安定していません。",
                  f"{name}: 마지막 두 누적 추정값 차이는 {d:.1f} kJ mol⁻¹뿐이지만 50%부터의 추정값이 계속 움직여 샘플링이 안정되지 않았습니다.")]
    return [S("caution",
              f"{name}：取樣從 {p:.0%} 增加到全部時，井深仍變化 {d:.1f} kJ mol⁻¹（> 2），尚未穩定，需要更長的窗口。",
              f"{name}: the depth still changes by {d:.1f} kJ mol⁻¹ from {p:.0%} to all samples (> 2). It has not stabilised and "
              "longer windows are needed.",
              f"{name}：サンプルを {p:.0%} から全体に増やすと、井戸の深さがまだ {d:.1f} kJ mol⁻¹ 変化します（> 2）。安定していないため、ウィンドウを長くする必要があります。",
              f"{name}: 샘플을 {p:.0%}에서 전체로 늘리면 우물 깊이가 아직 {d:.1f} kJ mol⁻¹ 바뀝니다(> 2). 안정되지 않았으므로 윈도우를 더 길게 해야 합니다.")]


_DIAG_NAME = {
    "histogram_coverage": ("直方圖涵蓋", "histogram coverage", "ヒストグラムの範囲", "히스토그램 범위"),
    "adjacent_overlap_min": ("相鄰窗口重疊", "adjacent-window overlap", "隣接ウィンドウの重なり", "이웃 윈도우 겹침"),
    "overlap_graph": ("全窗口重疊圖連通", "full overlap-graph connectivity", "全ウィンドウ重なりグラフの連結", "전체 겹침 그래프 연결"),
    "window_ess": ("每窗口有效樣本數", "per-window effective samples", "ウィンドウごとの有効サンプル数", "윈도우별 유효 표본 수"),
    "solver": ("求解收斂", "solver convergence", "ソルバーの収束", "솔버 수렴"),
    "half_split": ("前後半一致", "half-split agreement", "前半後半の一致", "전후반 일치"),
    "cumulative_drift": ("累積估計漂移", "cumulative-estimate drift", "累積推定値のドリフト", "누적 추정값 드리프트"),
    "endpoint_plateau": ("末端持平", "endpoint plateau", "終端の平坦性", "끝부분 평탄"),
    "range_coverage": ("PMF 涵蓋取樣範圍", "PMF covers the sampled range", "PMF がサンプル範囲を覆う", "PMF의 샘플 범위 포함"),
}


def classify_assessment(name: str, a: dict | None) -> list[dict]:
    """One overall sentence from the D-96 Assessment — the only place an overall sampling statement is made."""
    if not a:
        return [S("caution",
                  f"{name}：這個結果沒有取樣品質評估（D-96 之前的舊資料），待重新分析；不做任何比較或排名。",
                  f"{name}: this result has no sampling assessment (written before D-96) and awaits reanalysis; it is not "
                  "compared or ranked.",
                  f"{name}：この結果には取得品質の評価がありません（D-96 以前の旧データ）。再解析待ちで、比較や順位づけはしません。",
                  f"{name}: 이 결과에는 샘플링 품질 평가가 없습니다(D-96 이전 데이터). 재분석 대기 중이며 비교나 순위를 매기지 않습니다.")]
    pick = lambda ids, k: "、".join(_DIAG_NAME.get(i, (i,) * 4)[k] for i in ids) if k in (0, 2) else \
        ", ".join(_DIAG_NAME.get(i, (i,) * 4)[k] for i in ids)  # noqa: E731
    failed, unknown = a.get("failed") or [], a.get("unknown") or []
    el = a.get("eligibility") or {}
    out = []
    if el.get("delta_pmf_path_specific"):
        out.append(S("good",
                     f"{name}：所有必要的取樣診斷都通過，ΔPMF 可作為這條拉離路徑、這組條件下的井深；不是內在親和力。",
                     f"{name}: every required sampling diagnostic passes, so ΔPMF qualifies as the well depth along this pull "
                     "path under these conditions; it is not an intrinsic affinity.",
                     f"{name}：必要な取得診断はすべて合格し、ΔPMF はこの引き離し経路・この条件での井戸の深さとして使えます。固有の親和性ではありません。",
                     f"{name}: 필요한 샘플링 진단을 모두 통과하여 ΔPMF는 이 당김 경로와 이 조건에서의 우물 깊이로 쓸 수 있습니다. 고유 친화도는 아닙니다."))
    else:
        out.append(S("caution",
                     f"{name}：取樣評估未通過（未通過：{pick(failed, 0) or '—'}；無紀錄：{pick([u for u in unknown if u not in failed], 0) or '—'}）。"
                     "剖面只當診斷曲線，不做比較或排名。",
                     f"{name}: the sampling assessment does not pass (failed: {pick(failed, 1) or '—'}; not recorded: "
                     f"{pick([u for u in unknown if u not in failed], 1) or '—'}). The profile is a diagnostic curve only and is "
                     "not compared or ranked.",
                     f"{name}：取得評価は不合格です（不合格：{pick(failed, 2) or '—'}、記録なし：{pick([u for u in unknown if u not in failed], 2) or '—'}）。"
                     "プロファイルは診断曲線としてだけ扱い、比較や順位づけはしません。",
                     f"{name}: 샘플링 평가를 통과하지 못했습니다(미통과: {pick(failed, 3) or '—'}; 기록 없음: "
                     f"{pick([u for u in unknown if u not in failed], 3) or '—'}). 프로파일은 진단 곡선으로만 쓰며 비교하거나 순위를 매기지 않습니다."))
    for c in a.get("conflicts") or []:
        out.append(S("note", f"{name}：診斷之間不一致：{c}。", f"{name}: diagnostics disagree: {c}.",
                     f"{name}：診断どうしが一致しません：{c}。", f"{name}: 진단끼리 일치하지 않습니다: {c}."))
    return out

def classify_properties(props: list[dict]) -> list[dict]:
    if not props:
        return []
    from .chem import lipinski_violations
    v = [lipinski_violations(p) for p in props]
    ok = sum(1 for x in v if x == 0)
    n2 = sum(1 for x in v if x >= 2)
    return [S("note",
              f"{len(props)} 個化合物中有 {ok} 個（{ok / len(props):.0%}）完全符合 Lipinski 規則，{n2} 個違反兩項以上。",
              f"Of {len(props)} compounds, {ok} ({ok / len(props):.0%}) meet all Lipinski rules and {n2} break two or more.",
              f"{len(props)} 個の化合物のうち {ok} 個（{ok / len(props):.0%}）が Lipinski の規則をすべて満たし、{n2} 個が2項目以上に違反しています。",
              f"화합물 {len(props)}개 중 {ok}개({ok / len(props):.0%})가 Lipinski 규칙을 모두 만족하고, {n2}개는 두 항목 이상을 어깁니다.")]


def classify_chem_space(xy, scores, names) -> list[dict]:
    xy, s = np.asarray(xy, float), np.asarray(scores, float)
    if len(s) < 6:
        return []
    k = max(3, len(s) // 5)
    top = np.argsort(s)[:k]
    d_all = float(np.mean(np.linalg.norm(xy[:, None] - xy[None], axis=-1)))
    d_top = float(np.mean(np.linalg.norm(xy[top][:, None] - xy[top][None], axis=-1)))
    if d_top < 0.6 * d_all:
        r = d_top / d_all
        return [S("note",
                  f"分數最好的 {k} 個化合物在化學空間中聚在一起（彼此距離是整體平均的 {r:.0%}），某一種結構類型有利結合。",
                  f"The {k} best-scoring compounds cluster in chemical space (mutual distance {r:.0%} of the average), so one "
                  "structural type favours binding.",
                  f"スコアが最も良い {k} 個の化合物は化学空間で集まっています（互いの距離は全体平均の {r:.0%}）。ある構造タイプが結合に有利です。",
                  f"점수가 가장 좋은 화합물 {k}개가 화학 공간에서 모여 있습니다(서로의 거리가 전체 평균의 {r:.0%}). 특정 구조 유형이 결합에 유리합니다.")]
    return [S("note",
              f"分數最好的 {k} 個化合物分散在化學空間中，多種骨架都可能結合。",
              f"The {k} best-scoring compounds are spread across chemical space, so several scaffolds may bind.",
              f"スコアが最も良い {k} 個の化合物は化学空間に散らばっています。複数の骨格が結合しうると考えられます。",
              f"점수가 가장 좋은 화합물 {k}개가 화학 공간에 흩어져 있습니다. 여러 골격이 결합할 수 있습니다.")]


_KIND_2D = {"salt_bridge": ("鹽橋（電荷相反）", "Salt bridges (opposite charges)", "塩橋（反対電荷）", "염다리(반대 전하)"),
            "like_charge_proximity": ("同號電荷接近（互斥）", "Like-charge proximity (repulsive)", "同符号電荷の接近（反発）", "같은 부호 전하 근접(반발)"),
            "charged_proximity_ligand_charge_unknown": ("帶電殘基接近（配體電荷未知，不判定鹽橋）",
                                                        "Charged-residue proximity (ligand charge unknown; no salt bridge called)",
                                                        "荷電残基の接近（リガンド電荷不明のため塩橋とは判定しない）",
                                                        "하전 잔기 근접(리간드 전하 미상, 염다리로 판정하지 않음)"),
            "polar_proximity": ("極性接近（只看距離，不是氫鍵判定）", "Polar proximity (distance only, not a hydrogen-bond assignment)",
                                "極性の接近（距離のみ、水素結合の判定ではない）", "극성 근접(거리만, 수소 결합 판정 아님)"),
            "hydrophobic": ("疏水作用", "Hydrophobic", "疎水性", "소수성"), "contact": ("其他接觸", "Other contacts", "その他の接触", "기타 접촉"),
            # records written before D-97
            "hbond": ("距離 ≤ 3.5 Å 的 N/O（舊紀錄；不是氫鍵判定）", "N/O within 3.5 Å (old record; not a hydrogen-bond assignment)",
                      "3.5 Å 以内の N/O（旧記録、水素結合の判定ではない）", "3.5 Å 이내 N/O(이전 기록, 수소 결합 판정 아님)"),
            "ionic": ("帶電原子接近（舊紀錄；未檢查配體電荷）", "Charged-atom proximity (old record; ligand charge not checked)",
                      "荷電原子の接近（旧記録、リガンド電荷は未確認）", "하전 원자 근접(이전 기록, 리간드 전하 미확인)")}


def classify_interaction_2d(name: str, cons: list[dict]) -> list[dict]:
    hit = [c for c in cons if c.get("res")]
    if not hit:
        return []
    kinds = {}
    for c in hit:                     # D-97: every label of every partner, not only the nearest atom's single class
        for p in c.get("partners") or [{"res": c["res"], "labels": [c["kind"]]}]:
            for k in p.get("labels") or [c["kind"]]:
                kinds.setdefault(k, set()).add(p["res"])
    lab = {k: _KIND_2D.get(k, (k, k, k, k)) for k in kinds}
    return [S("note",
              f"{name}：{len(hit)} 個配體原子與蛋白接觸。" + "".join(f"{lab[k][0]}：{'、'.join(sorted(v))}。" for k, v in kinds.items()),
              f"{name}: {len(hit)} ligand atoms contact the protein. " + " ".join(f"{lab[k][1]}: {', '.join(sorted(v))}." for k, v in kinds.items()),
              f"{name}：リガンドの {len(hit)} 個の原子がタンパク質と接触しています。" + "".join(f"{lab[k][2]}：{'、'.join(sorted(v))}。" for k, v in kinds.items()),
              f"{name}: 리간드 원자 {len(hit)}개가 단백질과 접촉합니다. " + " ".join(f"{lab[k][3]}: {', '.join(sorted(v))}." for k, v in kinds.items()))]


FIG.update({
    "pose_rmsd": {
        "title": ("姿勢相似度矩陣", "Pose similarity matrix", "ポーズ類似度行列", "포즈 유사도 행렬"),
        "caption": ("各姿勢之間的 RMSD，直接在受體座標中比較，不重新疊合，依名次排列。",
                    "RMSD between every pair of poses in the receptor frame, without superposition, ordered by rank.",
                    "各ポーズ間の RMSD です。受容体の座標系でそのまま比べ（重ね合わせなし）、順位順に並べています。",
                    "포즈 사이의 RMSD입니다. 수용체 좌표계에서 그대로 비교했고(중첩 없음) 순위대로 정렬했습니다."),
        "read": ("前幾名所在的角落若是一塊低 RMSD 區域，代表低分姿勢屬於同一種結合模式。顏色分成幾塊，代表有不同的結合模式。",
                 "A low-RMSD block in the corner of the top ranks means the low-scoring poses share one binding mode. Separate "
                 "blocks are distinct modes.",
                 "上位ポーズの角が RMSD の低いブロックになっていれば、低スコアのポーズは同じ結合様式です。ブロックが分かれていれば、異なる結合様式があります。",
                 "상위 순위가 있는 모서리가 RMSD가 낮은 블록이면 낮은 점수의 포즈들이 같은 결합 모드입니다. 블록이 나뉘어 있으면 서로 다른 결합 모드가 있는 것입니다."),
    },
    "funnel": {
        "title": ("對接漏斗", "Docking funnel", "ドッキングファネル", "도킹 깔때기"),
        "caption": ("每個姿勢的分數對它與共結晶姿勢的 RMSD 作圖，用來做重新對接自檢。",
                    "Score of each pose against its RMSD from the co-crystal pose, as a redocking check.",
                    "各ポーズのスコアを、共結晶ポーズからの RMSD に対してプロットしています（再ドッキングによる自己検証）。",
                    "각 포즈의 점수를 공결정 포즈와의 RMSD에 대해 그렸습니다(재도킹 자체 점검)."),
        "read": ("理想情況下，分數最好的點落在 2 Å 以內，而且 RMSD 越大分數越差，形成漏斗形。這表示評分函數能辨認正確的結合模式。",
                 "Ideally the best-scoring point lies within 2 Å and scores worsen as RMSD grows, giving a funnel shape. This "
                 "means the scoring function recognises the correct mode.",
                 "理想的には、最もスコアの良い点が 2 Å 以内にあり、RMSD が大きくなるほどスコアが悪くなる漏斗形になります。これはスコア関数が正しい結合様式を見分けられることを示します。",
                 "이상적으로는 점수가 가장 좋은 점이 2 Å 이내에 있고 RMSD가 커질수록 점수가 나빠져 깔때기 모양이 됩니다. 이는 점수 함수가 올바른 결합 모드를 알아본다는 뜻입니다."),
    },
    "pose_positions": {
        "title": ("姿勢在搜尋區中的位置", "Pose positions in the search box", "探索領域内のポーズの位置", "탐색 영역 안의 포즈 위치"),
        "caption": ("各姿勢中心的俯視（x–y）與側視（x–z）投影。框線是搜尋區，顏色是分數。",
                    "Top (x–y) and side (x–z) projections of the pose centres. The frame is the search box and colour is the score.",
                    "各ポーズ中心の上面（x–y）と側面（x–z）への投影です。枠は探索領域、色はスコアです。",
                    "각 포즈 중심의 위(x–y)와 옆(x–z) 투영입니다. 테두리는 탐색 영역, 색은 점수입니다."),
        "read": ("點聚集在一處，代表配體一致選擇同一個口袋。點散布在搜尋區各處，代表有多個候選位置，盲對接時常見。",
                 "Points gathered in one place mean the ligand consistently chooses one pocket. Points scattered across the box "
                 "mean several candidate sites, which is common in blind docking.",
                 "点が1か所に集まっていれば、リガンドは一貫して同じポケットを選んでいます。探索領域全体に散らばっていれば候補部位が複数あり、ブラインドドッキングではよくあることです。",
                 "점이 한곳에 모여 있으면 리간드가 일관되게 같은 포켓을 고른 것입니다. 탐색 영역 곳곳에 흩어져 있으면 후보 부위가 여러 개이며, 블라인드 도킹에서 흔합니다."),
    },
    "pose_contacts": {
        "title": ("各姿勢的接觸殘基", "Contact residues of each pose", "各ポーズの接触残基", "포즈별 접촉 잔기"),
        "caption": ("每個姿勢與哪些殘基相距 4 Å 以內。列是殘基，行是姿勢名次。",
                    "Residues each pose contacts within 4 Å. Rows are residues and columns are pose ranks.",
                    "各ポーズから 4 Å 以内にある残基です。行が残基、列がポーズの順位です。",
                    "각 포즈에서 4 Å 이내에 있는 잔기입니다. 행은 잔기, 열은 포즈 순위입니다."),
        "read": ("整列都有接觸的殘基是結合位的核心。只在少數姿勢出現的殘基屬於替代結合模式。",
                 "Residues contacted across the whole row form the binding-site core. Residues seen in only a few poses belong "
                 "to alternative modes.",
                 "行全体で接触している残基が結合部位の中心です。少数のポーズでしか現れない残基は別の結合様式に属します。",
                 "행 전체에서 접촉하는 잔기가 결합 부위의 핵심입니다. 일부 포즈에서만 보이는 잔기는 다른 결합 모드에 속합니다."),
    },
    "ligand_compare": {
        "title": ("配體比較", "Ligand comparison", "リガンドの比較", "리간드 비교"),
        "caption": ("各配體最佳姿勢的分數、配體效率（每個重原子的分數）與重原子數。",
                    "Best-pose score, ligand efficiency (score per heavy atom) and heavy-atom count of each ligand.",
                    "各リガンドの最良ポーズのスコア、リガンド効率（重原子あたりのスコア）、重原子数です。",
                    "각 리간드 최고 포즈의 점수, 리간드 효율(중원자당 점수), 중원자 수입니다."),
        "read": ("分數比較會受分子大小影響，配體效率可以校正大小。相差不到 1 kcal mol⁻¹ 的配體不能排序。",
                 "Scores favour larger molecules, and ligand efficiency corrects for size. Ligands within 1 kcal mol⁻¹ of each "
                 "other cannot be ordered.",
                 "スコアは大きな分子ほど有利になり、リガンド効率はその大きさを補正します。差が 1 kcal mol⁻¹ 未満のリガンドは順位をつけられません。",
                 "점수는 큰 분자에 유리하며 리간드 효율이 크기를 보정합니다. 차이가 1 kcal mol⁻¹ 미만인 리간드는 순위를 매길 수 없습니다."),
    },
})


FIG.update({
    "joint_poses": {
        "title": ("聯合姿勢的共同佔位檢查", "Co-occupancy of the joint poses", "共同ポーズの同時占有の確認", "공동 포즈의 동시 점유 확인"),
        "caption": ("上圖是每個聯合姿勢中配體間的最短距離。綠帶是共同佔位且不碰撞的範圍，紅虛線以下是碰撞。下圖是每個配體接觸的蛋白重原子數。點線標出採用的姿勢。",
                    "The top panel shows the minimum ligand–ligand distance of each joint pose. The green band is co-occupancy "
                    "without a clash, and below the red line is a clash. The bottom panel shows the protein heavy atoms "
                    "contacted by each ligand. The dotted line marks the pose used.",
                    "上段は各共同ポーズでのリガンド間の最短距離です。緑の帯は衝突せずに同時占有している範囲で、赤い破線より下は衝突です。"
                    "下段は各リガンドが接触するタンパク質の重原子数です。点線は採用したポーズを示します。",
                    "위쪽은 공동 포즈마다 리간드 사이의 최단 거리입니다. 초록 띠는 충돌 없이 동시 점유하는 범위이고, 빨간 점선 아래는 충돌입니다. "
                    "아래쪽은 각 리간드가 접촉하는 단백질 중원자 수입니다. 점선은 선택한 포즈를 표시합니다."),
        "read": ("可信的聯合姿勢要落在綠帶內，而且每個配體都有足夠的接觸。只有一個配體埋入、另一個只是靠在它身上的姿勢不可信。",
                 "A credible joint pose sits in the green band with every ligand making enough contacts. A pose where one ligand "
                 "is buried and the other only leans on it is not credible.",
                 "信頼できる共同ポーズは緑の帯の中にあり、どのリガンドも十分に接触しています。1つのリガンドだけが埋まり、もう1つがそれに寄りかかっているだけのポーズは信頼できません。",
                 "믿을 만한 공동 포즈는 초록 띠 안에 있고 모든 리간드가 충분히 접촉합니다. 리간드 하나만 묻혀 있고 다른 하나는 거기에 기대어 있기만 한 포즈는 믿을 수 없습니다."),
    },
    "joint_positions": {
        "title": ("各配體在搜尋區中的位置", "Position of each ligand in the search box", "探索領域内の各リガンドの位置", "탐색 영역 안의 리간드별 위치"),
        "caption": ("各聯合姿勢中每個配體中心的投影。顏色代表配體，數字是名次。",
                    "Centre of each ligand in each joint pose. Colour marks the ligand and the number is the rank.",
                    "各共同ポーズでの各リガンド中心の投影です。色はリガンド、数字は順位です。",
                    "공동 포즈마다 각 리간드 중심의 투영입니다. 색은 리간드, 숫자는 순위입니다."),
        "read": ("每種顏色各自聚集，代表排列一致。顏色互相交錯，代表配體在不同姿勢中互換位置，哪個配體佔哪個子位點並不確定。",
                 "Each colour gathered in its own place means a consistent arrangement. Interleaved colours mean the ligands swap "
                 "places between poses, so which ligand holds which subsite is uncertain.",
                 "色ごとにまとまっていれば配置は一貫しています。色が入り混じっていれば、ポーズによってリガンドの位置が入れ替わっており、"
                 "どのリガンドがどのサブサイトを占めるかは確定できません。",
                 "색마다 따로 모여 있으면 배치가 일관된 것입니다. 색이 섞여 있으면 포즈마다 리간드가 자리를 바꾸는 것이므로 "
                 "어느 리간드가 어느 하위 부위를 차지하는지 확실하지 않습니다."),
    },
    "subsites": {
        "title": ("子位點地圖", "Subsite map", "サブサイトマップ", "하위 부위 지도"),
        "caption": ("採用的聯合姿勢中，每個配體 4 Å 內的殘基。列是殘基，行是配體。",
                    "Residues within 4 Å of each ligand in the joint pose used. Rows are residues and columns are ligands.",
                    "採用した共同ポーズで、各リガンドから 4 Å 以内にある残基です。行が残基、列がリガンドです。",
                    "선택한 공동 포즈에서 각 리간드로부터 4 Å 이내에 있는 잔기입니다. 행은 잔기, 열은 리간드입니다."),
        "read": ("同一列有兩格以上，代表該殘基夾在配體之間，是共用的子位點，可能有競爭。各自獨立的區塊代表配體佔據不同子位點。",
                 "A row with two or more filled cells is a residue between ligands. That is a shared subsite with possible "
                 "competition. Separate blocks mean the ligands hold different subsites.",
                 "1つの行に2マス以上あれば、その残基はリガンドの間にあり、共有されたサブサイトです。競合が起きている可能性があります。"
                 "ブロックが分かれていれば、リガンドは別々のサブサイトを占めています。",
                 "한 행에 칸이 두 개 이상이면 그 잔기는 리간드 사이에 있는 공유 하위 부위이며 경쟁이 있을 수 있습니다. "
                 "블록이 따로 떨어져 있으면 리간드가 서로 다른 하위 부위를 차지하는 것입니다."),
    },
    "ll_distance": {
        "title": ("配體之間的距離", "Distance between the ligands", "リガンド間の距離", "리간드 사이 거리"),
        "caption": ("多配體系統模擬中各配體中心之間的距離。", "Distance between the ligand centroids during the multi-ligand simulation.",
                    "複数リガンド系のシミュレーションにおける、各リガンド中心間の距離です。", "다중 리간드 시스템 시뮬레이션에서 리간드 중심 사이의 거리입니다."),
        "read": ("距離維持穩定，代表模擬支持共同佔位。距離持續增加，代表其中一個配體離開，對接得到的聯合姿勢不被支持。",
                 "A steady distance means the simulation supports co-occupancy. A steadily growing one means a ligand leaves and "
                 "the joint docking pose is not supported.",
                 "距離が安定していれば、シミュレーションは同時占有を支持しています。増え続ける場合は一方のリガンドが離れており、ドッキングで得た共同ポーズは支持されません。",
                 "거리가 안정적이면 시뮬레이션이 동시 점유를 뒷받침하는 것입니다. 계속 늘면 리간드 하나가 떠나는 것이므로 도킹으로 얻은 공동 포즈는 뒷받침되지 않습니다."),
    },
})


FIG.update({
    "cooperativity": {
        "title": ("協同自由能（熱力學循環）", "Binding cooperativity (thermodynamic cycle)", "結合の協同性（熱力学サイクル）", "결합 협동성(열역학 순환)"),
        "caption": ("每個配體單獨結合，以及另一配體已結合時的結合自由能，越低越強，誤差棒為 σ。圖上的數字是兩者之差，也就是循環的一條路徑。",
                    "Binding free energy of each ligand alone and with the partner bound. Lower is stronger and the error bars "
                    "are σ. The number is their difference, which is one leg of the cycle.",
                    "各リガンドが単独で結合する場合と、相手のリガンドがすでに結合している場合の結合自由エネルギーです。低いほど強く、エラーバーは σ です。"
                    "数字は両者の差で、サイクルの片方の経路にあたります。",
                    "각 리간드가 단독으로 결합할 때와 상대 리간드가 이미 결합해 있을 때의 결합 자유 에너지입니다. 낮을수록 강하며 오차 막대는 σ입니다. "
                    "숫자는 두 값의 차이로, 순환의 한 경로에 해당합니다."),
        "read": ("熱力學要求兩條路徑得到相同的差，也就是循環閉合。先檢查閉合，再看平均差。負值是正協同（彼此加強），正值是互斥。兩條路徑不一致時，代表採樣未收斂，這時不下結論。",
                 "Thermodynamics requires both legs to give the same difference, which means the cycle closes. Check closure "
                 "first, then the mean. A negative value is positive cooperativity and a positive value is competition. Legs "
                 "that disagree mean the sampling has not converged, and no conclusion is drawn.",
                 "熱力学的には、2つの経路で同じ差が得られる（サイクルが閉じる）必要があります。まず閉じているかを確かめ、それから平均の差を見ます。"
                 "負の値は正の協同性（互いに強め合う）、正の値は競合です。2つの経路が一致しない場合はサンプリングが収束していないため、結論を出しません。",
                 "열역학적으로 두 경로는 같은 차이를 주어야 하며, 이것이 순환이 닫힌다는 뜻입니다. 먼저 닫힘을 확인하고 그다음 평균 차이를 봅니다. "
                 "음수는 양의 협동성(서로 강화), 양수는 경쟁입니다. 두 경로가 일치하지 않으면 샘플링이 수렴하지 않은 것이므로 결론을 내리지 않습니다."),
    },
})


def classify_cooperativity(rec: dict) -> list[dict]:
    lvl = {"COOPERATIVE": "note", "ANTICOOPERATIVE": "note", "NONE": "good", "UNCERTAIN": "caution", "NOT_CLOSED": "warn",
           "PER_LIGAND": "note", "INSUFFICIENT": "caution"}.get(rec.get("status"), "note")
    return [S(lvl, *rec["why"])] if rec.get("why") else []


# ============================================================================================ D-82: fold, membrane, long run, coarse-grained
FIG.update({
    "fold_plddt": {
        "title": ("預測結構的逐殘基可信度（pLDDT）", "Per-residue confidence of the predicted structure (pLDDT)",
                  "予測構造の残基ごとの信頼度（pLDDT）", "예측 구조의 잔기별 신뢰도(pLDDT)"),
        "caption": ("每個殘基的 pLDDT。背景色帶依常用分級：90 以上很高、70 到 90 可信、50 到 70 偏低、50 以下很低。虛線分開不同的鏈。",
                    "pLDDT of every residue. The background bands follow the usual grades: above 90 very high, 70–90 confident, "
                    "50–70 low and below 50 very low. Dashed lines separate the chains.",
                    "各残基の pLDDT です。背景の色帯は一般的な区分で、90 以上はとても高い、70〜90 は信頼できる、50〜70 は低い、50 未満はとても低いです。"
                    "破線は鎖の境目です。",
                    "각 잔기의 pLDDT입니다. 배경 색 띠는 흔히 쓰는 구분으로 90 이상은 매우 높음, 70~90은 신뢰 가능, 50~70은 낮음, 50 미만은 매우 낮음입니다. "
                    "점선은 사슬 경계입니다."),
        "read": ("pLDDT 是模型對自己局部結構的信心，不是和實驗比較的誤差。平均 70 以上可以當起始構形，50 到 70 要靠 MD 檢查，50 以下的區段通常沒有固定結構，"
                 "不要解讀它的構形。末端偏低很常見。",
                 "pLDDT is the model's confidence in its own local structure, not an error against experiment. A mean of 70 or "
                 "more is a usable starting structure, 50–70 needs checking in MD, and stretches below 50 usually have no fixed "
                 "structure, so do not interpret their conformation. Low termini are common.",
                 "pLDDT はモデル自身の局所構造に対する確信度で、実験との誤差ではありません。平均 70 以上なら初期構造として使え、50〜70 は MD で確認が必要です。"
                 "50 未満の区間はふつう決まった構造を持たないため、その形を解釈しないでください。末端が低いのはよくあることです。",
                 "pLDDT는 모델이 자신의 국소 구조에 대해 갖는 확신도이며 실험과 비교한 오차가 아닙니다. 평균 70 이상이면 시작 구조로 쓸 수 있고, "
                 "50~70은 MD로 확인해야 합니다. 50 미만 구간은 대개 고정된 구조가 없으므로 그 모양을 해석하지 마십시오. 말단이 낮은 것은 흔합니다."),
    },
    "fold_superposition": {
        "title": ("預測受體與實際受體的逐殘基偏差", "Predicted versus actual receptor, deviation per residue",
                  "予測受容体と実際の受容体の残基ごとのずれ", "예측 수용체와 실제 수용체의 잔기별 편차"),
        "caption": ("以序列比對配對的 Cα，Kabsch 疊合後每個殘基與實際受體的距離。深色是胜肽 10 Å 內的結合位殘基，虛線是 2 Å。",
                    "Distance of each sequence-matched Cα from the actual receptor after Kabsch superposition. Dark bars are "
                    "binding-site residues within 10 Å of the peptide. The dashed line marks 2 Å.",
                    "配列アラインメントで対応づけた Cα を Kabsch 法で重ね合わせた後の、各残基と実際の受容体との距離です。濃い棒はペプチドから 10 Å 以内の結合部位残基、破線は 2 Å です。",
                    "서열 정렬로 짝지은 Cα를 Kabsch 방법으로 겹친 뒤 각 잔기와 실제 수용체 사이의 거리입니다. 진한 막대는 펩타이드 10 Å 이내의 결합 부위 잔기이고 점선은 2 Å입니다."),
        "read": ("整體 Cα RMSD 在 2 Å 以內，代表預測的受體和實際結構一致，胜肽的位置可以搬到實際受體上。重要的是結合位：結合位殘基偏差小，胜肽的姿勢才可信。"
                 "loop 與末端偏差大是常見的，只要不在結合位就影響不大。",
                 "An overall Cα RMSD within 2 Å means the predicted receptor matches the actual structure and the peptide's "
                 "position can be transferred. The binding site matters most: the peptide pose is credible only if the site "
                 "residues deviate little. Large deviations in loops and termini are common and matter little away from the site.",
                 "全体の Cα RMSD が 2 Å 以内なら、予測した受容体は実際の構造と一致しており、ペプチドの位置を実際の受容体に移せます。"
                 "大事なのは結合部位で、結合部位の残基のずれが小さいときにだけペプチドのポーズを信頼できます。ループや末端のずれが大きいのはよくあることで、結合部位から離れていれば影響は小さいです。",
                 "전체 Cα RMSD가 2 Å 이내이면 예측한 수용체가 실제 구조와 일치하므로 펩타이드의 위치를 실제 수용체로 옮길 수 있습니다. "
                 "가장 중요한 것은 결합 부위입니다. 결합 부위 잔기의 편차가 작아야 펩타이드 포즈를 믿을 수 있습니다. 루프와 말단의 큰 편차는 흔하며 결합 부위에서 멀면 영향이 작습니다."),
    },
    "fold_contacts": {
        "title": ("胜肽與受體的接觸圖", "Peptide–receptor contact map", "ペプチドと受容体の接触マップ", "펩타이드-수용체 접촉 지도"),
        "caption": ("放進受體後，每個胜肽殘基（列）與受體殘基（欄）之間最短的重原子距離，只列出 8 Å 內的受體殘基。白框是 4 Å 以內的接觸。",
                    "Shortest heavy-atom distance between each peptide residue (rows) and receptor residue (columns) after "
                    "placement. Only receptor residues within 8 Å are shown. White boxes mark contacts within 4 Å.",
                    "受容体に置いた後の、各ペプチド残基（行）と受容体残基（列）の最短重原子間距離です。8 Å 以内の受容体残基だけを示し、白枠は 4 Å 以内の接触です。",
                    "수용체에 놓은 뒤 각 펩타이드 잔기(행)와 수용체 잔기(열) 사이의 최단 중원자 거리입니다. 8 Å 이내의 수용체 잔기만 표시했고 흰 테두리는 4 Å 이내 접촉입니다."),
        "read": ("4 Å 以內算接觸。一半以上的胜肽殘基有接觸，代表介面完整。只有少數殘基接觸，代表胜肽大多懸在溶劑中，預測的介面弱。"
                 "同一個受體殘基接觸好幾個胜肽殘基時，它可能是熱點。距離小於 1.5 Å 是原子重疊，最小化必須先解開。",
                 "Within 4 Å counts as a contact. Contacts on half or more of the peptide residues mean a complete interface. "
                 "Only a few contacting residues mean the peptide mostly hangs in solvent and the predicted interface is weak. "
                 "A receptor residue touching several peptide residues may be a hot spot. Below 1.5 Å atoms overlap and "
                 "minimisation has to resolve them first.",
                 "4 Å 以内を接触とします。ペプチド残基の半分以上が接触していれば界面は十分です。接触する残基が少なければペプチドの大部分は溶媒中にあり、予測された界面は弱いです。"
                 "1 つの受容体残基が複数のペプチド残基と接触していれば、ホットスポットの可能性があります。1.5 Å 未満は原子の重なりで、まず最小化で解消する必要があります。",
                 "4 Å 이내를 접촉으로 봅니다. 펩타이드 잔기의 절반 이상이 접촉하면 계면이 온전합니다. 접촉하는 잔기가 적으면 펩타이드 대부분이 용매에 떠 있어 예측된 계면이 약합니다. "
                 "한 수용체 잔기가 여러 펩타이드 잔기와 접촉하면 핫스팟일 수 있습니다. 1.5 Å 미만은 원자가 겹친 것이며 최소화로 먼저 풀어야 합니다."),
    },
    "membrane_equil": {
        "title": ("膜的平衡：每個脂質的面積與厚度", "Membrane equilibration: area per lipid and thickness",
                  "膜の平衡化：脂質あたりの面積と厚さ", "막 평형화: 지질당 면적과 두께"),
        "caption": ("上：每個脂質的面積。下：上下兩葉磷原子平面的距離（P–P 厚度）。灰色帶是實驗參考值 ±6 % 面積、±0.3 nm 厚度，虛線是後半段平均。",
                    "Top: area per lipid. Bottom: distance between the phosphate planes of the two leaflets (P–P thickness). "
                    "Grey bands are the experimental reference ±6 % in area and ±0.3 nm in thickness. Dotted lines are the second-half means.",
                    "上は脂質あたりの面積、下は上下 2 枚のリン原子面の距離（P–P 厚さ）です。灰色の帯は実験の参照値の面積 ±6 %、厚さ ±0.3 nm、点線は後半の平均です。",
                    "위는 지질당 면적, 아래는 위아래 두 층의 인 원자 평면 사이 거리(P–P 두께)입니다. 회색 띠는 실험 참고값의 면적 ±6 %, 두께 ±0.3 nm이고 점선은 후반부 평균입니다."),
        "read": ("膜平衡後，面積與厚度都在平台上，並落在灰色帶內。面積還在下降或上升，代表膜仍在收縮或展開，要延長平衡。落在帶外通常是溫度、組成或力場的問題。"
                 "含蛋白的膜，面積包含蛋白截面，只能看趨勢。",
                 "An equilibrated membrane has both area and thickness on a plateau inside the grey bands. An area still "
                 "falling or rising means the membrane is still contracting or expanding, so extend equilibration. Values "
                 "outside the band usually point to temperature, composition or force field. With a protein, the area includes "
                 "the protein cross-section, so only the trend is meaningful.",
                 "平衡化した膜では、面積と厚さがどちらも平坦で灰色の帯の中にあります。面積がまだ下がる、または上がる場合は膜が縮んでいるか広がっている途中なので、平衡化を延ばしてください。"
                 "帯の外にあるときは、たいてい温度、組成、力場の問題です。タンパク質を含む膜では面積にタンパク質の断面が含まれるため、傾向だけを見ます。",
                 "평형에 도달한 막은 면적과 두께가 모두 평탄하고 회색 띠 안에 있습니다. 면적이 계속 줄거나 늘면 막이 아직 수축하거나 팽창하는 중이므로 평형화를 늘리십시오. "
                 "띠 밖에 있으면 대개 온도, 조성, 역장의 문제입니다. 단백질이 있는 막은 면적에 단백질 단면이 포함되므로 경향만 봅니다."),
    },
    "membrane_density": {
        "title": ("沿膜法線的密度剖面", "Density profile along the membrane normal", "膜法線方向の密度分布", "막 법선 방향 밀도 분포"),
        "caption": ("各組原子的數密度對膜中心的距離 z（膜中心 z = 0），整段模擬平均。",
                    "Number density of each atom group against the distance z from the membrane centre (z = 0), averaged over the run.",
                    "各原子グループの数密度を膜中心からの距離 z（膜中心が z = 0）に対してプロットし、計算全体で平均しています。",
                    "각 원자 그룹의 수밀도를 막 중심으로부터의 거리 z(막 중심 z = 0)에 대해 그렸으며 전체 시뮬레이션에 걸쳐 평균했습니다."),
        "read": ("磷原子的兩個峰之間的距離就是膜厚。膜中心（|z| < 0.5 nm）的水密度應低於水相的 1 %，否則有孔洞或缺陷。胜肽或配體的分佈落在磷峰外側，代表在水中。"
                 "落在磷峰附近，代表吸附在頭基區。落在磷峰內側，代表插入膜中。",
                 "The distance between the two phosphate peaks is the thickness. Water at the centre (|z| < 0.5 nm) should be "
                 "below 1 % of bulk water, otherwise there is a pore or defect. A peptide or ligand distribution outside the "
                 "phosphate peaks is in the water, one near the peaks is adsorbed at the head groups, and one inside them has "
                 "inserted into the membrane.",
                 "リンの 2 つのピークの間隔が膜厚です。膜中心（|z| < 0.5 nm）の水密度はバルクの 1 % 未満であるべきで、それを超えるなら孔や欠陥があります。"
                 "ペプチドやリガンドの分布がリンのピークより外側なら水中、ピーク付近なら頭部基の領域に吸着、ピークより内側なら膜に入り込んでいます。",
                 "인의 두 피크 사이 거리가 막 두께입니다. 막 중심(|z| < 0.5 nm)의 물 밀도는 벌크의 1 % 미만이어야 하며, 넘으면 구멍이나 결함이 있는 것입니다. "
                 "펩타이드나 리간드 분포가 인 피크 바깥이면 물속에, 피크 근처면 머리 부분 영역에 흡착, 피크 안쪽이면 막 안으로 들어간 것입니다."),
    },
    "membrane_scd": {
        "title": ("脂肪鏈的序參數 −S_CD", "Acyl-chain order parameter −S_CD", "アシル鎖の秩序パラメータ −S_CD", "아실 사슬 질서 매개변수 −S_CD"),
        "caption": ("每個碳原子的 −S_CD，sn-1 與 sn-2 兩條鏈分開畫。碳編號從羰基往鏈尾增加。灰色帶是流體相常見的 0.12 到 0.25。",
                    "−S_CD of every carbon, sn-1 and sn-2 chains drawn separately. Carbon numbers increase from the carbonyl "
                    "towards the chain end. The grey band is the usual fluid-phase range 0.12–0.25.",
                    "各炭素の −S_CD で、sn-1 鎖と sn-2 鎖を分けて描いています。炭素番号はカルボニルから鎖末端に向かって増えます。灰色の帯は流動相でよく見られる 0.12〜0.25 です。",
                    "각 탄소의 −S_CD이며 sn-1과 sn-2 사슬을 따로 그렸습니다. 탄소 번호는 카르보닐에서 사슬 끝으로 갈수록 커집니다. 회색 띠는 유동상에서 흔한 0.12~0.25입니다."),
        "read": ("−S_CD 越大，鏈越有序。流體相的平台（碳 4 到 10）約 0.12 到 0.25，往鏈尾逐漸下降。平台高於 0.3 代表膜過於有序，可能接近凝膠相。"
                 "低於 0.12 代表過於無序。這是和氘 NMR 直接比較的量。",
                 "A larger −S_CD means a more ordered chain. In the fluid phase the plateau (carbons 4–10) is about 0.12–0.25 "
                 "and falls towards the chain end. A plateau above 0.3 means an over-ordered membrane, possibly near the gel "
                 "phase, and one below 0.12 an over-disordered one. This quantity is compared directly with deuterium NMR.",
                 "−S_CD が大きいほど鎖は秩序立っています。流動相の平坦部（炭素 4〜10）はおよそ 0.12〜0.25 で、鎖末端に向かって下がります。"
                 "平坦部が 0.3 を超えると膜は秩序が高すぎ、ゲル相に近い可能性があります。0.12 未満は無秩序すぎます。重水素 NMR と直接比べられる量です。",
                 "−S_CD가 클수록 사슬이 질서 있습니다. 유동상에서 평탄 구간(탄소 4~10)은 약 0.12~0.25이며 사슬 끝으로 갈수록 낮아집니다. "
                 "평탄 구간이 0.3을 넘으면 막이 지나치게 질서 있어 겔상에 가까울 수 있고, 0.12 미만이면 지나치게 무질서합니다. 중수소 NMR과 직접 비교하는 양입니다."),
    },
    "insertion_depth": {
        "title": ("插入深度隨時間的變化", "Insertion depth over time", "挿入の深さの時間変化", "삽입 깊이의 시간 변화"),
        "caption": ("溶質相對所在那一葉磷原子平面的深度，正值是進入膜內。實線是重原子質心，虛線是最深的重原子。0 是磷平面，灰色帶是頭基區（磷平面上方 0.5 nm 到下方 0.3 nm）。",
                    "Depth of the solute relative to the phosphate plane of its leaflet. Positive is inside the membrane. The solid "
                    "line is the heavy-atom centroid and the dashed line the deepest heavy atom. Zero is the phosphate plane and "
                    "the grey band the head-group region (0.5 nm above to 0.3 nm below it).",
                    "溶質が接している葉のリン原子面からの深さで、正の値は膜の内側です。実線は重原子の重心、破線は最も深い重原子です。0 がリン原子面、灰色の帯が頭部基の領域（リン原子面の上 0.5 nm から下 0.3 nm）です。",
                    "용질이 놓인 층의 인 원자 평면으로부터의 깊이이며 양수는 막 안쪽입니다. 실선은 중원자 무게중심, 점선은 가장 깊은 중원자입니다. 0은 인 원자 평면이고 회색 띠는 머리 부분 영역(인 평면 위 0.5 nm부터 아래 0.3 nm)입니다."),
        "read": ("質心在磷平面上方超過 0.5 nm，溶質仍在水中。落在灰色帶，代表吸附在膜表面。磷平面下方 0.3 到 1.0 nm 是介面區，超過 1.0 nm 已進入疏水核心。"
                 "曲線在後半段仍在變化，代表吸附或插入還沒完成。穿過膜中心是罕見事件，一次不能當作速率。",
                 "A centroid more than 0.5 nm above the phosphate plane is still in the water. Inside the grey band the solute "
                 "is adsorbed on the surface. 0.3–1.0 nm below the plane is the interface, and beyond 1.0 nm it has entered "
                 "the hydrophobic core. A curve still changing in the second half means adsorption or insertion is not "
                 "finished. Crossing the membrane centre is a rare event, and one crossing is not a rate.",
                 "重心がリン原子面より 0.5 nm 以上上にあれば、溶質はまだ水中です。灰色の帯の中なら膜表面に吸着しています。リン原子面の下 0.3〜1.0 nm は界面領域で、1.0 nm を超えると疎水性コアに入っています。"
                 "後半になっても曲線が変化していれば、吸着や挿入はまだ終わっていません。膜中心の通過はまれな現象で、1 回だけでは速度とは言えません。",
                 "무게중심이 인 원자 평면보다 0.5 nm 넘게 위에 있으면 용질은 아직 물속에 있습니다. 회색 띠 안이면 막 표면에 흡착한 것입니다. 인 평면 아래 0.3~1.0 nm는 계면 영역이고 1.0 nm를 넘으면 소수성 중심부에 들어간 것입니다. "
                 "후반부에도 곡선이 변하면 흡착이나 삽입이 끝나지 않은 것입니다. 막 중심 통과는 드문 사건이며 한 번으로는 속도라고 할 수 없습니다."),
    },
    "headgroup_residence": {
        "title": ("與頭基接觸的殘基與停留比例", "Residues in contact with the head groups and their residence",
                  "頭部基と接触する残基と滞在の割合", "머리 부분과 접촉하는 잔기와 체류 비율"),
        "caption": ("每個殘基與脂質磷原子（或膽固醇 O3）距離 0.4 nm 以內的時間比例，依比例排序。",
                    "Fraction of time each residue spends within 0.4 nm of a lipid phosphorus (or cholesterol O3), sorted by fraction.",
                    "各残基が脂質のリン原子（またはコレステロールの O3）から 0.4 nm 以内にある時間の割合を、割合の高い順に並べています。",
                    "각 잔기가 지질의 인 원자(또는 콜레스테롤 O3)로부터 0.4 nm 이내에 있는 시간의 비율을 비율순으로 정렬했습니다."),
        "read": ("50 % 以上是持續接觸，是吸附的錨點，常見的是帶正電的離胺酸與精胺酸。20 % 到 50 % 是間歇接觸。最後一幀仍在接觸的事件，停留時間只能算下限。",
                 "Above 50 % is a persistent contact that anchors the adsorption, often positively charged lysine and arginine. "
                 "20–50 % is intermittent. For a contact still open at the last frame the residence time is only a lower bound.",
                 "50 % 以上は持続的な接触で吸着のアンカーです。正に帯電したリシンやアルギニンがよく見られます。20〜50 % は断続的な接触です。最後のフレームでも接触が続いている場合、滞在時間は下限値にすぎません。",
                 "50 % 이상은 지속적인 접촉으로 흡착의 앵커이며 양전하를 띤 라이신과 아르지닌이 흔합니다. 20~50 %는 간헐적 접촉입니다. 마지막 프레임에서도 접촉 중이면 체류 시간은 하한값일 뿐입니다."),
    },
    "peptide_tilt": {
        "title": ("胜肽傾角的分佈", "Distribution of the peptide tilt", "ペプチドの傾きの分布", "펩타이드 기울기 분포"),
        "caption": ("胜肽主軸（Cα 的主成分）與膜法線的夾角，前半段與後半段分開畫。90° 是平躺在膜面，0° 是沿法線直立。",
                    "Angle between the peptide's principal axis (principal component of the Cα atoms) and the membrane normal, "
                    "first and second halves drawn separately. 90° lies flat on the surface and 0° stands along the normal.",
                    "ペプチドの主軸（Cα の主成分）と膜法線のなす角で、前半と後半を分けて描いています。90° は膜面に寝た状態、0° は法線に沿って立った状態です。",
                    "펩타이드 주축(Cα의 주성분)과 막 법선 사이의 각도이며 전반부와 후반부를 따로 그렸습니다. 90°는 막 표면에 누운 상태, 0°는 법선을 따라 선 상태입니다."),
        "read": ("60° 以上是平躺，兩親性螺旋吸附在膜表面時常見。30° 到 60° 是斜插。30° 以下是沿法線直立，表面接觸的短胜肽很少這樣。標準差超過 20° 代表方向還沒穩定。"
                 "胜肽沒有固定的二級結構時，主軸只是大致的方向。",
                 "Above 60° the peptide lies flat, as amphipathic helices usually do on a membrane surface. 30–60° is oblique. "
                 "Below 30° it stands along the normal, which is rare for a short surface-bound peptide. A standard deviation "
                 "above 20° means the orientation has not settled. Without a fixed secondary structure the principal axis is only a rough direction.",
                 "60° 以上は寝た状態で、両親媒性ヘリックスが膜表面に吸着したときによく見られます。30〜60° は斜めに入った状態、30° 未満は法線に沿って立った状態で、表面に接触する短いペプチドではまれです。"
                 "標準偏差が 20° を超えるなら向きはまだ定まっていません。二次構造が決まっていないペプチドでは、主軸はおおよその方向にすぎません。",
                 "60° 이상은 누운 상태로, 양친매성 나선이 막 표면에 흡착할 때 흔합니다. 30~60°는 비스듬히 들어간 상태이고 30° 미만은 법선을 따라 선 상태로, 표면에 접촉하는 짧은 펩타이드에서는 드뭅니다. "
                 "표준편차가 20°를 넘으면 방향이 아직 안정되지 않은 것입니다. 이차 구조가 정해지지 않은 펩타이드에서는 주축이 대략적인 방향일 뿐입니다."),
    },
    "thickness_map": {
        "title": ("膜厚度的平面分佈", "Thickness map of the membrane plane", "膜厚の面内分布", "막 두께의 평면 분포"),
        "caption": ("把膜面切成格子，每格上下兩葉磷原子的平均距離，整段模擬平均。白色是沒有取樣的格子，× 是溶質的平均位置。",
                    "The membrane plane cut into a grid, with the mean distance between the phosphates of the two leaflets in each "
                    "cell, averaged over the run. White cells were not sampled and × marks the mean solute position.",
                    "膜面を格子に分け、各格子で上下 2 枚のリン原子の平均距離を求めて計算全体で平均しています。白はサンプルのない格子、× は溶質の平均位置です。",
                    "막 평면을 격자로 나누고 각 칸에서 위아래 두 층 인 원자의 평균 거리를 구해 전체 시뮬레이션에 걸쳐 평균했습니다. 흰색은 표본이 없는 칸, ×는 용질의 평균 위치입니다."),
        "read": ("均勻的膜各格相差不到 0.5 nm。溶質附近變薄，代表它擾動了膜。局部厚度低於平均的 80 % 是明顯變薄，可能是缺陷或孔洞的前兆。格子少、取樣短時，邊緣的格子雜訊大。",
                 "In a uniform membrane the cells differ by less than 0.5 nm. Thinning near the solute means it perturbs the "
                 "membrane. A local thickness below 80 % of the mean is marked thinning and may precede a defect or pore. With "
                 "few cells or short sampling, edge cells are noisy.",
                 "均一な膜では格子間の差は 0.5 nm 未満です。溶質の近くで薄くなっていれば、溶質が膜を乱しています。局所的な厚さが平均の 80 % を下回るのは明らかな薄化で、欠陥や孔の前ぶれかもしれません。"
                 "格子が少ない、またはサンプリングが短い場合、端の格子はノイズが大きくなります。",
                 "균일한 막에서는 칸 사이의 차이가 0.5 nm 미만입니다. 용질 근처에서 얇아지면 용질이 막을 교란한 것입니다. 국소 두께가 평균의 80 %보다 낮으면 뚜렷하게 얇아진 것이며 결함이나 구멍의 전조일 수 있습니다. "
                 "칸이 적거나 샘플링이 짧으면 가장자리 칸은 잡음이 큽니다."),
    },
    "longrun_plan": {
        "title": ("長時間模擬：規劃與實際", "Long simulation: plan and actual", "長時間シミュレーション：計画と実績", "장시간 시뮬레이션: 계획과 실제"),
        "caption": ("左：正式模擬的長度（ns），規劃與實際完成。右：硬碟用量（GB），規劃的軌跡、chunk 檔與合計，和實際的資料夾大小。",
                    "Left: production length (ns), planned and completed. Right: disk use (GB), the planned trajectory, chunk "
                    "files and total, against the actual size of the run folder.",
                    "左は本計算の長さ（ns）の計画値と完了した値、右はディスク使用量（GB）で、計画した軌跡、chunk ファイル、合計と実際のフォルダの大きさです。",
                    "왼쪽은 본 시뮬레이션 길이(ns)의 계획값과 완료값, 오른쪽은 디스크 사용량(GB)으로 계획한 궤적, chunk 파일, 합계와 실제 폴더 크기입니다."),
        "read": ("實際完成的長度達到規劃的 99 % 才算跑完。沒跑完時，後面的分析只代表已完成的部分。實際硬碟用量超過規劃的 125 %，代表規劃的估計偏低，下次要多留空間。"
                 "只存溶質時，水的分析（水橋、水的密度）無法做。",
                 "The run is complete only when at least 99 % of the planned length is done. Otherwise the analysis covers "
                 "only the completed part. Actual disk use above 125 % of the plan means the estimate was low, so leave more "
                 "space next time. When only the solute is saved, water analyses (water bridges, water density) are not possible.",
                 "完了した長さが計画の 99 % に達して初めて完走とみなします。達していなければ、解析は完了した部分だけを表します。実際のディスク使用量が計画の 125 % を超えたら見積もりが低かったので、次回は余裕を持たせてください。"
                 "溶質だけを保存した場合、水の解析（水架橋、水の密度）はできません。",
                 "완료한 길이가 계획의 99 %에 이르러야 끝까지 실행한 것입니다. 그렇지 않으면 분석은 완료된 부분만 나타냅니다. 실제 디스크 사용량이 계획의 125 %를 넘으면 추정이 낮았던 것이므로 다음에는 공간을 더 확보하십시오. "
                 "용질만 저장했다면 물 분석(물 다리, 물 밀도)은 할 수 없습니다."),
    },
    "convergence_rmsf": {
        "title": ("收斂：前半段與後半段的殘基柔性", "Convergence: residue flexibility in the first and second halves",
                  "収束：前半と後半の残基の柔軟性", "수렴: 전반부와 후반부의 잔기 유연성"),
        "caption": ("把正式模擬切成前後兩半，各自計算的 Cα RMSF。下方是後半減前半。",
                    "Cα RMSF computed separately for the first and second halves of production. The panel below is the second half minus the first.",
                    "本計算を前半と後半に分け、それぞれで計算した Cα RMSF です。下段は後半から前半を引いた差です。",
                    "본 시뮬레이션을 전반부와 후반부로 나누어 각각 계산한 Cα RMSF입니다. 아래쪽은 후반부에서 전반부를 뺀 차이입니다."),
        "read": ("兩半的柔性剖面相關係數 0.8 以上、平均差 0.3 Å 以內，代表動態已經收斂，延長模擬不會改變結論。後半段整體較高，代表還在取樣新的運動，例如 loop 開合。",
                 "A correlation of 0.8 or more between the two profiles with a mean difference within 0.3 Å means the dynamics "
                 "have converged and a longer run would not change the conclusion. A second half that is higher overall means "
                 "new motions, such as a loop opening, are still being sampled.",
                 "2 つの柔軟性プロファイルの相関係数が 0.8 以上で平均差が 0.3 Å 以内なら、動きは収束しており、計算を延ばしても結論は変わりません。後半が全体に高い場合は、ループの開閉のような新しい動きをまだサンプリングしています。",
                 "두 유연성 프로파일의 상관계수가 0.8 이상이고 평균 차이가 0.3 Å 이내이면 동역학이 수렴한 것이며 시뮬레이션을 늘려도 결론이 바뀌지 않습니다. 후반부가 전체적으로 높으면 루프 개폐 같은 새로운 움직임을 아직 샘플링하는 중입니다."),
    },
    "convergence_rmsd": {
        "title": ("收斂：前半段與後半段的 RMSD 分佈", "Convergence: RMSD distribution in the first and second halves",
                  "収束：前半と後半の RMSD 分布", "수렴: 전반부와 후반부의 RMSD 분포"),
        "caption": ("主鏈 RMSD 在前半段與後半段的直方圖（面積標準化）。", "Histograms of the backbone RMSD in the first and second halves (normalised to equal area).",
                    "主鎖 RMSD の前半と後半のヒストグラム（面積で規格化）です。", "주사슬 RMSD의 전반부와 후반부 히스토그램(면적으로 정규화)입니다."),
        "read": ("兩個分佈的重疊係數 0.6 以上，代表兩半取樣到同一組構形。0.3 到 0.6 是部分重疊，結構還在慢慢變化。0.3 以下代表後半段到了新的構形，前半段的平均不能代表整體。",
                 "An overlap coefficient of 0.6 or more means both halves sampled the same set of conformations. 0.3–0.6 is "
                 "partial overlap and the structure is still drifting slowly. Below 0.3 the second half reached new "
                 "conformations and an average over the whole run is not representative.",
                 "2 つの分布の重なり係数が 0.6 以上なら、前半と後半は同じ構造の集まりをサンプリングしています。0.3〜0.6 は部分的な重なりで、構造はまだゆっくり変化しています。0.3 未満なら後半は新しい構造に移っており、全体の平均は代表値になりません。",
                 "두 분포의 겹침 계수가 0.6 이상이면 두 절반이 같은 구조 집합을 샘플링한 것입니다. 0.3~0.6은 부분 겹침으로 구조가 아직 천천히 변하고 있습니다. 0.3 미만이면 후반부가 새로운 구조로 옮겨 간 것이므로 전체 평균은 대표값이 되지 못합니다."),
    },
    "cluster_timeline": {
        "title": ("構形叢集比例隨時間的變化", "Cluster populations over time", "構造クラスターの割合の時間変化", "구조 클러스터 비율의 시간 변화"),
        "caption": ("把模擬切成 10 段，每段中各構形叢集所占的比例（堆疊面積圖）。",
                    "The run cut into 10 windows, with the share of each conformational cluster in every window (stacked area).",
                    "計算を 10 区間に分け、各区間で各構造クラスターが占める割合を積み上げ面グラフで示しています。",
                    "시뮬레이션을 10구간으로 나누고 각 구간에서 구조 클러스터가 차지하는 비율을 누적 면적 그래프로 나타냈습니다."),
        "read": ("各叢集在前後兩半的比例相差 10 個百分點以內，代表構形的分佈穩定。後四分之一才出現、占 20 % 以上的新叢集，代表模擬還在探索新的狀態，還沒收斂。"
                 "叢集之間來回切換，代表狀態之間有轉換，這是長時間模擬才看得到的資訊。",
                 "Cluster shares within 10 percentage points between the two halves mean a stable distribution of "
                 "conformations. A new cluster that appears only in the last quarter with 20 % or more means the run is still "
                 "exploring new states and has not converged. Switching back and forth between clusters shows transitions "
                 "between states, information only a long run can give.",
                 "各クラスターの割合の差が前半と後半で 10 ポイント以内なら、構造の分布は安定しています。最後の 4 分の 1 で初めて現れ、20 % 以上を占める新しいクラスターがあれば、計算はまだ新しい状態を探しており収束していません。"
                 "クラスター間を行き来していれば状態間の遷移があり、これは長時間の計算でしか得られない情報です。",
                 "각 클러스터 비율이 전반부와 후반부에서 10 %p 이내로 차이 나면 구조 분포가 안정적입니다. 마지막 4분의 1에서야 나타나 20 % 이상을 차지하는 새 클러스터가 있으면 시뮬레이션이 아직 새로운 상태를 탐색 중이며 수렴하지 않은 것입니다. "
                 "클러스터 사이를 오가면 상태 간 전이가 있는 것이며, 이는 장시간 시뮬레이션에서만 얻을 수 있는 정보입니다."),
    },
    "cg_membrane": {
        "title": ("粗粒化膜的性質（Martini 3，珠子層級）", "Coarse-grained membrane properties (Martini 3, bead level)",
                  "粗視化膜の性質（Martini 3、ビーズ単位）", "조립화 막의 성질(Martini 3, 비드 단위)"),
        "caption": ("粗粒化模擬，不是全原子。左上：每個脂質的面積。左下：PO4 珠子平面之間的厚度，灰色帶是實驗參考值 ±6 % 與 ±0.3 nm。右：每個鍵的序參數 P2。",
                    "Coarse-grained simulation, not atomistic. Top left: area per lipid. Bottom left: thickness between the PO4 "
                    "bead planes, with grey bands at the experimental reference ±6 % and ±0.3 nm. Right: order parameter P2 of each bond.",
                    "粗視化シミュレーションで、全原子ではありません。左上は脂質あたりの面積、左下は PO4 ビーズ面の間の厚さで、灰色の帯は実験参照値の ±6 % と ±0.3 nm です。右は各結合の秩序パラメータ P2 です。",
                    "조립화 시뮬레이션이며 전원자가 아닙니다. 왼쪽 위는 지질당 면적, 왼쪽 아래는 PO4 비드 평면 사이의 두께이고 회색 띠는 실험 참고값 ±6 %와 ±0.3 nm입니다. 오른쪽은 각 결합의 질서 매개변수 P2입니다."),
        "read": ("每顆珠子約代表 4 個重原子，所以沒有氫鍵與原子細節，序參數是鍵的 P2，不能和氘 NMR 的 S_CD 直接比較。面積與厚度可以和實驗比。"
                 "P2 平均在 0.1 到 0.6 之間是流體相。高於 0.6 偏凝膠，低於 0.1 過於無序。粗粒化的動態比真實快，模擬時間不能直接當真實時間。",
                 "Each bead stands for about 4 heavy atoms, so there are no hydrogen bonds or atomic detail, and the order "
                 "parameter is the bond P2, which cannot be compared directly with the deuterium S_CD. Area and thickness can be "
                 "compared with experiment. A mean P2 of 0.1–0.6 is the fluid phase. Above 0.6 tends towards gel and below 0.1 "
                 "is over-disordered. Coarse-grained dynamics run faster than real ones, so simulated time is not real time.",
                 "ビーズ 1 個はおよそ 4 個の重原子にあたるため、水素結合や原子の細部はありません。秩序パラメータは結合の P2 で、重水素 NMR の S_CD とは直接比べられません。面積と厚さは実験と比べられます。"
                 "P2 の平均が 0.1〜0.6 なら流動相、0.6 を超えるとゲル寄り、0.1 未満は無秩序すぎます。粗視化の動きは実際より速いため、シミュレーション時間をそのまま実時間とみなせません。",
                 "비드 하나가 중원자 약 4개를 나타내므로 수소 결합과 원자 수준의 세부가 없고, 질서 매개변수는 결합의 P2로 중수소 NMR의 S_CD와 직접 비교할 수 없습니다. 면적과 두께는 실험과 비교할 수 있습니다. "
                 "P2 평균이 0.1~0.6이면 유동상이고 0.6을 넘으면 겔 쪽, 0.1 미만이면 지나치게 무질서합니다. 조립화 동역학은 실제보다 빠르므로 시뮬레이션 시간을 그대로 실제 시간으로 볼 수 없습니다."),
    },
})


def _jz(items, n: int = 8) -> tuple[str, str]:
    """A short list in Chinese/Japanese and in English/Korean separators."""
    items = [str(x) for x in items][:n]
    return "、".join(items), ", ".join(items)


def _halfmean(y) -> float:
    y = np.asarray(y, float)
    return float(y[len(y) // 2:].mean())


# --------------------------------------------------------------------------------------------- fold
PLDDT_GOOD, PLDDT_LOW, IPTM_MIN = 70.0, 50.0, 0.5


def classify_fold_plddt(name: str, rec: dict) -> list[dict]:
    pl = [float(x) for x in rec.get("per_residue_plddt") or []]
    m = rec.get("mean_plddt")
    if m is None and pl:
        m = float(np.mean(pl))
    if m is None:
        return []
    out = []
    eng = rec.get("engine") or "—"
    if m >= PLDDT_GOOD:
        out.append(S("good",
                     f"{name}：胜肽平均 pLDDT {m:.1f}（≥ 70，{eng}），預測的主鏈可信，可以當起始構形。這仍是預測，不是實驗結構。",
                     f"{name}: mean peptide pLDDT {m:.1f} (≥ 70, {eng}), so the predicted backbone is confident and usable as the "
                     "starting structure. It is still a prediction, not an experimental structure.",
                     f"{name}：ペプチドの平均 pLDDT は {m:.1f}（≥ 70、{eng}）で、予測した主鎖は信頼でき、初期構造として使えます。それでも予測であり、実験構造ではありません。",
                     f"{name}: 펩타이드 평균 pLDDT {m:.1f}(≥ 70, {eng})로 예측한 주사슬을 믿을 수 있어 시작 구조로 쓸 수 있습니다. 그래도 예측이며 실험 구조가 아닙니다."))
    elif m >= PLDDT_LOW:
        out.append(S("note",
                     f"{name}：胜肽平均 pLDDT {m:.1f}（50 到 70，{eng}），可信度偏低。MD 要確認這個構形站得住，主鏈 RMSD 若很快超過 3 Å，代表預測的構形不穩定。",
                     f"{name}: mean peptide pLDDT {m:.1f} (50–70, {eng}), low confidence. MD has to show that this conformation "
                     "holds. A backbone RMSD quickly above 3 Å means the predicted conformation is unstable.",
                     f"{name}：ペプチドの平均 pLDDT は {m:.1f}（50〜70、{eng}）で、信頼度は低めです。この構造が保たれるかを MD で確かめる必要があり、主鎖 RMSD がすぐ 3 Å を超えるなら予測構造は不安定です。",
                     f"{name}: 펩타이드 평균 pLDDT {m:.1f}(50~70, {eng})로 신뢰도가 낮습니다. 이 구조가 유지되는지 MD로 확인해야 하며 주사슬 RMSD가 곧 3 Å을 넘으면 예측 구조가 불안정한 것입니다."))
    else:
        out.append(S("caution",
                     f"{name}：胜肽平均 pLDDT {m:.1f}（< 50，{eng}），預測不可信，胜肽在溶液中可能沒有固定結構。以這個構形得到的結果只能當定性參考。",
                     f"{name}: mean peptide pLDDT {m:.1f} (< 50, {eng}). The prediction is not reliable and the peptide may have no "
                     "fixed structure in solution. Results from this conformation are qualitative only.",
                     f"{name}：ペプチドの平均 pLDDT は {m:.1f}（< 50、{eng}）で、予測は信頼できません。ペプチドは溶液中で決まった構造を持たない可能性があり、この構造から得た結果は定性的な参考にとどまります。",
                     f"{name}: 펩타이드 평균 pLDDT {m:.1f}(< 50, {eng})로 예측을 믿을 수 없습니다. 펩타이드가 용액에서 고정된 구조가 없을 수 있으므로 이 구조로 얻은 결과는 정성적 참고로만 쓰십시오."))
    low = [i + 1 for i, v in enumerate(pl) if v < PLDDT_LOW]
    if low and m >= PLDDT_LOW:
        z, e = _jz(low, 12)
        out.append(S("note",
                     f"{name}：第 {z} 個殘基的 pLDDT 低於 50，通常是末端或柔軟的 loop，不要解讀這些位置的構形。",
                     f"{name}: residues {e} are below pLDDT 50, usually termini or flexible loops. Do not interpret their conformation.",
                     f"{name}：{z} 番目の残基は pLDDT が 50 未満で、たいてい末端か柔らかいループです。これらの位置の構造は解釈しないでください。",
                     f"{name}: {e}번째 잔기는 pLDDT가 50 미만으로 대개 말단이나 유연한 루프입니다. 이 위치의 구조는 해석하지 마십시오."))
    ip = rec.get("iptm")
    if ip is not None:
        ip = float(ip)
        out.append(S("note", f"{name}：介面的 ipTM {ip:.2f}（≥ 0.5），預測的結合介面可以參考，仍要以 MD 確認。",
                     f"{name}: interface ipTM {ip:.2f} (≥ 0.5). The predicted interface is a reasonable hypothesis, still to be confirmed by MD.",
                     f"{name}：界面の ipTM は {ip:.2f}（≥ 0.5）で、予測された結合界面は参考になりますが、MD で確認が必要です。",
                     f"{name}: 계면 ipTM {ip:.2f}(≥ 0.5)로 예측한 결합 계면을 참고할 수 있지만 MD로 확인해야 합니다.")
                   if ip >= IPTM_MIN else
                   S("caution", f"{name}：介面的 ipTM {ip:.2f}（< 0.5），預測的結合介面不可信，胜肽的結合位置可能是錯的。",
                     f"{name}: interface ipTM {ip:.2f} (< 0.5). The predicted interface is not reliable and the peptide may sit in the wrong place.",
                     f"{name}：界面の ipTM は {ip:.2f}（< 0.5）で、予測された結合界面は信頼できず、ペプチドの結合位置が誤っている可能性があります。",
                     f"{name}: 계면 ipTM {ip:.2f}(< 0.5)로 예측한 결합 계면을 믿을 수 없으며 펩타이드의 결합 위치가 틀렸을 수 있습니다."))
    by = rec.get("plddt_by_chain") or {}
    pc = rec.get("peptide_chain")
    for c, v in by.items():
        if c == pc or not v:
            continue
        cm = float(np.mean(v))
        if cm < PLDDT_GOOD:
            out.append(S("caution",
                         f"{name}：預測的受體鏈 {c} 平均 pLDDT {cm:.1f}（< 70），受體本身的預測不可靠，放置胜肽時應以實際受體為準。",
                         f"{name}: predicted receptor chain {c} has a mean pLDDT of {cm:.1f} (< 70). The receptor prediction itself "
                         "is unreliable, so rely on the actual receptor when placing the peptide.",
                         f"{name}：予測した受容体の鎖 {c} は平均 pLDDT {cm:.1f}（< 70）で、受容体自体の予測が信頼できません。ペプチドを置くときは実際の受容体を基準にしてください。",
                         f"{name}: 예측한 수용체 사슬 {c}의 평균 pLDDT가 {cm:.1f}(< 70)로 수용체 예측 자체를 믿기 어렵습니다. 펩타이드를 놓을 때는 실제 수용체를 기준으로 하십시오."))
    return out


def classify_fold_superposition(name: str, dev, labels, rmsd=None, pocket_rmsd=None, pocket_mask=None, max_rmsd: float = 2.0) -> list[dict]:
    d = np.asarray(dev, float)
    if not len(d):
        return []
    r = float(rmsd) if rmsd is not None else float(np.sqrt((d ** 2).mean()))
    out = [S("good",
             f"{name}：{len(d)} 個配對的 Cα 疊合後 RMSD {r:.2f} Å（≤ {max_rmsd:g} Å），預測的受體和實際受體一致，胜肽的位置可以搬過來。",
             f"{name}: {len(d)} matched Cα superpose at {r:.2f} Å RMSD (≤ {max_rmsd:g} Å). The predicted receptor agrees with the "
             "actual one, so the peptide's position can be transferred.",
             f"{name}：対応づけた Cα {len(d)} 個の重ね合わせ RMSD は {r:.2f} Å（≤ {max_rmsd:g} Å）で、予測した受容体は実際の受容体と一致しています。ペプチドの位置を移せます。",
             f"{name}: 짝지은 Cα {len(d)}개를 겹친 RMSD가 {r:.2f} Å(≤ {max_rmsd:g} Å)로 예측한 수용체가 실제 수용체와 일치합니다. 펩타이드 위치를 옮길 수 있습니다.")
           if r <= max_rmsd else
           S("caution",
             f"{name}：{len(d)} 個配對的 Cα 疊合後 RMSD {r:.2f} Å（> {max_rmsd:g} Å），預測的受體和實際受體不一致，搬過來的胜肽姿勢可能不在正確的位置。",
             f"{name}: {len(d)} matched Cα superpose at {r:.2f} Å RMSD (> {max_rmsd:g} Å). The predicted receptor differs from the "
             "actual one, so the transferred peptide pose may be misplaced.",
             f"{name}：対応づけた Cα {len(d)} 個の重ね合わせ RMSD は {r:.2f} Å（> {max_rmsd:g} Å）で、予測した受容体は実際の受容体と一致しません。移したペプチドのポーズは正しい位置にない可能性があります。",
             f"{name}: 짝지은 Cα {len(d)}개를 겹친 RMSD가 {r:.2f} Å(> {max_rmsd:g} Å)로 예측한 수용체가 실제 수용체와 다릅니다. 옮긴 펩타이드 포즈가 잘못된 위치에 있을 수 있습니다.")]
    pm = None if pocket_mask is None else np.asarray(pocket_mask, bool)
    if pocket_rmsd is None and pm is not None and pm.sum() >= 3:
        pocket_rmsd = float(np.sqrt((d[pm] ** 2).mean()))
    if pocket_rmsd is not None:
        p = float(pocket_rmsd)
        out.append(S("good" if p <= max_rmsd else "caution",
                     f"{name}：胜肽 10 Å 內結合位殘基的 Cα RMSD {p:.2f} Å（{'≤' if p <= max_rmsd else '>'} {max_rmsd:g} Å），"
                     + ("結合位的形狀和實際結構相同。" if p <= max_rmsd else "結合位的形狀不同，胜肽姿勢是在另一種口袋形狀下預測的。"),
                     f"{name}: binding-site Cα within 10 Å of the peptide deviate by {p:.2f} Å RMSD ({'≤' if p <= max_rmsd else '>'} {max_rmsd:g} Å). "
                     + ("The site has the same shape as in the actual structure." if p <= max_rmsd else
                        "The site has a different shape, so the peptide pose was predicted for another pocket shape."),
                     f"{name}：ペプチドから 10 Å 以内の結合部位残基の Cα RMSD は {p:.2f} Å（{'≤' if p <= max_rmsd else '>'} {max_rmsd:g} Å）です。"
                     + ("結合部位の形は実際の構造と同じです。" if p <= max_rmsd else "結合部位の形が異なり、ペプチドのポーズは別のポケットの形で予測されています。"),
                     f"{name}: 펩타이드 10 Å 이내 결합 부위 잔기의 Cα RMSD는 {p:.2f} Å({'≤' if p <= max_rmsd else '>'} {max_rmsd:g} Å)입니다. "
                     + ("결합 부위 모양이 실제 구조와 같습니다." if p <= max_rmsd else "결합 부위 모양이 달라 펩타이드 포즈가 다른 포켓 모양에서 예측된 것입니다.")))
    labels = list(labels) if labels is not None and len(labels) == len(d) else [f"#{i + 1}" for i in range(len(d))]
    big = [str(labels[i]) for i in np.argsort(-d) if d[i] > 3.0][:8]
    if big:
        z, e = _jz(big)
        inpk = pm is not None and any(pm[i] for i in range(len(d)) if d[i] > 3.0)
        out.append(S("caution" if inpk else "note",
                     f"{name}：偏差超過 3 Å 的殘基有 {z}" + ("，其中有結合位殘基，結合位附近的預測要保守看待。" if inpk else "，都不在結合位，對胜肽姿勢影響不大。"),
                     f"{name}: residues deviating by more than 3 Å are {e}" + (". Some line the binding site, so read the prediction near the site with caution."
                                                                          if inpk else ". None lines the binding site, so they matter little for the peptide pose."),
                     f"{name}：ずれが 3 Å を超える残基は {z} です" + ("。結合部位の残基を含むため、結合部位付近の予測は慎重に扱ってください。" if inpk else "。どれも結合部位にはなく、ペプチドのポーズへの影響は小さいです。"),
                     f"{name}: 편차가 3 Å을 넘는 잔기는 {e}입니다" + (". 결합 부위 잔기가 포함되어 있으므로 결합 부위 근처 예측은 신중하게 보십시오." if inpk else ". 모두 결합 부위 밖이므로 펩타이드 포즈에는 영향이 작습니다.")))
    return out


def classify_fold_contacts(name: str, rows: list, cols: list, M) -> list[dict]:
    D = np.asarray(M, float)
    if D.size == 0:
        return []
    c = D <= 4.0
    k, n = int(c.any(1).sum()), len(rows)
    f = k / max(1, n)
    if f >= 0.5:
        out = [S("good", f"{name}：{n} 個胜肽殘基中有 {k} 個（{f:.0%}，≥ 50 %）與受體接觸，介面完整。",
                 f"{name}: {k} of {n} peptide residues ({f:.0%}, ≥ 50 %) touch the receptor, a complete interface.",
                 f"{name}：ペプチド残基 {n} 個のうち {k} 個（{f:.0%}、≥ 50 %）が受容体と接触しており、界面は十分です。",
                 f"{name}: 펩타이드 잔기 {n}개 중 {k}개({f:.0%}, ≥ 50 %)가 수용체와 접촉하여 계면이 온전합니다.")]
    elif f >= 0.25:
        out = [S("note", f"{name}：{n} 個胜肽殘基中有 {k} 個（{f:.0%}，25 % 到 50 %）與受體接觸，其餘伸在溶劑中。",
                 f"{name}: {k} of {n} peptide residues ({f:.0%}, 25–50 %) touch the receptor and the rest extend into solvent.",
                 f"{name}：ペプチド残基 {n} 個のうち {k} 個（{f:.0%}、25〜50 %）が受容体と接触し、残りは溶媒中に出ています。",
                 f"{name}: 펩타이드 잔기 {n}개 중 {k}개({f:.0%}, 25~50 %)가 수용체와 접촉하고 나머지는 용매 쪽으로 뻗어 있습니다.")]
    else:
        out = [S("caution", f"{name}：只有 {k} 個胜肽殘基（{f:.0%}，< 25 %）與受體接觸，預測的介面很弱，胜肽可能只是貼在表面。",
                 f"{name}: only {k} peptide residues ({f:.0%}, < 25 %) touch the receptor. The predicted interface is weak and "
                 "the peptide may only lie on the surface.",
                 f"{name}：受容体と接触するペプチド残基は {k} 個（{f:.0%}、< 25 %）だけです。予測された界面は弱く、ペプチドは表面に貼り付いているだけかもしれません。",
                 f"{name}: 수용체와 접촉하는 펩타이드 잔기가 {k}개({f:.0%}, < 25 %)뿐입니다. 예측된 계면이 약하며 펩타이드가 표면에 붙어 있기만 할 수 있습니다.")]
    hot = [str(cols[j]) for j in np.argsort(-c.sum(0)) if c[:, j].sum() >= 3][:6]
    if hot:
        z, e = _jz(hot)
        out.append(S("note", f"{name}：{z} 同時接觸 3 個以上胜肽殘基，可能是介面的熱點，可優先做突變或比對實驗資料。",
                     f"{name}: {e} each touch 3 or more peptide residues and may be interface hot spots, good first candidates for mutation or comparison with experiment.",
                     f"{name}：{z} はそれぞれ 3 個以上のペプチド残基と接触しており、界面のホットスポットの可能性があります。変異実験や実験データとの比較の候補になります。",
                     f"{name}: {e} 잔기는 각각 펩타이드 잔기 3개 이상과 접촉하므로 계면 핫스팟일 수 있습니다. 돌연변이 실험이나 실험 자료와 비교할 우선 후보입니다."))
    mn = float(np.nanmin(D))
    if mn < 1.5:
        out.append(S("caution", f"{name}：最短距離 {mn:.2f} Å（< 1.5 Å），有原子重疊，必須靠能量最小化解開，最小化後要確認胜肽沒有被推離。",
                     f"{name}: the shortest distance is {mn:.2f} Å (< 1.5 Å). Atoms overlap and energy minimisation must resolve "
                     "them. Check after minimisation that the peptide was not pushed away.",
                     f"{name}：最短距離は {mn:.2f} Å（< 1.5 Å）で原子が重なっています。エネルギー最小化で解消する必要があり、最小化の後にペプチドが押し出されていないか確認してください。",
                     f"{name}: 최단 거리가 {mn:.2f} Å(< 1.5 Å)로 원자가 겹칩니다. 에너지 최소화로 풀어야 하며 최소화 후 펩타이드가 밀려나지 않았는지 확인하십시오."))
    return out


# --------------------------------------------------------------------------------------------- membrane
APL_TOL, DPP_TOL_NM = 0.06, 0.30


def _band(key: str, what: tuple, unit: str, m: float, ref, lo: float, hi: float, nd: int) -> dict:
    ok = lo <= m <= hi
    v, a, b, rf = f"{m:.{nd}f}", f"{lo:.{nd}f}", f"{hi:.{nd}f}", f"{ref:.{nd}f}"
    if ok:
        return S("good", f"{key}：{what[0]}後半段平均 {v} {unit}，在參考值 {rf} 的容許範圍 {a} 到 {b} 內。",
                 f"{key}: {what[1]} averages {v} {unit} in the second half, inside the range {a}–{b} around the reference {rf}.",
                 f"{key}：{what[2]}の後半の平均は {v} {unit} で、参照値 {rf} の許容範囲 {a}〜{b} に入っています。",
                 f"{key}: {what[3]} 후반부 평균은 {v} {unit}로 참고값 {rf}의 허용 범위 {a}~{b} 안에 있습니다.")
    return S("caution", f"{key}：{what[0]}後半段平均 {v} {unit}，超出參考值 {rf} 的容許範圍 {a} 到 {b}。請檢查溫度、脂質組成與力場，或延長平衡。",
             f"{key}: {what[1]} averages {v} {unit} in the second half, outside the range {a}–{b} around the reference {rf}. "
             "Check temperature, lipid composition and force field, or extend equilibration.",
             f"{key}：{what[2]}の後半の平均は {v} {unit} で、参照値 {rf} の許容範囲 {a}〜{b} から外れています。温度、脂質組成、力場を確認するか、平衡化を延ばしてください。",
             f"{key}: {what[3]} 후반부 평균은 {v} {unit}로 참고값 {rf}의 허용 범위 {a}~{b}를 벗어났습니다. 온도, 지질 조성, 역장을 확인하거나 평형화를 늘리십시오.")


_APL = ("每個脂質的面積", "the area per lipid", "脂質あたりの面積", "지질당 면적")
_DPP = ("P–P 厚度", "the P–P thickness", "P–P 厚さ", "P–P 두께")


def classify_membrane_equil(key: str, t, apl, dpp, ref: dict | None, approximate: bool = False) -> list[dict]:
    apl, dpp = np.asarray(apl, float), np.asarray(dpp, float)
    if len(apl) < 4:
        return []
    ref = ref or {}
    out = []
    ma, md_ = _halfmean(apl), _halfmean(dpp)
    if approximate:
        out.append(S("note", f"{key}：膜中有蛋白，面積包含蛋白截面（後半段 {ma:.3f} nm²），不和參考值比較，只看是否進入平台。",
                     f"{key}: the membrane holds a protein, so the area includes its cross-section ({ma:.3f} nm² in the second half). "
                     "It is not compared with the reference; only the plateau is checked.",
                     f"{key}：膜にタンパク質が入っているため、面積にはその断面が含まれます（後半 {ma:.3f} nm²）。参照値とは比べず、平坦になったかだけを見ます。",
                     f"{key}: 막에 단백질이 있어 면적에 단백질 단면이 포함됩니다(후반부 {ma:.3f} nm²). 참고값과 비교하지 않고 평탄해졌는지만 봅니다."))
    elif ref.get("apl_nm2"):
        r = float(ref["apl_nm2"])
        out.append(_band(key, _APL, "nm²", ma, r, r * (1 - APL_TOL), r * (1 + APL_TOL), 3))
    if ref.get("dpp_nm"):
        r = float(ref["dpp_nm"])
        out.append(_band(key, _DPP, "nm", md_, r, r - DPP_TOL_NM, r + DPP_TOL_NM, 2))
    if not ref.get("apl_nm2") and not ref.get("dpp_nm"):
        out.append(S("note", f"{key}：這個脂質組成沒有實驗參考值（例如含膽固醇或心磷脂），面積 {ma:.3f} nm² 與厚度 {md_:.2f} nm 沒有和實驗比較。",
                     f"{key}: there is no experimental reference for this composition (for example with cholesterol or cardiolipin), "
                     f"so the area {ma:.3f} nm² and thickness {md_:.2f} nm are not compared with experiment.",
                     f"{key}：この脂質組成には実験の参照値がありません（コレステロールやカルジオリピンを含む場合など）。面積 {ma:.3f} nm² と厚さ {md_:.2f} nm は実験と比べていません。",
                     f"{key}: 이 지질 조성에는 실험 참고값이 없습니다(콜레스테롤이나 카디오리핀을 포함한 경우 등). 면적 {ma:.3f} nm²와 두께 {md_:.2f} nm는 실험과 비교하지 않았습니다."))
    h = apl[len(apl) // 2:]
    th = np.asarray(t, float)[len(apl) // 2:len(apl)] if len(t) >= len(apl) else np.arange(len(h), dtype=float)
    if len(h) > 2 and th[-1] > th[0]:
        drift = float(np.polyfit(th, h, 1)[0] * (th[-1] - th[0])) / max(1e-9, abs(ma))
        if abs(drift) > 0.02:
            out.append(S("caution", f"{key}：後半段面積仍改變 {drift:+.1%}（超過 ±2 %），膜還沒平衡，請延長平衡後再分析。",
                         f"{key}: the area still changes by {drift:+.1%} over the second half (more than ±2 %). The membrane has not "
                         "equilibrated, so extend equilibration before analysing.",
                         f"{key}：後半でも面積が {drift:+.1%} 変化しています（±2 % 超）。膜はまだ平衡に達していないため、平衡化を延ばしてから解析してください。",
                         f"{key}: 후반부에도 면적이 {drift:+.1%} 변합니다(±2 % 초과). 막이 아직 평형에 도달하지 않았으므로 평형화를 늘린 뒤 분석하십시오."))
    return out


def _is(name: str, *keys) -> bool:
    n = name.lower()
    return any(k in n for k in keys)


def classify_density(key: str, dens: dict) -> list[dict]:
    z = np.asarray(dens.get("z_nm") if dens.get("z_nm") is not None else [], float)
    g = {k: np.asarray(v, float) for k, v in (dens.get("groups") or {}).items()}
    if len(z) < 5 or not g:
        return []
    out = []
    phos = next((v for k, v in g.items() if _is(k, "phosph", "po4", "磷") or k.strip().upper() == "P"), None)
    zp = None
    if phos is not None and phos.max() > 0:
        up, lo = z > 0, z < 0
        if up.any() and lo.any():
            pu, pl = float(z[up][np.argmax(phos[up])]), float(z[lo][np.argmax(phos[lo])])
            zp = 0.5 * (pu - pl)
            out.append(S("note", f"{key}：兩個磷峰位於 z = {pl:+.2f} 與 {pu:+.2f} nm，峰距 {pu - pl:.2f} nm，就是這段模擬的膜厚。",
                         f"{key}: the two phosphate peaks sit at z = {pl:+.2f} and {pu:+.2f} nm, {pu - pl:.2f} nm apart, which is the thickness in this run.",
                         f"{key}：リンの 2 つのピークは z = {pl:+.2f} と {pu:+.2f} nm にあり、間隔 {pu - pl:.2f} nm がこの計算での膜厚です。",
                         f"{key}: 인의 두 피크는 z = {pl:+.2f}와 {pu:+.2f} nm에 있으며 간격 {pu - pl:.2f} nm가 이 시뮬레이션의 막 두께입니다."))
    water = next((v for k, v in g.items() if _is(k, "water", "水") or k.strip().upper() == "W"), None)
    if water is not None and water.max() > 0:
        bulk = float(water[np.abs(z) >= np.abs(z).max() - 1.0].mean()) or float(water.max())
        core = float(water[np.abs(z) < 0.5].mean()) if (np.abs(z) < 0.5).any() else 0.0
        fr = core / max(bulk, 1e-12)
        out.append(S("good", f"{key}：膜中心（|z| < 0.5 nm）的水密度只有水相的 {fr:.1%}（< 1 %），疏水核心是乾的，沒有孔洞。",
                     f"{key}: water at the centre (|z| < 0.5 nm) is {fr:.1%} of bulk (< 1 %). The hydrophobic core is dry and there is no pore.",
                     f"{key}：膜中心（|z| < 0.5 nm）の水密度はバルクの {fr:.1%}（< 1 %）しかなく、疎水性コアは乾いており孔はありません。",
                     f"{key}: 막 중심(|z| < 0.5 nm)의 물 밀도가 벌크의 {fr:.1%}(< 1 %)에 불과해 소수성 중심부가 건조하고 구멍이 없습니다.")
                   if fr < 0.01 else
                   S("caution", f"{key}：膜中心（|z| < 0.5 nm）的水密度是水相的 {fr:.1%}（≥ 1 %），水進入疏水核心，可能有孔洞或缺陷。請看厚度圖找變薄的位置。",
                     f"{key}: water at the centre (|z| < 0.5 nm) is {fr:.1%} of bulk (≥ 1 %). Water has entered the hydrophobic core, "
                     "so there may be a pore or defect. Look at the thickness map for thinning.",
                     f"{key}：膜中心（|z| < 0.5 nm）の水密度はバルクの {fr:.1%}（≥ 1 %）で、水が疎水性コアに入っています。孔や欠陥の可能性があるため、膜厚マップで薄い場所を確認してください。",
                     f"{key}: 막 중심(|z| < 0.5 nm)의 물 밀도가 벌크의 {fr:.1%}(≥ 1 %)로 물이 소수성 중심부에 들어왔습니다. 구멍이나 결함이 있을 수 있으므로 두께 지도에서 얇아진 곳을 확인하십시오."))
    for k, v in g.items():
        if not _is(k, "peptide", "ligand", "solute", "胜肽", "配體") or v.sum() <= 0 or zp is None:
            continue
        mz = float((np.abs(z) * v).sum() / v.sum())
        if mz > zp + 0.5:
            t = ("在磷峰外側超過 0.5 nm，主要在水中", "more than 0.5 nm outside the phosphate peak, mostly in the water",
                 "リンのピークより 0.5 nm 以上外側で、主に水中", "인 피크보다 0.5 nm 넘게 바깥쪽으로 주로 물속")
        elif mz >= zp - 0.5:
            t = ("在磷峰 ±0.5 nm 內，吸附在頭基區", "within ±0.5 nm of the phosphate peak, adsorbed at the head groups",
                 "リンのピークから ±0.5 nm 以内で、頭部基の領域に吸着", "인 피크 ±0.5 nm 이내로 머리 부분 영역에 흡착")
        else:
            t = ("在磷峰內側超過 0.5 nm，已插入膜中", "more than 0.5 nm inside the phosphate peak, inserted into the membrane",
                 "リンのピークより 0.5 nm 以上内側で、膜に挿入", "인 피크보다 0.5 nm 넘게 안쪽으로 막에 삽입")
        out.append(S("note", f"{key}：{k} 的平均 |z| 為 {mz:.2f} nm（磷峰 {zp:.2f} nm），{t[0]}。",
                     f"{key}: {k} has a mean |z| of {mz:.2f} nm (phosphate peak {zp:.2f} nm), {t[1]}.",
                     f"{key}：{k} の平均 |z| は {mz:.2f} nm（リンのピーク {zp:.2f} nm）で、{t[2]}しています。",
                     f"{key}: {k} 그룹의 평균 |z|는 {mz:.2f} nm(인 피크 {zp:.2f} nm)로 {t[3]}되어 있습니다."))
    return out


def scd_series(scd: dict) -> dict:
    """{"sn1:C32": S} → {"sn1": ([2, 3, ...], [−S ...]), "sn2": ...} sorted by carbon number."""
    out: dict = {}
    for k, v in (scd or {}).items():
        try:
            tail, atom = k.split(":", 1)
            n = int("".join(ch for ch in atom[2:] if ch.isdigit()))
        except ValueError:
            continue
        out.setdefault(tail, []).append((n, -float(v)))
    return {t: ([a for a, _ in sorted(v)], [b for _, b in sorted(v)]) for t, v in sorted(out.items())}


def classify_scd(key: str, scd: dict) -> list[dict]:
    ser = scd_series(scd)
    if not ser:
        return []
    out = []
    for tail, (n, s) in ser.items():
        p = [y for x, y in zip(n, s) if 4 <= x <= 10]
        if not p:
            continue
        m = float(np.mean(p))
        if 0.12 <= m <= 0.25:
            out.append(S("good", f"{key}：{tail} 鏈的平台（碳 4 到 10）−S_CD = {m:.2f}，在流體相的 0.12 到 0.25 之間。",
                         f"{key}: the {tail} plateau (carbons 4–10) has −S_CD = {m:.2f}, within the fluid-phase range 0.12–0.25.",
                         f"{key}：{tail} 鎖の平坦部（炭素 4〜10）の −S_CD は {m:.2f} で、流動相の 0.12〜0.25 に入っています。",
                         f"{key}: {tail} 사슬 평탄 구간(탄소 4~10)의 −S_CD는 {m:.2f}로 유동상 범위 0.12~0.25 안에 있습니다."))
        elif 0.25 < m <= 0.3:
            out.append(S("note", f"{key}：{tail} 鏈的平台 −S_CD = {m:.2f}（0.25 到 0.3），比一般流體相有序，膽固醇或飽和鏈會造成這種情形。",
                         f"{key}: the {tail} plateau has −S_CD = {m:.2f} (0.25–0.3), more ordered than a typical fluid phase, as cholesterol or saturated chains cause.",
                         f"{key}：{tail} 鎖の平坦部の −S_CD は {m:.2f}（0.25〜0.3）で、一般的な流動相より秩序立っています。コレステロールや飽和鎖でこうなります。",
                         f"{key}: {tail} 사슬 평탄 구간의 −S_CD는 {m:.2f}(0.25~0.3)로 일반 유동상보다 질서 있습니다. 콜레스테롤이나 포화 사슬이 있으면 이렇게 됩니다."))
        else:
            hi = m > 0.3
            out.append(S("caution",
                         f"{key}：{tail} 鏈的平台 −S_CD = {m:.2f}（{'> 0.3，過於有序，可能接近凝膠相' if hi else '< 0.12，過於無序'}）。請檢查模擬溫度與脂質的相轉變溫度。",
                         f"{key}: the {tail} plateau has −S_CD = {m:.2f} ({'> 0.3, over-ordered and possibly near the gel phase' if hi else '< 0.12, over-disordered'}). "
                         "Check the simulation temperature against the lipid's transition temperature.",
                         f"{key}：{tail} 鎖の平坦部の −S_CD は {m:.2f}（{'> 0.3、秩序が高すぎゲル相に近い可能性' if hi else '< 0.12、無秩序すぎる'}）です。シミュレーション温度と脂質の相転移温度を確認してください。",
                         f"{key}: {tail} 사슬 평탄 구간의 −S_CD는 {m:.2f}({'> 0.3, 지나치게 질서 있어 겔상에 가까울 수 있음' if hi else '< 0.12, 지나치게 무질서함'})입니다. 시뮬레이션 온도와 지질의 상전이 온도를 확인하십시오."))
    return out


def classify_insertion(key: str, t, com, deepest=None, crossed: bool = False) -> list[dict]:
    c = np.asarray(com, float)
    if len(c) < 4:
        return []
    d = _halfmean(c)
    dd = _halfmean(deepest) if deepest is not None and len(deepest) else None
    tail = (f"，最深的原子 {dd:+.2f} nm" if dd is not None else "", f", deepest atom {dd:+.2f} nm" if dd is not None else "",
            f"、最も深い原子は {dd:+.2f} nm" if dd is not None else "", f", 가장 깊은 원자 {dd:+.2f} nm" if dd is not None else "")
    if d < -0.5:
        out = [S("note", f"{key}：後半段質心在磷平面上方 {-d:.2f} nm（> 0.5 nm）{tail[0]}，溶質留在水中，沒有吸附到膜上。",
                 f"{key}: in the second half the centroid is {-d:.2f} nm above the phosphate plane (> 0.5 nm){tail[1]}. The solute stays in the water and has not adsorbed.",
                 f"{key}：後半の重心はリン原子面の {-d:.2f} nm 上（> 0.5 nm）にあり{tail[2]}、溶質は水中にとどまって膜に吸着していません。",
                 f"{key}: 후반부 무게중심이 인 원자 평면보다 {-d:.2f} nm 위(> 0.5 nm)에 있으며{tail[3]}, 용질이 물속에 머물러 막에 흡착하지 않았습니다.")]
    elif d < 0.3:
        out = [S("good", f"{key}：後半段質心深度 {d:+.2f} nm（磷平面上方 0.5 到下方 0.3 nm 之間）{tail[0]}，溶質吸附在頭基區，屬於膜表面接觸。",
                 f"{key}: the second-half centroid depth is {d:+.2f} nm (between 0.5 nm above and 0.3 nm below the phosphate plane){tail[1]}. "
                 "The solute is adsorbed at the head groups, a surface contact.",
                 f"{key}：後半の重心の深さは {d:+.2f} nm（リン原子面の上 0.5 nm から下 0.3 nm の間）で{tail[2]}、溶質は頭部基の領域に吸着しており、膜表面での接触です。",
                 f"{key}: 후반부 무게중심 깊이는 {d:+.2f} nm(인 평면 위 0.5 nm와 아래 0.3 nm 사이)이며{tail[3]}, 용질이 머리 부분 영역에 흡착한 막 표면 접촉입니다.")]
    elif d < 1.0:
        out = [S("note", f"{key}：後半段質心在磷平面下方 {d:.2f} nm（0.3 到 1.0 nm）{tail[0]}，溶質插入頭基與脂肪鏈之間的介面區。",
                 f"{key}: the second-half centroid is {d:.2f} nm below the phosphate plane (0.3–1.0 nm){tail[1]}. The solute has inserted into the interface between head groups and acyl chains.",
                 f"{key}：後半の重心はリン原子面の {d:.2f} nm 下（0.3〜1.0 nm）にあり{tail[2]}、溶質は頭部基とアシル鎖の間の界面領域に入り込んでいます。",
                 f"{key}: 후반부 무게중심이 인 원자 평면보다 {d:.2f} nm 아래(0.3~1.0 nm)에 있으며{tail[3]}, 용질이 머리 부분과 아실 사슬 사이의 계면 영역에 삽입되었습니다.")]
    else:
        out = [S("note", f"{key}：後半段質心在磷平面下方 {d:.2f} nm（≥ 1.0 nm）{tail[0]}，溶質進入疏水核心。",
                 f"{key}: the second-half centroid is {d:.2f} nm below the phosphate plane (≥ 1.0 nm){tail[1]}. The solute has entered the hydrophobic core.",
                 f"{key}：後半の重心はリン原子面の {d:.2f} nm 下（≥ 1.0 nm）にあり{tail[2]}、溶質は疎水性コアに入っています。",
                 f"{key}: 후반부 무게중심이 인 원자 평면보다 {d:.2f} nm 아래(≥ 1.0 nm)에 있으며{tail[3]}, 용질이 소수성 중심부에 들어갔습니다.")]
    a = float(c[: max(1, len(c) // 10)].mean())
    if abs(d - a) > 0.5:
        out.append(S("note", f"{key}：深度從開始的 {a:+.2f} nm 變到後半段的 {d:+.2f} nm（變化 > 0.5 nm），吸附或插入在模擬中發生，後半段可能仍未穩定。",
                     f"{key}: the depth moved from {a:+.2f} nm at the start to {d:+.2f} nm in the second half (change > 0.5 nm). "
                     "Adsorption or insertion happened during the run and may not have settled.",
                     f"{key}：深さは最初の {a:+.2f} nm から後半の {d:+.2f} nm に変わりました（変化 > 0.5 nm）。吸着や挿入は計算中に起きており、後半でもまだ落ち着いていない可能性があります。",
                     f"{key}: 깊이가 처음 {a:+.2f} nm에서 후반부 {d:+.2f} nm로 바뀌었습니다(변화 > 0.5 nm). 흡착이나 삽입이 시뮬레이션 중에 일어났으며 후반부에도 아직 안정되지 않았을 수 있습니다."))
    if crossed:
        out.append(S("caution", f"{key}：溶質穿過了膜中心。這是罕見事件，請確認盒子大小與約束設定。一次穿越不能當作穿膜速率。",
                     f"{key}: the solute crossed the membrane centre. This is a rare event, so check the box size and restraints. One crossing is not a permeation rate.",
                     f"{key}：溶質が膜中心を通過しました。まれな現象なので、ボックスの大きさと拘束の設定を確認してください。1 回の通過は透過速度にはなりません。",
                     f"{key}: 용질이 막 중심을 통과했습니다. 드문 사건이므로 상자 크기와 구속 설정을 확인하십시오. 한 번의 통과는 투과 속도가 아닙니다."))
    return out


def classify_headgroup(key: str, rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    anch = [r for r in rows if r["fraction"] >= 0.5]
    out = []
    if anch:
        names = [r["residue"] for r in anch]
        z, e = _jz(names)
        basic = [n for n in names if str(n).upper().startswith(("LYS", "ARG", "K", "R"))]
        out.append(S("good", f"{key}：{z} 有 50 % 以上的時間與頭基接觸，是吸附的錨點" + (f"。其中帶正電的離胺酸或精胺酸有 {'、'.join(basic)}，符合與磷酸基的靜電吸引。" if basic else "。"),
                     f"{key}: {e} touch the head groups at least 50 % of the time and anchor the adsorption"
                     + (f". The positively charged lysine or arginine among them ({', '.join(basic)}) fits electrostatic attraction to the phosphates." if basic else "."),
                     f"{key}：{z} は 50 % 以上の時間、頭部基と接触しており、吸着のアンカーです" + (f"。そのうち正に帯電したリシンまたはアルギニン（{'、'.join(basic)}）は、リン酸基との静電的な引力と合っています。" if basic else "。"),
                     f"{key}: {e} 잔기는 50 % 이상의 시간 동안 머리 부분과 접촉하는 흡착 앵커입니다" + (f". 그중 양전하를 띤 라이신이나 아르지닌({', '.join(basic)})은 인산기와의 정전기적 인력과 맞습니다." if basic else ".")))
    else:
        top = rows[0]
        out.append(S("note", f"{key}：沒有殘基與頭基接觸超過 50 % 的時間（最高 {top['residue']} {top['fraction']:.0%}），接觸是短暫的。",
                     f"{key}: no residue touches the head groups for 50 % of the time (highest {top['residue']} {top['fraction']:.0%}), so contacts are transient.",
                     f"{key}：50 % 以上の時間頭部基と接触する残基はなく（最大は {top['residue']} の {top['fraction']:.0%}）、接触は一時的です。",
                     f"{key}: 50 % 이상 머리 부분과 접촉하는 잔기가 없으며(최고 {top['residue']} {top['fraction']:.0%}) 접촉은 일시적입니다."))
    best = max(rows, key=lambda r: r.get("max_ps") or 0)
    if best.get("max_ps"):
        mx = best["max_ps"] / 1000.0
        out.append(S("note", f"{key}：最長的連續接觸是 {best['residue']} 的 {mx:.2f} ns（共 {best.get('events', 0)} 次接觸，平均 {best.get('mean_ps', 0) / 1000:.2f} ns）。",
                     f"{key}: the longest continuous contact is {best['residue']} at {mx:.2f} ns ({best.get('events', 0)} contact events, mean {best.get('mean_ps', 0) / 1000:.2f} ns).",
                     f"{key}：最も長い連続接触は {best['residue']} の {mx:.2f} ns です（接触 {best.get('events', 0)} 回、平均 {best.get('mean_ps', 0) / 1000:.2f} ns）。",
                     f"{key}: 가장 긴 연속 접촉은 {best['residue']} 잔기의 {mx:.2f} ns입니다(접촉 {best.get('events', 0)}회, 평균 {best.get('mean_ps', 0) / 1000:.2f} ns)."))
    op = [r["residue"] for r in rows if r.get("open_at_end") and r["fraction"] >= 0.2]
    if op:
        z, e = _jz(op)
        out.append(S("note", f"{key}：{z} 在最後一幀仍在接觸，它們的停留時間只是下限，真正的停留更長。",
                     f"{key}: {e} are still in contact at the last frame, so their residence times are lower bounds and the true residence is longer.",
                     f"{key}：{z} は最後のフレームでも接触が続いているため、滞在時間は下限値で、実際の滞在はもっと長いです。",
                     f"{key}: {e} 잔기는 마지막 프레임에서도 접촉 중이므로 체류 시간은 하한값이며 실제 체류는 더 깁니다."))
    return out


def classify_tilt(key: str, tilt) -> list[dict]:
    a = np.asarray(tilt, float)
    if len(a) < 4:
        return []
    h = a[len(a) // 2:]
    m, sd = float(h.mean()), float(h.std())
    if m >= 60:
        t = ("平躺在膜面（≥ 60°），兩親性螺旋吸附時常見", "lies flat on the surface (≥ 60°), as amphipathic helices usually do when adsorbed",
             "膜面に寝ており（≥ 60°）、両親媒性ヘリックスが吸着したときによく見られる向き", "막 표면에 누워 있으며(≥ 60°) 양친매성 나선이 흡착할 때 흔한 방향")
    elif m >= 30:
        t = ("斜插（30° 到 60°）", "is oblique (30–60°)", "斜めに入った状態（30〜60°）", "비스듬히 들어간 상태(30~60°)")
    else:
        t = ("沿法線直立（< 30°），表面接觸的短胜肽很少這樣，請檢查是否插入膜中", "stands along the normal (< 30°), rare for a short surface-bound "
             "peptide, so check whether it has inserted", "法線に沿って立っており（< 30°）、表面に接触する短いペプチドではまれなので、膜に入り込んでいないか確認が必要",
             "법선을 따라 서 있으며(< 30°) 표면에 접촉하는 짧은 펩타이드에서는 드물므로 막에 삽입되었는지 확인 필요")
    out = [S("note", f"{key}：後半段平均傾角 {m:.0f}° ± {sd:.0f}°，胜肽{t[0]}。",
             f"{key}: the mean tilt in the second half is {m:.0f}° ± {sd:.0f}°, so the peptide {t[1]}.",
             f"{key}：後半の平均の傾きは {m:.0f}° ± {sd:.0f}° で、ペプチドは{t[2]}です。",
             f"{key}: 후반부 평균 기울기는 {m:.0f}° ± {sd:.0f}°로 펩타이드가 {t[3]}입니다.")]
    if sd > 20:
        out.append(S("caution", f"{key}：傾角的標準差 {sd:.0f}°（> 20°），方向還沒穩定，請延長模擬或增加重複。",
                     f"{key}: the tilt varies with a standard deviation of {sd:.0f}° (> 20°). The orientation has not settled, so extend the run or add replicas.",
                     f"{key}：傾きの標準偏差は {sd:.0f}°（> 20°）で、向きはまだ定まっていません。計算を延ばすか、繰り返しを増やしてください。",
                     f"{key}: 기울기 표준편차가 {sd:.0f}°(> 20°)로 방향이 아직 안정되지 않았습니다. 시뮬레이션을 늘리거나 반복을 추가하십시오."))
    return out


def classify_thickness_map(key: str, tmap: dict) -> list[dict]:
    G = np.array([[np.nan if v is None else v for v in row] for row in (tmap or {}).get("dpp_nm") or []], float)
    if G.size == 0 or not np.isfinite(G).any():
        return []
    m, lo, hi = float(np.nanmean(G)), float(np.nanmin(G)), float(np.nanmax(G))
    rng = hi - lo
    out = []
    if lo < 0.8 * m:
        out.append(S("caution", f"{key}：局部厚度最薄 {lo:.2f} nm，低於平均 {m:.2f} nm 的 80 %，膜明顯變薄，可能是缺陷或孔洞的前兆。請對照溶質的位置與膜中心的水。",
                     f"{key}: the thinnest cell is {lo:.2f} nm, below 80 % of the mean {m:.2f} nm. The membrane thins markedly, which may precede a "
                     "defect or pore. Compare with the solute position and water at the centre.",
                     f"{key}：最も薄い格子は {lo:.2f} nm で、平均 {m:.2f} nm の 80 % を下回っています。膜が明らかに薄くなっており、欠陥や孔の前ぶれかもしれません。溶質の位置と膜中心の水と照らし合わせてください。",
                     f"{key}: 가장 얇은 칸이 {lo:.2f} nm로 평균 {m:.2f} nm의 80 %보다 낮습니다. 막이 뚜렷하게 얇아졌으며 결함이나 구멍의 전조일 수 있습니다. 용질 위치와 막 중심의 물과 비교하십시오."))
    elif rng > 0.5:
        out.append(S("note", f"{key}：局部厚度在 {lo:.2f} 到 {hi:.2f} nm 之間（相差 {rng:.2f} nm，> 0.5 nm），膜有局部的厚薄變化。",
                     f"{key}: the local thickness ranges from {lo:.2f} to {hi:.2f} nm (a spread of {rng:.2f} nm, > 0.5 nm), so the membrane varies locally.",
                     f"{key}：局所的な厚さは {lo:.2f}〜{hi:.2f} nm（差 {rng:.2f} nm、> 0.5 nm）で、膜には局所的な厚さの変化があります。",
                     f"{key}: 국소 두께가 {lo:.2f}~{hi:.2f} nm(차이 {rng:.2f} nm, > 0.5 nm)로 막에 국소적인 두께 변화가 있습니다."))
    else:
        out.append(S("good", f"{key}：局部厚度在 {lo:.2f} 到 {hi:.2f} nm 之間（相差 {rng:.2f} nm，≤ 0.5 nm），膜厚均勻。",
                     f"{key}: the local thickness ranges from {lo:.2f} to {hi:.2f} nm (a spread of {rng:.2f} nm, ≤ 0.5 nm), so the membrane is uniform.",
                     f"{key}：局所的な厚さは {lo:.2f}〜{hi:.2f} nm（差 {rng:.2f} nm、≤ 0.5 nm）で、膜厚は均一です。",
                     f"{key}: 국소 두께가 {lo:.2f}~{hi:.2f} nm(차이 {rng:.2f} nm, ≤ 0.5 nm)로 막 두께가 균일합니다."))
    return out


# --------------------------------------------------------------------------------------------- long run
def classify_longrun(key: str, plan: dict, actual: dict) -> list[dict]:
    out = []
    p, a = float(plan.get("production_ns") or 0), actual.get("production_ns")
    if p and a is not None:
        f = float(a) / p
        out.append(S("good", f"{key}：正式模擬完成 {a:g} ns，達到規劃 {p:g} ns 的 {f:.0%}（≥ 99 %）。",
                     f"{key}: production completed {a:g} ns, {f:.0%} of the planned {p:g} ns (≥ 99 %).",
                     f"{key}：本計算は {a:g} ns 完了し、計画 {p:g} ns の {f:.0%}（≥ 99 %）に達しました。",
                     f"{key}: 본 시뮬레이션은 {a:g} ns를 완료해 계획 {p:g} ns의 {f:.0%}(≥ 99 %)에 도달했습니다.")
                   if f >= 0.99 else
                   S("caution", f"{key}：正式模擬只完成 {a:g} ns，是規劃 {p:g} ns 的 {f:.0%}（< 99 %）。後面的分析只代表已完成的部分，續跑後要重新產生報告。",
                     f"{key}: production completed only {a:g} ns, {f:.0%} of the planned {p:g} ns (< 99 %). The analysis covers only the "
                     "completed part, so regenerate the report after resuming.",
                     f"{key}：本計算は {a:g} ns しか完了しておらず、計画 {p:g} ns の {f:.0%}（< 99 %）です。解析は完了した部分だけを表すため、続きを実行した後でレポートを作り直してください。",
                     f"{key}: 본 시뮬레이션은 {a:g} ns만 완료해 계획 {p:g} ns의 {f:.0%}(< 99 %)입니다. 분석은 완료된 부분만 나타내므로 이어서 실행한 뒤 보고서를 다시 만드십시오."))
    reps = max(1, int(plan.get("replicas") or 1))
    pd_ = float(plan.get("total_gb") or 0) / reps
    ad = actual.get("disk_gb")
    if pd_ > 0 and ad is not None:
        r = float(ad) / pd_
        out.append(S("good", f"{key}：實際硬碟用量 {ad:.1f} GB，規劃每份 {pd_:.1f} GB（{r:.0%}，≤ 125 %）。",
                     f"{key}: actual disk use is {ad:.1f} GB against {pd_:.1f} GB planned per replica ({r:.0%}, ≤ 125 %).",
                     f"{key}：実際のディスク使用量は {ad:.1f} GB で、1 回分の計画 {pd_:.1f} GB の {r:.0%}（≤ 125 %）です。",
                     f"{key}: 실제 디스크 사용량은 {ad:.1f} GB로 1회분 계획 {pd_:.1f} GB의 {r:.0%}(≤ 125 %)입니다.")
                   if r <= 1.25 else
                   S("note", f"{key}：實際硬碟用量 {ad:.1f} GB，超過規劃每份 {pd_:.1f} GB 的 125 %（{r:.0%}），規劃的估計偏低，下次同樣大小的系統要多留空間。",
                     f"{key}: actual disk use is {ad:.1f} GB, more than 125 % of the {pd_:.1f} GB planned per replica ({r:.0%}). The estimate "
                     "was low, so leave more space next time for a system of this size.",
                     f"{key}：実際のディスク使用量は {ad:.1f} GB で、1 回分の計画 {pd_:.1f} GB の 125 % を超えました（{r:.0%}）。見積もりが低かったため、同じ大きさの系では次回もっと余裕を持たせてください。",
                     f"{key}: 실제 디스크 사용량이 {ad:.1f} GB로 1회분 계획 {pd_:.1f} GB의 125 %를 넘었습니다({r:.0%}). 추정이 낮았으므로 같은 크기의 시스템은 다음에 공간을 더 확보하십시오."))
    pdays, adays = plan.get("days"), actual.get("days")
    if pdays and adays:
        r = float(adays) / (float(pdays) / reps)
        if r > 1.5:
            out.append(S("note", f"{key}：實際花了約 {adays:.1f} 天，是估計的 {r:.1f} 倍（> 1.5 倍），效能測試可能高估了速度，請重新做效能測試。",
                         f"{key}: the run took about {adays:.1f} days, {r:.1f} times the estimate (> 1.5). The benchmark probably overestimated the speed, so run it again.",
                         f"{key}：実際には約 {adays:.1f} 日かかり、見積もりの {r:.1f} 倍（> 1.5 倍）でした。ベンチマークが速度を過大評価した可能性があるため、測り直してください。",
                         f"{key}: 실제로 약 {adays:.1f}일이 걸려 추정의 {r:.1f}배(> 1.5배)였습니다. 벤치마크가 속도를 과대평가했을 수 있으므로 다시 측정하십시오."))
    if plan.get("solute_only"):
        out.append(S("note", f"{key}：軌跡只存溶質（每 {plan.get('trajectory_interval_ps', 0):g} ps 一幀），水橋與水的密度剖面無法分析。",
                     f"{key}: only the solute was saved (one frame every {plan.get('trajectory_interval_ps', 0):g} ps), so water bridges and the water density profile cannot be analysed.",
                     f"{key}：軌跡は溶質だけを保存したため（{plan.get('trajectory_interval_ps', 0):g} ps ごとに 1 フレーム）、水架橋と水の密度分布は解析できません。",
                     f"{key}: 궤적은 용질만 저장했으므로({plan.get('trajectory_interval_ps', 0):g} ps마다 한 프레임) 물 다리와 물 밀도 분포는 분석할 수 없습니다."))
    return out


def classify_rmsf_halves(key: str, a, b) -> list[dict]:
    a, b = np.asarray(a, float), np.asarray(b, float)
    n = min(len(a), len(b))
    if n < 5:
        return []
    a, b = a[:n], b[:n]
    r = float(np.corrcoef(a, b)[0, 1]) if a.std() > 0 and b.std() > 0 else 0.0
    mad = float(np.abs(b - a).mean())
    shift = float(b.mean() - a.mean())
    if r >= 0.8 and mad <= 0.3:
        out = [S("good", f"{key}：前後兩半的 RMSF 相關係數 {r:.2f}（≥ 0.8），平均差 {mad:.2f} Å（≤ 0.3 Å），殘基柔性已收斂。",
                 f"{key}: the RMSF of the two halves correlates at r = {r:.2f} (≥ 0.8) with a mean difference of {mad:.2f} Å (≤ 0.3 Å). Residue flexibility has converged.",
                 f"{key}：前半と後半の RMSF の相関係数は {r:.2f}（≥ 0.8）、平均差は {mad:.2f} Å（≤ 0.3 Å）で、残基の柔軟性は収束しています。",
                 f"{key}: 전반부와 후반부 RMSF의 상관계수는 {r:.2f}(≥ 0.8), 평균 차이는 {mad:.2f} Å(≤ 0.3 Å)로 잔기 유연성이 수렴했습니다.")]
    elif r >= 0.6:
        out = [S("note", f"{key}：前後兩半的 RMSF 相關係數 {r:.2f}（0.6 到 0.8），平均差 {mad:.2f} Å，柔性的分佈大致一致，個別區域仍在變化。",
                 f"{key}: the RMSF of the two halves correlates at r = {r:.2f} (0.6–0.8) with a mean difference of {mad:.2f} Å. The pattern "
                 "broadly agrees but some regions are still changing.",
                 f"{key}：前半と後半の RMSF の相関係数は {r:.2f}（0.6〜0.8）、平均差は {mad:.2f} Å です。柔軟性の分布はおおむね一致していますが、一部の領域はまだ変化しています。",
                 f"{key}: 전반부와 후반부 RMSF의 상관계수는 {r:.2f}(0.6~0.8), 평균 차이는 {mad:.2f} Å입니다. 유연성 분포는 대체로 일치하지만 일부 영역은 아직 변하고 있습니다.")]
    else:
        out = [S("caution", f"{key}：前後兩半的 RMSF 相關係數只有 {r:.2f}（< 0.6），柔性還沒收斂，RMSF 的結論要等更長的模擬或更多重複。",
                 f"{key}: the RMSF of the two halves correlates at only r = {r:.2f} (< 0.6). Flexibility has not converged, so conclusions "
                 "from RMSF need a longer run or more replicas.",
                 f"{key}：前半と後半の RMSF の相関係数は {r:.2f}（< 0.6）しかなく、柔軟性は収束していません。RMSF からの結論には、より長い計算か繰り返しの追加が必要です。",
                 f"{key}: 전반부와 후반부 RMSF의 상관계수가 {r:.2f}(< 0.6)에 불과해 유연성이 수렴하지 않았습니다. RMSF에서 결론을 내리려면 더 긴 시뮬레이션이나 반복이 필요합니다.")]
    if shift > 0.3:
        out.append(S("note", f"{key}：後半段的 RMSF 平均高 {shift:.2f} Å（> 0.3 Å），模擬仍在取樣新的運動。",
                     f"{key}: the second half is {shift:.2f} Å more flexible on average (> 0.3 Å), so new motions are still being sampled.",
                     f"{key}：後半の RMSF は平均で {shift:.2f} Å 高く（> 0.3 Å）、新しい動きをまだサンプリングしています。",
                     f"{key}: 후반부 RMSF가 평균 {shift:.2f} Å 높아(> 0.3 Å) 새로운 움직임을 아직 샘플링하고 있습니다."))
    return out


def overlap_coefficient(a, b, bins: int = 30) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    lo, hi = float(min(a.min(), b.min())), float(max(a.max(), b.max()))
    if hi <= lo:
        return 1.0
    ha, e = np.histogram(a, bins=bins, range=(lo, hi))
    hb, _ = np.histogram(b, bins=e)
    return float(np.minimum(ha / ha.sum(), hb / hb.sum()).sum())


def classify_rmsd_halves(key: str, y) -> list[dict]:
    y = np.asarray(y, float)
    if len(y) < 20:
        return []
    a, b = y[: len(y) // 2], y[len(y) // 2:]
    ov = overlap_coefficient(a, b)
    ma, mb = float(a.mean()), float(b.mean())
    txt = (f"前半段 {ma:.2f} Å、後半段 {mb:.2f} Å", f"first half {ma:.2f} Å, second half {mb:.2f} Å",
           f"前半 {ma:.2f} Å、後半 {mb:.2f} Å", f"전반부 {ma:.2f} Å, 후반부 {mb:.2f} Å")
    if ov >= 0.6:
        return [S("good", f"{key}：兩半 RMSD 分佈的重疊係數 {ov:.2f}（≥ 0.6，{txt[0]}），取樣到同一組構形。",
                  f"{key}: the RMSD distributions of the two halves overlap at {ov:.2f} (≥ 0.6, {txt[1]}), so both sampled the same conformations.",
                  f"{key}：前半と後半の RMSD 分布の重なり係数は {ov:.2f}（≥ 0.6、{txt[2]}）で、同じ構造の集まりをサンプリングしています。",
                  f"{key}: 두 절반의 RMSD 분포 겹침 계수는 {ov:.2f}(≥ 0.6, {txt[3]})로 같은 구조 집합을 샘플링했습니다.")]
    if ov >= 0.3:
        return [S("note", f"{key}：兩半 RMSD 分佈的重疊係數 {ov:.2f}（0.3 到 0.6，{txt[0]}），結構還在慢慢變化。",
                  f"{key}: the RMSD distributions of the two halves overlap at {ov:.2f} (0.3–0.6, {txt[1]}). The structure is still drifting slowly.",
                  f"{key}：前半と後半の RMSD 分布の重なり係数は {ov:.2f}（0.3〜0.6、{txt[2]}）で、構造はまだゆっくり変化しています。",
                  f"{key}: 두 절반의 RMSD 분포 겹침 계수는 {ov:.2f}(0.3~0.6, {txt[3]})로 구조가 아직 천천히 변하고 있습니다.")]
    return [S("caution", f"{key}：兩半 RMSD 分佈的重疊係數只有 {ov:.2f}（< 0.3，{txt[0]}），後半段到了新的構形，整段平均不能代表結構。只用後半段分析，或延長模擬。",
              f"{key}: the RMSD distributions of the two halves overlap at only {ov:.2f} (< 0.3, {txt[1]}). The second half reached new "
              "conformations and a whole-run average is not representative. Analyse the second half only or extend the run.",
              f"{key}：前半と後半の RMSD 分布の重なり係数は {ov:.2f}（< 0.3、{txt[2]}）しかなく、後半は新しい構造に移っています。全体の平均は代表値にならないため、後半だけを解析するか計算を延ばしてください。",
              f"{key}: 두 절반의 RMSD 분포 겹침 계수가 {ov:.2f}(< 0.3, {txt[3]})에 불과해 후반부가 새로운 구조로 옮겨 갔습니다. 전체 평균은 대표값이 되지 못하므로 후반부만 분석하거나 시뮬레이션을 늘리십시오.")]


def cluster_windows(labels, n_windows: int = 10) -> tuple[np.ndarray, list[int]]:
    """(windows × clusters) share of each cluster per window and the cluster ids (columns)."""
    lab = np.asarray(labels, int)
    ids = sorted(set(lab.tolist()))
    parts = np.array_split(lab, min(n_windows, max(1, len(lab))))
    P = np.array([[float((p == c).mean()) if len(p) else 0.0 for c in ids] for p in parts])
    return P, ids


def classify_cluster_timeline(key: str, labels) -> list[dict]:
    lab = np.asarray(labels, int)
    if len(lab) < 20:
        return []
    ids = sorted(set(lab.tolist()))
    h1, h2, q4 = lab[: len(lab) // 2], lab[len(lab) // 2:], lab[3 * len(lab) // 4:]
    d = {c: float((h2 == c).mean() - (h1 == c).mean()) for c in ids}
    out = []
    worst = max(d, key=lambda c: abs(d[c]))
    if abs(d[worst]) <= 0.10:
        out.append(S("good", f"{key}：各叢集在前後兩半的比例相差都在 10 個百分點以內（變化最大的是叢集 {worst + 1}，{abs(d[worst]) * 100:.0f} 個百分點），構形分佈穩定。",
                     f"{key}: every cluster's share differs by at most 10 percentage points between the halves (largest change {abs(d[worst]) * 100:.0f} points, cluster {worst + 1}), so the distribution is stable.",
                     f"{key}：各クラスターの割合の前半と後半の差はすべて 10 ポイント以内（最も変化したのはクラスター {worst + 1} の {abs(d[worst]) * 100:.0f} ポイント）で、構造の分布は安定しています。",
                     f"{key}: 모든 클러스터 비율의 전후반 차이가 10 %p 이내(가장 크게 변한 것은 클러스터 {worst + 1}, {abs(d[worst]) * 100:.0f} %p)로 구조 분포가 안정적입니다."))
    else:
        out.append(S("note", f"{key}：叢集 {worst + 1} 的比例在後半段改變 {d[worst] * 100:+.0f} 個百分點（超過 10），構形的分佈還在移動。",
                     f"{key}: cluster {worst + 1} changes its share by {d[worst] * 100:+.0f} percentage points in the second half (more than 10), so the distribution is still shifting.",
                     f"{key}：クラスター {worst + 1} の割合が後半で {d[worst] * 100:+.0f} ポイント変わっており（10 超）、構造の分布はまだ動いています。",
                     f"{key}: 클러스터 {worst + 1}의 비율이 후반부에 {d[worst] * 100:+.0f} %p 바뀌어(10 초과) 구조 분포가 아직 움직이고 있습니다."))
    new = [c for c in ids if (h1 == c).mean() < 0.05 and (q4 == c).mean() >= 0.2]
    if new:
        z, e = _jz([c + 1 for c in new])
        out.append(S("caution", f"{key}：叢集 {z} 在前半段幾乎沒有（< 5 %），最後四分之一卻占 20 % 以上，模擬還在探索新的狀態，沒有收斂。",
                     f"{key}: cluster {e} is almost absent in the first half (< 5 %) but holds 20 % or more of the last quarter. The run is still exploring new states and has not converged.",
                     f"{key}：クラスター {z} は前半にはほとんどなく（< 5 %）、最後の 4 分の 1 では 20 % 以上を占めます。計算はまだ新しい状態を探しており、収束していません。",
                     f"{key}: 클러스터 {e}는 전반부에 거의 없지만(< 5 %) 마지막 4분의 1에서는 20 % 이상을 차지합니다. 시뮬레이션이 아직 새로운 상태를 탐색 중이며 수렴하지 않았습니다."))
    sw = int((np.diff(lab) != 0).sum())
    if len(ids) > 1:
        out.append(S("note", f"{key}：{len(lab)} 幀中叢集切換 {sw} 次。",
                     f"{key}: the cluster changes {sw} times over {len(lab)} frames.",
                     f"{key}：{len(lab)} フレームの間にクラスターは {sw} 回切り替わりました。",
                     f"{key}: {len(lab)}프레임 동안 클러스터가 {sw}번 바뀌었습니다."))
    return out


# --------------------------------------------------------------------------------------------- coarse-grained
def classify_cg_membrane(name: str, summ: dict) -> list[dict]:
    out = [S("note", f"{name}：這是粗粒化（Martini 3）模擬，每顆珠子約 4 個重原子，數值是珠子層級，不是全原子結果。",
             f"{name}: this is a coarse-grained (Martini 3) simulation with about 4 heavy atoms per bead. The values are bead-level, not atomistic.",
             f"{name}：これは粗視化（Martini 3）シミュレーションで、ビーズ 1 個はおよそ 4 個の重原子です。値はビーズ単位で、全原子の結果ではありません。",
             f"{name}: 조립화(Martini 3) 시뮬레이션이며 비드 하나가 중원자 약 4개입니다. 값은 비드 단위이며 전원자 결과가 아닙니다.")]
    out += classify_membrane_equil(name, summ.get("time_ns") or [], summ.get("apl_nm2") or [], summ.get("dpp_nm") or [], summ.get("reference"))
    p2 = summ.get("p2") or {}
    if p2:
        m = float(np.mean(list(p2.values())))
        out.append(S("good", f"{name}：鍵的序參數 P2 平均 {m:.2f}（0.1 到 0.6），脂肪鏈是流體相。",
                     f"{name}: the mean bond order parameter P2 is {m:.2f} (0.1–0.6), so the tails are in the fluid phase.",
                     f"{name}：結合の秩序パラメータ P2 の平均は {m:.2f}（0.1〜0.6）で、アシル鎖は流動相です。",
                     f"{name}: 결합 질서 매개변수 P2 평균은 {m:.2f}(0.1~0.6)로 아실 사슬이 유동상입니다.")
                   if 0.1 <= m <= 0.6 else
                   S("caution", f"{name}：鍵的序參數 P2 平均 {m:.2f}（{'> 0.6，偏凝膠相' if m > 0.6 else '< 0.1，過於無序'}），請檢查溫度與組成。",
                     f"{name}: the mean bond order parameter P2 is {m:.2f} ({'> 0.6, towards the gel phase' if m > 0.6 else '< 0.1, over-disordered'}). Check temperature and composition.",
                     f"{name}：結合の秩序パラメータ P2 の平均は {m:.2f}（{'> 0.6、ゲル相寄り' if m > 0.6 else '< 0.1、無秩序すぎる'}）です。温度と組成を確認してください。",
                     f"{name}: 결합 질서 매개변수 P2 평균은 {m:.2f}({'> 0.6, 겔상 쪽' if m > 0.6 else '< 0.1, 지나치게 무질서함'})입니다. 온도와 조성을 확인하십시오."))
    return out


# D-105 analysis toolbox: tICA landscape, Markov state model timescales (md20/analysis/toolbox.py)
FIG.update({
    "tica_landscape": {
        "title": ("慢運動的自由能地形（tICA）", "Free-energy landscape of the slow motions (tICA)",
                  "遅い運動の自由エネルギー地形（tICA）", "느린 운동의 자유 에너지 지형(tICA)"),
        "caption": ("Cα 座標先做主成分分析，再找出隨時間變化最慢的兩個組合（時間延遲獨立成分）畫成地形。顏色越深自由能越低。",
                    "Cα coordinates are reduced by PCA, then the two combinations that change most slowly in time "
                    "(time-lagged independent components) are drawn as a landscape. Darker is lower free energy.",
                    "Cα 座標を主成分分析で縮約し、時間的に最もゆっくり変わる2つの組み合わせ（時間遅れ独立成分）で地形を描いています。色が濃いほど自由エネルギーが低くなります。",
                    "Cα 좌표를 주성분 분석으로 줄인 뒤, 시간에 따라 가장 느리게 변하는 두 조합(시간 지연 독립 성분)으로 지형을 그렸습니다. 색이 진할수록 자유 에너지가 낮습니다."),
        "read": ("PCA 找的是變動最大的方向，tICA 找的是變得最慢的方向，兩者不一定相同。分開的低谷代表彼此轉換很慢的構形狀態。低谷之間只轉換過一兩次時，相對深度不可信。",
                 "PCA finds the directions that vary most; tICA finds those that change most slowly, which need not be the "
                 "same. Separate basins are states that interconvert slowly. If the run crossed between them only once or "
                 "twice, their relative depth is not reliable.",
                 "PCA は変動の大きい方向、tICA は変化の遅い方向を見つけます。両者は同じとは限りません。離れた谷は互いの転移が遅い構造状態です。"
                 "谷の間の転移が1、2回しかない場合、谷の相対的な深さは信頼できません。",
                 "PCA는 변동이 큰 방향을, tICA는 가장 느리게 변하는 방향을 찾으며 둘이 같다는 보장은 없습니다. 떨어진 골은 서로 느리게 바뀌는 구조 상태입니다. "
                 "골 사이 전이가 한두 번뿐이면 골의 상대 깊이는 믿을 수 없습니다."),
    },
    "msm_its": {
        "title": ("馬可夫狀態模型的隱含時間尺度", "Implied timescales of the Markov state model",
                  "マルコフ状態モデルの陰的時間スケール", "마르코프 상태 모델의 암시적 시간 척도"),
        "caption": ("tICA 空間分成數十個微狀態，在不同延遲時間估計轉移矩陣，畫出最慢的幾個過程的時間尺度。灰色區域短於延遲時間，無法解析；虛線是模擬長度的三分之一。",
                    "tICA space is split into tens of microstates, the transition matrix is estimated at several lag times and "
                    "the timescales of the slowest processes are drawn. The grey area is shorter than the lag and cannot be "
                    "resolved. The dashed line is one third of the run.",
                    "tICA 空間を数十個のミクロ状態に分け、いくつかの遅れ時間で遷移行列を推定し、最も遅い過程の時間スケールを描いています。灰色の領域は遅れ時間より短く、解像できません。破線はシミュレーション長の3分の1です。",
                    "tICA 공간을 수십 개 미시 상태로 나누고 여러 지연 시간에서 전이 행렬을 추정해 가장 느린 과정들의 시간 척도를 그렸습니다. 회색 영역은 지연 시간보다 짧아 분해할 수 없습니다. 점선은 시뮬레이션 길이의 3분의 1입니다."),
        "read": ("曲線隨延遲時間變平，代表模型在那個延遲下近似馬可夫。時間尺度接近或超過虛線，代表那個過程在這次模擬裡只發生過很少次，數值只能當教學示範，不能當速率。單一一條軌跡的 MSM 不能用來報告動力學結論。",
                 "A curve that levels off as the lag grows means the model is close to Markovian at that lag. A timescale "
                 "near or above the dashed line means the process happened only a few times in this run, so the value is "
                 "a teaching illustration, not a rate. An MSM from a single trajectory cannot support kinetic conclusions.",
                 "遅れ時間を大きくして曲線が平らになれば、その遅れ時間でモデルはほぼマルコフ的です。時間スケールが破線に近いか超える場合、その過程はこの計算で数回しか起きておらず、値は教育用の例であって速度ではありません。"
                 "1本のトラジェクトリから作った MSM で速度論の結論は出せません。",
                 "지연 시간이 길어질수록 곡선이 평평해지면 그 지연 시간에서 모델이 마르코프에 가깝다는 뜻입니다. 시간 척도가 점선 근처이거나 넘으면 그 과정은 이번 계산에서 몇 번밖에 일어나지 않았으므로 값은 교육용 예시이고 속도가 아닙니다. "
                 "궤적 하나로 만든 MSM으로는 동역학 결론을 낼 수 없습니다."),
    },
})


def classify_tica(name: str, ti: dict) -> list[dict]:
    basins = (ti.get("landscape") or {}).get("basins") or []
    ts = [v for v in (ti.get("timescales_ns") or []) if v is not None]
    lag = ti.get("lag_ns")
    slow = f"{ts[0]:.2g}" if ts else "—"
    lead = (f"{name}：延遲 {lag} ns，最慢的運動模式時間尺度約 {slow} ns",
            f"{name}: lag {lag} ns, slowest mode about {slow} ns",
            f"{name}：遅れ時間 {lag} ns、最も遅い運動モードの時間スケールは約 {slow} ns",
            f"{name}: 지연 {lag} ns, 가장 느린 운동 모드의 시간 척도 약 {slow} ns")
    if len(basins) <= 1:
        return [S("good", lead[0] + "。慢運動地形只有一個主要低谷。", lead[1] + ". The slow-motion landscape has one main basin.",
                  lead[2] + "。遅い運動の地形には主な谷が1つだけです。", lead[3] + ". 느린 운동 지형에 주요 골이 하나뿐입니다.")]
    return [S("note", lead[0] + f"。有 {len(basins)} 個低谷，蛋白在慢速轉換的構形之間移動。",
              lead[1] + f". There are {len(basins)} basins: the protein moves between slowly interconverting states.",
              lead[2] + f"。谷が {len(basins)} 個あり、タンパク質はゆっくり転移する状態の間を動いています。",
              lead[3] + f". 골이 {len(basins)}개로, 단백질이 느리게 바뀌는 상태들 사이를 움직입니다.")]


def classify_msm(name: str, m: dict) -> list[dict]:
    el = m.get("eligibility")
    T = m.get("trajectory_ns")
    if el == "insufficient":
        return [S("caution", f"{name}：轉換次數或連通性不足（{m.get('reason')}），不建立馬可夫模型的結論，圖只示範方法。",
                  f"{name}: too few transitions or poor connectivity ({m.get('reason')}). No conclusion is drawn from the "
                  "Markov model; the figure only shows the method.",
                  f"{name}：遷移の回数か連結性が足りません（{m.get('reason')}）。マルコフモデルから結論は出さず、図は方法の例示です。",
                  f"{name}: 전이 횟수나 연결성이 부족합니다({m.get('reason')}). 마르코프 모델로 결론을 내지 않으며 그림은 방법 예시입니다.")]
    if el == "unresolved":
        return [S("caution", f"{name}：最慢過程長於模擬（{T} ns）的三分之一，這次只看過幾次，時間尺度不可當速率。",
                  f"{name}: the slowest process is longer than a third of the run ({T} ns). It was seen only a few times, "
                  "so its timescale is not a rate.",
                  f"{name}：最も遅い過程がシミュレーション（{T} ns）の3分の1より長く、数回しか観測されていません。時間スケールを速度として扱えません。",
                  f"{name}: 가장 느린 과정이 시뮬레이션({T} ns)의 3분의 1보다 길어 몇 번밖에 관찰되지 않았습니다. 시간 척도를 속도로 볼 수 없습니다.")]
    flat = m.get("its_flat")
    return [S("note" if flat else "caution",
              f"{name}：時間尺度" + ("隨延遲時間變平" if flat else "隨延遲時間仍在變") + "；單一軌跡，只能當探索性的結果。",
              f"{name}: the timescales " + ("level off with lag" if flat else "still change with lag") +
              ". One trajectory, so this is exploratory only.",
              f"{name}：時間スケールは遅れ時間に対して" + ("平らになっています" if flat else "まだ変化しています") + "。1本のトラジェクトリなので探索的な結果です。",
              f"{name}: 시간 척도가 지연 시간에 따라 " + ("평평해집니다" if flat else "아직 변합니다") + ". 궤적 하나이므로 탐색적 결과입니다.")]
