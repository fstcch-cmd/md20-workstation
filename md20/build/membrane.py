"""Membrane systems (docs/specs/membrane.md, D-80): orientation, lipid composition, bilayer building, surface placement.

Three system types share one plan and one set of gates:
    protein   a membrane protein embedded in a bilayer (GLUT1 4PYP)
    surface   a peptide or small molecule above one bilayer, starting a set distance above the phosphate plane
    bilayer   lipids, water and ions only

The pure-numpy part (orientation scan, composition, grid placement, surface placement, ion selection, box sizes) runs
anywhere and is unit-tested here.  The OpenMM part (`add_membrane`, `build_bilayer`, `add_headgroup_restraints`) runs
only where OpenMM is installed (CI openmm-stack, the students' laptops).

Builders, chosen by `plan_membrane` and never guessed:
    openmm_addmembrane   one neutral lipid that OpenMM ships a pre-equilibrated patch for, with a solute (A, B)
    openmm_patch_tile    the same lipids without a solute (C): copies of OpenMM's patch, no relaxation needed
    grid                 mixtures and lipids without an OpenMM patch: one z-oriented template per lipid placed on a
                         grid (HTMD membranebuilder style).  Templates come from OpenMM's patches for the seven
                         patch lipids; POPG, cholesterol, cardiolipin and lysyl-PG need templates the user provides
                         (`templates_dir`), otherwise NEEDS_HUMAN.  Unverified on a real engine (CI test is xfail).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .gates import Gate, GateReport, PASS, AUTO_FIXED, NEEDS_HUMAN

MEMBRANE_TYPES = ("protein", "surface", "bilayer")

# --------------------------------------------------------------------------------------------------- lipid table
# apl_nm2 / dpp_nm: experimental area per lipid and head-to-head (phosphate peak) thickness of the fluid phase.  Values
# from Kučerka et al. (PC series), Pan et al. (POPG) and Rappolt/Leftin (POPE) as recalled by the developer: marked
# "to confirm" in docs/specs/membrane.md §3.1 until checked against the papers.  tm_k = main transition temperature.
# patch = OpenMM ships a pre-equilibrated solvated patch (openmm/app/data/<NAME>.pdb, Modeller.addMembrane).
# ff = force-field files that contain a template for the lipid (verified in the OpenMM source, spec §4.2).
LIPIDS: dict[str, dict] = {
    "POPC": dict(charge=0, tm_k=271.0, apl_nm2=0.643, dpp_nm=3.70, patch=True, ff="amber14/lipid17.xml",
                 resnames=("POPC", "POP", "PC", "PA", "OL")),
    "POPE": dict(charge=0, tm_k=298.0, apl_nm2=0.58, dpp_nm=3.95, patch=True, ff="amber14/lipid17.xml",
                 resnames=("POPE", "PE")),
    "DOPC": dict(charge=0, tm_k=256.0, apl_nm2=0.674, dpp_nm=3.67, patch=True, ff="amber14/lipid17.xml",
                 resnames=("DOPC", "DOP")),
    "DPPC": dict(charge=0, tm_k=314.0, apl_nm2=0.631, dpp_nm=3.80, patch=True, ff="amber14/lipid17.xml",
                 resnames=("DPPC", "DPP")),
    "DMPC": dict(charge=0, tm_k=297.0, apl_nm2=0.606, dpp_nm=3.44, patch=True, ff="amber14/lipid17.xml",
                 resnames=("DMPC", "DMP", "MY")),
    "DLPC": dict(charge=0, tm_k=271.0, apl_nm2=0.632, dpp_nm=3.08, patch=True, ff="amber14/lipid17.xml",
                 resnames=("DLPC", "DLP", "LA")),
    "DLPE": dict(charge=0, tm_k=302.0, apl_nm2=0.56, dpp_nm=3.30, patch=True, ff="amber14/lipid17.xml",
                 resnames=("DLPE",)),
    "POPG": dict(charge=-1, tm_k=269.0, apl_nm2=0.661, dpp_nm=3.65, patch=False, ff="amber14/lipid17.xml",
                 resnames=("POPG", "PGR", "PGS")),
    "CHOL": dict(charge=0, tm_k=None, apl_nm2=None, dpp_nm=None, patch=False, ff="amber14/lipid17.xml",
                 resnames=("CHL1", "CHL", "CHOL")),
    # cardiolipin (tetraoleoyl, 2−) and lysyl-PG (1+): only the CHARMM36 files shipped with OpenMM have templates
    # (charmm36.xml: TOCL2; charmm36_2024.xml: TOCL2, DPPGK).  Mixing CHARMM lipids with the Amber protein force field
    # is not allowed, so these stop with NEEDS_HUMAN until a CHARMM36m protein route exists.
    "CL": dict(charge=-2, tm_k=None, apl_nm2=1.30, dpp_nm=None, patch=False, ff=None, charmm="TOCL2",
               resnames=("TOCL2", "TOCL", "CL")),
    "LYSPG": dict(charge=1, tm_k=None, apl_nm2=None, dpp_nm=None, patch=False, ff=None, charmm="DPPGK",
                  resnames=("DPPGK", "LYPG")),
}
ALIASES = {"CHL1": "CHOL", "CHOLESTEROL": "CHOL", "TOCL2": "CL", "TOCL": "CL", "CARDIOLIPIN": "CL",
           "LYS-PG": "LYSPG", "LYSYL-PG": "LYSPG", "DPPGK": "LYSPG", "LPG": "LYSPG"}
OPENMM_PATCH_LIPIDS = tuple(k for k, v in LIPIDS.items() if v["patch"])   # POPC POPE DOPC DPPC DMPC DLPC DLPE

PRESETS: dict[str, dict] = {
    # mammalian plasma membrane, simplest model (spec §3); cholesterol can be added by the user
    "mammalian": {"lipids": {"POPC": 1.0}, "temperature_k": 310.0},
    # E. coli inner-membrane model, the usual 3:1 PE:PG of antimicrobial-peptide MD
    "bacterial": {"lipids": {"POPE": 0.75, "POPG": 0.25}, "temperature_k": 310.0},
    # Gram-positive (S. aureus-like) cytoplasmic membrane: PG, lysyl-PG and cardiolipin; ratio 待確認 (spec §3)
    "gram_positive": {"lipids": {"POPG": 0.55, "LYSPG": 0.35, "CL": 0.10}, "temperature_k": 310.0},
}

DEFAULTS = {"type": "protein", "lipids": "mammalian", "oriented": False, "surface_distance_nm": 1.0,
            "lateral_padding_nm": 1.5, "water_nm": 2.0, "temperature_k": None, "surface_orientation": "as_is",
            "seed": 2026, "templates_dir": None, "size_nm": None}

HEAD_K_KJ_MOL_NM2 = 1000.0     # z restraint on lipid P (and cholesterol O3) during heating and the NPT release
P_TO_EDGE_NM = 0.5             # head groups extend ~0.5 nm beyond the phosphate plane (glycerol, choline)


def canonical_lipid(name: str) -> str | None:
    n = str(name).strip().upper()
    n = ALIASES.get(n, n)
    return n if n in LIPIDS else None


# --------------------------------------------------------------------------------------------------- composition
def _counts_from_fractions(fracs: dict[str, float], n: int) -> dict[str, int]:
    """Largest-remainder rounding: exact total n, each count within 1 of fraction·n."""
    raw = {k: v * n for k, v in fracs.items()}
    out = {k: int(math.floor(v)) for k, v in raw.items()}
    rest = n - sum(out.values())
    for k in sorted(raw, key=lambda k: (raw[k] - out[k], k), reverse=True)[:rest]:
        out[k] += 1
    return out


def resolve_composition(lipids) -> tuple[dict, list[Gate]]:
    """md.membrane.lipids → {"upper": {lipid: fraction}, "lower": {...}, "preset": name|None}.

    Accepts a preset name, a flat {lipid: ratio} (symmetric) or {"upper": {...}, "lower": {...}} (asymmetric).  Ratios
    that do not sum to 1 are normalised (AUTO_FIXED, recorded); unknown lipids, negative or empty ratios stop."""
    gates: list[Gate] = []
    preset = None
    if lipids is None:
        lipids = DEFAULTS["lipids"]
    if isinstance(lipids, str):
        if lipids not in PRESETS:
            gates.append(Gate("membrane composition", NEEDS_HUMAN,
                              f"未知的膜組成預設 {lipids!r}。可用：{', '.join(PRESETS)}，或直接寫脂質比例。",
                              options=[f"md.membrane.lipids: {p}" for p in PRESETS]))
            return {}, gates
        preset = lipids
        lipids = PRESETS[lipids]["lipids"]
    if not isinstance(lipids, dict) or not lipids:
        gates.append(Gate("membrane composition", NEEDS_HUMAN, "md.membrane.lipids 必須是預設名稱或 {脂質: 比例}。",
                          options=[f"md.membrane.lipids: {p}" for p in PRESETS]))
        return {}, gates
    leaflets = {"upper": lipids["upper"], "lower": lipids.get("lower", lipids["upper"])} if "upper" in lipids \
        else {"upper": lipids, "lower": lipids}
    out = {"preset": preset}
    for leaf, comp in leaflets.items():
        clean: dict[str, float] = {}
        for k, v in (comp or {}).items():
            c = canonical_lipid(k)
            if c is None:
                gates.append(Gate("membrane composition", NEEDS_HUMAN,
                                  f"不認得的脂質 {k!r}（{leaf} 葉）。目前可用：{', '.join(LIPIDS)}。",
                                  options=[f"md.membrane.lipids: {p}" for p in PRESETS]))
                return {}, gates
            try:
                fv = float(v)
            except (TypeError, ValueError):
                fv = -1.0
            if not math.isfinite(fv) or fv < 0:
                gates.append(Gate("membrane composition", NEEDS_HUMAN, f"{k} 的比例 {v!r} 不是非負數字。"))
                return {}, gates
            if fv > 0:
                clean[c] = clean.get(c, 0.0) + fv
        tot = sum(clean.values())
        if tot <= 0:
            gates.append(Gate("membrane composition", NEEDS_HUMAN, f"{leaf} 葉沒有任何脂質（比例總和為 0）。"))
            return {}, gates
        if abs(tot - 1.0) > 0.01:
            gates.append(Gate("membrane composition", AUTO_FIXED,
                              f"{leaf} 葉的比例總和 {tot:g}，已換算成分率（{', '.join(f'{k} {v / tot:.3f}' for k, v in clean.items())}）。"))
        out[leaf] = {k: v / tot for k, v in clean.items()}
    if "CHOL" in out["upper"] and out["upper"]["CHOL"] > 0.5 or "CHOL" in out["lower"] and out["lower"]["CHOL"] > 0.5:
        gates.append(Gate("membrane composition", NEEDS_HUMAN,
                          "膽固醇超過 50 mol%：高於生物膜的範圍（細胞膜約 20–40 mol%），膽固醇會析出成另一相。",
                          options=["md.membrane.lipids: {POPC: 0.7, CHOL: 0.3}"]))
    return out, gates


def composition_charge(comp: dict[str, float]) -> float:
    return sum(LIPIDS[k]["charge"] * f for k, f in comp.items())


def reference_values(comp: dict[str, float]) -> dict:
    """Fraction-weighted experimental APL and P–P thickness; None when a component has no value (cholesterol condenses
    the bilayer, so a weighted mean would be wrong; the gate then checks thickness and core water only)."""
    apl = [LIPIDS[k]["apl_nm2"] for k in comp]
    dpp = [LIPIDS[k]["dpp_nm"] for k in comp]
    return {"apl_nm2": None if any(a is None for a in apl) else sum(LIPIDS[k]["apl_nm2"] * f for k, f in comp.items()),
            "dpp_nm": None if any(d is None for d in dpp) else sum(LIPIDS[k]["dpp_nm"] * f for k, f in comp.items())}


def phase_gate(comp: dict, temperature_k: float) -> Gate | None:
    """A lipid that is the majority component and below Tm + 5 K would start in (or near) the gel phase: the area,
    thickness and order parameters then describe the wrong phase.  Mixtures lower Tm, so only majority lipids count."""
    bad = [(k, LIPIDS[k]["tm_k"]) for k, f in comp.items() if f >= 0.5 and LIPIDS[k]["tm_k"] and temperature_k < LIPIDS[k]["tm_k"] + 5]
    if not bad:
        return None
    need = max(t for _, t in bad) + 10.0
    return Gate("membrane phase", NEEDS_HUMAN,
                f"模擬溫度 {temperature_k:g} K 太接近或低於 {', '.join(f'{k}（Tm 約 {t:g} K）' for k, t in bad)} 的相轉變溫度："
                "膜會進入或接近凝膠相，面積、厚度與序參數都會是另一個相的值。",
                options=[f"md.membrane.temperature_k: {need:g}", "md.membrane.lipids: mammalian"],
                evidence={"temperature_k": temperature_k, "tm_k": dict(bad)})


# --------------------------------------------------------------------------------------------------- plan
def membrane_temperature(spec: dict | None) -> float:
    """md.membrane.temperature_k, else the preset's temperature, else 310 K (physiological; above POPE's Tm 298 K)."""
    s = {**DEFAULTS, **(spec or {})}
    if s.get("temperature_k") is not None:
        return float(s["temperature_k"])
    lip = s.get("lipids")
    return float(PRESETS[lip]["temperature_k"]) if isinstance(lip, str) and lip in PRESETS else 310.0


@dataclass
class MembranePlan:
    type: str
    composition: dict = field(default_factory=dict)      # {"upper": {...}, "lower": {...}, "preset": ...}
    builder: str = ""
    temperature_k: float = 310.0
    oriented: bool = False
    surface_distance_nm: float = 1.0
    surface_orientation: str = "as_is"
    lateral_padding_nm: float = 1.5
    water_nm: float = 2.0
    seed: int = 2026
    templates_dir: str | None = None
    size_nm: float | None = None
    forcefield_files: tuple = ("amber14/lipid17.xml",)
    reference: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)

    @property
    def single_lipid(self) -> str | None:
        up, lo = self.composition.get("upper", {}), self.composition.get("lower", {})
        if len(up) == 1 and up == lo:
            return next(iter(up))
        return None


def plan_membrane(spec: dict | None, *, has_solute: bool, solvent: str = "explicit") -> tuple[MembranePlan | None, GateReport]:
    """md.membrane → plan + gates.  Nothing here touches OpenMM."""
    rep = GateReport()
    s = {**DEFAULTS, **(spec or {})}
    mtype = s.get("type")
    if mtype not in MEMBRANE_TYPES:
        rep.add(Gate("membrane type", NEEDS_HUMAN, f"md.membrane.type = {mtype!r} 不是已知的膜系統類型。",
                     options=[f"md.membrane.type: {t}" for t in MEMBRANE_TYPES]))
        return None, rep
    if solvent != "explicit":
        rep.add(Gate("membrane implicit solvent", NEEDS_HUMAN,
                     "膜系統需要顯式水：GBn2 隱式溶劑沒有膜的介電環境，脂質頭基與水的作用無法表示。",
                     options=["md.solvent: explicit（顯式水）"]))
        return None, rep
    if mtype == "bilayer" and has_solute:
        rep.add(Gate("membrane type", NEEDS_HUMAN, "type: bilayer 是純膜，但設定裡有蛋白或配體。",
                     options=["md.membrane.type: protein", "md.membrane.type: surface"]))
        return None, rep
    if mtype in ("protein", "surface") and not has_solute:
        rep.add(Gate("membrane type", NEEDS_HUMAN, f"type: {mtype} 需要蛋白、胜肽或小分子，但沒有提供。",
                     options=["md.membrane.type: bilayer"]))
        return None, rep
    comp, gates = resolve_composition(s.get("lipids"))
    for g in gates:
        rep.add(g)
    if not rep.ok:
        return None, rep
    temp = membrane_temperature(s)
    plan = MembranePlan(type=mtype, composition=comp, temperature_k=temp, oriented=bool(s.get("oriented")),
                        surface_distance_nm=float(s.get("surface_distance_nm", 1.0)),
                        surface_orientation=str(s.get("surface_orientation") or "as_is"),
                        lateral_padding_nm=float(s.get("lateral_padding_nm", 1.5)), water_nm=float(s.get("water_nm", 2.0)),
                        seed=int(s.get("seed", 2026)), templates_dir=s.get("templates_dir"),
                        size_nm=(float(s["size_nm"]) if s.get("size_nm") else None))
    allc = {**comp["upper"], **comp["lower"]}
    whole = {k: 0.5 * (comp["upper"].get(k, 0.0) + comp["lower"].get(k, 0.0)) for k in allc}
    plan.reference = reference_values(whole)
    g = phase_gate(whole, temp)
    if g:
        rep.add(g)
    # force field: every lipid needs a template in the Amber lipid file used with ff14SB
    no_ff = [k for k in allc if not LIPIDS[k]["ff"]]
    if no_ff:
        rep.add(Gate("membrane force field", NEEDS_HUMAN,
                     f"{', '.join(no_ff)} 在 OpenMM 內建的 Amber 脂質力場（Lipid17、Lipid21）沒有參數，只有 CHARMM36 有"
                     f"（{', '.join(LIPIDS[k].get('charmm', '') for k in no_ff)}）。CHARMM 脂質不能和 Amber ff14SB 蛋白混用，"
                     "目前不提供這個組成。",
                     options=["md.membrane.lipids: bacterial", "md.membrane.lipids: {POPG: 1.0}",
                              "使用 CHARMM-GUI 建好的系統（尚未支援匯入）"]))
    if plan.type == "surface":
        if plan.surface_distance_nm < 0.3:
            rep.add(Gate("membrane surface placement", NEEDS_HUMAN,
                         f"起始距離 {plan.surface_distance_nm} nm 太近：分子會從頭基裡面開始，無法說明它是自己吸附上去的。",
                         options=["md.membrane.surface_distance_nm: 1.0"]))
        if plan.surface_orientation not in ("as_is", "random", "parallel", "normal"):
            rep.add(Gate("membrane surface placement", NEEDS_HUMAN,
                         f"未知的起始方向 {plan.surface_orientation!r}。",
                         options=["md.membrane.surface_orientation: as_is", "md.membrane.surface_orientation: parallel"]))
    if not rep.ok:
        return plan, rep
    single = plan.single_lipid
    if single and LIPIDS[single]["patch"]:
        plan.builder = "openmm_patch_tile" if mtype == "bilayer" else "openmm_addmembrane"
    else:
        plan.builder = "grid"
        missing = [k for k in allc if not LIPIDS[k]["patch"]]
        if missing and not plan.templates_dir:
            rep.add(Gate("membrane builder", NEEDS_HUMAN,
                         f"{', '.join(missing)} 沒有可用的單一脂質構形模板（OpenMM 只附 {', '.join(OPENMM_PATCH_LIPIDS)} 的膜片）。"
                         "格點排列器需要每種脂質一個沿 z 軸的模板 PDB；沒有模板時不猜構形。",
                         options=["md.membrane.templates_dir: <每種脂質一個 PDB 的資料夾>",
                                  "md.membrane.lipids: mammalian"]))
        else:
            rep.add(Gate("membrane builder", AUTO_FIXED,
                         "混合或非對稱膜改用格點排列器（每種脂質一個模板，依比例排在格點上）。這條路徑尚未在真實引擎上驗證，"
                         "平衡後的面積與厚度閘門必須通過才可使用。", advisory=True))
    return plan, rep


# --------------------------------------------------------------------------------------------------- orientation
# hydrophobicity weights for the slab score: aliphatic/aromatic core +1, Ala/Cys +0.5, Trp/Tyr (interfacial) +0.25,
# charged −1, amides −0.5; everything else 0.  Protonation variants map to their parent residue.
HYDRO_W = {"LEU": 1.0, "ILE": 1.0, "VAL": 1.0, "PHE": 1.0, "MET": 1.0, "ALA": 0.5, "CYS": 0.5, "CYX": 0.5, "CYM": 0.5,
           "TRP": 0.25, "TYR": 0.25, "ASP": -1.0, "GLU": -1.0, "LYS": -1.0, "ARG": -1.0, "ASH": -0.5, "GLH": -0.5,
           "LYN": -0.5, "ARN": -0.5, "ASN": -0.5, "GLN": -0.5, "HIP": -0.5, "MSE": 1.0}
HYDROPHOBIC = {k for k, v in HYDRO_W.items() if v >= 0.5}


def fibonacci_hemisphere(n: int) -> np.ndarray:
    i = np.arange(n) + 0.5
    z = 1.0 - i / n                      # (0, 1]: upper hemisphere (the normal's sign is irrelevant)
    r = np.sqrt(np.clip(1.0 - z * z, 0.0, 1.0))
    phi = i * math.pi * (3.0 - math.sqrt(5.0))
    return np.stack([r * np.cos(phi), r * np.sin(phi), z], axis=1)


def _cap(axis: np.ndarray, max_deg: float, n: int) -> np.ndarray:
    """n directions within max_deg of axis (for refinement)."""
    i = np.arange(n) + 0.5
    cos_t = 1.0 - (1.0 - math.cos(math.radians(max_deg))) * i / n
    sin_t = np.sqrt(1.0 - cos_t ** 2)
    phi = i * math.pi * (3.0 - math.sqrt(5.0))
    local = np.stack([sin_t * np.cos(phi), sin_t * np.sin(phi), cos_t], axis=1)
    return local @ rotation_to_z(axis)          # rows: R^T applied → directions around `axis`


def rotation_to_z(n: np.ndarray) -> np.ndarray:
    """Rotation matrix R with R @ n = ẑ (Rodrigues)."""
    n = np.asarray(n, float) / np.linalg.norm(n)
    z = np.array([0.0, 0.0, 1.0])
    v = np.cross(n, z)
    s, c = np.linalg.norm(v), float(np.dot(n, z))
    if s < 1e-12:
        return np.eye(3) if c > 0 else np.diag([1.0, -1.0, -1.0])
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * ((1 - c) / s ** 2)


def _slab_scores(X: np.ndarray, w: np.ndarray, D: np.ndarray, slab_nm: float, bin_nm: float = 0.05):
    """For each direction (row of D): best window sum of weights w over a slab of thickness slab_nm; returns
    (best score, slab centre along the direction)."""
    P = X @ D.T                                    # N × M projections
    lo = P.min()
    nb = int(math.ceil((P.max() - lo) / bin_nm)) + 2
    idx = np.floor((P - lo) / bin_nm).astype(int)
    M = D.shape[0]
    flat = (idx + nb * np.arange(M)[None, :]).ravel()
    H = np.bincount(flat, weights=np.repeat(w, M), minlength=M * nb).reshape(M, nb)
    C = np.concatenate([np.zeros((M, 1)), np.cumsum(H, axis=1)], axis=1)
    W = max(1, int(round(slab_nm / bin_nm)))
    if nb <= W:
        S = C[:, -1:] - C[:, :1]
        j = np.zeros(M, int)
    else:
        S = C[:, W:] - C[:, :-W]
        j = np.argmax(S, axis=1)
    best = S[np.arange(M), j]
    centre = lo + (j + 0.5 * W) * bin_nm
    return best, centre


def exposure_factor(ca: np.ndarray, radius_nm: float = 1.0, buried_weight: float = 0.4) -> np.ndarray:
    """Residues with many Cα neighbours (top 30 %) are buried: they face other helices, not lipid."""
    d2 = ((ca[:, None, :] - ca[None, :, :]) ** 2).sum(-1)
    cnt = (d2 < radius_nm ** 2).sum(1) - 1
    thr = np.quantile(cnt, 0.7) if len(cnt) else 0
    return np.where(cnt > thr, buried_weight, 1.0)


def scan_orientation(ca_xyz_nm, resnames, *, slab_nm: float = 3.0, n_dirs: int = 2000) -> dict:
    """Hydrophobic-slab scan: the membrane normal is the direction along which a slab of `slab_nm` holds the most
    (exposure-weighted) hydrophobic minus polar residues.  Returns normal, centre, tilt and confidence measures.

    Confidence (all must hold for "high"): hydrophobic fraction of the exposed residues in the slab ≥ 0.55, at least
    0.20 above the exposed residues outside, the best direction ≥ 20 % better than any direction > 45° away, ≥ 12
    exposed residues in the slab,
    and the protein extending ≥ 0.5 nm beyond both faces (it crosses the membrane)."""
    ca = np.asarray(ca_xyz_nm, float)
    rn = [str(r).upper() for r in resnames]
    if len(ca) < 10:
        return {"status": NEEDS_HUMAN, "confidence": "low", "reason": "too few residues", "n_residues": int(len(ca))}
    w0 = np.array([HYDRO_W.get(r, 0.0) for r in rn])
    expo = exposure_factor(ca)
    w = w0 * expo
    exposed = expo >= 1.0
    cen = ca.mean(0)
    X = ca - cen
    D = fibonacci_hemisphere(n_dirs)
    best, centre = _slab_scores(X, w, D, slab_nm)
    k = int(np.argmax(best))
    D2 = np.vstack([D[k], _cap(D[k], 6.0, 400)])
    D2 /= np.linalg.norm(D2, axis=1, keepdims=True)
    b2, c2 = _slab_scores(X, w, D2, slab_nm, bin_nm=0.02)
    k2 = int(np.argmax(b2))
    n, c, s_best = D2[k2], float(c2[k2]), float(b2[k2])
    if n[2] < 0:
        n, c = -n, -c
    ang = np.degrees(np.arccos(np.clip(np.abs(D @ n), 0.0, 1.0)))
    far = best[ang > 45.0]
    s_far = float(far.max()) if len(far) else -np.inf
    sharp = (s_best - s_far) / abs(s_best) if s_best > 0 and np.isfinite(s_far) else 0.0
    p = X @ n
    inside = np.abs(p - c) <= slab_nm / 2
    hyd = np.array([r in HYDROPHOBIC for r in rn])
    # fractions over lipid-facing (exposed) residues only: a soluble protein's buried core is hydrophobic too
    e_in, e_out = inside & exposed, ~inside & exposed
    f_in = float(hyd[e_in].mean()) if e_in.any() else 0.0
    f_out = float(hyd[e_out].mean()) if e_out.any() else 0.0
    beyond_lo, beyond_hi = float(c - slab_nm / 2 - p.min()), float(p.max() - (c + slab_nm / 2))
    checks = {"hydrophobic_in": f_in >= 0.55, "contrast": f_in - f_out >= 0.20, "sharpness": sharp >= 0.20,
              "residues_in_slab": int(e_in.sum()) >= 12, "crosses": min(beyond_lo, beyond_hi) >= 0.5}
    ok = all(checks.values())
    tilt = float(np.degrees(np.arccos(min(1.0, abs(float(n[2]))))))
    return {"status": PASS if ok else NEEDS_HUMAN, "confidence": "high" if ok else "low",
            "normal": [float(x) for x in n], "centre_nm": [float(x) for x in (cen + c * n)],
            "tilt_deg": round(tilt, 2), "slab_nm": slab_nm, "score": round(s_best, 3),
            "score_other_direction": round(s_far, 3) if np.isfinite(s_far) else None, "sharpness": round(sharp, 3),
            "hydrophobic_fraction_in": round(f_in, 3), "hydrophobic_fraction_out": round(f_out, 3),
            "residues_in_slab": int(inside.sum()), "exposed_in_slab": int(e_in.sum()), "beyond_faces_nm": [round(beyond_lo, 2), round(beyond_hi, 2)],
            "checks": checks, "n_residues": int(len(ca))}


def orientation_transform(result: dict) -> tuple[np.ndarray, np.ndarray]:
    """(R, t) with x' = R @ (x − t): membrane normal → z, membrane centre → origin."""
    return rotation_to_z(np.asarray(result["normal"])), np.asarray(result["centre_nm"], float)


