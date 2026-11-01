"""Metal sites: enforce `metal_policy` in the build, including a crystal-geometry *bonded* model.

Policies (per element "ZN" or per site "ZN:A301"; site key wins):
  remove          drop the metal from the receptor (only if it is not functionally needed — user's call)
  keep_nonbonded  keep it as a nonbonded ion (Amber/Li–Merz 12-6) + a weak position restraint that stays on
                  during production, so the ion cannot wander off its site; the report says so
  bonded          keep it and add a *geometric bonded model*:
                    • harmonic metal–donor bonds at the crystal distances,
                    • harmonic donor–metal–donor angles at the crystal angles,
                    • metal–donor 1-2 pairs excluded from nonbonded (otherwise +2 e electrostatics collapse the bonds),
                    • coordinating residues set to the deprotonated/tautomer state the coordination implies
                      (Cys SG → CYM; His NE2 → HID; His ND1 → HIE).
                  This is NOT a fitted MCPB.py/ZAFF model: charges stay those of the force field.  It keeps the
                  site geometry (what a docking/MD teaching run needs) and is labelled as such in the report.

No policy → the force field's nonbonded ion, unchanged (pocket transition metals never get here without a
policy: the WP6 structure gate stops them first).
Gates (pure logic, `plan_site`): fewer than 3 protein donors, a docked/other ligand among the donors, a
His coordinating through both nitrogens, or an unsupported metal → NEEDS_HUMAN (never guess a coordination).
Coordinating waters are listed but not bonded (receptor waters are removed; the open site is a caveat).
"""
from __future__ import annotations

import math

import numpy as np

from .gates import Gate, PASS, AUTO_FIXED, NEEDS_HUMAN

BONDED_METALS = {"ZN", "FE", "FE2", "CU", "CU1", "MN", "CO", "NI", "MG", "CA", "CD"}
# donor atoms (resname, atom) and the cutoff (Å) at which they count as coordinating
DONORS = {("HIS", "NE2"): "N", ("HIS", "ND1"): "N", ("CYS", "SG"): "S", ("ASP", "OD1"): "O", ("ASP", "OD2"): "O",
          ("GLU", "OE1"): "O", ("GLU", "OE2"): "O", ("MET", "SD"): "S", ("ASN", "OD1"): "O", ("GLN", "OE1"): "O",
          ("SER", "OG"): "O", ("THR", "OG1"): "O", ("TYR", "OH"): "O"}
HIS_NAMES = {"HIS", "HID", "HIE", "HIP"}
CYS_NAMES = {"CYS", "CYM", "CYX"}
CUTOFF_A = {"N": 2.45, "O": 2.6, "S": 2.6}
WATER = {"HOH", "WAT", "TIP3", "SOL"}
K_BOND = 2 * 46.0 * 4.184 * 100      # ZAFF-like Zn–N 46 kcal/mol/Å² → OpenMM ½k(r−r0)² in kJ/mol/nm²
K_ANGLE = 2 * 25.0 * 4.184           # 25 kcal/mol/rad² → kJ/mol/rad²
K_KEEP = 1000.0                      # kJ/mol/nm² position restraint for keep_nonbonded
K_ANGLE_MDX = 2 * 50.0 * 4.184       # metal–donor–neighbour angle (ZAFF/MCPB-like ~50 kcal/mol/rad²)
SCEE, SCNB = 1.2, 2.0                # Amber 1-4 scaling (electrostatics, LJ)


def policy_for(key: str, policy: dict | None) -> str | None:
    p = policy or {}
    return p.get(key) or p.get(key.split(":")[0])


def _base(resname: str) -> str:
    r = resname.upper()
    return "HIS" if r in HIS_NAMES else "CYS" if r in CYS_NAMES else "ASP" if r in {"ASP", "ASH"} else \
        "GLU" if r in {"GLU", "GLH"} else r


