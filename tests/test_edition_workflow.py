"""D-181: the workflow, the command line and the one-click gate obey the edition.

Lite is simulated the only way the contract allows: by patching `md20.edition.current` (and `build_edition`,
`licence_features`).  No environment variable, setting or flag changes the edition.  Pure Python: the engine is a stub, the
builds are stand-ins that write the manifest a real build writes."""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from md20 import edition as E
from md20.project.store import Project
from md20.util import load_json
from md20.workflow import (DECISION_KEYS, Workflow, WorkflowBlocked, example_config, merge_human_decisions,
                           protein_residues_in_pdb)

ROOT = Path(__file__).resolve().parents[1]
LANGS = ("zh", "en", "ja", "ko")
PLATFORM = SimpleNamespace(name="CPU", properties={}, device_name="")
RAN = {"status": "COMPLETE", "ran": True}


# ------------------------------------------------------------------------------------------------ helpers
@pytest.fixture
def lite(monkeypatch):
    monkeypatch.setattr(E, "current", lambda **kw: E.LITE)
    monkeypatch.setattr(E, "build_edition", lambda marker=None: E.LITE)
    monkeypatch.setattr(E, "licence_features", lambda: ["lite", "binding", "hts"])


@pytest.fixture
def stub_run(monkeypatch):
    """Replace the body of the workflow (receptor, docking, MD ...) by a marker; the entrance check stays real."""
    calls = []

    def _run(self, make_factory, platform, **kw):
        calls.append(1)
        return dict(RAN)
    monkeypatch.setattr(Workflow, "_run", _run)
    return calls


def _cfg(**top):
    cfg = copy.deepcopy(example_config())
    cfg.update(top)
    return cfg


def _wf(tmp_path, cfg=None, name="p") -> Workflow:
    root = Path(tmp_path) / name
    proj = Project(root) if (root / "project.json").is_file() else Project.create(tmp_path, name)
    return Workflow(proj, cfg if cfg is not None else _cfg())


def _go(wf):
    return wf.run(lambda case, proto: None, PLATFORM)


def _saved(wf) -> dict:
    """The workflow's own config.json without the provenance stamp."""
    return {k: v for k, v in load_json(wf.dir / "config.json").items() if k != "_md20"}


def _edition_rows(wf):
    return [r for r in wf.dec.read() if str(r.get("stage", "")).startswith("edition.")]


def _hit_codes(wf):
    return [h["code"] for h in (wf.state().get("edition") or {}).get("hits", [])]


def _accepted(cfg=None):
    cfg = cfg if cfg is not None else _cfg()
    cfg["edition"] = {"accept_clamp": True}
    return cfg


# ------------------------------------------------------------------------------------------------ complete edition unchanged
def test_complete_edition_is_untouched(tmp_path, stub_run):
    cfg = _cfg(ligands=[{"name": f"L{i}", "smiles": "C"} for i in range(6)])
    cfg["md"].update(tier="research", replicas=7, production_ns=500.0)
    wf = _wf(tmp_path, copy.deepcopy(cfg))
    assert E.current() == E.FULL
    assert _go(wf) == RAN
    st = wf.state()
    assert "edition" not in st and E.STEP not in st["steps"]
    assert _saved(wf) == cfg                       # not one value changed
    assert _edition_rows(wf) == []
    assert wf.cfg["md"]["replicas"] == 7


def test_complete_edition_still_defaults_to_three_replicas(tmp_path):
    cfg = _cfg()
    cfg["md"].pop("replicas")
    wf = _wf(tmp_path, cfg)
    assert wf._edition_hits(wf.cfg) == []
    from md20.engine.replica_plan import configured_replicas
    assert configured_replicas(wf.cfg) == (3, False)


def test_complete_edition_gives_no_system_or_library_stop(tmp_path):
    wf = _wf(tmp_path)
    wf._edition_check_library(10_000)
    assert E.check_system(n_atoms=10**7, n_protein_residues=10**5) == []
    assert "edition" not in wf.state()


# ------------------------------------------------------------------------------------------------ the entrance
def test_licence_is_checked_before_the_edition(tmp_path, lite, stub_run, license_env):
    from md20.util.license import LicenseRequired
    wf = _wf(tmp_path)
    license_env.clear()
    with pytest.raises(LicenseRequired):
        _go(wf)
    assert "edition" not in wf.state() and stub_run == []


def test_lite_entrance_blocks_with_the_edition_gate(tmp_path, lite, stub_run):
    wf = _wf(tmp_path)
    before = _saved(wf)
    with pytest.raises(WorkflowBlocked, match="Lite"):
        _go(wf)
    assert stub_run == []                                                  # nothing of the workflow ran
    st = wf.state()
    step = st["steps"][E.STEP]
    assert step["status"] == "NEEDS_HUMAN"
    gate = step["gates"][0]
    assert gate["name"] == E.GATE_NAME and gate["status"] == "NEEDS_HUMAN"
    assert gate["options"][0] == E.OPT_CLAMP[0]                            # the reduction is offered first
    assert {"md.replicas", "binding.max_windows", "binding.refine_rounds"} <= set(_hit_codes(wf))
    rec = st["edition"]
    assert set(rec) == {"edition", "hits", "clamped", "at"} and rec["edition"] == E.LITE and rec["clamped"] == []
    assert set(rec["hits"][0]) >= {"code", "kind", "value", "limit", "feature", "can_clamp", "text"}
    assert set(rec["hits"][0]["text"]) == set(LANGS)
    assert _saved(wf) == before                    # a block changes nothing
    assert not (wf.dir / "running.json").exists()                          # the lock is released
    assert _edition_rows(wf) == []


