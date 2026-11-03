"""Membrane analysis on coordinate arrays (pure numpy; docs/specs/membrane.md §6).

Everything takes nm and rectangular boxes (F, 3) so it works on any trajectory reader (mdtraj `xyz`,
`unitcell_lengths`).  The membrane normal is z (the build puts it there and the membrane barostat keeps it).

Shapes: F frames, N atoms.  Head atoms = lipid phosphorus (cholesterol O3), from build_manifest membrane.head_atom_indices.
"""
from __future__ import annotations

import math

import numpy as np

from ..build.gates import Gate, PASS, AUTO_FIXED, NEEDS_HUMAN

# labels for reports and figures (zh, en, ja, ko)
METRIC_LABELS = {
    "apl": ("每個脂質的面積", "Area per lipid", "脂質 1 分子あたりの面積", "지질당 면적"),
    "dpp": ("膜厚度（P–P）", "Bilayer thickness (P–P)", "膜の厚さ（P–P）", "막 두께(P–P)"),
    "density": ("沿膜法線的密度剖面", "Density profile along the membrane normal", "膜法線方向の密度分布",
                "막 법선 방향 밀도 분포"),
    "scd": ("氘序參數 S_CD", "Deuterium order parameter S_CD", "重水素秩序パラメータ S_CD", "중수소 질서 매개변수 S_CD"),
    "depth": ("插入深度（相對磷原子平面）", "Insertion depth (relative to the phosphate plane)",
              "挿入の深さ（リン原子面から）", "삽입 깊이(인 원자 평면 기준)"),
    "contacts": ("與頭基接觸的殘基", "Residues in contact with head groups", "頭部基と接触する残基", "머리 부분과 접촉하는 잔기"),
    "residence": ("停留時間", "Residence time", "滞在時間", "체류 시간"),
    "tilt": ("胜肽傾角", "Peptide tilt", "ペプチドの傾き", "펩타이드 기울기"),
    "core_water": ("疏水核心中的水", "Water in the hydrophobic core", "疎水性コア中の水", "소수성 중심부의 물"),
}


def _box(box, F: int) -> np.ndarray:
    b = np.asarray(box, float)
    if b.ndim == 1:
        b = np.tile(b, (F, 1))
    return b


def _mic(d: np.ndarray, L: np.ndarray) -> np.ndarray:
    """Minimum image for displacement d (..., k) and box lengths L broadcastable to d."""
    return d - L * np.round(d / L)


def membrane_centre(head_z, box) -> np.ndarray:
    """Per-frame membrane centre along z, robust to wrapping: circular mean of head z with period Lz."""
    z = np.asarray(head_z, float)
    if z.ndim == 1:
        z = z[None, :]
    Lz = _box(box, len(z))[:, 2]
    ang = 2 * np.pi * z / Lz[:, None]
    c = np.arctan2(np.sin(ang).mean(1), np.cos(ang).mean(1))
    # circular mean of the two leaflets lands on the centre or half a box away (the water layer); keep the centre
    # by taking the side where the heads are closest
    cand = np.stack([c, c + np.pi], 1) * Lz[:, None] / (2 * np.pi)
    spread = []
    for k in range(2):
        dz = _mic(z - cand[:, k:k + 1], Lz[:, None])
        spread.append(np.abs(dz).mean(1))
    pick = np.argmin(np.stack(spread, 1), 1)
    return cand[np.arange(len(z)), pick]


def relative_z(z, centre, box) -> np.ndarray:
    """z − centre with minimum image along z; z (F, N), centre (F,)."""
    z = np.asarray(z, float)
    Lz = _box(box, len(z))[:, 2]
    return _mic(z - np.asarray(centre)[:, None], Lz[:, None])


def leaflets(head_z, box) -> tuple[np.ndarray, np.ndarray]:
    """(upper mask from the first frame, centre per frame).  Flip-flop takes microseconds, so frame 0 decides."""
    c = membrane_centre(head_z, box)
    rz = relative_z(head_z, c, box)
    return rz[0] > 0, c


