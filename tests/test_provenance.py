"""D-96 (A10): decision provenance per workflow and key findings that never drop a late critical caution
(spec Tests 10 and the A10 acceptance criteria)."""
import copy

from md20.project.store import Project
from md20.report.workflow_report import key_findings
from md20.workflow import Workflow, example_config


def _wf(proj, name):
    cfg = copy.deepcopy(example_config())
    cfg["name"] = name
    return Workflow(proj, cfg)


def test_two_workflows_in_one_project_do_not_mix(tmp_path):
    proj = Project.create(tmp_path, "p")
    a, b = _wf(proj, "alpha"), _wf(proj, "beta")
    a.dec.record("binding.result", "X", 1, "from alpha")
    b.dec.record("binding.result", "Y", 2, "from beta")
    proj.decisions.record("project.case", "ff", "amber", "project level")      # no workflow id
    assert [r["why"] for r in a.dec.read()] == ["from alpha"]
    assert [r["why"] for r in b.dec.read()] == ["from beta"]
    assert [r["why"] for r in a.dec.unattributed()] == ["project level"]
    assert all(r.get("workflow") in ("alpha", "beta", None) for r in proj.decisions.read())


def test_legacy_rows_without_workflow_are_unattributed_not_guessed(tmp_path):
    proj = Project.create(tmp_path, "p")
    proj.decisions.record("binding.result", "BEN", 1, "alpha 的結果（文字提到 alpha 也不歸屬）")
    a = _wf(proj, "alpha")
    assert a.dec.read() == [] and len(a.dec.unattributed()) == 1


def _f(level, t):
    return {"level": level, "text": (t, t, t, t)}


def test_late_critical_caution_survives_repeated_early_warnings():
    pool = [_f("note", f"note {i}") for i in range(5)] + [_f("caution", "repeated early warning")] * 12 \
        + [_f("caution", f"other early caution {i}") for i in range(11)] + [_f("caution", "PMF overlap graph disconnected")]
    key = key_findings(pool)
    texts = [k["text"][1] for k in key]
    assert "PMF overlap graph disconnected" in texts                         # not truncated away
    assert texts.count("repeated early warning") == 1                        # de-duplicated
    assert all(k["level"] == "caution" for k in key)                        # cautions first; notes only fill spare room


def test_key_findings_fill_with_good_then_note():
    key = key_findings([_f("note", "n1"), _f("good", "g1"), _f("caution", "c1")], limit=3)
    assert [k["text"][1] for k in key] == ["c1", "g1", "n1"]
