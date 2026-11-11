# -*- coding: utf-8 -*-
"""L1 tool layer: the three tools the MCP adapter exposes (read_capabilities, plan_workflow, read_report).

Boundaries (llm_orchestration.md §1): the LLM proposes, MD20 executes. Nothing here runs a workflow, creates a
project, touches ``workflows/`` or applies anything. ``plan_workflow`` only writes a proposal file (and a
config file for the user to review) under ``<projects_dir>/llm_proposals/``. ``read_report`` only reads inside
``projects_dir`` and returns names/statuses and report text, never absolute paths and never gate messages.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from md20.util.decisions import DecisionLog
from md20.util.hashing import sha256_file
from md20.util.jsonio import load_json, replace_retry
from md20.util.paths import safe_name
from md20.util.timeutil import now_iso
from md20.workflow import find_workflows, workflow_status

from .interface import ACTIONS, L1_EXPOSED, capabilities_view, validate_workflow_draft
from .mcp_server import ServerContext, Tool, ToolError

PROPOSAL_DIR = "llm_proposals"
MAX_RATIONALE = 2000
DEFAULT_PAGE = 8000
MAX_PAGE = 20000


def _description(name: str) -> str:
    for a in ACTIONS:
        if a["name"] == name:
            return f"{a['summary']} Limits: {a['limits']}."
    raise KeyError(name)


def _reject_extra(args: dict, allowed: set[str]) -> None:
    extra = sorted(set(args) - allowed)
    if extra:
        raise ToolError(f"unknown argument(s): {', '.join(extra)}")


# --------------------------------------------------------------------------- read_capabilities
def _read_capabilities(ctx: ServerContext, args: dict) -> dict:
    _reject_extra(args, set())
    return {"capabilities": capabilities_view()}


# --------------------------------------------------------------------------- plan_workflow
def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _write_new_json(path: Path, data: Any, *, stamp: bool = False) -> None:
    """Atomically create ``path`` with JSON content; never overwrite an existing file (ToolError instead)."""
    if stamp and isinstance(data, dict):
        from md20.util.stamp import stamp_record
        data = {**data, "_md20": stamp_record()}
    if path.exists() or path.is_symlink():
        raise ToolError("proposal file already exists; nothing was overwritten (retry in a moment)")
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(tmp, path)               # fails if the destination appeared meanwhile: never overwrites
        except FileExistsError:
            raise ToolError("proposal file already exists; nothing was overwritten (retry in a moment)")
        except OSError:                      # filesystem without hard links: fall back to the checked replace
            if path.exists():
                raise ToolError("proposal file already exists; nothing was overwritten (retry in a moment)")
            replace_retry(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _why_zh(verdict: dict, name: Any, proposal: str | None) -> str:
    if verdict["status"] == "ALLOWED":
        review = "、".join(h["key"] for h in verdict["human_review"])
        extra = f"另有科學敏感設定需使用者特別審查：{review}。" if review else ""
        return (f"LLM 提出工作流程草稿「{name}」，已通過格式與範圍檢查，寫入提議檔 {proposal}。"
                f"這只是提議：MD20 尚未執行任何東西，需使用者審查提議檔後自行執行。{extra}")
    top = "；".join(verdict["errors"][:3]) or "草稿不符規則"
    more = f"（共 {len(verdict['errors'])} 項）" if len(verdict["errors"]) > 3 else ""
    return f"LLM 的工作流程草稿被拒絕，未寫入任何提議檔。主要原因{more}：{top}"


def _plan_workflow(ctx: ServerContext, args: dict) -> dict:
    _reject_extra(args, {"draft", "rationale"})
    if "draft" not in args:
        raise ToolError("draft is required")
    draft = args["draft"]
    rationale = args.get("rationale")
    if not isinstance(draft, dict):
        raise ToolError("draft must be an object")
    if rationale is not None:
        if not isinstance(rationale, str):
            raise ToolError("rationale must be a string")
        if len(rationale) > MAX_RATIONALE:
            raise ToolError(f"rationale is too long (max {MAX_RATIONALE} characters)")

    verdict = validate_workflow_draft(draft)
    try:
        digest = hashlib.sha256(_canonical(draft)).hexdigest()
    except (TypeError, ValueError):
        raise ToolError("draft must be plain JSON")
    root = Path(ctx.projects_dir)
    if not root.is_dir():      # D-184: never create the projects root on the LLM's behalf (block, don't guess)
        raise ToolError("the MD20 projects folder does not exist; nothing was written")
    pdir = root / PROPOSAL_DIR
    log = DecisionLog(pdir / "decisions.jsonl")
    client = dict(ctx.client or {})

    if verdict["status"] != "ALLOWED":
        log.record("llm.plan_workflow", "LLM 工作流程草稿", verdict["status"], _why_zh(verdict, draft.get("name"), None),
                   kind="proposal", actor="llm", client=client, draft_sha256=digest, proposal=None)
        return {"status": verdict["status"], "verdict": verdict, "proposal_id": None, "files": [],
                "next_step": "Nothing was written. Fix the errors in the verdict and call plan_workflow again."}

    created = now_iso().replace("-", "").replace(":", "")
    stem = f"{created}_{draft['name']}_{digest[:8]}"
    proposal_path, config_path = pdir / f"{stem}.json", pdir / f"{stem}.config.json"
    pdir.mkdir(parents=True, exist_ok=True)
    if proposal_path.exists() or config_path.exists():
        raise ToolError("proposal file already exists; nothing was overwritten (retry in a moment)")
    _write_new_json(proposal_path, {
        "schema": "md20.llm_proposal/1", "action": "plan_workflow", "status": "PENDING_USER_CONFIRMATION",
        "applied": False, "draft": draft, "draft_sha256": digest, "verdict": verdict, "rationale": rationale,
        "client": client, "created_at": now_iso()}, stamp=True)
    _write_new_json(config_path, draft)
    log.record("llm.plan_workflow", "LLM 工作流程草稿", verdict["status"], _why_zh(verdict, draft["name"], proposal_path.name),
               kind="proposal", actor="llm", client=client, draft_sha256=digest, proposal=proposal_path.name)
    return {"status": "ALLOWED", "verdict": verdict, "proposal_id": stem,
            "files": [f"{PROPOSAL_DIR}/{proposal_path.name}", f"{PROPOSAL_DIR}/{config_path.name}"],
            "draft_sha256": digest,
            "next_step": "MD20 has not run anything. The user must review the proposal file and run it themselves "
                         "(e.g. md20 pipeline run on the .config.json file)."}


# --------------------------------------------------------------------------- read_report
class _TextExtractor(HTMLParser):
    """Visible text only: drops <script>/<style>, collapses whitespace later."""
    _SKIP = {"script", "style", "noscript", "template"}
    _BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "ul", "ol", "pre"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        elif tag in self._BLOCK:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self._BLOCK:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    p.close()
    return re.sub(r"\s+", " ", "".join(p.parts)).strip()


def _check_name(label: str, value: Any) -> str:
    if (not isinstance(value, str) or not value or value in (".", "..") or "/" in value or "\\" in value
            or safe_name(value) != value):
        raise ToolError(f"invalid {label} name (letters, digits, '_', '.', '-' only)")
    return value


def _inside(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base)
        return True
    except (ValueError, OSError):
        return False


def _read_report(ctx: ServerContext, args: dict) -> dict:
    _reject_extra(args, {"project", "workflow", "offset", "max_chars"})
    project, workflow = args.get("project"), args.get("workflow")
    offset, max_chars = args.get("offset", 0), args.get("max_chars", DEFAULT_PAGE)
    for label, v, lo, hi in (("offset", offset, 0, None), ("max_chars", max_chars, 1, MAX_PAGE)):
        if isinstance(v, bool) or not isinstance(v, int) or v < lo or (hi is not None and v > hi):
            raise ToolError(f"{label} must be an integer" + (f" between {lo} and {hi}" if hi else f" >= {lo}"))
    base = Path(ctx.projects_dir).resolve()

    if project is None and workflow is None:
        rows = []
        for r in find_workflows(base):
            wdir = Path(r["workflow_dir"])
            if _inside(wdir, base):
                rows.append({"project": Path(r["project_dir"]).name, "workflow": r["name"], "status": r["status"]})
        return {"workflows": rows}
    if project is None or workflow is None:
        raise ToolError("give both project and workflow, or neither to list workflows")
    _check_name("project", project)
    _check_name("workflow", workflow)

    wdir = base / project / "workflows" / workflow
    cfg = wdir / "config.json"
    if not _inside(wdir, base) or not cfg.is_file() or not _inside(cfg, base):
        raise ToolError("workflow not found")
    wdir = wdir.resolve()

    state_path = wdir / "state.json"
    state = load_json(state_path, {"steps": {}}) if _inside(state_path, wdir) else {"steps": {}}
    steps = state.get("steps") if isinstance(state, dict) else None
    steps = steps if isinstance(steps, dict) else {}
    out: dict[str, Any] = {
        "project": project, "workflow": workflow, "status": workflow_status({"steps": steps}),
        "steps": [{"step": str(k), "status": (v or {}).get("status") if isinstance(v, dict) else None}
                  for k, v in steps.items()],
    }
    rp = wdir / "workflow_report.html"
    if not rp.is_file():
        out["report"] = None
        out["report_note"] = "No report yet: the workflow has not produced workflow_report.html."
        return out
    if not _inside(rp, wdir):
        raise ToolError("report is not readable")
    text = html_to_text(rp.read_text(encoding="utf-8", errors="replace"))
    end = offset + max_chars
    out["report"] = {
        "report_sha256": sha256_file(rp), "report_bytes": rp.stat().st_size,
        "total_chars": len(text), "offset": offset, "text": text[offset:end],
        "next_offset": end if end < len(text) else None,
    }
    return out


# --------------------------------------------------------------------------- registry
_OBJ = {"type": "object", "additionalProperties": False}

L1_TOOLS: tuple[Tool, ...] = (
    Tool("read_capabilities", _description("read_capabilities"),
         {**_OBJ, "properties": {}}, _read_capabilities),
    Tool("plan_workflow", _description("plan_workflow") +
         " Human-decision keys (gate choices) are rejected; science-sensitive settings are flagged for the user's "
         "review; MD20 writes a proposal file only and runs nothing.",
         {**_OBJ, "properties": {
             "draft": {"type": "object", "description": "Draft workflow config.json (see `md20 pipeline example`)."},
             "rationale": {"type": "string", "maxLength": MAX_RATIONALE,
                           "description": "Why these settings (shown to the user)."}},
          "required": ["draft"]}, _plan_workflow),
    Tool("read_report", _description("read_report") +
         " Call with no arguments to list workflows; give project and workflow to read one.",
         {**_OBJ, "properties": {
             "project": {"type": "string", "description": "Project folder name."},
             "workflow": {"type": "string", "description": "Workflow name inside the project."},
             "offset": {"type": "integer", "minimum": 0, "default": 0},
             "max_chars": {"type": "integer", "minimum": 1, "maximum": MAX_PAGE, "default": DEFAULT_PAGE}}},
         _read_report),
)

assert tuple(t.name for t in L1_TOOLS) == L1_EXPOSED