def apply_transform(xyz: np.ndarray, R: np.ndarray, t: np.ndarray) -> np.ndarray:
    return (np.asarray(xyz, float) - t) @ R.T


def orientation_gate(result: dict, *, oriented: bool) -> Gate:
    """User-oriented input (OPM, PDBTM, CHARMM-GUI) is used as is; the scan is still run and differences are listed.
    Automatic orientation without a clear hydrophobic belt stops (block rather than guess)."""
    if oriented:
        diffs = []
        if result.get("normal"):
            if result["tilt_deg"] > 15.0:
                diffs.append(f"自動判定的法線和輸入 z 軸差 {result['tilt_deg']:.0f}°")
            cz = result["centre_nm"][2]
            if abs(cz) > 0.5:
                diffs.append(f"疏水帶中心在 z = {cz:+.2f} nm，不在 0")
        note = "；".join(diffs)
        return Gate("membrane orientation", PASS if not diffs else AUTO_FIXED,
                    "使用者提供已定向的結構，照原樣使用（膜中心在 z = 0，法線為 z）。"
                    + (f"自動掃描的結果不同：{note}。請確認結構來源（OPM 的膜中心在 z = 0）。" if diffs else ""),
                    evidence=result, advisory=bool(diffs))
    if result.get("status") == PASS:
        return Gate("membrane orientation", AUTO_FIXED,
                    f"疏水帶掃描找到膜法線：傾角 {result['tilt_deg']:.0f}°（相對輸入的 z 軸），帶內疏水殘基比例 "
                    f"{result['hydrophobic_fraction_in']:.2f}、帶外 {result['hydrophobic_fraction_out']:.2f}。"
                    "已旋轉使法線為 z、膜中心在 z = 0。膜的內外側無法由疏水帶判斷，請以 OPM 或文獻確認。",
                    evidence=result)
    failed = [k for k, v in (result.get("checks") or {}).items() if not v] or [result.get("reason", "")]
    return Gate("membrane orientation", NEEDS_HUMAN,
                f"疏水帶不明顯，無法可靠判定膜中的方向（未通過：{', '.join(failed)}）。不猜方向。",
                options=["md.membrane.oriented: true（結構已依 OPM 定向）", "下載 OPM 定向結構後重新上傳",
                         "md.membrane.type: surface"],
                evidence=result)


