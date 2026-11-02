"""D-67: a running calculation must survive language switches, page changes and second clicks."""
import threading
import time
from types import SimpleNamespace
from pathlib import Path

from md20.util.paths import safe_name
from md20.util.timeutil import to_local


def test_non_ascii_names_do_not_collapse_to_one_folder():
    a, b = safe_name("教學"), safe_name("測試")
    assert a != b and a.isascii() and b.isascii()
    assert safe_name("教學") == a                       # stable
    assert safe_name("Teaching") == "Teaching"          # ASCII unchanged
    assert safe_name("my 專案") != safe_name("my 案例")


def test_to_local_converts_utc_and_tolerates_junk():
    import datetime as dt
    s = to_local("2026-11-02T14:51:30Z", "%Y-%m-%d %H:%M:%S")
    want = dt.datetime(2026, 11, 2, 14, 51, 30, tzinfo=dt.timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    assert s == want
    assert to_local("") == "" and to_local("not a time") == "not a time"


def test_runner_runs_one_calculation_at_a_time(monkeypatch):
    from md20.gui import logic
    gate = threading.Event()

    class WF:
        def __init__(self, d):
            self.dir = Path(d); self.name = Path(d).name
            self.project = SimpleNamespace(dir=Path("/p"))
        def run(self, *a, **k):
            gate.wait(5)
            return {"status": "COMPLETE"}
        def state(self):
            return {"steps": {}}

    r = logic.Runner()
    first = r.start(WF("/p/workflows/a"), None, None)
    again = r.start(WF("/p/workflows/a"), None, None)          # same lesson clicked again (e.g. after a language switch)
    other = r.start(WF("/p/workflows/b"), None, None)          # a different workflow while the first runs
    assert again is first and other is first and len(r.jobs) == 1
    gate.set(); first.thread.join(5)
    assert r.running() is None
    second = r.start(WF("/p/workflows/b"), None, None)         # free again → starts
    assert second is not first
    second.thread.join(5)


def test_teaching_project_name_does_not_depend_on_language():
    src = Path(__file__).resolve().parents[1].joinpath("md20", "gui", "pages_v2.py").read_text(encoding="utf-8")
    assert '_project("Teaching")' in src and '"教學")' not in src
