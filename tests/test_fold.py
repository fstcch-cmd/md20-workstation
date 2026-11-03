"""D-80 one-click folding (md20/build/fold.py): pure tests with fake engines and fake PDB files.

Real engines: test_omegafold_real (skips unless the `omegafold` program is installed; CI has none, the laptop runs it
after `md20 setup-fold --yes`).  RDKit/Meeko parts (template mapping, rigid backbone) run in the openmm-stack CI."""
import copy
import json
import math

import pytest

from md20.build import fold as F
from md20.build.gates import PASS, AUTO_FIXED, NEEDS_HUMAN

SEQ20 = "GIGAVLKVLTTGLPALISWI"          # melittin 1-20
SEQ_REC = "IVGGYTCGANTVPYQVSLNSGYHFCGGSLINSQWVVSAAHC"


def _fake_pdb(seq, b, *, chain="A", start=0, oxt=False, ile_cd=False, drop=None, extra_chains=()):
    """PDB text with every heavy atom of `seq` (OmegaFold style: numbering from `start`, no OXT), B-factor `b`
    (a number or one value per residue)."""
    lines, k = [], 0
    chains = [(chain, seq, b)] + list(extra_chains)
    for ch, sq, bb in chains:
        for i, aa in enumerate(sq):
            bi = bb[i] if isinstance(bb, (list, tuple)) else bb
            names = list(F.HEAVY_ATOMS[aa]) + (["OXT"] if oxt and i == len(sq) - 1 else [])
            for j, nm in enumerate(names):
                if drop and (i, nm) == drop:
                    continue
                if ile_cd and aa == "I" and nm == "CD1":
                    nm = "CD"
                k += 1
                x, y, z = 3.8 * i + 0.3 * j, 0.5 * j, 0.1 * k
                lines.append(f"ATOM  {k:5d} {(' ' + nm) if len(nm) < 4 else nm:<4s} {F.ONE_TO_THREE[aa]:>3s} {ch}{start + i:4d}    "
                             f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00{bi:6.2f}           {nm[0]}")
        lines.append("TER")
    return "\n".join(lines + ["END"]) + "\n"


def _fake_runner(text, meta=None, calls=None):
    def run(seqs, chains, out, device, timeout_s, **kw):
        if calls is not None:
            calls.append({"seqs": seqs, "device": device, **kw})
        p = out / "fake.pdb"
        p.write_text(text(seqs) if callable(text) else text)
        return p, dict(meta or {})
    return run


@pytest.fixture
def fake_omega(monkeypatch):
    calls = []

    def install(b):
        monkeypatch.setitem(F.RUNNERS, "omegafold", _fake_runner(lambda s: _fake_pdb(s[0], b), calls=calls))
        return calls
    return install


# ------------------------------------------------------------------------------------------ parsing
def test_pdb_parsing_plddt_and_chain():
    per = [50 + i for i in range(20)]
    res = F.residues(F.parse_pdb(_fake_pdb(SEQ20, per)))
    assert F.chain_sequences(res) == {"A": SEQ20}
    assert F.residue_plddt(res["A"]) == per
    assert F.find_chain(res, SEQ20) == "A"
    with pytest.raises(F.FoldError) as e:
        F.find_chain(res, "KKKK")
    assert set(e.value.text) == {"zh", "en", "ja", "ko"} and "KKKK" in e.value.text["en"]


def test_mmcif_parsing_first_model_and_quotes(tmp_path):
    cif = """data_x
#
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_alt_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_seq_id
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.B_iso_or_equiv
_atom_site.auth_seq_id
_atom_site.auth_asym_id
_atom_site.pdbx_PDB_model_num
ATOM 1 N N . GLY A 1 0.0 0.0 0.0 81.5 1 B 1
ATOM 2 C CA . GLY A 1 1.4 0.0 0.0 82.5 1 B 1
ATOM 3 C C . GLY A 1 2.0 1.4 0.0 83.5 1 B 1
ATOM 4 O O . GLY A 1 1.3 2.4 0.0 84.5 1 B 1
ATOM 5 N N . ALA A 2 3.3 1.5 0.0 70.0 2 B 1
ATOM 6 C CA . ALA A 2 4.0 2.7 0.0 71.0 2 B 1
ATOM 7 C "C" . ALA A 2 5.5 2.5 0.0 72.0 2 B 1
ATOM 8 N N . GLY A 1 9.9 9.9 9.9 10.0 1 B 2
#
"""
    p = tmp_path / "fold_x_model_0.cif"
    p.write_text(cif)
    atoms = F.read_structure(p)
    assert len(atoms) == 7                                     # model 2 dropped
    res = F.residues(atoms)
    assert list(res) == ["B"] and F.chain_sequences(res)["B"] == "GA"
    assert res["B"][1]["atoms"]["C"]["x"] == 5.5
    assert F.residue_plddt(res["B"]) == [82.5, 71.0]           # CA B-factor


def test_unreadable_and_missing_upload(tmp_path):
    with pytest.raises(F.FoldError) as e:
        F.read_structure(tmp_path / "nope.pdb")
    assert e.value.key == "upload_missing"
    (tmp_path / "x.pdb").write_text("HELLO\n")
    with pytest.raises(F.FoldError) as e:
        F.read_structure(tmp_path / "x.pdb")
    assert e.value.key == "upload_format"


def test_bad_sequence_message_four_languages():
    with pytest.raises(F.FoldError) as e:
        F.clean("GIGXZ", "PEP")
    assert "XZ" in e.value.text["ko"] and e.value.pick("ja") == e.value.text["ja"]
    assert F.clean(" gig avl-k*") == "GIGAVLK"


# ------------------------------------------------------------------------------------------ engine choice
def test_auto_choice_single_and_complex():
    all_ = {"omegafold": True, "esmfold": True, "boltz": True, "colabfold": False}
    assert F.choose_engine(1, vram_mb=8188, available=all_)[:2] == ("omegafold", "cuda")
    e, d, notes = F.choose_engine(1, vram_mb=0, available=all_)
    assert (e, d) == ("omegafold", "cpu") and notes and "CPU" in notes[0]["en"]
    assert F.choose_engine(1, vram_mb=8188, available={"esmfold": True})[:2] == ("esmfold", "cuda")
    assert F.choose_engine(1, vram_mb=4000, available={"esmfold": True})[:2] == ("esmfold", "cpu")
    assert F.choose_engine(1, vram_mb=12000, available={"boltz": True})[0] == "boltz"
    assert F.choose_engine(2, vram_mb=8188, available=all_)[:2] == ("boltz", "cuda")
    with pytest.raises(F.FoldUnavailable) as e:
        F.choose_engine(2, vram_mb=4000, available=all_)       # boltz needs 8 GB, no colabfold
    assert e.value.key == "no_engine_complex" and F.OPT_UPLOAD in e.value.options
    assert F.choose_engine(2, vram_mb=4000, available={"colabfold": True})[0] == "colabfold"
    with pytest.raises(F.FoldUnavailable) as e:
        F.choose_engine(1, vram_mb=8000, available={})
    assert e.value.key == "no_engine" and all(e.value.text[l] for l in ("zh", "en", "ja", "ko"))


def test_explicit_engine_missing_or_single_only(tmp_path):
    with pytest.raises(F.FoldUnavailable) as e:
        F.fold(SEQ20, engine="omegafold", out_dir=tmp_path, available={"omegafold": False}, vram_mb=8000)
    assert "setup-fold --engine omegafold" in e.value.text["en"]
    with pytest.raises(F.FoldError) as e:
        F.fold([SEQ_REC, SEQ20], engine="omegafold", out_dir=tmp_path, available={"omegafold": True}, vram_mb=8000)
    assert e.value.key == "single_only"
    with pytest.raises(F.FoldError) as e:
        F.fold(SEQ20, engine="alphafold3", out_dir=tmp_path)
    assert e.value.key == "unknown_engine"


def test_engine_failure_is_reported_not_silent(tmp_path, monkeypatch):
    import sys
    monkeypatch.setattr(F, "find_tool", lambda name: sys.executable)
    with pytest.raises(F.FoldError) as e:      # python rejects omegafold's arguments → non-zero exit
        F.fold(SEQ20, engine="omegafold", out_dir=tmp_path, available={"omegafold": True}, vram_mb=0)
    assert e.value.key == "failed" and (tmp_path / "omegafold.log").is_file()


# ------------------------------------------------------------------------------------------ gates
@pytest.mark.parametrize("b,status", [(85.0, PASS), (60.0, AUTO_FIXED), (40.0, NEEDS_HUMAN)])
def test_plddt_gates(tmp_path, fake_omega, b, status):
    calls = fake_omega(b)
    r = F.fold(SEQ20, out_dir=tmp_path, available={"omegafold": True}, vram_mb=8188)
    assert calls[0]["device"] == "cuda" and r.engine == "omegafold"
    assert r.mean_plddt == pytest.approx(b) and len(r.per_residue_plddt) == 20
    assert r.status == status and r.provenance == "predicted"
    g = r.gates["gates"][0]
    assert g["name"] == "fold confidence" and set(g["evidence"]["text"]) == {"zh", "en", "ja", "ko"}
    if status == NEEDS_HUMAN:
        assert F.OPT_NO_FOLD in g["options"] and F.OPT_UPLOAD in g["options"] and F.OPT_ACCEPT_LOW in g["options"]
    saved = json.loads((tmp_path / "fold_result.json").read_text(encoding="utf-8"))
    assert saved["status"] == status and saved["engine"] == "omegafold"
    assert (tmp_path / "predicted.pdb").read_text().startswith("REMARK")


def test_low_plddt_accepted_by_user(tmp_path, fake_omega):
    fake_omega(40.0)
    r = F.fold(SEQ20, out_dir=tmp_path, available={"omegafold": True}, vram_mb=8188, accept_low=True)
    assert r.status == AUTO_FIXED and r.gates["gates"][0]["evidence"]["human"]


def test_bfactors_zero_to_one_are_scaled(tmp_path, monkeypatch):
    monkeypatch.setitem(F.RUNNERS, "esmfold", _fake_runner(lambda s: _fake_pdb(s[0], 0.8)))
    r = F.fold(SEQ20, engine="esmfold", out_dir=tmp_path, available={"esmfold": True}, vram_mb=16000)
    assert r.mean_plddt == pytest.approx(80.0) and any("100" in n["en"] for n in r.notes)


def test_short_peptide_is_not_folded(tmp_path, fake_omega):
    calls = fake_omega(90.0)
    r = F.fold("GGGGGKP", out_dir=tmp_path, available={"omegafold": True}, vram_mb=8188)
    assert r.status == "SKIPPED_SHORT" and not calls and r.pdb_path == ""
    assert "extended" in r.notes[0]["en"] and r.gates == {}


def test_complex_iptm_advisory(tmp_path, monkeypatch):
    calls = []
    text = lambda s: _fake_pdb(s[0], 90.0, extra_chains=[("B", s[1], 62.0)])   # noqa: E731
    monkeypatch.setitem(F.RUNNERS, "boltz", _fake_runner(text, {"iptm": 0.31, "complex_plddt": 0.85}, calls))
    r = F.fold([SEQ_REC, SEQ20], out_dir=tmp_path, available={"boltz": True}, vram_mb=8188)
    assert r.engine == "boltz" and r.is_complex and r.peptide_chain == "B"
    assert r.mean_plddt == pytest.approx(62.0) and r.complex_plddt == pytest.approx(85.0) and r.iptm == 0.31
    gates = {g["name"]: g for g in r.gates["gates"]}
    assert gates["fold confidence"]["status"] == AUTO_FIXED
    assert gates["fold interface"]["status"] == AUTO_FIXED and gates["fold interface"]["advisory"]
    assert r.status == AUTO_FIXED                         # advisory never blocks
    assert any("single-sequence" in n["en"] for n in r.notes)   # boltz without MSA says so


def test_boltz_yaml_single_sequence_mode():
    y = F.boltz_yaml([SEQ_REC, SEQ20], ["A", "B"], msa_server=False)
    assert "id: A" in y and "id: B" in y and y.count("msa: empty") == 2 and f"sequence: {SEQ20}" in y
    assert "msa" not in F.boltz_yaml([SEQ20], ["A"], msa_server=True)


def test_upload_with_alphafold_server_confidence(tmp_path):
    d = tmp_path / "af"
    d.mkdir()
    (d / "fold_pep_model_0.pdb").write_text(_fake_pdb(SEQ_REC, 92.0, extra_chains=[("B", SEQ20, 75.0)]))
    (d / "fold_pep_summary_confidences_0.json").write_text(json.dumps({"iptm": 0.66, "ptm": 0.7}))
    r = F.fold([SEQ_REC, SEQ20], out_dir=tmp_path / "out", upload=d / "fold_pep_model_0.pdb")
    assert r.engine == "upload" and r.provenance == "predicted (uploaded)"
    assert r.iptm == 0.66 and r.status == PASS and r.peptide_chain == "B"
    # an uploaded short peptide is still read (the user chose the structure)
    (d / "short.pdb").write_text(_fake_pdb("GGKP", 80.0))
    assert F.fold("GGKP", out_dir=tmp_path / "o2", upload=d / "short.pdb").status == PASS


def test_upload_colabfold_naming(tmp_path):
    p = tmp_path / "job_unrelaxed_rank_001_alphafold2_ptm_model_1_seed_000.pdb"
    p.write_text("x")
    j = tmp_path / "job_scores_rank_001_alphafold2_ptm_model_1_seed_000.json"
    j.write_text("{}")
    assert F.upload_confidence_json(p) == j


# ------------------------------------------------------------------------------------------ mapping to the template
def test_heavy_coords_oxt_and_synonym():
    res = F.residues(F.parse_pdb(_fake_pdb(SEQ20, 80.0, ile_cd=True)))["A"]
    coords, notes = F.peptide_heavy_coords(res, SEQ20)
    assert "OXT" in coords[-1] and all("CD1" in c for c, aa in zip(coords, SEQ20) if aa == "I")
    keys = {n["en"].split()[0] for n in notes}
    assert "The" in keys and any("CD" in n["en"] and "CD1" in n["en"] for n in notes)
    # placement on real backbone geometry (O-C-CA about 121 degrees): OXT about 120 degrees from O, 1.25 A from C
    c, ca = (0.0, 0.0, 0.0), (1.52, 0.0, 0.0)
    o = (1.23 * math.cos(math.radians(121)), 1.23 * math.sin(math.radians(121)), 0.0)
    oxt = F._place_oxt(c, o, ca)
    dist = math.dist(c, oxt)
    v1 = [o[i] - c[i] for i in range(3)]
    v2 = [oxt[i] - c[i] for i in range(3)]
    ang = math.degrees(math.acos(sum(a * b for a, b in zip(v1, v2)) / (math.hypot(*v1) * math.hypot(*v2))))
    assert dist == pytest.approx(1.25, abs=0.01) and 100 < ang < 140


def test_missing_atom_is_not_guessed():
    res = F.residues(F.parse_pdb(_fake_pdb(SEQ20, 80.0, drop=(3, "CB"))))["A"]
    with pytest.raises(F.FoldError) as e:
        F.peptide_heavy_coords(res, SEQ20)
    assert e.value.key == "atoms_missing" and "CB" in e.value.text["en"]


# ------------------------------------------------------------------------------------------ setup plan
def test_setup_plan_separate_env(tmp_path):
    plan = F.setup_plan("omegafold", vram_mb=8188, platform="win32", micromamba="C:/mm/micromamba.exe", prefix=tmp_path / "fe")
    cmds = [" ".join(s["cmd"]) for s in plan["steps"]]
    assert plan["ok"] and "create" in cmds[0] and "python=3.10" in cmds[0]
    assert "download.pytorch.org/whl/cu121" in cmds[1]
    assert "--no-deps git+https://github.com/HeliXonProtein/OmegaFold.git" in cmds[2]
    assert "omegafold_ckpt" in plan["first_run_download"]
    mac = F.setup_plan("boltz", vram_mb=0, platform="darwin", micromamba="/mm", prefix=tmp_path / "fe")
    assert "whl/cu121" not in " ".join(mac["steps"][1]["cmd"]) and mac["steps"][2]["cmd"][-1] == "boltz"
    assert not F.setup_plan("esmfold", micromamba=None, prefix=tmp_path / "none")["ok"]


# ------------------------------------------------------------------------------------------ CLI
def test_cli_fold_upload_and_setup_preview(tmp_path, monkeypatch, capsys):
    from md20 import cli
    up = tmp_path / "pep.pdb"
    up.write_text(_fake_pdb(SEQ20, 77.0))
    assert cli.main(["fold", SEQ20, "--engine", "upload", "--upload", str(up), "--out", str(tmp_path / "o")]) == 0
    out = capsys.readouterr().out
    assert "平均 pLDDT：77.0" in out and "[PASS] fold confidence" in out
    up.write_text(_fake_pdb(SEQ20, 30.0))
    assert cli.main(["fold", SEQ20, "--upload", str(up), "--out", str(tmp_path / "o2")]) == 1      # NEEDS_HUMAN
    assert cli.main(["fold", SEQ20, "--engine", "boltz", "--out", str(tmp_path / "o3")]) == 2       # not installed here
    assert "boltz" in capsys.readouterr().out

    import subprocess
    monkeypatch.setattr(subprocess, "call", lambda *a, **k: pytest.fail("setup-fold ran without --yes"))
    monkeypatch.setattr(F, "find_micromamba", lambda: "/opt/mm/micromamba")
    monkeypatch.setenv("MD20_FOLD_ENV", str(tmp_path / "fe"))
    assert cli.main(["setup-fold", "--engine", "boltz"]) == 0
    out = capsys.readouterr().out
    assert "預覽" in out and "pip install boltz" in out and "--yes" in out


# ------------------------------------------------------------------------------------------ workflow hook
def _wf(tmp_path, **lig):
    from md20.project.store import Project
    from md20.workflow import Workflow, example_config
    cfg = copy.deepcopy(example_config())
    cfg["ligands"] = [{"name": "PEP", "sequence": SEQ20, "fold": True, **lig}]
    return Workflow(Project.create(tmp_path, "p"), cfg)


def _patch_fold(monkeypatch, b, calls=None):
    real = F.fold

    def fake_fold(seq, **kw):
        if calls is not None:
            calls.append(kw)
        kw.pop("available", None)
        return real(seq, available={"omegafold": True}, vram_mb=8188, **kw)
    monkeypatch.setitem(F.RUNNERS, "omegafold", _fake_runner(lambda s: _fake_pdb(s[0], b)))
    monkeypatch.setattr(F, "fold", fake_fold)

    def fake_sdf(r, path):
        path.write_text("fake sdf\n")
        return path, []
    monkeypatch.setattr(F, "docking_sdf", fake_sdf)


def test_workflow_fold_hook_uses_prediction(tmp_path, monkeypatch):
    calls = []
    _patch_fold(monkeypatch, 82.0, calls)
    wf = _wf(tmp_path)
    sdf = wf._fold_peptide(wf.cfg["ligands"][0])
    assert sdf and sdf.endswith("PEP_predicted.sdf")
    st = wf.state()["fold"]["PEP"]
    assert st["engine"] == "omegafold" and st["status"] == PASS and st["rigid_backbone"] and st["provenance"] == "predicted"
    d = [x for x in wf.dec.read() if x["stage"] == "build.fold"]
    assert d and "預測" in d[-1]["why"] and "φ/ψ" in d[-1]["why"]
    assert wf._fold_peptide(wf.cfg["ligands"][0]) == sdf and len(calls) == 1      # cached, not folded again


def test_workflow_fold_low_confidence_blocks_then_accept(tmp_path, monkeypatch):
    from md20.workflow import WorkflowBlocked
    from md20.gui.views import gate_cards
    _patch_fold(monkeypatch, 35.0)
    wf = _wf(tmp_path)
    with pytest.raises(WorkflowBlocked):
        wf._fold_peptide(wf.cfg["ligands"][0])
    step = wf.state()["steps"]["fold"]
    assert step["status"] == NEEDS_HUMAN and step["ligand"] == "PEP" and F.OPT_ACCEPT_LOW in step["gates"][0]["options"]
    assert any(c["status"] == NEEDS_HUMAN for c in gate_cards(wf))
    wf.cfg["ligands"][0]["fold_accept_low"] = True
    assert wf._fold_peptide(wf.cfg["ligands"][0])
    assert [x for x in wf.dec.read() if x["stage"] == "build.fold"][-1]["kind"] == "human"


def test_workflow_fold_unavailable_needs_human(tmp_path, monkeypatch):
    from md20.workflow import WorkflowBlocked
    monkeypatch.setattr(F, "engine_available", lambda e: e == "upload")
    wf = _wf(tmp_path)
    with pytest.raises(WorkflowBlocked) as e:
        wf._fold_peptide(wf.cfg["ligands"][0])
    assert "setup-fold" in str(e.value)
    g = wf.state()["steps"]["fold"]["gates"][0]
    assert g["name"] == "fold" and g["options"] == [F.OPT_INSTALL, F.OPT_UPLOAD, F.OPT_NO_FOLD]
    assert set(g["evidence"]["text"]) == {"zh", "en", "ja", "ko"}


def test_workflow_short_peptide_keeps_extended_build(tmp_path, monkeypatch):
    _patch_fold(monkeypatch, 90.0)
    wf = _wf(tmp_path)
    wf.cfg["ligands"][0]["sequence"] = "GGGGGKP"
    assert wf._fold_peptide(wf.cfg["ligands"][0]) is None
    assert wf.state()["fold"]["PEP"]["status"] == "SKIPPED_SHORT"


def test_fold_decisions_survive_pipeline_rerun():
    from md20.workflow import merge_human_decisions
    old = {"ligands": [{"name": "PEP", "sequence": SEQ20, "fold": True, "fold_accept_low": True, "fold_upload": "a.cif"}]}
    new = {"ligands": [{"name": "PEP", "sequence": SEQ20, "fold": True}]}
    merged, carried = merge_human_decisions(new, old)
    assert merged["ligands"][0]["fold_accept_low"] and merged["ligands"][0]["fold_upload"] == "a.cif"


def test_docking_ligand_input_has_rigid_backbone():
    from md20.docking.run import LigandInput, BACKBONE_RIGID_SMARTS, BACKBONE_RIGID_INDICES
    assert LigandInput(name="x").rigid_backbone is False
    assert len(BACKBONE_RIGID_SMARTS) == len(BACKBONE_RIGID_INDICES) == 2


# ------------------------------------------------------------------------------------------ RDKit / Meeko (CI)
def _rdkit_peptide_pdb(seq, b):
    """Realistic geometry: RDKit-embedded peptide, written as PDB without OXT (as OmegaFold does), numbered from 0."""
    from rdkit import Chem
    from rdkit.Chem import AllChem
    m = Chem.AddHs(Chem.MolFromSequence(seq))
    AllChem.EmbedMolecule(m, randomSeed=7)
    m = Chem.RemoveHs(m)
    out = []
    for line in Chem.MolToPDBBlock(m).splitlines():
        if line.startswith(("ATOM", "HETATM")):
            if line[12:16].strip() == "OXT":
                continue
            resseq = int(line[22:26]) - 1
            line = "ATOM  " + line[6:22] + f"{resseq:4d}" + line[26:60] + f"{b:6.2f}" + line[66:]
        out.append(line)
    return "\n".join(out) + "\n"


def test_docking_sdf_from_prediction(tmp_path):
    pytest.importorskip("rdkit")
    from rdkit import Chem
    up = tmp_path / "pred.pdb"
    up.write_text(_rdkit_peptide_pdb(SEQ20, 81.0))
    r = F.fold(SEQ20, out_dir=tmp_path / "o", upload=up)
    assert r.status == PASS
    sdf, notes = F.docking_sdf(r, tmp_path / "pep.sdf")
    mol = next(iter(Chem.SDMolSupplier(str(sdf))))
    tmpl = Chem.RemoveHs(Chem.MolFromSequence(SEQ20))
    assert mol.GetNumAtoms() == tmpl.GetNumAtoms() and any("OXT" in n["en"] for n in notes)


def test_rigid_backbone_reduces_torsions(tmp_path):
    pytest.importorskip("rdkit")
    pytest.importorskip("meeko")
    from md20.docking.run import LigandInput, _ligand_mol, _meeko_pdbqt
    up = tmp_path / "pred.pdb"
    up.write_text(_rdkit_peptide_pdb("GIGAVLKVLT", 85.0))
    r = F.fold("GIGAVLKVLT", out_dir=tmp_path / "o", upload=up)
    sdf, _ = F.docking_sdf(r, tmp_path / "pep.sdf")
    mol = _ligand_mol(LigandInput(name="PEP", sdf=str(sdf)))

    def torsdof(s):
        return int(next(l for l in s.splitlines() if l.startswith("TORSDOF")).split()[1])
    flex, rigid = torsdof(_meeko_pdbqt(mol)), torsdof(_meeko_pdbqt(mol, rigid_backbone=True))
    # 10 residues: 9 φ + 9 ψ backbone torsions minus the glycine-free… at least 2 per non-terminal residue fixed
    assert rigid < flex and flex - rigid >= 10, (flex, rigid)


def test_omegafold_real(tmp_path):
    """Laptop/CI with OmegaFold installed (`md20 setup-fold --yes`): fold melittin 1-20 for real."""
    if not F.engine_available("omegafold"):
        pytest.skip("omegafold not installed (md20 setup-fold --engine omegafold --yes)")
    r = F.fold(SEQ20, engine="omegafold", out_dir=tmp_path)
    assert r.engine == "omegafold" and len(r.per_residue_plddt) == 20 and 0 < r.mean_plddt <= 100
    assert r.status in (PASS, AUTO_FIXED, NEEDS_HUMAN) and r.runtime_s > 0
    print(f"omegafold {SEQ20}: mean pLDDT {r.mean_plddt}, {r.runtime_s} s on {r.device}")


# ------------------------------------------------------------------------------------------ complex → actual receptor
def _rot(deg):
    import numpy as np
    a = math.radians(deg)
    Rz = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
    b = math.radians(deg / 2)
    Rx = np.array([[1, 0, 0], [0, math.cos(b), -math.sin(b)], [0, math.sin(b), math.cos(b)]])
    return Rz @ Rx


def _moved(res, R, t, *, chain=None, noise=0.0, drop_first=0):
    import numpy as np
    rng = np.random.default_rng(1)
    out = {}
    for c, rs in res.items():
        new = []
        for x in rs[drop_first:]:
            atoms = {}
            for k, a in x["atoms"].items():
                v = np.array([a["x"], a["y"], a["z"]]) @ R.T + t + (rng.normal(0, noise, 3) if noise else 0)
                atoms[k] = {**a, "x": float(v[0]), "y": float(v[1]), "z": float(v[2])}
            new.append({**x, "atoms": atoms})
        out[chain or c] = new
    return out


def _complex_prediction(tmp_path, monkeypatch):
    text = lambda s: _fake_pdb(s[0], 90.0, extra_chains=[("B", s[1], 80.0)])   # noqa: E731
    monkeypatch.setitem(F.RUNNERS, "boltz", _fake_runner(text, {"iptm": 0.7}))
    return F.fold([SEQ_REC, SEQ20], out_dir=tmp_path / "pred", available={"boltz": True}, vram_mb=8188)


def test_align_and_kabsch():
    assert F.align("ACDEFG", "ACDEFG") == [(i, i) for i in range(6)]
    assert F.align("ACDEFGHIK", "ACDHIK") == [(0, 0), (1, 1), (2, 2), (6, 3), (7, 4), (8, 5)]
    import numpy as np
    P = np.random.default_rng(0).normal(size=(30, 3)) * 5
    R0, t0 = _rot(70), np.array([3.0, -2.0, 11.0])
    R, t, rmsd = F.kabsch(P, P @ R0.T + t0)
    assert rmsd < 1e-6 and np.allclose(R, R0) and np.allclose(t, t0)


def test_place_peptide_on_actual_receptor(tmp_path, monkeypatch):
    import numpy as np
    r = _complex_prediction(tmp_path, monkeypatch)
    pred = F.residues(F.read_structure(r.pdb_path))
    R0, t0 = _rot(40), np.array([10.0, 5.0, -3.0])
    ref = F.write_pdb(_moved({"A": pred["A"]}, R0, t0, chain="X", drop_first=3), tmp_path / "crystal.pdb")   # missing N-terminus
    pl = F.place_peptide(r, tmp_path / "pl", reference=ref)
    assert pl.status == PASS and pl.receptor_source == "actual" and pl.chain_map == {"A": "X"}
    assert pl.rmsd_ca < 1e-3 and pl.n_matched == len(SEQ_REC) - 3
    placed = F.residues(F.read_structure(pl.peptide_pdb))["B"]
    want = np.array([pred["B"][0]["atoms"]["CA"][k] for k in "xyz"]) @ R0.T + t0
    got = np.array([placed[0]["atoms"]["CA"][k] for k in "xyz"])
    assert np.allclose(got, want, atol=2e-3)
    g = pl.gates["gates"][0]
    assert g["name"] == "fold placement" and set(g["evidence"]["text"]) == {"zh", "en", "ja", "ko"}


def test_place_peptide_high_rmsd_needs_human(tmp_path, monkeypatch):
    import numpy as np
    r = _complex_prediction(tmp_path, monkeypatch)
    pred = F.residues(F.read_structure(r.pdb_path))
    ref = F.write_pdb(_moved({"A": pred["A"]}, np.eye(3), np.zeros(3), noise=2.5), tmp_path / "crystal.pdb")
    pl = F.place_peptide(r, tmp_path / "pl", reference=ref)
    assert pl.status == NEEDS_HUMAN and pl.rmsd_ca > F.SUP_MAX_RMSD
    assert pl.gates["gates"][0]["options"][:2] == [F.OPT_ACCEPT_RMSD, F.OPT_DOCK]
    ok = F.place_peptide(r, tmp_path / "pl2", reference=ref, accept_rmsd=True)
    assert ok.status == AUTO_FIXED and ok.gates["gates"][0]["evidence"]["human"]


def test_place_peptide_unrelated_receptor_or_none(tmp_path, monkeypatch):
    r = _complex_prediction(tmp_path, monkeypatch)
    other = tmp_path / "other.pdb"
    other.write_text(_fake_pdb("W" * 40, 50.0))
    pl = F.place_peptide(r, tmp_path / "pl", reference=other)
    assert pl.status == NEEDS_HUMAN and pl.gates["gates"][0]["evidence"]["n_matched"] < F.SUP_MIN_MATCHED
    pl = F.place_peptide(r, tmp_path / "pl2", reference=None)
    assert pl.receptor_source == "predicted" and pl.status == AUTO_FIXED
    assert "PREDICTED" in open(pl.receptor_pdb).read().splitlines()[0]


def test_receptor_sequences_notes_chain_breaks(tmp_path):
    res = F.residues(F.parse_pdb(_fake_pdb(SEQ_REC, 50.0)))
    for x in res["A"][20:]:
        for a in x["atoms"].values():
            a["x"] += 30.0                                       # a gap between residue 20 and 21
    p = F.write_pdb(res, tmp_path / "gap.pdb")
    seqs, chains, notes = F.receptor_sequences(p)
    assert seqs == [SEQ_REC] and chains == ["A"] and notes and "fold_receptor_seq" in notes[0]["en"]


def test_workflow_fold_complex_goes_to_md(tmp_path, monkeypatch):
    import numpy as np
    from md20.workflow import WorkflowBlocked
    r = _complex_prediction(tmp_path, monkeypatch)
    pred = F.residues(F.read_structure(r.pdb_path))
    raw = F.write_pdb(_moved({"A": pred["A"]}, _rot(25), np.array([1.0, 2.0, 3.0])), tmp_path / "raw.pdb")
    monkeypatch.setitem(F.RUNNERS, "boltz", _fake_runner(lambda s: _fake_pdb(s[0], 90.0, extra_chains=[("B", s[1], 80.0)]),
                                                         {"iptm": 0.7}))
    real = F.fold
    monkeypatch.setattr(F, "fold", lambda seqs, **kw: real(seqs, **{**kw, "available": {"boltz": True}, "vram_mb": 8188}))
    seen = {}

    def fake_sdf(res, path, transform=None):
        seen["transform"] = transform
        path.write_text("sdf\n")
        return path, []
    monkeypatch.setattr(F, "docking_sdf", fake_sdf)
    wf = _wf(tmp_path, fold="complex")
    sdf = wf._fold_complex(wf.cfg["ligands"][0], raw, "SMILES")
    rec = wf.state()["fold"]["PEP"]
    assert rec["placement"]["rmsd_ca"] < 1e-3 and rec["engine"] == "boltz" and rec["complex_pose"] == sdf
    assert seen["transform"] is not None
    d = [x for x in wf.dec.read() if x["stage"] == "build.fold"][-1]
    assert "不經對接" in d["why"] and "Kabsch" in d["why"]
    sel = {"mode": "independent", "ligands": {}}
    wf._complex_picks(sel)
    assert sel["ligands"]["PEP"]["source"] == "fold_complex" and sel["ligands"]["PEP"]["sdf"] == sdf
    # a receptor that does not match the prediction stops with options
    raw2 = F.write_pdb(_moved({"A": pred["A"]}, np.eye(3), np.zeros(3), noise=3.0), tmp_path / "raw2.pdb")
    with pytest.raises(WorkflowBlocked):
        wf._fold_complex(wf.cfg["ligands"][0], raw2, "SMILES")
    assert F.OPT_ACCEPT_RMSD in wf.state()["steps"]["fold"]["gates"][0]["options"]


def test_docking_sdf_with_transform(tmp_path):
    pytest.importorskip("rdkit")
    import numpy as np
    from rdkit import Chem
    up = tmp_path / "pred.pdb"
    up.write_text(_rdkit_peptide_pdb(SEQ20, 81.0))
    r = F.fold(SEQ20, out_dir=tmp_path / "o", upload=up)
    a, _ = F.docking_sdf(r, tmp_path / "a.sdf")
    b, _ = F.docking_sdf(r, tmp_path / "b.sdf", transform=(np.eye(3), np.array([5.0, 0.0, 0.0])))
    ma, mb = (next(iter(Chem.SDMolSupplier(str(x)))) for x in (a, b))
    d = mb.GetConformer().GetPositions() - ma.GetConformer().GetPositions()
    assert np.allclose(d, [5.0, 0.0, 0.0], atol=2e-3)
