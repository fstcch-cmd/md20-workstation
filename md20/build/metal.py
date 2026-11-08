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
Coordinating waters: under `bonded` the first-shell crystal water is added back and bonded as a neutral TIP3P water
(D-133/D-139).  D-141: `metal_water_state` may ask for a hydroxide (OH-) instead — never decided automatically (X-ray
cannot see the proton) and never with invented charges: it needs fitted parameters (`site_water` block of
`metal_params`); without them the build stops at a NEEDS_HUMAN gate and writes the QM cluster input with the OH-.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from .gates import Gate, PASS, AUTO_FIXED, NEEDS_HUMAN

BONDED_POLICIES = ("bonded", "bonded_open")      # D-133: bonded keeps crystal coordinating waters; bonded_open does not
BONDED_METALS = {"ZN", "FE", "FE2", "CU", "CU1", "MN", "CO", "NI", "MG", "CA", "CD"}
# donor atoms (resname, atom) and the cutoff (Å) at which they count as coordinating
DONORS = {("HIS", "NE2"): "N", ("HIS", "ND1"): "N", ("CYS", "SG"): "S", ("ASP", "OD1"): "O", ("ASP", "OD2"): "O",
          ("GLU", "OE1"): "O", ("GLU", "OE2"): "O", ("MET", "SD"): "S", ("ASN", "OD1"): "O", ("GLN", "OE1"): "O",
          ("SER", "OG"): "O", ("THR", "OG1"): "O", ("TYR", "OH"): "O"}
HIS_NAMES = {"HIS", "HID", "HIE", "HIP"}
CYS_NAMES = {"CYS", "CYM", "CYX"}
CUTOFF_A = {"N": 2.45, "O": 2.6, "S": 2.6}
WATER = {"HOH", "WAT", "TIP3", "SOL"}
# D-139: first-shell metal–water(O) target distances (Å), Harding, Acta Cryst D 62:678 (2006) Table / Harding 2001;
# a crystal water is bonded to a `bonded` site only within target + WATER_SHELL_TOL_A (2.6 Å stays the detection
# cutoff for reporting).  CA II 3KS3: zinc water 1.90 Å (bonded), a second water at 2.57 Å (weak, not first shell)
WATER_TARGET_A = {"ZN": 2.09, "FE": 2.13, "FE2": 2.13, "CU": 2.00, "CU1": 2.00, "MN": 2.19, "CO": 2.09, "NI": 2.09,
                  "MG": 2.07, "CA": 2.39, "CD": 2.31}
WATER_SHELL_TOL_A = 0.25
# D-141: protonation state of the metal-bound water.  "water" (default, neutral TIP3P) | "hydroxide" (OH-, fitted params only)
WATER_STATES = ("water", "hydroxide")
HYDROXIDE_RESNAME = "OHM"
# LJ / bonded types of the hydroxide template: Amber ff14SB hydroxyl O and H of Ser/Thr/Tyr (same values as GAFF oh/ho).
# Only the *charges* come from the fitted parameters; the LJ type is an assumption stated in the report (docs §4e).
HYDROXIDE_ATOM_TYPES = {"O": "protein-OH", "H": "protein-HO"}


def water_bond_max_A(metal_resname: str) -> float:
    """Largest metal–O(water) distance (Å) treated as first-shell coordination for the bonded model."""
    return WATER_TARGET_A.get(str(metal_resname).upper(), 2.09) + WATER_SHELL_TOL_A
K_BOND = 2 * 46.0 * 4.184 * 100      # ZAFF-like Zn–N 46 kcal/mol/Å² → OpenMM ½k(r−r0)² in kJ/mol/nm²
K_ANGLE = 2 * 25.0 * 4.184           # 25 kcal/mol/rad² → kJ/mol/rad²
K_KEEP = 1000.0                      # kJ/mol/nm² position restraint for keep_nonbonded
K_ANGLE_MDX = 2 * 50.0 * 4.184       # metal–donor–neighbour angle (ZAFF/MCPB-like ~50 kcal/mol/rad²)
SCEE, SCNB = 1.2, 2.0                # Amber 1-4 scaling (electrostatics, LJ)


def policy_for(key: str, policy: dict | None) -> str | None:
    p = policy or {}
    return p.get(key) or p.get(key.split(":")[0])


def water_state_for(key: str, cfg: dict | None) -> str | None:
    """D-141: `metal_water_state` for a site (site key wins over the element); None = not set (default water, but
    then a `site_water` block in metal_params is a conflict that needs a human).  Returned lower-case, unvalidated."""
    v = policy_for(key, cfg)
    return None if v is None else str(v).strip().lower()


def is_site_water(resname: str) -> bool:
    return resname.upper() in WATER or resname.upper() == HYDROXIDE_RESNAME


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
            if is_site_water(a["resname"]):
                if el == "O" and d[j] <= CUTOFF_A["O"]:
                    waters.append({"index": a["index"], "name": a["name"], "resname": a["resname"], "chain": a["chain"],
                                   "resseq": a["resseq"], "element": "O", "distance_A": round(float(d[j]), 2)})
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


def _water_state_option(key: str, state: str) -> str:
    text = {"water": "維持中性 TIP3P 水，不改質子化狀態", "hydroxide": "確認改用氫氧根 OH⁻（需 metal_params 的 site_water 參數）"}[state]
    return "metal_water_state: {" + key + ": " + state + "}（" + text + "）"


