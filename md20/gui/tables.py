"""Pure-Python view models: turn package data (gate reports, doctor findings, manifests,
decisions, docking selections) into plain rows for `ui.table`.  No NiceGUI import here,
so everything in this module is unit-tested without a browser."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from ..i18n import pick, cjk, colon, paren
from ..util import load_json

NAV = [  # (label in zh, en, ja, ko; route) for the left drawer, in workflow order
    (("診斷", "Check", "診断", "진단"), "/"),
    (("專案", "Projects", "プロジェクト", "프로젝트"), "/projects"),
    (("分子對接", "Molecular docking", "分子ドッキング", "분자 도킹"), "/docking"),
    (("建模", "System building", "系の構築", "시스템 구축"), "/build"),
    (("執行", "Run", "実行", "실행"), "/run"),
    (("報告", "Report", "レポート", "보고서"), "/report"),
    (("決策紀錄", "Decision log", "判断の記録", "결정 기록"), "/decisions"),
]

STATUS_COLOR = {"PASS": "positive", "AUTO_FIXED": "warning", "NEEDS_HUMAN": "negative",
                "OK": "positive", "WARN": "warning", "FAIL": "negative",
                "COMPLETE": "positive", "RUNNING": "info", "PAUSED": "warning", "QUEUED": "grey",
                "INTERRUPTED": "negative", "CREATED": "grey", "BUILT": "positive"}

STATUS_LABEL = {"PASS": ("通過", "Passed", "合格", "통과"),
                "AUTO_FIXED": ("已自動修正", "Corrected automatically", "自動で修正済み", "자동 수정됨"),
                "NEEDS_HUMAN": ("需要你決定", "Needs your decision", "判断が必要", "결정 필요"),
                "OK": ("正常", "OK", "正常", "정상"), "WARN": ("注意", "Warning", "注意", "주의"),
                "FAIL": ("失敗", "Failed", "失敗", "실패")}

RUN_STAGES = [("minimize", ("能量最小化", "Energy minimisation", "エネルギー最小化", "에너지 최소화")),
              ("nvt", ("升溫（NVT）", "Heating (NVT)", "加熱（NVT）", "가열(NVT)")),
              ("npt", ("定壓平衡（NPT）", "Pressure equilibration (NPT)", "定圧平衡化（NPT）", "정압 평형(NPT)")),
              ("production", ("正式模擬", "Production", "本計算", "본 시뮬레이션"))]

SOURCE_LABEL = {"受體": ("受體", "Receptor", "受容体", "수용체"), "配體": ("配體", "Ligand", "リガンド", "리간드"),
                "組裝": ("組裝", "Assembly", "組み立て", "조립")}


def nav(lang: str = "zh") -> list[tuple[str, str]]:
    return [(pick(label, lang), route) for label, route in NAV]


def status_label(status: str, lang: str = "zh") -> str:
    s = str(status or "")
    return pick(STATUS_LABEL[s], lang) if s in STATUS_LABEL else s


def source_label(source: str, lang: str = "zh") -> str:
    """Row source in the interface language.  The source itself ("受體", "配體 BEN", "組裝") is an internal key."""
    head, _, rest = source.partition(" ")
    if head in SOURCE_LABEL:
        return (pick(SOURCE_LABEL[head], lang) + (f" {rest}" if rest else "")).strip()
    return source


def color_for(status: str | None) -> str:
    s = str(status or "")
    if s.startswith("BUILD_"):
        s = s[len("BUILD_"):]
    return STATUS_COLOR.get(s, "grey")


# ---- gates ---------------------------------------------------------------------------
def gate_rows(report: dict | Any, source: str = "", lang: str = "zh") -> list[dict]:
    """GateReport (object or its `to_dict()`) → rows with status colour, joined diff and options.

    `source` stays an internal key (human_choices_from reads it); `source_label` is the text to show."""
    if report is None:
        return []
    if hasattr(report, "to_dict"):
        report = report.to_dict()
    gates = report.get("gates", []) if isinstance(report, dict) else list(report)
    rows = []
    for i, g in enumerate(gates):
        if hasattr(g, "to_dict"):
            g = g.to_dict()
        status = g.get("status", "")
        rows.append({
            "id": f"{source}:{g.get('name', i)}:{i}",
            "source": source,
            "source_label": source_label(source, lang),
            "name": g.get("name", ""),
            "status": status,
            "status_label": status_label(status, lang),
            "color": color_for(status),
            "explanation": g.get("explanation", ""),
            "diff": "\n".join(str(d) for d in (g.get("diff") or [])),
            "n_diff": len(g.get("diff") or []),
            "options": list(g.get("options") or []),
            "options_text": ("、" if cjk(lang) else ", ").join(g.get("options") or []),
        })
    return rows


def build_summary_gate_rows(summary: dict | None, lang: str = "zh") -> list[dict]:
    """All gates of a `build_case` summary: receptor, then each ligand, then assembly."""
    if not summary:
        return []
    rows = gate_rows((summary.get("receptor") or {}).get("gates"), "受體", lang)
    for lig in summary.get("ligands") or []:
        rows += gate_rows(lig.get("gates"), f"配體 {lig.get('name', '')}".strip(), lang)
    rows += gate_rows((summary.get("assembly") or {}).get("gates"), "組裝", lang)
    return rows


def blocking_rows(rows: Iterable[dict]) -> list[dict]:
    return [r for r in rows if r["status"] == "NEEDS_HUMAN"]


def human_choices_from(rows: Iterable[dict], picked: dict[str, str]) -> dict:
    """GUI radio picks (row id → option) → the `human_choices` dict `build_case` accepts.

    `build_case` currently resolves receptor gates (`human_choices["receptor"][gate_name]`).
    Ligand picks are kept under `"ligands"` so they are recorded and passed along, but the
    build pipeline does not consume them yet (the GUI tells the student what to do instead).
    """
    out: dict = {}
    for r in rows:
        opt = picked.get(r["id"])
        if not opt:
            continue
        if r["source"] == "受體":
            out.setdefault("receptor", {})[r["name"]] = opt
        elif r["source"].startswith("配體"):
            lig = r["source"].split(" ", 1)[-1]
            out.setdefault("ligands", {}).setdefault(lig, {})[r["name"]] = opt
        else:
            out.setdefault("other", {})[r["name"]] = opt
    return out


def merge_choices(old: dict | None, new: dict) -> dict:
    out = {k: dict(v) if isinstance(v, dict) else v for k, v in (old or {}).items()}
    for k, v in new.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            for kk, vv in v.items():
                out[k][kk] = {**out[k].get(kk, {}), **vv} if isinstance(vv, dict) and isinstance(out[k].get(kk), dict) else vv
        else:
            out[k] = v
    return out


# ---- doctor --------------------------------------------------------------------------
def finding_rows(report: Any, lang: str = "zh") -> list[dict]:
    findings = getattr(report, "findings", None)
    if findings is None and isinstance(report, dict):
        findings = report.get("findings", [])
    rows = []
    for i, f in enumerate(findings or []):
        d = f if isinstance(f, dict) else {"item": f.item, "severity": f.severity, "detail": f.detail, "fix": f.fix}
        rows.append({"id": i, "item": d.get("item", ""), "severity": d.get("severity", ""),
                     "severity_label": status_label(d.get("severity", ""), lang),
                     "color": color_for(d.get("severity")), "detail": d.get("detail", ""), "fix": d.get("fix", "")})
    return rows


# ---- input parsing -------------------------------------------------------------------
def parse_lines(text: str | None) -> list[str]:
    """One item per line; blank lines and `#` comments ignored; surrounding quotes stripped."""
    out = []
    for line in (text or "").splitlines():
        s = line.strip().strip('"').strip("'").strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


def parse_optional_lines(text: str | None, n: int) -> list[str | None]:
    """Pose / co-crystal lists aligned with ligands: `-` or empty → None; padded/truncated to n."""
    vals: list[str | None] = []
    for line in (text or "").splitlines():
        s = line.strip().strip('"').strip("'").strip()
        if s.startswith("#"):
            continue
        vals.append(None if s in {"", "-", "無", "none", "None"} else s)
    while vals and vals[-1] is None and len(vals) > n:
        vals.pop()
    vals = vals[:n]
    return vals + [None] * (n - len(vals))


# ---- projects / runs -----------------------------------------------------------------
def case_rows(project) -> list[dict]:
    rows = []
    for c in project.cases():
        m = c.manifest()
        rows.append({"case_id": c.case_id, "name": m.get("name", ""), "status": m.get("status", ""),
                     "color": color_for(m.get("status")), "forcefield": m.get("forcefield_family", ""),
                     "active_run": m.get("active_run", ""), "n_runs": sum(1 for _ in c.runs())})
    return rows


def run_rows(case) -> list[dict]:
    rows = []
    for r in case.runs():
        m = r.manifest()
        rows.append({"run_id": r.run_id, "stage": r.stage() or "—", "status": m.get("status", ""),
                     "color": color_for(m.get("status")), "tier": (m.get("protocol") or {}).get("tier", ""),
                     "replica": m.get("replica_index", ""), "created_at": m.get("created_at", "")})
    return rows


def stage_badges(run, lang: str = "zh") -> list[dict]:
    """Per-stage acceptance from `<stage>_complete.json` (file truth)."""
    out = []
    not_run = pick(("未執行", "Not run", "未実行", "실행 안 됨"), lang)
    for name, labels in RUN_STAGES:
        label = pick(labels, lang)
        d = load_json(Path(run.dir) / "stages" / name / f"{name}_complete.json", {})
        status = d.get("status") or ("RUNNING" if (Path(run.dir) / "stages" / name / f"{name}_running.json").is_file() else "")
        acc = (d.get("acceptance") or {}).get("status", "")
        text = f"{label}{colon(lang)}{status_label(status, lang) or not_run}"
        if acc:
            text += paren(pick((f"驗收 {acc}", f"acceptance {acc}", f"合格判定 {acc}", f"합격 판정 {acc}"), lang), lang)
        out.append({"stage": name, "label": label, "status": status or "NOT_RUN", "acceptance": acc,
                    "text": text, "color": color_for(status) if status else "grey"})
    return out


def queue_rows(jobs: Iterable[dict]) -> list[dict]:
    return [{"id": j.get("id", ""), "case_id": j.get("case_id", ""), "tier": j.get("tier", ""),
             "replicas": j.get("replicas", 1), "status": j.get("status", ""), "color": color_for(j.get("status")),
             "reason": j.get("reason", "")} for j in jobs]


def progress_text(hb: dict | None, lang: str = "zh") -> str:
    if not hb:
        return pick(("還沒有進度", "No progress yet", "まだ進捗はありません", "아직 진행 상황이 없습니다"), lang)
    total = hb.get("total_steps") or 0
    done = hb.get("completed_local_steps") or 0
    pct = 100.0 * done / total if total else 0.0
    t = hb.get("temperature_k")
    t_txt = f"{t:.1f} K" if isinstance(t, (int, float)) else "—"
    chunk, steps = hb.get("chunk", "?"), f"{done:,}/{total:,}"
    head = pick((f"區段 {chunk} · {steps} 步", f"chunk {chunk} · {steps} steps", f"区切り {chunk} · {steps} ステップ",
                 f"구간 {chunk} · {steps} 스텝"), lang)
    return (f"[{hb.get('stage', '?')}] {head}{paren(f'{pct:.1f}%', lang)} · "
            f"T={t_txt} · dt={hb.get('timestep_fs', '?')} fs · {hb.get('elapsed_s', 0)} s")


def progress_fraction(hb: dict | None) -> float:
    if not hb or not hb.get("total_steps"):
        return 0.0
    return max(0.0, min(1.0, float(hb.get("completed_local_steps") or 0) / float(hb["total_steps"])))


# ---- decisions -----------------------------------------------------------------------
def decision_rows(rows: Iterable[dict], stage_prefix: str | None = None) -> list[dict]:
    out = []
    for i, r in enumerate(rows):
        stage = str(r.get("stage", ""))
        if stage_prefix and not stage.startswith(stage_prefix):
            continue
        choice = r.get("choice")
        out.append({"id": i, "at": r.get("at", ""), "stage": stage, "what": r.get("what", ""),
                    "choice": choice if isinstance(choice, str) else str(choice), "kind": r.get("kind", ""),
                    "why": r.get("why", "")})
    return out


def decision_stage_options(rows: Iterable[dict]) -> list[str]:
    """Distinct top-level prefixes (`build`, `engine`, …) followed by full stage names."""
    stages = sorted({str(r.get("stage", "")) for r in rows if r.get("stage")})
    tops = sorted({s.split(".")[0] for s in stages})
    return tops + [s for s in stages if s not in tops]


# ---- docking -------------------------------------------------------------------------
def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def pose_rows(poses: Iterable[Any], recommended_pose_id: Any = None) -> list[dict]:
    """Docking `Pose` objects or dicts → table rows (fields per docs/specs/docking.md)."""
    rows = []
    for p in poses or []:
        pid = _get(p, "pose_id")
        aff = _get(p, "affinity")
        rmsd = _get(p, "rmsd_to_reference")
        rows.append({"pose_id": pid, "joint_pose_id": _get(p, "joint_pose_id"),
                     "affinity": round(float(aff), 2) if isinstance(aff, (int, float)) else aff,
                     "contacts": _get(p, "contacts"),
                     "rmsd_to_reference": round(float(rmsd), 2) if isinstance(rmsd, (int, float)) else rmsd,
                     "sdf": str(_get(p, "sdf_path", _get(p, "sdf", "")) or ""),
                     "recommended": pid == recommended_pose_id})
    return rows
