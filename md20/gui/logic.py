"""GUI logic without NiceGUI (testable): form → config, background runner, status snapshots."""
from __future__ import annotations

import queue
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from ..util import load_json, safe_name
from ..workflow import Workflow, WorkflowBlocked, example_config, SYSTEM_MODES


def parse_ligand_table(text: str) -> list[dict]:
    """One ligand per line: `NAME  SMILES  [crystal_resname]` (tab, comma or spaces)."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p for p in line.replace(",", " ").replace("\t", " ").split(" ") if p]
        if len(parts) < 2:
            raise ValueError(f"每行需要「名稱 SMILES」：{line}")
        d = {"name": safe_name(parts[0])[:3].upper(), "smiles": parts[1]}
        if len(parts) > 2:
            d["reference_resname"] = parts[2].upper()
        out.append(d)
    names = [d["name"] for d in out]
    if len(set(names)) != len(names):
        raise ValueError("配體名稱（前三字元）重複；請改名以免拓撲殘基名衝突。")
    return out


def config_from_form(*, name: str, pdb_id: str = "", receptor_file: str = "", ligands_text: str = "", box_residue: str = "",
                     box_center: str = "", box_size: str = "22,22,22", mode: str = "independent", exhaustiveness: int = 16,
                     systems: list[str] | None = None, tier: str = "teaching", replicas: int = 1, binding: bool = True,
                     ph: float = 7.4, keep_hetero: str = "") -> dict:
    cfg = example_config()
    cfg["name"] = safe_name(name or "pipeline")
    if pdb_id:
        cfg["receptor"] = {"pdb_id": pdb_id.strip().upper()}
    elif receptor_file:
        cfg["receptor"] = {"file": receptor_file}
    else:
        raise ValueError("請輸入 PDB ID 或上傳受體檔")
    cfg["ph"] = float(ph)
    cfg["keep_hetero"] = [x.strip().upper() for x in keep_hetero.replace(",", " ").split() if x.strip()]
    cfg["ligands"] = parse_ligand_table(ligands_text)
    if box_residue:
        cfg["box"] = {"from_residue": box_residue.strip().upper()}
    elif box_center:
        cfg["box"] = {"center": [float(x) for x in box_center.split(",")], "size": [float(x) for x in box_size.split(",")]}
    else:
        cfg["box"] = {"whole_receptor": True}
    if mode not in {"independent", "simultaneous"}:
        raise ValueError("docking 模式錯誤")
    if mode == "simultaneous" and len(cfg["ligands"]) < 2:
        raise ValueError("simultaneous 模式至少需要 2 個配體")
    cfg["docking"].update({"mode": mode, "exhaustiveness": int(exhaustiveness)})
    systems = list(systems or ["apo", "docked_single"])
    bad = [s for s in systems if s not in SYSTEM_MODES]
    if bad:
        raise ValueError(f"未知 MD 系統：{bad}")
    if "docked_multi" in systems and len(cfg["ligands"]) < 2:
        raise ValueError("docked_multi 需要至少 2 個配體")
    if not cfg["ligands"]:
        systems = [s for s in systems if s == "apo"] or ["apo"]
    cfg["md"].update({"systems": systems, "tier": tier, "replicas": int(replicas)})
    cfg["binding"] = {"enabled": bool(binding) and bool(cfg["ligands"]) and "docked_single" in systems,
                      "ligands": [l["name"] for l in cfg["ligands"]], "config": {}}
    cfg["pose_choices"] = {}
    return cfg


def step_rows(state: dict) -> list[dict]:
    order = ["receptor_input", "receptor_docking", "docking", "pose_selection", "md_cases", "md_runs", "analysis", "binding", "report"]
    labels = {"receptor_input": "受體來源", "receptor_docking": "受體整理", "docking": "分子對接", "pose_selection": "pose 選擇",
              "md_cases": "MD 建模", "md_runs": "MD 執行", "analysis": "軌跡分析", "binding": "SMD＋傘狀採樣", "report": "報告"}
    steps = state.get("steps", {})
    return [{"step": labels[k], "key": k, "status": steps.get(k, {}).get("status", "—"), "at": steps.get(k, {}).get("at", ""),
             "message": steps.get(k, {}).get("message", "")} for k in order]


@dataclass
class Job:
    wf: Workflow
    thread: threading.Thread | None = None
    events: "queue.Queue[dict]" = field(default_factory=queue.Queue)
    status: str = "IDLE"
    message: str = ""
    report: str = ""
    history: list[dict] = field(default_factory=list)

    def snapshot(self) -> dict:
        while True:
            try:
                ev = self.events.get_nowait()
            except queue.Empty:
                break
            self.history.append(ev)
            self.history = self.history[-2000:]
        return {"status": self.status, "message": self.message, "report": self.report,
                "steps": step_rows(self.wf.state()), "history": self.history}


class Runner:
    """One background workflow per (project, name).  Pause = create the project PAUSE file."""

    def __init__(self):
        self.jobs: dict[str, Job] = {}

    def start(self, wf: Workflow, make_factory, platform, should_pause=None) -> Job:
        key = f"{wf.project.dir}::{wf.name}"
        job = self.jobs.get(key)
        if job and job.thread and job.thread.is_alive():
            return job
        job = Job(wf=wf)
        self.jobs[key] = job

        def target():
            job.status = "RUNNING"
            try:
                out = wf.run(make_factory, platform, should_pause=should_pause, progress_cb=job.events.put)
                job.status = out["status"]
                job.report = out.get("report", "")
                job.message = "完成" if out["status"] == "COMPLETE" else "已暫停；按「繼續」從中斷處接續"
            except WorkflowBlocked as exc:
                job.status, job.message = "NEEDS_HUMAN", str(exc)
            except Exception as exc:  # noqa: BLE001
                job.status, job.message = "ERROR", f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-2000:]}"
        job.thread = threading.Thread(target=target, name=f"md20-{wf.name}", daemon=True)
        job.thread.start()
        return job

    def get(self, wf: Workflow) -> Job | None:
        return self.jobs.get(f"{wf.project.dir}::{wf.name}")


def set_pose_choice(wf: Workflow, entry: str, rank: int) -> None:
    """User override from the pose table; invalidates pose selection and everything downstream."""
    cfg = load_json(wf.dir / "config.json", wf.cfg)
    cfg.setdefault("pose_choices", {})[entry] = int(rank)
    wf.cfg = cfg
    from ..util import atomic_write_json
    atomic_write_json(cfg, wf.dir / "config.json")
    st = wf.state()
    for k in ("pose_selection", "md_cases", "md_runs", "analysis", "binding", "report"):
        st["steps"].pop(k, None)
    atomic_write_json(st, wf.state_path)


def pose_table(wf: Workflow) -> list[dict]:
    d = wf.state()["steps"].get("docking")
    if not d:
        return []
    res = load_json(d["result"], {})
    sel = (wf.state()["steps"].get("pose_selection") or {}).get("selection", {}).get("ligands", {})
    rows = []
    for e in res.get("entries", []):
        chosen = {v["rank"] for v in sel.values() if v.get("entry") == e["name"]}
        for p in e["poses"]:
            rows.append({"entry": e["name"], "rank": p["rank"], "score": round(p["score"], 2), "cluster": f"{p['cluster']} ({p['cluster_size']})",
                         "contacts": p["contacts"], "rmsd_ref": p["rmsd_ref"], "clash": p.get("clash", False),
                         "recommended": p["recommended"], "chosen": p["rank"] in chosen, "reason": e["reason"] if p["recommended"] else ""})
    return rows


def list_workflows(projects_dir: Path) -> list[dict]:
    out = []
    root = Path(projects_dir)
    if not root.is_dir():
        return out
    for pdir in sorted(root.iterdir()):
        wroot = pdir / "workflows"
        if not wroot.is_dir():
            continue
        for w in sorted(wroot.iterdir()):
            st = load_json(w / "state.json", {})
            steps = st.get("steps", {})
            last = max(steps.items(), key=lambda kv: kv[1].get("at", ""), default=(None, {}))
            out.append({"project": pdir.name, "workflow": w.name, "last_step": last[0] or "—", "status": last[1].get("status", "—"),
                        "updated": st.get("updated_at", "")})
    return out
