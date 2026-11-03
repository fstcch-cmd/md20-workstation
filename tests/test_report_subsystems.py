"""D-82: report figures, scenario sentences and sections for structure prediction, membranes, long runs and
coarse-grained Martini (docs/specs/report_language.md F43–F57).  Pure Python + numpy + matplotlib."""
import importlib.util
import re
import sys
from pathlib import Path

import numpy as np
import pytest

from md20.report import figure_text as FT
from md20.report import figures as FG
from md20.report import interpret as I

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
NEW = ["fold_plddt", "fold_superposition", "fold_contacts", "membrane_equil", "membrane_density", "membrane_scd", "insertion_depth",
       "headgroup_residence", "peptide_tilt", "thickness_map", "longrun_plan", "convergence_rmsf", "convergence_rmsd",
       "cluster_timeline", "cg_membrane"]
KANA, HANGUL = re.compile(r"[぀-ヿ一-鿿]"), re.compile(r"[가-힯]")


def _levels(f):
    return [x["level"] for x in f]


def _four(findings):
    for x in findings:
        zh, en, ja, ko = x["text"]
        assert re.search(r"[一-鿿]", zh) and KANA.search(ja) and HANGUL.search(ko) and en and en != ja, x


def test_every_new_kind_has_four_language_texts():
    for k in NEW:
        f = FT.FIG[k]
        for part in ("title", "caption", "read"):
            zh, en, ja, ko = f[part]
            assert zh and en and KANA.search(ja) and HANGUL.search(ko), (k, part)


# ------------------------------------------------------------------------------------------------ classifiers
def test_fold_plddt_scenarios():
    good = FT.classify_fold_plddt("P", {"per_residue_plddt": [40] + [85] * 20 + [45], "engine": "omegafold"})
    assert _levels(good)[:2] == ["good", "note"] and "≥ 70" in good[0]["text"][1] and "1, 22" in good[1]["text"][1]
    assert _levels(FT.classify_fold_plddt("P", {"mean_plddt": 60.0}))[0] == "note"
    assert _levels(FT.classify_fold_plddt("P", {"mean_plddt": 41.0}))[0] == "caution"
    cx = FT.classify_fold_plddt("P", {"mean_plddt": 80, "iptm": 0.3, "plddt_by_chain": {"A": [55] * 30, "B": [80] * 10}, "peptide_chain": "B"})
    assert _levels(cx).count("caution") == 2 and any("ipTM 0.30 (< 0.5)" in x["text"][1] for x in cx)
    _four(good + cx)


def test_fold_superposition_and_contacts():
    dev = np.r_[np.full(40, 0.8), np.full(5, 3.6)]
    pocket = np.r_[np.zeros(40, bool), np.ones(5, bool)]
    f = FT.classify_fold_superposition("P", dev, [f"R{i}" for i in range(45)], rmsd=1.4, pocket_mask=pocket)
    assert _levels(f) == ["good", "caution", "caution"] and "(≤ 2 Å)" in f[0]["text"][1]
    assert _levels(FT.classify_fold_superposition("P", dev, [], rmsd=2.6))[0] == "caution"
    M = np.full((10, 6), 7.0); M[:6, :3] = 3.5; M[0, 0] = 1.2
    c = FT.classify_fold_contacts("P", [f"p{i}" for i in range(10)], [f"r{j}" for j in range(6)], M)
    assert _levels(c) == ["good", "note", "caution"] and "6 of 10" in c[0]["text"][1]
    M2 = np.full((10, 6), 7.0); M2[0, 0] = 3.0
    assert _levels(FT.classify_fold_contacts("P", list(range(10)), list(range(6)), M2))[0] == "caution"
    _four(f + c)