# --------------------------------------------------------------------------------------------------- surface (case B)
def principal_axis(xyz: np.ndarray) -> np.ndarray:
    X = np.asarray(xyz, float) - np.mean(xyz, axis=0)
    _, _, vt = np.linalg.svd(X, full_matrices=False)
    return vt[0]


def random_rotation(rng: np.random.Generator) -> np.ndarray:
    q = rng.normal(size=4)
    q /= np.linalg.norm(q)
    a, b, c, d = q
    return np.array([[a * a + b * b - c * c - d * d, 2 * (b * c - a * d), 2 * (b * d + a * c)],
                     [2 * (b * c + a * d), a * a - b * b + c * c - d * d, 2 * (c * d - a * b)],
                     [2 * (b * d - a * c), 2 * (c * d + a * b), a * a - b * b - c * c + d * d]])


def place_on_surface(xyz_nm, *, upper_p_z: float, distance_nm: float = 1.0, box_xy=None, orientation: str = "as_is",
                     seed: int = 2026, heavy_mask=None) -> tuple[np.ndarray, dict]:
    """Put the solute above the upper-leaflet phosphate plane: its lowest heavy atom at upper_p_z + distance_nm,
    centroid at a random lateral position inside box_xy (seeded).  orientation: as_is | random | parallel (long axis in
    the membrane plane, the usual start for amphipathic helices) | normal (long axis along z)."""
    xyz = np.asarray(xyz_nm, float)
    rng = np.random.default_rng(seed)
    heavy = np.ones(len(xyz), bool) if heavy_mask is None else np.asarray(heavy_mask, bool)
    c0 = xyz[heavy].mean(0)
    X = xyz - c0
    if orientation == "random":
        X = X @ random_rotation(rng).T
    elif orientation in ("parallel", "normal"):
        ax = principal_axis(X[heavy])
        R = rotation_to_z(ax)                     # long axis → z
        X = X @ R.T
        if orientation == "parallel":
            X = X @ np.array([[1.0, 0, 0], [0, 0, -1.0], [0, 1.0, 0]]).T     # z → y: long axis in the plane
    lateral = np.zeros(2) if box_xy is None else rng.uniform(0.0, 1.0, 2) * np.asarray(box_xy, float)
    zmin = X[heavy, 2].min()
    shift = np.array([lateral[0], lateral[1], upper_p_z + distance_nm - zmin])
    out = X + shift
    info = {"distance_nm": float(distance_nm), "upper_p_z_nm": float(upper_p_z), "lateral_xy_nm": [float(v) for v in lateral],
            "orientation": orientation, "lowest_heavy_z_nm": float(out[heavy, 2].min()),
            "top_z_nm": float(out[:, 2].max()), "seed": int(seed)}
    if orientation in ("parallel", "normal"):
        info["long_axis_tilt_deg"] = float(np.degrees(np.arccos(min(1.0, abs(principal_axis(out[heavy])[2])))))
    return out, info


