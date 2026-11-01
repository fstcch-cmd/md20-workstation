"""Peptide ligands: protein force field, independent chain, never merged into the receptor backbone.

Why a separate path (brief S1): a docked peptide written as ATOM records with standard residue names is
indistinguishable from a receptor chain; PDBFixer/Modeller may join it to the receptor (same chain ID or
consecutive numbering) or "repair" the gap between them as a missing loop.  Peptides therefore:

* are identified explicitly (user-supplied sequence) or detected and *stopped* (no sequence → NEEDS_HUMAN);
* get ff14SB parameters (same force field as the receptor), not OpenFF/GAFF;
* get their own chain ID (never used by the receptor), residues renumbered from 1, TER, chosen termini;
* pass a topology gate after assembly: no bond between receptor and peptide, one chain per peptide.

Also contains the CPP (cell-penetrating peptide) gate (brief S10): prediction is never reported as validation.
"""
from __future__ import annotations

import math
import re
import string
from dataclasses import dataclass, field, asdict
from pathlib import Path

from ..util import DecisionLog
from .gates import Gate, GateReport, PASS, AUTO_FIXED, NEEDS_HUMAN

AA1 = set("ACDEFGHIKLMNPQRSTVWY")
BACKBONE_2RES = "[NX3,NX4+][CX4][CX3](=O)[NX3][CX4][CX3](=O)[NX3,OX2,OX1-,OX2H1]"
VINA_MAX_RESIDUES = 8
VINA_MAX_ROTB = 32


def clean_sequence(seq: str) -> str:
    s = re.sub(r"\s+", "", str(seq).upper())
    bad = sorted(set(s) - AA1)
    if bad:
        raise ValueError(f"序列含非標準胺基酸字母：{''.join(bad)}（只接受 20 種標準胺基酸單字母碼）")
    if len(s) < 2:
        raise ValueError("胜肽序列至少 2 個殘基")
    return s


def looks_like_peptide(smiles: str) -> bool:
    """≥ 2 consecutive α-amino-acid units.  Used only to *stop* and ask, never to guess a sequence."""
    try:
        from rdkit import Chem
    except ImportError:
        return False
    m = Chem.MolFromSmiles(smiles or "")
    q = Chem.MolFromSmarts(BACKBONE_2RES)
    return bool(m is not None and q is not None and m.HasSubstructMatch(q))


def peptide_smiles(seq: str, termini: str = "charged") -> str:
    """SMILES used for docking (neutral form from the sequence).

    Vina has no electrostatic term, so the protonation form barely changes docking scores; the MD system
    is built from the sequence with ff14SB and pH-dependent hydrogens (charged termini, K/R +, D/E −).
    """
    from rdkit import Chem
    return Chem.MolToSmiles(Chem.MolFromSequence(clean_sequence(seq)))


def net_charge(seq: str, termini: str = "charged") -> int:
    s = clean_sequence(seq)
    q = s.count("K") + s.count("R") - s.count("D") - s.count("E")
    return q + (0 if termini != "charged" else 0)   # NH3+ and COO− cancel


@dataclass
class PeptideRecord:
    name: str
    sequence: str
    chain_id: str
    termini: str = "charged"
    kind: str = "peptide"
    pdb_path: str = ""
    pose_source: str = ""
    mapping: str = ""
    n_heavy: int = 0
    formal_charge: int = 0
    provider: str = "amber14/protein.ff14SB"
    charge_method: str = "ff14SB residue charges"
    gates: dict = field(default_factory=dict)
    cpp: dict = field(default_factory=dict)
    status: str = PASS
    resname: str = ""      # not a single residue; kept for interface compatibility
    smiles: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def free_chain_id(used: set[str], prefer: str = "P") -> str:
    for c in [prefer] + list(string.ascii_uppercase) + list(string.digits):
        if c not in used:
            return c
    raise RuntimeError("沒有可用的 chain ID")


def _generic_graph(mol):
    """Heavy-atom element graph with all bonds single, no charges/aromaticity — protonation-agnostic matching."""
    from rdkit import Chem
    m = Chem.RWMol(Chem.RemoveHs(mol, sanitize=False))
    for a in m.GetAtoms():
        a.SetFormalCharge(0); a.SetIsAromatic(False); a.SetNoImplicit(True); a.SetNumExplicitHs(0)
    for b in m.GetBonds():
        b.SetBondType(Chem.BondType.SINGLE); b.SetIsAromatic(False)
    m2 = m.GetMol()
    m2.UpdatePropertyCache(strict=False)
    return m2


