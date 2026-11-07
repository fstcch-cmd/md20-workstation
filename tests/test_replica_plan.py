"""D-131: replica plan (docs/specs/replicas.md §3-§5): default 3 everywhere, explicit values kept, time with and without a
benchmark, four languages, the CLI line, the GUI one-click choice, and topping up an old project without recomputing.
Pure Python (FakeBackend, no OpenMM)."""
import copy
import json

import pytest

from md20 import advisor
from md20.engine import make_protocol, FakeBackend, JobQueue
from md20.engine.replica_plan import (DEFAULT_REPLICAS, ANALYSIS_MIN_REPLICAS, required_replicas, configured_replicas,
                                      plan_replicas, lines, card_lines, summary_text, line_text, independence_text,
                                      single_command_text, decision_why, topup_text, seeds_for)
from md20.engine.protocol import TIERS
from md20.gui import actions as ACT
from md20.gui.logic import config_from_form
from md20.gui.views import replica_card
from md20.i18n import LANGS, pick
from md20.project import Project
from md20.workflow import Workflow, example_config, merge_human_decisions, DECISION_KEYS


def _wf(tmp_path, replicas="unset", **md):
    cfg = copy.deepcopy(example_config())
    cfg["md"].update(md)
    if replicas == "unset":
        cfg["md"].pop("replicas", None)
    else:
        cfg["md"]["replicas"] = replicas
    return Workflow(Project.create(tmp_path, "p"), cfg)


def _short_md(replicas):
    ov = {"nvt": {"length_ps": 10.0, "checkpoint_interval_ps": 5.0, "report_interval_ps": 0.2},
          "npt": {"length_ps": 10.0, "checkpoint_interval_ps": 5.0, "report_interval_ps": 0.2},
          "production": {"length_ps": 10.0, "checkpoint_interval_ps": 5.0, "report_interval_ps": 0.2}}
    return {"systems": ["apo"], "tier": "classroom", "stage_overrides": ov, "replicas": replicas}


def _factory(case, proto):
    return lambda spec, dt_: FakeBackend(timestep_fs=dt_, temperature_k=spec.temperature_k, ensemble=spec.ensemble, seed=spec.seed)


def _all_four(t):
    assert isinstance(t, tuple) and len(t) == 4 and all(isinstance(x, str) and x.strip() for x in t)
    assert len(set(t)) == 4


# ------------------------------------------------------------------------------------------- default 3 everywhere
def test_required_is_the_largest_need_and_is_three():
    assert set(ANALYSIS_MIN_REPLICAS.values()) == {3}
    assert required_replicas() == 3 == DEFAULT_REPLICAS


def test_default_is_three_everywhere():
    for tier in TIERS:
        assert make_protocol(tier).replicas == 3                      # classroom, teaching and research alike
    assert make_protocol("classroom", replicas=1).replicas == 1       # an explicit value is used
    assert example_config()["md"]["replicas"] == 3
    assert example_config(screen=True)["md"]["replicas"] == 3
    assert advisor.recommend(advisor.CaseFeatures(), "teaching", "en")["replicas"]["value"] == 3
    assert advisor.recommend(advisor.CaseFeatures(), "publication", "en")["replicas"]["value"] == 3
    assert advisor.recommended_values(advisor.CaseFeatures(), "teaching")["replicas"] == 3
    cfg = config_from_form(name="x", pdb_id="3PTB", ligands_text="BEN NC(=[NH2+])c1ccccc1")
    assert cfg["md"]["replicas"] == 3
    from md20.validation import CASES
    for case in CASES.values():
        assert case.workflow_config(tier="classroom")["md"]["replicas"] == 3


def test_queue_default_is_three_and_explicit_kept(tmp_path):
    q = JobQueue(Project.create(tmp_path, "q"))
    assert q.add("c1")["replicas"] == 3
    assert q.add("c2", replicas=1)["replicas"] == 1
    assert q.add("c3", tier="classroom", replicas=2)["replicas"] == 2
    from md20.cli import main
    assert main(["queue", "add", "--project", str(tmp_path / "q"), "--case", "c4"]) == 0
    assert JobQueue(Project(tmp_path / "q")).jobs()[-1]["replicas"] == 3


