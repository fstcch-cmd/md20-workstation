"""Synthetic SMD pull for the contact-release tests and the report template (D-116): a one-atom ligand moves along +x
away from residues placed along the path; a residue at position p is in contact (< 0.40 nm) while |d - p| < 0.40."""
import numpy as np

from md20.analysis import smd_contacts as SC


def synth_path(positions: dict, *, d0=0.4, d1=2.0, n_frames=100, box_len=8.0, wrap=False, dy=0.0):
    """positions = {label: p_nm}.  Residues have two atoms (0.05 nm apart in z).  Returns the dict `load_path` gives."""
    d = np.linspace(d0, d1, n_frames)
    labels = list(positions)
    F = n_frames
    atoms = 1 + 2 * len(labels)
    xyz = np.zeros((F, atoms, 3))
    xyz[:, 0, 0] = d
    xyz[:, 0, 1] = dy
    for k, lab in enumerate(labels):
        for j in range(2):
            xyz[:, 1 + 2 * k + j, 0] = positions[lab]
            xyz[:, 1 + 2 * k + j, 2] = 0.05 * j
    xyz += 1.0
    if wrap:
        xyz %= box_len
    box = np.tile(np.diag([box_len] * 3), (F, 1, 1))
    return {"time_ps": np.linspace(0, 300, F), "d_nm": d, "r0_nm": d + 0.1, "xyz_nm": xyz.astype(np.float32),
            "box_nm": box.astype(np.float32), "atom_index": np.arange(atoms),
            "atom_res": np.array([-1] + [k for k in range(len(labels)) for _ in range(2)]),
            "atom_name": np.array(["C1"] + ["CA", "CB"] * len(labels)),
            "is_ligand": np.array([True] + [False] * (atoms - 1)), "res_labels": np.array(labels), "meta": {"n_residues": len(labels)}}


def synth_curve(peak_d=0.9, n=300, d0=0.4, d1=2.0, seed=1):
    d = np.linspace(d0, d1, n)
    f = 600 * np.exp(-((d - peak_d) / 0.1) ** 2) + np.random.default_rng(seed).normal(0, 10, n)
    return {"time_ps": np.linspace(0, 300, n), "r0_nm": d + 0.05, "d_nm": d, "force": f}


def save(out_dir, path):
    return SC.save_path(out_dir, time_ps=path["time_ps"], d_nm=path["d_nm"], r0_nm=path["r0_nm"], xyz_nm=path["xyz_nm"],
                        box_nm=path["box_nm"], atom_index=path["atom_index"], atom_res=path["atom_res"],
                        atom_name=path["atom_name"], is_ligand=path["is_ligand"], res_labels=path["res_labels"],
                        meta=path["meta"])
