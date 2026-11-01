"""Fitted metal-site parameters for `metal_policy: bonded` — three sources, one internal form.

The geometric bonded model in `metal.py` uses crystal distances/angles with generic force constants.  This
module lets a site use *fitted* parameters instead, without AmberTools on the student's machine:

  source "hessian"  (內建)  QM Hessian of the capped cluster model (Gaussian .fchk or ORCA .hess) → bond and
                           angle force constants by transforming the Cartesian Hessian to the site's internal
                           coordinates (Wilson B-matrix pseudo-inverse: metal–donor bonds, donor–metal–donor
                           angles, plus the donors' own bonds/angles so their coupling does not leak in);
                           r0/θ0 from the QM geometry.  The Seminario (1996) bond value is logged as a
                           cross-check.  Cluster atoms are matched to the protein site by element and
                           permutation-optimal superposition (never by atom order).  Charges unchanged.
  source "mcpb"     (轉譯)  MCPB.py output (frcmod + the residue mol2 files + the MCPB PDB) → bonds/angles by
                           atom type, RESP charges of the metal and its coordinating residues.
  source "json"             {"bonds": {"<donor label>": {"r0_A", "k_kcal_A2"}}, "angles": [...], "charges": {...}}
                           written by hand or by any other tool (Sobtop, ZAFF tables …).

Everything is checked before use (寧可擋也不要猜): every protein donor must get a bond, fitted r0 must stay
near the crystal distance, force constants must be physical, imported charges must sum to the same integer
as the force field's.  Anything else → NEEDS_HUMAN with the reason.

Conventions: internal k is OpenMM's, E = ½ k (r − r0)², kJ/mol/nm² (angles kJ/mol/rad²).  Amber frcmod uses
E = K (r − r0)², so k = 2·K.  The Hessian-derived k is already in the ½-k convention.
"""
from __future__ import annotations

import itertools
import math
import re
from pathlib import Path

import numpy as np

from .gates import AUTO_FIXED, NEEDS_HUMAN

HARTREE_BOHR2_TO_KCAL_A2 = 627.509474 / 0.529177210903 ** 2      # 2240.87
BOHR_TO_A = 0.529177210903
KCAL_A2_TO_KJ_NM2 = 4.184 * 100.0
KCAL_RAD2_TO_KJ_RAD2 = 4.184
MAX_R0_DEV_A = 0.25          # fitted r0 vs crystal distance
MAX_THETA_DEV_DEG = 15.0
K_BOND_RANGE = (10.0, 400.0)      # kcal/mol/Å² (½k convention); outside → not a metal–donor bond we trust
K_ANGLE_RANGE = (2.0, 200.0)      # kcal/mol/rad²
ELEMENT_Z = {"H": 1, "C": 6, "N": 7, "O": 8, "S": 16, "P": 15, "MG": 12, "CA": 20, "MN": 25, "FE": 26, "CO": 27,
             "NI": 28, "CU": 29, "ZN": 30, "CD": 48}
Z_ELEMENT = {v: k for k, v in ELEMENT_Z.items()}


# ================================================================================================ Hessian
def parse_fchk(text: str) -> dict:
    """Gaussian formatted checkpoint → {"z": [...], "xyz_A": (n,3), "hessian": (3n,3n) Hartree/Bohr²}."""
    def block(name):
        m = re.search(rf"^{re.escape(name)}\s+[RI]\s+N=\s*(\d+)\s*\n((?:[ \t]*[-+0-9.ED]+[ \t\n]+)+)", text, re.M)
        if not m:
            raise ValueError(f"fchk 缺少區塊「{name}」")
        vals = [float(v.replace("D", "E")) for v in m.group(2).split()]
        return np.asarray(vals[:int(m.group(1))])
    z = block("Atomic numbers").astype(int)
    xyz = block("Current cartesian coordinates").reshape(-1, 3) * BOHR_TO_A
    tri = block("Cartesian Force Constants")
    n3 = 3 * len(z)
    if len(tri) != n3 * (n3 + 1) // 2:
        raise ValueError("fchk 的 Cartesian Force Constants 長度與原子數不符（需為頻率計算的 fchk）")
    h = np.zeros((n3, n3))
    h[np.tril_indices(n3)] = tri
    h = h + h.T - np.diag(np.diag(h))
    return {"z": z.tolist(), "xyz_A": xyz, "hessian": h}


