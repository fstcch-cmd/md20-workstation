"""D-108 (F01): evidence coverage rows — planned vs run vs supported, never 'supported' by default."""
from types import SimpleNamespace


def _wf(tmp_path, steps, cfg=None):
    return SimpleNamespace(cfg=cfg or {"ligands": [{"name": "BEN"}, {"name": "PGA"}], "md": {"replicas": 3},
                                        "binding": {"added": ["BEN"]}},
                           state=lambda: {"steps": steps}, dir=tmp_path)


def test_rows_cover_plan_run_and_gaps(tmp_path):
    import json
    from md20.report.evidence import evidence_rows, summary
    ext = tmp_path / "x.json"
    ext.write_text(json.dumps({"tica": {"status": "ok", "msm": {"eligibility": "unresolved"}}}))
    steps = {"pose_selection": {"selection": {"ligands": {"BEN": {"rank": 1}}}},
             "md_cases": {"cases": {"apo": {}, "docked_BEN": {}, "docked_PGA": {}}},
             "md_runs": {"runs": {"apo": {"status": "COMPLETE", "run_ids": ["r1", "r2", "r3"]},
                                  "docked_BEN": {"status": "COMPLETE", "run_ids": ["r1"]}}},
             "analysis": {"summaries": {"apo": {"extended_file": str(ext)},
                                        "docked_BEN": {"restrained_production": {"backbone": 0.05}}},
                          "comparison": {"comparability": {"comparable": False}}},
             "binding": {"results": {"BEN": {"status": "PASS", "dG_standard_kj_mol": None, "dG_withheld": "classroom"}}}}
    rows = evidence_rows(_wf(tmp_path, steps))
    by = {(r["item"], r["subject"]): r for r in rows}
    assert by[("docking", "PGA")]["status"] == "missing" and by[("docking", "BEN")]["status"] == "supported"
    assert by[("md", "docked_PGA")]["status"] == "missing"
    assert by[("md", "apo")]["status"] == "ran"            # D-134: COMPLETE is execution, not a scientific claim
    assert by[("replicas", "apo")]["status"] == "supported" and by[("replicas", "docked_BEN")]["reasons"] == ["fewer_replicas"]
    assert by[("analysis", "docked_BEN")]["reasons"] == ["restrained"]
    assert by[("kinetics", "apo")]["reasons"] == ["msm_unresolved"]
    assert by[("compare", "")]["status"] == "limited"
    assert by[("binding", "BEN")]["status"] == "limited" and by[("binding", "BEN")]["detail"] == "classroom"
    assert by[("binding", "BEN")]["reasons"] == ["assess_legacy", "dg_withheld"]          # no stored assessment: reanalysis needed
    sm = summary(rows)
    assert sm["missing"] == 2 and sm["supported"] >= 3


def test_comparison_without_a_record_is_not_supported(tmp_path):
    from md20.report.evidence import evidence_rows
    steps = {"md_cases": {"cases": {"apo": {}, "holo": {}}}, "md_runs": {"runs": {}}, "analysis": {"summaries": {}}}
    rows = evidence_rows(_wf(tmp_path, steps, {"md": {}}))
    comp = [r for r in rows if r["item"] == "compare"][0]
    assert comp["status"] == "limited" and comp["reasons"] == ["not_recorded"]
