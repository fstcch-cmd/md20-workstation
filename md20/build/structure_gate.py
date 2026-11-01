"""WP6: is this crystal structure trustworthy *where we are going to dock*?  And are there metals in the pocket?

Reads only the PDB text (header REMARKs + ATOM/HETATM columns), so it is pure Python and fast.

Gates (each PASS / AUTO_FIXED / NEEDS_HUMAN, with a Chinese explanation):
  experiment      — X-ray / EM / NMR; NMR and predicted models get a warning.
  resolution      — ≤ 2.5 Å PASS, ≤ 3.2 Å warning, > 3.2 Å NEEDS_HUMAN.
  R-free          — ≤ 0.28 PASS, ≤ 0.32 warning, > 0.32 NEEDS_HUMAN.
  pocket B/occupancy — pocket residues with mean B > 80 Å² or occupancy < 1 → warning; > 30 % of pocket atoms
                    with occupancy < 0.5 → NEEDS_HUMAN (the pocket is not really resolved).
  co-crystal ligand occupancy — < 0.7 → NEEDS_HUMAN when it defines the box/redocking reference.
  biological assembly — REMARK 350 lists more chains than the asymmetric unit has, or the pocket is at a chain
                    interface → warning (the real pocket may need the partner chain).
  metal in pocket — Zn/Fe/Cu/Mn/Co/Ni (coordinating metals; nonbonded Amber models misplace them) within 6 Å of
                    the pocket → NEEDS_HUMAN unless `metal_policy` says how to treat it; Mg/Ca → warning.
"""
from __future__ import annotations

import re

import numpy as np

from .gates import Gate, GateReport, PASS, AUTO_FIXED, NEEDS_HUMAN

TRANSITION_METALS = {"ZN", "FE", "FE2", "CU", "CU1", "MN", "CO", "NI", "CD", "HG"}
ALKALINE_EARTH = {"MG", "CA", "SR", "BA"}


def _atoms(pdb_text: str):
    rows = []
    for l in pdb_text.splitlines():
        if l.startswith(("ATOM", "HETATM")) and len(l) >= 54:
            try:
                xyz = (float(l[30:38]), float(l[38:46]), float(l[46:54]))
            except ValueError:
                continue
            occ = float(l[54:60]) if l[54:60].strip() else 1.0
            b = float(l[60:66]) if l[60:66].strip() else 0.0
            rows.append({"rec": l[:6].strip(), "name": l[12:16].strip(), "resname": l[17:20].strip(), "chain": l[21],
                         "resseq": l[22:27].strip(), "xyz": xyz, "occ": occ, "b": b})
    return rows


def header_info(pdb_text: str) -> dict:
    info: dict = {"method": None, "resolution_A": None, "r_free": None, "biomt_chains": None}
    for l in pdb_text.splitlines():
        if l.startswith("EXPDTA"):
            info["method"] = l[10:].strip()
        elif l.startswith("REMARK   2 RESOLUTION."):
            m = re.search(r"([\d.]+)\s*ANGSTROM", l)
            if m:
                info["resolution_A"] = float(m.group(1))
        elif l.startswith("REMARK   3") and "FREE R VALUE" in l and "TEST" not in l and "ERROR" not in l:
            m = re.search(r":\s*([\d.]+)\s*$", l)
            if m and info["r_free"] is None:
                info["r_free"] = float(m.group(1))
        elif l.startswith("REMARK 350 APPLY THE FOLLOWING TO CHAINS:") and info["biomt_chains"] is None:
            info["biomt_chains"] = sorted({c.strip() for c in l.split(":", 1)[1].split(",") if c.strip()})
    return info


