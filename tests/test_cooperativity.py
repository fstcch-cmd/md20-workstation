"""D-61: binding cooperativity from the thermodynamic cycle — closure first, then significance."""
import pytest

from md20.sampling.multi import cooperativity
from md20.report.figure_text import classify_cooperativity


def _res(a_alone, a_with, b_alone, b_with, err=1.0, dG=False):
    key = "dG_standard_kj_mol" if dG else "delta_pmf_kj_mol"
    ekey = "dG_err_kj_mol" if dG else "delta_pmf_err_kj_mol"
    r = {}
    for k, lig, v in (("A", "A", a_alone), ("B", "B", b_alone), ("multi:A", "A", a_with), ("multi:B", "B", b_with)):
        r[k] = {"status": "PASS", "ligand": lig, key: v, ekey: err, "delta_pmf_kj_mol": v, "delta_pmf_err_kj_mol": err}
        if not dG:
            r[k]["dG_standard_kj_mol"] = None
    return r, {"single": ["A", "B"], "multi:docked_multi": ["multi:A", "multi:B"]}


def test_positive_cooperativity_from_pmf_depths():
    r, ctx = _res(20, 25, 15, 20.5)                 # both wells deeper with the partner → −ΔΔPMF ≈ −5
    c = cooperativity(r, ctx)[0]
    assert c["status"] == "COOPERATIVE" and c["coop_kj_mol"] == pytest.approx(-5.25) and abs(c["closure_kj_mol"]) == pytest.approx(0.5)
    assert "qualitative" in c["why"][1] and classify_cooperativity(c)[0]["level"] == "note"


def test_cycle_that_does_not_close_is_not_interpreted():
    r, ctx = _res(20, 30, 15, 14)                   # one leg says +10 stronger, the other −1: path dependence
    c = cooperativity(r, ctx)[0]
    assert c["status"] == "NOT_CLOSED" and "does not close" in c["why"][1] and classify_cooperativity(c)[0]["level"] == "warn"


def test_no_detectable_effect_and_competition_with_dG():
    r, ctx = _res(-30, -30.5, -25, -25.2, err=1.0, dG=True)
    assert cooperativity(r, ctx)[0]["status"] == "NONE"
    r, ctx = _res(-30, -22, -25, -17.5, err=1.0, dG=True)      # each binds ~8 kJ/mol more weakly with the other
    c = cooperativity(r, ctx)[0]
    assert c["status"] == "ANTICOOPERATIVE" and c["quantity"].startswith("ΔΔG")


def test_missing_single_leg_and_missing_errors():
    r, ctx = _res(20, 25, 15, 20.5)
    del r["B"]
    c = cooperativity(r, {"single": ["A"], "multi:docked_multi": ["multi:A", "multi:B"]})[0]
    assert c["status"] == "INSUFFICIENT" and "B" in c["missing"]
    r, ctx = _res(20, 25, 15, 20.5, err=None)
    c = cooperativity(r, ctx)[0]
    assert c["status"] == "UNCERTAIN"
    r, ctx = _res(20, 30, 15, 16, err=None)          # no errors: 4 kJ/mol fallback closure limit
    assert cooperativity(r, ctx)[0]["status"] == "NOT_CLOSED"
