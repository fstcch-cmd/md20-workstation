"""Chemistry figures for the report (D-58): compound properties, drug-likeness, chemical space, 2D interaction diagram.

RDKit is imported inside each function; without it the functions return None and the report states that the figure
needs RDKit.  Pure numpy parts (`lipinski_violations`, `chem_space_xy`, `pose_contacts`) are tested everywhere.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

LIMITS = {"mw": 500.0, "logp": 5.0, "hbd": 5, "hba": 10, "tpsa": 140.0, "rotb": 10}
PROP_LABELS = {"mw": ("分子量", "Molecular weight", "Da"), "logp": ("脂水分配係數 logP", "logP", ""),
               "tpsa": ("極性表面積", "Polar surface area", "Å²"), "hbd": ("氫鍵供體", "H-bond donors", ""),
               "hba": ("氫鍵受體", "H-bond acceptors", ""), "rotb": ("可轉動鍵", "Rotatable bonds", "")}


def lipinski_violations(p: dict) -> int:
    return int(p["mw"] > 500) + int(p["logp"] > 5) + int(p["hbd"] > 5) + int(p["hba"] > 10)


def chem_space_xy(bits: np.ndarray) -> np.ndarray:
    """2D map of fingerprint bit vectors by principal components (n × 2)."""
    X = np.asarray(bits, float)
    if len(X) < 3:
        return np.zeros((len(X), 2))
    X = X - X.mean(0)
    U, S, _ = np.linalg.svd(X, full_matrices=False)
    return U[:, :2] * S[:2]


def properties_from_sdf(path) -> dict | None:
    try:
        from rdkit import Chem
        from rdkit.Chem import Crippen, Descriptors, Lipinski, rdMolDescriptors
    except Exception:  # noqa: BLE001
        return None
    m = Chem.MolFromMolFile(str(path), removeHs=True)
    if m is None:
        return None
    return {"mw": round(Descriptors.MolWt(m), 1), "logp": round(Crippen.MolLogP(m), 2),
            "tpsa": round(rdMolDescriptors.CalcTPSA(m), 1), "hbd": Lipinski.NumHDonors(m), "hba": Lipinski.NumHAcceptors(m),
            "rotb": Lipinski.NumRotatableBonds(m), "heavy": m.GetNumHeavyAtoms()}


def fingerprint_bits(path, n_bits: int = 1024):
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except Exception:  # noqa: BLE001
        return None
    m = Chem.MolFromMolFile(str(path), removeHs=True)
    if m is None:
        return None
    fp = AllChem.GetMorganFingerprintAsBitVect(m, 2, nBits=n_bits)
    return np.array(list(fp), dtype=np.uint8)


# ------------------------------------------------------------------------------------------- 2D interaction diagram
def pose_contacts(lig_xyz, lig_elem, prot_atoms: list[dict], *, cutoff: float = 4.0) -> list[dict]:
    """For each ligand heavy atom: nearest protein residue within the cutoff and the interaction class.
    prot_atoms: [{"xyz", "element", "res", "name", "resname"}].  Pure numpy."""
    if not prot_atoms:
        return []
    P = np.array([a["xyz"] for a in prot_atoms], float)
    out = []
    for i, (x, el) in enumerate(zip(np.asarray(lig_xyz, float), lig_elem)):
        d = np.linalg.norm(P - x, axis=1)
        j = int(np.argmin(d))
        if d[j] > cutoff:
            out.append({"atom": i, "res": None})
            continue
        a = prot_atoms[j]
        polar = el in ("N", "O") and a["element"] in ("N", "O")
        ionic = polar and (a["resname"], a["name"]) in {("LYS", "NZ"), ("ARG", "NH1"), ("ARG", "NH2"), ("ARG", "NE"),
                                                        ("ASP", "OD1"), ("ASP", "OD2"), ("GLU", "OE1"), ("GLU", "OE2")}
        kind = "ionic" if ionic and d[j] <= 4.0 else ("hbond" if polar and d[j] <= 3.5 else
                                                      ("hydrophobic" if el == "C" and a["element"] == "C" else "contact"))
        out.append({"atom": i, "res": a["res"], "kind": kind, "distance_A": round(float(d[j]), 2)})
    return out


def interaction_diagram(sdf_path, receptor_pdb, out_png: Path) -> tuple[str | None, list[dict]]:
    """2D drawing of the ligand; atoms coloured by interaction class with the residue name next to them."""
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
        from rdkit.Chem.Draw import rdMolDraw2D
    except Exception:  # noqa: BLE001
        return None, []
    m = Chem.MolFromMolFile(str(sdf_path), removeHs=False)
    if m is None:
        return None, []
    heavy = [a.GetIdx() for a in m.GetAtoms() if a.GetAtomicNum() > 1]
    conf = m.GetConformer()
    xyz = [list(conf.GetAtomPosition(i)) for i in heavy]
    elem = [m.GetAtomWithIdx(i).GetSymbol() for i in heavy]
    prot = []
    for l in Path(receptor_pdb).read_text(encoding="utf-8", errors="ignore").splitlines():
        if l.startswith("ATOM"):
            el = (l[76:78].strip() or l[12:16].strip()[:1]).upper()
            if el == "H":
                continue
            try:
                prot.append({"xyz": [float(l[30:38]), float(l[38:46]), float(l[46:54])], "element": el,
                             "res": f"{l[17:20].strip()}{int(l[22:26])}", "name": l[12:16].strip(), "resname": l[17:20].strip()})
            except ValueError:
                continue
    cons = pose_contacts(xyz, elem, prot)
    mh = Chem.RemoveHs(m)
    AllChem.Compute2DCoords(mh)
    colors = {"hbond": (0.18, 0.44, 0.62), "ionic": (0.72, 0.26, 0.25), "hydrophobic": (0.66, 0.53, 0.17), "contact": (0.6, 0.6, 0.6)}
    hl, hc = [], {}
    for c, i_heavy in zip(cons, range(len(heavy))):
        if c.get("res"):
            idx = i_heavy          # heavy-atom order is preserved by RemoveHs
            if idx < mh.GetNumAtoms():
                hl.append(idx)
                hc[idx] = colors[c["kind"]]
                mh.GetAtomWithIdx(idx).SetProp("atomNote", c["res"])
    d = rdMolDraw2D.MolDraw2DCairo(720, 480)
    d.drawOptions().annotationFontScale = 0.55
    d.DrawMolecule(mh, highlightAtoms=hl, highlightAtomColors=hc)
    d.FinishDrawing()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    out_png.write_bytes(d.GetDrawingText())
    return str(out_png), cons