def thickness_pp(head_xyz, box) -> dict:
    """P–P thickness per frame: mean z of upper-leaflet heads minus lower-leaflet heads."""
    h = np.asarray(head_xyz, float)
    up, c = leaflets(h[..., 2], box)
    rz = relative_z(h[..., 2], c, box)
    d = rz[:, up].mean(1) - rz[:, ~up].mean(1)
    return {"dpp_nm": d, "mean_nm": float(d.mean()), "sd_nm": float(d.std()), "n_upper": int(up.sum()),
            "n_lower": int((~up).sum()), "centre_nm": c}


def area_per_lipid(box, n_upper: int, n_lower: int, *, protein_area_nm2=0.0) -> dict:
    """APL per frame = (Lx·Ly − protein cross-section) / lipids per leaflet (mean of the two leaflets).  With a protein
    the cross-section must be given (or the value is labelled approximate by the caller)."""
    b = np.asarray(box, float)
    b = b[None, :] if b.ndim == 1 else b
    area = b[:, 0] * b[:, 1] - np.asarray(protein_area_nm2, float)
    a = 0.5 * (area / n_upper + area / n_lower)
    return {"apl_nm2": a, "mean_nm2": float(a.mean()), "sd_nm2": float(a.std())}


def density_profile(z, box, centre, *, weights=None, bin_nm: float = 0.1, half_range_nm: float | None = None) -> dict:
    """Number (or weighted, e.g. mass in amu) density along the normal, relative to the membrane centre, averaged over
    frames: per nm³; with masses in amu use `to_g_cm3` on the result."""
    z = np.asarray(z, float)
    b = _box(box, len(z))
    rz = relative_z(z, centre, b)
    h = half_range_nm or float(b[:, 2].min() / 2)
    edges = np.arange(-h, h + bin_nm * 0.5, bin_nm)
    w = None if weights is None else np.broadcast_to(np.asarray(weights, float), rz.shape)
    acc = np.zeros(len(edges) - 1)
    for f in range(len(rz)):
        hist, _ = np.histogram(rz[f], bins=edges, weights=None if w is None else w[f])
        acc += hist / (b[f, 0] * b[f, 1] * bin_nm)
    return {"z_nm": 0.5 * (edges[1:] + edges[:-1]), "density_per_nm3": acc / len(rz)}


def to_g_cm3(amu_per_nm3) -> np.ndarray:
    return np.asarray(amu_per_nm3) * 1.66053906660e-24 / 1e-21


def scd_groups_from_names(atom_names, residue_ids) -> dict[str, list[tuple[int, int]]]:
    """C–H pairs of the acyl chains by CHARMM names (OpenMM's lipid patches and Lipid17/21 templates use them):
    sn-2 carbons C2n with hydrogens HnR/HnS/HnT, sn-1 carbons C3n with HnX/HnY/HnZ (n ≥ 2).  Returns
    {"sn1:C3n" | "sn2:C2n": [(c_index, h_index), ...]} over all lipids."""
    names = [str(a).upper() for a in atom_names]
    res = list(residue_ids)
    by_res: dict = {}
    for i, (n, r) in enumerate(zip(names, res)):
        by_res.setdefault(r, {})[n] = i
    out: dict[str, list[tuple[int, int]]] = {}
    for r, amap in by_res.items():
        for nm, ci in amap.items():
            if len(nm) < 3 or nm[0] != "C" or nm[1] not in "23" or not nm[2:].isdigit():
                continue
            k = int(nm[2:])
            if k < 2:
                continue
            tail = "sn2" if nm[1] == "2" else "sn1"
            suff = "RST" if tail == "sn2" else "XYZ"
            for s in suff:
                hi = amap.get(f"H{k}{s}")
                if hi is not None:
                    out.setdefault(f"{tail}:{nm}", []).append((ci, hi))
    return dict(sorted(out.items(), key=lambda kv: (kv[0][:3], int(kv[0][6:]))))


def order_parameter(xyz, pairs) -> float:
    """S_CD = ⟨(3 cos² θ − 1) / 2⟩ over frames and C–H pairs, θ = angle between C–H and z.  Fluid acyl chains give
    S_CD ≈ −0.1 to −0.25 on the plateau; usually reported as −S_CD."""
    x = np.asarray(xyz, float)
    p = np.asarray(pairs, int)
    v = x[:, p[:, 1], :] - x[:, p[:, 0], :]
    cos2 = v[..., 2] ** 2 / (v ** 2).sum(-1)
    return float(np.mean(1.5 * cos2 - 0.5))


