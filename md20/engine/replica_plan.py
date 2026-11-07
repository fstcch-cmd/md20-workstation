"""Replica plan (D-129 / D-131): how many independent trajectories a workflow needs, what it costs, what the user can choose.

Pure Python, no OpenMM.  Everything here is information plus a default; it never stops a run (docs/specs/replicas.md §4).
The choice the user makes is written to the config (`md.replicas`) and the DecisionLog by the caller
(`Workflow.record_replica_plan`, `gui.actions.set_replicas`).

Text is (zh, en, ja, ko) tuples, `pick(..., lang)` resolves them (docs/specs/writing_style.md).
"""
from __future__ import annotations

from ..i18n import pick

# docs/specs/replicas.md §2: the least number of independent replicas each analysis needs.  The workflow runs all of
# these analyses, so the number of replicas it needs is the largest of them (§3).  3 is the smallest number for which a
# sample standard deviation and a t-based confidence interval exist.
ANALYSIS_MIN_REPLICAS: dict[str, int] = {
    "backbone_rmsd_rg_sasa": 3,
    "rmsf": 3,
    "delta_rmsf_apo_vs_complex": 3,
    "ligand_state": 3,
    "contacts_fingerprint_hbond_persistence": 3,
    "hydration_sites": 3,
    "dssp": 3,
    "pca_landscape_clusters_common_basis": 3,
    "dccm": 3,
    "tica_msm": 3,
    "membrane_area_thickness_order": 3,
    "binding_dG_research": 3,
}


def required_replicas() -> int:
    return max(ANALYSIS_MIN_REPLICAS.values())


DEFAULT_REPLICAS: int = required_replicas()     # every tier, including classroom (D-129)
DEFAULT_SEED = 2026                             # make_protocol's seed
SEED_STRIDE = 1000                              # replicas.replica_protocol: seed + 1000 * index
MAX_REPLICAS_SUGGESTED = 10                     # the advisor form's upper bound; the config itself accepts more


def configured_replicas(cfg: dict | None) -> tuple[int, bool]:
    """(number of replicas the workflow will run, whether the config sets it).  Not set -> the default."""
    md = (cfg or {}).get("md") or {}
    v = md.get("replicas")
    if v is None or isinstance(v, bool):
        return DEFAULT_REPLICAS, False
    try:
        return max(1, int(v)), True
    except (TypeError, ValueError):
        return DEFAULT_REPLICAS, False


def seeds_for(n: int, base_seed: int = DEFAULT_SEED) -> list[int]:
    return [int(base_seed) + SEED_STRIDE * i for i in range(max(0, int(n)))]


# ------------------------------------------------------------------------------------------------ cost
def count_systems(cfg: dict | None, built_keys: list[str] | None = None) -> int:
    """How many systems get their own replicas.  The built cases when they are known, otherwise from the config."""
    if built_keys:
        return len(built_keys)
    cfg = cfg or {}
    systems = (cfg.get("md") or {}).get("systems") or ["apo", "docked_single"]
    ligs = [l for l in cfg.get("ligands") or [] if isinstance(l, dict)]
    n = 0
    if "apo" in systems:
        n += 1
    if "docked_single" in systems:
        n += len(ligs)
    if "docked_multi" in systems and len(ligs) >= 2:
        n += 1
    return max(1, n)


def md_ns_per_replica(cfg: dict | None) -> tuple[float, float]:
    """(simulated ns of one replica of one system without the minimisation, time step of production in fs), as
    `Workflow.run_md` builds the protocol.  Membrane and implicit-solvent variants change lengths only a little and
    are not modelled here."""
    from .protocol import make_protocol, RESTRAINT_STRATEGIES
    md = (cfg or {}).get("md") or {}
    restraints = md.get("restraints") or "standard"
    if restraints not in RESTRAINT_STRATEGIES:
        restraints = "standard"
    proto = make_protocol(md.get("tier", "teaching"), production_ns=md.get("production_ns"), restraints=restraints)
    npt_factor = float(RESTRAINT_STRATEGIES[restraints].get("npt_length_factor", 1.0))
    for st in proto.stages:
        ov = (md.get("stage_overrides") or {}).get(st.name) or {}
        if "length_ps" in ov:
            st.length_ps = float(ov["length_ps"]) * npt_factor if st.name == "npt" else float(ov["length_ps"])
    prod = next((s for s in proto.stages if s.name == "production"), proto.stages[-1])
    return proto.total_ns(), float(prod.timestep_fs)


