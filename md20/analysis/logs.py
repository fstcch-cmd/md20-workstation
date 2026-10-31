"""Parse OpenMM StateDataReporter logs (tab-separated, quoted header) into DataFrames."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

_RENAME = {
    '#"Step"': "step", "Step": "step",
    "Time (ps)": "time_ps",
    "Potential Energy (kJ/mole)": "potential_kj_mol",
    "Kinetic Energy (kJ/mole)": "kinetic_kj_mol",
    "Total Energy (kJ/mole)": "total_kj_mol",
    "Temperature (K)": "temperature_k",
    "Box Volume (nm^3)": "volume_nm3",
    "Density (g/mL)": "density_g_ml",
    "Speed (ns/day)": "speed_ns_day",
    "Elapsed Time (s)": "elapsed_s",
    "Time Remaining": "remaining",
}


def read_state_log(path: Path | str) -> pd.DataFrame:
    path = Path(path)
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        header = fh.readline().rstrip("\n")
    cols = [c.strip().strip('"') for c in header.lstrip("#").split("\t")]
    df = pd.read_csv(path, sep="\t", comment=None, skiprows=1, names=cols, engine="python")
    df = df[pd.to_numeric(df[cols[0]], errors="coerce").notna()]  # drop repeated headers from concatenation
    df = df.rename(columns={c: _RENAME.get(c, c) for c in df.columns})
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.reset_index(drop=True)


def log_stats(df: pd.DataFrame, last_fraction: float = 0.3) -> dict:
    """Summary of the final `last_fraction` of a stage: means, std, CV, drift."""
    if df.empty:
        return {"n": 0}
    n = len(df)
    tail = df.iloc[int(n * (1 - last_fraction)):] if n > 3 else df
    out = {"n": int(n), "n_tail": int(len(tail))}
    for col in ("temperature_k", "density_g_ml", "potential_kj_mol", "volume_nm3", "total_kj_mol"):
        if col in tail and tail[col].notna().any():
            x = tail[col].astype(float).to_numpy()
            mean = float(np.nanmean(x)); std = float(np.nanstd(x))
            out[col] = {"mean": mean, "std": std, "cv": (std / abs(mean)) if mean else None,
                        "min": float(np.nanmin(x)), "max": float(np.nanmax(x))}
            if "time_ps" in tail and len(tail) > 2:
                t = tail["time_ps"].to_numpy(dtype=float)
                try:
                    slope = float(np.polyfit(t - t[0], x, 1)[0])
                except Exception:  # noqa: BLE001
                    slope = None
                out[col]["drift_per_ns"] = slope * 1000.0 if slope is not None else None
    if "speed_ns_day" in df and df["speed_ns_day"].notna().any():
        out["speed_ns_day"] = float(np.nanmedian(df["speed_ns_day"]))
    return out
