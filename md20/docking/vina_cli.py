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
    target = dest / ("vina.exe" if sys.platform.startswith("win") else "vina")
    errors = []
    for url in _candidate_urls(errors):
        try:
            urllib.request.urlretrieve(url, target)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")
            continue
        target.chmod(target.stat().st_mode | stat.S_IEXEC)
        return str(target)
    raise RuntimeError("找不到或下載不到此作業系統的 AutoDock Vina 執行檔；請手動下載並設定 MD20_VINA_EXE。"
                       + ("（" + "；".join(errors[-3:]) + "）" if errors else ""))


# Release-asset downloads (github.com/…/releases/download/…) are not subject to the REST API's 60 requests/hour
# per-IP limit, which a classroom behind one NAT — or a CI runner pool — exhausts quickly.
PINNED_VERSION = "v1.2.5"
PINNED_ASSETS = {("Windows", "x86_64"): "vina_1.2.5_win.exe", ("Linux", "x86_64"): "vina_1.2.5_linux_x86_64",
                 ("Darwin", "x86_64"): "vina_1.2.5_mac_x86_64", ("Darwin", "arm64"): "vina_1.2.5_mac_aarch64",
                 ("Linux", "aarch64"): "vina_1.2.5_linux_aarch64"}


def _pinned_url() -> str | None:
    m = platform.machine().lower()
    arch = "arm64" if m in {"arm64", "aarch64"} and platform.system() == "Darwin" else \
           "aarch64" if m in {"arm64", "aarch64"} else "x86_64"
    name = PINNED_ASSETS.get((platform.system(), arch))
    return f"https://github.com/ccsb-scripps/AutoDock-Vina/releases/download/{PINNED_VERSION}/{name}" if name else None


def _candidate_urls(errors: list[str]) -> list[str]:
    """Latest matching asset from the releases API (token used when GH_TOKEN/GITHUB_TOKEN is set), then the pinned
    release as a fallback when the API is rate-limited or unreachable."""
    urls = []
    pat = _asset_pattern()
    req = urllib.request.Request(RELEASES, headers={"Accept": "application/vnd.github+json"})
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            releases = json.loads(r.read().decode())
        for rel in releases:
            for a in rel.get("assets", []):
                name = a.get("name", "")
                if pat.search(name) and not name.endswith((".tar.gz", ".zip", ".sha256")) and "split" not in name:
                    urls.append(a["browser_download_url"])
                    break
            if urls:
                break
    except Exception as exc:  # noqa: BLE001  (HTTP 403 rate limit, offline proxy …)
        errors.append(f"releases API: {exc}")
    pinned = _pinned_url()
    if pinned and pinned not in urls:
        urls.append(pinned)
    return urls


_RESULT = re.compile(r"REMARK VINA RESULT:\s+(-?\d+\.\d+)")


def run_vina_cli(exe: str, receptor_pdbqt: str, ligand_pdbqts: list[str], center, size, *, scoring: str = "vina",
                 exhaustiveness: int = 16, n_poses: int = 9, energy_range: float = 3.0, seed: int = 2026,
                 cpu: int = 0, stats: dict | None = None) -> tuple[str, np.ndarray]:
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
        # D-68: always pass --cpu, from the resource mode the user chose (background ¼ of the CPUs so a report can be
        # written meanwhile, balanced all but two, full all).  Left to itself the Windows vina.exe used about 4 of 16
        # logical CPUs on the laptop during a six-ligand simultaneous docking.
        from ..env.resources import cpu_threads, child_creationflags, child_eco_qos
        n_cpu = int(cpu) if cpu else cpu_threads()
        cmd += ["--cpu", str(n_cpu)]
        # simultaneous docking of several ligands is much slower than one ligand: 2 h + 1 h per extra ligand (D-68)
        timeout = 7200 + 3600 * max(0, len(lig_files) - 1)
        p, run = _run_measured(cmd, timeout, child_creationflags() if os.name == "nt" else 0, child_eco_qos())
        if stats is not None:
            stats.update(run, cpu_requested=n_cpu, exhaustiveness=int(exhaustiveness), n_ligands=len(lig_files),
                         threads_possible=min(n_cpu, int(exhaustiveness)))
        if p.returncode != 0 or not out.is_file():
            raise RuntimeError("Vina 執行失敗：" + (p.stderr or p.stdout)[-2000:])
        text = out.read_text(encoding="utf-8")
    energies = np.array([float(m.group(1)) for m in _RESULT.finditer(text)])
    return text, energies


def _run_measured(cmd: list[str], timeout: float, creationflags: int, eco: bool):
    """Run Vina and measure how many CPU threads it actually kept busy (D-72).

    Vina parallelises only its Monte-Carlo runs: min(--cpu, exhaustiveness) threads in the search, one thread for
    the grid maps and the final refinement.  effective_threads = CPU seconds / wall seconds of the whole run, so a
    value far below that bound means the OS — not Vina — held it back.  On Windows the process is also tagged
    HighQoS (EcoQoS in background mode) right after it starts."""
    import time
    from ..env.winfix import process_cpu_seconds, set_power_throttling
    ru0 = None
    if os.name != "nt":
        import resource
        ru0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    t0 = time.monotonic()
    kw = {"creationflags": creationflags} if os.name == "nt" else {}
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kw)
    qos = None
    if os.name == "nt":
        qos = ("eco" if eco else "high") if set_power_throttling(proc._handle, eco=eco) else "unchanged"
    try:
        so, se = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise
    wall = time.monotonic() - t0
    if os.name == "nt":
        cpu_s = process_cpu_seconds(proc._handle)
    else:
        import resource
        ru1 = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu_s = (ru1.ru_utime - ru0.ru_utime) + (ru1.ru_stime - ru0.ru_stime)
    run = {"wall_s": round(wall, 1), "cpu_s": None if cpu_s is None else round(cpu_s, 1), "qos": qos,
           "effective_threads": None if (cpu_s is None or wall <= 0) else round(cpu_s / wall, 2)}
    return subprocess.CompletedProcess(cmd, proc.returncode, so, se), run


def cpu_use_note(st: dict) -> tuple[str, bool]:
    """Chinese DecisionLog text for a measured Vina run; second value True when the OS evidently held Vina back."""
    eff, bound, wall = st.get("effective_threads"), st.get("threads_possible"), st.get("wall_s") or 0
    if eff is None or not bound:
        return "無法量測 Vina 實際使用的執行緒數。", False
    msg = (f"Vina 要求 {st.get('cpu_requested')} 執行緒、exhaustiveness {st.get('exhaustiveness')}"
           f"（最多可平行 {bound} 條），實際平均 {eff:.1f} 條（CPU {st.get('cpu_s')} s／牆鐘 {wall} s）。")
    if bound <= 1 or wall < 120:
        return msg + "執行時間短，數字只供參考。", False
    if eff < 0.5 * bound:
        return (msg + "遠低於上限：作業系統限制了 Vina。Windows 11 混合核心筆電常見原因是 MD20 視窗被最小化或被瀏覽器蓋住時，"
                "子程式被降為低 QoS、只排到節能核心（D-72，已改為標記 HighQoS；若仍出現，請回報並把 MD20 視窗留在畫面上）。"), True
    if bound < (st.get("cpu_requested") or 0):
        return msg + f"exhaustiveness {st.get('exhaustiveness')} 小於執行緒數，其餘執行緒本來就用不到（Vina 的設計）。", False
    return msg, False
