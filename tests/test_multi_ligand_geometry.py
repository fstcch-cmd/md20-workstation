"""D-60: multi-ligand complex geometry — ring piercing, overlaps, floating ligands, nudge repair, culprit naming."""
import numpy as np

from md20.build import multi_ligand as ML

ANG = np.linspace(0, 2 * np.pi, 7)[:-1]
BENZ = np.c_[1.39 * np.cos(ANG), 1.39 * np.sin(ANG), np.zeros(6)]


def ring(name, shift=(0, 0, 0)):
    return ML.Mol(name, ["C"] * 6, BENZ + shift)


def rod(name, a, b):
    return ML.Mol(name, ["C", "C"], np.array([a, b], float))


def shell(n=400, r=(5.0, 9.0), seed=0):
    rng = np.random.default_rng(seed)
    v = rng.normal(size=(n, 3)); v /= np.linalg.norm(v, axis=1, keepdims=True)
    return ML.Mol("protein", ["C"] * n, v * rng.uniform(*r, (n, 1)), bonds=[], is_protein=True)


def test_rings_and_piercing_geometry():
    A = ring("A")
    assert len(A.rings) == 1 and len(A.rings[0]) == 6
    assert ML.piercings(A, A.xyz, rod("B", [0.2, 0, -0.77], [0.2, 0, 0.77]), np.array([[0.2, 0, -0.77], [0.2, 0, 0.77]]))
    out = rod("C", [3.0, 0, -0.77], [3.0, 0, 0.77])            # crosses the plane outside the ring
    assert not ML.piercings(A, A.xyz, out, out.xyz)
    flat = rod("D", [0.2, 0, 1.0], [0.2, 0, 2.5])              # above the ring, does not cross
    assert not ML.piercings(A, A.xyz, flat, flat.xyz)


def test_hydrogen_bond_is_not_an_overlap():
    don = ML.Mol("D", ["N", "H"], np.array([[0, 0, 0], [1.01, 0, 0]]))
    acc = ML.Mol("A", ["O"], np.array([[2.9, 0, 0]]))           # H···O 1.89 Å, N···O 2.9 Å
    assert ML.overlaps(don, don.xyz, acc, acc.xyz) == []
    close = ML.Mol("A", ["O"], np.array([[1.9, 0, 0]]))         # N···O 1.9 Å, H···O 0.89 Å: impossible
    assert len(ML.overlaps(don, don.xyz, close, close.xyz)) == 2


def test_small_overlap_is_nudged_and_mode_kept():
    prot = shell(r=(8.0, 12.0))
    A = ring("A")
    B = ring("B", (4.4, 0.0, 0.0))                          # nearest C···C 1.62 Å: overlapping, not threaded
    r = ML.resolve([A, B], prot)
    assert r["status"] == "AUTO_FIXED" and r["adjusted"], r["why"]
    moved = next(iter(r["adjusted"].values()))
    assert moved["rmsd"] <= ML.MAX_NUDGE_RMSD
    assert all(v["ok"] for v in r["per_ligand"].values())
    assert "same binding mode" in r["why"][1]


def test_threaded_ligand_is_named_for_exclusion():
    prot = shell()
    A = ring("A")
    B = ML.Mol("B", ["C"] * 4, np.array([[0.1, 0, -2.3], [0.1, 0, -0.77], [0.1, 0, 0.77], [0.1, 0, 2.3]]))
    r = ML.resolve([A, B], prot)
    assert r["status"] == "NEEDS_HUMAN" and r["culprit"] in ("A", "B")
    assert any("multi_ligand.exclude" in o for o in r["options"]) and "ring piercing" in r["why"][1]
    # the human decisions
    assert ML.resolve([A, B], prot, exclude=[r["culprit"]])["status"] == "PASS"
    assert ML.resolve([A, B], prot, accept=True)["status"] == "ACCEPTED"


def test_floating_ligand_is_auto_excluded():
    prot = shell()
    A = ring("A")
    far = ring("F", (30.0, 0, 0))
    r = ML.resolve([A, far], prot)
    assert r["status"] == "AUTO_FIXED" and r["auto_excluded"] == ["F"] and r["ligands"] == ["A"]
    assert "floating" in r["why"][1]


def test_protein_ring_piercing_ligand_bond():
    phe = ML.Mol("protein", ["C"] * 6, BENZ + (0, 0, 0), is_protein=True)
    lig = rod("L", [0.1, 0.1, -0.77], [0.1, 0.1, 0.77])
    per = ML.check([lig], phe)
    assert per["L"]["piercings"] and not per["L"]["ok"]


