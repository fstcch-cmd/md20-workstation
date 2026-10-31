"""Doctor: one command that answers "can this laptop run MD, how fast, and if not, why?"

Outputs a JSON report (machine readable) and a Markdown summary (for pasting
to a teacher).  Nothing here raises on a missing component; every finding
is a row with severity OK / WARN / FAIL and a plain-language fix.
"""
from __future__ import annotations

import importlib
import importlib.metadata as md
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from ..util import atomic_write_json, now_iso, app_data_dir, ensure_dir
from .hardware import probe_hardware
from .platforms import choose_platform, available_platforms, explain_rejection
from .winfix import suppress_windows_error_dialogs, diagnose_nvidia_files

CORE_PACKAGES = {
    "openmm": "MD 引擎（必要）",
    "pdbfixer": "受體修復（必要）",
    "rdkit": "配體化學（必要）",
    "mdtraj": "軌跡分析（必要）",
    "numpy": "數值（必要）",
    "pandas": "表格（必要）",
    "matplotlib": "圖表（必要）",
    "openff.toolkit": "配體力場 OpenFF（預設路徑）",
    "openff.nagl": "配體電荷 NAGL（預設路徑）",
    "openmmforcefields": "GAFF／OpenFF 與 OpenMM 的橋接",
    "pymbar": "WHAM／MBAR（傘狀採樣）",
    "parmed": "GROMACS 匯出",
    "plotly": "互動圖表（選配）",
    "nicegui": "GUI（選配）",
}


@dataclass
class Finding:
    item: str
    severity: str          # OK | WARN | FAIL
    detail: str
    fix: str = ""


@dataclass
class DoctorReport:
    hardware: dict
    packages: dict
    platform: dict | None
    benchmark: dict | None
    findings: list[Finding] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)

    @property
    def ok(self) -> bool:
        return not any(f.severity == "FAIL" for f in self.findings)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def to_markdown(self) -> str:
        hw = self.hardware
        lines = [f"# MD20 Doctor 報告（{self.created_at}）", "",
                 f"- OS: {hw['os']['system']} {hw['os']['release']} ({hw['os']['machine']}), Python {hw['os']['python']}",
                 f"- CPU 邏輯核心: {hw['cpu']['logical_cores']}  RAM: {hw.get('ram_gb')} GB  可用磁碟: {hw['disk'].get('free_gb')} GB",
                 f"- GPU: " + ("; ".join(f"{g.get('vendor')} {g.get('name')} {g.get('vram_mb') or ''}MB" for g in hw['gpus']) or "未偵測到獨立顯示卡"),
                 f"- 電源: {'接電' if hw.get('power', {}).get('on_ac', True) else '電池（效能會降低，建議接電）'}", ""]
        if self.platform:
            lines.append(f"- 選用 OpenMM 平台: **{self.platform['name']}** {self.platform.get('properties', {})}")
        if self.benchmark and self.benchmark.get("ns_per_day"):
            lines.append(f"- Benchmark: {self.benchmark['ns_per_day']:.1f} ns/day（{self.benchmark['n_atoms']} 原子，dt {self.benchmark['timestep_fs']} fs）")
        lines += ["", "| 項目 | 狀態 | 說明 | 建議 |", "|---|---|---|---|"]
        for f in self.findings:
            lines.append(f"| {f.item} | {f.severity} | {f.detail} | {f.fix} |")
        return "\n".join(lines)


def _package_report() -> tuple[dict, list[Finding]]:
    out, findings = {}, []
    for mod, label in CORE_PACKAGES.items():
        try:
            m = importlib.import_module(mod)
            ver = getattr(m, "__version__", None)
            if ver is None:
                try:
                    ver = md.version(mod.split(".")[0].replace("_", "-"))
                except Exception:  # noqa: BLE001
                    ver = "?"
            out[mod] = {"installed": True, "version": str(ver)}
        except Exception as exc:  # noqa: BLE001
            out[mod] = {"installed": False, "error": f"{type(exc).__name__}: {exc}"}
            required = "必要" in label
            findings.append(Finding(item=f"套件 {mod}", severity="FAIL" if required else "WARN",
                                    detail=f"未安裝（{label}）",
                                    fix="執行安裝器或 `micromamba install -f environment/<os>.yml`"))
    return out, findings


