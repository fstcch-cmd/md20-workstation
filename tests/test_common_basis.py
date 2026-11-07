"""D-106 (A11/F12/F10): common PCA basis across systems, half-split check, comparability, residue-matched ΔRMSF."""
import numpy as np


def _rot(rng):
    q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    return q * np.sign(np.linalg.det(q))


def _system(rng, n_frames, states, n_res=30, drop=(), switch_at=None):
    base = np.c_[np.arange(n_res) * 3.8, np.zeros(n_res), np.zeros(n_res)]
    mode = np.zeros((n_res, 3)); mode[n_res // 2:, 1] = 2.0           # second half of the chain swings
    xyz = []
    for f in range(n_frames):
        if switch_at is not None:
            s = 0 if f < switch_at else 1
        else:
            s = states[f % len(states)]
        x = base + s * mode + rng.normal(0, 0.15, base.shape)
        xyz.append(x @ _rot(rng).T + rng.normal(0, 5, 3))              # arbitrary orientation per frame
    labels = [f"A:{i + 1}" for i in range(n_res)]
    keep = [i for i in range(n_res) if i not in drop]
    return {"labels": [labels[i] for i in keep], "xyz": np.array(xyz)[:, keep, :], "time_ns": list(np.arange(n_frames) * 0.04)}


def test_common_basis_puts_systems_on_the_same_axes():
    from md20.analysis.common_basis import common_basis
    rng = np.random.default_rng(0)
    sysd = {"apo": _system(rng, 200, [0, 1]), "docked_L01": _system(rng, 200, [0], drop=(3,))}
    r = common_basis(sysd)
    assert r["status"] == "ok" and r["n_common_ca"] == 29                # residue 4 missing in the complex
    assert r["explained"][0] > 0.3                                       # the swing dominates the noise
    la = r["per_system"]["apo"]["landscape"]; lb = r["per_system"]["docked_L01"]["landscape"]
    assert la["xedges"] == lb["xedges"] == r["xedges"]                    # same bins
    assert len(la["basins"]) == 2 and len(lb["basins"]) == 1
    reps = [x for x in r["representatives"] if x["system"] == "apo"]
    assert len(reps) == 2 and all(0 <= x["frame"] < 200 for x in reps)
    assert r["per_system"]["apo"]["half_split"]["consistent"]


def test_half_split_flags_a_system_that_changed_state_midway():
    from md20.analysis.common_basis import common_basis
    rng = np.random.default_rng(1)
    r = common_basis({"apo": _system(rng, 200, [0, 1]), "holo": _system(rng, 200, [0], switch_at=100)})
    hs = r["per_system"]["holo"]["half_split"]
    assert hs["status"] == "ok" and not hs["consistent"] and hs["max_change"] > 0.5


def test_common_basis_refuses_too_little_overlap():
    from md20.analysis.common_basis import common_basis
    rng = np.random.default_rng(2)
    a = _system(rng, 50, [0]); b = _system(rng, 50, [0])
    b["labels"] = [f"B:{i}" for i in range(len(b["labels"]))]
    assert common_basis({"a": a, "b": b})["status"] == "insufficient"
    assert common_basis({"a": a})["status"] == "insufficient"


def test_conditions_and_comparability():
    from md20.analysis.common_basis import conditions, comparability
    run = {"protocol": {"hmr": True, "stages": [{"name": "production", "temperature_k": 300.0, "ensemble": "NPT", "length_ps": 10000,
                                                 "timestep_fs": 4.0, "restraint_groups": {"backbone": [0.0, 0.0]}}]}}
    bm = {"forcefields": ["amber14-all.xml", "amber14/tip3pfb.xml"], "solvent": "explicit"}
    holo_bm = {"assembly": {"forcefields": ["amber14-all.xml", "amber14/tip3pfb.xml", "openff-2.1.0 (L01)"], "solvent": "explicit"}}
    assert conditions(run, holo_bm)["forcefield"] == conditions(run, bm)["forcefield"]     # ligand generator ignored
    assert conditions(run, bm)["water_model"] == "amber14/tip3pfb.xml"
    assert conditions(run, {"forcefields": ["amber14-all.xml", "implicit/gbn2.xml"], "solvent": "gbn2"})["water_model"] == "gbn2"
    c1 = conditions(run, bm)
    assert c1["restrained"] == [] and c1["temperature_k"] == 300.0
    run2 = {"protocol": {**run["protocol"], "stages": [{**run["protocol"]["stages"][0], "temperature_k": 310.0,
                                                        "restraint_groups": {"backbone": [0.05, 0.05]}}]}}
    c2 = conditions(run2, bm)
    ok = comparability({"apo": c1, "holo": dict(c1)})
    assert ok["comparable"]
    bad = comparability({"apo": c1, "holo": c2})
    assert not bad["comparable"] and {d["field"] for d in bad["differences"]} == {"temperature_k", "restrained"}
    unk = comparability({"apo": c1, "holo": {**c1, "water_model": None}})
    assert not unk["comparable"] and unk["unknown"] == ["water_model"]   # unknown is never assumed equal
    long = comparability({"apo": c1, "holo": {**c1, "production_ps": 20000}})
    assert not long["comparable"]


def test_delta_rmsf_matches_by_residue_and_refuses_when_not_comparable():
    from md20.analysis.common_basis import delta_rmsf
    from md20.analysis.traj import residue_keys
    assert residue_keys(["HIE57", "ALA58", "HIS57"]) == ["HIS57", "ALA58", "HIS57#2"]
    apo = (residue_keys(["ALA1", "HID2", "GLY3", "SER4", "LEU5", "VAL6"]), [1.0, 2.0, 1.0, 1.0, 1.0, 1.0])
    holo = (residue_keys(["HIE2", "GLY3", "SER4", "LEU5", "VAL6"]), [0.5, 1.0, 1.0, 1.0, 1.5])   # residue 1 missing
    r = delta_rmsf(apo, holo, {"comparable": True})
    assert r["status"] == "ok" and r["most_rigidified"][0] == {"residue": "HIS2", "delta_rmsf_A": -1.5}
    assert r["most_flexible"][0]["residue"] == "VAL6"
    no = delta_rmsf(apo, holo, {"comparable": False, "differences": [{"field": "temperature_k"}], "unknown": []})
    assert no["status"] == "not_comparable"
