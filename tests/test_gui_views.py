"""WP13 view models: gate cards, timeline, live curves, offline 3D scene (no NiceGUI, no OpenMM)."""
import copy
import json
import shutil

import numpy as np
import pytest

from md20.gui.views import (gate_cards, timeline, live_series, echart_options, parse_pdb_atoms, build_scene,
                            viewer_html, STATIC)
from md20.project.store import Project
from md20.util.jsonio import atomic_write_json
from md20.workflow import Workflow, WorkflowBlocked, example_config


def _pdb_line(i, name, res, chain, seq, x, y, z, el, het=False):
    rec = "HETATM" if het else "ATOM  "
    return f"{rec}{i:5d} {name:<4s} {res:>3s} {chain}{seq:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00          {el:>2s}"


def _mini_pdb():
    lines, i = [], 1
    for k in range(10):                                   # 10-residue helix-ish trace along x
        x = 3.8 * k
        for nm, dx, el in (("N", -1.2, "N"), ("CA", 0.0, "C"), ("C", 1.2, "C"), ("O", 1.5, "O"), ("CB", 0.0, "C")):
            lines.append(_pdb_line(i, nm, "ALA", "A", k + 1, x + dx, 0.0 if nm != "CB" else 1.5, 0.0, el)); i += 1
    for nm, xyz in (("C1", (11.4, 4.0, 0.0)), ("C2", (12.8, 4.0, 0.0)), ("N1", (13.5, 5.2, 0.0))):
        lines.append(_pdb_line(i, nm, "L01", "B", 1, *xyz, nm[0], het=True)); i += 1
    lines.append(_pdb_line(i, "H1", "L01", "B", 1, 14.5, 5.2, 0.0, "H", het=True)); i += 1
    lines.append(_pdb_line(i, "O", "HOH", "W", 1, 0.0, 9.0, 0.0, "O", het=True)); i += 1
    lines.append(_pdb_line(i, "ZN", "ZN", "C", 1, 20.0, 4.0, 0.0, "ZN", het=True)); i += 1
    return "\n".join(lines) + "\nEND\n"


def test_scene_keeps_ligand_pocket_trace_metal_and_drops_water():
    atoms, xyz = parse_pdb_atoms(_mini_pdb())
    sc = build_scene(atoms, xyz, pocket_cutoff_A=5.0)
    kinds = [a["k"] for a in sc["atoms"]]
    assert kinds.count("L") == 3                          # heavy ligand atoms only, ligand H dropped
    assert "M" in kinds and all(a["r"] != "HOH" for a in sc["atoms"])
    assert sc["summary"]["n_pocket_residues"] >= 1 and "T" in kinds
    assert len(sc["frames"]) == 1 and len(sc["frames"][0]) == 3 * len(sc["atoms"])
    lig = [i for i, a in enumerate(sc["atoms"]) if a["k"] == "L"]
    assert [lig[0], lig[1]] in sc["bonds"] and [lig[1], lig[2]] in sc["bonds"]
    trace = [b for b in sc["bonds"] if sc["atoms"][b[0]]["n"] == "CA" and sc["atoms"][b[1]]["n"] == "CA"]
    assert len(trace) == 9                                # consecutive Cα along the chain


def test_scene_multi_frame_and_explicit_indices():
    atoms, xyz = parse_pdb_atoms(_mini_pdb())
    frames = np.stack([xyz, xyz + 0.5, xyz + 1.0])
    lig = [i for i, a in enumerate(atoms) if a["r"] == "L01"]
    sc = build_scene(atoms, frames, ligand_indices=lig, times_ps=[0, 10, 20])
    assert sc["summary"]["n_frames"] == 3 and sc["times_ps"] == [0.0, 10.0, 20.0]


def test_viewer_html_is_self_contained():
    atoms, xyz = parse_pdb_atoms(_mini_pdb())
    h = viewer_html(build_scene(atoms, xyz), title="t")
    assert h.startswith("<!DOCTYPE html>") and "md20Mount" in h and "MD20View" in h
    assert "http://" not in h and "https://" not in h       # nothing fetched from the network


