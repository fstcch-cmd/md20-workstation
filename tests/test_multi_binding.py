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


def _ok(dG):
    """A qualified D-96 assessment (every required diagnostic passed)."""
    return {"eligibility": {"delta_pmf_curve": True, "delta_pmf_path_specific": True, "dG_standard": dG is not None,
                            "affinity_ranking": dG is not None}, "reasons": []}


COND = {"cv": "com_distance_radial", "temperature_k": 300.0, "backbone_restraint_kj_mol_nm2": 100.0, "spectators": [],
        "anchor": "automatic"}


def _r(dpmf, err=None, dG=None, ligand=None, status="PASS", qualified=True):
    r = {"status": status, "delta_pmf_kj_mol": dpmf, "delta_pmf_err_kj_mol": err, "dG_standard_kj_mol": dG,
         "ligand": ligand}
    if qualified:
        r.update(assessment=_ok(dG), condition=dict(COND))
    return r


def test_compare_uses_dpmf_when_any_dG_withheld_and_applies_2sigma():
    res = {"A": _r(30.0, 1.0, dG=-25.0, ligand="A"), "B": _r(29.0, 1.0, dG=None, ligand="B"),
           "C": _r(20.0, 1.0, dG=-15.0, ligand="C")}
    c = compare_binding(res, contexts={"single": ["A", "B", "C"]})["contexts"]["single"]
    assert c["quantity"].startswith("ΔΔPMF") and c["reference"] == "A"
    rows = {r["key"]: r for r in c["rows"]}
    assert "不可區分" in rows["B"]["verdict"]                  # 1.0 < 2·√2
    assert "井深較淺" in rows["C"]["verdict"] and rows["C"]["delta"] == 10.0
    assert c["status"] == "PATH_SPECIFIC" and "最強" not in str(c) and "strongest" not in str(c)


def test_compare_dG_when_all_allowed_and_missing_errors_never_significant():
    res = {"A": _r(30.0, dG=-25.0), "B": _r(20.0, dG=-12.0)}
    c = compare_binding(res, contexts={"single": ["A", "B"]})["contexts"]["single"]
    assert c["quantity"] == "ΔΔG°" and c["rows"][1]["delta"] == 13.0 and "缺誤差" in c["rows"][1]["verdict"]


def test_compare_insufficient_and_co_occupancy():
    res = {"A": _r(30.0, 1.0, ligand="A"), "multi:A": _r(36.0, 1.0, ligand="A"),
           "multi:B": _r(10.0, 1.0, ligand="B", status="NEEDS_HUMAN")}
    out = compare_binding(res, contexts={"single": ["A"], "multi:docked_multi": ["multi:A", "multi:B"]})
    assert out["contexts"]["single"]["status"] == "INSUFFICIENT"
    assert out["contexts"]["multi:docked_multi"]["status"] == "DESCRIPTIVE"     # D-96: never ranked
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
                               delta_pmf_err_kj_mol=0.8, dG_standard_kj_mol=None, dG_standard_kcal_mol=None,
                               assessment=_ok(None), condition=dict(COND))

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
    assert comp["contexts"]["single"]["reference"] == "A" and comp["contexts"]["single"]["status"] == "PATH_SPECIFIC"
    assert comp["contexts"]["multi:docked_multi"]["status"] == "DESCRIPTIVE"      # D-96: co-occupancy pulls not ranked
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


def _rep(dp, dpe, dG=None, dGe=None, hs=0.5):
    return SimpleNamespace(delta_pmf_kj_mol=dp, delta_pmf_err_kj_mol=dpe, dG_standard_kj_mol=dG, dG_err_kj_mol=dGe,
                           pmf={"half_split": {"diff_kj_mol": hs}})


