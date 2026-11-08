"""D-143: the autonomy loop made usable — owner policy CLI, executors with measured use, checkpoint fingerprint, cost inputs.
Nothing runs without a policy file the owner wrote; no budget has a default.  Fakes only (no OpenMM)."""
import json
import shutil
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from md20.autonomy import Controller, Ledger, Policy, load_policy, save_policy
from md20.autonomy.cli import PolicyRefused, build_policy, policy_summary, status_data
from md20.autonomy.controller import default_checkpoint_validator
from md20.autonomy.executors import WorkflowExecutors, window_ps
from md20.autonomy.inputs import doctor_benchmark, inputs_for_workflow, storage_gb_per_ns
from md20.autonomy.model import ACTION_EXTEND, ACTION_REANALYSIS, ACTION_REFINE, ACTION_REPLICA, ACTION_TYPES, FORBIDDEN_CHANGES
from md20.autonomy.rules import AssessmentInputs
from md20.cli import main
from md20.engine.longrun import dcd_frame_bytes
from md20.engine.runner import checkpoint_fingerprint, chunk_manifest_digest
from md20.util import atomic_write_json, load_json
from md20.util.paths import app_data_dir
from test_autonomy_kit import StubWorkflow, build_workflow, fake_factory, failing_pmf, good_pmf, legacy_pmf

ALL = ",".join(ACTION_TYPES)
GPU = SimpleNamespace(name="CUDA", properties={})


def cli(tmp_path, kit, *args):
    return main(["--dir", str(tmp_path), "autonomy", *args[:1], *args[1:], "--workflow-dir", str(kit.wf_dir)])


def set_policy(kit, **kw):
    d = dict(policy_id="pol-t", approved_by="owner", approved_at="2026-11-08T00:00:00Z", allowed_actions=tuple(ACTION_TYPES),
             max_sim_ns=100.0, max_gpu_hours=50.0, max_core_hours=None, max_storage_gb=50.0)
    d.update(kw)
    save_policy(kit.wf_dir, Policy(**d))


def failing(inp, *ids):
    """The same input with these diagnostics failing (and the sampling no longer adequate)."""
    inp.assessment = {**inp.assessment, "sampling_adequate": False,
                      "diagnostics": [{**d, "status": "fail"} if d["id"] in ids else d for d in inp.assessment["diagnostics"]]}
    return inp


def snapshot(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def doctor(tmp_path, monkeypatch):
    """A doctor benchmark record in a throw-away app-data folder."""
    monkeypatch.setenv("MD20_DATA_DIR", str(tmp_path / "appdata"))   # D-148: isolate on every OS, incl. macOS
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "xdg"))

    def write(**b):
        rec = {"platform": "CUDA", "n_atoms": 24000, "timestep_fs": 4.0, "ns_per_day": 200.0}
        rec.update(b)
        atomic_write_json({"benchmark": rec, "created_at": "2026-11-01T00:00:00Z"}, app_data_dir() / "doctor" / "doctor_report.json")
    return write


@pytest.fixture(autouse=True)
def _default_benchmark(doctor):
    """Most tests want a known speed (an unknown estimate needs approval); the ones about a missing record remove it."""
    doctor()


