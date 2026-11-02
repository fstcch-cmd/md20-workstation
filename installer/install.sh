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

if [ "$IS_WIN" = 1 ]; then
  # Git Bash on Windows.  Default root %LOCALAPPDATA%\MD20; override with MD20_ROOT=/d/MD20 to use another drive.
  ROOT="${MD20_ROOT:-$(cygpath -u "${LOCALAPPDATA:-$USERPROFILE/AppData/Local}")/MD20}"
  mkdir -p "$ROOT"
  export MAMBA_ROOT_PREFIX="$(cygpath -w "$ROOT")"   # keep the package cache under the same root (not AppData\Roaming)
  FREE_GB=$(df -k "$ROOT" | awk 'NR==2{printf "%d", $4/1048576}')
  echo "安裝位置：$ROOT（可用空間 ${FREE_GB} GB；環境約需 6 GB）"
  if [ "${FREE_GB:-0}" -lt 8 ]; then
    echo "!! 可用空間不足 8 GB。請清出空間，或改裝到其他磁碟：  MD20_ROOT=/d/MD20 bash installer/install.sh"
    exit 2
  fi
  MAMBA="$ROOT/micromamba.exe"
  if [ ! -f "$MAMBA" ]; then
    echo "[1/4] 下載 micromamba (win-64) ..."
    curl -Ls https://micro.mamba.pm/api/micromamba/win-64/latest -o "$ROOT/micromamba.tar.bz2"
    tar -xjf "$ROOT/micromamba.tar.bz2" -C "$ROOT" Library/bin/micromamba.exe
    cp "$ROOT/Library/bin/micromamba.exe" "$MAMBA"
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
        echo "!! 驅動只支援 CUDA $DRV（< 11.8）：改用 OpenCL；更新驅動後可重跑。"; GPU=opencl
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
  echo "[3/4] 安裝 md20 ..."; "$MAMBA" run -p "$W_PREFIX" pip install --no-cache-dir "openmmforcefields>=0.14" "meeko>=0.5" gemmi -e "$W_PKG"
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
echo "安裝位置 Install location: $ROOT（可用空間 free ${FREE_GB} GB；環境約需 6 GB / needs about 6 GB）"
if [ "${FREE_GB:-0}" -lt 8 ]; then echo "!! 可用空間不足 8 GB / less than 8 GB free；可用 MD20_ROOT=/path 指定其他磁碟。"; exit 2; fi
SRC="$(cd "$HERE/.." && pwd)"
if [ ! -d "$SRC/.git" ]; then
  APP="$ROOT/app"
  if [ "$SRC" != "$APP" ]; then
    if [ -d "$APP" ]; then
      OLD="$ROOT/_to_delete/app-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$ROOT/_to_delete"; mv "$APP" "$OLD"
      echo "舊版程式已移到 previous version moved to: $OLD（確認新版可用後可自行刪除 / delete it yourself later）"
    fi
    echo "複製程式到 Copying the program to $APP ..."
    mkdir -p "$APP"; cp -R "$SRC/." "$APP/"
  fi
  SRC="$APP"
fi
if [ ! -x "$MAMBA" ]; then
  echo "[1/4] 下載 micromamba / downloading micromamba ..."
  case "$OS-$(uname -m)" in
    Darwin-arm64) URL=https://micro.mamba.pm/api/micromamba/osx-arm64/latest ;;
    Darwin-*)     URL=https://micro.mamba.pm/api/micromamba/osx-64/latest ;;
    Linux-aarch64) URL=https://micro.mamba.pm/api/micromamba/linux-aarch64/latest ;;
    *)            URL=https://micro.mamba.pm/api/micromamba/linux-64/latest ;;
  esac
  curl -fLs "$URL" | tar -xj -C "$ROOT" bin/micromamba
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
"$MAMBA" run -p "$PREFIX" python -m pip install --no-cache-dir "openmmforcefields>=0.14" "meeko>=0.5" gemmi -e "$SRC"
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
echo
echo "完成 Done."
echo "  圖形介面 GUI：雙擊桌面的 MD20-GUI.command（或 or: $GUI）"
echo "  命令列 Command line：$ROOT/md20 doctor | demo | pipeline ..."
