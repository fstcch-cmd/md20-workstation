"""Decision log: every automatic choice the workstation makes is recorded with a reason.

For teaching, the log *is* the explanation: students can read why a
protonation state, a force field, a restraint or a timestep was chosen.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Iterable

from .timeutil import now_iso


@dataclass
class Decision:
    stage: str              # e.g. "build.receptor", "engine.platform"
    what: str               # short label, e.g. "HIS protonation"
    choice: Any             # the value chosen
    why: str                # plain-language reason (Traditional Chinese for students)
    kind: str = "auto"      # auto | auto_fixed | human
    evidence: dict = field(default_factory=dict)
    at: str = field(default_factory=now_iso)
    # D-96 (A10): which workflow wrote it; None = project-level or written before D-96 (attribution unknown)
    workflow: str | None = None


class DecisionLog:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, decision: Decision) -> Decision:
        with open(self.path, "a", encoding="utf-8") as fh:
            if fh.tell() == 0:
                from .stamp import stamp_record
                fh.write(json.dumps({"_md20": stamp_record()}, ensure_ascii=False) + "\n")
            fh.write(json.dumps(asdict(decision), ensure_ascii=False, default=str) + "\n")
        return decision

    def record(self, stage: str, what: str, choice: Any, why: str, *, kind: str = "auto", **evidence) -> Decision:
        return self.add(Decision(stage=stage, what=what, choice=choice, why=why, kind=kind, evidence=evidence))

    def read(self) -> list[dict]:
        if not self.path.is_file():
            return []
        rows = []
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if "_md20" in row and "stage" not in row:
                        continue
                    rows.append(row)
        return rows

    def by_stage(self, prefix: str) -> list[dict]:
        return [r for r in self.read() if str(r.get("stage", "")).startswith(prefix)]

    def to_markdown(self, rows: Iterable[dict] | None = None) -> str:
        rows = list(rows) if rows is not None else self.read()
        out = ["| 時間 | 階段 | 項目 | 選擇 | 類型 | 理由 |", "|---|---|---|---|---|---|"]
        for r in rows:
            out.append(f"| {r.get('at','')} | {r.get('stage','')} | {r.get('what','')} | "
                       f"`{r.get('choice','')}` | {r.get('kind','')} | {r.get('why','')} |")
        return "\n".join(out)


class ScopedDecisionLog:
    """A DecisionLog view bound to one workflow (D-96, A10).  `record`/`add` stamp `workflow`; `read` returns only
    this workflow's rows; `unattributed` returns rows with no workflow id (project-level steps, or anything written
    before D-96) — they are shown as "attribution unknown", never guessed from their text."""

    def __init__(self, base: DecisionLog, workflow: str):
        self.base, self.workflow = base, workflow
        self.path = base.path

    def add(self, decision: Decision) -> Decision:
        if decision.workflow is None:
            decision.workflow = self.workflow
        return self.base.add(decision)

    def record(self, stage: str, what: str, choice: Any, why: str, *, kind: str = "auto", **evidence) -> Decision:
        return self.add(Decision(stage=stage, what=what, choice=choice, why=why, kind=kind, evidence=evidence))

    def read(self) -> list[dict]:
        return [r for r in self.base.read() if r.get("workflow") == self.workflow]

    def unattributed(self) -> list[dict]:
        return [r for r in self.base.read() if not r.get("workflow")]

    def by_stage(self, prefix: str) -> list[dict]:
        return [r for r in self.read() if str(r.get("stage", "")).startswith(prefix)]

    def to_markdown(self, rows: Iterable[dict] | None = None) -> str:
        return self.base.to_markdown(self.read() if rows is None else rows)
