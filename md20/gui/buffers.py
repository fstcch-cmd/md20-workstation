"""Thread-safe buffers for live plots (pure Python, no NiceGUI needed).

The engine's `progress_cb` runs in a worker thread and appends heartbeats; the
GUI's `ui.timer` reads a snapshot on the event loop.  Only the last
`maxlen` points are kept so a 100 ns run never grows memory or plot size.
"""
from __future__ import annotations

import threading
from collections import deque
from typing import Any, Iterable

DEFAULT_MAXLEN = 2000


class RingBuffer:
    """Fixed-capacity FIFO: appending past `maxlen` drops the oldest items."""

    def __init__(self, maxlen: int = DEFAULT_MAXLEN):
        if int(maxlen) <= 0:
            raise ValueError("maxlen 必須為正整數")
        self.maxlen = int(maxlen)
        self._data: deque = deque(maxlen=self.maxlen)
        self._lock = threading.Lock()
        self._total = 0  # number of items ever appended (lets the GUI detect "nothing new")

    def append(self, item: Any) -> None:
        with self._lock:
            self._data.append(item)
            self._total += 1

    def extend(self, items: Iterable[Any]) -> None:
        with self._lock:
            for it in items:
                self._data.append(it)
                self._total += 1

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._total = 0

    def snapshot(self) -> list:
        with self._lock:
            return list(self._data)

    @property
    def total_appended(self) -> int:
        return self._total

    def __len__(self) -> int:
        return len(self._data)


class HeartbeatBuffer:
    """Keeps (x, temperature, potential) series from engine heartbeats.

    x is a monotonically increasing index across stages (heartbeats restart
    their step counters per stage), labelled with the stage name so plots can
    show where NVT ends and NPT starts.
    """

    FIELDS = ("temperature_k", "potential_kj_mol")

    def __init__(self, maxlen: int = DEFAULT_MAXLEN):
        self._buf = RingBuffer(maxlen)
        self._lock = threading.Lock()
        self._x = 0
        self.last: dict = {}

    @property
    def maxlen(self) -> int:
        return self._buf.maxlen

    def append(self, hb: dict) -> None:
        def num(v):
            try:
                f = float(v)
            except (TypeError, ValueError):
                return None
            return f if f == f and f not in (float("inf"), float("-inf")) else None  # drop NaN/inf
        with self._lock:
            self._x += 1
            x = self._x
            self.last = dict(hb)
        self._buf.append({"x": x, "stage": hb.get("stage", ""),
                          "temperature_k": num(hb.get("temperature_k")),
                          "potential_kj_mol": num(hb.get("potential_kj_mol"))})

    def clear(self) -> None:
        with self._lock:
            self._x = 0
            self.last = {}
        self._buf.clear()

    def points(self) -> list[dict]:
        return self._buf.snapshot()

    def series(self, field: str) -> list[list]:
        """[[x, y], …] for one field, skipping missing values — the shape ECharts' value axis wants."""
        if field not in self.FIELDS:
            raise KeyError(field)
        return [[p["x"], p[field]] for p in self._buf.snapshot() if p[field] is not None]

    def __len__(self) -> int:
        return len(self._buf)
