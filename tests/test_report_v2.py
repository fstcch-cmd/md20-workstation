"""D-52: project-grade workflow report — section order, numbered figures and tables, data-driven interpretation, both languages."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest

from md20.project.store import Project
from md20.util.jsonio import atomic_write_json
from md20.workflow import Workflow, example_config
from md20.report.workflow_report import build_workflow_report, methods_text, actual_values
from md20.report import interpret as I


def make_wf(tmp_path, lang="en"):
    cfg = copy.deepcopy(example_config())
    cfg["language"] = lang
    cfg["ligands"].append({"name": "GRP", "sequence": "GGGGGKP", "target_location": "intracellular"})
    wf = Workflow(Project.create(tmp_path, "demo"), cfg)
    atomic_write_json({"gates": [{"name": "resolution", "status": "AUTO_FIXED", "explanation": "2.9 Å"},
                                 {"name": "species", "status": "PASS", "explanation": "ok"}]}, wf.dir / "structure_gates.json")
    dres = {"mode": "independent", "params": {"scoring": "vina", "exhaustiveness": 16},
            "box": {"center": [1, 2, 3], "size": [22, 22, 22], "source": "co-crystal BEN"},
            "entries": [{"name": "BEN", "ligands": ["BEN"], "recommended_rank": 1, "reason": "rank 1",
                         "poses": [{"rank": 1, "score": -6.1, "cluster": 1, "cluster_size": 6, "contacts": 11, "rmsd_ref": 0.4, "recommended": True},
                                   {"rank": 2, "score": -5.6, "cluster": 2, "cluster_size": 2, "contacts": 8, "rmsd_ref": 3.1, "recommended": False}]}]}
    atomic_write_json(dres, wf.dir / "dock.json")
    wf._mark("docking", result=str(wf.dir / "dock.json"), mode="independent")
    wf._mark("pose_selection", selection={"mode": "independent", "ligands": {"BEN": {"rank": 1, "entry": "BEN", "score": -6.1}}})
    t = np.linspace(0, 2, 101)
    rng = np.random.default_rng(3)
    res = [f"{n}{i}" for i, n in zip(range(16, 246), ["ILE", "VAL", "GLY", "SER", "ASP", "HIS", "LYS"] * 40)]
    base_rmsf = 0.5 + 0.8 * np.abs(np.sin(np.arange(len(res)) / 9.0)) + rng.normal(0, 0.05, len(res))
    for key, base in (("apo", 1.2), ("docked_BEN", 1.0)):
        m = {"time_ns": t.tolist(), "rmsd_backbone_A": (base + 0.3 * (1 - np.exp(-t * 3)) + rng.normal(0, 0.05, t.size)).tolist(),
             "rg_protein_A": (16.4 + rng.normal(0, 0.05, t.size)).tolist(), "rmsf_residues": res,
             "rmsf_ca_A": (base_rmsf - (0.45 * (np.abs(np.arange(len(res)) - 173) < 5) if key != "apo" else 0)).tolist()}
        if key != "apo":
            m["ligands"] = {"L01": {"rmsd_in_pocket_A": (0.8 + 0.4 * (1 - np.exp(-t * 4)) + rng.normal(0, 0.1, t.size)).tolist(),
                                    "com_distance_to_pocket_A": (2.0 + rng.normal(0, 0.2, t.size)).tolist(),
                                    "polar_contacts": (3 + rng.integers(0, 2, t.size)).tolist(),
                                    "contact_frequency": {"ASP189": 0.92, "SER190": 0.71, "GLY219": 0.66, "SER195": 0.41, "TRP215": 0.22}}}
        atomic_write_json(m, wf.dir / f"m_{key}.json")
    # D-58 extended analyses (synthetic, shapes as written by analysis.extended)
    from md20.analysis.extended import pca, free_energy_landscape, cluster_from_rmsd, cross_correlation, histogram_overlap_matrix
    te = t[::2]
    xyz = rng.normal(0, 0.3, (te.size, 30, 3)); xyz[te.size // 2:, :, 0] += 1.5
    pc = pca(xyz); pr = np.asarray(pc["projection"]); pc["landscape"] = free_energy_landscape(pr[:, 0], pr[:, 1])
    D = np.abs(np.subtract.outer(np.arange(te.size), np.arange(te.size))) * 0.05
    for key in ("apo", "docked_BEN"):
        e = {"time_ns": te.tolist(), "errors": {},
             "dssp": {"fraction": {"H": (0.35 + 0 * te).tolist(), "E": (0.2 + 0 * te).tolist(), "C": (0.45 + 0 * te).tolist()}},
             "pca": pc, "clusters": cluster_from_rmsd(D, 2.0), "dccm": {"matrix": cross_correlation(xyz).round(3).tolist(),
                                                                         "residues": [f"R{i}" for i in range(30)]},
             "sasa_protein": {"total_A2": (11000 + rng.normal(0, 50, te.size)).tolist()},
             "hbonds_protein": {"count": (180 + rng.normal(0, 3, te.size)).tolist(), "time_ns": te.tolist()}, "ligands": {}}
        if key != "apo":
            e["ligands"]["L01"] = {"errors": {}, "hbonds": {"count": (2 + (rng.random(te.size) > 0.5)).tolist(),
                                                           "occupancy": [["ASP189:OD1 ← L01:N1", 0.83], ["SER190:OG → L01:N2", 0.41]]},
                                   "fingerprint": {"residues": ["ASP189", "SER190", "TRP215"],
                                                   "matrix": [[3] * te.size, [2, 0] * (te.size // 2) + [2] * (te.size % 2), [1] * te.size],
                                                   "occupancy": {"ionic": {"ASP189": 0.95}, "polar": {"SER190": 0.5}, "hydrophobic": {"TRP215": 0.9}}},
                                   "water_bridges": {"count": (rng.random(te.size) * 2).round().tolist(), "residues": [["GLY219", 0.4]]},
                                   "sasa": {"buried_fraction": (0.82 + rng.normal(0, 0.02, te.size)).tolist()}}
        atomic_write_json(e, wf.dir / f"x_{key}.json")
    bdir = wf.dir / "binding_BEN"; bdir.mkdir()
    pos = np.linspace(0.4, 1.9, 300)
    force = 600 * np.exp(-((pos - 0.7) / 0.12) ** 2) + rng.normal(0, 30, pos.size)
    work = np.cumsum(force) * (pos[1] - pos[0])
    np.savetxt(bdir / "smd.tsv", np.c_[pos * 100, pos, pos, force, work], delimiter="\t")
    g = np.linspace(0.4, 1.9, 60)
    W = -24.3 * np.exp(-((g - 0.45) / 0.35) ** 2)
    win = {round(c, 3): rng.normal(c, 0.04, 400) for c in np.arange(0.45, 1.9, 0.08)}
    conv = {f"{fr:.2f}": {"grid_nm": g.tolist(), "pmf_kj_mol": ((W - W.min()) * (0.9 + 0.1 * fr)).tolist(), "delta_pmf": 24.3 * (0.9 + 0.1 * fr)}
            for fr in (0.25, 0.5, 0.75, 1.0)}
    atomic_write_json({"result": {"pmf": {"grid_nm": g.tolist(), "pmf_radial_kj_mol": (W - W.min()).tolist(),
                                          "coverage": {"continuous": True, "breaks": [], "n_windows": 24},
                                          "overlap_matrix": histogram_overlap_matrix(win), "convergence": conv}}}, bdir / "binding_manifest.json")
    sums = {"apo": {"rmsd_backbone_mean_A": 1.45, "metrics_file": str(wf.dir / "m_apo.json"), "extended_file": str(wf.dir / "x_apo.json"), "ligands": {}},
            "docked_BEN": {"rmsd_backbone_mean_A": 1.21, "metrics_file": str(wf.dir / "m_docked_BEN.json"), "extended_file": str(wf.dir / "x_docked_BEN.json"),
                           "ligands": {"L01": {"stays_bound": True, "rmsd_last20_A": 1.3, "top_contacts": [["ASP189", 0.92], ["SER190", 0.71]]}}}}
    wf._mark("md_cases", cases={"apo": {"case_id": "c0", "mode": "apo", "ligands": []},
                                "docked_BEN": {"case_id": "c1", "mode": "docked_single", "ligands": ["BEN"]}})
    wf._mark("analysis", summaries=sums, comparison={"most_rigidified_on_binding": [{"residue": "SER195", "delta_rmsf_A": -0.42}]})
    wf._mark("binding", results={"BEN": {"delta_pmf_kj_mol": 24.3, "delta_pmf_err_kj_mol": 1.8, "dG_standard_kj_mol": None,
                                         "dG_withheld": "classroom", "half_split": {"diff_kj_mol": 1.1}, "caveats": ["profile only"],
                                         "r_min_nm": 0.42, "max_force": 650.0, "work": 80.2,
                                         "figures": {"pmf": {"png": str(bdir / "pmf.png")}}}}, comparison={})
    st = wf.state()
    st["cpp"] = {"GRP": {"status": "計算預測", "prediction": "不太可能穿膜", "limitation": "not predicted to penetrate", "explanation": "x"}}
    st["peptide_access"] = {"GRP": {"pose": {"burial_fraction": 0.12, "site_min_distance_A": 7.5, "gate": "AUTO_FIXED",
                                              "advisory": True, "explanation": "surface"}}}
    atomic_write_json(st, wf.state_path)
    return wf


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_report_structure_and_interpretation(tmp_path, lang):
    wf = make_wf(tmp_path, lang)
    html = build_workflow_report(wf).read_text(encoding="utf-8")
    if lang == "en":
        heads = ["Key findings", "1. Study design", "2. Receptor preparation", "3. Molecular docking", "4. Scientific limitations of the peptide",
                 "5. Molecular dynamics", "6. Binding free energy", "7. Methods", "8. Limitations", "Appendix A", "Appendix B", "Appendix C"]
        for sub in ("What this step is", "Scientific meaning", "Parameters used", "Results", "Interpretation"):
            assert html.count(sub) >= 5, sub
        assert "Table 1." in html and "AutoDock Vina" in html and "Amber ff14SB" in html
        assert "Redocking reproduces the co-crystal pose at 0.40 Å" in html      # scenario sentences from the data
        assert "top two poses differ by 0.50 kcal" in html
        assert "24.3 ± 1.8" in html and "has converged" in html
        assert "ASP189 (92%)" in html and "Recommended for this case" in html
        # every figure carries the general reading guide and the project-specific result (D-54)
        assert html.count("How to read") >= 20 and html.count("In this project") >= 20         # D-58: extended figures
        for kind in ("Secondary structure", "Conformational free-energy landscape", "Conformational clusters", "Dynamic cross-correlation",
                     "Ligand burial", "Ligand–protein hydrogen bonds", "Hydrogen-bond occupancy", "Interaction fingerprint", "Water bridges",
                     "Window overlap matrix", "Convergence of the free-energy profile", "Protein solvent-accessible surface area",
                     "Protein internal hydrogen bonds", "Ligand–pocket centre-of-mass distance"):
            assert kind in html, kind
        assert "ASP189:OD1 ← L01:N1 (83%)" in html and "deeply buried" in html and "has converged" in html
        idx = json.loads((wf.dir / "report_figures" / "index_en.json").read_text(encoding="utf-8"))
        assert len(idx["figures"]) >= 20 and all(f["read"] and Path(f["path"]).is_file() for f in idx["figures"])
        for kind in ("Docking pose scores", "Backbone RMSD", "Radius of gyration", "Ligand displacement in the pocket",
                     "Residue flexibility", "Contact frequency", "Steered molecular dynamics", "Free-energy profile"):
            assert kind in html, kind
        assert "single main rupture" in html and "fully detached" in html and "end of the profile is flat" in html
        assert "Residues that become most rigid" in html and "levels off below 2 Å" in html
    else:
        heads = ["重點摘要", "1. 研究設計", "2. 受體結構準備", "3. 分子對接與姿勢選擇", "4. 胜肽配體的科學限制", "5. 分子動力學",
                 "6. 結合自由能", "7. 方法", "8. 限制與注意事項", "附錄 A", "附錄 B", "附錄 C"]
        for sub in ("這一步是什麼", "科學意義", "使用的參數", "結果", "結果解釋"):
            assert sub in html
        assert "表 1." in html and "重新對接與共結晶姿勢的 RMSD 為 0.40 Å" in html and html.count("如何判讀") >= 8
    pos = [html.index(h) for h in heads]
    assert pos == sorted(pos), list(zip(heads, pos))


def test_actual_values_and_methods(tmp_path):
    wf = make_wf(tmp_path)
    v = actual_values(wf)
    assert v["tier"] == "teaching" and v["timestep_fs"] == 4.0 and v["production_ns"] == 10.0 and v["binding"]
    assert v["window_prod_ps"] == 500.0                                  # D-41 tier rule
    m = methods_text(wf, v, "en")
    assert "hydrogen masses were repartitioned" in m and "10 ns" in m and "0.15 M NaCl" in m and "MBAR" in m
    assert "氫質量重分配" in methods_text(wf, v, "zh")


def test_interpret_md_flags_drift_and_unbinding():
    t = np.linspace(0, 10, 200)
    drifting = {"time_ns": t.tolist(), "rmsd_backbone_A": (1 + 0.2 * t).tolist()}
    f = I.md({"x": {"rmsd_backbone_mean_A": 2.0, "ligands": {"L01": {"stays_bound": False, "rmsd_last20_A": 6.0}}}}, {"x": drifting})
    texts = " ".join(x["text"][1] for x in f)
    assert "not reached a plateau" in texts and "left or moved away" in texts
    assert sum(x["level"] == "caution" for x in f) == 2
    assert I.binding({"A": {"delta_pmf_kj_mol": 95.0}})[-1]["level"] == "caution"


def test_report_combines_several_smd_runs(tmp_path):
    """D-87: a target run twice shows each run and the combined value; the context column says alone / with others."""
    wf = make_wf(tmp_path, "en")
    st = wf.state()
    r = st["steps"]["binding"]["results"]["BEN"]
    r.update({"status": "PASS", "replicas": 2, "context": "single", "delta_pmf_kj_mol": 24.0, "delta_pmf_err_kj_mol": 1.0,
              "per_replica": [{"delta_pmf_kj_mol": 23.0, "delta_pmf_err_kj_mol": 1.0, "dG_standard_kj_mol": None},
                              {"delta_pmf_kj_mol": 25.0, "delta_pmf_err_kj_mol": 1.2, "dG_standard_kj_mol": None}]})
    atomic_write_json(st, wf.state_path)
    html = build_workflow_report(wf).read_text(encoding="utf-8")
    assert "Each SMD and umbrella-sampling run" in html and "23.0 ± 1.0" in html and "25.0 ± 1.2" in html
    assert "SMD runs" in html and ">Alone<" in html
