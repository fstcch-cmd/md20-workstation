from pathlib import Path

import pytest

from md20.project import Project, detect_stage
from md20.util import FileLock, cheap_fingerprint, verify_cheap_fingerprint, atomic_write_json, load_json, safe_name


def test_project_case_run_roundtrip(tmp_path: Path):
    p = Project.create(tmp_path, "My Project 2026")
    assert (p.dir / "project.json").is_file() and p.uuid
    assert Project.discover(tmp_path)[0].dir == p.dir
    with pytest.raises(FileExistsError):
        Project.create(tmp_path, "My Project 2026")
    c = p.new_case("kinase/lig#1")
    assert c.manifest()["forcefield_family"] == "amber"
    src = tmp_path / "rec.pdb"; src.write_text("ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n")
    rec = c.import_input(src, "receptor")
    assert Path(rec["path"]).is_file() and rec["sha256"]
    r = c.new_run({"tier": "classroom"})
    assert c.active_run().run_id == r.run_id
    assert detect_stage(r) is None
    atomic_write_json({"status": "PASS"}, c.build_dir / "build_manifest.json")
    assert detect_stage(r) == "BUILT"
    atomic_write_json({"status": "PASS"}, r.stage_dir("minimize") / "minimize_complete.json")
    atomic_write_json({"status": "RUNNING"}, r.stage_dir("nvt") / "nvt_complete.json")
    assert detect_stage(r) == "MINIMIZED"
    assert "force-field family" in p.decisions.to_markdown()


def test_safe_name_windows_reserved():
    assert safe_name("CON") == "CON_" and safe_name("a/b:c*d") == "a_b_c_d" and safe_name("") == "item"


def test_cheap_fingerprint_and_lock(tmp_path: Path):
    f = tmp_path / "big.bin"; f.write_bytes(b"a" * 200_000 + b"tail")
    fp = cheap_fingerprint(f)
    assert verify_cheap_fingerprint(f, fp)
    f.write_bytes(b"a" * 200_000 + b"TAIL")
    assert not verify_cheap_fingerprint(f, fp)
    with FileLock(tmp_path / "x.lock", timeout=1):
        with pytest.raises(TimeoutError):
            with FileLock(tmp_path / "x.lock", timeout=0.3):
                pass


def test_load_json_falls_back_to_backup(tmp_path: Path):
    p = tmp_path / "s.json"
    atomic_write_json({"v": 1}, p); atomic_write_json({"v": 2}, p)
    p.write_text("{corrupt", encoding="utf-8")
    assert load_json(p)["v"] == 1
