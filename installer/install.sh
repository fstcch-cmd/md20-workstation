#!/usr/bin/env bash
# MD20 installer for macOS / Linux / Windows Git Bash (MINGW/MSYS).
# Usage: bash installer/install.sh [cuda|opencl|cpu]
set -euo pipefail
GPU="${1:-auto}"
HERE="$(cd "$(dirname "$0")" && pwd)"
OS="$(uname -s)"
case "$OS" in
  MINGW*|MSYS*|CYGWIN*) IS_WIN=1 ;;
  *) IS_WIN=0 ;;
esac

# ---------------------------------------------------------------------------- micromamba pin (D-117)
# micromamba is pinned to one release and its sha256 is verified before use (the old URL .../latest gave every student
# whatever was newest that day, unverified).  Source: GitHub mamba-org/micromamba-releases, asset "micromamba-<platform>"
# (a single executable; each official .sha256 asset matches the hash below).  Keep in sync with install.ps1
# (tests/test_installer_pins.py).  MD20_MICROMAMBA_LATEST=1 is the explicit, unverified escape hatch (the previous behaviour).
MICROMAMBA_VERSION="2.10.0-0"
micromamba_sha256() {
  case "$1" in
    win-64)        echo "f8b4284bd4eb1134122eaf93b3ea6c7be567e596de5829e1a6f478e34e41974a" ;;
    osx-64)        echo "8421462a1ef1df9f7acd114f9e2a24c1332ce4f4e29f44465b4acb44e2755172" ;;
    osx-arm64)     echo "c547639f5caf742236641c362746abb4a3505774753ecd08fe341643670c4c01" ;;
    linux-64)      echo "701f39c06f8e6a670a0e186c8479b9e5c0502a2f0cda6cef65d83bdd2875e8bd" ;;
    linux-aarch64) echo "3bb56786e21b9b24024f599fe9185b4a59dc3f9f59937a42311ee583adbbb23c" ;;
    *)             echo "" ;;
  esac
}
sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else echo ""; fi
}
# fetch_micromamba <platform> <destination file> <member inside the legacy latest .tar.bz2>
fetch_micromamba() {
  local plat="$1" dest="$2" member="$3"
  mkdir -p "$(dirname "$dest")"
  if [ "${MD20_MICROMAMBA_LATEST:-}" = "1" ]; then
    echo "!! MD20_MICROMAMBA_LATEST=1：下載最新版 micromamba，未驗證 sha256 / UNVERIFIED: latest micromamba, no sha256 check"
    local lt="$(dirname "$dest")/mamba-latest"; mkdir -p "$lt"
    curl -fLs "https://micro.mamba.pm/api/micromamba/$plat/latest" -o "$lt/micromamba.tar.bz2"
    tar -xjf "$lt/micromamba.tar.bz2" -C "$lt" "$member"
    cp "$lt/$member" "$dest"; chmod +x "$dest"
    return 0
  fi
  local want url part got
  want="$(micromamba_sha256 "$plat")"
  if [ -z "$want" ]; then echo "!! 沒有 $plat 的釘選 micromamba / no pinned micromamba for platform $plat"; exit 4; fi
  url="https://github.com/mamba-org/micromamba-releases/releases/download/$MICROMAMBA_VERSION/micromamba-$plat"
  part="$dest.part"
  echo "    micromamba ${MICROMAMBA_VERSION}（釘選版本，驗證 sha256 / pinned, sha256 verified）: $url"
  if ! curl -fSL --retry 3 -o "$part" "$url"; then
    rm -f "$part"
    echo "!! 下載 micromamba 失敗 / Download of micromamba failed: $url"
    echo "   請檢查網路後重跑安裝器（不會改抓未驗證的最新版）。 / Check the network and rerun; the installer does not fall back to an unverified latest build."
    exit 5
  fi
  got="$(sha256_of "$part")"
  if [ -z "$got" ]; then
    rm -f "$part"
    echo "!! 找不到 sha256sum 或 shasum，無法驗證 micromamba，已刪除下載檔。 / Neither sha256sum nor shasum found; cannot verify micromamba, the download was deleted."
    exit 4
  fi
  if [ "$got" != "$want" ]; then
    rm -f "$part"
    echo "!! micromamba 的 sha256 與釘選值不符，已刪除該檔，未使用。 / micromamba sha256 does not match the pinned value; the file was deleted and not used."
    echo "   版本 version: $MICROMAMBA_VERSION  平台 platform: $plat"
    echo "   預期 expected: $want"
    echo "   實際 got:      $got"
    echo "   可能是下載被中斷或被代理改寫；請換網路重試並回報開發者。 / The download may be truncated or rewritten by a proxy; retry on another network and tell the developer."
    exit 4
  fi
  chmod +x "$part"; mv -f "$part" "$dest"
}

