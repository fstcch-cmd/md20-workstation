"""GUI logic without NiceGUI (testable): form → config, background runner, status snapshots."""
from __future__ import annotations

from ..util.timeutil import to_local
import copy
import queue
import os
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from ..i18n import pick, paren, LANGS
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
    order = ["receptor_input", "receptor_docking", "screen_library", "screen_docking", "screen_selection", "docking", "pose_selection",
             "md_confirm", "md_cases", "md_runs", "analysis", "binding", "report"]
    labels = {"receptor_input": "受體來源", "receptor_docking": "受體整理", "screen_library": "篩選：化合物庫", "screen_docking": "篩選：快速對接",
              "screen_selection": "篩選：選擇化合物", "docking": "分子對接", "pose_selection": "姿勢選擇",
              "md_confirm": "確認進入分子動力學", "md_cases": "MD 建模", "md_runs": "MD 執行", "analysis": "軌跡分析", "binding": "SMD＋傘狀採樣", "report": "報告"}
    steps = state.get("steps", {})
    screen_keys = {"screen_library", "screen_docking", "screen_selection"}
    if not any(k in steps for k in screen_keys):
        order = [k for k in order if k not in screen_keys]      # no screen configured: keep the table short
    if "md_confirm" not in steps:
        order = [k for k in order if k != "md_confirm"]
    return [{"step": labels[k], "key": k, "status": steps.get(k, {}).get("status", "—"), "at": to_local(steps.get(k, {}).get("at", "")),
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
        busy = self.running()
        if busy is not None:
            # D-67: one calculation at a time on this computer (two on one GPU/CPU are each slower and a second
            # click must never start the same lesson again).  The caller sees a job for another workflow.
            return busy
        job = Job(wf=wf)
        self.jobs[key] = job

        def target():
            job.status = "RUNNING"
            try:
                fake = os.environ.get("MD20_GUI_FAKE_RUN")
                out = (_fake_run(wf, float(fake), job.events.put) if fake else
                       wf.run(make_factory, platform, should_pause=should_pause, progress_cb=job.events.put))
                job.status = out["status"]
                job.report = out.get("report", "")
                # a (zh, en, ja, ko) tuple: the page shows it in its own language
                job.message = (("完成", "Done", "完了しました", "완료") if out["status"] == "COMPLETE" else
                               ("已暫停。按「開始或繼續」會從停下的地方接著跑。",
                                "Paused. Press Start or continue to carry on from where it stopped.",
                                "一時停止しました。「開始または再開」を押すと、止まったところから続きます。",
                                "일시 정지했습니다. '시작 또는 계속'을 누르면 멈춘 곳부터 이어서 실행합니다."))
            except WorkflowBlocked as exc:
                job.status, job.message = "NEEDS_HUMAN", str(exc)
            except Exception as exc:  # noqa: BLE001
                job.status, job.message = "ERROR", f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-2000:]}"
        job.thread = threading.Thread(target=target, name=f"md20-{wf.name}", daemon=True)
        job.thread.start()
        return job

    def running(self) -> Job | None:
        for j in self.jobs.values():
            if j.thread and j.thread.is_alive():
                return j
        return None

    def get(self, wf: Workflow) -> Job | None:
        return self.jobs.get(f"{wf.project.dir}::{wf.name}")


def _fake_run(wf: Workflow, seconds: float, progress_cb) -> dict:
    """Test stand-in for wf.run (env MD20_GUI_FAKE_RUN=<seconds>; tools/gui_preview.py, D-74): counts its starts and
    heartbeats in <workflow>/_fake_run.json so a test can prove that a language switch neither stops, restarts nor
    duplicates a running calculation.  Never used unless that variable is set."""
    import json
    import time
    f = wf.dir / "_fake_run.json"
    wf.dir.mkdir(parents=True, exist_ok=True)
    st = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
    st["starts"] = int(st.get("starts", 0)) + 1
    st["finished"] = False
    n = max(1, int(seconds))
    for k in range(n):
        st["beats"] = int(st.get("beats", 0)) + 1
        st["t"] = time.time()
        f.write_text(json.dumps(st), encoding="utf-8")
        progress_cb({"stage": "fake", "case_id": "fake", "completed_local_steps": k + 1, "total_steps": n, "elapsed_s": float(k)})
        time.sleep(1.0)
    st["finished"] = True
    f.write_text(json.dumps(st), encoding="utf-8")
    return {"status": "COMPLETE"}


def set_pose_choice(wf: Workflow, entry: str, rank: int) -> None:
    """User override from the pose table; invalidates pose selection and everything downstream."""
    cfg = load_json(wf.dir / "config.json", wf.cfg)
    cfg.setdefault("pose_choices", {})[entry] = int(rank)
    wf.cfg = cfg
    from ..util import atomic_write_json
    atomic_write_json(cfg, wf.dir / "config.json")
    st = wf.state()
    for k in ("pose_selection", "md_confirm", "md_cases", "md_runs", "analysis", "binding", "report"):
        st["steps"].pop(k, None)
    atomic_write_json(st, wf.state_path)


