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
    from .stream import production_topology
    comp = load_json(Path(run_dir) / "stages" / "production" / "production_complete.json", {})
    dcds = (comp.get("result") or {}).get("dcd_paths") or []
    if not dcds:
        raise FileNotFoundError("production 沒有 DCD；請確認 stage 已完成且 write_dcd=True")
    top, _ = production_topology(run_dir, topology_pdb)       # solute-only DCDs (long runs) get a cut topology
    traj = md.load(dcds, top=top, stride=stride)
    from .stream import set_production_time
    set_production_time(traj, run_dir, dcds, stride=stride)     # D-89: real time axis across chunk files
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
    from .stream import production_topology
    top0, _ = production_topology(run_dir, topology_pdb)
    raw = md.load(dcds, top=top0, stride=stride)
    from .stream import set_production_time
    set_production_time(raw, run_dir, dcds, stride=stride)
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


LIGAND_STATE_THRESHOLDS = {"version": "2026-11-07.1", "pose_rmsd_A": 2.0, "escape_com_rise_A": 5.0, "escape_min_frames": 3,
                           "source": "empirical starting values; validate per system (spec A4)"}


def ligand_state(rmsd_A, n_contact_res, com_A, t_ns=None, *, restrained: list | None = None, thr: dict | None = None) -> dict:
    """D-97 (A4): per-frame ligand state from contacts, pocket COM distance and RMSD together — never RMSD alone.

      pose_retained           ≥ 1 contacting residue and RMSD ≤ pose_rmsd_A
      pose_changed_in_pocket  ≥ 1 contacting residue and RMSD > pose_rmsd_A (high RMSD with contacts ≠ dissociation)
      escape_evidence         no contacting residue for ≥ escape_min_frames consecutive frames AND the COM is
                              ≥ escape_com_rise_A farther from the pocket than in frame 0
      unknown                 anything else (e.g. contacts lost briefly, or lost without COM displacement)
    Positional restraints, if any, are stated: retention under restraint is not unrestrained stability."""
    th = {**LIGAND_STATE_THRESHOLDS, **(thr or {})}
    r = np.asarray(rmsd_A, float)
    n = np.asarray(n_contact_res, int)
    c = np.asarray(com_A, float)
    F = len(r)
    if not (len(n) == len(c) == F) or not F:
        return {"status": "unavailable", "reason": "series lengths differ or are empty"}
    noc = n == 0
    run = np.zeros(F, int)
    for i in range(F):
        run[i] = (run[i - 1] + 1 if i and noc[i] else (1 if noc[i] else 0))
    # a frame belongs to a long no-contact stretch if the stretch it is in reaches escape_min_frames
    long_ = np.zeros(F, bool)
    i = F - 1
    while i >= 0:
        if run[i] >= th["escape_min_frames"]:
            k = run[i]
            long_[i - k + 1:i + 1] = True
            i -= k
        else:
            i -= 1
    rise = c - c[0]
    state = np.where(~noc & (r <= th["pose_rmsd_A"]), "pose_retained",
                     np.where(~noc, "pose_changed_in_pocket",
                              np.where(long_ & (rise >= th["escape_com_rise_A"]), "escape_evidence", "unknown")))
    names = ["pose_retained", "pose_changed_in_pocket", "escape_evidence", "unknown"]
    tail = slice(F - max(1, F // 5), F)
    return {"schema": "md20.ligand_state/1", "thresholds": th, "per_frame": state.tolist(),
            "fraction_all": {k: round(float((state == k).mean()), 4) for k in names},
            "fraction_final_20pct": {k: round(float((state[tail] == k).mean()), 4) for k in names},
            "first_escape_ns": (None if not (state == "escape_evidence").any() or t_ns is None
                                else float(np.asarray(t_ns)[int(np.argmax(state == "escape_evidence"))])),
            "restraints": restrained or [],
            "rmsd_reference": "first stored production frame (not the docking pose)",
            "note": "observed state under the simulated conditions; not an equilibrium binding probability"}


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
        # D-97 (A6): complete per-frame neighbour search — a contact that forms after frame 0 is counted (the old
        # first-frame 1.2 nm candidate filter missed it); residues are chain-aware (A:ASP189 ≠ B:ASP189)
        from .interactions import dynamic_pairs, residue_key, display_labels
        dyn = dynamic_pairs(traj.xyz, lh, prot_heavy, cutoff_nm=0.4)
        near_pairs, dist = dyn["pairs"], dyn["dist"]
        contacts = (dist < 0.4)
        n_contact_res = []
        res_freq: dict[str, int] = {}

        def _rk(r):
            return residue_key(getattr(r.chain, "chain_id", None) or str(r.chain.index), r.name, r.resSeq)
        res_of = np.array([top.atom(int(j)).residue.index for _, j in near_pairs]) if len(near_pairs) else np.array([])
        for f in range(traj.n_frames):
            rs = set(res_of[contacts[f]].tolist()) if len(near_pairs) else set()
            n_contact_res.append(len(rs))
            for r in rs:
                key = _rk(top.residue(r))
                res_freq[key] = res_freq.get(key, 0) + 1
        lab = display_labels(res_freq)
        lpolar = np.array([i for i in lh if top.atom(int(i)).element.symbol in ("N", "O")], dtype=int)
        hb = []
        if len(lpolar) and len(prot_polar):
            hp = np.array([[i, j] for i in lpolar for j in prot_polar])
            hd = md.compute_distances(traj, hp)
            hb = (hd < 0.35).sum(1).tolist()
        com_l = md.compute_center_of_mass(traj.atom_slice(lh))
        # pocket = protein atoms within 0.4 nm of the ligand in the FIRST frame (a fixed reference region, so the COM
        # distance is measured from the same place all run); all-frame contacts above are separate
        p0 = [int(j) for (_, j), on in zip(near_pairs, contacts[0])] if len(near_pairs) else []
        pocket = sorted(set(p0)) or (sorted({int(j) for _, j in near_pairs}) if len(near_pairs) else list(prot_heavy[:1]))
        com_p = md.compute_center_of_mass(traj.atom_slice(np.array(pocket)))
        out["ligands"][rn] = {
            "rmsd_in_pocket_A": lrmsd.tolist(),
            "contact_residues": n_contact_res,
            "polar_contacts": hb,
            "com_distance_to_pocket_A": (np.linalg.norm(com_l - com_p, axis=1) * 10).tolist(),
            "contact_frequency": {lab[k]: v / traj.n_frames for k, v in sorted(res_freq.items(), key=lambda kv: -kv[1])},
            "contact_residue_ids": {lab[k]: k for k in res_freq},
            # kept for compatibility only; the report reads `ligand_state` (D-97, A4)
            "stays_bound": bool(np.mean(lrmsd[-max(1, len(lrmsd) // 5):]) < 3.0),
            "rmsd_reference": "first stored production frame (not the docking pose), protein-frame, no ligand refit, "
                              "no symmetry correction",
        }
        out["ligands"][rn]["ligand_state"] = ligand_state(lrmsd, n_contact_res, out["ligands"][rn]["com_distance_to_pocket_A"],
                                                          t_ns)
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


_VARIANT = {"HID": "HIS", "HIE": "HIS", "HIP": "HIS", "HSD": "HIS", "HSE": "HIS", "HSP": "HIS", "CYX": "CYS", "CYM": "CYS",
            "ASH": "ASP", "GLH": "GLU", "LYN": "LYS"}


def residue_keys(names: list[str]) -> list[str]:
    """"HIE57" → "HIS57" (protonation variants folded); repeats (several chains) get "#2", "#3"."""
    out, seen = [], {}
    for n in names:
        k = _VARIANT.get(n[:3], n[:3]) + n[3:]
        seen[k] = seen.get(k, 0) + 1
        out.append(k if seen[k] == 1 else f"{k}#{seen[k]}")
    return out


def ca_labels(top, atom_indices) -> list[str]:
    """chain:residue-number per Cα.  The residue *name* is left out on purpose: HID/HIE/HIP or CYX can differ between
    the apo and the complex build of the same protein (D-106)."""
    out = []
    for i in atom_indices:
        r = top.atom(int(i)).residue
        ch = getattr(r.chain, "chain_id", None) or str(r.chain.index)
        out.append(f"{ch}:{r.resSeq}")
    return out


def save_ca_coordinates(traj, adir: Path, ligand_groups=None, max_frames: int = 250, *, resolution: dict | None = None) -> None:
    """analysis/ca_xyz.npy (frames ≤ max_frames, Å, already centred and superposed) + ca_labels.json.

    D-135 (R3): the kept frames are a uniform subsample of the analysed frames, and ca_labels.json now says so
    (`sampling`: n kept of N, scheme, role, plus the stride/cadence context in `resolution`) so the common basis can
    report what its populations are made of."""
    try:
        lig = {int(i) for v in (ligand_groups or {}).values() for i in v}
        ca = [int(i) for i in traj.topology.select("protein and name CA") if int(i) not in lig]
        if not ca:
            return
        sel = np.unique(np.linspace(0, traj.n_frames - 1, min(max_frames, traj.n_frames)).round().astype(int))
        np.save(Path(adir) / "ca_xyz.npy", (traj.xyz[sel][:, ca, :] * 10.0).astype(np.float32))
        t = (np.asarray(traj.time)[sel] / 1000.0).round(4).tolist() if traj.time is not None and len(traj.time) == traj.n_frames else sel.tolist()
        sampling = {"scheme": "uniform subsample: np.linspace(0, N-1, n).round().astype(int), unique indices",
                    "role": "estimator input for the common-basis PCA/landscape (not a display-only thinning)",
                    "max_frames": int(max_frames), "n_frames_analysed": int(traj.n_frames), "n_kept": int(len(sel)),
                    "resolution": resolution}
        atomic_write_json({"labels": ca_labels(traj.topology, ca), "time_ns": t, "sampling": sampling},
                          Path(adir) / "ca_labels.json", backup=False)
    except Exception:  # noqa: BLE001 — the comparison is optional; the per-system analysis stands
        pass


def _resolution_context(traj, stride: int, n_source: int | None) -> dict:
    """Source cadence, stride and counts of the trajectory `traj` that analyse_run loaded (D-135, R3)."""
    from .persistence import resolution_record
    rec = resolution_record(traj.time if traj.time is not None and len(traj.time) else None, effective_stride=int(stride),
                            n_frames_source=n_source, origin="frames of the analysed trajectory (after any memory stride)")
    if rec["n_frames_used"] == 0:
        rec["n_frames_used"] = int(traj.n_frames)
    return rec


def analyse_run(run_dir: Path | str, topology_pdb: Path | str, *, stride: int = 1, label: str = "",
                ligand_groups: dict[str, list[int]] | None = None, metal_indices: list[int] | None = None,
                decisions=None, ligand_charges: dict[str, dict[int, int]] | None = None,
                fingerprint: dict | None = None, provenance: dict | None = None) -> dict:
    """ligand_charges (D-98) = {ligand name: {full-system atom index: ±1}} from the build manifest; a ligand absent
    from it has an unknown charge (no salt bridge is called for it).

    D-135: `fingerprint` (analysis.fingerprint.analysis_fingerprint, computed by the caller BEFORE the analysis so the
    reuse check and the stored value are the same) is stored in analysis_manifest.json; computed here when absent.  The
    JSON/NPY outputs are staged and swapped in together with the manifest (written last), keeping the previous result
    (analysis_manifest.prev.json, analysis/prev/) — an interrupted regeneration never replaces a complete result."""
    from .fingerprint import analysis_fingerprint, begin_staging, commit_staging
    run_dir = Path(run_dir)
    if fingerprint is None:
        fingerprint = analysis_fingerprint(run_dir, topology_pdb, ligand_groups=ligand_groups, metal_indices=metal_indices,
                                           ligand_charges=ligand_charges)
    orig_charges = ligand_charges
    staging = begin_staging(run_dir)
    # long runs (docs/specs/long_timescale.md): solute-only DCDs renumber atoms; a trajectory too large for memory
    # is read with a stride here and at full resolution by the streaming pass below
    from .stream import production_info, production_topology, remap_groups, remap_indices, remap_charges, \
        dcd_frame_count, choose_stride, stream_production_metrics
    full_groups, full_metals = ligand_groups, metal_indices
    pinfo = production_info(run_dir)
    if pinfo["dcd_atoms"] == "solute":
        _, subset = production_topology(run_dir, topology_pdb)
        ligand_groups, metal_indices = remap_groups(ligand_groups, subset), remap_indices(metal_indices, subset)
        ligand_charges = remap_charges(ligand_charges, subset)
    auto_stride = 1
    n_fr = None
    if pinfo["dcds"] and pinfo.get("dcd_atom_count"):
        n_fr = sum(dcd_frame_count(p, int(pinfo["dcd_atom_count"])) for p in pinfo["dcds"])
    if stride == 1 and n_fr:
        auto_stride = choose_stride(n_fr, int(pinfo["dcd_atom_count"]))
        if auto_stride > 1:
            stride = auto_stride
            if decisions is not None:
                decisions.record("analysis.memory", "stride", auto_stride,
                                 f"production 約 {n_fr:,} 幀、每幀 {pinfo['dcd_atom_count']:,} 個原子，整份讀進記憶體超過上限；"
                                 f"一般分析改為每 {auto_stride} 幀取一幀，RMSD、RMSF 與接觸頻率另以分段串流讀取全部幀"
                                 "（analysis/stream_metrics.json）。", kind="auto_fixed")
    traj = load_production(run_dir, topology_pdb, stride=stride, metal_indices=metal_indices)
    m = compute_metrics(traj, ligand_groups)
    adir = run_dir / "analysis"
    adir.mkdir(parents=True, exist_ok=True)
    res_rec = _resolution_context(traj, stride, n_fr)  # D-135: source vs effective cadence of everything below
    m["resolution"] = res_rec
    save_ca_coordinates(traj, staging, ligand_groups, resolution=res_rec)     # D-106: for the common basis across systems
    try:
        cen = export_centered(run_dir, topology_pdb, metal_indices=metal_indices, ligand_groups=ligand_groups, stride=stride)
    except Exception as exc:  # noqa: BLE001 — the centred export is a convenience; metrics above are already imaged
        cen = {"error": f"{type(exc).__name__}: {exc}"}
    m["pbc"] = cen
    if auto_stride > 1:
        m["stride"] = auto_stride
        try:
            sm = stream_production_metrics(run_dir, topology_pdb, ligand_groups=full_groups, metal_indices=full_metals,
                                           out_dir=staging)
            m["stream_metrics_file"] = str(adir / "stream_metrics.json")
            m["stream_n_frames"] = sm["n_frames"]
        except Exception as exc:  # noqa: BLE001 — the strided metrics above remain; the failure is recorded
            m["stream_error"] = f"{type(exc).__name__}: {exc}"
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
    summary = {"status": "PASS", "resolution": res_rec, "restrained_production": restrained, "metrics_file": str(adir / "metrics.json"), "figures": figs, "created_at": now_iso(),
               "n_frames": m["n_frames"], "centered": {k: v for k, v in cen.items() if k != "pbc_checks"},
               "pbc_checks": cen.get("pbc_checks", {}),
               "rmsd_backbone_mean_A": float(np.mean(m["rmsd_backbone_A"])) if "rmsd_backbone_A" in m else None,
               "ligands": {rn: {"stays_bound": d["stays_bound"], "rmsd_last20_A": float(np.mean(d["rmsd_in_pocket_A"][-max(1, len(d["rmsd_in_pocket_A"]) // 5):])),
                                "top_contacts": list(d["contact_frequency"].items())[:5],
                                # D-97 (A4): state from contacts + COM + RMSD; restraints stated with it
                                "state": {k: v for k, v in (d.get("ligand_state") or {}).items() if k != "per_frame"}
                                | {"restraints": restrained}}
                           for rn, d in m["ligands"].items()}}
    # D-58: extended analyses (hydrogen bonds, SASA, secondary structure, PCA, clustering, correlations, fingerprint,
    # water bridges) — independent of the metrics above; a failure is recorded, never fatal
    try:
        from .extended import extended_metrics
        groups = ligand_groups
        if groups is None:
            top = traj.topology
            groups = {rn: top.select(f"resname {rn} and not element H").tolist() for rn in _ligand_resnames(top)}
        ext = extended_metrics(traj, groups, ligand_charges=ligand_charges,
                               resolution={"effective_stride": int(stride), "n_frames_source": n_fr})
        if stride > 1:
            # R3: contact events must not be judged on decimated frames — repeat the persistence on every stored frame
            try:
                from .stream import stream_production_persistence
                sp = stream_production_persistence(run_dir, topology_pdb, ligand_groups=full_groups, metal_indices=full_metals,
                                                   ligand_charges=orig_charges, out_dir=staging)
                for rn, per in (sp.get("ligands") or {}).items():
                    fpb = ((ext.get("ligands") or {}).get(rn) or {}).get("fingerprint")
                    if fpb is not None:
                        fpb["persistence_decimated_status"] = (fpb.get("persistence") or {}).get("status")
                        fpb["persistence"] = per
                ext["streamed_persistence_file"] = str(adir / "stream_persistence.json")
                summary["streamed_persistence_file"] = ext["streamed_persistence_file"]
            except Exception as exc:  # noqa: BLE001 — the decimated persistence stays, marked "limited"; the failure is recorded
                ext["streamed_persistence_error"] = f"{type(exc).__name__}: {exc}"
                summary["streamed_persistence_error"] = ext["streamed_persistence_error"]
        atomic_write_json(ext, staging / "extended.json", backup=False)
        summary["extended_file"] = str(adir / "extended.json")
        summary["extended_errors"] = {**ext.get("errors", {}), **{f"{k}:{n}": e for k, l in (ext.get("ligands") or {}).items()
                                                                   for n, e in (l.get("errors") or {}).items()}}
    except Exception as exc:  # noqa: BLE001
        summary["extended_errors"] = {"all": f"{type(exc).__name__}: {exc}"}
    atomic_write_json(m, staging / "metrics.json", backup=False)
    return commit_staging(run_dir, staging, summary, fingerprint=fingerprint,
                          provenance={"reason": (provenance or {}).get("reason", "analysis run"), **(provenance or {})})


def compare_runs(metrics: dict[str, dict], out_dir: Path | str, comparability: dict | None = None) -> dict:
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
    # residues whose flexibility changes most on binding (first pair apo vs first holo).  D-106 (F10): residues
    # matched by name+number (protonation variants folded), never by position; refused when the runs differ
    labs = list(metrics)
    delta = None
    if len(labs) >= 2 and "rmsf_ca_A" in metrics[labs[0]] and "rmsf_ca_A" in metrics[labs[1]]:
        from .common_basis import delta_rmsf
        a, b = metrics[labs[0]], metrics[labs[1]]
        r = delta_rmsf((residue_keys(a.get("rmsf_residues") or []), a["rmsf_ca_A"]),
                       (residue_keys(b.get("rmsf_residues") or []), b["rmsf_ca_A"]), comparability)
        delta = r.get("most_rigidified") if r.get("status") == "ok" else None
        figs_note = r
    else:
        figs_note = None
    return {"figures": figs, "most_rigidified_on_binding": delta, "delta_rmsf": figs_note}
