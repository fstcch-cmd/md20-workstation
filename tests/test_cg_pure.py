"""D-86 coarse-grained path, pure Python parts: force-field download check, topology helpers, GUI settings and the
workflow driver with the build, run and analysis replaced (the real tools run in tests/test_cg_integration.py)."""
import hashlib
import io
import json
import zipfile

import pytest

from md20.build import martini as M
from md20.build import cg_system as C
from md20.gui import advanced as A


def _fake_zip(tamper: str | None = None) -> tuple[bytes, dict]:
    buf = io.BytesIO()
    sums = {}
    with zipfile.ZipFile(buf, "w") as z:
        for name in M.FF_SOURCE["sha256"]:
            blob = f"; {name}\n[ moleculetype ]\nPOPC 1\n".encode()
            sums[name] = hashlib.sha256(blob).hexdigest()
            z.writestr(M.FF_SOURCE["member_dir"] + name, blob + (b"x" if name == tamper else b""))
    return buf.getvalue(), sums


def test_install_forcefield_checks_sha256(tmp_path, monkeypatch):
    data, sums = _fake_zip()
    monkeypatch.setitem(M.FF_SOURCE, "sha256", sums)
    r = M.install_forcefield(tmp_path / "ff", fetch=lambda url: data)
    assert sorted(r["files"]) == sorted(sums) and M.forcefield_ready(tmp_path / "ff")
    bad, _ = _fake_zip(tamper=M.FF_CORE)
    with pytest.raises(ValueError, match="SHA-256"):
        M.install_forcefield(tmp_path / "ff2", fetch=lambda url: bad)
    assert not (tmp_path / "ff2").exists()                 # nothing is written when one file fails


def test_pinned_sources_agree():
    assert M.FF_SOURCE["zip"] == M.TOOLS["martini_openmm"]["pip"]       # force field from the same commit pip installs
    assert all(len(v) == 64 for v in M.FF_SOURCE["sha256"].values())


def test_itp_names_and_bead_count(tmp_path):
    itp = tmp_path / "molecule_0.itp"
    itp.write_text("[ moleculetype ]\n; name nrexcl\nmolecule_0 1\n[ atoms ]\n1 Q5 1 MET BB 1 1\n2 C6 1 MET SC1 2 0\n"
                   "3 P2 2 ALA BB 3 0\n[ bonds ]\n1 2 1 0.3 5000\n", encoding="utf-8")
    assert M.itp_molecule_names(itp) == {"molecule_0"}
    assert C.protein_bead_count("[ molecules ]\nmolecule_0 2\n", [itp]) == 6


def test_read_gro_and_protein_only(tmp_path):
    gro = tmp_path / "s.gro"
    rows = [(1, "POPC", "NC3", 1.0, 2.0, 3.0), (1, "POPC", "PO4", 1.1, 2.0, 3.5), (2, "W", "W", 0.5, 0.5, 0.5)]
    body = "".join(f"{r:5d}{rn:<5s}{an:>5s}{i + 1:5d}{x:8.3f}{y:8.3f}{z:8.3f}\n" for i, (r, rn, an, x, y, z) in enumerate(rows))
    gro.write_text("t\n3\n" + body + "   5.0 6.0 7.0\n", encoding="utf-8")
    g = C.read_gro(gro)
    assert g["name"] == ["NC3", "PO4", "W"] and list(g["box"]) == [5.0, 6.0, 7.0] and g["xyz"][1, 2] == pytest.approx(3.5)
    pdb = tmp_path / "a.pdb"
    pdb.write_text("ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N\n"
                   "HETATM    2 ZN    ZN A 101       1.000   0.000   0.000  1.00  0.00          ZN\nEND\n", encoding="utf-8")
    r = C.protein_only(pdb, tmp_path / "b.pdb")
    assert r == {"atoms": 1, "hetatm_dropped": 1}


