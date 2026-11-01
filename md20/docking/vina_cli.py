"""AutoDock Vina command-line fallback (Windows: the pip `vina` package has no wheel and needs Boost to build).

Executable search order: $MD20_VINA_EXE → <app data>/bin/vina[.exe] → `vina` on PATH.
`ensure_vina_exe()` downloads the official binary for this OS from the latest AutoDock-Vina GitHub release.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

import numpy as np

from ..util import app_data_dir

RELEASES = "https://api.github.com/repos/ccsb-scripps/AutoDock-Vina/releases"


def find_vina_exe() -> str | None:
    env = os.environ.get("MD20_VINA_EXE")
    if env and Path(env).is_file():
        return env
    for name in ("vina.exe", "vina"):
        p = app_data_dir() / "bin" / name
        if p.is_file():
            return str(p)
    return shutil.which("vina")


def _asset_pattern() -> re.Pattern:
    sysname, machine = platform.system(), platform.machine().lower()
    if sysname == "Windows":
        return re.compile(r"win", re.I)
    if sysname == "Darwin":
        return re.compile(r"mac.*(arm64|aarch64)" if machine in {"arm64", "aarch64"} else r"mac.*x86_64", re.I)
    return re.compile(r"linux.*(aarch64|arm64)" if machine in {"arm64", "aarch64"} else r"linux.*x86_64", re.I)


def ensure_vina_exe(dest_dir: Path | None = None) -> str:
    found = find_vina_exe()
    if found:
        return found
    dest = Path(dest_dir) if dest_dir else app_data_dir() / "bin"
    dest.mkdir(parents=True, exist_ok=True)
    pat = _asset_pattern()
    with urllib.request.urlopen(RELEASES, timeout=60) as r:
        releases = json.loads(r.read().decode())
    for rel in releases:
        for a in rel.get("assets", []):
            name = a.get("name", "")
            if pat.search(name) and not name.endswith((".tar.gz", ".zip", ".sha256")) and "split" not in name:
                target = dest / ("vina.exe" if sys.platform.startswith("win") else "vina")
                urllib.request.urlretrieve(a["browser_download_url"], target)
                target.chmod(target.stat().st_mode | stat.S_IEXEC)
                return str(target)
    raise RuntimeError("找不到此作業系統的 AutoDock Vina 執行檔；請手動下載並設定 MD20_VINA_EXE。")


_RESULT = re.compile(r"REMARK VINA RESULT:\s+(-?\d+\.\d+)")


def run_vina_cli(exe: str, receptor_pdbqt: str, ligand_pdbqts: list[str], center, size, *, scoring: str = "vina",
                 exhaustiveness: int = 16, n_poses: int = 9, energy_range: float = 3.0, seed: int = 2026,
                 cpu: int = 0) -> tuple[str, np.ndarray]:
    """Run the Vina executable; returns (docked PDBQT string, total energies per pose)."""
    with tempfile.TemporaryDirectory(prefix="md20_vina_") as td:
        td = Path(td)
        lig_files = []
        for i, s in enumerate(ligand_pdbqts):
            f = td / f"lig{i}.pdbqt"; f.write_text(s, encoding="utf-8"); lig_files.append(str(f))
        out = td / "out.pdbqt"
        cmd = [exe, "--receptor", str(receptor_pdbqt), "--ligand", *lig_files, "--scoring", scoring,
               "--center_x", str(center[0]), "--center_y", str(center[1]), "--center_z", str(center[2]),
               "--size_x", str(size[0]), "--size_y", str(size[1]), "--size_z", str(size[2]),
               "--exhaustiveness", str(int(exhaustiveness)), "--num_modes", str(int(n_poses)),
               "--energy_range", str(float(energy_range)), "--seed", str(int(seed)), "--out", str(out)]
        if cpu:
            cmd += ["--cpu", str(int(cpu))]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
        if p.returncode != 0 or not out.is_file():
            raise RuntimeError("Vina 執行失敗：" + (p.stderr or p.stdout)[-2000:])
        text = out.read_text(encoding="utf-8")
    energies = np.array([float(m.group(1)) for m in _RESULT.finditer(text)])
    return text, energies
