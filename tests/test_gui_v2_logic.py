"""D-51: GUI v2 logic without NiceGUI — ligand lines, mode → config, teaching configs, bilingual content."""
import pytest

from md20.gui.logic import parse_ligand_lines, config_from_mode
from md20.gui.content import UI, MODES, TEACHING, t, teaching_config
from md20 import advisor


def test_ligand_lines_small_and_peptide():
    ls = parse_ligand_lines("ben NC(=[NH2+])c1ccccc1 BEN\nGRP peptide:gggggkp intracellular\n# comment")
    assert ls[0] == {"name": "BEN", "smiles": "NC(=[NH2+])c1ccccc1", "reference_resname": "BEN"}
    assert ls[1]["sequence"] == "GGGGGKP" and ls[1]["target_location"] == "intracellular"
    with pytest.raises(ValueError):
        parse_ligand_lines("AAA1 C\nAAA2 CC")            # same three-character name
    with pytest.raises(ValueError):
        parse_ligand_lines("P peptide:GXZ")


def test_config_from_mode_applies_values_and_asks_before_md():
    f = advisor.CaseFeatures()
    vals = advisor.recommended_values(f, "binding")
    vals["temperature_k"] = 310.0
    cfg = config_from_mode(mode="pro", name="my run", values=vals, pdb_id="3ptb", ligands_text="BEN NC(=[NH2+])c1ccccc1 BEN",
                           box_residue="ben", goal="binding", lang="zh")
    assert cfg["receptor"] == {"pdb_id": "3PTB"} and cfg["box"] == {"from_residue": "BEN"}
    assert cfg["confirm_before_md"] and cfg["language"] == "zh" and cfg["gui_mode"] == "pro"
    assert cfg["binding"]["enabled"] and cfg["binding"]["ligands"] == ["BEN"]
    assert cfg["md"]["stage_overrides"]["production"]["temperature_k"] == 310.0
    assert "screen" not in cfg
    cfg = config_from_mode(mode="quick", name="x", values={"docking_mode": "simultaneous"}, pdb_id="1ABC",
                           ligands_text="L1 CCO", library_file="compound_library.xlsx")
    assert cfg["docking"]["mode"] == "independent"          # one ligand cannot be docked "simultaneously"
    assert cfg["screen"]["library"] == "compound_library.xlsx" and cfg["box"] == {}
    with pytest.raises(ValueError):
        config_from_mode(mode="quick", name="x", values={}, ligands_text="L1 CCO")    # no receptor


def test_teaching_cases_and_content_are_bilingual():
    for key, (zh, en) in UI.items():
        assert zh and en, key
        assert " / " not in zh and " / " not in en, key        # user rule: no slash separators
    for m in MODES.values():
        assert all(m["title"]) and all(m["text"])
    for case, c in TEACHING.items():
        for part in ("title", "background"):
            assert all(c[part])
        for part in ("objectives", "checks", "discussion"):
            assert c[part] and all(zh and en for zh, en in c[part])
        cfg = teaching_config(case)
        assert cfg["confirm_before_md"] and cfg["md"]["tier"] == "classroom"
        assert cfg["validation"]["case"] == case
    c24, c25 = teaching_config("hsieh2024"), teaching_config("hsieh2025")
    assert c24["docking"]["mode"] == "simultaneous" and len(c24["ligands"]) == 6 and c24["md"]["padding_nm"] == 1.0
    assert c25["ligands"][0]["sequence"] == "GGGGGKP" and c25["md"]["restraints"] == "gentle"
    assert t("estimate_text", "en", total=1, md=1, bind=0, atoms=2, speed=3).startswith("About 1 h")
