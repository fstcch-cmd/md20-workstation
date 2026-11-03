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
                         f"{key}：RMSD 進入低於 2 Å 的平台（{tail[0]}），結構穩定且已平衡。",
                         f"{key}: RMSD levels off below 2 Å ({tail[1]}). The structure is stable and equilibrated.",
                         f"{key}：RMSD は 2 Å 未満で平坦になっています（{tail[2]}）。構造は安定しており、平衡に達しています。",
                         f"{key}: RMSD가 2 Å 미만에서 평탄해졌습니다({tail[3]}). 구조가 안정적이며 평형에 도달했습니다."))
    ref = next((k for k in means if k.lower().startswith("apo")), None)
    if ref is not None:
        for k, m in means.items():
            if k == ref:
                continue
            d = m - means[ref]
            if d <= -0.3:
                out.append(S("good",
                             f"{k} 的平台比蛋白單獨低 {abs(d):.2f} Å（≥ 0.3），配體結合讓蛋白更穩定。",
                             f"{k} plateaus {abs(d):.2f} Å below the protein alone (≥ 0.3), so ligand binding stabilises the protein.",
                             f"{k} の平坦部はタンパク質単独より {abs(d):.2f} Å 低く（≥ 0.3）、リガンドの結合でタンパク質が安定しています。",
                             f"{k} 시스템의 평탄 구간이 단백질 단독보다 {abs(d):.2f} Å 낮습니다(≥ 0.3). 리간드 결합으로 단백질이 더 안정해졌습니다."))
            elif d >= 0.3:
                out.append(S("note",
                             f"{k} 的平台比蛋白單獨高 {d:.2f} Å（≥ 0.3），配體結合後蛋白的構形調整較大。",
                             f"{k} plateaus {d:.2f} Å above the protein alone (≥ 0.3). The protein adjusts more with the ligand bound.",
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


def classify_umbrella(coverage: dict, name: str) -> list[dict]:
    if not coverage:
        return []
    br = coverage.get("breaks") or []
    if coverage.get("continuous") and not br:
        nw = coverage.get("n_windows")
        return [S("good",
                  f"{name}：{f'{nw} 個' if nw else '所有'}窗口的分佈在整條路徑上互相重疊，剖面連續。",
                  f"{name}: {f'the {nw}' if nw else 'all'} windows overlap along the whole path, so the profile is continuous.",
                  f"{name}：{f'{nw} 個の' if nw else 'すべての'}ウィンドウの分布が経路全体で重なっており、プロファイルは連続しています。",
                  f"{name}: {f'{nw}개' if nw else '모든'} 윈도우의 분포가 경로 전체에서 겹치므로 프로파일이 연속적입니다.")]
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
    kinds = (("ionic", ("離子", "ionic", "イオン性", "이온성")), ("polar", ("極性", "polar", "極性", "극성")),
             ("hydrophobic", ("疏水", "hydrophobic", "疎水性", "소수성")))
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


def classify_overlap(name: str, o: dict) -> list[dict]:
    if not o or "min_neighbour" not in o:
        return []
    mn = o["min_neighbour"]
    c = o.get("centers") or []
    i = int(np.argmin(o.get("neighbour") or [0]))
    where = f"{c[i]:.2f}–{c[i + 1]:.2f} nm" if len(c) > i + 1 else ""
    if mn >= 0.2:
        return [S("good",
                  f"{name}：相鄰窗口的重疊最低為 {mn:.2f}（≥ 0.2），整條路徑的取樣連續。",
                  f"{name}: the lowest neighbour overlap is {mn:.2f} (≥ 0.2), so sampling is continuous along the path.",
                  f"{name}：隣り合うウィンドウの重なりは最低でも {mn:.2f} です（≥ 0.2）。経路全体でサンプリングが連続しています。",
                  f"{name}: 이웃한 윈도우의 겹침이 최저 {mn:.2f}입니다(≥ 0.2). 경로 전체에서 샘플링이 연속적입니다.")]
    if mn >= 0.05:
        return [S("note",
                  f"{name}：最低重疊 {mn:.2f}，位置在 {where}。低於 0.2 但仍連通，該處誤差較大。",
                  f"{name}: the lowest overlap is {mn:.2f} (at {where}). It is below 0.2 but still connected, and the error is larger there.",
                  f"{name}：最も低い重なりは {mn:.2f} です（{where}）。0.2 を下回りますがつながってはおり、そこでは誤差が大きくなります。",
                  f"{name}: 가장 낮은 겹침은 {mn:.2f}입니다({where}). 0.2보다 낮지만 아직 이어져 있으며, 그 위치의 오차가 큽니다.")]
    return [S("caution",
              f"{name}：{where} 的重疊只有 {mn:.2f}（< 0.05），剖面在這裡斷開，需要補窗口。",
              f"{name}: overlap at {where} is only {mn:.2f} (< 0.05). The profile is broken there and windows must be added.",
              f"{name}：{where} の重なりは {mn:.2f} しかありません（< 0.05）。プロファイルはここで途切れているため、ウィンドウを追加する必要があります。",
              f"{name}: {where}의 겹침이 {mn:.2f}에 불과합니다(< 0.05). 프로파일이 여기서 끊어지므로 윈도우를 추가해야 합니다.")]


def classify_convergence(name: str, conv: dict) -> list[dict]:
    vals = [(k, v.get("delta_pmf")) for k, v in sorted(conv.items()) if isinstance(v, dict) and v.get("delta_pmf") is not None]
    if len(vals) < 2:
        return []
    d = abs(vals[-1][1] - vals[-2][1])
    p = float(vals[-2][0])
    if d <= 2.0:
        return [S("good",
                  f"{name}：取樣從 {p:.0%} 增加到全部時，井深只變化 {d:.1f} kJ mol⁻¹（≤ 2），自由能已收斂。",
                  f"{name}: the depth changes by only {d:.1f} kJ mol⁻¹ from {p:.0%} to all samples (≤ 2), so the free energy has converged.",
                  f"{name}：サンプルを {p:.0%} から全体に増やしても、井戸の深さの変化は {d:.1f} kJ mol⁻¹ だけです（≤ 2）。自由エネルギーは収束しています。",
                  f"{name}: 샘플을 {p:.0%}에서 전체로 늘려도 우물 깊이 변화가 {d:.1f} kJ mol⁻¹에 그칩니다(≤ 2). 자유 에너지가 수렴했습니다.")]
    return [S("caution",
              f"{name}：取樣從 {p:.0%} 增加到全部時，井深仍變化 {d:.1f} kJ mol⁻¹（> 2），尚未收斂，需要更長的窗口。",
              f"{name}: the depth still changes by {d:.1f} kJ mol⁻¹ from {p:.0%} to all samples (> 2). It has not converged and "
              "longer windows are needed.",
              f"{name}：サンプルを {p:.0%} から全体に増やすと、井戸の深さがまだ {d:.1f} kJ mol⁻¹ 変化します（> 2）。収束していないため、ウィンドウを長くする必要があります。",
              f"{name}: 샘플을 {p:.0%}에서 전체로 늘리면 우물 깊이가 아직 {d:.1f} kJ mol⁻¹ 바뀝니다(> 2). 수렴하지 않았으므로 윈도우를 더 길게 해야 합니다.")]


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


_KIND_2D = {"hbond": ("氫鍵", "Hydrogen bonds", "水素結合", "수소 결합"), "ionic": ("離子作用", "Ionic", "イオン性", "이온성"),
            "hydrophobic": ("疏水作用", "Hydrophobic", "疎水性", "소수성"), "contact": ("其他接觸", "Other contacts", "その他の接触", "기타 접촉")}


def classify_interaction_2d(name: str, cons: list[dict]) -> list[dict]:
    hit = [c for c in cons if c.get("res")]
    if not hit:
        return []
    kinds = {}
    for c in hit:
        kinds.setdefault(c["kind"], set()).add(c["res"])
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
