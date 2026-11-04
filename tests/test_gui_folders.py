"""D-88: the user chooses where projects are saved and opens a project or workflow folder from anywhere."""
import json

import pytest

from md20.gui import folders as F
from md20.project import Project
from md20.workflow import Workflow, example_config


@pytest.fixture(autouse=True)
def _settings(tmp_path, monkeypatch):
    monkeypatch.setenv("MD20_GUI_FOLDERS", str(tmp_path / "cfg" / "gui_folders.json"))


def test_check_folder(tmp_path):
    ok, p = F.check_folder(str(tmp_path / "a" / "b"))
    assert ok and (tmp_path / "a" / "b").is_dir() and not list((tmp_path / "a" / "b").iterdir())   # probe removed
    assert F.check_folder("relative/path") == (False, "relative")
    assert F.check_folder("") == (False, "empty")
    f = tmp_path / "file.txt"; f.write_text("x")
    assert F.check_folder(str(f)) == (False, "not_a_folder")


def test_remember_recent_and_saved(tmp_path):
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir(); b.mkdir()
    F.remember(a); F.remember(b); F.remember(a)
    assert F.saved_projects_dir() == a and F.recent() == [str(a), str(b)]
    b.rmdir()
    assert F.recent() == [str(a)]                      # folders that are gone are not offered


def test_classify(tmp_path):
    cfg = example_config(); cfg["name"] = "w1"
    proj = Project.create(tmp_path / "root", "p1")
    wf = Workflow(proj, cfg)
    assert F.classify(wf.dir) == {"kind": "workflow", "projects_dir": str(tmp_path / "root"), "project": "p1", "workflow": "w1"}
    assert F.classify(proj.dir)["kind"] == "project" and F.classify(proj.dir / "workflows")["kind"] == "project"
    assert F.classify(tmp_path / "root") == {"kind": "projects_root", "projects_dir": str(tmp_path / "root")}
    (tmp_path / "empty").mkdir()
    assert F.classify(tmp_path / "empty")["kind"] == "empty_folder"
    assert F.classify(tmp_path / "nope")["kind"] == "missing"
    assert F.project_workflows(tmp_path / "root", "p1") == ["w1"]


def test_cli_uses_the_folder_chosen_in_the_gui(tmp_path, capsys):
    from md20 import cli
    chosen = tmp_path / "chosen"
    Project.create(chosen, "picked_in_gui")
    F.remember(chosen)
    assert cli.main(["project", "list"]) == 0
    assert "picked_in_gui" in capsys.readouterr().out
    other = tmp_path / "other"
    Project.create(other, "given_on_command_line")
    assert cli.main(["--dir", str(other), "project", "list"]) == 0           # --dir still wins
    assert "given_on_command_line" in capsys.readouterr().out
