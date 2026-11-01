"""Fitted metal parameters (pure python): Seminario fit from a Hessian, MCPB.py translation, JSON import, gates."""
import json
import math

import numpy as np
import pytest

from md20.build.gates import AUTO_FIXED, NEEDS_HUMAN
from md20.build.metal import find_sites, plan_site, K_BOND
from md20.build.metal_params import (BOHR_TO_A, KCAL_A2_TO_KJ_NM2, cluster_neighbours, load_hessian,
                                     match_cluster_to_site, mcpb_residue_map, parse_frcmod, parse_mol2,
                                     parse_orca_hess, resolve_site_params, seminario_bond, site_force_constants)

# ------------------------------------------------------------------------- a Zn(His)3 site, crystal-like
R0 = 2.05
DIRS = np.array([[1, 1, 1], [1, -1, -1], [-1, 1, -1]], float) / math.sqrt(3)        # three tetrahedral arms
ZN = np.array([10.0, 10.0, 10.0])


def _site_atoms():
    atoms = [{"index": 0, "name": "ZN", "resname": "ZN", "chain": "A", "resseq": "301", "xyz": ZN.tolist(), "element": "Zn",
              "is_protein": False}]
    for i, d in enumerate(DIRS):
        n = ZN + R0 * d
        c = n + 1.35 * d                                             # a carbon behind each nitrogen (CE1-like)
        atoms.append({"index": 1 + 2 * i, "name": "NE2", "resname": "HIS", "chain": "A", "resseq": str(94 + i), "xyz": n.tolist(),
                      "element": "N", "is_protein": True})
        atoms.append({"index": 2 + 2 * i, "name": "CE1", "resname": "HIS", "chain": "A", "resseq": str(94 + i), "xyz": c.tolist(),
                      "element": "C", "is_protein": True})
    return atoms


def _xyz_of(atoms):
    return {a["index"]: np.asarray(a["xyz"]) for a in atoms}


# ------------------------------------------------------------------------- synthetic QM cluster + Hessian
K_B_KCAL, K_A_KCAL = 60.0, 30.0            # ½k convention, kcal/mol/Å² and kcal/mol/rad²


def _cluster(single_angle=False):
    """Same site, reordered and rotated, plus a stray water O: z, xyz (Å), analytic harmonic Hessian (Hartree/Bohr²)."""
    rot = np.array([[0, 1, 0], [0, 0, 1], [1, 0, 0]], float)
    pts = [("N", ZN + R0 * DIRS[2]), ("C", ZN + (R0 + 1.35) * DIRS[2]), ("Zn", ZN), ("N", ZN + R0 * DIRS[0]),
           ("C", ZN + (R0 + 1.35) * DIRS[0]), ("O", ZN + np.array([0, 0, 4.0])), ("N", ZN + R0 * DIRS[1]),
           ("C", ZN + (R0 + 1.35) * DIRS[1])]
    z = [{"N": 7, "C": 6, "Zn": 30, "O": 8}[e] for e, _ in pts]
    xyz = np.array([rot @ (p - ZN) for _, p in pts])              # Å, metal at origin
    bonds = [(2, 0), (2, 3), (2, 6), (0, 1), (3, 4), (6, 7)]
    angles = [(0, 2, 3)] if single_angle else [(0, 2, 3), (0, 2, 6), (3, 2, 6)]
    kb = K_B_KCAL / 627.509474 * BOHR_TO_A ** 2                      # Hartree/Bohr²
    ka = K_A_KCAL / 627.509474                                       # Hartree/rad²
    xb = xyz / BOHR_TO_A

    def energy(x):
        x = x.reshape(-1, 3); e = 0.0
        for i, j in bonds:
            r = np.linalg.norm(x[i] - x[j]); e += 0.5 * kb * (r - np.linalg.norm(xb[i] - xb[j])) ** 2
        for a, b, c in angles:
            u, v = x[a] - x[b], x[c] - x[b]
            th = math.acos(np.dot(u, v) / np.linalg.norm(u) / np.linalg.norm(v))
            u0, v0 = xb[a] - xb[b], xb[c] - xb[b]
            th0 = math.acos(np.dot(u0, v0) / np.linalg.norm(u0) / np.linalg.norm(v0))
            e += 0.5 * ka * (th - th0) ** 2
        return e
    n3 = 3 * len(z); h = np.zeros((n3, n3)); x0 = xb.reshape(-1); d = 1e-3
    for i in range(n3):
        for j in range(i, n3):
            ei, ej = np.zeros(n3), np.zeros(n3); ei[i] = d; ej[j] = d
            h[i, j] = h[j, i] = (energy(x0 + ei + ej) - energy(x0 + ei - ej) - energy(x0 - ei + ej) + energy(x0 - ei - ej)) / (4 * d * d)
    return z, xyz, h