def prepare_peptide(sequence: str, pose: Path | str | None, out_dir: Path | str, *, name: str = "P01", chain_id: str = "P",
                    termini: str = "charged", decisions: DecisionLog | None = None) -> PeptideRecord:
    """Template from sequence (standard atom names) + coordinates from pose (SDF/PDB) → heavy-atom PDB on its own chain."""
    from rdkit import Chem
    from rdkit.Chem import AllChem
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    seq = clean_sequence(sequence)
    rec = PeptideRecord(name=name, sequence=seq, chain_id=chain_id, termini=termini, formal_charge=net_charge(seq, termini))
    report = GateReport()
    if termini not in {"charged", "capped"}:
        raise ValueError("termini 必須是 charged 或 capped")
    if termini == "capped":
        report.add(Gate("termini", NEEDS_HUMAN, "ACE/NME 端帽尚未支援；目前只提供帶電端（NH3+/COO−）。",
                        options=["改用帶電端（預設）"]))
        rec.gates, rec.status = report.to_dict(), report.status
        return rec
    tmpl = Chem.MolFromSequence(seq)
    tmpl_heavy = Chem.RemoveHs(tmpl)
    rec.n_heavy = tmpl_heavy.GetNumAtoms()
    if pose is not None:
        pose = Path(pose)
        rec.pose_source = str(pose)
        if pose.suffix.lower() == ".sdf":
            pm = next(m for m in Chem.SDMolSupplier(str(pose), removeHs=False, sanitize=False) if m is not None)
        else:
            pm = Chem.MolFromPDBFile(str(pose), removeHs=False, sanitize=False)
        if pm is None:
            raise ValueError(f"無法讀取胜肽 pose：{pose}")
        g_t, g_p = _generic_graph(tmpl_heavy), _generic_graph(pm)
        match = g_p.GetSubstructMatch(g_t)
        if not match or len(match) != rec.n_heavy:
            report.add(Gate("peptide pose mapping", NEEDS_HUMAN,
                            f"docking pose（{g_p.GetNumAtoms()} 重原子）無法對應到序列 {seq}（{rec.n_heavy} 重原子）；不猜測。",
                            options=["確認序列", "改用 docking 輸出的 SDF"]))
            rec.gates, rec.status = report.to_dict(), report.status
            return rec
        conf = pm.GetConformer()
        coords = [conf.GetAtomPosition(match[i]) for i in range(rec.n_heavy)]
        rec.mapping = "graph"
        report.add(Gate("peptide pose mapping", PASS, f"{rec.n_heavy} 個重原子依序列模板一一對應（標準原子名由模板提供）。"))
    else:
        mh = Chem.AddHs(tmpl)
        AllChem.EmbedMolecule(mh, randomSeed=2026)
        AllChem.MMFFOptimizeMolecule(mh, maxIters=500)
        heavy = Chem.RemoveHs(mh)
        conf = heavy.GetConformer()
        coords = [conf.GetAtomPosition(i) for i in range(rec.n_heavy)]
        report.add(Gate("peptide 3D", AUTO_FIXED, "無 pose：以 ETKDG 建立初始構形（僅供 apo 胜肽或測試）。"))
    lines = []
    for i, a in enumerate(tmpl_heavy.GetAtoms()):
        info = a.GetPDBResidueInfo()
        nm, rn, ri = info.GetName().strip(), info.GetResidueName().strip(), info.GetResidueNumber()
        el = a.GetSymbol().upper()
        p = coords[i]
        lines.append(f"ATOM  {i + 1:5d} {nm:<4s} {rn:>3s} {chain_id}{ri:4d}    {p.x:8.3f}{p.y:8.3f}{p.z:8.3f}  1.00  0.00          {el:>2s}")
    lines += ["TER", "END"]
    pdb = out_dir / f"{name}_peptide.pdb"
    pdb.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rec.pdb_path = str(pdb)
    rec.smiles = peptide_smiles(seq, termini)
    n_res, n_rotb = len(seq), _rotatable_bonds(rec.smiles)
    if n_res > VINA_MAX_RESIDUES or n_rotb > VINA_MAX_ROTB:
        report.add(Gate("docking reliability", AUTO_FIXED,
                        f"{n_res} 殘基、{n_rotb} 個可旋轉鍵：超過 Vina 可靠範圍（≤ {VINA_MAX_RESIDUES} 殘基、≤ {VINA_MAX_ROTB} 可旋轉鍵）。"
                        "pose 僅供起始構形，務必以短 MD 複核；建議提高 exhaustiveness。"))
    report.add(Gate("force field", PASS, "胜肽使用與受體相同的 ff14SB，不走小分子 OpenFF/GAFF。"))
    report.add(Gate("chain", PASS, f"獨立 chain {chain_id}，殘基自 1 起編號，帶 TER；不會併入受體主鏈。"))
    if decisions:
        decisions.record("build.peptide", name, f"{seq} chain {chain_id} termini {termini}",
                         "胜肽走蛋白力場並放在獨立 chain；帶電端（NH3+/COO−）是生理 pH 的預設，會影響結合能，若實驗是端帽胜肽請改。")
    rec.gates, rec.status = report.to_dict(), report.status
    return rec


