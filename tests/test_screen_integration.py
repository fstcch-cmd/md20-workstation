"""HTS screen end-to-end on 3PTB with real downloads (PubChem / RCSB), real RDKit checks and real Vina.
Runs only in the openmm-stack CI job (vina + meeko + rdkit); everything else is covered by the pure tests."""
import os

import pytest

pytest.importorskip("rdkit")
pytest.importorskip("meeko")
pytest.importorskip("pdbfixer")
try:
    import vina  # noqa: F401
except ImportError:
    from md20.docking.vina_cli import ensure_vina_exe
    try:
        ensure_vina_exe()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Vina unavailable: {exc}", allow_module_level=True)

from md20.docking.library import read_library, resolve_library, LibraryFilters
from md20.project.store import Project
from md20.workflow import Workflow, WorkflowBlocked, example_config


def _library(tmp_path):
    p = tmp_path / "lib.csv"
    p.write_text("name,smiles,pubchem_cid,inchikey,ccd\n"
                 "benzamidine_smi,NC(=[NH2+])c1ccccc1,,,\n"
                 "aminobenzamidine,,7638,,\n"                       # 4-aminobenzamidine (trypsin ligand)
                 "aspirin,,2244,,\n"
                 "caffeine,,,RYYVLZVUVIJVGH-UHFFFAOYSA-N,\n"
                 "atp_ccd,,,,ATP\n"
                 "sodium_benzoate,[Na+].[O-]C(=O)c1ccccc1,,,\n"     # salt → largest fragment kept
                 "too_small,C,,,\n", encoding="utf-8")              # filtered out (heavy atoms < 5)
    return p


def test_library_resolve_real_sources(tmp_path):
    ents, problems = read_library(_library(tmp_path))
    assert not problems
    try:
        man = resolve_library(ents, tmp_path / "lib", filters=LibraryFilters(), workers=3)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"network: {exc}")
    e = man["entries"]
    net_ok = [n for n in ("aminobenzamidine", "aspirin", "caffeine", "atp_ccd") if e[n]["status"] == "OK"]
    if len(net_ok) < 2:
        pytest.skip(f"network sources unreachable: { {n: e[n].get('error') for n in e} }")
    assert e["benzamidine_smi"]["status"] == "OK" and e["benzamidine_smi"]["checked"] and e["benzamidine_smi"]["heavy_atoms"] == 9
    assert e["too_small"]["status"] == "SKIPPED" and "重原子" in e["too_small"]["error"]
    assert e["sodium_benzoate"]["status"] == "OK" and e["sodium_benzoate"]["salt_stripped"] and e["sodium_benzoate"]["heavy_atoms"] == 9
    for n in net_ok:
        assert e[n]["inchikey"] and e[n]["mw"] > 100
    if e["caffeine"]["status"] == "OK":
        assert e["caffeine"]["inchikey"] == "RYYVLZVUVIJVGH-UHFFFAOYSA-N" and e["caffeine"]["pubchem_cid"] == "2519"


def test_screen_workflow_3ptb(tmp_path, pdb_3ptb):
    """Screen 4 small compounds into the benzamidine box (exhaustiveness 2), pick two, continue to real docking."""
    lib = tmp_path / "lib.csv"
    lib.write_text("name,smiles,pubchem_cid\nbenzamidine_smi,NC(=[NH2+])c1ccccc1,\naminobenzamidine,,7638\n"
                   "phenol,Oc1ccccc1,\nbenzoate,[O-]C(=O)c1ccccc1,\n", encoding="utf-8")
    cfg = example_config(screen=True)
    cfg.update({"name": "screen3ptb", "receptor": {"file": str(pdb_3ptb)},
                "md": {"systems": ["docked_single"], "tier": "classroom", "replicas": 1, "padding_nm": 1.0},
                "binding": {"enabled": False, "ligands": [], "config": {}}})
    cfg["screen"].update({"library": str(lib), "exhaustiveness": 2, "n_poses": 3, "allow_partial": True})
    cfg["docking"]["exhaustiveness"] = 2
    wf = Workflow(Project.create(tmp_path, "p"), cfg)
    raw = wf.fetch_receptor()
    clean = wf.prepare_docking_receptor(raw)
    with pytest.raises(WorkflowBlocked, match="勾選"):
        wf.apply_screen(clean, raw)
    st = wf.state()["steps"]
    assert st["screen_docking"]["status"] == "PASS"
    from md20.docking.screen import rank_screen
    from md20.util import load_json
    rows = rank_screen(load_json(st["screen_docking"]["results"]))
    names = [r["name"] for r in rows]
    assert len(rows) >= 3, st["screen_docking"].get("failed")
    assert all(r["score"] < 0 for r in rows) and all(r["ligand_efficiency"] for r in rows)
    assert "benzamidine_smi" in names[:2] or "aminobenzamidine" in names[:2]     # amidines must beat phenol in the S1 pocket
    assert (wf.dir / "screen" / "plots" / "screen_top.png").is_file()
    wf.cfg["screen"].update({"select": names[:2], "next_mode": "independent"})
    assert wf.apply_screen(clean, raw) is True
    assert [l["name"] for l in wf.cfg["ligands"]] == ["BEN"] + names[:2]
    res = wf.run_docking(clean, raw)                                              # real docking of the merged list
    assert {e["name"] for e in res.entries} == {"BEN", *names[:2]}
    ben = res.entry("BEN")
    assert ben["redock_rmsd"] is not None and ben["redock_rmsd"] < 2.0
