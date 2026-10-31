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
  # Git Bash on Windows: use the win-64 micromamba.exe under %LOCALAPPDATA%\MD20
  ROOT="$(cygpath -u "${LOCALAPPDATA:-$USERPROFILE/AppData/Local}")/MD20"
  mkdir -p "$ROOT"
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
  # micromamba.exe wants Windows-style paths
  W_PREFIX="$(cygpath -w "$PREFIX")"; W_BASE="$(cygpath -w "$HERE/../environment/base.yml")"; W_GPU="$(cygpath -w "$GPUYML")"; W_PKG="$(cygpath -w "$HERE/..")"
  echo "[2/4] 建立環境 ($GPU) ..."; "$MAMBA" create -y -p "$W_PREFIX" -f "$W_BASE" -f "$W_GPU"
  echo "[3/4] 安裝 md20 ..."; "$MAMBA" run -p "$W_PREFIX" pip install -e "$W_PKG"
  echo "[4/4] Doctor ..."; "$MAMBA" run -p "$W_PREFIX" md20 doctor
  echo; echo "完成。之後執行：  \"$MAMBA\" run -p \"$W_PREFIX\" md20 <command>"
  echo "提示：也可用 PowerShell 版安裝器 installer\\install.ps1。"
  exit 0
fi

ROOT="${HOME}/.local/share/MD20"; mkdir -p "$ROOT"
MAMBA="$ROOT/bin/micromamba"
if [ ! -x "$MAMBA" ]; then
  echo "[1/4] 下載 micromamba ..."
  case "$OS-$(uname -m)" in
    Darwin-arm64) URL=https://micro.mamba.pm/api/micromamba/osx-arm64/latest ;;
    Darwin-*)     URL=https://micro.mamba.pm/api/micromamba/osx-64/latest ;;
    Linux-aarch64) URL=https://micro.mamba.pm/api/micromamba/linux-aarch64/latest ;;
    *)            URL=https://micro.mamba.pm/api/micromamba/linux-64/latest ;;
  esac
  curl -Ls "$URL" | tar -xj -C "$ROOT" bin/micromamba
fi
if [ "$GPU" = auto ]; then
  if command -v nvidia-smi >/dev/null 2>&1; then GPU=cuda; else GPU=opencl; fi
fi
case "$OS" in
  Darwin) GPUYML="$HERE/../environment/macos.yml" ;;
  *) if [ "$GPU" = cuda ]; then GPUYML="$HERE/../environment/linux-cuda.yml"; else GPUYML="$HERE/../environment/windows-opencl.yml"; fi ;;
esac
PREFIX="$ROOT/envs/md20"
echo "[2/4] 建立環境 ($GPU) ..."; "$MAMBA" create -y -p "$PREFIX" -f "$HERE/../environment/base.yml" -f "$GPUYML"
echo "[3/4] 安裝 md20 ..."; "$MAMBA" run -p "$PREFIX" pip install -e "$HERE/.."
echo "[4/4] Doctor ..."; "$MAMBA" run -p "$PREFIX" md20 doctor
echo; echo "完成。之後執行：  $MAMBA run -p $PREFIX md20 <command>"
