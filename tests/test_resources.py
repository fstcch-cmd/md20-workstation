from md20.env.resources import plan, guard_reason, platform_properties, DutyCycle, CachedGuard
from md20.engine.queue import PausePolicy


def test_plans():
    assert plan("background", 16).threads == 4
    assert plan("balanced", 16).threads == 14
    assert plan("full", 16).threads == 16 and plan("full").gpu_duty == 1.0
    assert platform_properties("CPU", {}, plan("background", 8)) == {"Threads": "2"}
    assert platform_properties("CUDA", {"Precision": "mixed"}, plan("background", 8)) == {"Precision": "mixed"}


def test_guards():
    assert "記憶體" in guard_reason(ram_probe=lambda: 97.0, temp_probe=lambda: None)
    assert "GPU 溫度" in guard_reason(ram_probe=lambda: 40.0, temp_probe=lambda: 90)
    assert guard_reason(ram_probe=lambda: 40.0, temp_probe=lambda: 60) is None
    pol = PausePolicy(resource_guard=CachedGuard(ram_probe=lambda: 99.0, temp_probe=lambda: None))
    assert "記憶體" in pol()


def test_duty_cycle_sleeps_proportionally():
    # Deterministic: inject a fake clock + capture sleeps instead of wall-clock timing (D-179;
    # the old real-sleep version flaked on loaded macOS CI runners). 50% duty → sleep == busy.
    ticks = iter([100.0, 100.06, 100.06])   # init t0, then now (busy=0.06), then reset
    slept = []
    d = DutyCycle(0.5, clock=lambda: next(ticks), sleep=slept.append)
    d()
    assert len(slept) == 1 and abs(slept[0] - 0.06) < 1e-9   # busy * (1-0.5)/0.5 = busy

    # cap at 5.0 s regardless of how long the busy interval was
    ticks2 = iter([0.0, 100.0, 100.0])
    slept2 = []
    DutyCycle(0.5, clock=lambda: next(ticks2), sleep=slept2.append)()
    assert slept2 == [5.0]

    # duty == 1.0 never sleeps (GPU fully busy)
    slept3 = []
    DutyCycle(1.0, clock=lambda: 1.0, sleep=slept3.append)()
    assert slept3 == []