OPT_QM_HYDROXIDE = "產生含氫氧根的 QM 小模型輸入（metal_qm 資料夾），自行擬合電荷與 M–O 鍵參數"
OPT_PROVIDE_SITE_WATER = "在 metal_params 提供 site_water 區塊（RESP 電荷與 M–O 鍵參數）"


def decide_water_mode(key: str, policy: str | None, state: str | None, params: dict | None) -> dict:
    """D-141 (pure): how the metal-bound water of a site is modelled → {"mode": "none"|"water"|"hydroxide",
    "block": site_water block | None, "problem": str | None, "options": [...], "caveat": str | None}.

    never decided automatically: hydroxide only when `metal_water_state` says so (X-ray cannot see the proton); a
    `site_water` block in metal_params while the state is unset is a conflict, not a decision."""
    from .metal_params import site_water_block
    out = {"mode": "none", "block": None, "problem": None, "options": [], "caveat": None}
    block, err = site_water_block(params) if params else (None, None)
    out["block"] = block
    if err:
        out.update(problem=f"讀取 metal_params 的 site_water 區塊失敗：{err}。",
                   options=["修正 metal_params 設定", _water_state_option(key, "water")])
        return out
    if state is not None and state not in WATER_STATES:
        out.update(problem=f"metal_water_state「{state}」不認得（可用 water / hydroxide）。",
                   options=[_water_state_option(key, "water")])
        return out
    if policy != "bonded":
        if state == "hydroxide":
            out.update(problem=f"metal_water_state 要求氫氧根，但 metal_policy 是「{policy}」：氫氧根是鍵結模型的第四個配位，"
                               "只在 metal_policy: bonded 下有意義（bonded_open 不加回配位水，keep_nonbonded 不建鍵）。",
                       options=["metal_policy: {" + key + ": bonded}（氫氧根需要鍵結模型）", _water_state_option(key, "water")])
        return out
    if state == "hydroxide":
        out["mode"] = "hydroxide"
        return out
    if block is not None and state is None:
        out.update(problem="metal_params 含氫氧根的 site_water 參數，但 metal_water_state 沒有指定。配位水是 H₂O 還是 OH⁻ "
                           "X 光看不到（質子不可見），程式不自動決定；請明確選擇。",
                   options=[_water_state_option(key, "hydroxide"), _water_state_option(key, "water")])
        return out
    if block is not None:
        out["caveat"] = "metal_params 內的 site_water 區塊未使用（metal_water_state 設為 water）。"
    out["mode"] = "none" if params else "water"
    return out


def hydroxide_template_xml(q_o: float, q_h: float, resname: str = HYDROXIDE_RESNAME) -> str:
    """D-141 (pure): OpenMM ForceField XML for a metal-bound hydroxide residue — O + one H, charges from the fitted
    parameters, atom types `protein-OH` / `protein-HO` (Amber ff14SB hydroxyl O/H: LJ and the O–H bond come from the
    force field; nothing else is invented).  The Residues-only XML is loaded into the ForceField with loadFile."""
    return ('<ForceField>\n <Residues>\n'
            f'  <Residue name="{resname}">\n'
            f'   <Atom name="O" type="{HYDROXIDE_ATOM_TYPES["O"]}" charge="{float(q_o)!r}"/>\n'
            f'   <Atom name="H1" type="{HYDROXIDE_ATOM_TYPES["H"]}" charge="{float(q_h)!r}"/>\n'
            '   <Bond atomName1="O" atomName2="H1"/>\n'
            '  </Residue>\n </Residues>\n</ForceField>\n')


def choose_hydroxide_h(metal_xyz, o_xyz, h_xyzs) -> int:
    """D-141 (pure): which of the (two) hydrogens Modeller put on the site water stays as the hydroxide H — the one
    with the larger M–O–H angle (pointing away from the metal).  No geometry is invented; the other H is deleted."""
    best, best_a = 0, -1.0
    for i, h in enumerate(h_xyzs):
        a = _angle(metal_xyz, o_xyz, h)
        if a > best_a:
            best, best_a = i, a
    return best