def test_aggregate_replicas_uses_larger_of_scatter_and_bootstrap():
    from md20.sampling.multi import aggregate_binding_replicas
    a = aggregate_binding_replicas([_rep(20.0, 0.5, -20.0, 0.5), _rep(26.0, 0.5, -24.0, 0.5, hs=1.5), _rep(23.0, 0.5, -22.0, 0.5)])
    assert a["delta_pmf"] == 23.0 and a["delta_pmf_err"] == pytest.approx(3.0 / np.sqrt(3), abs=1e-3)   # scatter dominates
    assert a["dG"] == -22.0 and a["half_split"]["diff_kj_mol"] == 1.5 and "沒有起點紀錄" in a["why"] and a["n_independent_md_starts"] == 0
    b = aggregate_binding_replicas([_rep(20.0, 2.0, None), _rep(20.1, 2.0, -20.0)])
    assert b["dG"] is None and b["dG_withheld"] and b["delta_pmf_err"] == pytest.approx(np.hypot(2, 2) / 2, abs=1e-3)


def test_research_tier_needs_completed_replicas(tmp_path, monkeypatch):
    import md20.sampling.binding as B
    from md20.project.store import Project
    from md20.util.jsonio import atomic_write_json
    from md20.workflow import Workflow, example_config
    seen = []

    def fake(system_xml, topology_pdb, start, out_dir, *, config, **kw):
        seen.append((str(start), config.seed, str(out_dir)))
        return SimpleNamespace(status="PASS", caveats=[], smd={}, figures={}, delta_pmf_kj_mol=25.0 + len(seen),
                               delta_pmf_err_kj_mol=0.4, dG_standard_kj_mol=-20.0 - len(seen), dG_err_kj_mol=0.5,
                               dG_standard_kcal_mol=None, pmf={"half_split": {"diff_kj_mol": 0.5}, "r_min_nm": 0.4},
                               assessment=_ok(-20.0), condition=dict(COND))

    monkeypatch.setattr(B, "run_binding", fake)
    out = {}
    for n in (1, 3):
        cfg = copy.deepcopy(example_config())
        cfg["md"]["tier"] = "research"
        cfg["binding"] = {"enabled": True, "replicas": n, "config": {"window_prod_ps": 2000.0}}
        wf = Workflow(Project.create(tmp_path / f"n{n}", "p"), cfg)
        case = wf.project.new_case("p_docked_BEN")
        case.build_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json({"system_xml": "s", "topology_pdb": "t",
                           "assembly": {"ligands": [{"name": "L01", "heavy_atom_indices": [1, 2]}]}}, case.build_dir / "build_manifest.json")
        built = {"docked_BEN": {"case_id": case.case_id, "mode": "docked_single", "ligands": ["BEN"], "ligand_map": {"BEN": "L01"}}}
        runs = {"docked_BEN": {"case_id": case.case_id, "run_ids": ["mdA", "mdB", "mdC"]}}
        seen.clear()
        out[n] = (wf.binding(runs, built, SimpleNamespace(name="CPU", properties={}))["BEN"], list(seen))
    r1, calls1 = out[1]
    assert len(calls1) == 1 and r1["dG_standard_kj_mol"] is None and "實際只有 1 個不同的 MD 起點" in r1["dG_withheld"]
    r3, calls3 = out[3]
    assert [c[1] for c in calls3] == [2026, 3026, 4026]                      # independent seeds
    from pathlib import Path
    assert [Path(c[0]).parts[-4] for c in calls3] == ["mdA", "mdB", "mdC"]   # from different MD replicas
    assert [Path(c[2]).name for c in calls3] == ["rep1", "rep2", "rep3"]
    assert r3["replicas"] == 3 and r3["dG_standard_kj_mol"] == -22.0 and r3["dG_err_kj_mol"] is not None
    assert r3["n_independent_md_starts"] == 3 and [x["md_run_id"] for x in r3["replica_sources"]] == ["mdA", "mdB", "mdC"]


