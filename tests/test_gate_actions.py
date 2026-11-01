"""One-click gate decisions (GUI 閘門卡片): option → config patch → write-back → downstream invalidation.

Pure python (no OpenMM / NiceGUI).  The guarantee under test: only options the program really executes become
buttons; everything else stays a "handle outside the program" hint and the gate keeps blocking."""
import copy

import pytest

from md20.build.receptor import prepare_receptor, receptor_choice_action
from md20.gui.actions import apply_gate_action, apply_patch, gate_actions, invalidate_from
from md20.gui.views import gate_cards
from md20.project.store import Project
from md20.util import load_json
from md20.workflow import Workflow, WorkflowBlocked, example_config
from test_build_gates import _protein
from test_workflow_gates import PDB


def _wf(tmp_path, **over):
    cfg = copy.deepcopy(example_config())
    cfg.update(over)
    return Workflow(Project.create(tmp_path, "p"), cfg)


def _raw(tmp_path):
    p = tmp_path / "raw.pdb"; p.write_text(PDB); return p


# ------------------------------------------------------------------------------------------ mapping
def test_receptor_choices_only_implemented_ones():
    assert receptor_choice_action("hetero groups", "全部移除（預設）") == "remove"
    assert receptor_choice_action("hetero groups", "保留為參考配體（僅用於 box 定義）") == "remove"   # not kept in the MD receptor
    assert receptor_choice_action("hetero groups", "保留並參數化") == "keep"
    assert receptor_choice_action("missing loops (long)", "以 PDBFixer 補建並接受風險") is None
    assert receptor_choice_action("missing loops (long)", "截斷（加 ACE/NME 端帽）") is None
    assert receptor_choice_action("unknown residues", "移除並記錄") is None


def test_gate_actions_split_clickable_and_manual():
    loop = {"name": "missing loops (long)", "status": "NEEDS_HUMAN",
            "options": ["截斷（加 ACE/NME 端帽）", "以 PDBFixer 補建並接受風險", "改用 AlphaFold 模型"]}
    acts, manual = gate_actions(loop, step="receptor_docking")
    assert acts == [] and len(manual) == 3                       # nothing here is executed by the program
    het = {"name": "hetero groups", "status": "NEEDS_HUMAN",
           "options": ["全部移除（預設）", "保留並參數化", "保留為參考配體（僅用於 box 定義）"]}
    acts, manual = gate_actions(het, step="receptor_docking")
    assert len(acts) == 3 and manual == []
    assert acts[0]["patch"] == [{"path": ["human_choices", "receptor", "hetero groups"], "value": "全部移除（預設）"}]
    res = {"name": "resolution", "status": "NEEDS_HUMAN", "options": ["換一個更高解析度的結構", "仍要使用（structure_override.resolution）"]}
    acts, manual = gate_actions(res, step="structure_gate")
    assert manual == ["換一個更高解析度的結構"] and acts[0]["needs_text"]
    metal = {"name": "metal", "status": "NEEDS_HUMAN", "options": [
        "metal_policy: {ZN: bonded}（晶體幾何鍵結模型＋配位殘基質子化，報告標註）",
        "metal_policy: {ZN: keep_nonbonded}（保留並加位置限制，報告標註）", "metal_policy: {ZN: remove}（若金屬非功能必要）", "換一個系統"]}
    acts, manual = gate_actions(metal, step="structure_gate")
    assert [a["patch"][0]["value"] for a in acts] == ["bonded", "keep_nonbonded", "remove"] and manual == ["換一個系統"]
    site = {"name": "metal ZN:A262", "status": "NEEDS_HUMAN",
            "options": ["改用 keep_nonbonded（報告標註）", "以 MCPB.py/QM 參數化後匯入", "remove（若非必要）"]}
    acts, manual = gate_actions(site, step="md_cases")
    assert [a["patch"][0]["path"] for a in acts] == [["metal_policy", "ZN:A262"]] * 2
    assert manual == ["以 MCPB.py/QM 參數化後匯入"] and all(a["from_step"] == "md_cases" for a in acts)
    assert gate_actions({**site, "status": "AUTO_FIXED"}, step="md_cases") == ([], [])


def test_cpp_actions_target_ligand_entry():
    g = {"name": "CPP", "status": "NEEDS_HUMAN", "options": ["胞內 intracellular", "膜外側 extracellular-membrane", "分泌／胞外 secreted"]}
    acts, _ = gate_actions(g, step="docking_preflight", ligand="PEP")
    cfg = {"ligands": [{"name": "BEN"}, {"name": "PEP", "sequence": "GGGGGKP"}]}
    out = apply_patch(cfg, acts[0]["patch"])
    assert out["ligands"][1]["target_location"] == "intracellular" and "target_location" not in out["ligands"][0]
    assert "target_location" not in cfg["ligands"][1]             # input not mutated
    g2 = {"name": "CPP", "status": "NEEDS_HUMAN", "options": ["提供實驗證據（文獻或自有數據）", "改設計：縮短為帶電核心（如 GKP、KP）或富集 Arg/Lys",
                                                             "仍要繼續（報告標註為未驗證穿膜性）"]}
    acts, manual = gate_actions(g2, step="docking_preflight", ligand="PEP")
    assert [a["needs_text"] for a in acts] == [True, True] and manual[0].startswith("改設計")
    out = apply_patch(cfg, acts[1]["patch"], "教學示範")
    assert out["ligands"][1]["cpp_override"] == "教學示範"


