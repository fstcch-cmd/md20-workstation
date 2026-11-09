"""GPU driver resolution: detect → decide → one-click download from the vendor's official site.

What Doctor only *diagnosed* ("driver too old") this module turns into an action the student can click:
  plan_drivers(hardware)  → DriverPlan per GPU: status (OK / UPDATE / FALLBACK / NONE), the CUDA level the installed
                            driver supports, the OpenMM build that matches it, and the official download.
  resolve_nvidia_download → NVIDIA's public driver-lookup service (the same one nvidia.com's "Download drivers" page
                            uses): product series/family ids by GPU name → newest WHQL package for this Windows.
  download_driver         → HTTPS download from an allow-listed vendor host into ~/Downloads, never executed by us
                            (driver installers need administrator rights and a reboot; the student runs the file).

Facts the decisions rest on (NVIDIA CUDA release notes, "CUDA Toolkit and Corresponding Driver Versions"):
  CUDA 12.4 needs driver ≥ 551.61 (Windows) / 550.54.14 (Linux); 12.0 ≥ 527.41 / 525.60.13; 11.8 ≥ 452.39 / 450.80.02.
conda-forge openmm for win-64 is CUDA-linked; MD20's installer picks `cuda-version` 12.4 or 11.8 from the driver, so a
student with an old driver has two honest options: update the driver (this module) or keep it and install the 11.8 build.
Network calls take an injectable `fetch` so every rule is testable offline; a lookup failure degrades to the official
download page, never to a guess.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from pathlib import Path

MD20_CUDA = "12.4"                       # what environment/windows-cuda.yml asks for
CUDA_MIN_DRIVER = {                      # CUDA toolkit → minimum driver (windows, linux)
    "12.4": ("551.61", "550.54.14"),
    "12.0": ("527.41", "525.60.13"),
    "11.8": ("452.39", "450.80.02"),
}
OFFICIAL_HOSTS = ("nvidia.com", "nvidia.cn", "geforce.com", "amd.com", "intel.com")
NVIDIA_LOOKUP = "https://www.nvidia.com/Download/API/lookupValueSearch.aspx"
NVIDIA_MANIFEST = "https://gfwsl.geforce.com/services_toolkit/services/com/nvidia/services/AjaxDriverService.php"
NVIDIA_PAGE = "https://www.nvidia.com/Download/index.aspx"
NVIDIA_APP = "https://www.nvidia.com/en-us/software/nvidia-app/"
AMD_AUTODETECT = "https://www.amd.com/en/support/download/drivers.html"
INTEL_DSA = "https://www.intel.com/content/www/us/en/support/detect.html"
NVIDIA_OS_IDS = {"win11": 135, "win10": 57, "linux64": 12}


@dataclass
class DriverPlan:
    vendor: str
    gpu: str
    driver: str | None
    status: str                          # OK | UPDATE | FALLBACK | NONE | UNKNOWN
    cuda_supported: str | None = None    # highest CUDA toolkit this driver can run (NVIDIA)
    env_cuda_version: str | None = None  # cuda-version the installer should use *without* updating the driver
    platform_now: str = ""               # what MD20 would use today (CUDA / OpenCL / CPU)
    download_url: str | None = None      # direct installer URL (official host) when resolved
    download_page: str | None = None     # official page / auto-detect tool when no direct URL
    package_version: str | None = None
    why: str = ""
    steps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ----------------------------------------------------------------------------- version helpers
def _vtuple(v: str | None) -> tuple[int, ...]:
    if not v:
        return ()
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:4])


def nvidia_driver_from_wmi(version: str | None) -> str | None:
    """Windows reports NVIDIA drivers as 31.0.15.5161 → the GeForce number is the last 5 digits: 551.61."""
    if not version:
        return None
    parts = version.split(".")
    if len(parts) == 4 and len(parts[2]) >= 2:
        tail = (parts[2][-1] + parts[3]).lstrip("0") if len(parts[3]) == 4 else None
        if tail and len(tail) >= 4:
            return f"{tail[:-2]}.{tail[-2:]}"
    if re.fullmatch(r"\d{3}\.\d{2,3}(\.\d+)?", version):
        return version
    return None


def cuda_supported_by_driver(driver: str | None, os_name: str = "windows") -> str | None:
    """Highest CUDA toolkit (from the table) the driver can run; None when the driver is unknown or older than 11.8."""
    d = _vtuple(driver)
    if not d:
        return None
    col = 0 if os_name.startswith("win") else 1
    for cuda in ("12.4", "12.0", "11.8"):
        if d >= _vtuple(CUDA_MIN_DRIVER[cuda][col]):
            return cuda
    return None


def env_cuda_version_for(cuda_supported: str | None) -> str | None:
    """Which conda `cuda-version` build to install for a driver we are NOT going to update."""
    if cuda_supported is None:
        return None
    return "12.4" if _vtuple(cuda_supported) >= (12, 4) else "11.8"


# ----------------------------------------------------------------------------- NVIDIA lookup
def http_fetch(url: str, timeout: float = 20.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "MD20-workstation/0.1 (driver lookup)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _norm(s: str) -> str:
    s = s.lower().replace("nvidia", "").replace("(r)", "").replace("(tm)", "")     # keep "laptop gpu": it distinguishes products
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _lookup_values(fetch, type_id: int, parent_id: int | None = None) -> list[tuple[int, str]]:
    url = f"{NVIDIA_LOOKUP}?TypeID={type_id}" + (f"&ParentID={parent_id}" if parent_id is not None else "")
    root = ET.fromstring(fetch(url).decode("utf-8", errors="ignore"))
    out = []
    for lv in root.iter("LookupValue"):
        name = (lv.findtext("Name") or "").strip()
        val = lv.findtext("Value")
        if name and val and val.strip().isdigit():
            out.append((int(val), name))
    return out


def match_product(gpu_name: str, candidates: list[tuple[int, str]]) -> tuple[int, str] | None:
    """Best name match: exact normalised name, else the longest candidate contained in the GPU name."""
    g = _norm(gpu_name)
    exact = [c for c in candidates if _norm(c[1]) == g]
    if exact:
        return exact[0]
    contained = [c for c in candidates if _norm(c[1]) and _norm(c[1]) in g]
    if contained:
        return max(contained, key=lambda c: len(_norm(c[1])))
    # series names look like "GeForce RTX 30 Series (Notebooks)": match the family prefix (e.g. "rtx 30")
    m = re.search(r"(gtx|rtx|mx|quadro|titan|tesla|rtx a)\s*(\d+)", g)
    if m:
        series = f"{m.group(1)} {m.group(2)[:2]}"
        notebook = "laptop" in gpu_name.lower() or "notebook" in gpu_name.lower() or "mobile" in gpu_name.lower()
        hits = [c for c in candidates if series in _norm(c[1]) and (("notebook" in _norm(c[1])) == notebook)]
        if hits:
            return hits[0]
    return None


def resolve_nvidia_download(gpu_name: str, *, windows: str = "win10", fetch=http_fetch) -> dict | None:
    """Newest WHQL (DCH) package for this GPU + Windows from NVIDIA's lookup service.  None when the GPU cannot be
    matched or the service fails — the caller then offers the official page instead of guessing."""
    try:
        families = _lookup_values(fetch, 2)                       # all product families (pfid) with their names
        fam = match_product(gpu_name, families)
        if fam is None:
            return None
        pfid = fam[0]
        series = _lookup_values(fetch, 3)                         # product series (psid)
        ser = match_product(gpu_name, series)
        psid = ser[0] if ser else 0
        q = {"func": "DriverManifestLookup", "pfid": pfid, "psid": psid, "osID": NVIDIA_OS_IDS.get(windows, 57),
             "languageCode": 1033, "beta": 0, "isWHQL": 1, "dltype": -1, "dch": 1, "upCRD": 0, "qnf": 0, "sort1": 0,
             "numberOfResults": 1}
        data = json.loads(fetch(f"{NVIDIA_MANIFEST}?{urllib.parse.urlencode(q)}").decode("utf-8", errors="ignore"))
        ids = data.get("IDS") or []
        if not ids:
            return None
        info = ids[0].get("downloadInfo") or {}
        url = info.get("DownloadURL") or ""
        if not url:
            return None
        if url.startswith("//"):
            url = "https:" + url
        return {"url": url, "version": info.get("Version"), "name": info.get("Name"), "release_date": info.get("ReleaseDateTime"),
                "product": fam[1], "series": ser[1] if ser else None}
    except Exception:  # noqa: BLE001 — lookup is best effort; the plan falls back to the official page
        return None


# ----------------------------------------------------------------------------- planning
def _windows_kind() -> str:
    if not sys.platform.startswith("win"):
        return "linux64"
    try:
        build = sys.getwindowsversion().build  # type: ignore[attr-defined]
        return "win11" if build >= 22000 else "win10"
    except Exception:  # noqa: BLE001
        return "win10"


def plan_drivers(hardware: dict, *, resolve=None, os_name: str | None = None) -> list[DriverPlan]:
    """One plan per GPU.  `resolve(gpu_name, windows=...)` is resolve_nvidia_download (injectable)."""
    os_name = os_name or ("windows" if sys.platform.startswith("win") else ("darwin" if sys.platform == "darwin" else "linux"))
    win_kind = _windows_kind() if os_name == "windows" else "linux64"
    gpus = [g for g in (hardware.get("gpus") or []) if g.get("name")]
    plans: list[DriverPlan] = []
    for g in gpus:
        vendor, name = (g.get("vendor") or "").upper(), str(g.get("name"))
        drv = g.get("driver")
        if vendor == "NVIDIA":
            if g.get("source") == "wmi":
                drv = nvidia_driver_from_wmi(drv) or drv
            cuda = cuda_supported_by_driver(drv, os_name)
            env_v = env_cuda_version_for(cuda)
            p = DriverPlan(vendor="NVIDIA", gpu=name, driver=drv, status="OK", cuda_supported=cuda, env_cuda_version=env_v)
            if cuda == MD20_CUDA:
                p.platform_now = "CUDA"
                p.why = f"驅動 {drv} 支援 CUDA {cuda}，與 MD20 的 OpenMM（cuda-version {MD20_CUDA}）相符；不需要更新。"
            else:
                p.status = "UPDATE"
                p.platform_now = "CUDA (cuda-version 11.8)" if cuda else "OpenCL"
                p.why = (f"驅動 {drv or '未知'} 最高支援 CUDA {cuda or '< 11.8'}，MD20 預設的 OpenMM 需要 CUDA {MD20_CUDA}"
                         f"（驅動 ≥ {CUDA_MIN_DRIVER[MD20_CUDA][0 if os_name == 'windows' else 1]}）。")
                p.steps = ["① 一鍵下載最新 WHQL 驅動（官方）→ 執行安裝（需管理員、重開機）→ 重跑安裝器（自動改用 CUDA 12.4）",
                           (f"② 不想動驅動：重跑安裝器加 -Cuda {env_v}（安裝對應此驅動的 OpenMM）" if env_v else
                            "② 不想動驅動：驅動太舊連 CUDA 11.8 都不支援，只能走 OpenCL 或 CPU")]
                if os_name == "windows" and resolve is not None:
                    hit = resolve(name, windows=win_kind)
                    if hit:
                        p.download_url, p.package_version = hit["url"], hit.get("version")
                        p.why += f" 官方最新套件：{hit.get('name') or ''} {hit.get('version') or ''}（{hit.get('product') or ''}）。"
                if not p.download_url:
                    p.download_page = NVIDIA_PAGE
                    p.why += " 自動查詢沒有對到這張卡，請用官方頁面選擇型號下載，或安裝 NVIDIA App 自動更新。"
            plans.append(p)
        elif vendor == "AMD":
            plans.append(DriverPlan(vendor="AMD", gpu=name, driver=drv, status="FALLBACK", platform_now="OpenCL",
                                    download_page=AMD_AUTODETECT,
                                    why="AMD 顯示卡在 Windows 走 OpenCL（Linux 可 HIP）；驅動更新請用 AMD 官方自動偵測工具（沒有公開的查詢 API 可一鍵對到型號）。",
                                    steps=["下載 AMD 自動偵測工具並執行 → 重跑 md20 doctor"]))
        elif vendor == "INTEL" or "intel" in name.lower():
            plans.append(DriverPlan(vendor="INTEL", gpu=name, driver=drv, status="FALLBACK", platform_now="OpenCL（內顯，慢）",
                                    download_page=INTEL_DSA,
                                    why="Intel 內顯只能走 OpenCL，速度接近 CPU；若筆電另有獨顯，請確認 MD20 不是被指派到內顯。",
                                    steps=["Intel Driver & Support Assistant 更新驅動（可選）", "有獨顯時：NVIDIA 控制面板 → 高效能處理器指派給 python.exe"]))
        else:
            plans.append(DriverPlan(vendor=vendor or "?", gpu=name, driver=drv, status="UNKNOWN", platform_now="CPU",
                                    why="無法辨識的顯示卡廠商；MD20 會用 CPU 平台。"))
    if not plans:
        plans.append(DriverPlan(vendor="-", gpu="（未偵測到顯示卡）", driver=None, status="NONE", platform_now="CPU",
                                why="沒有偵測到 GPU：MD20 以 CPU 執行（教學 tier 10 ns 約需一天）。真的要快：md.solvent: gbn2 或借用有獨顯的電腦。"))
    return plans


# ----------------------------------------------------------------------------- download
def _official(url: str) -> bool:
    host = urllib.parse.urlparse(url).hostname or ""
    return url.startswith("https://") and any(host == h or host.endswith("." + h) for h in OFFICIAL_HOSTS)


def download_driver(url: str, dest_dir: Path | str | None = None, *, fetch_stream=None, progress_cb=None) -> Path:
    """Download an installer from an official vendor host into dest_dir (default ~/Downloads).  Refuses other hosts.
    The file is NOT executed: the student double-clicks it (administrator rights, reboot)."""
    if not _official(url):
        raise ValueError(f"只從官方網域下載驅動（nvidia.com / amd.com / intel.com），拒絕：{url}")
    dest_dir = Path(dest_dir) if dest_dir else Path.home() / "Downloads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = Path(urllib.parse.urlparse(url).path).name or "driver-installer.exe"
    dest = dest_dir / name
    tmp = dest.with_suffix(dest.suffix + ".part")
    if fetch_stream is None:
        def fetch_stream(u):  # noqa: E306
            req = urllib.request.Request(u, headers={"User-Agent": "MD20-workstation/0.1"})
            r = urllib.request.urlopen(req, timeout=60)
            total = int(r.headers.get("Content-Length") or 0)
            def gen():
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        return
                    yield chunk
            return total, gen()
    total, chunks = fetch_stream(url)
    done = 0
    with open(tmp, "wb") as fh:
        for chunk in chunks:
            fh.write(chunk)
            done += len(chunk)
            if progress_cb:
                progress_cb({"bytes": done, "total": total, "pct": round(100 * done / total) if total else None})
    if done == 0 or (total and done != total):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"下載不完整（{done}/{total} bytes），已刪除。請重試或用官方頁面下載。")
    tmp.replace(dest)
    return dest


def installer_hint(plan: DriverPlan) -> str:
    """The exact installer flag for the 'keep my driver' path."""
    if plan.vendor != "NVIDIA":
        return "powershell -ExecutionPolicy Bypass -File installer\\install.ps1 -Gpu opencl"
    if plan.status == "OK":
        return "powershell -ExecutionPolicy Bypass -File installer\\install.ps1"
    if plan.env_cuda_version:
        return f"powershell -ExecutionPolicy Bypass -File installer\\install.ps1 -Cuda {plan.env_cuda_version}"
    return "powershell -ExecutionPolicy Bypass -File installer\\install.ps1 -Gpu opencl"
