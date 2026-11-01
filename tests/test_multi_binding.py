"""WP9: multi-ligand binding — exit-path gate, ΔΔ comparison, workflow targets and report (no OpenMM)."""
import copy
from types import SimpleNamespace

import numpy as np
import pytest

from md20.sampling.multi import pull_path_blockers, compare_binding, delta_pmf_error


def test_path_blocker_detects_ligand_on_exit_path():
    anchor = np.zeros(3)
    lig = np.array([[1.0, 0, 0], [1.1, 0.05, 0]])             # pulled along +x
    on_path = {"B": np.array([[1.6, 0.05, 0.0], [1.7, 0.0, 0.1]])}
    beside = {"B": np.array([[1.0, 1.2, 0.0]])}
    behind = {"B": np.array([[0.4, 0.0, 0.0]])}                # between anchor and ligand: not on the exit path
    assert pull_path_blockers(anchor, lig, on_path, pull_distance_nm=1.5)[0]["ligand"] == "B"
    assert pull_path_blockers(anchor, lig, beside, pull_distance_nm=1.5) == []
    assert pull_path_blockers(anchor, lig, behind, pull_distance_nm=1.5) == []
    assert pull_path_blockers(lig.mean(0), lig, on_path, pull_distance_nm=1.5)[0]["reason"]   # undefined direction


def _r(dpmf, err=None, dG=None, ligand=None, status="PASS"):
    return {"status": status, "delta_pmf_kj_mol": dpmf, "delta_pmf_err_kj_mol": err, "dG_standard_kj_mol": dG,
            "ligand": ligand}


def test_compare_uses_dpmf_when_any_dG_withheld_and_applies_2sigma():
    res = {"A": _r(30.0, 1.0, dG=-25.0, ligand="A"), "B": _r(29.0, 1.0, dG=None, ligand="B"),
           "C": _r(20.0, 1.0, dG=-15.0, ligand="C")}
    c = compare_binding(res, contexts={"single": ["A", "B", "C"]})["contexts"]["single"]
    assert c["quantity"].startswith("ΔΔPMF") and c["reference"] == "A"
    rows = {r["key"]: r for r in c["rows"]}
    assert "不可區分" in rows["B"]["verdict"]                  # 1.0 < 2·√2
    assert "弱於參考" in rows["C"]["verdict"] and rows["C"]["delta"] == 10.0


def test_compare_dG_when_all_allowed_and_missing_errors_never_significant():
    res = {"A": _r(30.0, dG=-25.0), "B": _r(20.0, dG=-12.0)}
    c = compare_binding(res, contexts={"single": ["A", "B"]})["contexts"]["single"]
    assert c["quantity"] == "ΔΔG°" and c["rows"][1]["delta"] == 13.0 and "缺誤差" in c["rows"][1]["verdict"]


def test_compare_insufficient_and_co_occupancy():
    res = {"A": _r(30.0, 1.0, ligand="A"), "multi:A": _r(36.0, 1.0, ligand="A"),
           "multi:B": _r(10.0, 1.0, ligand="B", status="NEEDS_HUMAN")}
    out = compare_binding(res, contexts={"single": ["A"], "multi:docked_multi": ["multi:A", "multi:B"]})
    assert out["contexts"]["single"]["status"] == "INSUFFICIENT"
    assert out["contexts"]["multi:docked_multi"]["status"] == "INSUFFICIENT"
    co = out["co_occupancy"][0]
    assert co["ligand"] == "A" and co["shift_kj_mol"] == 6.0 and co["significant"]


def test_delta_pmf_error():
    err = np.array([0.3, 0.4, 0.5, 0.6, 0.6, 0.6])
    assert delta_pmf_error(np.arange(6.0), err, 1, 3) == pytest.approx(np.hypot(0.4, 0.6), abs=1e-3)
    assert delta_pmf_error(np.arange(6.0), None, 1, 3) is None