def estimate_md_hours(cfg: dict | None, n: int, systems: int, *, benchmark: dict | None = None,
                      n_atoms: int | None = None) -> tuple[float | None, str | None]:
    """(hours of the molecular-dynamics part for n replicas, basis).  None without a speed: the time is not guessed.
    Speed: `md.ns_per_day` (measured for this system) -> the doctor benchmark scaled to `n_atoms` -> the benchmark
    as it is (basis "benchmark_size": the real system may be larger or smaller)."""
    md = (cfg or {}).get("md") or {}
    ns, dt = md_ns_per_replica(cfg)
    speed, basis = None, None
    if md.get("ns_per_day"):
        speed, basis = float(md["ns_per_day"]), "config"
    else:
        bench = benchmark or md.get("benchmark") or {}
        if bench.get("ns_per_day"):
            from .longrun import scaled_ns_per_day
            if n_atoms:
                speed, basis = scaled_ns_per_day(bench, int(n_atoms), dt), "benchmark"
            else:
                speed, basis = scaled_ns_per_day(bench, int(bench.get("n_atoms") or 24000), dt), "benchmark_size"
    if not speed or speed <= 0:
        return None, None
    return ns * max(1, systems) * max(1, int(n)) / speed * 24.0, basis


def format_hours(h: float, lang: str = "zh") -> str:
    if h < 1.0:
        m = max(1, int(round(h * 60)))
        return pick((f"{m} 分鐘", f"{m} min", f"{m} 分", f"{m}분"), lang)
    if h < 48.0:
        return pick((f"{h:.1f} 小時", f"{h:.1f} h", f"{h:.1f} 時間", f"{h:.1f}시간"), lang)
    d = h / 24.0
    return pick((f"{d:.1f} 天", f"{d:.1f} days", f"{d:.1f} 日", f"{d:.1f}일"), lang)


# ------------------------------------------------------------------------------------------------ plan
def plan_replicas(cfg: dict | None, *, benchmark: dict | None = None, n_atoms: int | None = None,
                  built_keys: list[str] | None = None, done: dict | None = None) -> dict:
    """The replica plan of a workflow config.

    `benchmark`: the doctor benchmark ({"ns_per_day", "n_atoms", "timestep_fs"}) when this computer has one.
    `n_atoms`: atoms of the built system when known.  `done`: {system key: replicas already complete}.
    Returns a JSON-able dict; `lines(plan, lang)` turns it into text."""
    cfg = cfg or {}
    md = cfg.get("md") or {}
    required = required_replicas()
    n, explicit = configured_replicas(cfg)
    systems = count_systems(cfg, built_keys)
    cg = md.get("resolution") == "cg"
    done = {k: int(v) for k, v in (done or {}).items()}
    missing = {k: max(0, n - d) for k, d in done.items() if d < n}
    hours = basis = None
    if not cg:
        hours, basis = estimate_md_hours(cfg, n, systems, benchmark=benchmark, n_atoms=n_atoms)
    plan = {
        "applicable": not cg, "required": required, "configured": n, "explicit": explicit,
        "multiplier": n, "single": n == 1, "below_required": n < required,
        "systems": systems, "eta_hours": None if hours is None else round(hours, 2), "eta_basis": basis,
        "base_seed": DEFAULT_SEED, "seeds": seeds_for(n), "done": done, "missing": missing,
        "topup_runs": sum(missing.values()),
        "topup_to_required": sum(max(0, required - d) for d in done.values()),
        "analysis_min": dict(ANALYSIS_MIN_REPLICAS),
    }
    plan["options"] = _options(plan)
    return plan


