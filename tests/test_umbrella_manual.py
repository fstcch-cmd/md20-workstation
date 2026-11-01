"""Live coverage view + manual "resample a–b" on a workflow (pure python; synthetic window files)."""
import copy

import numpy as np

from md20.gui.actions import binding_dirs, load_windows, resample_range
from md20.gui.views import coverage_chart, coverage_summary, coverage_targets
from md20.project.store import Project
from md20.sampling.adaptive import coverage_view
from md20.util import load_json
from md20.util.jsonio import atomic_write_json
from md20.workflow import Workflow, example_config
from test_adaptive_windows import COARSE, PROFILES, _old_rule


def _wf_with_binding(tmp_path):
    cfg = copy.deepcopy(example_config())
    wf = Workflow(Project.create(tmp_path, "p"), cfg)
    odir = wf.dir / "binding" / "BEN"
    (odir / "windows").mkdir(parents=True)
    samples = _old_rule(PROFILES["sharp"], COARSE)               # leaves a break on the wall
    for c, x in samples.items():
        np.save(odir / "windows" / f"w_{c:.4f}_cv.npy", x)
    atomic_write_json({f"{c:.4f}": 1000.0 for c in samples}, odir / "windows" / "windows_k.json")
    atomic_write_json({"status": "DONE", "updated_at": "t1", "cv_range_nm": [0.45, 1.6], "rounds": [],
                       **coverage_view(samples, 1000.0)}, odir / "coverage.json")
    wf._mark("binding", results={"BEN": {"status": "PASS"}, "OTHER": {"status": "PASS"}})
    wf._mark("report", path="r.html")
    return wf, samples


def test_coverage_chart_shows_breaks(tmp_path):
    wf, samples = _wf_with_binding(tmp_path)
    t = coverage_targets(wf)
    assert [x["target"] for x in t] == ["BEN"]
    cov = load_json(t[0]["dir"] + "/coverage.json")
    opt = coverage_chart(cov)
    assert opt["series"][0]["markArea"]["data"] and len(opt["series"]) == 1 + len(samples)
    assert "斷點" in opt["title"]["text"] and "斷點" in coverage_summary(cov)
    assert coverage_chart({})["series"] == []


def test_resample_range_writes_target_windows_and_reopens_only_that_target(tmp_path):
    wf, samples = _wf_with_binding(tmp_path)
    assert binding_dirs(wf, "BEN") and len(load_windows(binding_dirs(wf, "BEN")[0])[0]) == len(samples)
    out = resample_range(wf, "BEN", 0.48, 0.70, note="牆上沒有樣本")
    assert out["windows"] and out["k"] > 1000.0 and out["breaks_in_range"]
    cfg = load_json(wf.dir / "config.json")
    mw = cfg["binding"]["manual_windows"]["BEN"]
    assert [w["center"] for w in mw] == [w["center"] for w in out["windows"]]
    st = wf.state()["steps"]
    assert "BEN" not in st["binding"]["results"] and st["binding"]["results"]["OTHER"]["status"] == "PASS"
    assert st["binding"]["status"] == "PENDING" and "report" not in st
    d = [x for x in wf.dec.read() if x.get("stage") == "gui.umbrella"][-1]
    assert d["kind"] == "human" and "牆上沒有樣本" in d["why"]
    again = resample_range(wf, "BEN", 0.48, 0.70)               # same request twice: no duplicate windows
    assert again["windows"] == [] and len(load_json(wf.dir / "config.json")["binding"]["manual_windows"]["BEN"]) == len(mw)


def test_resample_requires_existing_windows(tmp_path):
    import pytest
    wf = Workflow(Project.create(tmp_path, "p"), copy.deepcopy(example_config()))
    with pytest.raises(ValueError):
        resample_range(wf, "BEN", 0.5, 0.7)


def test_finished_binding_is_returned_without_resampling(tmp_path):
    """Resume with the same config → stored result (same ΔPMF); a manual resample (extra_windows) reopens it."""
    from md20.sampling.binding import run_binding, finished_result, BindingConfig
    from md20.util import atomic_write_json
    cfg = BindingConfig(pull_distance_nm=0.45, k_umbrella=2500)
    res = {"status": "PASS", "d_bound_nm": 0.28, "delta_pmf_kj_mol": 3.518, "dG_standard_kj_mol": 0.294, "pmf": {"grid_nm": [0.3]},
           "windows": [], "smd": {}, "caveats": ["x"]}
    atomic_write_json({"status": "PASS", "config": cfg.to_dict(), "result": res}, tmp_path / "binding_manifest.json")
    got = run_binding("no.xml", "no.pdb", None, tmp_path, config=cfg)        # no OpenMM needed on this path
    assert got.status == "PASS" and got.delta_pmf_kj_mol == 3.518 and got.dG_standard_kj_mol == 0.294
    import dataclasses
    cfg2 = dataclasses.replace(cfg, extra_windows=[{"center": 0.5, "k": 2500}])
    assert finished_result(tmp_path, cfg2) is None
    atomic_write_json({"status": "PAUSED", "config": cfg.to_dict(), "result": {"status": "PAUSED"}}, tmp_path / "binding_manifest.json")
    assert finished_result(tmp_path, cfg) is None
