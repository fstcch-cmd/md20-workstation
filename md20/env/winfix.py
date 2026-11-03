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


def set_power_throttling(handle=None, *, eco: bool) -> bool:
    """Windows 11: tag a process HighQoS (eco=False) or EcoQoS (eco=True) — D-72.

    Windows gives a process the QoS of the window it descends from: when the MD20 console window is minimised or
    hidden behind the browser, the GUI and the vina.exe it starts drop to "Low" QoS, which hybrid CPUs run on the
    efficiency cores — on the laptop's i7-13620H that is 4 of 16 threads (the ~25 % seen in Task Manager however
    --cpu, priority and affinity were set).  An explicit tag through SetProcessInformation(ProcessPowerThrottling)
    replaces the visibility-based level.  `handle` = a process handle (Popen._handle); None = this process.
    Returns True when the tag was set; False elsewhere or when the call is unavailable (Windows 10 < 1709)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.GetCurrentProcess.argtypes = []
        k32.SetProcessInformation.restype = wintypes.BOOL
        k32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]

        class STATE(ctypes.Structure):     # PROCESS_POWER_THROTTLING_STATE
            _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]

        st = STATE(1, 0x1, 0x1 if eco else 0x0)   # CURRENT_VERSION, EXECUTION_SPEED; StateMask 0 = HighQoS
        h = k32.GetCurrentProcess() if handle is None else wintypes.HANDLE(int(handle))
        return bool(k32.SetProcessInformation(h, 4, ctypes.byref(st), ctypes.sizeof(st)))   # ProcessPowerThrottling
    except Exception:  # noqa: BLE001
        return False


def process_cpu_seconds(handle) -> float | None:
    """User + kernel CPU seconds of a (possibly finished) Windows process, from GetProcessTimes; None elsewhere."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetProcessTimes.restype = wintypes.BOOL
        k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        t = [wintypes.FILETIME() for _ in range(4)]
        if not k32.GetProcessTimes(wintypes.HANDLE(int(handle)), *[ctypes.byref(x) for x in t]):
            return None
        ticks = lambda ft: (ft.dwHighDateTime << 32) | ft.dwLowDateTime   # noqa: E731  (100 ns units)
        return (ticks(t[2]) + ticks(t[3])) / 1e7
    except Exception:  # noqa: BLE001
        return None