def scd_profile(xyz, groups: dict) -> dict:
    return {k: order_parameter(xyz, v) for k, v in groups.items() if v}


def insertion_depth(solute_xyz, head_xyz, box, *, heavy_mask=None) -> dict:
    """Depth of the solute relative to the phosphate plane of the leaflet it sits on (per frame, nm):
    positive = below the P plane (inside the bilayer), negative = still in the water.  `com_depth` uses the heavy-atom
    centroid, `deepest` the deepest heavy atom.  Leaflet = side of the membrane centre the centroid is on."""
    s = np.asarray(solute_xyz, float)
    h = np.asarray(head_xyz, float)
    b = _box(box, len(s))
    up, c = leaflets(h[..., 2], b)
    rz_h = relative_z(h[..., 2], c, b)
    p_up, p_lo = rz_h[:, up].mean(1), rz_h[:, ~up].mean(1)
    m = np.ones(s.shape[1], bool) if heavy_mask is None else np.asarray(heavy_mask, bool)
    rz_s = relative_z(s[..., 2], c, b)[:, m]
    com = rz_s.mean(1)
    upper_side = com >= 0
    plane = np.where(upper_side, p_up, p_lo)
    sign = np.where(upper_side, 1.0, -1.0)
    com_depth = sign * (plane - com)
    deepest = np.where(upper_side, plane - rz_s.min(1), rz_s.max(1) - plane)
    return {"com_depth_nm": com_depth, "deepest_nm": deepest, "upper_side": upper_side,
            "mean_com_depth_nm": float(com_depth.mean()), "crossed_centre": bool(np.any(np.sign(com) != np.sign(com[0])))}


def headgroup_contacts(residue_xyz: list, head_xyz, box, *, cutoff_nm: float = 0.4) -> np.ndarray:
    """(F, R) bool: residue r has any atom within cutoff of any head atom (minimum image in x, y, z)."""
    h = np.asarray(head_xyz, float)
    b = _box(box, len(h))
    out = np.zeros((len(h), len(residue_xyz)), bool)
    for r, rx in enumerate(residue_xyz):
        rx = np.asarray(rx, float)
        for f in range(len(h)):
            d = _mic(rx[f][:, None, :] - h[f][None, :, :], b[f])
            out[f, r] = bool(((d ** 2).sum(-1) < cutoff_nm ** 2).any())
    return out


def residence_times(contact, dt_ps: float) -> list[dict]:
    """Per residue (column): contact fraction, number of contact events, mean and longest residence (ps).  An event
    still open at the last frame counts with its observed length (a lower bound)."""
    c = np.asarray(contact, bool)
    out = []
    for r in range(c.shape[1]):
        col = np.concatenate([[False], c[:, r], [False]]).astype(int)
        d = np.diff(col)
        starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
        lens = (ends - starts) * dt_ps
        out.append({"fraction": float(c[:, r].mean()), "events": int(len(lens)),
                    "mean_ps": float(lens.mean()) if len(lens) else 0.0, "max_ps": float(lens.max()) if len(lens) else 0.0,
                    "open_at_end": bool(c[-1, r]) if len(c) else False})
    return out


def helix_tilt(ca_xyz) -> np.ndarray:
    """Angle (degrees, 0–90) between the peptide's principal axis (Cα) and the membrane normal z, per frame.
    90° = lying flat on the surface."""
    x = np.asarray(ca_xyz, float)
    out = np.empty(len(x))
    for f in range(len(x)):
        X = x[f] - x[f].mean(0)
        _, _, vt = np.linalg.svd(X, full_matrices=False)
        out[f] = math.degrees(math.acos(min(1.0, abs(vt[0][2]))))
    return out