def parse_orca_hess(text: str) -> dict:
    """ORCA .hess → same dict (Hessian in Hartree/Bohr², coordinates in Bohr in the $atoms block)."""
    m = re.search(r"\$hessian\s*\n\s*(\d+)\s*\n(.*?)(?=\n\$|\Z)", text, re.S)
    if not m:
        raise ValueError("ORCA .hess 缺少 $hessian 區塊")
    n3 = int(m.group(1))
    h = np.zeros((n3, n3))
    cols: list[int] = []
    for line in m.group(2).splitlines():
        parts = line.split()
        if not parts:
            continue
        if all(p.isdigit() for p in parts):          # column header
            cols = [int(p) for p in parts]
        else:
            r = int(parts[0])
            for c, v in zip(cols, parts[1:]):
                h[r, c] = float(v)
    a = re.search(r"\$atoms\s*\n\s*(\d+)\s*\n(.*?)(?=\n\$|\Z)", text, re.S)
    if not a:
        raise ValueError("ORCA .hess 缺少 $atoms 區塊")
    z, xyz = [], []
    for line in a.group(2).splitlines()[:int(a.group(1))]:
        sym, _mass, x, y, zz = line.split()[:5]
        z.append(ELEMENT_Z.get(sym.upper(), 0)); xyz.append([float(x), float(y), float(zz)])
    return {"z": z, "xyz_A": np.asarray(xyz) * BOHR_TO_A, "hessian": h}


def load_hessian(path: Path | str) -> dict:
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="ignore")
    if p.suffix.lower() == ".fchk" or "Cartesian Force Constants" in text:
        return parse_fchk(text)
    if p.suffix.lower() == ".hess" or "$hessian" in text:
        return parse_orca_hess(text)
    raise ValueError(f"看不懂的 Hessian 檔：{p.name}（支援 Gaussian .fchk、ORCA .hess）")


def seminario_bond(hessian: np.ndarray, xyz_A: np.ndarray, i: int, j: int) -> tuple[float, float]:
    """Seminario (1996): k_ij = Σ_k λ_k |u_ij·v_k| from the eigen-decomposition of −H_ij.  Returns (k kcal/mol/Å²
    in the ½k convention, r0 Å)."""
    u = xyz_A[j] - xyz_A[i]
    r = float(np.linalg.norm(u)); u /= r
    sub = -hessian[3 * i:3 * i + 3, 3 * j:3 * j + 3]
    lam, vec = np.linalg.eig(sub)
    k = float(sum(abs(l) * abs(np.dot(u, vec[:, c])) for c, l in enumerate(lam)).real)
    return k * HARTREE_BOHR2_TO_KCAL_A2, r


def wilson_b_bond(x: np.ndarray, i: int, j: int) -> np.ndarray:
    u = x[i] - x[j]; u = u / np.linalg.norm(u)
    B = np.zeros(3 * len(x)); B[3 * i:3 * i + 3] = u; B[3 * j:3 * j + 3] = -u
    return B


def wilson_b_angle(x: np.ndarray, a: int, b: int, c: int) -> np.ndarray:
    u, v = x[a] - x[b], x[c] - x[b]
    ru, rv = np.linalg.norm(u), np.linalg.norm(v); u, v = u / ru, v / rv
    cos = float(np.dot(u, v)); sin = math.sqrt(max(1e-12, 1.0 - cos * cos))
    ga, gc = (cos * u - v) / (ru * sin), (cos * v - u) / (rv * sin)
    B = np.zeros(3 * len(x)); B[3 * a:3 * a + 3] = ga; B[3 * c:3 * c + 3] = gc; B[3 * b:3 * b + 3] = -ga - gc
    return B


def site_force_constants(hessian: np.ndarray, xyz_A: np.ndarray, metal: int, donors: list[int],
                         neighbours: dict[int, list[int]] | None = None) -> dict:
    """Internal-coordinate force constants of the site by the Wilson B-matrix transformation
    F_int = (B⁺)ᵀ H B⁺ over {metal–donor bonds, donor–metal–donor angles, donor–neighbour bonds,
    metal–donor–neighbour angles}.  Exact when the Hessian is a sum of harmonic terms in those coordinates
    (tests); the neighbour terms absorb the coupling that otherwise leaks into the angles.
    Returns {"bonds": {donor: (k kcal/mol/Å², r0 Å)}, "angles": {(d1, d2): (k kcal/mol/rad², θ0 deg)},
             "seminario_bonds": {donor: k}} — the Seminario value is a cross-check only."""
    xb = xyz_A / BOHR_TO_A
    rows, labels = [], []
    for d in donors:
        rows.append(wilson_b_bond(xb, metal, d)); labels.append(("b", d))
    for i in range(len(donors)):
        for j in range(i + 1, len(donors)):
            rows.append(wilson_b_angle(xb, donors[i], metal, donors[j])); labels.append(("a", donors[i], donors[j]))
    for d, nbs in (neighbours or {}).items():
        for n in nbs:
            rows.append(wilson_b_bond(xb, d, n)); labels.append(("x",))
            rows.append(wilson_b_angle(xb, metal, d, n)); labels.append(("x",))
    B = np.array(rows)
    Bp = np.linalg.pinv(B)
    F = Bp.T @ hessian @ Bp
    out = {"bonds": {}, "angles": {}, "seminario_bonds": {}}
    for k, lab in enumerate(labels):
        if lab[0] == "b":
            r0 = float(np.linalg.norm(xyz_A[metal] - xyz_A[lab[1]]))
            out["bonds"][lab[1]] = (float(F[k, k]) * HARTREE_BOHR2_TO_KCAL_A2, r0)
            out["seminario_bonds"][lab[1]] = seminario_bond(hessian, xyz_A, metal, lab[1])[0]
        elif lab[0] == "a":
            u, v = xyz_A[lab[1]] - xyz_A[metal], xyz_A[lab[2]] - xyz_A[metal]
            th = math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(u, v) / np.linalg.norm(u) / np.linalg.norm(v))))))
            out["angles"][(lab[1], lab[2])] = (float(F[k, k]) * 627.509474, th)
    return out