# ---------------------------------------------------------------- workflow integration with a fake run_binding
def test_workflow_multi_targets_and_comparison(tmp_path, monkeypatch):
    import md20.sampling.binding as B
    from md20.project.store import Project
    from md20.util.jsonio import atomic_write_json
    from md20.workflow import Workflow, example_config
    cfg = copy.deepcopy(example_config())
    cfg["binding"] = {"enabled": True, "config": {}}
    wf = Workflow(Project.create(tmp_path, "p"), cfg)
    calls = []

    def fake(system_xml, topology_pdb, start, out_dir, *, ligand_indices, ligand_resname, other_ligand_indices=None, **kw):
        calls.append((ligand_resname, other_ligand_indices))
        d = {"L01": 30.0, "L02": 22.0}[ligand_resname] + (2.0 if other_ligand_indices else 0.0)
        return SimpleNamespace(status="PASS", caveats=[], pmf={}, smd={}, figures={}, delta_pmf_kj_mol=d,
                               delta_pmf_err_kj_mol=0.8, dG_standard_kj_mol=None, dG_standard_kcal_mol=None)

    monkeypatch.setattr(B, "run_binding", fake)
    built, runs = {}, {}
    for key, mode, ligs, lmap, recs in [
        ("docked_A", "docked_single", ["A"], {"A": "L01"}, [("L01", [10, 11])]),
        ("docked_B", "docked_single", ["B"], {"B": "L02"}, [("L02", [20, 21])]),   # resname chosen so the fake can key on it
        ("docked_multi", "docked_multi", ["A", "B"], {"A": "L01", "B": "L02"}, [("L01", [10, 11]), ("L02", [20, 21])])]:
        case = wf.project.new_case(f"p_{key}")
        case.build_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json({"system_xml": "s", "topology_pdb": "t", "ligands": [{"name": n} for n, _ in recs],
                           "assembly": {"ligands": [{"name": n, "heavy_atom_indices": ix} for n, ix in recs]}},
                          case.build_dir / "build_manifest.json")
        built[key] = {"case_id": case.case_id, "mode": mode, "ligands": ligs, "ligand_map": lmap}
        runs[key] = {"case_id": case.case_id, "run_ids": ["r1"]}

    out = wf.binding(runs, built, SimpleNamespace(name="CPU", properties={}))
    assert set(out) == {"A", "B", "multi:A", "multi:B"}
    assert ("L01", {"B": [20, 21]}) in calls and ("L02", {"A": [10, 11]}) in calls
    comp = wf.state()["steps"]["binding"]["comparison"]
    assert comp["contexts"]["single"]["reference"] == "A"
    assert comp["contexts"]["multi:docked_multi"]["reference"] == "multi:A"
    assert {c["ligand"] for c in comp["co_occupancy"]} == {"A", "B"}
    from md20.report.workflow_report import _binding_section
    html = _binding_section(wf)
    assert "配體間比較" in html and "共存效應" in html and "共同口袋" in html


def test_bootstrap_sigma_of_derived_quantities():
    from md20.sampling.binding import bootstrap_binding_sigma
    g = np.linspace(0.3, 2.0, 120)
    rng = np.random.default_rng(1)
    # well of depth ≈ 20 kJ/mol at 0.5 nm, flat beyond ~1.2 nm (raw W includes −2kT ln r, removed by radial_pmf)
    kT = 0.0083145 * 300
    base = -20 * np.exp(-((g - 0.5) / 0.15) ** 2) - 2 * kT * np.log(g)
    boot = np.vstack([base + rng.normal(0, 1.0) * np.exp(-((g - 0.5) / 0.15) ** 2) for _ in range(60)])
    s = bootstrap_binding_sigma(g, boot, 300.0)
    assert s["n"] == 60 and 0.5 < s["delta_pmf_sd"] < 1.6          # depth jitter SD = 1 kJ/mol
    assert s["dG_sd"] is not None and s["dG_sd"] > 0
    assert bootstrap_binding_sigma(g, None, 300.0)["delta_pmf_sd"] is None
    assert bootstrap_binding_sigma(g, boot[:5], 300.0)["delta_pmf_sd"] is None   # too few replicates → no σ


def test_compare_dG_uses_errors_when_present():
    res = {"A": {**_r(30.0, 1.0, dG=-25.0), "dG_err_kj_mol": 1.0}, "B": {**_r(20.0, 1.0, dG=-24.0), "dG_err_kj_mol": 1.0}}
    rows = compare_binding(res, contexts={"single": ["A", "B"]})["contexts"]["single"]["rows"]
    assert "不可區分" in rows[1]["verdict"]