# ------------------------------------------------------------------------------------ write-back
def test_apply_writes_config_logs_human_and_invalidates(tmp_path):
    wf = _wf(tmp_path)
    for k in ("receptor_input", "receptor_docking", "docking", "pose_selection", "md_cases"):
        wf._mark(k, x=1)
    act = gate_actions({"name": "resolution", "status": "NEEDS_HUMAN", "options": ["仍要使用（structure_override.resolution）"]},
                       step="structure_gate")[0][0]
    with pytest.raises(ValueError, match="需要填寫"):
        apply_gate_action(wf, act, "  ")
    out = apply_gate_action(wf, act, "口袋區域電子密度清楚")
    assert load_json(wf.dir / "config.json")["structure_override"]["resolution"] == "口袋區域電子密度清楚"
    assert wf.cfg["structure_override"]["resolution"] == "口袋區域電子密度清楚"
    assert set(out["invalidated"]) == {"receptor_docking", "docking", "pose_selection", "md_cases"}
    assert set(wf.state()["steps"]) == {"receptor_input"}        # the raw structure is never discarded
    d = [x for x in wf.dec.read() if x.get("stage") == "gui.gate"][-1]
    assert d["kind"] == "human" and "口袋區域電子密度清楚" in d["why"]


def test_md_cases_decision_keeps_docking(tmp_path):
    wf = _wf(tmp_path)
    for k in ("receptor_docking", "docking", "pose_selection", "md_cases", "md_runs"):
        wf._mark(k, x=1)
    assert invalidate_from(wf, "md_cases") == ["md_cases", "md_runs"]
    assert {"receptor_docking", "docking", "pose_selection"} <= set(wf.state()["steps"])


# --------------------------------------------------------------------------------- end to end
def test_blind_docking_card_resolves_the_block(tmp_path):
    wf = _wf(tmp_path, box={})
    with pytest.raises(WorkflowBlocked):
        wf.docking_preflight(_raw(tmp_path))
    card = next(c for c in gate_cards(wf) if c["title"] == "blind docking")
    labels = [a["label"] for a in card["actions"]]
    assert labels == ["box.from_residue: BEN", "box.allow_blind: true（盲對接，報告標註）"]
    apply_gate_action(wf, card["actions"][0])
    assert wf.cfg["box"] == {"from_residue": "BEN"}
    wf.docking_preflight(_raw(tmp_path))                          # BEN is the redock reference in example_config
    assert not any(c["status"] == "NEEDS_HUMAN" for c in gate_cards(wf))


def test_redock_card_skip(tmp_path):
    wf = _wf(tmp_path, ligands=[{"name": "X1", "smiles": "c1ccccc1O"}])
    with pytest.raises(WorkflowBlocked):
        wf.docking_preflight(_raw(tmp_path))
    card = next(c for c in gate_cards(wf) if c["title"] == "redocking")
    assert len(card["actions"]) == 1 and len(card["manual"]) == 1   # adding a reference ligand needs its SMILES
    apply_gate_action(wf, card["actions"][0])
    wf.docking_preflight(_raw(tmp_path))
    assert any(d.get("choice") == "skipped" for d in wf.dec.read())


def test_cpp_block_card_from_workflow(tmp_path):
    wf = _wf(tmp_path, ligands=[{"name": "PEP", "sequence": "GGGGGKP"}])
    with pytest.raises(WorkflowBlocked):
        wf._peptide_preflight(wf.cfg["ligands"][0])
    card = next(c for c in gate_cards(wf) if c["title"] == "CPP")
    act = next(a for a in card["actions"] if a["label"].startswith("胞內"))
    apply_gate_action(wf, act)
    assert wf.cfg["ligands"][0]["target_location"] == "intracellular"
    with pytest.raises(WorkflowBlocked):                          # +1 net charge: still predicted not to enter cells
        wf._peptide_preflight(wf.cfg["ligands"][0])
    card = next(c for c in gate_cards(wf) if c["title"] == "CPP")
    assert any(m.startswith("改設計") for m in card["manual"])
    go = next(a for a in card["actions"] if a["label"].startswith("仍要繼續"))
    apply_gate_action(wf, go, "課堂示範：觀察閘門行為")
    pytest.importorskip("rdkit")
    wf._peptide_preflight(wf.cfg["ligands"][0])


def test_receptor_unimplemented_choice_keeps_blocking(tmp_path):
    lines, _ = _protein(6, gap_after=2, gap_len=12)
    src = tmp_path / "loop.pdb"; src.write_text("\n".join(lines) + "\nEND\n")
    man = prepare_receptor(src, tmp_path / "out", keep_hetero=set(),
                           human_choices={"missing loops (long)": "以 PDBFixer 補建並接受風險"})
    g = {x["name"]: x for x in man["gates"]["gates"]}["missing loops (long)"]
    assert man["status"] == "NEEDS_HUMAN" and g["status"] == "NEEDS_HUMAN" and "不會由程式自動執行" in g["explanation"]
