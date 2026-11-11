# -*- coding: utf-8 -*-
"""L1 MCP protocol layer (D-161 section 5): a stdio MCP server using only the standard library.

Newline-delimited JSON-RPC 2.0 over binary stdin/stdout, explicit UTF-8. This module knows the
protocol, not MD20's tools: the tool set is injected by the caller (``md20/llm/tools.py`` provides
``L1_TOOLS``). It must never import tools.py (circular), and it applies nothing by itself.

Safety rules kept here:
- stdout carries protocol messages only; anything else that prints is sent to stderr.
- a tool failure never leaks a traceback or a source path to the model; tracebacks go to stderr.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterable, Optional

SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")   # newest first
STRUCTURED_MIN_VERSION = "2025-06-18"
MAX_LINE_BYTES = 4 * 1024 * 1024

INSTRUCTIONS = (
    "MD20 molecular dynamics workstation. Tools here are read-only or propose-only: nothing you "
    "suggest is applied automatically, the user must confirm, and MD20's gates stay the final "
    "authority. Prefer reading the current problem and capabilities before proposing anything."
)

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
NOT_INITIALIZED = -32002


class ToolError(Exception):
    """Raised by a handler; the message (English) is shown to the LLM as an error result."""


@dataclass(frozen=True)
class ServerContext:
    projects_dir: Path
    client: dict


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[ServerContext, dict], dict]


def negotiate_version(requested: Any) -> str:
    """Same version if we support it, else our newest (the client decides whether to continue)."""
    return requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]


def _version_at_least(version: str, minimum: str) -> bool:
    return version in SUPPORTED_VERSIONS and version >= minimum    # ISO dates sort lexically


def _log(msg: str) -> None:
    try:
        print(f"[md20-mcp] {msg}", file=sys.stderr, flush=True)
    except Exception:  # noqa: BLE001
        pass


# --- minimal JSON-Schema validation (top level only) --------------------------------------
_TYPES: dict[str, Callable[[Any], bool]] = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


def validate_arguments(schema: dict, args: dict) -> Optional[str]:
    """Return an error message, or None when the arguments fit the schema."""
    props = schema.get("properties") or {}
    for key in schema.get("required") or []:
        if key not in args:
            return f"missing required argument '{key}'"
    if schema.get("additionalProperties") is False:
        for key in args:
            if key not in props:
                return f"unexpected argument '{key}'"
    for key, val in args.items():
        spec = props.get(key)
        if not isinstance(spec, dict):
            continue
        want = spec.get("type")
        if want is not None:
            wants = want if isinstance(want, list) else [want]
            if not any(_TYPES.get(w, lambda _v: True)(val) for w in wants):
                return f"argument '{key}' must be of type {'/'.join(wants)}"
        if "enum" in spec and val not in spec["enum"]:
            return f"argument '{key}' must be one of {spec['enum']}"
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            if "minimum" in spec and val < spec["minimum"]:
                return f"argument '{key}' must be >= {spec['minimum']}"
            if "maximum" in spec and val > spec["maximum"]:
                return f"argument '{key}' must be <= {spec['maximum']}"
    return None


# --- server --------------------------------------------------------------------------------
class _Server:
    def __init__(self, projects_dir: Path, tools: Iterable[Tool]):
        self.projects_dir = Path(projects_dir)
        self.tools = {t.name: t for t in tools}
        self.initialized = False
        self.version = SUPPORTED_VERSIONS[0]
        self.client: dict = {}

    @staticmethod
    def _error(id_: Any, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}

    def handle(self, msg: Any) -> Optional[dict]:
        """Return the response for one decoded message, or None when none is due."""
        if not isinstance(msg, dict):
            return self._error(None, INVALID_REQUEST, "request must be a JSON object")
        has_id = "id" in msg
        id_ = msg.get("id")
        if has_id and (isinstance(id_, bool) or not isinstance(id_, (str, int))):
            return self._error(None, INVALID_REQUEST, "invalid id")
        method = msg.get("method")
        if method is None and has_id and ("result" in msg or "error" in msg):
            return None                                   # a reply to us; we send no requests
        if msg.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return self._error(id_ if has_id else None, INVALID_REQUEST, "not a JSON-RPC 2.0 request")
        params = msg.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return self._error(id_ if has_id else None, INVALID_PARAMS, "params must be an object")
        if not has_id:
            if method == "notifications/initialized":
                _log("client initialized")
            return None                                   # notifications never get a reply

        if method == "ping":
            return {"jsonrpc": "2.0", "id": id_, "result": {}}
        if method == "initialize":
            return self._initialize(id_, params)
        if method not in ("tools/list", "tools/call"):
            return self._error(id_, METHOD_NOT_FOUND, f"method not found: {method}")
        if not self.initialized:
            return self._error(id_, NOT_INITIALIZED, "server not initialized")
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": id_, "result": {"tools": [
                {"name": t.name, "description": t.description, "inputSchema": t.input_schema}
                for t in self.tools.values()]}}
        return self._call(id_, params)

    def _initialize(self, id_: Any, params: dict) -> dict:
        requested = params.get("protocolVersion")
        if not isinstance(requested, str):
            return self._error(id_, INVALID_PARAMS, "protocolVersion (string) is required")
        info = params.get("clientInfo")
        self.client = dict(info) if isinstance(info, dict) else {}
        self.version = negotiate_version(requested)
        self.initialized = True
        _log(f"initialize: client={self.client.get('name', '?')} requested={requested} -> {self.version}")
        from md20 import __version__
        return {"jsonrpc": "2.0", "id": id_, "result": {
            "protocolVersion": self.version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "md20", "version": __version__},
            "instructions": INSTRUCTIONS,
        }}

    def _tool_result(self, payload: Optional[dict], error: Optional[str]) -> dict:
        if error is not None:
            return {"content": [{"type": "text", "text": error}], "isError": True}
        res: dict = {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
                     "isError": False}
        if _version_at_least(self.version, STRUCTURED_MIN_VERSION):
            res["structuredContent"] = payload
        return res

    def _call(self, id_: Any, params: dict) -> dict:
        name = params.get("name")
        if not isinstance(name, str):
            return self._error(id_, INVALID_PARAMS, "tool name (string) is required")
        tool = self.tools.get(name)
        if tool is None:
            return self._error(id_, INVALID_PARAMS, f"unknown tool: {name}")
        args = params.get("arguments")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            _log(f"tools/call {name}: failed (arguments not an object)")
            return {"jsonrpc": "2.0", "id": id_, "result": self._tool_result(None, "arguments must be an object")}
        problem = validate_arguments(tool.input_schema, args)
        if problem:
            _log(f"tools/call {name}: failed (invalid arguments)")
            return {"jsonrpc": "2.0", "id": id_, "result": self._tool_result(None, f"invalid arguments: {problem}")}
        ctx = ServerContext(self.projects_dir, dict(self.client))
        try:
            out = tool.handler(ctx, args)
            if not isinstance(out, dict):
                raise TypeError("tool handler must return a dict")
            json.dumps(out, ensure_ascii=False)           # fail here, not while writing the reply
            _log(f"tools/call {name}: ok")
            return {"jsonrpc": "2.0", "id": id_, "result": self._tool_result(out, None)}
        except ToolError as exc:
            _log(f"tools/call {name}: failed (tool error)")
            return {"jsonrpc": "2.0", "id": id_, "result": self._tool_result(None, str(exc) or "tool error")}
        except Exception:  # noqa: BLE001 - never leak traceback or paths to the model
            _log(f"tools/call {name}: failed (internal error)")
            traceback.print_exc(file=sys.stderr)
            return {"jsonrpc": "2.0", "id": id_, "result": self._tool_result(None, "internal error")}


def _read_line(stdin: BinaryIO) -> tuple[Optional[bytes], bool]:
    """Return (line, too_long). line None means EOF. An oversize line is drained and flagged."""
    raw = stdin.readline(MAX_LINE_BYTES + 1)
    if not raw:
        return None, False
    if len(raw) > MAX_LINE_BYTES and not raw.endswith(b"\n"):
        while True:                                       # discard the rest of this line
            chunk = stdin.readline(1 << 20)
            if not chunk or chunk.endswith(b"\n"):
                break
        return b"", True
    return raw, False


def _write(stdout: BinaryIO, obj: dict) -> None:
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    stdout.write(data)
    stdout.flush()


def serve(projects_dir, *, tools, stdin: Optional[BinaryIO] = None, stdout: Optional[BinaryIO] = None) -> int:
    """Run the server until EOF. Returns 0 on a normal end of input."""
    server = _Server(Path(projects_dir), tools)
    saved_stdout = sys.stdout
    saved_fd1: Optional[int] = None
    if stdin is None:
        stdin = sys.stdin.buffer
    if stdout is None:
        try:
            sys.stdout.flush()
        except Exception:  # noqa: BLE001
            pass
        out_fd = sys.stdout.fileno()
        try:   # keep a private copy of the real stdout, then point fd 1 at stderr (child processes, C code)
            saved_fd1 = os.dup(out_fd)
            stdout = os.fdopen(saved_fd1, "wb", closefd=False)
            os.dup2(sys.stderr.fileno(), out_fd)
        except Exception:  # noqa: BLE001
            saved_fd1 = None
            stdout = sys.stdout.buffer
    sys.stdout = sys.stderr           # stray print() calls must not corrupt the protocol stream
    try:
        while True:
            line, too_long = _read_line(stdin)
            if line is None:
                return 0
            if too_long:
                _write(stdout, server._error(None, INVALID_REQUEST, f"line exceeds {MAX_LINE_BYTES} bytes"))
                continue
            if not line.strip():
                continue
            try:
                msg = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                _write(stdout, server._error(None, PARSE_ERROR, "parse error"))
                continue
            try:
                reply = server.handle(msg)
            except Exception:  # noqa: BLE001
                traceback.print_exc(file=sys.stderr)
                reply = server._error(msg.get("id") if isinstance(msg, dict) else None, INTERNAL_ERROR, "internal error")
            if reply is not None:
                _write(stdout, reply)
    finally:
        sys.stdout = saved_stdout
        if saved_fd1 is not None:
            try:
                os.dup2(saved_fd1, sys.stdout.fileno())
                os.close(saved_fd1)
            except Exception:  # noqa: BLE001
                pass