def find_sites(atoms: list[dict], *, metals: set[str] | None = None) -> list[dict]:
    """atoms: [{index, name, resname, chain, resseq, xyz (Å), element, is_protein}] → one site per metal atom."""
    metals = metals or BONDED_METALS
    xyz = np.array([a["xyz"] for a in atoms], dtype=float) if atoms else np.zeros((0, 3))
    sites = []
    for m in atoms:
        if m["resname"].upper() not in metals or m.get("is_protein"):
            continue
        d = np.linalg.norm(xyz - np.asarray(m["xyz"]), axis=1)
        donors, waters, foreign = [], [], []
        for j in np.where((d > 0.5) & (d < 3.0))[0]:
            a = atoms[int(j)]
            el = (a.get("element") or a["name"][:1]).upper()[:1]
            if a["resname"].upper() in WATER:
                if el == "O" and d[j] <= CUTOFF_A["O"]:
                    waters.append({"resname": a["resname"], "chain": a["chain"], "resseq": a["resseq"], "distance_A": round(float(d[j]), 2)})
                continue
            if el not in CUTOFF_A or d[j] > CUTOFF_A[el]:
                continue
            rec = {"index": a["index"], "name": a["name"], "resname": a["resname"], "chain": a["chain"],
                   "resseq": a["resseq"], "element": el, "distance_A": round(float(d[j]), 2)}
            if a.get("is_protein") and (_base(a["resname"]), a["name"]) in DONORS:
                donors.append(rec)
            elif not a.get("is_protein"):
                foreign.append(rec)
        sites.append({"key": f"{m['resname'].upper()}:{m['chain']}{m['resseq']}", "metal_index": m["index"],
                      "metal_xyz": list(map(float, m["xyz"])), "donors": donors, "waters": waters, "foreign": foreign})
    return sites


