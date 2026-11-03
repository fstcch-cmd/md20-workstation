"""Coarse-grained Martini 3 scaffolding (md20/build/martini.py): availability, command plan, topology composition."""
import pytest

from md20.build import martini as M


def _avail(modules, exes=None):
    exes = modules if exes is None else exes
    return M.availability(find_spec=lambda m: object() if m in modules else None,
                          which=lambda e: f"/bin/{e}" if e in exes else None)


def test_tool_table_records_verified_facts():
    assert M.TOOLS["vermouth"]["executable"] == "martinize2" and M.TOOLS["vermouth"]["license"] == "Apache-2.0"
    assert M.TOOLS["insane"]["license"] == "GPL-2.0-or-later"
    assert "maccallumlab/martini_openmm" in M.TOOLS["martini_openmm"]["pip"]
    for t in M.TOOLS.values():
        assert len(t["commit"]) == 40


def test_availability_needs_module_and_executable():
    a = _avail({"vermouth", "insane", "martini_openmm"}, {"martinize2"})       # insane module but no insane script
    assert a["vermouth"]["ok"] and a["martini_openmm"]["ok"] and a["martini_openmm"]["executable"] is None
    assert not a["insane"]["ok"]
    assert M.missing_tools(a) == ["insane"]
    assert M.missing_tools(_avail(set())) == ["vermouth", "insane", "martini_openmm"]


def test_plan_not_installed_is_needs_human(tmp_path):
    p = M.plan_cg_membrane(tmp_path / "prot.pdb", tmp_path / "cg", avail=_avail(set()))
    assert p.status == "NEEDS_HUMAN"
    codes = {i["code"] for i in p.issues}
    assert codes == {"not_installed", "forcefield_files"}
    assert any("md20 setup-cg" in o for i in p.issues for o in i["options"])
    assert all(len(i["text"]) == 4 for i in p.issues)


def test_plan_ready_and_argv(tmp_path):
    ff = tmp_path / "ff"; ff.mkdir()
    for f in M.FF_FILES.values():
        (ff / f).write_text("; itp\n")
    all_tools = {"vermouth", "insane", "martini_openmm", "martinize2"}      # module and script names
    p = M.plan_cg_membrane(tmp_path / "prot.pdb", tmp_path / "cg", lipids={"POPC": 3, "POPG": 1}, box_nm=(12, 12, 11),
                           salt_molar=0.15, forcefield_dir=ff, avail=_avail(all_tools))
    assert p.status == "PASS" and not p.missing and not p.missing_ff
    names = [s["name"] for s in p.steps]
    assert names == ["martinize2", "insane", "compose_topology", "martini_openmm"]
    m2 = p.steps[0]["argv"]
    assert m2[0] == "martinize2" and m2[m2.index("-ff") + 1] == "martini3001" and "-elastic" in m2 and "-dssp" in m2
    ins = p.steps[1]["argv"]
    assert ins[ins.index("-x") + 1] == "12" and ins[ins.index("-z") + 1] == "11"
    assert ["-l", "POPC:3"] == ins[ins.index("-l"):ins.index("-l") + 2] and "POPG:1" in ins
    assert ins[ins.index("-salt") + 1] == "0.15" and ins[ins.index("-sol") + 1] == "W"
    st = p.steps[3]["settings"]
    assert st == {"epsilon_r": 15.0, "cutoff_nm": 1.1, "timestep_fs": 20.0, "friction_per_ps": 10.0}
    # no salt → the ions itp is not required
    (ff / M.FF_FILES["ions"]).unlink()
    assert M.plan_cg_membrane("x.pdb", tmp_path, salt_molar=0, forcefield_dir=ff, avail=_avail(all_tools)).status == "PASS"


def test_compose_topology_replaces_protein_entry():
    insane = ('#include "martini.itp"\n\n[ system ]\n; name\nProtein in INSANE!\n\n[ molecules ]\n; name  number\n'
              "Protein          1\nPOPC           128 ; upper\nPOPC           128\nW             3000\nNA              40\nCL              38\n")
    protein = '#include "martini.itp"\n#include "molecule_0.itp"\n[ system ]\nx\n[ molecules ]\nmolecule_0    1\nmolecule_1 2\n'
    top = M.compose_topology(insane, protein, [M.FF_CORE, M.FF_FILES["phospholipids"]], ["molecule_0.itp", "molecule_1.itp"])
    assert top.splitlines()[0] == f'#include "{M.FF_CORE}"' and '#include "molecule_1.itp"' in top
    assert M.molecules_section(top) == [("molecule_0", 1), ("molecule_1", 2), ("POPC", 128), ("POPC", 128),
                                        ("W", 3000), ("NA", 40), ("CL", 38)]
    assert "martini.itp" not in top


def test_install_plan_and_cli_preview_installs_nothing(capsys, monkeypatch):
    cmds = M.install_plan("py")
    assert [c[:4] for c in cmds] == [["py", "-m", "pip", "install"]] * 3
    assert cmds[0][4] == "vermouth" and cmds[2][4].endswith(".zip")
    import subprocess
    monkeypatch.setattr(subprocess, "call", lambda *a, **k: pytest.fail("preview must not run pip"))
    from md20.cli import main
    assert main(["setup-cg"]) == 0
    out = capsys.readouterr().out
    assert "vermouth" in out and "insane" in out and "martini_openmm" in out and "--yes" in out
