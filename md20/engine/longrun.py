"""Long production runs (microseconds and beyond): time, disk and checkpoint plan, and the gate before starting.

docs/specs/long_timescale.md §2.  Pure Python: the numbers are arithmetic on atom counts, the measured speed and the
requested length, so the plan is tested everywhere and the GUI can show it while the user types.

    plan = plan_long_run(n_atoms=32000, production_ns=2000, ns_per_day=330, disk_free_gb=250, n_solute_atoms=3300)
    plan.status            # PASS | AUTO_FIXED | NEEDS_HUMAN
    plan.stage_overrides   # {"production": {"trajectory_interval_ps": …, "report_interval_ps": …, …}}
    apply_plan(protocol, plan)

What it decides:
* trajectory save interval so the production DCD stays under `target_gb` (default 20 GB), optionally solute only;
* StateData log interval so the log stays under about 250 000 rows (acceptance reads the whole log into memory);
* chunk (checkpoint) length: each chunk keeps its own State XML and checkpoint, so a 1 µs run with the 200 ps
  default leaves 5000 of them; the chunk is lengthened to at most MAX_CHUNKS chunks, but never above one hour of
  computing, so a crash loses at most one hour;
* gates: longer than 1 µs needs `md.long_run_confirmed: true`; longer than 10 µs is refused; not enough disk space
  blocks with options.  Nothing here starts or changes a run that is already in progress: the plan becomes part of
  the protocol (and its hash) before the first step.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

CONFIRM_ABOVE_NS = 1000.0          # > 1 µs: the user confirms days of computing and the disk use
MAX_PRODUCTION_NS = 10000.0        # professional-mode limit (advisor.PARAMS["production_ns"]["max"])
PLAN_ABOVE_NS = 100.0              # the research tier default; at or below this the protocol is left as it is
DEFAULT_TARGET_GB = 20.0
MAX_CHUNKS = 500
MAX_CHUNK_WALL_HOURS = 1.0
MAX_LOG_ROWS = 250_000
SPARSE_FRAME_PS = 100.0            # a full-system save interval above this triggers solute-only (auto mode)
MAX_FRAME_PS = 1000.0
INTERVAL_LADDER_PS = (1, 2, 5, 10, 20, 50, 100, 200, 250, 500, 1000, 2000, 5000)
# disk per chunk: OpenMM State XML (positions + velocities as text) plus the binary checkpoint.  Estimated, not
# measured on the laptop yet (spec §6): about 150 + 90 bytes per atom.
STATE_BYTES_PER_ATOM = 240
KEEP_CHUNK_STATES = 3              # newest chunk states kept on disk in a planned run (StageSpec.keep_chunk_states)
LOG_BYTES_PER_ROW = 160
DISK_MARGIN = 1.2                  # needed space × 1.2 must fit in the free space
GB = 1e9

# residues left out of a solute-only trajectory: water and the monovalent counter-ions the build adds.  Structural
# metals (ZN, MG, CA, FE …) stay: they belong to the protein.
WATER_RESNAMES = frozenset({"HOH", "WAT", "TIP3", "TIP4", "TIP5", "SPC", "SOL", "T3P", "T4P", "H2O"})
COUNTER_ION_RESNAMES = frozenset({"NA", "CL", "K", "LI", "RB", "CS", "BR", "F", "I", "NA+", "CL-", "K+", "SOD", "CLA",
                                  "POT"})


def dcd_frame_bytes(n_atoms: int, unit_cell: bool = True) -> int:
    """One DCD frame as OpenMM writes it: an optional 48-byte unit-cell record and three Fortran records of float32
    coordinates, each with 4-byte markers before and after."""
    return (56 if unit_cell else 0) + 3 * (4 * int(n_atoms) + 8)


def solute_atom_indices(residue_names: list[str]) -> list[int]:
    """Atom indices kept in a solute-only trajectory, from the residue name of each atom (in atom order).  The same
    rule is applied by the OpenMM backend when writing and by the analysis when reading, so both agree."""
    return [i for i, rn in enumerate(residue_names)
            if rn.strip().upper() not in WATER_RESNAMES and rn.strip().upper() not in COUNTER_ION_RESNAMES]


def scaled_ns_per_day(bench: dict | None, n_atoms: int, timestep_fs: float) -> float | None:
    """Doctor benchmark → expected speed for this system (linear in atoms and timestep, as advisor.estimate_hours)."""
    if not bench or not bench.get("ns_per_day"):
        return None
    b_atoms = int(bench.get("n_atoms") or 24000)
    b_dt = float(bench.get("timestep_fs") or 4.0)
    return float(bench["ns_per_day"]) * (float(timestep_fs) / b_dt) * (b_atoms / max(int(n_atoms), 1000))


def _ladder_at_least(x: float, floor: float) -> float:
    for v in INTERVAL_LADDER_PS:
        if v >= x and v >= floor:
            return float(v)
    return float(max(INTERVAL_LADDER_PS[-1], math.ceil(max(x, floor))))


def _fs(ps: float) -> int:
    return max(1, int(round(ps * 1000)))


@dataclass
class LongRunPlan:
    status: str                         # PASS | AUTO_FIXED | NEEDS_HUMAN
    production_ns: float
    n_atoms: int
    saved_atoms: int
    solute_only: bool
    timestep_fs: float
    ns_per_day: float | None            # scaled to this system; None = no benchmark
    days: float | None
    trajectory_interval_ps: float
    report_interval_ps: float
    checkpoint_interval_ps: float
    n_frames: int
    n_chunks: int
    chunk_wall_minutes: float | None
    trajectory_gb: float
    states_gb: float
    log_gb: float
    total_gb: float                     # all replicas
    disk_free_gb: float | None
    replicas: int = 1
    keep_chunk_states: int = 0
    issues: list = field(default_factory=list)       # [{"code", "level", "zh", "text": (zh,en,ja,ko), "options": [...]}]
    decisions: list = field(default_factory=list)    # [{"what", "choice", "why", "kind"}] (why in Chinese)
    stage_overrides: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def blocked(self) -> bool:
        return self.status == "NEEDS_HUMAN"

    def message_zh(self) -> str:
        return " ".join(i["zh"] for i in self.issues if i["level"] == "block")

    def options(self) -> list[str]:
        out: list[str] = []
        for i in self.issues:
            if i["level"] == "block":
                out += [o for o in i.get("options", []) if o not in out]
        return out


def plan_long_run(*, n_atoms: int, production_ns: float, timestep_fs: float = 4.0, ns_per_day: float | None = None,
                  bench: dict | None = None, n_solute_atoms: int | None = None, solute_only: bool | None = None,
                  target_gb: float = DEFAULT_TARGET_GB, disk_free_gb: float | None = None, confirmed: bool = False,
                  replicas: int = 1, base_trajectory_ps: float = 20.0, base_report_ps: float = 2.0,
                  base_checkpoint_ps: float = 200.0, unit_cell: bool = True,
                  keep_chunk_states: int = KEEP_CHUNK_STATES) -> LongRunPlan:
    """Plan one production stage of `production_ns` (per replica).  `ns_per_day` is the speed for *this* system;
    without it `bench` (the doctor benchmark) is scaled.  `solute_only`: True / False / None (decide: only when the
    full system would need frames sparser than SPARSE_FRAME_PS and the solute atom count is known)."""
    n_atoms = int(n_atoms)
    prod_ns = float(production_ns)
    prod_ps = prod_ns * 1000.0
    replicas = max(1, int(replicas))
    speed = float(ns_per_day) if ns_per_day else scaled_ns_per_day(bench, n_atoms, timestep_fs)
    issues: list[dict] = []
    decisions: list[dict] = []
    target = float(target_gb)

    def need_interval(atoms: int) -> float:
        return prod_ps * dcd_frame_bytes(atoms, unit_cell) / (target * GB)

    # ---- trajectory interval and atom subset
    full_need = need_interval(n_atoms)
    solute_ok = bool(n_solute_atoms) and 0 < int(n_solute_atoms) < n_atoms
    if solute_only is None:
        use_solute = solute_ok and _ladder_at_least(full_need, base_trajectory_ps) > SPARSE_FRAME_PS
        if use_solute:
            decisions.append({"what": "trajectory_atoms", "choice": "solute", "kind": "auto_fixed",
                              "why": f"全系統 {n_atoms:,} 個原子要壓在 {target:g} GB 以內，存檔間隔得拉到 "
                                     f"{_ladder_at_least(full_need, base_trajectory_ps):g} ps 以上，太稀疏不利於接觸頻率與動態分析；"
                                     f"改為只存溶質（{int(n_solute_atoms):,} 個原子，不含水與反離子）。"})
    else:
        use_solute = bool(solute_only) and solute_ok
        if solute_only and not solute_ok:
            issues.append(_issue("solute_unknown", "warn",
                                 "要求只存溶質，但不知道溶質原子數（或系統全是溶質），仍存全系統。",
                                 ("要求只存溶質，但不知道溶質的原子數，所以仍存全系統。",
                                  "Solute-only saving was requested, but the solute atom count is unknown, so the whole "
                                  "system is saved.",
                                  "溶質だけの保存が指定されましたが、溶質の原子数が不明なため系全体を保存します。",
                                  "용질만 저장하도록 했지만 용질 원자 수를 알 수 없어 전체 계를 저장합니다.")))
    saved = int(n_solute_atoms) if use_solute else n_atoms
    traj_ps = _ladder_at_least(need_interval(saved), base_trajectory_ps)
    if traj_ps > MAX_FRAME_PS:
        traj_ps = MAX_FRAME_PS
    if traj_ps != base_trajectory_ps:
        decisions.append({"what": "trajectory_interval_ps", "choice": traj_ps, "kind": "auto_fixed",
                          "why": f"正式模擬 {prod_ns:g} ns、每幀 {dcd_frame_bytes(saved, unit_cell) / 1e6:.2f} MB；每 "
                                 f"{base_trajectory_ps:g} ps 存一幀會超過 {target:g} GB，改為每 {traj_ps:g} ps 存一幀。"})
    n_frames = int(prod_ps // traj_ps)
    traj_gb = n_frames * dcd_frame_bytes(saved, unit_cell) / GB
    if traj_gb > target * 1.0001:
        issues.append(_issue("trajectory_too_large", "block",
                             f"即使每 {MAX_FRAME_PS:g} ps 存一幀，軌跡仍約 {traj_gb:.1f} GB，超過上限 {target:g} GB。",
                             (f"即使每 {MAX_FRAME_PS:g} ps 存一幀，軌跡仍約 {traj_gb:.1f} GB，超過上限 {target:g} GB。",
                              f"Even with one frame every {MAX_FRAME_PS:g} ps the trajectory is about {traj_gb:.1f} GB, "
                              f"over the {target:g} GB limit.",
                              f"{MAX_FRAME_PS:g} ps ごとに 1 フレームでも、トラジェクトリは約 {traj_gb:.1f} GB で上限 "
                              f"{target:g} GB を超えます。",
                              f"{MAX_FRAME_PS:g} ps마다 한 프레임을 저장해도 궤적이 약 {traj_gb:.1f} GB로 상한 "
                              f"{target:g} GB를 넘습니다."),
                             options=_space_options(use_solute, solute_ok, raise_to_gb=traj_gb)))

    # ---- log interval
    report_ps = _ladder_at_least(prod_ps / MAX_LOG_ROWS, base_report_ps)
    if report_ps != base_report_ps:
        decisions.append({"what": "report_interval_ps", "choice": report_ps, "kind": "auto_fixed",
                          "why": f"每 {base_report_ps:g} ps 記錄一次會有 {prod_ps / base_report_ps:,.0f} 筆，驗收時要整份讀進記憶體；"
                                 f"改為每 {report_ps:g} ps 一筆（約 {prod_ps / report_ps:,.0f} 筆）。"})

    # ---- chunk (checkpoint) length: a multiple of both intervals so frames stay evenly spaced across chunks
    unit_fs = math.lcm(_fs(traj_ps), _fs(report_ps))
    unit_ps = unit_fs / 1000.0
    want = max(base_checkpoint_ps, prod_ps / MAX_CHUNKS)
    wall_cap_ps = speed * 1000.0 * MAX_CHUNK_WALL_HOURS / 24.0 if speed else None
    if wall_cap_ps is not None and want > wall_cap_ps:
        want = max(base_checkpoint_ps, wall_cap_ps)
    chunk_ps = max(unit_ps, math.floor(want / unit_ps + 1e-9) * unit_ps)
    n_chunks = max(1, math.ceil(prod_ps / chunk_ps))
    chunk_wall_min = (chunk_ps / 1000.0) / speed * 24 * 60 if speed else None
    if chunk_ps != base_checkpoint_ps:
        why = (f"每個 chunk 都保留一份 State 與 checkpoint（約 {n_atoms * STATE_BYTES_PER_ATOM / 1e6:.1f} MB）；"
               f"每 {base_checkpoint_ps:g} ps 一段會有 {math.ceil(prod_ps / base_checkpoint_ps):,} 段。改為每 {chunk_ps:g} ps 一段"
               f"（{n_chunks:,} 段")
        why += f"，每段約 {chunk_wall_min:.0f} 分鐘，當機最多損失一段）。" if chunk_wall_min is not None else "）。"
        decisions.append({"what": "checkpoint_interval_ps", "choice": chunk_ps, "kind": "auto_fixed", "why": why})
    keep = max(0, int(keep_chunk_states))
    if keep and n_chunks > keep:
        decisions.append({"what": "keep_chunk_states", "choice": keep, "kind": "auto_fixed",
                          "why": f"{n_chunks:,} 個 chunk 各留一份 State 與 checkpoint 要 "
                                 f"{n_chunks * n_atoms * STATE_BYTES_PER_ATOM / GB:.1f} GB；續跑只需要最新的，"
                                 f"改為只保留最新 {keep} 個（軌跡與紀錄檔全部保留）。"})
    else:
        keep = 0
    states_gb = (min(n_chunks, keep + 1) if keep else n_chunks) * n_atoms * STATE_BYTES_PER_ATOM / GB
    log_gb = (prod_ps / report_ps) * LOG_BYTES_PER_ROW / GB
    total_gb = (traj_gb + states_gb + log_gb) * replicas
    days = prod_ns * replicas / speed if speed else None

    # ---- gates
    if prod_ns > MAX_PRODUCTION_NS:
        issues.append(_issue("too_long", "block",
                             f"正式模擬 {prod_ns:g} ns 超過專業模式上限 {MAX_PRODUCTION_NS:g} ns（10 µs）。",
                             (f"正式模擬 {prod_ns:g} ns 超過專業模式的上限 {MAX_PRODUCTION_NS:g} ns（10 µs）。",
                              f"A production of {prod_ns:g} ns is over the professional-mode limit of "
                              f"{MAX_PRODUCTION_NS:g} ns (10 µs).",
                              f"本計算 {prod_ns:g} ns はプロフェッショナルモードの上限 {MAX_PRODUCTION_NS:g} ns（10 µs）を"
                              "超えています。",
                              f"본 계산 {prod_ns:g} ns는 전문가 모드 상한 {MAX_PRODUCTION_NS:g} ns(10 µs)를 넘습니다."),
                             options=[f"md.production_ns: {MAX_PRODUCTION_NS:g}（縮短到上限）",
                                      "改用粗粒化 Martini 3（md20 setup-cg，見 docs/specs/long_timescale.md §3）"]))
    elif prod_ns > CONFIRM_ABOVE_NS and not confirmed:
        when_zh = f"估計約 {days:.1f} 天" if days is not None else "這台電腦還沒做效能測試，無法估計天數"
        when = ((f"估計約 {days:.1f} 天", f"about {days:.1f} days", f"約 {days:.1f} 日", f"약 {days:.1f}일")
                if days is not None else
                ("這台電腦還沒做效能測試，無法估計天數", "no benchmark on this computer, so the days cannot be estimated",
                 "このコンピュータはベンチマーク未実行のため日数を見積もれません",
                 "이 컴퓨터에서 벤치마크를 하지 않아 일수를 추정할 수 없습니다"))
        issues.append(_issue("confirm_long", "block",
                             f"正式模擬 {prod_ns:g} ns 超過 1 µs：{when_zh}，硬碟約需 {total_gb:.1f} GB"
                             f"（{replicas} 份）。請確認後再開始。",
                             (f"正式模擬 {prod_ns:g} ns 超過 1 µs。{when[0]}，硬碟約需 {total_gb:.1f} GB（{replicas} 份）。"
                              "請確認後再開始。",
                              f"A production of {prod_ns:g} ns is longer than 1 µs: {when[1]}, and about "
                              f"{total_gb:.1f} GB of disk ({replicas} replica(s)). Confirm before it starts.",
                              f"本計算 {prod_ns:g} ns は 1 µs を超えます。{when[2]}、ディスクは約 {total_gb:.1f} GB"
                              f"（{replicas} 回分）必要です。確認してから開始してください。",
                              f"본 계산 {prod_ns:g} ns는 1 µs를 넘습니다. {when[3]}, 디스크는 약 {total_gb:.1f} GB"
                              f"({replicas}회분) 필요합니다. 확인한 뒤 시작하십시오."),
                             options=["md.long_run_confirmed: true（確認天數與硬碟用量，開始）",
                                      f"md.production_ns: {CONFIRM_ABOVE_NS:g}（縮短到 1 µs）"]))
    if disk_free_gb is not None and total_gb * DISK_MARGIN > float(disk_free_gb):
        issues.append(_issue("disk", "block",
                             f"硬碟剩 {float(disk_free_gb):.1f} GB，這次模擬約需 {total_gb:.1f} GB（含 {DISK_MARGIN:g} 倍餘裕要 "
                             f"{total_gb * DISK_MARGIN:.1f} GB）。",
                             (f"硬碟剩 {float(disk_free_gb):.1f} GB，這次模擬約需 {total_gb:.1f} GB，加上餘裕要 "
                              f"{total_gb * DISK_MARGIN:.1f} GB。",
                              f"{float(disk_free_gb):.1f} GB of disk is free. This run needs about {total_gb:.1f} GB, "
                              f"{total_gb * DISK_MARGIN:.1f} GB with the safety margin.",
                              f"ディスクの空きは {float(disk_free_gb):.1f} GB です。この計算には約 {total_gb:.1f} GB、余裕を"
                              f"含めて {total_gb * DISK_MARGIN:.1f} GB 必要です。",
                              f"디스크 여유 공간은 {float(disk_free_gb):.1f} GB입니다. 이 계산에는 약 {total_gb:.1f} GB, "
                              f"여유분을 포함하면 {total_gb * DISK_MARGIN:.1f} GB가 필요합니다."),
                             options=_space_options(use_solute, solute_ok, fit_gb=(float(disk_free_gb) / DISK_MARGIN / replicas
                                                                                   - states_gb - log_gb))))
    elif disk_free_gb is None:
        issues.append(_issue("disk_unknown", "info", "無法讀取剩餘磁碟空間，未檢查。",
                             ("無法讀取剩餘的磁碟空間，所以沒有檢查。", "The free disk space could not be read, so it was not checked.",
                              "ディスクの空き容量を読み取れなかったため、確認していません。",
                              "디스크 여유 공간을 읽지 못해 확인하지 않았습니다.")))

    overrides = {}
    for key, value, base in (("trajectory_interval_ps", traj_ps, base_trajectory_ps),
                             ("report_interval_ps", report_ps, base_report_ps),
                             ("checkpoint_interval_ps", chunk_ps, base_checkpoint_ps)):
        if value != base:
            overrides[key] = float(value)
    if use_solute:
        overrides["trajectory_atoms"] = "solute"
    if keep:
        overrides["keep_chunk_states"] = keep
    status = "NEEDS_HUMAN" if any(i["level"] == "block" for i in issues) else ("AUTO_FIXED" if decisions else "PASS")
    return LongRunPlan(status=status, production_ns=prod_ns, n_atoms=n_atoms, saved_atoms=saved, solute_only=use_solute,
                       timestep_fs=float(timestep_fs), ns_per_day=round(speed, 2) if speed else None,
                       days=round(days, 2) if days is not None else None, trajectory_interval_ps=float(traj_ps),
                       report_interval_ps=float(report_ps), checkpoint_interval_ps=float(chunk_ps), n_frames=n_frames,
                       n_chunks=n_chunks, chunk_wall_minutes=round(chunk_wall_min, 1) if chunk_wall_min is not None else None,
                       trajectory_gb=round(traj_gb, 3), states_gb=round(states_gb, 3), log_gb=round(log_gb, 4),
                       total_gb=round(total_gb, 2), disk_free_gb=None if disk_free_gb is None else float(disk_free_gb),
                       replicas=replicas, keep_chunk_states=keep, issues=issues, decisions=decisions,
                       stage_overrides={"production": overrides} if overrides else {})


def _issue(code: str, level: str, zh: str, text: tuple, *, options: list | None = None) -> dict:
    return {"code": code, "level": level, "zh": zh, "text": text, "options": list(options or [])}


def _space_options(use_solute: bool, solute_ok: bool, *, raise_to_gb: float | None = None,
                   fit_gb: float | None = None) -> list[str]:
    """Options for a trajectory over its limit (`raise_to_gb`: allow a larger file) or a disk that is too small
    (`fit_gb`: the trajectory size per replica that would still fit; offered only when it is at least 1 GB)."""
    opts = []
    if solute_ok and not use_solute:
        opts.append("md.long_run.solute_only: true（只存溶質，不存水與反離子）")
    if raise_to_gb is not None:
        opts.append(f"md.long_run.target_gb: {math.ceil(raise_to_gb):g}（放寬軌跡上限，需要更多硬碟）")
    if fit_gb is not None and fit_gb >= 1.0:
        opts.append(f"md.long_run.target_gb: {math.floor(fit_gb):g}（存檔變稀疏，以符合剩餘空間）")
    opts.append("縮短 md.production_ns，或把專案資料夾移到空間較大的硬碟後重試")
    return opts


def needs_plan(production_ns: float | None, long_run_cfg: dict | None = None) -> bool:
    """Plan only runs longer than the research tier default, or when the config asks for it: runs at or below
    100 ns keep exactly the protocol (and hash) they had before this module existed."""
    return bool(long_run_cfg) or (production_ns is not None and float(production_ns) > PLAN_ABOVE_NS)


def apply_plan(protocol, plan: LongRunPlan) -> None:
    """Write the plan's production overrides into a Protocol in place (before the run starts)."""
    over = (plan.stage_overrides or {}).get("production") or {}
    for st in protocol.stages:
        if st.name == "production":
            for k, v in over.items():
                setattr(st, k, v)


