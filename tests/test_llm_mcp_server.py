# -*- coding: utf-8 -*-
"""L1 MCP protocol layer: stdlib stdio server (md20/llm/mcp_server.py). Stub tools only."""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from md20 import __version__
from md20.llm import mcp_server as M
from md20.llm.mcp_server import ServerContext, Tool, ToolError, serve

HELPER = Path(__file__).with_name("_mcp_stub_server.py")


def _echo(ctx, args):
    print("STRAY-PRINT")                                  # must never reach protocol stdout
    return {"text": args.get("text"), "n": args.get("n"), "client": ctx.client.get("name")}


def _boom(ctx, args):
    raise RuntimeError("secret /home/x/source.py traceback detail")


def _tool_err(ctx, args):
    raise ToolError("that run does not exist")


SCHEMA = {"type": "object", "properties": {
    "text": {"type": "string"},
    "n": {"type": "integer", "minimum": 1, "maximum": 10},
    "x": {"type": "number", "minimum": 0},
}, "required": ["text"], "additionalProperties": False}

TOOLS = (Tool("echo", "Echo.", SCHEMA, _echo),
         Tool("boom", "Raises.", {"type": "object", "properties": {}}, _boom),
         Tool("deny", "ToolError.", {"type": "object", "properties": {}}, _tool_err))


def run(msgs, *, raw: bytes = b"", tools=TOOLS):
    """Drive serve() with the given messages; return the list of decoded replies."""
    data = b"".join(json.dumps(m, ensure_ascii=False).encode("utf-8") + b"\n" for m in msgs) + raw
    out = io.BytesIO()
    assert serve("/tmp/p", tools=tools, stdin=io.BytesIO(data), stdout=out) == 0
    return [json.loads(line) for line in out.getvalue().decode("utf-8").splitlines()]


