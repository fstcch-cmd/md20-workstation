"""PBC re-centering (立體歸零): the exact failure modes seen in practice, on synthetic coordinates (no mdtraj)."""
import numpy as np
import pytest

from md20.analysis.pbc import recenter_frame, split_molecules, anchor_and_others, make_whole, apparent_vs_true_distance
from md20.workflow import metal_indices_from_manifest

BOX = np.array([5.0, 5.0, 5.0])


def _chain(n, start, step=0.15):
    """A linear 'chain' of n atoms along x starting at `start` (nm); bonds between neighbours."""
    xyz = np.array([start + np.array([i * step, 0, 0]) for i in range(n)])
    return xyz


def _bonds_of(bonds):
    d = {}
    for a, b in bonds:
        d.setdefault(a, []).append((a, b)); d.setdefault(b, []).append((a, b))
    return d


def test_protein_wrapped_across_edge_is_made_whole_and_centred():
    # 6-atom chain straddling the x boundary: atoms 0-2 at x≈4.85…5.0 (wrapped to 0.0…), atoms 3-5 at 0.0…0.3
    prot = _chain(6, np.array([4.7, 2.5, 2.5]))
    wrapped = prot.copy(); wrapped[:, 0] %= BOX[0]                          # what DCDReporter(enforcePeriodicBox) writes
    bonds = [(i, i + 1) for i in range(5)]
    mols = split_molecules(6, bonds)
    anchors, others = anchor_and_others(mols, set(range(6)))
    out = recenter_frame(wrapped, BOX, anchors, others, _bonds_of(bonds))
    d = np.diff(out[:, 0])
    assert np.allclose(d, 0.15)                                             # no bond crosses the boundary any more
    assert np.allclose(out.mean(0), BOX / 2)                                # protein centroid at the box centre


def test_second_chain_and_peptide_on_the_far_side_come_back():
    """Protein sits at the +x face; chain B and a peptide bound just beyond the face get wrapped to x≈0 and look
    4–5 nm away (the classic 'ligand dissociated' picture)."""
    chainA = _chain(5, np.array([4.4, 2.5, 2.5]))                            # x 4.4…5.0, centroid 4.7
    chainB = _chain(5, np.array([4.4, 2.9, 2.5]))                            # next to A (0.4 nm in y)
    pep = _chain(4, np.array([5.1, 2.5, 2.5]))                               # bound beyond the face: x 5.1…5.55
    raw = np.vstack([chainA, chainB, pep]) % BOX                             # per-atom wrap, as the DCD is written
    assert raw[10:, 0].max() < 1.0                                           # peptide now appears at x≈0.1…0.55
    bonds = [(i, i + 1) for i in range(4)] + [(5 + i, 6 + i) for i in range(4)] + [(10 + i, 11 + i) for i in range(3)]
    mols = split_molecules(14, bonds)
    assert len(mols) == 3
    anchors, others = anchor_and_others(mols, set(range(10)))                # both protein chains anchor; peptide is not
    assert len(anchors) == 2 and len(others) == 1
    out = recenter_frame(raw, BOX, anchors, others, _bonds_of(bonds))
    dAB = np.linalg.norm(out[0:5].mean(0) - out[5:10].mean(0))
    dAP = out[10:14, 0].min() - out[0:5, 0].max()                            # peptide starts 0.1 nm past the last A atom
    assert dAB == pytest.approx(0.4, abs=1e-6) and dAP == pytest.approx(0.1, abs=1e-6)
    assert np.allclose(out[0:10].mean(0), BOX / 2)
    chk = apparent_vs_true_distance(raw, out, np.arange(10, 14), np.arange(0, 5))
    assert chk["pbc_artifact"] and chk["apparent_nm"] > 2.0 and chk["true_nm"] < 1.0


def test_true_dissociation_is_not_hidden():
    prot = _chain(5, np.array([2.0, 2.5, 2.5]))
    lig = _chain(3, np.array([2.0, 2.5, 4.3]))                               # really 1.8 nm away (left the pocket)
    raw = np.vstack([prot, lig]) % BOX
    bonds = [(i, i + 1) for i in range(4)] + [(5, 6), (6, 7)]
    mols = split_molecules(8, bonds)
    anchors, others = anchor_and_others(mols, set(range(5)))
    out = recenter_frame(raw, BOX, anchors, others, _bonds_of(bonds))
    chk = apparent_vs_true_distance(raw, out, np.arange(5, 8), np.arange(0, 5))
    assert not chk["pbc_artifact"] and chk["true_nm"] == pytest.approx(1.8, abs=0.01)


def test_bonded_metal_is_part_of_the_anchor():
    prot = _chain(4, np.array([2.0, 2.5, 2.5]))
    zn = np.array([[2.2, 2.7, 2.5]])                                         # 0.2 nm from the chain, no bond in the topology
    raw = np.vstack([prot, zn + np.array([0, BOX[1], 0])]) % BOX             # written in the next image
    bonds = [(i, i + 1) for i in range(3)]
    mols = split_molecules(5, bonds)
    anchors, others = anchor_and_others(mols, set(range(4)) | {4})
    assert len(anchors) == 2 and not others
    out = recenter_frame(raw, BOX, anchors, others, _bonds_of(bonds))
    assert np.linalg.norm(out[4] - out[0:4].mean(0)) < 0.5
    bm = {"restraints": {"metals": {"plans": [{"metal_index": 4, "action": "bonded"}, {"metal_index": 9, "action": "keep_nonbonded"}]}}}
    assert metal_indices_from_manifest(bm) == [4]
    assert metal_indices_from_manifest({}) == []


def test_make_whole_handles_branched_molecule():
    # star: centre 0 bonded to 1,2,3; atom 2 wrapped to the other side
    xyz = np.array([[4.95, 2, 2], [4.8, 2, 2], [0.1, 2, 2], [4.95, 2.15, 2]])
    bonds = [(0, 1), (0, 2), (0, 3)]
    out = make_whole(xyz, [np.arange(4)], _bonds_of(bonds), BOX)
    assert out[2, 0] == pytest.approx(5.1)


def test_no_anchor_returns_whole_but_uncentred():
    xyz = np.array([[0.1, 0, 0], [4.95, 0, 0]])
    out = recenter_frame(xyz, BOX, [], [np.array([0, 1])], _bonds_of([(0, 1)]))
    assert out[1, 0] == pytest.approx(-0.05)