if [ "$IS_WIN" = 1 ]; then
  # Git Bash on Windows.  Default root %LOCALAPPDATA%\MD20; override with MD20_ROOT=/d/MD20 to use another drive.
  ROOT="${MD20_ROOT:-$(cygpath -u "${LOCALAPPDATA:-$USERPROFILE/AppData/Local}")/MD20}"
  mkdir -p "$ROOT"
  export MAMBA_ROOT_PREFIX="$(cygpath -w "$ROOT")"   # keep the package cache under the same root (not AppData\Roaming)
  FREE_GB=$(df -k "$ROOT" | awk 'NR==2{printf "%d", $4/1048576}')
  echo "安裝位置：${ROOT}（可用空間 ${FREE_GB} GB；環境約需 6 GB）"
  if [ "${FREE_GB:-0}" -lt 8 ]; then
    echo "!! 可用空間不足 8 GB。請清出空間，或改裝到其他磁碟：  MD20_ROOT=/d/MD20 bash installer/install.sh"
    exit 2
  fi
  MAMBA="$ROOT/micromamba.exe"
  if [ ! -f "$MAMBA" ]; then
    echo "[1/4] 下載 micromamba (win-64) ..."
    fetch_micromamba win-64 "$MAMBA" Library/bin/micromamba.exe
  fi
  if [ "$GPU" = auto ]; then
    if command -v nvidia-smi >/dev/null 2>&1 || [ -f "/c/Windows/System32/nvidia-smi.exe" ]; then GPU=cuda; else GPU=opencl; fi
  fi
  case "$GPU" in cuda) GPUYML="$HERE/../environment/windows-cuda.yml" ;; *) GPUYML="$HERE/../environment/windows-opencl.yml"; export CONDA_OVERRIDE_CUDA=12.4 ;; esac
  PREFIX="$ROOT/envs/md20"
  if [ "$GPU" = cuda ]; then
    SMI="$(command -v nvidia-smi || echo /c/Windows/System32/nvidia-smi.exe)"
    DRV="$("$SMI" 2>/dev/null | sed -n 's/.*CUDA Version: *\([0-9][0-9]*\.[0-9]*\).*/\1/p' | head -1)"
    if [ -n "$DRV" ]; then
      MAJ=${DRV%%.*}; MIN=${DRV#*.}
      if [ "$MAJ" -lt 11 ] || { [ "$MAJ" -eq 11 ] && [ "$MIN" -lt 8 ]; }; then
        echo "!! 驅動只支援 CUDA ${DRV}（< 11.8）：改用 OpenCL；更新驅動後可重跑。"; GPU=opencl
        GPUYML="$HERE/../environment/windows-opencl.yml"; export CONDA_OVERRIDE_CUDA=12.4
      else
        if [ "$MAJ" -lt 12 ]; then CV=11.8; elif [ "$MAJ" -gt 12 ] || [ "$MIN" -ge 4 ]; then CV=12.4; else CV=$DRV; fi
        sed "s/cuda-version=[0-9.]*/cuda-version=$CV/" "$GPUYML" > "$ROOT/windows-cuda-$CV.yml"; GPUYML="$ROOT/windows-cuda-$CV.yml"
        echo "驅動支援 CUDA $DRV → 使用 cuda-version=$CV"
      fi
    fi
  fi
  # micromamba.exe wants Windows-style paths
  W_PREFIX="$(cygpath -w "$PREFIX")"; W_BASE="$(cygpath -w "$HERE/../environment/base.yml")"; W_GPU="$(cygpath -w "$GPUYML")"; W_PKG="$(cygpath -w "$HERE/..")"
  # pip and conda use %TEMP% (usually on C:); keep all scratch under the install root
  mkdir -p "$ROOT/tmp"; export TMP="$(cygpath -w "$ROOT/tmp")"; export TEMP="$TMP"; export TMPDIR="$TMP"; export PIP_CACHE_DIR="$(cygpath -w "$ROOT/pipcache")"
  if [ -d "$PREFIX/conda-meta" ]; then
    echo "[2/4] 環境已存在，補齊套件 ($GPU) ..."; "$MAMBA" install -y -p "$W_PREFIX" -f "$W_BASE" -f "$W_GPU"
  else
    echo "[2/4] 建立環境 ($GPU) ..."; "$MAMBA" create -y -p "$W_PREFIX" -f "$W_BASE" -f "$W_GPU"
  fi
  echo "[3/4] 安裝 md20 ..."; "$MAMBA" run -p "$W_PREFIX" pip install --no-cache-dir "openmmforcefields==0.15.1" "meeko~=0.5" gemmi -e "$W_PKG"
  "$MAMBA" run -p "$W_PREFIX" md20 setup-vina || echo "!! Vina 執行檔下載失敗；docking 前請重跑 md20 setup-vina"
  echo "[4/4] Doctor ..."; "$MAMBA" run -p "$W_PREFIX" md20 doctor
  echo; echo "完成。之後執行：  \"$MAMBA\" run -p \"$W_PREFIX\" md20 <command>"
  echo "提示：也可用 PowerShell 版安裝器 installer\\install.ps1。"
  exit 0
fi

# ---------------------------------------------------------------------------- macOS / Linux (D-66)
# Same layout as Windows: program copied to $ROOT/app (a release ZIP is usually in Downloads and may be deleted),
# environment in $ROOT/envs/md20, launchers $ROOT/md20 (command line) and MD20-GUI.command on the Desktop.
# Nothing is deleted: a previous $ROOT/app is moved to $ROOT/_to_delete/app-<time> (user rule, D-37).
ROOT="${MD20_ROOT:-${HOME}/MD20}"; mkdir -p "$ROOT"
export MAMBA_ROOT_PREFIX="$ROOT"
MAMBA="$ROOT/bin/micromamba"
FREE_GB=$(df -k "$ROOT" | awk 'NR==2{printf "%d", $4/1048576}')
echo "安裝位置 Install location: ${ROOT}（可用空間 free ${FREE_GB} GB；環境約需 6 GB / needs about 6 GB）"
if [ "${FREE_GB:-0}" -lt 8 ]; then echo "!! 可用空間不足 8 GB / less than 8 GB free；可用 MD20_ROOT=/path 指定其他磁碟。"; exit 2; fi
SRC="$(cd "$HERE/.." && pwd)"
if [ ! -d "$SRC/.git" ]; then
  APP="$ROOT/app"
  if [ "$SRC" != "$APP" ]; then
    if [ -d "$APP" ]; then
      OLD="$ROOT/_to_delete/app-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$ROOT/_to_delete"; mv "$APP" "$OLD"
      echo "舊版程式已移到 previous version moved to: ${OLD}（確認新版可用後可自行刪除 / delete it yourself later）"
    fi
    echo "複製程式到 Copying the program to $APP ..."
    mkdir -p "$APP"; cp -R "$SRC/." "$APP/"
  fi
  SRC="$APP"
fi
if [ ! -x "$MAMBA" ]; then
  echo "[1/4] 下載 micromamba / downloading micromamba ..."
  case "$OS-$(uname -m)" in
    Darwin-arm64) MM_PLAT=osx-arm64 ;;
    Darwin-*)     MM_PLAT=osx-64 ;;
    Linux-aarch64) MM_PLAT=linux-aarch64 ;;
    *)            MM_PLAT=linux-64 ;;
  esac
  fetch_micromamba "$MM_PLAT" "$MAMBA" bin/micromamba
