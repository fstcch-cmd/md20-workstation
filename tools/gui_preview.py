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
                extras(pg, base, out, code)
            br.close()
    finally:
        proc.terminate()
    rc = stability(out)
    return rc or e2e(out)


def extras(pg, base: str, out: Path, code: str) -> None:
    """D-80 groups: professional mode with every group open (membrane, peptide folding), the long-run card for a
    2 µs production, and the computer status page after pressing the install-plan buttons.  A failure here is
    printed and does not stop the other screenshots."""
    from md20.advisor import param_label
    try:
        pg.goto(base + "/new/pro?expand=all", wait_until="networkidle", timeout=60000)
        pg.wait_for_timeout(2500)
        pg.screenshot(path=str(out / f"{code}_05b_pro_membrane_fold.png"), full_page=True)
        print("saved", code, "05b_pro_membrane_fold")
        box = pg.get_by_label(param_label("production_ns", code)).first
        box.fill("2000")
        box.blur()
        pg.wait_for_timeout(1500)
        pg.get_by_test_id("long-run").screenshot(path=str(out / f"{code}_05c_pro_long_run.png"))
        print("saved", code, "05c_pro_long_run")
    except Exception as exc:  # noqa: BLE001
        print("extras (pro groups) failed:", code, type(exc).__name__, exc)
    try:
        pg.goto(base + "/system", wait_until="networkidle", timeout=60000)
        pg.wait_for_timeout(1500)
        for k in ("fold", "cg"):
            pg.get_by_test_id(f"preview-{k}").click()
            pg.wait_for_timeout(1500)
        pg.screenshot(path=str(out / f"{code}_07b_system_tools.png"), full_page=True)
        print("saved", code, "07b_system_tools")
    except Exception as exc:  # noqa: BLE001
        print("extras (tools) failed:", code, type(exc).__name__, exc)


def _fake_state(wf_dir: Path) -> dict:
    import json
    f = wf_dir / "_fake_run.json"
    for _ in range(20):                          # the stand-in rewrites the file every second (atomically since D-103)
        try:
            return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
        except (ValueError, OSError):
            time.sleep(0.1)
    return {}


