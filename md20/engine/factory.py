"""Backend factory shared by CLI, workflow and GUI: real OpenMM on the best platform, or the Fake backend."""
from __future__ import annotations

from ..util import load_json


def make_backend_factory(case, protocol, *, fake: bool = False, platform=None, resource_mode: str | None = None):
    if fake:
        from .backend import FakeBackend
        return lambda spec, dt: FakeBackend(timestep_fs=dt, temperature_k=spec.temperature_k, ensemble=spec.ensemble,
                                            seed=spec.seed)
    from .backend import OpenMMBackend
    if platform is None:
        from ..env import choose_platform
        platform = choose_platform()
    bm = load_json(case.build_dir / "build_manifest.json", {})
    sys_xml, top = bm.get("system_xml"), bm.get("topology_pdb")
    if not sys_xml or not top:
        raise RuntimeError(f"case {case.case_id} 尚未 build 成功。")
    case.project.decisions.record("engine.platform", "OpenMM platform", platform.name,
                                  "依 CUDA→HIP→OpenCL→CPU 順序實測第一個能建立 Context 的平台。", rejected=platform.rejected)
    props = platform.properties
    duty = None
    if resource_mode:
        from ..env.resources import plan, apply_priority, platform_properties, DutyCycle
        rp = plan(resource_mode)
        props = platform_properties(platform.name, props, rp)
        msg = apply_priority(rp.priority)
        duty = DutyCycle(rp.gpu_duty) if platform.name != "CPU" and rp.gpu_duty < 1.0 else None
        case.project.decisions.record("engine.resources", "mode", rp.to_dict(), f"資源模式 {resource_mode}：{msg}。")

    def make(spec, dt):
        b = OpenMMBackend(sys_xml, top, platform_name=platform.name, platform_properties=props,
                             timestep_fs=dt, temperature_k=spec.temperature_k, friction_per_ps=spec.friction_per_ps,
                             ensemble=spec.ensemble, pressure_bar=spec.pressure_bar,
                             barostat_interval_steps=spec.barostat_interval_steps, hmr=protocol.hmr, seed=spec.seed)
        if duty is not None:
            _step = b.step

            def throttled(n, _s=_step):
                _s(n)
                duty()
            b.step = throttled
        return b
    return make