def _fchk_text(z, xyz, h):
    def fmt(vals, per, f):
        lines = []
        for k in range(0, len(vals), per):
            lines.append("".join(f % v for v in vals[k:k + per]))
        return "\n".join(lines)
    n3 = 3 * len(z)
    tri = [h[i, j] for i in range(n3) for j in range(i + 1)]
    return ("Title\nFREQ RB3LYP\n" + f"Atomic numbers                             I   N=        {len(z)}\n" + fmt(z, 6, "%12d") + "\n"
            + f"Current cartesian coordinates              R   N=        {n3}\n" + fmt((xyz / BOHR_TO_A).reshape(-1), 5, "%16.8E") + "\n"
            + f"Cartesian Force Constants                  R   N=        {len(tri)}\n" + fmt(tri, 5, "%16.8E") + "\n")


def _orca_text(z, xyz, h):
    n3 = 3 * len(z); out = ["$orca_hessian_file", "", "$hessian", str(n3)]
    for c0 in range(0, n3, 5):
        cols = list(range(c0, min(n3, c0 + 5)))
        out.append("".join(f"{c:>12d}" for c in cols))
        for r in range(n3):
            out.append(f"{r:>5d}" + "".join(f"{h[r, c]:>14.6E}" for c in cols))
    out += ["", "$atoms", str(len(z))]
    sym = {7: "N", 6: "C", 30: "Zn", 8: "O"}
    for zz, p in zip(z, xyz / BOHR_TO_A):
        out.append(f" {sym[zz]:<3s} 1.0 {p[0]:14.8f} {p[1]:14.8f} {p[2]:14.8f}")
    out += ["", "$end"]
    return "\n".join(out)


@pytest.fixture(scope="module")
def cluster():
    return _cluster()


def test_internal_coordinate_fit_recovers_known_constants(cluster):
    z, xyz, h = cluster
    k, r0 = seminario_bond(h, xyz, 2, 0)
    assert abs(k - K_B_KCAL) / K_B_KCAL < 0.02 and abs(r0 - R0) < 1e-3       # Seminario bond (cross-check value)
    nbs = {c: cluster_neighbours(z, xyz, c, {2}) for c in (0, 3, 6)}
    assert nbs == {0: [1], 3: [4], 6: [7]}
    fc = site_force_constants(h, xyz, 2, [0, 3, 6], nbs)
    for d in (0, 3, 6):
        assert abs(fc["bonds"][d][0] - K_B_KCAL) / K_B_KCAL < 0.01 and abs(fc["bonds"][d][1] - R0) < 1e-3
    for (a, b), (k_a, th) in fc["angles"].items():
        assert abs(th - 109.47) < 0.1 and abs(k_a - K_A_KCAL) / K_A_KCAL < 0.01   # shared angles: still exact
    _, xyz1, h1 = _cluster(single_angle=True)
    fc1 = site_force_constants(h1, xyz1, 2, [0, 3, 6], nbs)
    assert abs(fc1["angles"][(0, 3)][0] - K_A_KCAL) / K_A_KCAL < 0.01 and abs(fc1["angles"][(0, 6)][0]) < 0.5
    # without the neighbour terms the donors' own bonds leak into the angles — the reason they are included
    leaky = site_force_constants(h, xyz, 2, [0, 3, 6], None)
    assert leaky["angles"][(0, 3)][0] > 1.2 * K_A_KCAL


