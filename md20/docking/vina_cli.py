"""AutoDock Vina command-line fallback (Windows: the pip `vina` package has no wheel and needs Boost to build).

Executable search order: $MD20_VINA_EXE → <app data>/bin/vina[.exe] → `vina` on PATH.
`ensure_vina_exe()` downloads the official binary for this OS from ONE pinned AutoDock-Vina release and checks its
sha256 before use (D-114, REVIEW #19).  "latest" is opt-in only (MD20_VINA_LATEST=1) and is recorded as unverified.
"""
from __future__ import annotations

import hashlib
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
    for url, want in _candidate_urls(errors):
        tmp = target.with_name(target.name + ".part")
        try:
            urllib.request.urlretrieve(url, tmp)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")
            tmp.unlink(missing_ok=True)
            continue
        got = sha256_file(tmp)
        if want is not None and got != want:
            # D-114: never run a binary whose bytes differ from the pinned release (corrupt proxy download, tampering)
            tmp.unlink(missing_ok=True)
            errors.append(f"{url}: sha256 {got[:12]}… ≠ 預期 {want[:12]}…（檔案不符，已刪除，未使用）")
            continue
        os.replace(tmp, target)
        target.chmod(target.stat().st_mode | stat.S_IEXEC)
        return str(target)
    raise RuntimeError("找不到或下載不到此作業系統的 AutoDock Vina 執行檔；請手動下載並設定 MD20_VINA_EXE。"
                       + ("（" + "；".join(errors[-3:]) + "）" if errors else ""))


# D-114 (REVIEW #19): one pinned release for every student — previously the releases API ("latest", v1.2.7 on
# 2026-11-07) was tried first and the pinned v1.2.5 only when the API was rate-limited (60 requests/hour per IP: a
# classroom behind one NAT), so the same class could dock with two Vina versions.  Release-asset downloads are not
# subject to that limit.  Hashes: computed 2026-11-07 from the GitHub release assets (see DECISIONS D-114).
PINNED_VERSION = "v1.2.7"
_ASSET_SUFFIX = {("Windows", "x86_64"): "win.exe", ("Linux", "x86_64"): "linux_x86_64", ("Darwin", "x86_64"): "mac_x86_64",
                 ("Darwin", "arm64"): "mac_aarch64", ("Linux", "aarch64"): "linux_aarch64"}
PINNED_ASSETS = {k: f"vina_{PINNED_VERSION.lstrip('v')}_{v}" for k, v in _ASSET_SUFFIX.items()}
KNOWN_SHA256 = {
    "vina_1.2.7_win.exe": "e0c4b2715e0c1a74f6e92d0f3be0328ac97542eafbc111e6b1efad897a73cce5",
    "vina_1.2.7_linux_x86_64": "f31f774f723bba7bbe6e9d1c47577020eea9a8da16424284c043d22593570644",
    "vina_1.2.7_linux_aarch64": "d30c18a7d5f6f8ea9146e1cbc0aa7ade0bbb105b54ece08b4e5a7fa53edb6c62",
    "vina_1.2.7_mac_x86_64": "9f44ccbb163223613283a75d0be53235d9e63f4da08292cb7196144f9838b7f9",
    "vina_1.2.7_mac_aarch64": "823c2bbacf26d72183861322345f0a89736aca66c8e81054c66f93af5ad623f1",
    # the previous pin, so an executable installed by an earlier MD20 is still identified
    "vina_1.2.5_win.exe": "b5a23b226ee5dc1b028df04082d13a7b0e5b9b12b988bbcf9498cb351e20b38f",
    "vina_1.2.5_linux_x86_64": "fa0126a28a9ea9162d1b161dfa92bc76e632416db28ca246278ea4b2dc6860cb",
    "vina_1.2.5_linux_aarch64": "5bf4eba87f133b5c2d35e5e6c21c062221e2a35a91ee7fa1dbd69d341efb3516",
    "vina_1.2.5_mac_x86_64": "de9402701fba0f69bce53aec94254a08a7044c7d1d459958896022a7f98b073d",
    "vina_1.2.5_mac_aarch64": "4999b3133f162b66d8b21bafdb54aa53c507ed6347489844e6778dac7871ff5f",
}


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def vina_exe_identity(path: Path | str) -> dict:
    """Which official release an executable is, by sha256 (None = not an official asset we know: user-built, other
    version, or modified).  Recorded with every docking run so results say which Vina produced them."""
    try:
        h = sha256_file(path)
    except OSError as exc:
        return {"path": str(path), "sha256": None, "asset": None, "error": str(exc)}
    asset = next((a for a, v in KNOWN_SHA256.items() if v == h), None)
    return {"path": str(path), "sha256": h, "asset": asset,
            "version": ("v" + asset.split("_")[1]) if asset else None, "pinned": bool(asset and asset in PINNED_ASSETS.values())}


def _pinned_url() -> str | None:
    name = _pinned_name()
    return f"https://github.com/ccsb-scripps/AutoDock-Vina/releases/download/{PINNED_VERSION}/{name}" if name else None


def _pinned_name() -> str | None:
    m = platform.machine().lower()
    arch = "arm64" if m in {"arm64", "aarch64"} and platform.system() == "Darwin" else \
           "aarch64" if m in {"arm64", "aarch64"} else "x86_64"
    return PINNED_ASSETS.get((platform.system(), arch))


def _candidate_urls(errors: list[str]) -> list[tuple[str, str | None]]:
    """(url, expected sha256).  Default: only the pinned release, verified.  MD20_VINA_LATEST=1: the newest matching
    asset from the releases API first (sha256 unknown → recorded, not verified), then the pinned release."""
    urls: list[tuple[str, str | None]] = []
    if os.environ.get("MD20_VINA_LATEST") == "1":
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
                        urls.append((a["browser_download_url"], KNOWN_SHA256.get(name)))
                        break
                if urls:
                    break
        except Exception as exc:  # noqa: BLE001  (HTTP 403 rate limit, offline proxy …)
            errors.append(f"releases API: {exc}")
    pinned, name = _pinned_url(), _pinned_name()
    if pinned and pinned not in [u for u, _ in urls]:
        urls.append((pinned, KNOWN_SHA256.get(name)))
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
