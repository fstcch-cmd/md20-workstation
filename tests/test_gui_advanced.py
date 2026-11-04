"""Professional-mode membrane, folding and long-run settings; computer-status tools; one-click actions for the D-80
gates; predicted-complex score text (pure, no NiceGUI)."""
import copy

import pytest

from md20 import advisor
from md20.gui import advanced as A
from md20.gui.actions import gate_actions, apply_patch, STEP_ORDER, invalidate_from
from md20.gui.logic import config_from_mode
from md20.i18n import LANGS
from md20.workflow import example_config

PEP = "PEP peptide:KLAKLAKKLAKLAK"


def _cfg_from(adv, *, ligands=PEP, pdb="3PTB", quick_fold=None, binding=False):
    f = advisor.features_from_config({})
    vals = {**advisor.recommended_values(f, "teaching"), "binding": binding}
    return config_from_mode(mode="pro", name="m", values=vals, pdb_id=pdb, ligands_text=ligands, advanced=adv,
                            quick_fold=quick_fold)


def test_no_membrane_keeps_the_config_as_before():
    cfg = _cfg_from(A.defaults())
    assert "membrane" not in cfg["md"] and cfg["receptor"] == {"pdb_id": "3PTB"}
    assert all("fold" not in l for l in cfg["ligands"]) and "long_run_confirmed" not in cfg["md"]


def test_surface_system_without_receptor():
    cfg = _cfg_from({**A.defaults(), "membrane_type": "surface", "lipids": "bacterial", "surface_distance_nm": 1.5},
                    pdb="", binding=True)
    assert cfg["md"]["membrane"] == {"type": "surface", "lipids": "bacterial", "surface_distance_nm": 1.5}
    assert cfg["receptor"] == {} and cfg["box"] == {} and cfg["binding"]["enabled"] is False


def test_bilayer_drops_ligands_and_single_lipid_becomes_a_ratio():
    cfg = _cfg_from({**A.defaults(), "membrane_type": "bilayer", "lipids": "POPE"}, pdb="")
    assert cfg["md"]["membrane"] == {"type": "bilayer", "lipids": {"POPE": 1.0}} and cfg["ligands"] == []


def test_membrane_protein_still_needs_a_receptor():
    with pytest.raises(ValueError):
        _cfg_from({**A.defaults(), "membrane_type": "protein"}, pdb="")
    cfg = _cfg_from({**A.defaults(), "membrane_type": "protein", "oriented": True})
    assert cfg["md"]["membrane"] == {"type": "protein", "lipids": "mammalian", "oriented": True}


@pytest.mark.parametrize("mode,expect", [("dock", True), ("complex", "complex")])
def test_fold_modes_write_ligand_keys(mode, expect):
    cfg = _cfg_from({**A.defaults(), "fold": mode, "fold_engine": "boltz", "fold_receptor_seq": "IVGG YTCG\n:AAAK"},
                    ligands=PEP + "\nLIG CCO")
    pep, lig = cfg["ligands"]
    assert pep["fold"] == expect and pep["fold_engine"] == "boltz" and "fold" not in lig
    assert pep.get("fold_receptor_seq") == (["IVGGYTCG", "AAAK"] if mode == "complex" else None)


def test_upload_engine_passes_the_file_and_quick_fold_only_ticked():
    cfg = _cfg_from({**A.defaults(), "fold": "dock", "fold_engine": "upload", "fold_upload": "/tmp/x.pdb"})
    assert cfg["ligands"][0]["fold_upload"] == "/tmp/x.pdb" and cfg["ligands"][0]["fold_engine"] == "upload"
    cfg = _cfg_from(A.defaults(), ligands=PEP + "\nPEB peptide:GGGGGKPGGGGG", quick_fold={"PEB"})
    assert "fold" not in cfg["ligands"][0] and cfg["ligands"][1]["fold"] is True


def test_long_run_confirmation_sets_the_decision_key():
    cfg = _cfg_from({**A.defaults(), "long_run_confirmed": True})
    assert cfg["md"]["long_run_confirmed"] is True


def _codes(issues):
    return {(i["level"], i["key"]) for i in issues}