def test_parsers_roundtrip(cluster, tmp_path):
    z, xyz, h = cluster
    f = tmp_path / "zn.fchk"; f.write_text(_fchk_text(z, xyz, h))
    d = load_hessian(f)
    assert d["z"] == z and np.allclose(d["xyz_A"], xyz, atol=1e-6) and np.allclose(d["hessian"], h, rtol=1e-6)
    o = tmp_path / "zn.hess"; o.write_text(_orca_text(z, xyz, h))
    d2 = parse_orca_hess(o.read_text(encoding="utf-8"))
    assert d2["z"] == z and np.allclose(d2["xyz_A"], xyz, atol=1e-6) and np.allclose(d2["hessian"], h, rtol=1e-4)


def test_cluster_matching_is_permutation_and_rotation_invariant(cluster):
    z, xyz, _ = cluster
    atoms = _site_atoms(); site = find_sites(atoms)[0]
    xo = _xyz_of(atoms)
    mapping, rmsd, why = match_cluster_to_site(z, xyz, "ZN", {0: xo[0], 1: xo[1], 3: xo[3], 5: xo[5]}, {1: "N", 3: "N", 5: "N"})
    assert mapping[0] == 2 and rmsd < 1e-6
    assert {mapping[1], mapping[3], mapping[5]} == {0, 3, 6}                 # the water O (index 5) is never a donor
    # three equivalent arms: any proper rotation of the assignment is equally valid, geometry decides, not order
    assert mapping[1] in (0, 3, 6)


def test_hessian_source_end_to_end(cluster, tmp_path):
    z, xyz, h = cluster
    f = tmp_path / "zn.fchk"; f.write_text(_fchk_text(z, xyz, h))
    atoms = _site_atoms(); site = find_sites(atoms)[0]; xo = _xyz_of(atoms)
    out = resolve_site_params(site, {"source": "hessian", "file": str(f)}, xo)
    assert out["status"] == AUTO_FIXED and out["source"] == "hessian", out
    assert set(out["bonds"]) == {1, 3, 5} and all(abs(b["k_kcal_A2"] - K_B_KCAL) < 2 for b in out["bonds"].values())
    assert len(out["angles"]) == 3 and out["charges"] == {}
    plan = plan_site(site, "bonded", xo, params={"source": "hessian", "file": str(f)})
    assert plan["status"] == AUTO_FIXED and plan["source"] == "hessian"
    assert all(abs(b["k"] - K_B_KCAL * KCAL_A2_TO_KJ_NM2) < 2 * KCAL_A2_TO_KJ_NM2 for b in plan["bonds"])
    assert "Wilson" in plan["why"] and "Seminario" in plan["caveats"][0]
    assert all(abs(v - K_B_KCAL) < 2 for v in plan["evidence"]["seminario_bond_k_kcal_A2"].values())
    geo = plan_site(site, "bonded", xo)
    assert geo["source"] == "geometric" and geo["bonds"][0]["k"] == K_BOND


