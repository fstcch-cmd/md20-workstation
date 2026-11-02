"""D-59: docking analysis figures — geometry helpers and the general scenario sentences (one test per scenario)."""
import numpy as np

from md20.report import docking_figs as D


def _sdf(path, xyz, elems=None):
    elems = elems or ["C"] * len(xyz)
    lines = ["X", "", "", f"{len(xyz):3d}  0  0  0  0  0  0  0  0  0999 V2000"]
    lines += [f"{x:10.4f}{y:10.4f}{z:10.4f} {e:<3} 0  0" for (x, y, z), e in zip(xyz, elems)]
    path.write_text("\n".join(lines + ["M  END", "$$$$"]) + "\n")
    return path


def lv(sents):
    return [s["level"] for s in sents]


def en(sents):
    return " ".join(s["text"][1] for s in sents)


def test_sdf_heavy_skips_hydrogens(tmp_path):
    p = _sdf(tmp_path / "a.sdf", [[0, 0, 0], [1, 0, 0], [0, 1, 0]], ["C", "H", "O"])
    assert D.sdf_heavy(p).shape == (2, 3)
    assert D.sdf_heavy(tmp_path / "missing.sdf") is None


def test_pose_rmsd_matrix_and_scenarios():
    a = np.zeros((5, 3))
    poses = [a, a + [0.5, 0, 0], a + [0, 0.5, 0], a + [6, 0, 0]]
    M = D.pose_rmsd_matrix(poses)
    assert np.allclose(M, M.T) and M[0, 1] == 0.5 and M[0, 3] == 6.0
    assert lv(D.classify_pose_rmsd("L", M, [-7, -6.9, -6.8, -5])) == ["good"]
    far = D.pose_rmsd_matrix([a, a + [5, 0, 0], a + [0, 5, 0]])
    assert lv(D.classify_pose_rmsd("L", far, [-7, -6.9, -6.8])) == ["note"] and "different binding modes" in en(D.classify_pose_rmsd("L", far, [0] * 3))
    assert np.isnan(D.pose_rmsd_matrix([a, np.zeros((4, 3))])[0, 1])        # different atom counts are not compared


def test_funnel_scenarios():
    good = [{"rmsd_ref": r, "score": -8 + 0.5 * r} for r in (0.5, 1.5, 3, 5)]
    assert lv(D.classify_funnel("L", good)) == ["good"]
    flat = [{"rmsd_ref": r, "score": s} for r, s in ((0.5, -8), (3, -7.9), (5, -8.0 + 0.001), (6, -7.95))]
    assert lv(D.classify_funnel("L", flat)) == ["note"]
    wrong = [{"rmsd_ref": r, "score": s} for r, s in ((0.5, -6), (4, -8), (6, -7))]
    assert lv(D.classify_funnel("L", wrong)) == ["caution"]
    assert D.classify_funnel("L", [{"rmsd_ref": None, "score": -5}] * 5) == []      # no co-crystal reference → no figure text


def test_positions_three_scenarios():
    box = {"size": [22, 22, 22]}
    one = np.random.default_rng(0).normal(0, 1.0, (9, 3))
    assert lv(D.classify_positions("L", one, box)) == ["good"]
    main = np.vstack([np.zeros((6, 3)) + np.random.default_rng(1).normal(0, 0.8, (6, 3)), [[8, 0, 0], [0, 9, 0], [0, 0, -9]]])
    s = D.classify_positions("L", main, box)
    assert lv(s) == ["note"] and "6 of 9 poses" in en(s) and "alternative" in en(s)
    many = np.array([[0, 0, 0], [8, 0, 0], [0, 8, 0], [-8, 0, 0], [0, -8, 0], [0, 0, 8]], float)
    assert lv(D.classify_positions("L", many, box)) == ["warn"]


def test_contact_map_core(tmp_path):
    pdb = tmp_path / "r.pdb"
    rows = []
    for i, (rn, x) in enumerate((("ASP", 0.0), ("SER", 3.0), ("TRP", 20.0))):
        rows.append(f"ATOM  {i + 1:5d}  CA  {rn} A{100 + i:4d}    {x:8.3f}{0:8.3f}{0:8.3f}  1.00  0.00           C")
    pdb.write_text("\n".join(rows) + "\nEND\n")
    prot = D.receptor_atoms(pdb)
    poses = [np.array([[1.0, 0, 0]]), np.array([[1.5, 0, 0]]), np.array([[19.0, 0, 0]])]
    res, M = D.contact_map(poses, prot)
    assert "ASP100" in res and M.shape[1] == 3
    core = D.classify_contact_map("L", res, M)
    assert lv(core) in (["good"], ["note"])
    none = D.classify_contact_map("L", ["A1", "B2"], np.array([[1, 0, 0], [0, 0, 1]]))
    assert lv(none) == ["note"] and "do not share" in en(none)


def test_ligand_compare():
    rows = [{"name": "A", "score": -7.0, "le": -0.35}, {"name": "B", "score": -6.5, "le": -0.45}]
    s = D.classify_ligand_compare(rows)
    assert "best score belongs to A" in en(s) and "ligand efficiency to B" in en(s) and "cannot be ordered" in en(s)
    assert D.classify_ligand_compare(rows[:1]) == []


def test_multi_ligand_classifiers():
    poses = [{"rank": r, "min_ll_distance": d, "contacts_per_ligand": c} for r, d, c in
             ((1, 3.6, [14, 12]), (2, 3.9, [13, 11]), (3, 2.4, [12, 11]), (4, 4.0, [12, 3]))]
    s = D.classify_joint_poses(poses, ["A", "B"], 1, [1, 1])
    assert lv(s)[0] == "good" and "2 of 4" in en(s) and "Ranks 3" in en(s) and "caution" in lv(s)
    assert lv(D.classify_joint_poses([dict(p, min_ll_distance=2.0) for p in poses], ["A", "B"], 1))[0] == "warn"
    cents = {"A": np.array([[0, 0, 0], [0.3, 0, 0], [5, 0, 0]], float), "B": np.array([[5, 0, 0], [5.2, 0, 0], [0, 0, 0]], float)}
    assert "exchange sites" in en(D.classify_joint_positions(cents))
    calm = {"A": np.array([[0, 0, 0], [0.3, 0, 0]], float), "B": np.array([[5, 0, 0], [5.2, 0, 0]], float)}
    assert lv(D.classify_joint_positions(calm)) == ["good"]
    M = np.array([[1, 1], [1, 1], [1, 1], [1, 0], [0, 1]])
    assert "share a subsite" in en(D.classify_subsites(["R1", "R2", "R3", "R4", "R5"], M, ["A", "B"]))
    sep = np.array([[1, 0], [1, 0], [1, 0], [1, 0], [0, 1], [0, 1], [0, 1], [0, 1]])
    assert "fully separate" in en(D.classify_subsites([f"R{i}" for i in range(8)], sep, ["A", "B"]))
    t = np.linspace(0, 10, 50)
    assert lv(D.classify_ll_distance({"L01-L02": (t, 5 + 0 * t)})) == ["good"]
    assert lv(D.classify_ll_distance({"L01-L02": (t, 5 + t)})) == ["warn"]
    assert lv(D.classify_ll_distance({"L01-L02": (t, 5 + 0 * t)}, restrained=True)) == ["good", "caution"]
