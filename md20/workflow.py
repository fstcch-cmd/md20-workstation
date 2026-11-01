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
         "padding_nm": null,                  # null = tier default (0.8 nm teaching/classroom, 1.0 research)
         "box_shape": "dodecahedron",         # 71 % of a cube's water for the same image distance
         "ionic_strength_molar": 0.15},       # 0 = neutralising counter-ions only
  "binding": {"enabled": true, "ligands": ["BEN"], "config": {"pull_velocity_nm_per_ps": 0.01}},
  "screen": {"library": "compounds.xlsx", "exhaustiveness": 8, "n_poses": 3, "top_n": 20, "select": [], "next_mode": "independent"}
                                            # optional HTS pre-screen (docs/specs/hts_screen.md): selected compounds are
                                            # appended to `ligands` and docked for real with `docking` settings
}
"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import fields
from pathlib import Path
from typing import Callable

import numpy as np

from .project import Project
from .util import atomic_write_json, load_json, now_iso, ensure_dir, safe_name

SYSTEM_MODES = ("apo", "docked_single", "docked_multi")
# minimum protein–box-edge distance when md.padding_nm is not given (rhombic dodecahedron box)
TIER_PADDING_NM = {"classroom": 0.8, "teaching": 0.8, "research": 1.0}



def manifest_ligands(bm: dict) -> list[dict]:
    """Ligand records that carry topology atom indices.

    build_case() rewrites build_manifest.json after assembly; the indices live in ``assembly.ligands``
    (written by assemble_system).  Older manifests only have the pre-assembly records at top level, which
    carry no indices — callers must then block, not guess."""
    asm = (bm.get("assembly") or {}).get("ligands") or []
    if any(l.get("heavy_atom_indices") or l.get("atom_indices") for l in asm):
        return asm
    return bm.get("ligands") or []