def test_hessian_wrong_cluster_is_blocked(cluster, tmp_path):
    z, xyz, h = cluster
    atoms = _site_atoms(); site = find_sites(atoms)[0]; xo = _xyz_of(atoms)
    f = tmp_path / "bad.fchk"; f.write_text(_fchk_text([z[i] for i in (0, 1, 3, 4)], xyz[[0, 1, 3, 4]], h[:12, :12]))
    out = resolve_site_params(site, {"source": "hessian", "file": str(f)}, xo)       # no zinc in the file
    assert out["status"] == NEEDS_HUMAN and "0 個 ZN" in out["why"]
    # scaled Hessian → unphysical force constants → blocked, not silently used
    f2 = tmp_path / "weak.fchk"; f2.write_text(_fchk_text(z, xyz, h * 0.05))
    out = resolve_site_params(site, {"source": "hessian", "file": str(f2)}, xo)
    assert out["status"] == NEEDS_HUMAN and "超出合理範圍" in out["why"]
    plan = plan_site(site, "bonded", xo, params={"source": "hessian", "file": str(f2)})
    assert plan["status"] == NEEDS_HUMAN and "改用幾何鍵結模型" in " ".join(plan["options"])


# ------------------------------------------------------------------------------------------- MCPB.py
FRCMOD = """Remark line goes here
MASS
ZN  65.40   0.000
Y1  14.01   0.530
Y2  14.01   0.530

BOND
ZN-Y1   38.70   2.0600
ZN-Y2   41.20   2.0400
Y1-CV  410.0    1.394

ANGLE
Y1-ZN-Y1    22.10   109.60
Y1-ZN-Y2    20.80   108.20
ZN-Y1-CV    50.00   125.00

DIHE
X -ZN-Y1-X    4    0.000   180.000   2.000

NONBON
  ZN  1.3950  0.0150

"""


def _mol2(resname, atoms):
    lines = ["@<TRIPOS>MOLECULE", resname, f"{len(atoms)} 0 1 0 0", "SMALL", "USER_CHARGES", "", "@<TRIPOS>ATOM"]
    for i, (name, typ, q) in enumerate(atoms, 1):
        lines.append(f"{i:>7d} {name:<6s} 0.0 0.0 0.0 {typ:<6s} 1 {resname} {q:9.4f}")
    lines += ["@<TRIPOS>BOND"]
    return "\n".join(lines) + "\n"


def _mcpb_files(tmp_path, *, hid_charge_sum=0.0):
    (tmp_path / "zn.frcmod").write_text(FRCMOD)
    (tmp_path / "ZN1.mol2").write_text(_mol2("ZN1", [("ZN", "ZN", 0.70)]))
    # His residues are renamed HD1/HD2/HD3 by MCPB; atom names stay Amber's.  Each sums to hid_charge_sum.
    for k in (1, 2, 3):
        typ = "Y1" if k < 3 else "Y2"
        qs = [("N", "N", -0.4), ("H", "H", 0.3), ("CA", "CT", 0.0), ("HA", "H1", 0.1), ("C", "C", 0.6), ("O", "O", -0.6),
              ("CB", "CT", 0.0), ("HB2", "HC", 0.05), ("HB3", "HC", 0.05), ("CG", "CC", 0.1), ("ND1", "NA", -0.3), ("HD1", "H", 0.3),
              ("CE1", "CV", 0.1), ("HE1", "H5", 0.1), ("NE2", typ, -0.5), ("CD2", "CW", 0.1), ("HD2", "H4", 0.1)]
        tot = sum(q for _, _, q in qs); qs[-1] = ("HD2", "H4", round(0.1 + hid_charge_sum - tot, 4))
        (tmp_path / f"HD{k}.mol2").write_text(_mol2(f"HD{k}", qs))
    pdb = [f"HETATM{1:5d} {'ZN':^4s} {'ZN1':>3s} A{301:4d}    {10.0:8.3f}{10.0:8.3f}{10.0:8.3f}  1.00  0.00          ZN"]
    for k, rs in enumerate((94, 95, 96), 1):
        pdb.append(f"ATOM  {k + 1:5d} {'NE2':^4s} {'HD' + str(k):>3s} A{rs:4d}    {0.0:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00  0.00           N")
    (tmp_path / "zn_mcpbpy.pdb").write_text("\n".join(pdb) + "\nEND\n")
    return {"source": "mcpb", "frcmod": str(tmp_path / "zn.frcmod"), "pdb": str(tmp_path / "zn_mcpbpy.pdb"),
            "mol2": [str(tmp_path / f) for f in ("ZN1.mol2", "HD1.mol2", "HD2.mol2", "HD3.mol2")]}


