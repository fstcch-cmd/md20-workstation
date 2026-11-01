"""Validation against HCC Lab publications (teaching background cases).

1. Hsieh 2024 J. Ethnopharmacol. — six metabolites, simultaneous docking on NF-κB RELA.
2. Hsieh 2025 LWT — glycine-rich peptide GGGGGKP on Keap1-BTB (4CXT).

Pure part (network only): is the published PDB/box consistent with the published residues?
Heavy part (vina + meeko + pdbfixer): reproduce the docking and record score + residue recall in
validation_results/*.json (posted by CI).  Assertions are deliberately about *consistency*, not about
matching the paper's numbers, which depend on unpublished settings (exhaustiveness, protonation, seeds).
"""
import json
import os
import urllib.request
from pathlib import Path

import pytest

from md20.validation import hsieh2024, hsieh2025, residues_in_box, residues_near, protein_residues

OUT = Path(os.environ.get("MD20_VALIDATION_OUT", "validation_results"))
# word-boundary match: "ANTITERMINATOR-RELATED" must not count as RELA
NFKB_RE = __import__("re").compile(r"NF-?\s?KAPPA\s?-?B|NF-?KB|\bKAPPA\s?B\b|\bP65\b|\bRELA\b")


def _fetch(pdb_id: str, d: Path) -> Path:
    p = d / f"{pdb_id}.pdb"
    if not p.is_file():
        try:
            urllib.request.urlretrieve(f"https://files.rcsb.org/download/{pdb_id}.pdb", p)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"RCSB unreachable: {exc}")
    return p


@pytest.fixture(scope="module")
def rcsb(tmp_path_factory):
    d = tmp_path_factory.mktemp("rcsb_val")
    return lambda pid: _fetch(pid, d)


