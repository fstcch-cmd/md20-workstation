"""Ligand protonation at a target pH (default 7.4) — one place, used by docking, the HTS screen and (through the
docked molecule's SMILES) the MD build, so all three see the same charge state.

Why (consultation 2026-11-01 §0.1): PubChem/ChEMBL structures are neutral; the receptor is protonated for pH 7.4.
Docking neutral acids/amines against a protonated receptor is a systematic error larger than search effort.

Rules (transparent SMARTS, pKa classes far from 7.4 only; nothing ambiguous is guessed):
  deprotonated (−1): carboxylic acid (pKa ~4–5), sulfonic acid (~−1), phosph(on)ate first OH (~1–2; second ~6–7 left
                     neutral and noted), tetrazole N–H (~4.5–5), acyl sulfonamide N–H (~4–5)
  protonated  (+1): aliphatic amines whose N carries only sp3 carbons (primary/secondary/tertiary, pKa ~9–11),
                     amidines (~11–12), guanidines (~13; acyl-guanidines excluded); a second amine within 3 bonds of
                     a cation stays neutral (piperazine, 1,2-diamines: pKa₂ ≈ 5.6–7)
  left neutral, noted when present: imidazole/histidine-like (~6–7), pyridines, anilines, phenols, amides,
                     sulfonamides, hydroxamic acids (~8.5–9.5)
Groups already charged are never touched, so a charge state the user wrote explicitly is preserved.
`mode="as_given"` disables the rules (the SMILES/SDF state is used unchanged).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# (label, SMARTS, index of the atom in the match to change, new formal charge)
DEPROTONATE = [
    ("carboxylic acid", "[CX3](=O)[OX2H1;+0]", 2),
    ("sulfonic acid", "[SX4](=O)(=O)[OX2H1;+0]", 3),
    ("phosph(on)ate (first OH)", "[PX4](=O)[OX2H1;+0]", 2),
    ("tetrazole N–H", "[nH;+0]1nnnc1", 0),
    ("tetrazole N–H", "[nH;+0]1nncn1", 0),
    ("acyl sulfonamide N–H", "[CX3](=O)[NX3H1;+0][SX4](=O)=O", 2),
]
PROTONATE = [
    # amidine / guanidine: protonate the imine-like N (not part of an acyl group, not N–O/N–N/N–S, not aromatic)
    ("guanidine", "[NX2;+0;!a;!$(N-[#8,#7,#16]);!$(N-C=[O,S])]=[CX3;!a]([NX3;!$(N-C=[O,S])])[NX3;!$(N-C=[O,S])]", 0),
    ("amidine", "[NX2;+0;!a;!$(N-[#8,#7,#16]);!$(N-C=[O,S])]=[CX3;!a;!$(C(=N)(N)N)]([NX3;!$(N-C=[O,S]);!$(N-[#8,#7,#16])])[#6,#1]", 0),
    # aliphatic amine: every heavy neighbour is an sp3 carbon (excludes anilines, amides, sulfonamides, enamines,
    # hydrazines, hydroxylamines, N-aryl, carbamates)
    ("aliphatic amine", "[NX3;+0;!$(N~[!#6;!#1]);!$(N-[!CX4])]", 0),
]
NOTE_ONLY = [
    ("imidazole-like (pKa ~6–7, left neutral)", "c1ncc[nH]1"),
    ("hydroxamic acid (pKa ~9, left neutral)", "[CX3](=O)[NX3][OX2H1]"),
    ("phosph(on)ate second OH (pKa ~6–7, left neutral)", "[PX4](=O)([OX1-,OX2H1])[OX2H1]"),
]


@dataclass
class IonizeResult:
    mode: str
    ph: float
    changes: list[dict] = field(default_factory=list)       # {"group", "atom", "charge"}
    ambiguous: list[str] = field(default_factory=list)
    net_charge_before: int = 0
    net_charge_after: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.changes)

    def why(self) -> str:
        if self.mode != "auto":
            return f"使用輸入的質子化狀態（protonation: {self.mode}），淨電荷 {self.net_charge_after:+d}。"
        if not self.changes:
            base = f"pH {self.ph:g} 下沒有需要改變的可離子化基團（或已是帶電型），淨電荷 {self.net_charge_after:+d}。"
        else:
            groups = "、".join(sorted({c["group"] for c in self.changes}))
            base = (f"依 pH {self.ph:g} 主要離子態對接（{groups}），淨電荷 {self.net_charge_before:+d} → {self.net_charge_after:+d}；"
                    "受體依同一 pH 加氫，兩邊一致。")
        if self.ambiguous:
            base += "未改變（pKa 接近 7.4，不猜）：" + "、".join(sorted(set(self.ambiguous))) + "。"
        return base

    def to_dict(self) -> dict:
        return {"mode": self.mode, "ph": self.ph, "changes": self.changes, "ambiguous": sorted(set(self.ambiguous)),
                "net_charge_before": self.net_charge_before, "net_charge_after": self.net_charge_after, "why": self.why()}


def ionize(mol, *, ph: float = 7.4, mode: str = "auto"):
    """Return (heavy-atom RDKit mol in the pH-7.4 state, IonizeResult).  Input may carry explicit hydrogens;
    the output has none (callers re-add them, with coordinates if the input had a conformer)."""
    from rdkit import Chem
    heavy = Chem.RemoveHs(mol, sanitize=True)
    res = IonizeResult(mode=mode, ph=ph, net_charge_before=Chem.GetFormalCharge(heavy))
    if mode != "auto":
        res.net_charge_after = res.net_charge_before
        return heavy, res
    if abs(ph - 7.4) > 1.0:
        # the rule set is pKa-class based; far from physiological pH it would be wrong
        res.ambiguous.append(f"規則只適用 pH 6.4–8.4（目前 {ph:g}）")
        res.net_charge_after = res.net_charge_before
        return heavy, res
    rw = Chem.RWMol(heavy)
    for label, smarts in NOTE_ONLY:
        if rw.HasSubstructMatch(Chem.MolFromSmarts(smarts)):
            res.ambiguous.append(label)
    done: set[int] = set()
    for label, smarts, k in DEPROTONATE:
        patt = Chem.MolFromSmarts(smarts)
        seen_p: set[int] = set()
        for m in rw.GetSubstructMatches(patt):
            idx = m[k]
            if idx in done:
                continue
            if label.startswith("phosph"):          # only the first OH per P
                p_idx = m[0]
                if p_idx in seen_p:
                    continue
                seen_p.add(p_idx)
            a = rw.GetAtomWithIdx(idx)
            a.SetFormalCharge(-1)
            a.SetNumExplicitHs(0)
            a.SetNoImplicit(True)
            done.add(idx)
            res.changes.append({"group": label, "atom": int(idx), "charge": -1})
    dmat = Chem.GetDistanceMatrix(rw)
    cations: list[int] = []
    for label, smarts, k in PROTONATE:
        patt = Chem.MolFromSmarts(smarts)
        for m in rw.GetSubstructMatches(patt):
            idx = m[k]
            if idx in done:
                continue
            if label == "aliphatic amine" and any(dmat[idx][c] <= 3 for c in cations):
                # a second amine within 3 bonds of a cation has its pKa pushed to ~5–7 (piperazine 9.8/5.6,
                # ethylenediamine 10.0/7.0): only one is protonated
                res.ambiguous.append("相鄰的第二個胺（pKa 被前一個陽離子壓低，留中性）")
                continue
            cations.append(idx)
            a = rw.GetAtomWithIdx(idx)
            a.SetFormalCharge(+1)
            a.SetNoImplicit(False)
            a.SetNumExplicitHs(0)
            done.add(idx)
            res.changes.append({"group": label, "atom": int(idx), "charge": +1})
            if label in ("guanidine", "amidine"):
                # the other N atoms of the same C are now part of the delocalised cation — never protonate them too
                c = rw.GetAtomWithIdx(m[1])
                done.update(n.GetIdx() for n in c.GetNeighbors() if n.GetAtomicNum() == 7)
    out = rw.GetMol()
    Chem.SanitizeMol(out)
    res.net_charge_after = Chem.GetFormalCharge(out)
    return out, res