def _stop_worker(root: Path) -> None:
    """The fake calculation process outlives the GUI by design (D-103); end it when the check is over."""
    import json
    import signal
    for f in root.glob("*/workflows/*/_gui_job/job.json"):
        try:
            pid = int(json.loads(f.read_text(encoding="utf-8")).get("pid") or 0)
            if pid and json.loads(f.read_text(encoding="utf-8")).get("status") == "RUNNING":
                os.kill(pid, signal.SIGTERM)
        except (OSError, ValueError):
            pass


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
            # D-103: the calculation runs in its own process.  Stop the GUI (as a crash or a closed window would),
            # check the calculation keeps going, start the GUI again and check it attaches to the same run: the
            # banner and the progress line come back from the files, and the start button does not start it twice.
            proc.terminate()
            proc.wait(30)
            a = _fake_state(wf_dir); time.sleep(4); b = _fake_state(wf_dir)
            if not b.get("beats", 0) > a.get("beats", 0) or b.get("finished"):
                problems.append(f"GUI stopped: the calculation stopped too ({a.get('beats')} -> {b.get('beats')})")
            port = _free_port()
            base = f"http://127.0.0.1:{port}"
            proc = subprocess.Popen([sys.executable, "-m", "md20", "--dir", str(root), "gui", "--port", str(port), "--no-browser"],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
            for _ in range(240):
                try:
                    urllib.request.urlopen(base + "/", timeout=2); break
                except Exception:  # noqa: BLE001
                    time.sleep(0.5)
            pg.goto(base + "/", wait_until="networkidle"); pg.wait_for_timeout(3000)
            pg.screenshot(path=str(out / "stab_restart_home.png"), full_page=True)
            if wf_dir.name not in pg.content():
                problems.append("after the GUI restart the home page does not show the running calculation")
            pg.goto(base + "/" + wf_url.split("/", 3)[3].split("?")[0], wait_until="networkidle")
            # the progress line lives on the live-curves tab (third tab: gates, screening, live), in any language
            pg.locator(".q-tab").nth(2).click()
            pg.wait_for_timeout(5000)
            pg.screenshot(path=str(out / "stab_restart_wf.png"), full_page=True)
            if "fake" not in pg.content():
                problems.append("after the GUI restart the progress line is empty (not read back from progress.jsonl)")
            pg.goto(base + "/teach/hsieh2025", wait_until="networkidle"); pg.wait_for_timeout(1000)
            pg.get_by_test_id("start-lesson").click()
            pg.wait_for_url("**/wf/**", timeout=60000); pg.wait_for_timeout(2000)
            c = _fake_state(wf_dir)
            if c.get("starts") != 1:
                problems.append(f"after the GUI restart the run was started again ({c.get('starts')} starts)")
            print("stability restart", c)
            br.close()
    finally:
        proc.terminate()
        _stop_worker(root)
    print("STABILITY", "OK" if not problems else "FAILED")
    for m in problems:
        print(" -", m)
    (out / "stability.txt").write_text("OK\n" if not problems else "\n".join(problems) + "\n", encoding="utf-8")
    return 0 if not problems else 1


def _demo_membrane_scene(stage: str) -> dict:
    """Synthetic bilayer for the live-3D check (D-104): a 4 × 4 nm patch of head and tail atoms and a small peptide."""
    import numpy as np
    from md20.build.live3d import membrane_scene, STAGE_TEXT
    atoms, xyz, lip, heads = [], [], [], []
    for k in range(6):                                    # peptide above the membrane
        atoms.append({"e": "C", "n": "CA", "r": "GLY", "s": str(k + 1), "c": "P"}); xyz.append([1.5 + 0.38 * k, 2.0, 3.2])
    if stage != "solute":
        rng = np.random.default_rng(1)
        for leaf, z in ((1, 1.9), (-1, -1.9)):
            for gx in range(8):
                for gy in range(8):
                    x, y = 0.25 + 0.5 * gx, 0.25 + 0.5 * gy
                    heads.append(len(atoms)); lip.append(len(atoms))
                    atoms.append({"e": "P", "n": "P", "r": "POPC", "s": str(len(atoms)), "c": "M"}); xyz.append([x, y, z])
                    for t in range(1, 9):
                        lip.append(len(atoms))
                        atoms.append({"e": "C", "n": f"C{t}", "r": "POPC", "s": str(len(atoms)), "c": "M"})
                        xyz.append([x + rng.normal(0, 0.05), y + rng.normal(0, 0.05), z - leaf * 0.2 * t])
    return membrane_scene(atoms, np.array(xyz), lipid_indices=lip, head_indices=heads, planes_nm=[-1.9, 1.9],
                          box_nm=[4.0, 4.0, 8.0], stage=stage, lang_labels=STAGE_TEXT[stage])


def build_e2e(root: Path) -> tuple[str, str]:
    """A finished all-ligands workflow (hsieh2024-like): MD complete, PGA pulled once, report written."""
    from md20.project.store import Project
    from md20.util.jsonio import atomic_write_json
    from md20.workflow import Workflow, example_config
    cfg = copy.deepcopy(example_config()); cfg["name"] = "multi_demo"
    cfg["ligands"] = [{"name": n, "smiles": "CCO"} for n in ("PGA", "CAR", "GLU")]
    cfg["md"]["systems"] = ["apo", "docked_multi"]
    cfg["binding"] = {"enabled": True, "ligands": ["PGA"], "multi": True, "config": {}}
    proj = Project.create(root, "multi")
    wf = Workflow(proj, cfg)
    case = proj.new_case("docked_multi")             # D-94: a built case with a small topology, for the 3D tab
    lines, i = [], 0
    for rs, (x, y) in enumerate(((0.0, 0.0), (3.8, 0.0), (7.6, 0.0), (11.4, 0.0)), start=1):
        for nm, el, dx in (("N", "N", -1.2), ("CA", "C", 0.0), ("C", "C", 1.2)):
            i += 1
            lines.append(f"ATOM  {i:5d}  {nm:<3s} ALA A{rs:4d}    {x + dx:8.3f}{y:8.3f}{0.0:8.3f}  1.00  0.00          {el:>2s}")
    lig0 = i
    for k, (nm, el) in enumerate((("C1", "C"), ("O1", "O"), ("C2", "C"))):
        i += 1
        lines.append(f"HETATM{i:5d}  {nm:<3s} PGA B   1    {5.0 + 1.4 * k:8.3f}{3.5:8.3f}{0.0:8.3f}  1.00  0.00          {el:>2s}")
    top = case.build_dir / "topology.pdb"
    top.write_text("\n".join(lines) + "\nEND\n", encoding="utf-8")
    atomic_write_json({"topology_pdb": str(top), "assembly": {"ligands": [{"name": "PGA", "heavy_atom_indices": [lig0, lig0 + 1, lig0 + 2]}]}},
                      case.build_dir / "build_manifest.json")
    st = wf.state()
    st["steps"]["md_cases"] = {"status": "PASS", "cases": {"docked_multi": {"case_id": case.case_id, "mode": "docked_multi",
                                                                            "ligands": ["PGA", "CAR", "GLU"]}}}
    st["steps"]["md_runs"] = {"status": "PASS", "runs": {"docked_multi": {"status": "COMPLETE", "case_id": case.case_id, "run_ids": []}}}
    st["steps"]["binding"] = {"status": "PASS", "results": {"multi:PGA": {
        "status": "PASS", "ligand": "PGA", "context": "multi:docked_multi", "co_ligands": ["CAR", "GLU"], "replicas": 1,
        "delta_pmf_kj_mol": 18.0, "delta_pmf_err_kj_mol": 1.5, "dG_standard_kj_mol": -9.5, "dG_err_kj_mol": 1.6,
        "dG_standard_kcal_mol": -2.27, "dG_withheld": None, "per_replica": [], "caveats": [], "figures": {}}}}
    atomic_write_json(st, wf.state_path)
    return proj.dir.name, wf.name


def e2e(out: Path) -> int:
    """D-87/D-88 self-check with clicks in a real browser (MD20_GUI_FAKE_RUN replaces the chemistry):
    the binding panel lists the three ligands of the all-ligands system, adds CAR, adds one more run to PGA and
    rebuilds the report; the projects-folder card opens another folder and switches to a new one, and the choice
    is saved for the next start.  Every check that fails is printed and makes the job fail."""
    import json
    from playwright.sync_api import sync_playwright
    root = Path(tempfile.mkdtemp(prefix="md20e2e_"))
    other = Path(tempfile.mkdtemp(prefix="md20other_"))
    fresh = Path(tempfile.mkdtemp(prefix="md20fresh_")) / "new_projects"
    folders_file = Path(tempfile.mkdtemp(prefix="md20cfg_")) / "gui_folders.json"
    project, name = build_e2e(root)
    oproj, oname = build_e2e(other)
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    env["MD20_GUI_FAKE_RUN"] = "2"
    env["MD20_GUI_FOLDERS"] = str(folders_file)
    proc = subprocess.Popen([sys.executable, "-m", "md20", "--dir", str(root), "gui", "--port", str(port), "--no-browser"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    base = f"http://127.0.0.1:{port}"
    problems: list[str] = []
    wf_dir = root / project / "workflows" / name

    def cfg():
        return json.loads((wf_dir / "config.json").read_text(encoding="utf-8"))

    def check(cond, msg):
        if not cond:
            problems.append(msg)
        print("E2E", "ok " if cond else "FAIL", msg)
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
            pg = br.new_page(viewport={"width": 1400, "height": 1000})
            pg.goto(f"{base}/wf/{project}/{name}", wait_until="networkidle", timeout=60000)
            pg.get_by_test_id("binding-panel").locator(".q-expansion-item__container > .q-item").first.click()
            pg.wait_for_timeout(1500)
            panel = pg.get_by_test_id("binding-panel")
            for tk in ("multi:PGA", "multi:CAR", "multi:GLU"):
                check(panel.locator("tr", has_text=tk).count() == 1, f"binding panel lists {tk}")
            pg.screenshot(path=str(out / "e2e_binding_panel.png"), full_page=True)
            panel.locator("tr", has_text="multi:CAR").locator(".q-checkbox").first.click()
            pg.get_by_test_id("binding-add").click()
            pg.wait_for_timeout(4000)
            check("multi:CAR" in (cfg().get("binding") or {}).get("added", []), "Compute the selected ligands writes binding.added")
            st = json.loads((wf_dir / "state.json").read_text(encoding="utf-8"))
            check((st["steps"].get("binding") or {}).get("results", {}).get("multi:PGA", {}).get("status") == "PASS",
                  "the finished PGA result is kept")
            pg.wait_for_timeout(3000)                   # let the 2 s stand-in run end before the next button
            panel.locator("tr", has_text="multi:CAR").locator(".q-checkbox").first.click()
            panel.locator("tr", has_text="multi:PGA").locator(".q-checkbox").first.click()
            pg.get_by_test_id("binding-more").click()
            pg.wait_for_timeout(4000)
            check((cfg().get("binding") or {}).get("target_replicas", {}).get("multi:PGA") == 2,
                  "One more SMD run sets target_replicas[multi:PGA] = 2")
            pg.wait_for_timeout(3000)
            with pg.context.expect_page(timeout=60000) as newtab:
                pg.get_by_test_id("report-rebuild").click()
            rep = newtab.value
            rep.wait_for_load_state("networkidle", timeout=120000)
            check("ΔG" in rep.content(), "Rebuild the report opens a report with the binding results")
            rep.close()
            st = json.loads((wf_dir / "state.json").read_text(encoding="utf-8"))
            check(Path((st["steps"].get("report") or {}).get("path", "")).is_file(), "the rebuilt report is on disk")
            # 3D tab (D-94): the viewer iframe is really in the page and draws the molecule
            pg.goto(f"{base}/wf/{project}/{name}", wait_until="networkidle", timeout=60000)
            pg.get_by_role("tab", name="3D").first.click()
            pg.wait_for_timeout(2500)
            fr = pg.get_by_test_id("viewer-frame")
            check(fr.count() == 1 and "/viewer?" in (fr.first.get_attribute("src") or ""), "the 3D tab has the viewer frame")
            inner = pg.frame_locator('[data-testid="viewer-frame"]')
            try:
                inner.locator("canvas").first.wait_for(timeout=20000)
                ok = True
            except Exception:  # noqa: BLE001
                ok = False
            check(ok, "the 3D viewer draws on a canvas inside the tab")
            pg.screenshot(path=str(out / "e2e_3d.png"), full_page=True)
            # D-104: a membrane build in progress appears in the open 3D tab by itself and redraws after each step
            from md20.build import live3d as LV
            bdir = root / "_live_case" / "build"
            LV.mark_current(wf_dir, "membrane_demo", bdir)
            LV.write_stage(bdir, "solute", _demo_membrane_scene("solute"))
            pg.wait_for_timeout(4500)
            src1 = fr.first.get_attribute("src") or ""
            check("&t=" in src1, f"the live membrane build is shown without reloading the page ({src1})")
            try:
                inner.locator("canvas").first.wait_for(timeout=20000)
                ok = True
            except Exception:  # noqa: BLE001
                ok = False
            check(ok, "the live membrane scene draws on a canvas")
            time.sleep(1.1)
            LV.write_stage(bdir, "bilayer", _demo_membrane_scene("bilayer"))
            pg.wait_for_timeout(4500)
            src2 = fr.first.get_attribute("src") or ""
            check(src2 != src1, "the 3D tab redraws when the next build step is written")
            pg.screenshot(path=str(out / "e2e_3d_live.png"), full_page=True)
            # projects folder: open another folder (one project, one workflow → straight to it)
            pg.goto(base + "/", wait_until="networkidle")
            check(str(root) in pg.get_by_test_id("folder-now").inner_text(), "home shows the current projects folder")
            pg.get_by_test_id("folder-path").locator("xpath=descendant-or-self::input").first.fill(str(other / oproj))
            pg.get_by_test_id("folder-open").click()
            pg.wait_for_url("**/wf/**", timeout=30000)
            check(pg.url.rstrip("/").endswith(f"/wf/{oproj}/{oname}"), f"opening a project folder goes to its workflow ({pg.url})")
            # save new projects in a folder that does not exist yet
            pg.goto(base + "/", wait_until="networkidle")
            pg.get_by_test_id("folder-path").locator("xpath=descendant-or-self::input").first.fill(str(fresh))
            pg.get_by_test_id("folder-use").click()
            pg.wait_for_timeout(2500)
            pg.goto(base + "/", wait_until="networkidle")
            check(str(fresh) in pg.get_by_test_id("folder-now").inner_text(), "the projects folder switches to the new one")
            saved = json.loads(folders_file.read_text(encoding="utf-8")) if folders_file.is_file() else {}
            check(saved.get("projects_dir") == str(fresh) and str(other) in saved.get("recent", []),
                  "the choice and the recent folders are saved for the next start")
            pg.screenshot(path=str(out / "e2e_folders.png"), full_page=True)
            br.close()
    except Exception as exc:  # noqa: BLE001
        problems.append(f"{type(exc).__name__}: {exc}")
        print("E2E FAIL", type(exc).__name__, exc)
    finally:
        proc.terminate()
        try:
            log = proc.communicate(timeout=10)[0].decode(errors="ignore")
        except subprocess.TimeoutExpired:
            proc.kill(); log = ""
    if "Traceback" in log:
        problems.append("server printed a Traceback")
        print(log[-6000:])
    print("E2E", "OK" if not problems else "FAILED")
    (out / "e2e.txt").write_text("OK\n" if not problems else "\n".join(problems) + "\n", encoding="utf-8")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "gui_preview")))
