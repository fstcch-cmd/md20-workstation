"""Validation case 1 — Hsieh C.-C. et al., J. Ethnopharmacol. 318 (2024) 116980.

"Alleviation of PM2.5-induced alveolar macrophage inflammation using extract of fermented Chenopodium
formosanum Koidz sprouts via regulation of NF-κB pathway."  §2.13 / Fig. 5 / Table 1:
AutoDock Vina 1.2.3, *multiple-ligand simultaneous docking* of six LC-MS/MS-identified water-fraction
metabolites on the NF-κB RELA (p65) subunit.

Published setup (copied from §2.13):
  receptor   "NF-κB (PDB ID: 1VKF)", non-protein molecules removed, minimised
  box        28.5 × 34.5 × 26.25 Å, centre (14.63, 54.821, 63.425), spacing 0.375 (AD4 grid units)
  result     collective affinity −13.86 kcal/mol; 24 H-bonds with Lys195, Ile196, Gln225, Tyr227, Arg236,
             Gln234, Phe239, Gln241, Ser281, Glu282, Arg273

Erratum found while building this case: RCSB 1VKF is a *Thermotoga maritima* glycerol-uptake antiterminator
protein (TM1436, 188 aa/chain), not NF-κB.  The NF-κB entry consistent with the paper (mouse — MH-S cells are
murine; p65 residues 19–291 cover Lys195…Glu282) is **1VKX** (p50/p65 heterodimer + κB DNA, 2.9 Å).  The
CI test `test_validation_hsieh2024.py::test_which_pdb_matches_the_paper` decides this from coordinates:
it counts the paper's 11 H-bond residues (name + number) inside the published box in both entries.

This is exactly the kind of mistake MD20's gates are for; the case is kept as a teaching example.
"""
from __future__ import annotations

PAPER = {
    "citation": "Hsieh C.-C., Yu S.-H., Kuo H.-C., Cheng K.-W., Hsu C.-C., Lin Y.-P., Khumsupan D., Lin S.-P., "
                "Angkawijaya A.E., Cheng K.-C. J. Ethnopharmacol. 2024, 318, 116980. doi:10.1016/j.jep.2023.116980",
    "pdb_printed": "1VKF",
    "pdb_candidate": "1VKX",
    "box_center": (14.63, 54.821, 63.425),
    "box_size": (28.5, 34.5, 26.25),
    "collective_affinity_kcal_mol": -13.86,
    "hbond_residues": ["LYS195", "ILE196", "GLN225", "TYR227", "ARG236", "GLN234", "PHE239", "GLN241",
                       "SER281", "GLU282", "ARG273"],
}

# Table 1: concentration in 25 ppm water-extracted FCS (ppb) and the H-bond residues reported per ligand.
# SMILES: stereochemistry of the natural L-/D- forms; ionisation at pH 7.4 (carboxylates deprotonated,
# carnitine zwitterion) — Vina ignores charge, but MD/binding steps do not.
LIGANDS = [
    {"name": "PGA", "label": "L-pyroglutamic acid", "ppb": 95.57, "smiles": "[O-]C(=O)[C@@H]1CCC(=O)N1",
     "paper_residues": ["GLN241", "PHE239"]},
    {"name": "GLC", "label": "gluconic acid", "ppb": 46.93,
     "smiles": "OC[C@@H](O)[C@@H](O)[C@H](O)[C@@H](O)C([O-])=O",
     "paper_residues": ["TYR227", "GLN234", "ARG236", "GLN225", "ARG273"]},   # Table 1 prints "Glu225" (text: Gln225)
    {"name": "URI", "label": "uridine", "ppb": 18.62, "smiles": "OC[C@H]1O[C@@H](N2C=CC(=O)NC2=O)[C@H](O)[C@@H]1O",
     "paper_residues": ["ARG236", "PHE239"]},
    {"name": "MAL", "label": "L-(−)-malic acid", "ppb": 9.27, "smiles": "O[C@@H](CC([O-])=O)C([O-])=O",
     "paper_residues": ["LYS195", "ILE196", "SER281", "GLU282"]},
    {"name": "ALC", "label": "acetyl-L-carnitine", "ppb": 0.48, "smiles": "CC(=O)O[C@H](CC([O-])=O)C[N+](C)(C)C",
     "paper_residues": ["ARG236", "TYR227"]},
    {"name": "PAN", "label": "D-pantothenic acid", "ppb": 0.20, "smiles": "CC(C)(CO)[C@@H](O)C(=O)NCCC([O-])=O",
     "paper_residues": ["GLN225"]},
]


def workflow_config(pdb_id: str = "1VKX", *, tier: str = "classroom") -> dict:
    """MD20 workflow reproducing the paper, with MD20's additions (apo vs holo MD, SMD/umbrella)."""
    return {
        "name": f"hsieh2024_rela_{pdb_id.lower()}",
        "receptor": {"pdb_id": pdb_id, "exclude_chains": ["C", "D"]},   # 1VKX: C/D = κB DNA ("non-protein removed")
        "ph": 7.4,
        "box": {"center": list(PAPER["box_center"]), "size": list(PAPER["box_size"])},
        "ligands": [{"name": l["name"], "smiles": l["smiles"]} for l in LIGANDS],
        "docking": {"mode": "simultaneous", "exhaustiveness": 32, "n_poses": 9, "seed": 2026},
        "pose_choices": {},
        "md": {"systems": ["apo", "docked_multi"], "tier": tier, "replicas": 1, "padding_nm": 1.0},
        # the most abundant metabolite; a weak, polar binder — expect a shallow PMF
        "binding": {"enabled": False, "ligands": ["PGA"], "config": {}},
        "validation": {"case": "hsieh2024", "paper": PAPER},
    }


def residue_overlap(found: set[str], reference: list[str] | None = None) -> dict:
    ref = set(reference or PAPER["hbond_residues"])
    hit = sorted(ref & found)
    return {"reference": sorted(ref), "found_in_contact": hit, "recall": round(len(hit) / len(ref), 3),
            "extra": sorted(found - ref)[:30]}
