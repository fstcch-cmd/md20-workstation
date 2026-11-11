"""Whether the implicit-solvent quick preview may be offered on this computer (D-181, docs/specs/lite_edition.md §8).

The quick preview is the existing `md.solvent: gbn2` (D-20, docs/specs/implicit_solvent.md).  GBn2 is fast only on a GPU.
On a CPU 3PTB took 65 minutes (D-25), far slower than explicit water, so a computer without a usable GPU platform is
not offered the preview.  This module only answers that question from a platform or a Doctor result.  It starts no
calculation and imports nothing heavy, so the interface can ask it at any time.
"""
from __future__ import annotations

GPU_PLATFORMS = ("CUDA", "HIP", "Metal")            # a GPU by construction
OPENCL = "OpenCL"                                   # runs on a GPU or on a CPU; the device name tells which
_CPU_DEVICE_WORDS = ("cpu", "pocl", "pthread", "portable computing", "llvmpipe", "software", "reference")

NOT_OFFERED = (
    "這台電腦沒有可用的 GPU，不提供隱式溶劑快速預覽。GBn2 在 CPU 上比顯式水更慢。",
    "This computer has no usable GPU, so the implicit-solvent quick preview is not offered. GBn2 is slower than explicit water on a CPU.",
    "このコンピュータには使える GPU がないため、陰溶媒のクイックプレビューは提供しません。GBn2 は CPU では陽溶媒の水より遅くなります。",
    "이 컴퓨터에는 사용할 수 있는 GPU가 없어 암시적 용매 빠른 미리보기를 제공하지 않습니다. GBn2는 CPU에서 명시적 물보다 느립니다.",
)


def _as_platform(obj) -> dict | None:
    """The platform record out of a platform choice, its dict, a Doctor report or the dict of a Doctor report."""
    if obj is None:
        return None
    if hasattr(obj, "platform") and not hasattr(obj, "is_gpu"):          # DoctorReport
        obj = obj.platform
        if obj is None:
            return None
    if isinstance(obj, dict) and "platform" in obj and "name" not in obj:     # DoctorReport.to_dict()
        obj = obj.get("platform")
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    return {"name": getattr(obj, "name", ""), "properties": getattr(obj, "properties", None) or {},
            "device_name": getattr(obj, "device_name", "") or ""}


def _gpus_listed(obj) -> bool:
    """The Doctor report lists at least one graphics card without an error."""
    hw = obj.get("hardware") if isinstance(obj, dict) else getattr(obj, "hardware", None)
    gpus = (hw or {}).get("gpus") if isinstance(hw, dict) else None
    return any(isinstance(g, dict) and not g.get("error") for g in gpus or [])


def quick_preview_available(result) -> bool:
    """True only when a GPU platform is usable.

    `result` is what the Doctor or the platform choice returned: a `PlatformChoice`, its `to_dict()`, a `DoctorReport` or
    its `to_dict()`.  CUDA, HIP and Metal count as a GPU.  OpenCL counts when its device is not a CPU: the device name must
    be known and must not look like a CPU, or the Doctor must list a graphics card.  CPU, Reference, no platform and
    anything not understood give False (寧可擋也不要猜)."""
    p = _as_platform(result)
    if not p:
        return False
    name = str(p.get("name") or "")
    if name in GPU_PLATFORMS:
        return True
    if name != OPENCL:
        return False
    props = p.get("properties") or {}
    device = str(p.get("device_name") or next((v for k, v in props.items() if str(k).lower().endswith("devicename")), "") or "").lower()
    if device:
        return not any(w in device for w in _CPU_DEVICE_WORDS)
    return _gpus_listed(result)