def test_viewer_renders_in_headless_browser(tmp_path):
    """Real browser: the viewer draws non-background pixels and raises no JS error (local Chromium only)."""
    pw = pytest.importorskip("playwright.sync_api")
    atoms, xyz = parse_pdb_atoms(_mini_pdb())
    sc = build_scene(atoms, np.stack([xyz, xyz + 0.3]), times_ps=[0, 10])
    page_file = tmp_path / "v.html"
    page_file.write_text(viewer_html(sc), encoding="utf-8")
    try:
        with pw.sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(page_file.as_uri())
            n = pg.evaluate("""() => { const c = document.querySelector('canvas'); const d = c.getContext('2d')
                 .getImageData(0, 0, c.width, c.height).data; let k = 0;
                 for (let i = 0; i < d.length; i += 4) if (d[i] !== 0x11 || d[i+1] !== 0x14 || d[i+2] !== 0x18) k++; return k; }""")
            pg.click("button")                            # play / pause the trajectory
            pg.wait_for_timeout(300)
            pg.click("button")
            pg.click("text=表面")                         # vdW surface on, interactions off → redraw without errors
            pg.click("text=互作")
            b.close()
    except Exception as exc:  # noqa: BLE001  (no browser on this runner)
        if "Executable doesn't exist" in str(exc) or "playwright install" in str(exc):
            pytest.skip(str(exc)[:200])
        raise
    assert not errors, errors
    assert n > 500, n


def test_live_series_from_heartbeats_smd_umbrella():
    hist = [{"stage": "nvt", "absolute_step": s, "temperature_k": 290 + s / 100, "potential_kj_mol": -1e5 + s,
             "completed_local_steps": s, "total_steps": 1000} for s in range(0, 1000, 100)]
    hist += [{"stage": "smd", "r0": 1.0 + 0.1 * k, "force": 100.0 * k, "work": 5.0 * k} for k in range(5)]
    hist += [{"stage": "umbrella", "window": 3, "n": 12, "mean": 1.2}]
    s = live_series(hist)
    assert len(s["temperature"]) == 10 and s["potential"][0] == [0, -100000.0]
    assert s["progress"]["pct"] == 90.0 and s["umbrella"]["pct"] == 25.0
    assert len(s["smd_force"]) == 5 and s["smd_work"][-1] == [1.4, 20.0]
    o = echart_options(s["temperature"], title="T", x="step", y="K")
    assert o["series"][0]["data"] == s["temperature"]


def _wf(tmp_path):
    cfg = copy.deepcopy(example_config())
    return Workflow(Project.create(tmp_path, "p"), cfg)


def test_gate_cards_and_timeline(tmp_path):
    wf = _wf(tmp_path)
    wf.dec.record("workflow.pose", "BEN", "rank 1", "第 1 名 pose 通過保守條件")
    case = wf.project.new_case("p_docked_BEN")
    case.build_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json({"receptor": {"gates": {"gates": [
        {"name": "altloc", "status": "AUTO_FIXED", "explanation": "保留 A"},
        {"name": "protein", "status": "PASS", "explanation": "ok"}]}},
        "assembly": {"gates": {"gates": [{"name": "metal ZN:A301", "status": "NEEDS_HUMAN", "explanation": "只有 2 個配位",
                                          "options": ["keep_nonbonded", "remove"]}]}},
        "ligands": [{"name": "L01", "gates": {"gates": [{"name": "charge", "status": "PASS", "explanation": "ok"}]}}]},
        case.build_dir / "build_manifest.json")
    wf._mark("md_cases", cases={"docked_BEN": {"case_id": case.case_id}})
    with pytest.raises(WorkflowBlocked):
        wf._block("pose_selection", "BEN：都不穩定（選項：重跑對接 / 指定名次）")
    cards = gate_cards(wf)
    assert cards[0]["status"] == "NEEDS_HUMAN"
    blk = next(c for c in cards if c["source"] == "pose 選擇")
    assert blk["options"] == ["重跑對接", "指定名次"] and "都不穩定" in blk["explanation"]
    assert any(c["title"] == "metal ZN:A301" and c["color"] == "negative" for c in cards)
    assert any(c["title"] == "altloc" and c["label"] == "已自動修正" for c in cards)
    assert not any(c["status"] == "PASS" for c in cards)
    assert len(gate_cards(wf, include_pass=True)) == len(cards) + 2
    tl = timeline(wf)
    assert [e["at"] for e in tl] == sorted(e["at"] for e in tl)
    assert any(e["title"].startswith("workflow.pose") and "保守" in e["text"] for e in tl)
    assert any(e["kind"] == "step" and e["title"] == "pose 選擇" and e["status"] == "NEEDS_HUMAN" for e in tl)