def plan_site(site: dict, policy: str | None, xyz_of: dict | None = None, params: dict | None = None,
              residue_atoms: dict | None = None, water_state: str | None = None) -> dict:
    """Decide what to do with one metal site → {status, action, bonds, angles, variants, gate, why}.

    `params` (metal_params spec for this site) replaces the crystal-geometry constants with fitted ones
    (see metal_params.py); it is only resolved when `xyz_of` is given (final pass on the edited topology).
    `water_state` (D-141, `metal_water_state` of this site: None | "water" | "hydroxide"): see decide_water_mode;
    the plan carries `water_mode` ("none" | "water" | "hydroxide") and, for a gate about the water state,
    `gate_name` ("metal water state <key>")."""
    key = site["key"]
    out = {"key": key, "metal_index": site["metal_index"], "policy": policy, "action": None, "bonds": [], "angles": [],
           "variants": {}, "caveats": [], "charges": {}, "source": "geometric"}
    if water_state == "hydroxide" and policy in (None, "keep_nonbonded"):
        # D-141: the user asked for a hydroxide on a site that gets no bonded model — say so instead of ignoring it
        wm = decide_water_mode(key, policy, water_state, None)
        out.update(status=NEEDS_HUMAN, gate_name=f"metal water state {key}", why=f"{key}：{wm['problem']}", options=wm["options"])
        return out
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
    if policy not in BONDED_POLICIES:
        out.update(status=NEEDS_HUMAN, why=f"{key}：未知的 metal_policy「{policy}」（可用 bonded / bonded_open / keep_nonbonded / remove）。")
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
    # D-133: under `bonded` a crystal water on the site (added back by apply_metal_policy) is bonded too, so the site
    # keeps its coordination number; `bonded_open` leaves the position open (the pre-D-133 model).
    # D-141: the water may instead be a hydroxide (`metal_water_state`), only with fitted parameters (site_water block)
    wm = decide_water_mode(key, policy, water_state, params)
    out["water_mode"] = wm["mode"]
    if wm["problem"]:
        out.update(status=NEEDS_HUMAN, gate_name=f"metal water state {key}", why=f"{key}：{wm['problem']}",
                   options=wm["options"], water_mode="none")
        return out
    mode, block = wm["mode"], wm["block"]
    wmax = water_bond_max_A(site.get("metal") or key.split(":")[0])
    first_shell = [w for w in site.get("waters") or [] if w.get("index") is not None and w["distance_A"] <= wmax]
    final_pass = bool(xyz_of)
    site_w = []
    if mode == "water":
        site_w = first_shell        # fitted params cover only the donors they were fitted on (mode "none" then)
    elif mode == "hydroxide" and final_pass:
        why_not = None
        if not first_shell:
            why_not = "晶體沒有第一配位殼的配位水可轉成氫氧根（程式不憑空放置氧原子）"
        elif len(first_shell) > 1:
            why_not = f"第一配位殼有 {len(first_shell)} 個水，無法決定哪一個是氫氧根"
        elif first_shell[0]["resname"].upper() != HYDROXIDE_RESNAME:
            why_not = "配位水尚未轉成氫氧根（缺氫原子的拓樸編輯未完成）"
        if why_not:
            out.update(status=NEEDS_HUMAN, gate_name=f"metal water state {key}", why=f"{key}：metal_water_state=hydroxide，但{why_not}。",
                       options=[_water_state_option(key, "water")])
            return out
        if block is None:
            out.update(status=NEEDS_HUMAN, gate_name=f"metal water state {key}", needs_water_params=True,
                       why=f"{key}：metal_water_state 要求配位水為氫氧根（OH⁻），但沒有擬合參數。X 光看不到質子，程式不自動決定質子化狀態；"
                           "OH⁻ 結合金屬的電荷與 M–O 鍵參數不在 amber14／OpenMM 樣板裡，程式不憑空設定。",
                       options=[_water_state_option(key, "water"), OPT_QM_HYDROXIDE, OPT_PROVIDE_SITE_WATER])
            return out
        site_w = first_shell
    bonds += [{"metal": site["metal_index"], "donor": w["index"], "r0_nm": round(w["distance_A"] / 10.0, 4), "k": K_BOND,
               "label": f"{w['resname']}{w['resseq']}:{w['name']}", "water": True,
               **({"hydroxide": True} if mode == "hydroxide" else {})} for w in site_w]
    cage = list(donors) + list(site_w)
    angles = []
    if xyz_of:
        mx = site["metal_xyz"]
        for i in range(len(cage)):
            for j in range(i + 1, len(cage)):
                a, b = cage[i], cage[j]
                angles.append({"a": a["index"], "metal": site["metal_index"], "b": b["index"],
                               "theta0_deg": round(_angle(xyz_of[a["index"]], mx, xyz_of[b["index"]]), 2), "k": K_ANGLE})
    geom = {3: "三配位", 4: "四配位", 5: "五配位", 6: "六配位"}.get(len(cage), f"{len(cage)} 配位")
    caveats = ["鍵結模型為晶體幾何的諧和鍵與角（非擬合的 MCPB.py/ZAFF 參數）；電荷沿用力場。金屬被當成與配位原子共價相連："
               "1-2、1-3 非鍵結作用排除、1-4 依 Amber 縮放（靜電 ÷1.2、LJ ÷2），並加金屬–配位原子–鄰原子角項固定環的朝向。"]
    fitted = ""
    if params and xyz_of:
        from .metal_params import resolve_site_params
        rsite = site
        if mode == "hydroxide":                       # the hydroxide O is one more fitted partner of the metal
            w = site_w[0]
            hidx = ((residue_atoms or {}).get(f"{w['chain']}:{w['resseq']}") or {}).get("H1")
            rsite = {**site, "donors": list(donors) + [{**w, "is_site_water": True}],
                     "site_water": {"o_index": w["index"], "h_index": hidx, "block": block}}
        fp = resolve_site_params(rsite, params, xyz_of, residue_atoms=residue_atoms)
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
        if mode == "hydroxide":
            sw = fp["site_water"]
            out["site_water"] = {**sw, "resname": HYDROXIDE_RESNAME,
                                 "template_xml": hydroxide_template_xml(sw["q_O"], sw["q_H"])}
            caveats.append(
                f"金屬配位水依使用者指定（metal_water_state）以氫氧根 OH⁻ 建模（殘基 {HYDROXIDE_RESNAME}，淨電荷 −1）：X 光看不到質子，"
                f"程式沒有自動判斷（CA II 鋅水 pKa ≈ 7）。O／H 電荷 {sw['q_O']:+.3f}／{sw['q_H']:+.3f} 與 M–O 鍵來自擬合參數；"
                f"LJ 與 O–H 鍵沿用 Amber ff14SB 羥基型態（{HYDROXIDE_ATOM_TYPES['O']}／{HYDROXIDE_ATOM_TYPES['H']}，未擬合）。"
                + ("M–O–H 角使用擬合參數。" if sw.get("moh_angle") else "沒有 M–O–H 角項（參數未提供），氫可自由轉動。"))
    elif params and not xyz_of:
        out["source"] = "pending"            # resolved on the final pass
    if wm.get("caveat"):
        caveats.append(wm["caveat"])
    if site_w and mode == "water":
        caveats.append(f"晶體中的 {len(site_w)} 個配位水保留並以鍵結項連到金屬（中性 TIP3P 水，不是氫氧根；"
                       "鋅水的質子化狀態依 pKa 可能不同，X 光看不到質子，報告標註；要改成 OH⁻ 見 metal_water_state，需擬合參數）。"
                       "這是為了讓配位數與晶體一致，避免開放位點被附近帶負電基團佔據（D-133）。")
    elif policy == "bonded_open":
        caveats.append("bonded_open：配位水不加回，該配位位置開放；附近帶負電的基團可能塌陷到金屬上（D-133 診斷），只在配體要佔該位置時使用。")
    elif len(donors) < 4 and not site_w:
        caveats.append(f"只有 {len(donors)} 個配位原子且晶體沒有記錄配位水：開放位點可能被溶劑水、配體或附近帶負電基團佔據。")
    out.update(status=AUTO_FIXED, action="bonded", bonds=bonds, angles=angles, variants=variants, caveats=caveats,
               why=f"{key} 依使用者設定建立鍵結模型：{geom}（" + "、".join(b["label"] + f" {b['r0_nm'] * 10:.2f} Å" for b in bonds)
                   + "）" + (f"；配位殘基質子化改為 " + "、".join(f"{k}→{v}" for k, v in variants.items()) if variants else "")
                   + "（配位的 Cys 去質子化、His 以未配位的氮帶氫）。" + fitted)
    return out


