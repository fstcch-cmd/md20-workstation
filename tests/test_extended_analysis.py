"""D-58: extended trajectory analyses — pure numpy parts here, the mdtraj layer on a small synthetic trajectory (CI)."""
import numpy as np
import pytest

from md20.analysis.extended import (pca, free_energy_landscape, cluster_from_rmsd, cross_correlation, occupancy, block_average,
                                    histogram_overlap_matrix, frame_indices)
from md20.report.chem import lipinski_violations, chem_space_xy, pose_contacts


def test_pca_and_landscape_find_two_states():
    rng = np.random.default_rng(0)
    xyz = rng.normal(0, 0.2, (200, 20, 3))
    xyz[100:, :, 0] += 2.0                                     # two conformational states
    p = pca(xyz)
    assert p["explained"][0] > 0.5
    pr = np.asarray(p["projection"])
    land = free_energy_landscape(pr[:, 0], pr[:, 1], bins=20)
    assert len(land["basins"]) >= 2 and np.nanmin(np.array(land["G"], dtype=float)) == 0


def test_clustering_and_correlation():
    D = np.zeros((10, 10)); D[:6, 6:] = D[6:, :6] = 5.0         # two groups of 6 and 4 frames
    c = cluster_from_rmsd(D, 2.0)
    assert c["n_clusters"] == 2 and c["populations"] == [0.6, 0.4] and c["labels"][:6] == [0] * 6
    rng = np.random.default_rng(1)
    base = rng.normal(0, 1, (300, 1, 3))
    xyz = np.concatenate([base, base, -base, rng.normal(0, 1, (300, 1, 3))], axis=1)
    C = cross_correlation(xyz)
    assert C[0, 1] > 0.99 and C[0, 2] < -0.99 and abs(C[0, 3]) < 0.2


def test_occupancy_blocks_overlap():
    assert occupancy([["a", "b"], ["a"], [], ["a", "a"]], 4) == [["a", 0.75], ["b", 0.25]]
    b = block_average(np.arange(100.0))
    assert b["mean"] == 49.5 and b["sem"] > 0
    rng = np.random.default_rng(2)
    o = histogram_overlap_matrix({0.5: rng.normal(0.5, 0.05, 500), 0.6: rng.normal(0.6, 0.05, 500), 1.5: rng.normal(1.5, 0.05, 500)})
    assert o["neighbour"][0] > 0.2 and o["neighbour"][1] < 0.01 and o["min_neighbour"] < 0.01
    assert list(frame_indices(1000, 250))[:2] == [0, 4] and len(frame_indices(1000, 250)) == 250


def test_chemistry_helpers():
    assert lipinski_violations({"mw": 600, "logp": 6, "hbd": 2, "hba": 4}) == 2
    xy = chem_space_xy(np.eye(5))
    assert xy.shape == (5, 2)
    prot = [{"xyz": [0, 0, 3.0], "element": "O", "res": "SER195", "name": "OG", "resname": "SER"},
            {"xyz": [5, 0, 0], "element": "C", "res": "LEU99", "name": "CD1", "resname": "LEU"},
            {"xyz": [0, 3.5, 0], "element": "O", "res": "ASP189", "name": "OD1", "resname": "ASP"}]
    c = pose_contacts([[0, 0, 0], [4, 0, 0], [0, 0.5, 0], [20, 20, 20]], ["N", "C", "N", "C"], prot)
    # D-97 (A5): distance alone is polar proximity, not a hydrogen bond; with the ligand charge unknown a N next to ASP
    # is "charged proximity", never ionic/salt bridge; every applicable label is kept
    assert [x.get("kind") for x in c] == ["charged_proximity_ligand_charge_unknown", "hydrophobic",
                                          "charged_proximity_ligand_charge_unknown", None]
    assert "polar_proximity" in c[0]["kinds"] and all("hbond" not in (x.get("kinds") or []) for x in c)
    cat = pose_contacts([[0, 0, 0]], ["N"], [{"xyz": [0, 3.0, 0], "element": "O", "res": "ASP189", "name": "OD1", "resname": "ASP"}],
                        lig_charges=[+1])
    assert cat[0]["kind"] == "salt_bridge"                    # cationic ligand N next to ASP: opposite charges
    an = pose_contacts([[0, 0, 0]], ["O"], [{"xyz": [0, 3.0, 0], "element": "O", "res": "ASP189", "name": "OD1", "resname": "ASP"}],
                       lig_charges=[-1])
    assert an[0]["kind"] == "like_charge_proximity"           # anionic ligand O next to ASP: never a salt bridge


def test_extended_metrics_on_synthetic_trajectory():
    md = pytest.importorskip("mdtraj")
    from md20.analysis.extended import extended_metrics
    top = md.Topology()
    ch = top.add_chain()
    rng = np.random.default_rng(3)
    coords = []
    for i in range(8):
        r = top.add_residue("ALA" if i % 2 else "SER", ch, resSeq=i + 1)
        for name, el, off in (("N", "N", (0, 0, 0)), ("CA", "C", (1.45, 0, 0)), ("C", "C", (2.0, 1.4, 0)), ("O", "O", (1.4, 2.4, 0)),
                              ("CB", "C", (2.0, -1.0, 1.0))):
            top.add_atom(name, md.element.get_by_symbol(el), r)
            coords.append(np.array(off) + [3.8 * i, 0, 0])
        if i % 2 == 0:
            top.add_atom("OG", md.element.oxygen, r); coords.append(np.array([2.5, -1.5, 2.0]) + [3.8 * i, 0, 0])
    lig = top.add_residue("L01", top.add_chain(), resSeq=1)
    lstart = top.n_atoms
    for name, el, off in (("C1", "C", (14, 3, 3)), ("N1", "N", (15, 3, 3)), ("O1", "O", (14, 4, 3))):
        top.add_atom(name, md.element.get_by_symbol(el), lig); coords.append(np.array(off, float))
    w = top.add_residue("HOH", top.add_chain(), resSeq=1)
    top.add_atom("O", md.element.oxygen, w); coords.append(np.array([14.5, 5.0, 3.0]))
    for a, b in ((0, 1), (1, 2), (2, 3), (1, 4)):
        pass
    X = np.array(coords) / 10.0
    traj = md.Trajectory(np.stack([X + rng.normal(0, 0.01, X.shape) for _ in range(40)]), top, time=np.arange(40) * 10.0)
    out = extended_metrics(traj, {"L01": list(range(lstart, lstart + 3))})
    for k in ("pca", "clusters", "dccm"):
        assert k in out, (k, out["errors"])
    L = out["ligands"]["L01"]
    assert "water_bridges" in L and len(L["water_bridges"]["count"]) == 40
    assert "fingerprint" in L or "fingerprint" in L["errors"]
    # D-105: the toolbox blocks run on a real mdtraj trajectory without raising; 40 frames are too few for tICA, and
    # the result says so instead of producing a model; one water in the trajectory → hydration is attempted
    assert out["tica"]["status"] == "insufficient", out.get("tica")
    assert "network" in out["hbonds_protein"], out["errors"]
    assert out["hbonds_protein"]["network"]["status"] in ("ok", "insufficient")
    assert L["hydration"]["status"] in ("ok", "insufficient"), L.get("errors")