# ======================================================================================== owner policy CLI
def test_policy_set_show_revoke_round_trip(tmp_path, capsys):
    kit = build_workflow(tmp_path)
    assert load_policy(kit.wf_dir)[0] is None
    rc = main(["autonomy", "policy", "set", "--workflow-dir", str(kit.wf_dir), "--approver", "Chen-Che", "--allow",
               "reanalysis,add_independent_replica", "--ns", "5", "--gpu-hours", "3", "--max-attempts", "3", "--yes"])
    out = capsys.readouterr().out
    assert rc == 0 and "Chen-Che" in out and "5" in out
    pol, _ = load_policy(kit.wf_dir)
    assert pol.approved_by == "Chen-Che" and pol.approved_at and set(pol.allowed_actions) == {"reanalysis", "add_independent_replica"}
    assert (pol.max_sim_ns, pol.max_gpu_hours, pol.max_core_hours, pol.max_storage_gb) == (5.0, 3.0, None, None)   # no default for the rest
    assert pol.max_attempts == 3 and pol.no_improvement_stop == 2
    assert pol.effective()[0]
    # the audit trail is in the ledger
    assert [r["event"] for r in Ledger(kit.wf_dir / "autonomy").records()] == ["policy_set"]
    # show: plain summary, including what never runs by itself
    assert main(["autonomy", "policy", "show", "--workflow-dir", str(kit.wf_dir), "--lang", "en"]) == 0
    shown = capsys.readouterr().out
    assert "Chen-Che" in shown and "not authorized" in shown and "force field" in shown and "need your approval" in shown
    assert main(["autonomy", "policy", "show", "--workflow-dir", str(kit.wf_dir), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["effective"] is True
    # revoke: the file moves away (kept as history), policy is gone, ledger says who
    assert main(["autonomy", "policy", "revoke", "--workflow-dir", str(kit.wf_dir), "--by", "Chen-Che"]) == 0
    assert load_policy(kit.wf_dir)[0] is None
    assert list((kit.wf_dir / "autonomy").glob("autonomy_policy.revoked-*.json"))
    assert [r["event"] for r in Ledger(kit.wf_dir / "autonomy").records()] == ["policy_set", "policy_revoked"]
    main(["autonomy", "policy", "show", "--workflow-dir", str(kit.wf_dir)])
    assert "沒有行動政策" in capsys.readouterr().out
    assert main(["autonomy", "policy", "revoke", "--workflow-dir", str(kit.wf_dir), "--by", "x"]) == 0     # nothing left: no error


def test_replacing_a_policy_keeps_the_old_one_as_history(tmp_path, capsys):
    kit = build_workflow(tmp_path)
    base = ["autonomy", "policy", "set", "--workflow-dir", str(kit.wf_dir), "--approver", "A", "--yes", "--allow", "reanalysis"]
    assert main(base + ["--ns", "1"]) == 0 and main(base + ["--ns", "2"]) == 0
    assert load_policy(kit.wf_dir)[0].max_sim_ns == 2.0
    old = list((kit.wf_dir / "autonomy").glob("autonomy_policy.superseded-*.json"))
    assert len(old) == 1 and json.loads(old[0].read_text(encoding="utf-8"))["max_sim_ns"] == 1.0


@pytest.mark.parametrize("allow", sorted(FORBIDDEN_CHANGES) + ["delete_everything", "reanalysis,force_field", ""])
def test_forbidden_unknown_and_empty_actions_are_refused_and_write_nothing(tmp_path, capsys, allow):
    kit = build_workflow(tmp_path)
    snap = snapshot(kit.wf_dir)
    args = ["autonomy", "policy", "set", "--workflow-dir", str(kit.wf_dir), "--approver", "A", "--ns", "5", "--yes"]
    rc = main(args + ["--allow", allow])
    assert rc == 2 and "拒絕" in capsys.readouterr().err
    assert snapshot(kit.wf_dir) == snap and not (kit.wf_dir / "autonomy").exists()


def test_policy_without_budget_or_approver_or_with_bad_numbers_is_refused(tmp_path):
    ns = lambda **kw: SimpleNamespace(**{"approver": "A", "allow": "reanalysis", "ns": None, "gpu_hours": None, "core_hours": None,  # noqa: E731
                                         "storage_gb": None, "max_attempts": None, "no_improvement_stop": None, **kw})
    with pytest.raises(PolicyRefused, match="預算"):
        build_policy(ns())                                    # not a single number: there is no default budget
    with pytest.raises(PolicyRefused, match="預算"):
        build_policy(ns(ns=0))                                # zero authorizes nothing either
    with pytest.raises(PolicyRefused, match="核准者"):
        build_policy(ns(approver=" ", ns=1))
    with pytest.raises(PolicyRefused, match="非負"):
        build_policy(ns(ns=-1))
    with pytest.raises(PolicyRefused, match="非負"):
        build_policy(ns(ns=float("inf")))
    with pytest.raises(PolicyRefused, match="整數"):
        build_policy(ns(ns=1, max_attempts=0))
    p = build_policy(ns(ns=1))
    assert p.approved_at and p.approved_by == "A" and p.max_gpu_hours is None


def test_policy_set_needs_a_person_to_confirm(tmp_path, capsys, monkeypatch):
    kit = build_workflow(tmp_path)
    args = ["autonomy", "policy", "set", "--workflow-dir", str(kit.wf_dir), "--approver", "A", "--allow", "reanalysis", "--ns", "1"]
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: False))
    assert main(args) == 2 and load_policy(kit.wf_dir)[0] is None             # no terminal and no --yes: refused
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda prompt="": "no")
    assert main(args) == 2 and load_policy(kit.wf_dir)[0] is None
    monkeypatch.setattr("builtins.input", lambda prompt="": "yes")
    assert main(args) == 0 and load_policy(kit.wf_dir)[0] is not None


