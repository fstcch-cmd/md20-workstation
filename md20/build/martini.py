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
# D-86: the four Martini 3.0.0 files come from martini_openmm's own protein-in-POPC test system (tests/1j4n_en_m3/openmm)
# at the commit pip installs, checked by SHA-256.  Using the files its tests compare against GROMACS keeps the force
# field and the OpenMM implementation from the same, tested source.  (The tutorial's copy of martini_v3.0.0.itp differs
# only by a trailing blank line.)
FF_SOURCE = {
    "zip": "https://github.com/maccallumlab/martini_openmm/archive/216e62b26c4ee6cea7ed21e20ec84fffe97a101c.zip",
    "member_dir": "martini_openmm-216e62b26c4ee6cea7ed21e20ec84fffe97a101c/tests/1j4n_en_m3/openmm/",
    "sha256": {
        "martini_v3.0.0.itp": "0ecbf0ff334b2ec21dc5e3151aca42167b977bc2aed41eb2a44bd8c997754894",
        "martini_v3.0.0_phospholipids_v1.itp": "21fb2eb6d8a1d48854d179dc71981c1210f608486efb3e6644347391ba9cf392",
        "martini_v3.0.0_solvents_v1.itp": "e6a78414b317c38a1a816eded4aee6082a5da1ed229a126359f0cc92314dcb4e",
        "martini_v3.0.0_ions_v1.itp": "c7ec26bcd272f0e127d67515097e8cc88979e7e0cf5373baa0f410edeb125e68",
    },
}


def default_ff_dir() -> Path:
    """Where `md20 setup-cg` puts the Martini 3 files: inside MD20's own environment (removed with it)."""
    return Path(sys.prefix) / "share" / "md20" / "martini3"


def install_forcefield(dest: Path | None = None, *, fetch=None) -> dict:
    """Download the pinned martini_openmm archive and extract the four Martini 3 itp files, each checked by SHA-256.
    `fetch(url) -> bytes` can be injected for tests.  Raises ValueError on a checksum mismatch (nothing is kept)."""
    import hashlib
    import io
    import zipfile
    dest = Path(dest) if dest else default_ff_dir()
    if fetch is None:
        import urllib.request

        def fetch(url):
            with urllib.request.urlopen(url, timeout=300) as r:      # noqa: S310 — fixed https URL
                return r.read()
    data = fetch(FF_SOURCE["zip"])
    out = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name, want in FF_SOURCE["sha256"].items():
            blob = z.read(FF_SOURCE["member_dir"] + name)
            got = hashlib.sha256(blob).hexdigest()
            if got != want:
                raise ValueError(f"{name} 的 SHA-256 不符（{got}），沒有安裝。")
            out[name] = blob
    dest.mkdir(parents=True, exist_ok=True)
    for name, blob in out.items():
        (dest / name).write_bytes(blob)
    return {"dir": str(dest), "files": sorted(out), "source": FF_SOURCE["zip"]}


def forcefield_ready(ff_dir: Path | None = None) -> bool:
    d = Path(ff_dir) if ff_dir else default_ff_dir()
    return all((d / f).is_file() for f in FF_SOURCE["sha256"])


def itp_molecule_names(path: Path | str) -> set[str]:
    """Names of every [ moleculetype ] in an itp file (to check that the chosen lipids exist in Martini 3)."""
    names, take = set(), False
    for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        if line.startswith("["):
            take = line.strip("[] ").replace(" ", "").lower() == "moleculetype"
            continue
        if take:
            names.add(line.split()[0])
            take = False
    return names


def dssp_string(pdb: Path | str) -> str:
    """Secondary structure per residue for martinize2 -ss, computed with mdtraj (DSSP codes; coil for blanks).
    Passing -ss avoids depending on which vermouth version has the mdtraj fallback behind -dssp."""
    import mdtraj
    t = mdtraj.load_pdb(str(pdb))
    prot = t.topology.select("protein")
    t = t.atom_slice(prot)
    codes = mdtraj.compute_dssp(t, simplified=False)[0]
    return "".join("C" if c in (" ", "NA", "") else str(c) for c in codes)

