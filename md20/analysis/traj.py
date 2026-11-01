"""Trajectory analysis with mdtraj: production run → metrics, figures, analysis_manifest.json.

PBC handling: molecules are imaged (made whole) and the trajectory is superposed on protein Cα of
frame 0 before any ligand metric, so a ligand that crosses the box edge is never reported as
"unbound" (the classic visual-wrap artefact the original notebook warned about).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..util import atomic_write_json, load_json, now_iso
from .plots import PALETTE, _mpl, _save

LIG_PREFIX = "L"


def _ligand_resnames(top) -> list[str]:
    return sorted({r.name for r in top.residues if len(r.name) == 3 and r.name.startswith(LIG_PREFIX) and r.name[1:].isdigit()})


def anchor_atoms(top, metal_indices: list[int] | None = None) -> set[int]:
    """Protein chains (+ metals bonded to them) are the anchor; never let mdtraj guess by molecule size —
    with a peptide ligand or a second chain the guess puts them on the wrong side of the box."""
    idx = set(int(i) for i in top.select("protein"))
    idx |= set(int(i) for i in (metal_indices or []))
    return idx


def center_trajectory(traj, *, metal_indices: list[int] | None = None, superpose: bool = True, inplace: bool = True):
    """Image every molecule to the side of the protein, put the protein centroid at the box centre, optionally
    superpose on Cα (docs/specs/pbc_centering.md).  Returns the (possibly new) trajectory plus the molecule sets."""
    import mdtraj as md  # noqa: F401
    t = traj if inplace else traj[:]
    top = t.topology
    anchors = anchor_atoms(top, metal_indices)
    mols = top.find_molecules()
    anchor_mols = [m for m in mols if any(a.index in anchors for a in m)]
    other_mols = [m for m in mols if not any(a.index in anchors for a in m)]
    if anchor_mols and t.unitcell_vectors is not None:      # implicit solvent (GBn2) trajectories have no box: nothing to image
        t.image_molecules(inplace=True, anchor_molecules=anchor_mols, other_molecules=other_mols)
        a_idx = np.array(sorted(i for m in anchor_mols for i in (a.index for a in m)), dtype=int)
        box = t.unitcell_lengths if t.unitcell_lengths is not None else None
        for f in range(t.n_frames):
            centroid = t.xyz[f, a_idx].mean(0)
            target = (box[f] / 2.0) if box is not None else np.zeros(3)   # no box (GBn2): protein centroid at the origin
            t.xyz[f] += target - centroid
    ca = top.select("protein and name CA")
    if superpose and len(ca):
        t.superpose(t, 0, atom_indices=ca)
    return t


def load_production(run_dir: Path | str, topology_pdb: Path | str, *, stride: int = 1, metal_indices: list[int] | None = None,
                    superpose: bool = True):
    """Production DCDs → one trajectory, re-centred (anchored on the protein) and Cα-superposed."""
    import mdtraj as md
    comp = load_json(Path(run_dir) / "stages" / "production" / "production_complete.json", {})
    dcds = (comp.get("result") or {}).get("dcd_paths") or []
    if not dcds:
        raise FileNotFoundError("production 沒有 DCD；請確認 stage 已完成且 write_dcd=True")
    traj = md.load(dcds, top=str(topology_pdb), stride=stride)
    return center_trajectory(traj, metal_indices=metal_indices, superpose=superpose)


def export_centered(run_dir: Path | str, topology_pdb: Path | str, *, metal_indices: list[int] | None = None,
                    ligand_groups: dict[str, list[int]] | None = None, stride: int = 1) -> dict:
    """Write production_centered.dcd (+ .pdb) for students/VMD and the apparent-vs-true dissociation check.
    Two files: *_centered* (imaged + protein centroid at the box centre, no rotation) and *_aligned* (also
    Cα-superposed; the box appears to rotate, RMSD-ready)."""
    import mdtraj as md
    from .pbc import apparent_vs_true_distance
    run_dir = Path(run_dir)
    comp = load_json(run_dir / "stages" / "production" / "production_complete.json", {})
    dcds = (comp.get("result") or {}).get("dcd_paths") or []
    if not dcds:
        raise FileNotFoundError("production 沒有 DCD")
    raw = md.load(dcds, top=str(topology_pdb), stride=stride)
    raw_xyz_last = raw.xyz[-1].copy()
    cen = center_trajectory(raw, metal_indices=metal_indices, superpose=False, inplace=True)
    adir = run_dir / "analysis"; adir.mkdir(parents=True, exist_ok=True)
    cen.save_dcd(str(adir / "production_centered.dcd"))
    cen[0].save_pdb(str(adir / "production_centered.pdb"))
    checks = {}
    top = cen.topology
    if ligand_groups is None:
        ligand_groups = {rn: top.select(f"resname {rn} and not element H").tolist() for rn in _ligand_resnames(top)}
    prot_heavy = top.select("protein and not element H")
    for name, idx in ligand_groups.items():
        li = np.array(idx, dtype=int)
        if not len(li) or not len(prot_heavy):
            continue
        d0 = np.linalg.norm(cen.xyz[0, prot_heavy][:, None, :] - cen.xyz[0, li][None, :, :], axis=-1).min(1)
        pocket = prot_heavy[d0 < 0.8]
        if not len(pocket):
            pocket = prot_heavy
        checks[name] = apparent_vs_true_distance(raw_xyz_last, cen.xyz[-1], li, np.asarray(pocket, dtype=int))
    aligned = cen[:]
    ca = top.select("protein and name CA")
    if len(ca):
        aligned.superpose(aligned, 0, atom_indices=ca)
        aligned.save_dcd(str(adir / "production_aligned.dcd"))
    out = {"centered_dcd": str(adir / "production_centered.dcd"), "centered_pdb": str(adir / "production_centered.pdb"),
           "aligned_dcd": str(adir / "production_aligned.dcd") if len(ca) else None, "n_frames": int(cen.n_frames),
           "pbc_checks": checks}
    atomic_write_json(out, adir / "centered_manifest.json", backup=False)
    return out


def compute_metrics(traj, ligand_groups: dict[str, list[int]] | None = None) -> dict:
    """`ligand_groups` = {name: heavy-atom indices} from build_manifest (works for peptides too);
    falls back to residue names L01, L02 … when absent."""
    import mdtraj as md
    top = traj.topology
    if ligand_groups is None:
        ligand_groups = {rn: top.select(f"resname {rn} and not element H").tolist() for rn in _ligand_resnames(top)}
    lig_all = np.array(sorted({i for v in ligand_groups.values() for i in v}), dtype=int)
    t_ns = traj.time / 1000.0 if traj.time is not None and len(traj.time) else np.arange(traj.n_frames, dtype=float)
    out: dict = {"time_ns": t_ns.tolist(), "n_frames": int(traj.n_frames)}
    bb = np.setdiff1d(top.select("protein and backbone"), lig_all)
    ca = np.setdiff1d(top.select("protein and name CA"), lig_all)
    if len(bb):
        out["rmsd_backbone_A"] = (md.rmsd(traj, traj, 0, atom_indices=bb) * 10).tolist()
    if len(ca):
        rmsf = md.rmsf(traj, traj, 0, atom_indices=ca) * 10
        out["rmsf_ca_A"] = rmsf.tolist()
        out["rmsf_residues"] = [f"{top.atom(i).residue.name}{top.atom(i).residue.resSeq}" for i in ca]
        out["rg_protein_A"] = (md.compute_rg(traj.atom_slice(np.setdiff1d(top.select("protein"), lig_all))) * 10).tolist()
    out["ligands"] = {}
    prot_heavy = np.setdiff1d(top.select("protein and not element H"), lig_all)
    prot_polar = np.setdiff1d(top.select("protein and (element N or element O)"), lig_all)
    for rn, idx in ligand_groups.items():
        lh = np.array(idx, dtype=int)
        if not len(lh):
            continue
        # ligand RMSD in the protein frame (no ligand re-fit): measures movement inside the pocket
        xyz = traj.xyz[:, lh, :]
        lrmsd = np.sqrt(((xyz - xyz[0]) ** 2).sum(-1).mean(-1)) * 10
        pairs = np.array([[i, j] for i in lh for j in prot_heavy])
        # restrict to protein atoms near the ligand in frame 0 to keep it cheap
        d0 = md.compute_distances(traj[0], pairs)[0]
        near_pairs = pairs[d0 < 1.2]
        dist = md.compute_distances(traj, near_pairs) if len(near_pairs) else np.zeros((traj.n_frames, 0))
        contacts = (dist < 0.4)
        n_contact_res = []
        res_freq: dict[str, int] = {}
        res_of = np.array([top.atom(j).residue.index for _, j in near_pairs]) if len(near_pairs) else np.array([])
        for f in range(traj.n_frames):
            rs = set(res_of[contacts[f]].tolist()) if len(near_pairs) else set()
            n_contact_res.append(len(rs))
            for r in rs:
                key = f"{top.residue(r).name}{top.residue(r).resSeq}"
                res_freq[key] = res_freq.get(key, 0) + 1
        lpolar = np.array([i for i in lh if top.atom(int(i)).element.symbol in ("N", "O")], dtype=int)
        hb = []
        if len(lpolar) and len(prot_polar):
            hp = np.array([[i, j] for i in lpolar for j in prot_polar])
            hd = md.compute_distances(traj, hp)
            hb = (hd < 0.35).sum(1).tolist()
        com_l = md.compute_center_of_mass(traj.atom_slice(lh))
        pocket = sorted({j for _, j in near_pairs}) if len(near_pairs) else list(prot_heavy[:1])
        com_p = md.compute_center_of_mass(traj.atom_slice(np.array(pocket)))
        out["ligands"][rn] = {
            "rmsd_in_pocket_A": lrmsd.tolist(),
            "contact_residues": n_contact_res,
            "polar_contacts": hb,
            "com_distance_to_pocket_A": (np.linalg.norm(com_l - com_p, axis=1) * 10).tolist(),
            "contact_frequency": {k: v / traj.n_frames for k, v in sorted(res_freq.items(), key=lambda kv: -kv[1])},
            "stays_bound": bool(np.mean(lrmsd[-max(1, len(lrmsd) // 5):]) < 3.0),
        }
    # WP4: ligand–ligand centroid distances (multi-ligand systems)
    names = [n for n in ligand_groups if len(ligand_groups[n])]
    if len(names) > 1:
        coms = {n: traj.xyz[:, np.array(ligand_groups[n], dtype=int), :].mean(1) for n in names}
        out["ligand_ligand_distance_A"] = {f"{a}-{b}": (np.linalg.norm(coms[a] - coms[b], axis=1) * 10).tolist()
                                           for i, a in enumerate(names) for b in names[i + 1:]}
    return out


def plot_metrics(m: dict, out_dir: Path | str, *, label: str = "") -> dict:
    plt = _mpl()
    out_dir = Path(out_dir)
    figs = {}
    t = np.asarray(m["time_ns"])
    rows = [("rmsd_backbone_A", "Backbone RMSD (Å)"), ("rg_protein_A", "Protein Rg (Å)")]
    rows = [r for r in rows if r[0] in m]
    for rn, d in m.get("ligands", {}).items():
        rows += [(("lig", rn, "rmsd_in_pocket_A"), f"{rn} RMSD in pocket (Å)"),
                 (("lig", rn, "contact_residues"), f"{rn} contacting residues")]
    if rows:
        fig, axes = plt.subplots(len(rows), 1, figsize=(7.2, 1.8 * len(rows) + 0.6), sharex=True)
        axes = np.atleast_1d(axes)
        for ax, (key, lab), c in zip(axes, rows, PALETTE * 3):
            y = m["ligands"][key[1]][key[2]] if isinstance(key, tuple) else m[key]
            ax.plot(t[:len(y)], y, color=c)
            ax.set_ylabel(lab, fontsize=8)
        axes[-1].set_xlabel("Time (ns)")
        axes[0].set_title(f"Production analysis {label}".strip(), loc="left", fontsize=10)
        figs["timeseries"] = _save(fig, out_dir / "analysis_timeseries")
    if "rmsf_ca_A" in m:
        fig, ax = plt.subplots(figsize=(7.6, 2.6))
        ax.plot(np.arange(len(m["rmsf_ca_A"])), m["rmsf_ca_A"], color=PALETTE[0])
        ax.set_xlabel("Residue index"); ax.set_ylabel("Cα RMSF (Å)")
        ax.set_title("Per-residue flexibility", loc="left", fontsize=10)
        figs["rmsf"] = _save(fig, out_dir / "analysis_rmsf")
    for rn, d in m.get("ligands", {}).items():
        freq = list(d["contact_frequency"].items())[:15]
        if not freq:
            continue
        fig, ax = plt.subplots(figsize=(7.2, 0.28 * len(freq) + 0.9))
        names = [k for k, _ in freq][::-1]; vals = [v for _, v in freq][::-1]
        ax.barh(names, vals, color=PALETTE[2], height=0.6)
        ax.set_xlim(0, 1); ax.set_xlabel("Fraction of frames in contact (≤ 4 Å)")
        ax.set_title(f"{rn}: pocket residues", loc="left", fontsize=10)
        for y, v in enumerate(vals):
            ax.text(v + 0.01, y, f"{v:.0%}", va="center", fontsize=7)
        figs[f"contacts_{rn}"] = _save(fig, out_dir / f"analysis_contacts_{rn}")
    if m.get("ligand_ligand_distance_A"):
        fig, ax = plt.subplots(figsize=(7.2, 2.6))
        for (pair, y), c in zip(m["ligand_ligand_distance_A"].items(), PALETTE * 3):
            ax.plot(t[:len(y)], y, color=c, lw=2, label=pair)
        ax.set_xlabel("Time (ns)"); ax.set_ylabel("Centroid distance (Å)")
        ax.set_title("Ligand–ligand distance (co-occupancy stability)", loc="left", fontsize=10)
        ax.legend(fontsize=7, frameon=False)
        figs["ligand_ligand"] = _save(fig, out_dir / "analysis_ligand_ligand")
    return figs


def analyse_run(run_dir: Path | str, topology_pdb: Path | str, *, stride: int = 1, label: str = "",
                ligand_groups: dict[str, list[int]] | None = None, metal_indices: list[int] | None = None,
                decisions=None) -> dict:
    run_dir = Path(run_dir)
    traj = load_production(run_dir, topology_pdb, stride=stride, metal_indices=metal_indices)
    m = compute_metrics(traj, ligand_groups)
    adir = run_dir / "analysis"
    adir.mkdir(parents=True, exist_ok=True)
    try:
        cen = export_centered(run_dir, topology_pdb, metal_indices=metal_indices, ligand_groups=ligand_groups, stride=stride)
    except Exception as exc:  # noqa: BLE001 — the centred export is a convenience; metrics above are already imaged
        cen = {"error": f"{type(exc).__name__}: {exc}"}
    m["pbc"] = cen
    for name, chk in (cen.get("pbc_checks") or {}).items():
        if chk.get("pbc_artifact") and decisions is not None:
            decisions.record("analysis.pbc", name, "visual wrap artefact corrected",
                             f"原始 DCD 的最後一幀中 {name} 與口袋質心距離 {chk['apparent_nm'] * 10:.1f} Å（看起來已解離），"
                             f"歸零／錨定後為 {chk['true_nm'] * 10:.1f} Å：這是週期邊界的視覺假象，不是解離；分析與報告都用歸零後的座標。",
                             kind="auto_fixed")
    from ..engine.protocol import production_restraints
    restrained = production_restraints(load_json(run_dir / "run.json", {}).get("protocol") or {})
    if restrained:
        m["restrained_production"] = restrained
        label = f"{label}（受約束：{', '.join(restrained)}）" if label else f"受約束：{', '.join(restrained)}"
    figs = plot_metrics(m, run_dir / "figures", label=label)
    summary = {"status": "PASS", "restrained_production": restrained, "metrics_file": str(adir / "metrics.json"), "figures": figs, "created_at": now_iso(),
               "n_frames": m["n_frames"], "centered": {k: v for k, v in cen.items() if k != "pbc_checks"},
               "pbc_checks": cen.get("pbc_checks", {}),
               "rmsd_backbone_mean_A": float(np.mean(m["rmsd_backbone_A"])) if "rmsd_backbone_A" in m else None,
               "ligands": {rn: {"stays_bound": d["stays_bound"], "rmsd_last20_A": float(np.mean(d["rmsd_in_pocket_A"][-max(1, len(d["rmsd_in_pocket_A"]) // 5):])),
                                "top_contacts": list(d["contact_frequency"].items())[:5]} for rn, d in m["ligands"].items()}}
    atomic_write_json(m, adir / "metrics.json", backup=False)
    atomic_write_json(summary, adir / "analysis_manifest.json")
    return summary


def compare_runs(metrics: dict[str, dict], out_dir: Path | str) -> dict:
    """Overlay e.g. {"apo": m_apo, "holo L01": m_holo}: backbone RMSD and Cα RMSF (same protein ⇒ same residue axis)."""
    plt = _mpl()
    out_dir = Path(out_dir)
    figs = {}
    fig, axes = plt.subplots(2, 1, figsize=(7.6, 4.6))
    for i, (lab, m) in enumerate(metrics.items()):
        c = PALETTE[i % len(PALETTE)]
        if "rmsd_backbone_A" in m:
            axes[0].plot(m["time_ns"][:len(m["rmsd_backbone_A"])], m["rmsd_backbone_A"], color=c, label=lab)
        if "rmsf_ca_A" in m:
            axes[1].plot(np.arange(len(m["rmsf_ca_A"])), m["rmsf_ca_A"], color=c, label=lab)
    axes[0].set_xlabel("Time (ns)"); axes[0].set_ylabel("Backbone RMSD (Å)")
    axes[1].set_xlabel("Residue index"); axes[1].set_ylabel("Cα RMSF (Å)")
    axes[0].set_title("Apo vs ligand-bound: stability and flexibility", loc="left", fontsize=10)
    axes[0].legend(frameon=False, fontsize=8)
    fig.tight_layout()
    figs["compare"] = _save(fig, out_dir / "compare_apo_holo")
    # residues whose flexibility changes most on binding (first pair apo vs first holo)
    labs = list(metrics)
    delta = None
    if len(labs) >= 2 and "rmsf_ca_A" in metrics[labs[0]] and "rmsf_ca_A" in metrics[labs[1]]:
        a, b = np.asarray(metrics[labs[0]]["rmsf_ca_A"]), np.asarray(metrics[labs[1]]["rmsf_ca_A"])
        n = min(len(a), len(b))
        d = b[:n] - a[:n]
        idx = np.argsort(d)[:10]
        names = metrics[labs[1]].get("rmsf_residues", [str(i) for i in range(n)])
        delta = [{"residue": names[i], "delta_rmsf_A": round(float(d[i]), 3)} for i in idx]
    return {"figures": figs, "most_rigidified_on_binding": delta}