def ligand_metal_contacts(atoms: list[dict], ligand_indices: set[int]) -> list[dict]:
    """Ligand N/O/S within coordination distance of a metal, checked on the *assembled* topology (REVIEW #15:
    metal sites were analysed before ligands were added, so a docked pose binding a metal was never stopped)."""
    lig = [a for a in atoms if a["index"] in ligand_indices]
    out = []
    for m in atoms:
        if m["resname"].upper() not in BONDED_METALS or m.get("is_protein") or m["index"] in ligand_indices:
            continue
        mx = np.asarray(m["xyz"], float)
        for a in lig:
            el = (a.get("element") or a["name"][:1]).upper()[:1]
            if el not in CUTOFF_A:
                continue
            d = float(np.linalg.norm(np.asarray(a["xyz"], float) - mx))
            if d <= CUTOFF_A[el]:
                out.append({"metal": f"{m['resname'].upper()}:{m['chain']}{m['resseq']}", "ligand_resname": a["resname"],
                            "atom": a["name"], "element": el, "distance_A": round(d, 2),
                            "metal_index": int(m["index"]), "atom_index": int(a["index"])})
    return out


LM_FLAT_NM = 0.025          # ± 0.25 Å around the docked distance: no force
LM_K = 5000.0               # kJ/mol/nm² outside the flat region


def ligand_metal_gate(contacts: list[dict], policy: str | None = None) -> Gate | None:
    if not contacts:
        return None
    if policy == "restrain":
        desc = "、".join(f"{c['ligand_resname']}:{c['atom']}–{c['metal']} {c['distance_A']:.2f} Å" for c in contacts[:6])
        return Gate("ligand–metal coordination", AUTO_FIXED,
                    f"配體直接配位金屬（{desc}）：依使用者選擇以平底距離約束維持對接時的配位距離（± {LM_FLAT_NM * 10:.2f} Å 內零力，"
                    f"外側 {LM_K:.0f} kJ mol⁻¹ nm⁻²），全程開啟。這是幾何後備，不是配位化學參數：配位能不在力場中，"
                    "所以這個配體的結合自由能不計算，MD 只用來看其餘部分的接觸與蛋白反應（報告標註）。",
                    diff=[f"{c['ligand_resname']}:{c['atom']} – {c['metal']}: {c['distance_A']:.2f} Å" for c in contacts],
                    evidence={"contacts": contacts})
    metals = sorted({c["metal"] for c in contacts})
    rn = metals[0].split(":")[0]
    desc = "、".join(f"{c['ligand_resname']}:{c['atom']}–{c['metal']} {c['distance_A']:.2f} Å" for c in contacts[:6])
    return Gate("ligand–metal coordination", NEEDS_HUMAN,
                f"配體直接配位金屬（{desc}）。力場沒有配體–金屬鍵參數：非鍵結模型下配位會散開或塌陷，"
                "Vina 也不計配位能；這個結合模式的 MD 與結合自由能都不可信，不自動處理。",
                options=["換一個不直接配位金屬的 pose（pose 表點選）",
                         "ligand_metal: restrain（以距離約束維持配位，報告標註；此配體不計算結合自由能）",
                         "以 MCPB.py/QM 參數化配體–金屬鍵後匯入（metal_params）",
                         "metal_policy: {" + rn + ": remove}（僅限金屬非功能必要）"],
                evidence={"contacts": contacts, "metals": metals})