def _options(p: dict) -> list[dict]:
    r, n = p["required"], p["configured"]
    gap = sum(max(0, r - d) for d in p["done"].values())          # old project: replicas missing for the advised number
    done_total = sum(p["done"].values())
    opts = [
        {"id": "recommended", "replicas": r,
         "label": (f"照建議，每個系統 {r} 條", f"Follow the advice: {r} replicas per system",
                   f"推奨どおり、系ごとに {r} 回", f"권장대로 계 하나당 {r}회"),
         "note": (f"時間約為 1 條的 {r} 倍。報告可以呈現平均與標準差。",
                  f"About {r} times the time of one. The report can show means and standard deviations.",
                  f"時間は 1 回の約 {r} 倍です。レポートに平均と標準偏差を載せられます。",
                  f"시간은 1회의 약 {r}배입니다. 보고서에 평균과 표준편차를 담을 수 있습니다.")},
        {"id": "single", "replicas": 1,
         "label": ("改為 1 條", "Use 1 replica", "1 回にする", "1회로 변경"),
         "note": ("時間最短。報告每一處都標「單一軌跡，無法估計不確定性」，比較結論降級為描述。",
                  "Shortest time. The report marks every place \"single trajectory, uncertainty cannot be estimated\" and "
                  "comparisons are described, not concluded.",
                  "時間は最短です。レポートの各所に「単一軌跡、不確かさは推定できません」と表示し、比較は記述にとどめます。",
                  "시간이 가장 짧습니다. 보고서 곳곳에 '단일 궤적, 불확도를 추정할 수 없음'이라고 표시하고 비교는 서술에 그칩니다.")},
        {"id": "custom", "replicas": None,
         "label": ("自訂條數", "Choose a number", "回数を指定", "횟수 지정"),
         "note": ("在設定裡寫 md.replicas。可以大於 3，例如發表等級用 5。",
                  "Set md.replicas in the settings. It can be more than 3, for example 5 for publication.",
                  "設定に md.replicas を書きます。3 より大きくでき、論文発表では 5 などにします。",
                  "설정에 md.replicas를 씁니다. 3보다 크게 할 수 있으며 논문 발표에는 예를 들어 5로 합니다.")},
    ]
    if gap > 0 and p["topup_runs"] == 0:
        # finished (or started) with fewer than advised and the config does not ask for more yet: the advised option is the
        # top-up.  Same resume mechanism, only the missing replicas run.
        opts[0] = {"id": "recommended", "replicas": r,
                   "label": (f"補跑到 {r} 條", f"Top up to {r} replicas", f"{r} 回まで追加", f"{r}회까지 추가 실행"),
                   "note": (f"已完成 {done_total} 條，只補跑缺的 {gap} 條，不重算已有的。分析與報告會重做。",
                            f"{done_total} replica(s) are complete. Only the {gap} missing one(s) run and nothing is recomputed. "
                            "The analysis and report are redone.",
                            f"{done_total} 回は完了しています。不足の {gap} 回だけを計算し、既存の結果は再計算しません。解析とレポートは作り直します。",
                            f"{done_total}회는 끝났습니다. 부족한 {gap}회만 실행하며 이미 있는 것은 다시 계산하지 않습니다. 분석과 보고서는 다시 만듭니다.")}
    if p["topup_runs"] > 0:
        k = p["topup_runs"]
        opts.append({"id": "topup", "replicas": n,
                     "label": (f"補跑 {k} 條", f"Run the {k} missing replica(s)", f"不足の {k} 回を追加", f"부족한 {k}회 추가 실행"),
                     "note": (f"已完成 {done_total} 條，只跑缺的 {k} 條，不重算已有的。",
                              f"{done_total} replica(s) are complete. Only the {k} missing one(s) run, nothing is recomputed.",
                              f"{done_total} 回は完了しています。足りない {k} 回だけを計算し、既存の結果は再計算しません。",
                              f"{done_total}회는 끝났습니다. 부족한 {k}회만 실행하며 이미 있는 것은 다시 계산하지 않습니다.")})
    return opts


