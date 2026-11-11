# -*- coding: utf-8 -*-
"""L1 tool layer tests (pure Python, tmp_path): validate_workflow_draft, plan_workflow, read_report."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path

import pytest

from md20.llm import ACTIONS, L1_EXPOSED, capabilities_view, validate_workflow_draft
from md20.llm.mcp_server import ServerContext, ToolError
from md20.llm.tools import L1_TOOLS, html_to_text
from md20.util.decisions import DecisionLog
from md20.workflow import example_config

CLIENT = {"name": "test-client", "version": "1"}


def ctx(tmp_path) -> ServerContext:
    return ServerContext(projects_dir=tmp_path, client=CLIENT)


def tool(name):
    return next(t for t in L1_TOOLS if t.name == name)


def good_draft(screen: bool = False) -> dict:
    """example_config with the keys that are human decisions removed (see test_example_config_...)."""
    d = example_config(screen)
    if screen:
        d["screen"].pop("next_mode", None)
    return d


def errs(d) -> str:
    return " | ".join(validate_workflow_draft(d)["errors"])


# ------------------------------------------------------------------ registry / contract
def test_l1_tools_are_exactly_the_three_exposed_actions():
    assert [t.name for t in L1_TOOLS] == ["read_capabilities", "plan_workflow", "read_report"]
    assert tuple(t.name for t in L1_TOOLS) == L1_EXPOSED
    modes = {a["name"]: a["mode"] for a in ACTIONS}
    for t in L1_TOOLS:
        assert t.name in modes and modes[t.name] in ("read", "propose")
        assert t.input_schema["type"] == "object" and t.input_schema["additionalProperties"] is False
        assert isinstance(t.input_schema["properties"], dict) and t.description
    assert tool("plan_workflow").input_schema["required"] == ["draft"]
    props = tool("read_report").input_schema["properties"]
    assert props["max_chars"]["minimum"] == 1 and props["max_chars"]["maximum"] == 20000 and props["offset"]["minimum"] == 0
    json.dumps([t.input_schema for t in L1_TOOLS])
    for hidden in ("read_problem", "select_gate_option", "propose_config_change", "read_file", "write_report_narrative"):
        assert hidden not in L1_EXPOSED


def test_read_capabilities_has_no_implementation(tmp_path):
    out = tool("read_capabilities").handler(ctx(tmp_path), {})
    assert out["capabilities"] == capabilities_view()
    assert "implementation" not in json.dumps(out)
    with pytest.raises(ToolError):
        tool("read_capabilities").handler(ctx(tmp_path), {"x": 1})


# ------------------------------------------------------------------ validate_workflow_draft
def test_example_config_allowed_and_screen_next_mode_still_a_gate_choice():
    # D-184: md.replicas is a planning parameter (PLANNABLE_DECISION_PATHS), so the plain example is ALLOWED;
    # screen.next_mode stays a person's choice at the screen gate, so the screen example is rejected for it alone.
    assert validate_workflow_draft(example_config())["status"] == "ALLOWED"
    v = validate_workflow_draft(example_config(screen=True))
    assert [e.split(":")[0] for e in v["errors"]] == ["screen.next_mode"]
    for screen in (False, True):
        ok = validate_workflow_draft(good_draft(screen))
        assert ok["status"] == "ALLOWED" and ok["errors"] == []


def test_md_replicas_is_range_checked_not_waved_through():
    d = good_draft(); d["md"]["replicas"] = 0
    v = validate_workflow_draft(d)
    assert v["status"] == "REJECTED" and any(e.startswith("replicas:") for e in v["errors"])


def test_plan_workflow_refuses_missing_projects_root(tmp_path):
    from md20.llm.mcp_server import ServerContext, ToolError
    missing = tmp_path / "nope"
    with pytest.raises(ToolError):
        tool("plan_workflow").handler(ServerContext(missing, {}), {"draft": good_draft()})
    assert not missing.exists()


def test_ok_draft_reports_features_and_human_review():
    v = validate_workflow_draft(good_draft())
    assert v["required_features"] == ["binding"]
    keys = {h["key"] for h in v["human_review"]}
    assert {"tier", "docking_mode", "binding", "box_shape"} <= keys
    assert validate_workflow_draft(good_draft(True))["required_features"] == ["hts"]


def test_basic_shape_rules():
    assert validate_workflow_draft("x")["status"] == "REJECTED"
    assert validate_workflow_draft([])["status"] == "REJECTED"
    d = good_draft(); d["name"] = "../evil"; assert "name" in errs(d)
    d = good_draft(); d["name"] = ""; assert "name" in errs(d)
    d = good_draft(); d["name"] = "教學"; assert "name" in errs(d)       # safe_name would rename it
    d = good_draft(); d["name"] = 5; assert "name" in errs(d)
    d = good_draft(); del d["name"]; assert "name" in errs(d)
    d = good_draft(); d["receptor"] = "3PTB"; assert "receptor" in errs(d)
    d = good_draft(); d["md"] = "teaching"; assert "md must be an object" in errs(d)
    d = good_draft(); d["ligands"] = ["BEN"]; assert "ligands" in errs(d)
    d = good_draft(); d["ph"] = float("nan"); assert "plain JSON" in errs(d)


def test_unknown_top_level_key_rejected():
    d = good_draft(); d["run_now"] = True
    assert "unknown top-level key: 'run_now'" in errs(d)
    d = good_draft(); d["_md20"] = {}
    assert "_md20" in errs(d)


@pytest.mark.parametrize("path,value", [
    (("pose_choices",), {"BEN": 1}),
    (("md_confirmed",), True),
    (("human_choices",), {"x": "y"}),
    (("metal_policy",), {"CA": "bonded"}),
    (("structure_override",), {"a": 1}),
    (("docking", "skip_redock"), True),
    (("box", "allow_blind"), True),
    (("md", "long_run_confirmed"), True),
    (("md", "membrane", "oriented"), True),
    (("binding", "manual_windows"), [1, 2]),
    (("screen", "select"), ["A"]),
])
def test_human_decision_keys_rejected(path, value):
    d = good_draft(True)
    node = d
    for k in path[:-1]:
        node = node.setdefault(k, {})
    node[path[-1]] = value
    v = validate_workflow_draft(d)
    assert v["status"] == "REJECTED"
    assert any("human-decision key: only a person can set this at a gate" in e and e.startswith(".".join(path)) for e in v["errors"])


def test_empty_decision_keys_are_fine():
    d = good_draft(); d["pose_choices"] = {}; d["md_confirmed"] = False; d["human_choices"] = None
    assert validate_workflow_draft(d)["status"] == "ALLOWED"


def test_ligand_decision_keys_rejected():
    d = good_draft(); d["ligands"][0]["cpp_override"] = "accept"
    assert "ligands[0].cpp_override" in errs(d)
    d = good_draft(); d["ligands"][0]["fold_accept_low"] = True
    assert "fold_accept_low" in errs(d)


@pytest.mark.parametrize("path,value", [
    (("docking", "exhaustiveness"), 100000), (("docking", "exhaustiveness"), 2.5), (("docking", "n_poses"), 0),
    (("md", "padding_nm"), 99.0), (("md", "production_ns"), "lots"), (("md", "ions", "concentration_molar"), -1),
    (("md", "box_shape"), "sphere"), (("md", "tier"), "ultra"), (("md", "ions", "neutralize"), "yes"),
    (("docking", "mode"), "bogus"),
])
def test_out_of_range_values_rejected(path, value):
    d = good_draft()
    node = d
    for k in path[:-1]:
        node = node.setdefault(k, {})
    node[path[-1]] = value
    v = validate_workflow_draft(d)
    assert v["status"] == "REJECTED" and v["errors"]


def test_malformed_nested_values_are_rejected_not_crashing():
    d = good_draft(); d["md"]["ions"] = "NaCl"
    assert validate_workflow_draft(d)["status"] == "REJECTED"
    d = good_draft(); d["md"]["stage_overrides"] = {"nvt": "x"}
    assert validate_workflow_draft(d)["status"] == "REJECTED"


def test_science_sensitive_values_go_to_human_review_not_error():
    d = good_draft(); d["md"]["tier"] = "research"; d["docking"]["mode"] = "simultaneous"
    v = validate_workflow_draft(d)
    review = {h["key"]: h["value"] for h in v["human_review"]}
    assert review["tier"] == "research" and review["docking_mode"] == "simultaneous"
    assert not any(e.startswith(("tier", "docking_mode")) for e in v["errors"])


def test_advisor_error_rejects_and_warning_passes_through():
    d = good_draft(); d["md"]["stage_overrides"] = {"production": {"timestep_fs": 5.0}}
    v = validate_workflow_draft(d)
    assert v["status"] == "REJECTED" and any(e.startswith("timestep_fs") for e in v["errors"])
    # advisor warnings are surfaced (English message text), not fatal
    d = good_draft(); d["md"]["production_ns"] = 0.5
    v = validate_workflow_draft(d)
    assert v["status"] == "ALLOWED" and any(w.startswith("production_ns: 0.5 ns of production") for w in v["warnings"])
    d = good_draft(); d["md"]["padding_nm"] = 0.5
    v = validate_workflow_draft(d)
    assert v["status"] == "REJECTED" and any(e.startswith("padding_nm: ") and len(e) > 20 for e in v["errors"])


def test_advisor_check_failure_is_not_waved_through(monkeypatch):
    from md20 import advisor
    monkeypatch.setattr(advisor, "check", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    v = validate_workflow_draft(good_draft())
    assert v["status"] == "REJECTED" and "could not evaluate parameters" in v["errors"]


def test_validate_does_not_mutate_input():
    d = good_draft(); before = copy.deepcopy(d)
    validate_workflow_draft(d)
    assert d == before


# ------------------------------------------------------------------ plan_workflow
def canonical_sha(d) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def test_plan_workflow_allowed_writes_two_files_and_logs(tmp_path):
    d = good_draft()
    out = tool("plan_workflow").handler(ctx(tmp_path), {"draft": d, "rationale": "trypsin demo"})
    assert out["status"] == "ALLOWED" and out["verdict"]["status"] == "ALLOWED"
    assert "has not run anything" in out["next_step"]
    sha = canonical_sha(d)
    assert out["draft_sha256"] == sha
    files = out["files"]
    assert len(files) == 2 and all(not os.path.isabs(f) and f.startswith("llm_proposals/") for f in files)
    stem = out["proposal_id"]
    assert re.fullmatch(r"\d{8}T\d{6}Z_trypsin_benzamidine_" + sha[:8], stem)
    prop = json.loads((tmp_path / files[0]).read_text(encoding="utf-8"))
    assert prop["schema"] == "md20.llm_proposal/1" and prop["action"] == "plan_workflow"
    assert prop["status"] == "PENDING_USER_CONFIRMATION" and prop["applied"] is False
    assert prop["draft"] == d and prop["draft_sha256"] == sha and prop["rationale"] == "trypsin demo"
    assert prop["client"] == CLIENT and prop["verdict"]["status"] == "ALLOWED" and prop["created_at"]
    assert files[1].endswith(".config.json")
    assert json.loads((tmp_path / files[1]).read_text(encoding="utf-8")) == d       # draft body only
    rows = DecisionLog(tmp_path / "llm_proposals" / "decisions.jsonl").read()
    assert len(rows) == 1
    r = rows[0]
    assert r["stage"] == "llm.plan_workflow" and r["choice"] == "ALLOWED" and r["kind"] == "proposal"
    assert r["evidence"]["actor"] == "llm" and r["evidence"]["client"] == CLIENT
    assert r["evidence"]["draft_sha256"] == sha and r["evidence"]["proposal"] == Path(files[0]).name
    assert re.search(r"[一-鿿]", r["why"]) and "尚未執行" in r["why"]


def test_plan_workflow_rejected_logs_but_writes_no_proposal(tmp_path):
    d = good_draft(); d["pose_choices"] = {"BEN": 1}
    out = tool("plan_workflow").handler(ctx(tmp_path), {"draft": d})
    assert out["status"] == "REJECTED" and out["files"] == [] and out["proposal_id"] is None
    assert sorted(p.name for p in (tmp_path / "llm_proposals").iterdir()) == ["decisions.jsonl"]
    r = DecisionLog(tmp_path / "llm_proposals" / "decisions.jsonl").read()[0]
    assert r["choice"] == "REJECTED" and r["evidence"]["proposal"] is None
    assert re.search(r"[一-鿿]", r["why"]) and "pose_choices" in r["why"]


def test_plan_workflow_never_overwrites(tmp_path, monkeypatch):
    d = good_draft()
    tool("plan_workflow").handler(ctx(tmp_path), {"draft": d})
    before = {p.name: p.read_bytes() for p in (tmp_path / "llm_proposals").iterdir()}
    # force the same stem as the first call: copy an existing proposal to the stem the second call would use
    stem = next(n for n in before if n.endswith(".config.json")).removesuffix(".config.json")
    created = re.match(r"(\d{8}T\d{6}Z)", stem).group(1)
    iso = f"{created[:4]}-{created[4:6]}-{created[6:8]}T{created[9:11]}:{created[11:13]}:{created[13:15]}Z"
    monkeypatch.setattr("md20.llm.tools.now_iso", lambda: iso)
    with pytest.raises(ToolError, match="already exists"):
        tool("plan_workflow").handler(ctx(tmp_path), {"draft": d})
    after = {p.name: p.read_bytes() for p in (tmp_path / "llm_proposals").iterdir() if p.name != "decisions.jsonl"}
    assert after == {k: v for k, v in before.items() if k != "decisions.jsonl"}


def test_plan_workflow_creates_no_project_or_workflow_dirs(tmp_path):
    tool("plan_workflow").handler(ctx(tmp_path), {"draft": good_draft()})
    assert [p.name for p in tmp_path.iterdir()] == ["llm_proposals"]
    assert not list(tmp_path.glob("**/workflows")) and not list(tmp_path.glob("**/project.json"))


def test_plan_workflow_argument_errors(tmp_path):
    h = tool("plan_workflow").handler
    with pytest.raises(ToolError): h(ctx(tmp_path), {})
    with pytest.raises(ToolError): h(ctx(tmp_path), {"draft": "x"})
    with pytest.raises(ToolError): h(ctx(tmp_path), {"draft": good_draft(), "rationale": "x" * 2001})
    with pytest.raises(ToolError): h(ctx(tmp_path), {"draft": good_draft(), "rationale": 5})
    with pytest.raises(ToolError): h(ctx(tmp_path), {"draft": good_draft(), "run": True})
    assert not (tmp_path / "llm_proposals").exists()


# ------------------------------------------------------------------ read_report
def make_wf(root: Path, project="p1", wf="w1", steps=None, html=None):
    d = root / project / "workflows" / wf
    d.mkdir(parents=True)
    (d / "config.json").write_text("{}", encoding="utf-8")
    (d / "state.json").write_text(json.dumps({"steps": steps if steps is not None else {}}), encoding="utf-8")
    if html is not None:
        (d / "workflow_report.html").write_text(html, encoding="utf-8")
    return d


def test_read_report_lists_workflows_without_paths(tmp_path):
    make_wf(tmp_path, "p1", "w1", {"receptor": {"status": "PASS"}, "report": {"status": "PASS"}})
    make_wf(tmp_path, "p2", "w2", {"dock": {"status": "NEEDS_HUMAN", "message": "secret gate text"}})
    out = tool("read_report").handler(ctx(tmp_path), {})
    assert out["workflows"] == [{"project": "p1", "workflow": "w1", "status": "COMPLETE"},
                                {"project": "p2", "workflow": "w2", "status": "NEEDS_HUMAN"}]
    assert str(tmp_path) not in json.dumps(out)


def test_read_report_needs_both_or_neither(tmp_path):
    make_wf(tmp_path)
    for a in ({"project": "p1"}, {"workflow": "w1"}):
        with pytest.raises(ToolError, match="both"):
            tool("read_report").handler(ctx(tmp_path), a)


@pytest.mark.parametrize("bad", ["..", ".", "../p1", "/etc", "a/b", "a\\b", "", "p 1", "教學", ".hidden"])
def test_read_report_rejects_unsafe_names(tmp_path, bad):
    make_wf(tmp_path)
    with pytest.raises(ToolError, match="invalid"):
        tool("read_report").handler(ctx(tmp_path), {"project": bad, "workflow": "w1"})
    with pytest.raises(ToolError, match="invalid"):
        tool("read_report").handler(ctx(tmp_path), {"project": "p1", "workflow": bad})


def test_read_report_unknown_workflow(tmp_path):
    make_wf(tmp_path)
    with pytest.raises(ToolError, match="workflow not found"):
        tool("read_report").handler(ctx(tmp_path), {"project": "p1", "workflow": "nope"})


def test_read_report_symlink_escape_rejected(tmp_path):
    root = tmp_path / "projects"; root.mkdir()
    outside = tmp_path / "outside"
    make_wf(outside, "evil", "w", {"x": {"status": "PASS"}}, html="<p>TOPSECRET</p>")
    try:
        (root / "linked").symlink_to(outside / "evil", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ToolError, match="workflow not found"):
        tool("read_report").handler(ctx(root), {"project": "linked", "workflow": "w"})
    assert tool("read_report").handler(ctx(root), {})["workflows"] == []


def test_read_report_report_file_symlink_escape_rejected(tmp_path):
    root = tmp_path / "projects"; root.mkdir()
    d = make_wf(root)
    secret = tmp_path / "secret.html"; secret.write_text("<p>TOPSECRET</p>", encoding="utf-8")
    try:
        (d / "workflow_report.html").symlink_to(secret)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ToolError):
        tool("read_report").handler(ctx(root), {"project": "p1", "workflow": "w1"})


def test_read_report_incomplete_has_null_report_and_steps_without_messages(tmp_path):
    make_wf(tmp_path, steps={"receptor": {"status": "PASS", "path": "/abs/x"},
                             "dock": {"status": "NEEDS_HUMAN", "message": "choose a pose", "options": ["a"]}})
    out = tool("read_report").handler(ctx(tmp_path), {"project": "p1", "workflow": "w1"})
    assert out["status"] == "NEEDS_HUMAN" and out["report"] is None and "No report yet" in out["report_note"]
    assert out["steps"] == [{"step": "receptor", "status": "PASS"}, {"step": "dock", "status": "NEEDS_HUMAN"}]
    blob = json.dumps(out)
    assert "choose a pose" not in blob and "/abs/x" not in blob and str(tmp_path) not in blob


def test_read_report_html_text_extraction_and_paging(tmp_path):
    html = ("<html><head><style>body{color:red}</style><script>var secret=1;</script></head>"
            "<body><h1>Title</h1><p>Hello   <b>world</b></p><script>alert('x')</script>"
            "<p>" + "abcdefghij" * 10 + "</p></body></html>")
    d = make_wf(tmp_path, steps={"report": {"status": "PASS"}}, html=html)
    text = html_to_text(html)
    assert text.startswith("Title Hello world abcdefghij") and "secret" not in text and "alert" not in text and "color" not in text
    out = tool("read_report").handler(ctx(tmp_path), {"project": "p1", "workflow": "w1", "max_chars": 20})
    rep = out["report"]
    assert out["status"] == "COMPLETE"
    assert rep["text"] == text[:20] and rep["next_offset"] == 20 and rep["total_chars"] == len(text)
    raw = (d / "workflow_report.html").read_bytes()
    assert rep["report_bytes"] == len(raw) and rep["report_sha256"] == hashlib.sha256(raw).hexdigest()
    seen, off = "", 0
    while off is not None:
        r = tool("read_report").handler(ctx(tmp_path), {"project": "p1", "workflow": "w1", "offset": off, "max_chars": 50})["report"]
        seen += r["text"]; off = r["next_offset"]
    assert seen == text
    last = tool("read_report").handler(ctx(tmp_path), {"project": "p1", "workflow": "w1", "offset": len(text) + 5})["report"]
    assert last["text"] == "" and last["next_offset"] is None
    assert str(tmp_path) not in json.dumps(out)


@pytest.mark.parametrize("a", [{"offset": -1}, {"max_chars": 0}, {"max_chars": 20001}, {"offset": 1.5}, {"max_chars": True}, {"x": 1}])
def test_read_report_bad_paging_args(tmp_path, a):
    make_wf(tmp_path)
    with pytest.raises(ToolError):
        tool("read_report").handler(ctx(tmp_path), {"project": "p1", "workflow": "w1", **a})
