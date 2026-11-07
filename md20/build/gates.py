"""Three-state gates.

Every check in the build pipeline returns a `Gate`:
  PASS         nothing to do
  AUTO_FIXED   the workstation changed something; `diff` says exactly what
  NEEDS_HUMAN  stop; `explanation` is written for a student, `options` are the
               one-click choices the GUI will offer (each is a plain string key)

A `GateReport` aggregates gates; `report.blocking` lists the NEEDS_HUMAN ones.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

PASS, AUTO_FIXED, NEEDS_HUMAN = "PASS", "AUTO_FIXED", "NEEDS_HUMAN"


@dataclass
class Gate:
    name: str
    status: str
    explanation: str = ""
    diff: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    # advisory = scientific-limitation notice (D-48): never blocks, but the GUI shows it as a card with its options
    advisory: bool = False
    # D-96 (A3): an accepted scientific limitation that nothing repaired — e.g. a 3.0 Å structure.  The execution
    # status stays PASS (continuation follows policy); `limitation` records what is limited and why it was accepted.
    # AUTO_FIXED is reserved for a performed repair with a `diff`.
    limitation: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GateReport:
    gates: list[Gate] = field(default_factory=list)

    def add(self, gate: Gate) -> Gate:
        self.gates.append(gate)
        return gate

    @property
    def blocking(self) -> list[Gate]:
        return [g for g in self.gates if g.status == NEEDS_HUMAN]

    @property
    def ok(self) -> bool:
        return not self.blocking

    @property
    def status(self) -> str:
        if self.blocking:
            return NEEDS_HUMAN
        return AUTO_FIXED if any(g.status == AUTO_FIXED for g in self.gates) else PASS

    def to_dict(self) -> dict:
        return {"status": self.status, "gates": [g.to_dict() for g in self.gates]}

    def to_markdown(self) -> str:
        icon = {PASS: "✅", AUTO_FIXED: "🛠", NEEDS_HUMAN: "⛔"}
        out = [f"**整體狀態：{self.status}**", ""]
        for g in self.gates:
            out.append(f"- {icon.get(g.status, '?')} **{g.name}** — {g.status}")
            if g.explanation:
                out.append(f"  - {g.explanation}")
            for d in g.diff[:12]:
                out.append(f"  - diff: {d}")
            if len(g.diff) > 12:
                out.append(f"  - …另有 {len(g.diff) - 12} 項")
            if g.options:
                out.append("  - 選項：" + " / ".join(g.options))
        return "\n".join(out)