def cluster_neighbours(z: list[int], xyz_A: np.ndarray, atom: int, exclude: set[int]) -> list[int]:
    """Covalently bonded neighbours of a cluster atom (distance < 1.9 Å, 2.2 Å for S), excluding `exclude`."""
    cut = 2.2 if Z_ELEMENT.get(z[atom]) == "S" else 1.9
    d = np.linalg.norm(xyz_A - xyz_A[atom], axis=1)
    return [i for i in range(len(z)) if i != atom and i not in exclude and d[i] < cut]


def match_cluster_to_site(cluster_z: list[int], cluster_xyz: np.ndarray, metal_element: str, site_xyz: dict,
                          donor_elements: dict) -> tuple[dict | None, float, str]:
    """Find the metal and its donors in the QM cluster and map them onto the protein site atoms.

    site_xyz: {atom_index: xyz Å} for metal + donors; donor_elements: {atom_index: "N"/"O"/"S"}; the metal is the
    key whose element matches `metal_element`.  Returns ({protein_index: cluster_index}, rmsd Å, why)."""
    zm = ELEMENT_Z.get(metal_element.upper())
    metals = [i for i, z in enumerate(cluster_z) if z == zm]
    if len(metals) != 1:
        return None, math.inf, f"QM cluster 中有 {len(metals)} 個 {metal_element}（需恰好 1 個）"
    cm = metals[0]
    prot_metal = next(i for i in site_xyz if i not in donor_elements)
    donors = list(donor_elements)
    # candidate cluster atoms: same element, within 3.0 Å of the cluster metal
    d = np.linalg.norm(cluster_xyz - cluster_xyz[cm], axis=1)
    cand = {el: [i for i, z in enumerate(cluster_z) if Z_ELEMENT.get(z) == el and 0.5 < d[i] < 3.0]
            for el in set(donor_elements.values())}
    pools = [cand[donor_elements[i]] for i in donors]
    best, best_rmsd = None, math.inf
    P = np.array([np.asarray(site_xyz[i]) - np.asarray(site_xyz[prot_metal]) for i in donors])
    for choice in itertools.product(*pools):
        if len(set(choice)) != len(choice):
            continue
        Q = np.array([cluster_xyz[c] - cluster_xyz[cm] for c in choice])
        rmsd = _kabsch_rmsd(P, Q)
        if rmsd < best_rmsd:
            best, best_rmsd = choice, rmsd
    if best is None:
        return None, math.inf, "QM cluster 中找不到與蛋白配位原子元素相符、且在金屬 3 Å 內的原子"
    mapping = {prot_metal: cm, **{i: c for i, c in zip(donors, best)}}
    return mapping, best_rmsd, f"金屬＋{len(donors)} 個配位原子以最佳置換疊合，RMSD {best_rmsd:.2f} Å"


def _kabsch_rmsd(P: np.ndarray, Q: np.ndarray) -> float:
    h = P.T @ Q
    u, _, vt = np.linalg.svd(h)
    dsign = np.sign(np.linalg.det(vt.T @ u.T))
    dm = np.diag([1, 1, dsign])
    r = vt.T @ dm @ u.T
    return float(np.sqrt(np.mean(np.sum((P @ r.T - Q) ** 2, axis=1))))


# =================================================================================================== MCPB
def parse_frcmod(text: str) -> dict:
    """Amber frcmod → {"bonds": {(t1,t2): (K kcal/mol/Å², r0 Å)}, "angles": {(t1,t2,t3): (K, θ0 deg)}}.
    Type pairs are stored in both orders.  Dihedrals/impropers/nonbonded are reported but not used."""
    out = {"bonds": {}, "angles": {}, "ignored": []}
    section = None
    for raw in text.splitlines():
        line = raw.rstrip()
        key = line.strip().upper()
        if key in ("MASS", "BOND", "ANGLE", "DIHE", "IMPROPER", "NONBON", "NONB"):
            section = key; continue
        if not line.strip():
            section = None if section in ("BOND", "ANGLE") else section
            continue
        if section == "BOND":
            m = re.match(r"\s*(\S+?)\s*-\s*(\S+?)\s+([-\d.]+)\s+([-\d.]+)", line)
            if m:
                t1, t2, k, r0 = m.group(1), m.group(2), float(m.group(3)), float(m.group(4))
                out["bonds"][(t1, t2)] = out["bonds"][(t2, t1)] = (k, r0)
        elif section == "ANGLE":
            m = re.match(r"\s*(\S+?)\s*-\s*(\S+?)\s*-\s*(\S+?)\s+([-\d.]+)\s+([-\d.]+)", line)
            if m:
                t = (m.group(1), m.group(2), m.group(3)); v = (float(m.group(4)), float(m.group(5)))
                out["angles"][t] = out["angles"][t[::-1]] = v
        elif section in ("DIHE", "IMPROPER", "NONBON", "NONB"):
            out["ignored"].append(f"{section}: {line.strip()}")
    return out


