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
         "ions": {"positive": "Na+", "negative": "Cl-",        # Na+ K+ Li+ Rb+ Cs+ ; Cl- Br- F- I- (monovalent only)
                  "concentration_molar": 0.15, "neutralize": true}},  # 0 M = counter-ions only
  "binding": {"enabled": true, "ligands": ["BEN"], "config": {"pull_velocity_nm_per_ps": 0.005}},
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

def manifest_ligand_charges(bm: dict) -> dict[str, dict[int, int]]:
    """D-98: {ligand name: {topology atom index: +1/-1}} for small-molecule ligands whose build record carries
    atom-level charge signs (``atom_charge_signs``, resonance-delocalised; else ``atom_formal_charges``; SDF order)
    AND topology indices of the same length.

    A ligand is LEFT OUT (→ its charge stays "unknown" in the interaction fingerprint, so no salt bridge is called)
    when the charges were not recorded (manifests before D-98), the lengths disagree (order cannot be trusted), or it
    is a peptide (atom-level charges are not recorded for peptides yet).  An included ligand with no charged atom
    maps to {} — "known, neutral" — which is different from absent."""
    out: dict[str, dict[int, int]] = {}
    for l in manifest_ligands(bm):
        q, idx = (l.get("atom_charge_signs") or l.get("atom_formal_charges")), l.get("atom_indices")
        if l.get("kind", "small") == "peptide" or not q or not idx or len(q) != len(idx):
            continue
        out[l["name"]] = {int(i): (1 if int(c) > 0 else -1) for i, c in zip(idx, q) if int(c) != 0}
    return out


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


def _openmm_available() -> bool:
    import importlib.util
    return importlib.util.find_spec("openmm") is not None


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
            "md": {"systems": ["apo", "docked_single"], "tier": "teaching", "replicas": 1, "production_ns": None, "padding_nm": None, "box_shape": "dodecahedron", "ions": {"positive": "Na+", "negative": "Cl-", "concentration_molar": 0.15, "neutralize": True}},
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
        "md": {"systems": ["apo", "docked_single"], "tier": "teaching", "replicas": 1, "production_ns": None, "padding_nm": None, "box_shape": "dodecahedron", "ions": {"positive": "Na+", "negative": "Cl-", "concentration_molar": 0.15, "neutralize": True}},
        "binding": {"enabled": True, "ligands": ["BEN"], "config": {}},
    }


# keys that hold *human decisions* written back by gates/GUI (never re-derivable); re-running `pipeline run` from
# the student's original file must not silently discard them
DECISION_KEYS: tuple[tuple[str, ...], ...] = (
    ("pose_choices",), ("human_choices",), ("structure_override",), ("metal_policy",), ("metal_params",), ("peptide_policy",),
    ("docking", "skip_redock"), ("box", "allow_blind"), ("binding", "manual_windows"),
    ("screen", "select"), ("screen", "next_mode"), ("screen", "allow_partial"), ("md_confirmed",), ("ligand_metal",),
    ("multi_ligand",), ("md", "long_run_confirmed"), ("md", "long_run"),
    ("md", "membrane", "oriented"),        # gate `membrane orientation` one-click choice (D-80)
    ("md", "resolution"), ("md", "membrane", "surface_distance_nm"),   # coarse-grained gates (D-86)
    ("binding", "added"), ("binding", "target_replicas"),               # targets and extra SMD runs chosen later (D-87)
    ("binding", "skip_targets"),                                         # targets left out at the path gate (D-92)
    ("binding", "alone"), ("binding", "anchor_residues"),                # path gate choices (D-93)
)
LIGAND_DECISION_KEYS = ("cpp_override", "cpp_evidence", "target_location", "fold_accept_low", "fold_upload", "fold_engine",
                        "fold_accept_rmsd", "fold_receptor_seq")


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


def _heavy_xyz_pdb(text: str, *, atom_only: bool = False, resname: str | None = None) -> list:
    out = []
    for l in text.splitlines():
        if not l.startswith(("ATOM", "HETATM")) or (atom_only and not l.startswith("ATOM")):
            continue
        if resname and l[17:20].strip() != resname:
            continue
        el = (l[76:78].strip() or l[12:16].strip()[:1]).upper()
        if el == "H":
            continue
        try:
            out.append([float(l[30:38]), float(l[38:46]), float(l[46:54])])
        except ValueError:
            continue
    return out


def _heavy_xyz_sdf(text: str) -> list:
    """Heavy-atom coordinates of the first molecule in a V2000 SDF/MOL block."""
    lines = text.splitlines()
    if len(lines) < 4:
        return []
    try:
        n = int(lines[3][:3])
    except ValueError:
        return []
    out = []
    for l in lines[4:4 + n]:
        parts = l.split()
        if len(parts) >= 4 and parts[3] != "H":
            out.append([float(parts[0]), float(parts[1]), float(parts[2])])
    return out


