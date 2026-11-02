"""D-52: project-grade workflow report — section order, numbered figures and tables, data-driven interpretation, both languages."""
import copy
import json

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
    for key, base in (("apo", 1.2), ("docked_BEN", 1.0)):
        atomic_write_json({"time_ns": t.tolist(), "rmsd_backbone_A": (base + 0.3 * (1 - np.exp(-t * 3))).tolist()}, wf.dir / f"m_{key}.json")
    sums = {"apo": {"rmsd_backbone_mean_A": 1.45, "metrics_file": str(wf.dir / "m_apo.json"), "ligands": {}},
            "docked_BEN": {"rmsd_backbone_mean_A": 1.21, "metrics_file": str(wf.dir / "m_docked_BEN.json"),
                           "ligands": {"L01": {"stays_bound": True, "rmsd_last20_A": 1.3, "top_contacts": [["ASP189", 0.92], ["SER190", 0.71]]}}}}
    wf._mark("md_cases", cases={"apo": {"case_id": "c0", "mode": "apo", "ligands": []},
                                "docked_BEN": {"case_id": "c1", "mode": "docked_single", "ligands": ["BEN"]}})
    wf._mark("analysis", summaries=sums, comparison={"most_rigidified_on_binding": [{"residue": "SER195", "delta_rmsf_A": -0.42}]})
    wf._mark("binding", results={"BEN": {"delta_pmf_kj_mol": 24.3, "delta_pmf_err_kj_mol": 1.8, "dG_standard_kj_mol": None,
                                         "dG_withheld": "classroom", "half_split": {"diff_kj_mol": 1.1}, "caveats": ["profile only"],
                                         "r_min_nm": 0.42, "max_force": 650.0, "work": 80.2, "figures": {}}}, comparison={})
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
        assert "RMSD to the co-crystal pose is 0.40 Å" in html          # interpretation from the data
        assert "top two poses differ by 0.50 kcal" in html
        assert "ΔPMF = 24.3 ± 1.8 kJ mol⁻¹" in html and "has converged" in html
        assert "ASP189 (92%)" in html and "Recommended for this case" in html
    else:
        heads = ["重點摘要", "1. 研究設計", "2. 受體結構準備", "3. 分子對接與姿勢選擇", "4. 胜肽配體的科學限制", "5. 分子動力學",
                 "6. 結合自由能", "7. 方法", "8. 限制與注意事項", "附錄 A", "附錄 B", "附錄 C"]
        for sub in ("這一步是什麼", "科學意義", "使用的參數", "結果", "結果解釋"):
            assert sub in html
        assert "表 1." in html and "與共結晶姿勢的 RMSD 為 0.40 Å" in html
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
