"""Environment pinning guards (D-163, supply_chain §3).

Pure text checks: the installers and CI must build the environment from the same files and the same pip line,
and every conda package that has CI evidence of an exact version must be pinned with `==`.  Packages without
evidence are listed in PENDING_UNPINNED (see docs/_pending/D-163.md); the list may only shrink.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / "environment"
PS1 = (ROOT / "installer" / "install.ps1").read_text(encoding="utf-8-sig")
SH = (ROOT / "installer" / "install.sh").read_text(encoding="utf-8")
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

# conda specs with exact versions backed by repo evidence (DECISIONS: CI openmm-stack 5a3fa37/d879f2b runs)
PINNED = {"numpy": "2.4.6", "openff-toolkit": "0.18.0"}
# family pins that are intentionally minor-level (python 3.11 is the supported interpreter).
# D-172: cuda-version is intentionally NOT pinned — conda matches the driver's __cuda and picks an openmm build to fit,
# so students on different NVIDIA drivers each get a working GPU build without forcing a driver update.
FAMILY = {"python": "3.11"}
# D-171: openmm is a RANGE, not exact — 8.6.1 dropped CUDA<12.9 builds, so pinning it exactly forces every student
# onto a very new NVIDIA driver.  A range lets conda pick a build whose cuda-version fits the student's driver
# (CI reproducibility moves to a lock file).  This is intentional, not "awaiting a lock", so it is excluded from both.
RANGED = {"openmm": ">=8.5,<8.7"}
# no evidence in the repo of an exact version -> waiting for the CI lock artifact
PENDING_UNPINNED = {
    "pandas", "openpyxl", "scipy", "cryptography", "psutil", "matplotlib-base", "plotly", "rdkit", "pdbfixer",
    "mdtraj", "parmed", "pymbar", "openff-nagl", "openff-nagl-models", "lxml", "pdb2pqr", "gemmi", "propka",
    "nicegui", "pytest", "pip", "ambertools", "vina",
}


def _deps(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*-\s+([A-Za-z0-9_.-]+)\s*([<>=!~][^\s#]*)?", line)
        if m and not line.lstrip().startswith("- name"):
            out[m.group(1)] = m.group(2) or ""
    return out


def _all() -> dict:
    allv = {}
    for f in sorted(ENV.glob("*.yml")):
        for k, v in _deps(f).items():
            allv.setdefault(k, {})[f.name] = v
    return allv


def test_evidence_backed_packages_are_exact_everywhere():
    allv = _all()
    for pkg, ver in PINNED.items():
        assert pkg in allv, pkg
        for fname, spec in allv[pkg].items():
            assert spec == "==" + ver, (pkg, fname, spec)
    for pkg, ver in FAMILY.items():
        for fname, spec in allv[pkg].items():
            assert spec in ("=" + ver, "==" + ver), (pkg, fname, spec)


def test_openmm_is_ranged_everywhere_it_appears():
    allv = _all()
    for pkg, spec in RANGED.items():
        assert pkg in allv, pkg
        for fname, s in allv[pkg].items():
            assert s == spec, (pkg, fname, s)


def test_unpinned_list_matches_reality_and_never_grows():
    allv = _all()
    unpinned = {p for p, d in allv.items() if p not in FAMILY and p not in RANGED
                and any(not s.startswith("==") for s in d.values())}
    assert unpinned == PENDING_UNPINNED, (unpinned ^ PENDING_UNPINNED)


def test_every_openmm_environment_file_is_used_by_installers_and_ci():
    for gpu in ("windows-cuda", "windows-opencl"):
        assert gpu in PS1 or f"{gpu}.yml" in SH
    assert "windows-opencl.yml" in SH and "windows-cuda.yml" in SH
    for f in ("environment/windows-opencl.yml", "environment/macos.yml", "environment/linux-cuda.yml"):
        assert f in CI, f
    assert "environment\\base.yml" in PS1 and "environment/base.yml" in SH and "environment/base.yml" in CI
    # no installer or CI create/install line may bypass the shared files with an inline spec
    for text in (PS1, SH, CI):
        assert not re.search(r"create[^\n]*\b(openmm|numpy|rdkit)[=<>]", text)


def test_pip_line_is_identical_in_installers_and_ci():
    pat = re.compile(r'"openmmforcefields==[^"]+"\s+"meeko[^"]+"\s+gemmi')
    found = {}
    for name, text in (("ps1", PS1), ("sh", SH), ("ci", CI)):
        found[name] = set(pat.findall(text))
        assert found[name], name
    assert found["ps1"] == found["sh"] == found["ci"]


def test_ci_exports_explicit_lock_per_os_without_auto_commit():
    assert "env export -n md20 --explicit" in CI
    assert "name: lock-${{ runner.os }}" in CI
    assert "git commit" not in CI and "git push" not in CI


def test_cuda_version_is_not_pinned_and_driver_floors_are_defined():
    """D-172 回歸守衛（承第九個 session 的 D-170 守衛，隨 D-172 更新）：cuda-version 刻意
    不釘選——conda 依驅動的 __cuda 挑對應的 openmm GPU 建置，學生各種驅動都能用而不必更新。
    若有人把 cuda-version 釘回環境檔，本測試先紅；同時確認 drivers.py 的驅動底線表仍可用。"""
    allv = _all()
    # cuda 環境檔不得釘 cuda-version（釘了就會把舊/新驅動的學生擋在外面，正是 D-170 的坑）
    assert "cuda-version" not in allv, ("cuda-version should not be pinned (D-172)", allv.get("cuda-version"))
    # drivers.py 的 MD20_CUDA 仍是一個有定義驅動底線的 CUDA 版本（給 GUI/doctor 的更新建議用）
    from md20.env import drivers
    assert drivers.MD20_CUDA in drivers.CUDA_MIN_DRIVER, (drivers.MD20_CUDA, sorted(drivers.CUDA_MIN_DRIVER))
    win_floor, linux_floor = drivers.CUDA_MIN_DRIVER[drivers.MD20_CUDA]
    assert win_floor and linux_floor  # 兩個平台的驅動底線都要給，否則學生無從判斷要不要更新驅動