def surface_box_z(top_z_nm: float, *, centre_z: float = 0.0, dpp_nm: float = 3.8, water_gap_nm: float = 2.0) -> float:
    """Box height so that above the solute there are ≥ water_gap_nm of water before the periodic image of the lower
    leaflet's head groups (2 × the 1.0 nm cutoff: the solute must not feel the other side of the membrane)."""
    z_low_edge = centre_z - dpp_nm / 2 - P_TO_EDGE_NM
    return float(top_z_nm - z_low_edge + water_gap_nm)


def bilayer_box_z(dpp_nm: float, water_nm: float) -> float:
    return float(dpp_nm + 2 * P_TO_EDGE_NM + 2 * water_nm)


# --------------------------------------------------------------------------------------------------- ions
def n_salt_pairs(n_water: int, molar: float) -> int:
    """Ion pairs for a salt concentration from the number of waters (55.4 mol/L water), as OpenMM's Modeller does."""
    return int(math.floor(n_water * molar / 55.4 + 0.5))


def choose_ion_waters(o_xyz_nm, n: int, *, centre_z: float, box=None, exclude_half_nm: float = 2.6,
                      min_sep_nm: float = 0.5, seed: int = 2026) -> list[int]:
    """Indices of n water oxygens to replace by ions: outside |z − centre| < exclude_half_nm (not in the head groups)
    and ≥ min_sep_nm from already chosen ions (minimum image when box = (Lx, Ly, Lz) is given)."""
    o = np.asarray(o_xyz_nm, float)
    if n <= 0:
        return []
    rng = np.random.default_rng(seed)
    dz = o[:, 2] - centre_z
    if box is not None:
        dz -= box[2] * np.round(dz / box[2])
    cand = np.where(np.abs(dz) >= exclude_half_nm)[0]
    rng.shuffle(cand)
    chosen: list[int] = []
    for i in cand:
        if chosen:
            d = o[chosen] - o[i]
            if box is not None:
                d -= np.asarray(box, float) * np.round(d / np.asarray(box, float))
            if np.min((d ** 2).sum(1)) < min_sep_nm ** 2:
                continue
        chosen.append(int(i))
        if len(chosen) == n:
            break
    if len(chosen) < n:
        raise ValueError(f"只找到 {len(chosen)} 個可換成離子的水分子（需要 {n}）；水層太薄。")
    return chosen


