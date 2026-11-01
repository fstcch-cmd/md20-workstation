"""HTS screen: batch docking with a fake dock(), ranking/plots, workflow gates and the GUI selection action.
Pure Python (no Vina/RDKit): dock_fn is injected; receptor PDBQT conversion runs on a tiny real PDB."""
import copy
import json

import numpy as np
import pytest

from md20.docking.box import Box
from md20.docking.screen import (ScreenConfig, screen_dock, rank_screen, write_ranking_csv, screen_plots, failed_rows,
                                 echart_screen)
from md20.docking.run import DockingResult
from md20.gui.actions import select_screen_ligands, gate_actions, STEP_ORDER, invalidate_from
from md20.gui.logic import step_rows, screen_table
from md20.project.store import Project
from md20.util import load_json, DecisionLog
from md20.workflow import Workflow, WorkflowBlocked, example_config

PDB = ("ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N\n"
       "ATOM      2  CA  ALA A   1       1.500   0.000   0.000  1.00  0.00           C\n"
       "HETATM    3  C1  BEN A   2       3.000   0.000   0.000  1.00  0.00           C\nEND\n")
SDF = "\n  fake\n\n  1  0  0  0  0  0  0  0  0  0999 V2000\n    0.0000    0.0000    0.0000 C   0  0\nM  END\n$$$$\n"


@pytest.fixture(autouse=True)
def _pure_library_path(monkeypatch):
    """These tests pin the no-RDKit path (fake one-atom SDFs, honest `checked: False`).  In the openmm-stack env RDKit
    is installed and its size filters would skip every fake compound (CI c4b5de6, D-25); the RDKit path is covered by
    tests/test_screen_integration.py."""
    import md20.docking.library as lib
    monkeypatch.setattr(lib, "_rdkit_available", lambda: False)
SCORES = {"c1": -7.2, "c2": -7.9, "c3": -5.1, "c4": -7.5}


def fake_dock(receptor_pdb, ligands, box, out_dir, *, mode, receptor_pdbqt=None, **kw):
    """Mimics dock(): one entry per ligand with 3 poses; `bad` raises like Meeko would."""
    from pathlib import Path
    lig = ligands[0]
    if lig.name == "bad":
        raise RuntimeError("Meeko: could not type atom 7")
    assert receptor_pdbqt is not None and Path(receptor_pdbqt).is_file()
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    s = SCORES.get(lig.name, -6.0)
    poses = [{"rank": k + 1, "score": s + 0.3 * k, "cluster": 0, "cluster_size": 3 - k, "contacts": 20, "rmsd_ref": None,
              "min_ll_distance": None, "recommended": k == 0, "clash": False} for k in range(3)]
    sdfs = [str(out / f"pose_{k + 1:02d}.sdf") for k in range(3)]
    for p in sdfs:
        Path(p).write_text(SDF)
    res = DockingResult(mode=mode, receptor_pdbqt=str(receptor_pdbqt), box=box.to_dict(), params=dict(kw),
                        entries=[{"name": lig.name, "ligands": [lig.name], "smiles": "CC", "poses": poses, "pose_sdfs": {lig.name: sdfs},
                                  "recommended_rank": 1, "reason": "最大 cluster", "recommendation_status": "PASS"}])
    (out / "docking_results.json").write_text(json.dumps(res.to_dict()))
    return res


def _entries(tmp_path, names):
    d = tmp_path / "lib"; d.mkdir(exist_ok=True)
    out = []
    for n in names:
        (d / f"{n}.sdf").write_text(SDF)
        out.append({"name": n, "path": str(d / f"{n}.sdf"), "heavy_atoms": {"c1": 20, "c2": 30, "c3": 10, "c4": 25}.get(n, 15), "smiles": "CC"})
    return out


def _receptor(tmp_path):
    p = tmp_path / "rec.pdb"; p.write_text(PDB); return p


# ----------------------------------------------------------------------------- batch docking
def test_screen_dock_resumes_and_records_failures(tmp_path):
    rec = _receptor(tmp_path)
    ents = _entries(tmp_path, ["c1", "bad", "c2"])
    box = Box((0, 0, 0), (20, 20, 20), "test", "")
    dec = DecisionLog(tmp_path / "dec.jsonl")
    calls = []
    def dock_fn(*a, **k):
        calls.append(a[1][0].name); return fake_dock(*a, **k)
    ev = []
    res = screen_dock(rec, ents, box, tmp_path / "screen", ScreenConfig(), decisions=dec, dock_fn=dock_fn, progress_cb=ev.append)
    assert calls == ["c1", "bad", "c2"]
    assert res["entries"]["bad"]["status"] == "FAILED" and "Meeko" in res["entries"]["bad"]["error"]
    assert res["entries"]["c2"]["status"] == "OK" and res["entries"]["c2"]["score"] == pytest.approx(-7.9)
    assert res["params"]["reduced_search"] is True
    assert [e["i"] for e in ev] == [1, 2, 3] and "eta_s" in ev[0]
    assert (tmp_path / "screen" / "receptor.pdbqt").is_file()
    # second run: only the failed one is retried; the receptor is not re-converted (the file is reused)
    calls.clear()
    res2 = screen_dock(rec, ents, box, tmp_path / "screen", ScreenConfig(), dock_fn=dock_fn)
    assert calls == ["bad"] and res2["entries"]["c1"]["status"] == "OK"