def add_ligand_metal_restraints(system, contacts: list[dict], *, periodic: bool = True) -> list[dict]:
    """Flat-bottom distance restraints that keep each ligand donor at its docked distance from the metal (D-53)."""
    import openmm as mm
    f = mm.CustomBondForce("k_lm*(step(r-hi)*(r-hi)^2 + step(lo-r)*(lo-r)^2)")
    f.setName("msw_ligand_metal")
    f.addGlobalParameter("k_lm", LM_K)
    f.addPerBondParameter("lo")
    f.addPerBondParameter("hi")
    f.setUsesPeriodicBoundaryConditions(bool(periodic))
    out = []
    for c in contacts:
        d = c["distance_A"] / 10.0
        f.addBond(int(c["metal_index"]), int(c["atom_index"]), [max(0.0, d - LM_FLAT_NM), d + LM_FLAT_NM])
        out.append({**c, "lo_nm": round(max(0.0, d - LM_FLAT_NM), 4), "hi_nm": round(d + LM_FLAT_NM, 4)})
    system.addForce(f)
    return out


def site_water_ligand_gate(plans: list[dict], positions_nm, ligand_indices: list[int], min_nm: float = 0.22) -> Gate | None:
    """D-133: a bonded site water (crystal) that a docked ligand overlaps → NEEDS_HUMAN.  The ligand probably
    displaces that water (e.g. a zinc-binding group); keeping both would be a clash, dropping the water silently
    would be a guess."""
    if not ligand_indices:
        return None
    pos = np.asarray(positions_nm, float)
    lig = pos[np.asarray(ligand_indices, int)]
    hits = []
    for p in plans:
        for b in p.get("bonds") or []:
            if b.get("water"):
                d = float(np.min(np.linalg.norm(lig - pos[b["donor"]], axis=1)))
                if d < min_nm:
                    hits.append((p["key"], b["label"], d))
    if not hits:
        return None
    what = "、".join(f"{k} {lab}（配體原子距 {d * 10:.1f} Å）" for k, lab, d in hits)
    return Gate("metal site water vs ligand", NEEDS_HUMAN,
                f"對接配體與金屬位點保留的晶體配位水重疊：{what}。配體可能取代了這個水（例如直接配位金屬），"
                "兩者都保留會碰撞，自動刪水則是猜測。",
                options=["metal_policy: {" + hits[0][0] + ": bonded_open}（不加回配位水；配體若直接配位金屬仍需另外參數化）",
                         "改選其他 pose（pose 表）", "metal_policy: {" + hits[0][0] + ": keep_nonbonded}"],
                evidence={"hits": [{"site": k, "water": lab, "min_distance_nm": round(d, 3)} for k, lab, d in hits]})


def site_gates(plans: list[dict]) -> list[Gate]:
    return [Gate(p.get("gate_name") or f"metal {p['key']}", p["status"], p["why"], options=p.get("options") or [],
                 evidence={"action": p["action"], "n_bonds": len(p["bonds"]), "variants": p["variants"],
                           "source": p.get("source", "geometric"), "water_mode": p.get("water_mode"),
                           **(p.get("evidence") or {})}) for p in plans]


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


def site_waters_to_add(sites: list[dict], plans: list[dict], waters: list[dict], metal_params: dict | None = None,
                       cutoff_A: float | None = None) -> list[dict]:
    """D-133 (pure): which sidecar crystal waters (metal_site_waters.pdb records {resname, resseq, xyz (Å)}) go back
    into the model — only for a site whose policy is exactly `bonded` with no fitted parameters, and only waters
    within the O cutoff of that metal.  Each water is returned once with the metal key it serves.
    D-141: a site whose plan has `water_mode == "hydroxide"` gets its water back as well (also with fitted
    parameters — they carry the `site_water` block; without it the build writes the QM input and stops); the record
    carries `state` ("water" | "hydroxide") so the topology edit knows which to convert."""
    out, used = [], set()
    for s, p in zip(sites, plans):
        if p.get("policy") != "bonded" or p.get("action") != "bonded":
            continue
        mode = p.get("water_mode") or "water"
        if mode == "none" or (policy_for(s["key"], metal_params) and mode != "hydroxide"):
            continue
        cut = water_bond_max_A(s.get("metal") or s["key"].split(":")[0]) if cutoff_A is None else cutoff_A
        for k, w in enumerate(waters):
            if k in used:
                continue
            if float(np.linalg.norm(np.asarray(w["xyz"], float) - np.asarray(s["metal_xyz"], float))) <= cut:
                used.add(k)
                out.append({**w, "metal_key": s["key"], "chain": s.get("chain") or (s["key"].split(":")[1][:1] if ":" in s["key"] else "A"),
                            "state": "hydroxide" if mode == "hydroxide" else "water"})
    return out


def read_site_waters(path) -> list[dict]:
    """Records of metal_site_waters.pdb (receptor.prepare_receptor, D-133): O atoms only."""
    out = []
    from pathlib import Path as _P
    if not path or not _P(path).is_file():
        return out
    for line in _P(path).read_text(encoding="ascii", errors="replace").splitlines():
        if line.startswith("HETATM") and len(line) >= 54:
            try:
                out.append({"resname": line[17:20].strip() or "HOH", "resseq": line[22:26].strip(),
                            "xyz": (float(line[30:38]), float(line[38:46]), float(line[46:54]))})
            except ValueError:
                continue
    return out