def test_static_asset_present():
    assert (STATIC / "md20view.js").is_file()


def test_viewer_targets_and_scene(tmp_path):
    from md20.gui.views import viewer_targets, scene_for
    wf = _wf(tmp_path)
    case = wf.project.new_case("p_docked_BEN")
    case.build_dir.mkdir(parents=True, exist_ok=True)
    top = case.build_dir / "topology.pdb"; top.write_text(_mini_pdb(), encoding="utf-8")
    atomic_write_json({"topology_pdb": str(top), "ligands": [{"name": "L01"}],
                       "assembly": {"ligands": [{"name": "L01", "atom_indices": [50, 51, 52, 53]}]}},
                      case.build_dir / "build_manifest.json")
    wf._mark("md_cases", cases={"docked_BEN": {"case_id": case.case_id}})
    wf._mark("md_runs", runs={"docked_BEN": {"case_id": case.case_id, "status": "COMPLETE", "run_ids": ["r1"]}})
    t = viewer_targets(wf)
    assert [x["mode"] for x in t] == ["start", "traj"] and t[0]["ligand_indices"] == [50, 51, 52, 53]
    sc = scene_for(t[0])
    assert sc["summary"]["n_ligand_atoms"] == 3
    from md20.report.workflow_report import _viewer_section
    sec = _viewer_section(wf)                  # trajectory needs mdtraj + DCD → falls back to the start structure
    assert "md20Mount" in sec and "docked_BEN" in sec


def test_ligand_interactions_geometry_and_occupancy():
    from md20.gui.views import ligand_interactions, interaction_table_html
    sa = [{"e": "O", "n": "O1", "r": "L01", "s": "1", "k": "L"}, {"e": "C", "n": "C1", "r": "L01", "s": "1", "k": "L"},
          {"e": "O", "n": "OG", "r": "SER", "s": "195", "k": "P"}, {"e": "C", "n": "CD1", "r": "LEU", "s": "99", "k": "P"},
          {"e": "C", "n": "CA", "r": "LEU", "s": "99", "k": "P"}, {"e": "C", "n": "CB", "r": "SER", "s": "195", "k": "P"},
          {"e": "Zn", "n": "ZN", "r": "ZN", "s": "301", "k": "M"}]
    f0 = np.array([[0, 0, 0], [3, 0, 0], [0, 3.0, 0], [3, 3.8, 0], [3.0, -3.5, 0], [0, -3.9, 0], [-2.1, 0, 0]], float)
    f1 = f0.copy(); f1[:2] += [0, 0, 20.0]                   # ligand leaves the pocket in frame 2
    out = ligand_interactions(sa, np.stack([f0, f1]))
    kinds = {(sa[j]["r"] + sa[j]["s"], t) for i, j, t in out["frames"][0]}
    assert kinds == {("SER195", "h"), ("LEU99", "c"), ("ZN301", "m")}   # Leu CA (backbone) and Ser CB are not hydrophobic contacts
    assert out["frames"][1] == []
    assert {o["fraction"] for o in out["occupancy"]} == {0.5}
    h = interaction_table_html({"interactions": out, "summary": {"n_frames": 2}})
    assert "SER195" in h and "氫鍵候選" in h and "50%" in h and "未檢查角度" in h


def test_scene_carries_interactions_and_viewer_shows_table():
    atoms, xyz = parse_pdb_atoms(_mini_pdb())
    sc = build_scene(atoms, xyz, pocket_cutoff_A=5.0)
    assert len(sc["interactions"]["frames"]) == 1
    assert any(o["type"] == "c" for o in sc["interactions"]["occupancy"])      # ligand C next to an Ala CB
    h = viewer_html(sc)
    assert "疏水接觸" in h and "不是溶劑可及表面" in h