def test_exit_direction_avoids_other_ligands_and_prefers_open_side():
    """D-92: ligand at the origin, another ligand on +x (the default exit), protein wall on −y; the free and open exit
    is found (no ligand inside, fewest protein atoms) and an anchor behind it points the CV that way."""
    from md20.sampling.multi import find_exit_direction, anchor_for_direction, pull_path_blockers
    rng = np.random.default_rng(0)
    lig = rng.normal(0, 0.1, (8, 3))
    others = {"ALC": np.array([[0.9, 0.0, 0.0], [1.0, 0.1, 0.0], [1.1, -0.1, 0.05]])}
    wall = np.array([[x, -1.0 - 0.1 * k, z] for x in np.linspace(-2, 2, 9) for z in np.linspace(-2, 2, 9) for k in range(2)])
    ex = find_exit_direction(lig, others, wall, pull_distance_nm=1.5, default_u=np.array([1.0, 0, 0]))
    assert ex is not None
    u = ex["u"]
    assert pull_path_blockers(lig.mean(0) - u, lig, others, pull_distance_nm=1.5) == []
    assert u[1] > -0.5                                       # not into the wall
    ca = np.array([[x, y, z] for x in np.linspace(-1.5, 1.5, 7) for y in np.linspace(-1.5, 1.5, 7) for z in np.linspace(-1.5, 1.5, 7)])
    ca = ca[np.linalg.norm(ca, axis=1) > 0.6]
    a = anchor_for_direction(np.arange(len(ca)), ca, lig.mean(0), u)
    assert a is not None and a["angle_deg"] <= 25 and len(a["anchor_indices"]) >= 4
    acom = ca[a["anchor_indices"]].mean(0)
    assert pull_path_blockers(acom, lig, others, pull_distance_nm=1.5) == []


def test_exit_direction_none_when_surrounded():
    from md20.sampling.multi import find_exit_direction
    lig = np.zeros((2, 3)) + [[0, 0, 0], [0.05, 0, 0]]
    shell = np.array([[np.cos(t) * np.sin(p), np.sin(t) * np.sin(p), np.cos(p)] for t in np.linspace(0, 2 * np.pi, 40)
                      for p in np.linspace(0.01, np.pi - 0.01, 30)]) * 0.8
    assert find_exit_direction(lig, {"X": shell}, None, pull_distance_nm=1.5, n_dirs=200) is None


def test_skipped_target_is_left_out(tmp_path):
    from md20.project import Project
    from md20.workflow import Workflow
    cfg = {"name": "w", "receptor": {}, "ligands": [], "md": {}, "binding": {"enabled": True, "multi": True,
           "skip_targets": {"multi:URI": True}}}
    wf = Workflow(Project.create(tmp_path, "p"), cfg)
    built = {"docked_multi": {"mode": "docked_multi", "ligands": ["URI", "ALC", "MAL"]}}
    targets, _ = wf._binding_targets({"docked_multi": {}}, built)
    assert [t["key"] for t in targets] == ["multi:ALC", "multi:MAL"]


# ------------------------------------------------------------------------------------------------ D-93
def test_contact_neighbour_beside_the_ligand_does_not_block():
    """Laptop 11/04 (hsieh2024_rela_1vkx): ALC/MAL touching URI at t ≈ 0.01–0.04 nm blocked every direction."""
    from md20.sampling.multi import pull_path_blockers
    lig = np.array([[0.0, 0, 0], [0.2, 0, 0], [-0.2, 0, 0], [0, 0.2, 0], [0, -0.2, 0]])
    beside = {"ALC": np.array([[0.02, 0.5, 0.0], [0.04, 0.55, 0.1]])}       # in contact, level with the ligand
    assert pull_path_blockers(np.array([0, 0, -1.0]), lig, beside, pull_distance_nm=1.5) == []
    ahead = {"MAL": np.array([[0.0, 0.1, 0.8]])}                            # on the way out
    assert pull_path_blockers(np.array([0, 0, -1.0]), lig, ahead, pull_distance_nm=1.5)[0]["ligand"] == "MAL"


