"""Report template (D-59): one demo workflow with synthetic data for EVERY figure kind, rendered in English and
Traditional Chinese.  The numbers are invented to exercise layout and wording; they are not a simulation result.

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
    st["steps"]["md_cases"]["cases"] = cases
    st["steps"]["md_runs"] = {"status": "PASS", "runs": runs}
    atomic_write_json(st, wf.state_path)
    return wf


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