# simulation constants of the martini_openmm tutorial (tutorial/run.py) and Martini 3 practice
CG_TIMESTEP_FS = 20.0
CG_EPSILON_R = 15.0
CG_CUTOFF_NM = 1.1
CG_FRICTION_PER_PS = 10.0
# martinize2 elastic network for Martini 3 proteins (common Martini 3 tutorial values)
ELASTIC = {"-ef": "700", "-el": "0.5", "-eu": "0.9"}


# Python entry points used when the console script cannot be found (laptop 11/03: `martinize2` was not on PATH after
# `md20 setup-cg` although vermouth installed).  Running the module with the env's own python avoids PATH entirely.
ENTRY = {"martinize2": ("vermouth.bin.martinize2", "entry"), "insane": ("insane.cli", "cli")}


def _script_dirs() -> list[Path]:
    """Where pip puts console scripts for the running interpreter (Windows: <env>/Scripts, otherwise <env>/bin)."""
    base = Path(sys.executable).parent
    return [base / "Scripts", base, base / "bin"]


def tool_argv(exe: str, *, find_spec=importlib.util.find_spec, which=shutil.which,
              script_dirs: list[Path] | None = None) -> list[str] | None:
    """Command prefix that runs `exe`: on PATH, else in the env's script folder, else the module entry point with this
    python.  None when none of them exists."""
    hit = which(exe)
    if hit:
        return [hit]
    for d in (_script_dirs() if script_dirs is None else script_dirs):
        for name in (exe + ".exe", exe + "-script.py", exe):
            f = d / name
            if f.is_file():
                return [str(f)] if name.endswith(".exe") else [sys.executable, str(f)]
    mod, fn = ENTRY.get(exe, (None, None))
    if mod:
        try:
            ok = find_spec(mod) is not None
        except (ImportError, ValueError):
            ok = False
        if ok:
            return [sys.executable, "-c", f"import sys; from {mod} import {fn}; sys.argv[0] = {exe!r}; sys.exit({fn}())"]
    return None


def availability(*, find_spec=importlib.util.find_spec, which=shutil.which, script_dirs: list[Path] | None = None) -> dict:
    """{tool: {"module": bool, "executable": bool | None, "argv": list | None, "ok": bool}}; injectable lookups."""
    out = {}
    for name, t in TOOLS.items():
        try:
            mod = find_spec(t["module"]) is not None
        except (ImportError, ValueError):
            mod = False
        argv = None if t["executable"] is None else tool_argv(t["executable"], find_spec=find_spec, which=which,
                                                               script_dirs=[] if script_dirs is None and which is not shutil.which else script_dirs)
        exe = None if t["executable"] is None else argv is not None
        out[name] = {"module": mod, "executable": exe, "argv": argv, "ok": mod and (exe is not False)}
    return out


def why_missing(avail: dict) -> list[str]:
    """One line per missing tool saying whether the Python package or its command is what is missing."""
    out = []
    for k, v in avail.items():
        if v["ok"]:
            continue
        if not v["module"]:
            out.append(f"{k}：Python 套件無法匯入（pip 安裝可能失敗，請看上面的錯誤）")
        else:
            out.append(f"{k}：套件已安裝，但找不到指令 {TOOLS[k]['executable']}")
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