def test_policy_summary_is_available_in_four_languages():
    pol = Policy("p", "A", "2026-11-08T00:00:00Z", ("reanalysis",), max_sim_ns=2.0)
    texts = {l: "\n".join(policy_summary(pol, l, {"sim_ns": 1.5})) for l in ("zh", "en", "ja", "ko")}
    assert len(set(texts.values())) == 4 and all("2" in t and "1.5" in t for t in texts.values())
    assert "力場" in texts["zh"] and "force field" in texts["en"] and "力場" in texts["ja"] and "힘장" in texts["ko"]


# ======================================================================================== no policy: plan only
def test_no_policy_means_plan_only_and_plan_writes_nothing(tmp_path, capsys):
    kit = build_workflow(tmp_path)
    snap = snapshot(kit.wf_dir)
    assert main(["autonomy", "plan", "--workflow-dir", str(kit.wf_dir)]) == 0
    out = capsys.readouterr().out
    assert "沒有行動政策" in out and "重新分析" in out and "recommendation_only" in out
    assert snapshot(kit.wf_dir) == snap and not (kit.wf_dir / "autonomy").exists()
    assert main(["autonomy", "plan", "--workflow-dir", str(kit.wf_dir), "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows and all(not p["would_execute"] for r in rows for p in r["proposals"])
    assert snapshot(kit.wf_dir) == snap


def test_run_refuses_without_a_valid_policy_and_never_calls_an_executor(tmp_path, capsys):
    kit = build_workflow(tmp_path)
    assert main(["autonomy", "run", "--workflow-dir", str(kit.wf_dir), "--fake"]) == 2
    assert "沒有有效的行動政策" in capsys.readouterr().err
    assert not (kit.wf_dir / "autonomy").exists()
    (kit.wf_dir / "autonomy").mkdir()
    (kit.wf_dir / "autonomy" / "autonomy_policy.json").write_text("{not json", encoding="utf-8")        # invalid = no policy
    assert main(["autonomy", "run", "--workflow-dir", str(kit.wf_dir), "--fake"]) == 2
    set_policy(kit, approved_by="")                                                                      # no approver = no policy
    assert main(["autonomy", "run", "--workflow-dir", str(kit.wf_dir), "--fake"]) == 2


def test_status_reports_cost_and_policy(tmp_path, capsys):
    kit = build_workflow(tmp_path)
    assert main(["autonomy", "status", "--workflow-dir", str(kit.wf_dir)]) == 0
    assert "嘗試 0 次" in capsys.readouterr().out
    set_policy(kit)
    d = status_data(kit.wf_dir)
    assert d["policy_effective"] and d["integrity"]["ok"] and d["remaining"]["sim_ns"] == 100.0


def test_run_with_policy_executes_the_reanalysis_through_the_ledger(tmp_path, capsys):
    kit = build_workflow(tmp_path, pmf=good_pmf())
    set_policy(kit, allowed_actions=("reanalysis",))
    assert main(["autonomy", "run", "--workflow-dir", str(kit.wf_dir), "--fake", "--max-cycles", "1"]) == 0
    assert "reanalysis：ok" in capsys.readouterr().out
    res = load_json(kit.wf_dir / "state.json")["steps"]["binding"]["results"][kit.target]
    assert res["assessment"]["provenance"]["source"] == "reassessed"
    led = Ledger(kit.wf_dir / "autonomy")
    assert [r["event"] for r in led.records()].count("exec_start") == 1
    cs = led.cost_summary()
    assert cs["attempts"] == 1 and cs["simulated_ps_reported"] == 0.0 and cs["resources"]["wall_s"] >= 0
    # the same evidence state again: nothing is launched a second time
    main(["autonomy", "run", "--workflow-dir", str(kit.wf_dir), "--fake", "--max-cycles", "1"])
    assert [r["event"] for r in Ledger(kit.wf_dir / "autonomy").records()].count("exec_start") == 1


# ======================================================================================== executors through claim
def ctl_for(kit, wf, *, platform=GPU, factory=lambda case, proto: fake_factory, **kw):
    ex = WorkflowExecutors(wf, factory, platform, check_licence=False, **kw)
    return Controller.for_workflow(kit.wf_dir, executor=ex, preflight=ex.preflight, reassessor=ex.reassessor), ex


def proposals_of(kit, ctl, **inp_kw):
    inp = inputs_for_workflow(kit.wf_dir, **inp_kw)[0]
    return ctl.step(inp).proposals


def test_reanalysis_goes_through_claim_and_a_duplicate_launch_is_prevented(tmp_path):
    kit = build_workflow(tmp_path, pmf=good_pmf())
    set_policy(kit)
    wf = StubWorkflow(kit)
    c1, _ = ctl_for(kit, wf)
    p = next(x for x in proposals_of(kit, c1) if x.action_type == ACTION_REANALYSIS)
    c2, _ = ctl_for(kit, wf)                                   # a second worker on the same ledger
    out1, out2 = c1.execute(p), c2.execute(p)
    assert out1.status == "ok" and out2.status != "ok" and "已成功" in out2.reason
    assert [r["event"] for r in c1.ledger.records()].count("exec_start") == 1


def test_executor_is_only_reachable_through_claim(tmp_path):
    """Two workers racing for the same replica top-up: run_md is entered once."""
    kit = build_workflow(tmp_path)
    set_policy(kit)
    entered = []
    gate = threading.Event()

    def run_md(wf):
        entered.append(1)
        gate.wait(2)
        return wf.state()["steps"]["md_runs"]["runs"]
    wf = StubWorkflow(kit, run_md=run_md)
    c, _ = ctl_for(kit, wf)
    p = next(x for x in proposals_of(kit, c) if x.action_type == ACTION_REPLICA)
    res = []
    t = threading.Thread(target=lambda: res.append(c.execute(p)))
    t.start()
    for _ in range(100):
        if entered:
            break
        threading.Event().wait(0.02)
    c2, _ = ctl_for(kit, StubWorkflow(kit, run_md=run_md))
    dup = c2.execute(p)
    gate.set()
    t.join(5)
    assert dup.status != "ok" and "進行中" in dup.reason and len(entered) == 1 and res[0].status == "ok"


def test_add_replica_runs_the_topup_path_and_reports_measured_use(tmp_path, doctor):
    doctor()
    kit = build_workflow(tmp_path)
    set_policy(kit)

    def run_md(wf):                                            # what the real top-up leaves behind: a new COMPLETE replica run
        st = wf.state()
        r = st["steps"]["md_runs"]["runs"]["docked"]
        new = kit.case.new_run(kit.run.manifest()["protocol"], reason="replica 2")
        rj = new.manifest()
        rj["status"] = "COMPLETE"
        new.save_manifest(rj)
        sd = new.dir / "stages" / "production"
        sd.mkdir(parents=True)
        atomic_write_json({"result": {"steps": 250000}, "timestep_fs": 4.0}, sd / "production_complete.json")
        (new.dir / "big.bin").write_bytes(b"0" * 2_000_000)
        r["run_ids"].append(new.run_id)
        atomic_write_json(st, wf.state_path)
        return st["steps"]["md_runs"]["runs"]
    wf = StubWorkflow(kit, run_md=run_md)
    c, _ = ctl_for(kit, wf)
    p = next(x for x in proposals_of(kit, c) if x.action_type == ACTION_REPLICA)
    out = c.execute(p)
    assert out.status == "ok", out.reason
    assert wf.cfg["md"]["replicas"] == 2 and load_json(kit.wf_dir / "config.json")["md"]["replicas"] == 2
    assert ("run_md", 2) in wf.calls and any(k == "analyse" for k, *_ in wf.calls)
    row = wf.dec.by_stage("autonomy.replicas")[0]
    assert row["kind"] == "auto" and "自主行動" in row["why"]                      # never recorded as a human decision
    end = [r for r in c.ledger.records() if r["event"] == "exec_end"][-1]
    assert end["simulated_ps"] == pytest.approx(250000 * 4.0 / 1000.0)                # simulated time from the files
    r = end["resources"]
    assert r["storage_gb"] >= 0.002 - 1e-9 and r["wall_s"] >= 0 and r["gpu_hours"] >= 0 and "core_hours" in r
    assert end["charged_from"]["gpu_hours"] == "reported" and end["charged_from"]["storage_gb"] == "reported"
    cs = c.ledger.cost_summary()
    assert cs["simulated_ps_successful"] == pytest.approx(1000.0) and cs["resources"]["storage_gb"] >= 0.002 - 1e-9


def test_add_replica_refuses_when_the_config_already_asks_for_more_or_another_process_owns_the_workflow(tmp_path):
    kit = build_workflow(tmp_path)
    set_policy(kit)
    wf = StubWorkflow(kit)
    wf.cfg["md"]["replicas"] = 5
    c, ex = ctl_for(kit, wf)
    p = next(x for x in proposals_of(kit, c) if x.action_type == ACTION_REPLICA)
    ok, why = ex.preflight(p)
    assert not ok and "一次只補一條" in why
    out = c.execute(p)
    assert out.stop["reason"] == "cannot_start" and not [r for r in c.ledger.records() if r["event"] == "exec_start"]
    wf.cfg["md"]["replicas"] = 2
    import os
    import socket
    (kit.wf_dir / "running.json").write_text(json.dumps({"pid": os.getppid(), "host": socket.gethostname()}), encoding="utf-8")
    ok, why = ex.preflight(p)
    assert not ok and "正在執行" in why


def test_refine_adds_manual_windows_and_reopens_only_this_target(tmp_path, doctor):
    doctor()
    kit = build_workflow(tmp_path, pmf=failing_pmf(), assessed=True)
    pm = good_pmf()
    pm["quality"] = {**pm["quality"], "graph_connected": False}
    from md20.sampling.assessment import assess_pmf
    st = load_json(kit.wf_dir / "state.json")
    st["steps"]["binding"]["results"][kit.target]["assessment"] = assess_pmf(pm, has_dG=True)
    atomic_write_json(st, kit.wf_dir / "state.json")
    set_policy(kit)
    seen = {}

    def binding(wf):
        seen["popped"] = kit.target not in wf.state()["steps"]["binding"]["results"]
        import numpy as np
        np.save(kit.wf_dir / "binding" / kit.target / "windows" / "w_0.7000_cv.npy", np.linspace(0.65, 0.75, 200))
        return {kit.target: {"status": "PASS"}}
    wf = StubWorkflow(kit, binding=binding)
    c, _ = ctl_for(kit, wf)
    inp = inputs_for_workflow(kit.wf_dir)[0]
    inp.refine_plan = {"insert": [{"center": 0.7, "k": 1000.0}, {"center": 0.8, "k": 1500.0}], "extend": [], "budget_exhausted": False,
                       "unsamplable": [], "notes": []}
    p = next(x for x in c.step(inp).proposals if x.action_type == ACTION_REFINE)
    assert p.target["binding_target"] == kit.target and p.estimate["sim_ns"] is not None       # window ps × replicas, from the recorded config
    ws0 = window_ps(kit.wf_dir, kit.target)
    out = c.execute(p)
    assert out.status == "ok", out.reason
    mw = wf.cfg["binding"]["manual_windows"][kit.target]
    assert [w["center"] for w in mw] == [0.7, 0.8] and mw[1]["k"] == 1500.0
    assert seen["popped"] is True                                                             # the target is reopened, nothing else touched
    assert wf.calls[-1][0] == "binding"
    assert wf.dec.by_stage("autonomy.umbrella")[0]["kind"] == "auto"
    end = [r for r in c.ledger.records() if r["event"] == "exec_end"][-1]
    assert end["simulated_ps"] == pytest.approx(window_ps(kit.wf_dir, kit.target) - ws0) and end["simulated_ps"] > 0


def test_extend_of_umbrella_windows_has_no_public_path_and_does_not_start(tmp_path):
    kit = build_workflow(tmp_path, real_run=True)
    set_policy(kit)
    wf = StubWorkflow(kit)
    c, ex = ctl_for(kit, wf)
    inp = inputs_for_workflow(kit.wf_dir, extend_ps=20.0)[0]
    failing(inp, "window_ess")
    inp.refine_plan = {"insert": [], "extend": [{"center": 0.5}], "budget_exhausted": False, "unsamplable": [], "notes": []}
    p = next(x for x in c.step(inp).proposals if x.action_type == ACTION_EXTEND)
    out = c.execute(p)
    assert out.stop["reason"] == "cannot_start" and "沒有公開的執行介面" in out.stop["detail"]
    assert not [r for r in c.ledger.records() if r["event"] == "exec_start"]


# ======================================================================================== checkpoint fingerprint
def test_completed_run_records_a_checkpoint_fingerprint_and_the_default_validator_accepts_it(tmp_path):
    kit = build_workflow(tmp_path, real_run=True)
    fp = kit.run.manifest()["checkpoint_fingerprint"]
    state = kit.run.dir / "stages" / "production" / "production_state.xml"
    assert fp["sha256"] and fp["edge_sha256"] and fp["bytes"] == state.stat().st_size and fp["chunk_manifest"]["digest"]
    assert default_checkpoint_validator({"required": True, "path": str(state), "fingerprint": fp}) == (True, "")
    # the approved-run input the controller reads carries it, and an extend proposal is not blocked
    a = inputs_for_workflow(kit.wf_dir, extend_ps=20.0)[0].approved_run
    assert a["checkpoint"]["fingerprint"] == fp and "legacy_run" not in a["checkpoint"]


def test_changed_state_or_chunk_manifest_is_invalid(tmp_path):
    kit = build_workflow(tmp_path, real_run=True)
    fp = kit.run.manifest()["checkpoint_fingerprint"]
    sd = kit.run.dir / "stages" / "production"
    state = sd / "production_state.xml"
    cp = {"required": True, "path": str(state), "fingerprint": fp}
    prog = sd / "production_progress.json"
    saved = prog.read_text(encoding="utf-8")
    d = json.loads(saved)
    d["chunks"][0]["artifacts"]["state"]["edge_sha256"] = "0" * 64          # the chunk history was edited
    prog.write_text(json.dumps(d), encoding="utf-8")
    ok, why = default_checkpoint_validator(cp)
    assert not ok and "chunk 清單" in why
    prog.write_text(saved, encoding="utf-8")
    assert default_checkpoint_validator(cp)[0]
    data = bytearray(state.read_bytes())
    data[len(data) // 2] ^= 0xFF                                            # a flipped byte in the MIDDLE: only the full sha256 sees it
    state.write_bytes(bytes(data))
    ok, why = default_checkpoint_validator(cp)
    assert not ok and "不符" in why
    assert chunk_manifest_digest(json.loads(saved)) == fp["chunk_manifest"]["digest"]
    assert checkpoint_fingerprint(tmp_path / "nothing") is None


def test_legacy_run_without_fingerprint_escalates_and_says_why(tmp_path):
    kit = build_workflow(tmp_path, real_run=True, fingerprint=False)
    set_policy(kit)
    a = inputs_for_workflow(kit.wf_dir, extend_ps=20.0)[0].approved_run
    assert a["checkpoint"]["legacy_run"] is True and a["checkpoint"]["fingerprint"] is None
    wf = StubWorkflow(kit)
    c, _ = ctl_for(kit, wf)
    inp = inputs_for_workflow(kit.wf_dir, extend_ps=20.0)[0]
    failing(inp, "half_split")
    p = next(x for x in c.step(inp).proposals if x.action_type == ACTION_EXTEND)
    out = c.execute(p)
    assert out.stop["reason"] == "invalid_checkpoint" and "舊版" in out.stop["detail"] and "指紋" in out.stop["detail"]
    assert not [r for r in c.ledger.records() if r["event"] == "exec_start"]
    esc = c.ledger.state().scope(p.scope)["escalations"]
    assert esc and esc[0]["reason"] == "invalid_checkpoint"


def test_extend_continues_the_same_chunk_sequence_from_the_verified_checkpoint(tmp_path):
    kit = build_workflow(tmp_path, real_run=True)
    set_policy(kit)
    old_fp = kit.run.manifest()["checkpoint_fingerprint"]
    wf = StubWorkflow(kit)
    c, _ = ctl_for(kit, wf)
    inp = inputs_for_workflow(kit.wf_dir, extend_ps=20.0)[0]
    failing(inp, "half_split")
    p = next(x for x in c.step(inp).proposals if x.action_type == ACTION_EXTEND)
    assert p.target["extend_ps"] == 20.0 and p.estimate["sim_ns"] == pytest.approx(0.02)
    out = c.execute(p)
    assert out.status == "ok", out.reason
    rj = kit.run.manifest()
    assert rj["status"] == "COMPLETE" and rj["extensions"][0]["extra_ps"] == 20.0 and rj["effective_production_ps"] == 60.0
    assert rj["checkpoint_fingerprint"]["sha256"] != old_fp["sha256"]
    prog = load_json(kit.run.dir / "stages" / "production" / "production_progress.json")
    assert [x["chunk"] for x in prog["chunks"]] == [1, 2, 3, 4, 5, 6] and prog["completed_local_steps"] > 0
    assert default_checkpoint_validator({"required": True, "path": str(kit.run.dir / "stages" / "production" / "production_state.xml"),
                                         "fingerprint": rj["checkpoint_fingerprint"]})[0]
    end = [r for r in c.ledger.records() if r["event"] == "exec_end"][-1]
    assert end["simulated_ps"] == pytest.approx(20.0, rel=0.05)
    assert wf.dec.by_stage("autonomy.extend")[0]["kind"] == "auto" and ("analyse", ["docked"]) in wf.calls
    # the evidence changed (one extension done): a repeat of the old proposal is not launched again
    assert c.execute(p).status != "ok"


def test_extend_refuses_when_the_run_is_not_what_was_approved(tmp_path):
    kit = build_workflow(tmp_path, real_run=True)
    set_policy(kit)
    wf = StubWorkflow(kit)
    c, _ = ctl_for(kit, wf)
    inp = inputs_for_workflow(kit.wf_dir, extend_ps=20.0)[0]
    failing(inp, "half_split")
    p = next(x for x in c.step(inp).proposals if x.action_type == ACTION_EXTEND)
    rj = kit.run.manifest()
    rj["protocol_hash"] = "somethingelse"
    kit.run.save_manifest(rj)
    out = c.execute(p)
    assert out.status == "failed" and "證據已改變" in out.reason


def test_extend_without_a_length_chosen_by_a_person_is_blocked_not_defaulted(tmp_path):
    kit = build_workflow(tmp_path, real_run=True)
    set_policy(kit)
    c, _ = ctl_for(kit, StubWorkflow(kit))
    inp = inputs_for_workflow(kit.wf_dir)[0]                                       # no --extend-ps
    failing(inp, "half_split")
    res = c.step(inp)
    p = next(x for x in res.proposals if x.action_type == ACTION_EXTEND)
    assert res.decisions[p.idempotency_key].outcome == "blocked" and "extension_length" in res.decisions[p.idempotency_key].reason


# ======================================================================================== policy changes apply at once
def test_revoking_the_policy_stops_the_next_launch(tmp_path):
    kit = build_workflow(tmp_path, pmf=good_pmf())
    set_policy(kit)
    c, _ = ctl_for(kit, StubWorkflow(kit))
    p = next(x for x in proposals_of(kit, c) if x.action_type == ACTION_REANALYSIS)
    (kit.wf_dir / "autonomy" / "autonomy_policy.json").unlink()                   # revoked after the controller was built
    out = c.execute(p)
    assert out.status == "not_executed" and "撤銷" in out.reason
    assert not [r for r in c.ledger.records() if r["event"] == "exec_start"]


# ======================================================================================== cost inputs
def test_cost_inputs_come_from_the_doctor_benchmark_and_the_frame_size(tmp_path, doctor):
    doctor(ns_per_day=200.0, timestep_fs=4.0, n_atoms=24000)
    kit = build_workflow(tmp_path)
    inp = inputs_for_workflow(kit.wf_dir)[0]
    prod = next(s for s in kit.run.manifest()["protocol"]["stages"] if s["name"] == "production")
    scale = prod["timestep_fs"] / 4.0
    assert inp.costs["ns_per_day"] == pytest.approx(200.0 * scale) and inp.costs["device"] == "gpu"
    assert inp.costs["gb_per_ns"] == pytest.approx(1000.0 / prod["trajectory_interval_ps"] * dcd_frame_bytes(24000) / 1e9, rel=1e-4)
    assert "doctor benchmark" in inp.costs["basis_note"]
    c = Controller(tmp_path / "led")
    props = c.step(inp).proposals
    rep = next(p for p in props if p.action_type == ACTION_REPLICA)
    ns = rep.estimate["sim_ns"]
    assert ns and rep.estimate["gpu_hours"] == pytest.approx(ns / inp.costs["ns_per_day"] * 24.0, rel=1e-3)
    assert rep.estimate["storage_gb"] == pytest.approx(ns * inp.costs["gb_per_ns"], rel=1e-3)
    assert "doctor benchmark" in rep.estimate["basis"] and rep.estimate["core_hours"] is None      # not measured, not invented
    assert rep.estimate["sim_ns"] == pytest.approx(inp.costs["replica_ns"])


def test_missing_benchmark_leaves_the_estimate_unknown_which_needs_approval(tmp_path, doctor):
    (app_data_dir() / "doctor" / "doctor_report.json").unlink()                   # no doctor record on this computer
    kit = build_workflow(tmp_path)
    assert doctor_benchmark() is None
    inp = inputs_for_workflow(kit.wf_dir)[0]
    assert "ns_per_day" not in inp.costs
    set_policy(kit)
    c = Controller.for_workflow(kit.wf_dir)
    res = c.step(inp)
    rep = next(p for p in res.proposals if p.action_type == ACTION_REPLICA)
    assert rep.estimate["gpu_hours"] is None
    d = res.decisions[rep.idempotency_key]
    assert d.outcome == "needs_approval" and "無法估計" in d.reason


def test_cpu_benchmark_gives_core_hours_not_gpu_hours(tmp_path, doctor):
    doctor(platform="CPU", ns_per_day=10.0)
    kit = build_workflow(tmp_path)
    inp = inputs_for_workflow(kit.wf_dir)[0]
    assert inp.costs["device"] == "cpu" and inp.costs["cpu_threads"]
    rep = next(p for p in Controller(tmp_path / "led").step(inp).proposals if p.action_type == ACTION_REPLICA)
    assert rep.estimate["gpu_hours"] == 0.0
    assert rep.estimate["core_hours"] == pytest.approx(rep.estimate["sim_ns"] / inp.costs["ns_per_day"] * 24.0 * inp.costs["cpu_threads"], rel=1e-3)


def test_storage_estimate_is_unknown_without_size_or_interval():
    assert storage_gb_per_ns(None, 10.0) is None and storage_gb_per_ns(1000, None) is None and storage_gb_per_ns(1000, 0) is None
    assert storage_gb_per_ns(24000, 10.0) == pytest.approx(100 * dcd_frame_bytes(24000) / 1e9, rel=1e-4)


def test_legacy_result_gets_a_reanalysis_proposal_and_samples_check(tmp_path):
    kit = build_workflow(tmp_path)
    inp = inputs_for_workflow(kit.wf_dir)[0]
    assert inp.reanalysis == {"available": True} and inp.target_key == kit.target and inp.scope == f"{kit.name}/{kit.target}"
    p = next(x for x in Controller(tmp_path / "led").step(inp).proposals if x.action_type == ACTION_REANALYSIS)
    assert p.target["binding_target"] == kit.target and p.inputs["assessment_digest"]
    shutil.rmtree(kit.wf_dir / "binding")
    inp2 = inputs_for_workflow(kit.wf_dir)[0]
    assert inp2.reanalysis == {"available": False}


def test_md20_data_dir_overrides_app_data_on_every_os_and_is_not_a_licence_switch(tmp_path, monkeypatch):
    """D-148: the override that isolates tests from the real user directory works regardless of sys.platform, and it
    only moves where files live — it never makes an unsigned licence valid (verification is signature-based)."""
    import importlib
    from md20.util import paths as P
    monkeypatch.setenv("MD20_DATA_DIR", str(tmp_path / "d"))
    for plat in ("darwin", "win32", "linux"):
        monkeypatch.setattr(P.sys, "platform", plat)
        assert P.app_data_dir() == tmp_path / "d" / "MD20"
    monkeypatch.delenv("MD20_DATA_DIR")
    monkeypatch.setattr(P.sys, "platform", "darwin")
    assert P.app_data_dir() == P.Path.home() / "Library" / "Application Support" / "MD20"
