"""Streaming analysis of long trajectories (md20/analysis/stream.py): pure numpy, a fake chunk iterator."""
import json
from types import SimpleNamespace

import numpy as np
import pytest

from md20.analysis.stream import (kabsch_align, StreamingMetrics, iter_chunks, dcd_frame_count, choose_stride,
                                  memory_gb, remap_groups, remap_indices, production_info, production_topology)
from md20.engine.longrun import dcd_frame_bytes


def _rot(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])


def _traj(n_frames=37, n_atoms=12, seed=0):
    rng = np.random.default_rng(seed)
    base = rng.normal(size=(n_atoms, 3))
    frames = []
    for f in range(n_frames):
        x = base + 0.05 * rng.normal(size=base.shape)
        frames.append(x @ _rot(0.1 * f).T + np.array([f * 0.3, -f * 0.1, 2.0]))   # rigid motion + noise
    return np.array(frames, dtype=np.float32)


def _batch(xyz, idx):
    """Reference implementation on the whole array (what mdtraj.rmsd / mdtraj.rmsf compute)."""
    a = kabsch_align(xyz, xyz[0].astype(float), idx)[:, idx]
    rmsd = np.sqrt(((a - xyz[0, idx]) ** 2).sum(-1).mean(-1)) * 10
    rmsf = np.sqrt(((a - a.mean(0)) ** 2).sum(-1).mean(0)) * 10
    return rmsd, rmsf


def test_kabsch_removes_rigid_motion():
    x = _traj(n_frames=1)[0].astype(float)
    moved = (x @ _rot(1.1).T + 3.0)[None]
    out = kabsch_align(moved, x, np.arange(len(x)))
    assert np.allclose(out[0], x, atol=1e-6)


@pytest.mark.parametrize("chunk", [1, 4, 10, 37])
def test_streaming_equals_whole_trajectory_for_any_chunk_size(chunk):
    xyz = _traj()
    idx = np.arange(12)
    rmsd, rmsf = _batch(xyz, idx)
    sm = StreamingMetrics(rmsd_atoms=idx, rmsf_atoms=idx)
    for i in range(0, len(xyz), chunk):
        sm.update(xyz[i:i + chunk], np.arange(i, min(i + chunk, len(xyz))) * 20.0)
    r = sm.result()
    assert r["n_frames"] == 37
    assert np.allclose(r["rmsd_A"], rmsd, atol=1e-4)
    assert np.allclose(r["rmsf_A"], rmsf, atol=1e-4)
    assert r["time_ns"][-1] == pytest.approx(36 * 0.02)


def test_contact_frequency_per_pair_and_residue():
    # atom 0 is the ligand; atoms 1, 2 belong to residue A, atom 3 to residue B
    xyz = np.zeros((4, 4, 3), dtype=np.float32)
    xyz[:, 1, 0] = [0.3, 0.3, 0.9, 0.9]          # A via atom 1: frames 0, 1
    xyz[:, 2, 0] = [0.9, 0.3, 0.3, 0.9]          # A via atom 2: frames 1, 2
    xyz[:, 3, 0] = [0.9, 0.9, 0.9, 0.2]          # B: frame 3
    sm = StreamingMetrics(contact_pairs=[[0, 1], [0, 2], [0, 3]], pair_residues=["A", "A", "B"])
    sm.update(xyz[:2]); sm.update(xyz[2:])
    r = sm.result()
    assert r["pair_frequency"] == [0.5, 0.5, 0.25]
    assert r["residue_frequency"] == {"A": 0.75, "B": 0.25}
    assert r["contact_residues"] == [1, 1, 1, 1]


def test_iter_chunks_uses_loader_and_prepare_in_order():
    calls = []

    def loader(path, top, chunk, stride):
        calls.append((path, top, chunk, stride))
        for k in range(2):
            yield SimpleNamespace(xyz=np.full((chunk, 2, 3), float(k)), path=path)

    seen = [(c.path, c.xyz[0, 0, 0], c.tag) for c in iter_chunks(["a.dcd", "b.dcd"], "TOP", chunk=3, stride=2, loader=loader,
                                                                 prepare=lambda c: SimpleNamespace(**vars(c), tag="ok"))]
    assert calls == [("a.dcd", "TOP", 3, 2), ("b.dcd", "TOP", 3, 2)]
    assert seen == [("a.dcd", 0.0, "ok"), ("a.dcd", 1.0, "ok"), ("b.dcd", 0.0, "ok"), ("b.dcd", 1.0, "ok")]


def test_frame_count_memory_and_stride(tmp_path):
    p = tmp_path / "x.dcd"
    p.write_bytes(b"\0" * (276 + 50 * dcd_frame_bytes(1000)))
    assert dcd_frame_count(p, 1000) == 50
    assert dcd_frame_count(tmp_path / "missing.dcd", 1000) == 0
    assert memory_gb(50000, 32000) == pytest.approx(50000 * 32000 * 36 / 1e9)
    assert choose_stride(500, 32000, budget_gb=4) == 1
    s = choose_stride(50000, 32000, budget_gb=4)
    assert s > 1 and memory_gb(50000 // s + 1, 32000) <= 4.2


def test_remap_to_solute_subset():
    subset = [0, 1, 2, 5, 9]
    assert remap_groups({"L01": [5, 9, 7]}, subset) == {"L01": [3, 4]}
    assert remap_indices([2, 3], subset) == [2]
    assert remap_groups(None, subset) is None and remap_indices([1], None) == [1]


def test_production_info_defaults_to_whole_system(tmp_path):
    d = tmp_path / "run" / "stages" / "production"
    d.mkdir(parents=True)
    (d / "production_complete.json").write_text(json.dumps({"result": {"dcd_paths": ["a.dcd"]}}))
    info = production_info(tmp_path / "run")
    assert info == {"dcds": ["a.dcd"], "dcd_atoms": "all", "dcd_atom_count": None}
    assert production_topology(tmp_path / "run", "top.pdb") == ("top.pdb", None)     # no mdtraj needed for old runs
