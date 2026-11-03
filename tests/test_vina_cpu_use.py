"""D-72: measure how many threads Vina really kept busy, and tag it HighQoS on Windows 11 hybrid CPUs."""
import sys

import pytest

from md20.docking import vina_cli
from md20.env import resources, winfix

BUSY = "import time\nt=time.process_time()\nwhile time.process_time()-t<1.5: pass\n"
IDLE = "import time\ntime.sleep(1.5)\n"


def test_effective_threads_measures_a_busy_child():
    p, run = vina_cli._run_measured([sys.executable, "-c", BUSY], 60, 0, False)
    assert p.returncode == 0
    assert 0.6 <= run["effective_threads"] <= 1.3, run      # one busy thread ≈ 1
    if sys.platform == "win32":
        assert run["qos"] == "high"                         # SetProcessInformation accepted the tag


def test_effective_threads_of_an_idle_child_is_near_zero():
    _, run = vina_cli._run_measured([sys.executable, "-c", IDLE], 60, 0, False)
    assert run["effective_threads"] < 0.4, run


def test_cpu_use_note_flags_os_throttling_only_when_far_below_bound():
    base = {"cpu_requested": 16, "exhaustiveness": 32, "threads_possible": 16, "wall_s": 3600, "cpu_s": 14400}
    why, held = vina_cli.cpu_use_note({**base, "effective_threads": 4.0})     # the laptop: 4 of 16
    assert held and "節能核心" in why
    why, held = vina_cli.cpu_use_note({**base, "effective_threads": 14.5})
    assert not held
    # exhaustiveness 8 on 16 threads: only 8 can work — Vina's design, not a fault
    why, held = vina_cli.cpu_use_note({**base, "exhaustiveness": 8, "threads_possible": 8, "effective_threads": 7.6})
    assert not held and "用不到" in why
    why, held = vina_cli.cpu_use_note({**base, "wall_s": 30, "effective_threads": 1.0})   # too short to judge
    assert not held


def test_eco_qos_only_in_background_mode():
    assert resources.child_eco_qos("background") is True
    assert resources.child_eco_qos("balanced") is False and resources.child_eco_qos("full") is False


def test_power_throttling_is_a_noop_off_windows():
    if sys.platform == "win32":
        pytest.skip("Windows path tested above")
    assert winfix.set_power_throttling(None, eco=False) is False
    assert winfix.process_cpu_seconds(0) is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows API")
def test_power_throttling_tags_this_process_on_windows():
    assert winfix.set_power_throttling(None, eco=False) is True
