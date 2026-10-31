"""Cross-platform advisory file lock.

Windows has no `fcntl`; use `msvcrt.locking` there.  Falls back to a lock
directory (mkdir is atomic everywhere) when neither primitive is usable.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

try:  # POSIX
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover - Windows
    fcntl = None
try:  # Windows
    import msvcrt  # type: ignore
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None


class FileLock:
    def __init__(self, path: Path | str, timeout: float = 30.0, poll: float = 0.1):
        self.path = Path(path)
        self.timeout = float(timeout)
        self.poll = float(poll)
        self._fh = None
        self._dir_lock = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        if fcntl is not None or msvcrt is not None:
            self._fh = open(self.path, "a+", encoding="utf-8")
            while True:
                try:
                    if fcntl is not None:
                        fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    else:
                        msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                    return self
                except OSError:
                    if time.monotonic() > deadline:
                        self._fh.close()
                        self._fh = None
                        raise TimeoutError(f"無法取得檔案鎖：{self.path}")
                    time.sleep(self.poll)
        # directory fallback
        self._dir_lock = self.path.with_suffix(self.path.suffix + ".lockdir")
        while True:
            try:
                self._dir_lock.mkdir()
                return self
            except FileExistsError:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"無法取得目錄鎖：{self._dir_lock}")
                time.sleep(self.poll)

    def __exit__(self, *exc):
        if self._fh is not None:
            try:
                if fcntl is not None:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
                else:
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                self._fh.close()
                self._fh = None
        if self._dir_lock is not None:
            try:
                self._dir_lock.rmdir()
            except OSError:
                pass
            self._dir_lock = None
        return False


IS_WINDOWS = sys.platform.startswith("win")