# ------------------------------------------------------------------------------------------------ text
def _eta_phrase(p: dict) -> tuple:
    h = p["eta_hours"]
    if h is None:
        return ("這台電腦還沒做效能測試，所以只給倍數，不猜時間。",
                "This computer has no benchmark yet, so only the factor is given and the time is not guessed.",
                "このパソコンはまだベンチマークをしていないため、倍率だけを示し、時間は推測しません。",
                "이 컴퓨터는 아직 성능 테스트를 하지 않아 배수만 알려 드리고 시간은 추측하지 않습니다.")
    zh, en, ja, ko = (format_hours(h, "zh"), format_hours(h, "en"), format_hours(h, "ja"), format_hours(h, "ko"))
    near = p["eta_basis"] == "benchmark_size"
    return (f"分子動力學部分依這台電腦的效能測試估計約 {zh}" + ("（以測試系統的大小計算，建模後會更準）。" if near else "。"),
            f"The molecular dynamics part is estimated at about {en} from this computer's benchmark" +
            (" (for the size of the test system, more accurate once the system is built)." if near else "."),
            f"分子動力学の部分は、このパソコンのベンチマークから約 {ja} と見積もっています" +
            ("（テスト系の大きさで計算しており、系の構築後に精度が上がります）。" if near else "。"),
            f"분자동역학 부분은 이 컴퓨터의 성능 테스트로 약 {ko}로 추정합니다" +
            ("(테스트 계의 크기 기준이며 계를 구축한 뒤에 더 정확해집니다)." if near else "."))


def independence_text(p: dict) -> tuple:
    """How the replicas differ and where each one starts: the facts of `run_replicas`, not a promise (§5)."""
    s = p["seeds"][:6] or seeds_for(p["required"])
    seeds = ", ".join(str(x) for x in s) + (" …" if len(p["seeds"]) > 6 else "")
    b = p["base_seed"]
    return (f"每條的亂數 seed 是 {b} 加 {SEED_STRIDE} 乘條序（{seeds}）。每條都從同一個建好的系統開始，各自做最小化、加熱與平衡，"
            "初速由各自的 seed 產生，不是從同一個平衡後的結構分出去。",
            f"The random seed of replica i is {b} + {SEED_STRIDE} × i ({seeds}). Every replica starts from the same built system "
            "and does its own minimisation, heating and equilibration, with velocities drawn from its own seed. They do not "
            "branch from one equilibrated structure.",
            f"各反復の乱数シードは {b} + {SEED_STRIDE} × 番号です（{seeds}）。どの反復も同じ構築済みの系から始まり、"
            "それぞれが最小化、加熱、平衡化を行い、初速度は各自のシードで決まります。平衡化後の同じ構造から分岐させてはいません。",
            f"각 반복의 난수 시드는 {b} + {SEED_STRIDE} × 번호입니다({seeds}). 모든 반복은 같은 구축된 계에서 시작해 "
            "각자 최소화, 가열, 평형화를 하며 초기 속도는 각자의 시드로 정해집니다. 평형화된 같은 구조에서 갈라지지 않습니다.")


def summary_text(p: dict) -> tuple:
    """The plan in a few sentences (the full form, shown when the config does not set md.replicas)."""
    if not p["applicable"]:
        return ("粗粒化目前每個系統只跑 1 條，還沒有獨立重複。報告會標「單一軌跡，無法估計不確定性」。",
                "Coarse-grained runs one trajectory per system for now and has no independent replicas. The report marks "
                "\"single trajectory, uncertainty cannot be estimated\".",
                "粗視化は今のところ系ごとに 1 本だけ計算し、独立した反復はありません。レポートに「単一軌跡、不確かさは推定できません」と表示します。",
                "조잡화(CG)는 현재 계 하나당 궤적 1개만 계산하며 독립 반복이 없습니다. 보고서에 '단일 궤적, 불확도를 추정할 수 없음'이라고 표시합니다.")
    n, r, k = p["configured"], p["required"], p["systems"]
    eta = _eta_phrase(p)
    head = (f"為了讓報告能呈現不確定性，每個系統要跑 {r} 條獨立重複（共 {k} 個系統）。計算時間約為 1 條的 {r} 倍。",
            f"To let the report show uncertainty, every system needs {r} independent replicas ({k} system(s)). "
            f"The calculation takes about {r} times as long as one.",
            f"レポートに不確かさを示すため、各系で独立した反復が {r} 回必要です（{k} 系）。計算時間は 1 回の約 {r} 倍です。",
            f"보고서에 불확도를 담기 위해 계마다 독립 반복 {r}회가 필요합니다({k}개 계). 계산 시간은 1회의 약 {r}배입니다.")
    return tuple(f"{h} {e}" for h, e in zip(head, eta))