def test_sdf_roundtrip_and_pdb_scan(tmp_path):
    p = tmp_path / "a.sdf"
    lines = ["A", "", "", "  6  6  0  0  0  0  0  0  0  0999 V2000"]
    lines += [f"{x:10.4f}{y:10.4f}{z:10.4f} C   0  0  0  0  0  0  0  0  0  0  0  0" for x, y, z in BENZ]
    lines += [f"{i + 1:3d}{(i + 1) % 6 + 1:3d}  1  0" for i in range(6)]
    p.write_text("\n".join(lines + ["M  END", "$$$$"]) + "\n")
    m = ML.mol_from_sdf(p, "A")
    assert len(m.bonds) == 6 and len(m.rings) == 1
    ML.write_sdf_coords(p, tmp_path / "b.sdf", m.xyz + 1.0, note="nudged")
    assert np.allclose(ML.mol_from_sdf(tmp_path / "b.sdf", "A").xyz, m.xyz + 1.0)
    rows = []
    for k, (x, y, z) in enumerate(BENZ):
        rows.append(f"HETATM{k + 1:5d}  C{k + 1:<2} L01 A   1    {x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00           C")
    for k, (x, y, z) in enumerate([(0.1, 0.1, -0.77), (0.1, 0.1, 0.77)]):
        rows.append(f"HETATM{k + 7:5d}  C{k + 1:<2} L02 A   2    {x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00           C")
    (tmp_path / "m.pdb").write_text("\n".join(rows) + "\nEND\n")
    assert ML.piercings_in_pdb(tmp_path / "m.pdb")


def _sdf_file(path, xyz, el="C"):
    lines = ["X", "", "", f"{len(xyz):3d}  0  0  0  0  0  0  0  0  0999 V2000"]
    lines += [f"{x:10.4f}{y:10.4f}{z:10.4f} {el:<3} 0  0  0  0  0  0  0  0  0  0  0  0" for x, y, z in xyz]
    path.write_text("\n".join(lines + ["M  END", "$$$$"]) + "\n")
    return str(path)


def _wf(tmp_path, a_xyz, b_xyz):
    import copy
    from md20.project.store import Project
    from md20.workflow import Workflow, example_config
    cfg = copy.deepcopy(example_config())
    wf = Workflow(Project.create(tmp_path, "p"), cfg)
    rec = tmp_path / "rec.pdb"
    P = shell(r=(8.0, 12.0)).xyz
    rec.write_text("\n".join(f"ATOM  {i + 1:5d}  CA  ALA A{i + 1:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00           C"
                             for i, (x, y, z) in enumerate(P)) + "\nEND\n")
    wf._mark("receptor_docking", path=str(rec))
    sel = {"mode": "simultaneous", "ligands": {"A": {"sdf": _sdf_file(tmp_path / "a.sdf", a_xyz)},
                                               "B": {"sdf": _sdf_file(tmp_path / "b.sdf", b_xyz)}}}
    return wf, sel


def test_workflow_blocks_names_culprit_then_honours_exclusion(tmp_path, monkeypatch):
    import pytest
    import md20.workflow as W
    from md20.workflow import WorkflowBlocked
    monkeypatch.setattr(W, "_openmm_available", lambda: False)     # no soft-core layer → a human decides now
    threaded = np.array([[0.1, 0, -2.3], [0.1, 0, -0.77], [0.1, 0, 0.77], [0.1, 0, 2.3]])
    wf, sel = _wf(tmp_path, BENZ, threaded)
    with pytest.raises(WorkflowBlocked):
        wf._multi_geometry(sel, ["A", "B"])
    st = wf.state()
    gate = st["steps"]["md_cases"]["gates"][0]
    assert gate["name"] == "multi-ligand geometry" and any(o.startswith("multi_ligand.exclude") for o in gate["options"])
    from md20.gui.actions import gate_actions
    acts, _ = gate_actions(gate, step="md_cases")
    excl = next(a for a in acts if a["label"].startswith("multi_ligand.exclude"))
    culprit = st["multi_ligand"]["culprit"]
    assert excl["patch"][0]["value"] == [culprit]
    wf.cfg["multi_ligand"] = {"exclude": [culprit]}
    out = wf._multi_geometry(sel, ["A", "B"])
    assert out["ligands"] == [n for n in ("A", "B") if n != culprit]


