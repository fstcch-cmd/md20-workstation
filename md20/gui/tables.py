"""Pure-Python view models: turn package data (gate reports, doctor findings, manifests,
decisions, docking selections) into plain rows for `ui.table`.  No NiceGUI import here,
so everything in this module is unit-tested without a browser."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from ..util import load_json

NAV = [  # (label, route) — left drawer, in workflow order
    ("Doctor", "/"),
    ("專案", "/projects"),
    ("Docking", "/docking"),
    ("建模", "/build"),
    ("執行", "/run"),
    ("報告", "/report"),
    ("決策日誌", "/decisions"),
]

STATUS_COLOR = {"PASS": "positive", "AUTO_FIXED": "warning", "NEEDS_HUMAN": "negative",
                "OK": "positive", "WARN": "warning", "FAIL": "negative",
                "COMPLETE": "positive", "RUNNING": "info", "PAUSED": "warning", "QUEUED": "grey",
                "INTERRUPTED": "negative", "CREATED": "grey", "BUILT": "positive"}

STATUS_LABEL = {"PASS": "通過", "AUTO_FIXED": "已自動修正", "NEEDS_HUMAN": "需要你決定",
                "OK": "正常", "WARN": "注意", "FAIL": "失敗"}

RUN_STAGES = [("minimize", "能量最小化"), ("nvt", "NVT 升溫"), ("npt", "NPT 平衡"), ("production", "Production")]


def color_for(status: str | None) -> str:
    s = str(status or "")
    if s.startswith("BUILD_"):
        s = s[len("BUILD_"):]
    return STATUS_COLOR.get(s, "grey")


# ---- gates ---------------------------------------------------------------------------
def gate_rows(report: dict | Any, source: str = "") -> list[dict]:
    """GateReport (object or its `to_dict()`) → rows with status colour, joined diff and options."""
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
            "name": g.get("name", ""),
            "status": status,
            "status_label": STATUS_LABEL.get(status, status),
            "color": color_for(status),
            "explanation": g.get("explanation", ""),
            "diff": "\n".join(str(d) for d in (g.get("diff") or [])),
            "n_diff": len(g.get("diff") or []),
            "options": list(g.get("options") or []),
            "options_text": " / ".join(g.get("options") or []),
        })
    return rows


def build_summary_gate_rows(summary: dict | None) -> list[dict]:
    """All gates of a `build_case` summary: receptor → each ligand → assembly."""
    if not summary:
        return []
    rows = gate_rows((summary.get("receptor") or {}).get("gates"), "受體")
    for lig in summary.get("ligands") or []:
        rows += gate_rows(lig.get("gates"), f"配體 {lig.get('name', '')}".strip())
    rows += gate_rows((summary.get("assembly") or {}).get("gates"), "組裝")
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
def finding_rows(report: Any) -> list[dict]:
    findings = getattr(report, "findings", None)
    if findings is None and isinstance(report, dict):
        findings = report.get("findings", [])
    rows = []
    for i, f in enumerate(findings or []):
        d = f if isinstance(f, dict) else {"item": f.item, "severity": f.severity, "detail": f.detail, "fix": f.fix}
        rows.append({"id": i, "item": d.get("item", ""), "severity": d.get("severity", ""),
                     "severity_label": STATUS_LABEL.get(d.get("severity", ""), d.get("severity", "")),
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


def stage_badges(run) -> list[dict]:
    """Per-stage acceptance from `<stage>_complete.json` (file truth)."""
    out = []
    for name, label in RUN_STAGES:
        d = load_json(Path(run.dir) / "stages" / name / f"{name}_complete.json", {})
        status = d.get("status") or ("RUNNING" if (Path(run.dir) / "stages" / name / f"{name}_running.json").is_file() else "")
        acc = (d.get("acceptance") or {}).get("status", "")
        text = f"{label}：{STATUS_LABEL.get(status, status) or '未執行'}"
        if acc:
            text += f"（驗收 {acc}）"
        out.append({"stage": name, "label": label, "status": status or "NOT_RUN", "acceptance": acc,
                    "text": text, "color": color_for(status) if status else "grey"})
    return out


def queue_rows(jobs: Iterable[dict]) -> list[dict]:
    return [{"id": j.get("id", ""), "case_id": j.get("case_id", ""), "tier": j.get("tier", ""),
             "replicas": j.get("replicas", 1), "status": j.get("status", ""), "color": color_for(j.get("status")),
             "reason": j.get("reason", "")} for j in jobs]


def progress_text(hb: dict | None) -> str:
    if not hb:
        return "尚無進度"
    total = hb.get("total_steps") or 0
    done = hb.get("completed_local_steps") or 0
    pct = 100.0 * done / total if total else 0.0
    t = hb.get("temperature_k")
    t_txt = f"{t:.1f} K" if isinstance(t, (int, float)) else "—"
    return (f"[{hb.get('stage', '?')}] chunk {hb.get('chunk', '?')} · {done:,}/{total:,} steps ({pct:.1f}%) · "
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
