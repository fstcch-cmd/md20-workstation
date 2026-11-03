"""Analysis of a coarse-grained Martini 3 run (D-86).  Bead-level numbers for the report (subsystem_report.cg_section):

  time_ns, apl_nm2, dpp_nm   area per lipid and PO4–PO4 thickness per frame (membranes)
  reference                  experimental POPC area per lipid (Martini 3 is parametrised to reproduce it); the CG
                             PO4–PO4 distance is not compared with the all-atom P–P value (different centres)
  p2                         second-rank bond order parameter of the tail bonds (fluid 0.1–0.6)
  protein_rmsd_nm            RMSD of the BB beads to the first frame (after fitting)
  solute_dz_nm, contact_frac surface systems: protein centre height above the phosphate plane, fraction of frames
                             with any protein bead within 0.7 nm of a PO4 bead
Everything uses the .gro bead names (PO4, BB, SC*), so it works for any lipid mix insane wrote.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..analysis import membrane as MA
from ..build.membrane import LIPIDS

TAIL_BEADS = ("GL1", "GL2", "C1A", "D2A", "C2A", "C3A", "D3A", "C4A", "D4A", "C5A", "C1B", "D2B", "C2B", "C3B",
              "D3B", "C4B", "C5B")
CONTACT_NM = 0.7


def bond_p2(xyz: np.ndarray, pairs: list[tuple[int, int]]) -> float:
    """⟨P2(cos θ)⟩ of bond vectors to z (frames × pairs averaged)."""
    if not pairs:
        return float("nan")
    a = np.array([p[0] for p in pairs]); b = np.array([p[1] for p in pairs])
    v = xyz[:, b, :] - xyz[:, a, :]
    c = v[..., 2] / np.maximum(np.linalg.norm(v, axis=-1), 1e-9)
    return float(np.mean(0.5 * (3 * c * c - 1)))


def tail_pairs(names: list[str], resid: np.ndarray, lipid_resnames: set[str]) -> dict[str, list[tuple[int, int]]]:
    """Consecutive tail-bead bonds per bond label (e.g. C1A-D2A) over all lipids."""
    out: dict[str, list] = {}
    by_res: dict[int, dict[str, int]] = {}
    for i, n in enumerate(names):
        by_res.setdefault(int(resid[i]), {})[n] = i
    for beads in by_res.values():
        if "PO4" not in beads:
            continue
        for chain in ("A", "B"):
            seq = [n for n in TAIL_BEADS if n.endswith(chain) and n in beads]
            for x, y in zip(seq, seq[1:]):
                out.setdefault(f"{x}-{y}", []).append((beads[x], beads[y]))
    return out


def analyse_cg(man: dict, run_dir: Path | str, *, decisions=None) -> dict:
    import mdtraj
    rd = Path(run_dir)
    t = mdtraj.load_dcd(str(rd / "production.dcd"), top=man["gro"])
    names = [a.name for a in t.topology.atoms]
    resid = np.array([a.residue.resSeq for a in t.topology.atoms])
    resn = [a.residue.name for a in t.topology.atoms]
    xyz = t.xyz
    box = t.unitcell_lengths
    prog = json.loads((rd / "progress.json").read_text(encoding="utf-8")) if (rd / "progress.json").is_file() else {}
    save_ps = float((prog.get("plan") or {}).get("save_ps") or 0.0)
    time_ns = (np.arange(t.n_frames) * save_ps / 1000.0).tolist()
    out = {"resolution": "coarse-grained", "n_frames": int(t.n_frames), "time_ns": time_ns, "kind": man.get("kind")}
    po4 = [i for i, n in enumerate(names) if n == "PO4"]
    n_prot = int(man.get("n_protein_beads") or 0)
    if po4:
        th = MA.thickness_pp(xyz[:, po4, :], box)
        out["dpp_nm"] = [round(float(x), 4) for x in th["dpp_nm"]]
        n_up, n_lo = th["n_upper"], th["n_lower"]
        # with a protein in the bilayer the xy area includes its cross-section: labelled approximate
        apl = MA.area_per_lipid(box, n_up, n_lo)
        out["apl_nm2"] = [round(float(x), 4) for x in apl["apl_nm2"]]
        out["apl_includes_protein"] = bool(n_prot and man.get("kind") == "protein")
        out["n_lipids"] = [n_up, n_lo]
        lip = dict(man.get("lipids") or {})
        ref_apl = LIPIDS["POPC"]["apl_nm2"] if set(lip) <= {"POPC"} and not out["apl_includes_protein"] else None
        out["reference"] = {"apl_nm2": ref_apl, "dpp_nm": None,
                            "source": "POPC experimental area per lipid (Kučerka et al.); thickness not compared"}
        pairs = tail_pairs(names, resid, set(lip))
        out["p2"] = {k: round(bond_p2(xyz[:, :, :], v), 3) for k, v in pairs.items()}
        centre = MA.membrane_centre(xyz[:, po4, 2], box)
        out["centre_nm"] = [round(float(x), 3) for x in centre]
    if n_prot:
        bb = [i for i in range(n_prot) if names[i] == "BB"]
        if bb:
            sub = t.atom_slice(bb)
            sub.superpose(sub, 0)
            rmsd = np.sqrt(((sub.xyz - sub.xyz[0]) ** 2).sum(-1).mean(-1))
            out["protein_rmsd_nm"] = [round(float(x), 4) for x in rmsd]
        if po4 and man.get("kind") == "surface":
            up, c = MA.leaflets(xyz[:, po4, 2], box)
            rp = MA.relative_z(xyz[:, po4, 2], c, box)
            rz = MA.relative_z(xyz[:, :n_prot, 2], c, box)
            upper, lower = rp[:, up].mean(1), rp[:, ~up].mean(1)
            above = rz.mean(1) > 0
            dz = np.where(above, rz.min(1) - upper, lower - rz.max(1))
            out["solute_dz_nm"] = [round(float(x), 3) for x in dz]
            out["contact_frac"] = round(float(np.mean(dz < CONTACT_NM)), 3)
    path = rd / "cg_analysis.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    out["file"] = str(path)
    if decisions:
        s = []
        if out.get("apl_nm2"):
            s.append(f"每脂質面積平均 {np.mean(out['apl_nm2']):.3f} nm²" + ("（含蛋白截面，偏大）" if out["apl_includes_protein"] else ""))
        if out.get("dpp_nm"):
            s.append(f"PO4–PO4 厚度平均 {np.mean(out['dpp_nm']):.2f} nm")
        if out.get("protein_rmsd_nm"):
            s.append(f"蛋白骨架珠 RMSD 最後 {out['protein_rmsd_nm'][-1]:.2f} nm")
        if "contact_frac" in out:
            s.append(f"胜肽與磷酸珠 0.7 nm 內接觸的幀比例 {out['contact_frac']:.0%}")
        decisions.record("analysis.cg", man.get("kind"), f"{t.n_frames} frames", "粗粒化分析（珠子層級）：" + "；".join(s) + "。",
                         kind="auto")
    return out