def _find_residue(topology, chain_id: str, resid: str, name: str | None = None):
    for r in topology.residues():
        if r.chain.id == chain_id and str(r.id) == str(resid) and (name is None or r.name == name):
            return r
    return None


def convert_waters_to_hydroxide(modeller, waters: list[dict], metal_xyz_A: dict) -> list[str]:
    """D-141: the added site waters whose state is "hydroxide" lose one hydrogen (the one pointing at the metal, see
    choose_hydroxide_h) and become residue OHM with atoms O, H1.  Returns problems (empty when all converted)."""
    from openmm import unit
    problems, done = [], []
    for w in waters:
        r = _find_residue(modeller.topology, w["chain"], w["resseq"], "HOH")
        hs = [a for a in r.atoms() if a.element is not None and a.element.symbol == "H"] if r is not None else []
        o = next((a for a in r.atoms() if a.name == "O"), None) if r is not None else None
        if r is None or o is None or len(hs) != 2:
            problems.append(f"{w['metal_key']}：找不到配位水 {w['chain']}:{w['resseq']} 或它的氫原子不是 2 個，無法轉成氫氧根")
            continue
        pos = np.asarray(modeller.positions.value_in_unit(unit.nanometer)) * 10.0
        keep = choose_hydroxide_h(metal_xyz_A[w["metal_key"]], pos[o.index], [pos[h.index] for h in hs])
        modeller.delete([hs[1 - keep]])
        done.append(w)
    for w in done:
        r = _find_residue(modeller.topology, w["chain"], w["resseq"], "HOH")
        r.name = HYDROXIDE_RESNAME
        for a in r.atoms():
            if a.name != "O":
                a.name = "H1"
    return problems


def register_hydroxide_template(forcefield, xml: str, path=None) -> str | None:
    """D-141: load the OHM residue template into the ForceField (before createSystem — Modeller.addSolvent builds a
    System too).  Returns an error text, or None.  Checks the Amber hydroxyl atom types exist first."""
    types = getattr(forcefield, "_atomTypes", None)
    if types is not None:
        missing = [t for t in HYDROXIDE_ATOM_TYPES.values() if t not in types]
        if missing:
            return f"力場沒有羥基原子型態 {missing}，無法建立氫氧根樣板"
    try:
        if path is not None:
            from pathlib import Path as _P
            _P(path).parent.mkdir(parents=True, exist_ok=True)
            _P(path).write_text(xml, encoding="utf-8")
            forcefield.loadFile(str(path))
        else:
            import io
            forcefield.loadFile(io.StringIO(xml))
    except Exception as exc:  # noqa: BLE001  (bad XML / unknown type: report, never guess)
        return f"載入氫氧根樣板失敗：{exc}"
    return None