HID_NAMES = ["N", "H", "CA", "HA", "C", "O", "CB", "HB2", "HB3", "CG", "ND1", "HD1", "CE1", "HE1", "NE2", "CD2", "HD2"]


def _residue_atoms():
    out = {}
    base = 100
    for k, rs in enumerate((94, 95, 96)):
        out[f"A:{rs}"] = {n: base + 20 * k + i for i, n in enumerate(HID_NAMES)}
        out[f"A:{rs}"]["NE2"] = 1 + 2 * k                        # donor indices used by the site
    return out


def test_frcmod_and_mol2_parsers():
    frc = parse_frcmod(FRCMOD)
    assert frc["bonds"][("ZN", "Y1")] == (38.70, 2.06) and frc["bonds"][("Y1", "ZN")] == (38.70, 2.06)
    assert frc["angles"][("Y2", "ZN", "Y1")] == (20.80, 108.20) and len(frc["ignored"]) == 2
    m = parse_mol2(_mol2("HD1", [("NE2", "Y1", -0.5), ("CE1", "CV", 0.1)]))
    assert m["resname"] == "HD" and m["atoms"]["NE2"] == {"type": "Y1", "charge": -0.5, "resname": "HD1"}
    assert mcpb_residue_map("ATOM      1  NE2 HD1 A  94       0.0 0.0 0.0\n")[(94, "NE2")] == "HD1"


def test_mcpb_translation_bonds_angles_charges(tmp_path):
    spec = _mcpb_files(tmp_path)
    atoms = _site_atoms(); site = find_sites(atoms)[0]; xo = _xyz_of(atoms)
    ff_q = {i: 0.0 for i in range(200)}; ff_q[0] = 2.0                 # force field: Zn2+, neutral HID residues
    out = resolve_site_params(site, spec, xo, residue_atoms=_residue_atoms(), ff_charges=ff_q)
    assert out["status"] == NEEDS_HUMAN and "不是整數" in out["why"]     # RESP set sums to +0.7
    spec = _mcpb_files(tmp_path, hid_charge_sum=0.1)                    # sums to +1.0: integer, but not the FF's +2
    out = resolve_site_params(site, spec, xo, residue_atoms=_residue_atoms(), ff_charges=ff_q)
    assert out["status"] == NEEDS_HUMAN and "整數不同" in out["why"]
    # make the imported set sum to +2 (Zn 0.7 + 3 × 0.4333…)
    spec = _mcpb_files(tmp_path, hid_charge_sum=1.3 / 3)
    out = resolve_site_params(site, spec, xo, residue_atoms=_residue_atoms(), ff_charges=ff_q)
    assert out["status"] == AUTO_FIXED, out["why"]
    assert out["bonds"][1]["k_kcal_A2"] == pytest.approx(2 * 38.70) and out["bonds"][1]["r0_A"] == 2.06
    assert out["bonds"][5]["k_kcal_A2"] == pytest.approx(2 * 41.20)                     # His96 is type Y2
    assert out["angles"][(1, 5)]["theta0_deg"] == 108.20 and out["angles"][(1, 3)]["k_kcal_rad2"] == pytest.approx(2 * 22.10)
    assert out["charges"][0] == 0.70 and len(out["charges"]) == 1 + 3 * len(HID_NAMES)
    assert sum(out["charges"].values()) == pytest.approx(2.0, abs=1e-3)   # mol2 charges are 4-decimal
    assert any("二面角" in c for c in out["caveats"])
    plan = plan_site(site, "bonded", xo, params=spec, residue_atoms=_residue_atoms())
    assert plan["source"] == "mcpb" and plan["charges"]["0"] == 0.70 and "MCPB.py" in plan["why"]