def test_lite_default_replicas_are_a_hit_too(tmp_path, lite, stub_run):
    """md.replicas left out means 3 (D-131), which is above the Lite limit of 1."""
    cfg = _cfg()
    cfg["md"].pop("replicas")
    cfg["binding"] = {"enabled": False, "ligands": [], "config": {}}
    wf = _wf(tmp_path, cfg)
    with pytest.raises(WorkflowBlocked):
        _go(wf)
    hit = next(h for h in wf.state()["edition"]["hits"] if h["code"] == "md.replicas")
    assert (hit["value"], hit["limit"], hit["can_clamp"]) == (3, 1, True)
    wf = _wf(tmp_path, _accepted(copy.deepcopy(cfg)))
    assert _go(wf) == RAN
    assert _saved(wf)["md"]["replicas"] == 1        # the Lite number is explicit now


def test_lite_config_inside_the_limits_is_not_stopped(tmp_path, lite, stub_run):
    cfg = _cfg()
    cfg["md"]["replicas"] = 1
    cfg["binding"] = {"enabled": False, "ligands": [], "config": {}}
    wf = _wf(tmp_path, cfg)
    assert _go(wf) == RAN
    assert "edition" not in wf.state() and E.STEP not in wf.state()["steps"]


def test_accept_reduces_logs_persists_and_continues(tmp_path, lite, stub_run):
    wf = _wf(tmp_path, _accepted())
    assert _go(wf) == RAN
    cfg = _saved(wf)
    assert cfg["md"]["replicas"] == 1
    assert cfg["binding"]["config"]["max_windows"] == 12 and cfg["binding"]["config"]["max_refine_rounds"] == 0
    assert cfg["edition"] == {"accept_clamp": True}                       # the decision stays
    assert cfg["md"]["tier"] == "teaching" and cfg["ligands"] == example_config()["ligands"]    # only sizes change
    assert E.check_config(cfg) == [] and wf.cfg["md"]["replicas"] == 1     # config in memory is the reduced one
    st = wf.state()
    assert E.STEP not in st["steps"]
    keys = {c["key"] for c in st["edition"]["clamped"]}
    assert keys == {"md.replicas", "binding.config.max_windows", "binding.config.max_refine_rounds"}
    assert {c["code"] for c in st["edition"]["clamped"]} == {"md.replicas", "binding.max_windows", "binding.refine_rounds"}
    rows = _edition_rows(wf)
    assert {r["stage"] for r in rows} == {"edition.clamp"} and {r["what"] for r in rows} == keys
    assert all(r["kind"] == "auto_fixed" and "edition.accept_clamp" in r["why"] and "不刪配體" in r["why"] for r in rows)
    assert any("1" in r["choice"] and "3" in r["choice"] for r in rows if r["what"] == "md.replicas")


def test_accept_is_idempotent_on_resume_and_on_rerun_from_the_original_file(tmp_path, lite, stub_run):
    wf = _wf(tmp_path, _accepted())
    _go(wf)
    rows, rec = _edition_rows(wf), wf.state()["edition"]
    # 1. resume from the workflow's own (reduced) config.json
    wf2 = Workflow.open(wf.project, wf.name)
    assert _go(wf2) == RAN
    assert _edition_rows(wf2) == rows and wf2.state()["edition"] == rec
    # 2. `pipeline run` again with the student's original file: only the decision is carried, the sizes are reduced again
    original = _cfg()
    merged, carried = merge_human_decisions(original, _saved(wf))
    assert "edition.accept_clamp" in carried
    wf3 = Workflow(wf.project, merged)
    assert _go(wf3) == RAN
    assert _saved(wf3)["md"]["replicas"] == 1
    assert len(_edition_rows(wf3)) == len(rows)                            # the same reductions are not logged twice
    assert [c for c in wf3.state()["edition"]["clamped"]] == rec["clamped"]


def test_a_person_who_fixes_the_config_clears_the_stop(tmp_path, lite, stub_run):
    wf = _wf(tmp_path)
    with pytest.raises(WorkflowBlocked):
        _go(wf)
    cfg = _saved(wf)
    cfg["md"]["replicas"] = 1
    cfg["binding"]["config"] = {"max_windows": 12, "max_refine_rounds": 0}
    wf2 = Workflow(wf.project, cfg)
    assert _go(wf2) == RAN
    st = wf2.state()
    assert E.STEP not in st["steps"]                                       # no stale NEEDS_HUMAN
    assert "md.replicas" in _hit_codes(wf2)                                # the hits that were met stay on record
    assert st["edition"]["clamped"] == []                                  # and nothing was reduced for the person


def test_accepting_does_not_redo_finished_steps(tmp_path, lite, stub_run):
    from md20.gui.actions import apply_gate_action, gate_actions
    wf = _wf(tmp_path)
    st = wf.state()
    st["steps"]["receptor_input"] = {"status": "PASS", "path": "x"}
    from md20.util import atomic_write_json
    atomic_write_json(st, wf.state_path)
    with pytest.raises(WorkflowBlocked):
        _go(wf)
    gate = wf.state()["steps"][E.STEP]["gates"][0]
    acts, manual = gate_actions(gate, step=E.STEP)
    assert len(acts) == 1 and acts[0]["patch"] == [{"path": ["edition", "accept_clamp"], "value": True}]
    assert acts[0]["from_step"] == E.STEP and not acts[0]["needs_text"]
    assert set(manual) == {E.OPT_EDIT[0], E.OPT_OPEN_IN_FULL[0], E.OPT_LEARN[0]}
    out = apply_gate_action(wf, acts[0])
    assert out["invalidated"] == [E.STEP]                                  # only the stop is lifted
    st = wf.state()["steps"]
    assert st["receptor_input"]["status"] == "PASS" and E.STEP not in st
    assert _saved(wf)["edition"]["accept_clamp"] is True
    assert any(r["stage"] == "gui.gate" and r["kind"] == "human" for r in wf.dec.read())
    assert _go(Workflow.open(wf.project, wf.name)) == RAN                  # one click and the run goes on


