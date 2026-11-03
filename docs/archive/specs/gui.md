> **已被取代（2026-11-01）**：這是第一個 session 的規格，模組與頁面結構與現在的程式不符；請以 `../WORKFLOW.md`、`hts_screen.md`、`gate_actions.md` 與原始碼為準。

# Spec: `md20.gui` (NiceGUI, local browser UI)

Goal: a teaching GUI over the existing package. No new science; every action calls existing functions.
NiceGUI may be absent in some environments → `import md20.gui` must not fail (lazy import inside `launch()`),
and `md20 gui` prints an install hint if NiceGUI is missing.

## Pages (left drawer navigation; Traditional Chinese labels)
1. **Doctor** — button "執行診斷" runs `md20.env.run_doctor(do_benchmark=True, benchmark_seconds=10)` in a
   background thread (`run.io_bound`); renders `report.to_markdown()`; shows findings table with severity colors;
   "複製給老師" copies the markdown.
2. **專案** — projects dir picker (default `md20.util.default_projects_dir()`), list projects (`Project.discover`),
   create project, select active project; list cases with status (`case.manifest()["status"]`) and runs with
   `run.stage()`.
3. **Docking** (optional; only if `md20.docking` exists — guard with try/except import): receptor file, ligand
   list (SMILES textarea or file paths), box mode, docking mode (independent/simultaneous), run button → table of
   poses per ligand with recommendation reason; per-ligand pose selector (radio); "送交 MD 建模" calls handoff.
4. **建模** — form: receptor path, ligand references (one per line: SMILES or SDF path), optional poses,
   co-crystal residue names, pH, padding, ionic strength; "開始建模" runs `md20.build.pipeline.build_case` in a
   thread; show the **three-state gate table** (PASS/AUTO_FIXED/NEEDS_HUMAN with explanation, diff, options);
   for NEEDS_HUMAN gates render the `options` as radio buttons and a "套用選擇並重試" button that re-runs with
   `human_choices`.
5. **執行** — choose case, tier (`md20.engine.TIERS` with notes), replicas, HMR toggle (display only; tier decides),
   "開始／續跑"; progress via a `progress_cb` writing to a shared dict; live plots using `ui.echart` or `ui.line_plot`
   of temperature and potential energy from heartbeats (append per callback, keep last 2000 points);
   pause button creates `<project>/PAUSE`; shows `md20 queue` list; per-stage acceptance badges from
   `<stage>_complete.json`.
6. **報告** — pick run → "產生報告" (`md20.report.build_run_report`) → open in new tab (serve the HTML via
   `app.add_static_files` on the run dir); "可重現包" button (`reproducibility_bundle`) → download link.
7. **決策日誌** — table of `project.decisions.read()` with filter by stage.

## Implementation notes
- File: `md20/gui/app.py` with `build_app(state) -> None` registering pages and `launch(host="127.0.0.1", port=8420,
  native=False)`; state object (dataclass) holds projects_dir, active project/case/run, running threads.
- Long jobs: run in a thread; never block the event loop; use `ui.timer` to poll shared state.
- CLI: add `md20 gui [--port]` to `md20/cli.py` (keep argparse style).
- Tests (`tests/test_gui.py`): `pytest.importorskip("nicegui")`; construct the app with NiceGUI's testing client
  (`nicegui.testing.User` or `Screen` if available — otherwise just import `build_app` and call it with a fresh
  state inside a `ui.page` context) and assert the drawer contains the 7 labels; plus a pure-Python test for the
  heartbeat buffer logic (`md20/gui/buffers.py`: ring buffer append/trim).
- Keep it visually clean: NiceGUI default theme, `ui.card` per section, no custom CSS beyond minimal.
- Everything user-facing in Traditional Chinese.
- Run `python -m pytest -q` before finishing.