def plan_cg_membrane(protein_pdb: str | Path | None, workdir: str | Path, *, lipids: dict | None = None,
                     box_nm: tuple = (10.0, 10.0, 10.0), salt_molar: float = 0.15, forcefield_dir: str | Path | None = None,
                     elastic: bool = True, avail: dict | None = None, membrane: bool = True, memshift_nm: float = 0.0,
                     ss: str | None = None, insane_ff: bool = True) -> CGPlan:
    """Command plan.  `protein_pdb` None → no protein (bilayer or water only); `membrane` False → protein in water;
    `memshift_nm` > 0 puts the protein that far above the membrane centre (surface contact, insane -dm);
    `ss` (one DSSP letter per residue) → martinize2 -ss instead of -dssp; `lipids` {name: relative amount}
    (default POPC); `forcefield_dir` holds the Martini 3 itp files (default: where setup-cg puts them).
    Nothing is executed."""
    lipids = (lipids or {"POPC": 1}) if membrane else {}
    wd = Path(workdir)
    avail = availability() if avail is None else avail
    missing = missing_tools(avail)
    if protein_pdb is None:
        missing = [m for m in missing if m != "vermouth"]
    ff_dir = Path(forcefield_dir) if forcefield_dir else default_ff_dir()
    need_ff = [FF_FILES["core"]] + ([FF_FILES["phospholipids"]] if lipids else []) + [FF_FILES["solvents"]] + \
              ([FF_FILES["ions"]] if salt_molar > 0 else [])
    missing_ff = [f for f in need_ff if not (ff_dir / f).is_file()]
    m2_cmd = (avail.get("vermouth") or {}).get("argv") or ["martinize2"]
    ins_cmd = (avail.get("insane") or {}).get("argv") or ["insane"]
    steps = []
    if protein_pdb is not None:
        m2 = [*m2_cmd, "-f", str(protein_pdb), "-x", str(wd / "protein_cg.pdb"), "-o", str(wd / "protein.top"),
              "-ff", "martini3001", "-ignh"] + (["-ss", ss] if ss else ["-dssp"])
        if elastic:
            m2 += ["-elastic"] + [x for kv in ELASTIC.items() for x in kv]
        steps.append({"name": "martinize2", "kind": "exec", "argv": m2,
                      "outputs": ["protein_cg.pdb", "protein.top", "molecule_*.itp"]})
    x, y, z = (f"{float(v):g}" for v in box_nm)
    ins = [*ins_cmd] + (["-f", str(wd / "protein_cg.pdb")] if protein_pdb is not None else []) + \
          ["-o", str(wd / "system.gro"), "-p", str(wd / "insane.top"), "-pbc", "rectangular", "-x", x, "-y", y, "-z", z,
           "-sol", "W"]
    if insane_ff:
        ins += ["-ff", "M3"]
    if protein_pdb is not None:
        ins += ["-center"]
        if memshift_nm:
            ins += ["-dm", f"{float(memshift_nm):g}"]
    for name, amount in lipids.items():
        ins += ["-l", f"{name}:{amount:g}" if isinstance(amount, (int, float)) else f"{name}:{amount}"]
    if salt_molar > 0:
        ins += ["-salt", f"{float(salt_molar):g}"]
    steps += [
        {"name": "insane", "kind": "exec", "argv": ins, "outputs": ["system.gro", "insane.top"]},
        {"name": "compose_topology", "kind": "python", "call": "md20.build.martini.compose_topology",
         "inputs": ["insane.top"] + (["molecule_*.itp"] if protein_pdb is not None else []) + need_ff,
         "outputs": ["system.top"]},
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
                       "text": (f"找不到 Martini 3 力場檔：{names}。執行 md20 setup-cg --yes（或在電腦狀態頁按一鍵安裝）會一併下載。",
                                f"Martini 3 force-field files are missing: {names}. Run md20 setup-cg --yes (or press Install "
                                "now on the computer status page); it downloads them too.",
                                f"Martini 3 の力場ファイルがありません：{names}。md20 setup-cg --yes を実行する（またはパソコンの状態の"
                                "ページで「今すぐインストール」を押す）と一緒にダウンロードされます。",
                                f"Martini 3 역장 파일이 없습니다: {names}. md20 setup-cg --yes를 실행하면(또는 컴퓨터 상태 페이지에서 "
                                "'지금 설치'를 누르면) 함께 내려받습니다."),
                       "options": ["執行 md20 setup-cg --yes（會一併下載力場檔）", f"cg.forcefield_dir: <資料夾>（放 {FF_CORE} 等檔案）", "改用全原子模擬"]})
    if lipids and not missing_ff:
        known = itp_molecule_names(ff_dir / FF_FILES["phospholipids"])
        bad = [k for k in lipids if k not in known]
        if bad:
            names = ", ".join(bad)
            issues.append({"code": "lipid_not_in_martini3", "zh": f"Martini 3 磷脂檔沒有這些脂質：{names}。",
                           "text": (f"Martini 3 磷脂檔沒有這些脂質：{names}。", f"The Martini 3 phospholipid file has no {names}.",
                                    f"Martini 3 のリン脂質ファイルに {names} がありません。", f"Martini 3 인지질 파일에 {names}이(가) 없습니다."),
                           "options": ["md.membrane.lipids: {POPC: 1}", "改用全原子模擬"]})
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
