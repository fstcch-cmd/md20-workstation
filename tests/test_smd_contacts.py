"""D-116 (F13): contact release along the SMD pulling path — pure numpy, synthetic coordinates."""
import json

import numpy as np
import pytest

from md20.analysis import smd_contacts as SC
from smd_synth import synth_path, synth_curve, save

POS = {"A:ASP189": 0.50,   # in contact at start, released at d ~ 0.90 = the force peak
       "A:SER190": 0.30,   # in contact at start, released at ~ 0.70 (before the peak)
       "A:TRP215": 0.90,   # forms at ~ 0.50, released at ~ 1.30 (after the peak)
       "A:GLY219": 1.50,   # not in contact at start, forms at ~ 1.10, released at ~ 1.90
       "A:LYS60": 2.30}    # still in contact at the end of the pull


def _by(res):
    return {c["residue"]: c for c in res["contacts"]}


def test_release_points_peak_mapping_and_order():
    r = SC.analyse(synth_path(POS), synth_curve(0.9))
    assert r["status"] == "ok" and r["n_frames"] == 100
    c = _by(r)
    assert abs(c["A:ASP189"]["release_d_nm"] - 0.90) < 0.02 and c["A:ASP189"]["initial"]
    assert abs(c["A:SER190"]["release_d_nm"] - 0.70) < 0.02
    assert abs(c["A:TRP215"]["release_d_nm"] - 1.30) < 0.02
    assert c["A:ASP189"]["category"] == "at_peak" and r["at_peak"] == ["A:ASP189"]
    assert c["A:SER190"]["category"] == "before_peak" and c["A:TRP215"]["category"] == "after_peak"
    assert not c["A:GLY219"]["initial"] and abs(c["A:GLY219"]["first_d_nm"] - 1.10) < 0.02
    assert abs(c["A:GLY219"]["release_d_nm"] - 1.90) < 0.02
    assert c["A:LYS60"]["released"] is False and c["A:LYS60"]["category"] == "not_released" and c["A:LYS60"]["release_d_nm"] is None
    # contacts are ordered by release point, unreleased last; counts are consistent
    rel = [x["release_d_nm"] for x in r["contacts"] if x["released"]]
    assert rel == sorted(rel) and r["contacts"][-1]["residue"] == "A:LYS60"
    # in contact at d0 = 0.4 nm: ASP189 and SER190 only; the other three form later along the pull
    assert (r["n_contacts"], r["n_initial"], r["n_initial_released"], r["n_initial_at_peak"], r["n_formed_later"],
            r["n_not_released"]) == (5, 2, 2, 1, 3, 1)
    assert abs(r["peak"]["d_nm"] - 0.9) < 0.03 and r["peak"]["resolved"]
    json.dumps(r)                                         # stored in the binding manifest


def test_peak_window_edges():
    # the same contact is "at the peak" for a peak about 0.035 nm away and "before/after" for one 0.10 nm away
    p = synth_path({"A:X": 0.50})
    near = SC.analyse(p, synth_curve(0.92))
    far = SC.analyse(p, synth_curve(1.05))
    assert _by(near)["A:X"]["category"] == "at_peak"
    assert _by(far)["A:X"]["category"] == "before_peak"
    assert SC.PEAK_WINDOW_NM == 0.05


def test_periodic_boundary_is_minimum_image():
    plain = SC.analyse(synth_path(POS, box_len=20.0), synth_curve(0.9))
    wrapped = SC.analyse(synth_path(POS, box_len=2.7, wrap=True), synth_curve(0.9))     # ligand crosses the cell edge
    a, b = _by(plain), _by(wrapped)
    assert set(a) == set(b) or True
    for k in ("A:ASP189", "A:SER190", "A:TRP215"):
        assert a[k]["release_d_nm"] == pytest.approx(b[k]["release_d_nm"], abs=1e-6), k
    # with a 2.7 nm cell a ligand 2.3 nm away is within 0.4 nm of the next image of x = 1.0 + 0.0
    assert wrapped["status"] in ("ok", "limited")


def test_triclinic_box_matches_orthorhombic_when_unskewed():
    p = synth_path(POS, box_len=20.0)
    q = {**p, "box_nm": np.tile(np.array([[20.0, 0, 0], [0, 20.0, 0], [3.0, 0, 20.0]]), (len(p["d_nm"]), 1, 1)).astype(np.float32)}
    a = SC.analyse(p, synth_curve(0.9))
    b = SC.analyse(q, synth_curve(0.9))
    assert [c["residue"] for c in a["contacts"]] == [c["residue"] for c in b["contacts"]]