def _rotatable_bonds(smiles: str) -> int:
    try:
        from rdkit import Chem
        from rdkit.Chem import rdMolDescriptors
        return int(rdMolDescriptors.CalcNumRotatableBonds(Chem.MolFromSmiles(smiles)))
    except Exception:  # noqa: BLE001
        return 0


def topology_gate(topology, receptor_chain_ids: set[str], peptide_chain_ids: list[str]) -> GateReport:
    """After assembly: peptide chains exist once each and share no bond with the receptor."""
    rep = GateReport()
    chains = list(topology.chains())
    ids = [c.id for c in chains]
    for pid in peptide_chain_ids:
        n = ids.count(pid)
        if n != 1:
            rep.add(Gate("peptide chain count", NEEDS_HUMAN, f"胜肽 chain {pid} 在組裝後出現 {n} 次（應為 1）；可能被合併或拆開。"))
    pep_atoms = {a.index for c in chains if c.id in peptide_chain_ids for a in c.atoms()}
    rec_atoms = {a.index for c in chains if c.id in receptor_chain_ids for a in c.atoms()}
    cross = [(a, b) for a, b in topology.bonds() if (a.index in pep_atoms and b.index in rec_atoms) or (b.index in pep_atoms and a.index in rec_atoms)]
    if cross:
        a, b = cross[0]
        rep.add(Gate("peptide–receptor bond", NEEDS_HUMAN,
                     f"胜肽與受體之間出現 {len(cross)} 個共價鍵（例：{a.residue.name}{a.residue.id}:{a.name} – {b.residue.name}{b.residue.id}:{b.name}）。"
                     "胜肽被接進受體主鏈，MD 結果將完全錯誤；不自動修正。", options=["檢查 chain ID 與殘基編號", "重新匯出 docking pose"]))
    if not rep.gates:
        rep.add(Gate("peptide topology", PASS, f"{len(peptide_chain_ids)} 條胜肽鏈獨立存在，與受體無共價鍵。"))
    return rep


# --------------------------------------------------------------------------- CPP gate (brief S10)
# Small offline reference set of experimentally established CPPs (public literature sequences).
KNOWN_CPPS = {
    "TAT(48-60)": "GRKKRRQRRRPPQ", "Penetratin": "RQIKIWFQNRRMKWKK", "R8": "RRRRRRRR", "R9": "RRRRRRRRR",
    "Transportan": "GWTLNSAGYLLGKINLKALAALAKKIL", "pVEC": "LLIILRRRIRKQAHAHSK", "MAP": "KLALKLALKALKAALKLA",
    "Pep-1": "KETWWETWWTEWSQPKKKRKV", "SV40 NLS": "PKKKRKV", "Buforin II": "TRSSRAGLQFPVGRVHRLLRK",
}
EISENBERG = {"A": 0.62, "R": -2.53, "N": -0.78, "D": -0.90, "C": 0.29, "Q": -0.85, "E": -0.74, "G": 0.48, "H": -0.40,
             "I": 1.38, "L": 1.06, "K": -1.50, "M": 0.64, "F": 1.19, "P": 0.12, "S": -0.18, "T": -0.05, "W": 0.81,
             "Y": 0.26, "V": 1.08}


