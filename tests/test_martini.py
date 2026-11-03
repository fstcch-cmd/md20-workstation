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
    assert a["insane"]["ok"] and a["insane"]["argv"][1] == "-c"             # D-86: started through python (shim)
    a = _avail({"insane", "martini_openmm"}, set())
    assert M.missing_tools(a) == ["vermouth"]
    assert M.missing_tools(_avail(set())) == ["vermouth", "insane", "martini_openmm"]


def test_plan_not_installed_is_needs_human(tmp_path):
    p = M.plan_cg_membrane(tmp_path / "prot.pdb", tmp_path / "cg", avail=_avail(set()), forcefield_dir=tmp_path / "no_ff")
    assert p.status == "NEEDS_HUMAN"
    codes = {i["code"] for i in p.issues}
    assert codes == {"not_installed", "forcefield_files"}
    assert any("md20 setup-cg" in o for i in p.issues for o in i["options"])
    assert all(len(i["text"]) == 4 for i in p.issues)


def test_plan_ready_and_argv(tmp_path):
    ff = tmp_path / "ff"; ff.mkdir()
    for f in M.FF_FILES.values():
        (ff / f).write_text("; itp\n")
    (ff / M.FF_FILES["phospholipids"]).write_text("[ moleculetype ]\nPOPC 1\n[ atoms ]\n[moleculetype]\n; c\nPOPG 1\n")
    all_tools = {"vermouth", "insane", "martini_openmm", "martinize2"}      # module and script names
    p = M.plan_cg_membrane(tmp_path / "prot.pdb", tmp_path / "cg", lipids={"POPC": 3, "POPG": 1}, box_nm=(12, 12, 11),
                           salt_molar=0.15, forcefield_dir=ff, avail=_avail(all_tools))
    assert p.status == "PASS" and not p.missing and not p.missing_ff
    names = [s["name"] for s in p.steps]
    assert names == ["martinize2", "insane", "compose_topology", "martini_openmm"]
    m2 = p.steps[0]["argv"]
    assert m2[0].endswith("martinize2") and m2[m2.index("-ff") + 1] == "martini3001" and "-elastic" in m2 and "-dssp" in m2
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


def test_tool_argv_finds_script_off_path(tmp_path):
    """Laptop 11/03: pip put martinize2 in <env>/Scripts, which was not on PATH."""
    (tmp_path / "martinize2.exe").write_text("")
    argv = M.tool_argv("martinize2", which=lambda e: None, find_spec=lambda m: None, script_dirs=[tmp_path])
    assert argv == [str(tmp_path / "martinize2.exe")]
    (tmp_path / "insane").write_text("#!python\n")                        # extension-less script → run with python
    argv = M.tool_argv("insane", which=lambda e: None, find_spec=lambda m: None, script_dirs=[tmp_path])
    assert argv[1] == str(tmp_path / "insane")


def test_tool_argv_module_fallback_and_reason():
    argv = M.tool_argv("martinize2", which=lambda e: None, script_dirs=[],
                       find_spec=lambda m: object() if m == "vermouth.bin.martinize2" else None)
    assert argv[1] == "-c" and "from vermouth.bin.martinize2 import entry" in argv[2]
    assert M.tool_argv("martinize2", which=lambda e: None, script_dirs=[], find_spec=lambda m: None) is None
    a = _avail({"vermouth", "insane", "martini_openmm"}, {"insane"})
    assert M.missing_tools(a) == ["vermouth"]
    assert "找不到指令 martinize2" in M.why_missing(a)[0]
    assert "無法匯入" in M.why_missing(_avail({"insane", "martini_openmm", "martinize2"}))[0]


def test_insane_shim_reads_package_data(tmp_path, monkeypatch):
    """The stand-in pkg_resources.resource_stream reads a file next to the package, like insane/utils.py expects."""
    import subprocess, sys
    pkg = tmp_path / "insane"; pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "lipids.dat").write_text("M3.POPC 0\n")
    (pkg / "utils.py").write_text("import pkg_resources\n"
                                  "def first():\n    with pkg_resources.resource_stream(__name__, 'lipids.dat') as f:\n"
                                  "        return f.readline().decode()\n")
    (pkg / "cli.py").write_text("from . import utils\nimport sys\ndef cli():\n    print(utils.first().strip(), sys.argv[1:])\n    return 0\n")
    code = M.INSANE_LAUNCH.replace("import pkg_resources", "import pkg_resources_absent_for_test")
    r = subprocess.run([sys.executable, "-c", code, "-x", "6"], cwd=tmp_path, capture_output=True, text=True,
                       env={"PYTHONPATH": str(tmp_path), "PATH": ""})
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "M3.POPC 0 ['-x', '6']"