def line_text(p: dict) -> tuple:
    """One line: what the config sets and what that means (shown when the user wrote md.replicas)."""
    if not p["applicable"]:
        return summary_text(p)
    n, r = p["configured"], p["required"]
    src = ("設定指定", "set in the settings", "設定で指定", "설정에서 지정")
    if p["explicit"] is False:
        src = ("預設", "default", "既定", "기본값")
    eta = p["eta_hours"]
    t = ((f"約 {format_hours(eta, 'zh')}" if eta is not None else "時間未估"),
         (f"about {format_hours(eta, 'en')}" if eta is not None else "time not estimated"),
         (f"約 {format_hours(eta, 'ja')}" if eta is not None else "時間は未見積もり"),
         (f"약 {format_hours(eta, 'ko')}" if eta is not None else "시간 미추정"))
    if n == 1:
        return (f"重複：每個系統 1 條（{src[0]}），{t[0]}。報告每一處會標「單一軌跡，無法估計不確定性」。",
                f"Replicas: 1 per system ({src[1]}), {t[1]}. The report marks every place \"single trajectory, uncertainty "
                "cannot be estimated\".",
                f"反復：系ごとに 1 回（{src[2]}）、{t[2]}。レポートの各所に「単一軌跡、不確かさは推定できません」と表示します。",
                f"반복: 계 하나당 1회({src[3]}), {t[3]}. 보고서 곳곳에 '단일 궤적, 불확도를 추정할 수 없음'이라고 표시합니다.")
    low = n < r
    tail = (("，少於建議的 %d 條，報告會逐處標註實際條數。" % r) if low else "。",
            (f", fewer than the {r} advised, so the report states the real number everywhere." if low else "."),
            (f"。推奨の {r} 回より少ないため、レポートは実際の回数を各所に明記します。" if low else "。"),
            (f". 권장 {r}회보다 적어 보고서가 실제 횟수를 곳곳에 밝힙니다." if low else "."))
    return (f"重複：每個系統 {n} 條（{src[0]}），時間約為 1 條的 {n} 倍，{t[0]}{tail[0]}",
            f"Replicas: {n} per system ({src[1]}), about {n} times the time of one, {t[1]}{tail[1]}",
            f"反復：系ごとに {n} 回（{src[2]}）、時間は 1 回の約 {n} 倍、{t[2]}{tail[2]}",
            f"반복: 계 하나당 {n}회({src[3]}), 시간은 1회의 약 {n}배, {t[3]}{tail[3]}")


def topup_text(p: dict) -> tuple | None:
    """For a project that already finished with fewer replicas than the config asks for."""
    if not p["topup_runs"]:
        return None
    k, n = p["topup_runs"], p["configured"]
    d = ", ".join(f"{key}: {v}/{n}" for key, v in sorted(p["done"].items()) if v < n)
    return (f"已完成的重複少於 {n} 條（{d}）。可以補跑缺的 {k} 條，已有的不重算。",
            f"Fewer than {n} replicas are complete ({d}). The {k} missing one(s) can be run, and the existing ones are not recomputed.",
            f"完了した反復が {n} 回に足りません（{d}）。不足の {k} 回を追加で計算でき、既存の結果は再計算しません。",
            f"끝난 반복이 {n}회보다 적습니다({d}). 부족한 {k}회를 추가로 실행할 수 있으며 이미 있는 것은 다시 계산하지 않습니다.")


