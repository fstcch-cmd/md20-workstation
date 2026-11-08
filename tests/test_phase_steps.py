"""D-153: the workflow page shows the whole pipeline skeleton in four phases, top-to-bottom = first-to-last."""
from md20.gui.views import phase_rows, STEP_PHASES, _case_uses_step


class _WF:
    def __init__(self, cfg, steps):
        self.cfg = cfg
        self._steps = steps

    def state(self):
        return {"steps": self._steps}


def _keys(rows):
    return [r["key"] for r in rows if r["kind"] == "step"]


def test_skeleton_is_always_the_full_ordered_pipeline():
    wf = _WF({"ligands": [{"name": "L"}], "md": {"systems": ["apo", "docked_single"]}}, {})
    rows = phase_rows(wf)
    phases = [r["label"] for r in rows if r["kind"] == "phase"]
    assert phases == ["準備", "對接", "模擬", "分析"]
    assert _keys(rows) == [k for _p, _l, ks in STEP_PHASES for k in ks]   # every step, in order, every time
    # docking comes before md_cases comes before md_runs comes before binding
    ks = _keys(rows)
    assert ks.index("docking") < ks.index("md_cases") < ks.index("md_runs") < ks.index("binding")


def test_md_cases_is_renamed_so_it_is_not_mistaken_for_up_front_preparation():
    rows = phase_rows(_WF({"ligands": [{"name": "L"}]}, {}), lang="zh")
    md = next(r for r in rows if r.get("key") == "md_cases")
    assert md["label"] == "MD 系統建立"
    # and it sits in the simulation phase, after docking — not in preparation
    sim_start = [i for i, r in enumerate(rows) if r["kind"] == "phase" and r["label"] == "模擬"][0]
    assert [i for i, r in enumerate(rows) if r.get("key") == "md_cases"][0] > sim_start


def test_conditional_steps_are_marked_not_used_when_the_case_does_not_use_them():
    # no peptide, no screening, apo + docked single → fold and screening are "not used", docking IS used
    wf = _WF({"ligands": [{"name": "BEN"}], "md": {"systems": ["apo", "docked_single"]}}, {})
    by = {r["key"]: r for r in phase_rows(wf) if r["kind"] == "step"}
    assert by["fold"]["state"] == "not_used" and by["fold"]["status_label"] == "未使用"
    assert by["screen_library"]["state"] == "not_used"
    assert by["docking"]["state"] == "not_started"        # used, just not reached yet
    # a peptide with fold, and screening on → those become used (not_started), not "not used"
    wf2 = _WF({"ligands": [{"name": "P", "sequence": "ACDE", "fold": True}], "screen": {"library": "x"},
               "md": {"systems": ["docked_single"]}}, {})
    by2 = {r["key"]: r for r in phase_rows(wf2) if r["kind"] == "step"}
    assert by2["fold"]["state"] == "not_started" and by2["screen_library"]["state"] == "not_started"


def test_apo_only_run_marks_docking_not_used():
    wf = _WF({"ligands": [], "md": {"systems": ["apo"]}}, {})
    by = {r["key"]: r for r in phase_rows(wf) if r["kind"] == "step"}
    assert by["docking"]["state"] == "not_used" and by["pose_selection"]["state"] == "not_used"
    assert by["md_cases"]["state"] == "not_started"       # MD still runs for apo


def test_finished_steps_show_their_real_status():
    wf = _WF({"ligands": [{"name": "L"}], "md": {"systems": ["docked_single"]}},
             {"receptor_input": {"status": "PASS", "at": "2026-11-08T05:00:00"},
              "md_cases": {"status": "AUTO_FIXED", "at": "2026-11-08T05:10:00"}})
    by = {r["key"]: r for r in phase_rows(wf) if r["kind"] == "step"}
    assert by["receptor_input"]["state"] == "PASS" and by["receptor_input"]["at"] == "2026-11-08 05:00:00"
    assert by["md_cases"]["state"] == "AUTO_FIXED"
