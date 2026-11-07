"""D-54: general figure language — every figure kind is bilingual and every scenario of the spec is reachable."""
import numpy as np

from md20.report import figure_text as FT

T = np.linspace(0, 10, 200)


def _en(fs):
    return " ".join(f["text"][1] for f in fs)


def test_every_kind_bilingual_and_in_spec():
    spec = open("docs/specs/report_language.md", encoding="utf-8").read()
    for k, f in FT.FIG.items():
        for part in ("title", "caption", "read"):
            zh, en, ja, ko = f[part]                                   # D-74: four languages
            assert zh and en and ja and ko and zh != en, (k, part)
            assert ja != en and ko != en, (k, part)
        assert f"`{k}`" in spec, k                                     # every figure kind is specified in the spec


def test_docking_scenarios():
    poses = lambda gap, cs: ([{"rank": 1, "score": -8.0, "cluster": 1, "cluster_size": cs}, {"rank": 2, "score": -8.0 + gap, "cluster": 2, "cluster_size": 1}]  # noqa: E731
                             + [{"rank": r, "score": -5.0, "cluster": r, "cluster_size": 1} for r in range(3, 11)])
    assert "binding mode is clear" in _en(FT.classify_docking_scores("A", poses(1.5, 4), 1))
    assert "equivalent within Vina" in _en(FT.classify_docking_scores("A", poses(0.3, 6), 1))
    assert "did not converge" in _en(FT.classify_docking_scores("A", poses(1.5, 2), 1))


def test_screen_scenarios():
    rows = [{"name": f"c{i}", "score": -9 + 0.2 * i, "heavy_atoms": 40 - i} for i in range(8)]
    e = _en(FT.classify_screen(rows))
    assert "within 1 kcal" in e and "mostly reflects molecular size" in e
    assert "clear first choice" in _en(FT.classify_screen([{"name": "a", "score": -10}, {"name": "b", "score": -8}]))


def test_rmsd_rg_scenarios():
    flat = 1.2 + 0.0 * T
    s = _en(FT.classify_rmsd({"apo": (T, flat + 0.5), "holo": (T, flat), "drift": (T, 1 + 0.2 * T), "big": (T, flat + 2.5)}))
    assert "levels off below 2 Å" in s and "has not equilibrated" in s and "rearranged substantially" in s
    assert "stabilises the protein" in s
    assert "expands markedly" in _en(FT.classify_rg({"x": (T, 15 + 0.2 * T)}))
    assert "compactly folded" in _en(FT.classify_rg({"x": (T, 15 + 0 * T)}))


def test_ligand_contacts_scenarios():
    assert "keeps the docked pose" in _en(FT.classify_ligand_rmsd("k", "L", T, 1 + 0 * T))
    out = 1 + (T > 6) * 5.0
    assert "left the docked position" in _en(FT.classify_ligand_rmsd("k", "L", T, out)) and "from about 6" in _en(FT.classify_ligand_rmsd("k", "L", T, out))
    blip = 1 + ((T > 3) & (T < 3.5)) * 3.0
    assert "fluctuation within the bound state" in _en(FT.classify_ligand_rmsd("k", "L", T, blip))
    assert "adjusts its pose" in _en(FT.classify_ligand_rmsd("k", "L", T, 2.5 + 0 * T))
    assert "persistent anchor" in _en(FT.classify_contacts("k", "L", {"A": .9, "B": .8, "C": .8}))
    assert "relies on few" in _en(FT.classify_contacts("k", "L", {"A": .9, "B": .3}))
    assert "binds loosely" in _en(FT.classify_contacts("k", "L", {"A": .4}))


def test_rmsf_smd_pmf_scenarios():
    names = [f"R{i}" for i in range(50)]
    ref = np.ones(50)
    assert "most rigid" in _en(FT.classify_rmsf(names, ref, ref - 0.5 * (np.arange(50) < 3), "holo"))
    t = _en(FT.classify_rmsf(names, ref, ref + 0.3, "holo"))      # D-138 (R6): observation, not a causal claim
    assert "flexibility is higher with the ligand" in t and "not a causal conclusion" in t and "less stable" not in t
    pos = np.linspace(0.4, 2.0, 300)
    two = 500 * np.exp(-((pos - 0.7) / 0.08) ** 2) + 450 * np.exp(-((pos - 1.2) / 0.08) ** 2)
    work = np.cumsum(two) * (pos[1] - pos[0])
    assert "detaches in stages" in _en(FT.classify_smd(pos, two, work, "L")) and "fully detached" in _en(FT.classify_smd(pos, two, work, "L"))
    ramp = np.full(300, 200.0)
    assert "may not have fully detached" in _en(FT.classify_smd(pos, ramp, np.cumsum(ramp), "L"))
    g = np.linspace(0.4, 2.0, 50)
    flat = 30 * (1 - np.exp(-((g - 0.4) / 0.3) ** 2))
    assert "end of the profile is flat" in _en(FT.classify_pmf(g, flat, None, "L"))
    assert "still slopes" in _en(FT.classify_pmf(g, 20 * g, None, "L"))
    assert "implausible" in _en(FT.classify_pmf(g, 3 * flat, None, "L"))
    assert "gaps at" in _en(FT.classify_umbrella({"continuous": False, "breaks": [[0.9, 1.0]]}, "L"))