def init(version="2025-06-18", id_=1):
    return {"jsonrpc": "2.0", "id": id_, "method": "initialize",
            "params": {"protocolVersion": version, "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}


def call(name, args=None, id_=2):
    p = {"name": name}
    if args is not None:
        p["arguments"] = args
    return {"jsonrpc": "2.0", "id": id_, "method": "tools/call", "params": p}


def test_initialize_shape():
    r = run([init()])[0]["result"]
    assert r["protocolVersion"] == "2025-06-18"
    assert r["capabilities"] == {"tools": {"listChanged": False}}
    assert r["serverInfo"] == {"name": "md20", "version": __version__}
    assert "propose" in r["instructions"].lower() or "read-only" in r["instructions"].lower()


@pytest.mark.parametrize("asked,expect", [
    ("2025-06-18", "2025-06-18"), ("2025-03-26", "2025-03-26"), ("2024-11-05", "2024-11-05"),
    ("2025-11-25", "2025-06-18"), ("2099-01-01", "2025-06-18"), ("1999-01-01", "2025-06-18")])
def test_version_negotiation(asked, expect):
    assert run([init(asked)])[0]["result"]["protocolVersion"] == expect


def test_blocked_before_initialize_but_ping_ok():
    out = run([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, {"jsonrpc": "2.0", "id": 2, "method": "ping"},
               call("echo", {"text": "a"}, id_=3)])
    assert out[0]["error"]["code"] == M.NOT_INITIALIZED
    assert out[1]["result"] == {}
    assert out[2]["error"]["code"] == M.NOT_INITIALIZED


def test_server_discover_is_method_not_found_even_before_initialize():
    out = run([{"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {}}])
    assert out[0]["error"]["code"] == M.METHOD_NOT_FOUND


def test_list_tools():
    out = run([init(), {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
    tools = out[1]["result"]["tools"]
    assert [t["name"] for t in tools] == ["echo", "boom", "deny"]
    assert tools[0]["inputSchema"] == SCHEMA and tools[0]["description"] == "Echo."


def test_call_success_and_stdout_not_polluted(capsys):
    out = run([init(), call("echo", {"text": "hi", "n": 3})])
    res = out[1]["result"]
    assert res["isError"] is False
    assert json.loads(res["content"][0]["text"]) == {"text": "hi", "n": 3, "client": "t"}
    assert res["structuredContent"] == {"text": "hi", "n": 3, "client": "t"}
    assert "STRAY-PRINT" not in json.dumps(out)
    assert "STRAY-PRINT" in capsys.readouterr().err        # went to stderr instead
    assert sys.stdout is not sys.stderr                    # restored afterwards


@pytest.mark.parametrize("ver,has", [("2025-06-18", True), ("2025-03-26", False), ("2024-11-05", False)])
def test_structured_content_only_for_new_versions(ver, has):
    res = run([init(ver), call("echo", {"text": "a"})])[1]["result"]
    assert ("structuredContent" in res) is has


def test_tool_error_is_iserror_with_message():
    res = run([init(), call("deny", {})])[1]["result"]
    assert res["isError"] is True and res["content"][0]["text"] == "that run does not exist"


def test_unexpected_exception_does_not_leak(capsys):
    out = run([init(), call("boom", {})])
    res = out[1]["result"]
    assert res["isError"] is True and res["content"][0]["text"] == "internal error"
    blob = json.dumps(out)
    assert "secret" not in blob and "source.py" not in blob and "Traceback" not in blob
    assert "secret" in capsys.readouterr().err             # traceback is kept on stderr


@pytest.mark.parametrize("args", [
    {}, {"text": 5}, {"text": "a", "n": 0}, {"text": "a", "n": 11}, {"text": "a", "n": 2.5},
    {"text": "a", "n": True}, {"text": "a", "x": -1}, {"text": "a", "extra": 1}])
def test_schema_validation_gives_iserror(args):
    res = run([init(), call("echo", args)])[1]["result"]
    assert res["isError"] is True and res["content"][0]["text"].startswith("invalid arguments")
    assert "STRAY-PRINT" not in json.dumps(res)            # handler never ran


def test_valid_float_for_number_and_missing_arguments_default():
    ok = run([init(), call("echo", {"text": "a", "x": 1.5})])[1]["result"]
    assert ok["isError"] is False
    assert run([init(), call("boom")])[1]["result"]["content"][0]["text"] == "internal error"   # arguments omitted -> {}


def test_unknown_tool_and_method():
    out = run([init(), call("nope", {}), {"jsonrpc": "2.0", "id": 3, "method": "resources/list"}])
    assert out[1]["error"]["code"] == M.INVALID_PARAMS
    assert out[2]["error"]["code"] == M.METHOD_NOT_FOUND


def test_bad_json_and_invalid_requests():
    out = run([], raw=b"{not json\n" + b"\xff\xfe\n" + b"[1,2]\n" + b'{"jsonrpc":"1.0","id":9,"method":"ping"}\n'
               + b'{"jsonrpc":"2.0","id":true,"method":"ping"}\n')
    assert out[0]["error"]["code"] == M.PARSE_ERROR and out[0]["id"] is None
    assert out[1]["error"]["code"] == M.PARSE_ERROR
    assert out[2]["error"]["code"] == M.INVALID_REQUEST
    assert out[3]["error"]["code"] == M.INVALID_REQUEST and out[3]["id"] == 9
    assert out[4]["error"]["code"] == M.INVALID_REQUEST and out[4]["id"] is None


def test_server_survives_after_errors():
    out = run([], raw=b"garbage\n" + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode() + b"\n")
    assert out[-1]["result"] == {}


def test_notifications_get_no_reply():
    out = run([{"jsonrpc": "2.0", "method": "notifications/initialized"},
               {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}},
               {"jsonrpc": "2.0", "method": "unknown/thing"},
               {"jsonrpc": "2.0", "id": 4, "result": {}},       # a reply from the client: ignored
               {"jsonrpc": "2.0", "id": 5, "method": "ping"}])
    assert [m["id"] for m in out] == [5]


def test_utf8_chinese_roundtrip():
    text = "分子動力學：配體 結合 — 日本語 한국어 \U0001F9EC"
    out = run([init(), call("echo", {"text": text})])
    assert out[1]["result"]["structuredContent"]["text"] == text
    assert json.loads(out[1]["result"]["content"][0]["text"])["text"] == text


def test_utf8_on_wire_not_escaped_and_newline_safe():
    out = io.BytesIO()
    msgs = [init(), call("echo", {"text": "行1\n行2"})]
    serve("/tmp/p", tools=TOOLS, stdin=io.BytesIO(b"".join(json.dumps(m, ensure_ascii=False).encode() + b"\n" for m in msgs)),
          stdout=out)
    raw = out.getvalue()
    assert "行1".encode("utf-8") in raw
    assert len(raw.splitlines()) == 2                      # embedded newline stayed escaped


def test_oversize_line_rejected_and_server_continues(monkeypatch):
    monkeypatch.setattr(M, "MAX_LINE_BYTES", 1000)
    big = b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"pad":"' + b"a" * 5000 + b'"}}\n'
    ping = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}).encode() + b"\n"
    out = io.BytesIO()
    assert serve("/tmp/p", tools=TOOLS, stdin=io.BytesIO(big + ping), stdout=out) == 0
    msgs = [json.loads(x) for x in out.getvalue().decode().splitlines()]
    assert msgs[0]["error"]["code"] == M.INVALID_REQUEST and msgs[0]["id"] is None
    assert msgs[1]["result"] == {} and msgs[1]["id"] == 2


def test_empty_input_and_last_line_without_newline():
    assert run([]) == []
    out = io.BytesIO()
    serve("/tmp/p", tools=TOOLS, stdin=io.BytesIO(b'{"jsonrpc":"2.0","id":1,"method":"ping"}'), stdout=out)
    assert json.loads(out.getvalue())["result"] == {}


def test_context_gets_projects_dir():
    seen = {}

    def h(ctx, args):
        seen["dir"] = ctx.projects_dir
        return {}
    run([init(), call("t", {})], tools=(Tool("t", "d", {"type": "object"}, h),))
    assert seen["dir"] == Path("/tmp/p")


# --- interop with the official SDK (test-only; never a product dependency) -----------------
def test_official_sdk_interop(tmp_path):
    pytest.importorskip("mcp")
    anyio = pytest.importorskip("anyio")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def go():
        params = StdioServerParameters(command=sys.executable, args=[str(HELPER), str(tmp_path)])
        with open(tmp_path / "err.log", "w", encoding="utf-8") as err:
            async with stdio_client(params, errlog=err) as (r, w):
                async with ClientSession(r, w) as session:
                    init_res = await session.initialize()
                    tools = await session.list_tools()
                    ok = await session.call_tool("echo", {"text": "你好，MD20"})
                    bad = await session.call_tool("fail", {})
                    inv = await session.call_tool("echo", {})
                    return init_res, tools, ok, bad, inv

    init_res, tools, ok, bad, inv = anyio.run(go)
    assert init_res.server_info.name == "md20" and init_res.protocol_version == "2025-06-18"
    assert {t.name for t in tools.tools} == {"echo", "fail"}
    assert ok.is_error is False and "你好，MD20" in ok.content[0].text
    assert ok.structured_content["echo"] == "你好，MD20"
    assert bad.is_error is True and "nothing to do" in bad.content[0].text
    assert inv.is_error is True