def test_membrane_classifiers():
    t = np.linspace(0, 20, 80)
    ref = {"apl_nm2": 0.643, "dpp_nm": 3.70}
    ok = FT.classify_membrane_equil("m", t, 0.64 + 0 * t, 3.72 + 0 * t, ref)
    assert _levels(ok) == ["good", "good"]
    bad = FT.classify_membrane_equil("m", t, np.linspace(0.75, 0.70, 80), 4.2 + 0 * t, ref)
    assert _levels(bad) == ["caution", "caution", "caution"] and "±2 %" in bad[2]["text"][1]
    assert _levels(FT.classify_membrane_equil("m", t, 0.6 + 0 * t, 3.7 + 0 * t, {}))[0] == "note"
    z = np.linspace(-4, 4, 81)
    dens = {"z_nm": z, "groups": {"phosphate": np.exp(-((np.abs(z) - 1.9) / 0.2) ** 2), "water": 1 / (1 + np.exp(-(np.abs(z) - 2.4) * 6)) + 0.05,
                                  "peptide": np.exp(-((z - 1.0) / 0.3) ** 2)}}
    d = FT.classify_density("m", dens)
    assert _levels(d) == ["note", "caution", "note"] and "inserted" in d[2]["text"][1]
    scd = {f"sn1:C3{c}": -0.2 for c in range(2, 16)} | {f"sn2:C2{c}": -0.35 for c in range(2, 16)}
    assert _levels(FT.classify_scd("m", scd)) == ["good", "caution"]
    ins = FT.classify_insertion("m", t, np.r_[np.full(40, -1.0), np.full(40, 0.1)], None, crossed=True)
    assert _levels(ins) == ["good", "note", "caution"]
    assert "stays in the water" in FT.classify_insertion("m", t, np.full(80, -0.8))[0]["text"][1]
    assert "hydrophobic core" in FT.classify_insertion("m", t, np.full(80, 1.3))[0]["text"][1]
    rows = [{"residue": "LYS7", "fraction": 0.9, "events": 2, "mean_ps": 3000, "max_ps": 5000, "open_at_end": True},
            {"residue": "GLY2", "fraction": 0.1, "events": 5, "mean_ps": 100, "max_ps": 200, "open_at_end": False}]
    hg = FT.classify_headgroup("m", rows)
    assert hg[0]["level"] == "good" and "LYS7" in hg[0]["text"][1] and "lower bound" in hg[-1]["text"][1]
    assert _levels(FT.classify_tilt("m", np.r_[np.full(20, 80), np.random.default_rng(0).uniform(0, 90, 40)]))[-1] == "caution"
    assert "flat" in FT.classify_tilt("m", np.full(40, 85.0))[0]["text"][1]
    G = np.full((6, 6), 3.8); G[2, 2] = 2.6
    assert _levels(FT.classify_thickness_map("m", {"dpp_nm": G.tolist()})) == ["caution"]
    assert _levels(FT.classify_thickness_map("m", {"dpp_nm": (G * 0 + 3.8).tolist()})) == ["good"]
    _four(ok + bad + d + ins + hg)


def test_long_run_and_convergence_classifiers():
    plan = {"production_ns": 1000, "total_gb": 20, "replicas": 1, "days": 3.0, "solute_only": True, "trajectory_interval_ps": 50}
    f = FT.classify_longrun("s", plan, {"production_ns": 400, "disk_gb": 30, "days": 6})
    assert _levels(f) == ["caution", "note", "note", "note"] and "(< 99 %)" in f[0]["text"][1]
    assert _levels(FT.classify_longrun("s", plan, {"production_ns": 1000, "disk_gb": 19}))[:2] == ["good", "good"]
    rng = np.random.default_rng(1)
    a = 0.5 + np.abs(np.sin(np.arange(100) / 7))
    assert _levels(FT.classify_rmsf_halves("s", a, a + rng.normal(0, 0.05, 100))) == ["good"]
    assert _levels(FT.classify_rmsf_halves("s", a, rng.permutation(a) + 0.5)) == ["caution", "note"]
    y = np.r_[rng.normal(1.2, 0.1, 200), rng.normal(1.2, 0.1, 200)]
    assert _levels(FT.classify_rmsd_halves("s", y)) == ["good"]
    assert _levels(FT.classify_rmsd_halves("s", np.r_[rng.normal(1.2, 0.1, 200), rng.normal(2.4, 0.1, 200)])) == ["caution"]
    lab = np.r_[np.zeros(200, int), np.ones(50, int), np.zeros(50, int), np.ones(100, int) * 2]
    cl = FT.classify_cluster_timeline("s", lab)
    assert "caution" in _levels(cl) and "cluster 3" in [x for x in cl if x["level"] == "caution"][0]["text"][1]
    P, ids = FT.cluster_windows(lab)
    assert P.shape == (10, 3) and np.allclose(P.sum(1), 1)
    _four(f + cl)


def test_cg_classifier_always_says_coarse_grained():
    s = {"time_ns": list(range(10)), "apl_nm2": [0.64] * 10, "dpp_nm": [3.8] * 10, "reference": {"apl_nm2": 0.643, "dpp_nm": 3.7},
         "p2": {"PO4-GL1": 0.75, "C1A-C2A": 0.7}}
    f = FT.classify_cg_membrane("cg", s)
    assert f[0]["level"] == "note" and "coarse-grained" in f[0]["text"][1] and f[-1]["level"] == "caution"
    _four(f)


