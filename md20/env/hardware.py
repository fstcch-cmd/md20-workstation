"""Hardware probe without third-party dependencies.

Collects what a student needs to paste to a teacher when something does not
run: OS, CPU, RAM, free disk, GPUs (NVIDIA via nvidia-smi, AMD via rocm-smi
or Windows WMI, Apple via system_profiler), power state on laptops.
Everything is best-effort: a probe that fails records the error instead of
raising.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str], timeout: float = 15.0) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return -1, f"{type(exc).__name__}: {exc}"


def _ram_bytes() -> int | None:
    try:
        if sys.platform.startswith("win"):
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MEMORYSTATUSEX(); st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))  # type: ignore[attr-defined]
            return int(st.ullTotalPhys)
        if sys.platform == "darwin":
            rc, out = _run(["sysctl", "-n", "hw.memsize"])
            return int(out.strip()) if rc == 0 else None
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except Exception:  # noqa: BLE001
        return None


def _nvidia() -> list[dict]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    rc, out = _run([exe, "--query-gpu=name,memory.total,driver_version,compute_cap",
                    "--format=csv,noheader,nounits"])
    gpus = []
    if rc == 0:
        for line in out.strip().splitlines():
            parts = [x.strip() for x in line.split(",")]
            if len(parts) >= 3:
                gpus.append({"vendor": "NVIDIA", "name": parts[0], "vram_mb": _int(parts[1]),
                             "driver": parts[2], "compute_capability": parts[3] if len(parts) > 3 else None})
    else:
        gpus.append({"vendor": "NVIDIA", "name": "nvidia-smi present but failed", "error": out[-500:]})
    return gpus


def _amd() -> list[dict]:
    gpus = []
    exe = shutil.which("rocm-smi")
    if exe:
        rc, out = _run([exe, "--showproductname", "--showmeminfo", "vram", "--csv"])
        if rc == 0:
            gpus.append({"vendor": "AMD", "name": "ROCm device (see raw)", "raw": out[-1500:]})
    return gpus


def _windows_wmi_gpus() -> list[dict]:
    if not sys.platform.startswith("win"):
        return []
    rc, out = _run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion | ConvertTo-Json"],
                   timeout=30)
    if rc != 0:
        return []
    import json
    try:
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
        return [{"vendor": _vendor_from_name(d.get("Name", "")), "name": d.get("Name"),
                 "vram_mb": (int(d["AdapterRAM"]) // (1024 * 1024)) if d.get("AdapterRAM") else None,
                 "driver": d.get("DriverVersion"), "source": "wmi"} for d in data]
    except Exception:  # noqa: BLE001
        return []


def _mac_gpus() -> list[dict]:
    if sys.platform != "darwin":
        return []
    rc, out = _run(["system_profiler", "SPDisplaysDataType"], timeout=30)
    if rc != 0:
        return []
    names = [l.split(":", 1)[1].strip() for l in out.splitlines() if "Chipset Model" in l]
    return [{"vendor": _vendor_from_name(n), "name": n, "source": "system_profiler"} for n in names]


def _vendor_from_name(name: str) -> str:
    n = name.lower()
    if "nvidia" in n or "geforce" in n or "rtx" in n or "quadro" in n:
        return "NVIDIA"
    if "amd" in n or "radeon" in n:
        return "AMD"
    if "intel" in n:
        return "Intel"
    if "apple" in n:
        return "Apple"
    return "unknown"


def _int(x):
    try:
        return int(float(x))
    except Exception:  # noqa: BLE001
        return None


def _power_state() -> dict:
    """Laptop on battery?  Windows via WMI, macOS via pmset, Linux via /sys."""
    try:
        if sys.platform.startswith("win"):
            rc, out = _run(["powershell", "-NoProfile", "-Command",
                            "(Get-CimInstance Win32_Battery).BatteryStatus"], timeout=20)
            if rc == 0 and out.strip():
                status = out.strip().splitlines()[0]
                return {"has_battery": True, "on_ac": status not in {"1"}, "raw": status}
            return {"has_battery": False, "on_ac": True}
        if sys.platform == "darwin":
            rc, out = _run(["pmset", "-g", "batt"])
            return {"has_battery": "InternalBattery" in out, "on_ac": "AC Power" in out}
        for d in Path("/sys/class/power_supply").glob("*"):
            if (d / "type").is_file() and (d / "type").read_text().strip() == "Mains":
                online = (d / "online").read_text().strip() == "1" if (d / "online").is_file() else True
                return {"has_battery": any(p.name.startswith("BAT") for p in d.parent.iterdir()), "on_ac": online}
        return {"has_battery": False, "on_ac": True}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def probe_hardware(workdir: Path | str | None = None) -> dict:
    wd = Path(workdir) if workdir else Path.cwd()
    try:
        du = shutil.disk_usage(wd)
        disk = {"path": str(wd), "free_gb": round(du.free / 1e9, 1), "total_gb": round(du.total / 1e9, 1)}
    except Exception as exc:  # noqa: BLE001
        disk = {"error": str(exc)}
    ram = _ram_bytes()
    gpus = _nvidia() + _amd()
    if not gpus:
        gpus = _windows_wmi_gpus() or _mac_gpus()
    return {
        "os": {"system": platform.system(), "release": platform.release(), "version": platform.version(),
               "machine": platform.machine(), "python": platform.python_version()},
        "cpu": {"logical_cores": os.cpu_count(), "name": platform.processor() or None},
        "ram_gb": round(ram / 1e9, 1) if ram else None,
        "disk": disk,
        "gpus": gpus,
        "power": _power_state(),
        "env": {"CUDA_VISIBLE_DEVICES": os.environ.get("CUDA_VISIBLE_DEVICES"),
                "OPENMM_CUDA_COMPILER": os.environ.get("OPENMM_CUDA_COMPILER")},
    }