def benchmark(platform_name: str, properties: dict, *, n_atoms_target: int = 24000, seconds: float = 20.0,
              timestep_fs: float = 4.0) -> dict:
    """TIP3P water box (~24k atoms, the size of a teaching system) built with Modeller; returns ns/day.

    Water is rigid (SETTLE), so 4 fs is stable here exactly as with HMR on a protein system.
    """
    import openmm as mm
    from openmm import app, unit
    n_w = max(300, n_atoms_target // 3)
    side = (n_w / 33.4) ** (1 / 3)
    ff = app.ForceField("amber14/tip3p.xml")
    modeller = app.Modeller(app.Topology(), [])
    modeller.addSolvent(ff, model="tip3p", boxSize=mm.Vec3(side, side, side) * unit.nanometer)
    system = ff.createSystem(modeller.topology, nonbondedMethod=app.PME, nonbondedCutoff=0.9 * unit.nanometer,
                             constraints=app.HBonds, rigidWater=True)
    integ = mm.LangevinMiddleIntegrator(300 * unit.kelvin, 1 / unit.picosecond, timestep_fs * unit.femtoseconds)
    ctx = mm.Context(system, integ, mm.Platform.getPlatformByName(platform_name), properties)
    ctx.setPositions(modeller.positions)
    mm.LocalEnergyMinimizer.minimize(ctx, maxIterations=200)
    ctx.setVelocitiesToTemperature(300 * unit.kelvin, 1)
    integ.step(200)  # warm-up / kernel compile
    steps, t0 = 0, time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        integ.step(250)
        steps += 250
    dt = time.perf_counter() - t0
    e = ctx.getState(getEnergy=True).getPotentialEnergy()._value
    if e != e:
        raise RuntimeError("benchmark energy NaN")
    ns_per_day = steps * timestep_fs * 1e-6 / dt * 86400
    n_atoms = system.getNumParticles()
    del ctx
    return {"platform": platform_name, "n_atoms": n_atoms, "timestep_fs": timestep_fs, "steps": steps,
            "seconds": round(dt, 2), "ns_per_day": round(ns_per_day, 2)}


def run_doctor(*, do_benchmark: bool = True, benchmark_seconds: float = 20.0, workdir: Path | None = None,
               save: bool = True) -> DoctorReport:
    suppress_windows_error_dialogs()
    hardware = probe_hardware(workdir)
    packages, findings = _package_report()
    verdict = diagnose_nvidia_files(hardware.get("nvidia_driver_files", {}))
    if verdict and "殘留" in verdict:
        findings.append(Finding("NVIDIA 驅動檔案", "WARN", "nvopencl.dll 殘留／驅動不完整", verdict))
    platform = None
    bench = None
    # hardware findings
    if (hardware.get("ram_gb") or 0) and hardware["ram_gb"] < 8:
        findings.append(Finding("記憶體", "WARN", f"{hardware['ram_gb']} GB", "建議 ≥ 8 GB；大系統請縮小水盒 padding。"))
    free = hardware.get("disk", {}).get("free_gb")
    if free is not None and free < 20:
        findings.append(Finding("磁碟空間", "WARN", f"剩餘 {free} GB", "教學 tier 一個 case 約需 5–15 GB；請清出空間。"))
    if hardware.get("power", {}).get("has_battery") and not hardware["power"].get("on_ac", True):
        findings.append(Finding("電源", "WARN", "目前使用電池", "長時間 MD 請接上電源，否則 CPU/GPU 會降頻且可能睡眠中斷。"))
    if packages.get("openmm", {}).get("installed"):
        try:
            choice = choose_platform()
            platform = choice.to_dict()
            for rej in choice.rejected:
                if rej["name"] in {"CUDA", "OpenCL", "HIP"}:
                    sev = "WARN" if choice.is_gpu else ("WARN" if rej["name"] != "CUDA" else "WARN")
                    findings.append(Finding(f"平台 {rej['name']}", sev, rej["error"][:160], explain_rejection(rej, hardware)))
            if not choice.is_gpu:
                findings.append(Finding("GPU 加速", "WARN", f"目前使用 {choice.name}（CPU）",
                                        "可以跑，但速度約為 GPU 的 1/10–1/30；教學 tier 請選 2–5 ns 課堂設定。"))
            else:
                findings.append(Finding("GPU 加速", "OK", f"{choice.name} {choice.properties}", ""))
            if do_benchmark:
                try:
                    bench = benchmark(choice.name, choice.properties, seconds=benchmark_seconds)
                    findings.append(Finding("Benchmark", "OK", f"{bench['ns_per_day']} ns/day @ {bench['n_atoms']} 原子, dt {bench['timestep_fs']} fs", ""))
                    rec = recommend_tier(bench["ns_per_day"], n_atoms_benchmark=bench["n_atoms"])
                    bench["tier_recommendation"] = rec
                    findings.append(Finding("建議 tier", "OK", rec["recommended"],
                                            "; ".join(f"{r['tier']}: {r['total_ns']} ns ≈ {r['eta_hours']} h" for r in rec["rows"])))
                except Exception as exc:  # noqa: BLE001
                    bench = {"error": f"{type(exc).__name__}: {str(exc)[:500]}", "platform": choice.name}
                    findings.append(Finding("Benchmark", "WARN", bench["error"][:200], "平台可建立但 PME benchmark 失敗；請把這行回報。"))
        except Exception as exc:  # noqa: BLE001
            findings.append(Finding("OpenMM 平台", "FAIL", str(exc)[:300], "連 CPU 平台都失敗：openmm 安裝損毀，請重新建立環境。"))
    else:
        findings.append(Finding("OpenMM 平台", "FAIL", "openmm 未安裝，無法探測平台", "先完成環境安裝。"))
    report = DoctorReport(hardware=hardware, packages=packages, platform=platform, benchmark=bench, findings=findings)
    if save:
        out = ensure_dir(app_data_dir() / "doctor")
        atomic_write_json(report.to_dict(), out / "doctor_report.json")
        (out / "doctor_report.md").write_text(report.to_markdown(), encoding="utf-8")
    return report


def estimate_eta_hours(ns_per_day: float, total_ns: float) -> float:
    return float("inf") if ns_per_day <= 0 else 24.0 * total_ns / ns_per_day


def recommend_tier(ns_per_day: float, *, n_atoms_benchmark: int = 24000, n_atoms_system: int | None = None,
                   max_hours: float = 48.0) -> dict:
    """Pick the largest teaching tier whose total simulated time fits in `max_hours` on this machine.

    Scales ns/day inversely with system size relative to the benchmark box.
    """
    from ..engine.protocol import TIERS, make_protocol
    scale = (n_atoms_benchmark / n_atoms_system) if n_atoms_system else 1.0
    rate = max(1e-9, ns_per_day * scale)
    rows = []
    for tier in ("classroom", "teaching", "research"):
        total = make_protocol(tier).total_ns()
        hours = estimate_eta_hours(rate, total)
        rows.append({"tier": tier, "total_ns": round(total, 3), "eta_hours": round(hours, 1), "fits": hours <= max_hours})
    best = [r for r in rows if r["fits"]]
    chosen = best[-1]["tier"] if best else "classroom"
    why = (f"以 {rate:.1f} ns/day（依系統大小換算）估算；{chosen} tier 可在 {max_hours:.0f} 小時內完成。"
           if best else f"即使最小的 classroom tier 也超過 {max_hours:.0f} 小時；建議縮小系統（padding 0.8 nm）或改用工作站佇列。")
    return {"recommended": chosen, "rate_ns_per_day": round(rate, 2), "rows": rows, "why": why}