def parse_mol2(text: str) -> dict:
    """Tripos mol2 → {"resname": ..., "atoms": {name: {"type", "charge"}}} (first residue name wins)."""
    atoms, resname = {}, None
    sect = None
    for line in text.splitlines():
        if line.startswith("@<TRIPOS>"):
            sect = line.strip(); continue
        if sect == "@<TRIPOS>ATOM" and line.strip():
            p = line.split()
            if len(p) < 6:
                continue
            name, typ = p[1], p[5]
            rn = p[7] if len(p) > 7 else None
            q = float(p[8]) if len(p) > 8 else None
            resname = resname or (re.sub(r"\d+$", "", rn) if rn else None)
            atoms[name] = {"type": typ, "charge": q, "resname": rn}
    return {"resname": resname, "atoms": atoms}


def mcpb_residue_map(pdb_text: str) -> dict:
    """MCPB-renamed PDB → {(resseq, atom name): residue name} (chain ignored: MCPB files usually drop it)."""
    out = {}
    for line in pdb_text.splitlines():
        if line.startswith(("ATOM", "HETATM")):
            out[(int(line[22:26]), line[12:16].strip())] = line[17:20].strip()
    return out


# ======================================================================================= resolution per site
def _bond_label(d: dict) -> str:
    return f"{d['resname']}{d['resseq']}:{d['name']}"


def resolve_site_params(site: dict, spec: dict, xyz_of: dict, *, ff_charges: dict | None = None,
                        residue_atoms: dict | None = None) -> dict:
    """Turn a `metal_params` spec into checked per-atom parameters for one site.

    site: from metal.find_sites (metal_index, donors with index/name/resname/resseq/element/distance_A).
    xyz_of: {atom_index: xyz Å}.  residue_atoms: {"chain:resseq": {atom name: index}} (for charges).
    ff_charges: {atom_index: q} current force-field charges (to check the imported total).
    Returns {status, source, bonds: {donor_index: {r0_nm, k}}, angles: {(i,j): {theta0_deg, k}}, charges: {index: q},
             why, caveats, evidence}."""
    src = (spec or {}).get("source")
    try:
        if src == "hessian":
            out = _from_hessian(site, spec, xyz_of)
        elif src == "mcpb":
            out = _from_mcpb(site, spec, xyz_of, residue_atoms or {})
        elif src == "json":
            out = _from_json(site, spec, xyz_of, residue_atoms or {})
        else:
            return _fail(src, f"metal_params.{site['key']}.source 必須是 hessian / mcpb / json（目前：{src}）")
    except (ValueError, KeyError, OSError) as exc:
        return _fail(src, f"讀取擬合參數失敗：{exc}")
    if out["status"] == NEEDS_HUMAN:
        return out
    return _validate(site, out, xyz_of, ff_charges or {})


def _fail(src, why) -> dict:
    return {"status": NEEDS_HUMAN, "source": src, "bonds": {}, "angles": {}, "charges": {}, "why": why, "caveats": [],
            "evidence": {}, "options": ["修正 metal_params 設定", "改用幾何鍵結模型（移除 metal_params）", "改用 keep_nonbonded"]}