# ------------------------------------------------------------------------------------------------ what cannot be reduced
FEATURE_CFGS = {
    "feature.membrane": lambda c: c["md"].update(membrane={"type": "protein"}),
    "feature.cg": lambda c: c["md"].update(resolution="cg"),
    "feature.long_run": lambda c: c["md"].update(long_run={"solute_only": True}),
    "feature.autonomy": lambda c: c.update(autonomy={"policy": "x"}),
    "feature.fold": lambda c: c["ligands"].append({"name": "PEP", "sequence": "ACDEFGHIK", "fold": True}),
}


@pytest.mark.parametrize("code", sorted(FEATURE_CFGS))
def test_a_complete_only_feature_blocks_even_when_the_reduction_is_accepted(tmp_path, lite, stub_run, code):
    cfg = _accepted()
    FEATURE_CFGS[code](cfg)
    wf = _wf(tmp_path, cfg)
    with pytest.raises(WorkflowBlocked):
        _go(wf)
    assert stub_run == []
    gate = wf.state()["steps"][E.STEP]["gates"][0]
    assert [h["code"] for h in gate["evidence"]["hits"]] == [code]         # only what cannot be reduced is left to decide
    assert E.OPT_CLAMP[0] not in gate["options"]                           # a button that does nothing is not offered
    saved = _saved(wf)
    assert saved["md"]["replicas"] == 1                                    # the sizes were reduced ...
    for k, v in (cfg["md"].items()):
        if k in ("membrane", "resolution", "long_run"):
            assert saved["md"][k] == v                                      # ... and nothing was removed for the person
    assert len(saved["ligands"]) == len(cfg["ligands"])
    assert code in _hit_codes(wf) and "md.replicas" in _hit_codes(wf)
    assert {c["key"] for c in wf.state()["edition"]["clamped"]} >= {"md.replicas"}


def test_more_ligands_than_the_edition_takes_are_never_dropped(tmp_path, lite, stub_run):
    cfg = _accepted()
    cfg["ligands"] = [{"name": f"L{i}", "smiles": "C"} for i in range(3)]
    wf = _wf(tmp_path, cfg)
    with pytest.raises(WorkflowBlocked, match="3"):
        _go(wf)
    gate = wf.state()["steps"][E.STEP]["gates"][0]
    assert [h["code"] for h in gate["evidence"]["hits"]] == ["ligands.count"]
    assert (gate["evidence"]["hits"][0]["value"], gate["evidence"]["hits"][0]["limit"]) == (3, 2)
    assert len(_saved(wf)["ligands"]) == 3
    # the person removes one ligand and the run goes on
    cfg2 = _saved(wf)
    cfg2["ligands"] = cfg2["ligands"][:2]
    assert _go(Workflow(wf.project, cfg2)) == RAN
    assert E.STEP not in wf.state()["steps"]


# ------------------------------------------------------------------------------------------------ the library
def _library_wf(tmp_path, n_rows, **screen):
    lib = tmp_path / "lib.csv"
    lib.write_text("name,sdf\n" + "".join(f"c{i:02d},c{i:02d}.sdf\n" for i in range(n_rows)), encoding="utf-8")
    for i in range(n_rows):
        (tmp_path / f"c{i:02d}.sdf").write_text("\n  fake\n\n  1  0  0  0  0  0  0  0  0  0999 V2000\n    0.0000    0.0000    0.0000 C   0  0\nM  END\n$$$$\n")
    cfg = _cfg(screen={"library": str(lib), "select": [], **screen})
    cfg["receptor"] = {"file": str(tmp_path / "rec.pdb")}
    return _wf(tmp_path, cfg)


@pytest.fixture
def pure_library(monkeypatch):
    import md20.docking.library as lib
    monkeypatch.setattr(lib, "_rdkit_available", lambda: False)


def test_library_over_the_limit_stops_before_any_download(tmp_path, lite, pure_library, monkeypatch):
    import md20.docking.library as lib

    def no_download(*a, **k):
        raise AssertionError("a 3D structure was fetched for a library that is over the limit")
    monkeypatch.setattr(lib, "resolve_library", no_download)
    wf = _library_wf(tmp_path, 11)
    with pytest.raises(WorkflowBlocked, match="11"):
        wf.run_screen_library()
    st = wf.state()
    assert st["steps"][E.STEP]["gates"][0]["name"] == E.GATE_NAME
    hit = st["edition"]["hits"][0]
    assert (hit["code"], hit["value"], hit["limit"], hit["can_clamp"]) == ("screen.compounds", 11, 10, False)
    assert E.OPT_CLAMP[0] not in st["steps"][E.STEP]["gates"][0]["options"]
    assert "screen_library" not in st["steps"]


def test_library_at_the_limit_goes_on_and_rows_are_counted_before_filters(tmp_path, lite, pure_library):
    filters = {"min_heavy_atoms": 99}                                      # filters cannot be used to get under the limit
    wf = _library_wf(tmp_path, 10, filters=filters)
    assert len(wf.run_screen_library()["entries"]) == 10 and "edition" not in wf.state()
    (tmp_path / "b").mkdir()
    wf = _library_wf(tmp_path / "b", 11, filters=filters)
    with pytest.raises(WorkflowBlocked):
        wf.run_screen_library()