def test_alone_builds_a_single_case_and_pulls_from_it(tmp_path):
    from md20.project import Project
    from md20.workflow import Workflow
    cfg = {"name": "w", "receptor": {}, "ligands": [], "md": {"systems": ["apo", "docked_multi"]},
           "binding": {"enabled": False, "multi": True, "added": ["multi:URI"], "alone": {"URI": True}}}
    wf = Workflow(Project.create(tmp_path, "p"), cfg)
    assert wf._alone() == {"URI"}
    built = {"docked_multi": {"mode": "docked_multi", "ligands": ["URI", "ALC"]},
             "docked_URI": {"mode": "docked_single", "ligands": ["URI"]}}
    targets, ctx = wf._binding_targets({"docked_multi": {}, "docked_URI": {}}, built)
    assert [t["key"] for t in targets] == ["URI"] and ctx["single"] == ["URI"]


def test_path_gate_options_are_all_actionable():
    from md20.gui.actions import gate_actions
    g = {"name": "binding path", "status": "NEEDS_HUMAN", "evidence": {"target": "multi:URI", "ligand": "URI"},
         "options": ["略過 multi:URI，先算其他配體（binding.skip_targets）", "只算 URI 單獨結合（binding.alone）",
                     "指定 anchor 殘基，改變拉離方向（binding.anchor_residues）", "binding.enabled: false（只做 MD）"]}
    acts, manual = gate_actions(g, step="binding")
    assert not manual and len(acts) == 4
    by = {a["label"]: a for a in acts}
    assert by["只算 URI 單獨結合（binding.alone）"]["patch"] == [{"path": ["binding", "alone", "URI"], "value": True}]
    assert by["只算 URI 單獨結合（binding.alone）"]["from_step"] == "binding"     # shared-pocket MD is not redone
    assert by["指定 anchor 殘基，改變拉離方向（binding.anchor_residues）"]["needs_text"]
    off = by["binding.enabled: false（只做 MD）"]["patch"]
    assert {"path": ["binding", "added"], "value": []} in off


def test_only_md_stops_added_targets(tmp_path):
    from md20.project import Project
    from md20.workflow import Workflow
    from md20.gui.actions import apply_patch
    cfg = {"name": "w", "receptor": {}, "ligands": [], "md": {},
           "binding": {"enabled": True, "multi": True, "added": ["multi:URI"]}}
    new = apply_patch(cfg, [{"path": ["binding", "enabled"], "value": False}, {"path": ["binding", "added"], "value": []},
                            {"path": ["binding", "alone"], "value": {}}])
    wf = Workflow(Project.create(tmp_path, "p"), new)
    assert wf.binding({}, {}, None) == {}


def test_anchor_residues_to_ca(tmp_path):
    from md20.sampling.binding import anchor_atoms_from_residues
    lines = []
    i = 0
    for ch, rs in (("A", 120), ("A", 121), ("B", 120)):
        for nm, el in (("N", "N"), ("CA", "C"), ("C", "C")):
            i += 1
            lines.append(f"ATOM  {i:5d}  {nm:<3s} ALA {ch}{rs:4d}    {0:8.3f}{0:8.3f}{0:8.3f}  1.00  0.00          {el:>2s}")
    p = tmp_path / "t.pdb"; p.write_text("\n".join(lines) + "\nEND\n")
    idx, missing = anchor_atoms_from_residues(p, "120, 121，B:120, 999")
    assert idx == [1, 4, 7] and missing == ["999"]


def test_three_smd_seeds_from_one_md_endpoint_are_not_independent_starts():
    """Spec Test 7 / A9: one MD end point pulled with three seeds is one starting configuration, not three."""
    from md20.sampling.multi import aggregate_binding_replicas
    reps = [_rep(20.0, 0.5, -20.0, 0.5), _rep(21.0, 0.5, -21.0, 0.5), _rep(22.0, 0.5, -22.0, 0.5)]
    src = [{"md_run_id": "md1", "seed": 2026 + 1000 * i} for i in range(3)]
    a = aggregate_binding_replicas(reps, sources=src)
    assert a["n_independent_md_starts"] == 1 and a["n_pulls_sharing_start"] == 2
    assert "只有 1 個不同的 MD 起點" in a["why"] and "not independent equilibrium starts" in a["why_i18n"][1]
    assert "各自從不同的 MD 起點" not in a["why"]
    b = aggregate_binding_replicas(reps, sources=[{"md_run_id": f"md{i}"} for i in range(3)])
    assert b["n_independent_md_starts"] == 3 and "各自從不同的 MD 起點" in b["why"]


