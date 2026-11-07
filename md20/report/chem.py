"""Chemistry figures for the report (D-58): compound properties, drug-likeness, chemical space, 2D interaction diagram.

RDKit is imported inside each function; without it the functions return None and the report states that the figure
needs RDKit.  Pure numpy parts (`lipinski_violations`, `chem_space_xy`, `pose_contacts`) are tested everywhere.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

LIMITS = {"mw": 500.0, "logp": 5.0, "hbd": 5, "hba": 10, "tpsa": 140.0, "rotb": 10}
# Axis labels: {"label": (zh, en, ja, ko), "unit": ...}; resolve the label with md20.i18n.pick (D-74).
PROP_LABELS = {
    "mw": {"label": ("分子量", "Molecular weight", "分子量", "분자량"), "unit": "Da"},
    "logp": {"label": ("脂水分配係數 logP", "logP", "分配係数 logP", "분배 계수 logP"), "unit": ""},
    "tpsa": {"label": ("極性表面積", "Polar surface area", "極性表面積", "극성 표면적"), "unit": "Å²"},
    "hbd": {"label": ("氫鍵供體", "H-bond donors", "水素結合供与体", "수소 결합 주개"), "unit": ""},
    "hba": {"label": ("氫鍵受體", "H-bond acceptors", "水素結合受容体", "수소 결합 받개"), "unit": ""},
    "rotb": {"label": ("可轉動鍵", "Rotatable bonds", "回転可能結合", "회전 가능 결합"), "unit": ""},
}


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
# display order for the ONE highlight colour of an atom; it is not a strength ranking (all labels stay in "kinds")
KIND_DISPLAY_ORDER = ("salt_bridge", "like_charge_proximity", "charged_proximity_ligand_charge_unknown", "polar_proximity",
                      "hydrophobic", "contact")


def pose_contacts(lig_xyz, lig_elem, prot_atoms: list[dict], *, cutoff: float = 4.0,
                  lig_charges: list[int] | None = None) -> list[dict]:
    """Static pose contacts with the SAME chemistry as the trajectory fingerprint (D-97, A5; analysis/interactions.py).

    For each ligand heavy atom: every protein atom within `cutoff` Å is examined (not only the nearest), and the atom
    gets all labels that apply ("kinds"); "res" is the nearest residue (for the drawing), "kind" is the label used for
    the highlight colour (display order, not strength).  `lig_charges` = formal charge per ligand atom (from the
    molecule's chemistry); None = unknown → no salt bridge can be called.  Distance-only N/O pairs are
    polar_proximity, never "hbond".  prot_atoms: [{"xyz", "element", "res", "name", "resname"}] in Å.  Pure numpy."""
    from ..analysis.interactions import pair_labels, HYDROPHOBIC_RES
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
        sign = None if lig_charges is None else int(np.sign(lig_charges[i]))
        kinds, partners = set(), []
        for k in np.nonzero(d <= cutoff)[0]:
            a = prot_atoms[int(k)]
            labs = pair_labels(el, sign, a["element"], a["resname"], a["name"], float(d[k]) / 10.0,
                               sidechain_carbon=a["name"] not in ("C", "CA") and a["resname"] in HYDROPHOBIC_RES)
            if labs:
                kinds |= labs
                partners.append({"res": a["res"], "atom": a["name"], "labels": sorted(labs), "distance_A": round(float(d[k]), 2)})
        kinds = kinds or {"contact"}
        kind = next(k for k in KIND_DISPLAY_ORDER if k in kinds)
        out.append({"atom": i, "res": prot_atoms[j]["res"], "kind": kind, "kinds": sorted(kinds),
                    "distance_A": round(float(d[j]), 2), "partners": partners,
                    "ligand_charge": "unknown" if lig_charges is None else "formal charges"})
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
    # formal charges come from the molecule's chemistry (charged groups written in the SDF), not from partial charges;
    # D-98: delocalised over resonance forms (carboxylate: both O), the same rule as the trajectory fingerprint
    from ..build.ligand import charged_group_signs
    signs, _ = charged_group_signs(m)
    q = [signs[i] for i in heavy]
    cons = pose_contacts(xyz, elem, prot, lig_charges=q)
    mh = Chem.RemoveHs(m)
    AllChem.Compute2DCoords(mh)
    colors = {"polar_proximity": (0.18, 0.44, 0.62), "salt_bridge": (0.72, 0.26, 0.25), "hydrophobic": (0.66, 0.53, 0.17),
              "like_charge_proximity": (0.55, 0.35, 0.6), "charged_proximity_ligand_charge_unknown": (0.85, 0.55, 0.45),
              "contact": (0.6, 0.6, 0.6), "hbond": (0.18, 0.44, 0.62), "ionic": (0.72, 0.26, 0.25)}
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
