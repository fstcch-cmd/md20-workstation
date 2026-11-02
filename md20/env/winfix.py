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


_JOB = None   # kept for the life of the process: closing it (on exit, crash or a closed console) ends the children


def kill_children_on_exit() -> bool:
    """Windows: put this process into a Job Object with KILL_ON_JOB_CLOSE (D-69).

    Closing the console window that runs MD20 killed Python but not the vina.exe it had started: the orphan kept
    docking (and the next run competed with it for the CPU).  Children inherit the job, so when this process ends
    for any reason the system ends them too.  Returns True when the job is in place; no-op elsewhere."""
    global _JOB
    if sys.platform != "win32" or _JOB is not None:
        return _JOB is not None
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # 64-bit handles: without argtypes ctypes passes them as 32-bit ints and the call fails (CI c4d7232)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.GetCurrentProcess.argtypes = []
        k32.SetInformationJobObject.restype = wintypes.BOOL
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("Read", "Write", "Other", "ReadT", "WriteT", "OtherT")]

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class EXTENDED(ctypes.Structure):
            _fields_ = [("Basic", BASIC), ("Io", IO_COUNTERS), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        job = k32.CreateJobObjectW(None, None)
        if not job:
            return False
        info = EXTENDED()
        info.Basic.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):   # ExtendedLimitInformation
            return False
        if not k32.AssignProcessToJobObject(job, k32.GetCurrentProcess()):
            return False
        _JOB = job
        return True
    except Exception:  # noqa: BLE001 — never stop MD20 from starting because of this
        return False
