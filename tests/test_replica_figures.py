"""D-164: the two replica-set figures (ΔRMSF with CI band, DCCM mean and SD) draw from synthetic aggregates; no mdtraj."""
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("matplotlib")

from md20.analysis import replica_set as RS
from md20.report import replica_figs as RF


def _rows(n=30, shift=0.0):
    rng = np.random.default_rng(1)
    res = [f"ALA{i}" for i in range(n)]
    A = [list(np.arange(n) * 0.01 + rng.normal(0, 0.03, n)) for _ in range(3)]
    B = [list(np.arange(n) * 0.01 + shift * (np.arange(n) > 20) + rng.normal(0, 0.03, n)) for _ in range(3)]
    ref = {"residues": res, "per_replica": {f"a{i}": v for i, v in enumerate(A)}}
    oth = {"residues": res, "per_replica": {f"b{i}": v for i, v in enumerate(B)}}
    return RS.delta_rmsf_between_replicas("apo", ref, "cx", oth, {"comparable": True})


def test_delta_rmsf_figure_marks_residues_whose_ci_excludes_zero(tmp_path):
    p = _rows(shift=0.8)
    assert p["status"] == "ok" and p["n_ci_excludes_zero"] >= 5
    png = RF.delta_rmsf_replicas(p["residues"], tmp_path / "d", label="cx")
    assert png and Path(png).is_file()


def test_delta_rmsf_figure_refuses_too_few_residues(tmp_path):
    assert RF.delta_rmsf_replicas([], tmp_path / "d") is None


def test_dccm_figure_with_and_without_sd(tmp_path):
    M = np.corrcoef(np.random.default_rng(0).normal(size=(12, 5)))
    assert Path(RF.dccm_replicas(M.tolist(), (np.abs(M) * 0.1).tolist(), tmp_path / "a")).is_file()
    assert Path(RF.dccm_replicas(M.tolist(), None, tmp_path / "b")).is_file()          # one replica: mean only, no invented spread
    assert RF.dccm_replicas([[1.0]], None, tmp_path / "c") is None
