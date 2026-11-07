"""micromamba is pinned and sha256-checked in both installers (D-117, supply_chain §2, REVIEW #19).

Pure text checks on installer/install.ps1 and installer/install.sh; the real download and hash check run in CI
(installer-windows / installer-macos jobs) because the development container cannot be relied on to reach GitHub releases.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PS1 = (ROOT / "installer" / "install.ps1").read_text(encoding="utf-8-sig")
SH = (ROOT / "installer" / "install.sh").read_text(encoding="utf-8")

SH_PLATFORMS = ["win-64", "osx-64", "osx-arm64", "linux-64", "linux-aarch64"]
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _sh_hashes() -> dict:
    block = SH[SH.index("micromamba_sha256()"):SH.index("sha256_of()")]
    return dict(re.findall(r'^\s*([a-z0-9-]+)\)\s+echo "([0-9a-fA-F]*)"', block, re.M))


def _ps1_hashes() -> dict:
    m = re.search(r"\$MambaSha256\s*=\s*@\{(.*?)\}", PS1, re.S)
    assert m, "install.ps1 has no $MambaSha256 table"
    return dict(re.findall(r'"([a-z0-9-]+)"\s*=\s*"([0-9a-fA-F]*)"', m.group(1)))


def _versions() -> tuple:
    sh = re.search(r'^MICROMAMBA_VERSION="([^"]+)"', SH, re.M)
    ps = re.search(r'^\$MambaVersion\s*=\s*"([^"]+)"', PS1, re.M)
    assert sh and ps
    return sh.group(1), ps.group(1)


def test_both_installers_pin_the_same_version():
    sh_v, ps_v = _versions()
    assert sh_v == ps_v
    assert re.fullmatch(r"2\.\d+\.\d+-\d+", sh_v), sh_v   # a stable 2.x tag of micromamba-releases, not "latest"


def test_every_platform_has_a_64_hex_sha256_and_windows_agrees():
    sh = _sh_hashes()
    assert set(sh) == set(SH_PLATFORMS)
    for plat, h in sh.items():
        assert HEX64.match(h), (plat, h)
    assert len(set(sh.values())) == len(sh)             # five different binaries, no copy-paste duplicate
    ps = _ps1_hashes()
    assert set(ps) == {"win-64"}
    assert HEX64.match(ps["win-64"])
    assert ps["win-64"] == sh["win-64"]                 # the two Windows paths must install the same file


def test_default_path_downloads_the_pinned_release_asset_not_latest():
    for text in (PS1, SH):
        assert "github.com/mamba-org/micromamba-releases/releases/download/" in text
    # every use of the unverified .../latest URL must sit behind the explicit override
    sh_latest = [m.start() for m in re.finditer(r"micro\.mamba\.pm/api/micromamba/", SH)]
    assert len(sh_latest) == 1
    assert SH.rindex('MD20_MICROMAMBA_LATEST', 0, sh_latest[0]) < sh_latest[0]
    ps_latest = [m.start() for m in re.finditer(r"micro\.mamba\.pm/api/micromamba/", PS1)]
    assert len(ps_latest) == 1
    assert PS1.rindex('MD20_MICROMAMBA_LATEST', 0, ps_latest[0]) < ps_latest[0]
    # the platform-specific latest URLs of the old install.sh are gone
    assert not re.search(r"micro\.mamba\.pm/api/micromamba/(osx|linux)-[a-z0-9]+/latest", SH)


def test_override_variable_exists_and_says_unverified():
    assert "MD20_MICROMAMBA_LATEST" in PS1 and "MD20_MICROMAMBA_LATEST" in SH
    assert "未驗證" in PS1 and "未驗證" in SH


def test_hash_is_checked_before_use_and_mismatch_stops_with_deletion():
    assert "Get-FileHash -Algorithm SHA256" in PS1
    assert PS1.index("Get-FileHash") < PS1.index("Move-Item -Force -Path $MambaPart")
    assert re.search(r"-ne \$MambaSha256\[", PS1)
    assert "Remove-Item -Force $MambaPart" in PS1 and "exit 4" in PS1
    assert re.search(r'sha256sum|shasum -a 256', SH)
    assert SH.index('got="$(sha256_of') < SH.index('mv -f "$part" "$dest"')
    assert 'rm -f "$part"' in SH and "exit 4" in SH
    # errors are bilingual (Chinese and English on the same message)
    assert "does not match the pinned value" in PS1 and "does not match the pinned value" in SH


def test_download_goes_to_a_part_file_and_failure_does_not_fall_back_to_latest():
    assert '"$Mamba.part"' in PS1 and 'part="$dest.part"' in SH
    assert "exit 5" in PS1 and "exit 5" in SH
    assert "不會改抓未驗證的最新版" in PS1 and "不會改抓未驗證的最新版" in SH


def test_powershell_51_compatible_download_and_hash_cmdlets():
    # no PowerShell 7-only syntax in the new block (`?.`, `??`, `-Parallel`); Invoke-WebRequest needs -UseBasicParsing on 5.1
    block = PS1[PS1.index("$MambaVersion"):PS1.index("if ($Gpu -eq \"auto\")")]
    assert "?." not in block and "??" not in block
    assert "-UseBasicParsing" in block


def test_old_fixes_are_intact():
    assert "$env:CONDA_PKGS_DIRS = $Pkgs" in PS1                 # D-38
    assert '"meeko~=0.5"' in PS1 and '"meeko~=0.5"' in SH         # cmd.exe redirection trap
    assert 'meeko>=0.5' not in PS1 and 'meeko>=0.5' not in SH
