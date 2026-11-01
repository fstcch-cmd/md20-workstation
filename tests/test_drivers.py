"""Driver resolution: detect → decide → official download.  Offline: NVIDIA's lookup service is replaced by fixtures."""
import json
import urllib.parse

import pytest

from md20.env.drivers import (plan_drivers, cuda_supported_by_driver, env_cuda_version_for, nvidia_driver_from_wmi, match_product,
                              resolve_nvidia_download, download_driver, installer_hint, NVIDIA_PAGE, AMD_AUTODETECT, MD20_CUDA)


# ----------------------------------------------------------------------------- version table
def test_cuda_level_from_driver_windows_and_linux():
    assert cuda_supported_by_driver("551.61") == "12.4" and cuda_supported_by_driver("560.94") == "12.4"
    assert cuda_supported_by_driver("551.60") == "12.0"
    assert cuda_supported_by_driver("527.41") == "12.0" and cuda_supported_by_driver("472.12") == "11.8"
    assert cuda_supported_by_driver("452.38") is None and cuda_supported_by_driver(None) is None
    assert cuda_supported_by_driver("550.54.14", "linux") == "12.4" and cuda_supported_by_driver("550.54.13", "linux") == "12.0"
    assert env_cuda_version_for("12.4") == "12.4" and env_cuda_version_for("12.0") == "11.8" and env_cuda_version_for(None) is None


def test_wmi_driver_version_conversion():
    assert nvidia_driver_from_wmi("31.0.15.5161") == "551.61"
    assert nvidia_driver_from_wmi("30.0.14.7168") == "471.68"
    assert nvidia_driver_from_wmi("32.0.15.6094") == "560.94"
    assert nvidia_driver_from_wmi("551.61") == "551.61"
    assert nvidia_driver_from_wmi(None) is None and nvidia_driver_from_wmi("1.2") is None


# ----------------------------------------------------------------------------- plans
def _hw(*gpus):
    return {"gpus": list(gpus)}


def test_plan_old_driver_gives_update_with_download_and_keep_driver_path():
    hits = []
    def resolve(name, windows="win10"):
        hits.append((name, windows))
        return {"url": "https://us.download.nvidia.com/Windows/560.94/560.94-desktop-win10-win11-64bit-international-dch-whql.exe",
                "version": "560.94", "name": "GeForce Game Ready Driver", "product": "GeForce GTX 1060"}
    plans = plan_drivers(_hw({"vendor": "NVIDIA", "name": "NVIDIA GeForce GTX 1060", "driver": "456.71"}), resolve=resolve, os_name="windows")
    p = plans[0]
    assert p.status == "UPDATE" and p.cuda_supported == "11.8" and p.env_cuda_version == "11.8"
    assert p.download_url.startswith("https://us.download.nvidia.com/") and p.package_version == "560.94"
    assert "11.8" in p.steps[1] and "-Cuda 11.8" in installer_hint(p)
    assert hits and hits[0][0] == "NVIDIA GeForce GTX 1060"


def test_plan_new_driver_is_ok_without_lookup():
    called = []
    plans = plan_drivers(_hw({"vendor": "NVIDIA", "name": "NVIDIA GeForce RTX 4060 Laptop GPU", "driver": "31.0.15.6094", "source": "wmi"}),
                         resolve=lambda *a, **k: called.append(1), os_name="windows")
    p = plans[0]
    assert p.status == "OK" and p.driver == "560.94" and p.cuda_supported == MD20_CUDA and p.platform_now == "CUDA"
    assert not called and installer_hint(p).endswith("install.ps1")


def test_plan_lookup_failure_falls_back_to_official_page_not_a_guess():
    plans = plan_drivers(_hw({"vendor": "NVIDIA", "name": "NVIDIA GeForce GTX 1060", "driver": "456.71"}), resolve=lambda *a, **k: None, os_name="windows")
    assert plans[0].download_url is None and plans[0].download_page == NVIDIA_PAGE and "官方頁面" in plans[0].why


def test_plan_very_old_driver_has_no_cuda_env():
    p = plan_drivers(_hw({"vendor": "NVIDIA", "name": "GeForce GTX 960", "driver": "391.35"}), resolve=lambda *a, **k: None, os_name="windows")[0]
    assert p.status == "UPDATE" and p.env_cuda_version is None and p.platform_now == "OpenCL" and "-Gpu opencl" in installer_hint(p)


def test_plan_amd_intel_none():
    ps = plan_drivers(_hw({"vendor": "AMD", "name": "AMD Radeon RX 6600M", "driver": "31.0.21001"}, {"vendor": "Intel", "name": "Intel(R) UHD Graphics 630"}),
                      os_name="windows")
    assert ps[0].status == "FALLBACK" and ps[0].download_page == AMD_AUTODETECT and ps[0].platform_now == "OpenCL"
    assert ps[1].vendor == "INTEL" and "內顯" in ps[1].platform_now
    none = plan_drivers({"gpus": []}, os_name="windows")[0]
    assert none.status == "NONE" and none.platform_now == "CPU" and "gbn2" in none.why


