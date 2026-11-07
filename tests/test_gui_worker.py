"""D-103: the GUI's calculation runs in its own process; status and progress are read back from files."""
import copy
import json
import os
import sys
import time
from pathlib import Path


def _workflow(tmp_path, name="w1"):
    from md20.project.store import Project
    from md20.workflow import Workflow, example_config
    cfg = copy.deepcopy(example_config())
    cfg["name"] = name
    proj = Project.create(tmp_path, "p")
    return Workflow(proj, cfg)


def test_progress_reader_reads_whole_lines_only_and_restarts_on_truncate(tmp_path):
    from md20.gui.worker import ProgressReader
    f = tmp_path / "progress.jsonl"
    f.write_text('{"a": 1}\n{"a": 2}\n{"a"', encoding="utf-8")        # the writer is in the middle of line 3
    r = ProgressReader(f)
    assert [e["a"] for e in r.read()] == [1, 2]
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(': 3}\n')
    assert [e["a"] for e in r.read()] == [1, 2, 3]
    assert [e["a"] for e in r.read()] == [1, 2, 3]                       # nothing new: nothing added twice
    f.write_text('{"a": 9}\n', encoding="utf-8")                         # a new run truncates the file
    assert [e["a"] for e in r.read()] == [9]


def test_heartbeat_freshness():
    from md20.gui.worker import heartbeat_fresh, STALE_S
    now = 1000.0
    assert heartbeat_fresh({"status": "RUNNING", "heartbeat": now - 10}, now)
    assert not heartbeat_fresh({"status": "RUNNING", "heartbeat": now - STALE_S - 1}, now)
    assert not heartbeat_fresh({"status": "COMPLETE", "heartbeat": now}, now)
    assert not heartbeat_fresh({}, now)


def test_run_worker_writes_status_progress_and_pointer(tmp_path):
    from md20.gui.worker import run_worker, read_job, pointer_path, job_dir, read_json
    wf = _workflow(tmp_path)
    seen = {}

    def run_fn(w, cb):
        cb({"stage": "nvt", "completed_local_steps": 5, "total_steps": 10})
        seen["pointer"] = read_json(pointer_path(tmp_path))            # while running, the pointer names this run
        seen["job"] = read_job(w.dir)
        return {"status": "COMPLETE", "report": "r.html"}
    info = run_worker(wf.project.dir, wf.name, run_fn=run_fn)
    assert info["status"] == "COMPLETE" and info["message"][1] == "Done"
    assert seen["pointer"]["name"] == wf.name and seen["pointer"]["pid"] == os.getpid()
    assert seen["job"]["status"] == "RUNNING"
    assert not pointer_path(tmp_path).exists()                            # removed when the run ends
    j = read_job(wf.dir)
    assert j["status"] == "COMPLETE" and j["report"] == "r.html"
    lines = (job_dir(wf.dir) / "progress.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["stage"] == "nvt"


def test_run_worker_reports_blocked_and_errors(tmp_path):
    from md20.gui.worker import run_worker
    from md20.workflow import WorkflowBlocked
    wf = _workflow(tmp_path)

    def blocked(w, cb):
        raise WorkflowBlocked("需要人工決定")
    assert run_worker(wf.project.dir, wf.name, run_fn=blocked)["status"] == "NEEDS_HUMAN"

    def boom(w, cb):
        raise RuntimeError("壞了")
    info = run_worker(wf.project.dir, wf.name, run_fn=boom)
    assert info["status"] == "ERROR" and "RuntimeError" in info["message"]


def test_process_job_reads_back_and_flags_a_dead_worker(tmp_path):
    from md20.gui.logic import ProcessJob, _msg
    from md20.gui.worker import job_dir, _write_json
    wf = _workflow(tmp_path)
    jd = job_dir(wf.dir)
    _write_json({"status": "COMPLETE", "message": ["完成", "Done", "完了しました", "완료"], "report": "x"}, jd / "job.json")
    (jd / "progress.jsonl").write_text('{"stage": "md"}\n', encoding="utf-8")
    snap = ProcessJob(wf).snapshot()
    assert snap["status"] == "COMPLETE" and snap["message"] == ("完成", "Done", "完了しました", "완료")
    assert snap["history"] == [{"stage": "md"}]
    # a RUNNING record whose heartbeat stopped long ago: the process is gone, never shown as running
    _write_json({"status": "RUNNING", "heartbeat": time.time() - 10_000}, jd / "job.json")
    job = ProcessJob(wf)
    assert not job.alive() and job.snapshot()["status"] == "ERROR"
    assert _msg("plain") == "plain"


def test_runner_attaches_after_restart_and_runs_one_at_a_time(tmp_path):
    """A second Runner (= the GUI after a restart) finds the running worker from the pointer file."""
    from md20.gui.logic import Runner
    from md20.gui.worker import job_dir, pointer_path, _write_json
    wf = _workflow(tmp_path, "w1")
    _write_json({"status": "RUNNING", "heartbeat": time.time(), "pid": 4242}, job_dir(wf.dir) / "job.json")
    _write_json({"project": str(wf.project.dir), "name": wf.name, "pid": 4242}, pointer_path(tmp_path))
    launched = []
    r = Runner(launcher=lambda w: launched.append(w) or None)
    job = r.running(tmp_path)
    assert job is not None and job.wf.dir == wf.dir and job.alive()
    assert r.start_process(wf) is job and not launched                    # pressing start again does not start it twice
    assert r.get(wf) is job


def test_real_worker_process_survives_and_is_read_back(tmp_path, monkeypatch):
    """End to end without NiceGUI: launch md20.gui.worker with the timed stand-in, drop the Runner (as a GUI restart
    would), attach a new Runner and read status and progress from the files."""
    from md20.gui.logic import Runner
    monkeypatch.setenv("MD20_GUI_FAKE_RUN", "3")
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1]) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    wf = _workflow(tmp_path)
    job = Runner().start_process(wf)
    deadline = time.time() + 60
    while time.time() < deadline and not (wf.dir / "_gui_job" / "job.json").is_file():
        time.sleep(0.2)
    again = Runner()                                                      # "the GUI restarted"
    attached = again.running(tmp_path) or again.get(wf)
    assert attached is not None
    job.popen.wait(60)
    snap = again.get(wf).snapshot()
    assert snap["status"] == "COMPLETE", (wf.dir / "_gui_job" / "worker.log").read_text(encoding="utf-8", errors="replace")
    assert any(e.get("stage") == "fake" for e in snap["history"])
    st = json.loads((wf.dir / "_fake_run.json").read_text(encoding="utf-8"))
    assert st["starts"] == 1 and st["finished"]