# ------------------------------------------------------------------------------------------------ figures
def test_new_figure_functions_draw(tmp_path):
    rng = np.random.default_rng(2)
    t = np.linspace(0, 10, 50)
    out = [FG.plddt_profile({"A": list(rng.uniform(40, 95, 60)), "B": list(rng.uniform(40, 95, 12))}, tmp_path / "a.png", "B"),
           FG.residue_deviation([f"R{i}" for i in range(30)], rng.uniform(0, 4, 30), tmp_path / "b.png", pocket_mask=rng.random(30) > 0.7),
           FG.contact_matrix(["p1", "p2"], ["r1", "r2", "r3"], [[3, 5, 7], [2, 9, 4]], tmp_path / "c.png"),
           FG.membrane_equil(t, 0.64 + 0 * t, 3.7 + 0 * t, {"apl_nm2": 0.643, "dpp_nm": 3.7}, tmp_path / "d.png"),
           FG.density_profile({"z_nm": list(np.linspace(-3, 3, 31)), "groups": {"phosphate": list(rng.random(31))}}, tmp_path / "e.png"),
           FG.scd_plot({"sn1": ([2, 3, 4], [0.2, 0.21, 0.2])}, tmp_path / "f.png"),
           FG.insertion_plot(t, rng.normal(0, 0.1, 50), rng.normal(0.4, 0.1, 50), tmp_path / "g.png"),
           FG.tilt_hist(rng.uniform(0, 90, 50), tmp_path / "h.png"),
           FG.thickness_map_plot({"x_nm": [0, 1, 2], "y_nm": [0, 1, 2], "dpp_nm": [[3.7, None], [3.6, 3.8]]}, tmp_path / "i.png", (1, 1)),
           FG.longrun_plot({"production_ns": 1000, "trajectory_gb": 10, "states_gb": 1, "total_gb": 12}, {"production_ns": 900, "disk_gb": 11},
                           tmp_path / "j.png"),
           FG.rmsf_halves([f"R{i}" for i in range(20)], rng.random(20), rng.random(20), tmp_path / "k.png"),
           FG.rmsd_halves(rng.normal(1, 0.1, 100), tmp_path / "l.png"),
           FG.cluster_timeline_plot(*FT.cluster_windows(rng.integers(0, 3, 100)), np.linspace(0, 10, 11), tmp_path / "m.png"),
           FG.cg_membrane_plot({"time_ns": list(t), "apl_nm2": list(0.64 + 0 * t), "dpp_nm": list(3.9 + 0 * t), "p2": {"PO4-GL1": 0.3}},
                               tmp_path / "n.png")]
    assert all(p and Path(p).stat().st_size > 1000 for p in out)
    assert FG.plddt_profile({}, tmp_path / "x.png") is None and FG.rmsd_halves([1, 2], tmp_path / "y.png") is None


# ------------------------------------------------------------------------------------------------ data builders
def test_membrane_report_data_on_a_synthetic_bilayer():
    from md20.analysis.membrane_report import membrane_report_data, thickness_map
    rng = np.random.default_rng(3)
    nF, nL = 12, 36
    box = np.tile([4.8, 4.8, 9.0], (nF, 1))
    g = (np.arange(6) + 0.5) / 6
    xy = np.c_[np.meshgrid(g, g)[0].ravel(), np.meshgrid(g, g)[1].ravel()] * 4.8
    heads = np.concatenate([np.c_[xy, np.full(nL, 6.4)], np.c_[xy, np.full(nL, 2.6)]])[None].repeat(nF, 0) + rng.normal(0, 0.01, (nF, 2 * nL, 3))
    d = membrane_report_data(time_ns=np.arange(nF), box=box, head_xyz=heads, composition={"POPC": 1.0}, mtype="bilayer",
                             density_z={"phosphate": heads[..., 2]}, map_bins=3)
    assert abs(np.mean(d["apl_nm2"]) - 4.8 * 4.8 / nL) < 1e-6 and abs(np.mean(d["dpp_nm"]) - 3.8) < 0.02
    assert d["reference"]["apl_nm2"] == pytest.approx(0.643) and len(d["thickness_map"]["dpp_nm"]) == 3
    assert abs(np.nanmean(np.array(thickness_map(heads, box, bins=3)["dpp_nm"], float)) - 3.8) < 0.02