def _save(name: str, data: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def test_which_pdb_matches_hsieh2024(rcsb):
    """The paper prints PDB 1VKF, but the reported residues (Lys195…Glu282, p65) can only belong to an NF-κB
    structure.  Decide by whether the numbered residues actually EXIST in each entry — coordinate-frame
    independent, so it does not depend on the paper's (unresolvable) box frame."""
    P = hsieh2024.PAPER
    ref = set(P["hbond_residues"])
    res = {}
    for pid in ("1VKF", "1VKX"):
        txt = rcsb(pid).read_text(errors="ignore")
        present = protein_residues(txt)
        title = next((l[10:].strip() for l in txt.splitlines() if l.startswith("TITLE")), "")
        hit = sorted(ref & present)
        res[pid] = {"title": title, "is_nf_kb": bool(NFKB_RE.search(title.upper())),
                    "reported_residues_present": hit, "recall": round(len(hit) / len(ref), 3)}
    _save("hsieh2024_pdb_identity", res)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    # 1VKF is a Thermotoga glycerol-uptake protein (≤188 aa/chain): it cannot carry Arg236/Arg273/Glu282
    assert not res["1VKF"]["is_nf_kb"], res["1VKF"]["title"]
    assert res["1VKX"]["is_nf_kb"], res["1VKX"]["title"]
    # 1VKF (≤188 aa Thermotoga protein) cannot carry the high-numbered p65 residues; 1VKX can
    assert res["1VKX"]["recall"] > res["1VKF"]["recall"] and res["1VKX"]["recall"] >= 0.5, res


def _atoms(pdb_text: str):
    import numpy as np
    out = []
    for l in pdb_text.splitlines():
        if l.startswith("ATOM") and len(l) >= 54:
            try:
                out.append((l[21], f"{l[17:20].strip()}{int(l[22:26])}", np.array([float(l[30:38]), float(l[38:46]), float(l[46:54])])))
            except ValueError:
                continue
    return out


def test_hsieh2024_box_hypotheses(rcsb):
    """Why does the hsieh2024 docking land elsewhere?  Pure geometry, no docking: where does the published box sit
    in each candidate structure, under three readings of its size —
      published  28.5×34.5×26.25 Å  (= 76×92×70 AD4 grid points × 0.375 Å; what MD20 docks with)
      points_as_A 76×92×70 Å        (ADT grid-point counts typed into Vina's size field, which is in Å)
      A_as_points 10.7×12.9×9.8 Å   (the Å values read as points and multiplied by 0.375 again)
    and how far the box centre is from the reported residues.  The centre is in Å in both programs, so a
    spacing mix-up changes the box *size*, never where it is."""
    import numpy as np
    P = hsieh2024.PAPER
    ref = set(P["hbond_residues"])
    c = np.asarray(P["box_center"], float)
    sizes = {"published": P["box_size"], "points_as_A": tuple(round(v / 0.375) for v in P["box_size"]),
             "A_as_points": tuple(round(v * 0.375, 2) for v in P["box_size"])}
    out = {}
    for pid in ("1VKX", "1VKF"):
        txt = rcsb(pid).read_text(errors="ignore")
        atoms = _atoms(txt)
        xyz = np.array([a[2] for a in atoms])
        d = np.linalg.norm(xyz - c, axis=1)
        near = []
        for i in np.argsort(d):
            r = f"{atoms[i][0]}:{atoms[i][1]}"
            if r not in near:
                near.append(r)
            if len(near) == 8:
                break
        rec = {"center_to_nearest_atom_A": round(float(d.min()), 2), "residues_nearest_center": near,
               "protein_extent_A": [round(float(v), 1) for v in xyz.max(0) - xyz.min(0)],
               "protein_centroid": [round(float(v), 2) for v in xyz.mean(0)]}
        refpts = np.array([a[2] for a in atoms if a[1] in ref])
        if len(refpts):
            cen = refpts.mean(0)
            rec["reported_residues_centroid"] = [round(float(v), 2) for v in cen]
            rec["center_to_reported_centroid_A"] = round(float(np.linalg.norm(cen - c)), 2)
            rec["reported_chains"] = sorted({a[0] for a in atoms if a[1] in ref})
        for k, sz in sizes.items():
            inside = residues_in_box(txt, c, sz)
            rec[k] = {"size_A": sz, "n_residues_in_box": len(inside),
                      "reported_in_box": sorted(ref & inside), "recall": round(len(ref & inside) / len(ref), 3)}
        out[pid] = rec
    _save("hsieh2024_box_hypotheses", out)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    assert out["1VKX"]["published"]["n_residues_in_box"] >= 0      # a measurement, recorded for the teaching case


def test_hsieh2025_reported_residues_are_in_keap1(rcsb):
    """The reported Keap1-BTB contacts must exist in 4CXT (coordinate-independent); also record how many fall
    inside the published 36×51×45 Å box — that box is larger than the domain, i.e. effectively blind docking."""
    P = hsieh2025.PAPER
    txt = rcsb("4CXT").read_text(errors="ignore")
    ref = P["hbond_residues"] + P["contact_residues"]
    present = protein_residues(txt)
    in_box = residues_in_box(txt, P["box_center"], P["box_size"])
    exist = sorted(set(ref) & present)
    _save("hsieh2025_box", {"reported": ref, "present_in_4CXT": exist, "exist_recall": round(len(exist) / len(ref), 3),
                            "n_in_box": len(in_box), "n_protein_residues": len(present),
                            "box_covers_fraction": round(len(in_box) / max(1, len(present)), 3)})
    assert len(exist) / len(ref) >= 0.8, (exist, ref)


def test_cpp_gate_flags_grp():
    from md20.build.peptide import cpp_gate
    g, rec = cpp_gate(hsieh2025.PAPER["sequence"], target_location="胞內")
    assert g.status == "NEEDS_HUMAN" and rec["prediction"] == "不太可能穿膜"


def test_structure_gates_on_paper_structures(rcsb):
    from md20.build.structure_gate import structure_confidence
    out = {}
    for pid, center in (("1VKX", hsieh2024.PAPER["box_center"]), ("4CXT", hsieh2025.PAPER["box_center"])):
        rep = structure_confidence(rcsb(pid).read_text(errors="ignore"), pocket_center=center)
        out[pid] = rep.to_dict()
    _save("paper_structure_gates", out)
    # 1VKX is 2.9 Å: a resolution warning is expected, not a block
    assert any(g["name"] == "resolution" and g["status"] == "AUTO_FIXED" for g in out["1VKX"]["gates"]), out["1VKX"]


# ------------------------------------------------------------------ heavy: reproduce the docking
def _need_docking():
    pytest.importorskip("meeko")
    pytest.importorskip("pdbfixer")
    try:
        import vina  # noqa: F401
    except ImportError:
        from md20.docking.vina_cli import find_vina_exe
        if not find_vina_exe():
            pytest.skip("no vina")


def _pose_residues(sdf: str, rec_txt: str) -> set[str]:
    from rdkit import Chem
    m = Chem.MolFromMolFile(sdf, removeHs=False, sanitize=False)
    xyz = m.GetConformer().GetPositions()
    return residues_near(rec_txt, xyz, 4.0)


# The two paper reproductions are hours of Vina on a 4-core runner (six ligands at once in a 28×34×26 Å box;
# a 7-mer peptide in a 36×51×45 Å box).  They run in their own non-blocking CI job (MD20_PAPERS=1) with a
# reduced search (exhaustiveness 8), and the result JSON says so — a check of the workflow, not of the
# papers' exact search settings.
PAPER_EXHAUSTIVENESS = 8
PAPERS = pytest.mark.skipif(not os.environ.get("MD20_PAPERS"), reason="set MD20_PAPERS=1 (CI paper-docking job)")


@PAPERS
def test_reproduce_hsieh2024_simultaneous_docking(rcsb, tmp_path):
    _need_docking()
    from md20.build.receptor import prepare_receptor
    from md20.docking import dock, LigandInput, Box
    P = hsieh2024.PAPER
    man = prepare_receptor(rcsb("1VKX"), tmp_path / "rec", keep_hetero=set(), exclude_chains={"C", "D"})
    assert man["status"] != "NEEDS_HUMAN", man["gates"]
    rec = Path(man["receptor_pdb"])
    box = Box(tuple(P["box_center"]), tuple(P["box_size"]), "paper", "Hsieh 2024 §2.13")
    ligs = [LigandInput(l["name"], smiles=l["smiles"]) for l in hsieh2024.LIGANDS]
    res = dock(rec, ligs, box, tmp_path / "dock", mode="simultaneous", exhaustiveness=PAPER_EXHAUSTIVENESS, n_poses=9)
    e = res.entry("joint")
    rank = e["recommended_rank"] or 1
    rtxt = rec.read_text()
    per = {}
    allres = set()
    for l in hsieh2024.LIGANDS:
        r = _pose_residues(e["pose_sdfs"][l["name"]][rank - 1], rtxt)
        allres |= r
        per[l["name"]] = {"label": l["label"], "contacts": sorted(r),
                          **hsieh2024.residue_overlap(r, l["paper_residues"])}
    out = {"search": f"reduced: exhaustiveness {PAPER_EXHAUSTIVENESS} (CI time budget), not the paper's setting",
           "paper_affinity": P["collective_affinity_kcal_mol"], "md20_joint_score": e["poses"][rank - 1]["score"],
           "md20_best_score": e["poses"][0]["score"], "recommended_rank": e["recommended_rank"],
           "recommendation": e["reason"], "pocket": hsieh2024.residue_overlap(allres), "per_ligand": per}
    _save("hsieh2024_docking", out)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    assert e["poses"][0]["score"] < 0


@PAPERS
def test_reproduce_hsieh2025_peptide_docking(rcsb, tmp_path):
    _need_docking()
    from md20.build.receptor import prepare_receptor
    from md20.build.peptide import peptide_smiles
    from md20.docking import dock, LigandInput, Box
    P = hsieh2025.PAPER
    man = prepare_receptor(rcsb("4CXT"), tmp_path / "rec", keep_hetero=set(), ligand_resnames={"SXJ"})
    assert man["status"] != "NEEDS_HUMAN", man["gates"]
    rec = Path(man["receptor_pdb"])
    box = Box(tuple(P["box_center"]), tuple(P["box_size"]), "paper", "Hsieh 2025 §2.13")
    res = dock(rec, [LigandInput("GRP", smiles=peptide_smiles(P["sequence"]))], box, tmp_path / "dock",
               exhaustiveness=PAPER_EXHAUSTIVENESS, n_poses=9)
    e = res.entry("GRP")
    rtxt = rec.read_text()
    poses = []
    for i, p in enumerate(e["poses"][:5]):
        r = _pose_residues(e["pose_sdfs"]["GRP"][i], rtxt)
        ov = hsieh2025.PAPER["hbond_residues"] + hsieh2025.PAPER["contact_residues"]
        poses.append({"rank": p["rank"], "score": p["score"], "cluster": p.get("cluster_size"),
                      "recall_vs_paper": round(len(set(ov) & r) / len(ov), 3), "contacts": sorted(r)})
    out = {"search": f"reduced: exhaustiveness {PAPER_EXHAUSTIVENESS} (CI time budget), not the paper's setting",
           "paper_affinity": P["affinity_kcal_mol"], "recommended_rank": e["recommended_rank"],
           "recommendation": e["reason"], "poses": poses}
    _save("hsieh2025_docking", out)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    assert e["poses"][0]["score"] < 0
