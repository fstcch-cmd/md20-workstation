"""D-69: on Windows, children (vina.exe) must end when MD20 ends — even when the console window is closed."""
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object")

PARENT = r"""
import os, subprocess
from md20.env.winfix import kill_children_on_exit
assert kill_children_on_exit()
p = subprocess.Popen(["ping", "-n", "120", "127.0.0.1"], stdout=subprocess.DEVNULL)
print(p.pid, flush=True)
os._exit(0)          # abrupt end, like a closed console window: no cleanup code runs
"""


def _alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


def test_child_process_ends_with_md20():
    r = subprocess.run([sys.executable, "-c", PARENT], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    pid = int(r.stdout.strip().splitlines()[-1])
    for _ in range(20):
        if not _alive(pid):
            break
        time.sleep(0.5)
    assert not _alive(pid), "the child outlived its parent: vina.exe would keep running after the window is closed"