def test_not_set_means_three_set_means_as_set():
    assert configured_replicas({"md": {}}) == (3, False)
    assert configured_replicas({}) == (3, False)
    assert configured_replicas({"md": {"replicas": None}}) == (3, False)
    assert configured_replicas({"md": {"replicas": 1}}) == (1, True)
    assert configured_replicas({"md": {"replicas": 5}}) == (5, True)
    assert configured_replicas({"md": {"replicas": "2"}}) == (2, True)
    assert configured_replicas({"md": {"replicas": "abc"}}) == (3, False)


def test_run_md_uses_the_default_and_the_explicit_value(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr("md20.engine.run_replicas", lambda case, proto, fac, **k: (seen.append((proto.replicas, k["n"])) or
                        {"runs": [{"status": "COMPLETE", "run_id": f"r{i}"} for i in range(k["n"])]}))
    for rep, want in (("unset", 3), (1, 1), (5, 5)):
        wf = _wf(tmp_path / f"w{rep}", replicas=rep)
        c = wf.project.new_case("c")
        wf.run_md({"apo": {"case_id": c.case_id}}, lambda case, proto: None)
        assert seen[-1] == (want, want)


# ------------------------------------------------------------------------------------------- time
BENCH = {"ns_per_day": 240.0, "n_atoms": 24000, "timestep_fs": 4.0}


def test_eta_without_benchmark_gives_only_the_factor():
    p = plan_replicas(example_config())
    assert p["multiplier"] == 3 and p["configured"] == 3 and p["eta_hours"] is None and p["eta_basis"] is None
    for lang in LANGS:
        text = " ".join(lines(plan_replicas({"md": {}, "ligands": []}), lang))
        assert "3" in text
    assert "不猜" in pick(summary_text(plan_replicas({"md": {}})), "zh")
    assert "not guessed" in pick(summary_text(plan_replicas({"md": {}})), "en")


def test_eta_with_benchmark_scales_with_replicas_and_systems():
    cfg = {"md": {"tier": "teaching", "systems": ["apo"], "replicas": 3}, "ligands": []}
    p3 = plan_replicas(cfg, benchmark=BENCH)
    cfg1 = {"md": {**cfg["md"], "replicas": 1}, "ligands": []}
    p1 = plan_replicas(cfg1, benchmark=BENCH)
    assert p1["eta_hours"] and p3["eta_hours"] == pytest.approx(3 * p1["eta_hours"], rel=0.02)
    assert p3["eta_basis"] == "benchmark_size"
    # teaching: (0.2 + 0.5 + 10) ns at 4 fs on a 24 000-atom system at 240 ns/day, three replicas, one system
    assert p3["eta_hours"] == pytest.approx(10.7 * 3 / 240.0 * 24.0, rel=0.01)
    pa = plan_replicas(cfg, benchmark=BENCH, n_atoms=48000)             # twice the atoms: half the speed
    assert pa["eta_basis"] == "benchmark" and pa["eta_hours"] == pytest.approx(2 * p3["eta_hours"], rel=0.01)
    two = plan_replicas({"md": {**cfg["md"], "systems": ["apo", "docked_single"]},
                         "ligands": [{"name": "BEN"}, {"name": "PGA"}]}, benchmark=BENCH)
    assert two["systems"] == 3 and two["eta_hours"] == pytest.approx(3 * p3["eta_hours"], rel=0.01)
    for lang in LANGS:
        assert any(ch.isdigit() for ch in " ".join(lines(p3, lang)))
    # the speed measured for this system wins over the benchmark
    pm = plan_replicas({"md": {**cfg["md"], "ns_per_day": 100.0}, "ligands": []}, benchmark=BENCH)
    assert pm["eta_basis"] == "config" and pm["eta_hours"] == pytest.approx(10.7 * 3 / 100.0 * 24.0, rel=0.01)


# ------------------------------------------------------------------------------------------- text
@pytest.mark.parametrize("n", [1, 2, 3, 5])
def test_four_languages_complete(n):
    for bench in (None, BENCH):
        p = plan_replicas({"md": {"replicas": n}, "ligands": []}, benchmark=bench)
        q = plan_replicas({"md": {}, "ligands": []}, benchmark=bench)
        for plan in (p, q):
            _all_four(summary_text(plan)); _all_four(line_text(plan)); _all_four(independence_text(plan))
            for o in plan["options"]:
                _all_four(o["label"]); _all_four(o["note"])
            for lang in LANGS:
                assert all(x.strip() for x in lines(plan, lang)) and all(x.strip() for x in card_lines(plan, lang))
    _all_four(single_command_text())
    cg = plan_replicas({"md": {"resolution": "cg"}})
    assert cg["applicable"] is False and cg["eta_hours"] is None
    _all_four(summary_text(cg))


def test_single_replica_is_labelled_everywhere():
    p = plan_replicas({"md": {"replicas": 1}})
    assert p["single"] and p["below_required"]
    assert "單一軌跡，無法估計不確定性" in pick(line_text(p), "zh")
    assert "single trajectory" in pick(line_text(p), "en")
    assert "単一軌跡" in pick(line_text(p), "ja") and "단일 궤적" in pick(line_text(p), "ko")
    assert "單一軌跡，無法估計不確定性" in decision_why(p)


def test_options_and_independence_text():
    p = plan_replicas({"md": {}, "ligands": []})
    assert [o["id"] for o in p["options"]] == ["recommended", "single", "custom"]
    assert [o["replicas"] for o in p["options"]] == [3, 1, None]
    assert p["seeds"] == [2026, 3026, 4026] == seeds_for(3)
    z = pick(independence_text(p), "zh")
    assert "2026" in z and "3026" in z and "同一個建好的系統" in z and "各自做最小化、加熱與平衡" in z
    assert "do not branch from one equilibrated structure" in pick(independence_text(p), "en")
    # not set: the full explanation with the options; set: one line
    assert len(lines(p, "zh")) >= 5
    assert len(lines(plan_replicas({"md": {"replicas": 3}}), "zh")) == 1


def test_seed_facts_match_run_replicas():
    from md20.engine.replicas import replica_protocol
    base = make_protocol("classroom")
    seeds = [replica_protocol(base, i).stages[-1].seed for i in range(3)]
    assert seeds == seeds_for(3)


# ------------------------------------------------------------------------------------------- advisor
def test_advisor_reason_in_four_languages_and_check():
    f = advisor.CaseFeatures()
    for lang in LANGS:
        why = advisor.recommend(f, "teaching", lang)["replicas"]["why"]
        assert "3" in why and why.strip()
    raws = {l: advisor.recommend(f, "teaching", l)["replicas"]["why"] for l in LANGS}
    assert len(set(raws.values())) == 4
    vals = advisor.recommended_values(f, "teaching")
    assert not [i for i in advisor.check(vals, f, goal="teaching") if i["key"] == "replicas"]
    one = [i for i in advisor.check({**vals, "replicas": 1}, f, goal="teaching", lang="zh") if i["key"] == "replicas"]
    assert one and one[0]["level"] == "info" and one[0]["suggestion"] == 3 and "單一軌跡" in one[0]["message"]
    pub = [i for i in advisor.check({**vals, "replicas": 1}, f, goal="publication", lang="en") if i["key"] == "replicas"]
    assert pub and pub[0]["level"] == "warning"
    two = [i for i in advisor.check({**vals, "replicas": 2}, f, goal="teaching", lang="en") if i["key"] == "replicas"]
    assert two and "fewer than the 3" in two[0]["message"]
    for lang in LANGS:
        assert advisor.check({**vals, "replicas": 1}, f, goal="teaching", lang=lang)[0]["message"].strip()


# ------------------------------------------------------------------------------------------- CLI
def test_cli_pipeline_prints_the_plan_and_does_not_stop(tmp_path, capsys, monkeypatch):
    from md20 import cli
    cfg = example_config()
    cfg["md"].pop("replicas")                    # not set: the full plan
    path = tmp_path / "c.json"; path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr("md20.workflow.Workflow.run", lambda self, *a, **k: {"status": "PAUSED", "state": {}})
    monkeypatch.setattr("md20.env.choose_platform", lambda *a, **k: type("Plat", (), {"name": "FAKE", "properties": {}})())
    rc = cli.main(["--dir", str(tmp_path / "proj"), "pipeline", "run", str(path), "--project", "P", "--fake"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "每個系統要跑 3 條獨立重複" in out and "計算時間約為 1 條的 3 倍" in out and "不猜時間" in out
    assert "照建議" in out and "改為 1 條" in out and "自訂條數" in out and "2026" in out
    # set in the config: one line
    cfg["md"]["replicas"] = 1
    path.write_text(json.dumps(cfg), encoding="utf-8")
    rc = cli.main(["--dir", str(tmp_path / "proj2"), "pipeline", "run", str(path), "--project", "P", "--fake"])
    out = capsys.readouterr().out
    assert rc == 0 and "重複：每個系統 1 條（設定指定）" in out and "單一軌跡，無法估計不確定性" in out
    assert "照建議" not in out and out.count("重複：") == 1


def test_cli_run_says_it_is_one_trajectory(tmp_path, capsys):
    from md20 import cli
    p = Project.create(tmp_path, "pr"); c = p.new_case("c")
    rc = cli.main(["run", "--project", str(p.dir), "--case", c.case_id, "--tier", "classroom", "--ns", "0.01", "--fake"])
    out = capsys.readouterr().out
    assert "只跑 1 條軌跡" in out and "md20 pipeline run" in out and "md20 queue add --replicas 3" in out
    assert rc in (0, 3)
    run = next(iter(c.runs()))
    assert run.manifest()["protocol"]["replicas"] == 1            # the stored protocol tells the truth


# ------------------------------------------------------------------------------------------- DecisionLog
def test_default_and_explicit_are_recorded_once(tmp_path):
    wf = _wf(tmp_path)
    wf.record_replica_plan(); wf.record_replica_plan()
    rows = [r for r in wf.dec.read() if r["stage"] == "workflow.replicas"]
    assert len(rows) == 1 and rows[0]["choice"] == 3 and rows[0]["kind"] == "auto" and "採用預設 3 條" in rows[0]["why"]
    assert wf.state()["replica_plan"]["configured"] == 3
    wf2 = _wf(tmp_path / "b", replicas=1)
    wf2.record_replica_plan()
    r = [x for x in wf2.dec.read() if x["stage"] == "workflow.replicas"][0]
    assert r["kind"] == "human" and "單一軌跡，無法估計不確定性" in r["why"]


# ------------------------------------------------------------------------------------------- GUI one click
def test_gui_one_click_writes_config_and_decision(tmp_path):
    wf = _wf(tmp_path)
    card = replica_card(wf, lang="en")
    assert card["show"] and card["current"] == 3 and [o["id"] for o in card["options"]] == ["recommended", "single", "custom"]
    out = ACT.set_replicas(wf, 1)
    assert out["replicas"] == 1 and out["previous"] == 3
    assert json.loads((wf.dir / "config.json").read_text(encoding="utf-8"))["md"]["replicas"] == 1
    assert wf.cfg["md"]["replicas"] == 1
    row = [r for r in wf.dec.read() if r["stage"] == "gui.replicas"][-1]
    assert row["kind"] == "human" and row["choice"] == 1 and "1 條" in row["why"] and row["evidence"]["patch"][0]["path"] == ["md", "replicas"]
    assert replica_card(wf, lang="zh")["lines"][0].startswith("重複：每個系統 1 條（設定指定）")
    ACT.set_replicas(wf, 3)
    assert wf.cfg["md"]["replicas"] == 3
    with pytest.raises(ValueError):
        ACT.set_replicas(wf, 0)
    with pytest.raises(ValueError):
        ACT.set_replicas(wf, "x")
    for lang in LANGS:
        c = replica_card(wf, lang=lang)
        assert c["title"] and all(o["label"] and o["note"] for o in c["options"])


def test_replicas_is_a_carried_decision_key():
    assert ("md", "replicas") in DECISION_KEYS
    new = {"md": {"tier": "teaching"}}
    merged, carried = merge_human_decisions(new, {"md": {"replicas": 1}})
    assert merged["md"]["replicas"] == 1 and "md.replicas" in carried
    merged, carried = merge_human_decisions({"md": {"replicas": 3}}, {"md": {"replicas": 1}})     # the file in hand wins
    assert merged["md"]["replicas"] == 3 and not carried


# ------------------------------------------------------------------------------------------- old project: top up
def test_old_project_top_up_runs_only_the_missing_replicas(tmp_path):
    wf = _wf(tmp_path)
    wf.cfg["md"] = _short_md(1)
    wf.cfg = copy.deepcopy(wf.cfg)
    case = wf.project.new_case("c")
    built = {"apo": {"case_id": case.case_id}}
    runs = wf.run_md(built, _factory)
    assert runs["apo"]["status"] == "COMPLETE" and len(runs["apo"]["run_ids"]) == 1
    first = runs["apo"]["run_ids"][0]
    run0 = next(iter(case.runs()))
    started = run0.manifest()
    stamp = (run0.dir / "run.json").stat().st_mtime_ns
    wf._mark("analysis", x=1); wf._mark("report", path="r.html")
    assert wf.completed_replicas() == {"apo": 1}
    # the card offers the top-up even though the config says 1 (an old project)
    card = replica_card(wf, lang="zh")
    assert card["show"] and card["plan"]["topup_to_required"] == 2
    rec = next(o for o in card["options"] if o["id"] == "recommended")
    assert rec["label"] == "補跑到 3 條" and "只補跑缺的 2 條" in rec["note"]
    out = ACT.set_replicas(wf, 3)
    assert out["topup_runs"] == 2 and set(out["invalidated"]) == {"analysis", "report"}
    assert wf._done("md_runs") is not None                     # the MD step stays: nothing finished is dropped
    runs = wf.run_md(built, _factory)
    assert runs["apo"]["status"] == "COMPLETE" and len(runs["apo"]["run_ids"]) == 3
    assert runs["apo"]["run_ids"][0] == first
    assert len(list(case.runs())) == 3
    assert (run0.dir / "run.json").stat().st_mtime_ns == stamp          # the existing replica was not run again
    seeds = sorted(r.manifest()["protocol"]["stages"][-1]["seed"] for r in case.runs())
    assert seeds == [2026, 3026, 4026]
    assert any(r["choice"] == "top up 1 -> 3" for r in wf.dec.read())
    assert wf.completed_replicas() == {"apo": 3}
    assert not replica_card(wf, lang="en")["plan"]["topup_to_required"]
    # asking again changes nothing
    again = wf.run_md(built, _factory)
    assert len(again["apo"]["run_ids"]) == 3 and len(list(case.runs())) == 3


def test_top_up_text_and_option_when_config_already_asks_for_more(tmp_path):
    p = plan_replicas({"md": {"replicas": 3}}, done={"apo": 1, "docked_BEN": 3})
    assert p["topup_runs"] == 2 and p["missing"] == {"apo": 2}
    assert [o["id"] for o in p["options"]] == ["recommended", "single", "custom", "topup"]
    _all_four(topup_text(p))
    assert "補跑缺的 2 條" in pick(topup_text(p), "zh") and "apo: 1/3" in pick(topup_text(p), "en")
    assert plan_replicas({"md": {"replicas": 3}}, done={"apo": 3})["topup_runs"] == 0
