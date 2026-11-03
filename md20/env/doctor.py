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
from .hardware import probe_hardware, gpu_label
from .platforms import choose_platform, available_platforms, explain_rejection
from .winfix import suppress_windows_error_dialogs, diagnose_nvidia_files
from ..i18n import pick as tx, colon, paren

# module: (required, what it is for)
CORE_PACKAGES = {
    "openmm": (True, ("MD 引擎，必要", "MD engine, required", "MD エンジン、必須", "MD 엔진, 필수")),
    "pdbfixer": (True, ("受體修復，必要", "receptor repair, required", "受容体の修復、必須", "수용체 복구, 필수")),
    "rdkit": (True, ("配體化學，必要", "ligand chemistry, required", "リガンドの化学処理、必須", "리간드 화학, 필수")),
    "mdtraj": (True, ("軌跡分析，必要", "trajectory analysis, required", "トラジェクトリ解析、必須", "궤적 분석, 필수")),
    "numpy": (True, ("數值計算，必要", "numerics, required", "数値計算、必須", "수치 계산, 필수")),
    "pandas": (True, ("表格，必要", "tables, required", "表の処理、必須", "표 처리, 필수")),
    "matplotlib": (True, ("圖表，必要", "plots, required", "グラフ、必須", "그래프, 필수")),
    "openff.toolkit": (False, ("配體力場 OpenFF，預設路徑", "OpenFF ligand force field, default route",
                               "リガンド力場 OpenFF、既定の経路", "리간드 역장 OpenFF, 기본 경로")),
    "openff.nagl": (False, ("配體電荷 NAGL，預設路徑", "NAGL ligand charges, default route",
                            "リガンド電荷 NAGL、既定の経路", "리간드 전하 NAGL, 기본 경로")),
    "openmmforcefields": (False, ("把 GAFF 與 OpenFF 接到 OpenMM", "bridge from GAFF and OpenFF to OpenMM",
                                  "GAFF と OpenFF を OpenMM につなぐ", "GAFF와 OpenFF를 OpenMM에 연결")),
    "pymbar": (False, ("傘狀採樣的 WHAM 與 MBAR", "WHAM and MBAR for umbrella sampling",
                       "アンブレラサンプリングの WHAM と MBAR", "엄브렐라 샘플링용 WHAM과 MBAR")),
    "parmed": (False, ("匯出 GROMACS 檔案", "GROMACS export", "GROMACS 形式への書き出し", "GROMACS 내보내기")),
    "plotly": (False, ("互動圖表，選配", "interactive plots, optional", "インタラクティブなグラフ、任意", "대화형 그래프, 선택")),
    "nicegui": (False, ("GUI，選配", "GUI, optional", "GUI、任意", "GUI, 선택")),
}


