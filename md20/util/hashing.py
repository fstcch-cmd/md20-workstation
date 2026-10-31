"""Full and cheap file fingerprints.

The Colab engine re-hashed every chunk DCD in full on each resume (cost grew
linearly with trajectory size).  Here a *cheap fingerprint* (size + mtime +
SHA-256 of the first and last 64 KiB) is used for routine resume checks and
the full SHA-256 only once, when a stage is sealed.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

_EDGE = 64 * 1024


def sha256_file(path: Path | str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def cheap_fingerprint(path: Path | str) -> dict:
    p = Path(path)
    st = p.stat()
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        h.update(fh.read(_EDGE))
        if st.st_size > 2 * _EDGE:
            fh.seek(st.st_size - _EDGE)
        elif st.st_size > _EDGE:
            fh.seek(_EDGE)
        h.update(fh.read(_EDGE))
    return {"bytes": int(st.st_size), "mtime_ns": int(st.st_mtime_ns), "edge_sha256": h.hexdigest()}


def verify_cheap_fingerprint(path: Path | str, expected: dict) -> bool:
    p = Path(path)
    if not p.is_file():
        return False
    st = p.stat()
    if int(st.st_size) != int(expected.get("bytes", -1)):
        return False
    # mtime may legitimately change after a copy; only the content edges are authoritative.
    return cheap_fingerprint(p)["edge_sha256"] == expected.get("edge_sha256")