def test_a_library_read_in_the_complete_edition_is_judged_again_in_lite(tmp_path, pure_library, monkeypatch):
    wf = _library_wf(tmp_path, 12)
    assert len(wf.run_screen_library()["entries"]) == 12                  # complete edition: no limit
    monkeypatch.setattr(E, "current", lambda **kw: E.LITE)
    wf2 = Workflow(wf.project, wf.cfg)
    with pytest.raises(WorkflowBlocked):
        wf2.run_screen_library()                                          # the step is cached; the limit still applies
    assert wf2.state()["edition"]["hits"][0]["code"] == "screen.compounds"


def test_screened_picks_plus_explicit_ligands_must_fit(tmp_path, lite, monkeypatch):
    wf = _library_wf(tmp_path, 3)
    merged = [{"name": f"L{i}", "smiles": "C"} for i in range(4)]
    monkeypatch.setattr(Workflow, "run_screen_library", lambda self, progress_cb=None: {"entries": {}})
    monkeypatch.setattr(Workflow, "run_screen_docking", lambda self, *a, **k: {"entries": {}})
    monkeypatch.setattr(Workflow, "screen_selection", lambda self, man, res: merged)
    with pytest.raises(WorkflowBlocked):
        wf.apply_screen(Path("c.pdb"), Path("r.pdb"))
    assert [h["code"] for h in wf.state()["edition"]["hits"]] == ["ligands.count"]
    assert len(merged) == 4                                                # nothing was dropped


# ------------------------------------------------------------------------------------------------ the built system
def _builder(monkeypatch, assembly: dict, calls=None):
    """Stand-in for `_build_one`: writes what a real build writes (build_manifest.json with an assembly record)."""
    def fake(self, case, raw, names, picks, *, screen=False):
        if calls is not None:
            calls.append(case.case_id)
        s = {"status": "PASS", "assembly": dict(assembly)}
        (case.build_dir).mkdir(parents=True, exist_ok=True)
        (case.build_dir / "build_manifest.json").write_text(json.dumps(s), encoding="utf-8")
        return s, {}
    monkeypatch.setattr(Workflow, "_build_one", fake)


SEL = {"mode": "none", "ligands": {}}


def _built_wf(tmp_path):
    cfg = _cfg()
    cfg["md"]["systems"] = ["apo"]
    return _wf(tmp_path, cfg)


@pytest.mark.parametrize("asm,code,value,limit", [
    ({"n_atoms": 30_001, "solvent": "explicit", "n_protein_residues": 250}, "system.atoms", 30_001, 30_000),
    ({"n_atoms": 20_000, "solvent": "explicit", "n_protein_residues": 401}, "system.residues", 401, 400),
    ({"n_atoms": 6_001, "solvent": "gbn2", "n_protein_residues": 250}, "system.atoms", 6_001, 6_000),
])
def test_a_built_system_over_the_limit_stops_with_the_edition_gate(tmp_path, lite, monkeypatch, asm, code, value, limit):
    _builder(monkeypatch, asm)
    wf = _built_wf(tmp_path)
    with pytest.raises(WorkflowBlocked, match="Lite"):
        wf.build_cases(Path("raw.pdb"), SEL)
    st = wf.state()
    assert st["steps"][E.STEP]["status"] == "NEEDS_HUMAN"
    hit = next(h for h in st["edition"]["hits"] if h["code"] == code)
    assert (hit["value"], hit["limit"], hit["can_clamp"]) == (value, limit, False)
    assert st["steps"][E.STEP]["gates"][0]["name"] == E.GATE_NAME
    assert E.OPT_CLAMP[0] not in st["steps"][E.STEP]["gates"][0]["options"]
    case = st["steps"]["md_cases"]["cases"]["apo"]
    assert case["status"] == "NEEDS_HUMAN" and case["blocking"] == "edition"      # built again next time, never skipped


def test_the_same_counts_are_fine_in_the_complete_edition_and_in_other_solvents(tmp_path, monkeypatch):
    _builder(monkeypatch, {"n_atoms": 80_000, "solvent": "explicit", "n_protein_residues": 900})
    wf = _built_wf(tmp_path)
    assert wf.build_cases(Path("raw.pdb"), SEL)["apo"]["status"] == "PASS"
    assert "edition" not in wf.state()


def test_a_system_at_the_limits_passes_in_lite(tmp_path, lite, monkeypatch):
    _builder(monkeypatch, {"n_atoms": 30_000, "solvent": "explicit", "n_protein_residues": 400})
    wf = _built_wf(tmp_path)
    assert wf.build_cases(Path("raw.pdb"), SEL)["apo"]["status"] == "PASS"
    assert "edition" not in wf.state()
    assert E.check_system(n_atoms=7_000, n_protein_residues=100, solvent="explicit") == []
    assert [h.code for h in E.check_system(n_atoms=7_000, n_protein_residues=100, solvent="gbn2")] == ["system.atoms"]


def test_an_oversized_case_is_rebuilt_and_checked_again_after_the_settings_change(tmp_path, lite, monkeypatch):
    calls = []
    _builder(monkeypatch, {"n_atoms": 31_000, "solvent": "explicit", "n_protein_residues": 300}, calls)
    wf = _built_wf(tmp_path)
    with pytest.raises(WorkflowBlocked):
        wf.build_cases(Path("raw.pdb"), SEL)
    _builder(monkeypatch, {"n_atoms": 20_000, "solvent": "explicit", "n_protein_residues": 300}, calls)    # e.g. a smaller box
    built = Workflow(wf.project, wf.cfg).build_cases(Path("raw.pdb"), SEL)
    assert len(calls) == 2 and built["apo"]["status"] == "PASS"


