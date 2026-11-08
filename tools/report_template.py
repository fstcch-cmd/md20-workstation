"""Report template (D-59): one demo workflow with synthetic data for EVERY figure kind, rendered in English and
Traditional Chinese.  The numbers are invented to exercise layout and wording; they are not a simulation result.

D-155: this template deliberately uses a trypsin / benzamidine (BEN) co-crystal system, NOT the teaching case.
It is a *figure-coverage self-check*, not a demo of the project: the `pose_rmsd` figure (score vs RMSD to the
co-crystal pose) requires a known experimental binding pose, which the teaching case — six djulis metabolites on
NF-κB p65 (no co-crystal) — structurally cannot provide.  The user-facing demos (GUI preview, theme preview) use
the real teaching case instead; see DECISIONS D-155.  The rendered HTML is labelled "synthetic demo data" and
named `trypsin_benzamidine`, so it is not mistaken for a teaching result.

Usage: python tools/report_template.py OUT_DIR      (CI job `report-template` runs it with RDKit installed, so the
compound and 2D-interaction figures appear too)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def _sdf(xyz, elems, name="LIG") -> str:
    lines = [name, "  synthetic", "", f"{len(xyz):3d}  0  0  0  0  0  0  0  0  0999 V2000"]
    for (x, y, z), e in zip(xyz, elems):
        lines.append(f"{x:10.4f}{y:10.4f}{z:10.4f} {e:<3} 0  0  0  0  0  0  0  0  0  0  0  0")
    return "\n".join(lines + ["M  END", "$$$$", ""])


def _rot(rng, scale: float) -> np.ndarray:
    a = rng.normal(0, scale, 3)
    cx, cy, cz = np.cos(a); sx, sy, sz = np.sin(a)
    return (np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]]) @ np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
            @ np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]))


def _rdkit_sdf(smiles: str, centre, rng, path: Path) -> bool:
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except Exception:  # noqa: BLE001
        return False
    m = Chem.AddHs(Chem.MolFromSmiles(smiles))
    AllChem.EmbedMolecule(m, randomSeed=int(rng.integers(1, 10_000)))
    conf = m.GetConformer()
    pos = conf.GetPositions()
    shift = np.asarray(centre) - pos.mean(0)
    for i in range(m.GetNumAtoms()):
        x, y, z = pos[i] + shift
        conf.SetAtomPosition(i, (float(x), float(y), float(z)))
    w = Chem.SDWriter(str(path)); w.write(m); w.close()
    return True


def build(root: Path, lang: str):
    from test_report_v2 import make_wf
    from md20.util.jsonio import atomic_write_json
    from md20.analysis.plots import plot_stage_log, plot_minimization, plot_overview
    from md20.docking.screen import screen_plots, rank_screen
    import pandas as pd
    rng = np.random.default_rng(11)
    wf = make_wf(root, lang)
    centre = np.array([20.0, 20.0, 20.0])
    # ---- receptor: residues on a shell around the pocket
    names = ["ASP", "SER", "GLY", "TRP", "LEU", "HIS", "VAL", "TYR", "LYS", "PHE"]
    rec_lines, serial = [], 1
    for i in range(80):
        v = rng.normal(0, 1, 3); v /= np.linalg.norm(v)
        p = centre + v * rng.uniform(5.5, 13)
        rn = names[i % len(names)]
        for an, el, off in (("N", "N", (0, 0, 0)), ("CA", "C", (1.4, 0, 0)), ("C", "C", (2.0, 1.3, 0)), ("O", "O", (1.5, 2.3, 0)),
                            ("CB", "C", (1.8, -1.2, 0.8)), ("OG" if rn == "SER" else "CG", "O" if rn == "SER" else "C", (2.5, -2.0, 1.4))):
            x, y, z = p + off
            rec_lines.append(f"ATOM  {serial:5d}  {an:<3} {rn} A{170 + i:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00           {el}")
            serial += 1
    rec = root / "receptor_docking.pdb"
    rec.write_text("\n".join(rec_lines) + "\nEND\n")
    wf._mark("receptor_docking", path=str(rec))
    # ---- docking: two ligands, nine poses each, pose SDFs
    ddir = root / "docking"; ddir.mkdir(exist_ok=True)
    entries, sel = [], {"mode": "independent", "ligands": {}}
    shape = rng.normal(0, 1.3, (9, 3)); shape -= shape.mean(0)
    for li, (lig, smi, best) in enumerate((("BEN", "NC(=[NH2+])c1ccccc1", -6.1), ("PGA", "[O-]C(=O)[C@@H]1CCC(=O)N1", -5.2))):
        poses, sdfs = [], []
        for r in range(1, 10):
            c = centre + (rng.normal(0, 0.8, 3) if r <= 4 else rng.normal(0, 4.5, 3))
            pth = ddir / f"{lig}_pose{r}.sdf"
            if not _rdkit_sdf(smi, c, rng, pth):
                xyz = c + shape @ _rot(rng, 0.3 if r <= 4 else 3.0).T   # same molecule, small vs large reorientation
                pth.write_text(_sdf(xyz, ["C", "C", "C", "N", "C", "C", "O", "C", "N"], lig))
            sdfs.append(str(pth))
            poses.append({"rank": r, "score": round(best + 0.18 * (r - 1) + rng.normal(0, 0.05), 2), "cluster": 1 if r <= 4 else r - 3,
                          "cluster_size": 4 if r <= 4 else 1, "contacts": int(12 - r // 2),
                          "rmsd_ref": (round(0.4 + 0.5 * (r - 1) + rng.normal(0, 0.2), 2) if lig == "BEN" else None),
                          "recommended": r == 1})
        entries.append({"name": lig, "ligands": [lig], "recommended_rank": 1, "reason": "rank 1, largest cluster, redocking ≤ 2 Å",
                        "smiles": smi, "poses": poses, "pose_sdfs": {lig: sdfs}})
        sel["ligands"][lig] = {"rank": 1, "entry": lig, "score": poses[0]["score"], "sdf": sdfs[0]}
    # ---- simultaneous docking of BEN + PGA (D-60): joint poses, two subsites side by side
    jposes, jsdf = [], {"BEN": [], "PGA": []}
    for r in range(1, 10):
        off = np.array([3.4, 0, 0]) if r != 6 else np.array([-3.4, 0.5, 0])          # rank 6 swaps the two ligands
        cb = centre - off / 2 + rng.normal(0, 0.5 if r <= 5 else 2.5, 3)
        cp = centre + off / 2 + rng.normal(0, 0.5 if r <= 5 else 2.5, 3)
        for lig, c in (("BEN", cb), ("PGA", cp)):
            pth = ddir / f"joint_{lig}_pose{r}.sdf"
            pth.write_text(_sdf(c + shape @ _rot(rng, 0.3).T * 0.6, ["C", "C", "C", "N", "C", "C", "O", "C", "N"], lig))
            jsdf[lig].append(str(pth))
        dll = float(np.round(rng.uniform(3.4, 4.3) if r not in (3, 8) else rng.uniform(2.1, 3.0), 2))
        jposes.append({"rank": r, "score": round(-9.4 + 0.25 * (r - 1) + rng.normal(0, 0.05), 2), "cluster": 1 if r <= 5 else r - 4,
                       "cluster_size": 5 if r <= 5 else 1, "contacts": 20, "contacts_per_ligand": [int(14 - r // 2), int(12 - r // 2) if r != 7 else 4],
                       "min_ll_distance": dll, "clash": dll < 3.3, "rmsd_ref": None, "recommended": r == 1})
    entries.append({"name": "joint", "ligands": ["BEN", "PGA"], "recommended_rank": 1, "reason": "rank 1, ligands 3.3–4.5 Å, both buried",
                    "smiles": {"BEN": "NC(=[NH2+])c1ccccc1", "PGA": "[O-]C(=O)[C@@H]1CCC(=O)N1"}, "poses": jposes, "pose_sdfs": jsdf})
    atomic_write_json({"mode": "independent", "params": {"scoring": "vina", "exhaustiveness": 16, "ligand_charges": [1, -1]},
                       "box": {"center": centre.tolist(), "size": [22, 22, 22], "source": "co-crystal BEN"}, "entries": entries},
                      ddir / "docking_results.json")
    wf._mark("docking", result=str(ddir / "docking_results.json"), mode="independent")
    wf._mark("pose_selection", selection=sel)
    # ---- screening: 40 compounds with SDFs, ranking, plots, library manifest
    sdir = root / "screen"; sdir.mkdir(exist_ok=True)
    lib = {"entries": {}}
    res = {"params": {"exhaustiveness": 8, "n_poses": 3}, "entries": {}}
    smiles = ["c1ccccc1O", "CC(=O)Oc1ccccc1C(=O)O", "Cn1cnc2c1c(=O)n(C)c(=O)n2C", "NC(=[NH2+])c1ccccc1", "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
              "CCN(CC)CC", "c1ccc2ccccc2c1", "O=C(O)CCC(=O)O", "CC(C)Cc1ccc(C(C)C(=O)O)cc1", "COc1ccc(CCN)cc1"]
    for i in range(40):
        name = f"cmp{i + 1:02d}"
        smi = smiles[i % len(smiles)]
        p = sdir / f"{name}.sdf"
        if not _rdkit_sdf(smi, centre, rng, p):
            p.write_text(_sdf(centre + rng.normal(0, 1.2, (8, 3)), ["C"] * 8, name))
        heavy = int(rng.integers(8, 32))
        lib["entries"][name] = {"status": "OK", "path": str(p), "heavy_atoms": heavy}
        res["entries"][name] = {"status": "OK", "score": round(-4.0 - 0.12 * heavy + rng.normal(0, 0.6), 2), "heavy_atoms": heavy,
                                "cluster_size": int(rng.integers(1, 5)), "contacts": int(rng.integers(4, 14)),
                                "recommendation_status": "PASS" if i % 5 else "AUTO_FIXED", "smiles": smi}
    lib["entries"]["cmp41"] = {"status": "FAILED", "error": "PubChem not reachable (manual upload expected)"}
    atomic_write_json(res, sdir / "screen_results.json")
    atomic_write_json(lib, sdir / "library_manifest.json")
    plots = screen_plots(rank_screen(res, top_n=40), sdir)
    wf._mark("screen_library", manifest=str(sdir / "library_manifest.json"))
    wf._mark("screen_docking", results=str(sdir / "screen_results.json"), plots=plots)
    wf.cfg["screen"] = {"library": "compound_library.xlsx", "exhaustiveness": 8, "n_poses": 3, "top_n": 20, "select": ["cmp03", "cmp12"]}
    atomic_write_json(wf.cfg, wf.dir / "config.json")
    # ---- simulation runs with stage logs (equilibration figures)
    cases, runs = {}, {}
    for key in ("apo", "docked_BEN"):
        case = wf.project.new_case(f"demo_{key}")
        run = case.new_run({"tier": "teaching", "hmr": True, "stages": []}, reason="template")
        frames = {}
        for stg, n, T0 in (("nvt", 200, 50.0), ("npt", 250, 300.0), ("production", 500, 300.0)):
            t = np.linspace(0, {"nvt": 200, "npt": 500, "production": 10000}[stg], n)
            temp = (np.clip(T0 + (300 - T0) * t / (0.6 * t[-1]), None, 300) if stg == "nvt" else np.full(n, 300.0)) + rng.normal(0, 2.5, n)
            df = pd.DataFrame({"time_ps": t, "temperature_k": temp, "potential_kj_mol": -5.2e5 + 2e3 * np.exp(-t / (t[-1] / 3)) + rng.normal(0, 300, n)})
            if stg != "nvt":
                df["density_g_ml"] = 1.02 + 0.01 * np.exp(-t / (t[-1] / 5)) + rng.normal(0, 0.002, n)
                df["volume_nm3"] = 280 - 3 * np.exp(-t / (t[-1] / 5)) + rng.normal(0, 0.4, n)
            frames[stg] = df
            sd = run.dir / "stages" / stg; sd.mkdir(parents=True, exist_ok=True)
            figs = plot_stage_log(df, run.dir / "figures" / f"{stg}_timeseries", title=f"{stg.upper()}", target_temperature_k=300.0,
                                  ensemble="NVT" if stg == "nvt" else "NPT", html=False)
            checks = [{"check": "temperature within 5 K", "ok": True, "mean_k": 300.1}]
            if stg != "nvt":
                checks.append({"check": "density variation < 3 %", "ok": not (key == "apo" and stg == "npt"), "cv": 0.012 if key != "apo" else 0.034})
            atomic_write_json({"acceptance": {"status": "PASS", "checks": checks}, "figures": figs}, sd / f"{stg}_complete.json")
        md_ = run.dir / "stages" / "minimize"; md_.mkdir(parents=True, exist_ok=True)
        e = [-4.1e5, -4.9e5, -5.15e5]
        atomic_write_json({"energies_kj_mol": e, "figures": plot_minimization(e, run.dir / "figures" / "minimize_energy")}, md_ / "minimize_complete.json")
        plot_overview(frames, run.dir / "figures" / "run_overview")
        from md20.engine.replicas import _overlay
        reps = [(f"r{k}", frames["production"].assign(temperature_k=frames["production"]["temperature_k"] + rng.normal(0, 1.5, len(frames["production"])),
                                                       potential_kj_mol=frames["production"]["potential_kj_mol"] + rng.normal(k * 200, 300, len(frames["production"]))))
                for k in range(3)]
        _overlay(reps, case.dir / "replicas" / "production_replicas")
        cases[key] = {"case_id": case.case_id, "mode": "apo" if key == "apo" else "docked_single", "ligands": [] if key == "apo" else ["BEN"]}
        runs[key] = {"case_id": case.case_id, "status": "COMPLETE", "run_ids": [run.run_id]}
    # ---- umbrella window histograms for the binding section
    from md20.analysis.plots import plot_umbrella_histograms
    win = {round(c, 3): rng.normal(c, 0.04, 400) for c in np.arange(0.45, 1.9, 0.08)}
    hist = plot_umbrella_histograms(win, wf.dir / "binding_BEN" / "umbrella_histograms")
    st = wf.state()
    st["steps"]["binding"]["results"]["BEN"]["figures"]["histograms"] = hist
    wf.cfg.setdefault("md", {})["replicas"] = 3
    atomic_write_json(wf.cfg, wf.dir / "config.json")
    # ---- multi-ligand system (D-60): geometry check record and ligand–ligand distance during MD
    st["multi_ligand"] = {"status": "AUTO_FIXED", "ligands": ["BEN", "PGA"], "excluded": [], "auto_excluded": [], "culprit": None,
                          "why": ["PGA 以剛體微調（旋轉 8.2°、平移 0.6 Å，RMSD 0.7 Å ≤ 2.0 Å，結合模式不變）消除重疊或穿環",
                                  "PGA nudged as a rigid body (rotation 8.2°, shift 0.6 Å, RMSD 0.7 Å ≤ 2.0 Å, same binding mode) to clear overlaps or ring piercing"],
                          "adjusted": {"PGA": {"rmsd": 0.7, "rotation_deg": 8.2, "shift_A": 0.6}},
                          "per_ligand": {"BEN": {"contacts": 31, "overlaps": 0, "piercings": 0, "floating": False, "partners": []},
                                         "PGA": {"contacts": 22, "overlaps": 0, "piercings": 0, "floating": False, "partners": []}}}
    tm = np.linspace(0, 2, 101)
    mm = json.loads(Path(st["steps"]["analysis"]["summaries"]["docked_BEN"]["metrics_file"]).read_text(encoding="utf-8"))
    mm["ligand_ligand_distance_A"] = {"L01-L02": (4.6 + 0.4 * np.tanh(tm * 2) + rng.normal(0, 0.25, tm.size)).tolist()}
    atomic_write_json(mm, wf.dir / "m_docked_multi.json")
    st["steps"]["analysis"]["summaries"]["docked_multi"] = {**st["steps"]["analysis"]["summaries"]["docked_BEN"],
                                                            "metrics_file": str(wf.dir / "m_docked_multi.json")}
    cases["docked_multi"] = {**cases["docked_BEN"], "mode": "docked_multi", "ligands": ["BEN", "PGA"]}
    runs["docked_multi"] = dict(runs["docked_BEN"])
    # ---- cooperativity cycle (D-61): BEN and PGA pulled alone and from the shared pocket
    from md20.sampling.multi import cooperativity, compare_binding
    b = st["steps"]["binding"]["results"]
    base = {k: v for k, v in b["BEN"].items() if k not in ("figures",)}
    b["PGA"] = {**base, "ligand": "PGA", "delta_pmf_kj_mol": 15.2, "delta_pmf_err_kj_mol": 1.6, "figures": {}}
    b["BEN"].update(ligand="BEN", status="PASS")
    b["multi:BEN"] = {**base, "ligand": "BEN", "context": "multi:docked_multi", "delta_pmf_kj_mol": 28.9, "delta_pmf_err_kj_mol": 1.9, "figures": {}}
    b["multi:PGA"] = {**base, "ligand": "PGA", "context": "multi:docked_multi", "delta_pmf_kj_mol": 19.0, "delta_pmf_err_kj_mol": 1.7, "figures": {}}
    # D-96: synthetic template data carry a synthetic *qualified* assessment so that the comparison and cooperativity
    # figures can be shown; real results get theirs from sampling/assessment.py
    from md20.sampling.assessment import THRESHOLDS_VERSION
    for v in b.values():
        v["status"] = "PASS"
        v.setdefault("assessment", {"schema": "md20.assessment.pmf/1", "thresholds_version": THRESHOLDS_VERSION,
                                    "synthetic_template": True, "diagnostics": [], "failed": [], "unknown": [], "conflicts": [],
                                    "sampling_adequate": True, "reasons": [],
                                    "eligibility": {"delta_pmf_curve": True, "delta_pmf_path_specific": True,
                                                    "dG_standard": v.get("dG_standard_kj_mol") is not None,
                                                    "affinity_ranking": v.get("dG_standard_kj_mol") is not None}})
        v.setdefault("condition", {"cv": "com_distance_radial", "temperature_k": 300.0, "anchor": "automatic",
                                   "backbone_restraint_kj_mol_nm2": 100.0, "spectators": []})
    ctx = {"single": ["BEN", "PGA"], "multi:docked_multi": ["multi:BEN", "multi:PGA"]}
    comp = compare_binding(b, contexts=ctx)
    comp["cooperativity"] = cooperativity(b, ctx)
    st["steps"]["binding"]["comparison"] = comp
    st["steps"]["md_cases"]["cases"] = cases
    st["steps"]["md_runs"] = {"status": "PASS", "runs": runs}
    subsystems(root, wf, st, rng)                      # D-82
    atomic_write_json(wf.cfg, wf.dir / "config.json")
    atomic_write_json(st, wf.state_path)
    return wf


# ---------------------------------------------------------------------------------------------- D-82 subsystems
AA = "ACDEFGHIKLMNPQRSTVWY"
THREE = {"A": "ALA", "C": "CYS", "D": "ASP", "E": "GLU", "F": "PHE", "G": "GLY", "H": "HIS", "I": "ILE", "K": "LYS", "L": "LEU",
         "M": "MET", "N": "ASN", "P": "PRO", "Q": "GLN", "R": "ARG", "S": "SER", "T": "THR", "V": "VAL", "W": "TRP", "Y": "TYR"}


def _chain(seq: str, ca: np.ndarray, b) -> list[dict]:
    out = []
    for i, (aa, x) in enumerate(zip(seq, ca), 1):
        atoms = {}
        for nm, el, off in (("N", "N", (-1.2, 0.5, 0)), ("CA", "C", (0, 0, 0)), ("C", "C", (1.2, 0.6, 0)), ("O", "O", (1.4, 1.8, 0)),
                            ("CB", "C", (0.3, -1.3, 0.9))):
            if nm == "CB" and aa == "G":
                continue
            p = x + np.asarray(off)
            atoms[nm] = {"x": float(p[0]), "y": float(p[1]), "z": float(p[2]), "b": float(b[i - 1]), "element": el, "altloc": "", "name": nm}
        out.append({"resname": THREE[aa], "resseq": i, "icode": "", "one": aa, "atoms": atoms})
    return out


def _fold_demo(root: Path, wf, st: dict, rng) -> None:
    """A receptor + peptide complex predicted (synthetic coordinates), superposed by build/fold.place_peptide."""
    from md20.build import fold as F
    fdir = root / "fold_demo"
    fdir.mkdir(exist_ok=True)
    rseq = "".join(rng.choice(list(AA), 70))
    k = np.arange(70)
    ca_ref = np.c_[2.3 * np.cos(k * 1.745) + 0.15 * k, 2.3 * np.sin(k * 1.745), 1.5 * k / 3.6] * 2.2 / 1.5
    ref = {"A": _chain(rseq, ca_ref, np.full(70, 0.0))}
    F.write_pdb(ref, fdir / "actual_receptor.pdb", remark="synthetic actual receptor")
    R, _, _ = F.kabsch(rng.normal(0, 1, (4, 3)), rng.normal(0, 1, (4, 3)))
    noise = rng.normal(0, 0.45, (70, 3))
    noise[30:38] += rng.normal(0, 2.4, (8, 3))                     # a loop that the prediction gets wrong
    ca_pred = (ca_ref + noise) @ R.T + np.array([12.0, -4.0, 3.0])
    pep = "GIGAVLKVLTTGLPALISWIKRKRQQ"
    j = np.arange(len(pep))
    site = ca_ref[40:60].mean(0) + np.array([9.5, 0.0, 0.0])
    ca_pep_ref = site + np.c_[1.5 * j - 19.0, 2.3 * np.cos(j * 1.745), 2.3 * np.sin(j * 1.745)] * np.array([0.6, 1, 1])
    ca_pep = ca_pep_ref @ R.T + np.array([12.0, -4.0, 3.0])
    pl_rec = np.clip(85 + rng.normal(0, 4, 70), 0, 100); pl_rec[30:38] -= 30
    pl_pep = np.clip(np.r_[np.linspace(48, 80, 4), 82 + rng.normal(0, 3, len(pep) - 8), np.linspace(78, 44, 4)], 0, 100)
    pred = {"A": _chain(rseq, ca_pred, pl_rec), "B": _chain(pep, ca_pep, pl_pep)}
    F.write_pdb(pred, fdir / "predicted_complex.pdb", remark="synthetic predicted complex")
    by = {c: [round(x, 2) for x in F.residue_plddt(v)] for c, v in pred.items()}
    r = F.FoldResult(engine="boltz", sequences=[rseq, pep], chains=["A", "B"], peptide_chain="B", peptide_sequence=pep,
                     pdb_path=str(fdir / "predicted_complex.pdb"), per_residue_plddt=by["B"], plddt_by_chain=by,
                     mean_plddt=round(float(np.mean(by["B"])), 2), iptm=0.71, runtime_s=412.0, device="cuda", status="PASS")
    pl = F.place_peptide(r, fdir, reference=fdir / "actual_receptor.pdb")
    st.setdefault("fold", {})["MEL"] = {"request": {"mode": "complex", "sequence": pep, "engine": "auto", "accept_low": False,
                                                    "accept_rmsd": False, "reference": str(fdir / "actual_receptor.pdb")},
                                        **r.to_dict(), "placement": pl.to_dict(), "notes": pl.notes, "complex_pose": ""}
    sel = st["steps"]["pose_selection"]["selection"]["ligands"]
    sel["MEL"] = {"rank": 1, "sdf": "", "score": None, "rmsd_ref": None, "entry": "MEL", "source": "fold_complex"}
    wf.cfg["ligands"].append({"name": "MEL", "sequence": pep, "fold": "complex", "target_location": "extracellular-membrane"})


def _membrane_demo(root: Path, wf, st: dict, rng, *, cg: bool = False) -> dict:
    """Synthetic POPC bilayer (64 lipids per leaflet) with a peptide adsorbing on the upper surface."""
    from md20.analysis.membrane_report import membrane_report_data
    nF, nL = 60, 64
    t = np.linspace(0, 20.0 if not cg else 2000.0, nF)
    L = 6.4 * (1 + 0.01 * np.exp(-t / t[-1] * 6))[:, None] * np.array([1, 1, 0]) + np.array([0, 0, 9.0])
    L += rng.normal(0, 0.006, (nF, 3)) * np.array([1, 1, 0])
    g = (np.arange(8) + 0.5) / 8
    gx, gy = np.meshgrid(g, g)
    xy = np.c_[gx.ravel(), gy.ravel()]
    heads = np.zeros((nF, 2 * nL, 3))
    for f in range(nF):
        for k, zc in enumerate((1.9, -1.9)):
            p = (xy + rng.normal(0, 0.02, xy.shape)) * L[f, :2]
            dz = -0.25 * np.exp(-((p[:, 0] - 3.2) ** 2 + (p[:, 1] - 3.2) ** 2) / 1.5) * np.sign(zc)   # thinning under the peptide
            heads[f, k * nL:(k + 1) * nL] = np.c_[p, zc + dz + rng.normal(0, 0.08, nL)]
    heads[..., 2] += 4.5
    water = np.c_[rng.uniform(0, 6.4, (nF, 400, 2)), rng.choice([1, -1], (nF, 400, 1)) * rng.uniform(2.6, 4.4, (nF, 400, 1)) + 4.5]
    acyl = np.c_[rng.uniform(0, 6.4, (nF, 600, 2)), rng.uniform(-1.6, 1.6, (nF, 600, 1)) + 4.5]
    pep = "GIGAVLKVLTTGLPALISWIKRKRQQ"
    depth = 0.6 * np.exp(-t / (t[-1] / 5)) - 0.15 + rng.normal(0, 0.05, nF)            # nm above the P plane → adsorbed
    j = np.arange(len(pep))
    ca = np.zeros((nF, len(pep), 3))
    for f in range(nF):
        ang = np.deg2rad(80 + rng.normal(0, 6))
        ca[f] = np.c_[3.2 + (j - 12.5) * 0.15 * np.sin(ang), 3.2 + 0.2 * np.cos(j * 1.745), 1.9 + 4.5 + depth[f] + (j - 12.5) * 0.15 * np.cos(ang)
                      + 0.2 * np.sin(j * 1.745)]
    res_xyz = [ca[:, i:i + 1, :] + np.where(pep[i] in "KR", -0.25, 0.1) * np.array([0, 0, 1]) for i in range(len(pep))]
    dens = {"phosphate": heads[..., 2], "water": water[..., 2], "acyl chains": acyl[..., 2], "peptide": ca[..., 2]}
    kw = {}
    if cg:
        names = ["NC3-PO4", "PO4-GL1", "GL1-C1A", "C1A-D2A", "D2A-C3A", "C3A-C4A", "GL2-C1B", "C1B-C2B", "C2B-C3B", "C3B-C4B"]
        xyz, pairs, n0 = [], {}, 0
        for b, p2 in zip(names, np.linspace(0.45, 0.18, len(names))):
            th = np.arccos(np.sqrt((2 * p2 + 1) / 3))
            phi = rng.uniform(0, 2 * np.pi, 50)
            v = np.c_[np.sin(th) * np.cos(phi), np.sin(th) * np.sin(phi), np.cos(th) * np.ones(50)] * 0.47
            xyz += [np.zeros((50, 3)), v]
            pairs[b] = [(n0 + i, n0 + 50 + i) for i in range(50)]
            n0 += 100
        kw = {"p2_xyz": np.repeat(np.vstack(xyz)[None], 3, 0), "p2_pairs": pairs}
    else:
        groups, xyz, n0 = {}, [], 0
        for tail, prof in (("sn1", (0.20, 0.21, 0.21, 0.21, 0.20, 0.20, 0.19, 0.18, 0.16, 0.14, 0.12, 0.10, 0.08, 0.05, 0.03)),
                           ("sn2", (0.16, 0.18, 0.19, 0.19, 0.18, 0.12, 0.10, 0.14, 0.15, 0.13, 0.11, 0.09, 0.07, 0.05, 0.03))):
            for c, s_ in enumerate(prof, 2):
                th = np.arccos(np.sqrt((1 - 2 * s_) / 3))
                phi = rng.uniform(0, 2 * np.pi, 40)
                h = np.c_[np.sin(th) * np.cos(phi), np.sin(th) * np.sin(phi), np.cos(th) * np.ones(40)] * 0.109
                xyz += [np.zeros((40, 3)), h]
                groups[f"{tail}:C{'3' if tail == 'sn1' else '2'}{c}"] = [(n0 + i, n0 + 40 + i) for i in range(40)]
                n0 += 80
        kw = {"scd_xyz": np.repeat(np.vstack(xyz)[None], 3, 0), "scd_groups": groups}
    d = membrane_report_data(time_ns=t, box=L, head_xyz=heads, composition={"POPC": 1.0}, temperature_k=310.0, mtype="surface",
                             resolution="coarse-grained" if cg else "atomistic", density_z=dens,
                             solute_xyz=None if cg else ca, residue_xyz=None if cg else res_xyz,
                             residue_names=[f"{THREE[a]}{i + 1}" for i, a in enumerate(pep)], ca_xyz=None if cg else ca,
                             water_o_xyz=water, **kw)
    d["solute_xy_nm"] = [3.2, 3.2]
    from md20.util.jsonio import atomic_write_json
    p = root / ("membrane_cg.json" if cg else "membrane_surface.json")
    atomic_write_json(d, p)
    return {"file": str(p), "data": d}


def _long_run_demo(root: Path, wf, st: dict, rng) -> None:
    from md20.engine.longrun import plan_long_run
    from md20.util.jsonio import atomic_write_json
    plan = plan_long_run(n_atoms=31000, production_ns=1000.0, timestep_fs=4.0, ns_per_day=330.0, n_solute_atoms=3600,
                         disk_free_gb=400.0, confirmed=True)
    st.setdefault("long_run", {})["docked_BEN"] = {**{k: v for k, v in plan.to_dict().items() if k != "decisions"},
                                                   "actual": {"production_ns": 1000.0, "disk_gb": round(plan.total_gb * 1.08, 2), "days": 3.6}}
    s = st["steps"]["analysis"]["summaries"]["docked_BEN"]
    m = json.loads(Path(s["metrics_file"]).read_text(encoding="utf-8"))
    rf = np.asarray(m["rmsf_ca_A"], float)
    sm = {"status": "PASS", "time_ns": np.linspace(0, 1000, 2000).tolist(),
          "rmsd_backbone_A": (1.3 + 0.3 * (1 - np.exp(-np.linspace(0, 10, 2000))) + rng.normal(0, 0.12, 2000)).tolist(),
          "rmsf_residues": m["rmsf_residues"], "rmsf_first_half_A": (rf + rng.normal(0, 0.08, rf.size)).tolist(),
          "rmsf_second_half_A": (rf * 1.04 + rng.normal(0, 0.08, rf.size)).tolist()}
    atomic_write_json(sm, root / "stream_metrics_docked_BEN.json")
    m["stream_metrics_file"] = str(root / "stream_metrics_docked_BEN.json")
    atomic_write_json(m, Path(s["metrics_file"]))


def subsystems(root: Path, wf, st: dict, rng) -> None:
    """D-82: fold, membrane, long run and coarse-grained data, so the template shows F43–F57."""
    from md20.build import martini as MA
    _fold_demo(root, wf, st, rng)
    mem = _membrane_demo(root, wf, st, rng)
    st["steps"]["analysis"]["summaries"]["surface_MEL"] = {"status": "PASS", "membrane_file": mem["file"]}
    wf.cfg.setdefault("md", {})["membrane"] = {"type": "surface", "lipids": "mammalian"}
    _long_run_demo(root, wf, st, rng)
    cg = _membrane_demo(root, wf, st, rng, cg=True)
    plan = MA.plan_cg_membrane(root / "receptor_docking.pdb", root / "cg", avail=MA.availability(find_spec=lambda n: object(), which=lambda n: "/bin/" + n))
    st["coarse_grained"] = {"POPC_CG": {"plan": plan.to_dict(), "membrane_file": cg["file"]}}


def main(out: Path) -> int:
    from md20.report.workflow_report import build_workflow_report
    out.mkdir(parents=True, exist_ok=True)
    counts = {}
    for lang in ("en", "zh"):
        root = out / f"_work_{lang}"
        wf = build(root, lang)
        banner = ("<div style='background:#fff4e5;border:1px solid #f0b46c;padding:10px 14px;margin:0 0 18px;font-size:14px'>"
                  + ("<b>報告範本（合成示範資料）</b>：本檔所有數字與圖都是為了展示版面、圖表種類與通用解讀用語而產生的合成資料，"
                     "不是任何真實模擬結果，請勿引用。" if lang == "zh" else
                     "<b>Report template (synthetic demo data)</b>: every number and figure in this file was generated to show the layout, "
                     "the figure types and the general interpretation wording. It is not the result of any real simulation; do not cite it.")
                  + "</div>")
        p = build_workflow_report(wf, out / f"MD20_report_template_{lang}.html", lang=lang, banner_html=banner)
        idx = json.loads((wf.dir / "report_figures" / f"index_{lang}.json").read_text(encoding="utf-8"))
        counts[lang] = len(idx["figures"])
        kinds = sorted({f["kind"] for f in idx["figures"]})
        print(lang, p, counts[lang], "figures,", len(kinds), "kinds:", ", ".join(kinds))
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "report_template")))