def hydrophobic_moment(seq: str, angle_deg: float = 100.0) -> float:
    s = clean_sequence(seq)
    a = math.radians(angle_deg)
    x = sum(EISENBERG[c] * math.cos(i * a) for i, c in enumerate(s))
    y = sum(EISENBERG[c] * math.sin(i * a) for i, c in enumerate(s))
    return math.hypot(x, y) / len(s)


def _identity(a: str, b: str) -> float:
    """Best ungapped local identity of the shorter sequence slid along the longer (fraction of the shorter)."""
    s, l = (a, b) if len(a) <= len(b) else (b, a)
    best = 0
    for off in range(-len(s) + 1, len(l)):
        m = sum(1 for i, c in enumerate(s) if 0 <= off + i < len(l) and l[off + i] == c)
        best = max(best, m)
    return best / len(s)


def cpp_features(seq: str) -> dict:
    s = clean_sequence(seq)
    n = len(s)
    rk = s.count("R") + s.count("K")
    best = max(((name, _identity(s, ref)) for name, ref in KNOWN_CPPS.items()), key=lambda x: x[1])
    return {"length": n, "net_charge": net_charge(s), "arg_lys_fraction": round(rk / n, 3), "arg_count": s.count("R"),
            "hydrophobic_moment": round(hydrophobic_moment(s), 3),
            "hydrophobic_fraction": round(sum(1 for c in s if EISENBERG[c] > 0.5) / n, 3),
            "closest_known_cpp": best[0], "identity_to_closest": round(best[1], 3)}


def cpp_gate(seq: str, *, target_location: str | None, experimental_evidence: str | None = None) -> tuple[Gate, dict]:
    """Returns (gate, record).  record['status'] ∈ 實驗證實 / 計算預測 / 未評估 / 不適用."""
    if not target_location:
        g = Gate("CPP", NEEDS_HUMAN, "胜肽的作用標靶位置未指定。請選擇：胞內（需要穿膜）、膜外側、分泌／胞外。",
                 options=["胞內 intracellular", "膜外側 extracellular-membrane", "分泌／胞外 secreted"])
        return g, {"status": "未評估", "reason": "標靶位置未指定"}
    loc = target_location.lower()
    if not loc.startswith("intra") and "胞內" not in target_location:
        return Gate("CPP", PASS, f"標靶位於 {target_location}，不需穿膜；不評估 CPP。"), {"status": "不適用", "target": target_location}
    if experimental_evidence:
        return (Gate("CPP", PASS, f"使用者提供穿膜實驗證據：{experimental_evidence}"),
                {"status": "實驗證實", "evidence": experimental_evidence, "target": target_location})
    f = cpp_features(seq)
    score = 0
    reasons = []
    if 5 <= f["length"] <= 30:
        score += 1
    else:
        reasons.append(f"長度 {f['length']}（典型 CPP 5–30）")
    if f["net_charge"] >= 3:
        score += 2
    else:
        reasons.append(f"淨電荷 {f['net_charge']:+d}（典型 CPP ≥ +3）")
    if f["arg_lys_fraction"] >= 0.3 or f["arg_count"] >= 5:
        score += 2
    else:
        reasons.append(f"Arg/Lys 比例 {f['arg_lys_fraction']:.0%}")
    if f["hydrophobic_moment"] >= 0.35 and f["net_charge"] >= 2:
        score += 1    # amphipathic
    if f["identity_to_closest"] >= 0.6:
        score += 2
    rec = {"status": "計算預測", "target": target_location, "features": f, "score": score, "max_score": 8}
    if score >= 4:
        rec["prediction"] = "可能穿膜"
        return (Gate("CPP", AUTO_FIXED, f"依序列特徵預測可能穿膜（分數 {score}/8；最接近已知 CPP：{f['closest_known_cpp']}，"
                     f"相同度 {f['identity_to_closest']:.0%}）。這是**預測**而非驗證，報告會標註「CPP 狀態：計算預測」。",
                     options=["提供實驗證據", "接受預測並繼續"]), rec)
    rec["prediction"] = "不太可能穿膜"
    return (Gate("CPP", NEEDS_HUMAN, "依序列特徵預測不太可能進入細胞（分數 %d/8；%s）。對胞內標靶而言，後續 docking/MD 在生物學上可能沒有意義。" % (score, "；".join(reasons)),
                 options=["提供實驗證據（文獻或自有數據）", "改設計：加入 CPP 序列（如 TAT、R8）", "仍要繼續（報告標註）"]), rec)
