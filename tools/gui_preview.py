"""Render the MD20 GUI pages to PNG for design review (CI job `gui-preview`; D-42).

Builds a small demo project (one workflow with a blocked gate and a decision, as in tests/test_gui_server.py),
starts `md20 gui`, and screenshots every page with Playwright/Chromium.  Usage: python tools/gui_preview.py OUT_DIR
"""
from __future__ import annotations

import copy
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def build_demo(root: Path) -> tuple[str, str]:
    from test_gui_views import _mini_pdb
    from md20.project.store import Project
    from md20.util.jsonio import atomic_write_json
    from md20.workflow import Workflow, WorkflowBlocked, example_config
    cfg = copy.deepcopy(example_config()); cfg["name"] = "trypsin_demo"
    proj = Project.create(root, "教學示範")
    wf = Workflow(proj, cfg)
    case = proj.new_case("demo_docked_BEN")
    case.build_dir.mkdir(parents=True, exist_ok=True)
    top = case.build_dir / "topology.pdb"; top.write_text(_mini_pdb(), encoding="utf-8")
    atomic_write_json({"topology_pdb": str(top), "system_xml": "s",
                       "assembly": {"ligands": [{"name": "L01", "atom_indices": [50, 51, 52, 53], "heavy_atom_indices": [50, 51, 52]}],
                                    "gates": {"gates": [{"name": "metal ZN:C1", "status": "AUTO_FIXED", "explanation": "bonded"}]}}},
                      case.build_dir / "build_manifest.json")
    wf.dec.record("workflow.pose", "BEN", "rank 1", "第 1 名 pose（-6.11 kcal/mol）；與晶體 RMSD 0.38 Å。")
    wf._mark("md_cases", cases={"docked_BEN": {"case_id": case.case_id, "mode": "docked_single", "ligands": ["BEN"]}})
    try:
        wf._block("structure_gate", "結構可信度：resolution", gates=[{
            "name": "resolution", "status": "NEEDS_HUMAN", "explanation": "解析度 3.4 Å（教學示範：故意擋下）",
            "options": ["換一個更高解析度的結構", "仍要使用（structure_override.resolution）"]}])
    except WorkflowBlocked:
        pass
    return proj.dir.name, wf.name


def main(out: Path) -> int:
    from playwright.sync_api import sync_playwright
    out.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="md20gui_"))
    project, name = build_demo(root)
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    proc = subprocess.Popen([sys.executable, "-m", "md20", "--dir", str(root), "gui", "--port", str(port), "--no-browser"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(240):
            try:
                urllib.request.urlopen(base + "/", timeout=2); break
            except Exception:  # noqa: BLE001
                if proc.poll() is not None:
                    print(proc.stdout.read().decode(errors="ignore")[-4000:]); return 1
                time.sleep(0.5)
        pages = {"01_dashboard": "/", "02_new_pipeline": "/new", "03_workflow": f"/wf/{project}/{name}",
                 "04_viewer": f"/viewer?project={project}&name={name}&i=0"}
        with sync_playwright() as p:
            br = p.chromium.launch()
            pg = br.new_page(viewport={"width": 1400, "height": 900}, device_scale_factor=1)
            for fname, path in pages.items():
                pg.goto(base + path, wait_until="networkidle", timeout=60000)
                pg.wait_for_timeout(2500)
                pg.screenshot(path=str(out / f"{fname}.png"), full_page=True)
                print("saved", fname)
            br.close()
    finally:
        proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "gui_preview")))
