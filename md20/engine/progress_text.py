"""One readable progress line for the command window (D-57): stage, percent, temperature, time left, measured speed."""
from __future__ import annotations


def _dur(s: float) -> str:
    m = int(s // 60)
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else (f"{m} min" if m else f"{int(s)} s")


class StageMeter:
    """Feed progress events; `line(ev)` returns a text line or None.  The rate uses the first and the latest heartbeat
    of the current stage, so a resumed stage (clock restarted) is handled."""

    def __init__(self):
        self.key = None
        self.steps0 = 0
        self.t0 = 0.0

    def line(self, ev: dict) -> str | None:
        st = ev.get("stage")
        if ev.get("total_steps") and "completed_local_steps" in ev:
            key = (ev.get("case_id"), st)
            el = float(ev.get("elapsed_s") or 0.0)
            if key != self.key or el < self.t0:
                self.key, self.steps0, self.t0 = key, ev["completed_local_steps"], el
            done, tot = ev["completed_local_steps"], ev["total_steps"]
            parts = [f"[{st}] {100.0 * done / tot:5.1f} %"]
            if ev.get("temperature_k") is not None:
                parts.append(f"T {float(ev['temperature_k']):.1f} K")
            ds, dt = done - self.steps0, el - self.t0
            if ds > 0 and dt > 0:
                rate = ds / dt
                parts.append(f"{_dur((tot - done) / rate)} left in stage")
                if ev.get("timestep_fs"):
                    parts.append(f"{rate * float(ev['timestep_fs']) * 1e-6 * 86400:.0f} ns/day")
            return "  " + " | ".join(parts)
        if st == "umbrella" and ev.get("window") is not None:
            n = ev.get("n_windows", ev.get("n"))
            return f"  [umbrella] window {ev['window']}" + (f" of {n}" if n else "")
        if st == "smd" and ev.get("force") is not None:
            r = ev.get("r_nm", ev.get("r0"))
            return f"  [smd] r {float(r):.3f} nm | force {float(ev['force']):.0f} kJ/mol/nm" if r is not None else None
        if st == "docking":
            return f"  [docking] {ev.get('ligand', '')} {ev.get('i', '')} of {ev.get('n', '')}"
        return None