def test_workflow_nudges_and_writes_new_pose(tmp_path):
    wf, sel = _wf(tmp_path, BENZ, BENZ + (4.4, 0, 0))
    out = wf._multi_geometry(sel, ["A", "B"])
    assert out["record"]["status"] == "AUTO_FIXED" and out["picks"]
    n, pk = next(iter(out["picks"].items()))
    assert pk["sdf"].endswith("_nudged.sdf") and ML.mol_from_sdf(pk["sdf"], n).xyz.shape == (6, 3)


def test_workflow_defers_to_softcore_when_openmm_exists(tmp_path, monkeypatch):
    import md20.workflow as W
    monkeypatch.setattr(W, "_openmm_available", lambda: True)
    threaded = np.array([[0.1, 0, -2.3], [0.1, 0, -0.77], [0.1, 0, 0.77], [0.1, 0, 2.3]])
    wf, sel = _wf(tmp_path, BENZ, threaded)
    out = wf._multi_geometry(sel, ["A", "B"])
    assert out["record"]["status"] == "DEFERRED" and out["ligands"] == ["A", "B"] and "soft-core" in out["record"]["why"][1]
    wf.cfg["multi_ligand"] = {"softcore": False}                          # user opts out of the soft-core layer → ask now
    import pytest
    with pytest.raises(W.WorkflowBlocked):
        wf._multi_geometry(sel, ["A", "B"])


def test_workflow_switches_to_a_clean_joint_pose_before_asking(tmp_path):
    from md20.util.jsonio import atomic_write_json
    threaded = np.array([[0.1, 0, -2.3], [0.1, 0, -0.77], [0.1, 0, 0.77], [0.1, 0, 2.3]])
    wf, sel = _wf(tmp_path, BENZ, threaded)
    ok_b = _sdf_file(tmp_path / "b2.sdf", threaded + (5.0, 0, 0))
    a2 = _sdf_file(tmp_path / "a2.sdf", BENZ)
    poses = [{"rank": 1, "score": -9.0, "cluster_size": 3, "rejected": []}, {"rank": 2, "score": -8.6, "cluster_size": 2, "rejected": []},
             {"rank": 3, "score": -8.5, "cluster_size": 4, "rejected": ["配體間 2.0 Å < 3.3（碰撞）"]}]
    res = {"entries": [{"name": "joint", "ligands": ["A", "B"], "poses": poses,
                        "pose_sdfs": {"A": [sel["ligands"]["A"]["sdf"], a2, a2], "B": [sel["ligands"]["B"]["sdf"], ok_b, ok_b]}}]}
    atomic_write_json(res, tmp_path / "dock.json")
    wf._mark("docking", result=str(tmp_path / "dock.json"))
    for n in sel["ligands"]:
        sel["ligands"][n]["rank"] = 1
    out = wf._multi_geometry(sel, ["A", "B"])
    assert out["record"]["status"] in ("PASS", "AUTO_FIXED") and sel["ligands"]["A"]["rank"] == 2   # rank 3 was rejected by docking


def test_backbone_bond_through_ligand_ring_after_minimisation(tmp_path):
    rows = []
    for k, (x, y, z) in enumerate(BENZ):
        rows.append(f"HETATM{k + 1:5d}  C{k + 1:<2} L01 B   1    {x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00           C")
    bb = [("N", "GLY", 1, (0.1, 2.2, -2.2), "N"), ("CA", "GLY", 1, (0.1, 1.2, -1.4), "C"), ("C", "GLY", 1, (0.1, 0.1, -0.66), "C"),
          ("N", "GLY", 2, (0.1, 0.1, 0.67), "N"), ("CA", "GLY", 2, (0.1, -0.9, 1.5), "C"), ("C", "GLY", 2, (0.1, -2.0, 2.3), "C")]
    for k, (an, rn, ri, (x, y, z), el) in enumerate(bb):
        rows.append(f"ATOM  {k + 10:5d}  {an:<3} {rn} A{ri:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00           {el}")
    (tmp_path / "bb.pdb").write_text("\n".join(rows) + "\nEND\n")
    hits = ML.piercings_in_pdb(tmp_path / "bb.pdb")
    assert hits and hits[0]["bond_of"] == "protein"        # the C(1)–N(2) peptide bond threads the ring


def test_lone_ligand_away_from_protein_is_not_a_geometry_problem():
    far = ring("P01", (30.0, 0, 0))                    # e.g. a peptide built on its own chain, not docked
    r = ML.resolve([far], shell())
    assert r["status"] == "PASS"
