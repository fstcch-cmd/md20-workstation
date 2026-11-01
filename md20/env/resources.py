"""WP10 resource modes: how much of the computer MD20 may take.

  background — lowest OS priority, CPU platform uses ¼ of the cores, GPU duty cycle 50 % (sleep between batches);
               for a lab PC someone is also using.
  balanced   — below-normal priority, CPU platform leaves 2 cores free, GPU duty 85 %.  (default)
  full       — normal priority, all cores, no throttling; for an idle workstation / overnight.

Guards (any mode): pause at the next chunk boundary when RAM use > 92 % or the NVIDIA GPU is ≥ 87 °C; resume
automatically when it cools down / memory is freed (the pause policy is polled again by `md20 resume`).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass

MODES = {
    "background": {"priority": "idle", "cpu_fraction": 0.25, "gpu_duty": 0.5},
    "balanced": {"priority": "below_normal", "cpu_fraction": None, "gpu_duty": 0.85},
    "full": {"priority": "normal", "cpu_fraction": 1.0, "gpu_duty": 1.0},
}
RAM_MAX_PERCENT = 92.0
GPU_MAX_C = 87


@dataclass
class ResourcePlan:
    mode: str
    threads: int | None
    gpu_duty: float
    priority: str

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def plan(mode: str = "balanced", n_cpu: int | None = None) -> ResourcePlan:
    if mode not in MODES:
        raise ValueError(f"未知資源模式 {mode}（可用：{', '.join(MODES)}）")
    m = MODES[mode]
    n = n_cpu or os.cpu_count() or 2
    if m["cpu_fraction"] is None:
        threads = max(1, n - 2)
    else:
        threads = max(1, int(round(n * m["cpu_fraction"])))
    return ResourcePlan(mode=mode, threads=threads, gpu_duty=m["gpu_duty"], priority=m["priority"])


def apply_priority(priority: str) -> str:
    """Lower this process' OS priority (never raises it above normal)."""
    try:
        import psutil
    except ImportError:
        return "psutil 不可用，未調整優先權"
    p = psutil.Process()
    try:
        if os.name == "nt":
            val = {"idle": psutil.IDLE_PRIORITY_CLASS, "below_normal": psutil.BELOW_NORMAL_PRIORITY_CLASS,
                   "normal": psutil.NORMAL_PRIORITY_CLASS}[priority]
        else:
            val = {"idle": 19, "below_normal": 10, "normal": 0}[priority]
            val = max(val, p.nice())   # cannot raise priority without root
        p.nice(val)
        return f"程序優先權：{priority}"
    except Exception as exc:  # noqa: BLE001
        return f"無法調整優先權：{exc}"


def platform_properties(platform_name: str, base: dict | None, rp: ResourcePlan) -> dict:
    props = dict(base or {})
    if platform_name == "CPU" and rp.threads:
        props["Threads"] = str(rp.threads)
    return props


class DutyCycle:
    """Sleep after GPU work so the GPU is busy only `duty` of the wall time (keeps a desktop responsive)."""

    def __init__(self, duty: float):
        self.duty = max(0.05, min(1.0, float(duty)))
        self._t = time.monotonic()

    def __call__(self) -> None:
        now = time.monotonic()
        busy = now - self._t
        if self.duty < 1.0 and busy > 0:
            time.sleep(min(5.0, busy * (1.0 - self.duty) / self.duty))
        self._t = time.monotonic()


def gpu_temperature_c() -> int | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout
        vals = [int(x) for x in out.split() if x.strip().isdigit()]
        return max(vals) if vals else None
    except Exception:  # noqa: BLE001
        return None


def guard_reason(*, ram_probe=None, temp_probe=gpu_temperature_c) -> str | None:
    """Reason to pause at the next chunk boundary, or None."""
    try:
        if ram_probe is None:
            import psutil
            ram = psutil.virtual_memory().percent
        else:
            ram = ram_probe()
        if ram is not None and ram > RAM_MAX_PERCENT:
            return f"記憶體使用 {ram:.0f}% > {RAM_MAX_PERCENT:.0f}%：暫停以免系統當機（關閉其他程式後續跑）"
    except Exception:  # noqa: BLE001
        pass
    t = temp_probe() if temp_probe else None
    if t is not None and t >= GPU_MAX_C:
        return f"GPU 溫度 {t} °C ≥ {GPU_MAX_C} °C：暫停降溫（檢查散熱／風扇）"
    return None


class CachedGuard:
    """guard_reason() at most every `every_s` seconds (nvidia-smi is slow-ish; the engine polls often)."""

    def __init__(self, every_s: float = 30.0, **kw):
        self.every_s, self.kw, self._t, self._last = every_s, kw, -1e9, None

    def __call__(self) -> str | None:
        now = time.monotonic()
        if now - self._t >= self.every_s:
            self._t, self._last = now, guard_reason(**self.kw)
        return self._last
