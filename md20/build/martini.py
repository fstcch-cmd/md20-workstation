"""Coarse-grained Martini 3 path: availability check and command plan (docs/specs/long_timescale.md §3).

Scaffolding only.  The plan is what MD20 would run for a protein in a bilayer:

    1. martinize2 (vermouth)  protein.pdb      → protein_cg.pdb + molecule_*.itp + protein.top
    2. insane                 protein_cg.pdb   → system.gro + insane.top (bilayer, water W, NA/CL)
    3. compose_topology       force-field itps + protein itps + insane [ molecules ] → system.top
    4. martini_openmm         system.gro + system.top → system.xml (MartiniTopFile.create_system, ε_r 15, 1.1 nm)

What is verified here (pure tests): the tool table, the availability logic, the argv of each step and the topology
composition.  Running the tools needs `md20 setup-cg` and the Martini 3 force-field files (martini_v3.0.0*.itp from
cgmartini.nl), which no pip package ships; without them the plan is NEEDS_HUMAN.  Facts about the tools (package
names, licences, entry points, commits) are recorded in the spec; they were read from the tools' source trees.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

# verified from the source trees (2026-11-03): pyproject/setup.py names, console scripts, licence files, HEAD commits.
# GitHub archive zips instead of git+https: a student's Windows laptop usually has no git.
TOOLS = {
    "vermouth": {"module": "vermouth", "executable": "martinize2", "license": "Apache-2.0",
                 "pip": "vermouth", "source": "https://github.com/marrink-lab/vermouth-martinize",
                 "commit": "a9b62eed6eec028c486ab6369a13cdd9c31f4561"},
    "insane": {"module": "insane", "executable": "insane", "license": "GPL-2.0-or-later",
               "pip": "insane",   # PyPI: the GitHub archive has test files whose names are invalid on Windows (laptop 11/03)
               "source": "https://github.com/Tsjerk/Insane", "commit": "e23a501036c683f2652fe07a66ba941195d7b8f6"},
    "martini_openmm": {"module": "martini_openmm", "executable": None,
                       "license": "LGPL-3.0 (LICENSE file; README says GPL v3)",
                       "pip": "https://github.com/maccallumlab/martini_openmm/archive/216e62b26c4ee6cea7ed21e20ec84fffe97a101c.zip",
                       "source": "https://github.com/maccallumlab/martini_openmm",
                       "commit": "216e62b26c4ee6cea7ed21e20ec84fffe97a101c"},
}

# Martini 3.0.0 force-field files a protein-in-POPC system includes (names as in martini_openmm's test systems)
FF_CORE = "martini_v3.0.0.itp"
FF_FILES = {"core": FF_CORE, "phospholipids": "martini_v3.0.0_phospholipids_v1.itp",
            "solvents": "martini_v3.0.0_solvents_v1.itp", "ions": "martini_v3.0.0_ions_v1.itp"}
FF_URL = "https://cgmartini.nl"

# simulation constants of the martini_openmm tutorial (tutorial/run.py) and Martini 3 practice
CG_TIMESTEP_FS = 20.0
CG_EPSILON_R = 15.0
CG_CUTOFF_NM = 1.1
CG_FRICTION_PER_PS = 10.0
# martinize2 elastic network for Martini 3 proteins (common Martini 3 tutorial values)
ELASTIC = {"-ef": "700", "-el": "0.5", "-eu": "0.9"}


def availability(*, find_spec=importlib.util.find_spec, which=shutil.which) -> dict:
    """{tool: {"module": bool, "executable": bool | None, "ok": bool}}; injectable lookups for tests."""
    out = {}
    for name, t in TOOLS.items():
        try:
            mod = find_spec(t["module"]) is not None
        except (ImportError, ValueError):
            mod = False
        exe = None if t["executable"] is None else bool(which(t["executable"]))
        out[name] = {"module": mod, "executable": exe, "ok": mod and (exe is not False)}
    return out


def missing_tools(avail: dict) -> list[str]:
    return [k for k, v in avail.items() if not v["ok"]]


def install_plan(python: str | None = None) -> list[list[str]]:
    """pip commands `md20 setup-cg` runs in the current environment (printed before running)."""
    py = python or sys.executable
    return [[py, "-m", "pip", "install", TOOLS[k]["pip"]] for k in ("vermouth", "insane", "martini_openmm")]


@dataclass
class CGPlan:
    status: str                              # PASS | NEEDS_HUMAN
    workdir: str
    steps: list = field(default_factory=list)          # [{"name", "kind": "exec"|"python", "argv"|"call", "outputs"}]
    missing: list = field(default_factory=list)        # tools not installed
    missing_ff: list = field(default_factory=list)     # force-field files not found
    issues: list = field(default_factory=list)         # [{"code", "zh", "text": (zh,en,ja,ko), "options"}]
    resolution: str = "coarse-grained (Martini 3, about 4 heavy atoms per bead)"

    def to_dict(self) -> dict:
        return asdict(self)


def plan_cg_membrane(protein_pdb: str | Path, workdir: str | Path, *, lipids: dict | None = None,
                     box_nm: tuple = (10.0, 10.0, 10.0), salt_molar: float = 0.15, forcefield_dir: str | Path | None = None,
                     elastic: bool = True, avail: dict | None = None) -> CGPlan:
    """Command plan for protein + bilayer.  `lipids` {name: relative amount} (default POPC); `forcefield_dir` holds the
    Martini 3 itp files.  Nothing is executed."""
    lipids = lipids or {"POPC": 1}
    wd = Path(workdir)
    avail = availability() if avail is None else avail
    missing = missing_tools(avail)
    ff_dir = Path(forcefield_dir) if forcefield_dir else None
    need_ff = [FF_FILES["core"], FF_FILES["phospholipids"], FF_FILES["solvents"]] + \
              ([FF_FILES["ions"]] if salt_molar > 0 else [])
    missing_ff = [f for f in need_ff if ff_dir is None or not (ff_dir / f).is_file()]
    m2 = ["martinize2", "-f", str(protein_pdb), "-x", str(wd / "protein_cg.pdb"), "-o", str(wd / "protein.top"),
          "-ff", "martini3001", "-ignh", "-dssp"]
    if elastic:
        m2 += ["-elastic"] + [x for kv in ELASTIC.items() for x in kv]
    x, y, z = (f"{float(v):g}" for v in box_nm)
    ins = ["insane", "-f", str(wd / "protein_cg.pdb"), "-o", str(wd / "system.gro"), "-p", str(wd / "insane.top"),
           "-pbc", "rectangular", "-x", x, "-y", y, "-z", z, "-center", "-sol", "W"]
    for name, amount in lipids.items():
        ins += ["-l", f"{name}:{amount:g}" if isinstance(amount, (int, float)) else f"{name}:{amount}"]
    if salt_molar > 0:
        ins += ["-salt", f"{float(salt_molar):g}"]
    steps = [
        {"name": "martinize2", "kind": "exec", "argv": m2, "outputs": ["protein_cg.pdb", "protein.top", "molecule_*.itp"]},
        {"name": "insane", "kind": "exec", "argv": ins, "outputs": ["system.gro", "insane.top"]},
        {"name": "compose_topology", "kind": "python", "call": "md20.build.martini.compose_topology",
         "inputs": ["insane.top", "molecule_*.itp", *need_ff], "outputs": ["system.top"]},
        {"name": "martini_openmm", "kind": "python", "call": "md20.build.martini.build_openmm_system",
         "inputs": ["system.gro", "system.top"], "outputs": ["system.xml"],
         "settings": {"epsilon_r": CG_EPSILON_R, "cutoff_nm": CG_CUTOFF_NM, "timestep_fs": CG_TIMESTEP_FS,
                      "friction_per_ps": CG_FRICTION_PER_PS}},
    ]
    issues = []
    if missing:
        names = ", ".join(missing)
        issues.append({"code": "not_installed", "zh": f"粗粒化工具沒有安裝：{names}。",
                       "text": (f"粗粒化工具沒有安裝：{names}。", f"Coarse-grained tools are not installed: {names}.",
                                f"粗視化ツールがインストールされていません：{names}。",
                                f"조립화 도구가 설치되지 않았습니다: {names}."),
                       "options": ["執行 md20 setup-cg 安裝（vermouth、insane、martini_openmm）", "改用全原子模擬"]})
    if missing_ff:
        names = ", ".join(missing_ff)
        issues.append({"code": "forcefield_files", "zh": f"找不到 Martini 3 力場檔：{names}。",
                       "text": (f"找不到 Martini 3 力場檔：{names}。請從 {FF_URL} 下載後放進同一個資料夾。",
                                f"Martini 3 force-field files are missing: {names}. Download them from {FF_URL} and put "
                                "them in one folder.",
                                f"Martini 3 の力場ファイルがありません：{names}。{FF_URL} からダウンロードし、同じフォルダに置いて"
                                "ください。",
                                f"Martini 3 역장 파일이 없습니다: {names}. {FF_URL}에서 내려받아 한 폴더에 넣으십시오."),
                       "options": [f"cg.forcefield_dir: <資料夾>（放 {FF_CORE} 等檔案）", "改用全原子模擬"]})
    return CGPlan(status="NEEDS_HUMAN" if issues else "PASS", workdir=str(wd), steps=steps, missing=missing,
                  missing_ff=missing_ff, issues=issues)


def molecules_section(top_text: str) -> list[tuple[str, int]]:
    """[ molecules ] entries of a GROMACS topology (comments and blank lines skipped)."""
    out, inside = [], False
    for raw in top_text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        if line.startswith("["):
            inside = line.strip("[] ").lower() == "molecules"
            continue
        if inside:
            parts = line.split()
            if len(parts) >= 2:
                out.append((parts[0], int(parts[1])))
    return out


def compose_topology(insane_top: str, protein_top: str, ff_files: list[str], protein_itps: list[str],
                     title: str = "MD20 Martini 3 system") -> str:
    """system.top: force-field includes, the martinize2 protein itps, then insane's molecules with its single
    "Protein" entry replaced by martinize2's protein molecules (in order)."""
    prot = molecules_section(protein_top)
    mols = []
    for name, n in molecules_section(insane_top):
        if name == "Protein":
            mols += prot
        else:
            mols.append((name, n))
    if not any(n == "Protein" for n, _ in molecules_section(insane_top)):
        mols = prot + mols
    lines = [f'#include "{f}"' for f in ff_files] + [f'#include "{p}"' for p in protein_itps]
    lines += ["", "[ system ]", title, "", "[ molecules ]"] + [f"{n:<10} {c:>7}" for n, c in mols]
    return "\n".join(lines) + "\n"


def build_openmm_system(gro: str | Path, top: str | Path, out_xml: str | Path, *, include_dir: str | Path | None = None,
                        epsilon_r: float = CG_EPSILON_R, cutoff_nm: float = CG_CUTOFF_NM) -> dict:
    """martini_openmm: GROMACS Martini topology → serialized OpenMM System (needs openmm and martini_openmm)."""
    import martini_openmm as martini
    from openmm import XmlSerializer, unit
    from openmm.app import GromacsGroFile
    conf = GromacsGroFile(str(gro))
    topf = martini.MartiniTopFile(str(top), periodicBoxVectors=conf.getPeriodicBoxVectors(), epsilon_r=epsilon_r,
                                  includeDir=str(include_dir) if include_dir else None)
    system = topf.create_system(nonbonded_cutoff=cutoff_nm * unit.nanometer)
    Path(out_xml).write_text(XmlSerializer.serialize(system), encoding="utf-8")
    return {"system_xml": str(out_xml), "n_particles": system.getNumParticles(), "epsilon_r": epsilon_r,
            "cutoff_nm": cutoff_nm}