def _angle(a, m, b) -> float:
    u, v = np.asarray(a) - np.asarray(m), np.asarray(b) - np.asarray(m)
    c = float(np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v)))
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def plan_site(site: dict, policy: str | None, xyz_of: dict | None = None, params: dict | None = None,
              residue_atoms: dict | None = None) -> dict:
    """Decide what to do with one metal site → {status, action, bonds, angles, variants, gate, why}.

    `params` (metal_params spec for this site) replaces the crystal-geometry constants with fitted ones
    (see metal_params.py); it is only resolved when `xyz_of` is given (final pass on the edited topology)."""
    key = site["key"]
    out = {"key": key, "metal_index": site["metal_index"], "policy": policy, "action": None, "bonds": [], "angles": [],
           "variants": {}, "caveats": [], "charges": {}, "source": "geometric"}
    if policy is None:
        # pocket transition metals were already stopped by the structure gate (WP6); anything reaching here
        # without a policy keeps the pre-existing behaviour, stated explicitly
        out.update(status=PASS, action="default_nonbonded",
                   why=f"{key} 未設定 metal_policy：以力場的非鍵結離子保留（不加限制、不建鍵）。")
        return out
    if policy == "remove":
        out.update(status=AUTO_FIXED, action="remove", why=f"{key} 依使用者設定移除（使用者確認非功能必要）。")
        return out
    if policy == "keep_nonbonded":
        out.update(status=AUTO_FIXED, action="keep_nonbonded",
                   why=f"{key} 以非鍵結離子保留，並加 {K_KEEP:.0f} kJ/mol/nm² 位置限制（production 也不解除），避免離子離開位點；"
                       "配位幾何不保證，報告標註。")
        return out
    if policy != "bonded":
        out.update(status=NEEDS_HUMAN, why=f"{key}：未知的 metal_policy「{policy}」（可用 bonded / keep_nonbonded / remove）。")
        return out
    donors = site["donors"]
    problems = []
    if site["foreign"]:
        problems.append("配位原子包含非蛋白分子（" + "、".join(f"{f['resname']}{f['resseq']}:{f['name']}" for f in site["foreign"])
                        + "）；配體–金屬鍵需要專門參數化（MCPB.py/QM），不自動建")
    his_both = {(d["chain"], d["resseq"]) for d in donors if _base(d["resname"]) == "HIS" and d["name"] == "ND1"} & \
               {(d["chain"], d["resseq"]) for d in donors if _base(d["resname"]) == "HIS" and d["name"] == "NE2"}
    if his_both:
        problems.append(f"His {sorted(his_both)} 兩個氮同時配位，幾何不合理（請檢查結構）")
    if len(donors) < 3:
        problems.append(f"只有 {len(donors)} 個蛋白配位原子（< 3）；位點不完整或解析度不足，鍵結模型會扭曲")
    if problems:
        out.update(status=NEEDS_HUMAN, why=f"{key} 無法建立鍵結模型：" + "；".join(problems) + "。",
                   options=["改用 keep_nonbonded（報告標註）", "以 MCPB.py/QM 參數化後匯入", "remove（若非必要）"])
        return out
    variants = {}
    for d in donors:
        b = _base(d["resname"])
        rid = f"{d['chain']}:{d['resseq']}"
        if b == "CYS":
            variants[rid] = "CYM"
        elif b == "HIS":
            variants[rid] = "HID" if d["name"] == "NE2" else "HIE"
    bonds = [{"metal": site["metal_index"], "donor": d["index"], "r0_nm": round(d["distance_A"] / 10.0, 4), "k": K_BOND,
              "label": f"{d['resname']}{d['resseq']}:{d['name']}"} for d in donors]
    angles = []
    if xyz_of:
        mx = site["metal_xyz"]
        for i in range(len(donors)):
            for j in range(i + 1, len(donors)):
                a, b = donors[i], donors[j]
                angles.append({"a": a["index"], "metal": site["metal_index"], "b": b["index"],
                               "theta0_deg": round(_angle(xyz_of[a["index"]], mx, xyz_of[b["index"]]), 2), "k": K_ANGLE})
    geom = {4: "四配位", 5: "五配位", 6: "六配位"}.get(len(donors), f"{len(donors)} 配位")
    caveats = ["鍵結模型為晶體幾何的諧和鍵與角（非擬合的 MCPB.py/ZAFF 參數）；電荷沿用力場。金屬被當成與配位原子共價相連："
               "1-2、1-3 非鍵結作用排除、1-4 依 Amber 縮放（靜電 ÷1.2、LJ ÷2），並加金屬–配位原子–鄰原子角項固定環的朝向。"]
    fitted = ""
    if params and xyz_of:
        from .metal_params import resolve_site_params
        fp = resolve_site_params(site, params, xyz_of, residue_atoms=residue_atoms)
        if fp["status"] == NEEDS_HUMAN:
            out.update(status=NEEDS_HUMAN, why=f"{key}：{fp['why']}", options=fp.get("options") or [],
                       evidence=fp.get("evidence", {}))
            return out
        for b in bonds:
            b.update(r0_nm=round(fp["bonds"][b["donor"]]["r0_nm"], 4), k=fp["bonds"][b["donor"]]["k"],
                     k_kcal_A2=round(fp["bonds"][b["donor"]]["k_kcal_A2"], 1))
        for a in angles:
            rec = fp["angles"].get((a["a"], a["b"])) or fp["angles"].get((a["b"], a["a"]))
            a.update(theta0_deg=round(rec["theta0_deg"], 2), k=rec["k"], k_kcal_rad2=round(rec["k_kcal_rad2"], 1))
        out["charges"] = {str(i): q for i, q in fp["charges"].items()}
        out["source"] = fp["source"]
        out["evidence"] = fp.get("evidence", {})
        caveats = list(fp.get("caveats", []))
        fitted = "（擬合參數：" + fp["why"] + "）"
    elif params and not xyz_of:
        out["source"] = "pending"            # resolved on the final pass
    if site["waters"]:
        caveats.append(f"晶體中有 {len(site['waters'])} 個配位水；受體準備已移除水分子，該配位位置開放（可能由溶劑水或配體佔據）。")
    out.update(status=AUTO_FIXED, action="bonded", bonds=bonds, angles=angles, variants=variants, caveats=caveats,
               why=f"{key} 依使用者設定建立鍵結模型：{geom}（" + "、".join(b["label"] + f" {b['r0_nm'] * 10:.2f} Å" for b in bonds)
                   + "）" + (f"；配位殘基質子化改為 " + "、".join(f"{k}→{v}" for k, v in variants.items()) if variants else "")
                   + "（配位的 Cys 去質子化、His 以未配位的氮帶氫）。" + fitted)
    return out


