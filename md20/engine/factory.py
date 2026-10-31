"""Backend factory shared by CLI, workflow and GUI: real OpenMM on the best platform, or the Fake backend."""
from __future__ import annotations

from ..util import load_json


def make_backend_factory(case, protocol, *, fake: bool = False, platform=None):
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

    def make(spec, dt):
        return OpenMMBackend(sys_xml, top, platform_name=platform.name, platform_properties=platform.properties,
                             timestep_fs=dt, temperature_k=spec.temperature_k, friction_per_ps=spec.friction_per_ps,
                             ensemble=spec.ensemble, pressure_bar=spec.pressure_bar,
                             barostat_interval_steps=spec.barostat_interval_steps, hmr=protocol.hmr, seed=spec.seed)
    return make