def test_plan_variants(tmp_path):
    ff = tmp_path / "ff"; ff.mkdir()
    for f in M.FF_FILES.values():
        (ff / f).write_text("; itp\n")
    (ff / M.FF_FILES["phospholipids"]).write_text("[ moleculetype ]\nPOPC 1\n[ moleculetype ]\nPOPE 1\n")
    av = {k: {"module": True, "executable": True, "argv": [k], "ok": True} for k in ("vermouth", "insane")}
    av["martini_openmm"] = {"module": True, "executable": None, "argv": None, "ok": True}
    b = M.plan_cg_membrane(None, tmp_path, forcefield_dir=ff, avail=av)                      # bilayer only
    assert b.status == "PASS" and [s["name"] for s in b.steps][0] == "insane" and "-f" not in b.steps[0]["argv"]
    s = M.plan_cg_membrane("p.pdb", tmp_path, forcefield_dir=ff, avail=av, memshift_nm=3.5, ss="HHHC")
    m2 = s.steps[0]["argv"]
    assert m2[m2.index("-ss") + 1] == "HHHC" and "-dssp" not in m2
    ins = s.steps[1]["argv"]
    assert ins[ins.index("-dm") + 1] == "3.5" and ins[ins.index("-ff") + 1] == "M3"
    w = M.plan_cg_membrane("p.pdb", tmp_path, forcefield_dir=ff, avail=av, membrane=False)
    assert "-l" not in w.steps[1]["argv"] and w.status == "PASS"
    bad = M.plan_cg_membrane(None, tmp_path, forcefield_dir=ff, avail=av, lipids={"CL": 1})
    assert bad.status == "NEEDS_HUMAN" and bad.issues[0]["code"] == "lipid_not_in_martini3"


def test_gui_resolution_settings_and_checks():
    cfg = {"receptor": {"pdb_id": "1ABC"}, "ligands": [{"name": "BEN", "smiles": "c1ccccc1"},
                                                       {"name": "MEL", "sequence": "GIGAVLKVLTTGLPALISWIKRKRQQ"}],
           "binding": {"enabled": True}, "md": {}}
    adv = {**A.defaults(), "resolution": "cg", "membrane_type": "surface"}
    out = A.apply_advanced(cfg, adv)
    assert out["md"]["resolution"] == "cg" and [l["name"] for l in out["ligands"]] == ["MEL"]
    assert out["binding"]["enabled"] is False and out["receptor"] == {}
    assert "resolution" not in A.apply_advanced(cfg, A.defaults())["md"]
    iss = A.advanced_checks({**A.defaults(), "resolution": "cg", "membrane_type": "protein"}, ligands=cfg["ligands"],
                            has_receptor=False, binding=True, lang="en", cg_ready=False)
    levels = {(i["key"], i["level"]) for i in iss}
    assert ("resolution", "error") in levels and ("resolution", "warning") in levels


def test_workflow_cg_driver(tmp_path, monkeypatch):
    """build → run → analysis → report with the three heavy calls replaced; the report must contain the CG section."""
    from md20.project import Project
    from md20.workflow import Workflow
    import md20.build.cg_system as CS
    import md20.engine.cg_run as CR
    import md20.analysis.cg as AC

    def fake_build(workdir, **kw):
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / "system.xml").write_text("<System/>", encoding="utf-8")
        return {"kind": kw["kind"], "workdir": str(workdir), "system_xml": str(workdir / "system.xml"), "n_beads": 100,
                "plan": {"status": "PASS", "steps": [{"name": "insane", "kind": "exec", "outputs": ["system.gro"]}]},
                "settings": {"timestep_fs": 20.0, "epsilon_r": 15.0, "cutoff_nm": 1.1, "friction_per_ps": 10.0},
                "membrane": True, "lipids": kw.get("lipids")}

    def fake_run(man, run_dir, **kw):
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "production.dcd").write_bytes(b"")
        return {"status": "COMPLETE", "run_dir": str(run_dir)}

    def fake_analyse(man, run_dir, decisions=None):
        d = {"time_ns": [0, 1, 2, 3], "apl_nm2": [0.64, 0.65, 0.64, 0.65], "dpp_nm": [4.0, 4.0, 4.1, 4.0],
             "reference": {"apl_nm2": 0.643, "dpp_nm": None}, "p2": {"C1A-D2A": 0.35}, "resolution": "coarse-grained"}
        f = run_dir / "cg_analysis.json"
        f.write_text(json.dumps(d), encoding="utf-8")
        return {**d, "file": str(f)}
    monkeypatch.setattr(CS, "build_cg_system", fake_build)
    monkeypatch.setattr(CR, "run_cg", fake_run)
    monkeypatch.setattr(AC, "analyse_cg", fake_analyse)
    cfg = {"name": "cg", "receptor": {}, "ligands": [], "md": {"resolution": "cg", "production_ns": 100,
           "membrane": {"type": "bilayer", "lipids": "mammalian"}}, "binding": {"enabled": False}}
    wf = Workflow(Project.create(tmp_path, "p"), cfg)

    class P:
        name = "CPU"
        properties = {}
    r = wf._run(lambda *a: None, P())
    assert r["status"] == "COMPLETE"
    st = wf.state()
    assert "cg_bilayer" in st["coarse_grained"] and st["coarse_grained"]["cg_bilayer"]["membrane_file"]
    html = open(r["report"], encoding="utf-8").read()
    assert "Martini" in html