# --------------------------------------------------------------------------------------------------- grid placer
@dataclass
class LipidTemplate:
    """One lipid with its long axis along +z, head up, phosphorus (or cholesterol O3) at the origin; nm."""
    name: str
    xyz: np.ndarray
    elements: list
    atom_names: list
    head_index: int
    source: str = ""


def template_from_coordinates(name: str, xyz_nm, elements, atom_names, *, source: str = "") -> LipidTemplate:
    """Orient one lipid: head atom (P, else O3 for cholesterol) to the origin; the vector from the heavy-atom
    centroid to the head atom becomes +z."""
    xyz = np.asarray(xyz_nm, float)
    el = [str(e).upper() for e in elements]
    names = [str(a).upper() for a in atom_names]
    if "P" in el:
        h = el.index("P")
    elif "O3" in names:
        h = names.index("O3")
    else:
        raise ValueError(f"{name} 模板沒有磷原子或 O3，無法決定頭基位置。")
    heavy = np.array([e != "H" for e in el])
    axis = xyz[h] - xyz[heavy].mean(0)
    R = rotation_to_z(axis)
    out = (xyz - xyz[h]) @ R.T
    return LipidTemplate(name=name, xyz=out, elements=list(elements), atom_names=list(atom_names), head_index=h, source=source)


def grid_slots(box_xy, n: int, rng: np.random.Generator | None = None, jitter: float = 0.1) -> np.ndarray:
    """n lateral positions on a near-square grid filling the box (± jitter × spacing)."""
    Lx, Ly = float(box_xy[0]), float(box_xy[1])
    nx = max(1, int(round(math.sqrt(n * Lx / Ly))))
    ny = int(math.ceil(n / nx))
    gx, gy = np.meshgrid((np.arange(nx) + 0.5) * Lx / nx, (np.arange(ny) + 0.5) * Ly / ny, indexing="ij")
    pts = np.stack([gx.ravel(), gy.ravel()], 1)[:n]
    if rng is not None and jitter > 0:
        pts = pts + rng.uniform(-jitter, jitter, pts.shape) * np.array([Lx / nx, Ly / ny])
    return pts


def free_slots(slots_xy, protein_xyz, *, z_lo: float, z_hi: float, radius_nm: float = 0.5, box_xy=None) -> np.ndarray:
    """Mask of slots with no protein heavy atom within radius_nm laterally inside the leaflet's z range."""
    slots = np.asarray(slots_xy, float)
    if protein_xyz is None or len(protein_xyz) == 0:
        return np.ones(len(slots), bool)
    p = np.asarray(protein_xyz, float)
    p = p[(p[:, 2] >= z_lo) & (p[:, 2] <= z_hi)][:, :2]
    if not len(p):
        return np.ones(len(slots), bool)
    d = slots[:, None, :] - p[None, :, :]
    if box_xy is not None:
        b = np.asarray(box_xy, float)
        d -= b * np.round(d / b)
    return (d ** 2).sum(-1).min(1) > radius_nm ** 2


def assign_lipids(fracs: dict[str, float], n_slots: int, rng: np.random.Generator) -> list[str]:
    counts = _counts_from_fractions(fracs, n_slots)
    names = [k for k, c in counts.items() for _ in range(c)]
    rng.shuffle(names)
    return names


def grid_layout(plan_comp: dict, box_xy, *, centre_z: float = 0.0, dpp_nm: float, apl_nm2: float,
                protein_xyz=None, seed: int = 2026) -> dict:
    """Lipid slots for both leaflets: [(leaflet, name, x, y, z_head, flip)], composition kept exact on the surviving
    slots (identities are assigned after the protein has removed slots)."""
    rng = np.random.default_rng(seed)
    area = float(box_xy[0]) * float(box_xy[1])
    n_full = max(1, int(round(area / apl_nm2)))
    out = []
    counts = {}
    for leaf, sign in (("upper", 1.0), ("lower", -1.0)):
        slots = grid_slots(box_xy, n_full, rng)
        zh = centre_z + sign * dpp_nm / 2
        z_lo, z_hi = (centre_z, zh + P_TO_EDGE_NM) if sign > 0 else (zh - P_TO_EDGE_NM, centre_z)
        keep = free_slots(slots, protein_xyz, z_lo=z_lo, z_hi=z_hi, box_xy=box_xy)
        slots = slots[keep]
        names = assign_lipids(plan_comp[leaf], len(slots), rng)
        counts[leaf] = {k: names.count(k) for k in sorted(set(names))}
        for (x, y), nm in zip(slots, names):
            out.append({"leaflet": leaf, "lipid": nm, "x": float(x), "y": float(y), "z_head": float(zh), "flip": sign < 0,
                        "rot_deg": float(rng.uniform(0, 360))})
    return {"slots": out, "counts": counts, "n_full_per_leaflet": n_full}


