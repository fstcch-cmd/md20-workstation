"""D-104: live 3D snapshots while a membrane system is built."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))


def _system(n_protein_res=3, n_lipids=4, tails=10, n_water=20):
    atoms, xyz, lip, heads = [], [], [], []
    for r in range(n_protein_res):
        for nm, el in (("N", "N"), ("CA", "C"), ("C", "C"), ("H", "H")):
            atoms.append({"e": el, "n": nm, "r": "ALA", "s": str(r + 1), "c": "A"}); xyz.append([0.38 * r, 0, 3.0])
    for k in range(n_lipids):
        heads.append(len(atoms)); lip.append(len(atoms))
        atoms.append({"e": "P", "n": "P", "r": "POPC", "s": str(100 + k), "c": "M"}); xyz.append([k, 0, 1.9])
        for t in range(tails):
            lip.append(len(atoms))
            atoms.append({"e": "C", "n": f"C2{t}", "r": "POPC", "s": str(100 + k), "c": "M"}); xyz.append([k, 0, 1.9 - 0.1 * t])
    for w in range(n_water):
        atoms.append({"e": "O", "n": "O", "r": "HOH", "s": str(500 + w), "c": "W"}); xyz.append([w * 0.1, 1, 4])
    atoms.append({"e": "Na", "n": "NA", "r": "NA", "s": "900", "c": "I"}); xyz.append([2, 2, 4])
    return atoms, np.array(xyz, float), lip, heads


def test_scene_drops_water_and_hydrogens_marks_heads_tails_ions():
    from md20.build.live3d import membrane_scene
    atoms, xyz, lip, heads = _system()
    sc = membrane_scene(atoms, xyz, lipid_indices=lip, head_indices=heads, planes_nm=[-1.9, 1.9], box_nm=[4, 4, 8])
    kinds = [a["k"] for a in sc["atoms"]]
    assert "HOH" not in {a["r"] for a in sc["atoms"]} and "H" not in {a["e"] for a in sc["atoms"]}
    assert kinds.count("H") == 4 and kinds.count("A") == 40 and kinds.count("I") == 1
    assert kinds.count("P") == 9                      # small peptide: all heavy atoms
    assert sc["planes"] == [-19.0, 19.0] and sc["box"] == [40.0, 40.0, 80.0]   # Å
    assert len(sc["frames"][0]) == 3 * len(sc["atoms"])
    assert sc["summary"]["n_lipid_heads"] == 4 and sc["summary"]["n_tail_atoms"] == 40


def test_tails_are_thinned_to_fit_and_large_proteins_become_a_trace():
    from md20.build.live3d import membrane_scene
    atoms, xyz, lip, heads = _system(n_protein_res=80, n_lipids=50, tails=40)
    sc = membrane_scene(atoms, xyz, lipid_indices=lip, head_indices=heads, max_atoms=300)
    kinds = [a["k"] for a in sc["atoms"]]
    assert len(sc["atoms"]) <= 300
    assert kinds.count("H") == 50 and kinds.count("T") == 80 and "P" not in kinds    # heads always kept
    assert 0 < kinds.count("A") < 2000 and sc["summary"]["tail_stride"] > 1
    assert any(b for b in sc["bonds"])                                                # Cα trace bonds


def test_write_stage_index_and_latest(tmp_path):
    from md20.build.live3d import write_stage, read_index, latest_scene
    write_stage(tmp_path, "solute", {"stage": "solute", "frames": [[0, 0, 0]]})
    write_stage(tmp_path, "bilayer", {"stage": "bilayer", "frames": [[1, 1, 1]]})
    idx = read_index(tmp_path)
    assert [s["stage"] for s in idx["stages"]] == ["solute", "bilayer"]
    assert idx["stages"][0]["file"] == "01_solute.json" and idx["stages"][1]["file"] == "02_bilayer.json"
    sc, st = latest_scene(tmp_path)
    assert sc["stage"] == "bilayer" and st["label"][1].startswith("Bilayer")
    write_stage(tmp_path, "solute", {"stage": "solute2", "frames": [[2, 2, 2]]})      # a rebuild replaces the stage
    idx = read_index(tmp_path)
    assert [s["stage"] for s in idx["stages"]] == ["bilayer", "solute"]
    assert latest_scene(tmp_path)[0]["stage"] == "solute2"
    assert latest_scene(tmp_path / "nothing") == (None, None)


def test_atoms_from_topology_duck_types_openmm():
    from md20.build.live3d import atoms_from_topology
    chain = SimpleNamespace(id="A")
    res = SimpleNamespace(name="POPC", id="7", index=6, chain=chain)
    top = SimpleNamespace(atoms=lambda: [SimpleNamespace(name="P", element=SimpleNamespace(symbol="P"), residue=res),
                                         SimpleNamespace(name="EP", element=None, residue=res)])
    assert atoms_from_topology(top) == [{"e": "P", "n": "P", "r": "POPC", "s": "7", "c": "A"},
                                        {"e": "", "n": "EP", "r": "POPC", "s": "7", "c": "A"}]


def test_snapshot_never_breaks_a_build(tmp_path):
    from md20.build.live3d import snapshot_modeller
    snapshot_modeller(tmp_path, "solute", object())            # no OpenMM / not a modeller: silently nothing


def test_ranges_and_planes():
    from md20.build.live3d import ranges_to_indices
    from md20.build.membrane import index_ranges, target_planes_nm
    assert ranges_to_indices(index_ranges([3, 4, 5, 9])) == [3, 4, 5, 9]
    plan = SimpleNamespace(builder="grid", single_lipid=None, reference={"dpp_nm": 4.0})
    assert target_planes_nm(plan) == [-2.0, 2.0]


def test_live_target_in_viewer_and_caption(tmp_path):
    from md20.build.live3d import mark_current, write_stage, membrane_scene, STAGE_TEXT
    from md20.gui.views import viewer_targets, scene_for, viewer_html
    atoms, xyz, lip, heads = _system()
    wf_dir = tmp_path / "wf"; wf_dir.mkdir()
    wf = SimpleNamespace(dir=wf_dir, state=lambda: {"steps": {}}, project=None)
    assert viewer_targets(wf) == []
    mark_current(wf_dir, "bilayer", tmp_path / "case" / "build")
    assert viewer_targets(wf) == []                               # marked but nothing written yet
    write_stage(tmp_path / "case" / "build", "bilayer",
                membrane_scene(atoms, xyz, lipid_indices=lip, head_indices=heads, stage="bilayer",
                               lang_labels=STAGE_TEXT["bilayer"]))
    tg = viewer_targets(wf, lang="en")
    assert len(tg) == 1 and tg[0]["mode"] == "live" and tg[0]["stamp"] and "Membrane build (live)" in tg[0]["label"]
    sc = scene_for(tg[0])
    html = viewer_html(sc, lang="zh")
    assert "脂質頭基" in html and "已加入脂雙層" in html and "口袋" not in html


def test_demo_scene_used_by_the_browser_check_builds():
    import gui_preview
    sc = gui_preview._demo_membrane_scene("bilayer")
    assert sc["planes"] and sc["box"] and sum(a["k"] == "H" for a in sc["atoms"]) == 128
    assert json.dumps(sc)