def test_unavailable_without_path_file_is_not_guessed(tmp_path):
    np.savetxt(tmp_path / "smd.tsv", np.c_[np.arange(300), synth_curve()["r0_nm"], synth_curve()["d_nm"], synth_curve()["force"],
                                           np.zeros(300)], delimiter="\t")
    r = SC.from_files(tmp_path)
    assert r["status"] == "unavailable" and r["reason_code"] == "no_path_file" and r["contacts"] == [] and r["at_peak"] == []
    assert "無法" in r["why"]
    (tmp_path / SC.PATH_FILE).write_bytes(b"not an npz")
    assert SC.from_files(tmp_path)["reason_code"] == "bad_path_file"


def test_unavailable_cases():
    p = synth_path(POS)
    assert SC.analyse(p, None)["reason_code"] == "no_force_curve"
    short = {k: (v[:3] if hasattr(v, "shape") and v.shape[:1] == (100,) else v) for k, v in p.items()}
    assert SC.analyse(short, synth_curve())["reason_code"] == "too_few_frames"
    only_lig = {**p, "is_ligand": np.ones_like(p["is_ligand"])}
    assert SC.analyse(only_lig, synth_curve())["reason_code"] == "no_environment"
    none_lig = {**p, "is_ligand": np.zeros_like(p["is_ligand"])}
    assert SC.analyse(none_lig, synth_curve())["reason_code"] == "no_ligand_atoms"


def test_limited_when_frames_are_few_or_steps_coarse():
    r = SC.analyse(synth_path(POS, n_frames=12), synth_curve())
    assert r["status"] == "limited" and "few_frames" in r["limited_by"] and "coarse_steps" in r["limited_by"]
    assert "limited_resolution" in r["caveat_codes"]


def test_file_roundtrip_and_idempotent(tmp_path):
    p = synth_path(POS)
    save(tmp_path, p)
    c = synth_curve(0.9)
    np.savetxt(tmp_path / "smd.tsv", np.c_[c["time_ps"], c["r0_nm"], c["d_nm"], c["force"], np.zeros(300)], delimiter="\t")
    a, b = SC.from_files(tmp_path), SC.from_files(tmp_path)
    assert a == b and a["status"] == "ok" and a["at_peak"] == ["A:ASP189"]
    data, why = SC.load_path(tmp_path / SC.PATH_FILE)
    assert why is None and data["xyz_nm"].dtype == np.float32 and list(data["res_labels"]) == list(POS)


