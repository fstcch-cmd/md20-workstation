"""Windows-only hardening for driver probing.

A broken or leftover GPU driver DLL (e.g. an old `nvopencl.dll` whose exports
no longer match) makes Windows show a *modal* "entry point not found" dialog
when the OpenCL ICD loader touches it.  That dialog blocks a headless Doctor
or a scheduled run forever.  `SetErrorMode` turns the dialog into a plain
load failure that the platform ladder can catch and explain.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SEM_FAILCRITICALERRORS = 0x0001
SEM_NOGPFAULTERRORBOX = 0x0002
SEM_NOOPENFILEERRORBOX = 0x8000


def suppress_windows_error_dialogs() -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes
        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        k32.SetErrorMode(k32.SetErrorMode(0) | SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX)
        # Also ask the C runtime not to pop assertion boxes.
        try:
            ctypes.cdll.msvcrt._set_error_mode(1)  # _OUT_TO_STDERR
        except Exception:  # noqa: BLE001
            pass
        return True
    except Exception:  # noqa: BLE001
        return False


def nvidia_driver_files() -> dict:
    """Which NVIDIA runtime files exist in System32 (works even when nvidia-smi is not on PATH)."""
    if not sys.platform.startswith("win"):
        return {}
    sysdir = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    names = ["nvcuda.dll", "nvopencl.dll", "nvidia-smi.exe", "nvml.dll"]
    out = {n: (sysdir / n).is_file() for n in names}
    out["system32"] = str(sysdir)
    return out


def diagnose_nvidia_files(files: dict) -> str | None:
    """Plain-language verdict about leftover / inconsistent NVIDIA driver files."""
    if not files:
        return None
    has_cuda, has_ocl, has_smi = files.get("nvcuda.dll"), files.get("nvopencl.dll"), files.get("nvidia-smi.exe")
    if has_ocl and not (has_cuda and has_smi):
        return ("System32 裡有 nvopencl.dll 但沒有完整的 NVIDIA 驅動（nvcuda.dll / nvidia-smi.exe 缺失）：這是舊驅動殘留，"
                "會讓 OpenCL 載入時跳出「無法找到程序輸入點 fatBinaryCtl」。若這台電腦有 NVIDIA 顯示卡，請用 NVIDIA App 重新安裝驅動（勾選全新安裝）；"
                "若沒有 NVIDIA 顯示卡，請用 Display Driver Uninstaller（DDU）移除殘留，或直接以 CPU 平台執行（Doctor 會自動選）。")
    if has_cuda and has_smi and not has_ocl:
        return "NVIDIA 驅動存在但缺少 nvopencl.dll；CUDA 可用、OpenCL 不可用，屬正常組合。"
    return None
