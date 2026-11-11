# -*- coding: utf-8 -*-
"""Helper for the interop test: runs serve() with stub tools (not a test module)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from md20.llm.mcp_server import ServerContext, Tool, ToolError, serve  # noqa: E402


def _echo(ctx: ServerContext, args: dict) -> dict:
    print("stray print must not reach the protocol stream")
    return {"echo": args.get("text", ""), "client": ctx.client.get("name", "")}


def _fail(ctx: ServerContext, args: dict) -> dict:
    raise ToolError("nothing to do here")


TOOLS = (
    Tool("echo", "Echo text back.", {"type": "object", "properties": {"text": {"type": "string"}},
                                     "required": ["text"], "additionalProperties": False}, _echo),
    Tool("fail", "Always fails with a tool error.", {"type": "object", "properties": {}}, _fail),
)

if __name__ == "__main__":
    sys.exit(serve(Path(sys.argv[1]), tools=TOOLS))
