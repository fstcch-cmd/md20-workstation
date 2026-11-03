"""D-86 coarse-grained Martini 3 with the real tools (CI openmm-stack after `md20 setup-cg --yes`): martinize2,
insane, martini_openmm and OpenMM on the CPU.  Three small systems run a few thousand 20 fs steps each:
a POPC bilayer, a transmembrane helix in POPC (belt check) and a peptide above POPC (surface gap check).
MD20_CG=1 (set in CI) turns a missing tool into a failure instead of a skip."""
import math
import os

import numpy as np
import pytest

from md20.build import martini as M

_ready = not M.missing_tools(M.availability()) and M.forcefield_ready()
if not _ready:
    if os.environ.get("MD20_CG") == "1":
        raise RuntimeError(f"MD20_CG=1 but the CG tools are missing: {M.why_missing(M.availability())}, "
                           f"force field {'ready' if M.forcefield_ready() else 'missing'}")
    pytest.skip("Martini tools not installed (md20 setup-cg --yes)", allow_module_level=True)
pytest.importorskip("openmm")

from md20.analysis.cg import analyse_cg  # noqa: E402
from md20.build.cg_system import build_cg_system  # noqa: E402
from md20.engine.cg_run import run_cg  # noqa: E402

AA3 = {"A": "ALA", "L": "LEU", "K": "LYS", "G": "GLY", "W": "TRP", "S": "SER", "E": "GLU", "I": "ILE", "V": "VAL"}


def _place(a, b, c, bond, angle, torsion):
    """NeRF: position of d from a, b, c with |cd| = bond, ∠bcd = angle, dihedral abcd = torsion (degrees)."""
    angle, torsion = math.radians(angle), math.radians(torsion)
    bc = c - b; bc /= np.linalg.norm(bc)
    n = np.cross(b - a, bc); n /= np.linalg.norm(n)
    m = np.cross(n, bc)
    d2 = np.array([-bond * math.cos(angle), bond * math.sin(angle) * math.cos(torsion), bond * math.sin(angle) * math.sin(torsion)])
    return c + d2[0] * bc + d2[1] * m + d2[2] * n


def helix_pdb(seq: str, path, *, along_z: bool = True):
    """Ideal α-helix backbone (φ −57°, ψ −47°), side chains added by PDBFixer; axis on z, centred at the origin."""
    from openmm.app import PDBFile
    from pdbfixer import PDBFixer
    N = np.array([0.0, 1.458, 0.0]); CA = np.array([0.0, 0.0, 0.0]); C = np.array([1.525, 0.0, 0.0])
    atoms = []
    for i, aa in enumerate(seq):
        if i:
            N = _place(Np, CAp, Cp, 1.329, 116.2, -47.0)
            CA = _place(CAp, Cp, N, 1.458, 121.7, 180.0)
            C = _place(Cp, N, CA, 1.525, 111.2, -57.0)
        O = _place(N, CA, C, 1.231, 120.5, -47.0 + 180.0)
        atoms += [("N", N), ("CA", CA), ("C", C), ("O", O)]
        Np, CAp, Cp = N, CA, C
    xyz = np.array([p for _, p in atoms])
    ca = xyz[1::4]
    ax = np.linalg.svd(ca - ca.mean(0))[2][0]
    if along_z:
        z = np.array([0, 0, 1.0]); v = np.cross(ax, z); s = np.linalg.norm(v); c = float(ax @ z)
        vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
        R = np.eye(3) + vx + vx @ vx * ((1 - c) / (s * s)) if s > 1e-8 else np.eye(3)
        xyz = (xyz - ca.mean(0)) @ R.T
    lines = []
    for k, (name, _) in enumerate(atoms):
        r = k // 4
        x, y, zz = xyz[k]
        lines.append(f"ATOM  {k + 1:5d}  {name:<3s} {AA3[seq[r]]} A{r + 1:4d}    {x:8.3f}{y:8.3f}{zz:8.3f}  1.00  0.00           {name[0]}")
    raw = path.with_suffix(".bb.pdb")
    raw.write_text("\n".join(lines) + "\nEND\n", encoding="utf-8")
    fx = PDBFixer(filename=str(raw))
    fx.findMissingResidues(); fx.missingResidues = {}
    fx.findMissingAtoms(); fx.addMissingAtoms()
    with open(path, "w") as fh:
        PDBFile.writeFile(fx.topology, fx.positions, fh, keepIds=True)
    return path


def _run(man, tmp_path, ns=0.06):
    r = run_cg(man, tmp_path / "run", platform_name="CPU", nvt_ns=0.02, equil_ns=0.04, production_ns=ns, save_ps=6.0, chunk_ns=0.03)
    assert r["status"] == "COMPLETE"
    return analyse_cg(man, tmp_path / "run")


def test_cg_bilayer(tmp_path):
    man = build_cg_system(tmp_path / "b", kind="bilayer", lipids={"POPC": 1}, box_xy_nm=6.0, water_nm=2.5, salt_molar=0.15)
    assert dict(man["molecules"]).get("POPC", 0) > 60 and man["n_beads"] > 1000
    d = _run(man, tmp_path)
    assert 0.50 < np.mean(d["apl_nm2"]) < 0.80, d["apl_nm2"]
    assert 3.4 < np.mean(d["dpp_nm"]) < 4.8, d["dpp_nm"]
    assert all(0.0 < v < 0.8 for v in d["p2"].values()), d["p2"]


def test_cg_transmembrane_helix(tmp_path):
    pdb = helix_pdb("GKKLALLLALALLLALALLLALALLLKKG", tmp_path / "tm.pdb")
    man = build_cg_system(tmp_path / "p", kind="protein", protein_pdb=pdb, lipids={"POPC": 1}, box_xy_nm=6.5,
                          water_nm=2.5, oriented=True)
    assert man["n_protein_beads"] > 29 and abs(man["belt_offset_nm"]) <= 0.3
    assert set(man["secondary_structure"]) <= set("HGIEBTSC")
    d = _run(man, tmp_path)
    assert d["protein_rmsd_nm"][-1] < 0.6 and d["apl_includes_protein"]


def test_cg_peptide_on_surface(tmp_path):
    pdb = helix_pdb("GIGAVLKVLTTGLPALISWIKRKRQQ".replace("T", "S").replace("P", "A").replace("Q", "K").replace("R", "K"),
                    tmp_path / "pep.pdb", along_z=False)
    man = build_cg_system(tmp_path / "s", kind="surface", protein_pdb=pdb, lipids={"POPC": 1}, box_xy_nm=6.5,
                          water_nm=2.0, surface_distance_nm=1.0)
    assert man["surface_gap_nm"] >= 0.3
    d = _run(man, tmp_path)
    assert len(d["solute_dz_nm"]) == d["n_frames"] and 0.0 <= d["contact_frac"] <= 1.0