def test_adapt_membrane_run_output():
    from md20.report.subsystem_report import adapt_membrane_metrics
    mm = {"type": "surface", "n_lipids": 128, "dpp_nm": [3.7] * 4, "apl_nm2": [0.64] * 4, "core_water": [0, 1, 0, 0],
          "insertion": {"PEP": {"com_depth_nm": [-0.2] * 4, "crossed_centre": False}},
          "acceptance": {"status": "PASS", "evidence": {"reference": {"apl_nm2": 0.643, "dpp_nm": 3.7}, "checks": {"apl": True}}}}
    d = adapt_membrane_metrics(mm, [0, 1, 2, 3])
    assert d["reference"]["dpp_nm"] == 3.7 and d["insertion_by"]["PEP"]["com_depth_nm"] and d["time_ns"] == [0, 1, 2, 3]
    assert adapt_membrane_metrics(mm, None)["time_is_frames"] and adapt_membrane_metrics({"status": "SKIPPED"}) == {}
    lv = _levels(I.membrane("s", d))
    assert lv[0] == "good" and len(lv) == 2                  # acceptance replaces the core-water line; surface note


def test_stream_halves_match_direct_rmsf():
    from md20.analysis.stream import StreamingMetrics
    rng = np.random.default_rng(4)
    xyz = rng.normal(0, 0.05, (40, 6, 3)) + np.arange(18).reshape(6, 3)
    xyz[20:] += rng.normal(0, 0.1, (20, 6, 3))
    sm = StreamingMetrics(rmsf_atoms=np.arange(6))
    sm.update(xyz[:20]); sm.update(xyz[20:])
    r = sm.result()
    full = StreamingMetrics(rmsf_atoms=np.arange(6))
    full.ref = sm.ref
    full.update(xyz[20:])
    assert np.allclose(r["rmsf_second_half_A"], full.result()["rmsf_A"]) and len(r["rmsf_first_half_A"]) == 6
    one = StreamingMetrics(rmsf_atoms=np.arange(6)); one.update(xyz)
    assert "rmsf_first_half_A" not in one.result()


def test_score_text_never_prints_none():
    assert [I.score_text(None, l) for l in ("zh", "en", "ja", "ko")] == list(I.NO_SCORE)
    assert I.score_text(-6.114, "en") == "-6.11" and I.score_text(-6.1, "en", unit=True).endswith("kcal mol⁻¹")


# ------------------------------------------------------------------------------------------------ sections
def _template():
    spec = importlib.util.spec_from_file_location("report_template", ROOT / "tools" / "report_template.py")
    rt = importlib.util.module_from_spec(spec); spec.loader.exec_module(rt)
    return rt


def test_sections_absent_without_data(tmp_path):
    from test_report_v2 import make_wf
    from md20.report.workflow_report import build_workflow_report
    wf = make_wf(tmp_path, "en")
    html = build_workflow_report(wf, tmp_path / "r.html", lang="en").read_text(encoding="utf-8")
    for h in ("Peptide structure prediction", "Membrane system", "Long simulation and convergence", "Coarse-grained simulation"):
        assert h not in html


@pytest.mark.parametrize("lang", ["zh", "en", "ja", "ko"])
def test_sections_render_in_four_languages(tmp_path, lang):
    from md20.report.workflow_report import build_workflow_report, SECTION
    from md20.util import load_json
    from md20.i18n import pick
    rt = _template()
    wf = rt.build(tmp_path / "w", lang)
    html = build_workflow_report(wf, tmp_path / f"r_{lang}.html", lang=lang).read_text(encoding="utf-8")
    for key in ("fold", "membrane", "longrun", "cg"):
        assert pick(SECTION[key]["title"], lang) in html, key
    assert pick(I.NO_SCORE, lang) in html and "None kcal" not in html and ">None<" not in html
    idx = load_json(wf.dir / "report_figures" / f"index_{lang}.json", {})
    kinds = {f["kind"] for f in idx["figures"]}
    assert set(NEW) <= kinds
    if lang in ("ja", "ko"):
        meth = html.split("class=methods>")[1].split("</div>")[0]
        assert ("である" in meth or "した。" in meth) if lang == "ja" else ("했다" in meth)
        assert "Martini 3" in meth and "Kabsch" in meth


def test_long_run_plan_is_stored_for_the_report(tmp_path):
    from test_longrun import _wf_case
    from md20.engine.protocol import make_protocol
    wf, case = _wf_case(tmp_path, {"production_ns": 500, "ns_per_day": 330})
    wf._plan_long_run("docked_single", case, make_protocol("teaching", production_ns=500), {})
    p = wf.state()["long_run"]["docked_single"]
    assert p["production_ns"] == 500 and p["n_chunks"] > 0 and "decisions" not in p
