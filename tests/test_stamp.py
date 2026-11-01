import json
import zipfile
from pathlib import Path

import pytest

from md20.util import stamp as st
from md20.util import atomic_write_json, load_json


def test_zero_width_roundtrip():
    s = "text" + st.zw_encode() + "more"
    assert st.zw_decode(s) == [st.TAG]
    assert "HCC" not in s.replace(st.zw_encode(), "")      # invisible: no readable letters added


def test_json_and_pdb_and_zip_markers(tmp_path: Path):
    p = tmp_path / "a.json"
    atomic_write_json({"x": 1}, p)
    d = load_json(p)
    assert d["x"] == 1 and d["_md20"]["by"] == st.TAG
    f = st.find_markers(p)
    assert "JSON _md20" in f["hidden"] or not d["_md20"].get("p")
    pdb = tmp_path / "x.pdb"
    pdb.write_text("ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\nEND\n")
    st.stamp_pdb_file(pdb); st.stamp_pdb_file(pdb)            # idempotent
    txt = pdb.read_text()
    assert txt.count("REMARK 999 GENERATED") == 1 and txt.splitlines()[-2].startswith("ATOM")
    z = tmp_path / "b.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.comment = st.zip_comment(); zf.writestr("a.txt", "x")
    assert st.find_markers(z)["visible"]


def test_figure_metadata_in_png(tmp_path: Path):
    from md20.analysis.plots import _mpl, _save
    plt = _mpl()
    fig, ax = plt.subplots(); ax.plot([0, 1], [0, 1])
    out = _save(fig, tmp_path / "fig")
    f = st.find_markers(out["png"])
    assert any("PNG" in h for h in f["hidden"])
    assert "HCC Lab" in Path(out["svg"]).read_text(encoding="utf-8")


def test_encrypted_provenance_only_owner_can_read(tmp_path: Path, monkeypatch):
    pytest.importorskip("cryptography")
    priv, pub = st.keygen(tmp_path / "k")
    monkeypatch.setattr(st, "_PUB", pub)
    st.provenance_blob.cache_clear()
    blob = st.provenance_blob()
    assert blob and len(blob) > 300
    rec = st.decrypt_blob(blob, priv)
    assert rec["o"] == "HCCLab" and rec["t"] and len(rec["m"]) == 16
    other, _ = st.keygen(tmp_path / "other")
    with pytest.raises(Exception):
        st.decrypt_blob(blob, other)
    st.provenance_blob.cache_clear()