def fetch_pdb(pid: str, path: Path, *, timeout: float = 60.0) -> Path:
    """Download an RCSB entry to a temporary file, check it is really a PDB, then move it into place: a broken
    connection or an HTML error page must never be left behind as `<ID>.pdb` and reused on the next run."""
    tmp = path.with_suffix(".pdb.part")
    req = urllib.request.Request(f"https://files.rcsb.org/download/{pid}.pdb", headers={"User-Agent": "MD20-workstation"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as fh:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
        text = tmp.read_text(encoding="utf-8", errors="ignore")
        if not any(l.startswith(("ATOM  ", "HETATM")) for l in text.splitlines()) or not text.rstrip().endswith("END"):
            raise RuntimeError(f"RCSB 回傳的 {pid}.pdb 不完整或不是 PDB（{len(text)} 字元）")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def metal_indices_from_manifest(bm: dict) -> list[int]:
    """Metals the bonded model tied to the protein: they belong to the protein anchor when re-centering."""
    plans = ((bm.get("restraints") or {}).get("metals") or {}).get("plans") or []
    return [int(p["metal_index"]) for p in plans if p.get("action") == "bonded" and p.get("metal_index") is not None]


class WorkflowBlocked(RuntimeError):
    """A step needs a human decision; message explains which and why."""


def example_config(screen: bool = False) -> dict:
    if screen:
        return {
            "name": "trypsin_screen",
            "receptor": {"pdb_id": "3PTB"},
            "ph": 7.4, "keep_hetero": ["CA"],
            "box": {"from_residue": "BEN"},
            "ligands": [{"name": "BEN", "smiles": "NC(=[NH2+])c1ccccc1", "reference_resname": "BEN"}],   # co-crystal self-check
            "screen": {"library": "compound_library.xlsx", "exhaustiveness": 8, "n_poses": 3, "top_n": 20,
                       "allow_partial": False, "allow_name_lookup": False,
                       "filters": {"min_heavy_atoms": 5, "max_heavy_atoms": 80, "min_mw": 100, "max_mw": 900},
                       "select": [], "next_mode": "independent"},
            "docking": {"mode": "independent", "scoring": "vina", "exhaustiveness": 16, "n_poses": 9},
            "pose_choices": {},
            "md": {"systems": ["apo", "docked_single"], "tier": "teaching", "replicas": 1, "production_ns": None, "padding_nm": None, "box_shape": "dodecahedron", "ionic_strength_molar": 0.15},
            "binding": {"enabled": False, "ligands": [], "config": {}},
        }
    return {
        "name": "trypsin_benzamidine",
        "receptor": {"pdb_id": "3PTB"},
        "ph": 7.4, "keep_hetero": ["CA"],
        "box": {"from_residue": "BEN"},
        "ligands": [{"name": "BEN", "smiles": "NC(=[NH2+])c1ccccc1", "reference_resname": "BEN"}],
        "docking": {"mode": "independent", "scoring": "vina", "exhaustiveness": 16, "n_poses": 9},
        "pose_choices": {},
        "md": {"systems": ["apo", "docked_single"], "tier": "teaching", "replicas": 1, "production_ns": None, "padding_nm": None, "box_shape": "dodecahedron", "ionic_strength_molar": 0.15},
        "binding": {"enabled": True, "ligands": ["BEN"], "config": {}},
    }


# keys that hold *human decisions* written back by gates/GUI (never re-derivable); re-running `pipeline run` from
# the student's original file must not silently discard them
DECISION_KEYS: tuple[tuple[str, ...], ...] = (
    ("pose_choices",), ("human_choices",), ("structure_override",), ("metal_policy",), ("metal_params",), ("peptide_policy",),
    ("docking", "skip_redock"), ("box", "allow_blind"), ("binding", "manual_windows"),
    ("screen", "select"), ("screen", "next_mode"), ("screen", "allow_partial"),
)
LIGAND_DECISION_KEYS = ("cpp_override", "cpp_evidence", "target_location")


def _get_path(d: dict, path: tuple) -> tuple[bool, object]:
    node = d
    for k in path:
        if not isinstance(node, dict) or k not in node:
            return False, None
        node = node[k]
    return True, node


def merge_human_decisions(new: dict, existing: dict) -> tuple[dict, list[str]]:
    """Carry decision keys from the workflow's own config.json into a freshly loaded config when the new one does
    not set them.  Returns (merged, carried-key names)."""
    import copy as _copy
    out = _copy.deepcopy(new)
    carried = []
    for path in DECISION_KEYS:
        has_old, old = _get_path(existing, path)
        has_new, cur = _get_path(out, path)
        if not has_old or old in (None, {}, [], False):
            continue
        if has_new and cur not in (None, {}, [], False):
            continue
        node = out
        for k in path[:-1]:
            node = node.setdefault(k, {})
        node[path[-1]] = _copy.deepcopy(old)
        carried.append(".".join(path))
    old_ligs = {l.get("name"): l for l in existing.get("ligands") or [] if isinstance(l, dict)}
    for l in out.get("ligands") or []:
        o = old_ligs.get(l.get("name"))
        if not o:
            continue
        for k in LIGAND_DECISION_KEYS:
            if o.get(k) and not l.get(k):
                l[k] = o[k]
                carried.append(f"ligands[{l.get('name')}].{k}")
    return out, carried


class Workflow:
    def __init__(self, project: Project, config: dict, *, create: bool = True):
        self.project = project
        self.cfg = config
        self.name = safe_name(config.get("name", "workflow"))
        self.dir = project.dir / "workflows" / self.name
        if create:
            ensure_dir(self.dir)
        self.state_path = self.dir / "state.json"
        self.dec = project.decisions
        cfg_path = self.dir / "config.json"
        if create and (not cfg_path.is_file() or load_json(cfg_path, {}) != config):   # only touch the file when the content changes
            atomic_write_json(config, cfg_path)

    @classmethod
    def open(cls, project: Project, name: str) -> "Workflow":
        """An existing workflow by name, from its own config.json (the file that carries human decisions)."""
        p = project.dir / "workflows" / safe_name(name) / "config.json"
        if not p.is_file():
            raise FileNotFoundError(f"找不到 workflow {name}（{p}）")
        return cls(project, load_json(p, {}))

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
            pid = str(r["pdb_id"]).strip().upper()
            if not re.fullmatch(r"[0-9][A-Z0-9]{3}", pid):
                self._block("receptor_input", f"PDB ID「{r['pdb_id']}」格式不對（4 個英數字，例如 3PTB）。")
            path = dst / f"{pid}.pdb"
            if not path.is_file():
                fetch_pdb(pid, path)
            src = f"RCSB {pid}"
        else:
            src_path = Path(r["file"])
            path = dst / src_path.name
            path.write_bytes(src_path.read_bytes())
            src = str(src_path)
        self.dec.record("workflow.receptor", "source", src, "原始結構永久保存在 workflow/inputs；之後所有建模都從原檔重做，不回收 docking 處理過的 PDB。")
        return Path(self._mark("receptor_input", path=str(path), source=src)["path"])

    OVERRIDE_KEYS = {"resolution": "resolution", "R-free": "r_free", "ligand occupancy": "ligand_occupancy",
                     "pocket occupancy": "pocket"}

    def structure_gate(self, raw: Path, box_res: str | None) -> dict:
        """WP6: structure confidence + metals in the pocket, before anything is docked."""
        from .build.structure_gate import structure_confidence
        b = self.cfg.get("box") or {}
        center = b.get("center")
        res = str(box_res).split(":")[0].split()[0] if box_res else None
        mp = self.cfg.get("metal_policy") or {}
        rep = structure_confidence(raw.read_text(encoding="utf-8", errors="ignore"), pocket_center=center,
                                   ligand_resname=res, metal_policy=mp)
        over = self.cfg.get("structure_override") or {}
        blocking = []
        for g in rep.gates:
            if g.status != "NEEDS_HUMAN":
                continue
            key = self.OVERRIDE_KEYS.get(g.name)
            if key and over.get(key):
                self.dec.record("structure.gate", g.name, "override", f"{g.explanation}（使用者選擇仍要使用：{over[key]}）", kind="human")
                continue
            blocking.append(g)
        for rn, pol in mp.items():
            if str(pol).startswith("keep"):
                kh = set(self.cfg.get("keep_hetero", [])); kh.add(rn.split(":")[0]); self.cfg["keep_hetero"] = sorted(kh)
        atomic_write_json(rep.to_dict(), self.dir / "structure_gates.json")
        if blocking:
            self._block("structure_gate", "結構可信度：" + "；".join(f"{g.name}：{g.explanation}（選項：{' / '.join(g.options)}）"
                                                                  for g in blocking), gates=[g.to_dict() for g in blocking])
        return rep.to_dict()

    def prepare_docking_receptor(self, raw: Path) -> Path:
        if (d := self._done("receptor_docking")):
            return Path(d["path"])
        from .build.receptor import prepare_receptor
        lig_res = {l.get("reference_resname") for l in self.cfg.get("ligands") or [] if l.get("reference_resname")}
        box_res = (self.cfg.get("box") or {}).get("from_residue")
        if box_res:
            lig_res.add(box_res)
        self.structure_gate(raw, box_res)
        man = prepare_receptor(raw, self.dir / "docking_receptor", ph=self.cfg.get("ph", 7.4), decisions=self.dec,
                               keep_hetero=set(self.cfg.get("keep_hetero", [])), ligand_resnames=lig_res,
                               human_choices=self.cfg.get("human_choices", {}).get("receptor"),
                               exclude_chains=set(self.cfg["receptor"].get("exclude_chains", [])))
        if man["status"] == "NEEDS_HUMAN":
            blocking = [g for g in man["gates"]["gates"] if g["status"] == "NEEDS_HUMAN"]
            self._block("receptor_docking", "受體需要人工決定：" + "；".join(f"{g['name']}：{g['explanation']}（選項：{' / '.join(g['options'])}）" for g in blocking),
                        gates=blocking)
        prot = self.protonation_review(raw, Path(man["receptor_pdb"]))
        return Path(self._mark("receptor_docking", path=man["receptor_pdb"], protonation=prot)["path"])

    def protonation_review(self, raw: Path, clean: Path) -> dict:
        """WP8 review mode: PROPKA on the cleaned receptor; flag pocket residues (never blocks, never edits)."""
        from .build.protonation import propka_available, run_pdb2pqr, pocket_protonation_review
        ph = self.cfg.get("ph", 7.4)
        if not propka_available():
            return {"method": "pdbfixer", "note": "pdb2pqr/propka 未安裝；只用 PDBFixer 固定規則。"}
        try:
            box = self.make_box(raw, clean)
            res = run_pdb2pqr(clean, self.dir / "protonation", ph=ph)
            flags = pocket_protonation_review(res["pka_table"], clean, box.center, ph=ph)
        except Exception as exc:  # noqa: BLE001
            self.dec.record("build.protonation", "PROPKA", "failed", f"PROPKA 執行失敗（{str(exc)[:200]}）；改用 PDBFixer 固定規則。")
            return {"method": "pdbfixer", "note": f"PROPKA 失敗：{str(exc)[:200]}"}
        for f in flags:
            self.dec.record("build.protonation", f["residue"], f"pKa {f['pka']:.1f}", "；".join(f["flags"]) +
                            "。建模仍用固定規則；若此殘基參與結合，請考慮指定其質子化狀態後重建。")
        return {"method": "propka-review", "ph": ph, "pocket_flags": flags}

    def make_box(self, raw: Path, clean: Path):
        from .docking import Box, box_from_pdb_residue, box_whole_receptor
        b = self.cfg.get("box") or {}
        if b.get("from_residue"):
            return box_from_pdb_residue(raw, b["from_residue"])
        if b.get("center"):
            return Box(tuple(b["center"]), tuple(b.get("size", (22, 22, 22))), "manual", "使用者指定 box。")
        return box_whole_receptor(clean)

    @staticmethod
    def cocrystal_ligands(raw: Path) -> set[str]:
        """Hetero residues in the raw PDB that look like real ligands (not water/ions/buffers)."""
        from .build.receptor import JUNK_HETERO
        names = set()
        for line in raw.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("HETATM"):
                rn = line[17:20].strip()
                if rn not in JUNK_HETERO and rn not in {"HOH", "WAT", "DOD"}:
                    names.add(rn)
        return names

    def docking_preflight(self, raw: Path) -> None:
        """S9: redocking self-check is mandatory for co-crystal boxes; blind boxes need explicit consent."""
        b, dcfg = self.cfg.get("box") or {}, self.cfg.get("docking", {})
        refs = {l.get("reference_resname") for l in self.cfg.get("ligands") or [] if l.get("reference_resname")}
        if b.get("from_residue"):
            res = str(b["from_residue"]).split(":")[0].split()[0]
            if res not in refs:
                if dcfg.get("skip_redock"):
                    self.dec.record("docking.redock", res, "skipped", "使用者明確設定 docking.skip_redock；本次對接沒有共晶自檢，"
                                    "pose 可信度未經驗證，報告將標註。", kind="human")
                else:
                    msg = (f"box 取自共晶配體 {res}，但沒有任何配體以它作為 reference_resname 進行 redocking 自檢。"
                           f"請加入一個 {{name: {res}, smiles: <共晶配體 SMILES>, reference_resname: {res}}}，"
                           f"或設定 docking.skip_redock: true（會記錄在報告）。")
                    self._block("docking_preflight", msg, gates=[{
                        "name": "redocking", "status": "NEEDS_HUMAN", "explanation": msg, "evidence": {"residue": res},
                        "options": [f"加入共晶配體 {res} 作為 redocking 參考（需要 SMILES）",
                                    "docking.skip_redock: true（不做自檢，報告標註）"]}])
            else:
                self.dec.record("docking.redock", res, "required",
                                "共晶 box：對接共晶配體並與晶體姿勢比較，RMSD > 2 Å 時不推薦任何 pose。")
        elif not b.get("center"):
            co = self.cocrystal_ligands(raw)
            if co and not b.get("allow_blind"):
                msg = (f"結構中有共晶配體（{', '.join(sorted(co))}），卻使用全蛋白盲對接。"
                       f"建議 box.from_residue: {sorted(co)[0]}；若確定要盲對接，請設定 box.allow_blind: true。")
                self._block("docking_preflight", msg, gates=[{
                    "name": "blind docking", "status": "NEEDS_HUMAN", "explanation": msg,
                    "evidence": {"cocrystal": sorted(co)},
                    "options": [f"box.from_residue: {r}" for r in sorted(co)] + ["box.allow_blind: true（盲對接，報告標註）"]}])
            if co or b.get("allow_blind"):
                self.dec.record("docking.box", "blind", "allowed", "使用者明確允許盲對接；盲對接分數與口袋排名可信度較低。",
                                kind="human" if b.get("allow_blind") else "auto")

    def _peptide_preflight(self, l: dict) -> str:
        """Peptide ligand: CPP gate before docking, docking SMILES from the sequence."""
        from .build.peptide import clean_sequence, peptide_smiles, cpp_gate
        from .build.gates import NEEDS_HUMAN
        seq = clean_sequence(l["sequence"])
        gate, rec = cpp_gate(seq, target_location=l.get("target_location"), experimental_evidence=l.get("cpp_evidence"))
        # record the CPP result (incl. redesign suggestions) first, so a blocked run still surfaces them in state/report
        self.dec.record("peptide.cpp", l["name"], rec.get("status"), gate.explanation,
                        kind="human" if l.get("cpp_override") else "auto")
        st = self.state(); st.setdefault("cpp", {})[l["name"]] = {**rec, "gate": gate.status, "explanation": gate.explanation,
                                                                  "override": bool(l.get("cpp_override"))}
        atomic_write_json(st, self.state_path)
        if gate.status == NEEDS_HUMAN and not l.get("cpp_override"):
            self._block("docking_preflight", f"胜肽 {l['name']}：{gate.explanation}（確認要繼續請在該配體設定 cpp_override 並說明理由）",
                        gates=[gate.to_dict()], ligand=l["name"])
        return peptide_smiles(seq, l.get("termini", "charged"))

    # ------------------------------------------------------------------ HTS pre-screen (docs/specs/hts_screen.md)
    def _screen_config(self):
        from .docking.screen import ScreenConfig
        sc = dict(self.cfg.get("screen") or {})
        sc.setdefault("ph", float(self.cfg.get("ph", 7.4)))              # same pH as the receptor protonation
        sc.setdefault("protonation", (self.cfg.get("docking") or {}).get("protonation", "auto"))
        return ScreenConfig.from_cfg(sc)

    def _library_path(self) -> Path:
        lib = (self.cfg.get("screen") or {}).get("library") or ""
        if not lib:
            self._block("screen_library", "screen.library 未設定：請指定化合物庫（.xlsx/.csv），或移除 screen 區塊。")
        p = Path(lib)
        if not p.is_absolute():
            p = (self.dir / p) if (self.dir / p).is_file() else p
        if not p.is_file():
            self._block("screen_library", f"找不到化合物庫檔案：{lib}")
        return p

    def run_screen_library(self, progress_cb=None) -> dict:
        """Read the sheet and fetch one 3D SDF per compound (cached); keyed on the sheet's fingerprint."""
        from .util.hashing import cheap_fingerprint, verify_cheap_fingerprint
        from .docking.library import read_library, resolve_library, LibraryFilters, problem_entries
        lib = self._library_path()
        key = {"library": str(lib), "fingerprint": {k: v for k, v in cheap_fingerprint(lib).items() if k != "mtime_ns"},
               "filters": (self.cfg.get("screen") or {}).get("filters") or {},
               "allow_name_lookup": bool((self.cfg.get("screen") or {}).get("allow_name_lookup"))}
        if (d := self._done("screen_library")) and d.get("key") == key and verify_cheap_fingerprint(lib, d["key"]["fingerprint"] | {"bytes": key["fingerprint"]["bytes"]}):
            return load_json(d["manifest"], {"entries": {}})
        scfg = self._screen_config()
        entries, problems = read_library(lib, sheet=scfg.sheet)
        if problems:
            self._block("screen_library", "化合物庫有問題，請修正後重跑：\n" + "\n".join(f"• {p}" for p in problems[:40])
                        + (f"\n…另有 {len(problems) - 40} 項" if len(problems) > 40 else ""),
                        gates=[{"name": "library", "status": "NEEDS_HUMAN", "explanation": "\n".join(problems[:40]),
                                "options": ["修正化合物庫檔案後重新執行"]}])
        self.dec.record("screen.library", "input", {"file": str(lib), "rows": len(entries)},
                        f"化合物庫 {lib.name}：{len(entries)} 筆；來源優先序 sdf > smiles > pubchem_cid > inchikey > chembl_id > ccd。"
                        + ("名稱查詢已啟用（可能對應錯分子，每筆記錄）。" if scfg.allow_name_lookup else "名稱查詢關閉（寧可擋也不要猜）。"))
        out = self.dir / "screen" / "library"
        man = resolve_library(entries, out, filters=LibraryFilters.from_cfg(key["filters"]), allow_name_lookup=scfg.allow_name_lookup,
                              decisions=self.dec, progress_cb=progress_cb, workers=scfg.workers)
        bad = problem_entries(man)
        if bad and not scfg.allow_partial:
            lines = [f"• {b['name']}（第 {b.get('row', '?')} 列）：{b['status']} — {b.get('error', '')}" for b in bad[:40]]
            msg = (f"化合物庫 {man['summary']['total']} 筆中有 {len(bad)} 筆無法使用（{man['summary']['FAILED']} 失敗、"
                   f"{man['summary']['SKIPPED']} 略過）。請修正庫檔重跑，或設定 screen.allow_partial: true 略過它們（報告會列出）。\n" + "\n".join(lines))
            self._block("screen_library", msg, manifest=str(out / "library_manifest.json"),
                        gates=[{"name": "library partial", "status": "NEEDS_HUMAN", "explanation": msg,
                                "evidence": {"failed": [b["name"] for b in bad]},
                                "options": ["修正化合物庫檔案後重新執行", "screen.allow_partial: true（略過失敗的化合物，報告標註）"]}])
        if bad:
            self.dec.record("screen.library", "partial", [b["name"] for b in bad],
                            f"使用者設定 screen.allow_partial：{len(bad)} 個化合物未納入篩選（{', '.join(b['name'] for b in bad[:10])}"
                            + ("…" if len(bad) > 10 else "") + "）。", kind="human")
        self._mark("screen_library", manifest=str(out / "library_manifest.json"), key=key, summary=man["summary"])
        return man

    def run_screen_docking(self, clean: Path, raw: Path, manifest: dict, progress_cb=None, should_stop=None) -> dict | None:
        """Reduced-search independent docking of every usable compound; None when paused."""
        from .docking.library import usable_entries
        from .docking.screen import screen_dock, rank_screen, write_ranking_csv, screen_plots, failed_rows
        scfg = self._screen_config()
        box = self.make_box(raw, clean)
        key = {"library": (self._done("screen_library") or {}).get("key"), "box": box.to_dict(), "params": scfg.params()}
        if (d := self._done("screen_docking")) and d.get("key") == key:
            return load_json(d["results"], {"entries": {}})
        self.docking_preflight(raw)
        out = self.dir / "screen"
        ents = usable_entries(manifest)
        if not ents:
            self._block("screen_docking", "化合物庫沒有任何可用的化合物。")
        res = screen_dock(clean, ents, box, out, scfg, decisions=self.dec, progress_cb=progress_cb, should_stop=should_stop)
        if res.get("paused"):
            return None
        rows = rank_screen(res, top_n=scfg.top_n)
        write_ranking_csv(rows, out / "screen_ranking.csv")
        try:
            plots = screen_plots(rows, out / "plots", top_n=scfg.top_n)
        except Exception as exc:  # noqa: BLE001  — a plotting failure must not hide the numbers
            plots = {"error": f"{type(exc).__name__}: {exc}"}
            self.dec.record("screen.docking", "plots", "failed", f"篩選圖產生失敗（{str(exc)[:200]}）；排名表仍可用。")
        bad = failed_rows(res, manifest)
        dock_failed = [b for b in bad if b["stage"] == "docking"]
        if dock_failed and not scfg.allow_partial:
            msg = (f"{len(dock_failed)} 個化合物對接失敗（其餘 {len(rows)} 個已完成）。請檢查後重跑，或設定 screen.allow_partial: true。\n"
                   + "\n".join(f"• {b['name']}：{b['error']}" for b in dock_failed[:40]))
            self._block("screen_docking", msg, results=str(out / "screen_results.json"),
                        gates=[{"name": "screen partial", "status": "NEEDS_HUMAN", "explanation": msg,
                                "evidence": {"failed": [b["name"] for b in dock_failed]},
                                "options": ["檢查失敗原因後重新執行", "screen.allow_partial: true（略過失敗的化合物，報告標註）"]}])
        n_close = sum(1 for r in rows if r.get("indistinguishable_from_top"))
        self.dec.record("screen.docking", "ranking", {"n": len(rows), "best": rows[0]["name"] if rows else None,
                                                      "within_1kcal_of_best": n_close},
                        f"篩選完成：{len(rows)} 個化合物有分數；第 1 名 {rows[0]['name'] if rows else '—'}"
                        f"（{rows[0]['score'] if rows else '—'} kcal/mol），其中 {n_close} 個與第 1 名差距 < 1 kcal/mol，"
                        "在 Vina 誤差內、名次沒有統計意義。篩選只用來剔除，正式對接與 MD 才做完整搜尋。")
        self._mark("screen_docking", results=str(out / "screen_results.json"), ranking=str(out / "screen_ranking.csv"),
                   plots=plots, key=key, n_scored=len(rows), failed=[b["name"] for b in bad])
        return res

    def screen_selection(self, manifest: dict, results: dict) -> list[dict]:
        """Gate: the student picks which screened compounds go on (screen.select); returns the merged ligand list."""
        from .docking.screen import rank_screen
        scfg = self._screen_config()
        sel = list((self.cfg.get("screen") or {}).get("select") or [])
        mode = (self.cfg.get("screen") or {}).get("next_mode") or "independent"
        rows = rank_screen(results, top_n=scfg.top_n)
        by_name = {r["name"]: r for r in rows}
        if not sel:
            top = [r["name"] for r in rows[:scfg.top_n]]
            msg = (f"篩選完成（{len(rows)} 個化合物有分數）。請在 GUI「篩選」分頁勾選要進入下一步的化合物，或在 config 設定 "
                   f"screen.select: [名稱…] 與 screen.next_mode: independent|simultaneous。前 {len(top)} 名：{', '.join(top)}")
            self._block("screen_selection", msg, gates=[{"name": "screen selection", "status": "NEEDS_HUMAN", "explanation": msg,
                                                        "evidence": {"top": top}, "options": ["在「篩選」分頁勾選化合物"]}])
        missing = [n for n in sel if n not in by_name]
        if missing:
            self._block("screen_selection", f"screen.select 裡的 {', '.join(missing)} 沒有篩選分數（不在庫中、失敗或被略過）。")
        if mode not in ("independent", "simultaneous"):
            self._block("screen_selection", f"screen.next_mode 必須是 independent 或 simultaneous（現在是 {mode}）。")
        if mode == "simultaneous" and len(sel) < 2:
            self._block("screen_selection", "多配體同時對接至少要選 2 個化合物。")
        explicit = list(self.cfg.get("ligands") or [])
        names = {l["name"] for l in explicit}
        # the library SDF (input conformer) goes on, not the screen pose: the final docking re-searches with full exhaustiveness
        merged = explicit + [{"name": n, "sdf": (manifest["entries"].get(n) or {}).get("path", ""), "smiles": by_name[n]["smiles"],
                              "from_screen": True, "screen_rank": by_name[n]["rank"], "screen_score": by_name[n]["score"]}
                             for n in sel if n not in names]
        self.dec.record("screen.selection", "selected", sel,
                        f"使用者從篩選結果選出 {len(sel)} 個化合物（{', '.join(sel)}）進入正式對接，模式 {mode}；"
                        f"與使用者明列的 {len(explicit)} 個配體合併，正式對接用完整 exhaustiveness 重新搜尋。", kind="human")
        self._mark("screen_selection", selected=sel, next_mode=mode, ligands=merged)
        return merged

    def apply_screen(self, clean: Path, raw: Path, progress_cb=None, should_stop=None) -> bool:
        """Run the whole pre-screen when `screen` is configured; mutates cfg.ligands/docking.mode for this run.
        Returns False when paused."""
        if not self.cfg.get("screen"):
            return True
        self.cfg.setdefault("ligands", [])
        man = self.run_screen_library(progress_cb=progress_cb)
        res = self.run_screen_docking(clean, raw, man, progress_cb=progress_cb, should_stop=should_stop)
        if res is None:
            return False
        merged = self.screen_selection(man, res)
        self.cfg["ligands"] = merged
        self.cfg.setdefault("docking", {})["mode"] = (self.cfg.get("screen") or {}).get("next_mode") or "independent"
        return True

    def run_docking(self, clean: Path, raw: Path, progress_cb=None):
        from .docking import dock, LigandInput, DockingResult
        out = self.dir / "docking"
        if (d := self._done("docking")):
            return DockingResult.load(d["result"])
        self.docking_preflight(raw)
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
            smi = l.get("smiles", "")
            if l.get("sequence"):
                smi = self._peptide_preflight(l)
            ligs.append(LigandInput(name=l["name"], smiles=smi, sdf=l.get("sdf", ""), reference_pose=ref,
                                    protonation=l.get("protonation") or dcfg.get("protonation", "auto"),
                                    ph=float(self.cfg.get("ph", 7.4))))
        exh = dcfg.get("exhaustiveness", 16)
        if any(l.get("sequence") for l in self.cfg["ligands"]) and exh < 32:
            self.dec.record("docking.setup", "exhaustiveness", 32, f"胜肽配體自由度高，exhaustiveness 由 {exh} 自動提高到 32。")
            exh = 32
        res = dock(clean, ligs, self.make_box(raw, clean), out, mode=dcfg.get("mode", "independent"),
                   scoring=dcfg.get("scoring", "vina"), exhaustiveness=exh,
                   n_poses=dcfg.get("n_poses", 9), seed=dcfg.get("seed", 2026), decisions=self.dec, progress_cb=progress_cb)
        self._mark("docking", result=str(out / "docking_results.json"), mode=res.mode)
        return res

    def _screen_cfg(self):
        from .docking.pose_screen import PoseScreenConfig
        return PoseScreenConfig.from_cfg(self.cfg.get("docking", {}).get("pose_md_screen"),
                                         tier=self.cfg.get("md", {}).get("tier", "teaching"))

    def choose_poses(self, res, screen: Callable | None = None) -> dict | None:
        """Recommended pose per entry unless the user overrides; validates joint consistency.

        WP5: with `docking.pose_md_screen.enabled`, candidate poses are screened by short MD before the pose is
        fixed (`screen(entry, rank) → assessment`, None = paused).  Returns None when the screen paused."""
        from .docking.pose_screen import screen_candidates, decide
        scfg = self._screen_cfg()
        key = {"choices": self.cfg.get("pose_choices", {}), "screen": scfg.to_dict()}
        if (d := self._done("pose_selection")) and d.get("choices_cfg") == key:
            return d["selection"]
        user = self.cfg.get("pose_choices", {}) or {}
        sel = {"mode": res.mode, "ligands": {}}
        cache_path = self.dir / "pose_screen.json"
        cache = self._pose_screen_cache(cache_path)
        for e in res.entries:
            n = len(e["poses"])
            if e.get("recommended_rank") is None and e["name"] not in user:
                self._block("pose_selection",
                            f"{e['name']}：系統沒有推薦任何 pose（{e.get('reason') or '無合格候選'}）。"
                            f"請在 pose_choices 指定名次，或檢查盒子/口袋設定後重跑對接。")
            rank = int(user.get(e["name"], e["recommended_rank"]))
            if not 1 <= rank <= n:
                self._block("pose_selection", f"{e['name']} 只有 {n} 個 pose，無法選第 {rank} 名。")
            why = e["reason"] if rank == e["recommended_rank"] else f"使用者改選第 {rank} 名（系統推薦第 {e['recommended_rank']} 名：{e['reason']}）"
            screen_info = None
            if e["name"] in user:
                pass                                   # explicit human choice is never overridden by the screen
            elif not scfg.enabled:
                self.dec.record("workflow.pose_screen", e["name"], "skipped",
                                "短 MD 篩 pose 未啟用（docking.pose_md_screen.enabled=false；非 research tier 預設關閉以節省時間）；"
                                "pose 只依對接保守條件選擇，報告會標註。")
            elif screen is None:
                self._block("pose_selection", f"{e['name']}：已啟用短 MD 篩 pose，但此執行方式沒有提供模擬器；請用 pipeline run 執行。")
            else:
                ec = cache.setdefault(e["name"], {})
                screened = {}
                for r in screen_candidates(e, scfg.top_n):
                    if str(r) in ec and ec[str(r)].get("verdict"):
                        screened[r] = ec[str(r)]
                        continue
                    a = screen(e, r)
                    if a is None:
                        atomic_write_json(cache, cache_path)
                        return None
                    ec[str(r)] = screened[r] = a
                    atomic_write_json(cache, cache_path)
                dec = decide(e, screened, scfg)
                screen_info = {k: dec[k] for k in ("status", "rank", "summary")}
                if dec["status"] == "NEEDS_HUMAN":
                    self._block("pose_selection", dec["why"] + "（選項：" + " / ".join(dec["options"]) + "）",
                                screen={e["name"]: dec})
                self.dec.record("workflow.pose_screen", e["name"], f"rank {dec['rank']}", dec["why"])
                if dec["rank"] != rank:
                    why = dec["why"]
                rank = dec["rank"]
            p = e["poses"][rank - 1]
            if p.get("clash"):
                self._block("pose_selection", f"{e['name']} 第 {rank} 名 joint pose 配體互相碰撞（最短 {p['min_ll_distance']} Å），請改選。")
            for lig in e["ligands"]:
                sel["ligands"][lig] = {"rank": rank, "sdf": e["pose_sdfs"][lig][rank - 1], "score": p["score"],
                                       "rmsd_ref": p.get("rmsd_ref"), "entry": e["name"],
                                       "smiles": e["smiles"][lig] if isinstance(e["smiles"], dict) else e["smiles"],
                                       "md_screen": screen_info}
            self.dec.record("workflow.pose", e["name"], f"rank {rank}", why, kind="human" if e["name"] in user else "auto")
        self._mark("pose_selection", selection=sel, choices_cfg=key)
        return sel

    def _docking_signature(self) -> str | None:
        from .util import sha256_file
        d = self._done("docking")
        p = Path(d["result"]) if d and d.get("result") else None
        return sha256_file(p) if p and p.is_file() else None

    def _pose_screen_cache(self, cache_path: Path) -> dict:
        """Short-MD verdicts are keyed by entry+rank; after a re-dock rank 1 is a different pose, so the whole cache
        (and the registry of cases built from the old poses) is dropped when docking_results.json changed."""
        cache = load_json(cache_path, {})
        sig = self._docking_signature()
        if cache and cache.get("_docking") != sig:
            n = sum(1 for k in cache if not k.startswith("_"))
            cache = {}
            reg_path = self.dir / "pose_screen_cases.json"
            if reg_path.is_file():
                reg_path.unlink()
            if n:
                self.dec.record("workflow.pose_screen", "cache", "discarded",
                                f"對接結果已改變（重新對接），{n} 個舊 pose 的短 MD 判定與其建模 case 不再沿用，重新篩選。")
        cache["_docking"] = sig
        return cache

    def _screen_pose(self, raw: Path, make_factory: Callable, entry: dict, rank: int, *,
                     should_pause=None, progress_cb=None) -> dict | None:
        """Build the pose at `rank`, run a short MD, return assess_pose(...) (None if paused)."""
        from .docking.pose_screen import assess_pose
        from .engine import make_protocol, run_replicas
        scfg = self._screen_cfg()
        names = list(entry["ligands"])
        picks = {n: {"sdf": entry["pose_sdfs"][n][rank - 1],
                     "smiles": entry["smiles"][n] if isinstance(entry["smiles"], dict) else entry["smiles"]} for n in names}
        reg_path = self.dir / "pose_screen_cases.json"
        reg = load_json(reg_path, {})
        rkey = f"{entry['name']}#{rank}"
        try:
            if rkey in reg:
                case = self.project.case(reg[rkey]["case_id"])
                bs, lmap = load_json(case.build_dir / "build_manifest.json", {}), reg[rkey]["ligand_map"]
                if bs.get("status") != "PASS":
                    raise RuntimeError(f"建模未通過：{bs.get('blocking')}")
            else:
                case = self.project.new_case(f"{self.name}_screen_{safe_name(entry['name'])}_r{rank}")
                bs, lmap = self._build_one(case, raw, names, picks, screen=True)
                reg[rkey] = {"case_id": case.case_id, "ligand_map": lmap}
                atomic_write_json(reg, reg_path)
                if bs.get("status") != "PASS":
                    raise RuntimeError(f"建模未通過：{bs.get('blocking')}：{bs.get('blocking_detail')}")
            md = self.cfg.get("md", {})
            proto = make_protocol(md.get("tier", "teaching"), production_ns=scfg.production_ps / 1000.0, replicas=1,
                                  seed=int(self.cfg.get("docking", {}).get("seed", 2026)))
            if self._solvent(screen=True) == "gbn2":
                from .engine.protocol import implicit_solvent_protocol
                proto = implicit_solvent_protocol(proto)
            for st in proto.stages:
                if st.name in ("nvt", "npt"):
                    st.length_ps = getattr(scfg, f"{st.name}_ps")
                if st.ensemble != "MIN":
                    st.trajectory_interval_ps = scfg.frame_interval_ps
                    st.checkpoint_interval_ps = min(st.checkpoint_interval_ps, st.length_ps)
            summ = run_replicas(case, proto, make_factory(case, proto), n=1, should_pause=should_pause,
                                progress_cb=progress_cb, group_id=f"screen_{rank}")
            r0 = summ["runs"][0]
            if r0["status"] == "PAUSED":
                return None
            if r0["status"] != "COMPLETE":
                raise RuntimeError(r0.get("reason") or r0["status"])
            from .analysis.traj import load_production, compute_metrics
            bm = load_json(case.build_dir / "build_manifest.json", {})
            recs = {l.get("name"): l for l in manifest_ligands(bm)}
            groups = {n: (recs.get(lmap.get(n)) or {}).get("heavy_atom_indices") or [] for n in names}
            if not all(groups.values()):
                raise RuntimeError("建模紀錄缺少配體原子索引")
            traj = load_production(case.dir / "runs" / r0["run_id"], bm["topology_pdb"])
            a = assess_pose(compute_metrics(traj, groups), names, scfg)
        except Exception as exc:              # a failed screen is a recorded FAILED verdict, never a silent pass
            a = assess_pose(None, names, scfg, error=f"{type(exc).__name__}: {exc}")
        a["case_id"] = (reg.get(rkey) or {}).get("case_id")
        return a

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

    def _solvent(self, screen: bool = False) -> str:
        """`md.solvent` (explicit | gbn2); the short-MD pose screen may set its own (`docking.pose_md_screen.solvent`)."""
        md = self.cfg.get("md") or {}
        if screen:
            ps = (self.cfg.get("docking") or {}).get("pose_md_screen") or {}
            return ps.get("solvent") or md.get("solvent", "explicit")
        return md.get("solvent", "explicit")

    def _metal_params(self) -> dict | None:
        """`metal_params` with relative file paths resolved against the workflow directory."""
        mp = self.cfg.get("metal_params") or None
        if not mp:
            return None
        out = {}
        for key, spec in mp.items():
            if not spec:                                  # None/{}: GUI chose the geometric bonded model for this site
                continue
            spec = dict(spec)
            for f in ("file", "frcmod", "pdb"):
                if spec.get(f) and not Path(spec[f]).is_absolute():
                    spec[f] = str((self.dir / spec[f]).resolve())
            if spec.get("mol2"):
                spec["mol2"] = [m if Path(m).is_absolute() else str((self.dir / m).resolve()) for m in spec["mol2"]]
            out[key] = spec
        return out

    def _padding_nm(self, ligands: list[str] | None = None, *, screen: bool = False) -> float:
        """WP3: SMD/umbrella need room to pull; raise padding for the systems that will be pulled from
        (cases with ligands when binding is enabled) — not for apo, not for the short-MD pose screen."""
        md = self.cfg.get("md", {})
        tier = md.get("tier", "teaching")
        if md.get("padding_nm") is None:
            pad = TIER_PADDING_NM.get(tier, 0.8)
            if not getattr(self, "_pad_default_logged", False):
                self.dec.record("build.box", "padding_nm", pad,
                                f"未指定 padding：{tier} tier 預設 {pad} nm（蛋白到盒邊的最小距離；菱形十二面體盒）。"
                                "水佔原子數 80–90%，盒子只需容納蛋白加一層完整溶劑化殼層。")
                self._pad_default_logged = True
        else:
            pad = float(md["padding_nm"])
        if screen:
            return min(pad, 0.8)          # the short pose screen only asks whether the pose falls apart
        if (self.cfg.get("binding") or {}).get("enabled") and ligands and not screen:
            bc = self.cfg["binding"].get("config") or {}
            need = float(bc.get("pull_distance_nm", bc.get("pull_distance", 1.5))) + 0.5
            need = max(1.5, min(need, 2.5))
            if pad < need:
                if not getattr(self, "_pad_logged", False):
                    self.dec.record("build.box", "padding_nm", need,
                                    f"啟用結合自由能計算：拉離距離需要空間，padding 由 {pad} 自動提高到 {need} nm，"
                                    f"避免配體被拉到週期影像附近。")
                    self._pad_logged = True
                pad = need
        return pad

    def _build_one(self, case, raw: Path, names: list[str], picks: dict, *, screen: bool = False) -> tuple[dict, dict]:
        """Build one case from chosen poses (`picks[name]` has sdf/smiles); returns (build summary, name → topology name)."""
        from .build.pipeline import build_case
        drop = {l.get("reference_resname") for l in self.cfg["ligands"] if l.get("reference_resname")}
        lspec = {l["name"]: l for l in self.cfg["ligands"]}
        small = [n for n in names if not lspec.get(n, {}).get("sequence")]
        peps = [{"name": n, "sequence": lspec[n]["sequence"], "pose": picks[n]["sdf"],
                 "termini": lspec[n].get("termini", "charged"), "target_location": lspec[n].get("target_location"),
                 "cpp_evidence": lspec[n].get("cpp_evidence"), "cpp_override": lspec[n].get("cpp_override")}
                for n in names if lspec.get(n, {}).get("sequence")]
        s = build_case(case, receptor=raw, ligand_references=[picks[n]["smiles"] for n in small],
                       ligand_poses=[picks[n]["sdf"] for n in small], ph=self.cfg.get("ph", 7.4),
                       padding_nm=self._padding_nm(names, screen=screen), keep_hetero=set(self.cfg.get("keep_hetero", [])),
                       extra_ligand_resnames=drop, peptides=peps or None, ligand_names=small,
                       exclude_chains=set(self.cfg["receptor"].get("exclude_chains", [])),
                       metal_policy=self.cfg.get("metal_policy") or None,
                       peptide_policy=self.cfg.get("peptide_policy") or None,
                       metal_params=self._metal_params(), solvent=self._solvent(screen),
                       box_shape=self.cfg.get("md", {}).get("box_shape", "dodecahedron"),
                       ionic_strength_molar=float(self.cfg.get("md", {}).get("ionic_strength_molar", 0.15)))
        lmap = {n: f"L{i:02d}" for i, n in enumerate(small, 1)} | {p["name"]: p["name"] for p in peps}
        return s, lmap

    def build_cases(self, raw: Path, sel: dict) -> dict:
        built = dict((self._done("md_cases") or {}).get("cases", {}))
        for spec in self._cases_to_build(sel):
            if spec["key"] in built and built[spec["key"]].get("status") == "PASS":
                continue
            case = self.project.new_case(f"{self.name}_{spec['key']}")
            s, lmap = self._build_one(case, raw, spec["ligands"], sel["ligands"])
            built[spec["key"]] = {"case_id": case.case_id, "mode": spec["mode"], "ligands": spec["ligands"], "ligand_map": lmap,
                                  "status": s["status"], "blocking": s.get("blocking"), "blocking_detail": s.get("blocking_detail")}
            self._mark("md_cases", cases=built)
            if s["status"] != "PASS":
                self._block("md_cases", f"{spec['key']} 建模需要人工決定：{s.get('blocking')}：{s.get('blocking_detail')}", cases=built)
        return built

    def _restraint_strategy(self) -> str:
        """md.restraints: standard（預設）| gentle | hold_backbone（D-23）。未知值 → 擋下，不猜。"""
        from .engine.protocol import RESTRAINT_STRATEGIES
        name = (self.cfg.get("md") or {}).get("restraints") or "standard"
        if name not in RESTRAINT_STRATEGIES:
            self._block("md_runs", f"md.restraints = {name!r} 不是已知的約束策略。",
                        options=[f"md.restraints: {k}" for k in RESTRAINT_STRATEGIES])
        if name == "hold_backbone":
            self.dec.record("workflow.md", "restraints", name,
                            "production 全程保留主鏈 5% 約束（50 kJ/mol/nm²）：主鏈 RMSD／RMSF 會被約束壓低，報告標註「受約束」，"
                            "不能當作結構穩定的證據。", kind="auto")
        return name

    def run_md(self, built: dict, make_factory: Callable, *, should_pause=None, progress_cb=None) -> dict:
        from .engine import make_protocol, run_replicas
        md = self.cfg.get("md", {})
        runs = dict((self._done("md_runs") or {}).get("runs", {}))
        for key, c in built.items():
            prev = runs.get(key, {})
            if prev.get("status") == "COMPLETE" and prev.get("case_id") == c["case_id"]:
                continue
            if prev and prev.get("case_id") != c["case_id"]:
                self.dec.record("workflow.md", key, "rebuilt case", f"{key} 的 MD 紀錄屬於舊 case {prev.get('case_id')}（pose 或設定改變後重新建模為 "
                                f"{c['case_id']}）；舊結果不沿用，重新執行 MD。")
                runs.pop(key, None)
            case = self.project.case(c["case_id"])
            proto = make_protocol(md.get("tier", "teaching"), production_ns=md.get("production_ns"), replicas=md.get("replicas", 1),
                                  restraints=self._restraint_strategy())
            if self._solvent() == "gbn2":
                from .engine.protocol import implicit_solvent_protocol
                proto = implicit_solvent_protocol(proto)
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
                bm = load_json(case.build_dir / "build_manifest.json", {})
                groups = {l["name"]: l["heavy_atom_indices"] for l in manifest_ligands(bm) if l.get("heavy_atom_indices")}
                man = analyse_run(run_dir, top, label=key, ligand_groups=groups or None, metal_indices=metal_indices_from_manifest(bm),
                                  decisions=self.dec)
            out[key] = man
            metrics[key] = load_json(man["metrics_file"], {})
        comp = compare_runs(metrics, self.dir / "figures") if len(metrics) > 1 else {}
        self._mark("analysis", summaries=out, comparison=comp)
        return {"summaries": out, "comparison": comp}

    # WP3: what a tier is allowed to claim.  Sampling below the tier minimum still runs, but ΔG° is not reported.
    TIER_BINDING = {"classroom": {"dG": False},
                    "teaching": {"dG": True, "min_window_ps": 500.0},
                    "research": {"dG": True, "min_window_ps": 2000.0, "min_replicas": 3, "max_half_split_kj": 2.0}}

    def _tier_withholds_dG(self, cfg, res, n_done: int = 1) -> str | None:
        tier = self.cfg.get("md", {}).get("tier", "teaching")
        rule = self.TIER_BINDING.get(tier, self.TIER_BINDING["teaching"])
        if not rule["dG"]:
            return "classroom 等級只展示 ΔPMF 趨勢，不輸出 ΔG° 絕對值（取樣不足以支持定量結論）。"
        if cfg.window_prod_ps < rule.get("min_window_ps", 0):
            return (f"{tier} 等級要求每個 window ≥ {rule['min_window_ps']:.0f} ps，本次只有 {cfg.window_prod_ps:.0f} ps；"
                    f"ΔG° 不輸出，ΔPMF 僅供定性比較。")
        if rule.get("min_replicas") and int(n_done) < rule["min_replicas"]:
            return (f"research 等級要求 ≥ {rule['min_replicas']} 個獨立 replica 的結合計算；實際完成 {n_done} 個"
                    f"（設定 binding.replicas），ΔG° 不輸出。")
        hs = (res.pmf.get("half_split") or {}).get("diff_kj_mol")
        if rule.get("max_half_split_kj") and (hs is None or hs > rule["max_half_split_kj"]):
            return f"前後半段 ΔPMF 差 {hs} kJ/mol > {rule['max_half_split_kj']}：未收斂，ΔG° 不輸出。"
        return None

    def _binding_targets(self, runs: dict, built: dict) -> tuple[list[dict], dict[str, list[str]]]:
        """(targets, contexts).  Single-ligand cases → key = ligand name (backward compatible);
        WP9: every ligand of a docked_multi case is pulled from the shared complex → key = "multi:<ligand>"."""
        b = self.cfg.get("binding", {})
        wanted = b.get("ligands") or None
        targets, ctx = [], {"single": []}
        for key, c in built.items():
            if key not in runs:
                continue
            if c["mode"] == "docked_single":
                for n in c["ligands"]:
                    if wanted is None or n in wanted:
                        targets.append({"key": n, "ligand": n, "run_key": key, "others": []})
                        ctx["single"].append(n)
            elif c["mode"] == "docked_multi" and b.get("multi", True):
                names = [n for n in c["ligands"] if wanted is None or n in wanted]
                ctx[f"multi:{key}"] = []
                for n in names:
                    targets.append({"key": f"multi:{n}", "ligand": n, "run_key": key,
                                    "others": [m for m in c["ligands"] if m != n]})
                    ctx[f"multi:{key}"].append(f"multi:{n}")
        return targets, ctx

    def binding(self, runs: dict, built: dict, platform, *, should_pause=None, progress_cb=None) -> dict:
        from .sampling.binding import run_binding, BindingConfig
        from types import SimpleNamespace
        from .sampling.multi import compare_binding, aggregate_binding_replicas
        b = self.cfg.get("binding", {})
        if not b.get("enabled"):
            return {}
        if self._solvent() == "gbn2":
            msg = ("隱式溶劑（GBn2）不做 SMD／傘狀採樣：拉離過程的去溶劑化能障在連續介質模型下會失真，PMF 與 ΔG° 不可信。")
            self._block("binding", msg, gates=[{"name": "implicit solvent + binding", "status": "NEEDS_HUMAN", "explanation": msg,
                                                "options": ["md.solvent: explicit（顯式水，重建並重跑 MD）", "binding.enabled: false（只做 MD）"]}])
        # keep every finished target even when the step itself was paused or reopened (manual resampling of one
        # target must not recompute the others)
        results = {k: v for k, v in ((self.state()["steps"].get("binding") or {}).get("results") or {}).items()
                   if v.get("status") == "PASS"}
        valid = {f.name for f in fields(BindingConfig)}
        cfg = BindingConfig(**{k: v for k, v in (b.get("config") or {}).items() if k in valid})
        targets, contexts = self._binding_targets(runs, built)
        for t in targets:
            name, key = t["key"], t["run_key"]
            if results.get(name, {}).get("status") == "PASS":
                continue
            case = self.project.case(runs[key]["case_id"])
            bm = load_json(case.build_dir / "build_manifest.json", {})
            lmap = built.get(key, {}).get("ligand_map") or {}
            mname = lmap.get(t["ligand"], "L01")
            recs = {l.get("name"): l for l in manifest_ligands(bm)}
            lrec = recs.get(mname)
            if lrec is None or not lrec.get("heavy_atom_indices"):
                self._block("binding", f"{name}：建模紀錄中找不到配體 {mname} 的原子索引，無法定義拉離座標。")
            others = {}
            for o in t["others"]:
                orec = recs.get(lmap.get(o, ""))
                if not orec or not orec.get("heavy_atom_indices"):
                    self._block("binding", f"{name}：共同口袋中的配體 {o} 沒有原子索引，無法檢查拉離路徑。")
                others[o] = orec["heavy_atom_indices"]
            n_rep = max(1, int(b.get("replicas", 1)))
            md_runs = runs[key]["run_ids"]
            reps, paused = [], False
            for i in range(n_rep):
                # replica i starts from MD replica i (cycled) with its own seed → independent SMD/umbrella paths
                rdir = case.dir / "runs" / md_runs[i % len(md_runs)]
                rcfg = BindingConfig(**{**cfg.to_dict(), "seed": cfg.seed + 1000 * i,
                                        "extra_windows": list((b.get("manual_windows") or {}).get(name, []))})
                odir = self.dir / "binding" / name.replace(":", "_")
                res = run_binding(bm["system_xml"], bm["topology_pdb"], rdir / "stages" / "production" / "production_state.xml",
                                  odir if n_rep == 1 else odir / f"rep{i + 1}",
                                  ligand_indices=lrec["heavy_atom_indices"], ligand_resname=mname, config=rcfg, platform_name=platform.name,
                                  platform_properties=platform.properties, decisions=self.dec, should_pause=should_pause,
                                  progress_cb=progress_cb, other_ligand_indices=others or None)
                if res.status == "NEEDS_HUMAN":
                    results[name] = {"status": "NEEDS_HUMAN", "ligand": t["ligand"], "caveats": res.caveats}
                    self._block("binding", f"{name} 結合自由能（replica {i + 1}）：{res.caveats[0] if res.caveats else ''}", results=results)
                if res.status == "PAUSED":
                    paused = True
                    break
                reps.append(res)
            if paused:
                results[name] = {"status": "PAUSED", "ligand": t["ligand"], "replicas_done": len(reps)}
                st = self.state(); st["steps"]["binding"] = {"status": "PAUSED", "results": results}; atomic_write_json(st, self.state_path)
                return results
            agg = aggregate_binding_replicas(reps)
            res = reps[0]
            dG, dGk, withheld = agg["dG"], agg["dG_kcal"], agg["dG_withheld"]
            reason = self._tier_withholds_dG(cfg, SimpleNamespace(pmf={"half_split": agg["half_split"]}), n_done=len(reps))
            if reason and dG is not None:
                dG, dGk, withheld = None, None, reason
                self.dec.record("binding.result", name, "ΔG° withheld", reason)
            if len(reps) > 1:
                self.dec.record("binding.replicas", name, f"{len(reps)} replicas", agg["why"])
            results[name] = {"status": "PASS", "ligand": t["ligand"], "context": "single" if not t["others"] else f"multi:{key}",
                             "co_ligands": t["others"], "replicas": len(reps), "delta_pmf_kj_mol": agg["delta_pmf"],
                             "delta_pmf_err_kj_mol": agg["delta_pmf_err"],
                             "dG_standard_kj_mol": dG, "dG_err_kj_mol": agg["dG_err"] if dG is not None else None,
                             "dG_standard_kcal_mol": dGk, "dG_withheld": withheld,
                             "per_replica": agg["per_replica"], "half_split": agg["half_split"],
                             "r_min_nm": res.pmf.get("r_min_nm"), "figures": res.figures, "caveats": res.caveats,
                             "max_force": res.smd.get("max_force_kj_mol_nm"), "work": res.smd.get("final_work_kj_mol")}
        comparison = compare_binding(results, contexts={k: v for k, v in contexts.items() if v})
        for c in comparison["contexts"].values():
            if c.get("why"):
                self.dec.record("binding.compare", "ΔΔ", c.get("reference"), c["why"])
        for c in comparison["co_occupancy"]:
            self.dec.record("binding.compare", f"co-occupancy {c['ligand']}", c["shift_kj_mol"], c["why"])
        self._mark("binding", results=results, comparison=comparison)
        return results

    # ------------------------------------------------------------------ driver
    def run(self, make_factory: Callable, platform, *, should_pause=None, progress_cb=None) -> dict:
        """Resumable driver.  One owner at a time (stale owner locks are taken over); hardware changes are logged —
        chunks resume from platform-independent State XML, so a run started on CUDA can finish on OpenCL/CPU."""
        from .util.locks import OwnerLock
        lock = OwnerLock(self.dir / "running.json")
        try:
            lock.acquire()
        except RuntimeError as exc:
            raise WorkflowBlocked(str(exc)) from exc
        try:
            if lock.took_over:
                self.dec.record("workflow.resume", "stale lock", lock.took_over,
                                "上次執行的程序已不存在（當機、重開機或視窗被關閉）；自動接手並從最後確認的 chunk 續跑。")
            hw = {"platform": getattr(platform, "name", str(platform)),
                  "device": (getattr(platform, "properties", None) or {}).get("DeviceIndex", ""),
                  "detail": getattr(platform, "device_name", "") or ""}
            st = self.state()
            if st.get("hardware") and st["hardware"] != hw:
                self.dec.record("workflow.resume", "hardware changed", hw,
                                f"運算平台由 {st['hardware'].get('platform')} 變為 {hw['platform']}；續跑使用與平台無關的 "
                                f"State XML，結果可接續，但速度與數值雜訊會不同（報告會註記）。")
            st["hardware"] = hw
            st.setdefault("hardware_history", []).append({**hw, "at": now_iso()})
            atomic_write_json(st, self.state_path)
            return self._run(make_factory, platform, should_pause=should_pause, progress_cb=progress_cb)
        finally:
            lock.release()

    def _run(self, make_factory: Callable, platform, *, should_pause=None, progress_cb=None) -> dict:
        raw = self.fetch_receptor()
        clean = self.prepare_docking_receptor(raw)
        sel = None
        systems = self.cfg.get("md", {}).get("systems", ["apo", "docked_single"])
        if not self.apply_screen(clean, raw, progress_cb=progress_cb,
                                 should_stop=(lambda: bool(should_pause())) if callable(should_pause) else None):
            return {"status": "PAUSED", "state": self.state()}
        if self.cfg.get("ligands") and (any(s != "apo" for s in systems) or self.cfg.get("docking", {}).get("always")):
            res = self.run_docking(clean, raw, progress_cb=progress_cb)
            sel = self.choose_poses(res, screen=lambda e, r: self._screen_pose(raw, make_factory, e, r,
                                                                              should_pause=should_pause, progress_cb=progress_cb))
            if sel is None:
                return {"status": "PAUSED", "state": self.state()}
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


# ---------------------------------------------------------------------- resume support (WP11)
def workflow_status(state: dict) -> str:
    steps = state.get("steps", {})
    if (steps.get("report") or {}).get("status") == "PASS":
        return "COMPLETE"
    if any((s or {}).get("status") == "NEEDS_HUMAN" for s in steps.values()):
        return "NEEDS_HUMAN"
    return "INCOMPLETE" if steps else "NEW"


def find_workflows(projects_dir: Path | str) -> list[dict]:
    """Every workflow under a projects root, with its status (for `md20 resume --all` and the GUI)."""
    out = []
    root = Path(projects_dir)
    if not root.is_dir():
        return out
    for cfgp in sorted(root.glob("*/workflows/*/config.json")):
        wdir = cfgp.parent
        st = load_json(wdir / "state.json", {"steps": {}})
        lock = load_json(wdir / "running.json", {})
        out.append({"project_dir": str(wdir.parent.parent), "workflow_dir": str(wdir), "name": wdir.name,
                    "status": workflow_status(st), "running_pid": lock.get("pid"), "updated_at": st.get("updated_at")})
    return out