def _from_hessian(site, spec, xyz_of) -> dict:
    data = load_hessian(spec["file"])
    metal_el = site["key"].split(":")[0]
    donors = site["donors"]
    site_xyz = {site["metal_index"]: xyz_of[site["metal_index"]], **{d["index"]: xyz_of[d["index"]] for d in donors}}
    mapping, rmsd, why = match_cluster_to_site(data["z"], data["xyz_A"], metal_el, site_xyz, {d["index"]: d["element"] for d in donors})
    if mapping is None:
        return _fail("hessian", why)
    if rmsd > 0.6:
        return _fail("hessian", f"QM cluster 的配位幾何與晶體差異過大（{why}）；cluster 可能不是這個位點或已重排。")
    H, X = data["hessian"], data["xyz_A"]
    cm = mapping[site["metal_index"]]
    cd = [mapping[d["index"]] for d in donors]
    nbs = {c: cluster_neighbours(data["z"], X, c, {cm}) for c in cd}
    fc = site_force_constants(H, X, cm, cd, nbs)
    bonds, angles, xcheck = {}, {}, {}
    for d in donors:
        k, r0 = fc["bonds"][mapping[d["index"]]]
        bonds[d["index"]] = {"r0_nm": r0 / 10.0, "k": k * KCAL_A2_TO_KJ_NM2, "k_kcal_A2": k, "r0_A": r0}
        xcheck[_bond_label(d)] = round(fc["seminario_bonds"][mapping[d["index"]]], 1)
    for i in range(len(donors)):
        for j in range(i + 1, len(donors)):
            a, b = donors[i]["index"], donors[j]["index"]
            k, th = fc["angles"][(mapping[a], mapping[b])]
            angles[(a, b)] = {"theta0_deg": th, "k": k * KCAL_RAD2_TO_KJ_RAD2, "k_kcal_rad2": k}
    return {"status": AUTO_FIXED, "source": "hessian", "bonds": bonds, "angles": angles, "charges": {},
            "why": f"由 QM Hessian（{Path(spec['file']).name}）以內座標（Wilson B 矩陣）轉換擬合金屬–配位鍵與角；{why}。",
            "caveats": ["力常數與平衡值來自 QM cluster 模型（Hessian 內座標轉換；Seminario 鍵值列為交叉檢查）；電荷沿用力場（未做 RESP）。"],
            "evidence": {"cluster_rmsd_A": round(rmsd, 3), "n_cluster_atoms": len(data["z"]), "seminario_bond_k_kcal_A2": xcheck}}


def _from_mcpb(site, spec, xyz_of, residue_atoms) -> dict:
    frc = parse_frcmod(Path(spec["frcmod"]).read_text(encoding="utf-8", errors="ignore"))
    mols = [parse_mol2(Path(m).read_text(encoding="utf-8", errors="ignore")) for m in spec.get("mol2", [])]
    pdb_map = mcpb_residue_map(Path(spec["pdb"]).read_text(encoding="utf-8", errors="ignore")) if spec.get("pdb") else {}
    by_res = {m["resname"]: m for m in mols if m["resname"]}
    by_res.update({a["resname"]: m for m in mols for a in m["atoms"].values() if a.get("resname")})

    def typed(resseq: int, name: str, fallback_res: str | None):
        rn = pdb_map.get((int(resseq), name)) or fallback_res
        m = by_res.get(rn) if rn else None
        if m is None:
            cands = [m for m in mols if name in m["atoms"]]
            if len(cands) != 1:
                raise ValueError(f"無法決定殘基 {resseq} 原子 {name} 對應的 mol2（候選 {len(cands)} 個）；請提供 MCPB 產生的 PDB（metal_params.pdb）")
            m = cands[0]
        if name not in m["atoms"]:
            raise ValueError(f"mol2 {m['resname']} 沒有原子 {name}")
        return m, m["atoms"][name]["type"]
    metal_name = site["key"].split(":")[0]
    mres, mt = typed(re.sub(r"^\D*", "", site["key"].split(":")[1]), metal_name, None)
    bonds, angles, charges = {}, {}, {}
    donor_types = {}
    for d in site["donors"]:
        m, t = typed(d["resseq"], d["name"], None)
        donor_types[d["index"]] = (m, t)
        if (mt, t) not in frc["bonds"]:
            raise ValueError(f"frcmod 沒有鍵 {mt}-{t}（{_bond_label(d)}）")
        K, r0 = frc["bonds"][(mt, t)]
        bonds[d["index"]] = {"r0_nm": r0 / 10.0, "k": 2 * K * KCAL_A2_TO_KJ_NM2, "k_kcal_A2": 2 * K, "r0_A": r0}
    ds = site["donors"]
    for i in range(len(ds)):
        for j in range(i + 1, len(ds)):
            a, b = ds[i]["index"], ds[j]["index"]
            key = (donor_types[a][1], mt, donor_types[b][1])
            if key not in frc["angles"]:
                raise ValueError(f"frcmod 沒有角 {'-'.join(key)}")
            K, th = frc["angles"][key]
            angles[(a, b)] = {"theta0_deg": th, "k": 2 * K * KCAL_RAD2_TO_KJ_RAD2, "k_kcal_rad2": 2 * K}
    if spec.get("charges", True):
        # metal charge + every atom of each coordinating residue, by atom name
        mq = mres["atoms"][metal_name]["charge"]
        if mq is not None:
            charges[site["metal_index"]] = mq
        for d in ds:
            m = donor_types[d["index"]][0]
            rid = f"{d['chain']}:{d['resseq']}"
            names = residue_atoms.get(rid) or {}
            missing = [n for n in names if n not in m["atoms"]]
            extra = [n for n in m["atoms"] if n not in names]
            if missing or extra:
                raise ValueError(f"殘基 {rid} 與 mol2 {m['resname']} 的原子名不一致（系統多出 {missing}；mol2 多出 {extra}）；"
                                 "通常是質子化狀態不同，請確認 MCPB 模型用的互變異構體")
            for n, idx in names.items():
                if m["atoms"][n]["charge"] is not None:
                    charges[idx] = m["atoms"][n]["charge"]
    return {"status": AUTO_FIXED, "source": "mcpb", "bonds": bonds, "angles": angles, "charges": charges,
            "why": f"由 MCPB.py 輸出轉譯（{Path(spec['frcmod']).name}，{len(mols)} 個 mol2）：鍵／角依原子型態查表"
                   + ("，RESP 電荷套用到金屬與配位殘基" if charges else "，電荷沿用力場") + "。",
            "caveats": ["MCPB.py 的二面角與 LJ 參數未轉譯（金屬 LJ 沿用力場離子模型）。"] +
                       ([f"frcmod 內 {len(frc['ignored'])} 行（DIHE/IMPROPER/NONBON）未使用。"] if frc["ignored"] else []),
            "evidence": {"metal_type": mt, "donor_types": {str(k): v[1] for k, v in donor_types.items()}}}


