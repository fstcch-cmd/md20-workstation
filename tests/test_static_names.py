"""Static check: no function refers to a module-level name that is never defined (e.g. `np` without `import numpy`).

The heavy CI only reaches many OpenMM code paths after 10+ minutes; a missing import there (fc4da13: `np` in
build/assemble.py) used to surface only in that job.  This runs in seconds on the pure-python matrix (D-24)."""
import builtins
import symtable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "md20"
FILES = sorted(p for p in ROOT.rglob("*.py") if "__pycache__" not in p.parts)


def _undefined(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    top = symtable.symtable(src, str(path), "exec")
    defined = {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported()}
    defined |= set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__spec__", "__package__", "__path__"}
    if any(s.get_name() == "*" for s in top.get_symbols()):
        return []          # star imports: cannot tell
    bad = []

    def walk(t):
        for ch in t.get_children():
            if ch.get_type() in ("function", "class"):
                for s in ch.get_symbols():
                    if s.is_global() and not s.is_assigned() and s.get_name() not in defined \
                            and not (s.is_declared_global() and s.is_assigned()):
                        bad.append(f"{path.relative_to(ROOT.parent)}:{ch.get_name()}() → {s.get_name()}")
            walk(ch)
    walk(top)
    return bad


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(ROOT.parent)))
def test_no_undefined_module_names(path):
    assert _undefined(path) == []
