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
    import time
    d = DutyCycle(0.5)
    time.sleep(0.05)
    t0 = time.monotonic(); d(); slept = time.monotonic() - t0
    assert 0.03 < slept < 0.5