def test_checks_block_impossible_membrane_settings():
    lig = [{"name": "PEP", "sequence": "KLAKLAK"}]
    iss = A.advanced_checks({**A.defaults(), "membrane_type": "surface"}, ligands=[], has_receptor=False, binding=False)
    assert ("error", "membrane_type") in _codes(iss)
    iss = A.advanced_checks({**A.defaults(), "membrane_type": "protein"}, ligands=lig, has_receptor=False, binding=False)
    assert ("error", "membrane_type") in _codes(iss)
    iss = A.advanced_checks({**A.defaults(), "membrane_type": "surface"}, ligands=lig, has_receptor=False, binding=True)
    b = next(i for i in iss if i["key"] == "binding")
    assert b["level"] == "error" and b["suggestion"] is False
    iss = A.advanced_checks({**A.defaults(), "membrane_type": "bilayer", "lipids": "gram_positive"}, ligands=[],
                            has_receptor=False, binding=False, lang="en")
    assert any(i["level"] == "error" and "force field" in i["label"].lower() for i in iss)
    iss = A.advanced_checks({**A.defaults(), "membrane_type": "bilayer", "lipids": "DPPC"}, ligands=[], has_receptor=False,
                            binding=False)
    assert any(i["level"] == "error" for i in iss)
    ok = A.advanced_checks({**A.defaults(), "membrane_type": "surface"}, ligands=lig, has_receptor=False, binding=False)
    assert not [i for i in ok if i["level"] == "error"]
    iss = A.advanced_checks({**A.defaults(), "membrane_type": "surface", "surface_distance_nm": 0.1}, ligands=lig,
                            has_receptor=False, binding=False)
    assert any(i["level"] == "error" for i in iss)


def test_checks_for_folding_and_long_runs():
    lig = [{"name": "PEP", "sequence": "KLAKLAKKLAKLAK"}]
    d = A.defaults()
    assert ("error", "fold") in _codes(A.advanced_checks({**d, "fold": "complex"}, ligands=lig, has_receptor=False, binding=False))
    assert ("error", "fold") in _codes(A.advanced_checks({**d, "fold": "dock", "fold_engine": "upload"}, ligands=lig,
                                                         has_receptor=True, binding=False))
    assert ("error", "fold") in _codes(A.advanced_checks({**d, "fold": "complex", "fold_receptor_seq": "IVGGXZ1"},
                                                         ligands=lig, has_receptor=True, binding=False))
    assert ("warning", "fold") in _codes(A.advanced_checks({**d, "fold": "dock"}, ligands=[], has_receptor=True, binding=False))
    none = {"omegafold": False, "boltz": False, "esmfold": False, "colabfold": False}
    w = A.advanced_checks({**d, "fold": "dock"}, ligands=lig, has_receptor=True, binding=False, fold_installed=none)
    assert ("warning", "fold") in _codes(w)
    ok = A.advanced_checks({**d, "fold": "dock"}, ligands=lig, has_receptor=True, binding=False,
                           fold_installed={**none, "omegafold": True})
    assert not ok
    assert ("warning", "long_run") in _codes(A.advanced_checks(d, ligands=lig, has_receptor=True, binding=False,
                                                               production_ns=2000))
    assert not A.advanced_checks({**d, "long_run_confirmed": True}, ligands=lig, has_receptor=True, binding=False,
                                 production_ns=2000)


@pytest.mark.parametrize("lang", LANGS)
def test_every_issue_has_text_in_each_language(lang):
    lig = [{"name": "PEP", "sequence": "KLAKLAK"}]
    iss = A.advanced_checks({**A.defaults(), "membrane_type": "surface", "lipids": "gram_positive", "fold": "complex",
                             "fold_engine": "upload"}, ligands=lig, has_receptor=True, binding=True, production_ns=5000,
                            fold_installed={"omegafold": False}, lang=lang)
    assert len(iss) >= 5 and all(i["label"] and i["message"] for i in iss)
    if lang != "zh":
        assert not any("一" <= ch <= "鿿" for i in iss for ch in i["message"]) or lang == "ja"


def test_long_run_view():
    f = advisor.features_from_config({})
    f.ns_per_day, f.bench_atoms, f.bench_dt_fs = 300.0, 24000, 4.0
    assert A.long_run_view({"production_ns": 50}, f, "teaching", "en")["show"] is False
    v = A.long_run_view({"production_ns": 500}, f, "teaching", "en")
    assert v["show"] and not v["needs_confirm"]
    for lang in LANGS:
        v = A.long_run_view({"production_ns": 2000}, f, "teaching", lang)
        assert v["needs_confirm"] and len(v["lines"]) >= 3 and all(v["lines"])
    assert "days" in A.long_run_view({"production_ns": 2000}, f, "teaching", "en")["lines"][0]


