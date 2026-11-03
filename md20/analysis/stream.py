"""Streaming analysis of long production trajectories (docs/specs/long_timescale.md §2).

A 1 µs run saved every 20 ps is 50 000 frames; loaded whole by mdtraj (float32, plus the centred and aligned copies
analyse_run makes) a 30 000-atom system needs about 50 GB of memory.  This module reads the DCD in chunks
(`mdtraj.iterload`) and keeps running sums only, so backbone RMSD, Cα RMSF and pocket contact frequencies never need
the whole trajectory in memory:

    sm = StreamingMetrics(rmsd_atoms=bb, rmsf_atoms=ca, contact_pairs=pairs, pair_residues=res)
    for chunk in iter_chunks(dcds, top, chunk=500, prepare=center):   # any iterable of (F, N, 3) arrays works too
        sm.update(chunk.xyz, chunk.time)
    out = sm.result()

The numerics are plain numpy (Kabsch superposition, running first and second moments), so they are tested without
mdtraj; `stream_production_metrics` is the mdtraj entry point used by `traj.analyse_run`.

Also here: the solute-only trajectory topology (StageSpec.trajectory_atoms = "solute") and the memory estimate that
decides when analyse_run must stride or stream.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Callable, Iterable

import numpy as np

from ..util import atomic_write_json, load_json, now_iso

DEFAULT_MEMORY_GB = 4.0       # analyse_run budget for an in-memory load (override: MD20_ANALYSIS_MEM_GB)
COPIES_IN_MEMORY = 3          # analyse_run holds the loaded, centred and aligned trajectories at once


# ----------------------------------------------------------------------------------- numerics (pure numpy)
def kabsch_align(mobile: np.ndarray, ref: np.ndarray, fit: np.ndarray) -> np.ndarray:
    """Superpose every frame of `mobile` (F, N, 3) on `ref` (N, 3) using the atoms `fit`; returns the moved frames."""
    out = np.empty_like(mobile, dtype=np.float64)
    r = ref[fit].astype(np.float64)
    rc = r.mean(0)
    r0 = r - rc
    for f in range(mobile.shape[0]):
        x = mobile[f].astype(np.float64)
        xc = x[fit].mean(0)
        p = x[fit] - xc
        h = p.T @ r0
        u, _, vt = np.linalg.svd(h)
        d = np.sign(np.linalg.det(u @ vt)) or 1.0
        rot = u @ np.diag([1.0, 1.0, d]) @ vt
        out[f] = (x - xc) @ rot + rc
    return out


class StreamingMetrics:
    """Running RMSD (to the first frame), RMSF (about the mean, after superposition on the RMSF atoms, as
    mdtraj.rmsf) and contact frequencies.  Units follow the input (nm); results are reported in Å."""

    def __init__(self, *, rmsd_atoms=None, rmsf_atoms=None, contact_pairs=None, pair_residues=None,
                 cutoff_nm: float = 0.4):
        self.rmsd_atoms = None if rmsd_atoms is None or not len(rmsd_atoms) else np.asarray(rmsd_atoms, dtype=int)
        self.rmsf_atoms = None if rmsf_atoms is None or not len(rmsf_atoms) else np.asarray(rmsf_atoms, dtype=int)
        self.pairs = None if contact_pairs is None or not len(contact_pairs) else np.asarray(contact_pairs, dtype=int)
        self.cutoff = float(cutoff_nm)
        self.ref: np.ndarray | None = None
        self.n = 0
        self.rmsd: list[float] = []
        self.time_ps: list[float] = []
        self._s1 = self._s2 = None
        self._pair_count = None
        if self.pairs is not None:
            res = np.asarray(pair_residues if pair_residues is not None else np.arange(len(self.pairs)))
            self._res_keys, inv = np.unique(res, return_inverse=True)
            self._order = np.argsort(inv, kind="stable")
            self._starts = np.searchsorted(inv[self._order], np.arange(len(self._res_keys)))
            self._res_count = np.zeros(len(self._res_keys), dtype=np.int64)
            self._pair_count = np.zeros(len(self.pairs), dtype=np.int64)
            self.n_contact_residues: list[int] = []

    def update(self, xyz, time_ps=None) -> None:
        xyz = np.asarray(xyz)
        if xyz.ndim == 2:
            xyz = xyz[None]
        if not len(xyz):
            return
        if self.ref is None:
            self.ref = xyz[0].astype(np.float64).copy()
        if self.rmsd_atoms is not None:
            a = kabsch_align(xyz, self.ref, self.rmsd_atoms)[:, self.rmsd_atoms]
            d = a - self.ref[self.rmsd_atoms]
            self.rmsd += (np.sqrt((d ** 2).sum(-1).mean(-1)) * 10.0).tolist()
        if self.rmsf_atoms is not None:
            a = kabsch_align(xyz, self.ref, self.rmsf_atoms)[:, self.rmsf_atoms]
            if self._s1 is None:
                self._s1 = np.zeros(a.shape[1:]); self._s2 = np.zeros(a.shape[1])
            self._s1 += a.sum(0)
            self._s2 += (a ** 2).sum(-1).sum(0)
        if self.pairs is not None:
            dist = np.linalg.norm(xyz[:, self.pairs[:, 0]] - xyz[:, self.pairs[:, 1]], axis=-1)
            c = dist < self.cutoff
            self._pair_count += c.sum(0)
            per_res = np.add.reduceat(c[:, self._order].astype(np.int32), self._starts, axis=1) > 0
            self._res_count += per_res.sum(0)
            self.n_contact_residues += per_res.sum(1).tolist()
        if time_ps is not None and len(np.atleast_1d(time_ps)) == len(xyz):
            self.time_ps += np.atleast_1d(time_ps).astype(float).tolist()
        self.n += len(xyz)

    def result(self) -> dict:
        out: dict = {"n_frames": int(self.n)}
        if self.time_ps:
            out["time_ns"] = [t / 1000.0 for t in self.time_ps]
        if self.rmsd_atoms is not None:
            out["rmsd_A"] = self.rmsd
        if self.rmsf_atoms is not None and self.n:
            mean = self._s1 / self.n
            msd = self._s2 / self.n - (mean ** 2).sum(-1)
            out["rmsf_A"] = (np.sqrt(np.clip(msd, 0.0, None)) * 10.0).tolist()
        if self.pairs is not None and self.n:
            out["pair_frequency"] = (self._pair_count / self.n).tolist()
            out["residue_frequency"] = {str(k): float(v) / self.n for k, v in zip(self._res_keys, self._res_count)}
            out["contact_residues"] = self.n_contact_residues
        return out


# ----------------------------------------------------------------------------------- trajectories on disk
def dcd_frame_count(path: Path | str, n_atoms: int, unit_cell: bool = True) -> int:
    """Frames in an OpenMM DCD from its size (header ≈ 276 bytes), without reading it."""
    from ..engine.longrun import dcd_frame_bytes
    size = Path(path).stat().st_size if Path(path).is_file() else 0
    return max(0, (size - 276) // dcd_frame_bytes(n_atoms, unit_cell))


def memory_gb(n_frames: int, n_atoms: int, copies: int = COPIES_IN_MEMORY) -> float:
    return n_frames * n_atoms * 12 * copies / 1e9


def choose_stride(n_frames: int, n_atoms: int, budget_gb: float | None = None) -> int:
    """Smallest stride that keeps an in-memory analyse_run under the budget (1 = no change)."""
    budget = float(budget_gb if budget_gb is not None else os.environ.get("MD20_ANALYSIS_MEM_GB", DEFAULT_MEMORY_GB))
    need = memory_gb(n_frames, n_atoms)
    return 1 if need <= budget or budget <= 0 else int(math.ceil(need / budget))


def production_info(run_dir: Path | str) -> dict:
    """DCD paths and which atoms they hold, from production_complete.json."""
    comp = load_json(Path(run_dir) / "stages" / "production" / "production_complete.json", {})
    info = comp.get("backend_info") or {}
    return {"dcds": (comp.get("result") or {}).get("dcd_paths") or [], "dcd_atoms": info.get("dcd_atoms", "all"),
            "dcd_atom_count": info.get("dcd_atom_count")}


def remap_groups(groups: dict | None, subset: list[int] | None) -> dict | None:
    """Full-system atom indices → indices in a solute-only trajectory (atoms outside the subset are dropped)."""
    if groups is None or subset is None:
        return groups
    pos = {int(a): i for i, a in enumerate(subset)}
    return {k: [pos[int(i)] for i in v if int(i) in pos] for k, v in groups.items()}


def remap_indices(idx: list[int] | None, subset: list[int] | None) -> list[int] | None:
    if idx is None or subset is None:
        return idx
    pos = {int(a): i for i, a in enumerate(subset)}
    return [pos[int(i)] for i in idx if int(i) in pos]


def production_topology(run_dir: Path | str, topology_pdb: Path | str):
    """(topology for md.load / iterload, subset indices or None).  A solute-only DCD gets the build topology cut with
    the same residue rule the backend used; a count mismatch stops instead of reading atoms as the wrong ones."""
    info = production_info(run_dir)
    if info["dcd_atoms"] != "solute":
        return str(topology_pdb), None
    import mdtraj as md
    from ..engine.longrun import solute_atom_indices
    full = md.load_topology(str(topology_pdb))
    subset = solute_atom_indices([a.residue.name for a in full.atoms])
    if info.get("dcd_atom_count") not in (None, len(subset)):
        raise RuntimeError(f"只存溶質的 DCD 有 {info['dcd_atom_count']} 個原子，但依拓樸算出的溶質是 {len(subset)} 個；"
                           "拓樸檔可能被換過，不能確定原子對應，停止分析。")
    return full.subset(subset), subset


def iter_chunks(dcds: Iterable, top, *, chunk: int = 500, stride: int = 1, prepare: Callable | None = None,
                loader: Callable | None = None):
    """Yield trajectory chunks from each DCD in order.  `loader(path, top, chunk, stride)` defaults to mdtraj.iterload;
    `prepare(chunk)` (e.g. PBC centring) is applied to each chunk before it is yielded."""
    if loader is None:
        import mdtraj as md

        def loader(p, t, c, s):
            return md.iterload(str(p), top=t, chunk=c, stride=s)
    for p in dcds:
        for ch in loader(p, top, int(chunk), int(stride)):
            yield prepare(ch) if prepare is not None else ch


def stream_production_metrics(run_dir: Path | str, topology_pdb: Path | str, *, ligand_groups: dict | None = None,
                              metal_indices: list[int] | None = None, chunk: int = 500) -> dict:
    """Full-resolution backbone RMSD, Cα RMSF and pocket contact frequencies, chunk by chunk (mdtraj required).
    Writes analysis/stream_metrics.json.  `ligand_groups` and `metal_indices` are full-system indices."""
    from .traj import center_trajectory, _ligand_resnames
    run_dir = Path(run_dir)
    info = production_info(run_dir)
    if not info["dcds"]:
        raise FileNotFoundError("production 沒有 DCD")
    top, subset = production_topology(run_dir, topology_pdb)
    if isinstance(top, str):
        import mdtraj as md
        top = md.load_topology(top)
    groups = remap_groups(ligand_groups, subset)
    metals = remap_indices(metal_indices, subset)
    if groups is None:
        groups = {rn: top.select(f"resname {rn} and not element H").tolist() for rn in _ligand_resnames(top)}
    lig_all = np.array(sorted({i for v in groups.values() for i in v}), dtype=int)
    bb = np.setdiff1d(top.select("protein and backbone"), lig_all)
    ca = np.setdiff1d(top.select("protein and name CA"), lig_all)
    prot_heavy = np.setdiff1d(top.select("protein and not element H"), lig_all)

    def prepare(t):
        return center_trajectory(t, metal_indices=metals, superpose=False)

    chunks = iter_chunks(info["dcds"], top, chunk=chunk, prepare=prepare)
    first = next(chunks, None)
    if first is None:
        raise RuntimeError("DCD 沒有任何幀")
    per_lig = {}
    for name, idx in groups.items():
        lh = np.asarray(idx, dtype=int)
        if not len(lh) or not len(prot_heavy):
            continue
        pairs = np.array([[i, j] for i in lh for j in prot_heavy])
        d0 = np.linalg.norm(first.xyz[0, pairs[:, 0]] - first.xyz[0, pairs[:, 1]], axis=-1)
        near = pairs[d0 < 1.2]
        if len(near):
            res = [f"{top.atom(int(j)).residue.name}{top.atom(int(j)).residue.resSeq}" for j in near[:, 1]]
            per_lig[name] = StreamingMetrics(contact_pairs=near, pair_residues=res)
    prot = StreamingMetrics(rmsd_atoms=bb, rmsf_atoms=ca)
    for ch in [first]:
        prot.update(ch.xyz, ch.time)
        for sm in per_lig.values():
            sm.update(ch.xyz)
    for ch in chunks:
        prot.update(ch.xyz, ch.time)
        for sm in per_lig.values():
            sm.update(ch.xyz)
    p = prot.result()
    out = {"status": "PASS", "n_frames": p["n_frames"], "time_ns": p.get("time_ns", []),
           "rmsd_backbone_A": p.get("rmsd_A", []), "rmsf_ca_A": p.get("rmsf_A", []),
           "rmsf_residues": [f"{top.atom(int(i)).residue.name}{top.atom(int(i)).residue.resSeq}" for i in ca],
           "trajectory_atoms": info["dcd_atoms"], "chunk_frames": int(chunk), "created_at": now_iso(), "ligands": {}}
    for name, sm in per_lig.items():
        r = sm.result()
        freq = sorted(r.get("residue_frequency", {}).items(), key=lambda kv: -kv[1])
        out["ligands"][name] = {"contact_frequency": dict(freq), "contact_residues": r.get("contact_residues", [])}
    adir = run_dir / "analysis"
    adir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out, adir / "stream_metrics.json", backup=False)
    return out