def test_a_case_built_before_is_checked_again_not_skipped(tmp_path, monkeypatch):
    """Built in the complete edition (no limit), opened in Lite: the check reads the case's own build manifest."""
    _builder(monkeypatch, {"n_atoms": 45_000, "solvent": "explicit", "n_protein_residues": 300})
    wf = _built_wf(tmp_path)
    wf.build_cases(Path("raw.pdb"), SEL)
    monkeypatch.setattr(E, "current", lambda **kw: E.LITE)
    monkeypatch.setattr(Workflow, "_build_one", lambda *a, **k: pytest.fail("a PASS case must not be rebuilt just to be checked"))
    with pytest.raises(WorkflowBlocked):
        Workflow(wf.project, wf.cfg).build_cases(Path("raw.pdb"), SEL)
    assert wf.state()["edition"]["hits"][0]["code"] == "system.atoms"


def test_a_manifest_without_the_residue_count_gets_it_from_the_topology(tmp_path, lite, monkeypatch):
    top = tmp_path / "topology.pdb"
    lines = []
    for i in range(1, 402):                                               # 401 ALA residues of 2 atoms, then water
        lines.append(f"ATOM  {2 * i - 1:5d}  N   ALA A{i:4d}       0.000   0.000   0.000  1.00  0.00           N")
        lines.append(f"ATOM  {2 * i:5d}  CA  ALA A{i:4d}       0.000   0.000   0.000  1.00  0.00           C")
    lines.append("HETATM 9999  O   HOH B   1       0.000   0.000   0.000  1.00  0.00           O")
    top.write_text("\n".join(lines) + "\nEND\n")
    assert protein_residues_in_pdb(top, 802) == 401 and protein_residues_in_pdb(top, 20) == 10
    assert protein_residues_in_pdb(tmp_path / "missing.pdb", 5) is None
    _builder(monkeypatch, {"n_atoms": 10_000, "solvent": "explicit", "n_protein_atoms": 802, "topology_pdb": str(top)})
    wf = _built_wf(tmp_path)
    with pytest.raises(WorkflowBlocked):
        wf.build_cases(Path("raw.pdb"), SEL)
    assert [h["code"] for h in wf.state()["edition"]["hits"]] == ["system.residues"]


def test_the_build_summary_exposes_the_protein_residue_count():
    from md20.build.assemble import BuildResult, SEQUENCE_RESNAMES
    assert BuildResult(status="PASS").to_dict()["n_protein_residues"] == 0
    assert "ALA" in SEQUENCE_RESNAMES and "HIE" in SEQUENCE_RESNAMES
    assert not ({"ACE", "NME", "HOH", "ZN", "NA"} & SEQUENCE_RESNAMES)
    src = (ROOT / "md20" / "build" / "assemble.py").read_text(encoding="utf-8")
    assert "n_protein_residues=n_protein_res" in src


# ------------------------------------------------------------------------------------------------ the safety net
def test_an_upgrade_required_that_escapes_becomes_a_stop_not_a_traceback(tmp_path, lite, monkeypatch):
    def boom(self, make_factory, platform, **kw):
        raise E.UpgradeRequired("membrane")
    monkeypatch.setattr(Workflow, "_run", boom)
    wf = _wf(tmp_path, {**_accepted(), "md": {**_cfg()["md"], "replicas": 1}, "binding": {"enabled": False}})
    with pytest.raises(WorkflowBlocked, match="膜系統"):
        _go(wf)
    step = wf.state()["steps"][E.STEP]
    assert step["status"] == "NEEDS_HUMAN" and step["gates"][0]["name"] == E.GATE_NAME
    assert "HCC Lab" in step["gates"][0]["explanation"]
    assert step["gates"][0]["evidence"]["texts"] == [E.upgrade_text("membrane", l) for l in LANGS]
    assert wf.state()["edition"]["hits"][0]["code"] == "feature.membrane"
    assert not (wf.dir / "running.json").exists()


def test_an_upgrade_required_for_an_unlisted_name_is_a_stop_too(tmp_path, lite, monkeypatch):
    monkeypatch.setattr(Workflow, "_run", lambda self, *a, **k: (_ for _ in ()).throw(E.UpgradeRequired("", "something new")))
    wf = _wf(tmp_path, {**_accepted(), "md": {**_cfg()["md"], "replicas": 1}, "binding": {"enabled": False}})
    with pytest.raises(WorkflowBlocked, match="something new"):
        _go(wf)
    assert wf.state()["steps"][E.STEP]["status"] == "NEEDS_HUMAN"


def _lite_longrun_stub(monkeypatch):
    """What a Lite package has in place of engine/longrun.py: names that exist, calls that raise."""
    mod = types.ModuleType("md20.engine.longrun")

    def __getattr__(name):
        def f(*a, **k):
            raise E.UpgradeRequired("long_run")
        return f
    mod.__getattr__ = __getattr__
    monkeypatch.setitem(sys.modules, "md20.engine.longrun", mod)


def test_reduced_config_never_takes_replica_planning_beyond_one_or_the_long_run_planner(tmp_path, lite, monkeypatch):
    _lite_longrun_stub(monkeypatch)
    wf = _wf(tmp_path, _accepted())
    monkeypatch.setattr(Workflow, "_run", lambda self, *a, **k: RAN)
    _go(wf)                                                               # reduces the config
    from md20.engine.replica_plan import configured_replicas
    assert configured_replicas(wf.cfg) == (1, True)
    plan = wf.replica_plan()
    assert plan["configured"] == 1
    # run_md with a reduced config: one replica per system, and the long-run planner (a stub here) is not called
    asked = []
    case = wf.project.new_case("p_apo")
    import md20.engine as engine

    def fake_run_replicas(case_, proto, factory, *, n, **kw):
        asked.append((n, proto.replicas))
        return {"runs": [{"run_id": "r1", "status": "COMPLETE"}]}
    monkeypatch.setattr(engine, "run_replicas", fake_run_replicas)
    runs = wf.run_md({"apo": {"case_id": case.case_id}}, lambda c, p: None)
    assert asked == [(1, 1)] and runs["apo"]["status"] == "COMPLETE"
    assert wf.state()["replica_plan"]["configured"] == 1