def place_template(t: LipidTemplate, slot: dict) -> np.ndarray:
    th = math.radians(slot["rot_deg"])
    Rz = np.array([[math.cos(th), -math.sin(th), 0], [math.sin(th), math.cos(th), 0], [0, 0, 1.0]])
    X = t.xyz @ Rz.T
    if slot["flip"]:
        X = X * np.array([1.0, -1.0, -1.0])          # 180° about x: head down for the lower leaflet
    return X + np.array([slot["x"], slot["y"], slot["z_head"]])


# --------------------------------------------------------------------------------------------------- OpenMM part
def patch_pdb_path(lipid: str) -> Path:
    import openmm.app as app
    return Path(app.__file__).parent / "data" / f"{lipid}.pdb"


_WATER = {"HOH", "WAT", "TIP3", "SOL"}
_IONS = {"NA", "K", "LI", "RB", "CS", "CL", "BR", "F", "I", "NA+", "CL-", "MG", "CA", "ZN"}


def index_ranges(idx) -> list[list[int]]:
    """Sorted indices → [[start, stop), ...] (compact form for the manifest)."""
    out: list[list[int]] = []
    for i in sorted(int(v) for v in idx):
        if out and out[-1][1] == i:
            out[-1][1] = i + 1
        else:
            out.append([i, i + 1])
    return out


def lipid_atom_indices(topology, start: int = 0) -> list[int]:
    """Atoms added by the membrane builder that are neither water nor ions (lipids come right after the solute)."""
    return [a.index for a in topology.atoms() if a.index >= start and a.residue.name.upper() not in _WATER | _IONS]


def head_atoms(topology, lipid_indices) -> list[int]:
    s = set(lipid_indices)
    out = []
    for a in topology.atoms():
        if a.index in s and a.element is not None and (a.element.symbol == "P" or (a.name.upper() == "O3" and a.residue.name.upper() in
                                                                                    {"CHL1", "CHL", "CHOL"})):
            out.append(a.index)
    return out


def add_headgroup_restraints(system, topology, positions, head_indices, *, k: float = HEAD_K_KJ_MOL_NM2) -> dict:
    """z-only harmonic restraint on lipid head atoms, scaled by msw_restraint_scale·msw_rs_lipid_head (D-23 groups).
    Only z: the lipids diffuse laterally from the start; the head groups are held at their plane while water and the
    protein relax, then released over NPT (membrane_protocol)."""
    import openmm as mm
    from openmm import unit
    f = mm.CustomExternalForce("0.5*msw_restraint_scale*msw_rs_lipid_head*k_head*periodicdistance(0,0,z,0,0,z0)^2")
    f.addGlobalParameter("msw_restraint_scale", 1.0)
    f.addGlobalParameter("msw_rs_lipid_head", 1.0)
    f.addPerParticleParameter("k_head")
    f.addPerParticleParameter("z0")
    pos = positions.value_in_unit(unit.nanometer)
    for i in head_indices:
        f.addParticle(int(i), [float(k), float(pos[i][2])])
    f.setName("msw_lipid_head_restraints")
    system.addForce(f)
    return {"type": "CustomExternalForce", "group_parameter": "msw_rs_lipid_head", "atoms": len(head_indices),
            "k_kj_mol_nm2": float(k), "coordinate": "z"}


def _xyz(modeller) -> np.ndarray:
    from openmm import unit
    return np.asarray(modeller.positions.value_in_unit(unit.nanometer), float)


def _set_xyz(modeller, xyz: np.ndarray) -> None:
    from openmm import unit, Vec3
    modeller.positions = unit.Quantity([Vec3(*map(float, p)) for p in xyz], unit.nanometer)


def patch_geometry(lipid: str) -> dict:
    """Phosphate planes of OpenMM's patch where addMembrane puts it (membraneCenterZ = 0): addMembrane shifts the patch
    so the centre of its bounding box (lipids and water) lands on membraneCenterZ (modeller.py)."""
    from openmm import app, unit
    patch = app.PDBFile(str(patch_pdb_path(lipid)))
    p = np.asarray(patch.positions.value_in_unit(unit.nanometer), float)
    box_c = 0.5 * (p[:, 2].min() + p[:, 2].max())
    atoms = list(patch.topology.atoms())
    pz = np.array([p[a.index, 2] for a in atoms if a.element is not None and a.element.symbol == "P"]) - box_c
    mid = pz.mean()
    up, lo = pz[pz > mid], pz[pz <= mid]
    return {"upper_p_z_nm": float(up.mean()), "lower_p_z_nm": float(lo.mean()), "dpp_nm": float(up.mean() - lo.mean()),
            "n_per_leaflet": [int(len(up)), int(len(lo))]}


def prepare_solute(modeller, plan: MembranePlan, report: GateReport, decisions=None) -> dict:
    """Orient (protein) or place (surface) everything already in the Modeller, in place.  Returns placement info."""
    atoms = list(modeller.topology.atoms())
    xyz = _xyz(modeller)
    heavy = np.array([a.element is not None and a.element.symbol != "H" for a in atoms])
    info: dict = {}
    if plan.type == "protein":
        ca = [(a.index, a.residue.name) for a in atoms if a.name == "CA" and a.element is not None and a.element.symbol == "C"]
        res = scan_orientation(xyz[[i for i, _ in ca]], [r for _, r in ca]) if ca else {"status": NEEDS_HUMAN, "reason": "no CA"}
        g = report.add(orientation_gate(res, oriented=plan.oriented))
        info["orientation"] = res
        if decisions:
            decisions.record("build.membrane", "orientation", "user" if plan.oriented else res.get("status"),
                             g.explanation, kind="human" if g.status == NEEDS_HUMAN else "auto_fixed")
        if g.status == NEEDS_HUMAN or plan.oriented:
            return info
        R, t = orientation_transform(res)
        _set_xyz(modeller, apply_transform(xyz, R, t))
        info["transform"] = {"rotation": R.tolist(), "origin_nm": t.tolist()}
    elif plan.type == "surface":
        if plan.builder == "openmm_addmembrane":
            upper = patch_geometry(plan.single_lipid)["upper_p_z_nm"]       # the patch's own phosphate plane
        else:
            upper = (plan.reference.get("dpp_nm") or 3.8) / 2              # grid: heads placed at ± dpp/2
        out, pinfo = place_on_surface(xyz, upper_p_z=upper, distance_nm=plan.surface_distance_nm, box_xy=None,
                                      orientation=plan.surface_orientation, seed=plan.seed, heavy_mask=heavy)
        _set_xyz(modeller, out)
        info["surface"] = pinfo
        report.add(Gate("membrane surface placement", AUTO_FIXED,
                        f"溶質放在上葉磷原子平面上方 {plan.surface_distance_nm} nm（最低重原子），起始方向 {plan.surface_orientation}。"
                        "膜在 x、y 方向週期延伸，側向位置不影響結果。", evidence=pinfo))
        if decisions:
            decisions.record("build.membrane", "surface placement", pinfo,
                             f"溶質最低重原子放在上葉磷平面上方 {plan.surface_distance_nm} nm：起始時不接觸頭基，之後的吸附或插入"
                             "是模擬的結果，不是建模造成的。")
    return info