fi
if [ "$GPU" = auto ]; then
  if command -v nvidia-smi >/dev/null 2>&1; then GPU=cuda; else GPU=opencl; fi
fi
case "$OS" in
  Darwin) GPUYML="$SRC/environment/macos.yml" ;;
  *) if [ "$GPU" = cuda ]; then GPUYML="$SRC/environment/linux-cuda.yml"; else GPUYML="$SRC/environment/windows-opencl.yml"; export CONDA_OVERRIDE_CUDA=12.4; fi ;;
esac
PREFIX="$ROOT/envs/md20"
mkdir -p "$ROOT/tmp"; export TMPDIR="$ROOT/tmp"; export PIP_CACHE_DIR="$ROOT/pipcache"
if [ -d "$PREFIX/conda-meta" ]; then
  echo "[2/4] 環境已存在，補齊套件 / updating the environment ($GPU) ..."; "$MAMBA" install -y -p "$PREFIX" -f "$SRC/environment/base.yml" -f "$GPUYML"
else
  echo "[2/4] 建立環境 / creating the environment ($GPU) ..."; "$MAMBA" create -y -p "$PREFIX" -f "$SRC/environment/base.yml" -f "$GPUYML"
fi
echo "[3/4] 安裝 md20 / installing md20 ..."
"$MAMBA" run -p "$PREFIX" python -m pip install --no-cache-dir "openmmforcefields==0.15.1" "meeko~=0.5" gemmi -e "$SRC"
"$MAMBA" run -p "$PREFIX" md20 setup-vina || echo "!! Vina 下載失敗 / Vina download failed：稍後執行 run later: $ROOT/md20 setup-vina"
# launchers
cat > "$ROOT/md20" <<EOS
#!/usr/bin/env bash
export MAMBA_ROOT_PREFIX="$ROOT"
exec "$MAMBA" run -p "$PREFIX" md20 "\$@"
EOS
chmod +x "$ROOT/md20"
GUI="$ROOT/MD20-GUI.command"
cat > "$GUI" <<EOS
#!/usr/bin/env bash
echo "MD20 GUI: http://127.0.0.1:8020  （關閉此視窗即停止 / close this window to stop）"
"$ROOT/md20" gui
EOS
chmod +x "$GUI"
if [ -d "$HOME/Desktop" ]; then cp "$GUI" "$HOME/Desktop/MD20-GUI.command"; chmod +x "$HOME/Desktop/MD20-GUI.command"; fi
echo "[4/4] Doctor ..."; "$ROOT/md20" doctor
if [ "${MD20_WITH_FOLD:-}" = "1" ]; then   # D-85: also install peptide folding (several GB) and fold one test peptide
  echo "[+] 胜肽摺疊工具 Peptide folding (OmegaFold) ..."
  "$ROOT/md20" setup-fold --engine omegafold --yes --warmup || echo "!! 摺疊工具沒有裝好；之後雙擊 Install-Folding.command。 / Folding was not installed; double-click Install-Folding.command later."
fi
echo
echo "完成 Done."
echo "  圖形介面 GUI：雙擊桌面的 MD20-GUI.command（或 or: ${GUI}）"
echo "  命令列 Command line：$ROOT/md20 doctor | demo | pipeline ..."