def test_research_tier_counts_md_starts_not_pulls(tmp_path, monkeypatch):
    """binding.replicas = 3 with a single MD replica cycles one end point: ΔG° stays withheld (A9)."""
    import md20.sampling.binding as B
    from md20.project.store import Project
    from md20.util.jsonio import atomic_write_json
    from md20.workflow import Workflow, example_config

    def fake(system_xml, topology_pdb, start, out_dir, *, config, **kw):
        return SimpleNamespace(status="PASS", caveats=[], smd={}, figures={}, delta_pmf_kj_mol=25.0, delta_pmf_err_kj_mol=0.4,
                               dG_standard_kj_mol=-20.0, dG_err_kj_mol=0.5, dG_standard_kcal_mol=None,
                               pmf={"half_split": {"diff_kj_mol": 0.5}}, assessment=_ok(-20.0), condition=dict(COND))
    monkeypatch.setattr(B, "run_binding", fake)
    cfg = copy.deepcopy(example_config())
    cfg["md"]["tier"] = "research"
    cfg["binding"] = {"enabled": True, "replicas": 3, "config": {"window_prod_ps": 2000.0}}
    wf = Workflow(Project.create(tmp_path, "p"), cfg)
    case = wf.project.new_case("p_docked_BEN")
    case.build_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json({"system_xml": "s", "topology_pdb": "t",
                       "assembly": {"ligands": [{"name": "L01", "heavy_atom_indices": [1, 2]}]}}, case.build_dir / "build_manifest.json")
    built = {"docked_BEN": {"case_id": case.case_id, "mode": "docked_single", "ligands": ["BEN"], "ligand_map": {"BEN": "L01"}}}
    r = wf.binding({"docked_BEN": {"case_id": case.case_id, "run_ids": ["mdA"]}}, built, SimpleNamespace(name="CPU", properties={}))["BEN"]
    assert r["replicas"] == 3 and r["n_independent_md_starts"] == 1 and r["dG_standard_kj_mol"] is None
    assert [x["shares_start_with_earlier"] for x in r["replica_sources"]] == [False, True, True]
    assert r["assessment"]["eligibility"]["dG_standard"] is False


def test_completed_but_unqualified_pmfs_are_not_ranked():
    """Spec Test 1 / A1: calculations completed, but QC failed or is unknown → no ranking, no 'strongest'."""
    bad = {"eligibility": {"delta_pmf_curve": True, "delta_pmf_path_specific": False, "dG_standard": False},
           "reasons": ["overlap_graph: fail"]}
    res = {"A": {**_r(40.0, 0.1, ligand="A"), "assessment": bad}, "B": _r(20.0, 0.1, ligand="B"),
           "C": _r(10.0, 0.1, ligand="C", qualified=False)}           # legacy: no assessment at all
    c = compare_binding(res, contexts={"single": ["A", "B", "C"]})["contexts"]["single"]
    assert c["status"] == "INSUFFICIENT" and "rows" not in c
    why = {x["key"]: x["why"] for x in c["not_compared"]}
    assert "overlap_graph: fail" in why["A"] and "awaiting reanalysis" in why["C"]
    # tiny bootstrap errors do not rescue an ineligible result
    assert "strongest" not in str(c) and "最強" not in str(c)


def test_different_conditions_are_not_compared():
    res = {"A": _r(30.0, 0.5, ligand="A"), "B": _r(20.0, 0.5, ligand="B")}
    res["B"]["condition"] = {**COND, "anchor": "user residues"}
    c = compare_binding(res, contexts={"single": ["A", "B"]})["contexts"]["single"]
    assert c["status"] == "INSUFFICIENT" and "conditions" in c["why_i18n"][1]