def add_membrane(modeller, forcefield, plan: MembranePlan, *, ion_spec: dict, report: GateReport,
                 decisions=None, platform=None) -> dict:
    """Case A and B: build the bilayer around (or below) the solute already in the Modeller.  Edits the Modeller."""
    from openmm import unit, Vec3
    info = {"plan": plan.to_dict()}
    info.update(prepare_solute(modeller, plan, report, decisions))
    if not report.ok:
        return info
    n0 = modeller.topology.getNumAtoms()
    xyz = _xyz(modeller)
    dpp = plan.reference.get("dpp_nm") or 3.8
    if plan.type == "surface":
        lz = surface_box_z(float(xyz[:, 2].max()), dpp_nm=dpp, water_gap_nm=plan.water_nm)
    else:
        lz = float(xyz[:, 2].max() - xyz[:, 2].min()) + 2 * plan.water_nm
        lz = max(lz, bilayer_box_z(dpp, plan.water_nm))
    if plan.builder == "openmm_addmembrane":
        lipid = plan.single_lipid
        pad = plan.lateral_padding_nm
        # addMembrane takes the box height from the existing unit cell (+ 2 × padding) when one is set (OpenMM
        # modeller.py); setting it is how the water layer above a surface solute is made thick enough
        size = xyz.max(0) - xyz.min(0)
        modeller.topology.setUnitCellDimensions(Vec3(float(size[0]) + 2 * pad, float(size[1]) + 2 * pad, max(0.1, lz - 2 * pad)) * unit.nanometer)
        modeller.addMembrane(forcefield, lipidType=lipid, membraneCenterZ=0.0 * unit.nanometer,
                             minimumPadding=pad * unit.nanometer, positiveIon=ion_spec["positive"],
                             negativeIon=ion_spec["negative"], ionicStrength=ion_spec["concentration_molar"] * unit.molar,
                             neutralize=ion_spec["neutralize"], platform=platform)
        info["builder"] = "openmm_addmembrane"
    else:
        _grid_membrane(modeller, forcefield, plan, ion_spec=ion_spec, lz=lz, report=report, info=info)
        if not report.ok:
            return info
    _finish_info(modeller, n0, plan, info)
    if decisions:
        decisions.record("build.membrane", "bilayer", {"builder": info["builder"], "lipids": info.get("lipid_counts")},
                         f"{plan.type} 膜系統：{info['builder']}，{info.get('n_lipids')} 個脂質，盒子 "
                         f"{' × '.join(f'{v:.2f}' for v in info.get('box_nm', []))} nm；溫度 {plan.temperature_k:g} K。")
    return info


def _finish_info(modeller, n0: int, plan: MembranePlan, info: dict) -> None:
    lip = lipid_atom_indices(modeller.topology, n0)
    heads = head_atoms(modeller.topology, lip)
    xyz = _xyz(modeller)
    hz = xyz[heads, 2] if heads else np.zeros(0)
    centre = float(hz.mean()) if len(hz) else 0.0
    up = hz > centre
    counts: dict = {}
    hs = set(heads)
    for a in modeller.topology.atoms():
        if a.index in hs:
            counts[a.residue.name] = counts.get(a.residue.name, 0) + 1
    if info.get("grid"):          # patch residue names are truncated (POPC and POPE are both "POP"): use the layout
        counts = {}
        for leaf in info["grid"]["counts"].values():
            for k, c in leaf.items():
                counts[k] = counts.get(k, 0) + c
    vecs = modeller.topology.getPeriodicBoxVectors()
    info.update({"lipid_atom_ranges": index_ranges(lip), "head_atom_indices": heads,
                 "n_lipids": len(heads), "n_upper": int(up.sum()), "n_lower": int((~up).sum()), "lipid_counts": counts,
                 "centre_z_nm": round(centre, 3),
                 "dpp_initial_nm": round(float(hz[up].mean() - hz[~up].mean()), 3) if up.any() and (~up).any() else None,
                 "box_nm": [float(vecs[i][i].value_in_unit(__import__("openmm").unit.nanometer)) for i in range(3)] if vecs else []})


def build_bilayer(forcefield, plan: MembranePlan, *, ion_spec: dict, report: GateReport, decisions=None):
    """Case C: a bilayer with water and ions, no solute.  Returns (modeller, info)."""
    from openmm import app, unit, Vec3
    info = {"plan": plan.to_dict()}
    if plan.builder != "openmm_patch_tile":
        modeller = app.Modeller(app.Topology(), unit.Quantity([], unit.nanometer))
        _grid_membrane(modeller, forcefield, plan, ion_spec=ion_spec,
                       lz=bilayer_box_z(plan.reference.get("dpp_nm") or 3.8, plan.water_nm), report=report, info=info)
        if report.ok:
            _finish_info(modeller, 0, plan, info)
        return modeller, info
    patch = app.PDBFile(str(patch_pdb_path(plan.single_lipid)))
    p = np.asarray(patch.positions.value_in_unit(unit.nanometer), float)
    cell = patch.topology.getUnitCellDimensions().value_in_unit(unit.nanometer)
    n = 1 if not plan.size_nm else max(1, int(math.ceil(plan.size_nm / min(cell[0], cell[1]))))
    lip_mask = np.array([a.residue.name not in _WATER for a in patch.topology.atoms()])
    centre = p[lip_mask, 2].mean()
    modeller = app.Modeller(patch.topology, unit.Quantity([Vec3(*(x - [0, 0, centre])) for x in p], unit.nanometer))
    for ix in range(n):
        for iy in range(n):
            if ix == 0 and iy == 0:
                continue
            off = np.array([ix * cell[0], iy * cell[1], -centre])
            modeller.add(patch.topology, unit.Quantity([Vec3(*(x + off)) for x in p], unit.nanometer))
    modeller.topology.setUnitCellDimensions(Vec3(n * cell[0], n * cell[1], cell[2]) * unit.nanometer)
    _add_ions_by_replacement(modeller, ion_spec, centre_z=0.0, plan=plan, info=info)
    info["builder"] = "openmm_patch_tile"
    info["patch"] = {"file": str(patch_pdb_path(plan.single_lipid).name), "copies": n * n, "cell_nm": [float(c) for c in cell]}
    _finish_info(modeller, 0, plan, info)
    report.add(Gate("membrane builder", PASS, f"純膜：OpenMM 內建的 {plan.single_lipid} 平衡膜片 {n}×{n} 份。"))
    if decisions:
        decisions.record("build.membrane", "bilayer", info["patch"],
                         f"純 {plan.single_lipid} 膜直接用 OpenMM 附的平衡膜片（{n}×{n} 份），沒有溶質所以不需要 addMembrane 的鬆弛步驟。")
    return modeller, info


def _add_ions_by_replacement(modeller, ion_spec: dict, *, centre_z: float, plan: MembranePlan, info: dict,
                             charge: int = 0) -> None:
    """Neutralise (`charge` = net charge of everything but water and ions) and add salt by replacing waters outside
    the head-group region (choose_ion_waters)."""
    from openmm import app, unit, Vec3
    waters = [r for r in modeller.topology.residues() if r.name in _WATER]
    o_idx = [next(a.index for a in r.atoms() if a.element is not None and a.element.symbol == "O") for r in waters]
    xyz = _xyz(modeller)
    q = int(charge)
    pairs = n_salt_pairs(len(waters), ion_spec["concentration_molar"])
    n_pos = pairs + (max(0, -q) if ion_spec["neutralize"] else 0)
    n_neg = pairs + (max(0, q) if ion_spec["neutralize"] else 0)
    vecs = modeller.topology.getUnitCellDimensions()
    box = np.asarray(vecs.value_in_unit(unit.nanometer), float) if vecs is not None else None
    dpp = plan.reference.get("dpp_nm") or 3.8
    pick = choose_ion_waters(xyz[o_idx], n_pos + n_neg, centre_z=centre_z, box=box,
                             exclude_half_nm=dpp / 2 + P_TO_EDGE_NM + 0.2, seed=plan.seed)
    from .assemble import POSITIVE_IONS, NEGATIVE_IONS
    sites = [xyz[o_idx[i]] for i in pick]
    modeller.delete([waters[i] for i in pick])
    top = app.Topology()
    ch = top.addChain()
    pos = []
    for k, site in enumerate(sites):
        ion = ion_spec["positive"] if k < n_pos else ion_spec["negative"]
        rn = (POSITIVE_IONS if k < n_pos else NEGATIVE_IONS)[ion]
        el = app.Element.getBySymbol(ion.rstrip("+-"))
        r = top.addResidue(rn, ch)
        top.addAtom(rn, el, r)
        pos.append(Vec3(*map(float, site)))
    if pos:
        modeller.add(top, unit.Quantity(pos, unit.nanometer))
    info["ions_by_replacement"] = {"positive": n_pos, "negative": n_neg, "salt_pairs": pairs, "lipid_charge": q}