def pose_table(wf: Workflow, lang: str = "en") -> list[dict]:
    d = wf.state()["steps"].get("docking")
    if not d:
        return []
    res = load_json(d["result"], {})
    sel = (wf.state()["steps"].get("pose_selection") or {}).get("selection", {}).get("ligands", {})
    screen = load_json(wf.dir / "pose_screen.json", {})       # WP5 short-MD verdicts, if the screen ran
    rows = []
    for e in res.get("entries", []):
        chosen = {v["rank"] for v in sel.values() if v.get("entry") == e["name"]}
        for p in e["poses"]:
            rows.append({"entry": e["name"], "rank": p["rank"], "score": round(p["score"], 2), "cluster": f"{p['cluster']} ({p['cluster_size']})",
                         "contacts": p["contacts"], "rmsd_ref": p["rmsd_ref"], "clash": p.get("clash", False),
                         "recommended": p["recommended"], "chosen": p["rank"] in chosen, "reason": e["reason"] if p["recommended"] else "",
                         "md_screen": _screen_label((screen.get(e["name"]) or {}).get(str(p["rank"])), lang)})
    from .advanced import score_text
    for name, v in sel.items():               # D-80 fold: complex: placed from the prediction, no docking entry, no score
        if v.get("source") == "fold_complex" or v.get("score") is None:
            rows.append({"entry": name, "rank": v.get("rank", 1), "score": score_text(None, lang), "cluster": "", "contacts": "",
                         "rmsd_ref": None, "clash": False, "recommended": True, "chosen": True, "reason": "", "md_screen": ""})
    return rows


_VERDICT = {"STABLE": ("穩定", "Stable", "安定", "안정"), "UNSTABLE": ("不穩定", "Unstable", "不安定", "불안정"),
            "FAILED": ("失敗", "Failed", "失敗", "실패")}


def _screen_label(a: dict | None, lang: str = "en") -> str:
    if not a:
        return ""
    v = a.get("verdict", "")
    v = pick(_VERDICT[v], lang) if v in _VERDICT else v
    r = a.get("worst_tail_rmsd_A")
    return v + paren(f"{r:.1f} Å", lang) if r is not None else v


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
                        "updated": to_local(st.get("updated_at", ""))})
    return out


def screen_table(wf: Workflow) -> list[dict]:
    """Ranking rows for the 篩選 tab (empty until the screen docking finished)."""
    from ..docking.screen import rank_screen
    d = wf.state()["steps"].get("screen_docking") or {}
    if not d.get("results"):
        return []
    res = load_json(d["results"], {})
    rows = rank_screen(res, top_n=int((wf.cfg.get("screen") or {}).get("top_n", 20)))
    chosen = set((wf.cfg.get("screen") or {}).get("select") or [])
    for r in rows:
        r["key"] = r["name"]
        r["chosen"] = r["name"] in chosen
        r["tag"] = ("✔" if r["chosen"] else "") + ("≈" if r.get("indistinguishable_from_top") else "")
    return rows