def test_a_longer_production_than_the_edition_allows_raises_instead_of_planning(tmp_path, lite, monkeypatch):
    _lite_longrun_stub(monkeypatch)
    from md20.engine import make_protocol
    wf = _wf(tmp_path)
    case = SimpleNamespace(case_id="c", build_dir=tmp_path, dir=tmp_path)
    wf._plan_long_run("apo", case, make_protocol("teaching", production_ns=10.0), {})            # at the limit: nothing happens
    with pytest.raises(E.UpgradeRequired) as ei:
        wf._plan_long_run("apo", case, make_protocol("teaching", production_ns=20.0), {})
    assert ei.value.feature == "long_run"
    wf.cfg["md"]["long_run"] = {"solute_only": True}
    with pytest.raises(E.UpgradeRequired):
        wf._plan_long_run("apo", case, make_protocol("teaching", production_ns=2.0), {})


def test_the_long_run_planner_is_still_used_in_the_complete_edition(tmp_path, monkeypatch):
    wf = _wf(tmp_path)
    called = []
    import md20.engine.longrun as LR
    monkeypatch.setattr(LR, "needs_plan", lambda ns, lr: called.append(ns) or False)
    from md20.engine import make_protocol
    wf._plan_long_run("apo", SimpleNamespace(case_id="c", build_dir=tmp_path, dir=tmp_path), make_protocol("teaching", production_ns=500.0), {})
    assert called == [500.0]


def test_a_reduced_binding_config_takes_no_window_refinement(tmp_path, lite, monkeypatch):
    monkeypatch.setattr(Workflow, "_run", lambda self, *a, **k: RAN)
    wf = _wf(tmp_path, _accepted())
    _go(wf)
    bc = wf._binding_config(wf.cfg["binding"])
    assert bc.max_refine_rounds == 0 and bc.max_windows == 12
    assert bc.window_prod_ps <= E.limits().max_window_ps
    # the loop of the adaptive refinement runs `range(first, base_round + max_refine_rounds)`: nothing with 0 rounds
    src = (ROOT / "md20" / "sampling" / "binding.py").read_text(encoding="utf-8")
    assert "last = rstate[\"base_round\"] + cfg.max_refine_rounds" in src
    assert list(range(0, 0 + bc.max_refine_rounds)) == []


def test_one_click_actions_refuse_what_the_edition_does_not_take(tmp_path, lite):
    from md20.gui import actions as A
    wf = _wf(tmp_path, _accepted())
    with pytest.raises(A.EditionLimit) as ei:
        A.set_replicas(wf, 3)
    assert isinstance(ei.value, ValueError) and len(ei.value.texts) == 4 and "3" in ei.value.texts[1] and str(ei.value) == ei.value.texts[0]
    with pytest.raises(A.EditionLimit):
        A.resample_range(wf, "BEN", 0.5, 0.9)
    st = wf.state()
    st["steps"]["binding"] = {"status": "PASS", "results": {"BEN": {"status": "PASS", "replicas": 1}}}
    from md20.util import atomic_write_json
    atomic_write_json(st, wf.state_path)
    with pytest.raises(A.EditionLimit) as ei:
        A.add_smd_run(wf, "BEN")
    assert "2" in ei.value.texts[1]
    wf.cfg["ligands"] = [{"name": "A", "smiles": "C"}, {"name": "B", "smiles": "C"}]
    from md20.util import atomic_write_json as w
    w(wf.cfg, wf.dir / "config.json")
    with pytest.raises(A.EditionLimit):
        A.select_screen_ligands(wf, ["C1"])
    assert A.set_replicas(wf, 1)["replicas"] == 1                          # inside the limit it works


def test_one_click_actions_are_unchanged_in_the_complete_edition(tmp_path):
    from md20.gui import actions as A
    wf = _wf(tmp_path)
    assert A.set_replicas(wf, 5)["replicas"] == 5
    assert _saved(wf)["md"]["replicas"] == 5


# ------------------------------------------------------------------------------------------------ decision key, text, gate
def test_the_decision_key_is_carried_by_merge_human_decisions():
    assert ("edition", "accept_clamp") in DECISION_KEYS
    merged, carried = merge_human_decisions({"name": "x", "md": {}}, {"edition": {"accept_clamp": True}})
    assert merged["edition"] == {"accept_clamp": True} and carried == ["edition.accept_clamp"]
    merged, carried = merge_human_decisions({"name": "x", "edition": {"accept_clamp": False}}, {"edition": {"accept_clamp": True}})
    assert merged["edition"]["accept_clamp"] is True                      # a False in the new file does not undo the decision
    merged, carried = merge_human_decisions({"name": "x"}, {"edition": {"accept_clamp": False}})
    assert "edition" not in merged and carried == []


def test_gate_text_has_the_edition_gate_in_four_languages():
    from md20.gui.gate_text import gate_title, gate_general, option_text
    titles = {l: gate_title(E.GATE_NAME, l) for l in LANGS}
    texts = {l: gate_general(E.GATE_NAME, l) for l in LANGS}
    assert len(set(titles.values())) == 4 and len(set(texts.values())) == 4 and all(texts.values())
    for opt in (E.OPT_CLAMP, E.OPT_EDIT, E.OPT_OPEN_IN_FULL, E.OPT_LEARN):
        assert [option_text(opt[0], l) for l in LANGS] == [opt[0], opt[1], opt[2], opt[3]]


