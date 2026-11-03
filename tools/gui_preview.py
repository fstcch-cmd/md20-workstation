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
        pages = {"01_home": "/", "02_teach_small_molecules": "/teach/hsieh2024", "03_teach_peptide": "/teach/hsieh2025",
                 "04_quick": "/new/quick", "05_pro": "/new/pro", "06_workflow": f"/wf/{project}/{name}",
                 "07_system": "/system", "08_viewer": f"/viewer?project={project}&name={name}&i=0"}
        with sync_playwright() as p:
            br = p.chromium.launch()
            pg = br.new_page(viewport={"width": 1400, "height": 900}, device_scale_factor=1)
            from md20.util.jsonio import atomic_write_json
            for code in ("en", "zh", "ja", "ko"):          # D-51, D-74: all interface languages
                atomic_write_json({"lang": code}, root / "gui_settings.json")
                urllib.request.urlopen(base + "/", timeout=30).read()
                for fname, path in pages.items():
                    if code != "en" and fname.startswith("08"):
                        continue
                    pg.goto(base + path, wait_until="networkidle", timeout=60000)
                    pg.wait_for_timeout(2500)
                    pg.screenshot(path=str(out / f"{code}_{fname}.png"), full_page=True)
                    print("saved", code, fname)
            br.close()
    finally:
        proc.terminate()
    return stability(out)


def _fake_state(wf_dir: Path) -> dict:
    import json
    f = wf_dir / "_fake_run.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}


def stability(out: Path) -> int:
    """D-74: switching the interface language while a calculation runs must not stop, restart or duplicate it.

    Starts `md20 gui` with MD20_GUI_FAKE_RUN (the Runner runs a timed stand-in instead of the chemistry, so this
    works without OpenMM; everything else — teaching page, Runner, busy banner, language menu — is the real code),
    starts teaching case 2 from its page, then switches through all four languages with the header menu, revisits
    the teaching page and presses its start button again.  Checks: one start only, still running, one workflow
    folder, beats keep increasing.  Screenshots: stab_<lang>.png."""
    from playwright.sync_api import sync_playwright
    from md20.i18n import LANG_NAMES
    root = Path(tempfile.mkdtemp(prefix="md20stab_"))
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    env["MD20_GUI_FAKE_RUN"] = "240"
    proc = subprocess.Popen([sys.executable, "-m", "md20", "--dir", str(root), "gui", "--port", str(port), "--no-browser"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    base = f"http://127.0.0.1:{port}"
    problems: list[str] = []
    try:
        for _ in range(240):
            try:
                urllib.request.urlopen(base + "/", timeout=2); break
            except Exception:  # noqa: BLE001
                if proc.poll() is not None:
                    print(proc.stdout.read().decode(errors="ignore")[-4000:]); return 1
                time.sleep(0.5)
        with sync_playwright() as p:
            br = p.chromium.launch()
            pg = br.new_page(viewport={"width": 1400, "height": 900})
            pg.goto(base + "/teach/hsieh2025", wait_until="networkidle", timeout=60000)
            pg.get_by_test_id("start-lesson").click()
            pg.wait_for_url("**/wf/**", timeout=60000)
            wf_url = pg.url
            pg.wait_for_timeout(4000)
            wfs = list((root / "Teaching" / "workflows").glob("*/config.json"))
            if len(wfs) != 1:
                problems.append(f"expected one teaching workflow, found {len(wfs)}")
                return 1
            wf_dir = wfs[0].parent
            st0 = _fake_state(wf_dir)
            if st0.get("starts") != 1:
                problems.append(f"the run did not start once: {st0}")
            for code in ("zh", "ja", "ko", "en"):
                pg.get_by_test_id("lang-select").click()
                pg.get_by_role("option", name=LANG_NAMES[code]).click()
                pg.wait_for_load_state("networkidle")
                pg.wait_for_timeout(3000)
                pg.screenshot(path=str(out / f"stab_{code}.png"), full_page=True)
                # leave the page, come back, and press the lesson's start button again
                pg.goto(base + "/", wait_until="networkidle"); pg.wait_for_timeout(1000)
                pg.goto(base + "/teach/hsieh2025", wait_until="networkidle"); pg.wait_for_timeout(1000)
                pg.get_by_test_id("start-lesson").click()
                pg.wait_for_url("**/wf/**", timeout=60000)
                if pg.url.split("?")[0] != wf_url.split("?")[0]:
                    problems.append(f"{code}: start button led to {pg.url}, not the running lesson {wf_url}")
                pg.wait_for_timeout(2000)
                st = _fake_state(wf_dir)
                if st.get("starts") != 1:
                    problems.append(f"{code}: the run was started again ({st.get('starts')} starts)")
                if not st.get("beats", 0) > st0.get("beats", 0):
                    problems.append(f"{code}: the run stopped making progress ({st0.get('beats')} -> {st.get('beats')})")
                if st.get("finished"):
                    problems.append(f"{code}: the run ended early")
                st0 = st
                print("stability", code, st)
            n = len(list((root / "Teaching" / "workflows").glob("*/config.json")))
            if n != 1:
                problems.append(f"{n} teaching workflows after the language switches (expected 1)")
            br.close()
    finally:
        proc.terminate()
    print("STABILITY", "OK" if not problems else "FAILED")
    for m in problems:
        print(" -", m)
    (out / "stability.txt").write_text("OK\n" if not problems else "\n".join(problems) + "\n", encoding="utf-8")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "gui_preview")))