def lines(p: dict, lang: str = "zh", *, full: bool | None = None, with_options: bool = True) -> list[str]:
    """Text for the CLI and the GUI card.  `full` (default: when the config does not set md.replicas) adds the
    explanation, the seeds and the options; otherwise one line (plus the top-up hint when it applies).
    `with_options=False`: the GUI shows the options as buttons."""
    full = (not p["explicit"]) if full is None else full
    out: list[str] = []
    if full and p["applicable"]:
        out.append(pick(summary_text(p), lang))
        out.append(pick(independence_text(p), lang))
        if with_options:
            ordered = [o for o in p["options"] if o["id"] != "custom"] + [o for o in p["options"] if o["id"] == "custom"]
            for o in ordered:
                out.append("• " + pick(o["label"], lang) + " — " + pick(o["note"], lang))
    else:
        out.append(pick(line_text(p), lang))
    tu = topup_text(p)
    if tu:
        out.append(pick(tu, lang))
    return out


def card_lines(p: dict, lang: str = "zh") -> list[str]:
    """The lines of the GUI card: what is set now (and what it costs), then how the replicas differ."""
    out = [pick(line_text(p) if p["explicit"] else summary_text(p), lang)]
    if p["applicable"]:
        out.append(pick(independence_text(p), lang))
    tu = topup_text(p)
    if tu:
        out.append(pick(tu, lang))
    return out


def single_command_text(replicas: int = 1) -> tuple:
    """`md20 run` starts one trajectory of one case (it is not a workflow).  Say so, and where the replicas are."""
    r = required_replicas()
    return (f"重複：這個指令只跑 1 條軌跡（{replicas} 條），報告會標「單一軌跡，無法估計不確定性」。需要 {r} 條獨立重複時，"
            f"用 md20 pipeline run（預設每個系統 {r} 條），或 md20 queue add --replicas {r}。",
            f"Replicas: this command runs one trajectory, and the report marks \"single trajectory, uncertainty cannot be "
            f"estimated\". For {r} independent replicas use md20 pipeline run (default {r} per system) or md20 queue add "
            f"--replicas {r}.",
            f"反復：このコマンドは軌跡を 1 本だけ計算し、レポートに「単一軌跡、不確かさは推定できません」と表示します。独立した反復が "
            f"{r} 回必要なときは md20 pipeline run（既定は系ごとに {r} 回）か md20 queue add --replicas {r} を使ってください。",
            f"반복: 이 명령은 궤적 1개만 계산하며 보고서에 '단일 궤적, 불확도를 추정할 수 없음'이라고 표시합니다. 독립 반복 {r}회가 "
            f"필요하면 md20 pipeline run(기본 계 하나당 {r}회) 또는 md20 queue add --replicas {r}를 사용하십시오.")


def decision_why(p: dict) -> str:
    """Chinese reason for the DecisionLog."""
    n, r = p["configured"], p["required"]
    if not p["applicable"]:
        return "粗粒化目前每個系統只跑 1 條，沒有獨立重複；報告標註單一軌跡，無法估計不確定性。"
    how = "使用者在設定裡指定" if p["explicit"] else f"設定沒有指定，採用預設 {r} 條"
    eta = (f"；依效能測試，分子動力學部分約 {format_hours(p['eta_hours'], 'zh')}" if p["eta_hours"] is not None
           else "；這台電腦沒有效能測試，只給倍數，不猜時間")
    base = (f"{how}：每個系統 {n} 條獨立重複（需要重複的分析最少 {r} 條，取最大值），計算時間約為 1 條的 {n} 倍{eta}。"
            f"每條 seed = {p['base_seed']} + {SEED_STRIDE}×條序，各自從同一個建好的系統做最小化、加熱與平衡。")
    if n == 1:
        base += "只有 1 條：報告每一處標「單一軌跡，無法估計不確定性」，比較結論降級為描述。"
    elif n < r:
        base += f"少於 {r} 條：報告逐處標註實際條數，結論降級。"
    return base
