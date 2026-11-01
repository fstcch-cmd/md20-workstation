"""pH-dependent protonation via PROPKA (pdb2pqr) — optional, pure Python, Windows-friendly.

PDBFixer's `addMissingHydrogens(pH)` uses fixed rules; PROPKA predicts per-residue
pKa from the structure.  When pdb2pqr/propka are importable we run them and turn
the result into explicit residue-variant assignments (HID/HIE/HIP, ASH, GLH, LYN)
that PDBFixer/Modeller respect, and record every non-default choice as a decision.

If the packages are missing we fall back to PDBFixer rules and say so.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

from ..util import DecisionLog

# residue variants OpenMM's amber14 templates understand
_VARIANT = {"HIS": {"HID", "HIE", "HIP"}, "ASP": {"ASH"}, "GLU": {"GLH"}, "LYS": {"LYN"}, "CYS": {"CYX"}}


def propka_available() -> bool:
    try:
        import propka  # noqa: F401
        import pdb2pqr  # noqa: F401
        return True
    except ImportError:
        return shutil.which("pdb2pqr") is not None or shutil.which("pdb2pqr30") is not None


def run_pdb2pqr(pdb_in: Path | str, out_dir: Path | str, *, ph: float = 7.4, forcefield: str = "AMBER") -> dict:
    """Run pdb2pqr with PROPKA titration.  Returns paths + parsed pKa table."""
    pdb_in, out_dir = Path(pdb_in), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pqr = out_dir / "receptor_propka.pqr"
    pka = out_dir / "receptor_propka.pka"
    cmd = [sys.executable, "-m", "pdb2pqr", "--ff", forcefield, "--titration-state-method", "propka",
           f"--with-ph={ph}", "--pdb-output", str(out_dir / "receptor_propka.pdb"), str(pdb_in), str(pqr)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        raise RuntimeError("pdb2pqr 失敗：" + (proc.stderr or proc.stdout)[-2000:])
    table = parse_pka_file(pka) if pka.is_file() else []
    return {"pqr": str(pqr), "pdb": str(out_dir / "receptor_propka.pdb"), "pka_file": str(pka) if pka.is_file() else "",
            "ph": ph, "pka_table": table, "variants": variants_from_pqr(pqr)}


_PKA_LINE = re.compile(r"^\s*(ASP|GLU|HIS|LYS|ARG|TYR|CYS|N\+|C-)\s+(\d+)\s+([A-Z_])\s+([\d.]+)\s+([\d.]+)")


def parse_pka_file(path: Path | str) -> list[dict]:
    rows = []
    in_summary = False
    for line in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("SUMMARY OF THIS PREDICTION"):
            in_summary = True
            continue
        if in_summary:
            m = _PKA_LINE.match(line)
            if m:
                rows.append({"residue": m.group(1), "resid": int(m.group(2)), "chain": m.group(3),
                             "pka": float(m.group(4)), "model_pka": float(m.group(5))})
    return rows


def variants_from_pqr(pqr: Path | str) -> dict[tuple[str, int], str]:
    """Map (chain, resid) → variant name as pdb2pqr wrote it (HID/HIE/HIP/ASH/GLH/LYN/CYX)."""
    out = {}
    for line in Path(pqr).read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith(("ATOM", "HETATM")):
            resname = line[17:20].strip()
            chain = line[21].strip() or "_"
            try:
                resid = int(line[22:26])
            except ValueError:
                continue
            for std, var in _VARIANT.items():
                if resname in var:
                    out[(chain, resid)] = resname
    return out


def decide_protonation(receptor_pdb: Path | str, out_dir: Path | str, *, ph: float = 7.4,
                       decisions: DecisionLog | None = None) -> dict:
    """PROPKA when available, otherwise PDBFixer rules.  Always returns a dict the build can consume."""
    if not propka_available():
        if decisions:
            decisions.record("build.protonation", "method", "PDBFixer rules", f"pdb2pqr/propka 未安裝；以 PDBFixer 固定規則在 pH {ph} 加氫。")
        return {"method": "pdbfixer", "ph": ph, "variants": {}}
    res = run_pdb2pqr(receptor_pdb, out_dir, ph=ph)
    if decisions:
        decisions.record("build.protonation", "method", "PROPKA (pdb2pqr)", f"依結構預測 pKa，在 pH {ph} 指派質子化狀態。")
        for row in res["pka_table"]:
            if row["residue"] == "HIS" or abs(row["pka"] - row["model_pka"]) > 1.5:
                decisions.record("build.protonation", f"{row['residue']}{row['resid']}{row['chain']}", f"pKa {row['pka']:.1f}",
                                 f"模型 pKa {row['model_pka']:.1f}，結構環境位移 {row['pka'] - row['model_pka']:+.1f}；"
                                 + ("His 狀態依 pKa 與 pH 比較決定。" if row["residue"] == "HIS" else "位移超過 1.5 單位，值得在報告中說明。"))
    res["method"] = "propka"
    return res


def pocket_protonation_review(pka_table: list[dict], receptor_pdb: Path | str, center, *, ph: float = 7.4,
                              radius_A: float = 8.0) -> list[dict]:
    """WP8 (review mode): titratable pocket residues whose PROPKA pKa is within 1 unit of the pH, or whose predicted
    state differs from the fixed-rule default (Asp/Glu neutral, His doubly protonated, Lys neutral).

    These are *flagged*, not changed: the build still uses PDBFixer rules at the given pH, and the report lists
    the residues so the student can decide whether to rebuild with a different state."""
    import numpy as np
    c = np.asarray(center, float)
    near: set[tuple[str, int]] = set()
    for l in Path(receptor_pdb).read_text(encoding="utf-8", errors="ignore").splitlines():
        if l.startswith("ATOM"):
            try:
                xyz = np.array([float(l[30:38]), float(l[38:46]), float(l[46:54])])
                rid = int(l[22:26])
            except ValueError:
                continue
            if np.linalg.norm(xyz - c) <= radius_A:
                near.add(((l[21].strip() or "_"), rid))
    out = []
    for r in pka_table:
        if (r["chain"].strip() or "_", r["resid"]) not in near:
            continue
        pka, res = r["pka"], r["residue"]
        flags = []
        if abs(pka - ph) < 1.0:
            flags.append(f"pKa {pka:.1f} 與 pH {ph} 相差 < 1：兩種質子化狀態都有可觀比例")
        if res in ("ASP", "GLU") and pka > ph:
            flags.append(f"預測為中性（{'ASH' if res == 'ASP' else 'GLH'}），固定規則會給帶負電")
        elif res == "HIS" and pka > ph:
            flags.append("預測為雙質子化 HIP（+1）")
        elif res == "LYS" and pka < ph:
            flags.append("預測為中性 LYN")
        elif res == "CYS" and pka < ph:
            flags.append("預測為去質子化（−1）")
        if flags:
            out.append({"residue": f"{res}{r['resid']}{r['chain']}", "pka": pka, "model_pka": r["model_pka"],
                        "flags": flags})
    return out
