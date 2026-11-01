"""WP11: owner lock, stale takeover, workflow discovery."""
import json
import os

import pytest

from md20.util.locks import OwnerLock
from md20.workflow import find_workflows, workflow_status


def test_owner_lock_live_and_stale(tmp_path):
    p = tmp_path / "running.json"
    with OwnerLock(p):
        assert json.loads(p.read_text())["pid"] == os.getpid()
    assert not p.exists()
    import socket
    p.write_text(json.dumps({"pid": 999999999, "host": socket.gethostname(), "started": "x"}))
    lk = OwnerLock(p).acquire()           # dead pid → stale → taken over
    assert lk.took_over["pid"] == 999999999
    lk.release()


def test_owner_lock_refuses_live_other_process(tmp_path):
    import socket
    p = tmp_path / "running.json"
    p.write_text(json.dumps({"pid": os.getppid(), "host": socket.gethostname(), "started": "x"}))
    with pytest.raises(RuntimeError, match="正在執行"):
        OwnerLock(p).acquire()


def test_find_workflows(tmp_path):
    for name, steps in (("a", {"report": {"status": "PASS"}}), ("b", {"docking": {"status": "PASS"}}),
                        ("c", {"md_cases": {"status": "NEEDS_HUMAN"}})):
        d = tmp_path / "proj" / "workflows" / name
        d.mkdir(parents=True)
        (d / "config.json").write_text("{}")
        (d / "state.json").write_text(json.dumps({"steps": steps}))
    st = {r["name"]: r["status"] for r in find_workflows(tmp_path)}
    assert st == {"a": "COMPLETE", "b": "INCOMPLETE", "c": "NEEDS_HUMAN"}
    assert workflow_status({}) == "NEW"