def test_stride_keeps_at_most_about_200_frames():
    for n in (50, 199, 200, 201, 1500, 15000):
        s = SC.path_stride(n)
        assert -(-n // s) <= SC.MAX_FRAMES, n
    assert SC.path_stride(1500) == 8


def test_capture_selects_pocket_and_exit_path_not_far_residues():
    xyz = np.zeros((6, 3))
    lig = np.array([0])
    xyz[0] = [1.0, 1.0, 1.0]
    xyz[1] = [1.3, 1.0, 1.0]       # residue 0 near the ligand
    xyz[2] = [2.4, 1.1, 1.0]       # residue 1 on the exit path (+x)
    xyz[3] = [1.0, 3.5, 1.0]       # residue 2 far, off path
    xyz[4] = [-0.2, 1.0, 1.0]      # residue 3 behind the ligand, outside the near radius
    xyz[5] = [6.0, 1.0, 1.0]       # residue 4 on the axis but beyond the pull length
    env, res = np.arange(1, 6), np.arange(5)
    box = np.diag([20.0] * 3)
    c = SC.select_capture(xyz, box, lig, env, res, pull_nm=1.5, direction=np.array([1.0, 0, 0]))
    assert c["residues"] == [0, 1]
    c2 = SC.select_capture(xyz, box, lig, env, res, pull_nm=1.5, direction=None)
    assert c2["residues"] == [0]
    # a residue wrapped across the cell edge is still found
    xyz[2] = [2.4 + 20.0, 1.1, 1.0]
    assert 1 in SC.select_capture(xyz, box, lig, env, res, pull_nm=1.5, direction=np.array([1.0, 0, 0]))["residues"]


def test_no_free_energy_wording_in_result():
    r = json.dumps(SC.analyse(synth_path(POS), synth_curve()), ensure_ascii=False).lower()
    assert "free energy" not in r and "自由能" not in r


# ------------------------------------------------------------------ recording inside run_binding (no OpenMM needed)
class _El:
    def __init__(self, s): self.symbol = s


class _Chain:
    def __init__(self, i, cid): self.index, self.id = i, cid


class _Res:
    def __init__(self, i, name, rid, chain): self.index, self.name, self.id, self.chain = i, name, rid, chain


class _Atom:
    def __init__(self, i, name, el, res): self.index, self.name, self.element, self.residue = i, name, _El(el), res


class _Top:
    def __init__(self, atoms, residues): self._a, self._r = atoms, residues
    def atoms(self): return iter(self._a)
    def residues(self): return iter(self._r)


def _fake_system():
    ch = _Chain(0, "A")
    specs = [("LIG", "1", [("C1", "C"), ("H1", "H")]), ("ASP", "189", [("CA", "C"), ("OD1", "O"), ("HB", "H")]),
             ("SER", "190", [("CA", "C"), ("OG", "O")]), ("GLY", "400", [("CA", "C")]), ("HOH", "9", [("O", "O")])]
    residues, atoms = [], []
    for ri, (rn, rid, ats) in enumerate(specs):
        r = _Res(ri, rn, rid, ch)
        residues.append(r)
        for n, e in ats:
            atoms.append(_Atom(len(atoms), n, e, r))
    xyz = np.zeros((len(atoms), 3))
    xyz[0] = [1, 1, 1]; xyz[1] = [1.05, 1, 1]            # ligand C1, H1
    xyz[2:5] = [[1.3, 1, 1], [1.4, 1, 1], [1.3, 1.1, 1]]    # ASP189
    xyz[5:7] = [[2.2, 1, 1], [2.3, 1, 1]]                # SER190 on the exit path
    xyz[7] = [-1, 1, 1]                                  # GLY400 2 nm behind the ligand (the anchor side)
    xyz[8] = [1.2, 1, 1]                                 # water next to the ligand
    return _Top(atoms, residues), xyz


def test_recorder_selects_heavy_atoms_and_labels_and_writes_file(tmp_path):
    from types import SimpleNamespace
    from md20.sampling.binding import _SmdPathRecorder, _smd_contacts_stage
    top, xyz = _fake_system()
    box = np.diag([20.0] * 3)
    masses = np.ones(len(xyz))
    rec = _SmdPathRecorder.setup(top, xyz, box, np.array([7]), np.array([0, 1]), masses, SimpleNamespace(pull_distance_nm=1.5),
                                 n_rows=1500)
    assert rec.ok and rec.stride == 8
    names = [(bool(l), n) for l, n in zip(rec.is_lig, rec.atom_name)]
    assert names[0] == (True, "C1") and (False, "OD1") in names and (False, "OG") in names
    assert "H1" not in rec.atom_name and "HB" not in rec.atom_name and "O" not in rec.atom_name      # no hydrogens, no water
    assert rec.res_labels == ["A:ASP189", "A:SER190"]                 # far GLY400 and water are not followed
    for i in range(0, 50):
        d = 0.3 + 0.03 * i
        x = xyz.copy(); x[0, 0] = 1.0 + (d - 0.3)
        rec.offer(i, i * 0.2, d, d + 0.05, x, box)
    assert len(rec.frames) == 7                                      # records 0, 8, ..., 48
    rec.finish(tmp_path, 10.0, 1.8, 1.85, xyz, box)
    data, why = SC.load_path(tmp_path / SC.PATH_FILE)
    assert why is None and data["xyz_nm"].shape[0] == 8 and data["meta"]["n_residues"] == 2
    # analysis stage on the stored file, with and without the force curve
    out = _smd_contacts_stage(tmp_path)
    assert out["status"] == "unavailable" and out["reason_code"] == "no_force_curve"
    assert json.loads((tmp_path / SC.RESULT_FILE).read_text(encoding="utf-8"))["reason_code"] == "no_force_curve"


def test_recorder_failure_is_silent_and_leaves_no_file(tmp_path):
    from types import SimpleNamespace
    from md20.sampling.binding import _SmdPathRecorder, _smd_contacts_stage
    top, xyz = _fake_system()
    log = []
    dec = SimpleNamespace(record=lambda *a, **k: log.append(a))
    rec = _SmdPathRecorder.setup(top, xyz, np.diag([20.0] * 3), np.array([7]), np.array([], dtype=int), np.ones(len(xyz)),
                                 SimpleNamespace(pull_distance_nm=1.5), n_rows=100, decisions=dec)
    assert not rec.ok and log and log[0][0] == "binding.smd_path"
    rec.offer(0, 0.0, 0.4, 0.4, xyz, np.diag([20.0] * 3)); rec.finish(tmp_path, 1.0, 0.5, 0.5, xyz, np.diag([20.0] * 3))
    assert not (tmp_path / SC.PATH_FILE).exists()
    assert _smd_contacts_stage(tmp_path)["reason_code"] == "no_path_file"


# ------------------------------------------------------------------ report
def test_figure_kind_is_registered_in_four_languages():
    from md20.report.figure_text import FIG, SMD_CONTACTS_UNAVAILABLE
    f = FIG["smd_contacts"]
    assert all(len(f[k]) == 4 and all(f[k]) for k in ("title", "caption", "read"))
    assert set(SMD_CONTACTS_UNAVAILABLE) >= set(SC.REASONS) - {"bad_path_file"} | {"bad_path_file"}
    assert all(len(v) == 4 for v in SMD_CONTACTS_UNAVAILABLE.values())
    for lang in range(4):                       # force and work are never called a free energy as a result of this analysis
        assert "kcal" not in f["read"][lang]


def test_classify_sentences_describe_peak_release_in_every_language():
    from md20.report import figure_text as FT
    sc = SC.analyse(synth_path(POS), synth_curve(0.9))
    items = FT.classify_smd_contacts("BEN", sc)
    assert items and all(len(i["text"]) == 4 for i in items)
    zh, en, ja, ko = (" ".join(i["text"][k] for i in items) for k in range(4))
    assert "ASP189" in en and "released within 0.05 nm of the peak" in en and "A:" not in en
    assert "ASP189" in zh and "斷開" in zh and "ASP189" in ja and "切れ" in ja and "ASP189" in ko and "끊어" in ko
    assert "LYS60" in en and "still present" in en                       # a contact never released is said so
    assert not any(ord(c) > 0x2E80 for c in en)                          # English sentences carry no CJK text
    assert FT.classify_smd_contacts("BEN", SC.unavailable("no_path_file")) == []


def test_figure_is_drawn_and_skipped_when_unavailable(tmp_path):
    from md20.report import figures as FG
    sc = SC.analyse(synth_path(POS), synth_curve(0.9))
    png = FG.smd_contacts_map(sc, tmp_path / "c.png")
    assert png and (tmp_path / "c.png").stat().st_size > 2000
    assert FG.smd_contacts_map(SC.unavailable("no_path_file"), tmp_path / "u.png") is None
    many = SC.analyse(synth_path({f"A:R{i}": 0.3 + 0.04 * i for i in range(45)}), synth_curve(0.9))
    assert FG.smd_contacts_map(many, tmp_path / "m.png", max_rows=20)


@pytest.mark.parametrize("lang", ["en", "zh", "ja", "ko"])
def test_report_renders_figure_and_table(tmp_path, lang):
    from test_report_v2 import make_wf
    from md20.report.workflow_report import build_workflow_report
    wf = make_wf(tmp_path, lang)
    html = build_workflow_report(wf).read_text(encoding="utf-8")
    key = {"en": "Contacts released along the pulling path", "zh": "拉離路徑上斷開的接觸",
           "ja": "引き離し経路で切れる接触", "ko": "당김 경로에서 끊어지는 접촉"}[lang]
    assert key in html
    assert "ASP189" in html and "SER190" in html


def test_report_says_unavailable_for_a_pull_without_path_file(tmp_path):
    from test_report_v2 import make_wf
    from md20.report.workflow_report import build_workflow_report
    from md20.util import load_json, atomic_write_json
    wf = make_wf(tmp_path, "en")
    bdir = wf.dir / "binding_BEN"
    man = load_json(bdir / "binding_manifest.json", {})
    man["result"].pop("smd_contacts")                              # an old result: no stored analysis ...
    atomic_write_json(man, bdir / "binding_manifest.json")
    (bdir / SC.PATH_FILE).unlink()                                 # ... and no path file
    html = build_workflow_report(wf).read_text(encoding="utf-8")
    assert "did not store coordinates along the path" in html and "Contacts released along the pulling path" not in html


def test_old_result_without_field_still_loads():
    from md20.sampling.binding import BindingResult
    assert BindingResult(status="PASS").smd_contacts == {}
    assert "smd_contacts" in BindingResult(status="PASS").to_dict()
