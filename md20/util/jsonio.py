"""Atomic JSON / file operations that behave the same on Windows and POSIX."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any


def atomic_write_json(data: Any, path: Path | str, *, backup: bool = True) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, dict):
        from .stamp import stamp_record
        data = {**data, "_md20": stamp_record()}
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=True, default=_default)
            fh.flush()
            os.fsync(fh.fileno())
        if backup and path.exists() and path.stat().st_size > 0:
            try:
                shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
            except OSError:
                pass
        # os.replace is atomic on POSIX and on Windows (MoveFileEx with REPLACE_EXISTING)
        # as long as the destination is not held open by another process.
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
    return path


def load_json(path: Path | str, default: Any = None, *, critical: bool = False) -> Any:
    """Load JSON, falling back to the .bak copy.  `critical=True` raises if both are corrupt."""
    path = Path(path)
    errors = []
    found = False
    for candidate in (path, path.with_suffix(path.suffix + ".bak")):
        if not candidate.exists() or candidate.stat().st_size == 0:
            continue
        found = True
        try:
            with open(candidate, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{candidate.name}: {type(exc).__name__}: {exc}")
    if critical and found:
        raise RuntimeError("狀態檔損毀（主檔與備份皆無法讀取）：" + " | ".join(errors))
    return {} if default is None else default


def atomic_copy(src: Path | str, dst: Path | str) -> Path:
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dst.name}.", suffix=".part", dir=str(dst.parent))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
    return dst


def _default(obj: Any):
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "tolist"):
        return obj.tolist()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)