def _from_json(site, spec, xyz_of, residue_atoms) -> dict:
    import json
    data = json.loads(Path(spec["file"]).read_text(encoding="utf-8")) if spec.get("file") else spec.get("data") or {}
    bonds, angles, charges = {}, {}, {}
    jb = data.get("bonds") or {}
    for d in site["donors"]:
        lab = _bond_label(d)
        rec = jb.get(lab) or jb.get(d["name"]) or jb.get(d["element"])
        if not rec:
            raise ValueError(f"json 缺少配位原子 {lab} 的鍵參數（可用鍵名：{lab}、{d['name']} 或元素 {d['element']}）")
        k = float(rec["k_kcal_A2"]); r0 = float(rec.get("r0_A") or d["distance_A"])
        bonds[d["index"]] = {"r0_nm": r0 / 10.0, "k": k * KCAL_A2_TO_KJ_NM2, "k_kcal_A2": k, "r0_A": r0}
    ja = data.get("angles") or {}
    ds = site["donors"]
    for i in range(len(ds)):
        for j in range(i + 1, len(ds)):
            a, b = ds[i], ds[j]
            rec = ja.get(f"{_bond_label(a)}|{_bond_label(b)}") or ja.get(f"{_bond_label(b)}|{_bond_label(a)}") or ja.get("default")
            if not rec:
                raise ValueError(f"json 缺少角 {_bond_label(a)}–金屬–{_bond_label(b)} 的參數（或 angles.default）")
            from .metal import _angle
            th = float(rec.get("theta0_deg") or _angle(xyz_of[a["index"]], xyz_of[site["metal_index"]], xyz_of[b["index"]]))
            k = float(rec["k_kcal_rad2"])
            angles[(a["index"], b["index"])] = {"theta0_deg": th, "k": k * KCAL_RAD2_TO_KJ_RAD2, "k_kcal_rad2": k}
    for rid, qs in (data.get("charges") or {}).items():
        names = residue_atoms.get(rid)
        if rid == "metal":
            charges[site["metal_index"]] = float(qs); continue
        if not names:
            raise ValueError(f"json charges 指到不存在的殘基 {rid}（格式 chain:resseq）")
        for n, q in qs.items():
            if n not in names:
                raise ValueError(f"殘基 {rid} 沒有原子 {n}")
            charges[names[n]] = float(q)
    return {"status": AUTO_FIXED, "source": "json", "bonds": bonds, "angles": angles, "charges": charges,
            "why": "由使用者提供的參數檔（json）套用鍵／角" + ("與電荷" if charges else "") + "。",
            "caveats": ["參數來源由使用者負責（報告列出檔名與數值）。"], "evidence": {"file": spec.get("file")}}