@dataclass
class Finding:
    """One row of the check.  item, detail and fix are plain strings or (zh, en, ja, ko) tuples (D-74); texts that come
    from other modules (driver plans, platform hints) are recorded in Chinese and shown as recorded."""
    item: str | tuple
    severity: str          # OK | WARN | FAIL
    detail: str | tuple
    fix: str | tuple = ""

    def text(self, lang: str = "zh") -> dict:
        return {"item": tx(self.item, lang), "severity": self.severity, "detail": tx(self.detail, lang),
                "fix": tx(self.fix, lang)}


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

    def to_dict(self, lang: str = "zh") -> dict:
        """JSON form; finding texts are resolved to `lang` (Chinese by default, as recorded before D-74)."""
        d = asdict(self)
        d["findings"] = [f.text(lang) for f in self.findings]
        return d

    def to_markdown(self, lang: str = "zh") -> str:
        """Human-readable report in `lang` (zh, en, ja, ko).  Hint texts from the driver and platform modules stay in
        Chinese, as recorded."""
        hw = self.hardware
        c = colon(lang)

        def T(*four):
            return tx(four, lang)
        gpus = "; ".join(f"{gpu_label(g.get('vendor'), g.get('name'))} {g.get('vram_mb') or ''}MB" for g in hw['gpus'])
        power = hw.get('power', {}).get('on_ac', True)
        lines = [f"# {T('MD20 電腦診斷報告', 'MD20 computer check', 'MD20 パソコン診断レポート', 'MD20 컴퓨터 진단 보고서')}"
                 f"{paren(self.created_at, lang)}", "",
                 f"- {T('作業系統', 'Operating system', 'オペレーティングシステム', '운영체제')}{c}{hw['os']['system']} {hw['os']['release']} "
                 f"({hw['os']['machine']}), Python {hw['os']['python']}",
                 f"- {T('CPU 邏輯核心', 'CPU logical cores', 'CPU 論理コア数', 'CPU 논리 코어')}{c}{hw['cpu']['logical_cores']}  "
                 f"RAM{c}{hw.get('ram_gb')} GB  "
                 f"{T('可用磁碟', 'Free disk', '空きディスク容量', '사용 가능 디스크')}{c}{hw['disk'].get('free_gb')} GB",
                 f"- GPU{c}" + (gpus or T("沒有偵測到獨立顯示卡", "no discrete graphics card detected",
                                          "独立 GPU は検出されませんでした", "독립 그래픽 카드가 감지되지 않음")),
                 f"- {T('電源', 'Power', '電源', '전원')}{c}" + (
                     T("接上電源", "on mains", "AC 電源", "전원 연결") if power else
                     T("電池。效能會降低，建議接上電源", "battery, slower than on mains; plug in",
                       "バッテリー。性能が落ちるので電源につないでください", "배터리. 성능이 떨어지므로 전원을 연결하십시오")), ""]
        if self.platform:
            lines.append(f"- {T('使用的 OpenMM 平台', 'OpenMM platform used', '使用する OpenMM プラットフォーム', '사용 중인 OpenMM 플랫폼')}"
                         f"{c}{self.platform['name']} {self.platform.get('properties', {})}")
        if self.benchmark and self.benchmark.get("ns_per_day"):
            b = self.benchmark
            inner = T(f"{b['n_atoms']} 個原子，dt {b['timestep_fs']} fs", f"{b['n_atoms']} atoms, dt {b['timestep_fs']} fs",
                      f"{b['n_atoms']} 原子、dt {b['timestep_fs']} fs", f"원자 {b['n_atoms']}개, dt {b['timestep_fs']} fs")
            lines.append(f"- {T('效能測試', 'Benchmark', 'ベンチマーク', '벤치마크')}{c}{b['ns_per_day']:.1f} ns/day"
                         f"{paren(inner, lang)}")
        lines += ["", T("| 項目 | 狀態 | 說明 | 建議 |", "| Item | Status | Detail | Suggestion |",
                        "| 項目 | 状態 | 詳細 | 対処 |", "| 항목 | 상태 | 내용 | 권장 조치 |"), "|---|---|---|---|"]
        for f in self.findings:
            r = f.text(lang)
            lines.append(f"| {r['item']} | {r['severity']} | {r['detail']} | {r['fix']} |")
        return "\n".join(lines)