class Workflow:
    def __init__(self, project: Project, config: dict, *, create: bool = True):
        self.project = project
        self.cfg = config
        self.name = safe_name(config.get("name", "workflow"))
        self.dir = project.dir / "workflows" / self.name
        if create:
            ensure_dir(self.dir)
        self.state_path = self.dir / "state.json"
        from .util.decisions import ScopedDecisionLog
        self.dec = ScopedDecisionLog(project.decisions, self.name)      # D-96 (A10): rows carry this workflow's id
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
        self._box_size_notice(raw)

    def _box_size_notice(self, raw: Path) -> None:
        """REVIEW #6 / D-56: an oversized search box is flagged (never blocked): longest edge > 40 Å or > 300 residues
        inside.  Stored as a notice in state["advisories"] and shown as a card and in the report."""
        b = self.cfg.get("box") or {}
        if not (b.get("center") and b.get("size")):
            return
        import numpy as _np
        c, h = _np.asarray(b["center"], float), _np.asarray(b["size"], float) / 2
        res = set()
        for l in raw.read_text(encoding="utf-8", errors="ignore").splitlines():
            if l.startswith("ATOM"):
                try:
                    x = _np.array([float(l[30:38]), float(l[38:46]), float(l[46:54])])
                except ValueError:
                    continue
                if _np.all(_np.abs(x - c) <= h):
                    res.add((l[21], l[22:27]))
        longest, n = float(max(b["size"])), len(res)
        st = self.state()
        adv = st.setdefault("advisories", {})
        if longest > 40.0 or n > 300:
            grid = int(_np.prod(_np.asarray(b["size"], float) / 0.375))
            msg = (f"科學限制提醒（流程照常進行）：搜尋區 {' × '.join(f'{x:g}' for x in b['size'])} Å，最長邊 {longest:g} Å、"
                   f"包含 {n} 個殘基（門檻：40 Å 或 300 個殘基），約 {grid:,} 個格點（間距 0.375 Å）。過大的搜尋區等同盲對接："
                   "搜尋時間增加、同樣的搜尋強度下更難找到最佳姿勢，分數與姿勢的可信度下降。")
            adv["box size"] = {"name": "box size", "status": "AUTO_FIXED", "advisory": True, "explanation": msg,
                               "options": ["以共結晶配體或活性位殘基重新定義搜尋區", "接受並在報告中標註"],
                               "evidence": {"size": b["size"], "residues": n, "grid_points": grid}}
            self.dec.record("docking.box", "size", f"{longest:g} Å, {n} residues", msg)
        else:
            adv.pop("box size", None)
        atomic_write_json(st, self.state_path)

    def _peptide_preflight(self, l: dict, box=None) -> str:
        """Peptide ligand: CPP and pocket-access checks before docking (advisory, never blocking: D-48), docking
        SMILES from the sequence."""
        from .build.peptide import clean_sequence, peptide_smiles, cpp_gate, peptide_access_precheck
        seq = clean_sequence(l["sequence"])
        gate, rec = cpp_gate(seq, target_location=l.get("target_location"), experimental_evidence=l.get("cpp_evidence"))
        self.dec.record("peptide.cpp", l["name"], rec.get("status"), gate.explanation,
                        kind="human" if l.get("cpp_override") else "auto")
        st = self.state()
        st.setdefault("cpp", {})[l["name"]] = {**rec, "gate": gate.status, "explanation": gate.explanation,
                                               "options": gate.options, "advisory": gate.advisory,
                                               "override": bool(l.get("cpp_override")), "override_note": l.get("cpp_override")}
        if box is not None:
            b = self.cfg.get("box") or {}
            site = bool(b.get("from_residue") or b.get("site_residues"))
            g2, rec2 = peptide_access_precheck(seq, box.size, site_defined=site)
            st.setdefault("peptide_access", {}).setdefault(l["name"], {})["precheck"] = {
                **rec2, "gate": g2.status, "explanation": g2.explanation, "options": g2.options, "advisory": g2.advisory}
            self.dec.record("peptide.access", l["name"], g2.status, g2.explanation)
        atomic_write_json(st, self.state_path)
        return peptide_smiles(seq, l.get("termini", "charged"))

    def _fold_peptide(self, l: dict) -> str | None:
        """D-80: `ligands[i].fold: true` → predict the peptide's structure before docking (md20/build/fold.py).

        Returns the SDF used as the docking input (backbone kept rigid in Vina, side chains flexible), or None when the
        peptide is too short to fold (the extended build is used).  Results go to state["fold"][name] for the report.
        Not available or pLDDT < 50 → NEEDS_HUMAN with options; nothing falls back silently."""
        from .build import fold as F
        name = l["name"]
        seq = F.clean(l["sequence"], name)
        req = {"sequence": seq, "engine": l.get("fold_engine") or "auto", "upload": l.get("fold_upload") or "",
               "accept_low": bool(l.get("fold_accept_low"))}
        st = self.state()
        old = (st.get("fold") or {}).get(name) or {}
        if old.get("request") == req and old.get("docking_sdf") and Path(old["docking_sdf"]).is_file():
            return old["docking_sdf"]
        out = self.dir / "fold" / safe_name(name)
        opts = [F.OPT_INSTALL, F.OPT_UPLOAD, F.OPT_NO_FOLD]
        try:
            res = F.fold(seq, engine=req["engine"], out_dir=out, upload=req["upload"] or None, accept_low=req["accept_low"])
        except F.FoldError as exc:
            gate = {"name": "fold", "status": "NEEDS_HUMAN", "explanation": str(exc), "options": exc.options or opts,
                    "evidence": {"text": exc.text, "sequence": seq}}
            self._record_fold(name, {"request": req, "status": "NEEDS_HUMAN", "error": exc.text})
            self._block("fold", f"{name}：{exc}", gates=[gate], ligand=name)
        if res.status == "SKIPPED_SHORT":
            self.dec.record("build.fold", name, "not folded (short)",
                            f"{name} 只有 {len(seq)} 個殘基（少於 {F.MIN_FOLD_RESIDUES}），單獨存在時通常沒有穩定結構；"
                            "不摺疊，沿用由序列建立的延伸構形，由對接搜尋改變構形，報告會說明。")
            self._record_fold(name, {"request": req, **res.to_dict()})
            return None
        if res.status == "NEEDS_HUMAN":
            self._record_fold(name, {"request": req, **res.to_dict()})
            gates = [g for g in res.gates["gates"] if g["status"] == "NEEDS_HUMAN"]
            self._block("fold", f"{name}：{gates[0]['explanation']}", gates=gates, ligand=name)
        sdf, notes = F.docking_sdf(res, out / f"{safe_name(name)}_predicted.sdf")
        why = (f"{name} 以 {res.engine} 預測結構（平均 pLDDT {res.mean_plddt}，閘門 {res.status}"
               + (f"，ipTM {res.iptm:.2f}" if res.iptm is not None else "") +
               "）。預測結構當作對接的起始構形：Vina 每次搜尋都會把可旋轉鍵隨機化，所以主鏈 φ/ψ 設為不可旋轉以保留預測的摺疊，"
               "側鏈仍可轉動。這是預測，不是實驗結構；之後的 MD 會檢查它是否穩定。")
        self.dec.record("build.fold", name, f"{res.engine} pLDDT {res.mean_plddt}", why,
                        kind="human" if req["accept_low"] and (res.mean_plddt or 0) < F.PLDDT_LOW else "auto_fixed"
                        if res.status == "AUTO_FIXED" else "auto")
        self._record_fold(name, {"request": req, **res.to_dict(), "docking_sdf": str(sdf),
                                 "rigid_backbone": True, "notes": res.notes + notes})
        return str(sdf)

    def _fold_complex(self, l: dict, raw: Path, smiles: str) -> str:
        """D-80 `ligands[i].fold: "complex"`: fold receptor + peptide together, superpose the predicted receptor onto the
        actual receptor (sequence alignment, Kabsch on matched Cα) and take only the peptide pose; that pose goes to MD
        without docking.  Cα RMSD > 2 Å, too few matched Cα, low pLDDT or no engine → NEEDS_HUMAN with options."""
        from .build import fold as F
        name = l["name"]
        seq = F.clean(l["sequence"], name)
        excl = set(self.cfg["receptor"].get("exclude_chains", []))
        given = l.get("fold_receptor_seq")
        if given:
            rec_seqs, rec_notes = [F.clean(x, f"{name} receptor") for x in ([given] if isinstance(given, str) else given)], []
        else:
            rec_seqs, _, rec_notes = F.receptor_sequences(raw, exclude_chains=excl)
        req = {"mode": "complex", "sequence": seq, "receptor": rec_seqs, "engine": l.get("fold_engine") or "auto",
               "upload": l.get("fold_upload") or "", "accept_low": bool(l.get("fold_accept_low")),
               "accept_rmsd": bool(l.get("fold_accept_rmsd")), "reference": str(raw)}
        old = ((self.state().get("fold") or {}).get(name)) or {}
        if old.get("request") == req and old.get("complex_pose") and Path(old["complex_pose"]).is_file():
            return old["complex_pose"]
        out = self.dir / "fold" / safe_name(name)
        try:
            res = F.fold(rec_seqs + [seq], engine=req["engine"], out_dir=out, upload=req["upload"] or None,
                         accept_low=req["accept_low"])
            pl = None if res.status == "NEEDS_HUMAN" else F.place_peptide(res, out, reference=raw, exclude_chains=excl,
                                                                        accept_rmsd=req["accept_rmsd"])
        except F.FoldError as exc:
            gate = {"name": "fold", "status": "NEEDS_HUMAN", "explanation": str(exc),
                    "options": exc.options or [F.OPT_INSTALL, F.OPT_UPLOAD, F.OPT_DOCK],
                    "evidence": {"text": exc.text, "sequence": seq}}
            self._record_fold(name, {"request": req, "status": "NEEDS_HUMAN", "error": exc.text})
            self._block("fold", f"{name}：{exc}", gates=[gate], ligand=name)
        rec = {"request": req, **res.to_dict(), "placement": pl.to_dict() if pl else None,
               "notes": res.notes + rec_notes + (pl.notes if pl else [])}
        bad = [g for g in res.gates.get("gates", []) + ((pl.gates.get("gates", []) if pl else []))
               if g["status"] == "NEEDS_HUMAN"]
        if bad:
            self._record_fold(name, rec)
            self._block("fold", f"{name}：{bad[0]['explanation']}", gates=bad, ligand=name)
        sdf, map_notes = F.docking_sdf(res, out / f"{safe_name(name)}_complex_pose.sdf",
                                       transform=pl.transform if pl.receptor_source == "actual" else None)
        rec.update({"complex_pose": str(sdf), "smiles": smiles, "notes": rec["notes"] + map_notes})
        why = (f"{name} 以 {res.engine} 預測受體＋胜肽複合物（胜肽平均 pLDDT {res.mean_plddt}"
               + (f"，ipTM {res.iptm:.2f}" if res.iptm is not None else "") + "）。"
               + (f"預測的受體以序列比對配對 {pl.n_matched} 個 Cα，Kabsch 疊合到實際受體，Cα RMSD {pl.rmsd_ca} Å"
                  f"（門檻 {F.SUP_MAX_RMSD} Å），只取胜肽姿勢放進實際受體；" if pl.receptor_source == "actual"
                  else "沒有實際受體結構，直接使用預測的受體（標註為預測）；")
               + "此胜肽不經對接，姿勢直接進入建模與 MD。這是預測，不是實驗結構，MD 會檢查姿勢是否穩定。")
        human = (req["accept_rmsd"] and (pl.rmsd_ca or 0) > F.SUP_MAX_RMSD) or (req["accept_low"] and (res.mean_plddt or 0) < F.PLDDT_LOW)
        self.dec.record("build.fold", name, f"complex {res.engine} → MD (RMSD {pl.rmsd_ca})", why,
                        kind="human" if human else "auto_fixed")
        self._record_fold(name, rec)
        return str(sdf)

    def _complex_picks(self, sel: dict) -> None:
        """Add the peptides placed from a predicted complex to the pose selection (no docking entry, no score)."""
        fold = self.state().get("fold") or {}
        for l in self.cfg.get("ligands") or []:
            if l.get("fold") != "complex":
                continue
            rec = fold.get(l["name"]) or {}
            if not rec.get("complex_pose") or not Path(rec["complex_pose"]).is_file():
                self._block("pose_selection", f"{l['name']}：fold: complex 的胜肽姿勢不存在，請重跑對接步驟。")
            sel["ligands"][l["name"]] = {"rank": 1, "sdf": rec["complex_pose"], "score": None, "rmsd_ref": None,
                                         "entry": l["name"], "smiles": rec.get("smiles", ""), "md_screen": None,
                                         "source": "fold_complex"}

    def _record_fold(self, name: str, rec: dict) -> None:
        st = self.state()
        st.setdefault("fold", {})[name] = rec
        atomic_write_json(st, self.state_path)

    def _peptide_pose_access(self, sel: dict) -> None:
        """After pose selection: does each peptide pose reach the site or lie on the surface? (advisory, D-48)"""
        from .build.peptide import peptide_pose_access, peptide_access_gate
        peps = {l["name"] for l in self.cfg.get("ligands") or [] if l.get("sequence")}
        if not peps:
            return
        rec_path = (self._done("receptor_docking") or {}).get("path")
        raw_path = (self._done("receptor_input") or {}).get("path")
        if not rec_path or not Path(rec_path).is_file():
            return
        prot = _heavy_xyz_pdb(Path(rec_path).read_text(encoding="utf-8", errors="ignore"), atom_only=True)
        site = None
        res = str((self.cfg.get("box") or {}).get("from_residue") or "").split(":")[0].split()[:1]
        if res and raw_path and Path(raw_path).is_file():
            site = _heavy_xyz_pdb(Path(raw_path).read_text(encoding="utf-8", errors="ignore"), resname=res[0]) or None
        st = self.state()
        for name, info in (sel.get("ligands") or {}).items():
            if name not in peps or not info.get("sdf") or not Path(info["sdf"]).is_file():
                continue
            pep = _heavy_xyz_sdf(Path(info["sdf"]).read_text(encoding="utf-8", errors="ignore"))
            if not pep or not prot:
                continue
            m = peptide_pose_access(pep, prot, site_xyz=site)
            g = peptide_access_gate(name, m)
            st.setdefault("peptide_access", {}).setdefault(name, {})["pose"] = {
                **m, "rank": info.get("rank"), "gate": g.status, "explanation": g.explanation, "options": g.options,
                "advisory": g.advisory}
            self.dec.record("peptide.access", name, f"pose rank {info.get('rank')}: {g.status}", g.explanation)
        atomic_write_json(st, self.state_path)

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
        box = self.make_box(raw, clean)
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
            sdf, rigid = l.get("sdf", ""), False
            if l.get("sequence"):
                smi = self._peptide_preflight(l, box)
                if l.get("fold") == "complex":
                    self._fold_complex(l, raw, smi)         # D-80: predicted complex → pose straight to MD, no docking
                    continue
                if l.get("fold"):
                    folded = self._fold_peptide(l)          # D-80: predicted structure as the starting conformation
                    if folded:
                        sdf, rigid = folded, True
            ligs.append(LigandInput(name=l["name"], smiles=smi, sdf=sdf, reference_pose=ref,
                                    protonation=l.get("protonation") or dcfg.get("protonation", "auto"),
                                    ph=float(self.cfg.get("ph", 7.4)), rigid_backbone=rigid))
        exh = dcfg.get("exhaustiveness", 16)
        if any(l.get("sequence") for l in self.cfg["ligands"]) and exh < 32:
            self.dec.record("docking.setup", "exhaustiveness", 32, f"胜肽配體自由度高，exhaustiveness 由 {exh} 自動提高到 32。")
            exh = 32
        if not ligs:                                        # every ligand came from a complex prediction (D-80)
            res = DockingResult(mode=dcfg.get("mode", "independent"), receptor_pdbqt="", box=box.to_dict(),
                                params={"skipped": "all ligands placed from a predicted complex (fold: complex)"})
            out.mkdir(parents=True, exist_ok=True)
            atomic_write_json(res.to_dict(), out / "docking_results.json")
            self._mark("docking", result=str(out / "docking_results.json"), mode=res.mode)
            return res
        res = dock(clean, ligs, box, out, mode=dcfg.get("mode", "independent"),
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
            least = None
            if e.get("recommended_rank") is None and e["name"] not in user:
                # D-78: no joint pose passed the conservative rules.  When the trouble is geometry the build can repair
                # and verify (ligands touching each other), take the pose with the lowest risk of entering MD instead
                # of stopping; only a failed redocking self-check or unreadable poses still stop here.
                least = self._least_risk_joint_pose(e) if res.mode == "simultaneous" else None
                if least is None:
                    refusal = self._fallback_refusal(e) if res.mode == "simultaneous" else ""
                    self._block("pose_selection",
                                f"{e['name']}：系統沒有推薦任何 pose（{e.get('reason') or '無合格候選'}）。{refusal}"
                                f"請在 pose_choices 指定名次，或檢查盒子/口袋設定後重跑對接。")
            rank = least[0] if least else int(user.get(e["name"], e["recommended_rank"]))
            if not 1 <= rank <= n:
                self._block("pose_selection", f"{e['name']} 只有 {n} 個 pose，無法選第 {rank} 名。")
            if least:
                why = least[1]
            else:
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
            if p.get("clash") and not least:
                # D-78: a joint pose whose ligands touch is no longer a dead end.  The same geometry check, rigid nudge,
                # soft-core relaxation and post-minimisation piercing check that guard every multi-ligand build decide
                # whether it can enter MD; if none of them can untangle it, the build stops and names the ligand to exclude.
                self.dec.record("workflow.pose", e["name"], f"rank {rank}（配體互相接觸）",
                                f"第 {rank} 名聯合姿勢的配體最短距離 {p['min_ll_distance']} Å（< 2 Å，對接層判為碰撞）。"
                                "不在這裡擋下：建模前的幾何檢查會先以剛體微調、必要時以軟核鬆弛解開，並在最小化後再檢查穿環；"
                                "仍解不開才停下來請你決定排除哪個配體。報告會標註。",
                                kind="human" if e["name"] in user else "auto_fixed")
            for lig in e["ligands"]:
                sel["ligands"][lig] = {"rank": rank, "sdf": e["pose_sdfs"][lig][rank - 1], "score": p["score"],
                                       "rmsd_ref": p.get("rmsd_ref"), "entry": e["name"],
                                       "smiles": e["smiles"][lig] if isinstance(e["smiles"], dict) else e["smiles"],
                                       "md_screen": screen_info,
                                       # D-98 (A7): the docking rejections of the used pose stay on record — a repair
                                       # later in the build never erases why docking rejected it
                                       "docking_rejections": list(p.get("rejection_codes") or []),
                                       "fallback": bool(least)}
            self.dec.record("workflow.pose", e["name"], f"rank {rank}", why,
                            kind="human" if e["name"] in user else ("auto_fixed" if least else "auto"))
        self._complex_picks(sel)                           # D-80: peptides placed from a predicted complex
        self._mark("pose_selection", selection=sel, choices_cfg=key)
        try:
            self._peptide_pose_access(sel)
        except Exception as exc:  # noqa: BLE001  (advisory check must never break pose selection)
            self.dec.record("peptide.access", "pose", "skipped", f"胜肽 pose 可及性檢查未完成：{type(exc).__name__}: {exc}")
        return sel

    def _least_risk_joint_pose(self, e: dict) -> tuple[int, str, list] | None:
        """D-78: when no joint pose passes the docking rules, the pose with the lowest risk of entering MD.

        Ranking (general, not tied to a case): first the docking objections other than ligand–ligand contact
        (score outside the window, shallow or surface contacts, ligands apart) — fewer is better; then
        `multi_ligand.rank_for_md` (can the build's check-and-nudge clear it, ligands lost, problems left, ligands nudged,
        closest contact, score).  None when the redocking self-check failed (the docking setup itself is not
        trustworthy) or no pose file can be read."""
        from .build import multi_ligand as ML
        reason = e.get("reason") or ""
        if "edocking" in reason:
            return None
        eligible, _ = self._fallback_eligibility(e)
        if not eligible:
            return None
        names = list(e.get("ligands") or [])
        poses, scores = {}, {}
        for p in e.get("poses") or []:
            if p["rank"] not in eligible:
                continue
            k = p["rank"] - 1
            try:
                poses[p["rank"]] = [ML.mol_from_sdf(e["pose_sdfs"][nm][k], nm) for nm in names]
                scores[p["rank"]] = p["score"]
            except Exception:  # noqa: BLE001
                continue
        if not poses:
            return None
        rec = (self.state()["steps"].get("receptor_docking") or {}).get("path")
        around = np.vstack([m.xyz for ms in poses.values() for m in ms])
        prot = ML.protein_near(rec, around) if rec and Path(rec).is_file() else None
        rows = ML.rank_for_md(poses, prot, scores)
        codes = {p["rank"]: list(p.get("rejection_codes") or []) for p in e["poses"]}
        for r in rows:
            # D-98 (A7): only geometry-repairable poses reach here, so no other docking objection remains; the original
            # rejections are kept with the row (and with the selection) for the report
            r["docking_objections"] = []
            r["docking_rejections"] = codes.get(r["rank"], [])
        st = self.state()
        st["least_risk_poses"] = {**(st.get("least_risk_poses") or {}), e["name"]: rows}
        atomic_write_json(st, self.state_path)
        b = rows[0]
        how = {0: "建模前的檢查可直接通過或以剛體微調解開，所有配體都保留",
               1: "剛體微調可解開，但有配體在此姿勢下漂浮、會被排除",
               2: "剛體微調解不開，要靠建模時的軟核鬆弛；若仍失敗會停下來請你決定排除哪個配體"}[b["tier"]]
        top = "；".join(f"第 {r['rank']} 名（{['可直接或微調', '會排除漂浮配體', '需軟核鬆弛'][r['tier']]}，"
                       f"剩餘問題 {r['problems']}，分數 {r['score']:.2f}）" for r in rows[:3])
        orig = "、".join(x["text"] for x in b["docking_rejections"]) or "—"
        n_out = len(e.get("poses") or []) - len(eligible)
        why = (f"沒有聯合姿勢通過保守條件（{reason or '配體互相接觸'}）。不停在這裡，改依進入 MD 的風險排序"
               f"只有「可由建模修正的幾何問題」的姿勢（{len(eligible)} 個；另有 {n_out} 個因對接模型限制或共同佔據假設不成立而不列入，"
               f"這些拒絕不會被修復抹掉），選第 {b['rank']} 名（{b['score']:.2f} kcal/mol）：{how}。"
               f"這個姿勢在對接層被排除的原始理由（保留）：{orig}。排序依據依序為：幾何能否解開、"
               f"排除的配體數、微調後剩餘的重疊與穿環、需要微調的配體數、最短接觸距離、分數。前三名：{top}。"
               "進入 MD 前仍會做幾何檢查、剛體微調、必要時軟核鬆弛，最小化後再查穿環；報告會標註這是低風險選擇而不是推薦。"
               "若要用別的姿勢，在姿勢表點選即可。")
        return b["rank"], why, rows

    @staticmethod
    def _fallback_eligibility(e: dict) -> tuple[set, dict]:
        """D-98 (A7): ranks a least-risk fallback may consider — every docking rejection of the pose is
        `geometry_repairable`.  Returns (eligible ranks, {rank: why not}).  The whole entry is refused when the docking
        model or the co-occupancy hypothesis failed at entry level (pocket too small, redocking).  A pose written before
        D-98 has no rejection codes: it is NOT eligible (the text is not parsed to guess what it meant)."""
        from .docking.poses import GEOMETRY_REPAIRABLE, CODE_TEXT
        if e.get("recommendation_code") and e["recommendation_code"] != GEOMETRY_REPAIRABLE:
            return set(), {"entry": f"{CODE_TEXT.get(e['recommendation_code'], e['recommendation_code'])}"
                                    f"（{e.get('recommendation_rule') or '—'}）"}
        ok, why_not = set(), {}
        for p in e.get("poses") or []:
            codes = p.get("rejection_codes")
            if codes is None:
                why_not[p["rank"]] = "舊的對接結果沒有拒絕代碼"
            elif not codes:
                why_not[p["rank"]] = "沒有被排除（不需要後備）"
            elif all(c.get("code") == GEOMETRY_REPAIRABLE for c in codes):
                ok.add(p["rank"])
            else:
                why_not[p["rank"]] = "、".join(f"{c.get('text')}〔{CODE_TEXT.get(c.get('code'), c.get('code'))}〕"
                                              for c in codes if c.get("code") != GEOMETRY_REPAIRABLE)
        return ok, why_not

    def _fallback_refusal(self, e: dict) -> str:
        """Why no least-risk fallback was taken (appended to the NEEDS_HUMAN message)."""
        ok, why_not = self._fallback_eligibility(e)
        if ok:
            return ""
        if "entry" in why_not:
            return f"不採用低風險後備：{why_not['entry']}，這不是移動原子能修正的問題。"
        if why_not and all(v == "舊的對接結果沒有拒絕代碼" for v in why_not.values()):
            return "不採用低風險後備：這份對接結果是舊版寫的、沒有拒絕代碼，無法確認拒絕是否只是可修的幾何問題；重新對接即可。"
        items = "；".join(f"第 {r} 名：{v}" for r, v in list(why_not.items())[:4])
        return f"不採用低風險後備：沒有任何姿勢的拒絕理由全部屬於可由建模修正的幾何問題（{items}）。"

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
                                progress_cb=progress_cb, group_id=f"screen_{rank}", decisions=self.dec)
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

    def _alone(self) -> set[str]:
        a = (self.cfg.get("binding") or {}).get("alone") or {}
        return {k for k, v in a.items() if v} if isinstance(a, dict) else set(a)

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
        elif self._alone():
            # D-93: "只算單獨結合" from the binding path gate — a ligand blocked in the shared pocket is also built alone
            for name in sel["ligands"]:
                if name in self._alone():
                    out.append({"key": f"docked_{name}", "mode": "docked_single", "ligands": [name]})
        if "docked_multi" in systems:
            names = list(sel["ligands"])
            if len(names) < 2:
                self._block("md_cases", "docked_multi 需要至少 2 個配體。")
            geo = self._multi_geometry(sel, names)          # both modes: hydrogens and nudges were never seen by Vina
            if len(geo["ligands"]) < 2:
                self.dec.record("multi_ligand.geometry", "docked_multi", "skipped",
                                f"幾何檢查後只剩 {len(geo['ligands'])} 個配體，多配體系統等同單一配體系統，不另建 docked_multi。")
            else:
                if sel["mode"] != "simultaneous":
                    self.dec.record("workflow.md", "docked_multi from independent", "allowed",
                                    "配體分別對接，選定姿勢經幾何檢查（無重疊、無穿環）後組成多配體系統；嚴格的共同佔位請用 simultaneous 模式。")
                out.append({"key": "docked_multi", "mode": "docked_multi", "ligands": geo["ligands"], "picks": geo["picks"]})
        return out

    def _multi_geometry(self, sel: dict, names: list[str], *, allow_alternatives: bool = True) -> dict:
        """D-60: geometry of the multi-ligand complex before it is built — overlaps, ring piercing (穿環) and floating
        ligands; a small rigid nudge repairs what it can (AUTO_FIXED), a floating ligand leaves the multi-ligand system,
        anything else stops with the ligand to exclude named (NEEDS_HUMAN).  Human decisions: `multi_ligand.exclude`,
        `multi_ligand.accept_geometry`.  Result kept in state["multi_ligand"] for the report and the GUI."""
        from .build import multi_ligand as ML
        human = self.cfg.get("multi_ligand") or {}
        exclude = [n for n in (human.get("exclude") or []) if n in names]
        sig = {"names": list(names), "sdf": [sel["ligands"][n].get("sdf") for n in names], "human": human}
        prev = self.state().get("multi_ligand") or {}
        if prev.get("signature") == sig and prev.get("status") in ("PASS", "AUTO_FIXED", "ACCEPTED", "DEFERRED"):
            picks = {n: {**sel["ligands"][n], "sdf": a["sdf"]} for n, a in (prev.get("adjusted") or {}).items()}
            return {"ligands": prev["ligands"], "picks": picks, "record": prev}
        keep = [n for n in names if n not in exclude]
        if len(keep) < 2:          # no co-occupancy system is left to check; single-ligand builds keep their own backstop
            record = {"status": "PASS", "ligands": keep, "excluded": exclude, "auto_excluded": [], "culprit": None, "adjusted": {},
                      "per_ligand": {}, "why": [f"使用者排除 {'、'.join(exclude)} 後只剩 {len(keep)} 個配體。",
                                               f"After the user excluded {', '.join(exclude)}, {len(keep)} ligand(s) remain."],
                      "options": [], "decision": human, "signature": sig}
            st = self.state(); st["multi_ligand"] = record; atomic_write_json(st, self.state_path)
            return {"ligands": keep, "picks": {}, "record": record}
        mols = []
        for n in names:
            try:
                mols.append(ML.mol_from_sdf(sel["ligands"][n]["sdf"], n))
            except Exception as exc:  # noqa: BLE001
                self.dec.record("multi_ligand.geometry", n, "skipped", f"無法讀取 {n} 的姿勢檔（{type(exc).__name__}）；此配體不做幾何檢查。")
        rec = (self.state()["steps"].get("receptor_docking") or {}).get("path")
        around = np.vstack([m.xyz for m in mols]) if mols else np.zeros((1, 3))
        prot = ML.protein_near(rec, around) if rec and Path(rec).is_file() else None
        r = ML.resolve(mols, prot, exclude=exclude, accept=bool(human.get("accept_geometry")))
        outdir = self.dir / "multi_ligand"
        outdir.mkdir(exist_ok=True)
        picks = {}
        for n, a in r["adjusted"].items():
            dst = outdir / f"{safe_name(n)}_nudged.sdf"
            ML.write_sdf_coords(sel["ligands"][n]["sdf"], dst, a["xyz"], note=f"MD20 nudged rmsd={a['rmsd']}A")
            picks[n] = {**sel["ligands"][n], "sdf": str(dst)}
        record = {"status": r["status"], "why": list(r["why"]), "options": r["options"], "culprit": r["culprit"],
                  "ligands": r["ligands"], "excluded": r["excluded"], "auto_excluded": r["auto_excluded"],
                  "adjusted": {n: {k: v for k, v in a.items() if k != "xyz"} | {"sdf": picks[n]["sdf"]} for n, a in r["adjusted"].items()},
                  "per_ligand": {n: {"overlaps": len(v["overlaps"]), "min_overlap_A": min((o["d"] for o in v["overlaps"]), default=None),
                                     "piercings": len(v["piercings"]), "contacts": v["contacts"], "floating": v["floating"],
                                     "partners": v["partners"]} for n, v in r["per_ligand"].items()},
                  "protein_checked": prot is not None, "decision": human, "signature": sig}
        st = self.state(); st["multi_ligand"] = record; atomic_write_json(st, self.state_path)
        if r["status"] == "NEEDS_HUMAN" and allow_alternatives:
            alt = self._alternative_joint_pose(sel, names, prot)
            if alt is not None:
                return self._multi_geometry(sel, names, allow_alternatives=False)
        if r["status"] == "NEEDS_HUMAN" and human.get("softcore", True) and _openmm_available():
            # D-61: a rigid nudge was not enough; the build stage can still untangle the ligand with a soft-core relaxation
            # (it may pass through its neighbours while everything else is held).  Defer instead of asking now.
            record["status"] = "DEFERRED"
            record["why"] = [r["why"][0] + "（剛體微調不足；交給建模層的軟核鬆弛處理，失敗才請使用者決定。）",
                             r["why"][1] + " (A rigid nudge is not enough; deferred to the soft-core relaxation at build time, "
                                           "and only if that fails is a decision asked for.)"]
            st = self.state(); st["multi_ligand"] = record; atomic_write_json(st, self.state_path)
            self.dec.record("multi_ligand.geometry", "+".join(names), "DEFERRED", record["why"][0], kind="auto")
            return {"ligands": r["ligands"], "picks": picks, "record": record}
        if r["status"] == "NEEDS_HUMAN":
            self._block("md_cases", "多配體幾何檢查：" + r["why"][0], multi_ligand=record,
                        gates=[{"name": "multi-ligand geometry", "status": "NEEDS_HUMAN", "explanation": r["why"][0],
                                "options": r["options"]}])
        kind = {"PASS": "auto", "AUTO_FIXED": "auto_fixed", "ACCEPTED": "human"}[r["status"]]
        self.dec.record("multi_ligand.geometry", "+".join(names), r["status"],
                        r["why"][0] + ("；使用者選擇照原樣進入 MD（最小化可能大幅推開原子，報告會標註）。" if r["status"] == "ACCEPTED" else ""),
                        kind=kind)
        return {"ligands": r["ligands"], "picks": picks, "record": record}

    def _alternative_joint_pose(self, sel: dict, names: list[str], prot) -> int | None:
        """D-60: the chosen joint pose cannot enter MD; before asking a human, try the other joint poses that passed the
        docking rules (largest cluster first, then score).  The first one whose geometry passes or can be nudged replaces
        the selection for every system (single-ligand cases use the same joint pose).  Never overrides a human choice."""
        from .build import multi_ligand as ML
        if sel.get("mode") != "simultaneous" or "joint" in (self.cfg.get("pose_choices") or {}):
            return None
        d = self._done("docking")
        res = load_json(d["result"], {}) if d and d.get("result") else {}
        e = next((x for x in res.get("entries", []) if x.get("name") == "joint"), None)
        if not e:
            return None
        cur = {sel["ligands"][n].get("rank") for n in names}
        cands = sorted([p for p in e["poses"] if not p.get("rejected") and p["rank"] not in cur],
                       key=lambda p: (-p.get("cluster_size", 1), p["score"]))
        for p in cands:
            k = p["rank"] - 1
            try:
                mols = [ML.mol_from_sdf(e["pose_sdfs"][n][k], n) for n in names]
            except Exception:  # noqa: BLE001
                continue
            r = ML.resolve(mols, prot)
            if r["status"] in ("PASS", "AUTO_FIXED") and not r["auto_excluded"]:
                old = sorted(cur)
                for n in names:
                    sel["ligands"][n].update({"rank": p["rank"], "sdf": e["pose_sdfs"][n][k], "score": p["score"]})
                st = self.state()
                if st["steps"].get("pose_selection", {}).get("selection"):
                    st["steps"]["pose_selection"]["selection"] = sel
                    atomic_write_json(st, self.state_path)
                self.dec.record("multi_ligand.geometry", "joint pose", f"rank {p['rank']}",
                                f"原選聯合姿勢第 {old} 名有無法微調的重疊或穿環；改用同樣通過對接條件、幾何可進入 MD 的第 {p['rank']} 名"
                                f"（{p['score']:.2f} kcal/mol，cluster {p.get('cluster_size', 1)} 個姿勢）。所有系統改用此姿勢。",
                                kind="auto_fixed")
                return p["rank"]
        return None

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
                                f"未指定 padding：{tier} tier 預設 {pad} nm（溶質到自己週期影像的最小距離——OpenMM 的 padding 只加一次，"
                                f"盒寬 = 2×溶質半徑 + padding；菱形十二面體盒）。"
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
                                    f"啟用結合自由能計算：padding 下限由 {pad} 提高到 {need} nm；"
                                    f"實際大小在建模時依 SMD 規則算出（D-99，見 box size for SMD 閘門）。")
                    self._pad_logged = True
                pad = need
        return pad

    def _smd_box(self, ligands: list[str] | None, *, screen: bool = False) -> dict | None:
        """D-99: cases that will be pulled are sized by the SMD box rule at build time (build.assemble.smd_padding)."""
        b = self.cfg.get("binding") or {}
        if screen or not b.get("enabled") or not ligands:
            return None
        bc = b.get("config") or {}
        from .sampling.binding import BindingConfig
        d = BindingConfig()
        pulled = [n for n in ligands if n in (b.get("ligands") or ligands)]
        if not pulled:
            return None
        return {"pull_nm": float(bc.get("pull_distance_nm", bc.get("pull_distance", d.pull_distance_nm))),
                "margin_nm": float(bc.get("box_margin_nm", d.box_margin_nm)),
                "allowance_nm": float(bc.get("box_allowance_nm", 0.5)), "ligands": pulled}

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
        s = build_case(case, receptor=raw, decisions=self.dec, ligand_references=[picks[n]["smiles"] for n in small],
                       ligand_poses=[picks[n]["sdf"] for n in small], ph=self.cfg.get("ph", 7.4),
                       padding_nm=self._padding_nm(names, screen=screen), smd_box=self._smd_box(names, screen=screen),
                       keep_hetero=set(self.cfg.get("keep_hetero", [])),
                       extra_ligand_resnames=drop, peptides=peps or None, ligand_names=small,
                       exclude_chains=set(self.cfg["receptor"].get("exclude_chains", [])),
                       metal_policy=self.cfg.get("metal_policy") or None,
                       peptide_policy=self.cfg.get("peptide_policy") or None,
                       metal_params=self._metal_params(), solvent=self._solvent(screen),
                       box_shape=self.cfg.get("md", {}).get("box_shape", "dodecahedron"),
                       ionic_strength_molar=float(self.cfg.get("md", {}).get("ionic_strength_molar", 0.15)),
                       ions=self.cfg.get("md", {}).get("ions") or None,
                       membrane=self.cfg.get("md", {}).get("membrane") or None,      # docs/specs/membrane.md
                       human_choices=self.cfg.get("human_choices") or None,   # receptor gate choices apply to the MD build too
                       ligand_metal=self.cfg.get("ligand_metal") or None,
                       accept_geometry=bool((self.cfg.get("multi_ligand") or {}).get("accept_geometry")))
        lmap = {n: f"L{i:02d}" for i, n in enumerate(small, 1)} | {p["name"]: p["name"] for p in peps}
        return s, lmap

    def build_cases(self, raw: Path, sel: dict) -> dict:
        built = dict((self._done("md_cases") or {}).get("cases", {}))
        for spec in self._cases_to_build(sel):
            if spec["key"] in built and built[spec["key"]].get("status") == "PASS":
                continue
            case = self.project.new_case(f"{self.name}_{spec['key']}")
            s, lmap = self._build_one(case, raw, spec["ligands"], {**sel["ligands"], **(spec.get("picks") or {})})
            built[spec["key"]] = {"case_id": case.case_id, "mode": spec["mode"], "ligands": spec["ligands"], "ligand_map": lmap,
                                  "status": s["status"], "blocking": s.get("blocking"), "blocking_detail": s.get("blocking_detail")}
            self._mark("md_cases", cases=built)
            if s["status"] != "PASS":
                self._block("md_cases", f"{spec['key']} 建模需要人工決定：{s.get('blocking')}：{s.get('blocking_detail')}", cases=built)
        return built

    # ------------------------------------------------------------------ membrane systems without a receptor (D-80)
    def membrane_only_type(self) -> str | None:
        """"surface" (case B: a peptide or small molecule above a bilayer) or "bilayer" (case C: lipids only) when
        md.membrane asks for one of them; None for every other workflow (case A goes through the normal build)."""
        m = (self.cfg.get("md") or {}).get("membrane")
        t = m.get("type") if isinstance(m, dict) else None
        return t if t in ("surface", "bilayer") else None

    def _membrane_input_gate(self, mtype: str) -> None:
        """Inputs that do not fit case B or C stop with options (block rather than guess)."""
        ligs = [l for l in self.cfg.get("ligands") or [] if isinstance(l, dict)]
        rec = self.cfg.get("receptor") or {}
        problem, options = None, []
        if rec.get("pdb_id") or rec.get("file") or rec.get("alphafold"):
            problem = (f"md.membrane.type = {mtype} 不使用受體，但設定裡有受體（{rec.get('pdb_id') or rec.get('file') or 'AlphaFold'}）。"
                       "不確定要把受體放進膜裡還是忽略它。")
            options = ["md.membrane.type: protein", "移除 receptor（只模擬膜與溶質）"]
        elif mtype == "surface" and not ligs:
            problem = "type: surface 要有胜肽或小分子放在膜上方，但沒有配體。"
            options = ["md.membrane.type: bilayer"]
        elif mtype == "bilayer" and ligs:
            problem = f"type: bilayer 是純膜，但設定裡有 {len(ligs)} 個配體。"
            options = ["md.membrane.type: surface"]
        elif any(l.get("fold") == "complex" for l in ligs):
            problem = "fold: complex 需要受體（預測複合物再疊合到受體），膜表面系統沒有受體。"
            options = ["改用對接（fold: true）", "不使用預測結構，改用延伸構形（fold: false）"]
        if problem:
            self._block("md_cases", problem, gates=[{"name": "membrane type", "status": "NEEDS_HUMAN",
                                                     "explanation": problem, "options": options}])

    def _membrane_solute(self, l: dict, bdir: Path, index: int):
        """One solute of a surface system: a peptide (ff14SB, chain P; predicted structure when `fold` is set) or a
        small molecule (conformer from the SMILES; prepare_ligand's parameter ladder)."""
        if l.get("sequence"):
            from .build.peptide import prepare_peptide, clean_sequence
            pose = self._fold_peptide(l) if l.get("fold") else None
            self.dec.record("build.membrane", l["name"], "peptide above the bilayer",
                            f"{l['name']} 以序列建成胜肽（ff14SB，獨立 chain P）" +
                            ("，起始構形用預測結構" if pose else "，起始構形為由序列建立的構形") +
                            "；放在膜上方由建膜程式決定位置（md.membrane.surface_distance_nm），不經對接。", kind="auto")
            return prepare_peptide(clean_sequence(l["sequence"]), pose, bdir / "ligands", name=l["name"], chain_id="P",
                                   termini=l.get("termini", "charged"), decisions=self.dec)
        from .build.ligand import prepare_ligand
        return prepare_ligand(l.get("sdf") or l["smiles"], None, bdir / "ligands", name=f"L{index:02d}", decisions=self.dec)

    def build_membrane_cases(self) -> dict:
        """Cases B and C (docs/specs/membrane.md §2): no receptor and no docking.  surface → one system per solute
        (key surface_<name>); bilayer → one system (key bilayer).  Built with membrane.build_membrane_system."""
        from .build.membrane import build_membrane_system
        from .build.pipeline import _update_case
        mtype = self.membrane_only_type()
        self._membrane_input_gate(mtype)
        md = self.cfg.get("md") or {}
        built = dict((self._done("md_cases") or {}).get("cases", {}))
        ligs = [l for l in self.cfg.get("ligands") or [] if isinstance(l, dict)]
        specs = [("bilayer", [])] if mtype == "bilayer" else [(f"surface_{safe_name(l['name'])}", [l]) for l in ligs]
        if not built:
            self.dec.record("workflow.membrane", "system", mtype,
                            ("膜表面接觸（情境 B）：沒有受體、不做對接，每個溶質各建一個系統，放在上葉磷原子平面上方"
                             f" {md['membrane'].get('surface_distance_nm', 1.0)} nm，水盒由脂雙層取代。" if mtype == "surface" else
                             "純膜（情境 C）：只有脂雙層、水與離子，不做對接。"), kind="auto")
        for key, solutes in specs:
            if built.get(key, {}).get("status") == "PASS":
                continue
            case = self.project.new_case(f"{self.name}_{key}")
            recs, blocked = [], None
            for i, l in enumerate(solutes, 1):
                r = self._membrane_solute(l, case.build_dir, i)
                if r.status == "NEEDS_HUMAN":
                    blocked = [g for g in (r.gates or {}).get("gates", []) if g.get("status") == "NEEDS_HUMAN"]
                    break
                recs.append(r)
            if blocked is None:
                res = build_membrane_system(case.build_dir, md["membrane"], ligands=recs, decisions=self.dec,
                                            ionic_strength_molar=float(md.get("ionic_strength_molar", 0.15)),
                                            ions=md.get("ions") or None, solvent=self._solvent())
                # same layout as build_case(): readers look for the assembly record (ligand indices, gates) under "assembly"
                bm_path = case.build_dir / "build_manifest.json"
                bm = load_json(bm_path, {})
                if bm and "assembly" not in bm:
                    bm["assembly"] = res.to_dict()
                    atomic_write_json(bm, bm_path)
                if res.status == "NEEDS_HUMAN":
                    blocked = [g for g in (res.gates or {}).get("gates", []) if g.get("status") == "NEEDS_HUMAN"]
            status = "NEEDS_HUMAN" if blocked is not None else "PASS"
            _update_case(case, {"status": status})
            names = [l["name"] for l in solutes]
            built[key] = {"case_id": case.case_id, "mode": f"membrane_{mtype}", "ligands": names,
                          "ligand_map": {n: (n if l.get("sequence") else f"L{i:02d}") for i, (n, l) in enumerate(zip(names, solutes), 1)},
                          "status": status, "blocking": "assembly" if blocked is not None else None, "blocking_detail": blocked}
            self._mark("md_cases", cases=built)
            if blocked is not None:
                self._block("md_cases", f"{key} 建膜需要人工決定：" + "；".join(g.get("explanation", "") for g in blocked[:2]),
                            cases=built)
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
            if md.get("membrane"):
                from .engine.protocol import membrane_protocol
                from .build.membrane import membrane_temperature
                proto = membrane_protocol(proto, temperature_k=membrane_temperature(md["membrane"]))
            if md.get("stage_overrides"):
                from .engine.protocol import RESTRAINT_STRATEGIES
                npt_factor = float(RESTRAINT_STRATEGIES[self._restraint_strategy()].get("npt_length_factor", 1.0))
                for st in proto.stages:
                    for k, v in md["stage_overrides"].get(st.name, {}).items():
                        # an NPT length is the *base* length; the gentle strategy still doubles it (D-49)
                        setattr(st, k, float(v) * npt_factor if (st.name == "npt" and k == "length_ps") else v)
            self._plan_long_run(key, case, proto, runs)
            group = runs.get(key, {}).get("group_id") or f"wf_{self.name}_{key}"
            summary = run_replicas(case, proto, make_factory(case, proto), n=proto.replicas, should_pause=should_pause,
                                   progress_cb=progress_cb, group_id=group, decisions=self.dec)
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

    def _plan_long_run(self, key: str, case, proto, runs: dict) -> None:
        """Production > 100 ns (or an md.long_run block): save interval, log interval, chunk length and disk check
        (engine/longrun.py, docs/specs/long_timescale.md).  > 1 µs waits for md.long_run_confirmed."""
        from .engine.longrun import needs_plan, plan_long_run, apply_plan, record_plan
        md = self.cfg.get("md", {})
        lr = md.get("long_run") or {}
        prod = next((s for s in getattr(proto, "stages", []) if s.name == "production"), None)
        if prod is None or not needs_plan(prod.length_ps / 1000.0, lr):
            return
        bm = load_json(case.build_dir / "build_manifest.json", {})
        # build_case() keeps the assembly counts under "assembly"; assemble_system alone (membrane cases B, C) at top level
        bm = {**(bm.get("assembly") or {}), **{k: v for k, v in bm.items() if v not in (None, 0, "")}}
        n_atoms = int(bm.get("n_atoms") or 0)
        if n_atoms <= 0:
            self._block("md_runs", f"{key}：正式模擬 {prod.length_ps / 1000:g} ns 需要先估計硬碟用量，但 build 沒有原子數。"
                        "請重新建模後再試。", runs=runs)
        solute = int(bm.get("n_protein_atoms") or 0) + int(bm.get("n_ligand_atoms") or 0)
        free = None
        try:
            import shutil as _sh
            free = _sh.disk_usage(case.dir).free / 1e9
            # space this case's runs already use counts as available: a resumed run must not block on its own files
            free += sum(p.stat().st_size for p in (case.dir / "runs").rglob("*") if p.is_file()) / 1e9
        except OSError:
            pass
        plan = plan_long_run(n_atoms=n_atoms, production_ns=prod.length_ps / 1000.0, timestep_fs=prod.timestep_fs,
                             ns_per_day=md.get("ns_per_day"), bench=md.get("benchmark"),
                             n_solute_atoms=solute or None, solute_only=lr.get("solute_only"),
                             target_gb=float(lr.get("target_gb") or 20.0), disk_free_gb=free,
                             confirmed=bool(md.get("long_run_confirmed")), replicas=proto.replicas,
                             base_trajectory_ps=prod.trajectory_interval_ps, base_report_ps=prod.report_interval_ps,
                             base_checkpoint_ps=prod.checkpoint_interval_ps)
        if plan.blocked:
            msg = f"{key}：" + plan.message_zh()
            ev = {k: v for k, v in plan.to_dict().items() if k not in ("issues", "decisions", "stage_overrides")}
            self._block("md_runs", msg, runs=runs, gates=[{"name": "long run", "status": "NEEDS_HUMAN", "explanation": msg,
                                                           "options": plan.options(), "evidence": ev}])
        apply_plan(proto, plan)
        record_plan(plan, self.dec, stage=f"workflow.md.{key}")
        st = self.state()                                   # D-82: the report compares this plan with the run
        st.setdefault("long_run", {})[key] = {k: v for k, v in plan.to_dict().items() if k not in ("decisions",)}
        atomic_write_json(st, self.state_path)

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
            membrane = bool((self.cfg.get("md") or {}).get("membrane"))
            if man.get("status") != "PASS":
                bm = load_json(case.build_dir / "build_manifest.json", {})
                if self.membrane_only_type():
                    # cases B and C have no receptor: membrane analysis only (analysis/membrane_run.py)
                    from .analysis.membrane_run import membrane_only_analysis
                    man = membrane_only_analysis(run_dir, bm, label=key, decisions=self.dec)
                else:
                    groups = {l["name"]: l["heavy_atom_indices"] for l in manifest_ligands(bm) if l.get("heavy_atom_indices")}
                    man = analyse_run(run_dir, top, label=key, ligand_groups=groups or None, metal_indices=metal_indices_from_manifest(bm),
                                      decisions=self.dec, ligand_charges=manifest_ligand_charges(bm))
                    if membrane:            # case A: membrane metrics and the equilibration acceptance next to the usual ones
                        from .analysis.membrane_run import analyse_membrane_run
                        try:
                            ms = analyse_membrane_run(run_dir, bm, label=key, decisions=self.dec)
                            man = {**man, "membrane_metrics_file": str(run_dir / "analysis" / "membrane_metrics.json"),
                                   "membrane_acceptance": ms.get("acceptance"),
                                   **({"membrane_file": ms["membrane_file"]} if ms.get("membrane_file") else {})}
                        except Exception as exc:  # noqa: BLE001 — the general analysis above stands; the failure is recorded
                            self.dec.record("analysis.membrane", key, "failed", f"膜分析失敗：{type(exc).__name__}: {exc}。"
                                            "一般分析的結果仍保留，膜的面積、厚度與平衡驗收沒有計算。", kind="auto")
            acc = man.get("membrane_acceptance")
            if acc and acc.get("status") != "PASS":
                st = self.state()
                st.setdefault("advisories", {})[f"membrane equilibration {key}"] = acc
                atomic_write_json(st, self.state_path)
            out[key] = man
            metrics[key] = load_json(man["metrics_file"], {})
        comp = compare_runs(metrics, self.dir / "figures") if len(metrics) > 1 and not self.membrane_only_type() else {}
        self._mark("analysis", summaries=out, comparison=comp)
        return {"summaries": out, "comparison": comp}

    # WP3: what a tier is allowed to claim.  Sampling below the tier minimum still runs, but ΔG° is not reported.
    TIER_BINDING = {"classroom": {"dG": False},
                    "teaching": {"dG": True, "min_window_ps": 500.0},
                    "research": {"dG": True, "min_window_ps": 2000.0, "min_replicas": 3, "max_half_split_kj": 2.0}}

    def _binding_config(self, b: dict):
        from .sampling.binding import BindingConfig
        from dataclasses import fields
        valid = {f.name for f in fields(BindingConfig)}
        user_cfg = {k: v for k, v in (b.get("config") or {}).items() if k in valid}
        # D-41: a tier that requires long windows for ΔG° must also *run* them by default — otherwise teaching/research
        # always withhold ΔG° with the 50 ps library default.  An explicit binding.config value wins (and is judged).
        tier = self.cfg.get("md", {}).get("tier", "teaching")
        min_w = self.TIER_BINDING.get(tier, {}).get("min_window_ps")
        if min_w and "window_prod_ps" not in user_cfg:
            user_cfg["window_prod_ps"] = float(min_w)
            user_cfg.setdefault("window_equil_ps", max(BindingConfig.window_equil_ps, float(min_w) / 10.0))
            self.dec.record("workflow.binding", "window length", f"{min_w:.0f} ps（equil {user_cfg['window_equil_ps']:.0f} ps）",
                            f"{tier} 等級要輸出 ΔG° 需每個 window ≥ {min_w:.0f} ps；未在 binding.config 指定時自動採用此長度"
                            "（每個 window 的算力約為 classroom 的 10 倍以上）。", kind="auto")
        cfg = BindingConfig(**user_cfg)
        return cfg

    @staticmethod
    def _binding_assessment(reps: list, dG, withheld) -> dict:
        """Replica-combined assessment (every replica must support a conclusion); the tier rule and replica
        aggregation may withhold ΔG° further, which removes the ΔG°-based eligibility but not the diagnostics."""
        from .sampling.assessment import assess_pmf, combine_assessments
        per = [getattr(r, "assessment", None) or assess_pmf(r.pmf, dG_withheld=(r.pmf or {}).get("dG_withheld"),
                                                            has_dG=r.dG_standard_kj_mol is not None) for r in reps]
        a = combine_assessments(per)
        if dG is None:
            a["eligibility"] = {**a["eligibility"], "dG_standard": False, "affinity_ranking": False}
            if withheld:
                a["reasons"] = sorted(set(a["reasons"]) | {f"ΔG° withheld: {withheld}"})
        return a

    def _tier_withholds_dG(self, cfg, res, n_done: int = 1) -> str | None:
        tier = self.cfg.get("md", {}).get("tier", "teaching")
        rule = self.TIER_BINDING.get(tier, self.TIER_BINDING["teaching"])
        if not rule["dG"]:
            return "classroom 等級只展示 ΔPMF 趨勢，不輸出 ΔG° 絕對值（取樣不足以支持定量結論）。"
        if cfg.window_prod_ps < rule.get("min_window_ps", 0):
            return (f"{tier} 等級要求每個 window ≥ {rule['min_window_ps']:.0f} ps，本次只有 {cfg.window_prod_ps:.0f} ps；"
                    f"ΔG° 不輸出，ΔPMF 僅供定性比較。")
        if rule.get("min_replicas") and int(n_done) < rule["min_replicas"]:
            return (f"research 等級要求 ≥ {rule['min_replicas']} 個獨立 MD 起點的結合計算；實際只有 {n_done} 個不同的 MD 起點"
                    f"（共用同一個 MD 終點的拉離不算獨立起點；設定 binding.replicas 與 md.replicas），ΔG° 不輸出。")
        hs = (res.pmf.get("half_split") or {}).get("diff_kj_mol")
        if rule.get("max_half_split_kj") and (hs is None or hs > rule["max_half_split_kj"]):
            return f"前後半段 ΔPMF 差 {hs} kJ/mol > {rule['max_half_split_kj']}：未收斂，ΔG° 不輸出。"
        return None

    def _binding_targets(self, runs: dict, built: dict) -> tuple[list[dict], dict[str, list[str]]]:
        """(targets, contexts).  Single-ligand cases → key = ligand name (backward compatible);
        WP9: every ligand of a docked_multi case is pulled from the shared complex → key = "multi:<ligand>".
        D-87: `binding.added` holds target keys chosen later in the GUI (after the report, one ligand at a time);
        they run even when binding.enabled is false, and only they are added."""
        b = self.cfg.get("binding", {})
        enabled = bool(b.get("enabled"))
        alone = self._alone()
        added = set(b.get("added") or []) | alone           # D-93: pull the ligand from its own single-ligand system …
        wanted = (set(b["ligands"]) if b.get("ligands") else None) if enabled else set()
        targets, ctx = [], {"single": []}

        sk = b.get("skip_targets") or {}
        skip = {k for k, v in sk.items() if v} if isinstance(sk, dict) else set(sk)
        skip |= {f"multi:{n}" for n in alone}               # … instead of from the shared pocket

        def take(key: str, lig: str) -> bool:
            if key in skip:                          # D-92: the student chose to leave this one out
                return False
            return key in added or (enabled and (wanted is None or lig in wanted))
        for key, c in built.items():
            if key not in runs:
                continue
            if c["mode"] == "docked_single":
                for n in c["ligands"]:
                    if take(n, n):
                        targets.append({"key": n, "ligand": n, "run_key": key, "others": []})
                        ctx["single"].append(n)
            elif c["mode"] == "docked_multi" and (b.get("multi", True) or any(a.startswith("multi:") for a in added)):
                names = [n for n in c["ligands"] if take(f"multi:{n}", n)]
                ctx[f"multi:{key}"] = []
                for n in names:
                    targets.append({"key": f"multi:{n}", "ligand": n, "run_key": key,
                                    "others": [m for m in c["ligands"] if m != n]})
                    ctx[f"multi:{key}"].append(f"multi:{n}")
        return targets, ctx

    def _anchor_override(self, name: str, bm: dict) -> list[int] | None:
        """D-93: anchor residues the student typed at the path gate (binding.anchor_residues[target])."""
        spec = ((self.cfg.get("binding") or {}).get("anchor_residues") or {}).get(name)
        if not spec:
            return None
        from .sampling.binding import anchor_atoms_from_residues
        idx, missing = anchor_atoms_from_residues(bm["topology_pdb"], spec)
        if missing or len(idx) < 3:
            msg = (f"{name}：指定的 anchor 殘基 {spec} " + (f"找不到 Cα：{', '.join(missing)}" if missing else "少於 3 個") +
                   "。請輸入結構中的殘基編號（例如 120, 145, A:163），至少 3 個，位在配體要離開方向的反側。")
            self._block("binding", msg, gates=[{"name": "binding path", "status": "NEEDS_HUMAN", "explanation": msg,
                                                "evidence": {"target": name},
                                                "options": [f"指定 anchor 殘基，改變拉離方向（binding.anchor_residues）",
                                                            f"略過 {name}，先算其他配體（binding.skip_targets）",
                                                            "binding.enabled: false（只做 MD）"]}])
        self.dec.record("binding.anchor", name, spec, f"使用者指定 anchor 殘基 {spec}（{len(idx)} 個 Cα）；拉離方向 = anchor 質心 → 配體質心。",
                        kind="human")
        return idx

    def binding(self, runs: dict, built: dict, platform, *, should_pause=None, progress_cb=None) -> dict:
        from .sampling.binding import run_binding, BindingConfig
        from types import SimpleNamespace
        from .sampling.multi import compare_binding, aggregate_binding_replicas
        b = self.cfg.get("binding", {})
        if not b.get("enabled") and not b.get("added") and not self._alone():
            return {}
        if self._solvent() == "gbn2":
            msg = ("隱式溶劑（GBn2）不做 SMD／傘狀採樣：拉離過程的去溶劑化能障在連續介質模型下會失真，PMF 與 ΔG° 不可信。")
            self._block("binding", msg, gates=[{"name": "implicit solvent + binding", "status": "NEEDS_HUMAN", "explanation": msg,
                                                "options": ["md.solvent: explicit（顯式水，重建並重跑 MD）", "binding.enabled: false（只做 MD）"]}])
        if (self.cfg.get("md") or {}).get("membrane"):
            msg = ("膜系統還沒有 SMD／傘狀採樣：拉離方向可能穿過脂雙層，拉離時也沒有膜專用的壓力耦合，PMF 與 ΔG° 不可信"
                   "（docs/specs/membrane.md §6，沿膜法線的 PMF 尚未實作）。")
            self._block("binding", msg, gates=[{"name": "membrane binding", "status": "NEEDS_HUMAN", "explanation": msg,
                                                "options": ["binding.enabled: false（只做 MD）"]}])
        # keep every finished target even when the step itself was paused or reopened (manual resampling of one
        # target must not recompute the others)
        results = {k: v for k, v in ((self.state()["steps"].get("binding") or {}).get("results") or {}).items()
                   if v.get("status") == "PASS"}
        cfg = self._binding_config(b)
        targets, contexts = self._binding_targets(runs, built)
        per_target = b.get("target_replicas") or {}            # D-87: more SMD/umbrella runs for one target
        for t in targets:
            name, key = t["key"], t["run_key"]
            want = max(1, int(per_target.get(name) or b.get("replicas", 1)))
            if results.get(name, {}).get("status") == "PASS" and int(results[name].get("replicas") or 1) >= want:
                continue
            case = self.project.case(runs[key]["case_id"])
            bm = load_json(case.build_dir / "build_manifest.json", {})
            lmap = built.get(key, {}).get("ligand_map") or {}
            mname = lmap.get(t["ligand"], "L01")
            recs = {l.get("name"): l for l in manifest_ligands(bm)}
            lrec = recs.get(mname)
            if lrec is None or not lrec.get("heavy_atom_indices"):
                self._block("binding", f"{name}：建模紀錄中找不到配體 {mname} 的原子索引，無法定義拉離座標。")
            lm = [x for x in ((bm.get("restraints") or {}).get("ligand_metal") or []) if x.get("ligand_resname") == mname]
            if lm:
                # D-53: the coordination is held by a distance restraint, not by chemistry — pulling the ligand out would
                # measure the restraint, so no free energy is computed for this ligand
                why = (f"{name}：配體以距離約束維持與 {lm[0]['metal']} 的配位（ligand_metal: restrain）；拉離會量到約束而不是結合，"
                       "此配體不計算結合自由能。要計算，請以 MCPB.py 或 QM 參數化配體–金屬鍵（metal_params）。")
                results[name] = {"status": "SKIPPED", "ligand": t["ligand"], "caveats": [why]}
                self.dec.record("workflow.binding", name, "skipped", why)
                continue
            others = {}
            for o in t["others"]:
                orec = recs.get(lmap.get(o, ""))
                if not orec or not orec.get("heavy_atom_indices"):
                    self._block("binding", f"{name}：共同口袋中的配體 {o} 沒有原子索引，無法檢查拉離路徑。")
                others[o] = orec["heavy_atom_indices"]
            n_rep = want
            md_runs = runs[key]["run_ids"]
            reps, paused, rep_src = [], False, []
            for i in range(n_rep):
                # replica i starts from MD replica i; when there are more binding replicas than MD replicas the MD end
                # point is reused (cycled) — those pulls share a starting configuration and are NOT independent
                # equilibrium starts (A9, D-96): the provenance below keeps them apart
                md_id = md_runs[i % len(md_runs)]
                rdir = case.dir / "runs" / md_id
                rep_src.append({"replica": i, "md_run_id": md_id, "seed": cfg.seed + 1000 * i,
                                "start_state": str(rdir / "stages" / "production" / "production_state.xml"),
                                "shares_start_with_earlier": md_id in [r["md_run_id"] for r in rep_src]})
                rcfg = BindingConfig(**{**cfg.to_dict(), "seed": cfg.seed + 1000 * i,
                                        "extra_windows": list((b.get("manual_windows") or {}).get(name, []))})
                odir = binding_replica_dir(self.dir / "binding" / name.replace(":", "_"), i, n_rep)
                if i == 0:
                    anchor_idx = self._anchor_override(name, bm)
                res = run_binding(bm["system_xml"], bm["topology_pdb"], rdir / "stages" / "production" / "production_state.xml",
                                  odir,
                                  ligand_indices=lrec["heavy_atom_indices"], ligand_resname=mname, config=rcfg, platform_name=platform.name,
                                  platform_properties=platform.properties, decisions=self.dec, should_pause=should_pause,
                                  progress_cb=progress_cb, other_ligand_indices=others or None, anchor_indices=anchor_idx)
                if res.status == "NEEDS_HUMAN":
                    results[name] = {"status": "NEEDS_HUMAN", "ligand": t["ligand"], "caveats": res.caveats}
                    msg = f"{name} 結合自由能（replica {i + 1}）：{res.caveats[0] if res.caveats else ''}"
                    path = "拉離路徑" in msg
                    opts = [f"略過 {name}，先算其他配體（binding.skip_targets）"]
                    if path and name.startswith("multi:"):
                        opts.append(f"只算 {t['ligand']} 單獨結合（binding.alone）")
                    if path:
                        opts.append(f"指定 anchor 殘基，改變拉離方向（binding.anchor_residues）")
                    opts.append("binding.enabled: false（只做 MD）")
                    if path and name.startswith("multi:"):
                        msg += ("（沒有「先拉外側配體」：每個目標都從同一段 MD 的終點各自拉離，其他配體一直留在口袋裡；先拉外側"
                                "配體不會讓它從這個配體的路上消失。要讓路徑空出來，請選「只算單獨結合」。）")
                    gate = {"name": "binding path" if path else "binding target", "status": "NEEDS_HUMAN",
                            "explanation": msg, "evidence": {"target": name, "ligand": t["ligand"]}, "options": opts}
                    self._block("binding", msg, results=results, gates=[gate])
                if res.status == "PAUSED":
                    paused = True
                    break
                reps.append(res)
            if paused:
                results[name] = {"status": "PAUSED", "ligand": t["ligand"], "replicas_done": len(reps)}
                st = self.state(); st["steps"]["binding"] = {"status": "PAUSED", "results": results}; atomic_write_json(st, self.state_path)
                return results
            rep_src = rep_src[:len(reps)]
            agg = aggregate_binding_replicas(reps, sources=rep_src)
            res = reps[0]
            dG, dGk, withheld = agg["dG"], agg["dG_kcal"], agg["dG_withheld"]
            reason = self._tier_withholds_dG(cfg, SimpleNamespace(pmf={"half_split": agg["half_split"]}),
                                             n_done=agg["n_independent_md_starts"])
            if reason and dG is not None:
                dG, dGk, withheld = None, None, reason
                self.dec.record("binding.result", name, "ΔG° withheld", reason)
            if len(reps) > 1:
                self.dec.record("binding.replicas", name, f"{len(reps)} replicas", agg["why"])
            results[name] = {"status": "PASS", "ligand": t["ligand"], "context": "single" if not t["others"] else f"multi:{key}",
                             "finished_at": now_iso(),
                             "co_ligands": t["others"], "replicas": len(reps), "delta_pmf_kj_mol": agg["delta_pmf"],
                             "delta_pmf_err_kj_mol": agg["delta_pmf_err"],
                             "dG_standard_kj_mol": dG, "dG_err_kj_mol": agg["dG_err"] if dG is not None else None,
                             "dG_standard_kcal_mol": dGk, "dG_withheld": withheld,
                             "per_replica": agg["per_replica"], "half_split": agg["half_split"],
                             "r_min_nm": res.pmf.get("r_min_nm"), "figures": res.figures, "caveats": res.caveats,
                             "max_force": res.smd.get("max_force_kj_mol_nm"), "work": res.smd.get("final_work_kj_mol"),
                             # D-96: execution PASS above; what the evidence supports is in `assessment`
                             "assessment": self._binding_assessment(reps, dG, withheld),
                             "condition": getattr(res, "condition", None) or {},
                             "replica_sources": rep_src, "n_independent_md_starts": agg["n_independent_md_starts"],
                             "n_pulls_sharing_start": agg["n_pulls_sharing_start"],
                             "replicas_why_i18n": agg.get("why_i18n")}
        comparison = compare_binding(results, contexts={k: v for k, v in contexts.items() if v})
        for c in comparison["contexts"].values():
            if c.get("why"):
                self.dec.record("binding.compare", "ΔΔ", c.get("reference"), c["why"])
        for c in comparison["co_occupancy"]:
            self.dec.record("binding.compare", f"co-occupancy {c['ligand']}", c["shift_kj_mol"], c["why"])
        from .sampling.multi import cooperativity
        comparison["cooperativity"] = cooperativity(results, {k: v for k, v in contexts.items() if v})   # D-61
        for c in comparison["cooperativity"]:
            self.dec.record("binding.cooperativity", c["context"], c["status"], c["why"][0])
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

    def confirm_md(self, sel: dict) -> None:
        """GUI flow (D-50): after the poses are fixed, stop and ask whether to go on to molecular dynamics.
        Only when the config asks for it (`confirm_before_md`); the CLI default runs straight through."""
        if not self.cfg.get("confirm_before_md") or self.cfg.get("md_confirmed"):
            if self.cfg.get("md_confirmed"):
                self._mark("md_confirm", confirmed=True)
            return
        lig = ", ".join(f"{k} (rank {v.get('rank')}, {v.get('score')} kcal/mol)" if v.get("score") is not None
                        else f"{k}（預測複合物，沒有對接分數）" for k, v in (sel.get("ligands") or {}).items())
        msg = (f"對接與姿勢選擇已完成：{lig or '—'}。請在姿勢表確認選用的姿勢，再決定是否進入分子動力學"
               "（建模、平衡、正式模擬；依設定可能需要數小時）。")
        self._block("md_confirm", msg, gates=[{
            "name": "confirm MD", "status": "NEEDS_HUMAN", "explanation": msg,
            "options": ["進入分子動力學（md_confirmed）", "先改選姿勢（在姿勢表點選後再回來確認）"]}])

    def _run(self, make_factory: Callable, platform, *, should_pause=None, progress_cb=None) -> dict:
        if (self.cfg.get("md") or {}).get("resolution") == "cg":
            return self._run_cg(platform, should_pause=should_pause, progress_cb=progress_cb)
        if self.membrane_only_type():
            return self._run_membrane_only(make_factory, platform, should_pause=should_pause, progress_cb=progress_cb)
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
            self.confirm_md(sel)
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

    def _run_membrane_only(self, make_factory: Callable, platform, *, should_pause=None, progress_cb=None) -> dict:
        """Cases B and C: build → MD → analysis → report, the same steps without receptor and docking.
        Binding stays blocked for membrane systems (gate `membrane binding`)."""
        built = self.build_membrane_cases()
        runs = self.run_md(built, make_factory, should_pause=should_pause, progress_cb=progress_cb)
        if any(r["status"] == "PAUSED" for r in runs.values()):
            return {"status": "PAUSED", "state": self.state()}
        ana = self.analyse(runs)
        bind = self.binding(runs, built, platform, should_pause=should_pause, progress_cb=progress_cb)
        from .report.workflow_report import build_workflow_report
        rep = build_workflow_report(self)
        self._mark("report", path=str(rep))
        return {"status": "COMPLETE", "report": str(rep), "binding": bind, "analysis": ana}


    # ------------------------------------------------------------------ coarse-grained Martini 3 (D-86)
    def cg_kind(self) -> str:
        m = (self.cfg.get("md") or {}).get("membrane") or {}
        return {"protein": "protein", "surface": "surface", "bilayer": "bilayer"}.get(m.get("type"), "water")

    def _cg_block(self, step: str, exc) -> None:
        g = {"name": f"cg {exc.code}", "status": "NEEDS_HUMAN", "explanation": exc.text[0], "text": list(exc.text),
             "options": exc.options, "evidence": exc.evidence}
        self._block(step, f"粗粒化：{exc.text[0]}", gates=[g])

    def _cg_lipids(self) -> dict:
        from .build.membrane import resolve_composition
        m = (self.cfg.get("md") or {}).get("membrane") or {}
        comp, gates = resolve_composition(m.get("lipids") or "mammalian")
        bad = [g for g in gates if g.status == "NEEDS_HUMAN"]
        if bad:
            self._block("md_cases", "粗粒化膜組成：" + bad[0].explanation, gates=[g.to_dict() for g in bad])
        up, lo = comp.get("upper") or {}, comp.get("lower") or {}
        if up != lo:
            msg = "粗粒化目前只建對稱的脂雙層（上下層相同組成）。"
            self._block("md_cases", msg, gates=[{"name": "cg asymmetric", "status": "NEEDS_HUMAN", "explanation": msg,
                                                 "options": ["md.membrane.lipids: {POPC: 1}", "改用全原子模擬（md.resolution: aa）"]}])
        return {k: max(1, round(float(v) * 100)) for k, v in up.items() if float(v) > 0}

    def build_cg_cases(self) -> dict:
        """One CG system per solute (surface), or one system (protein, bilayer, water).  Kept in
        state["coarse_grained"][key]["build"]; a finished build is reused when its inputs did not change."""
        from .build.cg_system import build_cg_system, CGBuildError
        kind = self.cg_kind()
        md = self.cfg.get("md") or {}
        mem = md.get("membrane") or {}
        st = self.state()
        cgs = st.get("coarse_grained") or {}
        jobs: list[tuple[str, dict]] = []
        if kind in ("protein", "water"):
            if not self.cfg.get("receptor"):
                self._block("md_cases", "粗粒化的膜蛋白或水中蛋白需要受體結構。", gates=[{
                    "name": "cg no_solute", "status": "NEEDS_HUMAN", "explanation": "粗粒化的膜蛋白或水中蛋白需要受體結構。",
                    "options": ["md.membrane.type: bilayer", "輸入 PDB 編號或上傳結構"]}])
            if self.cfg.get("ligands"):
                self.dec.record("workflow.cg", "ligands", "not simulated",
                                "粗粒化只模擬蛋白與膜；配體沒有通用的 Martini 3 參數，不放進系統，也不做對接（報告會說明）。", kind="auto")
            raw = self.fetch_receptor()
            clean = self.prepare_docking_receptor(raw)
            jobs.append(("cg_" + kind, {"protein_pdb": str(clean)}))
        elif kind == "surface":
            ligs = self.cfg.get("ligands") or []
            small = [l["name"] for l in ligs if not l.get("sequence")]
            if small or not ligs:
                msg = (f"粗粒化的膜表面接觸只支援胜肽；{', '.join(small)} 是小分子，Martini 3 沒有通用參數。" if small else
                       "膜表面接觸要有一個胜肽。")
                self._block("md_cases", msg, gates=[{"name": "cg small molecule", "status": "NEEDS_HUMAN", "explanation": msg,
                                                     "options": ["改用全原子模擬（md.resolution: aa）", "移除小分子配體"]}])
            bdir = self.dir / "cg" / "solutes"
            for i, l in enumerate(ligs):
                rec = self._membrane_solute(l, bdir, i)
                jobs.append((f"cg_surface_{l['name']}", {"protein_pdb": rec.pdb_path}))
        else:
            jobs.append(("cg_bilayer", {}))
        lipids = self._cg_lipids() if kind != "water" else None
        built = {}
        for key, j in jobs:
            req = {"kind": kind, "lipids": lipids, "salt": float((md.get("ions") or {}).get("concentration_molar", 0.15)),
                   "surface_distance_nm": float(mem.get("surface_distance_nm", 1.0)), "oriented": bool(mem.get("oriented")),
                   **j}
            old = (cgs.get(key) or {})
            if old.get("request") == req and old.get("build") and Path(old["build"].get("system_xml", "")).is_file():
                built[key] = old["build"]
                continue
            try:
                man = build_cg_system(self.dir / "cg" / key, kind=kind, protein_pdb=j.get("protein_pdb"), lipids=lipids,
                                      salt_molar=req["salt"], surface_distance_nm=req["surface_distance_nm"],
                                      oriented=req["oriented"], decisions=self.dec)
            except CGBuildError as exc:
                self._cg_block("md_cases", exc)
            st = self.state()
            st.setdefault("coarse_grained", {})[key] = {"request": req, "build": man, "plan": man.get("plan"),
                                                        "settings": man.get("settings")}
            atomic_write_json(st, self.state_path)
            built[key] = man
        self._mark("md_cases", cg=sorted(built))
        return built

    def _run_cg(self, platform, *, should_pause=None, progress_cb=None) -> dict:
        """D-86: build → CG MD → analysis → report.  No docking and no binding free energy (bead level)."""
        from .engine.cg_run import run_cg
        from .analysis.cg import analyse_cg
        built = self.build_cg_cases()
        md = self.cfg.get("md") or {}
        prod = float(md.get("production_ns") or 200.0)
        pname = getattr(platform, "name", None) or str(platform or "CPU")
        props = dict(getattr(platform, "properties", None) or {})
        runs = dict((self._done("md_runs") or {}).get("runs", {}))
        for key, man in built.items():
            if (runs.get(key) or {}).get("status") == "COMPLETE" and runs[key].get("production_ns") == prod:
                continue
            if pname == "FAKE":
                r = {"status": "COMPLETE", "run_dir": str(self.dir / "cg" / key / "run")}
            else:
                temp = 310.0
                if md.get("membrane"):
                    from .build.membrane import membrane_temperature
                    temp = membrane_temperature(md["membrane"])
                r = run_cg(man, self.dir / "cg" / key / "run", platform_name=pname, properties=props, temperature_k=temp,
                           production_ns=prod, save_ps=max(20.0, prod * 1000 / 5000), chunk_ns=min(50.0, max(1.0, prod / 20)),
                           should_pause=should_pause, progress_cb=progress_cb)
            runs[key] = {"status": r["status"], "run_dir": r["run_dir"], "production_ns": prod, "cg": True}
            self._mark("md_runs", runs=runs)
            if r["status"] == "FAILED":
                msg = f"{key}：{r.get('reason')}"
                self._block("md_runs", msg, runs=runs, gates=[{"name": "cg minimise", "status": "NEEDS_HUMAN",
                            "explanation": msg, "options": ["刪除 cg 資料夾後重跑（重新建模）", "改用全原子模擬（md.resolution: aa）"]}])
            if r["status"] == "PAUSED":
                return {"status": "PAUSED", "state": self.state()}
        if self.cfg.get("binding", {}).get("enabled"):
            self.dec.record("workflow.cg", "binding", "not computed",
                            "粗粒化模擬只到珠子層級，不計算結合自由能（傘狀採樣與 MBAR 要全原子系統）。", kind="auto")
        st = self.state()
        summ = {}
        for key, man in built.items():
            rd = Path(runs[key]["run_dir"])
            if not (rd / "production.dcd").is_file():
                continue
            try:
                out = analyse_cg(man, rd, decisions=self.dec)
            except Exception as exc:  # noqa: BLE001 — the report still states what was run
                self.dec.record("analysis.cg", key, "failed", f"粗粒化分析失敗：{type(exc).__name__}: {exc}。", kind="auto")
                continue
            st = self.state()
            st.setdefault("coarse_grained", {}).setdefault(key, {})["membrane_file"] = out["file"]
            atomic_write_json(st, self.state_path)
            summ[key] = {"cg_analysis_file": out["file"]}
        self._mark("analysis", cg=summ)
        from .report.workflow_report import build_workflow_report
        rep = build_workflow_report(self)
        self._mark("report", path=str(rep))
        return {"status": "COMPLETE", "report": str(rep), "analysis": summ}


def binding_replica_dir(base: Path, i: int, n_rep: int) -> Path:
    """Output folder of SMD/umbrella replica i (0-based) of one target.  One replica: the target folder itself (as
    before D-87).  When a target that ran once gets more runs, its first run stays where it is (no recomputation)
    and the new ones go to rep2, rep3 …; a target planned with several runs uses rep1, rep2 …"""
    legacy = (base / "binding_manifest.json").is_file()
    if i == 0 and (n_rep == 1 or legacy):
        return base
    return base / f"rep{i + 1}"


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
