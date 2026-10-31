#!/usr/bin/env bash
# MD20 installer for macOS / Linux.  Usage: bash installer/install.sh [cuda|opencl|cpu]
set -euo pipefail
GPU="${1:-auto}"
ROOT="${HOME}/.local/share/MD20"; mkdir -p "$ROOT"
MAMBA="$ROOT/bin/micromamba"
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ ! -x "$MAMBA" ]; then
  echo "[1/4] 下載 micromamba ..."
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) URL=https://micro.mamba.pm/api/micromamba/osx-arm64/latest ;;
    Darwin-*)     URL=https://micro.mamba.pm/api/micromamba/osx-64/latest ;;
    *)            URL=https://micro.mamba.pm/api/micromamba/linux-64/latest ;;
  esac
  curl -Ls "$URL" | tar -xj -C "$ROOT" bin/micromamba
fi
if [ "$GPU" = auto ]; then
  if command -v nvidia-smi >/dev/null 2>&1; then GPU=cuda; else GPU=opencl; fi
fi
case "$(uname -s)" in
  Darwin) GPUYML="$HERE/../environment/macos.yml" ;;
  *) if [ "$GPU" = cuda ]; then GPUYML="$HERE/../environment/linux-cuda.yml"; else GPUYML="$HERE/../environment/windows-opencl.yml"; fi ;;
esac
PREFIX="$ROOT/envs/md20"
echo "[2/4] 建立環境 ($GPU) ..."; "$MAMBA" create -y -p "$PREFIX" -f "$HERE/../environment/base.yml" -f "$GPUYML"
echo "[3/4] 安裝 md20 ..."; "$MAMBA" run -p "$PREFIX" pip install -e "$HERE/.."
echo "[4/4] Doctor ..."; "$MAMBA" run -p "$PREFIX" md20 doctor
echo; echo "完成。之後執行：  $MAMBA run -p $PREFIX md20 <command>"
