"""Membrane analysis summary for the report (docs/specs/report_language.md F46–F52, F57).

`membrane_report_data(...)` runs the pure-numpy analyses of `analysis/membrane.py` on coordinate arrays and returns the
JSON-ready dict the workflow report reads from `analysis.summaries[<system>]["membrane_file"]` (atomistic) or
`state["coarse_grained"][<name>]["membrane_file"]` (Martini, resolution "coarse-grained").  Inputs are nm and
rectangular boxes (F, 3), as in analysis/membrane.py.  Nothing here reads a trajectory: the caller (runner hook, not
connected yet) passes mdtraj arrays.

Schema (every key optional except time_ns, apl_nm2, dpp_nm):
  resolution "atomistic" | "coarse-grained"; type; composition {lipid: fraction}; temperature_k; reference {apl_nm2, dpp_nm}
  time_ns [F]; apl_nm2 [F]; dpp_nm [F]; core_water [F]
  density {"z_nm": [B], "groups": {name: [B]}, "unit": "per nm³"}
  scd {"sn1:C32": S_CD, ...}            (atomistic, CHARMM names; figure plots −S_CD per carbon)
  p2 {"PO4-GL1": P2, ...}               (coarse-grained bond order parameter, same formula as S_CD)
  insertion {"com_depth_nm": [F], "deepest_nm": [F], "crossed_centre": bool}
  headgroup_contacts [{"residue", "fraction", "events", "mean_ps", "max_ps", "open_at_end"}] sorted by fraction
  tilt_deg [F]
  thickness_map {"x_nm": [nx+1], "y_nm": [ny+1], "dpp_nm": [[ny × nx], None where empty]}
"""
from __future__ import annotations

import numpy as np

from . import membrane as M


def thickness_map(head_xyz, box, *, bins: int = 8) -> dict:
    """Local P–P thickness on a bins × bins grid of the membrane plane, averaged over frames.  Positions are taken in
    fractional coordinates of each frame's box, so the map is correct while the box breathes; the edges are given in
    nm of the mean box.  Cells without heads of both leaflets in a frame are skipped for that frame."""
    h = np.asarray(head_xyz, float)
    b = M._box(box, len(h))
    up, c = M.leaflets(h[..., 2], b)
    rz = M.relative_z(h[..., 2], c, b)
    acc = np.zeros((bins, bins))
    cnt = np.zeros((bins, bins))
    for f in range(len(h)):
        fx = np.floor((h[f, :, 0] / b[f, 0]) % 1.0 * bins).astype(int).clip(0, bins - 1)
        fy = np.floor((h[f, :, 1] / b[f, 1]) % 1.0 * bins).astype(int).clip(0, bins - 1)
        su, nu = np.zeros((bins, bins)), np.zeros((bins, bins))
        sl, nl = np.zeros((bins, bins)), np.zeros((bins, bins))
        np.add.at(su, (fy[up], fx[up]), rz[f, up]); np.add.at(nu, (fy[up], fx[up]), 1)
        np.add.at(sl, (fy[~up], fx[~up]), rz[f, ~up]); np.add.at(nl, (fy[~up], fx[~up]), 1)
        ok = (nu > 0) & (nl > 0)
        acc[ok] += su[ok] / nu[ok] - sl[ok] / nl[ok]
        cnt[ok] += 1
    grid = np.where(cnt > 0, acc / np.maximum(cnt, 1), np.nan)
    Lx, Ly = float(b[:, 0].mean()), float(b[:, 1].mean())
    return {"x_nm": np.linspace(0, Lx, bins + 1).round(3).tolist(), "y_nm": np.linspace(0, Ly, bins + 1).round(3).tolist(),
            "dpp_nm": [[None if not np.isfinite(v) else round(float(v), 3) for v in row] for row in grid]}


def _r(a, nd: int = 4) -> list:
    return np.round(np.asarray(a, float), nd).tolist()