def test_tool_rows_and_preview_never_install():
    fs = {"gpu_vram_mb": 8188, "fold_env": "/x/envs/md20-fold", "engines": {"omegafold": False, "boltz": True}}
    cg = {"vermouth": {"ok": False}, "insane": {"ok": False}, "martini_openmm": {"ok": False}}
    rows = A.tool_rows(fs, cg, "en", platform="win32")
    assert rows[0]["installed"] and rows[1]["installed"] is False
    assert rows[0]["command"] == r"%LOCALAPPDATA%\MD20\md20.cmd setup-fold --engine omegafold --yes"
    assert rows[1]["command"].endswith("setup-cg --yes") and "8.2 GB" in rows[0]["detail"]
    assert A.md20_command("darwin") == "~/MD20/md20"
    plan = {"ok": True, "steps": [{"cmd": ["mm", "create", "-p", "/x"]}, {"cmd": ["py", "-m", "pip", "install", "torch"]}]}
    lines = A.setup_preview("fold", "ko", fold_plan=plan)
    assert lines[1] == "1. mm create -p /x" and lines[2].startswith("2. py -m pip install torch")
    assert "problem" not in A.setup_preview("fold", "en", fold_plan={"ok": False, "problem": "no micromamba"})[0]
    assert len(A.setup_preview("cg", "ja", cg_plan=[["py", "-m", "pip", "install", "vermouth"]])) == 2


