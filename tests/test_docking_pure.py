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
    for i in infos:
        i.contacts = max(i.contacts, 12)
    pick = recommend_pose(infos)
    assert pick.rank == 2 and pick.cluster_size == 3
    assert "Vina 分數誤差" in pick.reason and "3 個 pose" in pick.reason


def _line_lig(x0, n=5):
    return np.array([[x0 + 1.5 * k, 0.0, 0.0] for k in range(n)])


def test_joint_pose_rules_each_one():
    from md20.docking.poses import recommend_pose
    a = _line_lig(0)                                   # atoms at x = 0 … 6
    clash, good, far = _line_lig(6.5), _line_lig(9.8), _line_lig(16.0)   # min distances 0.5, 3.8, 10.0 Å
    sl = [slice(0, 5), slice(5, 10)]
    infos = analyse_poses([np.vstack([a, clash]), np.vstack([a, good]), np.vstack([a, far])], [-12.0, -11.6, -11.5],
                          per_ligand_slices=sl)
    for i in infos:
        i.contacts_per_ligand = [20, 20]
    pick = recommend_pose(infos)
    assert pick.rank == 2 and "共同佔據且無碰撞" in pick.reason
    assert any("碰撞" in r for r in infos[0].rejected) and any("未共同佔據" in r for r in infos[2].rejected)
    # one ligand shallow → rejected even with perfect distance
    infos[1].contacts_per_ligand = [25, 3]
    infos2 = analyse_poses([np.vstack([a, good])], [-11.6], per_ligand_slices=sl)
    infos2[0].contacts_per_ligand = [25, 3]
    assert recommend_pose(infos2) is None and "一深一淺" in infos2[0].extra["recommendation"]["reason"]


def test_no_candidate_means_no_recommendation():
    from md20.docking.poses import recommend_pose
    infos = analyse_poses([_pose((0, 0, 0)), _pose((5, 0, 0))], [-7.0, -6.8])
    for i in infos:
        i.contacts = 2                                  # all on the surface
    assert recommend_pose(infos) is None
    assert infos[0].extra["recommendation"]["status"] == "NEEDS_HUMAN"


def test_pocket_too_small_and_same_sign_charges():
    from md20.docking.poses import recommend_pose
    sl = [slice(0, 5), slice(5, 10)]
    infos = analyse_poses([np.vstack([_line_lig(0), _line_lig(9.8)])], [-10.0], per_ligand_slices=sl)
    infos[0].contacts_per_ligand = [20, 20]
    assert recommend_pose(infos, pocket_volume_A3=150, ligand_volume_A3=180) is None
    assert "只容得下一個" in infos[0].extra["recommendation"]["reason"]
    pick = recommend_pose(infos, ligand_charges=[1, 1], pocket_volume_A3=900, ligand_volume_A3=180)
    assert pick is not None and "同號淨電荷" in pick.reason and infos[0].extra["recommendation"]["status"] == "AUTO_FIXED"


def test_redocking_self_check_blocks():
    from md20.docking.poses import recommend_pose
    ref = _pose((0, 0, 0))
    infos = analyse_poses([ref + 3.0, ref + 3.1], [-7.0, -6.9], reference_xyz=ref)
    for i in infos:
        i.contacts = 30
    assert recommend_pose(infos) is None and "Redocking 自檢未通過" in infos[0].extra["recommendation"]["reason"]


def test_pocket_volume_cavity_vs_open():
    from md20.docking.poses import pocket_volume
    # hollow sphere of receptor atoms (radius 9 Å) → buried cavity inside; empty space → 0
    pts = []
    for th in np.linspace(0, np.pi, 18):
        for ph in np.linspace(0, 2 * np.pi, 36, endpoint=False):
            pts.append([9 * np.sin(th) * np.cos(ph), 9 * np.sin(th) * np.sin(ph), 9 * np.cos(th)])
    shell = np.array(pts)
    v = pocket_volume(shell, (0, 0, 0), (14, 14, 14))
    assert 300 < v < 3000
    assert pocket_volume(np.array([[50.0, 50.0, 50.0]]), (0, 0, 0), (10, 10, 10)) == 0.0


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


def test_docking_result_load_ignores_stamp(tmp_path):
    """Workflow resume reads docking_results.json written by atomic_write_json, which adds the `_md20` stamp."""
    from md20.docking.run import DockingResult
    from md20.util import atomic_write_json
    r = DockingResult(mode="independent", receptor_pdbqt="r.pdbqt", box={"center": [0, 0, 0]}, params={}, entries=[{"name": "BEN"}])
    atomic_write_json(r.to_dict(), tmp_path / "docking_results.json")
    assert "_md20" in (tmp_path / "docking_results.json").read_text(encoding="utf-8")
    back = DockingResult.load(tmp_path / "docking_results.json")
    assert back.entry("BEN") == {"name": "BEN"} and back.mode == "independent"