def record_plan(plan: LongRunPlan, decisions, stage: str = "engine.longrun") -> None:
    if decisions is None:
        return
    for d in plan.decisions:
        decisions.record(stage, d["what"], d["choice"], d["why"], kind=d.get("kind", "auto"))
    decisions.record(stage, "plan", {"days": plan.days, "total_gb": plan.total_gb, "n_frames": plan.n_frames,
                                     "n_chunks": plan.n_chunks, "saved_atoms": plan.saved_atoms},
                     f"長時間模擬規劃：{plan.production_ns:g} ns × {plan.replicas} 份，軌跡 {plan.trajectory_gb:.1f} GB、"
                     f"chunk 檔 {plan.states_gb:.1f} GB，合計約 {plan.total_gb:.1f} GB"
                     + (f"，估計 {plan.days:.1f} 天。" if plan.days is not None else "；沒有效能測試，無法估計天數。"),
                     kind="auto")


def summary_text(plan: LongRunPlan) -> tuple[str, str, str, str]:
    """One line for the GUI and advisor checks: days, disk, save interval."""
    sub = ("只存溶質", "solute only", "溶質のみ", "용질만") if plan.solute_only else ("全系統", "whole system", "系全体", "전체 계")
    if plan.days is not None:
        d = (f"約 {plan.days:.1f} 天", f"About {plan.days:.1f} days", f"約 {plan.days:.1f} 日", f"약 {plan.days:.1f}일")
    else:
        d = ("天數未知（尚未做效能測試）", "Days unknown (no benchmark yet)", "日数は不明（ベンチマーク未実行）",
             "일수 미상(벤치마크 미실행)")
    return (f"{d[0]}，硬碟約 {plan.total_gb:.1f} GB，每 {plan.trajectory_interval_ps:g} ps 存一幀（{sub[0]}）。",
            f"{d[1]}, about {plan.total_gb:.1f} GB of disk, one frame every {plan.trajectory_interval_ps:g} ps ({sub[1]}).",
            f"{d[2]}、ディスク約 {plan.total_gb:.1f} GB、{plan.trajectory_interval_ps:g} ps ごとに 1 フレーム保存（{sub[2]}）。",
            f"{d[3]}, 디스크 약 {plan.total_gb:.1f} GB, {plan.trajectory_interval_ps:g} ps마다 한 프레임 저장({sub[3]}).")