def _validate(site, out, xyz_of, ff_charges) -> dict:
    problems = []
    for d in site["donors"]:
        b = out["bonds"].get(d["index"])
        if b is None:
            problems.append(f"{_bond_label(d)} 沒有鍵參數"); continue
        if abs(b["r0_A"] - d["distance_A"]) > MAX_R0_DEV_A:
            problems.append(f"{_bond_label(d)} 擬合 r0 {b['r0_A']:.2f} Å 與晶體 {d['distance_A']:.2f} Å 差 > {MAX_R0_DEV_A} Å")
        if not K_BOND_RANGE[0] <= b["k_kcal_A2"] <= K_BOND_RANGE[1]:
            problems.append(f"{_bond_label(d)} 鍵力常數 {b['k_kcal_A2']:.1f} kcal/mol/Å² 超出合理範圍 {K_BOND_RANGE}")
    from .metal import _angle
    ds = {d["index"]: d for d in site["donors"]}
    for (a, b), rec in out["angles"].items():
        cryst = _angle(xyz_of[a], xyz_of[site["metal_index"]], xyz_of[b])
        if abs(rec["theta0_deg"] - cryst) > MAX_THETA_DEV_DEG:
            problems.append(f"角 {_bond_label(ds[a])}–M–{_bond_label(ds[b])} θ0 {rec['theta0_deg']:.0f}° 與晶體 {cryst:.0f}° 差 > {MAX_THETA_DEV_DEG}°")
        if not K_ANGLE_RANGE[0] <= rec["k_kcal_rad2"] <= K_ANGLE_RANGE[1]:
            problems.append(f"角力常數 {rec['k_kcal_rad2']:.1f} kcal/mol/rad² 超出合理範圍 {K_ANGLE_RANGE}")
    if out["charges"] and ff_charges:
        idx = list(out["charges"])
        old = sum(ff_charges.get(i, 0.0) for i in idx); new = sum(out["charges"].values())
        if abs(new - round(new)) > 0.02:
            problems.append(f"匯入電荷總和 {new:.3f} 不是整數")
        elif abs(round(new) - round(old)) > 0.5:
            problems.append(f"匯入電荷總和 {new:+.2f} 與力場原本 {old:+.2f} 的整數不同（位點淨電荷改變）")
    if problems:
        return {**_fail(out["source"], f"擬合參數未通過檢查：" + "；".join(problems) + "。"), "evidence": out.get("evidence", {})}
    out["evidence"] = {**out.get("evidence", {}),
                       "bonds": {str(i): {"r0_A": round(b["r0_A"], 3), "k_kcal_A2": round(b["k_kcal_A2"], 1)} for i, b in out["bonds"].items()},
                       "angles": [{"a": a, "b": b, "theta0_deg": round(r["theta0_deg"], 1), "k_kcal_rad2": round(r["k_kcal_rad2"], 1)}
                                  for (a, b), r in out["angles"].items()],
                       "n_charges": len(out["charges"])}
    return out


# ===================================================================================== QM cluster model input
BACKBONE_NAMES = {"N", "CA", "C", "O", "H", "HA", "HA2", "HA3", "H1", "H2", "H3", "OXT", "H2", "H3"}
SIDECHAIN_CHARGE = {"CYM": -1, "ASP": -1, "GLU": -1, "HIP": +1, "LYS": +1, "ARG": +1, "TYM": -1}
CLOSED_SHELL = {"ZN": (2, 1), "CD": (2, 1), "MG": (2, 1), "CA": (2, 1)}       # (oxidation state, multiplicity)
OPEN_SHELL_HINT = {"FE": "Fe(II) 高自旋 5、低自旋 1；Fe(III) 高自旋 6", "CU": "Cu(II) 2；Cu(I) 1", "MN": "Mn(II) 高自旋 6",
                   "CO": "Co(II) 高自旋 4；Co(III) 低自旋 1", "NI": "Ni(II) 3（四面體）或 1（平面四方）"}