def test_mcpb_atom_name_mismatch_blocks(tmp_path):
    spec = _mcpb_files(tmp_path, hid_charge_sum=1.3 / 3)
    atoms = _site_atoms(); site = find_sites(atoms)[0]; xo = _xyz_of(atoms)
    ra = _residue_atoms(); ra["A:95"]["HE2"] = 999                   # system has HIP-like His95, MCPB model is HID
    out = resolve_site_params(site, spec, xo, residue_atoms=ra)
    assert out["status"] == NEEDS_HUMAN and "原子名不一致" in out["why"] and "HE2" in out["why"]
    spec2 = dict(spec, charges=False)
    out = resolve_site_params(site, spec2, xo, residue_atoms=ra)
    assert out["status"] == AUTO_FIXED and out["charges"] == {}


def test_mcpb_without_pdb_is_ambiguous(tmp_path):
    spec = _mcpb_files(tmp_path, hid_charge_sum=1.3 / 3); spec.pop("pdb")
    atoms = _site_atoms(); site = find_sites(atoms)[0]; xo = _xyz_of(atoms)
    out = resolve_site_params(site, spec, xo, residue_atoms=_residue_atoms())
    assert out["status"] == NEEDS_HUMAN and "metal_params.pdb" in out["why"]   # three His mol2 files: which NE2 is which?


# ------------------------------------------------------------------------------------------------ JSON
def test_json_source_by_label_name_or_element(tmp_path):
    atoms = _site_atoms(); site = find_sites(atoms)[0]; xo = _xyz_of(atoms)
    data = {"bonds": {"HIS94:NE2": {"k_kcal_A2": 80, "r0_A": 2.1}, "N": {"k_kcal_A2": 70}},
            "angles": {"default": {"k_kcal_rad2": 40}}, "charges": {"metal": 1.2}}
    f = tmp_path / "p.json"; f.write_text(json.dumps(data))
    out = resolve_site_params(site, {"source": "json", "file": str(f)}, xo, residue_atoms=_residue_atoms())
    assert out["status"] == AUTO_FIXED
    assert out["bonds"][1]["r0_A"] == 2.1 and out["bonds"][3]["r0_A"] == R0 and out["bonds"][3]["k_kcal_A2"] == 70
    assert all(abs(a["theta0_deg"] - 109.47) < 0.1 for a in out["angles"].values())     # θ0 defaults to the crystal angle
    assert out["charges"] == {0: 1.2}
    data["bonds"]["HIS94:NE2"]["r0_A"] = 2.6                                                 # 0.55 Å off the crystal
    f.write_text(json.dumps(data))
    out = resolve_site_params(site, {"source": "json", "file": str(f)}, xo)
    assert out["status"] == NEEDS_HUMAN and "與晶體" in out["why"]


def test_unknown_source_and_pending(tmp_path):
    atoms = _site_atoms(); site = find_sites(atoms)[0]; xo = _xyz_of(atoms)
    assert resolve_site_params(site, {"source": "zaff"}, xo)["status"] == NEEDS_HUMAN
    assert plan_site(site, "bonded", None, params={"source": "json"})["source"] == "pending"    # first pass never resolves