# ----------------------------------------------------------------------------- NVIDIA lookup (fixtures)
FAMILIES = """<?xml version="1.0"?><LookupValueSearch><LookupValues>
<LookupValue ParentID="7"><Name>GeForce GTX 1060</Name><Value>861</Value></LookupValue>
<LookupValue ParentID="7"><Name>GeForce GTX 1060 with Max-Q Design</Name><Value>900</Value></LookupValue>
<LookupValue ParentID="129"><Name>GeForce RTX 4060 Laptop GPU</Name><Value>1030</Value></LookupValue>
<LookupValue ParentID="129"><Name>GeForce RTX 4060</Name><Value>1029</Value></LookupValue>
</LookupValues></LookupValueSearch>"""
SERIES = """<?xml version="1.0"?><LookupValueSearch><LookupValues>
<LookupValue><Name>GeForce 10 Series</Name><Value>101</Value></LookupValue>
<LookupValue><Name>GeForce 10 Series (Notebooks)</Name><Value>102</Value></LookupValue>
<LookupValue><Name>GeForce RTX 40 Series (Notebooks)</Name><Value>129</Value></LookupValue>
<LookupValue><Name>GeForce RTX 40 Series</Name><Value>128</Value></LookupValue>
</LookupValues></LookupValueSearch>"""


def _fake_fetch(seen):
    def fetch(url, timeout=20.0):
        seen.append(url)
        if "TypeID=2" in url:
            return FAMILIES.encode()
        if "TypeID=3" in url:
            return SERIES.encode()
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        assert q["func"] == "DriverManifestLookup" and q["isWHQL"] == "1" and q["dch"] == "1"
        return json.dumps({"IDS": [{"downloadInfo": {"DownloadURL": "//us.download.nvidia.com/Windows/560.94/560.94-win10-win11-dch-whql.exe",
                                                     "Version": "560.94", "Name": "GeForce Game Ready Driver", "ReleaseDateTime": "2024-08-20"}}]}).encode()
    return fetch


def test_match_product_prefers_exact_then_longest_contained_then_series():
    fams = [(861, "GeForce GTX 1060"), (900, "GeForce GTX 1060 with Max-Q Design"), (1030, "GeForce RTX 4060 Laptop GPU"), (1029, "GeForce RTX 4060")]
    assert match_product("NVIDIA GeForce GTX 1060", fams)[0] == 861
    assert match_product("NVIDIA GeForce GTX 1060 with Max-Q Design", fams)[0] == 900
    assert match_product("NVIDIA GeForce RTX 4060 Laptop GPU", fams)[0] == 1030
    assert match_product("NVIDIA GeForce RTX 4060", fams)[0] == 1029
    sers = [(101, "GeForce 10 Series"), (102, "GeForce 10 Series (Notebooks)"), (129, "GeForce RTX 40 Series (Notebooks)"), (128, "GeForce RTX 40 Series")]
    assert match_product("NVIDIA GeForce RTX 4060 Laptop GPU", sers)[0] == 129
    assert match_product("NVIDIA GeForce RTX 4070", sers)[0] == 128
    assert match_product("Unknown Accelerator 9000", fams) is None


def test_resolve_nvidia_download_from_lookup_service():
    seen = []
    hit = resolve_nvidia_download("NVIDIA GeForce RTX 4060 Laptop GPU", windows="win11", fetch=_fake_fetch(seen))
    assert hit["url"] == "https://us.download.nvidia.com/Windows/560.94/560.94-win10-win11-dch-whql.exe"
    assert hit["version"] == "560.94" and hit["product"] == "GeForce RTX 4060 Laptop GPU" and "Notebooks" in hit["series"]
    manifest = [u for u in seen if "DriverManifestLookup" in u][0]
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(manifest).query))
    assert q["pfid"] == "1030" and q["psid"] == "129" and q["osID"] == "135"


def test_resolve_returns_none_on_service_error_or_unknown_gpu():
    def broken(url, timeout=20.0):
        raise OSError("offline")
    assert resolve_nvidia_download("NVIDIA GeForce GTX 1060", fetch=broken) is None
    assert resolve_nvidia_download("Matrox G200", fetch=_fake_fetch([])) is None


# ----------------------------------------------------------------------------- download
def test_download_only_from_official_hosts_and_verifies_length(tmp_path):
    with pytest.raises(ValueError):
        download_driver("https://evil.example.com/nvidia.com/driver.exe", tmp_path)
    with pytest.raises(ValueError):
        download_driver("http://us.download.nvidia.com/driver.exe", tmp_path)          # https only
    body = b"MZ" + b"x" * 1000
    events = []
    dest = download_driver("https://us.download.nvidia.com/Windows/560.94/driver.exe", tmp_path,
                           fetch_stream=lambda u: (len(body), iter([body[:500], body[500:]])), progress_cb=events.append)
    assert dest.name == "driver.exe" and dest.read_bytes() == body and events[-1]["pct"] == 100
    with pytest.raises(RuntimeError):
        download_driver("https://us.download.nvidia.com/Windows/560.94/short.exe", tmp_path,
                        fetch_stream=lambda u: (2000, iter([b"x" * 100])))
    assert not (tmp_path / "short.exe").exists() and not list(tmp_path.glob("*.part"))