def test_real_setup_plans_build_without_running(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "call", lambda *a, **k: pytest.fail("the preview must not run anything"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("the preview must not run anything"))
    for kind in ("fold", "cg"):
        assert A.setup_preview(kind, "en")


@pytest.mark.parametrize("lang,word", [("en", "Predicted complex, no docking score"), ("zh", "預測複合物，沒有對接分數"),
                                       ("ja", "予測複合体"), ("ko", "예측 복합체")])
def test_predicted_complex_has_no_score(lang, word):
    assert A.score_text(None, lang).startswith(word) and A.score_text(-6.114, lang) == "-6.11"
    lines = A.selection_lines({"ligands": {"PEP": {"rank": 1, "score": None}, "BEN": {"rank": 2, "score": -6.1}}}, lang)
    assert word in lines[0] and "None" not in lines[0] and "-6.10" in lines[1]


def test_pose_table_lists_the_complex_peptide(tmp_path):
    from md20.project.store import Project
    from md20.util.jsonio import atomic_write_json
    from md20.workflow import Workflow
    from md20.gui.logic import pose_table
    cfg = copy.deepcopy(example_config())
    wf = Workflow(Project.create(tmp_path, "p"), cfg)
    atomic_write_json({"entries": []}, tmp_path / "dock.json")
    wf._mark("docking", result=str(tmp_path / "dock.json"))
    wf._mark("pose_selection", selection={"ligands": {"PEP": {"rank": 1, "score": None, "source": "fold_complex"}}})
    rows = pose_table(wf, "en")
    assert rows == [{"entry": "PEP", "rank": 1, "score": "Predicted complex, no docking score", "cluster": "", "contacts": "",
                     "rmsd_ref": None, "clash": False, "recommended": True, "chosen": True, "reason": "", "md_screen": ""}]


# ------------------------------------------------------------------------------- one-click gate actions (D-80)
def _patches(gate, step, ligand=None):
    acts, manual = gate_actions(gate, step=step, ligand=ligand)
    return {a["label"]: (a["patch"], a["from_step"], a["needs_text"]) for a in acts}, manual


def test_fold_confidence_actions():
    from md20.build import fold as F
    g = {"name": "fold confidence", "status": "NEEDS_HUMAN",
         "options": [F.OPT_NO_FOLD, F.OPT_OTHER_ENGINE, F.OPT_UPLOAD, F.OPT_ACCEPT_LOW]}
    acts, manual = _patches(g, "fold", "PEP")
    assert acts[F.OPT_NO_FOLD] == ([{"path": ["ligand:PEP", "fold"], "value": False}], "fold", False)
    assert acts[F.OPT_ACCEPT_LOW][0][0]["path"] == ["ligand:PEP", "fold_accept_low"]
    assert acts[F.OPT_OTHER_ENGINE][2] is True
    assert manual == [F.OPT_UPLOAD]
    assert _patches(g, "fold", None)[0] == {}                     # no ligand: nothing to write to


def test_fold_placement_and_tool_actions():
    from md20.build import fold as F
    g = {"name": "fold placement", "status": "NEEDS_HUMAN", "options": [F.OPT_ACCEPT_RMSD, F.OPT_DOCK, F.OPT_UPLOAD, F.OPT_RECEPTOR_SEQ]}
    acts, manual = _patches(g, "fold", "PEP")
    assert acts[F.OPT_ACCEPT_RMSD][0] == [{"path": ["ligand:PEP", "fold_accept_rmsd"], "value": True}]
    assert acts[F.OPT_DOCK][0] == [{"path": ["ligand:PEP", "fold"], "value": True}]
    assert acts[F.OPT_RECEPTOR_SEQ][2] is True and manual == [F.OPT_UPLOAD]
    g2 = {"name": "fold", "status": "NEEDS_HUMAN", "options": [F.OPT_INSTALL, F.OPT_UPLOAD, F.OPT_NO_FOLD, "fold_engine: boltz"]}
    acts, manual = _patches(g2, "fold", "PEP")
    assert set(acts) == {F.OPT_NO_FOLD, "fold_engine: boltz"} and manual == [F.OPT_INSTALL, F.OPT_UPLOAD]
    cfg = {"ligands": [{"name": "PEP", "sequence": "KLAK", "fold": True}]}
    out = apply_patch(cfg, acts["fold_engine: boltz"][0])
    assert out["ligands"][0]["fold_engine"] == "boltz"


def test_membrane_gate_actions():
    g = {"name": "membrane orientation", "status": "NEEDS_HUMAN",
         "options": ["md.membrane.oriented: true（結構已依 OPM 定向）", "下載 OPM 定向結構後重新上傳", "md.membrane.type: surface"]}
    acts, manual = _patches(g, "md_cases")
    assert list(acts.values())[0] == ([{"path": ["md", "membrane", "oriented"], "value": True}], "md_cases", False)
    assert len(manual) == 2
    g = {"name": "membrane phase", "status": "NEEDS_HUMAN", "options": ["md.membrane.temperature_k: 324", "md.membrane.lipids: mammalian"]}
    acts, _ = _patches(g, "md_cases")
    assert [p[0][0]["value"] for p in acts.values()] == [324.0, "mammalian"]
    g = {"name": "membrane force field", "status": "NEEDS_HUMAN",
         "options": ["md.membrane.lipids: bacterial", "md.membrane.lipids: {POPG: 1.0}", "使用 CHARMM-GUI 建好的系統（尚未支援匯入）"]}
    acts, manual = _patches(g, "md_cases")
    assert [p[0][0]["value"] for p in acts.values()] == ["bacterial", {"POPG": 1.0}] and len(manual) == 1
    g = {"name": "membrane composition", "status": "NEEDS_HUMAN", "options": ["md.membrane.lipids: gram_positive"]}
    assert _patches(g, "md_cases")[0] == {}
    g = {"name": "membrane binding", "status": "NEEDS_HUMAN", "options": ["binding.enabled: false（只做 MD）"]}
    acts, _ = _patches(g, "binding")
    assert list(acts.values())[0][0] == [{"path": ["binding", "enabled"], "value": False},
                                         {"path": ["binding", "added"], "value": []},
                                         {"path": ["binding", "alone"], "value": {}}]
    g = {"name": "membrane surface placement", "status": "NEEDS_HUMAN",
         "options": ["md.membrane.surface_distance_nm: 1.0", "md.membrane.surface_orientation: parallel"]}
    acts, _ = _patches(g, "md_cases")
    assert [p[0][0]["value"] for p in acts.values()] == [1.0, "parallel"]
    out = apply_patch({"md": {}}, [{"path": ["md", "membrane", "oriented"], "value": True}])
    assert out["md"]["membrane"]["oriented"] is True


def test_fold_step_is_invalidated_with_docking(tmp_path):
    from md20.project.store import Project
    from md20.workflow import Workflow
    assert STEP_ORDER.index("docking_preflight") < STEP_ORDER.index("fold") < STEP_ORDER.index("docking")
    wf = Workflow(Project.create(tmp_path, "p"), copy.deepcopy(example_config()))
    for k in ("receptor_docking", "fold", "docking", "md_cases"):
        wf._mark(k)
    assert invalidate_from(wf, "fold") == ["fold", "docking", "md_cases"]
    assert "receptor_docking" in wf.state()["steps"]


def test_text_hints_of_new_actions_are_translated():
    from md20.gui.gate_text import option_text
    from md20.build import fold as F
    acts, _ = gate_actions({"name": "fold placement", "status": "NEEDS_HUMAN", "options": [F.OPT_RECEPTOR_SEQ, F.OPT_OTHER_ENGINE]},
                           step="fold", ligand="PEP")
    for a in acts:
        for lang in ("en", "ja", "ko"):
            assert option_text(a["text_hint"], lang) != a["text_hint"]