def load_templates(plan: MembranePlan, names) -> dict:
    """Templates: OpenMM patch lipids from the patch file (first lipid molecule of the upper leaflet), others from
    plan.templates_dir/<NAME>.pdb.  Returns {name: (LipidTemplate, openmm Topology of one lipid)}."""
    from openmm import app, unit
    out = {}
    for nm in names:
        if LIPIDS[nm]["patch"] and not (plan.templates_dir and (Path(plan.templates_dir) / f"{nm}.pdb").is_file()):
            pdb = app.PDBFile(str(patch_pdb_path(nm)))
            src = f"openmm/app/data/{nm}.pdb"
        else:
            pth = Path(plan.templates_dir or ".") / f"{nm}.pdb"
            if not pth.is_file():
                raise FileNotFoundError(f"缺少脂質模板 {pth}")
            pdb = app.PDBFile(str(pth))
            src = str(pth)
        top = pdb.topology
        xyz = np.asarray(pdb.positions.value_in_unit(unit.nanometer), float)
        mol = _first_lipid_molecule(top, xyz)
        mod = app.Modeller(top, pdb.positions)
        keep = set(mol)
        mod.delete([a for a in mod.topology.atoms() if a.index not in keep])
        atoms = list(mod.topology.atoms())
        t = template_from_coordinates(nm, _xyz(mod), [a.element.symbol for a in atoms], [a.name for a in atoms], source=src)
        out[nm] = (t, mod.topology)
    return out


def _first_lipid_molecule(top, xyz) -> list[int]:
    """Atom indices of one whole lipid molecule (connected through bonds) containing a P (or O3), in the upper half."""
    parent = list(range(top.getNumAtoms()))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for a, b in top.bonds():
        ra, rb = find(a.index), find(b.index)
        if ra != rb:
            parent[ra] = rb
    groups: dict[int, list[int]] = {}
    for a in top.atoms():
        if a.residue.name in _WATER | _IONS:
            continue
        groups.setdefault(find(a.index), []).append(a.index)
    atoms = list(top.atoms())
    zc = np.mean([xyz[i, 2] for g in groups.values() for i in g]) if groups else 0.0
    for g in sorted(groups.values(), key=lambda g: g[0]):
        heads = [i for i in g if atoms[i].element is not None and (atoms[i].element.symbol == "P" or atoms[i].name.upper() == "O3")]
        if heads and xyz[heads[0], 2] > zc and len(g) > 20:
            return g
    raise ValueError("模板檔中找不到完整的脂質分子（需要 CONECT 鍵結與磷原子或 O3）。")


def _solute_charge(forcefield, solute) -> float:
    """Net charge of the solute (protein, peptide, ligands) from the force field; 0 without a solute."""
    if not solute:
        return 0.0
    import openmm as mm
    from openmm import app
    top, n = solute
    sub = app.Modeller(top, [mm.Vec3(0, 0, 0)] * top.getNumAtoms())
    sub.delete([a for a in sub.topology.atoms() if a.index >= n])
    system = forcefield.createSystem(sub.topology, nonbondedMethod=app.NoCutoff)
    nb = next(f for f in system.getForces() if isinstance(f, mm.NonbondedForce))
    return sum(nb.getParticleParameters(i)[0]._value for i in range(nb.getNumParticles()))


def _grid_membrane(modeller, forcefield, plan: MembranePlan, *, ion_spec: dict, lz: float, report: GateReport, info: dict) -> None:
    """Grid placer (unverified on a real engine): lipids from templates on a grid, protein slots removed, water added
    with addSolvent and then removed from the hydrophobic core, ions by replacement."""
    from openmm import app, unit, Vec3
    names = sorted({*plan.composition["upper"], *plan.composition["lower"]})
    try:
        templates = load_templates(plan, names)
    except (FileNotFoundError, ValueError) as exc:
        report.add(Gate("membrane builder", NEEDS_HUMAN, f"無法取得脂質模板：{exc}",
                        options=["md.membrane.templates_dir: <每種脂質一個 PDB 的資料夾>", "md.membrane.lipids: mammalian"]))
        return
    apl = plan.reference.get("apl_nm2") or 0.65
    dpp = plan.reference.get("dpp_nm") or 3.8
    n_solute = modeller.topology.getNumAtoms()
    xyz = _xyz(modeller)[:n_solute] if n_solute else np.zeros((0, 3))
    if n_solute:
        n_solute = (modeller.topology, n_solute)
    pad = plan.lateral_padding_nm
    if len(xyz):
        size = xyz.max(0) - xyz.min(0)
        box_xy = (float(size[0]) + 2 * pad, float(size[1]) + 2 * pad)
        shift = np.array([box_xy[0] / 2, box_xy[1] / 2, 0.0]) - np.array([*(xyz.min(0)[:2] + size[:2] / 2), 0.0])
        _set_xyz(modeller, xyz + shift)
        xyz = xyz + shift
    else:
        side = plan.size_nm or math.sqrt(64 * apl)
        box_xy = (side, side)
    lay = grid_layout(plan.composition, box_xy, dpp_nm=dpp, apl_nm2=apl,
                      protein_xyz=xyz if len(xyz) else None, seed=plan.seed)
    lt = app.Topology()
    ch = lt.addChain()
    pos = []
    for slot in lay["slots"]:
        t, ttop = templates[slot["lipid"]]
        amap = {}
        for res in ttop.residues():
            r = lt.addResidue(res.name, ch)
            for a in res.atoms():
                amap[a.index] = lt.addAtom(a.name, a.element, r)
        for a, b in ttop.bonds():
            lt.addBond(amap[a.index], amap[b.index])
        pos += [Vec3(*map(float, x)) for x in place_template(t, slot)]
    modeller.add(lt, unit.Quantity(pos, unit.nanometer))
    modeller.topology.setUnitCellDimensions(Vec3(box_xy[0], box_xy[1], lz) * unit.nanometer)
    modeller.addSolvent(forcefield, boxSize=Vec3(box_xy[0], box_xy[1], lz) * unit.nanometer, neutralize=False)
    allx = _xyz(modeller)
    core = [r for r in modeller.topology.residues() if r.name in _WATER and
            abs(float(allx[next(iter(r.atoms())).index, 2])) < dpp / 2 - 0.2]
    modeller.delete(core)
    q = sum(LIPIDS[k]["charge"] * c for leaf in lay["counts"].values() for k, c in leaf.items()) + _solute_charge(forcefield, n_solute)
    _add_ions_by_replacement(modeller, ion_spec, centre_z=0.0, plan=plan, info=info, charge=int(round(q)))
    info["builder"] = "grid"
    info["grid"] = {"counts": lay["counts"], "n_full_per_leaflet": lay["n_full_per_leaflet"], "core_waters_removed": len(core),
                    "templates": {k: v[0].source for k, v in templates.items()}}


# --------------------------------------------------------------------------------------------------- entry point
def build_membrane_system(out_dir, membrane: dict, *, receptor_pdb=None, ligands=None, peptide_sequence: str | None = None,
                          peptide_name: str = "P01", decisions=None, **assemble_kw):
    """Entry point for all three membrane types (the workflow uses it through assemble_system for case A).

    protein   receptor_pdb (prepared receptor) and optional docked ligands
    surface   peptide_sequence (built with ETKDG, ff14SB) or ligands (LigandRecord list) with receptor_pdb=None
    bilayer   nothing but the membrane spec"""
    from .assemble import assemble_system, BuildResult
    ligs = list(ligands or [])
    if peptide_sequence:
        from .peptide import prepare_peptide
        out = Path(out_dir)
        prec = prepare_peptide(peptide_sequence, None, out / "ligands", name=peptide_name, chain_id="P", decisions=decisions)
        if prec.status == NEEDS_HUMAN:
            return BuildResult(status=NEEDS_HUMAN, gates=prec.gates)
        ligs.append(prec)
    return assemble_system(receptor_pdb, ligs, out_dir, membrane=membrane, decisions=decisions, **assemble_kw)
