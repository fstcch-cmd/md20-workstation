"""D-85: a peptide sequence typed in the ligand box is recognised without `peptide:` and folded by default."""
import sys

import pytest

from md20.build.peptide import classify_ligand_text, AmbiguousLigand
from md20.gui.logic import parse_ligand_lines
from md20.gui import advanced as A

MEL = "GIGAVLKVLTTGLPALISWIKRKRQQ"


@pytest.mark.parametrize("text,kind,value", [
    (MEL, "peptide", MEL),
    (MEL.lower(), "peptide", MEL),
    ("peptide:GGGGGKP", "peptide", "GGGGGKP"),
    ("smiles:CCCCCC", "smiles", "CCCCCC"),
    ("NC(=[NH2+])c1ccccc1", "smiles", "NC(=[NH2+])c1ccccc1"),
    ("CC(=O)Nc1ccc(O)cc1", "smiles", "CC(=O)Nc1ccc(O)cc1"),
    ("CCO", "smiles", "CCO"),            # O is not an amino-acid letter
    ("CCN", "smiles", "CCN"),            # short all-C/N string: SMILES
    ("ClCCl", "smiles", "ClCCl"),        # lowercase l: not a sequence
    ("CBr", "smiles", "CBr"),
])
def test_classify(text, kind, value):
    assert classify_ligand_text(text) == (kind, value)


def test_ambiguous_long_cn_string_asks():
    with pytest.raises(AmbiguousLigand):
        classify_ligand_text("CCCCCN")
    with pytest.raises(ValueError, match="smiles:"):
        parse_ligand_lines("X CCCCCN", "en")


def test_lines_bare_sequence_and_auto_names():
    ls = parse_ligand_lines(f"MEL {MEL}\n{MEL}\nGGGGGKPLLL\nBEN NC(=[NH2+])c1ccccc1 BEN\nsmiles:CCO", "zh")
    assert [l["name"] for l in ls] == ["MEL", "PEP", "PP2", "BEN", "LIG"]
    assert ls[0]["sequence"] == MEL and ls[1]["sequence"] == MEL and "smiles" not in ls[0]
    assert ls[3] == {"name": "BEN", "smiles": "NC(=[NH2+])c1ccccc1", "reference_resname": "BEN"}
    assert ls[4]["smiles"] == "CCO"


def test_single_word_smiles_still_needs_a_name():
    with pytest.raises(ValueError, match="NAME"):
        parse_ligand_lines("CC(=O)Nc1ccc(O)cc1", "en")


def test_default_fold_only_long_peptides():
    ls = parse_ligand_lines(f"MEL {MEL}\nGRP GGGGGKP\nBEN NC(=[NH2+])c1ccccc1", "en")
    assert A.default_fold_names(ls) == ["MEL"]          # 7 residues < MIN_FOLD_RESIDUES: not folded


def test_install_argv_and_background_start(tmp_path):
    assert A.install_argv("fold", "py") == ["py", "-m", "md20", "setup-fold", "--engine", "omegafold", "--yes", "--warmup"]
    assert A.install_argv("cg", "py")[-2:] == ["setup-cg", "--yes"]
    calls = []

    class P:
        def __init__(self, argv, **kw):
            calls.append(argv); kw["stdout"].write("step 1\nstep 2\n"); kw["stdout"].flush(); self.rc = None
        def poll(self):
            return self.rc
    A.INSTALLS.clear()
    cur = A.start_install("fold", tmp_path, popen=P)
    assert A.start_install("fold", tmp_path, popen=P) is cur and len(calls) == 1      # no second copy while running
    text, rc = A.install_progress("fold")
    assert "step 2" in text and rc is None
    cur["proc"].rc = 0
    assert A.install_progress("fold")[1] == 0
    A.INSTALLS.clear()


def test_setup_fold_has_warmup_flag():
    from md20 import cli
    src = open(cli.__file__, encoding="utf-8").read()
    assert '"--warmup"' in src and "def _fold_warmup" in src and len(cli.WARMUP_SEQ) >= 10