def test_screen_dock_pause(tmp_path):
    rec = _receptor(tmp_path)
    ents = _entries(tmp_path, ["c1", "c2", "c3"])
    box = Box((0, 0, 0), (20, 20, 20), "test", "")
    n = {"c": 0}
    def stop():
        n["c"] += 1; return n["c"] > 2
    res = screen_dock(rec, ents, box, tmp_path / "screen", ScreenConfig(), dock_fn=fake_dock, should_stop=stop)
    assert res.get("paused") and set(res["entries"]) == {"c1", "c2"}
    res = screen_dock(rec, ents, box, tmp_path / "screen", ScreenConfig(), dock_fn=fake_dock)
    assert not res.get("paused") and set(res["entries"]) == {"c1", "c2", "c3"}


# ----------------------------------------------------------------------------- ranking / plots
def _results():
    return {"entries": {n: {"status": "OK", "score": s, "heavy_atoms": {"c1": 20, "c2": 30, "c3": 10, "c4": 25}[n], "cluster_size": 2,
                            "contacts": 20, "recommendation_status": "PASS" if n != "c3" else "NEEDS_HUMAN", "smiles": "CC", "sdf": "x.sdf"}
                        for n, s in SCORES.items()} | {"bad": {"status": "FAILED", "error": "Meeko"}}}


def test_rank_screen_flags_and_ligand_efficiency(tmp_path):
    rows = rank_screen(_results(), top_n=2)
    assert [r["name"] for r in rows] == ["c2", "c4", "c1", "c3"]
    assert rows[0]["rank"] == 1 and rows[0]["delta_to_best"] == 0 and rows[0]["indistinguishable_from_top"]
    assert rows[1]["indistinguishable_from_top"] and rows[2]["indistinguishable_from_top"]        # within 1 kcal/mol of the best
    assert not rows[3]["indistinguishable_from_top"] and not rows[3]["in_top_n"]
    assert rows[3]["ligand_efficiency"] == pytest.approx(0.51)                                      # 5.1 / 10 heavy atoms
    p = write_ranking_csv(rows, tmp_path / "r.csv")
    text = p.read_text(encoding="utf-8-sig")
    assert text.splitlines()[0].startswith("rank,name,score") and "c2" in text
    assert failed_rows(_results()) == [{"name": "bad", "stage": "docking", "status": "FAILED", "error": "Meeko"}]
    assert rank_screen({"entries": {}}) == []


def test_screen_plots_written(tmp_path):
    rows = rank_screen(_results())
    paths = screen_plots(rows, tmp_path / "plots", top_n=3)
    assert set(paths) == {"histogram", "scatter", "top"}
    for v in paths.values():
        assert (tmp_path / "plots" / v["png"].split("/")[-1].split("\\")[-1]).is_file()
    opt = echart_screen(rows)
    assert {s["name"] for s in opt["series"]} == {"PASS", "NEEDS_HUMAN"} and opt["yAxis"]["inverse"]
    assert echart_screen([])["series"] == []


# ----------------------------------------------------------------------------- workflow gates
def _wf(tmp_path, lib_rows, **screen):
    lib = tmp_path / "lib.csv"
    lib.write_text("name,sdf\n" + "".join(f"{n},{n}.sdf\n" for n in lib_rows), encoding="utf-8")
    for n in lib_rows:
        (tmp_path / f"{n}.sdf").write_text(SDF)
    cfg = copy.deepcopy(example_config(screen=True))
    cfg["receptor"] = {"file": str(_receptor(tmp_path))}
    cfg["screen"].update({"library": str(lib), **screen})
    cfg["ligands"] = [{"name": "BEN", "smiles": "NC(=[NH2+])c1ccccc1", "reference_resname": "BEN"}]
    return Workflow(Project.create(tmp_path, "p"), cfg)


def _run_screen(wf, monkeypatch):
    monkeypatch.setattr("md20.docking.run.dock", fake_dock)
    raw = wf.fetch_receptor()
    return wf.apply_screen(raw, raw)