def site_gates(plans: list[dict]) -> list[Gate]:
    return [Gate(f"metal {p['key']}", p["status"], p["why"], options=p.get("options") or [],
                 evidence={"action": p["action"], "n_bonds": len(p["bonds"]), "variants": p["variants"],
                           "source": p.get("source", "geometric"), **(p.get("evidence") or {})}) for p in plans]


def residue_variant(resname: str, atom_names: set[str]) -> str | None:
    """Current protonation variant of a titratable residue from its hydrogens (for Modeller.addHydrogens)."""
    b = _base(resname)
    if b == "HIS":
        hd, he = "HD1" in atom_names, "HE2" in atom_names
        return "HIP" if hd and he else "HID" if hd else "HIE" if he else None
    if b == "CYS":
        # PDBFixer protonates free Cys at physiological pH; a Cys without HG that is not a metal donor is a disulfide
        return "CYS" if "HG" in atom_names else "CYX"
    if b == "ASP":
        return "ASH" if "HD2" in atom_names else "ASP"
    if b == "GLU":
        return "GLH" if "HE2" in atom_names else "GLU"
    if b == "LYS":
        return "LYS" if "HZ3" in atom_names else "LYN"
    return None


# ---------------------------------------------------------------------------------------------- OpenMM side
def _atoms_of(topology, positions_nm) -> list[dict]:
    prot = {"ALA", "ARG", "ASN", "ASP", "ASH", "CYS", "CYM", "CYX", "GLN", "GLU", "GLH", "GLY", "HIS", "HID", "HIE", "HIP",
            "ILE", "LEU", "LYS", "LYN", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL", "ACE", "NME"}
    out = []
    for a in topology.atoms():
        p = positions_nm[a.index]
        out.append({"index": a.index, "name": a.name, "resname": a.residue.name, "chain": a.residue.chain.id,
                    "resseq": a.residue.id, "element": a.element.symbol if a.element is not None else "",
                    "is_protein": a.residue.name.upper() in prot, "xyz": [10 * float(p[0]), 10 * float(p[1]), 10 * float(p[2])]})
    return out


def apply_metal_policy(modeller, forcefield, policy: dict | None, *, ph: float = 7.4,
                       metal_params: dict | None = None, qm_dir=None) -> list[dict]:
    """Edit the receptor Modeller in place (remove metals / reprotonate coordinating residues) and return the
    final per-site plans with indices valid for the edited topology (ligands/solvent are appended later,
    so receptor indices stay valid in the assembled system)."""
    import numpy as np  # noqa: F811
    from openmm import unit

    def snapshot():
        pos = np.asarray(modeller.positions.value_in_unit(unit.nanometer))
        atoms = _atoms_of(modeller.topology, pos)
        sites = find_sites(atoms)
        return atoms, sites

    atoms, sites = snapshot()
    if not sites:
        return []
    plans = [plan_site(s, policy_for(s["key"], policy)) for s in sites]
    if any(p["status"] == NEEDS_HUMAN for p in plans):
        return plans
    # 1) removals
    rm = {sites[i]["metal_index"] for i, p in enumerate(plans) if p["action"] == "remove"}
    if rm:
        modeller.delete([a for a in modeller.topology.atoms() if a.index in rm])
    # 2) reprotonation of coordinating residues (delete their H, re-add with explicit variants everywhere)
    want = {k: v for p in plans if p["action"] == "bonded" for k, v in p["variants"].items()}
    if want:
        res_of = {f"{r.chain.id}:{r.id}": r for r in modeller.topology.residues()}
        modeller.delete([a for k in want if k in res_of for a in res_of[k].atoms()
                         if a.element is not None and a.element.symbol == "H"])
        variants = []
        for r in modeller.topology.residues():
            k = f"{r.chain.id}:{r.id}"
            variants.append(want.get(k) or residue_variant(r.name, {a.name for a in r.atoms()}))
        modeller.addHydrogens(forcefield, pH=ph, variants=variants)
    # 3) final plans on the edited topology (indices + angles)
    atoms, sites = snapshot()
    xyz_of = {a["index"]: a["xyz"] for a in atoms}
    residue_atoms = {}
    for r in modeller.topology.residues():
        residue_atoms[f"{r.chain.id}:{r.id}"] = {a.name: a.index for a in r.atoms()}
    final = [plan_site(s, policy_for(s["key"], policy), xyz_of, params=policy_for(s["key"], metal_params),
                       residue_atoms=residue_atoms) for s in sites]
    for p in final:
        if p["action"] == "bonded":
            p["variants"] = {k: v for k, v in want.items() if k in p["variants"]} or p["variants"]
    # geometric bonded sites: write the QM small-model input so the student can upgrade to fitted parameters
    if qm_dir is not None:
        from pathlib import Path as _P
        from .metal_params import write_qm_cluster
        for s_, p in zip(sites, final):
            if p["action"] != "bonded" or p.get("source") != "geometric":
                continue
            spec = policy_for(s_["key"], metal_params) or {}
            qm = write_qm_cluster(atoms, s_, _P(qm_dir) / s_["key"].replace(":", "_"),
                                  charge=spec.get("qm_charge"), multiplicity=spec.get("qm_multiplicity"))
            p["qm_input"] = qm
            if qm["status"] == "PASS":
                p["caveats"].append(f"可升級：QM 小模型輸入已寫到 {_P(qm_dir) / s_['key'].replace(':', '_')}（見 README.md）。")
            else:
                p["caveats"].append("未產生 QM 小模型輸入：" + qm["why"])
    return final


def bonded_metal_terms(bonds: list[tuple[int, int]], plans: list[dict], positions_nm) -> dict:
    """Topology terms that make a metal behave as covalently bound to its donors (pure Python).

    Treating M–D as a bond means, exactly as for any bonded pair in Amber: M–D (1-2) and M–X with X bonded to D
    (1-3) have no nonbonded interaction, M–Y with Y two bonds from D (1-4) is scaled, and the M–D–X angles keep
    the donor group pointing at the metal.  Without 1-3 exclusion the +2 metal sits ~3 Å from the donor's
    neighbours (e.g. His CE1/CD2 and their hydrogens) and is pushed off its site (CI: Zn–NE2 2.03 → 2.56 Å).
    Returns {"excl13": [(m, x)], "pairs14": [(m, y)], "angles": [(m, d, x, θ0 rad)]} with no duplicates."""
    import numpy as np  # noqa: F811
    nbr: dict[int, set[int]] = {}
    for a, b in bonds:
        nbr.setdefault(a, set()).add(b); nbr.setdefault(b, set()).add(a)
    pos = np.asarray(positions_nm, float)
    excl12, excl13, pairs14, angles = set(), set(), set(), []
    for p in plans:
        if p.get("action") != "bonded":
            continue
        m = p["metal_index"]
        donors = {b["donor"] for b in p["bonds"]}
        excl12 |= {(m, d) for d in donors}
        for d in donors:
            for x in nbr.get(d, ()):
                if x == m or x in donors:
                    continue
                excl13.add((m, x))
                u, v = pos[m] - pos[d], pos[x] - pos[d]
                th = float(np.arccos(np.clip(np.dot(u, v) / np.linalg.norm(u) / np.linalg.norm(v), -1.0, 1.0)))
                angles.append((m, d, x, th))
                for y in nbr.get(x, ()):
                    if y not in (d, m) and y not in donors:
                        pairs14.add((m, y))
    excl13 -= excl12
    pairs14 -= excl12 | excl13
    return {"excl13": sorted(excl13), "pairs14": sorted(pairs14), "angles": angles}


def add_metal_forces(system, plans: list[dict], positions_nm, topology=None) -> dict:
    """Bonded model forces + exclusions, and always-on restraints for keep_nonbonded metals.
    `topology` (OpenMM) supplies the covalent bonds for the 1-3 / 1-4 treatment (bonded_metal_terms)."""
    import openmm as mm
    import numpy as np  # noqa: F811
    info = {"bonds": 0, "angles": 0, "exclusions": 0, "restrained_metals": [], "charges_set": 0, "charge_problems": []}
    bonded = [p for p in plans if p["action"] == "bonded"]
    if bonded:
        hb, ha = mm.HarmonicBondForce(), mm.HarmonicAngleForce()
        hb.setName("msw_metal_bonds"); ha.setName("msw_metal_angles")
        nb = [f for f in system.getForces() if isinstance(f, mm.NonbondedForce)]
        cnb = [f for f in system.getForces() if isinstance(f, mm.CustomNonbondedForce)]
        for p in bonded:
            if p.get("charges"):
                # imported (RESP) charges: same integer total as the force field, else refuse (checked here because
                # the System only exists now); exceptions 1-4 pairs keep their own chargeProd, as Amber does
                idx = {int(k): float(v) for k, v in p["charges"].items()}
                for f in nb:
                    old = sum(f.getParticleParameters(i)[0]._value for i in idx)
                    new = sum(idx.values())
                    if abs(round(new) - round(old)) > 0.5 or abs(new - round(new)) > 0.02:
                        info["charge_problems"].append((p["key"], f"{p['key']}：匯入電荷總和 {new:+.3f} 與力場 {old:+.3f} 的整數不同，未套用"))
                        continue
                    for i, q in idx.items():
                        _, sig, eps = f.getParticleParameters(i)
                        f.setParticleParameters(i, q, sig, eps); info["charges_set"] += 1
            for b in p["bonds"]:
                hb.addBond(b["metal"], b["donor"], b["r0_nm"], b["k"]); info["bonds"] += 1
                for f in nb:
                    f.addException(b["metal"], b["donor"], 0.0, 0.1, 0.0, True); info["exclusions"] += 1
                for f in cnb:
                    try:
                        f.addExclusion(b["metal"], b["donor"])
                    except Exception:  # noqa: BLE001  (already excluded)
                        pass
            for a in p["angles"]:
                ha.addAngle(a["a"], a["metal"], a["b"], math.radians(a["theta0_deg"]), a["k"]); info["angles"] += 1
        if topology is not None:
            terms = bonded_metal_terms([(b[0].index, b[1].index) for b in topology.bonds()], bonded, positions_nm)
            for m, x in terms["excl13"]:
                for f in nb:
                    f.addException(m, x, 0.0, 0.1, 0.0, True)
                for f in cnb:
                    try:
                        f.addExclusion(m, x)
                    except Exception:  # noqa: BLE001
                        pass
            for m, y in terms["pairs14"]:
                for f in nb:
                    qm, sm, em = f.getParticleParameters(m)
                    qy, sy, ey = f.getParticleParameters(y)
                    f.addException(m, y, qm * qy / SCEE, (sm + sy) / 2, (em * ey) ** 0.5 / SCNB, True)
                for f in cnb:
                    try:
                        f.addExclusion(m, y)
                    except Exception:  # noqa: BLE001
                        pass
            for m, d, x, th in terms["angles"]:
                ha.addAngle(m, d, x, th, K_ANGLE_MDX)
            info.update(exclusions_13=len(terms["excl13"]), scaled_14=len(terms["pairs14"]), angles_mdx=len(terms["angles"]))
        system.addForce(hb); system.addForce(ha)
    keep = [p for p in plans if p["action"] == "keep_nonbonded"]
    if keep:
        f = mm.CustomExternalForce("0.5*k_metal*periodicdistance(x,y,z,x0,y0,z0)^2")
        f.addGlobalParameter("k_metal", K_KEEP)
        f.addPerParticleParameter("x0"); f.addPerParticleParameter("y0"); f.addPerParticleParameter("z0")
        f.setName("msw_metal_position_restraints")
        pos = np.asarray(positions_nm)
        for p in keep:
            i = p["metal_index"]
            f.addParticle(i, [float(v) for v in pos[i]])
            info["restrained_metals"].append(p["key"])
        system.addForce(f)
    return info

