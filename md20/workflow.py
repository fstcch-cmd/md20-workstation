"""End-to-end workflow: receptor → docking → pose choice → MD (apo / docked) → analysis → SMD+umbrella → report.

Mirrors the original MD20 notebooks:
  Project 1 Phase 7   docking mode   independent | simultaneous
  Project 1 Phase 10  MD system      apo | docked_single | docked_multi
and adds the binding-strength stage (Project 3 Phase 25 in the original plan).

Every step writes a completion record in <project>/workflows/<name>/state.json and is skipped when
already complete, so `md20 pipeline run cfg.json` can be re-run after a pause, a crash or a reboot.

Config (JSON):
{
  "name": "trypsin_demo",
  "receptor": {"pdb_id": "3PTB"}            | {"file": "receptor.pdb"},
  "ph": 7.4, "keep_hetero": ["CA"],
  "box": {"from_residue": "BEN"}            | {"center": [x,y,z], "size": [sx,sy,sz]} | {"whole_receptor": true},
  "ligands": [{"name": "BEN", "smiles": "NC(=[NH2+])c1ccccc1", "reference_resname": "BEN"}],
  "docking": {"mode": "independent", "scoring": "vina", "exhaustiveness": 16, "n_poses": 9},
  "pose_choices": {"BEN": 2},               # optional overrides (rank); simultaneous: {"joint": 3}
  "md": {"systems": ["apo", "docked_single"], "tier": "teaching", "replicas": 1, "production_ns": null,
         "padding_nm": 1.0},
  "binding": {"enabled": true, "ligands": ["BEN"], "config": {"pull_velocity_nm_per_ps": 0.01}}
}
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import fields
from pathlib import Path
from typing import Callable

import numpy as np

from .project import Project
from .util import atomic_write_json, load_json, now_iso, ensure_dir, safe_name

SYSTEM_MODES = ("apo", "docked_single", "docked_multi")


class WorkflowBlocked(RuntimeError):
    """A step needs a human decision; message explains which and why."""


def example_config() -> dict:
    return {
        "name": "trypsin_benzamidine",
        "receptor": {"pdb_id": "3PTB"},
        "ph": 7.4, "keep_hetero": ["CA"],
        "box": {"from_residue": "BEN"},
        "ligands": [{"name": "BEN", "smiles": "NC(=[NH2+])c1ccccc1", "reference_resname": "BEN"}],
        "docking": {"mode": "independent", "scoring": "vina", "exhaustiveness": 16, "n_poses": 9},
        "pose_choices": {},
        "md": {"systems": ["apo", "docked_single"], "tier": "teaching", "replicas": 1, "production_ns": None, "padding_nm": 1.0},
        "binding": {"enabled": True, "ligands": ["BEN"], "config": {}},
    }


class Workflow:
    def __init__(self, project: Project, config: dict):
        self.project = project
        self.cfg = config
        self.name = safe_name(config.get("name", "workflow"))
        self.dir = ensure_dir(project.dir / "workflows" / self.name)
        self.state_path = self.dir / "state.json"
        self.dec = project.decisions
        atomic_write_json(config, self.dir / "config.json")

    # ------------------------------------------------------------------ state helpers
    def state(self) -> dict:
        return load_json(self.state_path, {"steps": {}})

    def _done(self, step: str) -> dict | None:
        s = self.state()["steps"].get(step)
        return s if s and s.get("status") == "PASS" else None

    def _mark(self, step: str, **data) -> dict:
        st = self.state()
        st["steps"][step] = {"status": "PASS", **data, "at": now_iso()}
        st["updated_at"] = now_iso()
        atomic_write_json(st, self.state_path)
        return st["steps"][step]

    def _block(self, step: str, message: str, **data):
        st = self.state()
        st["steps"][step] = {"status": "NEEDS_HUMAN", "message": message, **data, "at": now_iso()}
        atomic_write_json(st, self.state_path)
        raise WorkflowBlocked(message)

    # ------------------------------------------------------------------ steps
    def fetch_receptor(self) -> Path:
        if (d := self._done("receptor_input")):
            return Path(d["path"])
        r = self.cfg["receptor"]
        dst = self.dir / "inputs"
        dst.mkdir(exist_ok=True)
        if r.get("pdb_id"):
            pid = r["pdb_id"].upper()
            path = dst / f"{pid}.pdb"
            if not path.is_file():
                urllib.request.urlretrieve(f"https://files.rcsb.org/download/{pid}.pdb", path)
            src = f"RCSB {pid}"
        else:
            src_path = Path(r["file"])
            path = dst / src_path.name
            path.write_bytes(src_path.read_bytes())
            src = str(src_path)
        self.dec.record("workflow.receptor", "source", src, "原始結構永久保存在 workflow/inputs；之後所有建模都從原檔重做，不回收 docking 處理過的 PDB。")
        return Path(self._mark("receptor_input", path=str(path), source=src)["path"])

    def prepare_docking_receptor(self, raw: Path) -> Path:
        if (d := self._done("receptor_docking")):
            return Path(d["path"])
        from .build.receptor import prepare_receptor
        lig_res = {l.get("reference_resname") for l in self.cfg["ligands"] if l.get("reference_resname")}
        box_res = (self.cfg.get("box") or {}).get("from_residue")
        if box_res:
            lig_res.add(box_res)
        man = prepare_receptor(raw, self.dir / "docking_receptor", ph=self.cfg.get("ph", 7.4), decisions=self.dec,
                               keep_hetero=set(self.cfg.get("keep_hetero", [])), ligand_resnames=lig_res,
                               human_choices=self.cfg.get("human_choices", {}).get("receptor"))
        if man["status"] == "NEEDS_HUMAN":
            blocking = [g for g in man["gates"]["gates"] if g["status"] == "NEEDS_HUMAN"]
            self._block("receptor_docking", "受體需要人工決定：" + "；".join(f"{g['name']}：{g['explanation']}（選項：{' / '.join(g['options'])}）" for g in blocking),
                        gates=blocking)
        return Path(self._mark("receptor_docking", path=man["receptor_pdb"])["path"])

    def make_box(self, raw: Path, clean: Path):
        from .docking import Box, box_from_pdb_residue, box_whole_receptor
        b = self.cfg.get("box") or {}
        if b.get("from_residue"):
            return box_from_pdb_residue(raw, b["from_residue"])
        if b.get("center"):
            return Box(tuple(b["center"]), tuple(b.get("size", (22, 22, 22))), "manual", "使用者指定 box。")
        return box_whole_receptor(clean)

    def run_docking(self, clean: Path, raw: Path, progress_cb=None):
        from .docking import dock, LigandInput, DockingResult
        out = self.dir / "docking"
        if (d := self._done("docking")):
            return DockingResult.load(d["result"])
        dcfg = self.cfg.get("docking", {})
        ligs = []
        for l in self.cfg["ligands"]:
            ref = ""
            if l.get("reference_resname"):
                from .build.ligand import extract_hetatm_pose
                try:
                    ref = str(extract_hetatm_pose(raw.read_text(encoding="utf-8", errors="ignore"), l["reference_resname"],
                                                  out / f"ref_{l['name']}.pdb"))
                except ValueError:
                    ref = ""
            ligs.append(LigandInput(name=l["name"], smiles=l.get("smiles", ""), sdf=l.get("sdf", ""), reference_pose=ref))
        res = dock(clean, ligs, self.make_box(raw, clean), out, mode=dcfg.get("mode", "independent"),
                   scoring=dcfg.get("scoring", "vina"), exhaustiveness=dcfg.get("exhaustiveness", 16),
                   n_poses=dcfg.get("n_poses", 9), seed=dcfg.get("seed", 2026), decisions=self.dec, progress_cb=progress_cb)
        self._mark("docking", result=str(out / "docking_results.json"), mode=res.mode)
        return res

    def choose_poses(self, res) -> dict:
        """Recommended pose per entry unless the user overrides; validates joint consistency."""
        if (d := self._done("pose_selection")) and d.get("choices_cfg") == self.cfg.get("pose_choices", {}):
            return d["selection"]
        user = self.cfg.get("pose_choices", {}) or {}
        sel = {"mode": res.mode, "ligands": {}}
        for e in res.entries:
            n = len(e["poses"])
            rank = int(user.get(e["name"], e["recommended_rank"]))
            if not 1 <= rank <= n:
                self._block("pose_selection", f"{e['name']} 只有 {n} 個 pose，無法選第 {rank} 名。")
            p = e["poses"][rank - 1]
            if p.get("clash"):
                self._block("pose_selection", f"{e['name']} 第 {rank} 名 joint pose 配體互相碰撞（最短 {p['min_ll_distance']} Å），請改選。")
            why = e["reason"] if rank == e["recommended_rank"] else f"使用者改選第 {rank} 名（系統推薦第 {e['recommended_rank']} 名：{e['reason']}）"
            for lig in e["ligands"]:
                sel["ligands"][lig] = {"rank": rank, "sdf": e["pose_sdfs"][lig][rank - 1], "score": p["score"],
                                       "rmsd_ref": p.get("rmsd_ref"), "entry": e["name"],
                                       "smiles": e["smiles"][lig] if isinstance(e["smiles"], dict) else e["smiles"]}
            self.dec.record("workflow.pose", e["name"], f"rank {rank}", why, kind="human" if e["name"] in user else "auto")
        self._mark("pose_selection", selection=sel, choices_cfg=user)
        return sel

    def _cases_to_build(self, sel: dict) -> list[dict]:
        systems = self.cfg.get("md", {}).get("systems", ["apo", "docked_single"])
        out = []
        for s in systems:
            if s not in SYSTEM_MODES:
                raise ValueError(f"未知 MD 系統：{s}（可用：{', '.join(SYSTEM_MODES)}）")
        if "apo" in systems:
            out.append({"key": "apo", "mode": "apo", "ligands": []})
        if "docked_single" in systems:
            for name in sel["ligands"]:
                out.append({"key": f"docked_{name}", "mode": "docked_single", "ligands": [name]})
        if "docked_multi" in systems:
            names = list(sel["ligands"])
            if len(names) < 2:
                self._block("md_cases", "docked_multi 需要至少 2 個配體。")
            if sel["mode"] != "simultaneous":
                # independent picks were docked separately: allow only if they do not overlap
                self._check_independent_overlap(sel)
            out.append({"key": "docked_multi", "mode": "docked_multi", "ligands": names})
        return out

    def _check_independent_overlap(self, sel: dict) -> None:
        from rdkit import Chem
        xyz = {}
        for n, s in sel["ligands"].items():
            m = next(Chem.SDMolSupplier(s["sdf"], removeHs=True))
            xyz[n] = m.GetConformer().GetPositions()
        names = list(xyz)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                d = np.sqrt(((xyz[names[i]][:, None] - xyz[names[j]][None]) ** 2).sum(-1)).min()
                if d < 2.5:
                    self._block("md_cases", f"{names[i]} 與 {names[j]} 是分別對接的，選定 pose 互相重疊（{d:.1f} Å）；"
                                "請改用 simultaneous 對接，或為其中一個配體改選不重疊的 pose。")
        self.dec.record("workflow.md", "docked_multi from independent", "allowed",
                        "配體分別對接，但選定 pose 彼此距離 ≥ 2.5 Å，可組成多配體系統；嚴格的共同佔位請用 simultaneous 模式。")

    def build_cases(self, raw: Path, sel: dict) -> dict:
        from .build.pipeline import build_case
        built = dict((self._done("md_cases") or {}).get("cases", {}))
        md = self.cfg.get("md", {})
        drop = {l.get("reference_resname") for l in self.cfg["ligands"] if l.get("reference_resname")}
        for spec in self._cases_to_build(sel):
            if spec["key"] in built and built[spec["key"]].get("status") == "PASS":
                continue
            case = self.project.new_case(f"{self.name}_{spec['key']}")
            refs = [sel["ligands"][n]["smiles"] for n in spec["ligands"]]
            poses = [sel["ligands"][n]["sdf"] for n in spec["ligands"]]
            s = build_case(case, receptor=raw, ligand_references=refs, ligand_poses=poses, ph=self.cfg.get("ph", 7.4),
                           padding_nm=md.get("padding_nm", 1.0), keep_hetero=set(self.cfg.get("keep_hetero", [])),
                           extra_ligand_resnames=drop)
            built[spec["key"]] = {"case_id": case.case_id, "mode": spec["mode"], "ligands": spec["ligands"],
                                  "status": s["status"], "blocking": s.get("blocking"), "blocking_detail": s.get("blocking_detail")}
            self._mark("md_cases", cases=built)
            if s["status"] != "PASS":
                self._block("md_cases", f"{spec['key']} 建模需要人工決定：{s.get('blocking')}：{s.get('blocking_detail')}", cases=built)
        return built

    def run_md(self, built: dict, make_factory: Callable, *, should_pause=None, progress_cb=None) -> dict:
        from .engine import make_protocol, run_replicas
        md = self.cfg.get("md", {})
        runs = dict((self._done("md_runs") or {}).get("runs", {}))
        for key, c in built.items():
            if runs.get(key, {}).get("status") == "COMPLETE":
                continue
            case = self.project.case(c["case_id"])
            proto = make_protocol(md.get("tier", "teaching"), production_ns=md.get("production_ns"), replicas=md.get("replicas", 1))
            if md.get("stage_overrides"):
                for st in proto.stages:
                    for k, v in md["stage_overrides"].get(st.name, {}).items():
                        setattr(st, k, v)
            group = runs.get(key, {}).get("group_id") or f"wf_{self.name}_{key}"
            summary = run_replicas(case, proto, make_factory(case, proto), n=proto.replicas, should_pause=should_pause,
                                   progress_cb=progress_cb, group_id=group)
            statuses = {r["status"] for r in summary["runs"]}
            status = "COMPLETE" if statuses == {"COMPLETE"} and len(summary["runs"]) == proto.replicas else \
                     ("PAUSED" if "PAUSED" in statuses else "NEEDS_HUMAN")
            runs[key] = {"case_id": case.case_id, "group_id": group, "status": status,
                         "run_ids": [r["run_id"] for r in summary["runs"]]}
            self._mark("md_runs", runs=runs)
            if status == "PAUSED":
                return runs
            if status == "NEEDS_HUMAN":
                reason = next((r.get("reason") for r in summary["runs"] if r["status"] == "NEEDS_HUMAN"), "")
                self._block("md_runs", f"{key} 的 MD 需要人工決定：{reason}", runs=runs)
        return runs

    def analyse(self, runs: dict) -> dict:
        from .analysis.traj import analyse_run, compare_runs
        out = {}
        metrics = {}
        for key, r in runs.items():
            case = self.project.case(r["case_id"])
            top = load_json(case.build_dir / "build_manifest.json", {}).get("topology_pdb")
            rid = r["run_ids"][0]
            run_dir = case.dir / "runs" / rid
            man = load_json(run_dir / "analysis" / "analysis_manifest.json", {})
            if man.get("status") != "PASS":
                man = analyse_run(run_dir, top, label=key)
            out[key] = man
            metrics[key] = load_json(man["metrics_file"], {})
        comp = compare_runs(metrics, self.dir / "figures") if len(metrics) > 1 else {}
        self._mark("analysis", summaries=out, comparison=comp)
        return {"summaries": out, "comparison": comp}

    def binding(self, runs: dict, built: dict, platform, *, should_pause=None, progress_cb=None) -> dict:
        from .sampling.binding import run_binding, BindingConfig
        b = self.cfg.get("binding", {})
        if not b.get("enabled"):
            return {}
        results = dict((self._done("binding") or {}).get("results", {}))
        valid = {f.name for f in fields(BindingConfig)}
        cfg = BindingConfig(**{k: v for k, v in (b.get("config") or {}).items() if k in valid})
        for name in b.get("ligands") or [n for c in built.values() if c["mode"] == "docked_single" for n in c["ligands"]]:
            key = f"docked_{name}"
            if key not in runs or results.get(name, {}).get("status") == "PASS":
                continue
            case = self.project.case(runs[key]["case_id"])
            bm = load_json(case.build_dir / "build_manifest.json", {})
            run_dir = case.dir / "runs" / runs[key]["run_ids"][0]
            start = run_dir / "stages" / "production" / "production_state.xml"
            res = run_binding(bm["system_xml"], bm["topology_pdb"], start, self.dir / "binding" / name,
                              ligand_resname="L01", config=cfg, platform_name=platform.name,
                              platform_properties=platform.properties, decisions=self.dec, should_pause=should_pause,
                              progress_cb=progress_cb)
            results[name] = {"status": res.status, "delta_pmf_kj_mol": res.delta_pmf_kj_mol,
                             "dG_standard_kj_mol": res.dG_standard_kj_mol, "dG_standard_kcal_mol": res.dG_standard_kcal_mol,
                             "r_min_nm": res.pmf.get("r_min_nm"), "figures": res.figures, "caveats": res.caveats,
                             "max_force": res.smd.get("max_force_kj_mol_nm"), "work": res.smd.get("final_work_kj_mol")}
            if res.status == "PAUSED":
                st = self.state(); st["steps"]["binding"] = {"status": "PAUSED", "results": results}; atomic_write_json(st, self.state_path)
                return results
        self._mark("binding", results=results)
        return results

    # ------------------------------------------------------------------ driver
    def run(self, make_factory: Callable, platform, *, should_pause=None, progress_cb=None) -> dict:
        raw = self.fetch_receptor()
        clean = self.prepare_docking_receptor(raw)
        sel = None
        systems = self.cfg.get("md", {}).get("systems", ["apo", "docked_single"])
        if self.cfg.get("ligands") and (any(s != "apo" for s in systems) or self.cfg.get("docking", {}).get("always")):
            res = self.run_docking(clean, raw, progress_cb=progress_cb)
            sel = self.choose_poses(res)
        built = self.build_cases(raw, sel or {"mode": "none", "ligands": {}})
        runs = self.run_md(built, make_factory, should_pause=should_pause, progress_cb=progress_cb)
        if any(r["status"] == "PAUSED" for r in runs.values()):
            return {"status": "PAUSED", "state": self.state()}
        ana = self.analyse(runs)
        bind = self.binding(runs, built, platform, should_pause=should_pause, progress_cb=progress_cb)
        if any(v.get("status") == "PAUSED" for v in bind.values()):
            return {"status": "PAUSED", "state": self.state()}
        from .report.workflow_report import build_workflow_report
        rep = build_workflow_report(self)
        self._mark("report", path=str(rep))
        return {"status": "COMPLETE", "report": str(rep), "binding": bind, "analysis": ana}
