"""OpenMM platform ladder: CUDA → HIP → OpenCL → CPU → Reference.

Each candidate is *really* exercised (a Context is built and a few steps are
integrated) before it is accepted, because `Platform.getPlatformByName`
succeeding does not mean the driver works.  Failure never blocks: the next
rung is tried and the reason is kept for the Doctor report.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict

DEFAULT_ORDER = ("CUDA", "HIP", "OpenCL", "CPU", "Reference")


@dataclass
class PlatformChoice:
    name: str
    properties: dict = field(default_factory=dict)
    probe_seconds: float | None = None
    rejected: list[dict] = field(default_factory=list)   # [{"name":..,"error":..}]
    is_gpu: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def available_platforms() -> list[str]:
    try:
        import openmm as mm
    except ImportError:
        return []
    try:
        mm.Platform.loadPluginsFromDirectory(mm.Platform.getDefaultPluginsDirectory())
    except Exception:  # noqa: BLE001
        pass
    return [mm.Platform.getPlatform(i).getName() for i in range(mm.Platform.getNumPlatforms())]


def _toy_system():
    """500 LJ argon atoms in a periodic box: enough to exercise nonbonded kernels."""
    import numpy as np
    import openmm as mm
    from openmm import unit
    n, box = 500, 3.0
    system = mm.System()
    system.setDefaultPeriodicBoxVectors(mm.Vec3(box, 0, 0), mm.Vec3(0, box, 0), mm.Vec3(0, 0, box))
    nb = mm.NonbondedForce()
    nb.setNonbondedMethod(mm.NonbondedForce.CutoffPeriodic)
    nb.setCutoffDistance(1.0)
    for _ in range(n):
        system.addParticle(39.948)
        nb.addParticle(0.0, 0.34, 0.99)
    system.addForce(nb)
    rng = np.random.default_rng(2026)
    pos = rng.uniform(0, box, size=(n, 3))
    return system, pos * unit.nanometer


def _props_for(name: str, precision: str, device_index: str | None) -> dict:
    props = {}
    if name in {"CUDA", "OpenCL", "HIP"}:
        props["Precision"] = precision
        if device_index is not None:
            props["DeviceIndex"] = str(device_index)
    return props


def choose_platform(order=DEFAULT_ORDER, *, precision: str = "mixed", device_index: str | None = None,
                    probe_steps: int = 200, require_gpu: bool = False) -> PlatformChoice:
    import openmm as mm
    from openmm import unit
    names = set(available_platforms())
    rejected: list[dict] = []
    system, positions = _toy_system()
    for name in order:
        if name not in names:
            rejected.append({"name": name, "error": "OpenMM 未載入此平台（外掛不存在或驅動缺失）"})
            continue
        if require_gpu and name in {"CPU", "Reference"}:
            rejected.append({"name": name, "error": "require_gpu=True，跳過 CPU"})
            continue
        props = _props_for(name, precision, device_index)
        try:
            platform = mm.Platform.getPlatformByName(name)
            integ = mm.LangevinMiddleIntegrator(300 * unit.kelvin, 1 / unit.picosecond, 0.002 * unit.picoseconds)
            t0 = time.perf_counter()
            ctx = mm.Context(system, integ, platform, props)
            ctx.setPositions(positions)
            ctx.setVelocitiesToTemperature(300 * unit.kelvin, 1)
            integ.step(int(probe_steps))
            e = ctx.getState(getEnergy=True).getPotentialEnergy()._value
            if e != e:  # NaN
                raise RuntimeError("probe energy is NaN")
            actual = ctx.getPlatform().getName()
            dt = time.perf_counter() - t0
            used = {k: platform.getPropertyValue(ctx, k) for k in platform.getPropertyNames()} if name != "Reference" else {}
            del ctx, integ
            if actual != name:
                raise RuntimeError(f"Context 實際建立在 {actual}")
            return PlatformChoice(name=name, properties=used, probe_seconds=round(dt, 3), rejected=rejected,
                                  is_gpu=name in {"CUDA", "HIP", "OpenCL"})
        except Exception as exc:  # noqa: BLE001
            rejected.append({"name": name, "error": f"{type(exc).__name__}: {str(exc)[:400]}"})
            continue
    raise RuntimeError("沒有任何 OpenMM 平台可用：" + "; ".join(f"{r['name']}: {r['error']}" for r in rejected))


def explain_rejection(rej: dict, hardware: dict) -> str:
    """Turn a rejection into a plain-language hint for students."""
    name, err = rej.get("name", ""), rej.get("error", "")
    gpus = hardware.get("gpus", [])
    has_nvidia = any(g.get("vendor") == "NVIDIA" for g in gpus)
    has_amd = any(g.get("vendor") == "AMD" for g in gpus)
    if name == "CUDA":
        if not has_nvidia:
            return "此電腦沒有 NVIDIA 顯示卡，CUDA 不可用是正常的。"
        if "未載入" in err:
            return "有 NVIDIA 顯示卡但 OpenMM 的 CUDA 外掛沒有載入：通常是 conda 環境裝到 CPU 版 openmm，或 CUDA 驅動版本太舊。請在環境中重新安裝 `openmm` 的 CUDA 版並更新 NVIDIA 驅動。"
        if "CUDA_ERROR" in err or "cuInit" in err or "no CUDA-capable" in err:
            return "NVIDIA 驅動存在但無法初始化 CUDA：請更新驅動（GeForce Experience／NVIDIA App），並確認筆電不是只開啟內顯。"
        return "CUDA 平台建立失敗：" + err
    if name == "HIP":
        if not has_amd:
            return "沒有 AMD 顯示卡，HIP 不可用是正常的。"
        return "HIP 只在 Linux + ROCm 可用；Windows 的 AMD 顯示卡請使用 OpenCL。"
    if name == "OpenCL":
        if "未載入" in err:
            return "OpenCL 外掛未載入：請確認安裝的 openmm 含 OpenCL 支援。"
        if "clGetPlatformIDs" in err or "No OpenCL" in err or "-1001" in err:
            return "系統沒有 OpenCL 執行環境（ICD）：NVIDIA/AMD/Intel 的顯示卡驅動通常會附帶；請重新安裝顯示卡驅動。"
        return "OpenCL 平台建立失敗：" + err
    return err
