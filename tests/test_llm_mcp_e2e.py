# -*- coding: utf-8 -*-
"""End-to-end L1 (D-184): `python -m md20 --dir X mcp` as a real subprocess, CLI -> server -> L1 tools.

Pure Python (no OpenMM). The SDK interop case runs only when the official `mcp` package happens to be
installed; it is a test-only check and never a product dependency.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from md20.workflow import example_config

ROOT = Path(__file__).resolve().parents[1]


def _env() -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "cp950"      # a Windows-like console encoding must not affect the protocol bytes
    return env


def _run(projects: Path, messages: list[dict]) -> tuple[list[dict], str]:
    data = b"".join(json.dumps(m, ensure_ascii=False).encode("utf-8") + b"\n" for m in messages)
    p = subprocess.run([sys.executable, "-m", "md20", "--dir", str(projects), "mcp"], input=data,
                       capture_output=True, env=_env(), timeout=120, cwd=str(ROOT))
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")
    lines = [l for l in p.stdout.split(b"\n") if l.strip()]
    return [json.loads(l.decode("utf-8")) for l in lines], p.stderr.decode("utf-8", "replace")


def _init(i=1, version="2025-06-18"):
    return {"jsonrpc": "2.0", "id": i, "method": "initialize",
            "params": {"protocolVersion": version, "capabilities": {}, "clientInfo": {"name": "e2e", "version": "0"}}}


def _call(i, name, args):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": args}}


def test_cli_lists_exactly_the_l1_tools_and_stdout_is_pure_protocol(tmp_path):
    out, err = _run(tmp_path, [_init(), {"jsonrpc": "2.0", "method": "notifications/initialized"},
                               {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
    assert [m["id"] for m in out] == [1, 2]                       # every stdout line is a JSON-RPC reply
    assert out[0]["result"]["serverInfo"]["name"] == "md20"
    names = [t["name"] for t in out[1]["result"]["tools"]]
    assert names == ["read_capabilities", "plan_workflow", "read_report"]
    assert "initialize" in err                                     # logs go to stderr


def test_cli_plan_workflow_writes_a_proposal_only_and_never_runs(tmp_path):
    draft = example_config()
    out, _ = _run(tmp_path, [_init(), _call(2, "plan_workflow", {"draft": draft, "rationale": "教學示範"}),
                             _call(3, "read_report", {})])
    res = out[1]["result"]
    assert res["isError"] is False
    body = res["structuredContent"]
    assert body["status"] == "ALLOWED"
    for rel in body["files"]:
        assert (tmp_path / rel).is_file()
    cfg = json.loads((tmp_path / body["files"][1]).read_text(encoding="utf-8"))
    assert cfg == draft                                             # the reviewable config is the draft itself
    assert not (tmp_path / draft["name"]).exists()                  # no project created
    assert list(tmp_path.glob("*/workflows/*")) == []               # nothing ran
    rows = [json.loads(l) for l in (tmp_path / "llm_proposals" / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    row = [r for r in rows if "stage" in r][-1]
    assert row["stage"] == "llm.plan_workflow" and row["kind"] == "proposal"
    assert row["evidence"]["client"]["name"] == "e2e"
    assert out[2]["result"]["structuredContent"] == {"workflows": []}


def test_cli_rejects_a_draft_that_makes_a_gate_decision(tmp_path):
    draft = example_config(); draft["pose_choices"] = {"BEN": 1}; draft["md_confirmed"] = True
    out, _ = _run(tmp_path, [_init(), _call(2, "plan_workflow", {"draft": draft})])
    body = out[1]["result"]["structuredContent"]
    assert body["status"] == "REJECTED" and body["files"] == []
    assert any(e.startswith("pose_choices") for e in body["verdict"]["errors"])
    assert not list((tmp_path / "llm_proposals").glob("*.config.json"))


def test_cli_l2_actions_are_not_exposed(tmp_path):
    out, _ = _run(tmp_path, [_init(), _call(2, "propose_config_change", {"key": "replicas", "value": 3})])
    assert out[1]["error"]["code"] == -32602


def test_official_sdk_client_drives_the_real_cli(tmp_path):
    pytest.importorskip("mcp")
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def go():
        params = StdioServerParameters(command=sys.executable, args=["-m", "md20", "--dir", str(tmp_path), "mcp"],
                                       env=_env(), cwd=str(ROOT))
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = await s.list_tools()
                assert [t.name for t in tools.tools] == ["read_capabilities", "plan_workflow", "read_report"]
                caps = await s.call_tool("read_capabilities", {})
                assert not caps.is_error
                text = caps.content[0].text
                assert "implementation" not in text
                plan = await s.call_tool("plan_workflow", {"draft": example_config()})
                assert not plan.is_error and json.loads(plan.content[0].text)["status"] == "ALLOWED"

    anyio.run(go)
