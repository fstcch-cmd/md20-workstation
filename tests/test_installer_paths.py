"""Installer guards that only show up on real student machines (D-36, D-38)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PS1 = (ROOT / "installer" / "install.ps1").read_text(encoding="utf-8-sig")

# deepest file seen in the micromamba package cache on Windows (pytorch 2.14.1, pulled by openff-nagl), relative to <pkgs>
DEEPEST = (r"\https\conda.anaconda.org\conda-forge\win-64\pytorch-2.14.1-cpu_mkl_py311_h0314612_102\Lib\site-packages"
           r"\torch-2.14.1.dist-info\licenses\third_party\flash-attention\third_party\aiter\3rdparty\composable_kernel"
           r"\docs\LICENSE.rst")


def _pkgs_dir(root: str) -> str:
    """Python mirror of the install.ps1 rule."""
    tail = int(re.search(r"\$PkgTail = (\d+)", PS1).group(1))
    pkgs = root + r"\pkgs"
    return root[:2] + r"\MD20pkgs" if len(pkgs) + tail >= 260 else pkgs


def test_tail_constant_covers_deepest_known_file():
    tail = int(re.search(r"\$PkgTail = (\d+)", PS1).group(1))
    assert tail >= len(DEEPEST)


def test_cache_moves_to_short_dir_for_localappdata_and_paths_fit():
    for root in [r"C:\Users\user\AppData\Local\MD20", r"C:\Users\chencheh.hsieh\AppData\Local\MD20",
                 r"D:\a\_temp\MD20", r"C:\MD20"]:
        pkgs = _pkgs_dir(root)
        assert len(pkgs + DEEPEST) < 260, (root, pkgs)
    assert _pkgs_dir(r"C:\Users\user\AppData\Local\MD20") == r"C:\MD20pkgs"   # the MSI laptop that failed
    assert _pkgs_dir(r"C:\MD20") == r"C:\MD20\pkgs"


def test_installer_exports_pkgs_dir_and_cuda_env_has_no_linux_only_packages():
    assert "$env:CONDA_PKGS_DIRS = $Pkgs" in PS1
    cuda = (ROOT / "environment" / "windows-cuda.yml").read_text(encoding="utf-8")
    assert "ocl-icd-system" not in cuda   # does not exist on win-64; broke every NVIDIA install in v0.1.0a1 (D-36)


def test_windows_11_and_gpu_label_seen_on_the_msi_laptop():
    from md20.env.hardware import os_release, gpu_label
    assert os_release("Windows", "10", "10.0.26200") == "11"    # Windows 11 home 26200 was reported as "Windows 10"
    assert os_release("Windows", "10", "10.0.19045") == "10"
    assert os_release("Linux", "6.8.0", "#1 SMP") == "6.8.0"
    assert gpu_label("NVIDIA", "NVIDIA GeForce RTX 4060 Laptop GPU") == "NVIDIA GeForce RTX 4060 Laptop GPU"
    assert gpu_label("AMD", "Radeon RX 7600") == "AMD Radeon RX 7600"
    assert gpu_label(None, "Intel(R) UHD Graphics") == "Intel(R) UHD Graphics"


def test_shell_scripts_never_follow_a_variable_with_non_ascii():
    """macOS bash 3.2 reads `$ROOT（` as one unbound name (CI installer-macos, D-66)."""
    for p in ["installer/install.sh", "Install-MD20.command"]:
        s = (ROOT / p).read_text(encoding="utf-8")
        assert not re.search(r"\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7f]", s), p


def test_vina_executable_always_gets_cpu(monkeypatch, tmp_path):   # D-68
    import subprocess, os
    from md20.docking import vina_cli
    seen = {}

    def fake_run(cmd, timeout, flags, eco):
        seen["cmd"] = cmd
        out = cmd[cmd.index("--out") + 1]
        open(out, "w").write("MODEL 1\nREMARK VINA RESULT:    -6.100      0.000      0.000\nENDMDL\n")
        return subprocess.CompletedProcess(cmd, 0, "", ""), {"wall_s": 1.0, "cpu_s": 1.0, "effective_threads": 1.0}
    monkeypatch.setattr(vina_cli, "_run_measured", fake_run)
    from md20.env.resources import plan
    for mode in ("background", "balanced", "full"):
        monkeypatch.setenv("MD20_RESOURCE_MODE", mode)
        vina_cli.run_vina_cli("vina", "rec.pdbqt", ["L1", "L2"], (0, 0, 0), (20, 20, 20))
        c = seen["cmd"]
        assert int(c[c.index("--cpu") + 1]) == plan(mode).threads          # the user's choice reaches Vina
    n = os.cpu_count() or 1
    assert plan("background").threads <= max(1, round(n / 4)) and plan("full").threads == n


def test_vina_priority_follows_mode_on_windows(monkeypatch):   # D-70
    from md20.env import resources
    if resources.os.name != "nt":
        assert resources.child_creationflags("full") == 0
        return
    import subprocess
    assert resources.child_creationflags("full") == subprocess.NORMAL_PRIORITY_CLASS
    assert resources.child_creationflags("balanced") == subprocess.NORMAL_PRIORITY_CLASS
    assert resources.child_creationflags("background") == subprocess.IDLE_PRIORITY_CLASS


def test_desktop_gui_launcher_points_at_the_install():   # D-76
    """A copy of MD20-GUI.cmd on the Desktop resolves %~dp0 to the Desktop and cannot find micromamba.exe."""
    from pathlib import Path
    s = (Path(__file__).resolve().parents[1] / "installer" / "install.ps1").read_text(encoding="utf-8-sig")
    assert 'Copy-Item $Gui (Join-Path $Desktop' not in s
    assert 'call `"$Gui`"' in s


def test_windows_launchers_start_from_a_short_path():   # D-77
    """`micromamba run` prepends to PATH in a cmd script; a long user PATH made it fail with 'The input line is too long'."""
    from pathlib import Path
    s = (Path(__file__).resolve().parents[1] / "installer" / "install.ps1").read_text(encoding="utf-8-sig")
    assert s.count('set `"PATH=%SystemRoot%\\system32;') == 2      # md20.cmd and MD20-GUI.cmd


def test_openmmforcefields_is_pinned_exactly_everywhere():
    """D-95: PyPI yanked openmmforcefields 0.15.1 ("Missing deps in pyproject.toml") and it is the only
    PyPI release, so a range spec finds no version.  pip accepts a yanked release only for an exact `==` pin."""
    files = [ROOT / ".github" / "workflows" / "ci.yml", ROOT / "installer" / "install.ps1", ROOT / "installer" / "install.sh"]
    specs = []
    for f in files:
        specs += re.findall(r'"openmmforcefields([^"]*)"', f.read_text(encoding="utf-8-sig"))
    assert specs, "no openmmforcefields install command found"
    assert set(specs) == {"==0.15.1"}, specs
