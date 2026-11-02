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
