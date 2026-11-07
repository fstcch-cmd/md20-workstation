"""D-97: the report shows the multi-label fingerprint, the persistence table, initial-vs-new contacts and an explicit
'unavailable' line for missing water — all from the numerical outputs of analysis/interactions.py (no hand-made values)."""
import json

import numpy as np

from md20.analysis import interactions as IX
from md20.analysis.extended import _persistence
from md20.report.workflow_report import build_workflow_report
from tests.test_report_v2 import make_wf


def _fp():
    F = 30
    X = np.full((F, 15, 3), 50.0)
    X[:, 0] = 0
    X[:, 12] = [0.3, 0, 0]                                       # LYS NZ next to the ligand O all the time
    X[:, 14] = [0, 0.3, 0]; X[12:14, 14] = [0, 2.0, 0]           # SER OG: polar contact with a two-frame break
    atoms = {0: {"element": "O"},
             12: {"element": "N", "resname": "LYS", "name": "NZ", "res_key": IX.residue_key("A", "LYS", 60)},
             14: {"element": "O", "resname": "SER", "name": "OG", "res_key": IX.residue_key("A", "SER", 190)}}
    fp = IX.fingerprint(IX.dynamic_pairs(X, [0], [12, 14]), atoms, ligand_charges={0: -1}, time_ps=np.arange(F) * 20.0)
    fp["time_ns"] = [t / 1000 for t in fp["time_ps"]]
    fp["display_labels"] = IX.display_labels(fp["residues"])
    fp["matrix"] = IX.legacy_matrix(fp)
    fp["initial_vs_new"] = IX.initial_vs_new(fp)
    fp["persistence"] = _persistence(fp)
    return fp


def test_report_shows_persistence_and_unavailable_water(tmp_path):
    wf = make_wf(tmp_path, "en")
    p = wf.dir / "x_docked_BEN.json"
    e = json.loads(p.read_text(encoding="utf-8"))
    e["ligands"]["L01"]["fingerprint"] = _fp()
    e["ligands"]["L01"]["water_bridges"] = IX.water_unavailable("no water coordinates in this trajectory")
    p.write_text(json.dumps(e), encoding="utf-8")
    html = build_workflow_report(wf).read_text(encoding="utf-8")
    assert "interaction persistence (continuous definition, stored frames; not ligand residence time or k_off)" in html
    assert "salt bridge" in html and "polar proximity (distance only)" in html
    assert "water-bridge analysis unavailable" in html and "no water coordinates" in html
    assert "Losing an initial docking contact does not by itself make a pose worse" in html
    fp = _fp()
    ser = [i for i in fp["persistence"]["items"] if i["residue"] == "A:SER190"][0]
    assert ser["n_events"] == 2 and ser["events"][0]["left_censored"] and ser["events"][1]["right_censored"]
    assert ser["lifetime_ps"] is None                         # both events censored → no lifetime, and the reason is shown
    assert "uncensored event" in html