def test_the_blocked_workflow_shows_one_card_with_one_button(tmp_path, lite, stub_run):
    from md20.gui.views import gate_cards
    wf = _wf(tmp_path)
    with pytest.raises(WorkflowBlocked):
        _go(wf)
    cards = [c for c in gate_cards(wf, lang="en") if c["title"] == E.GATE_NAME]
    assert len(cards) == 1
    c = cards[0]
    assert len(c["actions"]) == 1 and c["actions"][0]["patch"][0]["path"] == ["edition", "accept_clamp"]
    assert len(c["manual"]) == 3 and "Lite" in c["explanation"]


# ------------------------------------------------------------------------------------------------ the quick preview helper
def test_quick_preview_is_offered_only_with_a_usable_gpu():
    from md20.edition_preview import quick_preview_available as q, NOT_OFFERED
    from md20.env.platforms import PlatformChoice
    assert q(PlatformChoice(name="CUDA", is_gpu=True)) and q({"name": "HIP"}) and q({"name": "Metal"})
    assert not q(PlatformChoice(name="CPU")) and not q({"name": "Reference"}) and not q(None) and not q({}) and not q("CUDA")
    assert q({"name": "OpenCL", "properties": {"DeviceName": "NVIDIA GeForce GTX 1060"}})
    assert not q({"name": "OpenCL", "properties": {"DeviceName": "pthread-Intel(R) Core(TM) i7"}})
    assert not q({"name": "OpenCL", "properties": {}})                     # device unknown: not guessed
    gpu_doctor = {"platform": {"name": "OpenCL", "properties": {}}, "hardware": {"gpus": [{"vendor": "AMD", "name": "RX 580"}]}}
    cpu_doctor = {"platform": {"name": "CPU", "properties": {}}, "hardware": {"gpus": [{"vendor": "NVIDIA", "name": "GTX"}]}}
    assert q(gpu_doctor) and not q(cpu_doctor)                             # a card that OpenMM cannot use does not count
    assert not q({"platform": None, "hardware": {"gpus": []}})
    assert not q({"platform": {"name": "OpenCL", "properties": {}}, "hardware": {"gpus": [{"name": "x", "error": "failed"}]}})
    from md20.env.doctor import DoctorReport
    rep = DoctorReport(hardware={"gpus": []}, packages={}, platform={"name": "CUDA", "properties": {}}, benchmark=None)
    assert q(rep) and not q(DoctorReport(hardware={}, packages={}, platform=None, benchmark=None))
    assert len(NOT_OFFERED) == 4 and all(NOT_OFFERED)


def test_gbn2_still_blocks_binding_and_metal_sites_in_lite(tmp_path, lite):
    cfg = _cfg()
    cfg["md"].update(solvent="gbn2", replicas=1)
    cfg["binding"] = {"enabled": True, "ligands": ["BEN"], "config": {"max_windows": 12, "max_refine_rounds": 0}}
    wf = _wf(tmp_path, cfg)
    assert E.check_config(wf.cfg) == []                                   # the quick preview itself is inside the limits
    with pytest.raises(WorkflowBlocked, match="GBn2"):
        wf.binding({}, {}, PLATFORM)
    gate = wf.state()["steps"]["binding"]["gates"][0]
    assert gate["name"] == "implicit solvent + binding" and gate["status"] == "NEEDS_HUMAN"
    # accepting the reduction leaves the solvent alone
    c2 = _accepted(copy.deepcopy(cfg))
    c2["md"]["replicas"] = 3
    new, changes = E.clamp_config(c2)
    assert new["md"]["solvent"] == "gbn2" and [c["key"] for c in changes] == ["md.replicas"]
    # the metal gate lives in the assembly and is not touched by the edition work
    src = (ROOT / "md20" / "build" / "assemble.py").read_text(encoding="utf-8")
    assert 'Gate("implicit solvent + metal", NEEDS_HUMAN' in src
    assert 'any(pl.get("action") != "remove" for pl in metal_plans)' in src


# ------------------------------------------------------------------------------------------------ the command line
@pytest.fixture
def cli(monkeypatch, tmp_path):
    from md20 import cli as C
    import md20.env as env
    monkeypatch.setattr(env, "choose_platform", lambda *a, **k: PLATFORM)
    C.TMP = tmp_path
    return C


def _write_cfg(tmp_path, cfg, name="cfg.json"):
    p = tmp_path / name
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return p


