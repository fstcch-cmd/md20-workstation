"""D-97 wiring of `extended_metrics` → interactions/persistence without mdtraj: a minimal stand-in topology and
trajectory provide only what the fingerprint and water blocks touch; every other block fails inside its guard and is
recorded in `errors` (as it would on a real failure).  The real mdtraj path runs in CI openmm-stack."""
import sys
import types

import numpy as np
import pytest


class _El:
    def __init__(self, s):
        self.symbol = s


class _Chain:
    def __init__(self, i, cid):
        self.index, self.chain_id = i, cid


class _Res:
    def __init__(self, name, seq, chain, idx):
        self.name, self.resSeq, self.chain, self.index = name, seq, chain, idx
        self.is_protein = name not in ("LIG", "HOH")
        self.is_water = name == "HOH"


class _Atom:
    def __init__(self, i, name, el, res, side=True):
        self.index, self.name, self.element, self.residue, self.is_sidechain = i, name, _El(el), res, side


class _Top:
    def __init__(self, atoms):
        self.atoms_ = atoms

    def atom(self, i):
        return self.atoms_[int(i)]

    def select(self, q):
        A = self.atoms_
        if q == "protein":
            return np.array([a.index for a in A if a.residue.is_protein], int)
        if q == "protein and name CA":
            return np.array([a.index for a in A if a.residue.is_protein and a.name == "CA"], int)
        if q == "protein and (element N or element O)":
            return np.array([a.index for a in A if a.residue.is_protein and a.element.symbol in ("N", "O")], int)
        if q == "water and element O":
            return np.array([a.index for a in A if a.residue.is_water and a.element.symbol == "O"], int)
        raise ValueError(q)


class _Traj:
    def __init__(self, xyz, time, top):
        self.xyz, self.time, self.topology = xyz, time, top
        self.n_frames = xyz.shape[0]

    def __getitem__(self, sel):
        return _Traj(self.xyz[sel], self.time[sel], self.topology)


def _system(with_water=False):
    ca, cb = _Chain(0, "A"), _Chain(1, "B")
    lig = _Res("LIG", 1, _Chain(2, "L"), 0)
    asp_a, asp_b, leu = _Res("ASP", 189, ca, 1), _Res("ASP", 189, cb, 2), _Res("LEU", 99, ca, 3)
    atoms = [_Atom(0, "O1", "O", lig), _Atom(1, "C1", "C", lig),
             _Atom(2, "OD1", "O", asp_a), _Atom(3, "CA", "C", asp_a, side=False),
             _Atom(4, "OD1", "O", asp_b), _Atom(5, "CA", "C", asp_b, side=False),
             _Atom(6, "CD1", "C", leu), _Atom(7, "CA", "C", leu, side=False)]
    if with_water:
        atoms.append(_Atom(8, "O", "O", _Res("HOH", 1, _Chain(3, "W"), 4)))
    F = 20
    X = np.zeros((F, len(atoms), 3))
    X[:, 0] = [0, 0, 0]; X[:, 1] = [0.15, 0, 0]
    X[:, 2] = [0.3, 0, 0]; X[:, 3] = [0.6, 0, 0]          # A:ASP189 next to the ligand O all the time
    X[:, 4] = [-0.3, 0, 0]; X[:, 5] = [-0.6, 0, 0]        # B:ASP189 too: same residue number, other chain
    X[:10, 6] = [3.0, 0, 0]; X[10:, 6] = [0.5, 0, 0]       # LEU99 forms its contact only in the second half
    X[:, 7] = [3.5, 0, 0]
    if with_water:
        X[:, 8] = [5, 5, 5]
    return _Traj(X, np.arange(F, dtype=float) * 10.0, _Top(atoms))


@pytest.fixture
def fake_mdtraj(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("not available in the stand-in")
    m = types.ModuleType("mdtraj")
    for n in ("compute_dssp", "wernet_nilsson", "rmsd", "shrake_rupley"):
        setattr(m, n, boom)
    monkeypatch.setitem(sys.modules, "mdtraj", m)


def test_fingerprint_is_chain_aware_dynamic_and_charge_honest(fake_mdtraj):
    from md20.analysis.extended import extended_metrics
    out = extended_metrics(_system(), {"L01": [0, 1]})
    L = out["ligands"]["L01"]
    fp = L["fingerprint"]
    assert fp["schema"] == "md20.fingerprint/2" and "fingerprint" not in L["errors"]
    assert {"A:ASP189", "B:ASP189", "A:LEU99"} <= set(fp["residues"])                   # chains distinct
    assert fp["occupancy"]["hydrophobic"]["A:LEU99"] == 0.5                             # late contact found (A6)
    assert fp["occupancy"]["salt_bridge"] == {}                                        # ligand charge unknown (A5)
    assert "A:ASP189" in fp["occupancy"]["charged_proximity_ligand_charge_unknown"]
    assert fp["display_labels"]["A:LEU99"] == "LEU99" and fp["display_labels"]["A:ASP189"] == "A:ASP189"
    assert len(fp["time_ps"]) == 20                                                     # stored frames, not a display subset
    assert fp["initial_vs_new"]["new"] == ["A:LEU99"]
    per = {(i["residue"], i["label"]): i for i in fp["persistence"]["items"]}
    leu = per[("A:LEU99", "hydrophobic")]
    assert leu["n_events"] == 1 and leu["events"][0]["right_censored"] and not leu["events"][0]["left_censored"]
    assert leu["lifetime_ps"] is None                                                   # one censored event: no lifetime
    # no water in this system → unavailable, not zero
    assert L["water_bridges"]["status"] == "unavailable" and L["water_bridges"]["count"] is None


def test_known_ligand_charge_gives_like_charge_proximity_not_salt_bridge(fake_mdtraj):
    from md20.analysis.extended import extended_metrics
    out = extended_metrics(_system(with_water=True), {"L01": [0, 1]}, ligand_charges={"L01": {0: -1}})
    fp = out["ligands"]["L01"]["fingerprint"]
    assert fp["occupancy"]["salt_bridge"] == {} and set(fp["occupancy"]["like_charge_proximity"]) == {"A:ASP189", "B:ASP189"}
    assert out["ligands"]["L01"]["water_bridges"]["status"] == "computed"