# ------------------------------------------------------------------------------------- GUI v2 (D-51)
def parse_ligand_lines(text: str, lang: str = "en") -> list[dict]:
    """One ligand per line: `NAME SMILES [crystal_resname]` or `NAME peptide:SEQUENCE [target_location]`.
    Names become 3-character residue names (topology); they must stay unique."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p for p in line.replace(",", " ").replace("\t", " ").split(" ") if p]
        if len(parts) < 2:
            raise ValueError(pick((f"每行要寫「名稱 SMILES」或「名稱 peptide:序列」：{line}",
                                   f"Each line needs NAME SMILES or NAME peptide:SEQUENCE: {line}",
                                   f"各行には「名前 SMILES」か「名前 peptide:配列」を書いてください：{line}",
                                   f"각 줄에는 '이름 SMILES' 또는 '이름 peptide:서열'을 적어야 합니다: {line}"), lang))
        name = safe_name(parts[0])[:3].upper()
        if parts[1].lower().startswith("peptide:"):
            from ..build.peptide import clean_sequence
            d = {"name": name, "sequence": clean_sequence(parts[1].split(":", 1)[1]), "termini": "charged"}
            if len(parts) > 2:
                d["target_location"] = parts[2]
        else:
            d = {"name": name, "smiles": parts[1]}
            if len(parts) > 2:
                d["reference_resname"] = parts[2].upper()
        out.append(d)
    names = [d["name"] for d in out]
    if len(set(names)) != len(names):
        raise ValueError(pick(("有配體名稱的前三個字元相同。請改名，否則拓撲裡的殘基名會衝突。",
                               "Two ligand names share the same first three characters. Rename one, or their residue "
                               "names in the topology will clash.",
                               "先頭 3 文字が同じリガンド名があります。トポロジーの残基名が衝突するので、名前を変えてください。",
                               "앞 세 글자가 같은 리간드 이름이 있습니다. 토폴로지의 잔기 이름이 충돌하므로 이름을 바꾸십시오."), lang))
    return out


def config_from_mode(*, mode: str, name: str, values: dict, pdb_id: str = "", receptor_file: str = "",
                     ligands_text: str = "", box_residue: str = "", box_center: str = "", box_size: str = "",
                     systems: list[str] | None = None, ph: float = 7.4, keep_hetero: str = "", goal: str = "teaching",
                     library_file: str = "", lang: str = "en", advanced: dict | None = None,
                     quick_fold: list | set | None = None) -> dict:
    """Quick or pro form → workflow config.  `values` are the advisor parameters (already merged with the
    recommendation); the GUI always asks before molecular dynamics (confirm_before_md).
    `advanced`: membrane, folding and long-run settings of the professional form (gui/advanced.py);
    `quick_fold`: peptide names ticked "fold this peptide" in quick mode."""
    from .. import advisor
    from .advanced import apply_advanced, membrane_spec, defaults as adv_defaults
    adv = {**adv_defaults(), **(advanced or {})}
    mspec = membrane_spec(adv)
    no_receptor = bool(mspec and mspec["type"] in ("surface", "bilayer"))      # membrane cases B and C (D-80)
    cfg = copy.deepcopy(example_config())
    cfg["name"] = safe_name(name or "workflow")
    if no_receptor:
        cfg["receptor"] = {}
    elif pdb_id.strip():
        cfg["receptor"] = {"pdb_id": pdb_id.strip().upper()}
    elif receptor_file:
        cfg["receptor"] = {"file": receptor_file}
    else:
        raise ValueError(pick(("請輸入 PDB 編號，或上傳受體結構檔。", "Enter a PDB ID or upload a receptor structure file.",
                               "PDB ID を入力するか、受容体の構造ファイルをアップロードしてください。",
                               "PDB ID를 입력하거나 수용체 구조 파일을 업로드하십시오."), lang))
    cfg["ph"] = float(ph)
    cfg["keep_hetero"] = [x.strip().upper() for x in keep_hetero.replace(",", " ").split() if x.strip()]
    cfg["ligands"] = parse_ligand_lines(ligands_text, lang)
    if box_residue.strip():
        cfg["box"] = {"from_residue": box_residue.strip().upper()}
    elif box_center.strip():
        c = [float(x) for x in box_center.replace(" ", "").split(",")]
        s = [float(x) for x in (box_size or "22,22,22").replace(" ", "").split(",")]
        if len(c) != 3 or len(s) != 3:
            raise ValueError(pick(("搜尋區的中心和尺寸各要三個數字（x, y, z）。", "The box centre and size each need three numbers (x, y, z).",
                                   "探索ボックスの中心と大きさには、それぞれ 3 つの数字（x, y, z）が必要です。",
                                   "탐색 상자의 중심과 크기에는 각각 숫자 세 개(x, y, z)가 필요합니다."), lang))
        cfg["box"] = {"center": c, "size": s}
    else:
        cfg["box"] = {}
    ligs = cfg["ligands"]
    systems = list(systems or (["apo", "docked_single"] if ligs else ["apo"]))
    bad = [s for s in systems if s not in SYSTEM_MODES]
    if bad:
        raise ValueError(pick((f"未知的模擬系統：{bad}", f"Unknown simulation systems: {bad}",
                               f"不明なシミュレーション系：{bad}", f"알 수 없는 시뮬레이션 계: {bad}"), lang))
    if "docked_multi" in systems and len(ligs) < 2:
        raise ValueError(pick(("「所有配體同時與蛋白」至少要有兩個配體。", "Simulating all ligands together with the protein needs at least two ligands.",
                               "すべてのリガンドを同時にタンパク質と計算するには、リガンドが 2 つ以上必要です。",
                               "모든 리간드를 단백질과 함께 계산하려면 리간드가 두 개 이상 필요합니다."), lang))
    if not ligs:
        systems = ["apo"]
    v = dict(values)
    if v.get("docking_mode") == "simultaneous" and len(ligs) < 2:
        v["docking_mode"] = "independent"
    cfg = advisor.apply(v, cfg)
    cfg["md"]["systems"] = systems
    cfg["binding"]["enabled"] = bool(v.get("binding")) and bool(ligs) and "docked_single" in systems
    cfg["binding"]["ligands"] = [l["name"] for l in ligs] if cfg["binding"]["enabled"] else []
    if library_file:
        cfg["screen"] = {"library": library_file, "exhaustiveness": 8, "n_poses": 3, "top_n": 20, "allow_partial": False,
                         "allow_name_lookup": False, "select": [], "next_mode": v.get("docking_mode", "independent")}
    else:
        cfg.pop("screen", None)
    cfg["pose_choices"] = {}
    cfg["confirm_before_md"] = True
    cfg = apply_advanced(cfg, adv, quick_fold=quick_fold)
    if cfg["md"].get("membrane"):
        cfg["binding"]["enabled"], cfg["binding"]["ligands"] = False, []     # gate `membrane binding`: not available yet
        if no_receptor:
            cfg.pop("screen", None)
    cfg["language"] = lang if lang in LANGS else "en"
    cfg["gui_mode"] = mode
    cfg["goal"] = goal
    return cfg