def water_in_core(o_xyz, centre, box, *, half_nm: float = 0.5, exclude_xyz=None, exclude_radius_nm: float = 0.6) -> np.ndarray:
    """Water oxygens within ±half_nm of the membrane centre per frame, not counting those within exclude_radius_nm
    (lateral) of `exclude_xyz` atoms (protein: water inside a channel or transporter pore is expected)."""
    o = np.asarray(o_xyz, float)
    b = _box(box, len(o))
    rz = relative_z(o[..., 2], centre, b)
    n = np.zeros(len(o), int)
    for f in range(len(o)):
        sel = np.abs(rz[f]) < half_nm
        if exclude_xyz is not None and sel.any():
            p = np.asarray(exclude_xyz, float)[f][:, :2]
            d = _mic(o[f][sel][:, None, :2] - p[None, :, :], b[f, :2])
            near = ((d ** 2).sum(-1) < exclude_radius_nm ** 2).any(1)
            n[f] = int((~near).sum())
        else:
            n[f] = int(sel.sum())
    return n


def protein_offset(belt_xyz, centre, box) -> np.ndarray:
    """|mean z of the protein's membrane-belt atoms − membrane centre| per frame (nm): a protein leaving the membrane."""
    x = np.asarray(belt_xyz, float)
    return np.abs(relative_z(x[..., 2], centre, box).mean(1))


# ---------------------------------------------------------------------------------------------- equilibration gate
APL_TOL = 0.06          # ± 6 % of the experimental area (short runs, 64–256 lipids per leaflet)
DPP_TOL_NM = 0.30       # ± 0.3 nm of the experimental head-to-head thickness
PROTEIN_OFFSET_NM = 1.0


def assess_equilibration(*, apl_nm2: float | None, dpp_nm: float | None, core_water: float, n_lipids: int,
                         reference: dict, protein_offset_nm: float | None = None, attempt: int = 0) -> Gate:
    """Membrane acceptance after NPT (spec §5).  All checks pass → PASS.  Any fails: first time → AUTO_FIXED with
    evidence action "extend_equilibration" (the caller extends NPT once); after an extension → NEEDS_HUMAN.
    A reference that is None (cholesterol, cardiolipin) skips that check and says so."""
    checks, notes = {}, []
    ra, rd = reference.get("apl_nm2"), reference.get("dpp_nm")
    if apl_nm2 is not None and ra:
        lo, hi = ra * (1 - APL_TOL), ra * (1 + APL_TOL)
        checks["apl"] = lo <= apl_nm2 <= hi
        notes.append(f"每脂質面積 {apl_nm2:.3f} nm²（範圍 {lo:.3f}–{hi:.3f}）")
    else:
        notes.append("每脂質面積未檢查（沒有參考值或含蛋白）")
    if dpp_nm is not None and rd:
        lo, hi = rd - DPP_TOL_NM, rd + DPP_TOL_NM
        checks["dpp"] = lo <= dpp_nm <= hi
        notes.append(f"P–P 厚度 {dpp_nm:.2f} nm（範圍 {lo:.2f}–{hi:.2f}）")
    else:
        notes.append("厚度未檢查（沒有參考值）")
    lim = max(1.0, 0.01 * n_lipids)
    checks["core_water"] = core_water <= lim
    notes.append(f"疏水核心平均 {core_water:.1f} 個水（上限 {lim:.0f}）")
    if protein_offset_nm is not None:
        checks["protein_in_membrane"] = protein_offset_nm <= PROTEIN_OFFSET_NM
        notes.append(f"蛋白疏水帶偏離膜中心 {protein_offset_nm:.2f} nm（上限 {PROTEIN_OFFSET_NM}）")
    ev = {"checks": checks, "apl_nm2": apl_nm2, "dpp_nm": dpp_nm, "core_water": core_water,
          "protein_offset_nm": protein_offset_nm, "reference": reference, "attempt": attempt}
    text = "；".join(notes) + "。"
    if all(checks.values()):
        return Gate("membrane equilibration", PASS, "膜平衡驗收通過：" + text, evidence=ev)
    failed = [k for k, v in checks.items() if not v]
    if attempt == 0:
        return Gate("membrane equilibration", AUTO_FIXED,
                    f"膜還沒平衡（未通過：{', '.join(failed)}），延長 NPT 平衡一次再檢查：" + text,
                    evidence={**ev, "action": "extend_equilibration"})
    return Gate("membrane equilibration", NEEDS_HUMAN,
                f"延長平衡後膜仍不合（未通過：{', '.join(failed)}）：" + text + "不當作已平衡的膜繼續。",
                options=["再延長平衡（md.stage_overrides.npt.length_ps）", "檢查脂質組成與溫度", "回報給老師"],
                evidence=ev)
