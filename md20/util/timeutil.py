from __future__ import annotations

import datetime as _dt


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_local(iso: str | None, fmt: str = "%m-%d %H:%M:%S") -> str:
    """UTC ISO stamp ("2026-11-02T14:51:30Z") → this computer's local time for display (D-67).  Files keep UTC."""
    if not iso:
        return ""
    try:
        t = _dt.datetime.strptime(str(iso).replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return str(iso)
    return t.astimezone().strftime(fmt)