def apply_metal_policy(modeller, forcefield, policy: dict | None, *, ph: float = 7.4,
                       metal_params: dict | None = None, qm_dir=None, site_waters=None,
                       water_state: dict | None = None) -> list[dict]:
    """Edit the receptor Modeller in place (remove metals / reprotonate coordinating residues) and return the
    final per-site plans with indices valid for the edited topology (ligands/solvent are appended later,
    so receptor indices stay valid in the assembled system).  `water_state` = `metal_water_state` (D-141)."""
    import numpy as np  # noqa: F811
    from openmm import unit

    def snapshot():
        pos = np.asarray(modeller.positions.value_in_unit(unit.nanometer))
        atoms = _atoms_of(modeller.topology, pos)
        sites = find_sites(atoms)
        return atoms, sites

    def plan_for(s, xyz_of=None, residue_atoms=None):
        return plan_site(s, policy_for(s["key"], policy), xyz_of, params=policy_for(s["key"], metal_params),
                         residue_atoms=residue_atoms, water_state=water_state_for(s["key"], water_state))

    atoms, sites = snapshot()
    if not sites:
        return []
    plans = [plan_for(s) for s in sites]
    if any(p["status"] == NEEDS_HUMAN for p in plans):
        return plans
    # 1) removals
    rm = {sites[i]["metal_index"] for i, p in enumerate(plans) if p["action"] == "remove"}
    if rm:
        modeller.delete([a for a in modeller.topology.atoms() if a.index in rm])
    # 1b) D-133: crystal waters coordinating a `bonded` site go back in (O only; hydrogens added in step 2)
    added_w = []
    if site_waters:
        atoms, sites = snapshot()
        plans = [plan_for(s) for s in sites]
        added_w = site_waters_to_add(sites, plans, read_site_waters(site_waters) if not isinstance(site_waters, list)
                                     else site_waters, metal_params)
        if added_w:
            from openmm import app, Vec3
            wt = app.Topology()
            for w in added_w:
                ch = wt.addChain(w["chain"])
                r = wt.addResidue("HOH", ch, id=str(w["resseq"]))
                wt.addAtom("O", app.element.oxygen, r)
            modeller.add(wt, [Vec3(*[c / 10.0 for c in w["xyz"]]) for w in added_w] * unit.nanometer)
    # 2) reprotonation of coordinating residues (delete their H, re-add with explicit variants everywhere)
    want = {k: v for p in plans if p["action"] == "bonded" for k, v in p["variants"].items()}
    convert_problems: list[str] = []
    if want or added_w:
        res_of = {f"{r.chain.id}:{r.id}": r for r in modeller.topology.residues()}
        modeller.delete([a for k in want if k in res_of for a in res_of[k].atoms()
                         if a.element is not None and a.element.symbol == "H"])
        variants = []
        for r in modeller.topology.residues():
            k = f"{r.chain.id}:{r.id}"
            variants.append(want.get(k) or residue_variant(r.name, {a.name for a in r.atoms()}))
        modeller.addHydrogens(forcefield, pH=ph, variants=variants)
        # 2b) D-141: hydroxide state → one H of that water goes, the residue becomes OHM (template registered below)
        hyd = [w for w in added_w if w.get("state") == "hydroxide"]
        if hyd:
            convert_problems = convert_waters_to_hydroxide(modeller, hyd, {s_["key"]: s_["metal_xyz"] for s_ in sites})
    # 3) final plans on the edited topology (indices + angles)
    atoms, sites = snapshot()
    xyz_of = {a["index"]: a["xyz"] for a in atoms}
    residue_atoms = {}
    for r in modeller.topology.residues():
        residue_atoms[f"{r.chain.id}:{r.id}"] = {a.name: a.index for a in r.atoms()}
    final = [plan_for(s, xyz_of, residue_atoms) for s in sites]
    for p in final:
        if p["action"] == "bonded":
            p["variants"] = {k: v for k, v in want.items() if k in p["variants"]} or p["variants"]
    if convert_problems:
        for p in final:
            if p.get("water_mode") == "hydroxide" and p["action"] == "bonded":
                p.update(status=NEEDS_HUMAN, action=None, gate_name=f"metal water state {p['key']}",
                         why=f"{p['key']}：" + "；".join(convert_problems) + "。",
                         options=[_water_state_option(p["key"], "water")])
    # 3b) D-141: register the OHM template from the fitted charges before anything builds a System
    for s_, p in zip(sites, final):
        sw = p.get("site_water")
        if not sw or p["action"] != "bonded":
            continue
        tpl_path = (Path(qm_dir) / s_["key"].replace(":", "_") / "hydroxide_template.xml") if qm_dir is not None else None
        err = register_hydroxide_template(forcefield, sw["template_xml"], tpl_path)
        if err:
            p.update(status=NEEDS_HUMAN, action=None, gate_name=f"metal water state {p['key']}", why=f"{p['key']}：{err}。",
                     options=[_water_state_option(p["key"], "water")])
        elif tpl_path is not None:
            sw["template_file"] = str(tpl_path)
    # QM small-model input: geometric bonded sites (so the student can upgrade to fitted parameters) and, D-141, the
    # hydroxide site that stopped for lack of parameters (the cluster then carries the OH-)
    if qm_dir is not None:
        from .metal_params import write_qm_cluster
        for s_, p in zip(sites, final):
            geometric = p["action"] == "bonded" and p.get("source") == "geometric"
            need_oh = bool(p.get("needs_water_params"))
            if not (geometric or need_oh):
                continue
            spec = policy_for(s_["key"], metal_params) or {}
            wl = _qm_waters(s_, p, atoms, "hydroxide" if need_oh else "water")
            sub = s_["key"].replace(":", "_") + ("_hydroxide" if need_oh else "")
            qm = write_qm_cluster(atoms, s_, Path(qm_dir) / sub, charge=spec.get("qm_charge"),
                                  multiplicity=spec.get("qm_multiplicity"), waters=wl)
            p["qm_input"] = qm
            if need_oh:
                p.setdefault("evidence", {})["qm_input_dir"] = str(Path(qm_dir) / sub) if qm["status"] == "PASS" else None
                p["why"] += (f" 已把含氫氧根的 QM 小模型輸入寫到 {Path(qm_dir) / sub}（見 README.md）。" if qm["status"] == "PASS"
                             else " 未能產生含氫氧根的 QM 小模型輸入：" + qm["why"])
            elif qm["status"] == "PASS":
                p["caveats"].append(f"可升級：QM 小模型輸入已寫到 {Path(qm_dir) / sub}（見 README.md）。"
                                    + ("輸入含配位水（H₂O）。" if wl else ""))
            else:
                p["caveats"].append("未產生 QM 小模型輸入：" + qm["why"])
    return final


def _qm_waters(site: dict, plan: dict, atoms: list[dict], state: str) -> list[dict]:
    """The site waters that go into the QM cluster: the bonded water of a water-mode plan, or (hydroxide state without
    parameters) the first-shell water of the site — as {"rid": "chain:resseq", "state"}."""
    out, seen = [], set()
    by_index = {a["index"]: a for a in atoms}
    if plan.get("needs_water_params"):
        wmax = water_bond_max_A(site.get("metal") or site["key"].split(":")[0])
        idxs = [w["index"] for w in site.get("waters") or [] if w.get("index") is not None and w["distance_A"] <= wmax]
    else:
        idxs = [b["donor"] for b in plan.get("bonds") or [] if b.get("water")]
    for i in idxs:
        a = by_index.get(i)
        if a is None:
            continue
        rid = f"{a['chain']}:{a['resseq']}"
        if rid not in seen:
            seen.add(rid)
            out.append({"rid": rid, "state": state})
    return out


MOH_THETA0_DEG = (360.0 - 104.52) / 2.0     # D-145: geometric default M–O–H angle for a bonded site water