# ------------------------------------------------------------------------------------- QM cluster input
def _protonated_site_atoms():
    """Zn with HID94 (NE2 donor), CYM95 (SG donor), ASP96 (OD1 donor); full residues incl. backbone + H."""
    atoms = [{"index": 0, "name": "ZN", "resname": "ZN", "chain": "A", "resseq": "301", "xyz": ZN.tolist(), "element": "Zn",
              "is_protein": False}]
    idx = 1

    def add(name, res, seq, xyz, el):
        nonlocal idx
        atoms.append({"index": idx, "name": name, "resname": res, "chain": "A", "resseq": str(seq), "xyz": list(map(float, xyz)),
                      "element": el, "is_protein": True}); idx += 1
    for k, (res, donor, side) in enumerate((("HID", "NE2", ["CB", "HB2", "HB3", "CG", "ND1", "HD1", "CE1", "HE1", "NE2", "CD2", "HD2"]),
                                            ("CYM", "SG", ["CB", "HB2", "HB3", "SG"]),
                                            ("ASP", "OD1", ["CB", "HB2", "HB3", "CG", "OD1", "OD2"]))):
        d = DIRS[k]; base = ZN + R0 * d
        for i, nm in enumerate(side):
            off = 0.0 if nm == donor else 1.0 + 0.3 * i
            add(nm, res, 94 + k, base + off * d + (0.0 if nm == donor else 0.4 * i) * np.roll(d, 1), nm[0])
        cb = base + (1.0) * d
        for i, nm in enumerate(["CA", "N", "C", "O", "H", "HA"]):
            add(nm, res, 94 + k, cb + (2.0 + 0.5 * i) * d, nm[0])
    return atoms


def test_write_qm_cluster_caps_and_charges(tmp_path):
    from md20.build.metal_params import write_qm_cluster
    atoms = _protonated_site_atoms()
    site = find_sites(atoms)[0]
    assert {d["name"] for d in site["donors"]} == {"NE2", "SG", "OD1"}
    out = write_qm_cluster(atoms, site, tmp_path / "qm")
    assert out["status"] == "PASS" and out["charge"] == 0 and out["multiplicity"] == 1       # +2 −1 (CYM) −1 (ASP)
    assert out["n_atoms"] == 1 + (11 + 1) + (4 + 1) + (6 + 1) and len(out["frozen"]) == 3
    xyz = (tmp_path / "qm" / "cluster.xyz").read_text(encoding="utf-8").splitlines()
    assert xyz[0] == str(out["n_atoms"]) and xyz[2].startswith("Zn") and xyz[-1].startswith("H")   # capping H last per residue
    assert "CA" not in (tmp_path / "qm" / "cluster.xyz").read_text(encoding="utf-8")                            # no backbone in the model
    inp = (tmp_path / "qm" / "orca.inp").read_text(encoding="utf-8")
    assert "Opt Freq" in inp and "* xyz 0 1" in inp and inp.count("{ C ") == 3
    gjf = (tmp_path / "qm" / "gaussian.gjf").read_text(encoding="utf-8")
    assert "freq" in gjf and "\n0 1\n" in gjf and "X 2 F" in gjf
    assert "metal_params" in (tmp_path / "qm" / "README.md").read_text(encoding="utf-8")
    # the capping H sits 1.09 Å from CB along CB→CA
    hid_cb = next(a for a in atoms if a["resname"] == "HID" and a["name"] == "CB"); hid_ca = next(a for a in atoms if a["resname"] == "HID" and a["name"] == "CA")
    cap = np.array([float(v) for v in xyz[2 + 11 + 1].split()[1:]])
    assert abs(np.linalg.norm(cap - np.asarray(hid_cb["xyz"])) - 1.09) < 1e-3
    u = (np.asarray(hid_ca["xyz"]) - np.asarray(hid_cb["xyz"])); u /= np.linalg.norm(u)
    assert abs(np.dot((cap - np.asarray(hid_cb["xyz"])) / 1.09, u) - 1) < 1e-6


def test_write_qm_cluster_open_shell_needs_human(tmp_path):
    from md20.build.metal_params import write_qm_cluster
    atoms = _protonated_site_atoms()
    atoms[0].update(name="FE", resname="FE", element="Fe")
    site = find_sites(atoms)[0]
    out = write_qm_cluster(atoms, site, tmp_path / "qm")
    assert out["status"] == NEEDS_HUMAN and "自旋" in out["why"] and not (tmp_path / "qm").exists()
    out = write_qm_cluster(atoms, site, tmp_path / "qm", charge=2, multiplicity=5)
    assert out["status"] == "PASS" and out["charge"] == 0 and "* xyz 0 5" in (tmp_path / "qm" / "orca.inp").read_text(encoding="utf-8")