def membrane_report_data(*, time_ns, box, head_xyz, composition: dict | None = None, temperature_k: float | None = None,
                     mtype: str = "bilayer", resolution: str = "atomistic", protein_area_nm2: float = 0.0,
                     density_z: dict | None = None, density_bin_nm: float = 0.1,
                     scd_xyz=None, scd_groups: dict | None = None, p2_xyz=None, p2_pairs: dict | None = None,
                     solute_xyz=None, solute_heavy_mask=None, residue_xyz: list | None = None,
                     residue_names: list | None = None, ca_xyz=None, water_o_xyz=None, map_bins: int = 8,
                     contact_cutoff_nm: float = 0.4) -> dict:
    """Everything the report draws for one membrane system.  `density_z` = {group name: z (F, N)} (for example
    "phosphate", "water", "acyl chains", "peptide"); `scd_groups` from membrane.scd_groups_from_names; `p2_pairs`
    {bond name: [(i, j), ...]} of coarse-grained beads."""
    t = np.asarray(time_ns, float)
    h = np.asarray(head_xyz, float)
    b = M._box(box, len(h))
    th = M.thickness_pp(h, b)
    ap = M.area_per_lipid(b, th["n_upper"], th["n_lower"], protein_area_nm2=protein_area_nm2)
    out: dict = {"resolution": resolution, "type": mtype, "composition": dict(composition or {}),
                 "temperature_k": temperature_k, "time_ns": _r(t), "apl_nm2": _r(ap["apl_nm2"]), "dpp_nm": _r(th["dpp_nm"]),
                 "n_lipids": int(th["n_upper"] + th["n_lower"]), "approximate_apl": bool(protein_area_nm2 == 0.0 and mtype == "protein")}
    if composition:
        from ..build.membrane import reference_values, canonical_lipid
        comp = {canonical_lipid(k) or k: v for k, v in composition.items()}
        try:
            out["reference"] = reference_values(comp)
        except KeyError:
            out["reference"] = {"apl_nm2": None, "dpp_nm": None}
    centre = th["centre_nm"]
    if density_z:
        groups = {}
        zs = None
        for name, z in density_z.items():
            d = M.density_profile(np.asarray(z, float), b, centre, bin_nm=density_bin_nm)
            groups[name] = _r(d["density_per_nm3"], 3)
            zs = d["z_nm"]
        out["density"] = {"z_nm": _r(zs, 3), "groups": groups, "unit": "per nm³"}
    if scd_xyz is not None and scd_groups:
        out["scd"] = {k: round(v, 4) for k, v in M.scd_profile(scd_xyz, scd_groups).items()}
    if p2_xyz is not None and p2_pairs:
        out["p2"] = {k: round(v, 4) for k, v in M.scd_profile(p2_xyz, p2_pairs).items()}
    if water_o_xyz is not None:
        out["core_water"] = M.water_in_core(water_o_xyz, centre, b).tolist()
    if solute_xyz is not None:
        ins = M.insertion_depth(solute_xyz, h, b, heavy_mask=solute_heavy_mask)
        out["insertion"] = {"com_depth_nm": _r(ins["com_depth_nm"]), "deepest_nm": _r(ins["deepest_nm"]),
                            "crossed_centre": ins["crossed_centre"]}
    if residue_xyz:
        con = M.headgroup_contacts(residue_xyz, h, b, cutoff_nm=contact_cutoff_nm)
        dt = float(np.median(np.diff(t)) * 1000.0) if len(t) > 1 else 0.0
        rows = M.residence_times(con, dt)
        names = list(residue_names or [f"R{i + 1}" for i in range(len(rows))])
        out["headgroup_contacts"] = sorted(({"residue": n, **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}}
                                            for n, r in zip(names, rows)), key=lambda r: -r["fraction"])
        out["contact_cutoff_nm"] = contact_cutoff_nm
    if ca_xyz is not None and np.asarray(ca_xyz).shape[1] >= 3:
        out["tilt_deg"] = _r(M.helix_tilt(ca_xyz), 2)
    if map_bins:
        out["thickness_map"] = thickness_map(h, b, bins=map_bins)
    return out