def test_edition_command_in_the_complete_edition(cli, capsys):
    assert cli.main(["edition"]) == 0
    out = capsys.readouterr().out
    assert "MD20 完整版" in out and "沒有規模上限" in out and "30,000" in out and "只有完整版才有的功能" not in out
    assert cli.main(["edition", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc == E.summary() and doc["edition"] == "full" and doc["locked"] == [] and doc["limits"]["max_atoms"] is None


def test_edition_command_in_lite(cli, lite, capsys):
    assert cli.main(["edition"]) == 0
    out = capsys.readouterr().out
    assert "MD20 Lite（目前）" in out and "只有完整版才有的功能" in out and "HCC Lab" in out
    for f in E.PRO_FEATURES:
        assert E.pick(f.title, "zh") in out
    assert cli.main(["edition", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc == E.summary() and doc["edition"] == "lite" and doc["limits"]["max_atoms"] == 30_000
    assert [f["id"] for f in doc["locked"]] == [f.id for f in E.PRO_FEATURES] and doc["comparison"]


def test_edition_command_has_no_way_to_change_the_edition(cli):
    import argparse
    src = (ROOT / "md20" / "cli.py").read_text(encoding="utf-8")
    block = src[src.index('ed = sub.add_parser("edition"'):].split("\n", 2)[1]
    assert "--json" in block and "--edition" not in src and "MD20_EDITION" not in src
    with pytest.raises(SystemExit):
        cli.main(["edition", "--lite"])


def test_pipeline_run_exit_codes_for_an_edition_stop(cli, lite, stub_run, tmp_path, capsys):
    cfgp = _write_cfg(tmp_path, _cfg())
    base = ["--dir", str(tmp_path / "proj"), "pipeline", "run", str(cfgp), "--project", "pp", "--fake"]
    assert cli.main(base) == cli.EXIT_NEEDS_HUMAN == 3                    # the code of every blocked workflow
    out = capsys.readouterr().out
    assert "[NEEDS_HUMAN]" in out and "MD20 Lite" in out and "accept_clamp" in out and "pose_choices" not in out
    assert stub_run == []
    # the person accepts: the key goes into the config and the same command goes on
    cfg = _cfg()
    cfg["edition"] = {"accept_clamp": True}
    cfgp = _write_cfg(tmp_path, cfg)
    assert cli.main(["--dir", str(tmp_path / "proj"), "pipeline", "run", str(cfgp), "--project", "pp", "--fake"]) == 0
    assert stub_run == [1]
    saved = load_json(tmp_path / "proj" / "pp" / "workflows" / cfg["name"] / "config.json")
    assert saved["md"]["replicas"] == 1 and saved["edition"]["accept_clamp"] is True
    # the original file (no decision in it) is run again later: the decision in config.json is carried
    cfgp = _write_cfg(tmp_path, _cfg(), "orig.json")
    assert cli.main(["--dir", str(tmp_path / "proj"), "pipeline", "run", str(cfgp), "--project", "pp", "--fake"]) == 0
    assert "沿用先前" in capsys.readouterr().out


def test_pipeline_run_in_the_complete_edition_is_unchanged(cli, stub_run, tmp_path, capsys):
    cfgp = _write_cfg(tmp_path, _cfg())
    assert cli.main(["--dir", str(tmp_path / "proj"), "pipeline", "run", str(cfgp), "--project", "pp", "--fake"]) == 0
    out = capsys.readouterr().out
    assert "NEEDS_HUMAN" not in out and "重複" in out                     # the replica plan is still said at the start
    assert stub_run == [1]


def test_pipeline_run_other_blocks_keep_their_own_hint(cli, tmp_path, capsys, monkeypatch):
    def block(self, *a, **k):
        self._block("md_confirm", "x")
    monkeypatch.setattr(Workflow, "_run", block)
    cfgp = _write_cfg(tmp_path, _cfg())
    assert cli.main(["--dir", str(tmp_path / "proj"), "pipeline", "run", str(cfgp), "--project", "pp", "--fake"]) == 3
    assert "pose_choices" in capsys.readouterr().out


def test_resume_reports_an_edition_stop_with_the_same_code(cli, lite, stub_run, tmp_path, capsys):
    cfgp = _write_cfg(tmp_path, _cfg())
    root = ["--dir", str(tmp_path / "proj")]
    assert cli.main(root + ["pipeline", "run", str(cfgp), "--project", "pp", "--fake"]) == 3
    capsys.readouterr()
    assert cli.main(root + ["resume", "--list"]) == 0
    assert "NEEDS_HUMAN" in capsys.readouterr().out
    assert cli.main(root + ["resume", "--include-blocked"]) == 3
    out = capsys.readouterr().out
    assert "[NEEDS_HUMAN]" in out and "accept_clamp" in out
    assert stub_run == []


def test_an_upgrade_required_outside_a_workflow_exits_14_with_the_four_languages(cli, monkeypatch, capsys):
    def fn(a):
        raise E.UpgradeRequired("fold")
    monkeypatch.setattr(cli, "cmd_edition", fn)
    assert cli.main(["edition"]) == cli.EXIT_EDITION == 14
    err = capsys.readouterr().err
    assert all(E.upgrade_text("fold", l) in err for l in LANGS)


def test_autonomy_command_answers_with_the_edition_text(cli, lite, capsys):
    assert cli.main(["--dir", "x", "autonomy", "status"]) == 14            # a Lite licence on a complete package
    assert E.upgrade_text("autonomy", "en") in capsys.readouterr().err


def test_autonomy_command_of_a_lite_package_where_the_module_is_a_stub(cli, monkeypatch, capsys):
    import md20.autonomy.cli as AC

    def register(sub):
        raise E.UpgradeRequired("autonomy")
    monkeypatch.setattr(AC, "register", register)
    assert cli.main(["--dir", "x", "autonomy", "plan", "--anything"]) == 14
    assert E.upgrade_text("autonomy", "zh") in capsys.readouterr().err
    assert cli.main(["edition"]) == 0                                      # the other commands still work


def test_autonomy_command_is_unchanged_in_the_complete_edition(cli, capsys):
    with pytest.raises(SystemExit) as ei:                                  # the real parser answers; the edition does not interfere
        cli.main(["--dir", "x", "autonomy", "status", "--help"])
    assert ei.value.code == 0 and "usage" in capsys.readouterr().out


# ------------------------------------------------------------------------------------------------ nothing else knows what Lite is
@pytest.mark.parametrize("rel", ["md20/workflow.py", "md20/cli.py", "md20/gui/actions.py", "md20/gui/gate_text.py",
                                 "md20/edition_preview.py"])
def test_no_file_decides_the_edition_by_itself(rel):
    src = (ROOT / rel).read_text(encoding="utf-8")
    code = "\n".join(l.split("#")[0] for l in src.splitlines())
    import re
    assert not re.search(r"==\s*['\"]lite['\"]|['\"]lite['\"]\s*==|LITE_FLAG|_edition\.json|MARKER_NAME|environ\[?['\"]MD20_ED", code)
    assert not re.search(r"os\.environ.*(?:EDITION|LITE)|getenv\(.*(?:EDITION|LITE)", code, re.I)
