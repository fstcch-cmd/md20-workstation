"""On-disk project store.

Replaces the Colab design (Google Drive JSON pointers + cross-runtime lease +
heartbeat thread) with a plain directory tree that works on a laptop:

    <projects_dir>/<project>/
        project.json            identity, schema, created_at
        decisions.jsonl         decision log (teaching artefact)
        cases/<case_id>/
            case.json           force-field family lock, sources, status
            inputs/             immutable copies of user inputs (+ sha256)
            build/              receptor_clean.*, ligand_*.sdf, system.xml, topology.pdb, build_manifest.json
            runs/<run_id>/
                run.json        protocol, identity
                stages/<stage>/ chunk_00001.xml ... <stage>_complete.json
                figures/        auto-generated plots

Resume logic is *file-truth based*: the stage of a run is derived from which
completion manifests exist and validate, never from in-memory state.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from ..util import (atomic_write_json, load_json, ensure_dir, safe_name, now_iso,
                    DecisionLog, FileLock, sha256_file, atomic_copy)
from .. import __version__

SCHEMA = "md20/1.0"

# Ordered pipeline stages for a run.  `detect_stage` returns the last one whose
# completion manifest exists and is marked PASS.
STAGES = ["BUILT", "MINIMIZED", "NVT", "NPT", "PRODUCTION", "ANALYZED"]
_STAGE_FILES = {
    "BUILT": ("build", "build_manifest.json"),
    "MINIMIZED": ("stages/minimize", "minimize_complete.json"),
    "NVT": ("stages/nvt", "nvt_complete.json"),
    "NPT": ("stages/npt", "npt_complete.json"),
    "PRODUCTION": ("stages/production", "production_complete.json"),
    "ANALYZED": ("analysis", "analysis_manifest.json"),
}


@dataclass
class Run:
    case: "Case"
    run_id: str

    @property
    def dir(self) -> Path:
        return self.case.dir / "runs" / self.run_id

    @property
    def manifest_path(self) -> Path:
        return self.dir / "run.json"

    def manifest(self) -> dict:
        return load_json(self.manifest_path, {})

    def save_manifest(self, data: dict) -> None:
        data = {**data, "schema": SCHEMA, "run_id": self.run_id, "case_id": self.case.case_id,
                "project_uuid": self.case.project.uuid, "updated_at": now_iso()}
        atomic_write_json(data, self.manifest_path)

    def stage_dir(self, stage: str) -> Path:
        return ensure_dir(self.dir / "stages" / stage)

    @property
    def figures_dir(self) -> Path:
        return ensure_dir(self.dir / "figures")

    def stage(self) -> str | None:
        return detect_stage(self)


@dataclass
class Case:
    project: "Project"
    case_id: str

    @property
    def dir(self) -> Path:
        return self.project.dir / "cases" / self.case_id

    @property
    def manifest_path(self) -> Path:
        return self.dir / "case.json"

    def manifest(self) -> dict:
        return load_json(self.manifest_path, {})

    def save_manifest(self, data: dict) -> None:
        data = {**data, "schema": SCHEMA, "case_id": self.case_id,
                "project_uuid": self.project.uuid, "updated_at": now_iso()}
        atomic_write_json(data, self.manifest_path)

    @property
    def inputs_dir(self) -> Path:
        return ensure_dir(self.dir / "inputs")

    @property
    def build_dir(self) -> Path:
        return ensure_dir(self.dir / "build")

    def import_input(self, src: Path | str, role: str) -> dict:
        """Copy a user file into inputs/ immutably and record its hash."""
        src = Path(src)
        if not src.is_file():
            raise FileNotFoundError(src)
        dst = self.inputs_dir / f"{safe_name(role)}{src.suffix.lower()}"
        atomic_copy(src, dst)
        record = {"role": role, "original": str(src), "path": str(dst), "sha256": sha256_file(dst),
                  "imported_at": now_iso()}
        m = self.manifest()
        m.setdefault("inputs", {})[role] = record
        self.save_manifest(m)
        return record

    def runs(self) -> Iterator[Run]:
        root = self.dir / "runs"
        if root.is_dir():
            for d in sorted(root.iterdir()):
                if (d / "run.json").is_file():
                    yield Run(self, d.name)

    def new_run(self, protocol: dict, reason: str = "new") -> Run:
        run_id = f"run_{now_iso().replace(':', '').replace('-', '')}_{uuid.uuid4().hex[:6]}"
        run = Run(self, run_id)
        ensure_dir(run.dir)
        run.save_manifest({"protocol": protocol, "reason": reason, "created_at": now_iso(),
                           "md20_version": __version__, "status": "CREATED"})
        m = self.manifest()
        m["active_run"] = run_id
        self.save_manifest(m)
        return run

    def active_run(self) -> Run | None:
        rid = self.manifest().get("active_run")
        if rid and (self.dir / "runs" / rid / "run.json").is_file():
            return Run(self, rid)
        return None


class Project:
    def __init__(self, path: Path | str):
        self.dir = Path(path)
        self.manifest_path = self.dir / "project.json"
        if not self.manifest_path.is_file():
            raise FileNotFoundError(f"不是 MD20 專案（缺少 project.json）：{self.dir}")
        self._manifest = load_json(self.manifest_path, {}, critical=True)
        self.decisions = DecisionLog(self.dir / "decisions.jsonl")

    # ---- creation / discovery -------------------------------------------------
    @classmethod
    def create(cls, projects_dir: Path | str, name: str) -> "Project":
        root = ensure_dir(projects_dir)
        pdir = root / safe_name(name, "project")
        if pdir.exists():
            raise FileExistsError(f"專案已存在：{pdir}")
        ensure_dir(pdir)
        atomic_write_json({"schema": SCHEMA, "name": name, "project_uuid": str(uuid.uuid4()),
                           "created_at": now_iso(), "md20_version": __version__}, pdir / "project.json")
        ensure_dir(pdir / "cases")
        return cls(pdir)

    @classmethod
    def discover(cls, projects_dir: Path | str) -> list["Project"]:
        root = Path(projects_dir)
        if not root.is_dir():
            return []
        out = []
        for d in sorted(root.iterdir()):
            if (d / "project.json").is_file():
                try:
                    out.append(cls(d))
                except Exception:  # noqa: BLE001 - skip corrupt projects, never crash discovery
                    continue
        return out

    # ---- properties -----------------------------------------------------------
    @property
    def uuid(self) -> str:
        return str(self._manifest.get("project_uuid", ""))

    @property
    def name(self) -> str:
        return str(self._manifest.get("name", self.dir.name))

    def lock(self, timeout: float = 30.0) -> FileLock:
        return FileLock(self.dir / ".md20.lock", timeout=timeout)

    # ---- cases ----------------------------------------------------------------
    def cases(self) -> Iterator[Case]:
        root = self.dir / "cases"
        if root.is_dir():
            for d in sorted(root.iterdir()):
                if (d / "case.json").is_file():
                    yield Case(self, d.name)

    def case(self, case_id: str) -> Case:
        c = Case(self, case_id)
        if not c.manifest_path.is_file():
            raise FileNotFoundError(f"找不到 case：{case_id}")
        return c

    def new_case(self, name: str, *, forcefield_family: str = "amber") -> Case:
        case_id = f"{safe_name(name, 'case')}_{uuid.uuid4().hex[:6]}"
        c = Case(self, case_id)
        ensure_dir(c.dir)
        c.save_manifest({"name": name, "forcefield_family": forcefield_family, "status": "CREATED",
                         "created_at": now_iso()})
        self.decisions.record("project.case", "force-field family", forcefield_family,
                              "case 建立時鎖定力場家族；之後所有配體／蛋白參數必須屬於同一家族，禁止混用。",
                              case_id=case_id)
        return c


def detect_stage(run: Run) -> str | None:
    """Last stage whose completion manifest exists and is marked PASS."""
    last = None
    for stage in STAGES:
        sub, fname = _STAGE_FILES[stage]
        base = run.case.build_dir.parent if stage == "BUILT" else run.dir
        path = base / sub / fname
        data = load_json(path, {})
        if data.get("status") == "PASS":
            last = stage
        else:
            break
    return last