def write_qm_cluster(atoms: list[dict], site: dict, out_dir: Path | str, *, charge: int | None = None,
                     multiplicity: int | None = None, method: str = "B3LYP D3BJ def2-SVP") -> dict:
    """Small-model QM input for the site, MCPB.py-style: metal + the coordinating side chains cut at Cα→Cβ
    (the Cα becomes a capping H at 1.09 Å, so each residue is its methyl-capped side chain), hydrogens as in the
    protonated receptor topology.  Writes cluster.xyz, orca.inp (Opt+Freq, capping carbons frozen so the
    fragments keep the protein's arrangement), gaussian.gjf and a Chinese README with the next steps.

    atoms: the receptor atoms (index, name, resname, chain, resseq, element, xyz Å) *after* protonation.
    Returns {"status", "files", "charge", "multiplicity", "n_atoms", "why"}; open-shell metals without an
    explicit charge/multiplicity → NEEDS_HUMAN (never guess a spin state)."""
    out_dir = Path(out_dir)
    metal_el = site["key"].split(":")[0].upper()
    by_res: dict[str, list[dict]] = {}
    for a in atoms:
        by_res.setdefault(f"{a['chain']}:{a['resseq']}", []).append(a)
    metal = next(a for a in atoms if a["index"] == site["metal_index"])
    donor_res = sorted({f"{d['chain']}:{d['resseq']}" for d in site["donors"]})
    cluster, frozen, total_q = [(metal_el.capitalize(), np.asarray(metal["xyz"], float))], [], 0
    if charge is None:
        if metal_el in CLOSED_SHELL:
            total_q, multiplicity = CLOSED_SHELL[metal_el][0], multiplicity or CLOSED_SHELL[metal_el][1]
        else:
            return {"status": NEEDS_HUMAN, "files": [], "why": f"{metal_el} 不是閉殼層金屬，QM 模型的氧化態與自旋多重度不能猜"
                    f"（{OPEN_SHELL_HINT.get(metal_el, '請查文獻')}）；請在 metal_params.{site['key']} 設定 qm_charge 與 qm_multiplicity。"}
    else:
        total_q = int(charge)
        if multiplicity is None:
            if metal_el in CLOSED_SHELL:
                multiplicity = CLOSED_SHELL[metal_el][1]
            else:
                return {"status": NEEDS_HUMAN, "files": [], "why": f"{metal_el}：已指定電荷但缺自旋多重度（qm_multiplicity）。"}
    residues = []
    for rid in donor_res:
        ra = by_res.get(rid, [])
        if not ra:
            continue
        resname = ra[0]["resname"].upper()
        names = {a["name"]: a for a in ra}
        if "CA" not in names or "CB" not in names:
            return {"status": NEEDS_HUMAN, "files": [], "why": f"殘基 {rid}（{resname}）沒有 CA/CB，無法切出側鏈模型（Gly 或非標準殘基）。"}
        side = [a for a in ra if a["name"] not in BACKBONE_NAMES]
        ca, cb = np.asarray(names["CA"]["xyz"], float), np.asarray(names["CB"]["xyz"], float)
        cap = cb + 1.09 * (ca - cb) / np.linalg.norm(ca - cb)
        for a in side:
            cluster.append((a["element"].capitalize() if a.get("element") else a["name"][0], np.asarray(a["xyz"], float)))
            if a["name"] == "CB":
                frozen.append(len(cluster) - 1)
        cluster.append(("H", cap))
        q = SIDECHAIN_CHARGE.get(resname, 0)
        total_q += q
        residues.append({"residue": rid, "resname": resname, "n_atoms": len(side) + 1, "charge": q})
    out_dir.mkdir(parents=True, exist_ok=True)
    n = len(cluster)
    xyz_lines = [f"{el:<3s} {p[0]:12.6f} {p[1]:12.6f} {p[2]:12.6f}" for el, p in cluster]
    (out_dir / "cluster.xyz").write_text(f"{n}\nMD20 QM cluster {site['key']} charge={total_q} mult={multiplicity}\n"
                                         + "\n".join(xyz_lines) + "\n", encoding="utf-8")
    cons = "".join(f"  {{ C {i} C }}\n" for i in frozen)
    (out_dir / "orca.inp").write_text(
        f"! {method} Opt Freq TightSCF\n%pal nprocs 4 end\n%maxcore 2000\n%geom\n Constraints\n{cons} end\nend\n"
        f"* xyz {total_q} {multiplicity}\n" + "\n".join(xyz_lines) + "\n*\n", encoding="utf-8")
    gmethod = method.lower().replace(" d3bj", " empiricaldispersion=gd3bj").replace(" def2-svp", "/def2svp").replace("b3lyp", "B3LYP")
    (out_dir / "gaussian.gjf").write_text(
        f"%chk=cluster.chk\n%nprocshared=4\n%mem=8GB\n#p {gmethod} opt=modredundant freq\n\nMD20 QM cluster {site['key']}\n\n"
        f"{total_q} {multiplicity}\n" + "\n".join(xyz_lines) + "\n\n" + "".join(f"X {i + 1} F\n" for i in frozen) + "\n",
        encoding="utf-8")
    (out_dir / "README.md").write_text(
        f"# {site['key']} QM 小模型（擬合金屬鍵結參數用）\n\n"
        f"- 內容：金屬 + {len(residues)} 個配位殘基的側鏈（Cα 以 H 封端），共 {n} 原子；電荷 {total_q:+d}、多重度 {multiplicity}。\n"
        f"- 配位殘基：" + "、".join(f"{r['residue']} {r['resname']}（{r['charge']:+d}）" for r in residues) + "。\n"
        f"- 方法：{method}，Opt + Freq；Cβ 固定（保持蛋白中的相對排列）。\n\n"
        "## 下一步\n"
        "1. 用 ORCA（免費）跑 `orca orca.inp > orca.out`，或用 Gaussian 跑 `gaussian.gjf` 後 `formchk cluster.chk cluster.fchk`。\n"
        "2. 確認沒有虛頻（Freq 全為正）；若有，先在 QM 程式中重新最佳化。\n"
        "3. 把 `orca.hess`（或 `cluster.fchk`）放到工作流程資料夾，在設定檔加上：\n"
        f"   ```json\n   \"metal_params\": {{\"{site['key']}\": {{\"source\": \"hessian\", \"file\": \"orca.hess\"}}}}\n   ```\n"
        "4. 重新建模：程式會把 Hessian 轉成金屬–配位鍵與角的力常數並檢查（r0 與晶體差 > 0.25 Å、力常數不合理都會擋下）。\n"
        "5. 電荷仍沿用力場；若要 RESP 電荷，請走 MCPB.py 路徑（source: mcpb）。\n", encoding="utf-8")
    return {"status": "PASS", "files": [str(out_dir / f) for f in ("cluster.xyz", "orca.inp", "gaussian.gjf", "README.md")],
            "charge": total_q, "multiplicity": multiplicity, "n_atoms": n, "residues": residues, "frozen": frozen,
            "why": f"已產生 {site['key']} 的 QM 小模型輸入（{n} 原子，電荷 {total_q:+d}，多重度 {multiplicity}）於 {out_dir}；"
                   "算完 Hessian 後可在 metal_params 指定檔案，升級為擬合參數。"}
