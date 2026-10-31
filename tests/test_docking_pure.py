"""Docking logic that needs no Vina/Meeko: receptor typing and pose recommendation."""
import numpy as np

from md20.docking import receptor_to_pdbqt, ad4_type, analyse_poses, recommend_pose, cluster_poses, box_from_coords


def _line(serial, name, resname, resid, xyz, el, rec="ATOM  "):
    return (f"{rec}{serial:5d} {name:<4} {resname:>3} A{resid:>4}    {xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}  1.00  0.00          {el:>2}")


def test_receptor_pdbqt_types(tmp_path):
    lines = [
        _line(1, "N", "SER", 1, (0, 0, 0), "N"), _line(2, "H", "SER", 1, (0, 1.0, 0), "H"),
        _line(3, "CA", "SER", 1, (1.45, 0, 0), "C"), _line(4, "HA", "SER", 1, (1.45, -1.0, 0), "H"),
        _line(5, "OG", "SER", 1, (2.0, 1.3, 0), "O"), _line(6, "HG", "SER", 1, (2.9, 1.4, 0), "H"),
        _line(7, "CG", "PHE", 2, (5, 0, 0), "C"), _line(8, "CB", "PHE", 2, (6.5, 0, 0), "C"),
        _line(9, "ND1", "HIE", 3, (10, 0, 0), "N"), _line(10, "NE2", "HIE", 3, (12, 0, 0), "N"),
        _line(11, "HE2", "HIE", 3, (12.9, 0.5, 0), "H"), _line(12, "ZN", "ZN", 4, (20, 0, 0), "ZN", rec="HETATM"),
    ]
    src = tmp_path / "r.pdb"; src.write_text("\n".join(lines))
    counts = receptor_to_pdbqt(src, tmp_path / "r.pdbqt")
    out = (tmp_path / "r.pdbqt").read_text().splitlines()
    types = [l[77:79].strip() for l in out if l.startswith(("ATOM", "HETATM"))]
    names = [l[12:16].strip() for l in out if l.startswith(("ATOM", "HETATM"))]
    t = dict(zip(names, types))
    assert t["N"] == "N" and t["H"] == "HD" and t["OG"] == "OA" and t["HG"] == "HD" and t["CA"] == "C"
    assert "HA" not in t                                   # non-polar H dropped
    assert t["CG"] == "A" and t["CB"] == "C"               # aromatic vs aliphatic carbon
    assert t["ND1"] == "NA" and t["NE2"] == "N"            # HIE: ND1 unprotonated acceptor
    assert t["ZN"] == "Zn"
    assert counts["HD"] == 3 and all(len(l) >= 79 for l in out if l.startswith("ATOM"))
    # columns Vina reads: x,y,z at 30-54, charge at 70-76, type at 77-79
    l = next(l for l in out if " OG " in l)
    assert float(l[30:38]) == 2.0 and float(l[70:76]) == 0.0


def test_ad4_type_cofactor_atoms():
    assert ad4_type("P", "ATP", "PA", has_h=False, is_hetatm=True) == "P"
    assert ad4_type("CL", "LIG", "CL1", has_h=False, is_hetatm=True) == "Cl"


def _pose(shift, n=8, seed=0):
    rng = np.random.default_rng(seed)
    base = rng.normal(0, 1.5, size=(n, 3))
    return base + np.asarray(shift, float)


def test_recommend_prefers_consensus_within_window():
    # pose 1: best score, unique; poses 2–4: 0.5 kcal/mol worse, same cluster (repeatedly found)
    coords = [_pose((10, 0, 0), seed=1), _pose((0, 0, 0)), _pose((0.3, 0, 0)), _pose((0, 0.3, 0)), _pose((20, 0, 0), seed=2)]
    scores = [-8.0, -7.5, -7.4, -7.3, -5.0]
    rec = np.vstack([_pose((0, 0, 3), n=60, seed=5), _pose((10, 0, 3), n=60, seed=6)])
    infos = analyse_poses(coords, scores, receptor_xyz=rec)
    assert cluster_poses(coords, scores)[1:4] == [1, 1, 1]
    pick = recommend_pose(infos, min_contacts=1)
    assert pick.rank == 2 and pick.cluster_size == 3
    assert "Vina 分數誤差" in pick.reason and "3 個 pose" in pick.reason


def test_recommend_rejects_clashing_joint_pose():
    a1, b1 = _pose((0, 0, 0), n=5), _pose((0.2, 0, 0), n=5)          # overlapping ligands → clash
    a2, b2 = _pose((0, 0, 0), n=5), _pose((8, 0, 0), n=5)
    coords = [np.vstack([a1, b1]), np.vstack([a2, b2])]
    infos = analyse_poses(coords, [-12.0, -11.5], per_ligand_slices=[slice(0, 5), slice(5, 10)])
    assert infos[0].clash and not infos[1].clash
    pick = recommend_pose(infos, min_contacts=0)
    assert pick.rank == 2 and "無碰撞" in pick.reason


def test_reference_rmsd_reported():
    ref = _pose((0, 0, 0))
    infos = analyse_poses([ref + 0.1, ref + 3.0], [-7.0, -6.0], reference_xyz=ref)
    assert infos[0].rmsd_ref < 0.3 and infos[1].rmsd_ref > 4
    pick = recommend_pose(infos, min_contacts=0)
    assert "重現晶體" in pick.reason


def test_box_from_coords_bounds():
    b = box_from_coords(np.array([[0, 0, 0], [4, 2, 1]]), padding=6, min_size=18, max_size=32)
    assert b.center == (2.0, 1.0, 0.5) and b.size == (18.0, 18.0, 18.0)
    assert b.contains(np.array([2, 1, 0.5]))
