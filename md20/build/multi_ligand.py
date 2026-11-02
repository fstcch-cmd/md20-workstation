"""Multi-ligand complex geometry (D-60): find poses that cannot enter MD, repair the ones a small rigid move can fix,
and name the ligand to exclude when nothing can.  Pure numpy (coordinates in Å) so it runs and is tested anywhere.

Why this exists.  Simultaneous docking scores ligands with a soft, electrostatics-free function, then the build adds the
hydrogens Vina never saw.  Two failure kinds reach MD:
  * overlaps — atoms of two molecules closer than any real contact; the minimiser pushes them apart violently, often
    ejecting the lighter ligand or producing NaN;
  * ring piercing (穿環) — a bond of one molecule threads through a ring of another (ligand–ligand, protein ring–ligand
    bond, ligand ring–protein bond).  Energy minimisation cannot undo it: the bond stays locked through the ring (a
    catenane-like artefact) with absurd strain, and the simulation either explodes or silently samples an impossible
    complex.  It must be caught before minimisation.

Checks, in order of severity:
  piercing          bond from another molecule crosses a ring plane inside the ring polygon
  overlap           heavy–heavy < 2.2 Å, heavy–H < 1.3 Å, H–H < 1.0 Å between molecules (hydrogen bonds sit at ≥ 1.5 Å
                    H···acceptor and ≥ 2.5 Å donor···acceptor, so real contacts are never flagged; metals are skipped)
  floating          a ligand with < 3 protein heavy atoms within 4 Å and no other ligand within 4.5 Å — it is not bound
                    to anything in this pose and will drift into the solvent

Repair (`relieve`): rigid-body moves of one ligand (rotation ≤ 30° about its centroid, translation ≤ 2 Å), tried from the
smallest displacement up; accepted when it removes every overlap and piercing of that ligand, keeps ≥ 70 % of its
protein contacts and moves the ligand ≤ 2.0 Å RMSD — i.e. the same binding mode, nudged.  Larger corrections are a
different pose and are left to a human.

Exclusion (`culprit`): the ligand involved in most unresolved problems; ties go to the one with fewer protein contacts
(the less anchored, less credible pose).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

COVALENT = {"H": 0.31, "C": 0.76, "N": 0.71, "O": 0.66, "S": 1.05, "P": 1.07, "F": 0.57, "CL": 1.02, "BR": 1.20, "I": 1.39,
            "B": 0.84, "SE": 1.20, "SI": 1.11}
METALS = {"ZN", "MG", "CA", "MN", "FE", "CU", "CO", "NI", "NA", "K", "CD", "HG"}
HEAVY_HEAVY, HEAVY_H, H_H = 2.2, 1.3, 1.0
CONTACT_A, FLOAT_CONTACTS, FLOAT_LL = 4.0, 3, 4.5
MAX_NUDGE_RMSD, MAX_ROT_DEG, MAX_SHIFT_A, KEEP_CONTACTS = 2.0, 30.0, 2.0, 0.7


@dataclass
class Mol:
    """One molecule (protein or ligand): element symbols (upper case), coordinates (Å), optional bonds."""
    name: str
    elements: list[str]
    xyz: np.ndarray
    bonds: list[tuple[int, int]] | None = None
    is_protein: bool = False
    rings: list[list[int]] = field(default_factory=list)

    def __post_init__(self):
        self.elements = [e.upper() for e in self.elements]
        self.xyz = np.asarray(self.xyz, float).reshape(-1, 3)
        if self.bonds is None:
            self.bonds = infer_bonds(self.elements, self.xyz)
        if not self.rings:
            self.rings = find_rings(len(self.elements), self.bonds)

    @property
    def heavy(self) -> np.ndarray:
        return np.array([e != "H" for e in self.elements])


# ------------------------------------------------------------------------------------------------ topology helpers
def infer_bonds(elements: list[str], xyz: np.ndarray, tol: float = 0.45) -> list[tuple[int, int]]:
    xyz = np.asarray(xyz, float)
    r = np.array([COVALENT.get(e.upper(), 1.4) for e in elements])
    out = []
    order = np.argsort(xyz[:, 0])
    xs = xyz[order, 0]
    for a_i, a in enumerate(order):
        hi = np.searchsorted(xs, xs[a_i] + 2.6, side="right")
        for b in order[a_i + 1:hi]:
            d = float(np.linalg.norm(xyz[a] - xyz[b]))
            if 0.4 < d < r[a] + r[b] + tol and not (elements[a].upper() in METALS or elements[b].upper() in METALS):
                out.append((int(min(a, b)), int(max(a, b))))
    return out


def find_rings(n: int, bonds: list[tuple[int, int]], max_size: int = 8) -> list[list[int]]:
    """Smallest ring through every bond (ordered atom lists), deduplicated; enough for piercing tests."""
    adj = [[] for _ in range(n)]
    for a, b in bonds:
        adj[a].append(b); adj[b].append(a)
    rings, seen = [], set()
    for a, b in bonds:
        prev = {a: None}
        frontier = [a]
        found = None
        for _depth in range(max_size - 1):
            nxt = []
            for u in frontier:
                for v in adj[u]:
                    if (u == a and v == b) or v in prev:
                        continue
                    prev[v] = u
                    if v == b:
                        found = v
                        break
                    nxt.append(v)
                if found is not None:
                    break
            if found is not None or not nxt:
                break
            frontier = nxt
        if found is None:
            continue
        path = [b]
        while path[-1] != a:
            path.append(prev[path[-1]])
        if 3 <= len(path) <= max_size:
            key = frozenset(path)
            if key not in seen:
                seen.add(key)
                rings.append(path)
    return rings


def _ring_frame(P: np.ndarray):
    c = P.mean(0)
    _, _, vt = np.linalg.svd(P - c)
    return c, vt[2], vt[0], vt[1]


def _inside(poly2: np.ndarray, x2: np.ndarray) -> bool:
    inside = False
    n = len(poly2)
    for i in range(n):
        (x1, y1), (x2_, y2) = poly2[i], poly2[(i + 1) % n]
        if (y1 > x2[1]) != (y2 > x2[1]):
            xc = x1 + (x2[1] - y1) * (x2_ - x1) / (y2 - y1)
            if xc > x2[0]:
                inside = not inside
    return inside


def bond_pierces_ring(P: np.ndarray, a: np.ndarray, b: np.ndarray) -> bool:
    """True when segment a–b crosses the plane of ring P inside the ring polygon."""
    c, nrm, u, w = _ring_frame(P)
    sa, sb = float((a - c) @ nrm), float((b - c) @ nrm)
    if sa * sb >= 0:
        return False
    x = a + (sa / (sa - sb)) * (b - a)
    poly2 = np.c_[(P - c) @ u, (P - c) @ w]
    return _inside(poly2, np.array([(x - c) @ u, (x - c) @ w]))


# ------------------------------------------------------------------------------------------------ checks
def piercings(ring_mol: Mol, ring_xyz: np.ndarray, bond_mol: Mol, bond_xyz: np.ndarray) -> list[dict]:
    out = []
    for ring in ring_mol.rings:
        P = ring_xyz[ring]
        c = P.mean(0)
        rad = float(np.linalg.norm(P - c, axis=1).max())
        for i, j in bond_mol.bonds:
            a, b = bond_xyz[i], bond_xyz[j]
            if np.linalg.norm((a + b) / 2 - c) > rad + 1.5:
                continue
            if bond_pierces_ring(P, a, b):
                out.append({"ring_of": ring_mol.name, "ring_atoms": [int(k) for k in ring], "bond_of": bond_mol.name,
                            "bond": [int(i), int(j)]})
    return out


def overlaps(m1: Mol, x1: np.ndarray, m2: Mol, x2: np.ndarray) -> list[dict]:
    lo, hi = x1.min(0) - 2.3, x1.max(0) + 2.3
    near = np.where(np.all((x2 >= lo) & (x2 <= hi), axis=1))[0]
    if not len(near):
        return []
    d = np.sqrt(((x1[:, None, :] - x2[None, near, :]) ** 2).sum(-1))
    e1 = np.array(m1.elements)[:, None]
    e2 = np.array(m2.elements)[near][None, :]
    h1, h2 = e1 == "H", e2 == "H"
    cut = np.where(h1 & h2, H_H, np.where(h1 | h2, HEAVY_H, HEAVY_HEAVY))
    metal = np.isin(e1, list(METALS)) | np.isin(e2, list(METALS))
    bad = (d < cut) & ~metal
    out = []
    for i, j in zip(*np.where(bad)):
        out.append({"a": m1.name, "i": int(i), "b": m2.name, "j": int(near[j]), "d": round(float(d[i, j]), 2),
                    "depth": round(float(cut[i, j] - d[i, j]), 2)})
    return out


def protein_contacts(lig: Mol, x: np.ndarray, prot: Mol | None) -> int:
    if prot is None:
        return 0
    lh, ph = x[lig.heavy], prot.xyz[prot.heavy]
    lo, hi = lh.min(0) - CONTACT_A, lh.max(0) + CONTACT_A
    ph = ph[np.all((ph >= lo) & (ph <= hi), axis=1)]
    if not len(ph):
        return 0
    return int((np.sqrt(((ph[:, None] - lh[None]) ** 2).sum(-1)) <= CONTACT_A).any(1).sum())


def _min_dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(((a[:, None] - b[None]) ** 2).sum(-1)).min())


def check(ligands: list[Mol], protein: Mol | None) -> dict:
    """Every problem of the assembled complex, per ligand.  Ligand coordinates are taken from `ligand.xyz`."""
    per = {l.name: {"overlaps": [], "piercings": [], "contacts": protein_contacts(l, l.xyz, protein), "floating": False,
                    "partners": set()} for l in ligands}
    env = ([protein] if protein is not None else [])
    for k, l in enumerate(ligands):
        others = env + ligands[k + 1:]
        for o in others:
            ov = overlaps(l, l.xyz, o, o.xyz)
            pc = piercings(l, l.xyz, o, o.xyz) + piercings(o, o.xyz, l, l.xyz)
            if ov or pc:
                per[l.name]["overlaps"] += ov
                per[l.name]["piercings"] += pc
                per[l.name]["partners"].add(o.name)
                if not o.is_protein:
                    per[o.name]["overlaps"] += ov
                    per[o.name]["piercings"] += pc
                    per[o.name]["partners"].add(l.name)
    for l in ligands:
        near_lig = any(_min_dist(l.xyz[l.heavy], o.xyz[o.heavy]) <= FLOAT_LL for o in ligands if o is not l)
        per[l.name]["floating"] = protein is not None and per[l.name]["contacts"] < FLOAT_CONTACTS and not near_lig
    for v in per.values():
        v["partners"] = sorted(v["partners"])
        v["ok"] = not v["overlaps"] and not v["piercings"] and not v["floating"]
    return per


# ------------------------------------------------------------------------------------------------ repair
def _rotations(rng, n: int, max_deg: float) -> np.ndarray:
    axes = rng.normal(size=(n, 3)); axes /= np.linalg.norm(axes, axis=1, keepdims=True)
    ang = np.radians(rng.uniform(0, max_deg, n))
    K = np.zeros((n, 3, 3))
    K[:, 0, 1], K[:, 0, 2], K[:, 1, 2] = -axes[:, 2], axes[:, 1], -axes[:, 0]
    K = K - K.transpose(0, 2, 1)
    s, c = np.sin(ang)[:, None, None], np.cos(ang)[:, None, None]
    return np.eye(3)[None] + s * K + (1 - c) * (K @ K)


def relieve(lig: Mol, env: list[Mol], protein: Mol | None, *, n_trials: int = 6000, seed: int = 2026) -> dict | None:
    """Smallest rigid move of `lig` that clears all its overlaps and piercings against `env` (same binding mode).
    Returns {"xyz", "rmsd", "rotation_deg", "shift_A"} or None."""
    rng = np.random.default_rng(seed)
    x0 = lig.xyz
    c0 = x0.mean(0)
    base_contacts = protein_contacts(lig, x0, protein)
    R = _rotations(rng, n_trials, MAX_ROT_DEG)
    T = rng.normal(size=(n_trials, 3)); T *= (rng.uniform(0, MAX_SHIFT_A, n_trials) / np.linalg.norm(T, axis=1))[:, None]
    cand = np.einsum("kij,nj->kni", R, x0 - c0) + c0 + T[:, None, :]
    rmsd = np.sqrt(((cand - x0[None]) ** 2).sum(-1).mean(1))
    order = np.argsort(rmsd)
    env_xyz = np.vstack([m.xyz for m in env]) if env else np.zeros((0, 3))
    env_el = np.array(sum((m.elements for m in env), [])) if env else np.array([])
    lo, hi = x0.min(0) - MAX_SHIFT_A - 6, x0.max(0) + MAX_SHIFT_A + 6
    keep = np.all((env_xyz >= lo) & (env_xyz <= hi), axis=1) if len(env_xyz) else np.zeros(0, bool)
    ex, ee = env_xyz[keep], env_el[keep]
    lel = np.array(lig.elements)
    h1, h2 = (lel == "H")[:, None], (ee == "H")[None, :]
    cut = np.where(h1 & h2, H_H, np.where(h1 | h2, HEAVY_H, HEAVY_HEAVY))
    metal = np.isin(lel, list(METALS))[:, None] | np.isin(ee, list(METALS))[None, :]
    cut = np.where(metal, 0.0, cut)
    for start in range(0, n_trials, 300):
        idx = order[start:start + 300]
        idx = idx[rmsd[idx] <= MAX_NUDGE_RMSD]
        if not len(idx):
            return None
        if len(ex):
            d = np.sqrt(((cand[idx][:, :, None, :] - ex[None, None]) ** 2).sum(-1))
            clean = ~((d < cut[None]).any((1, 2)))
        else:
            clean = np.ones(len(idx), bool)
        for k in idx[clean]:
            x = cand[k]
            if protein is not None and protein_contacts(lig, x, protein) < KEEP_CONTACTS * base_contacts:
                continue
            if any(piercings(lig, x, o, o.xyz) or piercings(o, o.xyz, lig, x) for o in env):
                continue
            ang = float(np.degrees(np.arccos(np.clip((np.trace(R[k]) - 1) / 2, -1, 1))))
            return {"xyz": x, "rmsd": round(float(rmsd[k]), 2), "rotation_deg": round(ang, 1),
                    "shift_A": round(float(np.linalg.norm(T[k])), 2)}
    return None


def culprit(per: dict) -> str | None:
    bad = {n: v for n, v in per.items() if not v["ok"]}
    if not bad:
        return None
    return sorted(bad, key=lambda n: (-(len(bad[n]["piercings"]) * 10 + len(bad[n]["overlaps"]) + 5 * bad[n]["floating"]),
                                      bad[n]["contacts"], n))[0]


def resolve(ligands: list[Mol], protein: Mol | None, *, exclude: list[str] = (), accept: bool = False,
            pose_entry: str = "joint") -> dict:
    """Check → nudge each problem ligand (worst first) → re-check.  Returns
    {"status": PASS|AUTO_FIXED|NEEDS_HUMAN, "per_ligand", "adjusted": {name: {xyz, rmsd, …}}, "excluded": [...],
     "culprit", "why": (zh, en), "options": [...]}.  `exclude` / `accept` are the human decisions."""
    work = [Mol(l.name, l.elements, l.xyz.copy(), l.bonds, False, l.rings) for l in ligands if l.name not in exclude]
    excluded = [n for n in exclude if any(l.name == n for l in ligands)]
    adjusted: dict = {}
    auto_excluded = []
    per = check(work, protein)
    # a floating ligand is not bound in this pose: dropping it from the co-occupancy system is the only sensible move
    for n, v in list(per.items()):
        if v["floating"] and not v["overlaps"] and not v["piercings"] and len(work) > 1:
            auto_excluded.append(n)
    if auto_excluded:
        work = [l for l in work if l.name not in auto_excluded]
        per = check(work, protein)
    for _round in range(len(work)):
        bad = culprit(per)
        if bad is None:
            break
        lig = next(l for l in work if l.name == bad)
        env = ([protein] if protein is not None else []) + [l for l in work if l is not lig]
        fix = relieve(lig, env, protein)
        if fix is None:
            break
        lig.xyz = fix.pop("xyz")
        adjusted[bad] = {**fix, "xyz": lig.xyz}
        per = check(work, protein)
    remaining = culprit(per)
    excluded_all = excluded + auto_excluded
    info = {"per_ligand": per, "adjusted": adjusted, "excluded": excluded_all, "auto_excluded": auto_excluded,
            "culprit": remaining, "ligands": [l.name for l in work]}
    if remaining is None:
        status = "AUTO_FIXED" if (adjusted or auto_excluded) else "PASS"
        parts_zh, parts_en = [], []
        for n, a in adjusted.items():
            parts_zh.append(f"{n} 以剛體微調（旋轉 {a['rotation_deg']}°、平移 {a['shift_A']} Å，RMSD {a['rmsd']} Å ≤ {MAX_NUDGE_RMSD} Å，結合模式不變）消除重疊或穿環")
            parts_en.append(f"{n} nudged as a rigid body (rotation {a['rotation_deg']}°, shift {a['shift_A']} Å, RMSD {a['rmsd']} Å ≤ "
                            f"{MAX_NUDGE_RMSD} Å, same binding mode) to clear overlaps or ring piercing")
        for n in auto_excluded:
            parts_zh.append(f"{n} 在此姿勢未與蛋白或其他配體接觸（漂浮），自多配體系統排除")
            parts_en.append(f"{n} touches neither the protein nor another ligand in this pose (floating) and was removed from the multi-ligand system")
        for n in excluded:
            parts_zh.append(f"{n} 依使用者決定排除"); parts_en.append(f"{n} excluded by the user")
        info.update(status=status, why=("；".join(parts_zh) or "所有配體無重疊、無穿環，且都與蛋白接觸。",
                                         "; ".join(parts_en) or "No overlaps, no ring piercing, every ligand touches the protein."), options=[])
        return info
    v = per[remaining]
    kinds_zh, kinds_en = [], []
    if v["piercings"]:
        kinds_zh.append(f"{len(v['piercings'])} 處穿環"); kinds_en.append(f"{len(v['piercings'])} ring piercing(s)")
    if v["overlaps"]:
        kinds_zh.append(f"{len(v['overlaps'])} 對原子重疊（最近 {min(o['d'] for o in v['overlaps'])} Å）")
        kinds_en.append(f"{len(v['overlaps'])} overlapping atom pair(s) (closest {min(o['d'] for o in v['overlaps'])} Å)")
    if v["floating"]:
        kinds_zh.append("未與蛋白接觸"); kinds_en.append("no contact with the protein")
    with_ = "、".join(v["partners"]) or "—"
    if len(work) == 1:
        rec_zh = f"建議改選 {remaining} 的其他姿勢（與蛋白接觸 {v['contacts']} 個重原子）。"
        rec_en = f"Recommended: choose another pose for {remaining} ({v['contacts']} protein contacts)."
    else:
        rec_zh = (f"建議排除 {remaining}（它牽涉的問題最多，且與蛋白接觸 {v['contacts']} 個重原子，是較不可信的姿勢），或改選其他聯合姿勢。")
        rec_en = (f"Recommended: exclude {remaining} (involved in the most problems, {v['contacts']} protein contacts, the less "
                  "credible pose) or choose another joint pose.")
    info.update(status="ACCEPTED" if accept else "NEEDS_HUMAN",
                why=(f"{remaining} 與 {with_} 之間 {'、'.join(kinds_zh)}，在 {MAX_NUDGE_RMSD} Å 內的剛體微調無法消除；"
                     f"這種構型進入能量最小化會被硬推開或卡死（穿環無法自行解開）。" + rec_zh,
                     f"{remaining} has {', '.join(kinds_en)} with {', '.join(v['partners']) or '—'} that a rigid nudge within "
                     f"{MAX_NUDGE_RMSD} Å cannot remove; minimisation would either blast the atoms apart or stay locked (a pierced "
                     f"ring does not untangle by itself). " + rec_en),
                options=([f"multi_ligand.exclude: [{remaining}]（建議）"] if len(work) > 1 else [])
                + [f"pose_choices: {pose_entry}=<其他名次>", "multi_ligand.accept_geometry: true（不建議：照原樣進入 MD）"])
    return info


# ------------------------------------------------------------------------------------------------ file readers
def mol_from_sdf(path, name: str) -> Mol:
    lines = open(path, encoding="utf-8", errors="ignore").read().splitlines()
    na, nb = int(lines[3][:3]), int(lines[3][3:6])
    el, xyz, bonds = [], [], []
    for l in lines[4:4 + na]:
        p = l.split()
        xyz.append([float(p[0]), float(p[1]), float(p[2])]); el.append(p[3])
    for l in lines[4 + na:4 + na + nb]:
        a, b = int(l[:3]) - 1, int(l[3:6]) - 1
        bonds.append((min(a, b), max(a, b)))
    return Mol(name, el, np.array(xyz), bonds)


def write_sdf_coords(src, dst, xyz: np.ndarray, note: str = "") -> None:
    lines = open(src, encoding="utf-8", errors="ignore").read().splitlines()
    na = int(lines[3][:3])
    for k in range(na):
        l = lines[4 + k]
        lines[4 + k] = f"{xyz[k, 0]:10.4f}{xyz[k, 1]:10.4f}{xyz[k, 2]:10.4f}" + l[30:]
    if note:
        lines[1] = (lines[1] + " " + note)[:80]
    open(dst, "w", encoding="utf-8").write("\n".join(lines) + "\n")


def protein_near(pdb_path, around: np.ndarray, radius: float = 10.0) -> Mol | None:
    """Protein residues with any atom within `radius` Å of `around` (whole residues, so rings stay intact)."""
    rows = []
    for l in open(pdb_path, encoding="utf-8", errors="ignore").read().splitlines():
        if l.startswith(("ATOM", "HETATM")) and l[17:20].strip() not in {"HOH", "WAT"}:
            try:
                x = (float(l[30:38]), float(l[38:46]), float(l[46:54]))
            except ValueError:
                continue
            el = (l[76:78].strip() or l[12:16].strip()[:1]).upper()
            rows.append((f"{l[21]}{l[22:27]}", el, x))
    if not rows:
        return None
    X = np.array([r[2] for r in rows])
    lo, hi = around.min(0) - radius, around.max(0) + radius
    hit = np.all((X >= lo) & (X <= hi), axis=1)
    keep_res = {rows[i][0] for i in np.where(hit)[0]}
    idx = [i for i, r in enumerate(rows) if r[0] in keep_res]
    if not idx:
        return None
    return Mol("protein", [rows[i][1] for i in idx], X[idx], is_protein=True)


STANDARD = {"ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE", "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR",
            "TRP", "TYR", "VAL", "HID", "HIE", "HIP", "CYX", "ASH", "GLH", "LYN", "ACE", "NME", "NMA", "HOH", "WAT", "NA", "CL", "K",
            "MG", "CA", "ZN", "LI", "RB", "CS", "BR", "F", "I", "MN", "FE", "CU", "CO", "NI", "CD", "HG", "SOL"}


def piercings_in_pdb(pdb_path) -> list[dict]:
    """D-60: ring piercing involving a ligand in a written structure (e.g. after minimisation, when overlaps are gone
    but a threaded bond stays locked).  Ligand = any residue that is not standard protein, water or ion."""
    by_res: dict = {}
    for l in open(pdb_path, encoding="utf-8", errors="ignore").read().splitlines():
        if not l.startswith(("ATOM", "HETATM")):
            continue
        try:
            x = (float(l[30:38]), float(l[38:46]), float(l[46:54]))
        except ValueError:
            continue
        rn = l[17:20].strip()
        key = (l[21], l[22:27], rn)
        el = (l[76:78].strip() or l[12:16].strip()[:1]).upper()
        by_res.setdefault(key, []).append((el, x))
    ligs = {k: v for k, v in by_res.items() if k[2] not in STANDARD}
    if not ligs:
        return []
    lig_mols = [Mol(f"{k[2]}{k[1].strip()}", [a[0] for a in v], np.array([a[1] for a in v])) for k, v in ligs.items()]
    around = np.vstack([m.xyz for m in lig_mols])
    lo, hi = around.min(0) - 8, around.max(0) + 8
    prot_res = [v for k, v in by_res.items() if k[2] in STANDARD and k[2] not in {"HOH", "WAT", "SOL"}
                and any(np.all((np.array(x) >= lo) & (np.array(x) <= hi)) for _, x in v)]
    out = []
    for m in lig_mols:
        for o in lig_mols:
            if o is not m:
                out += piercings(m, m.xyz, o, o.xyz)
    for v in prot_res:                     # per residue: rings and bonds stay inside one residue (aromatic side chains, Pro)
        r = Mol("protein", [a[0] for a in v], np.array([a[1] for a in v]), is_protein=True)
        for m in lig_mols:
            out += piercings(m, m.xyz, r, r.xyz) + piercings(r, r.xyz, m, m.xyz)
    return out
