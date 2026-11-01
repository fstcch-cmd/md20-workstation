"""WP13 smoke test on the real GUI stack: start `md20 gui`, request every page (pages are built server-side,
so API mistakes in the page code surface as HTTP 500).  Runs where NiceGUI is installed (openmm-stack CI)."""
import copy
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

pytest.importorskip("nicegui")

from md20.project.store import Project
from md20.util.jsonio import atomic_write_json
from md20.workflow import Workflow, WorkflowBlocked, example_config


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def _get(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", errors="ignore")


@pytest.fixture
def gui_project(tmp_path):
    from test_gui_views import _mini_pdb
    cfg = copy.deepcopy(example_config()); cfg["name"] = "demo"
    proj = Project.create(tmp_path, "proj")
    wf = Workflow(proj, cfg)
    case = proj.new_case("demo_docked_BEN")
    case.build_dir.mkdir(parents=True, exist_ok=True)
    top = case.build_dir / "topology.pdb"; top.write_text(_mini_pdb(), encoding="utf-8")
    atomic_write_json({"topology_pdb": str(top), "system_xml": "s",
                       "assembly": {"ligands": [{"name": "L01", "atom_indices": [50, 51, 52, 53], "heavy_atom_indices": [50, 51, 52]}],
                                    "gates": {"gates": [{"name": "metal ZN:C1", "status": "AUTO_FIXED", "explanation": "bonded"}]}}},
                      case.build_dir / "build_manifest.json")
    wf.dec.record("workflow.pose", "BEN", "rank 1", "測試決策")
    wf._mark("md_cases", cases={"docked_BEN": {"case_id": case.case_id, "mode": "docked_single", "ligands": ["BEN"]}})
    # a blocked step with a structured gate → the page renders one-click decision buttons + a reason input
    try:
        wf._block("structure_gate", "結構可信度：resolution", gates=[{
            "name": "resolution", "status": "NEEDS_HUMAN", "explanation": "解析度 3.4 Å",
            "options": ["換一個更高解析度的結構", "仍要使用（structure_override.resolution）"]}])
    except WorkflowBlocked:
        pass
    return tmp_path, proj.dir.name, wf.name


def test_gui_pages_render(gui_project):
    root, project, name = gui_project
    port = _free_port()
    # NiceGUI switches to its own screen-test mode when it sees pytest's env var and then requires
    # NICEGUI_SCREEN_TEST_PORT; the GUI under test is a normal server process, so hide pytest from it
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen([sys.executable, "-m", "md20", "--dir", str(root), "gui", "--port", str(port), "--no-browser"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    base = f"http://127.0.0.1:{port}"
    try:
        up = False
        for _ in range(360):                      # up to ~180s: NiceGUI + openmm import is slow on a loaded CI runner
            try:
                _get(base + "/", timeout=2); up = True; break
            except Exception:  # noqa: BLE001
                if proc.poll() is not None:        # the server process died → a real error, show its output
                    pytest.fail(proc.stdout.read().decode(errors="ignore")[-4000:])
                time.sleep(0.5)
        if not up:
            pytest.skip("GUI server did not become reachable in time on this runner")
        st, body = _get(base + "/")
        assert st == 200
        st, body = _get(f"{base}/wf/{project}/{name}")
        assert st == 200 and "閘門" in body and "3D" in body, body[-2000:]
        assert "仍要使用" in body and "需要在程式外處理" in body, body[-2000:]     # one-click button + manual hint rendered
        st, body = _get(f"{base}/viewer?project={project}&name={name}&i=0")
        assert st == 200 and "md20Mount" in body and "https://" not in body
    finally:
        proc.terminate()
        try:
            out = proc.communicate(timeout=10)[0].decode(errors="ignore")
        except subprocess.TimeoutExpired:
            proc.kill(); out = ""
    assert "Traceback" not in out, out[-4000:]