def structure_confidence(pdb_text: str, *, pocket_center=None, pocket_radius_A: float = 8.0,
                         ligand_resname: str | None = None, metal_policy: dict | None = None) -> GateReport:
    rep = GateReport()
    info = header_info(pdb_text)
    atoms = _atoms(pdb_text)
    method = (info["method"] or "").upper()
    if not method:
        rep.add(Gate("experiment", AUTO_FIXED, "檔案沒有 EXPDTA（可能是預測模型或處理過的檔案）；無法評估實驗品質，請確認來源。",
                     evidence=info))
    elif "NMR" in method:
        rep.add(Gate("experiment", AUTO_FIXED, "NMR 結構：口袋側鏈構形較不確定；建議比對多個 model 或改用晶體結構。", evidence=info))
    else:
        rep.add(Gate("experiment", PASS, f"實驗方法：{info['method']}。", evidence=info))
    r = info["resolution_A"]
    if r is not None:
        if r <= 2.5:
            rep.add(Gate("resolution", PASS, f"解析度 {r:.2f} Å。"))
        elif r <= 3.2:
            rep.add(Gate("resolution", AUTO_FIXED, f"解析度 {r:.2f} Å 偏低：側鏈位置與水分子較不可靠，對接排名的可信度下降。"))
        else:
            rep.add(Gate("resolution", NEEDS_HUMAN, f"解析度 {r:.2f} Å > 3.2 Å：口袋原子位置不足以支持對接結論。",
                         options=["換一個更高解析度的結構", "仍要使用（structure_override.resolution）"]))
    rf = info["r_free"]
    if rf is not None:
        if rf <= 0.28:
            rep.add(Gate("R-free", PASS, f"R-free {rf:.3f}。"))
        elif rf <= 0.32:
            rep.add(Gate("R-free", AUTO_FIXED, f"R-free {rf:.3f} 偏高：模型與實驗數據吻合度一般。"))
        else:
            rep.add(Gate("R-free", NEEDS_HUMAN, f"R-free {rf:.3f} > 0.32：模型可能有明顯錯誤。",
                         options=["換結構", "仍要使用（structure_override.r_free）"]))
    lig_atoms = [a for a in atoms if ligand_resname and a["resname"] == ligand_resname]
    if pocket_center is None and lig_atoms:
        pocket_center = np.mean([a["xyz"] for a in lig_atoms], axis=0)
    if lig_atoms:
        occ = float(np.mean([a["occ"] for a in lig_atoms]))
        if occ < 0.7:
            rep.add(Gate("ligand occupancy", NEEDS_HUMAN,
                         f"共晶配體 {ligand_resname} 平均 occupancy {occ:.2f} < 0.7：晶體中只部分存在，作為 box/redocking 參考不可靠。",
                         options=["換結構", "仍要使用（structure_override.ligand_occupancy）"]))
        else:
            rep.add(Gate("ligand occupancy", PASS, f"共晶配體 {ligand_resname} occupancy {occ:.2f}。"))
    if pocket_center is not None:
        c = np.asarray(pocket_center, dtype=float)
        prot = [a for a in atoms if a["rec"] == "ATOM"]
        near = [a for a in prot if np.linalg.norm(np.asarray(a["xyz"]) - c) <= pocket_radius_A]
        if near:
            mean_b = float(np.mean([a["b"] for a in near]))
            low_occ = sum(1 for a in near if a["occ"] < 0.5) / len(near)
            partial = sum(1 for a in near if a["occ"] < 1.0) / len(near)
            chains = sorted({a["chain"] for a in near})
            if low_occ > 0.3:
                rep.add(Gate("pocket occupancy", NEEDS_HUMAN, f"口袋 {len(near)} 個原子中 {low_occ:.0%} 的 occupancy < 0.5：口袋沒有被好好解出。",
                             options=["換結構", "仍要使用（structure_override.pocket）"]))
            elif mean_b > 80 or partial > 0.2:
                rep.add(Gate("pocket B-factor", AUTO_FIXED,
                             f"口袋平均 B {mean_b:.0f} Å²、部分佔據 {partial:.0%}：口袋柔性高，建議以 MD 檢驗 pose 穩定性。"))
            else:
                rep.add(Gate("pocket B-factor", PASS, f"口袋 {len(near)} 個原子，平均 B {mean_b:.0f} Å²。"))
            if len(chains) > 1:
                rep.add(Gate("assembly", AUTO_FIXED, f"口袋位於鏈 {', '.join(chains)} 交界：請保留所有相關鏈（不要只取單鏈）。"))
            # metals
            mp = metal_policy or {}
            for a in atoms:
                if a["rec"] != "HETATM":
                    continue
                rn = a["resname"].upper()
                if rn not in TRANSITION_METALS | ALKALINE_EARTH:
                    continue
                d = float(np.linalg.norm(np.asarray(a["xyz"]) - c))
                if d > pocket_radius_A + 6.0:
                    continue
                key = f"{rn}:{a['chain']}{a['resseq']}"
                if rn in TRANSITION_METALS and not mp.get(rn) and not mp.get(key):
                    rep.add(Gate("metal", NEEDS_HUMAN,
                                 f"口袋 {d:.1f} Å 處有金屬 {key}。Amber 非鍵結離子模型常讓過渡金屬配位跑掉、Vina 也不計配位；"
                                 f"直接模擬可能得到錯誤的結合模式。",
                                 options=["metal_policy: {" + rn + ": keep_nonbonded}（保留並加位置限制，報告標註）",
                                          "metal_policy: {" + rn + ": remove}（若金屬非功能必要）", "換一個系統"],
                                 evidence={"metal": key, "distance_A": round(d, 1)}))
                elif rn in TRANSITION_METALS:
                    rep.add(Gate("metal", AUTO_FIXED, f"金屬 {key} 依使用者設定：{mp.get(key) or mp.get(rn)}。"))
                else:
                    rep.add(Gate("metal", AUTO_FIXED, f"口袋附近有 {key}（{d:.1f} Å）；以非鍵結離子保留。"))
    if info["biomt_chains"]:
        au = sorted({a["chain"] for a in atoms if a["rec"] == "ATOM"})
        if set(info["biomt_chains"]) - set(au):
            rep.add(Gate("assembly", AUTO_FIXED, f"生物組裝（REMARK 350）包含檔案中沒有的鏈 {sorted(set(info['biomt_chains']) - set(au))}："
                         f"真實口袋可能由對稱複本組成，請檢查。"))
    return rep