def test_workflow_screen_blocks_on_selection_then_merges(tmp_path, monkeypatch):
    wf = _wf(tmp_path, ["c1", "c2", "c3"])
    with pytest.raises(WorkflowBlocked, match="勾選"):
        _run_screen(wf, monkeypatch)
    st = wf.state()["steps"]
    assert st["screen_library"]["status"] == "PASS" and st["screen_docking"]["status"] == "PASS"
    assert st["screen_selection"]["status"] == "NEEDS_HUMAN" and st["screen_selection"]["gates"][0]["evidence"]["top"] == ["c2", "c1", "c3"]
    assert (wf.dir / "screen" / "screen_ranking.csv").is_file() and (wf.dir / "screen" / "plots" / "screen_top.png").is_file()
    labels = [r["step"] for r in step_rows(wf.state())]
    assert "篩選：選擇化合物" in labels
    rows = screen_table(wf)
    assert [r["name"] for r in rows] == ["c2", "c1", "c3"] and rows[0]["tag"] == "≈"
    # GUI selection → config written, downstream invalidated, screen kept
    out = select_screen_ligands(wf, ["c2", "c1"], "simultaneous", note="兩個都在誤差內")
    assert out["invalidated"] == ["screen_selection"]
    cfg = load_json(wf.dir / "config.json")
    assert cfg["screen"]["select"] == ["c2", "c1"] and cfg["screen"]["next_mode"] == "simultaneous"
    assert wf.state()["steps"]["screen_docking"]["status"] == "PASS"
    assert _run_screen(wf, monkeypatch) is True
    names = [l["name"] for l in wf.cfg["ligands"]]
    assert names == ["BEN", "c2", "c1"]                                     # explicit co-crystal ligand kept first
    assert wf.cfg["docking"]["mode"] == "simultaneous"
    assert wf.cfg["ligands"][1]["sdf"].endswith("c2.sdf") and wf.cfg["ligands"][1]["from_screen"]
    assert wf.state()["steps"]["screen_selection"]["status"] == "PASS"
    assert any(r["stage"] == "screen.selection" and r["kind"] == "human" for r in wf.dec.read())
    # a bad name in select blocks instead of silently dropping it
    wf.cfg["screen"]["select"] = ["c2", "nope"]
    invalidate_from(wf, "screen_selection")
    with pytest.raises(WorkflowBlocked, match="nope"):
        _run_screen(wf, monkeypatch)


def test_workflow_partial_library_blocks_unless_allowed(tmp_path, monkeypatch):
    wf = _wf(tmp_path, ["c1", "c2"])
    (tmp_path / "c2.sdf").unlink()                                          # c2 cannot be resolved
    with pytest.raises(WorkflowBlocked, match="allow_partial"):
        _run_screen(wf, monkeypatch)
    gate = wf.state()["steps"]["screen_library"]["gates"][0]
    acts, manual = gate_actions(gate, step="screen_library")
    assert [a["patch"][0]["path"] for a in acts] == [["screen", "allow_partial"]] and manual
    assert acts[0]["from_step"] == "screen_library"
    wf.cfg["screen"]["allow_partial"] = True
    with pytest.raises(WorkflowBlocked, match="勾選"):
        _run_screen(wf, monkeypatch)
    assert wf.state()["steps"]["screen_library"]["summary"] == {"OK": 1, "FAILED": 1, "SKIPPED": 0, "total": 2}
    assert "c2" in wf.state()["steps"]["screen_docking"]["failed"]


def test_workflow_partial_docking_blocks_unless_allowed(tmp_path, monkeypatch):
    wf = _wf(tmp_path, ["c1", "bad"])
    with pytest.raises(WorkflowBlocked, match="對接失敗"):
        _run_screen(wf, monkeypatch)
    wf.cfg["screen"]["allow_partial"] = True
    with pytest.raises(WorkflowBlocked, match="勾選"):
        _run_screen(wf, monkeypatch)


def test_workflow_screen_requires_redock_reference_like_docking(tmp_path, monkeypatch):
    wf = _wf(tmp_path, ["c1"])
    wf.cfg["ligands"] = []                                                  # co-crystal box without a reference ligand
    with pytest.raises(WorkflowBlocked, match="redocking"):
        _run_screen(wf, monkeypatch)


def test_library_change_invalidates_screen(tmp_path, monkeypatch):
    wf = _wf(tmp_path, ["c1", "c2"], select=["c1"])
    assert _run_screen(wf, monkeypatch) is True
    k1 = wf.state()["steps"]["screen_library"]["key"]
    lib = tmp_path / "lib.csv"
    lib.write_text(lib.read_text() + "c3,c3.sdf\n"); (tmp_path / "c3.sdf").write_text(SDF)
    wf2 = Workflow(wf.project, wf.cfg)
    assert _run_screen(wf2, monkeypatch) is True
    assert wf2.state()["steps"]["screen_library"]["key"] != k1
    assert set(load_json(wf2.state()["steps"]["screen_docking"]["results"])["entries"]) == {"c1", "c2", "c3"}


def test_select_action_validation(tmp_path):
    wf = _wf(tmp_path, ["c1"])
    with pytest.raises(ValueError):
        select_screen_ligands(wf, [], "independent")
    with pytest.raises(ValueError):
        select_screen_ligands(wf, ["c1"], "simultaneous")
    with pytest.raises(ValueError):
        select_screen_ligands(wf, ["c1"], "weird")


def test_step_order_contains_screen_before_docking():
    assert STEP_ORDER.index("screen_selection") < STEP_ORDER.index("docking_preflight")
    assert "screen_library" in STEP_ORDER
