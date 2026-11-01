"""Validation case 2 (peptide) — Hsieh C.-C. et al., LWT 222 (2025) 117641.

"Peptide from tempeh-like fermented Chenopodium formosanum counters senescence while enhancing antioxidant ability
in non-replicative aging."  §2.13 / Fig. 5: the glycine-rich peptide GRP (Gly-Gly-Gly-Gly-Gly-Lys-Pro) docked to
the Keap1 BTB domain (PDB 4CXT) with AutoDock; affinity −5.22 kcal/mol.

Published setup:
  receptor   Keap1-BTB, PDB 4CXT (human, 2.66 Å, co-crystal CDDO = SXJ, which reacts covalently with Cys151)
  box        36 × 51 × 45 Å, centre (5.043, −9.302, −13.046), spacing 0.375
  H-bonds    Ser102, Ser103, Ser166 (2.98–3.21 Å; mostly from the first three Gly)
  contacts   Ser104, Pro105, Phe139, Gln163, Ile164, Asp165; Lys/Pro at Thr60, Phe64, Ala140, Tyr141, Thr142, Ala143

Teaching points MD20 makes explicit:
  * Keap1 is cytosolic → the peptide must reach the cytosol.  MD20's CPP gate runs before docking; GGGGGKP
    (net +1, one Lys) is not predicted to be cell-penetrating, so the gate asks for evidence or an explicit override.
    The cell/C. elegans activity in the paper is functional evidence, not a measured uptake.
  * The paper calls the non-H-bond contacts "covalent bonding"; docking (and MD with Amber ff14SB) has no covalent
    chemistry — they are van der Waals / hydrophobic contacts.  CDDO's own binding at Cys151 *is* covalent.
  * The box (36 × 51 × 45 Å) is larger than the whole BTB domain: it is effectively blind docking; the score of a
    flexible 7-mer in Vina (~−5 kcal/mol) is within the method's noise, so MD stability decides.
"""
from __future__ import annotations

PAPER = {
    "citation": "Hsieh C.-C., Lin H.-W., Huang H.-C., Khumsupan D., Shen S.-C., Lin S.-P., Hsieh C.-W., Tsai T.-Y., "
                "Jantama S.S., Kuo H.-C., Cheng K.-C. LWT 2025, 222, 117641.",
    "pdb": "4CXT",
    "box_center": (5.043, -9.302, -13.046),
    "box_size": (36.0, 51.0, 45.0),
    "affinity_kcal_mol": -5.22,
    "sequence": "GGGGGKP",
    "hbond_residues": ["SER102", "SER103", "SER166"],
    "contact_residues": ["SER104", "PRO105", "PHE139", "GLN163", "ILE164", "ASP165", "THR60", "PHE64", "ALA140",
                         "TYR141", "THR142", "ALA143"],
}


def workflow_config(*, tier: str = "classroom", cpp_override: str | None = None) -> dict:
    lig = {"name": "GRP", "sequence": PAPER["sequence"], "termini": "charged", "target_location": "胞內"}
    if cpp_override:
        lig["cpp_override"] = cpp_override
    return {
        "name": "hsieh2025_keap1_grp",
        "receptor": {"pdb_id": PAPER["pdb"]},
        "ph": 7.4,
        "box": {"center": list(PAPER["box_center"]), "size": list(PAPER["box_size"])},
        "ligands": [lig],
        "docking": {"mode": "independent", "exhaustiveness": 32, "n_poses": 9, "seed": 2026},
        "pose_choices": {},
        "md": {"systems": ["apo", "docked_single"], "tier": tier, "replicas": 1, "padding_nm": 1.0},
        "binding": {"enabled": False, "ligands": ["GRP"], "config": {}},
        "validation": {"case": "hsieh2025", "paper": PAPER},
    }