def _package_report() -> tuple[dict, list[Finding]]:
    out, findings = {}, []
    for mod, (required, label) in CORE_PACKAGES.items():
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
            findings.append(Finding(item=(f"套件 {mod}", f"Package {mod}", f"パッケージ {mod}", f"패키지 {mod}"),
                                    severity="FAIL" if required else "WARN",
                                    detail=(f"未安裝（{label[0]}）", f"not installed ({label[1]})",
                                            f"未インストール（{label[2]}）", f"설치되지 않음({label[3]})"),
                                    fix=("執行安裝器，或執行 `micromamba install -f environment/<os>.yml`。",
                                         "Run the installer, or `micromamba install -f environment/<os>.yml`.",
                                         "インストーラを実行するか、`micromamba install -f environment/<os>.yml` を実行してください。",
                                         "설치 프로그램을 실행하거나 `micromamba install -f environment/<os>.yml`을 실행하십시오.")))
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
               save: bool = True, lookup_drivers: bool = True) -> DoctorReport:
    suppress_windows_error_dialogs()
    hardware = probe_hardware(workdir)
    packages, findings = _package_report()
    verdict = diagnose_nvidia_files(hardware.get("nvidia_driver_files", {}))
    if verdict and "殘留" in verdict:
        findings.append(Finding(("NVIDIA 驅動檔案", "NVIDIA driver files", "NVIDIA ドライバのファイル", "NVIDIA 드라이버 파일"), "WARN",
                                ("nvopencl.dll 殘留，驅動不完整", "nvopencl.dll left over, driver incomplete",
                                 "nvopencl.dll が残っており、ドライバが不完全です", "nvopencl.dll이 남아 있고 드라이버가 불완전함"),
                                verdict))
    # driver plan: not only "too old" but the official download and the keep-my-driver alternative
    from .drivers import plan_drivers, resolve_nvidia_download, installer_hint
    drivers = plan_drivers(hardware, resolve=resolve_nvidia_download if lookup_drivers else None)
    for dp in drivers:
        sev = {"OK": "OK", "UPDATE": "WARN", "FALLBACK": "OK", "NONE": "WARN", "UNKNOWN": "WARN"}[dp.status]
        fix = []
        for lang, dl, page, inst in (("zh", "一鍵下載", "官方頁面", "安裝器指令"),
                                     ("en", "One-click download", "Official page", "Installer command"),
                                     ("ja", "ワンクリックでダウンロード", "公式ページ", "インストーラのコマンド"),
                                     ("ko", "원클릭 다운로드", "공식 페이지", "설치 프로그램 명령")):
            c = colon(lang)
            x = dp.why + ("\n" + "\n".join(dp.steps) if dp.steps else "")
            if dp.download_url:
                x += f"\n{dl}{c}md20 drivers download" + (paren(dp.package_version, lang) if dp.package_version else "")
            elif dp.download_page:
                x += f"\n{page}{c}{dp.download_page}"
            x += f"\n{inst}{c}{installer_hint(dp)}"
            fix.append(x)
        g = gpu_label(dp.vendor, dp.gpu)
        drv = (dp.driver,) * 4 if dp.driver else ("未知版本", "unknown version", "不明なバージョン", "알 수 없는 버전")
        findings.append(Finding((f"驅動 {g}", f"Driver {g}", f"ドライバ {g}", f"드라이버 {g}"), sev,
                                (f"{drv[0]}，目前平台 {dp.platform_now}", f"{drv[1]}, current platform {dp.platform_now}",
                                 f"{drv[2]}、現在のプラットフォーム {dp.platform_now}", f"{drv[3]}, 현재 플랫폼 {dp.platform_now}"),
                                tuple(fix)))
    hardware["driver_plans"] = [dp.to_dict() for dp in drivers]
    platform = None
    bench = None
    bench_item = ("效能測試", "Benchmark", "ベンチマーク", "벤치마크")
    gpu_item = ("GPU 加速", "GPU acceleration", "GPU による高速化", "GPU 가속")
    mm_item = ("OpenMM 平台", "OpenMM platform", "OpenMM プラットフォーム", "OpenMM 플랫폼")
    # hardware findings
    if (hardware.get("ram_gb") or 0) and hardware["ram_gb"] < 8:
        findings.append(Finding(("記憶體", "Memory", "メモリ", "메모리"), "WARN", f"{hardware['ram_gb']} GB",
                                ("建議至少 8 GB。系統很大時請把水盒邊距調小。",
                                 "At least 8 GB is recommended. For a large system, reduce the box padding.",
                                 "8 GB 以上を推奨します。大きな系では水ボックスの余白を小さくしてください。",
                                 "8 GB 이상을 권장합니다. 큰 계에서는 물 상자 여백을 줄이십시오.")))
    free = hardware.get("disk", {}).get("free_gb")
    if free is not None and free < 20:
        findings.append(Finding(("磁碟空間", "Disk space", "ディスク容量", "디스크 공간"), "WARN",
                                (f"剩餘 {free} GB", f"{free} GB free", f"残り {free} GB", f"{free} GB 남음"),
                                ("教學等級每個案例大約需要 5 到 15 GB，請先清出空間。",
                                 "One case at the teaching tier needs about 5 to 15 GB. Free up some space first.",
                                 "教育レベルでは 1 ケースに約 5 から 15 GB 必要です。先に空き容量を作ってください。",
                                 "교육 등급은 사례 하나에 약 5에서 15 GB가 필요합니다. 먼저 공간을 확보하십시오.")))
    if hardware.get("power", {}).get("has_battery") and not hardware["power"].get("on_ac", True):
        findings.append(Finding(("電源", "Power", "電源", "전원"), "WARN",
                                ("目前使用電池", "running on battery", "バッテリーで動作中", "배터리로 작동 중"),
                                ("長時間跑 MD 請接上電源。用電池時 CPU 與 GPU 會降頻，電腦也可能進入睡眠而中斷計算。",
                                 "Plug in for long MD runs. On battery the CPU and GPU slow down, and the computer may "
                                 "sleep and interrupt the run.",
                                 "長時間の MD は電源につないで実行してください。バッテリーでは CPU と GPU のクロックが下がり、"
                                 "スリープで計算が中断することもあります。",
                                 "긴 MD 계산은 전원을 연결하고 실행하십시오. 배터리로는 CPU와 GPU 클럭이 낮아지고, 절전 모드로 "
                                 "계산이 중단될 수도 있습니다.")))
    if packages.get("openmm", {}).get("installed"):
        try:
            choice = choose_platform()
            platform = choice.to_dict()
            for rej in choice.rejected:
                if rej["name"] in {"CUDA", "OpenCL", "HIP"}:
                    n = rej["name"]
                    findings.append(Finding((f"平台 {n}", f"Platform {n}", f"プラットフォーム {n}", f"플랫폼 {n}"), "WARN",
                                            rej["error"][:160], explain_rejection(rej, hardware)))
            if not choice.is_gpu:
                nm = choice.name
                findings.append(Finding(gpu_item, "WARN",
                                        (f"目前使用 {nm}（CPU）", f"using {nm} (CPU)", f"現在は {nm}（CPU）を使用",
                                         f"현재 {nm}(CPU) 사용"),
                                        ("可以跑，但速度大約只有 GPU 的 1/10 到 1/30。教學時請選 2 到 5 ns 的課堂設定。",
                                         "It runs, but at about 1/10 to 1/30 of GPU speed. For teaching, choose the 2 to "
                                         "5 ns classroom setting.",
                                         "計算はできますが、速度は GPU のおよそ 10 分の 1 から 30 分の 1 です。授業では 2 から 5 ns "
                                         "の授業用設定を選んでください。",
                                         "실행은 되지만 속도가 GPU의 약 1/10에서 1/30입니다. 수업에서는 2에서 5 ns의 수업 설정을 "
                                         "고르십시오.")))
            else:
                findings.append(Finding(gpu_item, "OK", f"{choice.name} {choice.properties}", ""))
            if do_benchmark:
                try:
                    bench = benchmark(choice.name, choice.properties, seconds=benchmark_seconds)
                    ns, na, dt = bench["ns_per_day"], bench["n_atoms"], bench["timestep_fs"]
                    findings.append(Finding(bench_item, "OK",
                                            (f"{ns} ns/day，{na} 個原子，dt {dt} fs", f"{ns} ns/day, {na} atoms, dt {dt} fs",
                                             f"{ns} ns/day、{na} 原子、dt {dt} fs", f"{ns} ns/day, 원자 {na}개, dt {dt} fs"), ""))
                    rec = recommend_tier(bench["ns_per_day"], n_atoms_benchmark=bench["n_atoms"])
                    bench["tier_recommendation"] = rec
                    rows = rec["rows"]
                    findings.append(Finding(("建議等級", "Recommended tier", "推奨レベル", "권장 등급"), "OK", rec["recommended"],
                                            ("，".join(f"{r['tier']}：{r['total_ns']} ns 約 {r['eta_hours']} 小時" for r in rows),
                                             ", ".join(f"{r['tier']}: {r['total_ns']} ns ≈ {r['eta_hours']} h" for r in rows),
                                             "、".join(f"{r['tier']}：{r['total_ns']} ns で約 {r['eta_hours']} 時間" for r in rows),
                                             ", ".join(f"{r['tier']}: {r['total_ns']} ns 약 {r['eta_hours']}시간" for r in rows))))
                except Exception as exc:  # noqa: BLE001
                    bench = {"error": f"{type(exc).__name__}: {str(exc)[:500]}", "platform": choice.name}
                    findings.append(Finding(bench_item, "WARN", bench["error"][:200],
                                            ("平台可以建立，但 PME 效能測試失敗。請把這一行回報。",
                                             "The platform can be created but the PME benchmark failed. Please report this line.",
                                             "プラットフォームは作成できましたが、PME のベンチマークに失敗しました。この行を報告してください。",
                                             "플랫폼은 만들어졌지만 PME 벤치마크가 실패했습니다. 이 줄을 알려 주십시오.")))
        except Exception as exc:  # noqa: BLE001
            findings.append(Finding(mm_item, "FAIL", str(exc)[:300],
                                    ("連 CPU 平台都建立失敗，表示 openmm 的安裝已損毀。請重新建立環境。",
                                     "Even the CPU platform failed, so the openmm installation is broken. Rebuild the environment.",
                                     "CPU プラットフォームさえ作成できないため、openmm のインストールが壊れています。環境を作り直してください。",
                                     "CPU 플랫폼조차 만들 수 없으므로 openmm 설치가 손상되었습니다. 환경을 다시 만드십시오.")))
    else:
        findings.append(Finding(mm_item, "FAIL",
                                ("openmm 未安裝，無法偵測平台", "openmm is not installed, so platforms cannot be probed",
                                 "openmm がインストールされていないため、プラットフォームを調べられません",
                                 "openmm이 설치되지 않아 플랫폼을 확인할 수 없음"),
                                ("請先完成環境安裝。", "Finish installing the environment first.",
                                 "先に環境のインストールを済ませてください。", "먼저 환경 설치를 마치십시오.")))
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
    h = max_hours
    why = ((f"以 {rate:.1f} ns/day 估算（已依系統大小換算），{chosen} 等級可在 {h:.0f} 小時內完成。",
            f"Estimated at {rate:.1f} ns/day, scaled to the system size. The {chosen} tier finishes within {h:.0f} h.",
            f"{rate:.1f} ns/day（系の大きさで換算）で見積もると、{chosen} レベルは {h:.0f} 時間以内に終わります。",
            f"{rate:.1f} ns/day(계 크기로 환산)로 추정하면 {chosen} 등급은 {h:.0f}시간 안에 끝납니다.")
           if best else
           (f"最小的 classroom 等級也超過 {h:.0f} 小時。建議把系統縮小（邊距 0.8 nm），或改用工作站排程。",
            f"Even the smallest classroom tier takes more than {h:.0f} h. Make the system smaller (padding 0.8 nm) or "
            "use a workstation queue.",
            f"最小の classroom レベルでも {h:.0f} 時間を超えます。系を小さくする（余白 0.8 nm）か、ワークステーションのキューを"
            "使ってください。",
            f"가장 작은 classroom 등급도 {h:.0f}시간을 넘습니다. 계를 줄이거나(여백 0.8 nm) 워크스테이션 대기열을 쓰십시오."))
    return {"recommended": chosen, "rate_ns_per_day": round(rate, 2), "rows": rows, "why": why}