def bonded_metal_terms(bonds: list[tuple[int, int]], plans: list[dict], positions_nm) -> dict:
    """Topology terms that make a metal behave as covalently bound to its donors (pure Python).

    Treating M–D as a bond means, exactly as for any bonded pair in Amber: M–D (1-2) and M–X with X bonded to D
    (1-3) have no nonbonded interaction, M–Y with Y two bonds from D (1-4) is scaled, and the M–D–X angles keep
    the donor group pointing at the metal.  Without 1-3 exclusion the +2 metal sits ~3 Å from the donor's
    neighbours (e.g. His CE1/CD2 and their hydrogens) and is pushed off its site (CI: Zn–NE2 2.03 → 2.56 Å).
    The same bookkeeping runs *through* the metal, as tleap/MCPB.py do once M–D bonds exist: two donors of the
    same metal are a 1-3 pair (D–M–D′, excluded) and a donor with the neighbour of another donor is 1-4
    (D–M–D′–X′, scaled).  Without that, the three His NE2 (≈ −0.5 e each, 3.3 Å apart) repel at full strength
    while the D–M–D′ angle term tries to hold them — the Zn–N bonds stretch.
    D-141/D-145: every bonded site-water H gets an M–O–H angle: the fitted one for a hydroxide when given
    (`site_water.moh_angle`) → "angles_moh": [(m, o, h, θ0 rad, k)]; otherwise (D-145) the geometric default 127.7°.
    Returns {"excl13": [(a, b)], "pairs14": [(a, b)], "angles": [(m, d, x, θ0 rad)]} with no duplicates, plus
    "angles_moh" only when there is such an angle."""
    import numpy as np  # noqa: F811
    nbr: dict[int, set[int]] = {}
    for a, b in bonds:
        nbr.setdefault(a, set()).add(b); nbr.setdefault(b, set()).add(a)
    pos = np.asarray(positions_nm, float)
    excl12, excl13, pairs14, angles, angles_moh = set(), set(), set(), [], []
    for p in plans:
        if p.get("action") != "bonded":
            continue
        m = p["metal_index"]
        donors = {b["donor"] for b in p["bonds"]}
        excl12 |= {(m, d) for d in donors}
        dl = sorted(donors)
        waters = {b["donor"] for b in p["bonds"] if b.get("water")}
        for i, d in enumerate(dl):                       # through-metal pairs: D–M–D′ (1-3) and D–M–D′–X′ (1-4)
            for d2 in dl[i + 1:]:
                excl13.add((d, d2))
            for d2 in dl:
                if d2 == d:
                    continue
                for x2 in nbr.get(d2, ()):
                    if x2 != m and x2 not in donors and x2 != d and x2 not in nbr.get(d, ()):
                        if d2 in waters:
                            # D-145: a site-water H has no LJ (TIP3P); with D–O(water) already a 1-3 exclusion
                            # nothing repels it from the other donors, so a scaled 1-4 Coulomb pair is purely
                            # attractive and collapses (CI 6c85bde: NaN in the first 2 ps) — excluded instead
                            excl13.add((min(d, x2), max(d, x2)))
                        else:
                            pairs14.add((min(d, x2), max(d, x2)))
        moh = (p.get("site_water") or {}).get("moh_angle")
        o_idx = (p.get("site_water") or {}).get("o_index")
        for d in donors:
            for x in nbr.get(d, ()):
                if x == m or x in donors:
                    continue
                excl13.add((m, x))
                if d in waters:
                    # D-145: an M–O–H angle keeps each water H off the metal side (fitted value for a hydroxide when
                    # given, D-141; otherwise the geometric default (360° − 104.52°)/2 = 127.7°: metal and the two
                    # H trigonal around O).  Without it the H swung onto a His N (CI 6c85bde NaN).
                    if moh and d == o_idx:
                        angles_moh.append((m, d, x, math.radians(moh["theta0_deg"]), moh["k"]))
                    else:
                        angles_moh.append((m, d, x, math.radians(MOH_THETA0_DEG), K_ANGLE_MDX))
                    continue
                u, v = pos[m] - pos[d], pos[x] - pos[d]
                th = float(np.arccos(np.clip(np.dot(u, v) / np.linalg.norm(u) / np.linalg.norm(v), -1.0, 1.0)))
                angles.append((m, d, x, th))
                for y in nbr.get(x, ()):
                    if y not in (d, m) and y not in donors:
                        pairs14.add((m, y))
    # pairs that are already 1-2/1-3 inside the protein topology (e.g. bidentate carboxylate O–O) stay as the
    # force field has them; never *add* a scaled 1-4 where a closer relation exists
    bonded12 = {(min(a, b), max(a, b)) for a, b in bonds}
    bonded13 = {(min(a, c), max(a, c)) for b_, ns in nbr.items() for a in ns for c in ns if a < c}
    norm = lambda pairs: {(min(a, b), max(a, b)) for a, b in pairs}  # noqa: E731
    excl12n, excl13n = norm(excl12), norm(excl13) - norm(excl12) - bonded12 - bonded13
    pairs14n = norm(pairs14) - excl12n - excl13n - bonded12 - bonded13
    out = {"excl13": sorted(excl13n), "pairs14": sorted(pairs14n), "angles": angles}
    if angles_moh:
        out["angles_moh"] = angles_moh
    return out


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
            for m, d, x, th, k in terms.get("angles_moh", []):
                ha.addAngle(m, d, x, th, k)
            info.update(exclusions_13=len(terms["excl13"]), scaled_14=len(terms["pairs14"]), angles_mdx=len(terms["angles"]),
                        angles_moh=len(terms.get("angles_moh", [])))
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

